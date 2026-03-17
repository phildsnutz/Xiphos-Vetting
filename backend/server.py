#!/usr/bin/env python3
"""
Xiphos v5.0 API Server

Flask backend with SQLite persistence, JWT authentication, RBAC, and
full audit logging. All scoring runs through the FGAMLogit v5.0 engine
(two-layer DoD/commercial dual-vertical architecture).
17-source OSINT enrichment, entity resolution, continuous monitoring,
and dossier generation.

Auth Endpoints:
  POST /api/auth/login                   Authenticate and get bearer token
  GET  /api/auth/me                      Current user info
  GET  /api/auth/users                   List users (admin only)
  POST /api/auth/users                   Create user (admin only)
  POST /api/auth/setup                   One-time admin bootstrap
  GET  /api/audit                        Query audit log (auditor+)

Core Endpoints:
  GET  /api/health                       Health check + stats
  GET  /api/cases?limit=N                List vendor cases (with latest scores)
  GET  /api/cases/:id                    Get single case with full score
  POST /api/cases                        Create a new vendor case
  POST /api/cases/:id/score              Re-score a vendor
  POST /api/cases/:id/enrich             Run OSINT enrichment on a vendor
  POST /api/cases/:id/enrich-and-score   Full pipeline: enrich + augment + rescore
  GET  /api/cases/:id/enrichment         Get latest enrichment report
  POST /api/cases/:id/dossier            Generate dossier (HTML)
  POST /api/cases/:id/monitor            Check vendor for risk changes
  GET  /api/cases/:id/graph              Get entity resolution graph
  POST /api/enrich                       Run standalone OSINT enrichment
  POST /api/screen                       Screen a vendor name against OFAC
  GET  /api/screenings?limit=N           Screening history
  GET  /api/alerts?limit=N               List alerts
  POST /api/alerts/:id/resolve           Resolve an alert
  POST /api/monitor/run                  Run monitoring sweep on all vendors
  GET  /api/monitor/changes              Get recent risk changes
  GET  /api/graph/shared/:id_a/:id_b     Find hidden connections between vendors
"""

import os
import sys
import json
import uuid
import argparse
from datetime import datetime

from flask import Flask, request, jsonify, send_file

from fgamlogit import (
    score_vendor, VendorInputV5, OwnershipProfile, DataQuality,
    ExecProfile, DoDContext, integrate_layers,
)
from ofac import screen_name, get_active_db, invalidate_cache
import db
from auth import (
    init_auth_db, register_auth_routes, require_auth, log_audit, AUTH_ENABLED
)
from hardening import (
    rate_limit, validate_vendor_input, validate_auth_input,
    configure_cors, add_security_headers,
)

# Optional: sanctions sync engine (may fail if dependencies missing)
try:
    import sanctions_sync
    HAS_SYNC = True
except ImportError:
    HAS_SYNC = False

# Optional: OSINT enrichment engine
try:
    from osint.enrichment import enrich_vendor
    from osint_scoring import augment_from_enrichment
    from osint_cache import get_enricher
    HAS_OSINT = True
except ImportError:
    HAS_OSINT = False

# Optional: Entity resolution + knowledge graph
try:
    from entity_resolution import EntityResolver
    import knowledge_graph as kg
    HAS_KG = True
except ImportError:
    HAS_KG = False

# Optional: Monitoring agent
try:
    from monitor import VendorMonitor
    HAS_MONITOR = True
except ImportError:
    HAS_MONITOR = False

# Optional: Dossier generator
try:
    from dossier import generate_dossier
    HAS_DOSSIER = True
except ImportError:
    HAS_DOSSIER = False

# Static folder for serving the bundled frontend
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = Flask(__name__, static_folder=None)
configure_cors(app)
add_security_headers(app)

# Register auth routes immediately (available regardless of main() startup)
register_auth_routes(app)


@app.route("/")
def serve_frontend():
    """Serve the single-file dashboard."""
    index = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index):
        return send_file(index)
    # Fallback: try dist/ in the project root
    alt = os.path.join(os.path.dirname(__file__), "..", "dist", "xiphos-dashboard.html")
    if os.path.exists(alt):
        return send_file(alt)
    return jsonify({"error": "Frontend not found. Place index.html in static/ or dist/"}), 404


# ---- Seed data ----
# Empty by default. The database starts clean.
# Vendors are added via the API (POST /api/cases) or the frontend screening form.
# To load demo data for testing, use: python server.py --demo
SEED_VENDORS: list[dict] = []


def _build_vendor_input(v: dict) -> VendorInputV5:
    """Build VendorInputV5 from the stored/submitted vendor dict."""
    o = v.get("ownership", {})
    d = v.get("data_quality", {})
    e = v.get("exec", {})
    dod_raw = v.get("dod", {})

    ownership = OwnershipProfile(
        publicly_traded=o.get("publicly_traded", False),
        state_owned=o.get("state_owned", False),
        beneficial_owner_known=o.get("beneficial_owner_known", False),
        ownership_pct_resolved=o.get("ownership_pct_resolved", 0.0),
        shell_layers=o.get("shell_layers", 0),
        pep_connection=o.get("pep_connection", False),
        foreign_ownership_pct=o.get("foreign_ownership_pct", 0.0),
        foreign_ownership_is_allied=o.get("foreign_ownership_is_allied", True),
    )
    dq = DataQuality(
        has_lei=d.get("has_lei", False),
        has_cage=d.get("has_cage", False),
        has_duns=d.get("has_duns", False),
        has_tax_id=d.get("has_tax_id", False),
        has_audited_financials=d.get("has_audited_financials", False),
        years_of_records=d.get("years_of_records", 0),
    )
    ep = ExecProfile(
        known_execs=e.get("known_execs", 0),
        adverse_media=e.get("adverse_media", 0),
        pep_execs=e.get("pep_execs", 0),
        litigation_history=e.get("litigation_history", 0),
    )
    # Derive sensitivity from program if dod block not supplied
    program = v.get("program", "standard_industrial")
    _program_map = {
        "weapons_system": "TOP_SECRET", "mission_critical": "SECRET",
        "dual_use": "CUI", "standard_industrial": "COMMERCIAL",
        "commercial_off_shelf": "COMMERCIAL", "services": "COMMERCIAL",
    }
    default_sensitivity = _program_map.get(program, "COMMERCIAL")

    dod = DoDContext(
        sensitivity=dod_raw.get("sensitivity", default_sensitivity),
        supply_chain_tier=dod_raw.get("supply_chain_tier", 0),
        regulatory_gate_proximity=dod_raw.get("regulatory_gate_proximity", 0.0),
        itar_exposure=dod_raw.get("itar_exposure", 0.0),
        ear_control_status=dod_raw.get("ear_control_status", 0.0),
        foreign_ownership_depth=dod_raw.get("foreign_ownership_depth", 0.0),
        cmmc_readiness=dod_raw.get("cmmc_readiness", 0.0),
        single_source_risk=dod_raw.get("single_source_risk", 0.0),
        geopolitical_sector_exposure=dod_raw.get("geopolitical_sector_exposure", 0.0),
        financial_stability=dod_raw.get("financial_stability", 0.2),
        compliance_history=dod_raw.get("compliance_history", 0.0),
    )
    return VendorInputV5(
        name=v["name"], country=v["country"],
        ownership=ownership, data_quality=dq, exec_profile=ep, dod=dod,
    )


def _score_to_api_dict(result) -> dict:
    """Format ScoringResultV5 into the JSON shape the frontend expects."""
    return {
        "calibrated_probability": result.calibrated_probability,
        "calibrated_tier": result.calibrated_tier,
        "combined_tier": result.combined_tier,
        "interval": {
            "lower": result.interval_lower,
            "upper": result.interval_upper,
        },
        "contributions": result.contributions,
        "hard_stop_decisions": result.hard_stop_decisions,
        "soft_flags": result.soft_flags,
        "narratives": {"findings": result.findings},
        "marginal_information_values": result.marginal_information_values,
        # DoD fields (v5.0)
        "is_dod_eligible": result.is_dod_eligible,
        "is_dod_qualified": result.is_dod_qualified,
        "program_recommendation": result.program_recommendation,
        "sensitivity_context": result.sensitivity_context,
        "supply_chain_tier": result.supply_chain_tier,
        "regulatory_status": result.regulatory_status,
        "regulatory_findings": result.regulatory_findings,
        "model_version": result.model_version,
    }


def _full_score_dict(result) -> dict:
    # composite_score: probabilistic risk as 0-100 for legacy frontend display
    composite_score = round(result.calibrated_probability * 100)
    is_hard_stop = result.calibrated_tier.startswith("TIER_1")
    return {
        "composite_score": composite_score,
        "is_hard_stop": is_hard_stop,
        "calibrated": _score_to_api_dict(result),
    }


def _score_and_persist(vendor_id: str, v: dict) -> dict:
    """Score a vendor and persist everything to the database."""
    inp = _build_vendor_input(v)
    result = score_vendor(inp)
    score_dict = _full_score_dict(result)

    # Persist vendor
    db.upsert_vendor(vendor_id, v["name"], v["country"],
                     v.get("program", "standard_industrial"), v)

    # Persist score
    db.save_score(vendor_id, score_dict)

    # Persist alerts from hard stops and flags
    for stop in result.hard_stop_decisions:
        db.save_alert(vendor_id, v["name"], "critical",
                      stop["trigger"], stop["explanation"])
    for flag in result.soft_flags:
        sev = "high" if flag["confidence"] > 0.7 else "medium"
        db.save_alert(vendor_id, v["name"], sev,
                      flag["trigger"], flag["explanation"])

    return score_dict


def _seed_if_empty():
    """Load seed vendors if the database is empty."""
    stats = db.get_stats()
    if stats["vendors"] > 0:
        print(f"  Database has {stats['vendors']} vendors, skipping seed")
        return

    print("  Seeding database with 12 vendors...")
    for v in SEED_VENDORS:
        _score_and_persist(v["id"], v)
    stats = db.get_stats()
    print(f"  {stats['vendors']} vendors, {stats['unresolved_alerts']} alerts")


# ---- Routes ----

@app.route("/api/health")
@require_auth("health:read")
def health():
    stats = db.get_stats()
    _, db_label = get_active_db()

    sanctions_status = {}
    if HAS_SYNC:
        try:
            sanctions_sync.init_sanctions_db()
            sanctions_status = sanctions_sync.get_sync_status()
        except Exception:
            sanctions_status = {"error": "Could not read sanctions DB"}

    osint_connectors = []
    if HAS_OSINT:
        from osint.enrichment import CONNECTORS
        osint_connectors = [name for name, _ in CONNECTORS]

    # Cache stats
    cache_stats = {}
    if HAS_OSINT:
        try:
            cache_stats = get_enricher().get_stats()
        except Exception:
            pass

    return jsonify({
        "status": "ok",
        "version": "5.0.0",
        "auth_enabled": AUTH_ENABLED,
        "engine": "fgamlogit-dod-dual-vertical",
        "persistence": "sqlite",
        "sanctions_db": db_label,
        "sanctions_sync": sanctions_status,
        "osint_enabled": HAS_OSINT,
        "osint_connectors": osint_connectors,
        "osint_cache": cache_stats,
        "stats": stats,
    })


@app.route("/api/cases")
@require_auth("cases:read")
def api_list_cases():
    limit = request.args.get("limit", 100, type=int)
    vendors = db.list_vendors(limit)
    cases = []
    for v in vendors:
        score = db.get_latest_score(v["id"])
        cases.append({
            "id": v["id"],
            "vendor_name": v["name"],
            "status": score.get("calibrated", {}).get("calibrated_tier", "unknown") if score else "pending",
            "created_at": v["created_at"],
            "score": score,
        })
    return jsonify({"cases": cases})


@app.route("/api/cases/<case_id>")
@require_auth("cases:read")
def api_get_case(case_id):
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    score = db.get_latest_score(case_id)
    return jsonify({
        "id": v["id"], "vendor_name": v["name"],
        "status": score.get("calibrated", {}).get("calibrated_tier", "unknown") if score else "pending",
        "created_at": v["created_at"], "score": score,
    })


@app.route("/api/cases", methods=["POST"])
@require_auth("cases:create")
def api_create_case():
    body = request.get_json(silent=True) or {}
    required = ["name", "country"]
    for field in required:
        if field not in body:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    # Input validation
    valid, err = validate_vendor_input(body)
    if not valid:
        return jsonify({"error": err}), 400

    vendor_id = body.get("id", f"c-{uuid.uuid4().hex[:8]}")
    v = {
        "id": vendor_id,
        "name": body["name"],
        "country": body["country"],
        "ownership": body.get("ownership", {}),
        "data_quality": body.get("data_quality", {}),
        "exec": body.get("exec", {}),
        "program": body.get("program", "standard_industrial"),
    }
    score_dict = _score_and_persist(vendor_id, v)
    log_audit("case_created", "case", vendor_id,
              detail=f"Created case for {body['name']} ({body['country']})")
    return jsonify({
        "case_id": vendor_id,
        "composite_score": score_dict["composite_score"],
        "is_hard_stop": score_dict["is_hard_stop"],
        "calibrated": score_dict["calibrated"],
    }), 201


@app.route("/api/cases/<case_id>/score", methods=["POST"])
@require_auth("cases:score")
def api_rescore_case(case_id):
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    body = request.get_json(silent=True) or {}
    vendor_input = v["vendor_input"]
    if "program_type" in body:
        vendor_input["program"] = body["program_type"]

    score_dict = _score_and_persist(case_id, vendor_input)
    return jsonify({
        "case_id": case_id,
        "composite_score": score_dict["composite_score"],
        "is_hard_stop": score_dict["is_hard_stop"],
        "calibrated": score_dict["calibrated"],
    })


@app.route("/api/cases/<case_id>/score/history")
@require_auth("cases:read")
def api_score_history(case_id):
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    limit = request.args.get("limit", 10, type=int)
    history = db.get_score_history(case_id, limit)
    return jsonify({"vendor_id": case_id, "history": history})


@app.route("/api/cases/<case_id>/dossier", methods=["POST"])
@require_auth("cases:dossier")
def api_generate_dossier(case_id):
    """Generate a full HTML intelligence dossier for a vendor."""
    if not HAS_DOSSIER:
        return jsonify({"error": "Dossier generator not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    html = generate_dossier(case_id)

    # Save to static dir for download
    dossier_dir = os.path.join(os.path.dirname(__file__), "dossiers")
    os.makedirs(dossier_dir, exist_ok=True)
    filename = f"dossier-{case_id}.html"
    filepath = os.path.join(dossier_dir, filename)
    with open(filepath, "w") as f:
        f.write(html)

    log_audit("dossier_generated", "case", case_id,
              detail=f"Dossier generated for {v['name']}")

    body = request.get_json(silent=True) or {}
    if body.get("format") == "html":
        return html, 200, {"Content-Type": "text/html"}

    return jsonify({
        "case_id": case_id,
        "dossier_path": f"/dossiers/{filename}",
        "download_url": f"/api/dossiers/{filename}",
        "updated_at": datetime.now().isoformat(),
    })


@app.route("/api/dossiers/<filename>")
def api_serve_dossier(filename):
    """Serve a generated dossier HTML file."""
    dossier_dir = os.path.join(os.path.dirname(__file__), "dossiers")
    filepath = os.path.join(dossier_dir, filename)
    if os.path.exists(filepath):
        return send_file(filepath)
    return jsonify({"error": "Dossier not found"}), 404


# ---- Monitoring ----

@app.route("/api/cases/<case_id>/monitor", methods=["POST"])
@require_auth("monitor:run")
def api_monitor_vendor(case_id):
    """Run a monitoring check on a specific vendor."""
    if not HAS_MONITOR:
        return jsonify({"error": "Monitoring module not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    monitor = VendorMonitor()
    result = monitor.check_vendor(case_id)
    return jsonify({
        "vendor_id": result.vendor_id,
        "vendor_name": result.vendor_name,
        "previous_risk": result.previous_risk,
        "current_risk": result.current_risk,
        "risk_changed": result.risk_changed,
        "new_findings_count": len(result.new_findings),
        "resolved_findings_count": len(result.resolved_findings),
        "new_findings": result.new_findings[:10],
        "new_risk_signals": result.new_risk_signals[:10],
        "elapsed_ms": result.elapsed_ms,
    })


@app.route("/api/monitor/run", methods=["POST"])
@require_auth("monitor:run")
def api_monitor_all():
    """Run monitoring sweep on all vendors."""
    if not HAS_MONITOR:
        return jsonify({"error": "Monitoring module not available"}), 501

    body = request.get_json(silent=True) or {}
    interval = body.get("interval", 86400)

    monitor = VendorMonitor(check_interval=interval)
    results = monitor.check_all_vendors()

    changes = [r for r in results if r.risk_changed]
    return jsonify({
        "vendors_checked": len(results),
        "risk_changes": len(changes),
        "changes": [{
            "vendor_id": r.vendor_id,
            "vendor_name": r.vendor_name,
            "previous_risk": r.previous_risk,
            "current_risk": r.current_risk,
            "new_findings_count": len(r.new_findings),
        } for r in changes],
    })


@app.route("/api/monitor/changes")
@require_auth("monitor:read")
def api_monitor_changes():
    """Get recent risk changes from monitoring."""
    limit = request.args.get("limit", 20, type=int)
    try:
        changes = db.get_recent_risk_changes(limit)
        return jsonify({"changes": changes})
    except Exception:
        return jsonify({"changes": [], "note": "Monitoring log table not initialized"})


# ---- Entity Resolution / Knowledge Graph ----

@app.route("/api/cases/<case_id>/graph")
@require_auth("graph:read")
def api_get_entity_graph(case_id):
    """Get the entity resolution graph for a vendor."""
    if not HAS_KG:
        return jsonify({"error": "Knowledge graph module not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    kg.init_kg_db()
    entities = kg.get_vendor_entities(case_id)
    graph = {"vendor_id": case_id, "entities": [], "relationships": []}

    for e in entities:
        entity_data = kg.get_entity(e["entity_id"])
        if entity_data:
            graph["entities"].append(entity_data)
            network = kg.get_entity_network(e["entity_id"], depth=1)
            graph["relationships"].extend(network.get("relationships", []))

    return jsonify(graph)


@app.route("/api/graph/shared/<case_id_a>/<case_id_b>")
@require_auth("graph:read")
def api_find_shared_connections(case_id_a, case_id_b):
    """Find hidden connections between two vendors."""
    if not HAS_KG:
        return jsonify({"error": "Knowledge graph module not available"}), 501

    kg.init_kg_db()
    connections = kg.find_shared_connections(case_id_a, case_id_b)
    return jsonify({
        "vendor_a": case_id_a,
        "vendor_b": case_id_b,
        "shared_connections": connections,
    })


@app.route("/api/alerts")
@require_auth("alerts:read")
def api_list_alerts():
    limit = request.args.get("limit", 50, type=int)
    unresolved = request.args.get("unresolved", "false").lower() == "true"
    alerts = db.list_alerts(limit, unresolved_only=unresolved)
    return jsonify({"alerts": alerts})


@app.route("/api/alerts/<int:alert_id>/resolve", methods=["POST"])
@require_auth("alerts:resolve")
def api_resolve_alert(alert_id):
    body = request.get_json(silent=True) or {}
    resolved_by = body.get("resolved_by", "analyst")
    if db.resolve_alert(alert_id, resolved_by):
        log_audit("alert_resolved", "alert", str(alert_id),
                  detail=f"Alert {alert_id} resolved by {resolved_by}")
        return jsonify({"status": "resolved", "alert_id": alert_id})
    return jsonify({"error": "Alert not found or already resolved"}), 404


# ---- OSINT Enrichment ----

@app.route("/api/cases/<case_id>/enrich", methods=["POST"])
@require_auth("cases:enrich")
def api_enrich_case(case_id):
    """Run OSINT enrichment against a vendor case. Stores results in DB."""
    if not HAS_OSINT:
        return jsonify({"error": "OSINT enrichment module not available"}), 501

    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    body = request.get_json(silent=True) or {}
    connectors = body.get("connectors", None)  # Optional: run specific connectors only
    parallel = body.get("parallel", True)

    report = enrich_vendor(
        vendor_name=v["name"],
        country=v["country"],
        connectors=connectors,
        parallel=parallel,
    )

    # Persist enrichment report
    db.save_enrichment(case_id, report)

    # Generate alerts from critical/high findings
    for finding in report.get("findings", []):
        if finding["severity"] in ("critical", "high"):
            db.save_alert(
                case_id, v["name"],
                finding["severity"],
                f"[OSINT] {finding['title']}",
                finding.get("detail", ""),
            )

    log_audit("enrichment_run", "case", case_id,
              detail=f"OSINT enrichment on {v['name']}: {report.get('overall_risk', 'unknown')} risk")
    return jsonify(report)


@app.route("/api/cases/<case_id>/enrichment")
@require_auth("enrich:read")
def api_get_enrichment(case_id):
    """Get the latest OSINT enrichment report for a vendor case."""
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    report = db.get_latest_enrichment(case_id)
    if not report:
        return jsonify({"error": "No enrichment report found. Run POST /api/cases/{id}/enrich first."}), 404
    return jsonify(report)


@app.route("/api/enrich", methods=["POST"])
@require_auth("enrich:run")
def api_enrich_standalone():
    """Run OSINT enrichment without a case. Body: {"name": "...", "country": "US"}."""
    if not HAS_OSINT:
        return jsonify({"error": "OSINT enrichment module not available"}), 501

    body = request.get_json(silent=True) or {}
    vendor_name = body.get("name", "")
    if not vendor_name:
        return jsonify({"error": "Missing 'name' field"}), 400

    country = body.get("country", "")
    connectors = body.get("connectors", None)

    force = body.get("force", False)

    # Use cached enrichment (bypasses cache if force=True)
    enricher = get_enricher()
    report = enricher.enrich(
        vendor_name=vendor_name,
        country=country,
        force=force,
        connectors=connectors,
    )
    return jsonify(report)


@app.route("/api/cases/<case_id>/enrich-and-score", methods=["POST"])
@require_auth("cases:enrich")
def api_enrich_and_score(case_id):
    """Run OSINT enrichment, augment scoring inputs, and re-score. Full pipeline."""
    if not HAS_OSINT:
        return jsonify({"error": "OSINT enrichment module not available"}), 501

    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    body = request.get_json(silent=True) or {}
    connectors = body.get("connectors", None)

    # Step 1: Run OSINT enrichment
    report = enrich_vendor(
        vendor_name=v["name"],
        country=v["country"],
        connectors=connectors,
    )
    db.save_enrichment(case_id, report)

    # Step 2: Augment scoring inputs from enrichment
    vendor_input = v["vendor_input"]
    base_input = _build_vendor_input(vendor_input)
    augmentation = augment_from_enrichment(base_input, report)

    # Step 3: Re-score with augmented input
    result = score_vendor(augmentation.vendor_input)
    score_dict = _full_score_dict(result)

    # Persist updated vendor input and score
    updated_input = {
        **vendor_input,
        "ownership": {
            "publicly_traded": augmentation.vendor_input.ownership.publicly_traded,
            "state_owned": augmentation.vendor_input.ownership.state_owned,
            "beneficial_owner_known": augmentation.vendor_input.ownership.beneficial_owner_known,
            "ownership_pct_resolved": augmentation.vendor_input.ownership.ownership_pct_resolved,
            "shell_layers": augmentation.vendor_input.ownership.shell_layers,
            "pep_connection": augmentation.vendor_input.ownership.pep_connection,
        },
        "data_quality": {
            "has_lei": augmentation.vendor_input.data_quality.has_lei,
            "has_cage": augmentation.vendor_input.data_quality.has_cage,
            "has_duns": augmentation.vendor_input.data_quality.has_duns,
            "has_tax_id": augmentation.vendor_input.data_quality.has_tax_id,
            "has_audited_financials": augmentation.vendor_input.data_quality.has_audited_financials,
            "years_of_records": augmentation.vendor_input.data_quality.years_of_records,
        },
        "exec": {
            "known_execs": augmentation.vendor_input.exec_profile.known_execs,
            "adverse_media": augmentation.vendor_input.exec_profile.adverse_media,
            "pep_execs": augmentation.vendor_input.exec_profile.pep_execs,
            "litigation_history": augmentation.vendor_input.exec_profile.litigation_history,
        },
    }
    db.upsert_vendor(case_id, v["name"], v["country"],
                     v.get("program", "standard_industrial"), updated_input)
    db.save_score(case_id, score_dict)

    # Generate alerts from enrichment + scoring
    for finding in report.get("findings", []):
        if finding["severity"] in ("critical", "high"):
            db.save_alert(case_id, v["name"], finding["severity"],
                          f"[OSINT] {finding['title']}", finding.get("detail", ""))
    for stop in result.hard_stop_decisions:
        db.save_alert(case_id, v["name"], "critical",
                      stop["trigger"], stop["explanation"])

    return jsonify({
        "case_id": case_id,
        "enrichment": {
            "overall_risk": report["overall_risk"],
            "summary": report["summary"],
            "identifiers": report["identifiers"],
            "total_elapsed_ms": report["total_elapsed_ms"],
        },
        "augmentation": {
            "changes": augmentation.changes,
            "extra_risk_signals": augmentation.extra_risk_signals,
            "verified_identifiers": augmentation.verified_identifiers,
        },
        "scoring": {
            "composite_score": score_dict["composite_score"],
            "is_hard_stop": score_dict["is_hard_stop"],
            "calibrated": score_dict["calibrated"],
        },
    })


@app.route("/api/screen", methods=["POST"])
@require_auth("screen:run")
def api_screen_vendor():
    body = request.get_json(silent=True) or {}
    vendor_name = body.get("name", "")
    if not vendor_name:
        return jsonify({"error": "Missing 'name' field"}), 400

    # Input validation
    valid, err = validate_vendor_input({"name": vendor_name})
    if not valid:
        return jsonify({"error": err}), 400

    result = screen_name(vendor_name)
    result_dict = {
        "matched": result.matched,
        "best_score": round(result.best_score, 4),
        "matched_name": result.matched_name,
        "matched_entry": {
            "name": result.matched_entry.name,
            "list": result.matched_entry.list_type,
            "program": result.matched_entry.program,
            "country": result.matched_entry.country,
            "source": getattr(result.matched_entry, "source", "hardcoded"),
        } if result.matched_entry else None,
        "all_matches": [
            {"name": m.entry.name, "list": m.entry.list_type,
             "score": round(m.score, 4), "matched_on": m.matched_on,
             "source": getattr(m.entry, "source", "hardcoded")}
            for m in result.all_matches
        ],
        "screening_db": result.db_label,
        "screening_ms": result.screening_ms,
    }

    # Log the screening
    db.log_screening(vendor_name, result_dict)
    log_audit("screening_run", "vendor", vendor_name,
              detail=f"OFAC screen: {'MATCH' if result.matched else 'CLEAR'}")
    return jsonify(result_dict)


@app.route("/api/screenings")
@require_auth("screen:read")
def api_screening_history():
    limit = request.args.get("limit", 50, type=int)
    history = db.get_screening_history(limit)
    return jsonify({"screenings": history})


# ---- Sanctions sync ----

@app.route("/api/sanctions/status")
@require_auth("cases:read")
def api_sanctions_status():
    """Get current sanctions database status."""
    if not HAS_SYNC:
        _, db_label = get_active_db()
        return jsonify({"status": "sync_unavailable", "screening_db": db_label,
                        "message": "sanctions_sync module not available"})
    sanctions_sync.init_sanctions_db()
    status = sanctions_sync.get_sync_status()
    _, db_label = get_active_db()
    return jsonify({"status": "ok", "screening_db": db_label, **status})


@app.route("/api/sanctions/sources")
@require_auth("cases:read")
def api_sanctions_sources():
    """List available sanctions sources."""
    if not HAS_SYNC:
        return jsonify({"sources": {}})
    return jsonify({"sources": {
        k: {"label": v["label"], "format": v["format"]}
        for k, v in sanctions_sync.SOURCES.items()
    }})


@app.route("/api/sanctions/sync", methods=["POST"])
@require_auth("system:config")
def api_sanctions_sync():
    """Trigger a sanctions sync. Body: {"sources": ["ofac","uk"]} or omit for all."""
    if not HAS_SYNC:
        return jsonify({"error": "sanctions_sync module not available"}), 501

    body = request.get_json(silent=True) or {}
    source_keys = body.get("sources", None)
    dry_run = body.get("dry_run", False)

    sanctions_sync.init_sanctions_db()
    results = sanctions_sync.sync_all(source_keys=source_keys, dry_run=dry_run)

    # Invalidate the screening cache so next screen uses fresh data
    invalidate_cache()

    return jsonify({
        "results": [
            {k: v for k, v in r.items() if k != "sample"}
            for r in results
        ],
        "status": sanctions_sync.get_sync_status(),
    })


# ---- Main ----

def _load_demo_data():
    """Load sample vendors for demo/testing purposes."""
    demo_vendors = [
        {"id": "demo-001", "name": "Rosoboronexport", "country": "RU", "date": "2026-03-15",
         "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.20, "shell_layers": 0, "pep_connection": True},
         "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 25},
         "exec": {"known_execs": 2, "adverse_media": 3, "pep_execs": 2, "litigation_history": 0},
         "program": "weapons_system"},
        {"id": "demo-002", "name": "BAE Systems plc", "country": "GB", "date": "2026-03-14",
         "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.99, "shell_layers": 0, "pep_connection": False},
         "data_quality": {"has_lei": True, "has_cage": True, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 60},
         "exec": {"known_execs": 15, "adverse_media": 0, "pep_execs": 0, "litigation_history": 1},
         "program": "weapons_system"},
        {"id": "demo-003", "name": "Caspian Industrial", "country": "AZ", "date": "2026-03-13",
         "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.25, "shell_layers": 3, "pep_connection": True},
         "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 2},
         "exec": {"known_execs": 1, "adverse_media": 3, "pep_execs": 1, "litigation_history": 0},
         "program": "mission_critical"},
    ]
    print("  Loading demo data (3 sample vendors)...")
    for v in demo_vendors:
        _score_and_persist(v["id"], v)


def main():
    parser = argparse.ArgumentParser(description="Xiphos v2.0 API Server")
    parser.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--reset-db", action="store_true", help="Delete and recreate the database")
    parser.add_argument("--demo", action="store_true", help="Load 3 sample vendors for testing")
    parser.add_argument("--sync", action="store_true", help="Sync sanctions lists on startup")
    parser.add_argument("--sync-sources", type=str, default="",
                        help="Comma-separated sanctions sources to sync (default: all)")
    args = parser.parse_args()

    if args.reset_db:
        db_path = db.get_db_path()
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"  Deleted {db_path}")

    print("Initializing database...")
    db.init_db()
    init_auth_db()
    _seed_if_empty()

    if args.demo:
        _load_demo_data()

    # Sanctions sync on startup
    if args.sync and HAS_SYNC:
        sanctions_sync.init_sanctions_db()
        sources = [s.strip() for s in args.sync_sources.split(",") if s.strip()] if args.sync_sources else None
        sanctions_sync.sync_all(source_keys=sources)
    elif HAS_SYNC:
        sanctions_sync.init_sanctions_db()

    # Show active screening DB
    _, sanctions_label = get_active_db()
    print(f"  Sanctions DB: {sanctions_label}")

    # Show OSINT status
    if HAS_OSINT:
        from osint.enrichment import CONNECTORS
        print(f"  OSINT connectors ({len(CONNECTORS)}): {', '.join(n for n, _ in CONNECTORS)}")
    else:
        print("  OSINT: not available (osint package missing)")

    # Initialize knowledge graph
    if HAS_KG:
        kg.init_kg_db()
        print("  Knowledge graph: initialized")

    print(f"  Monitoring: {'enabled' if HAS_MONITOR else 'not available'}")
    print(f"  Dossier gen: {'enabled' if HAS_DOSSIER else 'not available'}")
    print(f"  Auth/RBAC: {'ENFORCED' if AUTH_ENABLED else 'DEV MODE (all requests = admin)'}")

    stats = db.get_stats()
    print(f"\n{'='*50}")
    print(f"  XIPHOS v5.0 -- Intelligence-Grade Vendor Assurance (FGAMLogit DoD Dual-Vertical)")
    print(f"  Persistence: SQLite ({db.get_db_path()})")
    print(f"  Vendors: {stats['vendors']}  Alerts: {stats['unresolved_alerts']}")
    print(f"  http://{args.host}:{args.port}")
    print(f"{'='*50}\n")

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
