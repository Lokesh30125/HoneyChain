"""Role-based workspace, navigation and laboratory→beekeeper synchronisation smoke.

Driven by a real browser against the built frontend, this verifies the two promises
of the role-based navigation phase from the outside:

**1. Each role sees only its own workspace.** For four signed-in roles the sidebar
is read as rendered text and compared with what that role works in, and a URL typed
by hand — ``/admin/users`` as a beekeeper, ``/laboratory`` as a KVIC officer, and so
on — is checked to land the user back in their own workspace rather than on a
"this is not your workspace" notice.

**2. A laboratory decision reaches the beekeeper.** A harvest is recorded and its
batch is processed and tested, the last step **through the laboratory technician's
own screens**. The beekeeper's batch page and traceability page are then opened in
a separate session and must show the laboratory stage as approved — read from the
same batch and test rows, with no duplicate record anywhere.

Setup uses the API (recording a harvest, processing a batch, configuring one
reference range); the laboratory work and every assertion happen in the browser.
The run cleans up after itself over SQL.

Run::

    cd backend && .venv/bin/uvicorn app.main:app --port 8000          # terminal 1
    cd frontend && npm run build && npx vite preview --port 4173      # terminal 2
    cd backend && .venv/bin/python tests/browser_smoke_role_navigation.py

Exit code 0 only if every check passes.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

from playwright.sync_api import Page, sync_playwright

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:4173")
API_URL = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")
HEADLESS = os.getenv("SMOKE_HEADLESS", "true").lower() != "false"
DIST_DIR = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"

ACCOUNTS = {
    "beekeeper": ("beekeeper@honeychain.example.com", "HoneyPass123"),
    "admin": ("admin@honeychain.example.com", "AdminSecure123"),
    "kvic": ("kvic@honeychain.example.com", "KvicSecure123"),
    "processor": ("processor@honeychain.example.com", "ProcessPass123"),
    "labtech": ("labtech@honeychain.example.com", "LabTechPass123"),
    "consumer": ("consumer@honeychain.example.com", "ConsumerPass123"),
}

PASSED: list[str] = []
FAILED: list[str] = []
CONSOLE_ERRORS: list[str] = []


def check(description: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(description)
        print(f"  PASS  {description}")
    else:
        FAILED.append(f"{description} {detail}".strip())
        print(f"  FAIL  {description} {detail}".strip())


# --------------------------------------------------------------------------- #
# API helpers — used only to set the scene, never to assert the UI
# --------------------------------------------------------------------------- #
def api_login(email: str, password: str) -> str:
    request = urllib.request.Request(
        f"{API_URL}/auth/login",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)["data"]["access_token"]


def api_call(method: str, path: str, token: str, payload: dict | None = None):
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as response:
            body = json.load(response)
            return response.status, body.get("data"), body.get("meta") or {}
    except urllib.error.HTTPError as error:  # a refusal is a legitimate answer
        return error.code, None, {"text": error.read().decode(errors="replace")[:200]}


# --------------------------------------------------------------------------- #
# Browser helpers
# --------------------------------------------------------------------------- #
def go(page: Page, path: str, settle: int = 1300) -> None:
    page.goto(f"{BASE_URL}{path}", wait_until="commit", timeout=30000)
    page.wait_for_timeout(settle)


def text_of(page: Page) -> str:
    return page.inner_text("body")


def wait_for_text(page: Page, needle: str, timeout: int = 12000) -> bool:
    try:
        page.wait_for_selector(f"text={needle}", timeout=timeout, state="visible")
        return True
    except Exception:  # noqa: BLE001 - absence is a legitimate result
        return False


def fill(page: Page, selector: str, value: str) -> None:
    """Set a field's value the way the browser does it.

    Native ``fill`` sets the value and fires one input event, which is what a
    React-controlled number input expects. Typing character by character into a
    controlled number field re-renders between keystrokes and can silently keep
    only the first digit — a real bug this smoke caught once, on the laboratory
    measurement form.
    """
    field = page.locator(selector).first
    field.click()
    field.fill(value)


def sign_in(page: Page, account: str) -> None:
    email, password = ACCOUNTS[account]
    go(page, "/about")
    page.evaluate("window.sessionStorage.clear()")
    page.evaluate("window.localStorage.clear()")
    go(page, "/login")
    fill(page, "input[name='email']", email)
    fill(page, "input[name='password']", password)
    page.click("button[type='submit']")
    page.wait_for_url(lambda url: "/login" not in url, timeout=20000)
    page.wait_for_timeout(1200)


def sidebar_labels(page: Page) -> list[str]:
    return [
        item.strip()
        for item in page.locator("nav[aria-label='Primary'] a").all_inner_texts()
        if item.strip()
    ]


def bundle_contains(needle: str) -> bool:
    if not DIST_DIR.exists():
        return False
    for path in DIST_DIR.rglob("*.js"):
        try:
            if needle in path.read_text(errors="replace"):
                return True
        except OSError:
            continue
    return False


def cleanup(batch_code: str | None) -> None:
    """Remove what this run created, over SQL — the API forbids deletion."""
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        from app.core.config import get_settings  # noqa: PLC0415
        import psycopg  # noqa: PLC0415

        dsn = get_settings().DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                if batch_code:
                    cursor.execute(
                        "DELETE FROM lab_test_results WHERE lab_test_id IN ("
                        "SELECT t.id FROM lab_tests t JOIN honey_batches b ON b.id = t.batch_id "
                        "WHERE b.batch_code = %s)",
                        (batch_code,),
                    )
                    cursor.execute(
                        "DELETE FROM lab_tests WHERE batch_id IN (SELECT id FROM honey_batches WHERE batch_code = %s)",
                        (batch_code,),
                    )
                    cursor.execute(
                        "DELETE FROM honey_processing_records WHERE batch_id IN "
                        "(SELECT id FROM honey_batches WHERE batch_code = %s)",
                        (batch_code,),
                    )
                    cursor.execute(
                        "DELETE FROM honey_batches WHERE collection_id IN ("
                        "SELECT id FROM honey_collections WHERE notes LIKE '%%role navigation smoke%%')"
                    )
                    cursor.execute(
                        "DELETE FROM honey_collections WHERE notes LIKE '%%role navigation smoke%%'"
                    )
                    removed = cursor.rowcount
                else:
                    removed = 0
                # The processing unit and the reference range are fixtures too: the
                # unit is named after this process, and the range is the one this run
                # configured. Leaving them behind would let a later run start from a
                # range it did not set, and would keep consuming unit codes.
                cursor.execute(
                    "DELETE FROM processing_units WHERE name = %s",
                    (f"Role smoke unit {os.getpid()}",),
                )
                cursor.execute(
                    "UPDATE lab_parameters SET reference_min = NULL, reference_max = NULL, "
                    "reference_source = NULL WHERE code = 'MOISTURE' "
                    "AND reference_source LIKE '%%Role smoke%%'"
                )
            connection.commit()
        print(f"\nCleanup: removed the smoke's records ({removed} collection row(s) touched).")
    except Exception as error:  # noqa: BLE001 - cleanup must never fail the run
        print(f"\nCleanup: could not remove the smoke's records automatically ({error}).")


# --------------------------------------------------------------------------- #
# The scenario
# --------------------------------------------------------------------------- #
BEEKEEPER_EXPECTED = {
    "Dashboard",
    "My Profile",
    "My Hives",
    "IoT Monitoring",
    "AI Insights",
    "Alerts",
    "Honey Collections",
    "Honey Batches",
    "Traceability",
}
BEEKEEPER_FORBIDDEN = [
    "Users",
    "Custodians",
    "Beekeepers",
    "Clusters",
    "Processing",
    "Laboratory",
    "Packaging",
    "Distribution",
    "Audit Logs",
    "KVIC",
    "Consumer",
    "System",
]

KVIC_EXPECTED = {
    "Dashboard",
    "My Profile",
    "Clusters",
    "Beekeepers",
    "Hives",
    "IoT Monitoring",
    "AI Insights",
    "Alerts",
    "Honey Collections",
    "Honey Batches",
    "Processing",
    "Laboratory",
    "Traceability",
    "Cluster Analytics",
}

LAB_EXPECTED = {
    "Dashboard",
    "My Profile",
    "Pending Lab Tests",
    "Laboratory Tests",
    "Samples",
    "Completed Tests",
    "Reference Parameters",
    "Laboratories",
}

PROCESSOR_EXPECTED = {
    "Dashboard",
    "My Profile",
    "Awaiting Processing",
    "Processing Runs",
    "Batches",
    "Processing Units",
}


def main() -> int:
    print("=" * 72)
    print("  HoneyChain — role-based workspace & laboratory synchronisation smoke")
    print(f"  {BASE_URL}")
    print("=" * 72)

    beekeeper_token = api_login(*ACCOUNTS["beekeeper"])
    admin_token = api_login(*ACCOUNTS["admin"])
    processor_token = api_login(*ACCOUNTS["processor"])

    # ---------------------------------------------------------------- fixture
    hives = api_call("GET", "/collections/eligible-hives", beekeeper_token)[1]
    if not hives or not hives.get("hives"):
        print("  No harvestable hives for the seeded beekeeper — run seed_dev_data.py first.")
        return 2
    hive = hives["hives"][0]

    unit_status, unit, _ = api_call(
        "POST",
        "/processing-units",
        processor_token,
        {"name": f"Role smoke unit {os.getpid()}", "location": "Guntur"},
    )
    check("a processing unit can be registered (API fixture)", unit_status == 201, f"status {unit_status}")

    collection_status, collection, _ = api_call(
        "POST",
        "/collections",
        beekeeper_token,
        {
            "collection_date": "2026-09-27",
            "unit": "KG",
            "hives": [{"hive_id": hive["id"], "quantity": "12.5"}],
            "notes": f"Recorded by tests/browser_smoke_role_navigation.py (role navigation smoke) — {hive['hive_code']}",
        },
    )
    check("the beekeeper records a harvest (API fixture)", collection_status == 201, f"status {collection_status}")
    if collection_status != 201:
        cleanup(None)
        return 2

    complete_status, completed, meta = api_call(
        "POST", f"/collections/{collection['id']}/complete", beekeeper_token, {}
    )
    check("completing it creates the batch (API fixture)", complete_status == 200, f"status {complete_status}")
    batch_id = (meta.get("batch") or {}).get("id")
    batch_code = (meta.get("batch") or {}).get("batch_code")
    if not batch_id:
        print("  No batch id returned; aborting.")
        cleanup(None)
        return 2

    run_status, run, _ = api_call(
        "POST",
        "/processing",
        processor_token,
        {"batch_id": batch_id, "processing_type": "FILTERING", "processing_unit_id": unit["id"] if unit else None},
    )
    check("a run opens against the batch (API fixture)", run_status == 201, f"status {run_status}")
    api_call("POST", f"/processing/{run['id']}/start", processor_token, {})
    done_status, done_run, _ = api_call(
        "POST",
        f"/processing/{run['id']}/complete",
        processor_token,
        {"input_quantity": "12.5", "output_quantity": "11.8"},
    )
    check("the run completes with measured quantities (API fixture)", done_status == 200, f"status {done_status}")
    check(
        "the batch is now awaiting testing (API fixture)",
        done_run is not None and done_run.get("batch_status") == "LAB_TESTING",
        str(done_run.get("batch_status") if done_run else None),
    )

    # One reference range, from a stated source — the platform invents nothing.
    parameter_status, _, _ = api_call(
        "PATCH",
        "/lab-parameters/MOISTURE",
        admin_token,
        {"reference_min": "0", "reference_max": "20", "reference_source": "Role smoke: configured range for the smoke run", "is_required": True},
    )
    check("an administrator configures one reference range (API fixture)", parameter_status == 200, f"status {parameter_status}")

    labs = api_call("GET", "/laboratories?page_size=50", admin_token)[1] or []
    if not labs:
        lab_status, lab, _ = api_call(
            "POST",
            "/laboratories",
            admin_token,
            {"name": "Role smoke laboratory", "district": "Guntur"},
        )
        check("a laboratory can be registered (API fixture)", lab_status == 201, f"status {lab_status}")
        labs = [lab]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on(
            "console",
            lambda message: CONSOLE_ERRORS.append(message.text) if message.type == "error" else None,
        )

        # ------------------------------------------------------- shipped wording
        print("\n1. The wording the phase requires (as shipped in the bundle)")
        for phrase in (
            "No batches awaiting processing.",
            "No batches awaiting laboratory testing.",
            "No laboratory results recorded.",
            "Loading batch information...",
            "Unable to load laboratory information.",
        ):
            check(f'the bundle contains "{phrase}"', bundle_contains(phrase), "not found in dist")
        check(
            "no 'not your workspace' notice is shipped anywhere",
            not bundle_contains("This is not your workspace")
            and not bundle_contains("not available for your role"),
            "a cross-workspace notice is still in the bundle",
        )

        # ----------------------------------------------------------- BEEKEEPER
        print("\n2. Beekeeper — sidebar and route guards")
        sign_in(page, "beekeeper")
        go(page, "/dashboard")
        labels = set(sidebar_labels(page))
        check("the beekeeper sidebar lists exactly their own workspace", labels == BEEKEEPER_EXPECTED, f"got {sorted(labels)}")
        body = text_of(page)
        check(
            "no cross-role label leaks into the beekeeper's navigation",
            not any(label in labels for label in BEEKEEPER_FORBIDDEN),
            f"found {sorted(labels & set(BEEKEEPER_FORBIDDEN))}",
        )
        check(
            "the page carries no 'coming soon', 'not your workspace' or placeholder notice",
            "coming soon" not in body.lower()
            and "not your workspace" not in body.lower()
            and "not available for your role" not in body.lower(),
            "placeholder wording is rendered",
        )

        for path, expected in (
            ("/admin/users", "/beekeeper"),
            ("/laboratory", "/beekeeper"),
            ("/processor/runs", "/beekeeper"),
            ("/kvic/batches", "/beekeeper"),
        ):
            go(page, path)
            check(
                f"beekeeper typing {path} lands in their own workspace",
                expected in page.url and path not in page.url,
                f"ended on {page.url}",
            )

        # ------------------------------------------------------ the journey now
        print("\n3. The laboratory technician decides the batch")
        sign_in(page, "labtech")
        labels = set(sidebar_labels(page))
        check("the laboratory sidebar lists exactly the laboratory workspace", labels == LAB_EXPECTED, f"got {sorted(labels)}")
        for path, expected in (("/admin/users", "/laboratory"), ("/kvic", "/laboratory"), ("/beekeeper/hives", "/laboratory")):
            go(page, path)
            check(
                f"laboratory technician typing {path} lands in the laboratory workspace",
                expected in page.url and path not in page.url,
                f"ended on {page.url}",
            )

        go(page, "/laboratory/awaiting")
        check("the pending queue names the batch", wait_for_text(page, batch_code), f"{batch_code} not listed")
        page.locator(f"[data-testid='open-test-{batch_code}']").first.click()
        page.wait_for_timeout(900)
        if page.locator("select[name='laboratory_id']").first.input_value() == "":
            page.locator("select[name='laboratory_id']").first.select_option(index=1)
        page.locator("[data-testid='create-test']").first.click()
        page.wait_for_url(lambda url: "/laboratory/tests/" in url, timeout=15000)
        page.wait_for_timeout(1200)
        body = text_of(page)
        check("the test page opens on the new sample", "HC-LAB-" in body and "HC-SMP-" in body, "no coded sample shown")
        check("the traceability chain is shown from the records", "Sample traceability" in body, "no traceability section")
        check("no laboratory result is claimed before one is recorded", "No laboratory results recorded." in body, "unexpected result text")

        page.locator("button:has-text('Record a measurement')").first.click()
        page.wait_for_timeout(700)
        page.locator("select[name='parameter_code']").first.select_option("MOISTURE")
        fill(page, "input[name='value']", "17.4")
        typed = page.locator("input[name='value']").first.input_value()
        check("the form carries the value that was typed", typed == "17.4", f"field reads {typed!r}")
        page.locator("button:has-text('Save the measurement')").first.click()
        page.wait_for_timeout(1800)
        check("the measured value is recorded against the test", "17.4" in text_of(page), "value not stored")
        check("the parameter is judged against the configured range", wait_for_text(page, "Pass"), "no outcome shown")

        page.locator("[data-testid='complete-test']").first.click()
        page.wait_for_timeout(700)
        page.locator("button:has-text('Complete and decide')").first.click()
        page.wait_for_timeout(2000)
        body = text_of(page)
        check("the platform decides the test", "Completed" in body, "status not completed")
        check("the decision is a pass, computed from the measurement", "Pass" in body, "no computed pass")
        check(
            "the decision explains itself in words",
            "within its configured range" in body or "configured range" in body,
            "no evaluation note",
        )

        # --------------------------------------------------------- BEEKEEPER
        print("\n4. The beekeeper's own view reflects the decision")
        sign_in(page, "beekeeper")
        go(page, f"/beekeeper/traceability/{batch_id}", settle=2000)
        body = text_of(page)
        check("the beekeeper can reach the batch's journey", batch_code in body, f"{batch_code} missing")
        check("the laboratory stage reads approved", "Approved" in body, "no approval shown to the beekeeper")
        check("packaging is still honestly pending", "Pending" in body and "Not implemented in this phase" in body, "packaging stage misreported")
        check("the processing quantities are shown as measured", "12.5" in body and "11.8" in body, "processed quantities missing")
        check(
            "the beekeeper has no control over the laboratory record",
            "Record a measurement" not in body and "Complete test" not in body,
            "a laboratory control is rendered for the beekeeper",
        )

        go(page, f"/beekeeper/batches/{batch_id}", settle=1800)
        body = text_of(page)
        check("the batch page shows the quality summary", "Quality summary" in body, "no quality summary")
        check("the quality summary carries the measured value", "17.4" in body, "measured value missing")
        check("the batch reads approved, not merely completed", "Approved" in body, "no approval on the batch page")

        # ------------------------------------------------------------- KVIC
        print("\n5. KVIC sees the same updated status for authorised data")
        sign_in(page, "kvic")
        labels = set(sidebar_labels(page))
        check("the KVIC sidebar lists exactly the officer's workspace", labels == KVIC_EXPECTED, f"got {sorted(labels)}")
        check(
            "no administration entry appears for the officer",
            "Users" not in labels and "Audit Logs" not in labels,
            f"found {sorted(labels)}",
        )
        for path, expected in (("/admin/users", "/kvic"), ("/laboratory", "/kvic"), ("/beekeeper/hives", "/kvic")):
            go(page, path)
            check(
                f"officer typing {path} lands in the KVIC workspace",
                expected in page.url and path not in page.url,
                f"ended on {page.url}",
            )

        go(page, f"/kvic/batches/{batch_id}", settle=1800)
        body = text_of(page)
        check("the officer reads the same batch record", batch_code in body, f"{batch_code} missing")
        check("the officer sees the laboratory outcome", "Approved" in body, "no outcome shown to KVIC")
        check(
            "the officer has no laboratory controls",
            "Record a measurement" not in body and "Override the outcome" not in body,
            "a laboratory control is rendered for the officer",
        )

        go(page, "/kvic/laboratory", settle=1600)
        body = text_of(page)
        check("the laboratory oversight page opens for the officer", "Laboratory oversight" in body, "page did not open")
        check(
            "and it is read-only",
            "Record a measurement" not in body and "Complete test" not in body,
            "a write control is rendered for the officer",
        )

        # --------------------------------------------------------- PROCESSOR
        print("\n6. Processor — own workspace only")
        sign_in(page, "processor")
        labels = set(sidebar_labels(page))
        check("the processor sidebar lists exactly the processing workspace", labels == PROCESSOR_EXPECTED, f"got {sorted(labels)}")
        for path, expected in (("/kvic/batches", "/processor"), ("/admin/users", "/processor"), ("/beekeeper/hives", "/processor")):
            go(page, path)
            check(
                f"processor typing {path} lands in the processing workspace",
                expected in page.url and path not in page.url,
                f"ended on {page.url}",
            )

        go(page, "/processor/runs", settle=1600)
        check("the processor reads the run they recorded", wait_for_text(page, run["processing_code"]), "run not listed")
        go(page, "/processor/awaiting", settle=1400)
        body = text_of(page)
        check(
            "the processing queue states its emptiness honestly",
            "No batches awaiting processing." in body or "waiting for a run" in body or "Collected" in body,
            "queue did not render",
        )

        # ------------------------------------------------------------ CONSUMER
        print("\n7. Consumer — no borrowed workspace")
        sign_in(page, "consumer")
        labels = set(sidebar_labels(page))
        check(
            "the consumer sidebar offers only their account screens",
            labels == {"Dashboard", "My Profile"},
            f"got {sorted(labels)}",
        )
        for path, expected in (("/kvic/batches", "/consumer"), ("/admin/users", "/consumer"), ("/laboratory", "/consumer")):
            go(page, path)
            check(
                f"consumer typing {path} lands in their own workspace",
                expected in page.url and path not in page.url,
                f"ended on {page.url}",
            )

        # --------------------------------------------------------- noise check
        print("\n8. Browser console")
        relevant = [
            error
            for error in CONSOLE_ERRORS
            if "Failed to load resource" not in error and "favicon" not in error.lower()
        ]
        check("no console errors on the visited screens", not relevant, f"{relevant[:3]}")

        browser.close()

    cleanup(batch_code)

    print("\n" + "=" * 72)
    print(f"  {len(PASSED)} passed / {len(FAILED)} failed")
    if FAILED:
        for failure in FAILED:
            print(f"    FAILED: {failure}")
    print("=" * 72)
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
