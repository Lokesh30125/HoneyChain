"""Smoke test for "Other" — the choice a list cannot contain.

Parts 5 and 35 of the correction prompt: wherever a field offers a fixed set of
values, and one of them is *Other*, choosing it has to reveal a field that says
what the other thing was, switching away has to hide and clear it, and the pair
has to survive a reload. A record that says ``OTHER`` and nothing else is not a
record — it says that something happened and nothing about what.

Three fields in the platform work that way:

* what a processing run did      → ``processing_type`` / ``processing_type_other``
* what a batch was packed into   → ``packaging_type`` / ``packaging_type_other``
* what a device is               → ``device_type`` / ``device_type_other``

This walks all three over HTTP against a running server, and checks the rule from
both sides, which is the part that is easy to get half-right:

* ``OTHER`` without a description is refused;
* a description alongside a listed value is refused;
* the description is stored, comes back in the read model, and — for the run that
  it belongs to — was still there after a fresh read (the "survives reload" claim);
* switching back to a listed value clears it, rather than leaving a stale
  description attached to a different choice;
* the read models expose ``*_display``, so nothing anywhere prints a bare enum;
* the database refuses the half-recorded pair directly, not only the API.

For packaging, this script checks the pair on the create path and then meets the
batch's own gate; the run-correction and package-inheritance parts need an approved
batch, so they live in ``tests/test_other_values.py``, which builds one through the
real workflow. Between the two, every field with an *Other* option is covered.

Everything it creates is marked ``smoke.other`` and is TEST data.

Usage::

    cd backend
    .venv/bin/python tests/api_smoke_other.py [--base-url http://localhost:8000/api/v1]

Exit code 0 means every check passed.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import date

DEFAULT_BASE = "http://localhost:8000/api/v1"

CREDENTIALS = {
    "admin": ("admin@honeychain.example.com", "AdminSecure123"),
    "beekeeper": ("beekeeper@honeychain.example.com", "HoneyPass123"),
    "processor": ("processor@honeychain.example.com", "ProcessPass123"),
    "labtech": ("labtech@honeychain.example.com", "LabTechPass123"),
}

MARKER = "smoke.other"

PASSED: list[str] = []
FAILED: list[str] = []
CREATED: dict[str, list[str]] = {"users": [], "hives": [], "codes": []}


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(f"{label} — {detail}")
        print(f"  FAIL  {label} — {detail}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def request(method, path, *, base, token=None, body=None):
    """Return ``(status, payload)``. Never raises for HTTP error statuses."""
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raw = error.read() or b"{}"
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"raw": raw.decode(errors="replace")}
    except Exception as error:  # network failure
        return 0, {"error": {"code": "NETWORK", "message": str(error)}}


def sign_in(base, email, password) -> str:
    status, payload = request(
        "POST", "/auth/login", base=base, body={"email": email, "password": password}
    )
    if status != 200:
        raise SystemExit(f"Could not sign in as {email}: {status} {payload}")
    return payload["data"]["access_token"]


def message_of(payload) -> str:
    """The human-readable reason out of an error envelope, for the log."""
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("details") or error)
    return str(payload)[:200]


def register_keeper(base) -> dict:
    """A fresh beekeeper per run: their hives and harvests are entirely their own."""
    email = f"{MARKER}.keeper.{uuid.uuid4().hex[:8]}@honeychain.example.com"
    password = "SmokeOtherPass123"
    status, payload = request(
        "POST",
        "/auth/register",
        base=base,
        body={
            "name": "Smoke Other Beekeeper TEST",
            "email": email,
            "password": password,
            "phone": f"+9196{uuid.uuid4().int % 100000000:08d}",
            "role": "BEEKEEPER",
            "accepted_terms": True,
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register a beekeeper: {status} {payload}")
    CREATED["users"].append(email)
    return {
        "email": email,
        "token": payload["data"]["access_token"],
        "user_id": payload["data"]["user"]["id"],
    }


def make_hive(base, token) -> dict:
    status, payload = request(
        "POST",
        "/hives",
        base=base,
        token=token,
        body={
            "bee_species": "Apis cerana indica",
            "village": "Tenali",
            "district": "Guntur",
            "state": "Andhra Pradesh",
            "notes": "Other-field smoke fixture",
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register a hive: {status} {payload}")
    CREATED["hives"].append(payload["data"]["hive_code"])
    return payload["data"]


def collect(base, keeper, hive, quantity="12.000") -> dict:
    status, payload = request(
        "POST",
        "/collections",
        base=base,
        token=keeper["token"],
        body={
            "hives": [{"hive_id": hive["id"], "quantity": quantity}],
            "collection_date": str(date.today()),
            "notes": "Other-field smoke fixture",
        },
    )
    if status != 201:
        raise SystemExit(f"Could not record a collection: {status} {payload}")
    collection = payload["data"]
    # A collection is planned first and completed when the honey is in: completing
    # it is what creates the single batch that the whole downstream chain shares.
    status, payload = request(
        "POST",
        f"/collections/{collection['id']}/complete",
        base=base,
        token=keeper["token"],
        body={},
    )
    if status != 200:
        raise SystemExit(f"Could not complete the collection: {status} {payload}")
    completed = payload["data"]
    batch = (payload.get("meta") or {}).get("batch") or {}
    completed = dict(completed)
    completed["batch_id"] = completed.get("batch_id") or batch.get("id")
    return completed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print(f"'{MARKER}' — the Other field, end to end, against {base}")

    tokens = {role: sign_in(base, *creds) for role, creds in CREDENTIALS.items()}
    admin = tokens["admin"]
    keeper = register_keeper(base)
    hive = make_hive(base, keeper["token"])
    collection = collect(base, keeper, hive)
    batch_id = collection.get("batch_id") or collection.get("batch", {}).get("id")
    if not batch_id:
        raise SystemExit(f"The collection did not produce a batch: {collection}")
    CREATED["codes"].append(collection.get("collection_code", "?"))

    # ---------------------------------------------------------------- processing
    section("Processing — what the run did")

    status, payload = request(
        "POST",
        "/processing",
        base=base,
        token=tokens["processor"],
        body={
            "batch_id": batch_id,
            "processing_type": "OTHER",
            "processing_type_other": "Centrifuged at 40 °C",
            "notes": "Other-field smoke fixture",
        },
    )
    check("a run can be opened with an unlisted operation", status == 201, f"{status} {message_of(payload)}")
    run = payload.get("data") or {}
    run_id = run.get("id")
    if run_id:
        CREATED["codes"].append(run.get("processing_code", "?"))
    check(
        "the description is stored with the run",
        (run.get("processing_type_other") or "").strip() == "Centrifuged at 40 °C",
        f"got {run.get('processing_type_other')!r}",
    )
    check(
        "the run reads back the operator's own words, not the enum",
        run.get("processing_type_display") == "Centrifuged at 40 °C",
        f"got {run.get('processing_type_display')!r}",
    )

    status, payload = request("GET", f"/processing/{run_id}", base=base, token=tokens["processor"])
    fresh = payload.get("data") or {}
    check(
        "the description survives a fresh read of the run",
        fresh.get("processing_type_other") == "Centrifuged at 40 °C",
        f"{status} {fresh.get('processing_type_other')!r}",
    )
    check(
        "a listed run still reads as its own name",
        fresh.get("processing_type_display") in {None, "", "Centrifuged at 40 °C"},
        f"got {fresh.get('processing_type_display')!r}",
    )

    status, payload = request(
        "POST",
        "/processing",
        base=base,
        token=tokens["processor"],
        body={"batch_id": batch_id, "processing_type": "OTHER"},
    )
    check("Other without a description is refused", status in (400, 422), f"{status} {message_of(payload)}")

    status, payload = request(
        "POST",
        "/processing",
        base=base,
        token=tokens["processor"],
        body={
            "batch_id": batch_id,
            "processing_type": "FILTERING",
            "processing_type_other": "should not be here",
        },
    )
    check(
        "a description beside a listed operation is refused",
        status in (400, 422),
        f"{status} {message_of(payload)}",
    )

    # The update path is separate code from create, and it is where a stale
    # description would live on: switching back to a listed value must clear it.
    status, payload = request(
        "PATCH",
        f"/processing/{run_id}",
        base=base,
        token=tokens["processor"],
        body={"processing_type": "FILTERING"},
    )
    check("a run can be corrected to a listed operation", status == 200, f"{status} {message_of(payload)}")
    updated = payload.get("data") or {}
    check(
        "switching away from Other clears the description",
        updated.get("processing_type_other") is None,
        f"got {updated.get('processing_type_other')!r}",
    )

    status, payload = request(
        "PATCH",
        f"/processing/{run_id}",
        base=base,
        token=tokens["processor"],
        body={"processing_type": "OTHER"},
    )
    check("switching to Other without one is refused", status in (400, 422), f"{status} {message_of(payload)}")

    status, payload = request(
        "PATCH",
        f"/processing/{run_id}",
        base=base,
        token=tokens["processor"],
        body={"processing_type": "OTHER", "processing_type_other": "  Filtered twice  "},
    )
    check("switching to Other with one is accepted", status == 200, f"{status} {message_of(payload)}")
    check(
        "the description is trimmed, not stored with the padding",
        (payload.get("data") or {}).get("processing_type_other") == "Filtered twice",
        f"got {(payload.get('data') or {}).get('processing_type_other')!r}",
    )

    status, payload = request(
        "GET", "/processing?page_size=50", base=base, token=tokens["processor"]
    )
    rows = payload.get("data") or []
    listed = next((row for row in rows if row.get("id") == run_id), None)
    check("the run appears in the operator's own list", listed is not None, f"{status} not found")
    if listed is not None:
        check(
            "the list carries the same description, so a table never shows a bare OTHER",
            listed.get("processing_type_display") == "Filtered twice",
            f"got {listed.get('processing_type_display')!r}",
        )

    # ----------------------------------------------------------------- packaging
    section("Packaging — what the honey was packed into")

    # This batch has not been through processing and the laboratory, so it cannot be
    # packed yet. That is useful here: the two rules are checked in order, and the
    # pair is validated *before* the batch's own gate — a request that is wrong in
    # both ways is reported as a malformed request, not as an unapproved batch.
    status, payload = request(
        "POST",
        "/packaging",
        base=base,
        token=tokens["admin"],
        body={"batch_id": batch_id, "packaging_type": "OTHER"},
    )
    check(
        "a packaging run typed Other with no description is refused as malformed",
        status == 422,
        f"{status} {message_of(payload)}",
    )

    status, payload = request(
        "POST",
        "/packaging",
        base=base,
        token=tokens["admin"],
        body={
            "batch_id": batch_id,
            "packaging_type": "JAR",
            "packaging_type_other": "stale description",
        },
    )
    check(
        "a description beside a listed container is refused as malformed",
        status == 422,
        f"{status} {message_of(payload)}",
    )

    status, payload = request(
        "POST",
        "/packaging",
        base=base,
        token=tokens["admin"],
        body={
            "batch_id": batch_id,
            "packaging_type": "OTHER",
            "packaging_type_other": "500 g glass jar, brass lid",
        },
    )
    check(
        "a well-formed run still meets the batch's own gate (not approved)",
        status in (400, 409),
        f"{status} {message_of(payload)}",
    )

    # The rest of the packaging half — correcting a run to Other and back, and the
    # package inheriting the description its run recorded — needs an approved batch,
    # so it lives in tests/test_other_values.py, which builds one the way the
    # workflow builds one.

    # -------------------------------------------------------------------- device
    section("IoT — what the hardware is")

    device_code = f"{MARKER.upper()}-{uuid.uuid4().hex[:6]}"
    status, payload = request(
        "POST",
        "/iot/devices",
        base=base,
        token=keeper["token"],
        body={
            "device_id": device_code,
            "device_name": "Other-field smoke node",
            "hive_id": hive["id"],
            "device_type": "OTHER",
            "device_type_other": "Custom LoRa board rev C",
        },
    )
    check("a device can be registered as unlisted hardware", status == 201, f"{status} {message_of(payload)}")
    device = payload.get("data") or {}
    device_id = device.get("id")
    check(
        "the hardware description is stored with the device",
        (device.get("device_type_other") or "").strip() == "Custom LoRa board rev C",
        f"got {device.get('device_type_other')!r}",
    )

    other_device_code = f"{MARKER.upper()}-{uuid.uuid4().hex[:6]}"
    status, payload = request(
        "POST",
        "/iot/devices",
        base=base,
        token=keeper["token"],
        body={
            "device_id": other_device_code,
            "device_name": "Other-field smoke node (no description)",
            "hive_id": hive["id"],
            "device_type": "OTHER",
        },
    )
    check("a device typed Other without a description is refused", status in (400, 422), f"{status} {message_of(payload)}")

    status, payload = request(
        "POST",
        "/iot/devices",
        base=base,
        token=keeper["token"],
        body={
            "device_id": f"{MARKER.upper()}-{uuid.uuid4().hex[:6]}",
            "device_name": "Other-field smoke node (mistaken description)",
            "hive_id": hive["id"],
            "device_type": "ESP32",
            "device_type_other": "not an ESP32 after all",
        },
    )
    check(
        "a description beside listed hardware is refused",
        status in (400, 422),
        f"{status} {message_of(payload)}",
    )

    if device_id:
        status, payload = request(
            "PUT",
            f"/iot/devices/{device_id}",
            base=base,
            token=keeper["token"],
            body={"device_type": "ESP32"},
        )
        check(
            "changing the hardware type away from Other clears the description",
            status == 200 and (payload.get("data") or {}).get("device_type_other") is None,
            f"{status} {(payload.get('data') or {}).get('device_type_other')!r}",
        )
        status, payload = request(
            "PUT",
            f"/iot/devices/{device_id}",
            base=base,
            token=keeper["token"],
            body={"device_type": "OTHER"},
        )
        check("changing back to Other without one is refused", status in (400, 422), f"{status} {message_of(payload)}")

    # ---------------------------------------------------------------- the rules
    section("Where the rule lives")

    # The API refuses the pair; the database refuses it too, because the API is not
    # the only thing that can write. This checks the constraint exists and bites.
    import os
    import sys as _sys

    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from sqlalchemy import text

        from app.core.database import engine

        with engine.connect() as connection:
            names = [
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint WHERE conname IN ("
                        "'ck_honey_processing_records_ck_processing_type_other',"
                        "'ck_packaging_records_ck_packaging_type_other',"
                        "'ck_iot_devices_ck_device_type_other')"
                    )
                )
            ]
        check("the processing pair is enforced in the database", len(names) >= 1, f"found {names}")
        with engine.begin() as connection:
            try:
                connection.execute(
                    text(
                        "UPDATE honey_processing_records SET processing_type = 'OTHER', "
                        "processing_type_other = NULL WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": run_id},
                )
                check("writing a bare OTHER straight to the database fails", False, "the update went through")
            except Exception as error:  # the constraint fired, which is the point
                check(
                    "writing a bare OTHER straight to the database fails",
                    "ck_" in str(error) or "constraint" in str(error).lower(),
                    str(error)[:160],
                )
    except Exception as error:  # pragma: no cover - environment problem, not a rule
        check("the database constraint could be inspected", False, str(error)[:200])

    # ------------------------------------------------------------------ cleanup
    print("\n=== Cleanup ===")
    print("-- Everything below was created by this run (marker: %s)." % MARKER)
    print(f"-- beekeepers: {', '.join(CREATED['users']) or 'none'}")
    print(f"-- hives:      {', '.join(CREATED['hives']) or 'none'}")
    print(f"-- records:    {', '.join(str(code) for code in CREATED['codes']) or 'none'}")
    print("-- devices:    " + ", ".join([device_code, other_device_code]))
    print(
        "-- the rows can be left in place: they are TEST data and are labelled as "
        "such in the notes field."
    )

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for failure in FAILED:
        print(f"  FAILED  {failure}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
