#!/bin/bash
# Helios DB Backup Script - Run anytime to snapshot both databases
# Usage: ./backup_helios_db.sh

CONTAINER=$(docker ps --format '{{.Names}}' | grep xiphos | head -1)
BACKUP_DIR="$(dirname "$0")/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if [ -z "$CONTAINER" ]; then
    echo "ERROR: No running Xiphos container found."
    exit 1
fi

MAIN_DB_PATH=$(docker exec "$CONTAINER" sh -lc 'printf "%s" "${XIPHOS_DB_PATH:-/data/xiphos.db}"')
KG_DB_PATH=$(docker exec "$CONTAINER" sh -lc 'printf "%s" "${XIPHOS_KG_DB_PATH:-/data/knowledge_graph.db}"')
SANCTIONS_DB_PATH=$(docker exec "$CONTAINER" sh -lc 'printf "%s" "${XIPHOS_SANCTIONS_DB:-/data/sanctions.db}"')

mkdir -p "$BACKUP_DIR"

echo "Backing up from container: $CONTAINER"
docker cp "$CONTAINER:$MAIN_DB_PATH" "$BACKUP_DIR/xiphos_${TIMESTAMP}.db" && echo "  $MAIN_DB_PATH -> backups/xiphos_${TIMESTAMP}.db"
docker cp "$CONTAINER:$KG_DB_PATH" "$BACKUP_DIR/kg_${TIMESTAMP}.db" && echo "  $KG_DB_PATH -> backups/kg_${TIMESTAMP}.db"
docker cp "$CONTAINER:$SANCTIONS_DB_PATH" "$BACKUP_DIR/sanctions_${TIMESTAMP}.db" && echo "  $SANCTIONS_DB_PATH -> backups/sanctions_${TIMESTAMP}.db"

# Also keep a "latest" copy
docker cp "$CONTAINER:$MAIN_DB_PATH" "$BACKUP_DIR/xiphos_latest.db"
docker cp "$CONTAINER:$KG_DB_PATH" "$BACKUP_DIR/kg_latest.db"
docker cp "$CONTAINER:$SANCTIONS_DB_PATH" "$BACKUP_DIR/sanctions_latest.db"

# Prune backups older than 7 days
find "$BACKUP_DIR" -name "*.db" -mtime +7 -delete 2>/dev/null

echo "Backup complete. Files in: $BACKUP_DIR"
ls -lh "$BACKUP_DIR"/*.db 2>/dev/null
