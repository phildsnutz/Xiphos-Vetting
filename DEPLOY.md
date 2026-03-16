# Xiphos v2.0 Deployment Guide

## Pre-Deployment Testing (Local)

### 1. Run the test suite
```bash
cd /path/to/Xiphos
python tests/test_engine_parity.py
```
All 24 tests should pass. This verifies scoring parity, OFAC matching, database operations, and tier boundaries.

### 2. Run the backend locally
```bash
cd backend
pip install flask flask-cors
python server.py --port 8080
```
Then open `http://localhost:8080` -- the server will serve the bundled dashboard and API from a single port.

### 3. Test the API manually
```bash
# Health check
curl http://localhost:8080/api/health

# List vendors
curl http://localhost:8080/api/cases

# Screen a name
curl -X POST http://localhost:8080/api/screen \
  -H "Content-Type: application/json" \
  -d '{"name": "Rosoboronexport"}'

# Re-score
curl -X POST http://localhost:8080/api/cases/c-4de48c49/score \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 4. Verify persistence
Stop the server (Ctrl+C), restart it, and confirm vendors and alerts are still there via `/api/health`.


## Deployment Options (2-3 Person Demo)

### Option A: Railway (Recommended for Quick Demo)

Railway is the fastest path. Free tier supports small teams. No Docker knowledge needed.

1. Push your project to a GitHub repo
2. Go to [railway.app](https://railway.app), connect the repo
3. Railway auto-detects the Dockerfile
4. Set environment variable: `XIPHOS_DB_PATH=/data/xiphos.db`
5. Add a persistent volume mounted at `/data`
6. Deploy -- you get a public URL like `xiphos-production.up.railway.app`
7. Share the URL with your 2-3 testers

**Cost**: Free tier or ~$5/month for the Hobby plan.


### Option B: DigitalOcean Droplet (Best for VPS Control)

Good if you want full control and SSH access.

1. Create a $6/month droplet (Ubuntu 22.04, 1GB RAM is plenty)
2. SSH in and install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. Clone your repo:
   ```bash
   git clone https://github.com/youruser/xiphos.git
   cd xiphos
   ```
4. Build and run:
   ```bash
   docker compose up -d
   ```
5. (Optional) Point a domain at the droplet IP and add Caddy for HTTPS:
   ```bash
   apt install caddy
   # Caddyfile:
   # xiphos.yourdomain.com {
   #     reverse_proxy localhost:8080
   # }
   ```

**Cost**: $6/month. Domain + SSL via Caddy is free (Let's Encrypt).


### Option C: Fly.io (Good Middle Ground)

Fly.io gives you Docker deployment with a generous free tier and persistent volumes.

1. Install flyctl: `curl -L https://fly.io/install.sh | sh`
2. From the Xiphos directory:
   ```bash
   fly launch          # creates fly.toml, picks a region
   fly volumes create xiphos_data --size 1
   fly deploy
   ```
3. Set the DB path:
   ```bash
   fly secrets set XIPHOS_DB_PATH=/data/xiphos.db
   ```

**Cost**: Free tier covers this easily.


## My Recommendation

For your situation -- 2-3 people demoing, testing, and offering feedback -- **Railway** is the move. Here's why:

- Zero ops overhead. You push to GitHub, it deploys automatically
- Built-in persistent storage for the SQLite database
- Preview deployments on every PR, so testers can compare versions
- Free or $5/month, scales up trivially if you need it later
- Public URL you can share immediately with your test group

The DigitalOcean path is better if you want to eventually run multiple services (say, adding a real OFAC feed updater or a background screening scheduler), since you own the box and can install whatever you need.

Fly.io splits the difference -- Docker-native, persistent volumes, but more ops than Railway.


## Demo Feedback Collection

For your 2-3 testers, I'd suggest:

1. **Shared feedback doc**: Create a simple Google Sheet with columns: Feature, Issue/Suggestion, Severity, Tester
2. **Test scenarios to assign**: Give each tester a different angle:
   - Tester A: Try to "break" the screening form. Weird names, edge cases, empty fields
   - Tester B: Walk through 3-4 vendor dossiers end-to-end. Do the scores make sense?
   - Tester C: Focus on UX. What's confusing? What's missing? Where did you get stuck?
3. **Time-box it**: 45-60 minutes of focused testing, then a 30-minute debrief call


## Running Tests Before Each Deploy

```bash
# From project root
python tests/test_engine_parity.py && echo "READY TO DEPLOY" || echo "FIX TESTS FIRST"
```

If any test fails, do NOT deploy. The test suite covers scoring parity, OFAC matching, database integrity, and tier boundaries.
