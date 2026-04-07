from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
from typing import Any

from knowledge_graph import (
    find_shortest_path,
    get_kg_conn,
    get_multi_entity_network,
    get_graph_snapshot_signature,
)


V1_SUPPORTED_VEHICLES = {"iteams"}
CURRENT_VEHICLE_REL_TYPES = {"prime_contractor_of", "incumbent_on"}
TEAMING_REL_TYPES = {"teamed_with"}
VEHICLE_SIGNAL_REL_TYPES = {"prime_contractor_of", "incumbent_on", "subcontractor_of", "competed_on", "awarded_under"}
OPERATIONAL_REL_TYPES = {"operates_facility", "performed_at", "contracts_with"}
OWNERSHIP_REL_TYPES = {"owned_by", "parent_of", "subsidiary_of", "beneficially_owned_by", "related_entity"}
LEGAL_SUFFIX_TOKENS = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "llc",
    "ltd",
    "limited",
    "lp",
    "llp",
    "plc",
    "gmbh",
    "ag",
    "sa",
    "srl",
    "bv",
    "nv",
    "holdings",
}
CLASS_ORDER = [
    "incumbent-core",
    "locked",
    "swing",
    "recruitable",
    "cooling",
    "emerging",
]


@dataclass
class CandidateSignals:
    entity_id: str
    entity_name: str
    direct_vehicle_relationships: list[dict[str, Any]]
    incumbent_relationships: list[dict[str, Any]]
    other_vehicle_relationships: list[dict[str, Any]]
    operational_paths: list[list[dict[str, Any]]]
    observed_role: str
    observed_award_amount: float


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_name(name: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", str(name or "").lower())
    while tokens and tokens[-1] in LEGAL_SUFFIX_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def _compact_name(name: str) -> str:
    compact = re.sub(r"\b(Holdings?|Incorporated|Corporation|Company|Corp|Inc|LLC|Ltd)\b\.?,?", "", str(name or ""), flags=re.IGNORECASE)
    compact = re.sub(r"\s{2,}", " ", compact).strip(" ,")
    return compact or str(name or "").strip()


def _confidence_label(value: float) -> str:
    if value >= 0.8:
        return "high"
    if value >= 0.6:
        return "medium"
    return "low"


def _safe_amount(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _best_claim_timestamp(relationship: dict[str, Any]) -> str:
    stamps: list[str] = []
    for claim in relationship.get("claim_records") or []:
        for field in ("last_observed_at", "observed_at", "first_observed_at", "updated_at"):
            value = str(claim.get(field) or "").strip()
            if value:
                stamps.append(value)
        for evidence in claim.get("evidence_records") or []:
            value = str(evidence.get("observed_at") or "").strip()
            if value:
                stamps.append(value)
    if stamps:
        return max(stamps)
    return str(relationship.get("last_seen_at") or relationship.get("created_at") or "").strip()


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _days_between(older: str, newer: str) -> int | None:
    older_ts = _parse_timestamp(older)
    newer_ts = _parse_timestamp(newer)
    if not older_ts or not newer_ts:
        return None
    return (newer_ts - older_ts).days


def _describe_relationship(relationship: dict[str, Any], entities: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_name = entities.get(str(relationship.get("source_entity_id") or ""), {}).get("canonical_name", "")
    target_name = entities.get(str(relationship.get("target_entity_id") or ""), {}).get("canonical_name", "")
    best_claim = None
    claim_records = relationship.get("claim_records") or []
    if claim_records:
        best_claim = claim_records[0]
    evidence_records = best_claim.get("evidence_records") if isinstance(best_claim, dict) else []
    best_evidence = evidence_records[0] if evidence_records else {}
    observed_at = _best_claim_timestamp(relationship)
    return {
        "source": source_name,
        "target": target_name,
        "rel_type": relationship.get("rel_type", ""),
        "confidence": round(float(relationship.get("confidence") or 0.0), 2),
        "connector": _first_non_empty(best_evidence.get("source"), best_claim.get("data_source") if isinstance(best_claim, dict) else "", relationship.get("data_source", "")),
        "observed_at": observed_at,
        "snippet": _first_non_empty(best_evidence.get("snippet"), best_claim.get("claim_value") if isinstance(best_claim, dict) else "", relationship.get("evidence_summary", ""), relationship.get("evidence", "")),
        "corroboration_count": int(relationship.get("corroboration_count") or 0),
    }


def _build_name_index(entities: dict[str, dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for entity_id, entity in entities.items():
        canonical = str(entity.get("canonical_name") or "").strip()
        if canonical:
            index.setdefault(_normalize_name(canonical), entity_id)
        for alias in entity.get("aliases") or []:
            alias_text = str(alias or "").strip()
            if alias_text:
                index.setdefault(_normalize_name(alias_text), entity_id)
    return index


def _supported_vehicle_key(vehicle_name: str) -> str:
    normalized = _normalize_name(vehicle_name)
    if normalized == "iteams":
        return "iteams"
    return normalized


def _load_all_entities() -> dict[str, dict[str, Any]]:
    with get_kg_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, canonical_name, entity_type, aliases, identifiers, country, sources
            FROM kg_entities
            """
        ).fetchall()
    entities: dict[str, dict[str, Any]] = {}
    for row in rows:
        aliases = row["aliases"]
        if not isinstance(aliases, list):
            try:
                import json

                aliases = json.loads(aliases or "[]")
            except Exception:
                aliases = []
        identifiers = row["identifiers"]
        if not isinstance(identifiers, dict):
            try:
                import json

                identifiers = json.loads(identifiers or "{}")
            except Exception:
                identifiers = {}
        entities[str(row["id"])] = {
            "id": str(row["id"]),
            "canonical_name": str(row["canonical_name"] or ""),
            "entity_type": str(row["entity_type"] or ""),
            "aliases": aliases or [],
            "identifiers": identifiers or {},
            "country": str(row["country"] or ""),
            "sources": row["sources"] if isinstance(row["sources"], list) else [],
        }
    return entities


def _resolve_vehicle_entity(vehicle_name: str, entities: dict[str, dict[str, Any]], name_index: dict[str, str]) -> str:
    normalized = _normalize_name(vehicle_name)
    entity_id = name_index.get(normalized, "")
    if entity_id and entities.get(entity_id, {}).get("entity_type") == "contract_vehicle":
        return entity_id
    for candidate_id, entity in entities.items():
        if entity.get("entity_type") != "contract_vehicle":
            continue
        if _normalize_name(entity.get("canonical_name", "")) == normalized:
            return candidate_id
    return ""


def _collect_incumbents(
    vehicle_id: str,
    relationships: list[dict[str, Any]],
    entities: dict[str, dict[str, Any]],
) -> list[str]:
    incumbents: list[str] = []
    for relationship in relationships:
        rel_type = str(relationship.get("rel_type") or "")
        if rel_type not in CURRENT_VEHICLE_REL_TYPES:
            continue
        source_id = str(relationship.get("source_entity_id") or "")
        target_id = str(relationship.get("target_entity_id") or "")
        if target_id == vehicle_id and entities.get(source_id, {}).get("entity_type") == "company":
            incumbents.append(source_id)
    ordered: list[str] = []
    seen: set[str] = set()
    for entity_id in incumbents:
        if entity_id in seen:
            continue
        seen.add(entity_id)
        ordered.append(entity_id)
    return ordered


def _candidate_entity_ids(
    *,
    network: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    name_index: dict[str, str],
    observed_vendors: list[dict[str, Any]],
    vehicle_id: str,
    incumbent_ids: list[str],
) -> set[str]:
    candidates: set[str] = set()
    for entity_id, entity in (network.get("entities") or {}).items():
        if entity.get("entity_type") == "company":
            candidates.add(str(entity_id))
    for vendor in observed_vendors:
        entity_id = name_index.get(_normalize_name(vendor.get("vendor_name", "")), "")
        if entity_id and entities.get(entity_id, {}).get("entity_type") == "company":
            candidates.add(entity_id)
    candidates -= {vehicle_id}
    candidates -= set(incumbent_ids) - set()
    return candidates


def _find_relationships(
    relationships: list[dict[str, Any]],
    *,
    source_id: str = "",
    target_id: str = "",
    rel_types: set[str] | None = None,
    either_side: str = "",
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for relationship in relationships:
        rel_type = str(relationship.get("rel_type") or "")
        if rel_types and rel_type not in rel_types:
            continue
        left = str(relationship.get("source_entity_id") or "")
        right = str(relationship.get("target_entity_id") or "")
        if source_id and left != source_id:
            continue
        if target_id and right != target_id:
            continue
        if either_side and either_side not in {left, right}:
            continue
        matched.append(relationship)
    return matched


def _extract_candidate_signals(
    *,
    candidate_id: str,
    candidate_name: str,
    vehicle_id: str,
    incumbent_id: str,
    relationships: list[dict[str, Any]],
    observed_vendors: list[dict[str, Any]],
) -> CandidateSignals:
    normalized_candidate = _normalize_name(candidate_name)
    direct_vehicle_relationships = [
        relationship
        for relationship in relationships
        if str(relationship.get("rel_type") or "") in VEHICLE_SIGNAL_REL_TYPES
        and str(relationship.get("source_entity_id") or "") == candidate_id
        and str(relationship.get("target_entity_id") or "") == vehicle_id
    ]
    incumbent_relationships = [
        relationship
        for relationship in relationships
        if str(relationship.get("rel_type") or "") in TEAMING_REL_TYPES
        and {str(relationship.get("source_entity_id") or ""), str(relationship.get("target_entity_id") or "")} == {candidate_id, incumbent_id}
    ]
    other_vehicle_relationships = [
        relationship
        for relationship in relationships
        if str(relationship.get("source_entity_id") or "") == candidate_id
        and str(relationship.get("rel_type") or "") in VEHICLE_SIGNAL_REL_TYPES
        and str(relationship.get("target_entity_id") or "") != vehicle_id
    ]
    operational_paths: list[list[dict[str, Any]]] = []
    for target_id in [vehicle_id, incumbent_id]:
        path = find_shortest_path(candidate_id, target_id, max_depth=4)
        if path:
            operational_paths.append(path)
    observed_role = ""
    observed_award_amount = 0.0
    for vendor in observed_vendors:
        if _normalize_name(vendor.get("vendor_name", "")) != normalized_candidate:
            continue
        observed_role = str(vendor.get("role") or "")
        observed_award_amount = max(observed_award_amount, _safe_amount(vendor.get("award_amount")))
    return CandidateSignals(
        entity_id=candidate_id,
        entity_name=candidate_name,
        direct_vehicle_relationships=direct_vehicle_relationships,
        incumbent_relationships=incumbent_relationships,
        other_vehicle_relationships=other_vehicle_relationships,
        operational_paths=operational_paths,
        observed_role=observed_role,
        observed_award_amount=observed_award_amount,
    )


def _latest_signal_timestamp(relationships: list[dict[str, Any]]) -> str:
    stamps = [_best_claim_timestamp(relationship) for relationship in relationships]
    stamps = [stamp for stamp in stamps if stamp]
    return max(stamps) if stamps else ""


def _partner_classification(signals: CandidateSignals) -> tuple[str, float, str]:
    direct_vehicle = bool(signals.direct_vehicle_relationships)
    teamed = bool(signals.incumbent_relationships)
    teaming_confidence = max((float(item.get("confidence") or 0.0) for item in signals.incumbent_relationships), default=0.0)
    other_vehicle_presence = bool(signals.other_vehicle_relationships)
    operational_support = any(
        any(step.get("rel_type") in OPERATIONAL_REL_TYPES for step in path)
        for path in signals.operational_paths
    )
    observed = bool(signals.observed_role)
    latest_teaming = _latest_signal_timestamp(signals.incumbent_relationships)
    latest_other_vehicle = _latest_signal_timestamp(signals.other_vehicle_relationships)
    cooling_days = _days_between(latest_teaming, latest_other_vehicle) if latest_teaming and latest_other_vehicle else None

    if direct_vehicle:
        return (
            "incumbent-core",
            0.94 if observed else 0.9,
            "Observed as the active prime or incumbent on the current vehicle.",
        )

    if teamed and teaming_confidence >= 0.75 and not other_vehicle_presence:
        confidence = min(0.9, 0.72 + teaming_confidence * 0.2 + (0.05 if observed else 0.0))
        return (
            "locked",
            confidence,
            "Confirmed teammate relationship to the incumbent with no competing vehicle posture in the current graph.",
        )

    if teamed and cooling_days is not None and cooling_days > 180:
        confidence = min(0.82, 0.58 + (0.1 if observed else 0.0) + teaming_confidence * 0.15)
        return (
            "cooling",
            confidence,
            "Older incumbent tie exists, but fresher vehicle signals now point elsewhere.",
        )

    if teamed and other_vehicle_presence and teaming_confidence >= 0.5:
        confidence = min(0.84, 0.58 + teaming_confidence * 0.22 + (0.04 if observed else 0.0))
        return (
            "swing",
            confidence,
            "Incumbent tie exists, but the same company also carries independent vehicle posture elsewhere.",
        )

    if other_vehicle_presence and operational_support:
        confidence = min(0.74, 0.5 + (0.08 if observed else 0.0) + 0.08 * min(len(signals.operational_paths), 2))
        return (
            "recruitable",
            confidence,
            "Operational adjacency exists without a confirmed incumbent lock, making the company a plausible recruitable partner.",
        )

    if teamed:
        confidence = min(0.7, 0.42 + teaming_confidence * 0.3 + (0.05 if observed else 0.0))
        return (
            "emerging",
            confidence,
            "A live alignment signal exists, but the relationship is not corroborated strongly enough to treat as stable.",
        )

    if observed or other_vehicle_presence:
        confidence = 0.52 + (0.07 if observed else 0.0)
        return (
            "recruitable",
            confidence,
            "The company is present in the current market picture, but Helios does not yet see a confirmed incumbent lock.",
        )

    return (
        "emerging",
        0.4,
        "Signal density is still thin, so the company stays in watch-state rather than a stronger partner class.",
    )


def _should_skip_candidate(signals: CandidateSignals, relationships: list[dict[str, Any]]) -> bool:
    if signals.direct_vehicle_relationships or signals.incumbent_relationships or signals.other_vehicle_relationships or signals.observed_role:
        return False
    if not signals.operational_paths:
        return True
    if not any(
        any(step.get("rel_type") in OPERATIONAL_REL_TYPES for step in path)
        for path in signals.operational_paths
    ):
        return True
    for path in signals.operational_paths:
        path_types = {step.get("rel_type") for step in path}
        if path_types - OWNERSHIP_REL_TYPES:
            return False
    return True


def _summarize_assessed_partner(
    *,
    signals: CandidateSignals,
    classification: str,
    confidence: float,
    rationale: str,
    entities: dict[str, dict[str, Any]],
    incumbent_name: str,
) -> dict[str, Any]:
    evidence_relationships = [
        *signals.direct_vehicle_relationships[:2],
        *signals.incumbent_relationships[:2],
        *signals.other_vehicle_relationships[:2],
    ]
    evidence = []
    seen_evidence_keys: set[tuple[str, str, str]] = set()
    for relationship in evidence_relationships:
        described = _describe_relationship(relationship, entities)
        evidence_key = (described["source"], described["target"], described["rel_type"])
        if evidence_key in seen_evidence_keys:
            continue
        seen_evidence_keys.add(evidence_key)
        evidence.append(described)
    path_summaries: list[str] = []
    for path in signals.operational_paths[:2]:
        if not path:
            continue
        hops = []
        for step in path:
            hops.append(f"{_compact_name(step.get('from_name', ''))} -> {step.get('rel_type', '')} -> {_compact_name(step.get('to_name', ''))}")
        path_summaries.append(" | ".join(hops))

    observed_signals: list[str] = []
    if signals.observed_role:
        observed_signals.append(f"Observed in current vehicle roster as {signals.observed_role}.")
    if signals.direct_vehicle_relationships:
        observed_signals.append("Direct vehicle attachment exists in the graph.")
    if signals.incumbent_relationships:
        observed_signals.append(f"Teammate evidence links {signals.entity_name} to {incumbent_name}.")
    if signals.other_vehicle_relationships:
        observed_signals.append("Independent vehicle posture exists outside the current incumbent team.")
    if path_summaries:
        observed_signals.extend(path_summaries[:1])

    return {
        "entity_id": signals.entity_id,
        "entity_name": signals.entity_name,
        "display_name": _compact_name(signals.entity_name),
        "classification": classification,
        "state": "assessed",
        "confidence": round(confidence, 2),
        "confidence_label": _confidence_label(confidence),
        "rationale": rationale,
        "observed_signals": observed_signals,
        "observed_role": signals.observed_role or None,
        "observed_award_amount": signals.observed_award_amount or None,
        "evidence": evidence,
    }


def _top_conclusions(
    *,
    vehicle_name: str,
    incumbent_name: str,
    assessed_partners: list[dict[str, Any]],
) -> list[str]:
    conclusions: list[str] = []
    incumbent = next((item for item in assessed_partners if item["classification"] == "incumbent-core"), None)
    if incumbent:
        conclusions.append(
            f"{_compact_name(incumbent_name)} remains the incumbent-core read on {vehicle_name}, anchored by direct vehicle evidence rather than inference."
        )
    locked = next((item for item in assessed_partners if item["classification"] == "locked"), None)
    if locked:
        conclusions.append(
            f"{locked['display_name']} reads as locked to the incumbent, with confirmed teammate evidence and no competing alignment in the current graph."
        )
    swing = next((item for item in assessed_partners if item["classification"] == "swing"), None)
    if swing:
        conclusions.append(
            f"{swing['display_name']} is the clearest swing candidate: Helios sees an incumbent tie, but the company still carries independent vehicle posture elsewhere."
        )
    recruitable = next((item for item in assessed_partners if item["classification"] == "recruitable"), None)
    if recruitable:
        conclusions.append(
            f"{recruitable['display_name']} remains recruitable rather than locked, because Helios sees market relevance without a confirmed incumbent lock."
        )
    emerging = next((item for item in assessed_partners if item["classification"] == "emerging"), None)
    if emerging:
        conclusions.append(
            f"{emerging['display_name']} is still emerging. The signal is real enough to monitor, but not strong enough to write in as a stable teammate."
        )
    return conclusions[:4]


def _build_map_payload(
    *,
    vehicle_name: str,
    incumbent_name: str,
    assessed_partners: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes = [
        {
            "id": "vehicle",
            "label": vehicle_name,
            "kind": "vehicle",
            "state": "observed",
            "classification": "vehicle",
        }
    ]
    nodes.append(
        {
            "id": "incumbent",
            "label": _compact_name(incumbent_name),
            "kind": "company",
            "state": "observed",
            "classification": "incumbent-core",
        }
    )
    edges = [
        {
            "source": "incumbent",
            "target": "vehicle",
            "kind": "prime_contractor_of",
            "state": "observed",
        }
    ]
    for partner in assessed_partners:
        if partner["classification"] == "incumbent-core":
            continue
        node_id = partner["entity_id"]
        nodes.append(
            {
                "id": node_id,
                "label": partner["display_name"],
                "kind": "company",
                "state": partner["state"],
                "classification": partner["classification"],
                "confidence": partner["confidence"],
            }
        )
        edge_kind = "assessed_relationship"
        if partner["classification"] in {"locked", "swing", "cooling", "emerging"}:
            edge_kind = "teaming_posture"
            edges.append(
                {
                    "source": node_id,
                    "target": "incumbent",
                    "kind": edge_kind,
                    "state": partner["state"],
                    "classification": partner["classification"],
                }
            )
        else:
            edges.append(
                {
                    "source": node_id,
                    "target": "vehicle",
                    "kind": edge_kind,
                    "state": partner["state"],
                    "classification": partner["classification"],
                }
            )
    return {"nodes": nodes, "edges": edges}


def _scenario_assessment(
    assessed_partners: list[dict[str, Any]],
    scenario: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not scenario:
        return None
    recruit_partner = str(scenario.get("recruit_partner") or "").strip()
    if not recruit_partner:
        return None
    normalized = _normalize_name(recruit_partner)
    partner = next((item for item in assessed_partners if _normalize_name(item["entity_name"]) == normalized), None)
    if not partner:
        return {
            "state": "predicted",
            "recruit_partner": recruit_partner,
            "recommendation": "insufficient_signal",
            "confidence": 0.32,
            "confidence_label": "low",
            "rationale": "Helios does not yet have enough baseline evidence on that company to project a credible scenario move.",
        }
    classification = partner["classification"]
    if classification == "incumbent-core":
        recommendation = "low_feasibility"
        rationale = "This company is already the incumbent-core anchor. Treat it as the team to beat, not a recruitable partner."
        confidence = 0.92
    elif classification == "locked":
        recommendation = "low_feasibility"
        rationale = "The baseline read is locked to the incumbent, so a direct recruitment play currently looks low-probability."
        confidence = min(0.86, partner["confidence"])
    elif classification == "swing":
        recommendation = "competitive_flip"
        rationale = "This is the cleanest flip scenario in the current graph: Helios sees both incumbent affinity and independent market posture."
        confidence = min(0.8, partner["confidence"] + 0.05)
    elif classification == "recruitable":
        recommendation = "preferred_recruit"
        rationale = "The current graph shows market relevance without an incumbent lock, so this is the best recruiting posture Helios can support today."
        confidence = min(0.78, partner["confidence"] + 0.08)
    elif classification == "cooling":
        recommendation = "watch_then_recruit"
        rationale = "The incumbent relationship appears to be cooling. Keep watching for another corroborating signal before treating this as a firm recruiting play."
        confidence = min(0.74, partner["confidence"])
    else:
        recommendation = "early_move"
        rationale = "The signal is still early and lightly corroborated. This can be a differentiated move, but Helios cannot call it stable yet."
        confidence = min(0.68, partner["confidence"] + 0.06)
    return {
        "state": "predicted",
        "recruit_partner": partner["entity_name"],
        "classification_basis": classification,
        "recommendation": recommendation,
        "confidence": round(confidence, 2),
        "confidence_label": _confidence_label(confidence),
        "rationale": rationale,
    }


def build_teaming_intelligence(
    *,
    vehicle_name: str,
    observed_vendors: list[dict[str, Any]] | None = None,
    scenario: dict[str, Any] | None = None,
) -> dict[str, Any]:
    supported_key = _supported_vehicle_key(vehicle_name)
    report = {
        "analysis_scope": "iteams_recompete_v1",
        "supported": supported_key in V1_SUPPORTED_VEHICLES,
        "generated_at": _utc_now(),
        "vehicle_name": vehicle_name,
        "state_contract": {
            "observed": "Award records, graph relationships, and provenance-backed edges.",
            "assessed": "Helios partner classes derived from observed graph structure and current vehicle evidence.",
            "predicted": "Scenario outputs only. They do not become graph facts without analyst promotion.",
        },
        "graph_snapshot_signature": get_graph_snapshot_signature(),
    }
    if supported_key not in V1_SUPPORTED_VEHICLES:
        report.update(
            {
                "message": "Competitive teaming intelligence v1 is currently scoped to the ITEAMS recompete.",
                "observed_signals": [],
                "assessed_partners": [],
                "top_conclusions": [],
                "map": {"nodes": [], "edges": []},
                "scenario": _scenario_assessment([], scenario),
            }
        )
        return report

    observed_rows = [dict(row) for row in (observed_vendors or []) if isinstance(row, dict)]
    entities = _load_all_entities()
    name_index = _build_name_index(entities)
    vehicle_id = _resolve_vehicle_entity(vehicle_name, entities, name_index)
    if not vehicle_id:
        report.update(
            {
                "message": "ITEAMS is not present in the current knowledge graph.",
                "observed_signals": [],
                "assessed_partners": [],
                "top_conclusions": [],
                "map": {"nodes": [], "edges": []},
                "scenario": _scenario_assessment([], scenario),
            }
        )
        return report

    vehicle_network = get_multi_entity_network([vehicle_id], depth=1, include_provenance=True, max_claim_records=4, max_evidence_records=2)
    incumbent_ids = _collect_incumbents(vehicle_id, vehicle_network.get("relationships") or [], entities)
    roots = [vehicle_id, *incumbent_ids]
    full_network = get_multi_entity_network(roots, depth=2, include_provenance=True, max_claim_records=4, max_evidence_records=2)
    relationships = full_network.get("relationships") or []
    full_entities = full_network.get("entities") or {}
    for entity_id in roots:
        if entity_id not in full_entities and entity_id in entities:
            full_entities[entity_id] = entities[entity_id]

    if incumbent_ids:
        incumbent_id = incumbent_ids[0]
        incumbent_name = entities.get(incumbent_id, {}).get("canonical_name", "")
    else:
        incumbent_id = ""
        incumbent_name = ""

    candidate_ids = _candidate_entity_ids(
        network=full_network,
        entities=entities,
        name_index=name_index,
        observed_vendors=observed_rows,
        vehicle_id=vehicle_id,
        incumbent_ids=incumbent_ids,
    )

    assessed_partners: list[dict[str, Any]] = []
    if incumbent_id:
        incumbent_signals = _extract_candidate_signals(
            candidate_id=incumbent_id,
            candidate_name=entities.get(incumbent_id, {}).get("canonical_name", incumbent_name),
            vehicle_id=vehicle_id,
            incumbent_id=incumbent_id,
            relationships=relationships,
            observed_vendors=observed_rows,
        )
        classification, confidence, rationale = _partner_classification(incumbent_signals)
        assessed_partners.append(
            _summarize_assessed_partner(
                signals=incumbent_signals,
                classification=classification,
                confidence=confidence,
                rationale=rationale,
                entities=full_entities,
                incumbent_name=incumbent_name or incumbent_signals.entity_name,
            )
        )

    for candidate_id in sorted(candidate_ids):
        candidate_entity = entities.get(candidate_id)
        if not candidate_entity or candidate_entity.get("entity_type") != "company":
            continue
        candidate_name = candidate_entity.get("canonical_name", "")
        signals = _extract_candidate_signals(
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            vehicle_id=vehicle_id,
            incumbent_id=incumbent_id,
            relationships=relationships,
            observed_vendors=observed_rows,
        )
        if _should_skip_candidate(signals, relationships):
            continue
        classification, confidence, rationale = _partner_classification(signals)
        assessed_partners.append(
            _summarize_assessed_partner(
                signals=signals,
                classification=classification,
                confidence=confidence,
                rationale=rationale,
                entities=full_entities,
                incumbent_name=incumbent_name or "",
            )
        )

    assessed_partners.sort(
        key=lambda item: (
            CLASS_ORDER.index(item["classification"]) if item["classification"] in CLASS_ORDER else len(CLASS_ORDER),
            -float(item["confidence"]),
            item["entity_name"].lower(),
        )
    )

    observed_signals = []
    for relationship in relationships:
        rel_type = str(relationship.get("rel_type") or "")
        source_id = str(relationship.get("source_entity_id") or "")
        target_id = str(relationship.get("target_entity_id") or "")
        if rel_type not in CURRENT_VEHICLE_REL_TYPES | TEAMING_REL_TYPES | OPERATIONAL_REL_TYPES:
            continue
        if vehicle_id not in {source_id, target_id} and incumbent_id not in {source_id, target_id}:
            continue
        observed_signals.append(_describe_relationship(relationship, full_entities))

    top_conclusions = _top_conclusions(
        vehicle_name=vehicle_name,
        incumbent_name=incumbent_name or vehicle_name,
        assessed_partners=assessed_partners,
    )
    report.update(
        {
            "vehicle_entity_id": vehicle_id,
            "incumbent_prime": {
                "entity_id": incumbent_id,
                "name": incumbent_name,
            },
            "observed_signals": observed_signals[:10],
            "assessed_partners": assessed_partners,
            "top_conclusions": top_conclusions,
            "map": _build_map_payload(
                vehicle_name=vehicle_name,
                incumbent_name=incumbent_name or vehicle_name,
                assessed_partners=assessed_partners,
            ),
        }
    )
    report["scenario"] = _scenario_assessment(assessed_partners, scenario)
    return report
