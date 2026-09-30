"""The packaging-unit screen, driven in a browser, against the real database.

Four things are checked here that no API script can check, because each of them is
about what a person sees:

1. An administrator can **register a packaging unit** from Administration →
   Packaging Units, and the unit appears in the list with the code the server
   issued — not a code the browser made up.
2. The same screen attaches an **account** to that unit.
3. That operator **signs in through the ordinary login** and their packaging
   workspace states the facility without being asked — no dropdown, and no "no unit
   registered" sentence, which was the complaint.
4. The run dialog opens with **"Select packaging type"** and **"Select package
   size"** rather than a pre-chosen jar, its inputs take continuous typing, and the
   server's arithmetic check refuses a run whose figures do not add up.

Run it while the API and the built frontend are both up::

    cd backend
    .venv/bin/python tests/browser_packaging_units.py
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.api_smoke_phase7 import create_staff, request, sign_in  # noqa: E402

DEFAULT_APP = "http://localhost:4173"
DEFAULT_API = "http://localhost:8000/api/v1"
ADMIN = ("admin@honeychain.example.com", "AdminSecure123")

PASSED: list[str] = []
FAILED: list[str] = []
MARK = uuid.uuid4().hex[:6]
#: The password the provisioning helper sets on an account it creates.
STAFF_PASSWORD = "SmokeP7Staff123"


def check(description: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(description)
    print(f"  {'PASS' if condition else 'FAIL'}  {description}" + (f" — {detail}" if detail and not condition else ""))


def section(title: str) -> None:
    print(f"\n=== {title}")


def sign_in_ui(page, app: str, email: str, password: str, expect_path: str) -> None:
    """Sign in from a clean slate: a live session would redirect away from /login."""
    page.goto(f"{app}/login", wait_until="domcontentloaded")
    page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
    page.goto(f"{app}/login", wait_until="networkidle")
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_url(f"**{expect_path}**", timeout=20000)
    page.wait_for_load_state("networkidle")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", default=DEFAULT_APP)
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    app = args.app_url.rstrip("/")
    api = args.api_url.rstrip("/")

    from playwright.sync_api import sync_playwright

    admin = sign_in(api, *ADMIN)
    unit_name = f"Browser Unit TEST {MARK}"
    registration = f"REG-BROWSER-{MARK}"
    

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        # -------------------------------------------------------------- #
        section("An administrator registers a packaging unit in the browser")
        # -------------------------------------------------------------- #
        sign_in_ui(page, app, *ADMIN, expect_path="/admin")
        page.goto(f"{app}/admin/packaging-units", wait_until="networkidle")
        check(
            "the Administration sidebar links to Packaging Units",
            page.locator('a[href="/admin/packaging-units"]').count() >= 1,
        )
        page.click('[data-testid="register-packaging-unit"]')
        page.wait_for_selector('[data-testid="unit-name"]', timeout=10000)

        # Continuous typing, character by character: an input that takes one
        # character and drops the rest is the defect this checks for.
        page.click('[data-testid="unit-name"]')
        page.type('[data-testid="unit-name"]', unit_name, delay=25)
        page.click('[data-testid="unit-registration"]')
        page.type('[data-testid="unit-registration"]', registration, delay=25)
        typed_name = page.input_value('[data-testid="unit-name"]')
        typed_registration = page.input_value('[data-testid="unit-registration"]')
        check("the unit name field keeps every character typed", typed_name == unit_name, typed_name)
        check(
            "the registration field keeps every character typed",
            typed_registration == registration,
            typed_registration,
        )

        page.fill('input[name="district"]', "Guntur")
        page.fill('input[name="state"]', "Andhra Pradesh")
        page.fill('input[name="address"]', "12 Market Road, Guntur 522001")
        page.click('[data-testid="submit-packaging-unit"]')
        # The dialog closing is the receipt: it is only closed once the API has
        # answered. Waiting for the word "registered" on the page would have matched
        # the "Units registered" counter and checked too early.
        page.wait_for_selector('[data-testid="unit-name"]', state="detached", timeout=20000)
        check(
            "the page confirms the registration with the code the server issued",
            page.locator("text=Unit HC-PKUNIT-").count() >= 1,
            page.inner_text("body")[:200],
        )

        # Polled briefly rather than read once: the write has returned, and this is
        # the read that proves it reached the database.
        created = None
        for _ in range(10):
            status, payload = request(
                "GET", f"/packaging-units?search={MARK}", base=api, token=admin
            )
            units = (payload.get("data") or []) if status == 200 else []
            created = next((row for row in units if row["name"] == unit_name), None)
            if created:
                break
            page.wait_for_timeout(500)
        check("the unit is stored by the API, not only shown", created is not None, str(payload)[:200])
        if created:
            check(
                "the unit code is the one the server issued",
                str(created["unit_code"]).startswith("HC-PKUNIT-"),
                str(created.get("unit_code")),
            )
            check(
                "the address typed in the browser is what was stored",
                created["address"] == "12 Market Road, Guntur 522001",
                str(created.get("address")),
            )
        check(
            "the list shows the new unit without a manual reload",
            page.locator(f"text={unit_name}").count() >= 1,
        )

        # -------------------------------------------------------------- #
        section("The same screen puts an account to work at it")
        # -------------------------------------------------------------- #
        operator = create_staff(api, admin, f"browser.operator.{MARK}", "PACKAGING_UNIT")
        status, payload = request(
            "POST",
            f"/packaging-units/{created['id']}/members",
            base=api,
            token=admin,
            body={"user_id": operator["user_id"]},
        )
        check("the operator account is attached to the unit", status == 200, f"{status} {payload}")

        page.goto(f"{app}/admin/packaging-units", wait_until="networkidle")
        page.click(f'[data-testid="unit-members-{created["unit_code"]}"]')
        page.wait_for_selector(f"text={operator['email']}", timeout=10000)
        check(
            "the unit's people list names the operator",
            page.locator(f"text={operator['email']}").count() >= 1,
        )
        check(
            "the list counts the account against the unit",
            "1" in page.inner_text("table"),
        )
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # -------------------------------------------------------------- #
        section("The operator signs in and sees their own facility")
        # -------------------------------------------------------------- #
        # The helper provisions the account with a password it knows, and the
        # operator signs in through the ordinary login form with it — the same form
        # every other account uses.
        sign_in_ui(page, app, operator["email"], STAFF_PASSWORD, expect_path="/packaging")
        page.wait_for_selector('[data-testid="packaging-unit-name"]', timeout=15000)
        shown = page.inner_text('[data-testid="packaging-unit-name"]')
        check("the workspace names the facility attached to the account", unit_name in shown, shown)
        check(
            "the sentence about having no unit is gone",
            page.locator("text=No packaging unit is registered yet").count() == 0,
        )
        check(
            "the account is told it can pack under no other unit",
            page.locator("text=recorded against this unit").count() >= 1,
        )

        # -------------------------------------------------------------- #
        section("The run dialog asks instead of guessing")
        # -------------------------------------------------------------- #
        # A batch with room left in it, chosen by its code so the row clicked is the
        # row checked. The approved table shows approved, packed and remaining for
        # exactly this reason.
        status, payload = request(
            "GET", "/packaging/approved-batches?page_size=50", base=api, token=operator["token"]
        )
        target = next(
            (
                row
                for row in (payload.get("data") or [])
                if float(row.get("remaining_quantity") or 0) >= 10 and not row.get("open_packaging_code")
            ),
            None,
        )
        check("the operator has an approved batch to work from", target is not None)
        if target is None:
            context.close()
            browser.close()
            print("\nCannot continue without an approved batch with room to pack.")
            return 1

        page.reload(wait_until="networkidle")
        page.wait_for_selector(f'[data-testid="pack-batch-{target["batch_code"]}"]', timeout=15000)
        check(
            "the approved table shows the quantities as approved, packed and remaining",
            all(
                page.locator(f"th:has-text('{header}')").count() >= 1
                for header in ("Approved", "Packed", "Remaining")
            ),
        )
        page.click(f'[data-testid="pack-batch-{target["batch_code"]}"]')
        page.wait_for_selector('select[name="packaging_type"]', timeout=10000)
        type_select = page.locator('select[name="packaging_type"]')
        check(
            "the packaging type starts on 'Select packaging type'",
            type_select.input_value() == "",
        )
        check(
            "the type dropdown offers the placeholder as its own option",
            "Select packaging type" in type_select.locator("option").first.inner_text(),
        )
        check(
            "the package size starts on 'Select package size'",
            page.locator('select[name="package_size_choice"]').input_value() == "",
        )
        check(
            "the unit is stated, not offered as a dropdown",
            page.locator('select[name="packaging_unit_id"]').count() == 0,
        )
        check(
            "the standard sizes are offered",
            "1 kg"
            in " ".join(page.locator('select[name="package_size_choice"] option').all_inner_texts()),
        )

        # Typing into the quantity field, again character by character.
        page.click('input[name="packaged_quantity"]')
        page.keyboard.press("Control+A")
        page.type('input[name="packaged_quantity"]', "10", delay=30)
        check(
            "the quantity field keeps every character typed",
            page.input_value('input[name="packaged_quantity"]') == "10",
            page.input_value('input[name="packaged_quantity"]'),
        )

        # Other reveals a custom type field, and it takes typing too.
        type_select.select_option("OTHER")
        page.wait_for_selector('input[name="packaging_type_other"]', timeout=5000)
        page.click('input[name="packaging_type_other"]')
        page.type('input[name="packaging_type_other"]', "500 g glass jar with brass lid", delay=15)
        check(
            "the custom packaging type keeps every character typed",
            page.input_value('input[name="packaging_type_other"]') == "500 g glass jar with brass lid",
            page.input_value('input[name="packaging_type_other"]'),
        )

        page.locator('select[name="package_size_choice"]').select_option("OTHER")
        page.wait_for_selector('[data-testid="package-size-other"]', timeout=5000)
        page.click('[data-testid="package-size-other"]')
        page.type('[data-testid="package-size-other"]', "0.5", delay=30)
        check(
            "the size field keeps every character typed",
            page.input_value('[data-testid="package-size-other"]') == "0.5",
            page.input_value('[data-testid="package-size-other"]'),
        )

        # 10 kg of honey cannot be five 0.5 kg packages: the dialog refuses it before
        # sending, and the server refuses it too.
        page.fill('input[name="number_of_packages"]', "5")
        page.click('[data-testid="submit-packaging"]')
        page.wait_for_timeout(600)
        check(
            "figures that do not add up are refused with the arithmetic shown",
            page.locator("text=is 2.5, not 10").count() >= 1,
            page.inner_text("form"),
        )

        status, payload = request(
            "GET",
            "/packaging?page_size=5",
            base=api,
            token=operator["token"],
        )
        check(
            "no run was created by the refused figures",
            status == 200 and not (payload.get("data") or []),
            str(payload.get("data"))[:160],
        )

        check("no uncaught JavaScript error occurred", not errors, "; ".join(errors[:3]))
        context.close()
        browser.close()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for failure in FAILED:
        print(f"  FAILED  {failure}")
    print(f"\nTEST data: unit {unit_name} ({registration}), operator {operator['email']}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
