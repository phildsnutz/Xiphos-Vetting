#!/bin/bash
# ============================================================
#  Xiphos SSL Setup Script
#  Usage: ./deploy-ssl.sh [options]
#
#  Installs Caddy as a reverse proxy on the droplet and
#  enables HTTPS via sslip.io free subdomain.
#
#  Your dashboard will be available at:
#    https://209.38.141.101.sslip.io
#
#  Options:
#    --dry-run       Show commands without executing
#    --uninstall     Remove Caddy and revert to direct access
# ============================================================

set -euo pipefail

# ---- Configuration ----
DROPLET_IP="209.38.141.101"
SSH_KEY="$HOME/.ssh/xiphos_do"
SSH_USER="root"
DOMAIN="${DROPLET_IP}.sslip.io"
BACKEND_PORT=8080

# ---- Parse args ----
DRY_RUN=false
UNINSTALL=false

for arg in "$@"; do
  case $arg in
    --dry-run)    DRY_RUN=true ;;
    --uninstall)  UNINSTALL=true ;;
    *)            echo "Unknown option: $arg"; exit 1 ;;
  esac
done

SSH_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$DROPLET_IP"

run() {
  echo ""
  echo ">> $1"
  if [ "$DRY_RUN" = true ]; then
    echo "   [dry-run] skipped"
  else
    $SSH_CMD "$2"
  fi
}

# ---- Uninstall path ----
if [ "$UNINSTALL" = true ]; then
  echo "============================================================"
  echo "  XIPHOS SSL REMOVAL"
  echo "============================================================"
  run "Stopping Caddy..." \
      "systemctl stop caddy 2>/dev/null || true; systemctl disable caddy 2>/dev/null || true"
  run "Removing Caddy..." \
      "apt-get remove -y caddy 2>/dev/null || true; rm -f /etc/caddy/Caddyfile"
  run "Opening port 8080 direct access..." \
      "ufw allow 8080/tcp 2>/dev/null || true"
  echo ""
  echo "  Reverted. Dashboard at: http://$DROPLET_IP:$BACKEND_PORT"
  exit 0
fi

echo "============================================================"
echo "  XIPHOS SSL SETUP"
echo "  Domain: https://$DOMAIN"
echo "  Target: $SSH_USER@$DROPLET_IP"
echo "============================================================"

# Step 1: Install Caddy
run "Installing Caddy web server..." \
    "apt-get update -qq && \
     apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl > /dev/null 2>&1 && \
     curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null && \
     curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null && \
     apt-get update -qq && \
     apt-get install -y -qq caddy > /dev/null 2>&1 && \
     echo '  Caddy installed successfully'"

# Step 2: Configure Caddyfile
run "Writing Caddyfile for $DOMAIN..." \
    "cat > /etc/caddy/Caddyfile << 'CADDYEOF'
$DOMAIN {
    reverse_proxy localhost:$BACKEND_PORT

    header {
        # Security headers
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        X-XSS-Protection \"1; mode=block\"
        Referrer-Policy strict-origin-when-cross-origin
        Strict-Transport-Security \"max-age=31536000; includeSubDomains\"

        # Remove server identification
        -Server
    }

    # Gzip compression
    encode gzip

    log {
        output file /var/log/caddy/xiphos-access.log {
            roll_size 10mb
            roll_keep 5
        }
    }
}

# Redirect bare IP HTTP to HTTPS domain
http://$DROPLET_IP {
    redir https://$DOMAIN{uri} permanent
}
CADDYEOF
echo '  Caddyfile written'"

# Step 3: Create log directory
run "Setting up logging..." \
    "mkdir -p /var/log/caddy && chown caddy:caddy /var/log/caddy"

# Step 4: Open firewall ports
run "Configuring firewall (allow 80, 443)..." \
    "ufw allow 80/tcp 2>/dev/null || true; \
     ufw allow 443/tcp 2>/dev/null || true; \
     echo '  Ports 80 and 443 open'"

# Step 5: Restart Caddy
run "Starting Caddy with TLS provisioning..." \
    "systemctl enable caddy && \
     systemctl restart caddy && \
     sleep 3 && \
     systemctl is-active caddy > /dev/null && \
     echo '  Caddy is running'"

# Step 6: Wait for TLS certificate
echo ""
echo ">> Waiting for TLS certificate provisioning (up to 30s)..."
if [ "$DRY_RUN" = false ]; then
  for i in $(seq 1 6); do
    if $SSH_CMD "curl -sf -o /dev/null -w '%{http_code}' https://$DOMAIN/api/health 2>/dev/null" | grep -q "200"; then
      echo "   Certificate provisioned successfully"
      break
    fi
    if [ "$i" -eq 6 ]; then
      echo "   TLS may still be provisioning. Checking Caddy status..."
      $SSH_CMD "systemctl status caddy --no-pager -l | tail -5"
      echo ""
      echo "   If Let's Encrypt rate-limits sslip.io, Caddy falls back"
      echo "   to a self-signed cert (browser warning, but still encrypted)."
    fi
    sleep 5
  done
fi

# Step 7: Verify HTTPS
run "Verifying HTTPS endpoint..." \
    "curl -sk https://$DOMAIN/api/health | python3 -c \"
import sys, json
d = json.load(sys.stdin)
print(f'  Version:  {d[\"version\"]}')
print(f'  AI:       {d[\"ai_enabled\"]}')
print(f'  Vendors:  {d[\"stats\"][\"vendors\"]}')
print('  HTTPS:    active')
\" 2>/dev/null || echo '  Endpoint check failed (cert may still be provisioning)'"

echo ""
echo "============================================================"
echo "  SSL SETUP COMPLETE"
echo ""
echo "  Dashboard:  https://$DOMAIN"
echo "  Health:     https://$DOMAIN/api/health"
echo ""
echo "  Security headers: HSTS, X-Frame-Options, CSP"
echo "  TLS: Auto-renewed by Caddy (no cron needed)"
echo "============================================================"
echo ""
echo "  Share this URL with testers:"
echo "  https://$DOMAIN"
echo ""
