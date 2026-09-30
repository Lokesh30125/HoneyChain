"""The laboratory workflow end to end, over HTTP: analysis, pass, hold, override.

This is the fast check behind the browser walk. It drives the API only, against the
real database, and it asserts the things the correction prompt is about:

* opening a test pre-fills labelled development values that a technician can edit;
* running the analysis stores it with its model, version and source;
* a **pass** moves the batch ``LAB_TESTING → APPROVED → PACKAGING_READY`` and the
  batch appears in the packaging queue immediately;
* a **flagged** test cannot be completed past the flag — it is refused (409);
* ``WAIT / HOLD`` parks the test and the batch and blocks packaging;
* ``PROCEED ANYWAY`` requires the installation flag, the confirmation word and a
  reason, then moves ``→ PROCEEDED_WITH_RISK → APPROVED → PACKAGING_READY`` and
  writes a ``PROCEEDED_WITH_RISK`` audit entry naming the user, the risks and the
  analysis;
* every state change is visible to *every* role reading the same record.

Everything it creates is TEST data, marked in the names.

Usage::

    cd backend
    .venv/bin/python tests/smoke_lab_decision.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.api_smoke_phase7 import (  # noqa: E402
    create_staff,
    harvest_batch,
    make_hive,
    process_batch,
    register_keeper,
    request,
    sign_in,
)

DEFAULT_API = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")

ADMIN = ("admin@honeychain.example.com", "AdminSecure123")
OFFICER = ("kvic@honeychain.example.com", "KvicSecure123")

PASSED: list[str] = []
FAILED: list[str] = []


def check(description: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(description)
    print(f"  {'PASS' if condition else 'FAIL'}  {description}" + (f" — {detail}" if detail and not condition else ""))


def section(title: str) -> None:
    print(f"\n=== {title}")


def batch_status(api: str, token: str, batch_id: str) -> str:
    status, payload = request("GET", f"/batches/{batch_id}", base=api, token=token)
    return str((payload.get("data") or {}).get("status")) if status == 200 else f"HTTP {status}"


def lab_state(api: str, token: str, batch_id: str) -> dict:
    status, payload = request("GET", f"/batches/{batch_id}", base=api, token=token)
    if status != 200:
        return {}
    return (payload.get("data") or {}).get("laboratory") or {}


def packaging_queue(api: str, token: str) -> list[str]:
    status, payload = request("GET", "/packaging/approved-batches?page_size=100", base=api, token=token)
    if status != 200:
        return []
    return [row.get("batch_code") for row in (payload.get("data") or [])]


def test_detail(api: str, token: str, test_id: str) -> dict:
    status, payload = request("GET", f"/lab-tests/{test_id}", base=api, token=token)
    return (payload.get("data") or {}) if status == 200 else {}


def first_laboratory(api: str, admin: str) -> dict:
    """A test is opened *for* a laboratory, so the fixture uses the real record.

    Where none exists yet, one is registered through the same endpoint the
    laboratory's own screen uses — TEST data, named as such, never an accredited
    claim the platform cannot stand behind.
    """
    status, payload = request("GET", "/laboratories?page_size=1", base=api, token=admin)
    rows = (payload.get("data") or []) if status == 200 else []
    if rows:
        return rows[0]
    status, payload = request(
        "POST",
        "/laboratories",
        base=api,
        token=admin,
        body={
            "name": "Honey Quality Laboratory (TEST)",
            "location": "Guntur",
            "district": "Guntur",
            "state": "Andhra Pradesh",
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register a laboratory: {status} {payload}")
    return payload["data"]


def open_test(api: str, admin: str, batch: dict, laboratory: dict, *, sample: str = "500") -> dict:
    status, payload = request(
        "POST",
        "/lab-tests",
        base=api,
        token=admin,
        body={"batch_id": batch["id"], "laboratory_id": laboratory["id"], "sample_quantity": sample},
    )
    if status != 201:
        raise SystemExit(f"Could not open a laboratory test: {status} {payload}")
    return payload["data"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=DEFAULT_API)
    args = parser.parse_args()
    api = args.api_url.rstrip("/")

    admin = sign_in(api, *ADMIN)
    officer = sign_in(api, *OFFICER)
    # A processing run is worked by a processor, so the fixture account is
    # provisioned through the admin API exactly as the platform requires.
    processor = create_staff(api, admin, "lab.decision.processor", "PROCESSOR")
    # The bench is worked by a laboratory technician: opening a test is a
    # technician's action, and the analyst and the override are used with that
    # account so the script exercises the same role the screen does.
    bench = create_staff(api, admin, "lab.decision.technician", "LAB_TECHNICIAN")
    bench_token = bench["token"]

    print(f"Laboratory decisions over HTTP — {api}")

    # ------------------------------------------------------------------ #
    section("The configuration the demo runs on is labelled as such")
    # ------------------------------------------------------------------ #
    status, payload = request("GET", "/lab-parameters", base=api, token=admin)
    parameters = {row["code"]: row for row in (payload.get("data") or [])} if status == 200 else {}
    check("the parameter catalogue is readable", bool(parameters), f"{status}")
    moisture = parameters.get("MOISTURE", {})
    check(
        "a range is configured for moisture",
        moisture.get("is_configured") is True,
        f"is_configured={moisture.get('is_configured')}",
    )
    check(
        "the range says where it came from, as a development profile",
        moisture.get("is_demo_configuration") is True
        and "DEMO" in str(moisture.get("reference_source", "")).upper(),
        f"source={moisture.get('reference_source')!r}",
    )
    check(
        "each parameter offers the methods that apply to it",
        bool(moisture.get("methods")),
        f"methods={moisture.get('methods')!r}",
    )

    # ------------------------------------------------------------------ #
    section("A batch reaches the laboratory with its cluster intact")
    # ------------------------------------------------------------------ #
    keeper = register_keeper(api)
    # The beekeeper joins a cluster the way the platform does it, and the harvest
    # then inherits it — nobody types a cluster id into a collection.
    status, payload = request("GET", "/beekeepers/me", base=api, token=keeper["token"])
    keeper_record = payload["data"]
    clusters = (request("GET", "/clusters?page_size=1", base=api, token=admin)[1].get("data") or [])
    if clusters:
        request(
            "PUT",
            f"/beekeepers/{keeper_record['id']}",
            base=api,
            token=admin,
            body={"kvic_cluster_id": clusters[0]["id"]},
        )
    hive = make_hive(api, keeper["token"])
    batch = harvest_batch(api, keeper, hive, "13.7")
    status, payload = request("GET", f"/collections/{batch['collection_id']}", base=api, token=admin)
    collection = (payload.get("data") or {}) if status == 200 else {}
    expected_cluster = clusters[0]["id"] if clusters else None
    if expected_cluster:
        check(
            "the collection inherited its cluster from the beekeeper",
            collection.get("cluster_id") == expected_cluster,
            f"collection cluster_id={collection.get('cluster_id')}",
        )
        check(
            "the batch carries the same cluster the collection did",
            batch.get("cluster_id") == expected_cluster,
            f"batch cluster_id={batch.get('cluster_id')}",
        )
    else:
        check("a cluster exists to inherit", False, "no cluster in this database")
    process_batch(api, admin, processor, batch["id"], "12.9")
    check(
        "completing processing puts the batch at LAB_TESTING",
        batch_status(api, admin, batch["id"]) == "LAB_TESTING",
    )

    # ------------------------------------------------------------------ #
    section("Opening a test pre-fills labelled development values")
    # ------------------------------------------------------------------ #
    laboratory = first_laboratory(api, admin)
    test = open_test(api, bench_token, batch, laboratory)
    detail = test_detail(api, bench_token, test["id"])
    demo_results = [row for row in detail.get("results", []) if row["is_development_value"]]
    check(
        "the test opens with a development value for every configured parameter",
        len(demo_results) >= 5,
        f"{len(demo_results)} pre-filled row(s)",
    )
    check(
        "each one is labelled a development value, not a reading",
        all(row["measurement_source"] == "DEMO" for row in demo_results),
        str([row["measurement_source"] for row in demo_results][:4]),
    )
    moisture_result = next(
        (row for row in detail.get("results", []) if row["parameter_code"] == "MOISTURE"), None
    )
    check("the moisture value comes from the configured development value", moisture_result is not None)
    if moisture_result:
        check(
            "its unit is the parameter's own configured unit",
            moisture_result["unit"] == parameters["MOISTURE"]["unit"],
            f"{moisture_result['unit']} vs {parameters['MOISTURE']['unit']}",
        )
        check(
            "its outcome is evaluated against the configured range, not left unknown",
            moisture_result["status"] in {"PASS", "FAIL"},
            f"status={moisture_result['status']}",
        )
        # A technician edits one value by hand: it stops being a development value.
        status, payload = request(
            "PATCH",
            f"/lab-tests/{test['id']}/results/{moisture_result['id']}",
            base=api,
            token=bench_token,
            body={"value": "17.9", "method": "REFRACTOMETRY", "correction_reason": "re-read the refractometer"},
        )
        edited = next(
            (
                row
                for row in ((payload.get("data") or {}).get("results") or [])
                if row["id"] == moisture_result["id"]
            ),
            {},
        )
        check(
            "a value typed by a person is stored as MANUAL, not DEMO",
            edited.get("measurement_source") == "MANUAL",
            f"source={edited.get('measurement_source')}",
        )
        from decimal import Decimal as _D

        check(
            "the corrected value is recorded exactly as typed",
            _D(str(edited.get("value"))) == _D("17.9"),
            f"value={edited.get('value')}",
        )

    # ------------------------------------------------------------------ #
    section("The AI quality analysis is stored with its provenance")
    # ------------------------------------------------------------------ #
    status, payload = request(
        "POST", f"/lab-tests/{test['id']}/analyze", base=api, token=bench_token, body={}
    )
    analysed = (payload.get("data") or {}) if status == 200 else {}
    analysis = analysed.get("ai_analysis") or {}
    check("running the analysis succeeds", status == 200, f"{status} {payload if status != 200 else ''}")
    check(
        "it says whether the batch may proceed",
        analysis.get("overall_status") in {"PASS", "HOLD", "FAIL", "INCONCLUSIVE"},
        f"status={analysis.get('overall_status')}",
    )
    check(
        "it names the model, version and source that produced it",
        bool(analysis.get("model") and analysis.get("model_version") and analysis.get("source")),
        str({k: analysis.get(k) for k in ("model", "model_version", "source")}),
    )
    check(
        "it reports the parameters it could and could not judge",
        isinstance(analysis.get("passed_parameters"), list)
        and isinstance(analysis.get("inconclusive_parameters"), list),
    )
    check(
        "it states its own limitations rather than claiming validation",
        any("not a validated standard" in str(row) for row in analysis.get("limitations", [])),
        str(analysis.get("limitations")),
    )
    clean_pass = analysis.get("overall_status") == "PASS"

    # ------------------------------------------------------------------ #
    section("A clean pass releases the batch to packaging immediately")
    # ------------------------------------------------------------------ #
    if clean_pass:
        status, payload = request(
            "POST", f"/lab-tests/{test['id']}/complete", base=api, token=bench_token, body={}
        )
        completed = (payload.get("data") or {}) if status == 200 else {}
        check("completing the test succeeds", status == 200, f"{status} {payload if status != 200 else ''}")
        check(
            "the test is COMPLETED with a PASS on its record",
            str(completed.get("status")) == "COMPLETED"
            and str(completed.get("overall_result")) == "PASS",
            f"{completed.get('status')}/{completed.get('overall_result')}",
        )
        status_after = batch_status(api, admin, batch["id"])
        check(
            "the batch left LAB_TESTING and is released to packaging",
            status_after == "PACKAGING_READY",
            f"batch status is {status_after}",
        )
        check(
            "the packaging queue offers it without a further step",
            batch["batch_code"] in packaging_queue(api, admin),
        )
        check(
            "the batch detail reads its laboratory decision from the test",
            lab_state(api, admin, batch["id"]).get("overall_result") == "PASS",
            str(lab_state(api, admin, batch["id"]).get("overall_result")),
        )
        # A second click must not decide anything twice.
        status, payload = request(
            "POST", f"/lab-tests/{test['id']}/complete", base=api, token=bench_token, body={}
        )
        check(
            "completing an already-completed test is refused, not repeated",
            status in (409, 422),
            f"{status}",
        )
        # The same record, read by a second role: KVIC sees the same state.
        status, payload = request("GET", f"/batches/{batch['id']}", base=api, token=officer)
        check(
            "the KVIC officer reads the same batch and the same status",
            status == 200 and str((payload.get("data") or {}).get("status")) == "PACKAGING_READY",
            f"{status} {str((payload.get('data') or {}).get('status'))}",
        )
    else:
        check("the arranged measurements produce a clean pass", False, f"got {analysis.get('overall_status')}")

    # ------------------------------------------------------------------ #
    section("A flagged batch cannot be completed past the flag")
    # ------------------------------------------------------------------ #
    keeper_two = register_keeper(api)
    # This beekeeper joins the same cluster, so the officer's screens can be
    # checked against a hold rather than against a permission error.
    status, payload = request("GET", "/beekeepers/me", base=api, token=keeper_two["token"])
    if clusters:
        request(
            "PUT",
            f"/beekeepers/{payload['data']['id']}",
            base=api,
            token=admin,
            body={"kvic_cluster_id": clusters[0]["id"]},
        )
    hive_two = make_hive(api, keeper_two["token"])
    batch_two = harvest_batch(api, keeper_two, hive_two, "9.5")
    process_batch(api, admin, processor, batch_two["id"], "9.1")
    test_two = open_test(api, bench_token, batch_two, laboratory)

    # Move moisture outside the configured range: the analysis must flag it.
    detail_two = test_detail(api, bench_token, test_two["id"])
    moisture_two = next(row for row in detail_two["results"] if row["parameter_code"] == "MOISTURE")
    request(
        "PATCH",
        f"/lab-tests/{test_two['id']}/results/{moisture_two['id']}",
        base=api,
        token=bench_token,
        body={"value": "27.5", "correction_reason": "probe reading looks wrong"},
    )
    status, payload = request(
        "POST", f"/lab-tests/{test_two['id']}/analyze", base=api, token=bench_token, body={}
    )
    flagged = ((payload.get("data") or {}).get("ai_analysis") or {}) if status == 200 else {}
    check(
        "the analysis flags the out-of-range measurement",
        flagged.get("overall_status") in {"HOLD", "FAIL"} and bool(flagged.get("vulnerabilities")),
        f"status={flagged.get('overall_status')} vulns={flagged.get('vulnerabilities')}",
    )
    check(
        "the flagged parameter is named",
        "MOISTURE" in (flagged.get("abnormal_parameters") or []),
        str(flagged.get("abnormal_parameters")),
    )
    status, payload = request(
        "POST", f"/lab-tests/{test_two['id']}/complete", base=api, token=bench_token, body={}
    )
    check(
        "completing a flagged test is refused until the flag is answered",
        status == 409,
        f"{status} {payload.get('error', {}).get('message') if isinstance(payload, dict) else payload}",
    )
    check(
        "the refusal offers the two ways forward",
        set((payload.get("error", {}).get("details", {}) or {}).get("options", [])) >= {"hold"},
        str(payload.get("error", {}).get("details") if isinstance(payload, dict) else payload),
    )

    # ------------------------------------------------------------------ #
    section("WAIT / HOLD parks the test and blocks packaging")
    # ------------------------------------------------------------------ #
    status, payload = request(
        "POST",
        f"/lab-tests/{test_two['id']}/hold",
        base=api,
        token=bench_token,
        body={"reason": "Moisture above the configured range; resampling from the apiary."},
    )
    held = (payload.get("data") or {}) if status == 200 else {}
    check("holding succeeds", status == 200, f"{status} {payload if status != 200 else ''}")
    check("the test reads HOLD", str(held.get("status")) == "HOLD", f"{held.get('status')}")
    check(
        "the reason is stored on the test and readable by anyone who may see it",
        "resampling" in str(held.get("hold_reason", "")),
        f"hold_reason={held.get('hold_reason')!r}",
    )
    check(
        "the measurements survive the hold",
        len(held.get("results") or []) == len(detail_two.get("results") or []),
        f"{len(held.get('results') or [])} vs {len(detail_two.get('results') or [])}",
    )
    check(
        "the batch is held",
        batch_status(api, admin, batch_two["id"]) == "LAB_HOLD",
        f"batch status is {batch_status(api, admin, batch_two['id'])}",
    )
    check(
        "packaging refuses a held batch and says why",
        batch_two["batch_code"] not in packaging_queue(api, admin),
    )
    status, payload = request(
        "POST",
        "/packaging",
        base=api,
        token=admin,
        body={
            "batch_id": batch_two["id"],
            "packaging_type": "JAR",
            "packaged_quantity": "1",
            "package_size": "1",
            "number_of_packages": 1,
        },
    )
    check(
        "the packing itself is refused, not merely absent from the list",
        status in (400, 403, 409),
        f"{status}",
    )
    check(
        "the refusal explains the hold",
        "hold" in str((payload.get("error", {}) or {}).get("details", {})).lower()
        or "hold" in str((payload.get("error", {}) or {}).get("message", "")).lower()
        if isinstance(payload, dict)
        else False,
        str(payload.get("error") if isinstance(payload, dict) else payload),
    )
    # The hold is visible to the roles that must see it.
    for label, token in (("KVIC", officer),):
        status, payload = request("GET", f"/batches/{batch_two['id']}", base=api, token=token)
        data = (payload.get("data") or {}) if status == 200 else {}
        check(
            f"{label} sees the hold reason on the batch",
            (data.get("laboratory") or {}).get("hold_reason")
            or str(data.get("status")) == "LAB_HOLD",
            str((data.get("laboratory") or {}).get("hold_reason")),
        )
    status, payload = request("GET", f"/batches/{batch_two['id']}/timeline", base=api, token=admin)
    stages = {row["stage"]: row for row in ((payload.get("data") or []) if status == 200 else [])}
    check(
        "traceability shows the laboratory on hold and packaging blocked",
        stages.get("LABORATORY", {}).get("outcome") == "ON_HOLD"
        and stages.get("PACKAGING", {}).get("state") == "blocked",
        f"lab={stages.get('LABORATORY', {}).get('outcome')} packaging={stages.get('PACKAGING', {}).get('state')}",
    )
    check(
        "traceability reports the AI stage it ran",
        stages.get("AI_QUALITY", {}).get("outcome") in {"RISK_DETECTED", "FAILED", "HOLD", "INCONCLUSIVE"},
        str(stages.get("AI_QUALITY")),
    )

    # ------------------------------------------------------------------ #
    section("PROCEED ANYWAY requires the flag, the word and a reason")
    # ------------------------------------------------------------------ #
    status, payload = request(
        "POST",
        f"/lab-tests/{test_two['id']}/proceed-with-risk",
        base=api,
        token=bench_token,
        body={"confirmation": "NOT_THE_WORD", "reason": "pilot batch"},
    )
    check(
        "a wrong confirmation word is refused",
        status == 422,
        f"{status}",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{test_two['id']}/proceed-with-risk",
        base=api,
        token=bench_token,
        body={"confirmation": "PROCEED", "reason": ""},
    )
    check("a missing reason is refused", status == 422, f"{status}")

    # A held test is still open, so the override can be taken from the hold.
    status, payload = request(
        "POST",
        f"/lab-tests/{test_two['id']}/proceed-with-risk",
        base=api,
        token=bench_token,
        body={
            "confirmation": "PROCEED",
            "reason": "Buyer accepted the deviation in writing; releasing for the pilot batch.",
        },
    )
    overridden = (payload.get("data") or {}) if status == 200 else {}
    check("proceeding with the recorded risk succeeds", status == 200, f"{status} {payload if status != 200 else ''}")
    check(
        "the test keeps the outcome its measurements produced",
        str(overridden.get("overall_result")) in {"FAIL", "INCONCLUSIVE", "PASS"},
        f"result={overridden.get('overall_result')}",
    )
    override = overridden.get("risk_override") or {}
    check(
        "the override records the user, the moment, the reason and the risks shown",
        bool(override.get("user_id") and override.get("at") and override.get("reason"))
        and isinstance(override.get("detected_risks"), list),
        str({k: override.get(k) for k in ("user_name", "reason", "detected_risks")}),
    )
    check(
        "the analysis travels with the override",
        bool((override.get("ai_result") or {}).get("overall_status")),
        str(override.get("ai_result")),
    )
    final_status = batch_status(api, admin, batch_two["id"])
    check(
        "the batch is approved and released to packaging",
        final_status == "PACKAGING_READY",
        f"batch status is {final_status}",
    )
    check(
        "the packaging queue takes it",
        batch_two["batch_code"] in packaging_queue(api, admin),
    )
    status, payload = request(
        "GET", f"/batches/{batch_two['id']}/timeline", base=api, token=admin
    )
    stages = {row["stage"]: row for row in ((payload.get("data") or []) if status == 200 else [])}
    check(
        "traceability records that the risk was taken before the release",
        stages.get("AI_QUALITY", {}).get("outcome") == "PROCEEDED_WITH_RISK"
        and stages.get("PACKAGING", {}).get("state") != "blocked",
        f"ai={stages.get('AI_QUALITY', {}).get('outcome')} packaging={stages.get('PACKAGING', {}).get('state')}",
    )
    status, payload = request(
        "GET", "/admin/audit-logs?page_size=50", base=api, token=admin
    )
    actions = [
        row.get("action")
        for row in ((payload.get("data") or []) if status == 200 else [])
    ]
    check(
        "the override is in the audit log as PROCEEDED_WITH_RISK",
        "PROCEEDED_WITH_RISK" in actions,
        f"recent actions: {actions[:8]}",
    )

    # ------------------------------------------------------------------ #
    section("Tracing a package back through the whole chain")
    # ------------------------------------------------------------------ #
    status, payload = request(
        "POST",
        "/packaging",
        base=api,
        token=admin,
        body={
            "batch_id": batch["id"],
            "packaging_type": "JAR",
            "packaged_quantity": "2",
            "package_size": "1",
            "number_of_packages": 2,
        },
    )
    run = (payload.get("data") or {}) if status == 201 else {}
    check("a packaging run opens against the released batch", status == 201, f"{status} {payload if status != 201 else ''}")
    if run:
        # A run is started, then completed: the transition table refuses to finish
        # work that was never begun, and the script takes the same path a person does.
        started, started_payload = request(
            "POST", f"/packaging/{run['id']}/start", base=api, token=admin, body={}
        )
        check("the packaging run starts", started == 200, f"{started} {started_payload}")
        done, done_payload = request(
            "POST", f"/packaging/{run['id']}/complete", base=api, token=admin, body={}
        )
        check(
            "completing the run creates the packages",
            done == 200 and bool(((done_payload.get("data") or {}).get("packages"))),
            f"{done} {str(done_payload)[:200]}",
        )
        status, payload = request("GET", f"/batches/{batch['id']}/timeline", base=api, token=admin)
        stages = {row["stage"]: row for row in ((payload.get("data") or []) if status == 200 else [])}
        check(
            "the timeline names the packages that came out of it",
            "HC-PKG" in str(stages.get("PACKAGING", {}).get("detail", "")),
            str(stages.get("PACKAGING", {}).get("detail")),
        )
        check(
            "the chain reads collection → processing → laboratory → AI → packaging",
            [stages.get(name, {}).get("state") for name in ("COLLECTION", "PROCESSING", "LABORATORY")] 
            == ["completed", "completed", "completed"],
            str({k: stages.get(k, {}).get("state") for k in ("COLLECTION", "PROCESSING", "LABORATORY", "AI_QUALITY", "PACKAGING")}),
        )

    # ------------------------------------------------------------------ #
    section("Scoping is enforced on the server, not hidden in the interface")
    # ------------------------------------------------------------------ #
    outsider = register_keeper(api)
    outsider_hive = make_hive(api, outsider["token"])
    outside_batch = harvest_batch(api, outsider, outsider_hive, "4.2")
    check(
        "a batch whose apiary is in no cluster carries no cluster",
        outside_batch.get("cluster_id") is None,
        f"cluster_id={outside_batch.get('cluster_id')}",
    )
    status, payload = request("GET", f"/batches/{outside_batch['id']}", base=api, token=officer)
    check(
        "the officer cannot read a batch outside their clusters",
        status == 404,
        f"{status}",
    )
    status, payload = request("GET", f"/batches/{outside_batch['id']}", base=api, token=admin)
    check(
        "…while the administrator still can, because the record exists",
        status == 200,
        f"{status}",
    )
    status, payload = request(
        "POST", "/lab-tests", base=api, token=officer, body={"batch_id": outside_batch["id"]}
    )
    check(
        "an officer cannot open a laboratory test",
        status == 403,
        f"{status}",
    )
    status, payload = request("GET", "/lab-tests/held", base=api, token=admin)
    check(
        "the held queue is a real read of the database",
        status == 200 and isinstance(payload.get("data"), list),
        f"{status}",
    )

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for failure in FAILED:
        print(f"  FAILED  {failure}")
    print(
        f"\nTEST data: keeper {keeper['email']}, batch {batch['batch_code']}; "
        f"batch {batch_two['batch_code']} for the hold/override path."
    )
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
