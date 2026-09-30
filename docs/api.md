# HoneyChain API — Reference (v1)

Base URL: `/api/v1` — interactive documentation at `/docs` (Swagger) and `/redoc`
when the API is running.

> **Scope: Phases 1–3.** Authentication, profiles, beekeepers, KVIC clusters, administration
> (Phases 1–2) and the hive registry, IoT devices and telemetry (Phase 3) are implemented and
> documented below. Traceability, blockchain, QR, laboratory, AI and analytics endpoints belong to
> later phases and are listed under "Planned" so integrators know what is coming — nothing there
> exists in the codebase yet.
>
> Phase 3 has its own module reference: `docs/iot.md`.

---

## 1. Conventions

### 1.1 Response envelope

Success:

```json
{ "success": true, "data": { } }
```

Success (paginated — `meta` is added, and omitted entirely when not applicable):

```json
{
  "success": true,
  "data": [ ],
  "meta": { "page": 1, "page_size": 20, "total_items": 42, "total_pages": 3 }
}
```

Error:

```json
{
  "success": false,
  "error": { "code": "VALIDATION_ERROR", "message": "Invalid request",
             "details": [ { "field": "password", "message": "…", "type": "value_error" } ] },
  "request_id": "5ab0c271-10b2-4ea3-ac06-2be35f972cdf"
}
```

### 1.2 Headers

| Header | Direction | Notes |
| --- | --- | --- |
| `Authorization: Bearer <access_token>` | request | Required by authenticated endpoints |
| `Content-Type: application/json` | request | For JSON bodies |
| `X-Request-ID` | both | Echoed back; quote it when reporting an issue |
| `Set-Cookie: honeychain_refresh_token=…` | response | HttpOnly, `Path=/api/v1/auth`, `SameSite` from config |
| `WWW-Authenticate: Bearer` | response | Sent with every `401` |

### 1.3 Error codes

| Code | HTTP | Meaning |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 | Request failed schema validation; `details` lists fields |
| `BAD_REQUEST` | 400 | Malformed or unusable request |
| `AUTHENTICATION_ERROR` | 401 | No credentials supplied |
| `INVALID_CREDENTIALS` | 401 | Email/password combination rejected |
| `TOKEN_EXPIRED` | 401 | Token expired — sign in again |
| `TOKEN_INVALID` | 401 | Malformed, forged or revoked token |
| `PERMISSION_DENIED` | 403 | Authenticated but the role is not permitted |
| `ACCOUNT_INACTIVE` | 403 | Account deactivated by an administrator |
| `NOT_FOUND` | 404 | Resource does not exist |
| `CONFLICT` / `DUPLICATE_RESOURCE` | 409 | Uniqueness or integrity conflict |
| `DATABASE_ERROR` | 500 | Server-side database failure |
| `INTERNAL_ERROR` | 500 | Unexpected error |
| `SERVICE_UNAVAILABLE` | 503 | Dependency unavailable |
| `NOT_IMPLEMENTED` | 501 | Reserved for phase-gated features |

---

## 2. Health

### `GET /api/v1/health`

Liveness. Does not touch the database.

```bash
curl http://localhost:8000/api/v1/health
```

```json
{ "status": "ok", "service": "HoneyChain API" }
```

### `GET /api/v1/health/db`

Readiness: verifies PostgreSQL connectivity and lists applied tables.

```json
{
  "success": true,
  "data": {
    "status": "ok",
    "database": { "connected": true, "dialect": "postgresql",
                  "server_version": "17.11", "environment": "development" },
    "tables": ["alembic_version", "refresh_tokens", "users"]
  }
}
```

`status` becomes `degraded` when the database is unreachable (HTTP 200 either way, so a load
balancer can distinguish "API down" from "API up, database down").

### `GET /api/v1/health/detailed`

Per-component report.

```json
{
  "status": "ok",
  "service": "HoneyChain API",
  "version": "0.1.0",
  "environment": "development",
  "timestamp": "2026-09-22T18:30:00Z",
  "components": {
    "database": { "status": "ok", "dialect": "postgresql" },
    "authentication": { "status": "ok", "strategy": "JWT (access + rotating refresh)" },
    "blockchain": { "status": "not_configured", "phase": "Phase 3" },
    "iot": { "status": "not_configured", "phase": "Phase 4" },
    "ai": { "status": "not_configured", "phase": "Phase 5" }
  }
}
```

Future-phase components reporting `not_configured` is expected, not a fault.

---

## 3. Metadata

### `GET /api/v1/roles`

Public. The authoritative role catalogue, used by the registration form, the administration
role picker and the dashboards. All **ten** roles are listed, in the backend's declared
administration order (`UserRole.administration_order()`), with the label the API itself uses.
`self_registrable` marks the two roles a visitor may choose on the public form; everything else is
provisioned by an administrator through `POST /api/v1/admin/users`.

```json
{
  "success": true,
  "data": {
    "service": "HoneyChain API",
    "version": "0.1.0",
    "environment": "development",
    "roles": [
      { "value": "ADMIN", "label": "Administrator", "home_route": "/admin", "self_registrable": false },
      { "value": "BEEKEEPER", "label": "Beekeeper", "home_route": "/beekeeper", "self_registrable": true },
      { "value": "CONSUMER", "label": "Consumer", "home_route": "/consumer", "self_registrable": true },
      { "value": "KVIC_OFFICER", "label": "KVIC officer", "home_route": "/kvic", "self_registrable": false },
      { "value": "PROCESSOR", "label": "Processor", "home_route": "/processor", "self_registrable": false }
    ]
  }
}
```

---

## 4. Authentication

### `POST /api/v1/auth/register`

Creates an account and immediately opens a session.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string | yes | 2–120 characters |
| `email` | string (email) | yes | Stored lower-cased; unique |
| `phone` | string | no | 10-digit Indian numbers are normalised to `+91…`; unique |
| `password` | string | yes | 8–72 bytes, must contain a letter and a digit |
| `confirm_password` | string | no | Must match `password` when supplied |
| `role` | enum | no | Default `BEEKEEPER`. **Only `CONSUMER` and `BEEKEEPER` may be self-assigned**; any other role is rejected with `422` |
| `state`, `district`, `organization` | string | no | Profile context |
| `accepted_terms` | boolean | no | Default `true` |
| `beekeeper` | object | no | Apiary details — accepted only with `role: "BEEKEEPER"` (see below) |

`beekeeper` is an optional block of `village`, `mandal`, `district`, `state`, `pincode`,
`experience_years` (0–90), `bee_species` (≤80 chars) and `number_of_hives` (0–100 000). Every field
is optional: a beekeeper who would rather fill this in later still gets a record — it simply starts
empty. `beekeeper_code` and `kvic_cluster_id` are deliberately not accepted here (`422`): the code is
generated by the platform and cluster membership is granted by an officer after review.

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"name":"Lakshmi Devi","email":"lakshmi@example.com","phone":"9876543210",
       "password":"HoneyPass123","role":"BEEKEEPER","district":"Guntur"}'
```

`201 Created`:

```json
{
  "success": true,
  "data": {
    "user": {
      "id": "e02ef443-9c3b-40c6-a112-1b6c97d9eda1",
      "name": "Lakshmi Devi", "email": "lakshmi@example.com", "phone": "+919876543210",
      "role": "BEEKEEPER", "role_label": "Beekeeper", "account_status": "ACTIVE",
      "state": null, "district": "Guntur", "organization": null,
      "last_login_at": null, "created_at": "…", "updated_at": "…"
    },
    "access_token": "eyJhbGciOi…",
    "refresh_token": null,
    "token": { "token_type": "Bearer", "expires_in": 1800, "expires_at": "…" },
    "beekeeper": {
      "id": "…", "beekeeper_code": "BKR-GNT-00004", "verification_status": "PENDING",
      "verification_label": "Pending", "district": "Guntur", "kvic_cluster_id": null
    },
    "home_route": "/beekeeper"
  }
}
```

`beekeeper` is `null` for consumer registrations, and `home_route` is the workspace the client should
open for the new account.

Failures: `409 DUPLICATE_RESOURCE` (email or phone taken), `422 VALIDATION_ERROR` (weak password,
mismatched confirmation, a role that cannot be self-assigned, apiary details sent with a
non-beekeeper role, a cluster claimed at registration, or any extra field).

> `refresh_token` is `null` for browser clients — it is delivered as an HttpOnly cookie. Set
> `AUTH_EXPOSE_REFRESH_IN_BODY=true` for mobile clients, scripts and integration tests.

### `POST /api/v1/auth/login`

| Field | Type | Required |
| --- | --- | --- |
| `email` | string | yes |
| `password` | string | yes |
| `remember_me` | boolean | no |

Returns the same shape as registration. Unknown email and wrong password both return
`401 INVALID_CREDENTIALS` with an identical message, so the endpoint cannot be used to discover
which accounts exist. An inactive account returns `403 ACCOUNT_INACTIVE`.

### `POST /api/v1/auth/refresh`

Rotates the refresh token. The token is taken from the request body **or** the
`honeychain_refresh_token` cookie.

```bash
# Browser flow — cookie only, no body
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  --cookie "honeychain_refresh_token=…"
```

On success the old token is revoked, a new one is issued (`replaced_by_jti` records the chain) and a
fresh access token is returned. Presenting an already-revoked token is treated as theft: **all**
sessions for that user are revoked and `401 TOKEN_INVALID` is returned.

### `POST /api/v1/auth/logout`

| Field | Type | Notes |
| --- | --- | --- |
| `refresh_token` | string | Optional; the cookie is used when omitted |
| `all_devices` | boolean | `true` revokes every session for the user |

```json
{ "success": true, "data": { "message": "You have been signed out", "revoked_sessions": 1 } }
```

Idempotent — logging out twice is not an error. The cookie is cleared in the response.

### `GET /api/v1/auth/me`

Returns the authenticated user. Used to bootstrap the SPA session on every load.

```bash
curl http://localhost:8000/api/v1/auth/me -H "Authorization: Bearer $ACCESS_TOKEN"
```

`401 AUTHENTICATION_ERROR` (no credentials), `401 TOKEN_INVALID` (bad signature/revoked),
`403 ACCOUNT_INACTIVE` (account disabled after the token was issued).

---

## 5. Users and profiles

### `GET /api/v1/profile` · `PUT /api/v1/profile` · `PATCH /api/v1/profile`

The Phase 2 profile resource: everything the caller may see about their own account in one payload.

```json
{
  "success": true,
  "data": {
    "account":  { "id": "…", "name": "Ravi Kumar", "email": "…", "phone": "+919876500001",
                  "role": "BEEKEEPER", "is_active": true, "is_verified": false,
                  "last_login_at": "2026-09-22T19:02:22Z", "created_at": "…" },
    "profile":  { "village": "Tenali", "mandal": "Tenali", "district": "Guntur",
                  "state": "Andhra Pradesh", "pincode": "522201",
                  "profile_photo": null, "date_of_birth": null, "gender": null, "address": null },
    "beekeeper": { "beekeeper_code": "BKR-GNT-00003", "verification_status": "VERIFIED",
                   "verification_label": "Verified", "experience_years": 7,
                   "bee_species": "Apis cerana indica", "number_of_hives": 24,
                   "cluster": { "cluster_code": "KVIC-GNT-001", "cluster_name": "…" } }
  }
}
```

`beekeeper` is `null` for every non-beekeeper role. Every profile field is optional — the API never
demands personal information to hold an account. `PUT` replaces the profile, `PATCH` updates the
supplied fields; account fields (`email`, `role`, `is_active`) are administrator-controlled and are
rejected with `422` rather than ignored.

### `GET /api/v1/users/me`

Same payload as `/auth/me`; provided as a stable resource-oriented path.

### `PATCH /api/v1/users/me`

Updates the caller's own profile. `extra="forbid"`, so `role`, `email`, `is_active` in the body
produce `422` rather than being silently ignored.

```json
{ "name": "Lakshmi Devi", "district": "Krishna", "organization": "Coastal Apiaries" }
```

---

## 6. Beekeepers

### `GET /api/v1/beekeepers/me` · `PUT /api/v1/beekeepers/me`

The caller's own apiary record. `BEEKEEPER_READ_SELF` / `BEEKEEPER_UPDATE_SELF` — held by beekeepers
only, so any other role receives `403 PERMISSION_DENIED`. A beekeeper can edit practice and location
details but never their `verification_status`, `beekeeper_code` or `kvic_cluster_id` (sending one is
a `422`, not a silent no-op).

### `GET /api/v1/beekeepers`

Officer/administrator directory (`BEEKEEPER_READ_ALL`).

| Query | Notes |
| --- | --- |
| `search` | Beekeeper code, owner name or e-mail (case-insensitive) |
| `district`, `state` | Exact match |
| `cluster` | Cluster id or cluster code |
| `verification_status` | `PENDING`, `UNDER_REVIEW`, `VERIFIED`, `REJECTED`, `SUSPENDED` |
| `bee_species` | Exact match |
| `page`, `page_size` | 1-based; `page_size` 1–100 (default 20) |

Rows are `BeekeeperListItem`s: code, owner name/e-mail, location, hive count, verification status and
cluster. Full detail (owner account, history, allowed transitions) is only returned by the detail
endpoint, so a directory page never ships more data than it renders.

### `GET /api/v1/beekeepers/filters` · `GET /api/v1/beekeepers/summary`

Filter options and counts, both derived from stored rows — never invented. The summary returns
`total`, `by_verification_status`, `by_district` and `assigned_to_cluster`.

### `GET /api/v1/beekeepers/{beekeeper_id}`

Full record plus `owner`, `cluster`, `verification_history` (append-only, newest first) and
`allowed_next_statuses` — the states the workflow permits from the current one.

### `PUT /api/v1/beekeepers/{beekeeper_id}`

Officer correction (`BEEKEEPER_UPDATE_ALL`). The only way to set or clear cluster membership:
`{"kvic_cluster_id": "…"}` assigns, `{"kvic_cluster_id": null}` clears.

### `PATCH /api/v1/beekeepers/{beekeeper_id}/verification`

```json
{ "status": "VERIFIED", "remarks": "Verified after a field visit on 12 Sep." }
```

`BEEKEEPER_VERIFY` (ADMIN and KVIC_OFFICER). Enforces the transition rules
(`PENDING → UNDER_REVIEW → VERIFIED/REJECTED`, `VERIFIED → SUSPENDED`), requires a remark of at
least five characters for `REJECTED`/`SUSPENDED`, writes `verified_by`/`verified_at`, appends a
history row and records an audit entry. Illegal transitions return `422`; the response is the full
updated detail payload.

---

## 7. Clusters

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/v1/clusters` | `CLUSTER_READ` | Filters `search`, `district`, `state`, `is_active`; paginated; includes member counts |
| `POST` | `/api/v1/clusters` | `CLUSTER_MANAGE` | `cluster_code` is generated (`KVIC-GNT-001`) unless one is supplied for a migration. Optional `batch_ids` (and `reassign`) place real batches in the *same transaction* as the cluster |
| `GET` | `/api/v1/clusters/{id}` | `CLUSTER_READ` | Cluster + `member_count` + members |
| `PUT` | `/api/v1/clusters/{id}` | `CLUSTER_MANAGE` | Update name, district, state, description, coordinator |
| `PATCH` | `/api/v1/clusters/{id}/status` | `CLUSTER_MANAGE` | `{"is_active": false}` |
| `GET` | `/api/v1/clusters/{id}/beekeepers` | `CLUSTER_READ` | Members of the cluster (paginated) |
| `POST` | `/api/v1/clusters/{id}/beekeepers/{beekeeper_id}` | `CLUSTER_MANAGE` | Add membership |
| `DELETE` | `/api/v1/clusters/{id}/beekeepers/{beekeeper_id}` | `CLUSTER_MANAGE` | Remove membership — the beekeeper record is untouched |

### 7.1 Cluster views (Phase 4.1)

The five endpoints below are a **view over records that live elsewhere** — the cluster's members'
hives, their devices, the readings those devices stored and the analyses computed from them. None of
them creates a record, and none of them is available to a beekeeper (`403`).

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/v1/clusters/{id}/summary` | `CLUSTER_ANALYTICS_READ` | Member/hive/device/telemetry/AI counters plus the cluster identity; zeroes when empty |
| `GET` | `/api/v1/clusters/{id}/hives` | `CLUSTER_ANALYTICS_READ` | The cluster's hives (paginated `HiveListItem` rows), each with its device count |
| `GET` | `/api/v1/clusters/{id}/devices` | `CLUSTER_ANALYTICS_READ` | Devices attached to those hives, resolved through `hive_code` (paginated) |
| `GET` | `/api/v1/clusters/{id}/ai` | `CLUSTER_ANALYTICS_READ` | Latest stored assessment per hive: health indicator and status, disease/swarming risk, projection, data quality, `analysis_source`, `sample_count`; unanalysed hives appear as `analyzed: false` |
| `GET` | `/api/v1/clusters/{id}/telemetry/latest` | `CLUSTER_ANALYTICS_READ` | Newest stored reading plus the chain `device_id → hive_code → beekeeper_code`; `has_data: false` and a null `reading` when nothing is stored |

Related additions on the hive surface:

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/v1/hives?has_cluster=false` | hive read scope | Hives whose owner belongs to no cluster — the administrative worklist. Ignored for a beekeeper's own list. |
| `GET` | `/api/v1/hives/summary` | hive read scope | `without_cluster` (staff only) counts hives in no cluster |
| `POST` | `/api/v1/hives/{hive_id}/cluster` | staff only | `{cluster_id: uuid or null, reason ≤ 200}`. `404` unknown cluster, `422` inactive cluster / already in that cluster / clearing an unclustered hive, `403` for a beekeeper. Audited with the previous and new cluster |

`cluster_id` inside a hive create/update payload, or inside a device registration payload, is
rejected `422` — the relationship is never set by a client that way.

### 7.2 The cluster's honey batches (Prompt 10)

A cluster *holds* honey batches. The relationship is the one column that already existed —
`honey_batches.cluster_id` — written from the cluster screen and read back by the beekeeper, the
processor, the laboratory, the packager, the distributor and the QR trace. Nothing is copied into the
cluster, and no hive is assigned here: a batch already carries its harvest, its beekeeper and the
hives behind it.

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/v1/clusters/{id}/batches` | `CLUSTER_ANALYTICS_READ` | The batches this cluster holds (paginated `BatchListItem`), with processing / laboratory / packaging / distribution statuses |
| `GET` | `/api/v1/clusters/{id}/batch-candidates` | `CLUSTER_ANALYTICS_READ` | Real batches the caller may read, for the *Add batches* picker. `assignment=any\|unassigned\|this_cluster\|other_cluster`; each row carries `placement`, `placement_label` and `requires_confirmation` |
| `POST` | `/api/v1/clusters/{id}/batches` | `CLUSTER_MANAGE` | `{batch_ids: [uuid], reassign: bool}`. Writes the batch's own cluster link (and its harvest's). A batch in another cluster → `409 CONFLICT` with `details.requires_reassign` and `details.batches`; `reassign: true` moves it deliberately. Already-here batches are reported as `already`, never duplicated |
| `DELETE` | `/api/v1/clusters/{id}/batches/{batch_id}` | `CLUSTER_MANAGE` | Ends the cluster link on that batch (and on its harvest when the harvest names this cluster). The batch and every other record are untouched |
| `GET` | `/api/v1/clusters/{id}/batch-analytics` | `CLUSTER_ANALYTICS_READ` | Counted from the cluster's own batch rows: `totals` (batches, collections, beekeepers represented, hives behind them, packages, quantities, unit), `status_breakdown` (collection → processing → laboratory → packaging → distribution → delivered), `by_status`, and the `processing` / `laboratory` / `packaging` / `distribution` counters |

Batches are never created, edited or deleted here — they are produced by completing a harvest. These
endpoints place and remove the *link*, and each write is audited
(`CLUSTER_BATCHES_ASSIGNED`, `CLUSTER_BATCH_DETACHED`).

`GET /api/v1/batches` gained `unclustered=true` (the batches that name no cluster) for the picker and
the repair worklist; the filter is applied in the database, before pagination.

Cluster management otherwise stops at CRUD, membership and batch placement: scheme reporting and
exports belong to a later phase and are not exposed.

---

## 8. Administration (`ADMIN` only)

All routes below require an access token whose role is `ADMIN`; other roles receive
`403 PERMISSION_DENIED` with the required role listed in `details`.

### `GET /api/v1/admin/summary`

```json
{
  "success": true,
  "data": {
    "users": {
      "total": 12, "active": 11,
      "by_role": { "ADMIN": 1, "BEEKEEPER": 6, "COLLECTION_CENTER": 1, "PROCESSOR": 1,
                   "LAB_TECHNICIAN": 0, "PACKAGING_UNIT": 1, "DISTRIBUTOR": 1,
                   "RETAILER": 1, "CONSUMER": 0, "KVIC_OFFICER": 0 }
    },
    "modules": { "user_management": "available", "beekeeping": "available",
                 "hives": "available", "iot": "available", "ai": "planned",
                 "blockchain": "planned", "supply_chain": "planned" }
  }
}
```

### `GET /api/v1/admin/users`

| Query | Default | Notes |
| --- | --- | --- |
| `page` | 1 | 1-based |
| `page_size` | 20 | 1–100 |
| `role` | — | Any role value; unknown values give `422` |
| `is_active` | — | `true` / `false` |

Newest first. Pagination metadata in `meta`.

### `POST /api/v1/admin/users`

Provisions an account for **any of the ten roles** — the administrator's counterpart to public
registration, using the same `users` table, the same bcrypt hashing and the same
`POST /api/v1/auth/login`. Requires `ADMIN_USER_MANAGE` **and** `ADMIN_ROLE_ASSIGN`
(administrators only), enforced on the route and again in the service.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string | yes | 2–120 characters |
| `email` | string (email) | yes | Unique |
| `phone` | string | no | Normalised like registration; unique |
| `password` | string | yes | Same policy as registration: 8–72 bytes, a letter and a digit |
| `role` | enum | yes | Any of the ten: `ADMIN`, `BEEKEEPER`, `CONSUMER`, `KVIC_OFFICER`, `COLLECTION_CENTER`, `PROCESSOR`, `LAB_TECHNICIAN`, `PACKAGING_UNIT`, `DISTRIBUTOR`, `RETAILER` |
| `is_active` | boolean | no | Default `true`. `false` creates the account disabled, to be activated later |
| `state`, `district`, `organization` | string | no | Profile context |
| `reason` | string | no | Recorded in the audit log |
| `beekeeper` | object | no | Apiary details — accepted only with `role: "BEEKEEPER"` |

```json
{
  "success": true,
  "data": {
    "user": { "id": "…", "email": "sita.rao@honeychain.example.com", "role": "LAB_TECHNICIAN",
              "role_label": "Lab technician", "is_active": true },
    "message": "Account created as Lab technician",
    "beekeeper_created": false
  }
}
```

A `BEEKEEPER` account is created together with its beekeeper record in the same transaction, and that
record starts `PENDING` — provisioning an account is not a verification. `409 DUPLICATE_RESOURCE` for
an email or phone already in use; `422` for a weak password, an unknown role, or apiary details
supplied with a non-beekeeper role. Audited as `USER_PROVISIONED`.

### `PATCH /api/v1/admin/users/{user_id}/role`

```json
{ "role": "PROCESSOR", "reason": "Moved to the Guntur plant" }
```

Requires `ADMIN_ROLE_ASSIGN`. Returns the account, the `previous_role` and `sessions_revoked`.

Refused with `422` when the caller is changing **their own** role, and when the target is the last
active administrator being moved off `ADMIN`. Live refresh tokens are revoked, because the account's
permissions change the moment the role does. Audited as `USER_ROLE_CHANGED` with both the previous
and the new role; promoting an account to `BEEKEEPER` creates its missing apiary record.

### `PATCH /api/v1/admin/users/{user_id}/status`

```json
{ "is_active": false, "reason": "Duplicate registration" }
```

`404 NOT_FOUND` for an unknown id, `422` for a malformed UUID. Deactivating a user immediately
blocks their `/auth/me` calls with `403 ACCOUNT_INACTIVE` and prevents further sign-ins, and an
administrator cannot deactivate their own account (`422`).

### `GET /api/v1/admin/users/{user_id}`

Account detail plus the beekeeper record (when the account is a beekeeper) and the account's recent
audit activity.

### `GET /api/v1/admin/audit-logs`

| Query | Notes |
| --- | --- |
| `action` | Exact action code, case-insensitive (`USER_REGISTERED`, `BEEKEEPER_VERIFIED`, …) |
| `entity_type`, `entity_id` | Narrow to one record's history |
| `user_id` | One actor's trail |
| `page`, `page_size` | Paginated |

Entries carry `action`, `entity_type`, `entity_id`, `metadata`, `description`, `ip_address` and
`created_at`. Metadata is validated on write and never contains passwords, tokens or secrets, and no
endpoint can edit or delete an entry.

### `GET /api/v1/admin/activity`

Counts by action over a rolling window (`window_hours`, default 24) for the administration dashboard.

---

## 9. Hives

Permissions: `HIVE_READ_SELF` / `HIVE_WRITE_SELF` (beekeepers, own apiary) and
`HIVE_READ_ALL` / `HIVE_WRITE_ALL` (KVIC officers and admins, platform-wide).

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/v1/hives` | Filters `status`, `search`, `district`, `state`, `bee_species`, `colony_strength`, `cluster_id`, `beekeeper_id`, `has_device`, `include_removed`; paginated. Each row carries `cluster`, `device_count`, `primary_device` and `latest_reading` |
| `GET` | `/api/v1/hives/summary` | `{"total", "by_status", "with_device", "without_device"}` |
| `GET` | `/api/v1/hives/filters` | District/bee-species/status values present in scope, for filter dropdowns |
| `POST` | `/api/v1/hives` | Create. The `hive_code` is generated server-side (`HIVE-<DISTRICT>-NNNNN`) and cannot be supplied |
| `GET` | `/api/v1/hives/{hive_id}` | Detail: `owner`, `devices` (each with its derived `status`), `sensor_values`, `latest_reading` |
| `PUT` | `/api/v1/hives/{hive_id}` | Update apiary location, species, colony/queen observations, notes |
| `PATCH` | `/api/v1/hives/{hive_id}/status` | `{"status": "ACTIVE", "reason": "…"}` — `ACTIVE`, `INACTIVE`, `MAINTENANCE`, `REMOVED` |
| `DELETE` | `/api/v1/hives/{hive_id}?force=` | `409` with device/reading counts while history exists; `force=true` marks it `REMOVED` instead of deleting |
| `GET` | `/api/v1/beekeepers/me/hives` | The signed-in beekeeper's own hives (no id required) |

Colony strength and queen status are the beekeeper's *observations* (`UNKNOWN` until they assess);
the platform never derives them.

```json
{
  "success": true,
  "data": {
    "hive_code": "HIVE-GNT-00001", "status": "ACTIVE", "colony_strength": "STRONG",
    "queen_status": "PRESENT", "district": "Guntur", "state": "Andhra Pradesh",
    "device_count": 1, "primary_device": { "device_id": "ESP32-GNT-0001", "status": "ONLINE" },
    "latest_reading": { "timestamp": "2026-09-23T12:54:17Z", "temperature": 30.9,
                        "humidity": 52.98, "weight": 42.79, "source": "SIMULATOR" }
  }
}
```

---

## 10. IoT devices and sensors

Permissions: `DEVICE_READ_SELF` / `DEVICE_WRITE_SELF` for a beekeeper's own devices,
`DEVICE_READ_ALL` / `DEVICE_WRITE_ALL` for KVIC and admin. Authorisation is enforced in the service
layer: a cross-owner read answers `404` (the record is not confirmed to exist) and a cross-owner
telemetry write answers `403`.

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/v1/iot/devices` | Filters `search`, `status`, `hive_id`, `beekeeper_id`, `device_type`, `connection_type`; paginated. Rows include `sensors`, `last_reading` and derived `status` |
| `GET` | `/api/v1/iot/devices/summary` | Fleet counters for the monitoring screen: `total_devices`, `connected_devices`, `offline_devices`, `warning_devices`, `maintenance_devices`, `sensors_active`, `hives_without_device`, `readings_last_window`, `offline_threshold_seconds`, `last_telemetry_at` |
| `POST` | `/api/v1/iot/devices` | Register against one of your hives. Seeds the five sensor configurations. `422` on a duplicate `device_id` (case-insensitive) |
| `POST` | `/api/v1/iot/devices/heartbeat` | `{"device_id": "…"}` — reachability without a reading; marks the device `ONLINE` |
| `GET` | `/api/v1/iot/devices/{device_id}` | Detail with `sensors`, `last_reading`, `seconds_since_last_seen` |
| `PUT` | `/api/v1/iot/devices/{device_id}` | Name, firmware version, connection type, install date, MQTT topic |
| `PATCH` | `/api/v1/iot/devices/{device_id}/status` | `ONLINE`, `OFFLINE`, `WARNING` honour the derived value (a manual `OFFLINE` clears on the next packet); `MAINTENANCE` is sticky |
| `DELETE` | `/api/v1/iot/devices/{device_id}?confirm=` | `409` with the reading count while telemetry exists; `?confirm=true` deletes the device and its readings |
| `GET` | `/api/v1/iot/devices/{device_id}/sensors` | The device's sensor configuration |
| `PATCH` | `/api/v1/iot/devices/{device_id}/sensors/{sensor_type}` | Any of `enabled`, `sensor_name`, `unit`, `sampling_interval` (1–86400 s), `min_valid_value`, `max_valid_value` — e.g. `{"enabled": true, "sensor_name": "Brood temperature", "max_valid_value": 45}` |
| `GET` | `/api/v1/iot/me/devices` | Every device the caller owns |

Device registration body:

```json
{
  "device_id": "ESP32-GNT-0001",
  "device_name": "Guntur apiary node A",
  "hive_id": "3f1c…",
  "device_type": "ESP32",
  "connection_type": "MQTT",
  "firmware_version": "1.0.0",
  "installed_at": "2026-09-01T09:00:00Z"
}
```

---

## 11. Telemetry

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/api/v1/iot/telemetry` | One reading. `telemetry_ingest` permission on your own device |
| `POST` | `/api/v1/iot/telemetry/batch` | 1–200 readings (bare JSON array); the response reports `submitted`, `stored`, `duplicates`, `rejected_count`, `rejected[{index, reason}]` |
| `GET` | `/api/v1/iot/telemetry/{hive_id}` | Stored history for a hive. `range` (`1h`, `6h`, `24h`, `7d`, `30d`) or an explicit `from`/`to`; `interval` (`1m`, `5m`, `15m`, `30m`, `1h`, `6h`, `1d`) returns averaged buckets instead of raw points; also `sensor_type`, `device_id` (`device_pk`) and `limit` (≤ 2000). The response carries `points`, `latest`, `source_mix` and a `message` when the window is empty |
| `GET` | `/api/v1/iot/telemetry/{hive_id}/latest` | Newest values per device on the hive |
| `GET` | `/api/v1/iot/last-telemetry` | Most recent reading in scope; always returns a body, with `has_data: false` when the scope is empty |
| `GET` | `/api/v1/health/mqtt` | Consumer status (`connected` / `disconnected` / `stopped` / `not_configured`), topic, counters and `last_error` |

```json
// POST /api/v1/iot/telemetry
{
  "device_id": "ESP32-GNT-0001",
  "timestamp": "2026-09-23T12:54:17Z",
  "temperature": 30.9, "humidity": 52.98, "weight": 42.79,
  "vibration": 0.43, "acoustic_level": 38.65,
  "battery_level": 94, "signal_strength": -63,
  "source": "SIMULATOR"
}
```

Rules: at least one measurement is required; unknown fields are `422`; values outside the
data-validity ranges are rejected with the field named in `details` and are **never clamped**;
`(device_id, timestamp)` is idempotent, so a replay is reported as `duplicate`. The server decides
the effective `source`: `SIMULATOR` when declared, `MANUAL` for an authenticated HTTP submission
otherwise, and `REAL_DEVICE` for an unlabelled packet arriving over MQTT.

Full contract, ranges, MQTT topics and the hardware hand-off: `docs/iot.md`.

---

## 12. Blockchain traceability (Phase 8)

The traceability layer is an integration, not a second database. Every supply-chain transition
HoneyChain performs records one **event** (its own row, `blockchain_events`, written in the same
transaction as the record it describes) and a background outbox submits those events to the
existing service at `BLOCKCHAIN_BASE_URL` (`POST {BASE_URL}/transactions`). The database stays the
operational source of truth; the chain holds the summary of what happened.

| Method | Endpoint | Who | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/blockchain/transactions` | `BLOCKCHAIN_READ` (ADMIN, KVIC_OFFICER) | The ledger, newest first. Filters: `tx_type`, `status`, `batch_code`, `search` (event id / batch code / transaction id), `date_from`, `date_to`, `page`, `page_size`. An officer's answer contains their clusters' events only. |
| `GET` | `/api/v1/blockchain/transactions/{event_id}` | `BLOCKCHAIN_READ` | One event in full: payload, chain status, attempt count, `last_error`, the record it describes. |
| `GET` | `/api/v1/blockchain/ledger` | `BLOCKCHAIN_READ` | The **service's own** ledger (`GET {BASE_URL}/transactions`), including transactions recorded before HoneyChain wrote any. Each row carries `honey_chain_recorded` and, where matched, `matched_event_id`; legacy rows are shown here and never attached to a batch. |
| `GET` | `/api/v1/blockchain/health` | `BLOCKCHAIN_READ` | Reachability, latency, the service's ledger size and timestamp, and HoneyChain's own outbox (pending / submitted / confirmed / failed / skipped, last confirmation). The service's **address is never returned** — it is server-side configuration. |
| `POST` | `/api/v1/blockchain/sync` | `BLOCKCHAIN_SYNC` (ADMIN) | Submit everything outstanding now, instead of waiting for the worker. Answers `{submitted, confirmed, failed, skipped, outstanding, enabled}`. One call is bounded by `BLOCKCHAIN_OUTBOX_BATCH_SIZE`. |
| `POST` | `/api/v1/blockchain/transactions/{event_id}/retry` | `BLOCKCHAIN_SYNC` | Submit one `FAILED` event again. Audited (`BLOCKCHAIN_RETRY`). |
| `GET` | `/api/v1/blockchain/batches/{batch_id}` | batch read permissions | A batch's own events with their chain status, its package rows (with `qr_issued` and `qr_id`) and the chronological timeline of the stages that happened. This is what the batch screens' **Blockchain traceability** section reads. |
| `GET` | `/api/v1/blockchain/packages/{package_id}/qr` | `PACKAGING_READ` | The package's QR identity: `qr_id`, `qr_payload`, `event_id`, `svg`, scan count, and the transaction ids once confirmed. |
| `POST` | `/api/v1/blockchain/packages/{package_id}/qr` | `PACKAGING_READ` | Issue the QR identity. Idempotent: a package that already has one gets the same `qr_id` and `qr_payload` back and no second event is written. |
| `GET` | `/api/v1/trace/{package_code}` | **anonymous** | The customer's page: product, source, processing, laboratory, packaging, distribution, retailer and the chronological ledger of this package. Opening it records **one** `CUSTOMER_QR_VERIFIED` event per package (`qr_scan_count` counts the rest), and it exposes no account data, notes, telemetry or internal identifiers. |
| `GET` | `/api/v1/verify/{code}` | **anonymous** | The same answer, reached by the QR id printed beside the code (`QR-HC-PKG-…`) as well as by the package code. `GET /trace/{qr_id}` works too — the QR id *is* the package code with a `QR-` prefix, resolved server-side, so a label and a link can never disagree. The report's `processing[].facility` is the processing unit the run happened at and `packaging.facility` is the packing unit; both are read from the record, and a stage that has not happened is listed with `reached: false` rather than omitted or shown as done. |
| `GET` | `/api/v1/trace/{package_code}/qr.svg` | **anonymous** | The label itself, drawn from the stored payload. |

Also on `/api/v1/health/detailed`: the `blockchain` component reports the real outbox
(`events_recorded`, `pending`, `submitted`, `confirmed`, `failed`, `skipped`,
`last_confirmed_at`, `last_confirmed_tx_id`) and `ok` / `degraded` / `disabled`. That endpoint is
unauthenticated, so it carries counters only — never the service URL.

**Statuses.** `PENDING` → `SUBMITTED` → `CONFIRMED`, with `FAILED` (the attempt was made and
refused or the service could not be reached) and `SKIPPED` (the integration is switched off; the
event is recorded in HoneyChain and is not on the chain). No screen reports a record as on the
chain unless its status is `CONFIRMED` and a `tx_id` exists.

**Idempotency.** Every event carries a deterministic `event_id` (for example
`PACKAGE-HC-PKG-2026-000001-CREATED`, `DIST-HC-DIST-2026-000004-DELIVERED`, or a content hash where
the record is one of many) with a unique constraint on it. A double click, a refresh, an API retry,
a network timeout, a backend restart or a second browser tab therefore produce one row and one
transaction: submission finds the confirmed event and reuses its `tx_id` instead of POSTing again.

*Example — one event as the ledger returns it*

```json
{
  "event_id": "DIST-HC-DIST-2026-000004-DELIVERED",
  "tx_type": "DELIVERED",
  "tx_id": "9f0c…6b21",
  "status": "CONFIRMED",
  "batch_code": "HC-BATCH-2026-000005",
  "payload": {
    "distribution_code": "HC-DIST-2026-000004",
    "package_code": "HC-PKG-2026-000005",
    "retailer_id": "5f0c…",
    "received_at": "2026-09-29T18:31:12Z",
    "status": "DELIVERED"
  },
  "created_at": "2026-09-29T18:31:12Z",
  "confirmed_at": "2026-09-29T18:31:14Z"
}
```

Command line equivalent for operators: `python scripts/blocksync.py status|pending|failed|sync|retry <event_id>`.

---

## 13. Planned endpoints (later phases)

Listed so integrators can plan; **not implemented yet**.

| Phase | Endpoint (indicative) | Purpose |
| --- | --- | --- |
| 4 | `POST /beekeeping/harvests`, `GET /beekeeping/harvests` | Harvest records linked to hives — **delivered** (Phases 5–7) as `/collections*` |
| 4 | `POST /batches`, `GET /batches/{id}/timeline`, `POST /batches/{id}/events` | Batch lineage — **delivered** as `/batches*` (no client-supplied statuses) |
| 4 | `GET /trace/{qr_code}` | Public consumer verification — **delivered** in Phase 8 as `/trace/{package_code}` and `/verify/{code}` |
| 4 | `POST /laboratory/tests`, `GET /laboratory/samples` | Quality test workflow — **delivered** (Phase 6) as `/lab-tests*` |
| 4 | `POST /blockchain/anchor`, `GET /blockchain/verify/{hash}` | **Delivered differently, and deliberately**: anchoring is the event outbox described in section 12 — the transaction is written when the state changes, not in a separate anchoring batch |
| 5 | `GET /ai/hives/{id}/risk`, `GET /ai/harvest-forecast` | Advisory risk signals and forecasts |
| 6 | `GET /kvic/analytics/export`, `GET /kvic/schemes` | Cluster analytics, scheme reporting and exports |

All will follow the same envelope, pagination, error-code and RBAC conventions documented above.
