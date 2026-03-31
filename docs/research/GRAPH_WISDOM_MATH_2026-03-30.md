# Graph Wisdom Math

Helios should not chase a fantasy of "no weights." Modern decision systems still rely on coefficients, thresholds, priors, and utilities. The serious move is to make those quantities learned, calibrated, and auditable.

## Core Takeaways

### 1. Calibration matters

If Helios emits probabilities, those probabilities need to reflect real correctness likelihoods rather than ranking confidence alone.

Primary source:

- [On Calibration of Modern Neural Networks](https://proceedings.mlr.press/v70/guo17a.html)

Why it matters here:

- edge truth probabilities should be calibratable, not just sortable
- tribunal stance probabilities should support confidence-aware escalation
- post-hoc calibration is a real option for Helios once replay sets get larger

### 2. Abstention is not weakness

Selective classification formalizes the right to refuse a low-confidence prediction while controlling risk.

Primary sources:

- [Selective Classification for Deep Neural Networks](https://arxiv.org/abs/1705.08500)
- [Deep Gamblers: Learning to Abstain with Portfolio Theory](https://arxiv.org/abs/1907.00208)

Why it matters here:

- the tribunal should expose `confident`, `escalate`, and `abstain`
- Helios should reject brittle certainty when graph coverage is thin or class margins collapse
- abstention is a product feature for mission-critical use, not a model failure

### 3. Trust should propagate through reputable paths

Trust and reputation research treats path quality as a first-class signal rather than assuming every edge carries equal value.

Primary sources:

- [Combating Web Spam with TrustRank](https://snap.stanford.edu/class/cs224w-readings/gyongyi04trustrank.pdf)
- [The EigenTrust Algorithm for Reputation Management in P2P Networks](https://nlp.stanford.edu/pubs/eigentrust.pdf)

Why it matters here:

- weak co-mentions should not propagate like supported ownership edges
- graph path strength should combine local trust and multi-hop decay
- good seed evidence should dominate noisy graph mass

### 4. Path-based centrality should honor weights

Modern graph analysis does not stop at unweighted BFS when edges differ in quality. Weighted shortest paths and weighted betweenness are standard math, not indulgence.

Primary source:

- [A Faster Algorithm for Betweenness Centrality](https://snap.stanford.edu/class/cs224w-readings/brandes01centrality.pdf)

Why it matters here:

- bridge entities should matter because they connect strong paths, not because they sit between noisy edges
- weighted closeness and weighted betweenness fit Helios better than hop-count-only path metrics

## Helios Math Direction

1. Use learned edge-truth probabilities as the base edge weight.
2. Build the edge prior from hierarchical fixture evidence, not a hand-tuned score blend.
3. Gate propagation on semantic edge families plus empirical trust floors, not hard-coded confidence floors.
4. Use held-out confidence, margin, and entropy bands for tribunal abstention.
5. Use weighted path distance for closeness, betweenness, and critical pathing.
5. Move remaining fixed exposure or utility surfaces toward replay-trained calibration or empirical Bayes priors.

## What This Replaces

- arbitrary confidence cutoffs
- fixed relation propagation tables
- centrality math that treats all edges equally
- tribunal certainty that has no principled reject option

## Remaining Heuristic Surfaces

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_ingest.py`
  - heuristic prior still exists as a transparent fallback and feature input
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/network_risk.py`
  - family priors are empirical Bayes, but not yet learned from downstream outcomes
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_analytics.py`
  - composite importance is still a geometric blend, which is defensible but not yet task-conditioned

## Next Math Upgrades

1. Temperature-scale the tribunal on a held-out replay pack.
2. Learn relation-family propagation coefficients from observed downstream risk.
3. Separate structural importance from decision importance in graph analytics.
4. Train queue ranking from analyst accept or reject history instead of hand-shaped queue rules.
