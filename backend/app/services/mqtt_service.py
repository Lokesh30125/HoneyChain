"""MQTT ingest — the bridge between ESP32 hardware and the platform.

Topology (documented in ``docs/iot.md`` and mirrored on the device side)::

    honeychain/devices/{device_id}/telemetry   device → platform  (this consumer)
    honeychain/devices/{device_id}/status      device → platform  (online/offline notes)
    honeychain/devices/{device_id}/commands    platform → device  (future)
    honeychain/devices/{device_id}/config      platform → device  (future)

Design notes
------------
* **Nothing here is unique to MQTT.** A message is parsed into the same
  ``TelemetryIngest`` schema the HTTP endpoint uses and handed to
  ``TelemetryService``, so the two ingest paths cannot drift apart and a real
  ESP32 that later switches to HTTP needs no server change.
* **The broker is optional.** With no ``MQTT_BROKER_URL`` configured the service
  reports itself as disabled, ``/health/mqtt`` says so, and the rest of the
  platform behaves normally.
* **A dead broker must not take the API down.** The client reconnects on its own
  background loop with a bounded delay; failures are logged, never raised into
  request handling.
* **Parsing is separable from the network.** ``parse_telemetry_message`` and
  ``handle_message`` take bytes and return a result, which is what the test
  suite exercises without needing a broker at all.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.models.enums import TelemetrySource
from app.schemas.iot import TelemetryIngest
from app.services.device_service import DeviceService
from app.services.telemetry_service import TelemetryService

logger = get_logger("mqtt")

#: How deep a topic has to be for a device id to be extracted:
#: ``{prefix}/devices/{device_id}/telemetry`` (or ``/status``).
_TOPIC_PARTS = ("devices",)


def telemetry_topic(prefix: str, device_id: str) -> str:
    return f"{prefix}/devices/{device_id}/telemetry"


def status_topic(prefix: str, device_id: str) -> str:
    return f"{prefix}/devices/{device_id}/status"


def command_topic(prefix: str, device_id: str) -> str:
    return f"{prefix}/devices/{device_id}/commands"


def config_topic(prefix: str, device_id: str) -> str:
    return f"{prefix}/devices/{device_id}/config"


def parse_telemetry_message(payload: bytes | str) -> TelemetryIngest:
    """Parse and schema-validate a telemetry packet.

    Raises ``PydanticValidationError`` (schema problems) or ``ValueError``
    (not JSON / not an object), so the caller can log an accurate reason. This is
    the single place message shape is enforced — the HTTP route uses the same
    model, which is what keeps the two contracts identical.
    """
    if isinstance(payload, (bytes, bytearray)):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"payload is not valid UTF-8: {exc}") from exc
    else:
        text = payload

    limit = get_settings().TELEMETRY_MAX_PAYLOAD_BYTES
    if len(text.encode("utf-8")) > limit:
        raise ValueError(f"payload exceeds the {limit} byte limit")

    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"payload is not valid JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise ValueError("payload must be a JSON object")

    return TelemetryIngest.model_validate(document)


def extract_device_id(topic: str, *, prefix: str) -> str | None:
    """Pull the device id out of ``{prefix}/devices/{device_id}/…``."""
    parts = [part for part in topic.split("/") if part]
    if len(parts) < 4 or parts[0] != prefix or parts[1] != _TOPIC_PARTS[0]:
        return None
    return parts[2] or None


class MqttIngestService:
    """Subscribe to device telemetry and write it through the normal pipeline."""

    #: Topics subscribed on (re)connect. The wildcard keeps one subscription
    #: valid for every device, including ones registered after startup.
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: Any | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._reconnect_lock = threading.Lock()
        self.stats: dict[str, int] = {
            "messages": 0,
            "stored": 0,
            "duplicates": 0,
            "rejected": 0,
            "parse_errors": 0,
        }
        self.last_message_at: datetime | None = None
        self.last_error: str | None = None
        self.connected_at: datetime | None = None

    # ------------------------------------------------------------------ #
    # Topic helpers
    # ------------------------------------------------------------------ #
    @property
    def telemetry_wildcard(self) -> str:
        return f"{self.settings.MQTT_TOPIC_PREFIX}/devices/+/telemetry"

    @property
    def status_wildcard(self) -> str:
        return f"{self.settings.MQTT_TOPIC_PREFIX}/devices/+/status"

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    @property
    def enabled(self) -> bool:
        return self.settings.mqtt_configured and self.settings.MQTT_CONSUMER_ENABLED

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> bool:
        """Start the consumer in a background thread. Safe to call twice."""
        if not self.enabled:
            logger.info("MQTT consumer disabled (no broker configured)")
            return False
        if self._thread and self._thread.is_alive():
            return True

        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mqtt-consumer", daemon=True)
        self._thread.start()
        logger.info(
            "MQTT consumer starting",
            extra={
                "broker": self.settings.MQTT_BROKER_URL,
                "port": self.settings.MQTT_PORT,
                "topic": self.telemetry_wildcard,
            },
        )
        return True

    def stop(self) -> None:
        self._stop.set()
        client, self._client = self._client, None
        if client is not None:
            try:
                client.disconnect()
                client.loop_stop()
            except Exception:  # noqa: BLE001 - shutdown must never raise
                logger.debug("MQTT disconnect failed during shutdown", exc_info=True)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._connected.clear()
        logger.info("MQTT consumer stopped")

    # ------------------------------------------------------------------ #
    # Connection loop
    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        """Connect, subscribe, and reconnect forever without crashing the API."""
        while not self._stop.is_set():
            try:
                self._connect_once()
                # ``loop_forever`` blocks until the connection drops or stop()
                # disconnects; either way control returns here.
                if self._client is not None and not self._stop.is_set():
                    self._client.loop_forever(retry_first_connection=False)
            except Exception as exc:  # noqa: BLE001 - a broker outage is not fatal
                # Public via /health/mqtt: the type only; the full text is logged.
                self.last_error = type(exc).__name__
                logger.warning(
                    "MQTT connection failed, retrying", extra={"error": str(exc)}
                )
            finally:
                self._connected.clear()
                if self._client is not None:
                    try:
                        self._client.loop_stop()
                    except Exception:  # noqa: BLE001
                        pass

            if self._stop.is_set():
                break
            self._stop.wait(self.settings.MQTT_RECONNECT_SECONDS)

    def _connect_once(self) -> None:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(
            client_id=self.settings.MQTT_CLIENT_ID,
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )
        if self.settings.MQTT_USERNAME:
            client.username_pw_set(self.settings.MQTT_USERNAME, self.settings.MQTT_PASSWORD)
        if self.settings.MQTT_USE_TLS:
            client.tls_set()

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        client.connect(
            self.settings.MQTT_BROKER_URL,
            self.settings.MQTT_PORT,
            keepalive=self.settings.MQTT_KEEPALIVE_SECONDS,
        )
        self._client = client

    # ------------------------------------------------------------------ #
    # Callbacks
    # ------------------------------------------------------------------ #
    def _on_connect(self, client, userdata, flags, rc) -> None:  # noqa: ANN001
        if rc != 0:
            self.last_error = f"connect returned {rc}"
            logger.warning("MQTT connect refused", extra={"rc": rc})
            return
        self._connected.set()
        self.connected_at = datetime.now(timezone.utc)
        # Resubscribe on every (re)connect — brokers do not remember.
        client.subscribe(self.telemetry_wildcard, qos=1)
        client.subscribe(self.status_wildcard, qos=1)
        logger.info("MQTT connected and subscribed", extra={"topic": self.telemetry_wildcard})

    def _on_disconnect(self, client, userdata, rc) -> None:  # noqa: ANN001
        self._connected.clear()
        if not self._stop.is_set():
            logger.warning("MQTT disconnected; will retry", extra={"rc": rc})

    def _on_message(self, client, userdata, message) -> None:  # noqa: ANN001
        """Broker callback. All counting happens inside :meth:`handle_message`."""
        self.last_message_at = datetime.now(timezone.utc)
        self.handle_message(message.topic, message.payload)

    # ------------------------------------------------------------------ #
    # Message handling (broker-independent, unit-testable)
    # ------------------------------------------------------------------ #
    def handle_message(self, topic: str, payload: bytes | str, *, session: Session | None = None) -> dict:
        """Validate and store one message. Never raises for bad input.

        Returns a small result dict describing what happened, which is what the
        consumer counts and the test suite asserts on.
        """
        self.stats["messages"] += 1
        prefix = self.settings.MQTT_TOPIC_PREFIX
        device_id = extract_device_id(topic, prefix=prefix)
        if device_id is None and topic.endswith("/status"):
            device_id = extract_device_id(topic.replace("/status", "/telemetry"), prefix=prefix)
        if device_id is None:
            self.stats["parse_errors"] += 1
            logger.warning("Ignoring message on an unexpected topic", extra={"topic": topic})
            return {"status": "ignored", "reason": "unexpected topic", "topic": topic}

        try:
            parsed = parse_telemetry_message(payload)
        except (ValueError, PydanticValidationError) as exc:
            self.stats["parse_errors"] += 1
            logger.warning(
                "Rejected malformed MQTT payload",
                extra={"topic": topic, "error": str(exc)[:200]},
            )
            return {"status": "rejected", "reason": "malformed payload", "topic": topic}

        # The topic is authoritative for routing; the body must agree, otherwise
        # a device would be able to write into another device's series.
        if parsed.device_id.strip().upper() != device_id.strip().upper():
            self.stats["rejected"] += 1
            logger.warning(
                "Rejected MQTT payload whose device id does not match its topic",
                extra={"topic": topic, "payload_device_id": parsed.device_id},
            )
            return {"status": "rejected", "reason": "device id mismatch", "topic": topic}

        # A device that says it is a simulator is believed; anything else on the
        # wire is real hardware.
        source = parsed.source or TelemetrySource.REAL_DEVICE

        owned_session = session is None
        db = session or SessionLocal()
        try:
            service = TelemetryService(db, self.settings)
            result = service.ingest(parsed, actor=None, source=source, enforce_ownership=False)
            status = "duplicate" if result["duplicate"] else "stored"
            self.stats["duplicates" if result["duplicate"] else "stored"] += 1
            return {"status": status, "device_id": parsed.device_id, "topic": topic}
        except AppError as exc:
            # A domain rejection (unknown device, out-of-range value, bad
            # timestamp) is logged and dropped: MQTT has no response channel.
            self.stats["rejected"] += 1
            logger.warning(
                "Rejected telemetry",
                extra={"topic": topic, "device_id": parsed.device_id, "error": exc.message},
            )
            return {"status": "rejected", "reason": exc.message, "topic": topic}
        except Exception as exc:  # noqa: BLE001 - one bad packet must not kill the loop
            self.stats["rejected"] += 1
            logger.error(
                "Telemetry ingest failed",
                extra={"topic": topic, "device_id": parsed.device_id},
                exc_info=True,
            )
            return {"status": "error", "reason": str(exc), "topic": topic}
        finally:
            if owned_session:
                db.close()

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #
    def health(self) -> dict:
        """Component status for ``/api/v1/health/mqtt``."""
        if not self.settings.mqtt_configured:
            return {
                "status": "not_configured",
                "enabled": False,
                "broker": None,
                "detail": "Set MQTT_BROKER_URL to enable broker ingest. HTTP ingest "
                "at POST /api/v1/iot/telemetry works without a broker.",
            }
        if self._thread is None or not self._thread.is_alive():
            return {
                "status": "stopped",
                "enabled": True,
                "broker": f"{self.settings.MQTT_BROKER_URL}:{self.settings.MQTT_PORT}",
                "detail": "The consumer thread is not running.",
            }
        return {
            "status": "connected" if self.connected else "disconnected",
            "enabled": True,
            "broker": f"{self.settings.MQTT_BROKER_URL}:{self.settings.MQTT_PORT}",
            "topic": self.telemetry_wildcard,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None,
            "last_error": self.last_error,
            "stats": dict(self.stats),
        }


#: Process-wide consumer, started from the FastAPI lifespan and stopped on exit.
_ingest: MqttIngestService | None = None
_ingest_lock = threading.Lock()


def get_ingest_service(settings: Settings | None = None) -> MqttIngestService:
    """Return the process-wide MQTT ingest service (creating it on first use)."""
    global _ingest
    with _ingest_lock:
        if _ingest is None:
            _ingest = MqttIngestService(settings)
        return _ingest


def reset_ingest_service() -> None:
    """Drop the singleton (used by tests and after a configuration change)."""
    global _ingest
    with _ingest_lock:
        if _ingest is not None:
            _ingest.stop()
        _ingest = None


def publish_status(device_id: str, status: str, *, settings: Settings | None = None) -> bool:
    """Best-effort platform → device status note.

    Returns ``False`` when MQTT is not configured or the broker is unreachable;
    callers treat publishing as advisory and never fail a request over it.
    Commands and configuration delivery reuse this same channel in later phases.
    """
    cfg = settings or get_settings()
    if not cfg.mqtt_configured:
        return False
    try:
        import paho.mqtt.publish as publish

        publish.single(
            status_topic(cfg.MQTT_TOPIC_PREFIX, device_id),
            payload=json.dumps({"device_id": device_id, "status": status}),
            qos=1,
            hostname=cfg.MQTT_BROKER_URL,
            port=cfg.MQTT_PORT,
            auth=(
                {"username": cfg.MQTT_USERNAME, "password": cfg.MQTT_PASSWORD}
                if cfg.MQTT_USERNAME
                else None
            ),
        )
        return True
    except Exception as exc:  # noqa: BLE001 - publishing is advisory only
        logger.debug("Status publish failed", extra={"device_id": device_id, "error": str(exc)})
        return False


#: Signature used by tests to inject a fake publisher.
StatusPublisher = Callable[[str, str], bool]

__all__ = [
    "MqttIngestService",
    "get_ingest_service",
    "reset_ingest_service",
    "parse_telemetry_message",
    "extract_device_id",
    "publish_status",
    "telemetry_topic",
    "status_topic",
    "command_topic",
    "config_topic",
    "uuid",
]
