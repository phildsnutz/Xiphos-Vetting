"""
Flask Blueprint for Analyst Feedback API endpoints (Sprint 15-01)

Provides REST endpoints for collecting analyst feedback on scoring results
and triggering weight calibration.

Endpoints:
- POST /api/feedback: Save analyst feedback
- GET /api/feedback: List feedback records (with filters)
- GET /api/feedback/stats: Get aggregate feedback statistics
- POST /api/feedback/calibrate: Trigger weight calibration
- GET /api/feedback/weights: Get current active weights
"""

import logging
from flask import Blueprint, request, jsonify
from analyst_feedback import (
    init_feedback_tables,
    save_feedback,
    get_feedback,
    get_feedback_stats,
    calibrate_weights,
    get_active_weights,
)

logger = logging.getLogger(__name__)

feedback_bp = Blueprint("feedback", __name__, url_prefix="/api/feedback")


@feedback_bp.before_request
def init_tables_once():
    """Initialize feedback tables on first request."""
    if not hasattr(feedback_bp, "_tables_initialized"):
        try:
            init_feedback_tables()
            feedback_bp._tables_initialized = True
        except Exception as e:
            logger.warning(f"Failed to initialize feedback tables: {e}")
            # Continue anyway; tables may already exist


@feedback_bp.route("", methods=["POST"])
def create_feedback():
    """
    Save analyst feedback on a scoring result.

    Request body:
    {
        "vendor_id": str (required),
        "scoring_result_id": int (required),
        "action": "agree"|"disagree"|"override" (required),
        "original_tier": "GREEN"|"YELLOW"|"ORANGE"|"RED" (required),
        "original_score": float (required),
        "analyst_tier": str (optional, required if action is disagree/override),
        "notes": str (optional),
        "factor_overrides": {factor: weight, ...} (optional),
        "created_by": str (optional, default "analyst")
    }

    Returns:
    {
        "success": bool,
        "feedback": {...feedback record...},
        "error": str (if success=false)
    }
    """
    try:
        data = request.get_json() or {}

        # Validate required fields
        required = ["vendor_id", "scoring_result_id", "action", "original_tier", "original_score"]
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({
                "success": False,
                "error": f"Missing required fields: {', '.join(missing)}"
            }), 400

        # Call save_feedback
        feedback_record = save_feedback(
            vendor_id=data.get("vendor_id"),
            scoring_result_id=data.get("scoring_result_id"),
            action=data.get("action"),
            original_tier=data.get("original_tier"),
            original_score=data.get("original_score"),
            analyst_tier=data.get("analyst_tier"),
            notes=data.get("notes"),
            factor_overrides=data.get("factor_overrides"),
            created_by=data.get("created_by", "analyst"),
        )

        return jsonify({
            "success": True,
            "feedback": feedback_record
        }), 201

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
    except Exception as e:
        logger.error(f"Error creating feedback: {e}")
        return jsonify({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }), 500


@feedback_bp.route("", methods=["GET"])
def list_feedback():
    """
    List analyst feedback records with optional filtering.

    Query parameters:
    - vendor_id (str, optional): Filter by vendor
    - action (str, optional): Filter by action (agree/disagree/override)
    - limit (int, default 50): Max records to return
    - offset (int, default 0): Pagination offset

    Returns:
    {
        "success": bool,
        "feedback": [...feedback records...],
        "total": int,
        "limit": int,
        "offset": int,
        "error": str (if success=false)
    }
    """
    try:
        vendor_id = request.args.get("vendor_id")
        action = request.args.get("action")
        limit = min(int(request.args.get("limit", 50)), 500)  # Cap at 500
        offset = int(request.args.get("offset", 0))

        feedback_records = get_feedback(
            vendor_id=vendor_id,
            action=action,
            limit=limit,
            offset=offset,
        )

        return jsonify({
            "success": True,
            "feedback": feedback_records,
            "total": len(feedback_records),
            "limit": limit,
            "offset": offset,
        }), 200

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": f"Invalid parameter: {str(e)}"
        }), 400
    except Exception as e:
        logger.error(f"Error listing feedback: {e}")
        return jsonify({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }), 500


@feedback_bp.route("/stats", methods=["GET"])
def get_stats():
    """
    Get aggregate feedback statistics.

    Returns:
    {
        "success": bool,
        "stats": {
            "total": int,
            "agree_count": int,
            "disagree_count": int,
            "override_count": int,
            "agree_rate": float,
            "disagree_rate": float,
            "tier_confusion_matrix": {...},
            "most_overridden_factors": {...},
            "recent_feedback_count": int
        },
        "error": str (if success=false)
    }
    """
    try:
        stats = get_feedback_stats()

        return jsonify({
            "success": True,
            "stats": stats,
        }), 200

    except Exception as e:
        logger.error(f"Error getting feedback stats: {e}")
        return jsonify({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }), 500


@feedback_bp.route("/calibrate", methods=["POST"])
def trigger_calibration():
    """
    Trigger FGAMLogit weight calibration from analyst feedback.

    Request body (optional):
    {
        "min_samples": int (optional, default 30)
    }

    Returns:
    {
        "success": bool,
        "calibration": {
            "status": "calibrated"|"insufficient_data",
            "weights": {...calibrated weights...},
            "sample_size": int,
            "factor_details": [...],
            "calibrated_at": str,
            "model_version": str
        },
        "error": str (if success=false)
    }
    """
    try:
        data = request.get_json() or {}
        min_samples = data.get("min_samples", 30)

        calibration_result = calibrate_weights(min_samples=min_samples)

        return jsonify({
            "success": True,
            "calibration": calibration_result,
        }), 200

    except Exception as e:
        logger.error(f"Error triggering calibration: {e}")
        return jsonify({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }), 500


@feedback_bp.route("/weights", methods=["GET"])
def get_weights():
    """
    Get current active weights (calibrated if available, default otherwise).

    Returns:
    {
        "success": bool,
        "weights": {
            "weights": {...factor weights...},
            "source": "calibrated"|"default",
            "calibrated_at": str|null,
            "model_version": str
        },
        "error": str (if success=false)
    }
    """
    try:
        weights_info = get_active_weights()

        return jsonify({
            "success": True,
            "weights": weights_info,
        }), 200

    except Exception as e:
        logger.error(f"Error getting active weights: {e}")
        return jsonify({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }), 500
