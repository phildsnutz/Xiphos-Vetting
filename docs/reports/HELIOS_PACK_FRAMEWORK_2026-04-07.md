# Helios Pack Framework

Date: 2026-04-07

## Why This Exists

Helios is no longer a single-model prompt box. It is a multi-stage intelligence system with routing, collection, graph adjudication, dossier generation, and analyst-facing explanation surfaces. That means the product needs working lines, not one vague intelligence phenotype.

The pack model is the internal operating language for that system.

## Core Principle

Helios should behave like a disciplined working pack:

- a strong quarterback chooses the play
- specialists handle the phase they are bred for
- every phase has a handler-visible purpose
- weak signals never get promoted just because they are loud
- the pack stops when the judgment is good enough, not when every possible action has been tried

## Working Lines

### Vesper

- Breed: Dutch Shepherd
- Role: Quarterback
- Function: Mission command
- Responsibility: preflight, playbook selection, execution ordering, stop conditions, fallback handling, human-gated audibles

Vesper is the command layer. Vesper decides what kind of run this is, how aggressive Helios should be, where human approval is required, and when the system should stop collecting and package judgment.

### Mako

- Breed: Belgian Malinois
- Role: Collector
- Function: Edge collection
- Responsibility: high-signal source pressure, gap closure, identifier recovery, time-bounded expansion at the edge

Mako is fast and aggressive. Mako should push collectors, not make final trust decisions.

### Bruno

- Breed: Rottweiler
- Role: Adjudicator
- Function: Adverse-case adjudication
- Responsibility: contradiction handling, hidden-control pressure, stop-case skepticism, no-noise-through discipline

Bruno is heavy and skeptical. Bruno should be activated when the cost of a false clean read is high.

### Sable

- Breed: Doberman
- Role: Finisher
- Function: Artifact finish
- Responsibility: sharp thesis, concise recommendation language, commercially useful opening, no weak-noise headline drift

Sable turns the run into an artifact worth paying for.

### Rex

- Breed: German Shepherd
- Role: Generalist fallback
- Function: Balanced fallback coverage
- Responsibility: steady support when the case does not justify a more specialized pressure thread

Rex is the balanced fallback line when the case is real but not extreme.

## Playbooks

### Control Path Hardening

Use when the analyst is asking about ownership, control, PLA exposure, beneficial ownership, or hidden intermediary structure.

Goal: either resolve a credible control story or explicitly leave it unresolved.

### Identity Repair Sprint

Use when the case is likely being distorted by weak identifiers, false matches, thin official corroboration, or noisy entity resolution.

Goal: stop identity weakness from poisoning the rest of the run.

### Export Route Adjudication

Use when export posture depends on route ambiguity, end-user ambiguity, transshipment, reseller structure, or person-screening pressure.

Goal: no clean proceed call while route ambiguity is still doing real work.

### Assurance Pressure Thread

Use when cyber, provenance, dependency, or supplier-assurance evidence is thin, contradictory, or high consequence.

Goal: pressure the weak links until they corroborate, bound, or fail.

### Artifact Finish

Use when the main need is not more searching, but a sharper brief.

Goal: package the evidence into a thesis, competing case, and dark space that changes the operator’s understanding.

### Drift Scan

Use for watch and monitoring flows.

Goal: surface only changes that materially alter the trust picture.

### Balanced Explanation

Use for general analytical prompts that still require explicit sequencing and safe boundaries.

Goal: deliver the best current explanation without pretending the case is cleaner than it is.

## Rules Of Pack Discipline

1. Vesper always calls the play.
2. Mako can expand the search, but not the trust boundary.
3. Bruno can block a weak case from sounding clean.
4. Sable cannot invent strength that the evidence did not earn.
5. Rex keeps the system useful when the case does not justify specialized aggression.
6. Human approval gates any live mutation, rerun, or state-changing action.
7. Every run should expose:
   - the selected playbook
   - anomaly pressure
   - step ownership
   - success condition
   - why the current view does or does not win

## Near-Term Repo Direction

1. Keep enriching `ai_control_plane.py` until the assistant plan is a real mission-command surface.
2. Add persistent run state so Vesper can resume rather than restart.
3. Add evaluator gates so Sable rejects weak openings before the dossier ships.
4. Add failure-budget logic so Mako does not waste time on low-value collector churn.
5. Add stronger Bruno logic for contradiction and disambiguation.

## Success Standard

Helios is working when:

- the operator can see the play before execution
- the system recovers cleanly from partial failures
- weak evidence does not dominate the artifact
- the dossier opening changes what a serious analyst thinks
- the user no longer needs an invisible human quarterback just to make the product behave
