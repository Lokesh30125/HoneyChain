# HoneyChain — Architecture

> Screenshots of the implemented Phase 1 interface are in
> [`docs/screenshots/`](screenshots/) and embedded in the [README](../README.md#51-visual-tour).

> Scope: this document describes the **Phase 1 foundation**. It also states where each later phase
> plugs in, so the design intent is clear before those modules exist.

---

## 1. System context

```text
┌──────────────┐   scan QR (Phase 3)   ┌────────────────────┐
│  Consumer    │ ────────────────────▶ │                    │
└──────────────┘                       │                    │
┌──────────────┐                       │                    │      ┌──────────────────┐
│  Beekeeper   │  hive + harvest data  │   HoneyChain SPA   │      │  PostgreSQL      │
├──────────────┤ ────────────────────▶ │   (React + Vite)   │ ───▶ ├──────────────────┤
│  Collection  │                       │                    │      │  users, sessions │
│  Processor   │  batch events         │        │           │      │  (later: hives,  │
│  Lab         │ ────────────────────▶ │        │ /api/v1   │      │  batches, IoT,   │
│  Packager    │                       │        ▼           │      │  chain, tests)   │
│  Distributor │                       │  HoneyChain API    │      └──────────────────┘
│  Retailer    │                       │   (FastAPI)        │
├──────────────┤  cluster analytics    │        │           │      ┌──────────────────┐
│ KVIC officer │ ────────────────────▶ │        ├───────────┼────▶ │ IoT ingest       │ Phase 4
│  Admin       │  platform oversight   │        ├───────────┼────▶ │ AI service       │ Phase 5
└──────────────┘                       │        └───────────┼────▶ │ Chain anchor     │ Phase 3
                                       └────────────────────┘      └──────────────────┘
```

Ten roles, one sign-in. What a user can see and do is decided by the role attached to their account,
both in the router (UX) and in the API (authority).

---

## 2. Backend architecture

### 2.1 Layer responsibilities

| Layer | Location | May do | Must not do |
| --- | --- | --- | --- |
| **Route** | `app/routes/` | Parse/validate input, call a service, set cookies, choose status codes | Contain business rules or database queries |
| **Service** | `app/services/` | Enforce business rules, coordinate repositories, own transactions, emit audit logs | Build SQL or know about HTTP |
| **Repository** | `app/repositories/` | Build and execute SQLAlchemy queries, paginate, count | Apply business policy |
| **Model** | `app/models/` | Declare tables, relationships, constraints, light helpers | Perform I/O or know about requests |
| **Schema** | `app/schemas/` | Define request/response contracts and validation | Contain logic beyond validation |
| **Core** | `app/core/` | Config, security primitives, engine/session, logging, error taxonomy | Import from routes/services |

This is enforced by dependency direction: `routes → services → repositories → models`. Nothing points
back up.

### 2.2 Why this matters for later phases

A blockchain anchoring module, for example, will need to (a) read batch events, (b) hash them,
(c) write an anchor record, and (d) expose a verification endpoint. In this architecture that is:
`repositories/batch_repository.py` + `repositories/anchor_repository.py`, `services/anchor_service.py`,
`routes/blockchain.py`. No existing file needs to be restructured — the same pattern as auth.

### 2.3 Dependency injection

FastAPI's dependency system carries three things:

```python
db_session      = get_db               # one session per request, cached per callable
get_current_user                       # resolves and validates the bearer token
requires_roles(UserRole.ADMIN)         # dependency *factory* for RBAC
```

> **Note for maintainers.** `db_session` in `app/api/dependencies.py` is an *alias* of `get_db`,
> not a wrapper. FastAPI caches a dependency per callable, so a wrapper would create a second
> session per request and objects loaded in one session could not be used with the other. This bug
> was found by the test suite; keep the alias.

### 2.4 Error handling

Three mechanisms, one output shape:

| Raised | Handler | Result |
| --- | --- | --- |
| `AppError` subclass (`NotFoundError`, `ForbiddenError`, …) | `handle_app_error` | Its own status + stable code |
| `RequestValidationError` | `handle_validation_error` | `422 VALIDATION_ERROR` with per-field details |
| `StarletteHTTPException` (routing, method, framework 401) | `handle_http_exception` | Mapped code from `HTTP_STATUS_CODES` |
| `IntegrityError` (unique/FK violation) | `handle_integrity_error` | `409 CONFLICT` |
| `SQLAlchemyError` | `handle_database_error` | `500 DATABASE_ERROR`, full traceback logged |
| Anything else | `handle_unexpected_error` | `500 INTERNAL_ERROR`, never leaks internals |

Successful responses are built with the `ok()` / `paginated()` helpers from
`app/schemas/common.py`, and `ApiResponse` omits `meta` when there is nothing to report.

### 2.5 Observability

- `RequestContextMiddleware` assigns/propagates an `X-Request-ID`, stores it in a `ContextVar`, and
  logs method, path, status and duration for every request (health checks excluded to avoid noise).
- Every log record is JSON in non-development environments, with the request id attached by
  `RequestIdFilter`.
- `SensitiveDataFilter` scrubs passwords, tokens, API keys and connection strings from both the
  rendered message and `extra` fields — defence in depth, not a substitute for not logging them.
- Logger namespaces: `honeychain.api`, `honeychain.auth`, `honeychain.db`, `honeychain.service`; the
  IoT, AI and blockchain reserved namespaces are documented in `app/core/logging.py`.

---

## 3. Data architecture

### 3.1 Phase 1 tables

```text
users                                refresh_tokens
─────────────────────────            ─────────────────────────────
id            uuid PK                id              uuid PK
name          varchar(120)           user_id         uuid FK → users.id (CASCADE)
email         varchar(255) UNIQUE    token_hash      varchar(64) UNIQUE   ← SHA-256 of token
phone         varchar(20)  UNIQUE    jti             varchar(64) UNIQUE
password_hash varchar(255)           replaced_by_jti varchar(64)          ← rotation chain
role          user_role  (enum)      revoked         boolean
is_active     boolean                revoked_at      timestamptz
state         varchar(80)            revoke_reason   varchar(80)
district      varchar(80)            expires_at      timestamptz
organization  varchar(160)           last_used_at    timestamptz
last_login_at timestamptz            device          varchar(64)          ← hashed fingerprint
created_at    timestamptz
updated_at    timestamptz
```

Conventions applied platform-wide:

- **UUID primary keys** so identifiers are not enumerable in public trace/QR URLs (Phase 4).
- **`created_at` / `updated_at`** on every table via mixins; timezone-aware (UTC).
- **Named constraints** through a metadata naming convention, keeping Alembic diffs stable.
- **Indexes chosen for real queries**: `users(role, is_active)` for directories,
  `refresh_tokens(user_id, revoked)` for session lookups, `refresh_tokens(expires_at)` for cleanup.

### 3.2 Phase 3 tables — hive registry and telemetry

```
hives                          iot_devices                     sensor_readings (wide)
────────────────────────       ─────────────────────────       ──────────────────────────────
id            uuid PK          id            uuid PK           id            uuid PK
hive_code     varchar UNIQUE   device_id     varchar UNIQUE    device_id     uuid FK
beekeeper_id  uuid FK          hive_id       uuid FK (SET NULL) hive_id      uuid FK NOT NULL
cluster_id    uuid FK NULL     beekeeper_id  uuid FK            beekeeper_id uuid FK
status        hive_status      status        device_status      timestamp     timestamptz
colony_strength  enum          last_seen     timestamptz        temperature, humidity, weight,
queen_status  enum             battery_level smallint           vibration, acoustic_level,
bee_species   varchar          signal_strength smallint         battery_level, signal_strength
village…pincode, lat/lon       mqtt_topic    varchar            source       telemetry_source
created_at/updated_at          created_at/updated_at           UNIQUE (device_id, timestamp)

                          sensor_configs
                          ─────────────────────────
                          device_id  uuid FK (CASCADE)
                          sensor_type sensor_type
                          enabled    boolean
                          sampling_interval integer
                          UNIQUE (device_id, sensor_type)
```

Three choices worth naming:

- **Denormalised ownership.** `iot_devices.beekeeper_id` and `sensor_readings.hive_id` /
  `beekeeper_id` are copied down from the hive. Visibility then costs one indexed column instead of a
  join up the chain, and a cross-owner leak would have to break two independent checks to happen.
- **Wide readings with a `(device_id, timestamp)` uniqueness constraint.** One packet is one insert,
  a replay is a no-op, and a sensor the device does not carry is `NULL` — never a fabricated zero.
- **`source` on every reading.** `REAL_DEVICE` / `SIMULATOR` / `MANUAL` is stored, not inferred at
  display time, so simulated and hand-entered values can never be presented as hardware data.

### 3.3 Ingest paths converge

```
ESP32 node ──MQTT──► broker ──► MqttIngestService (daemon thread) ─┐
                                                                   ├─► TelemetryService.ingest ─► PostgreSQL
simulator / device / manual entry ──HTTP──► POST /iot/telemetry ───┘        (validate → label → store)
```

Both transports end in one validation pipeline, so the contract a device codes against does not
change with the transport, and neither path can write into another beekeeper's series. The MQTT
consumer is optional by design: with `MQTT_BROKER_URL` unset the API, the HTTP ingest endpoint and
every dashboard still work, and `/health/mqtt` says `not_configured` instead of failing.

### 3.4 Migration policy

- One migration per logical change; never edit an applied migration.
- Autogenerate, then **review**: Alembic cannot infer enum changes or data migrations.
- `downgrade()` must be real — the initial migration explicitly drops the `user_role` enum type,
  because `drop_table` does not remove it and a later upgrade would fail.
- `tests/test_migrations.py` asserts a single head and that metadata matches the migrations. The
  Phase-3 migration also creates and drops its eight enum types explicitly, so
  `alembic downgrade base` leaves no orphan types behind.

---

## 4. Frontend architecture

### 4.1 State ownership

| Kind of state | Where | Example |
| --- | --- | --- |
| Session | `AuthContext` (only true global state) | signed-in user, role |
| Transient notifications | `ToastContext` | "Profile updated" |
| Server data | the page that requested it | admin summary, user directory |
| Form state | the form component (React Hook Form) | login, registration |
| UI state | the component | sidebar open, password visible |

Deliberately **no global store** (Redux/Zustand): the application has exactly one cross-cutting
concern — authentication — and everything else is local or server-owned.

### 4.2 HTTP layer

```text
component → service function (services/*.js) → apiClient (axios) → /api/v1/...
```

- Request interceptor attaches the bearer token.
- Response interceptor unwraps `{success, data, meta}` so services return plain data.
- On `401`: refresh once, replay the original request. Concurrent 401s await the same refresh.
- On refresh failure: clear the session and notify the app via `onSessionExpired`.
- Errors are normalised to `ApiError { code, message, status, details, fieldErrors }`, which is what
  `ErrorState` and form error mapping consume.

Components never import `axios` or read tokens.

### 4.3 Routing and guards

```text
PublicLayout      → /  /about  /how-it-works  /contact
(auth pages)      → /login  /register
ProtectedRoute    → requires a valid session (boots via /auth/me, loading state while checking)
  DashboardLayout → /dashboard  /profile  /admin  /beekeeper  /supply-chain
                    /laboratory  /kvic  /consumer
RoleRoute         → additionally restricts a subtree to specific roles
```

`ProtectedRoute` waits for the session check instead of redirecting immediately, which avoids
flashing the login screen on a page refresh. `RoleRoute` is UX only — the API re-checks.

### 4.4 Design system

Design tokens live in `tailwind.config.js`:

| Token group | Purpose |
| --- | --- |
| `honey.*` | Golden accent (primary highlight, CTAs) |
| `forest.*` | Deep green (structure, headers, primary actions) |
| `sand.*` | Warm neutrals (backgrounds, borders) |
| `ink.*` | Text colours (primary/soft/muted) |
| `status.*` | Conventional semantics (success, warning, danger, info, pending) |

Components are split so no file becomes a monolith: `ui/` primitives (Button, Input, Card, Badge,
Alert, Modal, Spinner) → `common/` composed patterns (StatCard, DataTable, EmptyState, ErrorState,
LoadingState, ConfirmDialog, StatusBadge, PageHeader, Breadcrumb) → feature components → pages.

Accessibility requirements: labelled inputs, `aria-invalid` + `aria-describedby` on errors, visible
focus rings, `role="alert"` for errors, keyboard-operable dialog with Escape, and
`prefers-reduced-motion` respected globally.

---

## 5. Security model

| Threat | Control |
| --- | --- |
| Password theft from database | bcrypt (cost 12); hashes never serialised |
| Credential stuffing / user enumeration | Identical 401 for unknown email and wrong password |
| Token theft via XSS | Access token in memory; refresh token in HttpOnly cookie |
| Refresh token replay | Rotation + reuse detection revokes all sessions for that user |
| Session persistence after logout | Refresh token revoked server-side; UI state cleared |
| Privilege escalation via sign-up | Privileged roles rejected at the API, not just hidden in the UI |
| SQL injection | ORM parameter binding only; repositories never interpolate strings |
| Secret leakage in logs | Redaction filter + documented logging rules |
| Secret leakage in source control | `.gitignore` covers `.env*`; production boot check rejects placeholders |
| CSRF on cookie-authenticated calls | Refresh cookie is `SameSite` (configurable) and path-scoped; only `/auth/*` uses it |
| Cross-origin abuse | Explicit CORS allow-list; `*` rejected in production |
| Path traversal / malformed input | Pydantic validation and UUID typing at every boundary |

Known trade-off, documented deliberately: the access token cannot be revoked before it expires
(stateless JWT). That is why its TTL is short (30 minutes, 20 in production) and why logout revokes
the refresh token immediately. If instant access-token revocation is required later, the same
`refresh_tokens` table can back a token denylist without changing the API surface.

---

## 5.1 The organisational relationship (Phase 4.1)

One chain, stored once, resolved in the database:

```
KVIC → kvic_clusters → beekeepers.kvic_cluster_id → hives.(beekeeper_id, cluster_id)
     → iot_devices.hive_id → sensor_readings.(hive_id, device_id, beekeeper_id) → hive_ai_analyses.hive_id
```

Nothing in the platform stores a second copy of a hive, a device, a reading or an assessment for a
cluster. A cluster's data is *read through* the relationship, which is why the chain cannot drift:

- **Write path.** A hive inherits its owner's cluster at creation. `ClusterService.assign_beekeeper`
  propagates a membership change to the hives still following the owner; a hive deliberately placed
  elsewhere is left alone. Staff may place one hive explicitly through
  `HiveService.change_cluster`, which validates the target and audits the move.
- **Read path.** `ClusterAnalyticsService` derives `hive_ids` for the cluster and asks the same
  repositories, services and engine the beekeeper's own screens use
  (`HiveRepository.list_for_cluster`, device/reading repositories with `hive_ids=`,
  `AiService.summary_for_hive_ids`, `IotMonitoringService.summary_for_hive_ids`). The cluster view
  therefore cannot disagree with the hive screen — it is the same query through a different filter.
- **Boundary.** A client never names the relationship: `cluster_id` is refused inside hive and device
  payloads. Placement is a separate, staff-only, audited endpoint.
- **Honesty.** An empty cluster reports zeroes; a cluster with hives but no telemetry reports
  `has_data: false` and an explanatory empty state; a hive whose owner has no cluster is *absent*
  from every cluster view and present in the staff worklist (`has_cluster=false`).

---

## 6. Extension points for later phases

Phases 1–4.1 are implemented; the rows below describe where the remaining phases attach.

| Phase | Backend additions | Frontend additions |
| --- | --- | --- |
| 5 — Traceability & blockchain | `models/harvest.py`, `models/batch.py`, `models/event.py`, `models/qr_code.py`, `models/chain_tx.py`; `services/anchor_service.py`; `routes/blockchain.py`, `routes/trace.py` | harvest records, batch timeline, QR issuance, public verification page |
| 6 — KVIC analytics & operations | `services/analytics_service.py` (scheme aggregates), `models/notification.py` | scheme reporting, cluster exports, notifications |

Delivered so far: **Phase 4** — the advisory AI layer (`services/ai/` baseline engine,
`services/ai_service.py`, `services/ai_alert_service.py`, `routes/ai.py`, `models/ai_analysis.py`,
`models/ai_alert.py`) — and **Phase 4.1** — `services/cluster_analytics_service.py` and the
relationship primitives (propagation, `hive_ids` scoping, `change_cluster`, the `has_cluster`
worklist, migration `5e2b7d41c8aa`). Both extend the existing layers rather than adding new ones.

Existing extension points the later phases should reuse rather than duplicate:

- **Permission catalogue.** Add a capability to `Permission` and to `ROLE_PERMISSIONS`; routes declare
  `Depends(require_any_permission(...))` and never inspect roles themselves.
- **Hive and telemetry data.** A harvest can cite the hive it came from (`hives.id`, `hive_code`) and
  the device that measured it; AI inputs are the labelled sensor series from `sensor_readings`.
- **Status presentation.** `constants/hive.js` holds the sensor vocabulary, units and the
  `REAL_DEVICE` / `SIMULATOR` / `MANUAL` labels; new domains add their own constants module instead of
  hardcoding strings in components.
- **Reserved namespaces.** `app/core/logging.py` already reserves the IoT, AI and blockchain logger
  namespaces; `StatusBadge` maps the device/hive statuses the later phases will reuse.
