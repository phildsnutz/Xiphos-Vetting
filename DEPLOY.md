# Xiphos v2.6 Deployment Guide

## What's New in v2.6

- **JWT Authentication + RBAC**: Four roles (admin, analyst, auditor, reviewer) with permission-gated endpoints
- **Audit Logging**: Every authenticated action is logged with who/what/when/where/outcome
- **17 OSINT Connectors**: Including FARA foreign agent registration
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
python tests/test_engine_parity.py
```
All 24 tests should pass.

### 3. Run the backend locally
```bash
cd backend
pip install flask flask-cors
python server.py --port 8080
```
Open `http://localhost:8080` to verify the dashboard loads.

### 4. Test the auth flow
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


## Deployment Options

### Option A: Railway (Recommended for Quick Demo)

1. Push your project to GitHub
2. Go to [railway.app](https://railway.app), connect the repo
3. Railway auto-detects the Dockerfile
4. Set environment variables:
   ```
   XIPHOS_DB_PATH=/data/xiphos.db
   XIPHOS_AUTH_ENABLED=true
   XIPHOS_SECRET_KEY=<your-generated-secret>
   ```
5. Add a persistent volume mounted at `/data`
6. Deploy

**Cost**: Free tier or ~$5/month for Hobby plan.


### Option B: DigitalOcean Droplet

1. Create a $6/month droplet (Ubuntu 22.04, 1GB RAM)
2. SSH in, install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. Clone and deploy:
   ```bash
   git clone https://github.com/phildsnutz/Xiphos-Vetting.git
   cd Xiphos-Vetting
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


### Option C: Fly.io

```bash
fly launch
fly volumes create xiphos_data --size 1
fly secrets set XIPHOS_DB_PATH=/data/xiphos.db \
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
| `XIPHOS_DB_PATH`           | No       | `./xiphos.db`                        | Main SQLite database path          |
| `XIPHOS_KG_DB_PATH`        | No       | `./xiphos_kg.db`                     | Knowledge graph database           |
| `XIPHOS_SANCTIONS_DB`      | No       | `./sanctions.db`                     | Local sanctions database           |
| `XIPHOS_AUTH_ENABLED`      | No       | `false`                              | Set `true` to enforce JWT auth     |
| `XIPHOS_SECRET_KEY`        | **Yes*** | dev default                          | JWT signing key (generate fresh!)  |
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
3. **Back up `/data` volume** regularly. SQLite databases are the single source of truth.
4. **Rate limiting**: Add nginx/Caddy rate limiting on `/api/auth/login` to prevent brute force.
5. **CORS lockdown**: Currently `CORS(app)` allows all origins. For production, restrict to your domain.
6. **Consider PostgreSQL** if you expect > 10 concurrent users or > 10,000 vendors. SQLite WAL mode handles moderate load well, but it has a single-writer constraint.
