"""Phase 4 — repository round-trips for analyses and alerts.

These tests exercise the two AI tables through their repositories only, with no
service or engine in the way, because that is where the query shapes live that the
screens depend on: the latest analysis per hive (one query for a whole page), the
band counters, and the alert de-duplication lookup with its cooldown.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import (
    AiAlertSeverity,
    AiAlertStatus,
    AiAlertType,
    AiAnalysisSource,
    AiDataQuality,
    AiHealthStatus,
    AiRiskLevel,
    AiTrend,
)
from app.repositories.ai_repository import AiAlertRepository, AiAnalysisRepository

API = "/api/v1"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)

HIVE = {"village": "Tenali", "district": "Guntur", "state": "Andhra Pradesh"}


def make_hive(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post(f"{API}/hives", headers=headers, json={**HIVE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def analysis_values(**overrides) -> dict:
    """A complete set of ``hive_ai_analyses`` columns, minus hive/owner."""
    values = {
        "window_start": NOW - timedelta(days=7),
        "window_end": NOW,
        "sample_count": 168,
        "newest_reading_at": NOW,
        "data_quality": AiDataQuality.GOOD,
        "analysis_source": AiAnalysisSource.SIMULATOR,
        "model_type": "hive_ai_baseline",
        "model_version": "1.0",
        "health_score": 90,
        "health_status": AiHealthStatus.HEALTHY,
        "health_confidence": 78,
        "health_trend": AiTrend.STABLE,
        "disease_risk_score": 12,
        "disease_risk_level": AiRiskLevel.LOW,
        "disease_confidence": 70,
        "swarming_risk_score": 18,
        "swarming_risk_level": AiRiskLevel.LOW,
        "swarming_confidence": 70,
        "predicted_yield_kg": 3.6,
        "yield_confidence": 64,
        "yield_trend": AiTrend.RISING,
        "yield_period_days": 30,
        "overall_confidence": 70,
        "detail": {"summary": "test row"},
    }
    values.update(overrides)
    return values


@pytest.fixture()
def hive(client: TestClient, auth_headers: dict, db: Session) -> dict:
    db.expire_all()
    return make_hive(client, auth_headers)


def owner_id(client: TestClient, auth_headers: dict) -> str:
    response = client.get(f"{API}/beekeepers/me", headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


class TestAnalysisRepository:
    def test_record_and_read_back(self, db: Session, hive: dict):
        repository = AiAnalysisRepository(db)
        beekeeper_id = hive["beekeeper_id"]

        created = repository.record(
            hive_id=hive["id"], beekeeper_id=beekeeper_id, analyzed_at=NOW, **analysis_values()
        )
        db.commit()

        latest = repository.latest_for_hive(hive["id"])
        assert latest is not None and latest.id == created.id
        assert latest.health_status is AiHealthStatus.HEALTHY
        assert latest.detail["summary"] == "test row"
        assert repository.count_for_hive(hive["id"]) == 1

    def test_history_is_newest_first(self, db: Session, hive: dict):
        repository = AiAnalysisRepository(db)
        for offset in (3, 1, 2):
            repository.record(
                hive_id=hive["id"],
                beekeeper_id=hive["beekeeper_id"],
                analyzed_at=NOW - timedelta(days=offset),
                **analysis_values(),
            )
        db.commit()

        rows = repository.history(hive["id"], limit=10)
        assert [row.analyzed_at for row in rows] == sorted(
            (row.analyzed_at for row in rows), reverse=True
        )
        assert len(rows) == 3
        assert repository.history(hive["id"], limit=2, offset=2) == rows[2:]

    def test_latest_per_hive_returns_one_row_each(self, db: Session, hive: dict, client, auth_headers):
        second = make_hive(client, auth_headers, village="Repalle")
        repository = AiAnalysisRepository(db)
        rows_to_write = (
            (hive, NOW, 55),
            (hive, NOW + timedelta(hours=1), 90),
            (second, NOW, 30),
        )
        for target, analyzed_at, health_score in rows_to_write:
            repository.record(
                hive_id=target["id"],
                beekeeper_id=target["beekeeper_id"],
                analyzed_at=analyzed_at,
                **analysis_values(health_score=health_score),
            )
        db.commit()

        rows = repository.latest_per_hive([hive["id"], second["id"]])
        assert set(rows) == {uuid.UUID(hive["id"]), uuid.UUID(second["id"])}
        # Three stored rows, two hives, one row back per hive — the newest each.
        assert rows[uuid.UUID(hive["id"])].health_score == 90
        assert rows[uuid.UUID(second["id"])].health_score == 30
        assert repository.latest_per_hive([]) == {}

    def test_band_counters_use_each_hives_latest_analysis(self, db: Session, hive: dict):
        repository = AiAnalysisRepository(db)
        # An older CRITICAL row must not keep counting once the hive recovers.
        repository.record(
            hive_id=hive["id"],
            beekeeper_id=hive["beekeeper_id"],
            analyzed_at=NOW - timedelta(days=1),
            **analysis_values(health_status=AiHealthStatus.CRITICAL, disease_risk_level=AiRiskLevel.HIGH),
        )
        repository.record(
            hive_id=hive["id"],
            beekeeper_id=hive["beekeeper_id"],
            analyzed_at=NOW,
            **analysis_values(health_status=AiHealthStatus.HEALTHY, disease_risk_level=AiRiskLevel.LOW),
        )
        db.commit()

        health = repository.count_by_health_status(hive_ids=[hive["id"]])
        assert health["HEALTHY"] == 1
        assert health["CRITICAL"] == 0
        assert set(health) == {status.value for status in AiHealthStatus}

        disease = repository.count_by_risk_level(kind="disease", hive_ids=[hive["id"]])
        assert disease["LOW"] == 1 and disease["HIGH"] == 0
        swarming = repository.count_by_risk_level(kind="swarming", hive_ids=[hive["id"]])
        assert sum(swarming.values()) == 1

    def test_all_history_can_be_counted_when_asked(self, db: Session, hive: dict):
        repository = AiAnalysisRepository(db)
        repository.record(
            hive_id=hive["id"], beekeeper_id=hive["beekeeper_id"], analyzed_at=NOW - timedelta(days=1),
            **analysis_values(health_status=AiHealthStatus.CRITICAL),
        )
        repository.record(
            hive_id=hive["id"], beekeeper_id=hive["beekeeper_id"], analyzed_at=NOW,
            **analysis_values(health_status=AiHealthStatus.HEALTHY),
        )
        db.commit()

        counts = repository.count_by_health_status(hive_ids=[hive["id"]], latest_only=False)
        assert counts["CRITICAL"] == 1 and counts["HEALTHY"] == 1

    def test_yield_projection_ignores_rows_without_a_projection(self, db: Session, hive: dict, client, auth_headers):
        second = make_hive(client, auth_headers, village="Bapatla")
        repository = AiAnalysisRepository(db)
        repository.record(
            hive_id=hive["id"], beekeeper_id=hive["beekeeper_id"], analyzed_at=NOW,
            **analysis_values(predicted_yield_kg=4.0),
        )
        repository.record(
            hive_id=second["id"], beekeeper_id=second["beekeeper_id"], analyzed_at=NOW,
            **analysis_values(predicted_yield_kg=None, yield_confidence=0),
        )
        db.commit()

        summary = repository.yield_projection(hive_ids=[hive["id"], second["id"]])
        assert summary["hives_with_projection"] == 1
        assert summary["total_predicted_kg"] == 4.0
        assert summary["average_predicted_kg"] == 4.0

    def test_analyzed_hive_ids_and_delete_for_hive(self, db: Session, hive: dict):
        repository = AiAnalysisRepository(db)
        repository.record(
            hive_id=hive["id"], beekeeper_id=hive["beekeeper_id"], analyzed_at=NOW, **analysis_values()
        )
        db.commit()

        assert repository.analyzed_hive_ids([hive["id"]]) == {uuid.UUID(hive["id"])}
        assert repository.analyzed_hive_ids([]) == set()
        assert repository.delete_for_hive(hive["id"]) == 1
        db.commit()
        assert repository.latest_for_hive(hive["id"]) is None


class TestAlertRepository:
    def alert_values(self, hive: dict, **overrides) -> dict:
        values = {
            "hive_id": hive["id"],
            "beekeeper_id": hive["beekeeper_id"],
            "analysis_id": None,
            "alert_type": AiAlertType.TEMPERATURE_ANOMALY,
            "severity": AiAlertSeverity.WARNING,
            "title": "Temperature outside the reference band",
            "message": "Mean nest temperature was 41.5 °C over the window.",
            "metric": "temperature=41.5",
            "dedupe_key": f"{hive['id']}:TEMPERATURE_ANOMALY",
            "occurrences": 1,
            "first_seen_at": NOW,
            "last_seen_at": NOW,
            "status": AiAlertStatus.OPEN,
            "context": {"reference": "32.0–36.5 °C"},
        }
        values.update(overrides)
        return values

    def test_record_and_find_active(self, db: Session, hive: dict):
        repository = AiAlertRepository(db)
        created = repository.record(**self.alert_values(hive))
        db.commit()

        found = repository.active_for_key(dedupe_key=created.dedupe_key)
        assert found is not None and found.id == created.id
        assert found.alert_type is AiAlertType.TEMPERATURE_ANOMALY
        assert found.context["reference"] == "32.0–36.5 °C"

    def test_touch_counts_occurrences_without_creating_a_row(self, db: Session, hive: dict):
        repository = AiAlertRepository(db)
        alert = repository.record(**self.alert_values(hive))
        db.commit()

        repository.touch(alert, seen_at=NOW + timedelta(hours=6), message="Seen again.")
        db.commit()

        assert alert.occurrences == 2
        assert alert.last_seen_at == NOW + timedelta(hours=6)
        assert alert.message == "Seen again."
        assert repository.count(hive_ids=[hive["id"]]) == 1

    def test_the_cooldown_window_hides_old_alerts_from_deduplication(self, db: Session, hive: dict):
        repository = AiAlertRepository(db)
        alert = repository.record(
            **self.alert_values(hive, first_seen_at=NOW - timedelta(days=3), last_seen_at=NOW - timedelta(days=3))
        )
        db.commit()

        assert repository.active_for_key(dedupe_key=alert.dedupe_key) is not None
        assert (
            repository.active_for_key(
                dedupe_key=alert.dedupe_key, since=NOW - timedelta(hours=12)
            )
            is None
        )

    def test_an_acknowledged_alert_still_deduplicates(self, db: Session, hive: dict):
        repository = AiAlertRepository(db)
        alert = repository.record(**self.alert_values(hive))
        repository.set_status(alert, status=AiAlertStatus.ACKNOWLEDGED, actor_id=None, acknowledged_at=NOW)
        db.commit()

        assert alert.status is AiAlertStatus.ACKNOWLEDGED
        assert repository.active_for_key(dedupe_key=alert.dedupe_key) is not None

    def test_a_resolved_alert_stops_deduplicating_and_leaves_the_list(self, db: Session, hive: dict):
        repository = AiAlertRepository(db)
        alert = repository.record(**self.alert_values(hive))
        repository.set_status(alert, status=AiAlertStatus.RESOLVED)
        db.commit()

        assert repository.active_for_key(dedupe_key=alert.dedupe_key) is None
        assert repository.list_for_hive(hive["id"]) == []
        assert len(repository.list_for_hive(hive["id"], include_resolved=True)) == 1

    def test_search_and_count_filter_by_status_severity_and_type(self, db: Session, hive: dict):
        repository = AiAlertRepository(db)
        repository.record(**self.alert_values(hive))
        repository.record(
            **self.alert_values(
                hive,
                alert_type=AiAlertType.DATA_STALE,
                severity=AiAlertSeverity.INFO,
                dedupe_key=f"{hive['id']}:DATA_STALE",
            )
        )
        db.commit()

        assert repository.count(hive_ids=[hive["id"]]) == 2
        assert repository.count(hive_ids=[hive["id"]], severity=AiAlertSeverity.INFO) == 1
        assert repository.count(hive_ids=[hive["id"]], alert_type=AiAlertType.DATA_STALE) == 1
        assert len(repository.search(hive_ids=[hive["id"]], severity=AiAlertSeverity.WARNING)) == 1

    def test_severity_counters_exclude_resolved_alerts(self, db: Session, hive: dict):
        repository = AiAlertRepository(db)
        open_alert = repository.record(**self.alert_values(hive))
        resolved = repository.record(
            **self.alert_values(
                hive,
                alert_type=AiAlertType.DATA_STALE,
                severity=AiAlertSeverity.INFO,
                dedupe_key=f"{hive['id']}:DATA_STALE",
            )
        )
        repository.set_status(resolved, status=AiAlertStatus.RESOLVED)
        db.commit()

        counts = repository.count_by_severity(hive_ids=[hive["id"]])
        assert counts == {"WARNING": 1}
        all_counts = repository.count_by_severity(hive_ids=[hive["id"]], open_only=False)
        assert all_counts == {"WARNING": 1, "INFO": 1}
        assert repository.list_for_hive(hive["id"])[0].id == open_alert.id

    def test_resolve_missing_closes_what_no_longer_applies(self, db: Session, hive: dict):
        repository = AiAlertRepository(db)
        kept = repository.record(**self.alert_values(hive))
        dropped = repository.record(
            **self.alert_values(
                hive,
                alert_type=AiAlertType.DATA_STALE,
                severity=AiAlertSeverity.INFO,
                dedupe_key=f"{hive['id']}:DATA_STALE",
            )
        )
        db.commit()

        resolved = repository.resolve_missing(hive["id"], keep_keys=[kept.dedupe_key])
        db.commit()

        assert resolved == 1
        db.refresh(kept)
        db.refresh(dropped)
        assert kept.status is AiAlertStatus.OPEN
        assert dropped.status is AiAlertStatus.RESOLVED

    def test_resolve_missing_with_no_keys_closes_everything(self, db: Session, hive: dict):
        repository = AiAlertRepository(db)
        repository.record(**self.alert_values(hive))
        db.commit()

        assert repository.resolve_missing(hive["id"], keep_keys=[]) == 1
        db.commit()
        assert repository.list_for_hive(hive["id"]) == []
