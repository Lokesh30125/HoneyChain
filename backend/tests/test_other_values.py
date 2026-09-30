"""The "Other" option, all three places it exists, from both sides.

Parts 5 and 35 of the correction prompt: a field with a known set of choices may
offer *Other*, and when it does, the record has to say what the other thing was.
Half of that rule is easy to implement and the other half is easy to miss, so this
module checks both directions everywhere the option exists:

* what a processing run did — ``processing_type`` / ``processing_type_other``
* what a batch was packed into — ``packaging_type`` / ``packaging_type_other``
* what a device is — ``device_type`` / ``device_type_other``

The rule, in one sentence: **the description exists exactly when the choice is
Other.** "Other" on its own records nothing; a description beside a listed value
attaches words to the wrong thing, and is refused rather than silently dropped.

The read models are checked too, because a record that stores the description and
then prints the bare enum to every reader has not really recorded anything: each
field exposes ``*_other`` and ``*_display``, and a package inherits the container
its run was described as. Switching away and back is checked on the update paths,
which is where a stale description would otherwise survive.

``tests/api_smoke_other.py`` walks the same ground over HTTP against a running
server; this module keeps the rule inside the ordinary test run.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.iot_device import IotDevice
from app.models.packaging import PackagingRun
from app.models.processing import HoneyProcessing
from tests.test_packaging import (
    API,
    PACKAGING_UNIT_PAYLOAD,
    approve_batch,
    make_batch,
    make_hive,
    open_run,
    sign_in,
)

OTHER_OPERATION = "Centrifuged at 40 °C"
OTHER_CONTAINER = "500 g glass jar, brass lid"
OTHER_HARDWARE = "Custom LoRa board rev C"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def keeper(client: TestClient, register_user):
    """A beekeeper of their own, so the hives and harvests here are theirs alone."""
    payload = register_user(role=UserRole.BEEKEEPER, name="Other-field beekeeper")
    payload["headers"] = {"Authorization": f"Bearer {payload['access_token']}"}
    return payload


@pytest.fixture()
def processor(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.PROCESSOR, name="Other-field processor", password="ProcessPass123"
    )
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def technician(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.LAB_TECHNICIAN, name="Other-field technician", password="LabTechPass123"
    )
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def packer_headers(client: TestClient, make_privileged_user, admin_headers):
    """A packing operator, attached to the unit it works at.

    An administrator registers the facility and names the operator — the same
    order the platform uses — because a run records *which* facility packed the
    honey and an unattached account cannot open one.
    """
    payload = make_privileged_user(
        role=UserRole.PACKAGING_UNIT, name="Other-field packer", password="PackPass123"
    )
    payload["headers"] = sign_in(client, payload)
    unit = client.post(
        f"{API}/packaging-units",
        headers=admin_headers,
        json={**PACKAGING_UNIT_PAYLOAD, "registration_identifier": "REG-OTHER-VALUES"},
    )
    assert unit.status_code == 201, unit.text
    attached = client.post(
        f"{API}/packaging-units/{unit.json()['data']['id']}/members",
        headers=admin_headers,
        json={"user_id": str(payload["id"])},
    )
    assert attached.status_code in (200, 201), attached.text
    return payload["headers"]


@pytest.fixture()
def hive(client: TestClient, keeper):
    return make_hive(client, keeper["headers"])


@pytest.fixture()
def collected(client: TestClient, keeper, hive):
    """A complete collection and the single batch it produced."""
    return make_batch(client, keeper["headers"], hive)


@pytest.fixture()
def approved(client: TestClient, admin_headers, technician, keeper, collected):
    """The same batch taken through processing and the laboratory to APPROVED.

    An approved batch is the only kind that can be packed, so the packaging half of
    this module needs one; it is built the way the workflow builds one.
    """
    return approve_batch(
        client,
        admin_headers,
        technician["headers"],
        collected["id"],
        measured="12.9",
        config_headers=admin_headers,
    )


# --------------------------------------------------------------------------- #
# Processing — what the run did
# --------------------------------------------------------------------------- #
def test_a_run_can_record_an_operation_the_list_does_not_contain(client, processor, collected):
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={
            "batch_id": collected["id"],
            "processing_type": "OTHER",
            "processing_type_other": OTHER_OPERATION,
        },
    )
    assert response.status_code == 201, response.text
    run = response.json()["data"]
    assert run["processing_type_other"] == OTHER_OPERATION
    assert run["processing_type_display"] == OTHER_OPERATION


def test_other_without_a_description_is_refused(client, processor, collected):
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": collected["id"], "processing_type": "OTHER"},
    )
    assert response.status_code == 422, response.text
    assert "operation" in response.text.lower()


def test_a_description_beside_a_listed_operation_is_refused(client, processor, collected):
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={
            "batch_id": collected["id"],
            "processing_type": "FILTERING",
            "processing_type_other": OTHER_OPERATION,
        },
    )
    assert response.status_code == 422, response.text


def test_a_whitespace_description_counts_as_none(client, processor, collected):
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={
            "batch_id": collected["id"],
            "processing_type": "OTHER",
            "processing_type_other": "   ",
        },
    )
    assert response.status_code == 422, response.text


def test_changing_the_type_away_from_other_clears_the_description(
    client, processor, collected, db: Session
):
    """The half of the rule that a create-only implementation gets wrong."""
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={
            "batch_id": collected["id"],
            "processing_type": "OTHER",
            "processing_type_other": OTHER_OPERATION,
        },
    ).json()["data"]

    response = client.patch(
        f"{API}/processing/{run['id']}",
        headers=processor["headers"],
        json={"processing_type": "FILTERING"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["processing_type_other"] is None
    assert response.json()["data"]["processing_type_display"] == "Filtering"

    db.expire_all()
    stored = db.get(HoneyProcessing, run["id"])
    assert stored.processing_type_other is None
    assert str(stored.processing_type) == "FILTERING"


def test_changing_the_type_to_other_without_a_description_is_refused(client, processor, collected):
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": collected["id"], "processing_type": "FILTERING"},
    ).json()["data"]

    response = client.patch(
        f"{API}/processing/{run['id']}",
        headers=processor["headers"],
        json={"processing_type": "OTHER"},
    )
    assert response.status_code == 422, response.text


def test_the_description_is_trimmed_on_the_update_path(client, processor, collected):
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": collected["id"], "processing_type": "OTHER", "processing_type_other": "x"},
    ).json()["data"]

    response = client.patch(
        f"{API}/processing/{run['id']}",
        headers=processor["headers"],
        json={"processing_type": "OTHER", "processing_type_other": f"  {OTHER_OPERATION}  "},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["processing_type_other"] == OTHER_OPERATION


def test_a_listed_run_is_untouched_by_the_other_field(client, processor, collected):
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": collected["id"], "processing_type": "BLENDING"},
    )
    assert response.status_code == 201, response.text
    run = response.json()["data"]
    assert run["processing_type_other"] is None
    assert run["processing_type_display"] == "Blending"


# --------------------------------------------------------------------------- #
# Packaging — what the honey was packed into
# --------------------------------------------------------------------------- #
def test_a_run_can_record_a_container_the_list_does_not_contain(client, packer_headers, approved):
    run = open_run(
        client,
        packer_headers,
        approved["id"],
        packaging_type="OTHER",
        packaging_type_other=OTHER_CONTAINER,
    )
    assert run["packaging_type_other"] == OTHER_CONTAINER
    assert run["packaging_type_display"] == OTHER_CONTAINER

    detail = client.get(f"{API}/packaging/{run['id']}", headers=packer_headers).json()["data"]
    assert detail["packaging_type_other"] == OTHER_CONTAINER


def test_other_without_a_description_is_refused_on_a_run(client, packer_headers, approved):
    response = client.post(
        f"{API}/packaging",
        headers=packer_headers,
        json={"batch_id": approved["id"], "packaging_type": "OTHER"},
    )
    assert response.status_code == 422, response.text


def test_a_description_beside_a_listed_container_is_refused_on_a_run(client, packer_headers, approved):
    response = client.post(
        f"{API}/packaging",
        headers=packer_headers,
        json={
            "batch_id": approved["id"],
            "packaging_type": "JAR",
            "packaging_type_other": OTHER_CONTAINER,
        },
    )
    assert response.status_code == 422, response.text


def test_a_run_can_be_corrected_to_other_and_back(
    client, packer_headers, approved, db: Session
):
    run = open_run(client, packer_headers, approved["id"])

    response = client.patch(
        f"{API}/packaging/{run['id']}",
        headers=packer_headers,
        json={"packaging_type": "OTHER", "packaging_type_other": OTHER_CONTAINER},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["packaging_type_other"] == OTHER_CONTAINER

    response = client.patch(
        f"{API}/packaging/{run['id']}",
        headers=packer_headers,
        json={"packaging_type": "BOTTLE"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["packaging_type_other"] is None

    db.expire_all()
    stored = db.get(PackagingRun, run["id"])
    assert stored.packaging_type_other is None
    assert str(stored.packaging_type) == "BOTTLE"


def test_the_description_is_trimmed_on_a_run(client, packer_headers, approved):
    run = open_run(
        client,
        packer_headers,
        approved["id"],
        packaging_type="OTHER",
        packaging_type_other=f"   {OTHER_CONTAINER}   ",
    )
    assert run["packaging_type_other"] == OTHER_CONTAINER


def test_a_package_inherits_the_container_its_run_was_described_as(
    client, packer_headers, approved
):
    """The packages are the records that travel; they carry the description too."""
    run = open_run(
        client,
        packer_headers,
        approved["id"],
        packaging_type="OTHER",
        packaging_type_other=OTHER_CONTAINER,
        packaged_quantity="4.000",
        package_size="1.000",
        number_of_packages=4,
    )
    started = client.post(f"{API}/packaging/{run['id']}/start", headers=packer_headers)
    assert started.status_code == 200, started.text
    completed = client.post(
        f"{API}/packaging/{run['id']}/complete",
        headers=packer_headers,
        json={},
    )
    assert completed.status_code == 200, completed.text

    packages = client.get(
        f"{API}/packages?batch_id={approved['id']}", headers=packer_headers
    ).json()["data"]
    assert packages, "the run produced no packages"
    for package in packages:
        assert package["packaging_type_other"] == OTHER_CONTAINER
        assert package["packaging_type_display"] == OTHER_CONTAINER


def test_the_packaging_list_shows_the_description_not_the_enum(client, packer_headers, approved):
    open_run(
        client,
        packer_headers,
        approved["id"],
        packaging_type="OTHER",
        packaging_type_other=OTHER_CONTAINER,
    )
    rows = client.get(f"{API}/packaging?page_size=50", headers=packer_headers).json()["data"]
    assert rows, "the packaging list is empty"
    described = [row for row in rows if row["packaging_type"] == "OTHER"]
    assert described, "the run recorded as Other is missing from the list"
    for row in described:
        assert row["packaging_type_display"] == OTHER_CONTAINER


# --------------------------------------------------------------------------- #
# IoT — what the hardware is
# --------------------------------------------------------------------------- #
def device_payload(hive_id: str, **overrides) -> dict:
    payload = {
        "device_id": f"OTHER-{uuid.uuid4().hex[:8].upper()}",
        "device_name": "Other-field test node",
        "hive_id": hive_id,
        "device_type": "OTHER",
        "device_type_other": OTHER_HARDWARE,
    }
    payload.update(overrides)
    return payload


def test_a_device_can_be_unlisted_hardware(client, keeper, hive):
    response = client.post(
        f"{API}/iot/devices", headers=keeper["headers"], json=device_payload(hive["id"])
    )
    assert response.status_code == 201, response.text
    device = response.json()["data"]
    assert device["device_type_other"] == OTHER_HARDWARE
    assert device["device_type_display"] == OTHER_HARDWARE


def test_a_device_typed_other_without_a_description_is_refused(client, keeper, hive):
    response = client.post(
        f"{API}/iot/devices",
        headers=keeper["headers"],
        json=device_payload(hive["id"], device_type_other=None),
    )
    assert response.status_code == 422, response.text


def test_a_device_description_beside_listed_hardware_is_refused(client, keeper, hive):
    response = client.post(
        f"{API}/iot/devices",
        headers=keeper["headers"],
        json=device_payload(hive["id"], device_type="ESP32"),
    )
    assert response.status_code == 422, response.text


def test_changing_a_devices_type_away_from_other_clears_the_description(
    client, keeper, hive, db: Session
):
    device_id = client.post(
        f"{API}/iot/devices", headers=keeper["headers"], json=device_payload(hive["id"])
    ).json()["data"]["id"]

    response = client.put(
        f"{API}/iot/devices/{device_id}",
        headers=keeper["headers"],
        json={"device_type": "ESP32"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["device_type_other"] is None

    db.expire_all()
    stored = db.get(IotDevice, device_id)
    assert stored.device_type_other is None
    assert str(stored.device_type) == "ESP32"


def test_changing_a_devices_type_to_other_without_a_description_is_refused(
    client, keeper, hive
):
    device_id = client.post(
        f"{API}/iot/devices",
        headers=keeper["headers"],
        json=device_payload(hive["id"], device_type="ESP32", device_type_other=None),
    ).json()["data"]["id"]

    response = client.put(
        f"{API}/iot/devices/{device_id}",
        headers=keeper["headers"],
        json={"device_type": "OTHER"},
    )
    assert response.status_code in (400, 422), response.text


def test_the_hive_payload_reads_the_hardware_the_same_way(client, keeper, hive):
    """The compact device block inside a hive is a read model too."""
    client.post(f"{API}/iot/devices", headers=keeper["headers"], json=device_payload(hive["id"]))
    detail = client.get(f"{API}/hives/{hive['id']}", headers=keeper["headers"]).json()["data"]
    devices = detail.get("devices") or []
    assert devices, "the hive carries no device block"
    assert any(device["device_type_display"] == OTHER_HARDWARE for device in devices), devices


# --------------------------------------------------------------------------- #
# The rule is enforced where the data actually lives
# --------------------------------------------------------------------------- #
def test_the_database_refuses_a_bare_other(client, processor, collected, db: Session):
    """The API is not the only writer, so the pair is a constraint, not a convention."""
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={
            "batch_id": collected["id"],
            "processing_type": "OTHER",
            "processing_type_other": OTHER_OPERATION,
        },
    ).json()["data"]

    with pytest.raises(Exception) as failure:
        db.execute(
            text(
                "UPDATE honey_processing_records SET processing_type = 'OTHER', "
                "processing_type_other = NULL WHERE id = :id"
            ),
            {"id": run["id"]},
        )
        db.flush()
    assert "ck_" in str(failure.value) or "constraint" in str(failure.value).lower()
    db.rollback()
