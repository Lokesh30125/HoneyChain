"""Phase 2 end-to-end smoke test, driven by a real browser.

A *verification script*, not part of the pytest suite: it needs PostgreSQL, the
API, the Vite dev server and Playwright's Chromium. It walks the Phase 2
acceptance criteria the way a person would — through the UI, over the Vite
proxy, against the real database:

  1. Registration as a beekeeper, including the apiary section
  2. Phone-number validation (client-side, before the request is sent)
  3. Duplicate e-mail reported on the field
  4. Beekeeper profile edit persisting across a reload
  5. KVIC officer verifying a beekeeper, with remarks and history
  6. Cluster management screen (KVIC)
  7. Administrator: user directory, beekeeper directory, audit log
  8. Consumers blocked from the administration area

Run::

    cd backend && .venv/bin/uvicorn app.main:app --port 8000    # terminal 1
    cd frontend && npm run dev                                  # terminal 2
    cd backend && .venv/bin/python tests/browser_smoke_phase2.py

Exit code is 0 only if every check passes. The account it registers is left in
the development database on purpose (the script prints its e-mail) so the run
can be inspected afterwards.
"""

from __future__ import annotations

import os
import re
import sys
import time

from playwright.sync_api import Page, sync_playwright

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:5173")
ADMIN = (
    os.getenv("SMOKE_ADMIN_EMAIL", "admin@honeychain.example.com"),
    os.getenv("SMOKE_ADMIN_PASSWORD", "AdminSecure123"),
)
KVIC = (
    os.getenv("SMOKE_KVIC_EMAIL", "kvic@honeychain.example.com"),
    os.getenv("SMOKE_KVIC_PASSWORD", "KvicSecure123"),
)
CONSUMER = (
    os.getenv("SMOKE_CONSUMER_EMAIL", "consumer@honeychain.example.com"),
    os.getenv("SMOKE_CONSUMER_PASSWORD", "ConsumerPass123"),
)
HEADLESS = os.getenv("SMOKE_HEADLESS", "true").lower() != "false"

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


def visible(page: Page, text: str, timeout: int = 10000) -> bool:
    try:
        page.wait_for_selector(f"text={text}", timeout=timeout, state="visible")
        return True
    except Exception:
        return False


def go(page: Page, path: str) -> None:
    page.goto(f"{BASE_URL}{path}", wait_until="networkidle")


def fill(page: Page, selector: str, value: str) -> None:
    """Fill a controlled React input with real keystrokes.

    `page.fill()` sets the DOM value directly; React's onChange never fires, so
    the form state stays empty and the submit button stays disabled. Typing
    character by character keeps the form and the DOM in step.
    """
    field = page.locator(selector)
    field.click()
    field.press("Control+a")
    field.press_sequentially(value, delay=8)


def sign_in(page: Page, email: str, password: str) -> None:
    """Sign in as a different account, clearing any stored session first."""
    go(page, "/about")
    page.evaluate("window.sessionStorage.clear()")
    go(page, "/login")
    fill(page, "input[name='email']", email)
    fill(page, "input[name='password']", password)
    page.click("button[type='submit']")
    page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
    page.wait_for_load_state("networkidle")


def scenario_registration(page: Page) -> str:
    """[1] Register a beekeeper through the UI, apiary section included."""
    print("\n[1] Registration as a beekeeper")
    stamp = f"{int(time.time())}"
    email = f"smoke.beekeeper.{stamp}@honeychain.example.com"
    phone = f"9{stamp[-9:]}"

    go(page, "/register")
    fill(page, "input[name='name']", "Smoke Test Beekeeper")
    fill(page, "input[name='email']", email)
    fill(page, "input[name='phone']", phone)
    fill(page, "input[name='state']", "Andhra Pradesh")
    fill(page, "input[name='district']", "Guntur")
    fill(page, "input[name='beekeeper.village']", "Tenali")
    fill(page, "input[name='beekeeper.mandal']", "Tenali")
    fill(page, "input[name='beekeeper.pincode']", "522201")
    fill(page, "input[name='beekeeper.experienceYears']", "6")
    fill(page, "input[name='beekeeper.numberOfHives']", "14")
    page.select_option("select[name='beekeeper.beeSpecies']", "Apis cerana indica")
    fill(page, "input[name='password']", "SmokePass123")
    fill(page, "input[name='confirmPassword']", "SmokePass123")
    page.check("input[name='acceptedTerms']")
    page.click("button[type='submit']")
    try:
        page.wait_for_url(lambda url: "/register" not in url, timeout=20000)
    except Exception:  # noqa: BLE001 - reported by the check below
        pass
    page.wait_for_load_state("networkidle")

    check("registration redirects into the beekeeper workspace", "/beekeeper" in page.url, page.url)
    check("the beekeeper ID is announced", visible(page, "Beekeeper ID") or visible(page, "BKR-"))

    go(page, "/beekeeper/profile")
    check("apiary profile shows a generated beekeeper code", bool(re.search(r"BKR-[A-Z]{3}-\d{5}", page.content())))
    check("new registrations start Pending", visible(page, "Pending"))
    return email


def scenario_phone_validation(page: Page) -> None:
    """[2] The e-mail reported bug: a phone the API would reject is caught here."""
    print("\n[2] Phone validation happens on the field, not at the API")
    go(page, "/register")
    fill(page, "input[name='name']", "Phone Validation Probe")
    fill(page, "input[name='email']", f"smoke.phone.{int(time.time())}@honeychain.example.com")
    fill(page, "input[name='phone']", "91 98765 43210")  # country code without '+'
    fill(page, "input[name='password']", "SmokePass123")
    fill(page, "input[name='confirmPassword']", "SmokePass123")
    page.check("input[name='acceptedTerms']")
    page.click("button[type='submit']")
    page.wait_for_timeout(600)

    check(
        "the phone field explains what is accepted",
        visible(page, "10-digit mobile number", timeout=4000),
    )
    check("the form stays on the page instead of failing at the API", "/register" in page.url, page.url)
    check(
        "no generic 'Invalid request' banner is shown for this",
        not visible(page, "Invalid request", timeout=1500),
    )


def scenario_duplicate_email(page: Page, email: str) -> None:
    """[3] A duplicate e-mail is reported against the e-mail field."""
    print("\n[3] Duplicate e-mail is reported on the field")
    go(page, "/register")
    fill(page, "input[name='name']", "Duplicate Probe")
    fill(page, "input[name='email']", email)
    fill(page, "input[name='password']", "SmokePass123")
    fill(page, "input[name='confirmPassword']", "SmokePass123")
    page.check("input[name='acceptedTerms']")
    page.click("button[type='submit']")

    check("the banner names the field that failed", visible(page, "Email:", timeout=8000))
    check("the banner explains the conflict", visible(page, "already exists", timeout=4000))


def scenario_beekeeper_profile(page: Page, email: str) -> None:
    """[4] The apiary edit persists across a reload (PostgreSQL round trip)."""
    print("\n[4] Beekeeper profile edit persists")
    sign_in(page, email, "SmokePass123")
    go(page, "/beekeeper/profile")
    check("beekeeper reaches their own apiary profile", visible(page, "Number of hives"))

    fill(page, "input[name='numberOfHives']", "31")
    page.click("button:has-text('Save changes')")
    check("saving reports success", visible(page, "saved", timeout=8000) or visible(page, "updated", timeout=4000))

    page.reload(wait_until="networkidle")
    check("the new hive count survives a reload", page.input_value("input[name='numberOfHives']") == "31")


def scenario_kvic_verification(page: Page, email: str) -> None:
    """[5] A KVIC officer verifies the new beekeeper, with remarks."""
    print("\n[5] KVIC officer verifies a beekeeper")
    sign_in(page, *KVIC)
    check("KVIC officer lands on the KVIC workspace", "/kvic" in page.url, page.url)

    go(page, "/kvic/beekeepers")
    check("the beekeeper directory renders", visible(page, "Beekeepers"))

    fill(page, "input[name='search']", email)
    page.click("button:has-text('Apply')")
    page.wait_for_timeout(800)
    check("search finds the newly registered beekeeper", visible(page, email, timeout=8000))

    page.click("button:has-text('View')")
    check("the detail panel opens", visible(page, "Record decision", timeout=8000))
    page.click("button:has-text('Record decision')")

    page.wait_for_selector("select[name='status']", timeout=8000)
    page.select_option("select[name='status']", "VERIFIED")
    fill(page, "input[name='remarks']", "Smoke test: verified after reviewing the apiary details.")
    page.click("button:has-text('Save decision')")
    page.wait_for_timeout(1200)

    check("the decision is saved", visible(page, "verified", timeout=8000) or visible(page, "Verified", timeout=4000))
    page.reload(wait_until="networkidle")
    check("the verification status persisted", visible(page, "Verified", timeout=8000))


def scenario_clusters(page: Page) -> None:
    """[6] Cluster management renders real cluster data."""
    print("\n[6] Cluster management (KVIC)")
    go(page, "/kvic/clusters")
    check("cluster screen renders", visible(page, "Clusters"))
    check("a cluster code is listed", bool(re.search(r"KVIC-[A-Z]{3}-\d{3}", page.content())))


def scenario_admin(page: Page, email: str) -> None:
    """[7] Administrator directories and the audit log."""
    print("\n[7] Administrator directory, beekeepers and audit log")
    sign_in(page, *ADMIN)
    check("admin lands on the administration workspace", "/admin" in page.url, page.url)

    go(page, "/admin/users")
    fill(page, "input[name='search']", email)
    page.click("button:has-text('Apply')")
    page.wait_for_timeout(800)
    check("user directory finds the new account", visible(page, email, timeout=8000))

    go(page, "/admin/beekeepers")
    check("beekeeper directory renders for the admin", visible(page, "Beekeepers"))

    go(page, "/admin/audit-logs")
    check("audit log renders", visible(page, "Audit"))
    check(
        "registration is recorded",
        visible(page, "User Registered", timeout=8000) or visible(page, "USER_REGISTERED", timeout=2000),
    )
    check("the audit screen explains redaction and immutability", visible(page, "never", timeout=4000))


def scenario_consumer_is_blocked(page: Page) -> None:
    """[8] A consumer cannot reach administration screens.

    Phase 6 answers this with redirection rather than a notice: the route guard
    reads the central role→navigation configuration and returns the user to their
    own workspace, so a URL that does not belong to them is not reachable at all.
    """
    print("\n[8] Consumers are refused the administration area")
    sign_in(page, *CONSUMER)
    go(page, "/admin/users")
    page.wait_for_timeout(900)
    check(
        "the administration URL returns the consumer to their own workspace",
        "/consumer" in page.url and "/admin" not in page.url,
        f"ended on {page.url}",
    )
    check(
        "and no administration link was ever offered to them",
        "Users" not in page.inner_text("nav[aria-label='Primary']"),
    )


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)
        context = browser.new_context(viewport={"width": 1360, "height": 950})
        page = context.new_page()

        def _record_console(message) -> None:
            if message.type != "error":
                return
            # 401/403 responses are the point of the permission scenarios.
            if "401" in message.text or "403" in message.text or "409" in message.text:
                return
            CONSOLE_ERRORS.append(message.text)

        page.on("console", _record_console)
        page.on("pageerror", lambda error: CONSOLE_ERRORS.append(f"pageerror: {error}"))

        try:
            email = scenario_registration(page)
            scenario_phone_validation(page)
            scenario_duplicate_email(page, email)
            scenario_beekeeper_profile(page, email)
            scenario_kvic_verification(page, email)
            scenario_clusters(page)
            scenario_admin(page, email)
            scenario_consumer_is_blocked(page)
            page.screenshot(path=os.getenv("SMOKE_SCREENSHOT", "/tmp/honeychain-phase2-smoke.png"))
        finally:
            browser.close()

    print("\n" + "=" * 72)
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if CONSOLE_ERRORS:
        print(f"\nUnexpected browser console errors ({len(CONSOLE_ERRORS)}):")
        for entry in CONSOLE_ERRORS[:10]:
            print(f"  - {entry}")
    if FAILED:
        print("\nFailures:")
        for entry in FAILED:
            print(f"  - {entry}")
    return 1 if FAILED or CONSOLE_ERRORS else 0


if __name__ == "__main__":
    raise SystemExit(main())
