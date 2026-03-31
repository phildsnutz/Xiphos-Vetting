# Helios To Contested Logistics Architecture Map

Date: 2026-03-31  
Purpose: map the current Helios codebase to a future contested logistics decision-support platform

## Brutal Read

Helios already has about 60% of the right architecture for a contested sustainment intelligence platform.

The missing 40% is not generic “more graph.” It is:

- mission-thread modeling
- subsystem and node criticality
- alternate-source logic
- disruption simulation
- customer-side data integration

## Architecture Map

| Future platform layer | Current Helios modules | What exists now | What is missing |
|---|---|---|---|
| Evidence ingestion | `backend/osint/public_html_ownership.py`, `backend/osint/public_search_ownership.py`, `backend/osint/sam_gov.py`, `backend/osint/usaspending.py`, `backend/osint/gleif_lei.py`, `backend/osint/sec_edgar.py`, `backend/osint/openownership_bods_public.py` | Strong base for official, first-party, and public signal capture | More mission-thread-specific sources and customer-provided data ingestion |
| Provider-neutral import contract | `backend/graph_ingest.py` | Strong and already central to the collector posture | More dependency-specific relationship families |
| Entity resolution | `backend/entity_resolution.py` | Real entity matching backbone | More normalization for facilities, depots, ports, and subsystems |
| Knowledge graph storage | `backend/knowledge_graph.py` | Real graph persistence and traversal | First-class mission-thread entities and relationship semantics |
| Dependency and control-path reasoning | `backend/network_risk.py`, `backend/graph_analytics.py`, `backend/supplier_passport.py` | Good ownership, control, and path quality groundwork | Mission-conditioned dependency reasoning and sustainment-specific criticality |
| Evidence-backed decisioning | `backend/decision_tribunal.py`, `backend/workflow_control_summary.py`, `backend/ai_analysis.py` | Strong approve/watch/block and analyst rationale surfaces | Contested logistics-specific posture outcomes and next-best-evidence logic |
| Counterparty lane | `backend/server.py`, `backend/dossier.py`, `backend/dossier_pdf.py`, `frontend/src/components/xiphos/case-detail.tsx` | Mature core workflow | Must be generalized into mission-thread operations without losing discipline |
| Cyber and export lanes | `backend/cyber_evidence.py`, `backend/cyber_risk_scoring.py`, `backend/export_evidence.py`, `backend/export_authorization_rules.py`, `backend/license_exception_engine.py`, `backend/transaction_authorization.py` | Valuable for sustainment risk context | Need mission-thread relevance instead of isolated lane views |
| Monitoring | `backend/monitor.py`, `backend/monitor_core.py`, `backend/monitor_scheduler.py`, `backend/server_monitor_routes.py` | Strong refresh and sweep backbone | Mission-thread deltas and disruption alerts |
| Operator UI | `frontend/src/components/xiphos/portfolio-screen.tsx`, `frontend/src/components/xiphos/entity-graph.tsx`, `frontend/src/components/xiphos/case-detail.tsx` | Analyst-oriented, now much better | No mission-thread or resilience-focused operator view yet |

## What Already Transfers Cleanly

### 1. Supplier passport

Current use:

- one vendor, one passport, one evidence-backed read

Contested logistics use:

- supplier node card inside a mission thread
- include mission role, subsystem role, substitute coverage, and disruption impact

### 2. Knowledge graph

Current use:

- ownership, control, and dependency reasoning across a case

Contested logistics use:

- model mission thread as supplier, subsystem, service, and node relationships
- distinguish structural importance from operational importance

### 3. Decision tribunal

Current use:

- approve, watch, deny, escalate

Contested logistics use:

- safe, degraded, brittle, unacceptable, escalate
- next evidence or mitigation step for the planner

### 4. Monitoring

Current use:

- case refresh and delta awareness

Contested logistics use:

- monitor mission-thread brittle nodes and supplier changes
- alert when a critical dependency degrades

## What Must Be Added

### New domain model

Helios needs first-class concepts for:

- mission thread
- subsystem
- sustainment node
- alternate supplier
- critical dependency
- mode of failure
- mitigation path

Likely new modules:

- `backend/mission_threads.py`
- `backend/sustainment_dependency_model.py`
- `backend/resilience_scoring.py`
- `backend/disruption_scenarios.py`

### New relationship families

Current relationship families are strong for ownership and general dependency, but contested sustainment will need more:

- `supplies_component_to`
- `maintains_system_for`
- `supports_site`
- `ships_through`
- `depends_on_port`
- `depends_on_lift`
- `depends_on_depot`
- `substitutable_with`
- `single_point_of_failure_for`

### New analytics

Current analytics:

- centrality
- path quality
- risk propagation

Needed analytics:

- subsystem criticality
- alternate coverage score
- mission degradation estimate
- node denial blast radius
- resilience score by mission thread

### New user surfaces

Need a first-class operator page for:

- mission thread overview
- brittle-node heatmap
- alternate-source comparison
- unresolved questions and evidence gaps
- disruption what-if cards

## What Helios Should Not Build First

Avoid these as first-wave platform targets:

- route optimization engine
- inventory planner
- fleet scheduling
- maintenance execution
- transport dispatch
- warehouse operations

Those are system-of-record or execution-system problems.

Helios should stay the decision-support and intelligence layer first.

## Recommended Build Sequence

### Phase 1: Mission-thread intelligence

Use existing Helios modules and add:

- mission thread object
- mission relevance weighting
- critical supplier ranking
- operator view for top brittle nodes

### Phase 2: Resilience modeling

Add:

- subsystem-to-supplier links
- alternate-source coverage
- blast-radius and substitute analysis

### Phase 3: Scenario support

Add:

- disruption cards
- node denial simulations
- mitigation recommendations

### Phase 4: Customer integrations

Add:

- procurement and supplier master import
- maintenance and sustainment data joins
- limited workflow integration

## Buildability Read

### What is buildable now

- supplier intelligence for a mission thread
- dependency graph with ownership and cyber/export overlays
- brittle-node ranking
- evidence-backed dossier and passport packet

### What is not buildable now without real new work

- subsystem-aware resilience scoring
- alternate-source coverage logic
- meaningful disruption simulation
- operational sustainment planning views

## Recommendation

Use the current Helios stack as the base for:

**contested sustainment intelligence**

Then add:

1. mission-thread model
2. resilience analytics
3. disruption decision support

That is the shortest credible path from current product truth to contested logistics relevance.
