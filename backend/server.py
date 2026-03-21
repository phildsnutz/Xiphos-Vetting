#!/usr/bin/env python3
"""
Xiphos v5.0 API Server

Flask backend with SQLite persistence, JWT authentication, RBAC, and
full audit logging. All scoring runs through the FGAMLogit v5.0 engine
(two-layer DoD/commercial dual-vertical architecture).
27-source OSINT enrichment, entity resolution, continuous monitoring,
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
import csv
import io
import time
import logging
import threading
import argparse
from datetime import datetime

from flask import Flask, Response, g, jsonify, request, send_file, stream_with_context

from fgamlogit import (
    score_vendor, VendorInputV5, OwnershipProfile, DataQuality,
    ExecProfile, DoDContext, integrate_layers, PROGRAM_TO_SENSITIVITY,
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
from runtime_paths import get_data_dir

# Optional: sanctions sync engine (may fail if dependencies missing)
try:
    import sanctions_sync
    HAS_SYNC = True
except ImportError:
    HAS_SYNC = False

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

# Layer 1: Regulatory Gate Engine (DoD compliance)
try:
    from regulatory_gates import (
        evaluate_regulatory_gates, quick_screen,
        RegulatoryGateInput, Section889Input, NDAA1260HInput,
        FOCIInput, CFIUSInput,
    )
    HAS_GATES = True
except ImportError:
    HAS_GATES = False

# Static folder for serving the bundled frontend
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = Flask(__name__, static_folder=None)
configure_cors(app)
add_security_headers(app)

_LOG_LEVEL = os.environ.get("XIPHOS_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _LOG_LEVEL, logging.INFO), format="%(message)s")
LOGGER = logging.getLogger("xiphos")


def _log_event(event: str, **fields):
    payload = {"event": event, **fields}
    LOGGER.info(json.dumps(payload, default=str, sort_keys=True))


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
    default_sensitivity = PROGRAM_TO_SENSITIVITY.get(program, "COMMERCIAL")

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


PROFILE_DEFAULT_PROGRAMS = {
    "defense_acquisition": "dod_unclassified",
    "itar_trade_compliance": "regulated_commercial",
    "university_research_security": "federal_non_dod",
    "grants_compliance": "federal_non_dod",
    "commercial_supply_chain": "commercial",
}


def _current_user_id() -> str:
    return g.user.get("sub", "system") if getattr(g, "user", None) else "system"


def _current_user_email() -> str:
    return g.user.get("email", "") if getattr(g, "user", None) else ""


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


def _current_intel_report_hash(case_id: str) -> str:
    report = _current_enrichment_report(case_id)
    if not report or not HAS_INTEL:
        return ""
    return report.get("report_hash") or compute_report_hash(report)


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
    db.replace_case_events(case_id, report_hash, events)
    return events


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

    try:
        result = analyze_vendor(user_id, vendor, score, enrichment)
    except Exception as err:
        update_analysis_job(job_id, status="failed", error=str(err)[:500])
        return

    update_analysis_job(job_id, status="completed", analysis_id=result.get("analysis_id"))


def _default_program_for_profile(profile_id: str) -> str:
    return PROFILE_DEFAULT_PROGRAMS.get(profile_id, "commercial")


def _score_vendor_result(v: dict, source_reliability_avg: float = 0.0):
    """Score a vendor through the canonical two-layer pipeline without persisting side effects."""
    inp = _build_vendor_input(v)

    reg_status, reg_findings, gate_proximity = _run_regulatory_gates(
        v, inp.dod.sensitivity, inp.dod.supply_chain_tier
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
    return result, _full_score_dict(result)


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


def _run_regulatory_gates(v: dict, sensitivity: str, tier: int) -> tuple:
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

    # Quick screen: Section 889 + NDAA 1260H name-based checks
    screen = quick_screen(
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
    foreign_ownership_pct = ownership.get("foreign_ownership_pct", 0.0)
    if foreign_ownership_pct > 0:
        gate_inp.foci = FOCIInput(
            entity_foreign_ownership_pct=foreign_ownership_pct,
            sensitivity=sensitivity,
        )

    # Populate CFIUS with basic foreign involvement data
    if foreign_ownership_pct > 0:
        # Mark as transaction involving foreign party if foreign ownership detected
        gate_inp.cfius = CFIUSInput(
            transaction_involves_foreign_acquirer=True,
            foreign_acquirer_country=country if country != "US" else "",
        )
        # Add critical tech/infrastructure flags based on program type
        if "defense" in program.lower() or "dod" in program.lower():
            gate_inp.cfius.business_involves_critical_technology = True

    assessment = evaluate_regulatory_gates(gate_inp)

    # Convert gate results to serializable findings
    findings = []
    for g in assessment.failed_gates + assessment.pending_gates:
        findings.append({
            "gate": g.gate_id,
            "name": g.gate_name,
            "status": g.state.value,
            "severity": g.severity,
            "explanation": g.details,
            "regulation": g.regulation,
            "remediation": g.mitigation,
            "confidence": g.confidence,
        })

    return (assessment.status.value, findings, assessment.gate_proximity_score)


def _score_and_persist(vendor_id: str, v: dict, source_reliability_avg: float = 0.0) -> dict:
    """Score a vendor through full two-layer pipeline and persist."""
    result, score_dict = _score_vendor_result(v, source_reliability_avg=source_reliability_avg)

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

    # Persist alerts from hard stops and flags
    for stop in result.hard_stop_decisions:
        db.save_alert(vendor_id, v["name"], "critical",
                      stop["trigger"], stop["explanation"])
    for flag in result.soft_flags:
        sev = "high" if flag["confidence"] > 0.7 else "medium"
        db.save_alert(vendor_id, v["name"], sev,
                      flag["trigger"], flag["explanation"])

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
        "engine": "fgamlogit-dod-dual-vertical",
        "persistence": "sqlite",
        "sanctions_db": db_label,
        "sanctions_sync": sanctions_status,
        "osint_enabled": HAS_OSINT,
        "osint_connectors": osint_connectors,
        "osint_connector_count": len(osint_connectors),
        "osint_connector_health": connector_health,
        "osint_cache": cache_stats,
        "stats": stats,
    })


@app.route("/api/profiles")
@require_auth("health:read")
def api_list_profiles():
    """List all compliance profiles."""
    from profiles import list_profiles, profile_to_dict
    return jsonify({"profiles": [profile_to_dict(p) for p in list_profiles()]})


@app.route("/api/profiles/<profile_id>")
@require_auth("health:read")
def api_get_profile(profile_id):
    """Get a single compliance profile by ID."""
    from profiles import get_profile, profile_to_dict
    p = get_profile(profile_id)
    if not p:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify(profile_to_dict(p))


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
    candidates = resolve_entity(name)[:max_candidates]
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
    vendors = db.list_vendors(limit)
    cases = []
    for v in vendors:
        score = db.get_latest_score(v["id"])
        vendor_input = v.get("vendor_input", {}) if isinstance(v, dict) else {}
        program = vendor_input.get("program", "") if isinstance(vendor_input, dict) else ""
        cases.append({
            "id": v["id"],
            "vendor_name": v["name"],
            "country": v.get("country", ""),
            "profile": v.get("profile", "defense_acquisition"),
            "program": program,
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
        "country": v["country"], "program": v["program"], "profile": v.get("profile", "defense_acquisition"),
        "status": score.get("calibrated", {}).get("calibrated_tier", "unknown") if score else "pending",
        "created_at": v["created_at"], "score": score,
    })


@app.route("/api/cases", methods=["POST"])
@require_auth("cases:create")
@rate_limit(max_requests=30, window_seconds=60)
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
        "profile": body.get("profile_id", body.get("profile", "defense_acquisition")),
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
    # Ensure name/country are present (may be missing from legacy records)
    if "name" not in vendor_input:
        vendor_input["name"] = v["name"]
    if "country" not in vendor_input:
        vendor_input["country"] = v["country"]
    if "program_type" in body:
        vendor_input["program"] = body["program_type"]
    if "dod" in body:
        vendor_input["dod"] = body["dod"]

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
        return jsonify({"error": "HTML dossier generator not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404

    html = generate_dossier(case_id, user_id=_current_user_id())

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



@app.route("/api/cases/<case_id>/dossier-pdf", methods=["POST"])
@require_auth("cases:dossier")
def api_generate_dossier_pdf(case_id):
    """Generate a PDF dossier for a vendor."""
    if not HAS_DOSSIER_PDF:
        return jsonify({"error": "PDF dossier generator not available"}), 501
    v = db.get_vendor(case_id)
    if not v:
        return jsonify({"error": "Case not found"}), 404
    try:
        pdf_bytes = generate_pdf_dossier(case_id, user_id=_current_user_id())
        log_audit("dossier_pdf_generated", "case", case_id,
                  detail=f"PDF dossier generated for {v['name']}")
        return pdf_bytes, 200, {"Content-Type": "application/pdf",
                               "Content-Disposition": f"attachment; filename=dossier-{case_id}.pdf"}
    except Exception as e:
        return jsonify({"error": f"Failed to generate PDF: {str(e)}"}), 500

@app.route("/api/dossiers/<filename>")
def api_serve_dossier(filename):
    """Serve a generated dossier HTML file. Path traversal protected.
    Accepts token via query param since browser window.open() cannot set headers."""
    # Auth: check header first, fall back to query param for browser downloads
    from auth import _decode_token, AUTH_ENABLED
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    elif request.args.get("token"):
        token = request.args.get("token")
    if AUTH_ENABLED and not token:
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
        return send_file(filepath)
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
        return jsonify({"error": str(err)}), 400

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
        return jsonify({
            "status": job["status"],
            "case_id": case_id,
            "vendor_name": vendor["name"],
            "job": job,
        })

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


# ---- Portfolio Intelligence (Phase 4) ----

try:
    from portfolio_intelligence import (
        ScoreDriftDetector, AnomalyDetectorBank, PortfolioAnalytics
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
@rate_limit(max_requests=10, window_seconds=60)
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
    if HAS_INTEL:
        _persist_case_events(case_id, v, report)

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


@app.route("/api/cases/<case_id>/enrich-stream")
@require_auth("cases:enrich")
def api_enrich_case_stream(case_id):
    if not HAS_OSINT:
        return jsonify({"error": "OSINT enrichment module not available"}), 501

    vendor = db.get_vendor(case_id)
    if not vendor:
        return jsonify({"error": "Case not found"}), 404

    def _sse(event: str, payload: dict | None = None):
        body = json.dumps(payload or {})
        return f"event: {event}\ndata: {body}\n\n"

    @stream_with_context
    def _generate():
        report = None
        try:
            for event_name, payload in enrich_vendor_streaming(
                vendor_name=vendor["name"],
                country=vendor["country"],
            ):
                if event_name == "complete":
                    report = payload
                yield _sse(event_name, payload)

            if report is None:
                raise RuntimeError("Enrichment stream did not produce a final report")

            db.save_enrichment(case_id, report)
            if HAS_INTEL:
                _persist_case_events(case_id, vendor, report)
            for finding in report.get("findings", []):
                if finding["severity"] in ("critical", "high"):
                    db.save_alert(
                        case_id,
                        vendor["name"],
                        finding["severity"],
                        f"[OSINT] {finding['title']}",
                        finding.get("detail", ""),
                    )

            vendor_input = dict(vendor["vendor_input"])
            base_input = _build_vendor_input(vendor_input)
            augmentation = augment_from_enrichment(base_input, report)
            aug_vi = augmentation.vendor_input
            updated_input = {
                **vendor_input,
                "ownership": {
                    "publicly_traded": aug_vi.ownership.publicly_traded,
                    "state_owned": aug_vi.ownership.state_owned,
                    "beneficial_owner_known": aug_vi.ownership.beneficial_owner_known,
                    "ownership_pct_resolved": aug_vi.ownership.ownership_pct_resolved,
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
            score_dict = _score_and_persist(case_id, updated_input, source_reliability_avg=avg_reliability)

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
    connectors = body.get("connectors", None)

    # Step 1: Run OSINT enrichment
    report = enrich_vendor(
        vendor_name=v["name"],
        country=v["country"],
        connectors=connectors,
    )
    db.save_enrichment(case_id, report)
    if HAS_INTEL:
        _persist_case_events(case_id, v, report)

    # Step 2: Augment scoring inputs from enrichment
    vendor_input = v["vendor_input"]
    base_input = _build_vendor_input(vendor_input)
    augmentation = augment_from_enrichment(base_input, report)

    # Step 3: Serialize augmented input back to dict (preserving ALL v5 fields)
    aug_vi = augmentation.vendor_input
    updated_input = {
        **vendor_input,  # preserves dod{}, program, and any other original fields
        "ownership": {
            "publicly_traded": aug_vi.ownership.publicly_traded,
            "state_owned": aug_vi.ownership.state_owned,
            "beneficial_owner_known": aug_vi.ownership.beneficial_owner_known,
            "ownership_pct_resolved": aug_vi.ownership.ownership_pct_resolved,
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

    # Apply extra risk signals from OSINT augmentation before scoring
    updated_input = _apply_extra_risk_signals(updated_input, augmentation.extra_risk_signals)

    # Compute average source reliability from provenance data for CI modulation
    all_reliabilities = []
    for factor_sources in augmentation.provenance.values():
        for src_entry in factor_sources:
            all_reliabilities.append(src_entry.get("reliability", 0.6))
    avg_reliability = sum(all_reliabilities) / len(all_reliabilities) if all_reliabilities else 0.0

    # Step 4: Score through the SINGLE canonical pipeline (Layer 1 gates + Layer 2 FGAMLogit)
    score_dict = _score_and_persist(case_id, updated_input, source_reliability_avg=avg_reliability)

    # Generate alerts from OSINT findings (hard stop alerts handled by _score_and_persist)
    for finding in report.get("findings", []):
        if finding["severity"] in ("critical", "high"):
            db.save_alert(case_id, v["name"], finding["severity"],
                          f"[OSINT] {finding['title']}", finding.get("detail", ""))

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

    print(f"  Monitoring: {'enabled' if HAS_MONITOR else 'not available'}")
    print(f"  Dossier HTML: {'enabled' if HAS_DOSSIER else 'not available'}")
    print(f"  Dossier PDF: {'enabled' if HAS_DOSSIER_PDF else 'not available'}")
    print(f"  AI analysis: {'enabled' if HAS_AI else 'not available'}")
    dev_mode = os.environ.get("XIPHOS_DEV_MODE", "false").lower() == "true"
    auth_mode = 'ENFORCED' if AUTH_ENABLED else ('DEV MODE (anonymous admin passthrough)' if dev_mode else 'AUTH DISABLED (protected routes still require a token)')
    print(f"  Auth/RBAC: {auth_mode}")

    stats = db.get_stats()
    print(f"\n{'='*50}")
    print(f"  XIPHOS v5.0 -- Intelligence-Grade Vendor Assurance (FGAMLogit DoD Dual-Vertical)")
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


if __name__ == "__main__":
    main()
