# Helios Scope Manifest

Date: 2026-03-29
Workspace: `/Users/tyegonzalez/Desktop/Helios-Package Merged`

Companion state file: `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/SCOPE_BUCKETS_2026-03-29.md`
Execution report: `/Users/tyegonzalez/Desktop/Helios-Package Merged/docs/reports/COMMIT_SCOPE_2026-03-29.md`

## Admission Rule

A file belongs in active scope only if it has at least one of these:

1. A runtime path into the shipped backend, frontend, or deploy flow.
2. A paired test or quality harness that matters to the current product.
3. A real operator workflow that still matters now.
4. A named near-term owner and a credible reason to exist.

If none of those are true, the file stays quarantined or local-only.

## Post-Burn-Down Read

This repo is no longer carrying uncontrolled active scope.

- product scope has been turned into real commits
- ops scope has been turned into real commits
- accepted untracked source groups have been turned into real subsystem commits
- local operator memory is kept local
  - `AGENTS.md` is intentionally not part of repo history
- the remaining visible files before the final governance commit are only the governance records themselves

## Validation Baseline

Whole-scope validation is green on the committed product surface:

- repo-wide `ruff` clean with `--ignore E402`
- `py_compile` clean across `293` Python files under `backend`, `scripts`, and `tests`
- frontend `npm run build` passed
- `python3 -m pytest -q tests backend/test_*.py` reached `[100%]`

## Current Read

The repo is no longer blocked by scope ambiguity. The remaining discipline is normal engineering discipline:

- keep commits narrow
- keep validation current
- do not let local-only files leak into active repo scope
