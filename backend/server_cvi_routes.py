"""
Comparative Vehicle Intelligence API Routes

REST API endpoints for the CVI (Comparative Vehicle Intelligence) generation
system. Provides endpoints for:
  - Comparative dossier generation: POST /api/cvi/comparative
  - Single vehicle dossier generation: POST /api/cvi/vehicle-dossier
  - Gap advisory pipeline: POST /api/cvi/gap-advisory
  - Gap filling (Axiom): POST /api/cvi/fill-gaps

REGISTRATION:
=============
This blueprint is registered automatically via blueprint_registry.py.
No manual registration in server.py is needed.

Authentication Pattern:
- All routes available without authentication for MVP
- "cases:dossier" for dossier generation endpoints (scoped when auth added)
- "cases:enrich" for gap advisory and filling endpoints (scoped when auth added)
- "GET /api/cvi/health" requires no authentication

Error Handling:
- All exceptions caught and logged with app-level logger
- Missing modules return 503 Service Unavailable
- Invalid requests return 400 Bad Request
- Server errors return 500 Internal Server Error

Response Format:
- All responses use jsonify() for consistent JSON encoding
- Success responses include "status": "completed"
- Error responses include "error": "error message" field
- Complex results include nested objects and arrays
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from flask import Blueprint, g, jsonify, request

logger = logging.getLogger(__name__)

cvi_bp = Blueprint("cvi", __name__, url_prefix="/api/cvi")


def _priority_from_severity(value: object) -> str:
    severity = str(value or "medium").strip().lower()
    return severity if severity in {"critical", "high", "medium", "low"} else "medium"


def _build_gap_input(raw_gap: dict, default_vehicle_name: str = ""):
    from axiom_gap_filler import IntelligenceGap

    affected_entities = raw_gap.get("affected_entities") or []
    entity_name = str(
        raw_gap.get("entity_name")
        or raw_gap.get("affected_vendor")
        or raw_gap.get("entity")
        or (affected_entities[0] if affected_entities else "")
        or default_vehicle_name
        or "Unknown entity"
    ).strip()

    return IntelligenceGap(
        gap_id=str(raw_gap.get("gap_id") or raw_gap.get("id") or f"gap_{datetime.now(timezone.utc).timestamp()}"),
        description=str(raw_gap.get("description") or raw_gap.get("context") or "").strip() or "Unspecified intelligence gap",
        entity_name=entity_name,
        vehicle_name=str(raw_gap.get("vehicle_name") or raw_gap.get("vehicle") or default_vehicle_name or "").strip(),
        gap_type=str(raw_gap.get("gap_type") or "unknown"),
        priority=_priority_from_severity(raw_gap.get("severity")),
        original_classification=str(raw_gap.get("original_classification") or "manual"),
        source_iteration=int(raw_gap.get("source_iteration") or 0),
    )


def _serialize_gap_fill_result(result):
    gap = getattr(result, "gap", None)
    filled = bool(getattr(result, "filled", False))
    confidence = float(getattr(result, "fill_confidence", 0.0) or 0.0)
    attempts = list(getattr(result, "attempts", []) or [])

    return {
        "gap_id": getattr(gap, "gap_id", ""),
        "status": "closed" if filled else ("partial" if confidence > 0 else "failed"),
        "findings": [
            finding
            for attempt in attempts
            for finding in (getattr(attempt, "findings", []) or [])
        ],
        "confidence": confidence,
        "evidence": [
            {
                "approach": getattr(attempt, "approach_name", ""),
                "reasoning": getattr(attempt, "approach_reasoning", ""),
                "connectors_used": list(getattr(attempt, "connectors_used", []) or []),
                "graph_queries_made": list(getattr(attempt, "graph_queries_made", []) or []),
                "lesson_learned": getattr(attempt, "lesson_learned", ""),
            }
            for attempt in attempts
        ],
        "fill_attempts": len(attempts),
        "final_classification": getattr(result, "final_classification", ""),
        "advisory_value_estimate": float(getattr(result, "advisory_value_estimate", 0.0) or 0.0),
        "advisory_scope": getattr(result, "advisory_scope", ""),
    }


def _resolve_ai_runtime(user_id: str, body: dict, default_provider: str = "anthropic", default_model: str = "claude-sonnet-4-6"):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    provider = body.get("provider", default_provider)
    model = body.get("model", default_model)

    try:
        from ai_analysis import get_ai_config

        config = get_ai_config(user_id or "__org_default__")
        if config:
            api_key = config.get("api_key", "") or api_key
            provider = config.get("provider", provider)
            model = config.get("model", model)
    except ImportError:
        logger.debug("cvi_routes: ai_analysis unavailable, falling back to request/env runtime")
    except Exception as exc:
        logger.warning("cvi_routes: failed to resolve AI runtime from config store: %s", exc)

    return api_key, provider, model


def _maybe_queue_neo4j_sync(*, since_timestamp: str, requested_by: str = "", requested_by_email: str = ""):
    try:
        from neo4j_integration import is_neo4j_available
        from neo4j_sync_scheduler import get_neo4j_sync_scheduler

        if not since_timestamp:
            return {"status": "skipped", "reason": "no_since_timestamp"}
        if not is_neo4j_available():
            return {"status": "unavailable"}

        job = get_neo4j_sync_scheduler().queue_incremental_sync(
            since_timestamp,
            requested_by=requested_by,
            requested_by_email=requested_by_email,
            metadata={"requested_via": "cvi_graph_promotion"},
        )
        return {
            "status": job.get("status") or "queued",
            "job_id": job.get("job_id"),
            "status_url": f"/api/neo4j/sync/{job.get('job_id')}" if job.get("job_id") else None,
            "reused_existing_job": bool(job.get("reused_existing_job")),
        }
    except Exception as exc:
        logger.warning("cvi_routes: Neo4j sync queue failed: %s", exc)
        return {"status": "failed", "error": str(exc)}


def _serialize_gap(gap):
    """Serialize a gap object for JSON response."""
    return {
        "id": gap.get("id", ""),
        "gap_type": gap.get("gap_type", "unknown"),
        "description": gap.get("description", ""),
        "severity": gap.get("severity", "medium"),
        "vehicle": gap.get("vehicle", ""),
        "affected_vendor": gap.get("affected_vendor", ""),
        "recommended_action": gap.get("recommended_action", ""),
        "evidence": gap.get("evidence", []),
    }


def _serialize_metadata(metadata):
    """Serialize metadata object for JSON response."""
    return {
        "title": metadata.get("title", ""),
        "subtitle": metadata.get("subtitle", ""),
        "classification": metadata.get("classification", "UNCLASSIFIED"),
        "generated_at": metadata.get("generated_at", datetime.now(timezone.utc).isoformat()),
        "generated_by": metadata.get("generated_by", ""),
        "page_count": metadata.get("page_count", 0),
    }


# -------------------------------------------------------------------
# Comparative Vehicle Dossier Generation
# -------------------------------------------------------------------

@cvi_bp.route("/comparative", methods=["POST"])
def api_cvi_comparative():
    """
    Generate a comparative dossier for 2+ vehicles.

    Request body:
    {
        "vehicle_configs": [
            {
                "vehicle_name": "ITEAMS",
                "prime_contractor": "Amentum",
                "vendor_ids": ["vendor_1", "vendor_2"],
                "contract_data": {...}
            },
            {
                "vehicle_name": "LEIA",
                "prime_contractor": "SMX",
                ...
            }
        ],
        "title": "Comparative Vehicle Analysis Report",      // optional
        "subtitle": "Multi-Vendor Assessment",               // optional
        "classification": "UNCLASSIFIED",                   // optional
        "include_risk_summary": true,                        // optional
        "include_timeline": true                             // optional
    }

    Returns:
    {
        "html": "<html>...</html>",
        "metadata": {
            "title": "...",
            "subtitle": "...",
            "classification": "...",
            "generated_at": "2026-04-03T...",
            "generated_by": "...",
            "page_count": N
        },
        "comparison_summary": {
            "vehicles_analyzed": N,
            "total_vendors": N,
            "common_gaps": [...],
            "differentiated_risks": [...]
        }
    }
    """
    try:
        from comparative_dossier import generate_comparative_dossier

        body = request.get_json(silent=True) or {}
        vehicle_configs = body.get("vehicle_configs", [])

        if not vehicle_configs:
            return jsonify({"error": "Missing required field: vehicle_configs"}), 400

        if len(vehicle_configs) < 2:
            return jsonify({"error": "Comparative dossier requires 2 or more vehicles"}), 400

        # generate_comparative_dossier returns HTML string directly
        html_output = generate_comparative_dossier(
            vehicle_configs=vehicle_configs,
            title=body.get("title", "Comparative Vehicle Intelligence Report"),
            subtitle=body.get("subtitle", "Multi-Vendor Assessment"),
            analyst_name=body.get("analyst_name", "AXIOM Intelligence Module"),
            classification=body.get("classification", "UNCLASSIFIED"),
        )

        if not html_output:
            return jsonify({"error": "Comparative dossier generation returned empty result"}), 500

        response = {
            "html": html_output,
            "metadata": {
                "title": body.get("title", "Comparative Vehicle Intelligence Report"),
                "classification": body.get("classification", "UNCLASSIFIED"),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": "AXIOM Intelligence Module",
                "vehicles_analyzed": len(vehicle_configs),
            },
            "status": "completed",
        }

        return jsonify(response), 200

    except ImportError as e:
        logger.error("cvi_routes: comparative_dossier module not available: %s", e)
        return jsonify({"error": "CVI comparative module not available"}), 503
    except Exception as exc:
        logger.exception("cvi_routes: comparative dossier failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# -------------------------------------------------------------------
# Vehicle Teaming Intelligence
# -------------------------------------------------------------------

@cvi_bp.route("/teaming-intelligence", methods=["POST"])
def api_cvi_teaming_intelligence():
    """Return the v1 competitive teaming map for a named vehicle."""
    try:
        from teaming_intelligence import build_teaming_intelligence
        try:
            from vehicle_intel_support import build_vehicle_intelligence_support
        except Exception:
            build_vehicle_intelligence_support = None

        body = request.get_json(silent=True) or {}
        vehicle_name = str(body.get("vehicle_name", "")).strip()
        if not vehicle_name:
            return jsonify({"error": "Missing required field: vehicle_name"}), 400

        observed_vendors = body.get("observed_vendors", [])
        if not isinstance(observed_vendors, list):
            return jsonify({"error": "observed_vendors must be an array when provided"}), 400

        scenario = body.get("scenario")
        if scenario is not None and not isinstance(scenario, dict):
            return jsonify({"error": "scenario must be an object when provided"}), 400

        if not observed_vendors and build_vehicle_intelligence_support is not None:
            try:
                support_bundle = build_vehicle_intelligence_support(
                    vehicle_name=vehicle_name,
                    vendor={
                        "id": "",
                        "name": str(body.get("prime_contractor", "")).strip(),
                        "vendor_input": {
                            "seed_metadata": {
                                "contract_vehicle_name": vehicle_name,
                            }
                        },
                    },
                )
            except Exception:
                support_bundle = None
            if isinstance(support_bundle, dict):
                observed_vendors = [
                    dict(row)
                    for row in (support_bundle.get("observed_vendors") or [])
                    if isinstance(row, dict)
                ]

        report = build_teaming_intelligence(
            vehicle_name=vehicle_name,
            observed_vendors=observed_vendors,
            scenario=scenario,
        )

        return jsonify(
            {
                "status": "completed",
                "report": report,
            }
        ), 200
    except ImportError as e:
        logger.error("cvi_routes: teaming_intelligence module not available: %s", e)
        return jsonify({"error": "CVI teaming intelligence module not available"}), 503
    except Exception as exc:
        logger.exception("cvi_routes: teaming intelligence failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# -------------------------------------------------------------------
# Single Vehicle Dossier Generation
# -------------------------------------------------------------------

@cvi_bp.route("/vehicle-dossier", methods=["POST"])
def api_cvi_vehicle_dossier():
    """
    Generate a single vehicle dossier with vendor analysis.

    Request body:
    {
        "vehicle_name": "ITEAMS",                           // required
        "prime_contractor": "Amentum",                      // required
        "vendor_ids": ["vendor_1", "vendor_2"],             // required
        "contract_data": {                                  // optional
            "vehicle_id": "...",
            "contract_number": "...",
            "contract_value": 1000000,
            "contract_start": "2024-01-01",
            "contract_end": "2026-12-31"
        },
        "title": "ITEAMS Vehicle Dossier",                  // optional
        "classification": "UNCLASSIFIED",                   // optional
        "include_org_chart": true,                          // optional
        "include_subcontractor_network": true               // optional
    }

    Returns:
    {
        "html": "<html>...</html>",
        "metadata": {
            "title": "...",
            "classification": "...",
            "generated_at": "...",
            "generated_by": "...",
            "page_count": N
        },
        "vehicle_summary": {
            "vehicle_name": "ITEAMS",
            "prime_contractor": "Amentum",
            "vendor_count": N,
            "total_risk_score": 0.75,
            "risk_tier": "MODERATE"
        }
    }
    """
    try:
        from comparative_dossier import generate_vehicle_dossier

        body = request.get_json(silent=True) or {}
        vehicle_name = str(body.get("vehicle_name", "")).strip()
        prime_contractor = str(body.get("prime_contractor", "")).strip()
        vendor_ids = body.get("vendor_ids", [])

        if not vehicle_name:
            return jsonify({"error": "Missing required field: vehicle_name"}), 400
        if not prime_contractor:
            return jsonify({"error": "Missing required field: prime_contractor"}), 400
        if not vendor_ids:
            return jsonify({"error": "Missing required field: vendor_ids"}), 400

        user_id = g.user.get("sub", "") if getattr(g, "user", None) else ""

        # generate_vehicle_dossier returns HTML string directly
        html_output = generate_vehicle_dossier(
            vehicle_name=vehicle_name,
            prime_contractor=prime_contractor,
            vendor_ids=vendor_ids,
            contract_data=body.get("contract_data", {}),
            analyst_name=body.get("analyst_name", "AXIOM Intelligence Module"),
            classification=body.get("classification", "UNCLASSIFIED"),
        )

        if not html_output:
            return jsonify({"error": "Dossier generation returned empty result"}), 500

        response = {
            "html": html_output,
            "metadata": {
                "title": body.get("title", f"{vehicle_name} Vehicle Dossier"),
                "classification": body.get("classification", "UNCLASSIFIED"),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": "AXIOM Intelligence Module",
            },
            "status": "completed",
        }

        return jsonify(response), 200

    except ImportError as e:
        logger.error("cvi_routes: comparative_dossier module not available: %s", e)
        return jsonify({"error": "CVI vehicle dossier module not available"}), 503
    except Exception as exc:
        logger.exception("cvi_routes: vehicle dossier failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# -------------------------------------------------------------------
# Gap Advisory Pipeline
# -------------------------------------------------------------------

@cvi_bp.route("/gap-advisory", methods=["POST"])
def api_cvi_gap_advisory():
    """
    Run the full gap advisory pipeline: identify gaps, run Axiom search,
    fill gaps, and generate proposal HTML.

    Request body:
    {
        "vendor_ids": ["vendor_1", "vendor_2"],             // required
        "vehicle_name": "ITEAMS",                           // required
        "client_company": "Acme Defense",                   // required
        "gap_severity_filter": "all|critical|high",        // optional
        "skip_axiom_fill": false,                           // optional
        "max_iterations": 3,                                 // optional
        "proposal_title": "Gap Closure Strategy",            // optional
        "proposal_style": "technical|executive"             // optional
    }

    Returns:
    {
        "pipeline_result": {
            "gaps_identified": N,
            "gaps_by_severity": {...},
            "axiom_search_summary": {...},
            "gaps_closed": N,
            "gaps_remaining": N
        },
        "proposal_html": "<html>...</html>",
        "recommendations": [...],
        "status": "completed"
    }
    """
    try:
        from gap_advisory_pipeline import run_gap_advisory_pipeline

        body = request.get_json(silent=True) or {}
        vendor_ids = body.get("vendor_ids", [])
        vehicle_name = str(body.get("vehicle_name", "")).strip()
        client_company = str(body.get("client_company", "")).strip()

        if not vendor_ids:
            return jsonify({"error": "Missing required field: vendor_ids"}), 400
        if not vehicle_name:
            return jsonify({"error": "Missing required field: vehicle_name"}), 400
        if not client_company:
            return jsonify({"error": "Missing required field: client_company"}), 400

        user_id = g.user.get("sub", "") if getattr(g, "user", None) else ""
        user_email = g.user.get("email", "") if getattr(g, "user", None) else ""

        api_key, provider, model = _resolve_ai_runtime(user_id, body)

        # run_gap_advisory_pipeline returns a PipelineResult dataclass
        pipeline_result = run_gap_advisory_pipeline(
            vendor_ids=vendor_ids,
            vehicle_name=vehicle_name,
            client_company=client_company,
            skip_axiom_fill=body.get("skip_axiom_fill", False),
            api_key=api_key,
            provider=provider,
            model=model,
            user_id=user_id,
        )

        # Convert dataclass to dict via its to_dict() method
        result_dict = pipeline_result.to_dict() if hasattr(pipeline_result, "to_dict") else (
            pipeline_result if isinstance(pipeline_result, dict) else {}
        )

        graph_promotion = result_dict.get("graph_promotion") or {}
        neo4j_sync = None
        if int(graph_promotion.get("promoted_claims") or 0) > 0:
            neo4j_sync = _maybe_queue_neo4j_sync(
                since_timestamp=str(graph_promotion.get("since_timestamp") or ""),
                requested_by=user_id,
                requested_by_email=user_email,
            )

        response = {
            "pipeline_result": {
                "gaps_identified": result_dict.get("total_gaps_identified", 0),
                "gaps_filled_by_axiom": result_dict.get("gaps_filled_by_axiom", 0),
                "gaps_remaining": result_dict.get("gaps_remaining", 0),
                "total_pipeline_value": result_dict.get("total_pipeline_value", 0),
                "elapsed_ms": result_dict.get("elapsed_ms", 0),
            },
            "proposals": result_dict.get("proposals_generated", []),
            "axiom_fill_results": result_dict.get("axiom_fill_results", []),
            "graph_promotion": graph_promotion,
            "status": "completed",
        }
        if neo4j_sync:
            response["neo4j_sync"] = neo4j_sync

        return jsonify(response), 200

    except ImportError as e:
        logger.error("cvi_routes: gap_advisory_pipeline module not available: %s", e)
        return jsonify({"error": "CVI gap advisory module not available"}), 503
    except Exception as exc:
        logger.exception("cvi_routes: gap advisory pipeline failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# -------------------------------------------------------------------
# Axiom Gap Filling
# -------------------------------------------------------------------

@cvi_bp.route("/fill-gaps", methods=["POST"])
def api_cvi_fill_gaps():
    """
    Run Axiom gap filler on specific intelligence gaps.

    Request body:
    {
        "gaps": [
            {
                "id": "gap_1",
                "description": "Unknown supplier list",
                "context": "ITEAMS subcontractor network",
                "gap_type": "entity_discovery"
            },
            ...
        ],
        "vehicle_name": "ITEAMS",                          // optional
        "max_attempts_per_gap": 3,                          // optional
        "provider": "anthropic",                            // optional
        "model": "claude-sonnet-4-6"                       // optional
    }

    Returns:
    {
        "results": [
            {
                "gap_id": "gap_1",
                "status": "closed|partial|failed",
                "findings": [...],
                "confidence": 0.85,
                "evidence": [...],
                "fill_attempts": 2
            },
            ...
        ],
        "summary": {
            "total_gaps": N,
            "closed": N,
            "partial": N,
            "failed": N,
            "average_confidence": 0.78
        }
    }
    """
    try:
        from axiom_gap_filler import fill_gaps as fill_gaps_with_axiom
        from axiom_graph_promotion import promote_validated_gap_fill, summarize_promotions
        from validation_gate import validate_gap_fill_result

        body = request.get_json(silent=True) or {}
        gaps = body.get("gaps", [])

        if not gaps:
            return jsonify({"error": "Missing required field: gaps"}), 400

        user_id = g.user.get("sub", "") if getattr(g, "user", None) else ""
        user_email = g.user.get("email", "") if getattr(g, "user", None) else ""
        vendor_id = str(body.get("vendor_id") or "").strip()

        api_key, provider, model = _resolve_ai_runtime(user_id, body)
        default_vehicle_name = str(body.get("vehicle_name", "")).strip()
        gap_objects = [
            _build_gap_input(gap, default_vehicle_name=default_vehicle_name)
            for gap in gaps
            if isinstance(gap, dict)
        ]
        if not gap_objects:
            return jsonify({"error": "No valid gap objects supplied"}), 400

        results = fill_gaps_with_axiom(
            gaps=gap_objects,
            api_key=api_key,
            provider=provider,
            model=model,
            user_id=user_id,
            max_attempts_per_gap=body.get("max_attempts_per_gap", 3),
        )

        serialized_results = []
        promotion_results = []
        closed = 0
        partial = 0
        failed = 0
        for result in results:
            serialized = _serialize_gap_fill_result(result)
            validation = validate_gap_fill_result(result)
            promotion = promote_validated_gap_fill(result, validation, vendor_id=vendor_id)
            if validation.outcome == "accepted":
                serialized["status"] = "closed"
                closed += 1
            elif validation.outcome == "review":
                serialized["status"] = "partial"
                partial += 1
            else:
                serialized["status"] = "failed"
                failed += 1
            serialized["validation"] = validation.to_dict()
            serialized["graph_promotion"] = promotion.to_dict()
            serialized_results.append(serialized)
            promotion_results.append(promotion)

        average_confidence = (
            sum(float(getattr(result, "fill_confidence", 0.0) or 0.0) for result in results) / len(results)
            if results else 0.0
        )
        graph_promotion = summarize_promotions(promotion_results)
        neo4j_sync = None
        if int(graph_promotion.get("promoted_claims") or 0) > 0:
            neo4j_sync = _maybe_queue_neo4j_sync(
                since_timestamp=str(graph_promotion.get("since_timestamp") or ""),
                requested_by=user_id,
                requested_by_email=user_email,
            )

        response = {
            "results": serialized_results,
            "summary": {
                "total_gaps": len(results),
                "closed": closed,
                "partial": partial,
                "failed": failed,
                "accepted": closed,
                "review": partial,
                "rejected": failed,
                "average_confidence": average_confidence,
            },
            "graph_promotion": graph_promotion,
            "status": "completed",
        }
        if neo4j_sync:
            response["neo4j_sync"] = neo4j_sync

        return jsonify(response), 200

    except ImportError as e:
        logger.error("cvi_routes: axiom_gap_filler module not available: %s", e)
        return jsonify({"error": "CVI gap filler module not available"}), 503
    except Exception as exc:
        logger.exception("cvi_routes: fill gaps failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# -------------------------------------------------------------------
# Health check
# -------------------------------------------------------------------

@cvi_bp.route("/health", methods=["GET"])
def api_cvi_health():
    """Check CVI system availability."""
    status = {
        "comparative": False,
        "vehicle_dossier": False,
        "teaming_intelligence": False,
        "gap_advisory": False,
        "gap_filler": False,
    }

    try:
        import comparative_dossier
        status["comparative"] = True
        status["vehicle_dossier"] = True
    except ImportError:
        pass

    try:
        import teaming_intelligence
        status["teaming_intelligence"] = True
    except ImportError:
        pass

    try:
        import gap_advisory_pipeline
        status["gap_advisory"] = True
    except ImportError:
        pass

    try:
        import axiom_gap_filler
        status["gap_filler"] = True
    except ImportError:
        pass

    all_ok = all(status.values())
    return jsonify({"status": "ok" if all_ok else "degraded", "components": status}), 200


logger.info("cvi_bp: Blueprint initialized with 6 CVI API endpoints")
