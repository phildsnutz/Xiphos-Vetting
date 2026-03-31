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
- support-aware hierarchical prior plus fixture-trained binary logistic model
- features include:
  - hierarchical prior
  - authority bucket
  - temporal state
  - edge family
  - corroboration depth
  - descriptor-only penalty
  - claim/evidence backing
  - legacy-unscoped flag

Why this is better:

- coefficients are estimated, not guessed
- the baseline prior is now learned from family, authority, temporal, corroboration, and evidence support instead of a hand-tuned blend
- family thresholds come from training data
- the model still exposes the learned baseline prior for explainability and fallback

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
- held-out temperature scaling anchors live in:
  - `/Users/tyegonzalez/Desktop/Helios-Package Merged/fixtures/adversarial_gym/decision_tribunal_calibration_cases_v1.json`

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
- confidence, margin, and entropy bands now come from a held-out replay pack
- thin-graph and evidence-gap cases still force escalation even when the classifier is overconfident

Current wisdom upgrade:

- abstain / escalate bands now come from held-out confidence, margin, and entropy rather than a hand-picked score cutoff

Next upgrade:

- train from real analyst decision history in addition to fixtures
- apply temperature scaling or isotonic calibration on a held-out replay set
- apply utility-aware decision thresholds by lane

### 3. Network Propagation

Current heuristic surface:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/network_risk.py`

Previous state:

- propagation strengths were encoded as fixed relation-family weights and a fixed confidence cutoff

Current replacement:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/network_risk.py`
- edge eligibility now depends on whether the relationship clears its empirical family trust floor
- propagation strength now combines:
  - learned edge truth or intelligence score
  - empirical Bayes family reliability
  - harmonic hop decay

Why this is better:

- weak public-noise edges stop carrying the same downstream risk as supported ownership or legal edges
- the graph no longer hides a hard-coded confidence floor inside propagation
- path strength is now anchored to the same evidence-aware edge model used elsewhere

Next upgrade:

- learn relation-family propagation coefficients from reviewed downstream outcomes
- move path aggregation fully into log-probability space for multi-hop risk
- calibrate by workflow lane and mission class

### 4. Graph Analytics

Current heuristic surface:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_analytics.py`

Previous state:

- centrality and exposure metrics treated weak and strong edges too similarly, especially in shortest-path-style metrics

Current replacement:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_analytics.py`
- degree, PageRank, sanctions exposure, and composite importance now use `intelligence_score`
- weighted closeness and weighted betweenness now compute shortest paths using inverse edge trust instead of assuming every edge has equal cost
- centrality now separates:
  - `structural_importance`
  - `decision_importance`

Why this is better:

- broker nodes supported by strong control paths rise above nodes connected mostly by noise
- weak co-mention edges stop warping exposure and path-based influence metrics
- graph structure is now closer to trust-aware network analysis than raw topology counting
- operators no longer have to treat graph shape and decision relevance as the same thing

Next upgrade:

- expose both structural centrality and decision centrality to the frontend
- learn lane-conditioned centrality blends instead of using one composite everywhere

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
