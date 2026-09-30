"""The consumer's path, end to end, on a real package — browser + API + real chain.

This is the diagnostic-and-fix verification for the customer QR flow. One real
package, created by the real workflow, is taken through:

    real package → QR issued → QR id stable across reloads and sessions
      → the public page opens with no account → the report is the record
      → the same QR id resolves to the same package (and a second package to its own)
      → an unknown code is refused, safely
      → the QR_GENERATED event exists once, with a real tx_id, on the real ledger
      → the signed-in consumer's workspace renders the same record

Nothing here is stubbed: the API is the running HoneyChain API, the pages are the
built frontend, and the ledger is the real service at ``BLOCKCHAIN_BASE_URL``.

Usage (API on :8000, web on :4173, blockchain service reachable)::

    cd backend
    .venv/bin/python tests/consumer_qr_verification.py

Exit code 0 means every check passed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from tests.api_smoke_phase7 import request  # noqa: E402
from tests.browser_master_workflow import ADMIN, sign_in_page  # noqa: E402
from tests.phase8_blockchain_workflow import (  # noqa: E402  — reuse, do not rebuild
    DEFAULT_API,
    DEFAULT_CHAIN,
    events_for,
    read_chain,
)
from tests.phase8_ui_checks import (  # noqa: E402
    DEFAULT_WEB,
    main_text,
    newest_traced_batch,
)

PASSED: list[str] = []
FAILED: list[str] = []


def check(description: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(description)
    suffix = f" — {detail}" if detail and not condition else ""
    print(f"  {'PASS' if condition else 'FAIL'}  {description}{suffix}")


def section(title: str) -> None:
    print(f"\n=== {title}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Consumer QR verification checks")
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--web-url", default=DEFAULT_WEB)
    parser.add_argument("--ledger-url", default=DEFAULT_CHAIN)
    args = parser.parse_args()
    api = args.api_url.rstrip("/")
    web = args.web_url.rstrip("/")

    admin = request("POST", "/auth/login", base=api, body=dict(zip(("email", "password"), ADMIN)))[1][
        "data"
    ]["access_token"]

    # ---------------------------------------------------------------------- #
    section("A real package, from the real workflow")
    # ---------------------------------------------------------------------- #
    batch_code, _batch_id, package_code, package_id, _packaging_code = newest_traced_batch(api, admin)
    check("a real package exists in the database", bool(package_code), "none found")
    print(f"  package {package_code} (batch {batch_code})")

    status, payload = request("GET", f"/packages/{package_id}", base=api, token=admin)
    package = payload.get("data") or {} if status == 200 else {}
    check("it is a real package row", status == 200 and bool(package), f"{status} {payload}")
    check(
        "it belongs to a real batch",
        bool(package.get("batch_code")) or bool(package.get("batch_id")),
        json.dumps(package)[:200],
    )

    # The customer's report must name real places and real quantities, not the
    # shape of a column: this is where "KG" was once reported as the facility a
    # batch was processed at.
    status, payload = request("GET", f"/trace/{package_code}", base=api)
    report = payload.get("data") or {}
    facilities = [row.get("facility") for row in (report.get("processing") or [])]
    status, payload = request("GET", "/processing-units?page_size=100", base=api, token=admin)
    known_units = {row.get("name") for row in (payload.get("data") or [])}
    check(
        "no processing stage reports a unit of measure as its facility",
        all(name not in ("KG", "Kg", "LITRE", "Litre", "kg") for name in facilities),
        f"facilities={facilities}",
    )
    check(
        "a named facility is a real processing unit, and a blank one is blank",
        all(name is None or name in known_units for name in facilities),
        f"facilities={facilities} vs units={sorted(u for u in known_units if u)}",
    )
    check(
        "the packing stage names the packing unit",
        bool((report.get("packaging") or {}).get("facility")),
        f"packaging={report.get('packaging')}",
    )

    # ---------------------------------------------------------------------- #
    section("The QR identity belongs to the package, and is stable")
    # ---------------------------------------------------------------------- #
    status, payload = request("POST", f"/blockchain/packages/{package_id}/qr", base=api, token=admin)
    first = payload.get("data") or {}
    check("the QR identity is issued for this package", status == 200 and bool(first), f"{status}")
    qr_id = first.get("qr_id")
    check(
        "the QR id is derived from this package, not the batch",
        qr_id == f"QR-{package_code}",
        f"{qr_id} vs QR-{package_code}",
    )
    check(
        "it encodes this package's verification URL",
        str(first.get("qr_payload") or "").rstrip("/").endswith(package_code),
        str(first.get("qr_payload")),
    )
    check(
        "the label is really drawn",
        "<svg" in (first.get("svg") or ""),
        "no SVG returned",
    )
    # The label panel names the transaction behind the label in hand. In a batch
    # of many packages, "the batch's first QR event" is a different jar's.
    check(
        "the label panel reports this package's own QR event",
        first.get("event_id") == f"QR-{package_code}-GENERATED",
        f"event_id={first.get('event_id')}",
    )
    check(
        "the label panel reports a transaction id, not a batchmate's",
        bool(first.get("tx_id")),
        "no tx_id on the label",
    )

    status, payload = request("POST", f"/blockchain/packages/{package_id}/qr", base=api, token=admin)
    again = payload.get("data") or {}
    check(
        "re-issuing returns the same QR identity",
        again.get("qr_id") == qr_id and again.get("qr_payload") == first.get("qr_payload"),
        f"{again.get('qr_id')} / {again.get('qr_payload')}",
    )
    check(
        "and writes nothing new",
        again.get("event_id") == first.get("event_id"),
        f"{again.get('event_id')} vs {first.get('event_id')}",
    )

    # ---------------------------------------------------------------------- #
    section("The ledger: one QR_GENERATED event, a real tx_id")
    # ---------------------------------------------------------------------- #
    rows = events_for(api, admin, batch_code)
    # A QR_GENERATED payload names the package the label belongs to as
    # `package_id` — the package code, which is the identifier the chain uses.
    qr_events = [
        row
        for row in rows
        if row["tx_type"] == "QR_GENERATED"
        and (row.get("payload") or {}).get("package_id") == package_code
    ]
    check(
        "the QR_GENERATED event exists for this package",
        len(qr_events) == 1,
        f"{len(qr_events)} events",
    )
    if qr_events:
        event = qr_events[0]
        check(
            "it is confirmed with a transaction id",
            event["status"] == "CONFIRMED" and bool(event.get("tx_id")),
            f"{event['status']} / {event.get('tx_id')}",
        )
        check(
            "the event names this package and its event id",
            event.get("event_id") == f"QR-{package_code}-GENERATED",
            str(event.get("event_id")),
        )
        chain = {row.get("tx_id"): row for row in read_chain(args.ledger_url)}
        check(
            "the transaction is in the service's own ledger",
            event.get("tx_id") in chain,
            f"{event.get('tx_id')} not found among {len(chain)} transactions",
        )
        if event.get("tx_id") in chain:
            chain_row = chain[event["tx_id"]]
            check(
                "the chain row names this batch",
                chain_row.get("batch_id") == batch_code,
                f"{chain_row.get('batch_id')} != {batch_code}",
            )
            payload = chain_row.get("payload") or {}
            check(
                "the chain row names this package",
                payload.get("package_id") == package_code or payload.get("package_code") == package_code,
                json.dumps(payload)[:200],
            )
            check(
                "the chain row names this package's QR id",
                payload.get("qr_id") == qr_id,
                str(payload.get("qr_id")),
            )
            print(f"  tx_id {event['tx_id']} · {chain_row.get('timestamp')}")

    # ---------------------------------------------------------------------- #
    section("A customer opens the label — no account")
    # ---------------------------------------------------------------------- #
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        console_errors: list[str] = []
        #: URLs that answered with a client/server error, so a *deliberate*
        #: refusal (looking up a code that does not exist, below) is not counted
        #: as a defect while a real one still is.
        refused: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on(
            "response",
            lambda r: refused.append(f"{r.status} {r.request.method} {r.url}")
            if r.status >= 400
            else None,
        )
        page.browser_context = None  # keep linters quiet about the unused attribute

        response = page.goto(f"{web}/trace/{package_code}", wait_until="networkidle")
        page.wait_for_timeout(1500)
        public = main_text(page)
        check("the code resolves with no sign-in", response is not None and response.status == 200)
        check("the page names this package", package_code in public, public[:200])
        check("it states the QR id", qr_id in public, "no QR id on the page")
        check("it shows the journey", "The journey of this honey" in public)
        for name in facilities + [(report.get("packaging") or {}).get("facility")]:
            if name:
                check(f"the page names {name}", name in public, "not on the page")
        check("it shows the blockchain record", "Blockchain record" in public)
        check("it prints the real transaction", (qr_events[0].get("tx_id") or "")[:16] in public if qr_events else False, "tx id missing")

        # The QR id resolves on its own route, to the same package.
        response = page.goto(f"{web}/verify/{qr_id}", wait_until="networkidle")
        page.wait_for_timeout(1500)
        by_id = main_text(page)
        check(
            "the QR id resolves to the same package",
            response is not None and response.status == 200 and package_code in by_id,
        )

        # Reloading changes nothing: same id, same package, same record.
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1200)
        check("a reload shows the same record", package_code in main_text(page) and qr_id in main_text(page))

        # A different package must not resolve to the first one.
        status, payload = request(
            "GET", f"/batches/{package.get('batch_id')}/packages?page_size=100", base=api, token=admin
        )
        siblings = [row for row in (payload.get("data") or []) if row["package_code"] != package_code]
        other = None
        other_id = None
        other_tx = None
        if siblings:
            other = siblings[0]["package_code"]
            other_uuid = siblings[0]["id"]
            response = page.goto(f"{web}/verify/QR-{other}", wait_until="networkidle")
            page.wait_for_timeout(1200)
            other_text = main_text(page)
            check(
                "a second package of the same batch resolves to itself",
                other in other_text and package_code not in other_text,
                f"expected {other} and not {package_code}",
            )
        else:
            check("the batch has more than one package to tell apart", False, "only one package")

        # An unknown code is refused, and discloses nothing.
        response = page.goto(f"{web}/verify/INVALID-QR-123", wait_until="networkidle")
        page.wait_for_timeout(1200)
        unknown = main_text(page)
        check(
            "an unknown QR is refused as invalid",
            "Invalid QR Code" in unknown or "verification unavailable" in unknown.lower(),
            unknown[:200],
        )
        check(
            "the refusal leaks no internals",
            "traceback" not in unknown.lower()
            and "sql" not in unknown.lower()
            and "postgres" not in unknown.lower(),
        )

        # ------------------------------------------------------------------ #
        section("The customer's page carries this package, not the ledger")
        # ------------------------------------------------------------------ #
        # Another package's transaction must not be visible here: the browser is
        # sent the events of the package in hand, resolved server-side — never the
        # global ledger.
        # Read the report's own ledger list: the page must not carry another
        # jar's rows. The sibling's QR event is the sharpest case — it is a
        # different product's label.
        scoped = [
            json.dumps(row)
            for row in (report.get("blockchain") or {}).get("transactions") or []
        ]
        own_creations = [
            row
            for row in (report.get("blockchain") or {}).get("transactions") or []
            if row.get("tx_type") == "PACKAGE_CREATED"
        ]
        check(
            "the customer's ledger holds one package creation: this package's",
            len(own_creations) == 1,
            f"{len(own_creations)} PACKAGE_CREATED rows on a single jar's page",
        )
        for row in scoped:
            check(
                "no other package's record is on this page",
                "-GENERATED" not in row or package_code in row,
                row[:160],
            )

        if other:
            # Two labelled packages in one batch is the case that used to leak:
            # the batch's rows were handed to whichever package asked. The
            # batchmate is labelled through the same authorised endpoint, so both
            # jars have a real label and a real transaction of their own.
            status, payload = request(
                "POST", f"/blockchain/packages/{other_uuid}/qr", base=api, token=admin
            )
            sibling_label = payload.get("data") or {}
            check(
                "the batchmate can be labelled too",
                status == 200 and sibling_label.get("qr_id") == f"QR-{other}",
                f"{status} {sibling_label.get('qr_id')}",
            )
            other_event = f"QR-{other}-GENERATED"
            # The label is written in the same transaction as its event; the
            # outbox worker takes it to the chain within its interval, so the
            # transaction id is waited for rather than demanded instantly.
            other_tx = None
            for _ in range(20):
                status, payload = request(
                    "GET", f"/blockchain/transactions?search={other_event}", base=api, token=admin
                )
                other_rows = payload.get("data") or []
                other_tx = other_rows[0].get("tx_id") if other_rows else None
                if other_tx:
                    break
                time.sleep(2)
            check(
                "the batchmate has a QR transaction of its own",
                bool(other_tx),
                f"no QR_GENERATED transaction for {other}",
            )
            check(
                "the batchmate's label names its own event, not this jar's",
                sibling_label.get("event_id") == other_event,
                f"event_id={sibling_label.get('event_id')}",
            )

            # Read this jar's report and page again *after* the batchmate was
            # labelled: the row that used to leak is the one just written.
            status, payload = request("GET", f"/trace/{package_code}", base=api)
            fresh = payload.get("data") or {}
            on_page = " ".join(
                json.dumps(row)
                for row in (fresh.get("blockchain") or {}).get("transactions") or []
            )
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(1500)
            stranger_page = main_text(page)
            check(
                "this jar's page carries none of the batchmate's records",
                bool(other_tx)
                and other_tx not in on_page
                and other_event not in on_page
                and other not in on_page
                and other_tx not in stranger_page,
                "another package's transaction is on this page",
            )

            status, payload = request("GET", f"/trace/{other}", base=api)
            other_report = payload.get("data") or {}
            other_rows_on_page = " ".join(
                json.dumps(row)
                for row in (other_report.get("blockchain") or {}).get("transactions") or []
            )
            own_event = f"QR-{package_code}-GENERATED"
            check(
                "and the batchmate's page carries none of this jar's records",
                status == 200
                and own_event not in other_rows_on_page
                and package_code not in other_rows_on_page,
                f"{status} — this jar's rows are on the batchmate's page",
            )
            check(
                "each jar's report shows its own label event",
                f"QR-{other}-GENERATED" in other_rows_on_page and own_event in on_page,
                "a label event is missing from its own page",
            )

        # ------------------------------------------------------------------ #
        section("Verification is a read: the customer can change nothing")
        # ------------------------------------------------------------------ #
        consumer = request(
            "POST",
            "/auth/login",
            base=api,
            body={"email": "consumer@honeychain.example.com", "password": "ConsumerPass123"},
        )[1].get("data", {})
        consumer_token = consumer.get("access_token")
        check("the consumer account can sign in", bool(consumer_token))
        for method, path, what in (
            ("POST", f"/blockchain/packages/{package_id}/qr", "create a QR identity"),
            ("POST", "/blockchain/sync", "write to the blockchain"),
            ("POST", f"/packages/{package_id}/release", "release a package"),
            ("GET", "/blockchain/transactions", "read the platform's ledger"),
        ):
            status, _payload = request(method, path, base=api, token=consumer_token, body={})
            check(
                f"the consumer cannot {what}",
                status in (401, 403),
                f"{method} {path} answered {status}",
            )
        status, _payload = request("POST", f"/blockchain/packages/{package_id}/qr", base=api, body={})
        check("an anonymous caller cannot create a QR identity", status in (401, 403), str(status))
        status, _payload = request("GET", f"/trace/{package_code}", base=api)
        check("an anonymous caller can still verify a jar", status == 200, str(status))

        # ------------------------------------------------------------------ #
        section("The consumer's own workspace — signed in")
        # ------------------------------------------------------------------ #
        sign_in_page(page, ("consumer@honeychain.example.com", "ConsumerPass123"))
        page.goto(f"{web}/consumer", wait_until="networkidle")
        page.wait_for_timeout(1500)
        workspace = main_text(page)
        check("the consumer workspace opens", "Consumer workspace" in workspace, workspace[:200])
        check("it offers real verification", "Verify a product" in workspace)
        check(
            "it no longer claims verification is a later phase",
            "not part of this release" not in workspace.lower(),
            "the old placeholder is still rendered",
        )

        page.fill("input[name='code']", qr_id)
        page.click("button[type='submit']")
        page.wait_for_timeout(2500)
        typed = main_text(page)
        check("typing the QR id renders the same record", package_code in typed, typed[:200])
        # The field keeps what was typed — one keystroke at a time, no remount.
        page.fill("input[name='code']", "")
        for character in package_code:
            page.keyboard.type(character, delay=15)
        page.wait_for_timeout(400)
        value = page.input_value("input[name='code']")
        check(
            "the code field keeps every character that was typed",
            value == package_code,
            f"field holds {value!r}",
        )

        # The only refusals this walk should produce are the deliberate ones: the
        # unknown code, and the QR id of a package whose label was never issued.
        deliberate = [url for url in refused if "INVALID-QR-123" in url]
        unexpected = [url for url in refused if "INVALID-QR-123" not in url]
        check(
            "the unknown code was refused by the API, not by the page",
            bool(deliberate),
            f"refusals seen: {refused[:3]}",
        )
        check(
            "nothing else was refused during the walk",
            not unexpected,
            "; ".join(sorted(set(unexpected))[:3]),
        )
        check(
            "no console errors other than the deliberate refusal",
            len(console_errors) <= len(deliberate),
            f"{console_errors[:3]} | refused: {sorted(set(refused))[:3]}",
        )
        browser.close()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("Failures:")
        for failure in FAILED:
            print(f"  - {failure}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
