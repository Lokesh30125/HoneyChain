"""Simulate an ESP32 hive node, over MQTT or directly over HTTP.

**Every reading this script sends is stored with ``source = SIMULATOR``.** That
is the whole point of the flag: the dashboard can show simulated data while a
reviewer waits for hardware, and the charts can always say which is which. It
never writes real-device data.

Two transports, one payload contract
------------------------------------
* ``--transport mqtt`` publishes to ``honeychain/devices/{device_id}/telemetry``
  and needs a broker (``MQTT_BROKER_URL``) plus the optional dependency
  ``paho-mqtt``. This is the path real firmware uses.
* ``--transport http`` POSTs the identical JSON to
  ``POST /api/v1/iot/telemetry`` with a beekeeper's access token.

Because both paths land in the same validation pipeline, switching the ESP32
from MQTT to HTTP — or the simulator to real hardware — changes nothing on the
server side.

What it actually does
---------------------
It walks plausible sensor values inside the platform's sanity ranges: the hive
warms through the day, humidity moves inversely, weight creeps up as nectar
comes in, battery drains slowly. Values are *plausible*, not *meaningful*: this
is a wiring test, not a model of a colony.

Usage::

    # MQTT (needs a broker + paho-mqtt installed)
    python -m app.scripts.hive_simulator --device ESP32-GNT-0001 --interval 5

    # HTTP (works against the running API with no broker at all)
    python -m app.scripts.hive_simulator --device ESP32-GNT-0001 \\
        --transport http --email beekeeper@honeychain.example.com \\
        --password HoneyPass123 --interval 5 --count 20
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime, timezone

from app.core.config import build_settings
from app.core.logging import configure_logging

BANNER = "=" * 78
DEFAULT_API_URL = "http://localhost:8000/api/v1"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Simulate an ESP32 hive node. Readings are always labelled SIMULATOR — "
            "never stored as real device data."
        )
    )
    parser.add_argument("--device", required=True, help="Hardware id, e.g. ESP32-GNT-0001.")
    parser.add_argument(
        "--transport",
        choices=("mqtt", "http"),
        default="mqtt",
        help="mqtt publishes to the broker; http posts to the REST ingest endpoint.",
    )
    parser.add_argument("--interval", type=float, default=10.0, help="Seconds between packets.")
    parser.add_argument("--count", type=int, default=0, help="Stop after N packets (0 = forever).")
    parser.add_argument("--url", default=DEFAULT_API_URL, help="API base URL for --transport http.")
    parser.add_argument("--email", help="Beekeeper email (HTTP transport).")
    parser.add_argument("--password", help="Beekeeper password (HTTP transport).")
    parser.add_argument(
        "--sensors",
        default="temperature,humidity,weight,vibration,acoustic,power",
        help="Comma-separated subset to report. 'power' adds battery_level and signal_strength.",
    )
    parser.add_argument("--seed", type=int, default=None, help="Seed the RNG for a repeatable run.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the packets instead of sending them.",
    )
    return parser.parse_args(argv)


class HiveSimulator:
    """Generates one device's readings and walks them over time.

    The state lives here rather than being regenerated from scratch each packet,
    so consecutive readings look like one continuous sensor rather than noise.
    """

    def __init__(self, device_id: str, *, sensors: list[str], seed: int | None = None) -> None:
        self.device_id = device_id
        self.sensors = sensors
        self.random = random.Random(seed)
        self.started = time.time()

        # Starting state: a warm, healthy colony in a Guntur apiary.
        self.temperature = 32.0
        self.humidity = 58.0
        self.weight = 42.5
        self.vibration = 0.25
        self.acoustic = 44.0
        self.battery = 100.0
        self.signal = -61.0

        self.sent = 0

    # -- value drift ------------------------------------------------------ #
    def _step(self, elapsed_seconds: float) -> None:
        """Move each value a little, staying inside physical limits."""
        # A slow daily cycle plus small noise: warm afternoons, cooler nights.
        day_fraction = (self.started + elapsed_seconds) % 86400 / 86400
        target = 30.0 + 6.0 * math.sin(day_fraction * 2 * math.pi)
        self.temperature += (target - self.temperature) * 0.05 + self.random.uniform(-0.3, 0.3)
        self.temperature = min(max(self.temperature, 18.0), 42.0)

        self.humidity += (62.0 - self.humidity) * 0.04 + self.random.uniform(-0.8, 0.8)
        self.humidity = min(max(self.humidity, 35.0), 80.0)

        # Nectar income during the day, a small consumption drift at night.
        inflow = 0.03 if 6 <= (day_fraction * 24) <= 18 else -0.01
        self.weight += inflow + self.random.uniform(-0.02, 0.02)
        self.weight = max(20.0, self.weight)

        self.vibration = abs(self.vibration * 0.7 + self.random.uniform(0.0, 0.6))
        self.vibration = min(self.vibration, 4.0)

        self.acoustic = min(max(self.acoustic + self.random.uniform(-3.0, 3.0), 25.0), 70.0)

        # Battery drains slowly; the "solar" top-up nudges it back by day.
        self.battery -= 0.05
        if 7 <= (day_fraction * 24) <= 17:
            self.battery += 0.04
        self.battery = min(max(self.battery, 0.0), 100.0)

        self.signal = min(max(self.signal + self.random.uniform(-3.0, 3.0), -95.0), -45.0)

    # -- payload ---------------------------------------------------------- #
    def packet(self) -> dict:
        elapsed = time.time() - self.started
        self._step(elapsed)

        payload: dict = {
            "device_id": self.device_id,
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            # The server also decides this for MQTT traffic, but declaring it here
            # makes the intent explicit in the packet too.
            "source": "SIMULATOR",
        }
        if "temperature" in self.sensors:
            payload["temperature"] = round(self.temperature, 2)
        if "humidity" in self.sensors:
            payload["humidity"] = round(self.humidity, 2)
        if "weight" in self.sensors:
            payload["weight"] = round(self.weight, 3)
        if "vibration" in self.sensors:
            payload["vibration"] = round(self.vibration, 3)
        if "acoustic" in self.sensors:
            payload["acoustic_level"] = round(self.acoustic, 2)
        if "power" in self.sensors:
            payload["battery_level"] = int(round(self.battery))
            payload["signal_strength"] = int(round(self.signal))

        self.sent += 1
        return payload


# --------------------------------------------------------------------------- #
# Transports
# --------------------------------------------------------------------------- #
def publish_mqtt(payload: dict, *, settings) -> None:
    """Publish one packet as a real device would."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "paho-mqtt is not installed. Either install it (pip install paho-mqtt) "
            "or use --transport http, which needs no extra dependency."
        ) from exc

    if not settings.mqtt_configured:
        raise SystemExit(
            "MQTT_BROKER_URL is not configured. Set it in the backend .env, or run "
            "the simulator with --transport http."
        )

    from app.services.mqtt_service import telemetry_topic

    topic = telemetry_topic(settings.MQTT_TOPIC_PREFIX, payload["device_id"])

    client = mqtt.Client(client_id=f"honeychain-simulator-{payload['device_id']}")
    if settings.MQTT_USERNAME:
        client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
    client.connect(settings.MQTT_BROKER_URL, settings.MQTT_PORT, keepalive=30)
    client.loop_start()
    info = client.publish(topic, json.dumps(payload), qos=1)
    info.wait_for_publish(timeout=10)
    client.loop_stop()
    client.disconnect()
    print(f"  → mqtt {topic} qos=1")


def build_http_session(url: str, email: str, password: str) -> dict:
    """Sign in and return the headers for subsequent calls.

    Uses the standard library rather than ``requests``: the simulator must run on
    a fresh checkout with nothing installed beyond the backend's own
    requirements, and a JSON POST does not need a third-party HTTP client.
    """
    status, body = http_request(
        "POST", f"{url}/auth/login", payload={"email": email, "password": password}
    )
    if status != 200:
        raise SystemExit(
            f"Sign-in failed ({status}): {json.dumps(body)[:200]}\n"
            "Use a BEEKEEPER account that owns the device."
        )
    data = (body or {}).get("data", {})
    print(f"  signed in as {data.get('user', {}).get('email', email)}")
    return {"Authorization": f"Bearer {data['access_token']}", "Content-Type": "application/json"}


def http_request(method: str, url: str, *, payload: dict | None = None, headers: dict | None = None):
    """One JSON request. Returns ``(status_code, parsed_body)``."""
    import urllib.error
    import urllib.request

    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:200]}
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach the API at {url} ({exc.reason}). Is uvicorn running?"
        ) from exc


def post_http(headers: dict, url: str, payload: dict) -> None:
    status, body = http_request("POST", f"{url}/iot/telemetry", payload=payload, headers=headers)
    if status == 201:
        data = (body or {}).get("data", {})
        marker = "duplicate" if data.get("duplicate") else "stored"
        print(f"  → http 201 [{marker}] hive={data.get('hive_code')} status={data.get('device_status')}")
        return

    detail = (body or {}).get("error", {})
    print(
        f"  ! http {status} {detail.get('code', '')}: "
        f"{detail.get('message', json.dumps(body)[:120])}",
        file=sys.stderr,
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = build_settings()
    configure_logging(settings)

    sensors = [name.strip() for name in args.sensors.split(",") if name.strip()]

    print(BANNER)
    print("  HoneyChain hive simulator — readings are stored as SIMULATOR")
    print(f"  device={args.device}  transport={args.transport}  sensors={','.join(sensors)}")
    print(BANNER)

    if args.transport == "http" and not args.dry_run:
        if not (args.email and args.password):
            print("--transport http needs --email and --password.", file=sys.stderr)
            return 2
        if password_looks_like_a_placeholder(args.password):
            print(
                "Refusing to use a placeholder password. Pass a real development "
                "account password (see the README development section).",
                file=sys.stderr,
            )
            return 2

    headers: dict | None = None
    if args.transport == "http" and not args.dry_run:
        headers = build_http_session(args.url, args.email, args.password)

    simulator = HiveSimulator(args.device, sensors=sensors, seed=args.seed)
    sent = 0

    try:
        while True:
            payload = simulator.packet()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] packet {sent + 1}")
            print(f"  {json.dumps(payload)}")

            if not args.dry_run:
                if args.transport == "mqtt":
                    publish_mqtt(payload, settings=settings)
                else:
                    post_http(headers, args.url, payload)

            sent += 1
            if args.count and sent >= args.count:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")

    print(f"{sent} packet(s) sent, all labelled SIMULATOR.")
    return 0


def password_looks_like_a_placeholder(password: str) -> bool:
    """Catch the obvious placeholders so nobody tests with ``changeme``."""
    return password.strip().lower() in {"password", "changeme", "secret", "your-password", "***"}


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
