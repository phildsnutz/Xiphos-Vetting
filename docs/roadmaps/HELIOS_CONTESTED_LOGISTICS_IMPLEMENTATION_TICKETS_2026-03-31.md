# Helios Contested Logistics Implementation Tickets

Date: 2026-03-31  
Scope: first implementation tranche after the contested logistics strategy docs  
Source docs:

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/roadmaps/CONTESTED_LOGISTICS_BLUEPRINT_2026-03-31.md`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/roadmaps/AMENTUM_CONTESTED_LOGISTICS_MVP_30_45_DAYS_2026-03-31.md`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/roadmaps/HELIOS_CONTESTED_LOGISTICS_ARCHITECTURE_MAP_2026-03-31.md`

## Build Order

The first contested-logistics tranche should not start with UI polish or broad data sprawl.

It should start with:

1. `mission_threads`
2. `resilience_scoring`
3. new relationship families
4. operator-facing mission-thread surfaces

That order keeps the system honest:

- the domain model exists first
- the scoring and reasoning exists second
- the graph semantics exist third
- the UI comes last

## Ticket 1: Mission Thread Domain Model

### Goal

Create a first-class object for a sustainment or mission thread so Helios can reason across a coherent operational context instead of a pile of unrelated vendor cases.

### Deliverable

New backend module:

- `backend/mission_threads.py`

### Data model

Add tables for:

- `mission_threads`
- `mission_thread_members`
- `mission_thread_roles`
- `mission_thread_notes`

Suggested core fields:

#### `mission_threads`

- `id`
- `name`
- `description`
- `lane`
- `program`
- `theater`
- `mission_type`
- `created_at`
- `created_by`
- `status`

#### `mission_thread_members`

- `mission_thread_id`
- `vendor_id`
- `entity_id`
- `role`
- `criticality`
- `subsystem`
- `site`
- `is_alternate`
- `notes`

### API surface

Add routes for:

- `POST /api/mission-threads`
- `GET /api/mission-threads/<id>`
- `POST /api/mission-threads/<id>/members`
- `GET /api/mission-threads/<id>/graph`
- `GET /api/mission-threads/<id>/summary`

### Pass bar

- can create a mission thread
- can attach existing vendors and graph entities to it
- can retrieve a scoped member list and summary

## Ticket 2: Mission Thread Graph Scoping

### Goal

Allow Helios to derive a graph view from a mission thread instead of a single case.

### Deliverable

Extend:

- `backend/knowledge_graph.py`
- `backend/graph_ingest.py`
- `backend/graph_analytics.py`

### Work

- add helper to build a thread-scoped subgraph from member vendor IDs and mapped entities
- keep provider-neutral import contract intact
- preserve existing case-scoped graph behavior

### Pass bar

- a mission thread graph can be built without breaking case graph APIs
- scoped graph respects current provenance and intelligence metadata

## Ticket 3: New Relationship Families

### Goal

Add the minimum contested-sustainment relationship vocabulary needed for resilience reasoning.

### Deliverable

Extend graph normalization and ingest for:

- `supplies_component_to`
- `maintains_system_for`
- `supports_site`
- `substitutable_with`
- `single_point_of_failure_for`

### Why these first

These are the highest-yield first-wave families because they let Helios say:

- who supports what
- what can substitute for what
- which node is the real bottleneck

Do **not** start with route-heavy families like `ships_through` or `depends_on_port` unless there is actual data support for them.

### Touch points

- `backend/graph_ingest.py`
- `backend/knowledge_graph.py`
- `backend/graph_analytics.py`
- relevant fixture packs under `fixtures/`

### Pass bar

- relationships ingest cleanly
- relationship families show up in graph summaries
- no regression to current ownership/control paths

## Ticket 4: Resilience Scoring Engine

### Goal

Score mission-thread members by resilience impact, not just generic risk or structural centrality.

### Deliverable

New module:

- `backend/resilience_scoring.py`

### Inputs

- decision importance
- structural importance
- control-path quality
- criticality tag
- substitute availability
- dependency concentration
- lane-specific risk signals

### Outputs

- `resilience_score`
- `brittle_node_score`
- `substitute_coverage_score`
- `mission_impact_score`
- `recommended_action`

### Pass bar

- top brittle nodes can be ranked for a mission thread
- scores are explainable and evidence-linked

## Ticket 5: Mission-Conditioned Decision Importance

### Goal

Make importance conditional on the mission thread instead of using one global interpretation.

### Deliverable

Extend:

- `backend/graph_analytics.py`
- `backend/supplier_passport.py`

### Work

- add mission-conditioned weighting
- preserve current `structural_importance` and `decision_importance`
- add `mission_importance` for thread-scoped use

### Pass bar

- the same supplier can rank differently across different threads
- analysts can see why

## Ticket 6: Mission Thread Passport

### Goal

Extend the current supplier passport into a mission-thread-aware operator artifact.

### Deliverable

Extend:

- `backend/supplier_passport.py`

Add fields:

- `mission_role`
- `criticality`
- `subsystem`
- `site`
- `alternate_suppliers`
- `single_point_of_failure`
- `resilience_summary`

### Pass bar

- one passport can be rendered both in case context and mission-thread context
- no regression in current case dossiers

## Ticket 7: Mission Thread Operator Surface

### Goal

Create the first UI surface that feels like contested sustainment decision support instead of vendor screening.

### Deliverable

New frontend surface:

- `frontend/src/components/xiphos/mission-thread-screen.tsx`

### Required panels

- thread overview
- critical suppliers
- brittle nodes
- substitute coverage
- unresolved questions
- graph view

### Pass bar

- operator can see top brittle nodes in one viewport
- operator does not need to click through 20 vendor pages to understand the thread

## Ticket 8: Mission Thread Dossier / Briefing Packet

### Goal

Generate a briefing packet for a whole mission thread, not just one vendor.

### Deliverable

Extend:

- `backend/dossier.py`
- `backend/dossier_pdf.py`

### Output

- thread summary
- top brittle nodes
- top control-path exposures
- unresolved evidence gaps
- recommended mitigations

### Pass bar

- one exportable packet can support a contracting or planning review

## Ticket 9: Fixture Pack For Contested Sustainment

### Goal

Avoid building the new layer only against live luck.

### Deliverable

New fixtures under:

- `fixtures/adversarial_gym/`
- `fixtures/mission_threads/`

### Cases to add

- single-point-of-failure subsystem
- dual-source alternate supplier
- hidden holding-company dependency
- service intermediary bottleneck
- export-constrained supplier in a critical thread

### Pass bar

- new analytics and thread model can be regression-tested without live sources

## Ticket 10: Amentum Demo Thread

### Goal

Create a concrete demo-ready mission thread around an Amentum-relevant sustainment example.

### Candidate thread themes

- rotary-wing sustainment
- expeditionary comms sustainment
- C5ISR support chain

### Deliverable

- one seeded mission thread
- one demo packet
- one operator walk-through path

### Pass bar

- can show the whole story in 10 minutes

## Recommended Sequencing

### Sprint A

- Ticket 1
- Ticket 2
- Ticket 9

### Sprint B

- Ticket 3
- Ticket 4
- Ticket 5

### Sprint C

- Ticket 6
- Ticket 7
- Ticket 8

### Sprint D

- Ticket 10
- demo hardening

## What To Cut If Time Gets Tight

Cut these first:

- broad new relationship families beyond the five listed above
- polished scenario simulation
- rich dashboard visuals

Keep these no matter what:

- mission thread domain model
- resilience scoring
- mission-conditioned importance
- mission-thread passport

## Brutal Read

If Helios does these tickets in this order, it becomes a credible contested sustainment intelligence platform.

If it skips the mission-thread model and jumps straight to “resilience” or “simulation,” it will create fake platform language on top of case-centric plumbing.
