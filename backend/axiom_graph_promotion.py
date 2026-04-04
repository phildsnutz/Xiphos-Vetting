"""
Promote validated AXIOM gap-fill results into the durable knowledge graph.

This is the Phase 4 follow-on to the validation gate:
  - AXIOM can surface hard-to-get signal
  - the validation gate decides if the signal is durable
  - this module writes accepted signal into claim/evidence-backed graph memory

The first implementation is intentionally narrow. It only promotes gap types
that safely support a company-to-contract-vehicle participation claim.
Richer teammate, subcontract, ownership, or facility claims remain deferred
until AXIOM returns structured entities and relationship roles that justify
those stronger assertions.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from entity_resolution import ResolvedEntity, generate_entity_id, normalize_name
from knowledge_graph import get_entity, init_kg_db, link_entity_to_vendor, save_entity, save_relationship
from validation_gate import (
    ValidationDecision,
    extract_normalized_findings,
    validate_gap_fill_result,
)

logger = logging.getLogger(__name__)

_PROMOTABLE_GAP_RELATIONSHIPS = {
    "subcontractor_identity": "awarded_under",
    "contract_history": "awarded_under",
    "teaming_partner": "awarded_under",
    "supply_chain": "awarded_under",
    "regulatory_compliance": "awarded_under",
}

_TYPE_SAFE_ENTITY_IDS = {
    "contract_vehicle",
    "installation",
    "contract",
    "award",
    "facility",
    "government_agency",
    "country",
    "export_control",
    "trade_show_event",
}


@dataclass
class GraphPromotionResult:
    gap_id: str
    status: str
    reason: str = ""
    relationship_type: str = ""
    source_entity_id: str = ""
    target_entity_id: str = ""
    promoted_claims: int = 0
    skipped_findings: int = 0
    promoted_sources: list[str] = field(default_factory=list)
    since_timestamp: str = ""
    vendor_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_entity_id(name: str, entity_type: str, identifiers: dict | None = None) -> str:
    identifiers = identifiers or {}
    normalized_type = str(entity_type or "company").strip().lower()
    if normalized_type in _TYPE_SAFE_ENTITY_IDS:
        normalized_name = normalize_name(name) or str(name or "").strip().upper()
        hash_val = hashlib.md5(normalized_name.encode("utf-8")).hexdigest()[:12]
        return f"{normalized_type}:{hash_val}"
    return generate_entity_id(name, identifiers)


def _ensure_entity(
    *,
    name: str,
    entity_type: str,
    identifiers: dict | None = None,
    sources: list[str] | None = None,
    confidence: float = 0.7,
    vendor_id: str = "",
) -> str:
    identifiers = identifiers or {}
    sources = [str(source).strip() for source in (sources or []) if str(source or "").strip()]
    entity_id = _stable_entity_id(name, entity_type, identifiers)
    existing = get_entity(entity_id)

    aliases: list[str] = []
    merged_sources = set(sources)
    merged_identifiers = dict(identifiers)
    merged_confidence = confidence
    canonical_name = name
    country = ""

    if existing:
        canonical_name = existing.canonical_name or name
        country = existing.country or ""
        merged_sources.update(existing.sources or [])
        merged_identifiers = {**(existing.identifiers or {}), **merged_identifiers}
        merged_confidence = max(float(existing.confidence or 0.0), confidence)
        aliases = list(existing.aliases or [])
        if name and existing.canonical_name and name.strip().lower() != existing.canonical_name.strip().lower():
            aliases.append(name)

    entity = ResolvedEntity(
        id=entity_id,
        canonical_name=canonical_name,
        entity_type=entity_type,
        aliases=sorted({alias for alias in aliases if alias}),
        identifiers=merged_identifiers,
        country=country,
        sources=sorted(merged_sources),
        confidence=merged_confidence,
        last_updated=_utc_now(),
    )
    save_entity(entity)

    if vendor_id:
        link_entity_to_vendor(entity_id, vendor_id)

    return entity_id


def promote_validated_gap_fill(
    result,
    validation: ValidationDecision | None = None,
    *,
    vendor_id: str = "",
) -> GraphPromotionResult:
    """
    Promote a validated AXIOM gap-fill into the durable graph path.

    Only vehicle-facing participation claims are auto-promoted in this slice.
    """

    gap = getattr(result, "gap", None)
    gap_id = getattr(gap, "gap_id", "") if gap else ""
    started_at = _utc_now()
    init_kg_db()
    promotion = GraphPromotionResult(
        gap_id=gap_id,
        status="skipped",
        since_timestamp=started_at,
        vendor_id=vendor_id,
    )

    validation = validation or validate_gap_fill_result(result)
    if validation.outcome != "accepted":
        promotion.reason = f"Validation outcome '{validation.outcome}' is not eligible for graph promotion."
        return promotion

    if not gap:
        promotion.reason = "Gap fill result is missing gap metadata."
        return promotion

    relationship_type = _PROMOTABLE_GAP_RELATIONSHIPS.get(str(getattr(gap, "gap_type", "") or "").strip().lower())
    if not relationship_type:
        promotion.status = "deferred"
        promotion.reason = "Accepted result does not yet map to a safe automatic graph relationship."
        return promotion

    entity_name = str(getattr(gap, "entity_name", "") or "").strip()
    vehicle_name = str(getattr(gap, "vehicle_name", "") or "").strip()
    if not entity_name or not vehicle_name:
        promotion.status = "deferred"
        promotion.reason = "Accepted result is missing the company or contract vehicle anchor required for promotion."
        return promotion

    findings = [
        finding
        for finding in extract_normalized_findings(result)
        if finding.evidence and finding.authority_score >= 0.55
    ]
    if not findings:
        promotion.status = "deferred"
        promotion.reason = "Accepted result did not retain any promotable findings after authority filtering."
        return promotion

    source_entity_id = _ensure_entity(
        name=entity_name,
        entity_type="company",
        sources=sorted({finding.source for finding in findings} | {"axiom_gap_fill_validated"}),
        confidence=max(float(getattr(result, "fill_confidence", 0.0) or 0.0), 0.65),
        vendor_id=vendor_id,
    )
    target_entity_id = _ensure_entity(
        name=vehicle_name,
        entity_type="contract_vehicle",
        sources=["axiom_gap_fill_validated"],
        confidence=max(float(getattr(result, "fill_confidence", 0.0) or 0.0), 0.65),
        vendor_id=vendor_id,
    )

    promoted_sources: list[str] = []
    for finding in findings:
        if finding.source not in promoted_sources:
            promoted_sources.append(finding.source)
        structured_fields = {
            "promotion_type": "axiom_gap_fill_validated",
            "gap_id": gap_id,
            "gap_type": getattr(gap, "gap_type", ""),
            "gap_description": getattr(gap, "description", ""),
            "gap_entity_name": entity_name,
            "gap_vehicle_name": vehicle_name,
            "validation_outcome": validation.outcome,
            "validation_confidence_label": validation.confidence_label,
            "validation_reasons": list(validation.reasons or []),
            "axiom_fill_confidence": float(getattr(result, "fill_confidence", 0.0) or 0.0),
            "finding_confidence": float(finding.confidence or 0.0),
            "original_classification": getattr(gap, "original_classification", ""),
            "source_iteration": int(getattr(gap, "source_iteration", 0) or 0),
        }
        save_relationship(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            rel_type=relationship_type,
            confidence=max(float(getattr(result, "fill_confidence", 0.0) or 0.0), float(finding.confidence or 0.0)),
            data_source=finding.source,
            evidence=finding.evidence,
            observed_at=started_at,
            claim_value=f"{entity_name} is linked to {vehicle_name}",
            source_activity={
                "source": finding.source,
                "activity_type": "axiom_gap_fill_validated",
                "occurred_at": started_at,
                "metadata": {
                    "gap_id": gap_id,
                    "gap_type": getattr(gap, "gap_type", ""),
                    "relationship_type": relationship_type,
                },
            },
            asserting_agent={
                "label": "AXIOM Validation Gate",
                "agent_type": "agentic_collection",
                "metadata": {
                    "gap_id": gap_id,
                    "validation_outcome": validation.outcome,
                    "confidence_label": validation.confidence_label,
                },
            },
            artifact_ref=f"axiom-gap://{gap_id}",
            evidence_title=f"AXIOM validated {getattr(gap, 'gap_type', 'gap')}",
            raw_data={
                "gap": {
                    "gap_id": gap_id,
                    "description": getattr(gap, "description", ""),
                    "entity_name": entity_name,
                    "vehicle_name": vehicle_name,
                    "gap_type": getattr(gap, "gap_type", ""),
                },
                "validation": validation.to_dict(),
                "finding": asdict(finding),
            },
            structured_fields=structured_fields,
            source_class=finding.source_class,
            authority_level=finding.authority_level,
            access_model="lawful_public_edge",
            vendor_id=vendor_id,
        )

    promotion.status = "promoted"
    promotion.relationship_type = relationship_type
    promotion.source_entity_id = source_entity_id
    promotion.target_entity_id = target_entity_id
    promotion.promoted_claims = len(findings)
    promotion.skipped_findings = max(0, len(extract_normalized_findings(result)) - len(findings))
    promotion.promoted_sources = promoted_sources
    promotion.reason = f"Promoted {len(findings)} validated findings into claim-backed graph memory."
    return promotion


def summarize_promotions(promotions: list[GraphPromotionResult | dict]) -> dict:
    normalized = [
        promotion if isinstance(promotion, dict) else promotion.to_dict()
        for promotion in (promotions or [])
    ]
    promoted = [promotion for promotion in normalized if promotion.get("status") == "promoted"]
    deferred = [promotion for promotion in normalized if promotion.get("status") == "deferred"]
    skipped = [promotion for promotion in normalized if promotion.get("status") == "skipped"]
    since_values = [str(promotion.get("since_timestamp") or "").strip() for promotion in promoted if str(promotion.get("since_timestamp") or "").strip()]
    return {
        "total_results": len(normalized),
        "promoted_results": len(promoted),
        "deferred_results": len(deferred),
        "skipped_results": len(skipped),
        "promoted_claims": sum(int(promotion.get("promoted_claims") or 0) for promotion in normalized),
        "since_timestamp": min(since_values) if since_values else "",
        "results": normalized,
    }
