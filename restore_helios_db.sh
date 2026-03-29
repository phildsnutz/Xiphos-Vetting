#!/bin/bash
# Helios DB Restore Script - Restore from latest backup after a container rebuild
# Usage: ./restore_helios_db.sh

CONTAINER=$(docker ps --format '{{.Names}}' | grep xiphos | head -1)
BACKUP_DIR="$(dirname "$0")/backups"

if [ -z "$CONTAINER" ]; then
    echo "ERROR: No running Xiphos container found."
    exit 1
fi

if [ ! -f "$BACKUP_DIR/xiphos_latest.db" ]; then
    echo "ERROR: No backup found at $BACKUP_DIR/xiphos_latest.db"
    echo "Run backup_helios_db.sh first to create a backup."
    exit 1
fi

MAIN_DB_PATH=$(docker exec "$CONTAINER" sh -lc 'printf "%s" "${XIPHOS_DB_PATH:-/data/xiphos.db}"')
KG_DB_PATH=$(docker exec "$CONTAINER" sh -lc 'printf "%s" "${XIPHOS_KG_DB_PATH:-/data/knowledge_graph.db}"')

echo "Restoring to container: $CONTAINER"
echo "Backup files:"
ls -lh "$BACKUP_DIR"/*_latest.db

read -p "Proceed with restore? (y/N): " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Aborted."
    exit 0
fi

docker cp "$BACKUP_DIR/xiphos_latest.db" "$CONTAINER:$MAIN_DB_PATH" && echo "  Restored $MAIN_DB_PATH"
docker cp "$BACKUP_DIR/kg_latest.db" "$CONTAINER:$KG_DB_PATH" && echo "  Restored $KG_DB_PATH"

echo "Restarting container..."
docker restart "$CONTAINER"
echo "Restore complete. Container restarting."
