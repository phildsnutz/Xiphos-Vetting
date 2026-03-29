#!/usr/bin/env python3
"""
Helios Batch Vendor Screening API v1.0

Standalone Flask API for batch vendor screening through the full compliance pipeline.
Accepts JSON payloads of vendor data and returns scored compliance results.

Core features:
  - Single-vendor screening (immediate response)
  - Batch screening (up to 100 vendors, with job tracking for async processing)
  - Compliance profile selection (5 profiles: DEFENSE_ACQUISITION, ITAR_TRADE, etc.)
  - Full pipeline: OFAC -> Decision Engine -> Regulatory Gates -> FGAMLogit -> Workflow Routing
  - Optional ITAR compliance evaluation
  - API key authentication (Bearer token)
  - Rate limiting (100 single/min, 10 batch/min)
  - Request/response logging for audit trail
  - Graceful handling of missing optional modules

Endpoints:
  POST /api/v1/screen/single     Screen a single vendor
  POST /api/v1/screen/batch      Screen multiple vendors (up to 100)
  GET  /api/v1/screen/status/:id Check batch job status
  GET  /api/v1/profiles          List compliance profiles
  GET  /api/v1/health            API health check

Can be run standalone: python3 screening_api.py --port 5050

Author: Helios Platform
Date:   March 2026
"""

import os
import json
import uuid
import time
import logging
import argparse
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
from functools import wraps

from flask import Flask, Blueprint, request, jsonify, g

# Core scoring engines
try:
    from fgamlogit import (
        score_vendor, VendorInputV5, OwnershipProfile, DataQuality,
        ExecProfile, DoDContext
    )
    HAS_FGAM = True
except ImportError:
    HAS_FGAM = False

# OFAC screening
try:
    from ofac import screen_name
    HAS_OFAC = True
except ImportError:
    HAS_OFAC = False

# Decision engine (OFAC -> disposition classification)
try:
    from decision_engine import classify_alert
    HAS_DECISION_ENGINE = True
except ImportError:
    HAS_DECISION_ENGINE = False

# Regulatory gates (DoD compliance layer)
try:
    from regulatory_gates import evaluate_regulatory_gates, RegulatoryGateInput
    HAS_GATES = True
except ImportError:
    HAS_GATES = False

# Workflow routing (queue + SLA assignment)
try:
    from workflow_routing import route_alert
    HAS_WORKFLOW = True
except ImportError:
    HAS_WORKFLOW = False

# Compliance profiles
try:
    from compliance_profiles import (
        get_profile as get_canonical_profile,
        get_sensitivity_default,
    )
    from profiles import list_profiles as list_canonical_profiles, profile_to_dict
    HAS_PROFILES = True
except ImportError:
    HAS_PROFILES = False

# Optional ITAR module
try:
    from itar_module import evaluate_itar_compliance
    HAS_ITAR = True
except ImportError:
    HAS_ITAR = False


# =============================================================================
# CONFIGURATION
# =============================================================================

API_KEY = os.environ.get("HELIOS_API_KEY", "helios-test-key-12345")
MAX_BATCH_SIZE = 100
SINGLE_RATE_LIMIT = 100  # per minute
BATCH_RATE_LIMIT = 10    # per minute
API_VERSION = "1.0.0"

# In-memory job storage (in production, use persistent DB)
_BATCH_JOBS: Dict[str, dict] = {}


# =============================================================================
# LOGGING & AUDIT TRAIL
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
LOGGER = logging.getLogger("screening_api")


def _audit_log(event: str, **fields):
    """Structured audit log entry."""
    payload = {"event": event, "timestamp": datetime.utcnow().isoformat(), **fields}
    LOGGER.info(json.dumps(payload, default=str))


# =============================================================================
# RATE LIMITING
# =============================================================================

_request_history = {}  # {endpoint: [(timestamp, count), ...]}


def _check_rate_limit(endpoint: str, max_per_minute: int) -> tuple[bool, Optional[str]]:
    """
    Simple rate limiter: track requests per endpoint per minute.
    Returns (allowed, error_message).
    """
    now = time.time()
    window_start = now - 60

    if endpoint not in _request_history:
        _request_history[endpoint] = []

    # Prune old entries
    _request_history[endpoint] = [
        ts for ts in _request_history[endpoint] if ts > window_start
    ]

    # Check limit
    if len(_request_history[endpoint]) >= max_per_minute:
        return False, f"Rate limit exceeded: {max_per_minute} requests per minute"

    # Add current request
    _request_history[endpoint].append(now)
    return True, None


# =============================================================================
# AUTHENTICATION
# =============================================================================

def require_api_key(f):
    """Decorator to require Bearer token authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401

        token = auth_header[7:]  # Remove "Bearer "
        if token != API_KEY:
            _audit_log("auth_failure", path=request.path, remote_addr=request.remote_addr)
            return jsonify({"error": "Invalid API key"}), 403

        return f(*args, **kwargs)

    return decorated


# =============================================================================
# DATA CLASSES & VALIDATION
# =============================================================================

@dataclass
class OwnershipInput:
    """Ownership profile for screening request."""
    publicly_traded: bool = False
    state_owned: bool = False
    beneficial_owner_known: bool = False
    named_beneficial_owner_known: bool = False
    controlling_parent_known: bool = False
    owner_class_known: bool = False
    owner_class: str = ""
    ownership_pct_resolved: float = 0.0
    control_resolution_pct: float = 0.0
    shell_layers: int = 0
    pep_connection: bool = False
    foreign_ownership_pct: float = 0.0
    foreign_ownership_is_allied: bool = True


@dataclass
class DataQualityInput:
    """Data quality signals for screening request."""
    has_lei: bool = False
    has_cage: bool = False
    has_duns: bool = False
    has_tax_id: bool = False
    has_audited_financials: bool = False
    years_of_records: int = 0


@dataclass
class ITARInput:
    """ITAR-specific screening parameters."""
    usml_category: Optional[int] = None
    ddtc_registered: bool = False
    foreign_nationals: List[str] = field(default_factory=list)
    end_user_country: Optional[str] = None
    controlled_content: bool = False


@dataclass
class ScreeningRequest:
    """Single vendor screening request."""
    vendor_name: str
    vendor_country: str
    profile: str = "DEFENSE_ACQUISITION"
    sensitivity: Optional[str] = None
    ownership: Optional[Dict[str, Any]] = None
    data_quality: Optional[Dict[str, Any]] = None
    itar: Optional[Dict[str, Any]] = None

    def validate(self) -> tuple[bool, Optional[str]]:
        """Validate required fields."""
        if not self.vendor_name or not self.vendor_name.strip():
            return False, "vendor_name is required and must not be empty"
        if not self.vendor_country or len(self.vendor_country) != 2:
            return False, "vendor_country must be a 2-letter ISO country code"
        try:
            profile_config = get_canonical_profile(self.profile)
        except (ValueError, KeyError):
            return False, f"Invalid profile: {self.profile}"
        self.vendor_name = self.vendor_name.strip()
        self.vendor_country = self.vendor_country.upper()
        self.profile = profile_config.id
        if not self.sensitivity:
            self.sensitivity = str(profile_config.sensitivity_default)
        return True, None


@dataclass
class RiskScore:
    """Probabilistic risk scoring result."""
    probability: float  # 0.0 to 1.0
    confidence_interval: List[float]  # [lower, upper]
    tier: str  # monitor, elevated, critical
    factors: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScreeningResult:
    """Complete screening result for a single vendor."""
    request_id: str
    vendor_name: str
    timestamp: str
    profile: str
    screening: Dict[str, Any] = field(default_factory=dict)
    risk_score: Dict[str, Any] = field(default_factory=dict)
    regulatory_gates: Dict[str, Any] = field(default_factory=dict)
    itar: Optional[Dict[str, Any]] = None
    workflow: Dict[str, Any] = field(default_factory=dict)
    recommendation: str = "UNKNOWN"

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        result = asdict(self)
        if result["itar"] is None:
            result.pop("itar", None)
        return result


# =============================================================================
# SCREENING PIPELINE
# =============================================================================

def _build_vendor_input(req: ScreeningRequest) -> Optional[VendorInputV5]:
    """Build FGAMLogit VendorInputV5 from screening request."""
    if not HAS_FGAM:
        return None

    ownership_dict = req.ownership or {}
    dq_dict = req.data_quality or {}

    ownership = OwnershipProfile(
        publicly_traded=ownership_dict.get("publicly_traded", False),
        state_owned=ownership_dict.get("state_owned", False),
        beneficial_owner_known=ownership_dict.get("beneficial_owner_known", False),
        named_beneficial_owner_known=ownership_dict.get("named_beneficial_owner_known", False),
        controlling_parent_known=ownership_dict.get("controlling_parent_known", False),
        owner_class_known=ownership_dict.get("owner_class_known", False),
        owner_class=ownership_dict.get("owner_class", ""),
        ownership_pct_resolved=ownership_dict.get("ownership_pct_resolved", 0.0),
        control_resolution_pct=ownership_dict.get("control_resolution_pct", 0.0),
        shell_layers=ownership_dict.get("shell_layers", 0),
        pep_connection=ownership_dict.get("pep_connection", False),
        foreign_ownership_pct=ownership_dict.get("foreign_ownership_pct", 0.0),
        foreign_ownership_is_allied=ownership_dict.get("foreign_ownership_is_allied", True),
    )

    dq = DataQuality(
        has_lei=dq_dict.get("has_lei", False),
        has_cage=dq_dict.get("has_cage", False),
        has_duns=dq_dict.get("has_duns", False),
        has_tax_id=dq_dict.get("has_tax_id", False),
        has_audited_financials=dq_dict.get("has_audited_financials", False),
        years_of_records=dq_dict.get("years_of_records", 0),
    )

    ep = ExecProfile(
        known_execs=0,
        adverse_media=0,
        pep_execs=0,
        litigation_history=0,
    )

    sensitivity = req.sensitivity or (
        get_sensitivity_default(req.profile) if HAS_PROFILES else "COMMERCIAL"
    )
    dod = DoDContext(
        sensitivity=sensitivity,
        supply_chain_tier=0,
        regulatory_gate_proximity=0.0,
        itar_exposure=0.0,
        ear_control_status=0.0,
        foreign_ownership_depth=0.0,
        cmmc_readiness=0.0,
        single_source_risk=0.0,
        geopolitical_sector_exposure=0.0,
        financial_stability=0.2,
        compliance_history=0.0,
    )

    return VendorInputV5(
        name=req.vendor_name,
        country=req.vendor_country,
        ownership=ownership,
        data_quality=dq,
        exec_profile=ep,
        dod=dod,
        compliance_profile=req.profile,
    )


def _screen_single_vendor(req: ScreeningRequest, request_id: str) -> ScreeningResult:
    """
    Execute the full screening pipeline for a single vendor.
    
    Pipeline:
      1. OFAC screening (screen_name)
      2. Decision Engine (classify_alert)
      3. Regulatory Gates (evaluate_regulatory_gates)
      4. FGAMLogit scoring (score_vendor)
      5. Layer integration (integrate_layers)
      6. Workflow routing (route_alert)
      7. Optional ITAR evaluation (evaluate_itar_compliance)
    """
    result = ScreeningResult(
        request_id=request_id,
        vendor_name=req.vendor_name,
        timestamp=datetime.utcnow().isoformat() + "Z",
        profile=req.profile,
    )
    profile_config = get_canonical_profile(req.profile) if HAS_PROFILES else None
    effective_sensitivity = req.sensitivity or (
        str(profile_config.sensitivity_default) if profile_config else "COMMERCIAL"
    )
    enabled_gate_ids = (
        list(profile_config.enabled_gate_ids)
        if profile_config is not None
        else list(range(1, 14))
    )

    # =========================================================================
    # 1. OFAC SCREENING
    # =========================================================================
    ofac_match = None
    ofac_matched = False
    if HAS_OFAC:
        try:
            ofac_result = screen_name(req.vendor_name, req.vendor_country)
            ofac_matched = ofac_result.get("matched", False) if ofac_result else False
            ofac_match = ofac_result
            _audit_log(
                "ofac_screening",
                request_id=request_id,
                vendor=req.vendor_name,
                matched=ofac_matched,
            )
        except Exception as e:
            LOGGER.error(f"OFAC screening failed: {e}")
            ofac_matched = False

    result.screening["ofac_matched"] = ofac_matched
    result.screening["ofac_result"] = ofac_match

    # =========================================================================
    # 2. DECISION ENGINE (OFAC -> DISPOSITION)
    # =========================================================================
    disposition = None
    disposition_action = "AUTO_CLEAR"
    if HAS_DECISION_ENGINE and ofac_match:
        try:
            disposition = classify_alert(ofac_match)
            disposition_action = disposition.recommended_action if hasattr(
                disposition, "recommended_action"
            ) else "AUTO_CLEAR"
        except Exception as e:
            LOGGER.error(f"Decision engine failed: {e}")
            disposition = None

    result.screening["disposition"] = str(disposition) if disposition else "NONE"
    result.screening["disposition_action"] = disposition_action

    # =========================================================================
    # 3. REGULATORY GATES (DoD COMPLIANCE LAYER 1)
    # =========================================================================
    regulatory_status = "SKIPPED"
    regulatory_details = {}
    regulatory_findings = []
    gate_proximity_score = 0.0
    if HAS_GATES:
        try:
            gate_input = RegulatoryGateInput(
                entity_name=req.vendor_name,
                entity_country=req.vendor_country,
                sensitivity=effective_sensitivity,
                supply_chain_tier=0,
                enabled_gates=enabled_gate_ids,
            )
            gate_result = evaluate_regulatory_gates(gate_input)
            regulatory_assessment = gate_result.to_dict() if hasattr(gate_result, 'to_dict') else {}
            regulatory_status = regulatory_assessment.get("status", gate_result.status.value if hasattr(gate_result, 'status') else "UNKNOWN")
            regulatory_details = regulatory_assessment
            gate_proximity_score = float(regulatory_assessment.get("gate_proximity_score", 0.0) or 0.0)
            for gate in list(getattr(gate_result, "failed_gates", [])) + list(getattr(gate_result, "pending_gates", [])):
                regulatory_findings.append(
                    {
                        "gate": gate.gate_id,
                        "name": gate.gate_name,
                        "status": gate.state.value,
                        "severity": gate.severity,
                        "explanation": gate.details,
                        "regulation": gate.regulation,
                        "remediation": gate.mitigation,
                        "confidence": gate.confidence,
                    }
                )
            _audit_log(
                "regulatory_gates",
                request_id=request_id,
                vendor=req.vendor_name,
                status=regulatory_status,
            )
        except Exception as e:
            LOGGER.error(f"Regulatory gates failed: {e}")
            regulatory_status = "ERROR"

    result.regulatory_gates["overall_status"] = regulatory_status
    result.regulatory_gates["gates"] = regulatory_details
    result.regulatory_gates["findings"] = regulatory_findings
    result.regulatory_gates["enabled_gates"] = enabled_gate_ids
    result.regulatory_gates["gate_proximity_score"] = gate_proximity_score

    # =========================================================================
    # 4. FGAMLOGIT SCORING (LAYER 2: DUAL-VERTICAL MODEL)
    # =========================================================================
    probability = 0.0
    tier = "unknown"
    factors = {}
    program_recommendation = None
    if HAS_FGAM:
        try:
            vendor_input = _build_vendor_input(req)
            if vendor_input:
                vendor_input.dod.sensitivity = effective_sensitivity
                vendor_input.dod.regulatory_gate_proximity = gate_proximity_score
                score_result = score_vendor(
                    vendor_input,
                    regulatory_status=(
                        regulatory_status
                        if regulatory_status in ("COMPLIANT", "NON_COMPLIANT", "REQUIRES_REVIEW")
                        else "NOT_EVALUATED"
                    ),
                    regulatory_findings=regulatory_findings,
                )
                probability = getattr(
                    score_result, "calibrated_probability", 0.0
                )
                tier = getattr(
                    score_result,
                    "calibrated_tier",
                    getattr(score_result, "combined_tier", "unknown"),
                )
                factors = getattr(score_result, "contributions", {})
                program_recommendation = getattr(score_result, "program_recommendation", None)
                _audit_log(
                    "fgam_scoring",
                    request_id=request_id,
                    vendor=req.vendor_name,
                    probability=probability,
                    tier=tier,
                )
        except Exception as e:
            LOGGER.error(f"FGAMLogit scoring failed: {e}")
            probability = 0.5
            tier = "error"

    result.risk_score["probability"] = probability
    result.risk_score["confidence_interval"] = [
        max(0.0, probability - 0.15),
        min(1.0, probability + 0.15),
    ]
    result.risk_score["tier"] = tier
    result.risk_score["program_recommendation"] = program_recommendation
    result.risk_score["factors"] = factors

    # =========================================================================
    # 5. WORKFLOW ROUTING (QUEUE + SLA)
    # =========================================================================
    queue = "AUTO_CLEARED"
    sla_hours = None
    recommended_action = "No action required"
    if HAS_WORKFLOW and disposition:
        try:
            routing_result = route_alert(
                disposition=disposition,
                sensitivity=req.sensitivity or "COMMERCIAL",
                probability=probability,
            )
            queue = getattr(routing_result, "queue", "AUTO_CLEARED")
            sla_hours = getattr(routing_result, "sla_hours", None)
            recommended_action = getattr(
                routing_result, "recommended_action", "No action required"
            )
            _audit_log(
                "workflow_routing",
                request_id=request_id,
                vendor=req.vendor_name,
                queue=queue,
            )
        except Exception as e:
            LOGGER.error(f"Workflow routing failed: {e}")

    result.workflow["queue"] = queue
    result.workflow["sla_hours"] = sla_hours
    result.workflow["recommended_action"] = recommended_action

    # =========================================================================
    # 6. OPTIONAL ITAR EVALUATION
    # =========================================================================
    if req.itar and HAS_ITAR:
        try:
            itar_result = evaluate_itar_compliance(
                vendor_name=req.vendor_name,
                usml_category=req.itar.get("usml_category"),
                ddtc_registered=req.itar.get("ddtc_registered", False),
                foreign_nationals=req.itar.get("foreign_nationals", []),
                end_user_country=req.itar.get("end_user_country"),
            )
            result.itar = {
                "overall_status": itar_result.get("overall_status", "UNKNOWN"),
                "country_status": itar_result.get("country_status", "UNKNOWN"),
                "deemed_export_risk": itar_result.get("deemed_export_risk", 0.0),
                "red_flag_score": itar_result.get("red_flag_score", 0.0),
                "license_type": itar_result.get("license_type", "UNKNOWN"),
            }
            _audit_log(
                "itar_evaluation",
                request_id=request_id,
                vendor=req.vendor_name,
                status=result.itar.get("overall_status"),
            )
        except Exception as e:
            LOGGER.error(f"ITAR evaluation failed: {e}")
            result.itar = None

    # =========================================================================
    # FINAL RECOMMENDATION
    # =========================================================================
    if program_recommendation:
        result.recommendation = program_recommendation
    elif ofac_matched:
        result.recommendation = "BLOCKED"
    elif regulatory_status == "NON_COMPLIANT":
        result.recommendation = "REJECTED"
    elif probability > 0.7:
        result.recommendation = "HOLD_FOR_REVIEW"
    elif queue == "AUTO_CLEARED":
        result.recommendation = "APPROVED"
    else:
        result.recommendation = "PENDING_REVIEW"

    return result


# =============================================================================
# FLASK BLUEPRINT & ROUTES
# =============================================================================

screening_bp = Blueprint("screening", __name__, url_prefix="/api/v1/screen")


@screening_bp.route("/single", methods=["POST"])
@require_api_key
def screen_single():
    """
    POST /api/v1/screen/single
    
    Screen a single vendor through the full compliance pipeline.
    
    Request body: ScreeningRequest JSON
    Response: ScreeningResult JSON
    """
    allowed, error = _check_rate_limit("single", SINGLE_RATE_LIMIT)
    if not allowed:
        return jsonify({"error": error}), 429

    request_id = f"req-{uuid.uuid4().hex[:12]}"
    g.request_id = request_id

    try:
        body = request.get_json()
        if not body:
            return jsonify({"error": "Request body must be JSON"}), 400

        # Parse and validate request
        req = ScreeningRequest(
            vendor_name=body.get("vendor_name"),
            vendor_country=body.get("vendor_country"),
            profile=body.get("profile", "defense_acquisition"),
            sensitivity=body.get("sensitivity"),
            ownership=body.get("ownership"),
            data_quality=body.get("data_quality"),
            itar=body.get("itar"),
        )

        valid, error = req.validate()
        if not valid:
            _audit_log("screening_validation_failed", request_id=request_id, error=error)
            return jsonify({"error": error}), 400

        # Execute screening
        result = _screen_single_vendor(req, request_id)
        _audit_log(
            "screening_completed",
            request_id=request_id,
            vendor=req.vendor_name,
            recommendation=result.recommendation,
        )

        return jsonify(result.to_dict()), 200

    except Exception as e:
        LOGGER.error(f"Screening failed: {e}", exc_info=True)
        _audit_log("screening_error", request_id=request_id, error=str(e))
        return (
            jsonify({"error": "Internal server error", "request_id": request_id}),
            500,
        )


@screening_bp.route("/batch", methods=["POST"])
@require_api_key
def screen_batch():
    """
    POST /api/v1/screen/batch
    
    Screen multiple vendors (up to 100) in a single request.
    
    Request body: {"vendors": [ScreeningRequest, ...]}
    Response (small batches <10): Inline array of ScreeningResult
    Response (large batches >=10): {"job_id": "...", "status": "processing"}
    """
    allowed, error = _check_rate_limit("batch", BATCH_RATE_LIMIT)
    if not allowed:
        return jsonify({"error": error}), 429

    job_id = f"job-{uuid.uuid4().hex[:12]}"
    g.request_id = job_id

    try:
        body = request.get_json()
        if not body or "vendors" not in body:
            return jsonify({"error": "Request must contain 'vendors' array"}), 400

        vendors = body["vendors"]
        if not isinstance(vendors, list):
            return jsonify({"error": "vendors must be an array"}), 400

        if len(vendors) > MAX_BATCH_SIZE:
            return (
                jsonify(
                    {
                        "error": f"Batch size exceeds maximum ({MAX_BATCH_SIZE})",
                        "provided": len(vendors),
                    }
                ),
                413,
            )

        # Parse requests
        requests = []
        for i, v in enumerate(vendors):
            req = ScreeningRequest(
                vendor_name=v.get("vendor_name"),
                vendor_country=v.get("vendor_country"),
                profile=v.get("profile", "defense_acquisition"),
                sensitivity=v.get("sensitivity"),
                ownership=v.get("ownership"),
                data_quality=v.get("data_quality"),
                itar=v.get("itar"),
            )
            valid, error = req.validate()
            if not valid:
                return (
                    jsonify(
                        {
                            "error": f"Vendor {i}: {error}",
                            "vendor_index": i,
                        }
                    ),
                    400,
                )
            requests.append(req)

        # Process batch
        results = []
        for i, req in enumerate(requests):
            result = _screen_single_vendor(req, f"{job_id}-{i}")
            results.append(result.to_dict())

        # For small batches, return inline; for large, return job_id
        if len(results) < 10:
            _audit_log(
                "batch_screening_completed",
                job_id=job_id,
                count=len(results),
                size="small",
            )
            return jsonify({"job_id": job_id, "results": results}), 200
        else:
            _BATCH_JOBS[job_id] = {
                "status": "completed",
                "created_at": datetime.utcnow().isoformat(),
                "vendor_count": len(results),
                "results": results,
            }
            _audit_log(
                "batch_screening_job_stored",
                job_id=job_id,
                count=len(results),
                size="large",
            )
            return (
                jsonify(
                    {
                        "job_id": job_id,
                        "status": "completed",
                        "vendor_count": len(results),
                    }
                ),
                202,
            )

    except Exception as e:
        LOGGER.error(f"Batch screening failed: {e}", exc_info=True)
        _audit_log("batch_screening_error", job_id=job_id, error=str(e))
        return jsonify({"error": "Internal server error", "job_id": job_id}), 500


@screening_bp.route("/status/<job_id>", methods=["GET"])
@require_api_key
def check_status(job_id: str):
    """
    GET /api/v1/screen/status/<job_id>
    
    Check status of a batch screening job.
    
    Response: {"job_id": "...", "status": "processing|completed", "results": [...]}
    """
    if job_id not in _BATCH_JOBS:
        return jsonify({"error": "Job not found"}), 404

    job = _BATCH_JOBS[job_id]
    response = {
        "job_id": job_id,
        "status": job["status"],
        "vendor_count": job.get("vendor_count"),
        "created_at": job.get("created_at"),
    }

    if job["status"] == "completed":
        response["results"] = job.get("results", [])

    _audit_log("batch_status_check", job_id=job_id, status=job["status"])
    return jsonify(response), 200


@screening_bp.route("/profiles", methods=["GET"])
@require_api_key
def list_profiles():
    """
    GET /api/v1/profiles
    
    List available compliance profiles with their configurations.
    
    Response: {"profiles": [{"name": "...", "description": "..."}, ...]}
    """
    profiles = []
    if HAS_PROFILES:
        for profile in list_canonical_profiles():
            payload = profile_to_dict(profile)
            profiles.append(
                {
                    "name": payload["enum_name"],
                    "profile_id": payload["id"],
                    "description": payload["description"],
                    "gates": payload["enabled_gates"],
                    "sensitivity_levels": [payload["sensitivity_default"]],
                    "connector_priority": payload["connector_priority"],
                }
            )

    _audit_log("profiles_listed")
    return jsonify({"profiles": profiles}), 200


@screening_bp.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return jsonify({"error": "Endpoint not found"}), 404


@screening_bp.errorhandler(405)
def method_not_allowed(e):
    """Handle 405 errors."""
    return jsonify({"error": "Method not allowed"}), 405


# =============================================================================
# HEALTH CHECK (not in blueprint, at root level)
# =============================================================================

def create_health_endpoint(app: Flask):
    """Register health check endpoint on app."""

    @app.route("/api/v1/health", methods=["GET"])
    def health():
        """
        GET /api/v1/health
        
        API health check with module availability and version info.
        """
        return (
            jsonify(
                {
                    "status": "healthy",
                    "version": API_VERSION,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "modules": {
                        "fgam_logit": HAS_FGAM,
                        "ofac": HAS_OFAC,
                        "decision_engine": HAS_DECISION_ENGINE,
                        "regulatory_gates": HAS_GATES,
                        "workflow_routing": HAS_WORKFLOW,
                        "compliance_profiles": HAS_PROFILES,
                        "itar": HAS_ITAR,
                    },
                    "config": {
                        "max_batch_size": MAX_BATCH_SIZE,
                        "single_rate_limit": SINGLE_RATE_LIMIT,
                        "batch_rate_limit": BATCH_RATE_LIMIT,
                    },
                }
            ),
            200,
        )


# =============================================================================
# STANDALONE MODE
# =============================================================================

def create_app() -> Flask:
    """Factory function to create and configure the Flask app."""
    app = Flask(__name__)

    # Register blueprint
    app.register_blueprint(screening_bp)

    # Register health endpoint
    create_health_endpoint(app)

    # Error handlers
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "Bad request"}), 400

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"error": "Internal server error"}), 500

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Xiphos Screening API")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5050, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    app = create_app()
    LOGGER.info(
        f"Starting Xiphos Screening API v{API_VERSION} on {args.host}:{args.port}"
    )
    app.run(host=args.host, port=args.port, debug=args.debug)
