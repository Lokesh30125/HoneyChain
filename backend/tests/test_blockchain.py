"""Phase 8 — blockchain traceability: the events, the outbox, the ledger, the QR.

The tests in this module answer one question each about the promise the platform
makes: *every real supply-chain transition is written to the ledger, exactly
once, with the values the records actually hold — and nothing is claimed that the
chain has not confirmed.*

They run against a stand-in for the blockchain service
(:mod:`tests.blockchain_stub`) rather than the live one, because a test suite must
not write to a production ledger and because an outage has to be *simulated* to
be tested. Everything above the HTTP boundary is the real code: the workflow
services record the events, the outbox holds them, the worker and the sync
endpoint submit them, and the reads are the reads the screens use.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import clear_settings_cache
from app.models.blockchain import BlockchainEvent
from app.models.enums import BlockchainEventType, BlockchainStatus, UserRole
from app.models.packaging import HoneyPackage
from tests.blockchain_stub import BlockchainStub
from tests.test_packaging import (
    LABORATORY_PAYLOAD,
    PACKAGING_UNIT_PAYLOAD,
    API,
    make_batch,
    make_hive,
    open_run,
    sign_in,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def chain(monkeypatch) -> BlockchainStub:
    """A fresh ledger service, wired into the application for one test."""
    stub = BlockchainStub().start()
    monkeypatch.setenv("BLOCKCHAIN_ENABLED", "true")
    monkeypatch.setenv("BLOCKCHAIN_BASE_URL", stub.url)
    monkeypatch.setenv("BLOCKCHAIN_OUTBOX_WORKER_ENABLED", "false")
    monkeypatch.setenv("BLOCKCHAIN_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("BLOCKCHAIN_RETRY_BACKOFF_MS", "0")
    # Production throttles one sweep to a bounded batch (a backlog is worked
    # through steadily, not in one burst). A test that sweeps once expects a
    # sweep to finish the job, so the bound is lifted here.
    monkeypatch.setenv("BLOCKCHAIN_OUTBOX_BATCH_SIZE", "500")
    monkeypatch.setenv("PUBLIC_TRACE_BASE_URL", "http://trace.test/trace")
    clear_settings_cache()
    yield stub
    stub.stop()
    clear_settings_cache()


@pytest.fixture()
def keeper(client: TestClient, register_user):
    """A beekeeper of their own, so this module's records are theirs alone."""
    payload = register_user(role=UserRole.BEEKEEPER, name="Traceable beekeeper")
    payload["headers"] = {"Authorization": f"Bearer {payload['access_token']}"}
    return payload


@pytest.fixture()
def processor(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.PROCESSOR, name="Traceable processor", password="ProcessPass123"
    )
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def technician(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.LAB_TECHNICIAN, name="Traceable technician", password="LabTechPass123"
    )
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def packer(client: TestClient, make_privileged_user, admin_headers):
    """A packing operator attached to the facility it works at, as the platform does it."""
    payload = make_privileged_user(
        role=UserRole.PACKAGING_UNIT, name="Traceable packer", password="PackPass123"
    )
    payload["headers"] = sign_in(client, payload)
    unit = client.post(
        f"{API}/packaging-units",
        headers=admin_headers,
        json={**PACKAGING_UNIT_PAYLOAD, "registration_identifier": "REG-PHASE8-TRACE"},
    )
    assert unit.status_code == 201, unit.text
    payload["unit"] = unit.json()["data"]
    attached = client.post(
        f"{API}/packaging-units/{payload['unit']['id']}/members",
        headers=admin_headers,
        json={"user_id": str(payload["id"])},
    )
    assert attached.status_code in (200, 201), attached.text
    return payload


@pytest.fixture()
def distributor(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.DISTRIBUTOR, name="Traceable distributor", password="DistributorPass123"
    )
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def retailer(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.RETAILER, name="Traceable retailer", password="RetailPass123"
    )
    payload["headers"] = sign_in(client, payload)
    return payload


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def events(db: Session, *, tx_type: BlockchainEventType | None = None) -> list[BlockchainEvent]:
    # The submissions happen in the API's own sessions; drop this session's
    # identity map so the assertions read what the database now holds.
    db.expire_all()
    statement = select(BlockchainEvent).order_by(BlockchainEvent.created_at.asc())
    if tx_type is not None:
        statement = statement.where(BlockchainEvent.tx_type == tx_type)
    return list(db.execute(statement).scalars())


def complete_collection(client: TestClient, headers: dict, hive: dict, quantity: str = "13.7") -> dict:
    collection = client.post(
        f"{API}/collections",
        headers=headers,
        json={
            "hives": [{"hive_id": hive["id"], "quantity": quantity}],
            "collection_date": date.today().isoformat(),
            "unit": "KG",
        },
    ).json()["data"]
    response = client.post(f"{API}/collections/{collection['id']}/complete", headers=headers)
    assert response.status_code == 200, response.text
    return {"collection": collection, "batch": response.json()["meta"]["batch"]}


def configure_moisture(client: TestClient, admin_headers: dict) -> None:
    """One configured parameter, so a measurement can actually be judged.

    Configuration is a PATCH on the catalogue and states where the range came
    from — the platform quotes the source it was given and defines no scientific
    limits of its own.
    """
    response = client.patch(
        f"{API}/lab-parameters/MOISTURE",
        headers=admin_headers,
        json={
            "is_required": True,
            "reference_min": "10",
            "reference_max": "20",
            "reference_source": "Phase 8 test configuration",
        },
    )
    assert response.status_code == 200, response.text


def approved_batch(
    client: TestClient, admin_headers, processor, technician, keeper, *, moisture="12.9"
):
    """A batch taken through processing and the laboratory to a verdict.

    ``moisture`` is the measured value the laboratory records: 12.9 % is inside
    the configured 10–20 % range, anything outside it fails. The processing run
    always loses the same 0.8 kg — honey does not gain mass, and the platform
    refuses a completion that says it did.
    """
    hive = make_hive(client, keeper["headers"])
    batch = make_batch(client, keeper["headers"], hive)
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": batch["id"], "processing_type": "FILTERING"},
    ).json()["data"]
    client.post(f"{API}/processing/{run['id']}/start", headers=processor["headers"])
    completed_run = client.post(
        f"{API}/processing/{run['id']}/complete",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    assert completed_run.status_code == 200, completed_run.text
    laboratory = client.post(
        f"{API}/laboratories", headers=technician["headers"], json=LABORATORY_PAYLOAD
    ).json()["data"]
    test = client.post(
        f"{API}/lab-tests",
        headers=technician["headers"],
        json={
            "batch_id": batch["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.25",
        },
    ).json()["data"]
    configure_moisture(client, admin_headers)
    measured = client.post(
        f"{API}/lab-tests/{test['id']}/results",
        headers=technician["headers"],
        json={"parameter_code": "MOISTURE", "value": moisture},
    )
    assert measured.status_code in (200, 201), measured.text
    completed = client.post(
        f"{API}/lab-tests/{test['id']}/complete", headers=technician["headers"], json={}
    )
    assert completed.status_code == 200, completed.text
    return {"batch": batch, "run": run, "test": test, "laboratory": laboratory}


def packed_package(client: TestClient, packer) -> dict:
    """Pack whatever the laboratory approved, and hand back the packages."""
    worklist = client.get(f"{API}/packaging/approved-batches", headers=packer["headers"])
    assert worklist.status_code == 200, worklist.text
    batch = worklist.json()["data"][0]
    run = open_run(
        client,
        packer["headers"],
        batch["batch_id"],
        packaging_unit_id=packer["unit"]["id"],
        # The run's arithmetic has to add up: size × count is the quantity
        # packed, and the batch here has 12.9 kg to pack.
        package_size="0.5",
        number_of_packages=25,
    )
    client.post(f"{API}/packaging/{run['id']}/start", headers=packer["headers"])
    completed = client.post(
        f"{API}/packaging/{run['id']}/complete",
        headers=packer["headers"],
        json={"packaged_quantity": "12.5"},
    )
    assert completed.status_code == 200, completed.text
    packages = client.get(
        f"{API}/packages?batch_id={batch['batch_id']}&page_size=100", headers=packer["headers"]
    ).json()["data"]
    return {"run": run, "packages": packages, "batch": batch}


def sweep_via_api(client: TestClient, admin_headers: dict) -> dict:
    response = client.post(f"{API}/blockchain/sync", headers=admin_headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


# --------------------------------------------------------------------------- #
# Recording: a real transition becomes an event, once
# --------------------------------------------------------------------------- #
def test_completing_a_harvest_records_the_collection_and_the_batch(
    client: TestClient, chain, keeper, db: Session, admin_headers
):
    hive = make_hive(client, keeper["headers"])
    result = complete_collection(client, keeper["headers"], hive, quantity="13.7")

    recorded = events(db)
    assert [str(row.tx_type) for row in recorded] == [
        "COLLECTION_COMPLETED",
        "BATCH_CREATED",
    ]
    # Recorded, and *not yet* on the chain: the sweep is what writes them.
    assert {row.status for row in recorded} == {BlockchainStatus.PENDING}
    assert chain.posted == []

    sweep_via_api(client, admin_headers)

    for row in events(db):
        assert row.status is BlockchainStatus.CONFIRMED
        assert row.tx_id
        assert row.confirmed_at is not None
    assert chain.type_counts() == {"COLLECTION_COMPLETED": 1, "BATCH_CREATED": 1}

    # The payload carries the records' own values — the codes the rest of the
    # platform prints, and the quantities that were actually harvested.
    collection_event = chain.latest("COLLECTION_COMPLETED")
    assert collection_event["batch_id"] == result["batch"]["batch_code"]
    assert collection_event["payload"]["collection_id"] == result["collection"]["collection_code"]
    assert collection_event["payload"]["quantity"] == 13.7
    assert collection_event["payload"]["hive_ids"] == [hive["hive_code"]]
    assert collection_event["payload"]["status"] == "COMPLETED"

    batch_event = chain.latest("BATCH_CREATED")
    assert batch_event["payload"]["batch_id"] == result["batch"]["batch_code"]
    assert batch_event["payload"]["quantity"] == 13.7
    assert batch_event["payload"]["source_hives"] == [hive["hive_code"]]


def test_the_same_event_is_never_written_to_the_chain_twice(
    client: TestClient, chain, keeper, db: Session, admin_headers
):
    hive = make_hive(client, keeper["headers"])
    complete_collection(client, keeper["headers"], hive)

    sweep_via_api(client, admin_headers)
    first_round = len(chain.posted)
    assert first_round == 2

    # A second sweep, the retry path of the completion endpoint, and a second
    # browser tab all have to leave the ledger exactly as it was.
    sweep_via_api(client, admin_headers)
    collection_id = client.get(f"{API}/collections", headers=keeper["headers"]).json()["data"][0]["id"]
    client.post(f"{API}/collections/{collection_id}/complete", headers=keeper["headers"])
    sweep_via_api(client, admin_headers)

    assert len(chain.posted) == first_round
    assert len(events(db)) == 2
    confirmed = [row for row in events(db) if row.status is BlockchainStatus.CONFIRMED]
    assert len({row.tx_id for row in confirmed}) == 2  # one transaction per event, not per attempt


def test_every_stage_of_the_supply_chain_records_its_own_event(
    client: TestClient, chain, admin_headers, processor, technician, keeper, packer, db: Session
):
    """The journey from harvest to the packing floor, event by event."""
    journey = approved_batch(client, admin_headers, processor, technician, keeper)
    batch = journey["batch"]
    sweep_via_api(client, admin_headers)  # the worker's job, done explicitly

    # Processing: started, then completed, with the quantities that moved.
    started = chain.latest("PROCESSING_STARTED")
    assert started is not None, "PROCESSING_STARTED was not recorded"
    assert started["payload"]["batch_id"] == batch["batch_code"]
    completed = chain.latest("PROCESSING_COMPLETED")
    assert completed["payload"]["input_quantity"] == 13.7
    assert completed["payload"]["output_quantity"] == 12.9
    assert completed["payload"]["processing_type"] == "Filtering"

    # Laboratory: the sample, then the verdict — and the verdict carries the
    # measured values it was taken on.
    assert chain.latest("LAB_TEST_STARTED")["payload"]["sample_code"]
    verdict = chain.latest("QUALITY_CHECKED")
    assert verdict is not None, "QUALITY_CHECKED was not recorded"
    assert verdict["payload"]["result"] == "PASS"
    assert verdict["payload"]["measurement_summary"]["MOISTURE"]["value"] == 12.9
    assert verdict["payload"]["lab_test_id"] == journey["test"]["test_code"]

    # Packaging: the run, one event per package identity, and the run's own event.
    packed = packed_package(client, packer)
    sweep_via_api(client, admin_headers)
    assert packed["batch"]["batch_id"] == batch["id"]
    assert chain.latest("PACKAGING_STARTED")["payload"]["packaging_id"] == packed["run"]["packaging_code"]
    package_events = chain.submissions_for("PACKAGE_CREATED")
    assert len(package_events) == 25
    assert {row["payload"]["package_id"] for row in package_events} == {
        row["package_code"] for row in packed["packages"]
    }
    assert chain.latest("PACKAGED")["payload"]["package_count"] == 25

    # Distribution has not happened, so nothing about it is on the ledger: the
    # platform never writes an event ahead of the action that earns it.
    assert chain.latest("DISTRIBUTION_CREATED") is None
    assert chain.latest("DELIVERED") is None
    # And every event is a distinct logical event: one row per id.
    rows = events(db)
    assert len({row.event_id for row in rows}) == len(rows)


def test_a_pass_releases_the_batch_and_the_ledger_says_which_decision_it_was(
    client: TestClient, chain, admin_headers, processor, technician, keeper
):
    journey = approved_batch(client, admin_headers, processor, technician, keeper)
    sweep_via_api(client, admin_headers)
    assert chain.latest("QUALITY_CHECKED") is not None
    assert chain.latest("QUALITY_FAILED") is None
    assert chain.latest("QUALITY_HOLD") is None
    detail = client.get(f"{API}/batches/{journey['batch']['id']}", headers=keeper["headers"]).json()["data"]
    assert detail["status"] in ("APPROVED", "PACKAGING_READY")


def test_a_failing_measurement_is_recorded_as_a_failure_and_blocks_packaging(
    client: TestClient, chain, admin_headers, processor, technician, keeper
):
    journey = approved_batch(client, admin_headers, processor, technician, keeper, moisture="24.5")
    sweep_via_api(client, admin_headers)
    failed = chain.latest("QUALITY_FAILED")
    assert failed is not None, "a failing measurement must be recorded as QUALITY_FAILED"
    assert failed["payload"]["result"] == "FAIL"
    assert chain.latest("QUALITY_CHECKED") is None
    detail = client.get(f"{API}/batches/{journey['batch']['id']}", headers=keeper["headers"]).json()["data"]
    assert detail["status"] == "REJECTED"


def test_a_hold_is_its_own_event_and_the_override_is_added_beside_it(
    client: TestClient, chain, admin_headers, processor, technician, keeper, db: Session
):
    """HOLD stays on the ledger; PROCEEDED_WITH_RISK is written next to it.

    The one thing the chain must never show is a failure quietly becoming a
    pass. HoneyChain's rule is that an override *adds* an event — the decision
    and who made it — and leaves the measurement's own verdict where it is.
    """
    journey = approved_batch(client, admin_headers, processor, technician, keeper, moisture="24.5")
    test_id = journey["test"]["id"]
    # A failing measurement completed the test as REJECTED, so the override path
    # runs from a fresh hold on the same batch's record: the laboratory closed
    # the test without a decision, which is where a person is asked to decide.
    held = client.post(
        f"{API}/lab-tests",
        headers=technician["headers"],
        json={
            "batch_id": journey["batch"]["id"],
            "laboratory_id": journey["laboratory"]["id"],
            "sample_quantity": "0.2",
            "retest_reason": "A second sample was taken for review.",
        },
    )
    assert held.status_code == 201, held.text
    second = held.json()["data"]
    client.post(
        f"{API}/lab-tests/{second['id']}/results",
        headers=technician["headers"],
        json={"parameter_code": "MOISTURE", "value": "24.5"},
    )
    on_hold = client.post(
        f"{API}/lab-tests/{second['id']}/hold",
        headers=technician["headers"],
        json={"reason": "Quality review required before this batch goes anywhere."},
    )
    assert on_hold.status_code == 200, on_hold.text
    sweep_via_api(client, admin_headers)

    assert chain.latest("QUALITY_HOLD") is not None, "a hold must be recorded as QUALITY_HOLD"
    assert chain.latest("PROCEEDED_WITH_RISK") is None

    # The development override is switched on for this test alone, exactly as a
    # development installation would have it, and switched back after.
    from app.core.config import get_settings

    settings = get_settings()
    previous_override = settings.LAB_ALLOW_RISK_OVERRIDE
    settings.LAB_ALLOW_RISK_OVERRIDE = True
    try:
        response = client.post(
            f"{API}/lab-tests/{second['id']}/proceed-with-risk",
            headers=technician["headers"],
            json={
                "confirmation": "PROCEED",
                "reason": "Demo override reviewed with the cluster officer.",
            },
        )
    finally:
        settings.LAB_ALLOW_RISK_OVERRIDE = previous_override
    assert response.status_code == 200, response.text
    sweep_via_api(client, admin_headers)

    types = [str(row.tx_type) for row in events(db)]
    assert "PROCEEDED_WITH_RISK" in types
    # Order: what the laboratory found, then who decided to continue anyway.
    assert types.index("QUALITY_HOLD") < types.index("PROCEEDED_WITH_RISK")
    risk = chain.latest("PROCEEDED_WITH_RISK")
    assert risk["payload"]["override_status"] == "APPROVED_WITH_RISK"
    assert risk["payload"]["approved_by"], "the override must name the account that made it"
    assert risk["payload"]["reason"]
    # The hold is still on the ledger, unrewritten, and the batch moved on.
    hold = chain.latest("QUALITY_HOLD")
    assert hold["payload"]["hold_reason"]
    assert hold["batch_id"] == journey["batch"]["batch_code"]
    detail = client.get(
        f"{API}/batches/{journey['batch']['id']}", headers=keeper["headers"]
    ).json()["data"]
    assert detail["status"] in ("APPROVED", "PACKAGING_READY")


# --------------------------------------------------------------------------- #
# Failure, retry and honesty about status
# --------------------------------------------------------------------------- #
def test_an_outage_leaves_the_record_intact_and_the_event_retryable(
    client: TestClient, chain, keeper, db: Session, admin_headers
):
    chain.offline(True)
    hive = make_hive(client, keeper["headers"])
    result = complete_collection(client, keeper["headers"], hive)

    # The harvest happened, whatever the chain did.
    detail = client.get(f"{API}/batches/{result['batch']['id']}", headers=keeper["headers"])
    assert detail.status_code == 200, "an unavailable blockchain must not affect the workflow"

    sweep_via_api(client, admin_headers)
    for row in events(db):
        assert row.status is BlockchainStatus.FAILED
        assert row.last_error and "unavailable" in row.last_error.lower()
        assert row.tx_id is None
        assert row.attempt_count >= 1

    # The ledger screen says exactly that — not "recorded", not blank.
    ledger = client.get(f"{API}/blockchain/transactions", headers=admin_headers).json()
    assert {row["status"] for row in ledger["data"]} == {"FAILED"}
    assert ledger["data"][0]["last_error"]

    # The chain comes back; the worker's next sweep (here: the sync action)
    # writes what it owed, and nothing about the events changes except their state.
    event_ids = {row.event_id for row in events(db)}
    chain.offline(False)
    sweep_via_api(client, admin_headers)
    for row in events(db):
        assert row.status is BlockchainStatus.CONFIRMED
        assert row.tx_id and row.confirmed_at
        assert row.last_error is None
    assert {row.event_id for row in events(db)} == event_ids
    assert chain.type_counts() == {"COLLECTION_COMPLETED": 1, "BATCH_CREATED": 1}


def test_a_refused_transaction_is_recorded_with_the_services_own_answer(
    client: TestClient, chain, keeper, db: Session, admin_headers
):
    chain.reject_next(2)  # both events of the harvest hit a refusing ledger
    hive = make_hive(client, keeper["headers"])
    complete_collection(client, keeper["headers"], hive)
    sweep_via_api(client, admin_headers)

    for row in events(db):
        assert row.status is BlockchainStatus.FAILED
        assert "500" in (row.last_error or "")
    assert chain.posted == []


def test_an_operator_can_retry_one_failed_event(
    client: TestClient, chain, keeper, db: Session, admin_headers
):
    chain.offline(True)
    hive = make_hive(client, keeper["headers"])
    complete_collection(client, keeper["headers"], hive)
    sweep_via_api(client, admin_headers)

    event = events(db)[0]
    assert event.status is BlockchainStatus.FAILED

    chain.offline(False)
    response = client.post(
        f"{API}/blockchain/transactions/{event.id}/retry", headers=admin_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["status"] == "CONFIRMED"
    assert body["tx_id"]
    assert body["last_error"] is None


def test_the_detailed_health_report_carries_the_outbox_and_no_address(
    client: TestClient, chain, keeper, admin_headers, db: Session
):
    """The unauthenticated component report is about counters, never config."""
    hive = make_hive(client, keeper["headers"])
    complete_collection(client, keeper["headers"], hive)

    report = client.get(f"{API}/health/detailed")
    assert report.status_code == 200, report.text
    blockchain = report.json()["components"]["blockchain"]
    assert blockchain["status"] in {"ok", "degraded"}, blockchain
    assert blockchain["enabled"] is True and blockchain["configured"] is True
    assert blockchain["pending"] == len(events(db))
    assert blockchain["events_recorded"] == len(events(db))
    assert chain.url not in report.text


def test_the_health_endpoint_reports_real_values(
    client: TestClient, chain, keeper, admin_headers
):
    hive = make_hive(client, keeper["headers"])
    complete_collection(client, keeper["headers"], hive)

    health = client.get(f"{API}/blockchain/health", headers=admin_headers)
    assert health.status_code == 200, health.text
    data = health.json()["data"]
    assert data["service"]["reachable"] is True
    # The service's address is server-side configuration: the screen reports
    # whether the layer is reachable, never where it lives.
    assert "base_url" not in data["service"]
    assert chain.url not in health.text
    assert data["service"]["ledger_transactions"] == len(chain.transactions)
    assert data["honeychain"]["pending"] == 2
    assert data["honeychain"]["confirmed"] == 0

    sweep_via_api(client, admin_headers)
    after = client.get(f"{API}/blockchain/health", headers=admin_headers).json()["data"]
    assert after["honeychain"]["confirmed"] == 2
    assert after["honeychain"]["pending"] == 0
    assert after["honeychain"]["last_confirmed_tx_id"]


# --------------------------------------------------------------------------- #
# The ledgers and their scopes
# --------------------------------------------------------------------------- #
def test_the_ledger_shows_the_payload_the_record_and_the_transaction(
    client: TestClient, chain, keeper, admin_headers
):
    hive = make_hive(client, keeper["headers"])
    result = complete_collection(client, keeper["headers"], hive)
    sweep_via_api(client, admin_headers)

    listing = client.get(f"{API}/blockchain/transactions", headers=admin_headers).json()
    assert listing["meta"]["total_items"] == 2
    row = next(item for item in listing["data"] if item["tx_type"] == "COLLECTION_COMPLETED")
    assert row["batch_code"] == result["batch"]["batch_code"]
    assert row["status"] == "CONFIRMED"
    assert row["payload"]["quantity"] == 13.7
    assert row["status_label"] == "Confirmed"

    detail = client.get(f"{API}/blockchain/transactions/{row['id']}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["tx_id"] == row["tx_id"]

    # Filtering happens in the database: a filter that matches nothing returns an
    # empty page with a total of zero, not a page of everything.
    filtered = client.get(
        f"{API}/blockchain/transactions?tx_type=DELIVERED", headers=admin_headers
    ).json()
    assert filtered["data"] == []
    assert filtered["meta"]["total_items"] == 0


def test_the_chain_ledger_shows_the_services_own_records_and_marks_what_is_unlinked(
    client: TestClient, chain, keeper, admin_headers
):
    hive = make_hive(client, keeper["headers"])
    complete_collection(client, keeper["headers"], hive)
    sweep_via_api(client, admin_headers)

    response = client.get(f"{API}/blockchain/ledger", headers=admin_headers)
    assert response.status_code == 200, response.text
    rows = response.json()["data"]

    # Every transaction the service holds is present, including the three that
    # existed before HoneyChain wrote anything — nothing was deleted or rewritten.
    assert len(rows) == len(chain.transactions)
    legacy = [row for row in rows if row["batch_id"] in ("HC-REAL-001", "TEST-001", "HC-GNT-2026-001")]
    assert len(legacy) == 3
    assert all(row["honey_chain_recorded"] is False for row in legacy)
    assert all(row["matched_event_id"] is None for row in legacy)

    written = [row for row in rows if row["honey_chain_recorded"]]
    assert len(written) == 2
    assert all(row["matched_event_id"] for row in written)


def test_a_legacy_transaction_is_never_attached_to_a_batch(
    client: TestClient, chain, admin_headers, keeper
):
    """The old rows stay in the raw ledger and out of everybody's traceability."""
    hive = make_hive(client, keeper["headers"])
    result = complete_collection(client, keeper["headers"], hive)
    sweep_via_api(client, admin_headers)

    trace = client.get(
        f"{API}/blockchain/batches/{result['batch']['id']}", headers=admin_headers
    ).json()["data"]
    assert all(row["tx_id"] not in {"a" * 64, "b" * 64, "c" * 64} for row in trace["transactions"])
    assert {row["tx_type"] for row in trace["transactions"]} == {
        "COLLECTION_COMPLETED",
        "BATCH_CREATED",
    }


def test_a_cluster_officer_reads_the_same_ledger_the_administrator_reads(
    client: TestClient, admin_headers, keeper, kvic_headers
):
    """The officer's ledger is bounded by the cluster registry, like their batches.

    The rule this platform applies everywhere: a cluster officer reads the
    records of the clusters they are entitled to open — which is the registry,
    not the district line on their profile — and the records of batches that
    name no cluster are shown rather than hidden, because a row that vanishes is
    a relationship nobody can repair.
    """
    hive = make_hive(client, keeper["headers"])
    complete_collection(client, keeper["headers"], hive)

    officer_view = client.get(f"{API}/blockchain/transactions", headers=kvic_headers)
    assert officer_view.status_code == 200, officer_view.text
    admin_view = client.get(f"{API}/blockchain/transactions", headers=admin_headers).json()
    assert officer_view.json()["meta"]["total_items"] == admin_view["meta"]["total_items"] == 2
    assert {row["event_id"] for row in officer_view.json()["data"]} == {
        row["event_id"] for row in admin_view["data"]
    }


def test_roles_that_may_not_read_the_ledger_are_refused(client: TestClient, keeper, chain):
    refused = client.get(f"{API}/blockchain/transactions", headers=keeper["headers"])
    assert refused.status_code == 403, refused.text
    anonymous = client.get(f"{API}/blockchain/transactions")
    assert anonymous.status_code == 401, anonymous.text


# --------------------------------------------------------------------------- #
# QR and the customer's page
# --------------------------------------------------------------------------- #
def test_a_package_qr_resolves_to_a_customer_page_that_only_shows_what_happened(
    client: TestClient, chain, admin_headers, processor, technician, keeper, packer
):
    journey = approved_batch(client, admin_headers, processor, technician, keeper)
    packed = packed_package(client, packer)
    package = packed["packages"][0]

    issued = client.post(f"{API}/blockchain/packages/{package['id']}/qr", headers=packer["headers"])
    assert issued.status_code == 200, issued.text
    identity = issued.json()["data"]
    assert identity["qr_payload"] == f"http://trace.test/trace/{package['package_code']}"
    assert identity["svg"].lstrip().startswith("<")
    assert identity["event_id"] == f"QR-{package['package_code']}-GENERATED"
    # The label also carries a stable id beside the code. It is derived from the
    # package, so it is the same id after a reprint, and it resolves on its own
    # route — a scanner that stored the id and a link that carries the code must
    # land on the same jar.
    assert identity["qr_id"] == f"QR-{package['package_code']}"
    by_id = client.get(f"{API}/verify/{identity['qr_id']}")
    assert by_id.status_code == 200, by_id.text
    assert by_id.json()["data"]["package"]["package_code"] == package["package_code"]
    assert client.get(f"{API}/verify/HC-PKG-2099-999999").status_code == 404

    # Issuing again is not a second identity and not a second transaction.
    again = client.post(f"{API}/blockchain/packages/{package['id']}/qr", headers=packer["headers"])
    assert again.json()["data"]["qr_payload"] == identity["qr_payload"]
    sweep_via_api(client, admin_headers)
    assert len(chain.submissions_for("QR_GENERATED")) == 1

    # The customer opens the code — no account, no token.
    page = client.get(f"{API}/trace/{package['package_code']}")
    assert page.status_code == 200, page.text
    data = page.json()["data"]
    assert data["package"]["package_code"] == package["package_code"]
    assert data["product"]["batch_code"] == journey["batch"]["batch_code"]
    assert data["source"]["beekeeper"]
    assert data["source"]["collected_quantity"] == 13.7
    assert data["laboratory"][0]["result"] == "PASS"
    assert data["packaging"]["packaging_code"] == packed["run"]["packaging_code"]
    assert data["qr"]["qr_id"] == f"QR-{package['package_code']}"
    assert data["verification"]["available"] is True

    # The customer page's ledger lists the events that exist, with their
    # transaction ids, and says nothing about events that have not happened.
    types = [row["tx_type"] for row in data["blockchain"]["transactions"]]
    assert "BATCH_CREATED" in types and "PACKAGED" in types and "QR_GENERATED" in types
    assert "DELIVERED" not in types and "RETAILER_RECEIVED" not in types
    stages = {row["stage"]: row for row in data["timeline"]}
    assert stages["COLLECTION"]["reached"] is True
    assert stages["DELIVERED"]["reached"] is False
    assert stages["RETAILER"]["reached"] is False

    # Nothing private travelled to the customer: no account, no email, no notes,
    # no internal identifiers, no telemetry.
    blob = page.text.lower()
    for forbidden in (
        keeper["_request"]["email"].lower(),
        "password",
        "token",
        str(journey["batch"]["id"]).lower(),
        "telemetry",
    ):
        assert forbidden not in blob, f"the customer page leaked {forbidden!r}"


def test_opening_the_page_verifies_the_package_once_and_counts_the_rest(
    client: TestClient, chain, admin_headers, processor, technician, keeper, packer, db: Session
):
    approved_batch(client, admin_headers, processor, technician, keeper)
    packed = packed_package(client, packer)
    package = packed["packages"][0]
    client.post(f"{API}/blockchain/packages/{package['id']}/qr", headers=packer["headers"])

    for _ in range(3):
        assert client.get(f"{API}/trace/{package['package_code']}").status_code == 200

    sweep_via_api(client, admin_headers)
    row = db.get(HoneyPackage, uuid.UUID(str(package["id"])))
    db.refresh(row)
    assert row.qr_scan_count == 3
    # One verification event for the package, not one per refresh.
    assert len(chain.submissions_for("CUSTOMER_QR_VERIFIED")) == 1
    assert len(events(db, tx_type=BlockchainEventType.CUSTOMER_QR_VERIFIED)) == 1


def test_an_unknown_package_code_is_a_not_found(client: TestClient, chain):
    response = client.get(f"{API}/trace/HC-PKG-2099-999999")
    assert response.status_code == 404, response.text


def test_the_retailers_receipt_completes_the_chain_and_the_customer_sees_it(
    client: TestClient, chain, admin_headers, processor, technician, keeper, packer, distributor, retailer
):
    approved_batch(client, admin_headers, processor, technician, keeper)
    packed = packed_package(client, packer)
    package = packed["packages"][0]
    client.post(f"{API}/packages/{package['id']}/release", headers=packer["headers"], json={})

    shipment = client.post(
        f"{API}/distribution",
        headers=distributor["headers"],
        json={
            "package_id": package["id"],
            "quantity": "0.5",
            "destination": "Guntur market",
            "retailer_id": str(retailer["id"]),
        },
    )
    assert shipment.status_code == 201, shipment.text
    shipment_id = shipment.json()["data"]["id"]

    for action in ("dispatch", "in-transit", "deliver"):
        response = client.post(
            f"{API}/distribution/{shipment_id}/{action}", headers=distributor["headers"], json={}
        )
        assert response.status_code == 200, response.text
    received = client.post(
        f"{API}/retailer/shipments/{shipment_id}/receive",
        headers=retailer["headers"],
        json={"receipt_notes": "Cartons intact."},
    )
    assert received.status_code == 200, received.text
    sweep_via_api(client, admin_headers)

    assert chain.type_counts()["DISTRIBUTION_CREATED"] == 1
    assert chain.type_counts()["DISTRIBUTION_DISPATCHED"] == 1
    assert chain.type_counts()["IN_TRANSIT"] == 1
    assert chain.type_counts()["DELIVERED"] == 1
    assert chain.type_counts()["RETAILER_RECEIVED"] == 1

    page = client.get(f"{API}/trace/{package['package_code']}").json()["data"]
    stages = {row["stage"]: row for row in page["timeline"]}
    assert stages["DELIVERED"]["reached"] is True
    assert stages["RETAILER"]["reached"] is True
    types = [row["tx_type"] for row in page["blockchain"]["transactions"]]
    assert "RETAILER_RECEIVED" in types
    # And the customer still learns nothing about who received it beyond the shop.
    customer_page = client.get(f"{API}/trace/{package['package_code']}")
    assert retailer["email"].lower() not in customer_page.text.lower()


# --------------------------------------------------------------------------- #
# The configuration is not hard-coded
# --------------------------------------------------------------------------- #
def test_the_client_reads_its_configuration_from_the_environment(monkeypatch):
    from app.services.blockchain.client import BlockchainClient

    monkeypatch.setenv("BLOCKCHAIN_BASE_URL", "http://ledger.example:3001/")
    monkeypatch.setenv("BLOCKCHAIN_ENABLED", "true")
    clear_settings_cache()
    client = BlockchainClient()
    assert client.transactions_url == "http://ledger.example:3001/transactions"
    assert client.enabled and client.configured
    clear_settings_cache()


def test_switching_the_integration_off_records_events_without_submitting_them(
    client: TestClient, monkeypatch, chain, keeper, db: Session, admin_headers
):
    monkeypatch.setenv("BLOCKCHAIN_ENABLED", "false")
    clear_settings_cache()
    hive = make_hive(client, keeper["headers"])
    trace = complete_collection(client, keeper["headers"], hive)

    # The workflow is untouched and the events are still recorded. They are
    # marked SKIPPED with the reason — "not on the chain, because this
    # installation is not writing to it" — which is a fact, not a lie about a
    # transaction that never happened.
    sweep_via_api(client, admin_headers)
    assert {row.status for row in events(db)} == {BlockchainStatus.SKIPPED}
    assert all(row.tx_id is None for row in events(db))
    assert all("switched off" in (row.last_error or "") for row in events(db))

    # A skipped event is not on the chain, and no screen may say otherwise: the
    # batch's own verdict reports it as not synchronized, counts the skipped
    # steps separately and states the reason.
    response = client.get(
        f"{API}/blockchain/batches/{trace['batch']['id']}", headers=keeper["headers"]
    )
    assert response.status_code == 200, response.text
    summary = response.json()["data"]
    assert summary["blockchain"]["synchronized"] is False
    assert summary["blockchain"]["skipped"] == len(events(db))
    assert summary["blockchain"]["enabled"] is False
    assert "switched off" in summary["blockchain"]["note"]

    # Switching the integration back on owes the chain nothing less than the
    # whole gap: the next sweep writes the events that were skipped.
    monkeypatch.setenv("BLOCKCHAIN_ENABLED", "true")
    clear_settings_cache()
    sweep_via_api(client, admin_headers)
    assert {row.status for row in events(db)} == {BlockchainStatus.CONFIRMED}
