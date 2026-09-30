"""Phase 5 — recording a harvest, and the things that must not be possible.

The collection is where a beekeeper's work becomes a record, so these tests are
written as adversarial questions rather than happy paths:

* can a beekeeper record honey from **another beekeeper's hive**? (no)
* can a client choose its own ``beekeeper_id`` / ``cluster_id``? (no — the fields
  are forbidden, and the cluster is read from the authenticated owner's current
  membership on every write)
* can a harvest present the AI's *predicted* yield as *harvested* honey? (no — the
  estimate lives in its own columns and never enters the total)
* can a completed harvest be quietly rewritten afterwards? (no)
* does submitting the same harvest twice create two records? (no — a repeated
  ``client_reference`` returns the stored one)

Assertions are made against stored rows (via ``db``) or the API envelope — never
against what the frontend happens to send.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.ai_analysis import HiveAiAnalysis
from app.models.audit_log import AuditLog
from app.models.enums import (
    AiAnalysisSource,
    AiDataQuality,
    AiHealthStatus,
    AiTrend,
    CollectionStatus,
)
from app.models.hive import Hive
from app.models.honey_collection import HoneyCollection, HoneyCollectionHive

API = "/api/v1"

HIVE_PAYLOAD = {
    "bee_species": "Apis cerana indica",
    "village": "Tenali",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "pincode": "522201",
}

CLUSTER_PAYLOAD = {
    "cluster_name": "Guntur Cluster",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "coordinator_name": "K. Rao",
    "coordinator_phone": "9876543210",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def make_cluster(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post(f"{API}/clusters", headers=headers, json={**CLUSTER_PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def make_hive(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post(f"{API}/hives", headers=headers, json={**HIVE_PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def add_member(client: TestClient, headers: dict, cluster_id: str, beekeeper_id: str):
    return client.post(f"{API}/clusters/{cluster_id}/beekeepers/{beekeeper_id}", headers=headers)


def make_collection(
    client: TestClient,
    headers: dict,
    hives: list[dict],
    quantities: list[str] | None = None,
    **overrides,
) -> dict:
    """Record a harvest through the public endpoint.

    A single-hive harvest needs only a total, so ``total_quantity`` is passed
    through unless per-hive quantities are supplied — or a full ``hives`` list,
    which is how the deliberate mismatch cases are written.
    """
    if "hives" in overrides:
        payload_hives = overrides.pop("hives")
    elif quantities is not None:
        payload_hives = [
            {"hive_id": hive["id"], "quantity": quantity}
            for hive, quantity in zip(hives, quantities, strict=True)
        ]
    elif "total_quantity" in overrides:
        payload_hives = [{"hive_id": hive["id"]} for hive in hives]
    else:
        payload_hives = [{"hive_id": hive["id"], "quantity": "4.5"} for hive in hives]

    payload = {
        "hives": payload_hives,
        "collection_date": date.today().isoformat(),
        "unit": "KG",
        **overrides,
    }
    response = client.post(f"{API}/collections", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def headers_for(payload: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {payload['access_token']}"}


def store_analysis(
    db: Session, hive_id: str, predicted_yield_kg: float | None, **overrides
) -> HiveAiAnalysis:
    """Persist an AI analysis directly.

    The real engine needs a telemetry window to produce one, and this suite is
    about the harvest *snapshotting* what the engine stored — so the row is written
    here and read back through exactly the same repository the service uses.
    """
    hive = db.get(Hive, uuid.UUID(str(hive_id)))
    assert hive is not None
    analysis = HiveAiAnalysis(
        hive_id=hive.id,
        beekeeper_id=hive.beekeeper_id,
        analyzed_at=datetime.now(timezone.utc),
        sample_count=48,
        data_quality=overrides.get("data_quality", AiDataQuality.GOOD),
        analysis_source=overrides.get("analysis_source", AiAnalysisSource.SIMULATOR),
        model_type="hive_health_rules",
        model_version="1.0.0",
        health_score=78,
        health_status=overrides.get("health_status", AiHealthStatus.HEALTHY),
        health_trend=AiTrend.STABLE,
        predicted_yield_kg=predicted_yield_kg,
        yield_period_days=7,
        overall_confidence=80,
        detail={},
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def actions_of(db: Session) -> list[str]:
    db.expire_all()
    return [row.action for row in db.query(AuditLog).all()]


# --------------------------------------------------------------------------- #
# 1–4, 12 — recording a harvest
# --------------------------------------------------------------------------- #
class TestRecordingACollection:
    def test_a_beekeeper_records_a_harvest_from_their_own_hive(
        self, client: TestClient, auth_headers, beekeeper_record, db: Session
    ):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4.5")

        assert data["collection_code"].startswith("HC-COL-")
        assert data["status"] == "PLANNED" or data["status"] == "IN_PROGRESS"
        assert float(data["total_quantity"]) == 4.5
        assert data["unit"] == "KG"
        assert data["source_hive_count"] == 1
        assert data["source_hive_codes"] == [hive["hive_code"]]
        assert data["has_batch"] is False

        row = db.query(HoneyCollection).one()
        assert row.beekeeper_id == uuid.UUID(beekeeper_record["id"])
        assert db.query(HoneyCollectionHive).count() == 1

    def test_the_code_is_generated_by_the_server_and_is_unique(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        codes = {
            make_collection(client, auth_headers, [hive], total_quantity=str(index + 1))[
                "collection_code"
            ]
            for index in range(3)
        }
        assert len(codes) == 3
        for code in codes:
            prefix, kind, year, serial = code.split("-")
            assert (prefix, kind) == ("HC", "COL")
            assert year == str(date.today().year)
            assert len(serial) == 6 and serial.isdigit()

    def test_a_code_proposed_by_the_client_is_refused(self, client: TestClient, auth_headers):
        """The code is the platform's to issue, so a payload cannot choose one."""
        hive = make_hive(client, auth_headers)
        response = client.post(
            f"{API}/collections",
            headers=auth_headers,
            json={
                "hives": [{"hive_id": hive["id"], "quantity": "2"}],
                "collection_date": date.today().isoformat(),
                "collection_code": "HC-COL-2026-999999",
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_a_future_harvest_date_is_refused(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        response = client.post(
            f"{API}/collections",
            headers=auth_headers,
            json={
                "hives": [{"hive_id": hive["id"], "quantity": "2"}],
                "collection_date": (date.today() + timedelta(days=1)).isoformat(),
            },
        )
        assert response.status_code == 422, response.text

    def test_honey_cannot_be_recorded_from_another_beekeepers_hive(
        self, client: TestClient, register_user, auth_headers
    ):
        """The decisive isolation test: knowing a hive id is not a capability."""
        mine = make_hive(client, auth_headers)
        other_headers = headers_for(register_user(name="Other Beekeeper"))
        theirs = make_hive(client, other_headers)

        response = client.post(
            f"{API}/collections",
            headers=auth_headers,
            json={
                "hives": [
                    {"hive_id": mine["id"], "quantity": "1"},
                    {"hive_id": theirs["id"], "quantity": "1"},
                ],
                "collection_date": date.today().isoformat(),
                "total_quantity": "2",
            },
        )
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "NOT_FOUND"

    def test_an_unknown_hive_looks_exactly_like_a_foreign_one(
        self, client: TestClient, auth_headers
    ):
        response = client.post(
            f"{API}/collections",
            headers=auth_headers,
            json={
                "hives": [{"hive_id": str(uuid.uuid4()), "quantity": "1"}],
                "collection_date": date.today().isoformat(),
            },
        )
        assert response.status_code == 404
        # Same shape as the foreign-hive refusal, so ids cannot be probed for.
        assert response.json()["error"]["code"] == "NOT_FOUND"

    def test_a_hive_out_of_service_cannot_be_harvested(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        assert (
            client.patch(
                f"{API}/hives/{hive['id']}/status", headers=auth_headers, json={"status": "MAINTENANCE"}
            ).status_code
            == 200
        )
        response = client.post(
            f"{API}/collections",
            headers=auth_headers,
            json={
                "hives": [{"hive_id": hive["id"], "quantity": "1"}],
                "collection_date": date.today().isoformat(),
            },
        )
        assert response.status_code == 422, response.text

    def test_a_retired_hive_is_not_offered_for_collection(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        client.delete(f"{API}/hives/{hive['id']}", headers=auth_headers)
        payload = client.get(f"{API}/collections/eligible-hives", headers=auth_headers).json()
        assert payload["data"]["hives"] == []

    def test_the_same_hive_cannot_contribute_twice(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        response = client.post(
            f"{API}/collections",
            headers=auth_headers,
            json={
                "hives": [
                    {"hive_id": hive["id"], "quantity": "1"},
                    {"hive_id": hive["id"], "quantity": "2"},
                ],
                "collection_date": date.today().isoformat(),
                "total_quantity": "3",
            },
        )
        assert response.status_code == 422, response.text

    def test_only_a_beekeeper_can_record_a_harvest(
        self, client: TestClient, auth_headers, kvic_headers, admin_headers
    ):
        hive = make_hive(client, auth_headers)
        body = {
            "hives": [{"hive_id": hive["id"], "quantity": "1"}],
            "collection_date": date.today().isoformat(),
        }
        for headers in (kvic_headers, admin_headers):
            response = client.post(f"{API}/collections", headers=headers, json=body)
            assert response.status_code == 403, response.text
            # Declarative permission dependency: refused before the service runs.
            assert response.json()["error"]["code"] == "PERMISSION_DENIED"


# --------------------------------------------------------------------------- #
# 5–6, 26–27 — ownership and cluster inheritance
# --------------------------------------------------------------------------- #
class TestServerDerivedOwnership:
    def test_beekeeper_id_and_cluster_id_cannot_be_sent(
        self, client: TestClient, auth_headers, admin_headers
    ):
        hive = make_hive(client, auth_headers)
        cluster = make_cluster(client, admin_headers)
        for field, value in (
            ("beekeeper_id", str(uuid.uuid4())),
            ("cluster_id", cluster["id"]),
        ):
            response = client.post(
                f"{API}/collections",
                headers=auth_headers,
                json={
                    "hives": [{"hive_id": hive["id"], "quantity": "1"}],
                    "collection_date": date.today().isoformat(),
                    field: value,
                },
            )
            assert response.status_code == 422, f"{field} was accepted: {response.text}"

    def test_the_cluster_is_inherited_from_the_owners_membership(
        self, client: TestClient, auth_headers, admin_headers, beekeeper_record
    ):
        cluster = make_cluster(client, admin_headers)
        add_member(client, admin_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)

        data = make_collection(client, auth_headers, [hive], total_quantity="5")
        assert data["cluster_id"] == cluster["id"]
        assert data["cluster_code"] == cluster["cluster_code"]

    def test_a_harvest_recorded_without_a_cluster_records_none(
        self, client: TestClient, auth_headers
    ):
        """Absence is recorded as absence — never filled in speculatively."""
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="5")
        assert data["cluster_id"] is None
        assert data["cluster_code"] is None

    def test_joining_a_cluster_links_the_harvests_that_had_none(
        self, client: TestClient, auth_headers, admin_headers, beekeeper_record
    ):
        """Membership fills in the gap it explains — and only the gap.

        A harvest recorded before the beekeeper belonged to any cluster carries no
        cluster, which used to stay that way: the platform went on reporting "no
        cluster assigned" for honey whose owner was by then a member, and the two
        records disagreed for as long as the harvest existed. Joining a cluster now
        links the records that named none, because the relationship is what makes
        that value derivable rather than a guess. A record that already names a
        cluster is never touched — see the second half of this test.
        """
        hive = make_hive(client, auth_headers)
        earlier = make_collection(client, auth_headers, [hive], total_quantity="5")
        assert earlier["cluster_id"] is None
        cluster = make_cluster(client, admin_headers)
        add_member(client, admin_headers, cluster["id"], beekeeper_record["id"])

        replayed = client.get(f"{API}/collections/{earlier['id']}", headers=auth_headers).json()["data"]
        assert replayed["cluster_id"] == cluster["id"]
        assert replayed["cluster_code"] == cluster["cluster_code"]

        after = make_collection(client, auth_headers, [hive], total_quantity="6")
        assert after["cluster_id"] == cluster["id"]

    def test_a_harvest_that_already_names_a_cluster_is_never_repainted(
        self, client: TestClient, auth_headers, admin_headers, beekeeper_record
    ):
        """The repair fills blanks; it does not overwrite a recorded relationship."""
        first = make_cluster(client, admin_headers)
        second = make_cluster(client, admin_headers)
        add_member(client, admin_headers, first["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)
        harvest = make_collection(client, auth_headers, [hive], total_quantity="4")
        assert harvest["cluster_id"] == first["id"]

        # The beekeeper moves to another cluster; the honey recorded under the first
        # one stays attributed to the first one.
        add_member(client, admin_headers, second["id"], beekeeper_record["id"])
        replayed = client.get(f"{API}/collections/{harvest['id']}", headers=auth_headers).json()["data"]
        assert replayed["cluster_id"] == first["id"]


# --------------------------------------------------------------------------- #
# 4, 14, 20 — the source hives are real rows
# --------------------------------------------------------------------------- #
class TestSourceHives:
    def test_a_multi_hive_harvest_keeps_each_hive_and_its_quantity(
        self, client: TestClient, auth_headers, db: Session
    ):
        hives = [make_hive(client, auth_headers) for _ in range(3)]
        data = make_collection(client, auth_headers, hives, quantities=["10.5", "7.25", "4.75"])

        assert data["source_hive_count"] == 3
        assert set(data["source_hive_codes"]) == {hive["hive_code"] for hive in hives}
        assert float(data["total_quantity"]) == pytest.approx(22.5)

        rows = db.query(HoneyCollectionHive).all()
        assert len(rows) == 3
        assert {row.hive_code: float(row.quantity) for row in rows} == {
            hives[0]["hive_code"]: 10.5,
            hives[1]["hive_code"]: 7.25,
            hives[2]["hive_code"]: 4.75,
        }
        assert {str(row.hive_id) for row in rows} == {hive["id"] for hive in hives}

    def test_a_total_that_contradicts_the_parts_is_refused(self, client: TestClient, auth_headers):
        hives = [make_hive(client, auth_headers) for _ in range(2)]
        response = client.post(
            f"{API}/collections",
            headers=auth_headers,
            json={
                "hives": [
                    {"hive_id": hives[0]["id"], "quantity": "4"},
                    {"hive_id": hives[1]["id"], "quantity": "4"},
                ],
                "collection_date": date.today().isoformat(),
                "total_quantity": "9",
            },
        )
        assert response.status_code == 422, response.text
        assert "does not match the sum" in response.text

    def test_a_single_hive_harvest_may_state_only_the_total(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="6.5")
        assert float(data["total_quantity"]) == 6.5
        assert float(db.query(HoneyCollectionHive).one().quantity) == 6.5

    def test_every_source_hive_needs_a_quantity(self, client: TestClient, auth_headers):
        hives = [make_hive(client, auth_headers) for _ in range(2)]
        response = client.post(
            f"{API}/collections",
            headers=auth_headers,
            json={
                "hives": [
                    {"hive_id": hives[0]["id"], "quantity": "4"},
                    {"hive_id": hives[1]["id"]},
                ],
                "collection_date": date.today().isoformat(),
            },
        )
        assert response.status_code == 422, response.text

    def test_the_harvest_history_of_a_hive_is_queryable(self, client: TestClient, auth_headers):
        first = make_hive(client, auth_headers)
        second = make_hive(client, auth_headers)
        make_collection(client, auth_headers, [first], total_quantity="3")
        make_collection(client, auth_headers, [first, second], quantities=["2", "3"])

        both = client.get(f"{API}/collections?hive_id={first['id']}", headers=auth_headers).json()
        assert both["meta"]["total_items"] == 2
        only_second = client.get(
            f"{API}/collections?hive_id={second['id']}", headers=auth_headers
        ).json()
        assert only_second["meta"]["total_items"] == 1

    def test_the_hive_harvest_history_endpoint_is_owner_scoped(
        self, client: TestClient, auth_headers, register_user
    ):
        hive = make_hive(client, auth_headers)
        make_collection(client, auth_headers, [hive], total_quantity="2")

        stranger = headers_for(register_user(name="Stranger"))
        assert client.get(f"{API}/hives/{hive['id']}/collections", headers=stranger).status_code == 404

        mine = client.get(f"{API}/hives/{hive['id']}/collections", headers=auth_headers).json()
        assert mine["meta"]["total_items"] == 1
        assert mine["data"][0]["source_hive_codes"] == [hive["hive_code"]]


# --------------------------------------------------------------------------- #
# 7, 9, 21 — actual quantity versus predicted yield
# --------------------------------------------------------------------------- #
class TestActualVersusPredicted:
    def test_a_stored_analysis_is_snapshotted_beside_the_harvest(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        analysis = store_analysis(db, hive["id"], predicted_yield_kg=6.0)

        data = make_collection(client, auth_headers, [hive], total_quantity="4.5")
        assert float(data["total_quantity"]) == 4.5  # what was taken
        assert float(data["ai_predicted_yield_kg"]) == 6.0  # what was expected
        source = data["sources"][0]
        assert float(source["ai_predicted_yield_kg"]) == 6.0
        assert source["ai_analysis_id"] == str(analysis.id)

    def test_a_harvest_without_an_analysis_reports_no_comparison(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4.5")

        assert data["ai_predicted_yield_kg"] is None
        context = data["ai_context"]
        assert context["predicted_yield_kg"] is None
        assert context["difference_kg"] is None
        assert float(context["actual_quantity"]) == 4.5
        assert "no ai yield estimate" in context["note"].lower()

    def test_the_ai_estimate_never_becomes_the_harvested_quantity(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        store_analysis(db, hive["id"], predicted_yield_kg=99.0)
        data = make_collection(client, auth_headers, [hive], total_quantity="4.5")

        assert float(data["total_quantity"]) == 4.5
        row = db.query(HoneyCollection).one()
        assert float(row.total_quantity) == 4.5
        assert float(row.ai_predicted_yield_kg) == 99.0
        assert float(data["ai_context"]["difference_kg"]) == pytest.approx(4.5 - 99.0)

    def test_an_analysis_without_a_yield_figure_is_not_invented(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        store_analysis(db, hive["id"], predicted_yield_kg=None)
        data = make_collection(client, auth_headers, [hive], total_quantity="4.5")

        assert data["ai_predicted_yield_kg"] is None
        assert data["sources"][0]["ai_predicted_yield_kg"] is None
        assert data["sources"][0]["ai_analysis_id"] is None

    def test_a_multi_hive_snapshot_covers_only_the_analysed_hives(
        self, client: TestClient, auth_headers, db: Session
    ):
        analysed = make_hive(client, auth_headers)
        unanalysed = make_hive(client, auth_headers)
        store_analysis(db, analysed["id"], predicted_yield_kg=7.0)

        data = make_collection(client, auth_headers, [analysed, unanalysed], quantities=["5", "4"])
        assert float(data["total_quantity"]) == 9.0
        assert float(data["ai_predicted_yield_kg"]) == 7.0
        by_code = {row["hive_code"]: row for row in data["sources"]}
        assert float(by_code[analysed["hive_code"]]["ai_predicted_yield_kg"]) == 7.0
        assert by_code[unanalysed["hive_code"]]["ai_predicted_yield_kg"] is None


# --------------------------------------------------------------------------- #
# 8 — IoT context is context
# --------------------------------------------------------------------------- #
class TestIotContext:
    def _post_reading(self, client: TestClient, headers: dict, hive_id: str, **values) -> str:
        device = client.post(
            f"{API}/iot/devices",
            headers=headers,
            json={
                "device_id": f"ESP32-TST-{uuid.uuid4().hex[:4]}",
                "device_name": "Harvest test node",
                "hive_id": hive_id,
            },
        )
        assert device.status_code == 201, device.text
        device_id = device.json()["data"]["device_id"]
        response = client.post(
            f"{API}/iot/telemetry",
            headers=headers,
            json={
                "device_id": device_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "temperature": 33.5,
                "humidity": 58.0,
                "weight": 41.75,
                "vibration": 0.4,
                "source": "SIMULATOR",
                **values,
            },
        )
        assert response.status_code in (200, 201), response.text
        return device_id

    def test_sensor_readings_are_shown_as_context_and_never_as_honey(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        self._post_reading(client, auth_headers, hive["id"])

        data = make_collection(client, auth_headers, [hive], total_quantity="4.5")
        context = data["iot_context"]
        assert context["has_data"] is True
        assert context["weight"] == pytest.approx(41.75)
        assert context["temperature"] == pytest.approx(33.5)
        assert context["source"] == "SIMULATOR"
        assert context["source_label"] == "Simulated device feed"
        assert "no honey quantity is derived" in context["note"]
        # The harvested figure is untouched by the scale reading.
        assert float(data["total_quantity"]) == 4.5

    def test_no_readings_means_no_context_rather_than_zeros(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4.5")
        assert data["iot_context"]["has_data"] is False
        assert data["iot_context"]["weight"] is None
        assert data["iot_context"]["temperature"] is None


# --------------------------------------------------------------------------- #
# 3, 11 — idempotency
# --------------------------------------------------------------------------- #
class TestIdempotency:
    def test_repeating_a_record_with_the_same_reference_does_not_duplicate_it(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        payload = {
            "hives": [{"hive_id": hive["id"], "quantity": "3.5"}],
            "collection_date": date.today().isoformat(),
            "client_reference": f"form-{uuid.uuid4().hex[:8]}",
        }
        first = client.post(f"{API}/collections", headers=auth_headers, json=payload)
        second = client.post(f"{API}/collections", headers=auth_headers, json=payload)
        assert first.status_code == 201 and second.status_code == 201, second.text

        assert second.json()["meta"]["reused"] is True
        assert second.json()["data"]["id"] == first.json()["data"]["id"]
        assert db.query(HoneyCollection).count() == 1

    def test_two_beekeepers_may_use_the_same_form_reference(
        self, client: TestClient, auth_headers, register_user
    ):
        mine = make_hive(client, auth_headers)
        other_headers = headers_for(register_user(name="Another Keeper"))
        theirs = make_hive(client, other_headers)
        reference = "harvest-1"

        first = client.post(
            f"{API}/collections",
            headers=auth_headers,
            json={
                "hives": [{"hive_id": mine["id"], "quantity": "1"}],
                "collection_date": date.today().isoformat(),
                "client_reference": reference,
            },
        )
        second = client.post(
            f"{API}/collections",
            headers=other_headers,
            json={
                "hives": [{"hive_id": theirs["id"], "quantity": "2"}],
                "collection_date": date.today().isoformat(),
                "client_reference": reference,
            },
        )
        assert first.status_code == 201 and second.status_code == 201
        assert first.json()["data"]["id"] != second.json()["data"]["id"]
        assert second.json()["meta"]["reused"] is False
        assert (
            first.json()["data"]["collection_code"] != second.json()["data"]["collection_code"]
        )


# --------------------------------------------------------------------------- #
# 5, 17 — reading, editing and isolation
# --------------------------------------------------------------------------- #
class TestAccessAndEditing:
    def test_a_beekeeper_cannot_read_another_beekeepers_harvest(
        self, client: TestClient, auth_headers, register_user
    ):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4")
        stranger = headers_for(register_user(name="Stranger"))

        assert client.get(f"{API}/collections/{data['id']}", headers=stranger).status_code == 404
        listing = client.get(f"{API}/collections", headers=stranger).json()
        assert listing["data"] == []
        assert listing["meta"]["total_items"] == 0

    def test_a_beekeeper_cannot_edit_or_complete_another_beekeepers_harvest(
        self, client: TestClient, auth_headers, register_user
    ):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4")
        stranger = headers_for(register_user(name="Stranger"))

        assert (
            client.patch(
                f"{API}/collections/{data['id']}", headers=stranger, json={"total_quantity": "99"}
            ).status_code
            == 404
        )
        assert (
            client.post(f"{API}/collections/{data['id']}/complete", headers=stranger).status_code == 404
        )
        assert client.post(f"{API}/collections/{data['id']}/cancel", headers=stranger).status_code == 404

    def test_an_open_harvest_can_be_corrected(self, client: TestClient, auth_headers, db: Session):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4")
        response = client.patch(
            f"{API}/collections/{data['id']}",
            headers=auth_headers,
            json={"total_quantity": "6.25", "notes": "Corrected after re-weighing"},
        )
        assert response.status_code == 200, response.text
        updated = response.json()["data"]
        assert float(updated["total_quantity"]) == 6.25
        assert updated["notes"] == "Corrected after re-weighing"
        assert float(db.query(HoneyCollection).one().total_quantity) == 6.25

    def test_the_status_can_move_between_the_two_open_states(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4")
        response = client.patch(
            f"{API}/collections/{data['id']}", headers=auth_headers, json={"status": "IN_PROGRESS"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "IN_PROGRESS"

    def test_finishing_through_the_patch_endpoint_is_refused(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4")
        for status in ("COMPLETED", "CANCELLED"):
            response = client.patch(
                f"{API}/collections/{data['id']}", headers=auth_headers, json={"status": status}
            )
            assert response.status_code == 422, response.text

    def test_a_completed_harvest_is_immutable(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4")
        client.post(f"{API}/collections/{data['id']}/complete", headers=auth_headers)

        for change in (
            {"total_quantity": "9"},
            {"collection_date": (date.today() - timedelta(days=3)).isoformat()},
            {"hives": [{"hive_id": hive["id"], "quantity": "1"}]},
            {"status": "IN_PROGRESS"},
        ):
            response = client.patch(
                f"{API}/collections/{data['id']}", headers=auth_headers, json=change
            )
            assert response.status_code == 409, f"{change} was accepted: {response.text}"
        assert (
            client.post(f"{API}/collections/{data['id']}/cancel", headers=auth_headers).status_code
            == 409
        )

    def test_staff_read_within_their_scope_only(
        self, client: TestClient, auth_headers, admin_headers, register_user
    ):
        hive = make_hive(client, auth_headers)
        mine = make_collection(client, auth_headers, [hive], total_quantity="4")
        other_headers = headers_for(register_user(name="Another Keeper"))
        other_hive = make_hive(client, other_headers)
        theirs = make_collection(client, other_headers, [other_hive], total_quantity="5")

        seen = client.get(f"{API}/collections", headers=admin_headers).json()
        assert seen["meta"]["total_items"] == 2

        listing = client.get(f"{API}/collections", headers=auth_headers).json()
        codes = [row["collection_code"] for row in listing["data"]]
        assert codes == [mine["collection_code"]]
        assert theirs["collection_code"] not in codes


# --------------------------------------------------------------------------- #
# 16–17 — completion, cancellation and the audit trail
# --------------------------------------------------------------------------- #
class TestCompletionAndCancellation:
    def test_cancelling_records_the_reason_and_the_actor(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4")
        response = client.post(
            f"{API}/collections/{data['id']}/cancel",
            headers=auth_headers,
            json={"reason": "Rain stopped the harvest"},
        )
        assert response.status_code == 200, response.text
        cancelled = response.json()["data"]
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "Rain stopped the harvest"
        assert cancelled["cancelled_at"] is not None
        assert cancelled["can_edit"] is False
        assert "COLLECTION_CANCELLED" in actions_of(db)

    def test_a_cancelled_harvest_cannot_be_edited_or_completed(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4")
        client.post(f"{API}/collections/{data['id']}/cancel", headers=auth_headers)

        assert (
            client.patch(
                f"{API}/collections/{data['id']}", headers=auth_headers, json={"total_quantity": "5"}
            ).status_code
            == 409
        )
        response = client.post(f"{API}/collections/{data['id']}/complete", headers=auth_headers)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "CONFLICT"

    def test_the_audit_trail_names_every_harvest_action(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4")
        client.patch(f"{API}/collections/{data['id']}", headers=auth_headers, json={"notes": "n"})
        client.post(f"{API}/collections/{data['id']}/cancel", headers=auth_headers)

        recorded = actions_of(db)
        for action in ("COLLECTION_CREATED", "COLLECTION_UPDATED", "COLLECTION_CANCELLED"):
            assert action in recorded

        entry = db.query(AuditLog).filter(AuditLog.action == "COLLECTION_CREATED").one()
        assert entry.entity_type == "collection"
        assert entry.event_metadata["collection_code"] == data["collection_code"]
        assert entry.event_metadata["source_hive_codes"] == [hive["hive_code"]]
        assert float(entry.event_metadata["total_quantity"]) == 4.0
        assert entry.user_id is not None  # the actor, not an anonymous change

    def test_a_harvest_with_no_source_hives_cannot_be_completed(
        self, client: TestClient, auth_headers, db: Session
    ):
        """Defence in depth: the service refuses, not only the request schema."""
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4")
        db.query(HoneyCollectionHive).delete()
        db.commit()

        response = client.post(f"{API}/collections/{data['id']}/complete", headers=auth_headers)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["details"]["collection_code"] == data["collection_code"]


# --------------------------------------------------------------------------- #
# 19–24, 28–29 — the workspace, its counters and its empty states
# --------------------------------------------------------------------------- #
class TestWorkspaceReads:
    def test_the_summary_counts_real_rows(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        make_collection(client, auth_headers, [hive], total_quantity="4")
        second = make_collection(client, auth_headers, [hive], total_quantity="3")
        client.patch(f"{API}/collections/{second['id']}", headers=auth_headers, json={"status": "IN_PROGRESS"})
        third = make_collection(client, auth_headers, [hive], total_quantity="2")
        client.post(f"{API}/collections/{third['id']}/cancel", headers=auth_headers)

        summary = client.get(f"{API}/collections/summary", headers=auth_headers).json()["data"]
        assert summary["total"] == 3
        assert summary["planned"] == 1
        assert summary["in_progress"] == 1
        assert summary["cancelled"] == 1
        assert summary["completed"] == 0
        assert summary["batches_created"] == 0
        # Nothing has been completed, so there is no harvested total to report —
        # an empty map, not a zero that looks like a measurement of nothing.
        assert summary["harvested_totals"] == {}

    def test_an_empty_workspace_returns_empty_values_not_errors(
        self, client: TestClient, auth_headers
    ):
        listing = client.get(f"{API}/collections", headers=auth_headers)
        assert listing.status_code == 200
        assert listing.json()["data"] == []
        assert listing.json()["meta"]["total_items"] == 0

        summary = client.get(f"{API}/collections/summary", headers=auth_headers).json()["data"]
        assert summary["total"] == 0
        assert summary["harvested_totals"] == {}

    def test_eligible_hives_are_the_callers_own_hives(
        self, client: TestClient, auth_headers, register_user
    ):
        mine = make_hive(client, auth_headers)
        other_headers = headers_for(register_user(name="Another Keeper"))
        make_hive(client, other_headers)

        payload = client.get(f"{API}/collections/eligible-hives", headers=auth_headers).json()
        assert [row["hive_code"] for row in payload["data"]["hives"]] == [mine["hive_code"]]
        assert payload["data"]["total"] == 1

    def test_the_empty_eligible_hive_list_explains_itself(
        self, client: TestClient, auth_headers
    ):
        payload = client.get(f"{API}/collections/eligible-hives", headers=auth_headers).json()
        assert payload["data"]["hives"] == []
        assert payload["data"]["note"] == "No eligible hives available for collection."

    def test_eligible_hives_carry_the_context_to_plan_a_harvest(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        store_analysis(db, hive["id"], predicted_yield_kg=6.5)
        first = make_collection(client, auth_headers, [hive], total_quantity="2")

        row = client.get(f"{API}/collections/eligible-hives", headers=auth_headers).json()["data"][
            "hives"
        ][0]
        assert float(row["ai_predicted_yield_kg"]) == pytest.approx(6.5)
        assert row["total_collections"] == 1
        assert row["last_collection_code"] == first["collection_code"]

    def test_listing_is_paginated_and_filterable(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        for index in range(3):
            make_collection(client, auth_headers, [hive], total_quantity=str(index + 1))

        page_two = client.get(f"{API}/collections?page=2&page_size=2", headers=auth_headers).json()
        assert page_two["meta"]["total_items"] == 3
        assert page_two["meta"]["page"] == 2
        assert page_two["meta"]["total_pages"] == 2
        assert len(page_two["data"]) == 1

        completed_only = client.get(
            f"{API}/collections?has_batch=true", headers=auth_headers
        ).json()
        assert completed_only["meta"]["total_items"] == 0


# --------------------------------------------------------------------------- #
# 22, 27 — what staff may and may not do
# --------------------------------------------------------------------------- #
class TestStaffScope:
    def test_a_kvic_officer_reads_the_registry_and_cannot_write_to_it(
        self,
        client: TestClient,
        auth_headers,
        admin_headers,
        kvic_headers,
        beekeeper_record,
        register_user,
    ):
        inside = make_cluster(client, admin_headers, cluster_name="Inside Cluster")
        add_member(client, admin_headers, inside["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)
        included = make_collection(client, auth_headers, [hive], total_quantity="4")

        outside_headers = headers_for(register_user(name="Outside Keeper"))
        outside_hive = make_hive(client, outside_headers)
        excluded = make_collection(client, outside_headers, [outside_hive], total_quantity="5")

        # The officer's authority is the cluster registry, not the district on a
        # profile: a member's harvest is visible, and so is the harvest that names
        # no cluster at all — a harvest vanishing from the register is how a
        # missing relationship stays missing. Nothing was duplicated to make that
        # true: both rows are the rows their beekeepers wrote.
        listing = client.get(f"{API}/collections", headers=kvic_headers).json()
        codes = [row["collection_code"] for row in listing["data"]]
        assert included["collection_code"] in codes
        assert excluded["collection_code"] in codes
        detail = client.get(f"{API}/collections/{excluded['id']}", headers=kvic_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["id"] == excluded["id"]

        # Reading is all of it. Completing somebody else's harvest is refused, and
        # refused without touching it: the harvest is still open afterwards.
        attempt = client.post(
            f"{API}/collections/{excluded['id']}/complete", headers=kvic_headers
        )
        assert attempt.status_code in (403, 404), attempt.text
        still_open = client.get(
            f"{API}/collections/{excluded['id']}", headers=outside_headers
        ).json()["data"]
        assert still_open["status"] == excluded["status"], "the harvest changed"
        assert still_open["has_batch"] is False

    def test_a_kvic_officer_sees_the_same_record_the_beekeeper_wrote(
        self, client: TestClient, auth_headers, admin_headers, kvic_headers, beekeeper_record
    ):
        cluster = make_cluster(client, admin_headers)
        add_member(client, admin_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)
        mine = make_collection(client, auth_headers, [hive], total_quantity="4.25")

        response = client.get(f"{API}/collections/{mine['id']}", headers=kvic_headers)
        assert response.status_code == 200, response.text
        theirs = response.json()["data"]
        # Same row, same id, same numbers — a view, not a copy.
        assert theirs["id"] == mine["id"]
        assert theirs["collection_code"] == mine["collection_code"]
        assert float(theirs["total_quantity"]) == float(mine["total_quantity"])
        assert theirs["can_edit"] is False
        assert theirs["can_complete"] is False

    def test_a_kvic_officer_cannot_record_or_change_a_harvest(
        self, client: TestClient, auth_headers, admin_headers, kvic_headers, beekeeper_record
    ):
        cluster = make_cluster(client, admin_headers)
        add_member(client, admin_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4")

        assert (
            client.patch(
                f"{API}/collections/{data['id']}", headers=kvic_headers, json={"total_quantity": "9"}
            ).status_code
            == 403
        )
        assert client.post(f"{API}/collections/{data['id']}/cancel", headers=kvic_headers).status_code == 403
        assert client.post(f"{API}/collections/{data['id']}/complete", headers=kvic_headers).status_code == 403
        assert (
            client.post(
                f"{API}/collections",
                headers=kvic_headers,
                json={
                    "hives": [{"hive_id": hive["id"], "quantity": "1"}],
                    "collection_date": date.today().isoformat(),
                },
            ).status_code
            == 403
        )

    def test_the_cluster_view_exposes_the_clusters_harvests(
        self, client: TestClient, auth_headers, admin_headers, kvic_headers, beekeeper_record
    ):
        cluster = make_cluster(client, admin_headers)
        add_member(client, admin_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)
        data = make_collection(client, auth_headers, [hive], total_quantity="4")

        response = client.get(f"{API}/clusters/{cluster['id']}/collections", headers=kvic_headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert [row["collection_code"] for row in payload["data"]] == [data["collection_code"]]
        assert payload["data"][0]["cluster_id"] == cluster["id"]

    def test_a_beekeeper_cannot_read_a_cluster_harvest_view(
        self, client: TestClient, auth_headers, admin_headers, beekeeper_record
    ):
        cluster = make_cluster(client, admin_headers)
        add_member(client, admin_headers, cluster["id"], beekeeper_record["id"])
        assert client.get(f"{API}/clusters/{cluster['id']}/collections", headers=auth_headers).status_code == 403

    def test_a_consumer_has_no_access_at_all(self, client: TestClient, consumer_headers):
        """Authorization is enforced by the API, not by frontend route protection."""
        for path in ("/collections", "/collections/summary", "/batches", "/batches/summary"):
            response = client.get(f"{API}{path}", headers=consumer_headers)
            assert response.status_code == 403, f"{path} → {response.status_code}"


# --------------------------------------------------------------------------- #
# Regression — Phase 5 must not weaken Phases 1–4.1
# --------------------------------------------------------------------------- #
class TestCrossPhaseRegression:
    def test_the_collection_status_vocabulary_is_exactly_four_states(self):
        assert [status.value for status in CollectionStatus] == [
            "PLANNED",
            "IN_PROGRESS",
            "COMPLETED",
            "CANCELLED",
        ]
        assert CollectionStatus.COMPLETED.is_terminal
        assert CollectionStatus.CANCELLED.is_terminal
        assert CollectionStatus.PLANNED.is_open
        assert CollectionStatus.IN_PROGRESS.is_open

    def test_a_hive_with_harvest_history_cannot_be_erased(self, client: TestClient, auth_headers, db: Session):
        """Phase 3's rule, extended: a hive's harvest history is not deletable."""
        hive = make_hive(client, auth_headers)
        make_collection(client, auth_headers, [hive], total_quantity="2")

        refusal = client.delete(f"{API}/hives/{hive['id']}", headers=auth_headers)
        assert refusal.status_code == 409, refusal.text
        assert refusal.json()["error"]["details"]["collection_count"] == 1

        forced = client.delete(f"{API}/hives/{hive['id']}?force=true", headers=auth_headers)
        assert forced.status_code == 200, forced.text
        assert forced.json()["data"]["soft_deleted"] is True
        assert forced.json()["data"]["collections_preserved"] == 1
        assert db.get(Hive, uuid.UUID(hive["id"])) is not None
        assert db.query(HoneyCollectionHive).count() == 1

    def test_the_cluster_relationship_still_resolves_unchanged(
        self, client: TestClient, auth_headers, admin_headers, kvic_headers, beekeeper_record
    ):
        """Phase 4.1's chain is untouched by Phase 5: the hive still appears in
        the cluster view, and now its harvests do too."""
        cluster = make_cluster(client, admin_headers)
        add_member(client, admin_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)
        make_collection(client, auth_headers, [hive], total_quantity="3")

        hives = client.get(f"{API}/clusters/{cluster['id']}/hives", headers=kvic_headers).json()
        assert [row["hive_code"] for row in hives["data"]] == [hive["hive_code"]]

        member = client.get(f"{API}/beekeepers/me", headers=auth_headers).json()["data"]
        assert member["cluster"]["id"] == cluster["id"]
        assert member["cluster"]["cluster_code"] == cluster["cluster_code"]
