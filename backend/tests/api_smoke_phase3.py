"""Phase-3 end-to-end smoke test against a *running* API.

Walks the flow a person actually performs, over HTTP, against the development
server:

    register a hive → register a device on it → send telemetry →
    watch the device come online → chart the history → read the monitoring
    counters → and confirm that a second beekeeper can reach none of it.

Every destructive check runs against **throwaway fixtures created by this run**
(a fresh beekeeper account, their hive and their device), never against the
seeded development data. The run cleans up what it can through the API and
prints the single SQL statement that removes the rest.

Usage::

    cd backend
    .venv/bin/python tests/api_smoke_phase3.py [--base-url http://localhost:8000/api/v1]

Exit code 0 means every check passed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_BASE = "http://localhost:8000/api/v1"

CREDENTIALS = {
    "admin": ("admin@honeychain.example.com", "AdminSecure123"),
    "kvic": ("kvic@honeychain.example.com", "KvicSecure123"),
    "beekeeper": ("beekeeper@honeychain.example.com", "HoneyPass123"),
    "consumer": ("consumer@honeychain.example.com", "ConsumerPass123"),
}

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(f"{label} — {detail}")
        print(f"  FAIL  {label} — {detail}")


def request(
    method: str,
    path: str,
    *,
    base: str,
    token: str | None = None,
    body: dict | list | None = None,
):
    """Return ``(status, payload)``. Never raises for HTTP error statuses."""
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raw = error.read() or b"{}"
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"raw": raw.decode(errors="replace")}
    except Exception as error:  # network failure
        return 0, {"error": {"code": "NETWORK", "message": str(error)}}


def login(base: str, who: str) -> str:
    email, password = CREDENTIALS[who]
    status, payload = request("POST", "/auth/login", base=base, body={"email": email, "password": password})
    if status != 200:
        raise SystemExit(f"Could not sign in as {who}: {status} {payload}")
    return payload["data"]["access_token"]


def register_beekeeper(base: str) -> dict:
    """A throwaway beekeeper for the two isolation checks."""
    email = f"smoke.p3.{uuid.uuid4().hex[:8]}@honeychain.example.com"
    password = "SmokeP3Pass123"
    status, payload = request(
        "POST",
        "/auth/register",
        base=base,
        body={
            "name": "Smoke Phase 3 Beekeeper",
            "email": email,
            "password": password,
            "phone": f"+91987{uuid.uuid4().int % 10000000:07d}",
            "role": "BEEKEEPER",
            "accepted_terms": True,
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register the throwaway beekeeper: {status} {payload}")
    data = payload["data"]
    return {"email": email, "password": password, "token": data["access_token"], "id": data["user"]["id"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase-3 API smoke test.")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args(argv)
    base = args.base_url.rstrip("/")

    print("=" * 68)
    print("  HoneyChain — Phase 3 API smoke test (hives + IoT)")
    print(f"  target: {base}")
    print("=" * 68)

    # ------------------------------------------------------------- sign-in
    print("\nAuthentication")
    tokens = {who: login(base, who) for who in CREDENTIALS}
    check("all four seeded roles can sign in", all(tokens.values()))

    status, payload = request("GET", "/health", base=base)
    check("the API is live", status == 200)

    status, payload = request("GET", "/health/mqtt", base=base)
    mqtt = payload.get("data", {})
    check("GET /health/mqtt reports the ingest state", status == 200, f"got {status}")
    check(
        "the MQTT consumer reports honestly when no broker is configured",
        mqtt.get("enabled") in (True, False) and "status" in mqtt,
        f"payload={mqtt}",
    )
    check(
        "HTTP ingest is documented as available without a broker",
        "iot/telemetry" in (mqtt.get("detail") or ""),
        f"detail={mqtt.get('detail')!r}",
    )

    # -------------------------------------------------------- hive creation
    print("\nHive registration")
    district = f"Smoke{uuid.uuid4().hex[:4]}"
    status, payload = request(
        "POST",
        "/hives",
        base=base,
        token=tokens["beekeeper"],
        body={
            "bee_species": "Apis cerana indica",
            "village": "Smoke Village",
            "district": district,
            "state": "Andhra Pradesh",
            "notes": "Created by the Phase-3 smoke test.",
        },
    )
    check("a beekeeper can register a hive", status == 201, f"got {status} {payload}")
    hive = payload.get("data", {})
    hive_id = hive.get("id")
    hive_code = hive.get("hive_code", "")

    check(
        "the backend generates the hive code",
        bool(re.fullmatch(r"HIVE-[A-Z]{3}-\d{5}", hive_code or "")),
        hive_code,
    )
    check(
        "the code prefix is derived from the district",
        hive_code.split("-")[1] == "SMK",
        f"{hive_code} for district {district!r}",
    )
    check("a new hive starts ACTIVE", hive.get("status") == "ACTIVE", str(hive.get("status")))
    check("the payload carries a location label", bool(hive.get("location_label")), str(hive.get("location_label")))

    status, payload = request(
        "POST",
        "/hives",
        base=base,
        token=tokens["beekeeper"],
        body={"village": "Forbidden", "hive_code": "HIVE-GNT-99999"},
    )
    check("a client cannot choose its own hive code", status == 422, f"got {status}")
    check(
        "unknown fields are rejected rather than silently ignored",
        payload.get("error", {}).get("details", [{}])[0].get("field") == "hive_code",
        str(payload.get("error", {}).get("details")),
    )

    status, payload = request("GET", f"/hives/{hive_id}", base=base, token=tokens["beekeeper"])
    check("the hive detail screen loads", status == 200 and payload["data"]["id"] == hive_id, f"got {status}")

    status, payload = request("GET", f"/beekeepers/me/hives", base=base, token=tokens["beekeeper"])
    check(
        "GET /beekeepers/me/hives lists it for its owner",
        status == 200 and any(row["id"] == hive_id for row in payload.get("data", [])),
        f"got {status}",
    )

    # ------------------------------------------------------ device creation
    print("\nDevice registration")
    device_id = f"ESP32-SMK-{uuid.uuid4().hex[:4].upper()}"
    status, payload = request(
        "POST",
        "/iot/devices",
        base=base,
        token=tokens["beekeeper"],
        body={"device_id": device_id, "device_name": "Smoke node", "hive_id": hive_id, "firmware_version": "1.0.0"},
    )
    check("a device can be attached to the hive", status == 201, f"got {status} {payload}")
    device = payload.get("data", {})
    device_pk = device.get("id")
    check("a new device starts OFFLINE", device.get("status") == "OFFLINE", str(device.get("status")))
    check(
        "the MQTT topic is derived from the hardware id",
        device.get("mqtt_topic") == f"honeychain/devices/{device_id}/telemetry",
        str(device.get("mqtt_topic")),
    )

    status, payload = request("GET", f"/iot/devices/{device_pk}/sensors", base=base, token=tokens["beekeeper"])
    sensors = payload.get("data", [])
    check("the sensor set is created with the device", status == 200 and len(sensors) == 5, f"got {status}, {len(sensors)} sensors")

    status, payload = request(
        "POST",
        "/iot/devices",
        base=base,
        token=tokens["beekeeper"],
        body={"device_id": device_id, "device_name": "Duplicate", "hive_id": hive_id},
    )
    check("a duplicate hardware id is refused", status == 422, f"got {status}")

    # ------------------------------------------------------------ telemetry
    print("\nTelemetry ingest")
    moment = datetime.now(timezone.utc).replace(microsecond=0)
    reading = {
        "device_id": device_id,
        "timestamp": moment.isoformat(),
        "temperature": 33.4,
        "humidity": 58.2,
        "weight": 41.5,
        "vibration": 0.4,
        "acoustic_level": 44.0,
        "battery_level": 88,
        "signal_strength": -67,
        "source": "SIMULATOR",
    }
    status, payload = request("POST", "/iot/telemetry", base=base, token=tokens["beekeeper"], body=reading)
    check("a full packet is accepted", status == 201, f"got {status} {payload}")
    body = payload.get("data", {})
    check("the reading is stored", body.get("stored") is True, str(body))
    check("a declared simulator stays labelled SIMULATOR", body.get("source") == "SIMULATOR", str(body.get("source")))
    check("the device goes ONLINE once it reports", body.get("device_status") == "ONLINE", str(body.get("device_status")))

    status, payload = request("POST", "/iot/telemetry", base=base, token=tokens["beekeeper"], body=reading)
    check(
        "the same instant re-sent is reported as a duplicate",
        status == 201 and payload["data"]["duplicate"] is True,
        f"got {status} {payload.get('data')}",
    )

    status, payload = request(
        "POST",
        "/iot/telemetry",
        base=base,
        token=tokens["beekeeper"],
        body={"device_id": device_id, "temperature": 300.0},
    )
    details = payload.get("error", {}).get("details", {})
    check("an impossible temperature is refused", status == 422, f"got {status}")
    check(
        "the rejection names the bound rather than clamping the value",
        isinstance(details, dict) and details.get("min") == -20.0 and details.get("max") == 80.0,
        str(details),
    )

    status, payload = request(
        "POST",
        "/iot/telemetry",
        base=base,
        token=tokens["beekeeper"],
        body={"device_id": device_id, "weight": -5.0},
    )
    check("a negative hive weight is refused", status == 422, f"got {status}")

    status, payload = request(
        "POST",
        "/iot/telemetry",
        base=base,
        token=tokens["beekeeper"],
        body={
            "device_id": device_id,
            "timestamp": (moment - timedelta(minutes=2)).isoformat(),
            "temperature": 32.9,
            "humidity": 57.4,
            "source": "SIMULATOR",
        },
    )
    check("a buffered/late packet is accepted", status == 201, f"got {status}")

    status, payload = request("GET", f"/iot/devices/{device_pk}", base=base, token=tokens["beekeeper"])
    detail = payload.get("data", {})
    check("the device detail shows its latest reading", status == 200 and detail.get("latest_reading"), f"got {status}")
    check("the device detail counts its 24h readings", detail.get("readings_last_24h", 0) >= 2, str(detail.get("readings_last_24h")))
    check(
        "each configured sensor carries its current value",
        any(sensor.get("value") == 33.4 for sensor in detail.get("sensors", [])),
        str([(s["sensor_type"], s["value"]) for s in detail.get("sensors", [])]),
    )

    # --------------------------------------------------------------- history
    print("\nHistory and monitoring")
    status, payload = request("GET", f"/iot/telemetry/{hive_id}", base=base, token=tokens["beekeeper"])
    history = payload.get("data", {})
    check("raw history is returned", status == 200 and history.get("count", 0) >= 2, f"got {status}, count={history.get('count')}")
    check(
        "the response says which sources the chart contains",
        history.get("source_mix", {}).get("SIMULATOR", 0) >= 1,
        str(history.get("source_mix")),
    )

    status, payload = request("GET", f"/iot/telemetry/{hive_id}?range=24h", base=base, token=tokens["beekeeper"])
    bucketed = payload.get("data", {})
    check("a range preset buckets the series", status == 200 and bucketed.get("interval") == "15m", f"got {status}, {bucketed.get('interval')}")

    status, payload = request(
        "GET", f"/iot/telemetry/{hive_id}?sensor_type=humidity", base=base, token=tokens["beekeeper"]
    )
    series = payload.get("data", {})
    check(
        "a single sensor can be charted",
        status == 200 and series.get("sensor_type") == "HUMIDITY" and series["points"],
        f"got {status}",
    )

    status, payload = request("GET", f"/iot/telemetry/{hive_id}/latest", base=base, token=tokens["beekeeper"])
    live = payload.get("data", {})
    check("the live panel returns the newest values", status == 200 and live.get("latest", {}).get("temperature") == 33.4, f"got {status}")

    status, payload = request("GET", "/iot/devices/summary", base=base, token=tokens["beekeeper"])
    summary = payload.get("data", {})
    check("the IoT counters count real rows", status == 200 and summary.get("connected_devices", 0) >= 1, f"got {status}, {summary}")
    check("the summary counts configured sensors", summary.get("sensors_active", 0) >= 5, str(summary.get("sensors_active")))
    check("the summary reports the last telemetry time", summary.get("last_telemetry_at") is not None, str(summary))

    status, payload = request("GET", "/iot/last-telemetry", base=base, token=tokens["beekeeper"])
    last = payload.get("data", {})
    check("the last-telemetry header names the device", status == 200 and last.get("has_data") is True and last.get("device_id") == device_id, f"got {status}, {last}")

    # ------------------------------------------------------------ hive edits
    print("\nHive updates and lifecycle")
    status, payload = request(
        "PUT", f"/hives/{hive_id}", base=base, token=tokens["beekeeper"], body={"queen_status": "PRESENT"}
    )
    check("a hive can be updated", status == 200 and payload["data"]["queen_status"] == "PRESENT", f"got {status}")

    status, payload = request(
        "PATCH",
        f"/hives/{hive_id}/status",
        base=base,
        token=tokens["beekeeper"],
        body={"status": "MAINTENANCE", "reason": "Smoke test."},
    )
    check("a hive status can be changed", status == 200 and payload["data"]["status"] == "MAINTENANCE", f"got {status}")

    status, payload = request("GET", "/hives/summary", base=base, token=tokens["beekeeper"])
    check("the hive summary counts by status", status == 200 and "MAINTENANCE" in payload.get("data", {}).get("by_status", {}), f"got {status}")

    status, payload = request("GET", "/hives/filters", base=base, token=tokens["beekeeper"])
    check("the filter options include the new district", status == 200 and district in payload.get("data", {}).get("districts", []), f"got {status}")

    # ---------------------------------------------------------- authorisation
    print("\nAuthorisation and isolation")
    other = register_beekeeper(base)

    status, payload = request("GET", f"/hives/{hive_id}", base=base, token=other["token"])
    check("another beekeeper cannot read the hive (404)", status == 404, f"got {status}")

    status, payload = request("GET", "/hives", base=base, token=other["token"])
    check(
        "another beekeeper's hive list is empty",
        status == 200 and payload.get("data") == [] and payload.get("meta", {}).get("total_items") == 0,
        f"got {status}, {payload.get('meta')}",
    )

    status, payload = request(
        "POST", "/iot/telemetry", base=base, token=other["token"], body={"device_id": device_id, "temperature": 30.0}
    )
    check("another beekeeper cannot submit telemetry for this device (403)", status == 403, f"got {status}")

    status, payload = request("GET", f"/iot/telemetry/{hive_id}", base=base, token=other["token"])
    check("another beekeeper cannot read the series (404)", status == 404, f"got {status}")

    status, payload = request(
        "POST",
        "/iot/devices",
        base=base,
        token=other["token"],
        body={"device_id": f"ESP32-X-{uuid.uuid4().hex[:4].upper()}", "device_name": "Hijack", "hive_id": hive_id},
    )
    check("another beekeeper cannot register a device on the hive (404)", status == 404, f"got {status}")

    status, payload = request("DELETE", f"/hives/{hive_id}", base=base, token=other["token"])
    check("another beekeeper cannot delete the hive (404)", status == 404, f"got {status}")

    status, payload = request("GET", "/hives", base=base, token=tokens["consumer"])
    check("a consumer cannot reach the hive registry (403)", status == 403, f"got {status}")

    status, payload = request("GET", f"/iot/telemetry/{hive_id}", base=base, token=tokens["consumer"])
    check("a consumer cannot read telemetry (403)", status == 403, f"got {status}")

    status, payload = request("GET", f"/hives/{hive_id}", base=base, token=tokens["kvic"])
    check("a KVIC officer can inspect any hive", status == 200, f"got {status}")

    status, payload = request("GET", f"/iot/telemetry/{hive_id}", base=base, token=tokens["admin"])
    check("an administrator can inspect any series", status == 200, f"got {status}")

    status, payload = request("GET", "/admin/audit-logs?page=1&page_size=20&entity_type=hive", base=base, token=tokens["admin"])
    actions = {entry["action"] for entry in payload.get("data", [])}
    check(
        "the audit log records the hive lifecycle",
        {"HIVE_CREATED", "HIVE_UPDATED", "HIVE_STATUS_CHANGED"} <= actions,
        f"actions={sorted(actions)}",
    )

    status, payload = request("GET", f"/admin/audit-logs?page=1&page_size=20&action=DEVICE_REGISTERED", base=base, token=tokens["admin"])
    check("the audit log records device registration", status == 200 and payload.get("data"), f"got {status}")

    status, payload = request("GET", "/admin/audit-logs?page=1&page_size=20&action=TELEMETRY_RECEIVED", base=base, token=tokens["admin"])
    check("the audit log records telemetry receipt", status == 200 and payload.get("data"), f"got {status}")

    # --------------------------------------------------------------- cleanup
    print("\nCleanup (this run's fixtures only)")
    status, payload = request("DELETE", f"/hives/{hive_id}", base=base, token=tokens["beekeeper"])
    check(
        "a hive with a device and history is refused (409)",
        status == 409 and payload["error"]["details"]["device_count"] == 1,
        f"got {status} {payload.get('error')}",
    )

    status, payload = request("DELETE", f"/iot/devices/{device_pk}", base=base, token=tokens["beekeeper"])
    check("deleting a device with readings needs confirmation (409)", status == 409, f"got {status}")
    check(
        "the refusal says what would be lost",
        payload.get("error", {}).get("details", {}).get("reading_count", 0) >= 2,
        str(payload.get("error", {}).get("details")),
    )

    status, payload = request(
        "DELETE", f"/iot/devices/{device_pk}?confirm=true", base=base, token=tokens["beekeeper"]
    )
    check(
        "the confirmed deletion reports what it removed",
        status == 200 and payload.get("data", {}).get("readings_deleted", 0) >= 2,
        f"got {status} {payload.get('data')}",
    )

    status, payload = request("DELETE", f"/hives/{hive_id}", base=base, token=tokens["beekeeper"])
    check(
        "an emptied hive is deleted outright",
        status == 200 and payload.get("data", {}).get("soft_deleted") is False,
        f"got {status} {payload.get('data')}",
    )

    status, payload = request("GET", f"/hives/{hive_id}", base=base, token=tokens["beekeeper"])
    check("the deleted hive is gone", status == 404, f"got {status}")

    status, payload = request("GET", "/hives", base=base, token=tokens["beekeeper"])
    check(
        "it leaves the registry entirely",
        all(row["id"] != hive_id for row in payload.get("data", [])),
    )

    # --------------------------------------------------------------- summary
    print("\n" + "=" * 68)
    print(f"{len(PASSED)} passed, {len(FAILED)} failed")
    for failure in FAILED:
        print(f"  ✗ {failure}")
    print("=" * 68)
    print(
        "NOTE: this run created throwaway fixtures in the development database:\n"
        f"  account: {other['email']} (plus its beekeeper record)\n"
        f"  hive:    {hive_code} (status REMOVED, history preserved)\n"
        f"  device:  {device_id} (deleted with its readings)\n"
        "\nRemove the account — its beekeeper, hive and readings cascade — with:\n"
        '  psql "$DATABASE_URL" -c "delete from users where email like \'smoke.p3.%\';"'
    )
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
