"""Phase-5 integration smoke test, driven by a real browser.

Verifies the harvest → batch journey from the outside, through the screens the two
people involved actually use, against the seeded development data:

  1. The beekeeper's workspace opens with honest empty states and a form that has
     no beekeeper or cluster field on it — those come from the signed-in record.
  2. Recording a harvest from the UI produces a server-issued code, and the same
     harvest then appears in the beekeeper's list.
  3. Completing it creates the batch, and the batch screen explains itself: what
     the honey is, where it came from, which harvest it belongs to, what the AI
     expected, and a timeline where the collection is done and everything later is
     not started — with no control anywhere that could move it on.
  4. A KVIC officer sees the same single record through the cluster screens,
     read-only: no record button, no action buttons.

The run cleans up after itself over SQL at the end (nothing in this phase may
delete a harvest through the API — that is the immutability rule working), so the
development database is left as it was found.

Run::

    cd backend && .venv/bin/uvicorn app.main:app --port 8000         # terminal 1
    cd frontend && npm run build && npm run preview -- --port 4173   # terminal 2
    cd backend && .venv/bin/python tests/browser_smoke_phase5.py

Exit code is 0 only if every check passes.
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
BEEKEEPER = (
    os.getenv("SMOKE_BEEKEEPER_EMAIL", "beekeeper@honeychain.example.com"),
    os.getenv("SMOKE_BEEKEEPER_PASSWORD", "HoneyPass123"),
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
DIST_DIR = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"

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

    A workspace loads several endpoints at once; on a 2-CPU sandbox a fixed sleep
    is a coin toss, so the assertions wait on the data rather than on the machine.
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


def sign_in(page: Page, email: str, password: str) -> None:
    go(page, "/about")
    page.evaluate("window.sessionStorage.clear()")
    go(page, "/login")
    fill(page, "input[name='email']", email)
    fill(page, "input[name='password']", password)
    page.click("button[type='submit']")
    page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
    page.wait_for_timeout(1200)


def no_horizontal_scroll(page: Page) -> bool:
    """The layout must fit the viewport at 100% zoom (Prompt 3.1)."""
    return page.evaluate(
        "() => { const el = document.documentElement;"
        " return el.scrollWidth <= el.clientWidth + 2; }"
    )


def bundle_contains(needle: str) -> bool:
    """Is the exact phrase shipped in the built bundle?

    Some states (a failed request, a screenshot at the wrong moment) cannot be
    provoked reliably in a smoke run; checking the shipped bundle proves the
    wording is what the UI actually renders rather than what the source meant to.
    """
    if not DIST_DIR.exists():
        return False
    for path in DIST_DIR.rglob("*.js"):
        try:
            if needle in path.read_text(errors="replace"):
                return True
        except OSError:
            continue
    return False


def cleanup() -> None:
    """Remove the records this run created — over SQL, since the API forbids it."""
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        from app.core.config import get_settings  # noqa: PLC0415 - optional at import time
        import psycopg  # noqa: PLC0415

        dsn = get_settings().DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """DELETE FROM honey_batches WHERE collection_id IN (
                           SELECT c.id FROM honey_collections c
                           JOIN beekeepers b ON b.id = c.beekeeper_id
                           JOIN users u ON u.id = b.user_id
                           WHERE u.email = %s AND c.notes LIKE '%%browser smoke%%')""",
                    (BEEKEEPER[0],),
                )
                cursor.execute(
                    """DELETE FROM honey_collections WHERE id IN (
                           SELECT c.id FROM honey_collections c
                           JOIN beekeepers b ON b.id = c.beekeeper_id
                           JOIN users u ON u.id = b.user_id
                           WHERE u.email = %s AND c.notes LIKE '%%browser smoke%%')""",
                    (BEEKEEPER[0],),
                )
                removed = cursor.rowcount
            connection.commit()
        print(f"\nCleanup: removed the smoke's harvest records ({removed} collection(s)).")
    except Exception as error:  # noqa: BLE001 - cleanup must never fail the run
        print(f"\nCleanup: could not remove the smoke's records automatically ({error}).")
        print("  Remove them with:")
        print(
            "    DELETE FROM honey_batches WHERE collection_id IN (SELECT c.id FROM honey_collections c "
            "JOIN beekeepers b ON b.id=c.beekeeper_id JOIN users u ON u.id=b.user_id "
            f"WHERE u.email='{BEEKEEPER[0]}' AND c.notes LIKE '%browser smoke%');"
        )
        print(
            "    DELETE FROM honey_collections WHERE id IN (SELECT c.id FROM honey_collections c "
            "JOIN beekeepers b ON b.id=c.beekeeper_id JOIN users u ON u.id=b.user_id "
            f"WHERE u.email='{BEEKEEPER[0]}' AND c.notes LIKE '%browser smoke%');"
        )


def main() -> int:
    print("=" * 68)
    print("  HoneyChain — Phase 5 collection → honey batch browser smoke")
    print(f"  {BASE_URL}")
    print("=" * 68)

    token = api_token(*BEEKEEPER)
    profile = api_get("/beekeepers/me", token)
    cluster = profile.get("cluster") or {}
    hives = api_get("/collections/eligible-hives", token)
    existing = api_get("/collections?page_size=50", token)
    batches_before = api_get("/batches?page_size=50", token)

    if not hives.get("hives"):
        print("  No harvestable hives for the seeded beekeeper — run seed_dev_data.py first.")
        return 2

    hive = hives["hives"][0]
    notes = f"Recorded by tests/browser_smoke_phase5.py (browser smoke) — {hive['hive_code']}"
    print(
        f"\nFixture: {hive['hive_code']} owned by the seeded beekeeper, "
        f"cluster {cluster.get('cluster_code', 'none')}"
    )
    print(f"Before: {len(existing)} collection(s), {len(batches_before)} batch(es)")

    # -------------------------------------------------------- shipped wording
    print("\nThe exact wording the phase requires (as shipped in the bundle)")
    for phrase in (
        "No collections recorded yet.",
        "No eligible hives available for collection.",
        "No honey batches created yet.",
        "Loading collections...",
        "Unable to load collection data.",
    ):
        check(f'the bundle contains "{phrase}"', bundle_contains(phrase), "not found in dist")

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

        # ------------------------------------------------ 1. the workspace
        print("\n1. The beekeeper's collection workspace")
        sign_in(page, *BEEKEEPER)
        body = text_of(page)
        check(
            "the sidebar offers Harvest Records without a 'coming soon' mark",
            "Honey Collections" in body,
            "no collections entry in navigation",
        )
        check(
            "and Honey Batches as a real screen",
            "Honey Batches" in body,
            "no batches entry in navigation",
        )

        go(page, "/beekeeper/collections")
        page.wait_for_timeout(600)
        body = text_of(page)
        check("the workspace opens", "Collections" in body or "Honey Collections" in body, "title missing")
        check(
            "the record form is offered to the beekeeper",
            page.locator("select[name='hives.0.hive_id']").count() == 1
            and page.locator("input[name='collection_date']").count() == 1
            and page.locator("button:has-text('Save collection')").count() == 1,
            "the harvest form is not rendered",
        )
        check(
            "the form names no beekeeper or cluster field",
            page.locator("input[name='beekeeper_id']").count() == 0
            and page.locator("input[name='cluster_id']").count() == 0
            and page.locator("select[name='cluster_id']").count() == 0,
            "a client-selectable owner field is rendered",
        )
        check(
            "the same empty harvest list reads honestly",
            "No collections recorded yet." in body,
            "empty state missing",
        )
        check(
            "the layout has no horizontal scroll at 100% zoom",
            no_horizontal_scroll(page),
            "the page is wider than the viewport",
        )
        selector = "select[name='hives.0.hive_id']"
        options = page.locator(f"{selector} option").all_inner_texts()
        offered = page.eval_on_selector_all(
            f"{selector} option", "nodes => nodes.map(n => n.value).filter(Boolean)"
        )
        check(
            "the harvestable hive is offered in the form",
            any(hive["hive_code"] in option for option in options),
            f"{hive['hive_code']} not among {options}",
        )
        own_ids = {row["id"] for row in hives["hives"]}
        check(
            "and only the caller's own hives can be chosen",
            set(offered) and set(offered) <= own_ids,
            f"offered {offered}, own hives are {sorted(own_ids)}",
        )

        # ------------------------------------------- 2. recording a harvest
        print("\n2. Recording a harvest through the form")
        page.select_option("select[name='hives.0.hive_id']", hive["id"])
        page.wait_for_timeout(200)
        selected = page.locator("select[name='hives.0.hive_id']").input_value()
        check(
            "the hive can be selected",
            selected == hive["id"],
            f"select holds {selected!r}",
        )

        fill(page, "input[name='hives.0.quantity']", "4.5")
        fill(page, "input[name='notes']", notes)
        check(
            "the form shows no beekeeper or cluster selector",
            page.locator("select[name='cluster_id']").count() == 0
            and page.locator("input[name='beekeeper_id']").count() == 0,
            "an owner field appeared with the hive options",
        )

        page.locator("button:has-text('Save collection')").first.click()
        page.wait_for_timeout(2500)
        body = text_of(page)
        recorded = api_get("/collections?page_size=50", token)
        created = [row for row in recorded if row.get("notes") == notes]
        check(
            "the harvest is stored",
            len(created) == 1,
            f"found {len(created)} matching records",
        )
        code = created[0]["collection_code"] if created else ""
        check(
            "the server issued its code",
            code.startswith("HC-COL-"),
            f"got {code!r}",
        )
        check(
            "the new harvest appears in the list",
            bool(code) and wait_for_text(page, code),
            f"{code} not rendered",
        )
        check(
            "it is shown as planned, not complete",
            "Planned" in text_of(page) or "In progress" in text_of(page),
            "no open status shown",
        )

        # ------------------------------------------------- 3. the detail page
        print("\n3. The harvest detail page")
        go(page, f"/beekeeper/collections/{created[0]['id']}" if created else "/beekeeper/collections")
        page.wait_for_timeout(900)
        body = text_of(page)
        check("the detail page opens", code in body, f"{code} missing")
        check(
            "the source hive is named with its contribution",
            hive["hive_code"] in body,
            "source hive missing",
        )
        complete_button = page.locator("button:has-text('Complete')")
        check(
            "closing the harvest is offered to its owner",
            complete_button.count() >= 1,
            "no complete action",
        )

        complete_button.first.click()
        page.wait_for_timeout(2500)
        body = text_of(page)
        after = api_get("/collections?page_size=50", token)
        row = next((item for item in after if item["collection_code"] == code), {})
        batch_code = row.get("batch_code") or ""
        check(
            "completing it produces a batch",
            row.get("status") == "COMPLETED" and batch_code.startswith("HC-BATCH-"),
            f"status={row.get('status')} batch={batch_code!r}",
        )
        check(
            "and the screen says so",
            wait_for_text(page, batch_code) if batch_code else False,
            f"{batch_code} not rendered",
        )
        check(
            "a completed harvest offers no further edit",
            page.locator("button:has-text('Complete')").count() == 0
            and page.locator("button:has-text('Cancel')").count() == 0,
            "an action is still offered on a completed harvest",
        )

        # -------------------------------------------------- 4. the batch view
        print("\n4. The honey batch screen")
        go(page, "/beekeeper/batches")
        page.wait_for_timeout(900)
        body = text_of(page)
        check("the batch list shows the batch", batch_code in body, f"{batch_code} missing")
        check(
            "and no longer claims there are none",
            "No honey batches created yet." not in body,
            "the empty state is still rendered",
        )
        check("the batches layout has no horizontal scroll", no_horizontal_scroll(page), "wider than viewport")

        batches = api_get("/batches?page_size=50", token)
        batch = next((item for item in batches if item["batch_code"] == batch_code), {})
        go(page, f"/beekeeper/batches/{batch['id']}")
        page.wait_for_timeout(1200)
        body = text_of(page)
        for heading in ("Source", "Collection", "AI Context"):
            check(f"the batch screen has a {heading} section", heading in body, f"{heading} missing")
        check(
            "it carries the harvest's quantity",
            "4.5" in body,
            "quantity not shown",
        )
        check(
            "the AI section does not invent a comparison",
            ("No AI yield estimate" in body)
            or ("Predicted yield" in body and "Difference" in body),
            "the AI section is neither an estimate nor an honest absence",
        )
        check(
            "the timeline marks the collection complete",
            "Collection" in body and "Completed" in body,
            "no completed collection stage",
        )
        # Phase 6 gave each stage row its own state badge and a data attribute, so
        # the walk reads each row instead of searching the whole page for a phrase.
        collection_row = page.locator("[data-stage='COLLECTION']")
        check(
            "the timeline row itself marks the collection complete",
            collection_row.count() == 1 and "Completed" in collection_row.inner_text(),
            collection_row.inner_text()[:80] if collection_row.count() else "no collection row",
        )
        for stage in ("PROCESSING", "LABORATORY", "PACKAGING", "DISTRIBUTION"):
            row = page.locator(f"[data-stage='{stage}']")
            row_text = row.inner_text() if row.count() else ""
            check(
                f"the timeline marks {stage.title()} as not started",
                row.count() == 1 and "Pending" in row_text,
                f"{stage} missing from the timeline" if not row.count() else row_text[:80],
            )
        for stage in ("PACKAGING", "DISTRIBUTION"):
            row_text = page.locator(f"[data-stage='{stage}']").inner_text()
            check(
                f"the {stage.title()} row says the module is not built rather than pretending",
                "Not implemented in this phase" in row_text,
                row_text[:120],
            )
        check(
            "nothing on the screen offers to move the batch on",
            not any(
                phrase in body.lower()
                for phrase in ("move to processing", "mark as packaged", "send for testing", "start processing")
            ),
            "a future-phase control is rendered",
        )
        check("the batch layout has no horizontal scroll", no_horizontal_scroll(page), "wider than viewport")

        # ---------------------------------------------- 5. the officer's view
        print("\n5. What the KVIC officer sees")
        sign_in(page, *KVIC)
        go(page, "/kvic/collections")
        page.wait_for_timeout(1000)
        body = text_of(page)
        if cluster:
            check(
                "the officer reads the same harvest record",
                code in body,
                f"{code} not visible to the officer",
            )
            check(
                "and is offered no way to record one",
                page.locator("button:has-text('Save collection')").count() == 0
                and page.locator("select[name='hives.0.hive_id']").count() == 0,
                "the record form is rendered for an officer",
            )
        go(page, "/kvic/batches")
        page.wait_for_timeout(1000)
        check(
            "the officer reads the same batch record",
            batch_code in text_of(page),
            f"{batch_code} not visible to the officer",
        )

        if cluster:
            go(page, f"/kvic/clusters/{cluster['id']}")
            page.wait_for_timeout(1200)
            body = text_of(page)
            check(
                "the cluster screen carries the cluster's harvests",
                "Harvests in this cluster" in body and code in body,
                "the cluster harvest panel is missing the record",
            )
            check(
                "and the batches they produced",
                "Batches from this cluster" in body and batch_code in body,
                "the cluster batch panel is missing the record",
            )
            check(
                "the cluster screen stays read-only",
                page.locator("button:has-text('Complete')").count() == 0,
                "an action button is rendered inside the cluster view",
            )

        # --------------------------------------------- 6. the wrong audience
        print("\n6. Roles that may not see any of this")
        sign_in(page, *CONSUMER)
        go(page, "/beekeeper/collections")
        page.wait_for_timeout(900)
        body = text_of(page)
        check(
            "a consumer reaches no collection workspace",
            code not in body,
            "harvest records rendered for a consumer",
        )

        context.close()
        browser.close()

    print("\nConsole errors seen:", len(CONSOLE_ERRORS))
    for entry in CONSOLE_ERRORS[:5]:
        print("   ", entry[:160])

    cleanup()

    print("\n" + "=" * 68)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    print("=" * 68)
    for failure in FAILED:
        print(f"  FAILED: {failure}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
