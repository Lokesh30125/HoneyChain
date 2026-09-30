"""Phase 3 — device registry, sensor configuration and derived device health."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

API = "/api/v1"

HIVE = {
    "bee_species": "Apis cerana indica",
    "village": "Tenali",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "pincode": "522201",
    "latitude": 16.243,
    "longitude": 80.64,
}

DEVICE_ID = "ESP32-GNT-0001"


def make_hive(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post(f"{API}/hives", headers=headers, json={**HIVE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def register_device(client: TestClient, headers: dict, hive_id: str | None = None, **overrides):
    payload = {
        "device_id": DEVICE_ID,
        "device_name": "North field node",
        "hive_id": hive_id,
        **overrides,
    }
    return client.post(f"{API}/iot/devices", headers=headers, json=payload)


def make_device(client: TestClient, headers: dict, hive_id: str | None = None, **overrides) -> dict:
    hive_id = hive_id or make_hive(client, headers)["id"]
    response = register_device(client, headers, hive_id, **overrides)
    assert response.status_code == 201, response.text
    return response.json()["data"]


class TestDeviceRegistration:
    def test_requires_authentication(self, client: TestClient):
        assert client.post(f"{API}/iot/devices", json={}).status_code == 401

    def test_a_consumer_cannot_register_a_device(self, client: TestClient, auth_headers, consumer_headers):
        hive = make_hive(client, auth_headers)
        response = register_device(client, consumer_headers, hive["id"])
        assert response.status_code == 403

    def test_registration_seeds_the_sensor_set(self, client: TestClient, auth_headers):
        device = make_device(client, auth_headers)

        assert device["device_id"] == DEVICE_ID
        assert device["status"] == "OFFLINE"
        assert device["status_label"] == "Offline"
        assert device["last_seen"] is None

        sensors = client.get(f"{API}/iot/devices/{device['id']}/sensors", headers=auth_headers).json()["data"]
        assert {sensor["sensor_type"] for sensor in sensors} == {
            "TEMPERATURE",
            "HUMIDITY",
            "WEIGHT",
            "VIBRATION",
            "ACOUSTIC",
        }
        assert all(sensor["enabled"] for sensor in sensors)
        assert all(sensor["sampling_interval"] > 0 for sensor in sensors)

    def test_the_mqtt_topic_is_derived_from_the_hardware_id(self, client: TestClient, auth_headers):
        device = make_device(client, auth_headers)
        assert device["mqtt_topic"] == f"honeychain/devices/{DEVICE_ID}/telemetry"

    def test_device_ids_are_case_insensitive_and_unique(self, client: TestClient, auth_headers):
        make_device(client, auth_headers)
        response = register_device(client, auth_headers, make_hive(client, auth_headers)["id"], device_id="esp32-gnt-0001")

        assert response.status_code == 422
        assert response.json()["error"]["details"]["field"] == "device_id"

    def test_a_malformed_device_id_is_refused(self, client: TestClient, auth_headers):
        for bad in ("ab", "ESP32 GNT 1", "esp32/../etc"):
            response = register_device(client, auth_headers, None, device_id=bad)
            assert response.status_code in (422, 400), bad

    def test_a_device_cannot_be_attached_to_another_beekeepers_hive(
        self, client: TestClient, auth_headers, register_user
    ):
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        theirs = make_hive(client, other_headers)

        response = register_device(client, auth_headers, theirs["id"])

        # 404, not 403: the caller cannot tell "not yours" from "does not exist".
        assert response.status_code == 404

    def test_an_unknown_hive_is_not_found(self, client: TestClient, auth_headers):
        assert register_device(client, auth_headers, str(uuid.uuid4())).status_code == 404

    def test_registration_is_audited(self, client: TestClient, auth_headers, db):
        from app.models.audit_log import AuditLog

        device = make_device(client, auth_headers)
        entry = (
            db.query(AuditLog)
            .filter(AuditLog.action == "DEVICE_REGISTERED", AuditLog.entity_id == device["id"])
            .one_or_none()
        )
        assert entry is not None
        assert entry.event_metadata["device_id"] == DEVICE_ID
        assert entry.event_metadata["sensors_configured"] == 5


class TestDeviceHealth:
    def test_a_new_device_is_offline_because_it_has_never_reported(
        self, client: TestClient, auth_headers
    ):
        device = make_device(client, auth_headers)
        assert client.get(f"{API}/iot/devices/{device['id']}", headers=auth_headers).json()["data"]["status"] == "OFFLINE"

    def test_a_device_becomes_online_when_it_reports(self, client: TestClient, auth_headers):
        device = make_device(client, auth_headers)

        reading = client.post(
            f"{API}/iot/telemetry",
            headers=auth_headers,
            json={"device_id": DEVICE_ID, "temperature": 33.4, "humidity": 58.0},
        )
        assert reading.status_code == 201, reading.text
        assert reading.json()["data"]["device_status"] == "ONLINE"

        detail = client.get(f"{API}/iot/devices/{device['id']}", headers=auth_headers).json()["data"]
        assert detail["status"] == "ONLINE"
        assert detail["last_seen"] is not None
        assert detail["readings_last_24h"] == 1

    def test_a_low_battery_reports_a_warning(self, client: TestClient, auth_headers):
        make_device(client, auth_headers)
        client.post(
            f"{API}/iot/telemetry",
            headers=auth_headers,
            json={"device_id": DEVICE_ID, "temperature": 31.0, "battery_level": 8},
        )

        devices = client.get(f"{API}/iot/devices", headers=auth_headers).json()["data"]
        assert devices[0]["status"] == "WARNING"

    def test_a_device_that_has_gone_quiet_is_offline(
        self, client: TestClient, auth_headers, db
    ):
        from app.models.iot_device import IotDevice

        device = make_device(client, auth_headers)
        client.post(
            f"{API}/iot/telemetry",
            headers=auth_headers,
            json={"device_id": DEVICE_ID, "temperature": 33.0},
        )

        # Age the last_seen beyond the offline threshold and let the sweep decide.
        stored = db.get(IotDevice, uuid.UUID(device["id"]))
        stored.last_seen = datetime.now(timezone.utc) - timedelta(hours=5)
        db.commit()

        detail = client.get(f"{API}/iot/devices/{device['id']}", headers=auth_headers).json()["data"]
        assert detail["status"] == "OFFLINE"
        assert detail["seconds_since_last_seen"] > 3600

    def test_an_operator_can_take_a_device_out_for_maintenance(
        self, client: TestClient, auth_headers
    ):
        device = make_device(client, auth_headers)
        response = client.patch(
            f"{API}/iot/devices/{device['id']}/status",
            headers=auth_headers,
            json={"status": "MAINTENANCE", "reason": "Load cell replacement."},
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "MAINTENANCE"

    def test_a_device_cannot_be_declared_healthy_by_hand(self, client: TestClient, auth_headers):
        """ONLINE is derived from last_seen; asking for it changes nothing."""
        device = make_device(client, auth_headers)
        response = client.patch(
            f"{API}/iot/devices/{device['id']}/status",
            headers=auth_headers,
            json={"status": "ONLINE"},
        )
        assert response.json()["data"]["status"] == "OFFLINE"

    def test_a_heartbeat_marks_the_device_reachable(self, client: TestClient, auth_headers):
        make_device(client, auth_headers)
        response = client.post(
            f"{API}/iot/devices/heartbeat",
            headers=auth_headers,
            json={"device_id": DEVICE_ID, "battery_level": 77, "signal_strength": -70},
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["status"] == "ONLINE"
        assert body["battery_level"] == 77
        assert body["signal_strength"] == -70

    def test_a_heartbeat_for_an_unknown_device_is_rejected(
        self, client: TestClient, auth_headers
    ):
        response = client.post(
            f"{API}/iot/devices/heartbeat", headers=auth_headers, json={"device_id": "ESP32-GNT-9999"}
        )
        assert response.status_code == 404


class TestDeviceListing:
    def test_a_beekeeper_sees_only_their_own_devices(
        self, client: TestClient, auth_headers, register_user
    ):
        make_device(client, auth_headers)
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        make_device(client, other_headers, device_id="ESP32-GNT-0002")

        mine = client.get(f"{API}/iot/devices", headers=auth_headers).json()
        theirs = client.get(f"{API}/iot/devices", headers=other_headers).json()

        assert mine["meta"]["total_items"] == 1
        assert theirs["meta"]["total_items"] == 1
        assert mine["data"][0]["hive_code"] != theirs["data"][0]["hive_code"]

    def test_staff_see_every_device(
        self, client: TestClient, auth_headers, register_user, kvic_headers
    ):
        make_device(client, auth_headers)
        other = register_user(email=None)
        make_device(client, {"Authorization": f"Bearer {other['access_token']}"}, device_id="ESP32-GNT-0003")

        assert client.get(f"{API}/iot/devices", headers=kvic_headers).json()["meta"]["total_items"] == 2

    def test_rows_carry_their_hive_and_sensor_counts(self, client: TestClient, auth_headers):
        device = make_device(client, auth_headers)
        row = client.get(f"{API}/iot/devices", headers=auth_headers).json()["data"][0]

        assert row["hive_code"].startswith("HIVE-GNT-")
        assert row["sensors_enabled"] == 5
        assert row["sensors_total"] == 5
        assert row["latest_reading_at"] is None
        assert row["seconds_since_last_seen"] is None
        assert device["id"] == row["id"]

    def test_search_and_status_filters(self, client: TestClient, auth_headers):
        make_device(client, auth_headers)
        assert client.get(f"{API}/iot/devices", headers=auth_headers, params={"search": "ESP32-GNT"}).json()["meta"]["total_items"] == 1
        assert client.get(f"{API}/iot/devices", headers=auth_headers, params={"search": "nothing"}).json()["meta"]["total_items"] == 0
        assert client.get(f"{API}/iot/devices", headers=auth_headers, params={"status": "OFFLINE"}).json()["meta"]["total_items"] == 1
        assert client.get(f"{API}/iot/devices", headers=auth_headers, params={"status": "ONLINE"}).json()["meta"]["total_items"] == 0

    def test_my_devices_endpoint_returns_the_callers_apiary(self, client: TestClient, auth_headers):
        make_device(client, auth_headers)
        body = client.get(f"{API}/iot/me/devices", headers=auth_headers).json()
        assert len(body["data"]) == 1

    def test_a_consumer_cannot_list_devices(self, client: TestClient, consumer_headers):
        assert client.get(f"{API}/iot/devices", headers=consumer_headers).status_code == 403

    def test_another_beekeepers_device_is_not_found_by_id(
        self, client: TestClient, auth_headers, register_user
    ):
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        theirs = make_device(client, other_headers, device_id="ESP32-GNT-0004")

        assert client.get(f"{API}/iot/devices/{theirs['id']}", headers=auth_headers).status_code == 404


class TestDeviceUpdates:
    def test_rename_and_firmware_update(self, client: TestClient, auth_headers):
        device = make_device(client, auth_headers)
        response = client.put(
            f"{API}/iot/devices/{device['id']}",
            headers=auth_headers,
            json={"device_name": "Renamed node", "firmware_version": "1.2.0"},
        )

        assert response.status_code == 200
        assert response.json()["data"]["device_name"] == "Renamed node"
        assert response.json()["data"]["firmware_version"] == "1.2.0"

    def test_a_device_id_cannot_be_changed(self, client: TestClient, auth_headers):
        device = make_device(client, auth_headers)
        response = client.put(
            f"{API}/iot/devices/{device['id']}", headers=auth_headers, json={"device_id": "ESP32-OTHER"}
        )
        assert response.status_code == 422

    def test_a_device_can_be_moved_between_own_hives(self, client: TestClient, auth_headers):
        device = make_device(client, auth_headers)
        second_hive = make_hive(client, auth_headers, village="Kuchipudi")

        response = client.put(
            f"{API}/iot/devices/{device['id']}", headers=auth_headers, json={"hive_id": second_hive["id"]}
        )

        assert response.status_code == 200
        assert response.json()["data"]["hive_id"] == second_hive["id"]

    def test_a_device_cannot_be_moved_to_another_beekeepers_hive(
        self, client: TestClient, auth_headers, register_user
    ):
        device = make_device(client, auth_headers)
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        theirs = make_hive(client, other_headers)

        response = client.put(
            f"{API}/iot/devices/{device['id']}", headers=auth_headers, json={"hive_id": theirs["id"]}
        )
        assert response.status_code == 404

    def test_another_beekeeper_cannot_edit_a_device(
        self, client: TestClient, auth_headers, register_user
    ):
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        theirs = make_device(client, other_headers, device_id="ESP32-GNT-0005")

        response = client.put(
            f"{API}/iot/devices/{theirs['id']}", headers=auth_headers, json={"device_name": "Hijacked"}
        )
        assert response.status_code == 404


class TestSensorConfiguration:
    def test_a_sensor_can_be_disabled_and_retuned(self, client: TestClient, auth_headers):
        device = make_device(client, auth_headers)
        response = client.patch(
            f"{API}/iot/devices/{device['id']}/sensors/humidity",
            headers=auth_headers,
            json={"enabled": False, "sensor_name": "Hive humidity (spare)", "sampling_interval": 600},
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["enabled"] is False
        assert body["sampling_interval"] == 600

    def test_a_configured_range_narrows_validation(self, client: TestClient, auth_headers):
        device = make_device(client, auth_headers)
        client.patch(
            f"{API}/iot/devices/{device['id']}/sensors/temperature",
            headers=auth_headers,
            json={"min_valid_value": 25.0, "max_valid_value": 40.0},
        )

        # Inside the platform bound (-20..80) but outside the hive's own range.
        response = client.post(
            f"{API}/iot/telemetry", headers=auth_headers, json={"device_id": DEVICE_ID, "temperature": 45.0}
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"]["max"] == 40.0

    def test_an_inverted_range_is_refused(self, client: TestClient, auth_headers):
        device = make_device(client, auth_headers)
        response = client.patch(
            f"{API}/iot/devices/{device['id']}/sensors/weight",
            headers=auth_headers,
            json={"min_valid_value": 50.0, "max_valid_value": 10.0},
        )
        assert response.status_code == 422

    def test_a_sensor_the_device_does_not_carry_is_not_found(
        self, client: TestClient, auth_headers
    ):
        device = make_device(client, auth_headers)
        response = client.patch(
            f"{API}/iot/devices/{device['id']}/sensors/battery",
            headers=auth_headers,
            json={"enabled": False},
        )
        # Power data arrives with the packet's battery_level field rather than as
        # a configured sensor row, so there is nothing to configure here.
        assert response.status_code == 404

    def test_an_unknown_sensor_name_is_a_validation_error(
        self, client: TestClient, auth_headers
    ):
        device = make_device(client, auth_headers)
        response = client.patch(
            f"{API}/iot/devices/{device['id']}/sensors/telepathy",
            headers=auth_headers,
            json={"enabled": False},
        )
        assert response.status_code == 422
        assert "HUMIDITY" in response.json()["error"]["details"]["allowed"]

    def test_another_beekeeper_cannot_touch_the_sensors(
        self, client: TestClient, auth_headers, register_user
    ):
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        theirs = make_device(client, other_headers, device_id="ESP32-GNT-0006")

        response = client.patch(
            f"{API}/iot/devices/{theirs['id']}/sensors/humidity",
            headers=auth_headers,
            json={"enabled": False},
        )
        assert response.status_code == 404


class TestDeviceRemoval:
    def test_a_device_with_no_history_is_deleted(self, client: TestClient, auth_headers):
        device = make_device(client, auth_headers)
        response = client.delete(f"{API}/iot/devices/{device['id']}", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["data"]["readings_deleted"] == 0
        assert client.get(f"{API}/iot/devices/{device['id']}", headers=auth_headers).status_code == 404

    def test_deleting_a_device_with_readings_needs_confirmation(
        self, client: TestClient, auth_headers
    ):
        device = make_device(client, auth_headers)
        client.post(
            f"{API}/iot/telemetry", headers=auth_headers, json={"device_id": DEVICE_ID, "temperature": 32.0}
        )

        refused = client.delete(f"{API}/iot/devices/{device['id']}", headers=auth_headers)
        assert refused.status_code == 409
        assert refused.json()["error"]["details"]["reading_count"] == 1

        # Still there — the refusal changed nothing.
        assert client.get(f"{API}/iot/devices/{device['id']}", headers=auth_headers).status_code == 200

    def test_confirmed_deletion_reports_what_it_removed(self, client: TestClient, auth_headers):
        device = make_device(client, auth_headers)
        client.post(
            f"{API}/iot/telemetry", headers=auth_headers, json={"device_id": DEVICE_ID, "temperature": 32.0}
        )

        response = client.delete(
            f"{API}/iot/devices/{device['id']}", headers=auth_headers, params={"confirm": True}
        )
        assert response.status_code == 200
        assert response.json()["data"]["readings_deleted"] == 1

    def test_the_loss_is_recorded_in_the_audit_log(
        self, client: TestClient, auth_headers, db
    ):
        from app.models.audit_log import AuditLog

        device = make_device(client, auth_headers)
        client.post(
            f"{API}/iot/telemetry", headers=auth_headers, json={"device_id": DEVICE_ID, "temperature": 32.0}
        )
        client.delete(f"{API}/iot/devices/{device['id']}", headers=auth_headers, params={"confirm": True})

        entry = (
            db.query(AuditLog)
            .filter(AuditLog.action == "DEVICE_UPDATED", AuditLog.entity_id == device["id"])
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert entry.event_metadata["removed"] is True
        assert entry.event_metadata["readings_deleted"] == 1

    def test_another_beekeeper_cannot_delete_a_device(
        self, client: TestClient, auth_headers, register_user
    ):
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        theirs = make_device(client, other_headers, device_id="ESP32-GNT-0007")

        assert client.delete(f"{API}/iot/devices/{theirs['id']}", headers=auth_headers).status_code == 404
        assert client.get(f"{API}/iot/devices/{theirs['id']}", headers=other_headers).status_code == 200
