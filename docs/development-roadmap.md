# HoneyChain — Development roadmap

The platform is built in phases. Each phase is independently reviewable, ships working software, and
extends the previous one without restructuring it.

**Current status:** Phases 1–8 are delivered and verified against running software. The traceability
layer is live: every supply-chain transition writes one event to the existing blockchain service,
and the database remains the operational source of truth. Each phase's evidence is in its own
report under `docs/`.

---

## Phase status at a glance

| Phase | Title | Status | Delivers |
| --- | --- | --- | --- |
| **1** | **Platform foundation** | ✅ **Complete** | Auth, ten roles, RBAC, database schema, API foundation, public site, app shell, docs, tests |
| **2** | **Beekeeper & KVIC records** | ✅ **Complete** | User + profile management, beekeeper registry, KVIC clusters, verification workflow, audit trail |
| **3** | **Hive registry & smart-hive IoT foundation** | ✅ **Complete** | Hive registry, device binding, sensor configuration, telemetry ingest (HTTP + MQTT), device health, monitoring dashboards |
| **4** | **AI-powered hive health insights** | ✅ **Complete** | Advisory baseline engine: health indicator, disease/swarming risk, guarded yield projection, recommendations, alert lifecycle, data-quality gating |
| **4.1** | **Organisational data-relationship correction** | ✅ **Complete** | The chain KVIC → cluster → beekeeper → hive → device → telemetry → AI resolves server-side; cluster views, staff placement, backfill, audit |
| **5** | **Honey collections & batches** | ✅ **Complete** | Harvest records against hives, `HC-BATCH-YYYY-NNNNNN` lineage, batch lifecycle and timeline (`docs/phase-5-report.md`) |
| **6** | **Processing & the laboratory** | ✅ **Complete** | Processing facilities and runs, quality parameters, laboratory tests and the PASS / FAIL / HOLD decision, the single batch-lifecycle writer (`docs/phase-6-report.md`) |
| **7** | **Packaging, distribution & retail receipt** | ✅ **Complete** | Packaging units and runs, stable package identities, shipments, dispatch / transit / delivery, the retailer's receipt (covered by the packaging, distribution and browser suites; no separate report) |
| **8** | **Blockchain traceability integration** | ✅ **Complete** | One centralised client for the service that already existed, an event per real state transition, idempotent event ids, a DB-backed outbox with retry, administrator and KVIC ledgers, QR identity, the customer's page, health reporting (`docs/phase-8-report.md`) |

Delivery notes: the phase numbers in this table are the ones the delivered work used. The two plan
sections further down ("Phase 5 — Traceability, packaging & blockchain", "Phase 6 — KVIC analytics &
operations") are the **original plan**, written before delivery: it was executed as Phases 5–8, and
the table above is the record of what actually shipped. Delivered phases have their own verification
records: `docs/phase-2-report.md`, `docs/phase-3-report.md`, `docs/phase-4-1-report.md` (Phase 4 and
the Phase 4.1 correction), `docs/phase-5-report.md`, `docs/phase-6-report.md`,
`docs/phase-6-role-workspaces-report.md`, `docs/role-management-report.md`,
`docs/integration-verification-report.md` and `docs/phase-8-report.md`. Phase 7 has no separate
report; its behaviour is covered by the packaging, distribution and browser suites listed in
`docs/phase-8-report.md` §9. The IoT module has a dedicated reference, `docs/iot.md`.

---

## Phase 1 — Platform foundation ✅

**Delivered**

| Area | What exists |
| --- | --- |
| Architecture | Routes → services → repositories → models; core/config/security/logging/exceptions |
| Authentication | Register, login, refresh (with rotation + replay detection), logout, `/auth/me` |
| Roles | Ten roles in one auth system; RBAC via a central permission catalogue; privileged roles provisioned by an admin |
| Database | PostgreSQL schema for `users` + `refresh_tokens`; Alembic initial migration; UUID keys; audit timestamps |
| API | Versioned `/api/v1`; single success/error envelope; request-id correlation; structured logging with redaction |
| Security | bcrypt hashing, JWT access + HttpOnly refresh cookie, explicit CORS allow-list, production config guard |
| Frontend | React + Vite SPA: public site, register/login, protected dashboard shell, profile, role workspaces |
| Components | Reusable `ui/` primitives and `common/` patterns (DataTable, StatCard, EmptyState, ErrorState, LoadingState, ConfirmDialog, StatusBadge, Modal, Breadcrumb, Toaster, ErrorBoundary) |
| Documentation | README, architecture, API reference, database design, this roadmap |
| Tests | Backend suite across health, auth, authorisation, migrations and logging |

**Exit criteria met**

- `/register`, `/login`, `/dashboard`, `/api/v1/health`, `/api/v1/auth/me` all work.
- Frontend ↔ backend ↔ PostgreSQL verified end to end.
- Protected routes reject unauthenticated users; RBAC rejects wrong roles with `403`.
- Migrations apply and roll back; the migration chain has a single head.

---

## Phase 2 — Beekeeper & KVIC records ✅

**Delivered** — see `docs/phase-2-report.md` for the full record.

| Area | What exists |
| --- | --- |
| Data | `user_profiles`, `beekeepers`, `kvic_clusters`, `beekeeper_verification_history` (append-only), `audit_logs`, `document_sequences` |
| Beekeeper registry | Platform-generated `BKR-<DIST>-NNNNN` codes, apiary address, experience and colony counts, KVIC cluster assignment |
| Verification workflow | `PENDING → UNDER_REVIEW → VERIFIED / REJECTED` with mandatory reasons, history and officer remarks; KVIC officers are restricted to their jurisdiction |
| Profiles | Self-service profile and beekeeper profile editing, with validation shared between frontend and backend |
| KVIC & admin surfaces | Beekeeper directory, verification dialog, cluster management and membership, user administration, audit-log viewer, role-specific dashboards |
| API | `/beekeepers`, `/beekeepers/me`, `/beekeepers/filters`, `/beekeepers/summary`, `/clusters`, `/admin/*` |
| Tests | Ownership and jurisdiction isolation, verification transitions, pagination, audit writes |

**Definition of done met:** a beekeeper can complete their profile and be verified by an officer, and
every KVIC/admin screen reads real data from the database.

---

## Phase 3 — Hive registry & smart-hive IoT foundation ✅

**Delivered** — see `docs/phase-3-report.md` (verification record) and `docs/iot.md` (module reference).

**Goal:** give each beekeeper a real hive registry, and give the platform a telemetry pipeline that
real ESP32 hardware can use later without changing the contract.

| Workstream | Detail |
| --- | --- |
| Data | `hives` (`HIVE-<DIST>-NNNNN`), `iot_devices`, `sensor_configs`, wide `sensor_readings` with a `source` label and a `(device_id, timestamp)` uniqueness guarantee |
| Hive registry | Lifecycle `ACTIVE / INACTIVE / MAINTENANCE / REMOVED`, apiary location, colony strength and queen status as *beekeeper observations*, notes, cluster/beekeeper links |
| Devices | Registration against one of your own hives (seeds five sensor configs), rename/retire, MQTT topic per device, heartbeat, deletion refused while history exists |
| Telemetry | One validation path for HTTP (`POST /iot/telemetry`, batch) and MQTT (`<prefix>/devices/{device_id}/telemetry`); idempotent, range-rejecting (never clamping), source-labelled |
| Device health | Derived `ONLINE / WARNING / OFFLINE` from `last_seen` and battery, sticky `MAINTENANCE`, offline sweep script, `/health/mqtt` consumer status |
| Frontend | My Hives (list, register, edit, status, detail), hive detail with paired devices and stored history, IoT Monitoring (fleet counters, device table, device panel, sensor configuration, trend chart), monitoring blocks on the beekeeper/KVIC/admin dashboards |
| Authorisation | Server-side on every request: cross-owner reads are `404`, cross-owner telemetry is `403`; KVIC and admin have read/write scope, consumers have none |
| Tests | 195 backend tests for the module (registry, devices, telemetry, MQTT), API smoke, and a browser walk including cross-user isolation and empty states |

**Definition of done met:** the simulator → MQTT/HTTP → FastAPI → PostgreSQL → dashboard path is
demonstrable, every reading is labelled with how it was produced, and no screen presents simulated or
absent data as real. Real hardware replaces the simulator by publishing the same payload — see
`docs/iot.md` §8.

**Not delivered in Phase 3** (and not implied anywhere in the UI): disease detection, colony-health
scoring, queen-presence inference, yield prediction, actuator control, blockchain anchoring, QR
traceability, alerts/notifications.

---

## Phase 4 — AI-powered hive health insights ✅

Delivered as an advisory layer over **stored telemetry**, never a clinical claim. The engine
(`app/services/ai/`) is a documented rule-based baseline: a health indicator assembled from published
weighted factors (`clamp(70 + min(Σ positive, 20) + Σ negative, 0, 100)`, capped at 90 by design),
disease and swarming **risk** levels, a yield projection bounded by `YIELD_MAX_DAILY_GAIN`, and
recommendations that fall back to data-quality advice below `AI_MIN_SAMPLES`. Alerts carry a
`dedupe_key` and a cooldown, and move through `OPEN → ACKNOWLEDGED → RESOLVED`. Data quality decides
what may be said: source (`SIMULATOR` / `MANUAL` / `REAL_DEVICE`) is recorded with every assessment
and confidence falls with staleness.

Thirteen `/api/v1/ai/**` endpoints serve it; beekeepers are scoped to their own hives, staff read
platform-wide. Frontend: `HiveAiSection` on the hive screen plus AI Insights and Alerts workspaces
for beekeeper, KVIC and administrator roles.

## Phase 4.1 — Organisational data-relationship correction ✅

The platform held every part of the chain `KVIC → Cluster → Beekeeper → Hive → IoT → Telemetry → AI`
but connected them only where they were written. This phase made the relationships resolve
consistently, server-side, with **no duplicated records and no schema change**: membership
propagation with a `previous_cluster_id` guard, `hive_ids` scoping through the device/reading/AI
repositories, five read-through cluster views under `CLUSTER_ANALYTICS_READ`, a staff-only audited
`POST /hives/{id}/cluster`, the `has_cluster=false` worklist for unassigned hives, and the
`5e2b7d41c8aa` backfill that links historical hives to their owner's cluster without inventing one.

Full write-up, including the verification evidence and the defect the browser pass caught:
[`docs/phase-4-1-report.md`](phase-4-1-report.md).

## Phase 5 — Traceability, packaging & blockchain

**Goal:** the full chain of custody, from harvest to consumer verification.

| Workstream | Detail |
| --- | --- |
| Data | `harvests` (linked to the hives and devices Phase 3 introduced), `honey_batches` (with lineage), `batch_events`, `processing_events`, `quality_tests`, `packaging`, `qr_codes`, `blockchain_transactions`, `distribution`, `retail` |
| API | Harvest entry, batch creation and timeline, event append (stage-scoped), test entry, packaging and QR issuance, public `GET /trace/{qr}`, anchoring and verification |
| Blockchain | *(original plan — see Phase 8 below)* Hash-and-anchor service: canonical payload hashing, transaction submission, confirmation tracking, verification endpoint — abstracted behind an interface so a different chain or a permissioned ledger can be swapped in |
| QR | Batch/lot QR issuance, printable label payload, public verification page requiring no account |
| Frontend | Harvest records, batch timeline, supply-chain event forms, laboratory result entry, packaging screen, consumer verification page, QR display |
| Reuse | Hive and telemetry data are already in place: a harvest can cite the hive it came from and, where a device exists, the weight series around the harvest date |
| Tests | Lineage integrity (split/blend), event ordering and immutability, verification success/failure, public trace authorisation, RBAC per stage |

**Definition of done:** scanning a jar shows its recorded journey and whether the anchored history
verifies — and the platform reports missing steps instead of implying completeness.

---

## Phase 5b — future AI work (beyond the delivered baseline)

**Goal:** turn data into advisory insight, never diagnosis.

| Workstream | Detail |
| --- | --- |
| Data | `ai_predictions` with `model_version` for reproducibility |
| Models | Colony risk scoring from sensor trend + observations + season; yield forecasting from hive weight history; adulteration screening support from test parameters and origin consistency |
| Input available from Phase 3 | Sensor series (`temperature`, `humidity`, `weight`, `vibration`, `acoustic_level`) with source labels, so a model can distinguish hardware data from simulator data |
| API | `GET /ai/hives/{id}/risk`, `GET /ai/harvest-forecast`, explanations included with each output |
| Frontend | Risk and forecast panels presented as advisory, with contributing factors visible; confidence shown honestly |
| Governance | Model cards, accuracy reporting, drift monitoring, human-review workflow before acting on any output |
| Tests | Deterministic behaviour under frozen inputs, confidence bounds, graceful failure when the inference service is unavailable |

**Definition of done:** predictions appear as clearly-labelled risk indicators with reasoning, never
as diagnoses or purity verdicts.

---

## Phase 6 — KVIC analytics & operations

**Goal:** cluster-level visibility and platform operations.

| Workstream | Detail |
| --- | --- |
| Data | `notifications` (cluster and audit tables already exist from Phase 2) |
| Analytics | Aggregate queries (cluster, district and state level) over beekeepers, hives, devices and sensor series, with privacy-preserving thresholds |
| API | Analytics endpoints, export (CSV/PDF), audit-log query extensions |
| Frontend | KVIC dashboards over real aggregates, exportable reports for scheme monitoring |
| Notifications | Email/SMS/push dispatch (event- and digest-based), per-user preferences and quiet hours — including device-offline and battery events from Phase 3 |
| Tests | Aggregation correctness, jurisdiction scoping (no cross-cluster leakage), notification scheduling |

**Definition of done:** a KVIC officer can monitor clusters and produce scheme reports without
re-entering data that beekeepers already recorded.

---

## Phase 8 — Blockchain traceability integration ✅

**Goal:** make the blockchain service that already exists part of the supply chain rather than a
screen beside it — without building a second chain, a second copy of the data, or a single invented
transaction. The database stays the operational source of truth; the chain is the immutable record
of what happened.

| Workstream | Delivered |
| --- | --- |
| Integration | One centralised client (`app/services/blockchain/client.py`) for `GET`/`POST {BLOCKCHAIN_BASE_URL}/transactions`, configured entirely by environment, with timeouts, bounded retries, structured logging and failures returned rather than raised |
| Events | 19 event types recorded at the moment the real transition happens, from inside the same database transaction as the record — `COLLECTION_COMPLETED` through `RETAILER_RECEIVED`, plus `QR_GENERATED` and the idempotent `CUSTOMER_QR_VERIFIED` |
| Persistence | One new table, `blockchain_events` (idempotent `event_id`, nine foreign keys to the rows the workflow already wrote, `payload` JSONB, status, `tx_id`, `attempt_count`, `last_error`, timestamps). No duplicate operational entities |
| Delivery | A database-backed outbox swept by a background worker or by an administrator's **Sync now**: `PENDING` → `SUBMITTED` → `CONFIRMED`, with `FAILED` and `SKIPPED` telling the truth when the service refuses or the integration is switched off |
| Reads | Administrator ledger over the service's real `GET /transactions`, a KVIC ledger scoped to the officer's clusters, the batch screen's traceability section, the public `/trace/{code}` and `/verify/{qr_id}` pages, and a health widget reporting connected / pending / failed / last success |
| Roles | Beekeeper, processor, laboratory, packaging unit, distributor, retailer and consumer each trigger only their own stage's events; no client may choose a `tx_type`; Admin and KVIC read without writing |
| Preserved | The service's pre-existing transactions are history: never modified, never attached to a batch that did not produce them, never migrated |
| Evidence | `tests/test_blockchain.py` (22), `tests/phase8_blockchain_workflow.py` (46 checks against the **real** service), `tests/phase8_ui_checks.py` (browser checks of every Phase 8 screen) — recorded in `docs/phase-8-report.md` |

**Definition of done:** an end-to-end run — harvest, processing, laboratory, packaging, distribution,
retail receipt, QR, customer page — leaves one confirmed transaction per real transition in the
service's own ledger, visible on the HoneyChain screens, with nothing recorded ahead of the step it
describes. Met; see `docs/phase-8-report.md` §10.

---

## Cross-cutting workstreams

| Concern | Approach |
| --- | --- |
| **Offline tolerance** | Field connectivity is unreliable; later phases add optimistic updates and a queued-sync path. The telemetry batch endpoint already accepts a backlog of packets. |
| **Regional languages** | Copy is kept in components today; extraction into locale files happens before the first field pilot (Telugu, Hindi and English first) |
| **Observability** | Request-id correlation exists now; the MQTT consumer exposes counters at `/health/mqtt`. Add metrics (latency, error rate, ingest lag) and alerting as volume grows |
| **Security review** | Repeat after Phase 4: anchoring keys, device credentials, public trace endpoint abuse, rate limiting. Device ownership and ingest authorisation were covered in Phase 3. |
| **Performance** | Index and partition strategy revisited with real data volumes; `sensor_readings` is the first table where a rollup policy will matter |
| **Accessibility audit** | Screen-reader and keyboard pass before each release; target WCAG 2.1 AA |
| **Documentation** | Each phase updates `docs/api.md`, `docs/database.md` and this file as part of its definition of done |

---

## Out of scope (at this time)

- Cryptocurrency, tokens or any financial instrument — blockchain is used solely for record integrity.
- Self-service planting of IoT hardware for consumers.
- Claims of certified purity or automated disease diagnosis: the platform reports measurements,
  evidence and risk indicators, and defers certification to accredited laboratories and regulators.
  Phase 3 stores sensor readings and nothing more; it does not interpret them.
- Native mobile applications: the PWA-responsive web client is the delivery target, with mobile
  clients supported through the same API (`AUTH_EXPOSE_REFRESH_IN_BODY`).
