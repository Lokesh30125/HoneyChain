# Consumer QR verification — diagnostic and repair report

**Task.** The platform's consumer workspace still showed the old placeholder — *"Consumer
verification is not part of this release"* / *"The QR identity and the public verification page
are part of a later phase; nothing is generated here yet."* The brief was to find what actually
rendered that text, repair the root cause rather than the sentence, and prove the real path
end-to-end: **real package → Generate QR → scan/open → package → batch → full traceability →
real blockchain history → customer page**, with no faking anywhere.

**Result.** The path works end to end on real records. The placeholder is gone because the route
it lived on now opens the real verification screen, and three data defects found while checking
the customer's page against the database were repaired (see item 1.2–1.4). Everything below was
executed against the running stack: API on `:8000`, built web app on `:4173`, PostgreSQL, and the
existing blockchain service at `http://54.160.152.176:3001`.

---

## 1. Root cause

**1.1 The placeholder was a routing/roadmap leftover, not a missing feature.**
`/consumer` rendered `RoleWorkspaceHomePage`, which read the `CONSUMER` entry from
`src/constants/plannedModules.js` and printed the roadmap notice. The real record had existed
since Phase 8 — public page `/trace/:packageCode`, API `GET /api/v1/trace/{code}`, QR identity and
`POST /api/v1/blockchain/packages/{package_id}/qr`. The workspace home was simply never pointed at
it. Repaired by routing `/consumer` to `ConsumerVerificationPage` (inside `RoleRoute
allow={[ROLES.CONSUMER]}`) and deleting the roadmap entry, then deleting the two components that
existed only to draw roadmap pages. No text-only edit: the screen that rendered the sentence is no
longer reachable from any route.

**1.2 The customer's page named a unit of measure as the place the honey was processed.**
`public_trace` built `processing[].facility` from `run.unit` — the *unit of measure* column — so the
page reported `"facility": "KG"` for every batch and never the processing unit. The facility is
`processing_unit_id → unit_ref`. Now read from the relationship; blank when no unit is recorded, as
in the batches where processing happened without a facility.

**1.3 The packing stage never named the packing unit.**
`packaging.facility` was read from `packaging_unit` on the packaging record. That attribute does not
exist — the relationship is `unit_ref` — so `getattr(..., None)` answered `None` for every package
ever exported. Verified against the database: `packaging_records.packaging_unit_id =
bb51ddaf-…` (the real `packaging_units` row) while the API returned `null`. Now returns
`Phase 8 Packing Unit (TEST)`.

**1.4 A package's page carried other packages' records, and the label panel named another jar's
transaction.**
`events_for_package` selected `package_id = this OR batch_id = this`, so a single jar's page listed
all 25 packages of the batch: 25 `PACKAGE_CREATED` rows, plus — the sharp case — a *sibling's*
`QR_GENERATED` and `CUSTOMER_QR_VERIFIED` events, i.e. another product's label and transaction id.
The same query, read by the label panel (`_qr_read`), took "the first `QR_GENERATED` of the batch",
so the packaging screen reported whichever package happened to be labelled first: package
`HC-PKG-2026-000050` was displaying `event_id QR-HC-PKG-2026-000049-GENERATED` and tx
`c7e9368f…dde`, which belongs to package 049. Repaired by narrowing the package's ledger to its own
rows plus the batch's package-level-free rows (`package_id IS NULL`), and by looking the label's
event up by package (`service.qr_event`).

**1.5 Two public pages still described QR verification as future work.**
The sign-in/sign-up panel said *"Batch traceability, blockchain anchoring and AI assistance are
released in later phases"* and the landing page's call to action said *"Batch traceability and QR
verification follow in later phases"*. Both false since Phase 8. Copy corrected to state what is
live and to keep the one thing that genuinely is not (AI assistance) as later work.

**Not a cause, worth recording:** `/api/v1/packaging-units/mine` does exist
(`app/routes/packaging.py`); it answers `404` **by design** for an operator who has not been
attached to a facility yet. The browser logs that answer as a failed resource, which is why the
navigation audit previously reported it; the audit now classifies it as an expected, state-explained
refusal and still fails on any *other* 4xx/5xx.

---

## 2. Files and components changed

| File | Change |
| --- | --- |
| `frontend/src/routes/AppRoutes.jsx` | `/consumer` renders `ConsumerVerificationPage` inside `RoleRoute allow={[ROLES.CONSUMER]}`; the roadmap page import removed |
| `frontend/src/constants/plannedModules.js` | `CONSUMER` roadmap entry deleted; header note rewritten (only `/kvic/production` and `/admin/system` remain) |
| `frontend/src/constants/navigation.js` | `CONSUMER` workspace gains a **Verify** section → `Verify a product` → `/consumer` |
| `frontend/src/components/layout/Sidebar.jsx` | `QrCode` registered in the icon map |
| `frontend/src/components/blockchain/PackageQrLabel.jsx` | Action wording aligned: **Generate QR**, **Open verification page** (the panel already showed `QR Generated ✓`, the QR ID, the batch, the drawn label and the scan count) |
| `frontend/src/components/layout/AuthLayout.jsx` | Copy: traceability and blockchain anchoring are live; only AI assistance is later work |
| `frontend/src/components/landing/LandingSections.jsx` | Copy: the customer's QR page is live and needs no account |
| `frontend/src/pages/workspace/RoleWorkspaceHomePage.jsx` | **Deleted** — unreferenced once `/consumer` stopped rendering it |
| `frontend/src/components/common/PlannedModuleNotice.jsx` | **Deleted** — used only by the deleted page |
| `backend/app/services/blockchain/service.py` | `processing[].facility` from `unit_ref`; `packaging.facility` from `unit_ref`; `events_for_package` scoped to this package + batch-wide rows; new `qr_event()` |
| `backend/app/routes/blockchain.py` | `_qr_read` reports this package's own `QR_GENERATED` event |
| `backend/tests/consumer_qr_verification.py` | **New** — 66 checks over the whole path |
| `backend/tests/browser_nav_audit.py` | Placeholder allowance removed; "the consumer workspace offers verification" check added; refusals classified by expected state |
| `backend/tests/api_smoke_phase7.py`, `backend/tests/phase8_blockchain_workflow.py` | `request(..., timeout=)` and a 300 s sweep (the sync sweep legitimately takes ~2 min) |
| `docs/api.md`, `docs/phase-8-report.md` | Public-verification notes and the consumer role row corrected |
| `docs/consumer-qr-verification-report.md` | This report |

---

## 3. Existing QR functionality found (nothing was rebuilt)

The diagnosis came first, and it found a complete Phase 8 implementation:

* **Identity** — `app/services/blockchain/qr.py`: `qr_identifier(package)` is a pure function,
  `QR-{package_code}`; `package_code_from_qr` accepts `QR-HC-PKG-…` and `HC-PKG-…`; `qr_svg(text)`
  draws the label. There is no separate QR table: the label's identity is derived, which is why it
  is stable across refreshes, logouts and browsers.
* **Issue / read** — `POST` and `GET /api/v1/blockchain/packages/{package_id}/qr`. `service.ensure_qr`
  validates the package and its batch, writes `packages.qr_payload` (the verification URL) and
  `qr_generated_at` once, and records `QR_GENERATED` through the existing outbox → the existing
  service. Re-issuing returns the same identity and writes nothing.
* **Public read** — `GET /api/v1/trace/{code}`, `GET /api/v1/verify/{code}`,
  `GET /api/v1/trace/{code}/qr.svg`; screens `/trace/:packageCode` and `/verify/:code` rendering the
  same `TraceReport` the consumer workspace now uses, so the signed-out page and the signed-in
  workspace cannot disagree.
* **Chain** — `CUSTOMER_QR_VERIFIED` is written once per package (the scan counter increments), so a
  reload cannot duplicate a transaction.

What was missing was only the consumer workspace's route — and, hidden behind it, the three data
defects in §1.2–1.4 that only a comparison against the database could reveal.

---

## 4. Backend endpoints verified

| Method | Endpoint | Called as | Observed |
| --- | --- | --- | --- |
| `POST` | `/api/v1/blockchain/packages/{package_id}/qr` | admin (authorised role) | `200`; `qr_id QR-HC-PKG-2026-000079`; `qr_payload http://localhost:4173/trace/HC-PKG-2026-000079`; `<svg>` label; `event_id QR-HC-PKG-2026-000079-GENERATED`; real `tx_id` |
| `GET` | `/api/v1/blockchain/packages/{package_id}/qr` | admin | same identity, no write on re-read |
| `POST` | same, repeated | admin | identical `qr_id`, `event_id` unchanged — no duplicate record |
| `GET` | `/api/v1/trace/{code}` | **anonymous** | full report for the package; `200` |
| `GET` | `/api/v1/verify/{qr_id}` | **anonymous** | resolves the same package |
| `GET` | `/api/v1/trace/{code}` | unknown code | `404`, "Invalid QR Code" on the page, no ids or internals |
| `GET` | `/api/v1/blockchain/transactions?search=QR-HC-PKG-…-GENERATED` | admin | the platform row behind the label |
| `GET` | `/api/v1/blockchain/health`, `/api/v1/blockchain/batches/{id}` | admin | connected; batch traceability synchronised |
| `POST` | `/api/v1/blockchain/packages/{id}/qr` | consumer token / anonymous | `403` / `401` |
| `POST` | `/api/v1/blockchain/sync`, `POST /api/v1/packages/{id}/release`, `GET /api/v1/blockchain/transactions` | consumer token | `403` |
| `GET` | `/api/v1/trace/{code}` | anonymous | still `200` — reading stays public while writing does not |

---

## 5. Frontend routes verified

| Route | Screen | Evidence |
| --- | --- | --- |
| `/consumer` | `ConsumerVerificationPage` (consumer workspace, signed in) | "Consumer workspace", "Verify a product", no roadmap sentence; a typed code renders the same record as the public page |
| `/trace/HC-PKG-2026-000079` | `TracePage` + `TraceReport`, no account | package, QR id, journey, packing unit, blockchain rows with the real tx |
| `/verify/QR-HC-PKG-2026-000079` | same report via the QR id | resolves to the same package |
| `/verify/QR-HC-PKG-2026-000080` | a batchmate | resolves to *itself*: different package, different QR id, different transaction |
| `/verify/INVALID-QR-123` | refusal | "Invalid QR Code"; no stack trace, SQL, DB id or unrelated batch data |
| `/packaging/packages/:id` (packaging workspace) | `PackageQrLabel` | "QR Generated ✓", Package ID, QR ID, drawn label, "Open verification page" |
| `/admin/blockchain`, `/kvic/blockchain` | ledger screens | still render the real ledger after the change |

---

## 6. Real Package ID used

* **`HC-PKG-2026-000079`** — batch **`HC-BATCH-2026-000004`**, packing run `HC-PACK-2026-000004`,
  created by the end-to-end run of this task (harvest → batch → processing → lab PASS → packaging →
  package → shipment → retailer receipt → QR).
* **`HC-PKG-2026-000080`** — the same batch, the shipped one, used for the distribution/retailer
  half of the customer's page.
* Earlier in the task: `HC-PKG-2026-000050` / `HC-PKG-2026-000049`, batch `HC-BATCH-2026-000002`.

## 7. Real QR ID generated

* **`QR-HC-PKG-2026-000079`** (label payload `http://localhost:4173/trace/HC-PKG-2026-000079`,
  issued `2026-09-30T01:49:45Z`), and **`QR-HC-PKG-2026-000080`** for the batchmate.
* Re-issuing returned the same id, the same `event_id` and wrote no second record; a page reload
  after 12 opens kept the id and the same scan counter.

## 8. Verification URL tested

* `http://localhost:4173/trace/HC-PKG-2026-000079` — opened signed out; shows the package, its QR id
  and its journey.
* `http://localhost:4173/verify/QR-HC-PKG-2026-000079` — same record through the QR id.
* `/trace/QR-HC-PKG-2026-000049` and `/trace/HC-PKG-2026-000080` — both resolve; each to its own
  package.

## 9. Real `QR_GENERATED` transaction

Taken from the platform's event row **and** found in the blockchain service's own
`GET http://54.160.152.176:3001/transactions` (730 transactions at the time of writing):

| Package | `event_id` | `tx_id` | `batch_id` on the chain | Confirmed at |
| --- | --- | --- | --- | --- |
| `HC-PKG-2026-000079` | `QR-HC-PKG-2026-000079-GENERATED` | `fe08b566830f857a06acd806dbf6e9de8946fe740865d93848fc7a8f148a64e8` | `HC-BATCH-2026-000004` | `2026-09-30T01:49:48.104Z` |
| `HC-PKG-2026-000080` | `QR-HC-PKG-2026-000080-GENERATED` | `12c8149fa0a9218b659ef16386483cab4d22b15a2b8b185fb466f20059c81f20` | `HC-BATCH-2026-000004` | `2026-09-30T01:49:13.688Z` |
| `HC-PKG-2026-000050` | `QR-HC-PKG-2026-000050-GENERATED` | `ec95a08e936752ea3e048944215fba29339c510de5ec6ed9bfc89d46aa9e05ba` | `HC-BATCH-2026-000002` | `2026-09-30T01:14:54.909Z` |
| `HC-PKG-2026-000049` | `QR-HC-PKG-2026-000049-GENERATED` | `c7e9368f0a9c8157c4abe88da8de55fa6c3237c1baa936b5a4d785bad1f28dde` | `HC-BATCH-2026-000002` | `2026-09-30T01:15:26Z` |

The remote ledger outlives local resets, so it also holds rows from earlier runs whose
`qr_id` names a package code that has since been re-issued (for example three `QR-HC-PKG-2026-000050`
labels, only one of them belonging to batch `HC-BATCH-2026-000002`). The platform's own rows are
matched by **batch and package together**, never by the code alone, so a historical row can never be
presented as this run's transaction.

Chain payload of the first row, as the service stores it:
`{"qr_id": "QR-HC-PKG-2026-000079", "status": "ACTIVE", "batch_id": "HC-BATCH-2026-000004",
"package_id": "HC-PKG-2026-000079", "generated_at": "2026-09-30T01:49:45.790946+00:00",
"verification_url": "http://localhost:4173/trace/HC-PKG-2026-000079"}` — no notes, prompts,
telemetry, documents or internal ids.

## 10. Customer data displayed

`GET /api/v1/trace/HC-PKG-2026-000080`, rendered by the customer page — every value read from the
database, none hardcoded:

| Section | Values shown |
| --- | --- |
| PRODUCT | batch `HC-BATCH-2026-000004`, honey, net `13.7 KG` |
| SOURCE | cluster `Guntur KVIC Beekeeping Cluster` (`KVIC-GNT-001`), Guntur / Andhra Pradesh, beekeeper `BKR-GEN-00004`, 1 hive, collected `2026-09-30`, `13.7 KG` |
| PROCESSING | `HC-PROC-2026-000004`, Filtering, `13.7 → 12.9 KG`, completed `01:47:40Z`, status `COMPLETED` (no facility recorded for this run — shown blank, never "KG") |
| LABORATORY | `HC-LAB-2026-000004` / `HC-SMP-2026-000004`, `COMPLETED`, **PASS**, "All 13 recorded parameter(s) are within their configured ranges.", round 1, `proceeded_with_risk false` |
| PACKAGING | `HC-PACK-2026-000004`, **Phase 8 Packing Unit (TEST)**, `12.5 KG`, 25 packages in the run, completed `01:47:41Z` |
| DISTRIBUTION | dispatched `01:47:43.25Z` → in transit `01:47:43.29Z` → delivered `01:47:43.32Z`, destination "Guntur market" |
| RETAILER | `Master Workflow Retailer TEST Guntur Shop`, received `01:47:43.36Z` |
| BLOCKCHAIN | 16 events, 16 confirmed, `synchronized: true`, incl. `QR_GENERATED` tx `12c8149f…f20` and `CUSTOMER_QR_VERIFIED` tx `c92d959d…327` |
| Timeline | COLLECTION → BATCH → PROCESSING → LABORATORY → PACKAGING → DISPATCHED → IN_TRANSIT → DELIVERED → RETAILER → QR → VERIFIED, each with its real timestamp |

A package that has not shipped shows no distribution stage at all (`HC-PKG-2026-000079`: 11 events,
`distribution: []`) rather than a tick for something that has not happened.

## 11. Tests executed and actual results

| Command | Result |
| --- | --- |
| `tests/phase8_blockchain_workflow.py` — full real workflow on the live blockchain service | **46 passed / 0 failed**, exit 0; sweep `{"submitted":25,"confirmed":25,"failed":0,"skipped":0,"outstanding":0,"enabled":true}` |
| `tests/consumer_qr_verification.py` — the consumer/QR proof (new) | **66 passed / 0 failed**, exit 0 |
| `tests/phase8_ui_checks.py` | **27 passed / 0 failed**, exit 0 |
| `tests/browser_nav_audit.py` — all ten roles | **329 passed / 0 failed**, exit 0 |
| `tests/browser_input_focus.py` | **28 passed / 0 failed**, exit 0 |
| `tests/browser_master_workflow.py` — all role workspaces end to end | **87 passed / 0 failed**, exit 0 |
| `pytest tests/test_*.py` — the whole backend suite | **928 passed, 0 failed**, 1 warning, exit 0 (22 min 10 s; `928 passed in 1330.75s`) |
| `npx eslint src/` | clean, exit 0 |
| `npx vite build` | exit 0 (`dist/assets/index-B4PfdG6M.js`) — the preview on `:4173` serves this build |

The consumer test is the one written for this task; it fails if any of the following regress: the QR
id is not `QR-{package_code}`, re-issuing writes a second record, the label panel reports a
batchmate's event, the customer's page carries another package's rows, a facility is reported as a
unit of measure, the packing unit is missing, an invalid code leaks internals, a reload changes the
record, or the consumer can write anything.

Its first run reported 3 failures; all three were faults in the test, not the product, and both were
corrected rather than relaxed. It required a named facility on every processing run, which failed on
a batch whose run has no facility (`processing_unit_id IS NULL`) — the honest answer; it now checks
that no *unit of measure* is reported as a facility and that any named facility exists in
`GET /processing-units`. And it assumed the batchmate it picked already carried a label; it now
labels that batchmate through the same authorised endpoint, which is a better test than before —
two labelled packages in one batch, each proving it cannot see the other's rows.

Raw logs, in the workspace's `/tmp`: `final_evidence.log` (E2E, UI, navigation, focus),
`consumer_qr3.log` (the consumer proof), `final_regression.log` (master workflow),
`fullsuite_final3.log` (the backend suite).

## 12. Remaining blockers

* **None open for the QR path.** Every step of *real package → QR → scan → package → batch →
  traceability → blockchain → customer page* passed on real records in this task.
* **Known, pre-existing, not caused by this task:** the packaging operator's dashboard issues
  `GET /api/v1/packaging-units/mine`, which answers `404` for an operator not yet attached to a
  facility (documented behaviour of `my_packaging_unit`); the UI handles it, but the browser still
  logs the failed resource. The navigation audit now classifies it as an expected refusal and fails
  on anything else. Left as-is deliberately — changing the endpoint's contract is outside this task.
* **Data, not defects:** `honey_processing_records.processing_unit_id` is `NULL` for the batches in
  this environment and `processing_units` is empty, so the processing facility row is blank. The
  customer's page says nothing rather than something false.
* **Still genuinely future work (unchanged copy):** AI assistance — no screen claims otherwise.

---

## Appendix — the checklist, point by point

| # | Check | Where the evidence is |
| --- | --- | --- |
| 1 | A real package exists, created by the real workflow | E2E run: `HC-PKG-2026-000079/080`, batch `HC-BATCH-2026-000004` |
| 2 | "Generate QR" works in the packaging UI | `tests/phase8_ui_checks.py`; label panel on the package screen |
| 3 | A real QR record exists | `packages.qr_payload`/`qr_generated_at` for the package; `POST …/qr` returns it |
| 4 | The QR id is stable | re-issue, reload after 12 opens, reopened browser → `QR-HC-PKG-2026-000079` |
| 5 | The QR resolves to the exact package, never the batch's first | `/verify/QR-HC-PKG-…-080` resolves 080, not 079 |
| 6 | The package resolves to its real batch | `HC-BATCH-2026-000004` in the report and on the chain row |
| 7 | The QR visual is drawn | `<svg>` from `qr_svg`, on the label and on the page |
| 8 | The verification URL opens | `http://localhost:4173/trace/HC-PKG-2026-000079` |
| 9 | No internal sign-in is needed | anonymous `GET /api/v1/trace/{code}` → `200`; page renders signed out |
| 10 | Collection is shown from the record | cluster, beekeeper, hive count, date, `13.7 KG` |
| 11 | Processing is shown from the record | `HC-PROC-2026-000004`, Filtering, `13.7→12.9 KG`, COMPLETED |
| 12 | The laboratory result is shown | `HC-LAB-2026-000004`, PASS, the summary sentence |
| 13 | Packaging is shown from the record | `HC-PACK-2026-000004`, Phase 8 Packing Unit (TEST), `12.5 KG`, 25 packages |
| 14 | Distribution is shown | dispatched / in transit / delivered with timestamps |
| 15 | The retailer is shown | `Master Workflow Retailer TEST Guntur Shop`, received |
| 16 | The blockchain timeline is shown | 16 events, tx ids, timestamps, `synchronized: true` |
| 17 | A real `QR_GENERATED` event exists for the package | `QR-HC-PKG-2026-000079-GENERATED`, `CONFIRMED` |
| 18 | Its transaction id is real | `fe08b566…f20` found in the service's own `GET /transactions` |
| 19 | An invalid QR is refused safely | `/verify/INVALID-QR-123` → "Invalid QR Code"; no internals |
| 20 | Multiple packages resolve separately | 079 and 080 each resolve to themselves; neither page carries the other's rows |
| 21 | No duplicates on refresh/reopen | one QR record, one `QR_GENERATED`, one `CUSTOMER_QR_VERIFIED` per package |
| 22 | The ledger and batch traceability still work | `/admin/blockchain`, `/kvic/blockchain`, `GET /blockchain/batches/{id}` |
| 23 | The customer cannot write; QR generation stays with the authorised role | consumer/anonymous writes → `401`/`403`; the label is issued by the authorised role only |
