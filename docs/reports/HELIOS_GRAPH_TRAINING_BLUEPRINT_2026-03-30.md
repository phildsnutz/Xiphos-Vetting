# Helios Graph Training Blueprint

Date: 2026-03-30

## Objective

Raise Helios from a graph-aware system to a graph-led system that can credibly clear the `9.5+` bar.

The target is not a single model. It is a staged training stack:

1. Analyst-labeled graph construction training
2. Link prediction for missing edge families
3. Temporal recurrence / change training
4. Subgraph anomaly training
5. Uncertainty calibration and soft-logic fusion
6. GraphRAG only for explanation

## Hard Read

Helios still loses points when the graph is thin, shallow, stale, or missing the edge families that matter most:

- ownership and control
- intermediaries, banks, routes, and services
- cyber fourth-party dependencies
- contradiction, corroboration, and freshness

That means the highest-ROI training is not end-to-end decision prediction. It is graph construction quality.

If the graph is wrong, stronger reasoning just makes wrong answers sound more confident.

## Current Starting Point

Helios already has useful training footholds:

- [graph_embeddings.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/graph_embeddings.py) provides a TransE baseline.
- [link_prediction_api.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/link_prediction_api.py) exposes training, predicted links, similar entities, and analyst review.
- [graph_ingest.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/graph_ingest.py) already maps modeled and live evidence into typed graph families.
- [neo4j_integration.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/neo4j_integration.py) and [neo4j_sync_scheduler.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/neo4j_sync_scheduler.py) now support reliable hosted graph sync.
- [pillar_briefing_query_to_dossier_pack.json](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/fixtures/customer_demo/pillar_briefing_query_to_dossier_pack.json) and the adversarial gym packs already provide hostile evaluation surfaces.

The right move is to evolve this stack, not throw it away.

## Training Program

### 1. Analyst-Labeled Graph Construction Training

Train the graph builder to do four things well:

- extract the right edge
- assign the right edge family
- resolve the right endpoint
- decline to create an edge when evidence is descriptor-only, stale, or contradictory

Training units:

- evidence span -> claim
- claim -> edge family
- claim -> canonical source and target
- claim -> contradiction or corroboration state
- claim -> confidence and freshness

Positive labels should come from:

- official records
- first-party records
- analyst-confirmed predicted links
- curated adversarial fixtures

Hard negatives should come from:

- descriptor-only ownership language
- generic market text
- near-match aliases
- stale or superseded filings
- route snippets that do not establish actual transshipment

Helios-specific label families:

- `ownership_control`
- `finance_intermediary`
- `trade_and_logistics`
- `intermediaries_and_services`
- `cyber_supply_chain`
- `component_dependency`
- `sanctions_and_legal`
- `contracts_and_programs`

Why first:

- this directly fixes thin graphs
- this directly reduces false edges
- this improves every downstream model

### 2. Link Prediction For Missing Edge Families

Use the graph to recover plausible but currently missing links. Start with typed, family-specific link prediction rather than generic completion.

Best first operational path:

- keep TransE as the fast baseline
- add Neo4j GDS link prediction baselines
- compare those against family-specific offline models

Train separate heads or experiments for:

- `OWNED_BY`
- `SUBSIDIARY_OF`
- `BACKED_BY`
- `ROUTES_PAYMENT_THROUGH`
- `DISTRIBUTED_BY`
- `SHIPS_VIA`
- `DEPENDS_ON_SERVICE`
- `DEPENDS_ON_NETWORK`
- `SUPPLIES_COMPONENT`
- `INTEGRATED_INTO`

Guardrail:

Predicted links are candidates with uncertainty. They are not facts until supported by evidence or analyst confirmation.

### 3. Temporal Recurrence / Change Training

Helios is a temporal graph problem, not a static one.

Train for:

- edge persistence
- edge disappearance
- contradiction emergence
- monitoring-trigger prediction
- route drift
- ownership-change recurrence
- recurring cyber dependency changes

Primary input sources:

- `kg_relationships.created_at`
- monitoring runs
- case events
- enrichment report timestamps
- dossier and passport snapshots

Baseline first:

- recurrence and change heuristics
- temporal edge frequency baselines

Then evaluate:

- TGN-style temporal memory
- temporal knowledge-graph forecasting baselines
- state-space temporal graph models if the simpler baselines plateau

### 4. Subgraph Anomaly Training

Train the graph to detect structures, not just entities.

Core anomaly classes:

- shell layering
- nominee-style ownership
- suspicious payment routing
- export diversion and transshipment
- cyber fourth-party concentration
- lower-tier hidden dependency
- contradicted high-confidence subgraphs

Use both:

- synthetic hostile scenarios
- live audited cases with confirmed patterns

This is the training layer that should make Helios uncomfortable in the right cases.

### 5. Uncertainty Calibration And Soft-Logic Fusion

Helios needs calibrated uncertainty, not just model scores.

Train and calibrate:

- edge confidence
- family-specific prediction confidence
- anomaly confidence
- final recommended-view confidence

Fuse model outputs with soft rules:

- official evidence outranks public HTML
- descriptor-only ownership cannot create named beneficial owners
- stale contradictory evidence lowers confidence even when structure looks rich
- thin graph is not neutral

The recommended mechanism is a soft-logic fusion layer, not a hard-coded if/else pile and not a black-box end-to-end model.

### 6. GraphRAG Only For Explanation

GraphRAG belongs on top of the graph, not underneath it.

Use it to:

- summarize strongest paths
- explain missing edge families
- compress large neighborhoods
- render analyst-facing provenance narratives

Do not use it to invent graph facts.

## Model Ladder

### Baselines To Keep

- TransE in [graph_embeddings.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/graph_embeddings.py)
- family-specific heuristics
- Neo4j GDS link prediction pipelines

### Serious Next Models

- heterogeneous graph models for typed nodes and edges
- temporal models for time-varying paths
- subgraph anomaly detectors
- hypergraph models for shipment and transaction events

### Models To Avoid As First Moves

- giant graph foundation models trained from scratch on Helios’s current graph size
- unconstrained KG completion that silently invents facts
- end-to-end decision classifiers that bypass provenance

## Data Program

### Gold Set Construction

Build a gold set with the following label objects:

- `entity_match`
- `entity_non_match`
- `edge_true`
- `edge_false`
- `edge_family`
- `source_authority`
- `freshness_class`
- `contradiction_state`
- `descriptor_only`
- `named_owner_resolved`

### Training Data Sources

- `kg_entities`
- `kg_relationships`
- `enrichment_reports`
- `case_events`
- supplier passport snapshots
- dossier fragments
- `kg_predicted_links` review outcomes
- adversarial fixture packs

### Mandatory Hard Negatives

- Yorktown-style descriptor-only owner class
- alias confusion between related companies
- payment-bank mention without real routing evidence
- logistics article mention without real shipment route evidence
- cyber vendor mention without actual dependency evidence

## Implementation Order

### Tranche A

- build construction gold set
- instrument analyst review capture on predicted links
- baseline family-specific link prediction
- expose candidate-edge confidence and support in analyst surfaces

### Tranche B

- train temporal recurrence and change models
- build anomaly datasets
- add anomaly outputs to tribunal and passport

### Tranche C

- add uncertainty calibration
- add soft-logic fusion
- add GraphRAG explanation audits

## 9.5+ Benchmark Contract

Helios does not get to claim `9.5+` unless it beats the benchmark suite in [graph_training_benchmark_suite_v1.json](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/fixtures/adversarial_gym/graph_training_benchmark_suite_v1.json).

Graduation gates:

- graph construction quality is above threshold
- missing-edge recovery is above threshold
- temporal recurrence beats heuristic baselines
- anomaly detection beats baseline on hostile subgraphs
- uncertainty is calibrated
- GraphRAG explanations remain provenance-faithful
- hostile end-to-end packs stay green

## Recommended Success Metric

The key product metric is not abstract embedding quality.

It is:

`required edge family coverage x path correctness x calibration x hostile-case decision quality`

That is the metric family that moves Helios toward `9.5+`.

## Primary Sources

- Heterogeneous Graph Transformer: [arXiv:2003.01332](https://arxiv.org/abs/2003.01332)
- Temporal Graph Networks: [arXiv:2006.10637](https://arxiv.org/abs/2006.10637)
- Neural Bellman-Ford Networks: [NeurIPS 2021](https://papers.nips.cc/paper_files/paper/2021/file/f6a673f09493afcd8b129a0bcf1cd5bc-Paper.pdf)
- GraphMAE: [arXiv:2205.10803](https://arxiv.org/abs/2205.10803)
- State Space Models on Temporal Graphs: [NeurIPS 2024](https://papers.neurips.cc/paper_files/paper/2024/file/e5ba3d6d93213db6b1d1931c6517fe1a-Paper-Conference.pdf)
- History Repeats Itself for Temporal KG Forecasting: [arXiv:2404.16726](https://arxiv.org/abs/2404.16726)
- Deep Graph Anomaly Detection Survey: [arXiv:2409.09957](https://arxiv.org/abs/2409.09957)
- Uncertainty Quantification on Graph Learning: [arXiv:2404.14642](https://arxiv.org/abs/2404.14642)
- Uncertainty Management in Knowledge Graph Construction: [arXiv:2405.16929](https://arxiv.org/abs/2405.16929)
- Probabilistic Soft Logic: [official docs](https://psl.linqs.org/wiki/)
- Hyper-SAGNN: [arXiv:1911.02613](https://arxiv.org/abs/1911.02613)
- GraphRAG: [arXiv:2404.16130](https://arxiv.org/abs/2404.16130)
- Structural Measures of Resilience for Supply Chains: [arXiv:2303.12660](https://arxiv.org/abs/2303.12660)
- Relational Graph Transformer: [arXiv:2505.10960](https://arxiv.org/abs/2505.10960)
- Neo4j GDS Link Prediction Pipelines: [official docs](https://neo4j.com/docs/graph-data-science/current/machine-learning/linkprediction-pipelines/link-prediction/)
