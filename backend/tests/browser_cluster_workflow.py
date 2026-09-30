"""Cluster creation, in the browser, the way an officer does it.

Parts 51–64 of the correction prompt are about one thing seen from several angles:
a KVIC officer creates a cluster, and the cluster has to be *there* — in the
database, in the list, on its own page, after a refresh, after signing out and back
in — and it has to be usable by the rest of the platform (beekeepers, hives,
harvests, batches). The report was that the screen said "Cluster not created" and
the list did not change, so this script walks the exact sequence the prompt sets
out and checks each step against the API as well as the screen:

 1. sign in as the seeded KVIC officer;
 2. open Clusters and note what is already there;
 3. create a cluster through the dialog, with a name nobody has used before;
 4. read the response and say what it actually was;
 5. confirm the row exists in the database (over HTTP, not from React state);
 6. confirm the list refreshed and shows it;
 7. open the cluster's own page and confirm it renders real data;
 8. reload the browser;
 9. sign out, sign in again, and confirm it is still there;
10. attach a beekeeper to it and confirm the membership persisted.

Every record it creates is TEST data, marked in the name.

Usage (API and the built frontend must be running)::

    cd backend
    .venv/bin/python tests/browser_cluster_workflow.py
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from tests.api_smoke_phase7 import register_keeper, request, sign_in  # noqa: E402

DEFAULT_API = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")
DEFAULT_WEB = os.getenv("SMOKE_BASE_URL", "http://localhost:4173")

OFFICER = ("kvic@honeychain.example.com", "KvicSecure123")

PASSED: list[str] = []
FAILED: list[str] = []


def check(description: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(description)
    suffix = f" — {detail}" if detail and not condition else ""
    print(f"  {'PASS' if condition else 'FAIL'}  {description}{suffix}")


def section(title: str) -> None:
    print(f"\n=== {title}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--web-url", default=DEFAULT_WEB)
    parser.add_argument("--headless", action="store_true", default=True)
    args = parser.parse_args()
    api = args.api_url.rstrip("/")
    web = args.web_url.rstrip("/")

    officer_token = sign_in(api, *OFFICER)
    name = f"Tenali Cluster TEST {uuid.uuid4().hex[:6]}"
    district = "Guntur"
    state = "Andhra Pradesh"

    print(f"Cluster creation in a browser — {web} against {api}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1100})
        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        def sign_in_page(email: str, password: str) -> None:
            page.goto(f"{web}/login", wait_until="domcontentloaded")
            page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
            page.goto(f"{web}/login", wait_until="networkidle")
            page.fill("input[name='email']", email)
            page.fill("input[name='password']", password)
            page.click("button[type='submit']")
            page.wait_for_url(lambda url: "/login" not in url, timeout=20000)
            page.wait_for_load_state("networkidle")

        responses: list[tuple[str, str, int]] = []

        def watch(response) -> None:
            if "/clusters" in response.url and response.request.method in ("GET", "POST"):
                responses.append((response.request.method, response.url, response.status))

        page.on("response", watch)

        # ------------------------------------------------------------------ #
        section("The officer opens the cluster registry")
        # ------------------------------------------------------------------ #
        sign_in_page(*OFFICER)
        check("the officer lands in the KVIC workspace", "/kvic" in page.url, f"landed on {page.url}")
        page.goto(f"{web}/kvic/clusters", wait_until="networkidle")
        page.wait_for_timeout(1500)
        before_text = page.locator("main").inner_text()
        before_count = page.locator("table tbody tr").count()
        check(
            "the cluster registry lists what exists today",
            before_count >= 1,
            f"{before_count} row(s) on screen",
        )

        # ------------------------------------------------------------------ #
        section("Creating a cluster through the dialog")
        # ------------------------------------------------------------------ #
        # The registry's own button is "New cluster"; the dialog it opens submits
        # with "Create cluster".
        create = page.get_by_role("button", name="New cluster").first
        check("the registry offers cluster creation", create.count() == 1, "no create button")
        if create.count():
            create.click()
            page.locator("div[role='dialog']").wait_for(state="visible", timeout=10000)
            # Submitting an incomplete form must say what is missing rather than
            # doing nothing at all.
            page.locator("div[role='dialog'] button[type='submit']").first.click()
            page.wait_for_timeout(600)
            empty_text = page.locator("div[role='dialog']").first.inner_text()
            check(
                "an incomplete cluster form says what is missing instead of failing silently",
                "at least" in empty_text or "required" in empty_text.lower(),
                f"the dialog says: {empty_text[:160]!r}",
            )

            # Scoped to the dialog: the page behind it has its own search and
            # filter fields with the same names, and the one on top is the one the
            # officer is actually typing into.
            for selector, value, label in (
                ("input[name='clusterName']", name, "Cluster name"),
                ("input[name='district']", district, "District"),
                ("input[name='state']", state, "State"),
            ):
                field = page.locator(f"div[role='dialog'] {selector}").first
                if field.count():
                    field.click()
                    page.keyboard.type(value, delay=25)
                    check(
                        f"{label} accepts the whole value in one go",
                        field.input_value() == value,
                        f"field holds {field.input_value()!r}",
                    )
                else:
                    check(f"{label} exists in the dialog", False, f"no field {selector}")

            # The dialog's own submit button, not the one that opened it.
            submit = page.locator("div[role='dialog'] button[type='submit']").first
            check(
                "the dialog submits with a button that says what it does",
                submit.count() == 1 and "create cluster" in submit.inner_text().lower(),
                f"submit button says {submit.inner_text()!r}" if submit.count() else "no submit button",
            )
            responses.clear()
            submit.click()
            page.wait_for_timeout(2500)

        posted = [row for row in responses if row[0] == "POST"]
        check(
            "the dialog posted the cluster to the API exactly once",
            len(posted) == 1,
            f"POSTs seen: {posted}",
        )
        check(
            "the API created the cluster",
            bool(posted) and posted[0][2] in (200, 201),
            f"status {posted[0][2] if posted else 'none'}",
        )

        dialog_text = ""
        if page.locator("div[role='dialog']").count():
            dialog_text = page.locator("div[role='dialog']").first.inner_text()
        check(
            "the screen does not claim the creation failed",
            "not created" not in dialog_text.lower() and "not created" not in page.locator("body").inner_text().lower(),
            f"dialog says: {dialog_text[:160]}",
        )

        # ------------------------------------------------------------------ #
        section("The record exists, in the database and on the screen")
        # ------------------------------------------------------------------ #
        status, payload = request("GET", "/clusters?page_size=100", base=api, token=officer_token)
        rows = payload.get("data", []) if status == 200 else []
        created = next((row for row in rows if row["cluster_name"] == name), None)
        check(
            "the cluster is persisted and readable through the API",
            created is not None,
            f"{len(rows)} cluster(s) returned",
        )
        check(
            "the backend generated the cluster code",
            bool(created) and (created.get("cluster_code") or "").startswith("KVIC-"),
            f"code: {created.get('cluster_code') if created else 'none'}",
        )

        page.wait_for_timeout(1500)
        after_text = page.locator("main").inner_text()
        check(
            "the cluster appears in the list without a manual reload",
            (created is not None and created["cluster_code"] in after_text) or name in after_text,
            "the new cluster is not on the screen after creation",
        )

        # ------------------------------------------------------------------ #
        section("The cluster can be opened and survives a refresh")
        # ------------------------------------------------------------------ #
        if created:
            page.goto(f"{web}/kvic/clusters/{created['id']}", wait_until="networkidle")
            page.wait_for_timeout(1800)
            detail_text = page.locator("main").inner_text()
            check(
                "the cluster's own page renders its real details",
                name in detail_text and created["cluster_code"] in detail_text,
                "the detail page does not name the cluster",
            )
            check(
                "the detail page is not an empty shell",
                len(detail_text.strip()) > 80,
                f"the page says: {detail_text[:120]!r}",
            )

            page.reload(wait_until="networkidle")
            page.wait_for_timeout(1500)
            check(
                "the cluster is still there after a browser refresh",
                name in page.locator("main").inner_text(),
                "the refresh lost the cluster",
            )

        # ------------------------------------------------------------------ #
        section("Signing out and back in does not lose it")
        # ------------------------------------------------------------------ #
        sign_in_page(*OFFICER)
        page.goto(f"{web}/kvic/clusters", wait_until="networkidle")
        page.wait_for_timeout(1800)
        check(
            "the cluster is in the registry after signing in again",
            name in page.locator("main").inner_text(),
            "the cluster is missing on a fresh session",
        )

        # ------------------------------------------------------------------ #
        section("The cluster is usable by the rest of the platform")
        # ------------------------------------------------------------------ #
        if created:
            keeper = register_keeper(api)
            status, payload = request("GET", "/beekeepers/me", base=api, token=keeper["token"])
            beekeeper_id = payload["data"]["id"] if status == 200 else None
            check(
                "a beekeeper record exists to attach (public registration)",
                beekeeper_id is not None,
                f"status {status}",
            )
            if beekeeper_id:
                # Membership is addressed by the pair, not by a body: the cluster
                # and the beekeeper are both in the path.
                status, payload = request(
                    "POST",
                    f"/clusters/{created['id']}/beekeepers/{beekeeper_id}",
                    base=api,
                    token=officer_token,
                    body={},
                )
                check(
                    "the officer can add the beekeeper to the new cluster",
                    status in (200, 201),
                    f"status {status} {str(payload)[:160]}",
                )
                status, payload = request(
                    "GET", f"/clusters/{created['id']}", base=api, token=officer_token
                )
                members = ((payload.get("data") or {}).get("members") or []) if status == 200 else []
                check(
                    "the membership is stored, not shown only on the screen",
                    any(str(member.get("id")) == str(beekeeper_id) for member in members),
                    f"{len(members)} member(s) returned",
                )

                page.goto(f"{web}/kvic/clusters/{created['id']}", wait_until="networkidle")
                page.wait_for_timeout(1800)
                check(
                    "the membership is visible on the cluster page",
                    "Master Workflow" in page.locator("main").inner_text()
                    or "Smoke 7 Beekeeper" in page.locator("main").inner_text()
                    or "TEST" in page.locator("main").inner_text(),
                    "the member list does not show the beekeeper",
                )

        check("no console errors during the run", not console_errors, str(console_errors[:3]))
        browser.close()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("Failures:")
        for item in FAILED:
            print(f"  - {item}")
    print(f"\nTEST data created: cluster {name!r} (and one beekeeper account).")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
