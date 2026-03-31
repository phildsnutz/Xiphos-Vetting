# Amentum Contested Logistics MVP

Date: 2026-03-31  
Target window: 30 to 45 days  
Customer context: Amentum Center for Contested Logistics / USINDOPACOM-facing sustainment support

## Outcome

Deliver a scoped Helios pilot that proves one thing:

> Helios can identify supplier, control, cyber, export, and dependency risks across a contested sustainment thread faster than a manual review can.

## Pilot Thesis

This is **not** a full contested logistics system.

It is a **contested sustainment supplier intelligence pilot**.

That makes it credible for Amentum’s contracting and mission-support teams because it sits directly in the gap between:

- generic vendor screening
- and full operational logistics planning

## Customer Problem

Amentum’s Honolulu center is focused on planning, experimentation, and technology integration for sustainment in denied or degraded environments.

Before they can trust a sustainment concept, they need to know:

- which suppliers are truly critical
- where hidden ownership or foreign dependence exists
- whether cyber, export, or service dependencies create a weak link
- what alternate suppliers or nodes exist

That is the Helios wedge.

## Target Users

- contracting lead
- supplier assurance analyst
- program or capture manager
- mission assurance / security reviewer
- export / compliance reviewer

## Pilot Scope

### Mission scope

One sustainment thread only.

Examples:

- rotary-wing sustainment
- avionics or comms sustainment
- expeditionary C5ISR support package
- fuel, lift, or maintenance support chain

### Data scope

- 25 to 50 suppliers
- 1 to 3 mission-critical subsystem or service categories
- customer-provided supplier list plus Helios public-data enrichment

### Output scope

- supplier passports for each vendor
- one mission-thread dependency graph
- top brittle-node list
- ownership/control-path summaries
- cyber/export/counterparty caveats
- weekly delta monitoring during pilot window

## MVP Features

### 1. Mission-thread intake

Input:

- supplier list
- mission thread name
- critical subsystem or service categories
- priority vendors

Output:

- a structured pilot thread inside Helios

### 2. Contested sustainment passports

For each supplier:

- identity and official corroboration
- ownership and control-path summary
- financing, service, and network intermediaries
- cyber and export flags
- mission relevance and decision importance
- recommended next action

### 3. Mission dependency graph

Graph shows:

- suppliers
- holding entities
- critical services
- known intermediaries
- official and first-party evidence
- structural importance versus decision importance

### 4. Resilience panel

For the mission thread:

- top 10 brittle suppliers
- single points of failure
- unresolved high-impact questions
- known alternates or substitute paths

### 5. Monitoring and refresh

During pilot:

- rerun refreshes on critical vendors
- produce deltas in ownership, control, service, or adverse findings

## Explicit Non-Goals

- route optimization
- live inventory management
- fleet or cargo movement planning
- warehouse or maintenance execution
- transportation dispatch

Those do not belong in a 30 to 45 day MVP.

## Delivery Plan

### Week 1: Pilot framing and intake

Deliverables:

- pilot objective agreed
- one mission thread selected
- supplier list ingested
- pilot success metrics agreed

Technical work:

- add mission-thread grouping metadata
- add pilot workspace and tagging conventions

### Week 2: Supplier and graph baseline

Deliverables:

- supplier passports generated
- dependency graph baseline built
- top control and dependency risks surfaced

Technical work:

- connect current passports and graph summaries to mission-thread context
- rank vendors by decision importance, not just generic risk

### Week 3: Resilience view

Deliverables:

- brittle-node list
- alternate-source gaps
- top unresolved questions

Technical work:

- add mission relevance weighting
- add substitute and single-point-of-failure framing

### Week 4: Operator workflow and review

Deliverables:

- contracting or analyst review workflow
- exportable briefing packet
- customer review session

Technical work:

- add pilot-specific portfolio view
- tighten dossier and PDF output for meeting-safe handoff

### Week 5 to 6: Live monitoring and after-action

Deliverables:

- 1 to 2 refresh cycles
- delta report
- pilot readout with findings, wins, and gaps

Technical work:

- support monitored refresh
- package after-action evidence

## Required Engineering Additions

### Must add

- mission-thread or sustainment-thread entity grouping
- decision-importance scoring conditioned on mission context
- pilot-specific graph filters
- resilient-node and brittle-node reporting
- exportable Amentum-ready artifacts

### Helpful but not strictly required

- alternate-source suggestion logic
- subsystem-to-supplier mapping
- scenario card generation

## Success Metrics

### Product success

- a user can explain the top 5 sustainment risks in under 10 minutes
- at least one hidden dependency or control issue is surfaced that was not obvious from the supplier list alone
- the customer can identify which suppliers require deeper review

### Operational success

- 25 to 50 suppliers processed reliably
- dossier and PDF artifacts are meeting-safe
- AI state is honest and does not degrade into fake readiness

### Customer success

- Amentum sees Helios as a useful intelligence layer for contested sustainment
- the pilot earns a follow-on scope decision

## Likely Risks

### Risk 1: bad mission-thread input

If Amentum cannot provide a clean supplier set or subsystem framing, the pilot turns into generic vendor screening.

### Risk 2: overselling the platform

If the pilot is framed as route planning or logistics execution, expectations outrun the product immediately.

### Risk 3: thin intermediary coverage on the wrong cohort

Helios is improving here, but the intermediary lane is still weaker than ownership. The pilot should bias toward suppliers where public and official evidence can actually move the graph.

## Recommendation

Pitch this MVP as:

**Contested sustainment supplier intelligence for one mission thread**

That is specific, credible, and close enough to Amentum’s Honolulu center mission to get real attention.
