# Deploying HoneyChain with Docker Compose

Three services: **db** (PostgreSQL 16), **backend** (FastAPI + uvicorn; runs
migrations on start) and **frontend** (nginx serving the built React app and
proxying `/api` to the backend, so the app and the API share one origin). The
blockchain ledger is an external service reached by `BLOCKCHAIN_BASE_URL`.

## 1. Configure

```bash
cp .env.docker.example .env
```

Replace every `REPLACE_…` value in `.env`:

| Setting | What to put |
| --- | --- |
| `FRONTEND_URL`, `BACKEND_URL`, `CORS_ORIGINS` | the public `https://` address of the site |
| `PUBLIC_TRACE_BASE_URL` | `https://<site>/trace` — printed inside every QR label |
| `POSTGRES_PASSWORD` | a strong database password |
| `JWT_SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `BLOCKCHAIN_BASE_URL` | the ledger service URL, or set `BLOCKCHAIN_ENABLED=false` |
| `BOOTSTRAP_ADMIN_EMAIL` + `DEFAULT_ADMIN_PASSWORD` | first administrator (optional; clear them after first start) |

The API **refuses to start** in production when the JWT secret is the
placeholder or short, `DEBUG` is on, CORS is empty or `*`, a public URL still
points at localhost, the blockchain is enabled without a URL, or any
development switch (`LAB_ALLOW_RISK_OVERRIDE`, `LAB_DEMO_*`,
`AUTH_EXPOSE_REFRESH_IN_BODY`) is on. Interactive API docs are disabled in
production.

## 2. Start

```bash
docker compose up -d --build
docker compose ps          # all three services report (healthy)
```

The web client listens on `HTTP_PORT` (default 8080). Put a TLS terminator or
your cloud load balancer in front of it: authentication cookies are `Secure` in
production.

## 3. Operate

* Create further administrators: `docker compose exec -e DEFAULT_ADMIN_PASSWORD=… backend python -m app.scripts.create_admin --email … --name … --role ADMIN`
* Logs: `docker compose logs -f backend`
* Database backups: `docker compose exec db pg_dump -U honeychain honeychain > backup.sql`
* Upgrade: `docker compose up -d --build` (migrations run automatically).

The backend runs a single uvicorn worker on purpose: the MQTT consumer and the
blockchain outbox worker live inside the API process and must run once. To
scale out, run them in one instance only (`MQTT_CONSUMER_ENABLED=false`,
`BLOCKCHAIN_OUTBOX_WORKER_ENABLED=false` on the others).

Never run `app.scripts.seed_dev_data` against a deployment: it creates accounts
with published passwords, and it refuses to run outside development/testing or
against a non-local database.
