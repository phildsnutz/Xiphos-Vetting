# Helios Artifact Contract

Date: 2026-04-06
Workspace: `/Users/tyegonzalez/Desktop/Helios-Package Merged`
Related:
- [HELIOS_DOSSIER_BASELINE_RUBRIC_2026-04-06.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/HELIOS_DOSSIER_BASELINE_RUBRIC_2026-04-06.md)
- [HELIOS_DOSSIER_GAP_ASSESSMENT_2026-04-06.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/HELIOS_DOSSIER_GAP_ASSESSMENT_2026-04-06.md)

## Purpose

This contract defines the product artifacts that must exist from first-turn intake through final dossier output.

The goal is simple:

- `Stoa` should produce a real intake artifact, not transient chat state
- `Aegis` should produce a real working assessment, not disconnected narrative
- the final dossier should be a deterministic projection of those artifacts plus graph and evidence state

This is the bridge between the old long-form Helios dossiers and the newer graph-centered brief engine.

## Core Product Rule

Helios should behave like a graph-backed executive intelligence partner using disciplined analytic tradecraft, not like an intelligence doctrine simulator or a search bot.

That means:

- doctrine stays mostly internal
- rigor shows up through behavior and artifact structure
- the graph is part of the reasoning spine
- uncertainty and dissent are visible
- the user can always revise the frame without getting trapped in the wrong branch

## Canonical Artifact Sequence

1. `MissionBrief`
2. `WorkingAssessment`
3. `DossierPacket`

No stage should skip directly to prose without emitting its artifact state.

## 1. MissionBrief

Producer: `Stoa`

Purpose:
- establish the decision question
- establish what object the user means
- capture first assumptions without freezing them
- define collection intent and stop conditions

Required fields:
- `brief_id`
- `created_at`
- `room = stoa`
- `decision_question`
- `object_type`
  allowed: `vehicle`, `vendor`, `entity`, `person`, `mixed`, `unknown`
- `routing_state`
  allowed: `resolved`, `ambiguous`, `corrected`
- `user_seed`
  original user text that opened the thread
- `canonical_subject`
  the working label after routing or clarification
- `ambiguity_options`
  competing interpretations when intake is unresolved
- `initial_assumptions`
- `collection_intent`
- `constraints`
- `stop_conditions`
- `handoff_ready`

Behavioral rules:
- `Stoa` asks `0-2` follow-ups max
- exact vehicle seeds are strong evidence, not blind locks
- if routing is ambiguous, ask one sharp clarifier
- user corrections override stale branch state immediately
- `Stoa` must never trap the user in the wrong mode
- doctrinal terms like `PIR` may exist internally, but UI phrasing should stay plain

## 2. WorkingAssessment

Producer: `Aegis`

Purpose:
- turn the mission brief into a graph-backed working judgment
- keep claims, evidence, graph movement, dissent, and gaps in one object
- support revision without collapsing into freeform prose

Required fields:
- `assessment_id`
- `brief_id`
- `created_at`
- `room = aegis`
- `working_question`
- `recommendation`
- `recommendation_authority`
- `counterview`
- `confidence`
- `graph_changed_the_read`
- `claims`
- `evidence_ledger`
- `graph_summary`
- `supplier_passport_snapshot`
- `gaps`
- `recommended_actions`
- `next_collection_moves`

Claim contract:

Every claim must carry:
- `claim_id`
- `statement`
- `state`
  allowed: `observed`, `inferred`, `predicted`, `reviewed_promoted`
- `confidence`
- `sources`
- `graph_support`
- `counterevidence`

Behavioral rules:
- `Aegis` owns deeper hypothesis work
- alternatives check, disconfirming evidence check, and assumptions check happen here
- counter-deception is targeted to deception-prone problems such as ownership, beneficial control, proxy relationships, quiet teaming, shell entities, and sanctions exposure
- there must be one visible recommendation authority and one visible counterview when dissent exists
- the graph must be able to upgrade, downgrade, or destabilize the working judgment

## 3. DossierPacket

Producer: final dossier renderer

Purpose:
- produce an executive-grade artifact that can be read as HTML, PDF, or interactive dossier without losing analytical integrity

Required universal sections:
- `Helios Intelligence Brief`
- `Axiom Assessment`
- `Supplier Passport`
- `Risk Storyline`
- `Graph Read`
- `Recommended Actions`
- `Evidence Ledger`

Required universal fields:
- `dossier_id`
- `brief_id`
- `assessment_id`
- `artifact_mode`
  allowed: `counterparty`, `vehicle`, `comparative_vehicle`
- `recommendation`
- `recommendation_authority`
- `counterview`
- `confidence_statement`
- `graph_changed_the_read`
- `source_trace`
- `gaps`
- `render_targets`
  allowed: `html`, `pdf`, `interactive`

Universal rendering rules:
- HTML and PDF must share the same analytical contract
- the dossier must separate `observed`, `inferred`, `predicted`, and `reviewed_promoted` in the underlying claim state
- user-facing confidence language such as `CONFIRMED`, `ASSESSED`, `INFERRED`, and `UNCONFIRMED` may be derived from those states, but not replace them
- recommendation, dissent, and graph impact must be visible without reading the whole document
- gaps and next actions are first-class output, not appendix material

## Dossier Mode Addenda

### Counterparty dossier

Minimum additional content:
- ownership and control posture
- supplier passport summary
- graph-backed control or influence paths
- evidence-bound risk storyline
- decision recommendation and next actions

### Vehicle dossier

Minimum additional content:
- award anatomy
- mission scope and requirements
- prime contractor profile
- subcontractor and teaming intelligence
- adjacent or overlapping contract context
- protest or litigation profile
- aggregated risk signals
- intelligence gap analysis
- preliminary capture or decision assessment

### Comparative vehicle dossier

Minimum additional content:
- side-by-side award anatomy
- prime comparison
- teaming persistence or transition analysis
- active versus expired lifecycle comparison
- lineage map
- risk signal comparison
- consolidated gap analysis
- final comparative judgment

## Provenance State Contract

This is mandatory across all stages.

- `observed`
  direct evidence captured from a source or reviewed record
- `inferred`
  analyst or system inference derived from observed evidence and graph structure
- `predicted`
  forward-looking projection, scenario, or likely outcome
- `reviewed_promoted`
  claim reviewed and promoted into a user-facing conclusion or recommendation

Helios must not blur these states together.

## Recommendation Contract

There must be one visible recommendation authority.

Required fields:
- `posture`
- `summary`
- `authority_sources`
- `counterview`
- `decision_gap`
- `what_would_change_this`

This fixes the older contradiction problem where different parts of the artifact implied different recommendations.

## Graph Contract

The graph is not optional decoration.

Every `WorkingAssessment` and `DossierPacket` must answer:
- what entities were mapped
- what relationships were corroborated
- what claim coverage exists
- what edge families are still missing
- whether the graph materially changed the read

If the graph did not materially change the read yet, the artifact must say so directly.

## Acceptance Gates

Current minimum HTML/PDF contract markers:
- `Helios Intelligence Brief`
- `Axiom Assessment`
- `Supplier Passport`
- `Risk Storyline`
- `Graph Read`
- `Recommended Actions`
- `Evidence Ledger`

These markers are the minimum universal contract, not the full end-state ceiling.

The full baseline ceiling remains the richer long-form vehicle and comparative dossier architecture defined in the rubric.

## Reunification Rule

The rebuild path is:

1. keep the current brief engine as the graph, recommendation, and evidence spine
2. make the current HTML/PDF paths share one universal dossier contract
3. port the surviving vehicle and comparative section map into that contract
4. remove placeholder theater from the old comparative generator
5. make the gauntlet and hardening scripts enforce this contract end to end

## Brutal Read

The old dossiers were better on breadth.

The new brief engine is better on graph reasoning, recommendation authority, and stage continuity.

Helios should not choose one and discard the other.

The right artifact is the fusion of both.
