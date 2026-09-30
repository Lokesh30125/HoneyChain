# HoneyChain — integration and correction phase: verification report

*Smart India Hackathon 2026 · Problem Statement 26021*
*Covers the pre-blockchain correction and integration phase (KVIC cluster → beekeeper → hive → collection → honey batch → processor → laboratory → sample/test → measurements → verdict → packaging → package IDs → distribution → retailer).*

---

## 1. What was verified

One continuous chain, on **one set of real database records**, with no manual copying of codes and
no static screens:

```
KVIC cluster → beekeeper → hive → collection → honey batch
   → processing run → laboratory test → sample → measurements
      → PASS / FAIL / INCONCLUSIVE → APPROVED / REJECTED / stays in testing
         → packaging run → individual package codes → release
            → distributor shipment → dispatch → delivered
```

Every stage was walked **in a browser, as the role that owns it**, and each step was then re-read
from the API and the database. A screen that says something happened is not evidence; the rows are.

---

## 2. Defects found in this window and fixed

| Defect | Root cause | Fix |
| --- | --- | --- |
| A **distributor saw no packages at all** — the ready screens and the shipment chooser were empty, so the last legs of the chain could not be walked | `packaging_service._in_scope` was a *batch*-level rule and returned `False` for `DISTRIBUTOR`, so both the list and the detail refused | new package-level `_package_in_scope` + `DISTRIBUTOR_VISIBLE_PACKAGE_STATUSES = (READY_FOR_DISTRIBUTION, IN_DISTRIBUTION, DELIVERED)`; `list_packages` and `_assert_can_read_package` use it (out of scope → 404) |
| The distributor's **"Ready for dispatch" screen** raised shipments from a dialog but never showed the released packages | the view read them only to populate the dialog | the ready view now lists them in the existing `PackageRegisterTable` (same rows, no copy) |
| **Package lists were not in a stable order** — the batch-package register could come back ascending or shuffled for the same data | every package of a run is written in one flush and therefore shares one `created_at`, and the listing ordered by that column alone | deterministic tie-break (`sequence_number DESC`, then `id ASC`) in the package register; the same rule added to the audit log, cluster, shipment and laboratory-result listings. Verified live: the same batch now returns `12, 11, 10, … 1` on every call (before: `3, 11, 4, 2, 8, …`) |
| A **collection centre account was told its module was "not part of this release"** while the module was running | its entry had been left in `plannedModules.js` | entry removed; the roadmap file now lists only modules that genuinely have no screens (consumer verification, production reports, system settings) |
| **Package size had no predefined control** | the dialog only accepted a typed number | the size is now chosen from the sizes that packaging unit has actually packed (read from its own runs), with **Other → "Specify the package size"**; picking a listed size hides and clears the typed one, and switching back starts empty |
| **Completing a test did not name what was missing** on the screen | the dialog listed counts only | the dialog now names the missing required measurements and states the consequence (the test closes inconclusive, the batch stays in testing, nothing can be packed) |
| `POST /clusters/{id}/members` was probed with a body and answered 404 | the real route addresses the pair in the path | **no product change**: the route is `POST /clusters/{cluster_id}/beekeepers/{beekeeper_id}` and the cluster probe now uses it |

The reported **"Cluster not created"** did **not** reproduce. With the built frontend and the running
API, creating a cluster posts exactly one request, the server answers `201` with a backend-generated
`KVIC-…` code, the registry refreshes without a manual reload, and the cluster survives a browser
reload, sign-out and sign-in. What the earlier report described is what the *test* used to do
(wrong button names, and field clicks intercepted by the filter inputs behind the modal); the
screens themselves were not failing.

---

## 3. Evidence

All commands run from `backend/` with the API on `:8000` and the built frontend served on `:4173`.
Every record any of these creates is **TEST data**, marked as such in its name or notes.

| Probe | What it covers | Latest result |
| --- | --- | --- |
| `tests/browser_master_workflow.py` | the whole chain in one browser session, role by role, each step re-read from the API/DB | **70 passed / 0 failed** |
| `tests/browser_cluster_workflow.py` | Parts 51–64: create → API response → DB row → list refresh → detail page → browser reload → sign-out/in → beekeeper attached and stored | **23 passed / 0 failed** |
| `tests/browser_lab_workflow.py --verdict PASS` | laboratory: open test → sample → measurement (catalogue parameter, unit from config, decimal in one go) → complete → `COMPLETED` + batch `APPROVED` → packaging worklist | **26 passed / 0 failed** |
| `tests/browser_lab_workflow.py --verdict FAIL` | the same path ending `REJECTED`, and packaging refused by the server | **27 passed / 0 failed** |
| `tests/browser_lab_workflow.py --verdict INCONCLUSIVE` | the same path ending `INCONCLUSIVE`: the batch stays in testing, traceability says so, packaging refuses it | **29 passed / 0 failed** |
| `tests/browser_input_focus.py` | one click, then a whole phrase typed continuously — every modal named in the prompt (register laboratory, record a measured value, complete a test, assign processor, create collection, create packaging run, add package, edit record) | **28 passed / 0 failed** |
| `tests/browser_nav_audit.py` | all ten roles: sidebar shows only its own modules, every entry opens a real screen, no "coming soon"/"not part of this release"/"not your workspace" text, a foreign URL redirects back, no console errors | **308 passed / 0 failed** |
| `tests/api_smoke_phase7.py` | packaging, packages, distribution, dispatch, delivery, scope and transition rules over HTTP | **69 passed / 0 failed** |
| `tests/api_smoke_other.py` | every "Other" pair end to end (processing type, container, device type): stored, echoed back as the description, refused when half-filled | **25 passed / 0 failed** |
| `pytest tests/test_packaging.py` | packaging rules and registers, after the ordering fix | **34 passed / 0 failed** |
| `pytest tests/test_packaging.py tests/test_distribution.py tests/test_batch_assignment.py tests/test_laboratory.py tests/test_other_values.py tests/test_collections.py` | the modules this window touched | **all passed** |
| full `pytest tests` (earlier in the phase, before the last fixes) | the whole backend suite | **903 passed / 1 warning** |

### What the master walk checks, stage by stage

* the harvest creates **one** batch, carrying its cluster, its collection and its source hives;
* the processing run moves the batch to `LAB_TESTING` and the laboratory sees it without a page
  refresh, with no false "awaiting a sample" state;
* a measurement is recorded from the configured catalogue, with the parameter's own unit and the
  decimal typed in one go; the method comes from the platform's list (or Other, described in words);
* completing the test writes `COMPLETED` server-side, the batch reads `APPROVED` in the database,
  and the test leaves the pending queue;
* the packaging unit sees the approved batch, describes the container with Other, chooses the
  package size from its own history or asks for a new one, and the server generates one code per
  package (`HC-PKG-…`) persisted with batch, run, cluster, unit, size and quantity;
* the packed stock, the package information page and the traceability timeline all read those same
  rows;
* the distributor sees the released packages, raises a shipment **against a package** (not a copy of
  the batch), dispatches it, and the package — not the batch — moves.

### Deliberate behaviours worth recording

* **`INCONCLUSIVE` is not a batch status.** The batch status catalogue has `APPROVED` and `REJECTED`
  and nothing for "undecided", so an inconclusive test leaves the batch at `LAB_TESTING`. The test
  record carries `INCONCLUSIVE`, the batch's laboratory state reads `INCONCLUSIVE`, and traceability
  reports the laboratory stage as inconclusive — but the batch is never approved and never packable.
  The probe asserts exactly this, rather than the batch flipping to a status the platform does not have.
* **A distributor's package list is deliberately narrower than the register**: only released,
  in-distribution and delivered packages. The fix was scoped to the package, not widened to the batch.
* Original quantities are never rewritten: collection quantity, processing input/output, laboratory
  approved, packaged and remaining are separate figures, and packaging can never exceed what the
  laboratory approved minus what is already packed.

---

## 4. How to re-run

```bash
# from the repository root — idempotent; recreates the venv, the database and the build
bash dev-rebuild.sh --serve

cd backend
.venv/bin/python tests/browser_master_workflow.py
.venv/bin/python tests/browser_cluster_workflow.py
.venv/bin/python tests/browser_lab_workflow.py --verdict PASS        # also FAIL, INCONCLUSIVE
.venv/bin/python tests/browser_input_focus.py
.venv/bin/python tests/browser_nav_audit.py
.venv/bin/python tests/api_smoke_phase7.py
.venv/bin/python tests/api_smoke_other.py
.venv/bin/python -m pytest tests -q
```

Each browser probe prints `N passed, M failed` and lists any failure with the reason it read from
the screen or the API.

---

## 5. Out of scope for this phase (unchanged by this work)

Blockchain anchoring and ledger entries, consumer QR verification and public verification pages,
and the Trust Score are the next phase. Nothing in this report implements them, nothing claims they
exist, and no hash or ledger row is written anywhere. The consumer workspace still says plainly that
its module belongs to a later phase — the only such statement left in the product.
