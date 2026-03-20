# Claude Handoff: Merged Package Hardening Pass

## Metadata

- Date: 2026-03-19
- From agent: Codex
- To agent: Claude
- Workspace: `/Users/tyegonzalez/Desktop/Helios-Package Merged`
- Scope: Hardening pass on the merged HELIOS/Xiphos package after the merged audit
- Status: Implemented and locally verified

## Objective

The goal of this pass was not to add new product surface. It was to close the gap between what the merged package claimed to do and what it actually did in local runtime, tests, docs, and operational tooling.

The biggest targets were local ML wiring, stale integration/deploy contracts, overclaimed vehicle-search behavior, misleading batch-assessment language, compatibility gaps with older payloads, and a few operator-facing truthfulness problems.

## What Changed

- Fixed the DistilBERT model so local server-style imports auto-detect the repo model instead of silently disabling ML outside Docker.
- Replaced stale hardcoded host/login assumptions in integration, export, and deploy scripts with env-driven configuration and the current `/api/auth/login` contract.
- Refactored contract vehicle search to use vehicle alias expansion, search the right USAspending award classes, filter on actual vehicle references, and surface upstream failures instead of silently returning empty results.
- Made the API, frontend copy, and marketing docs honest that vehicle batch actions create scored draft cases rather than running full per-vendor enrichment.
- Added regression tests for ML wiring, legacy payload aliases, and vehicle-search upstream failure handling.
- Fixed misleading startup logging around auth-disabled mode versus explicit local dev mode.

## Files Changed

- `ml/inference.py`: added robust model-path resolution so the model auto-loads locally and in Docker.
- `backend/osint/google_news.py`: fixed local import path resolution so the media connector can import `ml.inference`.
- `backend/osint/gdelt_media.py`: fixed the same local ML import-path issue.
- `backend/contract_vehicle_search.py`: added alias expansion, match scoring, correct award-type searches, upstream error collection, and env-controlled USAspending TLS verification.
- `backend/osint/usaspending.py`: added env-controlled TLS verification handling for USAspending connector calls.
- `backend/osint/fpds_contracts.py`: added the same env-controlled TLS verification handling for FPDS/USAspending-backed calls.
- `backend/server.py`: added legacy request aliases, honest vehicle-batch semantics, upstream error surfacing for vehicle search, and truthful auth-mode startup logging.
- `tests/test_integration.py`: rewrote around env-driven auth and current API routes.
- `ml/export_training_data.py`: removed hardcoded remote credentials and switched to env-driven auth/runtime config.
- `deploy.py`: removed hardcoded deployment host/login data and switched to env-driven config.
- `deploy.sh`: removed droplet-specific assumptions and switched to env-driven host/domain/remote-dir config.
- `deploy-ssl.sh`: removed droplet-specific assumptions and switched to env-driven host/domain config.
- `XIPHOS_PROJECT_STATE.md`: removed machine-specific deployment references and updated state language.
- `ml/README.md`: updated ML export/deploy instructions and noted local model auto-detection.
- `DEPLOY.md`: updated stale connector-count language.
- `frontend/package.json`: raised the declared Node engine floor to match actual dependency requirements.
- `verify.py`: added local ML auto-detection verification instead of just file existence checks.
- `tests/test_api_surface_local.py`: added legacy alias coverage and vehicle-search failure coverage.
- `tests/test_ml_wiring.py`: new regression tests for local model auto-detection and media-connector ML activation.
- `.github/workflows/ci.yml`: added ML wiring tests to backend CI.
- `frontend/src/lib/api.ts`: updated batch vehicle result typing for the honest response contract.
- `frontend/src/components/xiphos/helios-landing.tsx`: changed UI copy to reflect draft-case creation and award-relationship semantics.
- `docs/marketing/Xiphos_Helios_LinkedIn_Drip_Sequence.md`: corrected overstated contract-vehicle and batch-assessment claims.
- `docs/OPERATIONS.md`: documented the USAspending TLS-inspection caveat and fallback env var.
- `backend/static/index.html`: rebuilt shipped frontend bundle so static assets match UI source changes.

## API And Contract Changes

- `/api/cases` now accepts legacy `vendor_name` as an alias for `name`.
- `/api/vehicle-search` now accepts `vehicle`, `vehicle_name`, or `query`.
- `/api/vehicle-search` now returns `502` with error detail when the upstream USAspending lookup fails and there are no results, instead of returning a fake empty `200`.
- `/api/vehicle-batch-assess` remains a draft-case creator, but its semantics and response metadata were made honest rather than implied full enrichment.
- Integration and export scripts now authenticate against `/api/auth/login`, not the stale `/api/login`.

## Env Vars And Runtime Assumptions

- New operationally relevant env vars:
- `XIPHOS_USASPENDING_VERIFY_SSL`: set to `false` only as a controlled fallback if outbound TLS inspection breaks USAspending verification.
- `XIPHOS_VERIFY_EXTERNAL_SSL`: broader fallback used as a default source for external HTTPS verification behavior.
- Existing env-driven contracts reinforced:
- `HELIOS_BASE_URL`
- `HELIOS_LOGIN_EMAIL`
- `HELIOS_LOGIN_PASSWORD`
- `HELIOS_VERIFY_SSL`
- `XIPHOS_DEPLOY_HOST`
- `XIPHOS_DEPLOY_SSH_USER`
- `XIPHOS_DEPLOY_SSH_PASSWORD`
- `XIPHOS_DEPLOY_SSH_KEY_PATH`
- `XIPHOS_DEPLOY_REMOTE_DIR`
- `XIPHOS_DEPLOY_DOMAIN`
- `XIPHOS_DEPLOY_VERIFY_SSL`
- Runtime nuance:
- Auth-disabled mode is not the same thing as anonymous admin passthrough. Protected routes still require auth unless `XIPHOS_DEV_MODE=true`.

## Data, ML, And Migrations

- No database migration was introduced in this pass.
- No scoring-model logic change was made in the merged hardening pass itself.
- The main ML fix was packaging/runtime resolution: local repo model discovery and connector import wiring.
- Existing runtime `.db` artifacts were intentionally not deleted because they may contain real data and removal would be destructive.

## Verification

- `npm run lint` in `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend`: passed.
- `npm run build` in `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend`: passed.
- `python3 -m pytest tests/test_engine_parity.py tests/test_api_surface_local.py tests/test_ml_wiring.py -q`: passed, `41 passed`.
- `python3 tests/test_scoring_validation.py`: passed, `25/25`, `100%`.
- `XIPHOS_DATA_DIR=/tmp/helios-merged-monitor python3 backend/test_monitor_scheduler.py`: passed.
- `python3 scripts/run_local_smoke.py --base-url http://127.0.0.1:8099`: passed end to end.
- Live spot-check on `OASIS` vehicle search with `XIPHOS_USASPENDING_VERIFY_SSL=false` in this shell environment: returned `30` prime matches, `17` subcontractor matches, `47` unique vendors.

## Not Verified

- I did not run a secrets-backed remote integration flow against a real authenticated hosted environment after this pass.
- I did not rotate or scrub any exposed credentials from history.
- I did not delete or rewrite existing runtime SQLite files.
- I did not validate every marketing/manual doc beyond the obvious overstated contract-vehicle and batch-assessment claims I found during this pass.

## Known Risks And Sharp Edges

- Credential exposure remains the biggest unresolved issue. Hardcoded usage patterns were removed from the touched scripts, but actual key rotation and history cleanup still need to happen separately.
- The USAspending/FPDS integrations are now honest about upstream failure, but this environment still requires TLS-inspection handling for those calls. The right fix is to trust the inspecting CA at the host level, not rely on `XIPHOS_USASPENDING_VERIFY_SSL=false` long-term.
- The product is stronger, but it is still fundamentally a SQLite-centered system. That is fine for pilots and controlled deployments, not my definition of world-class multi-user scale.
- Some runtime/docs drift may still exist outside the touched files, especially in sales or marketing collateral that was not part of the functional audit path.

## Questions For The Next Agent

- Check whether any remaining public-facing docs still describe vehicle batch assessment as a full 27-connector bulk enrichment flow.
- Check whether the hosted environment needs a proper CA trust-store fix instead of the USAspending TLS fallback flag.
- Check whether the deployment docs should explicitly describe the auth-disabled versus dev-mode distinction for local testing.
- Check whether remote integration automation should become a secrets-backed CI lane rather than staying manual.

## Recommended Next Actions

1. Rotate exposed credentials and scrub historical secret exposure.
2. Add one authenticated remote integration lane in CI backed by managed secrets.
3. Decide whether the next maturity step is Postgres and multi-worker serving or whether you are intentionally staying in pilot-scale territory for now.
