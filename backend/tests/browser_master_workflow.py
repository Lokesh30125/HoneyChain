"""The whole chain, once, through the screens a real user gets.

`tests/api_smoke_phase7.py` proves the rules over HTTP and the pytest suites prove
them in the database. This script proves the part neither can: that the **screens**
carry the same records from one end of the supply chain to the other — that work
leaving one role's queue actually arrives in the next role's, that the buttons are
wired to the endpoints, and that a refresh does not undo any of it.

It is one continuous run, because the failures worth catching here are the seams.
The steps, in the order a batch travels:

 1. A TEST beekeeper is registered, given a hive, and joined to a real cluster by
    the administrator — so the batch that comes out of the harvest carries its
    cluster rather than an empty column.
 2. The harvest is recorded and completed; **one** batch is created, carrying
    cluster, beekeeper, collection and source hives (never one batch per hive).
 3. The batch is processed: the run is allocated to the named processor account,
    accepted, started, recorded and completed, which is what puts the batch in the
    laboratory.
 4. The beekeeper's screens show the hive, the harvest with its batch, and the
    batch register.
 5. The KVIC officer's screens show the cluster, its batches, the batch detail and
    the traceability timeline — read from the records, with the later stages
    genuinely not started rather than blank.
 6. The collection centre's screen lists the same harvest read-only, in its own
    workspace, with no form it does not own.
 7. The processor's screens show the run that was allocated, and its detail shows
    what was done to the honey.
 8. The laboratory worklist offers the batch (a test waiting to be opened — not
    "awaiting a sample" with nothing behind it), and the technician records a
    measurement through the catalogue dropdown.
 9. The technician completes the test; the laboratory's own rules decide it, the
    test reaches COMPLETED, the batch becomes APPROVED, and both queues agree.
10. The packaging unit sees the approved batch, opens a run with a hand-typed
    container ("Other"), completes it and gets real, individual package codes.
11. The packaging information screen reports the batch, the quantities and the
    package codes from those same rows, and the stock screen lists them.
12. The distributor's screen offers the released packages and names the batch they
    came from.
13. The timeline on the officer's screen shows the laboratory and packaging stages
    from the records, not from a template.

Every record is produced by the application — nothing is inserted behind its back.
Sign-in details come from the seeded accounts plus the accounts this run creates
through the administrator's directory; everything it creates is marked TEST.

Usage (API and the built frontend must be running)::

    cd backend
    .venv/bin/python tests/browser_master_workflow.py

Exit code 0 means the journey worked end to end through the interface.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import Page, sync_playwright  # noqa: E402

from tests.api_smoke_phase7 import (  # noqa: E402
    configure_parameter,
    harvest_batch,
    make_hive,
    process_batch,
    register_keeper,
    request,
    sign_in,
)

DEFAULT_API = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")
DEFAULT_WEB = os.getenv("SMOKE_BASE_URL", "http://localhost:4173")
BASE_WEB = DEFAULT_WEB

ADMIN = ("admin@honeychain.example.com", "AdminSecure123")
OFFICER = ("kvic@honeychain.example.com", "KvicSecure123")
PROCESSOR = ("processor@honeychain.example.com", "ProcessPass123")
LABTECH = ("labtech@honeychain.example.com", "LabTechPass123")

PACKER_PASSWORD = "PackUnitPass123"
DISTRIBUTOR_PASSWORD = "DistributorPass123"
CENTRE_PASSWORD = "CentrePass123"
RETAILER_PASSWORD = "RetailerPass123"

PASSED: list[str] = []
FAILED: list[str] = []


def check(description: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(description)
    suffix = f" — {detail}" if detail and not condition else ""
    print(f"  {'PASS' if condition else 'FAIL'}  {description}{suffix}")


def section(title: str) -> None:
    print(f"\n=== {title}")


def staging_email(role: str) -> str:
    """A fresh address per run, marked as test data in the address itself."""
    return f"master.{role}.{uuid.uuid4().hex[:8]}@honeychain.example.com"


def create_account(
    api: str,
    admin_token: str,
    *,
    role: str,
    email: str,
    password: str,
    district: str | None = None,
    organization: str | None = None,
    name_suffix: str | None = None,
) -> dict:
    """Create a supply-chain account through the administrator's directory.

    Public registration offers two roles and always will; every other role is
    created here, by the administrator, exactly as it is in production.
    """
    body = {
        "name": (
            f"Master Workflow {role.title().replace('_', ' ')} TEST"
            + (f" {name_suffix}" if name_suffix else "")
        ),
        "email": email,
        "password": password,
        "role": role,
        "phone": f"+9198{uuid.uuid4().int % 100000000:08d}",
        "reason": "Created by the master workflow probe (TEST data)",
    }
    if district:
        body["district"] = district
    if organization:
        body["organization"] = organization
    status, payload = request("POST", "/admin/users", base=api, token=admin_token, body=body)
    if status not in (200, 201):
        raise SystemExit(f"Could not create the {role} account: {status} {payload}")
    # The answer names the account it created; the *id* is what the run needs when
    # it addresses a shipment to this shop.
    return (payload.get("data") or {}).get("user") or payload.get("data") or {}


def sign_in_page(page: Page, credentials: tuple[str, str]) -> None:
    """Sign in from a clean slate: a live session would redirect away from /login."""
    email, password = credentials
    page.goto(f"{BASE_WEB}/login", wait_until="domcontentloaded")
    page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
    page.goto(f"{BASE_WEB}/login", wait_until="networkidle")
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", password)
    page.click("button[type='submit']")
    page.wait_for_url(lambda url: "/login" not in url, timeout=20000)
    page.wait_for_load_state("networkidle")


def main_text(page: Page) -> str:
    """Everything the page says, minus the chrome (so nav labels do not mislead)."""
    body = page.locator("main")
    if body.count():
        return body.first.inner_text()
    return page.locator("body").inner_text()


# --------------------------------------------------------------------------- #
# Arrangement — real records, produced by the application itself
# --------------------------------------------------------------------------- #
def arrange(api: str) -> dict:
    admin = sign_in(api, *ADMIN)
    processor_tokens = sign_in(api, *PROCESSOR)
    status, payload = request("GET", "/auth/me", base=api, token=processor_tokens)
    if status != 200:
        raise SystemExit(f"Could not read the processor account: {status} {payload}")
    processor = {"token": processor_tokens, "user_id": payload["data"]["id"]}

    # A cluster from the registry, so the batch's cluster is a real relationship and
    # not a column this script filled in by hand.
    status, payload = request("GET", "/clusters?page_size=5", base=api, token=admin)
    if status != 200 or not payload.get("data"):
        raise SystemExit(f"Could not read the cluster registry: {status} {payload}")
    cluster = payload["data"][0]

    packer_email = staging_email("packer")
    distributor_email = staging_email("distributor")
    centre_email = staging_email("centre")
    retailer_email = staging_email("retailer")
    other_retailer_email = staging_email("retailer-other")
    packer = create_account(
        api,
        admin,
        role="PACKAGING_UNIT",
        email=packer_email,
        password=PACKER_PASSWORD,
        organization="Master Workflow Packing Unit (TEST)",
    )
    # The operator is put to work at a facility, because an operator with no unit
    # has nowhere to open a run: the workspace states the unit and the run is
    # recorded against it, so the packing account has to have one before it can
    # pack anything. The unit is registered by the administrator, as it is in the
    # Administration → Packaging Units screen, and the account is attached to it.
    status, payload = request("GET", "/packaging-units?page_size=1", base=api, token=admin)
    units = payload.get("data") or []
    if status != 200 or not units:
        status, payload = request(
            "POST",
            "/packaging-units",
            base=api,
            token=admin,
            body={
                "name": "Master Workflow Packing Unit (TEST)",
                "registration_identifier": f"REG-MW-{uuid.uuid4().hex[:6]}",
                "district": "Guntur",
                "state": "Andhra Pradesh",
                "status": "ACTIVE",
            },
        )
        if status != 201:
            raise SystemExit(f"Could not register a packaging unit: {status} {payload}")
        units = [payload["data"]]
    packaging_unit = units[0]
    status, payload = request(
        "POST",
        f"/packaging-units/{packaging_unit['id']}/members",
        base=api,
        token=admin,
        body={"user_id": (packer.get("user") or {}).get("id") or packer.get("id")},
    )
    if status not in (200, 201):
        raise SystemExit(f"Could not attach the operator to the unit: {status} {payload}")
    create_account(
        api,
        admin,
        role="DISTRIBUTOR",
        email=distributor_email,
        password=DISTRIBUTOR_PASSWORD,
        organization="Master Workflow Distribution (TEST)",
    )
    # The shop the consignment is addressed to. A shipment names a *retailer
    # account* — that is what puts it in that shop's inbound list and lets the
    # receipt be confirmed by the receiver — so the run arranges one, as an
    # administrator would in Administration → Users.
    retailer = create_account(
        api,
        admin,
        role="RETAILER",
        email=retailer_email,
        password=RETAILER_PASSWORD,
        district="Guntur",
        organization="Master Workflow Retail TEST",
        name_suffix="Guntur Shop",
    )
    # A second shop that this consignment is *not* for. Without it "the retailer
    # sees the shipment" would not distinguish a correct scope from a scope that
    # shows a delivery to every shop on the platform.
    other_retailer = create_account(
        api,
        admin,
        role="RETAILER",
        email=other_retailer_email,
        password=RETAILER_PASSWORD,
        district="Krishna",
        organization="Master Workflow Other Retail TEST",
        name_suffix="Krishna Shop",
    )
    create_account(
        api,
        admin,
        role="COLLECTION_CENTER",
        email=centre_email,
        password=CENTRE_PASSWORD,
        district=cluster.get("district") or "Guntur",
        organization="Master Workflow Collection Centre (TEST)",
    )

    keeper = register_keeper(api)
    # The beekeeper joins the cluster the way the platform does it — an
    # administrator's edit of the beekeeper record — and the harvest inherits it.
    status, payload = request("GET", "/beekeepers/me", base=api, token=keeper["token"])
    if status != 200:
        raise SystemExit(f"Could not read the beekeeper record: {status} {payload}")
    status, payload = request(
        "PUT",
        f"/beekeepers/{payload['data']['id']}",
        base=api,
        token=admin,
        body={"kvic_cluster_id": cluster["id"]},
    )
    if status != 200:
        raise SystemExit(f"Could not join the beekeeper to the cluster: {status} {payload}")

    hive = make_hive(api, keeper["token"])
    batch = harvest_batch(api, keeper, hive, "13.7")
    run = process_batch(api, admin, processor, batch["id"], "12.9")
    # A verdict needs a limit to judge against; it is configured the way the
    # platform requires — stated, sourced and described as a demonstration limit.
    configure_parameter(api, admin, "MOISTURE", "10", "20")

    status, payload = request("GET", f"/batches/{batch['id']}", base=api, token=admin)
    batch = payload["data"]
    # The collection code the batch came from, as the API reports it.
    collection_code = (batch.get("collection") or {}).get("collection_code")
    return {
        "admin": admin,
        "processor": processor,
        "keeper": keeper,
        "hive": hive,
        "cluster": cluster,
        "batch": batch,
        "collection_code": collection_code,
        "run": run,
        "packer": (packer_email, PACKER_PASSWORD),
        "packaging_unit": packaging_unit,
        "distributor": (distributor_email, DISTRIBUTOR_PASSWORD),
        "retailer": (retailer_email, RETAILER_PASSWORD),
        "retailer_id": retailer.get("id"),
        "retailer_name": retailer.get("name"),
        "retailer_other": (other_retailer_email, RETAILER_PASSWORD),
        "retailer_other_id": other_retailer.get("id"),
        "centre": (centre_email, CENTRE_PASSWORD),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--web-url", default=DEFAULT_WEB)
    parser.add_argument("--headless", action="store_true", default=True)
    args = parser.parse_args()

    global BASE_WEB  # noqa: PLW0603 - the sign-in helper reads it
    BASE_WEB = args.web_url.rstrip("/")
    api = args.api_url.rstrip("/")

    print(f"Master workflow in a browser — {BASE_WEB} against {api}")

    section("A harvest becomes one batch, inside a cluster")
    arrangement = arrange(api)
    batch = arrangement["batch"]
    check(
        "the batch carries the cluster of its beekeeper",
        batch.get("cluster_id") == arrangement["cluster"]["id"],
        f"batch cluster={batch.get('cluster_id')} expected={arrangement['cluster']['id']}",
    )
    check(
        "the batch carries its collection and beekeeper",
        bool(batch.get("collection_id")) and bool(batch.get("beekeeper_id")),
        f"collection={batch.get('collection_id')} beekeeper={batch.get('beekeeper_id')}",
    )
    check(
        "the collection the batch came from is a real record",
        bool(arrangement["collection_code"]),
        "the batch detail carries no collection",
    )
    check(
        "the batch has one source hive, from its collection",
        int(batch.get("source_hive_count") or 0) == 1,
        f"source_hive_count={batch.get('source_hive_count')}",
    )
    check(
        "completing the processing run moved the batch to the laboratory",
        str(batch["status"]) == "LAB_TESTING",
        f"status={batch['status']}",
    )

    # The other shop's credentials are used through the API rather than the screen:
    # the browser checks below are about what the receiving shop's own workspace
    # shows, and the isolation of a *third* account is a question for the API.
    other_retailer_token = sign_in(api, *arrangement["retailer_other"])

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1100})
        console_errors: list[str] = []
        #: Which request produced a console error — a bare "403" says nothing
        #: about the screen that asked for it, and 4xx answers are part of this
        #: run (a role is deliberately refused things it may not open).
        rejected_requests: list[str] = []
        #: URLs that answered 5xx during the run.
        failed_requests: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))
        page.on(
            "response",
            lambda r: rejected_requests.append(f"{r.status} {r.request.method} {r.url}")
            if 400 <= r.status < 500 and "/api/" in r.url
            else None,
        )
        # A "failed to load resource" line says nothing about *which* call failed, so
        # the run records the URLs that answered 5xx as well. A server error during a
        # walk through every role is a defect worth naming, not a line to count.
        page.on(
            "response",
            lambda r: failed_requests.append(f"{r.status} {r.request.method} {r.url}")
            if r.status >= 500
            else None,
        )

        # ------------------------------------------------------------------ #
        section("The KVIC officer sees the cluster, its batch and the timeline")
        # ------------------------------------------------------------------ #
        sign_in_page(page, OFFICER)
        page.wait_for_timeout(800)
        check(
            "the officer lands in the KVIC workspace",
            "/kvic" in page.url,
            f"landed on {page.url}",
        )
        page.goto(f"{BASE_WEB}/kvic/clusters", wait_until="networkidle")
        page.wait_for_timeout(1500)
        check(
            "the cluster is listed with its code",
            arrangement["cluster"]["cluster_code"] in main_text(page),
            "the cluster registry does not show the cluster",
        )
        page.goto(f"{BASE_WEB}/kvic/batches", wait_until="networkidle")
        page.wait_for_timeout(1500)
        check(
            "the cluster's batch is on the officer's batch list",
            batch["batch_code"] in main_text(page),
            "the batch is not visible to the officer",
        )
        page.goto(
            f"{BASE_WEB}/kvic/traceability/{batch['id']}", wait_until="networkidle"
        )
        page.wait_for_timeout(1800)
        timeline = main_text(page)
        check(
            "the timeline shows the collection and processing stages",
            "Collection" in timeline and "Processing" in timeline,
            "the stages are not rendered",
        )
        check(
            "the timeline names the processing run that really happened",
            arrangement["run"]["processing_code"] in timeline,
            "the run code is missing from the timeline",
        )
        check(
            "the timeline does not claim a laboratory result that does not exist",
            "Not started" in timeline or "In progress" in timeline,
            "no honest laboratory state on the timeline",
        )

        # ------------------------------------------------------------------ #
        section("The beekeeper sees the hive, the harvest and the batch")
        # ------------------------------------------------------------------ #
        sign_in_page(page, (arrangement["keeper"]["email"], "SmokeP7Pass123"))
        page.goto(f"{BASE_WEB}/beekeeper/hives", wait_until="networkidle")
        page.wait_for_timeout(1200)
        check(
            "the hive the harvest came from is on the beekeeper's hive list",
            arrangement["hive"]["hive_code"] in main_text(page),
            f"{arrangement['hive']['hive_code']} is not listed",
        )
        page.goto(f"{BASE_WEB}/beekeeper/collections", wait_until="networkidle")
        page.wait_for_timeout(1500)
        collections_text = main_text(page)
        check(
            "the harvest is listed with the batch it produced",
            batch["batch_code"] in collections_text,
            "the batch code is not on the collections screen",
        )
        page.goto(f"{BASE_WEB}/beekeeper/batches", wait_until="networkidle")
        page.wait_for_timeout(1500)
        check(
            "the batch is in the beekeeper's own batch register",
            batch["batch_code"] in main_text(page),
            "the batch is not in the register",
        )
        page.goto(f"{BASE_WEB}/beekeeper/traceability/{batch['id']}", wait_until="networkidle")
        page.wait_for_timeout(1500)
        check(
            "the beekeeper can follow their own batch's timeline",
            "Collection" in main_text(page),
            "the beekeeper's timeline did not render",
        )

        # ------------------------------------------------------------------ #
        section("The collection centre lists the same harvests, read-only")
        # ------------------------------------------------------------------ #
        sign_in_page(page, arrangement["centre"])
        page.wait_for_timeout(800)
        check(
            "the collection centre lands in its own workspace",
            "/collection-center" in page.url,
            f"landed on {page.url}",
        )
        page.goto(f"{BASE_WEB}/collection-center", wait_until="networkidle")
        page.wait_for_timeout(1800)
        centre_text = main_text(page)
        check(
            "the harvest is listed at the centre with its code",
            arrangement["collection_code"] in centre_text,
            f"{arrangement['collection_code']} is not listed",
        )
        check(
            "the centre is not offered a form it does not own",
            "Record a collection" not in centre_text and "Record harvest" not in centre_text,
            "a write control is rendered for a read-only role",
        )

        # ------------------------------------------------------------------ #
        section("The processor's screens carry the allocated run")
        # ------------------------------------------------------------------ #
        sign_in_page(page, PROCESSOR)
        page.wait_for_timeout(800)
        check(
            "the processor lands in the processing workspace",
            "/processor" in page.url,
            f"landed on {page.url}",
        )
        page.goto(f"{BASE_WEB}/processor/runs", wait_until="networkidle")
        page.wait_for_timeout(1800)
        check(
            "the run is in the processor's own list",
            arrangement["run"]["processing_code"] in main_text(page),
            "the run is not listed",
        )
        page.goto(
            f"{BASE_WEB}/processor/runs/{arrangement['run']['id']}", wait_until="networkidle"
        )
        page.wait_for_timeout(1500)
        run_text = main_text(page)
        check(
            "the run detail shows the batch and what was done to it",
            batch["batch_code"] in run_text and "Filtering" in run_text,
            "the run detail does not show its batch and type",
        )
        check(
            "the run detail shows the measured quantities",
            "13.7" in run_text and "12.9" in run_text,
            "the quantities are not shown",
        )

        # ------------------------------------------------------------------ #
        section("The laboratory opens the test")
        # ------------------------------------------------------------------ #
        sign_in_page(page, LABTECH)
        # An API token for the same account the browser is signed in as, so the
        # clearing of a demonstration value below is done as the technician who is
        # allowed to do it rather than as a script with extra rights.
        tech_token = sign_in(api, *LABTECH)
        page.wait_for_timeout(800)
        page.goto(f"{BASE_WEB}/laboratory/awaiting", wait_until="networkidle")
        page.wait_for_timeout(1800)
        open_button = page.locator(f"[data-testid='open-test-{batch['batch_code']}']")
        check(
            "the batch that left processing is on the laboratory's worklist",
            open_button.count() == 1,
            "no action offered for the batch that just arrived",
        )
        test_id = None
        if open_button.count():
            open_button.first.click()
            page.locator("div[role='dialog']").wait_for(state="visible", timeout=10000)
            quantity = page.locator("input[name='sample_quantity']").first
            check(
                "the sample quantity starts empty rather than pre-filled",
                quantity.count() == 1 and quantity.input_value() == "",
                f"field holds {quantity.input_value()!r}" if quantity.count() else "no field",
            )
            if quantity.count():
                quantity.click()
                page.keyboard.type("250", delay=30)
                check(
                    "the sample quantity takes the whole number in one go",
                    quantity.input_value() == "250",
                    f"field holds {quantity.input_value()!r}",
                )
            create = page.locator("[data-testid='create-test']").first
            if create.count():
                create.click()
            else:
                page.get_by_role("button", name="Open the test").first.click()
            page.wait_for_url(lambda url: "/laboratory/tests/" in url, timeout=20000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1200)
            test_id = page.url.rstrip("/").rsplit("/", 1)[-1]

        check(
            "opening the test took the technician to the test's own screen",
            bool(test_id),
            f"url is {page.url}",
        )

        # ------------------------------------------------------------------ #
        section("A measurement is recorded through the platform's own controls")
        # ------------------------------------------------------------------ #
        # The development profile pre-fills a demonstration value for every
        # configured parameter, and the panel deliberately excludes parameters that
        # are already recorded — so on an installation with the demo configuration
        # in place there is nothing left to *add* until the demonstration row is
        # cleared. Removing it is a supported action on an open test and is exactly
        # what the row tells the technician to do ("confirm or replace it").
        status, detail = request("GET", f"/lab-tests/{test_id}", base=api, token=tech_token)
        existing = next(
            (
                row
                for row in (detail.get("data") or {}).get("results", [])
                if row.get("parameter_code") == "MOISTURE"
            ),
            None,
        ) if status == 200 else None
        check(
            "a demonstration value is on the test, and is labelled as one",
            existing is None or existing.get("measurement_source") == "DEMO",
            str((existing or {}).get("measurement_source")),
        )
        if existing:
            request(
                "DELETE",
                f"/lab-tests/{test_id}/results/{existing['id']}",
                base=api,
                token=tech_token,
            )
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(1200)

        record = page.get_by_role("button", name="Record a measurement").first
        check(
            "the test screen offers the measurement control",
            record.count() == 1,
            "no measurement button on the test screen",
        )
        if record.count():
            record.click()
            page.locator("div[role='dialog']").wait_for(state="visible", timeout=10000)
            parameter = page.locator("select[name='parameter_code']").first
            check(
                "the parameter is chosen from the configured catalogue",
                parameter.count() == 1,
                "no parameter dropdown",
            )
            parameter.select_option("MOISTURE")
            page.wait_for_timeout(300)
            unit = page.locator("[data-testid='measurement-unit']").first
            check(
                "the unit comes from the parameter's own configuration",
                unit.count() == 1 and unit.inner_text().strip() == "%",
                f"unit shows {unit.inner_text().strip()!r}" if unit.count() else "no unit cell",
            )
            value = page.locator("input[name='value']").first
            value.click()
            page.keyboard.type("17.2", delay=30)
            check(
                "the measured value takes its decimal in one go",
                value.input_value() == "17.2",
                f"field holds {value.input_value()!r}",
            )
            method = page.locator("select[name='method']").first
            if method.count():
                # The methods come from the chosen parameter's own configuration, so
                # the check is that a configured method can be picked and stays
                # picked — not that one particular bench method exists.
                choices = [
                    value
                    for value in method.locator("option").evaluate_all(
                        "els => els.map(e => e.value)"
                    )
                    if value and value != "OTHER"
                ]
                check(
                    "the method is chosen from the configured set rather than typed",
                    bool(choices),
                    "no configured method is offered",
                )
                if choices:
                    method.select_option(choices[0])
                    page.wait_for_timeout(250)
                    check(
                        "the chosen method stays selected",
                        method.input_value() == choices[0],
                        f"method select holds {method.input_value()!r}",
                    )
            page.get_by_role("button", name="Save the measurement").first.click()
            page.wait_for_timeout(1800)
            results = page.locator("table[data-testid='lab-results']")
            check(
                "the measurement is saved against the test",
                results.count() == 1 and "Moisture" in results.first.inner_text(),
                "the results table does not show the measurement",
            )

        # ------------------------------------------------------------------ #
        section("Completing the test decides the batch")
        # ------------------------------------------------------------------ #
        # Completing is a decision, so it is made in a dialog that states what is
        # about to be recorded — the button on the screen opens it, the button in
        # the dialog commits it.
        opener = page.locator("[data-testid='complete-test']").first
        check(
            "the test screen offers the completion control",
            opener.count() == 1,
            "no completion control on the test screen",
        )
        if opener.count():
            opener.click()
            page.locator("div[role='dialog']").wait_for(state="visible", timeout=10000)
            decide = page.get_by_role("button", name="Complete and decide").first
            check(
                "the decision dialog names the action it is about to take",
                decide.count() == 1,
                "the dialog has no decision button",
            )
            if decide.count():
                decide.click()
                page.wait_for_timeout(3000)
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1800)
        decision_text = main_text(page)
        check(
            "the test screen shows the decision after a refresh",
            "Completed" in decision_text and "Pass" in decision_text,
            "the decision did not survive the refresh",
        )

        status, payload = request(
            "GET", f"/batches/{batch['id']}", base=api, token=arrangement["admin"]
        )
        decided = payload["data"]
        # A pass moves the batch straight on to PACKAGING_READY — approved *and*
        # released to packaging in one audited step — so both statuses are correct
        # answers here. Anything else means the decision did not reach the record.
        check(
            "the batch is approved in the database, not only on the screen",
            str(decided["status"]) in ("APPROVED", "PACKAGING_READY"),
            f"status={decided['status']}",
        )
        check(
            "the batch detail carries the laboratory decision",
            (decided.get("laboratory") or {}).get("overall_result") == "PASS",
            f"laboratory={decided.get('laboratory', {}).get('overall_result')}",
        )

        page.goto(f"{BASE_WEB}/laboratory/completed", wait_until="networkidle")
        page.wait_for_timeout(1800)
        check(
            "the completed test is in the completed queue",
            batch["batch_code"] in main_text(page),
            "the test is not in the completed queue",
        )
        page.goto(f"{BASE_WEB}/laboratory/pending", wait_until="networkidle")
        page.wait_for_timeout(1500)
        check(
            "the completed test has left the pending queue",
            batch["batch_code"] not in main_text(page),
            "the batch is still offered as pending work",
        )

        # ------------------------------------------------------------------ #
        section("The packaging unit packs what the laboratory approved")
        # ------------------------------------------------------------------ #
        sign_in_page(page, arrangement["packer"])
        page.wait_for_timeout(900)
        check(
            "the packaging account lands in the packaging workspace",
            "/packaging" in page.url,
            f"landed on {page.url}",
        )
        page.goto(f"{BASE_WEB}/packaging/approved", wait_until="networkidle")
        page.wait_for_timeout(1800)
        pack_button = page.locator(f"[data-testid='pack-batch-{batch['batch_code']}']")
        check(
            "the approved batch is offered to packaging",
            pack_button.count() == 1,
            "the approved batch is not on the packing worklist",
        )
        if pack_button.count():
            pack_button.first.click()
            page.locator("div[role='dialog']").wait_for(state="visible", timeout=10000)
            container = page.locator("select[name='packaging_type']").first
            container.select_option("OTHER")
            page.wait_for_timeout(300)
            typed = page.locator("input[name='packaging_type_other']").first
            check(
                "choosing Other reveals the field that says what the container is",
                typed.count() == 1,
                "the Other field did not appear",
            )
            if typed.count():
                typed.click()
                page.keyboard.type("Custom glass jar 500 g", delay=20)
                check(
                    "the container description takes a whole phrase in one go",
                    typed.input_value() == "Custom glass jar 500 g",
                    f"field holds {typed.input_value()!r}",
                )
            page.fill("input[name='packaged_quantity']", "5")
            # The package size is chosen from the sizes this unit has really packed,
            # with Other asking for a new one. Both paths are exercised: a preset
            # first (which must hide the specify field, not leave a stale value),
            # then Other with the size typed in one go.
            size_choice = page.locator("select[name='package_size_choice']").first
            if size_choice.count():
                size_choice.select_option("OTHER")
                page.wait_for_timeout(200)
                size_typed = page.locator("input[name='package_size']").first
                check(
                    "choosing a package size that is not on the list asks for it",
                    size_typed.count() == 1 and size_typed.input_value() == "",
                    f"the specify field reads {size_typed.input_value()!r}",
                )
                size_choice.select_option(index=0)
                page.wait_for_timeout(200)
                check(
                    "picking a size from the unit's own history hides the typed one",
                    page.locator("input[name='package_size']").count() == 0,
                    "the specify field is still on screen",
                )
                size_choice.select_option("OTHER")
                page.wait_for_timeout(200)
                check(
                    "coming back to Other starts from an empty field, not stale text",
                    page.locator("input[name='package_size']").first.input_value() == "",
                    "the previous size is still in the box",
                )
            page.fill("input[name='package_size']", "1")
            page.fill("input[name='number_of_packages']", "5")
            page.locator("[data-testid='submit-packaging']").first.click()
            page.wait_for_timeout(2500)

            page.goto(f"{BASE_WEB}/packaging/runs", wait_until="networkidle")
            page.wait_for_timeout(1800)
            runs_text = main_text(page)
            check(
                "the packaging run exists and reads as pending",
                "Pending" in runs_text,
                "the run is not listed as pending",
            )
            check(
                "the run shows the container that was described by hand",
                "Custom glass jar 500 g" in runs_text,
                "the description is not shown to readers",
            )
            check(
                "the run is linked to the honey it is packing",
                batch["batch_code"] in runs_text,
                "the run does not name its batch",
            )
            start = page.locator("[data-testid^='start-run-']").first
            if start.count():
                start.click()
                page.wait_for_timeout(2200)
            complete_run = page.locator("[data-testid^='complete-run-']").first
            check(
                "the run that is under way can be completed from the list",
                complete_run.count() == 1,
                "no completion control on the run",
            )
            # Which run this is, so the check below is about *this* run rather
            # than about whatever else the board happens to be showing.
            this_run = None
            if complete_run.count():
                this_run = complete_run.get_attribute("data-testid")
                complete_run.click()
                page.wait_for_timeout(3000)
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(2000)
            if this_run:
                check(
                    "the completed run is no longer offered as work in progress",
                    page.locator(f"[data-testid='{this_run}']").count() == 0,
                    f"{this_run} is still listed as completable",
                )
            # A package exists when its row exists; it reaches a distributor only
            # when the unit releases it, which is a decision and not a side effect.
            release = page.locator("[data-testid^='release-run-']").first
            if release.count():
                release.click()
                page.wait_for_timeout(2500)

        status, payload = request(
            "GET",
            f"/batches/{batch['id']}/packages?page_size=50",
            base=api,
            token=arrangement["admin"],
        )
        rows = payload.get("data", []) if status == 200 else []
        codes = [row["package_code"] for row in rows]
        check(
            "packaging generated real, individual package codes",
            len(codes) == 5 and all(code.startswith("HC-PKG-") for code in codes),
            f"codes: {codes[:6]}",
        )
        check(
            "each package carries the container the run was described as",
            bool(rows)
            and all(row.get("packaging_type") == "OTHER" for row in rows)
            and all((row.get("packaging_type_display") or "") == "Custom glass jar 500 g" for row in rows),
            f"first row: {rows[0].get('packaging_type')} / {rows[0].get('packaging_type_display')}"
            if rows
            else "no packages",
        )
        check(
            "each package is a separate record with its own size and batch",
            bool(rows)
            and all(row.get("batch_id") == batch["id"] for row in rows)
            and all(str(row.get("package_size")) == "1.000" for row in rows),
            "a package is missing its batch or its size",
        )

        # ------------------------------------------------------------------ #
        section("Packaging information and stock read the same rows")
        # ------------------------------------------------------------------ #
        page.goto(f"{BASE_WEB}/packaging/stock", wait_until="networkidle")
        page.wait_for_timeout(1800)
        stock_text = main_text(page)
        check(
            "the packed stock lists the package codes that were generated",
            bool(codes) and codes[0] in stock_text,
            "the package is not on the stock screen",
        )
        if rows:
            page.goto(f"{BASE_WEB}/packaging/packages/{rows[0]['id']}", wait_until="networkidle")
            page.wait_for_timeout(1800)
            info_text = main_text(page)
            check(
                "the package information traces back to its batch",
                batch["batch_code"] in info_text,
                "the package does not name its batch",
            )
            check(
                "the package information names the harvest it came from",
                bool(arrangement["collection_code"])
                and arrangement["collection_code"] in info_text,
                "the package does not name the collection",
            )

        status, payload = request(
            "GET", f"/packaging?batch_id={batch['id']}&page_size=5", base=api,
            token=arrangement["admin"],
        )
        runs = payload.get("data", []) if status == 200 else []
        run_id = runs[0]["id"] if runs else None
        if run_id:
            page.goto(f"{BASE_WEB}/packaging/runs/{run_id}", wait_until="networkidle")
            page.wait_for_timeout(1800)
            info_text = main_text(page)
            check(
                "the packaging information screen reports the batch and quantities",
                batch["batch_code"] in info_text and "5" in info_text,
                "the information screen does not report the run",
            )

        # ------------------------------------------------------------------ #
        section("The distributor receives the packed honey")
        # ------------------------------------------------------------------ #
        sign_in_page(page, arrangement["distributor"])
        page.wait_for_timeout(900)
        check(
            "the distributor lands in the distribution workspace",
            "/distributor" in page.url,
            f"landed on {page.url}",
        )
        page.goto(f"{BASE_WEB}/distributor/ready", wait_until="networkidle")
        page.wait_for_timeout(2000)
        ready_text = main_text(page)
        check(
            "the released packages are offered to the distributor",
            bool(codes) and codes[0] in ready_text,
            "the released package is not on the distributor's ready screen",
        )
        # Taking a shipment and dispatching it: the distributor moves the package,
        # never the batch, and never a copy of it.
        open_shipment = page.get_by_role("button", name="New shipment").first
        check(
            "the distributor can start a shipment from the released package",
            open_shipment.count() == 1,
            "no shipment control on the ready screen",
        )
        if open_shipment.count() and rows:
            open_shipment.click()
            page.locator("div[role='dialog']").wait_for(state="visible", timeout=10000)
            chooser = page.locator("select[name='package_id']").first
            check(
                "the shipment is taken against a package, chosen from the released ones",
                chooser.count() == 1,
                "no package chooser in the shipment dialog",
            )
            if chooser.count():
                # The dialog loads the released packages itself, so the chooser is
                # waited for rather than assumed to be populated on the first frame.
                for _ in range(20):
                    if chooser.locator("option").count() > 1:
                        break
                    page.wait_for_timeout(250)
                values = chooser.locator("option").evaluate_all("(nodes) => nodes.map(n => n.value)")
                check(
                    "the chooser is populated from the released packages",
                    rows[0]["id"] in values,
                    f"{len(values)} option(s): {values[:3]}",
                )
                if rows[0]["id"] in values:
                    chooser.select_option(rows[0]["id"])
                elif len(values) > 1:
                    chooser.select_option(values[1])
            # The receiver is a real account, chosen from the shops the API lists —
            # not typed as text, and not left empty. This is the field whose absence
            # left shipments addressed to nobody.
            retailer_chooser = page.locator("select[name='retailer_id']").first
            check(
                "the shipment form asks which retailer it is for",
                retailer_chooser.count() == 1,
                "no retailer chooser in the shipment dialog",
            )
            if retailer_chooser.count():
                for _ in range(20):
                    if retailer_chooser.locator("option").count() > 1:
                        break
                    page.wait_for_timeout(250)
                options = retailer_chooser.locator("option").evaluate_all(
                    "(nodes) => nodes.map(n => ({ value: n.value, text: n.textContent }))"
                )
                check(
                    "the retailer list is read from the platform's own accounts",
                    any(str(arrangement["retailer_id"]) == row["value"] for row in options),
                    f"{len(options)} option(s): {[row['text'] for row in options][:3]}",
                )
                if any(str(arrangement["retailer_id"]) == row["value"] for row in options):
                    retailer_chooser.select_option(str(arrangement["retailer_id"]))
                elif len(options) > 1:
                    retailer_chooser.select_option(options[1]["value"])

            quantity = page.locator("input[name='quantity']").first
            if quantity.count() and not quantity.input_value():
                quantity.click()
                page.keyboard.type("1", delay=30)
            destination = page.locator("input[name='destination']").first
            if destination.count():
                destination.click()
                page.keyboard.type("Guntur market", delay=20)
            submit = page.locator("[data-testid='submit-shipment']").first
            if submit.count():
                submit.click()
                page.wait_for_timeout(2500)

        status, payload = request("GET", "/distribution?page_size=10", base=api, token=arrangement["admin"])
        shipments = payload.get("data", []) if status == 200 else []
        check(
            "the shipment names the package, not a second batch record",
            bool(shipments)
            and any(row.get("package_code") == codes[0] for row in shipments),
            f"shipments: {[(row.get('distribution_code'), row.get('package_code')) for row in shipments][:3]}",
        )
        check(
            "the shipped package belongs to the batch the journey started with",
            bool(shipments) and any(row.get("batch_id") == batch["id"] for row in shipments),
            "the shipment does not point at the original batch",
        )
        ours = next(
            (row for row in shipments if row.get("package_code") == codes[0]),
            shipments[0] if shipments else None,
        )
        check(
            "the shipment is addressed to the retailer chosen in the form",
            bool(ours) and str(ours.get("retailer_id")) == str(arrangement["retailer_id"]),
            f"retailer_id={ours and ours.get('retailer_id')} expected {arrangement['retailer_id']}",
        )
        check(
            "the shipment response carries the retailer's name, not just an id",
            bool(ours) and ours.get("retailer_name") == arrangement["retailer_name"],
            f"retailer_name={ours and ours.get('retailer_name')}",
        )
        dispatch = page.locator("[data-testid^='dispatch-']").first
        if dispatch.count():
            dispatch.click()
            page.wait_for_timeout(2500)
        status, payload = request(
            "GET", f"/packages/{rows[0]['id']}", base=api, token=arrangement["admin"]
        ) if rows else (404, {})
        shipped = payload.get("data") or {}
        check(
            "dispatching moves the package itself, not the batch's status by hand",
            bool(rows) and str(shipped.get("status")) in ("IN_DISTRIBUTION", "READY_FOR_DISTRIBUTION"),
            f"package status={shipped.get('status')}",
        )

        # ------------------------------------------------------------------ #
        section("The timeline reflects what actually happened")
        # ------------------------------------------------------------------ #
        sign_in_page(page, OFFICER)
        page.goto(f"{BASE_WEB}/kvic/traceability/{batch['id']}", wait_until="networkidle")
        page.wait_for_timeout(2000)
        final_timeline = main_text(page)
        check(
            "the laboratory stage now reports its decision",
            "Approved" in final_timeline or "PASS" in final_timeline,
            "the laboratory stage does not report the approval",
        )
        check(
            "the packaging stage reflects the run that exists",
            "Packaging" in final_timeline,
            "the packaging stage is missing from the timeline",
        )
        check(
            "the timeline names the packages that came out of the batch",
            bool(codes) and any(code in final_timeline for code in codes),
            "no package code on the timeline",
        )

        # ------------------------------------------------------------------ #
        section("The retailer receives it — and only that retailer can")
        # ------------------------------------------------------------------ #
        shipment_code = (ours or {}).get("distribution_code")
        shipment_id = (ours or {}).get("id")

        # The other shop's list is read first, so "not there" is a fact about a
        # request that ran rather than about one that never happened.
        status, payload = request(
            "GET", "/retailer/shipments?page_size=50", base=api, token=other_retailer_token
        )
        other_rows = payload.get("data", []) if status == 200 else []
        check(
            "another retailer's inbound list does not contain this shipment",
            bool(shipment_id) and all(row.get("id") != shipment_id for row in other_rows),
            f"{len(other_rows)} shipment(s) in the other shop's list",
        )
        status, payload = request(
            "POST",
            f"/retailer/shipments/{shipment_id}/receive",
            base=api,
            token=other_retailer_token,
            body={},
        )
        check(
            "another retailer cannot confirm receipt of it",
            status in (403, 404),
            f"status={status}",
        )

        sign_in_page(page, arrangement["retailer"])
        page.goto(f"{BASE_WEB}/retailer/inbound", wait_until="networkidle")
        page.wait_for_timeout(2000)
        inbound_text = main_text(page)
        check(
            "the retailer's inbound list shows the shipment addressed to them",
            bool(shipment_code) and shipment_code in inbound_text,
            f"expected {shipment_code} in the inbound list",
        )
        receive_button = page.locator(f"[data-testid='receive-{shipment_code}']").first
        check(
            "the receipt is offered on the shipment that is the retailer's own",
            receive_button.count() == 1,
            "no receive control for the retailer's shipment",
        )
        if receive_button.count():
            receive_button.click()
            page.wait_for_timeout(2500)

        status, payload = request(
            "GET", f"/distribution/{shipment_id}", base=api, token=arrangement["admin"]
        )
        received = payload.get("data") or {}
        check(
            "the receipt is recorded on the shipment itself",
            received.get("status") == "DELIVERED"
            and str(received.get("received_by_id")) == str(arrangement["retailer_id"]),
            f"status={received.get('status')} received_by={received.get('received_by_id')}",
        )
        check(
            "the receipt names the receiver and the moment it arrived",
            bool(received.get("received_at")),
            "no received_at on the shipment",
        )
        page.goto(f"{BASE_WEB}/retailer/received", wait_until="networkidle")
        page.wait_for_timeout(2000)
        received_text = main_text(page)
        check(
            "the received products are derived from the delivered shipment",
            bool(codes) and any(code in received_text for code in codes),
            f"expected one of {codes} in the received products",
        )

        # The same record, read by the other roles — not a copy of it.
        sign_in_page(page, arrangement["distributor"])
        page.goto(f"{BASE_WEB}/distributor/shipments", wait_until="networkidle")
        page.wait_for_timeout(2000)
        check(
            "the distributor sees the delivery they handed over",
            bool(shipment_code) and shipment_code in main_text(page),
            "the delivered shipment is missing from the distributor's register",
        )
        sign_in_page(page, OFFICER)
        page.goto(f"{BASE_WEB}/kvic/traceability/{batch['id']}", wait_until="networkidle")
        page.wait_for_timeout(2000)
        closed_timeline = main_text(page)
        check(
            "the traceability record closes with the retailer's receipt",
            ("Received" in closed_timeline or "Delivered" in closed_timeline),
            "the timeline does not report the receipt",
        )
        check(
            "the traceability record names the shop that received it",
            arrangement["retailer_name"] in closed_timeline,
            f"expected {arrangement['retailer_name']} on the timeline",
        )

        check(
            "no request answered with a server error during the run",
            not failed_requests,
            "; ".join(sorted(set(failed_requests))[:5]),
        )
        check(
            "no console errors during the run",
            not console_errors,
            f"{console_errors[:3]} | requests: {sorted(set(rejected_requests))[:5]}",
        )
        browser.close()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("Failures:")
        for item in FAILED:
            print(f"  - {item}")
    print(
        "\nEverything this run created is TEST data "
        f"(beekeeper {arrangement['keeper']['email']}, batch {batch['batch_code']})."
    )
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
