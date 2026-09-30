"""Phase 3 — hive registry: codes, scoping, lifecycle and derived payloads.

The tests are grouped the way the risk is: what the *backend* guarantees about a
hive (a generated code, an owner it cannot be talked out of), what a beekeeper
may reach, and what happens to data when a hive is retired.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import HiveStatus
from app.models.hive import Hive
from app.models.user import User

API = "/api/v1"

VALID_HIVE = {
    "bee_species": "Apis cerana indica",
    "village": "Tenali",
    "mandal": "Tenali",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "pincode": "522201",
    "latitude": 16.243,
    "longitude": 80.64,
    "notes": "South row, near the canal.",
}


def make_hive(client: TestClient, headers: dict, **overrides) -> dict:
    payload = {**VALID_HIVE, **overrides}
    response = client.post(f"{API}/hives", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
class TestHiveRegistration:
    def test_requires_authentication(self, client: TestClient):
        assert client.post(f"{API}/hives", json=VALID_HIVE).status_code == 401

    def test_a_consumer_cannot_register_a_hive(self, client: TestClient, consumer_headers):
        response = client.post(f"{API}/hives", headers=consumer_headers, json=VALID_HIVE)
        assert response.status_code == 403

    def test_code_is_generated_by_the_backend(self, client: TestClient, auth_headers, beekeeper_record):
        hive = make_hive(client, auth_headers)

        assert hive["hive_code"].startswith("HIVE-GNT-")
        assert hive["hive_code"].endswith("00001")
        assert hive["beekeeper_id"] == beekeeper_record["id"]
        assert hive["status"] == HiveStatus.ACTIVE.value
        assert hive["status_label"] == "Active"

    def test_codes_increment_within_a_district(self, client: TestClient, auth_headers):
        first = make_hive(client, auth_headers)
        second = make_hive(client, auth_headers, village="Kuchipudi")

        assert first["hive_code"] == "HIVE-GNT-00001"
        assert second["hive_code"] == "HIVE-GNT-00002"

    def test_a_different_district_gets_its_own_sequence(self, client: TestClient, auth_headers):
        guntur = make_hive(client, auth_headers)
        krishna = make_hive(client, auth_headers, district="Krishna", village="Machilipatnam")

        assert guntur["hive_code"] == "HIVE-GNT-00001"
        assert krishna["hive_code"] == "HIVE-KRS-00001"

    def test_the_prefix_follows_the_district_name_stably(
        self, client: TestClient, auth_headers
    ):
        """The code is derived, so the same district always yields the same prefix."""
        one = make_hive(client, auth_headers, district="Srikakulam")
        two = make_hive(client, auth_headers, district="Srikakulam", village="Palasa")

        assert one["hive_code"] == "HIVE-SRK-00001"
        assert two["hive_code"] == "HIVE-SRK-00002"

    def test_a_hive_with_no_district_at_all_uses_the_generic_prefix(
        self, client: TestClient, auth_headers
    ):
        """Neither the payload nor the apiary record knows the district."""
        hive = make_hive(client, auth_headers, district=None, state=None)
        assert hive["hive_code"] == "HIVE-GEN-00001"
        assert hive["district"] is None

    def test_client_supplied_identity_fields_are_rejected(
        self, client: TestClient, auth_headers
    ):
        """A beekeeper cannot choose a code, an owner or a cluster."""
        for field, value in (
            ("hive_code", "HIVE-GNT-99999"),
            ("beekeeper_id", str(uuid.uuid4())),
            ("cluster_id", str(uuid.uuid4())),
            ("status", "REMOVED"),
        ):
            response = client.post(
                f"{API}/hives", headers=auth_headers, json={**VALID_HIVE, field: value}
            )
            assert response.status_code == 422, field

    def test_district_and_state_fall_back_to_the_apiary_record(
        self, client: TestClient, auth_headers, beekeeper_record
    ):
        """A hive registered without a district inherits the owner's."""
        client.put(
            f"{API}/beekeepers/me",
            headers=auth_headers,
            json={"district": "Guntur", "state": "Andhra Pradesh", "village": "Tenali"},
        )
        hive = make_hive(client, auth_headers, district=None, state=None, village="Mangalagiri")

        assert hive["district"] == "Guntur"
        assert hive["state"] == "Andhra Pradesh"
        assert hive["hive_code"].startswith("HIVE-GNT-")

    def test_a_half_specified_location_is_refused(self, client: TestClient, auth_headers):
        response = client.post(
            f"{API}/hives", headers=auth_headers, json={**VALID_HIVE, "longitude": None}
        )
        assert response.status_code == 422
        assert any("latitude" in detail["message"] or "longitude" in detail["message"]
                   for detail in response.json()["error"]["details"])

    def test_an_invalid_pincode_is_refused(self, client: TestClient, auth_headers):
        response = client.post(
            f"{API}/hives", headers=auth_headers, json={**VALID_HIVE, "pincode": "01234"}
        )
        assert response.status_code == 422

    def test_an_impossible_coordinate_is_refused(self, client: TestClient, auth_headers):
        response = client.post(
            f"{API}/hives", headers=auth_headers, json={**VALID_HIVE, "latitude": 120.0}
        )
        assert response.status_code == 422

    def test_blank_text_becomes_null_rather_than_empty_string(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers, notes="   ", bee_species="  Apis  dorsata ")
        assert hive["notes"] is None
        assert hive["bee_species"] == "Apis dorsata"

    def test_registration_is_audited(self, client: TestClient, auth_headers, db: Session):
        from app.models.audit_log import AuditLog

        hive = make_hive(client, auth_headers)
        entry = (
            db.query(AuditLog)
            .filter(AuditLog.action == "HIVE_CREATED", AuditLog.entity_id == hive["id"])
            .one_or_none()
        )
        assert entry is not None
        assert entry.event_metadata["hive_code"] == hive["hive_code"]


# --------------------------------------------------------------------------- #
# Listing and scoping
# --------------------------------------------------------------------------- #
class TestHiveListing:
    def test_a_new_beekeeper_has_no_hives(self, client: TestClient, auth_headers):
        body = client.get(f"{API}/hives", headers=auth_headers).json()

        assert body["data"] == []
        assert body["meta"]["total_items"] == 0
        assert body["meta"]["total_pages"] == 0

    def test_a_beekeeper_sees_only_their_own_hives(
        self, client: TestClient, auth_headers, register_user
    ):
        make_hive(client, auth_headers)
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        make_hive(client, other_headers, village="Other apiary")

        mine = client.get(f"{API}/hives", headers=auth_headers).json()["data"]
        theirs = client.get(f"{API}/hives", headers=other_headers).json()["data"]

        assert len(mine) == 1
        assert len(theirs) == 1
        assert mine[0]["id"] != theirs[0]["id"]

    def test_staff_see_every_hive(
        self, client: TestClient, auth_headers, register_user, kvic_headers, admin_headers
    ):
        make_hive(client, auth_headers)
        other = register_user(email=None)
        make_hive(client, {"Authorization": f"Bearer {other['access_token']}"})

        for headers in (kvic_headers, admin_headers):
            body = client.get(f"{API}/hives", headers=headers).json()
            assert body["meta"]["total_items"] == 2

    def test_staff_can_filter_by_beekeeper(
        self, client: TestClient, auth_headers, beekeeper_record, kvic_headers
    ):
        make_hive(client, auth_headers)
        body = client.get(
            f"{API}/hives", headers=kvic_headers, params={"beekeeper_id": beekeeper_record["id"]}
        ).json()
        assert body["meta"]["total_items"] == 1

        none = client.get(
            f"{API}/hives", headers=kvic_headers, params={"beekeeper_id": str(uuid.uuid4())}
        ).json()
        assert none["meta"]["total_items"] == 0

    def test_a_beekeeper_cannot_widen_their_scope_with_a_filter(
        self, client: TestClient, auth_headers, register_user
    ):
        """``beekeeper_id`` is ignored for a self-scoped caller."""
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        make_hive(client, other_headers, village="Other apiary")
        make_hive(client, auth_headers)

        body = client.get(
            f"{API}/hives",
            headers=auth_headers,
            params={"beekeeper_id": "00000000-0000-0000-0000-000000000000"},
        ).json()

        assert body["meta"]["total_items"] == 1

    def test_filters_narrow_the_result(self, client: TestClient, auth_headers):
        active = make_hive(client, auth_headers)
        retired = make_hive(client, auth_headers, village="Kuchipudi")
        client.patch(
            f"{API}/hives/{retired['id']}/status",
            headers=auth_headers,
            json={"status": "MAINTENANCE", "reason": "Moving supers."},
        )
        make_hive(client, auth_headers, colony_strength="STRONG", village="Pedakakani")

        assert client.get(f"{API}/hives", headers=auth_headers, params={"status": "MAINTENANCE"}).json()["meta"]["total_items"] == 1
        assert client.get(f"{API}/hives", headers=auth_headers, params={"search": "Kuchipudi"}).json()["meta"]["total_items"] == 1
        assert client.get(f"{API}/hives", headers=auth_headers, params={"colony_strength": "STRONG"}).json()["meta"]["total_items"] == 1
        assert client.get(f"{API}/hives", headers=auth_headers, params={"district": "Guntur"}).json()["meta"]["total_items"] == 3
        assert active["id"]

    def test_pagination_metadata_is_accurate(self, client: TestClient, auth_headers):
        for index in range(5):
            make_hive(client, auth_headers, village=f"Village {index}")

        body = client.get(
            f"{API}/hives", headers=auth_headers, params={"page": 2, "page_size": 2}
        ).json()

        assert len(body["data"]) == 2
        assert body["meta"]["total_items"] == 5
        assert body["meta"]["total_pages"] == 3
        assert body["meta"]["page"] == 2

    def test_each_row_carries_its_device_and_reading_state(
        self, client: TestClient, auth_headers
    ):
        make_hive(client, auth_headers)
        row = client.get(f"{API}/hives", headers=auth_headers).json()["data"][0]

        # No device yet: the API says so rather than inventing a placeholder.
        assert row["device_count"] == 0
        assert row["primary_device"] is None
        assert row["latest_reading"] is None
        assert row["has_coordinates"] is True
        assert row["location_label"].startswith("Tenali")

    def test_a_hive_with_a_device_lists_that_device(
        self, client: TestClient, auth_headers
    ):
        """The row embeds the device and its sensor set, not just a count."""
        hive = make_hive(client, auth_headers)
        client.post(
            f"{API}/iot/devices",
            headers=auth_headers,
            json={"device_id": "ESP32-GNT-0201", "device_name": "Node C", "hive_id": hive["id"]},
        )

        row = client.get(f"{API}/hives", headers=auth_headers).json()["data"][0]

        assert row["device_count"] == 1
        assert row["primary_device"]["device_id"] == "ESP32-GNT-0201"
        assert row["primary_device"]["status"] == "OFFLINE"
        assert len(row["primary_device"]["sensors"]) == 5

        detail = client.get(f"{API}/hives/{hive['id']}", headers=auth_headers).json()["data"]
        assert len(detail["devices"]) == 1
        assert detail["devices"][0]["mqtt_topic"].startswith("honeychain/devices/")

    def test_summary_counts_real_rows(self, client: TestClient, auth_headers):
        make_hive(client, auth_headers)
        retired = make_hive(client, auth_headers, village="Kuchipudi")
        client.patch(
            f"{API}/hives/{retired['id']}/status", headers=auth_headers, json={"status": "REMOVED"}
        )

        summary = client.get(f"{API}/hives/summary", headers=auth_headers).json()["data"]

        assert summary["total"] == 2
        assert summary["by_status"]["ACTIVE"] == 1
        assert summary["by_status"]["REMOVED"] == 1
        assert summary["without_device"] == 2
        assert summary["with_device"] == 0

    def test_filters_endpoint_reflects_the_caller_data(self, client: TestClient, auth_headers):
        make_hive(client, auth_headers, district="Krishna", village="Machilipatnam")
        make_hive(client, auth_headers)

        options = client.get(f"{API}/hives/filters", headers=auth_headers).json()["data"]

        assert set(options["districts"]) == {"Guntur", "Krishna"}
        assert "ACTIVE" in options["statuses"]

    def test_my_hives_endpoint_is_scoped_and_available(self, client: TestClient, auth_headers):
        make_hive(client, auth_headers)
        body = client.get(f"{API}/beekeepers/me/hives", headers=auth_headers).json()
        assert body["meta"]["total_items"] == 1

    def test_my_hives_is_not_available_to_staff(self, client: TestClient, admin_headers):
        """An administrator has no apiary of their own, so this is a 403, not an empty list."""
        assert client.get(f"{API}/beekeepers/me/hives", headers=admin_headers).status_code == 403


# --------------------------------------------------------------------------- #
# Detail and isolation
# --------------------------------------------------------------------------- #
class TestHiveDetail:
    def test_detail_includes_owner_cluster_devices_and_values(
        self, client: TestClient, auth_headers, beekeeper_record
    ):
        hive = make_hive(client, auth_headers)
        body = client.get(f"{API}/hives/{hive['id']}", headers=auth_headers).json()["data"]

        assert body["owner"]["beekeeper_code"] == beekeeper_record["beekeeper_code"]
        assert body["cluster"] is None  # not yet assigned to a cluster
        assert body["devices"] == []
        assert body["sensor_values"] == []

    def test_another_beekeepers_hive_is_not_found(
        self, client: TestClient, auth_headers, register_user
    ):
        """404 rather than 403: existence itself is not disclosed."""
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        theirs = make_hive(client, other_headers)

        assert client.get(f"{API}/hives/{theirs['id']}", headers=auth_headers).status_code == 404
        assert client.get(f"{API}/hives/{theirs['id']}", headers=other_headers).status_code == 200

    def test_staff_can_read_any_hive(self, client: TestClient, auth_headers, kvic_headers):
        hive = make_hive(client, auth_headers)
        assert client.get(f"{API}/hives/{hive['id']}", headers=kvic_headers).status_code == 200

    def test_unknown_hive_is_not_found(self, client: TestClient, auth_headers):
        assert client.get(f"{API}/hives/{uuid.uuid4()}", headers=auth_headers).status_code == 404

    def test_a_malformed_id_is_a_validation_error(self, client: TestClient, auth_headers):
        assert client.get(f"{API}/hives/not-a-uuid", headers=auth_headers).status_code == 422


# --------------------------------------------------------------------------- #
# Updates and lifecycle
# --------------------------------------------------------------------------- #
class TestHiveUpdates:
    def test_a_partial_update_touches_only_what_was_sent(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        response = client.put(
            f"{API}/hives/{hive['id']}", headers=auth_headers, json={"queen_status": "PRESENT"}
        )

        updated = response.json()["data"]
        assert updated["queen_status"] == "PRESENT"
        assert updated["queen_status_label"] == "Present"
        assert updated["village"] == hive["village"]
        assert updated["bee_species"] == hive["bee_species"]

    def test_an_empty_update_is_refused(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        assert client.put(f"{API}/hives/{hive['id']}", headers=auth_headers, json={}).status_code == 422

    def test_the_code_cannot_be_changed(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        response = client.put(
            f"{API}/hives/{hive['id']}", headers=auth_headers, json={"hive_code": "HIVE-GNT-00099"}
        )
        assert response.status_code == 422

    def test_a_beekeeper_cannot_edit_someone_elses_hive(
        self, client: TestClient, auth_headers, register_user
    ):
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        theirs = make_hive(client, other_headers)

        response = client.put(
            f"{API}/hives/{theirs['id']}", headers=auth_headers, json={"notes": "Mine now."}
        )
        assert response.status_code == 404  # indistinguishable from "no such hive"

        unchanged = client.get(f"{API}/hives/{theirs['id']}", headers=other_headers).json()["data"]
        assert unchanged["notes"] == VALID_HIVE["notes"]

    def test_staff_may_correct_a_hive(self, client: TestClient, auth_headers, kvic_headers):
        hive = make_hive(client, auth_headers)
        response = client.put(
            f"{API}/hives/{hive['id']}", headers=kvic_headers, json={"village": "Corrected"}
        )
        assert response.status_code == 200
        assert response.json()["data"]["village"] == "Corrected"

    def test_the_update_is_audited_with_field_names_only(
        self, client: TestClient, auth_headers, db: Session
    ):
        from app.models.audit_log import AuditLog

        hive = make_hive(client, auth_headers)
        client.put(f"{API}/hives/{hive['id']}", headers=auth_headers, json={"notes": "Moved."})

        entry = (
            db.query(AuditLog)
            .filter(AuditLog.action == "HIVE_UPDATED", AuditLog.entity_id == hive["id"])
            .one_or_none()
        )
        assert entry is not None
        assert entry.event_metadata["changed_fields"] == ["notes"]
        # The note itself is not copied into the audit log.
        assert "Moved." not in str(entry.event_metadata)


class TestHiveStatus:
    def test_status_change_records_both_states(
        self, client: TestClient, auth_headers, db: Session
    ):
        from app.models.audit_log import AuditLog

        hive = make_hive(client, auth_headers)
        response = client.patch(
            f"{API}/hives/{hive['id']}/status",
            headers=auth_headers,
            json={"status": "MAINTENANCE", "reason": "Hive box repair."},
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "MAINTENANCE"

        entry = (
            db.query(AuditLog)
            .filter(AuditLog.action == "HIVE_STATUS_CHANGED", AuditLog.entity_id == hive["id"])
            .one_or_none()
        )
        assert entry.event_metadata["previous_status"] == "ACTIVE"
        assert entry.event_metadata["new_status"] == "MAINTENANCE"
        assert entry.event_metadata["reason"] == "Hive box repair."

    def test_an_unknown_status_is_refused(self, client: TestClient, auth_headers):
        hive = make_hive(client, auth_headers)
        response = client.patch(
            f"{API}/hives/{hive['id']}/status", headers=auth_headers, json={"status": "BROKEN"}
        )
        assert response.status_code == 422

    def test_setting_the_same_status_twice_is_a_no_op(
        self, client: TestClient, auth_headers, db: Session
    ):
        from app.models.audit_log import AuditLog

        hive = make_hive(client, auth_headers)
        before = db.query(AuditLog).filter(AuditLog.action == "HIVE_STATUS_CHANGED").count()
        client.patch(
            f"{API}/hives/{hive['id']}/status", headers=auth_headers, json={"status": "ACTIVE"}
        )
        after = db.query(AuditLog).filter(AuditLog.action == "HIVE_STATUS_CHANGED").count()

        assert before == after

    def test_a_beekeeper_cannot_change_another_hives_status(
        self, client: TestClient, auth_headers, register_user
    ):
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        theirs = make_hive(client, other_headers)

        response = client.patch(
            f"{API}/hives/{theirs['id']}/status", headers=auth_headers, json={"status": "REMOVED"}
        )
        assert response.status_code == 404


class TestHiveRemoval:
    def test_an_empty_hive_is_deleted_outright(self, client: TestClient, auth_headers, db: Session):
        hive = make_hive(client, auth_headers)
        response = client.delete(f"{API}/hives/{hive['id']}", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["data"]["soft_deleted"] is False

        db.expire_all()
        assert db.get(Hive, uuid.UUID(hive["id"])) is None
        assert client.get(f"{API}/hives/{hive['id']}", headers=auth_headers).status_code == 404

    def test_a_hive_with_a_device_is_refused_without_force(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        device = client.post(
            f"{API}/iot/devices",
            headers=auth_headers,
            json={"device_id": "ESP32-GNT-0101", "device_name": "Node A", "hive_id": hive["id"]},
        )
        assert device.status_code == 201, device.text

        response = client.delete(f"{API}/hives/{hive['id']}", headers=auth_headers)

        assert response.status_code == 409
        assert response.json()["error"]["details"]["device_count"] == 1

    def test_force_removes_the_hive_but_keeps_history(
        self, client: TestClient, auth_headers, db: Session
    ):
        hive = make_hive(client, auth_headers)
        client.post(
            f"{API}/iot/devices",
            headers=auth_headers,
            json={"device_id": "ESP32-GNT-0102", "device_name": "Node B", "hive_id": hive["id"]},
        )

        response = client.delete(
            f"{API}/hives/{hive['id']}", headers=auth_headers, params={"force": True}
        )
        data = response.json()["data"]

        assert data["soft_deleted"] is True
        assert data["devices_preserved"] == 1

        db.expire_all()
        stored = db.get(Hive, uuid.UUID(hive["id"]))
        assert stored is not None
        assert stored.status == HiveStatus.REMOVED
        # The device is still attached to the retired hive.
        assert len(stored.devices) == 1

    def test_a_removed_hive_leaves_the_working_registry(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        client.delete(f"{API}/hives/{hive['id']}", headers=auth_headers)

        assert client.get(f"{API}/hives", headers=auth_headers).json()["data"] == []

    def test_a_beekeeper_cannot_delete_another_hives(self, client: TestClient, auth_headers, register_user):
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        theirs = make_hive(client, other_headers)

        response = client.delete(f"{API}/hives/{theirs['id']}", headers=auth_headers)
        assert response.status_code == 404
        assert client.get(f"{API}/hives/{theirs['id']}", headers=other_headers).status_code == 200

    def test_a_consumer_cannot_delete_anything(self, client: TestClient, auth_headers, consumer_headers):
        hive = make_hive(client, auth_headers)
        assert client.delete(f"{API}/hives/{hive['id']}", headers=consumer_headers).status_code == 403

    def test_deletion_is_audited(self, client: TestClient, auth_headers, db: Session):
        from app.models.audit_log import AuditLog

        hive = make_hive(client, auth_headers)
        client.delete(f"{API}/hives/{hive['id']}", headers=auth_headers)

        entry = (
            db.query(AuditLog)
            .filter(AuditLog.action == "HIVE_REMOVED", AuditLog.entity_id == hive["id"])
            .one_or_none()
        )
        assert entry is not None
        assert entry.event_metadata["hard_delete"] is True
