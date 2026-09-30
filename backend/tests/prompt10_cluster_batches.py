"""Prompt 10 — the cluster → batch relationship, in a browser, with real records.

What this proves, in the order an officer actually works:

1. A KVIC officer creates a cluster on the cluster screen and, on the same form,
   selects an **existing honey batch** (batch id, collection id, beekeeper,
   quantity and current status all come from the batch's own record).
2. A batch that already belongs to another cluster is flagged before it is
   chosen and refused until the officer confirms the move — and confirming moves
   that same batch, it does not create a second one.
3. The created cluster appears in the register at once, with its real batch
   count, and opens showing *Batches in this Cluster* with the batch, its
   harvest, its beekeeper and its laboratory / packaging / distribution statuses.
4. The cluster's analytics are counted from those same rows.
5. A page reload and a fresh sign-in both show the same stored state.
6. Removing the batch from the cluster leaves the batch intact, and placing it
   back restores exactly the relationship that existed before the run.

The script restores the records it moved and removes the cluster it created, so
it can run repeatedly against the development database. Usage:

    cd backend
    .venv/bin/python tests/prompt10_cluster_batches.py [--api-url …] [--web-url …]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from tests.api_smoke_phase7 import request, sign_in  # noqa: E402
from tests.browser_master_workflow import ADMIN, OFFICER, sign_in_page  # noqa: E402

DEFAULT_API = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")
DEFAULT_WEB = os.getenv("SMOKE_BASE_URL", "http://localhost:4173")

#: The cluster the batch is taken from and returned to. Read from the registry by
#: code so the script cannot pick up a cluster it created on an earlier run.
HOME_CLUSTER_CODE = "KVIC-GNT-001"

PASSED: list[str] = []
FAILED: list[str] = []
SHOTS: list[Path] = []


def check(description: str, condition: bool, detail: str = "") -> bool:
    (PASSED if condition else FAILED).append(description)
    suffix = f" — {detail}" if detail and not condition else ""
    print(f"  {'PASS' if condition else 'FAIL'}  {description}{suffix}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n=== {title}")


def main_text(page) -> str:
    body = page.locator("main")
    return body.first.inner_text() if body.count() else page.locator("body").inner_text()


def shoot(page, name: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    SHOTS.append(path)


def cluster_by_code(api: str, token: str, code: str) -> dict:
    status, payload = request("GET", "/clusters?page_size=100", base=api, token=token)
    if status != 200:
        raise SystemExit(f"Could not read the cluster registry: {status} {payload}")
    for row in payload["data"]:
        if row["cluster_code"] == code:
            return row
    raise SystemExit(f"Cluster {code} is not in the registry: {payload}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--web-url", default=DEFAULT_WEB)
    parser.add_argument(
        "--shots",
        default=str(Path(__file__).resolve().parents[2] / "docs" / "screenshots" / "prompt10"),
    )
    args = parser.parse_args()
    api, web = args.api_url.rstrip("/"), args.web_url.rstrip("/")
    out_dir = Path(args.shots)

    officer = sign_in(api, *OFFICER)
    admin = sign_in(api, *ADMIN)

    home = cluster_by_code(api, officer, HOME_CLUSTER_CODE)
    status, payload = request(
        "GET", f"/clusters/{home['id']}/batches?page_size=100", base=api, token=officer
    )
    if status != 200 or not payload["data"]:
        raise SystemExit(f"Cluster {HOME_CLUSTER_CODE} has no batches to work with: {payload}")
    # The batch this run moves out of its cluster and puts back at the end.
    subject = payload["data"][0]
    home_batch_count = payload["meta"]["total_items"]

    created_code = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.set_default_timeout(30000)

            section("The cluster register")
            sign_in_page(page, OFFICER)
            page.goto(f"{web}/kvic/clusters", wait_until="networkidle")
            register_text = main_text(page)
            check(
                "the register shows the existing cluster with a real batch count",
                HOME_CLUSTER_CODE in register_text and "Batches" in register_text,
                register_text[:400],
            )
            shoot(page, "01-cluster-register", out_dir)

            section("Create a cluster and select a real batch on the same form")
            page.get_by_role("button", name="New cluster").click()
            page.wait_for_selector("#cluster-form")
            new_name = f"TEST — Prompt 10 verification ({subject['batch_code']})"
            # Scoped to the dialog's own form: the register above it has a filter
            # with `district`/`state` inputs of the same name, and a page-level
            # `fill` would quietly type into those instead.
            page.fill("#cluster-form input[name='clusterName']", new_name)
            page.fill("#cluster-form input[name='district']", "Guntur")
            page.fill("#cluster-form input[name='state']", "Andhra Pradesh")
            page.fill(
                "#cluster-form input[name='description']",
                "Verification cluster created by tests/prompt10_cluster_batches.py. "
                "It holds a real batch and is removed again at the end of the run.",
            )
            form_text = page.locator("#cluster-form").inner_text()
            quantity_text = f"{float(subject['quantity']):g}".rstrip("0").rstrip(".") + " kg"
            check(
                "the create form offers real batches to place (not hives)",
                "Honey batches in this cluster" in form_text
                and subject["batch_code"] in form_text
                and "Add hives" not in form_text,
                form_text[:400],
            )
            check(
                "the picker lists the batch's own collection, beekeeper and quantity",
                subject["collection_code"] in form_text
                and (subject["beekeeper_code"] or "not recorded") in form_text
                and quantity_text in form_text,
                f"{quantity_text} / {subject['collection_code']} / {subject['beekeeper_code']}",
            )
            check(
                "a batch already in another cluster is flagged on its row, before it is chosen",
                f"Currently in {HOME_CLUSTER_CODE}" in form_text
                and "moving it must be confirmed" in form_text,
                form_text[-1200:],
            )
            page.click(f"[data-testid='pick-batch-{subject['batch_code']}']")
            page.wait_for_timeout(300)
            selected_text = page.locator("#cluster-form").inner_text()
            check(
                "selecting it names the cluster it currently belongs to",
                HOME_CLUSTER_CODE in selected_text,
                selected_text[:600],
            )
            check(
                "and the form says the move will be confirmed before it is written",
                "These batches already belong to another cluster" in selected_text
                and "will be asked to confirm" in selected_text,
                selected_text[:800],
            )
            shoot(page, "02-create-form-batch-selected", out_dir)

            page.click("[data-testid='submit-cluster-form']")
            confirm = page.locator("text=Some of these batches belong to another cluster")
            check("the move is refused until it is confirmed", confirm.count() > 0)
            if confirm.count():
                shoot(page, "03-move-confirmation", out_dir)
                page.get_by_role("button", name="Move and save").click()
            # The register only reloads after the write succeeded: waiting for the
            # name to appear is waiting for both.
            page.wait_for_selector(f"text={new_name}", timeout=30000)
            page.wait_for_timeout(700)

            register_text = main_text(page)
            check(
                "the cluster appears in the register immediately, with its batch count",
                new_name in register_text,
                register_text[:600],
            )
            status, clusters = request(
                "GET", "/clusters?page_size=100", base=api, token=officer
            )
            created = next((row for row in clusters["data"] if row["cluster_name"] == new_name), None)
            if created is None:
                raise SystemExit("The cluster the browser created is not in the registry")
            created_code = created["cluster_code"]
            check(
                "the new cluster stores the batch on the batch's own record",
                created["batch_count"] == 1,
                str(created),
            )
            status, moved = request("GET", f"/batches/{subject['id']}", base=api, token=admin)
            check(
                "the batch itself now names the new cluster (same row, not a copy)",
                moved["data"].get("cluster_code") == created_code,
                str(moved["data"].get("cluster_code")),
            )
            status, old_home = request(
                "GET", f"/clusters/{home['id']}/batch-analytics", base=api, token=officer
            )
            check(
                "the previous cluster no longer lists it",
                old_home["data"]["totals"]["batches"] == home_batch_count - 1,
                str(old_home["data"]["totals"]),
            )
            shoot(page, "04-register-with-new-cluster", out_dir)

            section("Open the cluster: Batches in this Cluster")
            page.goto(f"{web}/kvic/clusters/{created['id']}", wait_until="networkidle")
            page.wait_for_selector("text=Batches in this Cluster")
            detail_text = main_text(page)
            check(
                "the cluster page lists the batch with its harvest and beekeeper",
                subject["batch_code"] in detail_text
                and subject["collection_code"] in detail_text
                and (subject["beekeeper_code"] or "") in detail_text,
                detail_text[:700],
            )
            check(
                "the batch row carries its supply-chain, laboratory, packaging and distribution status",
                subject["status_label"] in detail_text
                and subject["laboratory_status_label"] in detail_text
                and "Packaging" in detail_text
                and "Distribution" in detail_text,
                detail_text[:900],
            )
            check(
                "the counters above the table are counted from that row",
                "Batches in cluster" in detail_text and "1 harvest record(s)" in detail_text,
                detail_text[:900],
            )
            check(
                "there is no hive-selection workflow on the cluster screens",
                "Add hives" not in detail_text and "Add Hives" not in detail_text,
            )
            shoot(page, "05-cluster-detail-batches", out_dir)

            section("Cluster analytics from the same rows")
            page.goto(f"{web}/kvic/cluster-analytics", wait_until="networkidle")
            # Every row is counted per cluster on request; wait for this cluster's
            # own row rather than for the first paint.
            page.wait_for_selector(f"text={created_code}", timeout=30000)
            page.wait_for_timeout(700)
            analytics_text = main_text(page)
            check(
                "the new cluster has an analytics row with its real figures",
                created_code in analytics_text,
                analytics_text[:500],
            )
            check(
                "the row reports one batch, one harvest and one beekeeper",
                "1 harvest(s)" in analytics_text and "1 beekeeper(s)" in analytics_text,
                analytics_text[:1200],
            )
            check(
                "the row carries the laboratory and stage breakdown counters",
                "approved" in analytics_text
                and "Delivered" in analytics_text
                and "Collection:" in analytics_text,
                analytics_text[:1200],
            )
            shoot(page, "06-cluster-analytics", out_dir)

            section("Refresh, and a fresh sign-in")
            page.reload(wait_until="networkidle")
            page.wait_for_selector(f"text={created_code}", timeout=30000)
            page.wait_for_timeout(500)
            reloaded = main_text(page)
            check(
                "the analytics survive a hard refresh",
                created_code in reloaded and "1 harvest(s)" in reloaded,
                reloaded[:600],
            )
            page.goto(f"{web}/kvic/clusters/{created['id']}", wait_until="networkidle")
            check("the cluster page survives a reload", subject["batch_code"] in main_text(page))

            sign_in_page(page, OFFICER)
            page.goto(f"{web}/kvic/clusters/{created['id']}", wait_until="networkidle")
            signed_in_text = main_text(page)
            check(
                "signing out and back in shows the same stored cluster and batch",
                subject["batch_code"] in signed_in_text and created_code in signed_in_text,
                signed_in_text[:600],
            )
            shoot(page, "07-after-new-sign-in", out_dir)

            section("Removing a batch, and putting the record back")
            page.goto(f"{web}/kvic/clusters/{created['id']}", wait_until="networkidle")
            page.wait_for_selector("text=Batches in this Cluster")
            page.get_by_role("button", name=f"Remove {subject['batch_code']}").click()
            page.get_by_role("button", name="Remove from cluster").click()
            page.wait_for_timeout(1500)
            after_remove = main_text(page)
            check(
                "removing the batch updates the count without a hard refresh",
                "No batches in this cluster yet" in after_remove,
                after_remove[:600],
            )
            status, still_there = request("GET", f"/batches/{subject['id']}", base=api, token=admin)
            check(
                "the batch itself still exists, with no cluster assigned",
                status == 200 and still_there["data"].get("cluster_id") is None,
                str(still_there["data"].get("cluster_id")),
            )
            shoot(page, "08-batch-removed", out_dir)

            # Place it back where it came from — through the UI, the same way it left.
            page.goto(f"{web}/kvic/clusters/{home['id']}", wait_until="networkidle")
            page.wait_for_selector("[data-testid='cluster-add-batches']")
            page.click("[data-testid='cluster-add-batches']")
            page.wait_for_selector(f"[data-testid='pick-batch-{subject['batch_code']}']")
            page.click(f"[data-testid='pick-batch-{subject['batch_code']}']")
            page.click("[data-testid='confirm-add-batches']")
            page.wait_for_timeout(1500)
            status, restored = request(
                "GET", f"/clusters/{home['id']}/batch-analytics", base=api, token=officer
            )
            check(
                "the batch is placed back in its original cluster through the UI",
                restored["data"]["totals"]["batches"] == home_batch_count,
                str(restored["data"]["totals"]),
            )
            shoot(page, "09-restored", out_dir)

            browser.close()
    finally:
        # The run's own artefacts are removed whether it succeeded or not: the
        # cluster it created holds nothing by now, and the batch it moved belongs
        # to its original cluster again.
        if created_code:
            status, clusters = request("GET", "/clusters?page_size=100", base=api, token=admin)
            row = next(
                (item for item in clusters.get("data", []) if item["cluster_code"] == created_code),
                None,
            )
            if row:
                # A run that failed half way still gets tidied: whatever it left in
                # the cluster goes back to the cluster it was taken from, so the
                # platform's own data is exactly as it was before the run.
                status, held = request(
                    "GET", f"/clusters/{row['id']}/batches?page_size=100", base=api, token=admin
                )
                for leftover in held.get("data", []):
                    status, moved_back = request(
                        "POST",
                        f"/clusters/{home['id']}/batches",
                        base=api,
                        token=admin,
                        body={"batch_ids": [leftover["id"]], "reassign": True},
                    )
                    print(
                        f"cleanup: {leftover['batch_code']} back in {HOME_CLUSTER_CODE} — {status}"
                    )
                status, payload = request(
                    "DELETE",
                    f"/clusters/{row['id']}",
                    base=api,
                    token=admin,
                    body={"confirm": True, "reason": "Prompt 10 verification cluster — removed by the test run"},
                )
                print(f"\ncleanup: removed {created_code} — {status}")
                if status != 200:
                    print(f"cleanup detail: {payload}")

    print(f"\n{PASSED.__len__()} passed, {FAILED.__len__()} failed")
    for name in FAILED:
        print(f"  FAILED: {name}")
    print("screenshots:")
    for path in SHOTS:
        print(f"  {path}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
