# HELIOS_VISUAL_DOCTRINE_2026-04-03

## Bottom line

Helios should feel like **Linear wearing an Apple suit, with Stripe-grade operational honesty**.

That means:

- **Linear** for operator speed, keyboard reachability, preserved context, and fast pivots
- **Apple** for restraint, hierarchy, whitespace, and chrome that recedes
- **Stripe** for explicit status, progressive disclosure, and trust through clarity

The goal is not "pretty."
The goal is an interface that disappears and leaves the analyst fully inside the work.

## Product truth

Helios is not a generic compliance dashboard.

Helios is:

- **Vendor Assessment** as the primary decision loop
- **Contract Vehicle Intelligence** as the dossier and ecosystem loop
- **Cyber** and **Export** as supporting evidence layers, not co-equal product pillars
- **AXIOM** as the lawful-edge case-officer layer for gap closure, watchlists, alerts, and collection follow-on
- the **knowledge graph** as the provenance-backed substrate for memory, contradiction, and navigation

UI decisions must reinforce that model.

Anything that makes Helios feel like a six-tab SaaS toy or a mosaic of dashboards is wrong.

## Research synthesis

### Apple

The lesson is not visual minimalism for its own sake.
The lesson is that structure should come from spacing, typography, and spatial continuity before borders, badges, or ornament.

Helios implication:

- make the working surface the primary object
- reduce header and card noise
- use motion only to preserve place and reveal relationships

### Stripe

Stripe's strongest pattern is explicit, scalable clarity:

- separate screens for additional context instead of cramming everything inline
- clear primary actions
- explicit empty, loading, and state communication
- strong tokenized styling discipline

Helios implication:

- error, loading, status, and provenance surfaces must be standardized
- evidence and metadata should be revealed intentionally, not dumped inline
- every state must explain what is happening and what to do next

### Linear

Linear treats speed as a product feature:

- sidebar as spatial memory
- keyboard-first navigation
- search everywhere
- view-local search and workspace-global search are distinct
- operators stay in context while switching altitude

Helios implication:

- preserve context while moving between queue, case, graph, and AXIOM
- use split views and inspectors instead of hard screen swaps
- implement one global command layer and one local search layer per heavy surface

### Vercel

Vercel earns trust by making runtime truth legible:

- deployment details expose logs, resources, build time, framework, and errors
- overview pages show latest production state and debugging context clearly

Helios implication:

- collection, enrichment, validation, and graph status must be explicit
- AXIOM cannot pretend success
- source freshness, gaps, and failure modes should be easy to inspect

### Arc

Arc's key lesson is contextual separation with low cognitive reset:

- spaces preserve task context
- the sidebar is not clutter, it is memory
- switching context should feel like moving rooms, not relaunching an app

Helios implication:

- Workbench, AXIOM, Graph Intel, and case detail should feel like related workspaces
- moving between them should preserve selection, filters, and source context whenever possible

### Internal audit truth

The existing internal UI audit was directionally right:

- current component sprawl is too high
- information hierarchy is weak
- the interface wastes analyst time with avoidable navigation drag
- visual and semantic systems are insufficiently disciplined

Helios should absorb that audit, not argue with it.

## The Helios UI laws

### 1. Workspace first, chrome second

Every screen needs one primary workspace.

- Workbench: queue
- Intake: scoping sheet
- Case detail: split decision and evidence workspace
- AXIOM: case-officer desk
- Graph Intel: investigation canvas

If chrome or summary cards draw more attention than the workspace, the screen fails.

### 2. One dominant idea per screen

Each surface gets one job.

- Workbench moves cases
- Intake scopes a mission
- Case detail decides
- AXIOM closes gaps
- Graph Intel explores relationships

Secondary context belongs in drawers, inspectors, or collapsible sections.

### 3. No dashboard-card mosaics

Helios should not look like stacked KPI cards and hero panels.

Use cards only when the card is the interaction.
If plain layout and spacing can do the job, remove the card.

### 4. Status must be explicit

Collection, enrichment, validation, dossier generation, and graph sync are core operator truths.

Never hide them.
Never imply success without evidence.
Never make the user check the console or guess what happened.

### 5. Progressive disclosure beats equal-weight clutter

Evidence, provenance, supporting layers, and advanced controls are important.
They are not all equally urgent at first glance.

Default to:

- visible task
- visible state
- visible next action
- deeper detail one intentional step away

### 6. Preserve context

Selection, filters, origin screen, and related evidence should survive navigation.

Opening Graph Intel from a case should feel like zooming into the same problem, not teleporting into a new app.

### 7. Use color semantically, not decoratively

Color exists for:

- status
- priority
- focus
- data hierarchy

Not for mood gradients, decorative accents, or gratuitous surface variation.

### 8. AXIOM is special

AXIOM should not look like a generic search tab.

It should feel like:

- an intelligence desk
- a gap-closure workspace
- a collection planning surface
- a watch and drift surface

AXIOM should foreground:

- what is unknown
- what is weakly inferred
- what can be collected next
- what has changed

not generic search chrome.

### 9. The graph is evidence memory, not decoration

Graph Intel should not lead with "cool graph."

It should lead with:

- why this node matters
- what changed
- what path is decision-relevant
- what evidence supports the path

The graph earns its right to exist through explanation and navigation, not by motion alone.

## Surface doctrine

### Front Porch

Front Porch is the calm entry layer.

It should feel:

- quiet
- object-first
- obvious

The user should choose:

- vendor assessment
- contract vehicle intelligence

and then immediately act.

Front Porch rules:

- no dashboard hero language
- no parallel equal-weight action soup
- one primary input
- one primary action
- supporting layers presented as scope controls, not product pillars

### Workbench

Workbench is a queue, not a marketing surface.

Workbench rules:

- top priority item visible immediately
- compact summary strip instead of hero sprawl
- queue before metrics
- metrics small and useful
- actions sparse and obvious

### Intake

Intake is mission scoping, not a landing page.

Intake rules:

- resolve the object first
- hide optional logic until needed
- show only the primary path above the fold
- supporting evidence and lane nuance should clarify, not compete

### Case detail

Case detail is the primary operator workspace.

Case detail rules:

- use split view by default
- decision and posture on one side
- evidence, enrichment, monitoring, and provenance on the other
- keep scroll local where possible
- the next decision should always be visible

### AXIOM

AXIOM should present a running intelligence problem, not a tabbed utility.

AXIOM rules:

- current gap load visible
- search framed as collection hypothesis, not generic query
- watchlist framed as active collection
- alerts framed as drift against prior truth
- provenance and validation outcomes visible

### Graph Intel

Graph Intel is an investigation canvas.

Graph rules:

- search must be fast and local
- selection must drive explanation
- analytics are secondary to pathfinding and relevance
- sidebars should explain what a node or path means in decision terms

## Visual system rules

### Typography

Keep the current 6-size discipline:

- 12
- 14
- 16
- 18
- 24
- 32

Usage:

- 32 only for top-level surface titles
- 24 for section or workspace title
- 18 for subheads and sectional pivots
- 14 for primary body text
- 12 for metadata, timestamps, and tertiary labels

No extra "marketing" sizes.

### Color

One accent.
One neutral system.
Semantic status colors only.

Status mapping must be stable:

- blocked: red
- review: amber
- watch: orange
- approved or qualified: green or qualified blue only where the distinction matters

Do not create screen-specific palette drift.

### Spacing

Use the existing base scale consistently:

- 4
- 8
- 12
- 16
- 24
- 32
- 48

The visual feel of premium product UI comes more from disciplined spacing than from effects.

### Surfaces

Default to plain layout.
Use cards sparingly.
Limit elevated surfaces to places where:

- the user acts inside the box
- grouping materially aids scanning
- the section is detachable in the mental model

### Motion

Use motion only for:

- panel entrance
- split-view and inspector presence
- state transition clarity
- graph focus and path emphasis

Remove ornamental motion.

## Interaction grammar

### Opening things

- modal: destructive or blocking confirmation only
- drawer or inspector: secondary detail, source evidence, node detail, alert history
- inline expansion: rationale, advanced options, supporting detail
- full navigation: only when switching primary workspace

### Loading

- skeleton for page and panel loads
- inline loading for small scoped operations
- never spinner-only for long-running analyst operations without status text

### Failure

- inline message for local failure
- banner for system-wide failure
- never silent failure
- never pretend success

### Search

- one global command layer
- one local search layer on graph, queue, and AXIOM
- local search should never replace global navigation

### Keyboard

Default operator grammar:

- `Cmd+K` global command
- `/` or `Cmd+F` local search
- `j/k` next and previous in queues and lists
- `Enter` open
- `Esc` close or step back
- `?` keyboard help

## Anti-patterns to forbid

- dashboard-card mosaics
- thick borders around every region
- decorative gradients behind normal product work
- more than one accent color
- equal-weight tabs for supporting evidence layers
- hidden loading and failure states
- hero copy on operator screens
- cool graph motion without decision explanation
- AXIOM framed as a generic search box

## Repo truth and immediate implications

Current repo surfaces already point in the right direction:

- shell: `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend/src/App.tsx`
- workbench: `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend/src/components/xiphos/portfolio-screen.tsx`
- intake: `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend/src/components/xiphos/helios-landing.tsx`
- case detail: `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend/src/components/xiphos/case-detail.tsx`
- AXIOM: `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend/src/components/xiphos/axiom-dashboard.tsx`
- graph: `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend/src/components/xiphos/graph-intelligence-dashboard.tsx`
- shared shell primitives: `/Users/tyegonzalez/Desktop/Helios-Package Merged/frontend/src/components/xiphos/shell-primitives.tsx`

But the current UI still drifts in these ways:

- too many elevated surfaces
- too much card treatment
- too much equal-weight summary content above the fold
- not enough split-workspace thinking
- insufficient distinction between global navigation and local search
- AXIOM and Graph still feel adjacent to the app instead of native to the operator loop

## Next UI tranche

### Priority order

1. Shell and navigation simplification
2. Workbench de-card and queue-first pass
3. Intake mission-scoping pass
4. Case-detail split-workspace pass
5. AXIOM case-officer workspace redesign
6. Graph Intel explanation-first pass

### Concrete build rules for the next tranche

- reduce visible surfaces before adding any new component
- replace hero or summary blocks with layout and whitespace where possible
- move secondary context into drawers or inspectors
- standardize status, loading, and error treatments before visual polish
- preserve existing functionality and evidence access

## Deferred on purpose

Do not build these into the next UI tranche:

- separate Alpha and Omega graphs
- marketplace or partner-economics UI
- speculative tier packaging UI
- decorative redesign without workflow improvement

## Sources

- Apple Human Interface Guidelines, Layout: https://developer.apple.com/design/human-interface-guidelines/layout
- Stripe Apps patterns: https://docs.stripe.com/stripe-apps/patterns
- Stripe Apps style: https://docs.stripe.com/stripe-apps/style
- Stripe Apps loading pattern: https://docs.stripe.com/stripe-apps/patterns/loading.md
- Linear Docs, Search: https://linear.app/docs/search
- Linear Docs, Project overview: https://linear.app/docs/project-overview
- Arc Help, Spaces: https://resources.arc.net/hc/en-us/articles/19228064149143-Spaces-Distinct-Browsing-Areas
- Vercel Docs, Deployments: https://vercel.com/docs/deployments
- Vercel Docs, Observability: https://vercel.com/docs/observability
- Existing internal audit: `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/Helios_UIUX_Audit_20260402.docx`

