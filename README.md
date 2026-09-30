# HoneyChain

**Blockchain-based honey traceability and smart beekeeping management system**

Reference implementation for **Smart India Hackathon 2026 — Problem Statement ID 26021**.

---

## Table of contents

1. [Project overview](#1-project-overview)
2. [Problem statement](#2-problem-statement)
3. [Architecture](#3-architecture)
4. [Technology stack](#4-technology-stack)
5. [Folder structure](#5-folder-structure)
6. [Environment setup](#6-environment-setup)
7. [Frontend setup](#7-frontend-setup)
8. [Backend setup](#8-backend-setup)
9. [Database setup](#9-database-setup)
10. [Running the application](#10-running-the-application)
11. [API health check](#11-api-health-check)
12. [Authentication flow](#12-authentication-flow)
13. [Phase 2 — users, roles, profiles & beekeepers](#13-phase-2--users-roles-profiles--beekeepers)
14. [Phase 3 — hive registry & smart-hive IoT](#14-phase-3--hive-registry--smart-hive-iot)
15. [Phase 4 — AI-powered hive health insights](#15-phase-4--ai-powered-hive-health-insights)
16. [Phase 4.1 — the organisational relationship](#16-phase-41--the-organisational-relationship)
17. [Testing](#17-testing)
18. [Development roadmap](#18-development-roadmap)
19. [Engineering conventions](#19-engineering-conventions)

---

## 1. Project overview

HoneyChain connects every participant in the honey value chain — beekeeper, collection centre,
processor, laboratory, packaging unit, distributor, retailer, consumer, KVIC cluster and platform
administrator — on **one shared, verifiable batch record**.

The platform combines four capabilities that are usually separate products:

| Capability | Purpose |
| --- | --- |
| **Supply-chain traceability** | One batch identity followed from harvest to retail shelf |
| **Smart beekeeping** | Hive-level monitoring, inspections and decision support for beekeepers |
| **Blockchain anchoring** | Tamper-evident records of each supply-chain event |
| **QR verification** | Consumer-facing verification of a jar's recorded journey |

> **Current status — Phases 1–3 delivered.**
> The platform currently provides: authentication and the ten-role model; profiles, the beekeeper
> registry and KVIC clusters with a verification workflow and audit trail (Phase 2); and the hive
> registry with bound IoT devices, sensor configuration, telemetry ingest over HTTP and MQTT, device
> health and monitoring dashboards (Phase 3). Harvest records, batch traceability, QR verification,
> blockchain anchoring, laboratory workflows, alerts and AI insights are **not implemented yet** and
> belong to later phases — see the [roadmap](#16-development-roadmap) and
> [`docs/development-roadmap.md`](docs/development-roadmap.md). No screen in the application
> simulates a feature that does not exist, and every sensor reading is labelled `REAL_DEVICE`,
> `SIMULATOR` or `MANUAL`.
>
> Verification records: [`docs/phase-2-report.md`](docs/phase-2-report.md),
> [`docs/phase-3-report.md`](docs/phase-3-report.md),
> [`docs/phase-4-1-report.md`](docs/phase-4-1-report.md),
> [`docs/phase-5-report.md`](docs/phase-5-report.md),
> [`docs/phase-6-report.md`](docs/phase-6-report.md) and
> [`docs/phase-6-role-workspaces-report.md`](docs/phase-6-role-workspaces-report.md);
> IoT module reference: [`docs/iot.md`](docs/iot.md).

---

## 2. Problem statement

**Problem Statement ID:** 26021
**Title:** Honey Chain — A blockchain-based system for honey traceability and smart beekeeping management.

The system is designed to address:

- Counterfeit and adulterated honey
- Low consumer trust
- Poor honey traceability
- Weak market linkages
- Lack of advanced hive monitoring
- Disease detection challenges
- Poor colony health monitoring
- Productivity optimisation
- Rural beekeeper support
- Scalable deployment across beekeeping clusters

---

## 3. Architecture

### 3.1 Layered backend

The backend enforces a strict separation of concerns. A request flows in one direction:

```text
HTTP request
    │
    ▼
Route (app/routes)              validates input via Pydantic, delegates, serialises
    │                           — contains no business rules, no SQL
    ▼
Service (app/services)          business logic, authorisation decisions,
    │                           transaction boundaries (commit/rollback)
    ▼
Repository (app/repositories)   the ONLY layer that builds SQLAlchemy queries
    │
    ▼
Model (app/models)              ORM entities → PostgreSQL
```

Cross-cutting concerns are shared, not duplicated:

```text
app/core/config.py      typed settings from environment variables
app/core/security.py    password hashing + JWT creation/verification
app/core/database.py    engine, session factory, FastAPI DB dependency
app/core/logging.py     structured logs with request-id correlation + redaction
app/core/exceptions.py  domain errors and the canonical error-code vocabulary
app/api/dependencies.py auth dependencies (get_current_user, requires_roles…)
app/main.py             app factory, CORS, middleware, global exception handlers
```

Adding a module in a later phase means adding a router, a service, a repository and models — and
registering the router in `app/api/router.py`. Nothing else changes.

### 3.2 Request lifecycle

```text
Browser
  │  relative /api/v1/... requests (same origin)
  ▼
Vite dev server (5173) ──proxy──▶ FastAPI (8000) ──SQLAlchemy──▶ PostgreSQL (5432)
```

In development the SPA talks to its own origin and Vite proxies `/api` to the backend. This keeps
the HttpOnly refresh cookie first-party and removes CORS from the development loop; the API's CORS
allow-list is still configured for deployments where the frontend is served from a different host.

### 3.3 Frontend layering

```text
pages/            screen composition — no HTTP, no business rules
components/       presentation (ui primitives, common patterns, layout, forms, landing)
hooks/            reusable stateful logic (useAuth, useApiHealth, useToast)
context/          the only global state: session (AuthContext) and toasts
services/         all HTTP access; components never call axios directly
utils/            error normalisation and Zod validation schemas
constants/        roles, navigation, endpoints, error codes — no magic strings in components
```

---

## 4. Technology stack

### Frontend

| Concern | Choice |
| --- | --- |
| Framework | React 18 + Vite 6 (**JavaScript**, not TypeScript) |
| Styling | Tailwind CSS 3 with a custom honey/forest design token set |
| Routing | React Router 6 |
| HTTP | Axios (single instance, envelope unwrapping, single-flight token refresh) |
| Charts | Recharts |
| Icons | Lucide React |
| Forms | React Hook Form + Zod (`@hookform/resolvers`) |
| Animation | Framer Motion (subtle, respects `prefers-reduced-motion`) |

### Backend

| Concern | Choice |
| --- | --- |
| Framework | FastAPI |
| Validation | Pydantic v2 + pydantic-settings |
| ORM | SQLAlchemy 2.0 (declarative, typed `Mapped[...]` columns) |
| Database | PostgreSQL 15+ via `psycopg` 3 |
| Migrations | Alembic |
| Auth | JWT (PyJWT): short-lived access token + rotating refresh token |
| Passwords | bcrypt via passlib (cost 12) |
| Logging | Structured JSON (or readable console) with request-id correlation |
| Server | Uvicorn |
| Tests | pytest + httpx/TestClient |

---

## 5. Folder structure

```text
HoneyChain/
├── frontend/
│   ├── public/
│   │   └── favicon.svg
│   ├── src/
│   │   ├── assets/
│   │   ├── components/
│   │   │   ├── common/          StatCard, DataTable, EmptyState, ErrorState, Modal,
│   │   │   │                    ConfirmDialog, StatusBadge, PageHeader, Breadcrumb,
│   │   │   │                    LoadingState, Toaster, ErrorBoundary, ForbiddenState, Logo,
│   │   │   │                    WorkspaceHeader, PlannedModuleNotice, SectionHeading
│   │   │   ├── beekeepers/      BeekeeperDirectory, BeekeeperDetailModal,
│   │   │   │                    VerificationBadge, VerificationDialog
│   │   │   ├── clusters/        ClusterManagement, ClusterFormModal, ClusterMembersModal
│   │   │   ├── forms/           LoginForm, RegisterForm (apiary section for BEEKEEPER)
│   │   │   ├── landing/         HeroSection, ChainFlow, LandingSections (10 sections)
│   │   │   ├── layout/          PublicHeader/Footer, PublicLayout, AuthLayout,
│   │   │   │                    DashboardLayout, Sidebar, Topbar
│   │   │   └── ui/              Button, Input, Select, Card, Badge, Alert, Modal, Spinner
│   │   ├── constants/           api.js, roles.js, navigation.js, plannedModules.js
│   │   ├── context/             AuthContext, ToastContext
│   │   ├── hooks/               useAuth, useApiHealth, useToast
│   │   ├── pages/
│   │   │   ├── public/          Landing, HowItWorks, About, Contact, NotFound
│   │   │   ├── auth/            Login, Register
│   │   │   ├── dashboard/       DashboardPage (shell for the remaining roles)
│   │   │   ├── profile/         ProfilePage            (Personal, Location, Account)
│   │   │   ├── beekeeper/       BeekeeperDashboardPage, BeekeeperProfilePage
│   │   │   ├── admin/           AdminDashboardPage, AdminUsersPage, AdminBeekeepersPage,
│   │   │   │                    AdminClustersPage, AuditLogsPage
│   │   │   ├── kvic/            KvicDashboardPage, KvicBeekeepersPage, KvicClustersPage
│   │   │   ├── placeholders/    ComingSoonPage (planned module notice)
│   │   │   ├── supply-chain/    SupplyChainDashboardPage (later phase shell)
│   │   │   ├── laboratory/      LaboratoryDashboardPage  (later phase shell)
│   │   │   └── consumer/        ConsumerDashboardPage    (later phase shell)
│   │   ├── routes/              AppRoutes, ProtectedRoute, RoleRoute
│   │   ├── services/            apiClient, authService, profileService, beekeeperService,
│   │   │                        clusterService, adminService, systemService, storage
│   │   ├── utils/               errors.js, validation.js, format.js
│   │   ├── App.jsx
│   │   ├── index.css
│   │   └── main.jsx
│   ├── .env.example
│   ├── index.html
│   ├── package.json
│   ├── postcss.config.js
│   ├── tailwind.config.js
│   └── vite.config.js
│
├── backend/
│   ├── alembic/
│   │   ├── versions/            20260922_1815_37a03aa5a040_initial_auth_foundation.py
│   │   │                        20260922_1850_c71dce65bc61_phase_2_profiles_beekeepers_clusters_.py
│   │   ├── env.py
│   │   └── script.py.mako
│   ├── app/
│   │   ├── api/                 dependencies.py (auth deps), router.py (v1 router)
│   │   ├── core/                config.py, security.py, database.py, logging.py, exceptions.py,
│   │   │                        permissions.py (Permission catalogue + RBAC dependencies)
│   │   ├── middleware/          request_context.py
│   │   ├── models/              base.py, enums.py, user.py, user_profile.py, beekeeper.py,
│   │   │                        kvic_cluster.py, beekeeper_verification_history.py,
│   │   │                        audit_log.py, document_sequence.py, refresh_token.py
│   │   ├── repositories/        base.py, user_repository.py, profile_repository.py,
│   │   │                        beekeeper_repository.py, cluster_repository.py,
│   │   │                        audit_repository.py, token_repository.py
│   │   ├── routes/              health.py, auth.py, users.py, profile.py, beekeepers.py,
│   │   │                        clusters.py, admin.py, meta.py
│   │   ├── schemas/             common.py, auth.py, user.py, roles.py, profile.py,
│   │   │                        beekeeper.py, cluster.py, admin.py, audit.py
│   │   ├── services/            auth_service.py, user_service.py, profile_service.py,
│   │   │                        beekeeper_service.py, cluster_service.py, audit_service.py,
│   │   │                        admin_service.py
│   │   ├── scripts/             create_admin.py, seed_dev_data.py, backfill_beekeeper_records.py
│   │   ├── utils/
│   │   └── main.py
│   ├── tests/                   conftest.py + 11 test modules (187 tests),
│   │                            api_smoke_phase2.py, browser_smoke.py, browser_smoke_phase2.py
│   ├── .env.example / .env.development.example / .env.production.example
│   ├── alembic.ini
│   ├── pytest.ini
│   └── requirements.txt
│
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── database.md
│   ├── development-roadmap.md
│   ├── iot.md
│   ├── phase-2-report.md
│   ├── phase-3-report.md
│   ├── phase-4-1-report.md
│   ├── phase-5-report.md
│   ├── phase-6-report.md
│   ├── phase-6-role-workspaces-report.md
│   └── screenshots/
│
├── .env.example
├── .gitignore
└── README.md
```

---

## 5.1 Visual tour

| Landing page | Blockchain traceability |
| --- | --- |
| ![Landing page](docs/screenshots/01-landing-hero.png) | ![Traceability](docs/screenshots/02-blockchain-traceability.png) |

| Registration | Sign in |
| --- | --- |
| ![Registration](docs/screenshots/03-registration.png) | ![Sign in](docs/screenshots/04-sign-in.png) |

| Administrator workspace (live data) | Dashboard shell |
| --- | --- |
| ![Admin workspace](docs/screenshots/05-admin-workspace.png) | ![Dashboard](docs/screenshots/06-dashboard.png) |

| Mobile — landing | Mobile — registration |
| --- | --- |
| ![Mobile landing](docs/screenshots/07-mobile-landing.png) | ![Mobile registration](docs/screenshots/08-mobile-registration.png) |

---

## 6. Environment setup

**Prerequisites**

| Tool | Version | Check |
| --- | --- | --- |
| Python | 3.11+ | `python3 --version` |
| Node.js | 18.18+ | `node --version` |
| PostgreSQL | 15+ | `psql --version` |

Each side has its own environment file. Both `.env` files are git-ignored; only the templates are
committed.

```bash
cp .env.example .env                            # optional shared defaults
cp backend/.env.example backend/.env            # API configuration
cp frontend/.env.example frontend/.env          # client configuration
```

Generate a real JWT secret (never reuse the placeholder):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Backend configuration is layered; later sources win:

```text
<repo>/.env  →  backend/.env  →  backend/.env.<ENVIRONMENT>  →  real environment variables
```

Separate development and production templates are provided
(`backend/.env.development.example`, `backend/.env.production.example`). In production the API
**refuses to start** if `JWT_SECRET_KEY` is still the placeholder or shorter than 32 characters, if
`DEBUG` is true, or if `CORS_ORIGINS` is empty or contains `*`.

---

## 7. Frontend setup

```bash
cd frontend
npm install
cp .env.example .env      # only needed once
npm run dev               # http://localhost:5173
```

Other scripts:

```bash
npm run build             # production bundle into dist/
npm run preview           # serve the built bundle on :4173
npm run lint              # ESLint
```

`frontend/.env` holds no secrets — every `VITE_*` value is compiled into the public bundle.

---

## 8. Backend setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # then set DATABASE_URL and JWT_SECRET_KEY
```

---

## 9. Database setup

### 9.1 Create the role and databases

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE honeychain WITH LOGIN PASSWORD 'honeychain_dev_password';
CREATE DATABASE honeychain_dev  OWNER honeychain;
CREATE DATABASE honeychain_test OWNER honeychain;   -- used by the test suite
SQL
```

`DATABASE_URL` uses the `psycopg` (v3) driver:

```env
DATABASE_URL=postgresql+psycopg://honeychain:honeychain_dev_password@localhost:5432/honeychain_dev
```

### 9.2 Apply migrations

```bash
cd backend
alembic upgrade head          # create schema
alembic current               # show applied revision
alembic history               # list revisions
alembic revision --autogenerate -m "describe change"   # after changing models
```

The initial migration creates:

| Table | Purpose |
| --- | --- |
| `users` | Single identity record for all ten roles (UUID PK, role enum, timestamps) |
| `refresh_tokens` | Server-side session records enabling logout, rotation and replay detection |
| `user_role` | PostgreSQL enum of the ten platform roles |

Primary keys are UUIDs (`gen_random_uuid()`, built in from PostgreSQL 13), so identifiers are not
enumerable in the public QR/trace URLs planned for Phase 3.

---

## 10. Running the application

Two terminals.

**Terminal 1 — API**

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 — web app**

```bash
cd frontend
npm run dev
```

Then open **http://localhost:5173**.

| URL | What it is |
| --- | --- |
| http://localhost:5173 | Public landing page |
| http://localhost:5173/register | Create an account (choose your role) |
| http://localhost:5173/login | Sign in |
| http://localhost:5173/dashboard | Authenticated shell (redirects if signed out) |
| http://localhost:8000/docs | Interactive OpenAPI documentation |
| http://localhost:8000/api/v1/health | Health endpoint |

> **Note on CORS and hosts.** In development the browser only ever calls the Vite origin. If you
> point the SPA directly at the API on another host, add that origin to `CORS_ORIGINS`. If Vite
> rejects your hostname (common behind a proxy domain), set `VITE_ALLOWED_HOSTS` in
> `frontend/.env`, or clear it to allow all hosts for local development.

---

## 11. API health check

```bash
curl http://localhost:8000/api/v1/health
# {"status":"ok","service":"HoneyChain API"}
```

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/health` | Liveness — does not touch the database |
| `GET /api/v1/health/db` | Readiness — PostgreSQL connectivity and applied tables |
| `GET /api/v1/health/detailed` | Per-component report (database, auth, blockchain, IoT, AI) |
| `GET /api/v1/health/mqtt` | MQTT ingest status — `connected` / `disconnected` / `stopped` / `not_configured`, with the subscribed topic, message counters and the last error. `not_configured` is a normal state: HTTP telemetry still works |

The frontend calls `/health` on load and periodically, and shows the result in the site footer and
in the dashboard's "Platform status" card — so the frontend↔backend link can be verified visually
without developer tools.

---

## 12. Authentication flow

One authentication system serves all ten roles; authorisation is role-based on top of it.

### 12.1 Token architecture

| Token | Lifetime (default) | Storage | Purpose |
| --- | --- | --- | --- |
| Access | 30 min (60 in dev) | In-memory + `sessionStorage` mirror | Authorises API calls |
| Refresh | 7 days (14 in dev) | **HttpOnly, SameSite cookie**, path-scoped to `/api/v1/auth` | Mints new access tokens; enables real logout |

Only a SHA-256 fingerprint of each refresh token is stored server-side — a database leak cannot be
replayed as credentials.

### 12.2 End-to-end sequence

```text
1. POST /auth/register   → user row created (bcrypt hash), session opened
                            body: access_token (+refresh_token in dev mode)
                            cookie: HttpOnly refresh token
2. POST /auth/login      → same shape; last_login_at recorded
3. GET  /auth/me         → profile for the bearer token; used on every app boot
4. POST /auth/refresh    → rotates the refresh token:
                            old token revoked, new token issued, replaced_by_jti recorded
                            replay of a revoked token ⇒ ALL sessions for that user revoked
5. POST /auth/logout     → revokes the session server-side and clears the cookie
                            { "all_devices": true } revokes every session
```

### 12.3 Frontend behaviour

- The access token is attached by a single Axios request interceptor.
- On a `401`, the client refreshes **once** and replays the request. Concurrent 401s share a single
  refresh (no refresh storms).
- If refresh fails, the session is cleared and the user is returned to `/login`.
- A page refresh re-validates the stored token against `/auth/me` before rendering protected pages,
  so a revoked session cannot be restored from client state.

### 12.4 Role-based access control

Public registration offers **`CONSUMER` and `BEEKEEPER` only**. Every other role — `ADMIN`,
`KVIC_OFFICER`, `LAB_TECHNICIAN` and the supply-chain participants — is provisioned by an
administrator through **Administration → Users → Create user**
(`POST /api/v1/admin/users`), and a request that tries to self-assign one is rejected with `422`
instead of being quietly downgraded.

Choosing a role is its own capability, `ADMIN_ROLE_ASSIGN`, granted to administrators only and
checked on the route *and* in the service. An administrator can create an account for any of the ten
roles, set its status at creation, activate or deactivate it afterwards, and change its role later
(`PATCH /api/v1/admin/users/{id}/role`) — except on their own account, which is refused, and except
when it would leave the platform without an active administrator. A user can never change their own
role: `PATCH /api/v1/users/me` rejects the field outright. The same single authentication system
serves every account; the role is stored in the database and read on every request, so a token
cannot carry a role the account no longer holds.

Route protection is declarative and driven by one capability catalogue:

```python
# app/core/permissions.py — the only place roles are mapped to capabilities
ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = { UserRole.KVIC_OFFICER: frozenset({
    Permission.BEEKEEPER_READ_ALL, Permission.BEEKEEPER_UPDATE_ALL,
    Permission.BEEKEEPER_VERIFY, Permission.CLUSTER_READ, Permission.CLUSTER_MANAGE, ... }), ... }

# app/routes/beekeepers.py — routes declare what they need, never who they are
@router.patch("/{beekeeper_id}/verification")
def change_beekeeper_verification(
    actor: User = Depends(require_permission(Permission.BEEKEEPER_VERIFY)), ...
```

| Role | Landing route | Phase-2 capabilities |
| --- | --- | --- |
| `ADMIN` | `/admin` | Every capability: user directory, account activation, beekeeper read/update/verify, cluster management, audit log |
| `KVIC_OFFICER` | `/kvic` | Beekeeper read/update/verify, cluster read/manage — no platform account management |
| `BEEKEEPER` | `/beekeeper` | Own account and own beekeeper record, cluster read; can never change its own verification status |
| `CONSUMER` | `/consumer` | Own account/profile only |
| `COLLECTION_CENTER` / `PROCESSOR` / `LAB_TECHNICIAN` / `PACKAGING_UNIT` / `DISTRIBUTOR` / `RETAILER` | `/collection-center`, `/processor`, `/laboratory`, `/packaging`, `/distributor`, `/retailer` | Own account/profile only until their modules ship |

On the client, `RoleRoute` prevents a user from landing on a workspace their role cannot use, and the
API enforces the same rule independently. A refusal renders an in-app explanation, not a raw status
code.

### 12.5 API response contract

Every endpoint uses one envelope.

```json
{ "success": true, "data": { } }
```

```json
{ "success": false, "error": { "code": "VALIDATION_ERROR", "message": "Invalid request" } }
```

Successful collections add `meta` (`page`, `page_size`, `total_items`, `total_pages`). Error
responses add `request_id`, which also appears in the `X-Request-ID` header and in the server logs.

| Status | Typical codes |
| --- | --- |
| 400 | `BAD_REQUEST` |
| 401 | `AUTHENTICATION_ERROR`, `INVALID_CREDENTIALS`, `TOKEN_EXPIRED`, `TOKEN_INVALID` |
| 403 | `PERMISSION_DENIED`, `ACCOUNT_INACTIVE` |
| 404 | `NOT_FOUND` |
| 409 | `CONFLICT`, `DUPLICATE_RESOURCE` |
| 422 | `VALIDATION_ERROR` (with field-level `details`) |
| 500 | `DATABASE_ERROR`, `INTERNAL_ERROR` |
| 503 | `SERVICE_UNAVAILABLE` |

---

### 12.6 Phase 2 — user, role, profile & beekeeper management

The module that turns the Phase 1 shell into real identity and apiary data. Full sign-off details are
in [`docs/phase-2-report.md`](docs/phase-2-report.md).

**Schema.** `users` extended (`phone` unique where provided, `is_verified`, `last_login_at`,
`deactivated_at`); new `user_profiles`, `beekeepers`, `kvic_clusters`,
`beekeeper_verification_history` (append-only) and `audit_logs`, plus `document_sequences` — the
counter behind backend-generated codes such as `BKR-GNT-00001` and `KVIC-GNT-001`. Relationships:
`User → UserProfile`, `User → Beekeeper → KvicCluster`; a beekeeper record exists only for
`BEEKEEPER` users.

**Registration.** `POST /auth/register` accepts `CONSUMER` and `BEEKEEPER` with `name`, `email`,
`phone?`, `password` and an optional `beekeeper` block (village, mandal, district, state, pincode,
experience, species, hives — all optional). A new beekeeper row is always created `PENDING`; the
platform never self-verifies, and `kvic_cluster_id` cannot be claimed at registration (`422`).
Authentication itself is unchanged: register, login, refresh (rotating, replay-detecting), logout,
`/auth/me`.

**Endpoints added** (all paginated lists carry `meta`):

| Area | Endpoints |
| --- | --- |
| Own profile | `GET`/`PUT`/`PATCH /profile` |
| Own apiary | `GET`/`PUT /beekeepers/me` |
| Directory | `GET /beekeepers`, `/beekeepers/filters`, `/beekeepers/summary`, `/beekeepers/{id}`, `PUT /beekeepers/{id}`, `PATCH /beekeepers/{id}/verification` |
| Clusters | `GET`/`POST /clusters`, `GET`/`PUT /clusters/{id}`, `PATCH /clusters/{id}/status`, `GET /clusters/{id}/beekeepers`, `POST`/`DELETE /clusters/{id}/beekeepers/{beekeeper_id}` |
| Administration | `GET`/`POST /admin/users`, `/admin/users/{id}`, `PATCH /admin/users/{id}/status`, `PATCH /admin/users/{id}/role`, `/admin/audit-logs`, `/admin/activity` |

**Verification workflow.** `PENDING → UNDER_REVIEW → VERIFIED`, with `REJECTED`/`SUSPENDED` reachable
only through allowed transitions; `REJECTED`/`SUSPENDED` require remarks of at least five characters
(`422` otherwise). Every change writes status, remarks, `verified_by`, `verified_at` **and** an
append-only history row, plus an audit entry. Only `ADMIN` and `KVIC_OFFICER` hold
`BEEKEEPER_VERIFY`.

**Audit.** `USER_REGISTERED`, `USER_PROVISIONED` (an administrator created the account),
`USER_ROLE_CHANGED` (with both the previous and the new role), `USER_LOGIN`/`FAILED`/`LOGOUT`,
`PROFILE_UPDATED`, `BEEKEEPER_CREATED`,
`BEEKEEPER_UPDATED`, `BEEKEEPER_VERIFIED`/`REJECTED`/`SUSPENDED`, `USER_ACTIVATED`/`DEACTIVATED`,
`CLUSTER_CREATED`/`UPDATED`/`STATUS_CHANGED`/`MEMBER_ASSIGNED`/`MEMBER_REMOVED` — written inside a
SAVEPOINT so auditing can never fail a business operation. No passwords, tokens or secrets reach
`metadata`; entries cannot be edited or deleted from the application.

**Frontend.** `/profile` (Personal, Location, Account, and beekeeper extras when applicable);
`/beekeeper/profile` with verification badges and read-only history; `/admin/users` (identity directory, **Create user** for any of the ten roles, **Change role**),
`/admin/beekeepers`, `/admin/clusters`, `/admin/audit-logs`; `/kvic/beekeepers`, `/kvic/clusters`;
role-based post-login redirects; a role-aware sidebar where future modules are labelled placeholders
rather than fake screens. Empty databases render empty states — never invented counts.

**Development seed.** `.venv/bin/python -m app.scripts.seed_dev_data` creates one account per role
(`ADMIN`, `KVIC_OFFICER`, `BEEKEEPER`, `CONSUMER`), cluster `KVIC-GNT-001` and a membership, labelled
**DEVELOPMENT ONLY** and refusing to run with `ENVIRONMENT=production`.

---

## 13. Phase 2 — users, roles, profiles & beekeepers

The identity and apiary registry module: real profiles, a beekeeper registry with KVIC clusters and
a review workflow, an administrator directory and an audit trail. Everything is built on the Phase 1
foundation — no part of the existing stack, schema or authorisation model was replaced.

### 13.1 Schema

| Table | Purpose |
| --- | --- |
| `users` *(extended)* | `phone` (unique where provided), `is_verified`, `last_login_at`, `deactivated_at` |
| `user_profiles` | Optional personal and location detail: photo link, date of birth, gender, address, village, mandal, district, state, pincode |
| `beekeepers` | One per beekeeper user: generated `beekeeper_code`, experience, bee species, hive count, location, `kvic_cluster_id`, `registration_date`, `verification_status` |
| `kvic_clusters` | Cluster master data: generated `cluster_code`, name, district, state, coordinator, `is_active` |
| `beekeeper_verification_history` | Append-only trail of every verification decision (previous → new status, remarks, actor, timestamp) |
| `audit_logs` | Platform audit trail: action, entity, actor, metadata, IP address |
| `document_sequences` | Counter behind backend-generated codes (`BKR-GNT-00001`, `KVIC-GNT-001`) |

`User → UserProfile`, `User → Beekeeper → KvicCluster`; a beekeeper record exists only for
`BEEKEEPER` users. Migration: `c71dce65bc61` (`alembic upgrade head`).

### 13.2 Registration rules

`POST /api/v1/auth/register` accepts **`CONSUMER` and `BEEKEEPER` only** — every other role is
provisioned by an administrator, and a request that tries to claim one gets `422` rather than being
quietly downgraded. A beekeeper registration may include an apiary block (`village`, `mandal`,
`district`, `state`, `pincode`, `experience_years`, `bee_species`, `number_of_hives` — all optional),
and always creates the beekeeper record as **`PENDING`**: the platform never verifies anyone on its
own, and cluster membership cannot be claimed at sign-up.

### 13.3 Endpoints added in Phase 2

| Method | Path | Required permission |
| --- | --- | --- |
| `GET`/`PUT`/`PATCH` | `/api/v1/profile` | authenticated (self only) |
| `GET` / `PUT` | `/api/v1/beekeepers/me` | `BEEKEEPER_READ_SELF` / `BEEKEEPER_UPDATE_SELF` |
| `GET` | `/api/v1/beekeepers` | `BEEKEEPER_READ_ALL` — filters `search`, `district`, `state`, `cluster`, `verification_status`, `bee_species` |
| `GET` | `/api/v1/beekeepers/filters`, `/api/v1/beekeepers/summary` | `BEEKEEPER_READ_ALL` |
| `GET` / `PUT` | `/api/v1/beekeepers/{id}` | `BEEKEEPER_READ_ALL` / `BEEKEEPER_UPDATE_ALL` |
| `PATCH` | `/api/v1/beekeepers/{id}/verification` | `BEEKEEPER_VERIFY` |
| `GET` / `POST` | `/api/v1/clusters` | `CLUSTER_READ` / `CLUSTER_MANAGE` |
| `GET` / `PUT` | `/api/v1/clusters/{id}` | `CLUSTER_READ` / `CLUSTER_MANAGE` |
| `PATCH` | `/api/v1/clusters/{id}/status` | `CLUSTER_MANAGE` |
| `GET` | `/api/v1/clusters/{id}/beekeepers` | `CLUSTER_READ` |
| `POST` / `DELETE` | `/api/v1/clusters/{id}/beekeepers/{beekeeper_id}` | `CLUSTER_MANAGE` |
| `GET` | `/api/v1/admin/users`, `/api/v1/admin/users/{id}` | `USER_READ_ALL` |
| `POST` | `/api/v1/admin/users` | `ADMIN_USER_MANAGE` + `ADMIN_ROLE_ASSIGN` |
| `PATCH` | `/api/v1/admin/users/{id}/status` | `ADMIN_USER_MANAGE` |
| `PATCH` | `/api/v1/admin/users/{id}/role` | `ADMIN_ROLE_ASSIGN` |
| `GET` | `/api/v1/admin/audit-logs`, `/api/v1/admin/activity` | `AUDIT_READ` |

Lists are paginated (`meta`), filtered server-side, and never return credentials. There is no delete
endpoint for users, beekeepers or clusters: accounts are deactivated, records are retained.

### 13.4 Authorisation and the verification workflow

One capability catalogue lives in `app/core/permissions.py`:

```python
ROLE_PERMISSIONS[UserRole.KVIC_OFFICER] = frozenset({
    Permission.USER_READ_SELF, Permission.USER_UPDATE_SELF,
    Permission.BEEKEEPER_READ_ALL, Permission.BEEKEEPER_UPDATE_ALL, Permission.BEEKEEPER_VERIFY,
    Permission.CLUSTER_READ, Permission.CLUSTER_MANAGE,
})
```

Routes declare the capability they need (`Depends(require_permission(...))`), never a role name, so a
re-scoped role is a one-line change. `BEEKEEPER_*_SELF` means "my own apiary record" and is held by
beekeepers alone, so an administrator calling `/beekeepers/me` is refused rather than landing on a
404.

`PENDING → UNDER_REVIEW → VERIFIED`, with `REJECTED` / `SUSPENDED` reachable only through allowed
transitions; rejections and suspensions require a remark of at least five characters. Every decision
writes `verified_by`, `verified_at`, an append-only history row **and** an audit entry.

### 13.5 Audit trail

`USER_REGISTERED`, `USER_LOGIN`, `USER_LOGIN_FAILED`, `USER_LOGOUT`, `PROFILE_UPDATED`,
`BEEKEEPER_CREATED`, `BEEKEEPER_UPDATED`, `BEEKEEPER_VERIFIED`, `BEEKEEPER_REJECTED`,
`BEEKEEPER_SUSPENDED`, `USER_ACTIVATED`, `USER_DEACTIVATED` and the `CLUSTER_*` events — written
inside a SAVEPOINT so auditing can never fail a business operation, and never containing passwords,
tokens or secrets. Entries cannot be edited or deleted from the application.

### 13.6 Screens

| Route | Roles | What it does |
| --- | --- | --- |
| `/profile` | all | Personal, location and account details, plus apiary/verification extras for beekeepers |
| `/beekeeper/profile` | beekeeper | Editable apiary record, verification badge, read-only history, cluster membership |
| `/admin/users` | admin | Search, role/status filters, pagination, activate/deactivate |
| `/admin/beekeepers` | admin | Directory with filters, detail panel, verify/reject with remarks |
| `/admin/clusters` | admin | Cluster CRUD, status, member assignment |
| `/admin/audit-logs` | admin | Filterable audit trail (states that secrets are redacted and entries immutable) |
| `/kvic/beekeepers` | KVIC officer | Directory and verification workflow |
| `/kvic/clusters` | KVIC officer | Cluster management and members |

Role-based redirects send each user to their own workspace, and every module that is not built yet is
labelled as planned instead of being faked.

### 13.7 Development accounts and scripts

**DEVELOPMENT ONLY** — created by `python -m app.scripts.seed_dev_data` (refuses to run when
`ENVIRONMENT=production`):

| Email | Role | Password |
| --- | --- | --- |
| `admin@honeychain.example.com` | ADMIN | `AdminSecure123` |
| `kvic@honeychain.example.com` | KVIC_OFFICER | `KvicSecure123` |
| `beekeeper@honeychain.example.com` | BEEKEEPER | `HoneyPass123` |
| `consumer@honeychain.example.com` | CONSUMER | `ConsumerPass123` |

```bash
cd backend && source .venv/bin/activate

.venv/bin/python -m app.scripts.seed_dev_data             # accounts + demo cluster (idempotent)
.venv/bin/python -m app.scripts.seed_dev_data --reset     # remove the fixtures again
.venv/bin/python -m app.scripts.backfill_beekeeper_records --dry-run
.venv/bin/python -m app.scripts.create_admin --email ops@example.org --name "Ops" --role ADMIN
```

---

## 14. Phase 3 — hive registry & smart-hive IoT

The physical layer of the platform: a hive registry per beekeeper, the devices attached to those
hives, and the telemetry pipeline an ESP32 node uses. Full sign-off:
[`docs/phase-3-report.md`](docs/phase-3-report.md); module reference:
[`docs/iot.md`](docs/iot.md).

**Schema.** One migration (`78889ff27825`) adds four tables and eight enum types:

| Table | Purpose |
| --- | --- |
| `hives` | `hive_code` (`HIVE-<DISTRICT>-NNNNN`, generated from `document_sequences`), apiary location, colony strength and queen status as *observations*, status lifecycle, cluster link |
| `iot_devices` | `device_id` unique (case-insensitive), bound hive, MQTT topic, `last_seen`, battery, signal, `status` (derived at read time) |
| `sensor_configs` | One row per sensor per device: name, unit, enabled, sampling interval, optional tighter valid range |
| `sensor_readings` | Wide row per packet — `temperature`, `humidity`, `weight`, `vibration`, `acoustic_level`, `battery_level`, `signal_strength` — with `source`, denormalised `hive_id`/`beekeeper_id`, and `UNIQUE (device_id, timestamp)` for idempotent ingest |

**Endpoints added** (25 + one health route):

| Area | Endpoints |
| --- | --- |
| Hives | `GET /hives`, `/hives/summary`, `/hives/filters`, `POST /hives`, `GET`/`PUT /hives/{id}`, `PATCH /hives/{id}/status`, `DELETE /hives/{id}?force=`, `GET /beekeepers/me/hives` |
| Devices | `GET /iot/devices`, `/iot/devices/summary`, `POST /iot/devices`, `/iot/devices/heartbeat`, `GET`/`PUT`/`DELETE /iot/devices/{id}`, `PATCH /iot/devices/{id}/status`, `GET /iot/devices/{id}/sensors`, `PATCH /iot/devices/{id}/sensors/{sensor_type}`, `GET /iot/me/devices` |
| Telemetry | `POST /iot/telemetry`, `/iot/telemetry/batch`, `GET /iot/telemetry/{hive_id}`, `/iot/telemetry/{hive_id}/latest`, `/iot/last-telemetry` |
| Health | `GET /health/mqtt` |

**Ingest contract.** HTTP (`POST /iot/telemetry`, plus a batch form for a store-and-forward backlog)
and MQTT (`<prefix>/devices/{device_id}/telemetry`) converge on one validation pipeline. Every
reading is range-checked against data-validity bounds and **rejected, never clamped**; `(device_id,
timestamp)` is idempotent, so a replayed packet is reported as `duplicate`; a value the device did
not measure stays `NULL` and renders as "No data". The effective `source` is decided server-side:
`SIMULATOR` when declared, `MANUAL` for an authenticated HTTP submission otherwise, and
`REAL_DEVICE` for an unlabelled packet arriving over MQTT. **The broker is optional**: without
`MQTT_BROKER_URL` the API, HTTP ingest and every dashboard still work, and `/health/mqtt` answers
`not_configured` with an explanation.

**Device health.** Status is derived, not asserted — `OFFLINE` when nothing has arrived within
`DEVICE_OFFLINE_THRESHOLD_SECONDS` (900 s), `WARNING` when the battery is at or below
`DEVICE_LOW_BATTERY_PERCENT` (20 %), `ONLINE` otherwise, and `MAINTENANCE` when an operator takes a
device out of service (`device_status_sweep` keeps the stored values current).

**Authorisation.** Six new capabilities — `HIVE_READ_SELF`/`HIVE_WRITE_SELF`, `HIVE_READ_ALL`/
`HIVE_WRITE_ALL` and the matching device/telemetry pairs. A beekeeper sees only their own apiary; a
cross-owner read answers `404` and submitting telemetry for someone else's device answers `403`; KVIC
officers and administrators have platform scope; the consumer role has no access at all.

**Frontend.** `/beekeeper/hives` (registry with summary tiles, filters, register/edit modals, status
changes, row → detail), `/beekeeper/hives/:id` (registration facts, sensor snapshot, paired devices
with derived status, stored history, MQTT topic), `/beekeeper/iot` (fleet counters, ingest state,
last-packet strip, device table, device panel with sensor configuration, trend chart, manual test
reading), `/kvic/hives`, `/kvic/iot`, `/admin/hives`, `/admin/iot`, plus live hive/device blocks on
the beekeeper, KVIC and admin dashboards. Sidebar entries for **My Hives** and **IoT Monitoring** are
live; modules that are still to come keep a "Soon" badge.

**Scripts.** `hive_simulator.py` (`--transport http|mqtt`, `--dry-run`, `--seed`, sensor subsets,
every packet labelled `SIMULATOR`) and `device_status_sweep.py`; both refuse to run against
production data without the development environment.

**Screens.** `docs/screenshots/phase-3-*.png` — dashboard, hive registry, IoT monitoring, device
panel and the KVIC hive registry.

---

## 15. Phase 4 — AI-powered hive health insights

**Scope.** Advisory analytics over *stored* telemetry — no training, no clinical claims. The engine is
a documented rule-based baseline: a health indicator assembled from weighted factors with published
arithmetic (`clamp(70 + min(Σ positive, 20) + Σ negative, 0, 100)`, capped at 90 by design and never
reported as 100), disease and swarming **risk** levels (never a diagnosis), a guarded yield
projection, recommendations, and alerts with cooldown de-duplication and an
`OPEN → ACKNOWLEDGED → RESOLVED` lifecycle. Data quality decides what may be said: below
`AI_MIN_SAMPLES` the assessment reports `INSUFFICIENT` and offers data-quality advice only, every
figure carries a confidence that staleness reduces, and each assessment records the source it was
computed from (`SIMULATOR`, `MANUAL`, `REAL_DEVICE`). Every run and every alert action is audited.

**API.** 13 endpoints under `/api/v1/ai/**` — summary, hive list, bulk `POST /ai/analyze`,
`GET /ai/hives/{id}?refresh=`, per-hive analysis, history, hive alerts, the alert worklist and
summary, alert detail, and ack/resolve/reopen. `compute_reason` explains *why* an assessment was or
was not recomputed (`no_analysis | stale | new_telemetry | forced | read_only | auto_disabled |
fresh`); an unanalysed hive is returned as `analyzed: false` rather than omitted. Beekeepers are
scoped to their own hives; KVIC officers and administrators read platform-wide.

**Frontend.** `HiveAiSection` on the hive screen (health factors, risks, projection,
recommendations, alerts, analysis history) plus AI Insights and Alerts workspaces for beekeeper, KVIC
and administrator roles, all rendering empty states and source labels rather than placeholder values.

**Verified.** `pytest` 432/432 at delivery, Phase-4 API smoke 73/73, and the AI suites
(`test_ai_engine.py` 42, `test_ai_repository.py` 16, `test_ai_insights.py` 30) run inside the full
suite (474 passed with Phase 4.1 below). Model reference: `hive_ai_baseline` v1.0.

---

## 16. Phase 4.1 — the organisational relationship

**The chain.** `KVIC → Cluster → Beekeeper → Hive → IoT Device → Telemetry → AI Analysis` resolves
server-side from relationships that already existed; the phase added **no table, no column and no
duplicated record**.

| Layer | What changed |
| ----- | ------------ |
| Propagation | Assigning a beekeeper to a cluster moves every hive still following them (`previous_cluster_id` guard); removing them leaves the hives with the owner and unassigned |
| Scoping | `hive_ids`/`list_for_hives` filters in the device, reading and AI repositories; `AiService`/`AiAlertService`/`IotMonitoringService` gained cluster-narrowed summaries |
| Cluster view | `GET /clusters/{id}/{summary,hives,devices,ai,telemetry/latest}` under the new `CLUSTER_ANALYTICS_READ` permission (ADMIN, KVIC_OFFICER) |
| Placement | `POST /hives/{id}/cluster` — staff-only, validated (unknown 404, inactive/duplicate 422), audited with previous and new cluster; `cluster_id` remains refused inside hive/device payloads |
| Worklist | `GET /hives?has_cluster=false` and the staff-only `HiveSummary.without_cluster` for hives whose owner belongs to no cluster |
| History | Migration `5e2b7d41c8aa` links existing hives to their owner's cluster (never inventing one, never overwriting a placement; no-op downgrade) |
| Audit | `BEEKEEPER_ASSIGNED_TO_CLUSTER`, `BEEKEEPER_REMOVED_FROM_CLUSTER`, `HIVE_ASSOCIATED_WITH_CLUSTER`, `CLUSTER_RELATIONSHIP_UPDATED` (+ legacy aliases) |

**Frontend.** The KVIC cluster screen (`/kvic/clusters/:clusterId`, mirrored for administrators) is a
read-through view: counters, the cluster's hives, their devices, the latest stored packet with its
full chain, and the stored assessments with source labels. Staff can place or clear a single hive on
the hive screen; a beekeeper sees the cluster read-only and never gets that control. The hive
registry's oversight filter *Any / In a cluster / Not in a cluster (worklist)* exposes the
administrative backlog.

**Verified.** Backend 474/474 (`test_cluster_relationships.py` 42 new); API smoke 43/43; browser
smoke 26/26 with 0 console errors; Phase-2/3/4 smokes unchanged at 43/64/73; eslint 0 and
`npm run build` exit 0. Full write-up: [`docs/phase-4-1-report.md`](docs/phase-4-1-report.md).

---

## 17. Testing

### 17.1 Backend suite

```bash
cd backend
source .venv/bin/activate
pytest                       # 474 tests
pytest --cov=app --cov-report=term-missing
```

The suite runs against **PostgreSQL** (`honeychain_test`) because that is the database the project
ships on. If no server is reachable it falls back to a temporary SQLite file and says so loudly, so
tests still run on a laptop without PostgreSQL.

| Module | Tests | Covers |
| --- | --- | --- |
| `test_health.py` | 9 | Liveness, readiness, component report, API discovery, error envelope |
| `test_auth_register.py` | 14 | Registration, role policy (consumer/beekeeper only), duplicate handling, validation, hashing |
| `test_auth_login.py` | 25 | Login, `/auth/me`, refresh rotation, reuse detection, logout, protected routes |
| `test_authorization.py` | 13 | Admin-only endpoints, 401 vs 403, pagination, role catalogue |
| `test_permissions_matrix.py` | 29 | Every role against every Phase-2 endpoint, incl. the permission catalogue |
| `test_profile.py` | 15 | `GET/PUT/PATCH /profile`, self-only access, optional fields, location sync |
| `test_beekeepers.py` | 32 | Registration-created records, self-service, directory, filters, verification workflow |
| `test_clusters.py` | 20 | Cluster CRUD, status, membership, per-cluster listings |
| `test_audit.py` | 14 | Audit entries for every Phase-2 action, redaction, filtering |
| `test_migrations.py` | 9 | Single migration head, Phase-2/3/4 tables, Phase-4.1 backfill revision, enum handling, no plaintext password column |
| `test_logging.py` | 9 | Secret redaction and log-record formatting |
| `test_hives.py` | 49 | Registry CRUD, generated codes, filters, summary, ownership, status lifecycle, retirement rules |
| `test_iot_devices.py` | 40 | Registration, seeded sensors, duplicate ids, derived status, battery warning, heartbeat, deletion rules |
| `test_telemetry.py` | 38 | Ingest, idempotency, range rejection, clock skew, batching, history, aggregation, ownership |
| `test_mqtt_ingest.py` | 27 | Topic parsing, payload validation, device/topic mismatch, counters, health states, broker-absent behaviour |
| `test_ai_engine.py` | 42 | Health factors and arithmetic, risk levels, guarded yield projection, quality gating, recommendations |
| `test_ai_repository.py` | 16 | Analysis/alert persistence, latest-per-hive, alert de-duplication and cooldown |
| `test_ai_insights.py` | 30 | AI endpoints end to end: scoping, recompute reasons, alert lifecycle, staff read scope |
| `test_cluster_relationships.py` | 42 | Membership and propagation, staff-only placement, cluster views and their refusals, unassigned worklist, backfill |

### 17.2 Frontend build check

```bash
cd frontend
npm run build      # import/module-graph check of the whole application
npm run dev        # then confirm the footer and dashboard show "API · Online"
```

### 17.3 Browser end-to-end smoke test

With PostgreSQL, the API and the dev server all running, a Playwright script drives a real
Chromium browser through the Phase 1 acceptance criteria — nine scenarios, 35 assertions:

```bash
cd backend
.venv/bin/pip install playwright && .venv/bin/playwright install chromium
.venv/bin/playwright install-deps chromium      # Linux only, once

.venv/bin/python tests/browser_smoke.py
```

It verifies that anonymous users are redirected from protected routes, registration and login work
through the UI, the session survives a reload, role guarding blocks a beekeeper from the admin area,
logout confirmation works, invalid credentials produce a safe error, and the administrator
workspace renders live data from the API. Exit code is non-zero if any check fails. **36 checks.**

A second script covers the Phase 2 acceptance criteria — registration with the apiary section,
beekeeper profile editing that survives a reload, the KVIC verification workflow with remarks,
cluster management, the administrator directories and audit log, and consumer refusals:

```bash
.venv/bin/python tests/browser_smoke_phase2.py       # 27 checks
```

Both scripts drive a real Chromium through the Vite proxy against the running API and PostgreSQL,
and fail on any unexpected browser console error.

A third script covers the Phase 3 acceptance criteria — the dashboard on live data, the registry
including registering a hive and asserting the platform-generated code, hive detail reaching the
paired device and its stored history, IoT monitoring with source labels, empty states for a new
beekeeper, cross-user isolation, dialog fitting at 100 % zoom, and layout at four desktop widths. It
defaults to the **production build** (`npm run build && npm run preview`) because the HMR dev server
holds an order of magnitude more memory per navigation, which ends in a crashed renderer on a small
machine:

```bash
cd frontend && npm run build && npm run preview -- --port 4173   # terminal
cd backend  && .venv/bin/python tests/browser_smoke_phase3.py    # 110 checks
```

The Phase 3 API smoke runs the same surface against the running API — including cross-owner refusals
and the simulator ingest path — and cleans up the fixtures it creates:

```bash
cd backend && .venv/bin/python tests/api_smoke_phase3.py         # 64 checks
.venv/bin/python tests/api_smoke_phase4.py         # 73 checks
.venv/bin/python tests/api_smoke_phase41.py        # 43 checks — the organisational chain
```

A fourth browser script walks the Phase 4.1 relationship: the cluster view's counters and panels, a
staff placement cleared and restored (with the view following immediately, because it is the same
record), the unassigned-hive worklist, the owner's read-only cluster, and the refusal a beekeeper
gets on a cluster URL:

```bash
.venv/bin/python tests/browser_smoke_phase41.py     # 26 checks
```

### 17.4 Creating an administrator

`ADMIN`, `KVIC_OFFICER` and `LAB_TECHNICIAN` cannot be self-registered (privilege-escalation guard),
so the first administrator is provisioned from the server:

```bash
cd backend
source .venv/bin/activate

.venv/bin/python -m app.scripts.create_admin \
  --email admin@example.org \
  --name "Platform Administrator" \
  --role ADMIN \
  --district Guntur --state "Andhra Pradesh"

# Or supply the password non-interactively (CI / containers):
DEFAULT_ADMIN_PASSWORD='…' .venv/bin/python -m app.scripts.create_admin \
  --email admin@example.org --name "Platform Administrator"
```

The password is read without echoing, never logged, and stored only as a bcrypt hash.

---

## 18. Development roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| **1** | **Platform foundation** — architecture, authentication, ten roles, RBAC, database schema, API foundation, public site, application shell, docs | ✅ **Delivered** |
| **2** | **User, role & beekeeper management** — profiles, apiary registry, KVIC clusters, verification workflow, audit trail, admin and KVIC workspaces | ✅ **Delivered** |
| **3** | **Hive registry & smart-hive IoT foundation** — hive lifecycle, device binding, sensor configuration, telemetry ingest (HTTP + MQTT), device health, monitoring dashboards | ✅ **Delivered** |
| **4** | **AI-powered hive health insights** — advisory baseline engine, health indicator, disease/swarming risk, yield projection, recommendations, alert lifecycle | ✅ **Delivered** |
| **4.1** | **Organisational data-relationship correction** — cluster ↔ beekeeper ↔ hive propagation, cluster views, staff placement, backfill, audit | ✅ **Delivered** |
| **5** | **Honey collections & batches** — harvest records against one or more hives, batch created on completion, batch lineage, timeline, role-scoped registers | ✅ **Delivered** |
| **6** | **Processing & laboratory** — processing units and runs with measured quantities, sample-based lab tests against the configured parameter catalogue, PASS/FAIL/INCONCLUSIVE verdicts driving the batch lifecycle | ✅ **Delivered** |
| **6.1** | **Role-based workspaces & navigation** — one central role→navigation configuration, per-role sidebars and route guards, laboratory → beekeeper/KVIC synchronization | ✅ **Delivered** |
| later | Packaging, distribution, QR issuance, customer verification, trust score, blockchain anchoring, KVIC analytics & campaigns | Planned |

Later phases extend the existing architecture; they do not restructure it. Each new module adds a
router, service, repository and models, then registers itself in `app/api/router.py` (the
commented mount points are already in place) and adds its pages under the matching `pages/` folder.

See [`docs/development-roadmap.md`](docs/development-roadmap.md) for the detailed breakdown.

---

## 19. Engineering conventions

Rules the codebase follows. Please keep them when extending it.

1. **No hardcoded secrets.** Configuration comes from environment variables; `.env` files are
   git-ignored; production refuses to boot with placeholder secrets.
2. **No fake functionality.** If a module is not implemented, the UI says so — it never shows
   invented data, and endpoints never return fabricated success payloads.
3. **Thin routes.** No business logic in `app/routes/*`; no SQL outside `app/repositories/*`.
4. **No plaintext passwords.** bcrypt only; the API never serialises credential fields.
5. **Validate at the boundary.** Pydantic schemas on input, response models on output.
6. **One envelope everywhere.** `{success, data}` / `{success, error{code,message}}`.
7. **Reusable components over duplicated markup.** Extend the `ui/` and `common/` primitives rather
   than writing one-off variants.
8. **Every screen handles loading, empty and error states** (`DataTable`, `EmptyState`,
   `ErrorState`, `LoadingState`).
9. **Never log secrets or personal data.** The logging layer redacts passwords, tokens, API keys and
   connection strings as defence in depth.
10. **Accessibility is not optional.** Labelled inputs, `aria-invalid`/`aria-describedby` on errors,
    visible focus rings, keyboard-operable dialogs, and motion that respects
    `prefers-reduced-motion`.
11. **Responsive by default.** Desktop, tablet and mobile layouts — many users are on mid-range
    Android phones in the field.
12. **Additive change.** Do not remove or rewrite working functionality when adding a module.
13. **Stated limits.** Describe capabilities as verification, traceability, AI-assisted risk
    detection, decision support and predictive analytics — never as guarantees of purity or
    complete disease detection.
14. **New technology requires justification.** Do not introduce a library or service outside the
    agreed stack without explaining why in the pull request.

---

## Licence and attribution

Prototype developed for **Smart India Hackathon 2026**, Problem Statement 26021.

Traceability, monitoring and advisory information provided by this platform is **not** a substitute
for accredited laboratory testing or regulatory certification.
