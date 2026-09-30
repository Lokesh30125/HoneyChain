# HoneyChain — Phase 2 delivery report

**Module:** User, Role & Beekeeper Management
**Problem statement:** Smart India Hackathon 2026 — ID 26021
**Status:** delivered and verified end to end against PostgreSQL 17
**Database:** `honeychain_dev`, migration head `c71dce65bc61`

Phase 2 turns the Phase 1 shell into real identity and apiary data. It extends the existing stack,
schema and authorisation model — nothing from Phase 1 was rebuilt, and no new technology was
introduced.

---

## 1. What was delivered

| Layer | Delivered |
| --- | --- |
| **Database** | One migration (`c71dce65bc61`): `users` extended (phone, is_verified, deactivated_at, last_login_at) and seven new tables — `user_profiles`, `beekeepers`, `kvic_clusters`, `beekeeper_verification_history`, `audit_logs`, `document_sequences` (+ the `verification_status` enum). Alembic only; no manual DDL. |
| **Models / repositories / services** | `user_profile`, `beekeeper`, `kvic_cluster`, `beekeeper_verification_history`, `audit_log`, `document_sequence` models; matching repositories; `ProfileService`, `BeekeeperService`, `ClusterService`, `AuditService`, `AdminService` (extended). |
| **Authorisation** | `app/core/permissions.py`: a `Permission` catalogue + `ROLE_PERMISSIONS`, with `require_permission` / `require_any_permission` / `require_role` dependencies. Routes declare capabilities, never role names. |
| **API** | 25 new endpoints under `/api/v1`: profile, beekeepers (self + directory + verification), clusters (+ membership), admin users, audit logs, activity. OpenAPI tags: Profiles, Beekeepers, Clusters, Administration. |
| **Registration** | `POST /auth/register` limited to `CONSUMER`/`BEEKEEPER`, with an optional apiary block; creates the beekeeper record as `PENDING`. Privileged roles remain administrator-provisioned. |
| **Audit** | Every identity, profile, beekeeper, cluster and account event recorded, with secrets redacted, written inside a SAVEPOINT. |
| **Frontend** | `/profile`, `/beekeeper/profile`, `/admin/users`, `/admin/beekeepers`, `/admin/clusters`, `/admin/audit-logs`, `/kvic/beekeepers`, `/kvic/clusters`, role-based post-login redirects, role-aware sidebar, `WorkspaceHeader`, beekeeper/cluster component sets, apiary section in the registration form. |
| **Scripts** | `seed_dev_data.py` (DEVELOPMENT ONLY, idempotent, `--reset`), `backfill_beekeeper_records.py` (`--dry-run`, idempotent), `create_admin.py` (extended to KVIC_OFFICER / LAB_TECHNICIAN). |
| **Tests** | 187 pytest tests, 43 HTTP smoke checks, 27 Phase-2 browser checks, 36 Phase-1 browser checks — all green. |
| **Docs** | README §13, `docs/api.md` §5–8, `docs/database.md` §3, `run.md`, this report. |

---

## 2. Database

```
users ──1:1── user_profiles
  │
  └──1:1── beekeepers ──N:1── kvic_clusters
                 │
                 └──1:N── beekeeper_verification_history   (append-only)

audit_logs            (actor + entity + metadata, indexed by action/user/entity)
document_sequences    (scope → counter, behind every generated code)
```

Constraints and indexes that matter:

- `uq_users_phone` — phone unique **where provided** (`NULL` may repeat).
- `uq_beekeepers_user_id` — one apiary record per beekeeper; `uq_beekeepers_beekeeper_code`.
- `uq_kvic_clusters_cluster_code`; `CHECK length(cluster_name) >= 3`.
- `CHECK experience_years BETWEEN 0 AND 90`, `CHECK number_of_hives BETWEEN 0 AND 100000`,
  `CHECK pincode ~ '^[1-9][0-9]{5}$'`.
- `ix_beekeepers_district_status`, `ix_beekeepers_cluster_status`, `ix_kvic_clusters_district_active`,
  `ix_beekeeper_verification_beekeeper_changed`, `ix_audit_logs_{entity,action_created,user_created}`.
- `ON DELETE CASCADE` from user → profile / beekeeper / history; `SET NULL` for
  `beekeepers.kvic_cluster_id` and the denormalised actor columns, so history survives an account
  being removed.

**Generated codes.** `DocumentSequence.next_value(session, scope, width=5)` allocates inside the
owning transaction (row lock), so codes are race-free and gapless per scope:
`BKR-GNT-00001` for beekeepers, `KVIC-GNT-001` for clusters. District segments come from a stable
abbreviation (`GUNTUR → GNT`, `KRISHNA → KRS`, multi-word districts take initials) with `GEN` as the
fallback when no district is known.

---

## 3. API surface

| Area | Endpoints |
| --- | --- |
| Profiles | `GET`/`PUT`/`PATCH /api/v1/profile` (self only) |
| Own apiary | `GET`/`PUT /api/v1/beekeepers/me` |
| Beekeeper directory | `GET /api/v1/beekeepers` (search, district, state, cluster, verification_status, bee_species; paginated), `GET /filters`, `GET /summary`, `GET /{id}`, `PUT /{id}`, `PATCH /{id}/verification` |
| Clusters | `GET`/`POST /api/v1/clusters`, `GET`/`PUT /{id}`, `PATCH /{id}/status`, `GET /{id}/beekeepers`, `POST`/`DELETE /{id}/beekeepers/{beekeeper_id}` |
| Administration | `GET /api/v1/admin/summary`, `GET /admin/users`, `GET /admin/users/{id}`, `PATCH /admin/users/{id}/status`, `GET /admin/audit-logs`, `GET /admin/activity` |

All responses use the single envelope (`{success, data}` / `{success, error}`); lists are paginated
with `meta`. There is **no delete endpoint** for users, beekeepers or clusters — accounts are
deactivated and records retained. Cluster membership is the one removable relationship, and removing
it never touches the beekeeper record.

---

## 4. Authorisation

| Capability | ADMIN | KVIC_OFFICER | BEEKEEPER | other 7 roles |
| --- | :-: | :-: | :-: | :-: |
| `USER_READ_SELF` / `USER_UPDATE_SELF` | ✅ | ✅ | ✅ | ✅ |
| `BEEKEEPER_READ_SELF` / `BEEKEEPER_UPDATE_SELF` | — | — | ✅ | — |
| `BEEKEEPER_READ_ALL` | ✅ | ✅ | — | — |
| `BEEKEEPER_UPDATE_ALL` | ✅ | ✅ | — | — |
| `BEEKEEPER_VERIFY` | ✅ | ✅ | — | — |
| `CLUSTER_READ` | ✅ | ✅ | ✅ | — |
| `CLUSTER_MANAGE` | ✅ | ✅ | — | — |
| `USER_READ_ALL`, `ADMIN_USER_MANAGE`, `ADMIN_SYSTEM_MANAGE`, `AUDIT_READ` | ✅ | — | — | — |

Deliberate behaviours, pinned by tests:

- **A supplied role is never trusted.** `POST /auth/register {"role":"ADMIN"}` (or any of the eight
  non-public roles) returns `422`; only `CONSUMER` and `BEEKEEPER` may self-register.
- **Cluster claims are refused at registration** — `kvic_cluster_id` in the apiary block is a `422`;
  membership is granted by an officer.
- `BEEKEEPER_*_SELF` means "my own apiary record", so `/beekeepers/me` answers `403` for an
  administrator or KVIC officer rather than a confusing `404`.
- A beekeeper can never change their own `verification_status`, `beekeeper_code` or cluster.
- Denials are logged with the actor, role and missing capability, and returned with
  `required_permissions` / `your_role` in `details`.

---

## 5. Verification workflow and audit

```
PENDING ──▶ UNDER_REVIEW ──▶ VERIFIED ──▶ SUSPENDED
   ├──▶ VERIFIED                └────────▶ UNDER_REVIEW
   └──▶ REJECTED   (REJECTED ──▶ UNDER_REVIEW / PENDING)
```

- Legal transitions live in `VerificationStatus.allowed_transitions`; an illegal jump is a `422`.
- `REJECTED` and `SUSPENDED` require a remark of ≥5 characters (validated by a model validator, so a
  missing field cannot slip through).
- Each decision writes `verification_status`, `verification_remarks`, `verified_by_id`, `verified_at`,
  **appends** a `beekeeper_verification_history` row (previous → new, remarks, actor name and role,
  timestamp) and records an audit entry. The history table has no update or delete path.
- Directory rows expose `allowed_next_statuses`, so the UI only ever offers legal decisions.

Audit actions recorded: `USER_REGISTERED`, `USER_LOGIN`, `USER_LOGIN_FAILED`, `USER_LOGOUT`,
`PROFILE_UPDATED`, `BEEKEEPER_CREATED`, `BEEKEEPER_UPDATED`, `BEEKEEPER_VERIFIED`,
`BEEKEEPER_REJECTED`, `BEEKEEPER_SUSPENDED`, `USER_ACTIVATED`, `USER_DEACTIVATED`, `USER_ROLE_CHANGED`,
`CLUSTER_CREATED`, `CLUSTER_UPDATED`, `CLUSTER_STATUS_CHANGED`, `CLUSTER_MEMBER_ASSIGNED`,
`CLUSTER_MEMBER_REMOVED`.

---

## 6. Frontend

| Route | Roles | Behaviour |
| --- | --- | --- |
| `/profile` | all | Personal, location and account details; apiary extras (code, verification badge, cluster, experience, species, hives) for beekeepers |
| `/beekeeper/profile` | BEEKEEPER | Editable apiary record, read-only verification block, verification history, cluster membership |
| `/admin/users` | ADMIN | Search, role/status filters, pagination, activate/deactivate with confirmation |
| `/admin/beekeepers` | ADMIN | Filters, pagination, detail panel, verify/reject with remarks |
| `/admin/clusters` | ADMIN | Create/edit/deactivate clusters, member lists, assign/remove members |
| `/admin/audit-logs` | ADMIN | Filterable, paginated trail; states that secrets are redacted and entries immutable |
| `/kvic/beekeepers` | KVIC_OFFICER | Directory and the verification workflow |
| `/kvic/clusters` | KVIC_OFFICER | Cluster management and membership |

Cross-cutting: `ProtectedRoute` + `RoleRoute`, role-based post-login redirects, role-aware sidebar
where unbuilt modules are labelled "coming soon", loading/empty/error states everywhere, and no
placeholder number that is not derived from real data.

---

## 7. Bug found and fixed during verification

**Reported:** registration failed with the banner *"Could not create your account — Invalid request"*.

**Root cause.** Three defects compounded:

1. The client-side phone rule (`/^\+?\d{8,15}$/` after stripping spaces) was **looser than the API's**
   (10 digits, or `+` and 8–15 digits). Inputs a person actually types — `91 98765 43210`,
   `09876543210`, an 8-digit number — passed the browser, travelled to the API and came back as a
   `422`.
2. The API returns the generic message `"Invalid request"` for *any* body validation failure and puts
   the details in `error.details`; the form rendered only the generic message.
3. Apiary errors arrive as `beekeeper.experience_years`, but the inputs are registered as
   `beekeeper.experienceYears`, so those messages were attached to a non-existent field and vanished.

**Fixes.**

- The phone rule now mirrors the API exactly and reports the problem on the field
  ("Enter a 10-digit mobile number (e.g. 9876543210) or a full international number starting with +").
- `RegisterForm` translates API field paths to form paths (`experience_years → experienceYears`,
  and so on) so every message lands on its input.
- The banner names the offending fields ("Please check these fields: Phone: …") instead of showing a
  bare *Invalid request*, and `ApiError.fieldErrors` now also maps the `{field}` shape used by
  duplicate-email/phone conflicts, so those highlight the right input too.
- Validator messages are humanised (`Value error, …` stripped; raw framework phrasing rewritten).

Regression coverage: the phone case is asserted in the browser smoke test (client-side, no request
sent), and the duplicate-email case is asserted to name the field.

---

## 8. Verification evidence

| Check | Command | Result |
| --- | --- | --- |
| Backend suite | `cd backend && .venv/bin/python -m pytest` | **187 passed**, 0 failed |
| HTTP smoke (every Phase-2 endpoint) | `.venv/bin/python tests/api_smoke_phase2.py` | **43 passed**, 0 failed |
| Browser smoke, Phase 2 flows | `.venv/bin/python tests/browser_smoke_phase2.py` | **27 passed**, 0 failed |
| Browser smoke, Phase 1 regression | `.venv/bin/python tests/browser_smoke.py` | **36 passed**, 0 failed |
| Frontend build | `cd frontend && npx vite build` | ✅ built successfully |
| Frontend lint | `npx eslint src --ext .js,.jsx` | ✅ clean |
| Database state | `psql … honeychain_dev` | 6 accounts · 3 beekeepers (1 `VERIFIED`, cluster member) · 1 cluster · verification history and audit trail populated |

The browser suites drive real Chromium through the Vite proxy against the running API and PostgreSQL,
and fail on any unexpected console error. The Phase-2 suite covers: registration with the apiary
section, phone validation on the field, duplicate e-mail on the field, apiary edit persisting across a
reload, KVIC verification with remarks and history, cluster management, the administrator directories
and audit log, and consumer refusal — the acceptance criteria of this phase, exercised the way a
person would.

---

## 9. Development accounts and scripts

**DEVELOPMENT ONLY** — `python -m app.scripts.seed_dev_data` refuses to run when the environment is
production, and prints this banner when it does run:

| Email | Role | Password | Notes |
| --- | --- | --- | --- |
| `admin@honeychain.example.com` | ADMIN | `AdminSecure123` | |
| `kvic@honeychain.example.com` | KVIC_OFFICER | `KvicSecure123` | |
| `beekeeper@honeychain.example.com` | BEEKEEPER | `HoneyPass123` | `VERIFIED`, member of `KVIC-GNT-001` |
| `consumer@honeychain.example.com` | CONSUMER | `ConsumerPass123` | |

```bash
cd backend && source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

.venv/bin/python -m app.scripts.seed_dev_data              # idempotent; --reset removes the fixtures
.venv/bin/python -m app.scripts.backfill_beekeeper_records --dry-run
.venv/bin/python -m app.scripts.create_admin --email ops@example.org --name "Ops" --role ADMIN
```

---

## 10. Explicitly not built (out of scope for this phase)

Hive management · hive inspections · harvest records · IoT sensors, ESP32, MQTT · AI/ML, disease
detection, yield prediction · honey batches · laboratory workflows · blockchain and smart contracts ·
QR issuance or scanning · supply-chain events · consumer traceability · digital certificates · KVIC
analytics, scheme reporting and exports. Cluster work stops at CRUD, status and membership.

Each of those is visible in the sidebar as a planned module that says so, and the API exposes no
endpoint that would pretend otherwise.

**Next phase:** hive registry + IoT ingest (devices, sensor readings, alerts), on top of the
beekeeper records created here.
