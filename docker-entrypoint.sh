#!/bin/bash
set -e

echo "=== Xiphos v2.7.1 ==="
echo "DB: $XIPHOS_DB_PATH"
echo "Auth: ${XIPHOS_AUTH_ENABLED:-false}"

# Warn if using default secret key in production
if [ "$XIPHOS_AUTH_ENABLED" = "true" ] && [ "$XIPHOS_SECRET_KEY" = "CHANGE-ME-IN-PRODUCTION" ]; then
    echo "WARNING: Using default secret key! Set XIPHOS_SECRET_KEY to a random value."
    echo "  Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
fi

# Initialize databases
cd /app/backend
python3 -c "import db; db.init_db(); from auth import init_auth_db; init_auth_db(); print('  Databases initialized')"

# Sanctions sync: skip in CI or when XIPHOS_SKIP_SYNC=true
SANCTIONS_DB="${XIPHOS_SANCTIONS_DB:-$(dirname "$XIPHOS_DB_PATH")/sanctions.db}"
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

# Start gunicorn (1 worker for SQLite safety, increase if moving to PostgreSQL)
exec gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 4 --timeout 300 --chdir backend server:app
