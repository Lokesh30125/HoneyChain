# HoneyChain — Phase 8 delivery report

**Blockchain traceability: the service that already exists, wired into the real workflow**

*Smart India Hackathon 2026 · Problem Statement 26021 · Report generated 30 September 2026*

---

## 1. What this phase set out to do

Phase 7 ended with a jar that had a code on it. Phase 8 makes that code mean something outside
HoneyChain: every real supply-chain transition now writes **one transaction** to the blockchain
service that already exists at `BLOCKCHAIN_BASE_URL` — and nothing else.

The work was an integration, not a rebuild. It added **one table**, **one package of server-side code**
(`app/services/blockchain/`: one client, one event builder, the service, the QR drawing and the
worker), hooked into the services that already performed the transitions. It did
not add a second chain, a second copy of the operational data, a mock, a static array, a
frontend-only ledger, or a single transaction invented by a browser.

| Requirement group | Where it lives |
| --- | --- |
| Configuration by environment, never hard-coded | `app/core/config.py`, `.env.example` §3 below |
| One centralised client, no scattered HTTP | `app/services/blockchain/client.py` |
| An event at each real state transition (§ events) | `app/services/blockchain/service.py` + hooks in the five stage services |
| Payloads that carry real values and never sensitive ones | `app/services/blockchain/events.py` |
| Persistence without duplicate entities | `models/blockchain.py`, migration `20260929_1800_9b1f4c2d7e05` |
| Idempotency and a DB-backed outbox | `service.py` (`record`/`submit`/`sweep`/`retry`), `worker.py` |
| Ledgers, traceability, QR, health | `routes/blockchain.py`, `routes/trace.py`, `scripts/blocksync.py` |
| Role-appropriate access (§ roles) | `core/permissions.py` + the existing per-route guards |
| Screens in the existing design system | `frontend/src/{pages/blockchain,pages/public,components/blockchain}` |
| Verification with the real service | `tests/phase8_blockchain_workflow.py`, `tests/phase8_ui_checks.py`, `tests/test_blockchain.py` |

---

## 2. The integration in one picture

```
  a real transition                 the record and its event             the chain
  ───────────────────                ─────────────────────────            ─────────
  collection completed ┐
  processing started   │            ┌───────────────────────────┐
  laboratory decided   ├── hook ───▶ │  operational row (DB)     │
  packaging completed  │  (same     │  + blockchain_events row  │
  shipment dispatched  │   DB txn)  │    event_id  (unique)     │
  package released     │            │    tx_type   payload      │
  retailer received    ┘            │    status = PENDING       │
                                    └────────────┬──────────────┘
                                                 │  commit (together — or not at all)
                                                 ▼
                                    ┌───────────────────────────┐
                                    │  DB-backed outbox         │
                                    │  worker every N seconds   │
                                    │  or  POST /blockchain/sync│
                                    └────────────┬──────────────┘
                                                 │  POST {BASE_URL}/transactions
                                                 │  {tx_type, batch_id, payload}
                                                 ▼
                                    ┌───────────────────────────┐
                                    │  the existing service     │
                                    │  answers { tx_id }        │
                                    └────────────┬──────────────┘
                                                 ▼
                                    status = CONFIRMED, tx_id stored
```

Two properties fall out of that shape and are the whole point of the phase:

* **The database stays the source of truth.** The chain is written *from* the database, never read
  back to decide what the workflow does. An outage leaves every screen exactly as correct as it was,
  with the event marked `FAILED` and retryable.
* **Nothing is written ahead of the step it describes.** There is no "generate the whole chain for
  this batch" call anywhere in the codebase, and the frontend cannot name a `tx_type`: it sends a
  business action, and the backend decides what — if anything — that action means for the chain.

---

## 3. Configuration

Read through the project's existing `pydantic-settings` chain (`<root>/.env` → `backend/.env` →
`.env.<ENVIRONMENT>`), so a deployment changes them the same way it changes every other setting.

| Key | Example | Meaning |
| --- | --- | --- |
| `BLOCKCHAIN_ENABLED` | `true` | Master switch. When false the workflow still records events — they are marked `SKIPPED` with the reason and are visibly *not* on the chain. |
| `BLOCKCHAIN_BASE_URL` | `http://54.160.152.176:3001` | The service. The transactions endpoint is `${BASE_URL}/transactions`; no other URL is built anywhere. |
| `BLOCKCHAIN_TIMEOUT_MS` | `10000` | Per-request timeout. |
| `BLOCKCHAIN_RETRY_ATTEMPTS` / `BLOCKCHAIN_RETRY_BACKOFF_MS` | `3` / `500` | Bounded retry with backoff inside one submission. |
| `BLOCKCHAIN_OUTBOX_WORKER_ENABLED` / `_POLL_SECONDS` / `_BATCH_SIZE` | `true` / `5` / `25` | The background sweep: how often it runs and how much of a backlog it takes in one pass. |
| `PUBLIC_TRACE_BASE_URL` | `http://localhost:4173/trace` | The base of the link encoded in a package's QR code. |

**Server-side configuration is never returned to a browser.** `GET /blockchain/health` reports
`configured`, `reachable`, `latency_ms`, the service's ledger size and timestamp — and deliberately
**not** the address; `/health/detailed` (unauthenticated) carries the outbox counters only. A test
asserts the URL is absent from the health response, and the frontend contains no blockchain address
at all.

---

## 4. One client

`app/services/blockchain/client.py` is the only code in HoneyChain that speaks HTTP to the service.

* `get_transactions()` — the service's own ledger, validated against the expected row shape.
* `create_transaction({tx_type, batch_id, payload})` — one POST, with the configured timeout.
* `probe()` — reachability and latency for the health endpoint.

It provides structured logging on every call (`honey chain.blockchain: blockchain request |
method=POST url=… http_status=200 duration_ms=…`), turns HTTP errors and connection failures into
**answers rather than exceptions** (so a chain outage can never roll back a harvest), validates the
`tx_id` it gets back, and retries within the configured budget. Nothing else in the backend, and
nothing at all in the frontend, builds a blockchain URL or calls it.

---

## 5. The event catalogue

Nineteen types, each recorded at the moment the transition happens — from inside the same database
transaction as the record, immediately before the service's pre-existing `commit()`:

| Event | Recorded when | Recorded by |
| --- | --- | --- |
| `COLLECTION_COMPLETED` | a harvest is completed and the batch is created | beekeeper |
| `BATCH_CREATED` | the batch row exists (`HC-BATCH-YYYY-NNNNNN`) | beekeeper (via collection completion) |
| `PROCESSING_STARTED` / `PROCESSING_COMPLETED` | a processing run starts / completes | processor |
| `LAB_TEST_STARTED` | a laboratory test is created for a sample | laboratory |
| `QUALITY_CHECKED` | the test completes with a PASS | laboratory |
| `QUALITY_FAILED` | the test completes as a failure | laboratory |
| `QUALITY_HOLD` | the test completes as a hold (measurement out of range, awaiting a decision) | laboratory |
| `PROCEEDED_WITH_RISK` | a **hold** is explicitly released. Only possible when `LAB_ALLOW_RISK_OVERRIDE` is enabled, only through the audited `proceed-with-risk` endpoint, and the original `QUALITY_HOLD`/`QUALITY_FAILED` event is never edited or replaced — the override is an additional event beside it | laboratory (with override enabled) |
| `PACKAGING_STARTED` | a packaging run starts | packaging unit |
| `PACKAGE_CREATED` | each individual package row is created (stable package ids) | packaging unit |
| `PACKAGED` | the run completes, with the packaged quantity | packaging unit |
| `DISTRIBUTION_CREATED` | a shipment is raised against released packages | distributor |
| `DISTRIBUTION_DISPATCHED` / `IN_TRANSIT` / `DELIVERED` | the shipment reaches each state | distributor |
| `RETAILER_RECEIVED` | the retailer confirms receipt | retailer |
| `QR_GENERATED` | a package's QR identity is issued (once; re-issuing writes nothing) | packaging unit |
| `CUSTOMER_QR_VERIFIED` | the customer page is opened for a package that has never been scanned — **once per package**, not once per refresh (further opens increment `qr_scan_count`) | nobody; it is a customer's scan |

Payloads carry the real values the records hold — identifiers, statuses, quantities and units, actor
role, cluster, beekeeper, hives, location, the moment — and carry **nothing else**: no passwords, no
tokens, no notes, no lab detail, no AI input or output, no images or documents, no telemetry series,
no internal ids that are not already in the payload's own vocabulary. The detailed measurements,
notes and documents stay in HoneyChain, where the batch screen reads them.

---

## 6. Persistence

One table, `blockchain_events` (migration `20260929_1800_9b1f4c2d7e05_phase_8_blockchain_traceability.py`),
documented in full in `docs/database.md` §7:

* `event_id` (unique — the idempotency key), `tx_type`, `status`, `tx_id`, `payload` (JSONB),
  `attempt_count`, `last_error`, `submitted_at`, `confirmed_at`;
* **nine foreign keys** — `batch_id`, `collection_id`, `processing_id`, `lab_test_id`,
  `packaging_id`, `package_id`, `distribution_id`, `cluster_id`, `actor_id` — every one of them
  pointing at the operational row the workflow already wrote. There is no `BlockchainBatch`,
  `BlockchainPackage`, `BlockchainDistribution` or copied record anywhere: the transactions describe
  the same rows the rest of the platform reads, and `batch_code` is denormalised only so a ledger
  row survives as history if a batch is removed.

---

## 7. Idempotency, failure and the outbox

* **Deterministic event ids.** `COLLECTION-HC-COL-2026-000013-COMPLETED`,
  `DIST-HC-DIST-2026-000004-DELIVERED`, `PACKAGE-HC-PKG-2026-000001-CREATED`, and content-derived
  ids where a record is one of many. The unique constraint is the guarantee, not a convention: a
  double click, a refresh, a retried API call, a network timeout, a backend restart or a second tab
  produces one row and one transaction.
* **A confirmed transaction is reused, never re-posted.** Submission checks the event's own row
  first; if it is already `CONFIRMED` with a `tx_id`, that id is returned.
* **Statuses are the truth.** `PENDING` → `SUBMITTED` → `CONFIRMED`, with `FAILED` (refused, or the
  service could not be reached — the service's own words are kept in `last_error`) and `SKIPPED`
  (the integration is switched off). Nothing is ever marked confirmed by HoneyChain's own decision.
* **The outbox is the database.** No Kafka, no Redis, no second service: a bounded sweep of
  `PENDING`/`FAILED` rows by the worker (`worker.py`, started in the application lifespan), or by an
  administrator pressing **Sync now**, or from the command line
  (`python scripts/blocksync.py status|pending|failed|sync|retry <event_id>`).
* **Failure never rolls back the business action.** The harvest is complete, the batch exists, the
  packages are packed — the event waits. Retrying is a first-class operation: `POST
  /blockchain/transactions/{event_id}/retry`, audited.
* **No screen claims more than the chain returned.** The UI shows "on the chain" only for
  `CONFIRMED` events with a transaction id; a batch summary reports `synchronized` only when every
  event is confirmed, and counts `skipped` separately with the reason attached.

---

## 8. What each role sees and does (§ roles)

| Role | Acts on | Reads |
| --- | --- | --- |
| BEEKEEPER | collection, and therefore the batch | their own batches' events inside the batch screen (event id, chain status, transaction id) |
| PROCESSOR | processing runs | the batch they are working (no ledger) |
| LAB TECHNICIAN | tests and their decision | the test and its batch |
| PACKAGING UNIT | packaging runs, packages, QR label | the packages of their runs, the QR label with its scan count |
| DISTRIBUTOR | shipments and their progression | the shipments they raised |
| RETAILER | receipt | the shipments addressed to them |
| CONSUMER | nothing | `/trace/{code}` and `/verify/{qr_id}` need no account at all; the signed-in consumer's workspace (`/consumer`) verifies a code through the same endpoint and is a read — a QR cannot be created, a package cannot be changed, a transaction cannot be written |
| KVIC OFFICER | nothing | the ledger, scoped to the clusters they are responsible for, and a batch's traceability |
| ADMIN | sync and retry | the whole ledger, the service's raw ledger, health |

The screens, all in the existing design system: **Administrator ledger** (`/admin/blockchain`) over
the real `GET /transactions` with search by event/batch/package, filters by type, status and date,
a chronological detail panel and a retry control for failed events; the same page in the **KVIC
workspace** (`/kvic/blockchain`) scoped server-side, with no sync control; a read-only **Blockchain
traceability** section on the batch screen; the **QR label** on the package screen; the **customer
page** (rendered by the same `TraceReport` the consumer's workspace uses, so the two can never
disagree); the **consumer workspace** at `/consumer`, where a code from a label — or a whole pasted
link — is verified; and the **health card** on both dashboards (connected / latency / pending /
failed / last successful confirmation — measured, not estimated).

---

## 9. Verification

Everything below was run against the running system — the API on PostgreSQL 17 and the browser build
served at `:4173` — not against a mock. The only stub in the repository is `tests/blockchain_stub.py`,
which exists solely so the unit suite can run without publishing transactions and is never used by
the application.

| Run | Result |
| --- | --- |
| `tests/test_blockchain.py` (unit + API, stub) | **22 passed, 0 failed** |
| `tests/phase8_blockchain_workflow.py` — the full journey against the **real** service | **46 passed, 0 failed** (exit 0) |
| `tests/phase8_ui_checks.py` — every Phase 8 screen in a real browser | **27 passed, 0 failed** |
| `tests/browser_master_workflow.py` — the whole platform walked as 13 roles, console errors included | **87 passed, 0 failed** (exit 0) |
| Full backend suite (`pytest tests/test_*.py`) | **928 passed, 0 failed** (`EXIT=0`) |
| `tests/browser_input_focus.py` — the input-bug regression suite (§64) re-run after the Phase 8 build | **28 passed, 0 failed** |

Bugs found by these runs and fixed in the course of the phase:

* a **403 on `GET /blockchain/health`** for a KVIC officer (the endpoint was guarded by the *sync*
  permission although it is a read) — found by the console-error check in the master workflow, fixed
  by moving the guard to `BLOCKCHAIN_READ`, and the service URL was removed from the response in the
  same change;
* a batch summary could report itself **synchronised while its events were `SKIPPED`** (integration
  switched off) — the chain summary now distinguishes confirmed / pending / failed / skipped and
  states the reason;
* a UI check that assumed a batch's events were on the ledger's **first page** — replaced by a search
  of the register, which is what an officer actually does (and now covers the search control itself);
* one stale unit expectation found by the full backend suite: `test_health.py` still asserted that
  the blockchain component reports `not_configured` (the pre-Phase-8 placeholder). It now asserts the
  real state — `disabled` when the integration is switched off — and that the unauthenticated report
  carries counters rather than the service address. A second test was added in the same pass so the
  *enabled* case is covered too: `/health/detailed` must report the outbox's own numbers and must not
  contain the service URL.

---

## 10. The definition of done, met (§ DoD)

One API journey, in order, against the real service — the log is `tests/phase8_blockchain_workflow.py`
output:

1. **Harvest → 2. processing → 3. laboratory → 4. packaging → 5. shipment → 6. dispatch, in-transit,
delivered → 7. retailer receipt → 8. QR issued → 9. customer page opened (twice).**

* The service held **427 transactions** before the run. The journey's events left HoneyChain in two
  bounded sweeps and every one of them was confirmed by the service, with a transaction id that is
  present in the service's own ledger; the ledger grew by exactly the events the run recorded.
* Outbox sweeps: `{"submitted": 25, "confirmed": 25, "failed": 0, "skipped": 0, "outstanding": 15}`
  then `{"submitted": 15, "confirmed": 15, "failed": 0, "skipped": 0, "outstanding": 0}` — nothing
  left owed to the chain.
* The customer page shows the journey and the ledger of that package, twice in a row, and records
  **one** `CUSTOMER_QR_VERIFIED` event for the package rather than one per page open; re-issuing the
  label returns the same `qr_id` and the same payload and writes nothing.
* No payload carried private data; no event was recorded twice; no event was left un-submitted.
* The screens were then checked independently in a browser: the administrator's ledger (search,
  filters, rows, sync control), the KVIC officer's scoped ledger without the sync control, the batch
  screen's blockchain section with the real event ids, the packing unit's QR label and its scan
  count, and the public page — which names the package, states the QR id, and never shows an account
  address.
* At the end of the phase the workspace holds **279 recorded events, all `CONFIRMED` with a
  transaction id, none pending, failed or skipped**; the service holds **492 transactions** — 279
  marked as HoneyChain's own, and 213 that predate this work, still present, still marked
  `honey_chain_recorded: false`, with no `matched_event_id` and no attachment to any batch.

---

## 11. What was deliberately not done

* **No second blockchain.** The service at `BLOCKCHAIN_BASE_URL` is the only chain HoneyChain talks
  to; there is no mock, no simulator and no demo mode in the application.
* **No second copy of the data.** One table with foreign keys to the rows that already existed; the
  payloads are summaries, not a database dump.
* **No legacy migration.** The service's pre-existing transactions were neither modified, nor
  re-anchored, nor attached to batches. They are visible in the administrator's raw ledger, marked
  `honey_chain_recorded: false`, and appear in no customer's traceability. The twenty-one rows
  naming `HC-BATCH-2026-000037` — written before this project recorded anything — are the worked
  example: every one of them reports `honey_chain_recorded: false`, `matched_event_id: null`, and no
  batch in HoneyChain claims them.
* **No QR database.** A QR code is a link to a package's page; the page is resolved server-side from
  the package record. There is no separate QR table to drift from the package, and the frontend needs
  no QR library — the label is drawn by the server as SVG from the stored payload.
* **No IoT, AI or laboratory detail on the chain.** The weight series, the AI advisory output, the
  measurement notes and the uploaded documents stay in HoneyChain; only the summary of the step is
  written.
* **No auto-selection hidden behind the promise of autonomy.** `PROCEEDED_WITH_RISK` remains behind
  an explicit, configurable, audited override — and never erases the decision it overrides.

Known limits, stated rather than hidden: the service identifies a batch by its **batch code** string
(`HC-BATCH-2026-000005`), so `batch_id` in a transaction is that code, not the database UUID; the
administrator's raw ledger reads one page of the service's ledger at a time; and the health card
reflects the last measured state, refreshed on demand rather than streamed.

---

## 12. Where the code lives

**Backend** — new: `app/services/blockchain/{client,events,qr,service,worker,__init__}.py`,
`app/models/blockchain.py`, `app/schemas/blockchain.py`, `app/routes/blockchain.py`,
`app/routes/trace.py`, `scripts/blocksync.py`, migration
`20260929_1800_9b1f4c2d7e05_phase_8_blockchain_traceability.py`. Changed: `core/config.py`,
`core/permissions.py`, `core/logging.py`, `api/router.py`, `main.py` (worker lifespan),
`models/enums.py`, `models/honey_batch.py`, `models/processing.py`, `routes/health.py`,
`services/{collection,processing,laboratory,packaging,distribution}_service.py`,
`services/admin_service.py`.

**Frontend** — new: `services/blockchainService.js`, `constants/blockchain.js`,
`pages/blockchain/BlockchainLedgerPage.jsx`, `pages/public/TracePage.jsx`,
`components/blockchain/{BatchBlockchainSection,BlockchainHealthCard,PackageQrLabel}.jsx`. Changed:
`routes/AppRoutes.jsx`, `constants/navigation.js`, `constants/api.js`, the sidebar, the batch detail
view, the package screen and both dashboards.

**Tests and documents** — `tests/blockchain_stub.py`, `tests/test_blockchain.py`,
`tests/phase8_blockchain_workflow.py`, `tests/phase8_ui_checks.py`; `docs/phase-8-report.md` (this
file), `docs/api.md` §12, `docs/database.md` §7, `docs/development-roadmap.md`.

**Reproduce it**

```bash
cd backend
.venv/bin/python -m pytest tests/test_blockchain.py -q            # the unit/API suite (stub)
.venv/bin/python tests/phase8_blockchain_workflow.py              # the real-service journey
.venv/bin/python tests/phase8_ui_checks.py                        # the screens
.venv/bin/python tests/browser_master_workflow.py                 # the whole platform
.venv/bin/python scripts/blocksync.py status                      # what the outbox is owed
```
