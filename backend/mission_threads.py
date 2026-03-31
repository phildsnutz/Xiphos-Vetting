from __future__ import annotations

import logging
from collections import Counter
from typing import Any

import db

try:
    import knowledge_graph as kg
except ImportError:  # pragma: no cover - exercised in environments without KG
    kg = None

try:
    from graph_ingest import (
        _aggregate_graph_relationships,
        _hydrate_missing_graph_entities,
        _normalize_graph_entity_payload,
        annotate_graph_relationship_intelligence,
        build_graph_intelligence_summary,
        get_vendor_graph_summary,
    )
except ImportError:  # pragma: no cover - exercised in environments without graph stack
    _aggregate_graph_relationships = None
    _hydrate_missing_graph_entities = None
    _normalize_graph_entity_payload = None
    annotate_graph_relationship_intelligence = None
    build_graph_intelligence_summary = None
    get_vendor_graph_summary = None


logger = logging.getLogger(__name__)

DEFAULT_THREAD_STATUS = "draft"
DEFAULT_MEMBER_CRITICALITY = "supporting"
MAX_GRAPH_DEPTH = 4


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _normalize_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = _normalize_text(value).lower()
    return normalized in {"1", "true", "yes", "y", "on"}


def _row_to_thread(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "lane": row["lane"],
        "program": row["program"],
        "theater": row["theater"],
        "mission_type": row["mission_type"],
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _thread_member_count(thread_id: str) -> int:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM mission_thread_members WHERE mission_thread_id = ?",
            (thread_id,),
        ).fetchone()
    return int(row["count"] if row and "count" in row.keys() else 0)


def _entity_to_payload(entity) -> dict[str, Any] | None:
    if not entity:
        return None
    payload = {
        "id": entity.id,
        "canonical_name": entity.canonical_name,
        "entity_type": entity.entity_type,
        "aliases": list(entity.aliases or []),
        "identifiers": dict(entity.identifiers or {}),
        "country": entity.country or "",
        "sources": list(entity.sources or []),
        "confidence": entity.confidence,
        "last_updated": entity.last_updated,
    }
    if callable(_normalize_graph_entity_payload):
        return _normalize_graph_entity_payload(payload)
    return payload


def create_mission_thread(
    *,
    thread_id: str,
    name: str,
    created_by: str,
    description: str = "",
    lane: str = "",
    program: str = "",
    theater: str = "",
    mission_type: str = "",
    status: str = DEFAULT_THREAD_STATUS,
) -> dict[str, Any]:
    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO mission_threads
            (id, name, description, lane, program, theater, mission_type, status, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                thread_id,
                _normalize_text(name),
                _normalize_text(description),
                _normalize_text(lane),
                _normalize_text(program),
                _normalize_text(theater),
                _normalize_text(mission_type),
                _normalize_text(status) or DEFAULT_THREAD_STATUS,
                _normalize_text(created_by),
            ),
        )
    return get_mission_thread(thread_id) or {}


def get_mission_thread(thread_id: str, *, include_members: bool = True) -> dict[str, Any] | None:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM mission_threads WHERE id = ?",
            (thread_id,),
        ).fetchone()
    if not row:
        return None

    thread = _row_to_thread(row)
    thread["member_count"] = _thread_member_count(thread_id)
    if include_members:
        thread["members"] = list_mission_thread_members(thread_id)
    return thread


def list_mission_threads(*, created_by: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 500))
    with db.get_conn() as conn:
        if created_by:
            rows = conn.execute(
                "SELECT * FROM mission_threads WHERE created_by = ? ORDER BY updated_at DESC LIMIT ?",
                (_normalize_text(created_by), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mission_threads ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

    threads: list[dict[str, Any]] = []
    for row in rows:
        thread = _row_to_thread(row)
        thread["member_count"] = _thread_member_count(thread["id"])
        threads.append(thread)
    return threads


def _ensure_thread_exists(thread_id: str) -> None:
    if not get_mission_thread(thread_id, include_members=False):
        raise LookupError("Mission thread not found")


def _validate_member_targets(vendor_id: str, entity_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    vendor = None
    entity = None
    if not vendor_id and not entity_id:
        raise ValueError("vendor_id or entity_id is required")

    if vendor_id:
        vendor = db.get_vendor(vendor_id)
        if not vendor:
            raise LookupError("Vendor not found")

    if entity_id:
        if kg is None:
            raise LookupError("Knowledge graph module not available")
        kg.init_kg_db()
        entity = _entity_to_payload(kg.get_entity(entity_id))
        if not entity:
            raise LookupError("Entity not found")

    return vendor, entity


def add_mission_thread_member(
    thread_id: str,
    *,
    vendor_id: str = "",
    entity_id: str = "",
    role: str = "",
    criticality: str = DEFAULT_MEMBER_CRITICALITY,
    subsystem: str = "",
    site: str = "",
    is_alternate: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    _ensure_thread_exists(thread_id)

    vendor_id = _normalize_text(vendor_id)
    entity_id = _normalize_text(entity_id)
    role = _normalize_text(role)
    criticality = _normalize_text(criticality) or DEFAULT_MEMBER_CRITICALITY
    subsystem = _normalize_text(subsystem)
    site = _normalize_text(site)
    notes = _normalize_text(notes)
    vendor, entity = _validate_member_targets(vendor_id, entity_id)

    with db.get_conn() as conn:
        existing = conn.execute(
            """
            SELECT id FROM mission_thread_members
            WHERE mission_thread_id = ?
              AND COALESCE(vendor_id, '') = ?
              AND COALESCE(entity_id, '') = ?
              AND COALESCE(role, '') = ?
              AND COALESCE(subsystem, '') = ?
              AND COALESCE(site, '') = ?
            LIMIT 1
            """,
            (thread_id, vendor_id, entity_id, role, subsystem, site),
        ).fetchone()
        if existing:
            member_id = int(existing["id"])
        else:
            cursor = conn.execute(
                """
                INSERT INTO mission_thread_members
                (mission_thread_id, vendor_id, entity_id, role, criticality, subsystem, site, is_alternate, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    thread_id,
                    vendor_id or None,
                    entity_id or None,
                    role,
                    criticality,
                    subsystem,
                    site,
                    1 if _normalize_bool(is_alternate) else 0,
                    notes,
                ),
            )
            inserted = conn.execute(
                """
                SELECT id FROM mission_thread_members
                WHERE mission_thread_id = ?
                  AND COALESCE(vendor_id, '') = ?
                  AND COALESCE(entity_id, '') = ?
                  AND COALESCE(role, '') = ?
                  AND COALESCE(subsystem, '') = ?
                  AND COALESCE(site, '') = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (thread_id, vendor_id, entity_id, role, subsystem, site),
            ).fetchone()
            member_id = int(inserted["id"] if inserted and "id" in inserted.keys() else 0)

        if role:
            conn.execute(
                """
                INSERT INTO mission_thread_roles (mission_thread_id, role, description, created_at)
                VALUES (?, ?, '', datetime('now'))
                ON CONFLICT(mission_thread_id, role) DO NOTHING
                """,
                (thread_id, role),
            )

        conn.execute(
            "UPDATE mission_threads SET updated_at = datetime('now') WHERE id = ?",
            (thread_id,),
        )

    member = get_mission_thread_member(member_id)
    if member is None:
        raise RuntimeError("Mission thread member was not persisted")
    if vendor is not None and not member.get("vendor"):
        member["vendor"] = {
            "id": vendor["id"],
            "name": vendor["name"],
            "country": vendor["country"],
            "program": vendor["program"],
            "profile": vendor["profile"],
        }
    if entity is not None and not member.get("entity"):
        member["entity"] = entity
    return member


def get_mission_thread_member(member_id: int) -> dict[str, Any] | None:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM mission_thread_members WHERE id = ?",
            (member_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_member(row)


def _row_to_member(row) -> dict[str, Any]:
    member = {
        "id": row["id"],
        "mission_thread_id": row["mission_thread_id"],
        "vendor_id": row["vendor_id"] or "",
        "entity_id": row["entity_id"] or "",
        "role": row["role"] or "",
        "criticality": row["criticality"] or DEFAULT_MEMBER_CRITICALITY,
        "subsystem": row["subsystem"] or "",
        "site": row["site"] or "",
        "is_alternate": bool(row["is_alternate"]),
        "notes": row["notes"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "vendor": None,
        "entity": None,
        "latest_score": None,
    }

    vendor_id = member["vendor_id"]
    if vendor_id:
        vendor = db.get_vendor(vendor_id)
        if vendor:
            member["vendor"] = {
                "id": vendor["id"],
                "name": vendor["name"],
                "country": vendor["country"],
                "program": vendor["program"],
                "profile": vendor["profile"],
            }
            latest_score = db.get_latest_score(vendor_id)
            if latest_score:
                calibrated = latest_score.get("calibrated") if isinstance(latest_score, dict) else {}
                member["latest_score"] = {
                    "composite_score": latest_score.get("composite_score"),
                    "calibrated_tier": ((calibrated or {}).get("calibrated_tier") or ""),
                    "display_tier": ((calibrated or {}).get("display_tier") or ""),
                }

    entity_id = member["entity_id"]
    if entity_id and kg is not None:
        try:
            kg.init_kg_db()
            member["entity"] = _entity_to_payload(kg.get_entity(entity_id))
        except Exception as exc:  # pragma: no cover - defensive on live DB drift
            logger.debug("Mission thread entity hydration failed for %s: %s", entity_id, exc)

    return member


def list_mission_thread_members(thread_id: str) -> list[dict[str, Any]]:
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM mission_thread_members
            WHERE mission_thread_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (thread_id,),
        ).fetchall()
    return [_row_to_member(row) for row in rows]


def build_mission_thread_graph(
    thread_id: str,
    *,
    depth: int = 2,
    include_provenance: bool = True,
    max_claim_records: int = 4,
    max_evidence_records: int = 4,
) -> dict[str, Any] | None:
    thread = get_mission_thread(thread_id, include_members=False)
    if not thread:
        return None

    depth = max(1, min(int(depth or 2), MAX_GRAPH_DEPTH))
    members = list_mission_thread_members(thread_id)
    member_vendor_ids = sorted({member["vendor_id"] for member in members if member.get("vendor_id")})
    member_entity_ids = sorted({member["entity_id"] for member in members if member.get("entity_id")})

    all_entities: dict[str, dict[str, Any]] = {}
    all_relationships: list[dict[str, Any]] = []
    root_entity_ids: list[str] = []

    if callable(get_vendor_graph_summary):
        for vendor_id in member_vendor_ids:
            vendor_graph = get_vendor_graph_summary(
                vendor_id,
                depth=depth,
                include_provenance=include_provenance,
                max_claim_records=max_claim_records,
                max_evidence_records=max_evidence_records,
            )
            if not isinstance(vendor_graph, dict) or vendor_graph.get("error"):
                continue
            for entity in vendor_graph.get("entities", []) or []:
                entity_id = str((entity or {}).get("id") or "")
                if entity_id:
                    normalized = (
                        _normalize_graph_entity_payload(entity)
                        if callable(_normalize_graph_entity_payload)
                        else dict(entity)
                    )
                    all_entities[entity_id] = normalized
            all_relationships.extend(list(vendor_graph.get("relationships", []) or []))
            for root_id in vendor_graph.get("root_entity_ids", []) or []:
                if root_id:
                    root_entity_ids.append(str(root_id))

    if kg is not None:
        try:
            kg.init_kg_db()
            for entity_id in member_entity_ids:
                network = kg.get_entity_network(
                    entity_id,
                    depth=depth,
                    include_provenance=include_provenance,
                    max_claim_records=max_claim_records,
                    max_evidence_records=max_evidence_records,
                )
                for hydrated_entity in (network.get("entities", {}) or {}).values():
                    hydrated_entity_id = str((hydrated_entity or {}).get("id") or "")
                    if hydrated_entity_id:
                        normalized = (
                            _normalize_graph_entity_payload(hydrated_entity)
                            if callable(_normalize_graph_entity_payload)
                            else dict(hydrated_entity)
                        )
                        all_entities[hydrated_entity_id] = normalized
                all_relationships.extend(list(network.get("relationships", []) or []))
                root_entity_ids.append(entity_id)
        except Exception as exc:  # pragma: no cover - defensive on live DB drift
            logger.warning("Mission thread graph assembly failed for explicit entities on %s: %s", thread_id, exc)

    unique_root_ids: list[str] = []
    seen_root_ids: set[str] = set()
    for root_id in root_entity_ids:
        normalized_root_id = _normalize_text(root_id)
        if normalized_root_id and normalized_root_id not in seen_root_ids:
            seen_root_ids.add(normalized_root_id)
            unique_root_ids.append(normalized_root_id)

    unique_relationships = (
        _aggregate_graph_relationships(all_relationships)
        if callable(_aggregate_graph_relationships)
        else [dict(rel) for rel in all_relationships]
    )
    if not include_provenance:
        for relationship in unique_relationships:
            relationship["claim_records"] = []
    if callable(annotate_graph_relationship_intelligence):
        unique_relationships = annotate_graph_relationship_intelligence(unique_relationships)

    if kg is not None and callable(_hydrate_missing_graph_entities):
        all_entities = _hydrate_missing_graph_entities(kg, all_entities, unique_relationships)

    entity_type_distribution = dict(
        Counter(
            str(entity.get("entity_type") or "unknown")
            for entity in all_entities.values()
        )
    )
    relationship_type_distribution = dict(
        Counter(
            str(relationship.get("rel_type") or "unknown")
            for relationship in unique_relationships
        )
    )

    graph_payload = {
        "mission_thread_id": thread_id,
        "thread": {
            "id": thread["id"],
            "name": thread["name"],
            "lane": thread["lane"],
            "program": thread["program"],
            "theater": thread["theater"],
            "mission_type": thread["mission_type"],
            "status": thread["status"],
        },
        "member_count": len(members),
        "vendor_member_count": len(member_vendor_ids),
        "entity_member_count": len(member_entity_ids),
        "vendor_ids": member_vendor_ids,
        "member_entity_ids": member_entity_ids,
        "root_entity_id": unique_root_ids[0] if unique_root_ids else None,
        "root_entity_ids": unique_root_ids,
        "graph_depth": depth,
        "entity_count": len(all_entities),
        "relationship_count": len(unique_relationships),
        "entity_type_distribution": entity_type_distribution,
        "relationship_type_distribution": relationship_type_distribution,
        "entities": list(all_entities.values()),
        "relationships": unique_relationships,
    }
    if callable(build_graph_intelligence_summary):
        graph_payload["intelligence"] = build_graph_intelligence_summary(
            graph_payload,
            workflow_lane=thread.get("lane"),
        )
    else:
        graph_payload["intelligence"] = {}
    return graph_payload


def build_mission_thread_summary(thread_id: str, *, depth: int = 2) -> dict[str, Any] | None:
    thread = get_mission_thread(thread_id, include_members=True)
    if not thread:
        return None

    members = list(thread.get("members") or [])
    graph = build_mission_thread_graph(thread_id, depth=depth, include_provenance=False) or {}
    role_distribution = dict(
        Counter(
            str(member.get("role") or "unassigned")
            for member in members
        )
    )
    criticality_distribution = dict(
        Counter(
            str(member.get("criticality") or DEFAULT_MEMBER_CRITICALITY)
            for member in members
        )
    )
    tier_distribution = dict(
        Counter(
            str(((member.get("latest_score") or {}).get("calibrated_tier") or "unscored"))
            for member in members
            if member.get("vendor_id")
        )
    )

    return {
        "mission_thread": {
            key: value
            for key, value in thread.items()
            if key != "members"
        },
        "member_count": len(members),
        "vendor_member_count": len([member for member in members if member.get("vendor_id")]),
        "entity_member_count": len([member for member in members if member.get("entity_id")]),
        "alternate_member_count": len([member for member in members if member.get("is_alternate")]),
        "role_distribution": role_distribution,
        "criticality_distribution": criticality_distribution,
        "tier_distribution": tier_distribution,
        "members": members,
        "graph": {
            "entity_count": int(graph.get("entity_count") or 0),
            "relationship_count": int(graph.get("relationship_count") or 0),
            "root_entity_ids": list(graph.get("root_entity_ids") or []),
            "entity_type_distribution": dict(graph.get("entity_type_distribution") or {}),
            "relationship_type_distribution": dict(graph.get("relationship_type_distribution") or {}),
            "intelligence": dict(graph.get("intelligence") or {}),
        },
    }
