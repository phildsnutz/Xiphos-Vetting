# Helios Workflow V2.1 Implementation Plan
## Phase tickets for mission-scoped Vendor Assessment + Contract Vehicle Intelligence

Date: 2026-04-03  
Status: Internal implementation plan  
Depends on: [HELIOS_WORKFLOW_V2_1_2026-04-03.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/roadmaps/HELIOS_WORKFLOW_V2_1_2026-04-03.md)

## Bottom line

Helios does not need a full rewrite to reach the workflow model.

It needs:
- mission scoping before collection
- one explicit validation gate
- cleaner object resolution
- stronger vehicle-first resolution
- analysis separated from rendering
- a stricter AXIOM feedback loop into the graph

This plan is intentionally staged so each phase lands a durable product behavior.

## Phase 0. Mission scoping

Goal:
- turn natural-language intent into a structured mission brief before collection starts

Tickets:
1. Add `MissionBrief` with:
   - engagement type
   - targets
   - known context
   - priority intelligence requirements
   - collection depth
   - timeline
2. Support two operator modes:
   - Front Porch guided intake
   - War Room expedited intake
3. Treat user-provided context as first-class signal in downstream collection.
4. Persist draft mission briefs for resumed work.

Current repo status:
- interaction ideas are clear
- implementation is still route-centric, not brief-centric

Exit criteria:
- every major workflow starts from a structured mission brief
- AXIOM scopes before it hunts

## Phase 1. Resolve the entry object

Goal:
- make every workflow start from a confirmed vendor or vehicle object

Tickets:
1. Add `resolved_object` contract shared by Vendor Assessment and CVI entry flows.
2. Keep vendor resolution on the existing spine in [entity_resolution.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/entity_resolution.py).
3. Add a first-class vehicle resolver abstraction for:
   - vehicle name
   - aliases
   - PIID
   - prime
   - related award identifiers
4. Make the UI treat ambiguous resolution as a required confirmation step, not a silent fallback.

Current repo status:
- vendor resolution is real
- vehicle resolution is partial and route-local

Exit criteria:
- every enrichment or dossier run begins from a persisted resolved object
- ambiguity becomes explicit in the UI and API

## Phase 2. Directed collection

Goal:
- move from broad connector spray to object-aware collection plans

Tickets:
1. Define vendor vs vehicle collection profiles.
2. Route official sources first, then lawful-edge sources, then optional uploads.
3. Make connector output explicitly include:
   - success
   - no data
   - blocked
   - contradictory
4. Preserve raw fixture captures for replay on high-value connectors.

Current repo status:
- connector coverage is broad
- orchestration is still more connector-centric than workflow-centric

Exit criteria:
- each entry object gets a predictable collection plan
- no-data becomes a first-class signal

## Phase 3. Validation and provenance gate

Goal:
- stop AXIOM and edge collectors from self-certifying their own outputs

Tickets:
1. Create [validation_gate.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/validation_gate.py).
2. Define `accepted / review / rejected` gate outcomes.
3. Require official or corroborated support before graph promotion.
4. Use the same gate for:
   - AXIOM gap fill
   - dossier gap closure
   - future vehicle ecosystem inference
5. Expose validation outcome in API responses.

Current repo status:
- this was the biggest missing keystone

Exit criteria:
- AXIOM fills are no longer counted as closed solely because AXIOM said so
- accepted findings become graph-eligible, review findings remain analyst-visible, rejected findings stay out

## Phase 4. Graph memory update

Goal:
- persist only durable intelligence with provenance

Tickets:
1. Keep claim/evidence persistence on the existing graph contract in [knowledge_graph.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/knowledge_graph.py).
2. Add a promotion hook from validation outcomes into claim/evidence writes.
3. Keep Neo4j sync optional and downstream of the durable write.
4. Expand graph-side support for CVI entities:
   - vehicle
   - protest
   - award
   - installation
   - teammate/sub signal

Current repo status:
- claim/evidence persistence exists
- accepted AXIOM vehicle-participation findings now promote into claim/evidence-backed graph memory
- promotion is intentionally narrow until richer structured AXIOM findings exist

Exit criteria:
- every durable edge is explainable by claim, evidence, source, and time

## Phase 5. Analysis and dossier construction

Goal:
- separate analytical judgment from HTML rendering

Tickets:
1. Pull gap discovery into an explicit analysis stage.
2. Make vendor dossier, supplier passport, vehicle dossier, and comparative dossier consume shared analytical summaries.
3. Label outputs as:
   - observed
   - corroborated
   - inferred
   - weakly inferred
   - unknown
4. Keep unresolved dark space visible to the operator.

Current repo status:
- artifacts are strong
- analysis is still too coupled to rendering helpers

Exit criteria:
- narrative generation can change without rewriting the evidence model

## Phase 6. AXIOM gap-closure loop

Goal:
- make AXIOM a disciplined case-officer layer, not a self-licking search loop

Tickets:
1. Require every AXIOM gap fill to pass back through Phase 3.
2. Keep AXIOM focused on:
   - approach selection
   - ambiguity handling
   - gap prioritization
   - lawful-edge collection
3. Feed accepted findings into Phase 4 only.
4. Feed rejected findings into audit memory only.
5. Add source-vetting and outcome telemetry so AXIOM can learn which approaches actually work.

Current repo status:
- AXIOM gap filling exists
- the feedback loop is not fully strict yet

Exit criteria:
- AXIOM can hunt aggressively without poisoning the durable intelligence path

## Phase 7. Monitoring and re-open

Goal:
- keep assessments and vehicle dossiers live

Tickets:
1. Unify watchlists and graph drift triggers.
2. Add vehicle-specific monitoring signals:
   - protest movement
   - amendment churn
   - award change
   - teammate/sub drift
3. Re-open work only when new evidence changes the posture.

Current repo status:
- AXIOM monitoring is real
- CVI-specific drift logic is thinner

Exit criteria:
- Helios reopens work based on evidence, not timer-based noise

## Immediate build order

1. Validation gate
2. Vehicle resolver abstraction
3. Shared analysis summary contract
4. Promotion hook from validated findings into the graph
5. CVI-specific monitoring signals

## Hard rule

Do not expand AXIOM capability faster than the validation gate and provenance layer can control it.
