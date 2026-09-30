"""Phase 4.1 integration smoke test, driven by a real browser.

Verifies the organisational relationship *from the outside*: that the chain
`cluster → beekeeper → hive → device → telemetry → analysis` renders as one set
of records with several views, and that the two people involved see different
things on the same screen.

Scenarios:

  1. A KVIC officer opens a cluster from the registry and sees its counters,
     its members' hives, their devices, the latest stored reading and the stored
     assessments — all counted from existing rows.
  2. Placing and clearing a hive is a staff action, and the cluster view follows
     immediately because it is the same row, not a copy.
  3. The hive registry's "not in a cluster" worklist is an oversight tool: the
     alert explains what it is, and a beekeeper never gets the filter.
  4. The hive screen shows the cluster read-only to its owner: no placement
     control at all.
  5. The relationship is not available to the wrong role: a beekeeper cannot open
     a cluster view.

Run::

    cd backend && .venv/bin/uvicorn app.main:app --port 8000        # terminal 1
    cd frontend && npm run build && npm run preview -- --port 4173  # terminal 2
    cd backend && .venv/bin/python tests/browser_smoke_phase41.py

Exit code is 0 only if every check passes. The script reads the seeded
development data and leaves it as it found it (the placement it clears is put
back). No throwaway accounts are created.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from playwright.sync_api import Page, sync_playwright

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:4173")
API_URL = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")
KVIC = (
    os.getenv("SMOKE_KVIC_EMAIL", "kvic@honeychain.example.com"),
    os.getenv("SMOKE_KVIC_PASSWORD", "KvicSecure123"),
)
BEEKEEPER = (
    os.getenv("SMOKE_BEEKEEPER_EMAIL", "beekeeper@honeychain.example.com"),
    os.getenv("SMOKE_BEEKEEPER_PASSWORD", "HoneyPass123"),
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


def text_of(page: Page) -> str:
    return page.inner_text("body")


def go(page: Page, path: str) -> None:
    """Navigate and let the first render settle (see the Phase-3 script)."""
    page.goto(f"{BASE_URL}{path}", wait_until="commit", timeout=30000)
    page.wait_for_timeout(1300)


def wait_for_text(page: Page, needle: str, timeout: int = 12000) -> bool:
    """Wait for text to become visible, then report whether it arrived.

    A cluster view loads five independent endpoints, and on a 2-CPU sandbox a
    fixed sleep is a coin toss. Waiting on the text itself keeps the assertion
    about the data rather than about machine speed.
    """
    try:
        page.wait_for_selector(f"text={needle}", timeout=timeout, state="visible")
        return True
    except Exception:  # noqa: BLE001 - absence is a legitimate result
        return False


def fill(page: Page, selector: str, value: str) -> None:
    field = page.locator(selector)
    field.click()
    field.press("Control+a")
    field.press_sequentially(value, delay=8)


def api_token(email: str, password: str) -> str:
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


def api_post(path: str, token: str, body: dict):
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)["data"]


def place_hive_in_cluster(hive_id: str, cluster_id: str, token: str, reason: str) -> None:
    """Idempotent precondition: the scenario needs the hive inside the cluster.

    A duplicate placement is refused (422) by the API, which is the correct
    behaviour — so it is treated here as "already placed" rather than a failure.
    """
    try:
        api_post(f"/hives/{hive_id}/cluster", token, {"cluster_id": cluster_id, "reason": reason})
    except urllib.error.HTTPError as error:
        if error.code != 422:
            raise


def sign_in(page: Page, email: str, password: str) -> None:
    go(page, "/about")
    page.evaluate("window.sessionStorage.clear()")
    go(page, "/login")
    fill(page, "input[name='email']", email)
    fill(page, "input[name='password']", password)
    page.click("button[type='submit']")
    page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
    page.wait_for_timeout(1200)


def main() -> int:
    print("=" * 68)
    print("  HoneyChain — Phase 4.1 organisational relationship browser smoke")
    print(f"  {BASE_URL}")
    print("=" * 68)

    kvic_token = api_token(*KVIC)
    clusters = api_get("/clusters?search=Guntur", kvic_token)
    if not clusters:
        print("  Could not find the seeded Guntur cluster — run app/scripts/seed_dev_data.py first.")
        return 2
    cluster = clusters[0]
    cluster_id = cluster["id"]

    hives = api_get("/hives?page_size=5", kvic_token)
    if not hives:
        print("  No hives in the development database — nothing to view.")
        return 2
    hive = hives[0]

    # The scenario needs the hive inside the cluster; the run restores this at
    # the end, so the development database is left as it was found.
    place_hive_in_cluster(hive["id"], cluster_id, kvic_token, "browser smoke precondition")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on(
            "console",
            lambda message: CONSOLE_ERRORS.append(message.text)
            if message.type == "error"
            else None,
        )

        # ------------------------------------------------- 1. the cluster view
        print("\nThe cluster view")
        sign_in(page, *KVIC)
        go(page, "/kvic/clusters")
        body = text_of(page)
        check(
            "the cluster registry lists the seeded cluster",
            cluster["cluster_code"] in body,
            f"{cluster['cluster_code']} not on the page",
        )

        go(page, f"/kvic/clusters/{cluster_id}")
        page.wait_for_timeout(800)
        body = text_of(page)
        check("the cluster view opens", cluster["cluster_name"] in body, "name missing")
        check(
            "it shows the cluster code and district",
            cluster["cluster_code"] in body and (cluster.get("district") or "") in body,
            "identifier missing",
        )
        for label in ("Beekeepers", "Hives", "Devices", "Readings (24 h)"):
            check(f"the overview counts {label}", label in body, f"{label} missing")
        check(
            "the hive that belongs to this cluster is listed",
            hive["hive_code"] in body,
            f"{hive['hive_code']} not listed",
        )
        check(
            "the hives list says where it came from",
            "Registered by the beekeepers assigned here" in body,
            "no provenance note",
        )
        check(
            "the latest telemetry panel names the chain",
            "Latest telemetry" in body and "kept by" in body,
            "telemetry chain not shown",
        )
        check(
            "the panel is honest about the data source",
            "SIMULATOR" in body or "Simulator" in body,
            "source label missing",
        )
        check(
            "the AI panel lists the stored assessment",
            "Hive health insights in this cluster" in body and hive["hive_code"] in body,
            "assessment missing",
        )
        check(
            "the view explains that it stores nothing of its own",
            "It stores nothing of its own" in body,
            "no explanatory note",
        )
        check(
            "a device is visible through its hive",
            "Devices in this cluster" in body and "ESP32-GNT-0001" in body,
            "device not resolved through the hive",
        )

        # --------------------------------------- 2. staff placement, round trip
        print("\nPlacing and clearing a hive (staff)")
        go(page, f"/kvic/hives/{hive['id']}")
        page.wait_for_timeout(800)
        body = text_of(page)
        check(
            "the hive screen offers staff a placement control",
            "Cluster placement" in body,
            "control missing for a KVIC officer",
        )
        check(
            "the hive screen states the current cluster",
            "Currently:" in body and cluster["cluster_code"] in body,
            "current placement not shown",
        )

        # clear the placement
        page.get_by_label("Cluster").select_option("")
        page.get_by_role("button", name="Clear placement").click()
        page.wait_for_timeout(1200)
        check(
            "clearing the placement is confirmed",
            "Placement cleared" in text_of(page) or "No cluster" in text_of(page),
            "no confirmation",
        )

        go(page, f"/kvic/clusters/{cluster_id}")
        # The assertion is about *this* hive leaving the view, not about the view
        # becoming empty: the cluster may legitimately hold other beekeepers'
        # hives, so waiting for the empty state would test the fixture rather
        # than the relationship.
        gone = wait_for_text(page, hive["hive_code"], timeout=2500) is False
        stray = text_of(page)
        check(
            "the cluster view drops the hive the moment it leaves",
            gone and hive["hive_code"] not in stray,
            "the hive table still shows the hive",
        )

        # put it back, where it belongs
        go(page, f"/kvic/hives/{hive['id']}")
        page.wait_for_timeout(800)
        page.get_by_label("Cluster").select_option(cluster_id)
        page.get_by_role("button", name="Save placement").click()
        page.wait_for_timeout(1200)
        check(
            "replacing it in the cluster is confirmed",
            f"Placed in {cluster['cluster_code']}" in text_of(page),
            "no confirmation",
        )
        go(page, f"/kvic/clusters/{cluster_id}")
        check(
            "and the cluster view lists it again",
            wait_for_text(page, hive["hive_code"]),
            "the hive did not come back",
        )

        # ------------------------------------------------ 3. the staff worklist
        print("\nThe unassigned-hive worklist")
        go(page, "/kvic/hives")
        page.wait_for_timeout(800)
        page.locator("select[name='hive-cluster']").select_option("out")
        page.get_by_role("button", name="Apply").click()
        page.wait_for_timeout(1200)
        body = text_of(page)
        check(
            "the worklist explains what it lists",
            "Hives with no cluster" in body,
            "no explanatory alert",
        )
        check(
            "the worklist does not contain a hive that is in a cluster",
            hive["hive_code"] not in body,
            "a placed hive appeared in the worklist",
        )

        # --------------------------------------- 4. the owner's read-only view
        print("\nThe owner's view of the same hive")
        sign_in(page, *BEEKEEPER)
        go(page, f"/beekeeper/hives/{hive['id']}")
        page.wait_for_timeout(900)
        body = text_of(page)
        check("the owner can open the hive", hive["hive_code"] in body, "hive page missing")
        check(
            "the owner sees the cluster the hive sits in",
            "Cluster" in body and cluster["cluster_code"] in body,
            "cluster not shown read-only",
        )
        check(
            "the owner gets no placement control",
            "Cluster placement" not in body,
            "a beekeeper was offered a staff action",
        )

        # ----------------------------------------------- 5. role separation
        print("\nRole separation")
        go(page, f"/kvic/clusters/{cluster_id}")
        page.wait_for_timeout(1000)
        body = text_of(page)
        check(
            "a beekeeper cannot reach a cluster view",
            cluster["cluster_code"] not in body or "not authorised" in body.lower(),
            "the cluster view rendered for a beekeeper",
        )

        context.close()
        browser.close()

    # Leave the fixture as we found it: the hive belongs to this cluster.
    place_hive_in_cluster(hive["id"], cluster_id, kvic_token, "browser smoke restore")
    final = api_get(f"/hives/{hive['id']}", kvic_token)
    print(
        "\nFixtures after the run:",
        hive["hive_code"],
        "→",
        (final.get("cluster") or {}).get("cluster_code", "no cluster"),
    )

    print("\nConsole errors seen:", len(CONSOLE_ERRORS))
    for entry in CONSOLE_ERRORS[:5]:
        print("   ", entry[:160])

    print("\n" + "=" * 68)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    print("=" * 68)
    for failure in FAILED:
        print(f"  FAILED: {failure}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
