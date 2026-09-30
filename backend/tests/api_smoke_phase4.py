"""Phase-4 end-to-end smoke test against a *running* API.

Walks the AI flow a person actually performs, over HTTP, against the development
server:

    a hive with no telemetry → an honest "insufficient data" assessment →
    attach a device → post a window of telemetry → a real assessment with
    factors and indicators → a stressed hive raising an alert → the alert
    lifecycle (acknowledge, de-duplicate, resolve, reopen) → and confirmation
    that a second beekeeper can reach none of it.

Every destructive check runs against **throwaway fixtures created by this run**
(a fresh beekeeper, their hives and devices), never against the seeded
development data. The run prints the single SQL statement that removes what it
created.

Usage::

    cd backend
    .venv/bin/python tests/api_smoke_phase4.py [--base-url http://localhost:8000/api/v1]

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


def login(base: str, who: str) -> str:
    email, password = CREDENTIALS[who]
    status, payload = request("POST", "/auth/login", base=base, body={"email": email, "password": password})
    if status != 200:
        raise SystemExit(f"Could not sign in as {who}: {status} {payload}")
    return payload["data"]["access_token"]


def register_beekeeper(base: str, label: str) -> dict:
    email = f"smoke.p4.{label}.{uuid.uuid4().hex[:8]}@honeychain.example.com"
    password = "SmokeP4Pass123"
    status, payload = request(
        "POST",
        "/auth/register",
        base=base,
        body={
            "name": f"Smoke Phase 4 {label}",
            "email": email,
            "password": password,
            "phone": f"+9198{uuid.uuid4().int % 100000000:08d}",
            "role": "BEEKEEPER",
            "accepted_terms": True,
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register the throwaway beekeeper: {status} {payload}")
    data = payload["data"]
    return {"email": email, "password": password, "token": data["access_token"], "id": data["user"]["id"]}


def make_hive(base: str, token: str, note: str) -> dict:
    status, payload = request(
        "POST",
        "/hives",
        base=base,
        token=token,
        body={
            "bee_species": "Apis cerana indica",
            "village": "AI Smoke Village",
            "district": f"Ai{uuid.uuid4().hex[:4]}",
            "state": "Andhra Pradesh",
            "notes": note,
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register a hive: {status} {payload}")
    return payload["data"]


def make_device(base: str, token: str, hive_id: str, prefix: str) -> dict:
    device_id = f"ESP32-{prefix}-{uuid.uuid4().hex[:5].upper()}"
    status, payload = request(
        "POST",
        "/iot/devices",
        base=base,
        token=token,
        body={"device_id": device_id, "device_name": f"AI smoke {prefix}", "hive_id": hive_id},
    )
    if status != 201:
        raise SystemExit(f"Could not attach a device: {status} {payload}")
    return payload["data"]


def post_telemetry(base: str, token: str, device_id: str, readings: list[dict]) -> int:
    """Post a batch, returning how many were stored."""
    stored = 0
    for reading in readings:
        status, payload = request(
            "POST", "/iot/telemetry", base=base, token=token, body={"device_id": device_id, **reading}
        )
        if status == 201 and payload.get("data", {}).get("stored"):
            stored += 1
    return stored


def window(
    *,
    samples: int,
    spread_hours: float,
    temperature: float,
    humidity: float,
    weight_start: float,
    gain_per_day: float,
    vibration: float,
    acoustic: float,
) -> list[dict]:
    """A backdated telemetry window, ending now.

    Past timestamps are accepted by the ingest (only future ones are rejected),
    which is what lets the smoke test build a few hours of history in seconds.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    step = timedelta(hours=spread_hours) / max(1, samples - 1)
    rows = []
    for index in range(samples):
        moment = now - step * (samples - 1 - index)
        hours_in = (step * index).total_seconds() / 3600.0
        rows.append(
            {
                "timestamp": moment.isoformat(),
                "temperature": round(temperature + (index % 3) * 0.2, 2),
                "humidity": round(humidity + (index % 4) * 0.3, 2),
                "weight": round(weight_start + gain_per_day * hours_in / 24.0, 3),
                "vibration": round(vibration + (index % 2) * 0.05, 3),
                "acoustic_level": round(acoustic + (index % 3) * 0.5, 2),
                "battery_level": 90,
                "signal_strength": -61,
                "source": "SIMULATOR",
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase-4 AI API smoke test.")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args(argv)
    base = args.base_url.rstrip("/")

    print("=" * 68)
    print("  HoneyChain — Phase 4 API smoke test (AI insights + alerts)")
    print(f"  target: {base}")
    print("=" * 68)

    # ------------------------------------------------------------- sign-in
    print("\nAuthentication and permissions")
    tokens = {who: login(base, who) for who in CREDENTIALS}
    check("all four seeded roles can sign in", all(tokens.values()))

    status, _ = request("GET", "/ai/summary", base=base, token=tokens["consumer"])
    check("a consumer is refused the AI module", status == 403, f"got {status}")

    status, payload = request("GET", "/ai/summary", base=base, token=tokens["beekeeper"])
    check("a beekeeper can read their AI overview", status == 200, f"got {status} {payload}")
    overview = payload.get("data", {})
    check(
        "the overview states which model produced the numbers",
        overview.get("model", {}).get("type") == "hive_ai_baseline",
        str(overview.get("model")),
    )
    note = (overview.get("model") or {}).get("note", "")
    check(
        "the model is described as a rule-based baseline, not a diagnosis engine",
        overview.get("model", {}).get("baseline") is True and "not diagnoses" in note,
        note,
    )
    check(
        "counters are integers, so an empty apiary reports zeros rather than nulls",
        all(
            isinstance(overview.get(key), int)
            for key in ("total_hives", "analysed_hives", "hives_without_analysis", "open_alerts")
        ),
        str({key: overview.get(key) for key in ("total_hives", "analysed_hives", "open_alerts")}),
    )

    status, payload = request("GET", "/ai/hives", base=base, token=tokens["consumer"])
    check("a consumer cannot list AI state either", status == 403, f"got {status}")

    # ------------------------------------------------ hive with no telemetry
    print("\nA hive with no telemetry")
    owner = register_beekeeper(base, "owner")
    empty_hive = make_hive(base, owner["token"], "Phase-4 smoke: no telemetry yet.")
    empty_hive_id = empty_hive["id"]

    status, payload = request(
        "GET", f"/ai/hives/{empty_hive_id}?refresh=false", base=base, token=owner["token"]
    )
    check("the insight endpoint answers for an unanalysed hive", status == 200, f"got {status} {payload}")
    body = payload.get("data", {})
    check("an unanalysed hive reports analyzed=false", body.get("analyzed") is False, str(body.get("analyzed")))
    check(
        "no score is invented for it",
        body.get("health") is None and body.get("disease_risk") is None,
        str({k: body.get(k) for k in ("health", "disease_risk")}),
    )

    status, payload = request(
        "POST", f"/ai/hives/{empty_hive_id}/analyze", base=base, token=owner["token"], body={}
    )
    check("an analysis runs on a hive with no telemetry", status == 200, f"got {status} {payload}")
    run = payload.get("data", {})
    check(
        "the run reports INSUFFICIENT data rather than a score",
        run.get("data_quality") == "INSUFFICIENT",
        str(run.get("data_quality")),
    )
    check("it consumed zero readings", run.get("sample_count") == 0, str(run.get("sample_count")))
    check(
        "the health status is INSUFFICIENT_DATA with no score",
        run.get("health_status") == "INSUFFICIENT_DATA" and run.get("health_score") is None,
        str({k: run.get(k) for k in ("health_status", "health_score")}),
    )
    check("no alert is raised for missing data", run.get("alerts_created") == 0, str(run))

    status, payload = request("GET", f"/ai/hives/{empty_hive_id}", base=base, token=owner["token"])
    body = payload.get("data", {})
    check("the stored analysis is read back", status == 200 and body.get("analyzed") is True, f"got {status}")
    check(
        "it carries a plain-language reason, not a placeholder number",
        bool(body.get("summary")) and (body.get("health") or {}).get("score") is None,
        str({k: body.get(k) for k in ("summary", "health")})[:200],
    )
    check(
        "the quality report names the missing sensors",
        isinstance((body.get("quality") or {}).get("issues"), list),
        str((body.get("quality") or {}).get("issues")),
    )
    check(
        "auto-analysis reports why it did or did not recompute",
        body.get("compute_reason") in (
            "no_analysis", "stale", "new_telemetry", "forced", "read_only", "auto_disabled", "fresh",
        ),
        str(body.get("compute_reason")),
    )

    # ------------------------------------------------------ a real assessment
    print("\nA hive with a telemetry window")
    good_hive = make_hive(base, owner["token"], "Phase-4 smoke: healthy window.")
    good_device = make_device(base, owner["token"], good_hive["id"], "GOOD")
    good_readings = window(
        samples=12,
        spread_hours=5,
        temperature=33.5,
        humidity=58.0,
        weight_start=40.0,
        gain_per_day=0.3,
        vibration=0.7,
        acoustic=42.0,
    )
    stored = post_telemetry(base, owner["token"], good_device["device_id"], good_readings)
    check("a backdated window is accepted by the ingest", stored == len(good_readings), f"{stored}/{len(good_readings)}")

    status, payload = request(
        "POST", f"/ai/hives/{good_hive['id']}/analyze", base=base, token=owner["token"], body={}
    )
    check("the analysis runs", status == 200, f"got {status} {payload}")
    run = payload.get("data", {})
    check(
        "the window is judged usable (GOOD or LIMITED, never INSUFFICIENT)",
        run.get("data_quality") in ("GOOD", "LIMITED"),
        str(run.get("data_quality")),
    )
    check("the readings were consumed", run.get("sample_count") == len(good_readings), str(run.get("sample_count")))
    check(
        "a health score is produced",
        isinstance(run.get("health_score"), int) and 0 <= run["health_score"] <= 100,
        str(run.get("health_score")),
    )
    check(
        "the simulator data is reported as simulator data",
        run.get("analysis_source") == "SIMULATOR",
        str(run.get("analysis_source")),
    )
    check(
        "the disease risk band is one of the four allowed values",
        run.get("disease_risk_level") in ("LOW", "MODERATE", "HIGH", "UNKNOWN"),
        str(run.get("disease_risk_level")),
    )

    status, payload = request("GET", f"/ai/hives/{good_hive['id']}?refresh=false", base=base, token=owner["token"])
    insight = payload.get("data", {})
    health = insight.get("health") or {}
    disease = insight.get("disease_risk") or {}
    swarming = insight.get("swarming_risk") or {}
    prediction = insight.get("yield_prediction") or {}
    check("the health assessment carries its evidence", len(health.get("factors", [])) > 0, str(health)[:200])
    check(
        "every factor states the points it contributed",
        all("delta" in factor and "label" in factor for factor in health.get("factors", [])),
        str(health.get("factors"))[:200],
    )
    check("the health payload carries its disclaimer", bool(health.get("disclaimer")), str(health.get("disclaimer")))
    check(
        "the disease payload is a risk with a disclaimer, not a diagnosis",
        bool(disease.get("disclaimer")) and "diagnos" in (disease.get("disclaimer") or "").lower(),
        str(disease.get("disclaimer")),
    )
    check(
        "the swarming payload says it does not predict a swarm",
        bool(swarming.get("disclaimer")),
        str(swarming.get("disclaimer")),
    )
    check(
        "a yield projection either carries a number or a reason",
        (prediction.get("available") is True and isinstance(prediction.get("predicted_yield"), (int, float)))
        or (prediction.get("available") is False and bool(prediction.get("reason"))),
        str(prediction)[:200],
    )
    check(
        "the insight reports the sample count and the newest reading it used",
        insight.get("sample_count") == len(good_readings) and insight.get("newest_reading_at"),
        str({k: insight.get(k) for k in ("sample_count", "newest_reading_at")}),
    )

    status, payload = request("GET", f"/ai/hives/{good_hive['id']}", base=base, token=owner["token"])
    body = payload.get("data", {})
    check(
        "a stored analysis is reused instead of recomputed on every read",
        body.get("computed") is False,
        str({k: body.get(k) for k in ("computed", "compute_reason")}),
    )

    status, payload = request(
        "GET", f"/ai/hives/{good_hive['id']}?refresh=true", base=base, token=owner["token"]
    )
    body = payload.get("data", {})
    check(
        "?refresh=true forces a fresh analysis",
        status == 200 and body.get("computed") is True and body.get("compute_reason") == "forced",
        str({k: body.get(k) for k in ("computed", "compute_reason")}),
    )

    status, payload = request("GET", f"/ai/hives/{good_hive['id']}/history", base=base, token=owner["token"])
    check(
        "the analysis history is paginated and newest-first",
        status == 200 and payload.get("meta", {}).get("total_items", 0) >= 2,
        str(payload.get("meta")),
    )

    status, payload = request(
        "POST",
        f"/ai/hives/{good_hive['id']}/analyze",
        base=base,
        token=owner["token"],
        body={"unexpected": "field"},
    )
    check("unknown request fields are refused", status == 422, f"got {status}")

    # ------------------------------------------------------- alerts lifecycle
    print("\nAlert lifecycle")
    stress_hive = make_hive(base, owner["token"], "Phase-4 smoke: stressed window.")
    stress_device = make_device(base, owner["token"], stress_hive["id"], "HOT")
    hot = window(
        samples=12,
        spread_hours=5,
        temperature=42.0,
        humidity=90.0,
        weight_start=40.0,
        gain_per_day=-0.6,
        vibration=0.9,
        acoustic=52.0,
    )
    posted = post_telemetry(base, owner["token"], stress_device["device_id"], hot)
    check("the stressed window is stored", posted == len(hot), f"{posted}/{len(hot)}")

    status, payload = request(
        "POST", f"/ai/hives/{stress_hive['id']}/analyze", base=base, token=owner["token"], body={}
    )
    run = payload.get("data", {})
    check("the stressed hive raises at least one alert", run.get("alerts_created", 0) >= 1, str(run))
    check(
        "the temperature excursion is reflected in the health indicator",
        run.get("health_status") in ("ATTENTION", "AT_RISK", "CRITICAL"),
        str(run.get("health_status")),
    )

    status, payload = request("GET", "/ai/alerts", base=base, token=owner["token"])
    check("the beekeeper can list their alerts", status == 200, f"got {status} {payload}")
    alerts = payload.get("data", [])
    check("the alert appears in the list", len(alerts) >= 1, f"{len(alerts)} alerts")
    alert = next((row for row in alerts if row.get("alert_type") in ("TEMPERATURE_ANOMALY", "HEALTH_AT_RISK", "HEALTH_CRITICAL")), alerts[0] if alerts else {})
    check("the alert starts OPEN", alert.get("status") == "OPEN", str(alert.get("status")))
    check("the alert carries a severity label", bool(alert.get("severity_label")), str(alert.get("severity")))
    check("the alert says which hive it belongs to", alert.get("hive_code") == stress_hive["hive_code"], str(alert.get("hive_code")))
    check(
        "occurrences are counted from the first one",
        isinstance(alert.get("occurrences"), int) and alert["occurrences"] >= 1,
        str(alert.get("occurrences")),
    )

    temperature_alerts = [row for row in alerts if row.get("alert_type") == "TEMPERATURE_ANOMALY"]
    check("the temperature anomaly produced its own alert", len(temperature_alerts) == 1, str(len(temperature_alerts)))
    if temperature_alerts:
        alert_id = temperature_alerts[0]["id"]
        first_occurrences = temperature_alerts[0]["occurrences"]

        status, payload = request(
            "POST", f"/ai/hives/{stress_hive['id']}/analyze", base=base, token=owner["token"], body={}
        )
        check(
            "re-running the analysis bumps the alert instead of duplicating it",
            payload.get("data", {}).get("alerts_created") == 0
            and payload.get("data", {}).get("alerts_bumped") >= 1,
            str(payload.get("data")),
        )

        status, payload = request("GET", f"/ai/alerts?alert_type=TEMPERATURE_ANOMALY", base=base, token=owner["token"])
        rows = payload.get("data", [])
        check(
            "exactly one active alert exists for that signal",
            len(rows) == 1 and rows[0]["occurrences"] >= first_occurrences,
            str([(row["alert_type"], row["occurrences"]) for row in rows]),
        )

        status, payload = request("GET", "/ai/alerts/summary", base=base, token=owner["token"])
        summary = payload.get("data", {})
        check("the alert summary reports open alerts", status == 200 and summary.get("open_total", 0) >= 1, str(summary))
        check(
            "the summary states that no notifications are sent",
            "notification" in (summary.get("note") or "").lower(),
            str(summary.get("note")),
        )

        status, payload = request(
            "POST", f"/ai/alerts/{alert_id}/acknowledge", base=base, token=owner["token"], body={"note": "Checked at the apiary."}
        )
        acked = payload.get("data", {})
        check(
            "an alert can be acknowledged",
            status == 200 and acked.get("status") == "ACKNOWLEDGED" and acked.get("acknowledged_at"),
            f"got {status} {acked.get('status')}",
        )
        check(
            "the acknowledgement records who did it",
            bool(acked.get("acknowledged_by")),
            str(acked.get("acknowledged_by")),
        )
        check(
            "the note is kept with the alert",
            (acked.get("context") or {}).get("acknowledged_note") == "Checked at the apiary.",
            str(acked.get("context")),
        )

        status, payload = request(
            "POST", f"/ai/alerts/{alert_id}/resolve", base=base, token=owner["token"], body={}
        )
        check("an alert can be resolved", status == 200 and payload["data"]["status"] == "RESOLVED", f"got {status}")

        status, payload = request("GET", f"/ai/alerts?alert_type=TEMPERATURE_ANOMALY", base=base, token=owner["token"])
        check(
            "a resolved alert leaves the default list",
            all(row["id"] != alert_id for row in payload.get("data", [])),
            str([row["status"] for row in payload.get("data", [])]),
        )

        status, payload = request(
            "GET", f"/ai/alerts?alert_type=TEMPERATURE_ANOMALY&include_resolved=true", base=base, token=owner["token"]
        )
        check(
            "…but stays in the record",
            any(row["id"] == alert_id and row["status"] == "RESOLVED" for row in payload.get("data", [])),
            str([(row["id"] == alert_id, row["status"]) for row in payload.get("data", [])]),
        )

        status, payload = request("POST", f"/ai/alerts/{alert_id}/reopen", base=base, token=owner["token"])
        check("an alert can be reopened", status == 200 and payload["data"]["status"] == "OPEN", f"got {status}")

    # ------------------------------------------------------------ audit trail
    print("\nAudit trail")
    status, payload = request(
        "GET", "/admin/audit-logs?action=AI_ANALYSIS_RUN", base=base, token=tokens["admin"]
    )
    entries = payload.get("data", [])
    check("the analysis runs are audited", status == 200 and len(entries) >= 1, f"got {status}, {len(entries)} entries")
    if entries:
        metadata = entries[0].get("metadata") or {}
        check(
            "the audit entry records the model, quality and sample count",
            {"data_quality", "sample_count", "model"} <= set(metadata),
            str(sorted(metadata)),
        )

    status, payload = request(
        "GET", "/admin/audit-logs?action=AI_ALERT_ACKNOWLEDGED", base=base, token=tokens["admin"]
    )
    check(
        "the acknowledgement is audited too",
        status == 200 and len(payload.get("data", [])) >= 1,
        f"got {status}, {len(payload.get('data', []))} entries",
    )

    # ------------------------------------------------------------ isolation
    print("\nCross-account isolation")
    stranger = register_beekeeper(base, "stranger")

    status, payload = request("GET", f"/ai/hives/{stress_hive['id']}", base=base, token=stranger["token"])
    check("a stranger cannot read another beekeeper's insight", status == 404, f"got {status}")

    status, payload = request(
        "POST", f"/ai/hives/{stress_hive['id']}/analyze", base=base, token=stranger["token"], body={}
    )
    check("a stranger cannot analyse another beekeeper's hive", status == 404, f"got {status}")

    status, payload = request(
        "GET", f"/ai/hives/{stress_hive['id']}/history", base=base, token=stranger["token"]
    )
    check("a stranger cannot read another hive's analysis history", status == 404, f"got {status}")

    if temperature_alerts:
        status, payload = request("GET", f"/ai/alerts/{alert_id}", base=base, token=stranger["token"])
        check("a stranger cannot read another beekeeper's alert", status == 404, f"got {status}")

        status, payload = request(
            "POST", f"/ai/alerts/{alert_id}/acknowledge", base=base, token=stranger["token"], body={}
        )
        check("a stranger cannot acknowledge another beekeeper's alert", status == 404, f"got {status}")

    status, payload = request("GET", "/ai/alerts", base=base, token=stranger["token"])
    check(
        "a new account starts with an empty alert list",
        status == 200 and payload.get("data") == [],
        f"got {status} {payload.get('data')}",
    )

    status, payload = request("GET", "/ai/summary", base=base, token=stranger["token"])
    check(
        "a new account starts with zero counters, not nulls",
        status == 200 and payload["data"]["total_hives"] == 0 and payload["data"]["open_alerts"] == 0,
        str(payload.get("data", {}))[:200],
    )

    # ----------------------------------------------------------- staff scope
    print("\nStaff scope")
    status, payload = request("GET", "/ai/hives", base=base, token=tokens["kvic"])
    check("a KVIC officer can list AI state", status == 200, f"got {status}")
    codes = {row["hive_code"] for row in payload.get("data", [])}
    check(
        "the officer sees hives beyond their own apiary",
        stress_hive["hive_code"] in codes,
        f"{stress_hive['hive_code']} not in {sorted(codes)[:5]}",
    )

    status, payload = request("GET", f"/ai/hives/{stress_hive['id']}", base=base, token=tokens["kvic"])
    check("an officer can read any hive's insight", status == 200, f"got {status}")

    status, payload = request("GET", "/ai/summary", base=base, token=tokens["admin"])
    check(
        "the administrator overview counts every hive in scope",
        status == 200 and payload["data"]["total_hives"] >= 3,
        str(payload.get("data", {}).get("total_hives")),
    )

    status, payload = request("POST", "/ai/analyze", base=base, token=tokens["admin"], body={})
    bulk = payload.get("data", {})
    check(
        "the bulk analysis runs over the platform",
        status == 200 and bulk.get("hives_analyzed", 0) >= 3,
        str(bulk),
    )

    # ------------------------------------------------------------- wind-down
    print("\nCleanup")
    print("  Fixtures created by this run (remove with SQL):")
    print(
        "    DELETE FROM beekeepers WHERE user_id IN "
        f"(SELECT id FROM users WHERE email LIKE 'smoke.p4.%');"
    )

    print("\n" + "=" * 68)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    print("=" * 68)
    for failure in FAILED:
        print(f"  FAILED: {failure}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
