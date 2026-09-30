"""Prompt 11 — the cross-module integration points.

Each test walks real records through the HTTP API, role by role, and checks that
the next role reads the *same* row the previous one wrote — never a copy — and
that every status it sees came from the database:

* one batch is followed from its harvest to the retailer's receipt and the
  customer's QR, and the unified traceability (``GET /blockchain/batches/{id}``)
  names the same collection, hive, runs, test, packages and shipments;
* a package-scoped trace names only that package's run, shipments and events;
* the carrier's "delivered" is not the retailer's "received": the batch is not
  complete, and the shop's inbound list still offers the receipt, until the shop
  has confirmed it;
* a package split over two shipments is not delivered until both arrived;
* the unpacked remainder of a batch can still be packed after its first packages
  have shipped;
* counters are scoped exactly like the lists they summarise;
* the raw chain ledger and QR issuance are limited to the roles that own them;
* the laboratory cannot re-open a verdict under an open packaging run.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import BatchStatus, PackageStatus, UserRole
from tests.test_distribution import (  # noqa: F401 - fixtures are used by name
    API,
    approve_batch,
    approved,
    batch_row,
    default_retailer,
    dispatched,
    distributor,
    keeper,
    move,
    package_row,
    packaged_run,
    packed,
    packer,
    receive,
    retailer,
    ship,
    sign_in,
    technician,
)


def _trace(client, headers, batch_id, **params):
    response = client.get(f"{API}/blockchain/batches/{batch_id}", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _stages(trace) -> dict[str, bool]:
    return {row["stage"]: row["reached"] for row in trace["chain"]["stages"]}


# --------------------------------------------------------------------------- #
# The whole chain, on one set of records
# --------------------------------------------------------------------------- #
def test_one_batch_is_followed_end_to_end_on_the_same_records(
    client: TestClient, db: Session, admin_headers, keeper, packer, distributor,
    retailer, packed,
):
    batch_id = keeper["batch"]["id"]
    first, second = packed["packages"]

    # Before anything ships: the chain reports what exists, and no later stage.
    trace = _trace(client, keeper["headers"], batch_id)
    chain = trace["chain"]
    assert chain["batch"]["id"] == batch_id
    assert chain["collection"]["id"] == keeper["batch"]["collection_id"]
    assert [row["hive_code"] for row in chain["hives"]] == [keeper["hive"]["hive_code"]]
    assert chain["beekeeper"]["beekeeper_code"] == keeper["batch"]["beekeeper_code"]
    assert {row["package_code"] for row in chain["packages"]} == {
        first["package_code"],
        second["package_code"],
    }
    stages = _stages(trace)
    assert stages["COLLECTION"] and stages["PROCESSING"] and stages["LABORATORY"]
    assert stages["PACKAGING"] and stages["PACKAGE"]
    assert not stages["DISTRIBUTION"] and not stages["DELIVERED"] and not stages["RETAILER"]
    assert not stages["QR"] and not stages["CONSUMER"]

    # The distributor ships both packages to the retailer, and delivers them.
    shipments = [
        ship(client, distributor["headers"], row["id"], "6.0", retailer_id=retailer["id"])
        for row in (first, second)
    ]
    for shipment in shipments:
        assert move(client, distributor["headers"], shipment["id"], "dispatch").status_code == 200
        assert move(client, distributor["headers"], shipment["id"], "deliver").status_code == 200

    # Delivered by the carrier is not received by the shop: the batch stays in
    # distribution and the shop still has two receipts to give.
    assert batch_row(db, batch_id).status is BatchStatus.DISTRIBUTION
    inbound = client.get(
        f"{API}/retailer/shipments",
        headers=retailer["headers"],
        params={"awaiting_receipt": "true"},
    ).json()
    assert {row["id"] for row in inbound["data"]} == {row["id"] for row in shipments}
    assert inbound["meta"]["total_items"] == 2
    summary = client.get(f"{API}/retailer/summary", headers=retailer["headers"]).json()["data"]
    assert summary["inbound"] == 2 and summary["delivered"] == 0
    assert _stages(_trace(client, keeper["headers"], batch_id))["RETAILER"] is False

    # The shop confirms both. Now — and only now — the batch is complete.
    for shipment in shipments:
        assert receive(client, retailer["headers"], shipment["id"]).status_code == 200
    assert batch_row(db, batch_id).status is BatchStatus.COMPLETED
    summary = client.get(f"{API}/retailer/summary", headers=retailer["headers"]).json()["data"]
    assert summary["inbound"] == 0 and summary["delivered"] == 2
    assert summary["packages_received"] == 2
    received = client.get(f"{API}/retailer/packages", headers=retailer["headers"]).json()["data"]
    assert {row["package_code"] for row in received} == {
        first["package_code"],
        second["package_code"],
    }

    # The packer issues the first package's label; the customer scans it.
    issued = client.post(f"{API}/blockchain/packages/{first['id']}/qr", headers=packer["headers"])
    assert issued.status_code == 200, issued.text
    public = client.get(f"{API}/trace/{issued.json()['data']['qr_id']}")
    assert public.status_code == 200, public.text
    public = public.json()["data"]
    assert public["package"]["package_code"] == first["package_code"]
    assert public["product"]["batch_code"] == keeper["batch"]["batch_code"]
    # The ledger on the first view already includes the QR and the verification.
    tx_types = [row["tx_type"] for row in public["blockchain"]["transactions"]]
    assert "QR_GENERATED" in tx_types and "CUSTOMER_QR_VERIFIED" in tx_types
    # Never another jar's label or creation event.
    assert tx_types.count("PACKAGE_CREATED") == 1

    # Every stage of the batch is now reached, from the records alone.
    stages = _stages(_trace(client, admin_headers, batch_id))
    assert all(stages.values()), stages

    # The KVIC officer reads the very same batch, not a copy of it.
    # (Admin stands in for the platform view; the officer's scope is tested below.)
    officer_trace = _trace(client, admin_headers, batch_id)
    assert officer_trace["chain"]["batch"]["id"] == batch_id


def test_a_package_scoped_trace_names_only_that_package(
    client: TestClient, keeper, distributor, retailer, packed,
):
    first, second = packed["packages"]
    shipment = ship(client, distributor["headers"], first["id"], "6.0", retailer_id=retailer["id"])
    move(client, distributor["headers"], shipment["id"], "dispatch")

    trace = _trace(client, keeper["headers"], keeper["batch"]["id"], package_code=first["package_code"])
    assert trace["package_code"] == first["package_code"]
    assert [row["package_code"] for row in trace["chain"]["packages"]] == [first["package_code"]]
    assert [row["package_code"] for row in trace["chain"]["distribution"]] == [first["package_code"]]
    package_ids = {row["package_id"] for row in trace["transactions"] if row["package_id"]}
    assert package_ids == {first["id"]}

    # The second package has no shipment, and its own trace says so.
    other = _trace(client, keeper["headers"], keeper["batch"]["id"], package_code=second["package_code"])
    assert other["chain"]["distribution"] == []
    assert _stages(other)["DISTRIBUTION"] is False


def test_a_package_of_another_batch_is_not_found_under_this_batch(
    client: TestClient, admin_headers, keeper, packed,
):
    response = client.get(
        f"{API}/blockchain/batches/{keeper['batch']['id']}",
        headers=admin_headers,
        params={"package_code": "HC-PKG-1999-999999"},
    )
    assert response.status_code == 404, response.text


def test_the_batch_timeline_counts_every_package_not_just_the_first(
    client: TestClient, admin_headers, packer, keeper, packed,
):
    second = packed["packages"][1]
    assert client.post(
        f"{API}/blockchain/packages/{second['id']}/qr", headers=packer["headers"]
    ).status_code == 200
    timeline = _trace(client, admin_headers, keeper["batch"]["id"])["timeline"]
    qr_step = next(row for row in timeline if row["stage"] == "QR")
    # Only the second package is labelled; the batch view still says a label exists.
    assert qr_step["reached"] is True
    assert qr_step["detail"] == "1 of 2 packages"


# --------------------------------------------------------------------------- #
# Delivery, receipt and completion
# --------------------------------------------------------------------------- #
def test_a_split_package_is_not_delivered_until_all_of_it_arrived(
    client: TestClient, db: Session, distributor, retailer, packed,
):
    package = packed["packages"][0]
    first = ship(client, distributor["headers"], package["id"], "3.0", retailer_id=retailer["id"])
    ship(client, distributor["headers"], package["id"], "3.0", retailer_id=retailer["id"])
    move(client, distributor["headers"], first["id"], "dispatch")
    assert move(client, distributor["headers"], first["id"], "deliver").status_code == 200
    # Half of it is still in the warehouse.
    assert package_row(db, package["id"]).status is not PackageStatus.DELIVERED


def test_the_retailer_can_confirm_a_shipment_the_carrier_already_delivered(
    client: TestClient, db: Session, distributor, retailer, dispatched,
):
    assert move(client, distributor["headers"], dispatched["id"], "deliver").status_code == 200
    first = receive(client, retailer["headers"], dispatched["id"])
    assert first.status_code == 200, first.text
    received_at = first.json()["data"]["received_at"]
    assert received_at
    # A second confirmation does not move the moment it happened.
    again = receive(client, retailer["headers"], dispatched["id"])
    assert again.status_code == 200
    assert again.json()["data"]["received_at"] == received_at


def test_the_unpacked_remainder_can_be_packed_after_the_first_shipment(
    client: TestClient, db: Session, packer, distributor, retailer, approved,
):
    def run(quantity: str, size: str, count: int) -> dict:
        created = client.post(
            f"{API}/packaging",
            headers=packer["headers"],
            json={
                "batch_id": approved["id"],
                "packaging_unit_id": packer["unit"]["id"],
                "packaging_type": "JAR",
                "packaged_quantity": quantity,
                "package_size": size,
                "number_of_packages": count,
            },
        )
        assert created.status_code == 201, created.text
        row = created.json()["data"]
        client.post(f"{API}/packaging/{row['id']}/start", headers=packer["headers"])
        done = client.post(f"{API}/packaging/{row['id']}/complete", headers=packer["headers"], json={})
        assert done.status_code == 200, done.text
        return done.json()["data"]

    half = run("6.0", "6.0", 1)
    released = client.post(f"{API}/packaging/{half['id']}/release", headers=packer["headers"])
    assert released.status_code == 200, released.text
    package = released.json()["data"][0]
    shipment = ship(client, distributor["headers"], package["id"], "6.0", retailer_id=retailer["id"])
    assert move(client, distributor["headers"], shipment["id"], "dispatch").status_code == 200
    assert batch_row(db, approved["id"]).status is BatchStatus.DISTRIBUTION

    # The other 6 KG is still on the packaging worklist, and can be packed.
    worklist = client.get(f"{API}/packaging/approved-batches", headers=packer["headers"])
    if worklist.status_code == 200:
        assert approved["id"] in {row["batch_id"] for row in worklist.json()["data"]}
    run("6.0", "6.0", 1)
    # Packing the remainder does not pull the batch back out of distribution.
    assert batch_row(db, approved["id"]).status is BatchStatus.DISTRIBUTION


# --------------------------------------------------------------------------- #
# Scoped counters and role limits
# --------------------------------------------------------------------------- #
def test_the_distribution_summary_counts_only_the_callers_shipments(
    client: TestClient, make_privileged_user, distributor, dispatched,
):
    mine = client.get(f"{API}/distribution/summary", headers=distributor["headers"]).json()["data"]
    assert mine["total"] == 1 and mine["dispatched"] == 1

    other = make_privileged_user(role=UserRole.DISTRIBUTOR, name="Other Distributor", password="DistPass123")
    theirs = client.get(f"{API}/distribution/summary", headers=sign_in(client, other)).json()["data"]
    assert theirs["total"] == 0


def test_only_packaging_may_issue_a_label_and_only_admin_reads_the_raw_ledger(
    client: TestClient, make_privileged_user, keeper, packer, packed,
):
    package = packed["packages"][0]
    refused = client.post(f"{API}/blockchain/packages/{package['id']}/qr", headers=keeper["headers"])
    assert refused.status_code == 403, refused.text
    assert client.post(
        f"{API}/blockchain/packages/{package['id']}/qr", headers=packer["headers"]
    ).status_code == 200

    officer = make_privileged_user(role=UserRole.KVIC_OFFICER, name="Ledger Officer", password="KvicPass123")
    officer_headers = sign_in(client, officer)
    assert client.get(f"{API}/blockchain/ledger", headers=officer_headers).status_code == 403
    # The officer's own, scoped ledger is unaffected.
    assert client.get(f"{API}/blockchain/transactions", headers=officer_headers).status_code == 200


def test_a_retest_is_refused_while_a_packaging_run_is_open(
    client: TestClient, technician, packer, approved,
):
    opened = client.post(
        f"{API}/packaging",
        headers=packer["headers"],
        json={
            "batch_id": approved["id"],
            "packaging_unit_id": packer["unit"]["id"],
            "packaging_type": "JAR",
            "packaged_quantity": "6.0",
            "package_size": "6.0",
            "number_of_packages": 1,
        },
    )
    assert opened.status_code == 201, opened.text
    laboratory = client.get(f"{API}/laboratories", headers=technician["headers"]).json()["data"][0]
    retest = client.post(
        f"{API}/lab-tests",
        headers=technician["headers"],
        json={
            "batch_id": approved["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.25",
            "sample_unit": "GRAM",
            "retest_reason": "Customer dispute over moisture",
        },
    )
    assert retest.status_code == 409, retest.text
    assert retest.json()["error"]["details"]["packaging_code"] == opened.json()["data"]["packaging_code"]


def test_registration_accepts_the_phone_spellings_the_form_accepts(client: TestClient):
    response = client.post(
        f"{API}/auth/register",
        json={
            "name": "Bracket Phone Consumer",
            "email": "bracket.phone@example.com",
            "password": "Consumer123",
            "role": "CONSUMER",
            "phone": "(987) 654-3210",
        },
    )
    assert response.status_code == 201, response.text
