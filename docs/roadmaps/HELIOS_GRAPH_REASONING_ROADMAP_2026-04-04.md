# Helios Graph Reasoning Roadmap

## Premise

The knowledge graph is not a storage layer or a visualization sink. It is the reasoning spine for Helios.

Helios should use the graph in four escalating layers:

1. Structural inference
2. Link prediction
3. Rule mining
4. Temporal reasoning

The graph must affect:

- Front Porch entity discovery
- Front Porch disambiguation
- AXIOM gap closure
- returned brief authorship
- War Room path work
- dossier claims and caveats

## Current Truth

Today the graph is materially stronger in the back half of the workflow than in the front half.

- `backend/entity_resolver.py` still leads with local vendor memory plus public registries.
- `frontend/src/components/xiphos/front-porch-landing.tsx` uses graph influence in readiness, gap closure, and brief shaping.
- `backend/ai_analysis.py` already incorporates graph context into analysis.
- `backend/knowledge_graph.py` exposes reusable entity and relationship memory, but Front Porch discovery does not yet treat it as first-class enough.

The immediate correction is to make graph memory part of entity discovery and candidate recommendation, not just post-resolution analysis.

## Layer 1: Structural Inference

### Goal

Use graph shape to surface hidden truth before any ML stack is required.

### Build

1. Graph-backed entity discovery and disambiguation
   - query graph memory during `/api/resolve`
   - prefer graph-anchored candidates over thinner public ambiguity when appropriate
   - expose relationship count and graph signal summaries to Front Porch and War Room

2. Betweenness centrality
   - identify chokepoints, brokers, and bridge entities
   - prioritize high-betweenness low-degree entities in supplier passport and War Room

3. Leiden community detection
   - reveal alliances, hidden teaming clusters, and quiet overlap
   - surface community membership in graph room and brief authorship

4. Suspicious absence detection
   - detect expected but missing relationships
   - use this to drive AXIOM gap closure prompts

### Code Anchors

- `backend/entity_resolver.py`
- `backend/knowledge_graph.py`
- `backend/network_risk.py`
- `frontend/src/components/xiphos/front-porch-landing.tsx`
- `frontend/src/components/xiphos/graph-intelligence-dashboard.tsx`

## Layer 2: Link Prediction

### Goal

Predict likely missing edges without confusing them for observed truth.

### Build

1. Baseline embedding model
   - start with TransE
   - persist predictions separately from observed claims

2. Compositional inference
   - add RotatE or ComplEx for indirect ownership, FOCI, and sanctions exposure chains

3. Analyst review queue
   - predicted links must land in a review surface before promotion

### Code Anchors

- `backend/knowledge_graph.py`
- `backend/graph_training.py`
- `backend/server.py`
- `frontend/src/components/xiphos/graph-intelligence-dashboard.tsx`

## Layer 3: Rule Mining

### Goal

Mine explainable rules from Helios’s own graph so dossier intelligence can cite defendable inference.

### Build

1. AMIE+ or AnyBURL batch mining
2. support/confidence thresholds for client-safe use
3. rule citations in briefs and supplier passports

### Output Contract

- rules with support
- rules with confidence
- rules tied to affected entities
- rules marked as inferred, not observed

## Layer 4: Temporal Reasoning

### Goal

Use change over time to predict recompete posture, contractor distress, and acquisition precursors.

### Build

1. timestamp coverage audit
2. temporal edge normalization
3. TTransE or HyTE baseline
4. analyst-visible temporal alerts and confidence caveats

### Constraint

Temporal reasoning should stay discounted until timestamp coverage and freshness quality are high enough to trust.

## Promotion Rules

Graph reasoning must follow the state contract in:

- `docs/roadmaps/HELIOS_GRAPH_STATE_CONTRACT_2026-04-04.md`

Nothing predicted or inferred should silently become observed graph truth.

## Execution Sequence

### Immediate

1. graph-backed Front Porch discovery
2. graph-backed Front Porch disambiguation
3. graph-aware candidate recommendation
4. graph-aware “are these related?” answers

### Next

1. centrality and community analytics surfaced in War Room
2. suspicious-absence engine feeding AXIOM pressure loops
3. predicted-link review queue formalized around the state contract

### Later

1. TransE baseline
2. rule mining
3. temporal modeling

## Success Standard

The graph is working when:

- Front Porch asks better questions because of graph memory
- AXIOM closes gaps by chasing graph absence and contradiction, not just source scarcity
- returned briefs read differently because the relationship fabric changed the analysis
- War Room can distinguish observed truth from inferred structure and predicted links

