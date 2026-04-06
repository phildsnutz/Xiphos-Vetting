from __future__ import annotations

import json
from typing import Any

import db
from helios_core.room_contract import (
    DEFAULT_MISSION_BRIEF_ROOM,
    canonicalize_mission_brief_room,
    mission_brief_room_sql,
)


_MISSION_BRIEF_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mission_briefs (
    id TEXT PRIMARY KEY,
    room TEXT NOT NULL DEFAULT 'stoa',
    case_id TEXT REFERENCES vendors(id),
    object_type TEXT,
    engagement_type TEXT,
    collection_depth TEXT NOT NULL DEFAULT 'full_picture',
    timeline TEXT,
    status TEXT NOT NULL DEFAULT 'scoped',
    question_count INTEGER NOT NULL DEFAULT 0,
    confidence_score REAL NOT NULL DEFAULT 0,
    primary_targets TEXT NOT NULL DEFAULT '{}',
    known_context TEXT NOT NULL DEFAULT '{}',
    priority_requirements TEXT NOT NULL DEFAULT '[]',
    authorized_tiers TEXT NOT NULL DEFAULT '[]',
    summary TEXT,
    notes TEXT NOT NULL DEFAULT '[]',
    created_by TEXT,
    created_by_email TEXT,
    created_by_role TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mission_briefs_case ON mission_briefs(case_id);
CREATE INDEX IF NOT EXISTS idx_mission_briefs_room ON mission_briefs(room);
CREATE INDEX IF NOT EXISTS idx_mission_briefs_updated ON mission_briefs(updated_at);
"""


def _safe_json_loads(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _row_to_mission_brief(row) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "room": canonicalize_mission_brief_room(row["room"]),
        "case_id": row["case_id"],
        "object_type": row["object_type"],
        "engagement_type": row["engagement_type"],
        "collection_depth": row["collection_depth"],
        "timeline": row["timeline"],
        "status": row["status"],
        "question_count": int(row["question_count"] or 0),
        "confidence_score": float(row["confidence_score"] or 0.0),
        "primary_targets": _safe_json_loads(row["primary_targets"]) or {},
        "known_context": _safe_json_loads(row["known_context"]) or {},
        "priority_requirements": _safe_json_loads(row["priority_requirements"]) or [],
        "authorized_tiers": _safe_json_loads(row["authorized_tiers"]) or [],
        "summary": row["summary"],
        "notes": _safe_json_loads(row["notes"]) or [],
        "created_by": row["created_by"],
        "created_by_email": row["created_by_email"],
        "created_by_role": row["created_by_role"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def ensure_schema() -> None:
    with db.get_conn() as conn:
        conn.executescript(_MISSION_BRIEF_SCHEMA_SQL)
        conn.execute(f"UPDATE mission_briefs SET room = {mission_brief_room_sql('room')}")


def create_or_update_mission_brief(
    brief_id: str,
    *,
    room: str = DEFAULT_MISSION_BRIEF_ROOM,
    case_id: str | None = None,
    object_type: str | None = None,
    engagement_type: str | None = None,
    collection_depth: str = "full_picture",
    timeline: str | None = None,
    status: str = "scoped",
    question_count: int = 0,
    confidence_score: float = 0.0,
    primary_targets: dict[str, Any] | None = None,
    known_context: dict[str, Any] | None = None,
    priority_requirements: list[str] | None = None,
    authorized_tiers: list[str] | None = None,
    summary: str | None = None,
    notes: list[str] | None = None,
    created_by: str = "",
    created_by_email: str = "",
    created_by_role: str = "",
) -> dict[str, Any]:
    ensure_schema()
    canonical_room = canonicalize_mission_brief_room(room)
    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO mission_briefs (
                id,
                room,
                case_id,
                object_type,
                engagement_type,
                collection_depth,
                timeline,
                status,
                question_count,
                confidence_score,
                primary_targets,
                known_context,
                priority_requirements,
                authorized_tiers,
                summary,
                notes,
                created_by,
                created_by_email,
                created_by_role,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                room = excluded.room,
                case_id = COALESCE(excluded.case_id, mission_briefs.case_id),
                object_type = COALESCE(excluded.object_type, mission_briefs.object_type),
                engagement_type = COALESCE(excluded.engagement_type, mission_briefs.engagement_type),
                collection_depth = excluded.collection_depth,
                timeline = COALESCE(excluded.timeline, mission_briefs.timeline),
                status = excluded.status,
                question_count = excluded.question_count,
                confidence_score = excluded.confidence_score,
                primary_targets = excluded.primary_targets,
                known_context = excluded.known_context,
                priority_requirements = excluded.priority_requirements,
                authorized_tiers = excluded.authorized_tiers,
                summary = COALESCE(excluded.summary, mission_briefs.summary),
                notes = excluded.notes,
                created_by = CASE
                    WHEN COALESCE(mission_briefs.created_by, '') = '' THEN excluded.created_by
                    ELSE mission_briefs.created_by
                END,
                created_by_email = CASE
                    WHEN COALESCE(mission_briefs.created_by_email, '') = '' THEN excluded.created_by_email
                    ELSE mission_briefs.created_by_email
                END,
                created_by_role = CASE
                    WHEN COALESCE(mission_briefs.created_by_role, '') = '' THEN excluded.created_by_role
                    ELSE mission_briefs.created_by_role
                END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                brief_id,
                canonical_room,
                case_id,
                object_type,
                engagement_type,
                collection_depth,
                timeline,
                status,
                int(question_count or 0),
                float(confidence_score or 0.0),
                json.dumps(primary_targets or {}),
                json.dumps(known_context or {}),
                json.dumps(priority_requirements or []),
                json.dumps(authorized_tiers or []),
                summary,
                json.dumps(notes or []),
                created_by,
                created_by_email,
                created_by_role,
            ),
        )
        row = conn.execute("SELECT * FROM mission_briefs WHERE id = ?", (brief_id,)).fetchone()
    return _row_to_mission_brief(row) or {"id": brief_id}


def get_mission_brief(brief_id: str) -> dict[str, Any] | None:
    ensure_schema()
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM mission_briefs WHERE id = ?", (brief_id,)).fetchone()
    return _row_to_mission_brief(row)
