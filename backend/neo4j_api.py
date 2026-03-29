"""
Neo4j Flask Blueprint for Helios compliance platform.

Provides REST API endpoints for Neo4j graph operations, including network traversal,
risk computation, and sync management. All endpoints require authentication via
JWT token in Authorization header.
"""

import logging
from datetime import datetime

from flask import Blueprint, request, jsonify

from auth import require_auth
from neo4j_integration import (
    is_neo4j_available,
    full_sync_from_postgres,
    incremental_sync,
    get_entity_network_neo4j,
    find_shortest_path_neo4j,
    find_shared_connections_neo4j,
    compute_network_risk_neo4j,
    compute_entity_centrality_neo4j,
    get_top_central_entities_neo4j,
    get_entity_neighbors_neo4j,
    get_graph_stats_neo4j,
)

logger = logging.getLogger(__name__)

# Create blueprint
neo4j_bp = Blueprint("neo4j", __name__, url_prefix="/api/neo4j")


# Health check endpoint (no auth required)
@neo4j_bp.route("/health", methods=["GET"])
def health_check():
    """Check if Neo4j is available."""
    available = is_neo4j_available()
    return jsonify(
        {
            "neo4j_available": available,
            "status": "available" if available else "unavailable",
            "timestamp": datetime.utcnow().isoformat(),
        }
    ), 200


@neo4j_bp.route("/sync", methods=["POST"])
@require_auth("graph:write")
def sync_full():
    """
    Trigger full sync from PostgreSQL to Neo4j.

    Returns:
        JSON with sync statistics (entities_synced, relationships_synced, duration_ms)
    """
    if not is_neo4j_available():
        logger.error("Neo4j not available for sync")
        return jsonify({"error": "Neo4j not available"}), 503

    try:
        logger.info("Starting full sync from PostgreSQL to Neo4j")
        result = full_sync_from_postgres()

        return jsonify(
            {
                "status": "success",
                "entities_synced": result.get("entities_synced", 0),
                "relationships_synced": result.get("relationships_synced", 0),
                "duration_ms": result.get("duration_ms", 0),
                "timestamp": datetime.utcnow().isoformat(),
            }
        ), 200

    except Exception as e:
        logger.error(f"Full sync failed: {e}")
        return jsonify({"error": str(e)}), 500


@neo4j_bp.route("/sync/incremental", methods=["POST"])
@require_auth("graph:write")
def sync_incremental():
    """
    Trigger incremental sync from PostgreSQL to Neo4j since a given timestamp.

    Request body:
        {
            "since": "2026-03-25T10:00:00"  # ISO format timestamp
        }

    Returns:
        JSON with sync statistics
    """
    if not is_neo4j_available():
        logger.error("Neo4j not available for incremental sync")
        return jsonify({"error": "Neo4j not available"}), 503

    try:
        data = request.get_json() or {}
        since_timestamp = data.get("since")

        if not since_timestamp:
            return jsonify({"error": "Missing 'since' timestamp in request body"}), 400

        logger.info(f"Starting incremental sync since {since_timestamp}")
        result = incremental_sync(since_timestamp)

        return jsonify(
            {
                "status": "success",
                "entities_synced": result.get("entities_synced", 0),
                "relationships_synced": result.get("relationships_synced", 0),
                "duration_ms": result.get("duration_ms", 0),
                "since": since_timestamp,
                "timestamp": datetime.utcnow().isoformat(),
            }
        ), 200

    except Exception as e:
        logger.error(f"Incremental sync failed: {e}")
        return jsonify({"error": str(e)}), 500


@neo4j_bp.route("/network/<entity_id>", methods=["GET"])
@require_auth("graph:read")
def get_network(entity_id):
    """
    Get entity network using variable-length path traversal.

    Query parameters:
        - depth: Max relationship depth (default 2)

    Returns:
        JSON with entities, relationships, and counts
    """
    if not is_neo4j_available():
        logger.error("Neo4j not available for network query")
        return jsonify({"error": "Neo4j not available"}), 503

    try:
        depth = request.args.get("depth", 2, type=int)
        if depth < 1 or depth > 10:
            return jsonify({"error": "Depth must be between 1 and 10"}), 400

        logger.info(f"Getting network for entity {entity_id} with depth {depth}")
        result = get_entity_network_neo4j(entity_id, depth=depth)

        if result is None:
            logger.warning(f"Could not retrieve network for entity {entity_id}")
            return jsonify({"error": "Failed to retrieve network from Neo4j"}), 500

        return jsonify(
            {
                "status": "success",
                "entity_id": entity_id,
                "depth": depth,
                "entities": result.get("entities", {}),
                "relationships": result.get("relationships", []),
                "entity_count": result.get("entity_count", 0),
                "relationship_count": result.get("relationship_count", 0),
            }
        ), 200

    except Exception as e:
        logger.error(f"Error getting network for {entity_id}: {e}")
        return jsonify({"error": str(e)}), 500


@neo4j_bp.route("/path/<source_id>/<target_id>", methods=["GET"])
@require_auth("graph:read")
def get_shortest_path(source_id, target_id):
    """
    Find shortest path between two entities.

    Query parameters:
        - max_depth: Maximum path length (default 6)

    Returns:
        JSON with path nodes and relationships
    """
    if not is_neo4j_available():
        logger.error("Neo4j not available for path query")
        return jsonify({"error": "Neo4j not available"}), 503

    try:
        max_depth = request.args.get("max_depth", 6, type=int)
        if max_depth < 1 or max_depth > 20:
            return jsonify({"error": "max_depth must be between 1 and 20"}), 400

        logger.info(f"Finding shortest path from {source_id} to {target_id}")
        result = find_shortest_path_neo4j(source_id, target_id, max_depth=max_depth)

        if result is None:
            logger.info(f"No path found from {source_id} to {target_id}")
            return jsonify(
                {
                    "status": "success",
                    "source_id": source_id,
                    "target_id": target_id,
                    "path_found": False,
                    "nodes": [],
                    "relationships": [],
                }
            ), 200

        return jsonify(
            {
                "status": "success",
                "source_id": source_id,
                "target_id": target_id,
                "path_found": True,
                "nodes": result.get("nodes", []),
                "relationships": result.get("relationships", []),
                "path_length": len(result.get("nodes", [])) - 1,
            }
        ), 200

    except Exception as e:
        logger.error(f"Error finding path from {source_id} to {target_id}: {e}")
        return jsonify({"error": str(e)}), 500


@neo4j_bp.route("/shared/<entity_id_a>/<entity_id_b>", methods=["GET"])
@require_auth("graph:read")
def get_shared_connections(entity_id_a, entity_id_b):
    """
    Find entities connected to both A and B within 3 hops.

    Returns:
        JSON with list of shared connection entities
    """
    if not is_neo4j_available():
        logger.error("Neo4j not available for shared connections query")
        return jsonify({"error": "Neo4j not available"}), 503

    try:
        logger.info(f"Finding shared connections between {entity_id_a} and {entity_id_b}")
        result = find_shared_connections_neo4j(entity_id_a, entity_id_b)

        if result is None:
            logger.warning("Could not retrieve shared connections")
            return jsonify({"error": "Failed to retrieve shared connections from Neo4j"}), 500

        return jsonify(
            {
                "status": "success",
                "entity_id_a": entity_id_a,
                "entity_id_b": entity_id_b,
                "shared_connections": result,
                "connection_count": len(result),
            }
        ), 200

    except Exception as e:
        logger.error(f"Error finding shared connections: {e}")
        return jsonify({"error": str(e)}), 500


@neo4j_bp.route("/neighbors/<entity_id>", methods=["GET"])
@require_auth("graph:read")
def get_neighbors(entity_id):
    """
    Get immediate neighbors of an entity for "expand node" in frontend.

    Query parameters:
        - rel_types: Comma-separated relationship types to filter by (optional)

    Returns:
        JSON with list of neighbor entities
    """
    if not is_neo4j_available():
        logger.error("Neo4j not available for neighbors query")
        return jsonify({"error": "Neo4j not available"}), 503

    try:
        # Parse rel_types query parameter
        rel_types_param = request.args.get("rel_types", "")
        rel_types = [rt.strip() for rt in rel_types_param.split(",")] if rel_types_param else None

        logger.info(f"Getting neighbors for entity {entity_id}")
        result = get_entity_neighbors_neo4j(entity_id, rel_types=rel_types)

        if result is None:
            logger.warning(f"Could not retrieve neighbors for entity {entity_id}")
            return jsonify({"error": "Failed to retrieve neighbors from Neo4j"}), 500

        return jsonify(
            {
                "status": "success",
                "entity_id": entity_id,
                "rel_types_filter": rel_types,
                "neighbors": result,
                "neighbor_count": len(result),
            }
        ), 200

    except Exception as e:
        logger.error(f"Error getting neighbors for {entity_id}: {e}")
        return jsonify({"error": str(e)}), 500


@neo4j_bp.route("/risk/<entity_id>", methods=["GET"])
@require_auth("graph:read")
def get_network_risk(entity_id):
    """
    Compute network risk propagation for an entity.

    Query parameters:
        - max_hops: Maximum hops to traverse (default 2)

    Returns:
        JSON with risk scores and connected entity risks
    """
    if not is_neo4j_available():
        logger.error("Neo4j not available for risk query")
        return jsonify({"error": "Neo4j not available"}), 503

    try:
        max_hops = request.args.get("max_hops", 2, type=int)
        if max_hops < 1 or max_hops > 10:
            return jsonify({"error": "max_hops must be between 1 and 10"}), 400

        logger.info(f"Computing network risk for entity {entity_id}")
        result = compute_network_risk_neo4j(entity_id, max_hops=max_hops)

        if result is None:
            logger.warning(f"Could not compute risk for entity {entity_id}")
            return jsonify({"error": "Failed to compute network risk"}), 500

        return jsonify(
            {
                "status": "success",
                "entity_id": entity_id,
                "base_risk": result.get("base_risk"),
                "network_risk": result.get("network_risk"),
                "risk_score": result.get("risk_score"),
                "connected_risks": result.get("connected_risks", []),
                "duration_ms": result.get("duration_ms", 0),
            }
        ), 200

    except Exception as e:
        logger.error(f"Error computing risk for {entity_id}: {e}")
        return jsonify({"error": str(e)}), 500


@neo4j_bp.route("/stats", methods=["GET"])
@require_auth("graph:read")
def get_stats():
    """
    Get overall Neo4j graph statistics.

    Returns:
        JSON with node counts, relationship counts, and type distributions
    """
    if not is_neo4j_available():
        logger.error("Neo4j not available for stats query")
        return jsonify({"error": "Neo4j not available"}), 503

    try:
        logger.info("Getting graph statistics")
        result = get_graph_stats_neo4j()

        if result is None:
            logger.warning("Could not retrieve graph statistics")
            return jsonify({"error": "Failed to retrieve statistics from Neo4j"}), 500

        return jsonify(
            {
                "status": "success",
                "node_count": result.get("node_count", 0),
                "relationship_count": result.get("relationship_count", 0),
                "node_types": result.get("node_types", {}),
                "relationship_types": result.get("relationship_types", {}),
                "timestamp": datetime.utcnow().isoformat(),
            }
        ), 200

    except Exception as e:
        logger.error(f"Error getting graph stats: {e}")
        return jsonify({"error": str(e)}), 500


@neo4j_bp.route("/centrality/<entity_id>", methods=["GET"])
@require_auth("graph:read")
def get_centrality(entity_id):
    """
    Compute centrality metrics for an entity.

    Returns degree centrality, bridging power, influence score, and neighbor type breakdown.
    """
    if not is_neo4j_available():
        return jsonify({"error": "Neo4j not available"}), 503

    try:
        result = compute_entity_centrality_neo4j(entity_id)
        if result is None:
            return jsonify({"error": f"Entity {entity_id} not found in Neo4j"}), 404

        return jsonify({"status": "success", **result}), 200

    except Exception as e:
        logger.error(f"Error computing centrality for {entity_id}: {e}")
        return jsonify({"error": str(e)}), 500


@neo4j_bp.route("/top-entities", methods=["GET"])
@require_auth("graph:read")
def get_top_entities():
    """
    Get the most connected entities in the graph.

    Query parameters:
        - limit: Max results (default 20)
    """
    if not is_neo4j_available():
        return jsonify({"error": "Neo4j not available"}), 503

    try:
        limit = int(request.args.get("limit", "20"))
        result = get_top_central_entities_neo4j(limit=limit)
        if result is None:
            return jsonify({"error": "Failed to retrieve top entities"}), 500

        return jsonify({
            "status": "success",
            "entities": result,
            "count": len(result),
            "timestamp": datetime.utcnow().isoformat(),
        }), 200

    except Exception as e:
        logger.error(f"Error getting top entities: {e}")
        return jsonify({"error": str(e)}), 500


# Error handlers
@neo4j_bp.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({"error": "Endpoint not found"}), 404


@neo4j_bp.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500
