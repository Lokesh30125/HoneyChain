"""Phase 7 — shipping packages, receiving them, and the limits on both.

The claims this module defends, in the order a shipment makes them:

* a package must have been released before a shipment may name it, and a
  shipment may never carry more than the package has left — the honey is counted
  against the package, not the batch, so two shipments from one package cannot
  both be for the whole of it;
* the journey is a one-way street — ``READY_FOR_DISPATCH`` → ``DISPATCHED`` →
  ``IN_TRANSIT`` → ``DELIVERED`` — a delivery before a dispatch is refused, a
  second dispatch of a delivered shipment is refused, and a cancelled shipment is
  quantity nobody moved;
* the batch follows its packages — dispatch moves ``PACKAGED`` →
  ``DISTRIBUTION``, and the batch is complete only when every package has been
  received, nothing is left to pack and no shipment is still out;
* the retailer's confirmation is a record of its own — a receiver, a time and a
  note kept beside the carrier's delivery, never instead of it, and never before
  the dispatch;
* the roles stay in their lanes — a retailer cannot raise, dispatch or deliver a
  shipment and cannot edit the package, the batch or the laboratory record it
  came from; a beekeeper reads the downstream journey and changes none of it;
* there is one set of records — the beekeeper, the officer and the parties to the
  shipment read the same rows, and none of them is a copy.

Every check goes through the HTTP API.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.distribution import Distribution
from app.models.enums import (
    AuditAction,
    BatchStatus,
    DistributionStatus,
    PackageStatus,
    UserRole,
)
from app.models.honey_batch import HoneyBatch
from app.models.packaging import HoneyPackage

API = "/api/v1"

#: The source every configured limit in this project carries: a demonstration
#: limit for the pilot, not a regulatory or certification standard.
DEMO_SOURCE = "Project-configured demonstration limit for tests (not a regulatory standard)"

HIVE_PAYLOAD = {
    "bee_species": "Apis cerana indica",
    "village": "Tenali",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "pincode": "522201",
}

LABORATORY_PAYLOAD = {
    "name": "Phase 7 Distribution Laboratory",
    "location": "Guntur",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "notes": "Phase 7 test fixture",
}

PACKAGING_UNIT_PAYLOAD = {
    "name": "Phase 7 Distribution Packing Unit",
    # The registry identifier an administrator records when the unit is registered.
    "registration_identifier": "REG-PHASE7-DIST",
    "location": "Guntur",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "notes": "Phase 7 test fixture",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def sign_in(client: TestClient, payload: dict) -> dict[str, str]:
    response = client.post(
        f"{API}/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def approve_batch(
    client: TestClient,
    headers: dict,
    lab_headers: dict,
    batch_id: str,
    *,
    measured: str,
    config_headers: dict,
) -> dict:
    """Process and laboratory-approve a collected batch through the real screens' API.

    The processing run is done with administrative rights; the laboratory work is
    done by a technician, because a sample belongs to a named technician from the
    moment it is opened — a laboratory test never sits in the queue unowned.
    """
    run = client.post(
        f"{API}/processing",
        headers=headers,
        json={"batch_id": batch_id, "processing_type": "FILTERING"},
    ).json()["data"]
    client.post(f"{API}/processing/{run['id']}/start", headers=headers)
    client.post(
        f"{API}/processing/{run['id']}/complete",
        headers=headers,
        json={"input_quantity": "12.0", "output_quantity": measured},
    )
    laboratory = client.post(
        f"{API}/laboratories", headers=lab_headers, json=LABORATORY_PAYLOAD
    ).json()["data"]
    test = client.post(
        f"{API}/lab-tests",
        headers=lab_headers,
        json={
            "batch_id": batch_id,
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.25",
            "sample_unit": "GRAM",
        },
    ).json()["data"]
    # A verdict needs a range to judge against, so the catalogue is configured
    # first — with the demonstration source the project always uses, never as a
    # regulatory standard. With the range in place, 17.2 passes and the batch is
    # approved by the laboratory's own rule engine rather than by an override.
    parameter = client.get(f"{API}/lab-parameters", headers=lab_headers).json()["data"][0]
    configured = client.patch(
        f"{API}/lab-parameters/{parameter['code']}",
        headers=config_headers,
        json={
            "reference_min": "10",
            "reference_max": "20",
            "reference_source": DEMO_SOURCE,
            "is_required": True,
        },
    )
    assert configured.status_code == 200, configured.text
    recorded = client.post(
        f"{API}/lab-tests/{test['id']}/results",
        headers=lab_headers,
        json={"parameter_code": parameter["code"], "value": "17.2"},
    )
    assert recorded.status_code == 201, recorded.text
    completed = client.post(f"{API}/lab-tests/{test['id']}/complete", headers=lab_headers, json={})
    assert completed.status_code == 200, completed.text
    return client.get(f"{API}/batches/{batch_id}", headers=headers).json()["data"]


def shipment_row(db: Session, distribution_id) -> Distribution:
    record = db.get(Distribution, uuid.UUID(str(distribution_id)))
    assert record is not None
    db.refresh(record)
    return record


def package_row(db: Session, package_id) -> HoneyPackage:
    record = db.get(HoneyPackage, uuid.UUID(str(package_id)))
    assert record is not None
    db.refresh(record)
    return record


def batch_row(db: Session, batch_id) -> HoneyBatch:
    record = db.get(HoneyBatch, uuid.UUID(str(batch_id)))
    assert record is not None
    db.refresh(record)
    return record


def audit_actions(db: Session, action: AuditAction) -> list[AuditLog]:
    db.expire_all()
    return db.query(AuditLog).filter(AuditLog.action == str(action)).all()


#: The shop a shipment is addressed to when a test does not name one. A shipment
#: must name a retailer — it is what puts the consignment in that shop's inbound
#: list and lets the receipt be confirmed by the receiver — so the helper needs a
#: real account to name rather than leaving the field empty.
DEFAULT_RETAILER_ID: str | None = None


def ship(client: TestClient, headers: dict, package_id, quantity: str, **payload) -> dict:
    body = {"package_id": str(package_id), "quantity": quantity, "destination": "Guntur market"}
    body.update(payload)
    # Only when the test has not named its own receiver, and never in addition to
    # one: naming a shop by account *and* by email is refused on purpose.
    if DEFAULT_RETAILER_ID is not None and not body.get("retailer_id") and not body.get("retailer_email"):
        body["retailer_id"] = DEFAULT_RETAILER_ID
    assert body.get("retailer_id") or body.get("retailer_email"), (
        "a shipment must name the retailer it is for"
    )
    response = client.post(f"{API}/distribution", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def move(client: TestClient, headers: dict, shipment_id, action: str, **payload):
    """Dispatch, in-transit and deliver — the carrier's side of the journey."""
    return client.post(f"{API}/distribution/{shipment_id}/{action}", headers=headers, json=payload)


def receive(client: TestClient, headers: dict, shipment_id, **payload):
    """The retailer's own endpoint for confirming what arrived."""
    return client.post(
        f"{API}/retailer/shipments/{shipment_id}/receive", headers=headers, json=payload
    )


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def keeper(client: TestClient, register_user):
    payload = register_user(name="Phase 7 Distribution Beekeeper", email=None)
    payload["headers"] = {"Authorization": f"Bearer {payload['access_token']}"}
    hive = client.post(f"{API}/hives", headers=payload["headers"], json=HIVE_PAYLOAD)
    assert hive.status_code == 201, hive.text
    payload["hive"] = hive.json()["data"]
    collection = client.post(
        f"{API}/collections",
        headers=payload["headers"],
        json={
            "hives": [{"hive_id": payload["hive"]["id"], "quantity": "12.0"}],
            "collection_date": date.today().isoformat(),
            "unit": "KG",
        },
    )
    assert collection.status_code == 201, collection.text
    completed = client.post(
        f"{API}/collections/{collection.json()['data']['id']}/complete", headers=payload["headers"]
    )
    assert completed.status_code == 200, completed.text
    batch_id = completed.json()["meta"]["batch"]["id"]
    payload["batch"] = client.get(
        f"{API}/batches/{batch_id}", headers=payload["headers"]
    ).json()["data"]
    return payload


@pytest.fixture()
def technician(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.LAB_TECHNICIAN, name="Phase 7 Distribution Technician", password="TechPass123"
    )
    payload["headers"] = sign_in(client, payload)
    payload["id"] = str(payload["id"])
    return payload


@pytest.fixture()
def approved(client: TestClient, admin_headers, technician, keeper):
    return approve_batch(
        client,
        admin_headers,
        technician["headers"],
        keeper["batch"]["id"],
        measured="12.0",
        config_headers=admin_headers,
    )


@pytest.fixture()
def packer(client: TestClient, make_privileged_user, admin_headers):
    """A packing operator, attached to the unit it works at.

    The unit is registered and the account attached the way the platform does it —
    an administrator registers the facility and names the operator — because a run
    records *which* facility packed the honey, and an unattached account cannot
    open one.
    """
    payload = make_privileged_user(
        role=UserRole.PACKAGING_UNIT, name="Phase 7 Distribution Packer", password="PackPass123"
    )
    payload["headers"] = sign_in(client, payload)
    unit = client.post(
        f"{API}/packaging-units", headers=admin_headers, json=PACKAGING_UNIT_PAYLOAD
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
def packaged_run(client: TestClient, packer, approved):
    """Two packages of 6.0 KG each — the whole of a 12.0 KG batch. Not released."""
    run = client.post(
        f"{API}/packaging",
        headers=packer["headers"],
        json={
            "batch_id": approved["id"],
            "packaging_unit_id": packer["unit"]["id"],
            "packaging_type": "JAR",
            "packaged_quantity": "12.0",
            "package_size": "6.0",
            "number_of_packages": 2,
        },
    ).json()["data"]
    client.post(f"{API}/packaging/{run['id']}/start", headers=packer["headers"])
    completed = client.post(
        f"{API}/packaging/{run['id']}/complete", headers=packer["headers"], json={}
    )
    assert completed.status_code == 200, completed.text
    detail = completed.json()["data"]
    assert detail["packages"][0]["status"] == "CREATED"
    return detail


@pytest.fixture()
def packed(client: TestClient, packer, packaged_run):
    """The same two packages, released by the packing unit and ready to move."""
    released = client.post(
        f"{API}/packaging/{packaged_run['id']}/release", headers=packer["headers"]
    )
    assert released.status_code == 200, released.text
    packaged_run["packages"] = released.json()["data"]
    assert all(row["status"] == "READY_FOR_DISTRIBUTION" for row in packaged_run["packages"])
    return packaged_run


@pytest.fixture()
def distributor(client: TestClient, make_privileged_user, default_retailer):
    global DEFAULT_RETAILER_ID  # noqa: PLW0603 - the shipping helper reads it
    DEFAULT_RETAILER_ID = default_retailer["id"]
    payload = make_privileged_user(
        role=UserRole.DISTRIBUTOR, name="Phase 7 Distributor", password="DistPass123"
    )
    payload["headers"] = sign_in(client, payload)
    payload["id"] = str(payload["id"])
    return payload


@pytest.fixture()
def default_retailer(client: TestClient, make_privileged_user):
    """One live shop account the shipping helper addresses by default.

    Created once per session and reused: the tests that are *about* retailers build
    their own, and every other test should not have to.
    """
    payload = make_privileged_user(
        role=UserRole.RETAILER, name="Phase 7 Default Retailer", password="RetailPass123"
    )
    payload["headers"] = sign_in(client, payload)
    payload["id"] = str(payload["id"])
    return payload


@pytest.fixture()
def retailer(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.RETAILER, name="Phase 7 Retailer", password="RetailPass123"
    )
    payload["headers"] = sign_in(client, payload)
    payload["id"] = str(payload["id"])
    return payload


@pytest.fixture()
def other_retailer(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.RETAILER, name="Phase 7 Other Retailer", password="RetailPass123"
    )
    payload["headers"] = sign_in(client, payload)
    payload["id"] = str(payload["id"])
    return payload


@pytest.fixture()
def dispatched(client: TestClient, distributor, packed, retailer):
    """One shipment, dispatched, of the first package in full."""
    package = packed["packages"][0]
    shipment = ship(
        client, distributor["headers"], package["id"], "6.0", retailer_id=retailer["id"]
    )
    assert move(client, distributor["headers"], shipment["id"], "dispatch").status_code == 200
    return shipment


# --------------------------------------------------------------------------- #
# Raising a shipment
# --------------------------------------------------------------------------- #
def test_an_unreleased_package_cannot_be_shipped(client, distributor, packaged_run):
    package = packaged_run["packages"][0]
    response = client.post(
        f"{API}/distribution",
        headers=distributor["headers"],
        json={
            "package_id": package["id"],
            "quantity": "0.2",
            "destination": "Guntur market",
            # Named, so the refusal under test is the one about the package's
            # readiness rather than the one about a missing receiver.
            "retailer_id": DEFAULT_RETAILER_ID,
        },
    )
    assert response.status_code == 409, response.text
    details = response.json()["error"]["details"]
    assert details["package_status"] == "CREATED"


def test_a_released_package_starts_ready_for_dispatch(client, distributor, packed):
    """Raising a shipment is not dispatching it, and the honey stays in the package."""
    package = packed["packages"][0]
    shipment = ship(client, distributor["headers"], package["id"], "6.0")
    assert shipment["status"] == "READY_FOR_DISPATCH"
    assert shipment["dispatch_date"] is None
    assert shipment["dispatched_at"] is None
    assert shipment["quantity"] == "6.000"
    assert shipment["unit"] == package["unit"]
    assert shipment["distributor_id"] == str(distributor["id"])


def test_more_than_the_package_holds_is_refused(client, distributor, packed):
    package = packed["packages"][0]
    response = client.post(
        f"{API}/distribution",
        headers=distributor["headers"],
        json={
            "package_id": package["id"],
            "quantity": "7.0",
            "destination": "Guntur market",
            "retailer_id": DEFAULT_RETAILER_ID,
        },
    )
    assert response.status_code == 422, response.text
    details = response.json()["error"]["details"]
    assert details["package_quantity"] == "6.000"
    assert details["remaining_quantity"] == "6.000"
    assert details["requested"] == "7.0"


def test_a_second_shipment_cannot_exceed_what_the_first_left(client, distributor, packed):
    """Two shipments of the same package are fine; two whole ones are not."""
    package = packed["packages"][0]
    ship(client, distributor["headers"], package["id"], "4.0")
    response = client.post(
        f"{API}/distribution",
        headers=distributor["headers"],
        json={
            "package_id": package["id"],
            "quantity": "4.0",
            "destination": "Guntur market",
            "retailer_id": DEFAULT_RETAILER_ID,
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["remaining_quantity"] == "2.000"

    top_up = ship(client, distributor["headers"], package["id"], "2.0")
    assert top_up["status"] == "READY_FOR_DISPATCH"


def test_a_package_cannot_be_shipped_twice_over(client, distributor, packed):
    package = packed["packages"][0]
    ship(client, distributor["headers"], package["id"], "6.0")
    response = client.post(
        f"{API}/distribution",
        headers=distributor["headers"],
        json={
            "package_id": package["id"],
            "quantity": "0.5",
            "destination": "Guntur market",
            "retailer_id": DEFAULT_RETAILER_ID,
        },
    )
    assert response.status_code == 422, response.text
    assert Decimal(response.json()["error"]["details"]["remaining_quantity"]) == Decimal("0")


def test_a_shipment_must_name_the_retailer_it_is_for(client, distributor, packed):
    """A consignment with no receiver reaches nobody, so it is refused outright.

    This is the bug the retailer flow had: the form collected a destination and no
    retailer, the API stored ``retailer_id = NULL``, and every shop's inbound list
    came back empty because no shipment had ever been addressed to one.
    """
    package = packed["packages"][0]
    response = client.post(
        f"{API}/distribution",
        headers=distributor["headers"],
        json={
            "package_id": package["id"],
            "quantity": "1.0",
            "destination": "Guntur market",
            # No retailer, by account or by email.
        },
    )
    assert response.status_code == 422, response.text
    assert "retailer" in response.text.lower()


def test_a_shipment_can_only_be_addressed_to_a_retailer(client, distributor, packed, keeper):
    package = packed["packages"][0]
    response = client.post(
        f"{API}/distribution",
        headers=distributor["headers"],
        json={
            "package_id": package["id"],
            "quantity": "1.0",
            "destination": "Guntur market",
            "retailer_id": str(keeper["user"]["id"]),
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["role"] == "BEEKEEPER"


def test_the_caller_cannot_set_the_status_or_the_code(client, distributor, packed):
    package = packed["packages"][0]
    for extra in ({"status": "DELIVERED"}, {"distribution_code": "HC-DIST-1999-000001"}):
        response = client.post(
            f"{API}/distribution",
            headers=distributor["headers"],
            json={
                "package_id": package["id"],
                "quantity": "1.0",
                "destination": "Guntur market",
                **extra,
            },
        )
        assert response.status_code == 422, response.text


def test_a_shipment_needs_a_destination_and_a_positive_quantity(client, distributor, packed):
    package = packed["packages"][0]
    for body in (
        {"quantity": "0", "destination": "Guntur market"},
        {"quantity": "-1", "destination": "Guntur market"},
        {"quantity": "1.0", "destination": "G"},
    ):
        response = client.post(
            f"{API}/distribution",
            headers=distributor["headers"],
            json={"package_id": package["id"], **body},
        )
        assert response.status_code == 422, response.text


# --------------------------------------------------------------------------- #
# The journey, and its order
# --------------------------------------------------------------------------- #
def test_dispatch_moves_the_package_and_the_batch(client, distributor, packed, approved, db):
    package = packed["packages"][0]
    shipment = ship(client, distributor["headers"], package["id"], "6.0")
    response = move(
        client, distributor["headers"], shipment["id"], "dispatch", carrier="Test Carrier"
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "DISPATCHED"
    assert response.json()["data"]["dispatch_date"] == date.today().isoformat()
    assert package_row(db, package["id"]).status is PackageStatus.IN_DISTRIBUTION
    assert batch_row(db, approved["id"]).status is BatchStatus.DISTRIBUTION


def test_delivery_before_a_dispatch_is_refused(client, distributor, packed, db):
    package = packed["packages"][0]
    shipment = ship(client, distributor["headers"], package["id"], "6.0")
    response = move(client, distributor["headers"], shipment["id"], "deliver")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["details"]["dispatched_at"] is None
    assert shipment_row(db, shipment["id"]).status is DistributionStatus.READY_FOR_DISPATCH


def test_in_transit_before_dispatch_is_refused(client, distributor, packed):
    package = packed["packages"][0]
    shipment = ship(client, distributor["headers"], package["id"], "6.0")
    response = move(client, distributor["headers"], shipment["id"], "in-transit")
    assert response.status_code == 409, response.text


def test_a_shipment_cannot_be_dispatched_twice(client, distributor, dispatched):
    response = move(client, distributor["headers"], dispatched["id"], "dispatch")
    assert response.status_code == 409, response.text


def test_the_journey_in_order(client, distributor, packed, db):
    package = packed["packages"][0]
    shipment = ship(client, distributor["headers"], package["id"], "6.0")

    assert move(client, distributor["headers"], shipment["id"], "dispatch").status_code == 200
    in_transit = move(client, distributor["headers"], shipment["id"], "in-transit")
    assert in_transit.status_code == 200, in_transit.text
    assert in_transit.json()["data"]["status"] == "IN_TRANSIT"
    assert in_transit.json()["data"]["in_transit_at"] is not None

    delivered = move(client, distributor["headers"], shipment["id"], "deliver")
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["data"]["status"] == "DELIVERED"
    assert delivered.json()["data"]["delivered_at"] is not None
    assert package_row(db, package["id"]).status is PackageStatus.DELIVERED

    # Delivered is final: no step of the journey may be taken again.
    assert move(client, distributor["headers"], shipment["id"], "dispatch").status_code == 409
    assert move(client, distributor["headers"], shipment["id"], "in-transit").status_code == 409


def test_the_batch_is_complete_only_when_everything_arrived(
    client, distributor, default_retailer, packed, approved, db
):
    """Two packages out, two received, nothing left to pack: then, and only then.

    "Received" is the retailer's confirmation. The carrier's delivery alone
    leaves the batch in distribution, as its timeline says.
    """
    first, second = packed["packages"][0], packed["packages"][1]

    # The first package goes out in two consignments; the batch is not finished
    # while the second package has not left at all.
    part_one = ship(client, distributor["headers"], first["id"], "3.0")
    assert move(client, distributor["headers"], part_one["id"], "dispatch").status_code == 200
    assert move(client, distributor["headers"], part_one["id"], "deliver").status_code == 200
    assert batch_row(db, approved["id"]).status is BatchStatus.DISTRIBUTION

    part_two = ship(client, distributor["headers"], first["id"], "3.0")
    assert move(client, distributor["headers"], part_two["id"], "dispatch").status_code == 200
    assert move(client, distributor["headers"], part_two["id"], "deliver").status_code == 200
    # The first package is now fully received, but the second is still here.
    assert batch_row(db, approved["id"]).status is BatchStatus.DISTRIBUTION

    second_shipment = ship(client, distributor["headers"], second["id"], "6.0")
    assert move(client, distributor["headers"], second_shipment["id"], "dispatch").status_code == 200
    # In transit is not arrived: the batch is still not complete.
    assert batch_row(db, approved["id"]).status is BatchStatus.DISTRIBUTION
    assert move(client, distributor["headers"], second_shipment["id"], "deliver").status_code == 200
    # Everything has been delivered, nothing has been received yet.
    assert batch_row(db, approved["id"]).status is BatchStatus.DISTRIBUTION
    for shipment in (part_one, part_two, second_shipment):
        assert receive(client, default_retailer["headers"], shipment["id"]).status_code == 200
    assert batch_row(db, approved["id"]).status is BatchStatus.COMPLETED
    assert package_row(db, first["id"]).status is PackageStatus.DELIVERED
    assert package_row(db, second["id"]).status is PackageStatus.DELIVERED


# --------------------------------------------------------------------------- #
# The retailer's side
# --------------------------------------------------------------------------- #
def test_the_retailer_sees_the_shipment_addressed_to_them(client, distributor, retailer, other_retailer, packed):
    package = packed["packages"][0]
    shipment = ship(
        client, distributor["headers"], package["id"], "6.0", retailer_id=retailer["id"]
    )
    move(client, distributor["headers"], shipment["id"], "dispatch")

    response = client.get(f"{API}/retailer/shipments", headers=retailer["headers"])
    assert response.status_code == 200, response.text
    codes = [row["distribution_code"] for row in response.json()["data"]]
    assert shipment["distribution_code"] in codes

    # Another retailer is not merely filtered out of the list: the shipment is
    # not theirs, and asking for it by id is a 404 rather than a peek.
    other = client.get(f"{API}/retailer/shipments", headers=other_retailer["headers"])
    assert shipment["distribution_code"] not in [
        row["distribution_code"] for row in other.json()["data"]
    ]
    assert (
        client.get(
            f"{API}/distribution/{shipment['id']}", headers=other_retailer["headers"]
        ).status_code
        == 404
    )


def test_the_retailer_confirms_receipt_and_the_confirmation_is_recorded(
    client, distributor, retailer, packed, db
):
    package = packed["packages"][0]
    shipment = ship(
        client, distributor["headers"], package["id"], "6.0", retailer_id=retailer["id"]
    )
    move(client, distributor["headers"], shipment["id"], "dispatch")

    response = receive(
        client, retailer["headers"], shipment["id"], receipt_notes="Two jars, intact"
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "DELIVERED"
    assert data["received_by_id"] == str(retailer["id"])
    assert data["received_by_name"] == "Phase 7 Retailer"
    assert data["notes"] == "Two jars, intact"

    record = shipment_row(db, shipment["id"])
    assert record.received_at is not None
    assert record.delivered_at is not None
    assert record.received_by_id == uuid.UUID(str(retailer["id"]))


def test_a_receipt_before_any_dispatch_is_refused(client, distributor, retailer, packed):
    package = packed["packages"][0]
    shipment = ship(
        client, distributor["headers"], package["id"], "6.0", retailer_id=retailer["id"]
    )
    response = receive(client, retailer["headers"], shipment["id"])
    assert response.status_code == 409, response.text
    assert "dispatched" in response.json()["error"]["message"].lower()


def test_the_retailer_receives_what_is_theirs_only(client, distributor, retailer, other_retailer, packed):
    package = packed["packages"][0]
    shipment = ship(
        client, distributor["headers"], package["id"], "6.0", retailer_id=retailer["id"]
    )
    move(client, distributor["headers"], shipment["id"], "dispatch")
    response = receive(client, other_retailer["headers"], shipment["id"])
    assert response.status_code == 404, response.text


def test_a_distributor_is_not_a_receiver(client, distributor, packed):
    """Confirmation comes from the receiving end, not from the sender."""
    package = packed["packages"][0]
    shipment = ship(client, distributor["headers"], package["id"], "1.0")
    move(client, distributor["headers"], shipment["id"], "dispatch")
    response = receive(client, distributor["headers"], shipment["id"])
    assert response.status_code == 403, response.text


def test_the_retailer_cannot_drive_the_shipment(client, distributor, retailer, packed):
    package = packed["packages"][0]
    shipment = ship(
        client, distributor["headers"], package["id"], "1.0", retailer_id=retailer["id"]
    )
    for action in ("dispatch", "in-transit", "deliver", "cancel"):
        assert move(client, retailer["headers"], shipment["id"], action).status_code == 403
    assert receive(client, retailer["headers"], shipment["id"]).status_code == 409
    response = client.post(
        f"{API}/distribution",
        headers=retailer["headers"],
        json={"package_id": package["id"], "quantity": "1.0", "destination": "Guntur market"},
    )
    assert response.status_code == 403, response.text


def test_the_retailer_cannot_edit_what_came_from_upstream(client, distributor, retailer, packed, approved):
    package = packed["packages"][0]
    ship(client, distributor["headers"], package["id"], "1.0", retailer_id=retailer["id"])
    assert (
        client.patch(
            f"{API}/packages/{package['id']}",
            headers=retailer["headers"],
            json={"quantity": "0.1"},
        ).status_code
        in (403, 404, 405)
    )
    assert (
        client.patch(
            f"{API}/batches/{approved['id']}", headers=retailer["headers"], json={"notes": "x"}
        ).status_code
        in (403, 404, 405)
    )
    # The package the retailer may read carries no write handle at all.
    detail = client.get(f"{API}/packages/{package['id']}", headers=retailer["headers"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["can_release"] is False


# --------------------------------------------------------------------------- #
# Cancelling
# --------------------------------------------------------------------------- #
def test_a_cancelled_shipment_moves_no_honey(client, distributor, packed, db):
    package = packed["packages"][0]
    shipment = ship(client, distributor["headers"], package["id"], "6.0")
    response = move(
        client, distributor["headers"], shipment["id"], "cancel", reason="Vehicle broke down"
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "CANCELLED"
    assert shipment_row(db, shipment["id"]).cancelled_at is not None
    # Nothing moved, so the same honey can be shipped again.
    again = ship(client, distributor["headers"], package["id"], "6.0")
    assert again["status"] == "READY_FOR_DISPATCH"
    assert package_row(db, package["id"]).status is PackageStatus.READY_FOR_DISTRIBUTION


def test_a_delivered_shipment_cannot_be_cancelled(client, distributor, dispatched):
    delivered = move(client, distributor["headers"], dispatched["id"], "deliver")
    assert delivered.status_code == 200, delivered.text
    response = move(client, distributor["headers"], dispatched["id"], "cancel")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["details"]["status"] == "DELIVERED"


# --------------------------------------------------------------------------- #
# Who may do what
# --------------------------------------------------------------------------- #
def test_a_packaging_unit_cannot_ship(client, packer, packed):
    package = packed["packages"][0]
    response = client.post(
        f"{API}/distribution",
        headers=packer["headers"],
        json={"package_id": package["id"], "quantity": "1.0", "destination": "Guntur market"},
    )
    assert response.status_code == 403, response.text


def test_a_beekeeper_reads_the_journey_of_their_own_honey(client, keeper, distributor, packed, approved):
    package = packed["packages"][0]
    shipment = ship(client, distributor["headers"], package["id"], "1.0")
    move(client, distributor["headers"], shipment["id"], "dispatch")

    listed = client.get(
        f"{API}/distribution?batch_id={approved['id']}", headers=keeper["headers"]
    )
    assert listed.status_code == 200, listed.text
    assert [row["distribution_code"] for row in listed.json()["data"]] == [
        shipment["distribution_code"]
    ]
    detail = client.get(f"{API}/distribution/{shipment['id']}", headers=keeper["headers"])
    assert detail.status_code == 200, detail.text

    # Read-only: the beekeeper may not raise, dispatch, deliver or cancel.
    assert (
        client.post(
            f"{API}/distribution",
            headers=keeper["headers"],
            json={"package_id": package["id"], "quantity": "1.0", "destination": "Guntur"},
        ).status_code
        == 403
    )
    for action in ("dispatch", "in-transit", "deliver", "cancel"):
        assert move(client, keeper["headers"], shipment["id"], action).status_code == 403


def test_a_beekeeper_cannot_read_another_keepers_shipment(client, register_user, distributor, packed):
    other = register_user(name="Other Phase 7 Keeper", email=None)
    other["headers"] = {"Authorization": f"Bearer {other['access_token']}"}
    package = packed["packages"][0]
    shipment = ship(client, distributor["headers"], package["id"], "1.0")
    assert (
        client.get(f"{API}/distribution/{shipment['id']}", headers=other["headers"]).status_code
        == 404
    )


def test_a_distributor_cannot_edit_the_package_or_the_batch(client, distributor, packed, approved):
    package = packed["packages"][0]
    assert (
        client.patch(
            f"{API}/packages/{package['id']}",
            headers=distributor["headers"],
            json={"quantity": "0.1"},
        ).status_code
        in (403, 404, 405)
    )
    assert (
        client.patch(
            f"{API}/batches/{approved['id']}",
            headers=distributor["headers"],
            json={"notes": "x"},
        ).status_code
        in (403, 404, 405)
    )


def test_an_officer_reads_the_shipments_of_the_clusters_they_may_open(
    client, make_privileged_user, distributor, packed
):
    """A cluster officer reads the registry, so they read what hangs off it.

    This test used to assert an empty list. The officer's scope was derived from the
    district on their profile, so a shipment outside that district — or one whose
    batch carried no cluster — was invisible to them even though the same officer
    could open its cluster from the registry. The registry is the authority for
    which clusters a role may read and it is not district-bound, so the same rule
    now answers for the records underneath them. What has *not* changed: an officer
    still cannot move a shipment.
    """
    officer = make_privileged_user(
        role=UserRole.KVIC_OFFICER, name="Phase 7 Officer", password="OfficerPass123"
    )
    officer["headers"] = sign_in(client, officer)
    package = packed["packages"][0]
    shipment = ship(client, distributor["headers"], package["id"], "1.0")
    listed = client.get(f"{API}/distribution", headers=officer["headers"])
    assert listed.status_code == 200, listed.text
    assert [row["distribution_code"] for row in listed.json()["data"]] == [
        shipment["distribution_code"]
    ]
    assert (
        client.get(f"{API}/distribution/{shipment['id']}", headers=officer["headers"]).status_code
        == 200
    )
    assert move(client, officer["headers"], shipment["id"], "dispatch").status_code == 403


# --------------------------------------------------------------------------- #
# The shared record: timeline, traceability and audit
# --------------------------------------------------------------------------- #
def test_the_batch_timeline_reports_distribution_from_the_records(client, admin_headers, dispatched, approved):
    detail = client.get(f"{API}/batches/{approved['id']}", headers=admin_headers).json()["data"]
    stages = {stage["stage"]: stage for stage in detail["timeline"]}
    assert stages["DISTRIBUTION"]["state"] in ("current", "completed")
    assert dispatched["distribution_code"] in stages["DISTRIBUTION"]["detail"]
    assert detail["distribution"]["shipment_count"] == 1
    assert detail["distribution"]["delivered_count"] == 0
    assert detail["distribution"]["latest_code"] == dispatched["distribution_code"]
    assert detail["distribution"]["latest_status"] == "DISPATCHED"
    assert detail["status"] == "DISTRIBUTION"


def test_the_shipment_traces_back_to_the_hive_and_the_beekeeper(client, distributor, keeper, packed):
    package = packed["packages"][0]
    shipment = ship(client, distributor["headers"], package["id"], "1.0")
    detail = client.get(f"{API}/distribution/{shipment['id']}", headers=distributor["headers"])
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    kinds = [node["kind"] for node in data["traceability"]]
    assert "PACKAGE" in kinds
    assert "COLLECTION" in kinds
    assert "HIVE" in kinds
    assert "BEEKEEPER" in kinds
    assert data["package"]["package_code"] == package["package_code"]
    assert data["batch"]["batch_code"] == keeper["batch"]["batch_code"]


def test_the_shipment_events_are_written(client, distributor, retailer, packed, db):
    package = packed["packages"][0]
    shipment = ship(
        client, distributor["headers"], package["id"], "6.0", retailer_id=retailer["id"]
    )
    move(client, distributor["headers"], shipment["id"], "dispatch")
    move(client, distributor["headers"], shipment["id"], "in-transit")
    receive(client, retailer["headers"], shipment["id"])

    for action in (
        AuditAction.DISTRIBUTION_CREATED,
        AuditAction.SHIPMENT_DISPATCHED,
        AuditAction.SHIPMENT_IN_TRANSIT,
        AuditAction.PACKAGE_RECEIVED,
        AuditAction.BATCH_MOVED_TO_DISTRIBUTION,
    ):
        rows = audit_actions(db, action)
        assert rows, f"{action} was never recorded"

    dispatched = audit_actions(db, AuditAction.SHIPMENT_DISPATCHED)[0]
    assert dispatched.user_id == uuid.UUID(str(distributor["id"]))
    assert str(dispatched.actor_role) == "DISTRIBUTOR"
    assert dispatched.entity_type == "distribution"
    assert str(dispatched.entity_id) == str(shipment["id"])
    assert dispatched.event_metadata["distribution_code"] == shipment["distribution_code"]
    assert dispatched.event_metadata["batch_status"] == "DISTRIBUTION"

    received = audit_actions(db, AuditAction.PACKAGE_RECEIVED)[0]
    assert received.user_id == uuid.UUID(str(retailer["id"]))
    assert received.event_metadata["retailer_id"] == str(retailer["id"])
    assert received.event_metadata["quantity"] == "6.000"


def test_completing_the_distribution_is_recorded_against_the_batch(
    client, distributor, default_retailer, packed, approved, db
):
    for package in packed["packages"]:
        shipment = ship(client, distributor["headers"], package["id"], "6.0")
        move(client, distributor["headers"], shipment["id"], "dispatch")
        move(client, distributor["headers"], shipment["id"], "deliver")
        receive(client, default_retailer["headers"], shipment["id"])
    rows = audit_actions(db, AuditAction.BATCH_DISTRIBUTION_COMPLETED)
    assert rows, "the batch's completion must be recorded"
    assert rows[0].event_metadata["batch_status"] == "COMPLETED"
    assert batch_row(db, approved["id"]).status is BatchStatus.COMPLETED


def test_a_shipment_may_name_its_retailer_by_email(client, distributor, retailer, packed):
    """A distributor cannot list accounts, so the shop may be named by its email."""
    package = packed["packages"][0]
    shipment = ship(
        client,
        distributor["headers"],
        package["id"],
        "1.0",
        retailer_email=retailer["email"],
    )
    assert shipment["retailer_id"] == retailer["id"]
    assert shipment["retailer_name"] == "Phase 7 Retailer"


def test_an_unknown_or_non_retailer_email_is_refused(client, distributor, keeper, packed):
    package = packed["packages"][0]
    unknown = client.post(
        f"{API}/distribution",
        headers=distributor["headers"],
        json={
            "package_id": package["id"],
            "quantity": "1.0",
            "destination": "Guntur market",
            "retailer_email": "no-such-shop@honeychain.example.com",
        },
    )
    assert unknown.status_code == 422, unknown.text
    assert unknown.json()["error"]["details"]["field"] == "retailer_email"

    # A real account, but not a retailer: the same refusal, so the message cannot
    # be used to find out who has an account on the platform.
    keeper_email = keeper["user"]["email"] if isinstance(keeper.get("user"), dict) else None
    if keeper_email:
        wrong_role = client.post(
            f"{API}/distribution",
            headers=distributor["headers"],
            json={
                "package_id": package["id"],
                "quantity": "1.0",
                "destination": "Guntur market",
                "retailer_email": keeper_email,
            },
        )
        assert wrong_role.status_code == 422, wrong_role.text
        assert wrong_role.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_naming_a_retailer_twice_over_is_refused(client, distributor, retailer, packed):
    package = packed["packages"][0]
    response = client.post(
        f"{API}/distribution",
        headers=distributor["headers"],
        json={
            "package_id": package["id"],
            "quantity": "1.0",
            "destination": "Guntur market",
            "retailer_id": str(retailer["id"]),
            "retailer_email": retailer["email"],
        },
    )
    assert response.status_code == 422, response.text
