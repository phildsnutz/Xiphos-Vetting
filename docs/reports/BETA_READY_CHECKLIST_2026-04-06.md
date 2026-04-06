# Beta Ready Checklist

Date: 2026-04-06
Workspace: `/Users/tyegonzalez/Desktop/Helios-Package Merged`
Branch: `codex/helios-ui-beta-redesign`
Latest committed fix: `bb4bba3`

## Current Call

Helios is ready for a small controlled beta now.

Helios is not yet at the stronger bar of "confident beta with low babysitting overhead" until one short hardening cycle is complete.

## Evidence Baseline

- Hosted root-cause and recovery record: [HOSTED_API_MATRIX_2026-04-05.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/HOSTED_API_MATRIX_2026-04-05.md)
- Latest hosted current-product pass: [current_product_stress_harness_20260405191445.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/current_product_stress_harness/current_product_stress_harness_20260405191445.md)
- Hosted JSON record: [current_product_stress_harness_20260405191445.json](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/current_product_stress_harness/current_product_stress_harness_20260405191445.json)

## Green Now

- [x] `Stoa` intake trust acceptance spine passes on the live host.
- [x] `LEIA` ambiguity behavior is correct on live.
- [x] `LEIA contract vehicle` pivots immediately to vehicle flow.
- [x] `SMX` takes the vendor-first path.
- [x] `ILS 2 pre solicitation Amentum is prime` anchors correctly as `ILS 2`.
- [x] `Aegis` carryover works on the live host.
- [x] Mission-brief room contract is canonicalized to `stoa` and `aegis`.
- [x] Authenticated case workflow passes on the live host.
- [x] Graph resolve and AXIOM graph endpoints respond on the live host.
- [x] PostgreSQL graph-memory search is fixed and covered by regression in [test_entity_resolver_local.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/tests/test_entity_resolver_local.py).
- [x] Hosted regression artifacts no longer retain live credentials.

## Remaining Gates Before "Confident Beta"

- [ ] Release discipline is enforced for every deploy.
  Success means deploys always ship from a clean temporary worktree or equivalent clean exact-tree path, never from a dirty repo.
- [ ] Hosted soak is repeated for 24 to 48 hours.
  Success means rerunning the current-product harness, auth flow, and `Stoa -> Aegis -> case` path multiple times without drift or credential/reporting regressions.
- [ ] Beta gate is written down as an operator ritual, not tribal memory.
  Success means the deploy checklist, post-deploy checks, and rollback trigger are documented and followed.
- [ ] Read-only reporting stays credential-safe by default.
  Success means generated browser/harness artifacts redact or suppress live credential fill lines automatically.
- [ ] One repeatable Postgres-first regression slice is part of the normal ship gate.
  Success means resolver and intake trust checks run against the same database shape that exposed the live failure.

## Non-Blockers

- [ ] `backend/server.py` is still too large.
- [ ] The worktree still contains unrelated in-flight collector and frontend changes outside this fix set.
- [ ] Broader AXIOM depth is still light compared with the full product vision.

These do not block a small beta on the current path. They do raise the cost of change and support if left unmanaged.

## Recommended Beta Scope Right Now

Open beta access only for the current proven path:

- `Stoa` intake
- `Aegis` handoff
- authenticated case creation and decisions
- supplier passport
- assistant plan, execute, and feedback
- dossier PDF
- batch upload and report

Do not widen the beta promise beyond that path until the remaining gates above are closed.

## Exit Rule

Call Helios "confident beta ready" when all five remaining gates are closed and the hosted current-product harness is still green on the canonical host.

## Brutal Read

You are no longer blocked by a core product failure.

You are blocked by release discipline and repeatability. That is a much better place to be.
