# AXIOM Collection Playbook
## Internal collection planning system for Helios vendor assurance and contract vehicle intelligence
### Classification: XIPHOS INTERNAL / COLLECTION METHODOLOGY
### Last Updated: 2026-04-02

---

## Summary

AXIOM is an internal Helios collection-planning system.

It is not a customer-facing brand, not a mythic persona, and not a generic OSINT doctrine file. Its job is to produce lawful edge collection plans that improve two linked Helios objects:

- `vehicle dossier`
- `vendor assurance dossier`

The governing question is:

> what lawful edge collection system gives Helios the best repeatable advantage in building vehicle dossiers and vendor assurance decisions?

AXIOM exists to close the gap between official procurement records and operationally useful judgments:

- should we pursue this vehicle
- should we partner on this vehicle
- should we trust this vendor
- should we attack this incumbent ecosystem

Export, cyber, and compliance remain supporting evidence families. They are not co-equal product lanes inside AXIOM.

---

## Core Objects

### 1. Vehicle dossier

Primary decisions supported:

- attackability of the opportunity
- incumbent vulnerability
- likely teammate and subcontract landscape
- customer complexity and recompete posture

Core sections:

- identity and hierarchy
- incumbent lineage
- teammate and subcontract ecosystem
- protest and legal history
- labor and pricing analogs
- amendment churn and requirement instability
- customer map
- recompete posture
- evidence gaps

### 2. Vendor assurance dossier

Primary decisions supported:

- should this vendor be trusted
- is this vendor fit for this vehicle
- what disqualifiers or hidden risks exist
- where are the evidence gaps that block a clean decision

Core sections:

- corporate identity and lineage
- ownership and control overlays
- SAM and exclusion posture
- socioeconomic and vehicle fit
- export, compliance, and cyber overlays
- contract and subaward history
- capability and staffing fit
- disqualifiers and evidence gaps

### Shared evidence families

- award and IDV data
- subaward data
- protest and litigation data
- solicitation and amendment history
- team and subcontract inference
- labor and staffing signals
- corporate lineage and officer data
- export / compliance / cyber overlays
- customer map signals
- uploaded internal documents
- FOIA returns and public archive captures

---

## Operating Rules

### Anti-bullshit rules

AXIOM must reject:

- strategies that amount to buying more feeds and calling that differentiation
- tactics that depend on protected proposal data, CPARS narratives, full fee splits, or source-selection material
- tactics that only work through bespoke analyst heroics and cannot be routed into Helios workflows
- tactics that collapse when scaled across many vehicles or vendors
- tactics that cannot be confidence-scored honestly

### Decision utility taxonomy

Every finding must be labeled as one of:

- `vehicle`: useful for vehicle attackability or capture posture
- `vendor`: useful for vendor assurance or trust posture
- `shared`: useful for both
- `interesting_not_monetizable`: useful context but weak commercial value

### Dark-space rule

Absence of evidence is valid output. AXIOM must surface:

- what is directly observed
- what is corroborated
- what is inferred
- what remains dark

It must not turn dark space into fake certainty.

---

## Source Admissibility

### Allowed as core product evidence

These can drive high-confidence dossier fields:

- official federal procurement records
- official subaward reporting
- official protests and court records
- official corporate registry data
- official sanctions / exclusion / registration records
- public solicitation attachments and archived notice history
- lawfully obtained FOIA returns
- public wage tables and public rate cards
- user-provided internal documents lawfully owned by the customer

### Allowed as weak support only

These can support inference but should not stand alone:

- conference speaker pages
- public executive bios
- public job postings
- cached pages and historical mirrors
- Google-indexed residue
- media or trade reporting
- commercial enrichment feeds with unclear upstream provenance

### Allowed only as optional user upload

These may materially improve a dossier but cannot be assumed available:

- debrief notes
- internal org charts
- incumbent staffing spreadsheets
- customer-provided contracts, mods, or SOW packages
- customer-provided supplier evidence

### Reject outright

- protected bid or proposal materials not lawfully provided
- source-selection information
- credential abuse or login circumvention
- paywall bypass and anti-bot evasion
- illicit breach data
- mobile geolocation or intrusive personal surveillance for this use case
- unattributed brokered data with unverifiable provenance and rights

---

## Lawful Edge Collection Stack

### Official public backbone

Purpose:

- identity spine
- award history
- subaward traces
- protest and litigation base layer
- registration and compliance baseline

Primary sources:

- SAM contract awards
- USAspending
- FPDS field semantics
- SAM subaward reporting
- SAM entity and exclusion data
- GAO protest decisions
- COFC / PACER court materials
- SBA DSBS / SUBNet / mentor-protege sources
- public wage determinations
- public rate cards and GSA price analogs

### Paid acceleration

Purpose:

- faster retrieval
- analyst overlays
- higher recall on recompetes and competitors

Priority sources:

- HigherGov
- PACER

Optional later:

- GovTribe
- GovWin
- labor analytics
- property / facility data

Paid sources accelerate collection. They are not the differentiator.

### Lawful edge collection

Purpose:

- recover the high-value details official datasets do not hand over cleanly
- preserve disappearing evidence
- convert weak public traces into repeatable collection assets

Primary source classes:

- archive and diff of solicitations and amendments
- public attachment metadata extraction
- protest and litigation text mining
- FOIA-targeting and FOIA return ingestion
- labor-rate reconstruction
- incumbent continuity mapping
- teammate and subcontract inference
- customer-map reconstruction
- user-provided internal document parsing

### Optional user-provided enrichment

Purpose:

- raise confidence ceilings where public evidence is thin

Examples:

- draft or final PWS
- mods and task order packages
- customer org charts
- internal incumbent notes
- debrief artifacts
- supplier evidence packages

### Do-not-promise data

Never market these as dependable platform inputs:

- full proposal pricing volumes
- full technical volumes
- true fee splits to subs
- exact workshare percentages
- complete team lists on every vehicle
- CPARS narrative evaluations
- award fee earned history
- debrief notes unless customer-provided
- internal win themes and red-team findings

---

## Priority Tactics

Each tactic must include what it surfaces, why it is lawful, how repeatable it is, its productization path, confidence ceiling, buyer value, and failure mode.

### Vehicle tactics

1. `vehicle` Archive and diff of solicitation notices and amendments
2. `vehicle` Procurement document metadata extraction from public attachments
3. `vehicle` Protest and litigation mining across GAO and COFC
4. `vehicle` Labor-rate triangulation from public rate cards, wage floors, and staffing residue
5. `vehicle` Incumbent continuity mapping through public bios, speaker residue, and job postings
6. `vehicle` Customer-map reconstruction from budget docs, procurement docs, and org traces

### Vendor tactics

7. `vendor` Corporate lineage and officer crosswalk from registry and filing sources
8. `vendor` Vehicle-fit scoring using SAM status, set-aside status, capability keywords, and contract history
9. `vendor` Export / compliance / cyber overlays as disqualifier and trust modifiers
10. `vendor` Public staffing and capability residue to assess execution plausibility

### Shared tactics

11. `shared` Teammate and subcontract inference from subawards, certifications, JVs, and mentor-protege patterns
12. `shared` FOIA-targeting strategy for contracts, mods, PWS, Q&A, subcontracting plans, and source-selection summaries to the extent releasable
13. `shared` User-uploaded internal document parsing into graph and dossier structures
14. `shared` Confidence-scored evidence gap detection and explicit next-step collection queue

Deferred unless clearly justified:

- local footprint and facility intelligence
- hiring-surge analytics
- premium real estate intelligence
- generic adverse-media overlays

---

## Shared Graph And Confidence Model

### Graph families

Nodes:

- vehicle
- solicitation
- award
- modification
- document
- agency
- program office
- company
- person
- subcontract
- protest case
- court case
- location
- evidence item

Edges:

- `issued_by`
- `awarded_to`
- `modified_by`
- `performed_at`
- `predecessor_to`
- `subcontracts_to`
- `teamed_with`
- `mentor_to`
- `jv_partner_of`
- `protested_by`
- `litigates_with`
- `supports_vehicle`
- `works_on`
- `appears_in`
- `suggests_vehicle_fit`
- `raises_assurance_risk`

### Observed vs inferred

Observed:

- direct award relationships
- direct subaward relationships
- official protest / court links
- registry-backed company or officer links
- document-to-author metadata where plainly present

Inferred:

- likely teammate relationships
- likely incumbent continuity
- labor-rate ranges
- customer stakeholder map
- vehicle-fit and attackability posture

### Confidence labels

- `observed`
- `corroborated`
- `inferred`
- `weakly_inferred`
- `unknown`
- `contradicted`

Move upward when:

- an official source exists
- two independent sources align
- a direct document or uploaded artifact confirms the relationship

Move downward when:

- the source is stale, single-source, cached-only, or contradicted
- the relationship depends on identity resolution with unresolved ambiguity

Never state as fact:

- exact fee split
- exact workshare
- unverified teammate membership
- precise pricing without a defensible range

---

## MVP Build Order

### Phase 1

Goal:

- produce a credible vehicle dossier plus linked vendor assurance overlays

Build:

- vehicle resolution using existing procurement connectors
- dossier object for vehicle + vendor assurance pairing
- archive and diff pipeline for tracked notices
- protest / court panel
- teammate and sub inference from public sources
- confidence labels and evidence-gap panel

Output:

- one usable vehicle dossier with attackability summary
- linked vendor assurance snapshots for prime and visible subs

### Phase 2

Goal:

- close more of the public-data dark space without overbuying feeds

Build:

- labor-rate reconstruction
- incumbent continuity mapping
- customer-map reconstruction
- FOIA-targeting recommendation engine
- uploaded document parsing into the shared graph

Output:

- richer dossier with pricing analogs, continuity signals, and stronger next-step collection guidance

### Phase 3

Goal:

- operationalize repeatable collection assets and reduce analyst heroics

Build:

- structured source-vetting workflow
- reusable source catalog with admissibility labels
- monitoring queues for tracked vehicles and linked vendors
- optional premium-source overlays where justified by ROI

Output:

- repeatable collection program rather than one-off dossier craftsmanship

---

## Success Criteria

AXIOM is working only if it produces:

- one primary differentiator, not five
- a clear separation between product spine and optional enrichment
- tactics that are reusable and systematizable
- outputs that improve both vehicle attackability and vendor assurance
- honest confidence grading without bluffing protected or unavailable data

If the result is mostly beautiful reasoning with weak collection repeatability, AXIOM has failed.
