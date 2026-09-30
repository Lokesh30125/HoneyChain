"""Phase 4 — the AI HTTP surface: insights, alerts, permissions and audit.

The engine's own behaviour is covered in ``test_ai_engine.py``; this file is about
everything wrapped around it — the read-through policy, the alert lifecycle, the
scoping rules that stop one beekeeper seeing another's assessment, and the audit
trail that makes a run accountable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ai_alert import AiAlert
from app.models.ai_analysis import HiveAiAnalysis
from app.models.audit_log import AuditLog
from app.models.enums import AiAlertStatus, AuditAction
from app.services.ai_alert_service import dedupe_key_for
from app.services.ai_service import AiService

API = "/api/v1"

HIVE = {"village": "Tenali", "district": "Guntur", "state": "Andhra Pradesh"}


def make_hive(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post(f"{API}/hives", headers=headers, json={**HIVE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def make_device(client: TestClient, headers: dict, hive_id: str, device_id: str | None = None) -> dict:
    response = client.post(
        f"{API}/iot/devices",
        headers=headers,
        json={
            "device_id": device_id or f"ESP32-P4-{uuid.uuid4().hex[:5].upper()}",
            "device_name": "Phase-4 test node",
            "hive_id": hive_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def post_window(
    client: TestClient,
    headers: dict,
    device_id: str,
    *,
    samples: int = 10,
    spread_hours: float = 4,
    ends_minutes_ago: float = 0,
    temperature: float = 33.6,
    humidity: float = 58.0,
    weight: float = 40.0,
    vibration: float = 0.7,
    acoustic: float = 42.0,
) -> int:
    """Post a backdated telemetry window; returns how many rows were stored.

    ``ends_minutes_ago`` shifts the whole window into the past, which is how the
    "new telemetry arrived" policy is exercised without waiting.
    """
    now = datetime.now(timezone.utc) - timedelta(minutes=ends_minutes_ago)
    step = timedelta(hours=spread_hours) / max(1, samples - 1)
    stored = 0
    for index in range(samples):
        moment = now - step * (samples - 1 - index)
        response = client.post(
            f"{API}/iot/telemetry",
            headers=headers,
            json={
                "device_id": device_id,
                "timestamp": moment.isoformat(),
                "temperature": temperature + (index % 3) * 0.2,
                "humidity": humidity + (index % 4) * 0.3,
                "weight": weight + index * 0.02,
                "vibration": vibration + (index % 2) * 0.05,
                "acoustic_level": acoustic + (index % 3) * 0.5,
                "battery_level": 88,
                "signal_strength": -63,
                "source": "SIMULATOR",
            },
        )
        assert response.status_code == 201, response.text
        stored += 1
    return stored


class TestPermissions:
    def test_authentication_is_required(self, client: TestClient):
        assert client.get(f"{API}/ai/summary").status_code == 401
        assert client.get(f"{API}/ai/alerts").status_code == 401
        assert client.post(f"{API}/ai/analyze", json={}).status_code == 401

    def test_a_consumer_is_refused_the_whole_module(self, client: TestClient, consumer_headers: dict):
        endpoints = [
            ("get", f"{API}/ai/summary"),
            ("get", f"{API}/ai/hives"),
            ("get", f"{API}/ai/alerts"),
            ("get", f"{API}/ai/alerts/summary"),
            ("post", f"{API}/ai/analyze"),
        ]
        for method, path in endpoints:
            call = getattr(client, method)
            response = (
                call(path, headers=consumer_headers, json={})
                if method == "post"
                else call(path, headers=consumer_headers)
            )
            assert response.status_code == 403, f"{method} {path} -> {response.status_code}"

    def test_a_beekeeper_can_read_their_own_overview(self, client: TestClient, auth_headers: dict):
        response = client.get(f"{API}/ai/summary", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["total_hives"] == 0
        assert body["open_alerts"] == 0
        assert body["model"]["type"] == get_settings().AI_MODEL_TYPE

    def test_staff_roles_can_read_the_platform_overview(
        self, client: TestClient, kvic_headers: dict, admin_headers: dict
    ):
        assert client.get(f"{API}/ai/summary", headers=kvic_headers).status_code == 200
        assert client.get(f"{API}/ai/summary", headers=admin_headers).status_code == 200

    def test_another_beekeeper_cannot_read_or_analyse_the_hive(
        self, client: TestClient, auth_headers: dict, register_user
    ):
        hive = make_hive(client, auth_headers)
        stranger = register_user()
        stranger_headers = {"Authorization": f"Bearer {stranger['access_token']}"}

        assert client.get(f"{API}/ai/hives/{hive['id']}", headers=stranger_headers).status_code == 404
        assert (
            client.post(f"{API}/ai/hives/{hive['id']}/analyze", headers=stranger_headers, json={}).status_code
            == 404
        )
        assert (
            client.get(f"{API}/ai/hives/{hive['id']}/history", headers=stranger_headers).status_code == 404
        )

    def test_an_unknown_hive_is_a_404(self, client: TestClient, auth_headers: dict):
        missing = uuid.uuid4()
        assert client.get(f"{API}/ai/hives/{missing}", headers=auth_headers).status_code == 404
        assert client.post(f"{API}/ai/hives/{missing}/analyze", headers=auth_headers, json={}).status_code == 404


class TestInsights:
    def test_an_unanalysed_hive_returns_an_honest_empty_state(self, client: TestClient, auth_headers: dict):
        hive = make_hive(client, auth_headers)

        response = client.get(f"{API}/ai/hives/{hive['id']}?refresh=false", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["analyzed"] is False
        assert body["health"] is None and body["disease_risk"] is None
        assert body["summary"] == "No AI analysis has been produced for this hive yet."

    def test_read_through_analysis_runs_once_and_then_reuses_the_row(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])
        post_window(client, auth_headers, device["device_id"])

        first = client.get(f"{API}/ai/hives/{hive['id']}", headers=auth_headers).json()["data"]
        assert first["computed"] is True
        assert first["compute_reason"] == "no_analysis"
        assert first["analyzed"] is True
        assert first["data_quality"] in ("GOOD", "LIMITED")
        assert isinstance(first["health"]["score"], int)

        second = client.get(f"{API}/ai/hives/{hive['id']}", headers=auth_headers).json()["data"]
        assert second["computed"] is False
        assert second["compute_reason"] == "fresh"
        assert second["analysis_id"] == first["analysis_id"]

        db.expire_all()
        assert db.query(HiveAiAnalysis).count() == 1

    def test_enough_new_telemetry_triggers_a_recomputation(
        self, client: TestClient, auth_headers: dict
    ):
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])
        # The first window ends ten minutes ago, so every reading of the second
        # window is genuinely newer than the stored analysis.
        post_window(client, auth_headers, device["device_id"], samples=10, ends_minutes_ago=10)
        client.get(f"{API}/ai/hives/{hive['id']}", headers=auth_headers)

        # A handful of new readings is not enough to be worth a second run…
        post_window(client, auth_headers, device["device_id"], samples=3, spread_hours=0.1)
        untouched = client.get(f"{API}/ai/hives/{hive['id']}", headers=auth_headers).json()["data"]
        assert untouched["computed"] is False
        assert untouched["compute_reason"] == "fresh"

        # …while AI_RECOMPUTE_AFTER_SAMPLES of them are.
        threshold = get_settings().AI_RECOMPUTE_AFTER_SAMPLES
        post_window(
            client, auth_headers, device["device_id"], samples=threshold, spread_hours=0.2
        )

        again = client.get(f"{API}/ai/hives/{hive['id']}", headers=auth_headers).json()["data"]
        assert again["computed"] is True
        assert again["compute_reason"] == "new_telemetry"

    def test_a_stale_analysis_is_recomputed(self, client: TestClient, auth_headers: dict, db: Session):
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])
        post_window(client, auth_headers, device["device_id"])
        client.get(f"{API}/ai/hives/{hive['id']}", headers=auth_headers)

        db.expire_all()
        stored = db.query(HiveAiAnalysis).one()
        stored.analyzed_at = datetime.now(timezone.utc) - timedelta(
            hours=get_settings().AI_ANALYSIS_TTL_HOURS + 1
        )
        db.commit()

        response = client.get(f"{API}/ai/hives/{hive['id']}", headers=auth_headers).json()["data"]
        assert response["computed"] is True
        assert response["compute_reason"] == "stale"

    def test_refresh_false_never_writes(self, client: TestClient, auth_headers: dict, db: Session):
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])
        post_window(client, auth_headers, device["device_id"], samples=10)

        response = client.get(f"{API}/ai/hives/{hive['id']}?refresh=false", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["data"]["analyzed"] is False
        db.expire_all()
        assert db.query(HiveAiAnalysis).count() == 0

    def test_auto_analysis_can_be_disabled(self, client: TestClient, auth_headers: dict, db: Session):
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])
        post_window(client, auth_headers, device["device_id"], samples=10)

        # The service takes its settings explicitly, so the policy can be turned
        # off here without touching the running application's configuration.
        settings = get_settings().model_copy(update={"AI_AUTO_ANALYSIS_ENABLED": False})
        service = AiService(db, settings)
        db.expire_all()
        hive_row = service.hives.get(uuid.UUID(hive["id"]))

        analysis, meta = service.snapshot_for_hive(hive_row)

        assert analysis is None
        assert meta["computed"] is False
        assert meta["reason"] == "auto_disabled"

    def test_a_hive_with_no_telemetry_is_analysed_as_insufficient(
        self, client: TestClient, auth_headers: dict
    ):
        hive = make_hive(client, auth_headers)

        response = client.post(f"{API}/ai/hives/{hive['id']}/analyze", headers=auth_headers, json={})

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["data_quality"] == "INSUFFICIENT"
        assert body["sample_count"] == 0
        assert body["health_status"] == "INSUFFICIENT_DATA"
        assert body["health_score"] is None
        assert body["alerts_created"] == 0

    def test_the_insight_carries_the_evidence_and_the_disclaimers(
        self, client: TestClient, auth_headers: dict
    ):
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])
        post_window(client, auth_headers, device["device_id"], samples=12, spread_hours=5)

        body = client.get(f"{API}/ai/hives/{hive['id']}", headers=auth_headers).json()["data"]

        assert body["health"]["factors"], body["health"]
        assert body["health"]["disclaimer"]
        assert "diagnos" in body["disease_risk"]["disclaimer"].lower()
        assert body["swarming_risk"]["disclaimer"]
        assert body["analysis_source"] == "SIMULATOR"
        assert body["analysis_source_label"] == "Simulator telemetry"
        assert body["quality"]["sample_count"] == 12
        assert body["model_type"] == get_settings().AI_MODEL_TYPE

    def test_unknown_request_fields_are_rejected(self, client: TestClient, auth_headers: dict):
        hive = make_hive(client, auth_headers)

        response = client.post(
            f"{API}/ai/hives/{hive['id']}/analyze",
            headers=auth_headers,
            json={"window_hours": 8760},
        )

        # The window is a platform setting, not a client parameter: a caller
        # cannot widen it until a thin dataset looks confident.
        assert response.status_code == 422

    def test_history_is_paginated(self, client: TestClient, auth_headers: dict):
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])
        post_window(client, auth_headers, device["device_id"], samples=10)
        for _ in range(3):
            client.post(f"{API}/ai/hives/{hive['id']}/analyze", headers=auth_headers, json={})

        response = client.get(f"{API}/ai/hives/{hive['id']}/history?page_size=2", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 2
        assert body["meta"]["total_items"] == 3
        assert body["meta"]["total_pages"] == 2
        assert body["data"][0]["analyzed_at"] >= body["data"][1]["analyzed_at"]

    def test_the_hive_list_reports_every_hive_including_unanalysed_ones(
        self, client: TestClient, auth_headers: dict
    ):
        analysed = make_hive(client, auth_headers, village="Analysed")
        device = make_device(client, auth_headers, analysed["id"])
        post_window(client, auth_headers, device["device_id"], samples=10)
        client.get(f"{API}/ai/hives/{analysed['id']}", headers=auth_headers)
        never = make_hive(client, auth_headers, village="Never analysed")

        body = client.get(f"{API}/ai/hives", headers=auth_headers).json()
        rows = {row["hive_code"]: row for row in body["data"]}

        assert analysed["hive_code"] in rows and never["hive_code"] in rows
        assert rows[analysed["hive_code"]]["analyzed"] is True
        assert rows[analysed["hive_code"]]["health_status"] is not None
        assert rows[never["hive_code"]]["analyzed"] is False
        assert rows[never["hive_code"]]["health_score"] is None

        filtered = client.get(f"{API}/ai/hives?only_with_analysis=true", headers=auth_headers).json()
        assert {row["hive_code"] for row in filtered["data"]} == {analysed["hive_code"]}

    def test_a_kvic_officer_can_read_any_hive_insight(
        self, client: TestClient, auth_headers: dict, kvic_headers: dict
    ):
        hive = make_hive(client, auth_headers)

        assert client.get(f"{API}/ai/hives/{hive['id']}", headers=kvic_headers).status_code == 200
        assert client.get(f"{API}/ai/hives", headers=kvic_headers).status_code == 200


class TestAlerts:
    def stress_hive(self, client: TestClient, headers: dict) -> dict:
        """A hive whose recorded window trips the temperature anomaly."""
        hive = make_hive(client, headers, village="Stressed")
        device = make_device(client, headers, hive["id"])
        post_window(
            client, headers, device["device_id"], samples=12, spread_hours=5,
            temperature=42.0, humidity=90.0, acoustic=52.0,
        )
        response = client.post(f"{API}/ai/hives/{hive['id']}/analyze", headers=headers, json={})
        assert response.status_code == 200, response.text
        return {"hive": hive, "run": response.json()["data"]}

    def test_a_stressed_window_raises_alerts(self, client: TestClient, auth_headers: dict, db: Session):
        stressed = self.stress_hive(client, auth_headers)

        assert stressed["run"]["alerts_created"] >= 1
        db.expire_all()
        alerts = db.query(AiAlert).all()
        assert alerts
        assert all(str(alert.status) == AiAlertStatus.OPEN.value for alert in alerts)
        assert all(alert.occurrences == 1 for alert in alerts)
        assert all(alert.dedupe_key == dedupe_key_for(alert.hive_id, alert.alert_type) for alert in alerts)

    def test_alerts_are_listed_for_their_owner_with_context(
        self, client: TestClient, auth_headers: dict
    ):
        stressed = self.stress_hive(client, auth_headers)

        body = client.get(f"{API}/ai/alerts", headers=auth_headers).json()["data"]

        assert body
        alert = body[0]
        assert alert["hive_code"] == stressed["hive"]["hive_code"]
        assert alert["severity"] in ("INFO", "WARNING", "CRITICAL")
        assert alert["status"] == "OPEN"
        assert alert["message"]
        assert alert["disclaimer"]
        assert alert["context"]["data_quality"] in ("GOOD", "LIMITED")
        assert alert["context"]["model"]["type"] == get_settings().AI_MODEL_TYPE

    def test_rerunning_the_analysis_bumps_instead_of_duplicating(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        stressed = self.stress_hive(client, auth_headers)
        hive_id = stressed["hive"]["id"]

        run = client.post(f"{API}/ai/hives/{hive_id}/analyze", headers=auth_headers, json={}).json()["data"]
        assert run["alerts_created"] == 0
        assert run["alerts_bumped"] >= 1

        rows = client.get(f"{API}/ai/alerts", headers=auth_headers).json()["data"]
        keys = [row["alert_type"] for row in rows]
        assert len(keys) == len(set(keys)), keys
        assert all(row["occurrences"] >= 2 for row in rows if row["alert_type"] == "TEMPERATURE_ANOMALY")

    def test_filters_and_summary(self, client: TestClient, auth_headers: dict):
        self.stress_hive(client, auth_headers)

        all_alerts = client.get(f"{API}/ai/alerts", headers=auth_headers).json()
        assert all_alerts["meta"]["total_items"] >= 1

        temperature = client.get(
            f"{API}/ai/alerts?alert_type=temperature_anomaly", headers=auth_headers
        ).json()["data"]
        assert temperature and all(row["alert_type"] == "TEMPERATURE_ANOMALY" for row in temperature)

        severity = client.get(f"{API}/ai/alerts?severity=WARNING", headers=auth_headers).json()["data"]
        assert all(row["severity"] == "WARNING" for row in severity)

        summary = client.get(f"{API}/ai/alerts/summary", headers=auth_headers).json()["data"]
        assert summary["open_total"] >= 1
        assert set(summary["by_severity"]) == {"INFO", "WARNING", "CRITICAL"}
        assert "notification" in summary["note"].lower()

    def test_acknowledge_resolve_and_reopen(self, client: TestClient, auth_headers: dict, db: Session):
        self.stress_hive(client, auth_headers)
        alert = client.get(f"{API}/ai/alerts", headers=auth_headers).json()["data"][0]
        alert_id = alert["id"]

        acked = client.post(
            f"{API}/ai/alerts/{alert_id}/acknowledge",
            headers=auth_headers,
            json={"note": "Looked at the hive this morning."},
        ).json()["data"]
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["acknowledged_at"]
        assert acked["acknowledged_by"]
        assert acked["context"]["acknowledged_note"] == "Looked at the hive this morning."

        # Acknowledging twice is a no-op rather than an error.
        again = client.post(f"{API}/ai/alerts/{alert_id}/acknowledge", headers=auth_headers, json={})
        assert again.status_code == 200 and again.json()["data"]["status"] == "ACKNOWLEDGED"

        resolved = client.post(f"{API}/ai/alerts/{alert_id}/resolve", headers=auth_headers, json={})
        assert resolved.status_code == 200 and resolved.json()["data"]["status"] == "RESOLVED"

        listing = client.get(f"{API}/ai/alerts", headers=auth_headers).json()["data"]
        assert all(row["id"] != alert_id for row in listing)
        history = client.get(
            f"{API}/ai/alerts?include_resolved=true", headers=auth_headers
        ).json()["data"]
        assert any(row["id"] == alert_id for row in history)

        reopened = client.post(f"{API}/ai/alerts/{alert_id}/reopen", headers=auth_headers, json={})
        assert reopened.status_code == 200 and reopened.json()["data"]["status"] == "OPEN"

        db.expire_all()
        entry = (
            db.query(AuditLog).filter_by(action=str(AuditAction.AI_ALERT_ACKNOWLEDGED)).first()
        )
        assert entry is not None
        assert entry.event_metadata["alert_type"]
        # The audit entry names the caller who acknowledged it, matching the
        # actor recorded on the alert itself.
        assert str(entry.user_id) == str(acked["acknowledged_by"])

    def test_resolving_then_rerunning_creates_a_new_alert_rather_than_reviving(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        stressed = self.stress_hive(client, auth_headers)
        hive_id = stressed["hive"]["id"]
        alert = client.get(f"{API}/ai/alerts", headers=auth_headers).json()["data"][0]
        client.post(f"{API}/ai/alerts/{alert['id']}/resolve", headers=auth_headers, json={})

        run = client.post(f"{API}/ai/hives/{hive_id}/analyze", headers=auth_headers, json={}).json()["data"]

        assert run["alerts_created"] >= 1
        active = client.get(f"{API}/ai/alerts", headers=auth_headers).json()["data"]
        assert any(row["alert_type"] == alert["alert_type"] for row in active)
        assert all(row["status"] == "OPEN" for row in active)

    def test_alerts_for_one_hive_can_be_read_directly(self, client: TestClient, auth_headers: dict):
        stressed = self.stress_hive(client, auth_headers)

        response = client.get(
            f"{API}/ai/hives/{stressed['hive']['id']}/alerts", headers=auth_headers
        )

        assert response.status_code == 200
        assert response.json()["data"]
        assert (
            client.get(
                f"{API}/ai/hives/{uuid.uuid4()}/alerts", headers=auth_headers
            ).status_code
            == 404
        )

    def test_an_unknown_alert_is_a_404(self, client: TestClient, auth_headers: dict):
        assert client.get(f"{API}/ai/alerts/{uuid.uuid4()}", headers=auth_headers).status_code == 404
        assert (
            client.post(f"{API}/ai/alerts/{uuid.uuid4()}/resolve", headers=auth_headers, json={}).status_code
            == 404
        )


class TestAuditAndBulk:
    def test_analysis_runs_are_audited_with_their_context(
        self, client: TestClient, auth_headers: dict, admin_headers: dict
    ):
        hive = make_hive(client, auth_headers)
        device = make_device(client, auth_headers, hive["id"])
        post_window(client, auth_headers, device["device_id"], samples=10)
        client.post(f"{API}/ai/hives/{hive['id']}/analyze", headers=auth_headers, json={})

        entries = client.get(
            f"{API}/admin/audit-logs?action={AuditAction.AI_ANALYSIS_RUN}", headers=admin_headers
        ).json()["data"]

        assert entries
        metadata = entries[0]["metadata"]
        assert metadata["hive_code"] == hive["hive_code"]
        assert metadata["sample_count"] == 10
        assert metadata["model"] == f"{get_settings().AI_MODEL_TYPE}@{get_settings().AI_MODEL_VERSION}"
        assert metadata["data_quality"] in ("GOOD", "LIMITED")

    def test_alert_creation_is_audited(self, client: TestClient, auth_headers: dict, admin_headers: dict):
        hive = make_hive(client, auth_headers, village="Stressed")
        device = make_device(client, auth_headers, hive["id"])
        post_window(
            client, auth_headers, device["device_id"], samples=12, spread_hours=5,
            temperature=42.0, humidity=90.0, acoustic=52.0,
        )
        client.post(f"{API}/ai/hives/{hive['id']}/analyze", headers=auth_headers, json={})

        entries = client.get(
            f"{API}/admin/audit-logs?action={AuditAction.AI_ALERT_CREATED}", headers=admin_headers
        ).json()["data"]

        assert entries
        assert entries[0]["metadata"]["count"] >= 1

    def test_the_bulk_run_covers_every_hive_the_caller_can_see(
        self, client: TestClient, auth_headers: dict, admin_headers: dict
    ):
        hive = make_hive(client, auth_headers, village="Bulk one")
        second = make_hive(client, auth_headers, village="Bulk two")

        body = client.post(f"{API}/ai/analyze", headers=auth_headers, json={}).json()["data"]

        assert body["hives_analyzed"] == 2
        assert body["hives_with_insufficient_data"] == 2  # no telemetry was posted
        assert body["model"]["type"] == get_settings().AI_MODEL_TYPE

        for target in (hive, second):
            insight = client.get(f"{API}/ai/hives/{target['id']}?refresh=false", headers=auth_headers).json()
            assert insight["data"]["analyzed"] is True

    def test_the_bulk_run_does_not_leak_across_beekeepers(
        self, client: TestClient, auth_headers: dict, register_user
    ):
        make_hive(client, auth_headers, village="Mine")
        stranger = register_user()
        stranger_headers = {"Authorization": f"Bearer {stranger['access_token']}"}
        make_hive(client, stranger_headers, village="Theirs")

        body = client.post(f"{API}/ai/analyze", headers=stranger_headers, json={}).json()["data"]

        assert body["hives_analyzed"] == 1
