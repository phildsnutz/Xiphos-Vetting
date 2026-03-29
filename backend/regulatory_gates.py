"""
Xiphos Regulatory Gate Engine v5.1 — Layer 1
DoD Supply Chain Compliance Deterministic Evaluation

Implements 13 regulatory gates that are evaluated before probabilistic
scoring. Each gate returns PASS / FAIL / PENDING. The combined status
is COMPLIANT / NON_COMPLIANT / REQUIRES_REVIEW.

Gates (Fixed):
  1.  Section 889 (FY2019 NDAA)         — Prohibited telecom entities
  2.  ITAR Compliance                    — US Munitions List items
  3.  EAR (Export Administration Regs)  — Dual-use item controls
  4.  DFARS Specialty Metals 252.225-7009 — Melting/refining origin
  5.  DFARS Covered Defense Info 252.204-7012 — CUI / CDI handling
  6.  CMMC 2.0                           — Cybersecurity maturity
  7.  FOCI (Foreign Ownership/Control)  — NIS Regulation 32 CFR Part 2004
  8.  NDAA Section 1260H CMC List       — Chinese Military Companies
  9.  CFIUS Jurisdiction                — Foreign investment screening
  10. Berry Amendment 10 USC §4862      — Domestic source for food/clothing/etc.

Gates (Optional - ITAR profile only):
  11. Deemed Export Risk (22 CFR 120.17) — Foreign national access to technical data
  12. End-Use Red Flags (BIS/DDTC)       — Transaction diversion indicators
  13. USML Category Control (22 CFR 121) — USML export to prohibited/elevated countries

Model version: 3.1-RegulatoryGate-DoD-ITAR
Author:        Xiphos Principal Risk Scientist
Date:          March 2026
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from itar_module import (
    assess_deemed_export_risk,
    check_red_flags,
    USML_CATEGORIES,
)


# ─────────────────────────────────────────────────────────────────────────────
# GATE STATES
# ─────────────────────────────────────────────────────────────────────────────

class GateState(str, Enum):
    PASS    = "PASS"
    FAIL    = "FAIL"
    PENDING = "PENDING"
    SKIP    = "SKIP"    # Gate not applicable to this context


class RegulatoryStatus(str, Enum):
    COMPLIANT       = "COMPLIANT"
    NON_COMPLIANT   = "NON_COMPLIANT"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


# ─────────────────────────────────────────────────────────────────────────────
# GATE INPUT DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Section889Input:
    entity_name: str
    parent_companies: list[str] = field(default_factory=list)
    subsidiaries: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)


@dataclass
class ITARInput:
    item_is_itar_controlled: bool = False
    entity_foreign_ownership_pct: float = 0.0
    entity_nationality_of_control: str = "US"
    entity_has_itar_compliance_certification: bool = False
    entity_manufacturing_process_certified: bool = False
    entity_has_approved_voting_agreement: bool = False
    entity_foci_status: str = "NOT_APPLICABLE"   # MITIGATED / IN_PROGRESS / UNMITIGATED / NOT_APPLICABLE
    entity_cmmc_level: int = 0
    supply_chain_tier: int = 0
    sensitivity: str = "COMMERCIAL"


@dataclass
class EARInput:
    item_ear_ccl_category: str = ""             # e.g. "3A001", "" = not controlled
    entity_foreign_origin_content_pct: float = 0.0
    entity_has_export_control_procedures: bool = False
    entity_has_export_control_document_package: bool = False
    entity_export_control_deemed_export_training_current: bool = False


@dataclass
class SpecialtyMetalsInput:
    item_contains_specialty_metals: bool = False
    # Specialty metals: tungsten, cobalt, tantalum, magnesium, titanium, aluminum-lithium
    metals_present: list[str] = field(default_factory=list)
    entity_melting_location_country: str = "US"
    entity_has_specialty_metals_certification: bool = False
    supply_chain_tier: int = 0
    # Qualifying countries per DFARS 252.225-7009
    # (US + 37 countries in qualifying country list)
    entity_is_qualifying_country: bool = True


@dataclass
class CDIInput:
    item_involves_covered_defense_info: bool = False
    entity_has_cloud_service_dod_authorization: bool = False    # FedRAMP Moderate+
    entity_has_incident_reporting_capability: bool = False
    entity_has_malicious_software_procedures: bool = False
    entity_has_media_sanitization_procedures: bool = False
    entity_preserves_images_for_60_days: bool = False
    entity_has_cyber_insurance: bool = False


@dataclass
class CMMCInput:
    handles_cui: bool = False
    required_cmmc_level: int = 0                # 0 = not required
    current_cmmc_level: int = 0
    entity_has_active_poam: bool = False         # Plan of Action & Milestones
    assessment_date: Optional[str] = None        # ISO date of last C3PAO assessment
    sensitivity: str = "COMMERCIAL"


@dataclass
class FOCIInput:
    entity_foreign_ownership_pct: float = 0.0
    entity_foreign_control_pct: float = 0.0
    foreign_controlling_country: str = ""
    entity_foci_mitigation_status: str = "NOT_APPLICABLE"  # MITIGATED / IN_PROGRESS / UNMITIGATED / NOT_APPLICABLE
    entity_has_facility_clearance: bool = False
    foci_mitigation_type: str = ""              # SSA / SCA / PP / VOTING_TRUST / PROXY
    dss_approval_obtained: bool = False
    sensitivity: str = "COMMERCIAL"


@dataclass
class NDAA1260HInput:
    entity_name: str
    parent_companies: list[str] = field(default_factory=list)
    subsidiaries: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    entity_country: str = ""


@dataclass
class CFIUSInput:
    transaction_involves_foreign_acquirer: bool = False
    foreign_acquirer_country: str = ""
    business_involves_critical_technology: bool = False
    business_involves_critical_infrastructure: bool = False
    business_involves_sensitive_personal_data: bool = False
    business_involves_real_estate_near_military: bool = False
    transaction_is_mandatory_filing: bool = False
    cfius_notice_filed: bool = False
    cfius_clearance_obtained: bool = False
    entity_is_tic_business: bool = False        # TIC = Technology, Infrastructure, or Data


@dataclass
class BerryAmendmentInput:
    item_category: str = ""                     # food / clothing / specialty_metals / hand/measuring_tools / other
    item_origin_country: str = "US"
    entity_manufacturing_country: str = "US"
    entity_has_domestic_nonavailability_determination: bool = False
    # Berry Amendment applies to specific item categories sourced from DoD appropriations
    applies_to_contract: bool = False


@dataclass
class DeemedExportGateInput:
    """Gate 11: Deemed Export Risk (22 CFR 120.17) assessment input."""
    foreign_nationals: list[dict] = field(default_factory=list)
    # Each dict in foreign_nationals should have: nationality (ISO code), role, access_level
    tcp_status: str = "NOT_REQUIRED"            # IMPLEMENTED / PENDING / NOT_REQUIRED / MISSING
    usml_category: int = 0                      # 0 = unknown/not specified, 1-21 = USML category
    facility_clearance: str = "NONE"            # SECRET / CONFIDENTIAL / UNCLASSIFIED / NONE


@dataclass
class RedFlagGateInput:
    """Gate 12: End-Use Red Flag (BIS/DDTC) assessment input."""
    transaction: dict = field(default_factory=dict)
    # Keys: routing, customer_reluctance_on_end_use, payment_method, order_quantity,
    #       customer_prior_orders, end_use_stated, packaging_description,
    #       delivery_to_freight_forwarder, declined_installation_training,
    #       end_user_description_clarity
    vendor_country: str = "US"                  # ISO country code of seller
    end_user_country: str = "US"                # ISO country code of stated end-user
    usml_category: int = 0                      # 0 = unknown, 1-21 = USML category


@dataclass
class USMLControlGateInput:
    """Gate 13: USML Category Control (22 CFR 121) assessment input."""
    usml_category: int = 0                      # 0 = not specified, 1-21 = USML category
    vendor_country: str = "US"                  # ISO country code of vendor/export destination
    # ITAR prohibited countries (no licenses available)
    itar_prohibited_countries: list[str] = field(default_factory=lambda: [
        "CN", "IR", "KP", "SY", "CU"             # China, Iran, North Korea, Syria, Cuba
    ])
    # ITAR elevated scrutiny countries (restricted licenses)
    itar_elevated_scrutiny_countries: list[str] = field(default_factory=lambda: [
        "RU", "BY", "VE", "ZW"                   # Russia, Belarus, Venezuela, Zimbabwe
    ])


@dataclass
class RegulatoryGateInput:
    """
    Unified input for all 13 regulatory gates (10 fixed + 3 optional ITAR).
    Callers should populate only the fields relevant to their context.
    """
    # Identification
    entity_name: str = ""
    entity_country: str = "US"
    sensitivity: str = "COMMERCIAL"    # SAP / SCI / TOP_SECRET / SECRET / CUI / UNCLASSIFIED / COMMERCIAL
    supply_chain_tier: int = 0         # 0=Prime, 1=Major Subsystem, 2=Component, 3=Material

    # Gate-specific inputs
    section_889: Section889Input = field(default_factory=lambda: Section889Input(entity_name=""))
    itar: ITARInput = field(default_factory=ITARInput)
    ear: EARInput = field(default_factory=EARInput)
    specialty_metals: SpecialtyMetalsInput = field(default_factory=SpecialtyMetalsInput)
    cdi: CDIInput = field(default_factory=CDIInput)
    cmmc: CMMCInput = field(default_factory=CMMCInput)
    foci: FOCIInput = field(default_factory=FOCIInput)
    ndaa_1260h: NDAA1260HInput = field(default_factory=lambda: NDAA1260HInput(entity_name=""))
    cfius: CFIUSInput = field(default_factory=CFIUSInput)
    berry: BerryAmendmentInput = field(default_factory=BerryAmendmentInput)

    # Optional ITAR-specific gates (11-13)
    deemed_export: DeemedExportGateInput = field(default_factory=DeemedExportGateInput)
    red_flag: RedFlagGateInput = field(default_factory=RedFlagGateInput)
    usml_control: USMLControlGateInput = field(default_factory=USMLControlGateInput)

    # Gate control: which gates to evaluate (list of gate IDs)
    enabled_gates: list[int] = field(default_factory=lambda: list(range(1,14)))


# ─────────────────────────────────────────────────────────────────────────────
# GATE RESULT
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GateResult:
    gate_id: int
    gate_name: str
    state: GateState
    severity: str          # CRITICAL / HIGH / MEDIUM / LOW
    regulation: str        # Regulation reference (e.g. "FY2019 NDAA Section 889")
    details: str           # Human-readable explanation
    mitigation: str        # What the entity must do to remediate
    confidence: float      # 0-1 confidence in this evaluation given available data


@dataclass
class RegulatoryAssessment:
    status: RegulatoryStatus
    passed_gates: list[GateResult]
    failed_gates: list[GateResult]
    pending_gates: list[GateResult]
    skipped_gates: list[GateResult]
    gate_proximity_score: float         # 0-1: how close to a gate failure (Layer 2 input)
    is_dod_eligible: bool
    is_dod_qualified: bool
    entity_name: str
    sensitivity: str
    supply_chain_tier: int

    def to_dict(self) -> dict:
        def _gate_dict(g: GateResult) -> dict:
            return {
                "gate_id": g.gate_id,
                "gate_name": g.gate_name,
                "state": g.state.value,
                "severity": g.severity,
                "regulation": g.regulation,
                "details": g.details,
                "mitigation": g.mitigation,
                "confidence": g.confidence,
            }
        return {
            "status": self.status.value,
            "passed_gates": [_gate_dict(g) for g in self.passed_gates],
            "failed_gates": [_gate_dict(g) for g in self.failed_gates],
            "pending_gates": [_gate_dict(g) for g in self.pending_gates],
            "gate_proximity_score": round(self.gate_proximity_score, 4),
            "is_dod_eligible": self.is_dod_eligible,
            "is_dod_qualified": self.is_dod_qualified,
        }


# ─────────────────────────────────────────────────────────────────────────────
# PROHIBITED ENTITY LISTS  (authoritative as of March 2026)
# ─────────────────────────────────────────────────────────────────────────────

# Section 889 FY2019 NDAA: Prohibited telecom/surveillance entities + subsidiaries
SECTION_889_PROHIBITED: dict[str, list[str]] = {
    "HUAWEI": [
        "HUAWEI TECHNOLOGIES", "HUAWEI TECH", "HUAWEI DEVICE", "HUAWEI MARINE",
        "HUAWEI CLOUD", "HUAWEI ENTERPRISE", "HUAWEI GLOBAL", "HISILICON",
        "HONOR DEVICE", "HUAWEI INVESTMENT",
    ],
    "ZTE": [
        "ZTE CORPORATION", "ZTE CORP", "ZTE MICROELECTRONICS", "SHENZHEN ZTE",
        "ZTE KANGXUN", "ZHONGXING TELECOMMUNICATION", "ZTE WISTRON TELETECH",
    ],
    "HYTERA": [
        "HYTERA COMMUNICATIONS", "HYTERA COMMUNICATIONS CORP",
        "HYTERA COMMUNICATIONS CO", "HYTERA MOBILFUNK",
    ],
    "HIKVISION": [
        "HIKVISION DIGITAL TECHNOLOGY", "HANGZHOU HIKVISION",
        "HIKVISION INTERNATIONAL", "EZVIZ", "HK HIKVISION",
    ],
    "DAHUA": [
        "DAHUA TECHNOLOGY", "HANGZHOU DAHUA", "DAHUA SECURITY",
        "ZHEJIANG DAHUA", "IMOU LIFE",
    ],
}

# NDAA FY2021 Section 1260H: Chinese Military Companies (CMC List)
# Per USD(P) designations — updated list
NDAA_1260H_CMC: dict[str, list[str]] = {
    "AVIC": [
        "AVIATION INDUSTRY CORPORATION", "AVIC INTERNATIONAL",
        "AVIC AEROSPACE", "AVIC SYSTEMS", "CHENGDU AIRCRAFT",
        "SHENYANG AIRCRAFT", "XIAN AIRCRAFT",
    ],
    "AERO ENGINE CORPORATION OF CHINA": [
        "AECC", "AERO ENGINE CORP", "CHINA AERO ENGINE",
    ],
    "CHINA AEROSPACE SCIENCE AND TECHNOLOGY": [
        "CASC", "CHINA AEROSPACE SCIENCE", "CAST",
    ],
    "CHINA AEROSPACE SCIENCE AND INDUSTRY": [
        "CASIC",
    ],
    "CHINA COMMUNICATIONS CONSTRUCTION": [
        "CCCC", "CHINA COMMUNICATIONS CONSTRUCTION COMPANY",
    ],
    "CHINA ELECTRONICS CORPORATION": [
        "CEC", "CHINA ELECTRONICS TECHNOLOGY",
        "CETC", "CHINA ELECTRONICS TECHNOLOGY GROUP",
    ],
    "CHINA GENERAL NUCLEAR": [
        "CGN", "CHINA GENERAL NUCLEAR POWER", "CGN NUCLEAR",
    ],
    "CHINA NATIONAL NUCLEAR": [
        "CNNC", "CHINA NATIONAL NUCLEAR CORPORATION",
    ],
    "CHINA NORTH INDUSTRIES": [
        "NORINCO", "CHINA NORTH INDUSTRIES GROUP",
        "NORINCO INTERNATIONAL", "CHINA ORDNANCE",
    ],
    "CHINA RAILWAY CONSTRUCTION": [
        "CRCC",
    ],
    "CHINA SHIPBUILDING INDUSTRY": [
        "CSIC", "CHINA SHIPBUILDING INDUSTRY CORPORATION",
    ],
    "CHINA STATE SHIPBUILDING": [
        "CSSC", "CHINA STATE SHIPBUILDING CORPORATION",
    ],
    "COFCO": [
        "COFCO CORPORATION", "CHINA NATIONAL CEREALS OIL AND FOODSTUFFS",
    ],
    "COMMERCIAL AIRCRAFT CORPORATION OF CHINA": [
        "COMAC",
    ],
    "CSSC": [
        "CHINA SHIPBUILDING SCIENTIFIC RESEARCH", "CSSRC",
    ],
    "DAWNING INFORMATION INDUSTRY": [
        "DAWNING", "SUGON",
    ],
    "HIKVISION": [  # Also on Section 889 list
        "HANGZHOU HIKVISION", "HIKVISION DIGITAL",
    ],
    "INSPUR": [
        "INSPUR GROUP", "INSPUR ELECTRONIC INFORMATION",
    ],
    "PANDA ELECTRONICS": [
        "PANDA ELECTRONICS GROUP", "NANJING PANDA",
    ],
    "SEMICONDUCTOR MANUFACTURING INTERNATIONAL": [
        "SMIC",
    ],
    "SINOVEL": [
        "SINOVEL WIND GROUP",
    ],
    "COSTAR GROUP": [
        "COSTAR TECHNOLOGIES",
    ],
}

# CFIUS mandatory filing triggers by country (adversary nation categories)
CFIUS_COVERED_COUNTRIES = {
    "CN", "RU", "IR", "KP", "CU", "VE", "SY",  # Tier 1: absolute scrutiny
    "BY", "MM", "SD", "SO", "ZW", "LY",           # Tier 2: heightened scrutiny
}

CFIUS_TID_BUSINESS_SECTORS = {
    "semiconductors", "artificial_intelligence", "autonomous_systems",
    "biotechnology", "quantum_computing", "advanced_materials",
    "nuclear_energy", "aerospace", "defense_electronics",
    "critical_infrastructure", "telecommunications",
}

# Berry Amendment covered item categories
BERRY_COVERED_CATEGORIES = {
    "food", "clothing", "fabrics", "specialty_metals",
    "hand_tools", "measuring_tools", "stainless_steel_flatware",
    "food_processing_equipment",
}

# DFARS specialty metals list
SPECIALTY_METALS = {
    "steel", "iron", "aluminum", "titanium", "zirconium",
    "tungsten", "cobalt", "tantalum", "magnesium", "aluminum_lithium",
    "chromium", "niobium", "molybdenum",
}

# Qualifying countries for specialty metals (DFARS 252.225-7009)
SPECIALTY_METALS_QUALIFYING_COUNTRIES = {
    "AU", "AT", "BE", "CA", "CZ", "DK", "EG", "FI", "FR", "DE",
    "GR", "HU", "IS", "IT", "JP", "LU", "NL", "NZ", "NO", "PL",
    "PT", "KR", "ES", "SE", "CH", "TR", "GB", "US", "IL", "BG",
    "EE", "LV", "LT", "RO", "SK", "SI", "HR", "MK", "AL",
}


# ─────────────────────────────────────────────────────────────────────────────
# GATE EVALUATORS
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    """Uppercase, strip punctuation for matching."""
    import re
    return re.sub(r"[.,\-&'\"()]", " ", name.upper()).strip()


def _matches_list(name: str, prohibited_dict: dict[str, list[str]]) -> tuple[bool, str]:
    """
    Check if name matches any entry in a prohibited dict.
    Uses substring containment on normalized names for robust matching.
    Returns (matched, key_matched).
    """
    norm = _normalize(name)
    for key, aliases in prohibited_dict.items():
        if key in norm:
            return True, key
        for alias in aliases:
            # Substring containment: alias appears in name OR name appears in alias
            if alias in norm or norm in alias:
                return True, key
    return False, ""


# ── Gate 1: Section 889 ───────────────────────────────────────────────────────

def evaluate_section_889(inp: Section889Input) -> GateResult:
    """
    FY2019 NDAA Section 889: Prohibition on use of certain telecom/surveillance equipment.
    Applies to ALL tiers and sensitivities — no mitigation path.
    """
    all_names = [inp.entity_name] + inp.parent_companies + inp.subsidiaries + inp.aliases

    for name in all_names:
        matched, key = _matches_list(name, SECTION_889_PROHIBITED)
        if matched:
            return GateResult(
                gate_id=1,
                gate_name="Section 889",
                state=GateState.FAIL,
                severity="CRITICAL",
                regulation="FY2019 NDAA Section 889(a)(1)(B) / 48 CFR 52.204-25",
                details=(
                    f"Entity '{name}' is identified as a Section 889 prohibited entity "
                    f"(matches '{key}' family). Use of this entity's telecommunications "
                    "or video surveillance equipment in any federal contract is prohibited. "
                    "This applies to the entity itself and all subsidiaries/affiliates."
                ),
                mitigation="NONE — Section 889 is an absolute prohibition with no waiver path.",
                confidence=0.99,
            )

    return GateResult(
        gate_id=1,
        gate_name="Section 889",
        state=GateState.PASS,
        severity="CRITICAL",
        regulation="FY2019 NDAA Section 889(a)(1)(B)",
        details="Entity does not appear on Section 889 prohibited entity list.",
        mitigation="N/A",
        confidence=0.95,
    )


# ── Gate 2: ITAR ─────────────────────────────────────────────────────────────

def evaluate_itar(inp: ITARInput) -> GateResult:
    """ITAR compliance based on item control status, foreign ownership, and tier."""
    if not inp.item_is_itar_controlled:
        return GateResult(
            gate_id=2, gate_name="ITAR",
            state=GateState.SKIP, severity="HIGH",
            regulation="22 CFR Parts 120-130 (ITAR)",
            details="Item is not ITAR-controlled — gate not applicable.",
            mitigation="N/A", confidence=0.90,
        )

    sensitivity = inp.sensitivity
    tier = inp.supply_chain_tier

    # Tier 2-3: may be exempt if COTS and not modified
    if tier >= 2:
        if inp.entity_has_itar_compliance_certification and inp.entity_manufacturing_process_certified:
            return GateResult(
                gate_id=2, gate_name="ITAR",
                state=GateState.PASS, severity="HIGH",
                regulation="22 CFR Parts 120-130 / DDTC",
                details=f"Tier {tier} supplier with ITAR compliance certification and certified manufacturing process.",
                mitigation="N/A", confidence=0.88,
            )
        return GateResult(
            gate_id=2, gate_name="ITAR",
            state=GateState.PENDING, severity="HIGH",
            regulation="22 CFR Parts 120-130 / DDTC",
            details=f"Tier {tier} ITAR-controlled item. ITAR compliance certification and manufacturing process audit required.",
            mitigation="Obtain ITAR compliance certification and manufacturing process certification from DDTC-registered broker.",
            confidence=0.85,
        )

    # Tier 0-1: SAP/SCI — any foreign ownership is disqualifying
    if sensitivity in ("CRITICAL_SAP", "CRITICAL_SCI"):
        if inp.entity_foreign_ownership_pct > 0.0:
            return GateResult(
                gate_id=2, gate_name="ITAR",
                state=GateState.FAIL, severity="CRITICAL",
                regulation="22 CFR Part 120.16 / DDTC / SAP Program Security Instruction",
                details=(
                    f"SAP/SCI program — foreign ownership ({inp.entity_foreign_ownership_pct * 100:.0f}%) "
                    "is categorically disqualifying. Entity cannot access ITAR items on this program."
                ),
                mitigation="NONE for SAP/SCI — entity must be 100% US-owned.",
                confidence=0.99,
            )

    # TOP_SECRET: foreign ownership allowed only with approved voting agreement + FOCI mitigated
    if sensitivity == "ELEVATED":
        if inp.entity_foreign_ownership_pct > 0.0:
            if inp.entity_has_approved_voting_agreement and inp.entity_foci_status == "MITIGATED":
                return GateResult(
                    gate_id=2, gate_name="ITAR",
                    state=GateState.PASS, severity="HIGH",
                    regulation="22 CFR Part 120.16 / 32 CFR Part 2004 (FOCI)",
                    details="Foreign ownership mitigated via approved voting agreement and DSS FOCI determination.",
                    mitigation="N/A", confidence=0.92,
                )
            return GateResult(
                gate_id=2, gate_name="ITAR",
                state=GateState.PENDING, severity="HIGH",
                regulation="22 CFR Part 120.16 / 32 CFR Part 2004",
                details=(
                    f"TOP_SECRET program — foreign ownership ({inp.entity_foreign_ownership_pct * 100:.0f}%) "
                    f"requires FOCI mitigation. Current status: {inp.entity_foci_status}."
                ),
                mitigation="Obtain DSS approval of voting agreement and FOCI mitigation plan.",
                confidence=0.90,
            )

    # SECRET/CUI: requires FOCI mitigation or CMMC Level 2+
    if sensitivity in ("ENHANCED", "CONTROLLED"):
        if inp.entity_foreign_ownership_pct > 0.0:
            if inp.entity_foci_status == "MITIGATED":
                if sensitivity == "CONTROLLED" and inp.entity_cmmc_level < 2:
                    return GateResult(
                        gate_id=2, gate_name="ITAR",
                        state=GateState.PENDING, severity="MEDIUM",
                        regulation="22 CFR Parts 120-130 / DFARS 252.204-7012 / CMMC 2.0",
                        details="FOCI mitigated but CMMC Level 2+ required for CUI handling.",
                        mitigation="Achieve CMMC Level 2 certification before CUI access.",
                        confidence=0.88,
                    )
                return GateResult(
                    gate_id=2, gate_name="ITAR",
                    state=GateState.PASS, severity="MEDIUM",
                    regulation="22 CFR Parts 120-130 / 32 CFR Part 2004",
                    details="FOCI mitigated — entity may access ITAR items at this sensitivity.",
                    mitigation="N/A", confidence=0.90,
                )
            return GateResult(
                gate_id=2, gate_name="ITAR",
                state=GateState.PENDING, severity="HIGH",
                regulation="22 CFR Parts 120-130 / 32 CFR Part 2004",
                details=f"Foreign ownership requires FOCI mitigation. Current status: {inp.entity_foci_status}.",
                mitigation="Initiate FOCI mitigation agreement with DSS (SSA, SCA, Proxy, or Voting Trust).",
                confidence=0.88,
            )

    # No foreign ownership, or UNCLASSIFIED/COMMERCIAL with clean ownership
    return GateResult(
        gate_id=2, gate_name="ITAR",
        state=GateState.PASS, severity="HIGH",
        regulation="22 CFR Parts 120-130",
        details="Entity meets ITAR access requirements for this program tier and sensitivity.",
        mitigation="N/A", confidence=0.90,
    )


# ── Gate 3: EAR ──────────────────────────────────────────────────────────────

def evaluate_ear(inp: EARInput) -> GateResult:
    """EAR compliance for dual-use items on the Commerce Control List."""
    if not inp.item_ear_ccl_category:
        return GateResult(
            gate_id=3, gate_name="EAR",
            state=GateState.SKIP, severity="MEDIUM",
            regulation="15 CFR Parts 730-774 (EAR)",
            details="Item is not EAR-controlled — gate not applicable.",
            mitigation="N/A", confidence=0.90,
        )

    pct = inp.entity_foreign_origin_content_pct

    # De minimis rule: <25% foreign content may be treated as US-origin
    if pct < 0.25:
        if inp.entity_has_export_control_procedures:
            return GateResult(
                gate_id=3, gate_name="EAR",
                state=GateState.PASS, severity="MEDIUM",
                regulation="15 CFR Part 734.4 (De Minimis Rule)",
                details=f"Foreign content ({pct * 100:.0f}%) below de minimis threshold. Export control procedures verified.",
                mitigation="N/A", confidence=0.88,
            )
        return GateResult(
            gate_id=3, gate_name="EAR",
            state=GateState.PENDING, severity="MEDIUM",
            regulation="15 CFR Parts 730-774",
            details=f"Foreign content ({pct * 100:.0f}%) below de minimis threshold but export control procedures not documented.",
            mitigation="Document export control procedures and provide to contracting officer.",
            confidence=0.85,
        )

    # ≥25% foreign content: requires export authorization
    if inp.entity_has_export_control_document_package:
        if inp.entity_export_control_deemed_export_training_current:
            return GateResult(
                gate_id=3, gate_name="EAR",
                state=GateState.PASS, severity="MEDIUM",
                regulation="15 CFR Parts 730-774",
                details=f"Foreign content ({pct * 100:.0f}%) ≥ 25% — export control package complete, training current.",
                mitigation="N/A", confidence=0.88,
            )
        return GateResult(
            gate_id=3, gate_name="EAR",
            state=GateState.PENDING, severity="MEDIUM",
            regulation="15 CFR Part 734.13 (Deemed Export)",
            details="Export control documents complete but deemed export training not current.",
            mitigation="Complete deemed export training for all foreign nationals with access to controlled technology.",
            confidence=0.85,
        )

    return GateResult(
        gate_id=3, gate_name="EAR",
        state=GateState.PENDING, severity="MEDIUM",
        regulation="15 CFR Parts 730-774",
        details=f"Foreign content ({pct * 100:.0f}%) requires export control documentation package.",
        mitigation="Submit export control documentation package including export license or license exception justification.",
        confidence=0.85,
    )


# ── Gate 4: DFARS Specialty Metals ───────────────────────────────────────────

def evaluate_specialty_metals(inp: SpecialtyMetalsInput) -> GateResult:
    """DFARS 252.225-7009: Specialty metals must originate from US or qualifying countries."""
    if not inp.item_contains_specialty_metals:
        return GateResult(
            gate_id=4, gate_name="DFARS Specialty Metals",
            state=GateState.SKIP, severity="MEDIUM",
            regulation="DFARS 252.225-7009 / 10 USC §4862",
            details="Item does not contain specialty metals — gate not applicable.",
            mitigation="N/A", confidence=0.90,
        )

    country = inp.entity_melting_location_country.upper()

    # Tier 3 (raw materials): may be exempt with certification
    if inp.supply_chain_tier == 3:
        if inp.entity_has_specialty_metals_certification:
            return GateResult(
                gate_id=4, gate_name="DFARS Specialty Metals",
                state=GateState.PASS, severity="MEDIUM",
                regulation="DFARS 252.225-7009",
                details="Tier 3 materials supplier with specialty metals origin certification.",
                mitigation="N/A", confidence=0.88,
            )
        return GateResult(
            gate_id=4, gate_name="DFARS Specialty Metals",
            state=GateState.PENDING, severity="MEDIUM",
            regulation="DFARS 252.225-7009",
            details="Tier 3 supplier — specialty metals certification required.",
            mitigation="Obtain and maintain specialty metals origin certification per DFARS 252.225-7009(b).",
            confidence=0.85,
        )

    if country in SPECIALTY_METALS_QUALIFYING_COUNTRIES:
        return GateResult(
            gate_id=4, gate_name="DFARS Specialty Metals",
            state=GateState.PASS, severity="MEDIUM",
            regulation="DFARS 252.225-7009",
            details=f"Specialty metals melted/remelted in qualifying country ({country}).",
            mitigation="N/A", confidence=0.92,
        )

    return GateResult(
        gate_id=4, gate_name="DFARS Specialty Metals",
        state=GateState.FAIL, severity="HIGH",
        regulation="DFARS 252.225-7009 / 10 USC §4862",
        details=(
            f"Specialty metals ({', '.join(inp.metals_present) or 'present'}) "
            f"melted/remelted in non-qualifying country ({country}). "
            "DFARS 252.225-7009 requires US or qualifying country origin."
        ),
        mitigation="Qualify alternate supplier in US or qualifying country, or obtain a non-availability determination.",
        confidence=0.92,
    )


# ── Gate 5: DFARS CDI ─────────────────────────────────────────────────────────

def evaluate_cdi(inp: CDIInput) -> GateResult:
    """DFARS 252.204-7012: Covered Defense Information / cyber incident reporting requirements."""
    if not inp.item_involves_covered_defense_info:
        return GateResult(
            gate_id=5, gate_name="DFARS CDI",
            state=GateState.SKIP, severity="HIGH",
            regulation="DFARS 252.204-7012",
            details="Contract does not involve covered defense information — gate not applicable.",
            mitigation="N/A", confidence=0.88,
        )

    requirements = {
        "Cloud service DoD authorization (FedRAMP Moderate+)": inp.entity_has_cloud_service_dod_authorization,
        "Cyber incident reporting capability (72-hour)": inp.entity_has_incident_reporting_capability,
        "Malicious software procedures": inp.entity_has_malicious_software_procedures,
        "Media sanitization procedures": inp.entity_has_media_sanitization_procedures,
        "Image preservation for 60 days post-incident": inp.entity_preserves_images_for_60_days,
    }
    missing = [k for k, v in requirements.items() if not v]

    if not missing:
        return GateResult(
            gate_id=5, gate_name="DFARS CDI",
            state=GateState.PASS, severity="HIGH",
            regulation="DFARS 252.204-7012",
            details="All CDI handling requirements met.",
            mitigation="N/A", confidence=0.92,
        )

    return GateResult(
        gate_id=5, gate_name="DFARS CDI",
        state=GateState.PENDING, severity="HIGH",
        regulation="DFARS 252.204-7012",
        details=f"CDI requirements not fully met. Missing: {'; '.join(missing)}.",
        mitigation=f"Implement missing CDI controls before contract performance: {'; '.join(missing)}.",
        confidence=0.88,
    )


# ── Gate 6: CMMC 2.0 ──────────────────────────────────────────────────────────

def evaluate_cmmc(inp: CMMCInput) -> GateResult:
    """CMMC 2.0: Cybersecurity Maturity Model Certification requirements."""
    if not inp.handles_cui or inp.required_cmmc_level == 0:
        return GateResult(
            gate_id=6, gate_name="CMMC 2.0",
            state=GateState.SKIP, severity="HIGH",
            regulation="32 CFR Part 170 (CMMC 2.0) / DFARS 252.204-7021",
            details="Contract does not require CMMC certification.",
            mitigation="N/A", confidence=0.88,
        )

    if inp.current_cmmc_level >= inp.required_cmmc_level:
        return GateResult(
            gate_id=6, gate_name="CMMC 2.0",
            state=GateState.PASS, severity="HIGH",
            regulation="32 CFR Part 170 / DFARS 252.204-7021",
            details=f"CMMC Level {inp.current_cmmc_level} certified — meets Level {inp.required_cmmc_level} requirement.",
            mitigation="N/A", confidence=0.95,
        )

    gap = inp.required_cmmc_level - inp.current_cmmc_level
    has_poam = inp.entity_has_active_poam

    if gap == 1 and has_poam:
        return GateResult(
            gate_id=6, gate_name="CMMC 2.0",
            state=GateState.PENDING, severity="HIGH",
            regulation="32 CFR Part 170 / DFARS 252.204-7021",
            details=(
                f"Entity is CMMC Level {inp.current_cmmc_level}, requires Level {inp.required_cmmc_level}. "
                "One level below with active POA&M — remediation plausible."
            ),
            mitigation=f"Achieve CMMC Level {inp.required_cmmc_level} certification via C3PAO assessment within 180 days.",
            confidence=0.88,
        )

    return GateResult(
        gate_id=6, gate_name="CMMC 2.0",
        state=GateState.FAIL if gap >= 2 else GateState.PENDING,
        severity="CRITICAL" if gap >= 2 else "HIGH",
        regulation="32 CFR Part 170 / DFARS 252.204-7021",
        details=(
            f"Entity is CMMC Level {inp.current_cmmc_level}, requires Level {inp.required_cmmc_level} "
            f"({gap} level{'s' if gap > 1 else ''} below requirement). "
            f"POA&M {'not active' if not has_poam else 'active but gap too large'}."
        ),
        mitigation=f"Achieve CMMC Level {inp.required_cmmc_level} via C3PAO. Gap of {gap} levels requires significant remediation.",
        confidence=0.92,
    )


# ── Gate 7: FOCI ──────────────────────────────────────────────────────────────

def evaluate_foci(inp: FOCIInput) -> GateResult:
    """FOCI: Foreign Ownership, Control, or Influence — 32 CFR Part 2004."""
    if inp.entity_foreign_ownership_pct == 0.0 and inp.entity_foreign_control_pct == 0.0:
        return GateResult(
            gate_id=7, gate_name="FOCI",
            state=GateState.PASS, severity="HIGH",
            regulation="32 CFR Part 2004 / NISPOM Rule",
            details="No foreign ownership or control — FOCI not applicable.",
            mitigation="N/A", confidence=0.90,
        )

    sensitivity = inp.sensitivity
    pct = max(inp.entity_foreign_ownership_pct, inp.entity_foreign_control_pct)

    # SAP/SCI: any foreign interest is disqualifying
    if sensitivity in ("CRITICAL_SAP", "CRITICAL_SCI"):
        return GateResult(
            gate_id=7, gate_name="FOCI",
            state=GateState.FAIL, severity="CRITICAL",
            regulation="32 CFR Part 2004 / SAP Program Security Instructions",
            details=(
                f"SAP/SCI program — foreign interest ({pct * 100:.0f}%) is categorically "
                "disqualifying. Entity cannot hold facility clearance for SAP/SCI programs."
            ),
            mitigation="NONE for SAP/SCI — entity must divest foreign ownership/control.",
            confidence=0.99,
        )

    # Mitigated FOCI
    if inp.entity_foci_mitigation_status == "MITIGATED" and inp.dss_approval_obtained:
        return GateResult(
            gate_id=7, gate_name="FOCI",
            state=GateState.PASS, severity="HIGH",
            regulation="32 CFR Part 2004",
            details=f"FOCI mitigated via {inp.foci_mitigation_type or 'approved instrument'} — DSS approval obtained.",
            mitigation="N/A", confidence=0.92,
        )

    if inp.entity_foci_mitigation_status in ("MITIGATED", "IN_PROGRESS"):
        return GateResult(
            gate_id=7, gate_name="FOCI",
            state=GateState.PENDING, severity="HIGH",
            regulation="32 CFR Part 2004",
            details=(
                f"FOCI mitigation status: {inp.entity_foci_mitigation_status}. "
                f"Foreign interest: {pct * 100:.0f}%. DSS approval {'not yet' if not inp.dss_approval_obtained else ''} obtained."
            ),
            mitigation="Obtain DSS approval of FOCI mitigation instrument (SSA, SCA, Voting Trust, or Proxy Agreement).",
            confidence=0.88,
        )

    # Unmitigated FOCI
    country = inp.foreign_controlling_country.upper()
    severity = "CRITICAL" if country in {"CN", "RU", "IR", "KP"} else "HIGH"
    return GateResult(
        gate_id=7, gate_name="FOCI",
        state=GateState.FAIL if severity == "CRITICAL" else GateState.PENDING,
        severity=severity,
        regulation="32 CFR Part 2004 / NISPOM Rule",
        details=(
            f"Unmitigated FOCI — {pct * 100:.0f}% foreign interest from {country}. "
            f"Entity {'cannot hold' if severity == 'CRITICAL' else 'requires mitigation for'} facility clearance."
        ),
        mitigation="Initiate FOCI mitigation agreement with DSS. Adversary-nation FOCI may be unmitigable.",
        confidence=0.90,
    )


# ── Gate 8: NDAA 1260H CMC ────────────────────────────────────────────────────

def evaluate_ndaa_1260h(inp: NDAA1260HInput) -> GateResult:
    """NDAA FY2021 Section 1260H: Chinese Military Companies prohibitions."""
    all_names = [inp.entity_name] + inp.parent_companies + inp.subsidiaries + inp.aliases

    for name in all_names:
        matched, key = _matches_list(name, NDAA_1260H_CMC)
        if matched:
            return GateResult(
                gate_id=8, gate_name="NDAA 1260H CMC",
                state=GateState.FAIL, severity="CRITICAL",
                regulation="NDAA FY2021 Section 1260H / EO 13959 (as amended)",
                details=(
                    f"Entity '{name}' is identified as a Chinese Military Company (CMC) "
                    f"under NDAA Section 1260H (matches '{key}'). "
                    "DoD investment and procurement restrictions apply per EO 13959."
                ),
                mitigation="NONE — CMC designation is an absolute procurement restriction.",
                confidence=0.99,
            )

    # Also check country-based heuristic for PLA-linked entities
    if inp.entity_country.upper() == "CN" and any(
        term in _normalize(inp.entity_name)
        for term in ["MILITARY", "DEFENSE", "ORDNANCE", "ROCKET FORCE", "NUCLEAR", "NAVY", "ARMY", "AIR FORCE"]
    ):
        return GateResult(
            gate_id=8, gate_name="NDAA 1260H CMC",
            state=GateState.PENDING, severity="HIGH",
            regulation="NDAA FY2021 Section 1260H",
            details=(
                "Chinese entity with military-adjacent naming. May be subject to NDAA 1260H. "
                "Manual review against current USD(P) CMC list required."
            ),
            mitigation="Conduct manual review against current USD(P) CMC designation list before contract award.",
            confidence=0.70,
        )

    return GateResult(
        gate_id=8, gate_name="NDAA 1260H CMC",
        state=GateState.PASS, severity="CRITICAL",
        regulation="NDAA FY2021 Section 1260H",
        details="Entity does not appear on current NDAA 1260H Chinese Military Companies list.",
        mitigation="N/A", confidence=0.90,
    )


# ── Gate 9: CFIUS ─────────────────────────────────────────────────────────────

def evaluate_cfius(inp: CFIUSInput) -> GateResult:
    """CFIUS: Foreign investment review for TID businesses."""
    if not inp.transaction_involves_foreign_acquirer:
        return GateResult(
            gate_id=9, gate_name="CFIUS",
            state=GateState.SKIP, severity="HIGH",
            regulation="50 USC §4565 (FIRRMA) / 31 CFR Parts 800-802",
            details="Transaction does not involve a foreign acquirer — CFIUS not applicable.",
            mitigation="N/A", confidence=0.88,
        )

    country = inp.foreign_acquirer_country.upper()
    is_covered_country = country in CFIUS_COVERED_COUNTRIES
    is_tid = (
        inp.business_involves_critical_technology or
        inp.business_involves_critical_infrastructure or
        inp.business_involves_sensitive_personal_data or
        inp.entity_is_tic_business
    )

    # Mandatory filing situations
    if inp.transaction_is_mandatory_filing or (is_covered_country and is_tid):
        if inp.cfius_clearance_obtained:
            return GateResult(
                gate_id=9, gate_name="CFIUS",
                state=GateState.PASS, severity="HIGH",
                regulation="50 USC §4565 / FIRRMA / 31 CFR Part 800",
                details="CFIUS clearance obtained for this transaction.",
                mitigation="N/A", confidence=0.95,
            )
        if inp.cfius_notice_filed:
            return GateResult(
                gate_id=9, gate_name="CFIUS",
                state=GateState.PENDING, severity="HIGH",
                regulation="50 USC §4565 / FIRRMA",
                details=f"Mandatory CFIUS filing submitted — review in progress. Foreign acquirer: {country}.",
                mitigation="Await CFIUS clearance before closing transaction.",
                confidence=0.88,
            )
        return GateResult(
            gate_id=9, gate_name="CFIUS",
            state=GateState.FAIL, severity="CRITICAL",
            regulation="50 USC §4565 / FIRRMA / 31 CFR Part 800.401",
            details=(
                f"Mandatory CFIUS filing required but not filed. Foreign acquirer from "
                f"{'covered country ' if is_covered_country else ''}{country} in TID business sector."
            ),
            mitigation="File mandatory CFIUS declaration within 30 days of closing agreement. Non-filing carries civil penalties.",
            confidence=0.92,
        )

    # Voluntary but recommended
    if is_tid and not inp.cfius_clearance_obtained:
        return GateResult(
            gate_id=9, gate_name="CFIUS",
            state=GateState.PENDING, severity="MEDIUM",
            regulation="50 USC §4565 / FIRRMA",
            details=f"Transaction involves TID business — voluntary CFIUS notice recommended. Foreign acquirer: {country}.",
            mitigation="Consider voluntary CFIUS notice to obtain safe harbor and avoid post-closing review.",
            confidence=0.80,
        )

    return GateResult(
        gate_id=9, gate_name="CFIUS",
        state=GateState.PASS, severity="MEDIUM",
        regulation="50 USC §4565 / FIRRMA",
        details="Transaction does not trigger mandatory CFIUS filing.",
        mitigation="N/A", confidence=0.85,
    )


# ── Gate 10: Berry Amendment ──────────────────────────────────────────────────

def evaluate_berry_amendment(inp: BerryAmendmentInput) -> GateResult:
    """Berry Amendment 10 USC §4862: Domestic sourcing for covered item categories."""
    if not inp.applies_to_contract or inp.item_category not in BERRY_COVERED_CATEGORIES:
        return GateResult(
            gate_id=10, gate_name="Berry Amendment",
            state=GateState.SKIP, severity="MEDIUM",
            regulation="10 USC §4862 (Berry Amendment) / DFARS 252.225-7012",
            details="Item category is not covered by Berry Amendment or contract does not apply.",
            mitigation="N/A", confidence=0.88,
        )

    origin = inp.item_origin_country.upper()
    mfg = inp.entity_manufacturing_country.upper()

    if origin == "US" and mfg == "US":
        return GateResult(
            gate_id=10, gate_name="Berry Amendment",
            state=GateState.PASS, severity="MEDIUM",
            regulation="10 USC §4862 / DFARS 252.225-7012",
            details="Berry Amendment compliance confirmed — item origin and manufacturing: US.",
            mitigation="N/A", confidence=0.95,
        )

    if inp.entity_has_domestic_nonavailability_determination:
        return GateResult(
            gate_id=10, gate_name="Berry Amendment",
            state=GateState.PASS, severity="MEDIUM",
            regulation="10 USC §4862(c) / Non-availability exception",
            details="Non-availability determination obtained — Berry Amendment exception applies.",
            mitigation="N/A", confidence=0.92,
        )

    return GateResult(
        gate_id=10, gate_name="Berry Amendment",
        state=GateState.FAIL, severity="HIGH",
        regulation="10 USC §4862 / DFARS 252.225-7012",
        details=(
            f"Berry Amendment violation — item category '{inp.item_category}' "
            f"originates/manufactures in {origin}/{mfg}. US domestic source required."
        ),
        mitigation="Source from US manufacturer, or obtain non-availability determination from DCSA.",
        confidence=0.92,
    )


# ── Gate 11: Deemed Export Risk ─────────────────────────────────────────────

def evaluate_deemed_export_risk(inp: DeemedExportGateInput) -> GateResult:
    """
    Gate 11: Deemed Export Risk (22 CFR 120.17)
    Assess risk of deemed export via foreign national access to ITAR technical data.
    """
    if not inp.foreign_nationals:
        return GateResult(
            gate_id=11, gate_name="Deemed Export Risk",
            state=GateState.SKIP, severity="MEDIUM",
            regulation="22 CFR 120.17",
            details="No foreign national data provided — deemed export not applicable.",
            mitigation="N/A", confidence=0.95,
        )

    # Call itar_module function
    risk_assessment = assess_deemed_export_risk(
        foreign_nationals=inp.foreign_nationals,
        tcp_status=inp.tcp_status,
        usml_category=inp.usml_category,
        facility_clearance=inp.facility_clearance,
    )

    risk_score = risk_assessment.risk_score

    if risk_score >= 0.70:
        return GateResult(
            gate_id=11, gate_name="Deemed Export Risk",
            state=GateState.FAIL, severity="CRITICAL",
            regulation="22 CFR 120.15-120.17",
            details=(
                f"High deemed export risk detected (score: {risk_score:.2f}). "
                f"Foreign nationals have access to ITAR technical data without valid TCP. "
                f"Foreign national count: {risk_assessment.foreign_national_count}, "
                f"Nationalities: {', '.join(risk_assessment.nationalities)}"
            ),
            mitigation="Implement Technology Control Plan (TCP) per 22 CFR 120.37, restrict foreign national access, or obtain facility security clearance.",
            confidence=0.90,
        )

    if 0.30 <= risk_score < 0.70:
        return GateResult(
            gate_id=11, gate_name="Deemed Export Risk",
            state=GateState.PENDING, severity="HIGH",
            regulation="22 CFR 120.17 / 22 CFR 120.37",
            details=(
                f"Moderate deemed export risk (score: {risk_score:.2f}). "
                f"TCP status: {inp.tcp_status}. Foreign nationals present: {risk_assessment.foreign_national_count}."
            ),
            mitigation="Finalize TCP implementation or restrict technical data access to foreign nationals.",
            confidence=0.85,
        )

    return GateResult(
        gate_id=11, gate_name="Deemed Export Risk",
        state=GateState.PASS, severity="MEDIUM",
        regulation="22 CFR 120.17",
        details=f"Deemed export risk acceptable (score: {risk_score:.2f}). TCP status: {inp.tcp_status}.",
        mitigation="N/A", confidence=0.90,
    )


# ── Gate 12: End-Use Red Flags ──────────────────────────────────────────────

def evaluate_red_flags(inp: RedFlagGateInput) -> GateResult:
    """
    Gate 12: End-Use Red Flags (BIS/DDTC Guidance)
    Check transaction for diversion risk indicators.
    """
    if not inp.transaction:
        return GateResult(
            gate_id=12, gate_name="End-Use Red Flags",
            state=GateState.SKIP, severity="MEDIUM",
            regulation="BIS/DDTC Guidance",
            details="No transaction data provided — red flag assessment not applicable.",
            mitigation="N/A", confidence=0.95,
        )

    # Call itar_module function
    flag_assessment = check_red_flags(
        transaction=inp.transaction,
        vendor_country=inp.vendor_country,
        end_user_country=inp.end_user_country,
        usml_category=inp.usml_category,
    )

    score = flag_assessment.score

    if score >= 0.60:
        flag_list = ", ".join(flag_assessment.flags_triggered[:5])
        return GateResult(
            gate_id=12, gate_name="End-Use Red Flags",
            state=GateState.FAIL, severity="HIGH",
            regulation="BIS Red Flag Indicators (15 CFR 730) / DDTC Enforcement",
            details=(
                f"Multiple red flags triggered (score: {score:.2f}). "
                f"Flags: {flag_list}{'...' if len(flag_assessment.flags_triggered) > 5 else ''}. "
                f"Transaction shows signs of diversion risk."
            ),
            mitigation="Obtain end-use statement, verify customer identity, decline transaction, or request interagency review.",
            confidence=0.88,
        )

    if 0.25 <= score < 0.60:
        flag_list = ", ".join(flag_assessment.flags_triggered[:3])
        return GateResult(
            gate_id=12, gate_name="End-Use Red Flags",
            state=GateState.PENDING, severity="MEDIUM",
            regulation="BIS Red Flag Indicators / DDTC Guidance",
            details=(
                f"Some red flags present (score: {score:.2f}). "
                f"Flags: {flag_list}. "
                f"Requires review and customer verification."
            ),
            mitigation="Request additional documentation, end-use certification, or customer verification before proceeding.",
            confidence=0.82,
        )

    return GateResult(
        gate_id=12, gate_name="End-Use Red Flags",
        state=GateState.PASS, severity="LOW",
        regulation="BIS Red Flag Indicators",
        details=f"Red flag risk acceptable (score: {score:.2f}).",
        mitigation="N/A", confidence=0.90,
    )


# ── Gate 13: USML Category Control ──────────────────────────────────────────

def evaluate_usml_control(inp: USMLControlGateInput) -> GateResult:
    """
    Gate 13: USML Category Control (22 CFR 121)
    Verify USML category is not exported to prohibited or elevated-scrutiny countries.
    """
    if inp.usml_category == 0:
        return GateResult(
            gate_id=13, gate_name="USML Category Control",
            state=GateState.SKIP, severity="MEDIUM",
            regulation="22 CFR 121",
            details="USML category not specified (0) — category control not applicable.",
            mitigation="N/A", confidence=0.95,
        )

    category = USML_CATEGORIES.get(inp.usml_category)
    if not category:
        return GateResult(
            gate_id=13, gate_name="USML Category Control",
            state=GateState.SKIP, severity="LOW",
            regulation="22 CFR 121",
            details=f"USML category {inp.usml_category} not recognized.",
            mitigation="N/A", confidence=0.90,
        )

    vendor_country = inp.vendor_country.upper()

    # CRITICAL + PROHIBITED = automatic FAIL
    if category.risk_level == "CRITICAL" and vendor_country in inp.itar_prohibited_countries:
        return GateResult(
            gate_id=13, gate_name="USML Category Control",
            state=GateState.FAIL, severity="CRITICAL",
            regulation="22 CFR 121 / State Department ITAR Prohibition",
            details=(
                f"USML Category {inp.usml_category} ({category.name}) is CRITICAL "
                f"and cannot be exported to {vendor_country} (prohibited country). "
                f"No licenses available."
            ),
            mitigation="Redirect export to approved destination or seek Presidential determination.",
            confidence=0.98,
        )

    # HIGH + ELEVATED SCRUTINY = PENDING
    if category.risk_level == "HIGH" and vendor_country in inp.itar_elevated_scrutiny_countries:
        return GateResult(
            gate_id=13, gate_name="USML Category Control",
            state=GateState.PENDING, severity="HIGH",
            regulation="22 CFR 121 / Elevated Scrutiny Policy",
            details=(
                f"USML Category {inp.usml_category} ({category.name}) is HIGH risk "
                f"and vendor country {vendor_country} is subject to elevated scrutiny. "
                f"License required; approval not guaranteed."
            ),
            mitigation="Apply for ITAR license, prepare detailed end-use statement, expect extended review timeline.",
            confidence=0.90,
        )

    # All other valid combinations PASS
    return GateResult(
        gate_id=13, gate_name="USML Category Control",
        state=GateState.PASS, severity="MEDIUM",
        regulation="22 CFR 121",
        details=(
            f"USML Category {inp.usml_category} ({category.name}) "
            f"export to {vendor_country} is permitted under current controls."
        ),
        mitigation="N/A", confidence=0.92,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GATE PROXIMITY SCORE
# ─────────────────────────────────────────────────────────────────────────────

# Gate severity weights for proximity score
_GATE_SEVERITY_WEIGHTS = {
    "CRITICAL": 1.0,
    "HIGH": 0.8,
    "MEDIUM": 0.5,
    "LOW": 0.2,
}


def _compute_gate_proximity(
    failed: list[GateResult],
    pending: list[GateResult],
) -> float:
    """
    Compute a 0-1 score reflecting how close entity is to regulatory failure.
    Used as the 'regulatory_gate_proximity' input to Layer 2.

    Scoring:
      FAIL gates:    contribute full weight (they already failed)
      PENDING gates: contribute 50% of weight (approaching failure)
      PASS gates:    contribute 0
    """
    if not failed and not pending:
        return 0.0

    # Max possible weighted sum (all 10 gates critical)
    max_weight = 10.0 * _GATE_SEVERITY_WEIGHTS["CRITICAL"]
    score = 0.0

    for g in failed:
        score += _GATE_SEVERITY_WEIGHTS.get(g.severity, 0.5)
    for g in pending:
        score += _GATE_SEVERITY_WEIGHTS.get(g.severity, 0.5) * 0.5

    return min(1.0, score / max_weight)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN EVALUATION ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_regulatory_gates(inp: RegulatoryGateInput) -> RegulatoryAssessment:
    """
    Evaluate selected regulatory gates and return a RegulatoryAssessment.

    Evaluates gates 1-10 (fixed) plus optional gates 11-13 (ITAR-specific).
    Gate selection is controlled by inp.enabled_gates list.

    Args:
        inp: RegulatoryGateInput with all gate-specific sub-inputs and enabled_gates list.

    Returns:
        RegulatoryAssessment with:
          - status: COMPLIANT / NON_COMPLIANT / REQUIRES_REVIEW
          - gate_proximity_score: 0-1 for Layer 2 input
          - is_dod_eligible: True if entity CAN do DoD work (no hard FAILs)
          - is_dod_qualified: True if entity is ready now (all PASS or SKIP)
    """
    # Ensure section_889 and ndaa_1260h have entity_name set
    if not inp.section_889.entity_name:
        inp.section_889 = Section889Input(
            entity_name=inp.entity_name,
            parent_companies=inp.section_889.parent_companies,
            subsidiaries=inp.section_889.subsidiaries,
            aliases=inp.section_889.aliases,
        )
    if not inp.ndaa_1260h.entity_name:
        inp.ndaa_1260h = NDAA1260HInput(
            entity_name=inp.entity_name,
            parent_companies=inp.ndaa_1260h.parent_companies,
            subsidiaries=inp.ndaa_1260h.subsidiaries,
            aliases=inp.ndaa_1260h.aliases,
            entity_country=inp.entity_country,
        )

    # Set sensitivity and tier on sub-inputs that need them
    inp.itar.sensitivity = inp.sensitivity
    inp.itar.supply_chain_tier = inp.supply_chain_tier
    inp.cmmc.sensitivity = inp.sensitivity
    inp.foci.sensitivity = inp.sensitivity
    inp.specialty_metals.supply_chain_tier = inp.supply_chain_tier

    # Determine which gates to run based on enabled_gates
    enabled = set(inp.enabled_gates) if inp.enabled_gates else set(range(1, 11))

    # Run gates 1-10 (fixed gates) based on enabled list
    results = []
    if 1 in enabled:
        results.append(evaluate_section_889(inp.section_889))
    if 2 in enabled:
        results.append(evaluate_itar(inp.itar))
    if 3 in enabled:
        results.append(evaluate_ear(inp.ear))
    if 4 in enabled:
        results.append(evaluate_specialty_metals(inp.specialty_metals))
    if 5 in enabled:
        results.append(evaluate_cdi(inp.cdi))
    if 6 in enabled:
        results.append(evaluate_cmmc(inp.cmmc))
    if 7 in enabled:
        results.append(evaluate_foci(inp.foci))
    if 8 in enabled:
        results.append(evaluate_ndaa_1260h(inp.ndaa_1260h))
    if 9 in enabled:
        results.append(evaluate_cfius(inp.cfius))
    if 10 in enabled:
        results.append(evaluate_berry_amendment(inp.berry))

    # Run optional gates 11-13 (ITAR-specific) if enabled
    if 11 in enabled:
        results.append(evaluate_deemed_export_risk(inp.deemed_export))
    if 12 in enabled:
        results.append(evaluate_red_flags(inp.red_flag))
    if 13 in enabled:
        results.append(evaluate_usml_control(inp.usml_control))

    passed   = [r for r in results if r.state == GateState.PASS]
    failed   = [r for r in results if r.state == GateState.FAIL]
    pending  = [r for r in results if r.state == GateState.PENDING]
    skipped  = [r for r in results if r.state == GateState.SKIP]

    # Determine overall status
    if failed:
        status = RegulatoryStatus.NON_COMPLIANT
    elif pending:
        status = RegulatoryStatus.REQUIRES_REVIEW
    else:
        status = RegulatoryStatus.COMPLIANT

    # Gate proximity score for Layer 2
    proximity = _compute_gate_proximity(failed, pending)

    # DoD eligibility
    is_dod_eligible  = len(failed) == 0
    is_dod_qualified = len(failed) == 0 and len(pending) == 0

    return RegulatoryAssessment(
        status=status,
        passed_gates=passed,
        failed_gates=failed,
        pending_gates=pending,
        skipped_gates=skipped,
        gate_proximity_score=round(proximity, 4),
        is_dod_eligible=is_dod_eligible,
        is_dod_qualified=is_dod_qualified,
        entity_name=inp.entity_name,
        sensitivity=inp.sensitivity,
        supply_chain_tier=inp.supply_chain_tier,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE: QUICK SCREEN (name-only, no deep gate inputs)
# ─────────────────────────────────────────────────────────────────────────────

def quick_screen(
    entity_name: str,
    parent_companies: list[str] | None = None,
    subsidiaries: list[str] | None = None,
    aliases: list[str] | None = None,
    entity_country: str = "",
) -> dict:
    """
    Fast name-based check against Section 889 and NDAA 1260H lists only.
    Returns a dict with matched_889, matched_cmc, details.
    Used for quick pre-filter before full gate evaluation.
    """
    all_names = [entity_name] + (parent_companies or []) + (subsidiaries or []) + (aliases or [])

    matched_889, key_889 = False, ""
    matched_cmc, key_cmc = False, ""

    for name in all_names:
        if not matched_889:
            matched_889, key_889 = _matches_list(name, SECTION_889_PROHIBITED)
        if not matched_cmc:
            matched_cmc, key_cmc = _matches_list(name, NDAA_1260H_CMC)

    return {
        "matched_section_889": matched_889,
        "section_889_key": key_889,
        "matched_cmc": matched_cmc,
        "cmc_key": key_cmc,
        "is_disqualified": matched_889 or matched_cmc,
    }
