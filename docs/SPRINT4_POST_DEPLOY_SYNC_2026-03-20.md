# Sprint 4 Post-Deploy Sync

Date: 2026-03-20

## Purpose

This note captures the local working-tree changes that were deployed live after the Sprint 4 readiness audit so the merged repo can be committed without drift from production.

Live deployment target:

- [internal live environment redacted]

## Files In Scope

- `backend/server.py`
- `backend/static/index.html`
- `deploy.py`
- `frontend/index.html`
- `frontend/src/components/xiphos/case-detail.tsx`

## What Changed

### 1. Restore the PDF dossier contract

`/api/cases/:id/dossier-pdf` was returning HTML in the local working tree, which broke the expected API contract and the local smoke test.

Fix:

- `backend/server.py` now returns a real PDF from `generate_pdf_dossier(...)` with `Content-Type: application/pdf`.

### 2. Keep the case detail dossier action on the rich HTML dossier path

The Sprint 4 case detail flow intentionally opens the richer HTML dossier experience, then falls back to the older client-side dossier path if needed.

Fix/behavior retained:

- `frontend/src/components/xiphos/case-detail.tsx` calls `/api/cases/:id/dossier`
- opens `download_url` in a new tab with the session token
- falls back to `onDossier(...)` on failure

### 3. Update shipped browser title

The SPA title still shipped as `xiphos-dashboard`, which was stale after the UI redesign.

Fix:

- `frontend/index.html` title changed to `Helios | Xiphos`
- rebuilt bundle captured in `backend/static/index.html`

### 4. Update deploy verification to match Sprint 4 UI copy

The deploy helper was still verifying old bundle strings and reported false failures even after a successful rollout.

Fix:

- `deploy.py` bundle expectations now check for:
  - `Helios | Xiphos`
  - `What do you want to assess?`
  - `Create draft cases`
  - `Begin Assessment`
- It now rejects `xiphos-dashboard` instead of the old stale `standard_industrial` heuristic

## Deployment Outcome

Deployment was completed to production using the patch deploy path over SSH.

Operational issue encountered:

- The droplet ran out of disk during Docker rebuild.
- Resolution: reclaimed ~63 GB via Docker image/build-cache cleanup, then reran deployment.

## Verification

Live verification passed after deployment:

- Container healthy
- SPA title updated
- Sprint 4 copy present in the shipped bundle
- 27 connectors reported by `/api/health`
- auth login works
- entity resolution works
- scoring works

## Recommended Commit Message

Subject:

`fix dossier pdf contract and sync sprint 4 deployed bundle`

Body:

- restore `/api/cases/:id/dossier-pdf` to real PDF output
- keep case detail on rich HTML dossier flow with fallback
- update shipped SPA title to `Helios | Xiphos`
- rebuild bundled frontend artifact
- align deploy verification with Sprint 4 UI copy
