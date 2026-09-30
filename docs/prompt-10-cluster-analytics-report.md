# Prompt 10 — KVIC cluster management and cluster analytics

**Scope implemented:** clusters associated to **existing honey batches/collections**, managed by KVIC
officers and administrators, with per-cluster analytics counted from the stored rows.
**What was deliberately not built:** an "Add Hives to Cluster" workflow. Hives are never the primary
selection; the chain is `cluster → honey batch → collection → beekeeper → hive`, and the hive side
follows the beekeeper.

Everything below was verified against the running platform with the real development records
(`honeychain_dev`: one cluster `KVIC-GNT-001`, six batches `HC-BATCH-2026-000001…000006`, their
collections, laboratory tests, packaging runs, 90 packages and 6 shipments). No test-only records are
left behind.

---

## 1. What already existed, and what this prompt added

| Area | Before | Now |
| --- | --- | --- |
| Cluster registry | `KvicCluster` model, `ClusterService`, `/api/v1/clusters` CRUD + status + members | unchanged — **no second cluster model, no second table** |
| Cluster → batch | `honey_batches.cluster_id` existed, set only sideways (hive/cluster worklists, backfill on membership) | the **cluster screens write it directly**: pick real batches on the cluster form, see them on the cluster page, remove them again |
| Cluster analytics | members, hives, devices, telemetry, AI | plus **batches, harvests, beekeepers represented, hives behind them, quantity collected/packaged, packages, laboratory approved/rejected/hold, and the collection→processing→laboratory→packaging→distribution→delivered breakdown** |
| Register list | member count | member count **and real batch count**, both single aggregate queries |
| Hive selection on clusters | none | still none — verified in the browser run |

The relationship is one column. Placing a batch in a cluster updates that batch's own `cluster_id`
(and its harvest's, which mirrors it); it does not insert a row anywhere, does not touch the batch's
quantity, status, beekeeper or sources, and cannot create a duplicate of a batch, a collection or a
hive.

---

## 2. Backend

### 2.1 Endpoints (all under `/api/v1`)

| Method | Path | Permission | Behaviour |
| --- | --- | --- | --- |
| `POST` | `/clusters` | `CLUSTER_MANAGE` | accepts optional `batch_ids` (+`reassign`) and places them **in the same transaction** — a refused batch means no cluster is created at all |
| `GET` | `/clusters` | `CLUSTER_READ` | each row now carries `batch_count` next to `member_count` (two grouped `COUNT` queries, not one per row) |
| `GET` | `/clusters/{id}/batches` | `CLUSTER_ANALYTICS_READ` | the cluster's batches, paginated, with the downstream stage labels |
| `GET` | `/clusters/{id}/batch-candidates` | `CLUSTER_ANALYTICS_READ` | the *Add batches* picker feed: real batches the caller may read, with `placement` (`unassigned` / `this_cluster` / `other_cluster`), `placement_label` and `requires_confirmation`. `assignment=` filters in the database |
| `POST` | `/clusters/{id}/batches` | `CLUSTER_MANAGE` | `{batch_ids, reassign}` → `{assigned[], moved[], already[], batch_count, reassigned}` |
| `DELETE` | `/clusters/{id}/batches/{batch_id}` | `CLUSTER_MANAGE` | `{detached, batch_count}` |
| `GET` | `/clusters/{id}/batch-analytics` | `CLUSTER_ANALYTICS_READ` | the counters described below |
| `GET` | `/batches?unclustered=true` | batch read scope | batches that name no cluster (used by the picker and the repair worklist) |

### 2.2 Rules the service enforces (not the UI)

* **Reassignment is explicit.** A batch that already belongs to another cluster is refused with
  `409 CONFLICT`, `details.requires_reassign: true` and `details.batches` naming each batch and the
  cluster it currently belongs to. Only `reassign: true` — which the form sends after the officer
  confirms — moves it, and the move is an *update of that batch's own row*.
* **No duplicates.** Ids are de-duplicated before use; a batch already in the target cluster is
  reported as `already`, and a second relationship is never created.
* **Atomicity.** Create-with-batches is one transaction. The refusal above is raised before anything
  is committed, so a failed placement leaves no empty cluster behind (checked in the browser run: the
  name was absent from the registry afterwards).
* **Scope.** Every placement and removal calls `BatchService.assert_can_read(actor, batch)`, and the
  candidate list is scoped by the same rules the batch lists use. An officer cannot place honey they
  cannot read into a cluster they can; a role without `CLUSTER_MANAGE` gets `403` from the API even if
  a button were rendered for them (verified: a beekeeper's `POST` is refused).
* **Inactive clusters** refuse new batches (`422`).
* **Audit.** `CLUSTER_BATCHES_ASSIGNED` (with the moved codes) and `CLUSTER_BATCH_DETACHED` are
  written on every change. The development database shows 8 + 2 such entries from the verification
  runs, all attributable.
* **Detachment is a link only.** Removing a batch clears `cluster_id` on the batch and on its harvest
  *only when the harvest names that same cluster*; nothing else about the batch changes.

### 2.3 Files changed

```
backend/app/repositories/batch_repository.py    for_cluster() (no pagination, for counters),
                                                search(..., unclustered=, not_cluster_id=)
backend/app/services/batch_service.py           batches_for_cluster(), list_batches(unclustered,
                                                not_cluster_id), public assert_can_read()
backend/app/services/cluster_service.py         assign_batches() / detach_batch() and the shared
                                                _place_batches() (commit=False for create),
                                                batch_counts(), create_cluster() places batches
backend/app/services/cluster_analytics_service.py  batch_analytics()
backend/app/schemas/cluster.py                  ClusterBatchCandidate + to_batch_candidate(),
                                                ClusterBatchAssign(Result), ClusterBatchDetachResult,
                                                ClusterBatchTotals/StageBreakdown/BatchAnalytics,
                                                batch_count on ClusterWithCounts, batch_ids/reassign
                                                on ClusterCreate
backend/app/routes/clusters.py                  four new endpoints, batch counts on list/detail/create
backend/app/routes/batches.py                   unclustered query parameter
backend/app/models/enums.py                     CLUSTER_BATCHES_ASSIGNED, CLUSTER_BATCH_DETACHED
backend/app/services/audit_service.py           matching audit helpers
```

### 2.4 Analytics, and where each number comes from

`GET /clusters/{id}/batch-analytics` counts the cluster's **own batch rows** — the same rows its batch
table lists — then reads each batch's stage records:

| Figure | Source |
| --- | --- |
| `totals.batches`, `collections`, `beekeepers_represented`, `hives_behind_them` | the cluster's `honey_batches` rows, their `collection_id`s, `beekeeper_id`s and source-hive codes |
| `totals.quantity_collected` / `quantity_packaged` / `packages` | summed from those batches' `quantity`, packaged quantity and package counts |
| `status_breakdown.collection` | every batch (a batch exists because a harvest completed) |
| `status_breakdown.processing` | the batch's processing record state (`honey_processing_records`) |
| `status_breakdown.laboratory`, `laboratory.{approved,rejected,hold}` | the batch's laboratory tests — `INCONCLUSIVE` is reported as **hold**, which is the word the KVIC screens use |
| `status_breakdown.packaging` / `packaging.*` | the batch's packaging runs and the packages they produced |
| `status_breakdown.distribution` / `delivered`, `distribution.*` | the batch's shipments (`distributions`) and their delivered state |

No cluster-side status record exists, no counter is stored ahead of time, and a cluster with no
batches answers with zeros (a true statement) rather than blanks.

**Honey type is reported as "Not recorded" on purpose.** No harvest, batch or collection column
carries a honey/floral variety anywhere in the schema (checked against `honey_collections`,
`honey_batches`, `honey_collection_hives`). Inventing a value — or silently dropping the column —
would misrepresent the records, so the picker and the batch table show the column with
*Not recorded* and the operator can see that the field simply does not exist yet.

---

## 3. Frontend

| File | Change |
| --- | --- |
| `src/components/clusters/ClusterBatchPicker.jsx` **(new)** | the *Add honey batches* picker: real batches with batch id, collection id, beekeeper, honey type (not recorded), quantity, current status, and the cluster they currently sit in. Search + `assignment` filter, multi-select, and a warning block naming any chosen batch that would have to be **moved** |
| `src/components/clusters/ClusterBatchSection.jsx` **(new)** | *Batches in this Cluster* on the cluster page: counters, stage-breakdown badges, the full batch table (supply-chain, laboratory, packaging, distribution status per row), *Add batches*, per-batch *Remove*, and in-place refresh after every change |
| `src/components/clusters/ClusterFormModal.jsx` | the same picker on create **and** edit. Create sends `batch_ids` (+`reassign`) with the cluster; edit saves the fields first, then applies additions/removals one by one, reporting "saved but batches not applied" separately from "not saved" |
| `src/components/clusters/ClusterView.jsx` | renders the batch section right after the cluster's own card, and states that the batch link is the one thing this screen writes |
| `src/components/clusters/ClusterManagement.jsx` | real *Batches* column and page total; the "created" receipt names how many batches were placed |
| `src/pages/kvic/KvicClusterAnalyticsPage.jsx` | rewritten around `/batch-analytics`: per-cluster batches, harvests, beekeepers represented, collected/packaged quantities, packages, laboratory outcomes and the stage breakdown, plus scope totals. A cluster whose figures cannot be read is shown as **unavailable** and named in a warning — never as zero |
| `src/constants/api.js`, `src/services/clusterService.js`, `src/services/batchService.js` | the four new calls; `unclustered` on the batch list |
| `src/pages/kvic/KvicClusterDetailPage.jsx` | wording aligned with what the screen now does (batches are placed here; other records are corrected where they live) |

Nothing was changed in the beekeeper, hive, IoT, AI, collection, batch, processing, laboratory,
packaging, distribution, retailer, consumer-QR or blockchain modules beyond the read paths those
screens already used.

---

## 4. Verification

### 4.1 Real-data browser run — `backend/tests/prompt10_cluster_batches.py` → **24 passed / 0 failed**

The script drives the real UI (`http://localhost:4173`, API `:8000`, development database) and prints
screenshots into `docs/screenshots/prompt10/`. It restores the records it moves and removes the
cluster it creates, so it is repeatable.

```
=== The cluster register
  PASS  the register shows the existing cluster with a real batch count
=== Create a cluster and select a real batch on the same form
  PASS  the create form offers real batches to place (not hives)
  PASS  the picker lists the batch's own collection, beekeeper and quantity
  PASS  a batch already in another cluster is flagged on its row, before it is chosen
  PASS  selecting it names the cluster it currently belongs to
  PASS  and the form says the move will be confirmed before it is written
  PASS  the move is refused until it is confirmed
  PASS  the cluster appears in the register immediately, with its batch count
  PASS  the new cluster stores the batch on the batch's own record
  PASS  the batch itself now names the new cluster (same row, not a copy)
  PASS  the previous cluster no longer lists it
=== Open the cluster: Batches in this Cluster
  PASS  the cluster page lists the batch with its harvest and beekeeper
  PASS  the batch row carries its supply-chain, laboratory, packaging and distribution status
  PASS  the counters above the table are counted from that row
  PASS  there is no hive-selection workflow on the cluster screens
=== Cluster analytics from the same rows
  PASS  the new cluster has an analytics row with its real figures
  PASS  the row reports one batch, one harvest and one beekeeper
  PASS  the row carries the laboratory and stage breakdown counters
=== Refresh, and a fresh sign-in
  PASS  the analytics survive a hard refresh
  PASS  the cluster page survives a reload
  PASS  signing out and back in shows the same stored cluster and batch
=== Removing a batch, and putting the record back
  PASS  removing the batch updates the count without a hard refresh
  PASS  the batch itself still exists, with no cluster assigned
  PASS  the batch is placed back in its original cluster through the UI
cleanup: removed KVIC-GNT-005 — 200
24 passed, 0 failed
```

Screenshots: `01-cluster-register`, `02-create-form-batch-selected`, `03-move-confirmation`,
`04-register-with-new-cluster`, `05-cluster-detail-batches`, `06-cluster-analytics`,
`07-after-new-sign-in`, `08-batch-removed`, `09-restored`.

### 4.2 API-level checks on the same database

* Create with a batch that belongs to another cluster → `409 CONFLICT`,
  `details.requires_reassign: true`, the message naming both the batch and `KVIC-GNT-001`; a registry
  search for the attempted name returned **0 rows** — nothing half-written.
* Same request with `reassign: true` → cluster created holding the batch (`batch_count: 1`);
  `GET /batches/{id}` (read as administrator) reported the new `cluster_code`, and the previous
  cluster's analytics dropped from 6 to 5 while the new cluster's read: 1 batch, 1 harvest, 1 beekeeper
  represented, 1 hive behind them, 13.7 kg collected, 12.5 kg packaged in 25 packages, all six stages
  reached, laboratory `1 approved / 0 rejected / 0 hold`.
* `DELETE /clusters/{id}/batches/{batch_id}` → `detached … batch_count: 0`; the batch row then reported
  `cluster_id: null`, and re-placing it restored the original cluster to 6 batches.
* A **beekeeper** token calling `POST /clusters/{id}/batches` (`PERMISSION_DENIED`) and
  `GET /clusters/{id}/batch-candidates` was refused by the API — the check is the permission, not the
  button.

### 4.3 Regression suites

| Check | Result |
| --- | --- |
| `pytest` (full backend suite) | **928 passed**, 1 warning (0 failures) — same as before the change |
| `pytest tests/test_clusters.py tests/test_cluster_relationships.py tests/test_honey_batches.py tests/test_batch_assignment.py tests/test_authorization.py tests/test_permissions_matrix.py` | 183 passed |
| `npx vitest run` (frontend) | 3 files, **34 passed** |
| `npx eslint src/` | clean |
| `npx vite build` | built (bundle served by the preview on `:4173`) |

### 4.4 Data integrity after the run (development database)

```
clusters:                1   (KVIC-GNT-001 — every verification cluster was removed,
                              all of them through the audited delete endpoint)
batches:                 6   (all in KVIC-GNT-001, 0 unclustered)
collections:             6   (all in KVIC-GNT-001)
packages:               90    distributions: 6
audit:   CLUSTER_BATCHES_ASSIGNED ×14, CLUSTER_BATCH_DETACHED ×4
         (every placement, move and removal of the verification runs)
```

No batch, collection, package or shipment was duplicated, and the batch↔cluster links that existed
before the work are exactly the ones that exist now.

---

## 5. Notes and known limits

* **Honey type** has no column in the schema; the screens say *Not recorded*. Adding it would be a
  change to the collection/batch model — out of scope here (Prompt 10 §11) and, if wanted, a separate
  decision.
* **The picker is presented to roles that hold `CLUSTER_MANAGE`** (KVIC officers, administrators);
  every write is refused by the API for anyone else regardless of what a screen renders.
* **Batch lists inside the cluster view are paged** (10 rows per page) while the counters are
  unpaginated by design — the headline counts the whole cluster, the table pages through it. The edit
  form loads the first 100 held batches and says so if a cluster ever holds more.
* Closing a cluster (deactivating) keeps every batch link; only new placements are refused.
