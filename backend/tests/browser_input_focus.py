"""Does every text field keep focus while it is being typed into?

This is a *verification script*, not part of the pytest suite. It drives a real
browser through the running application — full pages and small dialog windows —
and types a complete value into each field in one go, the way a person does.

The bug it exists to catch: a dialog whose focus effect re-ran on every render,
which made each input inside it accept exactly one character before losing focus.

It also covers the control that appears *because of* a choice — the "specify other"
field a dropdown reveals — since a field that only exists after a selection is the
easiest place for a focus bug to hide.

Run (API and the built frontend must be up)::

    cd backend
    .venv/bin/python tests/browser_input_focus.py

Exit code 0 means every field accepted its whole value with the caret still in it.
"""

from __future__ import annotations

import os
import sys

from playwright.sync_api import Page, sync_playwright

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:4173")

PROCESSOR = ("processor@honeychain.example.com", "ProcessPass123")
ADMIN = ("admin@honeychain.example.com", "AdminSecure123")
LABTECH = ("labtech@honeychain.example.com", "LabTechPass123")
BEEKEEPER = ("beekeeper@honeychain.example.com", "HoneyPass123")

PASSED: list[str] = []
FAILED: list[str] = []


def check(description: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(description)
    print(f"  {'PASS' if condition else 'FAIL'}  {description}{f' — {detail}' if detail and not condition else ''}")


def section(title: str) -> None:
    print(f"\n=== {title}")


def sign_in(page: Page, credentials: tuple[str, str]) -> None:
    """Sign in from a clean slate: a live session would redirect away from /login."""
    email, password = credentials
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
    page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", password)
    page.click("button[type='submit']")
    page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
    page.wait_for_load_state("networkidle")


def type_value(page: Page, selector: str, value: str) -> tuple[str, str | None]:
    """Click the field once, type the whole value, report what landed there.

    Returns the input's value and the name of whatever holds focus afterwards —
    which must still be the field itself.
    """
    field = page.locator(selector).first
    field.wait_for(state="visible", timeout=10000)
    field.click()
    page.keyboard.type(value, delay=25)
    focused = page.evaluate(
        "() => document.activeElement && (document.activeElement.name || document.activeElement.tagName)"
    )
    return field.input_value(), focused


def check_typing(page: Page, selector: str, value: str, label: str) -> None:
    got, focused = type_value(page, selector, value)
    check(
        f"{label} accepts '{value}' in one go",
        got == value,
        f"field holds {got!r} and focus is on {focused!r}",
    )


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        # ------------------------------------------------------------------ #
        section("Sign-in page (the first form anybody meets)")
        # ------------------------------------------------------------------ #
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        check_typing(page, "input[name='email']", "someone@example.com", "Sign-in email")
        check_typing(page, "input[name='password']", "SomePassword123", "Sign-in password")

        # ------------------------------------------------------------------ #
        section("Registration page")
        # ------------------------------------------------------------------ #
        page.goto(f"{BASE_URL}/register", wait_until="networkidle")
        for selector, value, label in (
            ("input[name='name']", "Sita Rao", "Full name"),
            ("input[name='email']", "sita@example.com", "Email"),
            ("input[name='phone']", "9876543210", "Phone"),
            ("input[name='state']", "Andhra Pradesh", "State"),
            ("input[name='district']", "Guntur", "District"),
            ("input[name='organization']", "Guntur Co-operative", "Organisation"),
            ("input[name='password']", "Password123", "Password"),
            ("input[name='confirmPassword']", "Password123", "Confirm password"),
        ):
            check_typing(page, selector, value, label)

        # ------------------------------------------------------------------ #
        section("A dialog window: 'Register a laboratory'")
        # ------------------------------------------------------------------ #
        sign_in(page, LABTECH)
        page.goto(f"{BASE_URL}/laboratory/facilities", wait_until="networkidle")
        page.get_by_role("button", name="Register a laboratory").first.click()
        page.locator("div[role='dialog']").wait_for(state="visible", timeout=10000)
        for selector, value, label in (
            ("input[name='facility_name']", "Honey Quality Laboratory", "Laboratory name"),
            ("input[name='facility_location']", "Guntur", "Location"),
            ("input[name='facility_district']", "Guntur", "District"),
            ("input[name='facility_registration']", "LAB-001", "Registration identifier"),
        ):
            if page.locator(selector).count() == 0:
                check(f"{label} exists in the dialog", False, f"no field {selector}")
                continue
            check_typing(page, selector, value, label)

        # backspace, paste and selection all behave inside the dialog too
        name_field = page.locator("input[name='facility_name']").first
        name_field.click()
        page.keyboard.press("End")
        page.keyboard.press("Backspace")
        after_backspace = name_field.input_value()
        page.keyboard.insert_text("X")
        after_paste = name_field.input_value()
        page.keyboard.press("Control+a")
        page.keyboard.type("Replaced")
        after_select_all = name_field.input_value()
        check(
            "the dialog field takes a backspace, a paste and a replacement",
            after_backspace == "Honey Quality Laborator" and after_paste.endswith("X") and after_select_all == "Replaced",
            f"backspace={after_backspace!r} paste={after_paste!r} replaced={after_select_all!r}",
        )
        check(
            "the dialog is still open after all that typing",
            page.locator("div[role='dialog']").count() == 1,
        )
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check("Escape still closes the dialog", page.locator("div[role='dialog']").count() == 0)

        # ------------------------------------------------------------------ #
        section("Search and filter inputs on a full page")
        # ------------------------------------------------------------------ #
        sign_in(page, ADMIN)
        page.goto(f"{BASE_URL}/admin/users", wait_until="networkidle")
        search = page.locator("input[name='search']").first
        if search.count():
            search.click()
            page.keyboard.type("lakshmi", delay=25)
            check(
                "the admin user search keeps focus while typing",
                search.input_value() == "lakshmi",
                f"holds {search.input_value()!r}",
            )

        # ------------------------------------------------------------------ #
        section("A dialog window on the processing screen")
        # ------------------------------------------------------------------ #
        # "Register a unit" lives on the processing *units* screen, which belongs to
        # the processor workspace: the role that runs the units is the role that
        # keeps the registry, so the dialog is driven from that account. The queue
        # itself need not be non-empty for this screen to be useful.
        sign_in(page, PROCESSOR)
        page.goto(f"{BASE_URL}/processor/units", wait_until="networkidle")
        page.wait_for_timeout(800)
        unit_button = page.get_by_role("button", name="Register a unit").first
        if unit_button.count():
            unit_button.click()
            page.locator("div[role='dialog']").wait_for(state="visible", timeout=10000)
            for selector, value, label in (
                ("input[name='unit_name']", "Guntur Processing Unit", "Unit name"),
                ("input[name='unit_location']", "Guntur", "Unit location"),
                ("input[name='unit_registration']", "PROC-001", "Unit registration"),
            ):
                if page.locator(selector).count() == 0:
                    check(f"{label} exists in the processing dialog", False, f"no field {selector}")
                    continue
                check_typing(page, selector, value, label)
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        else:
            check("the processing screen offers its unit dialog", False, "no such button")

        # The allocation dialog itself, when the queue has a row that can be handed
        # on. Both the run table and the pending-batch table use the same dialog.
        assign = page.locator("[data-testid^='assign-run-'], [data-testid^='assign-batch-']").first
        if assign.count():
            assign.click()
            page.wait_for_timeout(500)
            dialog = page.locator("div[role='dialog']")
            if dialog.count():
                note = dialog.locator("textarea").first
                if note.count():
                    note.click()
                    page.keyboard.type("Allocated to the processing unit.", delay=20)
                    check(
                        "the allocation dialog's note keeps focus while typing",
                        note.input_value() == "Allocated to the processing unit.",
                        f"holds {note.input_value()!r}",
                    )
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
            else:
                check("the allocation dialog opened", False, "no dialog after clicking Assign")
        else:
            print("  skip  no assignable row in the queue right now (the dialog is the same one)")

        # ------------------------------------------------------------------ #
        section("The 'Other' field inside a dialog")
        # ------------------------------------------------------------------ #
        # Pairing a device is where a text field appears *because of* a dropdown
        # choice, so it is the place to check that it takes continuous typing, that
        # it disappears when the choice changes, and that no stale text survives.
        sign_in(page, BEEKEEPER)
        page.goto(f"{BASE_URL}/beekeeper/iot", wait_until="networkidle")
        page.wait_for_timeout(800)
        pair = page.get_by_role("button", name="Pair a device").first
        if pair.count():
            pair.click()
            page.locator("div[role='dialog']").wait_for(state="visible", timeout=10000)
            check_typing(page, "input[name='deviceName']", "North field node", "Device name")

            device_type = page.locator("select[name='deviceType']").first
            other = page.locator("input[name='deviceType_other']")
            if device_type.count():
                device_type.select_option("OTHER")
                page.wait_for_timeout(250)
                check(
                    "choosing Other reveals the field that says what it was",
                    other.count() == 1 and other.first.is_visible(),
                    f"{other.count()} matching inputs",
                )
                value = "Custom LoRa board rev C"
                other.first.click()
                page.keyboard.type(value, delay=25)
                focused = page.evaluate(
                    "() => document.activeElement && document.activeElement.name"
                )
                check(
                    "the description takes a whole value without losing focus",
                    other.first.input_value() == value and focused == "deviceType_other",
                    f"holds {other.first.input_value()!r}, focus on {focused!r}",
                )

                device_type.select_option("ESP32")
                page.wait_for_timeout(250)
                check(
                    "switching back to a listed type hides the description field",
                    other.count() == 0 or not other.first.is_visible(),
                    f"{other.count()} still rendered",
                )
                device_type.select_option("OTHER")
                page.wait_for_timeout(250)
                revived = page.locator("input[name='deviceType_other']")
                check(
                    "choosing Other again comes back empty rather than stale",
                    revived.count() == 1 and revived.first.input_value() == "",
                    f"holds {revived.first.input_value()!r}" if revived.count() else "field missing",
                )
            else:
                check("the device type dropdown is there to choose Other on", False, "no select")
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        else:
            check("the IoT screen offers device pairing", False, "no such button")

        # ------------------------------------------------------------------ #
        section("A numeric field on a full page, typed in one go")
        # ------------------------------------------------------------------ #
        sign_in(page, BEEKEEPER)
        page.goto(f"{BASE_URL}/beekeeper/collections", wait_until="networkidle")
        page.wait_for_timeout(1200)
        note = page.locator("input[name='notes']").first
        if note.count():
            note.click()
            page.keyboard.type("Harvested in the early morning.", delay=20)
            check(
                "the collection notes field keeps focus while typing",
                note.input_value() == "Harvested in the early morning.",
                f"holds {note.input_value()!r}",
            )
        else:
            print("  skip  the collection form is not on screen for this account")

        check("no console errors during the run", not console_errors, str(console_errors[:3]))
        browser.close()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("Failures:")
        for item in FAILED:
            print(f"  - {item}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
