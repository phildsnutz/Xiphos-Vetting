# Graph 9.5 Status

Generated: 2026-03-30

## Bottom Line

Helios has crossed the line into legitimate `9.5` territory for the **graph benchmark stack**.

Helios has **not** yet earned an honest whole-system `9.5` claim.

That split is real:

- The graph benchmark contract now passes end to end.
- Live novelty discovery still needs harder production validation.
- Whole-system readiness still needs a fresh completed artifact instead of an `UNKNOWN` / stale state.

## What Is Now True

The graph benchmark stack is passing on its own contract:

- `construction_training = PASS`
- `missing_edge_recovery = PASS`
- `temporal_recurrence_change = PASS`
- `subgraph_anomaly = PASS`
- `uncertainty_fusion = PASS`
- `graphrag_explanation = PASS`

Reference artifact:

- `docs/reports/graph_training_benchmark/20260330213029/summary.json`

Key benchmark facts from the current passing tranche:

- masked holdout `hits@10 = 1.0`
- masked holdout `mean rank = 2.0`
- temporal `change_detection_f1 = 1.0`
- anomaly AUPRC is `1.0` across shell layering, transshipment, and cyber fourth party fixtures
- uncertainty calibration is tight, with low ECE and low Brier score
- explanation faithfulness shows full provenance coverage and zero unsupported explanation claims

## What Changed In This Tranche

### 1. Readiness auth failure is no longer the same bug

The readiness runner now refreshes cached auth and retries smoke once when the only failure is an expired token.

Files:

- `scripts/run_counterparty_readiness_report.py`
- `tests/test_counterparty_readiness_report.py`

This matters because the old readiness failure was partly fake. It died too early on stale auth.

### 2. Live novelty surfacing is being hardened separately from holdout ranking

The surfaced analyst queue is now stricter than before, without touching the passing masked-holdout ranking path.

Files:

- `backend/graph_embeddings.py`
- `tests/test_graph_embeddings_local.py`

The first novelty hardening pass was not enough. A live tranche still showed junk like:

- `owned_by -> Department of State`
- `contracts_with -> Department of State`

So the second hardening pass now requires stronger relation-support language for surfaced high-risk families:

- `owned_by`
- `backed_by`
- `routes_payment_through`
- `contracts_with`
- `litigant_in`

That second pass is green locally and still needs a fresh live rerun after the current hosted readiness canary finishes.

## Honest Remaining Blockers

### 1. Live novelty discovery is still the weak flank

The benchmark stack is now strong on fixture and masked-holdout work, but live novelty is still not strong enough to claim whole-system `9.5`.

The current production symptom is simple:

- too many surfaced candidates are still weak or obviously wrong
- analyst confirmation and novel edge yield are still not where they need to be

This is now a **production queue quality** problem, not a benchmark problem.

### 2. Readiness needs a fresh completed artifact

The latest readiness state on the live dashboard has been drifting toward `UNKNOWN` because the report artifact is stale or missing.

The current readiness rerun is important because it is testing whether Helios can finish the real multi-lane gate, not just pass a stale smoke.

Important distinction:

- the readiness auth bug has been reduced
- the long canary work still needs to complete and write a fresh artifact

## Current Position

### Graph stack

Call it `9.5`.

### Whole product

Do **not** call it `9.5` yet.

Call it:

- graph stack: `9.5`
- product: `not there yet`

## Next Moves

1. finish the hosted readiness run and write the fresh `helios_readiness` artifact
2. push the second novelty hardening pass live
3. rerun the live graph-training tranche
4. inspect the surfaced novelty queue again
5. force the next score movement to come from real analyst-confirmable novel edges, not more fixture wins
