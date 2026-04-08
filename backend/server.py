#!/usr/bin/env python3
"""
Xiphos v5.0 API Server

Flask backend with SQLite persistence, JWT authentication, RBAC, and
full audit logging. All scoring runs through the FGAMLogit v5.0 engine
(two-layer DoD/commercial dual-vertical architecture).
OSINT enrichment, entity resolution, queued monitoring, optional
periodic monitoring, and dossier generation.

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
  POST /api/graph/shortest-path          Find shortest path between two entities

Graph Workspace Endpoints:
  POST /api/graph/workspaces             Create a new analyst workspace
  GET  /api/graph/workspaces             List all workspaces (optional creator filter)
  GET  /api/graph/workspaces/:id         Get a specific workspace
  PUT  /api/graph/workspaces/:id         Update a workspace
  DELETE /api/graph/workspaces/:id       Delete a workspace
"""

import os
import json
import uuid
import csv
import io
import time
import logging
import threading
import argparse
import importlib.util
from datetime import datetime, timedelta
from urllib.parse import urlparse

_RUNTIME_ENV_BOOTSTRAP: dict[str, object] = {
    "loaded": False,
    "path": "",
    "available_keys": [],
    "injected_keys": [],
    "paths_checked": [],
}
if __name__ == "__main__" and os.environ.get("XIPHOS_SKIP_RUNTIME_ENV", "").lower() not in {"1", "true", "yes"}:
    try:
        from secure_runtime_env import load_runtime_env as _load_runtime_env

        _RUNTIME_ENV_BOOTSTRAP = _load_runtime_env()
    except Exception as exc:  # pragma: no cover - defensive bootstrap logging
        _RUNTIME_ENV_BOOTSTRAP = {
            "loaded": False,
            "path": "",
            "available_keys": [],
            "injected_keys": [],
            "paths_checked": [],
            "error": str(exc),
        }

from flask import Flask, Response, g, jsonify, request, send_file, stream_with_context

from fgamlogit import (
    score_vendor, VendorInputV5, OwnershipProfile, DataQuality,
    ExecProfile, DoDContext, PROGRAM_TO_SENSITIVITY,
)
from ofac import screen_name, get_active_db, invalidate_cache
import db
from auth import (
    init_auth_db, register_auth_routes, require_auth, log_audit, AUTH_ENABLED, decode_access_ticket
)
from hardening import (
    rate_limit, validate_vendor_input,
    configure_cors, add_security_headers,
)
from runtime_paths import get_data_dir
from blueprint_registry import register_optional_blueprints
from profile_api import profile_bp
from server_graph_routes import register_graph_surface_routes
from server_mission_thread_routes import register_mission_thread_routes
from server_monitor_routes import register_monitor_routes
from server_axiom_routes import register_axiom_routes
from helios_core.mission_briefs import (
    create_or_update_mission_brief,
    get_mission_brief as get_core_mission_brief,
)
from helios_core.room_contract import canonicalize_mission_brief_room
from intake_router import route_intake
import mission_thread_briefing as mission_thread_briefing_module
import mission_threads as mission_threads_module

# Optional: sanctions sync engine (may fail if dependencies missing)
try:
    import sanctions_sync
    HAS_SYNC = True
except ImportError:
    HAS_SYNC = False

# Optional: BIS CSL and person screening modules
HAS_BIS = importlib.util.find_spec("bis_csl") is not None

try:
    from person_screening import (
        screen_person, screen_person_batch, get_case_screenings,
        init_person_screening_db,
    )
    HAS_PERSON_SCREENING = True
except ImportError:
    HAS_PERSON_SCREENING = False

try:
    from person_graph_ingest import ingest_person_screening, ingest_batch_screenings, get_person_network_risk
    HAS_PERSON_GRAPH_INGEST = True
except ImportError:
    HAS_PERSON_GRAPH_INGEST = False

try:
    from graph_analytics import GraphAnalytics
    from graph_runtime import load_cached_graph_analytics
    HAS_GRAPH_ANALYTICS = True
except ImportError:
    HAS_GRAPH_ANALYTICS = False

def _get_graph_analytics():
    return load_cached_graph_analytics(analytics_factory=GraphAnalytics)


try:
    from export_monitor import ExportMonitor
    HAS_EXPORT_MONITOR = True
except ImportError:
    HAS_EXPORT_MONITOR = False

try:
    from transaction_authorization import authorize_transaction
    HAS_TX_AUTH = True
except ImportError:
    HAS_TX_AUTH = False

# Optional: OSINT enrichment engine
try:
    from osint.enrichment import enrich_vendor
    from osint.enrichment import enrich_vendor_streaming
    from osint_scoring import augment_from_enrichment
    from osint_cache import get_enricher
    HAS_OSINT = True
except ImportError:
    HAS_OSINT = False

# Optional: Entity resolution + knowledge graph
try:
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

try:
    from monitor_scheduler import (
        DEFAULT_INTERVAL_HOURS as MONITOR_DEFAULT_INTERVAL_HOURS,
        MonitorScheduler as QueuedMonitorScheduler,
        TIER_INTERVALS as MONITOR_TIER_INTERVALS,
    )
    HAS_MONITOR_SCHEDULER = True
except ImportError:
    HAS_MONITOR_SCHEDULER = False
    MONITOR_DEFAULT_INTERVAL_HOURS = 168
    MONITOR_TIER_INTERVALS = {}

# Optional: Dossier generators (HTML and PDF can fail independently)
try:
    from dossier import generate_dossier
    HAS_DOSSIER = True
except ImportError:
    HAS_DOSSIER = False

try:
    from dossier_pdf import generate_pdf_dossier
    HAS_DOSSIER_PDF = True
except ImportError:
    HAS_DOSSIER_PDF = False

# Optional: AI analysis module
try:
    from ai_analysis import (
        analyze_vendor,
        delete_ai_config as delete_ai_config_row,
        get_ai_config as get_ai_config_row,
        get_available_providers,
        get_latest_analysis,
        init_ai_tables,
        save_ai_config as save_ai_config_row,
    )
    HAS_AI = True
except ImportError:
    HAS_AI = False

try:
    from event_extraction import compute_report_hash, extract_case_events
    from intel_summary import generate_intel_summary
    HAS_INTEL = True
except ImportError:
    HAS_INTEL = False

try:
    from storyline import build_case_storyline
    HAS_STORYLINE = True
except ImportError:
    HAS_STORYLINE = False

try:
    from export_authorization_rules import build_export_authorization_guidance
    HAS_EXPORT_RULES = True
except ImportError:
    HAS_EXPORT_RULES = False

try:
    from graph_aware_authorization import build_graph_aware_guidance
    HAS_GRAPH_AWARE_AUTH = True
except ImportError:
    HAS_GRAPH_AWARE_AUTH = False

try:
    from export_evidence import (
        apply_export_risk_overlay,
        build_export_gate_overlay,
        get_export_evidence_summary,
    )
    HAS_EXPORT_EVIDENCE = True
except ImportError:
    HAS_EXPORT_EVIDENCE = False

try:
    from workflow_control_summary import build_workflow_control_summary
    HAS_WORKFLOW_CONTROL = True
except ImportError:
    HAS_WORKFLOW_CONTROL = False

try:
    from supplier_passport import build_supplier_passport
    HAS_SUPPLIER_PASSPORT = True
except ImportError:
    HAS_SUPPLIER_PASSPORT = False

try:
    from ai_control_plane import (
        build_case_assistant_plan,
        prepare_case_assistant_execution,
        prepare_case_assistant_feedback,
    )
    HAS_AI_CONTROL_PLANE = True
except ImportError:
    HAS_AI_CONTROL_PLANE = False

try:
    from export_ai_challenge import build_hybrid_export_review
    HAS_EXPORT_AI_CHALLENGE = True
except ImportError:
    HAS_EXPORT_AI_CHALLENGE = False

try:
    from supply_chain_assurance_ai_challenge import build_hybrid_assurance_review
    HAS_SUPPLY_CHAIN_ASSURANCE_AI = True
except ImportError:
    HAS_SUPPLY_CHAIN_ASSURANCE_AI = False

try:
    from artifact_vault import get_artifact_record, list_case_artifacts, read_artifact_bytes
    HAS_ARTIFACT_VAULT = True
except ImportError:
    HAS_ARTIFACT_VAULT = False

try:
    from foci_artifact_intake import ingest_foci_artifact, SUPPORTED_FOCI_ARTIFACT_TYPES
    HAS_FOCI_ARTIFACTS = HAS_ARTIFACT_VAULT
except ImportError:
    HAS_FOCI_ARTIFACTS = False

try:
    from foci_evidence import build_foci_gate_overlay, get_latest_foci_summary
    HAS_FOCI_SUMMARY = True
except ImportError:
    HAS_FOCI_SUMMARY = False

try:
    from cyber_evidence import (
        apply_cmmc_readiness_overlay,
        build_cmmc_gate_overlay,
        get_latest_cyber_evidence_summary,
    )
    HAS_CYBER_EVIDENCE = True
except ImportError:
    HAS_CYBER_EVIDENCE = False

try:
    from export_artifact_intake import ingest_export_artifact, SUPPORTED_EXPORT_ARTIFACT_TYPES
    HAS_EXPORT_ARTIFACTS = HAS_ARTIFACT_VAULT
except ImportError:
    HAS_EXPORT_ARTIFACTS = False

try:
    from sprs_import_intake import ingest_sprs_export, SPRS_ARTIFACT_TYPE
    HAS_SPRS_IMPORT = HAS_ARTIFACT_VAULT
except ImportError:
    HAS_SPRS_IMPORT = False

try:
    from oscal_intake import ingest_oscal_artifact
    HAS_OSCAL_INTAKE = HAS_ARTIFACT_VAULT
except ImportError:
    HAS_OSCAL_INTAKE = False

try:
    from nvd_overlay import create_nvd_overlay_artifact, NVD_OVERLAY_ARTIFACT_TYPE
    HAS_NVD_OVERLAY = HAS_ARTIFACT_VAULT
except ImportError:
    HAS_NVD_OVERLAY = False

# Optional: Cyber graph ingest (CVE/KEV to knowledge graph)
try:
    from cyber_graph_ingest import ingest_cve_findings, build_cyber_subgraph
    HAS_CYBER_GRAPH = True
except ImportError:
    HAS_CYBER_GRAPH = False

# Optional: Cyber risk scoring engine
try:
    from cyber_risk_scoring import score_vendor_cyber_risk
    HAS_CYBER_SCORING = True
except ImportError:
    HAS_CYBER_SCORING = False

# Optional: Network risk propagation engine
try:
    from network_risk import compute_network_risk, compute_portfolio_network_risk
    HAS_NETWORK_RISK = True
except ImportError:
    HAS_NETWORK_RISK = False

# Layer 1: Regulatory Gate Engine (DoD compliance)
try:
    from regulatory_gates import (
        evaluate_regulatory_gates, quick_screen,
        RegulatoryGateInput,
        FOCIInput, CFIUSInput, CMMCInput, ITARInput, EARInput,
        DeemedExportGateInput, USMLControlGateInput,
    )
    HAS_GATES = True
except ImportError:
    HAS_GATES = False

# --------------- Sentry error tracking ---------------
import sentry_sdk

_SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if _SENTRY_DSN:
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        traces_sample_rate=0.2,
        profiles_sample_rate=0.1,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
    )

# Static folder for serving the bundled frontend
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload
configure_cors(app)
add_security_headers(app)
app.register_blueprint(profile_bp)

register_optional_blueprints(app, logging.getLogger("xiphos"))

_LOG_LEVEL = os.environ.get("XIPHOS_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _LOG_LEVEL, logging.INFO), format="%(message)s")
LOGGER = logging.getLogger("xiphos")
_monitor_scheduler_instance = None
_monitor_scheduler_started = False


def _log_event(event: str, **fields):
    payload = {"event": event, **fields}
    LOGGER.info(json.dumps(payload, default=str, sort_keys=True))


def _get_monitor_scheduler():
    """Return a lazily initialized scheduler for queued monitoring work."""
    global _monitor_scheduler_instance
    if _monitor_scheduler_instance is None and HAS_MONITOR_SCHEDULER:
        interval_hours = int(os.environ.get("XIPHOS_MONITOR_INTERVAL_HOURS", "168"))
        _monitor_scheduler_instance = QueuedMonitorScheduler(interval_hours=interval_hours)
    return _monitor_scheduler_instance


def _maybe_start_periodic_monitoring() -> bool:
    """Start the background scheduler when the runtime explicitly enables it."""
    global _monitor_scheduler_started
    if _monitor_scheduler_started:
        return True
    if not HAS_MONITOR_SCHEDULER:
        return False
    if os.environ.get("XIPHOS_ENABLE_PERIODIC_MONITORING", "false").lower() != "true":
        return False

    scheduler = _get_monitor_scheduler()
    if not scheduler:
        return False
    if not scheduler.running:
        scheduler.start()
    _monitor_scheduler_started = True
    _log_event("monitor_scheduler_started", interval_hours=scheduler.interval_hours)
    return True


def _serialize_monitor_status(sweep_id: str, status: dict, vendor_id: str | None = None) -> dict:
    """Normalize sweep status payloads for API responses."""
    payload = {
        "sweep_id": sweep_id,
        "status": status.get("status", "unknown"),
        "triggered_at": status.get("triggered_at"),
        "started_at": status.get("started_at"),
        "completed_at": status.get("completed_at"),
        "total_vendors": status.get("total_vendors"),
        "processed": status.get("processed"),
        "risk_changes": status.get("risk_changes"),
        "new_alerts": status.get("new_alerts"),
    }
    if vendor_id:
        payload["vendor_id"] = vendor_id
        if payload["status"] == "completed":
            latest_history = db.get_monitoring_history(vendor_id, limit=1)
            latest_score = db.get_latest_score(vendor_id)
            payload["latest_check"] = latest_history[0] if latest_history else None
            if latest_score:
                payload["latest_score"] = {
                    "composite_score": latest_score.get("composite_score"),
                    "tier": latest_score.get("calibrated", {}).get("calibrated_tier"),
                }
    return payload


def _parse_iso_timestamp(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _monitor_interval_hours_for_case(case_id: str) -> int:
    latest_score = db.get_latest_score(case_id) or {}
    tier = ((latest_score.get("calibrated") or {}).get("calibrated_tier") or "").strip()
    return int(MONITOR_TIER_INTERVALS.get(tier, MONITOR_DEFAULT_INTERVAL_HOURS))


def _next_monitor_scheduled_at(case_id: str, checked_at_value):
    checked_at = _parse_iso_timestamp(checked_at_value)
    if not checked_at:
        return None
    return (checked_at + timedelta(hours=_monitor_interval_hours_for_case(case_id))).isoformat()


def _fallback_monitor_delta_summary(entry: dict) -> str:
    previous_risk = str(entry.get("previous_risk") or "").strip()
    current_risk = str(entry.get("current_risk") or "").strip()
    score_before = entry.get("score_before")
    score_after = entry.get("score_after")
    new_findings_count = int(entry.get("new_findings_count") or 0)
    resolved_findings_count = int(entry.get("resolved_findings_count") or 0)
    parts: list[str] = []
    if score_before is not None and score_after is not None:
        delta = float(score_after or 0.0) - float(score_before or 0.0)
        if abs(delta) >= 0.01:
            parts.append(f"Score {'increased' if delta > 0 else 'decreased'} {delta:+.1f}%")
    if previous_risk and current_risk and previous_risk != current_risk:
        parts.append(f"Tier {previous_risk} -> {current_risk}")
    if new_findings_count > 0:
        parts.append(f"{new_findings_count} new finding{'s' if new_findings_count != 1 else ''}")
    if resolved_findings_count > 0:
        parts.append(f"{resolved_findings_count} resolved finding{'s' if resolved_findings_count != 1 else ''}")
    sources_triggered = entry.get("sources_triggered") or []
    if sources_triggered:
        if len(sources_triggered) <= 2:
            parts.append(f"Sources triggered: {', '.join(str(item) for item in sources_triggered)}")
        else:
            parts.append(f"{len(sources_triggered)} sources triggered")
    return ", ".join(parts) if parts else "No material delta detected"


def _serialize_monitor_run(entry: dict) -> dict:
    run_id = str(entry.get("run_id") or "").strip() or f"monitor-log-{entry.get('id')}"
    checked_at = entry.get("checked_at")
    return {
        "run_id": run_id,
        "vendor_id": entry.get("vendor_id"),
        "vendor_name": entry.get("vendor_name"),
        "started_at": entry.get("started_at") or checked_at,
        "completed_at": entry.get("completed_at") or checked_at,
        "status": entry.get("status") or "completed",
        "change_type": entry.get("change_type") or "no_change",
        "delta_summary": entry.get("delta_summary") or _fallback_monitor_delta_summary(entry),
        "score_before": entry.get("score_before"),
        "score_after": entry.get("score_after"),
        "new_findings_count": int(entry.get("new_findings_count") or 0),
        "resolved_findings_count": int(entry.get("resolved_findings_count") or 0),
        "sources_triggered": list(entry.get("sources_triggered") or []),
        "checked_at": checked_at,
    }


def _parse_since_hours(raw_since: str | None) -> int | None:
    text = str(raw_since or "").strip().lower()
    if not text:
        return None
    if text.endswith("h") and text[:-1].isdigit():
        return int(text[:-1])
    if text.endswith("d") and text[:-1].isdigit():
        return int(text[:-1]) * 24
    if text.isdigit():
        return int(text)
    return None


def _augment_connector_status(case_id: str, report: dict) -> dict:
    connector_status = report.get("connector_status")
    if not isinstance(connector_status, dict):
        return report
    enriched_at = report.get("enriched_at")
    next_scheduled_at = _next_monitor_scheduled_at(case_id, enriched_at)
    augmented = dict(report)
    augmented["connector_status"] = {
        str(name): {
            **dict(status),
            "last_checked_at": dict(status).get("last_checked_at") or enriched_at,
            "next_scheduled_at": dict(status).get("next_scheduled_at") or next_scheduled_at,
        }
        for name, status in connector_status.items()
        if isinstance(status, dict)
    }
    return augmented


@app.before_request
def _request_context():
    g.request_id = request.headers.get("X-Request-Id", f"req-{uuid.uuid4().hex[:12]}")
    g.request_started_at = time.perf_counter()


@app.after_request
def _log_request(response):
    request_id = getattr(g, "request_id", "")
    started_at = getattr(g, "request_started_at", None)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2) if started_at else None
    response.headers["X-Request-Id"] = request_id
    _log_event(
        "http_request",
        request_id=request_id,
        method=request.method,
        path=request.path,
        status=response.status_code,
        duration_ms=duration_ms,
        remote_addr=request.remote_addr,
    )
    return response

# Register auth routes immediately (available regardless of main() startup)
register_auth_routes(app)


@app.route("/")
def serve_frontend():
    """Serve the single-file dashboard."""
    index = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index):
        return send_file(index)
    # Fallback: try the frontend build output if it exists.
    alt = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist", "index.html")
    if os.path.exists(alt):
        return send_file(alt)
    return jsonify({"error": "Frontend not found. Build the frontend into backend/static or frontend/dist."}), 404


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
        named_beneficial_owner_known=o.get("named_beneficial_owner_known", False),
        controlling_parent_known=o.get("controlling_parent_known", False),
        owner_class_known=o.get("owner_class_known", False),
        owner_class=o.get("owner_class", ""),
        ownership_pct_resolved=o.get("ownership_pct_resolved", 0.0),
        control_resolution_pct=o.get("control_resolution_pct", 0.0),
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
    profile_id = _normalize_profile_id(v.get("profile", "defense_acquisition"))
    default_program = _default_program_for_profile(profile_id)
    default_sensitivity = PROGRAM_TO_SENSITIVITY.get(
        program,
        PROGRAM_TO_SENSITIVITY.get(default_program, "COMMERCIAL"),
    )

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
    try:
        from profiles import get_legacy_profile_name

        compliance_profile = get_legacy_profile_name(profile_id)
    except Exception:
        compliance_profile = "DEFENSE_ACQUISITION"

    return VendorInputV5(
        name=v["name"], country=v["country"],
        ownership=ownership, data_quality=dq, exec_profile=ep, dod=dod,
        compliance_profile=compliance_profile,
    )


def _score_to_api_dict(result) -> dict:
    """Format ScoringResultV5 into the JSON shape the frontend expects."""
    return {
        "calibrated_probability": result.calibrated_probability,
        "calibrated_tier": result.calibrated_tier,
        "combined_tier": result.combined_tier,
        "display_tier": getattr(result, "display_tier", result.calibrated_tier),
        "interval": {
            "lower": result.interval_lower,
            "upper": result.interval_upper,
            "coverage": result.interval_coverage,
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
        "policy": result.policy_metadata,
        "screening": {
            "matched": result.screening.matched,
            "best_score": result.screening.best_score,
            "best_raw_jw": result.screening.best_raw_jw,
            "matched_name": result.screening.matched_name,
            "db_label": result.screening.db_label,
            "screening_ms": result.screening.screening_ms,
            "match_details": result.screening.match_details,
            "policy_basis": result.screening.policy_basis,
        },
        # Decision Engine (v5.1): alert classification with audit trail
        "alert_disposition": {
            "category": result.alert_disposition.category,
            "confidence_band": result.alert_disposition.confidence_band,
            "recommended_action": result.alert_disposition.recommended_action,
            "override_risk_weight": result.alert_disposition.override_risk_weight,
            "explanation": result.alert_disposition.explanation,
        } if result.alert_disposition else None,
    }


def _ownership_profile_to_dict(ownership: OwnershipProfile | None) -> dict:
    profile = ownership if isinstance(ownership, OwnershipProfile) else OwnershipProfile()
    return {
        "publicly_traded": bool(profile.publicly_traded),
        "state_owned": bool(profile.state_owned),
        "beneficial_owner_known": bool(profile.beneficial_owner_known),
        "named_beneficial_owner_known": bool(profile.named_beneficial_owner_known),
        "controlling_parent_known": bool(profile.controlling_parent_known),
        "owner_class_known": bool(profile.owner_class_known),
        "owner_class": str(profile.owner_class or ""),
        "ownership_pct_resolved": float(profile.ownership_pct_resolved or 0.0),
        "control_resolution_pct": float(profile.control_resolution_pct or 0.0),
        "shell_layers": int(profile.shell_layers or 0),
        "pep_connection": bool(profile.pep_connection),
        "foreign_ownership_pct": float(profile.foreign_ownership_pct or 0.0),
        "foreign_ownership_is_allied": bool(profile.foreign_ownership_is_allied),
    }


def _full_score_dict(result, ownership: OwnershipProfile | None = None) -> dict:
    # composite_score: probabilistic risk as 0-100 for legacy frontend display
    composite_score = round(result.calibrated_probability * 100)
    is_hard_stop = result.combined_tier.startswith("TIER_1") or result.calibrated_tier.startswith("TIER_1")
    return {
        "composite_score": composite_score,
        "is_hard_stop": is_hard_stop,
        "calibrated": _score_to_api_dict(result),
        "ownership": _ownership_profile_to_dict(ownership),
    }


PROFILE_DEFAULT_PROGRAMS = {
    "defense_acquisition": "dod_unclassified",
    "itar_trade_compliance": "regulated_commercial",
    "university_research_security": "federal_non_dod",
    "grants_compliance": "federal_non_dod",
    "commercial_supply_chain": "commercial",
}


def _normalize_profile_id(profile_id: str | None) -> str:
    try:
        from profiles import normalize_profile_id

        return normalize_profile_id(profile_id) or "defense_acquisition"
    except Exception:
        raw = str(profile_id or "").strip()
        return raw or "defense_acquisition"


def _current_user_id() -> str:
    return g.user.get("sub", "system") if getattr(g, "user", None) else "system"


def _current_user_email() -> str:
    return g.user.get("email", "") if getattr(g, "user", None) else ""


def _current_user_role() -> str:
    return g.user.get("role", "system") if getattr(g, "user", None) else "system"


def _truncate_text(value, limit: int = 240) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _sanitize_mission_brief_value(value, *, depth: int = 0):
    if depth > 2 or value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = _truncate_text(value, 320)
        return text or None
    if isinstance(value, list):
        items = []
        for item in value[:12]:
            sanitized = _sanitize_mission_brief_value(item, depth=depth + 1)
            if sanitized not in (None, "", [], {}):
                items.append(sanitized)
        return items
    if isinstance(value, dict):
        sanitized_dict = {}
        for key, item in list(value.items())[:16]:
            sanitized_key = _truncate_text(key, 64)
            if not sanitized_key:
                continue
            sanitized_value = _sanitize_mission_brief_value(item, depth=depth + 1)
            if sanitized_value not in (None, "", [], {}):
                sanitized_dict[sanitized_key] = sanitized_value
        return sanitized_dict
    return None


def _normalize_mission_brief_payload(body: dict) -> dict:
    room = canonicalize_mission_brief_room(body.get("room"))
    object_type = _truncate_text(body.get("object_type"), 24).lower() or None
    engagement_type = _truncate_text(body.get("engagement_type"), 64).lower() or None
    collection_depth = _truncate_text(body.get("collection_depth") or "full_picture", 64).lower() or "full_picture"
    timeline = _truncate_text(body.get("timeline"), 80) or None
    status = _truncate_text(body.get("status") or "scoped", 40).lower() or "scoped"
    question_count = body.get("question_count") if isinstance(body.get("question_count"), int) else 0
    confidence_score = body.get("confidence_score") if isinstance(body.get("confidence_score"), (int, float)) else 0.0
    primary_targets = _sanitize_mission_brief_value(body.get("primary_targets")) or {}
    known_context = _sanitize_mission_brief_value(body.get("known_context")) or {}
    priority_requirements = _sanitize_mission_brief_value(body.get("priority_requirements")) or []
    authorized_tiers = _sanitize_mission_brief_value(body.get("authorized_tiers")) or []
    notes = _sanitize_mission_brief_value(body.get("notes")) or []
    summary = _truncate_text(body.get("summary"), 320) or None
    case_id = _truncate_text(body.get("case_id"), 64) or None

    if not isinstance(primary_targets, dict):
        primary_targets = {}
    if not isinstance(known_context, dict):
        known_context = {}
    if not isinstance(priority_requirements, list):
        priority_requirements = []
    if not isinstance(authorized_tiers, list):
        authorized_tiers = []
    if not isinstance(notes, list):
        notes = []

    return {
        "room": room,
        "case_id": case_id,
        "object_type": object_type,
        "engagement_type": engagement_type,
        "collection_depth": collection_depth,
        "timeline": timeline,
        "status": status,
        "question_count": max(0, min(question_count, 8)),
        "confidence_score": max(0.0, min(float(confidence_score), 1.0)),
        "primary_targets": primary_targets,
        "known_context": known_context,
        "priority_requirements": [str(item)[:120] for item in priority_requirements[:8]],
        "authorized_tiers": [str(item)[:80] for item in authorized_tiers[:8]],
        "summary": summary,
        "notes": [str(item)[:200] for item in notes[:8]],
    }


def _analysis_job_row_to_dict(row) -> dict | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "created_by": row["created_by"],
        "input_hash": row["input_hash"],
        "status": row["status"],
        "analysis_id": row["analysis_id"],
        "error": row["error"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }


def _serialize_artifact_record(record: dict | None) -> dict | None:
    if not record:
        return None
    return {
        "id": record.get("id"),
        "case_id": record.get("case_id"),
        "artifact_type": record.get("artifact_type"),
        "source_system": record.get("source_system"),
        "source_class": record.get("source_class"),
        "authority_level": record.get("authority_level"),
        "access_model": record.get("access_model"),
        "uploaded_by": record.get("uploaded_by"),
        "filename": record.get("filename"),
        "content_type": record.get("content_type"),
        "size_bytes": record.get("size_bytes"),
        "retention_class": record.get("retention_class"),
        "sensitivity": record.get("sensitivity"),
        "effective_date": record.get("effective_date"),
        "parse_status": record.get("parse_status"),
        "created_at": record.get("created_at"),
        "structured_fields": record.get("structured_fields") or {},
    }


def _serialize_export_artifact(record: dict | None) -> dict | None:
    return _serialize_artifact_record(record)


def _latest_case_artifact(case_id: str, *, source_system: str) -> dict | None:
    if not HAS_ARTIFACT_VAULT:
        return None
    for record in list_case_artifacts(case_id, limit=20):
        if record.get("source_system") == source_system:
            return record
    return None


def _workflow_lane_for_vendor(vendor: dict) -> str:
    vendor_input = vendor.get("vendor_input", {}) if isinstance(vendor.get("vendor_input"), dict) else {}
    case_id = str(vendor.get("id") or "")
    profile = _normalize_profile_id(vendor_input.get("profile", vendor.get("profile", "")))

    has_export_lane = (
        isinstance(vendor_input.get("export_authorization"), dict)
        or profile in {"itar_trade_compliance", "trade_compliance"}
        or bool(case_id and _latest_case_artifact(case_id, source_system="export_artifact_upload"))
    )
    if has_export_lane:
        return "export"

    has_cyber_lane = (
        profile in {"supplier_cyber_trust", "cmmc_supplier_review"}
        or bool(case_id and _latest_case_artifact(case_id, source_system="sprs_import"))
        or bool(case_id and _latest_case_artifact(case_id, source_system="oscal_upload"))
        or bool(case_id and _latest_case_artifact(case_id, source_system="nvd_overlay"))
    )
    if has_cyber_lane:
        return "cyber"

    return "counterparty"


ENRICHMENT_CONNECTOR_EXCLUDES_BY_LANE: dict[str, tuple[str, ...]] = {
    "export": (
        "cisa_kev",
        "mitre_attack_fixture",
        "cisa_advisory_fixture",
        "cyclonedx_spdx_vex_fixture",
        "public_assurance_evidence_fixture",
        "osv_dev",
        "deps_dev",
        "openssf_scorecard",
        "epa_echo",
        "osha_safety",
        "fdic_bankfind",
    ),
    "cyber": (
        "fara",
        "sec_xbrl",
        "sam_subaward_reporting",
        "usaspending",
        "fpds_contracts",
        "epa_echo",
        "osha_safety",
        "courtlistener",
        "recap_courts",
        "fdic_bankfind",
    ),
}


def _default_enrichment_connectors(vendor: dict) -> list[str]:
    try:
        from osint.connector_registry import ACTIVE_CONNECTOR_ORDER
    except Exception:
        return []

    lane = _workflow_lane_for_vendor(vendor)
    excluded = set(ENRICHMENT_CONNECTOR_EXCLUDES_BY_LANE.get(lane, ()))
    return [name for name in ACTIVE_CONNECTOR_ORDER if name not in excluded]


def _resolve_enrichment_connectors(vendor: dict, requested_connectors) -> list[str] | None:
    if requested_connectors:
        return list(requested_connectors)
    return _default_enrichment_connectors(vendor)


def _intel_summary_job_row_to_dict(row) -> dict | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "created_by": row["created_by"],
        "report_hash": row["report_hash"],
        "status": row["status"],
        "summary_id": row["summary_id"],
        "error": row["error"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }


def _current_enrichment_report(case_id: str) -> dict | None:
    report = db.get_latest_enrichment(case_id)
    if report and HAS_INTEL and not report.get("report_hash"):
        report["report_hash"] = compute_report_hash(report)
    return report


def _seed_payload_from_report(report: dict | None) -> dict[str, dict]:
    identifiers = report.get("identifiers") if isinstance(report, dict) else {}
    identifier_sources = report.get("identifier_sources") if isinstance(report, dict) else {}
    connector_status = report.get("connector_status") if isinstance(report, dict) else {}
    return {
        "identifiers": dict(identifiers) if isinstance(identifiers, dict) else {},
        "identifier_sources": dict(identifier_sources) if isinstance(identifier_sources, dict) else {},
        "connector_status": dict(connector_status) if isinstance(connector_status, dict) else {},
    }


def _explicit_case_seed_metadata(vendor: dict | None) -> dict[str, object]:
    if not isinstance(vendor, dict):
        return {}
    seed_metadata: dict[str, object] = {}
    if isinstance(vendor.get("seed_metadata"), dict):
        seed_metadata.update(vendor["seed_metadata"])
    vendor_input = vendor.get("vendor_input") if isinstance(vendor.get("vendor_input"), dict) else {}
    nested_seed_metadata = vendor_input.get("seed_metadata") if isinstance(vendor_input.get("seed_metadata"), dict) else {}
    seed_metadata.update(nested_seed_metadata)
    return {
        str(key): value
        for key, value in seed_metadata.items()
        if not str(key).startswith("__") and value not in (None, "", [])
    }


def _apply_explicit_seed_overrides(
    seed_payload: dict[str, dict],
    explicit_seed_metadata: dict[str, object],
) -> dict[str, dict]:
    if not explicit_seed_metadata:
        return seed_payload

    merged_identifiers = dict(seed_payload.get("identifiers") or {})
    merged_sources = {
        str(key): list(values)
        for key, values in (seed_payload.get("identifier_sources") or {}).items()
        if isinstance(values, list)
    }

    for key, value in explicit_seed_metadata.items():
        existing = merged_identifiers.get(key)
        if existing != value:
            merged_identifiers[key] = value
            merged_sources.pop(str(key), None)
        elif key not in merged_identifiers:
            merged_identifiers[key] = value

    return {
        "identifiers": merged_identifiers,
        "identifier_sources": merged_sources,
        "connector_status": dict(seed_payload.get("connector_status") or {}),
    }


def _merge_seed_payload(primary: dict[str, dict], secondary: dict[str, dict]) -> dict[str, dict]:
    merged_identifiers = dict(primary.get("identifiers") or {})
    merged_sources = {
        str(key): list(values)
        for key, values in (primary.get("identifier_sources") or {}).items()
        if isinstance(values, list)
    }
    merged_status = dict(primary.get("connector_status") or {})

    for key, value in (secondary.get("identifiers") or {}).items():
        if str(key).startswith("__") or value in (None, "", []):
            continue
        if merged_identifiers.get(key) in (None, "", []):
            merged_identifiers[key] = value
        if merged_identifiers.get(key) == value:
            for source in secondary.get("identifier_sources", {}).get(key, []) or []:
                merged_sources.setdefault(str(key), [])
                if source not in merged_sources[str(key)]:
                    merged_sources[str(key)].append(source)

    for connector_name, status in (secondary.get("connector_status") or {}).items():
        merged_status.setdefault(connector_name, status)

    return {
        "identifiers": merged_identifiers,
        "identifier_sources": merged_sources,
        "connector_status": merged_status,
    }


def _enrichment_seed_identifiers(case_id: str) -> dict:
    report = db.get_latest_enrichment(case_id)
    seed_payload = _seed_payload_from_report(report)

    vendor = db.get_vendor(case_id)
    if vendor:
        explicit_seed_metadata = _explicit_case_seed_metadata(vendor)
        peer_report = db.get_latest_peer_enrichment(vendor.get("name", ""), exclude_vendor_id=case_id)
        if peer_report:
            seed_payload = _merge_seed_payload(seed_payload, _seed_payload_from_report(peer_report))
        seed_payload = _apply_explicit_seed_overrides(seed_payload, explicit_seed_metadata)

    seed_ids = dict(seed_payload.get("identifiers") or {})
    latest_nvd_overlay = _latest_case_artifact(case_id, source_system="nvd_overlay")
    nvd_structured = (latest_nvd_overlay or {}).get("structured_fields") or {}
    product_terms = [
        str(term).strip()
        for term in (nvd_structured.get("product_terms") or [])
        if str(term).strip()
    ]
    if product_terms and not seed_ids.get("product_terms"):
        seed_ids["product_terms"] = product_terms
    website = seed_ids.get("website") or seed_ids.get("official_website")
    if isinstance(website, str) and website.strip() and not seed_ids.get("domain"):
        parsed = urlparse(website if "://" in website else f"https://{website}")
        if parsed.netloc:
            seed_ids["domain"] = parsed.netloc
    if seed_payload.get("identifier_sources"):
        seed_ids["__seed_identifier_sources"] = seed_payload["identifier_sources"]
    if seed_payload.get("connector_status"):
        seed_ids["__seed_connector_status"] = seed_payload["connector_status"]
    return seed_ids


def _current_intel_report_hash(case_id: str) -> str:
    report = _current_enrichment_report(case_id)
    if not report or not HAS_INTEL:
        return ""
    return report.get("report_hash") or compute_report_hash(report)


def _build_case_storyline_payload(case_id: str, vendor: dict, score: dict | None, network_risk: dict | None = None) -> dict | None:
    if not HAS_STORYLINE or not isinstance(score, dict):
        return None

    report = None
    events: list[dict] = []
    intel_summary = None

    if HAS_INTEL:
        report = _current_enrichment_report(case_id)
        if report:
            report_hash = report.get("report_hash") or compute_report_hash(report)
            report["report_hash"] = report_hash
            events = db.get_case_events(case_id, report_hash)
            if not events:
                events = _persist_case_events(case_id, vendor, report)
            intel_summary = db.get_latest_intel_summary(
                case_id,
                user_id=_current_user_id(),
                report_hash=report_hash,
            )

    foci_summary = get_latest_foci_summary(case_id) if HAS_FOCI_SUMMARY else None
    cyber_summary = get_latest_cyber_evidence_summary(case_id) if HAS_CYBER_EVIDENCE else None
    vendor_input = vendor.get("vendor_input", {}) if isinstance(vendor.get("vendor_input"), dict) else {}
    export_summary = (
        get_export_evidence_summary(case_id, vendor_input.get("export_authorization"))
        if HAS_EXPORT_EVIDENCE else None
    )

    try:
        return build_case_storyline(
            case_id,
            vendor,
            score,
            report=report,
            events=events,
            intel_summary=intel_summary,
            network_risk=network_risk,
            foci_summary=foci_summary,
            cyber_summary=cyber_summary,
            export_summary=export_summary,
        )
    except Exception as err:
        LOGGER.debug("Storyline generation skipped for %s: %s", case_id, err)
        return None


def _merge_case_events(base_events: list[dict], ai_events: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {
        (event.get("finding_id", ""), event.get("event_type", "")): event
        for event in base_events
        if event.get("finding_id") and event.get("event_type")
    }
    for event in ai_events:
        key = (event.get("finding_id", ""), event.get("event_type", ""))
        if not key[0] or not key[1]:
            continue
        merged[key] = {**merged.get(key, {}), **event}
    combined = list(merged.values())
    combined.sort(key=lambda event: (event.get("status") != "active", -float(event.get("confidence") or 0.0), event.get("event_type", "")))
    return combined


def _persist_case_events(case_id: str, vendor: dict, report: dict, ai_events: list[dict] | None = None) -> list[dict]:
    if not HAS_INTEL or not report:
        return []
    report_hash = report.get("report_hash") or compute_report_hash(report)
    report["report_hash"] = report_hash
    deterministic_events = extract_case_events(case_id, vendor.get("name", "Vendor"), report)
    events = _merge_case_events(deterministic_events, ai_events or [])
    try:
        db.replace_case_events(case_id, report_hash, events)
    except Exception as e:
        # Degrade gracefully on DB write failures (e.g. sequence desync)
        # Events are still returned for the current response; they just won't be persisted
        app.logger.warning(f"Failed to persist case events for {case_id}: {type(e).__name__}: {e}")
    return events


def _persist_osint_alerts(case_id: str, vendor_name: str, report: dict) -> None:
    if not report:
        return
    for finding in report.get("findings", []):
        if finding.get("severity") in ("critical", "high"):
            db.save_alert(
                case_id,
                vendor_name,
                finding["severity"],
                f"[OSINT] {finding.get('title', 'Finding')}",
                finding.get("detail", ""),
            )


def _ingest_case_graph(case_id: str, vendor: dict, report: dict) -> dict | None:
    if not HAS_KG or not report:
        return None
    try:
        from graph_ingest import ingest_enrichment_to_graph

        graph_stats = ingest_enrichment_to_graph(
            case_id,
            vendor.get("name", ""),
            report,
            vendor_input=vendor.get("vendor_input") if isinstance(vendor.get("vendor_input"), dict) else {},
        )
        LOGGER.info("Graph ingest for %s: %s", case_id, graph_stats)
        return graph_stats
    except Exception as err:
        LOGGER.debug("Graph ingest skipped for %s: %s", case_id, err)
        return None


def _queue_neo4j_incremental_sync(since_timestamp: str, *, metadata: dict | None = None) -> dict | None:
    try:
        from neo4j_integration import is_neo4j_available
        from neo4j_sync_scheduler import get_neo4j_sync_scheduler

        if not is_neo4j_available():
            return {"status": "unavailable"}

        job = get_neo4j_sync_scheduler().queue_incremental_sync(
            since_timestamp,
            metadata=metadata or {"requested_via": "persist_enrichment_artifacts"},
        )
        return {
            "status": job.get("status") or "queued",
            "job_id": job.get("job_id"),
            "status_url": f"/api/neo4j/sync/{job.get('job_id')}" if job.get("job_id") else None,
            "reused_existing_job": bool(job.get("reused_existing_job")),
        }
    except Exception as err:
        LOGGER.debug("Neo4j incremental sync skipped: %s", err)
        return {"status": "failed", "error": str(err)}


def _persist_enrichment_artifacts(case_id: str, vendor: dict, report: dict) -> dict:
    if not report:
        return {"events": [], "graph": None}

    sync_since = datetime.utcnow().isoformat() + "Z"
    db.save_enrichment(case_id, report)
    events = _persist_case_events(case_id, vendor, report) if HAS_INTEL else []
    graph_stats = _ingest_case_graph(case_id, vendor, report)
    _persist_osint_alerts(case_id, vendor.get("name", ""), report)

    # Cyber graph ingest: feed KEV/CVE findings into the knowledge graph
    cyber_graph_stats = None
    if HAS_CYBER_GRAPH and report:
        try:
            findings = []
            for source_key, source_data in report.items():
                if isinstance(source_data, dict):
                    findings.extend(source_data.get("findings", []))
            if findings:
                cyber_graph_stats = ingest_cve_findings(case_id, vendor.get("name", ""), findings)
                LOGGER.info("Cyber graph ingest for %s: %s", case_id, cyber_graph_stats)
        except Exception as err:
            LOGGER.debug("Cyber graph ingest skipped for %s: %s", case_id, err)

    neo4j_sync = None
    if graph_stats or cyber_graph_stats:
        neo4j_sync = _queue_neo4j_incremental_sync(
            sync_since,
            metadata={"requested_via": "persist_enrichment_artifacts", "case_id": case_id},
        )

    return {
        "events": events,
        "graph": graph_stats,
        "cyber_graph": cyber_graph_stats,
        "neo4j_sync": neo4j_sync,
    }


def enqueue_intel_summary_job(case_id: str, user_id: str, report_hash: str) -> dict:
    with db.get_conn() as conn:
        existing = conn.execute(
            """
            SELECT * FROM intel_summary_jobs
            WHERE case_id = ? AND created_by = ? AND report_hash = ? AND status IN ('pending', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (case_id, user_id, report_hash),
        ).fetchone()
        if existing:
            return {"created": False, "job": _intel_summary_job_row_to_dict(existing)}

        job_id = f"intel-job-{uuid.uuid4().hex[:10]}"
        conn.execute(
            """
            INSERT INTO intel_summary_jobs (id, case_id, created_by, report_hash, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (job_id, case_id, user_id, report_hash),
        )
        row = conn.execute("SELECT * FROM intel_summary_jobs WHERE id = ?", (job_id,)).fetchone()
    return {"created": True, "job": _intel_summary_job_row_to_dict(row)}


def update_intel_summary_job(job_id: str, **kwargs) -> None:
    allowed = {"status", "summary_id", "error", "started_at", "completed_at"}
    updates = {key: value for key, value in kwargs.items() if key in allowed}
    if not updates:
        return

    now = datetime.utcnow().isoformat() + "Z"
    if updates.get("status") == "running" and "started_at" not in updates:
        updates["started_at"] = now
    if updates.get("status") in {"completed", "failed"} and "completed_at" not in updates:
        updates["completed_at"] = now

    assignments = ", ".join(f"{field} = ?" for field in updates)
    with db.get_conn() as conn:
        conn.execute(
            f"UPDATE intel_summary_jobs SET {assignments} WHERE id = ?",
            (*updates.values(), job_id),
        )


def _run_intel_summary_job(job_id: str, case_id: str, user_id: str) -> None:
    update_intel_summary_job(job_id, status="running")

    vendor = db.get_vendor(case_id)
    report = _current_enrichment_report(case_id)
    if not vendor:
        update_intel_summary_job(job_id, status="failed", error="Case not found")
        return
    if not report:
        update_intel_summary_job(job_id, status="failed", error="Run enrichment before generating an intel summary")
        return

    report_hash = report.get("report_hash") or compute_report_hash(report)
    base_events = db.get_case_events(case_id, report_hash)
    if not base_events:
        base_events = _persist_case_events(case_id, vendor, report)

    try:
        result = generate_intel_summary(user_id, vendor, report, base_events)
    except Exception as err:
        update_intel_summary_job(job_id, status="failed", error=str(err)[:500])
        return

    merged_events = _merge_case_events(base_events, result.get("normalized_events") or [])
    db.replace_case_events(case_id, report_hash, merged_events)

    summary_id = db.save_intel_summary(
        case_id=case_id,
        user_id=user_id,
        report_hash=report_hash,
        summary={
            **result.get("summary", {}),
            "normalized_event_count": len(merged_events),
        },
        provider=result.get("provider", ""),
        model=result.get("model", ""),
        prompt_tokens=result.get("prompt_tokens", 0),
        completion_tokens=result.get("completion_tokens", 0),
        elapsed_ms=result.get("elapsed_ms", 0),
        prompt_version=result.get("prompt_version", ""),
    )
    update_intel_summary_job(job_id, status="completed", summary_id=summary_id)


def _ensure_ai_job_tables() -> None:
    if HAS_AI:
        init_ai_tables()


def _current_analysis_input_hash(case_id: str) -> str:
    if not HAS_AI:
        return ""
    vendor = db.get_vendor(case_id)
    score = db.get_latest_score(case_id)
    if not vendor or not score:
        return ""
    enrichment = db.get_latest_enrichment(case_id)
    try:
        from ai_analysis import compute_analysis_fingerprint

        return compute_analysis_fingerprint(vendor, score, enrichment)
    except Exception:
        return ""


_AI_WARMUP_WAIT_SECONDS = float(os.environ.get("XIPHOS_AI_WARMUP_WAIT_SECONDS", "6"))
_AI_STATUS_WAIT_SECONDS = float(os.environ.get("XIPHOS_AI_STATUS_WAIT_SECONDS", "8"))
_AI_TRANSIENT_RETRY_DELAYS = tuple(
    float(part.strip())
    for part in os.environ.get("XIPHOS_AI_TRANSIENT_RETRY_DELAYS", "1,3,8").split(",")
    if part.strip()
)


def enqueue_analysis_job(case_id: str, user_id: str, input_hash: str) -> dict:
    _ensure_ai_job_tables()
    with db.get_conn() as conn:
        existing = conn.execute(
            """
            SELECT * FROM ai_analysis_jobs
            WHERE case_id = ? AND created_by = ? AND input_hash = ? AND status IN ('pending', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (case_id, user_id, input_hash),
        ).fetchone()
        if existing:
            return {"created": False, "job": _analysis_job_row_to_dict(existing)}

        job_id = f"ai-job-{uuid.uuid4().hex[:10]}"
        conn.execute(
            """
            INSERT INTO ai_analysis_jobs (id, case_id, created_by, input_hash, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (job_id, case_id, user_id, input_hash),
        )
        row = conn.execute("SELECT * FROM ai_analysis_jobs WHERE id = ?", (job_id,)).fetchone()
    return {"created": True, "job": _analysis_job_row_to_dict(row)}


def update_analysis_job(job_id: str, **kwargs) -> None:
    _ensure_ai_job_tables()
    allowed = {"status", "analysis_id", "error", "started_at", "completed_at"}
    updates = {key: value for key, value in kwargs.items() if key in allowed}
    if not updates:
        return

    now = datetime.utcnow().isoformat() + "Z"
    if updates.get("status") == "running" and "started_at" not in updates:
        updates["started_at"] = now
    if updates.get("status") in {"completed", "failed"} and "completed_at" not in updates:
        updates["completed_at"] = now

    assignments = ", ".join(f"{field} = ?" for field in updates)
    with db.get_conn() as conn:
        conn.execute(
            f"UPDATE ai_analysis_jobs SET {assignments} WHERE id = ?",
            (*updates.values(), job_id),
        )


def _run_ai_analysis_job(job_id: str, case_id: str, user_id: str) -> None:
    from ai_analysis import AIProviderTemporaryError

    update_analysis_job(job_id, status="running")

    vendor = db.get_vendor(case_id)
    score = db.get_latest_score(case_id)
    enrichment = db.get_latest_enrichment(case_id)

    if not vendor:
        update_analysis_job(job_id, status="failed", error="Case not found")
        return
    if not score:
        update_analysis_job(job_id, status="failed", error="Case must be scored before AI analysis")
        return

    attempt = 0
    while True:
        attempt += 1
        try:
            result = analyze_vendor(user_id, vendor, score, enrichment)
            break
        except AIProviderTemporaryError as err:
            retry_index = attempt - 1
            if retry_index >= len(_AI_TRANSIENT_RETRY_DELAYS):
                update_analysis_job(job_id, status="failed", error=str(err)[:500])
                return
            delay = max(_AI_TRANSIENT_RETRY_DELAYS[retry_index], 0.0)
            update_analysis_job(
                job_id,
                status="running",
                error=f"Transient AI provider failure, retry {attempt}/{len(_AI_TRANSIENT_RETRY_DELAYS) + 1}: {str(err)[:420]}",
            )
            time.sleep(delay)
        except Exception as err:
            update_analysis_job(job_id, status="failed", error=str(err)[:500])
            return

    update_analysis_job(job_id, status="completed", analysis_id=result.get("analysis_id"))


def _wait_for_primed_ai_analysis(
    case_id: str,
    user_id: str,
    input_hash: str,
    job_id: str,
    get_latest_analysis_fn,
    *,
    wait_seconds: float,
    poll_seconds: float,
) -> dict | None:
    if wait_seconds <= 0:
        return None

    deadline = time.monotonic() + wait_seconds
    while True:
        cached = get_latest_analysis_fn(case_id, user_id=user_id, input_hash=input_hash)
        if cached:
            return {
                "status": "ready",
                "job_id": job_id,
                "analysis_id": cached.get("id"),
                "input_hash": input_hash,
            }

        _ensure_ai_job_tables()
        with db.get_conn() as conn:
            row = conn.execute("SELECT * FROM ai_analysis_jobs WHERE id = ?", (job_id,)).fetchone()
        if row:
            job = _analysis_job_row_to_dict(row)
            if job.get("status") == "failed":
                return {
                    "status": "failed",
                    "job_id": job_id,
                    "analysis_id": job.get("analysis_id"),
                    "input_hash": input_hash,
                    "error": job.get("error"),
                }

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(max(poll_seconds, 0.0), remaining))


def _prime_ai_analysis_for_case(
    case_id: str,
    user_id: str,
    *,
    wait_seconds: float | None = None,
    poll_seconds: float = 0.25,
) -> dict:
    """Warm the AI narrative for a case after enrichment/rescore with a short bounded ready wait."""
    if not HAS_AI or not user_id:
        return {"status": "disabled"}

    vendor = db.get_vendor(case_id)
    score = db.get_latest_score(case_id)
    if not vendor or not score:
        return {"status": "skipped", "reason": "missing_case_or_score"}

    try:
        from ai_analysis import get_latest_analysis
    except ImportError:
        return {"status": "disabled"}

    input_hash = _current_analysis_input_hash(case_id)
    if not input_hash:
        return {"status": "skipped", "reason": "missing_input_hash"}

    try:
        cached = get_latest_analysis(case_id, user_id=user_id, input_hash=input_hash)
        if cached:
            return {
                "status": "ready",
                "job_id": None,
                "analysis_id": cached.get("id"),
                "input_hash": input_hash,
            }

        payload = enqueue_analysis_job(case_id, user_id, input_hash)
        job = payload["job"]
        if payload["created"]:
            worker = threading.Thread(target=_run_ai_analysis_job, args=(job["id"], case_id, user_id), daemon=True)
            worker.start()
        warmed = _wait_for_primed_ai_analysis(
            case_id,
            user_id,
            input_hash,
            job["id"],
            get_latest_analysis,
            wait_seconds=_AI_WARMUP_WAIT_SECONDS if wait_seconds is None else max(wait_seconds, 0.0),
            poll_seconds=poll_seconds,
        )
        if warmed:
            return warmed
        return {
            "status": job["status"],
            "job_id": job["id"],
            "analysis_id": job.get("analysis_id"),
            "input_hash": input_hash,
        }
    except Exception as err:
        LOGGER.debug("AI warm-up skipped for %s: %s", case_id, err)
        return {"status": "skipped", "reason": "warmup_failed"}


def _default_program_for_profile(profile_id: str) -> str:
    return PROFILE_DEFAULT_PROGRAMS.get(_normalize_profile_id(profile_id), "commercial")


def _score_vendor_result(v: dict, source_reliability_avg: float = 0.0, case_id: str | None = None):
    """Score a vendor through the canonical two-layer pipeline without persisting side effects."""
    inp = _build_vendor_input(v)
    cyber_summary = None
    export_summary = None
    if case_id and HAS_CYBER_EVIDENCE:
        cyber_summary = get_latest_cyber_evidence_summary(case_id)
        if cyber_summary:
            inp.dod.cmmc_readiness = apply_cmmc_readiness_overlay(
                cyber_summary,
                current_score=inp.dod.cmmc_readiness,
            )
    if case_id and HAS_EXPORT_EVIDENCE:
        export_case_input = None
        vendor_input = v.get("vendor_input", {}) if isinstance(v.get("vendor_input"), dict) else {}
        if isinstance(vendor_input, dict) and isinstance(vendor_input.get("export_authorization"), dict):
            export_case_input = vendor_input.get("export_authorization")
        elif isinstance(v.get("export_authorization"), dict):
            export_case_input = v.get("export_authorization")
        export_summary = get_export_evidence_summary(case_id, export_case_input)
        if export_summary:
            export_overlay = apply_export_risk_overlay(
                export_summary,
                current_itar=inp.dod.itar_exposure,
                current_ear=inp.dod.ear_control_status,
            )
            inp.dod.itar_exposure = export_overlay["itar_exposure"]
            inp.dod.ear_control_status = export_overlay["ear_control_status"]

    reg_status, reg_findings, gate_proximity = _run_regulatory_gates(
        v,
        inp.dod.sensitivity,
        inp.dod.supply_chain_tier,
        case_id=case_id,
        cyber_summary=cyber_summary,
        export_summary=export_summary,
    )
    inp.dod.regulatory_gate_proximity = gate_proximity

    extra_stops = list(v.get("extra_hard_stops", []))
    result = score_vendor(
        inp,
        regulatory_status=reg_status,
        regulatory_findings=reg_findings,
        extra_hard_stops=extra_stops,
        source_reliability_avg=source_reliability_avg,
    )
    return result, _full_score_dict(result, inp.ownership)


def _build_augmented_vendor_input(vendor_input: dict, report: dict) -> tuple[dict, float, object]:
    """Apply canonical enrichment augmentation and return the updated scoring payload."""
    base_input = _build_vendor_input(vendor_input)
    augmentation = augment_from_enrichment(base_input, report)
    aug_vi = augmentation.vendor_input

    updated_input = {
        **vendor_input,
        "ownership": {
            "publicly_traded": aug_vi.ownership.publicly_traded,
            "state_owned": aug_vi.ownership.state_owned,
            "beneficial_owner_known": aug_vi.ownership.beneficial_owner_known,
            "named_beneficial_owner_known": aug_vi.ownership.named_beneficial_owner_known,
            "controlling_parent_known": aug_vi.ownership.controlling_parent_known,
            "owner_class_known": aug_vi.ownership.owner_class_known,
            "owner_class": aug_vi.ownership.owner_class,
            "ownership_pct_resolved": aug_vi.ownership.ownership_pct_resolved,
            "control_resolution_pct": aug_vi.ownership.control_resolution_pct,
            "shell_layers": aug_vi.ownership.shell_layers,
            "pep_connection": aug_vi.ownership.pep_connection,
            "foreign_ownership_pct": aug_vi.ownership.foreign_ownership_pct,
            "foreign_ownership_is_allied": aug_vi.ownership.foreign_ownership_is_allied,
        },
        "data_quality": {
            "has_lei": aug_vi.data_quality.has_lei,
            "has_cage": aug_vi.data_quality.has_cage,
            "has_duns": aug_vi.data_quality.has_duns,
            "has_tax_id": aug_vi.data_quality.has_tax_id,
            "has_audited_financials": aug_vi.data_quality.has_audited_financials,
            "years_of_records": aug_vi.data_quality.years_of_records,
        },
        "exec": {
            "known_execs": aug_vi.exec_profile.known_execs,
            "adverse_media": aug_vi.exec_profile.adverse_media,
            "pep_execs": aug_vi.exec_profile.pep_execs,
            "litigation_history": aug_vi.exec_profile.litigation_history,
        },
    }

    updated_input = _apply_extra_risk_signals(updated_input, augmentation.extra_risk_signals)

    reliabilities = [
        src.get("reliability", 0.6)
        for factor_sources in augmentation.provenance.values()
        for src in factor_sources
    ]
    avg_reliability = sum(reliabilities) / len(reliabilities) if reliabilities else 0.0
    return updated_input, avg_reliability, augmentation


def _canonical_rescore_from_enrichment(case_id: str, vendor: dict, report: dict) -> dict:
    """Re-score a case using the canonical enrichment augmentation path."""
    vendor_input = dict(vendor.get("vendor_input") or {})
    vendor_input.setdefault("name", vendor.get("name", ""))
    vendor_input.setdefault("country", vendor.get("country", ""))
    vendor_input.setdefault("program", vendor.get("program", "standard_industrial"))
    vendor_input["profile"] = _normalize_profile_id(vendor_input.get("profile", vendor.get("profile", "defense_acquisition")))

    updated_input, avg_reliability, augmentation = _build_augmented_vendor_input(vendor_input, report)
    score_dict = _score_and_persist(case_id, updated_input, source_reliability_avg=avg_reliability)
    return {
        "score_dict": score_dict,
        "augmentation": augmentation,
        "updated_input": updated_input,
        "source_reliability_avg": avg_reliability,
    }


def _batch_summary(items: list[dict]) -> dict:
    completed_items = [item for item in items if item.get("status") == "completed"]
    tier_distribution: dict[str, int] = {}
    total_findings = 0
    posterior_sum = 0.0

    for item in completed_items:
        tier = item.get("tier")
        if tier:
            tier_distribution[tier] = tier_distribution.get(tier, 0) + 1
        total_findings += item.get("findings_count") or 0
        posterior_sum += item.get("posterior") or 0.0

    return {
        "completed": len(completed_items),
        "tier_distribution": tier_distribution,
        "total_findings": total_findings,
        "avg_posterior": posterior_sum / len(completed_items) if completed_items else 0.0,
    }


def _serialize_batch(batch: dict) -> dict:
    total = batch.get("total_vendors") or 0
    processed = batch.get("processed") or 0
    items = batch.get("items", [])
    return {
        "id": batch["id"],
        "batch_id": batch["id"],
        "filename": batch["filename"],
        "uploaded_by": batch.get("uploaded_by", ""),
        "uploaded_by_email": batch.get("uploaded_by_email", ""),
        "status": batch.get("status", "pending"),
        "total_vendors": total,
        "processed": processed,
        "completion_pct": round((processed / total) * 100) if total else 0,
        "created_at": batch.get("created_at"),
        "completed_at": batch.get("completed_at"),
        "items": items,
        "summary": _batch_summary(items),
    }


def _api_key_hint(api_key: str) -> str:
    if not api_key:
        return ""
    return f"...{api_key[-4:]}"


def _run_regulatory_gates(
    v: dict,
    sensitivity: str,
    tier: int,
    case_id: str | None = None,
    cyber_summary: dict | None = None,
    export_summary: dict | None = None,
) -> tuple:
    """
    Run Layer 1 regulatory gates if available and sensitivity is DoD-relevant.
    Returns (regulatory_status, regulatory_findings, gate_proximity_score).
    """
    if not HAS_GATES:
        return ("NOT_EVALUATED", [], 0.0)
    if sensitivity in ("COMMERCIAL", "STANDARD"):
        return ("NOT_EVALUATED", [], 0.0)

    name = v.get("name", "")
    country = v.get("country", "US")
    ownership = v.get("ownership", {})
    program = v.get("program", "standard_industrial")
    explicit_dod = v.get("dod", {}) if isinstance(v.get("dod"), dict) else {}

    # Quick screen: Section 889 + NDAA 1260H name-based checks
    quick_screen(
        entity_name=name,
        parent_companies=ownership.get("parent_companies", []),
        entity_country=country,
    )

    # Build full gate input with available ownership and program data
    gate_inp = RegulatoryGateInput(
        entity_name=name,
        entity_country=country,
        sensitivity=sensitivity,
        supply_chain_tier=tier,
    )

    # Populate FOCI with foreign ownership data
    foreign_ownership_pct = float(ownership.get("foreign_ownership_pct", 0.0) or 0.0)
    gate_inp.foci = FOCIInput(
        entity_foreign_ownership_pct=foreign_ownership_pct,
        sensitivity=sensitivity,
    )
    if case_id and HAS_FOCI_SUMMARY:
        foci_summary = get_latest_foci_summary(case_id)
        gate_overlay = build_foci_gate_overlay(
            foci_summary,
            base_foreign_ownership_pct=foreign_ownership_pct,
        )
        for key, value in gate_overlay.items():
            setattr(gate_inp.foci, key, value)

    # Populate CFIUS with basic foreign involvement data
    effective_foreign_ownership_pct = float(gate_inp.foci.entity_foreign_ownership_pct or 0.0)
    if effective_foreign_ownership_pct > 0:
        # Mark as transaction involving foreign party if foreign ownership detected
        gate_inp.cfius = CFIUSInput(
            transaction_involves_foreign_acquirer=True,
            foreign_acquirer_country=gate_inp.foci.foreign_controlling_country or (country if country != "US" else ""),
        )
        # Add critical tech/infrastructure flags based on program type
        if "defense" in program.lower() or "dod" in program.lower():
            gate_inp.cfius.business_involves_critical_technology = True

    if cyber_summary:
        cmmc_overlay = build_cmmc_gate_overlay(
            cyber_summary,
            profile=str(v.get("profile", "") or ""),
            program=str(program or ""),
            explicit_required_level=int(explicit_dod.get("required_cmmc_level") or 0),
        )
        if cmmc_overlay:
            gate_inp.cmmc = CMMCInput(
                handles_cui=bool(cmmc_overlay.get("handles_cui")),
                required_cmmc_level=int(cmmc_overlay.get("required_cmmc_level") or 0),
                current_cmmc_level=int(cmmc_overlay.get("current_cmmc_level") or 0),
                entity_has_active_poam=bool(cmmc_overlay.get("entity_has_active_poam")),
                assessment_date=str(cmmc_overlay.get("assessment_date") or ""),
            )

    if export_summary:
        gate_inp.enabled_gates = list(range(1, 14))
        export_overlay = build_export_gate_overlay(
            export_summary,
            profile=str(v.get("profile", "") or ""),
            program=str(program or ""),
            foreign_ownership_pct=float(gate_inp.foci.entity_foreign_ownership_pct or 0.0),
            foci_status=str(gate_inp.foci.entity_foci_mitigation_status or "NOT_APPLICABLE"),
            cmmc_level=int(gate_inp.cmmc.current_cmmc_level or 0),
        )
        itar_overlay = export_overlay.get("itar") or {}
        if itar_overlay:
            gate_inp.itar = ITARInput(
                item_is_itar_controlled=bool(itar_overlay.get("item_is_itar_controlled")),
                entity_foreign_ownership_pct=float(itar_overlay.get("entity_foreign_ownership_pct") or 0.0),
                entity_nationality_of_control=str(itar_overlay.get("entity_nationality_of_control") or "US"),
                entity_has_itar_compliance_certification=bool(itar_overlay.get("entity_has_itar_compliance_certification")),
                entity_manufacturing_process_certified=bool(itar_overlay.get("entity_manufacturing_process_certified")),
                entity_has_approved_voting_agreement=bool(itar_overlay.get("entity_has_approved_voting_agreement")),
                entity_foci_status=str(itar_overlay.get("entity_foci_status") or "NOT_APPLICABLE"),
                entity_cmmc_level=int(itar_overlay.get("entity_cmmc_level") or 0),
                supply_chain_tier=tier,
                sensitivity=sensitivity,
            )
        ear_overlay = export_overlay.get("ear") or {}
        if ear_overlay:
            gate_inp.ear = EARInput(
                item_ear_ccl_category=str(ear_overlay.get("item_ear_ccl_category") or ""),
                entity_foreign_origin_content_pct=float(ear_overlay.get("entity_foreign_origin_content_pct") or 0.0),
                entity_has_export_control_procedures=bool(ear_overlay.get("entity_has_export_control_procedures")),
                entity_has_export_control_document_package=bool(ear_overlay.get("entity_has_export_control_document_package")),
                entity_export_control_deemed_export_training_current=bool(ear_overlay.get("entity_export_control_deemed_export_training_current")),
            )
        deemed_overlay = export_overlay.get("deemed_export") or {}
        if deemed_overlay:
            gate_inp.deemed_export = DeemedExportGateInput(
                foreign_nationals=list(deemed_overlay.get("foreign_nationals") or []),
                tcp_status=str(deemed_overlay.get("tcp_status") or "NOT_REQUIRED"),
                usml_category=int(deemed_overlay.get("usml_category") or 0),
                facility_clearance=str(deemed_overlay.get("facility_clearance") or "UNCLASSIFIED"),
            )
        usml_overlay = export_overlay.get("usml_control") or {}
        if usml_overlay:
            gate_inp.usml_control = USMLControlGateInput(
                usml_category=int(usml_overlay.get("usml_category") or 0),
                vendor_country=str(usml_overlay.get("vendor_country") or "US"),
            )

    assessment = evaluate_regulatory_gates(gate_inp)

    # Convert gate results to serializable findings
    findings = []
    for gate_result in assessment.failed_gates + assessment.pending_gates:
        findings.append({
            "gate": gate_result.gate_id,
            "name": gate_result.gate_name,
            "status": gate_result.state.value,
            "severity": gate_result.severity,
            "explanation": gate_result.details,
            "regulation": gate_result.regulation,
            "remediation": gate_result.mitigation,
            "confidence": gate_result.confidence,
        })

    return (assessment.status.value, findings, assessment.gate_proximity_score)


def _score_and_persist(vendor_id: str, v: dict, source_reliability_avg: float = 0.0) -> dict:
    """Score a vendor through full two-layer pipeline and persist."""
    result, score_dict = _score_vendor_result(v, source_reliability_avg=source_reliability_avg, case_id=vendor_id)

    # Persist vendor
    db.upsert_vendor(
        vendor_id,
        v["name"],
        v["country"],
        v.get("program", "standard_industrial"),
        v,
        profile=v.get("profile", "defense_acquisition"),
    )

    # Persist score
    db.save_score(vendor_id, score_dict)

    # Persist alerts from hard stops and flags (batched)
    alert_batch = []
    for stop in result.hard_stop_decisions:
        alert_batch.append({
            "vendor_id": vendor_id, "entity_name": v["name"], "severity": "critical",
            "title": stop["trigger"], "description": stop["explanation"],
        })
    for flag in result.soft_flags:
        sev = "high" if flag["confidence"] > 0.7 else "medium"
        alert_batch.append({
            "vendor_id": vendor_id, "entity_name": v["name"], "severity": sev,
            "title": flag["trigger"], "description": flag["explanation"],
        })
    if alert_batch:
        db.save_alerts_batch(alert_batch)

    return score_dict


def _apply_extra_risk_signals(updated_input: dict, extra_signals: list) -> dict:
    """
    Process extra_risk_signals from OSINT augmentation and apply them to the scoring input.

    Signals are categorized by scoring_impact:
    - sanctions_raw_override: Signals that should override sanctions factor
    - hard_stop_candidate: Signals that should trigger hard stops
    - data_quality_penalty: Signals that lower data quality confidence
    - ownership_risk_increase: Signals that increase ownership risk
    """
    if not extra_signals:
        return updated_input

    # Ensure nested dicts exist
    if "dod" not in updated_input:
        updated_input["dod"] = {}
    if "ownership" not in updated_input:
        updated_input["ownership"] = {}
    if "data_quality" not in updated_input:
        updated_input["data_quality"] = {}

    for signal in extra_signals:
        impact = signal.get("scoring_impact", "")

        if impact == "sanctions_raw_override":
            # CSL/UN sanctions match: promote to hard stop (categorical prohibition)
            if "extra_hard_stops" not in updated_input:
                updated_input["extra_hard_stops"] = []
            updated_input["extra_hard_stops"].append({
                "trigger": f"OSINT Sanctions Match ({signal.get('source', 'unknown')})",
                "explanation": signal.get("detail", "Sanctions list match detected via OSINT"),
                "confidence": 0.95,
            })

        elif impact == "hard_stop_candidate":
            # SAM exclusion, World Bank debarment, etc.
            if "extra_hard_stops" not in updated_input:
                updated_input["extra_hard_stops"] = []
            updated_input["extra_hard_stops"].append({
                "trigger": signal.get("detail", signal.get("signal", "OSINT Signal")),
                "explanation": f"OSINT {signal.get('source', 'unknown')}: {signal.get('detail', signal.get('signal', ''))}",
                "confidence": 0.95 if signal.get("severity") == "critical" else 0.85,
            })

        elif impact == "data_quality_penalty":
            # Degrade data quality fields that _build_vendor_input actually reads
            # Remove verified identifiers to increase data_quality risk score
            penalty = 0.3 if signal.get("severity") == "critical" else 0.1
            if penalty >= 0.2:
                updated_input["data_quality"]["has_audited_financials"] = False
            if penalty >= 0.3:
                updated_input["data_quality"]["has_lei"] = False

        elif impact == "ownership_risk_increase":
            # Increase ownership opacity via fields _build_vendor_input reads
            updated_input["ownership"]["beneficial_owner_known"] = False
            current_resolved = updated_input["ownership"].get("ownership_pct_resolved", 0.5)
            updated_input["ownership"]["ownership_pct_resolved"] = max(0.0, current_resolved - 0.2)

    return updated_input


def _build_minimal_vendor_input(
    vendor_id: str,
    name: str,
    country: str,
    program: str,
    profile: str,
) -> dict:
    return {
        "id": vendor_id,
        "name": name,
        "country": country,
        "ownership": {
            "publicly_traded": False,
            "state_owned": False,
            "beneficial_owner_known": False,
            "ownership_pct_resolved": 0,
            "shell_layers": 0,
            "pep_connection": False,
        },
        "data_quality": {
            "has_lei": False,
            "has_cage": False,
            "has_duns": False,
            "has_tax_id": False,
            "has_audited_financials": False,
            "years_of_records": 0,
        },
        "exec": {
            "known_execs": 0,
            "adverse_media": 0,
            "pep_execs": 0,
            "litigation_history": 0,
        },
        "program": program,
        "profile": profile,
    }


def _process_batch_async(batch_id: str, rows: list[dict], default_program: str, default_profile: str):
    db.update_batch_progress(batch_id, 0, "processing")
    processed = 0
    completed = 0

    for row in rows:
        item_id = row["item_id"]
        name = row["name"]
        country = row["country"]
        program = row.get("program") or default_program
        profile = row.get("profile") or default_profile

        try:
            vendor_id = f"c-{uuid.uuid4().hex[:8]}"
            vendor_input = _build_minimal_vendor_input(vendor_id, name, country, program, profile)
            score_dict = _score_and_persist(vendor_id, vendor_input)
            calibrated = score_dict.get("calibrated", {})
            findings_count = len(calibrated.get("hard_stop_decisions", [])) + len(calibrated.get("soft_flags", []))
            db.update_batch_item(
                item_id,
                case_id=vendor_id,
                tier=calibrated.get("calibrated_tier"),
                posterior=calibrated.get("calibrated_probability"),
                findings_count=findings_count,
                status="completed",
            )
            completed += 1
        except Exception as err:
            db.update_batch_item(
                item_id,
                status="failed",
                error=str(err)[:500],
            )

        processed += 1
        db.update_batch_progress(batch_id, processed, "processing")

    if completed == len(rows):
        db.complete_batch(batch_id)
    elif completed == 0:
        db.fail_batch(batch_id)
    else:
        db.complete_batch(batch_id)


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

register_graph_surface_routes(
    app=app,
    require_auth=require_auth,
    db=db,
    has_kg=HAS_KG,
    kg_module=kg if HAS_KG else None,
    current_enrichment_report=_current_enrichment_report,
    ingest_case_graph=_ingest_case_graph,
)

register_monitor_routes(
    app=app,
    require_auth=require_auth,
    db=db,
    monitor_available=lambda: HAS_MONITOR,
    monitor_scheduler_available=lambda: HAS_MONITOR_SCHEDULER,
    vendor_monitor_cls_provider=lambda: VendorMonitor if HAS_MONITOR else None,
    monitor_scheduler_provider=lambda: _get_monitor_scheduler(),
    serialize_monitor_status=_serialize_monitor_status,
    serialize_monitor_run=_serialize_monitor_run,
    parse_since_hours=_parse_since_hours,
)

register_axiom_routes(
    app=app,
    require_auth=require_auth,
    db=db,
)

register_mission_thread_routes(
    app=app,
    require_auth=require_auth,
    mission_threads_module=mission_threads_module,
    mission_thread_briefing_module=mission_thread_briefing_module,
    log_audit=log_audit,
    current_user_email_provider=_current_user_email,
    current_user_id_provider=_current_user_id,
)

@app.route("/api/health")
@require_auth("health:read")
def health():
    stats = db.get_stats()
    _, db_label = get_active_db()
    dev_mode = os.environ.get("XIPHOS_DEV_MODE", "false").lower() == "true"
    login_required = AUTH_ENABLED or not dev_mode

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
        # Merge enrichment-level cache stats
        try:
            from osint.cache import get_cache
            ecache = get_cache()
            cache_stats.update({
                "enrichment_cache": ecache.stats,
            })
        except Exception:
            pass

    # Build connector health with reliability weights
    connector_health = []
    if HAS_OSINT:
        from osint_scoring import SOURCE_RELIABILITY, DEFAULT_RELIABILITY
        for name in osint_connectors:
            connector_health.append({
                "name": name,
                "reliability": SOURCE_RELIABILITY.get(name, DEFAULT_RELIABILITY),
                "status": "active",
            })

    return jsonify({
        "status": "ok",
        "version": "5.2.0",
        "auth_enabled": AUTH_ENABLED,
        "dev_mode": dev_mode,
        "login_required": login_required,
        "engine": "fgamlogit-dod-dual-vertical",
        "persistence": os.environ.get("HELIOS_DB_ENGINE", "sqlite"),
        "sanctions_db": db_label,
        "sanctions_sync": sanctions_status,
        "osint_enabled": HAS_OSINT,
        "osint_connectors": osint_connectors,
        "osint_connector_count": len(osint_connectors),
        "osint_connector_health": connector_health,
        "osint_cache": cache_stats,
        "stats": stats,
    })


@app.route("/api/mission-briefs", methods=["POST"])
@rate_limit(max_requests=120, window_seconds=60)
@require_auth("cases:read")
def api_create_mission_brief():
    body = request.get_json(silent=True) or {}
    payload = _normalize_mission_brief_payload(body)
    if not payload["primary_targets"] and not payload["summary"]:
        return jsonify({"error": "Mission brief needs a target or summary"}), 400
    if payload["case_id"] and not db.get_vendor(payload["case_id"]):
        return jsonify({"error": "Case not found for mission brief linkage"}), 400

    brief_id = _truncate_text(body.get("id"), 64) or f"mb-{uuid.uuid4().hex[:10]}"
    brief = create_or_update_mission_brief(
        brief_id,
        created_by=_current_user_id(),
        created_by_email=_current_user_email(),
        created_by_role=_current_user_role(),
        **payload,
    )
    status_code = 200 if body.get("id") else 201
    return jsonify({"mission_brief": brief}), status_code


@app.route("/api/mission-briefs/<brief_id>", methods=["GET"])
@rate_limit(max_requests=240, window_seconds=60)
@require_auth("cases:read")
def api_get_mission_brief(brief_id):
    brief = get_core_mission_brief(brief_id)
    if not brief:
        return jsonify({"error": "Mission brief not found"}), 404
    return jsonify({"mission_brief": brief})


@app.route("/api/mission-briefs/<brief_id>", methods=["PUT"])
@rate_limit(max_requests=120, window_seconds=60)
@require_auth("cases:read")
def api_update_mission_brief(brief_id):
    if not get_core_mission_brief(brief_id):
        return jsonify({"error": "Mission brief not found"}), 404

    body = request.get_json(silent=True) or {}
    payload = _normalize_mission_brief_payload(body)
    if payload["case_id"] and not db.get_vendor(payload["case_id"]):
        return jsonify({"error": "Case not found for mission brief linkage"}), 400
    brief = create_or_update_mission_brief(
        brief_id,
        created_by=_current_user_id(),
        created_by_email=_current_user_email(),
        created_by_role=_current_user_role(),
        **payload,
    )
    return jsonify({"mission_brief": brief})


@app.route("/api/ai/providers")
@require_auth("ai:config")
def api_ai_providers():
    if not HAS_AI:
        return jsonify({"error": "AI analysis module not available"}), 501
    return jsonify({"providers": get_available_providers()})


@app.route("/api/ai/config", methods=["GET"])
@require_auth("ai:config")
def api_get_ai_config():
    if not HAS_AI:
        return jsonify({"error": "AI analysis module not available"}), 501

    try:
        config = get_ai_config_row(_current_user_id())
    except RuntimeError as err:
        return jsonify({"error": str(err)}), 503
    if not config:
        return jsonify({"configured": False})

    return jsonify({
        "configured": True,
        "provider": config["provider"],
        "model": config["model"],
        "api_key_hint": _api_key_hint(config["api_key"]),
    })


@app.route("/api/ai/config", methods=["POST"])
@require_auth("ai:config")
def api_save_ai_config():
    if not HAS_AI:
        return jsonify({"error": "AI analysis module not available"}), 501

    body = request.get_json(silent=True) or {}
    provider = body.get("provider", "").strip()
    model = body.get("model", "").strip()
    api_key = body.get("api_key", "").strip()
    user_id = _current_user_id()

    if api_key == "UNCHANGED":
        try:
            existing = get_ai_config_row(user_id)
        except RuntimeError as err:
            return jsonify({"error": str(err)}), 503
        if not existing:
            return jsonify({"error": "No existing API key on file"}), 400
        api_key = existing["api_key"]

    if not provider or not model or not api_key:
        return jsonify({"error": "provider, model, and api_key are required"}), 400

    try:
        save_ai_config_row(user_id, provider, model, api_key)
        log_audit("ai_config_saved", "ai_config", user_id, detail=f"{provider}/{model}")
        return jsonify({"status": "saved"})
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    except RuntimeError as err:
        return jsonify({"error": str(err)}), 503


@app.route("/api/ai/config", methods=["DELETE"])
@require_auth("ai:config")
def api_delete_ai_config():
    if not HAS_AI:
        return jsonify({"error": "AI analysis module not available"}), 501

    deleted = delete_ai_config_row(_current_user_id())
    if deleted:
        log_audit("ai_config_deleted", "ai_config", _current_user_id())
    return jsonify({"status": "deleted" if deleted else "not_found"})


@app.route("/api/ai/config/org-default", methods=["POST"])
@require_auth("system:config")
def api_save_org_ai_config():
    if not HAS_AI:
        return jsonify({"error": "AI analysis module not available"}), 501

    body = request.get_json(silent=True) or {}
    provider = body.get("provider", "").strip()
    model = body.get("model", "").strip()
    api_key = body.get("api_key", "").strip()

    if api_key == "UNCHANGED":
        try:
            existing = get_ai_config_row("__org_default__")
        except RuntimeError as err:
            return jsonify({"error": str(err)}), 503
        if not existing:
            return jsonify({"error": "No existing organization default key on file"}), 400
        api_key = existing["api_key"]

    if not provider or not model or not api_key:
        return jsonify({"error": "provider, model, and api_key are required"}), 400

    try:
        save_ai_config_row("__org_default__", provider, model, api_key)
        log_audit("ai_org_default_saved", "ai_config", "__org_default__", detail=f"{provider}/{model}")
        return jsonify({"status": "saved"})
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    except RuntimeError as err:
        return jsonify({"error": str(err)}), 503

@app.route("/api/intake/route", methods=["POST"])
@rate_limit(max_requests=40, window_seconds=60)
def api_intake_route():
    body = request.get_json(silent=True) or {}
    text = str(body.get("text") or body.get("query") or "").strip()
    if not text:
        return jsonify({"error": "Missing 'text' field"}), 400

    current_object_type = str(body.get("current_object_type") or "").strip().lower() or None
    in_entity_narrowing_raw = body.get("in_entity_narrowing", False)
    if isinstance(in_entity_narrowing_raw, bool):
        in_entity_narrowing = in_entity_narrowing_raw
    elif isinstance(in_entity_narrowing_raw, str):
        in_entity_narrowing = in_entity_narrowing_raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        in_entity_narrowing = bool(in_entity_narrowing_raw)

    routed = route_intake(
        text,
        current_object_type=current_object_type,
        in_entity_narrowing=in_entity_narrowing,
    )
    return jsonify(routed)


@app.route("/api/resolve", methods=["POST"])
@require_auth("cases:read")
def api_resolve_entity():
    """Resolve an entity name into canonical candidates with identifiers.
    Queries SEC EDGAR, GLEIF, SAM.gov, OpenCorporates, and Wikidata in parallel.
    Optionally applies AI reranking when candidates are ambiguous.

    Request: {"name": "...", "country": "US", "profile": "...", "program": "...",
              "context": "...", "use_ai": true, "max_candidates": 6}
    Response: {"query": "...", "count": N, "candidates": [...], "resolution": {...}}
    """
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or body.get("vendor_name") or body.get("query") or "").strip()
    if not name:
        return jsonify({"error": "Missing 'name' field"}), 400

    country = str(body.get("country", "") or "").strip().upper()
    profile = str(body.get("profile", "") or "").strip()
    program = str(body.get("program", "") or "").strip()
    context = str(body.get("context", "") or "").strip()[:300]
    use_ai_raw = body.get("use_ai", True)
    if isinstance(use_ai_raw, bool):
        use_ai = use_ai_raw
    elif isinstance(use_ai_raw, str):
        use_ai = use_ai_raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        use_ai = bool(use_ai_raw)

    try:
        max_candidates = int(body.get("max_candidates", 6))
    except (TypeError, ValueError):
        return jsonify({"error": "max_candidates must be an integer"}), 400
    max_candidates = max(1, min(max_candidates, 10))

    from entity_resolver import resolve_entity
    try:
        candidates = resolve_entity(name)[:max_candidates]
    except Exception as exc:
        app.logger.warning("Entity resolution failed for %r: %s", name, exc)
        candidates = []
    resolution = None

    try:
        from entity_rerank import init_rerank_tables, resolve_with_reranking, save_resolution_run

        init_rerank_tables()
        user_id = g.user.get("sub", "") if hasattr(g, "user") else ""
        resolution = resolve_with_reranking(
            candidates=candidates,
            query=name,
            user_id=user_id,
            country=country,
            profile=profile,
            program=program,
            context=context,
            use_ai=use_ai,
        )
        resolution["_query"] = name
        resolution["_country"] = country
        resolution["_profile"] = profile
        resolution["_program"] = program
        resolution["_context"] = context
        try:
            save_resolution_run(resolution, candidates, user_id)
        except Exception as exc:
            app.logger.warning("Failed to persist entity resolution run %s: %s", resolution.get("request_id"), exc)
        for key in ["_query", "_country", "_profile", "_program", "_context"]:
            resolution.pop(key, None)
    except ImportError as exc:
        app.logger.warning("Entity rerank module unavailable: %s", exc)
    except Exception as exc:
        app.logger.warning("Entity reranking failed for %r: %s", name, exc)
        resolution = {
            "mode": "deterministic_plus_ai" if use_ai else "deterministic_only",
            "status": "unavailable",
            "abstained": False,
            "confidence": candidates[0].get("confidence", 0.0) if candidates else 0.0,
            "reason_summary": "AI reranking is unavailable. Showing raw deterministic candidates.",
            "reason_detail": [],
            "request_id": f"er-{uuid.uuid4().hex[:10]}",
            "input_hash": "",
            "prompt_version": "",
            "latency_ms": 0,
            "evidence": {
                "used_country": bool(country),
                "used_profile": bool(profile),
                "used_program": bool(program),
                "used_context": bool(context),
                "candidate_count_evaluated": len(candidates),
            },
        }

    response = {"query": name, "candidates": candidates, "count": len(candidates)}
    if resolution:
        response["resolution"] = resolution
    return jsonify(response)


@app.route("/api/resolve/feedback", methods=["POST"])
@require_auth("cases:read")
@rate_limit(max_requests=20, window_seconds=60)
def api_resolve_feedback():
    """Record analyst feedback on entity resolution recommendation."""
    body = request.get_json(silent=True) or {}
    run_id = str(body.get("request_id", "") or "").strip()
    selected_id = str(body.get("selected_candidate_id", "") or "").strip()

    if not run_id or not selected_id:
        return jsonify({"error": "request_id and selected_candidate_id required"}), 400
    if len(run_id) > 64 or len(selected_id) > 200:
        return jsonify({"error": "request_id or selected_candidate_id too long"}), 400

    try:
        from entity_rerank import init_rerank_tables, save_feedback

        init_rerank_tables()
        accepted = save_feedback(run_id, selected_id)
        return jsonify({"status": "recorded", "accepted_recommendation": accepted})
    except ValueError as err:
        message = str(err)
        status = 404 if "not found" in message.lower() else 400
        return jsonify({"error": message}), status
    except Exception as err:
        app.logger.warning("Failed to record entity resolution feedback for %s: %s", run_id, err)
        return jsonify({"error": "Could not record entity resolution feedback"}), 500


@app.route("/api/vehicle-search", methods=["POST"])
@require_auth("cases:read")
def api_vehicle_search():
    """Search for vendors associated with a contract vehicle (LEIA, TACS, OASIS, etc.).
    Returns prime contractors and subcontractors from USAspending.gov."""
    body = request.get_json(silent=True) or {}
    vehicle = (body.get("vehicle") or body.get("vehicle_name") or body.get("query") or "").strip()
    if not vehicle:
        return jsonify({"error": "Missing 'vehicle' field"}), 400

    include_subs = body.get("include_subs", True)
    limit = min(body.get("limit", 30), 100)

    from contract_vehicle_search import search_contract_vehicle
    result = search_contract_vehicle(vehicle, include_subs=include_subs, limit=limit)

    status_code = 200
    if result.get("errors") and not any((result.get("total_primes"), result.get("total_subs"), result.get("total_unique"))):
        status_code = 502
        first_error = result["errors"][0].get("message") if isinstance(result.get("errors"), list) and result["errors"] else None
        result = {
            **result,
            "error": "Vehicle search is temporarily unavailable.",
            "detail": first_error,
        }

    return jsonify(result), status_code


@app.route("/api/vehicle-batch-assess", methods=["POST"])
@require_auth("cases:create")
@rate_limit(max_requests=5, window_seconds=60)
def api_vehicle_batch_assess():
    """Batch-create scored draft cases from a contract vehicle search.
    Accepts a list of vendor names, creates minimally scored draft cases, and
    leaves full enrichment to an explicit per-case action."""
    body = request.get_json(silent=True) or {}
    vendors = body.get("vendors", [])
    program = body.get("program", "dod_unclassified")
    profile = body.get("profile", "defense_acquisition")

    if not vendors or not isinstance(vendors, list):
        return jsonify({"error": "Missing 'vendors' array"}), 400
    if len(vendors) > 50:
        return jsonify({"error": "Maximum 50 vendors per batch"}), 400

    results = []
    for v in vendors:
        name = v.get("vendor_name", "").strip() if isinstance(v, dict) else str(v).strip()
        if not name:
            continue

        vendor_id = f"c-{uuid.uuid4().hex[:8]}"
        vendor_input = _build_minimal_vendor_input(
            vendor_id,
            name,
            v.get("country", "US") if isinstance(v, dict) else "US",
            program,
            profile,
        )

        try:
            score_dict = _score_and_persist(vendor_id, vendor_input)
            results.append({
                "case_id": vendor_id,
                "vendor_name": name,
                "status": "created",
                "tier": score_dict.get("calibrated", {}).get("calibrated_tier", "pending"),
            })
        except Exception as e:
            results.append({"vendor_name": name, "status": "error", "error": str(e)})

    log_audit("batch_vehicle_assess", "batch", None,
              detail=f"Batch created {len(results)} scored draft cases from vehicle search")

    return jsonify({
        "mode": "draft_case_creation",
        "message": "Created scored draft cases only. Run enrichment per case for full OSINT review.",
        "total": len(results),
        "created": sum(1 for r in results if r["status"] == "created"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }), 201


@app.route("/api/compare", methods=["POST"])
@require_auth("cases:read")
def api_compare_profiles():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    country = body.get("country", "US").strip() or "US"
    profile_ids = body.get("profiles", [])
    programs = body.get("programs", {}) if isinstance(body.get("programs", {}), dict) else {}

    if not name:
        return jsonify({"error": "Missing 'name' field"}), 400
    if not profile_ids or not isinstance(profile_ids, list):
        return jsonify({"error": "Missing 'profiles' array"}), 400

    from profiles import get_profile

    comparisons = []
    for profile_id in profile_ids[:8]:
        profile = get_profile(profile_id)
        if not profile:
            comparisons.append({
                "profile_id": profile_id,
                "profile_name": profile_id,
                "tier": "UNSCORED",
                "posterior": 0.0,
                "hard_stops": [],
                "soft_flags": [],
                "contributions": [],
                "error": "Unknown profile",
            })
            continue

        program = str(programs.get(profile_id) or _default_program_for_profile(profile_id))
        vendor_input = _build_minimal_vendor_input(
            vendor_id=f"cmp-{uuid.uuid4().hex[:8]}",
            name=name,
            country=country,
            program=program,
            profile=profile_id,
        )

        try:
            _, score_dict = _score_vendor_result(vendor_input)
            calibrated = score_dict["calibrated"]
            comparisons.append({
                "profile_id": profile_id,
                "profile_name": profile.name,
                "tier": calibrated.get("calibrated_tier", "UNSCORED"),
                "posterior": calibrated.get("calibrated_probability", 0.0),
                "hard_stops": calibrated.get("hard_stop_decisions", []),
                "soft_flags": calibrated.get("soft_flags", []),
                "contributions": calibrated.get("contributions", []),
            })
        except Exception as err:
            comparisons.append({
                "profile_id": profile_id,
                "profile_name": profile.name,
                "tier": "UNSCORED",
                "posterior": 0.0,
                "hard_stops": [],
                "soft_flags": [],
                "contributions": [],
                "error": str(err),
            })

    return jsonify({
        "entity": {
            "name": name,
            "country": country,
        },
        "comparisons": comparisons,
    })


@app.route("/api/batch/upload", methods=["POST"])
@require_auth("cases:create")
@rate_limit(max_requests=3, window_seconds=60)
def api_batch_upload():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "CSV file is required"}), 400

    try:
        text = upload.stream.read().decode("utf-8-sig")
    except Exception:
        return jsonify({"error": "Could not read uploaded file as UTF-8 CSV"}), 400

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return jsonify({"error": "CSV must include a header row"}), 400

    field_map = {field.strip().lower(): field for field in reader.fieldnames if field}
    name_field = field_map.get("name") or field_map.get("vendor_name")
    country_field = field_map.get("country")
    program_field = field_map.get("program")
    profile_field = field_map.get("profile")

    if not name_field or not country_field:
        return jsonify({"error": "CSV must include 'name' and 'country' columns"}), 400

    parsed_rows = []
    for raw_row in reader:
        name = (raw_row.get(name_field) or "").strip()
        country = (raw_row.get(country_field) or "").strip() or "US"
        if not name:
            continue
        parsed_rows.append({
            "name": name,
            "country": country,
            "program": (raw_row.get(program_field) or "").strip() if program_field else "",
            "profile": (raw_row.get(profile_field) or "").strip() if profile_field else "",
        })

    if not parsed_rows:
        return jsonify({"error": "CSV did not contain any valid vendor rows"}), 400
    if len(parsed_rows) > 250:
        return jsonify({"error": "Maximum 250 rows per batch"}), 400

    batch_id = f"b-{uuid.uuid4().hex[:10]}"
    db.create_batch(batch_id, _current_user_id(), _current_user_email(), upload.filename, len(parsed_rows))

    rows_for_worker = []
    for row in parsed_rows:
        item_id = db.add_batch_item(batch_id, row["name"], row["country"], status="pending")
        rows_for_worker.append({**row, "item_id": item_id})

    default_profile = "defense_acquisition"
    default_program = _default_program_for_profile(default_profile)

    worker = threading.Thread(
        target=_process_batch_async,
        args=(batch_id, rows_for_worker, default_program, default_profile),
        daemon=True,
    )
    worker.start()

    log_audit("batch_uploaded", "batch", batch_id, detail=f"{len(parsed_rows)} vendor rows")

    return jsonify({
        "batch_id": batch_id,
        "filename": upload.filename,
        "total_vendors": len(parsed_rows),
        "status": "processing",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }), 201


@app.route("/api/batch")
@require_auth("cases:read")
def api_list_batches():
    uploaded_by = None if g.user.get("role") == "admin" else _current_user_id()
    batches = [_serialize_batch(batch) for batch in db.get_batches(uploaded_by=uploaded_by)]
    for batch in batches:
        batch.pop("items", None)
        batch.pop("summary", None)
    return jsonify({"batches": batches})


@app.route("/api/batch/<batch_id>")
@require_auth("cases:read")
def api_get_batch(batch_id):
    batch = db.get_batch(batch_id)
    if not batch:
        return jsonify({"error": "Batch not found"}), 404
    if g.user.get("role") != "admin" and batch.get("uploaded_by") != _current_user_id():
        return jsonify({"error": "Batch not found"}), 404
    return jsonify(_serialize_batch(batch))


@app.route("/api/batch/<batch_id>/report")
@require_auth("cases:read")
def api_download_batch_report(batch_id):
    batch = db.get_batch(batch_id)
    if not batch:
        return jsonify({"error": "Batch not found"}), 404
    if g.user.get("role") != "admin" and batch.get("uploaded_by") != _current_user_id():
        return jsonify({"error": "Batch not found"}), 404

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["vendor_name", "country", "status", "case_id", "tier", "posterior", "findings_count", "error"])
    for item in batch.get("items", []):
        writer.writerow([
            item.get("vendor_name", ""),
            item.get("country", ""),
            item.get("status", ""),
            item.get("case_id", ""),
            item.get("tier", ""),
            item.get("posterior", ""),
            item.get("findings_count", ""),
            item.get("error", ""),
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=batch-{batch_id}-report.csv"},
    )


@app.route("/api/cases")
@require_auth("cases:read")
def api_list_cases():
    limit = request.args.get("limit", 100, type=int)
    vendors = db.list_vendors_with_scores(limit)
    cases = []
    for v in vendors:
        score = v.get("latest_score")
        vendor_input = v.get("vendor_input", {}) if isinstance(v, dict) else {}
        program = vendor_input.get("program", "") if isinstance(vendor_input, dict) else ""
        cases.append({
            "id": v["id"],
            "vendor_name": v["name"],
            "country": v.get("country", ""),
            "profile": _normalize_profile_id(v.get("profile", "defense_acquisition")),
            "program": program,
            "workflow_lane": _workflow_lane_for_vendor(v),
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
    vendor_input = v.get("vendor_input", {}) if isinstance(v, dict) else {}
    result = {
        "id": v["id"], "vendor_name": v["name"],
        "country": v["country"], "program": v["program"], "profile": _normalize_profile_id(v.get("profile", "defense_acquisition")),
        "workflow_lane": _workflow_lane_for_vendor(v),
        "status": score.get("calibrated", {}).get("calibrated_tier", "unknown") if score else "pending",
        "created_at": v["created_at"], "score": score,
        "export_authorization": vendor_input.get("export_authorization") if isinstance(vendor_input, dict) else None,
    }
    if HAS_EXPORT_RULES and isinstance(vendor_input, dict):
        export_auth_input = vendor_input.get("export_authorization")
        if HAS_GRAPH_AWARE_AUTH:
            result["export_authorization_guidance"] = build_graph_aware_guidance(export_auth_input)
        else:
            result["export_authorization_guidance"] = build_export_authorization_guidance(export_auth_input)
    if HAS_EXPORT_ARTIFACTS:
        result["latest_export_artifact"] = _serialize_export_artifact(
            _latest_case_artifact(case_id, source_system="export_artifact_upload")
        )
    if HAS_EXPORT_EVIDENCE and isinstance(vendor_input, dict):
        result["export_evidence_summary"] = get_export_evidence_summary(
            case_id,
            vendor_input.get("export_authorization"),
        )
    if HAS_FOCI_ARTIFACTS:
        result["latest_foci_artifact"] = _serialize_artifact_record(
            _latest_case_artifact(case_id, source_system="foci_artifact_upload")
        )
    if HAS_FOCI_SUMMARY:
        result["foci_evidence_summary"] = get_latest_foci_summary(case_id)
    if HAS_SPRS_IMPORT:
        result["latest_sprs_import"] = _serialize_artifact_record(
            _latest_case_artifact(case_id, source_system="sprs_import")
        )
    if HAS_OSCAL_INTAKE:
        result["latest_oscal_artifact"] = _serialize_artifact_record(
            _latest_case_artifact(case_id, source_system="oscal_upload")
        )
    if HAS_NVD_OVERLAY:
        result["latest_nvd_overlay"] = _serialize_artifact_record(
            _latest_case_artifact(case_id, source_system="nvd_overlay")
        )
    if HAS_CYBER_EVIDENCE:
        result["cyber_evidence_summary"] = get_latest_cyber_evidence_summary(case_id)
    if HAS_WORKFLOW_CONTROL:
        result["workflow_control_summary"] = build_workflow_control_summary(
            v,
            foci_summary=result.get("foci_evidence_summary"),
            cyber_summary=result.get("cyber_evidence_summary"),
            export_summary=result.get("export_evidence_summary"),
        )
    network_risk_summary = None
    # Attach network risk if module available (lightweight lookup)
    if HAS_NETWORK_RISK:
        try:
            nr = compute_network_risk(case_id)
            network_risk_summary = {
                "score": nr.get("network_risk_score", 0),
                "level": nr.get("network_risk_level", "none"),
                "high_risk_neighbors": nr.get("high_risk_neighbors", 0),
                "neighbor_count": nr.get("neighbor_count", 0),
            }
            result["network_risk"] = network_risk_summary
        except Exception:
            result["network_risk"] = None
    try:
        result["storyline"] = _build_case_storyline_payload(case_id, v, score, network_risk=network_risk_summary)
    except Exception as e:
        app.logger.warning(f"Storyline build failed for {case_id}: {type(e).__name__}: {e}")
        result["storyline"] = None
    return jsonify(result)


@app.route("/api/cases/<case_id>/supplier-passport")
@require_auth("cases:read")
def api_get_supplier_passport(case_id):
    """Return a portable supplier-passport summary for the requested case."""
    if not HAS_SUPPLIER_PASSPORT:
        return jsonify({"error": "Supplier passport generator not available"}), 501

    passport = build_supplier_passport(case_id, mode=request.args.get("mode", "full"))
    if not passport:
        return jsonify({"error": "Case not found"}), 404
    return jsonify(passport)


@app.route("/api/cases/<case_id>/assistant-plan", methods=["POST"])
@require_auth("cases:read")
def api_get_case_assistant_plan(case_id):
    """Build a typed hybrid-control-plane plan for a natural-language analyst request."""
    if not HAS_AI_CONTROL_PLANE:
        return jsonify({"error": "AI control plane planner not available"}), 501

    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404

    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    score = db.get_latest_score(case_id)
    enrichment = db.get_latest_enrichment(case_id)
    passport = build_supplier_passport(case_id) if HAS_SUPPLIER_PASSPORT else None
    network_risk = passport.get("network_risk") if isinstance(passport, dict) else None
    storyline = _build_case_storyline_payload(case_id, vendor, score, network_risk=network_risk)
    plan_payload = build_case_assistant_plan(
        case_id=case_id,
        analyst_prompt=prompt,
        vendor=vendor,
        score=score,
        enrichment=enrichment,
        supplier_passport=passport,
        storyline=storyline,
    )
    run_id = f"qr-{uuid.uuid4().hex[:10]}"
    db.save_assistant_run(
        run_id=run_id,
        case_id=case_id,
        workflow_lane=str(((plan_payload.get("preflight") or {}).get("workflow_lane") or "")),
        objective=str(plan_payload.get("objective") or ""),
        playbook_id=str(((plan_payload.get("playbook") or {}).get("playbook_id") or "")),
        status="planned",
        analyst_prompt=prompt,
        plan_payload=plan_payload,
        execution_payload=_assistant_run_snapshot(plan_payload, phase="plan", status="planned"),
        created_by=_current_user_id(),
        created_by_email=_current_user_email(),
        created_by_role=_current_user_role(),
    )
    db.save_beta_event(
        user_id=_current_user_id(),
        user_email=_current_user_email(),
        user_role=_current_user_role(),
        case_id=case_id,
        workflow_lane=str(((plan_payload.get("preflight") or {}).get("workflow_lane") or "")),
        screen="assistant_control_plane",
        event_name="assistant_run_planned",
        metadata={
            "run_id": run_id,
            "objective": plan_payload.get("objective"),
            "playbook_id": (plan_payload.get("playbook") or {}).get("playbook_id"),
        },
    )
    return jsonify({**plan_payload, "run_id": run_id, "run_status": "planned"})


@app.route("/api/cases/<case_id>/assistant-runs", methods=["GET"])
@require_auth("cases:read")
def api_list_case_assistant_runs(case_id):
    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404
    limit = max(1, min(int(request.args.get("limit", 20) or 20), 100))
    runs = db.list_case_assistant_runs(case_id, limit=limit)
    return jsonify({"assistant_runs": runs, "total": len(runs)})


@app.route("/api/cases/<case_id>/assistant-runs/<run_id>", methods=["GET"])
@require_auth("cases:read")
def api_get_case_assistant_run(case_id, run_id):
    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404
    payload = db.get_assistant_run(run_id)
    if not payload or payload.get("case_id") != case_id:
        return jsonify({"error": "Assistant run not found"}), 404
    return jsonify(payload)


def _serialize_person_screenings_for_assistant(case_id: str) -> dict:
    if not HAS_PERSON_SCREENING:
        return {"status": "unavailable", "error": "person screening module not available"}
    try:
        init_person_screening_db()
        results = get_case_screenings(case_id)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "count": len(results),
        "screenings": [
            {
                "id": result.id,
                "person_name": result.person_name,
                "nationalities": result.nationalities,
                "employer": result.employer,
                "screening_status": result.screening_status,
                "composite_score": round(result.composite_score, 4),
                "recommended_action": result.recommended_action,
            }
            for result in results
        ],
    }


def _execute_case_assistant_tool(
    tool_id: str,
    *,
    case_id: str,
    vendor: dict,
    score: dict | None,
    enrichment: dict | None,
    supplier_passport: dict | None,
    storyline: dict | None,
    anomalies: list[dict],
) -> dict:
    if tool_id == "case_snapshot":
        network_risk = (supplier_passport or {}).get("network_risk") if isinstance(supplier_passport, dict) else None
        return {
            "tool_id": tool_id,
            "status": "ok",
            "result": {
                "case": {
                    "id": vendor["id"],
                    "vendor_name": vendor["name"],
                    "country": vendor.get("country"),
                    "program": vendor.get("program"),
                    "profile": _normalize_profile_id(vendor.get("profile", "defense_acquisition")),
                    "workflow_lane": _workflow_lane_for_vendor(vendor),
                    "status": ((score or {}).get("calibrated") or {}).get("calibrated_tier", "pending"),
                    "network_risk": network_risk,
                    "storyline": storyline,
                }
            },
        }
    if tool_id == "supplier_passport":
        return {
            "tool_id": tool_id,
            "status": "ok" if supplier_passport else "unavailable",
            "result": supplier_passport or {"error": "Supplier passport unavailable"},
        }
    if tool_id == "graph_probe":
        graph = (supplier_passport or {}).get("graph") if isinstance(supplier_passport, dict) else None
        return {
            "tool_id": tool_id,
            "status": "ok" if graph else "unavailable",
            "result": graph or {"error": "Graph probe unavailable"},
        }
    if tool_id == "network_risk":
        if not HAS_NETWORK_RISK:
            return {"tool_id": tool_id, "status": "unavailable", "result": {"error": "Network risk module unavailable"}}
        try:
            return {"tool_id": tool_id, "status": "ok", "result": compute_network_risk(case_id)}
        except Exception as exc:
            return {"tool_id": tool_id, "status": "error", "result": {"error": str(exc)}}
    if tool_id == "enrichment_findings":
        return {
            "tool_id": tool_id,
            "status": "ok" if enrichment else "unavailable",
            "result": enrichment or {"error": "Enrichment report unavailable"},
        }
    if tool_id == "identity_repair":
        identity = (supplier_passport or {}).get("identity") if isinstance(supplier_passport, dict) else None
        identity_anomalies = [item for item in anomalies if item.get("code", "").startswith(("missing_", "thin_identity", "passport_"))]
        return {
            "tool_id": tool_id,
            "status": "ok" if identity else "unavailable",
            "result": {
                "identity": identity or {},
                "anomalies": identity_anomalies,
            },
        }
    if tool_id == "export_guidance":
        export_auth_input = (vendor.get("vendor_input") or {}).get("export_authorization") if isinstance(vendor.get("vendor_input"), dict) else None
        guidance = None
        if export_auth_input and HAS_EXPORT_RULES:
            guidance = build_graph_aware_guidance(export_auth_input) if HAS_GRAPH_AWARE_AUTH else build_export_authorization_guidance(export_auth_input)
        hybrid_review = None
        if export_auth_input and HAS_EXPORT_AI_CHALLENGE:
            hybrid_review = build_hybrid_export_review(export_auth_input)
        return {
            "tool_id": tool_id,
            "status": "ok" if guidance or export_auth_input else "unavailable",
            "result": {
                "export_authorization": export_auth_input,
                "guidance": guidance,
                "hybrid_review": hybrid_review,
            },
        }
    if tool_id == "cyber_evidence":
        if not HAS_CYBER_EVIDENCE:
            return {"tool_id": tool_id, "status": "unavailable", "result": {"error": "Cyber evidence module unavailable"}}
        try:
            cyber_summary = get_latest_cyber_evidence_summary(case_id)
            hybrid_review = None
            if cyber_summary and HAS_SUPPLY_CHAIN_ASSURANCE_AI:
                hybrid_review = build_hybrid_assurance_review(
                    cyber_summary,
                    vendor=vendor,
                    supplier_passport=supplier_passport,
                )
            return {
                "tool_id": tool_id,
                "status": "ok",
                "result": {
                    "cyber_evidence_summary": cyber_summary,
                    "hybrid_review": hybrid_review,
                },
            }
        except Exception as exc:
            return {"tool_id": tool_id, "status": "error", "result": {"error": str(exc)}}
    if tool_id == "person_screening":
        return {
            "tool_id": tool_id,
            "status": "ok",
            "result": _serialize_person_screenings_for_assistant(case_id),
        }
    if tool_id == "monitoring_history":
        return {
            "tool_id": tool_id,
            "status": "ok",
            "result": {
                "history": db.get_monitoring_history(case_id, limit=10),
            },
        }

    return {
        "tool_id": tool_id,
        "status": "blocked",
        "result": {"error": "Tool is outside the approved execution boundary"},
    }


def _assistant_pack_state(
    plan_payload: dict | None,
    *,
    phase: str,
    executed_tool_ids: list[str] | None = None,
    blocked_tool_ids: list[str] | None = None,
) -> list[dict]:
    executed = set(executed_tool_ids or [])
    blocked = set(blocked_tool_ids or [])
    step_map: dict[str, list[dict]] = {}
    for step in (plan_payload or {}).get("plan", []) or []:
        pack_id = str(step.get("pack_id") or "").strip()
        if not pack_id:
            continue
        step_map.setdefault(pack_id, []).append(step)

    pack_state: list[dict] = []
    for member in (plan_payload or {}).get("pack", []) or []:
        pack_id = str(member.get("id") or member.get("pack_id") or member.get("call_sign") or "").strip().lower()
        assigned = step_map.get(pack_id, [])
        assigned_tool_ids = [str(step.get("tool_id") or "").strip() for step in assigned if str(step.get("tool_id") or "").strip()]
        completed_tool_ids = [tool_id for tool_id in assigned_tool_ids if tool_id in executed]
        blocked_member_tool_ids = [tool_id for tool_id in assigned_tool_ids if tool_id in blocked]

        if pack_id == "vesper":
            status = "command"
        elif phase == "plan":
            status = "ready" if assigned_tool_ids else "reserve"
        elif phase == "execute":
            if completed_tool_ids and len(completed_tool_ids) == len(assigned_tool_ids):
                status = "complete"
            elif completed_tool_ids or blocked_member_tool_ids:
                status = "engaged"
            else:
                status = "ready" if assigned_tool_ids else "reserve"
        else:
            status = "reviewing" if assigned_tool_ids else "reserve"

        pack_state.append(
            {
                "id": pack_id,
                "call_sign": member.get("call_sign"),
                "breed": member.get("breed"),
                "role": member.get("role"),
                "function": member.get("function"),
                "summary": member.get("summary"),
                "duty": member.get("duty"),
                "active": bool(member.get("active", True)),
                "status": status,
                "assigned_tool_ids": assigned_tool_ids,
                "completed_tool_ids": completed_tool_ids,
                "blocked_tool_ids": blocked_member_tool_ids,
            }
        )
    return pack_state


def _assistant_run_snapshot(
    plan_payload: dict | None,
    *,
    phase: str,
    status: str,
    approved_tool_ids: list[str] | None = None,
    executed_steps: list[dict] | None = None,
    blocked_tools: list[dict] | None = None,
    verdict: str = "",
    feedback_type: str = "",
    feedback_id: int | None = None,
    training_signal: dict | None = None,
) -> dict:
    executed_tool_ids = [str(step.get("tool_id") or "").strip() for step in (executed_steps or []) if str(step.get("tool_id") or "").strip()]
    blocked_tool_ids = [str(item.get("tool_id") or "").strip() for item in (blocked_tools or []) if str(item.get("tool_id") or "").strip()]
    preflight = (plan_payload or {}).get("preflight") or {}
    playbook = (plan_payload or {}).get("playbook") or {}
    quarterback = (plan_payload or {}).get("quarterback") or {}
    operator_updates = list((plan_payload or {}).get("operator_updates") or [])

    if phase == "execute":
        operator_updates.append(
            f"{quarterback.get('call_sign', 'Quarterback')} kept {len(executed_tool_ids)} tool step(s) inside the approved boundary."
        )
    if phase == "review" and verdict:
        operator_updates.append(
            f"Analyst verdict: {verdict}. Feedback type: {feedback_type or 'unspecified'}."
        )

    return {
        "quarterback": quarterback,
        "playbook": playbook,
        "preflight": preflight,
        "phase": phase,
        "status": status,
        "approved_tool_ids": list(approved_tool_ids or []),
        "executed_steps": executed_steps or [],
        "blocked_tools": blocked_tools or [],
        "feedback": {
            "verdict": verdict,
            "feedback_type": feedback_type,
            "feedback_id": feedback_id,
            "training_signal": training_signal or {},
        },
        "situation_report": {
            "workflow_lane": str(preflight.get("workflow_lane") or ""),
            "anomaly_pressure": str(preflight.get("anomaly_pressure") or ""),
            "human_gate_required": bool(preflight.get("human_gate_required")),
            "degraded_mode": bool(preflight.get("degraded_mode")),
            "execution_mode": str(preflight.get("execution_mode") or ""),
        },
        "pack_state": _assistant_pack_state(
            plan_payload,
            phase=phase,
            executed_tool_ids=executed_tool_ids,
            blocked_tool_ids=blocked_tool_ids,
        ),
        "operator_brief": (plan_payload or {}).get("operator_brief") or "",
        "operator_updates": operator_updates,
        "captured_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }


@app.route("/api/cases/<case_id>/assistant-execute", methods=["POST"])
@require_auth("cases:read")
def api_execute_case_assistant_plan(case_id):
    """Execute analyst-approved assistant tools within the current safe boundary."""
    if not HAS_AI_CONTROL_PLANE:
        return jsonify({"error": "AI control plane planner not available"}), 501

    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404

    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    approved_tool_ids = payload.get("approved_tool_ids") or []
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    if not isinstance(approved_tool_ids, list) or not approved_tool_ids:
        return jsonify({"error": "approved_tool_ids must be a non-empty list"}), 400

    score = db.get_latest_score(case_id)
    enrichment = db.get_latest_enrichment(case_id)
    passport = build_supplier_passport(case_id) if HAS_SUPPLIER_PASSPORT else None
    network_risk = passport.get("network_risk") if isinstance(passport, dict) else None
    storyline = _build_case_storyline_payload(case_id, vendor, score, network_risk=network_risk)
    plan_payload = build_case_assistant_plan(
        case_id=case_id,
        analyst_prompt=prompt,
        vendor=vendor,
        score=score,
        enrichment=enrichment,
        supplier_passport=passport,
        storyline=storyline,
    )
    assistant_run = None
    if run_id:
        assistant_run = db.get_assistant_run(run_id)
        if not assistant_run or assistant_run.get("case_id") != case_id:
            return jsonify({"error": "Assistant run not found"}), 404

    executable_ids, blocked_tools = prepare_case_assistant_execution(plan_payload.get("plan", []), approved_tool_ids)
    if not executable_ids:
        if run_id:
            db.update_assistant_run(
                run_id,
                status="blocked",
                plan_payload=plan_payload,
                execution_payload=_assistant_run_snapshot(
                    plan_payload,
                    phase="execute",
                    status="blocked",
                    approved_tool_ids=approved_tool_ids,
                    executed_steps=[],
                    blocked_tools=blocked_tools,
                ),
                last_error="No approved tools were eligible for execution",
            )
        return jsonify(
            {
                "error": "No approved tools were eligible for execution",
                "blocked_tools": blocked_tools,
                "plan": plan_payload,
            }
        ), 400

    executed_steps = [
        _execute_case_assistant_tool(
            tool_id,
            case_id=case_id,
            vendor=vendor,
            score=score,
            enrichment=enrichment,
            supplier_passport=passport,
            storyline=storyline,
            anomalies=plan_payload.get("anomalies", []),
        )
        for tool_id in executable_ids
    ]

    if run_id:
        db.update_assistant_run(
            run_id,
            status="executed",
            plan_payload=plan_payload,
            execution_payload=_assistant_run_snapshot(
                plan_payload,
                phase="execute",
                status="executed",
                approved_tool_ids=approved_tool_ids,
                executed_steps=executed_steps,
                blocked_tools=blocked_tools,
            ),
            last_error="",
        )
        db.save_beta_event(
            user_id=_current_user_id(),
            user_email=_current_user_email(),
            user_role=_current_user_role(),
            case_id=case_id,
            workflow_lane=str(((plan_payload.get("preflight") or {}).get("workflow_lane") or "")),
            screen="assistant_control_plane",
            event_name="assistant_run_executed",
            metadata={"run_id": run_id, "executed_tool_ids": executable_ids},
        )

    return jsonify(
        {
            "version": "ai-control-plane-execution-v1",
            "executed_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "case_id": case_id,
            "run_id": run_id or None,
            "run_status": "executed" if run_id else "ephemeral",
            "objective": plan_payload.get("objective"),
            "analyst_prompt": prompt,
            "quarterback": plan_payload.get("quarterback"),
            "playbook": plan_payload.get("playbook"),
            "preflight": plan_payload.get("preflight"),
            "pack": plan_payload.get("pack"),
            "operator_brief": plan_payload.get("operator_brief"),
            "operator_updates": plan_payload.get("operator_updates"),
            "approved_tool_ids": approved_tool_ids,
            "executed_steps": executed_steps,
            "blocked_tools": blocked_tools,
            "approval_boundary": "analyst-approved typed tools only; no silent live reruns or state mutation",
        }
    )


@app.route("/api/cases/<case_id>/assistant-feedback", methods=["POST"])
@require_auth("cases:read")
@rate_limit(max_requests=60, window_seconds=60)
def api_record_case_assistant_feedback(case_id):
    """Persist structured analyst feedback about assistant planning and execution."""
    if not HAS_AI_CONTROL_PLANE:
        return jsonify({"error": "AI control plane planner not available"}), 501

    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404

    body = request.get_json(silent=True) or {}
    prompt = str(body.get("prompt") or "").strip()
    run_id = str(body.get("run_id") or "").strip()
    objective = str(body.get("objective") or "").strip()
    verdict = str(body.get("verdict") or "").strip().lower()
    feedback_type = str(body.get("feedback_type") or "").strip().lower()
    comment = str(body.get("comment") or "").strip()
    approved_tool_ids = body.get("approved_tool_ids") or []
    executed_tool_ids = body.get("executed_tool_ids") or []
    suggested_tool_ids = body.get("suggested_tool_ids") or []
    anomaly_codes = body.get("anomaly_codes") or []

    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    if not objective:
        return jsonify({"error": "objective is required"}), 400
    if not isinstance(approved_tool_ids, list):
        return jsonify({"error": "approved_tool_ids must be a list"}), 400
    if not isinstance(executed_tool_ids, list):
        return jsonify({"error": "executed_tool_ids must be a list"}), 400
    if not isinstance(suggested_tool_ids, list):
        return jsonify({"error": "suggested_tool_ids must be a list"}), 400
    if not isinstance(anomaly_codes, list):
        return jsonify({"error": "anomaly_codes must be a list"}), 400

    assistant_run = None
    if run_id:
        assistant_run = db.get_assistant_run(run_id)
        if not assistant_run or assistant_run.get("case_id") != case_id:
            return jsonify({"error": "Assistant run not found"}), 404

    try:
        signal = prepare_case_assistant_feedback(
            prompt=prompt,
            objective=objective,
            verdict=verdict,
            feedback_type=feedback_type,
            comment=comment,
            approved_tool_ids=approved_tool_ids,
            executed_tool_ids=executed_tool_ids,
            suggested_tool_ids=suggested_tool_ids,
            anomaly_codes=anomaly_codes,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    workflow_lane = _workflow_lane_for_vendor(vendor)
    feedback_id = db.save_beta_feedback(
        user_id=_current_user_id(),
        user_email=_current_user_email(),
        user_role=_current_user_role(),
        case_id=case_id,
        workflow_lane=workflow_lane,
        screen="assistant_control_plane",
        category=signal["category"],
        severity=signal["severity"],
        summary=signal["summary"],
        details=signal["details"],
        metadata=signal["training_signal"],
    )
    db.save_beta_event(
        user_id=_current_user_id(),
        user_email=_current_user_email(),
        user_role=_current_user_role(),
        case_id=case_id,
        workflow_lane=workflow_lane,
        screen="assistant_control_plane",
        event_name="assistant_feedback_recorded",
        metadata={
            "feedback_id": feedback_id,
            "run_id": run_id or None,
            "objective": objective,
            "verdict": verdict,
            "feedback_type": feedback_type,
        },
    )
    if assistant_run:
        plan_payload = assistant_run.get("plan_payload") or {}
        prior_execution = assistant_run.get("execution_payload") or {}
        db.update_assistant_run(
            run_id,
            status=verdict or "reviewed",
            plan_payload=plan_payload,
            execution_payload=_assistant_run_snapshot(
                plan_payload,
                phase="review",
                status=verdict or "reviewed",
                approved_tool_ids=list(prior_execution.get("approved_tool_ids") or approved_tool_ids),
                executed_steps=list(prior_execution.get("executed_steps") or []),
                blocked_tools=list(prior_execution.get("blocked_tools") or []),
                verdict=verdict,
                feedback_type=feedback_type,
                feedback_id=feedback_id,
                training_signal=signal["training_signal"],
            ),
            last_error="" if verdict != "rejected" else "Analyst rejected the assistant run",
        )
    return jsonify(
        {
            "status": "ok",
            "feedback_id": feedback_id,
            "run_id": run_id or None,
            "run_status": verdict or "reviewed",
            "training_signal": signal["training_signal"],
        }
    ), 201


@app.route("/api/cases", methods=["POST"])
@require_auth("cases:create")
# Analysts routinely batch-seed training and review queues. Keep the limit
# high enough for the 55-vendor stress corpus while still bounding abuse.
@rate_limit(max_requests=120, window_seconds=60)
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
        "dod": body.get("dod", {}),
        "profile": _normalize_profile_id(body.get("profile_id", body.get("profile", "defense_acquisition"))),
    }
    for optional_key in ("source_context", "seed_metadata"):
        optional_value = body.get(optional_key)
        if isinstance(optional_value, dict) and optional_value:
            v[optional_key] = optional_value
    export_authorization = body.get("export_authorization")
    if isinstance(export_authorization, dict) and export_authorization:
        v["export_authorization"] = export_authorization
    score_dict = _score_and_persist(vendor_id, v)
    _prime_ai_analysis_for_case(
        vendor_id,
        _current_user_id(),
        wait_seconds=0,
        poll_seconds=0.0,
    )
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
    # Ensure name/country are present (may be missing from legacy records)
    if "name" not in vendor_input:
        vendor_input["name"] = v["name"]
    if "country" not in vendor_input:
        vendor_input["country"] = v["country"]
    if "program_type" in body:
        vendor_input["program"] = body["program_type"]
    if "dod" in body:
        vendor_input["dod"] = body["dod"]

    enrichment = db.get_latest_enrichment(case_id)
    updated_vendor = {**v, "vendor_input": vendor_input}
    if enrichment:
        score_dict = _canonical_rescore_from_enrichment(case_id, updated_vendor, enrichment)["score_dict"]
    else:
        score_dict = _score_and_persist(case_id, vendor_input)
    _prime_ai_analysis_for_case(
        case_id,
        _current_user_id(),
        wait_seconds=0,
        poll_seconds=0.0,
    )
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
        return jsonify({"error": "HTML dossier generator not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    body = request.get_json(silent=True) or {}
    include_ai = body.get("include_ai", True)
    hydrate_ai = body.get("hydrate_ai")
    user_id = _current_user_id()
    if include_ai:
        _prime_ai_analysis_for_case(case_id, user_id)
    if hydrate_ai is None:
        hydrate_ai = bool(include_ai)
    html = generate_dossier(case_id, user_id=user_id, hydrate_ai=bool(hydrate_ai))

    # Save to static dir for download
    dossier_dir = os.path.join(os.path.dirname(__file__), "dossiers")
    os.makedirs(dossier_dir, exist_ok=True)
    version_tag = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"dossier-{case_id}-{version_tag}.html"
    filepath = os.path.join(dossier_dir, filename)
    with open(filepath, "w") as f:
        f.write(html)

    log_audit("dossier_generated", "case", case_id,
              detail=f"Dossier generated for {v['name']}")

    if body.get("format") == "html":
        return html, 200, {"Content-Type": "text/html"}

    return jsonify({
        "case_id": case_id,
        "dossier_path": f"/dossiers/{filename}",
        "download_url": f"/api/dossiers/{filename}",
        "updated_at": datetime.now().isoformat(),
    })



@app.route("/api/cases/<case_id>/dossier-pdf", methods=["POST"])
@require_auth("cases:dossier")
def api_generate_dossier_pdf(case_id):
    """Generate a PDF dossier artifact for the requested case."""
    if not HAS_DOSSIER_PDF:
        return jsonify({"error": "Dossier generator not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    try:
        body = request.get_json(silent=True) or {}
        include_ai = body.get("include_ai", True)
        hydrate_ai = body.get("hydrate_ai")
        user_id = _current_user_id()
        if include_ai:
            _prime_ai_analysis_for_case(case_id, user_id)
        if hydrate_ai is None:
            hydrate_ai = bool(include_ai)
        pdf_bytes = generate_pdf_dossier(case_id, user_id=user_id, hydrate_ai=bool(hydrate_ai))
        return pdf_bytes, 200, {"Content-Type": "application/pdf",
                               "Content-Disposition": f"attachment; filename=dossier-{case_id}.pdf"}
    except Exception as e:
        return jsonify({"error": f"Failed to generate PDF: {str(e)}"}), 500

@app.route("/api/dossiers/<filename>")
def api_serve_dossier(filename):
    """Serve a generated dossier HTML file. Path traversal protected.
    Prefers short-lived access tickets for browser downloads."""
    # Auth: check header first, then short-lived access tickets, then legacy query token
    from auth import _decode_token, AUTH_ENABLED
    token = None
    access_ticket = request.args.get("access_ticket", "")
    auth_header = request.headers.get("Authorization", "")
    ticket_payload = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    elif access_ticket:
        ticket_payload = decode_access_ticket(access_ticket)
        if not (
            ticket_payload
            and ticket_payload.get("path") == request.path
            and ticket_payload.get("method", "GET") == request.method
        ):
            return jsonify({"error": "Invalid or expired access ticket"}), 401
    elif request.args.get("token"):
        token = request.args.get("token")
    if AUTH_ENABLED and not token and not ticket_payload:
        return jsonify({"error": "Authentication required"}), 401
    if AUTH_ENABLED and token and not _decode_token(token):
        return jsonify({"error": "Invalid or expired token"}), 401
    # Sanitize filename: strip path separators, reject traversal attempts
    safe_name = os.path.basename(filename)
    if safe_name != filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    dossier_dir = os.path.join(os.path.dirname(__file__), "dossiers")
    filepath = os.path.join(dossier_dir, safe_name)
    # Verify resolved path is within dossier directory
    if not os.path.realpath(filepath).startswith(os.path.realpath(dossier_dir)):
        return jsonify({"error": "Invalid filename"}), 400
    if os.path.exists(filepath):
        response = send_file(filepath)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response
    return jsonify({"error": "Dossier not found"}), 404


@app.route("/api/cases/<case_id>/intel-summary-async", methods=["POST"])
@require_auth("enrich:read")
def api_run_intel_summary_async(case_id):
    if not HAS_AI or not HAS_INTEL:
        return jsonify({"error": "Intel summary module not available"}), 501

    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404

    report = _current_enrichment_report(case_id)
    if not report:
        return jsonify({"error": "Run enrichment before generating an intel summary"}), 400

    user_id = _current_user_id()
    if not get_ai_config_row(user_id):
        return jsonify({"error": "No AI provider configured for intel summary generation"}), 400

    report_hash = report.get("report_hash") or compute_report_hash(report)
    cached = db.get_latest_intel_summary(case_id, user_id=user_id, report_hash=report_hash)
    if cached:
        return jsonify({
            "status": "ready",
            "case_id": case_id,
            "vendor_name": vendor["name"],
            "summary": cached,
            "job_id": None,
        })

    payload = enqueue_intel_summary_job(case_id, user_id, report_hash)
    job = payload["job"]
    if payload["created"]:
        worker = threading.Thread(target=_run_intel_summary_job, args=(job["id"], case_id, user_id), daemon=True)
        worker.start()

    return jsonify({
        "status": job["status"],
        "case_id": case_id,
        "vendor_name": vendor["name"],
        "job_id": job["id"],
        "job": job,
    }), 202


@app.route("/api/cases/<case_id>/intel-summary-status")
@require_auth("enrich:read")
def api_get_intel_summary_status(case_id):
    if not HAS_AI or not HAS_INTEL:
        return jsonify({"error": "Intel summary module not available"}), 501

    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404

    report_hash = _current_intel_report_hash(case_id)
    if not report_hash:
        return jsonify({"status": "missing", "case_id": case_id, "vendor_name": vendor["name"]})

    cached = db.get_latest_intel_summary(case_id, user_id=_current_user_id(), report_hash=report_hash)
    if cached:
        return jsonify({
            "status": "ready",
            "case_id": case_id,
            "vendor_name": vendor["name"],
            "summary": cached,
        })

    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM intel_summary_jobs
            WHERE case_id = ? AND created_by = ? AND report_hash = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (case_id, _current_user_id(), report_hash),
        ).fetchone()
    if row:
        job = _intel_summary_job_row_to_dict(row)
        return jsonify({
            "status": job["status"],
            "case_id": case_id,
            "vendor_name": vendor["name"],
            "job": job,
        })

    return jsonify({"status": "missing", "case_id": case_id, "vendor_name": vendor["name"]})


@app.route("/api/cases/<case_id>/intel-summary")
@require_auth("enrich:read")
def api_get_intel_summary(case_id):
    if not HAS_AI or not HAS_INTEL:
        return jsonify({"error": "Intel summary module not available"}), 501

    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404

    report_hash = _current_intel_report_hash(case_id)
    summary = db.get_latest_intel_summary(case_id, user_id=_current_user_id(), report_hash=report_hash)
    if not summary:
        return jsonify({"error": "No intel summary found for this case"}), 404

    return jsonify({
        "case_id": case_id,
        "vendor_name": vendor["name"],
        "summary": summary["summary"],
        "provider": summary["provider"],
        "model": summary["model"],
        "prompt_tokens": summary["prompt_tokens"],
        "completion_tokens": summary["completion_tokens"],
        "elapsed_ms": summary["elapsed_ms"],
        "created_at": summary["created_at"],
        "prompt_version": summary.get("prompt_version"),
        "report_hash": summary.get("report_hash"),
    })


@app.route("/api/cases/<case_id>/analyze", methods=["POST"])
@require_auth("ai:analyze")
def api_run_ai_analysis(case_id):
    if not HAS_AI:
        return jsonify({"error": "AI analysis module not available"}), 501

    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404

    score = db.get_latest_score(case_id)
    if not score:
        return jsonify({"error": "Case must be scored before AI analysis"}), 400

    enrichment = db.get_latest_enrichment(case_id)

    try:
        result = analyze_vendor(_current_user_id(), vendor, score, enrichment)
    except ValueError as err:
        status_code = 503 if err.__class__.__name__ == "AIProviderTemporaryError" else 400
        return jsonify({"error": str(err)}), status_code

    log_audit("ai_analysis_run", "case", case_id, detail=f"AI analysis for {vendor['name']}")
    return jsonify({
        "case_id": case_id,
        "vendor_name": vendor["name"],
        **result,
    })


@app.route("/api/cases/<case_id>/analyze-async", methods=["POST"])
@require_auth("ai:analyze")
def api_run_ai_analysis_async(case_id):
    if not HAS_AI:
        return jsonify({"error": "AI analysis module not available"}), 501

    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404

    score = db.get_latest_score(case_id)
    if not score:
        return jsonify({"error": "Case must be scored before AI analysis"}), 400

    user_id = _current_user_id()
    input_hash = _current_analysis_input_hash(case_id)
    cached = get_latest_analysis(case_id, user_id=user_id, input_hash=input_hash)
    if cached:
        return jsonify({
            "status": "ready",
            "case_id": case_id,
            "vendor_name": vendor["name"],
            "analysis": cached,
            "job_id": None,
        })

    payload = enqueue_analysis_job(case_id, user_id, input_hash)
    job = payload["job"]
    if payload["created"]:
        worker = threading.Thread(target=_run_ai_analysis_job, args=(job["id"], case_id, user_id), daemon=True)
        worker.start()

    return jsonify({
        "status": job["status"],
        "case_id": case_id,
        "vendor_name": vendor["name"],
        "job_id": job["id"],
        "job": job,
    }), 202


@app.route("/api/cases/<case_id>/analysis-status")
@require_auth("ai:analyze")
def api_get_ai_analysis_status(case_id):
    if not HAS_AI:
        return jsonify({"error": "AI analysis module not available"}), 501

    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404

    user_id = _current_user_id()
    input_hash = _current_analysis_input_hash(case_id)
    cached = get_latest_analysis(case_id, user_id=user_id, input_hash=input_hash)
    if cached:
        return jsonify({
            "status": "ready",
            "case_id": case_id,
            "vendor_name": vendor["name"],
            "analysis": cached,
        })

    _ensure_ai_job_tables()
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM ai_analysis_jobs
            WHERE case_id = ? AND created_by = ? AND input_hash = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (case_id, user_id, input_hash),
        ).fetchone()
    if row:
        job = _analysis_job_row_to_dict(row)
        if job.get("status") in {"pending", "running"}:
            warmed = _wait_for_primed_ai_analysis(
                case_id,
                user_id,
                input_hash,
                job["id"],
                get_latest_analysis,
                wait_seconds=_AI_STATUS_WAIT_SECONDS,
                poll_seconds=0.25,
            )
            if warmed:
                if warmed.get("status") == "ready":
                    cached = get_latest_analysis(case_id, user_id=user_id, input_hash=input_hash)
                    if cached:
                        return jsonify({
                            "status": "ready",
                            "case_id": case_id,
                            "vendor_name": vendor["name"],
                            "analysis": cached,
                        })
                if warmed.get("status") == "failed":
                    return jsonify({
                        "status": "failed",
                        "case_id": case_id,
                        "vendor_name": vendor["name"],
                        "job": {
                            **job,
                            "status": "failed",
                            "error": warmed.get("error"),
                        },
                    })
        return jsonify({
            "status": job["status"],
            "case_id": case_id,
            "vendor_name": vendor["name"],
            "job": job,
        })

    primed = _prime_ai_analysis_for_case(
        case_id,
        user_id,
        wait_seconds=0,
        poll_seconds=0.0,
    )
    if primed.get("status") == "ready":
        cached = get_latest_analysis(case_id, user_id=user_id, input_hash=input_hash)
        if cached:
            return jsonify({
                "status": "ready",
                "case_id": case_id,
                "vendor_name": vendor["name"],
                "analysis": cached,
            })
    if primed.get("status") not in {"missing", "disabled", "skipped"}:
        payload = {
            "status": primed.get("status"),
            "case_id": case_id,
            "vendor_name": vendor["name"],
        }
        if primed.get("job_id"):
            payload["job"] = {
                "id": primed.get("job_id"),
                "status": primed.get("status"),
                "analysis_id": primed.get("analysis_id"),
                "input_hash": primed.get("input_hash"),
                "error": primed.get("error"),
            }
        return jsonify(payload)

    return jsonify({
        "status": "missing",
        "case_id": case_id,
        "vendor_name": vendor["name"],
    })


@app.route("/api/cases/<case_id>/analysis")
@require_auth("ai:analyze")
def api_get_ai_analysis(case_id):
    if not HAS_AI:
        return jsonify({"error": "AI analysis module not available"}), 501

    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404

    analysis = get_latest_analysis(
        case_id,
        user_id=_current_user_id(),
        input_hash=_current_analysis_input_hash(case_id),
    )
    if not analysis:
        return jsonify({"error": "No AI analysis found for this case"}), 404

    return jsonify({
        "case_id": case_id,
        "vendor_name": vendor["name"],
        "analysis": analysis["analysis"],
        "provider": analysis["provider"],
        "model": analysis["model"],
        "prompt_tokens": analysis["prompt_tokens"],
        "completion_tokens": analysis["completion_tokens"],
        "elapsed_ms": analysis["elapsed_ms"],
        "created_at": analysis["created_at"],
        "created_by": analysis["created_by"],
        "input_hash": analysis.get("input_hash"),
        "prompt_version": analysis.get("prompt_version"),
    })



# ---- Decisions ----

@app.route("/api/cases/<case_id>/decision", methods=["POST"])
@require_auth("cases:decide")
def api_save_decision(case_id):
    """Save a decision for a vendor case."""
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    reason = body.get("reason")
    
    if decision not in {"approve", "reject", "escalate"}:
        return jsonify({"error": "decision must be one of approve, reject, escalate"}), 400

    latest_score = db.get_latest_score(case_id) or {}
    calibrated = latest_score.get("calibrated", {})

    row_id = db.save_decision(
        case_id,
        decision,
        user_id=_current_user_id(),
        email=_current_user_email(),
        reason=reason,
        posterior=calibrated.get("calibrated_probability"),
        tier=calibrated.get("calibrated_tier"),
    )
    
    log_audit("decision_saved", "case", case_id, 
              detail=f"Decision: {decision}")
    
    return jsonify({
        "decision_id": row_id,
        "vendor_id": case_id,
        "decision": decision,
        "decided_by": _current_user_id(),
        "decided_by_email": _current_user_email(),
        "reason": reason,
        "posterior_at_decision": calibrated.get("calibrated_probability"),
        "tier_at_decision": calibrated.get("calibrated_tier"),
        "created_at": datetime.now().isoformat(),
    }), 201


@app.route("/api/cases/<case_id>/decisions", methods=["GET"])
@require_auth("cases:read")
def api_get_decisions(case_id):
    """Get all decisions for a vendor case."""
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    
    decisions = db.get_decisions(case_id, request.args.get("limit", 50, type=int))
    return jsonify({
        "vendor_id": case_id,
        "decisions": decisions,
        "latest_decision": decisions[0] if decisions else None,
    })

# ---- Portfolio Intelligence (Phase 4) ----

try:
    from portfolio_intelligence import (
        ScoreDriftDetector, PortfolioAnalytics
    )
    HAS_PORTFOLIO_INTEL = True
except ImportError:
    HAS_PORTFOLIO_INTEL = False


@app.route("/api/portfolio/snapshot")
@require_auth("portfolio:read")
def api_portfolio_snapshot():
    """Get current portfolio risk posture snapshot."""
    if not HAS_PORTFOLIO_INTEL:
        return jsonify({"error": "Portfolio intelligence module not available"}), 501
    try:
        from dataclasses import asdict
        snapshot = PortfolioAnalytics.current_snapshot()
        return jsonify(asdict(snapshot))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/beta/feedback", methods=["POST"])
@require_auth("cases:read")
@rate_limit(max_requests=40, window_seconds=60)
def api_submit_beta_feedback():
    body = request.get_json(silent=True) or {}
    summary = (body.get("summary") or "").strip()
    details = (body.get("details") or "").strip()
    category = (body.get("category") or "general").strip().lower()
    severity = (body.get("severity") or "medium").strip().lower()
    workflow_lane = (body.get("workflow_lane") or "").strip().lower()
    screen = (body.get("screen") or "").strip().lower()
    case_id = (body.get("case_id") or "").strip() or None
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}

    if not summary:
        return jsonify({"error": "summary is required"}), 400
    if len(summary) > 240:
        return jsonify({"error": "summary must be 240 characters or fewer"}), 400
    if len(details) > 4000:
        return jsonify({"error": "details must be 4000 characters or fewer"}), 400
    if category not in {"bug", "confusion", "request", "general"}:
        return jsonify({"error": "invalid category"}), 400
    if severity not in {"low", "medium", "high"}:
        return jsonify({"error": "invalid severity"}), 400
    if workflow_lane and workflow_lane not in {"counterparty", "cyber", "export"}:
        return jsonify({"error": "invalid workflow_lane"}), 400
    if case_id and not db.get_vendor(case_id):
        return jsonify({"error": "Case not found"}), 404

    feedback_id = db.save_beta_feedback(
        user_id=_current_user_id(),
        user_email=_current_user_email(),
        user_role=_current_user_role(),
        case_id=case_id,
        workflow_lane=workflow_lane,
        screen=screen,
        category=category,
        severity=severity,
        summary=summary,
        details=details,
        metadata=metadata,
    )
    log_audit(
        "beta_feedback_submitted",
        "beta_feedback",
        str(feedback_id),
        detail=f"{category}:{severity}:{workflow_lane or 'unspecified'}",
    )
    return jsonify({"status": "ok", "feedback_id": feedback_id}), 201


@app.route("/api/beta/events", methods=["POST"])
@require_auth("cases:read")
@rate_limit(max_requests=300, window_seconds=60)
def api_record_beta_event():
    body = request.get_json(silent=True) or {}
    event_name = (body.get("event_name") or "").strip().lower()
    if not event_name:
        return jsonify({"error": "event_name is required"}), 400
    if len(event_name) > 80:
        return jsonify({"error": "event_name must be 80 characters or fewer"}), 400

    workflow_lane = (body.get("workflow_lane") or "").strip().lower()
    screen = (body.get("screen") or "").strip().lower()
    case_id = (body.get("case_id") or "").strip() or None
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}

    if workflow_lane and workflow_lane not in {"counterparty", "cyber", "export"}:
        return jsonify({"error": "invalid workflow_lane"}), 400
    if case_id and not db.get_vendor(case_id):
        return jsonify({"error": "Case not found"}), 404

    event_id = db.save_beta_event(
        user_id=_current_user_id(),
        user_email=_current_user_email(),
        user_role=_current_user_role(),
        case_id=case_id,
        workflow_lane=workflow_lane,
        screen=screen,
        event_name=event_name,
        metadata=metadata,
    )
    return jsonify({"status": "ok", "event_id": event_id}), 201


@app.route("/api/beta/feedback", methods=["GET"])
@require_auth("cases:read")
def api_list_beta_feedback():
    if _current_user_role() not in {"admin", "auditor"}:
        return jsonify({"error": "Forbidden"}), 403
    limit = request.args.get("limit", 100, type=int)
    status = (request.args.get("status", "") or "").strip().lower()
    workflow_lane = (request.args.get("workflow_lane", "") or "").strip().lower()
    entries = db.list_beta_feedback(limit=limit, status=status, workflow_lane=workflow_lane)
    return jsonify({"feedback": entries})


@app.route("/api/beta/ops/summary", methods=["GET"])
@require_auth("cases:read")
def api_beta_ops_summary():
    if _current_user_role() not in {"admin", "auditor"}:
        return jsonify({"error": "Forbidden"}), 403
    hours = request.args.get("hours", 168, type=int)
    return jsonify(db.get_beta_ops_summary(hours=hours))


@app.route("/api/cases/<case_id>/export-artifacts")
@require_auth("cases:read")
def api_list_export_artifacts(case_id):
    if not HAS_EXPORT_ARTIFACTS:
        return jsonify({"error": "Export artifact intake not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    limit = request.args.get("limit", 20, type=int)
    records = [
        _serialize_export_artifact(record)
        for record in list_case_artifacts(case_id, limit=limit)
        if record.get("source_system") == "export_artifact_upload"
    ]
    return jsonify({"case_id": case_id, "artifacts": [record for record in records if record]})


@app.route("/api/cases/<case_id>/export-artifacts", methods=["POST"])
@require_auth("cases:score")
def api_upload_export_artifact(case_id):
    if not HAS_EXPORT_ARTIFACTS:
        return jsonify({"error": "Export artifact intake not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Missing artifact file"}), 400

    artifact_type = (request.form.get("artifact_type") or "").strip()
    if artifact_type not in SUPPORTED_EXPORT_ARTIFACT_TYPES:
        return jsonify(
            {
                "error": "Unsupported artifact_type",
                "supported_artifact_types": sorted(SUPPORTED_EXPORT_ARTIFACT_TYPES),
            }
        ), 400

    content = upload.stream.read()
    if not content:
        return jsonify({"error": "Uploaded artifact is empty"}), 400

    record = ingest_export_artifact(
        case_id,
        artifact_type,
        upload.filename,
        content,
        uploaded_by=_current_user_id(),
        effective_date=(request.form.get("effective_date") or "").strip() or None,
        notes=request.form.get("notes", ""),
        declared_classification=request.form.get("declared_classification", ""),
        declared_jurisdiction=request.form.get("declared_jurisdiction", ""),
    )
    log_audit(
        "export_artifact_uploaded",
        "case",
        case_id,
        detail=f"{artifact_type} uploaded for {v['name']}",
    )
    return jsonify({"case_id": case_id, "artifact": _serialize_export_artifact(record)}), 201


@app.route("/api/cases/<case_id>/export-artifacts/<artifact_id>")
@require_auth("cases:read")
def api_download_export_artifact(case_id, artifact_id):
    if not HAS_EXPORT_ARTIFACTS:
        return jsonify({"error": "Export artifact intake not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    record = get_artifact_record(artifact_id)
    if not record or record.get("case_id") != case_id or record.get("source_system") != "export_artifact_upload":
        return jsonify({"error": "Artifact not found"}), 404

    payload = read_artifact_bytes(artifact_id)
    return send_file(
        io.BytesIO(payload),
        mimetype=record.get("content_type") or "application/octet-stream",
        as_attachment=True,
        download_name=record.get("filename") or f"{artifact_id}.bin",
    )


@app.route("/api/cases/<case_id>/foci-artifacts")
@require_auth("cases:read")
def api_list_foci_artifacts(case_id):
    if not HAS_FOCI_ARTIFACTS:
        return jsonify({"error": "FOCI artifact intake not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    limit = request.args.get("limit", 20, type=int)
    records = [
        _serialize_artifact_record(record)
        for record in list_case_artifacts(case_id, limit=limit)
        if record.get("source_system") == "foci_artifact_upload"
    ]
    return jsonify({"case_id": case_id, "artifacts": [record for record in records if record]})


@app.route("/api/cases/<case_id>/foci-artifacts", methods=["POST"])
@require_auth("cases:score")
def api_upload_foci_artifact(case_id):
    if not HAS_FOCI_ARTIFACTS:
        return jsonify({"error": "FOCI artifact intake not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Missing FOCI artifact file"}), 400

    artifact_type = (request.form.get("artifact_type") or "").strip()
    if artifact_type not in SUPPORTED_FOCI_ARTIFACT_TYPES:
        return jsonify(
            {
                "error": "Unsupported artifact_type",
                "supported_artifact_types": sorted(SUPPORTED_FOCI_ARTIFACT_TYPES),
            }
        ), 400

    content = upload.stream.read()
    if not content:
        return jsonify({"error": "Uploaded FOCI artifact is empty"}), 400

    record = ingest_foci_artifact(
        case_id,
        artifact_type,
        upload.filename or "",
        content,
        uploaded_by=_current_user_id(),
        effective_date=(request.form.get("effective_date") or "").strip() or None,
        notes=request.form.get("notes", ""),
        declared_foreign_owner=request.form.get("declared_foreign_owner", ""),
        declared_foreign_country=request.form.get("declared_foreign_country", ""),
        declared_foreign_ownership_pct=request.form.get("declared_foreign_ownership_pct", ""),
        declared_mitigation_status=request.form.get("declared_mitigation_status", ""),
        declared_mitigation_type=request.form.get("declared_mitigation_type", ""),
    )
    log_audit(
        "foci_artifact_uploaded",
        "case",
        case_id,
        detail=f"{artifact_type} uploaded for {v['name']}",
    )
    return jsonify({"case_id": case_id, "artifact": _serialize_artifact_record(record)}), 201


@app.route("/api/cases/<case_id>/foci-artifacts/<artifact_id>")
@require_auth("cases:read")
def api_download_foci_artifact(case_id, artifact_id):
    if not HAS_FOCI_ARTIFACTS:
        return jsonify({"error": "FOCI artifact intake not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    record = get_artifact_record(artifact_id)
    if not record or record.get("case_id") != case_id or record.get("source_system") != "foci_artifact_upload":
        return jsonify({"error": "FOCI artifact not found"}), 404

    payload = read_artifact_bytes(artifact_id)
    return send_file(
        io.BytesIO(payload),
        mimetype=record.get("content_type") or "application/octet-stream",
        as_attachment=True,
        download_name=record.get("filename") or f"{artifact_id}.bin",
    )


@app.route("/api/cases/<case_id>/sprs-imports")
@require_auth("cases:read")
def api_list_sprs_imports(case_id):
    if not HAS_SPRS_IMPORT:
        return jsonify({"error": "SPRS import intake not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    limit = request.args.get("limit", 20, type=int)
    records = [
        _serialize_artifact_record(record)
        for record in list_case_artifacts(case_id, artifact_type=SPRS_ARTIFACT_TYPE, limit=limit)
        if record.get("source_system") == "sprs_import"
    ]
    return jsonify({"case_id": case_id, "imports": [record for record in records if record]})


@app.route("/api/cases/<case_id>/sprs-imports", methods=["POST"])
@require_auth("cases:score")
def api_upload_sprs_import(case_id):
    if not HAS_SPRS_IMPORT:
        return jsonify({"error": "SPRS import intake not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Missing SPRS export file"}), 400

    filename = upload.filename or ""
    if not filename.lower().endswith((".csv", ".json")):
        return jsonify({"error": "SPRS export must be .csv or .json"}), 400

    content = upload.stream.read()
    if not content:
        return jsonify({"error": "Uploaded SPRS export is empty"}), 400

    record = ingest_sprs_export(
        case_id,
        v["name"],
        filename,
        content,
        uploaded_by=_current_user_id(),
        effective_date=(request.form.get("effective_date") or "").strip() or None,
        notes=request.form.get("notes", ""),
    )
    log_audit(
        "sprs_import_uploaded",
        "case",
        case_id,
        detail=f"SPRS export uploaded for {v['name']}",
    )
    return jsonify({"case_id": case_id, "import": _serialize_artifact_record(record)}), 201


@app.route("/api/cases/<case_id>/sprs-imports/<artifact_id>")
@require_auth("cases:read")
def api_download_sprs_import(case_id, artifact_id):
    if not HAS_SPRS_IMPORT:
        return jsonify({"error": "SPRS import intake not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    record = get_artifact_record(artifact_id)
    if not record or record.get("case_id") != case_id or record.get("source_system") != "sprs_import":
        return jsonify({"error": "SPRS import not found"}), 404

    payload = read_artifact_bytes(artifact_id)
    return send_file(
        io.BytesIO(payload),
        mimetype=record.get("content_type") or "application/octet-stream",
        as_attachment=True,
        download_name=record.get("filename") or f"{artifact_id}.bin",
    )


@app.route("/api/cases/<case_id>/oscal-artifacts")
@require_auth("cases:read")
def api_list_oscal_artifacts(case_id):
    if not HAS_OSCAL_INTAKE:
        return jsonify({"error": "OSCAL intake not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    limit = request.args.get("limit", 20, type=int)
    records = [
        _serialize_artifact_record(record)
        for record in list_case_artifacts(case_id, limit=limit)
        if record.get("source_system") == "oscal_upload"
    ]
    return jsonify({"case_id": case_id, "artifacts": [record for record in records if record]})


@app.route("/api/cases/<case_id>/oscal-artifacts", methods=["POST"])
@require_auth("cases:score")
def api_upload_oscal_artifact(case_id):
    if not HAS_OSCAL_INTAKE:
        return jsonify({"error": "OSCAL intake not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Missing OSCAL file"}), 400

    filename = upload.filename or ""
    if not filename.lower().endswith(".json"):
        return jsonify({"error": "OSCAL upload must be .json"}), 400

    content = upload.stream.read()
    if not content:
        return jsonify({"error": "Uploaded OSCAL artifact is empty"}), 400

    try:
        record = ingest_oscal_artifact(
            case_id,
            filename,
            content,
            uploaded_by=_current_user_id(),
            effective_date=(request.form.get("effective_date") or "").strip() or None,
            notes=request.form.get("notes", ""),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    log_audit(
        "oscal_artifact_uploaded",
        "case",
        case_id,
        detail=f"{record['artifact_type']} uploaded for {v['name']}",
    )
    return jsonify({"case_id": case_id, "artifact": _serialize_artifact_record(record)}), 201


@app.route("/api/cases/<case_id>/oscal-artifacts/<artifact_id>")
@require_auth("cases:read")
def api_download_oscal_artifact(case_id, artifact_id):
    if not HAS_OSCAL_INTAKE:
        return jsonify({"error": "OSCAL intake not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    record = get_artifact_record(artifact_id)
    if not record or record.get("case_id") != case_id or record.get("source_system") != "oscal_upload":
        return jsonify({"error": "OSCAL artifact not found"}), 404

    payload = read_artifact_bytes(artifact_id)
    return send_file(
        io.BytesIO(payload),
        mimetype=record.get("content_type") or "application/json",
        as_attachment=True,
        download_name=record.get("filename") or f"{artifact_id}.json",
    )


@app.route("/api/cases/<case_id>/nvd-overlays")
@require_auth("cases:read")
def api_list_nvd_overlays(case_id):
    if not HAS_NVD_OVERLAY:
        return jsonify({"error": "NVD overlay not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    limit = request.args.get("limit", 20, type=int)
    records = [
        _serialize_artifact_record(record)
        for record in list_case_artifacts(case_id, artifact_type=NVD_OVERLAY_ARTIFACT_TYPE, limit=limit)
        if record.get("source_system") == "nvd_overlay"
    ]
    return jsonify({"case_id": case_id, "overlays": [record for record in records if record]})


@app.route("/api/cases/<case_id>/nvd-overlays", methods=["POST"])
@require_auth("cases:score")
def api_run_nvd_overlay(case_id):
    if not HAS_NVD_OVERLAY:
        return jsonify({"error": "NVD overlay not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    body = request.get_json(silent=True) or {}
    raw_terms = body.get("product_terms") or []
    if isinstance(raw_terms, str):
        raw_terms = [term.strip() for part in raw_terms.splitlines() for term in part.split(",")]
    elif not isinstance(raw_terms, list):
        raw_terms = []

    product_terms = [str(term or "").strip() for term in raw_terms if str(term or "").strip()]
    if not product_terms:
        return jsonify({"error": "At least one product term is required"}), 400

    try:
        record = create_nvd_overlay_artifact(
            case_id,
            v["name"],
            product_terms,
            uploaded_by=_current_user_id(),
            notes=str(body.get("notes") or "").strip(),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"NVD overlay failed: {exc}"}), 502

    log_audit(
        "nvd_overlay_generated",
        "case",
        case_id,
        detail=f"NVD overlay generated for {v['name']}",
    )
    return jsonify({"case_id": case_id, "overlay": _serialize_artifact_record(record)}), 201


@app.route("/api/cases/<case_id>/nvd-overlays/<artifact_id>")
@require_auth("cases:read")
def api_download_nvd_overlay(case_id, artifact_id):
    if not HAS_NVD_OVERLAY:
        return jsonify({"error": "NVD overlay not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    record = get_artifact_record(artifact_id)
    if not record or record.get("case_id") != case_id or record.get("source_system") != "nvd_overlay":
        return jsonify({"error": "NVD overlay not found"}), 404

    payload = read_artifact_bytes(artifact_id)
    return send_file(
        io.BytesIO(payload),
        mimetype=record.get("content_type") or "application/json",
        as_attachment=True,
        download_name=record.get("filename") or f"{artifact_id}.json",
    )


# ---- Cyber Risk Scoring & Graph ----

@app.route("/api/cases/<case_id>/cyber-risk-score", methods=["POST"])
@require_auth("cases:read")
def api_cyber_risk_score(case_id):
    """Compute multi-dimensional cyber risk score for a vendor.

    Returns composite score across 5 dimensions: CMMC readiness,
    vulnerability exposure, remediation posture, supply chain propagation,
    and compliance maturity.
    """
    if not HAS_CYBER_SCORING:
        return jsonify({"error": "Cyber risk scoring module not available"}), 501

    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    # Gather all available cyber evidence
    sprs_summary = None
    oscal_summary = None
    nvd_summary = None
    graph_data = None

    if HAS_CYBER_EVIDENCE:
        cyber_ev = get_latest_cyber_evidence_summary(case_id)
        if cyber_ev:
            sprs_summary = {
                "current_cmmc_level": cyber_ev.get("current_cmmc_level"),
                "assessment_date": cyber_ev.get("assessment_date"),
                "assessment_status": cyber_ev.get("assessment_status"),
                "poam_active": cyber_ev.get("poam_active"),
            }
            oscal_summary = {
                "total_control_references": cyber_ev.get("total_control_references", 0),
                "open_poam_items": cyber_ev.get("open_poam_items", 0),
                "system_name": cyber_ev.get("system_name", ""),
            }
            nvd_summary = {
                "high_or_critical_cve_count": cyber_ev.get("high_or_critical_cve_count", 0),
                "critical_cve_count": cyber_ev.get("critical_cve_count", 0),
                "kev_flagged_cve_count": cyber_ev.get("kev_flagged_cve_count", 0),
                "product_terms": cyber_ev.get("product_terms", []),
            }

    if HAS_CYBER_GRAPH:
        try:
            graph_data = build_cyber_subgraph(case_id)
        except Exception:
            pass

    body = request.get_json(silent=True) or {}
    profile = body.get("profile") or v.get("profile") or ""

    result = score_vendor_cyber_risk(
        case_id=case_id,
        vendor_name=v.get("name"),
        sprs_summary=sprs_summary,
        nvd_summary=nvd_summary,
        oscal_summary=oscal_summary,
        graph_data=graph_data,
        profile=profile,
    )

    log_audit("cyber_risk_scored", "case", case_id,
              detail=f"Cyber risk: {result.get('cyber_risk_tier')} ({result.get('cyber_risk_score', 0):.2f})")

    return jsonify({"case_id": case_id, "vendor_name": v.get("name"), **result})


@app.route("/api/cases/<case_id>/cyber-subgraph")
@require_auth("graph:read")
def api_cyber_subgraph(case_id):
    """Get the cyber-relevant portion of the knowledge graph for a case."""
    if not HAS_CYBER_GRAPH:
        return jsonify({"error": "Cyber graph module not available"}), 501

    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    try:
        subgraph = build_cyber_subgraph(case_id)
        return jsonify({"case_id": case_id, "vendor_name": v.get("name"), **subgraph})
    except Exception as e:
        return jsonify({"error": f"Cyber subgraph failed: {str(e)}"}), 500


@app.route("/api/portfolio/trend")
@require_auth("portfolio:read")
def api_portfolio_trend():
    """Get portfolio risk trend over time."""
    if not HAS_PORTFOLIO_INTEL:
        return jsonify({"error": "Portfolio intelligence module not available"}), 501
    days = request.args.get("days", 30, type=int)
    try:
        trend = PortfolioAnalytics.portfolio_trend(days=days)
        return jsonify({"trend": trend, "days": days})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cases/<case_id>/drift", methods=["POST"])
@require_auth("monitor:run")
def api_check_drift(case_id):
    """Run score drift detection on a specific vendor."""
    if not HAS_PORTFOLIO_INTEL:
        return jsonify({"error": "Portfolio intelligence module not available"}), 501
    try:
        from dataclasses import asdict
        detector = ScoreDriftDetector()
        result = detector.check(case_id)
        if not result:
            return jsonify({"error": "No baseline score to compare against"}), 404
        # Fire alert if threshold exceeded
        if abs(result.delta_pp) >= detector.ALERT_THRESHOLD_PP:
            direction = "increased" if result.delta_pp > 0 else "decreased"
            db.save_alert(
                case_id, result.vendor_name, result.severity,
                f"Score drift: {result.previous_score}% -> {result.current_score}% "
                f"({direction} {abs(result.delta_pp):.1f}pp)",
                f"Tier: {result.previous_tier} -> {result.current_tier}. "
                f"Top factor changes: {', '.join(f['factor'] for f in result.factors_changed[:3])}"
            )
        return jsonify(asdict(result))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/portfolio/anomalies")
@require_auth("portfolio:read")
def api_portfolio_anomalies():
    """Get recent anomaly alerts."""
    limit = request.args.get("limit", 50, type=int)
    alerts = db.list_alerts(limit=limit, unresolved_only=True)
    anomaly_alerts = [a for a in alerts if any(
        tag in a.get("title", "").upper()
        for tag in ["SANCTIONS_HIT", "OWNERSHIP_CHANGE", "MEDIA_SPIKE",
                     "FINANCIAL_DOWNGRADE", "DEBARMENT", "SCORE DRIFT"]
    )]
    return jsonify({"anomalies": anomaly_alerts, "total": len(anomaly_alerts)})


# ---- Entity Resolution / Knowledge Graph ----

# Sprint 5 graph endpoint removed -- superseded by Sprint 6 api_case_graph() below


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


@app.route("/api/graph/shortest-path", methods=["POST"])
@require_auth("graph:read")
def api_shortest_path():
    """Find shortest path between two entities in the knowledge graph."""
    if not HAS_KG:
        return jsonify({"error": "Knowledge graph module not available"}), 501

    data = request.get_json(silent=True) or {}
    source_id = data.get("source_id")
    target_id = data.get("target_id")
    max_depth = data.get("max_depth", 6)

    if not source_id or not target_id:
        return jsonify({"error": "source_id and target_id required"}), 400

    if source_id == target_id:
        return jsonify({
            "path": [],
            "found": True,
            "hops": 0,
            "source_id": source_id,
            "target_id": target_id,
            "message": "Source and target are the same entity",
        })

    kg.init_kg_db()
    path = kg.find_shortest_path(source_id, target_id, max_depth)

    if path is None:
        return jsonify({
            "path": None,
            "found": False,
            "hops": 0,
            "source_id": source_id,
            "target_id": target_id,
            "message": f"No path found within {max_depth} hops",
        })

    return jsonify({
        "path": path,
        "found": True,
        "hops": len(path),
        "source_id": source_id,
        "target_id": target_id,
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
@rate_limit(max_requests=10, window_seconds=60)
def api_enrich_case(case_id):
    """Run OSINT enrichment against a vendor case. Stores results in DB."""
    if not HAS_OSINT:
        return jsonify({"error": "OSINT enrichment module not available"}), 501

    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    body = request.get_json(silent=True) or {}
    connectors = _resolve_enrichment_connectors(v, body.get("connectors", None))
    parallel = body.get("parallel", True)
    force = bool(body.get("force", False))

    report = enrich_vendor(
        vendor_name=v["name"],
        country=v["country"],
        connectors=connectors,
        parallel=parallel,
        force=force,
        **_enrichment_seed_identifiers(case_id),
    )

    _persist_enrichment_artifacts(case_id, v, report)

    log_audit("enrichment_run", "case", case_id,
              detail=f"OSINT enrichment on {v['name']}: {report.get('overall_risk', 'unknown')} risk")
    return jsonify(report)


@app.route("/api/cases/<case_id>/enrich-stream")
@require_auth("cases:enrich")
def api_enrich_case_stream(case_id):
    if not HAS_OSINT:
        return jsonify({"error": "OSINT enrichment module not available"}), 501

    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404
    force = str(request.args.get("force", "")).strip().lower() in {"1", "true", "yes", "on"}

    def _sse(event: str, payload: dict | None = None):
        body = json.dumps(payload or {})
        return f"event: {event}\ndata: {body}\n\n"

    @stream_with_context
    def _generate():
        report = None
        try:
            connectors = _default_enrichment_connectors(vendor)
            for event_name, payload in enrich_vendor_streaming(
                vendor_name=vendor["name"],
                country=vendor["country"],
                connectors=connectors,
                force=force,
                **_enrichment_seed_identifiers(case_id),
            ):
                if event_name == "complete":
                    report = payload
                yield _sse(event_name, payload)

            if report is None:
                raise RuntimeError("Enrichment stream did not produce a final report")

            _persist_enrichment_artifacts(case_id, vendor, report)
            score_dict = _canonical_rescore_from_enrichment(case_id, vendor, report)["score_dict"]
            ai_analysis = _prime_ai_analysis_for_case(case_id, _current_user_id())

            log_audit(
                "enrichment_stream_run",
                "case",
                case_id,
                detail=f"Streaming enrichment on {vendor['name']}: {report.get('overall_risk', 'unknown')} risk",
            )
            yield _sse("scored", {
                "calibrated_tier": score_dict["calibrated"].get("calibrated_tier", "UNSCORED"),
                "calibrated_probability": score_dict["calibrated"].get("calibrated_probability", 0.0),
                "is_hard_stop": score_dict.get("is_hard_stop", False),
                "composite_score": score_dict.get("composite_score", 0),
            })
            yield _sse("analysis", ai_analysis)
            yield _sse("done", {"case_id": case_id})
        except Exception as err:
            yield _sse("error", {"error": str(err)})

    return Response(_generate(), mimetype="text/event-stream")


@app.route("/api/cases/<case_id>/enrichment")
@require_auth("enrich:read")
def api_get_enrichment(case_id):
    """Get the latest OSINT enrichment report for a vendor case."""
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    report = _current_enrichment_report(case_id)
    if not report:
        return jsonify({"error": "No enrichment report found. Run POST /api/cases/{id}/enrich first."}), 404

    if HAS_INTEL:
        report_hash = report.get("report_hash") or compute_report_hash(report)
        events = db.get_case_events(case_id, report_hash)
        if not events:
            events = _persist_case_events(case_id, v, report)
        report["events"] = events
        report["intel_summary"] = db.get_latest_intel_summary(
            case_id,
            user_id=_current_user_id(),
            report_hash=report_hash,
        )
    else:
        report["events"] = []
        report["intel_summary"] = None

    # Attach cache freshness info
    try:
        from osint.cache import get_cache
        freshness = get_cache().vendor_freshness(v["name"])
        report["cache_freshness"] = freshness
    except Exception:
        report["cache_freshness"] = None

    return jsonify(_augment_connector_status(case_id, report))


@app.route("/api/cases/<case_id>/cache-freshness")
@require_auth("enrich:read")
def api_cache_freshness(case_id):
    """Get enrichment cache freshness details for a vendor case."""
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    try:
        from osint.cache import get_cache
        freshness = get_cache().vendor_freshness(v["name"])
        return jsonify(freshness)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/graph/connections/<vendor_a>/<vendor_b>")
@require_auth("enrich:read")
def api_graph_connections(vendor_a, vendor_b):
    """Find shared connections between two vendors."""
    try:
        from knowledge_graph import find_shared_connections, init_kg_db
        init_kg_db()
        connections = find_shared_connections(vendor_a, vendor_b)
        return jsonify({"connections": connections, "count": len(connections)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/graph/backfill", methods=["POST"])
@require_auth("admin:write")
def api_graph_backfill():
    """Replay all stored enrichment reports into the knowledge graph."""
    try:
        from graph_ingest import backfill_all_vendors
        stats = backfill_all_vendors()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/graph/seed-enrich/<case_id>", methods=["POST"])
@require_auth("cases:enrich")
def api_seed_enrich(case_id):
    """Seed-enrich discovered entities for a vendor (mini-assessment pipeline)."""
    body = request.get_json(silent=True) or {}
    max_entities = min(body.get("max_entities", 10), 25)
    try:
        from graph_ingest import seed_enrich_discovered_entities
        results = seed_enrich_discovered_entities(case_id, max_entities=max_entities)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/graph/cascade-risk/<case_id>")
@require_auth("enrich:read")
def api_cascade_risk(case_id):
    """Check for cascade risk in a vendor's network."""
    try:
        from graph_ingest import check_cascade_risk
        alerts = check_cascade_risk(case_id)
        return jsonify({"alerts": alerts, "count": len(alerts)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/graph/concentration")
@require_auth("enrich:read")
def api_concentration():
    """Find entities that appear across multiple vendors (single-point-of-failure risk)."""
    top_n = request.args.get("top", 10, type=int)
    try:
        from graph_ingest import get_portfolio_concentration
        data = get_portfolio_concentration(top_n=top_n)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cases/<case_id>/network-risk")
@require_auth("enrich:read")
def api_vendor_network_risk(case_id):
    """Compute network risk score for a specific vendor via graph propagation."""
    if not HAS_NETWORK_RISK:
        return jsonify({"error": "Network risk module not available"}), 501
    try:
        result = compute_network_risk(case_id)
        if result.get("network_risk_level") == "none" and result.get("note") in {"No graph entities", "No relationships in graph"}:
            v = db.get_vendor(case_id)
            report = _current_enrichment_report(case_id)
            if v and report:
                _ingest_case_graph(case_id, v, report)
                result = compute_network_risk(case_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/graph/network-risk")
@require_auth("enrich:read")
def api_portfolio_network_risk():
    """Compute network risk scores for all vendors in the portfolio."""
    if not HAS_NETWORK_RISK:
        return jsonify({"error": "Network risk module not available"}), 501
    try:
        result = compute_portfolio_network_risk()
        portfolio_stats = result.get("portfolio_stats", {})
        if (
            portfolio_stats.get("total_vendors", 0) > 0
            and portfolio_stats.get("vendors_with_network_risk", 0) == 0
            and HAS_KG
        ):
            try:
                from graph_ingest import backfill_all_vendors

                backfill_all_vendors()
                result = compute_portfolio_network_risk()
            except Exception as err:
                LOGGER.debug("Portfolio graph backfill skipped: %s", err)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/graph/context/<vendor_name>")
@require_auth("enrich:read")
def api_graph_context(vendor_name):
    """Get pre-populated context for a vendor from the knowledge graph."""
    try:
        from graph_ingest import get_pre_populated_context
        import urllib.parse
        decoded = urllib.parse.unquote(vendor_name)
        context = get_pre_populated_context(decoded)
        return jsonify(context)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---- Graph Workspaces ----

@app.route("/api/graph/workspaces", methods=["POST"])
@require_auth("graph:write")
def api_create_workspace():
    """Create a new analyst graph workspace."""
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    if not name:
        return jsonify({"error": "Missing required field: name"}), 400

    created_by = g.get("user_email", "unknown")
    workspace_id = f"ws-{uuid.uuid4().hex[:12]}"

    try:
        ws = db.create_workspace(
            workspace_id=workspace_id,
            name=name,
            created_by=created_by,
            description=body.get("description", ""),
            pinned_nodes=body.get("pinned_nodes"),
            annotations=body.get("annotations"),
            filter_state=body.get("filter_state"),
            layout_mode=body.get("layout_mode", "cose"),
            viewport=body.get("viewport"),
            node_positions=body.get("node_positions"),
        )
        log_audit("workspace_created", "workspace", workspace_id,
                  detail=f"Created workspace '{name}' by {created_by}")
        return jsonify(ws), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/graph/workspaces", methods=["GET"])
@require_auth("graph:read")
def api_list_workspaces():
    """List all analyst graph workspaces, optionally filtered by creator."""
    created_by_filter = request.args.get("created_by", None)
    try:
        workspaces = db.list_workspaces(created_by=created_by_filter)
        return jsonify({"workspaces": workspaces, "total": len(workspaces)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/graph/workspaces/<workspace_id>", methods=["GET"])
@require_auth("graph:read")
def api_get_workspace(workspace_id):
    """Get a specific analyst graph workspace by ID."""
    try:
        ws = db.get_workspace(workspace_id)
        if not ws:
            return jsonify({"error": "Workspace not found"}), 404
        return jsonify(ws)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/graph/workspaces/<workspace_id>", methods=["PUT"])
@require_auth("graph:write")
def api_update_workspace(workspace_id):
    """Update a specific analyst graph workspace."""
    ws = db.get_workspace(workspace_id)
    if not ws:
        return jsonify({"error": "Workspace not found"}), 404

    body = request.get_json(silent=True) or {}

    try:
        updated_ws = db.update_workspace(workspace_id, **body)
        log_audit("workspace_updated", "workspace", workspace_id,
                  detail=f"Updated workspace '{ws['name']}'")
        return jsonify(updated_ws)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/graph/workspaces/<workspace_id>", methods=["DELETE"])
@require_auth("graph:write")
def api_delete_workspace(workspace_id):
    """Delete a specific analyst graph workspace."""
    ws = db.get_workspace(workspace_id)
    if not ws:
        return jsonify({"error": "Workspace not found"}), 404

    try:
        deleted = db.delete_workspace(workspace_id)
        if deleted:
            log_audit("workspace_deleted", "workspace", workspace_id,
                      detail=f"Deleted workspace '{ws['name']}'")
            return jsonify({"deleted": True})
        return jsonify({"error": "Failed to delete workspace"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
@rate_limit(max_requests=20, window_seconds=60)
def api_enrich_and_score(case_id):
    """Run OSINT enrichment, augment scoring inputs, then score through the
    canonical two-layer pipeline (_score_and_persist). Single scoring path."""
    if not HAS_OSINT:
        return jsonify({"error": "OSINT enrichment module not available"}), 501

    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    body = request.get_json(silent=True) or {}
    connectors = _resolve_enrichment_connectors(v, body.get("connectors", None))
    force = bool(body.get("force", False))

    # Step 1: Run OSINT enrichment
    report = enrich_vendor(
        vendor_name=v["name"],
        country=v["country"],
        connectors=connectors,
        force=force,
        **_enrichment_seed_identifiers(case_id),
    )
    persisted = _persist_enrichment_artifacts(case_id, v, report)
    rescored = _canonical_rescore_from_enrichment(case_id, v, report)
    augmentation = rescored["augmentation"]
    score_dict = rescored["score_dict"]
    ai_analysis = _prime_ai_analysis_for_case(case_id, _current_user_id())

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
            "provenance": augmentation.provenance,
        },
        "scoring": {
            "composite_score": score_dict["composite_score"],
            "is_hard_stop": score_dict["is_hard_stop"],
            "calibrated": score_dict["calibrated"],
        },
        "graph": persisted["graph"],
        "ai_analysis": ai_analysis,
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
        "policy_basis": result.policy_basis,
    }

    # Log the screening
    db.log_screening(vendor_name, result_dict)
    log_audit("screening_run", "vendor", vendor_name,
              detail=f"OFAC screen: {'MATCH' if result.matched else 'APPROVED'}")
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
    sources = {}
    if HAS_SYNC:
        sources.update({
            k: {"label": v["label"], "format": v["format"]}
            for k, v in sanctions_sync.SOURCES.items()
        })
    if HAS_BIS:
        sources["bis"] = {"label": "BIS Consolidated Screening List", "format": "json"}
    return jsonify({"sources": sources})


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


# ---- Person/POI Screening (export control & deemed export) ----

@app.route("/api/export/screen-person", methods=["POST"])
@require_auth("screen:run")
def api_screen_person():
    """Screen a person against sanctions lists with deemed export evaluation.

    Body:
    {
        "name": "John Doe",
        "nationalities": ["CN", "HK"],
        "employer": "Huawei",
        "item_classification": "USML-Aircraft",
        "access_level": "SECRET",
        "case_id": "case-123"
    }
    """
    if not HAS_PERSON_SCREENING:
        return jsonify({"error": "person_screening module not available"}), 501

    body = request.get_json(silent=True) or {}
    person_name = body.get("name", "")
    if not person_name:
        return jsonify({"error": "Missing 'name' field"}), 400

    # Initialize database
    try:
        init_person_screening_db()
    except Exception as e:
        return jsonify({"error": f"Database initialization failed: {str(e)}"}), 500

    # Get user ID for audit trail
    user_id = getattr(g, '_current_user_id', None) or "anonymous"

    try:
        result = screen_person(
            name=person_name,
            nationalities=body.get("nationalities"),
            employer=body.get("employer"),
            item_classification=body.get("item_classification"),
            access_level=body.get("access_level"),
            case_id=body.get("case_id"),
            screened_by=user_id,
        )

        result_dict = {
            "id": result.id,
            "case_id": result.case_id,
            "person_name": result.person_name,
            "nationalities": result.nationalities,
            "employer": result.employer,
            "screening_status": result.screening_status,
            "composite_score": round(result.composite_score, 4),
            "matched_lists": result.matched_lists,
            "deemed_export": result.deemed_export,
            "recommended_action": result.recommended_action,
            "created_at": result.created_at,
        }

        # Ingest into knowledge graph (non-blocking, best-effort)
        graph_ingest_result = None
        if HAS_PERSON_GRAPH_INGEST:
            try:
                graph_ingest_result = ingest_person_screening(result, case_id=body.get("case_id"))
                result_dict["graph_ingest"] = graph_ingest_result
            except Exception as ge:
                logging.getLogger(__name__).warning(f"Person graph ingest failed (non-fatal): {ge}")

        # Check network risk from graph (enriches response)
        if HAS_PERSON_GRAPH_INGEST and result.screening_status == "CLEAR":
            try:
                network_risk = get_person_network_risk(
                    person_name, body.get("nationalities", [])
                )
                if network_risk.get("network_risk_level") not in ("CLEAR", "UNKNOWN"):
                    result_dict["network_risk"] = network_risk
            except Exception:
                pass

        # Log audit trail
        log_audit("person_screening", "person", person_name,
                  detail=f"Status: {result.screening_status}")

        return jsonify(result_dict)

    except Exception as e:
        log_audit("person_screening_error", "person", person_name,
                  detail=f"Error: {str(e)}")
        return jsonify({"error": f"Screening failed: {str(e)}"}), 500


@app.route("/api/export/screen-batch", methods=["POST"])
@require_auth("screen:run")
def api_screen_batch():
    """Screen multiple persons in a batch operation (max 50).

    Body:
    {
        "persons": [
            {
                "name": "John Doe",
                "nationalities": ["CN"],
                "employer": "Huawei",
                "item_classification": "USML-Aircraft",
                "case_id": "case-123"
            },
            ...
        ]
    }
    """
    if not HAS_PERSON_SCREENING:
        return jsonify({"error": "person_screening module not available"}), 501

    body = request.get_json(silent=True) or {}
    persons = body.get("persons", [])
    if not persons:
        return jsonify({"error": "Missing 'persons' field"}), 400
    if len(persons) > 50:
        return jsonify({"error": "Batch screening limited to 50 persons"}), 400

    # Initialize database
    try:
        init_person_screening_db()
    except Exception as e:
        return jsonify({"error": f"Database initialization failed: {str(e)}"}), 500

    user_id = getattr(g, '_current_user_id', None) or "anonymous"

    try:
        results = screen_person_batch(persons, screened_by=user_id)

        result_dicts = [
            {
                "id": r.id,
                "case_id": r.case_id,
                "person_name": r.person_name,
                "nationalities": r.nationalities,
                "employer": r.employer,
                "screening_status": r.screening_status,
                "composite_score": round(r.composite_score, 4),
                "matched_lists": r.matched_lists,
                "deemed_export": r.deemed_export,
                "recommended_action": r.recommended_action,
                "created_at": r.created_at,
            }
            for r in results
        ]

        # Ingest batch into knowledge graph (best-effort)
        graph_ingest_summary = None
        if HAS_PERSON_GRAPH_INGEST:
            try:
                graph_ingest_summary = ingest_batch_screenings(results, case_id=persons[0].get("case_id") if persons else None)
            except Exception as ge:
                logging.getLogger(__name__).warning(f"Batch person graph ingest failed (non-fatal): {ge}")

        log_audit("batch_person_screening", "batch", f"{len(persons)} persons",
                  detail=f"Screened {len(persons)} persons")

        resp = {"screenings": result_dicts, "count": len(result_dicts)}
        if graph_ingest_summary:
            resp["graph_ingest"] = graph_ingest_summary
        return jsonify(resp)

    except Exception as e:
        log_audit("batch_person_screening_error", "batch", "",
                  detail=f"Error: {str(e)}")
        return jsonify({"error": f"Batch screening failed: {str(e)}"}), 500


@app.route("/api/export/screen-batch-csv", methods=["POST"])
@require_auth("screen:run")
def api_screen_batch_csv():
    """Screen multiple persons from a CSV file upload (max 50 rows).

    Expects multipart/form-data with:
      - file: CSV with columns: name (required), nationalities, employer
      - case_id: optional case to associate screenings with

    CSV columns (case-insensitive, flexible naming):
      - name / person_name / full_name  (REQUIRED)
      - nationalities / nationality / country  (comma-separated ISO-2 codes within cell)
      - employer / organization / affiliation
    """
    if not HAS_PERSON_SCREENING:
        return jsonify({"error": "person_screening module not available"}), 501

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "CSV file is required"}), 400

    case_id = request.form.get("case_id", "")

    try:
        text = upload.stream.read().decode("utf-8-sig")
    except Exception:
        return jsonify({"error": "Could not read uploaded file as UTF-8 CSV"}), 400

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return jsonify({"error": "CSV must include a header row"}), 400

    # Flexible column mapping
    field_map = {f.strip().lower(): f for f in reader.fieldnames if f}
    name_col = field_map.get("name") or field_map.get("person_name") or field_map.get("full_name")
    nat_col = field_map.get("nationalities") or field_map.get("nationality") or field_map.get("country")
    emp_col = field_map.get("employer") or field_map.get("organization") or field_map.get("affiliation")

    if not name_col:
        return jsonify({"error": "CSV must include a 'name' column (also accepts person_name, full_name)"}), 400

    parsed = []
    for raw in reader:
        name_val = (raw.get(name_col) or "").strip()
        if not name_val:
            continue
        nat_val = (raw.get(nat_col) or "").strip() if nat_col else ""
        nationalities = [n.strip().upper() for n in nat_val.split(",") if n.strip()] if nat_val else []
        employer_val = (raw.get(emp_col) or "").strip() if emp_col else ""
        parsed.append({
            "name": name_val,
            "nationalities": nationalities,
            "employer": employer_val or None,
            "case_id": case_id or None,
        })

    if not parsed:
        return jsonify({"error": "CSV did not contain any valid person rows"}), 400
    if len(parsed) > 50:
        return jsonify({"error": "Batch screening limited to 50 persons per CSV"}), 400

    try:
        init_person_screening_db()
    except Exception as e:
        return jsonify({"error": f"Database initialization failed: {str(e)}"}), 500

    user_id = getattr(g, '_current_user_id', None) or "anonymous"

    try:
        results = screen_person_batch(parsed, screened_by=user_id)

        result_dicts = [
            {
                "id": r.id,
                "case_id": r.case_id,
                "person_name": r.person_name,
                "nationalities": r.nationalities,
                "employer": r.employer,
                "screening_status": r.screening_status,
                "composite_score": round(r.composite_score, 4),
                "matched_lists": r.matched_lists,
                "deemed_export": r.deemed_export,
                "recommended_action": r.recommended_action,
                "created_at": r.created_at,
            }
            for r in results
        ]

        # Ingest batch into knowledge graph (best-effort)
        graph_ingest_summary = None
        if HAS_PERSON_GRAPH_INGEST:
            try:
                graph_ingest_summary = ingest_batch_screenings(results, case_id=case_id or None)
            except Exception as ge:
                logging.getLogger(__name__).warning(f"CSV batch person graph ingest failed (non-fatal): {ge}")

        log_audit("batch_csv_person_screening", "batch", f"{len(parsed)} persons",
                  detail=f"CSV batch screened {len(parsed)} persons from {upload.filename}")

        resp = {
            "screenings": result_dicts,
            "count": len(result_dicts),
            "filename": upload.filename,
        }
        if graph_ingest_summary:
            resp["graph_ingest"] = graph_ingest_summary
        return jsonify(resp)

    except Exception as e:
        log_audit("batch_csv_person_screening_error", "batch", "",
                  detail=f"Error: {str(e)}")
        return jsonify({"error": f"Batch CSV screening failed: {str(e)}"}), 500


@app.route("/api/export/screenings/<case_id>")
@require_auth("screen:read")
def api_get_case_screenings(case_id):
    """Get all person screenings for a case.

    Returns:
    {
        "case_id": "case-123",
        "screenings": [...]
    }
    """
    if not HAS_PERSON_SCREENING:
        return jsonify({"error": "person_screening module not available"}), 501

    try:
        init_person_screening_db()
        results = get_case_screenings(case_id)

        result_dicts = [
            {
                "id": r.id,
                "case_id": r.case_id,
                "person_name": r.person_name,
                "nationalities": r.nationalities,
                "employer": r.employer,
                "screening_status": r.screening_status,
                "composite_score": round(r.composite_score, 4),
                "matched_lists": r.matched_lists,
                "deemed_export": r.deemed_export,
                "recommended_action": r.recommended_action,
                "created_at": r.created_at,
            }
            for r in results
        ]

        return jsonify({
            "case_id": case_id,
            "screenings": result_dicts,
            "count": len(result_dicts),
        })

    except Exception as e:
        return jsonify({"error": f"Failed to retrieve screenings: {str(e)}"}), 500


# ---- Graph Analytics API ----

@app.route("/api/graph/analytics/intelligence")
@require_auth("screen:read")
def api_graph_intelligence():
    """Full graph intelligence dashboard payload.
    Returns centrality leaders, risk distribution, community structure, and temporal profile.
    """
    if not HAS_GRAPH_ANALYTICS:
        return jsonify({"error": "Graph analytics module not available"}), 501

    try:
        analytics = _get_graph_analytics()
        result = analytics.compute_graph_intelligence()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Graph analytics failed: {str(e)}"}), 500


@app.route("/api/graph/analytics/centrality")
@require_auth("screen:read")
def api_graph_centrality():
    """Compute centrality metrics for all entities.
    Returns degree, betweenness, closeness, pagerank, and structural vs decision importance.
    """
    if not HAS_GRAPH_ANALYTICS:
        return jsonify({"error": "Graph analytics module not available"}), 501

    try:
        analytics = _get_graph_analytics()
        result = analytics.compute_all_centrality()
        # Sort by decision importance for operator-facing use.
        sorted_entities = sorted(result.values(), key=lambda x: x.get("decision_importance", x.get("composite_importance", 0)), reverse=True)
        return jsonify({"entities": sorted_entities, "count": len(sorted_entities)})
    except Exception as e:
        return jsonify({"error": f"Centrality computation failed: {str(e)}"}), 500


@app.route("/api/graph/analytics/communities")
@require_auth("screen:read")
def api_graph_communities():
    """Detect communities in the knowledge graph using the strongest available engine."""
    if not HAS_GRAPH_ANALYTICS:
        return jsonify({"error": "Graph analytics module not available"}), 501

    try:
        analytics = _get_graph_analytics()
        result = analytics.detect_communities()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Community detection failed: {str(e)}"}), 500


@app.route("/api/graph/analytics/path", methods=["POST"])
@require_auth("screen:read")
def api_graph_path():
    """Find paths between two entities.
    Body: {"source": "entity_id", "target": "entity_id", "mode": "shortest|critical|all"}
    """
    if not HAS_GRAPH_ANALYTICS:
        return jsonify({"error": "Graph analytics module not available"}), 501

    body = request.get_json(silent=True) or {}
    source = body.get("source", "")
    target = body.get("target", "")
    mode = body.get("mode", "shortest")

    if not source or not target:
        return jsonify({"error": "Both 'source' and 'target' entity IDs required"}), 400

    try:
        analytics = _get_graph_analytics()

        if mode == "critical":
            result = analytics.critical_path(source, target)
        elif mode == "all":
            result = analytics.all_paths(source, target)
        else:
            result = analytics.shortest_path(source, target)

        if result is None:
            return jsonify({"error": "No path found between entities"}), 404

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Path analysis failed: {str(e)}"}), 500


@app.route("/api/graph/analytics/sanctions-exposure")
@require_auth("screen:read")
def api_graph_sanctions_exposure():
    """Compute sanctions exposure scores for all entities via network propagation."""
    if not HAS_GRAPH_ANALYTICS:
        return jsonify({"error": "Graph analytics module not available"}), 501

    try:
        analytics = _get_graph_analytics()
        result = analytics.compute_sanctions_exposure()
        # Return sorted by exposure
        sorted_entities = sorted(
            [{"entity_id": k, "entity_name": analytics.nodes.get(k, {}).get("canonical_name", ""), **v}
             for k, v in result.items()],
            key=lambda x: x["exposure_score"],
            reverse=True,
        )
        return jsonify({"entities": sorted_entities, "count": len(sorted_entities)})
    except Exception as e:
        return jsonify({"error": f"Sanctions exposure computation failed: {str(e)}"}), 500


@app.route("/api/graph/analytics/temporal")
@require_auth("screen:read")
def api_graph_temporal():
    """Compute temporal profile of graph activity (timeline, bursts, growth)."""
    if not HAS_GRAPH_ANALYTICS:
        return jsonify({"error": "Graph analytics module not available"}), 501

    try:
        analytics = _get_graph_analytics()
        result = analytics.compute_temporal_profile()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Temporal analysis failed: {str(e)}"}), 500


@app.route("/api/graph/full-intelligence", methods=["GET"])
@require_auth("screen:read")
def api_graph_full_intelligence():
    """Combined endpoint: graph data + centrality + sanctions exposure + communities.
    Returns everything the Graph Intelligence Dashboard needs in one call."""
    if not HAS_GRAPH_ANALYTICS:
        return jsonify({"error": "Graph analytics not available"}), 503

    try:
        analytics = _get_graph_analytics()
    except Exception as e:
        return jsonify({"error": f"Graph load failed: {str(e)}"}), 500

    # Compute all analytics
    try:
        centrality = analytics.compute_all_centrality()
        communities = analytics.detect_communities()
        exposure = analytics.compute_sanctions_exposure()
        temporal = analytics.compute_temporal_profile()
    except Exception as e:
        return jsonify({"error": f"Analytics computation failed: {str(e)}"}), 500

    # Build enriched node list with analytics scores
    enriched_nodes = []
    for node_id, node_data in analytics.nodes.items():
        cent = centrality.get(node_id, {})
        exp = exposure.get(node_id, {})
        comm = communities.get("node_labels", {}).get(node_id)

        enriched_nodes.append({
            "id": node_id,
            "canonical_name": node_data.get("canonical_name", ""),
            "entity_type": node_data.get("entity_type", "unknown"),
            "confidence": node_data.get("confidence", 0),
            "country": node_data.get("country", ""),
            "created_at": node_data.get("created_at", ""),
            # Analytics enrichment
            "centrality_composite": round(cent.get("composite_importance", 0), 4),
            "centrality_structural": round(cent.get("structural_importance", 0), 4),
            "centrality_decision": round(cent.get("decision_importance", cent.get("composite_importance", 0)), 4),
            "centrality_degree": round(cent.get("degree", {}).get("normalized", 0) if isinstance(cent.get("degree"), dict) else cent.get("degree", 0), 4),
            "centrality_betweenness": round(cent.get("betweenness", {}).get("normalized", 0) if isinstance(cent.get("betweenness"), dict) else cent.get("betweenness", 0), 4),
            "centrality_pagerank": round(cent.get("pagerank", {}).get("normalized", 0) if isinstance(cent.get("pagerank"), dict) else cent.get("pagerank", 0), 4),
            "sanctions_exposure": round(exp.get("exposure_score", 0), 4),
            "risk_level": exp.get("risk_level", "CLEAR"),
            "community_id": comm,
        })

    # Build edge list
    edges = []
    for edge in analytics.edges:
        edges.append({
            "source_entity_id": edge.get("source"),
            "target_entity_id": edge.get("target"),
            "rel_type": edge.get("rel_type", "related_entity"),
            "confidence": edge.get("confidence", 0.5),
            "data_source": edge.get("data_source", ""),
            "evidence": edge.get("evidence", ""),
            "created_at": edge.get("created_at", ""),
        })

    # Summary stats
    risk_dist = {"CLEAR": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for n in enriched_nodes:
        risk_dist[n.get("risk_level", "CLEAR")] = risk_dist.get(n.get("risk_level", "CLEAR"), 0) + 1

    type_dist = {}
    for n in enriched_nodes:
        t = n.get("entity_type", "unknown")
        type_dist[t] = type_dist.get(t, 0) + 1

    # Top entities by composite centrality
    top_by_importance = sorted(enriched_nodes, key=lambda x: x["centrality_decision"], reverse=True)[:20]
    top_by_structural_importance = sorted(enriched_nodes, key=lambda x: x["centrality_structural"], reverse=True)[:20]
    top_by_risk = sorted(enriched_nodes, key=lambda x: x["sanctions_exposure"], reverse=True)[:20]

    return jsonify({
        "nodes": enriched_nodes,
        "edges": edges,
        "summary": {
            "total_nodes": len(enriched_nodes),
            "total_edges": len(edges),
            "risk_distribution": risk_dist,
            "type_distribution": type_dist,
            "community_count": communities.get("count", 0),
            "modularity": round(communities.get("modularity", 0), 4),
        },
        "top_by_importance": top_by_importance,
        "top_by_structural_importance": top_by_structural_importance,
        "top_by_risk": top_by_risk,
        "communities": [
            {
                "community_id": label,
                "size": cdata.get("size", 0),
                "members": [m.get("id", "") if isinstance(m, dict) else m for m in cdata.get("members", [])],
                "dominant_type": max(set(cdata.get("types", ["unknown"])), key=cdata.get("types", ["unknown"]).count) if cdata.get("types") else "unknown",
            }
            for label, cdata in communities.get("communities", {}).items()
        ],
        "temporal": temporal,
    })


# ---- Person Network Risk (graph-aware) ----

@app.route("/api/export/person-network-risk", methods=["POST"])
@require_auth("screen:read")
def api_person_network_risk():
    """Query the knowledge graph for network risk around a screened person.

    Body:
    {
        "name": "John Doe",
        "nationalities": ["CN"]
    }

    Returns risk signals from the entity network (sanctions connections,
    employer links, deemed export associations) even if the person
    personally cleared screening.
    """
    if not HAS_PERSON_GRAPH_INGEST:
        return jsonify({"error": "Person graph ingest module not available"}), 501

    body = request.get_json(silent=True) or {}
    name = body.get("name", "")
    if not name:
        return jsonify({"error": "Missing 'name' field"}), 400

    try:
        result = get_person_network_risk(name, body.get("nationalities", []))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Network risk query failed: {str(e)}"}), 500


# ---- Export Monitoring ----

@app.route("/api/export/monitor/sweep", methods=["POST"])
@require_auth("screen:run")
def api_export_monitor_sweep():
    """Run an export monitoring sweep.
    Re-screens persons whose screening interval has elapsed.

    Body (optional):
    {
        "max_persons": 50,
        "mode": "full" | "time_based" | "graph_triggered"
    }
    """
    if not HAS_EXPORT_MONITOR:
        return jsonify({"error": "Export monitor module not available"}), 501

    body = request.get_json(silent=True) or {}
    max_persons = body.get("max_persons", 50)
    mode = body.get("mode", "full")

    try:
        monitor = ExportMonitor()

        if mode == "graph_triggered":
            result = monitor.run_graph_triggered_sweep()
        elif mode == "time_based":
            result = monitor.run_sweep(max_persons=max_persons)
        else:
            result = monitor.run_full_sweep()

        log_audit("export_monitor_sweep", "export", mode,
                  detail=f"Rescreened {result.get('persons_rescreened', 0)} persons, "
                         f"{len(result.get('status_changes', []))} status changes, "
                         f"{len(result.get('graph_triggers', []))} graph triggers")

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": f"Export monitoring sweep failed: {str(e)}"}), 500


# ---- Transaction Authorization (S12-01) ----

@app.route("/api/export/authorize", methods=["POST"])
@require_auth("screen:run")
def api_export_authorize():
    """Run full transaction authorization pipeline.

    Body:
    {
        "jurisdiction_guess": "ear",
        "request_type": "physical_export",
        "classification_guess": "3A001",
        "item_or_data_summary": "Xilinx FPGAs for radar signal processing",
        "destination_country": "GB",
        "destination_company": "Meridian UK Ltd",
        "end_use_summary": "UK MoD radar program integration",
        "end_user_name": "UK Ministry of Defence",
        "access_context": "NATO-cleared contractor facility",
        "persons": [
            {
                "name": "Dr. Wei Chen",
                "nationalities": ["CN", "GB"],
                "employer": "Meridian UK Ltd",
                "role": "Lead FPGA Engineer"
            }
        ],
        "case_id": "demo-meridian-uk",
        "requested_by": "analyst@example.com"
    }

    Returns: Full TransactionAuthorization with combined posture,
    component results, and recommended next steps.
    """
    if not HAS_TX_AUTH:
        return jsonify({"error": "Transaction authorization module not available"}), 501

    body = request.get_json(silent=True) or {}

    if not body.get("destination_country") and not body.get("classification_guess"):
        return jsonify({"error": "Provide at least destination_country or classification_guess"}), 400

    # Inject requesting user from auth context
    if hasattr(request, "user_email"):
        body.setdefault("requested_by", request.user_email)

    try:
        result = authorize_transaction(body)

        log_audit("transaction_authorization", "export", result.get("id", ""),
                  detail=f"Posture: {result.get('combined_posture_label')}, "
                         f"persons: {len(result.get('person_results', []))}, "
                         f"duration: {result.get('duration_ms')}ms")

        return jsonify(result)

    except Exception as e:
        LOGGER.exception("Transaction authorization failed: %s", e)
        return jsonify({"error": f"Authorization pipeline failed: {str(e)}"}), 500


@app.route("/api/export/authorizations", methods=["GET"])
@require_auth("screen:read")
def api_export_authorizations_list():
    """List transaction authorizations with optional filters.

    Query params:
        case_id: Filter by case
        posture: Filter by combined_posture
        limit: Max results (default 50)
    """
    if not HAS_TX_AUTH:
        return jsonify({"error": "Transaction authorization module not available"}), 501

    case_id = request.args.get("case_id")
    posture = request.args.get("posture")
    limit = min(int(request.args.get("limit", 50)), 200)

    try:
        with db.get_conn() as conn:
            # Ensure table exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transaction_authorizations (
                    id TEXT PRIMARY KEY,
                    case_id TEXT,
                    transaction_type TEXT NOT NULL,
                    classification TEXT,
                    destination_country TEXT,
                    destination_company TEXT,
                    end_user TEXT,
                    combined_posture TEXT NOT NULL,
                    combined_posture_label TEXT,
                    confidence REAL,
                    rules_posture TEXT,
                    rules_confidence REAL,
                    graph_posture TEXT,
                    graph_elevated BOOLEAN DEFAULT 0,
                    persons_screened INTEGER DEFAULT 0,
                    person_summary JSON,
                    license_exception JSON,
                    escalation_reasons JSON,
                    blocking_factors JSON,
                    all_factors JSON,
                    recommended_next_step TEXT,
                    rules_guidance JSON,
                    graph_intelligence JSON,
                    person_results JSON,
                    pipeline_log JSON,
                    requested_by TEXT,
                    duration_ms REAL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (case_id) REFERENCES vendors(id) ON DELETE SET NULL
                )
            """)

            query = "SELECT id, case_id, transaction_type, classification, destination_country, destination_company, end_user, combined_posture, combined_posture_label, confidence, rules_posture, graph_posture, graph_elevated, persons_screened, person_summary, escalation_reasons, blocking_factors, recommended_next_step, requested_by, duration_ms, created_at FROM transaction_authorizations WHERE 1=1"
            params = []
            if case_id:
                query += " AND case_id = ?"
                params.append(case_id)
            if posture:
                query += " AND combined_posture = ?"
                params.append(posture)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                for json_field in ("person_summary", "escalation_reasons", "blocking_factors"):
                    if d.get(json_field) and isinstance(d[json_field], str):
                        try:
                            d[json_field] = json.loads(d[json_field])
                        except (json.JSONDecodeError, TypeError):
                            pass
                results.append(d)

            return jsonify({"authorizations": results, "count": len(results)})

    except Exception as e:
        return jsonify({"error": f"Failed to list authorizations: {str(e)}"}), 500


@app.route("/api/export/authorizations/<auth_id>", methods=["GET"])
@require_auth("screen:read")
def api_export_authorization_detail(auth_id):
    """Get full detail for a single transaction authorization."""
    if not HAS_TX_AUTH:
        return jsonify({"error": "Transaction authorization module not available"}), 501

    try:
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM transaction_authorizations WHERE id = ?",
                (auth_id,)
            ).fetchone()

            if not row:
                return jsonify({"error": "Authorization not found"}), 404

            d = dict(row)
            for json_field in ("person_summary", "license_exception", "escalation_reasons",
                             "blocking_factors", "all_factors", "rules_guidance",
                             "graph_intelligence", "person_results", "pipeline_log"):
                if d.get(json_field) and isinstance(d[json_field], str):
                    try:
                        d[json_field] = json.loads(d[json_field])
                    except (json.JSONDecodeError, TypeError):
                        pass

            return jsonify(d)

    except Exception as e:
        return jsonify({"error": f"Failed to get authorization: {str(e)}"}), 500


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
    db.migrate_add_profile_column()
    db.migrate_intelligence_tables()
    init_auth_db()
    if HAS_AI:
        init_ai_tables()
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

    periodic_monitoring_started = _maybe_start_periodic_monitoring()
    print(f"  Monitoring: {'enabled' if HAS_MONITOR else 'not available'}")
    if HAS_MONITOR_SCHEDULER:
        print(
            "  Periodic monitoring scheduler: "
            + ("started" if periodic_monitoring_started else "disabled")
        )
    print(f"  Dossier HTML: {'enabled' if HAS_DOSSIER else 'not available'}")
    print(f"  Dossier PDF: {'enabled' if HAS_DOSSIER_PDF else 'not available'}")
    print(f"  AI analysis: {'enabled' if HAS_AI else 'not available'}")
    print(f"  Network risk: {'enabled' if HAS_NETWORK_RISK else 'not available'}")
    if _RUNTIME_ENV_BOOTSTRAP.get("loaded"):
        print(f"  Runtime env: loaded ({_RUNTIME_ENV_BOOTSTRAP.get('path')})")
    elif _RUNTIME_ENV_BOOTSTRAP.get("error"):
        print(f"  Runtime env: load failed ({_RUNTIME_ENV_BOOTSTRAP.get('error')})")
    dev_mode = os.environ.get("XIPHOS_DEV_MODE", "false").lower() == "true"
    auth_mode = 'ENFORCED' if AUTH_ENABLED else ('DEV MODE (anonymous admin passthrough)' if dev_mode else 'AUTH DISABLED (protected routes still require a token)')
    print(f"  Auth/RBAC: {auth_mode}")

    stats = db.get_stats()
    print(f"\n{'='*50}")
    print("  HELIOS v5.0 -- Intelligence-Grade Vendor Assurance (FGAMLogit DoD Dual-Vertical)")
    print(f"  Persistence: SQLite ({db.get_db_path()})")
    print(f"  Vendors: {stats['vendors']}  Alerts: {stats['unresolved_alerts']}")
    print(f"  http://{args.host}:{args.port}")
    print(f"{'='*50}\n")
    _log_event(
        "startup",
        host=args.host,
        port=args.port,
        db_path=db.get_db_path(),
        data_dir=get_data_dir(),
        vendors=stats["vendors"],
        unresolved_alerts=stats["unresolved_alerts"],
        auth_enabled=AUTH_ENABLED,
        osint_enabled=HAS_OSINT,
    )

    app.run(host=args.host, port=args.port, debug=False)


# ============================================================================
# Graph Briefing PDF Export
# ============================================================================

@app.route("/api/graph/briefing", methods=["POST"])
@require_auth("screen:read")
def api_generate_graph_briefing():
    """Generate a professional, compliance-grade PDF briefing summarizing graph analytics.

    Accepts payload with optional enhanced fields:
    - title, subtitle, classification_marking, case_id
    - pinned_entities (array with id, name, type, risk_level, community, sources)
    - shortest_path (array of node objects with id, name)
    - propagation_summary (object with waves, total_affected, max_risk)
    - analyst_notes (free-text string)

    All new fields are optional; maintains backward compatibility.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        )
        from reportlab.lib.enums import TA_CENTER
        from io import BytesIO
    except ImportError:
        return jsonify({"error": "reportlab not available"}), 501

    body = request.get_json(silent=True) or {}

    # Upgraded payload fields
    title = body.get("title", "Graph Intelligence Briefing")
    subtitle = body.get("subtitle", "Network Analysis & Risk Assessment")
    classification_marking = body.get("classification_marking", "CUI // NOFORN")
    case_id = body.get("case_id", "")
    analyst = body.get("analyst", "analyst@xiphos.local")

    # Enhanced pinned entities (new format)
    pinned_entities = body.get("pinned_entities", [])
    # Backward compat: legacy pinned_nodes array
    if not pinned_entities and "pinned_nodes" in body:
        pinned_nodes = body.get("pinned_nodes", [])
        pinned_entities = [{"id": nid} for nid in pinned_nodes]

    # Graph metadata
    node_count = body.get("node_count", 0)
    edge_count = body.get("edge_count", 0)
    filter_summary = body.get("filter_summary", "None")
    layout_mode = body.get("layout_mode", "cose")

    # Enhanced analysis results
    shortest_path = body.get("shortest_path", None)
    propagation_summary = body.get("propagation_summary", None)

    # Analyst notes section
    analyst_notes = body.get("analyst_notes", "")

    # Legacy fields
    annotations = body.get("annotations", {})
    path_result = body.get("path_result")
    propagation_result = body.get("propagation_result")

    try:
        # Professional color palette
        NAVY = colors.HexColor("#1a2332")
        LIGHT_TEXT = colors.HexColor("#f0f4f8")
        SECONDARY_TEXT = colors.HexColor("#94a3b8")
        ACCENT = colors.HexColor("#3b82f6")
        GOLD = colors.HexColor("#c4a052")

        RISK_COLORS = {
            "CLEAR": colors.HexColor("#10b981"),
            "LOW": colors.HexColor("#06b6d4"),
            "MEDIUM": colors.HexColor("#f59e0b"),
            "HIGH": colors.HexColor("#ef4444"),
            "CRITICAL": colors.HexColor("#dc2626"),
        }

        # Create PDF with professional margins
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=letter,
            rightMargin=0.6*inch,
            leftMargin=0.6*inch,
            topMargin=1.0*inch,
            bottomMargin=0.8*inch,
        )

        # Define styles hierarchy
        styles = getSampleStyleSheet()

        # Header style (Helios branding)
        header_style = ParagraphStyle(
            'BriefingHeader',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=GOLD,
            spaceAfter=4,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold',
        )

        # Main title style
        title_style = ParagraphStyle(
            'BriefingTitle',
            parent=styles['Heading2'],
            fontSize=16,
            textColor=LIGHT_TEXT,
            spaceAfter=2,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold',
        )

        # Subtitle style
        subtitle_style = ParagraphStyle(
            'BriefingSubtitle',
            parent=styles['Normal'],
            fontSize=11,
            textColor=SECONDARY_TEXT,
            spaceAfter=8,
            alignment=TA_CENTER,
            fontName='Helvetica-Oblique',
        )

        # Section heading style
        section_heading_style = ParagraphStyle(
            'SectionHeading',
            parent=styles['Heading3'],
            fontSize=12,
            textColor=LIGHT_TEXT,
            spaceBefore=12,
            spaceAfter=8,
            fontName='Helvetica-Bold',
            borderColor=ACCENT,
            borderWidth=2,
            borderPadding=6,
            borderRadius=2,
        )

        # Body text style
        body_style = ParagraphStyle(
            'BriefingBody',
            parent=styles['Normal'],
            fontSize=9,
            textColor=SECONDARY_TEXT,
            spaceAfter=6,
            leading=12,
        )

        # Small text for metadata
        small_style = ParagraphStyle(
            'BriefingSmall',
            parent=styles['Normal'],
            fontSize=8,
            textColor=SECONDARY_TEXT,
            spaceAfter=4,
        )

        # Build story with professional structure
        story = []

        # ---- PROFESSIONAL HEADER ----
        # Classification banner top
        class_banner_data = [
            [classification_marking]
        ]
        class_banner = Table(class_banner_data, colWidths=[7.2*inch])
        class_banner.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), NAVY),
            ('TEXTCOLOR', (0, 0), (-1, -1), GOLD),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(class_banner)
        story.append(Spacer(1, 0.1*inch))

        # Xiphos Helios branding
        story.append(Paragraph("XIPHOS HELIOS", header_style))
        story.append(Paragraph("GRAPH INTELLIGENCE BRIEFING", title_style))
        story.append(Spacer(1, 0.05*inch))

        if subtitle:
            story.append(Paragraph(subtitle, subtitle_style))
        story.append(Spacer(1, 0.15*inch))

        # Metadata table (professional layout)
        gen_datetime = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        metadata_rows = [
            ["Classification", classification_marking],
            ["Generated", gen_datetime],
            ["Analyst", analyst],
        ]
        if case_id:
            metadata_rows.insert(0, ["Case Reference", case_id])
        if title and title != "Graph Intelligence Briefing":
            metadata_rows.insert(0, ["Brief Title", title])

        metadata_table = Table(
            metadata_rows,
            colWidths=[1.5*inch, 5.7*inch],
        )
        metadata_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), NAVY),
            ('BACKGROUND', (1, 0), (1, -1), colors.HexColor("#1e293b")),
            ('TEXTCOLOR', (0, 0), (-1, -1), LIGHT_TEXT),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, SECONDARY_TEXT),
        ]))
        story.append(metadata_table)
        story.append(Spacer(1, 0.2*inch))

        # ---- EXECUTIVE SUMMARY SECTION ----
        story.append(Paragraph("EXECUTIVE SUMMARY", section_heading_style))
        story.append(Spacer(1, 0.05*inch))

        # Key findings in structured format
        findings_text = f"""
        <b>Network Topology:</b> {node_count} entities, {edge_count} relationships<br/>
        <b>Analysis Mode:</b> {layout_mode} layout with {filter_summary} filters<br/>
        <b>Pinned Focus:</b> {len(pinned_entities)} key entities identified for detailed review<br/>
        <b>Risk Scope:</b> {"Propagation analysis active" if propagation_summary or propagation_result else "Path-based analysis"}
        """
        story.append(Paragraph(findings_text, body_style))
        story.append(Spacer(1, 0.1*inch))

        # ---- PINNED ENTITIES SECTION ----
        if pinned_entities:
            story.append(Paragraph("PINNED ENTITIES", section_heading_style))
            story.append(Spacer(1, 0.05*inch))

            pinned_table_data = [["Entity Name", "Type", "Risk Level", "Community", "Sources/Notes"]]

            for entity in pinned_entities:
                entity_id = entity.get("id")
                entity_name = entity.get("name", "Unknown")
                entity_type = entity.get("type", "unknown")
                risk_level = entity.get("risk_level", "CLEAR")
                community = entity.get("community", "—")
                sources = entity.get("sources", "")

                # Try legacy lookup if minimal entity data
                if not entity_name or entity_name == "Unknown":
                    try:
                        kg_entity = db.get_kg_entity(entity_id)
                        if kg_entity:
                            entity_name = kg_entity.get("canonical_name", entity_name)
                            entity_type = kg_entity.get("entity_type", entity_type)
                            risk_level = kg_entity.get("risk_level", risk_level)
                    except Exception:
                        pass

                # Add annotation if present
                note = annotations.get(entity_id, sources)

                pinned_table_data.append([
                    entity_name[:35],
                    entity_type.upper()[:15],
                    risk_level.upper()[:12],
                    str(community)[:12],
                    (note or "—")[:30],
                ])

            pinned_table = Table(
                pinned_table_data,
                colWidths=[1.6*inch, 1.0*inch, 1.0*inch, 0.9*inch, 2.7*inch],
            )

            # Professional table styling with alternating row colors
            table_style = [
                ('BACKGROUND', (0, 0), (-1, 0), NAVY),
                ('TEXTCOLOR', (0, 0), (-1, 0), LIGHT_TEXT),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('TOPPADDING', (0, 0), (-1, 0), 6),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('TOPPADDING', (0, 1), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#334155")),
            ]

            # Alternating row backgrounds
            for i in range(1, len(pinned_table_data)):
                if i % 2 == 0:
                    table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor("#0f172a")))
                else:
                    table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor("#1e293b")))

            # Color-code risk levels
            for i in range(1, len(pinned_table_data)):
                risk_val = pinned_table_data[i][2].upper()
                if risk_val in RISK_COLORS:
                    table_style.append(('TEXTCOLOR', (2, i), (2, i), RISK_COLORS[risk_val]))

            pinned_table.setStyle(TableStyle(table_style))
            story.append(pinned_table)
            story.append(Spacer(1, 0.15*inch))

        # ---- NETWORK ANALYSIS SECTION ----
        # Handle both legacy path_result and new shortest_path formats
        path_to_show = shortest_path or (path_result.get("path") if path_result else None)

        if path_to_show or path_result:
            story.append(Paragraph("SHORTEST PATH ANALYSIS", section_heading_style))
            story.append(Spacer(1, 0.05*inch))

            if shortest_path:
                source = shortest_path[0].get("name", "Unknown") if shortest_path else "Unknown"
                target = shortest_path[-1].get("name", "Unknown") if shortest_path else "Unknown"
                path_length = len(shortest_path) - 1 if len(shortest_path) > 1 else 0

                path_chain = " → ".join([
                    node.get("name", str(node.get("id", "?")))[:20]
                    for node in shortest_path[:15]
                ])
            else:
                source = path_result.get("source_name", "Unknown") if path_result else "Unknown"
                target = path_result.get("target_name", "Unknown") if path_result else "Unknown"
                path_length = len(path_result.get("path", [])) - 1 if path_result else 0
                path_chain = " → ".join([str(n)[:20] for n in (path_result.get("path", [])[:15] if path_result else [])])

            path_text = f"""
            <b>Source Entity:</b> {source}<br/>
            <b>Target Entity:</b> {target}<br/>
            <b>Minimum Hops:</b> {path_length} connection(s)<br/>
            <b>Path Chain:</b> {path_chain}
            """
            story.append(Paragraph(path_text, body_style))
            story.append(Spacer(1, 0.1*inch))

        # ---- RISK PROPAGATION SECTION ----
        # Handle both legacy propagation_result and new propagation_summary formats
        prop_to_show = propagation_summary or propagation_result

        if prop_to_show:
            story.append(Paragraph("RISK PROPAGATION ANALYSIS", section_heading_style))
            story.append(Spacer(1, 0.05*inch))

            if propagation_summary:
                source_name = propagation_summary.get("source_name", "Source Entity")
                total_affected = propagation_summary.get("total_affected", 0)
                max_hops = len(propagation_summary.get("waves", []))
                max_risk = propagation_summary.get("max_risk", 0.0)
            else:
                source_name = propagation_result.get("source_name", "Source Entity") if propagation_result else "Unknown"
                total_affected = propagation_result.get("total_nodes_affected", 0) if propagation_result else 0
                max_hops = len(propagation_result.get("waves", [])) if propagation_result else 0
                max_risk = propagation_result.get("max_risk", 0.0) if propagation_result else 0.0

            prop_text = f"""
            <b>Source Entity:</b> {source_name}<br/>
            <b>Cascade Reach:</b> {total_affected} entities affected<br/>
            <b>Max Propagation Depth:</b> {max_hops} hops<br/>
            <b>Peak Risk Score:</b> {max_risk:.3f}
            """
            story.append(Paragraph(prop_text, body_style))
            story.append(Spacer(1, 0.1*inch))

        # ---- ANALYST NOTES SECTION ----
        if analyst_notes:
            story.append(Paragraph("ANALYST NOTES", section_heading_style))
            story.append(Spacer(1, 0.05*inch))
            story.append(Paragraph(analyst_notes, body_style))
            story.append(Spacer(1, 0.15*inch))

        # ---- METHODOLOGY FOOTER ----
        story.append(Spacer(1, 0.2*inch))

        footer_text = (
            "<b>Methodology:</b> This briefing was generated by Helios graph analytics engine. "
            "All entity relationships are based on knowledge graph integration with OFAC SDN List, "
            "SEC EDGAR filings, and vendor enrichment databases. Risk scores reflect confidence levels "
            "and relationship weights. All analysis is advisory only and subject to independent compliance review. "
            "<br/><br/>"
            f"<b>Classification:</b> {classification_marking} | "
            f"<b>Document ID:</b> {case_id if case_id else 'AUTO-GENERATED'} | "
            f"<b>Generated:</b> {gen_datetime}"
        )
        story.append(Paragraph(footer_text, small_style))

        # Build PDF with professional structure
        doc.build(story)
        pdf_buffer.seek(0)

        log_audit("briefing_generated", "graph", title, detail=f"Compliance-grade PDF briefing generated by {analyst}")

        # Return with proper headers
        return pdf_buffer.getvalue(), 200, {
            "Content-Type": "application/pdf",
            "Content-Disposition": f"attachment; filename=helios-briefing-{case_id or 'auto'}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.pdf",
        }

    except Exception as e:
        return jsonify({"error": f"Failed to generate briefing: {str(e)}"}), 500


# ── Bulk Ingest Status ────────────────────────────────────────────────────
@app.route("/api/bulk-ingest/status")
@require_auth("enrich:read")
def api_bulk_ingest_status():
    """Read the bulk ingest status file written by bulk_ingest.py."""
    data_dir = os.environ.get("XIPHOS_DATA_DIR", os.path.dirname(__file__))
    backend_dir = os.path.dirname(__file__)
    # Check data dir first (Docker volume), then backend dir (host fallback)
    status_path = os.path.join(data_dir, "bulk_ingest_status.json")
    if not os.path.exists(status_path):
        status_path = os.path.join(backend_dir, "bulk_ingest_status.json")
    results_path = os.path.join(backend_dir, "bulk_ingest_results.json")

    # Prefer live status file (updated during runs)
    if os.path.exists(status_path):
        try:
            with open(status_path) as f:
                return jsonify(json.load(f))
        except Exception:
            pass

    # Fall back to completed results file
    if os.path.exists(results_path):
        try:
            with open(results_path) as f:
                data = json.load(f)
            return jsonify({
                "state": "completed",
                "total": data.get("created", 0) + len(data.get("errors", [])),
                "processed": data.get("created", 0) + len(data.get("errors", [])),
                "created": data.get("created", 0),
                "enriched": data.get("enriched", 0),
                "errors": len(data.get("errors", [])),
                "skipped": data.get("skipped", 0),
                "error_details": data.get("errors", [])[-5:],
            })
        except Exception:
            pass

    return jsonify({"state": "idle", "message": "No bulk ingest has been run yet."})


@app.route("/api/bulk-ingest/summary")
@require_auth("enrich:read")
def api_bulk_ingest_summary():
    """Risk distribution, top entities by centrality, and batch history."""
    with db.get_conn() as conn:
        cur = conn.cursor()

        # Risk distribution by calibrated tier (from scoring_results)
        cur.execute("""
            SELECT sr.calibrated_tier, COUNT(*) as cnt
            FROM scoring_results sr
            INNER JOIN (
                SELECT vendor_id, MAX(id) as latest_id
                FROM scoring_results GROUP BY vendor_id
            ) latest_sr ON sr.vendor_id = latest_sr.vendor_id AND sr.id = latest_sr.latest_id
            WHERE sr.calibrated_tier IS NOT NULL AND sr.calibrated_tier != ''
            GROUP BY sr.calibrated_tier
            ORDER BY cnt DESC
        """)
        risk_dist = {row[0]: row[1] for row in cur.fetchall()}

        # Total cases (deduplicated by name to match portfolio view)
        cur.execute("SELECT COUNT(DISTINCT LOWER(TRIM(name))) FROM vendors")
        total_cases = cur.fetchone()[0]

        # Score distribution (buckets from scoring_results.composite_score)
        cur.execute("""
            SELECT
                CASE
                    WHEN sr.composite_score IS NULL THEN 'unscored'
                    WHEN sr.composite_score <= 10 THEN '0-10 (low)'
                    WHEN sr.composite_score <= 25 THEN '11-25 (moderate)'
                    WHEN sr.composite_score <= 50 THEN '26-50 (elevated)'
                    WHEN sr.composite_score <= 75 THEN '51-75 (high)'
                    ELSE '76-100 (critical)'
                END as bucket,
                COUNT(*) as cnt
            FROM scoring_results sr
            INNER JOIN (
                SELECT vendor_id, MAX(id) as latest_id
                FROM scoring_results GROUP BY vendor_id
            ) latest_sr ON sr.vendor_id = latest_sr.vendor_id AND sr.id = latest_sr.latest_id
            GROUP BY bucket
            ORDER BY cnt DESC
        """)
        score_dist = {row[0]: row[1] for row in cur.fetchall()}

    # Top 15 entities by centrality from knowledge graph
    top_entities = []
    try:
        from runtime_paths import get_kg_db_path
        from knowledge_graph import init_kg_db
        import sqlite3 as _sqlite3
        init_kg_db()
        kg_path = get_kg_db_path()
        kgconn = _sqlite3.connect(kg_path)
        kgcur = kgconn.cursor()
        kgcur.execute("""
            SELECT e.canonical_name, e.entity_type, COUNT(DISTINCT r.id) as rel_count
            FROM kg_entities e
            LEFT JOIN kg_relationships r ON e.id = r.source_entity_id OR e.id = r.target_entity_id
            GROUP BY e.id
            ORDER BY rel_count DESC
            LIMIT 15
        """)
        top_entities = [{"name": r[0], "type": r[1], "connections": r[2]} for r in kgcur.fetchall()]
        kgconn.close()
    except Exception as exc:
        LOGGER.warning("Failed to compute top_entities_by_connections: %s", exc)

    # Batch history
    history = []
    history_path = os.path.join(os.path.dirname(__file__), "bulk_ingest_history.jsonl")
    if os.path.exists(history_path):
        try:
            with open(history_path) as f:
                for line in f:
                    if line.strip():
                        history.append(json.loads(line))
        except Exception:
            pass

    return jsonify({
        "total_cases": total_cases,
        "risk_distribution": risk_dist,
        "score_distribution": score_dist,
        "top_entities_by_connections": top_entities,
        "batch_history": history,
    })


# ── Lead Capture (SOF Week Vendor Intel Portal) ─────────────────────────────
@app.route("/api/leads", methods=["POST"])
def api_capture_lead():
    """Capture a lead from the SOF Week Vendor Intelligence portal.
    No auth required - this is a public-facing endpoint."""
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    company = (data.get("company") or "").strip()
    role = (data.get("role") or "").strip()
    source = (data.get("source") or "sof-week-portal").strip()

    if not name or not email or not company:
        return jsonify({"error": "name, email, and company are required"}), 400

    with db.get_conn() as conn:
        cur = conn.cursor()

        # Create leads table if it doesn't exist (PostgreSQL compatible)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                company TEXT NOT NULL,
                role TEXT DEFAULT '',
                source TEXT DEFAULT 'sof-week-portal',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT DEFAULT ''
            )
        """)

        # Check for duplicate by email
        cur.execute("SELECT id FROM leads WHERE LOWER(email) = LOWER(?)", (email,))
        existing = cur.fetchone()
        if existing:
            return jsonify({"status": "already_submitted", "message": "We already have your request. A specialist will be in touch soon."})

        cur.execute(
            "INSERT INTO leads (name, email, company, role, source) VALUES (?, ?, ?, ?, ?)",
            (name, email, company, role, source)
        )

    return jsonify({"status": "captured", "message": "Request received. A Xiphos compliance specialist will contact you within 24 hours."}), 201


@app.route("/api/leads", methods=["GET"])
@require_auth("admin")
def api_list_leads():
    """List all captured leads. Admin only."""
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                company TEXT NOT NULL,
                role TEXT DEFAULT '',
                source TEXT DEFAULT 'sof-week-portal',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT DEFAULT ''
            )
        """)
        cur.execute("SELECT id, name, email, company, role, source, created_at, notes FROM leads ORDER BY created_at DESC")
        leads = []
        for row in cur.fetchall():
            leads.append({
                "id": row[0], "name": row[1], "email": row[2], "company": row[3],
                "role": row[4], "source": row[5], "created_at": str(row[6]), "notes": row[7]
            })
    return jsonify({"leads": leads, "total": len(leads)})

@app.route("/api/graph/propagation", methods=["POST"])
@require_auth("enrich:read")
def api_risk_propagation():
    """Simulate risk propagation from a source entity through the network."""
    data = request.get_json() or {}
    source_id = data.get("source_id")
    max_hops = data.get("max_hops", 4)
    decay_factor = data.get("decay_factor", 0.6)
    
    if not source_id:
        return jsonify({"error": "source_id required"}), 400
    
    try:
        from knowledge_graph import simulate_risk_propagation
        
        result = simulate_risk_propagation(source_id, max_hops, decay_factor)
        
        if result is None:
            return jsonify({"error": "Entity not found"}), 404
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/re-authorize/<auth_id>", methods=["POST"])
@require_auth("screen:run")
def api_export_re_authorize(auth_id):
    """Re-run authorization pipeline for the same case with updated data.
    
    Uses the original authorization as context and re-evaluates with fresh data.
    
    Body:
    {
        "jurisdiction_guess": "ear",
        "classification_guess": "3A611",
        "destination_country": "GB",
        "destination_company": "Updated Company Ltd",
        ... (same as authorize endpoint)
    }
    
    Returns: New TransactionAuthorization linked to the original.
    """
    if not HAS_TX_AUTH:
        return jsonify({"error": "Transaction authorization module not available"}), 501
    
    body = request.get_json(silent=True) or {}
    
    try:
        from transaction_authorization import re_authorize, TransactionInput, TransactionPerson
        
        # Build persons list
        persons = []
        for p in body.get("persons", []):
            persons.append(TransactionPerson(
                name=p.get("name", ""),
                nationalities=p.get("nationalities", []),
                employer=p.get("employer"),
                role=p.get("role"),
                item_classification=p.get("item_classification"),
                access_level=p.get("access_level"),
            ))
        
        txn = TransactionInput(
            jurisdiction_guess=body.get("jurisdiction_guess", "unknown"),
            request_type=body.get("request_type", "physical_export"),
            classification_guess=body.get("classification_guess", "unknown"),
            item_or_data_summary=body.get("item_or_data_summary", ""),
            destination_country=body.get("destination_country", ""),
            destination_company=body.get("destination_company", ""),
            end_use_summary=body.get("end_use_summary", ""),
            end_user_name=body.get("end_user_name", ""),
            access_context=body.get("access_context", ""),
            persons=persons,
            case_id=body.get("case_id"),
            requested_by=body.get("requested_by", request.user_email if hasattr(request, "user_email") else "api"),
            notes=body.get("notes", ""),
        )
        
        result = re_authorize(auth_id, txn)
        
        log_audit("transaction_authorization", "re_authorize", result.get("id", ""),
                  detail=f"Original: {auth_id}, Posture: {result.get('combined_posture_label')}")
        
        return jsonify(result)
    
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404
    except Exception as e:
        LOGGER.exception("Re-authorization failed: %s", e)
        return jsonify({"error": f"Re-authorization failed: {str(e)}"}), 500


@app.route("/api/cases/<case_id>/authorization-history", methods=["GET"])
@require_auth("screen:read")
def api_case_authorization_history(case_id):
    """Get complete authorization history for a case.
    
    Query params:
        limit: Max results (default 50, max 200)
        offset: Pagination offset (default 0)
    
    Returns: List of all authorizations for this case, ordered by date descending.
    """
    if not HAS_TX_AUTH:
        return jsonify({"error": "Transaction authorization module not available"}), 501
    
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    
    try:
        from transaction_authorization import get_authorization_history
        
        history = get_authorization_history(case_id)
        
        # Apply pagination
        total = len(history)
        history = history[offset:offset+limit]
        
        return jsonify({
            "case_id": case_id,
            "total": total,
            "offset": offset,
            "limit": limit,
            "count": len(history),
            "authorizations": history,
        })
    
    except Exception as e:
        LOGGER.exception("Failed to fetch authorization history: %s", e)
        return jsonify({"error": f"Failed to fetch authorization history: {str(e)}"}), 500


@app.route("/api/export/authorize-batch", methods=["POST"])
@require_auth("screen:run")
def api_export_authorize_batch():
    """Batch transaction authorization (S13-04).

    Process multiple transactions in a single request. Supports dry_run mode
    to evaluate without persisting to audit trail.

    Body:
    {
        "dry_run": false,
        "transactions": [
            {
                "jurisdiction_guess": "ear",
                "classification_guess": "3A001",
                "item_or_data_summary": "Test item 1",
                "destination_country": "GB",
                "destination_company": "Test Co 1",
                "end_use_summary": "Test use",
                "persons": []
            },
            ...
        ]
    }

    Returns:
    {
        "batch_id": str,
        "dry_run": bool,
        "total_processed": int,
        "total_errors": int,
        "results": [
            {
                "authorization_id": str,
                "combined_posture": str,
                "confidence": float,
                "duration_ms": float
            },
            ...
        ],
        "error_details": [...]
    }
    """
    if not HAS_TX_AUTH:
        return jsonify({"error": "Transaction authorization module not available"}), 501

    body = request.get_json(silent=True) or {}
    transactions = body.get("transactions", [])
    dry_run = body.get("dry_run", False)

    if not transactions:
        return jsonify({"error": "Provide at least one transaction"}), 400

    if len(transactions) > 50:
        return jsonify({"error": "Maximum 50 transactions per batch"}), 400

    try:
        from transaction_authorization import authorize_batch

        # Inject requesting user
        for txn in transactions:
            if not txn.get("requested_by") and hasattr(request, "user_email"):
                txn["requested_by"] = request.user_email

        result = authorize_batch(transactions, dry_run=dry_run)

        log_audit("transaction_authorization", "authorize_batch",
                  detail=f"Batch: {result.get('batch_id')}, "
                         f"dry_run: {dry_run}, "
                         f"processed: {result.get('total_processed')}, "
                         f"errors: {result.get('total_errors')}")

        return jsonify(result)

    except Exception as e:
        LOGGER.exception("Batch authorization failed: %s", e)
        return jsonify({"error": f"Batch authorization failed: {str(e)}"}), 500


@app.route("/api/export/templates", methods=["GET"])
@require_auth("screen:read")
def api_export_templates_list():
    """List all export transaction templates (S13-04).

    Query params:
        created_by: Filter to templates created by this user
        limit: Max results (default 50, max 200)

    Returns:
    {
        "templates": [
            {
                "id": str,
                "name": str,
                "created_by": str,
                "created_at": str,
                "usage_count": int
            },
            ...
        ],
        "total": int
    }
    """
    if not HAS_TX_AUTH:
        return jsonify({"error": "Transaction authorization module not available"}), 501

    created_by = request.args.get("created_by")
    limit = min(int(request.args.get("limit", 50)), 200)

    try:
        from export_templates import list_templates, init_templates_db

        init_templates_db()
        result = list_templates(created_by=created_by)

        log_audit("transaction_authorization", "list_templates",
                  detail=f"Total: {result.get('total')}, "
                         f"created_by: {created_by or 'any'}")

        return jsonify({
            "templates": result.get("templates", [])[:limit],
            "total": min(result.get("total", 0), limit),
        })

    except Exception as e:
        LOGGER.exception("Failed to list templates: %s", e)
        return jsonify({"error": f"Failed to list templates: {str(e)}"}), 500


@app.route("/api/export/templates", methods=["POST"])
@require_auth("screen:run")
def api_export_templates_create():
    """Create a new export transaction template (S13-04).

    Body:
    {
        "name": "My ITAR Export",
        "template_data": {
            "jurisdiction_guess": "itar",
            "classification_guess": "USML",
            "item_or_data_summary": "Defense articles",
            "destination_country": "",
            "destination_company": "",
            "end_use_summary": "",
            "access_context": ""
        }
    }

    Returns:
    {
        "id": str,
        "name": str,
        "created_at": str
    }
    """
    if not HAS_TX_AUTH:
        return jsonify({"error": "Transaction authorization module not available"}), 501

    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    template_data = body.get("template_data", {})

    if not name:
        return jsonify({"error": "Provide template name"}), 400

    if not template_data:
        return jsonify({"error": "Provide template_data"}), 400

    try:
        from export_templates import save_template, init_templates_db

        init_templates_db()

        created_by = request.user_email if hasattr(request, "user_email") else "api"
        result = save_template(name, template_data, created_by=created_by)

        if "error" in result:
            return jsonify(result), 400

        log_audit("transaction_authorization", "save_template", result.get("id", ""),
                  detail=f"Name: {name}, created_by: {created_by}")

        return jsonify(result), 201

    except Exception as e:
        LOGGER.exception("Failed to save template: %s", e)
        return jsonify({"error": f"Failed to save template: {str(e)}"}), 500


@app.route("/api/export/templates/<template_id>/execute", methods=["POST"])
@require_auth("screen:run")
def api_export_templates_execute(template_id):
    """Execute a template and return its data ready for authorization (S13-04).

    Also increments usage count and updates last_used_at.

    Returns:
    {
        "template_id": str,
        "template_name": str,
        "transaction_data": {...}
    }
    """
    if not HAS_TX_AUTH:
        return jsonify({"error": "Transaction authorization module not available"}), 501

    try:
        from export_templates import execute_template

        result = execute_template(template_id)

        if "error" in result:
            return jsonify(result), 404

        log_audit("transaction_authorization", "execute_template", template_id,
                  detail=f"Template: {result.get('template_name')}")

        return jsonify(result)

    except Exception as e:
        LOGGER.exception("Failed to execute template: %s", e)
        return jsonify({"error": f"Failed to execute template: {str(e)}"}), 500


@app.route("/api/graph/ingest-persons/<case_id>", methods=["POST"])
@require_auth("screen:run")
def api_graph_ingest_persons(case_id):
    """Retroactively ingest person screening results into knowledge graph (S13-01).

    Finds all person screening results for a case and ingests them as person
    entities and relationships into the knowledge graph.

    Returns:
    {
        "case_id": str,
        "persons_ingested": int,
        "relationships_created": int,
        "details": [...]
    }
    """
    if not HAS_KG:
        return jsonify({"error": "Knowledge graph module not available"}), 501

    try:
        from person_graph_ingest import ingest_persons_for_case, init_persons_db

        init_persons_db()
        result = ingest_persons_for_case(case_id)

        log_audit("knowledge_graph", "ingest_persons", case_id,
                  detail=f"Persons: {result.get('persons_ingested')}, "
                         f"Relationships: {result.get('relationships_created')}")

        return jsonify(result)

    except Exception as e:
        LOGGER.exception("Failed to ingest persons: %s", e)
        return jsonify({"error": f"Failed to ingest persons: {str(e)}"}), 500


@app.route("/api/graph/person-details/<entity_id>", methods=["GET"])
@require_auth("screen:read")
def api_graph_person_details(entity_id):
    """Get comprehensive person entity details from knowledge graph (S13-01).

    Includes: basic info, screenings, risk scores, related companies/cases.

    Returns:
    {
        "entity_id": str,
        "entity_type": "person",
        "name": str,
        "identifiers": {...},
        "screenings": [...],
        "risk_score": float,
        "risk_level": str,
        "related_entities": [...]
    }
    """
    if not HAS_KG:
        return jsonify({"error": "Knowledge graph module not available"}), 501

    try:
        from knowledge_graph import get_entity
        from graph_analytics import GraphAnalytics

        entity = get_entity(entity_id)
        if not entity or entity.get("entity_type") != "person":
            return jsonify({"error": f"Person entity {entity_id} not found"}), 404

        # Compute person-specific risk
        ga = GraphAnalytics()
        risk_analysis = ga.compute_person_risk_score(entity_id)

        # Get screenings
        screenings = []
        try:
            with db.get_conn() as conn:
                rows = conn.execute("""
                    SELECT id, case_id, person_name, screening_status, matched_lists,
                           composite_score, deemed_export, recommended_action, created_at
                    FROM person_screenings
                    WHERE person_name = ?
                    ORDER BY created_at DESC
                """, (
                    entity.get("identifiers", {}).get("name", "")
                    or entity.get("canonical_name", ""),
                )).fetchall()

                screenings = []
                for row in rows:
                    item = dict(row)
                    for json_field in ("matched_lists",):
                        if item.get(json_field) and isinstance(item[json_field], str):
                            try:
                                item[json_field] = json.loads(item[json_field])
                            except (json.JSONDecodeError, TypeError):
                                pass
                    screenings.append(item)
        except Exception as exc:
            LOGGER.warning("Failed to load person screenings for %s: %s", entity_id, exc)

        result = {
            "entity_id": entity_id,
            "entity_type": "person",
            "name": entity.get("identifiers", {}).get("name", ""),
            "identifiers": entity.get("identifiers", {}),
            "nationalities": entity.get("identifiers", {}).get("nationalities", []),
            "screenings": screenings,
            "risk_score": risk_analysis.get("combined_risk", 0.0),
            "risk_level": risk_analysis.get("risk_level", "CLEAR"),
            "risk_factors": risk_analysis.get("risk_factors", []),
        }

        log_audit("knowledge_graph", "person_details", entity_id,
                  detail=f"Risk: {result['risk_level']}")

        return jsonify(result)

    except Exception as e:
        LOGGER.exception("Failed to get person details: %s", e)
        return jsonify({"error": f"Failed to get person details: {str(e)}"}), 500


@app.route("/api/compliance-dashboard", methods=["GET"])
@require_auth("screen:read")
def api_compliance_dashboard():
    """Unified compliance dashboard (S15-01).

    Aggregates data across all 3 compliance lanes (Counterparty, Cyber, Export)
    for a single-pane-of-glass view.

    Query params:
    - case_id (optional): Filter to specific case instead of global view

    Returns:
    {
        "summary": {...},
        "counterparty_lane": {...},
        "export_lane": {...},
        "cyber_lane": {...},
        "cross_lane_insights": {...},
        "activity_feed": [...]
    }
    """
    try:
        from compliance_dashboard import get_compliance_dashboard

        case_id = request.args.get("case_id")
        result = get_compliance_dashboard(case_id)

        log_audit(
            "dashboard",
            "compliance_view",
            case_id or "global",
            detail=f"Cases: {result['summary'].get('total_cases')}, "
            f"Alerts: {result['summary'].get('total_alerts')}",
        )

        return jsonify(result)

    except Exception as e:
        LOGGER.exception("Failed to get compliance dashboard: %s", e)
        return jsonify({"error": f"Failed to get compliance dashboard: {str(e)}"}), 500


# ── Sprint 14-16 module wiring ──────────────────────────────────────────────

# Decision Engine: classify screening alerts into disposition tiers
try:
    from decision_engine import classify_alert
    HAS_DECISION_ENGINE = True
except ImportError:
    HAS_DECISION_ENGINE = False

# Workflow Routing: route classified alerts to compliance queues
try:
    from workflow_routing import route_alert
    HAS_WORKFLOW_ROUTING = True
except ImportError:
    HAS_WORKFLOW_ROUTING = False

# Adversarial Gym: replay adversarial scenarios for trust surface validation
try:
    from adversarial_gym import load_scenarios, evaluate_scenarios, render_markdown
    HAS_ADVERSARIAL_GYM = True
except ImportError:
    HAS_ADVERSARIAL_GYM = False

# Cyber Risk Cascade: CVE risk propagation across supply chain
try:
    from cyber_risk_cascade import get_cyber_risk_cascade
    HAS_CYBER_CASCADE = True
except ImportError:
    HAS_CYBER_CASCADE = False

# Cyber Timeline: temporal view of CVE/KEV events
try:
    from cyber_timeline import get_cyber_timeline
    HAS_CYBER_TIMELINE = True
except ImportError:
    HAS_CYBER_TIMELINE = False

# Semantic Search: TF-IDF character n-gram sanctions matching
try:
    from semantic_search import SanctionsSemanticMatcher
    HAS_SEMANTIC_SEARCH = True
except ImportError:
    HAS_SEMANTIC_SEARCH = False

# Analyst Feedback: scoring calibration from analyst input
try:
    from analyst_feedback import (
        save_feedback as submit_analyst_feedback,
        get_feedback as get_analyst_feedback,
        get_feedback_stats as get_analyst_feedback_stats,
        calibrate_weights as calibrate_analyst_weights,
        get_active_weights as get_active_analyst_weights,
        init_feedback_tables,
    )
    HAS_ANALYST_FEEDBACK = True
except ImportError:
    HAS_ANALYST_FEEDBACK = False

# Resilience Scoring: mission thread resilience metrics
try:
    from resilience_scoring import compute_mission_thread_resilience
    HAS_RESILIENCE = True
except ImportError:
    HAS_RESILIENCE = False

# Ownership Control Intelligence: FOCI/OCI analysis helpers
try:
    from ownership_control_intelligence import build_oci_summary
    HAS_OCI = True
except ImportError:
    HAS_OCI = False

# Compliance Dossier PDF: audit-ready PDF generation
try:
    from compliance_dossier_pdf import generate_compliance_dossier_pdf, ComplianceDossierInput
    HAS_COMPLIANCE_PDF = True
except ImportError:
    HAS_COMPLIANCE_PDF = False

# Threat Intel Substrate: enrichment-derived threat intel summary
try:
    from threat_intel_substrate import build_threat_intel_summary
    HAS_THREAT_INTEL = True
except ImportError:
    HAS_THREAT_INTEL = False


# ── Decision Engine Routes ──────────────────────────────────────────────────

@app.route("/api/screen/classify", methods=["POST"])
@require_auth("cases:read")
def api_classify_alert():
    """Classify a screening result into DEFINITE/PROBABLE/POSSIBLE/UNLIKELY."""
    if not HAS_DECISION_ENGINE:
        return jsonify({"error": "Decision engine not available"}), 501

    body = request.get_json(force=True) or {}
    vendor_name = body.get("vendor_name", "")
    vendor_country = body.get("vendor_country", "")

    if not vendor_name:
        return jsonify({"error": "vendor_name is required"}), 400

    try:
        screening_result = screen_name(vendor_name)
        disposition = classify_alert(screening_result, vendor_country=vendor_country)

        result = {
            "vendor_name": vendor_name,
            "category": disposition.category,
            "confidence_band": disposition.confidence_band,
            "recommended_action": disposition.recommended_action,
            "override_risk_weight": disposition.override_risk_weight,
            "explanation": disposition.explanation,
            "classification_factors": disposition.classification_factors,
        }

        if HAS_WORKFLOW_ROUTING:
            routed = route_alert(disposition)
            result["workflow"] = {
                "queue": routed.queue.value if hasattr(routed, "queue") else str(routed),
                "sla_hours": getattr(routed, "sla_hours", None),
            }

        log_audit("screen", "classify_alert", vendor_name,
                  detail=f"Category: {disposition.category}, Action: {disposition.recommended_action}")

        return jsonify(result)

    except Exception as e:
        LOGGER.exception("classify_alert failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ── Adversarial Gym Routes ──────────────────────────────────────────────────

@app.route("/api/adversarial/run", methods=["POST"])
@require_auth("system:config")
def api_adversarial_run():
    """Run adversarial scenario suite and return pass/fail report."""
    if not HAS_ADVERSARIAL_GYM:
        return jsonify({"error": "Adversarial gym not available"}), 501

    try:
        body = request.get_json(force=True) or {}
        fixture_path = body.get("fixture_path")
        scenarios = load_scenarios(fixture_path)
        report = evaluate_scenarios(scenarios)

        log_audit("adversarial", "gym_run", "all",
                  detail=f"Scenarios: {report['scenario_count']}, Passed: {report['passed_count']}")

        return jsonify(report)

    except Exception as e:
        LOGGER.exception("adversarial gym run failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/adversarial/report", methods=["POST"])
@require_auth("system:config")
def api_adversarial_report():
    """Run adversarial suite and return Markdown report."""
    if not HAS_ADVERSARIAL_GYM:
        return jsonify({"error": "Adversarial gym not available"}), 501

    try:
        body = request.get_json(force=True) or {}
        fixture_path = body.get("fixture_path")
        scenarios = load_scenarios(fixture_path)
        report = evaluate_scenarios(scenarios)
        md = render_markdown(report, fixture_path or "default")

        return Response(md, mimetype="text/markdown")

    except Exception as e:
        LOGGER.exception("adversarial report failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ── Cyber Risk Cascade Routes ──────────────────────────────────────────────

@app.route("/api/cyber/risk-cascade", methods=["GET", "POST"])
@require_auth("cases:read")
def api_cyber_risk_cascade():
    """Compute CVE risk propagation across supply chain."""
    if not HAS_CYBER_CASCADE:
        return jsonify({"error": "Cyber risk cascade not available"}), 501

    try:
        if request.method == "POST":
            body = request.get_json(force=True) or {}
            case_id = body.get("case_id")
        else:
            case_id = request.args.get("case_id")

        cascade = get_cyber_risk_cascade(case_id=case_id)

        log_audit("cyber", "risk_cascade", case_id or "global",
                  detail=f"Nodes: {len(cascade.get('affected_nodes', []))}")

        return jsonify(cascade)

    except Exception as e:
        LOGGER.exception("cyber risk cascade failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/cyber/timeline", methods=["GET", "POST"])
@require_auth("cases:read")
def api_cyber_timeline():
    """Get temporal view of cyber events (CVE discoveries, KEV additions)."""
    if not HAS_CYBER_TIMELINE:
        return jsonify({"error": "Cyber timeline not available"}), 501

    try:
        if request.method == "POST":
            body = request.get_json(force=True) or {}
            case_id = body.get("case_id")
        else:
            case_id = request.args.get("case_id")

        timeline = get_cyber_timeline(case_id=case_id)

        log_audit("cyber", "timeline", case_id or "global",
                  detail=f"Events: {len(timeline.get('events', []))}")

        return jsonify(timeline)

    except Exception as e:
        LOGGER.exception("cyber timeline failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ── Semantic Sanctions Search Routes ────────────────────────────────────────

@app.route("/api/screen/semantic", methods=["POST"])
@require_auth("cases:read")
def api_semantic_screen():
    """Screen a name using semantic TF-IDF matching (complements fuzzy OFAC)."""
    if not HAS_SEMANTIC_SEARCH:
        return jsonify({"error": "Semantic search not available"}), 501

    try:
        body = request.get_json(force=True) or {}
        query = body.get("query", "")
        top_k = min(int(body.get("top_k", 10)), 50)

        if not query:
            return jsonify({"error": "query is required"}), 400

        matcher = SanctionsSemanticMatcher()
        results = matcher.search(query, top_k=top_k)

        log_audit("screen", "semantic_search", query,
                  detail=f"Results: {len(results)}")

        return jsonify({"query": query, "results": results})

    except Exception as e:
        LOGGER.exception("semantic search failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ── Analyst Feedback Routes ─────────────────────────────────────────────────

@app.route("/api/feedback", methods=["POST"])
@require_auth("cases:create")
def api_submit_feedback():
    """Submit analyst feedback on a scoring result."""
    if not HAS_ANALYST_FEEDBACK:
        return jsonify({"error": "Analyst feedback module not available"}), 501

    try:
        body = request.get_json(force=True) or {}
        vendor_id = body.get("vendor_id", "")
        scoring_result_id = int(body.get("scoring_result_id", 0))
        action = body.get("action", "")
        original_tier = body.get("original_tier", "")
        original_score = float(body.get("original_score", 0))
        analyst_tier = body.get("analyst_tier")
        notes = body.get("notes", "")
        factor_overrides = body.get("factor_overrides")
        created_by = body.get("created_by", "analyst")

        if not vendor_id or not action or not original_tier:
            return jsonify({"error": "vendor_id, action, and original_tier are required"}), 400

        result = submit_analyst_feedback(
            vendor_id=vendor_id,
            scoring_result_id=scoring_result_id,
            action=action,
            original_tier=original_tier,
            original_score=original_score,
            analyst_tier=analyst_tier,
            notes=notes,
            factor_overrides=factor_overrides,
            created_by=created_by,
        )

        log_audit("feedback", "submit", vendor_id,
                  detail=f"Action: {action}")

        return jsonify(result)

    except Exception as e:
        LOGGER.exception("submit feedback failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/feedback/<case_id>", methods=["GET"])
@require_auth("cases:read")
def api_get_feedback(case_id):
    """Get all analyst feedback for a case."""
    if not HAS_ANALYST_FEEDBACK:
        return jsonify({"error": "Analyst feedback module not available"}), 501

    try:
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        feedback = get_analyst_feedback(vendor_id=case_id, limit=limit, offset=offset)
        return jsonify({"vendor_id": case_id, "feedback": feedback})

    except Exception as e:
        LOGGER.exception("get feedback failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/feedback/stats", methods=["GET"])
@require_auth("cases:read")
def api_feedback_stats():
    """Get aggregate feedback statistics."""
    if not HAS_ANALYST_FEEDBACK:
        return jsonify({"error": "Analyst feedback module not available"}), 501

    try:
        stats = get_analyst_feedback_stats()
        return jsonify(stats)

    except Exception as e:
        LOGGER.exception("feedback stats failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/feedback/calibrate", methods=["POST"])
@require_auth("system:config")
def api_calibrate_weights():
    """Calibrate FGAMLogit weights from analyst feedback."""
    if not HAS_ANALYST_FEEDBACK:
        return jsonify({"error": "Analyst feedback module not available"}), 501

    try:
        body = request.get_json(force=True) or {}
        min_samples = int(body.get("min_samples", 30))
        result = calibrate_analyst_weights(min_samples=min_samples)

        log_audit("feedback", "calibrate", "global",
                  detail=f"Samples: {result.get('sample_count', 'N/A')}")

        return jsonify(result)

    except Exception as e:
        LOGGER.exception("calibrate weights failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/feedback/active-weights", methods=["GET"])
@require_auth("cases:read")
def api_active_weights():
    """Get the current active scoring weights."""
    if not HAS_ANALYST_FEEDBACK:
        return jsonify({"error": "Analyst feedback module not available"}), 501

    try:
        weights = get_active_analyst_weights()
        return jsonify(weights)

    except Exception as e:
        LOGGER.exception("calibration stats failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ── Resilience Scoring Route ────────────────────────────────────────────────

@app.route("/api/mission-threads/<thread_id>/resilience", methods=["POST"])
@require_auth("cases:read")
def api_resilience_score(thread_id):
    """Compute mission thread resilience score."""
    if not HAS_RESILIENCE:
        return jsonify({"error": "Resilience scoring not available"}), 501

    try:
        body = request.get_json(force=True) or {}
        thread = body.get("thread", {"id": thread_id})
        members = body.get("members", [])
        graph = body.get("graph", {})

        score = compute_mission_thread_resilience(
            thread=thread, members=members, graph=graph,
        )

        log_audit("resilience", "score", thread_id,
                  detail=f"Score: {score.get('overall_score', 'N/A')}")

        return jsonify(score)

    except Exception as e:
        LOGGER.exception("resilience score failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ── Ownership Control Intelligence Route ────────────────────────────────────

@app.route("/api/cases/<case_id>/oci", methods=["GET"])
@require_auth("cases:read")
def api_oci_assessment(case_id):
    """Get Ownership/Control/Influence assessment for a vendor."""
    if not HAS_OCI:
        return jsonify({"error": "OCI module not available"}), 501

    try:
        conn = db.get_conn()
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if not row:
            return jsonify({"error": "Case not found"}), 404

        case_data = dict(row)

        # Extract ownership profile from enrichment report
        enrichment = {}
        if case_data.get("enrichment_report"):
            enrichment = json.loads(case_data["enrichment_report"]) if isinstance(
                case_data["enrichment_report"], str) else case_data["enrichment_report"]
        ownership_profile = enrichment.get("ownership_profile") or {}

        # Get findings and relationships from knowledge graph
        findings = []
        relationships = []
        if HAS_KG:
            entities = kg.get_entities_for_case(case_id) if hasattr(kg, "get_entities_for_case") else []
            for ent in entities:
                rels = kg.get_entity_relationships(ent.get("id", "")) if hasattr(kg, "get_entity_relationships") else []
                relationships.extend(rels)

        assessment = build_oci_summary(ownership_profile, findings, relationships)

        log_audit("oci", "assessment", case_id,
                  detail=f"Owner class: {assessment.get('owner_class', 'N/A')}")

        return jsonify(assessment)

    except Exception as e:
        LOGGER.exception("OCI assessment failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ── Compliance Dossier PDF Route ────────────────────────────────────────────

@app.route("/api/cases/<case_id>/compliance-dossier-pdf", methods=["POST"])
@require_auth("cases:read")
def api_compliance_dossier_pdf(case_id):
    """Generate an audit-ready compliance dossier PDF."""
    if not HAS_COMPLIANCE_PDF:
        return jsonify({"error": "Compliance dossier PDF not available (reportlab required)"}), 501

    try:
        import tempfile

        conn = db.get_conn()
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if not row:
            return jsonify({"error": "Case not found"}), 404

        case_data = dict(row)
        body = request.get_json(force=True) or {}

        dossier_input = ComplianceDossierInput(
            vendor_name=case_data.get("vendor_name", "Unknown"),
            case_id=case_id,
            assessment_date=datetime.utcnow().strftime("%Y-%m-%d"),
            risk_tier=case_data.get("tier", "UNKNOWN"),
            composite_score=float(case_data.get("composite_score", 0)),
            analyst_name=body.get("analyst_name", "Helios Platform"),
        )

        output_path = os.path.join(tempfile.gettempdir(), f"dossier_{case_id}.pdf")
        generate_compliance_dossier_pdf(dossier_input, output_path)

        log_audit("dossier", "compliance_pdf", case_id,
                  detail=f"Tier: {dossier_input.risk_tier}")

        return send_file(output_path, mimetype="application/pdf",
                         as_attachment=True,
                         download_name=f"compliance_dossier_{case_id}.pdf")

    except Exception as e:
        LOGGER.exception("compliance dossier PDF failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ── Threat Intel Summary Route ──────────────────────────────────────────────

@app.route("/api/cases/<case_id>/threat-intel", methods=["GET"])
@require_auth("cases:read")
def api_threat_intel(case_id):
    """Get threat intelligence summary from enrichment data."""
    if not HAS_THREAT_INTEL:
        return jsonify({"error": "Threat intel substrate not available"}), 501

    try:
        conn = db.get_conn()
        row = conn.execute(
            "SELECT enrichment_report FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
        if not row or not row["enrichment_report"]:
            return jsonify({"error": "No enrichment data for this case"}), 404

        report = json.loads(row["enrichment_report"]) if isinstance(row["enrichment_report"], str) else row["enrichment_report"]
        summary = build_threat_intel_summary(report)

        if summary is None:
            return jsonify({"case_id": case_id, "threat_intel": None, "message": "No threat intel signals found"})

        log_audit("threat_intel", "summary", case_id,
                  detail=f"Techniques: {len(summary.get('attack_techniques', []))}")

        return jsonify({"case_id": case_id, "threat_intel": summary})

    except Exception as e:
        LOGGER.exception("threat intel summary failed: %s", e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    main()
