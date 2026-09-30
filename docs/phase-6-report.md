# HoneyChain — Phase 6 delivery report

**Processing and the laboratory: a batch becomes a tested batch**

*Smart India Hackathon 2026 · Problem Statement 26021 · Report generated 27 September 2026*

---

## 1. What this phase set out to do

Phase 5 ended with a batch that existed and could be read: a beekeeper completed a harvest, the
platform created `HC-BATCH-YYYY-NNNNNN`, and the batch's timeline stopped at **Collection —
completed**. Everything after that stage was a row of grey circles.

Phase 6 builds the two stages that come next, for the two roles that perform them:

* a **PROCESSOR** registers the plant the work happens in, opens a run against a batch that is
  waiting, records what went in and what came out, and completes or cancels it;
* a **LAB_TECHNICIAN** creates a test for a sample of that batch, records measurements against the
  platform's own parameter catalogue, and completes the test, at which point the platform compares
  each measurement with the configured reference range and decides the test **PASS**, **FAIL** or
  **INCONCLUSIVE** and moves the batch to **APPROVED** or **REJECTED** accordingly.

The eight requirements the phase was written against, and where each is answered:

| Requirement | Where it lives |
| --- | --- |
| Processing module — facilities, batches, input/output, status tracking | `models/processing.py`, `services/processing_service.py`, `/api/v1/processing*` |
| Laboratory module — samples, parameters, results, status tracking | `models/laboratory.py`, `services/laboratory_service.py`, `/api/v1/lab-*` |
| Quality parameters and thresholds | `lab_parameters` catalogue + `services/quality_rules.py` |
| Batch lifecycle updating as the batch moves | `services/batch_lifecycle.py` (the only writer) |
| Traceability synchronisation — lab result visible to the beekeeper | one batch record; `BatchDetail.laboratory` and `BatchTraceStage.outcome` read it |
| RBAC for processor and laboratory roles | `core/permissions.py`, `api/dependencies.py`, per-route dependencies |
| No duplication of batch/traceability records | no second batch table, no copied status; results carry a *reference snapshot* of the range, not a copy of the batch |
| Verification with real data | `tests/test_processing.py`, `tests/test_laboratory.py`, `tests/api_smoke_phase6.py`, `tests/browser_smoke_role_navigation.py` |

The role-based workspace prompt that followed this phase is reported separately, in
`docs/phase-6-role-workspaces-report.md`; it changed navigation and the beekeeper's read-only view
of the laboratory stage, not the processing/laboratory rules described here.

---

## 2. The model, as the database and the code define it

```
HoneyCollection ──▶ HoneyBatch ──┬─▶ HoneyProcessingRecord ──▶ ProcessingUnit
   (Phase 5)         (Phase 5)   │        (a run)
                                 ├─▶ LabTest ──▶ LabTestResult ──▶ LabParameter
                                 │   (a sample)     (measurements)   (the catalogue)
                                 └─▶ AuditLog (every transition, one row per event)
```

* **One batch.** Processing and laboratory records point at `honey_batches.id`. Nothing is copied
  onto the batch itself: no `latest_lab_result` column, no second "batch" row per stage. The API
  derives what the beekeeper sees from the records that exist.
* **One lifecycle writer.** `batch_lifecycle.advance()` is the only code that changes
  `honey_batches.status`. Services call it; routes never touch the column.
* **A range, snapshotted per result.** `lab_parameters` holds the *current* reference range for each
  parameter code. When a measurement is recorded, `lab_test_results` stores the value **and** the
  min/max that were in force at that moment, plus the source label. Re-configuring a range later
  cannot rewrite the history of a test that was decided under the old one.
* **Nothing is generated twice.** Codes come from the existing `DocumentSequence`
  (`HC-PROC-…`, `HC-LAB-…`, `HC-SMP-…`, and `HC-PU-…` / `HC-LABUNIT-…` for the facilities), in the
  same sequence rows the earlier phases already use.

Transitions added in this phase (`app/models/enums.py`):

```
COLLECTED   → PROCESSING
PROCESSING  → LAB_TESTING, COLLECTED          (a cancelled run returns the batch)
LAB_TESTING → APPROVED, REJECTED, LAB_TESTING (a retest stays in testing)
APPROVED    → LAB_TESTING                     (a retest starts by withdrawing the decision)
REJECTED    → LAB_TESTING
PACKAGED, DISTRIBUTION, COMPLETED → ()        (reserved: reachable in no code path)
```

A conflict is reported, not swallowed: `batch_lifecycle` raises a `ConflictError` carrying
`current_status` and `allowed_next`, so an out-of-order request gets a 409 that names what the batch
would actually accept.

---

## 3. Database work

One migration, applied and verified with `alembic check` (no drift):

`alembic/versions/20260925_1030_9b4d2f81ac07_phase_6_processing_and_laboratory.py`
(sits on `7c1f0b93d0e2`; head is **`9b4d2f81ac07`**)

| Table | Purpose | Notable columns |
| --- | --- | --- |
| `processing_units` | A plant or line where work is done | `unit_code` (unique), `unit_name`, `unit_type`, `facility_status`, `district`, `state`, capacity fields |
| `honey_processing_records` | One run of one batch | `processing_code` (unique), `batch_id`, `unit_id`, `processing_type`, `status`, `input_quantity`/`output_quantity` (loss derived = input − output), timestamps per transition, `notes`, `cancellation_reason` |
| `laboratories` | A lab that can be named on a test | `laboratory_code` (unique), `laboratory_name`, `accreditation_note`, contact fields, `facility_status` |
| `lab_parameters` | The review catalogue: 13 parameter codes | `code` (unique), `name`, `unit`, `reference_min`, `reference_max` (both nullable), `reference_source`, `is_required` |
| `lab_tests` | A sample and the test on it | `test_code` + `sample_code` (unique), `batch_id`, `laboratory_id`, `status`, `overall_result`, `round_number`, `retest_of_id`, decision fields, `override_*` |
| `lab_test_results` | One measurement | `lab_test_id`, `parameter_code`, `value`, `unit`, `status`, **snapshot** `reference_min`/`reference_max`/`reference_source` |

Also added: `ProcessingStatus`, `ProcessingType`, `FacilityStatus`, `LabTestStatus`, `LabResult`,
`LabParameterStatus` enums, and two Phase-6 audit action families
(`PROCESSING_*`, `LAB_TEST_*`/`LAB_PARAMETER_CONFIGURED`).

`NULL` reference ranges are meaningful and load-bearing: a parameter with no configured range is
recorded and labelled **NOT_EVALUATED** rather than silently passing. That is why both bounds are
nullable rather than defaulted to 0/100.

---

## 4. Backend changes

**Route → service → repository → model**, as the rest of the project is laid out.

* `app/repositories/{processing_repository,laboratory_repository}.py` — queries only, including the
  scope filters (`officer_cluster_ids`, `own_beekeeper`) that list endpoints need so that a page
  cannot leak rows the single-record checks would refuse.
* `app/services/processing_service.py` — capability checks, run creation (one open run per batch
  enforced by a partial-unique index *and* a service check), start/complete/cancel, loss arithmetic
  (`output_quantity ≤ input_quantity`, both > 0), and the transition calls into the lifecycle.
* `app/services/laboratory_service.py` — test creation against a batch that has reached
  `LAB_TESTING`, measurement recording with the range snapshot, the completion decision, the
  retest flow (`round_number`, `retest_of_id`, withdraw-then-decide), and the ADMIN-only override
  which requires a reason of at least 10 characters and writes both the computed and the overridden
  result to the audit row.
* `app/services/quality_rules.py` — pure functions. `evaluate_parameter(value, parameter)` decides
  PASS/FAIL/NOT_EVALUATED for one measurement; `decide(results, required_codes)` produces the test
  verdict, its one-line summary and its plain-language reasons ("No reference range is configured
  for: MOISTURE — the measurements are recorded but nothing was compared against them.").
  `required_codes` comes from the catalogue, not from the results, so a test cannot dodge a required
  measurement by simply not recording it.
* `app/services/batch_lifecycle.py` — the single writer described in §2.
* `app/core/permissions.py` — `PROCESSING_READ`, `PROCESSING_WRITE`, `PROCESSING_UNIT_MANAGE`,
  `LAB_TEST_READ`, `LAB_TEST_WRITE`, `LAB_TEST_OVERRIDE`, `LAB_PARAMETER_READ`,
  `LAB_PARAMETER_CONFIGURE`, granted to the roles the prompt allows: processor writes processing,
  lab technician writes tests, KVIC reads both inside its clusters, beekeeper reads its own batch.
  Configuring reference ranges is deliberately separate from writing tests.
* `app/api/dependencies.py` — reusable `require_permission(...)` dependencies; no route inspects a
  role string by hand.
* Audit events are written inside the service transaction, so a state change and its audit row
  either both exist or neither does.

**Two behaviours worth naming.** `_apply_decision()` withdraws a decided batch before applying a new
decision, because `APPROVED`/`REJECTED` may only move to `LAB_TESTING`. And completing a test is
idempotent in the sense that a second completion attempt is refused by status rather than
recomputing and rewriting the existing verdict.

---

## 5. API surface added

**29 routes** under `/api/v1/` (the whole application exposes 135). All of them return the standard
`{success, data}` envelope, paginate their lists, and validate with Pydantic
(`extra="forbid"` on request bodies — an unknown field is a 422, not a silent ignore).

| Method | Path | Who |
| --- | --- | --- |
| GET/POST | `/processing-units` | processor, admin write; KVIC read |
| PATCH | `/processing-units/{unit_id}` | processor, admin |
| GET | `/processing` | processor, admin, KVIC (cluster-scoped) |
| POST | `/processing` | processor, admin |
| GET | `/processing/awaiting` | processor queue of batches in `COLLECTED` |
| GET | `/processing/summary` | processor dashboard counters |
| GET/PATCH | `/processing/{processing_id}` | read: processor/admin/KVIC; write: processor/admin |
| POST | `/processing/{processing_id}/start` · `/complete` · `/cancel` | processor, admin |
| GET | `/processing/{processing_id}/history` | the run's audit trail |
| GET/POST | `/laboratories` | lab technician, admin write; KVIC read |
| PATCH | `/laboratories/{laboratory_id}` | lab technician, admin |
| GET | `/lab-parameters` | all staff roles that may read a test |
| PATCH | `/lab-parameters/{code}` | admin (range configuration) |
| GET/POST | `/lab-tests` | lab technician, admin |
| GET | `/lab-tests/awaiting` | queue of batches in `LAB_TESTING` |
| GET | `/lab-tests/summary` | counters for dashboards |
| GET/PATCH | `/lab-tests/{test_id}` | lab technician, admin (KVIC read within clusters) |
| POST | `/lab-tests/{test_id}/results` | record one measurement |
| PATCH/DELETE | `/lab-tests/{test_id}/results/{result_id}` | correct a measurement while the test is open |
| POST | `/lab-tests/{test_id}/complete` | decide the test and move the batch |
| POST | `/lab-tests/{test_id}/override` | admin only, reason required |

`BatchDetail` grew the fields the beekeeper's screen needs, all derived:
`processing_count`, `processing` (the latest run, a single reference — not a list),
`test_count`, `laboratory` (the latest test with its results and its `overall_result`), and
`allowed_next_statuses`. `BatchTraceStage` gained `outcome`, which is how the laboratory row reads
"✓ Approved" / "✕ Rejected" instead of a second status vocabulary.

---

## 6. What the laboratory stage does **not** do

* It does not certify honey, and the UI says no such thing. There is no "certified", "grade",
  "organic" or regulatory-compliance wording anywhere in the phase's copy.
* It does not invent thresholds. Every comparison is made against a range an administrator
  configured in `lab_parameters`, with the configured source recorded on the result row.
* It does not turn a missing range into a pass. No range ⇒ `NOT_EVALUATED` ⇒ the test is
  `INCONCLUSIVE`, and the batch does not advance to `APPROVED`.
* It does not let a lab technician grade their own work: overriding a computed result needs
  `LAB_TEST_OVERRIDE` (ADMIN) and a written reason.
* It does not touch, and does not claim, blockchain anchoring. That belongs to a later phase and is
  marked as such wherever the UI mentions future work.
* It does not create a second batch, a second sample, or a parallel "lab status" field. There is one
  batch row and one set of laboratory rows, read by everyone who is allowed to see them.

---

## 7. Frontend

Built with the agreed stack (React + Vite, JavaScript only, Tailwind, React Router, Axios, Recharts,
Lucide, React Hook Form, Zod, Framer Motion) and the honey/gold + deep-green + white-card system.

* `components/processing/` — `ProcessingWorkspace`, `AwaitingProcessingTable`, `ProcessingRunTable`,
  `ProcessingRunPanel` (create, start, complete with measured quantities, cancel with a reason).
* `components/laboratory/` — `LaboratoryWorkspace`, `AwaitingTestingTable`, `LabTestTable`,
  `LabTestPanel` (the record-a-measurement form, the recorded results with their snapshotted range
  and status, complete-and-decide, retest), `ParameterCatalogueTable`, `LaboratoryFacilitiesCard`.
* `components/collections/QualitySummaryCard.jsx` — the read-only quality card: latest run, latest
  test, each measurement with the range it was judged against, and the verdict's own words. It reads
  `batch.processing` (one run) and `batch.laboratory` (one test) and states the counts when more
  exist, rather than implying the payload holds a list.
* `components/collections/BatchTimeline.jsx` — five stage rows with a state badge per row and a
  `data-stage` attribute; the laboratory row carries the outcome.
* Pages: processor workspace + run detail; laboratory workspace, test detail, parameter catalogue,
  laboratories; KVIC processing and laboratory oversight (read-only); admin processing/laboratory.
* Messages are honest in both directions: "No batches awaiting processing.",
  "No batches awaiting laboratory testing.", "No laboratory results recorded.",
  "Loading batch information…", "Unable to load laboratory information."

Every write path in the UI is gated on the same central navigation/permission configuration the
sidebar uses — `canWrite` is `PROCESSOR|ADMIN` for processing and `LAB_TECHNICIAN|ADMIN` for the
laboratory — and the API refuses the request anyway if the role is wrong.

---

## 8. Verification evidence

All of the following were run against the live development stack (PostgreSQL 17.11, API on
`:8000`, a production build served by `vite preview` on `:4173`), not against mocks.

| Suite | Result |
| --- | --- |
| Full backend pytest suite | **695 passed, 1 warning, 0 failed** in 871 s — see §8.1 |
| `tests/test_processing.py` | 61 tests — duplicate open run raises `IntegrityError`, a beekeeper is forbidden, cancel returns the batch to `COLLECTED`, `by_unit.KG` loss 0.8 kg = 5.84%, Phase-7 URLs 404 |
| `tests/test_laboratory.py` | 77 tests — no range ⇒ `NOT_EVALUATED`/`INCONCLUSIVE`, a required failure ⇒ `REJECTED`, closed tests are immutable, a retest is `round_number=2`, ADMIN-only override records `computed_result` |
| `tests/api_smoke_phase6.py` | 176 passed / 0 failed — RBAC matrix, 409s on illegal transitions, `INCONCLUSIVE → PASS → APPROVED`, `FAIL → REJECTED`, override-withdraw, out-of-cluster 404s |
| `tests/api_smoke_phase{2,3,4,41,5}.py` | 43/0, 64/0, 73/0, 43/0, 77/0 |
| `tests/browser_smoke_role_navigation.py` | **63 passed / 0 failed** — the end-to-end laboratory→beekeeper synchronization walk |
| `tests/browser_smoke.py` | 38 / 0 |
| `tests/browser_smoke_phase2.py` | 28 / 0 |
| `tests/browser_smoke_phase3.py` | 112 / 0 |
| `tests/browser_smoke_phase41.py` | 26 / 0 |
| `tests/browser_smoke_phase5.py` | 51 / 0 |
| `npm run lint` | clean |
| `npm run build` | green |

### 8.1 The full suite

```
cd backend && .venv/bin/python -m pytest
695 passed, 1 warning in 871.31s (0:14:31)
```

The single warning is Starlette's own `anyio.abc.BlockingPortal` deprecation notice from
`TestClient`, not this project's code. The suite covers Phases 1–6 (identity, beekeepers, hives, IoT,
telemetry, AI, collections, batches, processing, laboratory) against a real PostgreSQL database that
it drops, creates and re-seeds itself.

### 8.2 The end-to-end walk that matters most

`tests/browser_smoke_role_navigation.py` drives the real UI with a real browser and asserts the one
thing this phase exists for:

1. a processor registers a unit, a beekeeper records a harvest, completing it creates
   `HC-BATCH-…`, a run opens and completes with measured quantities (12.5 kg → 11.8 kg), and the
   batch is now `LAB_TESTING`;
2. an administrator configures the `MOISTURE` range (0–20);
3. switching to the laboratory technician, the pending queue names the batch, the sample opens, a
   traceability chain is shown *read from the records*, and no result is claimed before one is
   recorded;
4. the technician types 17.4, saves it, and the screen shows the value, the parameter judged against
   the configured range, the verdict **PASS** ("Every recorded parameter is within its configured
   range"), written by the server — not by the form;
5. switching to the beekeeper: the same batch is **Approved**, the laboratory stage reads approved,
   packaging is still honestly *pending*, the processing quantities are the measured ones, and there
   is no control over the laboratory record anywhere on the page;
6. switching to the KVIC officer: the same batch, the same outcome, read-only, with no laboratory
   controls offered.

A failure found by this walk and fixed in it: the measurement field is a controlled numeric input,
and the walk's original typing simulation kept only the first digit of `17.4` — the shipped form was
fine (native `fill` sets the value the way React expects), but the test was asserting against a
value the browser never delivered. The walk now fills, asserts what the field actually contains,
saves, and then asserts what the page shows.

### 8.3 The bug the walk caught in the product

The batch screens rendered **nothing** for a batch once it had been through the laboratory:
`QualitySummaryCard` and `BatchDetailView` treated `batch.processing` as a list and called
`.filter`/`.map` on it, while the API returns a **single** `BatchProcessingRef | None`. React threw
`TypeError: a.filter is not a function`, the error boundary blanked the page, and the beekeeper's
traceability view died silently. Both components now read one run and one test, print the counts
when more records exist, and the browser walk asserts the quantities (12.5/11.8), the measured
value, and the approved status on the screen. This is why the phase was not considered done until
the browser walk passed: the unit and API suites never touched that shape.

---

## 9. Acceptance walk (development environment)

```bash
# stack
pg_ctlcluster 17 main start
cd backend && .venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.scripts.seed_dev_data
.venv/bin/python -m app.scripts.seed_lab_parameters --check     # 13/13 configured
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

# frontend
cd ../frontend && npm install && npm run build && npx vite preview --port 4173 --host 0.0.0.0

# evidence
cd ../backend
.venv/bin/python -m pytest -q
.venv/bin/python tests/api_smoke_phase6.py
SMOKE_BASE_URL=http://localhost:4173 .venv/bin/python tests/browser_smoke_role_navigation.py
```

Sign in at `http://localhost:4173` with the seeded accounts (`*@honeychain.example.com`; the
development passwords are listed in `run.md`): the processor records a run, the lab technician
records a measurement and completes the test, and the beekeeper's own batch page shows the outcome
without being able to change it.

---

## 10. Test data and development fixtures

* `app/scripts/seed_dev_data.py` — extends the existing dev fixture: a `PROCESSOR` account, a
  `LAB_TECHNICIAN` account, one processing unit, one laboratory. Idempotent; re-running it does not
  duplicate anything. It deliberately does **not** create telemetry or laboratory results.
* `app/scripts/seed_lab_parameters.py` — the 13-code review catalogue: `MOISTURE`, `HMF`, `SUCROSE`,
  `PH`, `FREE_ACIDITY`, `ASH`, `COLOR`, `DIASTASE_ACTIVITY`, `REDUCING_SUGARS`, `PURITY`,
  `ELECTRICAL_CONDUCTIVITY`, `WATER_INSOLUBLE_SOLIDS` and `OTHER`, each with its unit and with
  `NULL` reference bounds until an administrator configures them (only `MOISTURE` is flagged
  required in the development fixture). `--check` reports coverage; the script is idempotent. The
  `Unit` column is a real enum (`LabMeasureUnit.PH_SCALE` for pH, `%`, `mg/kg`, `DN`, …).
* Telemetry used by the dashboards comes from `app/scripts/hive_simulator.py` and is stored with
  `source = SIMULATOR`; the simulator is the only thing that writes readings in development, and
  every screen that shows a reading shows that label.
* The smoke suites clean up after themselves (`lab_test_results` → `lab_tests` →
  `honey_processing_records` → `honey_batches` → `honey_collections`), and the cleanup now deletes
  results by their real foreign key (`lab_test_id`), after the first cleanup attempt silently aborted
  and left a batch behind.

---

## 11. Explicitly not built (and why)

Packaging, distribution, QR scanning, customer verification, trust score, blockchain anchoring and
smart contracts are **not** implemented, not routed, and not described as shipped. The reserved
batch statuses (`PACKAGED`, `DISTRIBUTION`, `COMPLETED`) exist in the enum so the schema is stable
for the phase that implements them, and `batch_lifecycle` allows no transition into them — the
Phase-7 URL space returns 404, which `test_processing.py` asserts. On the beekeeper's timeline those
rows say "Not implemented in this phase" rather than showing an empty promise.

The reference ranges shipped by the catalogue script are development fixtures, not asserted
scientific limits: the platform compares against what an administrator configured and records where
that range came from. The beekeeper's laboratory view is read-only in the data model (no write
permission) and in the UI (no controls).

---

## 12. Risks, trade-offs and how they are contained

| Risk | Containment |
| --- | --- |
| A run or test silently rewrites batch status | `batch_lifecycle.advance()` is the single writer; every call audits; illegal moves raise `ConflictError` with the allowed set |
| A stale range re-classifies an old test | the range is snapshotted onto each result row at recording time, and the source label with it |
| A test passes because a required measurement was skipped | `required_codes` comes from the catalogue, not the results; missing required ⇒ `INCONCLUSIVE`, never `PASS` |
| Laboratory rows leak across clusters | repositories apply the same `officer_cluster_ids` filter as the single-record `can_access` check, and the smoke asserts an out-of-cluster test is a 404 |
| Two open runs or two identical codes | partial-unique index for the open run plus `DocumentSequence` for every code, both enforced in the database |
| An override quietly erases the computed verdict | the override row keeps `computed_result`, the reason, and the actor, and the audit event records both results |
| The UI claims more than the data supports | every card states what it read and what is absent; "pending" and "not implemented" are distinct words |

---

## 13. Files changed in this phase

**Backend — new**

```
app/models/processing.py            app/models/laboratory.py
app/repositories/processing_repository.py   app/repositories/laboratory_repository.py
app/services/processing_service.py  app/services/laboratory_service.py
app/services/batch_lifecycle.py     app/services/quality_rules.py
app/schemas/processing.py           app/schemas/laboratory.py
app/routes/processing.py            app/routes/laboratory.py
app/scripts/seed_lab_parameters.py
alembic/versions/20260925_1030_9b4d2f81ac07_phase_6_processing_and_laboratory.py
tests/test_processing.py            tests/test_laboratory.py
tests/api_smoke_phase6.py
```

**Backend — extended**

```
app/models/enums.py (6 enums, 2 transition tables, 2 audit families)
app/models/__init__.py, app/api/router.py, app/api/dependencies.py
app/core/permissions.py (8 permissions + grants)
app/schemas/batch.py (BatchDetail: processing_count, processing, test_count, laboratory,
                      allowed_next_statuses; BatchTraceStage: outcome)
app/services/batch_service.py (timeline derivation for the two new stages)
app/scripts/seed_dev_data.py (processor + laboratory fixtures)
tests/conftest.py (Phase-6 truncation order, re-seed of the catalogue)
tests/api_smoke_phase5.py (later-stage assertions, now that two of them are reachable)
```

**Frontend — new**

```
src/constants/processing.js         src/constants/laboratory.js
src/services/processingService.js   src/services/laboratoryService.js
src/components/processing/{ProcessingWorkspace,AwaitingProcessingTable,ProcessingRunTable,ProcessingRunPanel}.jsx
src/components/laboratory/{LaboratoryWorkspace,AwaitingTestingTable,LabTestTable,LabTestPanel,ParameterCatalogueTable,LaboratoryFacilitiesCard}.jsx
src/components/collections/{BatchTimeline,QualitySummaryCard,BatchDetailView,BatchWorkspace,BatchTable}.jsx
src/pages/processing/{ProcessorWorkspacePage,ProcessingRunDetailPage}.jsx
src/pages/laboratory/{LaboratoryWorkspacePage,LabTestDetailPage,ParameterCataloguePage,FacilitiesPage}.jsx
src/pages/kvic/{KvicProcessingPage,KvicLaboratoryPage}.jsx
src/pages/admin/{AdminProcessingPage,AdminLaboratoryPage}.jsx
```

**Frontend — extended**

```
src/constants/api.js (ENDPOINTS.processing, ENDPOINTS.laboratory)
src/constants/collection.js (BATCH_STATUS_META, BATCH_STATUS_OPTIONS)
src/routes/AppRoutes.jsx (processor + laboratory route trees, role allow-lists)
src/components/layout/Sidebar.jsx (central navigation configuration)
```

---

## 14. Where the project stands

The chain the problem statement describes now runs end to end inside the platform, on real rows:

```
KVIC → Cluster → Beekeeper → Hive → IoT → Telemetry → AI → Collection → Batch → Processing → Laboratory
```

A batch can be created from a harvest, processed with measured quantities, tested against
configured reference ranges, approved or rejected, and read back — by the beekeeper who owns it, by
the officer whose cluster contains it, and by the platform's administrators — from one record, with
every state change audited. The next phases (packaging, distribution, QR/customer verification,
trust score, anchoring) have their reserved vocabulary and nothing else.
