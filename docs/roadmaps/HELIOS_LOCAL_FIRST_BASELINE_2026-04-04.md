# Helios Local-First Baseline

Date: 2026-04-04

Tag:
- `helios-local-first-baseline-2026-04-04`

Pinned commit:
- `3a611bb` (`Harden current product stress harness`)

This tag marks the first Helios baseline that passed the canonical current-product gate in both environments:
- local dev server
- live hosted beta

Evidence:
- local report: [current_product_stress_harness_20260404225745.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/current_product_stress_harness/current_product_stress_harness_20260404225745.md)
- live report: [current_product_stress_harness_20260404225658.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/current_product_stress_harness/current_product_stress_harness_20260404225658.md)

## What This Baseline Guarantees

- Front Porch intake works through the current-product conversation path.
- clarifying follow-ups are consumed correctly instead of restarting intake
- carried brief handoff into War Room works
- authenticated current-product smoke passes
- graph-backed AXIOM routes are reachable
- community detection is live and returning `algorithm: leiden`
- the hosted beta and local dev build both satisfy the same current-product gate

## What This Baseline Does Not Guarantee

- it is not the final product architecture
- it is not the final naming system
- it is not a performance-complete baseline
- it does not certify every legacy lane or old platform surface
- it does not certify large-scale concurrency or soak behavior beyond the canonical gate

## Known Debt At Baseline Time

- live graph interrogation is still too slow
  - `graph_profile` p50 is roughly `34.6s`
  - `graph_anomalies` p50 is roughly `34.7s`
- local graph timings are materially better than live, so the next serious work should focus on live graph read-path cost before infrastructure arguments start driving product decisions

## Intended Use

Use this tag as the first stable local-first checkpoint for:
- graph and AXIOM reasoning work
- current-product UI iteration
- future stress and sizing comparisons

Do not use this tag to claim Helios is finished. Use it to claim Helios has its first disciplined, reproducible baseline.
