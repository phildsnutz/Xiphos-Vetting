# Claude UI Handoff

## Purpose

This note is for the UI polish tranche only.

Keep changes in the frontend and presentation layer unless there is a real break-fix issue.
Do not change graph-training logic, benchmark math, masked holdout logic, deploy behavior, or runtime contracts unless a UI bug forces it.

## Current Truth

These states are real and should remain visible in the UI:

- `construction_training = PASS`
- `missing_edge_recovery = PASS`
- overall graph benchmark = `FAIL`
- `temporal_recurrence_change = NOT_IMPLEMENTED`
- `subgraph_anomaly = NOT_IMPLEMENTED`
- `uncertainty_fusion = NOT_IMPLEMENTED`
- `graphrag_explanation = NOT_IMPLEMENTED`

Current graph-specific pain points:

- `contracts_with` is the weakest masked-holdout family
- recovery-queue surfacing still lags the ranking layer
- analyst review counts can legitimately be `0`

Do not polish away failure, null, zero, or `NOT_IMPLEMENTED` states.

## Ranked UI Targets

1. Graph training dashboard clarity
   Make `PASS`, `FAIL`, and `NOT_IMPLEMENTED` visually legible without softening them.
   The user should be able to scan benchmark state, Neo4j state, readiness state, and live tranche state quickly.

2. Graph training review panel usability
   Improve queue readability, batch actions, family grouping, and zero-state handling.
   Keep review actions obvious and preserve raw counts.

3. Case detail graph section polish
   Improve layout, spacing, hierarchy, and readability around graph and training surfaces without changing the underlying workflow.

## Files To Prefer

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend/src/components/xiphos/graph-training-review-panel.tsx`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend/src/components/xiphos/case-detail.tsx`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend/src/lib/api.ts`

Likely relevant read-only references:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/link_prediction_api.py`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_embeddings.py`

## Do Not Touch

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/static/index.html` by hand
- masked-holdout fixture logic
- benchmark thresholds
- deploy scripts
- Neo4j sync logic
- graph-training scoring or ranking logic

If frontend changes require a new bundle, rebuild instead of editing built artifacts.

## Runtime Notes

- Auth token is stored in `sessionStorage["helios_token"]`
- The graph-training dashboard payload comes from the authenticated runtime route:
  - `/api/graph/training-dashboard`
- The app should reflect that payload, not invent optimistic derived states

## Latest Backend State

Live KG counts from authenticated `/api/graph/stats`:

- `owned_by = 12`
- `backed_by = 2`
- `routes_payment_through = 4`
- `contracts_with = 231`
- `litigant_in = 147`
- total KG relationships = `2104`

Latest benchmark artifacts:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/live_graph_training_tranche/20260330192155/summary.json`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/graph_training_benchmark/20260330192254/summary.json`

Masked-holdout status from the latest run:

- `queries = 10`
- `hits@10 = 0.9`
- `MRR = 0.5104761904761904`
- `mean rank = 3.7`
- `contracts_with hits@10 = 0.5`
- `contracts_with mean rank = 9.5`

## Handoff Back To Codex

When done, leave a short note in this folder with:

- files changed
- commands run
- build result
- assumptions
- anything intentionally left untouched

Use a simple file such as:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/CLAUDE_UI_NOTES.md`

## Coordination

Codex is staying on graph and backend work.
Assume frontend ownership is yours for this tranche.
