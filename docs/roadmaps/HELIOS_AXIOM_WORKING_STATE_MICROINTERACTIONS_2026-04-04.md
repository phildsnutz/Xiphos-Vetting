# HELIOS_AXIOM_WORKING_STATE_MICROINTERACTIONS_2026-04-04

## Bottom line

Do **not** build a literal waiting game for dossier rendering.

The dossier itself is fast.
The real wait, when it exists, is AXIOM collection, enrichment, validation, and synthesis.

So if Helios gets a playful or quirky waiting-state interaction, it should:

- appear only while AXIOM is actively working
- feel like tradecraft, not entertainment
- never cheapen trust
- always remain optional
- help the user feel that intelligence work is happening, not that the product is stalling

The design rule is:

**The user should feel invited into the work, not distracted from the wait.**

---

## What this interaction is for

### Good use

- absorb 8 to 45 seconds of real working time
- make the room feel alive without exposing machinery
- reinforce how AXIOM thinks about evidence, ambiguity, and pressure points
- give the user one small, meaningful way to shape emphasis

### Bad use

- arcade minigames
- puzzle games unrelated to the mission
- visible connector or phase machinery
- anything that competes with the conversation
- anything that feels childish, gamified, or cute

---

## Trigger rules

Only show a working-state microinteraction when all of these are true:

1. AXIOM has already said `That is enough to start` or equivalent.
2. The room is in an actual working state.
3. Estimated or observed work time is greater than roughly `8s`.
4. The interaction can be dismissed instantly.
5. The conversation and returned brief remain primary.

Never show it:

- before intake confidence is good enough to start
- during the first 2 to 5 seconds of work
- when AXIOM is waiting on the user
- after the returned brief is ready

---

## Design constraints

- One small surface only.
- No full-screen takeover.
- No scoreboards.
- No bright celebratory motion.
- No fake progress theater.
- No mandatory participation.
- No exposed phase names like `connector pass`, `validation gate`, or `graph promotion`.

The user should always be free to:

- keep reading the status line
- continue the conversation
- ignore the interaction completely

---

## Concept 1: Signal Sort

### Feeling

- sharp
- tactile
- analyst-like
- slightly playful without being unserious

### Interaction

AXIOM surfaces 3 to 5 short signal fragments as floating cards.
The user can flick or tap them into one of three buckets:

- `Holds`
- `Thin`
- `Noise`

Example signals:

- `Incumbent named in follow-on chatter`
- `Subcontractor trace from archived teaming page`
- `Ownership path breaks at a Cayman entity`
- `Hiring burst near the program office`

### Why it fits

- this is already how Helios should think
- it teaches the user the product’s intelligence posture without saying so
- it feels like tradecraft, not gaming

### Risk

- if the signals are generic or obviously fake, it becomes corny fast
- if users think their answers affect truth rather than emphasis, trust can drop

### Build complexity

- low to medium

### Best use

- Front Porch waiting state
- optional only

---

## Concept 2: Thread Pull

### Feeling

- cinematic
- investigative
- slightly more premium and spatial

### Interaction

AXIOM shows one ambiguous thread, such as:

- ownership chain
- teammate network
- incumbent continuity
- export exposure

The user can pull one thread card outward to reveal two or three likely next paths.

Example:

- `Ownership wall`
  - `Follow the lien holder`
  - `Map officer overlap`
  - `Check offshore registration residue`

### Why it fits

- visually aligns with War Room
- reinforces that AXIOM is working a structure, not a static report
- can feel sophisticated if motion is restrained

### Risk

- more panel-like if overbuilt
- easier to drift into graph-demo energy
- harder to make useful in Front Porch

### Build complexity

- medium

### Best use

- War Room
- not ideal for first Front Porch implementation

---

## Concept 3: Pressure One Thread

### Feeling

- most conversational
- most aligned to `briefing a brilliant person`
- least game-like

### Interaction

AXIOM offers one optional prompt while it works:

`While I work the full picture, is there one thread you want me to weight first?`

Then it shows 2 to 4 short chips such as:

- `Ownership`
- `Incumbent continuity`
- `Teammate network`
- `Adverse history`

The user can tap one or ignore all of them.

If tapped, AXIOM responds with a short acknowledgment:

`Understood. I’ll weight ownership first while I work the full picture.`

### Why it fits

- stays closest to the product’s conversational promise
- does not feel like a toy
- gives the user agency without burden
- can operate in both Front Porch and War Room

### Risk

- less quirky than the other concepts
- if overused, it just becomes another form question

### Build complexity

- low

### Best use

- first shipping version
- especially Front Porch

---

## Recommendation

### Recommended first build

**Ship Concept 3 first: Pressure One Thread**

Why:

- lowest risk to trust
- easiest to explain
- most aligned to AXIOM as case officer
- easiest to remove if it feels wrong
- naturally compatible with the `0 to 2 follow-up questions max` intake doctrine

### Recommended second build

If Concept 3 feels too dry, add a lightweight version of **Concept 1: Signal Sort** inside War Room only.

That gives you:

- Front Porch: conversational authority
- War Room: optional tradecraft play

### Do not build first

Do **not** build Thread Pull first.

It is attractive, but it is easier to overdesign and slide back into dashboard theater.

---

## Suggested product behavior

### Front Porch

- AXIOM takes the brief
- AXIOM goes to work
- if work time crosses threshold, show:
  - subtle status line
  - optional `Pressure one thread` microinteraction

### War Room

- AXIOM takes the thread
- if the user is waiting on collection or drift evaluation, show:
  - working-state status
  - optional `Pressure one thread`
  - later, maybe `Signal Sort`

---

## Suggested copy

### Front Porch

- `While I work the full picture, is there one thread you want me to weight first?`
- `You can skip this. I’m already working the full picture.`

### War Room

- `I’m working the full thread. If you want, give me the one edge to weight first.`
- `No input needed. I’ll keep going unless you redirect me.`

---

## Analytics and guardrails

Measure:

- interaction rate
- skip rate
- time to first returned brief
- whether users who engage feel more confident or less
- whether the interaction increases abandonment

Kill it if:

- users ignore it almost entirely
- users read it as busywork
- it makes the room feel less calm
- it adds visible latency or UI noise

---

## Practical implementation sequence

1. Add a working-state slot below the status line and above the composer.
2. Implement `Pressure One Thread` as optional chips with no hard dependency.
3. Gate it behind a time threshold.
4. Track interaction and skip behavior.
5. Only after that, consider a War Room-only `Signal Sort` prototype.

---

## Hard call

If Helios wants something quirky and cool during wait states, it should be:

- **brief**
- **optional**
- **tradecraft-flavored**
- **subordinate to the conversation**

The safest first move is not a game.

It is a **case-officer microinteraction** that lets the user gently steer emphasis while AXIOM works the full picture.
