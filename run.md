# HoneyChain — How to run

Single-page operational guide. For architecture and API details see
[`README.md`](README.md), [`docs/architecture.md`](docs/architecture.md) and [`docs/api.md`](docs/api.md).

---

## 0. Current session status

Everything is already running in this workspace:

| Service | Port | Status | Process |
| --- | --- | --- | --- |
| PostgreSQL 17 | `5432` | running | system cluster `17/main` |
| FastAPI backend | `8000` | running | `uvicorn app.main:app` |
| React/Vite frontend | `4173` | **running — this is the preview** | `npm run build && npm run preview` — the target the browser smoke tests drive; `npm run dev` is available on `5173` |
| Production build preview | `4173` | running | same process as above |

**Open the preview** from the process panel (the `HoneyChain web app` entry → port `5173`).
The URL is `https://5173-<sandbox-id>.e2b.app`, and the same link is shown in the UI next to the
running process.

Quick check that everything is alive:

```bash
curl http://localhost:8000/api/v1/health          # {"status":"ok","service":"HoneyChain API"}
curl http://localhost:5173/api/v1/health/db       # database: connected, tables listed
curl http://localhost:8000/api/v1/health/mqtt    # ingest: not_configured without a broker (normal)
```

> The backend returns `status: "degraded"` if PostgreSQL is unreachable — the API still starts, so
> the health endpoint can tell you *why* it is unhealthy.

> **After a sandbox restart** the installed dependencies are gone (they are excluded from the
> workspace snapshot), so recreate them before starting the servers:
>
> ```bash
> cd HoneyChain/backend  && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
> cd HoneyChain/frontend && npm install
> ```
>
> The database itself survives; `alembic upgrade head` and `python -m app.scripts.seed_dev_data`
> are safe to re-run at any time.

---

## 1. Prerequisites

| Tool | Version | Check |
| --- | --- | --- |
| Python | 3.11+ | `python3 --version` |
| Node.js | 18.18+ | `node --version` |
| PostgreSQL | 15+ | `psql --version` |

---

## 2. Quick start

Three things must run: the database, the API, the web app. Use separate terminals for the last two.

### Terminal 1 — PostgreSQL

```bash
# Debian/Ubuntu (already installed in this workspace)
sudo pg_ctlcluster 17 main start
sudo pg_ctlcluster 17 main status

# macOS (Homebrew)
brew services start postgresql@17
```

One-time role and database creation (skip if already done):

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE honeychain WITH LOGIN PASSWORD 'honeychain_dev_password';
CREATE DATABASE honeychain_dev  OWNER honeychain;
CREATE DATABASE honeychain_test OWNER honeychain;   -- used by pytest
SQL
```

### Terminal 2 — backend API

```bash
cd HoneyChain/backend
source .venv/bin/activate                 # Windows: .venv\Scripts\activate

# First time only:
#   python3 -m venv .venv
#   pip install -r requirements.txt
#   cp .env.example .env                  # then set JWT_SECRET_KEY + DATABASE_URL

alembic upgrade head                      # apply migrations
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health

### Terminal 3 — frontend web app

```bash
cd HoneyChain/frontend
npm install                               # first time only
cp .env.example .env                      # first time only
npm run dev
```

Open **http://localhost:5173**.

> The dev server proxies `/api` to `http://localhost:8000` (configurable via `VITE_PROXY_TARGET`),
> so the browser talks to one origin — cookies work without any CORS setup.

---

## 3. Verify it works

### 3.1 Health endpoints

```bash
curl http://localhost:8000/api/v1/health
# {"status":"ok","service":"HoneyChain API"}

curl http://localhost:8000/api/v1/health/db
# database.connected: true, 13 tables (users, user_profiles, beekeepers, kvic_clusters,
#                                    hives, iot_devices, sensor_configs, sensor_readings, …)

curl http://localhost:8000/api/v1/health/detailed
# per-component report; blockchain/ai report "not_configured" until their phases land

curl http://localhost:8000/api/v1/health/mqtt
# {"status":"not_configured","enabled":false,…} — expected without MQTT_BROKER_URL;
# HTTP telemetry (POST /api/v1/iot/telemetry) is unaffected
```

### 3.2 In the browser

1. The landing page footer shows **API status: Online** — that is a live `/health` call.
2. Register a new account at `/register` (choose any non-privileged role).
3. You land directly in that role's workspace with a **Welcome** heading.
4. Reload the page — you stay signed in (the session is re-validated against `/auth/me`).
5. Sign out from the sidebar → confirmation dialog → back to `/login`.
6. Visit `/admin` as a beekeeper → blocked with an explanation (RBAC).

Phase 2 screens, in the order a reviewer would walk them:

7. **Beekeeper** (`beekeeper@honeychain.example.com`) → `/beekeeper/profile`: the apiary record, the
   verification badge, cluster membership and the read-only verification history. Edit the hive
   count, save, reload — the change persists.
8. **KVIC officer** (`kvic@honeychain.example.com`) → `/kvic/beekeepers`: search the directory, open a
   pending beekeeper, *Record decision* → `VERIFIED` with remarks; the badge and history update.
   Then `/kvic/clusters` → the cluster, its members and its status.
9. **Administrator** (`admin@honeychain.example.com`) → `/admin/users` (search, filters, pagination,
   activate/deactivate), `/admin/beekeepers` (verify/reject), `/admin/clusters`, `/admin/audit-logs`
   (the trail for everything above).

Phase 3 screens — the acceptance path is *simulator → ingest → PostgreSQL → dashboard*:

10. **Beekeeper** → `/beekeeper`: hive, device and offline counters; the hive overview lists
    `HIVE-GNT-00001` with its latest temperature, humidity and weight; the sensor overview shows the
    newest packet marked **Simulator**; quick actions jump to the registry and monitoring screens.
11. `/beekeeper/hives` → *Register hive* (the code `HIVE-<DISTRICT>-NNNNN` is generated by the
    platform) → open the row for the hive detail: registration facts, smoke sensors, paired device,
    stored history.
12. `/beekeeper/iot` → the paired `ESP32-GNT-0001`, derived status, battery, signal, last packet and
    the MQTT topic, plus the blue note explaining that no broker is configured here.
13. **KVIC officer** → `/kvic/hives` and `/kvic/iot`: the same registries and monitoring at district
    scope, read-only — no edit, pair or delete actions are offered.
14. **Administrator** → `/admin/hives` and `/admin/iot`: platform-wide oversight.

Phase 4 screens — the chain from a hive to an advisory assessment:

15. **Beekeeper** → open a hive → the **Hive health insights** section: the health indicator with its
    factors, disease and swarming risk levels, the guarded yield projection and recommendations, plus
    the analysis history. With little or no stored telemetry the section says so and gives
    data-quality advice instead of numbers.
16. `/beekeeper/alerts` → the alert worklist (severity, status, source); acknowledge, resolve and
    reopen. `/beekeeper/insights` lists the AI state of every hive.

Phase 4.1 screens — one set of records, several views:

17. **KVIC officer** → `/kvic/clusters` → the Guntur cluster → **View**: the cluster's membership,
    hive, device and telemetry counters, the latest stored packet with its full chain
    (`ESP32-GNT-0001 → HIVE-GNT-00001 → BKR-GNT-00001`, labelled **Simulator**), the stored
    assessments, and the devices the cluster's hives report through.
18. On a hive screen (`/kvic/hives/{id}`) → **Cluster placement**: staff may place or clear one hive,
    with a reason that lands in the audit log. Clearing it empties the cluster view on the next load
    — it is the same row, not a copy.
19. `/kvic/hives` → the cluster filter set to **Not in a cluster (worklist)** lists hives whose owner
    belongs to no cluster, with a note explaining that assigning the beekeeper is usually the better
    fix.
20. **Beekeeper** → the same hive: the cluster is shown as read-only information and no placement
    control is offered; the KVIC cluster URL is refused.

Feeding the pipeline with development data (every packet is labelled `SIMULATOR`):

```bash
cd HoneyChain/backend
# 20 packets over HTTP, one every 30 s
.venv/bin/python -m app.scripts.hive_simulator \
    --device ESP32-GNT-0001 --transport http \
    --email beekeeper@honeychain.example.com --password HoneyPass123 \
    --interval 30 --count 20

# the same packets over a broker, once MQTT_BROKER_URL is set in backend/.env
.venv/bin/python -m app.scripts.hive_simulator --device ESP32-GNT-0001 --transport mqtt --count 12

# see what would be sent, without sending it
.venv/bin/python -m app.scripts.hive_simulator --device ESP32-GNT-0001 --dry-run --count 2

# recompute stored device status (ONLINE / WARNING / OFFLINE) — cron this in a deployment
.venv/bin/python -m app.scripts.device_status_sweep
```

To exercise the MQTT leg locally: `sudo apt-get install -y mosquitto` then `mosquitto -p 1883 &`, set
`MQTT_BROKER_URL=localhost` in `backend/.env`, restart the API, and watch
`curl localhost:8000/api/v1/health/mqtt` while the simulator publishes.

### 3.3 Automated checks

```bash
# Backend test suite (474 tests, runs against PostgreSQL honeychain_test)
cd HoneyChain/backend && .venv/bin/python -m pytest

# Per module
.venv/bin/python -m pytest tests/test_hives.py tests/test_iot_devices.py \
    tests/test_telemetry.py tests/test_mqtt_ingest.py        # 154 Phase-3 tests
.venv/bin/python -m pytest tests/test_ai_engine.py tests/test_ai_repository.py \
    tests/test_ai_insights.py                                # 88 Phase-4 tests
.venv/bin/python -m pytest tests/test_cluster_relationships.py   # 42 Phase-4.1 tests

# HTTP smoke tests (need PostgreSQL + API running; each cleans up after itself)
.venv/bin/python tests/api_smoke_phase2.py       # 43 checks — Phase 2 endpoints
.venv/bin/python tests/api_smoke_phase3.py       # 64 checks — Phase 3 endpoints, ingest and refusals
.venv/bin/python tests/api_smoke_phase4.py       # 73 checks — Phase 4 AI insights and alerts
.venv/bin/python tests/api_smoke_phase41.py      # 43 checks — Phase 4.1 organisational chain

# Browser walks (need Chromium: playwright install chromium && playwright install-deps chromium).
# Run against the production preview; SMOKE_BASE_URL overrides the target.
cd ../frontend && npm run build && npm run preview -- --port 4173 &
cd ../backend
.venv/bin/python tests/browser_smoke.py          # 36 checks — Phase 1 flows
.venv/bin/python tests/browser_smoke_phase2.py   # 27 checks — Phase 2 flows
.venv/bin/python tests/browser_smoke_phase3.py   # 111 checks — Phase 3 flows, isolation, layout
.venv/bin/python tests/browser_smoke_phase41.py  # 26 checks — Phase 4.1 cluster view and placement

# Frontend production build and lint
cd ../frontend && npm run build && npx eslint "src/**/*.{js,jsx}"
```

---

## 4. Accounts

All development accounts are created by `python -m app.scripts.seed_dev_data` (**DEVELOPMENT ONLY**
— the script refuses to run against a production database):

| Email | Role | Password |
| --- | --- | --- |
| `admin@honeychain.example.com` | ADMIN | `AdminSecure123` |
| `kvic@honeychain.example.com` | KVIC_OFFICER | `KvicSecure123` |
| `beekeeper@honeychain.example.com` | BEEKEEPER | `HoneyPass123` |
| `consumer@honeychain.example.com` | CONSUMER | `ConsumerPass123` |

The seeded beekeeper is `VERIFIED` and belongs to cluster `KVIC-GNT-001`, so the directory, cluster
and verification screens have real data.

Or register a new account — `/register` is open for **consumers and beekeepers**; the other eight
roles are provisioned from the server (they cannot be self-assigned, by design).

### Creating a privileged account

`ADMIN`, `KVIC_OFFICER` and `LAB_TECHNICIAN` **cannot** be self-registered (privilege-escalation
guard), so they are provisioned from the server:

```bash
cd HoneyChain/backend && source .venv/bin/activate

.venv/bin/python -m app.scripts.create_admin \
  --email admin@example.org \
  --name "Platform Administrator" \
  --role ADMIN \
  --district Guntur --state "Andhra Pradesh"

# Non-interactive (CI / containers):
DEFAULT_ADMIN_PASSWORD='…' .venv/bin/python -m app.scripts.create_admin \
  --email admin@example.org --name "Platform Administrator"
```

The password is read without echoing, never logged, and stored only as a bcrypt hash.

---

## 5. Common tasks

### Database migrations

```bash
cd HoneyChain/backend && source .venv/bin/activate

alembic upgrade head                                   # apply all
alembic current                                        # show applied revision
alembic history                                        # list revisions
alembic revision --autogenerate -m "add hives"          # generate, then REVIEW the file
alembic downgrade -1                                   # step back one
```

### Inspecting the database

```bash
psql "postgresql://honeychain:honeychain_dev_password@localhost:5432/honeychain_dev"
# \dt           list tables
# \d users      describe the users table
# \q            quit
```

### Running the API on another host/port

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
# then point the frontend at it:  VITE_PROXY_TARGET=http://localhost:8080 in frontend/.env
```

### Switching environment

The backend reads, in order (later wins):
`<repo>/.env` → `backend/.env` → `backend/.env.<ENVIRONMENT>` → real environment variables.

```bash
HONEYCHAIN_ENV=production uvicorn app.main:app      # refuses to start on placeholder secrets
```

---

## 6. Stopping and restarting

```bash
# Stop the app servers: Ctrl+C in their terminals, or
pkill -f "uvicorn app.main:app"
pkill -f "vite"

# Stop PostgreSQL
sudo pg_ctlcluster 17 main stop

# Restart everything (short form)
sudo pg_ctlcluster 17 main start
cd HoneyChain/backend  && .venv/bin/uvicorn app.main:app --reload --port 8000 &
cd HoneyChain/frontend && npm run dev
```

---

## 7. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Footer shows **API status: Offline** | Backend not running, or wrong proxy target. Start uvicorn; check `VITE_PROXY_TARGET` in `frontend/.env`. |
| `401` immediately after signing in | `JWT_SECRET_KEY` changed while the old token was in use. Clear browser storage or sign in again. |
| `403 ACCOUNT_INACTIVE` | The account was deactivated by an admin: `PATCH /api/v1/admin/users/{id}/status`. |
| `could not connect to server: Connection refused` | PostgreSQL is not running → `sudo pg_ctlcluster 17 main start`. |
| `relation "users" does not exist` | Migrations not applied → `alembic upgrade head`. |
| `password authentication failed for user "honeychain"` | `DATABASE_URL` credentials do not match the role. Fix `backend/.env` or recreate the role. |
| `Blocked request. This host is not allowed` (Vite) | Add the hostname to `VITE_ALLOWED_HOSTS` in `frontend/.env`, or leave it empty to accept any host. |
| CORS error in the console | Only occurs when the SPA calls the API on a different origin directly. Add that origin to `CORS_ORIGINS` in `backend/.env`. |
| Table shows "No records found" | Working as intended — the module for that data has not been released yet (Phase 2+). |
| `email is not a valid email address` on register | `email-validator` rejects reserved TLDs such as `.test`. Use a normal domain. |
| `ModuleNotFoundError` in the backend | Virtualenv not active, or dependencies missing → `source .venv/bin/activate && pip install -r requirements.txt`. |

### Check what is listening

```bash
ss -ltnp | grep -E ':(5432|8000|5173)'
```

---

## 8. What is and is not implemented

**Working now (Phase 1 — foundation):**

- Register, sign in, sign out, session refresh, profile editing
- Ten roles in one authentication system, with role-based access control
- Protected routing on the client, enforced independently by the API
- Public site: landing page, how it works, about, contact
- Dashboard shell with sidebar/topbar, role workspaces, administrator workspace with live counts
- Health endpoints, structured logging, standard error envelope

**Working now (Phase 2 — user, role & beekeeper management):**

- Profiles (`/profile`): personal, location and account details, plus apiary extras for beekeepers
- Beekeeper registry with backend-generated codes (`BKR-GNT-00001`) and an apiary profile screen
- KVIC clusters: create, edit, activate/deactivate, add and remove members
- Verification workflow (`PENDING → UNDER_REVIEW → VERIFIED/REJECTED/SUSPENDED`) with remarks and an
  append-only history, for administrators and KVIC officers
- Administrator user directory: search, role/status filters, pagination, activate/deactivate
- Audit trail with filters and pagination
- Role-based post-login redirects and a role-aware sidebar

**Not implemented yet — the UI says so rather than faking it:**

- Hive registry, inspections and harvest records (next phase)
- Live hive/sensor data and IoT ingest (next phase)
- Batch and QR traceability, laboratory workflows, blockchain anchoring (later)
- AI risk/yield insights, KVIC analytics and exports (later)

Placeholder screens are labelled **Planned — Phase N** and show em-dashes instead of invented
numbers. No endpoint returns fabricated data.

---

## 9. Environment variables (essentials)

`backend/.env`:

```env
ENVIRONMENT=development
DATABASE_URL=postgresql+psycopg://honeychain:honeychain_dev_password@localhost:5432/honeychain_dev
JWT_SECRET_KEY=<generate: python3 -c "import secrets; print(secrets.token_urlsafe(64))">
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=14
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
AUTH_EXPOSE_REFRESH_IN_BODY=true          # dev convenience for curl/Postman
LOG_JSON=false                            # human-readable logs locally
```

`frontend/.env` (no secrets — everything `VITE_*` ships to the browser):

```env
VITE_API_BASE_URL=/api/v1
VITE_PROXY_TARGET=http://localhost:8000
VITE_ALLOWED_HOSTS=                       # empty = accept any host (dev only)
```

Full templates: `backend/.env.example`, `backend/.env.development.example`,
`backend/.env.production.example`, `frontend/.env.example`.

---

## 10. Reset to a clean database

```bash
cd HoneyChain/backend && source .venv/bin/activate

# Drop and recreate the schema, then re-apply migrations
alembic downgrade base
alembic upgrade head

# Or start over completely
sudo -u postgres psql -c "DROP DATABASE honeychain_dev;" \
                     -c "CREATE DATABASE honeychain_dev OWNER honeychain;"
alembic upgrade head
.venv/bin/python -m app.scripts.create_admin --email admin@honeychain.example.com \
  --name "Platform Administrator"
```
