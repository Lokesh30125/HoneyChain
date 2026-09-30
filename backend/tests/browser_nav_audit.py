"""Navigation and role boundaries, checked in the browser for all ten roles.

Two standing rules from the correction prompt are audited here, not re-implemented:

* the sidebar shows a role exactly the modules it works with and nothing from
  another workspace (an irrelevant module is hidden, never a "not your
  workspace" screen);
* every entry the sidebar *does* show opens a real screen — no placeholder, no
  "coming soon", no "not part of this release" — and a URL typed by hand that
  belongs to another role lands the user back in their own workspace.

The expectations below are written from the prompt's role list, deliberately not
by reading `src/constants/navigation.js`: a test that compares the sidebar with
the file that generates it would pass while both are wrong.

Usage (API and the built frontend must be running)::

    cd backend
    .venv/bin/python tests/browser_nav_audit.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from tests.api_smoke_phase7 import create_staff, request, sign_in  # noqa: E402

DEFAULT_API = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")
DEFAULT_WEB = os.getenv("SMOKE_BASE_URL", "http://localhost:4173")

#: Seeded accounts. The four staff workspaces that have no dev fixture are
#: provisioned through the admin API, as the platform requires.
SEEDED = {
    "ADMIN": ("admin@honeychain.example.com", "AdminSecure123"),
    "BEEKEEPER": ("beekeeper@honeychain.example.com", "HoneyPass123"),
    "KVIC_OFFICER": ("kvic@honeychain.example.com", "KvicSecure123"),
    "PROCESSOR": ("processor@honeychain.example.com", "ProcessPass123"),
    "LAB_TECHNICIAN": ("labtech@honeychain.example.com", "LabTechPass123"),
    "CONSUMER": ("consumer@honeychain.example.com", "ConsumerPass123"),
}
PROVISIONED = {
    "PACKAGING_UNIT": "packaging",
    "DISTRIBUTOR": "distributor",
    "COLLECTION_CENTER": "centre",
    "RETAILER": "retailer",
}

#: Per role: the path prefixes its sidebar may link to, and the workspace roots
#: it must never expose. `/dashboard` and `/profile` belong to every role, and an
#: administrator reaches the KVIC screens as oversight — that is a documented part
#: of the administrator's workspace, not a leak.
ALLOWED_EXTRA = ("/dashboard", "/profile")
ADMIN_OVERSIGHT = ("/kvic", "/processing", "/laboratory")
FORBIDDEN_ROOTS = {
    "ADMIN": (),
    "BEEKEEPER": ("/admin", "/kvic", "/laboratory", "/processor", "/packaging", "/distributor", "/retailer"),
    "KVIC_OFFICER": ("/admin", "/laboratory", "/processor", "/packaging", "/distributor", "/retailer", "/beekeeper"),
    "PROCESSOR": ("/admin", "/kvic", "/laboratory", "/packaging", "/distributor", "/retailer", "/beekeeper"),
    "LAB_TECHNICIAN": ("/admin", "/kvic", "/processor", "/packaging", "/distributor", "/retailer", "/beekeeper"),
    "PACKAGING_UNIT": ("/admin", "/kvic", "/laboratory", "/processor", "/distributor", "/retailer", "/beekeeper"),
    "DISTRIBUTOR": ("/admin", "/kvic", "/laboratory", "/processor", "/packaging", "/retailer", "/beekeeper"),
    "COLLECTION_CENTER": ("/admin", "/kvic", "/laboratory", "/processor", "/packaging", "/distributor", "/retailer"),
    "RETAILER": ("/admin", "/kvic", "/laboratory", "/processor", "/packaging", "/distributor", "/beekeeper"),
    "CONSUMER": ("/admin", "/kvic", "/laboratory", "/processor", "/packaging", "/distributor", "/retailer", "/beekeeper"),
}

#: Refusals a *provisioned* account is expected to receive, and why.
#:
#: The audit creates its staff accounts fresh, so a packaging operator it just
#: provisioned belongs to no packing unit yet. `GET /packaging-units/mine`
#: answers 404 for exactly that state — the screens treat it as "not put to work
#: at a facility yet", which is a fact rather than a failure — but the browser
#: still logs its own "Failed to load resource" line for the answer. Anything
#: else answering 4xx/5xx is a defect, and is reported as one.
EXPECTED_REFUSALS = {
    "PACKAGING_UNIT": ("/packaging-units/mine",),
}

#: Nothing this task implements may still be described as unfinished anywhere a
#: signed-in user can land.
#: Phrases that mean "this screen does not do the job". The bare word
#: "placeholder" is deliberately absent: honest copy uses it in the other sense
#: ("this is not a placeholder for a number"), and the audit is about unfinished
#: modules, not about vocabulary.
NEVER_ACCEPTABLE = (
    "not your workspace",
    "coming soon",
    "under construction",
    "not implemented yet",
)

#: No role's module is unbuilt any more: consumer verification — the QR identity
#: and the public traceability page — shipped in Phase 8, so this text on *any*
#: screen now means a stale roadmap note. The consumer's screen carried one until
#: this run, which is exactly the kind of lie the audit exists to catch.
PHASE_NOTICE = "not part of this release"

PASSED: list[str] = []
FAILED: list[str] = []


def check(description: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(description)
    suffix = f" — {detail}" if detail and not condition else ""
    print(f"  {'PASS' if condition else 'FAIL'}  {description}{suffix}")


def section(title: str) -> None:
    print(f"\n=== {title}")


def home_for(role: str) -> str:
    """The landing route the platform documents for a role."""
    return {
        "ADMIN": "/admin",
        "BEEKEEPER": "/beekeeper",
        "KVIC_OFFICER": "/kvic",
        "PROCESSOR": "/processor",
        "LAB_TECHNICIAN": "/laboratory",
        "PACKAGING_UNIT": "/packaging",
        "DISTRIBUTOR": "/distributor",
        "COLLECTION_CENTER": "/collection-center",
        "RETAILER": "/retailer",
        "CONSUMER": "/consumer",
    }[role]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--web-url", default=DEFAULT_WEB)
    args = parser.parse_args()
    api = args.api_url.rstrip("/")
    web = args.web_url.rstrip("/")

    admin_token = sign_in(api, *SEEDED["ADMIN"])
    accounts = dict(SEEDED)
    for role, label in PROVISIONED.items():
        provisioned = create_staff(api, admin_token, label, role)
        accounts[role] = (provisioned["email"], "SmokeP7Staff123")

    print(f"Navigation audit — {web} against {api}")
    print("Accounts: 6 seeded fixtures + 4 provisioned through POST /admin/users (TEST).")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for role, (email, password) in accounts.items():
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            console_errors: list[str] = []
            #: Every request the browser made that came back refused. A bare
            #: "Failed to load resource: 403" says nothing about which call it
            #: was, so the URLs are recorded and reported.
            refused: list[str] = []
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(str(e)))
            page.on(
                "response",
                lambda r: refused.append(f"{r.status} {r.request.method} {r.url}")
                if r.status >= 400
                else None,
            )

            home = home_for(role)
            allowed = tuple(
                {home, *ALLOWED_EXTRA, *(ADMIN_OVERSIGHT if role == "ADMIN" else ())}
            )

            section(f"{role} — signs in and lands in its own workspace")
            page.goto(f"{web}/login", wait_until="domcontentloaded")
            page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
            page.goto(f"{web}/login", wait_until="networkidle")
            page.fill("input[name='email']", email)
            page.fill("input[name='password']", password)
            page.click("button[type='submit']")
            page.wait_for_url(lambda url: "/login" not in url, timeout=20000)
            page.wait_for_load_state("networkidle")
            check(
                "the sign-in lands on the workspace the platform documents",
                page.url.rstrip("/").endswith(home),
                f"landed on {page.url}",
            )

            never_seen: set[str] = set()
            phase_seen: set[str] = set()

            def scan_screen() -> None:
                text = page.locator("body").inner_text().lower()
                never_seen.update(phrase for phrase in NEVER_ACCEPTABLE if phrase in text)
                if PHASE_NOTICE in text:
                    phase_seen.add(page.url)

            scan_screen()

            links = page.eval_on_selector_all(
                "nav[aria-label='Primary'] a[href]",
                "nodes => nodes.map(n => n.getAttribute('href'))",
            )
            links = [link for link in links if link and not link.startswith("http")]
            check(
                "the sidebar offers this role its own work",
                bool(links),
                "the sidebar rendered no links",
            )

            for root in FORBIDDEN_ROOTS[role]:
                visible = [
                    link
                    for link in links
                    if link == root or link.startswith(f"{root}/")
                ]
                check(
                    f"no {root} entry leaks into the {role} sidebar",
                    not visible,
                    f"found {visible}",
                )

            outside = [
                link
                for link in links
                if not any(link == prefix or link.startswith(f"{prefix}/") for prefix in allowed)
            ]
            check(
                "every sidebar entry belongs to this workspace",
                not outside,
                f"entries outside the workspace: {outside}",
            )

            # Each entry must open a real screen. A guard is not a failure: opening
            # `/dashboard` from a workspace is fine when the platform sends the user
            # to the screen for their own role. What is not fine is a screen that
            # renders a placeholder, or nothing at all.
            for link in links:
                page.goto(f"{web}{link}", wait_until="networkidle")
                page.wait_for_timeout(400)
                body = page.locator("body").inner_text()
                lowered = body.lower()
                scan_screen()
                placeholder = next((text for text in NEVER_ACCEPTABLE if text in lowered), None)
                check(
                    f"{link} opens a real screen",
                    placeholder is None and len(body.strip()) > 120,
                    placeholder and f"the page says {placeholder!r}" or "the page is empty",
                )
                check(
                    f"{link} stays inside the {role} workspace",
                    any(
                        page.url.split("#")[0].endswith(prefix)
                        or f"{prefix}/" in page.url
                        for prefix in allowed
                    ),
                    f"ended on {page.url}",
                )

            # A URL typed by hand for another workspace must land the user back in
            # their own — not on a "this is not your workspace" screen.
            intruder = next(
                (
                    root
                    for root in ("/admin", "/kvic", "/laboratory", "/processor", "/packaging", "/distributor", "/retailer", "/beekeeper", "/collection-center")
                    if root != home and root not in allowed
                ),
                None,
            )
            check(
                "there is a foreign workspace to try",
                intruder is not None,
                "every workspace root is open to this role",
            )
            if intruder:
                page.goto(f"{web}{intruder}", wait_until="networkidle")
                # The guard sends the user home once it knows who is signed in, and
                # that answer comes from the API; give the redirect the time a real
                # user would, rather than asserting on a stopwatch.
                try:
                    page.wait_for_function(
                        "(prefix) => !location.pathname.startsWith(prefix)", arg=intruder, timeout=5000
                    )
                except Exception:  # noqa: BLE001 — the assertion below reports it
                    pass
                page.wait_for_timeout(400)
                landed = page.url.split("#")[0].replace(web, "")
                scan_screen()
                check(
                    f"typing {intruder} as {role} returns to its own workspace",
                    landed == home or landed.startswith(f"{home}/"),
                    f"ended on {page.url}",
                )

            check(
                f"nothing in the {role} workspace reads as unfinished",
                not never_seen,
                f"the screens say {sorted(never_seen)}",
            )
            check(
                f"no screen in the {role} workspace says its module is not part of the release",
                not phase_seen,
                f"stale roadmap note on {sorted(phase_seen)}",
            )
            if role == "CONSUMER":
                # And the consumer's module is not merely "not described as
                # missing" — it is present. The check is about the real screen:
                # the verification box and the report it renders.
                check(
                    "the consumer workspace offers verification",
                    "verify a product" in page.locator("body").inner_text().lower(),
                    "no verification form on the consumer's own screen",
                )

            expected = EXPECTED_REFUSALS.get(role, ())
            unexpected_refusals = [
                url for url in refused if not any(marker in url for marker in expected)
            ]
            check(
                f"nothing was refused as {role} beyond what its own state explains",
                not unexpected_refusals,
                "; ".join(sorted(set(unexpected_refusals))[:3]),
            )
            check(
                f"no console errors as {role} beyond those refusals",
                len(console_errors) <= len(refused),
                f"{console_errors[:2]} | refused: {sorted(set(refused))[:2]}",
            )
            page.close()

        browser.close()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for failure in FAILED:
        print(f"  FAILED  {failure}")
    print("\nThe four provisioned accounts are TEST accounts created through the admin API.")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
