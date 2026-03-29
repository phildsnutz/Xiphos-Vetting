# Xiphos Operations

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd frontend && npm ci && cd ..
cp backend/.env.example .env
```

Optional ML inference and training dependencies live in `ml/requirements.txt`. Install them only if you want the DistilBERT adverse-media classifier locally.

Production container builds install only `backend/requirements.txt`. Local development and test runs should use `backend/requirements-dev.txt`.

Default mutable state now lives under `./var/`. You can override it with `XIPHOS_DATA_DIR`.

Auth note for local work:

- `XIPHOS_AUTH_ENABLED=false` disables JWT enforcement, but it does not grant anonymous admin access by itself.
- `XIPHOS_DEV_MODE=true` enables local admin passthrough for protected routes and should only be used for local testing.
- Production should run with `XIPHOS_AUTH_ENABLED=true` and `XIPHOS_DEV_MODE` unset.

## Run Locally

```bash
XIPHOS_DATA_DIR=$PWD/var \
XIPHOS_AUTH_ENABLED=false \
XIPHOS_DEV_MODE=true \
XIPHOS_SKIP_SYNC=true \
python3 backend/server.py --port 8080
```

## Smoke Test

With the server running:

```bash
python3 scripts/run_local_smoke.py --base-url http://127.0.0.1:8080
```

Against an authenticated environment:

```bash
HELIOS_BASE_URL=https://your-host \
HELIOS_LOGIN_EMAIL=analyst@example.com \
HELIOS_LOGIN_PASSWORD='replace-me' \
python3 scripts/run_local_smoke.py \
  --base-url https://your-host \
  --email "$HELIOS_LOGIN_EMAIL" \
  --password "$HELIOS_LOGIN_PASSWORD"
```

## Release Checklist

```bash
cd frontend && npm run lint && npm run build && cd ..
python3 -m pytest tests/test_engine_parity.py tests/test_api_surface_local.py -q
python3 tests/test_scoring_validation.py
python3 backend/test_monitor_scheduler.py
python3 scripts/run_local_smoke.py --base-url http://127.0.0.1:8080
docker build -t xiphos:local .
```

## Production Notes

- Beta operators should review `docs/BETA_OPERATOR_RUNBOOK_2026-03-24.md` during the pilot/beta window.
- Set `XIPHOS_SECRET_KEY` before enabling auth. Placeholder or empty values are rejected.
- Set `XIPHOS_AI_CONFIG_KEY` if you want AI provider credentials encrypted with a key that can rotate independently from auth signing.
- Mount `XIPHOS_DATA_DIR` to persistent storage.
- If you want ML adverse-media inference in production, place the trained model under `${XIPHOS_ML_MODEL_DIR:-/data/ml/model}` and install `ml/requirements.txt` in the runtime environment; otherwise the media connectors stay on keyword fallback.
- Set `XIPHOS_CORS_ORIGINS` explicitly in pilot/production environments.
- Keep `XIPHOS_ACCESS_TICKET_TTL_SECONDS` short. `120` seconds is the current default for browser-only access tickets.
- Keep Gunicorn at `1` worker while SQLite is the primary store.
- If outbound HTTPS is intercepted or your CA bundle is stale, USAspending-backed features can fail. The right fix is a current trust store in the container or host. `XIPHOS_USASPENDING_VERIFY_SSL=false` is only a controlled fallback.
- The GitHub Actions remote integration lane runs when these repo secrets are configured: `HELIOS_BASE_URL`, `HELIOS_LOGIN_EMAIL`, `HELIOS_LOGIN_PASSWORD`, and optionally `HELIOS_VERIFY_TLS`.
- Do not keep production snapshots, raw VPS copies, or live `deploy.env` files inside the shareable workspace.
