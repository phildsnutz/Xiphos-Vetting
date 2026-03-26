# Helios Tonight 1000-Entity Runbook

Date: 2026-03-26

## Honest Call

This run is worth doing tonight.

The mix is right for Helios as it exists now:

- `750` net-new US defense exhibitors and suppliers to grow the company graph
- `100` replay high-risk foreign entities to stress sanctions and network-risk paths
- `150` replay allied or partner foreign entities to deepen cross-border context

This is better than a 1000-row random company blast.
It leans into Helios' strongest live collectors and gives you both graph growth and demo-grade blocked/vendor-risk cases.

## Files

- Cohort CSV: `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/HELIOS_TONIGHT_1000_ENTITY_COHORT_2026-03-26.csv`
- Cohort JSON: `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/HELIOS_TONIGHT_1000_ENTITY_COHORT_2026-03-26.json`
- Cohort summary: `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/HELIOS_TONIGHT_1000_ENTITY_COHORT_2026-03-26.md`
- Runner: `/Users/tyegonzalez/Desktop/Helios-Package Merged/scripts/run_training_cohort.py`
- Builder: `/Users/tyegonzalez/Desktop/Helios-Package Merged/scripts/build_tonight_training_cohort.py`
- Public source fixtures:
  - `/Users/tyegonzalez/Desktop/Helios-Package Merged/fixtures/training_run/ausa_annual_2025_exhibitors.json`
  - `/Users/tyegonzalez/Desktop/Helios-Package Merged/fixtures/training_run/afa_air_space_cyber_2025_exhibitors.json`
  - `/Users/tyegonzalez/Desktop/Helios-Package Merged/fixtures/training_run/modern_day_marine_2025_exhibitors.json`

## One-Command Full Run

```bash
cd "/Users/tyegonzalez/Desktop/Helios-Package Merged" && HELIOS_BASE_URL="http://24.199.122.225:8080" HELIOS_EMAIL="tye.gonzalez@gmail.com" HELIOS_PASSWORD="helios2026" python3 scripts/run_training_cohort.py --cohort-file docs/reports/HELIOS_TONIGHT_1000_ENTITY_COHORT_2026-03-26.csv --delay 1.25 --output-file docs/reports/helios-training-cohort-run-20260326-full.json
```

## Safer Staged Version

If you want a lower-risk operator sequence, use this order:

1. First 100 new anchors

```bash
cd "/Users/tyegonzalez/Desktop/Helios-Package Merged" && HELIOS_BASE_URL="http://24.199.122.225:8080" HELIOS_EMAIL="tye.gonzalez@gmail.com" HELIOS_PASSWORD="helios2026" python3 scripts/run_training_cohort.py --cohort-file docs/reports/HELIOS_TONIGHT_1000_ENTITY_COHORT_2026-03-26.csv --only-bucket create_us_anchor --limit 100 --delay 1.25 --output-file docs/reports/helios-training-cohort-run-20260326-wave1.json
```

2. First 50 high-risk foreign replays

```bash
cd "/Users/tyegonzalez/Desktop/Helios-Package Merged" && HELIOS_BASE_URL="http://24.199.122.225:8080" HELIOS_EMAIL="tye.gonzalez@gmail.com" HELIOS_PASSWORD="helios2026" python3 scripts/run_training_cohort.py --cohort-file docs/reports/HELIOS_TONIGHT_1000_ENTITY_COHORT_2026-03-26.csv --only-bucket replay_high_risk_foreign --limit 50 --delay 1.25 --output-file docs/reports/helios-training-cohort-run-20260326-wave2.json
```

3. Then run the full remaining cohort if error rate is still near zero

## Validation Already Completed

- Builder generated `1000` rows cleanly.
- Bucket mix:
  - `350` `create_us_anchor`
  - `250` `create_us_supplier`
  - `150` `create_us_reserve`
  - `100` `replay_high_risk_foreign`
  - `150` `replay_allied_partner_foreign`
- Hosted sample create path passed:
  - `Boeing` -> `c-dc842153`
  - `Amazon Web Services` -> `c-bc9403d4`
- Hosted sample replay path passed:
  - `NORINCO` -> `c-0e3b5d2c`
  - `AVIC` -> `c-bcf4c643`

## Expected Yield

Best-case overnight outcome:

- `750` new vendor cases added
- existing high-risk and foreign cases re-enriched with current connectors
- more cross-border graph paths from the replay buckets
- better blocked-case and export-risk demo inventory by morning

Realistic caution:

- the foreign replay buckets are useful for context and scoring, but the biggest graph edge growth still comes from the US buckets
- if overnight error rate climbs above `5%`, stop and inspect before continuing

## Stop Criteria

Stop the run if any of these happen:

- `error_count` exceeds `50`
- consecutive HTTP `500` or timeout failures exceed `10`
- hosted `/api/health` stops returning `200`
- enrich-stream starts producing repeated terminal `error` events

## Morning Checks

1. Check the output JSON report written by the runner.
2. Pull `/api/portfolio/snapshot` and confirm vendor count growth.
3. Sample `10` new anchor cases and `10` replay cases for graph density and dossier quality.
4. If the overnight run is clean, rebuild any public portal or graph showcase assets from the updated data.
