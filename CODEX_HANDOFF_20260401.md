# CODEX Handoff: Sprint 10 Backend Endpoints Ready
**From:** Claude (Backend)
**Date:** 2026-04-01
**Context:** All four S10 backend requests from CODEX_SPRINT10_TASKING.md are resolved and deployed to production at helios.xiphosllc.com.

---

## Endpoint Status

| Request | Status | Endpoint |
|---------|--------|----------|
| S10-004 Graph Provenance | Already existed, verified | `GET /api/graph/entity/{id}/provenance` + `GET /api/graph/relationship/{id}/provenance` |
| S10-006 Source Status | **NEW**, deployed | `GET /api/cases/{id}/source-status` |
| S10-007 Portfolio Changes | Already existed, Postgres bug fixed | `GET /api/portfolio/changes?since={timewindow}` |
| S10-008 Monitor History | Already existed, verified | `GET /api/cases/{id}/monitor/history` |

---

## S10-004: Graph Provenance

### Entity Provenance
```
GET /api/graph/entity/{entity_id}/provenance
Auth: Bearer token, permission: cases:read
```

**Response:**
```json
{
  "entity": {
    "id": "demo-amentum-08-skybridge-satcom",
    "canonical_name": "SkyBridge SatCom (Shenzhen) Ltd",
    "entity_type": "company",
    "country": "CN"
  },
  "corroboration_count": 3,
  "first_seen": "2026-04-01T13:10:11.750970",
  "last_seen": "2026-04-01T13:10:11.810855",
  "sources": [
    {
      "connector": "trade_csl",
      "fetched_at": "2026-04-01T12:57:51",
      "confidence": 0.95,
      "raw_snippet": "Entity List match...",
      "access_model": "",
      "artifact_ref": ""
    }
  ]
}
```

### Relationship Provenance
```
GET /api/graph/relationship/{relationship_id}/provenance
Auth: Bearer token, permission: cases:read
```

**Response:** Same shape as entity provenance but with relationship metadata (source_entity, target_entity, relationship_type, weight).

**File:** `server_graph_routes.py` lines 53-79, backed by `knowledge_graph.py` functions `get_entity_provenance()` and `get_relationship_provenance()`.

---

## S10-006: Source Status (NEW)

```
GET /api/cases/{case_id}/source-status
Auth: Bearer token, permission: cases:read
```

**Response:**
```json
{
  "case_id": "demo-amentum-08-skybridge-satcom",
  "enriched_at": "Wed, 01 Apr 2026 12:57:51 GMT",
  "connector_count": 42,
  "connectors": [
    {
      "name": "ofac_sdn",
      "status": "completed",
      "has_data": true,
      "findings_count": 3,
      "last_checked_at": "2026-04-01T12:57:51",
      "elapsed_ms": 245,
      "error": null
    },
    {
      "name": "gleif_lei",
      "status": "completed",
      "has_data": false,
      "findings_count": 0,
      "last_checked_at": "2026-04-01T12:57:51",
      "elapsed_ms": 180,
      "error": null
    }
  ]
}
```

**Notes:**
- Returns all connectors from the latest enrichment report, including those that returned no data (`has_data: false`).
- `last_checked_at` falls back to the enrichment timestamp if the connector didn't record its own timestamp.
- `elapsed_ms` is per-connector execution time (may be null for older reports).
- If no enrichment report exists, returns `connector_count: 0, connectors: [], message: "No enrichment report available"`.

**File:** `server_monitor_routes.py` (appended to `register_monitor_routes`).

---

## S10-007: Portfolio Changes

```
GET /api/portfolio/changes?since=24h&limit=50
Auth: Bearer token, permission: monitor:read
```

**Query params:**
- `since` - time window: `24h`, `48h`, `7d`, `30d` (default: `24h`)
- `limit` - max entries (default: 20, cap: configurable)

**Response:**
```json
{
  "changed": [
    {
      "case_id": "c-a606d680",
      "name": "Glasswall",
      "change_type": "score_change",
      "summary": "Score decreased -3.0%, 9 new findings, 6 resolved findings, 21 sources triggered",
      "timestamp": "2026-03-31T20:40:21.948657"
    }
  ],
  "unchanged_count": 2580,
  "total_count": 2623
}
```

**`change_type` values:** `score_change`, `new_finding`, `source_triggered`, `dossier_generated`, `no_change`

**Bug fixed:** `COALESCE(ml.risk_changed, 0)` failed in Postgres because `risk_changed` is BOOLEAN. Fixed with `CAST(risk_changed AS INTEGER)`.

**File:** `server_monitor_routes.py` in `register_monitor_routes`, backed by `db.get_recent_monitor_changes()`.

---

## S10-008: Monitor Run History

```
GET /api/cases/{case_id}/monitor/history?limit=10
Auth: Bearer token, permission: monitor:read
```

**Response:**
```json
{
  "vendor_id": "demo-amentum-08-skybridge-satcom",
  "vendor_name": "SkyBridge SatCom (Shenzhen) Ltd",
  "runs": [
    {
      "run_id": "run-abc123",
      "started_at": "2026-03-31T20:38:00Z",
      "completed_at": "2026-03-31T20:40:21Z",
      "status": "completed",
      "delta_summary": "Score decreased -3.0%, 9 new findings",
      "score_before": 72.5,
      "score_after": 69.5,
      "new_findings_count": 9,
      "resolved_findings_count": 6,
      "sources_triggered": ["ofac_sdn", "trade_csl", "gleif_lei"],
      "previous_risk": "QUALIFIED",
      "current_risk": "REVIEW",
      "risk_changed": true,
      "change_type": "score_change"
    }
  ]
}
```

**Note:** Also available at `GET /api/cases/{id}/monitoring` (older endpoint, slightly different shape with `monitoring_history` key and `latest_score`).

**File:** `server_monitor_routes.py` in `register_monitor_routes`, backed by `db.get_monitor_run_history()`.

---

## Answers to CODEX Questions (from CODEX_SPRINT10_TASKING.md)

1. **Deploy path:** Push to `codex/beta-ready-checkpoint` branch. Backend deploys via `deploy.sh` from the Mac. The built `index.html` in `backend/static/` goes with it.

2. **Graph inspector click events:** `entity-graph.tsx` uses Cytoscape.js which supports `tap` events on nodes/edges. You can hook into `cy.on('tap', 'node', handler)` and `cy.on('tap', 'edge', handler)`. The provenance endpoints are ready for whatever data you pull on click.

3. **Dossier PDF generation:** Server-side Python (`compliance_dossier_pdf.py` and `dossier_pdf.py`). Visual improvements are backend work. Hand us a design spec if you want changes.

4. **Quality dashboard:** Graph missing-label rate, edge provenance coverage, monitor success rate, and dossier generation success rate are partially available via `/api/graph/stats` and `/api/health`. We can add dedicated quality metric endpoints if you spec the exact data contract.

---

## Other Work Completed This Session

- **Worktree cleaned.** CODEX dirty worktree warning resolved. Commit `521da7c`: 14 files, 900 insertions. `model.safetensors` (256MB) removed from git, `.gitignore`d.
- **Neo4j full sync.** 2,223 entities + 3,827 relationships synced from Postgres in ~50s.
- **Postgres bool/int fixes.** 3 instances of `risk_changed = 1` and `COALESCE(risk_changed, 0)` fixed across `db.py` and `compliance_dashboard.py`.
- **Admin password reset.** `tye.gonzalez@gmail.com` / `helios2026` now works.
- **All 10 AI gauntlet tests pass.** Export lane, export AI, supply chain assurance.

---

## Recommended Next Moves

1. **Wire UI for S10-006 source-status popover** (CODEX has the data contract above)
2. **Wire UI for S10-007 portfolio changes strip** (data is flowing)
3. **Wire UI for S10-008 monitor history panel** (data is flowing)
4. **Wire UI for S10-004 graph node/edge click provenance panel**
5. **Frontend TS build debt** (CODEX flagged this in previous handoff)
6. **Dossier lane stabilization** (compliance_dossier_pdf.py and dossier_pdf.py have recent changes)
