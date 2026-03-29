# Claude Handoff: Sprint 1 UI Redesign

## Metadata

- Date: 2026-03-20
- From agent: Claude
- To agent: Codex
- Workspace: `/Users/tyegonzalez/Desktop/Helios-Package Merged`
- Scope: Sprint 1 of UI redesign (Tickets 1-3: navigation collapse, portfolio screen, Helios home)
- Status: Deployed to production, needs hardening pass

## Objective

Implemented Tickets 1-3 from the HELIOS_UI_IMPLEMENTATION_TICKETS.md spec: collapsed the 8-tab navigation to 3 tabs (Helios/Portfolio/Admin), built a unified Portfolio screen replacing Dashboard+Executive, and rebuilt the Helios home as a focused command surface.

## What Changed

- Collapsed Tab type from 8 values to 3: `"helios" | "portfolio" | "admin"`
- Removed imports for BatchImport, ProfileCompare, DemoCompare, OnboardingWizard, ExecDashboard, ConnectorHealth from App.tsx
- Built new PortfolioScreen component replacing both DashboardScreen and ExecDashboard
- Rebuilt Helios home idle phase: removed workflow cards, removed search mode toggle, changed heading to "What do you want to assess?", moved vehicle search to text link, added Recent Work list, added compact portfolio status line
- Login/setup screen was intentionally OUT OF SCOPE for Sprint 1 (Ticket 8)

## Files Changed

- `frontend/src/App.tsx`: Navigation collapsed to 3 tabs. Removed 6 component imports. Simplified content rendering. Fixed `setTab("screen")` -> `setTab("helios")`. Fixed `tab === "dashboard"` -> `tab === "portfolio"`. Removed onboarding state.
- `frontend/src/components/xiphos/portfolio-screen.tsx`: NEW FILE (255 lines). Priority queue, tier distribution bar, sortable vendor list. Reuses CaseRow.
- `frontend/src/components/xiphos/helios-landing.tsx`: Removed pillars array and workflow cards. Changed heading. Removed search mode toggle. Added Recent Work section. Added portfolio status line. Prefixed unused props with underscore for strict TS.

## API And Contract Changes

- No backend changes in Sprint 1.
- HeliosLanding now accepts `cases: VettingCase[]` prop for Recent Work display.
- PortfolioScreen accepts `cases`, `alerts`, `onSelect` props.

## Env Vars And Runtime Assumptions

- No new env vars.
- The strict TypeScript config (`noUnusedLocals: true`, `noUnusedParameters: true` in `tsconfig.app.json`) caused multiple build failures. Every unused import and variable is a hard error. Prefix unused params with underscore (e.g., `_caseCount`) to suppress.

## Data, ML, And Migrations

- No changes.

## Verification

- `npm run build` passed on the production server after fixing unused variable warnings.
- Frontend bundle deployed and Docker container restarted.
- Login works (verified via API).
- Post-login UI shows 3-tab navigation.

## Not Verified

- `npm run lint` was not run. CODEX should verify lint-clean.
- No screenshots captured of the new UI (browser automation unavailable in this environment).
- Login/setup screen still shows old branding (intentionally out of scope for Sprint 1).
- Old DashboardScreen and ExecDashboard files still exist on disk (not deleted yet, Ticket 12).

## Known Risks And Sharp Edges

- The TS strict mode caused repeated build failures during development. Every sed edit on the server introduced new issues. The local-edit-then-upload pattern is the only reliable approach.
- The `searchMode` state was partially removed then re-added. The vehicle search link now calls `handleVehicleSearch()` directly instead of setting a mode, but the `searchMode` state still exists for the reset function. CODEX should verify this is clean.
- `PortfolioScreen` receives `alerts` prop but doesn't use it yet (prefixed as `_alerts`). Sprint 2 should wire alerts into the priority queue.
- Old DashboardScreen, ExecDashboard, and ConnectorHealth components are still on disk. They're not imported by App.tsx but should be deleted in Ticket 12.
- The batch CTA in vehicle results still says "Assess All" instead of "Create Draft Cases" (Ticket 11).

## Demo Credentials

- URL: [internal demo host redacted]
- Admin: stored in secure local ops notes, not in repo docs
- Partner: stored in secure local ops notes, not in repo docs

After login to the internal demo environment, the new 3-tab shell should be visible: Helios (default), Portfolio, Admin.

## Questions For The Next Agent

- Verify `npm run lint` passes. I expect unused import warnings may remain in files I didn't touch.
- Check whether the PortfolioScreen priority queue logic correctly identifies TIER_1 and TIER_2 cases.
- Check whether the "Or search by contract vehicle" link works correctly (calls handleVehicleSearch directly).
- Verify the old DashboardScreen/ExecDashboard aren't accidentally still reachable through any code path.
- The login screen (Ticket 8) still shows old branding. Should this be prioritized before Sprint 2?

## Recommended Next Actions

1. Run lint and build clean, fix any remaining issues.
2. Verify the new UI against the spec wireframes.
3. Delete dead component files (DashboardScreen, ExecDashboard, ConnectorHealth).
4. Start Sprint 2: Tickets 4-7 (entity resolution tightening, confirm simplification, case detail rebuild, evidence tabs).
