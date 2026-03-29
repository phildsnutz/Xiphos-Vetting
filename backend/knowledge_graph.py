"""
SQLite-based persistence layer for the entity resolution knowledge graph.

Stores resolved entities, relationships, and vendor links in a separate
database (knowledge_graph.db) using the same patterns as db.py.

No external dependencies beyond Python stdlib.
"""

import sqlite3
import json
import hashlib
from datetime import datetime
from contextlib import contextmanager
from entity_resolution import ResolvedEntity
from runtime_paths import get_kg_db_path as resolve_kg_db_path


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def get_kg_db_path() -> str:
    """Get knowledge graph database path from environment or default."""
    return resolve_kg_db_path()


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _json_dumps(value, fallback):
    if value in (None, ""):
        return json.dumps(fallback)
    return json.dumps(value)


def _json_loads(value, fallback):
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _stable_hash(*parts: str, prefix: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:20]}"


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
                risk_level TEXT NOT NULL DEFAULT 'unknown',
                sanctions_exposure REAL NOT NULL DEFAULT 0.0,
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

            CREATE TABLE IF NOT EXISTS kg_asserting_agents (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                agent_type TEXT NOT NULL DEFAULT 'system',
                metadata JSON NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS kg_source_activities (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                activity_type TEXT NOT NULL DEFAULT 'observation',
                occurred_at TEXT,
                metadata JSON NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS kg_claims (
                id TEXT PRIMARY KEY,
                claim_key TEXT NOT NULL UNIQUE,
                source_entity_id TEXT NOT NULL,
                target_entity_id TEXT,
                rel_type TEXT NOT NULL,
                claim_type TEXT NOT NULL DEFAULT 'relationship',
                claim_value TEXT,
                confidence REAL NOT NULL DEFAULT 0.7,
                contradiction_state TEXT NOT NULL DEFAULT 'unreviewed',
                validity_start TEXT,
                validity_end TEXT,
                observed_at TEXT,
                first_observed_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_observed_at TEXT NOT NULL DEFAULT (datetime('now')),
                data_source TEXT,
                vendor_id TEXT,
                source_activity_id TEXT,
                asserting_agent_id TEXT,
                structured_fields JSON NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (source_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
                FOREIGN KEY (target_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
                FOREIGN KEY (source_activity_id) REFERENCES kg_source_activities(id) ON DELETE SET NULL,
                FOREIGN KEY (asserting_agent_id) REFERENCES kg_asserting_agents(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS kg_evidence (
                id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL,
                source TEXT,
                title TEXT,
                url TEXT,
                artifact_ref TEXT,
                snippet TEXT,
                raw_data JSON NOT NULL DEFAULT '{}',
                structured_fields JSON NOT NULL DEFAULT '{}',
                source_class TEXT,
                authority_level TEXT,
                access_model TEXT,
                observed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (claim_id) REFERENCES kg_claims(id) ON DELETE CASCADE
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
            CREATE INDEX IF NOT EXISTS idx_kg_claims_source
                ON kg_claims(source_entity_id);
            CREATE INDEX IF NOT EXISTS idx_kg_claims_target
                ON kg_claims(target_entity_id);
            CREATE INDEX IF NOT EXISTS idx_kg_claims_rel_type
                ON kg_claims(rel_type);
            CREATE INDEX IF NOT EXISTS idx_kg_claims_vendor
                ON kg_claims(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_kg_evidence_claim
                ON kg_evidence(claim_id);
        """)

        # Migrate existing databases: add risk_level and sanctions_exposure columns
        # if they don't already exist (safe to run repeatedly).
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(kg_entities)").fetchall()}
        if "risk_level" not in existing_cols:
            conn.execute("ALTER TABLE kg_entities ADD COLUMN risk_level TEXT NOT NULL DEFAULT 'unknown'")
        if "sanctions_exposure" not in existing_cols:
            conn.execute("ALTER TABLE kg_entities ADD COLUMN sanctions_exposure REAL NOT NULL DEFAULT 0.0")

        # Legacy graph databases can contain duplicate relationships or NULLs in the
        # uniqueness columns. Normalize and collapse them before enforcing the
        # unique index so existing graphs remain queryable after upgrade.
        conn.execute("UPDATE kg_relationships SET data_source = '' WHERE data_source IS NULL")
        conn.execute("UPDATE kg_relationships SET evidence = '' WHERE evidence IS NULL")
        conn.execute("""
            DELETE FROM kg_relationships
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM kg_relationships
                GROUP BY source_entity_id, target_entity_id, rel_type, data_source, evidence
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_relationships_unique
                ON kg_relationships(source_entity_id, target_entity_id, rel_type, data_source, evidence)
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_evidence_unique
                ON kg_evidence(claim_id, url, artifact_ref, snippet)
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
    *,
    observed_at: str = "",
    valid_from: str = "",
    valid_to: str = "",
    claim_value: str = "",
    contradiction_state: str = "unreviewed",
    source_activity: dict | None = None,
    asserting_agent: dict | None = None,
    artifact_ref: str = "",
    evidence_url: str = "",
    evidence_title: str = "",
    raw_data: dict | None = None,
    structured_fields: dict | None = None,
    source_class: str = "",
    authority_level: str = "",
    access_model: str = "",
    vendor_id: str = "",
) -> int:
    """
    Save a relationship between two entities.
    Returns the relationship ID.
    """
    data_source = data_source or ""
    evidence = evidence or ""
    now = _utc_now()
    structured_fields = structured_fields or {}
    raw_data = raw_data or {}
    with get_kg_conn() as conn:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO kg_relationships
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
        relationship_id = cursor.lastrowid or 0
        if not relationship_id:
            row = conn.execute(
                """
                SELECT id FROM kg_relationships
                WHERE source_entity_id = ? AND target_entity_id = ? AND rel_type = ?
                  AND data_source = ? AND evidence = ?
                """,
                (source_entity_id, target_entity_id, rel_type, data_source, evidence),
            ).fetchone()
            relationship_id = row["id"] if row else 0

        activity_payload = source_activity or {
            "source": data_source or "knowledge_graph",
            "activity_type": "relationship_observation",
            "occurred_at": observed_at or now,
            "metadata": {
                "rel_type": rel_type,
                "vendor_id": vendor_id,
            },
        }
        activity_source = activity_payload.get("source") or data_source or "knowledge_graph"
        activity_type = activity_payload.get("activity_type") or "relationship_observation"
        activity_occurred_at = activity_payload.get("occurred_at") or observed_at or now
        activity_metadata = activity_payload.get("metadata") or {}
        activity_id = activity_payload.get("id") or _stable_hash(
            activity_source,
            activity_type,
            activity_occurred_at,
            json.dumps(activity_metadata, sort_keys=True),
            prefix="activity",
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO kg_source_activities (id, source, activity_type, occurred_at, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                activity_id,
                activity_source,
                activity_type,
                activity_occurred_at,
                _json_dumps(activity_metadata, {}),
            ),
        )

        agent_payload = asserting_agent or {
            "label": data_source or "system",
            "agent_type": "connector" if data_source else "system",
            "metadata": {"source": data_source or "knowledge_graph"},
        }
        agent_label = agent_payload.get("label") or data_source or "system"
        agent_type = agent_payload.get("agent_type") or "system"
        agent_metadata = agent_payload.get("metadata") or {}
        agent_id = agent_payload.get("id") or _stable_hash(
            agent_type,
            agent_label,
            json.dumps(agent_metadata, sort_keys=True),
            prefix="agent",
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO kg_asserting_agents (id, label, agent_type, metadata)
            VALUES (?, ?, ?, ?)
            """,
            (
                agent_id,
                agent_label,
                agent_type,
                _json_dumps(agent_metadata, {}),
            ),
        )

        claim_key = _stable_hash(
            source_entity_id,
            target_entity_id,
            rel_type,
            data_source,
            vendor_id,
            claim_value,
            evidence,
            artifact_ref,
            prefix="claim",
        )
        claim_observed_at = observed_at or ""
        conn.execute(
            """
            INSERT INTO kg_claims (
                id,
                claim_key,
                source_entity_id,
                target_entity_id,
                rel_type,
                claim_type,
                claim_value,
                confidence,
                contradiction_state,
                validity_start,
                validity_end,
                observed_at,
                first_observed_at,
                last_observed_at,
                data_source,
                vendor_id,
                source_activity_id,
                asserting_agent_id,
                structured_fields,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'relationship', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(claim_key) DO UPDATE SET
                confidence = MAX(kg_claims.confidence, excluded.confidence),
                contradiction_state = excluded.contradiction_state,
                validity_start = COALESCE(excluded.validity_start, kg_claims.validity_start),
                validity_end = COALESCE(excluded.validity_end, kg_claims.validity_end),
                observed_at = COALESCE(excluded.observed_at, kg_claims.observed_at),
                last_observed_at = CASE
                    WHEN excluded.last_observed_at > kg_claims.last_observed_at THEN excluded.last_observed_at
                    ELSE kg_claims.last_observed_at
                END,
                vendor_id = COALESCE(excluded.vendor_id, kg_claims.vendor_id),
                source_activity_id = COALESCE(excluded.source_activity_id, kg_claims.source_activity_id),
                asserting_agent_id = COALESCE(excluded.asserting_agent_id, kg_claims.asserting_agent_id),
                structured_fields = excluded.structured_fields,
                updated_at = excluded.updated_at
            """,
            (
                claim_key,
                claim_key,
                source_entity_id,
                target_entity_id,
                rel_type,
                claim_value or evidence or rel_type,
                confidence,
                contradiction_state or "unreviewed",
                valid_from or None,
                valid_to or None,
                claim_observed_at or None,
                claim_observed_at or now,
                claim_observed_at or now,
                data_source or None,
                vendor_id or None,
                activity_id,
                agent_id,
                _json_dumps(structured_fields, {}),
                now,
            ),
        )

        evidence_key = _stable_hash(
            claim_key,
            evidence_url,
            artifact_ref,
            evidence_title,
            evidence,
            prefix="evidence",
        )
        if evidence or evidence_url or artifact_ref or evidence_title or raw_data or structured_fields:
            conn.execute(
                """
                INSERT OR IGNORE INTO kg_evidence (
                    id,
                    claim_id,
                    source,
                    title,
                    url,
                    artifact_ref,
                    snippet,
                    raw_data,
                    structured_fields,
                    source_class,
                    authority_level,
                    access_model,
                    observed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_key,
                    claim_key,
                    data_source or None,
                    evidence_title or None,
                    evidence_url or None,
                    artifact_ref or None,
                    evidence or None,
                    _json_dumps(raw_data, {}),
                    _json_dumps(structured_fields, {}),
                    source_class or None,
                    authority_level or None,
                    access_model or None,
                    claim_observed_at or now,
                ),
            )

        return relationship_id


def _aggregate_relationships(rel_rows: list[sqlite3.Row | dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str], dict] = {}
    for rel in rel_rows:
        rel_id = rel["id"] if isinstance(rel, sqlite3.Row) else rel.get("id")
        source_id = rel["source_entity_id"] if isinstance(rel, sqlite3.Row) else rel.get("source_entity_id", "")
        target_id = rel["target_entity_id"] if isinstance(rel, sqlite3.Row) else rel.get("target_entity_id", "")
        rel_type = rel["rel_type"] if isinstance(rel, sqlite3.Row) else rel.get("rel_type", "")
        confidence = rel["confidence"] if isinstance(rel, sqlite3.Row) else rel.get("confidence", 0.0)
        data_source = rel["data_source"] if isinstance(rel, sqlite3.Row) else rel.get("data_source", "")
        evidence = rel["evidence"] if isinstance(rel, sqlite3.Row) else rel.get("evidence", "")
        created_at = rel["created_at"] if isinstance(rel, sqlite3.Row) else rel.get("created_at", "")
        key = (source_id, target_id, rel_type)
        entry = grouped.setdefault(
            key,
            {
                "id": rel_id,
                "source_entity_id": source_id,
                "target_entity_id": target_id,
                "rel_type": rel_type,
                "confidence": confidence,
                "data_source": data_source,
                "evidence": evidence,
                "created_at": created_at,
                "data_sources": [],
                "evidence_snippets": [],
                "corroboration_count": 0,
                "first_seen_at": created_at,
                "last_seen_at": created_at,
                "relationship_ids": [],
                "claim_records": [],
            },
        )
        entry["confidence"] = max(entry["confidence"], confidence or 0.0)
        entry["corroboration_count"] += 1
        if rel_id is not None and rel_id not in entry["relationship_ids"]:
            entry["relationship_ids"].append(rel_id)
        if data_source and data_source not in entry["data_sources"]:
            entry["data_sources"].append(data_source)
        if evidence and evidence not in entry["evidence_snippets"]:
            entry["evidence_snippets"].append(evidence)
        if entry["created_at"] == "" or (created_at and created_at < entry["created_at"]):
            entry["created_at"] = created_at
        if entry["first_seen_at"] == "" or (created_at and created_at < entry["first_seen_at"]):
            entry["first_seen_at"] = created_at
        if created_at and created_at > entry["last_seen_at"]:
            entry["last_seen_at"] = created_at
        if data_source and not entry["data_source"]:
            entry["data_source"] = data_source
        if evidence and not entry["evidence"]:
            entry["evidence"] = evidence

    for entry in grouped.values():
        entry["data_sources"].sort()
        entry["evidence_summary"] = " | ".join(entry["evidence_snippets"][:3])
    return list(grouped.values())


def _fetch_claim_records_for_relationship(
    conn: sqlite3.Connection,
    source_id: str,
    target_id: str,
    rel_type: str,
    *,
    max_claim_records: int = 4,
    max_evidence_records: int = 4,
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            c.id AS claim_id,
            c.vendor_id,
            c.claim_value,
            c.confidence AS claim_confidence,
            c.contradiction_state,
            c.observed_at,
            c.first_observed_at,
            c.last_observed_at,
            c.data_source,
            c.structured_fields AS claim_structured_fields,
            c.updated_at,
            sa.source AS activity_source,
            sa.activity_type,
            sa.occurred_at AS activity_occurred_at,
            a.label AS agent_label,
            a.agent_type,
            e.id AS evidence_id,
            e.source AS evidence_source,
            e.title AS evidence_title,
            e.url AS evidence_url,
            e.artifact_ref,
            e.snippet AS evidence_snippet,
            e.source_class,
            e.authority_level,
            e.access_model,
            e.observed_at AS evidence_observed_at,
            e.structured_fields AS evidence_structured_fields
        FROM kg_claims c
        LEFT JOIN kg_source_activities sa ON sa.id = c.source_activity_id
        LEFT JOIN kg_asserting_agents a ON a.id = c.asserting_agent_id
        LEFT JOIN kg_evidence e ON e.claim_id = c.id
        WHERE c.source_entity_id = ? AND c.target_entity_id = ? AND c.rel_type = ?
        ORDER BY COALESCE(c.last_observed_at, c.observed_at, c.updated_at) DESC,
                 COALESCE(e.observed_at, '') DESC,
                 c.id DESC
        """,
        (source_id, target_id, rel_type),
    ).fetchall()

    claims: dict[str, dict] = {}
    ordered_claim_ids: list[str] = []
    for row in rows:
        claim_id = row["claim_id"]
        if claim_id not in claims:
            claims[claim_id] = {
                "claim_id": claim_id,
                "vendor_id": row["vendor_id"] or "",
                "claim_value": row["claim_value"] or "",
                "confidence": row["claim_confidence"] if row["claim_confidence"] is not None else 0.0,
                "contradiction_state": row["contradiction_state"] or "unreviewed",
                "observed_at": row["observed_at"] or "",
                "first_observed_at": row["first_observed_at"] or "",
                "last_observed_at": row["last_observed_at"] or "",
                "data_source": row["data_source"] or "",
                "structured_fields": _json_loads(row["claim_structured_fields"], {}),
                "updated_at": row["updated_at"] or "",
                "asserting_agent": {
                    "label": row["agent_label"] or "",
                    "agent_type": row["agent_type"] or "",
                },
                "source_activity": {
                    "source": row["activity_source"] or "",
                    "activity_type": row["activity_type"] or "",
                    "occurred_at": row["activity_occurred_at"] or "",
                },
                "evidence_records": [],
            }
            ordered_claim_ids.append(claim_id)

        evidence_id = row["evidence_id"]
        if not evidence_id:
            continue
        evidence_records = claims[claim_id]["evidence_records"]
        if any(existing["evidence_id"] == evidence_id for existing in evidence_records):
            continue
        evidence_records.append({
            "evidence_id": evidence_id,
            "source": row["evidence_source"] or "",
            "title": row["evidence_title"] or "",
            "url": row["evidence_url"] or "",
            "artifact_ref": row["artifact_ref"] or "",
            "snippet": row["evidence_snippet"] or "",
            "source_class": row["source_class"] or "",
            "authority_level": row["authority_level"] or "",
            "access_model": row["access_model"] or "",
            "observed_at": row["evidence_observed_at"] or "",
            "structured_fields": _json_loads(row["evidence_structured_fields"], {}),
        })

    return [
        {
            **claims[claim_id],
            "evidence_records": claims[claim_id]["evidence_records"][: max(1, int(max_evidence_records or 1))],
        }
        for claim_id in ordered_claim_ids[: max(1, int(max_claim_records or 1))]
    ]


def _fetch_claim_records_for_relationships(
    conn: sqlite3.Connection,
    relationships: list[dict],
    *,
    max_claim_records: int = 4,
    max_evidence_records: int = 4,
) -> dict[tuple[str, str, str], list[dict]]:
    relationship_keys: list[tuple[str, str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for relationship in relationships:
        key = (
            str(relationship.get("source_entity_id") or ""),
            str(relationship.get("target_entity_id") or ""),
            str(relationship.get("rel_type") or ""),
        )
        if not all(key) or key in seen_keys:
            continue
        seen_keys.add(key)
        relationship_keys.append(key)

    if not relationship_keys:
        return {}

    query_template = """
        SELECT
            c.id AS claim_id,
            c.vendor_id,
            c.source_entity_id,
            c.target_entity_id,
            c.rel_type,
            c.claim_value,
            c.confidence AS claim_confidence,
            c.contradiction_state,
            c.observed_at,
            c.first_observed_at,
            c.last_observed_at,
            c.data_source,
            c.structured_fields AS claim_structured_fields,
            c.updated_at,
            sa.source AS activity_source,
            sa.activity_type,
            sa.occurred_at AS activity_occurred_at,
            a.label AS agent_label,
            a.agent_type,
            e.id AS evidence_id,
            e.source AS evidence_source,
            e.title AS evidence_title,
            e.url AS evidence_url,
            e.artifact_ref,
            e.snippet AS evidence_snippet,
            e.source_class,
            e.authority_level,
            e.access_model,
            e.observed_at AS evidence_observed_at,
            e.structured_fields AS evidence_structured_fields
        FROM kg_claims c
        LEFT JOIN kg_source_activities sa ON sa.id = c.source_activity_id
        LEFT JOIN kg_asserting_agents a ON a.id = c.asserting_agent_id
        LEFT JOIN kg_evidence e ON e.claim_id = c.id
        WHERE {predicate}
        ORDER BY COALESCE(c.last_observed_at, c.observed_at, c.updated_at) DESC,
                 COALESCE(e.observed_at, '') DESC,
                 c.id DESC
    """

    rows: list[sqlite3.Row] = []
    chunk_size = 150
    for start in range(0, len(relationship_keys), chunk_size):
        chunk = relationship_keys[start : start + chunk_size]
        predicate = " OR ".join(
            "(c.source_entity_id = ? AND c.target_entity_id = ? AND c.rel_type = ?)"
            for _ in chunk
        )
        params: list[str] = []
        for source_id, target_id, rel_type in chunk:
            params.extend([source_id, target_id, rel_type])
        rows.extend(conn.execute(query_template.format(predicate=predicate), params).fetchall())

    claims_by_relationship: dict[tuple[str, str, str], dict[str, dict]] = {}
    ordered_claim_ids: dict[tuple[str, str, str], list[str]] = {}
    for row in rows:
        relationship_key = (
            row["source_entity_id"] or "",
            row["target_entity_id"] or "",
            row["rel_type"] or "",
        )
        claims = claims_by_relationship.setdefault(relationship_key, {})
        claim_order = ordered_claim_ids.setdefault(relationship_key, [])
        claim_id = row["claim_id"]
        if claim_id not in claims:
            claims[claim_id] = {
                "claim_id": claim_id,
                "vendor_id": row["vendor_id"] or "",
                "claim_value": row["claim_value"] or "",
                "confidence": row["claim_confidence"] if row["claim_confidence"] is not None else 0.0,
                "contradiction_state": row["contradiction_state"] or "unreviewed",
                "observed_at": row["observed_at"] or "",
                "first_observed_at": row["first_observed_at"] or "",
                "last_observed_at": row["last_observed_at"] or "",
                "data_source": row["data_source"] or "",
                "structured_fields": _json_loads(row["claim_structured_fields"], {}),
                "updated_at": row["updated_at"] or "",
                "asserting_agent": {
                    "label": row["agent_label"] or "",
                    "agent_type": row["agent_type"] or "",
                },
                "source_activity": {
                    "source": row["activity_source"] or "",
                    "activity_type": row["activity_type"] or "",
                    "occurred_at": row["activity_occurred_at"] or "",
                },
                "evidence_records": [],
            }
            claim_order.append(claim_id)

        evidence_id = row["evidence_id"]
        if not evidence_id:
            continue
        evidence_records = claims[claim_id]["evidence_records"]
        if any(existing["evidence_id"] == evidence_id for existing in evidence_records):
            continue
        evidence_records.append(
            {
                "evidence_id": evidence_id,
                "source": row["evidence_source"] or "",
                "title": row["evidence_title"] or "",
                "url": row["evidence_url"] or "",
                "artifact_ref": row["artifact_ref"] or "",
                "snippet": row["evidence_snippet"] or "",
                "source_class": row["source_class"] or "",
                "authority_level": row["authority_level"] or "",
                "access_model": row["access_model"] or "",
                "observed_at": row["evidence_observed_at"] or "",
                "structured_fields": _json_loads(row["evidence_structured_fields"], {}),
            }
        )

    return {
        relationship_key: [
            {
                **claims[claim_id],
                "evidence_records": claims[claim_id]["evidence_records"][: max(1, int(max_evidence_records or 1))],
            }
            for claim_id in ordered_claim_ids.get(relationship_key, [])[: max(1, int(max_claim_records or 1))]
        ]
        for relationship_key, claims in claims_by_relationship.items()
    }


def _attach_relationship_provenance(
    conn: sqlite3.Connection,
    relationships: list[dict],
    *,
    max_claim_records: int = 4,
    max_evidence_records: int = 4,
) -> list[dict]:
    claim_records_by_relationship = _fetch_claim_records_for_relationships(
        conn,
        relationships,
        max_claim_records=max_claim_records,
        max_evidence_records=max_evidence_records,
    )
    for relationship in relationships:
        relationship_key = (
            str(relationship.get("source_entity_id") or ""),
            str(relationship.get("target_entity_id") or ""),
            str(relationship.get("rel_type") or ""),
        )
        relationship["claim_records"] = claim_records_by_relationship.get(relationship_key, [])
    return relationships


def attach_relationship_provenance(
    relationships: list[dict],
    *,
    max_claim_records: int = 4,
    max_evidence_records: int = 4,
) -> list[dict]:
    """Hydrate claim and evidence records onto relationship payloads."""
    hydrated = [dict(rel) for rel in (relationships or []) if isinstance(rel, dict)]
    if not hydrated:
        return []
    with get_kg_conn() as conn:
        return _attach_relationship_provenance(
            conn,
            hydrated,
            max_claim_records=max_claim_records,
            max_evidence_records=max_evidence_records,
        )


def get_entity_network(
    entity_id: str,
    depth: int = 2,
    *,
    include_provenance: bool = True,
    max_claim_records: int = 4,
    max_evidence_records: int = 4,
) -> dict:
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
        raw_relationships = []
        seen_relationship_ids = set()

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
                    "aliases": json.loads(entity_row["aliases"]),
                    "identifiers": json.loads(entity_row["identifiers"]),
                    "confidence": entity_row["confidence"],
                    "country": entity_row["country"],
                    "sources": json.loads(entity_row["sources"]),
                    "created_at": entity_row["created_at"],
                }

                # Get relationships (BIDIRECTIONAL - outgoing AND incoming)
                rel_rows = conn.execute(
                    "SELECT * FROM kg_relationships WHERE source_entity_id = ? OR target_entity_id = ?",
                    (current_id, current_id)
                ).fetchall()

                for rel in rel_rows:
                    rel_id = rel["id"]
                    if rel_id not in seen_relationship_ids:
                        raw_relationships.append(rel)
                        seen_relationship_ids.add(rel_id)

                    # Traverse to the other end of the relationship.
                    if rel["source_entity_id"] == current_id:
                        neighbor_id = rel["target_entity_id"]
                    else:
                        neighbor_id = rel["source_entity_id"]
                    if neighbor_id not in visited and current_depth < depth:
                        queue.append((neighbor_id, current_depth + 1))

        all_relationships = _aggregate_relationships(raw_relationships)
        if include_provenance:
            all_relationships = _attach_relationship_provenance(
                conn,
                all_relationships,
                max_claim_records=max_claim_records,
                max_evidence_records=max_evidence_records,
            )
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


def find_shortest_path(source_id: str, target_id: str, max_depth: int = 6) -> list[dict] | None:
    """
    Find shortest path between two entities using BFS.
    Returns list of relationship/entity dicts forming the path,
    or None if no path found within max_depth.
    """
    import collections

    with get_kg_conn() as conn:
        visited = {source_id}
        queue = collections.deque([(source_id, [])])

        while queue:
            current, path = queue.popleft()
            if len(path) >= max_depth:
                continue

            # Get all relationships for current entity (both directions)
            rows = conn.execute("""
                SELECT r.id, r.source_entity_id, r.target_entity_id, r.rel_type, r.confidence,
                       r.data_source, r.evidence, r.created_at,
                       s.canonical_name as source_name, s.entity_type as source_type,
                       t.canonical_name as target_name, t.entity_type as target_type
                FROM kg_relationships r
                JOIN kg_entities s ON s.id = r.source_entity_id
                JOIN kg_entities t ON t.id = r.target_entity_id
                WHERE r.source_entity_id = ? OR r.target_entity_id = ?
            """, (current, current)).fetchall()

            for row in rows:
                # Determine the neighbor
                if row["source_entity_id"] == current:
                    neighbor_id = row["target_entity_id"]
                else:
                    neighbor_id = row["source_entity_id"]

                if neighbor_id in visited:
                    continue

                step = {
                    "relationship_id": row["id"],
                    "from_id": row["source_entity_id"],
                    "from_name": row["source_name"],
                    "from_type": row["source_type"],
                    "to_id": row["target_entity_id"],
                    "to_name": row["target_name"],
                    "to_type": row["target_type"],
                    "rel_type": row["rel_type"],
                    "confidence": row["confidence"],
                    "data_source": row["data_source"],
                    "evidence": row["evidence"],
                    "created_at": row["created_at"],
                }
                new_path = path + [step]

                if neighbor_id == target_id:
                    return new_path

                visited.add(neighbor_id)
                queue.append((neighbor_id, new_path))

        return None


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

        # Find paths between A and B entities (max depth 3, bidirectional)
        shared = []
        seen_paths = set()

        for a_id in entity_ids_a:
            visited = set()
            queue = [(a_id, 0, [], [])]

            while queue:
                current_id, depth, path_entities, path_relationships = queue.pop(0)
                if current_id in visited or depth > 3:
                    continue
                visited.add(current_id)

                if current_id in entity_ids_b and current_id != a_id and path_relationships:
                    path_key = tuple(
                        (
                            rel["source_entity_id"],
                            rel["target_entity_id"],
                            rel["rel_type"],
                            rel.get("data_source", ""),
                            rel.get("evidence", ""),
                        )
                        for rel in path_relationships
                    )
                    if path_key not in seen_paths:
                        seen_paths.add(path_key)
                        shared.append({
                            "vendor_a": vendor_id_a,
                            "vendor_b": vendor_id_b,
                            "path_start": a_id,
                            "path_end": current_id,
                            "path_length": depth,
                            "entity_path": path_entities + [current_id],
                            "relationships": path_relationships,
                        })

                rel_rows = conn.execute(
                    "SELECT * FROM kg_relationships WHERE source_entity_id = ? OR target_entity_id = ?",
                    (current_id, current_id),
                ).fetchall()

                for rel in rel_rows:
                    rel_dict = dict(rel)
                    if rel["source_entity_id"] == current_id:
                        neighbor_id = rel["target_entity_id"]
                    else:
                        neighbor_id = rel["source_entity_id"]
                    if neighbor_id not in visited and depth < 3:
                        queue.append(
                            (
                                neighbor_id,
                                depth + 1,
                                path_entities + [current_id],
                                path_relationships + [rel_dict],
                            )
                        )

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
        claim_count = conn.execute("SELECT COUNT(*) FROM kg_claims").fetchone()[0]
        evidence_count = conn.execute("SELECT COUNT(*) FROM kg_evidence").fetchone()[0]
        activity_count = conn.execute("SELECT COUNT(*) FROM kg_source_activities").fetchone()[0]
        agent_count = conn.execute("SELECT COUNT(*) FROM kg_asserting_agents").fetchone()[0]

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
            "claim_count": claim_count,
            "evidence_count": evidence_count,
            "source_activity_count": activity_count,
            "asserting_agent_count": agent_count,
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


def clear_vendor_graph_state(vendor_id: str) -> None:
    """
    Remove vendor-scoped graph observations so re-enrichment replaces stale claims
    instead of accumulating contradictory connector output.
    """
    if not vendor_id:
        return

    with get_kg_conn() as conn:
        candidate_rows = conn.execute(
            """
            SELECT DISTINCT
                c.source_entity_id,
                c.target_entity_id,
                c.rel_type,
                COALESCE(c.data_source, '') AS data_source,
                COALESCE(e.snippet, '') AS evidence
            FROM kg_claims c
            LEFT JOIN kg_evidence e
                ON e.claim_id = c.id
            WHERE c.vendor_id = ?
            """,
            (vendor_id,),
        ).fetchall()

        conn.execute("DELETE FROM kg_entity_vendors WHERE vendor_id = ?", (vendor_id,))
        conn.execute("DELETE FROM kg_claims WHERE vendor_id = ?", (vendor_id,))

        for row in candidate_rows:
            remaining = conn.execute(
                """
                SELECT 1
                FROM kg_claims c
                LEFT JOIN kg_evidence e
                    ON e.claim_id = c.id
                WHERE c.source_entity_id = ?
                  AND c.target_entity_id = ?
                  AND c.rel_type = ?
                  AND COALESCE(c.data_source, '') = ?
                  AND COALESCE(e.snippet, '') = ?
                LIMIT 1
                """,
                (
                    row["source_entity_id"],
                    row["target_entity_id"],
                    row["rel_type"],
                    row["data_source"],
                    row["evidence"],
                ),
            ).fetchone()
            if remaining:
                continue
            conn.execute(
                """
                DELETE FROM kg_relationships
                WHERE source_entity_id = ?
                  AND target_entity_id = ?
                  AND rel_type = ?
                  AND COALESCE(data_source, '') = ?
                  AND COALESCE(evidence, '') = ?
                """,
                (
                    row["source_entity_id"],
                    row["target_entity_id"],
                    row["rel_type"],
                    row["data_source"],
                    row["evidence"],
                ),
            )

        conn.execute(
            """
            DELETE FROM kg_source_activities
            WHERE id NOT IN (
                SELECT DISTINCT source_activity_id
                FROM kg_claims
                WHERE source_activity_id IS NOT NULL
            )
            """
        )
        conn.execute(
            """
            DELETE FROM kg_asserting_agents
            WHERE id NOT IN (
                SELECT DISTINCT asserting_agent_id
                FROM kg_claims
                WHERE asserting_agent_id IS NOT NULL
            )
            """
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
                "entity_id": row["id"],
                "name": row["canonical_name"],
                "canonical_name": row["canonical_name"],
                "entity_type": row["entity_type"],
                "aliases": json.loads(row["aliases"]),
                "identifiers": json.loads(row["identifiers"]),
                "country": row["country"],
                "sources": json.loads(row["sources"]),
                "confidence": row["confidence"],
                "last_updated": row["last_updated"],
                "created_at": row["created_at"],
            }
            entity_ids.add(row["id"])

        # Get relationships
        rel_rows = conn.execute(
            "SELECT * FROM kg_relationships WHERE source_entity_id IN ({})".format(
                ",".join("?" * len(entity_ids))
            ) if entity_ids else "SELECT * FROM kg_relationships LIMIT 10000",
            list(entity_ids) if entity_ids else [],
        ).fetchall()

        relationships = _aggregate_relationships(rel_rows)

        return {
            "export_timestamp": datetime.utcnow().isoformat() + "Z",
            "entity_count": len(entities),
            "relationship_count": len(relationships),
            "claim_count": conn.execute("SELECT COUNT(*) FROM kg_claims").fetchone()[0],
            "evidence_count": conn.execute("SELECT COUNT(*) FROM kg_evidence").fetchone()[0],
            "entities": entities,
            "relationships": relationships,
        }



# ---------------------------------------------------------------------------
# Risk propagation simulation
# ---------------------------------------------------------------------------

def simulate_risk_propagation(source_id, max_hops=4, decay_factor=0.6):
    """
    Simulate risk spreading from a source entity through the network.
    
    Returns a list of propagation waves, where each wave contains entities
    reached at that hop distance with their received risk score.
    
    Args:
        source_id: Starting entity ID
        max_hops: Maximum propagation distance
        decay_factor: Risk decay per hop (0.6 = 60% retained per hop)
    
    Returns:
        {
            "source": { id, name, type, risk_level },
            "waves": [
                { "hop": 1, "entities": [{ id, name, type, received_risk, rel_type, from_id }] },
                { "hop": 2, "entities": [...] },
                ...
            ],
            "total_affected": N,
            "max_risk_propagated": float
        }
    """
    with get_kg_conn() as conn:
        # Get source entity -- risk_level/sanctions_exposure may not exist on
        # legacy databases so fall back to confidence-based heuristic.
        try:
            source = conn.execute(
                "SELECT id, canonical_name, entity_type, risk_level, sanctions_exposure FROM kg_entities WHERE id = ?",
                (source_id,)
            ).fetchone()
        except Exception:
            source = conn.execute(
                "SELECT id, canonical_name, entity_type, confidence FROM kg_entities WHERE id = ?",
                (source_id,)
            ).fetchone()
            if source:
                source = dict(source)
                source["risk_level"] = "high" if source.get("confidence", 0) > 0.7 else "medium"
                source["sanctions_exposure"] = source.get("confidence", 0.5)
        
        if not source:
            return None
        
        source_risk = source["sanctions_exposure"] if source["sanctions_exposure"] else 1.0
        
        visited = {source_id}
        current_frontier = [(source_id, source_risk)]
        waves = []
        
        for hop in range(1, max_hops + 1):
            next_frontier = []
            wave_entities = []
            
            for entity_id, incoming_risk in current_frontier:
                # Find all neighbors (bidirectional).  The risk_level column
                # may be absent on legacy databases; use COALESCE with a
                # fallback so the query never fails.
                try:
                    rows = conn.execute("""
                        SELECT r.source_entity_id, r.target_entity_id, r.rel_type, r.confidence,
                               e.id as neighbor_id, e.canonical_name, e.entity_type,
                               COALESCE(e.risk_level, 'unknown') as risk_level
                        FROM kg_relationships r
                        JOIN kg_entities e ON e.id = CASE
                            WHEN r.source_entity_id = ? THEN r.target_entity_id
                            ELSE r.source_entity_id END
                        WHERE (r.source_entity_id = ? OR r.target_entity_id = ?)
                    """, (entity_id, entity_id, entity_id)).fetchall()
                except Exception:
                    # Fallback query without risk_level column
                    rows = conn.execute("""
                        SELECT r.source_entity_id, r.target_entity_id, r.rel_type, r.confidence,
                               e.id as neighbor_id, e.canonical_name, e.entity_type,
                               'unknown' as risk_level
                        FROM kg_relationships r
                        JOIN kg_entities e ON e.id = CASE
                            WHEN r.source_entity_id = ? THEN r.target_entity_id
                            ELSE r.source_entity_id END
                        WHERE (r.source_entity_id = ? OR r.target_entity_id = ?)
                    """, (entity_id, entity_id, entity_id)).fetchall()

                for row in rows:
                    neighbor_id = row["neighbor_id"]
                    if neighbor_id in visited:
                        continue

                    propagated_risk = incoming_risk * decay_factor * row["confidence"]

                    visited.add(neighbor_id)
                    wave_entities.append({
                        "id": neighbor_id,
                        "name": row["canonical_name"],
                        "type": row["entity_type"],
                        "existing_risk_level": row["risk_level"],
                        "received_risk": round(propagated_risk, 4),
                        "rel_type": row["rel_type"],
                        "from_id": entity_id,
                    })
                    next_frontier.append((neighbor_id, propagated_risk))
            
            if wave_entities:
                # Sort by received risk descending
                wave_entities.sort(key=lambda x: x["received_risk"], reverse=True)
                waves.append({"hop": hop, "entities": wave_entities})
            
            current_frontier = next_frontier
            if not current_frontier:
                break
        
        total_affected = sum(len(w["entities"]) for w in waves)
        max_propagated = max((e["received_risk"] for w in waves for e in w["entities"]), default=0)
        
        return {
            "source": {
                "id": source["id"],
                "name": source["canonical_name"],
                "type": source["entity_type"],
                "risk_level": source["risk_level"],
                "base_risk": source_risk,
            },
            "waves": waves,
            "total_affected": total_affected,
            "max_risk_propagated": round(max_propagated, 4),
            "decay_factor": decay_factor,
            "max_hops": max_hops,
        }
