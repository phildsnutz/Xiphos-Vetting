# HELIOS_TOP_BAR_AND_ARTIFACT_COMPONENT_SPEC_2026-04-03

## Bottom line

The top bar and artifact block are the two shared UI objects most likely to destroy the product feel if they drift.

The top bar controls whether Helios feels like:

- a room
- or an application

The artifact block controls whether AXIOM feels like:

- a brilliant partner returning a clean work product
- or software dumping output

These components need hard rules.

---

## Shared principle

Both components must answer the same question:

**Does this increase the feeling of trust, clarity, and intelligent collaboration without exposing machinery?**

If not, it should be removed.

---

## Component 1: Front Porch top bar

### Purpose

Orient the user lightly and provide only the smallest necessary escape hatches.

### Required items

#### Left

- Helios wordmark

#### Right

- `Recent`
- `Examples`
- `War Room`
- profile / workspace menu

### Forbidden items

- full product navigation
- subsystem tabs
- KPI badges
- alert counters
- connector counts
- graph references
- visible settings clutter

### Behavior

#### Recent

Opens a small anchored menu with:

- recent engagements
- saved dossiers
- last viewed cases

Selecting an item should open the relevant engagement immediately.

#### Examples

Opens a small anchored menu with:

- example opening prompts
- no explanation walls
- one tap to drop the prompt into the composer

#### War Room

Moves the user into the deeper room.
It should feel like changing rooms, not changing products.

### Visual rules

- recessive
- low contrast compared with the conversation stage
- small type
- minimal separators
- no icon soup

---

## Component 2: War Room top bar

### Purpose

Keep the user oriented inside the same engagement while exposing only a few room-level moves.

### Required items

#### Left

- Helios mark
- current engagement title
- tiny room marker such as `War Room`

#### Right

- `Front Porch`
- `Recent`
- share / export
- profile / workspace menu

### Forbidden items

- giant feature nav
- admin links
- dense toolbar controls
- graph toggles presented as primary identity

### Behavior

The bar should support:

- returning to Front Porch
- moving among recent engagements
- sharing or exporting the current artifact

It should not become the place where the user operates the room.

---

## Component 3: Artifact block

### Purpose

Represent a returned work product in a way that feels authored, structured, and trustworthy.

The artifact block is the moment where AXIOM says:

- here is what I worked
- here is what holds
- here is how to go deeper if you want to

### Core anatomy

1. title
2. one-sentence framing
3. 3 to 5 section anchors
4. optional provenance cues
5. primary action
6. secondary action

### Front Porch artifact behavior

Front Porch artifacts should feel:

- polished
- calm
- editorial

Visible by default:

- artifact title
- concise framing sentence
- key sections
- `Open dossier`
- `Open in War Room`

Optional but quiet:

- source tier hints
- freshness note

Not visible by default:

- graph structure
- raw claim lists
- connector provenance
- detailed confidence scaffolding

### War Room artifact behavior

War Room artifacts should feel:

- working
- challengeable
- inspectable

Visible:

- artifact title
- claim blocks
- source trail access
- challenge action
- redirect action
- graph / evidence pivots

But even here, the artifact should remain readable as a document, not explode into a control panel.

---

## Artifact states

### State 1: Preliminary picture

The block says:

- this is the early read
- these are the strongest holds
- these gaps remain open

### State 2: Working artifact

The block says:

- this is still being shaped
- here is what is under challenge
- here is what AXIOM wants to pull next

### State 3: Delivered dossier

The block says:

- this is coherent enough to act on
- depth is available but not mandatory

---

## Interaction rules

### Open dossier

Opens the polished narrative view.
This is the default move for non-practitioner users.

### Open in War Room

Moves from calm delivery into deeper collaboration.
This should never feel like escalating into a technical product mode.

### Challenge

War Room only.
Challenge should attach to a claim or framing line, not to the artifact as an abstract object.

### Refine

Available in both rooms.
This is the natural-language way to ask AXIOM to keep working.

---

## Visual rules

### Artifact block should feel like

- a briefing object
- a dossier excerpt
- something with editorial gravity

### Artifact block should not feel like

- a card in a dashboard grid
- a software result tile
- a debug summary

### Surface rules

- strong internal spacing
- light borders if any
- tonal separation from the room
- typography first
- icons only when they improve scanning

---

## Anti-patterns

Do not ship:

- top bars with five or more equal-weight items
- icon-heavy control clusters
- artifact cards with many little badges
- provenance dominating the artifact
- export/share/download clusters before the narrative
- graph controls embedded into the artifact header

---

## Does this meet Tye’s intent?

This component pair meets the intent only if the answer to all of these is yes:

1. Does the top bar feel like a room header instead of product navigation?
2. Is `War Room` an invitation into deeper collaboration rather than a feature tab?
3. Does the artifact feel authored and trustworthy before it feels interactive?
4. Can a user understand the returned work without seeing the machinery?
5. If the component lost half its visible chrome, would it feel better rather than weaker?

If any answer is no, this component contract is not being followed.
