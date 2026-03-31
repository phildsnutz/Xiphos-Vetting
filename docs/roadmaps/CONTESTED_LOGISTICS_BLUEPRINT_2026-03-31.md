# Helios Contested Logistics Blueprint

Date: 2026-03-31  
Workspace: `/Users/tyegonzalez/Desktop/Helios-Package Merged`  
Branch: `codex/beta-ready-checkpoint`

## Product Thesis

Helios can become a real contested logistics platform, but only if it expands from its current strength instead of pretending to be a full logistics execution suite.

The winning thesis is:

> Helios becomes the intelligence, dependency, and resilience layer for contested sustainment.

That means Helios should help operators answer:

- which suppliers and intermediaries matter most to mission continuity
- where hidden ownership, financing, cyber, and service dependencies create failure risk
- what breaks if a supplier, bank, service, route, or node is disrupted
- what alternate sources, substitutes, or workarounds exist

It should **not** try to become ERP, TMS, fleet routing, or theater C2 in the first move.

## Decision

Build Helios toward contested logistics through a three-stage expansion:

1. supplier and dependency intelligence
2. mission-thread dependency mapping and resilience scoring
3. disruption simulation and decision support

Do **not** try to jump directly to transportation execution or full operational planning.

## Why This Path Is Real

Helios already has the right base primitives:

- provider-neutral evidence ingestion
- entity resolution
- knowledge graph construction
- ownership and control-path reasoning
- dossier, passport, and analyst review surfaces
- counterparty, cyber, and export risk framing
- monitoring and refresh loops

Those primitives are already closer to contested sustainment than they are to a generic vendor-screening app.

Current Helios already answers parts of the core contested-logistics problem:

- who is really behind a supplier
- whether a supplier is brittle, opaque, or exposed
- what service and network intermediaries sit underneath a company
- what risk signals exist across counterparty, cyber, and export lanes

That is enough to anchor a credible first platform move.

## Target Users And Jobs To Be Done

### 1. Contracting and supplier assurance teams

Jobs:

- vet sustainment suppliers before award
- identify hidden control or foreign exposure
- understand whether a vendor is safe to include in a mission thread

### 2. Program and sustainment managers

Jobs:

- understand what supplier dependencies are mission-critical
- see where single points of failure exist
- find alternate sources before a disruption occurs

### 3. Experimentation and wargaming cells

Jobs:

- model what happens if a node, service, bank, or vendor is denied
- pressure-test sustainment concepts against real supplier networks
- compare resilience across alternatives

### 4. Security, export, and mission assurance stakeholders

Jobs:

- identify cyber and export risk embedded in the sustainment chain
- understand whether a mission thread is legally and operationally supportable
- document the rationale for approve, watch, block, or escalate decisions

## Smallest Credible Platform Wedge

The smallest credible contested-logistics version of Helios is:

**mission-thread supplier intelligence**

Inputs:

- a sustainment use case
- a shortlist of suppliers, subs, OEMs, service providers, and mission nodes

Outputs:

- supplier passports
- dependency graphs
- control-path summaries
- resilience risks
- alternate source and follow-up recommendations

This is saleable. It is also buildable from the current repo.

## MVP Scope

### Must-have scope

- model a mission thread as a set of suppliers, components, services, facilities, and transport-adjacent nodes
- score suppliers by decision importance, not just graph structure
- show critical dependencies and control paths in one view
- identify ownership, financing, service, and network dependencies that create fragility
- surface alternate suppliers or substitute nodes where evidence exists
- persist dossier and passport artifacts for contracting and analyst use
- monitor key changes over time

### Must-have user outcomes

- an analyst can explain why a sustainment chain is brittle
- a contracting team can see which suppliers are the real risk
- a planner can see what breaks if a key node is denied
- a security or export reviewer can point to evidence, not just scores

## Non-Goals

Helios should explicitly avoid these as first-wave goals:

- transportation execution
- route optimization
- inventory management
- warehouse management
- maintenance scheduling
- fleet dispatch
- command-and-control replacement
- ERP replacement

Those are downstream integration opportunities, not the opening move.

## System Design

### Core product layers

#### 1. Evidence and identity layer

Purpose:

- resolve suppliers, sites, services, and counterparties into a common graph
- capture official, first-party, and public signals with provenance

Current Helios foundation:

- `backend/osint/*`
- `backend/entity_resolution.py`
- `backend/graph_ingest.py`
- `backend/knowledge_graph.py`

#### 2. Dependency graph layer

Purpose:

- represent supplier, component, service, network, and facility dependencies
- distinguish structural importance from decision importance

Current Helios foundation:

- `backend/knowledge_graph.py`
- `backend/graph_analytics.py`
- `backend/network_risk.py`
- `backend/supplier_passport.py`

#### 3. Mission-thread model layer

Purpose:

- group graph entities into a sustainment thread
- represent mission-critical subsystems, bottlenecks, alternates, and routes

Current Helios state:

- mostly missing as a first-class concept
- must be added

#### 4. Decision layer

Purpose:

- answer approve / watch / block / escalate
- identify what to do next when the graph is incomplete

Current Helios foundation:

- `backend/decision_tribunal.py`
- `backend/ai_analysis.py`
- `backend/workflow_control_summary.py`

#### 5. Operator layer

Purpose:

- let users inspect mission-critical dependencies instead of raw graph noise
- show brittle nodes, alternates, and unresolved questions

Current Helios foundation:

- `frontend/src/components/xiphos/entity-graph.tsx`
- `frontend/src/components/xiphos/case-detail.tsx`
- `frontend/src/components/xiphos/portfolio-screen.tsx`

## Data And Integrations

### Public and open sources

- SAM.gov
- USAspending
- GLEIF
- Open Ownership / BODS
- SEC EDGAR
- first-party websites and structured metadata
- public DNS, RDAP, MX, SPF, DMARC, and intermediary signals

### Customer-provided data needed for real contested-logistics value

- approved supplier lists
- BOM or component-to-supplier mappings
- program or mission-thread structure
- critical subsystem definitions
- depot, port, or site dependencies
- logistics assumptions and known alternates

### Later integrations

- procurement systems
- ERP / vendor master
- asset maintenance data
- transportation / route planning tools
- readiness and inventory systems

## Security And Operational Considerations

- keep Helios in unclassified or CUI-ready posture first
- maintain provenance and source traceability for every high-consequence claim
- do not let AI replace evidence-backed control surfaces
- treat lane-specific reasoning separately: counterparty, cyber, export, and contested sustainment should not blur into one generic risk blob

## Milestones

### Phase 1: Supplier intelligence for contested sustainment

Goal:

- turn Helios into a strong supplier and dependency risk layer for sustainment missions

Build:

- mission-thread entity grouping
- critical supplier ranking
- dependency and control-path views
- contracting-ready artifacts

### Phase 2: Resilience and failure-point mapping

Goal:

- identify brittle nodes, alternates, and blast radius

Build:

- subsystem-to-supplier modeling
- alternate-source modeling
- node criticality and substitute coverage
- resilience scoring

### Phase 3: Disruption simulation

Goal:

- support scenario analysis and experimentation

Build:

- what-if node denial
- route / service disruption overlays
- mission degradation estimates
- mitigation recommendation surfaces

## Risks And Triggers To Revisit

### Risk 1: trying to become too broad too early

Trigger:

- roadmap starts talking more about route execution than supplier intelligence

### Risk 2: weak mission-thread data

Trigger:

- customer cannot provide component, supplier, or sustainment-thread structure

### Risk 3: graph volume without mission relevance

Trigger:

- Helios adds more edges but operators still cannot explain mission fragility

### Risk 4: platform claim outruns product truth

Trigger:

- sales language implies end-to-end logistics planning or route optimization before those capabilities exist

## Brutal Read

There is a path for Helios to become a contested logistics platform.

But the credible path is:

- contested sustainment intelligence first
- resilience and dependency modeling second
- disruption decision support third

If Helios follows that sequence, it can become strategically important.

If it skips to execution-system fantasy, it becomes incoherent.
