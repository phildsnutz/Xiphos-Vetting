"""
Gap Advisory Pipeline -- Intelligence Gap to Advisory Proposal Generation

Converts unfilled intelligence gaps from the AXIOM system into scoped,
priced advisory engagement proposals. This is the revenue engine that turns
OSINT limitations into consulting opportunities ($15K-$50K engagements).

Architecture:
  1. Gap Extraction: Pull intelligence gaps from dossier context
  2. Axiom First-Look: Send gaps through axiom_gap_filler (wise case officer)
  3. Advisory Generation: Classify remaining unfilled gaps and generate proposals
  4. HTML Rendering: Package proposals into professional proposal document

The pipeline understands gap types (subcontractor_identity, ownership_chain,
contract_history, cyber_posture, etc.) and maps them to pricing tiers based
on complexity and effort required to fill.
"""

import json
import logging
import uuid
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

# Core Helios imports
try:
    from axiom_gap_filler import IntelligenceGap, GapFillResult, fill_gaps, load_wisdom
except ImportError:
    # Stub for development/testing
    IntelligenceGap = None
    GapFillResult = None
    fill_gaps = None
    load_wisdom = None

try:
    from axiom_agent import run_agent, SearchTarget, AgentResult
except ImportError:
    run_agent = None
    SearchTarget = None
    AgentResult = None

from dossier import build_dossier_context
from knowledge_graph import get_kg_conn
import db
import os
from validation_gate import validate_gap_fill_result

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Gap type pricing model (USD)
GAP_TYPE_PRICING = {
    "subcontractor_identity": {"min": 15000, "max": 35000, "per": "vehicle"},
    "ownership_chain": {"min": 10000, "max": 25000, "per": "entity"},
    "contract_history": {"min": 20000, "max": 45000, "per": "vehicle"},
    "personnel": {"min": 5000, "max": 15000, "per": "entity"},
    "facility": {"min": 10000, "max": 30000, "per": "installation"},
    "cyber_posture": {"min": 15000, "max": 40000, "per": "entity"},
    "financial": {"min": 10000, "max": 25000, "per": "entity"},
    "sanctions_screening": {"min": 5000, "max": 15000, "per": "entity"},
    "regulatory_compliance": {"min": 15000, "max": 35000, "per": "vehicle"},
}

# Gap classification rules: signal patterns that indicate a gap
GAP_SIGNALS = {
    "subcontractor_identity": {
        "signals": ["no_subcontractor_relationships", "empty_subcontractor_field", "team_members_unknown"],
        "confidence_threshold": 0.6,
        "typical_effort_days": 15,
    },
    "ownership_chain": {
        "signals": ["parent_company_unknown", "beneficial_owners_missing", "corporate_structure_incomplete"],
        "confidence_threshold": 0.5,
        "typical_effort_days": 12,
    },
    "contract_history": {
        "signals": ["no_contract_data", "fpds_empty", "usaspending_zero_results"],
        "confidence_threshold": 0.7,
        "typical_effort_days": 20,
    },
    "personnel": {
        "signals": ["cfo_unknown", "ceo_unknown", "exec_team_missing"],
        "confidence_threshold": 0.6,
        "typical_effort_days": 8,
    },
    "facility": {
        "signals": ["manufacturing_location_unknown", "no_manufacturing_data", "facility_location_uncertain"],
        "confidence_threshold": 0.5,
        "typical_effort_days": 10,
    },
    "cyber_posture": {
        "signals": ["no_cvss_data", "vulnerability_data_missing", "security_posture_unknown"],
        "confidence_threshold": 0.6,
        "typical_effort_days": 14,
    },
    "financial": {
        "signals": ["revenue_unknown", "financial_health_unclear", "sec_filing_not_found"],
        "confidence_threshold": 0.5,
        "typical_effort_days": 10,
    },
    "sanctions_screening": {
        "signals": ["ofac_screening_inconclusive", "sanctions_list_query_failed", "pep_status_unknown"],
        "confidence_threshold": 0.4,
        "typical_effort_days": 5,
    },
    "regulatory_compliance": {
        "signals": ["cmmc_level_unknown", "itar_status_unclear", "ddtc_registration_missing"],
        "confidence_threshold": 0.5,
        "typical_effort_days": 12,
    },
}

# Methodology library (how we fill different gap types)
FILL_METHODOLOGIES = {
    "subcontractor_identity": [
        "SAM.gov subaward registry scraping",
        "Network query with prime contractors",
        "FPDS historical contract analysis",
        "Industry partnership verification",
        "LinkedIn organizational mapping",
    ],
    "ownership_chain": [
        "SEC Edgar corporate filings analysis",
        "OpenCorporates global registry lookup",
        "State corporate filing research",
        "UCC lien searches",
        "Beneficial ownership databases (international)",
    ],
    "contract_history": [
        "FPDS.gov comprehensive query",
        "USASpending.gov detail analysis",
        "SAM.gov active contracts review",
        "Proprietary defense contractor database queries",
        "FOIA contract document requests",
    ],
    "personnel": [
        "LinkedIn executive research",
        "SEC proxy statements and Form 4s",
        "News archive searches",
        "Professional network queries",
        "Corporate registration documents",
    ],
    "facility": [
        "NAICS facility mapper queries",
        "Satellite imagery analysis",
        "Permitting agency records",
        "Property tax assessor databases",
        "EPA ECHO facility registry",
    ],
    "cyber_posture": [
        "CVSS vulnerability scanning",
        "Shodan API queries",
        "Certificate transparency logs",
        "Network penetration assessment scoping",
        "Passive vulnerability intelligence",
    ],
    "financial": [
        "SEC Edgar annual report analysis",
        "SAM.gov CCPA data review",
        "D&B credit reports",
        "Commercial lending databases",
        "Government payment records analysis",
    ],
    "sanctions_screening": [
        "OFAC SDN list enhanced screening",
        "International sanctions lists consolidation",
        "PEP database queries",
        "Corporate beneficial owner sanctions check",
        "Transaction screening rule validation",
    ],
    "regulatory_compliance": [
        "CMMC maturity level assessment scoping",
        "ITAR Directorate registration verification",
        "DDTC registration history research",
        "CUI handling requirements analysis",
        "Federal procurement compliance audit",
    ],
}

# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class AdvisoryProposal:
    """A scoped advisory engagement proposal generated from unfilled intelligence gaps."""
    proposal_id: str
    title: str  # e.g., "LEIA Subcontractor Ecosystem Mapping"
    client_company: str  # The target customer (the company with the gap)
    vehicle_name: str
    gaps_addressed: list[dict]  # List of gap descriptions this proposal covers
    scope_of_work: str  # Detailed scope narrative
    methodology: list[str]  # Steps to fill the gaps
    deliverables: list[str]  # What the customer gets
    estimated_value: float  # Dollar amount
    estimated_duration_days: int
    priority: str  # critical, high, medium, low
    data_sources_required: list[str]  # What sources are needed
    fill_methods: list[str]  # automated_search, network_query, foia, field_collection
    confidence_of_fill: float  # 0-1, how confident we are we can fill these gaps
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PipelineResult:
    """Complete result from the gap advisory pipeline."""
    total_gaps_identified: int
    gaps_filled_by_axiom: int
    gaps_remaining: int
    proposals_generated: list[AdvisoryProposal]
    total_pipeline_value: float
    axiom_fill_results: list[dict]  # Summary of what Axiom filled
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["proposals_generated"] = [p.to_dict() for p in self.proposals_generated]
        return data


# ---------------------------------------------------------------------------
# Gap Extraction
# ---------------------------------------------------------------------------

def extract_gaps_from_context(vendor_id: str, dossier_context: dict = None) -> list[dict]:
    """
    Extract intelligence gaps from a vendor's dossier context.

    Looks for:
    - OSINT connectors that returned zero findings (data availability gaps)
    - Enrichment fields that are empty/null (entity data gaps)
    - Knowledge graph entities with low confidence scores (confidence gaps)
    - Missing relationship types (structural gaps)
    - Regulatory gates with "insufficient data" results (compliance gaps)

    Returns list of gap dictionaries with:
      - gap_id: unique identifier
      - gap_type: category (subcontractor_identity, ownership_chain, etc.)
      - description: natural language description
      - severity: critical, high, medium, low
      - affected_entities: list of entity names
      - confidence: 0-1 confidence in the gap existence
    """
    gaps = []

    if dossier_context is None:
        dossier_context = build_dossier_context(vendor_id) or {}

    vendor = db.get_vendor(vendor_id)
    if not vendor:
        logger.warning("extract_gaps_from_context: vendor %s not found", vendor_id)
        return gaps

    # Extract enrichment data
    enrichment = db.get_latest_enrichment(vendor_id)
    if enrichment:
        full_report = enrichment.get("full_report", {})
        if isinstance(full_report, str):
            try:
                full_report = json.loads(full_report)
            except (json.JSONDecodeError, TypeError):
                full_report = {}

        # Check for empty connector results
        findings = full_report.get("findings", {})
        if isinstance(findings, dict):
            for connector_name, connector_data in findings.items():
                results = connector_data.get("results", [])
                if not results or (isinstance(results, dict) and not results.get("items")):
                    gap_type = _infer_gap_type_from_connector(connector_name)
                    if gap_type:
                        gaps.append({
                            "gap_id": f"gap_{vendor_id}_{connector_name}_{uuid.uuid4().hex[:8]}",
                            "gap_type": gap_type,
                            "description": f"No results from {connector_name} connector",
                            "severity": "high",
                            "affected_entities": [vendor.get("vendor_name", vendor_id)],
                            "confidence": 0.7,
                            "source": "connector_empty_result",
                        })

        # Check for missing enrichment fields
        enrichment_payload = full_report.get("enrichment_payload", {})
        if isinstance(enrichment_payload, dict):
            empty_fields = _identify_empty_enrichment_fields(enrichment_payload)
            for field_name in empty_fields:
                gap_type = _infer_gap_type_from_field(field_name)
                if gap_type:
                    gaps.append({
                        "gap_id": f"gap_{vendor_id}_{field_name}_{uuid.uuid4().hex[:8]}",
                        "gap_type": gap_type,
                        "description": f"Missing enrichment data: {field_name}",
                        "severity": "medium",
                        "affected_entities": [vendor.get("vendor_name", vendor_id)],
                        "confidence": 0.5,
                        "source": "missing_enrichment",
                    })

    # Check knowledge graph for low-confidence entities
    try:
        kg_conn = get_kg_conn()
        if kg_conn:
            # Query entities with confidence < 0.5
            graph_gaps = _extract_kg_gaps(vendor_id, kg_conn)
            gaps.extend(graph_gaps)
    except Exception as e:
        logger.warning("extract_gaps_from_context: KG query failed: %s", str(e))

    # Check for regulatory compliance gaps
    score = db.get_latest_score(vendor_id)
    if score:
        score_data = score.get("score_payload", {})
        if isinstance(score_data, str):
            try:
                score_data = json.loads(score_data)
            except (json.JSONDecodeError, TypeError):
                score_data = {}

        regulatory_gates = score_data.get("regulatory_gates", {})
        for gate_name, gate_result in regulatory_gates.items():
            if gate_result.get("status") == "data_insufficient":
                gaps.append({
                    "gap_id": f"gap_{vendor_id}_regulatory_{uuid.uuid4().hex[:8]}",
                    "gap_type": "regulatory_compliance",
                    "description": f"Regulatory gate '{gate_name}' has insufficient data",
                    "severity": "critical",
                    "affected_entities": [vendor.get("vendor_name", vendor_id)],
                    "confidence": 0.8,
                    "source": "regulatory_gate",
                })

    # Deduplicate gaps by type and description (keep highest confidence)
    gaps = _deduplicate_gaps(gaps)

    logger.info("extract_gaps_from_context: identified %d gaps for vendor %s", len(gaps), vendor_id)
    return gaps


def _infer_gap_type_from_connector(connector_name: str) -> Optional[str]:
    """Map connector name to gap type."""
    connector_gap_mapping = {
        "fpds": "contract_history",
        "usaspending": "contract_history",
        "sam_subawards": "subcontractor_identity",
        "sec_edgar": "financial",
        "opencorporates": "ownership_chain",
        "gleif": "ownership_chain",
        "ofac": "sanctions_screening",
        "opensanctions": "sanctions_screening",
        "cvss": "cyber_posture",
        "shodan": "cyber_posture",
        "epa_echo": "facility",
        "linkedin": "personnel",
        "courtlistener": "regulatory_compliance",
    }
    return connector_gap_mapping.get(connector_name.lower())


def _infer_gap_type_from_field(field_name: str) -> Optional[str]:
    """Map enrichment field name to gap type."""
    field_gap_mapping = {
        "ceo_name": "personnel",
        "cfo_name": "personnel",
        "exec_team": "personnel",
        "parent_company": "ownership_chain",
        "beneficial_owners": "ownership_chain",
        "manufacturing_location": "facility",
        "facility_count": "facility",
        "contract_count": "contract_history",
        "recent_contracts": "contract_history",
        "cmmc_level": "regulatory_compliance",
        "itar_registered": "regulatory_compliance",
        "cvss_score": "cyber_posture",
        "revenue": "financial",
        "employee_count": "financial",
    }
    return field_gap_mapping.get(field_name.lower())


def _identify_empty_enrichment_fields(enrichment_payload: dict) -> list[str]:
    """Identify fields in enrichment that are empty/null/missing."""
    empty_fields = []
    critical_fields = [
        "ceo_name", "cfo_name", "exec_team", "parent_company",
        "beneficial_owners", "manufacturing_location", "facility_count",
        "contract_count", "recent_contracts", "cmmc_level", "itar_registered",
        "cvss_score", "revenue", "employee_count",
    ]
    for field in critical_fields:
        value = enrichment_payload.get(field)
        if value is None or value == "" or (isinstance(value, list) and len(value) == 0):
            empty_fields.append(field)
    return empty_fields


def _extract_kg_gaps(vendor_id: str, kg_conn) -> list[dict]:
    """Extract gaps from knowledge graph (low confidence entities/relationships)."""
    gaps = []
    try:
        # Query for entities with confidence < 0.5
        rows = kg_conn.execute("""
            SELECT entity_id, entity_name, entity_type, confidence
            FROM knowledge_graph_entities
            WHERE vendor_id = ? AND confidence < 0.5
            ORDER BY confidence ASC
            LIMIT 20
        """, (vendor_id,)).fetchall()

        for row in rows:
            entity_name = row[1] if len(row) > 1 else row[0]
            gap_type = _infer_gap_type_from_field(row[2] if len(row) > 2 else "unknown")
            if gap_type:
                gaps.append({
                    "gap_id": f"gap_{vendor_id}_kg_{uuid.uuid4().hex[:8]}",
                    "gap_type": gap_type or "ownership_chain",
                    "description": f"Low-confidence entity in KG: {entity_name}",
                    "severity": "medium",
                    "affected_entities": [entity_name],
                    "confidence": 0.6,
                    "source": "kg_low_confidence",
                })
    except Exception as e:
        logger.warning("_extract_kg_gaps failed: %s", str(e))

    return gaps


def _deduplicate_gaps(gaps: list[dict]) -> list[dict]:
    """Remove duplicate gaps, keeping the one with highest confidence."""
    seen = {}
    for gap in gaps:
        key = (gap.get("gap_type"), gap.get("description"))
        if key not in seen or gap.get("confidence", 0) > seen[key].get("confidence", 0):
            seen[key] = gap
    return list(seen.values())


# ---------------------------------------------------------------------------
# Axiom First-Look
# ---------------------------------------------------------------------------

def attempt_axiom_fill(gaps: list[dict], vendor_id: str, api_key: str = "",
                       provider: str = "anthropic", model: str = "claude-sonnet-4-6",
                       user_id: str = "") -> tuple[list[dict], list[dict]]:
    """
    Send gaps through axiom_gap_filler (the wise case officer).

    Returns:
      - filled_gaps: list of gaps that Axiom successfully filled
      - unfilled_gaps: list of gaps that Axiom could not fill
    """
    if not fill_gaps:
        logger.warning("attempt_axiom_fill: axiom_gap_filler not available, skipping")
        return [], gaps

    filled_gaps = []
    unfilled_gaps = []

    vendor = db.get_vendor(vendor_id)
    vendor_name = vendor.get("name", vendor_id) if vendor else vendor_id

    for gap in gaps:
        try:
            affected_entities = gap.get("affected_entities") or []
            entity_name = str(
                gap.get("entity_name")
                or gap.get("affected_vendor")
                or (affected_entities[0] if affected_entities else "")
                or vendor_name
            ).strip() or vendor_name

            severity = str(gap.get("severity", "medium")).strip().lower()
            priority = severity if severity in {"critical", "high", "medium", "low"} else "medium"

            # Construct gap input for Axiom
            gap_input = IntelligenceGap(
                gap_id=str(gap.get("gap_id") or f"gap_{vendor_id}"),
                gap_type=str(gap.get("gap_type") or "unknown"),
                description=str(gap.get("description") or ""),
                entity_name=entity_name,
                vehicle_name=str(gap.get("vehicle_name") or gap.get("vehicle") or ""),
                priority=priority,
                original_classification=str(gap.get("original_classification") or "automated_search"),
                source_iteration=int(gap.get("source_iteration") or 0),
            ) if IntelligenceGap else gap

            # Call Axiom filler
            fill_result = fill_gaps(
                [gap_input],
                api_key=api_key,
                provider=provider,
                model=model,
                user_id=user_id,
            )

            # Check result
            if isinstance(fill_result, list) and len(fill_result) > 0:
                result = fill_result[0]
                validation = validate_gap_fill_result(result)
                result_payload = asdict(result) if hasattr(result, '__dataclass_fields__') else result
                if isinstance(result_payload, dict):
                    result_payload["validation"] = validation.to_dict()
                gap["axiom_fill_result"] = result_payload
                gap["axiom_validation"] = validation.to_dict()
                if isinstance(result, GapFillResult) and result.filled and validation.outcome == "accepted":
                    filled_gaps.append(gap)
                else:
                    unfilled_gaps.append(gap)
            else:
                unfilled_gaps.append(gap)

        except Exception as e:
            logger.warning("attempt_axiom_fill: error filling gap %s: %s", gap.get("gap_id"), str(e))
            unfilled_gaps.append(gap)

    logger.info("attempt_axiom_fill: filled %d/%d gaps", len(filled_gaps), len(gaps))
    return filled_gaps, unfilled_gaps


# ---------------------------------------------------------------------------
# Proposal Generation
# ---------------------------------------------------------------------------

def generate_advisory_proposals(
    unfilled_gaps: list[dict],
    vendor_id: str,
    vehicle_name: str = "",
    client_company: str = "",
) -> list[AdvisoryProposal]:
    """
    Generate advisory proposals from unfilled gaps.

    Groups related gaps into coherent engagement proposals.
    Estimates value based on gap type and complexity.

    Returns list of AdvisoryProposal objects ready for HTML rendering.
    """
    if not unfilled_gaps:
        return []

    proposals = []

    # Group gaps by type
    gaps_by_type = {}
    for gap in unfilled_gaps:
        gap_type = gap.get("gap_type", "unknown")
        if gap_type not in gaps_by_type:
            gaps_by_type[gap_type] = []
        gaps_by_type[gap_type].append(gap)

    vendor = db.get_vendor(vendor_id)
    vendor_name = vendor.get("vendor_name", vendor_id) if vendor else vendor_id
    if not client_company:
        client_company = vendor_name

    # Generate one proposal per gap type (can be combined later)
    for gap_type, type_gaps in gaps_by_type.items():
        proposal = _create_proposal_for_gap_type(
            gap_type=gap_type,
            gaps=type_gaps,
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            vehicle_name=vehicle_name,
            client_company=client_company,
        )
        if proposal:
            proposals.append(proposal)

    # Generate combined proposal if multiple gap types
    if len(proposals) > 1:
        combined = _create_combined_proposal(proposals, vendor_name, vehicle_name, client_company)
        proposals.append(combined)

    logger.info("generate_advisory_proposals: created %d proposals for vendor %s", len(proposals), vendor_id)
    return proposals


def _create_proposal_for_gap_type(
    gap_type: str,
    gaps: list[dict],
    vendor_id: str,
    vendor_name: str,
    vehicle_name: str,
    client_company: str,
) -> Optional[AdvisoryProposal]:
    """Create a proposal addressing a specific gap type."""

    pricing = GAP_TYPE_PRICING.get(gap_type, {"min": 15000, "max": 30000, "per": "vehicle"})
    gap_signals = GAP_SIGNALS.get(gap_type, {})
    methodologies = FILL_METHODOLOGIES.get(gap_type, [])

    # Estimate value
    num_gaps = len(gaps)
    per_unit = pricing.get("per", "vehicle")
    multiplier = num_gaps if per_unit == "entity" else 1
    estimated_value = pricing["min"] + (pricing["max"] - pricing["min"]) * 0.5
    estimated_value = estimated_value * multiplier

    estimated_duration = gap_signals.get("typical_effort_days", 10) * multiplier

    # Build proposal title
    title_map = {
        "subcontractor_identity": "Subcontractor Ecosystem Mapping",
        "ownership_chain": "Corporate Ownership Structure Analysis",
        "contract_history": "Government Contract History Research",
        "personnel": "Executive Team Identification",
        "facility": "Manufacturing Facility Assessment",
        "cyber_posture": "Cybersecurity Posture Analysis",
        "financial": "Financial Health Assessment",
        "sanctions_screening": "Enhanced Sanctions Screening",
        "regulatory_compliance": "Regulatory Compliance Audit",
    }
    title = title_map.get(gap_type, f"{gap_type.replace('_', ' ').title()} Assessment")

    # Build scope of work
    scope_narrative = _build_scope_narrative(gap_type, gaps, vendor_name)

    # Determine fill methods
    fill_methods = _determine_fill_methods(gap_type, gaps)

    # Calculate confidence of fill
    confidence_of_fill = _estimate_fill_confidence(gap_type, gaps)

    proposal = AdvisoryProposal(
        proposal_id=f"prop_{vendor_id}_{gap_type}_{uuid.uuid4().hex[:8]}",
        title=title,
        client_company=client_company,
        vehicle_name=vehicle_name,
        gaps_addressed=[{
            "gap_id": g.get("gap_id"),
            "gap_type": g.get("gap_type"),
            "description": g.get("description"),
            "severity": g.get("severity"),
        } for g in gaps],
        scope_of_work=scope_narrative,
        methodology=methodologies[:5],  # Top 5 methods
        deliverables=_get_deliverables_for_gap_type(gap_type),
        estimated_value=estimated_value,
        estimated_duration_days=int(estimated_duration),
        priority=_determine_priority(gaps),
        data_sources_required=_get_data_sources_for_gap_type(gap_type),
        fill_methods=fill_methods,
        confidence_of_fill=confidence_of_fill,
    )

    return proposal


def _build_scope_narrative(gap_type: str, gaps: list[dict], vendor_name: str) -> str:
    """Build detailed scope of work narrative."""
    scope_templates = {
        "subcontractor_identity": f"Comprehensive mapping of {vendor_name}'s subcontractor and partner ecosystem. Includes identification of all current and recent subcontractors, teaming partners, and suppliers. Deliverable includes organizational chart and relationship mapping.",
        "ownership_chain": f"Complete analysis of {vendor_name}'s corporate ownership structure. Traces parent company, intermediate holding entities, and beneficial owners. Includes foreign ownership analysis and any special purpose entities.",
        "contract_history": f"Detailed research of {vendor_name}'s government contracting history. Covers FPDS-NG records, USASpending data, SAM.gov active contracts, and historical vehicle participation.",
        "personnel": f"Identification and profiling of {vendor_name}'s key executive personnel. Includes C-suite (CEO, CFO, CTO), board members, and relevant operational leadership.",
        "facility": f"Assessment of {vendor_name}'s manufacturing, assembly, and operational facilities. Includes location verification, facility type classification, and production capability assessment.",
        "cyber_posture": f"Cybersecurity vulnerability and posture assessment for {vendor_name}. Includes passive reconnaissance, public vulnerability databases, and threat exposure analysis.",
        "financial": f"Financial health and viability assessment of {vendor_name}. Covers revenue analysis, profitability trends, liquidity position, and financial stability indicators.",
        "sanctions_screening": f"Enhanced sanctions and PEP screening of {vendor_name} and associated entities. Covers OFAC, international sanctions lists, and beneficial owner screening.",
        "regulatory_compliance": f"Assessment of {vendor_name}'s compliance posture against regulatory requirements. Covers CMMC, ITAR, DDTC, CUI handling, and federal procurement rules.",
    }
    return scope_templates.get(gap_type, f"Intelligence gap analysis and research for {vendor_name}")


def _determine_fill_methods(gap_type: str, gaps: list[dict]) -> list[str]:
    """Determine which fill methods are appropriate for this gap."""
    method_map = {
        "subcontractor_identity": ["automated_search", "network_query"],
        "ownership_chain": ["automated_search", "network_query"],
        "contract_history": ["automated_search", "foia"],
        "personnel": ["automated_search", "network_query"],
        "facility": ["automated_search", "field_collection"],
        "cyber_posture": ["automated_search", "field_collection"],
        "financial": ["automated_search"],
        "sanctions_screening": ["automated_search"],
        "regulatory_compliance": ["automated_search", "foia"],
    }
    return method_map.get(gap_type, ["automated_search"])


def _estimate_fill_confidence(gap_type: str, gaps: list[dict]) -> float:
    """Estimate confidence that we can successfully fill these gaps (0-1)."""
    base_confidence = 0.75
    # Adjust based on gap count and severity
    high_severity_count = sum(1 for g in gaps if g.get("severity") == "critical")
    medium_severity_count = sum(1 for g in gaps if g.get("severity") in ("high", "medium"))

    # Reduce confidence for critical gaps
    confidence = base_confidence - (high_severity_count * 0.1) - (medium_severity_count * 0.05)
    return max(0.4, min(0.95, confidence))


def _get_deliverables_for_gap_type(gap_type: str) -> list[str]:
    """Get typical deliverables for a gap type."""
    deliverables_map = {
        "subcontractor_identity": [
            "Current subcontractor roster with contract values",
            "Historical subcontractor analysis (3-5 years)",
            "Organizational chart with team structure",
            "Subcontractor location map",
        ],
        "ownership_chain": [
            "Corporate ownership structure diagram",
            "List of parent companies and intermediate entities",
            "Beneficial owner identification",
            "Foreign ownership analysis",
        ],
        "contract_history": [
            "Comprehensive contract list (FPDS, USASpending, SAM.gov)",
            "Contract value trends (3-5 years)",
            "Vehicle participation history",
            "Prime vs. subcontractor role analysis",
        ],
        "personnel": [
            "Executive biography summaries",
            "Educational and professional background",
            "Board member and leadership roster",
            "Compensation and equity data",
        ],
        "facility": [
            "Facility location maps and addresses",
            "Facility type classification",
            "Operational capability assessment",
            "Capacity and production analysis",
        ],
        "cyber_posture": [
            "Vulnerability assessment report",
            "Public exposure analysis",
            "Cybersecurity recommendations",
            "Risk scoring and prioritization",
        ],
        "financial": [
            "Revenue trends and analysis",
            "Profitability and margin analysis",
            "Liquidity and cash flow assessment",
            "Financial risk scoring",
        ],
        "sanctions_screening": [
            "OFAC SDN match/no-match certification",
            "PEP screening results",
            "International sanctions list review",
            "Beneficial owner screening certificate",
        ],
        "regulatory_compliance": [
            "CMMC maturity level assessment",
            "ITAR registration status verification",
            "DDTC registration audit",
            "CUI handling compliance review",
        ],
    }
    return deliverables_map.get(gap_type, ["Research report", "Data summary", "Risk assessment"])


def _get_data_sources_for_gap_type(gap_type: str) -> list[str]:
    """Get typical data sources needed for a gap type."""
    sources_map = {
        "subcontractor_identity": ["SAM.gov", "FPDS-NG", "USASpending", "LinkedIn", "Company websites"],
        "ownership_chain": ["SEC Edgar", "OpenCorporates", "State registrations", "UCC filings"],
        "contract_history": ["FPDS.gov", "USASpending.gov", "SAM.gov", "Proprietary databases"],
        "personnel": ["LinkedIn", "SEC filings", "News archives", "Company bios"],
        "facility": ["NAICS mapper", "EPA ECHO", "Permitting records", "Satellite imagery"],
        "cyber_posture": ["CVSS", "Shodan", "Certificate transparency", "Public vulnerability DBs"],
        "financial": ["SEC Edgar", "D&B", "Government payment records", "Commercial databases"],
        "sanctions_screening": ["OFAC SDN", "International sanctions", "PEP databases"],
        "regulatory_compliance": ["CMMC registry", "ITAR directorate", "DDTC records"],
    }
    return sources_map.get(gap_type, ["Public sources", "Commercial databases"])


def _determine_priority(gaps: list[dict]) -> str:
    """Determine priority level based on gap severity."""
    max_severity = max((g.get("severity") for g in gaps), default="low")
    priority_map = {
        "critical": "critical",
        "high": "high",
        "medium": "medium",
        "low": "low",
    }
    return priority_map.get(max_severity, "medium")


def _create_combined_proposal(proposals: list[AdvisoryProposal], vendor_name: str,
                              vehicle_name: str, client_company: str) -> AdvisoryProposal:
    """Create a combined proposal addressing all gap types together."""
    total_value = sum(p.estimated_value for p in proposals)
    total_duration = sum(p.estimated_duration_days for p in proposals)
    max_confidence = max((p.confidence_of_fill for p in proposals), default=0.75)

    combined = AdvisoryProposal(
        proposal_id=f"prop_{client_company}_combined_{uuid.uuid4().hex[:8]}",
        title=f"{vendor_name} Comprehensive Intelligence Assessment",
        client_company=client_company,
        vehicle_name=vehicle_name,
        gaps_addressed=[gap for p in proposals for gap in p.gaps_addressed],
        scope_of_work=f"Comprehensive intelligence assessment covering {len(proposals)} key intelligence gaps for {vendor_name}. Holistic approach delivers integrated understanding of vendor risk posture, ownership, financial health, and regulatory compliance.",
        methodology=[m for p in proposals for m in p.methodology],
        deliverables=[d for p in proposals for d in p.deliverables],
        estimated_value=total_value,
        estimated_duration_days=total_duration,
        priority="high",
        data_sources_required=list(set(s for p in proposals for s in p.data_sources_required)),
        fill_methods=list(set(m for p in proposals for m in p.fill_methods)),
        confidence_of_fill=max_confidence * 0.95,  # Slightly reduce for combined effort
    )

    return combined


# ---------------------------------------------------------------------------
# HTML Rendering
# ---------------------------------------------------------------------------

def generate_proposal_html(proposals: list[AdvisoryProposal], pipeline_result: PipelineResult) -> str:
    """
    Generate a professional HTML proposal document from advisory proposals.

    Same dark theme as dossier.py (background: #0F1923, cards: #1A2736, gold accent: #C4A052).
    Self-contained, print-ready.

    Sections:
    - Cover page with Xiphos branding
    - Executive summary (total pipeline value, gap breakdown)
    - Per-proposal detail (scope, methodology, deliverables, pricing)
    - Appendix: Axiom fill attempts summary (what was tried and what was learned)
    """

    timestamp = datetime.now(timezone.utc).strftime("%B %d, %Y")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Xiphos Intelligence Advisory Proposal</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #0F1923;
            color: #E8E8E8;
            line-height: 1.6;
            padding: 40px;
        }}

        .page {{
            max-width: 900px;
            margin: 0 auto;
            background-color: #1A2736;
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.4);
            padding: 60px;
            page-break-after: always;
            margin-bottom: 40px;
        }}

        .page-break {{
            page-break-after: always;
            margin-bottom: 60px;
        }}

        .cover-page {{
            display: flex;
            flex-direction: column;
            justify-content: center;
            min-height: 600px;
            text-align: center;
            background: linear-gradient(135deg, #0F1923 0%, #1A2736 100%);
        }}

        .logo {{
            font-size: 48px;
            font-weight: 900;
            color: #C4A052;
            margin-bottom: 40px;
            letter-spacing: 2px;
        }}

        .logo-tagline {{
            font-size: 14px;
            color: #999;
            letter-spacing: 3px;
            margin-bottom: 60px;
            text-transform: uppercase;
        }}

        h1 {{
            font-size: 42px;
            margin-bottom: 20px;
            color: #FFFFFF;
            line-height: 1.2;
        }}

        h2 {{
            font-size: 28px;
            margin: 30px 0 20px;
            color: #C4A052;
            border-bottom: 2px solid #C4A052;
            padding-bottom: 10px;
        }}

        h3 {{
            font-size: 18px;
            margin: 20px 0 10px;
            color: #E8E8E8;
        }}

        h4 {{
            font-size: 14px;
            margin: 15px 0 8px;
            color: #C4A052;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}

        .subtitle {{
            font-size: 18px;
            color: #C4A052;
            margin: 20px 0;
        }}

        .proposal-date {{
            font-size: 14px;
            color: #999;
            margin-top: 60px;
        }}

        .executive-summary {{
            background-color: rgba(196, 160, 82, 0.1);
            border-left: 4px solid #C4A052;
            padding: 20px;
            margin: 20px 0;
            border-radius: 4px;
        }}

        .summary-stats {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin: 20px 0;
        }}

        .stat-block {{
            background-color: rgba(196, 160, 82, 0.15);
            padding: 15px;
            border-radius: 4px;
            border-left: 3px solid #C4A052;
        }}

        .stat-value {{
            font-size: 28px;
            font-weight: bold;
            color: #C4A052;
        }}

        .stat-label {{
            font-size: 12px;
            color: #999;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-top: 5px;
        }}

        .proposal-card {{
            background-color: rgba(196, 160, 82, 0.05);
            border: 1px solid rgba(196, 160, 82, 0.3);
            border-radius: 6px;
            padding: 25px;
            margin: 20px 0;
        }}

        .proposal-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 20px;
            border-bottom: 1px solid rgba(196, 160, 82, 0.2);
            padding-bottom: 15px;
        }}

        .proposal-title {{
            font-size: 22px;
            color: #FFFFFF;
            margin-bottom: 5px;
        }}

        .proposal-id {{
            font-size: 11px;
            color: #666;
            font-family: 'Courier New', monospace;
        }}

        .proposal-price {{
            font-size: 32px;
            color: #C4A052;
            font-weight: bold;
        }}

        .proposal-price-label {{
            font-size: 12px;
            color: #999;
        }}

        .section {{
            margin: 20px 0;
        }}

        .section-label {{
            font-size: 11px;
            color: #C4A052;
            text-transform: uppercase;
            letter-spacing: 2px;
            margin: 15px 0 10px;
        }}

        .gap-list {{
            margin: 10px 0;
        }}

        .gap-item {{
            background-color: rgba(220, 53, 69, 0.1);
            border-left: 3px solid #dc3545;
            padding: 10px;
            margin: 8px 0;
            border-radius: 3px;
            font-size: 13px;
        }}

        .gap-type {{
            color: #C4A052;
            font-weight: 600;
        }}

        ul, ol {{
            margin-left: 20px;
            margin-top: 10px;
        }}

        li {{
            margin: 8px 0;
            font-size: 13px;
        }}

        .metadata {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin: 20px 0;
            font-size: 13px;
        }}

        .metadata-item {{
            background-color: rgba(232, 232, 232, 0.05);
            padding: 10px;
            border-radius: 4px;
        }}

        .metadata-label {{
            font-size: 10px;
            color: #999;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}

        .metadata-value {{
            margin-top: 5px;
            color: #E8E8E8;
        }}

        .methodology {{
            background-color: rgba(0, 255, 0, 0.05);
            border-left: 3px solid #0f0;
            padding: 15px;
            margin: 15px 0;
            border-radius: 4px;
        }}

        .methodology h4 {{
            color: #0f0;
            margin-bottom: 10px;
        }}

        .confidence-meter {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 10px 0;
        }}

        .confidence-bar {{
            flex: 1;
            height: 8px;
            background-color: rgba(232, 232, 232, 0.1);
            border-radius: 4px;
            overflow: hidden;
        }}

        .confidence-fill {{
            height: 100%;
            background-color: #C4A052;
            border-radius: 4px;
        }}

        .confidence-text {{
            font-size: 12px;
            color: #999;
        }}

        .priority-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin: 5px 0;
        }}

        .priority-critical {{
            background-color: rgba(220, 53, 69, 0.3);
            color: #ff6b6b;
            border: 1px solid #dc3545;
        }}

        .priority-high {{
            background-color: rgba(196, 160, 82, 0.3);
            color: #ffc764;
            border: 1px solid #C4A052;
        }}

        .priority-medium {{
            background-color: rgba(255, 193, 7, 0.2);
            color: #ffc107;
            border: 1px solid #ffc107;
        }}

        .priority-low {{
            background-color: rgba(13, 202, 240, 0.2);
            color: #0dcaf0;
            border: 1px solid #0dcaf0;
        }}

        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid rgba(196, 160, 82, 0.2);
            font-size: 12px;
            color: #666;
            text-align: center;
        }}

        .appendix {{
            background-color: rgba(0, 0, 0, 0.2);
            padding: 20px;
            border-radius: 4px;
            margin: 20px 0;
        }}

        .appendix h4 {{
            margin-bottom: 10px;
        }}

        @media print {{
            body {{
                padding: 0;
            }}
            .page {{
                margin: 0;
                padding: 40px;
                box-shadow: none;
            }}
        }}

        .separator {{
            height: 2px;
            background: linear-gradient(90deg, transparent, #C4A052, transparent);
            margin: 40px 0;
        }}
    </style>
</head>
<body>
"""

    # Cover Page
    html += f"""
    <div class="page cover-page">
        <div class="logo">XIPHOS</div>
        <div class="logo-tagline">Counterparty. Cyber. Export. Intelligence.</div>
        <h1>Intelligence Advisory<br>Proposal</h1>
        <p class="subtitle">Gap Analysis & Consulting Services</p>
        <div class="proposal-date">Prepared: {timestamp}</div>
    </div>

    <div class="page">
        <h2>Executive Summary</h2>
        <div class="executive-summary">
            <p>This proposal addresses <strong>{pipeline_result.gaps_remaining}</strong> identified intelligence gaps across <strong>{pipeline_result.total_gaps_identified}</strong> total gaps discovered during initial assessment. {pipeline_result.gaps_filled_by_axiom} gaps were successfully resolved through automated OSINT methods.</p>
        </div>

        <div class="summary-stats">
            <div class="stat-block">
                <div class="stat-value">${pipeline_result.total_pipeline_value:,.0f}</div>
                <div class="stat-label">Total Engagement Value</div>
            </div>
            <div class="stat-block">
                <div class="stat-value">{len(proposals)}</div>
                <div class="stat-label">Proposals</div>
            </div>
            <div class="stat-block">
                <div class="stat-value">{pipeline_result.total_gaps_identified}</div>
                <div class="stat-label">Gaps Identified</div>
            </div>
            <div class="stat-block">
                <div class="stat-value">{pipeline_result.gaps_filled_by_axiom}</div>
                <div class="stat-label">Gaps Auto-Filled</div>
            </div>
        </div>

        <h3>Gap Distribution</h3>
        <p>The identified gaps fall into the following categories:</p>
        <ul>
"""

    gap_type_counts = {}
    for proposal in proposals:
        for gap in proposal.gaps_addressed:
            gap_type = gap.get("gap_type", "unknown")
            gap_type_counts[gap_type] = gap_type_counts.get(gap_type, 0) + 1

    for gap_type, count in sorted(gap_type_counts.items()):
        html += f"            <li><strong>{gap_type.replace('_', ' ').title()}:</strong> {count} gap{'s' if count != 1 else ''}</li>\n"

    html += """
        </ul>

        <div class="separator"></div>

        <h3>Approach</h3>
        <p>Xiphos executes intelligence gap closure through:</p>
        <ol>
            <li><strong>OSINT Collection:</strong> Leveraging 29+ public data sources (SAM.gov, FPDS, SEC Edgar, LinkedIn, etc.)</li>
            <li><strong>Network Intelligence:</strong> Targeted inquiries to industry partners and connectors</li>
            <li><strong>Regulatory Research:</strong> FOIA requests and government record searches where appropriate</li>
            <li><strong>Analysis & Synthesis:</strong> Expert synthesis of discovered intelligence into actionable assessments</li>
            <li><strong>Structured Delivery:</strong> Intelligence formatted to support decision-making and compliance workflows</li>
        </ol>
    </div>
"""

    # Individual Proposals
    for i, proposal in enumerate(proposals):
        if proposal.title.lower() != "comprehensive intelligence assessment":  # Skip combined proposal for now
            html += _render_proposal_page(proposal, pipeline_result)

    # Combined proposal (if exists)
    combined_proposals = [p for p in proposals if p.title.lower() == "comprehensive intelligence assessment"]
    if combined_proposals:
        html += _render_proposal_page(combined_proposals[0], pipeline_result, is_combined=True)

    # Appendix
    html += f"""
    <div class="page">
        <h2>Appendix: Automated Gap Closure Attempts</h2>
        <p>The following intelligence gaps were submitted to Xiphos' automated gap closure system (AXIOM). Results below reflect what was attempted and what was learned:</p>
"""

    if pipeline_result.axiom_fill_results:
        html += "        <div class=\"appendix\">\n"
        for result in pipeline_result.axiom_fill_results:
            html += f"            <h4>{result.get('gap_type', 'Unknown')}:</h4>\n"
            html += f"            <p><strong>Status:</strong> {result.get('status', 'unknown')}</p>\n"
            if result.get('reasoning'):
                html += f"            <p><strong>Finding:</strong> {result.get('reasoning')}</p>\n"
            html += "            <br>\n"
        html += "        </div>\n"
    else:
        html += "        <p><em>No automated gap closure attempts were recorded.</em></p>\n"

    html += """
        <div class="footer">
            <p>Xiphos LLC | San Diego, CA | www.xiphosllc.com</p>
            <p style="margin-top: 10px; font-size: 10px;">This proposal contains analysis of publicly available information. Classification: Unclassified.</p>
        </div>
    </div>

</body>
</html>
"""

    return html


def _render_proposal_page(proposal: AdvisoryProposal, pipeline_result: PipelineResult,
                          is_combined: bool = False) -> str:
    """Render a single proposal as an HTML page."""

    priority_class = f"priority-{proposal.priority}"

    html = f"""
    <div class="page page-break">
        <div class="proposal-header">
            <div>
                <div class="proposal-title">{proposal.title}</div>
                <div class="proposal-id">{proposal.proposal_id}</div>
            </div>
            <div>
                <div class="proposal-price">${proposal.estimated_value:,.0f}</div>
                <div class="proposal-price-label">Estimated Value</div>
            </div>
        </div>

        <div style="margin-bottom: 15px;">
            <span class="priority-badge {priority_class}">{proposal.priority} Priority</span>
        </div>

        <div class="metadata">
            <div class="metadata-item">
                <div class="metadata-label">Client</div>
                <div class="metadata-value">{proposal.client_company}</div>
            </div>
            <div class="metadata-item">
                <div class="metadata-label">Vehicle/Program</div>
                <div class="metadata-value">{proposal.vehicle_name or "Not specified"}</div>
            </div>
            <div class="metadata-item">
                <div class="metadata-label">Duration</div>
                <div class="metadata-value">{proposal.estimated_duration_days} business days</div>
            </div>
            <div class="metadata-item">
                <div class="metadata-label">Fill Confidence</div>
                <div class="metadata-value">{proposal.confidence_of_fill:.0%}</div>
            </div>
        </div>

        <h3>Intelligence Gaps Addressed</h3>
        <div class="gap-list">
"""

    for gap in proposal.gaps_addressed:
        severity_class = {"critical": "#dc3545", "high": "#C4A052", "medium": "#ffc107", "low": "#0dcaf0"}.get(gap.get("severity", "medium"), "#6c757d")
        html += f"""            <div style="background-color: rgba(196, 160, 82, 0.1); border-left: 3px solid {severity_class}; padding: 10px; margin: 8px 0; border-radius: 3px;">
                <div><span class="gap-type">{gap.get('gap_type', 'Unknown').replace('_', ' ').title()}</span> — {gap.get('description', '')}</div>
                <div style="font-size: 11px; color: #999; margin-top: 3px;">Severity: {gap.get('severity', 'unknown').upper()}</div>
            </div>
"""

    html += """        </div>

        <h3>Scope of Work</h3>
        <p>"""
    html += proposal.scope_of_work
    html += """</p>

        <h3>Methodology</h3>
        <div class="methodology">
            <h4>Approach:</h4>
            <ol>
"""

    for method in proposal.methodology:
        html += f"                <li>{method}</li>\n"

    html += """            </ol>
        </div>

        <h3>Deliverables</h3>
        <ul>
"""

    for deliverable in proposal.deliverables:
        html += f"            <li>{deliverable}</li>\n"

    html += """        </ul>

        <h3>Data Sources</h3>
        <p>This engagement will leverage the following primary data sources:</p>
        <ul>
"""

    for source in proposal.data_sources_required:
        html += f"            <li>{source}</li>\n"

    html += """        </ul>

        <h3>Fill Methods</h3>
        <p>Xiphos will employ the following collection methods to close these gaps:</p>
        <ul>
"""

    for method in proposal.fill_methods:
        method_display = method.replace('_', ' ').title()
        html += f"            <li>{method_display}</li>\n"

    html += f"""        </ul>

        <h3>Confidence & Risk</h3>
        <div class="confidence-meter">
            <div class="confidence-bar">
                <div class="confidence-fill" style="width: {proposal.confidence_of_fill * 100}%;"></div>
            </div>
            <span class="confidence-text">{proposal.confidence_of_fill:.0%} confidence of successful gap closure</span>
        </div>

        <p style="font-size: 12px; color: #999; margin-top: 15px;">
            Confidence estimate reflects our assessment of data availability and collection methodology feasibility. Some gaps may require extended timelines or specialized access not estimated here.
        </p>

        <div class="separator"></div>

        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid rgba(196, 160, 82, 0.2); font-size: 12px; color: #999;">
            <p><strong>Next Steps:</strong> Upon approval, Xiphos will execute collection and analysis within the estimated timeline. Weekly updates will be provided during execution. Deliverables will be formatted per customer requirements (interactive dashboard, PDF report, API integration, etc.).</p>
        </div>
    </div>
"""

    return html


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def run_gap_advisory_pipeline(
    vendor_ids: list[str],
    vehicle_name: str = "",
    client_company: str = "",
    api_key: str = "",
    provider: str = "anthropic",
    model: str = "claude-sonnet-4-6",
    user_id: str = "",
    skip_axiom_fill: bool = False,
) -> PipelineResult:
    """
    Run the full gap extraction -> Axiom fill -> advisory proposal pipeline.

    1. Extract gaps from vendor dossier contexts
    2. Send gaps through Axiom gap filler (wise case officer)
    3. Generate advisory proposals for unfilled gaps
    4. Return complete pipeline result

    Args:
        vendor_ids: List of vendor IDs to process
        vehicle_name: Contract vehicle name
        client_company: Client company name
        api_key: API key for LLM calls
        provider: LLM provider (anthropic, openai, etc.)
        model: Model name (e.g., claude-sonnet-4-6)
        user_id: User ID for context
        skip_axiom_fill: For testing, skip Axiom fill step

    Returns:
        PipelineResult with all gaps, filled gaps, and generated proposals
    """
    import time
    start_time = time.time()

    logger.info("run_gap_advisory_pipeline: starting with %d vendors", len(vendor_ids))

    all_gaps = []
    all_filled_gaps = []
    all_unfilled_gaps = []
    all_proposals = []

    # Extract gaps from all vendors
    for vendor_id in vendor_ids:
        dossier_context = build_dossier_context(vendor_id, user_id=user_id)
        gaps = extract_gaps_from_context(vendor_id, dossier_context)
        all_gaps.extend(gaps)

        # Attempt Axiom fill (unless skipped)
        vendor_unfilled_gaps = gaps

        if gaps and not skip_axiom_fill:
            filled, unfilled = attempt_axiom_fill(
                gaps,
                vendor_id,
                api_key=api_key,
                provider=provider,
                model=model,
                user_id=user_id,
            )
            all_filled_gaps.extend(filled)
            all_unfilled_gaps.extend(unfilled)
            vendor_unfilled_gaps = unfilled
        else:
            all_unfilled_gaps.extend(gaps)

        # Generate proposals for unfilled gaps
        proposals = generate_advisory_proposals(
            vendor_unfilled_gaps,
            vendor_id,
            vehicle_name=vehicle_name,
            client_company=client_company or vendor_id,
        )
        all_proposals.extend(proposals)

    # Calculate metrics
    total_pipeline_value = sum(p.estimated_value for p in all_proposals)
    elapsed_ms = int((time.time() - start_time) * 1000)

    # Prepare Axiom fill results summary
    axiom_summary = [
        {
            "gap_type": gap.get("gap_type"),
            "status": gap.get("axiom_validation", {}).get("outcome", "accepted"),
            "confidence_label": gap.get("axiom_validation", {}).get("confidence_label", ""),
            "reasons": list(gap.get("axiom_validation", {}).get("reasons", []) or [])[:3],
        }
        for gap in all_filled_gaps
    ]

    result = PipelineResult(
        total_gaps_identified=len(all_gaps),
        gaps_filled_by_axiom=len(all_filled_gaps),
        gaps_remaining=len(all_unfilled_gaps),
        proposals_generated=all_proposals,
        total_pipeline_value=total_pipeline_value,
        axiom_fill_results=axiom_summary,
        elapsed_ms=elapsed_ms,
    )

    logger.info(
        "run_gap_advisory_pipeline: complete. gaps=%d, filled=%d, remaining=%d, proposals=%d, value=$%.0f",
        len(all_gaps),
        len(all_filled_gaps),
        len(all_unfilled_gaps),
        len(all_proposals),
        total_pipeline_value,
    )

    return result
