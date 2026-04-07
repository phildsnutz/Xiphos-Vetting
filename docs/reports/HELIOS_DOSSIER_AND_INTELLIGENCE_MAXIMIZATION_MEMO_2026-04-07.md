# Helios Dossier And Intelligence Maximization Memo

Date: 2026-04-07

## Bottom line

Helios is already stronger than the current dossier suggests.

The real gap is not missing AI, missing graph, or missing ML. The real gap is that the customer-facing artifact is underusing the strongest parts of the system:

- the supplier passport
- the decision tribunal
- graph intelligence and claim health
- network-risk pathing
- mission-conditioned graph importance
- storyline construction
- vehicle support evidence
- lightweight learned weighting
- graph embedding review and anomaly metrics

If Helios keeps presenting those assets as a cleaned-up fact sheet, the product will continue to feel expensive but shallow. If Helios fuses them into a claim-disciplined intelligence thesis with calibrated abstention, provenance, counterviews, and collection guidance, the product becomes much harder to dismiss.

## What Helios already has

### 1. A strong factual and provenance spine

The graph stack already does more than basic entity storage.

- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_ingest.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/graph_ingest.py) computes graph intelligence summaries that track:
  - required vs missing edge families
  - claim coverage
  - evidence coverage
  - contradicted edges
  - stale edges
  - official vs public-only edge mix
  - strong vs fragile vs disputed edges
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/supplier_passport.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/supplier_passport.py) already builds:
  - official corroboration summary
  - identifier status
  - claim health
  - ownership and control readouts
  - mission-conditioned graph summaries
  - tribunal inputs
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/network_risk.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/network_risk.py) already gives Helios a non-trivial path-based network risk model.

This is not a toy graph.

### 2. A much better decision layer than the dossier currently shows

The tribunal system is already doing the kind of reasoning a customer would pay for, but the dossier rarely exposes it cleanly.

- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/decision_tribunal.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/decision_tribunal.py) builds explicit `approve`, `watch`, and `deny` views from a rich signal packet.
- It includes:
  - ownership resolution
  - contradiction counts
  - official coverage thinness
  - graph thinness
  - foreign control risk
  - export and cyber gaps
  - learned softmax scoring via [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/learned_weighting.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/learned_weighting.py)

That is already a strong product primitive. The dossier should not flatten it into one watered-down recommendation paragraph.

### 3. A latent intelligence narrative layer

- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/storyline.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/storyline.py) already creates trigger / impact / offset / reach cards.
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/axiom_agent.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/axiom_agent.py) already builds a state contract for vehicle mode:
  - `graph_facts`
  - `support_evidence`
  - `predictions`
  - `unknowns`
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/vehicle_intel_support.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/vehicle_intel_support.py) already fuses:
  - notices
  - archive support
  - public HTML
  - GAO support
  - USAspending live vehicle evidence

Helios has the raw parts of an intelligence product. The dossier just is not orchestrating them well enough.

### 4. More ML and training capability than the artifact is currently exploiting

- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/learned_weighting.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/learned_weighting.py) already contains transparent fixture-trained models for:
  - graph edge truth
  - tribunal stance probabilities
  - calibration assessment
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_embeddings.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/graph_embeddings.py) already contains:
  - graph link prediction
  - missing-edge recovery metrics
  - temporal recurrence metrics
  - uncertainty-fusion metrics
  - subgraph anomaly metrics
  - GraphRAG explanation-faithfulness metrics
  - entity-resolution metrics

That means the product is not blocked on “we need to invent ML.” The product is blocked on deciding where ML should influence the dossier and where it should stay behind the scenes.

## The main problem

The dossier is still too close to a curated passport.

It often answers:

- who the entity is
- what identifiers it has
- what sources were queried
- what findings exist

when the customer is actually paying to answer:

- what is ordinary here
- what is unusual
- which unusual things actually matter
- which ones are probably noise
- what would change the judgment
- what should be done next
- how much of the answer is truly supported

That is a synthesis failure, not a data failure.

## What world-class should look like

Helios should generate a dossier as an intelligence thesis, not a sectioned record dump.

Every dossier should force five questions:

1. What is the strongest supported story?
2. What is the strongest competing story?
3. What evidence makes the difference?
4. What remains dark?
5. What would change the recommendation quickly?

That should become the core dossier contract.

## Highest-ROI moves

### Move 1: Add an intelligence thesis layer above the current sections

Create a new orchestration layer that sits between the raw context objects and the final brief renderer.

Proposed object:

```python
intelligence_thesis = {
    "principal_judgment": {},
    "counterview": {},
    "decision_shifters": [],
    "dark_space": [],
    "collection_priority": [],
    "supporting_claims": [],
}
```

Inputs should come from:

- supplier passport
- decision tribunal
- storyline
- graph intelligence summary
- ownership/control readout
- network-risk key paths
- AXIOM support bundle
- score and enrichment

The thesis layer should produce:

- the lead call
- the best alternative interpretation
- why the lead call currently wins
- what evidence still threatens it

This is the highest-value change.

### Move 2: Make the dossier claim-centric, not section-centric

Microsoft’s recent Claimify and VeriTrail work points in the right direction.

- Claimify argues that long-form outputs should first be broken into simple, verifiable claims, and that high-quality claim extraction must handle ambiguity conservatively.
- VeriTrail shows that multi-step generation should be traceable as a graph of intermediate artifacts, with provenance and error localization rather than just final-output scoring.

Sources:

- [Claimify / Towards Effective Extraction and Evaluation of Factual Claims](https://www.microsoft.com/en-us/research/publication/towards-effective-extraction-and-evaluation-of-factual-claims/)
- [VeriTrail: Detecting hallucination and tracing provenance in multi-step AI workflows](https://www.microsoft.com/en-us/research/blog/veritrail-detecting-hallucination-and-tracing-provenance-in-multi-step-ai-workflows/)

Helios should adopt the same operational idea:

- extract dossier claims
- map each claim to supporting graph claims, evidence records, or support evidence
- downgrade or suppress claims that cannot be grounded
- preserve an error path when a claim fails support

This would immediately improve trust.

### Move 3: Use selective generation and abstention instead of bluffing

Two useful references:

- [SelectiveNet](https://proceedings.mlr.press/v97/geifman19a.html) shows the value of integrated reject options rather than post-hoc confidence thresholds.
- [Self-Evaluation Improves Selective Generation in Large Language Models](https://proceedings.mlr.press/v239/ren23a.html) shows that self-evaluation can improve when the model should abstain.

For Helios, the product implication is simple:

- every claim-worthy section should be able to say `supported`, `conditional`, or `withheld`
- if the claim is too weak, the dossier should say less, not more
- the system should prefer a sharp `unknown` over an impressive bluff

Do not tune truth by customer type.

What can change by customer or program:

- required support threshold
- escalation threshold
- acceptable uncertainty before approval

What must not change:

- whether a claim is observed, inferred, assessed, or unsupported

### Move 4: Expose the tribunal as competing cases, not hidden math

The current tribunal is a strong internal asset. It needs a better customer-facing translation.

Instead of one final posture line, the dossier should show:

- `Why proceed`
- `Why hold`
- `Why stop`
- `Why the current recommendation wins`

That structure is already in the code. It just is not surfaced cleanly.

This will make Helios feel more like a real analytical partner and less like a score explainer.

### Move 5: Use graph intelligence as a first-class narrative input

The dossier should directly incorporate graph quality and contradiction, not just graph existence.

Helios already knows:

- which edge families are missing
- whether control paths are thin
- whether claims are contradicted
- whether evidence is stale
- whether the graph is dominated by public-only edges
- which nodes matter most given mission context

Those should directly shape language like:

- “ownership/control picture is structurally thin”
- “network risk is driven by one corroborated intermediary path”
- “the graph is broad but fragile”
- “mission relevance concentrates in these three nodes”

That is much more valuable than saying “graph has 18 entities and 26 relationships.”

### Move 6: Use GraphRAG patterns where Helios actually benefits

GraphRAG is relevant to Helios, but only in the right places.

The Microsoft GraphRAG paper argues that graph-based indexing and community summaries are especially useful for global sensemaking and query-focused summarization over large corpora.

Sources:

- [From Local to Global: A Graph RAG Approach to Query-Focused Summarization](https://arxiv.org/abs/2404.16130)
- [Microsoft Research GraphRAG project updates](https://www.microsoft.com/en-us/research/project/graphrag/news-and-awards/)

The right Helios use cases are:

- “What makes this vendor unusual?”
- “What themes dominate the legal and ownership evidence?”
- “Which competitor clusters surround this vehicle?”
- “Where is the contradiction concentrated?”

The wrong use case is:

- letting GraphRAG invent facts that should instead come from the graph or evidence ledger

Recommendation:

- use GraphRAG-style global/local summarization for thematic synthesis
- do not use it as a substitute for claim-level evidence grounding

### Move 7: Convert AXIOM into a real collection advantage, not just internal notes

AXIOM’s playbook is strong. Its outputs need to become more operational inside dossiers.

The current internal doctrine in [/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/manuals/AXIOM_COLLECTION_PLAYBOOK_2026-04-02.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/manuals/AXIOM_COLLECTION_PLAYBOOK_2026-04-02.md) already gets key things right:

- anti-bullshit rules
- dark-space discipline
- lawful edge collection
- explicit shared vs vehicle vs vendor decision utility

The next step is to route AXIOM into:

- `why this is still dark`
- `what lawful source family closes it`
- `what is automatable`
- `what requires analyst lift`
- `what becomes advisory revenue`

The dossier should not just end with recommendations. It should end with an intelligence closure plan.

### Move 8: Use weak supervision for narrow, high-value taggers

Data Programming and later LLM-in-the-loop weak supervision are highly relevant to Helios.

Sources:

- [Data Programming: Creating Large Training Sets, Quickly](https://arxiv.org/abs/1605.07723)
- [Language Models in the Loop: Incorporating Prompting into Weak Supervision](https://arxiv.org/abs/2205.02318)

The right Helios use is not giant fine-tuning. It is narrow classifier improvement for tasks where labels are sparse but heuristics are rich.

Good candidates:

- materiality of adverse findings
- ownership/control ambiguity class
- protest relevance to future capture posture
- teammate recruitability / lock / swing classification
- contract notice churn severity
- staffing-fit signals from jobs, DSBS, and public evidence
- evidence-noise filtering for dossier inclusion

Helios already has:

- structured features
- expert heuristics
- adjudicated fixtures
- transparent small models

That is exactly where weak supervision pays off.

### Move 9: Use graph embeddings as a review queue, not a truth injector

The graph-embedding layer is promising, but the product posture matters.

Do:

- use predicted links to create analyst review queues
- use anomaly scores to prioritize cases and sections
- use temporal recurrence to identify changing control or teaming patterns
- use explanation-faithfulness metrics to score graph-derived narratives

Do not:

- turn predicted links directly into dossier facts
- let embedding similarity silently inflate confidence

The correct pattern is:

- embeddings produce hypotheses
- graph and evidence resolve them
- dossier only reflects the resolved result

### Move 10: Treat foreign identity depth as a first-class graph problem

The product will not reach the next level if foreign entities are still mostly public-HTML heuristics plus sparse corroboration.

The next graph truth push should prioritize:

- country registry mapping
- LEI and legal entity chain resolution
- registry-grade parent/control anchors
- better intermediary and service-provider path recovery
- contradiction handling when public web evidence conflicts with registry evidence

This is backbone work, not polish.

## What not to do

### 1. Do not buy your way into shallow differentiation

More feeds are not the moat. The playbook already says this, and it is right.

Paid data can speed collection. It does not replace:

- synthesis
- calibration
- provenance
- collection discipline
- customer-grade judgment

### 2. Do not overfit the product around a giant fine-tuned model

Helios does not need a huge proprietary model to get better fast.

The higher-ROI path is:

- better claim contracts
- better fusion of existing signals
- weak supervision for narrow taggers
- better abstention
- better provenance

### 3. Do not let generated prose outrun the graph

The dossier should be downstream of graph truth and support evidence, not upstream of it.

### 4. Do not treat every section equally

Some sections should shrink when evidence is weak.
Some sections should dominate when evidence is strong.

A fixed-template dossier that fills every box the same way is part of the current problem.

## Concrete implementation sequence

### Phase 1: Fix the dossier contract

Build a new thesis layer and claim contract.

Priority:

1. add `intelligence_thesis.py`
2. fuse passport, tribunal, storyline, and graph intelligence into one thesis object
3. render competing views and decision shifters
4. suppress or downgrade under-supported claims

### Phase 2: Add claim extraction and provenance checking

Priority:

1. extract verifiable claims from the draft dossier
2. attach each claim to graph claim IDs, evidence IDs, or support evidence
3. classify claims as:
   - supported
   - conditional
   - unsupported
4. reject unsupported high-salience claims from final output

### Phase 3: Turn ML into product leverage, not decoration

Priority:

1. create weak-supervision label functions for materiality and capture-intelligence classifiers
2. train small transparent classifiers on adjudicated fixtures
3. use selective thresholds and abstention for dossier inclusion
4. use graph embeddings only for analyst review queues and anomaly prioritization

### Phase 4: Upgrade vehicle and counterparty separately

Counterparty dossier should optimize for:

- trust posture
- ownership/control
- unusual signals
- what changes approval

Vehicle dossier should optimize for:

- attackability
- lineage
- teammate ecosystem
- protest pressure
- recompete posture

Do not force both products into one bland structure.

### Phase 5: Install a ruthless benchmark

Every candidate dossier should be scored against this bar:

1. Would a serious buyer learn something non-obvious in the first minute?
2. Are the strongest claims grounded or explicitly conditional?
3. Is the best competing interpretation visible?
4. Does the artifact distinguish signal from noise?
5. Does it say what would change the decision?
6. Does it expose dark space honestly?
7. Does it avoid platform-self commentary?
8. Would a customer pay for this, not just admire the formatting?

If the answer to 1 or 8 is no, the dossier fails.

## My blunt recommendation

If the goal is to exceed client expectations, Helios should stop acting like a prettier due-diligence PDF generator and start acting like a calibrated intelligence engine.

The fastest path is:

1. thesis layer
2. claim-level grounding
3. selective abstention
4. tribunal-as-counterviews
5. weak-supervision taggers
6. graph-driven thematic synthesis

That gets Helios much closer to “this changed my judgment” instead of “this summarized what I already knew.”

## Sources

### Internal Helios sources

- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/ai_analysis.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/ai_analysis.py)
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/axiom_agent.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/axiom_agent.py)
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/decision_tribunal.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/decision_tribunal.py)
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_embeddings.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/graph_embeddings.py)
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_ingest.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/graph_ingest.py)
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/learned_weighting.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/learned_weighting.py)
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/storyline.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/storyline.py)
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/supplier_passport.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/supplier_passport.py)
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/vehicle_intel_support.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/vehicle_intel_support.py)
- [/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/manuals/AXIOM_COLLECTION_PLAYBOOK_2026-04-02.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/manuals/AXIOM_COLLECTION_PLAYBOOK_2026-04-02.md)

### External research sources

- [From Local to Global: A Graph RAG Approach to Query-Focused Summarization](https://arxiv.org/abs/2404.16130)
- [Microsoft Research GraphRAG project updates](https://www.microsoft.com/en-us/research/project/graphrag/news-and-awards/)
- [Data Programming: Creating Large Training Sets, Quickly](https://arxiv.org/abs/1605.07723)
- [Language Models in the Loop: Incorporating Prompting into Weak Supervision](https://arxiv.org/abs/2205.02318)
- [SelectiveNet: A Deep Neural Network with an Integrated Reject Option](https://proceedings.mlr.press/v97/geifman19a.html)
- [Self-Evaluation Improves Selective Generation in Large Language Models](https://proceedings.mlr.press/v239/ren23a.html)
- [FaithEval: Can Your Language Model Stay Faithful to Context, Even If "The Moon is Made of Marshmallows"](https://arxiv.org/abs/2410.03727)
- [Towards Effective Extraction and Evaluation of Factual Claims](https://www.microsoft.com/en-us/research/publication/towards-effective-extraction-and-evaluation-of-factual-claims/)
- [VeriTrail: Detecting hallucination and tracing provenance in multi-step AI workflows](https://www.microsoft.com/en-us/research/blog/veritrail-detecting-hallucination-and-tracing-provenance-in-multi-step-ai-workflows/)
