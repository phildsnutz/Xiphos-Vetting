# Graph Smarter Research

Date: 2026-03-30

## Why this matters

Helios already stores the right raw materials for a serious knowledge graph:

- relationship triples
- claim records
- evidence records
- timestamps
- contradiction state
- connector and authority metadata

The main weakness was synthesis. Too much of the product still treated an edge as `confidence + corroboration`, which is not enough for ownership, control, banking routes, contracts, litigation, and supply-chain reasoning.

The right move was not to add another black-box model. It was to make the graph behave more like an auditable claim system.

## Research logic

### 1. Provenance must be first-class, not decorative

W3C PROV-O treats provenance as a real model layer for entities, activities, and agents. That fits Helios directly:

- `kg_claims` already represent assertions
- `kg_evidence` already represent supporting artifacts
- `kg_source_activities` already represent collection or observation events
- `kg_asserting_agents` already represent connector or analyst origin

Implication for Helios:

- a relationship should be scored from its provenance bundle, not from triple existence alone
- authority, freshness, contradiction, and evidence density should change how much we trust the edge

### 2. Ownership intelligence needs statement semantics, not just edges

The Beneficial Ownership Data Standard and GLEIF Level 2 both push toward structured ownership statements:

- who owns whom
- direct versus ultimate parent semantics
- observation or reporting context
- exceptions, unknowns, and partial disclosure

Implication for Helios:

- ownership and control edges should get special treatment
- the system should reward official or first-party ownership evidence more than thin third-party mentions
- future work should distinguish direct parent, ultimate parent, and intermediary chain completeness

### 3. Supply-chain trust depends on source quality and change over time

NIST SP 800-161 is clear on cyber supply chain risk management: supplier trust is not static. Evidence must be evaluated by source quality, monitoring posture, and change over time.

Implication for Helios:

- stale edges should decay in trust
- contradicted edges should be treated as disputed, not just low confidence
- official and first-party evidence should matter more for high-risk families

### 4. Uncertain KGs should preserve graded belief, not force binary truth

UKGE showed that uncertain knowledge graphs benefit from learning and reasoning over confidence-weighted facts instead of flattening everything into true or false.

Implication for Helios:

- the graph should expose a continuous edge-quality score
- downstream ranking and operator review should use that score, not just raw relation confidence

### 5. Temporal KG reasoning should stay explainable

TLogic is useful here because it emphasizes temporal consistency and explainable rule behavior instead of only latent embedding quality.

Implication for Helios:

- temporal state should remain operator-visible
- the graph should say whether an edge is active, watch, stale, historical, or contradicted
- future ranking should use temporal consistency as a first-class feature

### 6. Graph retrieval should prefer trusted subgraphs

G-Retriever matters because it argues for retrieving a compact, relevant, explainable subgraph instead of flooding the language layer with the full graph.

Implication for Helios:

- GraphRAG and dossier generation should prefer strong supported edges
- fragile or contradicted edges should not dominate retrieval unless explicitly asked for uncertainty analysis

## What landed in this tranche

This tranche added a provenance-weighted edge intelligence layer to Helios:

- each relationship now gets a synthesized `intelligence_score`
- each relationship now gets an `intelligence_tier`
- tiering uses:
  - raw confidence
  - authority bucket
  - corroboration depth
  - claim and evidence coverage
  - freshness or temporal state
  - contradiction state
  - legacy unscoped penalties
- control paths now rank by edge intelligence instead of only corroboration and confidence
- graph summaries now expose:
  - average edge intelligence
  - control-path average intelligence
  - strong, fragile, and disputed edge counts
  - edge-intelligence tier counts
  - family-level quality summaries

## Why this is a better fit than another model

This improves Helios in the exact places operators care about:

- better ordering of control paths
- more honest graph quality summaries
- clearer distinction between strong evidence and speculative links
- no extra live-source dependencies
- no expensive retraining loop required

It also preserves Helios’s strongest property: explainability.

## Next smart KG moves

### 1. Ownership path semantics

Add explicit direct-parent and ultimate-parent synthesis from the existing ownership evidence, aligned with GLEIF Level 2 and BODS.

### 2. Temporal event ledger

Represent material relationship changes as graph events, not only edge snapshots. That would let Helios reason over ownership shifts, contract appearance and disappearance, and route changes.

### 3. Confidence-aware analytics

Feed provenance-weighted edge intelligence into graph analytics, network risk propagation, and community scoring so centrality and exposure are less naive.

### 4. Retrieval gating for GraphRAG

Prefer strong and supported edges by default, with an explicit uncertainty mode that includes tentative and disputed edges when analysts want conflict analysis.

## Sources

- W3C PROV-O Recommendation: https://www.w3.org/TR/prov-o/
- Beneficial Ownership Data Standard: https://standard.openownership.org/_/downloads/en/0.0.1/pdf/
- GLEIF Level 2 and relationship data overview: https://www.gleif.org/newsroom/blog/connect-the-corporate-dots-globally-with-the-legal-entity-identifier-a-progress-report-on-collecting-data-on-who-owns-whom
- NIST SP 800-161 announcement and supply chain risk management reference: https://csrc.nist.gov/News/2015/NIST-Announces-the-release-of-NIST-SP-800-161
- UKGE, Embedding Uncertain Knowledge Graphs: https://arxiv.org/abs/1811.10667
- TLogic, Temporal Logical Rules for Explainable Link Forecasting on Temporal Knowledge Graphs: https://arxiv.org/abs/2112.08025
- G-Retriever, Retrieval-Augmented Generation for Textual Graph Understanding and Question Answering: https://arxiv.org/abs/2402.07630
