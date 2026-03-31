# Weighting Replacement Plan

Helios should not pretend it can eliminate weighting. The real upgrade is to replace arbitrary constants with learned, calibrated, and lane-aware models that still remain explainable to operators.

## Core Principle

Replace:

- hand-picked additive constants
- fixed propagation tables
- implicit confidence blends

With:

- learned coefficients from fixtures and analyst labels
- proper probabilistic outputs
- explicit fallback behavior
- calibration and abstention bands

## Current Replacement Map

### 1. Graph Edge Truth

Current heuristic surface:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_ingest.py`

Previous state:

- blended `confidence`, `authority`, `corroboration`, `evidence`, and `freshness` with hand-tuned constants

Current replacement:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/learned_weighting.py`
- fixture-trained binary logistic model
- features include:
  - heuristic prior
  - authority bucket
  - temporal state
  - edge family
  - corroboration depth
  - descriptor-only penalty
  - claim/evidence backing
  - legacy-unscoped flag

Why this is better:

- coefficients are estimated, not guessed
- family thresholds come from training data
- the model still exposes the heuristic prior for explainability and fallback

Next upgrade:

- hierarchical logistic model with relation-family random effects
- calibration by family using replayable holdout sets

### 2. Tribunal Stance Selection

Current heuristic surface:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/decision_tribunal.py`

Previous state:

- approve, watch, and deny scores came from manually tuned additive rules

Current replacement:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/learned_weighting.py`
- fixture-trained softmax stance model
- training anchors live in:
  - `/Users/tyegonzalez/Desktop/Helios-Package Merged/fixtures/adversarial_gym/decision_tribunal_training_cases_v1.json`

Features include:

- current signal packet
- lane posture
- graph coverage state
- control-path depth
- cyber/export pressure
- network risk
- heuristic tribunal scores as transparent priors

Why this is better:

- the tribunal now learns class boundaries instead of relying only on additive constants
- explanations stay explicit because the heuristic rationale layer is still preserved in each view
- ranking and recommendation now depend on probabilistic stance scores

Next upgrade:

- train from real analyst decision history in addition to fixtures
- learn an abstain / escalate band
- apply utility-aware decision thresholds by lane

### 3. Network Propagation

Current heuristic surface:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/network_risk.py`

Current issue:

- propagation strengths are still encoded as fixed relation-family weights

Recommended replacement:

- learn relation-family propagation coefficients from known downstream outcomes
- express path aggregation in log-probability space
- calibrate by lane and mission type

Near-term approach:

- bootstrap from current weights as priors
- fit regularized coefficients from replay packs and reviewed cases

### 4. Graph Analytics

Current heuristic surface:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_analytics.py`

Current issue:

- centrality and exposure metrics still treat weak and strong edges too similarly

Recommended replacement:

- use `intelligence_score` as the default edge strength
- allow task-conditioned weights depending on the workflow lane
- separate structural centrality from decision centrality

### 5. Analyst Queue Ranking

Current heuristic surface:

- graph prediction surfacing and review queue ordering

Recommended replacement:

- pairwise or listwise ranking model
- features should include:
  - edge truth probability
  - mission relevance
  - control-path proximity
  - novelty
  - analyst rejection history
  - provenance strength

Recommended math:

- Bradley-Terry or pairwise logistic first
- LambdaMART later if ranking quality becomes the dominant concern

## Mathematical Standards

Helios should optimize and validate with:

- log loss
- Brier score
- calibration error
- family-level recall and precision
- abstention rate
- decision utility by lane

## Guardrails

- never hide the heuristic prior when a learned model is used
- keep feature inputs operator-auditable
- do not use a black-box model for tribunal recommendation without an explicit rationale layer
- prefer replayable fixtures before any live-label dependence

## Near-Term Sequence

1. Learned edge truth, fixture-first
2. Learned tribunal stance model, fixture-first
3. Calibration audit by family and lane
4. Network propagation coefficient learning
5. Analyst queue ranking model
