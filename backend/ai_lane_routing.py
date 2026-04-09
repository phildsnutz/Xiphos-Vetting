"""Lane-based AI runtime doctrine for Helios."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_LANE_POLICIES: dict[str, dict[str, Any]] = {
    "mission_command": {
        "label": "Mission Command",
        "intent": "Fast quarterback reads, preflight calls, and operator-facing field awareness.",
        "primary": {"config_id": "__org_default__", "provider": "anthropic", "model": "claude-sonnet-4-6"},
        "backups": [
            {"config_id": "__anthropic_backup__", "provider": "anthropic", "model": "claude-sonnet-4-6"},
            {"config_id": "__openai_backup__", "provider": "openai", "model": "gpt-4o"},
        ],
    },
    "edge_collection": {
        "label": "Edge Collection",
        "intent": "Cheap, fast collection pivots, extraction support, and iterative discovery loops.",
        "primary": {"config_id": "__org_default__", "provider": "anthropic", "model": "claude-sonnet-4-6"},
        "backups": [
            {"config_id": "__anthropic_backup__", "provider": "anthropic", "model": "claude-sonnet-4-6"},
            {"config_id": "__openai_backup__", "provider": "openai", "model": "gpt-4o"},
        ],
    },
    "adverse_case_adjudication": {
        "label": "Adverse Case Adjudication",
        "intent": "Hard judgment, contradiction handling, hidden-control pressure, and stop-case reasoning.",
        "primary": {"config_id": "__org_default__", "provider": "anthropic", "model": "claude-sonnet-4-6"},
        "backups": [
            {"config_id": "__anthropic_backup__", "provider": "anthropic", "model": "claude-sonnet-4-6"},
            {"config_id": "__openai_backup__", "provider": "openai", "model": "gpt-4o"},
        ],
    },
    "artifact_finish": {
        "label": "Artifact Finish",
        "intent": "Decision theses, dossier narrative, and client-facing analytical packaging.",
        "primary": {"config_id": "__org_default__", "provider": "anthropic", "model": "claude-sonnet-4-6"},
        "backups": [
            {"config_id": "__anthropic_backup__", "provider": "anthropic", "model": "claude-sonnet-4-6"},
            {"config_id": "__openai_backup__", "provider": "openai", "model": "gpt-4o"},
        ],
    },
    "balanced_analysis": {
        "label": "Balanced Analysis",
        "intent": "Default analytical work when the case does not justify a more specialized lane.",
        "primary": {"config_id": "__org_default__", "provider": "anthropic", "model": "claude-sonnet-4-6"},
        "backups": [
            {"config_id": "__anthropic_backup__", "provider": "anthropic", "model": "claude-sonnet-4-6"},
            {"config_id": "__openai_backup__", "provider": "openai", "model": "gpt-4o"},
        ],
    },
}

_PACK_POLICY: dict[str, dict[str, str]] = {
    "vesper": {"lane_id": "mission_command", "training_focus": "Clock management, preflight discipline, audibles, and bounded autonomy."},
    "mako": {"lane_id": "edge_collection", "training_focus": "High-signal collection pressure, quick pivots, and evidence expansion without drift."},
    "bruno": {"lane_id": "adverse_case_adjudication", "training_focus": "Contradiction pressure, hidden-control skepticism, and stop-case discipline."},
    "sable": {"lane_id": "artifact_finish", "training_focus": "Sharper openings, analyst-grade narrative, and disciplined packaging."},
    "rex": {"lane_id": "balanced_analysis", "training_focus": "Stable fallback coverage when the case needs breadth more than specialization."},
}

_OBJECTIVE_TO_LANE: dict[str, str] = {
    "trace_control_path": "adverse_case_adjudication",
    "export_review": "adverse_case_adjudication",
    "cyber_investigation": "adverse_case_adjudication",
    "data_repair": "edge_collection",
    "executive_brief": "artifact_finish",
    "monitor_change": "mission_command",
    "explain_decision": "balanced_analysis",
}

_SURFACE_TO_LANE: dict[str, str] = {
    "vendor_analysis": "artifact_finish",
    "dossier_generation": "artifact_finish",
    "control_plane": "mission_command",
    "axiom_search": "mission_command",
    "axiom_extract": "edge_collection",
    "comparative_vehicle_intel": "adverse_case_adjudication",
}


def get_lane_policy(lane_id: str) -> dict[str, Any]:
    normalized = str(lane_id or "").strip() or "balanced_analysis"
    policy = _LANE_POLICIES.get(normalized) or _LANE_POLICIES["balanced_analysis"]
    data = deepcopy(policy)
    data["lane_id"] = normalized if normalized in _LANE_POLICIES else "balanced_analysis"
    return data


def lane_for_objective(objective: str) -> str:
    normalized = str(objective or "").strip().lower()
    return _OBJECTIVE_TO_LANE.get(normalized, "balanced_analysis")


def lane_for_surface(surface: str, objective: str = "") -> str:
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface in _SURFACE_TO_LANE:
        return _SURFACE_TO_LANE[normalized_surface]
    return lane_for_objective(objective)


def get_pack_runtime_profile(pack_id: str) -> dict[str, Any]:
    normalized = str(pack_id or "").strip().lower()
    pack_policy = _PACK_POLICY.get(normalized) or _PACK_POLICY["rex"]
    lane_id = str(pack_policy.get("lane_id") or "balanced_analysis")
    lane_policy = get_lane_policy(lane_id)
    primary = dict(lane_policy.get("primary") or {})
    backups = [dict(item) for item in (lane_policy.get("backups") or []) if isinstance(item, dict)]
    return {
        "lane_id": lane_id,
        "lane_label": lane_policy.get("label"),
        "intent": lane_policy.get("intent"),
        "training_focus": pack_policy.get("training_focus"),
        "primary_provider": primary.get("provider", ""),
        "primary_model": primary.get("model", ""),
        "primary_config_id": primary.get("config_id", ""),
        "backup_provider": str((backups[0] if backups else {}).get("provider") or ""),
        "backup_model": str((backups[0] if backups else {}).get("model") or ""),
        "backup_config_id": str((backups[0] if backups else {}).get("config_id") or ""),
        "fallback_chain": backups,
    }


def build_runtime_chain_for_lane(lane_id: str) -> list[dict[str, str]]:
    policy = get_lane_policy(lane_id)
    primary = dict(policy.get("primary") or {})
    backups = [dict(item) for item in (policy.get("backups") or []) if isinstance(item, dict)]
    return [primary, *backups]
