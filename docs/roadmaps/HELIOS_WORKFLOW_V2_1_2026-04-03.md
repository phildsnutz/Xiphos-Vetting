# Helios Workflow V2.1
## Mission-Scoped operating model for Vendor Assessment and Contract Vehicle Intelligence

Date: 2026-04-03  
Status: Internal working spec  
Author: Codex repo-grounded merge of:
- [HELIOS_WORKFLOW_V2_2026-04-03.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/roadmaps/HELIOS_WORKFLOW_V2_2026-04-03.md)
- [Helios_Pipeline_Workflow_v2.0_20260403.docx](/Users/tyegonzalez/Library/Mobile%20Documents/com~apple~CloudDocs/Helios_Pipeline_Workflow_v2.0_20260403.docx)

## Bottom line

V2.1 keeps the internal Helios spine:

- resolve first
- collect second
- validate before graph
- analyze from graph memory
- let AXIOM close the hardest gaps
- re-validate AXIOM output before it becomes durable

What changes in V2.1 is the interaction model.

Helios should feel like:
- a calm **Front Porch** for self-serve tasking
- a collaborative **War Room** for practitioners
- a **Xiphos Assist** overlay for hard targets

The system underneath stays one workflow:
- **Vendor Assessment** and **Contract Vehicle Intelligence** are the primary front doors
- **Cyber** and **Export** are supporting evidence layers
- **AXIOM** is the lawful-edge case-officer engine
- the **knowledge graph** is the durable provenance-backed memory

Companion docs:
- [HELIOS_WORKFLOW_IMPLEMENTATION_PLAN_2026-04-03.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/roadmaps/HELIOS_WORKFLOW_IMPLEMENTATION_PLAN_2026-04-03.md)
- [HELIOS_VALIDATION_GATE_SPEC_2026-04-03.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/roadmaps/HELIOS_VALIDATION_GATE_SPEC_2026-04-03.md)
- [HELIOS_ONE_GRAPH_PREMIUM_CLAIMS_MODEL_2026-04-03.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/roadmaps/HELIOS_ONE_GRAPH_PREMIUM_CLAIMS_MODEL_2026-04-03.md)

## What changed from V2

Keep:
- explicit mission scoping before collection
- Front Porch vs War Room as interaction layers, not separate products
- AXIOM throughout the workflow
- the hard `Phase 6 -> Phase 3 -> Phase 4` loop
- human-assisted learning feeding back into AXIOM

Reject or defer:
- dual-graph `Alpha / Omega` architecture
- marketplace-style partner economics as an architecture driver
- hiding confidence and provenance from War Room users
- treating AXIOM as the mechanical owner of every deterministic step

## Product model

### Front-door pillars

1. **Vendor Assessment**
   - supplier passport
   - decision posture
   - supporting cyber and export evidence when relevant

2. **Contract Vehicle Intelligence**
   - vehicle dossier
   - ecosystem map
   - incumbent / teammate / protest / archive / recompete picture

### Supporting layers

- **Cyber**
  - vulnerability and infrastructure evidence
  - not a separate front door

- **Export**
  - authorization and deemed-export evidence
  - not a separate front door

## Interaction layers

### Tier 1. Front Porch

User:
- BD lead
- capture manager
- contracts lead
- executive sponsor

Experience:
- chat-first intake
- polished dossier delivery
- low pipeline visibility
- calm progress language

Show:
- mission framing
- dossier outputs
- key gaps in plain English
- whether more work is possible

Hide:
- raw connector chatter
- graph schema
- validation arithmetic

### Tier 2. War Room

User:
- analyst
- capture practitioner
- CI operator

Experience:
- collaborative workspace
- progressive dossier build
- visible gap states
- lead suggestion and challenge flow

Show:
- what has been resolved
- what has been collected
- what is validated
- what is weak
- where AXIOM is stuck

Do not hide:
- provenance
- confidence labels
- unresolved contradictions

### Tier 3. Xiphos Assist

User:
- Xiphos operator plus client team

Experience:
- same War Room
- same graph
- same AXIOM loop
- higher skill at using it

Principle:
- Xiphos Assist is a service overlay, not a separate pipeline

## User-visible workflow

The operator should not feel a seven-phase machine.
The operator should feel six calm states.

### 1. Scope the mission
- AXIOM determines whether this is:
  - Vendor Assessment
  - Contract Vehicle Intelligence
  - capture support
  - market landscape
  - supply-chain assessment
- user context becomes a structured mission brief

### 2. Resolve the object
- vendor resolution for company-driven work
- vehicle resolution for CVI work
- explicit confirmation when ambiguous

### 3. Collect the picture
- route official sources first
- route lawful-edge sources second
- preserve no-data and contradiction signals

### 4. Review the working picture
- vendor path: passport, posture, supporting layers, unresolved questions
- vehicle path: incumbents, teammates, archive drift, protest path, recompete posture

### 5. Close the hard gaps
- AXIOM proposes and executes targeted approaches
- every AXIOM return goes back through validation
- accepted returns update the graph and dossier
- review and rejected returns remain visible as leads, not facts

### 6. Monitor drift
- watchlists
- alerts
- graph movement
- dossier reopen triggers

## Internal pipeline

### Phase 0. Mission scoping

Purpose:
- turn natural-language intent into a structured mission brief

Outputs:
- `engagement_type`
- `primary_targets[]`
- `known_context{}`
- `priority_requirements[]`
- `collection_depth`
- `timeline`
- `authorized_tiers`

Rules:
- do not ask more than two clarifying questions in sequence unless the target is unusably ambiguous
- use user-provided context as first-class signal, not decoration

### Phase 1. Resolve the entry object

Purpose:
- confirm the vendor or vehicle object before running collection

### Phase 2. Directed collection

Purpose:
- run the right collection plan, not all connectors blindly

### Phase 3. Validation and provenance gate

Purpose:
- decide what can become durable intelligence

Outputs:
- `accepted`
- `review`
- `rejected`

### Phase 4. Graph memory update

Purpose:
- persist only durable claims with evidence, source, and time

Current rule:
- only accepted AXIOM findings are eligible for promotion
- early promotion is deliberately narrow and explainable

### Phase 5. Analysis and dossier construction

Purpose:
- turn graph-backed evidence into usable judgments

### Phase 6. AXIOM gap-closure loop

Purpose:
- pursue the highest-value unresolved questions using lawful-edge collection

### Phase 7. Monitoring and re-open

Purpose:
- keep assessments and dossiers live over time

## Where AXIOM fits

AXIOM is present throughout, but it is not supposed to own every mechanical step.

### AXIOM should own
- mission scoping support
- ambiguity handling
- collection planning for hard targets
- gap prioritization
- lawful-edge approach selection
- contradiction escalation
- narrative support
- monitoring escalation

### AXIOM should not own
- identifier normalization
- routing tables
- deterministic connector dispatch
- graph persistence rules
- confidence arithmetic

## Confidence and provenance rules

Front Porch:
- confidence can be translated into calm language
- provenance can be compressed

War Room:
- confidence labels stay visible
- provenance stays inspectable
- contradictions stay visible

Xiphos Assist:
- full claim/evidence context remains available

## Deferred on purpose

These are good ideas, but not now:

1. Partner-data marketplace mechanics
2. Dual `Alpha / Omega` graph architecture
3. Revenue-model-driven graph partitioning
4. Tier-specific data stores

The near-term build stays:
- one graph
- one validation gate
- one claim/evidence substrate
- different interaction layers and access surfaces

## Decision

Adopt V2.1 as the working Helios workflow spec.

Interpretation:
- use the user-facing interaction ideas from the v2.0 memo
- keep the repo-grounded validation and graph discipline from V2
- defer speculative graph-marketplace architecture until the operator loop is unquestionably strong
