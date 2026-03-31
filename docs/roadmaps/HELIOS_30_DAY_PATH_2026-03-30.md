# Helios 30-Day Path

Date: 2026-03-30
Priority order:

1. Runtime reduction
2. Modularization
3. Novelty quality maintenance

## Outcome Target

Preserve the current whole-system `PASS / GO / READY` state while reducing operator pain and lowering structural risk.

Success at 30 days means:

- live hardening stays green
- graph benchmark stays `6/6 PASS`
- slow collector-heavy flows feel materially faster
- critical giant files are broken into safer modules
- novelty queue quality improves without becoming the main lane

## Week 1: Runtime Reduction

### Goal

Cut the slowest live `enrich-and-score` paths, starting with the dominant public HTML ownership path.

### Primary targets

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/osint/public_html_ownership.py`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/osint/public_search_ownership.py`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/osint/gdelt_media.py`

### Work

- add adaptive stop rules once identity and ownership evidence cross a confidence floor
- stop duplicate first-party fetches
- move more expensive branch work behind earlier confidence gates
- add phase timing inside `enrich-and-score`, not just post-hoc connector timing
- profile both cyber and export canaries after each runtime cut

### Pass bars

- reduce dominant slow-path `enrich-and-score` below `45s`
- reduce `public_html_ownership` materially below current `~44s`
- no regression in query-to-dossier gauntlet verdicts

## Week 2: Backend Modularization

### Goal

Start paying down orchestration sprawl without changing behavior.

### Primary targets

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/server.py`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_ingest.py`

### Work

- extract cohesive route registrars from `server.py`
- separate graph, monitoring, and dossier route clusters into dedicated modules
- split `graph_ingest.py` into import-contract, entity synthesis, and relationship synthesis surfaces
- keep the existing provider-neutral import contract unchanged

### Pass bars

- first route extraction lands with no API regressions
- `server.py` drops below `6500` lines
- graph and readiness tests stay green

## Week 3: Frontend Modularization

### Goal

Make the analyst experience easier to evolve without touching behavior.

### Primary targets

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend/src/components/xiphos/case-detail.tsx`
- `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend/src/components/xiphos/entity-graph.tsx`

### Work

- extract case-detail support sections and helpers into sibling modules
- split graph inspector, provenance, controls, and path-analysis concerns inside `entity-graph.tsx`
- keep the current UI truth states intact: `PASS`, `FAIL`, `NOT_IMPLEMENTED`, `GO`, `READY`

### Pass bars

- `case-detail.tsx` drops below `5000` lines
- build stays green
- no regression in graph click, provenance, or monitor history flow

## Week 4: Novelty Quality Maintenance

### Goal

Improve the live novelty queue without letting it take over the roadmap.

### Primary targets

- `/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_embeddings.py`
- analyst review queue surfaces and their ranking inputs

### Work

- tighten surfacing filters
- add analyst-priority scoring
- keep negative-label harvest flowing
- keep novelty scorecards separate from holdout and construction scorecards

### Pass bars

- better top-of-queue quality on live analyst review
- no regression in graph benchmark
- no large new collector or model branch added just for novelty

## Non-Negotiables

- keep collector output routed through the existing provider-neutral import contract
- prefer replayable fixture-driven development before live-source automation
- do not let runtime work break graph honesty
- do not let modularization become a stealth feature rewrite

## What Not To Do

- do not start major new product lanes this month
- do not expand novelty discovery into a big new initiative
- do not add more bespoke collectors before the current ones are faster and cleaner
- do not keep piling logic into `server.py` and `case-detail.tsx`

## Metrics To Watch

- whole-system hardening verdict
- readiness verdict
- query-to-dossier gauntlet verdict
- graph benchmark `6/6` contract
- slowest `enrich-and-score` wall time
- file-size reduction in `server.py` and `case-detail.tsx`
- novelty queue confirmation rate

## Brutal Read

The project no longer needs more breadth to prove itself.

It needs faster execution and safer structure.

If the next 30 days follow this order, Helios gets more durable without losing momentum.
