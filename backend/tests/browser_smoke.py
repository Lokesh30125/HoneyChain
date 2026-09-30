"""End-to-end smoke test of the running application, driven by a real browser.

This is a *verification script*, not part of the pytest suite: it needs the API,
the Vite dev server and PostgreSQL to be running, plus Playwright's Chromium.
It exists so the Phase 1 acceptance criteria can be checked the way a person
would experience them — in a browser, through the Vite proxy, against the real
database.

Run::

    # terminal 1
    cd backend && .venv/bin/uvicorn app.main:app --port 8000
    # terminal 2
    cd frontend && npm run dev
    # then
    cd backend && .venv/bin/python tests/browser_smoke.py

Exit code is 0 only if every scenario passes.
"""

from __future__ import annotations

import os
import sys
import uuid

from playwright.sync_api import Page, sync_playwright

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:5173")
ADMIN_EMAIL = os.getenv("SMOKE_ADMIN_EMAIL", "admin@honeychain.example.com")
ADMIN_PASSWORD = os.getenv("SMOKE_ADMIN_PASSWORD", "AdminSecure123")
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


def visible(page: Page, text: str, timeout: int = 8000) -> bool:
    try:
        page.wait_for_selector(f"text={text}", timeout=timeout, state="visible")
        return True
    except Exception:
        return False


def go(page: Page, path: str) -> None:
    page.goto(f"{BASE_URL}{path}", wait_until="networkidle")


# --------------------------------------------------------------------------- #
def scenario_public_site(page: Page) -> None:
    print("\n[1] Public site loads and reports API connectivity")
    go(page, "/")

    check("landing page renders the hero headline",
          visible(page, "Blockchain-powered honey traceability"))
    check("pipeline stages are shown",
          visible(page, "AI assistance") and visible(page, "Blockchain record"))
    check("problem section is present", visible(page, "The problem"))
    check("technology section is present", visible(page, "layered architecture"))
    check("responsible wording is used (no purity guarantee)",
          not page.evaluate("() => document.body.innerText.includes('100% authentic')"))

    # The footer status badge proves the browser can reach the API through the proxy.
    page.wait_for_selector("text=API status")
    footer_text = page.inner_text("footer")
    check("footer reports the API as online (frontend → backend → DB)",
          "Online" in footer_text, f"— footer said: {footer_text[-200:]!r}")

    go(page, "/how-it-works")
    # The labels are the backend's own `UserRole.label` values, so this reads the
    # same text the API publishes rather than a second wording invented here.
    check("how-it-works page lists all ten roles",
          all(role in page.inner_text("body") for role in
              ["Administrator", "Beekeeper", "Collection centre", "Processor", "Lab technician",
               "Packaging unit", "Distributor", "Retailer", "Consumer", "KVIC officer"]))

    go(page, "/about")
    check("about page states the release scope honestly",
          visible(page, "What this release does and does not do"))
    go(page, "/contact")
    check("contact page renders", visible(page, "Talk to the HoneyChain team"))


def scenario_protected_route(page: Page) -> None:
    print("\n[2] Protected routes redirect anonymous visitors")
    go(page, "/dashboard")
    check("anonymous /dashboard redirects to /login", "/login" in page.url, f"— at {page.url}")
    check("login form is shown", visible(page, "Sign in to HoneyChain"))


def scenario_registration(page: Page) -> str:
    print("\n[3] Registration through the browser")
    email = f"smoke.{uuid.uuid4().hex[:8]}@honeychain.example.com"
    # Phones are unique in the database, so each run needs its own number.
    phone = f"9{uuid.uuid4().int % 10**9:09d}"
    go(page, "/register")

    page.fill("input[name='name']", "Smoke Test Beekeeper")
    page.fill("input[name='email']", email)
    page.fill("input[name='phone']", phone)
    page.select_option("select[name='role']", "BEEKEEPER")
    page.fill("input[name='state']", "Andhra Pradesh")
    page.fill("input[name='district']", "Guntur")
    page.fill("input[name='password']", "SmokePass123")
    page.fill("input[name='confirmPassword']", "SmokePass123")
    page.check("input[name='acceptedTerms']")

    # Client-side validation should trigger for a short password before submit.
    page.fill("input[name='password']", "abc")
    page.fill("input[name='confirmPassword']", "abc")
    page.click("button[type='submit']")
    check("weak password is rejected client-side", visible(page, "Use at least 8 characters"))

    page.fill("input[name='password']", "SmokePass123")
    page.fill("input[name='confirmPassword']", "SmokePass123")
    page.click("button[type='submit']")

    page.wait_for_url("**/beekeeper", timeout=15000)
    check("registration redirects to the beekeeper workspace", "/beekeeper" in page.url)

    # The dashboard fetches the beekeeper record, hive, IoT, batch and laboratory
    # panels after it mounts. Wait for the registration card itself — "BKR-" alone
    # also appears in the audit timeline, so it would match before the card does.
    visible(page, "My beekeeper profile", timeout=10000)
    body = page.inner_text("body")
    check("workspace greets the new user",
          "Smoke" in body and "Beekeeper" in body)
    # Phase 2 replaced the placeholder beekeeper tiles with the beekeeper's own
    # record; Phases 3–5 then replaced the workspace itself. The two checks below
    # still assert the same two things — that future modules are named as future
    # work rather than mocked up, and that the record shown is the real one.
    # Phase 6 replaced the last placeholder with a real beekeeper dashboard: the
    # checks below still assert the same two things — that what is shown is the
    # beekeeper's own record rather than a mock-up, and that modules which have
    # shipped are present rather than described as future work.
    check("the beekeeper dashboard shows their own workspace",
          "Beekeeper workspace" in body or "BKR-" in body)
    check("the workspace links only modules the beekeeper works in",
          "My Hives" in body and "Honey Batches" in body and "Users" not in body)
    # The card's labels are styled uppercase, so compare case-insensitively.
    check("the beekeeper record is real data, not a placeholder",
          "bkr-" in body.lower() and "apiary registration" in body.lower(),
          f"[url={page.url} len={len(body)}]")
    check("no placeholder screen is reachable from the navigation",
          "coming soon" not in body.lower() and "not your workspace" not in body.lower())
    return email


def scenario_session_persistence(page: Page) -> None:
    print("\n[4] Session survives a page reload (token re-validated via /auth/me)")
    page.reload(wait_until="networkidle")
    check("still authenticated after reload", "/beekeeper" in page.url)


def scenario_dashboard_and_navigation(page: Page) -> None:
    print("\n[5] Dashboard shell, sidebar and role guarding")
    go(page, "/dashboard")
    body = page.inner_text("body")
    check("dashboard shows the welcome heading", "Good" in body and "Smoke" in body)
    check("dashboard shows the signed-in role", "Beekeeper" in body)
    check("dashboard reports API connectivity", "Connected" in body)
    check("sidebar exposes profile and logout",
          visible(page, "My Profile") and visible(page, "Logout"))

    go(page, "/profile")
    check("profile page loads with the user's details",
          visible(page, "My profile") and "smoke." in page.inner_text("body"))

    # Phase 2 split the page: location lives under "Save details", the account
    # name/phone under "Save account details".
    page.fill("input[name='district']", "Krishna")
    page.click("button:has-text('Save details')")
    check("profile update is confirmed", visible(page, "Profile details saved"))

    go(page, "/admin")
    page.wait_for_timeout(900)
    check("beekeeper typing the admin URL is returned to their own workspace",
          "/beekeeper" in page.url and "/admin" not in page.url,
          f"ended on {page.url}")


def open_login_page(page: Page) -> None:
    """Reach the sign-in form the way a visitor does: from the public site.

    Note: `goto("/login")` is not equivalent. React Router keeps the previous
    history entry's state, so a same-URL navigation can still carry the
    `from` location that ProtectedRoute stored, which changes where the user is
    sent after signing in. Clicking through the header clears it naturally.
    """
    go(page, "/about")
    page.click("header >> text=Login")
    page.wait_for_url("**/login", timeout=10000)


def sign_out_via_ui(page: Page) -> None:
    """Sign out through the sidebar menu and its confirmation dialog."""
    go(page, "/dashboard")
    page.click("aside >> text=Logout")
    page.wait_for_selector("text=Sign out of HoneyChain?", timeout=8000)
    page.click("div[role='dialog'] button:has-text('Sign out')")
    page.wait_for_url("**/login", timeout=15000)


def scenario_logout_and_login(page: Page, email: str) -> None:
    print("\n[6] Logout confirmation, and login restoring the requested page")
    go(page, "/dashboard")
    page.click("aside >> text=Logout")
    check("logout asks for confirmation", visible(page, "Sign out of HoneyChain?"))

    page.click("div[role='dialog'] button:has-text('Sign out')")
    page.wait_for_url("**/login", timeout=15000)
    check("logout returns to the login page", "/login" in page.url)

    go(page, "/dashboard")
    check("session is gone after logout", "/login" in page.url)

    page.fill("input[name='email']", email)
    page.fill("input[name='password']", "SmokePass123")
    page.click("button[type='submit']")
    # The visitor asked for /dashboard before signing in, so that is where they
    # are returned — not their role home.
    page.wait_for_url("**/dashboard", timeout=15000)
    check("login returns the user to the page they originally requested",
          "/dashboard" in page.url)


def scenario_role_home_routing(page: Page, email: str) -> None:
    print("\n[7] A fresh sign-in lands on the role workspace")
    sign_out_via_ui(page)
    open_login_page(page)

    page.fill("input[name='email']", email)
    page.fill("input[name='password']", "SmokePass123")
    page.click("button[type='submit']")
    page.wait_for_url("**/beekeeper", timeout=15000)
    check("beekeeper lands on the beekeeper workspace", "/beekeeper" in page.url)


def scenario_wrong_password(page: Page) -> None:
    print("\n[8] Invalid credentials show a safe error")
    sign_out_via_ui(page)
    open_login_page(page)

    page.fill("input[name='email']", "nobody@honeychain.example.com")
    page.fill("input[name='password']", "TotallyWrong123")
    page.click("button[type='submit']")
    check("invalid credentials error is displayed", visible(page, "Invalid email or password"))
    check("the error does not reveal whether the account exists",
          "nobody" not in page.inner_text("div[role='alert']"))


def scenario_admin_workspace(page: Page) -> None:
    print("\n[9] Administrator workspace with live data")
    open_login_page(page)
    page.fill("input[name='email']", ADMIN_EMAIL)
    page.fill("input[name='password']", ADMIN_PASSWORD)
    page.click("button[type='submit']")
    page.wait_for_url("**/admin", timeout=15000)
    check("admin lands on the admin workspace", "/admin" in page.url)

    check("platform summary numbers are rendered", visible(page, "Registered accounts"))
    check("module status is reported", visible(page, "Module implementation status"))
    # These two assertions wait: both the chart and the directory render after
    # their API calls resolve, not on first paint.
    check("account directory lists real accounts",
          visible(page, "Smoke Test Beekeeper", timeout=15000))
    check("role chart is rendered from live data (Recharts SVG present)",
          page.wait_for_selector("svg.recharts-surface", timeout=15000) is not None)


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)
        context = browser.new_context(viewport={"width": 1360, "height": 900})
        page = context.new_page()

        # A 401 is logged by the browser for the deliberate invalid-credentials
        # scenario; every other console error is a real problem.
        def _record_console(message) -> None:
            if message.type != "error":
                return
            if "401" in message.text and "Unauthorized" in message.text:
                CONSOLE_ERRORS.append(f"expected (invalid sign-in test): {message.text}")
                return
            CONSOLE_ERRORS.append(f"unexpected: {message.text}")

        page.on("console", _record_console)
        page.on("pageerror", lambda error: CONSOLE_ERRORS.append(f"pageerror: {error}"))

        try:
            scenario_public_site(page)
            scenario_protected_route(page)
            email = scenario_registration(page)
            scenario_session_persistence(page)
            scenario_dashboard_and_navigation(page)
            scenario_logout_and_login(page, email)
            scenario_role_home_routing(page, email)
            scenario_wrong_password(page)
            scenario_admin_workspace(page)
            # Written outside the repository by default so a verification run
            # does not leave artefacts in the working tree.
            page.screenshot(
                path=os.getenv("SMOKE_SCREENSHOT", "/tmp/honeychain-smoke.png"),
                full_page=False,
            )
        finally:
            browser.close()

    print("\n" + "=" * 72)
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    unexpected = [entry for entry in CONSOLE_ERRORS if entry.startswith("unexpected")]
    if CONSOLE_ERRORS:
        print("\nBrowser console messages:")
        for entry in CONSOLE_ERRORS:
            print(f"  - {entry}")
    if FAILED:
        print("\nFailures:")
        for entry in FAILED:
            print(f"  - {entry}")
        return 1
    if unexpected:
        print("\nUnexpected console errors were reported.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
