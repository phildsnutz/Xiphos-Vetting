from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from graph_analytics import GraphAnalytics
from graph_ingest import (
    REL_BACKED_BY,
    REL_BENEFICIALLY_OWNED_BY,
    REL_DEPENDS_ON_NETWORK,
    REL_DEPENDS_ON_SERVICE,
    REL_DISTRIBUTED_BY,
    REL_OPERATES_FACILITY,
    REL_OWNED_BY,
    REL_ROUTES_PAYMENT_THROUGH,
    REL_SHIPS_VIA,
    REL_SINGLE_POINT_OF_FAILURE_FOR,
    REL_SUBSTITUTABLE_WITH,
    annotate_graph_relationship_intelligence,
)


CONTROL_PATH_REL_TYPES = {
    REL_OWNED_BY,
    REL_BENEFICIALLY_OWNED_BY,
    REL_BACKED_BY,
    REL_DEPENDS_ON_NETWORK,
    REL_DEPENDS_ON_SERVICE,
    REL_ROUTES_PAYMENT_THROUGH,
    REL_DISTRIBUTED_BY,
    REL_OPERATES_FACILITY,
    REL_SHIPS_VIA,
}

CRITICALITY_ORDER = (
    "supporting",
    "important",
    "high",
    "critical",
    "mission_critical",
)
CRITICALITY_INDEX = {label: idx for idx, label in enumerate(CRITICALITY_ORDER)}


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _safe_prob(value: object, *, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(numeric, 1.0))


def _criticality_score(label: object) -> float:
    normalized = _normalize_text(label).lower().replace(" ", "_")
    if normalized in {"primary", "essential"}:
        normalized = "high"
    if normalized not in CRITICALITY_INDEX:
        normalized = "supporting"
    return round((CRITICALITY_INDEX[normalized] + 1) / len(CRITICALITY_ORDER), 4)


def _geometric_mean(values: list[float]) -> float:
    safe = [max(_safe_prob(value), 1e-6) for value in values if value is not None]
    if not safe:
        return 0.0
    return math.prod(safe) ** (1.0 / len(safe))


def _context_key(member: dict[str, Any]) -> tuple[str, str, str]:
    subsystem = _normalize_text(member.get("subsystem")).lower()
    site = _normalize_text(member.get("site")).lower()
    role = _normalize_text(member.get("role")).lower()
    return subsystem, site, role


def _build_thread_analytics(graph: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    analytics = GraphAnalytics()
    analytics.nodes = {
        str(entity.get("id") or ""): dict(entity)
        for entity in (graph.get("entities") or [])
        if str(entity.get("id") or "")
    }
    raw_edges = [
        dict(edge)
        for edge in (graph.get("relationships") or [])
        if str(edge.get("source_entity_id") or "") and str(edge.get("target_entity_id") or "")
    ]
    analytics.edges = annotate_graph_relationship_intelligence(raw_edges)
    analytics.adj = defaultdict(list)
    for idx, edge in enumerate(analytics.edges):
        src = str(edge.get("source") or edge.get("source_entity_id") or "")
        tgt = str(edge.get("target") or edge.get("target_entity_id") or "")
        if not src or not tgt or src not in analytics.nodes or tgt not in analytics.nodes:
            continue
        analytics.edges[idx]["source"] = src
        analytics.edges[idx]["target"] = tgt
        analytics.adj[src].append((tgt, idx))
        analytics.adj[tgt].append((src, idx))
    analytics.loaded = True
    return analytics.compute_all_centrality(), analytics.edges


def _node_touching_edge_metrics(
    node_ids: list[str],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    node_set = {node_id for node_id in node_ids if node_id}
    control_scores: list[float] = []
    spof_scores: list[float] = []
    substitute_hits = 0
    touched_types: Counter[str] = Counter()

    for edge in edges:
        src = str(edge.get("source") or edge.get("source_entity_id") or "")
        tgt = str(edge.get("target") or edge.get("target_entity_id") or "")
        if src not in node_set and tgt not in node_set:
            continue
        rel_type = _normalize_text(edge.get("rel_type")).lower()
        touched_types[rel_type] += 1
        intelligence = _safe_prob(edge.get("intelligence_score"), default=_safe_prob(edge.get("confidence")))
        if rel_type in CONTROL_PATH_REL_TYPES:
            control_scores.append(intelligence)
        if rel_type == REL_SINGLE_POINT_OF_FAILURE_FOR:
            spof_scores.append(intelligence)
        if rel_type == REL_SUBSTITUTABLE_WITH:
            substitute_hits += 1

    return {
        "control_path_quality": round(sum(control_scores) / len(control_scores), 4) if control_scores else 0.0,
        "single_point_of_failure_signal": round(max(spof_scores), 4) if spof_scores else 0.0,
        "explicit_substitute_hits": substitute_hits,
        "touched_relationship_types": dict(touched_types),
    }


def compute_mission_thread_resilience(
    *,
    thread: dict[str, Any],
    members: list[dict[str, Any]],
    graph: dict[str, Any],
) -> dict[str, Any]:
    centrality, edges = _build_thread_analytics(graph)
    member_focus_map = {
        str(member_id): [str(node_id) for node_id in node_ids if str(node_id)]
        for member_id, node_ids in (graph.get("member_focus_node_ids") or {}).items()
    }
    graph_entities = {
        str(entity.get("id") or ""): dict(entity)
        for entity in (graph.get("entities") or [])
        if str(entity.get("id") or "")
    }

    criticality_by_member: dict[str, float] = {}
    member_contexts: defaultdict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    node_criticality: defaultdict[str, float] = defaultdict(float)

    for member in members:
        member_id = str(member.get("id") or "")
        criticality_score = _criticality_score(member.get("criticality"))
        criticality_by_member[member_id] = criticality_score
        member_contexts[_context_key(member)].append(member)
        for node_id in member_focus_map.get(member_id, []):
            node_criticality[node_id] = max(node_criticality[node_id], criticality_score)

    node_metrics: dict[str, dict[str, Any]] = {}
    for node_id, node in graph_entities.items():
        centrality_row = centrality.get(node_id, {})
        decision_importance = _safe_prob(centrality_row.get("decision_importance"))
        structural_importance = _safe_prob(centrality_row.get("structural_importance"))
        criticality_score = _safe_prob(node_criticality.get(node_id))
        mission_importance = _geometric_mean(
            [
                max(decision_importance, 1e-6),
                max(criticality_score, 1e-6),
            ]
        )
        node_metrics[node_id] = {
            "entity_id": node_id,
            "entity_name": _normalize_text(node.get("canonical_name") or node_id),
            "entity_type": _normalize_text(node.get("entity_type") or "unknown"),
            "structural_importance": round(structural_importance, 4),
            "decision_importance": round(decision_importance, 4),
            "mission_importance": round(mission_importance, 4),
            "criticality_score": round(criticality_score, 4),
        }

    member_scores: list[dict[str, Any]] = []
    for member in members:
        member_id = str(member.get("id") or "")
        node_ids = member_focus_map.get(member_id, [])
        if not node_ids and member.get("entity_id"):
            node_ids = [str(member.get("entity_id"))]

        centrality_rows = [centrality.get(node_id, {}) for node_id in node_ids if node_id in centrality]
        decision_importance = max((_safe_prob(row.get("decision_importance")) for row in centrality_rows), default=0.0)
        structural_importance = max((_safe_prob(row.get("structural_importance")) for row in centrality_rows), default=0.0)
        local_edge_intelligence = max((_safe_prob(row.get("local_edge_intelligence")) for row in centrality_rows), default=0.0)
        criticality_score = criticality_by_member.get(member_id, _criticality_score(member.get("criticality")))

        context_members = member_contexts[_context_key(member)]
        equivalent_member_count = max(len(context_members), 1)
        dependency_concentration = round(1.0 / equivalent_member_count, 4)
        substitute_coverage_score = round(1.0 - (1.0 / equivalent_member_count), 4)

        edge_metrics = _node_touching_edge_metrics(node_ids, edges)
        if edge_metrics["explicit_substitute_hits"] > 0:
            substitute_coverage_score = max(
                substitute_coverage_score,
                round(1.0 - (1.0 / (edge_metrics["explicit_substitute_hits"] + 1)), 4),
            )

        mission_impact_score = round(
            _geometric_mean(
                [
                    max(criticality_score, 1e-6),
                    max(decision_importance, 1e-6),
                    max(dependency_concentration, 1e-6),
                ]
            ),
            4,
        )
        substitute_gap = round(1.0 - substitute_coverage_score, 4)
        control_gap = round(1.0 - _safe_prob(edge_metrics["control_path_quality"]), 4)
        brittleness_factors = [
            mission_impact_score,
            max(substitute_gap, 1e-6),
            max(control_gap, 1e-6),
        ]
        if edge_metrics["single_point_of_failure_signal"] > 0:
            brittleness_factors.append(max(edge_metrics["single_point_of_failure_signal"], 1e-6))
        brittle_node_score = round(_geometric_mean(brittleness_factors), 4)
        resilience_score = round(max(0.0, 1.0 - brittle_node_score), 4)

        if edge_metrics["single_point_of_failure_signal"] >= 0.7:
            recommended_action = "Break the single-point dependency with an alternate supplier or subsystem path."
        elif substitute_gap >= max(control_gap, dependency_concentration):
            recommended_action = "Qualify alternates or explicit substitutes for this mission role."
        elif control_gap >= dependency_concentration:
            recommended_action = "Strengthen ownership, financing, and intermediary evidence for this member."
        else:
            recommended_action = "Reduce concentration by splitting this role across additional members or sites."

        member_scores.append(
            {
                "member_id": member_id,
                "vendor_id": _normalize_text(member.get("vendor_id")),
                "entity_id": _normalize_text(member.get("entity_id")),
                "label": _normalize_text(
                    ((member.get("vendor") or {}).get("name"))
                    or ((member.get("entity") or {}).get("canonical_name"))
                    or member.get("role")
                    or member_id
                ),
                "role": _normalize_text(member.get("role")),
                "criticality": _normalize_text(member.get("criticality") or "supporting"),
                "criticality_score": round(criticality_score, 4),
                "focus_node_ids": node_ids,
                "decision_importance": round(decision_importance, 4),
                "structural_importance": round(structural_importance, 4),
                "mission_impact_score": mission_impact_score,
                "brittle_node_score": brittle_node_score,
                "resilience_score": resilience_score,
                "substitute_coverage_score": substitute_coverage_score,
                "dependency_concentration": dependency_concentration,
                "control_path_quality": edge_metrics["control_path_quality"],
                "single_point_of_failure_signal": edge_metrics["single_point_of_failure_signal"],
                "local_edge_intelligence": round(local_edge_intelligence, 4),
                "recommended_action": recommended_action,
                "touched_relationship_types": edge_metrics["touched_relationship_types"],
            }
        )

    top_brittle_members = sorted(member_scores, key=lambda row: row.get("brittle_node_score", 0.0), reverse=True)[:5]
    top_resilient_members = sorted(member_scores, key=lambda row: row.get("resilience_score", 0.0), reverse=True)[:5]
    top_nodes_by_mission_importance = sorted(
        node_metrics.values(),
        key=lambda row: row.get("mission_importance", 0.0),
        reverse=True,
    )[:10]

    summary = {
        "model_version": "mission-thread-resilience-v1",
        "mission_thread_id": _normalize_text(thread.get("id")),
        "member_count": len(member_scores),
        "average_resilience_score": round(
            sum(row.get("resilience_score", 0.0) for row in member_scores) / len(member_scores),
            4,
        ) if member_scores else 0.0,
        "average_brittle_node_score": round(
            sum(row.get("brittle_node_score", 0.0) for row in member_scores) / len(member_scores),
            4,
        ) if member_scores else 0.0,
        "critical_brittle_member_count": len(
            [
                row
                for row in member_scores
                if row.get("criticality_score", 0.0) >= 0.8 and row.get("brittle_node_score", 0.0) >= 0.5
            ]
        ),
        "top_brittle_members": top_brittle_members,
        "top_resilient_members": top_resilient_members,
        "top_nodes_by_mission_importance": top_nodes_by_mission_importance,
    }

    return {
        "summary": summary,
        "member_scores": member_scores,
        "graph_analytics": {
            "node_metrics": node_metrics,
            "top_nodes_by_mission_importance": top_nodes_by_mission_importance,
        },
    }
