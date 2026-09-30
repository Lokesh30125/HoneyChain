"""Phase 8 — the traceability screens, in a browser, against the real data.

The end-to-end script (`tests/phase8_blockchain_workflow.py`) proves the records
and the ledger. This one proves the *screens* read them: the administrator's
ledger with real transactions and a working sync control, the batch screen's
blockchain section, the KVIC officer's scoped ledger, and — the one a customer
ever sees — the public page a QR code resolves to, opened with no account at all.

It reads whatever the last end-to-end run produced, so run that first. Usage:

    cd backend
    .venv/bin/python tests/phase8_ui_checks.py [--api-url …] [--web-url …]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from tests.api_smoke_phase7 import request, sign_in  # noqa: E402
from tests.browser_master_workflow import (  # noqa: E402
    ADMIN,
    OFFICER,
    PACKER_PASSWORD,
    create_account,
    sign_in_page,
    staging_email,
)

DEFAULT_API = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")
DEFAULT_WEB = os.getenv("SMOKE_BASE_URL", "http://localhost:4173")

PASSED: list[str] = []
FAILED: list[str] = []


def check(description: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(description)
    suffix = f" — {detail}" if detail and not condition else ""
    print(f"  {'PASS' if condition else 'FAIL'}  {description}{suffix}")


def section(title: str) -> None:
    print(f"\n=== {title}")


def main_text(page) -> str:
    body = page.locator("main")
    return body.first.inner_text() if body.count() else page.locator("body").inner_text()


def newest_traced_batch(api: str, token: str) -> tuple[str, str, str, str, str]:
    """The most recent batch that actually has a QR-labelled package.

    The newest batch on the ledger may be one a workflow is still working
    through, so the search walks back until it finds a package whose label was
    issued — which is what these checks need to look at.
    """
    status, payload = request(
        "GET", "/blockchain/transactions?page_size=100&status=CONFIRMED", base=api, token=token
    )
    if status != 200 or not payload["data"]:
        raise SystemExit(f"No confirmed events to look at: {status} {payload}")

    seen: list[str] = []
    for row in payload["data"]:
        batch_code = row.get("batch_code")
        if batch_code and batch_code not in seen:
            seen.append(batch_code)

    for batch_code in seen:
        status, listing = request(
            "GET", f"/blockchain/transactions?batch_code={batch_code}&page_size=100",
            base=api, token=token,
        )
        batch_id = next(
            (item["batch_id"] for item in listing["data"] if item.get("batch_id")), None
        )
        if batch_id is None:
            continue
        status, trace = request("GET", f"/blockchain/batches/{batch_id}", base=api, token=token)
        packages = (trace.get("data") or {}).get("packages") or []
        with_qr = next((item for item in packages if item.get("qr_issued")), None)
        if with_qr is None:
            continue
        status, listing = request(
            "GET", f"/packages?batch_id={batch_id}&page_size=100", base=api, token=token
        )
        package_id = next(
            (
                item["id"]
                for item in listing["data"]
                if item["package_code"] == with_qr["package_code"]
            ),
            None,
        )
        if package_id is None:
            continue
        return batch_code, batch_id, with_qr["package_code"], package_id, ""

    raise SystemExit("No batch with a QR-labelled package — run the end-to-end first.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 8 screen checks")
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--web-url", default=DEFAULT_WEB)
    args = parser.parse_args()
    api = args.api_url.rstrip("/")
    web = args.web_url.rstrip("/")

    admin = sign_in(api, *ADMIN)
    officer = sign_in(api, *OFFICER)
    batch_code, batch_id, package_code, package_id, _packaging_code = newest_traced_batch(api, admin)
    print(f"Phase 8 screens — {web} against {api}")
    print(f"  looking at package {package_code} (batch {batch_id})")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()

        # ------------------------------------------------------------------ #
        section("The administrator's ledger")
        # ------------------------------------------------------------------ #
        sign_in_page(page, ADMIN)
        page.goto(f"{web}/admin/blockchain", wait_until="networkidle")
        page.wait_for_timeout(2500)
        text = main_text(page)
        check("the ledger screen open for an administrator", "Blockchain ledger" in text)
        check("it reports the service's own state", "Blockchain service" in text)
        # A register of this size runs to many pages, so the batch is found the
        # way an officer finds it: by searching for it.
        check(
            "the ledger is searchable",
            page.locator("input[name='search']").count() == 1,
        )
        page.fill("input[name='search']", batch_code)
        page.click("button[type='submit']")
        page.wait_for_timeout(2000)
        searched = main_text(page)
        check(
            "searching by batch code lists that batch's events",
            batch_code in searched and "No events recorded yet" not in searched,
            f"{batch_code} was not found by search",
        )
        check(
            "the sync control is offered to the administrator",
            page.locator("button", has_text="Sync now").count() == 1,
        )
        row_count = page.locator("table tbody tr").count()
        check("the ledger renders rows from the API", row_count > 0, f"{row_count} rows")

        # A filter that must narrow the register, not empty it.
        page.fill("input[name='search']", package_code)
        page.click("button[type='submit']")
        page.wait_for_timeout(2000)
        filtered = main_text(page)
        check(
            "filtering by package code keeps the matching events",
            "No events recorded yet" not in filtered and package_code in filtered,
            f"{package_code} was not found by search",
        )

        # ------------------------------------------------------------------ #
        section("The batch screen's blockchain section")
        # ------------------------------------------------------------------ #
        page.goto(f"{web}/admin/batches/{batch_id}", wait_until="networkidle")
        page.wait_for_timeout(2500)
        # The section is further down the page; scroll it into view.
        page.locator("text=Blockchain traceability").first.scroll_into_view_if_needed()
        page.wait_for_timeout(1200)
        batch_text = main_text(page)
        check("the batch screen carries a blockchain section", "Blockchain traceability" in batch_text)
        check(
            "it states the chain state honestly",
            "confirmed" in batch_text.lower(),
            batch_text[:200],
        )
        check(
            "the event ids it shows are real ones",
            "COLLECTION-" in batch_text or "BATCH-" in batch_text,
        )

        # ------------------------------------------------------------------ #
        section("The KVIC officer's ledger")
        # ------------------------------------------------------------------ #
        sign_in_page(page, OFFICER)
        page.goto(f"{web}/kvic/blockchain", wait_until="networkidle")
        page.wait_for_timeout(2500)
        officer_text = main_text(page)
        check("the officer's ledger opens in the KVIC workspace", "Blockchain ledger" in officer_text)
        check(
            "it does not offer the administrator's sync control",
            page.locator("button", has_text="Sync now").count() == 0,
        )

        # ------------------------------------------------------------------ #
        section("The packing unit's QR label")
        # ------------------------------------------------------------------ #
        packer_email = staging_email("ui-packer")
        packer_user = create_account(
            api,
            admin,
            role="PACKAGING_UNIT",
            email=packer_email,
            password=PACKER_PASSWORD,
            organization="Phase 8 UI Packing Unit (TEST)",
            district="Guntur",
        )
        status, payload = request("GET", "/packaging-units?page_size=5", base=api, token=admin)
        unit = (payload.get("data") or [None])[0]
        if unit is not None:
            request(
                "POST",
                f"/packaging-units/{unit['id']}/members",
                base=api,
                token=admin,
                body={"user_id": (packer_user.get("user") or {}).get("id") or packer_user.get("id")},
            )
        sign_in_page(page, (packer_email, PACKER_PASSWORD))
        page.goto(f"{web}/packaging/packages/{package_id}", wait_until="networkidle")
        page.wait_for_timeout(2500)
        packer_text = main_text(page)
        check("the package screen carries its QR label", "QR label" in packer_text, packer_text[:200])
        check(
            "the label itself is drawn on the screen",
            page.locator("svg").count() > 0 and package_code in packer_text,
        )
        check(
            "the label states where it resolves to",
            "/trace/" in packer_text,
        )
        check(
            "the screen counts verifications honestly",
            "scan" in packer_text.lower(),
        )
        # The label carries a stable id beside the code: derived from the package,
        # so the same jar answers to the same id after a reprint.
        check(
            "the label prints the package's stable QR id",
            f"QR-{package_code}" in packer_text,
            packer_text[:300],
        )

        # ------------------------------------------------------------------ #
        section("The customer's page — no account at all")
        # ------------------------------------------------------------------ #
        page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        response = page.goto(f"{web}/trace/{package_code}", wait_until="networkidle")
        page.wait_for_timeout(2500)
        customer = main_text(page)
        check("the QR code resolves to a page", response is not None and response.status == 200)
        check("the page names the package", package_code in customer, customer[:200])
        check("it shows the journey", "The journey of this honey" in customer)
        check("it shows the blockchain record", "Blockchain record" in customer)
        check("it shows the packing step", "Packed at" in customer or "packaged" in customer.lower())
        check(
            "it never claims a chain state it has not got",
            "Being written" in customer or "On the chain" in customer,
        )
        check(
            "no account address is on the public page",
            "@honeychain.example.com" not in customer,
        )
        check(
            "the page names the QR id beside the package id",
            f"QR-{package_code}" in customer,
        )

        # The id resolves on its own route, without an account: a scanner that
        # stored the id and a link that carries the code land on the same jar.
        response = page.goto(f"{web}/verify/QR-{package_code}", wait_until="networkidle")
        page.wait_for_timeout(1500)
        by_id = main_text(page)
        check(
            "the QR id resolves to the same package",
            response is not None and response.status == 200 and package_code in by_id,
        )

        response = page.goto(f"{web}/trace/HC-PKG-2099-999999", wait_until="networkidle")
        page.wait_for_timeout(1500)
        unknown = main_text(page)
        check(
            "an unknown code is reported as invalid, never as an empty record",
            "Invalid QR Code" in unknown or "could not trace" in unknown.lower(),
            unknown[:200],
        )

        browser.close()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("\nFailures:")
        for description in FAILED:
            print(f"  - {description}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
