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
#  The shell deploy path performs an exact-tree sync from this local
#  workspace to the remote host, then rebuilds Docker in place.
#  For password-based deploys, use deploy.py.
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
#    XIPHOS_SECRET_KEY            App secret used by docker-compose on rebuild
#    XIPHOS_DEPLOY_SECRET_KEY     Legacy/special-purpose alias for deploy-only secret
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
#    --skip-smoke     Skip post-deploy authenticated read-only smoke
#    --dry-run        Show commands without executing
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${XIPHOS_CONFIG_DIR:-$HOME/.config/xiphos}"
ENV_FILE="${XIPHOS_DEPLOY_ENV_FILE:-}"
HELIOS_ENV_FILE="$CONFIG_DIR/helios.env"
if [ -z "$ENV_FILE" ]; then
  if [ -f "$CONFIG_DIR/deploy.env" ]; then
    ENV_FILE="$CONFIG_DIR/deploy.env"
  else
    ENV_FILE="$SCRIPT_DIR/deploy.env"
  fi
fi

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

if [ -f "$HELIOS_ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$HELIOS_ENV_FILE"
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
SKIP_SMOKE=false

for arg in "$@"; do
  case "$arg" in
    --skip-ai) SKIP_AI=true ;;
    --skip-verify) SKIP_VERIFY=true ;;
    --verify-only) VERIFY_ONLY=true ;;
    --reset-db) RESET_DB=true ;;
    --sync) SYNC_SANCTIONS=true ;;
    --skip-smoke) SKIP_SMOKE=true ;;
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

sync_secure_runtime_env() {
  local tmp_env=""
  tmp_env="$(mktemp /tmp/xiphos-runtime-XXXXXX.env)"
  : > "$tmp_env"

  local has_payload=false
  for key in NEO4J_URI NEO4J_USER NEO4J_DATABASE NEO4J_PASSWORD XIPHOS_SAM_API_KEY; do
    if [ -n "${!key:-}" ]; then
      has_payload=true
      printf '%s=%s\n' "$key" "${!key}" >> "$tmp_env"
    fi
  done

  if [ "$has_payload" = false ]; then
    rm -f "$tmp_env"
    return
  fi

  local remote_tmp="/tmp/$(basename "$tmp_env")"
  if [ "$DRY_RUN" = true ]; then
    echo ""
    echo ">> [dry-run] sync secure runtime env to $SSH_TARGET:$REMOTE_DIR/.env"
    rm -f "$tmp_env"
    return
  fi

  local scp_args=(-o StrictHostKeyChecking=accept-new)
  if [ -n "$SSH_KEY" ]; then
    scp_args+=(-i "$SSH_KEY")
  fi
  scp "${scp_args[@]}" "$tmp_env" "$SSH_TARGET:$remote_tmp"
  rm -f "$tmp_env"

  local merge_cmd
  merge_cmd=$(cat <<EOF
cd $REMOTE_DIR && python3 - <<'PY'
from pathlib import Path
keys = ["NEO4J_URI", "NEO4J_USER", "NEO4J_DATABASE", "NEO4J_PASSWORD", "XIPHOS_SAM_API_KEY"]
source = Path("$remote_tmp")
target = Path(".env")
updates = {}
if source.exists():
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in keys:
            updates[key] = value
existing = []
if target.exists():
    existing = target.read_text(encoding="utf-8").splitlines()
kept = []
for raw in existing:
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        kept.append(raw)
        continue
    key = line.split("=", 1)[0].strip()
    if key in updates:
        continue
    kept.append(raw)
for key in keys:
    if key in updates:
        kept.append(f"{key}={updates[key]}")
target.write_text("\\n".join(kept).rstrip() + "\\n", encoding="utf-8")
source.unlink(missing_ok=True)
PY
EOF
  )
  run "Syncing secure runtime env..." "$merge_cmd"
}

run() {
  echo ""
  echo ">> $1"
  remote_exec "$2"
}

sync_repo() {
  local rsync_ssh="ssh -o StrictHostKeyChecking=accept-new"
  if [ -n "$SSH_KEY" ]; then
    rsync_ssh="$rsync_ssh -i $SSH_KEY"
  fi

  local -a rsync_excludes=(
    --exclude '.git'
    --exclude '.claude'
    --exclude '.env'
    --exclude '.env.*'
    --exclude 'deploy.env'
    --exclude 'node_modules'
    --exclude 'frontend/node_modules'
    --exclude 'frontend/eslint-rules'
    --exclude 'backups'
    --exclude 'vps_snapshot'
    --exclude 'memory'
    --exclude 'secure-archive'
    --exclude 'CODEX_HANDOFF_20260322.md'
    --exclude 'docs/generated'
    --exclude 'artifacts'
    --exclude 'scratch'
    --exclude 'games'
    --exclude 'demos'
    --exclude 'var'
    --exclude '.pytest_cache'
    --exclude '__pycache__'
    --exclude '.codex-backups'
    --exclude '.DS_Store'
  )

  if [ "$DRY_RUN" = true ]; then
    echo ""
    echo ">> [dry-run] rsync exact tree to $SSH_TARGET:$REMOTE_DIR"
    echo "   Source: $SCRIPT_DIR/"
    return
  fi

  echo ""
  echo ">> Syncing exact repo tree to remote..."
  remote_exec "mkdir -p '$REMOTE_DIR'"
  rsync -az --delete "${rsync_excludes[@]}" -e "$rsync_ssh" "$SCRIPT_DIR"/ "$SSH_TARGET:$REMOTE_DIR/"
}

resolve_secret_key() {
  local secret="${XIPHOS_SECRET_KEY:-${XIPHOS_DEPLOY_SECRET_KEY:-}}"
  if [ -n "$secret" ]; then
    export XIPHOS_SECRET_KEY="$secret"
    return
  fi

  if [ "$DRY_RUN" = true ]; then
    export XIPHOS_SECRET_KEY="<dry-run-secret>"
    return
  fi

  secret="$(ssh "${SSH_ARGS[@]}" "$SSH_TARGET" "docker exec xiphos-xiphos-1 /bin/sh -lc 'printf %s \"\$XIPHOS_SECRET_KEY\"' 2>/dev/null || true")"
  if [ -z "$secret" ]; then
    secret="$(ssh "${SSH_ARGS[@]}" "$SSH_TARGET" "cd '$REMOTE_DIR' && if [ -f deploy.env ]; then set -a; . ./deploy.env; set +a; fi; if [ -f .env ]; then set -a; . ./.env; set +a; fi; printf %s \"\${XIPHOS_SECRET_KEY:-}\"")"
  fi

  if [ -z "$secret" ]; then
    echo "Set XIPHOS_SECRET_KEY (or XIPHOS_DEPLOY_SECRET_KEY) before deploying, or ensure the live container already exposes it."
    exit 1
  fi

  export XIPHOS_SECRET_KEY="$secret"
}

verify_local() {
  if [ "$DRY_RUN" = true ]; then
    echo ""
    echo ">> [dry-run] python3 $SCRIPT_DIR/deploy.py --verify-only"
  else
    python3 "$SCRIPT_DIR/deploy.py" --verify-only
  fi
}

smoke_local() {
  if [ "$SKIP_SMOKE" = true ]; then
    echo ""
    echo ">> Skipping authenticated smoke (--skip-smoke)"
    return
  fi

  if [ -z "$ADMIN_EMAIL" ] || [ -z "$ADMIN_PASSWORD" ]; then
    echo ""
    echo ">> Skipping authenticated smoke (set XIPHOS_DEPLOY_ADMIN_EMAIL/PASSWORD to enable)"
    return
  fi

  if [ "$DRY_RUN" = true ]; then
    echo ""
    echo ">> [dry-run] python3 $SCRIPT_DIR/scripts/run_local_smoke.py --base-url $PUBLIC_BASE_URL --email <redacted> --password <redacted> --skip-stream --read-only"
    return
  fi

  echo ""
  echo ">> Running authenticated read-only smoke..."
  python3 "$SCRIPT_DIR/scripts/run_local_smoke.py" \
    --base-url "$PUBLIC_BASE_URL" \
    --email "$ADMIN_EMAIL" \
    --password "$ADMIN_PASSWORD" \
    --skip-stream \
    --read-only
}

AI_PROVIDER_Q=""
AI_MODEL_Q=""
AI_KEY_Q=""
SECRET_KEY_Q=""
REMOTE_AI_SAVE_CMD=""
REMOTE_AI_VERIFY_CMD=""

refresh_remote_ai_cmds() {
  AI_PROVIDER_Q=$(printf '%q' "$AI_PROVIDER")
  AI_MODEL_Q=$(printf '%q' "$AI_MODEL")
  AI_KEY_Q=$(printf '%q' "$AI_KEY")
  SECRET_KEY_Q=$(printf '%q' "${XIPHOS_SECRET_KEY:-}")

  REMOTE_AI_SAVE_CMD=$(cat <<EOF
cd $REMOTE_DIR && export XIPHOS_SECRET_KEY=$SECRET_KEY_Q && docker compose exec -T -e XIPHOS_SCRIPT_PROVIDER=$AI_PROVIDER_Q -e XIPHOS_SCRIPT_MODEL=$AI_MODEL_Q -e XIPHOS_SCRIPT_KEY=$AI_KEY_Q -w /app/backend xiphos python3 -c "from ai_analysis import init_ai_tables, save_ai_config; import os; init_ai_tables(); save_ai_config('__org_default__', os.environ['XIPHOS_SCRIPT_PROVIDER'], os.environ['XIPHOS_SCRIPT_MODEL'], os.environ['XIPHOS_SCRIPT_KEY']); print('  Org AI default saved')"
EOF
  )

  REMOTE_AI_VERIFY_CMD=$(cat <<'EOF'
cd __REMOTE_DIR__ && export XIPHOS_SECRET_KEY=__SECRET_KEY__ && docker compose exec -T -w /app/backend xiphos python3 -c "from ai_analysis import init_ai_tables, get_available_providers, get_ai_config; init_ai_tables(); providers = get_available_providers(); print('  AI Providers: ' + ', '.join(p['display_name'] for p in providers)); cfg = get_ai_config('__org_default__'); print('  Org AI Config: ' + (f\"{cfg['provider']}/{cfg['model']}\" if cfg else 'not set'))"
EOF
  )
  REMOTE_AI_VERIFY_CMD="${REMOTE_AI_VERIFY_CMD/__REMOTE_DIR__/$REMOTE_DIR}"
  REMOTE_AI_VERIFY_CMD="${REMOTE_AI_VERIFY_CMD/__SECRET_KEY__/$SECRET_KEY_Q}"
}

echo "============================================================"
echo "  XIPHOS DEPLOYMENT"
echo "  Target: $SSH_TARGET"
echo "  Dir:    $REMOTE_DIR"
echo "============================================================"

if [ "$VERIFY_ONLY" = true ]; then
  verify_local
  exit 0
fi

resolve_secret_key
refresh_remote_ai_cmds
sync_repo
sync_secure_runtime_env
run "Stopping existing containers..." "cd $REMOTE_DIR && export XIPHOS_SECRET_KEY='$XIPHOS_SECRET_KEY' && docker compose down"
run "Building Docker image..." "cd $REMOTE_DIR && export XIPHOS_SECRET_KEY='$XIPHOS_SECRET_KEY' && export DOCKER_BUILDKIT=0 && BUILD_LOG=/tmp/xiphos-build.log && rm -f \$BUILD_LOG && if docker build --no-cache -t xiphos-xiphos . >\$BUILD_LOG 2>&1; then echo '  Docker build OK'; else code=\$?; tail -n 200 \$BUILD_LOG; exit \$code; fi"
run "Starting containers..." "cd $REMOTE_DIR && export XIPHOS_SECRET_KEY='$XIPHOS_SECRET_KEY' && docker compose up -d --no-build"
run "Container status..." "cd $REMOTE_DIR && export XIPHOS_SECRET_KEY='$XIPHOS_SECRET_KEY' && docker compose ps"

REMOTE_HEALTH_WAIT_CMD=$(cat <<EOF
python3 - <<'PY'
import json, time, urllib.request
url = "http://localhost:$DOCKER_PORT/api/health"
deadline = time.time() + 120
last_error = ""
while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            payload = json.load(resp)
        print(f"  Version: {payload.get('version', 'unknown')}")
        print(f"  AI:      {payload.get('ai_enabled', True)}")
        print(f"  OSINT:   {payload.get('osint_enabled', True)}")
        print(f"  Vendors: {payload.get('stats', {}).get('vendors', 0)}")
        raise SystemExit(0)
    except Exception as exc:
        last_error = str(exc)
        time.sleep(2)
raise SystemExit(f"remote health did not become ready: {last_error}")
PY
EOF
)

run "Waiting for remote health..." "$REMOTE_HEALTH_WAIT_CMD"
smoke_local

if [ "$SKIP_AI" = false ] && [ -n "$AI_KEY" ]; then
  run "Setting org-wide AI default ($AI_PROVIDER/$AI_MODEL)..." "$REMOTE_AI_SAVE_CMD"
elif [ "$SKIP_AI" = false ]; then
  echo ""
  echo ">> Skipping org AI default configuration (set XIPHOS_AI_KEY to enable)"
fi

if [ "$SYNC_SANCTIONS" = true ]; then
  run "Syncing sanctions lists..." "cd $REMOTE_DIR && export XIPHOS_SECRET_KEY='$XIPHOS_SECRET_KEY' && docker compose exec -T -w /app/backend xiphos python3 sanctions_sync.py --sources ofac uk eu un"
fi

if [ "$RESET_DB" = true ]; then
  run "Resetting database..." "cd $REMOTE_DIR && export XIPHOS_SECRET_KEY='$XIPHOS_SECRET_KEY' && docker compose exec -T -w /app/backend xiphos python3 -c 'import db, os; path = db.get_db_path(); os.path.exists(path) and os.remove(path); db.init_db(); print(\"  Database reset complete\")'"
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
