# Prompt 11 — HoneyChain core integration

**Scope:** only the seams between existing modules. No module was rebuilt. The
blockchain service, its outbox, its event payloads and its client are unchanged
apart from the three read/idempotency fixes listed below; no second chain, QR
system, traceability copy, KVIC copy or mock transaction was introduced.

```
KVIC → CLUSTER → BATCH → COLLECTION → BEEKEEPER → HIVE
      BATCH → PROCESSING → LABORATORY → PACKAGING → PACKAGE
            → DISTRIBUTION → RETAILER → QR → CUSTOMER → BLOCKCHAIN TRACEABILITY
```

---

## 1. One traceability service

`backend/app/services/traceability_service.py` is now the single reader of the
supply-chain records behind every trace. It takes a batch (optionally one package
of it) and returns the real rows: cluster, batch, collection, beekeeper, source
hives, processing runs, laboratory tests, packaging runs, packages, shipments,
retailer receipts and blockchain events.

| Consumer | Before | Now |
| --- | --- | --- |
| `GET /blockchain/batches/{id}` | its own queries; timeline built from `packages[0]` and the *last* packaging run | reads `TraceabilityService`; adds a `chain` section (every stage's record + a reached/not-reached `stages` list); optional `?package_code=` narrows to one package |
| `GET /trace/{code}` (customer QR) | its own queries | reads `TraceabilityService.for_package` — same rows as the batch view |
| `BlockchainService._processing_runs / _lab_tests / _shipments / events_for_package` | four private queries | delegate to the service |

No new traceability endpoint was added; the existing one was extended.

## 2. Defects fixed

### Cross-role status and data
| Defect | Effect | Fix |
| --- | --- | --- |
| Retailer "Confirm receipt" was hidden once the distributor marked a shipment delivered, and shown for undispatched shipments | the shop could never record receipt of a carrier-delivered shipment; the button it did show was always refused | `ShipmentTable`: receivable = dispatched / in transit / delivered **and not yet received** |
| Batch reached `COMPLETED` on the carrier's delivery | KVIC/beekeeper saw "completed" while the timeline said "awaiting receipt" | `_settle_package_and_batch` also requires every live shipment to carry the retailer's `received_at` |
| Package marked `DELIVERED` when shipments were merely *raised* for all of it | a package split over two shipments read delivered after the first arrived | new `_package_undelivered` counts delivered shipments only |
| Retailer inbound/received/summary treated "delivered" as "received" | counts and lists disagreed with the receipt records | `?awaiting_receipt=true` filter (server-side, paginated correctly); received = `received_at` set |
| A partly-packed batch could not pack its remainder after its first shipment | remainder stuck forever, batch never completed | `DISTRIBUTION` added to the packable statuses; completing a later run no longer pulls the batch back to `PACKAGED` |
| Approved quantity summed cancelled/open processing runs' output | packaging could pack more honey than exists | sum only `COMPLETED` runs |
| Lab retest allowed while a packaging run was open | packages could be created for a batch being re-judged | retest refused (409) naming the open run |
| Repeated receipt overwrote `received_at` | the moment of receipt moved on every click | first receipt is kept |

### Scope and permissions (enforced in the backend)
| Defect | Fix |
| --- | --- |
| `/distribution/summary`, `/packaging/summary` counted the whole platform for every role | counters scoped exactly like the lists (distributor, retailer, beekeeper, facility) |
| Beekeeper package/run/shipment lists filtered **after** pagination (empty pages, wrong totals) | scoped in SQL (`beekeeper_id` filters) |
| Packaging cluster filters used a stale copied `cluster_id` | filter on the batch's own `cluster_id` |
| KVIC officers could read the unscoped raw chain ledger (`/blockchain/ledger`) | administrator only |
| Any package reader (beekeeper, retailer, KVIC) could *issue* a QR and its ledger event | `PACKAGING_WRITE` required; cancelled packages refused |
| Public `qr.svg` minted a QR for a cancelled package | 404 |
| `officer_cluster_ids` read only the first 1000 clusters | reads every id |
| Retailer summary raised 403 via the packaging worklist | handled |

### Blockchain linkage (reads and idempotency only)
| Defect | Fix |
| --- | --- |
| Customer page read events *before* recording the first verification, so the first view's ledger lacked `QR_GENERATED`/`CUSTOMER_QR_VERIFIED` | record first, then read |
| A package's page included packaging events of other runs of the same batch | events narrowed by `packaging_id` too |
| Batch timeline QR/verified steps came from the first package only; shipment steps unlabelled; cancelled shipments listed | aggregated "n of m packages", shipment steps carry `package_code`, cancelled shipments omitted |
| A second lab override with the same verdict reused an event id and was silently dropped | override ids carry a sequence |
| Public page published the retailer account holder's personal name | shows the shop (`organization`), falling back to the account name |

### Frontend, error handling and dashboards
| Defect | Fix |
| --- | --- |
| Traceability page showed "Loading batch information…" forever for an unknown/out-of-scope id | error state ("not found, or outside your scope") |
| Consumer report kept the previous package's journey under a new code's error | cleared on failure |
| `Alert variant="error"` (not a variant) rendered failures as neutral info boxes in 6 places | `danger` (role="alert") |
| Registration showed a bare "Invalid request" | cross-field messages are listed; `ApiError` leads with the server's actual reason everywhere; backend accepts `(987) 654-3210` like the form does |
| Batch quality summary showed "Unknown" units/types/status and "NaN" sample quantity | batch detail uses the enum label helper; sample quantity/unit and technician name returned |
| Dashboards: "Packaging & distribution" / "QR & blockchain" marked "Not in this release"; admin modules "planned"; failed reads shown as `0` | live modules marked live and linked; failed reads show "—" |
| Retailer lists shared one page number | independent paging |
| `LoadingState label=…` silently dropped its text in 6 screens | `label` accepted |
| QR label issued without the page re-reading the package | parent refetches |

New: `components/trace/SupplyChainPanel.jsx` on the beekeeper/KVIC traceability
page (with a "View journey" link per batch) renders the `chain` section.

## 3. Verification

| Check | Result |
| --- | --- |
| `tests/prompt11_core_flow.py` — live API, dev database, every role, re-read after each action, sign-out/sign-in of all 9 roles | **41 passed / 0 failed** |
| `pytest tests/test_core_integration.py` (new) | **11 passed** |
| `pytest tests` (full backend suite, PostgreSQL) | 2 failures, both tests that expected a carrier's delivery to complete a batch; updated to the receipt rule and passing (final run: see `prompt-12-final-verification-report.md`) |
| `vitest run` (frontend, incl. new `errors.test.js`) | **37 passed** |
| `eslint src` | 0 errors (7 pre-existing warnings) |
| `vite build` | succeeds |
| Browser: traceability page supply-chain panel, quality summary, unknown-id error | verified |

## 4. Not changed — decisions for the product owner

* **KVIC scope is platform-wide.** There is no officer↔cluster assignment in the
  schema; every KVIC officer reads every cluster (by design since Prompt 10). If
  officers must be limited to named clusters, that needs an assignment table.
* **Packaging units can register and edit units, and work any unit's runs.** The
  docstrings say administrator-only; the permission map and a smoke test rely on
  the current behaviour, so it was left as is.
* **`/trace/{code}` issues a QR on first open** for a package that has none
  (including unreleased packages) and counts every open. Kept: a printed code
  must resolve.
