"""Phase 3 — the MQTT ingest path, tested without a broker.

``MqttIngestService.handle_message`` is deliberately separable from the network:
it takes a topic and a payload and returns what happened. That is what these
tests exercise, so the *entire* ingest contract — routing, device-id agreement,
source labelling, validation, idempotency — is covered in CI on a machine with
no broker installed. Only the socket itself is left untested here, and it is
verified by running the simulator against a broker (see ``docs/iot.md``).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from app.core.config import build_settings
from app.models.enums import TelemetrySource
from app.services.mqtt_service import (
    MqttIngestService,
    extract_device_id,
    parse_telemetry_message,
    telemetry_topic,
)

API = "/api/v1"
DEVICE_ID = "ESP32-GNT-0001"
PREFIX = "honeychain"
TOPIC = f"{PREFIX}/devices/{DEVICE_ID}/telemetry"

HIVE = {"village": "Tenali", "district": "Guntur", "state": "Andhra Pradesh"}


@pytest.fixture()
def mqtt_settings():
    """Settings as they look with a consumer running but no broker reachable.

    ``MQTT_CONSUMER_ENABLED=False`` keeps the background thread out of the test;
    message handling does not depend on it.
    """
    settings = build_settings()
    settings.MQTT_BROKER_URL = "localhost"
    settings.MQTT_TOPIC_PREFIX = PREFIX
    settings.MQTT_CONSUMER_ENABLED = False
    return settings


@pytest.fixture()
def ingest(mqtt_settings) -> MqttIngestService:
    return MqttIngestService(mqtt_settings)


def make_device(client: TestClient, headers: dict, **overrides) -> dict:
    hive = client.post(f"{API}/hives", headers=headers, json=HIVE).json()["data"]
    response = client.post(
        f"{API}/iot/devices",
        headers=headers,
        json={
            "device_id": overrides.pop("device_id", DEVICE_ID),
            "device_name": "North field node",
            "hive_id": hive["id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


# --------------------------------------------------------------------------- #
# Topic helpers
# --------------------------------------------------------------------------- #
class TestTopics:
    def test_topics_are_built_from_the_prefix_and_device_id(self):
        assert telemetry_topic("honeychain", DEVICE_ID) == TOPIC

    def test_the_device_id_is_extracted_from_a_topic(self):
        assert extract_device_id(TOPIC, prefix=PREFIX) == DEVICE_ID
        assert extract_device_id(f"{PREFIX}/devices/{DEVICE_ID}/status", prefix=PREFIX) == DEVICE_ID

    def test_topics_outside_the_prefix_are_ignored(self):
        assert extract_device_id("other/devices/ESP32-X/telemetry", prefix=PREFIX) is None
        assert extract_device_id("honeychain/hives/x/telemetry", prefix=PREFIX) is None
        assert extract_device_id("", prefix=PREFIX) is None


# --------------------------------------------------------------------------- #
# Payload parsing
# --------------------------------------------------------------------------- #
class TestParsing:
    def test_a_full_packet_parses(self):
        packet = parse_telemetry_message(
            json.dumps(
                {
                    "device_id": DEVICE_ID,
                    "temperature": 33.5,
                    "humidity": 58.0,
                    "weight": 41.2,
                    "vibration": 0.3,
                    "acoustic_level": 44.0,
                    "battery_level": 87,
                    "signal_strength": -66,
                    "source": "SIMULATOR",
                }
            )
        )
        assert packet.device_id == DEVICE_ID
        assert packet.source == TelemetrySource.SIMULATOR

    def test_bytes_and_str_are_both_accepted(self):
        raw = json.dumps({"device_id": DEVICE_ID, "temperature": 30})
        assert parse_telemetry_message(raw.encode("utf-8")).temperature == 30
        assert parse_telemetry_message(raw).temperature == 30

    def test_a_packet_without_a_device_id_is_refused(self):
        with pytest.raises(PydanticValidationError):
            parse_telemetry_message(json.dumps({"temperature": 30}))

    def test_a_packet_with_no_measurements_is_refused(self):
        with pytest.raises(PydanticValidationError):
            parse_telemetry_message(json.dumps({"device_id": DEVICE_ID}))

    def test_unknown_fields_are_refused(self):
        """``extra="forbid"``: firmware and simulator cannot drift silently."""
        with pytest.raises(PydanticValidationError):
            parse_telemetry_message(json.dumps({"device_id": DEVICE_ID, "temperatur": 30}))

    def test_malformed_json_is_reported_as_such(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_telemetry_message("{not json")

    def test_a_non_object_payload_is_refused(self):
        with pytest.raises(ValueError, match="JSON object"):
            parse_telemetry_message("[1, 2, 3]")

    def test_invalid_utf8_is_refused(self):
        with pytest.raises(ValueError, match="UTF-8"):
            parse_telemetry_message(b"\xff\xfe\x00")

    def test_an_oversized_payload_is_refused(self):
        with pytest.raises(ValueError, match="byte limit"):
            parse_telemetry_message(json.dumps({"device_id": DEVICE_ID, "notes": "x" * 9000}))


# --------------------------------------------------------------------------- #
# Message handling
# --------------------------------------------------------------------------- #
class TestMessageHandling:
    def test_a_valid_packet_is_stored_as_real_device_data(
        self, client: TestClient, auth_headers, db, ingest: MqttIngestService
    ):
        from app.repositories.sensor_reading_repository import SensorReadingRepository

        make_device(client, auth_headers)
        result = ingest.handle_message(
            TOPIC,
            json.dumps({"device_id": DEVICE_ID, "temperature": 34.1, "humidity": 57.0}),
            session=db,
        )

        assert result["status"] == "stored"
        assert ingest.stats["stored"] == 1

        reading = SensorReadingRepository(db).latest_for_device(
            __import__("uuid").UUID(result_device_id(db, DEVICE_ID))
        )
        # Hardware that does not declare itself a simulator is treated as real.
        assert reading.source == TelemetrySource.REAL_DEVICE
        assert float(reading.temperature) == 34.1

    def test_a_declared_simulator_is_believed(
        self, client: TestClient, auth_headers, db, ingest: MqttIngestService
    ):
        make_device(client, auth_headers)
        result = ingest.handle_message(
            TOPIC,
            json.dumps(
                {"device_id": DEVICE_ID, "temperature": 30.0, "source": "SIMULATOR"}
            ),
            session=db,
        )

        assert result["status"] == "stored"
        reading = reading_for(db, DEVICE_ID)
        assert reading.source == TelemetrySource.SIMULATOR

    def test_a_redelivered_packet_is_a_duplicate(
        self, client: TestClient, auth_headers, db, ingest: MqttIngestService
    ):
        """QoS 1 means at-least-once, so the same message can arrive twice."""
        make_device(client, auth_headers)
        moment = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        payload = json.dumps({"device_id": DEVICE_ID, "temperature": 30.0, "timestamp": moment})

        first = ingest.handle_message(TOPIC, payload, session=db)
        second = ingest.handle_message(TOPIC, payload, session=db)

        assert first["status"] == "stored"
        assert second["status"] == "duplicate"
        assert ingest.stats["duplicates"] == 1

    def test_a_payload_whose_device_id_disagrees_with_its_topic_is_rejected(
        self, client: TestClient, auth_headers, db, ingest: MqttIngestService
    ):
        """Otherwise a compromised node could write into another's series."""
        make_device(client, auth_headers)
        result = ingest.handle_message(
            TOPIC, json.dumps({"device_id": "ESP32-OTHER", "temperature": 30.0}), session=db
        )

        assert result["status"] == "rejected"
        assert result["reason"] == "device id mismatch"
        assert reading_for(db, DEVICE_ID) is None

    def test_a_message_for_an_unknown_device_is_rejected_not_crashed(
        self, client: TestClient, db, ingest: MqttIngestService
    ):
        result = ingest.handle_message(
            f"{PREFIX}/devices/ESP32-GHOST/telemetry",
            json.dumps({"device_id": "ESP32-GHOST", "temperature": 30.0}),
            session=db,
        )

        assert result["status"] == "rejected"
        assert "Unknown device" in result["reason"]

    def test_a_reading_outside_the_valid_range_is_rejected(
        self, client: TestClient, auth_headers, db, ingest: MqttIngestService
    ):
        make_device(client, auth_headers)
        result = ingest.handle_message(
            TOPIC, json.dumps({"device_id": DEVICE_ID, "temperature": 500.0}), session=db
        )

        assert result["status"] == "rejected"
        assert "between" in result["reason"]
        assert reading_for(db, DEVICE_ID) is None

    def test_a_malformed_payload_is_counted_as_a_parse_error(
        self, client: TestClient, db, ingest: MqttIngestService
    ):
        result = ingest.handle_message(TOPIC, "{oops", session=db)

        assert result["status"] == "rejected"
        assert ingest.stats["parse_errors"] == 1

    def test_a_message_on_an_unrelated_topic_is_ignored(
        self, client: TestClient, db, ingest: MqttIngestService
    ):
        result = ingest.handle_message(f"{PREFIX}/something/else", "{}", session=db)

        assert result["status"] == "ignored"
        assert ingest.stats["parse_errors"] == 1

    def test_the_status_top_topic_is_routed_to_the_right_device(
        self, client: TestClient, auth_headers, db, ingest: MqttIngestService
    ):
        """Devices that report liveness on ``/status`` resolve the same device."""
        make_device(client, auth_headers)
        result = ingest.handle_message(
            f"{PREFIX}/devices/{DEVICE_ID}/status",
            json.dumps({"device_id": DEVICE_ID, "temperature": 29.0}),
            session=db,
        )

        assert result["status"] == "stored"

    def test_ingesting_updates_the_device_record(
        self, client: TestClient, auth_headers, db, ingest: MqttIngestService
    ):
        from app.models.iot_device import IotDevice

        make_device(client, auth_headers)
        ingest.handle_message(
            TOPIC,
            json.dumps(
                {"device_id": DEVICE_ID, "temperature": 33.0, "battery_level": 64, "signal_strength": -72}
            ),
            session=db,
        )

        db.expire_all()
        device = db.query(IotDevice).filter(IotDevice.device_id == DEVICE_ID).one()
        assert device.last_seen is not None
        assert device.battery_level == 64
        assert device.signal_strength == -72
        assert str(device.status) == "ONLINE"

    def test_a_batch_of_packets_keeps_the_series_contiguous(
        self, client: TestClient, auth_headers, db, ingest: MqttIngestService
    ):
        from app.models.sensor_reading import SensorReading

        make_device(client, auth_headers)
        base = datetime.now(timezone.utc).replace(microsecond=0)
        for index in range(5):
            ingest.handle_message(
                TOPIC,
                json.dumps(
                    {
                        "device_id": DEVICE_ID,
                        "temperature": 30.0 + index,
                        "timestamp": (base - timedelta(minutes=5 - index)).isoformat(),
                    }
                ),
                session=db,
            )

        assert db.query(SensorReading).count() == 5
        assert ingest.stats["stored"] == 5

    def test_telemetry_auditing_is_windowed_not_per_packet(
        self, client: TestClient, auth_headers, db, ingest: MqttIngestService
    ):
        """A 5-minute cadence must not write an audit row five times an hour."""
        from app.models.audit_log import AuditLog

        make_device(client, auth_headers)
        base = datetime.now(timezone.utc).replace(microsecond=0)
        for index in range(4):
            ingest.handle_message(
                TOPIC,
                json.dumps(
                    {
                        "device_id": DEVICE_ID,
                        "temperature": 30.0,
                        "timestamp": (base - timedelta(minutes=index)).isoformat(),
                    }
                ),
                session=db,
            )

        entries = db.query(AuditLog).filter(AuditLog.action == "TELEMETRY_RECEIVED").all()
        assert len(entries) == 1


class TestHealth:
    def test_health_says_not_configured_without_a_broker(self):
        settings = build_settings()
        settings.MQTT_BROKER_URL = None
        status = MqttIngestService(settings).health()

        assert status["status"] == "not_configured"
        assert status["enabled"] is False
        assert "iot/telemetry" in status["detail"]

    def test_health_reports_a_configured_but_unconnected_consumer(self, mqtt_settings):
        status = MqttIngestService(mqtt_settings).health()

        assert status["status"] == "stopped"  # never started in the test
        assert status["enabled"] is True
        assert status["broker"].endswith(":1883")

    def test_start_is_a_no_op_when_no_broker_is_configured(self):
        settings = build_settings()
        settings.MQTT_BROKER_URL = None
        service = MqttIngestService(settings)

        assert service.start() is False
        assert service.connected is False
        service.stop()  # safe to call anyway


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def result_device_id(db, device_id: str) -> str:
    from app.models.iot_device import IotDevice

    return str(db.query(IotDevice).filter(IotDevice.device_id == device_id).one().id)


def reading_for(db, device_id: str):
    from app.repositories.sensor_reading_repository import SensorReadingRepository

    return SensorReadingRepository(db).latest_for_device(
        __import__("uuid").UUID(result_device_id(db, device_id))
    )
