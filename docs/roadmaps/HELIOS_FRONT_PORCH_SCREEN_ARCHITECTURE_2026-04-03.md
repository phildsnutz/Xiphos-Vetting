# HELIOS_FRONT_PORCH_SCREEN_ARCHITECTURE_2026-04-03

## Bottom line

Front Porch is not a homepage.
Front Porch is not an app shell.
Front Porch is not a lane picker.

Front Porch is the feeling of being competently briefed by a brilliant person.

The user should arrive, type naturally, answer a few high-leverage questions, and then feel AXIOM take ownership.

If the user notices the software before they notice the intelligence, the screen has failed.

---

## Visual thesis

**Mood**: calm, private, intelligent, assured  
**Material**: one soft visual field, almost no chrome, one dominant conversation surface  
**Energy**: quiet at first contact, then subtly alive once AXIOM begins working

This room should feel like a private briefing desk with a live intelligence partner on the other side of it.

---

## Content plan

Front Porch only needs four jobs:

1. orient the user without explaining the product
2. invite a natural first utterance
3. let AXIOM clarify the problem dynamically
4. hold the handoff, progress, and returned work in one coherent thread

Everything else is secondary.

---

## Interaction thesis

Front Porch should be animated by only three things:

1. the cursor and composer feel unmistakably primary
2. AXIOM messages appear with measured conversational timing, not chat gimmicks
3. progress language changes softly in place, without turning into a visible pipeline

No spinner theater.
No phase bars.
No dashboard counters.

---

## Design principles

### 1. Conversation beats navigation

The first meaningful object on the page is the briefing surface, not product structure.

### 2. One dominant action

The dominant action is always:

- say what you are trying to understand

No other action should visually compete with that.

### 3. Hide the machinery

The user should not see:

- connectors
- graph references
- validation gates
- confidence math
- product pillar taxonomies
- collection phases

unless AXIOM decides they matter for the current interaction.

### 4. Ask only the next best question

Front Porch is not a wizard.
AXIOM asks one question at a time only when the answer would materially change the work plan.

### 5. Declare ownership explicitly

Once AXIOM has enough context, it should say so and take the lead.

---

## Screen anatomy

### A. Full-canvas room

The room fills the viewport.
It should not feel boxed, framed, or inherited from a dashboard container.

Use:

- a calm field color or soft light bloom
- one stable tonal plane behind the conversation area
- no card mosaic
- no dashboard ornament

The first viewport should read like a poster with a conversation opening in the middle of it.

### B. Minimal top bar

The top bar is present but recessive.
It should feel like a quiet room header, not app navigation.

#### Left

- Helios mark or wordmark only

#### Center

- normally empty
- optional tiny state label such as `Briefing`

#### Right

- `Recent`
- `Examples`
- `War Room`
- profile / workspace dropdown

These should be small text tabs or understated pills.
No icon salad.
No badge soup.
No feature menu.

### C. Conversation stage

The center of the screen is the stage.

It contains:

1. one opening line
2. one supporting line
3. one large composer
4. 3 to 5 example prompts
5. later, the conversation thread itself

The stage must remain visually dominant even after the thread grows.

### D. Opening copy

The opening should sound like an intelligent collaborator, not a software category page.

Recommended primary line:

`Tell me what you’re trying to understand.`

Recommended supporting line:

`A vehicle, a vendor, or a live pursuit problem. Start with whatever you know and AXIOM will work from there.`

Alternative opening lines can exist, but all of them should feel like they belong to a person, not a product.

### E. Composer

The composer is the hero object.

It should be:

- wide
- centered
- plainly styled
- unmistakably important

It should feel closer to:

- ChatGPT
- Claude
- a refined executive-messaging input

than to:

- a search box
- a form field
- a command bar

#### Composer anatomy

- one large text area
- one subtle submit control
- optional attachment or document-drop affordance if needed later
- no visible model/provider control
- no visible workflow control

#### Placeholder examples

- `ILS 2 follow-on. We think Amentum is the incumbent.`
- `Need a quick read on SMX as a potential partner.`
- `Is this vehicle vulnerable and who really matters underneath it?`

### F. Example prompts

Example prompts should appear as quiet text prompts or minimal chips under the composer.

They should feel like:

- real problems
- real operator language

Not:

- marketing use cases
- feature bullets

Recommended set:

- `Amentum on ILS 2`
- `Who matters under LEIA?`
- `Pre-solicitation follow-on with unclear incumbent team`
- `Thin-data vendor with suspicious ownership trail`

### G. Conversation thread

Once the user types, the hero collapses gently into a thread.

The thread should remain centered and spacious.
It should not suddenly snap into a cluttered app layout.

#### Thread rules

- AXIOM messages are calm and concise
- user messages are visually subordinate but clear
- each AXIOM question should feel materially useful
- the room should never look like a customer-support transcript

### H. Progress line

Progress appears as a soft status line inside the thread.

Examples:

- `Working from incumbent lineage and likely transition path.`
- `Collecting the public picture and checking for gaps.`
- `Validating what holds before I bring this back to you.`

Never show:

- connector counts
- phase steps
- graph sync notices
- validation stage names

### I. Returned artifact

The returned work should appear in-thread as a polished artifact preview.

Artifact delivery should feel like:

- AXIOM bringing back a briefing book

not:

- a report generated by software

The artifact block can show:

- title
- one-line framing
- 3 to 5 section anchors
- a `Open in War Room` or `Open dossier` action

Optional provenance cues may be present, but they must not dominate the narrative surface.

---

## Screen states

### State 1: Cold start

Visible:

- top bar
- opening line
- supporting line
- composer
- example prompts

Hidden:

- thread
- recent dossier rail
- progress state

### State 2: Clarifying exchange

Visible:

- short thread
- composer
- one AXIOM question at a time

Behavior:

- AXIOM narrows object type, timing posture, lineage, goal, or known constraints
- no more than one active question at a time

### State 3: Handoff

Visible:

- AXIOM confirmation message
- subtle work-in-progress state
- optional offer to upload supporting material

Recommended handoff pattern:

`That is enough to start. I’m going to work from the incumbent vehicle, current prime, and likely transition path. I’ll bring back the preliminary picture and flag anything I need you to close.`

### State 4: Working

Visible:

- short status language
- quiet activity

Hidden:

- internal machinery
- multi-step progress bars
- detailed source panels

### State 5: Preliminary return

Visible:

- AXIOM summary
- one focused follow-up question if needed
- artifact preview

### State 6: Final delivery

Visible:

- dossier preview
- concise framing
- optional source-tier markers
- `Open in War Room`
- `Refine this`
- `Track this`

---

## What must never appear in Front Porch

- left-side app navigation
- top-level product tabs for every subsystem
- connector counts
- database language
- graph controls
- validation-gate naming
- confidence arithmetic
- alert dashboards
- card grids
- KPI strips
- logo clouds
- “platform” marketing copy
- lane selectors
- feature matrices

If any of those appear by default, Front Porch has become software again.

---

## Recommended visual directions

These are the strongest usable directions for Front Porch.

### Direction 1: Messenger-First Front Porch

This is the purest version.

- almost the whole screen is the chat
- no hero theater
- first AXIOM prompt already present
- ideal for maximum conversational honesty

### Direction 2: Quiet Briefing Desk

This is the safest default.

- one strong line of copy
- one large input
- calm field behind it
- slightly more composed than a raw chat window

### Direction 3: Luminous Intelligence Field

This borrows from the user’s visual references.

- dark field
- one restrained glow or bloom
- conversation centered in a premium visual plane

This should be used carefully.
It works only if the visual field supports trust instead of theatrics.

---

## Motion and transitions

### On load

- wordmark and top bar settle in immediately
- conversation stage fades in softly
- no dramatic entrance

### On first send

- hero compresses into thread without snapping
- example prompts recede
- AXIOM response arrives with natural delay

### On handoff

- composer remains present
- progress language transitions in place
- no loading overlay

### On artifact return

- dossier preview rises into thread as a substantial object
- if the user opens War Room, the move should feel like entering the same case at a deeper fidelity

---

## Mobile behavior

Mobile should preserve the same emotional contract.

Rules:

- top bar reduces to wordmark plus one menu
- `War Room` remains accessible but tucked into the top-right menu
- composer stays dominant
- example prompts reduce to 2 or 3
- artifact preview is stacked and readable

Front Porch mobile should feel like texting a brilliant analyst, not using a miniature enterprise app.

---

## Accessibility and trust

Front Porch must be world-class on:

- focus order
- keyboard send behavior
- readable line length
- high contrast
- reduced motion support
- screen-reader naming of the thread and composer

Trust is not just visual.
Trust is whether the interface behaves clearly and respectfully.

---

## First 30-second journey

The ideal first 30 seconds:

1. user lands and immediately knows they should type naturally
2. user enters a messy real-world prompt
3. AXIOM asks one sharp clarifying question
4. user answers
5. AXIOM reflects back the problem in cleaner language
6. AXIOM says it has enough to proceed

At that point, the user should feel:

- this thing gets it
- I do not need to operate it
- I want to see what it brings back

---

## Implementation consequences

If this screen is implemented correctly:

- most current first-impression shell chrome disappears
- AXIOM becomes the default face of the product
- the current app navigation becomes secondary
- product capability moves behind the conversation instead of in front of it

That is not a visual tweak.
It is the correct product expression.

---

## Does this meet Tye’s intent?

This screen meets the intent only if the answer to all of these is yes:

1. Does it feel more like briefing a brilliant person than opening a software tool?
2. Is the chat surface obviously the primary object?
3. Could a new user start without understanding Helios architecture?
4. Does AXIOM ask only the next best question instead of exposing a form?
5. Is the top bar quiet enough that most users barely notice it?
6. Would the page still work if most visible UI chrome were removed?
7. Does the screen feel calmer after subtraction instead of weaker?

If any answer is no, Front Porch is not done.
