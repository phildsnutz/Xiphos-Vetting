# Helios Validation Gate Spec
## Phase 3 control point for AXIOM and lawful-edge collection

Date: 2026-04-03  
Status: Internal spec  
Implements: [validation_gate.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/validation_gate.py)

## Purpose

The validation gate exists to answer one question:

**Can this finding become durable intelligence, or is it still just a lead?**

Helios needs this because AXIOM and edge collectors are allowed to hunt for high-signal public data, but they are not allowed to silently promote weak or thin findings into the knowledge graph or dossier as if they were settled fact.

## Scope

This first implementation covers:
- AXIOM gap-fill results
- CVI fill-gaps API responses
- AXIOM first-look inside the gap advisory pipeline

Future scope:
- direct connector outputs
- broader dossier gap closure
- graph ingest promotion hooks

## Decision outcomes

### `accepted`
- strong enough for durable promotion
- graph action: `promote`
- confidence labels:
  - `observed`
  - `corroborated`

### `review`
- useful lead, not durable fact
- graph action: `hold_review`
- confidence labels:
  - `inferred`
  - `weakly_inferred`

### `rejected`
- too thin, too weak, or too poorly evidenced
- graph action: `reject`
- confidence label:
  - `unknown`

## Inputs

The gate evaluates:
- AXIOM fill confidence
- distinct source count
- official-source count
- evidence presence
- average source authority
- average finding confidence

## Source weighting

The gate uses practical authority tiers:

### Highest trust
- `sam_gov`
- `usaspending`
- `fpds`
- `sam_subaward_reporting`
- `sec_edgar`
- `courtlistener`
- `ofac`
- `gleif`

### Middle trust
- `opencorporates`
- `opensanctions`
- durable structured public registries and aggregations

### Lower trust
- `public_html`
- `careers_scraper`
- `linkedin`
- `gdelt`
- general media or public capture sources

## Acceptance rules

### `accepted / observed`
Requires:
- at least one official or authoritative source
- at least one analyst-readable evidence snippet
- AXIOM fill confidence at or above `0.70`

### `accepted / corroborated`
Requires:
- at least two distinct sources
- at least two evidence-bearing findings
- average source authority at or above `0.65`
- AXIOM fill confidence at or above `0.65`

### `review / inferred`
Requires:
- at least one evidence-bearing finding
- average source authority at or above `0.55`
- AXIOM fill confidence at or above `0.50`

### `review / weakly_inferred`
Requires:
- at least one evidence-bearing finding
- AXIOM fill confidence at or above `0.35`

### `rejected`
Applied when:
- no findings are returned
- no readable evidence is returned
- authority remains too weak
- the result is still effectively single-source and unsupported

## Operational rules

1. AXIOM may propose, but the gate decides.
2. Only `accepted` results may be treated as closed intelligence gaps.
3. `review` results remain visible to analysts and may still support advisory or follow-on collection planning.
4. `rejected` results stay out of the durable intelligence path.
5. The API must expose validation reasons so operators understand why a result did or did not clear the gate.

## Current implementation slice

The first runtime implementation does two things:

1. `/api/cvi/fill-gaps`
- returns validation metadata per result
- computes `closed / partial / failed` from the validation decision, not just AXIOM self-reporting

2. `attempt_axiom_fill()` inside the gap advisory pipeline
- counts a gap as filled only if the validation gate returns `accepted`
- demotes review/rejected fills back into the unfilled/advisory path

## What this does not do yet

- automatic claim/evidence promotion into the graph
- contradiction review queues
- analyst override workflow
- freshness decay rules
- cross-source temporal conflict adjudication

Those are Phase 4 follow-ons, not prerequisites for this first gate.
