from __future__ import annotations

from typing import Final


DEFAULT_MISSION_BRIEF_ROOM: Final = "stoa"
MISSION_BRIEF_ROOMS: Final = ("stoa", "aegis")
MISSION_BRIEF_ROOM_ALIASES: Final[dict[str, str]] = {
    "stoa": "stoa",
    "front_porch": "stoa",
    "aegis": "aegis",
    "war_room": "aegis",
}


def canonicalize_mission_brief_room(
    value: str | None,
    *,
    default: str = DEFAULT_MISSION_BRIEF_ROOM,
) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    normalized = "_".join(raw.split())
    return MISSION_BRIEF_ROOM_ALIASES.get(normalized, default)


def mission_brief_room_sql(column_name: str = "room") -> str:
    return f"""
    CASE lower(replace(trim(COALESCE({column_name}, '')), ' ', '_'))
        WHEN 'war_room' THEN 'aegis'
        WHEN 'aegis' THEN 'aegis'
        WHEN 'front_porch' THEN 'stoa'
        WHEN 'stoa' THEN 'stoa'
        ELSE 'stoa'
    END
    """.strip()
