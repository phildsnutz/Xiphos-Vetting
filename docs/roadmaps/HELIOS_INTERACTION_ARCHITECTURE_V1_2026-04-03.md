# HELIOS_INTERACTION_ARCHITECTURE_V1_2026-04-03

## Bottom line

Helios should feel like a brilliant intelligence partner, not a complicated application.

The product should be organized as **two rooms**:

- **Front Porch**: brief AXIOM in natural language and get work started
- **War Room**: collaborate with AXIOM at higher altitude when the problem needs deeper work

Everything else is subordinate:

- graph
- validation
- confidence
- connectors
- monitoring
- source routing
- dossier assembly

The user is never buying infrastructure.
The user is buying the feeling that a sharp, disciplined intelligence partner took the problem, worked it, and came back with something useful.

---

## The product sentence

**The plumbing justifies the price. The simplicity justifies the trust.**

If a UI element increases visible machinery without increasing the user’s feeling of trust, clarity, or competence, it should not ship.

---

## Why the current app still misses

The current live app is calmer than it was, but it still feels too much like software because it leads with:

- app structure
- tabs
- navigation
- surfaces
- explicit product modules

That is wrong for Helios.

The user should lead with:

- the question
- the conversation
- the handoff
- the result

The right metaphor is not “operator dashboard.”
The right metaphor is:

- **Front Porch**: a capable briefing conversation
- **War Room**: a deeper collaboration room

---

## Emotional architecture

UI should be designed against emotional states, not only screen states.

### State 1: Arrival

The user should feel:

- calm
- not overwhelmed
- invited to speak naturally

### State 2: Being understood

The user should feel:

- AXIOM is asking the right questions
- the product understands the domain
- they are not filling out a form

### State 3: Handoff

The user should feel:

- AXIOM has enough to begin
- they are no longer driving the process
- the system is taking ownership

### State 4: Quiet progress

The user should feel:

- momentum
- calm confidence
- no need to inspect machinery

### State 5: Delivery

The user should feel:

- the answer is coherent
- the narrative is clean
- the evidence is there if they want it

### State 6: Deeper collaboration

The user should feel:

- invited into a more serious room
- not lost in a dashboard
- still talking to AXIOM, just with more visible evidence and challenge capability

---

## Room model

## 1. Front Porch

### Purpose

Front Porch is the accessible briefing surface.

It is where:

- a BD executive starts
- a capture manager starts
- a contracts lead starts
- a PM starts
- a user with imperfect context starts

### What Front Porch feels like

- conversational
- calm
- premium
- minimal
- confident

### What Front Porch is for

- describe the problem
- answer a few high-leverage questions
- let AXIOM frame the work
- receive a preliminary or final deliverable

### What Front Porch is not for

- graph inspection
- watching collection internals
- steering every collection route
- staring at process state

### Front Porch visible anatomy

Keep the top bar minimal.
No left rail.
No shell on first contact.

Visible elements:

1. Helios mark
2. one orientation line
3. one large chat composer
4. 2 to 4 soft example prompts
5. a small top-right control cluster

Top-right control cluster should be limited to:

- `War Room`
- `Recent`
- `Examples` or `How It Works`
- account / workspace menu

That is enough.

### Front Porch top-bar anatomy

#### Left

- Helios wordmark

#### Center

- usually empty
- optionally one tiny text label like `Briefing`

#### Right

- `War Room`
- `Recent`
- `Examples`
- profile/workspace dropdown

Possible dropdown content:

- recent dossiers
- saved engagements
- workspace switch
- sign out

Nothing more should be present by default.

### Front Porch copy doctrine

The page should not sound like a software homepage.
It should sound like an intelligent briefing partner.

Good opening lines:

- `Tell me what you’re trying to understand.`
- `Give me a vehicle, a vendor, or a live pursuit question.`
- `Start with whatever you know. AXIOM will work from there.`

Bad opening lines:

- product category language
- feature summaries
- connector claims
- “platform” marketing language

### Front Porch conversation behavior

Front Porch is driven by dynamic questioning.

AXIOM should:

- infer object type
- narrow ambiguity
- ask one high-value question at a time
- reflect back what it has learned
- stop asking once it has enough
- explicitly take ownership

Example handoff language:

- `That’s enough to start. I’m going to work from the incumbent vehicle, current prime, and likely transition path. I’ll bring back the preliminary picture and flag any gaps I need you to close.`

### Front Porch progress experience

Progress should be subtle and linguistic.

Good:

- `Working from the incumbent and vehicle lineage…`
- `Collecting public signal and validating what holds up…`
- `Building the preliminary picture…`

Bad:

- phase names
- status dashboards
- connector counters
- pipeline widgets

### Front Porch delivery experience

The deliverable should appear like a polished artifact in or adjacent to the conversation.

The user should first see:

- a clean narrative
- the answer
- the next implication

Only after that:

- citations
- source tiers
- gaps
- confidence

Front Porch should privilege reading and understanding, not operating.

---

## 2. War Room

### Purpose

War Room is the deeper collaboration space.

It exists for:

- practitioners
- Xiphos analysts
- sophisticated client intelligence teams
- power users who need to challenge or redirect work

### What War Room feels like

- darker
- denser
- spatial
- immersive
- controlled
- serious

### What War Room is for

- challenge a finding
- inspect provenance
- redirect collection
- pull a thread
- compare hypotheses
- trace ownership or control
- see why AXIOM believes something

### What War Room is not

- a generic admin dashboard
- a chart playground
- a graph demo
- a settings-heavy control room

### War Room visual model

War Room should feel like stepping into a different room, not expanding the same screen.

The atmospheric shifts should include:

- darker palette
- tighter light sources
- more spatial depth
- stronger focal hierarchy
- modular surfaces around a central live problem

### War Room anatomy

The central object should remain the problem, not the toolset.

Preferred War Room composition:

#### Center

- primary conversation thread with AXIOM
- active finding or active line of inquiry
- dossier fragment or live briefing artifact

#### Right rail

- evidence trail
- source cards
- alerts
- gap prompts
- collection opportunities

#### Left rail or left context panel

- target summary
- mission / vehicle / vendor context
- working assumptions
- session memory

#### Optional lower or floating surfaces

- graph path view
- timeline
- alternate hypotheses
- challenge controls

The central pane is always primary.
The side panes exist to support the conversation.

### War Room conversation doctrine

AXIOM should speak differently here.

Not in tone, but in altitude.

Front Porch:

- simpler
- more guided
- more summarizing

War Room:

- more explicit
- more trail-aware
- more collaborative
- more hypothesis-driven

Example:

- `I traced the ownership chain through three Delaware LLCs and hit a wall at a Cayman entity. UCC filings suggest the lender may be the real parent. Want me to pull that thread?`

That is the target.

### War Room depth controls

War Room can expose:

- source tier badges
- provenance chains
- structured gaps
- graph path context
- confidence reasoning
- route suggestions
- challenge actions

But expose them as contextual options, not permanent dashboard clutter.

---

## Shared design language across both rooms

Front Porch and War Room should feel related.
They should not feel like separate products.

### Shared constants

- same AXIOM voice
- same typography family
- same product identity
- same narrative logic
- same dossier grammar

### Different emphases

Front Porch emphasizes:

- spaciousness
- calm
- legibility
- single input

War Room emphasizes:

- density
- evidence
- continuity
- contextual depth

### Transition rule

The transition from Front Porch to War Room should feel like:

- entering a deeper room
- not opening a new module

The same engagement should carry over:

- target context
- conversation history
- known assumptions
- open gaps
- current findings

---

## Dynamic intake model

The questioning model must stay dynamic, not deterministic.

### Principle

Ask the next question that most reduces ambiguity and changes the work plan.

### Hidden scoping dimensions

AXIOM should maintain internal state across:

- object type
- time posture
- engagement goal
- follow-on lineage
- anchor entities
- user sophistication
- confidence to proceed

This state is not exposed as a visible wizard.

### Stop rule

Once AXIOM has:

- a likely object
- a likely decision goal
- one or more anchor entities
- enough temporal context

it should move to work mode.

### Reflective compression

After several turns, AXIOM should summarize:

- what it thinks the problem is
- what it is going to work from
- what it still might need later

This is a trust move.
It shows competence without exposing machinery.

---

## Hidden plumbing model

The interface should hide the machinery, but the architecture must support it.

Behind the scenes, Helios is still doing:

- entity and vehicle resolution
- directed collection
- validation
- graph updates
- source-tier assignment
- dossier assembly
- monitoring

But those system concerns should be mapped to user-visible concepts as follows:

### Internal: resolution
### Visible: understanding the problem

### Internal: collection
### Visible: working the brief

### Internal: validation
### Visible: checking what holds up

### Internal: graph update
### Visible: building the picture

### Internal: monitoring
### Visible: keeping watch

This mapping matters.
The system can be sophisticated without sounding mechanical.

---

## Navigation architecture

Navigation should become room-based, not module-based.

### Primary model

1. Front Porch
2. War Room
3. Recent
4. Profile / workspace

### Secondary entry points

These can exist, but they should not dominate:

- dossier library
- graph intel
- alerts / watch
- admin

Those should likely live:

- inside War Room
- under Recent
- inside a workspace/account menu
- behind internal-only access

### What should disappear from the public first impression

- left rail app shell
- portfolio / overview / threads / graph / AXIOM as equal-weight nav items
- “live/offline” operational chrome at the top level
- app-style footer messaging

---

## Artifact model

Helios should use artifacts deliberately.

### Front Porch artifact model

- brief conversation
- dossier appears as a polished artifact
- user can read it cleanly
- optional expand for provenance

### War Room artifact model

- conversation remains active
- findings, trail, graph paths, and dossier fragments appear as companion artifacts
- user can challenge or redirect from the artifact context

This supports the correct feel:

- chat first
- depth second

---

## Delivery model

The answer should not look like “output.”
It should look like a professionally assembled briefing object.

### Delivery priorities

1. Answer the user’s actual question
2. summarize the picture
3. state what is known
4. state what remains unclear
5. state what likely matters next

### Optional depth

- source tiers
- citations
- contradictory evidence
- open gaps
- graph path support

The narrative must stay primary.

---

## What must not ship

### Must not ship in Front Porch

- left-side application shell
- KPI mosaics
- visible module taxonomy
- connector counts
- validation phase labels
- graph-first visuals
- explicit workflow-lane selectors
- dashboard-card mosaics

### Must not ship in War Room

- tool clutter before the conversation
- graph decoration without decision relevance
- settings-heavy surfaces
- provenance shown before the finding
- shallow chat bolted onto a dashboard

---

## Does this meet Tye’s intent?

Every design move should be tested against these questions:

1. Does this make Helios feel more like talking to a brilliant person?
2. Does this hide machinery instead of showcasing it?
3. Does this preserve a calm first impression?
4. Does AXIOM feel like it is leading intelligently?
5. Does the deeper room feel like collaboration between peers, not dashboard operation?
6. Would a BD executive understand how to start instantly?
7. Would a sophisticated practitioner feel empowered rather than constrained?

If the answer to two or more is “no,” the design move is wrong.

---

## Current implementation consequences

The current app should evolve in this order:

### Phase 1

- build Front Porch as the real default entry point
- move the existing shell behind it

### Phase 2

- define War Room as the deeper room
- subordinate graph, watch, and alerts to the conversation

### Phase 3

- convert AXIOM from a feature tab into the product’s primary interaction layer

### Phase 4

- unify dossier delivery and artifact presentation across both rooms

---

## Final rule

Helios should never feel like the user is operating intelligence software.
It should feel like the user is collaborating with intelligence.
