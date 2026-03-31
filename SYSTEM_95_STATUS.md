# System 9.5 Status

Date: 2026-03-30

## Current truth

- Whole-system hardening verdict: `PASS`
- Readiness verdict: `GO`
- Prime-time verdict: `READY`
- Query-to-dossier canary: `PASS`
- Graph benchmark: `6/6 PASS`

Primary proof artifacts:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/helios-live-beta-hardening-report-20260330-173831.json`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/readiness/20260331005057/summary.json`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/query-to-dossier/query_to_dossier_gauntlet/20260331004329/summary.json`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/graph_training_benchmark/20260330213029/summary.json`

## What is no longer the blocker

- Graph construction
- Missing-edge recovery
- Temporal recurrence/change
- Subgraph anomaly
- Uncertainty fusion
- Graph-grounded explanation
- Counterparty control-path canary seeding

## Current bottleneck

The next material weakness is runtime, not correctness.

From the passing live hardening packet, the slowest `enrich-and-score` flows were:

1. `cyber_supplier_review` / `Vector Mission Software`: `63.8s`
2. `yorktown_descriptor_only` / `Yorktown Systems Group`: `62.0s`
3. `export_trade_compliance` / `Northern Channel Partners`: `49.1s`
4. `counterparty_defense` / `Harbor Beacon Holdings`: `42.0s`

The worst connector-level contributors on the slow cyber case were:

1. `public_html_ownership`: `53.3s`
2. `gdelt_media`: `32.7s`
3. `public_search_ownership`: `31.3s`

## Latest runtime profiling

Two live runtime tranches have now been measured against the same `cyber_supplier_review` flow for `Vector Mission Software`.

### First runtime tranche

- artifact: `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/runtime_profile/query_to_dossier_gauntlet/20260331010732/summary.json`
- changes:
  - `public_html_ownership` de-duplicates successful `www` and bare-host page variants
  - `public_html_ownership` prioritizes identity pages before news/blog
  - `gdelt_media` removes serialized sleeps and runs tone + GKG fetches in parallel
- measured result:
  - `enrich-and-score`: `63.8s -> 54.0s`
  - `public_html_ownership`: `53.3s -> 43.3s`
  - `gdelt_media`: `32.7s -> 23.4s`
  - `public_search_ownership`: `31.3s -> 38.6s`

### Second runtime tranche

- artifact: `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/runtime_profile/query_to_dossier_gauntlet/20260331011633/summary.json`
- changes:
  - `public_search_ownership` now skips broad web recovery when first-party extraction already resolved strong identity anchors
  - `public_search_ownership` explicitly records `broad_web_recovery_skipped = strong_first_party_identity`
  - search timeout reduced from `4s` to `3s`
- measured result versus the first runtime tranche:
  - `enrich-and-score`: `54.0s -> 54.3s`
  - `public_html_ownership`: `43.3s -> 43.9s`
  - `public_search_ownership`: `38.6s -> 35.5s`
  - `gdelt_media`: `23.4s -> 16.2s`

Brutal read:

- the second tranche improved `public_search_ownership` and `gdelt_media`
- total wall-clock is still effectively flat because `public_html_ownership` is now the dominant drag
- the next serious runtime target is `public_html_ownership`, not more search tuning

## Operating posture

- Keep novelty discovery in maintenance mode only.
- Allowed novelty work:
  - ranking hygiene
  - surfacing hygiene
  - negative-label harvest
- Do not let novelty become the main lane until runtime is materially lower.

## Next runtime targets

1. Cut `public_html_ownership` page count and fetch cost without losing first-party ownership signal
2. Re-profile `Vector Mission Software` live after each `public_html_ownership` change
3. Keep `public_search_ownership` broad-web recovery skip only for strong first-party identity cases
4. Only then decide whether cyber profile connector coverage should be narrowed
