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

INDOPACOM_THEATER_TOKENS = {"indopacom", "indo-pacific", "indo_pacific", "pacific"}
INDOPACOM_ALLY_COUNTRIES = {
    "AU",
    "AUS",
    "JP",
    "JPN",
    "KR",
    "KOR",
    "ROK",
    "SG",
    "SGP",
    "NZ",
    "NZL",
    "PH",
    "PHL",
    "TH",
    "THA",
}
AUSTERE_SITE_TOKENS = {
    "guam",
    "saipan",
    "tinian",
    "palau",
    "yap",
    "okinawa",
    "darwin",
    "philippines",
    "marianas",
    "timor",
    "weipa",
}
FUEL_KEYWORDS = {
    "fuel",
    "refuel",
    "petroleum",
    "defuel",
    "offload",
    "bladder",
    "pipeline",
}
REPAIR_KEYWORDS = {
    "repair",
    "maintenance",
    "maintainer",
    "depot",
    "mro",
    "calibration",
    "sustainment",
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


def _normalize_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return _normalize_text(value).lower() in {"1", "true", "yes", "y", "on"}


def _criticality_score(label: object) -> float:
    normalized = _normalize_text(label).lower().replace(" ", "_")
    if normalized in {"primary", "essential"}:
        normalized = "high"
    if normalized not in CRITICALITY_INDEX:
        normalized = "supporting"
    return round((CRITICALITY_INDEX[normalized] + 1) / len(CRITICALITY_ORDER), 4)


def _country_code(value: object) -> str:
    code = _normalize_text(value).upper()
    return code.split()[0] if code else ""


def _is_indopacom_thread(thread: dict[str, Any]) -> bool:
    theater = _normalize_text(thread.get("theater")).lower()
    return any(token in theater for token in INDOPACOM_THEATER_TOKENS)


def _member_text(member: dict[str, Any]) -> str:
    parts = [
        member.get("role"),
        member.get("subsystem"),
        member.get("site"),
        member.get("notes"),
        ((member.get("vendor") or {}).get("name")),
        ((member.get("entity") or {}).get("canonical_name")),
    ]
    return " ".join(_normalize_text(part).lower() for part in parts if _normalize_text(part))


def _site_is_austere(member: dict[str, Any]) -> bool:
    text = " ".join(
        [
            _normalize_text(member.get("site")).lower(),
            _normalize_text(member.get("notes")).lower(),
        ]
    )
    return any(token in text for token in AUSTERE_SITE_TOKENS)


def _member_country(member: dict[str, Any], graph_entities: dict[str, dict[str, Any]], node_ids: list[str]) -> str:
    candidate_values = [
        ((member.get("vendor") or {}).get("country")),
        ((member.get("entity") or {}).get("country")),
    ]
    candidate_values.extend((graph_entities.get(node_id) or {}).get("country") for node_id in node_ids)
    for value in candidate_values:
        code = _country_code(value)
        if code:
            return code
    return ""


def _ally_access_quality(
    *,
    thread: dict[str, Any],
    member: dict[str, Any],
    graph_entities: dict[str, dict[str, Any]],
    node_ids: list[str],
    edge_metrics: dict[str, Any],
) -> float:
    if not _is_indopacom_thread(thread):
        return 0.0

    country = _member_country(member, graph_entities, node_ids)
    if not country or country in {"US", "USA"}:
        return 0.0

    touched_types = set((edge_metrics.get("touched_relationship_types") or {}).keys())
    score = 0.45 if country in INDOPACOM_ALLY_COUNTRIES else 0.15
    if _normalize_bool(member.get("is_alternate")):
        score += 0.2
    if {"supports_site", "operates_facility"} & touched_types:
        score += 0.15
    if "substitutable_with" in touched_types:
        score += 0.1
    if any(token in _member_text(member) for token in REPAIR_KEYWORDS):
        score += 0.1
    return round(min(score, 0.95), 4)


def _repair_latency_penalty(
    *,
    thread: dict[str, Any],
    member: dict[str, Any],
    edge_metrics: dict[str, Any],
) -> float:
    if not _is_indopacom_thread(thread):
        return 0.0
    if not any(token in _member_text(member) for token in REPAIR_KEYWORDS):
        return 0.0

    penalty = 0.35
    if _site_is_austere(member):
        penalty += 0.15
    if int(edge_metrics.get("explicit_substitute_hits") or 0) == 0:
        penalty += 0.15
    if _safe_prob(edge_metrics.get("single_point_of_failure_signal")) > 0:
        penalty += 0.15
    if _safe_prob(edge_metrics.get("control_path_quality")) < 0.5:
        penalty += 0.1
    return round(min(penalty, 0.95), 4)


def _austere_site_fuel_criticality(
    *,
    thread: dict[str, Any],
    member: dict[str, Any],
    edge_metrics: dict[str, Any],
) -> float:
    if not _is_indopacom_thread(thread):
        return 0.0
    if not _site_is_austere(member):
        return 0.0
    if not any(token in _member_text(member) for token in FUEL_KEYWORDS):
        return 0.0

    touched_types = set((edge_metrics.get("touched_relationship_types") or {}).keys())
    score = 0.68
    if {"supports_site", "ships_via", "distributed_by"} & touched_types:
        score += 0.1
    if _safe_prob(edge_metrics.get("single_point_of_failure_signal")) > 0:
        score += 0.12
    if _normalize_bool(member.get("is_alternate")):
        score -= 0.12
    return round(max(0.0, min(score, 1.0)), 4)


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
        ally_access_quality = _ally_access_quality(
            thread=thread,
            member=member,
            graph_entities=graph_entities,
            node_ids=node_ids,
            edge_metrics=edge_metrics,
        )
        repair_latency_penalty = _repair_latency_penalty(
            thread=thread,
            member=member,
            edge_metrics=edge_metrics,
        )
        austere_site_fuel_criticality = _austere_site_fuel_criticality(
            thread=thread,
            member=member,
            edge_metrics=edge_metrics,
        )
        if edge_metrics["explicit_substitute_hits"] > 0:
            substitute_coverage_score = max(
                substitute_coverage_score,
                round(1.0 - (1.0 / (edge_metrics["explicit_substitute_hits"] + 1)), 4),
            )

        mission_impact_factors = [
            max(criticality_score, 1e-6),
            max(decision_importance, 1e-6),
            max(dependency_concentration, 1e-6),
        ]
        if repair_latency_penalty > 0:
            mission_impact_factors.append(max(repair_latency_penalty, 1e-6))
        if austere_site_fuel_criticality > 0:
            mission_impact_factors.append(max(austere_site_fuel_criticality, 1e-6))
        mission_impact_score = round(_geometric_mean(mission_impact_factors), 4)
        substitute_gap = round(1.0 - substitute_coverage_score, 4)
        control_gap = round(1.0 - _safe_prob(edge_metrics["control_path_quality"]), 4)
        brittleness_factors = [
            mission_impact_score,
            max(substitute_gap, 1e-6),
            max(control_gap, 1e-6),
        ]
        if edge_metrics["single_point_of_failure_signal"] > 0:
            brittleness_factors.append(max(edge_metrics["single_point_of_failure_signal"], 1e-6))
        if repair_latency_penalty > 0:
            brittleness_factors.append(max(repair_latency_penalty, 1e-6))
        if austere_site_fuel_criticality > 0:
            brittleness_factors.append(max(austere_site_fuel_criticality, 1e-6))
        if ally_access_quality > 0:
            brittleness_factors.append(max(1.0 - ally_access_quality, 1e-6))
        brittle_node_score = round(_geometric_mean(brittleness_factors), 4)
        resilience_score = round(max(0.0, 1.0 - brittle_node_score), 4)

        if edge_metrics["single_point_of_failure_signal"] >= 0.7:
            recommended_action = "Break the single-point dependency with an alternate supplier or subsystem path."
        elif repair_latency_penalty >= max(substitute_gap, control_gap, dependency_concentration) and repair_latency_penalty >= 0.45:
            recommended_action = "Pre-negotiate regional repair capacity and reciprocal maintenance coverage to cut Pacific repair latency."
        elif austere_site_fuel_criticality >= max(substitute_gap, control_gap, dependency_concentration) and austere_site_fuel_criticality >= 0.65:
            recommended_action = "Preposition fuel-transfer equipment and backup refuel coverage for this austere island site."
        elif ally_access_quality >= 0.6 and _normalize_bool(member.get("is_alternate")):
            recommended_action = "Harden ally-access activation terms and reciprocal maintenance or support certifications before relying on this alternate path."
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
                "ally_access_quality": ally_access_quality,
                "repair_latency_penalty": repair_latency_penalty,
                "austere_site_fuel_criticality": austere_site_fuel_criticality,
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
        "average_ally_access_quality": round(
            sum(row.get("ally_access_quality", 0.0) for row in member_scores) / len(member_scores),
            4,
        ) if member_scores else 0.0,
        "average_repair_latency_penalty": round(
            sum(row.get("repair_latency_penalty", 0.0) for row in member_scores) / len(member_scores),
            4,
        ) if member_scores else 0.0,
        "austere_site_fuel_member_count": len(
            [row for row in member_scores if row.get("austere_site_fuel_criticality", 0.0) >= 0.65]
        ),
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
