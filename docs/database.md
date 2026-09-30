# HoneyChain — Database design

Engine: **PostgreSQL 15+** (developed against 17). Access: SQLAlchemy 2.0 through
`psycopg` 3. Migrations: Alembic.

---

## 1. Design rules

| Rule | Reason |
| --- | --- |
| **UUID primary keys** (`gen_random_uuid()`) | Identifiers appear in public trace URLs and QR codes (Phase 4); sequential integers would leak volumes and invite enumeration |
| **Every table has `created_at` / `updated_at`** | Audit and dispute resolution across the supply chain |
| **Timestamps are `timestamptz` (UTC)** | Participants span districts, states and time zones |
| **Named constraints** via a metadata naming convention | Stable, readable Alembic diffs (`pk_users`, `uq_users_phone`, `fk_refresh_tokens_user_id_users`) |
| **`ON DELETE CASCADE` for owned rows** | Sessions must die with the account |
| **Enums for closed vocabularies** | Roles and statuses are validated by the database, not only by the application |
| **Unique constraints for real-world uniqueness** | `email`, `phone`, `refresh_tokens.token_hash`, `refresh_tokens.jti` |
| **Indexes justified by queries** | Not "just in case" |

---

## 2. Phase 1 schema

### 2.1 `users`

The single identity record for all ten roles. Role-specific profile data (apiary details, licences,
processing capacity) belongs in tables added by later phases — this table deliberately stays narrow.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | uuid | PK, default `gen_random_uuid()` | |
| `name` | varchar(120) | not null, `CHECK length(name) >= 2` | |
| `email` | varchar(255) | not null, **unique** | Stored lower-cased; login is case-insensitive |
| `phone` | varchar(20) | unique, nullable | Normalised to E.164 (`+91…`) |
| `password_hash` | varchar(255) | not null | bcrypt, cost 12. No plaintext column exists |
| `role` | `user_role` enum | not null, default `CONSUMER` | Ten values, see below |
| `is_active` | boolean | not null, default true | Administrators can suspend an account |
| `state` | varchar(80) | nullable | Onboarding/analytics context |
| `district` | varchar(80) | nullable | Cluster mapping in later phases |
| `organization` | varchar(160) | nullable | Co-operative, lab or company |
| `last_login_at` | timestamptz | nullable | Set on successful login only |
| `created_at` | timestamptz | not null, default `now()` | |
| `updated_at` | timestamptz | not null, default `now()` | Refreshed on modification |

Indexes: `ix_users_email` (unique), `ix_users_role`, `ix_users_role_active (role, is_active)`,
`uq_users_phone` (unique).

`ix_users_role_active` supports the administrator directory ("active beekeepers in this cluster")
without a full scan, which matters once clusters hold thousands of accounts.

### 2.2 `refresh_tokens`

Server-side session records. This is what makes logout, rotation and replay detection possible for
an otherwise stateless JWT architecture.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | uuid | PK | |
| `user_id` | uuid | FK → `users.id` ON DELETE CASCADE, not null | |
| `token_hash` | varchar(64) | not null, **unique** | SHA-256 of the token. The raw token is never stored |
| `jti` | varchar(64) | not null, **unique** | JWT id claim, correlates rotations |
| `replaced_by_jti` | varchar(64) | nullable | Points at the token that superseded this one |
| `revoked` | boolean | not null, default false | |
| `revoked_at` | timestamptz | nullable | |
| `revoke_reason` | varchar(80) | nullable | `logout`, `logout_all`, `rotated`, `reuse_detected`, `expired` |
| `expires_at` | timestamptz | not null | |
| `last_used_at` | timestamptz | nullable | Updated on refresh |
| `device` | varchar(64) | nullable | Hashed user-agent + IP fingerprint (audit display only) |
| `created_at` / `updated_at` | timestamptz | not null | |

Indexes: `ix_refresh_tokens_token_hash` (unique), `ix_refresh_tokens_user_id`,
`ix_refresh_tokens_user_active (user_id, revoked)`, `ix_refresh_tokens_expires_at`.

Why store a hash rather than nothing at all? A purely stateless refresh token cannot be revoked —
logout would only be cosmetic until expiry. Storing a fingerprint gives immediate revocation while
keeping a database leak non-replayable.

### 2.3 `user_role` enum

```text
ADMIN · BEEKEEPER · COLLECTION_CENTER · PROCESSOR · LAB_TECHNICIAN
PACKAGING_UNIT · DISTRIBUTOR · RETAILER · CONSUMER · KVIC_OFFICER
```

Declared with the full role vocabulary from the start: adding a role later would otherwise require
a migration plus client changes. The database type is created by the initial migration and dropped
explicitly on downgrade.

---

## 3. Phase 2 schema

Migration `c71dce65bc61` extends `users` and adds seven tables. All of it is Alembic-generated; no
manual DDL exists anywhere in the project.

### 3.1 `users` (extended)

| Added column | Type | Notes |
| --- | --- | --- |
| `phone` | varchar(20) | **Unique where provided** — `NULL`s are allowed to repeat |
| `is_verified` | boolean, default false | Account-level verification, distinct from beekeeper verification |
| `deactivated_at` | timestamptz | Set when an administrator deactivates the account |
| `last_login_at` | timestamptz | Written on successful login only |

`uq_users_phone` is a unique index, so several accounts without a phone number coexist.

### 3.2 `user_profiles`

Optional personal and location detail for any account — one row per user, created on first write.

| Column | Type | Notes |
| --- | --- | --- |
| `user_id` | uuid | PK and FK → `users.id`, `ON DELETE CASCADE` |
| `profile_photo` | varchar(512) | A URL; file storage is out of scope for this phase |
| `date_of_birth` | date | Checked to be in the past and plausible |
| `gender` | varchar(20) | Free vocabulary, nullable |
| `address` | text | |
| `village`, `mandal`, `district`, `state` | varchar | `district`/`state` indexed |
| `pincode` | varchar(10) | `CHECK pincode ~ '^[1-9][0-9]{5}$'` |
| `created_at`, `updated_at` | timestamptz | |

### 3.3 `beekeepers`

One row per beekeeper user, enforced by `uq_beekeepers_user_id`.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users.id`, **unique**, `ON DELETE CASCADE` |
| `beekeeper_code` | varchar(40) | **Unique**, generated (`BKR-GNT-00001`) from `document_sequences` |
| `experience_years` | integer | `CHECK 0…90` when present |
| `bee_species` | varchar(80) | |
| `number_of_hives` | integer | `CHECK 0…100 000` when present |
| `village`, `mandal`, `district`, `state`, `pincode` | varchar | `pincode` shares the PIN-code check |
| `kvic_cluster_id` | uuid | FK → `kvic_clusters.id`, `ON DELETE SET NULL`; `NULL` = unassigned |
| `registration_date` | date | Set on creation |
| `verification_status` | `verification_status` enum | Default `PENDING` |
| `verification_remarks` | text | Latest decision's remark |
| `verified_by_id` | uuid | FK → `users.id`, `ON DELETE SET NULL` |
| `verified_at` | timestamptz | |
| `created_at`, `updated_at` | timestamptz | |

Indexes: `ix_beekeepers_district_status (district, verification_status)` and
`ix_beekeepers_cluster_status (kvic_cluster_id, verification_status)` — the two shapes every directory
query uses.

### 3.4 `kvic_clusters`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `cluster_code` | varchar(40) | **Unique**, generated (`KVIC-GNT-001`) |
| `cluster_name` | varchar(160) | `CHECK length >= 3` |
| `district`, `state` | varchar(80) | Not null; indexed with `is_active` |
| `description` | text | |
| `coordinator_name`, `coordinator_phone` | varchar | |
| `is_active` | boolean, default true | Deactivated clusters keep their members |
| `created_at`, `updated_at` | timestamptz | |

### 3.5 `beekeeper_verification_history` (append-only)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `beekeeper_id` | uuid | FK → `beekeepers.id`, `ON DELETE CASCADE` |
| `previous_status` | enum | `NULL` for the opening `None → PENDING` row |
| `new_status` | enum | |
| `remarks` | text | Required by the API for `REJECTED`/`SUSPENDED` |
| `changed_by_id` | uuid | FK → `users.id`, `ON DELETE SET NULL` |
| `changed_by_name`, `changed_by_role` | varchar | Denormalised so the trail survives an account being removed |
| `changed_at` | timestamptz | Indexed with `beekeeper_id` |

The application only ever inserts here: no update or delete path exists, which is what makes the
review trail trustworthy.

### 3.6 `audit_logs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users.id`, `ON DELETE SET NULL` |
| `actor_email`, `actor_role` | varchar | Denormalised actor identity |
| `action` | varchar(60) | Event vocabulary (`USER_REGISTERED`, `BEEKEEPER_VERIFIED`, …) |
| `entity_type`, `entity_id` | varchar | What was acted on |
| `event_metadata` | jsonb | Validated on write; never holds passwords, tokens or secrets |
| `description` | text | Human-readable summary |
| `ip_address`, `user_agent` | varchar | Request context |
| `created_at` | timestamptz | Indexed with `action` and with `user_id` |

Written inside a SAVEPOINT (`begin_nested()`), so a failure to audit can never abort the business
transaction it describes.

### 3.7 `document_sequences`

| Column | Type | Notes |
| --- | --- | --- |
| `scope` | varchar(80) | **Unique** — e.g. `beekeeper:BKR-GNT`, `cluster:KVIC-GNT` |
| `last_value` | integer | Allocated with `SELECT … FOR UPDATE` inside the owning transaction |
| `updated_at` | timestamptz | |

`document_sequences` is what makes `BKR-GNT-00001` and `HIVE-GNT-00001` race-free and gapless per
district without a sequence explosion, and it keeps the human-readable code independent of the row's
UUID. Phase 3 adds the `HIVE:<PREFIX>` scope (see §4).

### 3.8 `verification_status` enum

```text
PENDING · UNDER_REVIEW · VERIFIED · REJECTED · SUSPENDED
```

Legal transitions are enforced in the application (`VerificationStatus.allowed_transitions`) as well
as by the service layer, so an illegal jump is rejected with `422` before it reaches the database.

---

## 4. Phase 3 schema — hive registry and telemetry

Four tables, plus two code-generation and history habits carried over from Phase 2 (root codes come
from `document_sequences`; nothing is ever hard-deleted when it holds evidence).

### 4.1 `hives`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `hive_code` | varchar(24) | **Unique**, `HIVE-<DISTRICT>-NNNNN`, generated from `document_sequences` |
| `beekeeper_id` | uuid | FK → `beekeepers.id`, `ON DELETE CASCADE`, indexed |
| `cluster_id` | uuid | FK → `kvic_clusters.id`, nullable, `ON DELETE SET NULL` |
| `status` | `hive_status` | `ACTIVE` (default), `INACTIVE`, `MAINTENANCE`, `REMOVED` |
| `colony_strength` | `colony_strength` | `UNKNOWN` (default), `WEAK`, `MODERATE`, `STRONG` — the beekeeper's observation |
| `queen_status` | `queen_status` | `UNKNOWN` (default), `PRESENT`, `ABSENT`, `UNDER_OBSERVATION` — an observation, not an inference |
| `bee_species` | varchar(80) | Optional (`Apis cerana indica`, …) |
| `installation_date` | date | Optional |
| `village`, `mandal`, `district`, `state`, `pincode` | varchar | Apiary location; `pincode` is 6 digits when present |
| `latitude`, `longitude` | numeric | Optional pair — both or neither |
| `notes` | text | Optional, ≤ 2000 characters |
| `created_at`, `updated_at` | timestamptz | |

Indexes: `beekeeper_id`, `cluster_id`, `status`, `district`, and a unique index on `hive_code`.
Deleting a hive that has devices or readings is refused by the service; it becomes `REMOVED`, which
keeps the telemetry series interpretable.

### 4.2 `iot_devices`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `device_id` | varchar(40) | **Unique** (case-insensitive), pattern `^[A-Za-z0-9][A-Za-z0-9._-]{3,39}$` |
| `device_name` | varchar(120) | Human label |
| `device_type` | `device_type` | `ESP32` (default), `ESP32_GATEWAY`, `LORA_NODE`, `OTHER` |
| `connection_type` | `connection_type` | `MQTT` (default), `WIFI`, `LORA`, `LORA_MQTT`, `CELLULAR` |
| `hive_id` | uuid | FK → `hives.id`, `ON DELETE SET NULL`, indexed |
| `beekeeper_id` | uuid | FK → `beekeepers.id`, `ON DELETE SET NULL` — the ownership column every query filters on |
| `status` | `device_status` | `OFFLINE` when registered; **derived** at read time from `last_seen` + `battery_level` |
| `last_seen` | timestamptz | Updated by a stored packet, heartbeat or status message |
| `battery_level` | smallint | 0–100, last reported |
| `signal_strength` | smallint | −140…0 dBm, last reported (null when the device does not send it) |
| `firmware_version` | varchar(40) | Optional |
| `mqtt_topic` | varchar(160) | Default `<prefix>/devices/{device_id}/telemetry`, shown in the UI |
| `installed_at` | timestamptz | Optional |
| `created_at`, `updated_at` | timestamptz | |

`status` is stored as well as derived: the stored value is what a sweep persists, the derived value
is what every response reports, and the two can only disagree between a packet and the next sweep.

### 4.3 `sensor_configs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `device_id` | uuid | FK → `iot_devices.id`, `ON DELETE CASCADE`, indexed |
| `sensor_type` | `sensor_type` | `TEMPERATURE`, `HUMIDITY`, `WEIGHT`, `VIBRATION`, `ACOUSTIC`, `BATTERY` |
| `sensor_name` | varchar(80) | Display label |
| `unit` | varchar(16) | `°C`, `%`, `kg`, `g`, `dB` |
| `enabled` | boolean | Default `true` |
| `sampling_interval` | integer | Suggested seconds between readings (≥ 1, default 300) |
| `min_valid_value`, `max_valid_value` | numeric(10,3) | Optional per-sensor narrowing of the global range |
| `created_at`, `updated_at` | timestamptz | |

Unique on `(device_id, sensor_type)`. Registration seeds the five sensors an ESP32 hive node carries
(`DEFAULT_SENSOR_SPECS`); `BATTERY` and `SIGNAL` are device-health facts rather than configured
sensors, so they are stored on the device row and in each reading instead.

### 4.4 `sensor_readings` (wide)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `device_id` | uuid | FK → `iot_devices.id`, `ON DELETE CASCADE` |
| `hive_id` | uuid | FK → `hives.id`, **NOT NULL** — denormalised for one-index history reads |
| `beekeeper_id` | uuid | FK → `beekeepers.id`, `ON DELETE CASCADE` — denormalised for apiary-wide queries |
| `timestamp` | timestamptz | **Unique with `device_id`** (`uq_sensor_readings_device_timestamp`) — makes ingest idempotent |
| `temperature` | numeric(6,2) | °C, −20…80 |
| `humidity` | numeric(5,2) | %, 0…100 |
| `weight` | numeric(8,3) | kg, ≥ 0 |
| `vibration` | numeric(6,3) | g, ≥ 0 |
| `acoustic_level` | numeric(6,2) | dB (relative activity), ≥ 0 |
| `battery_level` | smallint | % (optional) |
| `signal_strength` | smallint | dBm (optional) |
| `source` | `telemetry_source` | `REAL_DEVICE`, `SIMULATOR`, `MANUAL` |
| `created_at` | timestamptz | Receipt time; `timestamp` is measurement time |

Indexes: `(hive_id, timestamp)`, `(device_id, timestamp)`, `(beekeeper_id, timestamp)` — the three
access patterns the module actually uses (one hive's history, one device's history, one apiary's
readings). A wide row rather than an entity-attribute-value table keeps a packet to a single insert
and a chart query to a single scan; a sensor a device does not carry stays `NULL` and is rendered as
"No data" rather than as a zero.

### 4.5 New enums

```text
hive_status        ACTIVE · INACTIVE · MAINTENANCE · REMOVED
colony_strength    UNKNOWN · WEAK · MODERATE · STRONG
queen_status       UNKNOWN · PRESENT · ABSENT · UNDER_OBSERVATION
device_type        ESP32 · ESP32_GATEWAY · LORA_NODE · OTHER
connection_type    WIFI · LORA · MQTT · LORA_MQTT · CELLULAR
device_status      ONLINE · OFFLINE · WARNING · MAINTENANCE
sensor_type        TEMPERATURE · HUMIDITY · WEIGHT · VIBRATION · ACOUSTIC · BATTERY
telemetry_source   REAL_DEVICE · SIMULATOR · MANUAL
```

The migration creates and drops these types explicitly, so `alembic downgrade base` leaves no orphan
types behind (guarded by `tests/test_migrations.py`).

---

## 5. Role of the ORM

- All access goes through `app/repositories/*`; routes and services never build SQL.
- Repositories use SQLAlchemy expression constructs, so every value is parameter-bound — which is
  what protects against SQL injection.
- Sessions are per-request (`get_db`) and rolled back automatically when an exception escapes,
  leaving each request as a single unit of work.
- `expire_on_commit=False` keeps ORM objects usable after the service commits, so the route can
  serialise the response without triggering late implicit queries.

---

## 6. Migration workflow

```bash
cd backend

# Apply everything
alembic upgrade head

# After changing models — generate, then REVIEW the file
alembic revision --autogenerate -m "add hives and harvests"

# Step back / forward
alembic downgrade -1
alembic upgrade head

# Inspect
alembic current
alembic history --verbose

# Emit SQL without a database (for DBA review)
alembic upgrade head --sql
```

Guidelines:

1. **Review autogenerated migrations.** Alembic cannot detect enum value additions/changes, renames,
   or data backfills.
2. **Never edit an applied migration.** Add a new one.
3. **Downgrades must work.** PostgreSQL DDL is transactional, so `transaction_per_migration=True` in
   `alembic/env.py` makes a failed migration roll back cleanly.
4. **The URL is never in `alembic.ini`** — `env.py` reads it from application settings so migrations
   always target the same database as the API, with no credentials in version control.
5. **Tests guard the chain**: `tests/test_migrations.py` asserts a single head, the expected tables
   and the presence of the explicit enum teardown.

---

## 6.1 Phase 4.1 — no schema change, one backfill

Phase 4.1 (the organisational relationship `KVIC → Cluster → Beekeeper → Hive → IoT → Telemetry →
AI`) added **no table and no column**: `beekeepers.kvic_cluster_id` and `hives.cluster_id` already
expressed the relationship, both indexed, with `ix_hives_cluster_status` available for the cluster
views. What was missing was history, so the phase shipped one data-only migration:

| Item | Value |
| --- | --- |
| Revision | `5e2b7d41c8aa` (`down_revision = a77f6c38aaff`) |
| Statement | `UPDATE hives SET cluster_id = beekeepers.kvic_cluster_id FROM beekeepers WHERE hives.beekeeper_id = beekeepers.id AND hives.cluster_id IS NULL AND beekeepers.kvic_cluster_id IS NOT NULL` |
| Idempotent | Yes — only `NULL` placements are filled, so a second run changes nothing |
| Invents nothing | A beekeeper with no cluster leaves their hives unassigned; those hives are listed for staff via `has_cluster=false` |
| Overwrites nothing | A hive deliberately placed in another cluster keeps its placement |
| Downgrade | No-op by design: clearing the values would hide hives from the cluster that owns them |

The relationship's integrity is enforced by the existing foreign keys
(`hives.beekeeper_id`, `hives.cluster_id`, `iot_devices.hive_id`, `sensor_readings.hive_id`, …), most
of them `ON DELETE SET NULL`, so removing a cluster leaves the hives intact and merely unassigned.

---

---

## 7. Phase 8 — `blockchain_events` (the traceability outbox)

Phase 8 added **one** table. It did not add a second batch, package, laboratory or distribution
table, and it did not copy operational data: every event points at the row the workflow already
wrote.

Migration: `20260929_1800_9b1f4c2d7e05_phase_8_blockchain_traceability.py`.

| Column | Type | Notes |
| --- | --- | --- |
| `event_id` | text, **unique** | The idempotency key. Deterministic — derived from the record and the transition (`PACKAGE-HC-PKG-2026-000001-CREATED`, `DIST-HC-DIST-2026-000004-DELIVERED`) or a content hash where the record is one of many. A retry, a refresh or a second tab finds the existing row instead of writing a second transaction. |
| `tx_type` | enum | One of the 19 `BlockchainEventType` values: `COLLECTION_COMPLETED`, `BATCH_CREATED`, `PROCESSING_STARTED`, `PROCESSING_COMPLETED`, `LAB_TEST_STARTED`, `QUALITY_CHECKED`, `QUALITY_FAILED`, `QUALITY_HOLD`, `PROCEEDED_WITH_RISK`, `PACKAGING_STARTED`, `PACKAGE_CREATED`, `PACKAGED`, `DISTRIBUTION_CREATED`, `DISTRIBUTION_DISPATCHED`, `IN_TRANSIT`, `DELIVERED`, `RETAILER_RECEIVED`, `QR_GENERATED`, `CUSTOMER_QR_VERIFIED`. |
| `status` | enum | `PENDING`, `SUBMITTED`, `CONFIRMED`, `FAILED`, `SKIPPED`. |
| `tx_id` | text, nullable | The service's transaction id (64 hex), filled when the service answers. |
| `payload` | JSONB | The summary that goes on the chain: identifiers, statuses, quantities, actor role, cluster, beekeeper, hives, location and the moment. No passwords, tokens, notes, documents, images, raw telemetry or AI input — those stay in HoneyChain. |
| `batch_id`, `collection_id`, `processing_id`, `lab_test_id`, `packaging_id`, `package_id`, `distribution_id`, `cluster_id`, `actor_id` | uuid, nullable, `ON DELETE SET NULL` | References to the **same** rows the workflow uses. Nine foreign keys, no duplicated entities. `batch_code` is denormalised beside `batch_id` so a ledger row survives a deleted batch as history. |
| `attempt_count`, `last_error` | int / text | How many submissions were attempted and what the service said the last time it refused. |
| `submitted_at`, `confirmed_at` | timestamptz | When the POST left HoneyChain and when the service confirmed it. |

Indexes: `event_id` (unique), `status`, `tx_type`, `batch_id`, `package_id`, `created_at`.

**How a row is written.** Inside the same database transaction as the state change it describes,
immediately before the pre-existing `commit()` — so the record and its event are committed
together or not at all. Nothing is written for a step that has not happened, and nothing is written
by the frontend: the client never sends a `tx_type`.

**How it leaves the building.** A background worker (`BLOCKCHAIN_OUTBOX_WORKER_ENABLED`,
`BLOCKCHAIN_OUTBOX_POLL_SECONDS`) sweeps `PENDING`/`FAILED` rows in bounded batches
(`BLOCKCHAIN_OUTBOX_BATCH_SIZE`), or an administrator presses **Sync now**
(`POST /api/v1/blockchain/sync`). A refusal or an outage leaves the row `FAILED` with the service's
own words in `last_error`; the workflow that produced it is never rolled back and no success is
invented. With `BLOCKCHAIN_ENABLED=false`, events are recorded and swept to `SKIPPED` with the
reason — visible as such, never as confirmed.

**Legacy rows.** Transactions that exist on the service but were not written by HoneyChain are
read-only history: they are listed in the administrator's raw chain ledger (section 12 of
`docs/api.md`), marked `honey_chain_recorded: false`, and are never attached to a batch, migrated or
modified.

## 8. Phase 5–7 tables, as delivered (and what is still planned)

This table was written before Phases 5–7 and is kept as the record of what was planned. The
delivered schema differs from the sketch in two deliberate ways, and those differences are the
design: **`honey_batches`, `collections`, `packaging_records`, `packages`, `distribution` and
`distribution_items` are separate operational tables joined by foreign keys** (there is no
`harvests`/`packaging`/`retail` monolith), and **batch lineage is a parent link plus the collection
it came from**, not a copy of the batch per stage. Every one of those tables is documented in its
phase report (`docs/phase-5-report.md` … `docs/phase-8-report.md`). What remains genuinely planned
is the last two rows: `ai_predictions` and `notifications`.

| Phase | Tables | Key relationships |
| --- | --- | --- |
| 4 | `harvests`, `inspections` | `harvests.hive_id → hives.id` (already in place from Phase 3); `harvests.beekeeper_id → beekeepers.id` |
| 4 | `honey_batches`, `batch_events`, `processing_events`, `quality_tests`, `packaging`, `qr_codes`, `blockchain_transactions`, `distribution`, `retail` | `honey_batches.harvest_id → harvests.id`; batch lineage through a self-referencing `parent_batch_id` for splits and blends; every anchored event gets a `blockchain_transactions` row |
| 5 | `ai_predictions` | `ai_predictions.hive_id` / `batch_id` + `model_version` for reproducibility; inputs are the Phase 3 sensor series |
| 6 | `notifications` | `notifications.user_id → users.id`; device-offline and battery events come from Phase 3 telemetry |

When `sensor_readings` grows into the tens of millions of rows, the next step is monthly range
partitioning on `timestamp` — the three indexes are already aligned with that key.

Two design commitments for later phases:

- **Batch lineage, not batch replacement.** A batch keeps its parents, so a blended or split lot can
  still be traced back to source hives. This is the backbone of consumer verification.
- **Measurements, not verdicts.** `quality_tests` stores parameter values (`moisture`, `hmf`,
  `sucrose`, …) with method and instrument context, so the platform reports what was measured and
  who measured it, never a bare "pure" claim.

---

## 9. Operations

**Backups and restore**

```bash
pg_dump -h localhost -U honeychain -Fc honeychain_dev  > honeychain_$(date +%F).dump
pg_restore -h localhost -U honeychain -d honeychain_dev honeychain_2026-09-22.dump
```

**Housekeeping.** Expired refresh-token rows accumulate; `RefreshTokenRepository.purge_expired()`
exists for a scheduled job (cron / APScheduler) and should be wired up when the notification and
scheduler modules land.

**Connection handling.** The engine uses `pool_pre_ping=True` (transparently discards connections
dropped by the server or a pooler) and `pool_recycle=1800`, with pool size and overflow configurable
through `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`.

**Least privilege.** The application role should own only its own database. Schema-changing
privileges are needed solely by the migration role if a separate one is used in production.
