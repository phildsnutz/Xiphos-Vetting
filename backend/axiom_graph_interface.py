"""
AXIOM graph interface for summarized graph interrogation and staged writeback.

This module is the only graph-facing contract AXIOM should need:
  - query translation into graph analytics and provenance-aware summaries
  - deterministic summary generation with machine-readable payloads
  - staged writeback that never mutates durable graph truth directly
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from graph_analytics import GraphAnalytics
from graph_ingest import build_graph_intelligence_summary
from knowledge_graph import (
    get_entity,
    get_entity_network,
    get_vendor_entities,
    graph_annotate as stage_graph_annotation,
    graph_assert as stage_graph_assertion,
    graph_flag as stage_graph_flag,
    graph_update_confidence as stage_graph_confidence_update,
    list_graph_staging,
    review_graph_staging_entry,
)


def _load_analytics() -> GraphAnalytics:
    analytics = GraphAnalytics()
    analytics.load_graph()
    return analytics


def resolve_primary_entity_id_for_vendor(vendor_id: str) -> str:
    entities = get_vendor_entities(str(vendor_id or "").strip())
    if not entities:
        return ""
    ranked = sorted(
        entities,
        key=lambda entity: (
            str(getattr(entity, "entity_type", "") or "").lower() != "company",
            -len(getattr(entity, "relationships", []) or []),
            -float(getattr(entity, "confidence", 0.0) or 0.0),
            str(getattr(entity, "canonical_name", "") or "").lower(),
        ),
    )
    return str(getattr(ranked[0], "id", "") or "")


def _resolve_entity_id(entity_id: str = "", vendor_id: str = "") -> str:
    normalized_entity_id = str(entity_id or "").strip()
    if normalized_entity_id:
        return normalized_entity_id
    normalized_vendor_id = str(vendor_id or "").strip()
    if normalized_vendor_id:
        return resolve_primary_entity_id_for_vendor(normalized_vendor_id)
    return ""


def _entity_payload(entity) -> dict[str, Any]:
    return {
        "id": str(getattr(entity, "id", "") or ""),
        "name": str(getattr(entity, "canonical_name", "") or ""),
        "type": str(getattr(entity, "entity_type", "") or ""),
        "confidence": round(float(getattr(entity, "confidence", 0.0) or 0.0), 4),
        "country": str(getattr(entity, "country", "") or ""),
        "last_updated": str(getattr(entity, "last_updated", "") or ""),
        "identifiers": getattr(entity, "identifiers", {}) or {},
        "aliases": getattr(entity, "aliases", []) or [],
        "sources": getattr(entity, "sources", []) or [],
    }


def _confidence_bucket(value: float) -> str:
    score = max(0.0, min(float(value or 0.0), 1.0))
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "moderate"
    if score > 0.0:
        return "low"
    return "unknown"


def _state_for_relationship(relationship: dict) -> str:
    claim_records = [row for row in (relationship.get("claim_records") or []) if isinstance(row, dict)]
    structured_fields = relationship.get("structured_fields") if isinstance(relationship.get("structured_fields"), dict) else {}
    if structured_fields.get("review_outcome"):
        return "reviewed"
    if structured_fields.get("prediction_model") or structured_fields.get("model_family"):
        return "predicted"
    if structured_fields.get("inference_method") or structured_fields.get("rule_id"):
        return "inferred"
    if claim_records:
        for claim in claim_records:
            claim_fields = claim.get("structured_fields") if isinstance(claim.get("structured_fields"), dict) else {}
            if claim_fields.get("review_outcome"):
                return "reviewed"
            if claim_fields.get("prediction_model") or claim_fields.get("model_family"):
                return "predicted"
            if claim_fields.get("inference_method") or claim_fields.get("rule_id"):
                return "inferred"
        return "observed"
    return "observed"


def _relationship_type_counts(relationships: list[dict]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for relationship in relationships:
        rel_type = str(relationship.get("rel_type") or "").strip()
        if rel_type:
            counts[rel_type] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _state_mix(relationships: list[dict]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for relationship in relationships:
        counts[_state_for_relationship(relationship)] += 1
    return {
        "observed": int(counts.get("observed", 0)),
        "inferred": int(counts.get("inferred", 0)),
        "predicted": int(counts.get("predicted", 0)),
        "reviewed": int(counts.get("reviewed", 0)),
    }


def _community_summary(analytics: GraphAnalytics, entity_id: str) -> dict[str, Any]:
    communities = analytics.detect_communities()
    community_id = str((communities.get("node_labels") or {}).get(entity_id) or "")
    community = (communities.get("communities") or {}).get(community_id) if community_id else None
    if not isinstance(community, dict):
        return {
            "community_id": "",
            "algorithm": str(communities.get("algorithm") or ""),
            "size": 0,
            "density": 0.0,
            "members": [],
            "bridge_entities": [],
            "modularity": round(float(communities.get("modularity") or 0.0), 4),
        }
    return {
        "community_id": community_id,
        "algorithm": str(communities.get("algorithm") or ""),
        "size": int(community.get("size") or 0),
        "density": round(float(community.get("density") or 0.0), 4),
        "members": list((community.get("members") or [])[:8]),
        "bridge_entities": list((community.get("bridge_entities") or [])[:5]),
        "modularity": round(float(communities.get("modularity") or 0.0), 4),
    }


def _neighbor_rollup(entity_id: str, relationships: list[dict], entities: dict[str, dict], analytics: GraphAnalytics) -> list[dict]:
    exposure = analytics.compute_sanctions_exposure()
    rolled: dict[str, dict[str, Any]] = {}
    for relationship in relationships:
        source_id = str(relationship.get("source_entity_id") or "")
        target_id = str(relationship.get("target_entity_id") or "")
        if entity_id not in {source_id, target_id}:
            continue
        neighbor_id = target_id if source_id == entity_id else source_id
        if not neighbor_id:
            continue
        neighbor = rolled.setdefault(
            neighbor_id,
            {
                "entity_id": neighbor_id,
                "name": str((entities.get(neighbor_id) or {}).get("canonical_name") or neighbor_id),
                "entity_type": str((entities.get(neighbor_id) or {}).get("entity_type") or ""),
                "relationship_count": 0,
                "relationship_types": Counter(),
                "max_confidence": 0.0,
                "risk_level": str((exposure.get(neighbor_id) or {}).get("risk_level") or "CLEAR"),
                "exposure_score": float((exposure.get(neighbor_id) or {}).get("exposure_score") or 0.0),
            },
        )
        neighbor["relationship_count"] += 1
        rel_type = str(relationship.get("rel_type") or "").strip()
        if rel_type:
            neighbor["relationship_types"][rel_type] += 1
        neighbor["max_confidence"] = max(neighbor["max_confidence"], float(relationship.get("confidence") or 0.0))
    results = []
    for neighbor in rolled.values():
        relationship_types = dict(sorted(neighbor["relationship_types"].items(), key=lambda item: (-item[1], item[0])))
        results.append(
            {
                "entity_id": neighbor["entity_id"],
                "name": neighbor["name"],
                "entity_type": neighbor["entity_type"],
                "relationship_count": int(neighbor["relationship_count"]),
                "relationship_types": relationship_types,
                "max_confidence": round(float(neighbor["max_confidence"] or 0.0), 4),
                "risk_level": neighbor["risk_level"],
                "exposure_score": round(float(neighbor["exposure_score"] or 0.0), 4),
            }
        )
    results.sort(
        key=lambda item: (
            -float(item["exposure_score"]),
            -int(item["relationship_count"]),
            -float(item["max_confidence"]),
            str(item["name"]),
        )
    )
    return results


def graph_profile(
    entity_id: str = "",
    *,
    vendor_id: str = "",
    workflow_lane: str = "",
    mission_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_entity_id = _resolve_entity_id(entity_id, vendor_id)
    entity = get_entity(resolved_entity_id)
    if entity is None:
        return {
            "status": "not_found",
            "entity_id": resolved_entity_id,
            "summary_text": "No graph-backed entity profile is available yet.",
            "structured_payload": {},
        }

    network = get_entity_network(
        resolved_entity_id,
        depth=1,
        include_provenance=True,
        max_claim_records=2,
        max_evidence_records=1,
    )
    relationships = [row for row in (network.get("relationships") or []) if isinstance(row, dict)]
    intelligence = build_graph_intelligence_summary(network, workflow_lane=workflow_lane)
    analytics = _load_analytics()
    centrality = analytics.compute_all_centrality(mission_context=mission_context).get(resolved_entity_id, {})
    community = _community_summary(analytics, resolved_entity_id)
    sanctions = analytics.compute_sanctions_exposure().get(resolved_entity_id, {})
    rel_counts = _relationship_type_counts(relationships)
    state_mix = _state_mix(relationships)
    strongest_neighbor = ""
    highest_risk_neighbor = ""
    neighbors = _neighbor_rollup(resolved_entity_id, relationships, network.get("entities") or {}, analytics)
    if neighbors:
        strongest_neighbor = str(neighbors[0]["name"])
        highest_risk_neighbor = str(neighbors[0]["name"]) if float(neighbors[0]["exposure_score"]) > 0 else ""
    summary_bits = [
        f"{entity.canonical_name} is a {entity.entity_type} with {len(relationships)} direct relationships across {len(rel_counts)} relationship types.",
        f"Graph confidence is {_confidence_bucket(entity.confidence)}.",
    ]
    if highest_risk_neighbor:
        summary_bits.append(f"Highest-risk neighbor: {highest_risk_neighbor}.")
    elif strongest_neighbor:
        summary_bits.append(f"Most active direct neighbor: {strongest_neighbor}.")
    if community.get("community_id"):
        summary_bits.append(
            f"It sits in {community['community_id']} via {community.get('algorithm') or 'community detection'} "
            f"with {community.get('size', 0)} entities."
        )
    if intelligence.get("missing_required_edge_families"):
        summary_bits.append(
            "Thin areas remain around "
            + ", ".join(str(item).replace("_", " ") for item in (intelligence.get("missing_required_edge_families") or [])[:3])
            + "."
        )
    return {
        "status": "ok",
        "entity_id": resolved_entity_id,
        "summary_text": " ".join(summary_bits),
        "structured_payload": {
            "entity": _entity_payload(entity),
            "direct_relationship_counts": rel_counts,
            "risk": {
                "risk_level": str(sanctions.get("risk_level") or "CLEAR"),
                "exposure_score": round(float(sanctions.get("exposure_score") or 0.0), 4),
                "network_risk_level": str(intelligence.get("network_risk_level") or ""),
                "high_risk_neighbors": int(intelligence.get("high_risk_neighbors") or 0),
            },
            "freshness": {
                "last_updated": str(entity.last_updated or ""),
                "freshest_observation_at": str(intelligence.get("freshest_observation_at") or ""),
                "stalest_observation_at": str(intelligence.get("stalest_observation_at") or ""),
                "avg_edge_age_days": intelligence.get("avg_edge_age_days"),
            },
            "community": community,
            "centrality": centrality,
            "state_mix": state_mix,
            "graph_intelligence": intelligence,
            "neighbors": neighbors[:8],
        },
    }


def graph_neighborhood(
    entity_id: str = "",
    *,
    vendor_id: str = "",
    depth: int = 1,
    rel_types: list[str] | tuple[str, ...] | None = None,
    workflow_lane: str = "",
    mission_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_entity_id = _resolve_entity_id(entity_id, vendor_id)
    entity = get_entity(resolved_entity_id)
    if entity is None:
        return {
            "status": "not_found",
            "entity_id": resolved_entity_id,
            "summary_text": "No graph neighborhood is available because the entity is not present in graph memory.",
            "structured_payload": {},
        }
    network = get_entity_network(
        resolved_entity_id,
        depth=max(1, int(depth or 1)),
        include_provenance=True,
        max_claim_records=2,
        max_evidence_records=1,
    )
    relationships = [row for row in (network.get("relationships") or []) if isinstance(row, dict)]
    allowed_rel_types = {str(item).strip() for item in (rel_types or []) if str(item).strip()}
    if allowed_rel_types:
        relationships = [row for row in relationships if str(row.get("rel_type") or "").strip() in allowed_rel_types]
        network = {**network, "relationships": relationships, "relationship_count": len(relationships)}
    intelligence = build_graph_intelligence_summary(network, workflow_lane=workflow_lane)
    analytics = _load_analytics()
    neighbors = _neighbor_rollup(resolved_entity_id, relationships, network.get("entities") or {}, analytics)
    rel_counts = _relationship_type_counts(relationships)
    highest_risk_neighbor = next((row for row in neighbors if float(row.get("exposure_score") or 0.0) > 0.0), neighbors[0] if neighbors else None)
    summary_bits = [
        f"{entity.canonical_name} has {len(relationships)} relationships in the current neighborhood slice.",
    ]
    if rel_counts:
        top_types = ", ".join(f"{rel_type} ({count})" for rel_type, count in list(rel_counts.items())[:4])
        summary_bits.append(f"Most common relationship types: {top_types}.")
    if highest_risk_neighbor:
        summary_bits.append(
            f"Highest-risk neighbor: {highest_risk_neighbor['name']} "
            f"({highest_risk_neighbor['risk_level']}, {highest_risk_neighbor['exposure_score']:.2f})."
        )
    if intelligence.get("dominant_edge_family"):
        summary_bits.append(
            f"Dominant edge family in this slice: {str(intelligence.get('dominant_edge_family')).replace('_', ' ')}."
        )
    return {
        "status": "ok",
        "entity_id": resolved_entity_id,
        "summary_text": " ".join(summary_bits),
        "structured_payload": {
            "entity": _entity_payload(entity),
            "depth": max(1, int(depth or 1)),
            "relationship_counts": rel_counts,
            "neighbors": neighbors[:12],
            "state_mix": _state_mix(relationships),
            "graph_intelligence": intelligence,
            "mission_context": mission_context or {},
        },
    }


def graph_path(
    source_id: str,
    target_id: str,
    *,
    max_depth: int = 4,
) -> dict[str, Any]:
    analytics = _load_analytics()
    critical_path = analytics.critical_path(str(source_id or "").strip(), str(target_id or "").strip())
    all_paths = analytics.all_paths(str(source_id or "").strip(), str(target_id or "").strip(), max_hops=max(1, int(max_depth or 4)))
    if critical_path is None and not all_paths:
        return {
            "status": "not_found",
            "source_id": str(source_id or "").strip(),
            "target_id": str(target_id or "").strip(),
            "summary_text": "No graph path was found between those entities within the requested depth.",
            "structured_payload": {},
        }
    compact_paths = []
    for path in all_paths[:3]:
        node_names = [str(node.get("name") or node.get("id") or "") for node in (path.get("nodes") or [])]
        compact_paths.append(
            {
                "hops": int(path.get("hops") or 0),
                "path_confidence": round(float(path.get("path_confidence") or 0.0), 4),
                "chain": node_names,
                "edge_types": [str(edge.get("rel_type") or "") for edge in (path.get("edges") or [])],
            }
        )
    summary_bits = [f"{len(all_paths)} path(s) found between the requested entities."]
    if critical_path:
        node_names = [str(node.get("name") or node.get("id") or "") for node in (critical_path.get("nodes") or [])]
        summary_bits.append(
            f"Strongest path is {int(critical_path.get('hops') or 0)} hops at confidence {float(critical_path.get('path_confidence') or 0.0):.2f}: "
            + " > ".join(node_names)
            + "."
        )
    return {
        "status": "ok",
        "source_id": str(source_id or "").strip(),
        "target_id": str(target_id or "").strip(),
        "summary_text": " ".join(summary_bits),
        "structured_payload": {
            "critical_path": critical_path or {},
            "paths": compact_paths,
            "path_count": len(all_paths),
            "max_depth": max(1, int(max_depth or 4)),
        },
    }


def graph_community(
    entity_id: str = "",
    *,
    vendor_id: str = "",
) -> dict[str, Any]:
    resolved_entity_id = _resolve_entity_id(entity_id, vendor_id)
    entity = get_entity(resolved_entity_id)
    if entity is None:
        return {
            "status": "not_found",
            "entity_id": resolved_entity_id,
            "summary_text": "No community cluster is available because the entity is not present in graph memory.",
            "structured_payload": {},
        }
    analytics = _load_analytics()
    community = _community_summary(analytics, resolved_entity_id)
    if not community.get("community_id"):
        return {
            "status": "ok",
            "entity_id": resolved_entity_id,
            "summary_text": f"{entity.canonical_name} does not yet sit inside a meaningful detected community cluster.",
            "structured_payload": {"entity": _entity_payload(entity), "community": community},
        }
    key_members = ", ".join(member["name"] for member in community.get("members", [])[:5])
    summary = (
        f"{entity.canonical_name} belongs to {community['community_id']} via {community.get('algorithm') or 'community detection'} "
        f"with {community.get('size', 0)} entities and density {float(community.get('density') or 0.0):.2f}. "
        f"Key members: {key_members}."
    )
    return {
        "status": "ok",
        "entity_id": resolved_entity_id,
        "summary_text": summary,
        "structured_payload": {"entity": _entity_payload(entity), "community": community},
    }


def _community_absence_signal(entity_id: str, analytics: GraphAnalytics, community: dict[str, Any]) -> dict[str, Any] | None:
    community_members = [member for member in (community.get("members") or []) if isinstance(member, dict)]
    if len(community_members) < 3:
        return None
    peer_ids = [str(member.get("id") or "") for member in community_members if str(member.get("id") or "") and str(member.get("id")) != entity_id]
    if not peer_ids:
        return None

    entity_targets = set()
    entity_rel_types = set()
    for neighbor, eidx in analytics.adj.get(entity_id, []):
        entity_targets.add(neighbor)
        entity_rel_types.add(str(analytics.edges[eidx].get("rel_type") or ""))

    peer_target_support: Counter[str] = Counter()
    peer_rel_support: Counter[str] = Counter()
    for peer_id in peer_ids:
        peer_targets_seen = set()
        peer_rels_seen = set()
        for neighbor, eidx in analytics.adj.get(peer_id, []):
            if neighbor in {entity_id, peer_id}:
                continue
            rel_type = str(analytics.edges[eidx].get("rel_type") or "")
            if rel_type and rel_type not in peer_rels_seen:
                peer_rel_support[rel_type] += 1
                peer_rels_seen.add(rel_type)
            if neighbor not in peer_targets_seen:
                peer_target_support[neighbor] += 1
                peer_targets_seen.add(neighbor)

    threshold = max(2, math.ceil(len(peer_ids) * 0.6))
    for target_id, support in peer_target_support.most_common():
        if target_id not in entity_targets and support >= threshold:
            target_node = analytics.nodes.get(target_id, {})
            return {
                "type": "suspicious_absence",
                "confidence": round(min(0.55 + (support / max(len(peer_ids), 1)) * 0.35, 0.89), 4),
                "description": (
                    f"Peer entities in {community.get('community_id')} repeatedly connect to "
                    f"{target_node.get('canonical_name', target_id)}, but {analytics.nodes.get(entity_id, {}).get('canonical_name', entity_id)} does not."
                ),
            }
    for rel_type, support in peer_rel_support.most_common():
        if rel_type not in entity_rel_types and support >= threshold:
            return {
                "type": "missing_relationship_pattern",
                "confidence": round(min(0.5 + (support / max(len(peer_ids), 1)) * 0.3, 0.84), 4),
                "description": (
                    f"Peer entities in {community.get('community_id')} commonly carry {rel_type} edges, "
                    f"but this entity does not."
                ),
            }
    return None


def graph_anomalies(
    entity_id: str = "",
    *,
    vendor_id: str = "",
    workflow_lane: str = "",
    mission_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_entity_id = _resolve_entity_id(entity_id, vendor_id)
    entity = get_entity(resolved_entity_id)
    if entity is None:
        return {
            "status": "not_found",
            "entity_id": resolved_entity_id,
            "summary_text": "No anomaly scan is available because the entity is not present in graph memory.",
            "structured_payload": {},
        }
    analytics = _load_analytics()
    centrality = analytics.compute_all_centrality(mission_context=mission_context).get(resolved_entity_id, {})
    community = _community_summary(analytics, resolved_entity_id)
    sanctions = analytics.compute_sanctions_exposure().get(resolved_entity_id, {})
    network = get_entity_network(
        resolved_entity_id,
        depth=1,
        include_provenance=True,
        max_claim_records=2,
        max_evidence_records=1,
    )
    relationships = [row for row in (network.get("relationships") or []) if isinstance(row, dict)]
    intelligence = build_graph_intelligence_summary(network, workflow_lane=workflow_lane)
    anomalies: list[dict[str, Any]] = []

    betweenness = float(((centrality.get("betweenness") or {}).get("normalized") or 0.0))
    degree_count = int(((centrality.get("degree") or {}).get("degree") or 0))
    if betweenness >= 0.7 and degree_count <= 4:
        anomalies.append(
            {
                "type": "gatekeeper_structure",
                "confidence": round(min(0.6 + (betweenness * 0.3), 0.92), 4),
                "description": (
                    f"High betweenness ({betweenness:.2f}) with only {degree_count} direct links suggests a gatekeeper or broker role."
                ),
            }
        )

    if intelligence.get("missing_required_edge_families"):
        missing = [str(item).replace("_", " ") for item in (intelligence.get("missing_required_edge_families") or [])[:3]]
        anomalies.append(
            {
                "type": "thin_required_fabric",
                "confidence": 0.74,
                "description": f"Required graph fabric is still missing around {', '.join(missing)}.",
            }
        )

    absence = _community_absence_signal(resolved_entity_id, analytics, community)
    if absence:
        anomalies.append(absence)

    historical_claims = 0
    for relationship in relationships:
        for claim in (relationship.get("claim_records") or []):
            if str(claim.get("contradiction_state") or "").strip().lower() == "historical":
                historical_claims += 1
    if historical_claims >= 2:
        anomalies.append(
            {
                "type": "temporal_churn",
                "confidence": 0.68,
                "description": f"The local claim fabric already carries {historical_claims} historical edges, suggesting meaningful graph churn.",
            }
        )

    if float(sanctions.get("exposure_score") or 0.0) >= 0.45:
        anomalies.append(
            {
                "type": "network_risk_propagation",
                "confidence": round(min(0.55 + float(sanctions.get("exposure_score") or 0.0) * 0.35, 0.9), 4),
                "description": (
                    f"Network sanctions exposure is already {float(sanctions.get('exposure_score') or 0.0):.2f}, "
                    f"which should change how new links are interpreted."
                ),
            }
        )

    anomalies.sort(key=lambda item: (-float(item.get("confidence") or 0.0), str(item.get("type") or "")))
    summary = (
        f"{len(anomalies)} anomaly signal(s) detected around {entity.canonical_name}."
        if anomalies
        else f"No material structural anomaly surfaced around {entity.canonical_name} in the current graph slice."
    )
    return {
        "status": "ok",
        "entity_id": resolved_entity_id,
        "summary_text": summary,
        "structured_payload": {
            "entity": _entity_payload(entity),
            "anomalies": anomalies[:5],
            "community": community,
            "centrality": centrality,
            "graph_intelligence": intelligence,
            "risk": sanctions,
        },
    }


def graph_assert(*args, **kwargs) -> dict:
    return stage_graph_assertion(*args, **kwargs)


def graph_annotate(*args, **kwargs) -> dict:
    return stage_graph_annotation(*args, **kwargs)


def graph_flag(*args, **kwargs) -> dict:
    return stage_graph_flag(*args, **kwargs)


def graph_update_confidence(*args, **kwargs) -> dict:
    return stage_graph_confidence_update(*args, **kwargs)


def graph_staging_queue(*, status: str = "staged", proposal_type: str = "", vendor_id: str = "", limit: int = 50) -> dict[str, Any]:
    items = list_graph_staging(status=status, proposal_type=proposal_type, vendor_id=vendor_id, limit=limit)
    summary = f"{len(items)} staged graph proposal(s) currently match the requested filter."
    return {
        "status": "ok",
        "summary_text": summary,
        "structured_payload": {
            "items": items,
            "count": len(items),
            "status_filter": status,
            "proposal_type_filter": proposal_type,
            "vendor_id_filter": vendor_id,
        },
    }


def graph_review_staging(
    staging_id: str,
    *,
    review_outcome: str,
    reviewed_by: str = "",
    review_notes: str = "",
) -> dict[str, Any]:
    reviewed = review_graph_staging_entry(
        staging_id,
        review_outcome=review_outcome,
        reviewed_by=reviewed_by,
        review_notes=review_notes,
    )
    outcome = str(reviewed.get("review_outcome") or review_outcome or "").strip().lower() or "reviewed"
    return {
        "status": "ok",
        "summary_text": f"Graph proposal {staging_id} was marked {outcome}.",
        "structured_payload": reviewed,
    }
