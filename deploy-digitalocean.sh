#!/bin/bash
# =============================================================================
# Xiphos v2.7 -- DigitalOcean Deployment Script
# =============================================================================
# Target: ubuntu-s-2vcpu-4gb-sfo3-01 (Ubuntu 24.04 LTS)
#
# Usage:
#   1. SSH into your droplet
#   2. Clone the repo (or scp this script + the bundle)
#   3. Run: chmod +x deploy-digitalocean.sh && ./deploy-digitalocean.sh
#
# What this script does:
#   - Installs Docker + Docker Compose (if not present)
#   - Installs Caddy for automatic HTTPS
#   - Generates a secure JWT secret key
#   - Builds and starts Xiphos via Docker Compose
#   - Sets up Caddy reverse proxy with Let's Encrypt TLS
#   - Creates a systemd timer for daily sanctions list sync
# =============================================================================

set -e

XIPHOS_DIR="/opt/xiphos"
DOMAIN="${XIPHOS_DOMAIN:-}"  # Set before running, or pass as env var

echo "=== Xiphos v2.7 DigitalOcean Deployment ==="
echo ""

# ---- 1. System updates ----
echo "[1/7] Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq

# ---- 2. Install Docker ----
if ! command -v docker &> /dev/null; then
    echo "[2/7] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
else
    echo "[2/7] Docker already installed: $(docker --version)"
fi

# ---- 3. Install Docker Compose plugin ----
if ! docker compose version &> /dev/null; then
    echo "[3/7] Installing Docker Compose..."
    apt-get install -y -qq docker-compose-plugin
else
    echo "[3/7] Docker Compose already installed"
fi

# ---- 4. Install Caddy ----
if ! command -v caddy &> /dev/null; then
    echo "[4/7] Installing Caddy (HTTPS reverse proxy)..."
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq caddy
else
    echo "[4/7] Caddy already installed"
fi

# ---- 5. Clone/setup Xiphos ----
echo "[5/7] Setting up Xiphos..."
mkdir -p "$XIPHOS_DIR"

if [ -d "$XIPHOS_DIR/.git" ]; then
    echo "  Updating existing installation..."
    cd "$XIPHOS_DIR"
    git pull origin main
else
    echo "  Fresh install..."
    if [ -d ".git" ]; then
        # Running from inside the repo
        cp -r . "$XIPHOS_DIR/"
    else
        echo "  ERROR: Run this script from inside the Xiphos git repo,"
        echo "         or clone first: git clone https://github.com/phildsnutz/Xiphos-Vetting.git"
        exit 1
    fi
fi

cd "$XIPHOS_DIR"

# ---- 6. Generate secrets and start ----
echo "[6/7] Generating secrets and starting Xiphos..."

# Generate JWT secret if not set
if [ -z "$XIPHOS_SECRET_KEY" ]; then
    XIPHOS_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "  Generated XIPHOS_SECRET_KEY (save this somewhere safe):"
    echo "  $XIPHOS_SECRET_KEY"
fi

# Write .env for docker compose
cat > "$XIPHOS_DIR/.env" << ENVEOF
XIPHOS_SECRET_KEY=$XIPHOS_SECRET_KEY
XIPHOS_AUTH_ENABLED=true
XIPHOS_TOKEN_EXPIRY_HOURS=8
ENVEOF

# Build and start
docker compose build
docker compose up -d

echo "  Waiting for Xiphos to start..."
sleep 5

# Health check
if curl -sf http://localhost:8080/api/health > /dev/null; then
    echo "  Xiphos is running on port 8080"
else
    echo "  WARNING: Health check failed. Check: docker compose logs"
fi

# ---- 7. Configure Caddy (HTTPS) ----
echo "[7/7] Configuring HTTPS..."

if [ -n "$DOMAIN" ]; then
    cat > /etc/caddy/Caddyfile << CADDYEOF
$DOMAIN {
    reverse_proxy localhost:8080
    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy strict-origin-when-cross-origin
    }
}
CADDYEOF

    systemctl restart caddy
    echo "  Caddy configured for $DOMAIN with automatic HTTPS"
    echo "  Access Xiphos at: https://$DOMAIN"
else
    echo "  No domain configured. Set XIPHOS_DOMAIN and re-run, or configure manually."
    echo "  For now, access via: http://$(curl -s ifconfig.me):8080"
    echo ""
    echo "  To add HTTPS later:"
    echo "    1. Point your domain DNS to this server's IP"
    echo "    2. export XIPHOS_DOMAIN=xiphos.yourdomain.com"
    echo "    3. Re-run this script (or edit /etc/caddy/Caddyfile)"
fi

# ---- Setup daily sanctions sync ----
cat > /etc/systemd/system/xiphos-sync.service << SVCEOF
[Unit]
Description=Xiphos Sanctions Sync
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=$XIPHOS_DIR
ExecStart=/usr/bin/docker compose exec -T xiphos python3 -c "import sanctions_sync; sanctions_sync.init_sanctions_db(); sanctions_sync.sync_all()"
SVCEOF

cat > /etc/systemd/system/xiphos-sync.timer << TMREOF
[Unit]
Description=Daily Xiphos Sanctions Sync

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
TMREOF

systemctl daemon-reload
systemctl enable --now xiphos-sync.timer

echo ""
echo "=============================================="
echo "  XIPHOS v2.7 DEPLOYMENT COMPLETE"
echo "=============================================="
echo ""
echo "  Next steps:"
echo "  1. Create your admin account:"
echo "     curl -X POST http://localhost:8080/api/auth/setup \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"email\": \"admin@yourorg.com\", \"password\": \"YourSecurePassword!\", \"name\": \"Admin\"}'"
echo ""
echo "  2. Open the dashboard in your browser"
echo ""
echo "  Sanctions sync: daily at 4:00 AM UTC"
echo "  Logs: docker compose logs -f"
echo "  Status: docker compose ps"
echo "=============================================="
