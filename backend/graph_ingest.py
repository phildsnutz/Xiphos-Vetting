"""
Graph Ingestion Hook

Automatically extracts entities and relationships from enrichment reports
and feeds them into the knowledge graph. Runs as a post-enrichment step.

Relationship types extracted:
  - subcontractor_of / prime_contractor_of (USASpending subawards)
  - former_name (SEC EDGAR company history)
  - subsidiary_of / parent_of (SEC, OpenCorporates)
  - sanctioned_on (sanctions list matches)
  - litigant_in (RECAP court cases)
  - officer_of (SEC officer/director data)
  - contracts_with (FPDS, SAM.gov awards)
  - related_entity (cross-correlation aliases)
  - supplies_component_to / integrated_into (critical subsystem supply paths)
  - maintains_system_for / supports_site / substitutable_with / single_point_of_failure_for
  - owned_by / beneficially_owned_by / backed_by (ownership, financing, and control chains)

Entity types:
  - company, person, government_agency, court_case, sanctions_list
  - component, subsystem, holding_company
"""

import logging
import re
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learned_weighting import predict_edge_truth_probability
from ownership_control_intelligence import looks_like_descriptor_owner

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
GRAPH_CONSTRUCTION_GOLD_PATH = REPO_ROOT / "fixtures" / "adversarial_gym" / "graph_construction_gold_set_v1.json"
PILLAR_BRIEFING_PACK_PATH = REPO_ROOT / "fixtures" / "customer_demo" / "pillar_briefing_query_to_dossier_pack.json"

# Relationship type constants
REL_SUBCONTRACTOR = "subcontractor_of"
REL_PRIME_CONTRACTOR = "prime_contractor_of"
REL_FORMER_NAME = "former_name"
REL_SUBSIDIARY = "subsidiary_of"
REL_PARENT = "parent_of"
REL_SANCTIONED = "sanctioned_on"
REL_LITIGANT = "litigant_in"
REL_OFFICER = "officer_of"
REL_CONTRACTS_WITH = "contracts_with"
REL_ALIAS = "alias_of"
REL_RELATED = "related_entity"
REL_FILED_WITH = "filed_with"
REL_REGULATED_BY = "regulated_by"
REL_MENTIONED_WITH = "mentioned_with"
REL_SUPPLIES_COMPONENT_TO = "supplies_component_to"
REL_SUPPLIES_COMPONENT = "supplies_component"
REL_INTEGRATED_INTO = "integrated_into"
REL_MAINTAINS_SYSTEM_FOR = "maintains_system_for"
REL_SUPPORTS_SITE = "supports_site"
REL_SUBSTITUTABLE_WITH = "substitutable_with"
REL_SINGLE_POINT_OF_FAILURE_FOR = "single_point_of_failure_for"
REL_OWNED_BY = "owned_by"
REL_BENEFICIALLY_OWNED_BY = "beneficially_owned_by"
REL_BACKED_BY = "backed_by"
REL_LED_BY = "led_by"
REL_DEPENDS_ON_NETWORK = "depends_on_network"
REL_ROUTES_PAYMENT_THROUGH = "routes_payment_through"
REL_DISTRIBUTED_BY = "distributed_by"
REL_OPERATES_FACILITY = "operates_facility"
REL_SHIPS_VIA = "ships_via"
REL_DEPENDS_ON_SERVICE = "depends_on_service"

# -- Capture Intelligence edge family (Contract Vehicle Intelligence) --
REL_AWARDED_UNDER = "awarded_under"
REL_PREDECESSOR_OF = "predecessor_of"
REL_SUCCESSOR_OF = "successor_of"
REL_PERFORMED_AT = "performed_at"
REL_FUNDED_BY = "funded_by"
REL_COMPETED_ON = "competed_on"
REL_TEAMED_WITH = "teamed_with"
REL_INCUMBENT_ON = "incumbent_on"

_OFFICIAL_AUTHORITY_LEVELS = {
    "official_registry",
    "official_program_system",
    "official_regulatory",
    "official_judicial_record",
    "standards_modeled_fixture",
    "analyst_curated_fixture",
}

_GRAPH_EDGE_FAMILIES: dict[str, tuple[str, ...]] = {
    REL_OWNED_BY: ("ownership_control",),
    REL_BENEFICIALLY_OWNED_BY: ("ownership_control",),
    REL_PARENT: ("ownership_control",),
    REL_SUBSIDIARY: ("ownership_control",),
    REL_BACKED_BY: ("ownership_control", "intermediaries_and_services"),
    REL_LED_BY: ("ownership_control",),
    REL_OFFICER: ("ownership_control",),
    REL_CONTRACTS_WITH: ("contracts_and_programs",),
    REL_SUBCONTRACTOR: ("contracts_and_programs", "intermediaries_and_services"),
    REL_PRIME_CONTRACTOR: ("contracts_and_programs", "intermediaries_and_services"),
    REL_REGULATED_BY: ("official_and_regulatory",),
    REL_FILED_WITH: ("official_and_regulatory",),
    REL_SANCTIONED: ("sanctions_and_legal",),
    REL_LITIGANT: ("sanctions_and_legal",),
    REL_ALIAS: ("identity_and_alias",),
    REL_FORMER_NAME: ("identity_and_alias",),
    REL_MENTIONED_WITH: ("identity_and_alias",),
    REL_RELATED: ("identity_and_alias",),
    REL_SUPPLIES_COMPONENT_TO: ("cyber_supply_chain", "component_dependency"),
    REL_SUPPLIES_COMPONENT: ("cyber_supply_chain", "component_dependency"),
    REL_INTEGRATED_INTO: ("cyber_supply_chain", "component_dependency"),
    REL_MAINTAINS_SYSTEM_FOR: ("contracts_and_programs", "component_dependency"),
    REL_SUPPORTS_SITE: ("trade_and_logistics", "component_dependency"),
    REL_SUBSTITUTABLE_WITH: ("component_dependency",),
    REL_SINGLE_POINT_OF_FAILURE_FOR: ("component_dependency", "trade_and_logistics"),
    REL_DEPENDS_ON_NETWORK: ("cyber_supply_chain", "intermediaries_and_services"),
    REL_DEPENDS_ON_SERVICE: ("cyber_supply_chain", "intermediaries_and_services"),
    REL_DISTRIBUTED_BY: ("trade_and_logistics", "intermediaries_and_services"),
    REL_OPERATES_FACILITY: ("trade_and_logistics", "intermediaries_and_services"),
    REL_SHIPS_VIA: ("trade_and_logistics", "intermediaries_and_services"),
    REL_ROUTES_PAYMENT_THROUGH: ("trade_and_logistics", "finance_intermediary"),
    # -- Capture Intelligence --
    REL_AWARDED_UNDER: ("capture_intelligence", "contracts_and_programs"),
    REL_PREDECESSOR_OF: ("capture_intelligence",),
    REL_SUCCESSOR_OF: ("capture_intelligence",),
    REL_PERFORMED_AT: ("capture_intelligence", "trade_and_logistics"),
    REL_FUNDED_BY: ("capture_intelligence", "contracts_and_programs"),
    REL_COMPETED_ON: ("capture_intelligence",),
    REL_TEAMED_WITH: ("capture_intelligence", "contracts_and_programs"),
    REL_INCUMBENT_ON: ("capture_intelligence", "contracts_and_programs"),
}

_REQUIRED_EDGE_FAMILIES_BY_LANE: dict[str, tuple[str, ...]] = {
    "defense_counterparty_trust": ("ownership_control",),
    "counterparty": ("ownership_control",),
    "supplier_cyber_trust": ("ownership_control", "cyber_supply_chain"),
    "cyber": ("ownership_control", "cyber_supply_chain"),
    "export_authorization": ("ownership_control", "trade_and_logistics"),
    "export": ("ownership_control", "trade_and_logistics"),
    "contract_vehicle_intelligence": ("capture_intelligence", "contracts_and_programs"),
    "contract_vehicle": ("capture_intelligence", "contracts_and_programs"),
    "vehicle": ("capture_intelligence", "contracts_and_programs"),
}

# ---------------------------------------------------------------------------
# Relationship confidence scoring (Q3)
# Higher = stronger evidence supporting the relationship's existence
# ---------------------------------------------------------------------------
CONFIDENCE = {
    "deterministic":    0.95,  # Identifier match (CIK, LEI, CAGE)
    "structured_api":   0.85,  # Structured data from API (subaward records, SEC filings)
    "parsed_text":      0.70,  # Parsed from structured text (court docket listings)
    "inferred_text":    0.55,  # Inferred from title/detail text patterns
    "co_occurrence":    0.50,  # Co-occurrence in same enrichment report
    "news_mention":     0.40,  # Co-mentioned in news articles
}

_EDGE_INTELLIGENCE_THRESHOLDS = {
    "ownership_control": 0.76,
    "contracts_and_programs": 0.68,
    "trade_and_logistics": 0.68,
    "cyber_supply_chain": 0.66,
    "official_and_regulatory": 0.72,
    "sanctions_and_legal": 0.74,
    "identity_and_alias": 0.6,
    "intermediaries_and_services": 0.67,
    "component_dependency": 0.66,
    "finance_intermediary": 0.69,
    "other": 0.68,
}


def _json_field(value: object, fallback):
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _parse_graph_timestamp(value: object) -> datetime | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


_HISTORICAL_CLAIM_STATES = {"historical", "expired", "superseded"}


def _claim_is_historical(claim_record: dict[str, Any], *, now: datetime | None = None) -> bool:
    state = str((claim_record or {}).get("contradiction_state") or "").strip().lower()
    if state in _HISTORICAL_CLAIM_STATES:
        return True
    validity_end = _parse_graph_timestamp((claim_record or {}).get("validity_end"))
    if validity_end is not None and validity_end <= (now or datetime.now(timezone.utc)):
        return True
    return False


def _vendor_relationship_scope_keys(
    kg: Any,
    relationship_keys: set[tuple[str, str, str]],
    vendor_id: str,
) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]], set[tuple[str, str, str]], bool]:
    if not relationship_keys or not vendor_id or not callable(getattr(kg, "get_kg_conn", None)):
        return set(), set(), set(), False

    claimed_keys: set[tuple[str, str, str]] = set()
    vendor_active_claim_keys: set[tuple[str, str, str]] = set()
    vendor_historical_claim_keys: set[tuple[str, str, str]] = set()
    now = datetime.now(timezone.utc)
    with kg.get_kg_conn() as conn:
        claim_rows = conn.execute(
            """
            SELECT source_entity_id, target_entity_id, rel_type, vendor_id, contradiction_state, validity_end
            FROM kg_claims
            """
        ).fetchall()
    for row in claim_rows:
        key = (
            str(row["source_entity_id"] if not isinstance(row, tuple) else row[0] or ""),
            str(row["target_entity_id"] if not isinstance(row, tuple) else row[1] or ""),
            str(row["rel_type"] if not isinstance(row, tuple) else row[2] or ""),
        )
        if key not in relationship_keys:
            continue
        claimed_keys.add(key)
        row_vendor_id = str(row["vendor_id"] if not isinstance(row, tuple) else row[3] or "")
        if row_vendor_id != vendor_id:
            continue
        claim_record = {
            "contradiction_state": row["contradiction_state"] if not isinstance(row, tuple) else row[4],
            "validity_end": row["validity_end"] if not isinstance(row, tuple) else row[5],
        }
        if _claim_is_historical(claim_record, now=now):
            vendor_historical_claim_keys.add(key)
        else:
            vendor_active_claim_keys.add(key)
    use_historical_fallback = not vendor_active_claim_keys and bool(vendor_historical_claim_keys)
    return claimed_keys, vendor_active_claim_keys, vendor_historical_claim_keys, use_historical_fallback


def _relationship_temporal_state(rel: dict[str, Any], *, now: datetime, age_days: float | None) -> str:
    claim_records = [row for row in (rel.get("claim_records") or []) if isinstance(row, dict)]
    if any(str(row.get("contradiction_state") or "").strip().lower() in {"contradicted", "disputed", "challenged"} for row in claim_records):
        return "contradicted"
    if claim_records and all(_claim_is_historical(row, now=now) for row in claim_records):
        return "historical"

    validity_end = _parse_graph_timestamp(rel.get("validity_end"))
    if validity_end is None:
        for claim_record in claim_records:
            validity_end = _parse_graph_timestamp(claim_record.get("validity_end"))
            if validity_end is not None:
                break
    if validity_end is not None and validity_end <= now:
        return "historical"

    if age_days is None:
        return "unknown"
    if age_days >= 365:
        return "stale"
    if age_days >= 90:
        return "watch"
    return "active"


def _relationship_edge_families(rel_type: str) -> tuple[str, ...]:
    normalized = str(rel_type or "").strip().lower()
    if normalized in _GRAPH_EDGE_FAMILIES:
        return _GRAPH_EDGE_FAMILIES[normalized]
    families: list[str] = []
    if "own" in normalized or normalized.endswith("_parent") or normalized.endswith("_subsidiary"):
        families.append("ownership_control")
    if "ship" in normalized or "route" in normalized or "distribut" in normalized or "facility" in normalized:
        families.append("trade_and_logistics")
    if "depend" in normalized or "component" in normalized or "integrated" in normalized:
        families.append("cyber_supply_chain")
    if "regulat" in normalized or "filed" in normalized:
        families.append("official_and_regulatory")
    if "sanction" in normalized or "litig" in normalized:
        families.append("sanctions_and_legal")
    if "alias" in normalized or "former" in normalized or "mention" in normalized or "related" in normalized:
        families.append("identity_and_alias")
    return tuple(dict.fromkeys(families)) or ("other",)


def _relationship_authority_bucket(rel: dict[str, Any]) -> str:
    authority_levels: set[str] = set()
    claim_records = rel.get("claim_records") or []
    for claim_record in claim_records:
        if not isinstance(claim_record, dict):
            continue
        structured = claim_record.get("structured_fields") if isinstance(claim_record.get("structured_fields"), dict) else {}
        claim_authority = str(structured.get("authority_level") or "").strip().lower()
        if claim_authority:
            authority_levels.add(claim_authority)
        for evidence_record in claim_record.get("evidence_records") or []:
            if not isinstance(evidence_record, dict):
                continue
            authority = str(evidence_record.get("authority_level") or "").strip().lower()
            if authority:
                authority_levels.add(authority)

    if any(level in _OFFICIAL_AUTHORITY_LEVELS for level in authority_levels):
        return "official_or_modeled"
    if "first_party_self_disclosed" in authority_levels:
        return "first_party"
    if authority_levels and authority_levels <= {"third_party_public", "public_registry_aggregator"}:
        return "third_party_public_only"
    return "unspecified"


def _relationship_authority_levels(rel: dict[str, Any]) -> set[str]:
    authority_levels: set[str] = set()
    for claim_record in rel.get("claim_records") or []:
        if not isinstance(claim_record, dict):
            continue
        structured = claim_record.get("structured_fields") if isinstance(claim_record.get("structured_fields"), dict) else {}
        claim_authority = str(structured.get("authority_level") or "").strip().lower()
        if claim_authority:
            authority_levels.add(claim_authority)
        for evidence_record in claim_record.get("evidence_records") or []:
            if not isinstance(evidence_record, dict):
                continue
            authority = str(evidence_record.get("authority_level") or "").strip().lower()
            if authority:
                authority_levels.add(authority)
    return authority_levels


def _public_ownership_restraint_applies(
    rel: dict[str, Any],
    *,
    primary_family: str,
    authority_bucket: str,
    corroboration_count: int,
) -> bool:
    if primary_family != "ownership_control":
        return False
    rel_type = str(rel.get("rel_type") or "").strip().lower()
    if rel_type not in {REL_OWNED_BY, REL_BENEFICIALLY_OWNED_BY}:
        return False
    if authority_bucket != "third_party_public_only":
        return False
    authority_levels = _relationship_authority_levels(rel)
    if "public_registry_aggregator" in authority_levels:
        return False
    if corroboration_count > 1:
        return False
    return True


def _edge_intelligence_primary_family(families: tuple[str, ...]) -> str:
    if not families:
        return "other"
    for family in (
        "ownership_control",
        "contracts_and_programs",
        "trade_and_logistics",
        "cyber_supply_chain",
        "official_and_regulatory",
        "sanctions_and_legal",
        "identity_and_alias",
        "intermediaries_and_services",
        "component_dependency",
        "finance_intermediary",
    ):
        if family in families:
            return family
    return families[0]


def score_graph_relationship_intelligence(
    rel: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Synthesize relationship quality from provenance, freshness, and corroboration."""
    current_time = now or datetime.now(timezone.utc)
    rel_type = str(rel.get("rel_type") or "").strip().lower()
    families = _relationship_edge_families(rel_type)
    primary_family = _edge_intelligence_primary_family(families)
    claim_records = [row for row in (rel.get("claim_records") or []) if isinstance(row, dict)]
    claim_backed = bool(claim_records)
    evidence_backed = any((row.get("evidence_records") or []) for row in claim_records)
    authority_bucket = _relationship_authority_bucket(rel)
    corroboration_count = max(
        int(rel.get("corroboration_count") or 0),
        len(rel.get("data_sources") or []),
        len(claim_records),
        1,
    )
    edge_timestamp = _parse_graph_timestamp(rel.get("last_seen_at") or rel.get("created_at"))
    if edge_timestamp is None:
        for claim_record in claim_records:
            edge_timestamp = _parse_graph_timestamp(
                claim_record.get("last_observed_at")
                or claim_record.get("observed_at")
                or claim_record.get("updated_at")
            )
            if edge_timestamp is not None:
                break
    age_days = None
    if edge_timestamp is not None:
        age_days = max((current_time - edge_timestamp).total_seconds() / 86400.0, 0.0)
    temporal_state = _relationship_temporal_state(rel, now=current_time, age_days=age_days)

    model_input = dict(rel)
    model_input.update(
        {
            "authority_bucket": authority_bucket,
            "temporal_state": temporal_state,
            "primary_edge_family": primary_family,
            "edge_families": list(families),
            "claim_records": claim_records,
            "corroboration_count": corroboration_count,
            "descriptor_only": bool(rel.get("descriptor_only")),
            "legacy_unscoped": bool(rel.get("legacy_unscoped")),
        }
    )
    learned_truth = predict_edge_truth_probability(model_input)
    baseline_score = max(0.0, min(float(learned_truth.get("hierarchical_prior") or 0.5), 1.0))
    score = max(0.0, min(float(learned_truth.get("probability") or baseline_score), 1.0))
    strong_threshold = _EDGE_INTELLIGENCE_THRESHOLDS.get(primary_family, _EDGE_INTELLIGENCE_THRESHOLDS["other"])
    supported_threshold = max(strong_threshold - 0.14, 0.5)
    tentative_threshold = max(strong_threshold - 0.3, 0.35)
    promotion_restrained = _public_ownership_restraint_applies(
        rel,
        primary_family=primary_family,
        authority_bucket=authority_bucket,
        corroboration_count=corroboration_count,
    )
    if promotion_restrained:
        score = min(score, max(tentative_threshold + 0.02, 0.42))
    if temporal_state == "contradicted":
        tier = "disputed"
    elif score >= strong_threshold:
        tier = "strong"
    elif score >= supported_threshold:
        tier = "supported"
    elif score >= tentative_threshold:
        tier = "tentative"
    else:
        tier = "fragile"

    return {
        "intelligence_score": round(score, 4),
        "hierarchical_prior_score": round(baseline_score, 4),
        "heuristic_intelligence_score": round(baseline_score, 4),
        "learned_truth_probability": round(score, 4),
        "learned_truth_threshold": round(float(learned_truth.get("threshold") or 0.5), 4),
        "intelligence_score_source": "learned_edge_truth_v2" if int(learned_truth.get("training_count") or 0) > 0 else "hierarchical_edge_truth_fallback",
        "intelligence_tier": tier,
        "authority_bucket": authority_bucket,
        "temporal_state": temporal_state,
        "claim_backed": claim_backed,
        "evidence_backed": evidence_backed,
        "corroboration_count": corroboration_count,
        "promotion_restrained": promotion_restrained,
        "primary_edge_family": primary_family,
        "edge_families": list(families),
    }


def annotate_graph_relationship_intelligence(
    relationships: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for relationship in relationships or []:
        if not isinstance(relationship, dict):
            continue
        annotated_relationship = dict(relationship)
        annotated_relationship.update(score_graph_relationship_intelligence(annotated_relationship, now=now))
        annotated.append(annotated_relationship)
    return annotated


def build_graph_intelligence_summary(
    graph_summary: dict[str, Any] | None,
    *,
    workflow_lane: str | None = None,
    satisfied_required_edge_families: list[str] | None = None,
) -> dict[str, Any]:
    relationships = (
        [rel for rel in (graph_summary or {}).get("relationships", []) if isinstance(rel, dict)]
        if isinstance(graph_summary, dict)
        else []
    )
    now = datetime.now(timezone.utc)
    relationships = annotate_graph_relationship_intelligence(relationships, now=now)
    entity_count = int((graph_summary or {}).get("entity_count") or 0) if isinstance(graph_summary, dict) else 0
    relationship_count = len(relationships)
    edge_family_counts: dict[str, int] = {}
    edge_family_quality: dict[str, dict[str, float | int]] = {}
    official_edge_count = 0
    first_party_edge_count = 0
    public_only_edge_count = 0
    claim_backed_edges = 0
    evidence_backed_edges = 0
    contradicted_edges = 0
    legacy_unscoped_edges = 0
    low_confidence_edges = 0
    corroborated_edges = 0
    recent_edges = 0
    stale_edges = 0
    observed_edges = 0
    active_edges = 0
    watch_edges = 0
    historical_edges = 0
    temporal_state_counts: dict[str, int] = {}
    edge_intelligence_tier_counts: dict[str, int] = {}
    strong_edges = 0
    fragile_edges = 0
    disputed_edges = 0
    cumulative_intelligence_score = 0.0
    control_path_intelligence_score = 0.0
    control_path_intelligence_count = 0
    freshest_observation: datetime | None = None
    stalest_observation: datetime | None = None
    cumulative_age_days = 0.0
    control_path_count = 0
    intermediary_edge_count = 0

    for rel in relationships:
        rel_type = str(rel.get("rel_type") or "").strip().lower()
        families = tuple(rel.get("edge_families") or _relationship_edge_families(rel_type))
        primary_family = str(rel.get("primary_edge_family") or _edge_intelligence_primary_family(families))
        intelligence_score = float(rel.get("intelligence_score") or 0.0)
        intelligence_tier = str(rel.get("intelligence_tier") or "fragile")
        cumulative_intelligence_score += intelligence_score
        edge_intelligence_tier_counts[intelligence_tier] = edge_intelligence_tier_counts.get(intelligence_tier, 0) + 1
        if intelligence_tier == "strong":
            strong_edges += 1
        elif intelligence_tier == "fragile":
            fragile_edges += 1
        elif intelligence_tier == "disputed":
            disputed_edges += 1
        for family in families:
            edge_family_counts[family] = edge_family_counts.get(family, 0) + 1
            family_quality = edge_family_quality.setdefault(
                family,
                {
                    "edge_count": 0,
                    "avg_intelligence_score": 0.0,
                    "strong_edge_count": 0,
                    "fragile_edge_count": 0,
                    "disputed_edge_count": 0,
                },
            )
            family_quality["edge_count"] = int(family_quality["edge_count"]) + 1
            family_quality["avg_intelligence_score"] = float(family_quality["avg_intelligence_score"]) + intelligence_score
            if intelligence_tier == "strong":
                family_quality["strong_edge_count"] = int(family_quality["strong_edge_count"]) + 1
            elif intelligence_tier == "fragile":
                family_quality["fragile_edge_count"] = int(family_quality["fragile_edge_count"]) + 1
            elif intelligence_tier == "disputed":
                family_quality["disputed_edge_count"] = int(family_quality["disputed_edge_count"]) + 1
        if "ownership_control" in families:
            control_path_count += 1
            control_path_intelligence_score += intelligence_score
            control_path_intelligence_count += 1
        if "intermediaries_and_services" in families or "trade_and_logistics" in families or "finance_intermediary" in families:
            intermediary_edge_count += 1

        claim_records = [row for row in (rel.get("claim_records") or []) if isinstance(row, dict)]
        if claim_records:
            claim_backed_edges += 1
        if any((row.get("evidence_records") or []) for row in claim_records):
            evidence_backed_edges += 1
        if any(str(row.get("contradiction_state") or "").strip().lower() in {"contradicted", "disputed", "challenged"} for row in claim_records):
            contradicted_edges += 1
        if bool(rel.get("legacy_unscoped")):
            legacy_unscoped_edges += 1
        if float(rel.get("confidence") or 0.0) < 0.65:
            low_confidence_edges += 1
        if int(rel.get("corroboration_count") or 0) > 1:
            corroborated_edges += 1

        authority_bucket = _relationship_authority_bucket(rel)
        if authority_bucket == "official_or_modeled":
            official_edge_count += 1
        elif authority_bucket == "first_party":
            first_party_edge_count += 1
        elif authority_bucket == "third_party_public_only":
            public_only_edge_count += 1

        edge_timestamp = _parse_graph_timestamp(rel.get("last_seen_at") or rel.get("created_at"))
        if edge_timestamp is None:
            for claim_record in claim_records:
                edge_timestamp = _parse_graph_timestamp(
                    claim_record.get("last_observed_at")
                    or claim_record.get("observed_at")
                    or claim_record.get("updated_at")
                )
                if edge_timestamp is not None:
                    break
        if edge_timestamp is None:
            temporal_state = str(rel.get("temporal_state") or _relationship_temporal_state(rel, now=now, age_days=None))
            temporal_state_counts[temporal_state] = temporal_state_counts.get(temporal_state, 0) + 1
            if temporal_state == "historical":
                historical_edges += 1
            continue
        observed_edges += 1
        if freshest_observation is None or edge_timestamp > freshest_observation:
            freshest_observation = edge_timestamp
        if stalest_observation is None or edge_timestamp < stalest_observation:
            stalest_observation = edge_timestamp
        age_days = max((now - edge_timestamp).total_seconds() / 86400.0, 0.0)
        cumulative_age_days += age_days
        if age_days <= 90:
            recent_edges += 1
        if age_days >= 365:
            stale_edges += 1
        temporal_state = str(rel.get("temporal_state") or _relationship_temporal_state(rel, now=now, age_days=age_days))
        temporal_state_counts[temporal_state] = temporal_state_counts.get(temporal_state, 0) + 1
        if temporal_state == "active":
            active_edges += 1
        elif temporal_state == "watch":
            watch_edges += 1
        elif temporal_state == "historical":
            historical_edges += 1

    required_edge_families = list(_REQUIRED_EDGE_FAMILIES_BY_LANE.get(str(workflow_lane or "").strip().lower(), ()))
    satisfied_required_edge_families = [
        str(item).strip()
        for item in (satisfied_required_edge_families or [])
        if str(item).strip()
    ]
    externally_satisfied_edge_families = [
        family
        for family in required_edge_families
        if family in satisfied_required_edge_families and edge_family_counts.get(family, 0) <= 0
    ]
    present_required_edge_families = [
        family
        for family in required_edge_families
        if edge_family_counts.get(family, 0) > 0 or family in satisfied_required_edge_families
    ]
    missing_required_edge_families = [
        family
        for family in required_edge_families
        if edge_family_counts.get(family, 0) <= 0 and family not in satisfied_required_edge_families
    ]
    dominant_edge_family = max(edge_family_counts.items(), key=lambda item: (item[1], item[0]))[0] if edge_family_counts else None
    claim_coverage_pct = round(claim_backed_edges / relationship_count, 4) if relationship_count else 0.0
    evidence_coverage_pct = round(evidence_backed_edges / relationship_count, 4) if relationship_count else 0.0
    corroboration_pct = round(corroborated_edges / relationship_count, 4) if relationship_count else 0.0
    avg_edge_age_days = round(cumulative_age_days / observed_edges, 1) if observed_edges else None
    avg_edge_intelligence_score = round(cumulative_intelligence_score / relationship_count, 4) if relationship_count else 0.0
    control_path_avg_intelligence_score = (
        round(control_path_intelligence_score / control_path_intelligence_count, 4)
        if control_path_intelligence_count
        else 0.0
    )
    for family, metrics in edge_family_quality.items():
        edge_count = max(int(metrics.get("edge_count") or 0), 1)
        metrics["avg_intelligence_score"] = round(float(metrics.get("avg_intelligence_score") or 0.0) / edge_count, 4)
        metrics["primary_family"] = family

    return {
        "version": "graph-intelligence-v1",
        "workflow_lane": str(workflow_lane or "").strip().lower() or None,
        "thin_graph": entity_count <= 1 or relationship_count == 0,
        "thin_control_paths": control_path_count == 0,
        "dominant_edge_family": dominant_edge_family,
        "edge_family_counts": dict(sorted(edge_family_counts.items())),
        "required_edge_families": required_edge_families,
        "present_required_edge_families": present_required_edge_families,
        "externally_satisfied_edge_families": externally_satisfied_edge_families,
        "missing_required_edge_families": missing_required_edge_families,
        "claim_coverage_pct": claim_coverage_pct,
        "evidence_coverage_pct": evidence_coverage_pct,
        "corroborated_edge_pct": corroboration_pct,
        "avg_edge_intelligence_score": avg_edge_intelligence_score,
        "control_path_avg_intelligence_score": control_path_avg_intelligence_score,
        "strong_edge_count": strong_edges,
        "fragile_edge_count": fragile_edges,
        "disputed_edge_count": disputed_edges,
        "edge_intelligence_tier_counts": dict(sorted(edge_intelligence_tier_counts.items())),
        "edge_family_quality": dict(sorted(edge_family_quality.items())),
        "official_or_modeled_edge_count": official_edge_count,
        "first_party_edge_count": first_party_edge_count,
        "third_party_public_only_edge_count": public_only_edge_count,
        "contradicted_edge_count": contradicted_edges,
        "legacy_unscoped_edge_count": legacy_unscoped_edges,
        "low_confidence_edge_count": low_confidence_edges,
        "control_path_count": control_path_count,
        "intermediary_edge_count": intermediary_edge_count,
        "recent_edge_count": recent_edges,
        "stale_edge_count": stale_edges,
        "active_edge_count": active_edges,
        "watch_edge_count": watch_edges,
        "historical_edge_count": historical_edges,
        "temporal_state_counts": dict(sorted(temporal_state_counts.items())),
        "observed_edge_count": observed_edges,
        "avg_edge_age_days": avg_edge_age_days,
        "freshest_observation_at": freshest_observation.isoformat().replace("+00:00", "Z") if freshest_observation else None,
        "stalest_observation_at": stalest_observation.isoformat().replace("+00:00", "Z") if stalest_observation else None,
    }


def _safe_import_kg():
    """Safely import knowledge graph module. Returns None if unavailable."""
    try:
        import knowledge_graph as kg
        return kg
    except ImportError:
        logger.debug("Knowledge graph module not available")
        return None


def _safe_import_er():
    """Safely import entity resolution module."""
    try:
        import entity_resolution as er
        return er
    except ImportError:
        logger.debug("Entity resolution module not available")
        return None


def _safe_import_db():
    """Safely import main database module."""
    try:
        import db
        return db
    except ImportError:
        logger.debug("Database module not available")
        return None


def _generate_graph_entity_id(er, name: str, identifiers: dict, entity_type: str) -> str:
    """Mint type-aware IDs for non-company graph nodes to avoid entity-type collisions."""
    if identifiers:
        return er.generate_entity_id(name, identifiers)

    normalized_type = (entity_type or "unknown").strip().lower()
    type_safe = {
        "component",
        "subsystem",
        "holding_company",
        "bank",
        "telecom_provider",
        "distributor",
        "facility",
        "shipment_route",
        "service",
        "product",
        "cve",
        "kev_entry",
        "country",
        "export_control",
        "trade_show_event",
    }
    if normalized_type in type_safe:
        normalized_name = er.normalize_name(name) or name.strip().upper()
        hash_val = hashlib.md5(normalized_name.encode()).hexdigest()[:12]
        return f"{normalized_type}:{hash_val}"

    return er.generate_entity_id(name, identifiers)


# ---------------------------------------------------------------------------
# Merge-on-ingest deduplication
# ---------------------------------------------------------------------------

def _find_or_create_entity(kg, er, name: str, identifiers: dict, entity_type: str = "company",
                            country: str = "", sources: list = None, confidence: float = 0.7,
                            aliases: list = None) -> str:
    """
    Deduplicated entity creation. Before inserting a new entity, checks:
    1. Exact identifier match (CIK, LEI, UEI, CAGE) -> merge
    2. Fuzzy name match (Jaro-Winkler >= 0.88) -> merge
    3. No match -> create new

    Returns the entity ID (existing or newly created).
    """
    sources = sources or []
    aliases = aliases or []
    now = datetime.utcnow().isoformat() + "Z"

    # 1. Check by identifier (deterministic, highest confidence)
    for id_type in ("cik", "lei", "uei", "cage", "ein"):
        id_val = identifiers.get(id_type)
        if id_val:
            # Search existing entities
            candidate_id = er.generate_entity_id(name, {id_type: id_val})
            existing = kg.get_entity(candidate_id)
            if existing:
                # Merge: update aliases, sources, confidence
                _merge_entity(kg, existing, name, identifiers, sources, aliases, now)
                logger.debug("Dedup: merged '%s' into existing entity '%s' (identifier match: %s=%s)",
                           name, existing.canonical_name, id_type, id_val)
                return existing.id

    # 2. Check by fuzzy name match
    try:
        candidates = kg.find_entities_by_name(name, entity_type=entity_type, threshold=0.0)
        for candidate in candidates:
            # Use Jaro-Winkler for precise matching
            score = er.jaro_winkler(
                er.normalize_name(name),
                er.normalize_name(candidate.canonical_name)
            )
            if score >= 0.88:
                # Country match boosts confidence
                if country and candidate.country and candidate.country.upper() == country.upper():
                    score = min(1.0, score + 0.05)

                if score >= 0.88:
                    _merge_entity(kg, candidate, name, identifiers, sources, aliases, now)
                    logger.debug("Dedup: merged '%s' into '%s' (name match: %.2f)",
                               name, candidate.canonical_name, score)
                    return candidate.id

            # Also check aliases
            for alias in candidate.aliases:
                alias_score = er.jaro_winkler(
                    er.normalize_name(name),
                    er.normalize_name(alias)
                )
                if alias_score >= 0.88:
                    _merge_entity(kg, candidate, name, identifiers, sources, aliases, now)
                    logger.debug("Dedup: merged '%s' into '%s' (alias match: '%s', %.2f)",
                               name, candidate.canonical_name, alias, alias_score)
                    return candidate.id
    except Exception as e:
        logger.debug("Dedup name search failed for '%s': %s", name, e)

    # 3. No match found -> create new entity
    entity_id = _generate_graph_entity_id(er, name, identifiers, entity_type)
    entity = er.ResolvedEntity(
        id=entity_id,
        canonical_name=name,
        entity_type=entity_type,
        aliases=aliases,
        identifiers=identifiers,
        country=country,
        sources=sources,
        confidence=confidence,
        last_updated=now,
    )
    kg.save_entity(entity)
    return entity_id


def _merge_entity(kg, existing, new_name: str, new_identifiers: dict,
                  new_sources: list, new_aliases: list, now: str):
    """Merge new data into an existing entity without duplicating."""
    changed = False

    # Merge aliases (add new name as alias if different from canonical)
    current_aliases = set(existing.aliases)
    if new_name and new_name.upper() != existing.canonical_name.upper():
        if new_name not in current_aliases:
            current_aliases.add(new_name)
            changed = True

    for alias in new_aliases:
        if alias and alias.upper() != existing.canonical_name.upper() and alias not in current_aliases:
            current_aliases.add(alias)
            changed = True

    # Merge identifiers (don't overwrite, only add new)
    current_ids = dict(existing.identifiers)
    for k, v in new_identifiers.items():
        if v and k not in current_ids:
            current_ids[k] = v
            changed = True

    # Merge sources
    current_sources = set(existing.sources)
    for src in new_sources:
        if src and src not in current_sources:
            current_sources.add(src)
            changed = True

    if changed:
        existing.aliases = list(current_aliases)
        existing.identifiers = current_ids
        existing.sources = list(current_sources)
        existing.last_updated = now
        kg.save_entity(existing)


def ingest_enrichment_to_graph(
    vendor_id: str,
    vendor_name: str,
    enrichment_report: dict,
    vendor_input: dict | None = None,
) -> dict:
    """
    Extract entities and relationships from an enrichment report
    and store them in the knowledge graph.

    Pipeline:
      1. Create/update primary vendor entity (with dedup)
      2. Extract explicit relationships from report.relationships[]
      3. Extract entities/relationships from individual findings (Layer 1)
      4. Extract agency relationships from contract data
      5. Post-processing relationship inference (Layer 2)

    Returns summary stats: {entities_created, relationships_created, errors}.
    """
    kg = _safe_import_kg()
    er = _safe_import_er()

    if not kg or not er:
        return {"entities_created": 0, "relationships_created": 0, "errors": ["knowledge graph modules unavailable"]}

    stats = {
        "entities_created": 0,
        "relationships_created": 0,
        "errors": [],
        "vendor_id": vendor_id,
        "claims_pruned": 0,
        "relationships_pruned": 0,
    }

    try:
        # Initialize the KG database if needed
        kg.init_kg_db()
        identifiers = enrichment_report.get("identifiers", {})
        country = enrichment_report.get("country", "") or (
            vendor_input.get("country", "") if isinstance(vendor_input, dict) else ""
        )
        primary_entity_type = str(
            enrichment_report.get("primary_entity_type")
            or (vendor_input.get("primary_entity_type") if isinstance(vendor_input, dict) else "")
            or "company"
        ).strip().lower() or "company"
        aliases = _extract_aliases(vendor_name, enrichment_report)
        sources = list(enrichment_report.get("connector_status", {}).keys())

        entity_id = _find_or_create_entity(
            kg, er, vendor_name, identifiers,
            entity_type=primary_entity_type, country=country,
            sources=sources, confidence=0.95, aliases=aliases,
        )
        if callable(getattr(kg, "clear_vendor_graph_state", None)):
            kg.clear_vendor_graph_state(vendor_id, preserve_entity_ids=[entity_id])
        kg.link_entity_to_vendor(entity_id, vendor_id)
        stats["entities_created"] += 1

        # 2. Extract relationships from the enrichment report's relationship array
        for rel in enrichment_report.get("relationships", []):
            try:
                _ingest_relationship(kg, er, entity_id, vendor_name, rel, stats)
            except Exception as e:
                stats["errors"].append(f"relationship ingest: {e}")

        # 3. Extract entities/relationships from findings (Layer 1)
        for finding in enrichment_report.get("findings", []):
            try:
                _ingest_finding(kg, er, entity_id, vendor_name, finding, stats)
            except Exception as e:
                stats["errors"].append(f"finding ingest: {e}")

        # 4. Extract agency relationships from contract data
        _ingest_agency_relationships(kg, er, entity_id, vendor_name, enrichment_report, stats)

        # 5. Post-processing relationship inference (Layer 2)
        try:
            _infer_relationships(kg, er, entity_id, vendor_name, enrichment_report, stats)
        except Exception as e:
            stats["errors"].append(f"relationship inference: {e}")

        # 6. Modeled case-input graph context for adversarial and low-data scenarios
        try:
            _ingest_modeled_case_input_relationships(
                kg,
                er,
                entity_id,
                vendor_name,
                vendor_input if isinstance(vendor_input, dict) else {},
                stats,
            )
        except Exception as e:
            stats["errors"].append(f"modeled case input ingest: {e}")

        try:
            prune_stats = kg.retract_invalid_public_html_relationships(entity_id)
            stats["claims_pruned"] = int(prune_stats.get("claims_deleted") or 0)
            stats["relationships_pruned"] = int(prune_stats.get("relationships_deleted") or 0)
        except Exception as e:
            stats["errors"].append(f"invalid public_html cleanup: {e}")

        logger.info(
            "Graph ingest for %s: %d entities, %d relationships, %d errors",
            vendor_name, stats["entities_created"], stats["relationships_created"], len(stats["errors"]),
        )

    except Exception as e:
        stats["errors"].append(f"graph ingest top-level: {e}")
        logger.warning("Graph ingest failed for %s: %s", vendor_name, e)

    return stats


def _ingest_modeled_case_input_relationships(
    kg,
    er,
    primary_entity_id: str,
    vendor_name: str,
    vendor_input: dict[str, Any],
    stats: dict[str, Any],
) -> None:
    if not vendor_input:
        return

    ownership = vendor_input.get("ownership") if isinstance(vendor_input.get("ownership"), dict) else {}
    export_auth = (
        vendor_input.get("export_authorization")
        if isinstance(vendor_input.get("export_authorization"), dict)
        else {}
    )
    seed_metadata = (
        vendor_input.get("seed_metadata")
        if isinstance(vendor_input.get("seed_metadata"), dict)
        else {}
    )
    profile = str(vendor_input.get("profile") or "").strip().lower()
    product_terms = [
        str(term).strip()
        for term in (seed_metadata.get("product_terms") or [])
        if str(term).strip()
    ]
    parent_chain = _normalize_modeled_nodes(ownership.get("parent_chain"), "holding_company")
    financing_entities = _normalize_modeled_nodes(ownership.get("financing_entities"), "holding_company")
    payment_banks = _normalize_modeled_nodes(ownership.get("payment_banks"), "bank")
    network_providers = _normalize_modeled_nodes(seed_metadata.get("network_providers"), "telecom_provider")
    service_providers = _normalize_modeled_nodes(seed_metadata.get("service_providers"), "service")
    facilities = _normalize_modeled_nodes(seed_metadata.get("facilities"), "facility")
    distributors = _normalize_modeled_nodes(seed_metadata.get("distributors"), "distributor")
    transit_points = [
        str(value).strip().upper()
        for value in (export_auth.get("transit_countries") or [])
        if str(value).strip()
    ]
    component_suppliers = seed_metadata.get("component_suppliers") if isinstance(seed_metadata.get("component_suppliers"), list) else []

    modeled_relationships: list[dict[str, Any]] = []

    shell_layers = int(ownership.get("shell_layers") or 0)
    pep_connection = bool(ownership.get("pep_connection"))
    if shell_layers > 0:
        previous_name = vendor_name
        previous_type = "company"
        for layer_index in range(1, shell_layers + 1):
            layer_name = f"Unresolved Holding Layer {layer_index} for {vendor_name}"
            modeled_relationships.append(
                _modeled_case_relationship(
                    rel_type=REL_OWNED_BY,
                    source_entity=previous_name,
                    source_entity_type=previous_type,
                    target_entity=layer_name,
                    target_entity_type="holding_company",
                    evidence=(
                        f"Case input models {shell_layers} unresolved shell layer(s); "
                        f"layer {layer_index} remains a placeholder control node until named owners are resolved."
                    ),
                    claim_value=f"modeled_shell_layer_{layer_index}",
                    structured_fields={
                        "modeled_case_input": True,
                        "input_field": "ownership.shell_layers",
                        "shell_layers": shell_layers,
                        "layer_index": layer_index,
                    },
                    confidence=0.72 if layer_index == 1 else 0.66,
                )
            )
            previous_name = layer_name
            previous_type = "holding_company"
        if pep_connection:
            modeled_relationships.append(
                _modeled_case_relationship(
                    rel_type=REL_LED_BY,
                    source_entity=previous_name,
                    source_entity_type=previous_type,
                    target_entity=f"Potential PEP-Linked Controller ({vendor_name})",
                    target_entity_type="person",
                    evidence=(
                        "Case input flags PEP-linked control pressure but does not resolve a named controller. "
                        "A modeled placeholder preserves the control-risk path for adjudication."
                    ),
                    claim_value="modeled_pep_control_overlap",
                    structured_fields={
                        "modeled_case_input": True,
                        "input_field": "ownership.pep_connection",
                        "pep_connection": True,
                    },
                    confidence=0.62,
                )
            )

    if parent_chain:
        previous_name = vendor_name
        previous_type = "company"
        for index, parent in enumerate(parent_chain, start=1):
            modeled_relationships.append(
                _modeled_case_relationship(
                    rel_type=REL_OWNED_BY,
                    source_entity=previous_name,
                    source_entity_type=previous_type,
                    target_entity=parent["name"],
                    target_entity_type=parent.get("entity_type") or "holding_company",
                    country=parent.get("country") or "",
                    evidence=parent.get("evidence")
                    or (
                        f"Case input includes an explicit upstream ownership chain node at level {index}; "
                        "the node is retained as a modeled parent/control edge."
                    ),
                    claim_value=f"modeled_parent_chain_{index}",
                    structured_fields={
                        "modeled_case_input": True,
                        "input_field": "ownership.parent_chain",
                        "chain_index": index,
                    },
                    confidence=parent.get("confidence") or max(0.6, 0.82 - ((index - 1) * 0.04)),
                )
            )
            previous_name = parent["name"]
            previous_type = parent.get("entity_type") or "holding_company"

    for index, financier in enumerate(financing_entities, start=1):
        modeled_relationships.append(
            _modeled_case_relationship(
                rel_type=REL_BACKED_BY,
                source_entity=vendor_name,
                source_entity_type="company",
                target_entity=financier["name"],
                target_entity_type=financier.get("entity_type") or "holding_company",
                country=financier.get("country") or "",
                evidence=financier.get("evidence")
                or "Case input names a financing or sponsor entity that should remain visible in the ownership/control graph.",
                claim_value=f"modeled_financing_entity_{index}",
                structured_fields={
                    "modeled_case_input": True,
                    "input_field": "ownership.financing_entities",
                    "entity_index": index,
                },
                confidence=financier.get("confidence") or 0.72,
            )
        )

    for index, bank in enumerate(payment_banks, start=1):
        modeled_relationships.append(
            _modeled_case_relationship(
                rel_type=REL_ROUTES_PAYMENT_THROUGH,
                source_entity=vendor_name,
                source_entity_type="company",
                target_entity=bank["name"],
                target_entity_type=bank.get("entity_type") or "bank",
                country=bank.get("country") or "",
                evidence=bank.get("evidence")
                or "Case input names a payment or settlement intermediary that should remain explicit in the graph.",
                claim_value=f"modeled_payment_bank_{index}",
                structured_fields={
                    "modeled_case_input": True,
                    "input_field": "ownership.payment_banks",
                    "entity_index": index,
                },
                confidence=bank.get("confidence") or 0.7,
            )
        )

    destination_country = str(export_auth.get("destination_country") or "").strip().upper()
    destination_company = str(export_auth.get("destination_company") or "").strip()
    export_context = " ".join(
        str(value or "").strip()
        for value in (
            export_auth.get("request_type"),
            export_auth.get("access_context"),
            export_auth.get("end_use_summary"),
            export_auth.get("notes"),
        )
        if str(value or "").strip()
    ).lower()
    if destination_company:
        modeled_relationships.append(
            _modeled_case_relationship(
                rel_type=REL_DISTRIBUTED_BY,
                source_entity=vendor_name,
                source_entity_type="company",
                target_entity=destination_company,
                target_entity_type="distributor",
                country=destination_country,
                evidence=(
                    "Case input names a distribution or reseller intermediary for the export workflow; "
                    "the intermediary is retained as a modeled trade/logistics edge."
                ),
                claim_value="modeled_distribution_intermediary",
                structured_fields={
                    "modeled_case_input": True,
                    "input_field": "export_authorization.destination_company",
                    "destination_country": destination_country,
                },
                confidence=0.74,
            )
        )
    for index, distributor in enumerate(distributors, start=1):
        modeled_relationships.append(
            _modeled_case_relationship(
                rel_type=REL_DISTRIBUTED_BY,
                source_entity=vendor_name,
                source_entity_type="company",
                target_entity=distributor["name"],
                target_entity_type=distributor.get("entity_type") or "distributor",
                country=distributor.get("country") or destination_country,
                evidence=distributor.get("evidence")
                or "Seed metadata names an intermediary or reseller that should remain visible in the trade path.",
                claim_value=f"modeled_seed_distributor_{index}",
                structured_fields={
                    "modeled_case_input": True,
                    "input_field": "seed_metadata.distributors",
                    "entity_index": index,
                },
                confidence=distributor.get("confidence") or 0.72,
            )
        )
    if destination_country or export_context:
        route_suffix = destination_country or "unresolved-destination"
        modeled_relationships.append(
            _modeled_case_relationship(
                rel_type=REL_SHIPS_VIA,
                source_entity=vendor_name,
                source_entity_type="company",
                target_entity=f"{vendor_name} modeled route to {route_suffix}",
                target_entity_type="shipment_route",
                country=destination_country,
                evidence=(
                    "Case input includes destination and onward-delivery context, so a modeled shipment route is retained "
                    "until a concrete logistics chain is resolved."
                ),
                claim_value="modeled_export_route",
                structured_fields={
                    "modeled_case_input": True,
                    "input_field": "export_authorization.destination_country",
                    "destination_country": destination_country,
                    "context": export_context,
                },
                confidence=0.7,
            )
        )
    previous_route_name = None
    for index, transit_country in enumerate(transit_points, start=1):
        route_name = f"{vendor_name} modeled transit via {transit_country}"
        modeled_relationships.append(
            _modeled_case_relationship(
                rel_type=REL_SHIPS_VIA,
                source_entity=previous_route_name or vendor_name,
                source_entity_type="shipment_route" if previous_route_name else "company",
                target_entity=route_name,
                target_entity_type="shipment_route",
                country=transit_country,
                evidence=(
                    "Case input includes a transit-country chain, so the shipment route is modeled as a multi-hop logistics path."
                ),
                claim_value=f"modeled_transit_route_{index}",
                structured_fields={
                    "modeled_case_input": True,
                    "input_field": "export_authorization.transit_countries",
                    "chain_index": index,
                    "transit_country": transit_country,
                },
                confidence=max(0.62, 0.74 - ((index - 1) * 0.03)),
            )
        )
        previous_route_name = route_name

    if profile == "supplier_cyber_trust" and product_terms:
        component_term = next(
            (
                term
                for term in product_terms
                if not any(token in term.lower() for token in ("service", "network", "gateway", "telemetry"))
            ),
            product_terms[0],
        )
        subsystem_name = f"{vendor_name} mission stack"
        modeled_relationships.extend(
            [
                _modeled_case_relationship(
                    rel_type=REL_SUPPLIES_COMPONENT,
                    source_entity=vendor_name,
                    source_entity_type="company",
                    target_entity=component_term,
                    target_entity_type="component",
                    evidence=(
                        "Seed product terms identify a vendor-supplied component that should appear in the cyber supply-chain graph."
                    ),
                    claim_value="modeled_component_supply",
                    structured_fields={
                        "modeled_case_input": True,
                        "input_field": "seed_metadata.product_terms",
                        "product_term": component_term,
                    },
                    confidence=0.78,
                ),
                _modeled_case_relationship(
                    rel_type=REL_SUPPLIES_COMPONENT_TO,
                    source_entity=vendor_name,
                    source_entity_type="company",
                    target_entity=subsystem_name,
                    target_entity_type="subsystem",
                    evidence=(
                        "Seed product terms indicate a vendor-delivered subsystem or mission stack dependency."
                    ),
                    claim_value="modeled_subsystem_supply",
                    structured_fields={
                        "modeled_case_input": True,
                        "input_field": "seed_metadata.product_terms",
                        "product_terms": product_terms,
                    },
                    confidence=0.76,
                ),
                _modeled_case_relationship(
                    rel_type=REL_INTEGRATED_INTO,
                    source_entity=component_term,
                    source_entity_type="component",
                    target_entity=subsystem_name,
                    target_entity_type="subsystem",
                    evidence=(
                        "Component-to-subsystem integration is modeled from the analyst-supplied product term bundle."
                    ),
                    claim_value="modeled_component_integration",
                    structured_fields={
                        "modeled_case_input": True,
                        "input_field": "seed_metadata.product_terms",
                        "product_term": component_term,
                    },
                    confidence=0.74,
                ),
            ]
        )
        network_term = next(
            (
                term
                for term in product_terms
                if any(token in term.lower() for token in ("network", "gateway", "telemetry", "modem", "mesh"))
            ),
            "",
        )
        if network_term:
            modeled_relationships.append(
                _modeled_case_relationship(
                    rel_type=REL_DEPENDS_ON_NETWORK,
                    source_entity=vendor_name,
                    source_entity_type="company",
                    target_entity=network_term,
                    target_entity_type="telecom_provider",
                    evidence=(
                        "Seed product terms imply a network or telemetry dependency that should remain visible in the graph."
                    ),
                    claim_value="modeled_network_dependency",
                    structured_fields={
                        "modeled_case_input": True,
                        "input_field": "seed_metadata.product_terms",
                        "product_term": network_term,
                    },
                    confidence=0.7,
                )
            )
        service_term = next(
            (
                term
                for term in product_terms
                if any(token in term.lower() for token in ("service", "update", "patch", "signing", "cloud"))
            ),
            "",
        )
        if service_term:
            modeled_relationships.append(
                _modeled_case_relationship(
                    rel_type=REL_DEPENDS_ON_SERVICE,
                    source_entity=vendor_name,
                    source_entity_type="company",
                    target_entity=service_term,
                    target_entity_type="service",
                    evidence=(
                        "Seed product terms imply a service dependency that should remain explicit in the cyber supply-chain graph."
                    ),
                    claim_value="modeled_service_dependency",
                    structured_fields={
                        "modeled_case_input": True,
                        "input_field": "seed_metadata.product_terms",
                        "product_term": service_term,
                    },
                    confidence=0.7,
                )
            )
    for index, provider in enumerate(network_providers, start=1):
        modeled_relationships.append(
            _modeled_case_relationship(
                rel_type=REL_DEPENDS_ON_NETWORK,
                source_entity=vendor_name,
                source_entity_type="company",
                target_entity=provider["name"],
                target_entity_type=provider.get("entity_type") or "telecom_provider",
                country=provider.get("country") or "",
                evidence=provider.get("evidence")
                or "Seed metadata names a network dependency that should remain explicit in the cyber supply-chain graph.",
                claim_value=f"modeled_network_provider_{index}",
                structured_fields={
                    "modeled_case_input": True,
                    "input_field": "seed_metadata.network_providers",
                    "entity_index": index,
                },
                confidence=provider.get("confidence") or 0.72,
            )
        )
    for index, provider in enumerate(service_providers, start=1):
        modeled_relationships.append(
            _modeled_case_relationship(
                rel_type=REL_DEPENDS_ON_SERVICE,
                source_entity=vendor_name,
                source_entity_type="company",
                target_entity=provider["name"],
                target_entity_type=provider.get("entity_type") or "service",
                country=provider.get("country") or "",
                evidence=provider.get("evidence")
                or "Seed metadata names a service dependency that should remain explicit in the cyber supply-chain graph.",
                claim_value=f"modeled_service_provider_{index}",
                structured_fields={
                    "modeled_case_input": True,
                    "input_field": "seed_metadata.service_providers",
                    "entity_index": index,
                },
                confidence=provider.get("confidence") or 0.72,
            )
        )
    for index, facility in enumerate(facilities, start=1):
        modeled_relationships.append(
            _modeled_case_relationship(
                rel_type=REL_OPERATES_FACILITY,
                source_entity=vendor_name,
                source_entity_type="company",
                target_entity=facility["name"],
                target_entity_type=facility.get("entity_type") or "facility",
                country=facility.get("country") or "",
                evidence=facility.get("evidence")
                or "Seed metadata names a facility or hosted site that should remain explicit in the supply-chain graph.",
                claim_value=f"modeled_facility_{index}",
                structured_fields={
                    "modeled_case_input": True,
                    "input_field": "seed_metadata.facilities",
                    "entity_index": index,
                },
                confidence=facility.get("confidence") or 0.7,
            )
        )
    for index, supplier in enumerate(component_suppliers, start=1):
        if not isinstance(supplier, dict):
            continue
        supplier_name = str(supplier.get("supplier") or supplier.get("name") or "").strip()
        component_name = str(supplier.get("component") or "").strip()
        if not supplier_name or not component_name:
            continue
        subsystem_name = str(supplier.get("subsystem") or f"{vendor_name} mission stack").strip()
        supplier_type = str(supplier.get("supplier_type") or "company").strip().lower() or "company"
        supplier_country = str(supplier.get("country") or "").strip()
        supplier_evidence = str(supplier.get("evidence") or "").strip()
        supplier_confidence = float(supplier.get("confidence") or 0.74)
        modeled_relationships.extend(
            [
                _modeled_case_relationship(
                    rel_type=REL_SUPPLIES_COMPONENT,
                    source_entity=supplier_name,
                    source_entity_type=supplier_type,
                    target_entity=component_name,
                    target_entity_type="component",
                    country=supplier_country,
                    evidence=supplier_evidence
                    or "Seed metadata names a fourth-party component supplier that should remain explicit in the graph.",
                    claim_value=f"modeled_component_supplier_{index}",
                    structured_fields={
                        "modeled_case_input": True,
                        "input_field": "seed_metadata.component_suppliers",
                        "entity_index": index,
                    },
                    confidence=supplier_confidence,
                ),
                _modeled_case_relationship(
                    rel_type=REL_INTEGRATED_INTO,
                    source_entity=component_name,
                    source_entity_type="component",
                    target_entity=subsystem_name,
                    target_entity_type="subsystem",
                    country=supplier_country,
                    evidence=supplier_evidence
                    or "Fourth-party supplied component is modeled as integrated into the vendor subsystem.",
                    claim_value=f"modeled_component_integration_{index}",
                    structured_fields={
                        "modeled_case_input": True,
                        "input_field": "seed_metadata.component_suppliers",
                        "entity_index": index,
                    },
                    confidence=max(0.65, supplier_confidence - 0.02),
                ),
            ]
        )

    seen_keys: set[tuple[str, str, str]] = set()
    for rel in modeled_relationships:
        rel_key = (
            str(rel.get("type") or ""),
            str(rel.get("source_entity") or ""),
            str(rel.get("target_entity") or ""),
        )
        if rel_key in seen_keys:
            continue
        seen_keys.add(rel_key)
        _ingest_relationship(kg, er, primary_entity_id, vendor_name, rel, stats)


def _modeled_case_relationship(
    *,
    rel_type: str,
    source_entity: str,
    source_entity_type: str,
    target_entity: str,
    target_entity_type: str,
    evidence: str,
    claim_value: str,
    structured_fields: dict[str, Any],
    confidence: float,
    country: str = "",
) -> dict[str, Any]:
    return {
        "type": rel_type,
        "source_entity": source_entity,
        "source_entity_type": source_entity_type,
        "target_entity": target_entity,
        "target_entity_type": target_entity_type,
        "country": country,
        "data_source": "case_input_model",
        "confidence": confidence,
        "evidence": evidence,
        "claim_value": claim_value,
        "contradiction_state": "unreviewed",
        "structured_fields": structured_fields,
        "source_class": "analyst_fixture",
        "authority_level": "analyst_curated_fixture",
        "access_model": "case_input",
    }


def _normalize_modeled_nodes(values: Any, default_type: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if not values:
        return nodes
    if isinstance(values, (str, dict)):
        values = [values]
    for item in values:
        if isinstance(item, str):
            name = item.strip()
            if name:
                nodes.append({"name": name, "entity_type": default_type})
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("entity") or item.get("company") or "").strip()
        if not name:
            continue
        confidence_value = item.get("confidence")
        nodes.append(
            {
                "name": name,
                "entity_type": str(item.get("entity_type") or default_type).strip().lower() or default_type,
                "country": str(item.get("country") or "").strip(),
                "evidence": str(item.get("evidence") or "").strip(),
                "confidence": float(confidence_value) if confidence_value not in (None, "") else None,
            }
        )
    return nodes


def _extract_aliases(vendor_name: str, report: dict) -> list[str]:
    """Extract name aliases from enrichment data."""
    aliases = set()
    # SEC registered name
    sec_name = report.get("identifiers", {}).get("sec_registered_name", "")
    if sec_name and sec_name.upper() != vendor_name.upper():
        aliases.add(sec_name)

    # Former names from relationships
    for rel in report.get("relationships", []):
        if rel.get("type") == "former_name":
            fn = rel.get("entity", "")
            if fn and fn.upper() != vendor_name.upper():
                aliases.add(fn)

    return list(aliases)


def _ingest_relationship(kg, er, primary_entity_id: str, vendor_name: str, rel: dict, stats: dict):
    """Ingest a single relationship from the enrichment report."""
    rel_type = rel.get("type", "")
    vendor_id = stats.get("vendor_id", "")

    if rel_type in ("subcontractor_of", "prime_contractor_of"):
        if rel_type == "subcontractor_of":
            other_name = rel.get("target_entity", "")
        else:
            other_name = rel.get("source_entity", "")

        if not other_name or other_name.upper() == vendor_name.upper():
            return

        target_id = _find_or_create_entity(
            kg, er, other_name, {},
            entity_type="company",
            sources=[rel.get("data_source", "usaspending")],
            confidence=0.7,
        )
        stats["entities_created"] += 1

        # Determine direction
        if rel_type == "subcontractor_of":
            src, tgt = primary_entity_id, target_id
        else:
            src, tgt = target_id, primary_entity_id

        evidence = f"${rel.get('amount', 0):,.0f} across {rel.get('count', 0)} awards"
        kg.save_relationship(
            src,
            tgt,
            rel_type,
            confidence=0.8,
            data_source=rel.get("data_source", "usaspending"),
            evidence=evidence,
            vendor_id=vendor_id,
        )
        stats["relationships_created"] += 1

    elif rel_type == "former_name":
        entity_name = rel.get("entity", "")
        if entity_name:
            # Don't create a separate entity for former names, just record as alias
            pass

    elif rel_type in ("mentioned_with", "related_entity"):
        source_name = rel.get("source_entity", "")
        target_name = rel.get("target_entity", "")

        if source_name.upper() == vendor_name.upper():
            other_name = target_name
        elif target_name.upper() == vendor_name.upper():
            other_name = source_name
        else:
            other_name = target_name or source_name

        if not other_name or other_name.upper() == vendor_name.upper():
            return

        target_id = _find_or_create_entity(
            kg,
            er,
            other_name,
            {},
            entity_type=rel.get("entity_type", "company"),
            country=rel.get("country", ""),
            sources=[rel.get("data_source", "derived_relationship")],
            confidence=rel.get("confidence", CONFIDENCE["inferred_text"]),
        )
        stats["entities_created"] += 1
        vendor_id = stats.get("vendor_id", "")
        if vendor_id:
            kg.link_entity_to_vendor(target_id, vendor_id)

        kg.save_relationship(
            primary_entity_id,
            target_id,
            rel_type,
            confidence=rel.get("confidence", CONFIDENCE["inferred_text"]),
            data_source=rel.get("data_source", "derived_relationship"),
            evidence=rel.get("evidence", "") or f"Relationship imported from {rel.get('data_source', 'fixture')}",
            vendor_id=vendor_id,
        )
        stats["relationships_created"] += 1

    elif rel_type == "subsidiary_of":
        entity_name = rel.get("entity", "")
        jurisdiction = rel.get("jurisdiction", "")
        if entity_name and entity_name.upper() != vendor_name.upper():
            sub_id = _find_or_create_entity(
                kg, er, entity_name, {},
                entity_type="company", country=jurisdiction,
                sources=[rel.get("data_source", "sec_edgar")],
                confidence=rel.get("confidence", CONFIDENCE["structured_api"]),
            )
            stats["entities_created"] += 1
            # Link subsidiary entity to the same vendor case for graph visibility
            vendor_id = stats.get("vendor_id", "")
            if vendor_id:
                kg.link_entity_to_vendor(sub_id, vendor_id)
            # subsidiary -> parent relationship
            kg.save_relationship(
                sub_id, primary_entity_id, REL_SUBSIDIARY,
                confidence=rel.get("confidence", CONFIDENCE["structured_api"]),
                data_source=rel.get("data_source", "sec_edgar_ex21"),
                evidence=f"SEC Exhibit 21 subsidiary listing ({jurisdiction})",
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1

    elif rel_type == "former_name_match":
        # CIK validation found entity under a different name
        entity_name = rel.get("entity", "")
        if entity_name:
            target_id = _find_or_create_entity(
                kg, er, entity_name, {},
                entity_type="company", sources=["sec_edgar"],
                confidence=rel.get("match_score", 0.7),
            )
            stats["entities_created"] += 1
            kg.save_relationship(
                primary_entity_id, target_id, REL_RELATED,
                confidence=rel.get("match_score", 0.7),
                data_source="sec_edgar",
                evidence=f"Former name match: {rel.get('former_name', '')}",
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1

    elif rel_type in {
        REL_OFFICER,
        REL_CONTRACTS_WITH,
        REL_LITIGANT,
        REL_REGULATED_BY,
        REL_FILED_WITH,
        "has_vulnerability",
        "uses_product",
        REL_SUPPLIES_COMPONENT_TO,
        REL_SUPPLIES_COMPONENT,
        REL_INTEGRATED_INTO,
        REL_MAINTAINS_SYSTEM_FOR,
        REL_SUPPORTS_SITE,
        REL_SUBSTITUTABLE_WITH,
        REL_SINGLE_POINT_OF_FAILURE_FOR,
        REL_OWNED_BY,
        REL_BENEFICIALLY_OWNED_BY,
        REL_BACKED_BY,
        REL_LED_BY,
        REL_DEPENDS_ON_NETWORK,
        REL_ROUTES_PAYMENT_THROUGH,
        REL_DISTRIBUTED_BY,
        REL_OPERATES_FACILITY,
        REL_SHIPS_VIA,
        REL_DEPENDS_ON_SERVICE,
        REL_TEAMED_WITH,
        REL_COMPETED_ON,
        REL_INCUMBENT_ON,
        REL_PERFORMED_AT,
    }:
        source_name = (rel.get("source_entity") or vendor_name or "").strip()
        target_name = (rel.get("target_entity") or rel.get("entity") or "").strip()
        if not source_name or not target_name:
            return
        if rel_type in {REL_OWNED_BY, REL_BENEFICIALLY_OWNED_BY} and looks_like_descriptor_owner(target_name):
            logger.debug(
                "Skipping descriptor-only ownership relationship during graph ingest: %s -> %s",
                source_name,
                target_name,
            )
            return

        source_type = (rel.get("source_entity_type") or "company").strip().lower()
        target_type = (rel.get("target_entity_type") or "company").strip().lower()
        source_identifiers = rel.get("source_identifiers") or {}
        target_identifiers = rel.get("target_identifiers") or {}
        country = rel.get("country", "")
        data_source = rel.get("data_source", "component_supply_chain")
        confidence = rel.get("confidence", CONFIDENCE["structured_api"])
        evidence = rel.get("evidence", "") or f"Relationship imported from {data_source}"

        if source_name.upper() == vendor_name.upper():
            source_id = primary_entity_id
        else:
            source_id = _find_or_create_entity(
                kg,
                er,
                source_name,
                source_identifiers,
                entity_type=source_type,
                country=country,
                sources=[data_source],
                confidence=confidence,
            )
            stats["entities_created"] += 1

        target_id = _find_or_create_entity(
            kg,
            er,
            target_name,
            target_identifiers,
            entity_type=target_type,
            country=country,
            sources=[data_source],
            confidence=confidence,
        )
        stats["entities_created"] += 1

        vendor_id = stats.get("vendor_id", "")
        if vendor_id:
            kg.link_entity_to_vendor(source_id, vendor_id)
            kg.link_entity_to_vendor(target_id, vendor_id)

        kg.save_relationship(
            source_id,
            target_id,
            rel_type,
            confidence=confidence,
            data_source=data_source,
            evidence=evidence,
            observed_at=rel.get("observed_at", ""),
            valid_from=rel.get("valid_from", ""),
            valid_to=rel.get("valid_to", ""),
            claim_value=rel.get("claim_value", ""),
            contradiction_state=rel.get("contradiction_state", "unreviewed"),
            source_activity=rel.get("source_activity"),
            asserting_agent=rel.get("asserting_agent"),
            artifact_ref=rel.get("artifact_ref", ""),
            evidence_url=rel.get("evidence_url", "") or rel.get("url", ""),
            evidence_title=rel.get("evidence_title", "") or rel.get("title", ""),
            raw_data=rel.get("raw_data", {}) or {},
            structured_fields=rel.get("structured_fields", {}) or {},
            source_class=rel.get("source_class", ""),
            authority_level=rel.get("authority_level", ""),
            access_model=rel.get("access_model", ""),
            vendor_id=vendor_id,
        )
        stats["relationships_created"] += 1


def _load_graph_training_gold_rows(path: Path | None = None) -> list[dict[str, Any]]:
    fixture_path = path or GRAPH_CONSTRUCTION_GOLD_PATH
    if not fixture_path.exists():
        return []
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _graph_training_context_by_source() -> dict[str, dict[str, str]]:
    if not PILLAR_BRIEFING_PACK_PATH.exists():
        return {}
    try:
        payload = json.loads(PILLAR_BRIEFING_PACK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}

    context: dict[str, dict[str, str]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        case_payload = row.get("case_payload") if isinstance(row.get("case_payload"), dict) else {}
        source_name = str(case_payload.get("name") or "").strip()
        if not source_name:
            continue
        context[source_name.lower()] = {
            "country": str(case_payload.get("country") or "").strip(),
            "profile": str(case_payload.get("profile") or "").strip(),
            "program": str(case_payload.get("program") or "").strip(),
        }
    return context


def _graph_training_fixture_primary_entity_type(rows: list[dict[str, Any]]) -> str:
    relation_types = {
        str(row.get("relationship_type") or "").strip().lower()
        for row in rows
        if str(row.get("relationship_type") or "").strip()
    }
    if relation_types == {REL_INTEGRATED_INTO}:
        return "component"
    return "company"


def _graph_training_fixture_profile(rows: list[dict[str, Any]]) -> str:
    relation_types = {
        str(row.get("relationship_type") or "").strip().lower()
        for row in rows
        if str(row.get("relationship_type") or "").strip()
    }
    if relation_types & {
        REL_DEPENDS_ON_NETWORK,
        REL_DEPENDS_ON_SERVICE,
        REL_OPERATES_FACILITY,
        REL_INTEGRATED_INTO,
        REL_SUPPLIES_COMPONENT,
        REL_SUPPLIES_COMPONENT_TO,
        REL_MAINTAINS_SYSTEM_FOR,
        REL_SUPPORTS_SITE,
        REL_SUBSTITUTABLE_WITH,
        REL_SINGLE_POINT_OF_FAILURE_FOR,
    }:
        return "supplier_cyber_trust"
    if relation_types & {REL_DISTRIBUTED_BY, REL_SHIPS_VIA, REL_ROUTES_PAYMENT_THROUGH}:
        return "trade_compliance"
    return "defense_acquisition"


def _graph_training_fixture_target_type(rel_type: str, target_name: str) -> str:
    normalized_rel = str(rel_type or "").strip().lower()
    normalized_name = str(target_name or "").strip().lower()
    if normalized_rel == REL_CONTRACTS_WITH:
        return "government_agency"
    if normalized_rel == REL_LITIGANT:
        return "court_case"
    if normalized_rel == REL_ROUTES_PAYMENT_THROUGH:
        return "bank"
    if normalized_rel == REL_DEPENDS_ON_NETWORK:
        return "telecom_provider"
    if normalized_rel == REL_DEPENDS_ON_SERVICE:
        return "service"
    if normalized_rel == REL_OPERATES_FACILITY:
        return "facility"
    if normalized_rel == REL_SUPPORTS_SITE:
        return "facility"
    if normalized_rel == REL_DISTRIBUTED_BY:
        return "distributor"
    if normalized_rel == REL_SHIPS_VIA:
        return "shipment_route"
    if normalized_rel == REL_MAINTAINS_SYSTEM_FOR:
        if any(token in normalized_name for token in ("aircraft", "radar", "platform", "system", "sensor", "gateway", "terminal")):
            return "subsystem"
        return "company"
    if normalized_rel == REL_SUBSTITUTABLE_WITH:
        if any(token in normalized_name for token in ("module", "component", "firmware", "sensor", "gateway")):
            return "component"
        return "company"
    if normalized_rel == REL_SINGLE_POINT_OF_FAILURE_FOR:
        if any(token in normalized_name for token in ("site", "base", "depot", "hangar", "port", "warehouse", "facility")):
            return "facility"
        return "subsystem"
    if normalized_rel == REL_INTEGRATED_INTO:
        if any(token in normalized_name for token in ("module", "component", "firmware", "sensor", "gateway")):
            return "component"
        return "company"
    if normalized_rel == REL_BACKED_BY:
        if "bank" in normalized_name:
            return "bank"
        if any(token in normalized_name for token in ("capital", "holdings", "partners", "advisory", "fund")):
            return "holding_company"
        return "company"
    if normalized_rel in {REL_OWNED_BY, REL_PARENT, REL_SUBSIDIARY}:
        if any(token in normalized_name for token in ("capital", "holdings", "partners", "group", "fze")):
            return "holding_company"
        return "company"
    return "company"


def _graph_training_fixture_relationship(row: dict[str, Any], primary_entity_type: str) -> dict[str, Any]:
    rel_type = str(row.get("relationship_type") or "").strip().lower()
    source_name = str(row.get("source_entity") or "").strip()
    target_name = str(row.get("target_entity") or "").strip()
    evidence = str(row.get("evidence_text") or "").strip() or f"Graph training fixture relationship for {source_name}"
    edge_family = str(row.get("edge_family") or "").strip()
    source_entity_type = "component" if rel_type in {REL_INTEGRATED_INTO, REL_SINGLE_POINT_OF_FAILURE_FOR} else primary_entity_type
    target_entity_type = _graph_training_fixture_target_type(rel_type, target_name)
    return {
        "type": rel_type,
        "source_entity": source_name,
        "source_entity_type": source_entity_type,
        "target_entity": target_name,
        "target_entity_type": target_entity_type,
        "data_source": "graph_training_fixture",
        "confidence": 0.9,
        "evidence": evidence,
        "claim_value": f"graph_training_fixture::{rel_type}",
        "contradiction_state": "unreviewed",
        "structured_fields": {
            "graph_training_fixture": True,
            "edge_family": edge_family,
            "relationship_type": rel_type,
        },
        "source_class": "analyst_fixture",
        "authority_level": "analyst_curated_fixture",
        "access_model": "fixture_case_input",
    }


def ingest_graph_training_fixture_gold_set(path: str | Path | None = None) -> dict[str, Any]:
    rows = _load_graph_training_gold_rows(Path(path) if path else None)
    if not rows:
        return {
            "fixture_path": str(path or GRAPH_CONSTRUCTION_GOLD_PATH),
            "sources_seeded": 0,
            "rows_seeded": 0,
            "entities_created": 0,
            "relationships_created": 0,
            "errors": [],
            "source_summaries": [],
        }

    grouped_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        source_name = str(row.get("source_entity") or "").strip()
        if not source_name:
            continue
        grouped_rows.setdefault(source_name, []).append(row)

    context_by_source = _graph_training_context_by_source()
    source_summaries: list[dict[str, Any]] = []
    total_entities = 0
    total_relationships = 0
    errors: list[str] = []

    for source_name, source_rows in grouped_rows.items():
        primary_entity_type = _graph_training_fixture_primary_entity_type(source_rows)
        context = context_by_source.get(source_name.lower(), {})
        vendor_id = f"graph-training-fixture::{hashlib.sha1(source_name.encode('utf-8')).hexdigest()[:12]}"
        report = {
            "vendor_name": source_name,
            "country": context.get("country", ""),
            "primary_entity_type": primary_entity_type,
            "identifiers": {},
            "findings": [],
            "relationships": [
                _graph_training_fixture_relationship(row, primary_entity_type)
                for row in source_rows
            ],
            "connector_status": {
                "graph_training_fixture": "loaded",
            },
        }
        vendor_input = {
            "name": source_name,
            "country": context.get("country", ""),
            "profile": context.get("profile") or _graph_training_fixture_profile(source_rows),
            "program": context.get("program") or "graph_training_fixture",
            "primary_entity_type": primary_entity_type,
        }
        stats = ingest_enrichment_to_graph(vendor_id, source_name, report, vendor_input=vendor_input)
        total_entities += int(stats.get("entities_created") or 0)
        total_relationships += int(stats.get("relationships_created") or 0)
        errors.extend(str(item) for item in (stats.get("errors") or []) if str(item).strip())
        source_summaries.append(
            {
                "source_entity": source_name,
                "primary_entity_type": primary_entity_type,
                "relationship_count": len(source_rows),
                "entities_created": int(stats.get("entities_created") or 0),
                "relationships_created": int(stats.get("relationships_created") or 0),
            }
        )

    return {
        "fixture_path": str(path or GRAPH_CONSTRUCTION_GOLD_PATH),
        "sources_seeded": len(source_summaries),
        "rows_seeded": len(rows),
        "entities_created": total_entities,
        "relationships_created": total_relationships,
        "errors": errors,
        "source_summaries": source_summaries,
    }


def _ingest_finding(kg, er, primary_entity_id: str, vendor_name: str, finding: dict, stats: dict):
    """Extract entities and relationships from a single finding.

    Layer 1: parses the actual data structures produced by each connector.
    Confidence scoring reflects evidence quality:
      - Deterministic identifier match: 0.95
      - Structured API data (CIK, subaward records): 0.85
      - Parsed text (court docket details): 0.70
      - Inferred from title/detail text: 0.55
    """
    source = finding.get("source", "")
    category = finding.get("category", "")
    title = finding.get("title", "")
    detail = finding.get("detail", "")
    raw_data = finding.get("raw_data", {}) or {}
    vendor_id = stats.get("vendor_id", "")

    # ---- SEC EDGAR: extract related entities from filing search results ----
    if source == "sec_edgar" and category == "identity" and raw_data.get("cik"):
        cik = str(raw_data["cik"])
        # Extract entity name from title: "COMPANY NAME (TICKER) (CIK ...) - FORM (DATE)"
        # or "COMPANY NAME (CIK ...) - FORM (DATE)"
        entity_match = re.match(r"^(.+?)\s+(?:\(.+?\)\s+)?\(CIK\s", title)
        if not entity_match:
            entity_match = re.match(r"^(.+?)\s+-\s+\d", title)
        if entity_match:
            filing_entity = entity_match.group(1).strip()
            # Only create relationship if this is a DIFFERENT entity from the primary
            if filing_entity and filing_entity.upper() != vendor_name.upper():
                # Check if this is a name-similar entity (subsidiary, spin-off)
                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, vendor_name.upper(), filing_entity.upper()).ratio()
                if similarity < 0.85:  # Different enough to be a separate entity
                    related_id = _find_or_create_entity(
                        kg, er, filing_entity, {"cik": cik},
                        entity_type="company", sources=["sec_edgar"],
                        confidence=0.85,
                    )
                    stats["entities_created"] += 1
                    kg.save_relationship(
                        primary_entity_id, related_id, REL_FILED_WITH,
                        confidence=CONFIDENCE["structured_api"],
                        data_source="sec_edgar",
                        evidence=f"Co-appears in SEC EDGAR search results (CIK {cik})",
                        vendor_id=vendor_id,
                    )
                    stats["relationships_created"] += 1

    # ---- USASpending supply chain is handled by structured relationships ----
    if source == "usaspending" and category == "supply_chain":
        return

    # ---- USASpending: extract agencies from contracts findings ----
    if source == "usaspending" and category == "contracts":
        agencies = raw_data.get("agencies", [])
        for agency_name in agencies[:5]:
            if not agency_name:
                continue
            agency_id = _find_or_create_entity(
                kg, er, agency_name, {},
                entity_type="government_agency", country="US",
                sources=["usaspending"], confidence=0.95,
            )
            stats["entities_created"] += 1
            total_amount = raw_data.get("total_amount", 0)
            kg.save_relationship(
                primary_entity_id, agency_id, REL_CONTRACTS_WITH,
                confidence=CONFIDENCE["structured_api"],
                data_source="usaspending",
                evidence=f"Federal contract relationship (${total_amount:,.0f} total obligations)",
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1

    # ---- USASpending: extract agency from contract_detail title ----
    if source == "usaspending" and category == "contract_detail":
        # Title format: "Award: $X -- Agency Name"
        agency_match = re.search(r"-- (.+)$", title)
        if agency_match:
            agency_name = agency_match.group(1).strip()
            if agency_name and agency_name != "Unknown":
                agency_id = _find_or_create_entity(
                    kg, er, agency_name, {},
                    entity_type="government_agency", country="US",
                    sources=["usaspending"], confidence=0.9,
                )
                stats["entities_created"] += 1
                # Extract dollar amount from title
                amt_match = re.search(r"\$([0-9,]+)", title)
                amount_str = amt_match.group(1) if amt_match else "?"
                kg.save_relationship(
                    primary_entity_id, agency_id, REL_CONTRACTS_WITH,
                    confidence=CONFIDENCE["structured_api"],
                    data_source="usaspending",
                    evidence=f"Contract award: ${amount_str}",
                    vendor_id=vendor_id,
                )
                stats["relationships_created"] += 1

    # ---- RECAP courts: create court case entities ----
    if source == "recap_courts" and category == "litigation":
        # Two patterns to match:
        # Pattern A (high-risk case listing): "  - Case Name (court, date, docket)"
        cases_a = re.findall(r"- (.+?) \((\w+), (\d{4}-\d{2}-\d{2}), ([^)]+)\)", detail)
        # Pattern B (simpler): "  - Case Name (court, date)"
        if not cases_a:
            cases_a = re.findall(r"- (.+?) \((\w+), (\d{4}-\d{2}-\d{2})", detail)
            cases_a = [(n, c, d, "") for n, c, d in cases_a]

        for case_name, court, date, docket in cases_a[:8]:
            case_name = case_name.strip()[:100]
            if not case_name:
                continue
            ids = {"court": court, "date_filed": date}
            if docket:
                ids["docket_number"] = docket.strip()
            case_eid = _find_or_create_entity(
                kg, er, case_name, ids,
                entity_type="court_case", sources=["recap_courts"],
                confidence=CONFIDENCE["parsed_text"],
            )
            stats["entities_created"] += 1

            sev = finding.get("severity", "info")
            kg.save_relationship(
                primary_entity_id, case_eid, REL_LITIGANT,
                confidence=CONFIDENCE["parsed_text"],
                data_source="recap_courts",
                evidence=f"Court: {court}, Filed: {date}, Severity: {sev}",
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1

        # If there are no structured cases but title mentions docket count,
        # create a summary court entity for the court system
        if not cases_a:
            courts_match = re.search(r"Courts: (.+?)(?:\n|$)", detail)
            if courts_match:
                court_ids = [c.strip() for c in courts_match.group(1).split(",")]
                for court_id in court_ids[:3]:
                    if court_id:
                        court_eid = _find_or_create_entity(
                            kg, er, f"U.S. {court_id.upper()} Court", {"court_id": court_id},
                            entity_type="court_case", sources=["recap_courts"],
                            confidence=CONFIDENCE["inferred_text"],
                        )
                        stats["entities_created"] += 1
                        kg.save_relationship(
                            primary_entity_id, court_eid, REL_LITIGANT,
                            confidence=CONFIDENCE["inferred_text"],
                            data_source="recap_courts",
                            evidence=f"Federal docket(s) in {court_id}",
                            vendor_id=vendor_id,
                        )
                        stats["relationships_created"] += 1

    # ---- Sanctions: create sanctions list entities and link ----
    if category in ("screening", "clearance", "sanctions", "international_debarment",
                     "pep_screening", "foreign_agent") and source in (
        "dod_sam_exclusions", "trade_csl", "un_sanctions", "ofac_sdn",
        "eu_sanctions", "uk_hmt_sanctions", "opensanctions_pep", "worldbank_debarred",
    ):
        severity = finding.get("severity", "info")
        if severity in ("high", "critical", "medium"):
            list_id = _find_or_create_entity(
                kg, er, _sanctions_list_name(source), {"list_id": source},
                entity_type="sanctions_list", sources=[source], confidence=1.0,
            )
            stats["entities_created"] += 1
            kg.save_relationship(
                primary_entity_id, list_id, REL_SANCTIONED,
                confidence=CONFIDENCE["deterministic"],
                data_source=source,
                evidence=title[:200],
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1

    # ---- Cross-correlation: near-miss alias detection ----
    if source == "cross_correlation" and "near-miss" in title.lower():
        match = re.search(r"Near-miss match: '(.+?)' on", title)
        if match:
            alias_name = match.group(1)
            alias_id = _find_or_create_entity(
                kg, er, alias_name, {},
                entity_type="company", sources=["cross_correlation"],
                confidence=finding.get("confidence", 0.5),
            )
            stats["entities_created"] += 1
            kg.save_relationship(
                primary_entity_id, alias_id, REL_ALIAS,
                confidence=CONFIDENCE["inferred_text"],
                data_source="cross_correlation",
                evidence=title[:200],
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1

    # ---- SAM.gov: extract registration details ----
    if source == "sam_gov" and category == "registration":
        # SAM registrations confirm the entity exists in federal procurement
        # The entity is already the primary; no new entities to create here
        pass

    # ---- EPA ECHO: environmental facility relationships ----
    if source == "epa_echo" and category == "environmental_compliance":
        # Extract EPA registry IDs from title if present
        epa_match = re.search(r"Registry ID:\s*(\d+)", detail)
        if epa_match:
            # These are facilities, not separate entities
            pass


def _ingest_agency_relationships(kg, er, primary_entity_id: str, vendor_name: str, report: dict, stats: dict):
    """Extract government agency relationships from non-USASpending sources.

    Note: USASpending agency extraction is now handled by _ingest_finding()
    for both 'contracts' and 'contract_detail' categories. This function
    handles FPDS, SAM.gov, and other sources that may reference agencies.
    """
    vendor_id = stats.get("vendor_id", "")
    for finding in report.get("findings", []):
        source = finding.get("source", "")
        # Skip usaspending -- already handled in _ingest_finding
        if source == "usaspending":
            continue

        raw = finding.get("raw_data", {}) or {}
        agencies = raw.get("agencies", [])
        if not agencies:
            continue

        for agency_name in agencies[:3]:
            if not agency_name:
                continue
            agency_id = _find_or_create_entity(
                kg, er, agency_name, {},
                entity_type="government_agency", country="US",
                sources=[source], confidence=0.9,
            )
            stats["entities_created"] += 1
            kg.save_relationship(
                primary_entity_id, agency_id, REL_CONTRACTS_WITH,
                confidence=CONFIDENCE["structured_api"],
                data_source=source,
                evidence=f"Agency relationship via {source}",
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1


def _infer_relationships(kg, er, primary_entity_id: str, vendor_name: str, report: dict, stats: dict):
    """Layer 2: Post-processing relationship inference.

    After all entities are created from explicit data, this pass infers
    relationships from co-occurrence patterns and cross-source signals:
      1. News co-mentions: companies named together in media articles
      2. Regulatory co-filing: entities appearing in same SEC filing search
      3. Shared identifiers: entities sharing a common identifier prefix or parent
      4. Cross-domain correlation: entities linked by compound risk patterns
    """
    findings = report.get("findings", [])
    vendor_id = stats.get("vendor_id", "")

    # 1. News co-mentions: extract company names from news headlines
    news_entities = set()
    for f in findings:
        if f.get("source") in ("google_news", "gdelt_media") and f.get("category") == "media":
            t = f.get("title", "")
            # Look for company names in news titles (capitalized multi-word phrases)
            # that aren't the vendor itself
            candidates = re.findall(r"(?:^|\s)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", t)
            for c in candidates:
                c = c.strip()
                if len(c) > 5 and c.upper() != vendor_name.upper():
                    news_entities.add(c)

    for entity_name in list(news_entities)[:5]:
        # Only create relationship if the entity already exists in the graph
        try:
            existing = kg.find_entities_by_name(entity_name, entity_type="company", threshold=0.0)
            for candidate in existing:
                score = er.jaro_winkler(
                    er.normalize_name(entity_name),
                    er.normalize_name(candidate.canonical_name),
                )
                if score >= 0.85 and candidate.id != primary_entity_id:
                    kg.save_relationship(
                        primary_entity_id, candidate.id, REL_MENTIONED_WITH,
                        confidence=CONFIDENCE["news_mention"],
                        data_source="news_co_mention",
                        evidence="Co-mentioned in media coverage",
                        vendor_id=vendor_id,
                    )
                    stats["relationships_created"] += 1
                    break
        except Exception as e:
            logger.warning(f"Relationship inference failed for media co-mention: {e}")

    # 2. Cross-domain correlation: link entities from compound risk findings
    for f in findings:
        if f.get("source") == "cross_correlation" and f.get("category") == "risk_pattern":
            detail = f.get("detail", "")
            # Extract entity names mentioned in cross-domain findings
            # These are already-known entities referenced in compound patterns
            entity_refs = re.findall(r"'([^']+)'", detail)
            for ref in entity_refs:
                if ref and ref.upper() != vendor_name.upper() and len(ref) > 3:
                    try:
                        existing = kg.find_entities_by_name(ref, entity_type="company", threshold=0.0)
                        for candidate in existing:
                            score = er.jaro_winkler(
                                er.normalize_name(ref),
                                er.normalize_name(candidate.canonical_name),
                            )
                            if score >= 0.85 and candidate.id != primary_entity_id:
                                kg.save_relationship(
                                    primary_entity_id, candidate.id, REL_RELATED,
                                    confidence=CONFIDENCE["co_occurrence"],
                                    data_source="cross_correlation",
                                    evidence=f.get("title", "")[:200],
                                    vendor_id=vendor_id,
                                )
                                stats["relationships_created"] += 1
                                break
                    except Exception as e:
                        logger.warning(f"Cross-domain correlation failed: {e}")


def _sanctions_list_name(source: str) -> str:
    """Human-readable name for a sanctions source."""
    names = {
        "dod_sam_exclusions": "SAM.gov Exclusions List",
        "trade_csl": "Consolidated Screening List",
        "un_sanctions": "UN Security Council Sanctions",
        "ofac_sdn": "OFAC SDN List",
        "eu_sanctions": "EU Sanctions List",
        "uk_hmt_sanctions": "UK HMT Sanctions List",
        "opensanctions_pep": "PEP Screening Database",
        "worldbank_debarred": "World Bank Debarment List",
    }
    return names.get(source, source)


_WEAK_GRAPH_NAMES = {
    "",
    "entity",
    "entity name",
    "name",
    "name of entity",
    "name of subsidiary",
    "subsidiary name",
    "unknown",
    "n/a",
    "not available",
    "not applicable",
}


def _is_weak_graph_name(name: str) -> bool:
    """Detect generic or placeholder entity names that should not be shown verbatim."""
    normalized = re.sub(r"\s+", " ", (name or "").strip().lower())
    if normalized in _WEAK_GRAPH_NAMES:
        return True
    if normalized.startswith("entity ") and len(normalized.split()) <= 3:
        return True
    return False


def _infer_graph_entity_type(entity_id: str) -> str:
    """Best-effort entity type inference for legacy relationship endpoints."""
    if not entity_id:
        return "unknown"

    prefix = entity_id.split(":", 1)[0].lower()
    if prefix in {"cik", "lei", "uei", "cage", "duns", "ein", "entity"}:
        return "company"
    if prefix == "person":
        return "person"
    if prefix == "product":
        return "product"
    if prefix == "cve":
        return "cve"
    if prefix == "kev":
        return "kev_entry"
    if prefix == "component":
        return "component"
    if prefix == "subsystem":
        return "subsystem"
    if prefix == "holding_company":
        return "holding_company"
    if prefix == "bank":
        return "bank"
    if prefix == "telecom_provider":
        return "telecom_provider"
    if prefix == "distributor":
        return "distributor"
    if prefix == "facility":
        return "facility"
    if prefix == "shipment_route":
        return "shipment_route"
    if prefix == "service":
        return "service"
    if prefix in {"event", "trade", "show"}:
        return "trade_show_event"
    if prefix in {"court", "case", "docket"}:
        return "court_case"
    if prefix in {"agency", "sam", "fpds"}:
        return "government_agency"
    if prefix in {"ofac", "sdn", "sanction"}:
        return "sanctions_list"
    return "unknown"


def _fallback_graph_label(entity_id: str) -> str:
    """Readable fallback name for graph endpoints missing a persisted entity row."""
    if not entity_id:
        return "Unknown entity"

    prefix, _, raw = entity_id.partition(":")
    if not raw:
        return entity_id

    cleaned = re.sub(r"[_-]+", " ", raw).strip()
    clipped = cleaned[:24] + ("..." if len(cleaned) > 24 else "")

    label_map = {
        "cik": f"CIK {raw}",
        "lei": f"LEI {raw.upper()}",
        "uei": f"UEI {raw.upper()}",
        "cage": f"CAGE {raw.upper()}",
        "duns": f"DUNS {raw}",
        "ein": f"EIN {raw}",
        "person": cleaned or "Person",
        "entity": f"Unresolved company {raw[:12].upper()}",
        "product": cleaned.title() if cleaned else "Product",
        "cve": raw.upper(),
        "kev": f"KEV {raw.upper()}",
        "component": cleaned.title() if cleaned else "Component",
        "subsystem": cleaned.title() if cleaned else "Subsystem",
        "holding_company": cleaned.title() if cleaned else "Holding company",
        "bank": cleaned.title() if cleaned else "Bank",
        "telecom_provider": cleaned.title() if cleaned else "Telecom provider",
        "distributor": cleaned.title() if cleaned else "Distributor",
        "facility": cleaned.title() if cleaned else "Facility",
        "shipment_route": cleaned.title() if cleaned else "Shipment route",
        "service": cleaned.title() if cleaned else "Service",
        "court": cleaned or "Court case",
        "case": cleaned or "Court case",
        "docket": f"Docket {clipped}",
        "agency": cleaned.title() if cleaned else "Government agency",
        "ofac": f"OFAC record {clipped}",
        "sdn": f"SDN record {clipped}",
        "sanction": f"Sanctions record {clipped}",
    }
    return label_map.get(prefix.lower(), f"{prefix.upper()} {clipped}".strip())


def _fallback_graph_identifiers(entity_id: str) -> dict:
    """Derive lightweight identifiers from an identifier-based entity ID."""
    prefix, _, raw = entity_id.partition(":")
    if prefix and raw and prefix.lower() in {"cik", "lei", "uei", "cage", "duns", "ein"}:
        return {prefix.lower(): raw}
    return {}


def _normalize_graph_country(country: str) -> str:
    if not country:
        return ""
    normalized = country.strip()
    if normalized.lower() in {"unknown", "n/a", "not available", "not applicable"}:
        return ""
    return normalized


def _pick_graph_display_name(entity: dict) -> str:
    """Choose the best human-readable label for a graph entity payload."""
    entity_id = entity.get("id", "")
    canonical_name = (entity.get("canonical_name") or "").strip()
    if canonical_name and canonical_name != entity_id and not _is_weak_graph_name(canonical_name):
        return canonical_name

    for alias in entity.get("aliases", []) or []:
        alias = (alias or "").strip()
        if alias and alias != entity_id and not _is_weak_graph_name(alias):
            return alias

    identifiers = entity.get("identifiers") or {}
    for key in ("cik", "lei", "uei", "cage", "duns", "ein"):
        if identifiers.get(key):
            return _fallback_graph_label(f"{key}:{identifiers[key]}")

    sources = set(entity.get("sources", []) or [])
    entity_type = entity.get("entity_type", "unknown")
    if "sec_edgar_ex21" in sources:
        return "Unresolved SEC subsidiary"
    if entity_type == "court_case" or "recap_courts" in sources:
        return "Unresolved court case"
    if entity_type == "government_agency":
        return "Unresolved government agency"
    if entity_type == "person":
        return "Unresolved person"
    if entity_type == "component":
        return "Unresolved component"
    if entity_type == "subsystem":
        return "Unresolved subsystem"
    if entity_type == "holding_company":
        return "Unresolved holding company"
    if entity_type == "bank":
        return "Unresolved bank"
    if entity_type == "telecom_provider":
        return "Unresolved telecom provider"
    if entity_type == "distributor":
        return "Unresolved distributor"
    if entity_type == "facility":
        return "Unresolved facility"
    if entity_type == "shipment_route":
        return "Unresolved shipment route"
    if entity_type == "service":
        return "Unresolved service"
    if entity_type == "sanctions_list" or sources.intersection(
        {"trade_csl", "ofac_sdn", "dod_sam_exclusions", "worldbank_debarred", "un_sanctions"}
    ):
        return "Unresolved sanctions record"

    return _fallback_graph_label(entity_id)


def _normalize_graph_entity_payload(entity: dict) -> dict:
    """Sanitize a graph entity before returning it to the API/UI."""
    normalized = dict(entity)
    normalized["country"] = _normalize_graph_country(entity.get("country", ""))
    normalized["canonical_name"] = _pick_graph_display_name(entity)
    return normalized


def _hydrate_missing_graph_entities(kg, all_entities: dict, relationships: list[dict]) -> dict:
    """
    Close the graph entity set over relationship endpoints.

    Legacy graph rows can reference endpoint IDs that are not present in the
    entity payload. We first hydrate anything that exists in kg_entities, then
    fall back to readable synthetic nodes so the API contract stays whole.
    """
    endpoint_ids = set()
    for rel in relationships:
        source_id = rel.get("source_entity_id", "")
        target_id = rel.get("target_entity_id", "")
        if source_id:
            endpoint_ids.add(source_id)
        if target_id:
            endpoint_ids.add(target_id)

    missing_ids = sorted(endpoint_ids.difference(all_entities.keys()))
    if not missing_ids:
        return all_entities

    hydrated_entities: dict[str, dict] = {}
    try:
        placeholders = ",".join("?" for _ in missing_ids)
        with kg.get_kg_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, last_updated
                FROM kg_entities
                WHERE id IN ({placeholders})
                """,
                missing_ids,
            ).fetchall()
        for row in rows:
            aliases = _json_field(row["aliases"], [])
            identifiers = _json_field(row["identifiers"], {})
            sources = _json_field(row["sources"], [])
            hydrated_entities[row["id"]] = {
                "id": row["id"],
                "canonical_name": row["canonical_name"],
                "entity_type": row["entity_type"] or _infer_graph_entity_type(row["id"]),
                "aliases": aliases,
                "identifiers": identifiers,
                "country": row["country"] or "",
                "sources": sources,
                "confidence": row["confidence"] if row["confidence"] is not None else 0.5,
                "last_updated": row["last_updated"],
            }
    except Exception as exc:
        logger.debug("Graph entity hydration fallback engaged: %s", exc)

    for entity_id in missing_ids:
        if entity_id in hydrated_entities:
            all_entities[entity_id] = _normalize_graph_entity_payload(hydrated_entities[entity_id])
            continue

        all_entities[entity_id] = _normalize_graph_entity_payload({
            "id": entity_id,
            "canonical_name": _fallback_graph_label(entity_id),
            "entity_type": _infer_graph_entity_type(entity_id),
            "aliases": [],
            "identifiers": _fallback_graph_identifiers(entity_id),
            "country": "",
            "sources": ["graph_fallback"],
            "confidence": 0.35,
            "last_updated": "",
            "synthetic": True,
        })

    return all_entities


def _vendor_root_fallback(vendor_id: str) -> dict | None:
    """Build a stable synthetic vendor root when a case has no graph entities yet."""
    db_mod = _safe_import_db()
    if not db_mod:
        return None

    vendor = db_mod.get_vendor(vendor_id)
    if not vendor:
        return None

    er = _safe_import_er()
    vendor_name = str(vendor.get("name") or vendor_id)
    identifiers = {
        key: value
        for key in ("lei", "cage", "uei", "duns", "ein")
        if (value := vendor.get(key))
    }
    root_entity_id = (
        _generate_graph_entity_id(er, vendor_name, identifiers, "company")
        if er
        else f"vendor:{vendor_id}"
    )

    return _normalize_graph_entity_payload(
        {
            "id": root_entity_id,
            "canonical_name": vendor_name,
            "entity_type": "company",
            "aliases": [],
            "identifiers": identifiers,
            "country": vendor.get("country") or "",
            "sources": ["vendor_record_fallback"],
            "confidence": 0.35,
            "last_updated": vendor.get("updated_at") or "",
            "synthetic": True,
        }
    )


def get_vendor_graph_summary(
    vendor_id: str,
    depth: int = 3,
    *,
    include_provenance: bool = True,
    max_claim_records: int = 4,
    max_evidence_records: int = 4,
) -> dict:
    """
    Get a summary of the knowledge graph for a specific vendor.
    Used by the API to power the graph visualization.
    """
    kg = _safe_import_kg()
    if not kg:
        return {"error": "knowledge graph unavailable"}

    try:
        depth = max(1, min(int(depth), 4))
        kg.init_kg_db()
        entities = kg.get_vendor_entities(vendor_id)

        if not entities:
            root_entity = _vendor_root_fallback(vendor_id)
            summary = {
                "vendor_id": vendor_id,
                "graph_depth": depth,
                "root_entity_id": root_entity["id"] if root_entity else None,
                "root_entity_ids": [root_entity["id"]] if root_entity else [],
                "entity_count": 1 if root_entity else 0,
                "relationship_count": 0,
                "entities": [root_entity] if root_entity else [],
                "relationships": [],
            }
            summary["intelligence"] = build_graph_intelligence_summary(summary)
            return summary

        root_entity_ids = [entity.id for entity in entities if getattr(entity, "id", "")]
        if callable(getattr(kg, "get_multi_entity_network", None)):
            network = kg.get_multi_entity_network(
                root_entity_ids,
                depth=depth,
                include_provenance=False,
                max_claim_records=max_claim_records,
                max_evidence_records=max_evidence_records,
            )
            all_entities = dict(network.get("entities", {}) or {})
            all_relationships = list(network.get("relationships", []) or [])
            root_entity_id = network.get("root_entity_id")
        else:
            # Legacy fallback for older knowledge_graph modules.
            all_entities = {}
            all_relationships = []
            root_entity_id = entities[0].id if entities else None
            for entity in entities:
                network = kg.get_entity_network(
                    entity.id,
                    depth=depth,
                    include_provenance=False,
                    max_claim_records=max_claim_records,
                    max_evidence_records=max_evidence_records,
                )
                all_entities.update(network.get("entities", {}))
                all_relationships.extend(network.get("relationships", []))

        unique_rels = _aggregate_graph_relationships(all_relationships)
        unique_rels = _prefilter_relationships_to_vendor_scope(kg, unique_rels, vendor_id)
        if (
            include_provenance
            and vendor_id
            and unique_rels
            and callable(getattr(kg, "attach_relationship_provenance", None))
        ):
            unique_rels = kg.attach_relationship_provenance(
                unique_rels,
                max_claim_records=max(1, int(max_claim_records or 1)),
                max_evidence_records=max(1, int(max_evidence_records or 1)),
            )
            unique_rels = _filter_relationships_to_vendor_claims(unique_rels, vendor_id)
        if not include_provenance:
            for rel in unique_rels:
                rel["claim_records"] = []

        unique_rels = annotate_graph_relationship_intelligence(unique_rels)

        all_entities = _hydrate_missing_graph_entities(kg, all_entities, unique_rels)
        visible_entity_ids = {entity.id for entity in entities}
        for rel in unique_rels:
            source_id = str(rel.get("source_entity_id") or "")
            target_id = str(rel.get("target_entity_id") or "")
            if source_id:
                visible_entity_ids.add(source_id)
            if target_id:
                visible_entity_ids.add(target_id)
        all_entities = {
            entity_id: _normalize_graph_entity_payload(entity)
            for entity_id, entity in all_entities.items()
            if not visible_entity_ids or entity_id in visible_entity_ids
        }

        # Compute entity type distribution
        type_dist = {}
        for e in all_entities.values():
            t = e.get("entity_type", "unknown")
            type_dist[t] = type_dist.get(t, 0) + 1

        # Compute relationship type distribution
        rel_dist = {}
        for r in unique_rels:
            t = r.get("rel_type", "unknown")
            rel_dist[t] = rel_dist.get(t, 0) + 1

        summary = {
            "vendor_id": vendor_id,
            "root_entity_id": root_entity_id,
            "root_entity_ids": root_entity_ids,
            "graph_depth": depth,
            "entity_count": len(all_entities),
            "relationship_count": len(unique_rels),
            "entity_type_distribution": type_dist,
            "relationship_type_distribution": rel_dist,
            "entities": list(all_entities.values()),
            "relationships": unique_rels,
        }
        summary["intelligence"] = build_graph_intelligence_summary(summary)
        return summary

    except Exception as e:
        logger.warning("Graph summary failed for vendor %s: %s", vendor_id, e)
        return {"error": str(e)}


def _prefilter_relationships_to_vendor_scope(kg: Any, relationships: list[dict], vendor_id: str) -> list[dict]:
    if not vendor_id or not relationships or not callable(getattr(kg, "get_kg_conn", None)):
        return relationships

    relationship_keys = {
        (
            str(rel.get("source_entity_id") or ""),
            str(rel.get("target_entity_id") or ""),
            str(rel.get("rel_type") or ""),
        )
        for rel in relationships
    }
    if not relationship_keys:
        return relationships

    claimed_keys, vendor_active_claim_keys, vendor_historical_claim_keys, use_historical_fallback = _vendor_relationship_scope_keys(
        kg,
        relationship_keys,
        vendor_id,
    )

    filtered: list[dict] = []
    for rel in relationships:
        key = (
            str(rel.get("source_entity_id") or ""),
            str(rel.get("target_entity_id") or ""),
            str(rel.get("rel_type") or ""),
        )
        if key in vendor_active_claim_keys:
            filtered.append(rel)
            continue
        if use_historical_fallback and key in vendor_historical_claim_keys:
            rel_copy = dict(rel)
            rel_copy["vendor_scope_state"] = "historical"
            rel_copy["temporal_state"] = rel_copy.get("temporal_state") or "historical"
            filtered.append(rel_copy)
            continue
        if key not in claimed_keys:
            rel_copy = dict(rel)
            rel_copy["legacy_unscoped"] = True
            rel_copy["claim_records"] = []
            filtered.append(rel_copy)
    return filtered


def _aggregate_graph_relationships(all_relationships: list[dict]) -> list[dict]:
    """Collapse duplicate logical edges while preserving corroborating provenance."""
    aggregated: dict[tuple[str, str, str], dict] = {}

    for rel in all_relationships:
        key = (rel["source_entity_id"], rel["target_entity_id"], rel["rel_type"])
        data_source = (rel.get("data_source") or "").strip()
        evidence = (rel.get("evidence") or "").strip()
        created_at = rel.get("created_at") or ""
        first_seen_at = rel.get("first_seen_at") or created_at
        last_seen_at = rel.get("last_seen_at") or created_at
        rel_id = rel.get("id")
        rel_ids = list(rel.get("relationship_ids", []) or [])
        rel_sources = list(rel.get("data_sources", []) or [])
        rel_snippets = list(rel.get("evidence_snippets", []) or [])

        current = aggregated.get(key)
        if current is None:
            current = {
                "id": rel_id,
                "source_entity_id": rel["source_entity_id"],
                "target_entity_id": rel["target_entity_id"],
                "rel_type": rel["rel_type"],
                "confidence": rel.get("confidence", 0.0),
                "data_source": data_source,
                "evidence": evidence,
                "created_at": created_at,
                "first_seen_at": first_seen_at,
                "last_seen_at": last_seen_at,
                "corroboration_count": 0,
                "data_sources": [],
                "evidence_snippets": [],
                "claim_records": [],
                "_source_set": set(),
                "_evidence_set": set(),
                "_ids": [],
                "_claim_ids": set(),
            }
            aggregated[key] = current

        current["confidence"] = max(current["confidence"], rel.get("confidence", 0.0))
        if rel_id is not None and rel_id not in current["_ids"]:
            current["_ids"].append(rel_id)
        for existing_id in rel_ids:
            if existing_id is not None and existing_id not in current["_ids"]:
                current["_ids"].append(existing_id)

        if first_seen_at:
            if not current["first_seen_at"] or first_seen_at < current["first_seen_at"]:
                current["first_seen_at"] = first_seen_at
        if last_seen_at:
            if not current["last_seen_at"] or last_seen_at > current["last_seen_at"]:
                current["last_seen_at"] = last_seen_at

        for source_name in [data_source, *rel_sources]:
            if source_name and source_name not in current["_source_set"]:
                current["_source_set"].add(source_name)
                current["data_sources"].append(source_name)

        for snippet in [evidence, *rel_snippets]:
            if snippet and snippet not in current["_evidence_set"]:
                current["_evidence_set"].add(snippet)
                current["evidence_snippets"].append(snippet)

        for claim_record in rel.get("claim_records", []) or []:
            claim_id = claim_record.get("claim_id")
            if claim_id and claim_id in current["_claim_ids"]:
                existing_claim = next(
                    (existing for existing in current["claim_records"] if existing.get("claim_id") == claim_id),
                    None,
                )
                if existing_claim is not None:
                    existing_evidence_ids = {
                        evidence_record.get("evidence_id")
                        for evidence_record in existing_claim.get("evidence_records", [])
                        if evidence_record.get("evidence_id")
                    }
                    for evidence_record in claim_record.get("evidence_records", []) or []:
                        evidence_id = evidence_record.get("evidence_id")
                        if evidence_id and evidence_id in existing_evidence_ids:
                            continue
                        existing_claim.setdefault("evidence_records", []).append(evidence_record)
                        if evidence_id:
                            existing_evidence_ids.add(evidence_id)
                continue
            if claim_id:
                current["_claim_ids"].add(claim_id)
            current["claim_records"].append(claim_record)

    unique_rels: list[dict] = []
    for rel in aggregated.values():
        rel["corroboration_count"] = max(len(rel["data_sources"]), len(rel["_ids"]) or 1)
        rel["data_source"] = rel["data_sources"][0] if rel["data_sources"] else rel.get("data_source", "")
        rel["evidence"] = rel["evidence_snippets"][0] if rel["evidence_snippets"] else rel.get("evidence", "")
        rel["created_at"] = rel["first_seen_at"] or rel.get("created_at", "")
        rel["relationship_ids"] = rel["_ids"]
        rel["evidence_snippets"] = rel["evidence_snippets"][:5]
        rel["data_sources"] = rel["data_sources"][:5]
        rel["claim_records"] = [
            {
                **claim_record,
                "evidence_records": (claim_record.get("evidence_records") or [])[:4],
            }
            for claim_record in rel["claim_records"][:4]
        ]
        rel["evidence_summary"] = _build_relationship_evidence_summary(rel)
        rel.pop("_source_set", None)
        rel.pop("_evidence_set", None)
        rel.pop("_ids", None)
        rel.pop("_claim_ids", None)
        unique_rels.append(rel)

    unique_rels.sort(
        key=lambda rel: (
            rel.get("source_entity_id", ""),
            rel.get("target_entity_id", ""),
            rel.get("rel_type", ""),
        )
    )
    return unique_rels


def _filter_relationships_to_vendor_claims(all_relationships: list[dict], vendor_id: str) -> list[dict]:
    """Restrict case-level graph summaries to claims observed on the current vendor case."""
    if not vendor_id:
        return [dict(rel) for rel in all_relationships]

    now = datetime.now(timezone.utc)
    has_active_vendor_claims = any(
        str((claim_record or {}).get("vendor_id") or "") == vendor_id
        and not _claim_is_historical(dict(claim_record or {}), now=now)
        for relationship in all_relationships
        for claim_record in (relationship.get("claim_records") or [])
        if isinstance(claim_record, dict)
    )

    filtered: list[dict] = []
    for relationship in all_relationships:
        rel_copy = dict(relationship)
        all_claim_records = [dict(claim_record) for claim_record in (relationship.get("claim_records") or [])]
        active_claim_records = [
            dict(claim_record)
            for claim_record in all_claim_records
            if str((claim_record or {}).get("vendor_id") or "") == vendor_id
            and not _claim_is_historical(dict(claim_record or {}), now=now)
        ]
        historical_claim_records = [
            dict(claim_record)
            for claim_record in all_claim_records
            if str((claim_record or {}).get("vendor_id") or "") == vendor_id
            and _claim_is_historical(dict(claim_record or {}), now=now)
        ]
        claim_records = active_claim_records
        if not claim_records and not has_active_vendor_claims:
            claim_records = historical_claim_records
            if claim_records:
                rel_copy["vendor_scope_state"] = "historical"
                rel_copy["temporal_state"] = rel_copy.get("temporal_state") or "historical"
        if not claim_records:
            if all_claim_records:
                continue
            # Preserve legacy or pre-provenance edges so the graph surface stays whole.
            rel_copy["claim_records"] = []
            rel_copy["legacy_unscoped"] = True
            rel_copy["data_sources"] = list(rel_copy.get("data_sources") or [])
            rel_copy["corroboration_count"] = max(int(rel_copy.get("corroboration_count") or 0), 1)
            rel_copy["evidence_summary"] = _build_relationship_evidence_summary(rel_copy)
            filtered.append(rel_copy)
            continue
        rel_copy["claim_records"] = claim_records
        rel_copy["data_sources"] = sorted(
            {
                str(claim_record.get("data_source") or "").strip()
                for claim_record in claim_records
                if str(claim_record.get("data_source") or "").strip()
            }
        )
        rel_copy["corroboration_count"] = max(len(claim_records), 1)
        rel_copy["first_seen_at"] = min(
            (claim_record.get("first_observed_at") or claim_record.get("observed_at") or "")
            for claim_record in claim_records
        )
        rel_copy["last_seen_at"] = max(
            (claim_record.get("last_observed_at") or claim_record.get("observed_at") or "")
            for claim_record in claim_records
        )
        if not rel_copy.get("data_source"):
            rel_copy["data_source"] = str(claim_records[0].get("data_source") or "")
        rel_copy["evidence_summary"] = _build_relationship_evidence_summary(rel_copy)
        filtered.append(rel_copy)
    return filtered


def _build_relationship_evidence_summary(rel: dict) -> str:
    snippets = [snippet for snippet in rel.get("evidence_snippets", []) if snippet]
    if not snippets:
        return rel.get("evidence", "")

    record_count = max(int(rel.get("corroboration_count") or 1), len(snippets))
    source_count = len(rel.get("data_sources", []))
    source_phrase = _format_graph_source_phrase(rel.get("data_sources", []))
    rel_type = rel.get("rel_type", "")

    if rel_type in {REL_CONTRACTS_WITH, REL_SUBCONTRACTOR, REL_PRIME_CONTRACTOR} and record_count > 1:
        amounts = _extract_evidence_amounts(snippets)
        if amounts:
            total = sum(amounts)
            largest = max(amounts)
            return (
                f"{record_count} award records"
                f"{f' via {source_phrase}' if source_phrase else ''}; "
                f"total {_format_compact_currency(total)}, "
                f"largest {_format_compact_currency(largest)}."
            )
        return (
            f"{record_count} corroborating award records"
            f"{f' via {source_phrase}' if source_phrase else ''}."
        )

    if record_count > 1 and source_count > 1:
        return f"{record_count} corroborating records across {source_count} sources."

    if record_count > 1:
        return f"{record_count} corroborating records support this relationship."

    return snippets[0]


def _extract_evidence_amounts(snippets: list[str]) -> list[float]:
    amounts: list[float] = []
    for snippet in snippets:
        for raw_value in re.findall(r"\$([0-9][0-9,]*(?:\.\d+)?)", snippet):
            try:
                amounts.append(float(raw_value.replace(",", "")))
            except ValueError:
                continue
    return amounts


def _format_compact_currency(amount: float) -> str:
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.1f}B"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.1f}K"
    return f"${amount:,.0f}"


def _format_graph_source_phrase(sources: list[str]) -> str:
    if not sources:
        return ""
    source_labels = {
        "usaspending": "USAspending",
        "usaspending_subawards": "USAspending Subawards",
        "sam_subaward_reporting": "SAM Subcontract Reports",
        "fpds_contracts": "FPDS Contracts",
        "sec_edgar": "SEC EDGAR",
        "sec_edgar_ex21": "SEC Exhibit 21",
        "recap_courts": "RECAP Courts",
        "trade_csl": "Trade CSL",
        "ofac_sdn": "OFAC SDN",
        "cross_correlation": "Cross Correlation",
        "news_co_mention": "News Co-Mention",
    }
    cleaned = [
        source_labels.get(source, source.replace("_", " ").replace("-", " ").title())
        for source in sources
    ]
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{cleaned[0]}, {cleaned[1]}, and {len(cleaned) - 2} more"


# ---------------------------------------------------------------------------
# Batch backfill: replay all existing enrichment reports into graph
# ---------------------------------------------------------------------------

def backfill_all_vendors() -> dict:
    """
    Replay every stored enrichment report through graph ingestion.
    Call once to seed the knowledge graph from historical data.

    Returns: {vendors_processed, total_entities, total_relationships, errors}
    """
    try:
        import db
    except ImportError:
        return {"error": "db module not available"}

    kg = _safe_import_kg()
    if not kg:
        return {"error": "knowledge graph unavailable"}

    kg.init_kg_db()

    vendors = db.list_vendors()
    total_stats = {
        "vendors_processed": 0,
        "total_entities": 0,
        "total_relationships": 0,
        "legacy_relationships_scanned": 0,
        "legacy_relationships_backfilled": 0,
        "legacy_claims_backfilled": 0,
        "legacy_evidence_backfilled": 0,
        "legacy_relationships_without_vendor_scope": 0,
        "errors": [],
    }

    for v in vendors:
        case_id = v.get("id", "")
        name = v.get("name", "")
        if not case_id or not name:
            continue

        try:
            enrichment = db.get_latest_enrichment(case_id)
            if not enrichment:
                logger.debug("No enrichment for %s, skipping backfill", case_id)
                continue

            vendor_input = v.get("vendor_input") if isinstance(v.get("vendor_input"), dict) else None
            stats = ingest_enrichment_to_graph(case_id, name, enrichment, vendor_input=vendor_input)
            total_stats["vendors_processed"] += 1
            total_stats["total_entities"] += stats.get("entities_created", 0)
            total_stats["total_relationships"] += stats.get("relationships_created", 0)
            total_stats["errors"].extend(stats.get("errors", []))

            logger.info("Backfilled %s: %d entities, %d rels",
                       name, stats.get("entities_created", 0), stats.get("relationships_created", 0))

        except Exception as e:
            total_stats["errors"].append(f"{case_id}/{name}: {e}")
            logger.warning("Backfill failed for %s: %s", name, e)

    logger.info("Backfill complete: %d vendors, %d entities, %d relationships",
               total_stats["vendors_processed"],
               total_stats["total_entities"],
               total_stats["total_relationships"])

    try:
        legacy_stats = kg.backfill_legacy_relationship_claims()
        total_stats["legacy_relationships_scanned"] = int(legacy_stats.get("legacy_relationships_scanned") or 0)
        total_stats["legacy_relationships_backfilled"] = int(legacy_stats.get("relationships_backfilled") or 0)
        total_stats["legacy_claims_backfilled"] = int(legacy_stats.get("claims_backfilled") or 0)
        total_stats["legacy_evidence_backfilled"] = int(legacy_stats.get("evidence_backfilled") or 0)
        total_stats["legacy_relationships_without_vendor_scope"] = int(
            legacy_stats.get("relationships_without_vendor_scope") or 0
        )
    except Exception as e:
        total_stats["errors"].append(f"legacy-claim-backfill: {e}")
        logger.warning("Legacy graph claim backfill failed: %s", e)

    return total_stats


# ---------------------------------------------------------------------------
# Seed enrichment: lightweight assessment of discovered entities
# ---------------------------------------------------------------------------

SEED_CONNECTORS = ["sam_gov", "sec_edgar", "dod_sam_exclusions", "trade_csl", "ofac_sdn"]


def seed_enrich_entity(entity_name: str, entity_type: str = "company",
                       country: str = "US") -> dict:
    """
    Run a lightweight 'mini-assessment' on a discovered entity
    (subcontractor, related company, etc.) using only 5 core connectors
    instead of the full 28. Feeds results into the knowledge graph.

    Returns: {entity_name, findings_count, identifiers_found, graph_stats}
    """
    try:
        from osint.enrichment import enrich_vendor
    except ImportError:
        return {"error": "enrichment module not available"}

    kg = _safe_import_kg()
    er = _safe_import_er()
    if not kg or not er:
        return {"error": "graph modules unavailable"}

    kg.init_kg_db()

    # Run mini-enrichment with only seed connectors
    report = enrich_vendor(
        vendor_name=entity_name,
        country=country,
        connectors=SEED_CONNECTORS,
        timeout=30,
    )

    # Find or create the entity with discovered identifiers
    identifiers = report.get("identifiers", {})
    entity_id = _find_or_create_entity(
        kg, er, entity_name, identifiers,
        entity_type=entity_type, country=country,
        sources=SEED_CONNECTORS, confidence=0.6,
    )

    # Ingest findings into graph
    findings_count = len(report.get("findings", []))
    for finding in report.get("findings", []):
        try:
            _ingest_finding(kg, er, entity_id, entity_name, finding, {"entities_created": 0, "relationships_created": 0, "errors": []})
        except Exception as e:
            logger.warning(f"Seed enrichment ingestion failed for {entity_name}: {e}")

    return {
        "entity_name": entity_name,
        "entity_id": entity_id,
        "findings_count": findings_count,
        "identifiers_found": list(identifiers.keys()),
        "overall_risk": report.get("overall_risk", "UNKNOWN"),
    }


def seed_enrich_discovered_entities(vendor_id: str, max_entities: int = 10) -> dict:
    """
    For a given assessed vendor, find all discovered entities in the graph
    (subcontractors, related companies) that haven't been enriched yet,
    and run seed enrichment on them.

    Returns: {entities_enriched, results}
    """
    kg = _safe_import_kg()
    if not kg:
        return {"error": "graph unavailable"}

    kg.init_kg_db()

    # Get all entities linked to this vendor
    entities = kg.get_vendor_entities(vendor_id)
    if not entities:
        return {"entities_enriched": 0, "results": []}

    # Find entities connected to them that have low confidence (not yet enriched)
    candidates = []
    for entity in entities:
        network = kg.get_entity_network(entity.id, depth=1)
        for eid, edata in network.get("entities", {}).items():
            if edata.get("entity_type") == "company" and edata.get("confidence", 1.0) <= 0.75:
                candidates.append(edata)

    # Deduplicate and limit
    seen = set()
    unique_candidates = []
    for c in candidates:
        if c["id"] not in seen:
            seen.add(c["id"])
            unique_candidates.append(c)
    unique_candidates = unique_candidates[:max_entities]

    results = []
    for candidate in unique_candidates:
        try:
            result = seed_enrich_entity(
                candidate["canonical_name"],
                entity_type=candidate.get("entity_type", "company"),
                country=candidate.get("country", "US") or "US",
            )
            results.append(result)
        except Exception as e:
            results.append({"entity_name": candidate["canonical_name"], "error": str(e)})

    return {
        "entities_enriched": len(results),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Graph-powered workflow: cascade alerts, concentration, pre-populated context
# ---------------------------------------------------------------------------

def check_cascade_risk(vendor_id: str) -> list[dict]:
    """
    Check if any entity in a vendor's network has been flagged.
    Returns cascade alerts for connected entities with adverse findings.

    Use case: A subcontractor gets sanctioned -> alert all primes using them.
    """
    kg = _safe_import_kg()
    if not kg:
        return []

    try:
        kg.init_kg_db()

        entities = kg.get_vendor_entities(vendor_id)
        if not entities:
            return []

        alerts = []
        for entity in entities:
            network = kg.get_entity_network(entity.id, depth=2)

            for rel in network.get("relationships", []):
                target_id = rel["target_entity_id"]
                target = network.get("entities", {}).get(target_id, {})

                if not target:
                    continue

                # Check if the target entity is linked to any vendor with adverse findings
                target_entity = kg.get_entity(target_id)
                if not target_entity:
                    continue

                # Look for sanctions relationships on connected entities
                from knowledge_graph import get_kg_conn
                with get_kg_conn() as conn:
                    sanctions_rels = conn.execute(
                        "SELECT * FROM kg_relationships WHERE source_entity_id = ? AND rel_type = ?",
                        (target_id, REL_SANCTIONED),
                    ).fetchall()

                    if sanctions_rels:
                        alerts.append({
                            "alert_type": "cascade_sanctions",
                            "severity": "high",
                            "vendor_id": vendor_id,
                            "affected_entity": target.get("canonical_name", ""),
                            "relationship_type": rel["rel_type"],
                            "detail": (
                                f"Connected entity '{target.get('canonical_name', '')}' "
                                f"({rel['rel_type']}) has {len(sanctions_rels)} sanctions flag(s). "
                                "Review supply chain exposure."
                            ),
                        })

        return alerts

    except Exception as e:
        logger.warning("Cascade risk check failed for %s: %s", vendor_id, e)
        return []


def get_portfolio_concentration(top_n: int = 10) -> dict:
    """
    Find entities that appear across multiple assessed vendors.
    These are single-points-of-failure in the portfolio.

    Returns: {concentrations: [{entity_name, entity_type, vendor_count, vendors}]}
    """
    kg = _safe_import_kg()
    if not kg:
        return {"error": "graph unavailable"}

    try:
        kg.init_kg_db()

        from knowledge_graph import get_kg_conn
        with get_kg_conn() as conn:
            # Find entities linked to multiple vendors
            rows = conn.execute("""
                SELECT e.id, e.canonical_name, e.entity_type, e.country,
                       COUNT(DISTINCT ev.vendor_id) as vendor_count,
                       GROUP_CONCAT(DISTINCT ev.vendor_id) as vendor_ids
                FROM kg_entities e
                JOIN kg_entity_vendors ev ON e.id = ev.entity_id
                GROUP BY e.id
                HAVING vendor_count >= 2
                ORDER BY vendor_count DESC
                LIMIT ?
            """, (top_n,)).fetchall()

            # Also find entities that are targets of relationships from multiple source entities
            cross_vendor_rows = conn.execute("""
                SELECT e.id, e.canonical_name, e.entity_type,
                       COUNT(DISTINCT r.source_entity_id) as connection_count
                FROM kg_entities e
                JOIN kg_relationships r ON e.id = r.target_entity_id
                WHERE e.entity_type = 'company'
                GROUP BY e.id
                HAVING connection_count >= 2
                ORDER BY connection_count DESC
                LIMIT ?
            """, (top_n,)).fetchall()

        concentrations = []
        seen = set()

        for row in rows:
            if row["id"] not in seen:
                seen.add(row["id"])
                concentrations.append({
                    "entity_id": row["id"],
                    "entity_name": row["canonical_name"],
                    "entity_type": row["entity_type"],
                    "country": row["country"],
                    "vendor_count": row["vendor_count"],
                    "vendor_ids": row["vendor_ids"].split(",") if row["vendor_ids"] else [],
                    "concentration_type": "direct_link",
                })

        for row in cross_vendor_rows:
            if row["id"] not in seen:
                seen.add(row["id"])
                concentrations.append({
                    "entity_id": row["id"],
                    "entity_name": row["canonical_name"],
                    "entity_type": row["entity_type"],
                    "connection_count": row["connection_count"],
                    "concentration_type": "relationship_target",
                })

        return {
            "concentration_count": len(concentrations),
            "concentrations": concentrations,
        }

    except Exception as e:
        logger.warning("Concentration analysis failed: %s", e)
        return {"error": str(e)}


def get_pre_populated_context(vendor_name: str) -> dict:
    """
    Check if a vendor (or fuzzy match) already exists in the knowledge graph.
    Returns pre-populated context for new assessments.

    Use case: Analyst starts new assessment, graph shows known history.
    """
    kg = _safe_import_kg()
    er = _safe_import_er()
    if not kg or not er:
        return {"found": False}

    try:
        kg.init_kg_db()

        # Search by name
        candidates = kg.find_entities_by_name(vendor_name, entity_type="company")
        if not candidates:
            return {"found": False, "vendor_name": vendor_name}

        # Find best match
        best = None
        best_score = 0.0
        for c in candidates:
            try:
                score = er.jaro_winkler(
                    er.normalize_name(vendor_name),
                    er.normalize_name(c.canonical_name),
                )
            except Exception as e:
                logger.debug(f"Entity resolution scoring failed: {e}")
                score = 0.0
            if score > best_score:
                best_score = score
                best = c

        if not best or best_score < 0.80:
            return {"found": False, "vendor_name": vendor_name}

        # Get the network
        network = kg.get_entity_network(best.id, depth=1)

        return {
            "found": True,
            "vendor_name": vendor_name,
            "matched_entity": best.canonical_name,
            "match_score": round(best_score, 3),
            "entity_id": best.id,
            "known_identifiers": best.identifiers,
            "known_aliases": best.aliases,
            "country": best.country,
            "sources": best.sources,
            "confidence": best.confidence,
            "last_assessed": best.last_updated,
            "network_size": network.get("entity_count", 0),
            "relationship_count": network.get("relationship_count", 0),
            "connected_entities": [
                {"name": e.get("canonical_name", ""), "type": e.get("entity_type", "")}
                for e in list(network.get("entities", {}).values())[:10]
                if e.get("id") != best.id
            ],
        }

    except Exception as e:
        logger.warning("Pre-populated context failed for '%s': %s", vendor_name, e)
        return {"found": False, "error": str(e)}
