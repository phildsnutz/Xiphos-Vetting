from __future__ import annotations

from datetime import datetime
from typing import Any

import mission_threads
from resilience_scoring import CONTROL_PATH_REL_TYPES


BRIEFING_VERSION = "mission-thread-briefing-v1"
DEFAULT_MEMBER_PASSPORT_MODE = "control"


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _member_label(row: dict[str, Any]) -> str:
    return _normalize_text(row.get("label") or row.get("entity_name") or row.get("vendor_name") or row.get("member_label"))


def _entity_label(entity: dict[str, Any]) -> str:
    return _normalize_text(entity.get("canonical_name") or entity.get("entity_name") or entity.get("id"))


def _ranked_brittle_members(summary: dict[str, Any]) -> list[dict[str, Any]]:
    resilience = dict((summary.get("resilience") or {}).get("summary") or {})
    if resilience.get("top_brittle_members"):
        return list(resilience.get("top_brittle_members") or [])
    member_scores = list((summary.get("resilience") or {}).get("member_scores") or [])
    member_scores.sort(key=lambda row: _safe_float(row.get("brittle_node_score")), reverse=True)
    return member_scores[:5]


def _control_path_exposures(graph: dict[str, Any]) -> list[dict[str, Any]]:
    entity_index = {
        str(entity.get("id") or ""): dict(entity)
        for entity in (graph.get("entities") or [])
        if str(entity.get("id") or "")
    }
    node_metrics = dict((graph.get("analytics") or {}).get("node_metrics") or {})
    exposures: list[dict[str, Any]] = []

    for relationship in graph.get("relationships") or []:
        rel_type = _normalize_text(relationship.get("rel_type")).lower()
        if rel_type not in CONTROL_PATH_REL_TYPES and rel_type != "single_point_of_failure_for":
            continue

        source_id = _normalize_text(relationship.get("source_entity_id") or relationship.get("source"))
        target_id = _normalize_text(relationship.get("target_entity_id") or relationship.get("target"))
        source_entity = entity_index.get(source_id, {})
        target_entity = entity_index.get(target_id, {})
        source_metrics = node_metrics.get(source_id, {})
        target_metrics = node_metrics.get(target_id, {})
        mission_importance = max(
            _safe_float(source_metrics.get("mission_importance")),
            _safe_float(target_metrics.get("mission_importance")),
        )
        exposures.append(
            {
                "rel_type": rel_type,
                "source_entity_id": source_id,
                "target_entity_id": target_id,
                "source_label": _entity_label(source_entity) or source_id,
                "target_label": _entity_label(target_entity) or target_id,
                "intelligence_score": round(
                    _safe_float(relationship.get("intelligence_score"), _safe_float(relationship.get("confidence"))),
                    4,
                ),
                "mission_importance": round(mission_importance, 4),
                "evidence": _normalize_text(relationship.get("evidence")),
                "vendor_id": _normalize_text(relationship.get("vendor_id")),
            }
        )

    exposures.sort(
        key=lambda row: (
            _safe_float(row.get("mission_importance")),
            _safe_float(row.get("intelligence_score")),
        ),
        reverse=True,
    )
    return exposures[:8]


def _unresolved_evidence_gaps(
    *,
    graph: dict[str, Any],
    brittle_members: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    intelligence = dict(graph.get("intelligence") or {})
    rel_dist = dict(graph.get("relationship_type_distribution") or {})

    if bool(intelligence.get("thin_graph")):
        gaps.append(
            {
                "category": "graph_depth",
                "severity": "high",
                "detail": "Mission-thread graph is still thin. Expand supplier, site, and subsystem evidence before trusting resilience posture.",
            }
        )
    if int(rel_dist.get("substitutable_with") or 0) == 0:
        gaps.append(
            {
                "category": "alternate_coverage",
                "severity": "high",
                "detail": "No explicit substitute relationships are recorded for the thread.",
            }
        )
    if int(intelligence.get("intermediary_edge_count") or 0) == 0:
        gaps.append(
            {
                "category": "intermediary_visibility",
                "severity": "medium",
                "detail": "No service, network, or payment intermediary edges are visible in the thread graph.",
            }
        )

    for member in brittle_members[:3]:
        if _safe_float(member.get("brittle_node_score")) < 0.5:
            continue
        if _safe_float(member.get("substitute_coverage_score")) > 0.0:
            continue
        gaps.append(
            {
                "category": "member_alternate_gap",
                "severity": "high" if _normalize_text(member.get("criticality")).lower() in {"critical", "mission_critical"} else "medium",
                "member_id": member.get("member_id"),
                "detail": f"{_member_label(member)} has brittle concentration without an alternate recorded in the thread.",
            }
        )

    deduped: list[dict[str, Any]] = []
    seen = set()
    for gap in gaps:
        key = (gap.get("category"), gap.get("detail"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(gap)
    return deduped[:6]


def _recommended_mitigations(
    *,
    brittle_members: list[dict[str, Any]],
    evidence_gaps: list[dict[str, Any]],
) -> list[str]:
    mitigations: list[str] = []
    for member in brittle_members[:5]:
        action = _normalize_text(member.get("recommended_action"))
        if action:
            mitigations.append(action)

    gap_categories = {gap.get("category") for gap in evidence_gaps}
    if "intermediary_visibility" in gap_categories:
        mitigations.append("Resolve bank-route, service, and network intermediaries for the mission-critical members before operational review.")
    if "alternate_coverage" in gap_categories:
        mitigations.append("Record approved substitutes for mission-critical roles so the thread can distinguish resilient coverage from concentration risk.")
    if "graph_depth" in gap_categories:
        mitigations.append("Expand site, subsystem, and sustainment evidence before using the thread for planning decisions.")

    ordered: list[str] = []
    seen = set()
    for mitigation in mitigations:
        normalized = _normalize_text(mitigation)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered[:6]


def _member_briefs(
    thread_id: str,
    brittle_members: list[dict[str, Any]],
    *,
    depth: int,
    member_passport_mode: str,
) -> list[dict[str, Any]]:
    briefs: list[dict[str, Any]] = []
    for row in brittle_members[:3]:
        member_id = int(row.get("member_id") or 0)
        if member_id <= 0:
            continue
        passport = mission_threads.build_mission_thread_member_passport(
            thread_id,
            member_id,
            depth=depth,
            mode=member_passport_mode,
        )
        if passport:
            briefs.append(passport)
    return briefs


def _operator_readout(
    *,
    thread: dict[str, Any],
    brittle_members: list[dict[str, Any]],
    evidence_gaps: list[dict[str, Any]],
) -> str:
    thread_name = _normalize_text(((thread.get("mission_thread") or {}).get("name")) or (thread.get("name")))
    if brittle_members:
        lead = _member_label(brittle_members[0])
        return f"{thread_name} is currently constrained by {lead} with {len(evidence_gaps)} active evidence gap(s) requiring follow-up."
    return f"{thread_name} is seeded but does not yet have ranked brittle members."


def build_mission_thread_briefing(
    thread_id: str,
    *,
    depth: int = 2,
    member_passport_mode: str = DEFAULT_MEMBER_PASSPORT_MODE,
) -> dict[str, Any] | None:
    summary = mission_threads.build_mission_thread_summary(thread_id, depth=depth)
    if not summary:
        return None
    graph = mission_threads.build_mission_thread_graph(thread_id, depth=depth, include_provenance=False) or {}

    brittle_members = _ranked_brittle_members(summary)
    control_exposures = _control_path_exposures(graph)
    evidence_gaps = _unresolved_evidence_gaps(graph=graph, brittle_members=brittle_members)
    mitigations = _recommended_mitigations(brittle_members=brittle_members, evidence_gaps=evidence_gaps)
    member_briefs = _member_briefs(
        thread_id,
        brittle_members,
        depth=depth,
        member_passport_mode=member_passport_mode,
    )

    return {
        "briefing_version": BRIEFING_VERSION,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "mission_thread": dict(summary.get("mission_thread") or {}),
        "operator_readout": _operator_readout(
            thread=summary,
            brittle_members=brittle_members,
            evidence_gaps=evidence_gaps,
        ),
        "overview": {
            "member_count": int(summary.get("member_count") or 0),
            "vendor_member_count": int(summary.get("vendor_member_count") or 0),
            "entity_member_count": int(summary.get("entity_member_count") or 0),
            "alternate_member_count": int(summary.get("alternate_member_count") or 0),
            "entity_count": int((summary.get("graph") or {}).get("entity_count") or 0),
            "relationship_count": int((summary.get("graph") or {}).get("relationship_count") or 0),
            "resilience_summary": dict((summary.get("resilience") or {}).get("summary") or {}),
        },
        "top_brittle_members": brittle_members,
        "top_control_path_exposures": control_exposures,
        "mission_important_nodes": list(((summary.get("graph") or {}).get("top_nodes_by_mission_importance") or []))[:8],
        "unresolved_evidence_gaps": evidence_gaps,
        "recommended_mitigations": mitigations,
        "member_briefs": member_briefs,
    }
