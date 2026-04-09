"""
Provider-neutral persistence layer for the Helios knowledge graph.

Historically this module wrote to a dedicated SQLite knowledge-graph file.
The live stack now runs on PostgreSQL, so graph writes must follow the same
provider path that the rest of the application, graph training, and Neo4j sync
already use.
"""

import logging
import sqlite3
from collections import deque
import json
import hashlib
import os
import re
from datetime import datetime
from contextlib import contextmanager
from entity_resolution import ResolvedEntity
from runtime_paths import get_kg_db_path as resolve_kg_db_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def get_kg_db_path() -> str:
    """Get knowledge graph database path from environment or default."""
    return resolve_kg_db_path()


def _use_postgres_kg() -> bool:
    db_engine = os.environ.get("XIPHOS_DB_ENGINE", "").strip().lower()
    if db_engine in {"postgres", "postgresql", "pg"}:
        return True
    return bool(os.environ.get("XIPHOS_PG_URL", "").strip())


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
    current = value
    for _ in range(4):
        if isinstance(current, (dict, list)):
            return current
        if not isinstance(current, str):
            return fallback if isinstance(fallback, (dict, list)) else current
        try:
            current = json.loads(current)
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback
    return fallback if isinstance(fallback, (dict, list)) else current


_MAX_ALIAS_PAYLOAD_CHARS = int(os.environ.get("XIPHOS_KG_ALIAS_PAYLOAD_MAX_CHARS", "4096"))
_MAX_ALIAS_COUNT = int(os.environ.get("XIPHOS_KG_ALIAS_MAX_COUNT", "64"))
_MAX_ALIAS_VALUE_CHARS = int(os.environ.get("XIPHOS_KG_ALIAS_VALUE_MAX_CHARS", "180"))
_ALIAS_REPAIR_SCAN_LIMIT = int(os.environ.get("XIPHOS_KG_ALIAS_REPAIR_SCAN_LIMIT", "128"))
_ALIAS_REPAIR_RAN = False
_MAX_IDENTIFIER_PAYLOAD_CHARS = int(os.environ.get("XIPHOS_KG_IDENTIFIER_PAYLOAD_MAX_CHARS", "32768"))
_MAX_SOURCE_PAYLOAD_CHARS = int(os.environ.get("XIPHOS_KG_SOURCE_PAYLOAD_MAX_CHARS", "8192"))
_ENTITY_JSON_REPAIR_SCAN_LIMIT = int(os.environ.get("XIPHOS_KG_ENTITY_JSON_REPAIR_SCAN_LIMIT", "128"))
_ENTITY_JSON_REPAIR_RAN = False


def _normalize_alias_text(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    text = text.strip("\"'")
    return text[:_MAX_ALIAS_VALUE_CHARS].strip()


def _looks_like_corrupt_alias_char_array(values: list[object]) -> bool:
    sample = values[: min(len(values), 32)]
    if len(sample) < 8:
        return False
    if not all(isinstance(item, str) and len(item) <= 1 for item in sample):
        return False
    punctuation_hits = sum(1 for item in sample if item in {"[", "]", "{", "}", '"', ",", "\\", " "})
    return punctuation_hits >= max(4, len(sample) // 2)


def normalize_entity_aliases(value, canonical_name: str = "") -> tuple[list[str], bool]:
    repaired = False
    parsed = value

    if isinstance(parsed, str):
        stripped = parsed.strip()
        if not stripped:
            return [], False
        if len(stripped) > _MAX_ALIAS_PAYLOAD_CHARS:
            return [], True
        parsed = _json_loads(stripped, stripped)
        if parsed == stripped:
            parsed = [stripped]
            repaired = True

    while isinstance(parsed, str):
        repaired = True
        stripped = parsed.strip()
        if not stripped or len(stripped) > _MAX_ALIAS_PAYLOAD_CHARS:
            return [], True
        next_parsed = _json_loads(stripped, stripped)
        if next_parsed == stripped:
            parsed = [stripped]
            break
        parsed = next_parsed

    if isinstance(parsed, (set, tuple)):
        parsed = list(parsed)
        repaired = True

    if not isinstance(parsed, list):
        if parsed in (None, "", {}):
            return [], repaired or parsed not in (None, "")
        parsed = [parsed]
        repaired = True

    if _looks_like_corrupt_alias_char_array(parsed):
        return [], True

    normalized: list[str] = []
    seen: set[str] = set()
    canonical_norm = _normalize_alias_text(canonical_name).casefold()

    for item in parsed:
        text = _normalize_alias_text(item)
        if not text:
            if item not in (None, ""):
                repaired = True
            continue
        if len(text) <= 1:
            repaired = True
            continue
        folded = text.casefold()
        if canonical_norm and folded == canonical_norm:
            repaired = True
            continue
        if folded in seen:
            repaired = True
            continue
        seen.add(folded)
        normalized.append(text)
        if len(normalized) >= _MAX_ALIAS_COUNT:
            repaired = True
            break

    return normalized, repaired


def normalize_entity_identifiers(value) -> tuple[dict, bool]:
    repaired = False
    if isinstance(value, str) and len(value) > _MAX_IDENTIFIER_PAYLOAD_CHARS:
        return {}, True

    parsed = _json_loads(value, {})
    if value not in (None, "", {}) and parsed == {} and value not in ({}, "{}"):
        repaired = True

    if isinstance(parsed, (set, tuple)):
        parsed = dict(parsed)
        repaired = True

    if not isinstance(parsed, dict):
        if parsed not in (None, "", {}):
            repaired = True
        return {}, repaired

    normalized: dict[str, object] = {}
    for key, item in parsed.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            repaired = True
            continue
        normalized[normalized_key] = item

    return normalized, repaired or normalized != parsed


def normalize_entity_sources(value) -> tuple[list[str], bool]:
    repaired = False
    if isinstance(value, str) and len(value) > _MAX_SOURCE_PAYLOAD_CHARS:
        return [], True

    parsed = _json_loads(value, [])
    if value not in (None, "", []) and parsed == [] and value not in ([], "[]"):
        repaired = True

    if isinstance(parsed, (set, tuple)):
        parsed = list(parsed)
        repaired = True

    if not isinstance(parsed, list):
        if parsed not in (None, "", []):
            repaired = True
        return [], repaired

    normalized: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        text = str(item or "").strip()
        if not text:
            if item not in (None, ""):
                repaired = True
            continue
        if text in seen:
            repaired = True
            continue
        seen.add(text)
        normalized.append(text)

    return normalized, repaired or normalized != parsed


def repair_corrupt_alias_payloads(limit: int = _ALIAS_REPAIR_SCAN_LIMIT) -> int:
    global _ALIAS_REPAIR_RAN
    if _ALIAS_REPAIR_RAN:
        return 0
    _ALIAS_REPAIR_RAN = True

    try:
        with get_kg_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, canonical_name, aliases
                FROM kg_entities
                WHERE aliases IS NOT NULL
                  AND LENGTH(CAST(aliases AS TEXT)) > ?
                ORDER BY LENGTH(CAST(aliases AS TEXT)) DESC
                LIMIT ?
                """,
                (_MAX_ALIAS_PAYLOAD_CHARS, max(int(limit or 0), 1)),
            ).fetchall()

            repaired = 0
            now = _utc_now()
            for row in rows:
                aliases, needs_repair = normalize_entity_aliases(row["aliases"], row["canonical_name"])
                if not needs_repair:
                    continue
                conn.execute(
                    "UPDATE kg_entities SET aliases = ?, last_updated = ? WHERE id = ?",
                    (json.dumps(aliases), now, row["id"]),
                )
                repaired += 1
            if repaired:
                logger.warning("Repaired %s corrupted knowledge-graph alias payload(s).", repaired)
            return repaired
    except Exception as exc:
        logger.warning("Knowledge-graph alias repair skipped: %s", exc)
        return 0


def repair_corrupt_entity_json_payloads(limit: int = _ENTITY_JSON_REPAIR_SCAN_LIMIT) -> int:
    global _ENTITY_JSON_REPAIR_RAN
    if _ENTITY_JSON_REPAIR_RAN:
        return 0
    _ENTITY_JSON_REPAIR_RAN = True

    try:
        with get_kg_conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    CASE
                        WHEN LENGTH(CAST(identifiers AS TEXT)) > ? THEN NULL
                        ELSE identifiers
                    END AS identifiers,
                    LENGTH(CAST(identifiers AS TEXT)) AS identifiers_length,
                    CASE
                        WHEN LENGTH(CAST(sources AS TEXT)) > ? THEN NULL
                        ELSE sources
                    END AS sources,
                    LENGTH(CAST(sources AS TEXT)) AS sources_length
                FROM kg_entities
                WHERE identifiers IS NOT NULL
                  AND (
                    LENGTH(CAST(identifiers AS TEXT)) > ?
                    OR SUBSTR(CAST(identifiers AS TEXT), 1, 1) = '"'
                  )
                   OR sources IS NOT NULL
                  AND (
                    LENGTH(CAST(sources AS TEXT)) > ?
                    OR SUBSTR(CAST(sources AS TEXT), 1, 1) = '"'
                  )
                ORDER BY
                    MAX(LENGTH(CAST(identifiers AS TEXT)), LENGTH(CAST(sources AS TEXT))) DESC
                LIMIT ?
                """,
                (
                    _MAX_IDENTIFIER_PAYLOAD_CHARS,
                    _MAX_SOURCE_PAYLOAD_CHARS,
                    _MAX_IDENTIFIER_PAYLOAD_CHARS,
                    _MAX_SOURCE_PAYLOAD_CHARS,
                    max(int(limit or 0), 1),
                ),
            ).fetchall()

            repaired = 0
            now = _utc_now()
            for row in rows:
                identifiers, identifiers_repaired = normalize_entity_identifiers(row["identifiers"])
                sources, sources_repaired = normalize_entity_sources(row["sources"])
                needs_repair = (
                    int(row["identifiers_length"] or 0) > _MAX_IDENTIFIER_PAYLOAD_CHARS
                    or int(row["sources_length"] or 0) > _MAX_SOURCE_PAYLOAD_CHARS
                    or identifiers_repaired
                    or sources_repaired
                )
                if not needs_repair:
                    continue
                conn.execute(
                    "UPDATE kg_entities SET identifiers = ?, sources = ?, last_updated = ? WHERE id = ?",
                    (json.dumps(identifiers), json.dumps(sources), now, row["id"]),
                )
                repaired += 1
            if repaired:
                logger.warning("Repaired %s corrupted knowledge-graph identifier/source payload(s).", repaired)
            return repaired
    except Exception as exc:
        logger.warning("Knowledge-graph identifier/source repair skipped: %s", exc)
        return 0


def _stable_hash(*parts: str, prefix: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:20]}"


@contextmanager
def get_kg_conn():
    """Context manager for knowledge graph connections across SQLite and PostgreSQL."""
    if _use_postgres_kg():
        import db

        with db.get_conn() as conn:
            yield conn
        return

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
    if _use_postgres_kg():
        import db

        db.init_db()
        repair_corrupt_alias_payloads()
        repair_corrupt_entity_json_payloads()
        return

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

            CREATE TABLE IF NOT EXISTS kg_graph_staging (
                id TEXT PRIMARY KEY,
                proposal_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'staged',
                entity_id TEXT,
                source_entity_id TEXT,
                target_entity_id TEXT,
                relationship_id TEXT,
                rel_type TEXT,
                annotation_type TEXT,
                flag_type TEXT,
                severity TEXT,
                proposed_confidence REAL NOT NULL DEFAULT 0.0,
                source_tier TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                reasoning TEXT NOT NULL DEFAULT '',
                evidence JSON NOT NULL DEFAULT '[]',
                supporting_claim_ids JSON NOT NULL DEFAULT '[]',
                structured_fields JSON NOT NULL DEFAULT '{}',
                vendor_id TEXT,
                proposed_by_agent_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                reviewed_at TEXT,
                reviewed_by TEXT,
                review_outcome TEXT,
                review_notes TEXT,
                FOREIGN KEY (entity_id) REFERENCES kg_entities(id) ON DELETE SET NULL,
                FOREIGN KEY (source_entity_id) REFERENCES kg_entities(id) ON DELETE SET NULL,
                FOREIGN KEY (target_entity_id) REFERENCES kg_entities(id) ON DELETE SET NULL,
                FOREIGN KEY (proposed_by_agent_id) REFERENCES kg_asserting_agents(id) ON DELETE SET NULL
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
            CREATE INDEX IF NOT EXISTS idx_kg_graph_staging_status
                ON kg_graph_staging(status);
            CREATE INDEX IF NOT EXISTS idx_kg_graph_staging_type
                ON kg_graph_staging(proposal_type);
            CREATE INDEX IF NOT EXISTS idx_kg_graph_staging_vendor
                ON kg_graph_staging(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_kg_graph_staging_entity
                ON kg_graph_staging(entity_id);
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
    repair_corrupt_alias_payloads()
    repair_corrupt_entity_json_payloads()


# ---------------------------------------------------------------------------
# Entity operations
# ---------------------------------------------------------------------------

def save_entity(entity: ResolvedEntity) -> str:
    """
    Save a resolved entity to the knowledge graph.
    Returns the entity ID.
    """
    aliases, _ = normalize_entity_aliases(getattr(entity, "aliases", []), entity.canonical_name)
    identifiers, _ = normalize_entity_identifiers(getattr(entity, "identifiers", {}))
    sources, _ = normalize_entity_sources(getattr(entity, "sources", []))
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
            json.dumps(aliases),
            json.dumps(identifiers),
            entity.country,
            json.dumps(sources),
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
            aliases=normalize_entity_aliases(row["aliases"], row["canonical_name"])[0],
            identifiers=normalize_entity_identifiers(row["identifiers"])[0],
            country=row["country"],
            relationships=relationships,
            sources=normalize_entity_sources(row["sources"])[0],
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
                aliases=normalize_entity_aliases(row["aliases"], row["canonical_name"])[0],
                identifiers=normalize_entity_identifiers(row["identifiers"])[0],
                country=row["country"],
                relationships=[dict(r) for r in rel_rows],
                sources=normalize_entity_sources(row["sources"])[0],
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
                confidence = CASE
                    WHEN excluded.confidence > kg_claims.confidence THEN excluded.confidence
                    ELSE kg_claims.confidence
                END,
                contradiction_state = excluded.contradiction_state,
                validity_start = COALESCE(excluded.validity_start, kg_claims.validity_start),
                validity_end = CASE
                    WHEN LOWER(COALESCE(kg_claims.contradiction_state, '')) = 'historical'
                         AND LOWER(COALESCE(excluded.contradiction_state, '')) != 'historical'
                    THEN excluded.validity_end
                    ELSE COALESCE(excluded.validity_end, kg_claims.validity_end)
                END,
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


def _ensure_graph_agent(
    conn: sqlite3.Connection,
    *,
    label: str,
    agent_type: str = "agentic_analysis",
    metadata: dict | None = None,
    agent_id: str = "",
) -> str:
    resolved_metadata = metadata or {}
    resolved_id = agent_id or _stable_hash(
        agent_type,
        label,
        json.dumps(resolved_metadata, sort_keys=True),
        prefix="agent",
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO kg_asserting_agents (id, label, agent_type, metadata)
        VALUES (?, ?, ?, ?)
        """,
        (
            resolved_id,
            label,
            agent_type,
            _json_dumps(resolved_metadata, {}),
        ),
    )
    return resolved_id


def _stage_graph_proposal(
    *,
    proposal_type: str,
    entity_id: str = "",
    source_entity_id: str = "",
    target_entity_id: str = "",
    relationship_id: str = "",
    rel_type: str = "",
    annotation_type: str = "",
    flag_type: str = "",
    severity: str = "",
    proposed_confidence: float = 0.0,
    source_tier: str = "",
    content: str = "",
    reasoning: str = "",
    evidence: list[dict] | list[str] | None = None,
    supporting_claim_ids: list[str] | None = None,
    structured_fields: dict | None = None,
    vendor_id: str = "",
    proposed_by: dict | None = None,
) -> dict:
    init_kg_db()
    now = _utc_now()
    normalized_evidence = [item for item in (evidence or []) if isinstance(item, (dict, str))]
    normalized_claim_ids = [str(item).strip() for item in (supporting_claim_ids or []) if str(item).strip()]
    normalized_fields = structured_fields or {}

    with get_kg_conn() as conn:
        agent_payload = proposed_by or {
            "label": "AXIOM Graph Interface",
            "agent_type": "agentic_analysis",
            "metadata": {"proposal_type": proposal_type},
        }
        agent_id = _ensure_graph_agent(
            conn,
            label=str(agent_payload.get("label") or "AXIOM Graph Interface"),
            agent_type=str(agent_payload.get("agent_type") or "agentic_analysis"),
            metadata=agent_payload.get("metadata") if isinstance(agent_payload.get("metadata"), dict) else {},
            agent_id=str(agent_payload.get("id") or ""),
        )
        staging_id = _stable_hash(
            proposal_type,
            entity_id,
            source_entity_id,
            target_entity_id,
            relationship_id,
            rel_type,
            annotation_type,
            flag_type,
            severity,
            content,
            reasoning,
            vendor_id,
            json.dumps(normalized_fields, sort_keys=True),
            prefix="kgstage",
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO kg_graph_staging (
                id,
                proposal_type,
                status,
                entity_id,
                source_entity_id,
                target_entity_id,
                relationship_id,
                rel_type,
                annotation_type,
                flag_type,
                severity,
                proposed_confidence,
                source_tier,
                content,
                reasoning,
                evidence,
                supporting_claim_ids,
                structured_fields,
                vendor_id,
                proposed_by_agent_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, 'staged', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                staging_id,
                proposal_type,
                entity_id or None,
                source_entity_id or None,
                target_entity_id or None,
                relationship_id or None,
                rel_type or None,
                annotation_type or None,
                flag_type or None,
                severity or None,
                max(0.0, min(float(proposed_confidence or 0.0), 1.0)),
                source_tier or "",
                content or "",
                reasoning or "",
                _json_dumps(normalized_evidence, []),
                _json_dumps(normalized_claim_ids, []),
                _json_dumps(normalized_fields, {}),
                vendor_id or None,
                agent_id,
                now,
                now,
            ),
        )

    return {
        "staging_id": staging_id,
        "proposal_type": proposal_type,
        "status": "staged",
        "entity_id": entity_id,
        "source_entity_id": source_entity_id,
        "target_entity_id": target_entity_id,
        "relationship_id": relationship_id,
        "rel_type": rel_type,
        "annotation_type": annotation_type,
        "flag_type": flag_type,
        "severity": severity,
        "proposed_confidence": round(max(0.0, min(float(proposed_confidence or 0.0), 1.0)), 4),
        "source_tier": source_tier or "",
        "vendor_id": vendor_id or "",
        "created_at": now,
    }


def graph_assert(
    source_entity_id: str,
    target_entity_id: str,
    rel_type: str,
    *,
    confidence: float,
    evidence: list[dict] | list[str] | None = None,
    source_tier: str = "",
    reasoning: str = "",
    vendor_id: str = "",
    supporting_claim_ids: list[str] | None = None,
    proposed_by: dict | None = None,
    structured_fields: dict | None = None,
) -> dict:
    return _stage_graph_proposal(
        proposal_type="assert",
        source_entity_id=str(source_entity_id or "").strip(),
        target_entity_id=str(target_entity_id or "").strip(),
        rel_type=str(rel_type or "").strip(),
        proposed_confidence=confidence,
        source_tier=source_tier,
        reasoning=reasoning,
        evidence=evidence,
        vendor_id=vendor_id,
        supporting_claim_ids=supporting_claim_ids,
        proposed_by=proposed_by,
        structured_fields=structured_fields,
    )


def graph_annotate(
    entity_id: str,
    annotation_type: str,
    content: str,
    *,
    confidence: float = 0.0,
    reasoning: str = "",
    vendor_id: str = "",
    proposed_by: dict | None = None,
    structured_fields: dict | None = None,
) -> dict:
    return _stage_graph_proposal(
        proposal_type="annotate",
        entity_id=str(entity_id or "").strip(),
        annotation_type=str(annotation_type or "").strip(),
        content=str(content or "").strip(),
        proposed_confidence=confidence,
        reasoning=reasoning,
        vendor_id=vendor_id,
        proposed_by=proposed_by,
        structured_fields=structured_fields,
    )


def graph_flag(
    entity_id: str,
    flag_type: str,
    severity: str,
    reasoning: str,
    *,
    confidence: float = 0.0,
    vendor_id: str = "",
    proposed_by: dict | None = None,
    structured_fields: dict | None = None,
) -> dict:
    return _stage_graph_proposal(
        proposal_type="flag",
        entity_id=str(entity_id or "").strip(),
        flag_type=str(flag_type or "").strip(),
        severity=str(severity or "").strip(),
        reasoning=str(reasoning or "").strip(),
        proposed_confidence=confidence,
        vendor_id=vendor_id,
        proposed_by=proposed_by,
        structured_fields=structured_fields,
    )


def graph_update_confidence(
    relationship_id: str | int,
    new_confidence: float,
    *,
    evidence: list[dict] | list[str] | None = None,
    reasoning: str = "",
    vendor_id: str = "",
    supporting_claim_ids: list[str] | None = None,
    proposed_by: dict | None = None,
    structured_fields: dict | None = None,
) -> dict:
    return _stage_graph_proposal(
        proposal_type="update_confidence",
        relationship_id=str(relationship_id or "").strip(),
        proposed_confidence=new_confidence,
        reasoning=reasoning,
        evidence=evidence,
        vendor_id=vendor_id,
        supporting_claim_ids=supporting_claim_ids,
        proposed_by=proposed_by,
        structured_fields=structured_fields,
    )


def list_graph_staging(
    *,
    status: str = "staged",
    proposal_type: str = "",
    vendor_id: str = "",
    limit: int = 50,
) -> list[dict]:
    predicates: list[str] = []
    params: list[object] = []
    if str(status or "").strip():
        predicates.append("s.status = ?")
        params.append(str(status).strip())
    if str(proposal_type or "").strip():
        predicates.append("s.proposal_type = ?")
        params.append(str(proposal_type).strip())
    if str(vendor_id or "").strip():
        predicates.append("COALESCE(s.vendor_id, '') = ?")
        params.append(str(vendor_id).strip())
    where_clause = f"WHERE {' AND '.join(predicates)}" if predicates else ""

    with get_kg_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                s.*,
                a.label AS proposed_by_label,
                a.agent_type AS proposed_by_type
            FROM kg_graph_staging s
            LEFT JOIN kg_asserting_agents a ON a.id = s.proposed_by_agent_id
            {where_clause}
            ORDER BY s.updated_at DESC, s.created_at DESC
            LIMIT ?
            """,
            (*params, max(1, int(limit or 50))),
        ).fetchall()
    results = []
    for row in rows:
        results.append(
            {
                "staging_id": row["id"],
                "proposal_type": row["proposal_type"],
                "status": row["status"],
                "entity_id": row["entity_id"] or "",
                "source_entity_id": row["source_entity_id"] or "",
                "target_entity_id": row["target_entity_id"] or "",
                "relationship_id": row["relationship_id"] or "",
                "rel_type": row["rel_type"] or "",
                "annotation_type": row["annotation_type"] or "",
                "flag_type": row["flag_type"] or "",
                "severity": row["severity"] or "",
                "proposed_confidence": float(row["proposed_confidence"] or 0.0),
                "source_tier": row["source_tier"] or "",
                "content": row["content"] or "",
                "reasoning": row["reasoning"] or "",
                "evidence": _json_loads(row["evidence"], []),
                "supporting_claim_ids": _json_loads(row["supporting_claim_ids"], []),
                "structured_fields": _json_loads(row["structured_fields"], {}),
                "vendor_id": row["vendor_id"] or "",
                "proposed_by": {
                    "label": row["proposed_by_label"] or "",
                    "agent_type": row["proposed_by_type"] or "",
                },
                "created_at": row["created_at"] or "",
                "updated_at": row["updated_at"] or "",
                "reviewed_at": row["reviewed_at"] or "",
                "reviewed_by": row["reviewed_by"] or "",
                "review_outcome": row["review_outcome"] or "",
                "review_notes": row["review_notes"] or "",
            }
        )
    return results


def review_graph_staging_entry(
    staging_id: str,
    *,
    review_outcome: str,
    reviewed_by: str = "",
    review_notes: str = "",
) -> dict:
    normalized_id = str(staging_id or "").strip()
    if not normalized_id:
        raise ValueError("staging_id is required")

    normalized_outcome = str(review_outcome or "").strip().lower()
    status_map = {
        "promote": "reviewed_promoted",
        "promoted": "reviewed_promoted",
        "approve": "reviewed_promoted",
        "approved": "reviewed_promoted",
        "hold": "reviewed_hold",
        "held": "reviewed_hold",
        "needs_review": "reviewed_hold",
        "reject": "reviewed_rejected",
        "rejected": "reviewed_rejected",
        "deny": "reviewed_rejected",
        "denied": "reviewed_rejected",
    }
    if normalized_outcome not in status_map:
        raise ValueError("review_outcome must be one of promote, hold, or reject")

    now = _utc_now()
    with get_kg_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM kg_graph_staging WHERE id = ?",
            (normalized_id,),
        ).fetchone()
        if existing is None:
            raise ValueError(f"Staging entry not found: {normalized_id}")

        conn.execute(
            """
            UPDATE kg_graph_staging
            SET
                status = ?,
                updated_at = ?,
                reviewed_at = ?,
                reviewed_by = ?,
                review_outcome = ?,
                review_notes = ?
            WHERE id = ?
            """,
            (
                status_map[normalized_outcome],
                now,
                now,
                str(reviewed_by or "").strip(),
                normalized_outcome,
                str(review_notes or "").strip(),
                normalized_id,
            ),
        )

    reviewed = list_graph_staging(status="", proposal_type="", vendor_id="", limit=500)
    for item in reviewed:
        if item.get("staging_id") == normalized_id:
            return item
    raise ValueError(f"Unable to load reviewed staging entry: {normalized_id}")


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
                 COALESCE(e.observed_at, c.last_observed_at, c.observed_at, c.updated_at) DESC,
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
                 COALESCE(e.observed_at, c.last_observed_at, c.observed_at, c.updated_at) DESC,
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


def _build_provenance_sources_from_claim_records(claim_records: list[dict]) -> tuple[list[dict], str | None, str | None]:
    sources: list[dict] = []
    first_seen: str | None = None
    last_seen: str | None = None
    seen_keys: set[tuple[str, str, str, str]] = set()
    for claim in claim_records or []:
        claim_first = str(
            claim.get("first_observed_at")
            or claim.get("observed_at")
            or claim.get("updated_at")
            or ""
        ).strip() or None
        claim_last = str(
            claim.get("last_observed_at")
            or claim.get("observed_at")
            or claim.get("updated_at")
            or ""
        ).strip() or None
        if claim_first and (first_seen is None or claim_first < first_seen):
            first_seen = claim_first
        if claim_last and (last_seen is None or claim_last > last_seen):
            last_seen = claim_last

        evidence_records = claim.get("evidence_records") or []
        if evidence_records:
            for evidence in evidence_records:
                fetched_at = str(
                    evidence.get("observed_at")
                    or claim_last
                    or claim_first
                    or ""
                ).strip() or None
                if fetched_at and (first_seen is None or fetched_at < first_seen):
                    first_seen = fetched_at
                if fetched_at and (last_seen is None or fetched_at > last_seen):
                    last_seen = fetched_at
                source_key = (
                    str(evidence.get("evidence_id") or ""),
                    str(evidence.get("source") or ""),
                    str(fetched_at or ""),
                    str(evidence.get("snippet") or ""),
                )
                if source_key in seen_keys:
                    continue
                seen_keys.add(source_key)
                sources.append(
                    {
                        "connector": evidence.get("source") or claim.get("data_source") or "",
                        "fetched_at": fetched_at,
                        "confidence": claim.get("confidence", 0.0),
                        "raw_snippet": evidence.get("snippet") or claim.get("claim_value") or "",
                        "title": evidence.get("title") or "",
                        "url": evidence.get("url") or "",
                        "artifact_ref": evidence.get("artifact_ref") or "",
                        "source_class": evidence.get("source_class") or "",
                        "authority_level": evidence.get("authority_level") or "",
                        "access_model": evidence.get("access_model") or "",
                        "claim_id": claim.get("claim_id") or "",
                    }
                )
        else:
            source_key = (
                str(claim.get("claim_id") or ""),
                str(claim.get("data_source") or ""),
                str(claim_last or ""),
                str(claim.get("claim_value") or ""),
            )
            if source_key in seen_keys:
                continue
            seen_keys.add(source_key)
            sources.append(
                {
                    "connector": claim.get("data_source") or "",
                    "fetched_at": claim_last or claim_first,
                    "confidence": claim.get("confidence", 0.0),
                    "raw_snippet": claim.get("claim_value") or "",
                    "title": "",
                    "url": "",
                    "artifact_ref": "",
                    "source_class": "",
                    "authority_level": "",
                    "access_model": "",
                    "claim_id": claim.get("claim_id") or "",
                }
            )
    return sources, first_seen, last_seen


def get_relationship_provenance(relationship_id: int, *, max_claim_records: int = 12, max_evidence_records: int = 12) -> dict | None:
    """Return provenance detail for one relationship row."""
    with get_kg_conn() as conn:
        row = conn.execute(
            "SELECT * FROM kg_relationships WHERE id = ?",
            (relationship_id,),
        ).fetchone()
        if not row:
            return None

        aggregated = _aggregate_relationships([row])[0]
        hydrated = _attach_relationship_provenance(
            conn,
            [aggregated],
            max_claim_records=max_claim_records,
            max_evidence_records=max_evidence_records,
        )[0]
        sources, first_seen, last_seen = _build_provenance_sources_from_claim_records(
            hydrated.get("claim_records") or []
        )
        return {
            "relationship": hydrated,
            "sources": sources,
            "corroboration_count": hydrated.get("corroboration_count", 0),
            "first_seen": first_seen or hydrated.get("first_seen_at"),
            "last_seen": last_seen or hydrated.get("last_seen_at"),
        }


def get_entity_provenance(entity_id: str, *, max_claim_records: int = 24, max_evidence_records: int = 24) -> dict | None:
    """Return aggregated provenance for all claims touching an entity."""
    entity = get_entity(entity_id)
    if not entity:
        return None

    with get_kg_conn() as conn:
        claim_rows = conn.execute(
            """
            SELECT source_entity_id, target_entity_id, rel_type
            FROM kg_claims
            WHERE source_entity_id = ? OR target_entity_id = ?
            GROUP BY source_entity_id, target_entity_id, rel_type
            ORDER BY MAX(COALESCE(last_observed_at, observed_at, updated_at)) DESC
            """,
            (entity_id, entity_id),
        ).fetchall()

        relationships = [
            {
                "source_entity_id": row["source_entity_id"],
                "target_entity_id": row["target_entity_id"],
                "rel_type": row["rel_type"],
            }
            for row in claim_rows
        ]
        claim_records_by_relationship = _fetch_claim_records_for_relationships(
            conn,
            relationships,
            max_claim_records=max_claim_records,
            max_evidence_records=max_evidence_records,
        )

    all_claim_records: list[dict] = []
    for records in claim_records_by_relationship.values():
        all_claim_records.extend(records)
    sources, first_seen, last_seen = _build_provenance_sources_from_claim_records(all_claim_records)
    return {
        "entity": {
            "id": entity.id,
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type,
            "country": entity.country,
        },
        "sources": sources,
        "corroboration_count": len(all_claim_records),
        "first_seen": first_seen,
        "last_seen": last_seen,
    }


def _collect_entity_network(
    conn: sqlite3.Connection,
    root_entity_ids: list[str],
    depth: int,
    *,
    include_provenance: bool = True,
    max_claim_records: int = 4,
    max_evidence_records: int = 4,
) -> dict:
    normalized_roots: list[str] = []
    seen_roots: set[str] = set()
    for raw_id in root_entity_ids:
        entity_id = str(raw_id or "").strip()
        if not entity_id or entity_id in seen_roots:
            continue
        seen_roots.add(entity_id)
        normalized_roots.append(entity_id)

    if not normalized_roots:
        return {
            "root_entity_id": None,
            "root_entity_ids": [],
            "entity_count": 0,
            "entities": {},
            "relationship_count": 0,
            "relationships": [],
            "depth": depth,
        }

    visited: set[str] = set()
    queue = deque((entity_id, 0) for entity_id in normalized_roots)
    all_entities: dict[str, dict] = {}
    raw_relationships: list[sqlite3.Row] = []
    seen_relationship_ids: set[int] = set()

    while queue:
        current_id, current_depth = queue.popleft()
        if current_id in visited or current_depth > depth:
            continue
        visited.add(current_id)

        entity_row = conn.execute(
            "SELECT * FROM kg_entities WHERE id = ?",
            (current_id,),
        ).fetchone()

        if not entity_row:
            continue

        all_entities[current_id] = {
            "id": entity_row["id"],
            "canonical_name": entity_row["canonical_name"],
            "entity_type": entity_row["entity_type"],
            "aliases": _json_loads(entity_row["aliases"], []),
            "identifiers": normalize_entity_identifiers(entity_row["identifiers"])[0],
            "confidence": entity_row["confidence"],
            "country": entity_row["country"],
            "sources": normalize_entity_sources(entity_row["sources"])[0],
            "created_at": entity_row["created_at"],
        }

        rel_rows = conn.execute(
            "SELECT * FROM kg_relationships WHERE source_entity_id = ? OR target_entity_id = ?",
            (current_id, current_id),
        ).fetchall()

        for rel in rel_rows:
            rel_id = rel["id"]
            if rel_id not in seen_relationship_ids:
                raw_relationships.append(rel)
                seen_relationship_ids.add(rel_id)

            neighbor_id = rel["target_entity_id"] if rel["source_entity_id"] == current_id else rel["source_entity_id"]
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
        "root_entity_id": normalized_roots[0],
        "root_entity_ids": normalized_roots,
        "entity_count": len(all_entities),
        "entities": all_entities,
        "relationship_count": len(all_relationships),
        "relationships": all_relationships,
        "depth": depth,
    }


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
        return _collect_entity_network(
            conn,
            [entity_id],
            depth,
            include_provenance=include_provenance,
            max_claim_records=max_claim_records,
            max_evidence_records=max_evidence_records,
        )


def get_multi_entity_network(
    entity_ids: list[str],
    depth: int = 2,
    *,
    include_provenance: bool = True,
    max_claim_records: int = 4,
    max_evidence_records: int = 4,
) -> dict:
    """Get a combined network around multiple root entities in one traversal."""
    if depth < 0:
        depth = 2

    with get_kg_conn() as conn:
        return _collect_entity_network(
            conn,
            entity_ids,
            depth,
            include_provenance=include_provenance,
            max_claim_records=max_claim_records,
            max_evidence_records=max_evidence_records,
        )


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
        entity_rows = conn.execute(
            "SELECT entity_id FROM kg_entity_vendors WHERE vendor_id = ?",
            (vendor_id,),
        ).fetchall()
        ordered_entity_ids = [str(row[0] if isinstance(row, tuple) else row["entity_id"] or "") for row in entity_rows]
        ordered_entity_ids = [entity_id for entity_id in ordered_entity_ids if entity_id]
        if not ordered_entity_ids:
            return []

        placeholders = ",".join("?" for _ in ordered_entity_ids)
        entity_lookup = {
            str(row["id"]): row
            for row in conn.execute(
                f"SELECT * FROM kg_entities WHERE id IN ({placeholders})",
                ordered_entity_ids,
            ).fetchall()
        }
        relationship_rows = conn.execute(
            f"SELECT * FROM kg_relationships WHERE source_entity_id IN ({placeholders})",
            ordered_entity_ids,
        ).fetchall()
        relationships_by_source: dict[str, list[dict]] = {}
        for row in relationship_rows:
            source_entity_id = str(row["source_entity_id"] or "")
            relationships_by_source.setdefault(source_entity_id, []).append(dict(row))

        results = []
        for entity_id in ordered_entity_ids:
            entity_row = entity_lookup.get(entity_id)
            if not entity_row:
                continue
            entity = ResolvedEntity(
                id=entity_row["id"],
                canonical_name=entity_row["canonical_name"],
                entity_type=entity_row["entity_type"],
                aliases=normalize_entity_aliases(entity_row["aliases"], entity_row["canonical_name"])[0],
                identifiers=normalize_entity_identifiers(entity_row["identifiers"])[0],
                country=entity_row["country"],
                relationships=relationships_by_source.get(entity_id, []),
                sources=normalize_entity_sources(entity_row["sources"])[0],
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


def backfill_legacy_relationship_claims(*, batch_size: int = 500) -> dict:
    """Attach synthetic claim/evidence records to legacy relationships.

    Early graph ingest wrote kg_relationship rows before claim/evidence provenance
    existed. Case-scoped reasoning now depends on kg_claims, so this backfill
    replays those legacy rows into vendor-scoped claim records using the current
    entity-vendor links as the best available case association.
    """
    init_kg_db()
    with get_kg_conn() as conn:
        legacy_rows = conn.execute(
            """
            SELECT
                r.id,
                r.source_entity_id,
                r.target_entity_id,
                r.rel_type,
                r.confidence,
                COALESCE(r.data_source, '') AS data_source,
                COALESCE(r.evidence, '') AS evidence,
                r.created_at AS created_at
            FROM kg_relationships r
            LEFT JOIN kg_claims c
              ON c.source_entity_id = r.source_entity_id
             AND COALESCE(c.target_entity_id, '') = COALESCE(r.target_entity_id, '')
             AND c.rel_type = r.rel_type
            WHERE c.id IS NULL
            ORDER BY r.id ASC
            """
        ).fetchall()
        if not legacy_rows:
            return {
                "legacy_relationships_scanned": 0,
                "relationships_backfilled": 0,
                "claims_backfilled": 0,
                "evidence_backfilled": 0,
                "relationships_without_vendor_scope": 0,
            }

        entity_ids: set[str] = set()
        for row in legacy_rows:
            if row["source_entity_id"]:
                entity_ids.add(str(row["source_entity_id"]))
            if row["target_entity_id"]:
                entity_ids.add(str(row["target_entity_id"]))

        entity_vendor_map: dict[str, set[str]] = {}
        if entity_ids:
            placeholders = ",".join("?" for _ in entity_ids)
            vendor_rows = conn.execute(
                f"""
                SELECT entity_id, vendor_id
                FROM kg_entity_vendors
                WHERE entity_id IN ({placeholders})
                """,
                tuple(entity_ids),
            ).fetchall()
            for row in vendor_rows:
                entity_vendor_map.setdefault(str(row["entity_id"]), set()).add(str(row["vendor_id"]))
        stats = {
            "legacy_relationships_scanned": len(legacy_rows),
            "relationships_backfilled": 0,
            "claims_backfilled": 0,
            "evidence_backfilled": 0,
            "relationships_without_vendor_scope": 0,
        }
        seen_relationship_ids: set[int] = set()
        batch = max(1, int(batch_size or 1))

        for start in range(0, len(legacy_rows), batch):
            for row in legacy_rows[start : start + batch]:
                relationship_id = int(row["id"])
                source_entity_id = str(row["source_entity_id"] or "")
                target_entity_id = str(row["target_entity_id"] or "")
                rel_type = str(row["rel_type"] or "")
                confidence = float(row["confidence"] or 0.0)
                data_source = str(row["data_source"] or "")
                evidence = str(row["evidence"] or "")
                observed_at = str(row["created_at"] or "") or _utc_now()
                structured_fields = {"backfilled_legacy_claim": True, "relationship_id": relationship_id}
                vendor_ids = sorted(
                    (entity_vendor_map.get(source_entity_id, set()) or set())
                    | (entity_vendor_map.get(target_entity_id, set()) or set())
                )
                if not vendor_ids:
                    vendor_ids = [""]
                    stats["relationships_without_vendor_scope"] += 1

                for vendor_id in vendor_ids:
                    activity_id = _stable_hash(str(relationship_id), vendor_id, prefix="activity")
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO kg_source_activities (id, source, activity_type, occurred_at, metadata)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            activity_id,
                            data_source or "legacy_relationship_backfill",
                            "legacy_relationship_backfill",
                            observed_at,
                            _json_dumps({"relationship_id": relationship_id, "vendor_id": vendor_id}, {}),
                        ),
                    )

                    agent_id = _stable_hash(data_source or "legacy_relationship_backfill", prefix="agent")
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO kg_asserting_agents (id, label, agent_type, metadata)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            agent_id,
                            data_source or "legacy_relationship_backfill",
                            "migration",
                            _json_dumps({"relationship_id": relationship_id}, {}),
                        ),
                    )

                    claim_key = _stable_hash(
                        source_entity_id,
                        target_entity_id,
                        rel_type,
                        data_source,
                        vendor_id,
                        evidence,
                        f"kg-relationship://{relationship_id}",
                        prefix="claim",
                    )
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
                        VALUES (?, ?, ?, ?, ?, 'relationship', ?, ?, 'unreviewed', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(claim_key) DO NOTHING
                        """,
                        (
                            claim_key,
                            claim_key,
                            source_entity_id,
                            target_entity_id,
                            rel_type,
                            evidence or rel_type,
                            confidence,
                            observed_at,
                            observed_at,
                            observed_at,
                            data_source or None,
                            vendor_id or None,
                            activity_id,
                            agent_id,
                            _json_dumps(structured_fields, {}),
                            _utc_now(),
                        ),
                    )

                    evidence_key = _stable_hash(
                        claim_key,
                        f"kg-relationship://{relationship_id}",
                        evidence,
                        prefix="evidence",
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO kg_evidence (
                            id,
                            claim_id,
                            source,
                            title,
                            artifact_ref,
                            snippet,
                            structured_fields,
                            source_class,
                            authority_level,
                            access_model,
                            observed_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            evidence_key,
                            claim_key,
                            data_source or None,
                            "Legacy graph relationship backfill",
                            f"kg-relationship://{relationship_id}",
                            evidence or rel_type,
                            _json_dumps(structured_fields, {}),
                            "legacy_graph_backfill",
                            "legacy_unknown",
                            "sqlite_backfill",
                            observed_at,
                        ),
                    )

                if relationship_id not in seen_relationship_ids:
                    seen_relationship_ids.add(relationship_id)
                    stats["relationships_backfilled"] += 1
                stats["claims_backfilled"] += len(vendor_ids)
                stats["evidence_backfilled"] += len(vendor_ids)

        return stats


def clear_vendor_links(vendor_id: str) -> None:
    """Remove all entity-vendor links for a vendor (e.g., on re-enrichment)."""
    with get_kg_conn() as conn:
        conn.execute(
            "DELETE FROM kg_entity_vendors WHERE vendor_id = ?",
            (vendor_id,)
        )


def clear_vendor_graph_state(
    vendor_id: str,
    *,
    preserve_entity_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    historical_as_of: str = "",
) -> dict:
    """
    Age vendor-scoped graph observations so re-enrichment can replace stale claims
    without destroying provenance or collapsing thin vendor graphs.
    """
    if not vendor_id:
        return {"claims_aged": 0, "vendor_links_removed": 0}

    now = historical_as_of or _utc_now()
    preserved_ids = [
        str(entity_id or "").strip()
        for entity_id in (preserve_entity_ids or [])
        if str(entity_id or "").strip()
    ]

    with get_kg_conn() as conn:
        claim_rows = conn.execute(
            """
            SELECT id, contradiction_state, validity_end, structured_fields
            FROM kg_claims
            WHERE vendor_id = ?
            """,
            (vendor_id,),
        ).fetchall()

        claims_aged = 0
        for row in claim_rows:
            claim_id = str(row["id"] or "")
            contradiction_state = str(row["contradiction_state"] or "").strip().lower()
            structured_fields = _json_loads(row["structured_fields"], {})
            if not isinstance(structured_fields, dict):
                structured_fields = {}
            structured_fields["vendor_scope_state"] = "historical"
            structured_fields["historical_vendor_scope"] = True
            structured_fields["historical_vendor_id"] = vendor_id
            structured_fields["vendor_scope_superseded_at"] = now
            next_state = (
                row["contradiction_state"]
                if contradiction_state in {"contradicted", "disputed", "challenged", "retracted"}
                else "historical"
            )
            conn.execute(
                """
                UPDATE kg_claims
                SET contradiction_state = ?,
                    validity_end = COALESCE(validity_end, ?),
                    structured_fields = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    next_state,
                    now,
                    _json_dumps(structured_fields, {}),
                    now,
                    claim_id,
                ),
            )
            claims_aged += 1

        if preserved_ids:
            placeholders = ",".join("?" for _ in preserved_ids)
            cursor = conn.execute(
                f"DELETE FROM kg_entity_vendors WHERE vendor_id = ? AND entity_id NOT IN ({placeholders})",
                [vendor_id, *preserved_ids],
            )
        else:
            cursor = conn.execute("DELETE FROM kg_entity_vendors WHERE vendor_id = ?", (vendor_id,))

        vendor_links_removed = int(getattr(cursor, "rowcount", 0) or 0)

        return {
            "claims_aged": claims_aged,
            "vendor_links_removed": vendor_links_removed,
            "preserved_entity_ids": preserved_ids,
            "historical_as_of": now,
        }


def retract_invalid_public_html_relationships(source_entity_id: str) -> dict:
    """
    Retract clearly invalid public_html_ownership claims for a source entity, even if
    the bad claims were attached to older deduped vendor cases.
    """
    if not source_entity_id:
        return {"claims_deleted": 0, "relationships_deleted": 0}

    from ownership_control_intelligence import looks_like_descriptor_owner
    from osint import public_html_ownership

    def _should_retract(target_name: str, snippet: str) -> bool:
        cleaned = str(target_name or "").strip()
        if not cleaned:
            return False
        if looks_like_descriptor_owner(cleaned):
            return True
        if public_html_ownership._looks_like_geographic_name(cleaned):
            return True
        if not public_html_ownership._looks_like_entity_name(cleaned, cleaned):
            return True
        if re.search(r"\bpart of\b", str(snippet or "").lower()) and not public_html_ownership._part_of_phrase_has_corporate_signal(
            cleaned,
            cleaned,
            str(snippet or ""),
        ):
            return True
        return False

    deleted_claims = 0
    deleted_relationships = 0
    relationship_keys: set[tuple[str, str, str, str]] = set()

    with get_kg_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id,
                c.source_entity_id,
                c.target_entity_id,
                c.rel_type,
                COALESCE(c.data_source, '') AS data_source,
                COALESCE(t.canonical_name, '') AS target_name,
                COALESCE(e.snippet, r.evidence, '') AS snippet
            FROM kg_claims c
            JOIN kg_entities t
                ON t.id = c.target_entity_id
            LEFT JOIN kg_evidence e
                ON e.claim_id = c.id
            LEFT JOIN kg_relationships r
                ON r.source_entity_id = c.source_entity_id
               AND r.target_entity_id = c.target_entity_id
               AND r.rel_type = c.rel_type
               AND COALESCE(r.data_source, '') = COALESCE(c.data_source, '')
            WHERE c.source_entity_id = ?
              AND COALESCE(c.data_source, '') = 'public_html_ownership'
              AND c.rel_type IN ('owned_by', 'beneficially_owned_by', 'backed_by')
            """,
            (source_entity_id,),
        ).fetchall()

        for row in rows:
            if not _should_retract(row["target_name"], row["snippet"]):
                continue
            conn.execute("DELETE FROM kg_evidence WHERE claim_id = ?", (row["id"],))
            conn.execute("DELETE FROM kg_claims WHERE id = ?", (row["id"],))
            deleted_claims += 1
            relationship_keys.add(
                (
                    str(row["source_entity_id"]),
                    str(row["target_entity_id"]),
                    str(row["rel_type"]),
                    str(row["data_source"] or ""),
                )
            )

        for source_id, target_id, rel_type, data_source in relationship_keys:
            remaining = conn.execute(
                """
                SELECT 1
                FROM kg_claims
                WHERE source_entity_id = ?
                  AND target_entity_id = ?
                  AND rel_type = ?
                  AND COALESCE(data_source, '') = ?
                LIMIT 1
                """,
                (source_id, target_id, rel_type, data_source),
            ).fetchone()
            if remaining:
                continue
            cursor = conn.execute(
                """
                DELETE FROM kg_relationships
                WHERE source_entity_id = ?
                  AND target_entity_id = ?
                  AND rel_type = ?
                  AND COALESCE(data_source, '') = ?
                """,
                (source_id, target_id, rel_type, data_source),
            )
            deleted_relationships += int(getattr(cursor, "rowcount", 0) or 0)

    return {
        "claims_deleted": deleted_claims,
        "relationships_deleted": deleted_relationships,
    }


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
                "aliases": _json_loads(row["aliases"], []),
                "identifiers": normalize_entity_identifiers(row["identifiers"])[0],
                "country": row["country"],
                "sources": normalize_entity_sources(row["sources"])[0],
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


def get_graph_snapshot_signature() -> str:
    """
    Return a cheap signature for invalidating cached analytics snapshots.

    The interrogation layer only needs to know whether the durable graph
    changed enough to justify reloading analytics. Counts plus latest
    timestamps give us that without paying for a full export.
    """
    with get_kg_conn() as conn:
        entity_stats = conn.execute(
            """
            SELECT
                COUNT(*) AS entity_count,
                MAX(last_updated) AS latest_entity_updated_at,
                MAX(created_at) AS latest_entity_created_at
            FROM kg_entities
            """
        ).fetchone()
        relationship_stats = conn.execute(
            """
            SELECT
                COUNT(*) AS relationship_count,
                MAX(created_at) AS latest_relationship_created_at
            FROM kg_relationships
            """
        ).fetchone()

    return _stable_hash(
        str(entity_stats["entity_count"] or 0),
        str(entity_stats["latest_entity_updated_at"] or ""),
        str(entity_stats["latest_entity_created_at"] or ""),
        str(relationship_stats["relationship_count"] or 0),
        str(relationship_stats["latest_relationship_created_at"] or ""),
        prefix="kgsnapshot",
    )



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
