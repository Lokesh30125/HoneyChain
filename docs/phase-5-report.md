# HoneyChain — Phase 5 delivery report

**Honey collections and honey batches: a real harvest becomes a traceable batch**

*Smart India Hackathon 2026 · Problem Statement 26021 · Report generated 27 September 2026*

---

## 1. What this phase set out to do

Phases 1–4.1 built the people and the hardware side of the chain: accounts and roles, beekeepers and
clusters, hives, IoT devices and telemetry, AI analyses and alerts. None of it produced anything a
supply chain could move.

Phase 5 builds the first two records that can be *owned* and *moved*: a **honey collection** (what
actually came out of the hives) and the **honey batch** it produces (the traceable unit every later
stage attaches to).

| Requirement | Where it lives |
| --- | --- |
| Record a harvest against one or more hives, with the quantity actually taken | `models/honey_collection.py`, `models/honey_collection_hives`, `/api/v1/collections` |
| Track a harvest from planned → in progress → completed/cancelled | `services/collection_service.py`, `CollectionStatus` |
| Create the traceable batch when a harvest completes | `COLLECTION_COMPLETED` → `BATCH_CREATED`, one batch per collection |
| Batch identity, ownership, cluster and source hives readable together | `/api/v1/batches*`, `services/batch_service.py` |
| A timeline that shows where the batch stands | `BatchTraceStage` + `components/collections/BatchTimeline.jsx` |
| Role-appropriate visibility (own batches, cluster batches, all batches) | `core/permissions.py` (`BATCH_READ_SELF` / `BATCH_READ_ALL`) |
| Nothing invented: no simulated harvest, no derived quantity | empty states everywhere; the only writer is the service |

The single most important design decision of the phase: **three quantities are kept apart.**
`hive_ai_analyses.predicted_yield_kg` is what the AI *estimated*; `sensor_readings.weight` is what a
scale *measured* (including the box, frames and bees); `honey_collections.total_quantity` is what the
beekeeper actually *harvested*. Nothing derives one from another, and the collection stores the
harvested figure with the AI estimate snapshotted **next to it**, never instead of it.

---

## 2. The model

```
Beekeeper ──▶ HoneyCollection ──┬─▶ HoneyCollectionHive ──▶ Hive
   │              (the harvest)  │        (one row per contributing hive,
   │                             │         with its own quantity + AI snapshot)
   │                             └─▶ HoneyBatch (1:1, created on completion)
   │                                     │
   └── Cluster (snapshotted at harvest time)         Phase 6 → Processing → Laboratory
```

* **`honey_collections`** — the event: owner, cluster (nullable, recorded as the truth rather than
  guessed), planned and actual dates, `total_quantity` + `unit`, hive count, notes, status, a
  snapshot of the AI context (whether an analysis existed and what it predicted), and an optional
  `client_request_id` that is unique per beekeeper so a retried create cannot produce a second
  harvest.
* **`honey_collection_hives`** — one row per contributing hive: the quantity taken there, the hive's
  `hive_code` denormalised (a code never changes, and this keeps an old harvest readable even if the
  hive is later retired) and the per-hive AI estimate at the time. `ON DELETE RESTRICT`: a hive that
  contributed to a harvest cannot be hard-deleted out from under it.
* **`honey_batches`** — created by completing a collection, with `collection_id` **unique**: the
  constraint, not a convention, is what makes "one batch per completed collection" true. The batch
  repeats date, quantity, unit, owner and cluster on purpose — it has to stay interpretable on its
  own, exactly as it was at collection time — and it originates nothing. Source hives are reached
  through `batch → collection → honey_collection_hives → hives`, because a second copied list is a
  list that can drift.

Statuses: `CollectionStatus{PLANNED, IN_PROGRESS, COMPLETED, CANCELLED}` (only the last two are
terminal) and `CollectionUnit{KG, GRAM}` — both are mass, so a total is always a sum of like
quantities and nothing converts a bag of grams into a kilogram guess.
`BatchStatus` in Phase 5 could only be `COLLECTED`; nothing else was reachable.

---

## 3. Database work

One migration, applied and verified with `alembic check` (no drift):

`alembic/versions/20260924_1725_7c1f0b93d0e2_phase_5_collections_and_honey_batches.py`
(sits on `5e2b7d41c8aa`; later superseded by the Phase-6 head `9b4d2f81ac07`)

It creates `honey_collections`, `honey_collection_hives` and `honey_batches` with:

* `gen_random_uuid()` server defaults on every `id` (the project-wide rule);
* `Numeric(10, 3)` for quantities — weighed to the gram, room for a nine-tonne consignment, no float
  anywhere between the database and the JSON payload (quantities stay `Decimal` end to end);
* check constraints for non-negative quantities and for a unit that matches the stored figure;
* the unique constraint on `honey_batches.collection_id` and the per-beekeeper uniqueness of
  `client_request_id`;
* the audit actions the phase introduced (`COLLECTION_CREATED`, `COLLECTION_UPDATED`,
  `COLLECTION_COMPLETED`, `COLLECTION_CANCELLED`, `BATCH_CREATED`, `BATCH_STATUS_CHANGED`) and the
  `CollectionStatus` / `CollectionUnit` enums.

---

## 4. Backend changes

**Route → service → repository → model**, unchanged from the earlier phases.

* `repositories/collection_repository.py` / `batch_repository.py` — queries only, including the
  scope filters the list endpoints need (a beekeeper's own rows; a cluster officer's cluster rows),
  so pagination cannot leak what a single-record check would refuse.
* `services/collection_service.py` (≈1,250 lines) — the only writer of a collection. It validates
  the hives belong to the caller, refuses a hive that is retired, keeps `total_quantity` consistent
  with the per-hive rows, enforces the open/terminal status rules, derives the eligibility list for
  a new harvest, and on completion creates the batch **inside the same transaction** as the status
  change. A completed collection is immutable: hives, quantities, dates, owner and cluster stop
  being writable, which is what makes the batch trustworthy.
* `services/batch_service.py` — reads the batch with its sources, hives, collection and timeline;
  refuses every write (no Prompt-5 endpoint can change `batch_code`, `collection_id`,
  `beekeeper_id`, `cluster_id`, `collection_date`, `quantity`, `unit` or the AI snapshot) and offers
  `editable_fields: []` so a client can see the record is frozen rather than guess.
* `core/permissions.py` — `COLLECTION_READ_SELF`, `COLLECTION_WRITE_SELF`, `BATCH_READ_SELF` for the
  beekeeper, and `COLLECTION_READ_ALL` / `BATCH_READ_ALL` for KVIC, ADMIN and the later supply-chain
  roles. There is deliberately **no** `COLLECTION_WRITE_ALL`: a harvest is recorded by the person who
  took the honey, and no staff role may write one on their behalf.
* Codes (`HC-COL-{YYYY}-{NNNNNN}`, `HC-BATCH-{YYYY}-{NNNNNN}`) come from the existing
  `DocumentSequence`; nothing is hardcoded and nothing is generated in the client.
* Every create, update, completion, cancellation and batch creation writes an audit event in the
  same transaction.

---

## 5. API surface added

| Method | Path | Who |
| --- | --- | --- |
| GET/POST | `/api/v1/collections` | beekeeper (own), KVIC/ADMIN (read all) |
| GET/PATCH | `/api/v1/collections/{collection_id}` | owner while open; staff read |
| POST | `/api/v1/collections/{collection_id}/complete` | owner — creates the batch and returns its meta |
| POST | `/api/v1/collections/{collection_id}/cancel` | owner |
| GET | `/api/v1/collections/{collection_id}/batch` | owner, staff — the batch this harvest produced |
| GET | `/api/v1/collections/summary` | counters for the dashboards |
| GET | `/api/v1/collections/eligible-hives` | hives that may contribute to a new harvest |
| GET | `/api/v1/hives/{hive_id}/collections` · `/api/v1/clusters/{cluster_id}/collections` | the harvest history of a hive / a cluster |
| GET | `/api/v1/batches` · `/api/v1/batches/{batch_id}` | owner, cluster officer, ADMIN |
| GET | `/api/v1/batches/{batch_id}/sources` | the contributing hives with their quantities |
| GET | `/api/v1/batches/{batch_id}/hives` | the hives behind the batch |
| GET | `/api/v1/batches/{batch_id}/collection` | the harvest that produced it |
| GET | `/api/v1/batches/{batch_id}/timeline` | the stage-by-stage view |
| GET | `/api/v1/batches/summary` | counters |
| GET | `/api/v1/clusters/{cluster_id}/batches` | cluster-scoped batch list for KVIC |

All list endpoints paginate and return the standard `{success, data}` envelope; all request bodies
forbid unknown fields; nothing returns a password hash, a token or an internal id the caller may not
address.

---

## 6. What a batch view does **not** do

* It does not let anyone edit a batch. There is no batch write endpoint at all, and
  `editable_fields` is an empty list so the frozen record is explicit rather than implied.
* It does not invent a quantity. If no harvest was recorded there is no batch, and the lists say so
  ("No honey batches created yet.") instead of showing zero-valued sample rows.
* It does not describe stages that were not built. In Phase 5 the timeline ended at Collection; the
  rows for processing, laboratory, packaging and distribution were rendered as *not started* and, in
  the current build, each row says plainly whether the module exists.
* It does not compare the AI estimate with the harvest unless an analysis actually exists; the
  `ai_context` block reports `has_analysis: false` rather than manufacturing a difference.
* It does not convert units, average hives, or extrapolate a yield. Every figure shown is a figure
  somebody recorded.

---

## 7. Frontend

Same agreed stack and design system as the earlier phases (React + Vite, JavaScript only, Tailwind,
React Router, Axios, Recharts, Lucide, React Hook Form, Zod, Framer Motion; honey/gold + deep green +
white cards).

* `pages/collections/CollectionsPage.jsx` — the register of harvests with filters, pagination and an
  honest empty state.
* `pages/collections/CollectionDetailPage.jsx` — the harvest: the contributing hives with their
  quantities, the AI context, and the Complete/Cancel actions, which disappear once the record is
  terminal.
* `components/collections/RecordCollectionPanel.jsx` — React Hook Form + Zod: hive selection from the
  eligible list, per-hive quantities, unit, dates; the same validation rules as the API.
* `pages/collections/BatchesPage.jsx` / `BatchDetailPage.jsx` — the batch register and the batch
  record, with a role-aware breadcrumb/base (`/beekeeper/batches`, `/kvic/batches`, `/processor/batches`,
  `/admin/...`) so the same screen sits inside whichever workspace opened it.
* `components/collections/{BatchTimeline,BatchTable,BatchWorkspace,CollectionTable,CollectionWorkspace}.jsx`
  — the timeline with one row per stage, the tables with status badges driven by
  `BATCH_STATUS_META`, and the shared workspace shells.
* Every screen in this phase distinguishes *absent* from *zero*: a beekeeper with no harvest sees
  why the register is empty and what to do next, not a dashboard of zeros pretending to be data.

---

## 8. Verification evidence

Run against a real PostgreSQL database — the test suite drops and re-creates its own schema, and the
browser walks run against the live API and a production build served by `vite preview`.

| Suite | Result |
| --- | --- |
| `tests/test_collections.py` | 55 tests |
| `tests/test_honey_batches.py` | 27 tests |
| `tests/api_smoke_phase5.py` | **77 passed / 0 failed** |
| `tests/browser_smoke_phase5.py` | **51 passed / 0 failed** |
| Full backend suite (Phases 1–6, latest run) | **695 passed, 0 failed** in 871 s |

What the checks actually assert, from the suites as they stand:

* a completed collection produces exactly **one** batch, and a retried completion cannot produce a
  second (`collection_id` uniqueness is exercised through the API, not assumed);
* a cancelled collection can never produce a batch, and a completed one can never be edited or
  cancelled;
* a beekeeper cannot read or write another beekeeper's harvest; a KVIC officer reads only the
  harvests and batches of their own cluster, and an out-of-cluster record is a 404 rather than a
  403 that would confirm it exists;
* the per-hive quantities sum to the collection total, and a hive that does not belong to the caller
  is refused;
* quantities survive the round trip as `Decimal` (`4.5` kg recorded stays `4.5` kg — no float drift
  between the API, the database and the screen);
* the batch's snapshot does not move when the collection is read later, and no Prompt-5 endpoint can
  change it;
* the batch timeline reports Collection complete and every later stage not started, with the
  packaging/distribution rows labelled as modules this build does not contain;
* the Phase-7 URL space returns 404: nothing in this phase pretends packaging or distribution exists.

---

## 9. Acceptance walk (development environment)

```bash
cd backend
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.scripts.seed_dev_data
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
cd ../frontend && npm run build && npx vite preview --port 4173 --host 0.0.0.0

cd ../backend
.venv/bin/python -m pytest tests/test_collections.py tests/test_honey_batches.py
.venv/bin/python tests/api_smoke_phase5.py
SMOKE_BASE_URL=http://localhost:4173 .venv/bin/python tests/browser_smoke_phase5.py
```

By hand: sign in as `beekeeper@honeychain.example.com`, open **Honey Collections**, record a harvest
against a hive, mark it **In progress**, then **Complete** it. The register shows `HC-COL-…`, and
under **Honey Batches** the same harvest now appears as `HC-BATCH-…` with its source hive, its
quantity, and a timeline where Collection is complete and the later stages are honestly untouched.

---

## 10. Test data and development fixtures

* The collections and batches used by the browser walks are created **through the API** by the walk
  itself and removed afterwards, so no harvest is seeded into the development database and no
  sample batch is ever mistaken for real data.
* `seed_dev_data.py` continues to provide accounts, the cluster, the beekeeper, one hive and one
  device — deliberately **no** collections, batches or telemetry, because those are things that only
  happen when someone does them.
* The only reading-producing script in development remains
  `app/scripts/hive_simulator.py`, whose packets are stored with `source = SIMULATOR` and labelled as
  such on every screen that shows them.

---

## 11. Explicitly not built (and why)

Processing, the laboratory, packaging, distribution, QR/customer verification, trust score and
blockchain anchoring are out of scope for this phase. Consequently:

* `BatchStatus` reserves `PACKAGED`, `DISTRIBUTION` and `COMPLETED` but no code path can set them;
* the batch timeline renders those rows as not started and, in the current build, says the module is
  not implemented rather than showing a promise;
* the Phase-7 URL space returns 404, which the tests assert;
* nothing in the phase claims certification, provenance anchoring or a quality grade.

---

## 12. Risks, trade-offs and how they are contained

| Risk | Containment |
| --- | --- |
| Two batches from one harvest (a double-click, a retry) | unique `collection_id` on `honey_batches`, plus a per-beekeeper `client_request_id` on the collection; the completion runs in one transaction |
| A harvest edited after it became a batch | completed collections are immutable in the service (the only writer) and the batch is a snapshot that cannot be written at all |
| The AI estimate being mistaken for the harvest | the three quantities are separate columns with separate meanings, and the UI names both |
| Losing the per-hive contribution ("22.5 kg from 3 hives") | one `honey_collection_hives` row per contributing hive, with its own quantity, kept for the life of the batch |
| A hive delete breaking history | `ON DELETE RESTRICT` on the contribution rows; retiring a hive (status REMOVED) remains available |
| Cross-role data leaks | scope filters in the repositories mirror the single-record checks, and the API returns 404 — not 403 — for a record outside the caller's scope |
| Unit confusion (kg vs g) | a unit enum with no conversion anywhere; totals are sums of like quantities only |

---

## 13. Files changed in this phase

**New**

```
backend/app/models/honey_collection.py          backend/app/models/honey_batch.py
backend/app/repositories/collection_repository.py  backend/app/repositories/batch_repository.py
backend/app/services/collection_service.py      backend/app/services/batch_service.py
backend/app/schemas/collection.py               backend/app/schemas/batch.py
backend/app/routes/collections.py               backend/app/routes/batches.py
backend/alembic/versions/20260924_1725_7c1f0b93d0e2_phase_5_collections_and_honey_batches.py
backend/tests/test_collections.py               backend/tests/test_honey_batches.py
backend/tests/api_smoke_phase5.py
frontend/src/services/collectionService.js      frontend/src/services/batchService.js
frontend/src/constants/collection.js
frontend/src/pages/collections/{CollectionsPage,CollectionDetailPage,BatchesPage,BatchDetailPage}.jsx
frontend/src/components/collections/{CollectionTable,CollectionWorkspace,CollectionSummaryCards,CollectionContextPanels,RecordCollectionPanel,BatchTable,BatchWorkspace,BatchDetailView}.jsx
```

**Extended**

```
backend/app/models/enums.py            (CollectionStatus, CollectionUnit, BatchStatus, 6 audit actions)
backend/app/core/permissions.py        (COLLECTION_*, BATCH_READ_*)
backend/app/api/router.py              (collections, batches routers mounted)
backend/tests/conftest.py              (Phase-5 truncation order)
frontend/src/constants/api.js          (ENDPOINTS.collections, ENDPOINTS.batches)
frontend/src/routes/AppRoutes.jsx      (collection and batch route trees)
```

---

## 14. Where the project stands

After Phase 5 the platform held a complete, real record of the first half of the chain:

```
KVIC → Cluster → Beekeeper → Hive → IoT → Telemetry → AI → Collection → Batch
```

A harvest is a real event with real quantities, its per-hive contributions stay queryable, and the
batch it produces is a frozen, unique, auditable record that later phases attach their own work to.
Phase 6 then gave that batch a processing history and a laboratory verdict — reported in
`docs/phase-6-report.md` — and the role-navigation work that followed is reported in
`docs/phase-6-role-workspaces-report.md`.
