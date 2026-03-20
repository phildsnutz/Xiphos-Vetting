#!/bin/bash
# ============================================================
#  Xiphos Deploy Script
#  Usage: ./deploy.sh [options]
#
#  Preferred flow:
#    1. Copy deploy.env.example to deploy.env
#    2. Fill in SSH target, base URL, and optional admin creds
#    3. Run ./deploy.sh --with-ssl
#
#  The shell deploy path is intended for key-based SSH access or
#  SSH config aliases. For password-based deploys, use deploy.py.
#
#  Preferred env:
#    XIPHOS_DEPLOY_SSH_TARGET     SSH alias or user@host
#
#  Fallback env:
#    XIPHOS_DEPLOY_HOST           Remote SSH host/IP
#    XIPHOS_DEPLOY_SSH_USER       SSH user (default: root)
#
#  Optional env:
#    XIPHOS_DEPLOY_SSH_KEY        SSH private key path
#    XIPHOS_DEPLOY_SSH_KEY_PATH   Legacy alias for SSH key path
#    XIPHOS_REMOTE_DIR            Remote app dir (default: /opt/xiphos)
#    XIPHOS_DOCKER_PORT           Exposed app port (default: 8080)
#    XIPHOS_PUBLIC_BASE_URL       Public app URL
#    XIPHOS_DEPLOY_APP_URL        Legacy alias for public app URL
#    XIPHOS_DEPLOY_ADMIN_EMAIL    Admin/reviewer login for verification
#    XIPHOS_DEPLOY_ADMIN_PASSWORD Admin/reviewer password for verification
#    XIPHOS_DEPLOY_LOGIN_EMAIL    Legacy alias for admin email
#    XIPHOS_DEPLOY_LOGIN_PASSWORD Legacy alias for admin password
#    XIPHOS_DEPLOY_VERIFY_TLS     true/false. Defaults by URL scheme
#    XIPHOS_AI_PROVIDER           Org-default AI provider (default: openai)
#    XIPHOS_AI_MODEL              Org-default AI model (default: gpt-4o)
#    XIPHOS_AI_KEY                Org-default AI API key
#
#  Options:
#    --skip-ai        Skip AI org-default configuration
#    --skip-verify    Skip post-deploy verification
#    --verify-only    Run verification only
#    --with-ssl       Run deploy-ssl.sh after app rollout
#    --reset-db       Wipe and recreate the database
#    --sync           Sync sanctions lists after deploy
#    --dry-run        Show commands without executing
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${XIPHOS_DEPLOY_ENV_FILE:-$SCRIPT_DIR/deploy.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

SSH_TARGET="${XIPHOS_DEPLOY_SSH_TARGET:-}"
DEPLOY_HOST="${XIPHOS_DEPLOY_HOST:-}"
SSH_USER="${XIPHOS_DEPLOY_SSH_USER:-root}"
SSH_KEY="${XIPHOS_DEPLOY_SSH_KEY:-${XIPHOS_DEPLOY_SSH_KEY_PATH:-}}"
REMOTE_DIR="${XIPHOS_REMOTE_DIR:-${XIPHOS_DEPLOY_REMOTE_DIR:-/opt/xiphos}}"
DOCKER_PORT="${XIPHOS_DOCKER_PORT:-8080}"
PUBLIC_BASE_URL="${XIPHOS_PUBLIC_BASE_URL:-${XIPHOS_DEPLOY_APP_URL:-}}"
ADMIN_EMAIL="${XIPHOS_DEPLOY_ADMIN_EMAIL:-${XIPHOS_DEPLOY_LOGIN_EMAIL:-}}"
ADMIN_PASSWORD="${XIPHOS_DEPLOY_ADMIN_PASSWORD:-${XIPHOS_DEPLOY_LOGIN_PASSWORD:-}}"
VERIFY_TLS_RAW="${XIPHOS_DEPLOY_VERIFY_TLS:-}"

AI_PROVIDER="${XIPHOS_AI_PROVIDER:-openai}"
AI_MODEL="${XIPHOS_AI_MODEL:-gpt-4o}"
AI_KEY="${XIPHOS_AI_KEY:-}"

SKIP_AI=false
SKIP_VERIFY=false
VERIFY_ONLY=false
RESET_DB=false
SYNC_SANCTIONS=false
DRY_RUN=false
WITH_SSL=false

for arg in "$@"; do
  case "$arg" in
    --skip-ai) SKIP_AI=true ;;
    --skip-verify) SKIP_VERIFY=true ;;
    --verify-only) VERIFY_ONLY=true ;;
    --reset-db) RESET_DB=true ;;
    --sync) SYNC_SANCTIONS=true ;;
    --dry-run) DRY_RUN=true ;;
    --with-ssl) WITH_SSL=true ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

if [ -z "$SSH_TARGET" ]; then
  if [ -z "$DEPLOY_HOST" ]; then
    echo "Set XIPHOS_DEPLOY_SSH_TARGET or XIPHOS_DEPLOY_HOST before running deploy.sh"
    exit 1
  fi
  SSH_TARGET="${SSH_USER}@${DEPLOY_HOST}"
fi

if [ -z "$PUBLIC_BASE_URL" ] && [ -n "$DEPLOY_HOST" ]; then
  PUBLIC_BASE_URL="http://${DEPLOY_HOST}:${DOCKER_PORT}"
fi

if [ -z "$PUBLIC_BASE_URL" ] && { [ "$SKIP_VERIFY" = false ] || [ "$VERIFY_ONLY" = true ]; }; then
  echo "Set XIPHOS_PUBLIC_BASE_URL (or XIPHOS_DEPLOY_APP_URL) before running verification."
  exit 1
fi

if [ -z "$VERIFY_TLS_RAW" ]; then
  case "$PUBLIC_BASE_URL" in
    https://*) export XIPHOS_DEPLOY_VERIFY_TLS=true ;;
    *) export XIPHOS_DEPLOY_VERIFY_TLS=false ;;
  esac
else
  export XIPHOS_DEPLOY_VERIFY_TLS="$VERIFY_TLS_RAW"
fi

export XIPHOS_DEPLOY_SSH_TARGET="$SSH_TARGET"
export XIPHOS_DEPLOY_SSH_KEY="${SSH_KEY}"
export XIPHOS_REMOTE_DIR="$REMOTE_DIR"
export XIPHOS_DOCKER_PORT="$DOCKER_PORT"
export XIPHOS_PUBLIC_BASE_URL="$PUBLIC_BASE_URL"
export XIPHOS_DEPLOY_ADMIN_EMAIL="$ADMIN_EMAIL"
export XIPHOS_DEPLOY_ADMIN_PASSWORD="$ADMIN_PASSWORD"

SSH_ARGS=(-o StrictHostKeyChecking=accept-new)
if [ -n "$SSH_KEY" ]; then
  SSH_ARGS+=(-i "$SSH_KEY")
fi

remote_exec() {
  local cmd="$1"
  if [ "$DRY_RUN" = true ]; then
    echo "   [dry-run] ssh ${SSH_ARGS[*]} $SSH_TARGET $cmd"
  else
    ssh "${SSH_ARGS[@]}" "$SSH_TARGET" "$cmd"
  fi
}

run() {
  echo ""
  echo ">> $1"
  remote_exec "$2"
}

verify_local() {
  if [ "$DRY_RUN" = true ]; then
    echo ""
    echo ">> [dry-run] python3 $SCRIPT_DIR/deploy.py --verify-only"
  else
    python3 "$SCRIPT_DIR/deploy.py" --verify-only
  fi
}

AI_PROVIDER_Q=$(printf '%q' "$AI_PROVIDER")
AI_MODEL_Q=$(printf '%q' "$AI_MODEL")
AI_KEY_Q=$(printf '%q' "$AI_KEY")

REMOTE_AI_SAVE_CMD=$(cat <<EOF
cd $REMOTE_DIR && docker compose exec -T -e XIPHOS_SCRIPT_PROVIDER=$AI_PROVIDER_Q -e XIPHOS_SCRIPT_MODEL=$AI_MODEL_Q -e XIPHOS_SCRIPT_KEY=$AI_KEY_Q -w /app/backend xiphos python3 -c "from ai_analysis import init_ai_tables, save_ai_config; import os; init_ai_tables(); save_ai_config('__org_default__', os.environ['XIPHOS_SCRIPT_PROVIDER'], os.environ['XIPHOS_SCRIPT_MODEL'], os.environ['XIPHOS_SCRIPT_KEY']); print('  Org AI default saved')"
EOF
)

REMOTE_AI_VERIFY_CMD=$(cat <<'EOF'
cd __REMOTE_DIR__ && docker compose exec -T -w /app/backend xiphos python3 -c "from ai_analysis import init_ai_tables, get_available_providers, get_ai_config; init_ai_tables(); providers = get_available_providers(); print('  AI Providers: ' + ', '.join(p['display_name'] for p in providers)); cfg = get_ai_config('__org_default__'); print('  Org AI Config: ' + (f\"{cfg['provider']}/{cfg['model']}\" if cfg else 'not set'))"
EOF
)
REMOTE_AI_VERIFY_CMD="${REMOTE_AI_VERIFY_CMD/__REMOTE_DIR__/$REMOTE_DIR}"

echo "============================================================"
echo "  XIPHOS DEPLOYMENT"
echo "  Target: $SSH_TARGET"
echo "  Dir:    $REMOTE_DIR"
echo "============================================================"

if [ "$VERIFY_ONLY" = true ]; then
  verify_local
  exit 0
fi

run "Pulling latest from Git..." "cd $REMOTE_DIR && git pull --ff-only"
run "Rebuilding Docker containers..." "cd $REMOTE_DIR && docker compose down && docker compose build --no-cache && docker compose up -d"

echo ""
echo ">> Waiting 20s for container startup..."
if [ "$DRY_RUN" = false ]; then
  sleep 20
fi

run "Checking health..." "curl -sf http://localhost:$DOCKER_PORT/api/health | python3 -c \"import sys,json; d=json.load(sys.stdin); print(f'  Version: {d.get(\\\"version\\\", \\\"unknown\\\")}'); print(f'  AI:      {d.get(\\\"ai_enabled\\\", True)}'); print(f'  OSINT:   {d.get(\\\"osint_enabled\\\", True)}'); print(f'  Vendors: {d.get(\\\"stats\\\", {}).get(\\\"vendors\\\", 0)}')\""

if [ "$SKIP_AI" = false ] && [ -n "$AI_KEY" ]; then
  run "Setting org-wide AI default ($AI_PROVIDER/$AI_MODEL)..." "$REMOTE_AI_SAVE_CMD"
elif [ "$SKIP_AI" = false ]; then
  echo ""
  echo ">> Skipping org AI default configuration (set XIPHOS_AI_KEY to enable)"
fi

if [ "$SYNC_SANCTIONS" = true ]; then
  run "Syncing sanctions lists..." "cd $REMOTE_DIR && docker compose exec -T -w /app/backend xiphos python3 sanctions_sync.py --sources ofac uk eu un"
fi

if [ "$RESET_DB" = true ]; then
  run "Resetting database..." "cd $REMOTE_DIR && docker compose exec -T -w /app/backend xiphos python3 -c 'import db, os; path = db.get_db_path(); os.path.exists(path) and os.remove(path); db.init_db(); print(\"  Database reset complete\")'"
fi

run "Verifying AI/runtime inside the container..." "$REMOTE_AI_VERIFY_CMD"

if [ "$WITH_SSL" = true ]; then
  echo ""
  echo ">> Running SSL setup..."
  if [ "$DRY_RUN" = true ]; then
    "$SCRIPT_DIR/deploy-ssl.sh" --dry-run
  else
    "$SCRIPT_DIR/deploy-ssl.sh"
  fi
fi

if [ "$SKIP_VERIFY" = false ]; then
  verify_local
fi

echo ""
echo "============================================================"
echo "  DEPLOYMENT COMPLETE"
echo "  URL:       ${PUBLIC_BASE_URL:-<unset>}"
if [ -n "$PUBLIC_BASE_URL" ]; then
  echo "  Health:    ${PUBLIC_BASE_URL%/}/api/health"
fi
echo "============================================================"
echo ""
echo "Quick test:"
if [ -n "$PUBLIC_BASE_URL" ]; then
  echo "curl ${PUBLIC_BASE_URL%/}/api/health"
else
  echo "curl http://localhost:${DOCKER_PORT}/api/health"
fi
echo ""
