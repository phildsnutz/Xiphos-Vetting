# Helios 1000-Entity Training Run Plan

Date: 2026-03-26
Objective: maximize knowledge-graph edge yield, disqualifier coverage, and analyst-demo value from one overnight run

## Honest Assessment

Running 1000 entities through Helios is worth it only if the cohort is curated for edge density.

Bad version:
- 1000 random defense companies
- too many low-signal foreign firms with no identifiers
- lots of isolated nodes, limited graph growth, weak replay value

Good version:
- 1000 entities selected to exploit Helios' strongest current connectors
- identifier-rich companies first
- US procurement and SEC footprints for graph density
- targeted foreign risk entities for disqualifier coverage
- person screening only where it creates real graph bridges

As of 2026-03-26, the hosted portfolio snapshot reports `868` vendors already loaded. The next 1000 should not be a generic volume push. It should be a graph-expansion push.

## Recommended Mix

Total: 1000 entities

1. `350` US defense anchors
   - SOF Week exhibitors
   - AUSA / Sea-Air-Space / Modern Day Marine / AFCEA West overlap where available
   - top US defense and dual-use vendors with CAGE, UEI, LEI, or CIK
   - goal: maximize USASpending, FPDS, SAM, SEC EDGAR, RECAP, and monitoring value

2. `250` US procurement-linked suppliers
   - subaward and subcontractor entities tied to the top 40 to 60 primes/exhibitors
   - prioritize companies already visible in USASpending, SAM subaward, or FPDS chains
   - goal: create actual graph edges, not just more case rows

3. `150` allied foreign defense companies with US footprint
   - UK, CA, AU, DE, FR, IL, KR, SE, NO, NL, JP
   - only include firms with one of:
     - US subsidiary
     - SEC / LEI / OpenCorporates footprint
     - regular US trade show presence
     - known US government or prime-contractor relationship
   - goal: cross-border bridges that still enrich well

4. `150` adversary and transshipment-risk entities
   - CN, RU, BY, IR plus UAE / HK / TR / CY / RS intermediaries
   - include sanctions-adjacent manufacturers, distributors, logistics shells, and front-company patterns
   - goal: hard-stop coverage, export-control signal, and network-risk propagation

5. `100` persons
   - executives, founders, UBOs, export-control officers, sanctioned individuals, and PEPs tied to categories 3 and 4
   - only include persons attached to a company already in the run
   - goal: convert isolated company risk into explainable person-linked network context

## Why This Mix Wins

Helios is strongest today on:
- US procurement and contractor data
- sanctions and export-adjacent screening
- SEC and identifier-driven entity resolution
- graph expansion from company-to-company relationships

That means the best overnight run is not “more countries.”
It is:
- more US-connected companies
- more procurement-linked suppliers
- more foreign entities that can bridge into the existing US graph
- more persons only where they explain ownership, control, or sanctions risk

## Inclusion Rules

Only include a company if at least one is true:
- has CAGE, UEI, LEI, CIK, or DUNS
- appears in USASpending, FPDS, or SAM
- appears on a trade show exhibitor list relevant to defense vetting
- has sanctions, export-control, or enforcement relevance
- has a known parent, subsidiary, distributor, or subcontractor relationship to a selected anchor

Do not spend the 1000 on:
- generic local LLCs with no identifiers
- small foreign firms with no US footprint and no sanctions/export relevance
- duplicate brand aliases unless the alias itself matters for screening
- more low-signal “watchlist noise” when a denser supplier chain candidate exists

## Tonight's Execution Order

Wave 1: `150` anchors
- load the highest-confidence US exhibitor and prime set first
- objective: seed strong company nodes and identifiers

Wave 2: `250` procurement-linked suppliers
- expand from Wave 1 into subawards, suppliers, and contractor chains
- objective: maximize relationship creation

Wave 3: `200` additional US and allied exhibitor entities
- fill in trade-show and partner coverage
- objective: improve demo breadth without sacrificing graph yield

Wave 4: `150` adversary / transshipment entities
- objective: improve hard-stop and network-risk demonstrations

Wave 5: `100` persons
- objective: attach real control and sanctions context to the riskiest firms

Wave 6: `150` reserve slots
- use these only after reviewing early hit rates
- refill with whichever category is producing the highest edge-per-entity yield

## Success Metrics

The overnight run is successful if it increases:
- graph-linked vendor count, not just total vendor count
- average relationships per entity
- number of cross-border bridges between US and foreign entities
- sanctions / export-control relevant network paths
- analyst-useful person-to-company explanations

The wrong metric is just “we processed 1000.”

## My Recommendation

Do it.

But do it as a graph-building cohort, not a vanity-ingest cohort.

If forced to choose between:
- 1000 random SOF Week style companies
- 650 curated companies plus 100 curated persons plus 250 procurement-linked suppliers

the second option is clearly better for Helios.

## Q2 Decision

The next engineering pass should prioritize graph density and cross-domain linkage over more `server.py` extraction.

Reason:
- beta is already stable enough to use
- tonight's training value depends more on graph yield than route-file elegance
- better entity selection and linkage will create more analyst-visible value than another structural refactor this week
