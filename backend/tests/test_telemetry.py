"""Phase 3 — telemetry ingest, validation, history and monitoring.

Two things matter more than the happy path here:

* a reading that cannot be true is **rejected**, never clamped into a plausible
  value (a broken probe must look broken);
* one beekeeper can never write into, or read, another's series.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

API = "/api/v1"
DEVICE_ID = "ESP32-GNT-0001"

HIVE = {
    "village": "Tenali",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "latitude": 16.243,
    "longitude": 80.64,
}


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def make_hive(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post(f"{API}/hives", headers=headers, json={**HIVE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def make_device(client: TestClient, headers: dict, hive_id: str | None = None, **overrides) -> dict:
    hive_id = hive_id or make_hive(client, headers)["id"]
    response = client.post(
        f"{API}/iot/devices",
        headers=headers,
        json={
            "device_id": overrides.pop("device_id", DEVICE_ID),
            "device_name": "North field node",
            "hive_id": hive_id,
            **overrides,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def post_reading(client: TestClient, headers: dict, **payload):
    return client.post(f"{API}/iot/telemetry", headers=headers, json=payload)


class TestIngest:
    def test_requires_authentication(self, client: TestClient):
        assert client.post(f"{API}/iot/telemetry", json={"device_id": DEVICE_ID}).status_code == 401

    def test_a_consumer_cannot_submit_telemetry(self, client: TestClient, auth_headers, consumer_headers):
        make_device(client, auth_headers)
        response = post_reading(client, consumer_headers, device_id=DEVICE_ID, temperature=30.0)
        assert response.status_code == 403

    def test_a_valid_packet_is_stored_and_the_device_goes_online(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        make_device(client, auth_headers, hive["id"])

        response = post_reading(
            client,
            auth_headers,
            device_id=DEVICE_ID,
            temperature=33.4,
            humidity=58.2,
            weight=41.5,
            vibration=0.4,
            acoustic_level=44.0,
            battery_level=88,
            signal_strength=-67,
        )

        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert data["stored"] is True
        assert data["duplicate"] is False
        assert data["source"] == "MANUAL"  # a signed-in caller is a manual entry
        assert data["hive_code"] == hive["hive_code"]
        assert data["device_status"] == "ONLINE"

    def test_a_declared_simulator_reading_stays_labelled(self, client: TestClient, auth_headers):
        make_device(client, auth_headers)
        response = post_reading(
            client, auth_headers, device_id=DEVICE_ID, temperature=31.0, source="SIMULATOR"
        )
        assert response.json()["data"]["source"] == "SIMULATOR"

    def test_the_same_instant_twice_is_a_duplicate_not_a_second_row(
        self, client: TestClient, auth_headers, db
    ):
        hive = make_hive(client, auth_headers)
        make_device(client, auth_headers, hive["id"])
        moment = datetime.now(timezone.utc).replace(microsecond=0)

        first = post_reading(client, auth_headers, device_id=DEVICE_ID, temperature=30.0, timestamp=iso(moment))
        second = post_reading(client, auth_headers, device_id=DEVICE_ID, temperature=30.0, timestamp=iso(moment))

        assert first.json()["data"]["stored"] is True
        assert second.json()["data"]["duplicate"] is True
        assert second.json()["data"]["stored"] is False

        from app.repositories.sensor_reading_repository import SensorReadingRepository

        assert SensorReadingRepository(db).count_in_window(hive_id=uuid.UUID(hive["id"])) == 1

    def test_an_unknown_device_is_rejected(self, client: TestClient, auth_headers):
        response = post_reading(client, auth_headers, device_id="ESP32-NOWHERE", temperature=30.0)
        assert response.status_code == 404

    def test_a_packet_with_no_measurements_is_refused(self, client: TestClient, auth_headers):
        make_device(client, auth_headers)
        response = post_reading(client, auth_headers, device_id=DEVICE_ID)
        assert response.status_code == 422

    def test_a_device_cannot_exist_without_a_hive(self, client: TestClient, auth_headers, db):
        """A reading is always attributable to a hive — enforced by the schema."""
        from app.models.iot_device import IotDevice

        make_device(client, auth_headers)
        column = IotDevice.__table__.columns["hive_id"]

        assert column.nullable is False
        assert db.query(IotDevice).one().hive_id is not None

    def test_a_beekeeper_cannot_submit_for_another_beekeepers_device(
        self, client: TestClient, auth_headers, register_user
    ):
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        make_device(client, other_headers, device_id="ESP32-GNT-0099")

        response = post_reading(client, auth_headers, device_id="ESP32-GNT-0099", temperature=30.0)

        assert response.status_code == 403
        assert "another beekeeper" in response.json()["error"]["message"]


class TestValidation:
    """Every rejection is a 422 with the bound in the details — never a clamp."""

    def _device(self, client: TestClient, headers: dict) -> None:
        make_device(client, headers)

    def test_temperature_outside_the_physical_range(self, client: TestClient, auth_headers):
        self._device(client, auth_headers)
        for value in (-25.0, 95.0):
            response = post_reading(client, auth_headers, device_id=DEVICE_ID, temperature=value)
            assert response.status_code == 422, value
            details = response.json()["error"]["details"]
            assert details["field"] == "temperature"
            assert details["min"] == -20.0 and details["max"] == 80.0

    def test_humidity_outside_zero_to_one_hundred(self, client: TestClient, auth_headers):
        self._device(client, auth_headers)
        assert post_reading(client, auth_headers, device_id=DEVICE_ID, humidity=140.0).status_code == 422
        assert post_reading(client, auth_headers, device_id=DEVICE_ID, humidity=-1.0).status_code == 422

    def test_a_negative_weight_is_impossible(self, client: TestClient, auth_headers):
        self._device(client, auth_headers)
        assert post_reading(client, auth_headers, device_id=DEVICE_ID, weight=-4.0).status_code == 422

    def test_battery_is_a_percentage(self, client: TestClient, auth_headers):
        self._device(client, auth_headers)
        assert post_reading(client, auth_headers, device_id=DEVICE_ID, battery_level=150).status_code == 422

    def test_signal_strength_is_in_dbm(self, client: TestClient, auth_headers):
        self._device(client, auth_headers)
        assert post_reading(client, auth_headers, device_id=DEVICE_ID, signal_strength=-500).status_code == 422

    def test_a_rejected_value_is_not_stored(self, client: TestClient, auth_headers):
        """The important half of "reject, don't clamp"."""
        self._device(client, auth_headers)
        post_reading(client, auth_headers, device_id=DEVICE_ID, temperature=999.0)

        body = client.get(
            f"{API}/iot/devices", headers=auth_headers, params={"search": DEVICE_ID}
        ).json()
        assert body["data"][0]["latest_reading_at"] is None

    def test_a_future_timestamp_is_refused(self, client: TestClient, auth_headers):
        self._device(client, auth_headers)
        ahead = datetime.now(timezone.utc) + timedelta(hours=3)
        response = post_reading(
            client, auth_headers, device_id=DEVICE_ID, temperature=30.0, timestamp=iso(ahead)
        )

        assert response.status_code == 422
        assert response.json()["error"]["details"]["field"] == "timestamp"

    def test_a_modest_clock_skew_is_tolerated(self, client: TestClient, auth_headers):
        """Devices without an NTP sync are a fact of field life."""
        self._device(client, auth_headers)
        slightly_ahead = datetime.now(timezone.utc) + timedelta(seconds=60)
        response = post_reading(
            client, auth_headers, device_id=DEVICE_ID, temperature=30.0, timestamp=iso(slightly_ahead)
        )
        assert response.status_code == 201

    def test_a_missing_timestamp_uses_receipt_time(self, client: TestClient, auth_headers):
        self._device(client, auth_headers)
        response = post_reading(client, auth_headers, device_id=DEVICE_ID, temperature=30.0)
        assert response.json()["data"]["timestamp"] is not None


class TestBatchIngest:
    def test_a_backlog_is_accepted_and_invalid_packets_are_reported_individually(
        self, client: TestClient, auth_headers
    ):
        make_device(client, auth_headers)
        now = datetime.now(timezone.utc).replace(microsecond=0)

        response = client.post(
            f"{API}/iot/telemetry/batch",
            headers=auth_headers,
            json=[
                {"device_id": DEVICE_ID, "temperature": 30.0, "timestamp": iso(now - timedelta(minutes=20))},
                {"device_id": DEVICE_ID, "temperature": 30.5, "timestamp": iso(now - timedelta(minutes=15))},
                {"device_id": DEVICE_ID, "temperature": 900.0, "timestamp": iso(now - timedelta(minutes=10))},
            ],
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["submitted"] == 3
        assert data["stored"] == 2
        assert data["rejected_count"] == 1
        assert data["rejected"][0]["index"] == 2

    def test_an_empty_batch_is_refused(self, client: TestClient, auth_headers):
        assert (
            client.post(f"{API}/iot/telemetry/batch", headers=auth_headers, json=[]).status_code == 422
        )


class TestHistory:
    def _seed(self, client: TestClient, headers: dict, *, count: int = 3) -> dict:
        hive = make_hive(client, headers)
        make_device(client, headers, hive["id"])
        base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=count)
        for index in range(count):
            post_reading(
                client,
                headers,
                device_id=DEVICE_ID,
                temperature=30.0 + index,
                humidity=55.0,
                timestamp=iso(base + timedelta(minutes=index)),
                source="SIMULATOR",
            )
        return hive

    def test_history_returns_the_samples_in_order(self, client: TestClient, auth_headers):
        hive = self._seed(client, auth_headers)
        body = client.get(f"{API}/iot/telemetry/{hive['id']}", headers=auth_headers).json()["data"]

        assert body["count"] == 3
        assert [point["temperature"] for point in body["points"]] == [30.0, 31.0, 32.0]
        # Raw points carry the machine-readable source; the UI maps it to a label.
        assert all(point["source"] == "SIMULATOR" for point in body["points"])
        assert body["latest"]["temperature"] == 32.0

    def test_source_mix_reports_what_the_chart_is_showing(self, client: TestClient, auth_headers):
        hive = self._seed(client, auth_headers)
        body = client.get(f"{API}/iot/telemetry/{hive['id']}", headers=auth_headers).json()["data"]

        assert body["source_mix"] == {"SIMULATOR": 3}

    def test_a_range_preset_buckets_the_series(self, client: TestClient, auth_headers):
        hive = self._seed(client, auth_headers, count=4)
        body = client.get(
            f"{API}/iot/telemetry/{hive['id']}", headers=auth_headers, params={"range": "24h"}
        ).json()["data"]

        assert body["interval"] == "15m"
        # Four one-a-minute samples collapse to at most two 15-minute buckets
        # (the first and last can straddle a boundary), never four.
        assert 1 <= body["count"] <= 2
        assert sum(point["samples"] for point in body["points"]) == 4
        # Every point is the mean of its own samples, so the overall mean holds.
        weighted = sum(
            point["temperature"] * point["samples"] for point in body["points"]
        ) / 4
        assert round(weighted, 2) == 31.5

    def test_an_explicit_window_and_interval_is_honoured(self, client: TestClient, auth_headers):
        hive = self._seed(client, auth_headers, count=3)
        now = datetime.now(timezone.utc)
        body = client.get(
            f"{API}/iot/telemetry/{hive['id']}",
            headers=auth_headers,
            params={
                "from": iso(now - timedelta(hours=1)),
                "to": iso(now),
                "interval": "1m",
            },
        ).json()["data"]

        assert body["interval"] == "1m"
        assert body["count"] == 3

    def test_one_sensor_can_be_requested_alone(self, client: TestClient, auth_headers):
        hive = self._seed(client, auth_headers)
        body = client.get(
            f"{API}/iot/telemetry/{hive['id']}", headers=auth_headers, params={"sensor_type": "humidity"}
        ).json()["data"]

        # The request was case-insensitive; the response echoes the enum value.
        assert body["sensor_type"] == "HUMIDITY"
        # Unrequested sensors are present but null, so every point has the same
        # keys and a chart never has to guess which series exist.
        assert body["points"][0]["weight"] is None
        assert body["points"][0]["humidity"] == 55.0

    def test_an_empty_window_says_so_rather_than_charting_zeros(
        self, client: TestClient, auth_headers
    ):
        hive = make_hive(client, auth_headers)
        make_device(client, auth_headers, hive["id"])

        body = client.get(f"{API}/iot/telemetry/{hive['id']}", headers=auth_headers).json()["data"]

        assert body["points"] == []
        assert body["latest"] is None
        assert "No telemetry" in body["message"]

    def test_an_unknown_range_is_refused(self, client: TestClient, auth_headers):
        hive = self._seed(client, auth_headers)
        response = client.get(
            f"{API}/iot/telemetry/{hive['id']}", headers=auth_headers, params={"range": "99y"}
        )
        assert response.status_code == 422

    def test_another_beekeepers_series_is_not_found(
        self, client: TestClient, auth_headers, register_user
    ):
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        theirs = self._seed(client, other_headers)

        response = client.get(f"{API}/iot/telemetry/{theirs['id']}", headers=auth_headers)
        assert response.status_code == 404

    def test_staff_can_read_any_series(
        self, client: TestClient, auth_headers, kvic_headers
    ):
        hive = self._seed(client, auth_headers)
        assert client.get(f"{API}/iot/telemetry/{hive['id']}", headers=kvic_headers).status_code == 200

    def test_a_consumer_cannot_read_telemetry(self, client: TestClient, auth_headers, consumer_headers):
        hive = self._seed(client, auth_headers)
        response = client.get(f"{API}/iot/telemetry/{hive['id']}", headers=consumer_headers)
        assert response.status_code == 403


class TestLatestAndMonitoring:
    def _seed(self, client: TestClient, headers: dict) -> dict:
        hive = make_hive(client, headers)
        make_device(client, headers, hive["id"])
        post_reading(
            client, headers, device_id=DEVICE_ID, temperature=34.5, humidity=57.0, weight=42.1
        )
        return hive

    def test_latest_panel_reports_each_device(self, client: TestClient, auth_headers):
        hive = self._seed(client, auth_headers)
        body = client.get(f"{API}/iot/telemetry/{hive['id']}/latest", headers=auth_headers).json()["data"]

        assert body["hive_code"] == hive["hive_code"]
        assert body["latest"]["temperature"] == 34.5
        assert body["devices"][0]["device_id"] == DEVICE_ID
        assert body["devices"][0]["reading"]["humidity"] == 57.0

    def test_latest_is_not_found_for_another_beekeepers_hive(
        self, client: TestClient, auth_headers, register_user
    ):
        other = register_user(email=None)
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        theirs = self._seed(client, other_headers)

        assert client.get(f"{API}/iot/telemetry/{theirs['id']}/latest", headers=auth_headers).status_code == 404

    def test_summary_counts_only_real_rows(self, client: TestClient, auth_headers):
        self._seed(client, auth_headers)
        body = client.get(f"{API}/iot/devices/summary", headers=auth_headers).json()["data"]

        assert body["total_hives"] == 1
        assert body["total_devices"] == 1
        assert body["connected_devices"] == 1
        assert body["sensors_active"] == 5
        assert body["hives_without_device"] == 0
        assert body["readings_last_window"] == 1
        assert body["last_telemetry_at"] is not None

    def test_summary_is_zeroed_for_an_account_with_nothing(
        self, client: TestClient, register_user
    ):
        fresh = register_user(email=None)
        headers = {"Authorization": f"Bearer {fresh['access_token']}"}
        body = client.get(f"{API}/iot/devices/summary", headers=headers).json()["data"]

        assert body["total_hives"] == 0
        assert body["total_devices"] == 0
        assert body["readings_last_window"] == 0
        assert body["last_telemetry_at"] is None

    def test_last_telemetry_names_the_device_and_hive(self, client: TestClient, auth_headers):
        hive = self._seed(client, auth_headers)
        body = client.get(f"{API}/iot/last-telemetry", headers=auth_headers).json()["data"]

        assert body["has_data"] is True
        assert body["device_id"] == DEVICE_ID
        assert body["hive_code"] == hive["hive_code"]
        assert body["temperature"] == 34.5

    def test_last_telemetry_is_null_when_nothing_has_arrived(
        self, client: TestClient, register_user
    ):
        fresh = register_user(email=None)
        headers = {"Authorization": f"Bearer {fresh['access_token']}"}
        response = client.get(f"{API}/iot/last-telemetry", headers=headers)

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["has_data"] is False
        assert body["timestamp"] is None
        assert "No telemetry" in body["message"]


class TestMqttHealth:
    def test_health_reports_not_configured_without_a_broker(self, client: TestClient):
        body = client.get(f"{API}/health/mqtt").json()["data"]

        assert body["enabled"] is False
        assert body["status"] in {"not_configured", "stopped"}
        assert "POST /api/v1/iot/telemetry" in (body["detail"] or "")

    def test_the_detailed_health_report_includes_the_iot_component(self, client: TestClient):
        components = client.get(f"{API}/health/detailed").json()["components"]

        assert components["iot"]["phase"] == "Phase 3"
        assert components["iot"]["ingest"] == "MQTT + HTTP"
