# Helios Dossier Gap Assessment

Date: 2026-04-06
Workspace: `/Users/tyegonzalez/Desktop/Helios-Package Merged`
Rubric: [HELIOS_DOSSIER_BASELINE_RUBRIC_2026-04-06.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/HELIOS_DOSSIER_BASELINE_RUBRIC_2026-04-06.md)
Artifact contract: [HELIOS_ARTIFACT_CONTRACT_2026-04-06.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/HELIOS_ARTIFACT_CONTRACT_2026-04-06.md)

## Executive Read

Current Helios is below the legacy dossier baseline.

The problem is not that the dossier bones are gone. The problem is that the bones are split across two output systems:

- [backend/comparative_dossier.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/comparative_dossier.py) still carries the old vehicle-dossier section map and visual structure, but large parts of it are generic placeholder theater rather than evidence-bound output.
- [backend/helios_core/brief_engine.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/helios_core/brief_engine.py) carries the newer graph, recommendation, and evidence-ledger spine, but it collapses the deliverable into a short brief and drops much of the vehicle-intelligence architecture.

So the current state is not "missing capability." It is "unreconciled capability."

That is why the old baseline still feels reachable. The repo still has the section map, the rendering primitives, the graph-aware reasoning layer, the supplier passport, and the recommendation engine. They are just not composed into one final artifact.

## Scored Assessment

### A. Current shipped case dossier path

Artifact path:
- [backend/dossier.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/dossier.py)
- [backend/helios_core/brief_engine.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/helios_core/brief_engine.py)
- [backend/dossiers/dossier-c-d70d78fd-20260406195702.html](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/dossiers/dossier-c-d70d78fd-20260406195702.html)

Weighted score: `48 / 100`

| Dimension | Score | Weight | Weighted | Why |
| --- | ---: | ---: | ---: | --- |
| Deliverable architecture | `2/5` | `20` | `8.0` | The current HTML brief has `Axiom Assessment`, `Graph Read`, and `Evidence Ledger`, but it does not cover the fuller dossier structure expected from the baseline. |
| Executive decision utility | `4/5` | `15` | `12.0` | Recommendation, support line, confidence read, and next gaps are present and sharper than the old baseline in some places. |
| Evidence discipline | `3/5` | `15` | `9.0` | Evidence ledger exists, but explicit `observed / inferred / assessed / unknown` separation is not enforced. |
| Gap intelligence | `3/5` | `12` | `7.2` | `What needs to be closed` is useful, but thinner and less operational than the old gap sections. |
| Graph-centered reasoning | `4/5` | `12` | `9.6` | This is the strongest part of the new brief. The graph is visibly treated as part of the reasoning spine. |
| Comparative and lineage reasoning | `0/5` | `10` | `0.0` | The shipped brief path does not carry comparative vehicle, lineage, or lifecycle reasoning. |
| Visual and export quality | `4/5` | `8` | `6.4` | The new brief looks intentional and exports cleanly, but it is materially thinner than the old dossier shape. |
| Stage continuity | `4/5` | `8` | `6.4` | This path fits `Stoa -> Aegis -> dossier` better than the old generator did. |

### B. Current vehicle/comparative dossier path

Artifact path:
- [backend/comparative_dossier.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/comparative_dossier.py)
- [backend/server_cvi_routes.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/server_cvi_routes.py)
- [docs/ITEAMS_Vehicle_Dossier_Pipeline_20260403.html](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/ITEAMS_Vehicle_Dossier_Pipeline_20260403.html)

Weighted score: `52 / 100`

| Dimension | Score | Weight | Weighted | Why |
| --- | ---: | ---: | ---: | --- |
| Deliverable architecture | `4/5` | `20` | `16.0` | The old vehicle dossier shape is still largely present: award anatomy, mission scope, prime, teaming, lineage, risk, gap analysis, and preliminary assessment. |
| Executive decision utility | `3/5` | `15` | `9.0` | It ends with a recommendation and priorities, but the judgment is often generic. |
| Evidence discipline | `2/5` | `15` | `6.0` | Confidence labels and state separation are weak compared with the legacy PDF baseline. |
| Gap intelligence | `4/5` | `12` | `9.6` | Gap sections are structurally strong and close to baseline. |
| Graph-centered reasoning | `1/5` | `12` | `2.4` | The graph is mostly absent from the rendered logic. |
| Comparative and lineage reasoning | `4/5` | `10` | `8.0` | This is the main surviving strength of the old path. |
| Visual and export quality | `3/5` | `8` | `4.8` | Layout is serviceable and familiar, but too much of the content is canned or placeholder. |
| Stage continuity | `2/5` | `8` | `3.2` | This path is weakly connected to current `Stoa` and `Aegis` flow. |

### C. Legacy baseline examples

Baseline score: `78-84 / 100`

That is the bar Helios has to regain and then exceed.

## Hard Findings

1. The current shipped dossier path is too thin for vehicle intelligence.
   - [backend/dossier.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/dossier.py#L2049) now delegates to [brief_engine.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/helios_core/brief_engine.py#L857).
   - That output is a strong executive brief, not a full vehicle dossier.
   - It is better on graph reasoning and recommendation authority, but weaker on long-form dossier architecture.

2. The old vehicle/comparative path still exists, but large sections are placeholder theater.
   - In [backend/comparative_dossier.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/comparative_dossier.py#L644), teaming analysis uses canned sample subcontractors.
   - In [backend/comparative_dossier.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/comparative_dossier.py#L720), risk findings are generic and not clearly bound to evidence.
   - In [backend/comparative_dossier.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/comparative_dossier.py#L736), recommendations are canned and not tied to graph or passport state.

3. The dossier gates had drifted and are now being realigned to one contract.
   - At the start of this assessment, [scripts/run_query_to_dossier_gauntlet.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/scripts/run_query_to_dossier_gauntlet.py) and the beta hardening harnesses were still enforcing old marker assumptions.
   - This reunification slice updated the gauntlet, beta harness, live hardening scripts, and customer demo gate to the shared universal contract:
     - `Helios Intelligence Brief`
     - `Axiom Assessment`
     - `Supplier Passport`
     - `Risk Storyline`
     - `Graph Read`
     - `Recommended Actions`
     - `Evidence Ledger`

4. The fixture gauntlet was failing on the dossier HTML contract before the reunification slice and now passes.
   - Original failing run:
     - command: `python3 scripts/run_query_to_dossier_gauntlet.py --mode fixture --report-dir /tmp/helios_qtd_probe`
     - result: `FAIL`
     - failure: `dossier html missing marker: Supplier passport`
     - report: `/tmp/helios_qtd_probe/query_to_dossier_gauntlet/20260406195702/summary.json`
   - Current passing run:
     - command: `python3 scripts/run_query_to_dossier_gauntlet.py --mode fixture --report-dir /tmp/helios_qtd_probe_contract`
     - result: `PASS`
     - report: `/tmp/helios_qtd_probe_contract/query_to_dossier_gauntlet/20260406200933/summary.json`

5. The repo still contains strong legacy dossier artifacts that show the target structure is reproducible.
   - [docs/ITEAMS_Vehicle_Dossier_Pipeline_20260403.html](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/ITEAMS_Vehicle_Dossier_Pipeline_20260403.html)
   - [docs/ITEAMS_Competitive_Intelligence_Dossier_20260403.html](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/ITEAMS_Competitive_Intelligence_Dossier_20260403.html)
   - Those artifacts prove the rendering system can still express the old section map.

## What Was Lost

The main losses were:

- full dossier section breadth on the shipped case-dossier path
- explicit vehicle and comparative intelligence structure
- visible intelligence-gap priority table as a standard output
- protest, lineage, adjacent-contract, and teaming sections as first-class requirements
- one coherent artifact contract across UI, routes, generators, and gates

## What Survived

The main bones still present in the repo are:

- the old CVI section map in [backend/comparative_dossier.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/comparative_dossier.py)
- the live CVI routes in [backend/server_cvi_routes.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/server_cvi_routes.py)
- the graph and recommendation spine in [backend/helios_core/brief_engine.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/helios_core/brief_engine.py)
- the supplier passport and recommendation authority in the current case path
- the PDF wrapper in [backend/dossier_pdf.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/dossier_pdf.py)
- surviving dossier artifacts under [docs](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs)

## Root Cause

This is the root cause:

- Helios replaced the old dossier renderer with a newer brief engine
- the newer engine improved graph-centered reasoning and recommendation authority
- but the old long-form vehicle dossier contract was not ported into the new engine
- and the quality gates were not rewritten to enforce a new unified artifact contract

So Helios drifted from `full intelligence dossier` to `good executive brief plus disconnected legacy dossier scaffolding`.

## Rebuild Direction

The right fix is not to revert to the old dossier path and not to keep the brief path as-is.

The right fix is to fuse the two:

1. keep the brief engine as the recommendation, graph, and evidence spine
2. port the full vehicle/comparative dossier section map into that engine
3. remove placeholder theater from the old comparative generator
4. define one final artifact contract that both HTML and PDF share
5. rewrite the gauntlet and hardening gates to enforce that contract

## Brutal Read

The old dossiers were better than the current shipped dossier path.

The current codebase still has enough structure to rebuild them.

The loss was not capability loss in the abstract. It was contract drift.
