# Aegis + AXIOM Vehicle Support Contract

Date: 2026-04-06
Workspace: `/Users/tyegonzalez/Desktop/Helios-Package Merged`
Related:
- [HELIOS_ARTIFACT_CONTRACT_2026-04-06.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/HELIOS_ARTIFACT_CONTRACT_2026-04-06.md)
- [HELIOS_DOSSIER_GAP_ASSESSMENT_2026-04-06.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/HELIOS_DOSSIER_GAP_ASSESSMENT_2026-04-06.md)

## Purpose

This contract defines how vehicle-specific support evidence may enter `Aegis` and be reasoned over by `AXIOM` without being mistaken for graph fact.

Current scope:
- contract-vehicle intelligence only
- `Aegis` only
- not `Stoa`
- not supplier-passport authority
- not tribunal authority
- not direct graph promotion

## Core Rule

`AXIOM` may reason over vehicle support evidence.

`AXIOM` may not silently merge vehicle support evidence into canonical graph truth.

## Allowed Input Blocks

Every future `Aegis` contract-vehicle prompt that includes this material must separate it into these blocks:

1. `graph_facts`
2. `support_evidence`
3. `predictions`
4. `unknowns`

No mixed block is allowed.

## 1. graph_facts

Definition:
- observed graph relationships
- claim-backed graph evidence
- promoted and validated graph state

Examples:
- `prime_contractor_of`
- `subcontractor_of`
- `teamed_with`
- `predecessor_of`
- `successor_of`
- promoted AXIOM graph findings that cleared validation

Prompt rule:
- may be treated as durable observed input

## 2. support_evidence

Definition:
- vehicle-scoped dossier support that is useful but not yet graph truth
- replayable archive and protest fixtures
- public-source recovery artifacts that have not been promoted into the graph

Current examples:
- `contract_opportunities_archive_fixture`
- `gao_bid_protests_fixture`

Prompt rule:
- must be presented as support evidence
- may strengthen or weaken a hypothesis
- may trigger collection or gap actions
- may not be restated as graph fact unless separately promoted

## 3. predictions

Definition:
- forward-looking judgments
- teaming forecasts
- likely protest pressure
- likely recompete dynamics

Prompt rule:
- must always remain labeled as predicted or assessed
- must cite both the supporting evidence and the main uncertainty

## 4. unknowns

Definition:
- unresolved blockers
- evidence that should exist but does not
- conflicts between graph facts and support evidence

Prompt rule:
- must be explicit
- must reduce confidence when material

## Allowed Uses In Aegis

When vehicle support evidence is eventually wired into `Aegis`, `AXIOM` may use it for:
- hypothesis generation
- alternatives checks
- disconfirming evidence checks
- next-best collection suggestions
- capture-intelligence recommendations
- lineage and protest narrative support

## Disallowed Uses In Aegis

Vehicle support evidence may not directly control:
- first-turn routing
- supplier-passport posture
- tribunal recommendation authority
- validation gate outcomes
- graph promotion
- final recommendation authority by itself

## Conflict Rule

If `support_evidence` conflicts with `graph_facts`, `AXIOM` must:
- state the conflict explicitly
- lower confidence
- recommend the next collection or validation move

It may not silently reconcile the conflict.

## Minimum Prompt Shape

Future contract-vehicle `Aegis` prompts should follow this shape:

1. Mission question
2. Vehicle name and prime context
3. `graph_facts`
4. `support_evidence`
5. `predictions`
6. `unknowns`
7. Output instruction

## Required Output Shape

When this lane is enabled, `AXIOM` should return:
- `working_read`
- `confidence`
- `graph_changed_the_read`
- `support_evidence_effect`
- `main_conflicts`
- `unknowns`
- `recommended_next_collection_moves`

## Release Gate Before Wiring

Do not wire vehicle support into `Aegis` until all of the following are true:
- archive support is rich enough to produce a non-thin lineage section for `ITEAMS`
- GAO support is rich enough to produce a non-thin protest section for `ITEAMS`
- dossier tests prove support evidence remains labeled and separate
- a dedicated `Aegis` test proves support evidence does not alter graph or passport truth

## Current Status

As of this document:
- vehicle support is active in the long-form dossier path
- vehicle support is not yet active in `Aegis`
- that is intentional
