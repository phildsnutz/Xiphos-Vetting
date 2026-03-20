# Claude Handoff: Phase 1 Entity Disambiguation Implementation

## Metadata

- Date: 2026-03-19
- From agent: Claude
- To agent: Codex
- Workspace: `/Users/tyegonzalez/Desktop/Helios-Package Merged`
- Scope: Phase 1 Entity Disambiguation Copilot implementation
- Status: Implemented, needs hardening pass

## Objective

Implemented the Phase 1 Entity Disambiguation Copilot per CODEX's build-ready spec. The resolver now computes deterministic match features for every candidate, detects ambiguity, and optionally calls the AI provider for reranking when the top candidates are close. The frontend shows a "Recommended" badge, rationale, and "Why this match?" expander. Analyst feedback is captured on every selection.

## What Changed

- Added `backend/entity_rerank.py`: new module with deterministic feature extraction, AI reranking logic, prompt building, response validation, persistence, and feedback recording.
- Extended `POST /api/resolve` in `backend/server.py` to accept optional `country`, `profile`, `program`, `context`, `use_ai`, and `max_candidates` fields. Response now includes an optional `resolution` object with recommendation, rationale, and evidence.
- Added `POST /api/resolve/feedback` endpoint for analyst feedback capture.
- Extended `EntityCandidate` in `frontend/src/lib/api.ts` with `candidate_id`, `match_features`, and `deterministic_score` fields.
- Added `EntityResolution`, `MatchFeatures`, and `ResolveResponse` interfaces.
- Updated `resolveEntity()` to accept options object.
- Added `submitResolveFeedback()` function.
- Updated `helios-landing.tsx` with: Recommended badge on the top candidate, AI-assisted label, recommendation banner with reason_summary, "Why this match?" expander for reason_detail, ambiguous state warning banner, automatic feedback submission on candidate selection.

## Files Changed

- `backend/entity_rerank.py`: new file, 340 lines. Deterministic features, AI reranking, prompt contract, schema validation, persistence, feedback.
- `backend/server.py`: extended `/api/resolve` (~50 lines added), added `/api/resolve/feedback` (~15 lines).
- `frontend/src/lib/api.ts`: added `MatchFeatures`, `EntityResolution`, `ResolveResponse` interfaces. Updated `resolveEntity()` signature and added `submitResolveFeedback()`.
- `frontend/src/components/xiphos/helios-landing.tsx`: recommendation UI, feedback tracking, resolution state management.

## API And Contract Changes

- `POST /api/resolve` now accepts `name` (required), plus optional `country`, `profile`, `program`, `context` (max 300 chars), `use_ai` (boolean, default true), `max_candidates` (integer, default 6, max 10).
- Response includes optional `resolution` object per CODEX spec schema.
- Backward compatible: name-only requests still work identically.
- `POST /api/resolve/feedback` accepts `request_id`, `selected_candidate_id`, `accepted_recommendation`.

## Env Vars And Runtime Assumptions

- `XIPHOS_ENTITY_RERANK_ENABLED`: default "true"
- `XIPHOS_ENTITY_RERANK_MIN_DELTA`: default 0.15
- `XIPHOS_ENTITY_RERANK_MAX_CANDIDATES`: default 5
- `XIPHOS_ENTITY_RERANK_MIN_CONFIDENCE`: default 0.82
- `XIPHOS_ENTITY_RERANK_PROMPT_VERSION`: default "entity-rerank-2026-03-19"
- Reuses existing AI provider configuration from `ai_analysis.py` (no separate provider stack).
- Falls back to org default AI config if user has no personal config.

## Data, ML, And Migrations

- Added two tables: `entity_resolution_runs` and `entity_resolution_feedback` (additive, no destructive migration).
- Tables created via `init_rerank_tables()` called on first resolve request.
- No new trained model. Uses prompt-based reranking only.

## Verification

- Not yet verified against live system (this is the build pass for CODEX to harden).
- Frontend not yet built or deployed.
- No eval dataset created yet.

## Not Verified

- Did not run a live AI rerank call through the Anthropic API.
- Did not create the 100-150 entity eval dataset CODEX spec requested.
- Did not run lint or build on the frontend.
- Did not write the backend/frontend tests from the test plan.

## Known Risks And Sharp Edges

- The `_call_ai_rerank` function imports from `ai_analysis.py` using `_call_anthropic`, `_call_openai`, `_call_gemini`. These are internal functions. CODEX should verify the import contract is stable.
- The `candidate_id` is generated from `source:md5(key)[:10]` which may not be stable across resolver runs if the key identifier changes. CODEX should evaluate whether a more deterministic ID scheme is needed.
- JSON extraction from AI response uses a regex pattern `\{[^{}]*"decision"[^{}]*\}` which won't handle nested JSON. Should be tested against actual provider responses.
- No feature flag in the frontend yet. The recommendation UI always renders when `resolution` is present.
- The feedback endpoint has no rate limiting.

## Questions For The Next Agent

- Check whether the `_call_anthropic` / `_call_openai` / `_call_gemini` imports from `ai_analysis.py` are stable public interfaces or internal functions that might change.
- Verify the deterministic scoring weights (name_score 0.40, country 0.15, identifiers 0.08, ownership 0.10, source_rank 0.10) produce sensible rankings on the eval set.
- Check whether the prompt contract handles adversarial entity names (e.g., names containing JSON or instruction-like text).
- Decide whether the `entity_resolution_runs` table should have a TTL/cleanup policy.

## Recommended Next Actions

1. Run lint and build on the frontend to verify no TypeScript errors.
2. Write backend tests per the test plan in the spec.
3. Create the eval dataset (100-150 ambiguous entities).
4. Deploy and test with live AI calls against "General Atomics", "L3Harris", "BAE Systems", and one deliberately ambiguous private company.
