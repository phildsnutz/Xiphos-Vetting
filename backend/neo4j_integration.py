"""
Neo4j integration layer for Helios compliance platform.

Handles all Neo4j Aura connections, Cypher operations, and bidirectional sync
with PostgreSQL knowledge graph. Replaces SQL-based graph traversal with Neo4j
queries for improved performance and scalability.
"""

import os
import logging
import time
import threading
from typing import Optional, Dict, List, Any
from contextlib import contextmanager

from neo4j import GraphDatabase, Driver, Session
from neo4j.exceptions import ServiceUnavailable, AuthError

from knowledge_graph import get_kg_conn

logger = logging.getLogger(__name__)

# Global driver instance
_driver: Optional[Driver] = None
_driver_lock = threading.Lock()

# Relationship weight mapping for network risk propagation
RELATIONSHIP_WEIGHTS = {
    "subsidiary_of": 0.80,
    "subcontractor_of": 0.50,
    "prime_contractor_of": 0.50,
    "contracts_with": 0.30,
    "litigant_in": 0.20,
    "officer_of": 0.40,
    "sanctioned_on": 0.60,
    "sanctioned_person": 0.90,
    "deemed_export_subject": 0.70,
    "has_vulnerability": 0.65,
    "uses_product": 0.35,
    "supplies_component": 0.55,
    "supplies_component_to": 0.70,
    "integrated_into": 0.60,
    "owned_by": 0.85,
    "beneficially_owned_by": 0.95,
    "depends_on_network": 0.55,
    "routes_payment_through": 0.45,
    "distributed_by": 0.40,
    "operates_facility": 0.35,
    "ships_via": 0.35,
    "depends_on_service": 0.45,
    "parent_of": 0.80,
    "former_name": 1.0,
    "alias_of": 1.0,
    "related_entity": 0.30,
    "filed_with": 0.20,
    "regulated_by": 0.25,
    "mentioned_with": 0.15,
}
NEO4J_ENTITY_BATCH_SIZE = max(1, int(os.environ.get("XIPHOS_NEO4J_ENTITY_BATCH_SIZE", "500") or "500"))
NEO4J_REL_BATCH_SIZE = max(1, int(os.environ.get("XIPHOS_NEO4J_REL_BATCH_SIZE", "250") or "250"))
NEO4J_REL_SINGLE_RETRIES = max(1, int(os.environ.get("XIPHOS_NEO4J_REL_SINGLE_RETRIES", "3") or "3"))
_REL_BATCH_SIZE_OVERRIDES = {
    "FILED_WITH": max(1, int(os.environ.get("XIPHOS_NEO4J_FILED_WITH_BATCH_SIZE", "100") or "100")),
}


def get_neo4j_database() -> Optional[str]:
    """
    Resolve the target Neo4j database name.

    Aura free instances often use the instance ID as both the username and the
    database name. If no explicit database is configured, derive it from the
    non-default user before falling back to the server default.
    """
    explicit = os.environ.get("NEO4J_DATABASE", "").strip()
    if explicit:
        return explicit

    user = os.environ.get("NEO4J_USER", "").strip()
    if user and user.lower() != "neo4j":
        return user
    return None


def _neo4j_session_kwargs() -> dict[str, Any]:
    database = get_neo4j_database()
    if database:
        return {"database": database}
    return {}


def _verify_driver_connectivity(driver: Driver) -> None:
    with driver.session(**_neo4j_session_kwargs()) as session:
        session.run("RETURN 1 AS ok").single()


def is_neo4j_available() -> bool:
    """
    Check if Neo4j is configured and available.

    Returns:
        True if NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD are set and connection works.
        False otherwise.
    """
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")

    if not uri or not password:
        logger.debug("Neo4j not configured: missing URI or PASSWORD env vars")
        return False

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password), max_connection_pool_size=5)
        _verify_driver_connectivity(driver)
        driver.close()
        logger.info("Neo4j connectivity verified for database %s", get_neo4j_database() or "<default>")
        return True
    except (ServiceUnavailable, AuthError) as e:
        logger.warning(f"Neo4j unavailable: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error checking Neo4j availability: {e}")
        return False


def get_neo4j_driver() -> Optional[Driver]:
    """
    Get or create singleton Neo4j driver instance.

    Returns:
        Neo4j Driver instance if configured, None otherwise.
    """
    global _driver

    if _driver is not None:
        return _driver

    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")

    if not uri or not password:
        logger.debug("Neo4j driver not initialized: missing configuration")
        return None

    with _driver_lock:
        if _driver is not None:
            return _driver

        try:
            driver = GraphDatabase.driver(
                uri,
                auth=(user, password),
                max_connection_pool_size=10,
                connection_timeout=30,
            )
            _verify_driver_connectivity(driver)
            _driver = driver
            logger.info(f"Neo4j driver initialized: {uri}")
            return _driver
        except Exception as e:
            logger.error(f"Failed to initialize Neo4j driver: {e}")
            return None


def _is_deadlock_error(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "")
    message = str(exc)
    return "DeadlockDetected" in code or "DeadlockDetected" in message


def _relationship_merge_cypher(rel_type: str, single: bool = False) -> str:
    if single:
        return f"""
        MATCH (source:Entity {{id: $rel.source_entity_id}})
        MATCH (target:Entity {{id: $rel.target_entity_id}})
        MERGE (source)-[r:{rel_type} {{kg_id: $rel.kg_id}}]->(target)
        SET r.rel_type = $rel.rel_type,
            r.source_entity_id = $rel.source_entity_id,
            r.target_entity_id = $rel.target_entity_id,
            r.confidence = $rel.confidence,
            r.data_source = $rel.data_source,
            r.evidence = $rel.evidence,
            r.created_at = $rel.created_at,
            r.updated_at = toString(datetime())
        RETURN count(r) as count
        """
    return f"""
    UNWIND $rels AS rel
    WITH rel
    ORDER BY rel.source_entity_id, rel.target_entity_id, rel.kg_id
    MATCH (source:Entity {{id: rel.source_entity_id}})
    MATCH (target:Entity {{id: rel.target_entity_id}})
    MERGE (source)-[r:{rel_type} {{kg_id: rel.kg_id}}]->(target)
    SET r.rel_type = rel.rel_type,
        r.source_entity_id = rel.source_entity_id,
        r.target_entity_id = rel.target_entity_id,
        r.confidence = rel.confidence,
        r.data_source = rel.data_source,
        r.evidence = rel.evidence,
        r.created_at = rel.created_at,
        r.updated_at = toString(datetime())
    RETURN count(r) as count
    """


def _run_relationship_batch(driver: Driver, rel_type: str, rels: List[Dict[str, Any]]) -> int:
    with get_neo4j_session(driver) as session:
        result = session.run(_relationship_merge_cypher(rel_type), rels=rels)
        record = result.single()
        return int((record or {}).get("count") or len(rels))


def _relationship_batch_size(rel_type: str) -> int:
    normalized = str(rel_type or "").strip().upper()
    return _REL_BATCH_SIZE_OVERRIDES.get(normalized, NEO4J_REL_BATCH_SIZE)


def _run_single_relationship(driver: Driver, rel_type: str, rel: Dict[str, Any]) -> int:
    last_exc: Optional[Exception] = None
    for attempt in range(NEO4J_REL_SINGLE_RETRIES):
        try:
            with get_neo4j_session(driver) as session:
                result = session.run(_relationship_merge_cypher(rel_type, single=True), rel=rel)
                record = result.single()
                return int((record or {}).get("count") or 1)
        except Exception as exc:  # pragma: no cover - retry logic tested via batch splitter
            last_exc = exc
            if not _is_deadlock_error(exc) or attempt == NEO4J_REL_SINGLE_RETRIES - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise last_exc or RuntimeError("single relationship sync failed")


def _sync_relationships_serially(driver: Driver, rel_type: str, rels: List[Dict[str, Any]]) -> int:
    synced = 0
    for rel in rels:
        synced += _run_single_relationship(driver, rel_type, rel)
    return synced


def _sync_relationship_chunk(driver: Driver, rel_type: str, rels: List[Dict[str, Any]]) -> int:
    if not rels:
        return 0
    try:
        return _run_relationship_batch(driver, rel_type, rels)
    except Exception as exc:
        if not _is_deadlock_error(exc):
            raise
        if len(rels) == 1:
            logger.warning("Deadlock on single %s relationship; retrying row write", rel_type)
            return _run_single_relationship(driver, rel_type, rels[0])
        logger.warning(
            "Deadlock syncing %s chunk of %s rows; falling back to serial writes",
            rel_type,
            len(rels),
        )
        return _sync_relationships_serially(driver, rel_type, rels)


def close_driver() -> None:
    """Close the global Neo4j driver instance."""
    global _driver
    with _driver_lock:
        if _driver is not None:
            _driver.close()
            _driver = None
            logger.info("Neo4j driver closed")


@contextmanager
def get_neo4j_session(driver: Optional[Driver] = None) -> Session:
    """Context manager for Neo4j sessions."""
    active_driver = driver or get_neo4j_driver()
    if active_driver is None:
        raise RuntimeError("Neo4j driver not initialized")
    session = active_driver.session(**_neo4j_session_kwargs())
    try:
        yield session
    finally:
        session.close()


def sync_entities_to_neo4j(entities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Sync entities from PostgreSQL to Neo4j using UNWIND for batch efficiency.

    Args:
        entities: List of entity dicts from kg_entities table.
                 Expected keys: id, canonical_name, entity_type, aliases, identifiers,
                               country, sources, confidence, risk_level, sanctions_exposure,
                               created_at

    Returns:
        Dict with keys: synced_count, failed_count, duration_ms
    """
    if not entities:
        return {"synced_count": 0, "failed_count": 0, "duration_ms": 0}

    driver = get_neo4j_driver()
    if driver is None:
        logger.warning("Neo4j not available, skipping entity sync")
        return {"synced_count": 0, "failed_count": 0, "duration_ms": 0}

    start_time = time.time()
    synced = 0
    failed = 0

    try:
        import json as _json

        def _flatten_for_neo4j(value):
            """Serialize dicts/nested structures to JSON strings for Neo4j property storage."""
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                return _json.dumps(value, default=str)
            return str(value)

        with get_neo4j_session(driver) as session:
            # Normalize entities: flatten complex props, assign labels
            label_map = {
                "government_agency": "GovernmentAgency",
                "court_case": "CourtCase",
                "sanctions_list": "SanctionsList",
                "sanctions_entry": "SanctionsEntry",
                "trade_show_event": "TradeShowEvent",
                "export_control": "ExportControl",
                "holding_company": "HoldingCompany",
                "telecom_provider": "TelecomProvider",
                "shipment_route": "ShipmentRoute",
            }

            normalized_entities = []
            for entity in entities:
                entity_type = (entity.get("entity_type") or "").lower()
                label = label_map.get(
                    entity_type,
                    "".join(part.capitalize() for part in entity_type.split("_")) or "Entity",
                )

                # Extract flat alias list for Neo4j array property
                raw_aliases = entity.get("aliases", [])
                if isinstance(raw_aliases, str):
                    try:
                        raw_aliases = _json.loads(raw_aliases)
                    except (ValueError, TypeError):
                        raw_aliases = []
                alias_list = raw_aliases if isinstance(raw_aliases, list) else []

                normalized = {
                    "id": entity.get("id", ""),
                    "canonical_name": entity.get("canonical_name", ""),
                    "entity_type": entity_type,
                    "label": label,
                    "aliases": [str(a) for a in alias_list if isinstance(a, str)],
                    "identifiers_json": _flatten_for_neo4j(entity.get("identifiers")),
                    "country": entity.get("country", ""),
                    "sources_json": _flatten_for_neo4j(entity.get("sources")),
                    "confidence": float(entity.get("confidence", 0) or 0),
                    "risk_level": entity.get("risk_level", ""),
                    "sanctions_exposure": float(entity.get("sanctions_exposure", 0) or 0),
                    "created_at": str(entity.get("created_at", "")),
                }
                normalized_entities.append(normalized)

            # Batch by label type for efficient typed MERGE (no APOC needed)
            from collections import defaultdict
            by_label = defaultdict(list)
            for n in normalized_entities:
                by_label[n["label"]].append(n)

            total_synced = 0
            for label, batch in by_label.items():
                cypher = f"""
                UNWIND $entities AS entity
                MERGE (e:Entity {{id: entity.id}})
                SET e:{label},
                    e.canonical_name = entity.canonical_name,
                    e.entity_type = entity.entity_type,
                    e.aliases = entity.aliases,
                    e.identifiers_json = entity.identifiers_json,
                    e.country = entity.country,
                    e.sources_json = entity.sources_json,
                    e.confidence = entity.confidence,
                    e.risk_level = entity.risk_level,
                    e.sanctions_exposure = entity.sanctions_exposure,
                    e.created_at = entity.created_at,
                    e.updated_at = toString(datetime())
                RETURN count(e) as count
                """
                for start in range(0, len(batch), NEO4J_ENTITY_BATCH_SIZE):
                    entity_chunk = batch[start : start + NEO4J_ENTITY_BATCH_SIZE]
                    result = session.run(cypher, entities=entity_chunk)
                    record = result.single()
                    total_synced += record["count"] if record else len(entity_chunk)

            synced = total_synced

    except Exception as e:
        logger.error(f"Error syncing entities to Neo4j: {e}")
        failed = len(entities)
        synced = 0

    duration_ms = (time.time() - start_time) * 1000
    logger.info(f"Entity sync: {synced} synced, {failed} failed ({duration_ms:.0f}ms)")

    return {"synced_count": synced, "failed_count": failed, "duration_ms": duration_ms}


def sync_relationships_to_neo4j(relationships: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Sync relationships from PostgreSQL to Neo4j using UNWIND for batch efficiency.

    Args:
        relationships: List of relationship dicts from kg_relationships table.
                      Expected keys: id, source_entity_id, target_entity_id, rel_type,
                                    confidence, data_source, evidence, created_at

    Returns:
        Dict with keys: synced_count, failed_count, duration_ms
    """
    if not relationships:
        return {"synced_count": 0, "failed_count": 0, "duration_ms": 0}

    driver = get_neo4j_driver()
    if driver is None:
        logger.warning("Neo4j not available, skipping relationship sync")
        return {"synced_count": 0, "failed_count": 0, "duration_ms": 0}

    start_time = time.time()
    synced = 0
    failed = 0

    try:
        import json as _json
        from collections import defaultdict

        # Group relationships by type for static Cypher (no APOC needed)
        by_type = defaultdict(list)
        for rel in relationships:
            rel_type = (rel.get("rel_type") or "").upper().replace(" ", "_")
            if not rel_type:
                rel_type = "RELATED_TO"
            evidence = rel.get("evidence", "")
            if isinstance(evidence, (dict, list)):
                evidence = _json.dumps(evidence, default=str)
            rel_id = rel.get("id")
            rel_key = str(rel_id) if rel_id is not None else "|".join(
                [
                    str(rel.get("source_entity_id", "")),
                    str(rel.get("target_entity_id", "")),
                    str(rel.get("rel_type", "")),
                    str(rel.get("data_source", "")),
                    str(evidence or ""),
                    str(rel.get("created_at", "")),
                ]
            )
            by_type[rel_type].append({
                "kg_id": rel_key,
                "source_entity_id": rel.get("source_entity_id", ""),
                "target_entity_id": rel.get("target_entity_id", ""),
                "rel_type": str(rel.get("rel_type", "")),
                "confidence": float(rel.get("confidence", 0) or 0),
                "data_source": str(rel.get("data_source", "")),
                "evidence": str(evidence or ""),
                "created_at": str(rel.get("created_at", "")),
            })

        total_synced = 0
        for rel_type, batch in by_type.items():
            ordered_batch = sorted(
                batch,
                key=lambda rel: (
                    rel["source_entity_id"],
                    rel["target_entity_id"],
                    rel["kg_id"],
                ),
            )
            batch_size = _relationship_batch_size(rel_type)
            for start in range(0, len(ordered_batch), batch_size):
                rel_chunk = ordered_batch[start : start + batch_size]
                total_synced += _sync_relationship_chunk(driver, rel_type, rel_chunk)

        synced = total_synced

    except Exception as e:
        logger.error(f"Error syncing relationships to Neo4j: {e}")
        failed = len(relationships)
        synced = 0

    duration_ms = (time.time() - start_time) * 1000
    logger.info(f"Relationship sync: {synced} synced, {failed} failed ({duration_ms:.0f}ms)")

    return {"synced_count": synced, "failed_count": failed, "duration_ms": duration_ms}


def clear_neo4j_relationships() -> Dict[str, Any]:
    """
    Remove all mirrored relationships before a provenance-preserving full rebuild.
    """
    driver = get_neo4j_driver()
    if driver is None:
        logger.warning("Neo4j not available, skipping relationship clear")
        return {"deleted_count": 0, "duration_ms": 0}

    start_time = time.time()
    deleted_count = 0
    try:
        with get_neo4j_session(driver) as session:
            result = session.run(
                """
                MATCH ()-[r]->()
                WITH count(r) AS existing_count
                MATCH ()-[r]->()
                DELETE r
                RETURN existing_count
                """
            )
            record = result.single()
            deleted_count = int((record or {}).get("existing_count") or 0)
    except Exception as e:
        logger.error(f"Error clearing Neo4j relationships: {e}")
        return {"deleted_count": 0, "duration_ms": (time.time() - start_time) * 1000, "error": str(e)}

    duration_ms = (time.time() - start_time) * 1000
    logger.info(f"Cleared {deleted_count} Neo4j relationships ({duration_ms:.0f}ms)")
    return {"deleted_count": deleted_count, "duration_ms": duration_ms}


def full_sync_from_postgres() -> Dict[str, Any]:
    """
    Full sync: Read all entities and relationships from PostgreSQL, sync to Neo4j.

    Returns:
        Dict with keys: entities_synced, relationships_synced, duration_ms
    """
    start_time = time.time()
    entities_synced = 0
    relationships_synced = 0
    error: str | None = None

    try:
        # Read entities from the SQLite knowledge graph database.
        with get_kg_conn() as conn:
            entity_rows = conn.execute("SELECT * FROM kg_entities").fetchall()
            entities = [dict(row) for row in entity_rows]

            rel_rows = conn.execute("SELECT * FROM kg_relationships").fetchall()
            relationships = [dict(row) for row in rel_rows]

        logger.info(f"Read {len(entities)} entities and {len(relationships)} relationships from PostgreSQL")

        # Sync to Neo4j
        entity_result = sync_entities_to_neo4j(entities)
        entities_synced = entity_result["synced_count"]

        clear_neo4j_relationships()
        rel_result = sync_relationships_to_neo4j(relationships)
        relationships_synced = rel_result["synced_count"]

    except Exception as e:
        logger.error(f"Error during full sync: {e}", exc_info=True)
        error = str(e)

    duration_ms = (time.time() - start_time) * 1000
    logger.info(f"Full sync complete: {entities_synced} entities, {relationships_synced} relationships ({duration_ms:.0f}ms)")

    return {
        "status": "failed" if error else "success",
        "entities_synced": entities_synced,
        "relationships_synced": relationships_synced,
        "duration_ms": duration_ms,
        "error": error,
    }


def incremental_sync(since_timestamp: str) -> Dict[str, Any]:
    """
    Incremental sync: Only sync entities/relationships created after timestamp.

    Args:
        since_timestamp: ISO format timestamp string (e.g., '2026-03-25T10:00:00')

    Returns:
        Dict with keys: entities_synced, relationships_synced, duration_ms
    """
    start_time = time.time()
    entities_synced = 0
    relationships_synced = 0
    error: str | None = None

    try:
        # Read recent entities from the SQLite knowledge graph database.
        with get_kg_conn() as conn:
            entity_rows = conn.execute(
                "SELECT * FROM kg_entities WHERE created_at > ?",
                (since_timestamp,),
            ).fetchall()
            entities = [dict(row) for row in entity_rows]

            rel_rows = conn.execute(
                "SELECT * FROM kg_relationships WHERE created_at > ?",
                (since_timestamp,),
            ).fetchall()
            relationships = [dict(row) for row in rel_rows]

        logger.info(f"Incremental sync since {since_timestamp}: {len(entities)} entities, {len(relationships)} relationships")

        # Sync to Neo4j
        entity_result = sync_entities_to_neo4j(entities)
        entities_synced = entity_result["synced_count"]

        rel_result = sync_relationships_to_neo4j(relationships)
        relationships_synced = rel_result["synced_count"]

    except Exception as e:
        logger.error(f"Error during incremental sync: {e}")
        error = str(e)

    duration_ms = (time.time() - start_time) * 1000
    logger.info(f"Incremental sync complete: {entities_synced} entities, {relationships_synced} relationships ({duration_ms:.0f}ms)")

    return {
        "status": "failed" if error else "success",
        "entities_synced": entities_synced,
        "relationships_synced": relationships_synced,
        "duration_ms": duration_ms,
        "error": error,
    }


def get_entity_network_neo4j(entity_id: str, depth: int = 2) -> Optional[Dict[str, Any]]:
    """
    Get entity network using variable-length path traversal.

    Args:
        entity_id: The entity ID to get network for
        depth: Max relationship depth (default 2)

    Returns:
        Dict with keys: entities, relationships, entity_count, relationship_count
        Returns None if Neo4j unavailable.
    """
    driver = get_neo4j_driver()
    if driver is None:
        logger.warning("Neo4j not available, cannot get entity network")
        return None

    try:
        with get_neo4j_session(driver) as session:
            # Step 1: Find all nodes within `depth` hops
            node_cypher = f"""
            MATCH path = (center:Entity {{id: $entity_id}})-[*1..{depth}]-(connected:Entity)
            UNWIND nodes(path) AS n
            WITH DISTINCT n
            RETURN collect(n) AS nodes
            """

            node_result = session.run(node_cypher, entity_id=entity_id)
            node_record = node_result.single()

            if not node_record or not node_record["nodes"]:
                logger.info(f"No network found for entity {entity_id}")
                return {
                    "entities": {},
                    "relationships": [],
                    "entity_count": 0,
                    "relationship_count": 0,
                }

            # Collect all node IDs
            entities = {}
            node_ids = []
            for node in node_record["nodes"]:
                nid = node.get("id", "")
                if nid:
                    node_ids.append(nid)
                    entities[nid] = {
                        "id": nid,
                        "canonical_name": node.get("canonical_name", ""),
                        "entity_type": node.get("entity_type", ""),
                        "confidence": node.get("confidence"),
                        "risk_level": node.get("risk_level"),
                        "sanctions_exposure": node.get("sanctions_exposure"),
                    }

            # Step 2: Find all relationships between these nodes
            rel_cypher = """
            MATCH (a:Entity)-[r]->(b:Entity)
            WHERE a.id IN $node_ids AND b.id IN $node_ids
            RETURN a.id AS source, b.id AS target, type(r) AS rel_type,
                   r.confidence AS confidence
            """

            rel_result = session.run(rel_cypher, node_ids=node_ids)
            relationships = []
            for record in rel_result:
                relationships.append({
                    "source": record["source"],
                    "target": record["target"],
                    "type": record["rel_type"],
                    "confidence": record.get("confidence"),
                })

            return {
                "entities": entities,
                "relationships": relationships,
                "entity_count": len(entities),
                "relationship_count": len(relationships),
            }

    except Exception as e:
        logger.error(f"Error getting entity network for {entity_id}: {e}")
        return None


def find_shortest_path_neo4j(
    source_id: str, target_id: str, max_depth: int = 6
) -> Optional[List[Dict[str, Any]]]:
    """
    Find shortest path between two entities.

    Args:
        source_id: Source entity ID
        target_id: Target entity ID
        max_depth: Maximum path length (default 6)

    Returns:
        List of dicts with path nodes and relationships.
        Returns None if Neo4j unavailable or no path found.
    """
    driver = get_neo4j_driver()
    if driver is None:
        logger.warning("Neo4j not available, cannot find shortest path")
        return None

    try:
        with get_neo4j_session(driver) as session:
            cypher = f"""
            MATCH (source:Entity {{id: $source_id}})
            MATCH (target:Entity {{id: $target_id}})
            MATCH path = shortestPath((source)-[*1..{max_depth}]-(target))
            RETURN [node in nodes(path) | {{id: node.id, name: node.canonical_name, type: node.entity_type}}] as nodes,
                   [rel in relationships(path) | {{type: type(rel), confidence: rel.confidence}}] as rels
            """

            result = session.run(cypher, source_id=source_id, target_id=target_id)
            record = result.single()

            if not record:
                logger.info(f"No path found between {source_id} and {target_id}")
                return None

            return {
                "nodes": record.get("nodes", []),
                "relationships": record.get("rels", []),
            }

    except Exception as e:
        logger.error(f"Error finding shortest path from {source_id} to {target_id}: {e}")
        return None


def find_shared_connections_neo4j(entity_id_a: str, entity_id_b: str) -> Optional[List[Dict[str, Any]]]:
    """
    Find entities connected to both A and B within 3 hops.

    Args:
        entity_id_a: First entity ID
        entity_id_b: Second entity ID

    Returns:
        List of shared connection entities.
        Returns None if Neo4j unavailable.
    """
    driver = get_neo4j_driver()
    if driver is None:
        logger.warning("Neo4j not available, cannot find shared connections")
        return None

    try:
        with get_neo4j_session(driver) as session:
            cypher = """
            MATCH (a:Entity {id: $entity_id_a})-[*1..3]-(shared:Entity)-[*1..3]-(b:Entity {id: $entity_id_b})
            WITH DISTINCT shared
            RETURN {
                id: shared.id,
                canonical_name: shared.canonical_name,
                entity_type: shared.entity_type,
                confidence: shared.confidence,
                risk_level: shared.risk_level
            } as connection
            """

            result = session.run(cypher, entity_id_a=entity_id_a, entity_id_b=entity_id_b)
            connections = [record["connection"] for record in result]

            logger.info(f"Found {len(connections)} shared connections between {entity_id_a} and {entity_id_b}")
            return connections

    except Exception as e:
        logger.error(f"Error finding shared connections: {e}")
        return None


def compute_network_risk_neo4j(entity_id: str, max_hops: int = 2) -> Optional[Dict[str, Any]]:
    """
    Compute network risk propagation using weighted relationship traversal.

    Args:
        entity_id: Entity to compute risk for
        max_hops: Maximum hops to traverse (default 2)

    Returns:
        Dict with keys: entity_id, base_risk, network_risk, risk_score, connected_risks, duration_ms
        Returns None if Neo4j unavailable.
    """
    driver = get_neo4j_driver()
    if driver is None:
        logger.warning("Neo4j not available, cannot compute network risk")
        return None

    start_time = time.time()

    try:
        with get_neo4j_session(driver) as session:
            # Get entity with initial risk
            cypher_entity = """
            MATCH (e:Entity {id: $entity_id})
            RETURN e.risk_level as risk_level, e.sanctions_exposure as sanctions_exposure
            """

            result = session.run(cypher_entity, entity_id=entity_id)
            entity_record = result.single()

            if not entity_record:
                logger.warning(f"Entity {entity_id} not found")
                return None

            base_risk = entity_record.get("risk_level", "UNKNOWN")

            # Get connected entities with relationship weights
            cypher_network = f"""
            MATCH (source:Entity {{id: $entity_id}})-[rel*1..{max_hops}]-(connected:Entity)
            RETURN connected.id as connected_id,
                   connected.canonical_name as connected_name,
                   connected.risk_level as risk_level,
                   connected.sanctions_exposure as sanctions_exposure,
                   [r in rel | type(r)] as rel_types
            """

            result = session.run(cypher_network, entity_id=entity_id)
            connected_risks = []
            total_propagated_risk = 0.0

            for record in result:
                rel_types = record.get("rel_types", [])
                # Calculate weighted risk using relationship weights
                weight = 1.0
                for rel_type in rel_types:
                    rel_type_lower = rel_type.lower().replace("_", "_")
                    weight *= RELATIONSHIP_WEIGHTS.get(rel_type_lower, 0.3)

                connected_risks.append({
                    "entity_id": record["connected_id"],
                    "entity_name": record["connected_name"],
                    "risk_level": record["risk_level"],
                    "relationship_types": rel_types,
                    "propagation_weight": weight,
                })
                total_propagated_risk += weight

            # Compute final risk score (0-1)
            risk_score = min(1.0, total_propagated_risk)

            duration_ms = (time.time() - start_time) * 1000

            return {
                "entity_id": entity_id,
                "base_risk": base_risk,
                "network_risk": risk_score,
                "risk_score": risk_score,
                "connected_risks": connected_risks,
                "duration_ms": duration_ms,
            }

    except Exception as e:
        logger.error(f"Error computing network risk for {entity_id}: {e}")
        return None


def compute_entity_centrality_neo4j(entity_id: str) -> Optional[Dict[str, Any]]:
    """
    Compute centrality metrics for an entity using native Cypher (no GDS required).

    Returns degree centrality, betweenness approximation, and influence score.
    """
    driver = get_neo4j_driver()
    if driver is None:
        return None

    try:
        with get_neo4j_session(driver) as session:
            cypher = """
            MATCH (e:Entity {id: $entity_id})
            OPTIONAL MATCH (e)-[r]-(neighbor:Entity)
            WITH e, count(DISTINCT neighbor) AS degree,
                 count(r) AS total_rels,
                 collect(DISTINCT neighbor.entity_type) AS neighbor_types,
                 collect(DISTINCT type(r)) AS rel_types_used
            OPTIONAL MATCH (e)-[]-(n1:Entity)-[]-(n2:Entity)
            WHERE n1 <> e AND n2 <> e AND n1 <> n2
            AND NOT (e)-[]-(n2)
            WITH e, degree, total_rels, neighbor_types, rel_types_used,
                 count(DISTINCT n2) AS bridged_entities
            RETURN degree, total_rels, neighbor_types, rel_types_used,
                   bridged_entities,
                   e.risk_level AS risk_level,
                   e.entity_type AS entity_type,
                   e.canonical_name AS canonical_name
            """

            result = session.run(cypher, entity_id=entity_id)
            record = result.single()

            if not record:
                return None

            degree = record["degree"] or 0
            bridged = record["bridged_entities"] or 0

            # Influence score: weighted combination of degree + bridging power
            influence = min(1.0, (degree * 0.4 + bridged * 0.6) / 50.0)

            return {
                "entity_id": entity_id,
                "canonical_name": record["canonical_name"],
                "entity_type": record["entity_type"],
                "degree_centrality": degree,
                "total_relationships": record["total_rels"] or 0,
                "bridged_entities": bridged,
                "neighbor_types": record["neighbor_types"] or [],
                "relationship_types_used": record["rel_types_used"] or [],
                "influence_score": round(influence, 3),
                "risk_level": record["risk_level"],
            }

    except Exception as e:
        logger.error(f"Error computing centrality for {entity_id}: {e}")
        return None


def get_top_central_entities_neo4j(limit: int = 20) -> Optional[List[Dict[str, Any]]]:
    """
    Get the most connected entities across the entire graph.
    Useful for identifying key players and network hubs.
    """
    driver = get_neo4j_driver()
    if driver is None:
        return None

    try:
        with get_neo4j_session(driver) as session:
            cypher = """
            MATCH (e:Entity)-[r]-(neighbor:Entity)
            WITH e, count(DISTINCT neighbor) AS degree, count(r) AS total_rels
            ORDER BY degree DESC
            LIMIT $limit
            RETURN e.id AS id, e.canonical_name AS name, e.entity_type AS type,
                   e.risk_level AS risk_level, degree, total_rels
            """

            result = session.run(cypher, limit=limit)
            entities = []
            for record in result:
                entities.append({
                    "id": record["id"],
                    "name": record["name"],
                    "entity_type": record["type"],
                    "risk_level": record["risk_level"],
                    "degree": record["degree"],
                    "total_relationships": record["total_rels"],
                })

            return entities

    except Exception as e:
        logger.error(f"Error getting top central entities: {e}")
        return None


def get_entity_neighbors_neo4j(entity_id: str, rel_types: Optional[List[str]] = None) -> Optional[List[Dict[str, Any]]]:
    """
    Get immediate neighbors of an entity for "expand node" in frontend.

    Args:
        entity_id: Entity ID to get neighbors for
        rel_types: Optional list of relationship types to filter by

    Returns:
        List of neighbor entities with relationship info.
        Returns None if Neo4j unavailable.
    """
    driver = get_neo4j_driver()
    if driver is None:
        logger.warning("Neo4j not available, cannot get entity neighbors")
        return None

    try:
        with get_neo4j_session(driver) as session:
            if rel_types:
                # Build Cypher with relationship type filter
                rel_types_upper = [rt.upper().replace(" ", "_") for rt in rel_types]
                rel_pattern = "|".join(rel_types_upper)
                cypher = f"""
                MATCH (center:Entity {{id: $entity_id}})-[rel:{rel_pattern}]-(neighbor:Entity)
                RETURN {{
                    neighbor_id: neighbor.id,
                    neighbor_name: neighbor.canonical_name,
                    entity_type: neighbor.entity_type,
                    rel_type: type(rel),
                    rel_confidence: rel.confidence
                }} as neighbor
                """
            else:
                cypher = """
                MATCH (center:Entity {id: $entity_id})-[rel]-(neighbor:Entity)
                RETURN {
                    neighbor_id: neighbor.id,
                    neighbor_name: neighbor.canonical_name,
                    entity_type: neighbor.entity_type,
                    rel_type: type(rel),
                    rel_confidence: rel.confidence
                } as neighbor
                """

            result = session.run(cypher, entity_id=entity_id)
            neighbors = [record["neighbor"] for record in result]

            logger.info(f"Found {len(neighbors)} neighbors for entity {entity_id}")
            return neighbors

    except Exception as e:
        logger.error(f"Error getting neighbors for {entity_id}: {e}")
        return None


def get_graph_stats_neo4j() -> Optional[Dict[str, Any]]:
    """
    Get overall graph statistics: node counts, relationship counts, type distributions.

    Returns:
        Dict with keys: node_count, relationship_count, node_types, relationship_types
        Returns None if Neo4j unavailable.
    """
    driver = get_neo4j_driver()
    if driver is None:
        logger.warning("Neo4j not available, cannot get graph stats")
        return None

    try:
        with get_neo4j_session(driver) as session:
            cypher_nodes = """
            MATCH (n:Entity)
            WITH CASE
                WHEN size([label IN labels(n) WHERE label <> 'Entity']) > 0
                THEN [label IN labels(n) WHERE label <> 'Entity'][0]
                ELSE 'Entity'
            END AS label
            RETURN label, count(*) as count
            """

            cypher_rels = """
            MATCH ()-[r]->()
            RETURN type(r) as rel_type, count(r) as count
            """

            cypher_total = """
            MATCH (n:Entity)
            RETURN count(n) as total_nodes
            """

            result_nodes = session.run(cypher_nodes)
            node_types = {record["label"]: record["count"] for record in result_nodes}

            result_rels = session.run(cypher_rels)
            relationship_types = {record["rel_type"]: record["count"] for record in result_rels}

            result_total = session.run(cypher_total)
            total_nodes = result_total.single()["total_nodes"]

            return {
                "node_count": total_nodes,
                "relationship_count": sum(relationship_types.values()),
                "node_types": node_types,
                "relationship_types": relationship_types,
            }

    except Exception as e:
        logger.error(f"Error getting graph stats: {e}")
        return None
