# Helios One-Graph Premium Claims Model
## Replace `Alpha / Omega` with claim-level access and source controls

Date: 2026-04-03  
Status: Internal recommendation  
Author: Codex

## Bottom line

Do not build two graphs right now.

Build:
- one graph
- one claim/evidence substrate
- one provenance model
- multiple access surfaces

Premium differentiation should come from:
- better validated claims
- deeper evidence access
- stronger AXIOM gap closure
- better analyst workflows

Not from:
- a second graph with duplicated infrastructure

## Why not `Alpha / Omega`

The dual-graph concept is attractive because it sounds like:
- clean product separation
- premium intelligence moat
- simple packaging

In practice it creates avoidable complexity:

1. duplicate sync and storage logic
2. contradiction handling across graph boundaries
3. rights and entitlement complexity
4. harder provenance reasoning
5. higher risk of stale or divergent truth

The graph is already hard enough to keep honest.
Two graphs this early is product theater.

## Recommended model

### One graph

Everything durable lands in one claim/evidence-backed graph:
- entities
- relationships
- claims
- evidence
- source activities
- asserting agents

### Different access layers

What changes by tier is not where truth is stored.
What changes is what the user can see and act on.

## Access model by tier

### Front Porch

Expose:
- polished dossiers
- top-line judgments
- source tier badges
- unresolved critical gaps

Compress:
- claim-by-claim provenance
- weak signals
- internal connector detail

### War Room

Expose:
- active claims
- confidence labels
- evidence rails
- contradiction states
- AXIOM review leads

Hide or defer:
- internal-only raw artifacts that are not customer-safe
- admin-only telemetry

### Xiphos Assist

Expose:
- full War Room
- deeper evidence context
- analyst notes
- engagement-specific work products

## Claim-level controls

Instead of graph duplication, use claim and evidence attributes:

- `source_class`
- `authority_level`
- `access_model`
- `vendor_id`
- `contradiction_state`
- `structured_fields`

Examples:

- `access_model = lawful_public_edge`
- `access_model = customer_provided`
- `access_model = xiphos_internal`

This allows the same graph to support:
- self-serve surfaces
- enterprise practitioner surfaces
- assisted engagement work

without splitting memory into separate graph universes.

## Premium model

Premium should mean:

1. more validated claims
2. deeper evidence visibility
3. stronger AXIOM-led gap closure
4. better monitoring and re-open logic
5. faster human-assisted escalation when needed

Premium should not mean:
- a different truth store

## Recommended packaging

### Base
- dossier delivery
- limited evidence detail
- calm narrative

### Practitioner
- War Room collaboration
- claim/evidence inspection
- AXIOM-guided gap closure
- graph navigation

### Assist
- practitioner surface plus Xiphos operator involvement
- scoped internal notes and engagement-specific work products where contractually appropriate

## Implementation rule

Near-term graph work should optimize for:
- provenance quality
- contradiction handling
- promotion discipline
- access controls on claims/evidence

Not for:
- graph duplication
- tier-specific graph sync jobs
- marketplace rights orchestration

## Decision

Adopt the one-graph premium-claims model.

Defer:
- `Alpha / Omega`
- marketplace-led graph partitioning
- pricing-driven architecture splits

Revisit only after:
- the validation gate is mature
- graph promotion is stable
- AXIOM gap closure produces durable value consistently
