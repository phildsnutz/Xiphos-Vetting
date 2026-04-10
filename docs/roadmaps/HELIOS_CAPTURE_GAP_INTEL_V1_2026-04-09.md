# Helios Capture Gap Intel V1

## Product Thesis

Helios should not stop at surfacing uncertainty.

For pursuit, teaming, and vehicle work, Helios should convert unresolved intelligence into operator-ready closure tasks that tell a capture team:

- what is still unknown
- why it matters commercially
- what kind of source can close it
- what question to ask
- what proof is good enough

This is not a CRM expansion. It is an operational layer on top of existing Stoa and Aegis gap discovery.

## Target Users And Jobs To Be Done

Primary users:

- founder or capture lead
- BD lead
- analyst supporting a pursuit
- Xiphos LLC as premium service operator

Core jobs:

- decide which gaps are worth human effort
- convert weak-edge intelligence into targeted questions
- walk into a call or event with a real closure objective
- ingest what was learned back into Helios without pretending it is official truth

## MVP Scope

V1 should ship three contracts and one artifact.

Contracts:

- `CaptureGap`
- `FieldClosurePack`
- `ClosureEvidence`

Artifact:

- `Capture Orders`

V1 should do the following:

- generate `CaptureGap` objects from existing Aegis gaps, connector evidence, graph context, and analyst-curated proximity
- generate one `FieldClosurePack` per target or thread
- rank gaps by business impact and closure value
- make source honesty explicit
- support manual ingest of post-call, post-event, or post-outreach evidence as `ClosureEvidence`

## Non-Goals

Do not build any of this in V1:

- CRM
- contact manager
- conference scheduler
- travel logistics
- outreach sequencing
- badge scan workflows
- account planning system
- full capture operating system

If the feature requires Helios to own general sales operations, it is outside scope.

## System Design

### Placement

The feature should sit on top of current room flow:

- `Stoa` creates the first picture
- `Aegis` pressures the weak edge
- `Capture Orders` turns the surviving high-value gaps into human closure tasks

### Source Honesty Model

Every output must carry one or more of:

- `official`
- `first_party`
- `third_party_public`
- `analyst_curated`
- `unresolved`

V1 must not silently convert analyst-curated proximity into official truth.

### Generation Logic

Inputs Helios can already use:

- `intelligence_gaps`
- connector findings
- connector relationship types
- graph neighborhood
- supplier passport corroboration
- analyst-curated local proximity fixtures

Output logic:

1. detect closure-worthy gaps
2. score business relevance
3. infer best source class to close
4. generate closure questions
5. define acceptable proof threshold
6. package the top gaps into one field-ready artifact

## Data And Integrations

### CaptureGap

This is the minimum serious contract.

```json
{
  "gap_id": "cg-kavaliro-teaming-001",
  "gap_type": "teaming_and_vehicle_proximity_unverified",
  "subject_entity": "Kavaliro",
  "thread_scope": "general_pressure",
  "current_claim": "Kavaliro appears near SMX, Parsons, Alion, CACI, The Unconventional, and vehicles CEOIS, JCETII, C3PO, and LEIA.",
  "missing_fact": "Exact vehicle role, prime relationship, workshare, timing, and current-vs-historical status remain unverified.",
  "why_it_matters": "This uncertainty weakens teammate mapping and incumbent pressure.",
  "business_impact": "Affects bid posture, teammate targeting, and where capture should apply effort first.",
  "evidence_basis": [
    {
      "source": "axiom_known_proximity",
      "authority": "analyst_curated_fixture",
      "summary": "Kavaliro carried near SMX, Parsons, Alion, CACI, The Unconventional, CEOIS, JCETII, C3PO, and LEIA."
    },
    {
      "source": "public_search_ownership",
      "authority": "third_party_public",
      "summary": "Public identity and domain recovery held for Kavaliro."
    },
    {
      "source": "sam_gov",
      "authority": "official_registry",
      "summary": "Official registration support is thin or absent for the specific teaming and vehicle question."
    }
  ],
  "official_support_state": "thin",
  "confidence": 0.74,
  "priority": "high",
  "best_source_class_to_close": [
    "prime_capture_or_bd",
    "vehicle_adjacent_teammate",
    "first_party_artifact",
    "official_procurement_artifact_if_available"
  ],
  "best_collection_channel": [
    "targeted_outreach",
    "vehicle_teaming_conversation",
    "first_party_page_or_archive_hunt"
  ],
  "questions_to_ask": [
    "Was Kavaliro on LEIA, C3PO, or both?",
    "Under which prime did Kavaliro perform?",
    "What capability lane or labor category did Kavaliro hold?",
    "Was the relationship current, predecessor-bound, or one-off?",
    "Did The Unconventional and Kavaliro sit on the same team or on adjacent teams?"
  ],
  "acceptable_proof": {
    "minimum_standard": "one first-party artifact or two independent corroborations",
    "upgrade_rule": "do not promote proximity to confirmed teammate status without corroboration",
    "disqualifying_state": "single-source hearsay with no supporting artifact"
  },
  "recommended_next_action": "Pressure the SMX to LEIA/C3PO lineage first, then confirm whether The Unconventional and Kavaliro co-appear on the same pursuit or only adjacent ones.",
  "closure_value": "high",
  "status": "open"
}
```

### FieldClosurePack

This is the operator artifact.

```json
{
  "pack_id": "fcp-kavaliro-001",
  "target": "Kavaliro",
  "mission": "Resolve grey-zone teammate and vehicle posture around The Unconventional and SMX-linked vehicle work.",
  "working_picture": "Kavaliro sits in a proximity map near SMX, Parsons, Alion, CACI, The Unconventional, CEOIS, JCETII, C3PO, and LEIA. Official corroboration remains thin.",
  "priority_gaps": [
    "cg-kavaliro-teaming-001"
  ],
  "questions": [
    "Was Kavaliro on LEIA, C3PO, or both?",
    "Under which prime did Kavaliro perform?",
    "What workshare or capability lane did Kavaliro hold?"
  ],
  "proof_targets": [
    "first-party page or archived teaming reference",
    "prime-side confirmation",
    "independent teammate-side corroboration"
  ],
  "red_flags": [
    "human recollection without corroboration",
    "vehicle name confusion across predecessor and successor programs",
    "claim upgrade from proximity to confirmed role without proof"
  ],
  "recommended_next_actions": [
    "Start with SMX lineage and predecessor/successor clarification.",
    "Validate whether The Unconventional and Kavaliro appear on the same team or only the same mission space."
  ]
}
```

### ClosureEvidence

This is the feedback loop.

```json
{
  "closure_evidence_id": "ce-kavaliro-001",
  "gap_id": "cg-kavaliro-teaming-001",
  "collector": "Tye Gonzalez",
  "collection_method": "conversation",
  "source_type": "industry_contact",
  "source_reliability": "medium",
  "evidence_text": "Contact stated Kavaliro supported predecessor C3PO under SMX in analytics staffing, but could not confirm LEIA carryover.",
  "artifact_ref": "",
  "confidence": 0.62,
  "disposition": "partially_corroborates",
  "follow_on_action": "Need one independent corroboration or artifact before promoting to confirmed C3PO support."
}
```

## Notional Answers Helios Can Support Now

The following fields are worth building because Helios can already answer them well enough:

| Field | Helios can answer now? | Notes |
|---|---:|---|
| `gap_type` | yes | Existing Aegis gap surfaces already support typed gaps. |
| `current_claim` | yes | Can be built from connector findings, graph facts, and analyst-curated proximity. |
| `missing_fact` | yes | Existing `intelligence_gaps` plus corroboration logic is enough. |
| `why_it_matters` | yes | Can be templated from gap family and room context. |
| `business_impact` | yes | Can be inferred from pursuit, teaming, ownership, and vehicle ambiguity. |
| `evidence_basis` | yes | Already available across connectors and graph ingest provenance. |
| `official_support_state` | yes | Supplier passport and source classes make this straightforward. |
| `best_source_class_to_close` | yes | Helios can suggest source class even if it cannot identify a specific person. |
| `best_collection_channel` | yes | Outreach, artifact hunt, and vehicle-adjacent conversation are buildable. |
| `questions_to_ask` | yes | Templated from gap family and evidence shape. |
| `acceptable_proof` | yes | This should be policy-driven, not model-driven. |
| `recommended_next_action` | yes | Existing room doctrine already points toward next pressure move. |
| `priority` | yes | Existing gap priority and confidence can seed this. |
| `status` | yes | Open, in_review, partially_closed, closed, contradicted. |

The following should stay out of V1:

| Field | Why not now |
|---|---|
| `best_venue` | Too weak without event intelligence and would invite bluffing. |
| `people_to_probe` | Helios does not yet have reliable person-level source intelligence. |
| `dollar_roi_if_closed` | False precision risk is too high. |
| `meeting_schedule` | CRM and event ops creep. |
| `outreach_sequence` | Sales tooling creep. |

## Security And Operational Considerations

- Analyst-curated evidence must stay labeled as such.
- Manual ingest should preserve source type, confidence, and corroboration state.
- V1 should avoid storing sensitive personal contact data.
- Any export should preserve provenance and support later re-ingest.

## Milestones

### Milestone 1

Backend contract and generation logic only.

- normalize current Aegis gaps into `CaptureGap`
- add `official_support_state`
- add `best_source_class_to_close`
- add `questions_to_ask`
- add `acceptable_proof`

### Milestone 2

One analyst-visible artifact.

- add `Capture Orders` as a working artifact in Aegis
- support markdown or clipboard export
- no new giant screen yet

### Milestone 3

Manual closure ingest.

- accept `ClosureEvidence`
- link evidence to gap
- support `partially_corroborates`, `corroborates`, `contradicts`
- update gap state without forcing graph truth upgrades

### Milestone 4

Controlled feedback loop.

- allow graph promotion only when proof threshold is met
- preserve unresolved and contradictory state explicitly

## Risks And Open Questions

- Gap-to-question templating could become generic if not tuned by gap family.
- Teams may over-trust analyst-curated proximity unless labels stay strict.
- Event and person recommendation pressure will create scope creep if not checked.
- V1 should prove that users act on `Capture Orders` before any broader workflow buildout.

## Build Decision Rule

Build now if:

- the feature stays inside the current Stoa and Aegis loop
- the output improves human closure of real pursuit and teaming gaps
- the contracts stay provenance-native and honest

Shelve if:

- the work starts depending on CRM or event-ops infrastructure
- the product needs person-level contact intelligence to feel complete
- the output cannot beat a simple analyst note by a wide margin
