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

import logging
import time
from datetime import datetime
from typing import Optional

from flask import Blueprint, jsonify, request
from graph_embeddings import TransETrainer, train_and_save, get_predicted_links

logger = logging.getLogger(__name__)

link_prediction_bp = Blueprint("link_prediction", __name__, url_prefix="/api/graph")


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

        # Get predictions
        predictions = get_predicted_links(pg_url, entity_id, top_k=top_k)

        response = {
            "entity_id": entity_id,
            "entity_name": entity_name,
            "predictions": predictions,
            "model_version": _get_model_version(pg_url),
            "count": len(predictions),
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
                    "SELECT name, entity_type FROM kg_entities WHERE entity_id = %s",
                    (eid,)
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
        confirmed = data.get("confirmed", False)

        import psycopg2
        conn = psycopg2.connect(pg_url)
        cur = conn.cursor()

        try:
            # Fetch the predicted link
            cur.execute(
                """
                SELECT id, source_entity_id, target_entity_id, predicted_relation, score
                FROM kg_predicted_links
                WHERE id = %s
                """,
                (link_id,),
            )
            row = cur.fetchone()

            if not row:
                return jsonify({"error": f"Predicted link {link_id} not found"}), 404

            link_id_val, source_id, target_id, rel_type, score = row

            # Update review status
            cur.execute(
                """
                UPDATE kg_predicted_links
                SET reviewed = TRUE, analyst_confirmed = %s
                WHERE id = %s
                """,
                (confirmed, link_id_val),
            )

            # If confirmed, create real relationship
            if confirmed:
                cur.execute(
                    """
                    INSERT INTO kg_relationships
                        (source_entity_id, target_entity_id, relationship_type, confidence, source)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_entity_id, target_entity_id, relationship_type) DO NOTHING
                    """,
                    (source_id, target_id, rel_type, score, "link_prediction_analyst_review"),
                )
                logger.info("Created relationship: %s -> %s (%s) [score=%.4f, analyst=%s]",
                           source_id, target_id, rel_type, score, user_id)

            conn.commit()

            response = {
                "id": link_id_val,
                "status": "confirmed" if confirmed else "rejected",
                "relationship_created": confirmed,
                "reviewed_by": user_id,
                "reviewed_at": datetime.utcnow().isoformat(),
            }

            return jsonify(response), 200

        finally:
            cur.close()
            conn.close()

    except Exception as e:
        logger.exception("Failed to review predicted link %d", link_id)
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

            # Predicted links stats
            cur.execute("SELECT COUNT(*) FROM kg_predicted_links")
            (total_links,) = cur.fetchone() or (0,)

            cur.execute("SELECT COUNT(*) FROM kg_predicted_links WHERE reviewed = TRUE")
            (reviewed_links,) = cur.fetchone() or (0,)

            cur.execute("SELECT COUNT(*) FROM kg_predicted_links WHERE analyst_confirmed = TRUE")
            (confirmed_links,) = cur.fetchone() or (0,)

            response = {
                "entity_count": entity_count or 0,
                "relation_count": relation_count or 0,
                "model_version": model_version or "unknown",
                "trained_at": trained_at.isoformat() if trained_at else None,
                "predicted_links_count": total_links or 0,
                "predicted_links_reviewed": reviewed_links or 0,
                "predicted_links_confirmed": confirmed_links or 0,
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
            cur.execute("SELECT name FROM kg_entities WHERE entity_id = %s", (entity_id,))
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
