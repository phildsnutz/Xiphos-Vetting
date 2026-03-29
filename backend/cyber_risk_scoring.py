"""
Cyber Risk Scoring Engine.

Provides multi-dimensional cyber risk scoring for vendors based on CMMC readiness,
vulnerability exposure, remediation posture, supply chain propagation, and compliance
maturity. Combines evidence from SPRS, OSCAL, NVD, and knowledge graph data into a
composite 0.0-1.0 score and categorical tier assignment.

Pattern: evidence inputs -> scored dimensions -> weighted composite -> tier assignment
"""

from __future__ import annotations

from typing import Any


# Tier thresholds
TIER_THRESHOLDS = {
    "LOW": (0.0, 0.20),
    "MODERATE": (0.20, 0.40),
    "ELEVATED": (0.40, 0.60),
    "HIGH": (0.60, 0.80),
    "CRITICAL": (0.80, 1.0),
}

DIMENSION_WEIGHTS = {
    "cmmc_readiness": 0.25,
    "vulnerability_exposure": 0.30,
    "remediation_posture": 0.20,
    "supply_chain_propagation": 0.15,
    "compliance_maturity": 0.10,
}


# ---------------------------------------------------------------------------
# Scoring Helpers
# ---------------------------------------------------------------------------

def _tier_from_score(score: float) -> str:
    """Map numeric score to risk tier."""
    score = max(0.0, min(1.0, score))
    for tier, (lower, upper) in TIER_THRESHOLDS.items():
        if lower <= score < upper:
            return tier
    return "CRITICAL"


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int."""
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float."""
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    """Safely convert value to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in {"true", "yes", "1", "on"}
    return default


# ---------------------------------------------------------------------------
# Dimension Scorers
# ---------------------------------------------------------------------------

def _score_cmmc_readiness(
    sprs_summary: dict[str, Any] | None,
    *,
    profile: str = "",
) -> dict[str, Any]:
    """
    Score CMMC readiness based on SPRS data.

    Factors:
    - Current CMMC level (0-3, higher is better)
    - Assessment recency
    - SPRS score (if available)
    - POA&M active status

    Returns: {score, weight, factors, confidence}
    """
    if not sprs_summary:
        return {
            "score": 0.75,  # Worst-case assumption
            "weight": DIMENSION_WEIGHTS["cmmc_readiness"],
            "factors": [
                {"factor": "no_sprs_data", "impact": -0.75, "detail": "No SPRS data available"}
            ],
            "confidence": 0.3,
        }

    current_level = _safe_int(sprs_summary.get("current_cmmc_level"), 0)
    assessment_status = str(sprs_summary.get("assessment_status") or "").lower()
    poam_active = _safe_bool(sprs_summary.get("poam_active"), False)
    factors: list[dict[str, Any]] = []

    # Base score from CMMC level (0=0.80, 1=0.60, 2=0.40, 3=0.20)
    level_scores = [0.80, 0.60, 0.40, 0.20]
    level_score = level_scores[min(current_level, 3)]
    factors.append({
        "factor": f"cmmc_level_{current_level}",
        "impact": level_score - 0.5,
        "detail": f"Current CMMC level: {current_level}",
    })

    # Assessment recency (assessment_status as proxy)
    if assessment_status in {"passed", "assessed", "certified"}:
        factors.append({
            "factor": "recent_assessment",
            "impact": -0.10,
            "detail": "Assessment status indicates recent evaluation",
        })
    else:
        factors.append({
            "factor": "stale_assessment",
            "impact": 0.10,
            "detail": "Assessment status is not current or missing",
        })

    # POA&M status
    if poam_active:
        factors.append({
            "factor": "poam_active",
            "impact": 0.05,
            "detail": "Plan of Action and Milestones is active (remediation in progress)",
        })
    else:
        factors.append({
            "factor": "poam_inactive",
            "impact": -0.05,
            "detail": "No active POA&M (concerning or assessment complete)",
        })

    # CMMC Level 0 with defense_acquisition profile = automatic floor
    if current_level == 0 and profile.lower() == "defense_acquisition":
        factors.append({
            "factor": "cmmc_l0_defense_profile",
            "impact": 0.25,
            "detail": "CMMC Level 0 with defense acquisition profile (high risk)",
        })

    # Compute score
    base_score = level_score
    adjustments = sum(f.get("impact", 0.0) for f in factors)
    score = max(0.0, min(1.0, base_score + adjustments))

    confidence = 0.85 if assessment_status else 0.6
    if current_level is None:
        confidence = 0.3

    return {
        "score": score,
        "weight": DIMENSION_WEIGHTS["cmmc_readiness"],
        "factors": factors,
        "confidence": confidence,
    }


def _score_vulnerability_exposure(
    nvd_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Score vulnerability exposure based on NVD/CVE data.

    Factors:
    - Critical CVE count
    - High CVE count
    - Total CVE count
    - CISA KEV presence

    Returns: {score, weight, factors, confidence}
    """
    if not nvd_summary:
        return {
            "score": 0.5,
            "weight": DIMENSION_WEIGHTS["vulnerability_exposure"],
            "factors": [
                {"factor": "no_nvd_data", "impact": 0.0, "detail": "No NVD data available"}
            ],
            "confidence": 0.3,
        }

    critical_count = _safe_int(nvd_summary.get("critical_cve_count"), 0)
    high_count = _safe_int(nvd_summary.get("high_or_critical_cve_count"), 0) - critical_count
    total_count = _safe_int(nvd_summary.get("total_cve_count"), high_count + critical_count)
    kev_count = _safe_int(nvd_summary.get("kev_flagged_cve_count"), 0)

    factors: list[dict[str, Any]] = []

    # Critical CVEs: 0.25 per critical (capped at 0.75)
    critical_impact = min(0.75, critical_count * 0.25)
    factors.append({
        "factor": f"critical_cves_{critical_count}",
        "impact": critical_impact,
        "detail": f"{critical_count} critical CVEs found",
    })

    # High CVEs: 0.10 per high (capped at 0.40)
    high_impact = min(0.40, high_count * 0.10)
    factors.append({
        "factor": f"high_cves_{high_count}",
        "impact": high_impact,
        "detail": f"{high_count} high-severity CVEs found",
    })

    # KEV presence: automatic 0.35 impact (actively exploited)
    if kev_count > 0:
        factors.append({
            "factor": f"kev_count_{kev_count}",
            "impact": 0.35,
            "detail": f"{kev_count} CVEs in CISA KEV (actively exploited)",
        })

    # Total CVE burden
    if total_count == 0:
        factors.append({
            "factor": "no_cves",
            "impact": -0.25,
            "detail": "No CVEs detected (positive signal)",
        })
    elif total_count > 50:
        factors.append({
            "factor": "high_cve_burden",
            "impact": 0.10,
            "detail": f"High CVE burden ({total_count} total)",
        })

    # Compute score
    base_score = min(1.0, sum(f.get("impact", 0.0) for f in factors))
    if kev_count > 0:
        base_score = max(base_score, 0.60)  # KEV automatically floors at HIGH

    confidence = 0.85 if any(nvd_summary.get(k) for k in ["critical_cve_count", "kev_flagged_cve_count"]) else 0.5

    return {
        "score": base_score,
        "weight": DIMENSION_WEIGHTS["vulnerability_exposure"],
        "factors": factors,
        "confidence": confidence,
    }


def _score_remediation_posture(
    sprs_summary: dict[str, Any] | None,
    oscal_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Score remediation posture based on POA&M and compliance status.

    Factors:
    - POA&M active status
    - Open POA&M items count
    - Historical remediation velocity (inferred from assessment frequency)

    Returns: {score, weight, factors, confidence}
    """
    if not sprs_summary and not oscal_summary:
        return {
            "score": 0.5,
            "weight": DIMENSION_WEIGHTS["remediation_posture"],
            "factors": [
                {"factor": "no_remediation_data", "impact": 0.0, "detail": "No remediation data available"}
            ],
            "confidence": 0.3,
        }

    factors: list[dict[str, Any]] = []

    # POA&M status
    poam_active = _safe_bool(sprs_summary.get("poam_active") if sprs_summary else None, False)
    if poam_active:
        factors.append({
            "factor": "poam_active",
            "impact": -0.20,
            "detail": "Active remediation plan in place",
        })
    else:
        factors.append({
            "factor": "poam_inactive",
            "impact": 0.15,
            "detail": "No active remediation plan",
        })

    # Open POA&M items
    open_items = _safe_int(oscal_summary.get("open_poam_items") if oscal_summary else None, 0)
    if open_items == 0:
        factors.append({
            "factor": "no_open_items",
            "impact": -0.20,
            "detail": "No open remediation items",
        })
    elif open_items < 5:
        factors.append({
            "factor": f"open_items_{open_items}",
            "impact": -0.10,
            "detail": f"{open_items} open remediation items (manageable)",
        })
    elif open_items < 15:
        factors.append({
            "factor": f"open_items_{open_items}",
            "impact": 0.05,
            "detail": f"{open_items} open remediation items (moderate workload)",
        })
    else:
        factors.append({
            "factor": f"open_items_{open_items}",
            "impact": 0.20,
            "detail": f"{open_items} open remediation items (high workload)",
        })

    # Compute score (remediation posture: lower is better)
    base_score = 0.5
    adjustments = sum(f.get("impact", 0.0) for f in factors)
    score = max(0.0, min(1.0, base_score + adjustments))

    confidence = 0.75 if poam_active else 0.5

    return {
        "score": score,
        "weight": DIMENSION_WEIGHTS["remediation_posture"],
        "factors": factors,
        "confidence": confidence,
    }


def _score_supply_chain_propagation(
    graph_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Score supply chain risk based on network connectivity.

    Factors:
    - Number of related vulnerable entities (2-hop)
    - Criticality of connected entities
    - Relationship types (e.g., parent/subsidiary)

    Returns: {score, weight, factors, confidence}
    """
    if not graph_data or not isinstance(graph_data, dict):
        return {
            "score": 0.3,
            "weight": DIMENSION_WEIGHTS["supply_chain_propagation"],
            "factors": [
                {"factor": "no_graph_data", "impact": 0.0, "detail": "No graph data available"}
            ],
            "confidence": 0.4,
        }

    entities = graph_data.get("entities") or []
    relationships = graph_data.get("relationships") or []
    factors: list[dict[str, Any]] = []

    # Count critical entities in graph
    critical_count = len([e for e in entities if e.get("risk_level") == "critical"])
    high_count = len([e for e in entities if e.get("risk_level") == "high"])

    if critical_count > 0:
        factors.append({
            "factor": f"critical_entities_{critical_count}",
            "impact": min(0.4, critical_count * 0.15),
            "detail": f"{critical_count} critical entities in supply chain",
        })

    if high_count > 0:
        factors.append({
            "factor": f"high_entities_{high_count}",
            "impact": min(0.20, high_count * 0.05),
            "detail": f"{high_count} high-risk entities in supply chain",
        })

    # Count relationships (network density)
    rel_count = len(relationships)
    if rel_count == 0:
        factors.append({
            "factor": "isolated_entity",
            "impact": -0.15,
            "detail": "No related entities in graph (low propagation risk)",
        })
    elif rel_count < 3:
        factors.append({
            "factor": "low_connectivity",
            "impact": 0.05,
            "detail": "Low network connectivity",
        })
    elif rel_count < 8:
        factors.append({
            "factor": "moderate_connectivity",
            "impact": 0.15,
            "detail": "Moderate network connectivity",
        })
    else:
        factors.append({
            "factor": "high_connectivity",
            "impact": 0.25,
            "detail": "High network connectivity (risk propagation risk)",
        })

    # Compute score
    base_score = 0.3
    adjustments = sum(f.get("impact", 0.0) for f in factors)
    score = max(0.0, min(1.0, base_score + adjustments))

    confidence = 0.6 if rel_count > 0 else 0.3

    return {
        "score": score,
        "weight": DIMENSION_WEIGHTS["supply_chain_propagation"],
        "factors": factors,
        "confidence": confidence,
    }


def _score_compliance_maturity(
    oscal_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Score compliance maturity based on OSCAL control implementation.

    Factors:
    - Control implementation percentage
    - Total control references
    - System assessment status

    Returns: {score, weight, factors, confidence}
    """
    if not oscal_summary or not isinstance(oscal_summary, dict):
        return {
            "score": 0.5,
            "weight": DIMENSION_WEIGHTS["compliance_maturity"],
            "factors": [
                {"factor": "no_oscal_data", "impact": 0.0, "detail": "No OSCAL data available"}
            ],
            "confidence": 0.3,
        }

    factors: list[dict[str, Any]] = []

    # Control implementation percentage (if available)
    total_controls = _safe_int(oscal_summary.get("total_control_references"), 0)
    implemented_controls = _safe_int(oscal_summary.get("implemented_control_count"), 0)

    if total_controls > 0:
        impl_pct = (implemented_controls / total_controls) * 100.0
        score = 1.0 - (impl_pct / 100.0)  # 100% implemented = 0.0 score (good)
        factors.append({
            "factor": "control_implementation",
            "impact": score - 0.5,
            "detail": f"{impl_pct:.1f}% of controls ({implemented_controls}/{total_controls}) implemented",
        })
    else:
        factors.append({
            "factor": "no_controls",
            "impact": 0.25,
            "detail": "No control references found",
        })

    # System assessment status
    system_name = oscal_summary.get("system_name") or ""
    if system_name:
        factors.append({
            "factor": "system_documented",
            "impact": -0.15,
            "detail": f"System documented: {system_name}",
        })

    # Compute score
    if total_controls > 0:
        base_score = 1.0 - (implemented_controls / total_controls)
    else:
        base_score = 0.5

    adjustments = sum(f.get("impact", 0.0) for f in factors[1:])  # Skip first, it's already in base
    score = max(0.0, min(1.0, base_score + adjustments))

    confidence = 0.75 if total_controls > 0 else 0.4

    return {
        "score": score,
        "weight": DIMENSION_WEIGHTS["compliance_maturity"],
        "factors": factors,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Main Scoring Function
# ---------------------------------------------------------------------------

def score_vendor_cyber_risk(
    case_id: str,
    vendor_name: str = "",
    sprs_summary: dict[str, Any] | None = None,
    nvd_summary: dict[str, Any] | None = None,
    oscal_summary: dict[str, Any] | None = None,
    graph_data: dict[str, Any] | None = None,
    profile: str = "",
) -> dict[str, Any]:
    """
    Score vendor cyber risk across multiple dimensions.

    Aggregates CMMC, vulnerability, remediation, supply chain, and compliance
    dimensions into a composite 0.0-1.0 score and categorical tier.

    Args:
        case_id: Case ID
        vendor_name: Vendor/company name
        sprs_summary: SPRS assessment summary
        nvd_summary: NVD/CVE analysis summary
        oscal_summary: OSCAL compliance summary
        graph_data: Knowledge graph cyber subgraph
        profile: Profile name (e.g., "defense_acquisition")

    Returns:
        Comprehensive scoring result with dimensions, tier, and actions
    """

    # Score each dimension
    cmmc_dim = _score_cmmc_readiness(sprs_summary, profile=profile)
    vuln_dim = _score_vulnerability_exposure(nvd_summary)
    remed_dim = _score_remediation_posture(sprs_summary, oscal_summary)
    supply_dim = _score_supply_chain_propagation(graph_data)
    comply_dim = _score_compliance_maturity(oscal_summary)

    dimensions = {
        "cmmc_readiness": cmmc_dim,
        "vulnerability_exposure": vuln_dim,
        "remediation_posture": remed_dim,
        "supply_chain_propagation": supply_dim,
        "compliance_maturity": comply_dim,
    }

    # Compute weighted composite score
    weighted_sum = sum(
        dim["score"] * dim["weight"]
        for dim in dimensions.values()
    )
    composite_score = weighted_sum

    # Special rules: KEV or CMMC Level 0 defense profile
    kev_count = _safe_int(nvd_summary.get("kev_flagged_cve_count") if nvd_summary else None, 0)
    current_cmmc = _safe_int(sprs_summary.get("current_cmmc_level") if sprs_summary else None, None)

    if kev_count > 0:
        composite_score = max(composite_score, 0.60)

    if current_cmmc == 0 and profile.lower() == "defense_acquisition":
        composite_score = max(composite_score, 0.55)

    # Determine tier
    tier = _tier_from_score(composite_score)

    # Compute overall confidence
    confidences = [dim.get("confidence", 0.5) for dim in dimensions.values()]
    overall_confidence = sum(confidences) / len(confidences) if confidences else 0.5

    # Penalize confidence if no data sources
    has_sprs = sprs_summary is not None and bool(sprs_summary)
    has_nvd = nvd_summary is not None and bool(nvd_summary)
    has_oscal = oscal_summary is not None and bool(oscal_summary)
    data_sources_count = sum([has_sprs, has_nvd, has_oscal])

    if data_sources_count == 0:
        overall_confidence = 0.3
    elif data_sources_count == 1:
        overall_confidence = min(overall_confidence, 0.5)

    # Extract top findings
    top_findings: list[dict[str, Any]] = []

    for dim_name, dim_data in dimensions.items():
        for factor in dim_data.get("factors", []):
            top_findings.append({
                "dimension": dim_name,
                "factor": factor.get("factor", ""),
                "impact": factor.get("impact", 0.0),
                "detail": factor.get("detail", ""),
            })

    # Sort by impact magnitude (descending)
    top_findings.sort(key=lambda x: abs(x["impact"]), reverse=True)
    top_findings = top_findings[:5]

    # Generate recommended actions
    recommended_actions: list[str] = []

    if tier in {"HIGH", "CRITICAL"}:
        if kev_count > 0:
            recommended_actions.append(
                f"URGENT: {kev_count} CVEs in CISA KEV catalog (actively exploited). "
                "Prioritize patching and vulnerability remediation immediately."
            )
        if current_cmmc == 0:
            recommended_actions.append(
                "Vendor shows no CMMC certification. If defense_acquisition profile, "
                "mandate immediate CMMC Level 1 assessment."
            )
        if _safe_int(nvd_summary.get("critical_cve_count") if nvd_summary else None, 0) > 0:
            recommended_actions.append(
                "Multiple critical CVEs detected. Require detailed remediation timeline "
                "and evidence of patching plans."
            )

    if _safe_int(oscal_summary.get("open_poam_items") if oscal_summary else None, 0) > 10:
        recommended_actions.append(
            "High number of open POA&M items. Request updated remediation schedule "
            "and resource commitment."
        )

    if not has_sprs or (sprs_summary and not sprs_summary.get("assessment_status")):
        recommended_actions.append(
            "No recent CMMC/security assessment on file. Request latest assessment "
            "report or SPRS data."
        )

    if data_sources_count < 2:
        recommended_actions.append(
            "Limited cyber evidence available. Request additional security documentation "
            "(SPRS, OSCAL, vulnerability scans)."
        )

    if not recommended_actions:
        recommended_actions.append(
            "Continue monitoring vendor security posture. Schedule periodic reassessments."
        )

    return {
        "case_id": case_id,
        "vendor_name": vendor_name,
        "cyber_risk_score": composite_score,
        "cyber_risk_tier": tier,
        "dimensions": dimensions,
        "top_findings": top_findings,
        "recommended_actions": recommended_actions,
        "confidence": overall_confidence,
        "data_sources": {
            "has_sprs": has_sprs,
            "has_nvd": has_nvd,
            "has_oscal": has_oscal,
            "has_graph": graph_data is not None and bool(graph_data),
        },
    }
