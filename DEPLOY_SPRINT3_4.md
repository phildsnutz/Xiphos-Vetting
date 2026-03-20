# Deploy Sprint 3+4 to Production

## Pre-Deploy Status
- Package verification: 56/56 PASS
- Bundle: 442,578 bytes (pre-built, no server-side build needed)
- Sprint 3: login tone, visual system, copy/truth pass, vehicle search secondary
- Sprint 4: dead component deletion (10 files removed)
- All code audited: helios-landing, case-detail, login-screen, App.tsx, portfolio-screen

## Option A: Automated Deploy (Recommended)

Use the shared deploy contract instead of hand-exporting credentials:

```bash
cd ~/Desktop/Helios-Package\ Merged
cp deploy.env.example deploy.env
# edit deploy.env with the real SSH target, URL, and optional admin creds

./deploy.sh
```

If you also need to provision HTTPS on that host:

```bash
./deploy.sh --with-ssl
```

If you only have password-based SSH access instead of an SSH alias or key:

```bash
cd ~/Desktop/Helios-Package\ Merged
cp deploy.env.example deploy.env
# edit deploy.env and set XIPHOS_DEPLOY_PASSWORD in your shell

python3 deploy.py
```

## Option B: Manual Deploy via SSH

```bash
# 1. SSH into server
ssh root@YOUR_SERVER_IP

# 2. Upload the package (from local machine in another terminal)
scp -r ~/Desktop/Helios-Package\ Merged/backend root@YOUR_SERVER_IP:/opt/xiphos/
scp -r ~/Desktop/Helios-Package\ Merged/frontend root@YOUR_SERVER_IP:/opt/xiphos/
scp ~/Desktop/Helios-Package\ Merged/Dockerfile root@YOUR_SERVER_IP:/opt/xiphos/
scp ~/Desktop/Helios-Package\ Merged/docker-compose.yml root@YOUR_SERVER_IP:/opt/xiphos/

# 3. On the server: clean dead Sprint 4 files
cd /opt/xiphos
rm -f frontend/src/components/xiphos/dashboard-screen.tsx
rm -f frontend/src/components/xiphos/exec-dashboard.tsx
rm -f frontend/src/components/xiphos/portfolio-view.tsx
rm -f frontend/src/components/xiphos/risk-matrix.tsx
rm -f frontend/src/components/xiphos/stat-card.tsx
rm -f frontend/src/components/xiphos/screen-vendor.tsx
rm -f frontend/src/components/xiphos/batch-import.tsx
rm -f frontend/src/components/xiphos/connector-health.tsx
rm -f frontend/src/components/xiphos/onboarding-wizard.tsx
rm -f frontend/src/components/xiphos/profile-compare.tsx

# 4. Rebuild and restart Docker
docker compose down
docker compose build --no-cache xiphos
docker compose up -d

# 5. Wait for startup, then verify
sleep 15
curl -sf http://localhost:8080/api/health | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'Version: {d[\"version\"]}')
print(f'Connectors: {d[\"osint_connector_count\"]}')
print(f'Vendors: {d[\"stats\"][\"vendors\"]}')
"
```

## Option C: Use The Password-Based Helper

If SSH keys or aliases are not available yet, set `XIPHOS_DEPLOY_PASSWORD` in your shell and use `python3 deploy.py`. Keep the password out of docs and out of `deploy.env`.

## Post-Deploy Verification

After deployment, log in at your configured public URL and verify:

1. Login screen shows "Vendor intelligence and assurance" tagline (not old military copy)
2. PROPRIETARY banner is small footer text only
3. Post-login: 3-tab navigation (Helios / Portfolio / Admin)
4. Helios home: "What do you want to assess?" heading
5. Vehicle search is a text link, not a competing button
6. Recent Work section visible below search
7. Portfolio screen: priority queue at top, tier distribution bar
8. Case detail: Generate Dossier / Open Intel / Re-Enrich as primary actions
9. AI Analysis and Re-Score in "More" overflow menu
10. Evidence tabs: Intel Summary, Raw Findings, Events, Model Factors
