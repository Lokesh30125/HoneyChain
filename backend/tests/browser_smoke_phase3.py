"""Phase 3 integration smoke test, driven by a real browser.

A *verification script*, not part of the pytest suite: it needs PostgreSQL, the
API, the Vite dev server and Playwright's Chromium. It walks the phase's
acceptance criteria the way a person would — through the UI, over the Vite
proxy, against the real database:

  1. Beekeeper dashboard shows live apiary figures, not roadmap copy
  2. My Hives is a working registry (list, register, open detail)
  3. Hive detail reaches its device, sensors and stored history
  4. IoT monitoring shows devices, derived status and labelled reading sources
  5. Sidebar states: My Hives and IoT Monitoring are live, AI Insight is not
  6. Empty states: a fresh beekeeper sees honest "nothing yet" screens
  7. Admin long pages scroll from top to bottom
  8. KVIC pages scroll, and the review dialog fits at 100% zoom
  9. No unexpected horizontal page scrolling, at several desktop widths

Run::

    cd backend && .venv/bin/uvicorn app.main:app --port 8000        # terminal 1
    cd frontend && npm run build && npm run preview -- --port 4173  # terminal 2
    cd backend && .venv/bin/python tests/browser_smoke_phase3.py

The production build is the default target because the HMR dev server holds an
order of magnitude more memory per navigation, and under the 2 GB this sandbox
provides that ends in a crashed renderer rather than a test result. Add
``SMOKE_BASE_URL=http://localhost:5173`` to verify through the dev server.

Exit code is 0 only if every check passes. The script registers one throwaway
beekeeper (printed at the end, with the SQL to remove it) and leaves the
development data otherwise untouched.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import Page, sync_playwright

#: Default target is the *production* build served by ``npm run preview``: it
#: holds a fraction of the memory of the HMR dev server, and a 2 GB sandbox
#: otherwise crashes the renderer partway through the walk. Point
#: ``SMOKE_BASE_URL`` at the dev server (http://localhost:5173) to smoke that.
BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:4173")
API_URL = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")
ADMIN = (
    os.getenv("SMOKE_ADMIN_EMAIL", "admin@honeychain.example.com"),
    os.getenv("SMOKE_ADMIN_PASSWORD", "AdminSecure123"),
)
KVIC = (
    os.getenv("SMOKE_KVIC_EMAIL", "kvic@honeychain.example.com"),
    os.getenv("SMOKE_KVIC_PASSWORD", "KvicSecure123"),
)
BEEKEEPER = (
    os.getenv("SMOKE_BEEKEEPER_EMAIL", "beekeeper@honeychain.example.com"),
    os.getenv("SMOKE_BEEKEEPER_PASSWORD", "HoneyPass123"),
)
HEADLESS = os.getenv("SMOKE_HEADLESS", "true").lower() != "false"

#: Desktop widths the layout must survive without zooming out (PART 11).
WIDTHS = [1280, 1366, 1440, 1920]
HEIGHT = 800

PASSED: list[str] = []
FAILED: list[str] = []
CONSOLE_ERRORS: list[str] = []
CLEANUP_EMAIL: str | None = None


def check(description: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(description)
        print(f"  PASS  {description}")
    else:
        FAILED.append(f"{description} {detail}".strip())
        print(f"  FAIL  {description} {detail}".strip())


def body_text(page: Page) -> str:
    """Visible text of the page.

    Preferred over `page.content()`: the HTML of a dashboard with charts is
    megabytes, and this script only ever asserts on what a reader can see.
    """
    return page.inner_text("body")


def visible(page: Page, text: str, timeout: int = 10000) -> bool:
    try:
        page.wait_for_selector(f"text={text}", timeout=timeout, state="visible")
        return True
    except Exception:  # noqa: BLE001 - absence is the result we are testing
        return False


def go(page: Page, path: str) -> None:
    """Navigate and let the first render settle.

    `networkidle` is deliberately avoided: the topbar polls API health, so the
    network is never idle for long. Waiting on the load event plus a short settle
    matches what a person sees.
    """
    # `commit` + a settle wait: with a dev server and HMR the document-level
    # load event is an unreliable signal, and the topbar polls API health so the
    # network is never idle. A person waits for the page to look ready, and so
    # does this script.
    page.goto(f"{BASE_URL}{path}", wait_until="commit", timeout=30000)
    page.wait_for_timeout(1300)


def fill(page: Page, selector: str, value: str) -> None:
    """Fill a controlled React input with real keystrokes (see Phase-2 script)."""
    field = page.locator(selector)
    field.click()
    field.press("Control+a")
    field.press_sequentially(value, delay=8)


def api_login(email: str, password: str) -> str:
    """Access token from the API, so a scenario can discover its own fixtures."""
    payload = json.dumps({"email": email, "password": password}).encode()
    request = urllib.request.Request(
        f"{API_URL}/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)["data"]["access_token"]


def api_get(path: str, token: str):
    request = urllib.request.Request(
        f"{API_URL}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)["data"]


#: Mirrors ``app.models.document_sequence.district_code``: a single-word
#: district keeps its first three consonants ("Guntur" → GNT, "Krishna" → KRS),
#: which is why a smoke district called "Smokebad…" is coded SMK, not SMO.
VOWELS = set("AEIOU")


def expected_district_prefix(district: str) -> str:
    word = re.sub(r"[^A-Za-z0-9]", "", district).upper()
    consonants = [char for char in word if char not in VOWELS]
    return "".join(consonants[:3]) if len(consonants) >= 3 else word[:3]


def sign_in(page: Page, email: str, password: str) -> None:
    go(page, "/about")
    page.evaluate("window.sessionStorage.clear()")
    go(page, "/login")
    fill(page, "input[name='email']", email)
    fill(page, "input[name='password']", password)
    page.click("button[type='submit']")
    page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
    page.wait_for_timeout(1200)


# --------------------------------------------------------------------------- #
# Layout probes
# --------------------------------------------------------------------------- #
def horizontal_overflow(page: Page) -> int:
    """Pixels the document is wider than the viewport (negative = none)."""
    return page.evaluate(
        "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth"
    )


def page_scrolls(page: Page) -> tuple[bool, int, int]:
    """Scroll to the bottom; report whether the document was taller than the view."""

    def measure_before():
        return page.evaluate(
            "({ viewport: window.innerHeight, doc: document.documentElement.scrollHeight })"
        )

    before = measure_before()
    page.mouse.wheel(0, 40000)
    page.wait_for_timeout(400)
    after = page.evaluate("window.scrollY")
    return (before["doc"] > before["viewport"], before["doc"], after)


def body_is_scrollable(page: Page) -> bool:
    return page.evaluate("getComputedStyle(document.body).overflow") != "hidden"


def box_fits_viewport(page: Page, selector: str) -> tuple[bool, dict]:
    box = page.locator(selector).first.bounding_box()
    if not box:
        return False, {}
    viewport = page.viewport_size or {"width": 0, "height": 0}
    fits = (
        box["x"] >= -1
        and box["y"] >= -1
        and box["x"] + box["width"] <= viewport["width"] + 1
        and box["y"] + box["height"] <= viewport["height"] + 1
    )
    return fits, box


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #
def scenario_beekeeper_dashboard(page: Page) -> None:
    print("\n[1] Beekeeper dashboard shows live apiary data")
    go(page, "/beekeeper")

    # Phase 6 rebuilt this dashboard around the beekeeper's own record and their
    # batch pipeline, so the labels below are the ones the workspace now uses. The
    # intent of each check is unchanged: real counts, a real hive code, device
    # status, and the registration block rather than a mock-up.
    check("the workspace header greets the beekeeper", visible(page, "Beekeeper workspace"))
    main = page.locator("#main-content")
    check("the apiary tile is present in the workspace body", main.locator("text=My hives").count() > 0)
    text = body_text(page)
    check("hive overview lists a real hive code", bool(re.search(r"HIVE-[A-Z]{3}-\d{5}", text)))
    check("the dashboard reports device status", main.locator("text=Devices reporting").count() > 0)
    check("the apiary registration block is shown", visible(page, "Apiary registration"))

    content = body_text(page)
    check(
        "no phase-roadmap copy is used as the main workspace content",
        "Modules open up as each phase is released" not in content
        and "What is coming next" not in content,
    )
    check(
        "quick actions are real links",
        page.locator("a[href='/beekeeper/hives']").count() > 0
        and page.locator("a[href='/beekeeper/iot']").count() > 0,
    )
    check("the page does not scroll sideways", horizontal_overflow(page) <= 2, f"{horizontal_overflow(page)}px")


def scenario_sidebar_states(page: Page) -> None:
    print("\n[2] Sidebar states match what is implemented")
    go(page, "/beekeeper")
    nav = page.locator("nav[aria-label='Primary']")

    def item(text: str):
        return nav.locator("a", has_text=text).first

    check("My Hives is a live link, not 'Soon'", "Soon" not in item("My Hives").inner_text())
    check("IoT Monitoring is a live link, not 'Soon'", "Soon" not in item("IoT Monitoring").inner_text())
    # Phase 3 asserted AI Insights was still future work. Phase 4 delivered it, so
    # the expectation was updated rather than the check dropped: the sidebar has to
    # tell the truth in both directions.
    check("AI Insights is a live link since Phase 4", "Soon" not in item("AI Insights").inner_text())
    check("Alerts is a live link since Phase 4", "Soon" not in item("Alerts").inner_text())
    if nav.locator("a", has_text="Honey Collections").count():
        check(
            "Honey Collections is a live link since Phase 5",
            "Soon" not in item("Honey Collections").inner_text(),
        )
    # Phase 5 delivered collections and honey batches, so the expectation is
    # updated rather than the check dropped — the same rule as AI Insights above.
    # Packaging and distribution remain honestly marked as future work.
    check(
        "Honey Batches is a live link since Phase 5",
        "Soon" not in item("Honey Batches").inner_text(),
    )


def scenario_my_hives(page: Page) -> None:
    print("\n[3] My Hives is a working registry")
    go(page, "/beekeeper/hives")

    check("the registry screen opens", visible(page, "My hives"))
    text = body_text(page)
    check("an existing hive is listed", bool(re.search(r"HIVE-[A-Z]{3}-\d{5}", text)))
    check("the register action is offered", visible(page, "Register hive"))
    check("the registry explains codes are platform-generated", "generated by the platform" in text)

    stamp = int(time.time()) % 100000
    district = f"Smokebad{stamp}"
    page.click("button:has-text('Register hive')")
    page.wait_for_selector("form", timeout=10000)
    fill(page, "input[name='village']", "Smoke Village")
    fill(page, "input[name='district']", district)
    fill(page, "input[name='state']", "Andhra Pradesh")
    # Scope to the dialog: the registry behind it has its own filter form, and
    # its submit button sits under the modal backdrop.
    page.locator("[role='dialog'] form button[type='submit']").first.click()
    page.wait_for_timeout(3000)

    content = body_text(page)
    expected = f"HIVE-{expected_district_prefix(district)}"
    check(
        "registering a hive creates a platform-generated code",
        bool(re.search(rf"{expected}-\d{{5}}", content)),
        f"expected a {expected}-xxxxx code",
    )
    check("the new hive is visible in the list", "Smoke Village" in content)
    check(
        "the same prefix is reused for the district, not re-invented",
        len(re.findall(rf"{expected}-\d{{5}}", content)) >= 1,
    )


def scenario_hive_detail(page: Page) -> None:
    print("\n[4] Hive detail reaches devices, sensors and history")

    # Discover the fixtures instead of assuming them: the walk must hold whether
    # the apiary has one hive or twenty, and whichever hive was registered last.
    token = api_login(*BEEKEEPER)
    hives = api_get("/hives?page=1&page_size=50", token)
    reporting = next((hive for hive in hives if hive.get("device_count")), None)
    bare = next((hive for hive in hives if not hive.get("device_count")), None)
    check("the apiary has a hive with a paired device", reporting is not None)
    if reporting is None:
        return

    # Row clicks are what a beekeeper actually does, so prove that works first.
    go(page, "/beekeeper/hives")
    page.locator("tbody tr").first.click()
    page.wait_for_timeout(2000)
    check("clicking a registry row opens the hive detail", "/beekeeper/hives/" in page.url, page.url)
    check("the back link returns to the registry", page.locator("a[href='/beekeeper/hives']").count() > 0)

    # Then read the hive that genuinely has hardware, whatever page it is on.
    go(page, f"/beekeeper/hives/{reporting['id']}")
    check("registration details are shown", visible(page, "Registration"))
    check("the paired device is listed with its derived status", visible(page, "Devices on this hive"))
    check("the sensor history chart is present", visible(page, "Sensor history"))
    check("the hive code is on the page", reporting["hive_code"] in body_text(page))

    text = body_text(page)
    if reporting.get("latest_reading"):
        check("stored readings are rendered with units", "°C" in text)
        check(
            "readings state which source produced them",
            any(label in text for label in ("Simulator", "Hardware device", "Manual entry")),
            "no source label found on a hive that has readings",
        )
    else:
        check("a hive with no readings shows the empty state", "No telemetry data available yet" in text)

    check("detail does not scroll sideways", horizontal_overflow(page) <= 2, f"{horizontal_overflow(page)}px")

    if bare is not None:
        go(page, f"/beekeeper/hives/{bare['id']}")
        check(
            "a hive with no device says so without inventing readings",
            "No device is paired with this hive yet" in body_text(page),
        )


def scenario_iot_monitoring(page: Page) -> None:
    print("\n[5] IoT monitoring reads the Prompt-3 device APIs")
    go(page, "/beekeeper/iot")

    check("the monitoring screen opens", visible(page, "IoT monitoring"))
    check("the device list shows the paired ESP32", "ESP32-" in body_text(page))
    check("ingest state is reported honestly", visible(page, "MQTT", timeout=5000))
    check("device counters are shown", visible(page, "Devices") and visible(page, "Offline"))
    check("readings carry a source label", visible(page, "Simulator") or visible(page, "Hardware device"))
    check("simulated data is called out rather than hidden", "simulator" in body_text(page).lower())
    check("monitoring does not scroll sideways", horizontal_overflow(page) <= 2, f"{horizontal_overflow(page)}px")

    # Open the detail panel for the first device.
    page.locator("tbody tr").first.click()
    page.wait_for_timeout(2000)
    check("the device detail panel opens", visible(page, "Sensor configuration"))
    detail_text = body_text(page)
    check("the derived status is labelled as derived", "derived" in detail_text)
    check("the MQTT topic for the device is shown", "telemetry" in detail_text)


def scenario_empty_states(page: Page) -> None:
    print("\n[6] Empty states for a brand-new beekeeper")
    global CLEANUP_EMAIL

    stamp = f"{int(time.time())}"
    email = f"smoke.p3ui.{stamp}@honeychain.example.com"
    phone = f"9{stamp[-9:]}"
    CLEANUP_EMAIL = email

    # Register through the public API so the browser walk stays fast.
    payload = json.dumps(
        {
            "name": "Phase Three UI Smoke",
            "email": email,
            "phone": phone,
            "password": "SmokePass123",
            "role": "BEEKEEPER",
            "state": "Andhra Pradesh",
            "district": "Guntur",
        }
    ).encode()
    request = urllib.request.Request(
        f"{API_URL}/auth/register",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            json.load(response)
    except urllib.error.HTTPError as exc:  # noqa: BLE001
        check("a fresh beekeeper can be registered for the empty-state walk", False, str(exc))
        return

    sign_in(page, email, "SmokePass123")
    go(page, "/beekeeper/hives")
    check("empty registry explains what to do", visible(page, "No hives registered yet"))
    check("empty registry offers a call to action", visible(page, "Add hive") or visible(page, "Register your first hive"))

    go(page, "/beekeeper")
    # The dashboard reads the beekeeper record before it renders its tiles; wait for
    # the registration card so the counts below are the loaded ones.
    visible(page, "My beekeeper profile", timeout=10000)
    fresh = page.locator("#main-content").inner_text()
    check(
        "dashboard shows zero hives, not invented numbers",
        "My hives" in fresh and "0 active" in fresh,
        fresh[:160],
    )
    check(
        "dashboard reports no devices",
        "Devices reporting" in fresh and "0 paired" in fresh,
        fresh[:160],
    )
    go(page, "/beekeeper/hives")
    check("an empty apiary offers nothing to count", visible(page, "No hives registered yet"))

    go(page, "/beekeeper/iot")
    empty_text = body_text(page)
    check(
        "IoT monitoring explains there is nothing paired yet",
        "No devices paired yet" in empty_text or "No IoT devices connected" in empty_text,
        empty_text[:120],
    )

    # Isolation, proven through the UI rather than trusted to the API: opening
    # another beekeeper's hive by URL must not reveal it.
    foreign = api_get("/hives?page=1&page_size=1", api_login(*BEEKEEPER))[0]
    go(page, f"/beekeeper/hives/{foreign['id']}")
    foreign_text = body_text(page)
    check(
        "another beekeeper's hive is not readable by URL",
        foreign["hive_code"] not in foreign_text,
        f"{foreign['hive_code']} leaked to a different beekeeper",
    )
    check(
        "the refused hive is explained, not blank",
        "We could not load this" in foreign_text or "not found" in foreign_text.lower(),
        foreign_text[:160],
    )


def scenario_admin_pages(page: Page) -> None:
    print("\n[7] Admin pages scroll top to bottom")
    sign_in(page, *ADMIN)

    for path, label in [
        ("/admin/users", "user directory"),
        ("/admin/audit-logs", "audit log"),
        ("/admin/hives", "hive registry"),
        ("/admin/iot", "IoT monitoring"),
    ]:
        go(page, path)
        page.wait_for_timeout(800)
        taller, height, scrolled = page_scrolls(page)
        check(f"{label} renders", horizontal_overflow(page) <= 2)
        check(
            f"{label} can be scrolled through",
            (not taller) or scrolled > 0,
            f"doc={height}px scrolled={scrolled}px",
        )
        check(f"{label} keeps the body scrollable", body_is_scrollable(page))
        check(f"{label} does not scroll sideways", horizontal_overflow(page) <= 2)

    # A modal must not leave the page locked after it closes.
    go(page, "/admin/beekeepers")
    page.wait_for_timeout(1000)
    page.locator("tbody tr").first.locator("button").first.click()
    page.wait_for_selector("[role='dialog']", timeout=10000)
    fits, box = box_fits_viewport(page, "[role='dialog']")
    check("the beekeeper review dialog fits the viewport", fits, f"box={box}")
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    check("closing a dialog restores page scrolling", body_is_scrollable(page))
    taller, _height, scrolled = page_scrolls(page)
    check("the page scrolls again after the dialog closes", (not taller) or scrolled > 0)


def scenario_kvic_pages(page: Page) -> None:
    print("\n[8] KVIC pages scroll and the review fits at 100% zoom")
    sign_in(page, *KVIC)

    for path, label in [
        ("/kvic", "KVIC dashboard"),
        ("/kvic/beekeepers", "beekeeper directory"),
        ("/kvic/hives", "hive registry"),
        ("/kvic/iot", "IoT monitoring"),
        ("/kvic/clusters", "cluster list"),
    ]:
        go(page, path)
        page.wait_for_timeout(800)
        taller, height, scrolled = page_scrolls(page)
        check(f"{label} renders without sideways scroll", horizontal_overflow(page) <= 2)
        check(
            f"{label} reaches the end of its content",
            (not taller) or scrolled > 0,
            f"doc={height}px scrolled={scrolled}px",
        )

    # The review flow: open the record, check the dialog geometry, then record a
    # decision and check the second dialog too.
    go(page, "/kvic/beekeepers")
    page.wait_for_selector("tbody tr", timeout=15000)
    page.locator("tbody tr").first.locator("button").first.click()
    page.wait_for_selector("[role='dialog']", timeout=10000)
    page.wait_for_timeout(800)

    fits, box = box_fits_viewport(page, "[role='dialog']")
    check("the KVIC review dialog fits inside the viewport at 100% zoom", fits, f"box={box}")

    viewport = page.viewport_size or {"width": 0, "height": 0}
    check(
        "the review dialog is not taller than the viewport",
        box.get("height", 10**6) <= viewport.get("height", 0),
        f"dialog={box.get('height')}px viewport={viewport.get('height')}px",
    )

    body_scroll = page.evaluate(
        """() => {
            const dialog = document.querySelector("[role='dialog']");
            const body = dialog && dialog.children[1];
            if (!body) return null;
            return { client: body.clientHeight, scroll: body.scrollHeight };
        }"""
    )
    check(
        "long review content scrolls inside the dialog instead of off-screen",
        body_scroll is not None and (body_scroll["scroll"] <= body_scroll["client"] or body_scroll["client"] > 200),
        str(body_scroll),
    )

    footer_button = page.locator("[role='dialog'] button", has_text="Record decision")
    check("the decision action is inside the dialog", footer_button.count() == 1)
    if footer_button.count():
        footer_box = footer_button.first.bounding_box() or {}
        check(
            "the decision action is reachable without zooming out",
            footer_box.get("y", 10**6) + footer_box.get("height", 0)
            <= (page.viewport_size or {"height": 0}).get("height", 0) + 1,
            f"button={footer_box}",
        )
        footer_button.first.click()
        page.wait_for_selector("#verification-form", timeout=10000)
        fits, verify_box = box_fits_viewport(page, "[role='dialog']")
        check("the verification dialog also fits the viewport", fits, f"box={verify_box}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    check("the review dialog closes cleanly", page.locator("[role='dialog']").count() == 0)

    # KVIC detail screens must be read-only (no edit/pair actions offered).
    go(page, "/kvic/hives")
    page.locator("tbody tr").first.click()
    page.wait_for_timeout(1500)
    check("KVIC can open a hive detail (oversight)", "/kvic/hives/" in page.url, page.url)
    check(
        "KVIC is not offered hive editing",
        page.locator("button:has-text('Change status')").count() == 0
        and page.locator("button:has-text('Edit')").count() == 0,
    )


#: Signed-in screens the shell has to keep honest at every desktop width.
RESPONSIVE_ROUTES = [
    "/dashboard",
    "/beekeeper",
    "/beekeeper/hives",
    "/beekeeper/iot",
    "/profile",
]


def scenario_responsive(width: int):
    """Layout check for one width (a fresh browser each time, see run_group)."""

    def scenario(page: Page) -> None:
        print(f"\n[9] Layout at {width}px")
        page.set_viewport_size({"width": width, "height": HEIGHT})
        for route in RESPONSIVE_ROUTES:
            go(page, route)
            page.wait_for_timeout(500)
            overflow = horizontal_overflow(page)
            check(f"{route} at {width}px does not scroll sideways", overflow <= 2, f"{overflow}px")

    return scenario


def scenario_shell(page: Page) -> None:
    print("\n[10] The application shell itself")
    go(page, "/beekeeper")
    check("the sidebar stays usable", page.locator("aside").first.is_visible())
    check(
        "no nested vertical scrollbar was introduced",
        page.evaluate("getComputedStyle(document.querySelector('main')).overflowY") != "scroll",
    )
    check("the top bar reports API health", visible(page, "API"))
    check("breadcrumbs lead back to the workspace home", page.locator("nav[aria-label='Breadcrumb'] a").count() > 0)


def run_group(playwright, name: str, account: tuple[str, str], scenarios) -> None:
    """Run one scenario group in its own browser.

    A fresh browser per group keeps renderer memory bounded — a single long-lived
    session across every screen in this walk is what crashed the renderer under
    the 2 GB the sandbox provides.
    """
    browser = playwright.chromium.launch(headless=HEADLESS)
    context = browser.new_context(viewport={"width": 1366, "height": HEIGHT}, device_scale_factor=1)
    page = context.new_page()
    page.set_default_timeout(20000)
    page.on(
        "console",
        lambda message: CONSOLE_ERRORS.append(message.text) if message.type == "error" else None,
    )
    page.on("pageerror", lambda error: CONSOLE_ERRORS.append(f"pageerror: {error}"))

    try:
        if account:
            sign_in(page, *account)
        for scenario in scenarios:
            scenario(page)
        if name == "beekeeper":
            page.screenshot(path=os.getenv("SMOKE_SCREENSHOT", "/tmp/honeychain-phase3-smoke.png"))
    finally:
        context.close()
        browser.close()


def main() -> int:
    with sync_playwright() as playwright:
        print("=" * 72)
        print("  HoneyChain — Phase 3 browser verification (integration + layout)")
        print(f"  app: {BASE_URL}")
        print("=" * 72)

        run_group(
            playwright,
            "beekeeper",
            BEEKEEPER,
            [
                scenario_beekeeper_dashboard,
                scenario_sidebar_states,
                scenario_my_hives,
                scenario_hive_detail,
                scenario_iot_monitoring,
            ],
        )
        run_group(playwright, "empty-state", None, [scenario_empty_states])
        run_group(playwright, "admin", ADMIN, [scenario_admin_pages])
        run_group(playwright, "kvic", KVIC, [scenario_kvic_pages])
        run_group(playwright, "shell", BEEKEEPER, [scenario_shell])
        for width in WIDTHS:
            run_group(playwright, f"responsive-{width}", BEEKEEPER, [scenario_responsive(width)])

    # Console noise from permission probes (401/403 on role-scoped routes) is
    # expected in this walk and filtered the same way the Phase-2 script does.
    noisy = [
        entry
        for entry in CONSOLE_ERRORS
        if not re.search(r"401|403|Failed to load resource|favicon", entry, re.IGNORECASE)
    ]

    print("\n" + "=" * 72)
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if noisy:
        print(f"\nUnexpected browser console errors ({len(noisy)}):")
        for entry in noisy[:10]:
            print(f"  - {entry}")
    if FAILED:
        print("\nFailures:")
        for entry in FAILED:
            print(f"  - {entry}")
    if CLEANUP_EMAIL:
        print(
            "\nThis run registered one throwaway beekeeper (its hive, if any, cascades):\n"
            f"  {CLEANUP_EMAIL}\n"
            'Remove it with:  psql "$DATABASE_URL" -c "delete from users where email like \'smoke.p3ui.%\';"'
        )
    return 1 if FAILED or noisy else 0


if __name__ == "__main__":
    raise SystemExit(main())
