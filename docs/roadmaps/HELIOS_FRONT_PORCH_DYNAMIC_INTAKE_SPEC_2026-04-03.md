# HELIOS_FRONT_PORCH_DYNAMIC_INTAKE_SPEC_2026-04-03

## Bottom line

Helios should not open like software.
It should open like a sharp person taking a briefing.

The first experience is not:

- choose a tab
- choose a pillar
- choose a lane
- configure a workflow

The first experience is:

- say what you are trying to understand
- answer a few high-leverage questions
- let AXIOM take the lead
- receive a clean, sourced answer

The design rule is simple:

**The plumbing justifies the price. The simplicity justifies the trust.**

Everything behind the curtain exists to make the conversation feel intelligent, calm, and useful.

---

## Research anchors

This spec is grounded in a few patterns that matter:

- Apple HIG emphasizes hierarchy, content-first layout, and progressive disclosure rather than crowding important content with nonessential controls.
  - https://developer.apple.com/design/human-interface-guidelines/
  - https://developer.apple.com/design/human-interface-guidelines/layout
- Anthropic Artifacts demonstrates the right separation between a primary conversation and a dedicated companion space for substantial output.
  - https://support.claude.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them
- Linear shows the value of keeping local detail and deeper context available without forcing a full product mode-switch.
  - https://linear.app/docs/peek
  - https://linear.app/docs/search

The lesson is not to copy those products.
The lesson is:

- conversation stays primary
- deeper context gets its own room
- machinery is progressively disclosed

---

## Product truth

Helios is:

- **Vendor Assessment** as a decision surface
- **Contract Vehicle Intelligence** as a dossier and recompete surface
- **Cyber** and **Export** as supporting evidence layers
- **AXIOM** as the case-officer intelligence layer
- the **knowledge graph** as the durable provenance substrate

The user should not have to understand any of that to get value from Front Porch.

Front Porch exists to make all of that feel like:

- a smart conversation
- a competent work handoff
- a polished return product

---

## The Akinator lesson, corrected for Helios

Akinator is relevant for one reason:

- it asks the next best question

It is not relevant because Helios should become:

- deterministic
- playful
- tree-driven
- obviously “guessing”

Helios should borrow the **question-sequencing instinct**, not the game structure.

The correct model is:

**Akinator for scoping**
then
**case officer for collection**

That means AXIOM should:

- reduce ambiguity quickly
- establish the object
- infer the most decision-relevant edge
- identify the minimum viable starting context
- default to the full picture unless the user explicitly weights one edge first
- ask 0 to 2 follow-up questions max
- stop asking questions as soon as it has enough to work

AXIOM should not:

- ask every possible setup question
- expose taxonomy too early
- feel like a wizard or form
- make the user manage the process

---

## The emotional model

UI design starts from feeling, not layout.

Helios should optimize for these feelings in order:

### 1. First contact

The user should feel:

- understood quickly
- not intimidated
- not trapped in software

### 2. Clarification

The user should feel:

- guided by domain expertise
- asked only what matters
- like the system is getting smarter with each answer

### 3. Handoff to work

The user should feel:

- the problem has been competently framed
- the system is taking ownership
- they do not need to babysit it

### 4. Working period

The user should feel:

- quiet momentum
- calm confidence
- no urge to micromanage

### 5. Delivery

The user should feel:

- clarity
- authority
- trust
- optional depth, not mandatory complexity

### 6. Deep dive

The user should feel:

- invited into a sharper room
- not dropped into a technical dashboard
- still collaborating with AXIOM, just at a higher altitude

---

## Front Porch and War Room

### Front Porch

Front Porch is the public face of Helios.

It should feel like:

- ChatGPT-level accessibility
- expert interview cadence
- calm authority

It should present:

- one chat surface
- one primary input
- subtle status
- delivered output in-thread

It should hide:

- connector counts
- validation phase names
- graph jargon
- confidence arithmetic
- ingestion mechanics
- workflow lane terminology
- most product taxonomy

### War Room

War Room is not a separate product.
It is the deeper room.

It should feel like:

- two professionals working a problem
- AXIOM showing its trail when useful
- controlled depth
- collaborative collection

It can expose:

- source provenance
- structured gaps
- graph trails
- alternate hypotheses
- challenge and redirection controls
- source-tier badges
- confidence reasoning

But even here, the dominant experience is still conversation.
The tools are subordinate to the dialogue.

---

## The Front Porch conversation doctrine

### Rule 1: AXIOM starts from the user’s words

The user begins in natural language.
Do not force them into structured choices unless ambiguity is too high.

Bad:

- “Select a workflow”
- “Choose vendor or vehicle”
- “Pick a lane”

Better:

- user types naturally
- AXIOM infers the likely object
- AXIOM asks one clarifying question only when necessary

### Rule 2: Ask one high-leverage question at a time

Every AXIOM question must do real work.
If the answer would not change the collection plan, do not ask it.

### Rule 3: Questions should sound like a smart peer, not an intake form

Use natural language.
Use domain-aware phrasing.
Avoid robotic field labels.

Bad:

- “Please specify contract temporal status.”

Better:

- “Is this a current vehicle, an expired vehicle, or something still in pre-solicitation?”

### Rule 4: Reflect back what has been learned

After 2 to 4 answers, AXIOM should compress the current picture in plain language.

Example:

- “Good. This sounds like a pre-solicitation follow-on to ILS with Amentum as the incumbent prime. That’s enough to start working from the vehicle lineage and likely transition path.”

This creates trust.
It proves the system is listening.

### Rule 5: Stop asking as soon as enough context exists

Once AXIOM has the minimum viable context, it should take ownership.

Example:

- “That’s enough to start. I’m going to work this and I’ll flag any gaps I need you to close.”

### Rule 6: The user should never feel like they are operating a backend

AXIOM should not narrate:

- connectors
- validation stages
- graph sync
- source routing
- tool names

It may narrate:

- what it is trying to understand
- what it is checking
- why it needs one more answer

### Rule 7: AXIOM should make intelligent assumptions, then verify

When the user gives partial information, AXIOM should infer carefully and ask for confirmation only when that confirmation changes the plan.

### Rule 8: Ambiguity is a collaboration moment, not an error state

If the user says something fuzzy like `ILS 2`, AXIOM should treat that as a promising lead and narrow it.

Not:

- “I don’t understand”

But:

- “Are we looking at a current vehicle, an expired vehicle, or something still in pre-solicitation?”

---

## Dynamic question-selection model

This is not a deterministic Akinator tree.
It is a dynamic questioning model driven by expected scoping value.

### Core principle

Ask the next question that most reduces ambiguity **and** materially changes the work plan.

### Hidden scoping dimensions

AXIOM should keep an internal hypothesis map, not a visible form.

Important hidden dimensions include:

- `object_type`
  - vendor
  - contract_vehicle
  - mixed / uncertain
- `temporal_posture`
  - current
  - expired
  - pre_solicitation
  - recompete
  - unknown
- `engagement_goal`
  - vendor_assessment
  - vehicle_dossier
  - vulnerability_analysis
  - teammate_assessment
  - teammate_fit
  - unknown
- `lineage_state`
  - follow_on
  - net_new
  - unknown
- `known_anchor_entities`
  - incumbent prime
  - target vendor
  - agency
  - installation
  - contract family
- `user_sophistication`
  - exec / bd
  - practitioner
  - analyst
- `confidence_to_proceed`
  - low
  - medium
  - sufficient

### Question selection heuristic

For each turn, AXIOM should choose among candidate questions using these filters:

1. Will the answer materially change collection scope?
2. Will the answer collapse multiple hypotheses at once?
3. Can the question be asked in plain language?
4. Is this the minimum necessary next question?
5. Does the user already imply the answer?

The best question is the one with the highest combined score on those dimensions.

### Natural language question families

These are not rigid scripts.
They are reusable conversational moves.

#### Object disambiguation

- “Are we looking at a contract vehicle or a specific vendor?”
- “Is the target the vehicle itself, the incumbent, or a teammate you’re evaluating?”

#### Time posture

- “Is this current, expired, or still in pre-solicitation?”
- “Are you working something live right now, or trying to reconstruct what happened?”

#### Lineage

- “Is this a follow-on or something net-new?”
- “Do you know the incumbent vehicle or current prime?”

#### Goal clarification

- “If there’s one edge you want me to weight first, tell me now. Otherwise I’ll work the full picture.”
- “What is the one thing most likely to change the call if it breaks the wrong way?”

#### Evidence anchors

- “Do you know the current prime?”
- “Do you know the installation, customer, or likely mission set?”

#### Escalation

- “That’s enough to start. I’ll work from the incumbent and transition path.”
- “I can start now, but one thing would sharpen this materially: do you know the current subcontractor base?”

### Stop conditions

AXIOM stops asking questions when:

- it can define the object
- it understands the user’s goal
- it has at least one anchor entity
- it has enough temporal context to choose a collection posture

At that point it should move to work mode.

---

## Minimum hidden state model

The user should not see these states explicitly, but the system needs them.

### 1. Listening

- user prompt arrives
- AXIOM extracts candidate entities, goals, and ambiguities

### 2. Scoping

- AXIOM asks clarifying questions
- hypothesis map narrows

### 3. Ready to work

- scoping confidence reaches threshold
- AXIOM declares handoff to active work

### 4. Working quietly

- collection
- validation
- graph update
- dossier assembly

### 5. Needs input

- AXIOM hits a meaningful ambiguity
- surfaces one focused question

### 6. Delivery ready

- preliminary or final output is ready
- surfaced cleanly in thread

### 7. War Room available

- if the user wants to challenge, redirect, or go deeper
- open a deeper conversational room, not a tool dump

---

## Front Porch UX spec

### Landing experience

The landing page is a conversation surface.

Visible elements:

- Helios mark
- one short orientation line
- one large chat input
- perhaps 2 to 4 soft example prompts

Nothing else should compete.

No visible:

- product tabs
- connector references
- graph marketing
- KPI cards
- explicit lane chooser
- giant left navigation

### Opening copy

The page should not sound like marketing.
It should sound like a capable briefing partner.

Good:

- “Tell me what you’re trying to understand.”
- “Give me a vendor, vehicle, or problem, and I’ll work it.”

Bad:

- “The intelligence platform for vendor assurance and contract vehicle intelligence”

That sentence may be true.
It is not the right opening feeling.

### Conversation flow

The first 5 to 10 exchanges should aim to:

- identify object type
- establish time posture
- establish the actual decision the user is trying to make
- establish at least one anchor entity

Then AXIOM should explicitly take ownership.

### Progress experience

The status surface should be subtle and linguistic.

Good examples:

- “Working from the incumbent and vehicle lineage…”
- “Collecting public signal and validating what holds up…”
- “Building the preliminary picture…”

Bad examples:

- phase labels
- numbered pipeline steps
- connector counters
- status dashboards

### Delivery experience

The dossier should appear as:

- a polished in-thread artifact
- with optional provenance affordances
- readable without technical context

Visible depth for sophisticated users:

- source tier badges
- citations
- gap markers
- confidence labels where decision-relevant

But the narrative must remain primary.

### War Room transition

The deeper room should be introduced explicitly.

Example:

- “I have the preliminary picture. If you want, we can open the War Room and pull on the ownership chain, challenge the confidence, or redirect collection.”

The user should feel like they are entering a more serious conversation, not opening a settings panel.

---

## War Room UX spec

War Room is still primarily a conversation surface.

Visible elements may include:

- main chat stream
- dossier or evidence companion pane
- provenance trail pane
- graph inspector
- targeted source / gap cards

But the order matters:

1. conversation
2. finding
3. evidence trail
4. optional tools

Not:

1. tools
2. controls
3. graph
4. buried conversation

### War Room language

AXIOM should speak at a different altitude here.

Example:

- “I traced the ownership chain through three Delaware LLCs and hit a wall at a Cayman entity. UCC filings suggest the lender may be the real parent. Want me to pull that thread?”

That is the model.

War Room is:

- peer collaboration
- trail exposure
- focused choice

Not:

- dashboard administration

---

## Canonical Front Porch patterns

### Pattern 1: Vehicle-first, ambiguous label

User:

- `ILS 2`

AXIOM:

- `Are we looking at a current vehicle, an expired vehicle, or something still in pre-solicitation?`

User:

- `Pre-solicitation`

AXIOM:

- `Good. Is this a follow-on or something net-new?`

User:

- `Follow-on`

AXIOM:

- `Do you know the current prime?`

User:

- `Amentum`

AXIOM:

- `That’s enough to start. I’m going to work from the incumbent vehicle, current prime, and likely transition path. I’ll bring back the preliminary picture and flag any gaps I need you to close.`

### Pattern 2: Vendor-first, intent unclear

User:

- `SMX`

AXIOM:

- `Are you trying to vet SMX directly, or are you asking because they sit on a vehicle or team you care about?`

### Pattern 3: Teammate evaluation

User:

- `Can Dyncorp still get inside this?`

AXIOM:

- `Which vehicle are we talking about? If there’s one edge you want weighted first, tell me now. Otherwise I’ll work the full picture.`

### Pattern 4: Recompete vulnerability

User:

- `Is Amentum vulnerable on this follow-on?`

AXIOM:

- `Which follow-on, and do you know whether this is still current performance or already in pre-solicitation?`

---

## What must not ship

The following should not appear in Front Porch:

- left-rail app shell as the primary experience
- visible product tabs
- connector counts
- source routing controls
- graph as hero object
- explicit pipeline phase names
- lane taxonomy
- validation gate jargon
- dashboard-card mosaics

The following should not dominate War Room:

- giant control surfaces
- settings-heavy interaction
- graph decoration with weak narrative value
- provenance presented before the finding itself

---

## Design consequences for the current app

The current app structure is still too software-forward.

That means the redesign should move toward:

### Phase A

- Replace the current top-level multi-tab default with a chat-first Front Porch
- Move existing app surfaces behind a deeper navigation layer

### Phase B

- Introduce a War Room as a second conversational room with contextual inspectors
- Relegate graph, watchlist, and alert mechanics to contextual panels

### Phase C

- Reframe AXIOM from a feature tab into the voice and orchestration layer of the product

---

## Final rule

If a UI element makes Helios feel more like software and less like briefing with a brilliant person, it should not ship.
