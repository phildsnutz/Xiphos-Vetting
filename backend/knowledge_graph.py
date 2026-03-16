"""
SQLite-based persistence layer for the entity resolution knowledge graph.

Stores resolved entities, relationships, and vendor links in a separate
database (knowledge_graph.db) using the same patterns as db.py.

No external dependencies beyond Python stdlib.
"""

import sqlite3
import json
import os
from datetime import datetime
from contextlib import contextmanager
from entity_resolution import ResolvedEntity


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

DEFAULT_KG_DB_PATH = os.path.join(os.path.dirname(__file__), "knowledge_graph.db")


def get_kg_db_path() -> str:
    """Get knowledge graph database path from environment or default."""
    return os.environ.get("XIPHOS_KG_DB_PATH", DEFAULT_KG_DB_PATH)


@contextmanager
def get_kg_conn():
    """Context manager for knowledge graph database connections with WAL mode."""
    conn = sqlite3.connect(get_kg_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_kg_db():
    """Create knowledge graph tables if they don't exist."""
    with get_kg_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS kg_entities (
                id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                aliases JSON NOT NULL DEFAULT '[]',
                identifiers JSON NOT NULL DEFAULT '{}',
                country TEXT,
                sources JSON NOT NULL DEFAULT '[]',
                confidence REAL NOT NULL DEFAULT 0.0,
                last_updated TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS kg_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_entity_id TEXT NOT NULL,
                target_entity_id TEXT NOT NULL,
                rel_type TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.7,
                data_source TEXT,
                evidence TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (source_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
                FOREIGN KEY (target_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS kg_entity_vendors (
                entity_id TEXT NOT NULL,
                vendor_id TEXT NOT NULL,
                linked_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (entity_id, vendor_id),
                FOREIGN KEY (entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_kg_entities_name
                ON kg_entities(canonical_name);
            CREATE INDEX IF NOT EXISTS idx_kg_entities_type
                ON kg_entities(entity_type);
            CREATE INDEX IF NOT EXISTS idx_kg_entities_country
                ON kg_entities(country);

            CREATE INDEX IF NOT EXISTS idx_kg_relationships_source
                ON kg_relationships(source_entity_id);
            CREATE INDEX IF NOT EXISTS idx_kg_relationships_target
                ON kg_relationships(target_entity_id);
            CREATE INDEX IF NOT EXISTS idx_kg_relationships_type
                ON kg_relationships(rel_type);

            CREATE INDEX IF NOT EXISTS idx_kg_entity_vendors_vendor
                ON kg_entity_vendors(vendor_id);
        """)


# ---------------------------------------------------------------------------
# Entity operations
# ---------------------------------------------------------------------------

def save_entity(entity: ResolvedEntity) -> str:
    """
    Save a resolved entity to the knowledge graph.
    Returns the entity ID.
    """
    with get_kg_conn() as conn:
        conn.execute("""
            INSERT INTO kg_entities
                (id, canonical_name, entity_type, aliases, identifiers, country,
                 sources, confidence, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                canonical_name=excluded.canonical_name,
                entity_type=excluded.entity_type,
                aliases=excluded.aliases,
                identifiers=excluded.identifiers,
                country=excluded.country,
                sources=excluded.sources,
                confidence=excluded.confidence,
                last_updated=excluded.last_updated
        """, (
            entity.id,
            entity.canonical_name,
            entity.entity_type,
            json.dumps(entity.aliases),
            json.dumps(entity.identifiers),
            entity.country,
            json.dumps(entity.sources),
            entity.confidence,
            entity.last_updated or datetime.utcnow().isoformat() + "Z",
        ))
    return entity.id


def get_entity(entity_id: str) -> ResolvedEntity | None:
    """Retrieve a resolved entity by ID."""
    with get_kg_conn() as conn:
        row = conn.execute(
            "SELECT * FROM kg_entities WHERE id = ?",
            (entity_id,)
        ).fetchone()

        if not row:
            return None

        # Fetch relationships
        rel_rows = conn.execute(
            "SELECT * FROM kg_relationships WHERE source_entity_id = ?",
            (entity_id,)
        ).fetchall()

        relationships = [dict(r) for r in rel_rows]

        return ResolvedEntity(
            id=row["id"],
            canonical_name=row["canonical_name"],
            entity_type=row["entity_type"],
            aliases=json.loads(row["aliases"]),
            identifiers=json.loads(row["identifiers"]),
            country=row["country"],
            relationships=relationships,
            sources=json.loads(row["sources"]),
            confidence=row["confidence"],
            last_updated=row["last_updated"],
        )


def find_entities_by_name(
    name: str,
    entity_type: str = "",
    threshold: float = 0.0
) -> list[ResolvedEntity]:
    """
    Find entities by name pattern (SQL LIKE).
    If threshold > 0, returns only entities with confidence >= threshold.
    """
    with get_kg_conn() as conn:
        query = "SELECT * FROM kg_entities WHERE canonical_name LIKE ?"
        params = [f"%{name}%"]

        if entity_type:
            query += " AND entity_type = ?"
            params.append(entity_type)

        if threshold > 0:
            query += " AND confidence >= ?"
            params.append(threshold)

        query += " ORDER BY confidence DESC"

        rows = conn.execute(query, params).fetchall()

        results = []
        for row in rows:
            rel_rows = conn.execute(
                "SELECT * FROM kg_relationships WHERE source_entity_id = ?",
                (row["id"],)
            ).fetchall()

            entity = ResolvedEntity(
                id=row["id"],
                canonical_name=row["canonical_name"],
                entity_type=row["entity_type"],
                aliases=json.loads(row["aliases"]),
                identifiers=json.loads(row["identifiers"]),
                country=row["country"],
                relationships=[dict(r) for r in rel_rows],
                sources=json.loads(row["sources"]),
                confidence=row["confidence"],
                last_updated=row["last_updated"],
            )
            results.append(entity)

        return results


# ---------------------------------------------------------------------------
# Relationship operations
# ---------------------------------------------------------------------------

def save_relationship(
    source_entity_id: str,
    target_entity_id: str,
    rel_type: str,
    confidence: float = 0.7,
    data_source: str = "",
    evidence: str = "",
) -> int:
    """
    Save a relationship between two entities.
    Returns the relationship ID.
    """
    with get_kg_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO kg_relationships
                (source_entity_id, target_entity_id, rel_type, confidence,
                 data_source, evidence)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            source_entity_id,
            target_entity_id,
            rel_type,
            confidence,
            data_source,
            evidence,
        ))
        return cursor.lastrowid


def get_entity_network(entity_id: str, depth: int = 2) -> dict:
    """
    Get the network around an entity (BFS traversal).
    Returns {entity_id, entities, relationships}.
    """
    if depth < 0:
        depth = 2

    with get_kg_conn() as conn:
        visited = set()
        queue = [(entity_id, 0)]
        all_entities = {}
        all_relationships = []

        while queue:
            current_id, current_depth = queue.pop(0)
            if current_id in visited or current_depth > depth:
                continue
            visited.add(current_id)

            # Get entity
            entity_row = conn.execute(
                "SELECT * FROM kg_entities WHERE id = ?",
                (current_id,)
            ).fetchone()

            if entity_row:
                all_entities[current_id] = {
                    "id": entity_row["id"],
                    "canonical_name": entity_row["canonical_name"],
                    "entity_type": entity_row["entity_type"],
                    "confidence": entity_row["confidence"],
                    "country": entity_row["country"],
                }

                # Get relationships
                rel_rows = conn.execute(
                    "SELECT * FROM kg_relationships WHERE source_entity_id = ?",
                    (current_id,)
                ).fetchall()

                for rel in rel_rows:
                    all_relationships.append({
                        "source_entity_id": rel["source_entity_id"],
                        "target_entity_id": rel["target_entity_id"],
                        "rel_type": rel["rel_type"],
                        "confidence": rel["confidence"],
                    })

                    target_id = rel["target_entity_id"]
                    if target_id not in visited and current_depth < depth:
                        queue.append((target_id, current_depth + 1))

        return {
            "root_entity_id": entity_id,
            "entity_count": len(all_entities),
            "entities": all_entities,
            "relationship_count": len(all_relationships),
            "relationships": all_relationships,
            "depth": depth,
        }


# ---------------------------------------------------------------------------
# Vendor-entity linking
# ---------------------------------------------------------------------------

def link_entity_to_vendor(entity_id: str, vendor_id: str) -> None:
    """Link a resolved entity to a vendor (for tracking enrichment)."""
    with get_kg_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO kg_entity_vendors (entity_id, vendor_id)
            VALUES (?, ?)
        """, (entity_id, vendor_id))


def get_vendor_entities(vendor_id: str) -> list[ResolvedEntity]:
    """Get all resolved entities linked to a vendor."""
    with get_kg_conn() as conn:
        entity_ids = conn.execute(
            "SELECT entity_id FROM kg_entity_vendors WHERE vendor_id = ?",
            (vendor_id,)
        ).fetchall()

        results = []
        for (eid,) in entity_ids:
            entity_row = conn.execute(
                "SELECT * FROM kg_entities WHERE id = ?",
                (eid,)
            ).fetchone()

            if entity_row:
                rel_rows = conn.execute(
                    "SELECT * FROM kg_relationships WHERE source_entity_id = ?",
                    (eid,)
                ).fetchall()

                entity = ResolvedEntity(
                    id=entity_row["id"],
                    canonical_name=entity_row["canonical_name"],
                    entity_type=entity_row["entity_type"],
                    aliases=json.loads(entity_row["aliases"]),
                    identifiers=json.loads(entity_row["identifiers"]),
                    country=entity_row["country"],
                    relationships=[dict(r) for r in rel_rows],
                    sources=json.loads(entity_row["sources"]),
                    confidence=entity_row["confidence"],
                    last_updated=entity_row["last_updated"],
                )
                results.append(entity)

        return results


def find_shared_connections(vendor_id_a: str, vendor_id_b: str) -> list[dict]:
    """
    Find hidden connections between two vendors.
    Returns entities and relationships that link them.
    """
    with get_kg_conn() as conn:
        # Get all entities for vendor A
        entities_a = conn.execute(
            "SELECT entity_id FROM kg_entity_vendors WHERE vendor_id = ?",
            (vendor_id_a,)
        ).fetchall()

        # Get all entities for vendor B
        entities_b = conn.execute(
            "SELECT entity_id FROM kg_entity_vendors WHERE vendor_id = ?",
            (vendor_id_b,)
        ).fetchall()

        entity_ids_a = set(e[0] for e in entities_a)
        entity_ids_b = set(e[0] for e in entities_b)

        # Find paths between A and B entities (max depth 3)
        shared = []

        for a_id in entity_ids_a:
            # BFS from a_id, looking for entities in entity_ids_b
            visited = set()
            queue = [(a_id, 0, [])]

            while queue:
                current_id, depth, path = queue.pop(0)
                if current_id in visited or depth > 3:
                    continue
                visited.add(current_id)

                if current_id in entity_ids_b and current_id != a_id:
                    # Found a path from A to B
                    rel_rows = conn.execute(
                        "SELECT * FROM kg_relationships WHERE source_entity_id IN ({})".format(
                            ",".join("?" * len(path + [current_id]))
                        ),
                        path + [current_id],
                    ).fetchall()

                    shared.append({
                        "vendor_a": vendor_id_a,
                        "vendor_b": vendor_id_b,
                        "path_start": a_id,
                        "path_end": current_id,
                        "path_length": depth,
                        "relationships": [dict(r) for r in rel_rows],
                    })

                # Get outgoing edges
                rel_rows = conn.execute(
                    "SELECT target_entity_id FROM kg_relationships WHERE source_entity_id = ?",
                    (current_id,)
                ).fetchall()

                for (target_id,) in rel_rows:
                    if target_id not in visited and depth < 3:
                        queue.append((target_id, depth + 1, path + [current_id]))

        return shared


# ---------------------------------------------------------------------------
# Statistics and utilities
# ---------------------------------------------------------------------------

def get_kg_stats() -> dict:
    """Get knowledge graph statistics."""
    with get_kg_conn() as conn:
        entity_count = conn.execute("SELECT COUNT(*) FROM kg_entities").fetchone()[0]
        rel_count = conn.execute("SELECT COUNT(*) FROM kg_relationships").fetchone()[0]
        vendor_links = conn.execute("SELECT COUNT(DISTINCT vendor_id) FROM kg_entity_vendors").fetchone()[0]

        # Entity type distribution
        type_dist = {}
        rows = conn.execute("SELECT entity_type, COUNT(*) as cnt FROM kg_entities GROUP BY entity_type").fetchall()
        for r in rows:
            type_dist[r["entity_type"]] = r["cnt"]

        # Relationship type distribution
        rel_dist = {}
        rows = conn.execute("SELECT rel_type, COUNT(*) as cnt FROM kg_relationships GROUP BY rel_type").fetchall()
        for r in rows:
            rel_dist[r["rel_type"]] = r["cnt"]

        # Average confidence
        avg_conf = conn.execute("SELECT AVG(confidence) FROM kg_entities").fetchone()[0] or 0.0

        return {
            "entity_count": entity_count,
            "relationship_count": rel_count,
            "linked_vendors": vendor_links,
            "entity_type_distribution": type_dist,
            "relationship_type_distribution": rel_dist,
            "average_entity_confidence": round(avg_conf, 3),
        }


def clear_vendor_links(vendor_id: str) -> None:
    """Remove all entity-vendor links for a vendor (e.g., on re-enrichment)."""
    with get_kg_conn() as conn:
        conn.execute(
            "DELETE FROM kg_entity_vendors WHERE vendor_id = ?",
            (vendor_id,)
        )


def delete_entity(entity_id: str) -> bool:
    """Delete an entity and its relationships."""
    with get_kg_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM kg_entities WHERE id = ?",
            (entity_id,)
        )
        return cursor.rowcount > 0


def export_graph(limit_entities: int = 10000) -> dict:
    """
    Export the knowledge graph as a JSON-serializable dict.
    Useful for visualization or external analysis.
    """
    with get_kg_conn() as conn:
        # Get entities
        entity_rows = conn.execute(
            "SELECT * FROM kg_entities LIMIT ?",
            (limit_entities,)
        ).fetchall()

        entities = {}
        entity_ids = set()

        for row in entity_rows:
            entities[row["id"]] = {
                "id": row["id"],
                "canonical_name": row["canonical_name"],
                "entity_type": row["entity_type"],
                "aliases": json.loads(row["aliases"]),
                "identifiers": json.loads(row["identifiers"]),
                "country": row["country"],
                "sources": json.loads(row["sources"]),
                "confidence": row["confidence"],
                "last_updated": row["last_updated"],
            }
            entity_ids.add(row["id"])

        # Get relationships
        rel_rows = conn.execute(
            "SELECT * FROM kg_relationships WHERE source_entity_id IN ({})".format(
                ",".join("?" * len(entity_ids))
            ) if entity_ids else "SELECT * FROM kg_relationships LIMIT 10000",
            list(entity_ids) if entity_ids else [],
        ).fetchall()

        relationships = []
        for row in rel_rows:
            relationships.append({
                "source_entity_id": row["source_entity_id"],
                "target_entity_id": row["target_entity_id"],
                "rel_type": row["rel_type"],
                "confidence": row["confidence"],
                "data_source": row["data_source"],
                "evidence": row["evidence"],
            })

        return {
            "export_timestamp": datetime.utcnow().isoformat() + "Z",
            "entity_count": len(entities),
            "relationship_count": len(relationships),
            "entities": entities,
            "relationships": relationships,
        }
