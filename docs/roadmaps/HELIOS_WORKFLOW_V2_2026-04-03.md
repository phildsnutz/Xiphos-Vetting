# Helios Workflow V2
## Vendor Assessment + Contract Vehicle Intelligence Operating Model

Date: 2026-04-03  
Status: Internal working spec  
Author: Codex repo-truth rewrite from [Helios_Pipeline_Workflow_20260403.docx](/Users/tyegonzalez/Library/Mobile%20Documents/com~apple~CloudDocs/Helios_Pipeline_Workflow_20260403.docx)

## Bottom Line

The original workflow document had the right spine:

- resolve first
- collect second
- validate before graph
- analyze from graph memory
- let AXIOM close the hardest gaps
- re-validate AXIOM output before it becomes durable

This V2 reframes that workflow around what Helios is now:

- **Vendor Assessment** is the main operational decision loop
- **Contract Vehicle Intelligence** is the dossier and recompete loop
- **Cyber** and **Export** are supporting evidence layers, not co-equal front-door pillars
- **AXIOM** is the internal lawful-edge collection and gap-closure engine
- the **knowledge graph** is the provenance-backed intelligence substrate

Companion docs:
- [HELIOS_WORKFLOW_IMPLEMENTATION_PLAN_2026-04-03.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/roadmaps/HELIOS_WORKFLOW_IMPLEMENTATION_PLAN_2026-04-03.md)
- [HELIOS_VALIDATION_GATE_SPEC_2026-04-03.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/roadmaps/HELIOS_VALIDATION_GATE_SPEC_2026-04-03.md)

## Design Rules

1. Helios must accept two primary entry objects:
   - vendor
   - contract vehicle
2. Deterministic steps stay deterministic.
3. AXIOM is the intelligence layer, not the mechanical layer.
4. No low-confidence or gray-area finding enters the graph without re-validation.
5. The user should experience a calm workflow, not a visible seven-phase machine.

## User-Facing Workflow

This is what the operator should feel.

### 1. Start the work
- Choose **Vendor Assessment** or **Contract Vehicle Intelligence**
- Provide the starting object:
  - company name / alias / identifier
  - vehicle name / PIID / solicitation / known prime

### 2. Confirm the object
- Helios resolves the object
- If confidence is high, proceed
- If ambiguous, the user confirms the target
- If unresolved, Helios asks for a better query

### 3. Collect and map
- Helios runs directed collection
- The operator sees:
  - what was searched
  - what was found
  - what is weak
  - what is missing

### 4. Review the decision or dossier
- Vendor path:
  - supplier passport
  - evidence rails
  - decision posture
  - supporting cyber/export layers if relevant
- Vehicle path:
  - vehicle overview
  - incumbents / subs / ecosystem
  - protest / legal / archive signals
  - recompete posture

### 5. Close the hard gaps
- AXIOM proposes and runs focused collection approaches
- New findings re-enter the validation gate
- Accepted findings update the graph and the dossier
- rejected findings stay in audit memory only

### 6. Monitor drift
- AXIOM watchlists, alerts, and graph changes reopen the work when the world changes

## Internal Pipeline

This is what the system should actually do under the hood.

### Phase 1. Resolve the entry object

Goal:
- determine what the user actually meant

Variants:
- **Vendor resolution**
  - canonical name
  - identifiers
  - country
  - entity type
- **Vehicle resolution**
  - canonical vehicle object
  - prime
  - contract identifiers
  - related awards / children / aliases

Outputs:
- `resolved_object`
- `confidence`
- `resolution_evidence`
- `needs_user_confirmation`

### Phase 2. Directed collection

Goal:
- run the right collection plan, not every connector blindly

Inputs:
- resolved object
- object type
- identifiers
- country / mission / vehicle context

Outputs:
- standardized collection returns
- discovered identifiers
- discovered entities / relationships
- explicit no-data / failure / contradiction signals

### Phase 3. Validation and provenance gate

Goal:
- determine what can be trusted, what is weak, and what stays out

Functions:
- entity consistency checks
- temporal freshness checks
- cross-source corroboration
- source authority weighting
- contradiction detection
- gray-area re-validation

Outputs:
- validated claims
- rejected claims
- conflict queue items
- confidence labels

### Phase 4. Graph memory update

Goal:
- store durable intelligence with provenance

Functions:
- entity merge / create
- relationship merge / create
- claim and evidence persistence
- provenance retention
- graph-side risk propagation
- optional Neo4j sync

Outputs:
- updated graph state
- claim/evidence records
- network and passport refresh signals

### Phase 5. Analysis and dossier construction

Goal:
- turn graph-backed evidence into operator-usable judgments

Vendor outputs:
- passport
- posture
- risk rationale
- evidence rails
- unresolved gaps

Vehicle outputs:
- vehicle dossier
- ecosystem map
- sub / teammate gaps
- protest / archive / recompete posture

### Phase 6. AXIOM gap-closure loop

Goal:
- close the highest-value unresolved gaps with lawful-edge collection

Rules:
- AXIOM proposes ranked approaches
- AXIOM executes only within allowed source posture
- every returned finding goes back through **Phase 3**
- accepted findings update **Phase 4**
- rejected findings stay in audit memory

### Phase 7. Monitoring and re-open

Goal:
- keep dossiers and assessments live, not static

Signals:
- watchlist scans
- alert generation
- graph drift
- new evidence
- recompete timeline movement

## Where AXIOM Sits

AXIOM should be present throughout, but not as the blocker in every deterministic step.

### AXIOM should own
- collection planning for hard targets
- ambiguity handling
- contradiction adjudication support
- gap prioritization
- gap-filling approach selection
- dossier narrative assistance
- monitoring/watchlist escalation

### AXIOM should not own
- identifier parsing as the only mechanism
- connector dispatch plumbing
- graph CRUD
- confidence arithmetic
- routine deterministic transforms

## Repo-Truth Mapping

### Phase 1. Resolve the entry object

Current modules:
- [backend/entity_resolution.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/entity_resolution.py)
- [backend/knowledge_graph.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/knowledge_graph.py)

What is real:
- deterministic identifier extraction helpers
- fuzzy entity matching
- graph-side name lookup

What is partial:
- entity resolution exists, but it is not cleanly the first required gate for every workflow
- there is no equally mature explicit **vehicle resolution** phase abstraction

Main divergence:
- Helios still behaves more like `collect -> infer entity` in places than `resolve -> collect`

### Phase 2. Directed collection

Current modules:
- [backend/osint/enrichment.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/enrichment.py)
- [backend/server_axiom_routes.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/server_axiom_routes.py)
- [backend/axiom_agent.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/axiom_agent.py)

What is real:
- 50-connector enrichment spine
- country-aware filtering
- replay/dependency hints
- parallel execution
- AXIOM search + search/ingest + watchlist + alerts

What is partial:
- routing is still mostly connector-centric, not strongly profile-centric
- vendor vs vehicle collection plans are not yet formalized as separate orchestrators

Main divergence:
- collection is more powerful than it is selectively intelligent

### Phase 3. Validation and provenance gate

Current modules:
- partial behavior spread across:
  - [backend/graph_ingest.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/graph_ingest.py)
  - [backend/knowledge_graph.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/knowledge_graph.py)
  - [backend/axiom_gap_filler.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/axiom_gap_filler.py)

What is real:
- confidence exists in several places
- claim/evidence persistence exists
- provenance storage exists

What is missing:
- no single authoritative `validation_gate.py`
- no one place that decides `observed / corroborated / inferred / rejected`
- no formal conflict queue
- no explicit gray-area elevated scrutiny gate

Main divergence:
- the architecture wants a real validation phase, but the code still treats validation as distributed behavior

### Phase 4. Graph memory update

Current modules:
- [backend/knowledge_graph.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/knowledge_graph.py)
- [backend/graph_ingest.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/graph_ingest.py)
- [backend/network_risk.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/network_risk.py)
- Neo4j sync stack already wired into app runtime

What is real:
- entity / relationship / claim / evidence storage
- provider-neutral graph persistence
- vendor/entity linkage
- risk propagation
- Neo4j availability and sync path

What is partial:
- confidence-aware merge and contradiction handling are not yet the hard policy layer they should be

Main divergence:
- the substrate is strong, but the graph admission rules are not yet strict enough

### Phase 5. Analysis and dossier construction

Current modules:
- [backend/dossier.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/dossier.py)
- [helios_dossier.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/helios_dossier.py)
- [backend/comparative_dossier.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/comparative_dossier.py)
- [backend/supplier_passport.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/supplier_passport.py)

What is real:
- vendor dossier generation
- comparative vehicle dossier generation
- single vehicle dossier generation
- supplier passport construction

What is partial:
- narrative analysis and gap discovery are still somewhat entangled with dossier rendering

Main divergence:
- Helios can already produce strong artifacts, but the analysis layer is not yet a clean standalone stage

### Phase 6. AXIOM gap-closure loop

Current modules:
- [backend/axiom_gap_filler.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/axiom_gap_filler.py)
- [backend/gap_advisory_pipeline.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/gap_advisory_pipeline.py)
- [backend/axiom_agent.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/axiom_agent.py)
- [backend/server_cvi_routes.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/server_cvi_routes.py)

What is real:
- AXIOM gap filler exists
- wisdom memory exists
- gap advisory pipeline exists
- CVI routes exist and now degrade cleanly without blowing up on AI config

What is partial:
- the strict `6 -> 3 -> 4` loop is not yet fully formalized as a first-class pipeline
- source tiering exists conceptually, but is not yet enforced end-to-end as a durable policy object

Main divergence:
- AXIOM is architecturally in the right place, but the validation feedback loop is still softer than the workflow spec wants

### Phase 7. Monitoring and re-open

Current modules:
- [backend/server_axiom_routes.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/server_axiom_routes.py)
- existing monitoring / change surfaces in the product shell and dossiers

What is real:
- watchlist CRUD
- daemon controls
- alert surfaces
- monitoring data in the app

What is partial:
- monitoring is stronger for vendor/change workflows than for full CVI timeline/recompete drift

Main divergence:
- monitoring exists, but contract-vehicle-specific monitoring still needs maturation

## What This Means

### The good news

Helios already has most of the important bones:

- collection spine
- AXIOM search/gap-fill surfaces
- graph substrate
- passport/dossier outputs
- monitoring and watchlist behavior
- CVI entrypoints

### The hard truth

The missing piece is not “more intelligence ideas.”

It is:
- a strict validation gate
- a cleaner resolve-first posture
- a clearer separation between:
  - collection
  - validation
  - graph memory
  - analysis
  - gap closure

## Recommended Product Framing

### External product language

Helios should present as:

- **Vendor Assessment**
- **Contract Vehicle Intelligence**

with:

- **Cyber**
- **Export**

as supporting evidence layers.

### Internal system language

Helios should operate as:

1. resolve object
2. collect
3. validate
4. update graph memory
5. analyze and build artifact
6. let AXIOM close gaps
7. monitor drift

## Implementation Priorities

### P0
- formal validation gate
- explicit `6 -> 3 -> 4` feedback loop
- resolve-first orchestration for vendor and vehicle entry objects

### P1
- source tiering as durable metadata
- clearer vehicle-resolution orchestration
- separation of analysis phase from final dossier rendering

### P2
- wisdom memory schema hardening
- CVI-specific monitoring and recompete drift
- stronger profile-based connector routing

## Final Judgment

The original workflow document was directionally right.

This V2 is the version I would actually back:

- product-coherent
- graph-coherent
- AXIOM-coherent
- and closer to the code that already exists

The biggest strategic idea worth preserving is simple:

**AXIOM should be everywhere that intelligence judgment is needed, but nowhere that plain deterministic plumbing should suffice.**
