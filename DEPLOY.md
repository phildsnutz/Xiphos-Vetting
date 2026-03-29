# Xiphos Deployment Guide

## What's New in v2.6

- **JWT Authentication + RBAC**: Four roles (admin, analyst, auditor, reviewer) with permission-gated endpoints
- **Audit Logging**: Every authenticated action is logged with who/what/when/where/outcome
- **28 live OSINT connectors**: Sanctions, ownership, contracts, adverse media, litigation, and regulatory sources
- **Tightened ICIJ Matching**: Dual-layer verification eliminates false positives
- **One-time Admin Bootstrap**: `POST /api/auth/setup` creates the first admin user


## Pre-Deployment Checklist

### 1. Generate a JWT secret key
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```
Save this value. You will set it as `XIPHOS_SECRET_KEY` in your environment.

### 2. Run the test suite
```bash
cd /path/to/Xiphos
cd frontend && npm run lint && npm run build && cd ..
python3 -m pytest tests/test_engine_parity.py tests/test_api_surface_local.py -q
python3 tests/test_scoring_validation.py
python3 backend/test_monitor_scheduler.py
```
All checks should pass.

### 3. Run the backend locally
```bash
XIPHOS_DATA_DIR=$PWD/var \
XIPHOS_AUTH_ENABLED=false \
XIPHOS_DEV_MODE=true \
XIPHOS_SKIP_SYNC=true \
python3 backend/server.py --port 8080
```
Open `http://localhost:8080` to verify the dashboard loads.

Important:

- `XIPHOS_AUTH_ENABLED=false` disables JWT enforcement, but it does not by itself grant anonymous admin access.
- `XIPHOS_DEV_MODE=true` enables local admin passthrough for protected routes and should only be used for local testing.
- Production should run with `XIPHOS_AUTH_ENABLED=true` and `XIPHOS_DEV_MODE` unset.

### 4. Run the smoke test
```bash
python3 scripts/run_local_smoke.py --base-url http://127.0.0.1:8080
```
### 5. Test the auth flow
```bash
# Health check (works without auth)
curl http://localhost:8080/api/health

# Bootstrap admin user (only works once, when no users exist)
curl -X POST http://localhost:8080/api/auth/setup \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@yourorg.com", "password": "YourSecurePassword!", "name": "Admin"}'

# Login and get token
curl -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@yourorg.com", "password": "YourSecurePassword!"}'
# Save the "token" value from the response

# Use the token on protected endpoints
curl http://localhost:8080/api/cases \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

## Deployment Credential Checklist

For remote deployment, gather these before you start:

- SSH access to the target host:
  - Preferred: an `~/.ssh/config` alias you can use as `XIPHOS_DEPLOY_SSH_TARGET`
  - Acceptable fallback: host/IP plus `XIPHOS_DEPLOY_SSH_USER`
  - Optional override: `XIPHOS_DEPLOY_SSH_KEY`
- Public application URL:
  - `XIPHOS_PUBLIC_BASE_URL=https://helios.yourdomain.com`
- Optional admin verification credentials:
  - `XIPHOS_DEPLOY_ADMIN_EMAIL`
  - `XIPHOS_DEPLOY_ADMIN_PASSWORD`
- Optional TLS domain for first-time SSL setup:
  - `XIPHOS_DEPLOY_DOMAIN`

Do not commit real deploy credentials. Copy [deploy.env.example](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/deploy.env.example) to `deploy.env`, fill in real values locally, and keep `deploy.env` untracked.

For the minimum pilot security posture and workspace hygiene rules, see [docs/SECURITY_PILOT_CONTROLS_2026-03-23.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/SECURITY_PILOT_CONTROLS_2026-03-23.md).


## One-Command Remote Rollout

Preferred path for key-based SSH or SSH aliases:

```bash
cp deploy.env.example deploy.env
# edit deploy.env with real values

./deploy.sh --with-ssl
```

Notes:

- `deploy.sh` is the main rollout path and now performs an exact-tree sync from your local merged workspace via `rsync`, then rebuilds Docker on the host.
- `deploy.py` is the fallback helper when you only have password-based SSH access; it now uploads a full deploy archive instead of a hand-maintained patch file list.
- `deploy-ssl.sh` can still be run independently if the app is already deployed and you only need to provision HTTPS.
- For rebuilds, make sure `XIPHOS_SECRET_KEY` is available locally in `deploy.env`, or keep the current container running so the deploy helper can reuse the live value automatically.


## Deployment Options

### Option A: Exact-Tree Remote Rollout (Recommended)

1. Ensure the remote host is reachable over SSH and Docker Compose is installed
2. Copy `deploy.env.example` to `deploy.env`
3. Fill in:
   ```bash
   XIPHOS_DEPLOY_SSH_TARGET=prod-xiphos
   XIPHOS_PUBLIC_BASE_URL=https://helios.yourdomain.com
   XIPHOS_DEPLOY_DOMAIN=helios.yourdomain.com
   XIPHOS_SECRET_KEY=<your-runtime-secret>
   XIPHOS_DEPLOY_ADMIN_EMAIL=admin@yourorg.com
   XIPHOS_DEPLOY_ADMIN_PASSWORD=YourSecurePassword!
   ```
4. Run:
   ```bash
   ./deploy.sh --with-ssl
   ```

This path:

- syncs the exact local source tree to the remote host
- rebuilds Docker cleanly
- optionally provisions HTTPS with Caddy
- runs post-deploy verification against the live URL


### Option B: Railway (Recommended for Quick Demo)

1. Push your project to GitHub
2. Go to [railway.app](https://railway.app), connect the repo
3. Railway auto-detects the Dockerfile
4. Set environment variables:
   ```
   XIPHOS_DATA_DIR=/data
   XIPHOS_AUTH_ENABLED=true
   XIPHOS_SECRET_KEY=<your-generated-secret>
   XIPHOS_AI_CONFIG_KEY=<optional-separate-key>
   ```
5. Add a persistent volume mounted at `/data`
6. Deploy

**Cost**: Free tier or ~$5/month for Hobby plan.


### Option C: DigitalOcean Droplet

1. Create a $6/month droplet (Ubuntu 22.04, 1GB RAM)
2. SSH in, install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. Clone and deploy:
   ```bash
   git clone <your-repo-url>
   cd Helios-Package
   export XIPHOS_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
   docker compose up -d
   ```
4. Add HTTPS with Caddy:
   ```bash
   apt install caddy
   # /etc/caddy/Caddyfile:
   # xiphos.yourdomain.com {
   #     reverse_proxy localhost:8080
   # }
   systemctl restart caddy
   ```

**Cost**: $6/month. SSL via Let's Encrypt is free.


### Option D: Fly.io

```bash
fly launch
fly volumes create xiphos_data --size 1
fly secrets set XIPHOS_DATA_DIR=/data \
               XIPHOS_AUTH_ENABLED=true \
               XIPHOS_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
fly deploy
```

**Cost**: Free tier covers this.


## First Boot: Admin Setup

After deploying, the very first thing to do is create the admin user:

```bash
curl -X POST https://your-xiphos-url/api/auth/setup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@yourorg.com",
    "password": "MinimumEightChars!",
    "name": "Your Name"
  }'
```

This endpoint only works once (when zero users exist). It creates the admin and returns a token you can use immediately.

Then create analyst/reviewer accounts:
```bash
TOKEN="<admin-token-from-setup>"

curl -X POST https://your-xiphos-url/api/auth/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "email": "analyst@yourorg.com",
    "password": "AnalystPass123!",
    "name": "Jane Analyst",
    "role": "analyst"
  }'
```


## Role Reference

| Role     | Level | Can Do                                          |
|----------|-------|-------------------------------------------------|
| admin    | 100   | Everything: user management, system config, all ops |
| analyst  | 50    | Score vendors, run enrichments, generate dossiers  |
| auditor  | 30    | Read-only access to everything including audit logs |
| reviewer | 20    | Read-only access to cases, scores, and reports     |


## Environment Variables

| Variable                    | Required | Default                              | Description                        |
|-----------------------------|----------|--------------------------------------|------------------------------------|
| `XIPHOS_DATA_DIR`         | No       | `./var`                              | Root directory for runtime state   |
| `XIPHOS_DB_PATH`          | No       | `<data-dir>/xiphos.db`               | Main SQLite database path override |
| `XIPHOS_KG_DB_PATH`       | No       | `<data-dir>/knowledge_graph.db`      | Knowledge graph DB override        |
| `XIPHOS_SANCTIONS_DB`     | No       | `<data-dir>/sanctions.db`            | Sanctions DB override              |
| `XIPHOS_AUTH_ENABLED`      | No       | `false`                              | Set `true` to enforce JWT auth     |
| `XIPHOS_DEV_MODE`          | No       | `false`                              | Local-only admin passthrough for testing |
| `XIPHOS_SECRET_KEY`        | **Yes*** | none                                 | JWT signing key                    |
| `XIPHOS_AI_CONFIG_KEY`     | No       | falls back to `XIPHOS_SECRET_KEY`    | AI credential encryption key       |
| `XIPHOS_TOKEN_EXPIRY_HOURS`| No       | `8`                                  | Bearer token lifetime              |
| `XIPHOS_SAM_API_KEY`       | No       |                                      | SAM.gov API key                    |
| `XIPHOS_OPENSANCTIONS_KEY` | No       |                                      | OpenSanctions API key              |
| `XIPHOS_COMPANIES_HOUSE_KEY`| No      |                                      | UK Companies House API key         |
| `XIPHOS_OPENCORP_KEY`      | No       |                                      | OpenCorporates API key             |
| `XIPHOS_COURTLISTENER_TOKEN`| No      |                                      | CourtListener API token            |

*Required in production when `XIPHOS_AUTH_ENABLED=true`.


## Production Hardening Notes

For a live environment beyond demo/pilot:

1. **HTTPS is mandatory**. Use Caddy, nginx, or your cloud provider's load balancer with TLS termination.
2. **Rotate `XIPHOS_SECRET_KEY`** periodically. Token revocation requires key rotation since there is no token blacklist.
3. **Set `XIPHOS_AI_CONFIG_KEY`** if you want AI provider credential encryption to survive auth key rotation.
4. **Back up `/data` volume** regularly. SQLite databases are the single source of truth.
5. **Rate limiting**: Add nginx/Caddy rate limiting on `/api/auth/login` to prevent brute force.
6. **CORS lockdown**: Restrict origins to your production domains.
7. **Consider PostgreSQL** if you expect > 10 concurrent users or > 10,000 vendors. SQLite WAL mode handles moderate load well, but it has a single-writer constraint.
8. **Keep the CA bundle current**. USAspending and other outbound HTTPS connectors depend on standard public CAs. Fix trust-store problems in the image first; use `XIPHOS_USASPENDING_VERIFY_SSL=false` only as a temporary fallback.
