#!/usr/bin/env bash
#
# Rebuild the development environment from scratch.
#
# The sandbox this project is developed in is periodically reset: the PostgreSQL
# installation, the Python virtualenv, `node_modules`, the built frontend and any
# running server disappear, while the project files themselves survive. This script
# puts all of it back, in the order that works, so recovery is one command instead
# of a debugging session.
#
#   bash dev-rebuild.sh            # database, venv, dependencies, migrations, seed
#   bash dev-rebuild.sh --serve    # …and start the API and the frontend
#
# It is idempotent: an already-running database, an existing venv and an existing
# node_modules are reused rather than recreated.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
SERVE=0
[[ "${1:-}" == "--serve" ]] && SERVE=1

# The development credentials live in backend/.env; read them from there rather
# than repeating them here.
DB_URL="$(grep -E '^DATABASE_URL=' "$BACKEND/.env" | cut -d= -f2-)"
DB_USER="$(echo "$DB_URL" | sed -E 's|.*://([^:]+):.*|\1|')"
DB_PASSWORD="$(echo "$DB_URL" | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')"
# The suite names its database itself: tests/conftest.py defaults DATABASE_URL to
# .../honeychain_test, so the recovery script creates that name rather than a
# derived one — otherwise pytest silently falls back to SQLite.
TEST_DB="honeychain_test"

step() { printf '\n=== %s\n' "$1"; }

step "PostgreSQL"
if ! command -v psql >/dev/null 2>&1; then
  # The sandbox image ships a stale package index; refresh it first, or apt fails
  # with 404s for the exact versions it remembers.
  sudo apt-get update -qq
  sudo apt-get install -y postgresql postgresql-contrib >/dev/null
fi
if ! pg_isready -q 2>/dev/null; then
  sudo pg_ctlcluster 17 main start || sudo service postgresql start
  sleep 2
fi
pg_isready

step "Roles and databases"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 \
  || sudo -u postgres psql -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD' SUPERUSER"
for db in "$(echo "$DB_URL" | sed -E 's|.*/||')" "$TEST_DB"; do
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
    || sudo -u postgres createdb -O "$DB_USER" "$db"
done
sudo -u postgres psql -c '\l' | grep honeychain

step "Python environment"
cd "$BACKEND"
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

step "Migrations and seed data"
.venv/bin/alembic upgrade head
.venv/bin/python -m app.scripts.seed_dev_data
.venv/bin/python -m app.scripts.seed_lab_parameters 2>/dev/null || true

step "Frontend dependencies and build"
cd "$FRONTEND"
[[ -d node_modules ]] || npm install --no-audit --no-fund
npm run build

if [[ "$SERVE" == "1" ]]; then
  step "Servers"
  cd "$BACKEND"
  pkill -f "app.main:app" 2>/dev/null || true
  nohup .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/api-server.log 2>&1 &
  cd "$FRONTEND"
  pkill -f "vite preview" 2>/dev/null || true
  nohup npm run preview -- --host 0.0.0.0 --port 4173 > /tmp/frontend.log 2>&1 &
  sleep 6
  curl -s -o /dev/null -w 'API /health: %{http_code}\n' http://localhost:8000/api/v1/health
  curl -s -o /dev/null -w 'Frontend:   %{http_code}\n' http://localhost:4173/
fi

printf '\nEnvironment ready.\n'
