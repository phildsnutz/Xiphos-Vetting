"""
Flask API for graph embeddings and link prediction.

Provides REST endpoints for:
- Training embeddings (/api/graph/train-embeddings)
- Predicting missing links (/api/graph/predicted-links/<entity_id>)
- Finding similar entities (/api/graph/similar-entities/<entity_id>)
- Analyst review of predictions (/api/graph/predicted-links/<link_id>/review)
- Model stats (/api/graph/embedding-stats)

Register as a Blueprint in server.py:
    from link_prediction_api import link_prediction_bp
    app.register_blueprint(link_prediction_bp)
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Blueprint, jsonify, request
from graph_embeddings import (
    TransETrainer,
    get_predicted_links,
    get_prediction_review_stats,
    list_predicted_link_queue,
    queue_predicted_links,
    review_predicted_links,
    train_and_save,
)

logger = logging.getLogger(__name__)

link_prediction_bp = Blueprint("link_prediction", __name__, url_prefix="/api/graph")
REPORTS_ROOT = Path(__file__).resolve().parents[1] / "docs" / "reports"
RUNTIME_REPORTS_ROOT = Path("/data/reports")
REPORT_SEARCH_ROOTS = [REPORTS_ROOT, RUNTIME_REPORTS_ROOT]


# ---------------------------------------------------------------------------
# Helper: Get PostgreSQL URL from environment or config
# ---------------------------------------------------------------------------

def _get_pg_url() -> str:
    """Get PostgreSQL URL from environment."""
    import os
    pg_url = os.environ.get("XIPHOS_PG_URL")
    if not pg_url:
        raise ValueError("XIPHOS_PG_URL environment variable not set")
    return pg_url


def _get_auth_user() -> Optional[str]:
    """Extract authenticated user from request context (if using auth middleware)."""
    # If your auth system sets g.user or similar, extract it here
    # For now, return a generic identifier
    return request.headers.get("X-User-Id", "unknown")


def _report_sort_key(path: Path) -> tuple[float, str]:
    try:
        return (path.stat().st_mtime, str(path))
    except OSError:
        return (0.0, str(path))


def _latest_matching_summary(*relative_dirs: str) -> Path | None:
    candidates: list[Path] = []
    for root in REPORT_SEARCH_ROOTS:
        for relative_dir in relative_dirs:
            candidates.extend((root / relative_dir).glob("**/summary.json"))
    if not candidates:
        return None
    return max(candidates, key=_report_sort_key)


def _latest_neo4j_report() -> Path | None:
    candidates: list[Path] = []
    for root in REPORT_SEARCH_ROOTS:
        candidates.extend(root.glob("neo4j_graph_drift_audit*/neo4j-graph-drift-audit-*.json"))
        candidates.extend(root.glob("neo4j_graph_drift_audit*/**/*.json"))
    if not candidates:
        return None
    return max(candidates, key=_report_sort_key)


def _read_report_json(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _summary_verdict(payload: dict) -> str | None:
    for key in ("overall_verdict", "prime_time_verdict", "verdict"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _summary_timestamp(payload: dict) -> str | None:
    for key in ("generated_at", "timestamp", "created_at", "updated_at"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def build_training_dashboard_payload() -> dict:
    readiness_path = _latest_matching_summary("helios_readiness", "readiness")
    benchmark_path = _latest_matching_summary("graph_training_benchmark")
    tranche_path = _latest_matching_summary("live_graph_training_tranche", "graph_training_tranche", "graph_training_tranche_live")
    neo4j_path = _latest_neo4j_report()

    readiness = _read_report_json(readiness_path)
    benchmark = _read_report_json(benchmark_path)
    tranche = _read_report_json(tranche_path)
    neo4j = _read_report_json(neo4j_path)

    review_stats = tranche.get("review_stats") if isinstance(tranche.get("review_stats"), dict) else {}
    stage_metrics = tranche.get("stage_metrics") if isinstance(tranche.get("stage_metrics"), dict) else {}
    missing_edge = stage_metrics.get("missing_edge_recovery") if isinstance(stage_metrics.get("missing_edge_recovery"), dict) else {}
    stage_results = benchmark.get("stage_results") if isinstance(benchmark.get("stage_results"), list) else []
    data_foundation = benchmark.get("data_foundation") if isinstance(benchmark.get("data_foundation"), dict) else {}

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "readiness": {
            "verdict": _summary_verdict(readiness),
            "generated_at": _summary_timestamp(readiness),
            "path": str(readiness_path) if readiness_path else None,
        },
        "neo4j": {
            "verdict": _summary_verdict(neo4j),
            "generated_at": _summary_timestamp(neo4j),
            "path": str(neo4j_path) if neo4j_path else None,
            "node_count": neo4j.get("neo4j_node_count"),
            "relationship_count": neo4j.get("neo4j_relationship_count"),
        },
        "benchmark": {
            "verdict": _summary_verdict(benchmark),
            "generated_at": _summary_timestamp(benchmark),
            "path": str(benchmark_path) if benchmark_path else None,
            "data_foundation_verdict": data_foundation.get("verdict"),
            "passing_stage_count": sum(1 for stage in stage_results if isinstance(stage, dict) and stage.get("verdict") == "PASS"),
            "total_stage_count": len(stage_results),
            "stage_results": [
                {
                    "stage_id": str(stage.get("stage_id") or ""),
                    "verdict": str(stage.get("verdict") or "UNKNOWN"),
                    "objective": str(stage.get("objective") or ""),
                }
                for stage in stage_results
                if isinstance(stage, dict)
            ],
        },
        "live_tranche": {
            "generated_at": _summary_timestamp(tranche),
            "path": str(tranche_path) if tranche_path else None,
            "reviewed_links": int(review_stats.get("reviewed_links") or 0),
            "pending_links": int(review_stats.get("pending_links") or 0),
            "novel_pending_links": int(review_stats.get("novel_pending_links") or 0),
            "confirmed_links": int(review_stats.get("confirmed_links") or 0),
            "rejected_links": int(review_stats.get("rejected_links") or 0),
            "review_coverage_pct": float(review_stats.get("review_coverage_pct") or 0.0),
            "confirmation_rate": float(review_stats.get("confirmation_rate") or 0.0),
            "ownership_control_hits_at_10": float(missing_edge.get("ownership_control_hits_at_10") or 0.0),
            "ownership_control_mrr": float(missing_edge.get("ownership_control_mrr") or 0.0),
            "intermediary_route_queries_evaluated": int(missing_edge.get("intermediary_route_queries_evaluated") or 0),
            "cyber_dependency_queries_evaluated": int(missing_edge.get("cyber_dependency_queries_evaluated") or 0),
        },
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@link_prediction_bp.route("/train-embeddings", methods=["POST"])
def train_embeddings():
    """
    Train graph embeddings and save to pgvector.

    POST /api/graph/train-embeddings
    Returns:
        {
            "status": "training_complete",
            "entities": int,
            "relations": int,
            "final_loss": float,
            "duration_ms": int,
            "embeddings_saved": int
        }
    """
    try:
        pg_url = _get_pg_url()
        logger.info("Starting embedding training requested by %s", _get_auth_user())

        start_time = time.time()
        results = train_and_save(pg_url, dim=64)
        duration_ms = int((time.time() - start_time) * 1000)

        response = {
            "status": "training_complete",
            "entities": results.get("entity_count", 0),
            "relations": results.get("relation_count", 0),
            "final_loss": results.get("final_loss", 0.0),
            "duration_ms": duration_ms,
            "embeddings_saved": results.get("embeddings_saved", 0),
            "trained_at": datetime.utcnow().isoformat(),
        }

        logger.info("Training complete: %s", response)
        return jsonify(response), 200

    except Exception as e:
        logger.exception("Training failed")
        return jsonify({"error": str(e)}), 500


@link_prediction_bp.route("/predicted-links/<entity_id>", methods=["GET"])
def get_predicted_links_endpoint(entity_id: str):
    """
    Get predicted missing links for an entity.

    GET /api/graph/predicted-links/<entity_id>?top_k=10
    Query params:
        - top_k: Number of predictions (default 10, max 100)

    Returns:
        {
            "entity_id": str,
            "entity_name": str,
            "predictions": [
                {
                    "target_entity_id": str,
                    "target_name": str,
                    "predicted_relation": str,
                    "score": float
                }
            ],
            "model_version": str,
            "count": int
        }
    """
    try:
        pg_url = _get_pg_url()
        top_k = min(int(request.args.get("top_k", 10)), 100)

        # Load entity name
        entity_name = _get_entity_name(pg_url, entity_id)
        if not entity_name:
            return jsonify({"error": f"Entity {entity_id} not found"}), 404

        persist = str(request.args.get("persist", "")).strip().lower() in {"1", "true", "yes"}
        predictions = get_predicted_links(pg_url, entity_id, top_k=top_k)
        queue_summary = queue_predicted_links(pg_url, entity_id, top_k=top_k) if persist else None

        response = {
            "entity_id": entity_id,
            "entity_name": entity_name,
            "predictions": predictions,
            "model_version": _get_model_version(pg_url),
            "count": len(predictions),
            "persisted": persist,
            "queue_summary": queue_summary,
        }

        logger.info("Returned %d predicted links for %s", len(predictions), entity_id)
        return jsonify(response), 200

    except Exception as e:
        logger.exception("Failed to predict links for %s", entity_id)
        return jsonify({"error": str(e)}), 500


@link_prediction_bp.route("/similar-entities/<entity_id>", methods=["GET"])
def get_similar_entities(entity_id: str):
    """
    Find entities with similar embeddings.

    GET /api/graph/similar-entities/<entity_id>?top_k=10
    Query params:
        - top_k: Number of similar entities (default 10, max 100)

    Returns:
        {
            "entity_id": str,
            "entity_name": str,
            "similar": [
                {
                    "entity_id": str,
                    "name": str,
                    "similarity": float,
                    "entity_type": str
                }
            ],
            "model_version": str,
            "count": int
        }
    """
    try:
        pg_url = _get_pg_url()
        top_k = min(int(request.args.get("top_k", 10)), 100)

        # Load entity name
        entity_name = _get_entity_name(pg_url, entity_id)
        if not entity_name:
            return jsonify({"error": f"Entity {entity_id} not found"}), 404

        # Load embeddings
        trainer = TransETrainer()
        if not trainer.load_embeddings_from_db(pg_url):
            return jsonify({"error": "Embeddings not found. Train first."}), 404

        # Get similar entities
        similar = trainer.get_similar_entities(entity_id, top_k=top_k)

        # Enrich with entity data
        import psycopg2
        conn = psycopg2.connect(pg_url)
        cur = conn.cursor()

        try:
            for item in similar:
                eid = item["entity_id"]
                cur.execute(
                    "SELECT canonical_name, entity_type FROM kg_entities WHERE id = %s",
                    (eid,),
                )
                row = cur.fetchone()
                if row:
                    item["name"] = row[0]
                    item["entity_type"] = row[1]

        finally:
            cur.close()
            conn.close()

        response = {
            "entity_id": entity_id,
            "entity_name": entity_name,
            "similar": similar,
            "model_version": _get_model_version(pg_url),
            "count": len(similar),
        }

        logger.info("Found %d similar entities for %s", len(similar), entity_id)
        return jsonify(response), 200

    except Exception as e:
        logger.exception("Failed to find similar entities for %s", entity_id)
        return jsonify({"error": str(e)}), 500


@link_prediction_bp.route("/predicted-links/<int:link_id>/review", methods=["POST"])
def review_predicted_link(link_id: int):
    """
    Analyst review of a predicted link (confirm or reject).

    POST /api/graph/predicted-links/<link_id>/review
    Body:
        {
            "confirmed": true or false,
            "notes": "optional analyst notes"
        }

    Returns:
        {
            "id": int,
            "status": "confirmed" or "rejected",
            "created_at": str
        }
    """
    try:
        pg_url = _get_pg_url()
        user_id = _get_auth_user()
        data = request.get_json() or {}
        summary = review_predicted_links(
            pg_url,
            [
                {
                    "id": link_id,
                    "confirmed": bool(data.get("confirmed", False)),
                    "notes": data.get("notes"),
                    "rejection_reason": data.get("rejection_reason"),
                }
            ],
            reviewed_by=user_id,
        )
        item = summary["items"][0]
        return jsonify(
            {
                "id": int(item["id"]),
                "status": item["status"],
                "rejection_reason": item.get("rejection_reason"),
                "relationship_created": bool(item["relationship_created"]),
                "promoted_relationship_id": item.get("promoted_relationship_id"),
                "reviewed_by": user_id,
                "reviewed_at": summary["reviewed_at"],
            }
        ), 200

    except Exception as e:
        logger.exception("Failed to review predicted link %d", link_id)
        return jsonify({"error": str(e)}), 500


@link_prediction_bp.route("/predicted-links/<entity_id>/queue", methods=["POST"])
def queue_predicted_links_endpoint(entity_id: str):
    """Generate and persist predicted-link candidates for analyst review."""
    try:
        pg_url = _get_pg_url()
        data = request.get_json(silent=True) or {}
        top_k = min(int(data.get("top_k", request.args.get("top_k", 25))), 100)
        entity_name = _get_entity_name(pg_url, entity_id)
        if not entity_name:
            return jsonify({"error": f"Entity {entity_id} not found"}), 404
        summary = queue_predicted_links(pg_url, entity_id, top_k=top_k)
        return jsonify(summary), 202
    except Exception as e:
        logger.exception("Failed to queue predicted links for %s", entity_id)
        return jsonify({"error": str(e)}), 500


@link_prediction_bp.route("/predicted-links/review-queue", methods=["GET"])
def get_predicted_links_review_queue():
    """Return queued predicted links with analyst review metadata."""
    try:
        pg_url = _get_pg_url()

        def _parse_bool(raw: str) -> Optional[bool]:
            normalized = str(raw or "").strip().lower()
            if normalized in {"1", "true", "yes"}:
                return True
            if normalized in {"0", "false", "no"}:
                return False
            return None

        rows = list_predicted_link_queue(
            pg_url,
            reviewed=_parse_bool(request.args.get("reviewed", "")),
            analyst_confirmed=_parse_bool(request.args.get("confirmed", "")),
            novel_only=_parse_bool(request.args.get("novel_only", "")),
            edge_family=str(request.args.get("edge_family", "")).strip() or None,
            model_version=str(request.args.get("model_version", "")).strip() or None,
            source_entity_id=str(request.args.get("source_entity_id", "")).strip() or None,
            limit=min(int(request.args.get("limit", 100)), 500),
            offset=max(int(request.args.get("offset", 0)), 0),
        )
        return jsonify({"count": len(rows), "predictions": rows}), 200
    except Exception as e:
        logger.exception("Failed to fetch predicted link review queue")
        return jsonify({"error": str(e)}), 500


@link_prediction_bp.route("/predicted-links/review-batch", methods=["POST"])
def review_predicted_links_batch_endpoint():
    """Review multiple predicted links in one call."""
    try:
        pg_url = _get_pg_url()
        user_id = _get_auth_user()
        data = request.get_json() or {}
        reviews = data.get("reviews")
        if not isinstance(reviews, list) or not reviews:
            return jsonify({"error": "reviews list is required"}), 400
        return jsonify(review_predicted_links(pg_url, reviews, reviewed_by=user_id)), 200
    except Exception as e:
        logger.exception("Failed to review predicted links in batch")
        return jsonify({"error": str(e)}), 500


@link_prediction_bp.route("/predicted-links/review-stats", methods=["GET"])
def get_predicted_link_review_stats_endpoint():
    try:
        pg_url = _get_pg_url()
        source_entity_id = str(request.args.get("source_entity_id", "")).strip() or None
        return jsonify(get_prediction_review_stats(pg_url, source_entity_id=source_entity_id)), 200
    except Exception as e:
        logger.exception("Failed to fetch predicted link review stats")
        return jsonify({"error": str(e)}), 500


@link_prediction_bp.route("/training-dashboard", methods=["GET"])
def get_graph_training_dashboard():
    try:
        return jsonify(build_training_dashboard_payload()), 200
    except Exception as e:
        logger.exception("Failed to build graph training dashboard")
        return jsonify({"error": str(e)}), 500


@link_prediction_bp.route("/embedding-stats", methods=["GET"])
def get_embedding_stats():
    """
    Get current embedding model statistics.

    GET /api/graph/embedding-stats
    Returns:
        {
            "entity_count": int,
            "relation_count": int,
            "model_version": str,
            "trained_at": str,
            "predicted_links_count": int,
            "predicted_links_reviewed": int,
            "predicted_links_confirmed": int
        }
    """
    try:
        pg_url = _get_pg_url()

        import psycopg2
        conn = psycopg2.connect(pg_url)
        cur = conn.cursor()

        try:
            # Entity embeddings
            cur.execute("SELECT COUNT(*), MAX(trained_at), MAX(model_version) FROM kg_embeddings")
            entity_count, trained_at, model_version = cur.fetchone() or (0, None, None)

            # Relation embeddings
            cur.execute("SELECT COUNT(*) FROM kg_relation_embeddings")
            (relation_count,) = cur.fetchone() or (0,)

            review_stats = get_prediction_review_stats(pg_url)

            response = {
                "entity_count": entity_count or 0,
                "relation_count": relation_count or 0,
                "model_version": model_version or "unknown",
                "trained_at": trained_at.isoformat() if trained_at else None,
                "predicted_links_count": review_stats.get("total_links", 0),
                "predicted_links_reviewed": review_stats.get("reviewed_links", 0),
                "predicted_links_confirmed": review_stats.get("confirmed_links", 0),
                "predicted_links_confirmation_rate": review_stats.get("confirmation_rate", 0.0),
                "predicted_links_review_coverage_pct": review_stats.get("review_coverage_pct", 0.0),
                "predicted_links_by_edge_family": review_stats.get("by_edge_family", []),
            }

            return jsonify(response), 200

        finally:
            cur.close()
            conn.close()

    except Exception as e:
        logger.exception("Failed to fetch embedding stats")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _get_entity_name(pg_url: str, entity_id: str) -> Optional[str]:
    """Fetch entity name from database."""
    try:
        import psycopg2
        conn = psycopg2.connect(pg_url)
        cur = conn.cursor()

        try:
            cur.execute("SELECT canonical_name FROM kg_entities WHERE id = %s", (entity_id,))
            row = cur.fetchone()
            return row[0] if row else None

        finally:
            cur.close()
            conn.close()

    except Exception as e:
        logger.warning("Failed to fetch entity name for %s: %s", entity_id, e)
        return None


def _get_model_version(pg_url: str) -> str:
    """Fetch latest model version from database."""
    try:
        import psycopg2
        conn = psycopg2.connect(pg_url)
        cur = conn.cursor()

        try:
            cur.execute("SELECT MAX(model_version) FROM kg_embeddings")
            row = cur.fetchone()
            return row[0] if row and row[0] else "unknown"

        finally:
            cur.close()
            conn.close()

    except Exception as e:
        logger.warning("Failed to fetch model version: %s", e)
        return "unknown"
