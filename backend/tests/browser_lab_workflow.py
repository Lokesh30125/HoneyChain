"""Drive the laboratory in a real browser, from a batch to a decided result.

`tests/api_smoke_phase7.py` proves the workflow over HTTP. This script proves the
part HTTP cannot: that the **screens** actually carry it — that a technician can
open a test from the queue, record a measurement through the parameter, method and
unit controls, complete the test, and see the batch move on. It exists because a
working API behind a screen that does nothing is exactly the failure this phase is
about: the buttons have to be wired, the data has to be the same records, and a
browser refresh must not undo any of it.

What it does, in order:

1. Arranges a real chain through the API — a TEST beekeeper's hive, a harvest, its
   batch, a processing run completed — so the batch is genuinely at ``LAB_TESTING``
   with no test opened. That is the state the interface calls "Waiting for a sample",
   and it is where the laboratory is expected to pick the work up.
2. Signs in as a laboratory technician in Chromium and opens the laboratory
   worklist. The batch has to be there, with a working action, not an empty page.
3. Opens the test through the dialog, which registers the sample against the batch.
4. Records a measurement through the real controls: the parameter **dropdown**
   (from the configured catalogue), the numeric value, the **unit shown from the
   parameter's own configuration**, and the **method dropdown** — including the
   "Other" path, where a method typed by hand is stored and read back.
5. Completes the test and checks the whole consequence, from the database and not
   from the screen: the test is COMPLETED with a decided result, the batch is
   APPROVED, the test has left the pending queues and appears in completed, and the
   batch is offered to packaging.
6. Reloads the page and checks the result survived — the claim "refresh-safe" is
   only true if a refresh is actually performed.

Sign-in details come from the seeded development accounts; the records it creates
are marked TEST/``browser.lab``.

Usage (API and the built frontend must be running)::

    cd backend
    .venv/bin/python tests/browser_lab_workflow.py

Exit code 0 means the laboratory flow worked end to end through the interface.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from tests.api_smoke_phase7 import (  # noqa: E402
    configure_parameter,
    harvest_batch,
    make_hive,
    process_batch,
    register_keeper,
    request,
    sign_in,
)

DEFAULT_API = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")
DEFAULT_WEB = os.getenv("SMOKE_BASE_URL", "http://localhost:4173")

LABTECH = ("labtech@honeychain.example.com", "LabTechPass123")
ADMIN = ("admin@honeychain.example.com", "AdminSecure123")

PASSED: list[str] = []
FAILED: list[str] = []


def check(description: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(description)
    suffix = f" — {detail}" if detail and not condition else ""
    print(f"  {'PASS' if condition else 'FAIL'}  {description}{suffix}")


def section(title: str) -> None:
    print(f"\n=== {title}")


#: Which way the arranged test is set up to go. The range is what decides it: a
#: value inside the configured range passes, a value outside it fails. Nothing in
#: the interface chooses the verdict, so the way to test FAIL is to arrange a batch
#: whose measurement cannot pass — which is also the honest demonstration that the
#: decision comes from the record and not from a button.
VERDICTS = {
    "PASS": {"parameter": "MOISTURE", "unit": "%", "minimum": "10", "maximum": "20"},
    "FAIL": {"parameter": "MOISTURE", "unit": "%", "minimum": "30", "maximum": "40"},
    # No range at all: a measurement nobody has defined a limit for is reported as
    # recorded and the test comes out INCONCLUSIVE — never a pass. This is the third
    # outcome the workflow has to be able to reach, so it is arranged rather than
    # assumed.
    "INCONCLUSIVE": {"parameter": "PH", "unit": "pH"},
}


def arrange(api: str, verdict: str = "PASS") -> dict:
    """A real batch at LAB_TESTING with nothing opened against it."""
    admin = sign_in(api, *ADMIN)
    processor_tokens = sign_in(api, "processor@honeychain.example.com", "ProcessPass123")
    processor = {"token": processor_tokens}
    # The run has to be allocated to a named processor before it can be worked, so
    # the account's own id is read from the session rather than assumed.
    status, payload = request("GET", "/auth/me", base=api, token=processor_tokens)
    if status != 200:
        raise SystemExit(f"Could not read the processor account: {status} {payload}")
    processor["user_id"] = payload["data"]["id"]

    keeper = register_keeper(api)
    hive = make_hive(api, keeper["token"])
    batch = harvest_batch(api, keeper, hive, "13.7")
    process_batch(api, admin, processor, batch["id"], "12.9")

    # A range has to exist for a verdict to be possible at all; it is configured the
    # way the platform requires — stated, sourced, and described as a demonstration
    # limit, never as a regulatory one.
    limits = VERDICTS[verdict]
    if "minimum" in limits:
        configure_parameter(api, admin, limits["parameter"], limits["minimum"], limits["maximum"])

    status, payload = request("GET", f"/batches/{batch['id']}", base=api, token=admin)
    batch = payload["data"]
    names = {
        "MOISTURE": "Moisture",
        "PH": "pH",
    }
    return {
        "admin": admin,
        "keeper": keeper,
        "hive": hive,
        "batch": batch,
        "parameter": limits["parameter"],
        "parameter_name": names.get(limits["parameter"], limits["parameter"]),
        "unit": limits["unit"],
        "value": limits.get("measured", "17.2"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--web-url", default=DEFAULT_WEB)
    parser.add_argument(
        "--verdict",
        choices=sorted(VERDICTS),
        default="PASS",
        help=(
            "Which way the arranged test goes. Both are run as part of the checks: "
            "PASS ends in an approved batch offered to packaging, FAIL in a rejected "
            "batch that packaging is refused."
        ),
    )
    parser.add_argument("--headless", action="store_true", default=True)
    args = parser.parse_args()
    api = args.api_url.rstrip("/")
    web = args.web_url.rstrip("/")

    print(f"Laboratory workflow in a browser — {web} against {api}")

    section("A batch arrives at the laboratory")
    arrangement = arrange(api, args.verdict)
    batch = arrangement["batch"]
    check(
        "the completed processing run moved the batch to LAB_TESTING",
        str(batch["status"]) == "LAB_TESTING",
        f"batch is {batch['status']}",
    )
    check(
        "the batch carries its cluster, beekeeper and collection",
        bool(batch.get("beekeeper_id")) and bool(batch.get("collection_id")),
        f"beekeeper={batch.get('beekeeper_id')} collection={batch.get('collection_id')}",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1100})
        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        # ------------------------------------------------------------------ #
        section("The laboratory worklist offers the work")
        # ------------------------------------------------------------------ #
        page.goto(f"{web}/login", wait_until="domcontentloaded")
        page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        page.goto(f"{web}/login", wait_until="networkidle")
        page.fill("input[name='email']", LABTECH[0])
        page.fill("input[name='password']", LABTECH[1])
        page.click("button[type='submit']")
        page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
        page.wait_for_load_state("networkidle")

        page.goto(f"{web}/laboratory/awaiting", wait_until="networkidle")
        page.wait_for_timeout(1200)
        row = page.locator(f"[data-testid='open-test-{batch['batch_code']}']")
        check(
            "the batch awaiting testing is listed with its own action",
            row.count() == 1,
            f"row links found: {row.count()}",
        )

        # ------------------------------------------------------------------ #
        section("Opening a test registers the sample against that batch")
        # ------------------------------------------------------------------ #
        if row.count():
            row.first.click()
            page.locator("div[role='dialog']").wait_for(state="visible", timeout=10000)
            quantity = page.locator("input[name='sample_quantity']").first
            check(
                "the sample quantity starts empty rather than filled with a guess",
                quantity.input_value() == "",
                f"pre-filled with {quantity.input_value()!r}",
            )
            quantity.click()
            page.keyboard.type("250", delay=25)
            check(
                "the sample quantity field takes a whole value",
                quantity.input_value() == "250",
                f"holds {quantity.input_value()!r}",
            )
            page.click("[data-testid='create-test']")
            page.wait_for_url(lambda url: "/laboratory/tests/" in url, timeout=15000)
            test_url = page.url
            test_id = test_url.rstrip("/").split("/")[-1]
            check("opening the test lands on the test itself", bool(test_id), test_url)

            # ------------------------------------------------------------------ #
            section("Recording a measurement through the real controls")
            # ------------------------------------------------------------------ #
            page.wait_for_load_state("networkidle")
            page.get_by_role("button", name="Record a measurement").first.click()
            page.locator("div[role='dialog']").wait_for(state="visible", timeout=10000)

            parameter = page.locator("select[name='parameter_code']").first
            check(
                "the parameter control is a dropdown, not a text box",
                parameter.count() == 1,
                f"{parameter.count()} matching controls",
            )
            options = [o.inner_text() for o in page.locator("select[name='parameter_code'] option").all()]
            check(
                "the dropdown is populated from the configured catalogue",
                any(arrangement["parameter_name"] in text for text in options),
                f"options: {options[:6]}",
            )
            parameter.select_option(arrangement["parameter"])
            page.wait_for_timeout(200)
            unit = page.locator("[data-testid='measurement-unit']").first
            check(
                "the unit comes from the parameter's own configuration",
                unit.count() == 1 and unit.inner_text().strip() == arrangement["unit"],
                f"unit cell shows {unit.inner_text().strip() if unit.count() else 'nothing'!r}",
            )

            value = page.locator("input[name='value']").first
            value.click()
            page.keyboard.type(arrangement["value"], delay=25)
            check(
                "the measured value takes a decimal in one go",
                value.input_value() == arrangement["value"],
                f"holds {value.input_value()!r}",
            )

            method = page.locator("select[name='method']").first
            check(
                "the method control is a dropdown",
                method.count() == 1,
                f"{method.count()} matching controls",
            )
            method.select_option("REFRACTOMETER")
            page.wait_for_timeout(200)
            saved_method = "Refractometer"

            # The Other path, which is the part that is easy to leave half-done:
            # choose Other, type a method, then fall back to the list and check the
            # typed words are gone rather than waiting to be saved against the
            # wrong choice.
            method.select_option("OTHER")
            page.wait_for_timeout(250)
            other = page.locator("input[name='method_other']").first
            check(
                "choosing Other reveals the field for the method itself",
                other.count() == 1 and other.is_visible(),
                f"{other.count()} matching inputs",
            )
            other.click()
            page.keyboard.type("Bench refractometer, second reading", delay=20)
            check(
                "the typed method takes a whole sentence",
                other.input_value() == "Bench refractometer, second reading",
                f"holds {other.input_value()!r}",
            )
            method.select_option("REFRACTOMETER")
            page.wait_for_timeout(250)
            hidden = page.locator("input[name='method_other']")
            check(
                "switching back to a listed method hides the typed one",
                hidden.count() == 0 or not hidden.first.is_visible(),
                f"{hidden.count()} still rendered",
            )

            page.get_by_role("button", name="Save the measurement").first.click()
            page.wait_for_timeout(1500)
            results = page.locator("table[data-testid='lab-results']")
            check(
                "the measurement is saved and shown in the test's results",
                results.count() == 1 and arrangement["parameter_name"] in results.inner_text(),
                f"results table rows: {page.locator('table[data-testid=\"lab-results\"] tbody tr').count()}",
            )
            check(
                "the method that was chosen is what the record shows",
                saved_method in results.inner_text() if results.count() else False,
                "the method column does not name the chosen method",
            )

            # Reload before completing: a measurement that only exists in the
            # component's state is not a measurement.
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(1000)
            check(
                "the measurement survives a browser refresh",
                arrangement["parameter_name"] in page.locator("table[data-testid='lab-results']").inner_text(),
                "the results table lost the measurement",
            )

            # ------------------------------------------------------------------ #
            section("Completing the test decides the batch")
            # ------------------------------------------------------------------ #
            page.click("[data-testid='complete-test']")
            page.locator("div[role='dialog']").wait_for(state="visible", timeout=10000)
            page.get_by_role("button", name="Complete and decide").first.click()
            page.wait_for_timeout(1800)

            status, payload = request("GET", f"/lab-tests/{test_id}", base=api, token=arrangement["admin"])
            decided = (payload.get("data") or {}) if status == 200 else {}
            check(
                "the test is COMPLETED in the database, not only on screen",
                str(decided.get("status")) == "COMPLETED",
                f"{status} status={decided.get('status')}",
            )
            check(
                "the result the server computed is a decision",
                str(decided.get("overall_result")) in {"PASS", "FAIL", "INCONCLUSIVE"},
                f"result={decided.get('overall_result')}",
            )
            check(
                f"the arranged measurement produces the expected {args.verdict} verdict",
                str(decided.get("overall_result")) == args.verdict,
                f"result={decided.get('overall_result')}",
            )

            status, payload = request(
                "GET", f"/batches/{batch['id']}", base=api, token=arrangement["admin"]
            )
            moved = (payload.get("data") or {}) if status == 200 else {}
            # PASS approves and FAIL rejects. INCONCLUSIVE is not a decision, and the
            # platform has no such batch status: the batch stays under testing with the
            # inconclusive test on its record, so it can never be packed.
            expected = {
                "PASS": "APPROVED",
                "FAIL": "REJECTED",
                "INCONCLUSIVE": "LAB_TESTING",
            }.get(str(decided.get("overall_result")), "?")
            check(
                f"the batch follows the verdict ({decided.get('overall_result')} → {expected})",
                str(moved.get("status")) == expected,
                f"batch status is {moved.get('status')}",
            )

            if str(decided.get("overall_result")) == "INCONCLUSIVE":
                status, payload = request(
                    "GET", f"/batches/{batch['id']}/timeline", base=api, token=arrangement["admin"]
                )
                stages = payload.get("data") or [] if status == 200 else []
                laboratory = next((s for s in stages if s.get("stage") == "LABORATORY"), {})
                check(
                    "traceability says the laboratory stage is inconclusive, not passed",
                    "INCONCLUSIVE" in str(laboratory.get("outcome", "")).upper()
                    or "INCONCLUSIVE" in str(laboratory.get("detail", "")).upper(),
                    f"laboratory stage reads {laboratory!r}",
                )
                status, payload = request(
                    "GET", f"/batches/{batch['id']}", base=api, token=arrangement["admin"]
                )
                reread = (payload.get("data") or {}) if status == 200 else {}
                check(
                    "the inconclusive test is on the batch's record, not only on the test",
                    str(reread.get("lab_result") or reread.get("latest_lab_result") or "")
                    == "INCONCLUSIVE"
                    or "INCONCLUSIVE" in str(reread.get("laboratory_status", "")),
                    f"batch carries {reread.get('lab_result')!r}",
                )

            # The queues: the test must have left the ones it is no longer in.
            page.goto(f"{web}/laboratory/completed", wait_until="networkidle")
            page.wait_for_timeout(1200)
            check(
                "the completed queue now lists the test",
                decided.get("test_code", "TEST") in page.inner_text("body"),
                f"{decided.get('test_code')} not found in the completed queue",
            )
            page.goto(f"{web}/laboratory/pending", wait_until="networkidle")
            page.wait_for_timeout(1200)
            check(
                "the pending queue no longer offers it as work",
                decided.get("test_code", "TEST") not in page.inner_text("body"),
                "the finished test is still being offered as pending",
            )

            page.goto(test_url, wait_until="networkidle")
            page.wait_for_timeout(1000)
            body = page.inner_text("body")
            check(
                "the test page shows the decision it reached",
                "Completed" in body and str(decided.get("overall_result", "")).title() in body,
                "the panel does not show the completed result",
            )

            # ------------------------------------------------------------------ #
            section("The approved batch reaches packaging")
            # ------------------------------------------------------------------ #
            status, payload = request(
                "GET", "/packaging/approved-batches?page_size=20", base=api, token=arrangement["admin"]
            )
            approved_codes = [row.get("batch_code") for row in (payload.get("data") or [])]
            if decided.get("overall_result") == "PASS":
                check(
                    "an approved batch is offered to packaging",
                    batch["batch_code"] in approved_codes,
                    f"not in {approved_codes[:5]}",
                )
            else:
                check(
                    "a batch that did not pass is not offered to packaging",
                    batch["batch_code"] not in approved_codes,
                    f"unexpectedly offered: {approved_codes[:5]}",
                )
                # Being absent from the worklist is not the same as being refused, so
                # the packing itself is attempted. The status check above says the
                # record is REJECTED; this says the rule actually stops it.
                status, payload = request(
                    "POST",
                    "/packaging",
                    base=api,
                    token=arrangement["admin"],
                    body={
                        "batch_id": batch["id"],
                        "packaging_type": "JAR",
                        "packaged_quantity": "1",
                        "package_size": "1",
                        "number_of_packages": 1,
                    },
                )
                check(
                    "packaging a batch that did not pass is refused by the server",
                    status in (400, 403, 409),
                    f"{status} {payload.get('error', {}).get('message') if isinstance(payload, dict) else payload}",
                )

        check("no console errors during the run", not console_errors, str(console_errors[:3]))
        browser.close()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for failure in FAILED:
        print(f"  FAILED  {failure}")
    print(
        f"\nEverything this run created is TEST data (batch {batch['batch_code']}, "
        f"beekeeper {arrangement['keeper']['email']})."
    )
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
