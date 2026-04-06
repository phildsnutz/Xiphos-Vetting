# Hosted API Matrix

Generated: 2026-04-05  
Canonical host: `https://helios.xiphosllc.com`

## Executive Read

Final state: the deployed host is functioning and the hosted acceptance spine is green.

What is live and working:
- Auth is enabled and usable.
- `Stoa` loads and routes the current acceptance spine.
- `Aegis` carryover works.
- Graph resolve, communities, and AXIOM graph endpoints are reachable and returning structured payloads.
- Authenticated case workflow passes through compare, case creation, decisions, supplier passport, assistant plan/execute/feedback, dossier PDF, and batch upload/report.

Bottom line:
- The original live problem was twofold:
  - deploy drift left the host on a stale router and stale bundle
  - PostgreSQL graph-memory search in [entity_resolver.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/entity_resolver.py) used `LOWER(jsonb)` on `kg_entities.aliases`, failed on live, and silently returned no graph hits
- Once the host was redeployed from the current slice and graph-memory search was fixed to cast aliases to text, `LEIA` correctly returned the hybrid ambiguity path.
- This ended as a real root-cause fix, not a `LEIA` keyword hack and not a manual one-off data patch.

## Final Resolution

Hosted result on [helios.xiphosllc.com](https://helios.xiphosllc.com):
- `stoa_browser_regression`: `PASS`
- `aegis_carryover_regression`: `PASS`
- `room_contract`: `PASS`
- `graph_timing`: `PASS`
- `authenticated_case_flow`: `PASS`

Final hosted harness artifacts:
- [current_product_stress_harness_20260405191445.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/current_product_stress_harness/current_product_stress_harness_20260405191445.md)
- [current_product_stress_harness_20260405191445.json](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/current_product_stress_harness/current_product_stress_harness_20260405191445.json)

Final live intake payload shape:
- `LEIA` -> `winning_mode: null`, `clarifier_needed: true`
- `LEIA contract vehicle` -> `winning_mode: vehicle`
- `SMX` -> `winning_mode: vendor`
- `ILS 2 pre solicitation Amentum is prime` -> `winning_mode: vehicle`, `anchor_text: ILS 2`

## Hosted Matrix

### Public surfaces

| Surface | Status | Notes |
|---|---:|---|
| `GET /api/health` | `200` | `auth_enabled: true`, `login_required: true`, `connector_count: 50`, `version: 5.2.0` |
| `POST /api/auth/setup` | `400` | Correct behavior. Setup already complete and users exist. |
| `POST /api/intake/route` `LEIA` | `200` | `winning_mode: vehicle`, `clarifier_needed: false` |
| `POST /api/intake/route` `LEIA contract vehicle` | `200` | `winning_mode: vehicle`, `clarifier_needed: false` |
| `POST /api/intake/route` `SMX` | `200` | `winning_mode: vendor`, `clarifier_needed: false` |
| `POST /api/intake/route` `ILS 2 pre solicitation Amentum is prime` | `200` | `winning_mode: vehicle`, `clarifier_needed: false` |

### Authenticated surfaces

| Surface | Status | Notes |
|---|---:|---|
| `POST /api/auth/login` | `200` | Admin login succeeds on canonical host |
| `POST /api/resolve` | `200` | `SMX` returned `6` candidates |
| `GET /api/graph/analytics/communities` | `200` | `algorithm: leiden` |
| `POST /api/axiom/graph/profile` | `200` | `status: ok`, structured payload present |
| `POST /api/axiom/graph/anomalies` | `200` | `status: ok`, structured payload present |

### Browser and workflow gates

| Check | Status | Notes |
|---|---:|---|
| `stoa_browser_regression` | `PASS` | Returned `leia_path: vehicle_first`, `smx_path: vendor_first` |
| `aegis_carryover_regression` | `PASS` | Returned `carryover: passed` |
| `room_contract` | `FAIL` | Failed on `LEIA path drifted: vehicle_first` |
| `graph_timing` | `PASS` | `resolve_vehicle_ms: 1780.8`, `communities_ms: 924.4`, graph p95s healthy |
| `authenticated_case_flow` | `PASS` | Full smoke passed |

## Live Payloads

### `LEIA`

Live payload:

```json
{
  "anchor_text": "LEIA",
  "clarifier_needed": false,
  "confidence": 0.9,
  "hypotheses": [
    {
      "kind": "vehicle",
      "reasons": [
        "The input matches a known contract-vehicle seed."
      ],
      "score": 0.9
    },
    {
      "kind": "vendor",
      "reasons": [
        "The input reads like a named entity rather than a freeform question."
      ],
      "score": 0.42
    }
  ],
  "override_applied": false,
  "raw_input": "LEIA",
  "winning_mode": "vehicle"
}
```

Meaning:
- Live sees the known vehicle seed.
- Live does **not** see a strong competing vendor/entity memory signal.
- The ambiguity branch never fires.

### `LEIA contract vehicle`

Live payload:

```json
{
  "anchor_text": "LEIA",
  "clarifier_needed": false,
  "confidence": 0.94,
  "hypotheses": [
    {
      "kind": "vehicle",
      "reasons": [
        "The user explicitly described the target as a contract vehicle."
      ],
      "score": 0.94
    },
    {
      "kind": "vendor",
      "reasons": [
        "The input reads like a named entity rather than a freeform question."
      ],
      "score": 0.42
    }
  ],
  "override_applied": false,
  "raw_input": "LEIA contract vehicle",
  "winning_mode": "vehicle"
}
```

Meaning:
- Immediate vehicle correction works.
- This part of the policy is fine on live.

### `SMX`

Live payload:

```json
{
  "anchor_text": "SMX",
  "clarifier_needed": false,
  "confidence": 0.86,
  "hypotheses": [
    {
      "kind": "vehicle",
      "reasons": [],
      "score": 0.0
    },
    {
      "kind": "vendor",
      "reasons": [
        "The input reads like a named entity rather than a freeform question.",
        "Local vendor memory already has SMX (Security Matters) Public Ltd Co in frame."
      ],
      "score": 0.86
    }
  ],
  "override_applied": false,
  "raw_input": "SMX",
  "winning_mode": "vendor"
}
```

Meaning:
- Vendor-first trust path is working.

### `ILS 2 pre solicitation Amentum is prime`

Live payload:

```json
{
  "anchor_text": "ILS 2 pre  Amentum is prime",
  "clarifier_needed": false,
  "confidence": 0.94,
  "hypotheses": [
    {
      "kind": "vehicle",
      "reasons": [
        "The user explicitly described the target as a contract vehicle.",
        "The token pattern looks like a contract vehicle or solicitation identifier."
      ],
      "score": 0.94
    },
    {
      "kind": "vendor",
      "reasons": [],
      "score": 0.0
    }
  ],
  "override_applied": false,
  "raw_input": "ILS 2 pre solicitation Amentum is prime",
  "winning_mode": "vehicle"
}
```

Meaning:
- Vehicle branch selection is correct.
- Vehicle anchor extraction is stale on live.

## Local Contract Versus Live

### Current local branch behavior

Local `route_intake("LEIA")` currently returns:
- `winning_mode: null`
- `clarifier_needed: true`
- vehicle score `0.9`
- vendor score `0.78`
- vendor reason includes `Graph memory already has LEIA in frame.`

Local `route_intake("ILS 2 pre solicitation Amentum is prime")` currently returns:
- `winning_mode: vehicle`
- `anchor_text: ILS 2`

Local acceptance contract in [test_intake_router_local.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/tests/test_intake_router_local.py):
- `LEIA` with strong graph entity memory must admit ambiguity
- `LEIA contract vehicle`, `LEIA vehicle`, and `LEIA not a company` must pivot immediately from entity narrowing
- `SMX` with strong local memory must route vendor-first
- `ILS 2 pre solicitation Amentum is prime` must route vehicle-first with anchor `ILS 2`

### Exact deploy gaps

1. **Live data-plane gap on `LEIA` ambiguity**
   - Local contract assumes a strong competing graph/entity memory signal for `LEIA`.
   - Live payload shows no such signal at all.
   - Result: live goes straight to `vehicle_first`.

2. **Live router code-path drift on vehicle anchor extraction**
   - Local branch extracts `ILS 2`.
   - Live extracts `ILS 2 pre  Amentum is prime`.
   - That is not explained by data alone. It indicates the deployed router path is older or otherwise not aligned with the current branch.

3. **Live browser regression is permissive**
   - `stoa_browser_regression` passes on either `ambiguity_then_vehicle` or `vehicle_first`.
   - `room_contract` is the check that correctly fails the host.
   - Result: the broad browser check can still look green while the trust contract is wrong.

4. **Canonical host versus fallback host confusion**
   - The working canonical host is `https://helios.xiphosllc.com`.
   - The older `sslip.io` endpoint is not the right source of truth for hosted verification.
   - Future hosted checks should default to the canonical host.

## Smallest Live-Fix Plan

Scope only:
- `Stoa` intake trust
- no new features
- no unrelated graph work
- no UI polish

### Fix 1

Deploy the current `backend/intake_router.py` contract, not a partial or stale variant.

Why:
- The stale `ILS 2` anchor behavior is a code-path drift signal.
- The current branch already contains the stronger vehicle-anchor extraction and revision handling.

### Fix 2

Seed or restore the competing `LEIA` entity memory that the hybrid policy depends on, or verify that the intended live graph/local memory source actually contains it.

Why:
- The current hybrid policy is explicitly conditional.
- If the live host has no credible competing entity memory for `LEIA`, then ambiguity will never trigger.
- This is a data-plane requirement, not just a routing-rule requirement.

### Fix 3

Keep `room_contract` as the gating verdict and tighten hosted regression language around it.

Why:
- The current top-level browser regression is intentionally tolerant.
- That tolerance is fine for broad smoke, but not enough as the trust authority.
- `room_contract` should remain the release gate for `Stoa` intake trust.

### Fix 4

After deploy, rerun only this hosted acceptance spine first:
- `LEIA`
- `LEIA contract vehicle`
- `SMX`
- `ILS 2 pre solicitation Amentum is prime`

Expected result:
- `LEIA` -> `ambiguity_then_vehicle` when competing entity memory is live
- `LEIA contract vehicle` -> immediate vehicle pivot
- `SMX` -> vendor-first
- `ILS 2 pre solicitation Amentum is prime` -> vehicle-first with clean anchor handling

## Recommended Order

1. Verify the deployed container or process is actually on the current `intake_router.py`.
2. Verify the live memory sources contain the intended `LEIA` competing entity signal.
3. Redeploy only the `Stoa` intake trust slice if needed.
4. Rerun the hosted acceptance spine.
5. Do not touch broader workflow paths unless the rerun shows new regressions.

## Exact Ship List

Smallest live deploy to fix the actual disease:

- [backend/intake_router.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/intake_router.py)
  - This is the core fix.
  - It contains the stronger vehicle-anchor extraction, ambiguity handling, and revision override behavior.
- [frontend/src/components/xiphos/front-porch-landing.tsx](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/frontend/src/components/xiphos/front-porch-landing.tsx)
  - Needed if the deployed UI copy and state contract should match the current `Stoa` ambiguity behavior exactly.
- [scripts/run_front_porch_browser_regression.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/scripts/run_front_porch_browser_regression.py)
  - Keep this aligned so post-deploy smoke checks the right `LEIA` behavior.
- [tests/test_intake_router_local.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/tests/test_intake_router_local.py)
  - This is the local acceptance authority for the `Stoa` intake spine.
- [scripts/run_current_product_stress_harness.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/scripts/run_current_product_stress_harness.py)
  - Needed because `room_contract` is the real release gate for this behavior.
- [backend/static/index.html](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/static/index.html)
  - Ship this only if the deploy path is using the checked-in built bundle.

Optional but strongly recommended for coherence if you want the full current room contract live at the same time:

- [backend/helios_core/room_contract.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/helios_core/room_contract.py)
- [backend/helios_core/mission_briefs.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/helios_core/mission_briefs.py)
- [backend/server.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/server.py)
- [backend/db.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/db.py)
- [frontend/src/App.tsx](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/frontend/src/App.tsx)
- [frontend/src/components/xiphos/front-porch-brief-view.tsx](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/frontend/src/components/xiphos/front-porch-brief-view.tsx)
- [frontend/src/components/xiphos/war-room.tsx](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/frontend/src/components/xiphos/war-room.tsx)
- [frontend/src/lib/api.ts](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/frontend/src/lib/api.ts)
- [tests/test_mission_brief_api_local.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/tests/test_mission_brief_api_local.py)
- [scripts/run_war_room_carryover_regression.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/scripts/run_war_room_carryover_regression.py)

## Most Likely Reason The Host Is Behind

This is the strongest read from the live probe:

1. The deploy tools are not the old `git pull` path.
   - [deploy.sh](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/deploy.sh) now performs an exact-tree `rsync --delete` from the local workspace to the remote host, then rebuilds Docker.
   - [deploy.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/deploy.py) also performs an exact-tree archive sync, not a remote branch pull.

2. The live host is still running a different repo state.
   - Remote repo path: `/opt/xiphos`
   - Remote branch: `codex/beta-ready-checkpoint`
   - Remote HEAD: `9a0004e8bf1a13a5eb25c9215187aa67ecd5f6b8`
   - Local branch: `codex/helios-ui-beta-redesign`
   - Local HEAD: `0d88bbe0eaa0683bc0ee161b146a065b79292812`

3. The remote worktree is dirty.
   - The remote host has a long list of modified tracked files.
   - That means the host is not a clean mirror of the current local workspace.

4. The live files themselves prove router and bundle drift.
   - Remote [backend/intake_router.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/intake_router.py) equivalent is missing `_VEHICLE_ANCHOR_CUES`.
   - Remote router text does not contain `Entity narrowing should be abandoned because the new turn points back to a contract vehicle.`
   - Remote router text does not contain `Graph memory already has LEIA in frame.`
   - Remote built bundle still contains `front_porch` and `war_room`.
   - Remote built bundle does not contain `Brief carried from Stoa` or `Enter Aegis`.

Most likely operational explanation:
- the canonical deploy path from this exact workspace has not been run against the host since these `Stoa` and room-contract changes were made
- or the host was subsequently altered from another branch or ad hoc remote edits after a prior deploy

That is why the host can be broadly functional while still being behind the local router contract.

## Deeper Container Read

The running app is not being masked by a repo bind mount.

Observed live container facts:
- Container: `xiphos-xiphos-1`
- State: `running`, `healthy`
- Created: `2026-04-05T14:54:59Z`
- Started: `2026-04-05T14:55:01Z`
- Image: `xiphos-xiphos`
- Image digest label: `sha256:4d4ac73e1a826b1aad8a9ee3d92faa0aaf88ed87e0d4217acb2d72400b22c5b7`
- Only mount: `/data` volume
- No bind mount from `/opt/xiphos` into `/app`

Meaning:
- The live container is serving code baked into the current image.
- The image itself contains the stale router and stale bundle markers.
- This is not a case where the repo is stale but the image is current, or where a mounted repo is hiding the image state.
- A fresh image was built from stale remote source state.

## Related Reports

- [current_product_stress_harness_20260405180247.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/current_product_stress_harness/current_product_stress_harness_20260405180247.md)
- [current_product_stress_harness_20260405180247.json](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/current_product_stress_harness/current_product_stress_harness_20260405180247.json)
