# HoneyChain — Phase 4.1 delivery report

**Organisational data-relationship correction: `KVIC → Cluster → Beekeeper → Hive → IoT → Telemetry → AI`**

*Smart India Hackathon 2026 · Problem Statement 26021 · Report generated 24 September 2026*

---

## 1. What this phase set out to do

The platform already contained every part of the organisational chain, but the parts were connected
only where they were written. A hive created before its owner joined a cluster stayed outside every
cluster view; a beekeeper moved between clusters left their hives behind; and the KVIC workspace had
no way to read a cluster's telemetry or assessments at all. The risk in fixing that is obvious:
invent a parallel set of "KVIC hives" and "KVIC telemetry", and the platform starts disagreeing with
itself.

Phase 4.1 therefore had one job — **make the existing relationships resolve, consistently and
server-side, without storing a single duplicated record.** Concretely:

| # | Requirement | How it is met |
| - | ----------- | ------------- |
| 1 | One chain, one set of records | Every cluster figure is a query over the beekeeper's own hive rows, the hive's own devices, those devices' readings, and the analyses computed from them |
| 2 | A hive belongs to exactly one cluster | `hives.cluster_id` FK (`ON DELETE SET NULL`), written only by the service layer |
| 3 | Membership decides visibility | A beekeeper's cluster link propagates to the hives they own; a KVIC view is scoped to the cluster's `hive_id` set |
| 4 | Clients cannot dictate the relationship | `cluster_id` is refused in hive and device payloads (`extra="forbid"`); placement is a separate, authorised, audited staff action |
| 5 | An unplaceable hive is surfaced, not guessed | `GET /hives?has_cluster=false` plus a staff-only `without_cluster` count |
| 6 | Nothing rebuilt, nothing removed | Phase 1–4 modules, endpoints, tests and screens are untouched; the suite that proved them still passes |

**Scope discipline.** This was a correction and integration pass. No collection centre, processing,
laboratory, packaging, QR or blockchain module was started; no table was redesigned; no screen was
rewritten. Where a rule already existed it was reused (`HiveRepository`, `AiService`,
`IotMonitoringService`, `ClusterService`), and where a rule was missing it was added to the layer
that already owned it.

---

## 2. The relationship, as the database and the code define it

```
KVIC  (organisation)
  └── kvic_clusters            kvic_clusters.id
        └── beekeepers         beekeepers.kvic_cluster_id  → FK, ON DELETE SET NULL, indexed
              └── hives        hives.beekeeper_id, hives.cluster_id → FK, indexed (ix_hives_cluster_status)
                    └── iot_devices        iot_devices.hive_id → FK, indexed (hive_id, status)
                          └── sensor_readings   sensor_readings.hive_id / device_id / beekeeper_id, indexed (hive_id, timestamp)
                                └── hive_ai_analyses  hive_ai_analyses.hive_id → the assessment computed from those readings
```

Four properties make this a relationship rather than a set of loose columns:

1. **It is the only path.** Nothing stores a "cluster hive" or a "cluster reading". A cluster's hives
   are `hives WHERE cluster_id = :id`; its devices are the devices of those hives; its telemetry is
   their readings; its AI state is their analyses.
2. **It resolves in the database.** The screens never join data by hand: the repositories filter on
   `hive_ids` derived from the relationship (`HiveRepository.ids_for_cluster`,
   `device`/`reading` repositories with `hive_ids=`, `AiService.summary_for_hive_ids`,
   `IotMonitoringService.summary_for_hive_ids`).
3. **It moves as a unit.** Assigning a beekeeper to a cluster propagates to every hive still
   following them (`ClusterService.assign_beekeeper` → `HiveRepository.set_cluster_for_beekeeper`
   with a `previous_cluster_id` comparison), so a hive deliberately placed elsewhere is left alone.
4. **It is never inferred.** A beekeeper with no cluster produces no cluster membership, and their
   hives stay `cluster_id IS NULL` — listed for an officer to resolve rather than attached to
   something plausible.

---

## 3. Database work

**No new tables, no new columns.** The schema added in Phases 2–3 was already correct; what was
missing was history.

| Item | Detail |
| ---- | ------ |
| Migration | `alembic/versions/20260924_1010_5e2b7d41c8aa_phase_4_1_cluster_relationship_backfill.py` |
| Revision chain | `a77f6c38aaff` (Phase 4) → **`5e2b7d41c8aa` (head)** |
| What it does | One statement: `UPDATE hives SET cluster_id = beekeepers.kvic_cluster_id … WHERE hives.cluster_id IS NULL AND beekeepers.kvic_cluster_id IS NOT NULL` |
| What it refuses to do | It never invents a cluster (an owner with no cluster leaves the hive `NULL`) and never overwrites a placement (only `NULL` rows are touched) |
| Downgrade | Deliberately a no-op: the backfilled values *are* the relationship, and clearing them would hide hives from the cluster that owns them |
| Verified | `alembic upgrade head` → `alembic current` → `downgrade -1` → `upgrade head` round trip, clean |

Indexes supporting the relationship were already present and are unchanged:
`hives(beekeeper_id, status)`, `hives(cluster_id, status)`, `iot_devices(hive_id, status)`,
`sensor_readings(hive_id, timestamp)`, `beekeepers(kvic_cluster_id, verification_status)`.

---

## 4. Backend changes

### 4.1 Services

| File | Change |
| ---- | ------ |
| `app/services/hive_service.py` | New `change_cluster(user, hive_id, *, cluster_id, reason)` — staff-only placement/clearing with validation (unknown cluster → 404, inactive cluster → 422, duplicate → 422, clearing an unclustered hive → 422) and an audit trail carrying old and new cluster. `list_hives`/`list_items` gained `has_cluster`; `summary()` gained the staff-only `without_cluster` count |
| `app/services/cluster_service.py` | `assign_beekeeper` / `remove_beekeeper` now propagate the membership to the beekeeper's hives (only those still following the owner) and record the relationship event |
| `app/services/cluster_analytics_service.py` **(new)** | The cluster **view**: `overview`, `list_hives`, `list_devices`, `ai_state`, `latest_telemetry`, plus `hive_ids`, `beekeeper_ids`, `get_cluster`. It composes existing services and repositories; it owns no table |
| `app/services/ai_service.py`, `ai_alert_service.py` | `summary_for_hive_ids(...)` — the same aggregation the beekeeper sees, narrowed to a cluster's hives |
| `app/services/iot_monitoring_service.py` | `summary_for_hive_ids(hive_ids, *, window_hours=24)` for the cluster's device/telemetry counters |
| `app/services/audit_service.py` | Helpers `cluster_member_assigned`, `cluster_relationship_updated`, `hive_cluster_changed` |

### 4.2 Repositories

`HiveRepository`: `set_cluster_for_beekeeper(beekeeper_id, cluster_id, previous_cluster_id=)`,
`ids_for_cluster(...)`, `list_for_cluster(...)`, `count_without_cluster(...)`.
`IotDeviceRepository` and `SensorReadingRepository`: `hive_ids=` filters.
Nothing else was duplicated — the cluster view calls the same query functions the beekeeper screens use.

### 4.3 Authorisation

A single new capability, `Permission.CLUSTER_ANALYTICS_READ` (ADMIN + KVIC_OFFICER), applied through
the existing `require_permission` dependency. No role checks were scattered into handlers, and no
beekeeper-facing endpoint widened: a beekeeper still reaches only their own hive, device, telemetry
and analysis records. `POST /hives/{id}/cluster` requires staff and is refused for a beekeeper inside
the service as well as at the route.

### 4.4 Audit vocabulary

Four relationship events, plus the legacy names kept as aliases so rows written before this phase
stay filterable: `BEEKEEPER_ASSIGNED_TO_CLUSTER`, `BEEKEEPER_REMOVED_FROM_CLUSTER`,
`HIVE_ASSOCIATED_WITH_CLUSTER`, `CLUSTER_RELATIONSHIP_UPDATED` (legacy `CLUSTER_MEMBER_ASSIGNED` /
`CLUSTER_MEMBER_REMOVED`). Each placement records the previous and new cluster and the reason.

---

## 5. API surface added

| Method | Path | Permission | Purpose |
| ------ | ---- | ---------- | ------- |
| `GET` | `/api/v1/clusters/{id}/summary` | `CLUSTER_ANALYTICS_READ` | Members, hives, devices, telemetry and AI counters for the cluster |
| `GET` | `/api/v1/clusters/{id}/hives` | `CLUSTER_ANALYTICS_READ` | The cluster's hives, paginated (`HiveListItem` rows) |
| `GET` | `/api/v1/clusters/{id}/devices` | `CLUSTER_ANALYTICS_READ` | Devices attached to those hives, paginated |
| `GET` | `/api/v1/clusters/{id}/ai` | `CLUSTER_ANALYTICS_READ` | Latest stored assessment per hive, with source and sample count |
| `GET` | `/api/v1/clusters/{id}/telemetry/latest` | `CLUSTER_ANALYTICS_READ` | Newest stored reading and the chain that produced it; `has_data:false` when nothing is stored |
| `GET` | `/api/v1/hives?has_cluster=` | hive read scope | `false` = hives whose owner is in no cluster (staff worklist) |
| `POST` | `/api/v1/hives/{id}/cluster` | staff only | Place or clear one hive: `HiveClusterUpdate{cluster_id: uuid\|null, reason ≤ 200}` |

Response shapes follow the platform contract (`{success, data}` / `{success, error{code,message}}`)
and are declared in `app/schemas/cluster_analytics.py`. Attempts by a beekeeper to read any of the
five cluster views answer `403`; an unknown cluster answers `404`.

---

## 6. What a cluster view does **not** do

Stated plainly, because the temptation is to add them:

* it does not copy a hive, a device, a reading or an analysis into cluster-owned records;
* it does not run an analysis — assessments are computed from readings by the existing Phase-4
  engine, triggered by the hive's owner or an explicit staff action;
* it does not aggregate across clusters or infer a cluster from district/state text;
* it does not fill in numbers it cannot query — an empty cluster reports zeroes and a hive with no
  reading reports `has_data: false`;
* it does not let a client place a hive: `cluster_id` in a hive or device payload is rejected `422`.

---

## 7. Frontend

The KVIC view is a **view**, built from the same primitives as the rest of the application:

| Artifact | Purpose |
| -------- | ------- |
| `src/services/clusterAnalyticsService.js` | The five read-through calls, documented as reads of existing records |
| `src/components/clusters/ClusterView.jsx` | The cluster screen: identity, membership and verification summary, composed panels |
| `ClusterOverviewCards.jsx` | Beekeepers, hives, devices, readings (24 h), reporting hives |
| `ClusterHivesTable.jsx` | The cluster's hives, paginated, row → the hive's own screen |
| `ClusterDevicesTable.jsx` | Devices resolved through their hive, with derived status |
| `ClusterAiPanel.jsx` | Stored assessments with health, disease/swarming risk, projection and source labels |
| `ClusterTelemetryPanel.jsx` | The latest packet with the full chain (`device → hive → beekeeper`) and an honest empty state |
| `HiveClusterControl.jsx` | **Staff-only** placement control, with the "assign the beekeeper instead" guidance and a reason field |
| `src/pages/kvic/KvicClusterDetailPage.jsx`, `src/pages/admin/AdminClusterDetailPage.jsx` | Thin role wrappers; routes `/kvic/clusters/:clusterId` and `/admin/clusters/:clusterId` |
| `ClusterManagement.jsx` | Cluster name and a **View** action now open the cluster view |
| `HiveRegistry.jsx` | Oversight-only filter *Any / In a cluster / Not in a cluster (worklist)* with an explanatory alert |
| `HiveDetailPage.jsx` | Read-only cluster for every role; the placement panel renders for KVIC and admin only |

Beekeeper-side honesty is unchanged: the hive screen shows `Cluster` as read-only information
("Not in a cluster" where that is the truth) and offers no organisational action. eslint reports
**0 errors / 0 warnings**; `npm run build` exits 0.

**A defect the browser pass caught.** Both new list components could leave the table in its loading
skeleton forever when a request resolved — the empty state never replaced it, so an empty cluster
looked like a page stuck mid-load. The browser smoke failed that check, the missing state transition
was added in both components, and the scenario now passes. It is recorded here because a skeleton
that never resolves is exactly the class of dishonesty this project is meant to avoid.

---

## 8. Verification evidence

| Suite | Command | Result |
| ----- | ------- | ------ |
| Backend tests | `.venv/bin/python -m pytest -q` | **474 passed, 0 failed** (432 before + 42 new; `test_ai_insights` 30, `test_hives` 49, `test_cluster_relationships` **42**) |
| Phase-4.1 API smoke | `.venv/bin/python tests/api_smoke_phase41.py` | **43 passed, 0 failed** |
| Phase-4 API smoke | `tests/api_smoke_phase4.py` | 73 / 0 |
| Phase-3 API smoke | `tests/api_smoke_phase3.py` | 64 / 0 |
| Phase-2 API smoke | `tests/api_smoke_phase2.py` | 43 / 0 |
| Phase-4.1 browser smoke | `.venv/bin/python tests/browser_smoke_phase41.py` | **26 passed, 0 failed**, 0 console errors |
| Phase-3 browser smoke | `tests/browser_smoke_phase3.py` | **111 passed, 0 failed** (110 + 1 check updated: AI Insights/Alerts are live since Phase 4) |
| Frontend | `npx eslint` · `npm run build` | 0 problems · exit 0 |
| Migration | `alembic upgrade head` / `downgrade -1` / `upgrade head` | clean round trip, head `5e2b7d41c8aa` |

The new backend suite (`tests/test_cluster_relationships.py`, 42 tests) covers the cases that matter:
membership is staff-granted and audited; a hive inherits its owner's cluster and follows a
reassignment; `cluster_id` in a payload is refused; a cluster view shows the cluster's hives only; an
update is one row seen by two views; a cluster cannot be read by a beekeeper or a consumer; telemetry
and AI state resolve through the hive; counters reflect the relationship; clearing a placement keeps
the hive; the backfill links existing hives to their owner's cluster and invents nothing; and Phase
2/3 behaviour (cluster registry, hive CRUD, platform summaries) is unchanged.

---

## 9. Acceptance walk (development environment)

1. Sign in as `kvic@honeychain.example.com` → **Clusters** → the Guntur cluster → **View**.
2. The view lists 1 beekeeper (verified), 1 hive, 1 device, the readings received in the last 24 h,
   the latest packet with its chain (`ESP32-GNT-0001 → HIVE-GNT-00001 → BKR-GNT-00001`, labelled
   **Simulator**) and the stored assessment for the hive.
3. Open the hive → **Cluster placement**; clear the placement → the cluster view empties immediately,
   because it is the same row; place it back → the hive reappears.
4. As the beekeeper: the hive screen shows the cluster read-only and offers no placement control; the
   KVIC cluster URL is refused.
5. **Hives** with the filter *Not in a cluster (worklist)* shows the administrative list of hives
   whose owner belongs to no cluster — with an alert explaining that assigning the beekeeper is
   usually the better fix.

---

## 10. Test data and development fixtures

The development database was returned to a clean, demonstrable state after every run:
4 users (`admin`, `kvic`, `beekeeper`, `consumer`), 1 beekeeper (`BKR-GNT-00001`) in cluster
`KVIC-GNT-001`, 1 hive (`HIVE-GNT-00001`) in that cluster, 1 device (`ESP32-GNT-0001`), 24 stored
`SIMULATOR` readings and the analyses computed from them. Every smoke script prints the SQL that
removes what it created, and the phase-4.1 scripts are self-restoring: the browser walk places a hive
back where it found it and reports the state it left behind.

---

## 11. Explicitly not built (and why)

Collection centre intake, processing, laboratory testing, packaging, QR issuance, blockchain
anchoring and public verification remain **Planned** — they are later prompts, and starting them here
would have meant touching the schema and the navigation this phase was asked to leave alone. Also
deliberately absent: cluster-level campaign/scheme reporting (Phase 6), cluster-scoped exports,
cross-cluster analytics, and any health *diagnosis* — the AI layer remains a monitoring aid built
from stored readings, never a clinical claim.

---

## 12. Risks, trade-offs and how they are contained

| Risk | Containment |
| ---- | ----------- |
| A cluster view quietly becoming a second source of truth | The service owns no model and no table; every field is a query through a repository |
| A client placing a hive in an arbitrary cluster | `cluster_id` is refused in payloads; placement is staff-only, validated and audited |
| Historical hives invisible to their cluster | Backfill migration (data-only, idempotent) plus the `has_cluster=false` worklist |
| A hive moved by hand being dragged back by membership propagation | Propagation only moves hives still following the owner (`previous_cluster_id` comparison) |
| Performance on larger clusters | Filters use existing composite indexes; lists are paginated; the AI/telemetry panels are bounded by the cluster's hive set |
| Stale UI after a relationship change | Panels refresh from the API on load and after every write; nothing is cached client-side |

---

## 13. Files changed in this phase

**Backend** — new: `app/services/cluster_analytics_service.py`, `app/schemas/cluster_analytics.py`,
`alembic/versions/20260924_1010_5e2b7d41c8aa_phase_4_1_cluster_relationship_backfill.py`,
`tests/test_cluster_relationships.py`, `tests/api_smoke_phase41.py`, `tests/browser_smoke_phase41.py`.
Edited: `app/services/hive_service.py`, `app/services/cluster_service.py`, `app/services/ai_service.py`,
`app/services/ai_alert_service.py`, `app/services/iot_monitoring_service.py`,
`app/services/audit_service.py`, `app/repositories/hive_repository.py`,
`app/repositories/iot_device_repository.py`, `app/repositories/sensor_reading_repository.py`,
`app/schemas/hive.py`, `app/routes/clusters.py`, `app/routes/hives.py`, `app/core/permissions.py`,
`app/models/enums.py`, `tests/test_audit.py`, `tests/browser_smoke_phase3.py` (one Phase-3
expectation updated because Phase 4 made AI Insights live).

**Frontend** — new: `src/services/clusterAnalyticsService.js`, `src/components/clusters/{ClusterView,
ClusterOverviewCards, ClusterHivesTable, ClusterDevicesTable, ClusterAiPanel, ClusterTelemetryPanel,
HiveClusterControl}.jsx`, `src/pages/kvic/KvicClusterDetailPage.jsx`,
`src/pages/admin/AdminClusterDetailPage.jsx`. Edited: `src/constants/api.js`,
`src/services/hiveService.js`, `src/components/clusters/ClusterManagement.jsx`,
`src/components/hives/HiveRegistry.jsx`, `src/pages/beekeeper/HiveDetailPage.jsx`,
`src/routes/AppRoutes.jsx`, `src/pages/kvic/KvicClustersPage.jsx`,
`src/pages/admin/AdminClustersPage.jsx`.

**Docs** — `docs/phase-4-1-report.md` (this file), `README.md` (Phase 4 / 4.1 sections, test table,
roadmap), `run.md` (verification counts and the Phase 4.1 walk), `docs/architecture.md`,
`docs/api.md`, `docs/database.md`, `docs/development-roadmap.md`.

---

## 14. Where the project stands

Phase 1 (foundation), Phase 2 (users, roles, beekeepers, KVIC clusters, audit), Phase 3 (hive
registry, IoT devices, telemetry ingest, monitoring) and Phase 4 (rule-based hive health insights,
alerts) are delivered and verified. Phase 4.1 corrects and integrates the relationship that ties them
together, so the platform now answers, from a single set of records:

> which beekeepers a KVIC cluster contains → which hives they keep → which devices report on those
> hives → what those devices measured → what the stored readings imply about each hive.

Next in the roadmap: harvest records, batch lineage, quality testing, packaging, QR issuance and
anchoring (Phase 5 territory), followed by KVIC scheme reporting and notifications. The relationship
established here is the spine those modules will attach to — a batch will name a harvest, a harvest
will name a hive, and the hive will already know its beekeeper and their cluster.
