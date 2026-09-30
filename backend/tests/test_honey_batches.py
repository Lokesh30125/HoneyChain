"""Phase 5 — the honey batch, and the guarantee that it cannot be faked.

A batch is the unit the supply chain will move, so the questions here are about
what a batch is allowed to be:

* is it created by **completing a collection**, and by nothing else? (yes)
* can completing the same harvest twice produce two batches? (no — a retry returns
  the existing batch, and the unique constraint on ``collection_id`` makes a
  duplicate impossible even under concurrency)
* can a cancelled harvest produce one? (no)
* does the batch preserve the harvest it came from — the hives, each contribution,
  the date, the quantity, the owner and the cluster? (yes, and they are snapshots)
* can a caller move it to PROCESSING, PACKAGED or DISTRIBUTED? (no — no endpoint
  exists, and the timeline renders those stages as *not started*)
* does it show the AI estimate beside the actual harvest, and admit when there was
  no estimate at all? (yes, both)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ai_analysis import HiveAiAnalysis
from app.models.audit_log import AuditLog
from app.models.enums import (
    AiAnalysisSource,
    AiDataQuality,
    AiHealthStatus,
    AiTrend,
    BatchStage,
    BatchStatus,
)
from app.models.hive import Hive
from app.models.honey_batch import HoneyBatch
from app.models.honey_collection import HoneyCollection

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
def headers_for(payload: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {payload['access_token']}"}


def make_cluster(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post(f"{API}/clusters", headers=headers, json={**CLUSTER_PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def make_hive(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post(f"{API}/hives", headers=headers, json={**HIVE_PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def add_member(client: TestClient, headers: dict, cluster_id: str, beekeeper_id: str):
    response = client.post(f"{API}/clusters/{cluster_id}/beekeepers/{beekeeper_id}", headers=headers)
    assert response.status_code in (200, 201), response.text
    return response.json()


def record_harvest(
    client: TestClient, headers: dict, hives: list[dict], quantities: list[str] | None = None, **overrides
) -> dict:
    rows = [
        {"hive_id": hive["id"], "quantity": quantity}
        for hive, quantity in zip(hives, quantities, strict=True)
    ] if quantities else [{"hive_id": hive["id"], "quantity": "4.5"} for hive in hives]
    response = client.post(
        f"{API}/collections",
        headers=headers,
        json={
            "hives": rows,
            "collection_date": overrides.pop("collection_date", date.today().isoformat()),
            "unit": overrides.pop("unit", "KG"),
            **overrides,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def complete(client: TestClient, headers: dict, collection_id: str):
    return client.post(f"{API}/collections/{collection_id}/complete", headers=headers)


def make_batch(client: TestClient, headers: dict, hives: list[dict], quantities: list[str] | None = None, **overrides):
    """A harvest recorded and completed — the only path to a batch there is."""
    collection = record_harvest(client, headers, hives, quantities, **overrides)
    response = complete(client, headers, collection["id"])
    assert response.status_code == 200, response.text
    batch_code = response.json()["meta"]["batch"]["batch_code"]
    batch_id = response.json()["meta"]["batch"]["id"]
    return client.get(f"{API}/batches/{batch_id}", headers=headers).json()["data"], collection


def store_analysis(db: Session, hive_id: str, predicted_yield_kg: float | None) -> HiveAiAnalysis:
    hive = db.get(Hive, uuid.UUID(str(hive_id)))
    assert hive is not None
    analysis = HiveAiAnalysis(
        hive_id=hive.id,
        beekeeper_id=hive.beekeeper_id,
        analyzed_at=datetime.now(timezone.utc),
        sample_count=48,
        data_quality=AiDataQuality.GOOD,
        analysis_source=AiAnalysisSource.SIMULATOR,
        model_type="hive_health_rules",
        model_version="1.0.0",
        health_score=78,
        health_status=AiHealthStatus.HEALTHY,
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


# --------------------------------------------------------------------------- #
# 10, 12, 16 — one batch per completed collection, and it preserves the harvest
# --------------------------------------------------------------------------- #
class TestBatchCreation:
    def test_completing_a_collection_creates_exactly_one_batch(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        batch, collection = make_batch(client, auth_headers, [hive], ["4.5"])

        assert db.query(HoneyBatch).count() == 1
        row = db.query(HoneyBatch).one()
        assert row.collection_id == uuid.UUID(collection["id"])
        assert float(row.quantity) == 4.5
        assert row.unit.value == "KG"
        assert row.collection_date == date.today()
        assert row.status == BatchStatus.COLLECTED
        assert row.current_stage == BatchStage.COLLECTION
        assert row.source_hive_count == 1
        assert batch["collection_id"] == collection["id"]

    def test_the_batch_code_is_unique_and_server_generated(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        codes = set()
        for index in range(3):
            batch, _collection = make_batch(client, auth_headers, [hive], [str(index + 1)])
            codes.add(batch["batch_code"])
            assert batch["batch_code"].startswith("HC-BATCH-")
            assert batch["batch_code"].split("-")[-1].isdigit()
        assert len(codes) == 3

    def test_the_harvest_figures_are_copied_not_invented(
        self, client: TestClient, auth_headers, db: Session
    ):
        hives = [make_hive(client, auth_headers) for _ in range(2)]
        batch, collection = make_batch(client, auth_headers, hives, ["9.25", "4.75"])

        assert float(batch["quantity"]) == 14.0
        assert float(collection["total_quantity"]) == 14.0
        assert batch["collection_date"] == collection["collection_date"]
        assert batch["unit"] == collection["unit"]
        assert batch["beekeeper_id"] == collection["beekeeper_id"]
        assert batch["cluster_id"] == collection["cluster_id"]
        assert batch["source_hive_count"] == 2

    def test_a_gram_harvest_stays_in_grams(self, client: TestClient, auth_headers):
        """No conversion is invented between units: what was weighed is what is stored."""
        hive = make_hive(client, auth_headers)
        batch, _collection = make_batch(client, auth_headers, [hive], ["750"], unit="GRAM")
        assert batch["unit"] == "GRAM"
        assert float(batch["quantity"]) == 750.0
        assert batch["unit_label"] == "g"

    def test_the_batch_traces_back_to_each_source_hive(
        self, client: TestClient, auth_headers
    ):
        hives = [make_hive(client, auth_headers) for _ in range(3)]
        batch, collection = make_batch(client, auth_headers, hives, ["5", "3", "2"])

        sources = client.get(f"{API}/batches/{batch['id']}/sources", headers=auth_headers).json()["data"]
        assert {row["hive_code"] for row in sources} == {hive["hive_code"] for hive in hives}
        assert {row["hive_id"] for row in sources} == {hive["id"] for hive in hives}
        assert sum(float(row["contribution_share"]) for row in sources) == pytest.approx(1.0)
        by_code = {row["hive_code"]: float(row["quantity"]) for row in sources}
        assert by_code[hives[0]["hive_code"]] == 5.0

        # The hive records themselves are read from the registry, and the payload
        # says the status shown is today's, not a harvest-time snapshot.
        registry = client.get(f"{API}/batches/{batch['id']}/hives", headers=auth_headers).json()["data"]
        assert {row["hive_code"] for row in registry} == {hive["hive_code"] for hive in hives}
        assert all("current registry state" in (row["note"] or "").lower() for row in registry)
        assert {row["beekeeper_code"] for row in registry} == {batch["beekeeper_code"]}

        linked = client.get(f"{API}/batches/{batch['id']}/collection", headers=auth_headers).json()["data"]
        assert linked["id"] == collection["id"]
        assert linked["collection_code"] == collection["collection_code"]

    def test_a_batch_cannot_be_created_by_hand(
        self, client: TestClient, auth_headers
    ):
        """There is no create endpoint, and an attempt to invent one gets a 405."""
        response = client.post(f"{API}/batches", headers=auth_headers, json={"batch_code": "HC-BATCH-2026-000001"})
        assert response.status_code == 405, response.text

    def test_the_collection_endpoint_reports_a_batch_only_after_completion(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        collection = record_harvest(client, auth_headers, [hive], ["4"])

        before = client.get(f"{API}/collections/{collection['id']}/batch", headers=auth_headers).json()
        # The platform envelope never carries a null payload, so "no batch yet" is
        # an omitted data key plus an explicit meta flag — not an empty object.
        assert before.get("data") is None
        assert before["meta"]["batch_exists"] is False
        assert before["meta"]["collection_code"] == collection["collection_code"]

        complete(client, auth_headers, collection["id"])
        after = client.get(f"{API}/collections/{collection['id']}/batch", headers=auth_headers).json()
        assert after["data"]["batch_code"].startswith("HC-BATCH-")
        assert after["meta"]["batch_exists"] is True


# --------------------------------------------------------------------------- #
# 10 — idempotency and transactionality
# --------------------------------------------------------------------------- #
class TestBatchIdempotency:
    def test_completing_twice_returns_the_same_batch(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        collection = record_harvest(client, auth_headers, [hive], ["4"])

        first = complete(client, auth_headers, collection["id"])
        assert first.status_code == 200, first.text
        assert first.json()["meta"]["batch_created"] is True

        for _ in range(2):
            retry = complete(client, auth_headers, collection["id"])
            assert retry.status_code == 200, retry.text
            assert retry.json()["meta"]["batch_created"] is False
            assert (
                retry.json()["meta"]["batch"]["batch_code"]
                == first.json()["meta"]["batch"]["batch_code"]
            )

        assert db.query(HoneyBatch).count() == 1
        # A retry is not an event either: the harvest was completed once.
        actions = [row.action for row in db.query(AuditLog).all()]
        assert actions.count("COLLECTION_COMPLETED") == 1
        assert actions.count("BATCH_CREATED") == 1

    def test_the_database_refuses_a_second_batch_for_one_collection(
        self, client: TestClient, auth_headers, db: Session
    ):
        """The rule is enforced by a unique constraint, not only by the service."""
        hive = make_hive(client, auth_headers)
        batch, collection = make_batch(client, auth_headers, [hive], ["4"])
        existing = db.query(HoneyBatch).one()
        assert str(existing.collection_id) == collection["id"]

        duplicate = HoneyBatch(
            batch_code="HC-BATCH-2026-999999",
            collection_id=existing.collection_id,
            beekeeper_id=existing.beekeeper_id,
            cluster_id=existing.cluster_id,
            collection_date=existing.collection_date,
            quantity=existing.quantity,
            unit=existing.unit,
            status=BatchStatus.COLLECTED,
            current_stage=BatchStage.COLLECTION,
            source_hive_count=1,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.query(HoneyBatch).count() == 1
        assert batch["batch_code"] != "HC-BATCH-2026-999999"

    def test_a_failed_completion_leaves_no_batch_behind(
        self, client: TestClient, auth_headers, db: Session
    ):
        """Completion is one transaction: if the rules are not met, nothing is written."""
        hive = make_hive(client, auth_headers)
        collection = record_harvest(client, auth_headers, [hive], ["4"])
        # Remove the contribution rows so the harvest has no source hive at all.
        from app.models.honey_collection import HoneyCollectionHive

        db.query(HoneyCollectionHive).delete()
        db.commit()

        response = complete(client, auth_headers, collection["id"])
        assert response.status_code == 422, response.text
        assert db.query(HoneyBatch).count() == 0
        row = db.query(HoneyCollection).one()
        assert row.status.value == "PLANNED"  # still open, not half-completed
        assert row.completed_at is None


# --------------------------------------------------------------------------- #
# 13 — cancelled harvests, and the lifecycle this phase cannot reach
# --------------------------------------------------------------------------- #
class TestLifecycleLimits:
    def test_a_cancelled_collection_never_produces_a_batch(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        collection = record_harvest(client, auth_headers, [hive], ["4"])
        cancel = client.post(
            f"{API}/collections/{collection['id']}/cancel",
            headers=auth_headers,
            json={"reason": "Hive was empty"},
        )
        assert cancel.status_code == 200, cancel.text

        attempt = complete(client, auth_headers, collection["id"])
        assert attempt.status_code == 409, attempt.text
        assert db.query(HoneyBatch).count() == 0

        listing = client.get(f"{API}/batches", headers=auth_headers).json()
        assert listing["data"] == []

    def test_a_new_batch_starts_at_collected_and_the_timeline_says_so(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        batch, _collection = make_batch(client, auth_headers, [hive], ["4"])

        assert batch["status"] == "COLLECTED"
        assert batch["status_label"] == "Collected"
        assert batch["current_stage"] == "COLLECTION"

        stages = {row["stage"]: row for row in batch["timeline"]}
        assert stages["COLLECTION"]["state"] == "completed"
        assert stages["COLLECTION"]["reached"] is True
        assert stages["COLLECTION"]["module_available"] is True

        # Processing and laboratory ship in Phase 6, so their stages are real
        # steps of the journey that have simply not been reached yet — reachable,
        # and therefore *not* described as unimplemented.
        for stage in ("PROCESSING", "LABORATORY"):
            assert stages[stage]["state"] == "not_started"
            assert stages[stage]["reached"] is False
            assert stages[stage]["module_available"] is True
            assert "not implemented" not in (stages[stage]["note"] or "").lower()

        # Everything beyond the laboratory is a real stage of the journey too:
        # Phase 7 built packaging and distribution, so a batch that has not
        # reached them is reported as *not yet reached*, never as unimplemented.
        # Packaging is the one stage that is more than "not started": a batch the
        # laboratory has not released may not be packed at all, and the timeline
        # says so with the reason instead of implying that packing is next.
        assert stages["PACKAGING"]["state"] == "blocked"
        assert stages["PACKAGING"]["reached"] is False
        assert stages["PACKAGING"]["module_available"] is True
        assert "collected" in (stages["PACKAGING"]["detail"] or "").lower()
        assert "laboratory has released it" in (stages["PACKAGING"]["note"] or "").lower()

        for stage in ("DISTRIBUTION", "COMPLETED"):
            assert stages[stage]["state"] == "not_started"
            assert stages[stage]["reached"] is False
            assert stages[stage]["module_available"] is True
            assert "not implemented" not in (stages[stage]["note"] or "").lower()

    def test_no_endpoint_can_advance_a_batch(
        self, client: TestClient, auth_headers, admin_headers, db: Session
    ):
        """The capability is absent, not merely refused — that is the difference
        between 'not yet implemented' and 'implemented incorrectly'."""
        hive = make_hive(client, auth_headers)
        batch, _collection = make_batch(client, auth_headers, [hive], ["4"])
        path = f"{API}/batches/{batch['id']}"

        assert client.patch(path, headers=auth_headers, json={"status": "PACKAGED"}).status_code == 405
        assert client.put(path, headers=auth_headers, json={"status": "PACKAGED"}).status_code == 405
        assert client.delete(path, headers=auth_headers).status_code == 405
        assert client.post(f"{path}/status", headers=auth_headers, json={"status": "PACKAGED"}).status_code in (404, 405)
        # Not even an administrator can move it.
        assert (
            client.patch(path, headers=admin_headers, json={"status": "PACKAGED"}).status_code == 405
        )

        db.expire_all()
        assert db.query(HoneyBatch).one().status == BatchStatus.COLLECTED
        assert BatchStatus.PACKAGED.value not in [
            row.status.value for row in db.query(HoneyBatch).all()
        ]

    def test_the_status_vocabulary_is_defined_but_unreachable(
        self, client: TestClient, auth_headers
    ):
        """The later states exist in the vocabulary for the later modules — and no
        collection endpoint can set them.

        Phase 6 added REJECTED and the laboratory's own two states — LAB_HOLD and
        PROCEEDED_WITH_RISK — so eight of the eleven statuses are in reach from
        somewhere in the workflow. PACKAGED, DISTRIBUTION and COMPLETED are still
        vocabulary only *for this suite*: they are written by the packaging and
        distribution modules, and recording a harvest still never produces them.
        """
        assert len(BatchStatus) == 11
        assert BatchStatus.collection_phase_statuses() == [BatchStatus.COLLECTED]
        assert BatchStatus.quality_phase_statuses() == [
            BatchStatus.COLLECTED,
            BatchStatus.PROCESSING,
            BatchStatus.LAB_TESTING,
            BatchStatus.LAB_HOLD,
            BatchStatus.PROCEEDED_WITH_RISK,
            BatchStatus.APPROVED,
            BatchStatus.PACKAGING_READY,
            BatchStatus.REJECTED,
        ]
        assert BatchStatus.supply_phase_statuses() == [
            BatchStatus.PACKAGING_READY,
            BatchStatus.PACKAGED,
            BatchStatus.DISTRIBUTION,
            BatchStatus.COMPLETED,
        ]
        assert BatchStatus.reserved_statuses() == [
            BatchStatus.PACKAGED,
            BatchStatus.DISTRIBUTION,
            BatchStatus.COMPLETED,
        ]
        hive = make_hive(client, auth_headers)
        batch, _collection = make_batch(client, auth_headers, [hive], ["4"])

        listed = client.get(f"{API}/batches?status=PACKAGED", headers=auth_headers).json()
        assert listed["data"] == []
        assert listed["meta"]["total_items"] == 0
        assert batch["status"] == "COLLECTED"


# --------------------------------------------------------------------------- #
# 9 — the AI context beside the actual harvest
# --------------------------------------------------------------------------- #
class TestBatchAiContext:
    def test_predicted_yield_is_shown_beside_the_harvest(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        store_analysis(db, hive["id"], predicted_yield_kg=6.0)
        batch, _collection = make_batch(client, auth_headers, [hive], ["4.5"])

        assert float(batch["quantity"]) == 4.5
        assert float(batch["ai_predicted_yield_kg"]) == 6.0
        assert float(batch["prediction_difference_kg"]) == pytest.approx(-1.5)

        context = batch["ai_context"]
        assert context["has_analysis"] is True
        assert float(context["actual_quantity"]) == 4.5
        assert float(context["difference_kg"]) == pytest.approx(-1.5)
        assert "not a statement about model accuracy" in context["note"].lower()
        assert context["per_hive"][0]["hive_code"] == hive["hive_code"]
        assert float(context["per_hive"][0]["ai_predicted_yield_kg"]) == 6.0

    def test_no_analysis_means_no_comparison_and_no_invented_number(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        batch, _collection = make_batch(client, auth_headers, [hive], ["4"])

        assert batch["ai_predicted_yield_kg"] is None
        assert batch["prediction_difference_kg"] is None
        assert batch["ai_context"]["has_analysis"] is False
        assert batch["ai_context"]["difference_kg"] is None
        assert "nothing to compare" in batch["ai_context"]["note"].lower()

    def test_a_multi_hive_estimate_covers_only_the_analysed_hives(
        self, client: TestClient, auth_headers, db: Session
    ):
        analysed = make_hive(client, auth_headers)
        unanalysed = make_hive(client, auth_headers)
        store_analysis(db, analysed["id"], predicted_yield_kg=8.0)
        batch, _collection = make_batch(client, auth_headers, [analysed, unanalysed], ["5", "4"])

        assert float(batch["quantity"]) == 9.0
        assert float(batch["ai_predicted_yield_kg"]) == 8.0
        assert batch["ai_prediction_hive_count"] == 1
        per_hive = {row["hive_code"]: row for row in batch["ai_context"]["per_hive"]}
        assert float(per_hive[analysed["hive_code"]]["ai_predicted_yield_kg"]) == 8.0
        assert per_hive[unanalysed["hive_code"]]["ai_predicted_yield_kg"] is None


# --------------------------------------------------------------------------- #
# 17, 22, 27 — audit, scope and isolation
# --------------------------------------------------------------------------- #
class TestBatchAccessAndAudit:
    def test_creation_is_audited_with_the_chain_it_came_from(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        batch, collection = make_batch(client, auth_headers, [hive], ["4"])

        entry = db.query(AuditLog).filter(AuditLog.action == "BATCH_CREATED").one()
        assert entry.entity_type == "batch"
        assert str(entry.entity_id) == batch["id"]
        assert entry.event_metadata["batch_code"] == batch["batch_code"]
        assert entry.event_metadata["collection_code"] == collection["collection_code"]
        assert entry.event_metadata["source_hive_codes"] == [hive["hive_code"]]
        assert entry.event_metadata["status"] == "COLLECTED"
        assert entry.event_metadata["current_stage"] == "COLLECTION"
        assert entry.user_id is not None

        completed = db.query(AuditLog).filter(AuditLog.action == "COLLECTION_COMPLETED").one()
        assert completed.event_metadata["batch_code"] == batch["batch_code"]
        assert completed.event_metadata["new_status"] == "COMPLETED"

    def test_a_beekeeper_cannot_read_another_beekeepers_batch(
        self, client: TestClient, auth_headers, register_user
    ):
        hive = make_hive(client, auth_headers)
        batch, _collection = make_batch(client, auth_headers, [hive], ["4"])
        stranger = headers_for(register_user(name="Stranger"))

        assert client.get(f"{API}/batches/{batch['id']}", headers=stranger).status_code == 404
        assert client.get(f"{API}/batches/{batch['id']}/sources", headers=stranger).status_code == 404
        listing = client.get(f"{API}/batches", headers=stranger).json()
        assert listing["data"] == []
        assert listing["meta"]["total_items"] == 0

    def test_linking_a_beekeeper_to_a_cluster_repairs_the_honey_recorded_before_it(
        self, client: TestClient, auth_headers, admin_headers, kvic_headers, beekeeper_record
    ):
        """Membership is a relationship, and it reaches back over the history.

        The batch below was recorded before its beekeeper belonged to any cluster,
        so it named none. Linking the beekeeper to a cluster attaches it — the
        same row, repaired — which is why the cluster's view afterwards is the
        whole truth and not only the part recorded since the joining date.
        """
        hive = make_hive(client, auth_headers)
        early, _ = make_batch(client, auth_headers, [hive], ["2"])
        assert early["cluster_id"] is None

        cluster = make_cluster(client, admin_headers)
        add_member(client, admin_headers, cluster["id"], beekeeper_record["id"])
        later, _ = make_batch(client, auth_headers, [hive], ["4"])
        assert later["cluster_id"] == cluster["id"]

        view = client.get(f"{API}/clusters/{cluster['id']}/batches", headers=kvic_headers).json()
        codes = [row["batch_code"] for row in view["data"]]
        assert set(codes) == {later["batch_code"], early["batch_code"]}
        assert client.get(f"{API}/batches/{early['id']}", headers=kvic_headers).status_code == 200
        # The same rows the beekeeper reads — a view of one register, never a copy.
        mine = client.get(f"{API}/batches", headers=auth_headers).json()
        assert {row["id"] for row in view["data"]} <= {row["id"] for row in mine["data"]}

    def test_a_batch_that_names_no_cluster_is_still_readable_and_says_so(
        self, client: TestClient, auth_headers, kvic_headers
    ):
        """A missing relationship is shown, not hidden: the officer sees the batch
        with no cluster and can tell that it has none."""
        hive = make_hive(client, auth_headers)
        batch, _ = make_batch(client, auth_headers, [hive], ["2"])
        assert batch["cluster_id"] is None

        listing = client.get(f"{API}/batches", headers=kvic_headers).json()
        assert batch["id"] in {row["id"] for row in listing["data"]}
        detail = client.get(f"{API}/batches/{batch['id']}", headers=kvic_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["cluster_id"] is None

    def test_an_officer_reads_a_cluster_batch_but_cannot_touch_it(
        self, client: TestClient, auth_headers, admin_headers, kvic_headers, beekeeper_record
    ):
        cluster = make_cluster(client, admin_headers)
        add_member(client, admin_headers, cluster["id"], beekeeper_record["id"])
        hive = make_hive(client, auth_headers)
        batch, _collection = make_batch(client, auth_headers, [hive], ["4"])

        detail = client.get(f"{API}/batches/{batch['id']}", headers=kvic_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["id"] == batch["id"]
        assert detail.json()["data"]["editable_fields"] == []

        assert client.patch(f"{API}/batches/{batch['id']}", headers=kvic_headers, json={}).status_code == 405
        assert client.post(f"{API}/batches", headers=kvic_headers, json={}).status_code == 405

    def test_an_admin_sees_every_batch_read_only(
        self, client: TestClient, auth_headers, admin_headers, register_user
    ):
        hive = make_hive(client, auth_headers)
        make_batch(client, auth_headers, [hive], ["4"])
        other_headers = headers_for(register_user(name="Another Keeper"))
        other_hive = make_hive(client, other_headers)
        make_batch(client, other_headers, [other_hive], ["5"])

        listing = client.get(f"{API}/batches", headers=admin_headers).json()
        assert listing["meta"]["total_items"] == 2
        summary = client.get(f"{API}/batches/summary", headers=admin_headers).json()["data"]
        assert summary["total"] == 2
        assert summary["collected"] == 2
        assert float(summary["batched_totals"]["KG"]) == 9.0


# --------------------------------------------------------------------------- #
# 28–29 — the empty state, the counters, and the summary that drives the UI
# --------------------------------------------------------------------------- #
class TestBatchWorkspaceReads:
    def test_an_empty_workspace_reports_empty_rather_than_failing(
        self, client: TestClient, auth_headers
    ):
        listing = client.get(f"{API}/batches", headers=auth_headers)
        assert listing.status_code == 200
        assert listing.json()["data"] == []
        assert listing.json()["meta"]["total_items"] == 0

        summary = client.get(f"{API}/batches/summary", headers=auth_headers).json()["data"]
        assert summary["total"] == 0
        assert summary["batched_totals"] == {}
        assert summary["awaiting_collection_completion"] == 0

    def test_open_harvests_are_counted_as_awaiting_completion(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        record_harvest(client, auth_headers, [hive], ["4"])
        record_harvest(client, auth_headers, [hive], ["5"])
        make_batch(client, auth_headers, [hive], ["6"])

        summary = client.get(f"{API}/batches/summary", headers=auth_headers).json()["data"]
        assert summary["total"] == 1
        assert summary["awaiting_collection_completion"] == 2

    def test_listing_is_paginated_and_filterable_by_hive(
        self, client: TestClient, auth_headers
    ):
        first = make_hive(client, auth_headers)
        second = make_hive(client, auth_headers)
        make_batch(client, auth_headers, [first], ["4"])
        make_batch(client, auth_headers, [second], ["5"])
        make_batch(client, auth_headers, [first, second], ["1", "1"])

        page = client.get(f"{API}/batches?page=1&page_size=2", headers=auth_headers).json()
        assert page["meta"]["total_items"] == 3
        assert page["meta"]["total_pages"] == 2

        from_first = client.get(f"{API}/batches?hive_id={first['id']}", headers=auth_headers).json()
        assert from_first["meta"]["total_items"] == 2


# --------------------------------------------------------------------------- #
# Regression — the batch must not weaken the harvest it came from
# --------------------------------------------------------------------------- #
class TestBatchDoesNotWeakenTheHarvest:
    def test_the_collection_stays_complete_and_readable_after_the_batch(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        batch, collection = make_batch(client, auth_headers, [hive], ["4.5"])

        replayed = client.get(f"{API}/collections/{collection['id']}", headers=auth_headers).json()["data"]
        assert replayed["status"] == "COMPLETED"
        assert replayed["has_batch"] is True
        assert replayed["batch_id"] == batch["id"]
        assert replayed["batch_code"] == batch["batch_code"]
        assert replayed["source_hive_count"] == 1
        assert replayed["can_edit"] is False

    def test_the_harvest_history_defends_itself_against_deletion(
        self, client: TestClient, auth_headers, db: Session
    ):
        """Once honey has been recorded, the people in that record cannot be
        erased out from under it.

        ``honey_collection_hives.hive_id`` is ``ON DELETE RESTRICT``, so deleting
        the owner — which would cascade to their hives — is refused by the
        database, not merely discouraged by the service layer. The only removal
        paths are an explicit soft delete (``?force=true``), which keeps the rows.
        """
        hive = make_hive(client, auth_headers)
        batch, collection = make_batch(client, auth_headers, [hive], ["4"])
        from app.models.beekeeper import Beekeeper

        beekeeper = db.query(Beekeeper).one()
        db.delete(beekeeper)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        assert db.query(HoneyBatch).count() == 1
        assert db.query(HoneyCollection).count() == 1
        still_there = client.get(f"{API}/batches/{batch['id']}", headers=auth_headers)
        assert still_there.status_code == 200, still_there.text
        assert still_there.json()["data"]["collection_id"] == collection["id"]
