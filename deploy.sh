#!/bin/bash
# ============================================================
#  Xiphos Deploy Script
#  Usage: ./deploy.sh [options]
#
#  Deploys the latest version from GitHub to the DigitalOcean
#  droplet, rebuilds Docker, sets org AI config, and verifies.
#
#  Options:
#    --skip-ai       Skip AI org-default configuration
#    --reset-db      Wipe and recreate the database
#    --sync          Sync sanctions lists after deploy
#    --dry-run       Show commands without executing
# ============================================================

set -euo pipefail

# ---- Configuration ----
DROPLET_IP="209.38.141.101"
SSH_KEY="$HOME/.ssh/xiphos_do"
SSH_USER="root"
REMOTE_DIR="/opt/xiphos"
DOCKER_PORT=8080

# AI org-default config
# Set XIPHOS_AI_KEY env var or pass --skip-ai to skip
AI_PROVIDER="${XIPHOS_AI_PROVIDER:-openai}"
AI_MODEL="${XIPHOS_AI_MODEL:-gpt-4o}"
AI_KEY="${XIPHOS_AI_KEY:-}"

# ---- Parse args ----
SKIP_AI=false
RESET_DB=false
SYNC_SANCTIONS=false
DRY_RUN=false

for arg in "$@"; do
  case $arg in
    --skip-ai)       SKIP_AI=true ;;
    --reset-db)      RESET_DB=true ;;
    --sync)          SYNC_SANCTIONS=true ;;
    --dry-run)       DRY_RUN=true ;;
    *)               echo "Unknown option: $arg"; exit 1 ;;
  esac
done

SSH_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$DROPLET_IP"

run() {
  echo ""
  echo ">> $1"
  if [ "$DRY_RUN" = true ]; then
    echo "   [dry-run] $2"
  else
    $SSH_CMD "$2"
  fi
}

echo "============================================================"
echo "  XIPHOS DEPLOYMENT"
echo "  Target: $SSH_USER@$DROPLET_IP"
echo "  Dir:    $REMOTE_DIR"
echo "============================================================"

# Step 1: Pull latest code
run "Pulling latest from GitHub..." \
    "cd $REMOTE_DIR && git pull origin main"

# Step 2: Rebuild Docker
run "Rebuilding Docker containers..." \
    "cd $REMOTE_DIR && docker compose down && docker compose build --no-cache && docker compose up -d"

# Step 3: Wait for startup
echo ""
echo ">> Waiting 20s for container startup..."
if [ "$DRY_RUN" = false ]; then
  sleep 20
fi

# Step 4: Health check
run "Checking health..." \
    "curl -sf http://localhost:$DOCKER_PORT/api/health | python3 -c \"import sys,json; d=json.load(sys.stdin); print(f'  Version: {d[\\\"version\\\"]}'); print(f'  AI:      {d[\\\"ai_enabled\\\"]}'); print(f'  OSINT:   {d[\\\"osint_enabled\\\"]}'); print(f'  Vendors: {d[\\\"stats\\\"][\\\"vendors\\\"]}')\""

# Step 5: Set AI org default
if [ "$SKIP_AI" = false ] && [ -n "$AI_KEY" ]; then
  run "Setting org-wide AI default ($AI_PROVIDER/$AI_MODEL)..." \
      "curl -sf -X POST http://localhost:$DOCKER_PORT/api/ai/config/org-default \
        -H 'Content-Type: application/json' \
        -d '{\"provider\":\"$AI_PROVIDER\",\"model\":\"$AI_MODEL\",\"api_key\":\"$AI_KEY\"}'"
fi

# Step 6: Sanctions sync (optional)
if [ "$SYNC_SANCTIONS" = true ]; then
  run "Syncing sanctions lists (OFAC, UK, EU, UN)..." \
      "curl -sf -X POST http://localhost:$DOCKER_PORT/api/sanctions/sync \
        -H 'Content-Type: application/json' | python3 -c \"import sys,json; d=json.load(sys.stdin); [print(f'  {r[\\\"source\\\"]}: {r[\\\"entries_loaded\\\"]} entries') for r in d.get(\\\"results\\\",[])]\" 2>/dev/null || echo '  Sync module not available (non-blocking)'"
fi

# Step 7: Reset DB (optional)
if [ "$RESET_DB" = true ]; then
  run "Resetting database..." \
      "cd $REMOTE_DIR && docker compose exec -T xiphos python3 -c 'import db; import os; os.remove(db.get_db_path()); db.init_db(); print(\"  Database reset complete\")'"
fi

# Step 8: Final verification
run "Running final verification..." \
    "curl -sf http://localhost:$DOCKER_PORT/api/ai/providers | python3 -c \"import sys,json; d=json.load(sys.stdin); print('  AI Providers: ' + ', '.join(p['display_name'] for p in d['providers']))\" && \
     curl -sf http://localhost:$DOCKER_PORT/api/ai/config | python3 -c \"import sys,json; d=json.load(sys.stdin); print(f'  Org AI Config: {d.get(\\\"provider\\\",\\\"none\\\")}/{d.get(\\\"model\\\",\\\"none\\\")}' if d.get('configured') else '  Org AI Config: not set')\""

echo ""
echo "============================================================"
echo "  DEPLOYMENT COMPLETE"
echo "  Dashboard: http://$DROPLET_IP:$DOCKER_PORT"
echo "============================================================"
echo ""
echo "  Quick test:"
echo "  curl http://$DROPLET_IP:$DOCKER_PORT/api/health"
echo ""
