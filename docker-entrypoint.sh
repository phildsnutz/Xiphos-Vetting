#!/bin/bash
set -e

echo "=== Xiphos v2.9 ==="
echo "Data dir: ${XIPHOS_DATA_DIR:-/data}"
echo "DB engine: ${HELIOS_DB_ENGINE:-sqlite}"
echo "Auth: ${XIPHOS_AUTH_ENABLED:-false}"
export XIPHOS_ENABLE_PERIODIC_MONITORING="${XIPHOS_ENABLE_PERIODIC_MONITORING:-true}"
echo "Periodic monitoring: ${XIPHOS_ENABLE_PERIODIC_MONITORING}"

# Fail fast if auth is enabled without a real signing secret
if [ "${XIPHOS_AUTH_ENABLED:-false}" = "true" ]; then
    if [ -z "${XIPHOS_SECRET_KEY:-}" ] || [ "${XIPHOS_SECRET_KEY}" = "CHANGE-ME-IN-PRODUCTION" ] || [ "${XIPHOS_SECRET_KEY}" = "xiphos-dev-secret-change-in-production" ]; then
        echo "ERROR: XIPHOS_AUTH_ENABLED=true but XIPHOS_SECRET_KEY is missing or placeholder-valued."
        echo "  Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
        exit 1
    fi
fi

# Initialize databases
cd /app/backend
python3 -c "import db; db.init_db(); db.migrate_add_profile_column(); from auth import init_auth_db; init_auth_db(); from ai_analysis import init_ai_tables; init_ai_tables(); print('  Databases initialized')"

# Sanctions sync: skip in CI or when XIPHOS_SKIP_SYNC=true
DATA_DIR="${XIPHOS_DATA_DIR:-$(dirname "${XIPHOS_DB_PATH:-/data/xiphos.db}")}"
SANCTIONS_DB="${XIPHOS_SANCTIONS_DB:-$DATA_DIR/sanctions.db}"
if [ "${XIPHOS_SKIP_SYNC:-false}" = "true" ]; then
    echo "  Sanctions sync: skipped (XIPHOS_SKIP_SYNC=true)"
elif [ ! -f "$SANCTIONS_DB" ]; then
    echo "First boot: syncing sanctions lists (OFAC, UK, EU, UN)..."
    python3 sanctions_sync.py --sources ofac,uk,eu,un || echo "WARNING: Sanctions sync failed, will use fallback list"
else
    echo "  Sanctions DB exists, skipping sync (trigger via API if needed)"
fi

cd /app

echo "Starting gunicorn on :8080..."

# PostgreSQL can handle concurrent connections; use 2 workers
if [ "${HELIOS_DB_ENGINE:-sqlite}" = "postgres" ] || [ "${HELIOS_DB_ENGINE:-sqlite}" = "postgresql" ]; then
    WORKERS=2
    echo "PostgreSQL detected: using $WORKERS gunicorn workers"
else
    WORKERS=1
    echo "SQLite mode: using 1 gunicorn worker"
fi
exec gunicorn -c backend/gunicorn.conf.py --bind 0.0.0.0:8080 --workers $WORKERS --chdir backend server:app
