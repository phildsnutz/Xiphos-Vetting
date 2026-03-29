#!/bin/bash
# ============================================================
#  Xiphos SSL Setup Script
#  Usage: ./deploy-ssl.sh [options]
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
#    XIPHOS_DEPLOY_DOMAIN         Public domain (default: <host>.sslip.io)
#    XIPHOS_DOCKER_PORT           Backend port (default: 8080)
#
#  Options:
#    --dry-run       Show commands without executing
#    --uninstall     Remove Caddy and revert to direct access
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${XIPHOS_CONFIG_DIR:-$HOME/.config/xiphos}"
ENV_FILE="${XIPHOS_DEPLOY_ENV_FILE:-}"
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

SSH_TARGET="${XIPHOS_DEPLOY_SSH_TARGET:-}"
DEPLOY_HOST="${XIPHOS_DEPLOY_HOST:-}"
SSH_USER="${XIPHOS_DEPLOY_SSH_USER:-root}"
SSH_KEY="${XIPHOS_DEPLOY_SSH_KEY:-${XIPHOS_DEPLOY_SSH_KEY_PATH:-}}"
BACKEND_PORT="${XIPHOS_DOCKER_PORT:-8080}"
DOMAIN="${XIPHOS_DEPLOY_DOMAIN:-}"

DRY_RUN=false
UNINSTALL=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --uninstall) UNINSTALL=true ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

if [ -z "$SSH_TARGET" ]; then
  if [ -z "$DEPLOY_HOST" ]; then
    echo "Set XIPHOS_DEPLOY_SSH_TARGET or XIPHOS_DEPLOY_HOST before running deploy-ssl.sh"
    exit 1
  fi
  SSH_TARGET="${SSH_USER}@${DEPLOY_HOST}"
fi

if [ -z "$DOMAIN" ]; then
  if [ -z "$DEPLOY_HOST" ]; then
    echo "Set XIPHOS_DEPLOY_DOMAIN when using an SSH alias without XIPHOS_DEPLOY_HOST"
    exit 1
  fi
  DOMAIN="${DEPLOY_HOST}.sslip.io"
fi

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

write_caddyfile() {
  if [ "$DRY_RUN" = true ]; then
    echo "   [dry-run] write /etc/caddy/Caddyfile for $DOMAIN"
    return
  fi

  ssh "${SSH_ARGS[@]}" "$SSH_TARGET" "cat > /etc/caddy/Caddyfile <<'CADDYEOF'
$DOMAIN {
    reverse_proxy localhost:$BACKEND_PORT

    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        X-XSS-Protection \"1; mode=block\"
        Referrer-Policy strict-origin-when-cross-origin
        Strict-Transport-Security \"max-age=31536000; includeSubDomains\"
        -Server
    }

    encode gzip

    log {
        output file /var/log/caddy/xiphos-access.log {
            roll_size 10mb
            roll_keep 5
        }
    }
}

http://$DOMAIN {
    redir https://$DOMAIN{uri} permanent
}
CADDYEOF"
}

if [ "$UNINSTALL" = true ]; then
  echo "============================================================"
  echo "  XIPHOS SSL REMOVAL"
  echo "============================================================"
  run "Stopping Caddy..." "systemctl stop caddy 2>/dev/null || true; systemctl disable caddy 2>/dev/null || true"
  run "Removing Caddy..." "apt-get remove -y caddy 2>/dev/null || true; rm -f /etc/caddy/Caddyfile"
  run "Opening backend port for direct access..." "ufw allow ${BACKEND_PORT}/tcp 2>/dev/null || true"
  echo ""
  echo "  Reverted. Dashboard at: http://${DEPLOY_HOST:-<host>}:$BACKEND_PORT"
  exit 0
fi

echo "============================================================"
echo "  XIPHOS SSL SETUP"
echo "  Domain: https://$DOMAIN"
echo "  Target: $SSH_TARGET"
echo "============================================================"

run "Installing Caddy web server..." "apt-get update -qq && apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gnupg > /dev/null 2>&1 && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null && apt-get update -qq && apt-get install -y -qq caddy > /dev/null 2>&1 && echo '  Caddy installed successfully'"

echo ""
echo ">> Writing Caddyfile for $DOMAIN..."
write_caddyfile
echo "   Caddyfile written"

run "Setting up logging..." "mkdir -p /var/log/caddy && chown caddy:caddy /var/log/caddy"
run "Configuring firewall (allow 80, 443)..." "ufw allow 80/tcp 2>/dev/null || true; ufw allow 443/tcp 2>/dev/null || true; echo '  Ports 80 and 443 open'"
run "Starting Caddy with TLS provisioning..." "systemctl enable caddy && systemctl restart caddy && sleep 3 && systemctl is-active caddy > /dev/null && echo '  Caddy is running'"

echo ""
echo ">> Waiting for TLS certificate provisioning (up to 30s)..."
if [ "$DRY_RUN" = false ]; then
  for i in $(seq 1 6); do
    if ssh "${SSH_ARGS[@]}" "$SSH_TARGET" "curl -sf -o /dev/null -w '%{http_code}' https://$DOMAIN/api/health 2>/dev/null" | grep -q "200"; then
      echo "   Certificate provisioned successfully"
      break
    fi
    if [ "$i" -eq 6 ]; then
      echo "   TLS may still be provisioning. Checking Caddy status..."
      ssh "${SSH_ARGS[@]}" "$SSH_TARGET" "systemctl status caddy --no-pager -l | tail -5"
      echo ""
      echo "   If Let's Encrypt rate-limits sslip.io, Caddy may fall back"
      echo "   to a self-signed cert until a trusted certificate can be issued."
    fi
    sleep 5
  done
fi

run "Verifying HTTPS endpoint..." "curl -sk https://$DOMAIN/api/health | python3 -c \"import sys, json; d = json.load(sys.stdin); print(f'  Version:  {d.get(\\\"version\\\", \\\"unknown\\\")}'); print(f'  OSINT:    {d.get(\\\"osint_enabled\\\", True)}'); print(f'  Vendors:  {d.get(\\\"stats\\\", {}).get(\\\"vendors\\\", 0)}'); print('  HTTPS:    active')\" 2>/dev/null || echo '  Endpoint check failed (cert may still be provisioning)'"

echo ""
echo "============================================================"
echo "  SSL SETUP COMPLETE"
echo ""
echo "  Dashboard:  https://$DOMAIN"
echo "  Health:     https://$DOMAIN/api/health"
echo ""
echo "  Security headers: HSTS, X-Frame-Options, Referrer-Policy"
echo "  TLS: Auto-renewed by Caddy"
echo "============================================================"
echo ""
echo "Share this URL with testers:"
echo "https://$DOMAIN"
echo ""
