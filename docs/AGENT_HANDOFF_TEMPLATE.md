# Agent Handoff Template

Use this document when handing work from one agent to another. Keep it factual, specific, and easy to diff against the codebase.

## Metadata

- Date:
- From agent:
- To agent:
- Workspace:
- Scope:
- Status:

## Objective

Describe the user request or sprint goal in 2-4 sentences.

## What Changed

- Summarize the highest-impact changes first.
- Call out any behavior changes that a reviewer or operator would notice.

## Files Changed

- `path/to/file`: what changed and why
- `path/to/file`: what changed and why

## API And Contract Changes

- Routes added, removed, or behaviorally changed
- Request/response schema changes
- Backward-compatibility aliases or breaking changes

## Env Vars And Runtime Assumptions

- New env vars:
- Changed env vars:
- Runtime paths:
- Deployment assumptions:

## Data, ML, And Migrations

- Model files, training data, migrations, seeds, or schema changes
- Compatibility notes for existing data

## Verification

- Commands run:
- Results:
- Manual smoke checks:

## Not Verified

- Anything not run locally
- External systems that were mocked, skipped, or unavailable

## Known Risks And Sharp Edges

- Real remaining issues, not wishful thinking
- Operational caveats
- Security or reliability concerns still open

## Questions For The Next Agent

- Concrete questions only
- Prefer "check X in Y file" over vague requests

## Recommended Next Actions

1. Highest-value next step.
2. Second most important step.
3. Nice-to-have follow-up.
