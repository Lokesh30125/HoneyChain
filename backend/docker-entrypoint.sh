#!/bin/sh
# Bring the schema up to date, optionally seed the laboratory parameter
# catalogue and the first administrator, then hand over to the server.
set -eu

echo "[entrypoint] applying database migrations"
alembic upgrade head

# The parameter catalogue is configuration, not demo data: installing it is
# idempotent and never sets a reference range (an administrator does that).
python -m app.scripts.seed_lab_parameters || echo "[entrypoint] lab parameter catalogue not installed"

# First administrator, only when both values are provided. The password is read
# from the environment by the script and never echoed.
if [ -n "${BOOTSTRAP_ADMIN_EMAIL:-}" ] && [ -n "${DEFAULT_ADMIN_PASSWORD:-}" ]; then
  python -m app.scripts.create_admin \
    --email "$BOOTSTRAP_ADMIN_EMAIL" \
    --name "${BOOTSTRAP_ADMIN_NAME:-Platform Administrator}" \
    --role ADMIN || echo "[entrypoint] administrator already exists"
fi

exec "$@"
