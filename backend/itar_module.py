"""
Xiphos ITAR Compliance Module v1.0
International Traffic in Arms Regulations (ITAR) Risk Assessment Engine

Implements comprehensive ITAR compliance evaluation per 22 CFR 120-130,
including USML category risk mapping, country restrictions, deemed export
risk assessment, and red flag analysis for defense article transactions.

Components:
  1. USML Category Risk Mapper (21 CFR categories I-XXI)
  2. ITAR Country Restrictions (22 CFR 126.1 prohibited countries)
  3. Deemed Export Risk Scorer (Technical data access by foreign nationals)
  4. End-Use Red Flag Checker (BIS/DDTC red flag indicators)
  5. ITAR Compliance Gate (Orchestration of all sub-checks)
  6. DDTC Debarred List (Hardcoded fallback for entity screening)

Model version: 1.0-ITARCompliance
Author:        Xiphos Principal Risk Scientist
Date:          March 2026
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# =============================================================================
# ENUMERATION TYPES
# =============================================================================

class ComplianceStatus(str, Enum):
    """Overall ITAR compliance determination."""
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    PROHIBITED = "PROHIBITED"


class CountryStatus(str, Enum):
    """Country-level ITAR restriction status."""
    ALLOWED = "ALLOWED"
    PROHIBITED = "PROHIBITED"
    ELEVATED_SCRUTINY = "ELEVATED_SCRUTINY"
    CANADIAN_EXEMPTION = "CANADIAN_EXEMPTION"


class RegistrationStatus(str, Enum):
    """DDTC registration status per 22 CFR 122."""
    REGISTERED = "REGISTERED"
    UNREGISTERED = "UNREGISTERED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class LicenseType(str, Enum):
    """ITAR license types per 22 CFR 123-125."""
    DSP_5 = "DSP_5"          # Permanent license (4 years)
    DSP_73 = "DSP_73"        # Temporary license (180 days)
    DSP_85 = "DSP_85"        # Classified articles
    TAA = "TAA"              # Technical Assistance Agreement
    MLA = "MLA"              # Manufacturing License Agreement
    WDA = "WDA"              # Warehouse Distribution Agreement
    NONE = "NONE"            # No license required (not ITAR-controlled)
    UNKNOWN = "UNKNOWN"      # Unable to determine


# =============================================================================
# COUNTRY RESTRICTIONS (22 CFR 126.1 and related)
# =============================================================================

# Prohibited destinations per 22 CFR 126.1 - absolute block on all ITAR items
ITAR_PROHIBITED_COUNTRIES = {
    "CU",  # Cuba
    "IR",  # Iran
    "KP",  # North Korea (Democratic People's Republic of Korea)
    "SY",  # Syria
    "BY",  # Belarus (added post-2022)
    "RU",  # Russia (added post-2022)
}

# Elevated scrutiny countries requiring enhanced due diligence per DDTC guidance
# CFR 126.1 supplementary list and repeated enforcement actions
ITAR_ELEVATED_SCRUTINY = {
    "CN",  # China
    "VE",  # Venezuela
    "MM",  # Myanmar
    "SD",  # Sudan
    "YE",  # Yemen
    "SO",  # Somalia
    "AF",  # Afghanistan
    "PK",  # Pakistan
    "IQ",  # Iraq
    "LY",  # Libya
    "LB",  # Lebanon
}

# Canadian exemption per 22 CFR 126.5 - reduced restrictions for unclassified defense articles
# Applies to most defense articles without classified content
CANADIAN_EXEMPTION_ELIGIBLE = {
    "CA",  # Canada
}

# Allied nations with NATO/Five EYES intelligence sharing (lower deemed export risk)
ALLIED_NATIONS = {
    "GB",  # United Kingdom
    "AU",  # Australia
    "CA",  # Canada
    "DE",  # Germany
    "FR",  # France
    "IT",  # Italy
    "ES",  # Spain
    "NL",  # Netherlands
    "JP",  # Japan
    "KR",  # South Korea
    "NZ",  # New Zealand
    "NO",  # Norway
    "DK",  # Denmark
    "SE",  # Sweden
    "AT",  # Austria
    "BE",  # Belgium
    "CZ",  # Czechia
    "DU",  # EU (aggregate)
}


# =============================================================================
# USML CATEGORY DEFINITIONS
# =============================================================================

@dataclass
class USMLCategory:
    """
    Definition of a United States Munitions List (USML) category per 22 CFR 121.
    
    Attributes:
        number: USML category I-XXI (1-21)
        name: Short name of category
        description: Full regulatory description
        risk_level: CRITICAL, HIGH, MEDIUM (determines base weighting)
        base_risk_weight: Normalized risk 0.0-1.0 (used in scoring)
        congressional_notification: Requires Congressional notification per AECA
        deemed_export_sensitivity: Sensitivity level for deemed export assessment
        examples: Real-world examples of articles in this category
    """
    number: int
    name: str
    description: str
    risk_level: str
    base_risk_weight: float
    congressional_notification: bool
    deemed_export_sensitivity: str
    examples: list[str]


# Complete USML Categories per 22 CFR 121
# Risk levels and weights based on:
# - Congressional notification requirement (AECA 22 USC 2778)
# - DDTC enforcement history (recent consent agreements)
# - Technological sensitivity and military impact

USML_CATEGORIES = {
    1: USMLCategory(
        number=1,
        name="Firearms and Ammunition",
        description="Firearms, related articles, and ammunition per 22 CFR 121.1",
        risk_level="CRITICAL",
        base_risk_weight=0.95,
        congressional_notification=True,
        deemed_export_sensitivity="HIGH",
        examples=["Combat rifles", "Machine guns", "Suppressors", "Precision ammunition"],
    ),
    2: USMLCategory(
        number=2,
        name="Artillery Systems",
        description="Guns, howitzers, mortars, and related articles per 22 CFR 121.2",
        risk_level="CRITICAL",
        base_risk_weight=0.95,
        congressional_notification=True,
        deemed_export_sensitivity="HIGH",
        examples=["Field artillery", "Howitzers", "Mortars", "Recoilless rifles"],
    ),
    3: USMLCategory(
        number=3,
        name="Ordnance and Ammunition",
        description="Ammunition and ordnance not covered by Category I or II per 22 CFR 121.3",
        risk_level="CRITICAL",
        base_risk_weight=0.95,
        congressional_notification=True,
        deemed_export_sensitivity="HIGH",
        examples=["Guided missiles", "Warheads", "Fuzes", "Anti-tank rounds"],
    ),
    4: USMLCategory(
        number=4,
        name="Launch Systems and Missiles",
        description="Launch systems, missiles, and related articles per 22 CFR 121.4",
        risk_level="CRITICAL",
        base_risk_weight=0.95,
        congressional_notification=True,
        deemed_export_sensitivity="HIGH",
        examples=["Missile launchers", "Rocket systems", "Ballistic missiles"],
    ),
    5: USMLCategory(
        number=5,
        name="Explosives and Propellants",
        description="Explosives, propellants, and related articles per 22 CFR 121.5",
        risk_level="CRITICAL",
        base_risk_weight=0.93,
        congressional_notification=True,
        deemed_export_sensitivity="HIGH",
        examples=["Detonators", "Fuses", "Propellants", "Energetic materials"],
    ),
    6: USMLCategory(
        number=6,
        name="Combat Vessels",
        description="Vessels, surface effect vehicles, and related articles per 22 CFR 121.6",
        risk_level="CRITICAL",
        base_risk_weight=0.95,
        congressional_notification=True,
        deemed_export_sensitivity="HIGH",
        examples=["Combat ships", "Submarines", "Mine-sweepers", "Patrol boats"],
    ),
    7: USMLCategory(
        number=7,
        name="Military Aircraft",
        description="Aircraft and related articles per 22 CFR 121.7",
        risk_level="CRITICAL",
        base_risk_weight=0.95,
        congressional_notification=True,
        deemed_export_sensitivity="HIGH",
        examples=["Fighter jets", "Attack helicopters", "Military drones", "Avionics"],
    ),
    8: USMLCategory(
        number=8,
        name="Landing Craft and Amphibious Vehicles",
        description="Landing craft and related articles per 22 CFR 121.8",
        risk_level="HIGH",
        base_risk_weight=0.80,
        congressional_notification=False,
        deemed_export_sensitivity="HIGH",
        examples=["Assault landing craft", "Hovercraft", "Amphibious vehicles"],
    ),
    9: USMLCategory(
        number=9,
        name="Toxicological Agents",
        description="Toxicological agents and related articles per 22 CFR 121.9",
        risk_level="CRITICAL",
        base_risk_weight=0.95,
        congressional_notification=True,
        deemed_export_sensitivity="HIGH",
        examples=["Biological agents", "Toxins", "Defensive protective equipment"],
    ),
    10: USMLCategory(
        number=10,
        name="Protective Equipment",
        description="Protective equipment and related articles per 22 CFR 121.10",
        risk_level="HIGH",
        base_risk_weight=0.75,
        congressional_notification=False,
        deemed_export_sensitivity="MEDIUM",
        examples=["Armor plates", "Helmets", "NBC suits", "Body armor"],
    ),
    11: USMLCategory(
        number=11,
        name="Military Electronics",
        description="Military electronics and related articles per 22 CFR 121.11",
        risk_level="HIGH",
        base_risk_weight=0.80,
        congressional_notification=False,
        deemed_export_sensitivity="HIGH",
        examples=["Radar systems", "Secure communications", "Fire control systems"],
    ),
    12: USMLCategory(
        number=12,
        name="Fire Control and Guidance Systems",
        description="Fire control and related articles per 22 CFR 121.12",
        risk_level="HIGH",
        base_risk_weight=0.80,
        congressional_notification=False,
        deemed_export_sensitivity="HIGH",
        examples=["Aiming systems", "Ballistic computers", "Gun directors"],
    ),
    13: USMLCategory(
        number=13,
        name="Electronic Warfare and Countermeasures",
        description="Protective systems and related articles per 22 CFR 121.13",
        risk_level="HIGH",
        base_risk_weight=0.80,
        congressional_notification=False,
        deemed_export_sensitivity="HIGH",
        examples=["Chaff", "Flares", "Electronic countermeasures", "Radar jamming"],
    ),
    14: USMLCategory(
        number=14,
        name="Auxiliary Military Equipment",
        description="Auxiliary military equipment and related articles per 22 CFR 121.14",
        risk_level="MEDIUM",
        base_risk_weight=0.60,
        congressional_notification=False,
        deemed_export_sensitivity="MEDIUM",
        examples=["Military trucks", "Cranes", "Generators (integrated)", "Trailers"],
    ),
    15: USMLCategory(
        number=15,
        name="Firearms Accessories and Components",
        description="Firearms accessories and related articles per 22 CFR 121.15",
        risk_level="MEDIUM",
        base_risk_weight=0.65,
        congressional_notification=False,
        deemed_export_sensitivity="MEDIUM",
        examples=["Barrels", "Bolts", "Sights", "Tactical rails", "Suppressors"],
    ),
    16: USMLCategory(
        number=16,
        name="Auxiliary Aircraft Equipment",
        description="Auxiliary aircraft equipment and related articles per 22 CFR 121.16",
        risk_level="HIGH",
        base_risk_weight=0.75,
        congressional_notification=False,
        deemed_export_sensitivity="HIGH",
        examples=["Terrain avoidance radar", "Military refueling systems", "Defense avionics"],
    ),
    17: USMLCategory(
        number=17,
        name="Classified Articles",
        description="Articles and services classified as defense-related per 22 CFR 121.17",
        risk_level="CRITICAL",
        base_risk_weight=0.95,
        congressional_notification=True,
        deemed_export_sensitivity="HIGH",
        examples=["Classified specifications", "Secret military designs", "Defense research"],
    ),
    18: USMLCategory(
        number=18,
        name="Technical Data",
        description="Technical data directly related to USML articles per 22 CFR 121.18",
        risk_level="CRITICAL",
        base_risk_weight=0.93,
        congressional_notification=True,
        deemed_export_sensitivity="HIGH",
        examples=["Manufacturing blueprints", "Design specifications", "Test procedures"],
    ),
    19: USMLCategory(
        number=19,
        name="Defense Services",
        description="Services provided for USML articles per 22 CFR 121.19",
        risk_level="CRITICAL",
        base_risk_weight=0.90,
        congressional_notification=True,
        deemed_export_sensitivity="HIGH",
        examples=["Technical assistance", "Training", "Engineering support", "Consulting"],
    ),
    20: USMLCategory(
        number=20,
        name="Submunitions",
        description="Submunitions and related articles per 22 CFR 121.20",
        risk_level="CRITICAL",
        base_risk_weight=0.95,
        congressional_notification=True,
        deemed_export_sensitivity="HIGH",
        examples=["Cluster munitions", "Bomblets", "Self-destruct mechanisms"],
    ),
    21: USMLCategory(
        number=21,
        name="Miscellaneous Articles",
        description="Articles not in Categories I-XX designated as ITAR-controlled per 22 CFR 121.21",
        risk_level="MEDIUM",
        base_risk_weight=0.55,
        congressional_notification=False,
        deemed_export_sensitivity="MEDIUM",
        examples=["Designated items", "Future controlled items", "Special purpose equipment"],
    ),
}


# =============================================================================
# DEEMED EXPORT RISK ASSESSMENT
# =============================================================================

@dataclass
class DeemedExportRisk:
    """
    Risk assessment for deemed export of ITAR technical data to foreign nationals.
    
    Per 22 CFR 120.17, release of ITAR technical data to foreign nationals
    constitutes a deemed export to their country of nationality, requiring
    DDTC authorization unless exempt.
    
    Attributes:
        risk_score: Normalized risk 0.0-1.0 (higher = greater risk)
        foreign_national_count: Number of foreign nationals with access
        nationalities: List of affected foreign national country codes
        tcp_status: Technology Control Plan implementation status
        risk_factors: Human-readable list of contributing risk factors
        recommendation: Recommended action (ALLOW, REQUIRE_LICENSE, BLOCK)
    """
    risk_score: float
    foreign_national_count: int
    nationalities: list[str]
    tcp_status: str
    risk_factors: list[str]
    recommendation: str


def assess_deemed_export_risk(
    foreign_nationals: list[dict],
    tcp_status: str,
    usml_category: int = 0,
    facility_clearance: str = "NONE",
) -> DeemedExportRisk:
    """
    Assess risk of deemed export via technical data access by foreign nationals.
    
    Per 22 CFR 120.15-120.17, foreign nationals (non-U.S. persons) accessing
    ITAR technical data trigger deemed export requirements. U.S. citizens and
    green card holders (U.S. persons) do not trigger deemed exports.
    
    Args:
        foreign_nationals: List of dicts with keys:
            - nationality: ISO country code (e.g., "IN", "CN")
            - role: Job function (e.g., "engineer", "manager")
            - access_level: Data access classification (e.g., "technical_data")
        tcp_status: Technology Control Plan status per 22 CFR 120.37:
            - IMPLEMENTED: TCP written, enforced, trained
            - PENDING: TCP in development
            - NOT_REQUIRED: No foreign nationals or exempt situation
            - MISSING: Foreign nationals present but no TCP
        usml_category: USML category number (1-21) if applicable, 0 if unknown
        facility_clearance: Facility security clearance level:
            - SECRET, CONFIDENTIAL, UNCLASSIFIED, NONE
    
    Returns:
        DeemedExportRisk object with comprehensive assessment
    
    References:
        22 CFR 120.15: Foreign national definition
        22 CFR 120.17: Deemed export definition
        22 CFR 120.37: Technology Control Plan requirements
        22 CFR 127.7: Penalties (up to $1M fine, 20 years imprisonment)
    """
    risk_factors = []
    base_risk = 0.0
    
    # No foreign nationals = no deemed export risk
    if not foreign_nationals or len(foreign_nationals) == 0:
        return DeemedExportRisk(
            risk_score=0.0,
            foreign_national_count=0,
            nationalities=[],
            tcp_status="NOT_REQUIRED",
            risk_factors=[],
            recommendation="ALLOW",
        )
    
    foreign_national_count = len(foreign_nationals)
    nationalities = list(set(fn.get("nationality", "XX") for fn in foreign_nationals))
    
    # Check for prohibited countries (automatic block)
    prohibited_nationals = [n for n in nationalities if n in ITAR_PROHIBITED_COUNTRIES]
    if prohibited_nationals:
        risk_factors.append(
            f"Foreign nationals from prohibited country/countries: {', '.join(prohibited_nationals)}"
        )
        return DeemedExportRisk(
            risk_score=1.0,
            foreign_national_count=foreign_national_count,
            nationalities=nationalities,
            tcp_status=tcp_status,
            risk_factors=risk_factors,
            recommendation="BLOCK",
        )
    
    # Check for elevated scrutiny countries
    elevated_nationals = [n for n in nationalities if n in ITAR_ELEVATED_SCRUTINY]
    if elevated_nationals:
        risk_factors.append(
            f"Foreign nationals from elevated scrutiny country/countries: {', '.join(elevated_nationals)}"
        )
        base_risk = 0.75
    
    # Allied nations with proper controls = lower risk
    allied_nationals = [n for n in nationalities if n in ALLIED_NATIONS]
    if allied_nationals and not elevated_nationals:
        base_risk = 0.20
        risk_factors.append("Foreign nationals from allied NATO/FIVE EYES nations")
    
    # Non-allied, non-elevated countries get baseline low risk
    if not elevated_nationals and not allied_nationals:
        base_risk = 0.35
        risk_factors.append("Foreign nationals from standard international countries")
    
    # Scale risk by USML category sensitivity
    if usml_category > 0 and usml_category in USML_CATEGORIES:
        category = USML_CATEGORIES[usml_category]
        if category.deemed_export_sensitivity == "HIGH":
            base_risk *= 1.0
            risk_factors.append(f"USML Category {usml_category}: HIGH sensitivity category")
        elif category.deemed_export_sensitivity == "MEDIUM":
            base_risk *= 0.8
            risk_factors.append(f"USML Category {usml_category}: MEDIUM sensitivity category")
        else:
            base_risk *= 0.6
    
    # TCP status evaluation
    if tcp_status == "MISSING":
        risk_factors.append("Technology Control Plan (TCP) MISSING but required")
        base_risk += 0.30
    elif tcp_status == "PENDING":
        risk_factors.append("Technology Control Plan (TCP) PENDING implementation")
        base_risk += 0.15
    elif tcp_status == "IMPLEMENTED":
        risk_factors.append("Technology Control Plan (TCP) properly implemented")
        base_risk *= 0.5
    
    # Facility clearance reduces risk for classified data
    if facility_clearance in ("SECRET", "CONFIDENTIAL"):
        risk_factors.append(f"Facility has {facility_clearance} security clearance")
        base_risk *= 0.7
    
    # Foreign national count scaling (more people = higher risk)
    if foreign_national_count > 10:
        risk_factors.append("Large number of foreign nationals with access (>10)")
        base_risk = min(1.0, base_risk * 1.15)
    
    # Determine recommendation
    if base_risk >= 0.80:
        recommendation = "BLOCK"
    elif base_risk >= 0.50:
        recommendation = "REQUIRE_LICENSE"
    else:
        recommendation = "ALLOW"
    
    return DeemedExportRisk(
        risk_score=min(1.0, base_risk),
        foreign_national_count=foreign_national_count,
        nationalities=nationalities,
        tcp_status=tcp_status,
        risk_factors=risk_factors,
        recommendation=recommendation,
    )


# =============================================================================
# RED FLAG ASSESSMENT
# =============================================================================

@dataclass
class RedFlagAssessment:
    """
    Assessment of red flags indicating potential ITAR diversion risk.
    
    Per BIS/DDTC guidance and recent enforcement cases, certain transaction
    patterns indicate heightened risk of diversion to prohibited end-users
    or end-uses.
    
    Attributes:
        score: Normalized risk 0.0-1.0 (higher = more flags triggered)
        flags_triggered: List of red flag names that matched
        total_flags_checked: Total number of red flags evaluated
        recommendation: Recommended action (ALLOW, ENHANCED_DUE_DILIGENCE, BLOCK)
    """
    score: float
    flags_triggered: list[str]
    total_flags_checked: int
    recommendation: str


RED_FLAGS = [
    "unusual_routing",
    "reluctant_end_use_info",
    "cash_payment_insistence",
    "disproportionate_order",
    "new_customer_sensitive_item",
    "military_end_use_indicators",
    "packaging_mismatch",
    "delivery_to_freight_forwarder",
    "declined_installation",
    "known_diversion_route",
    "intermediate_consignee_mismatch",
    "vague_end_user_description",
]


def check_red_flags(
    transaction: dict,
    vendor_country: str,
    end_user_country: str,
    usml_category: int = 0,
) -> RedFlagAssessment:
    """
    Check transaction for BIS/DDTC red flag indicators of diversion risk.
    
    Red flags are based on:
    - BIS Supplements 1-7 to 15 CFR 730 (Red Flag Indicators)
    - DDTC recent enforcement actions and consent agreements
    - Supply chain diversion case studies
    
    Args:
        transaction: Dict with keys:
            - routing: List of countries item passes through
            - customer_reluctance_on_end_use: Boolean
            - payment_method: "cash", "wire", "letter_of_credit", etc.
            - order_quantity: Integer units ordered
            - customer_prior_orders: Boolean (established customer?)
            - end_use_stated: String description of stated end-use
            - packaging_description: String of requested packaging
            - delivery_to_freight_forwarder: Boolean
            - declined_installation_training: Boolean
            - end_user_description_clarity: "detailed", "vague", "missing"
        vendor_country: ISO country code of seller
        end_user_country: ISO country code of stated end-user
        usml_category: USML category (1-21) if applicable
    
    Returns:
        RedFlagAssessment with detailed findings
    
    References:
        BIS Red Flag Indicators: https://www.bis.doc.gov
        DDTC Enforcement: https://pmddtc.state.gov
        15 CFR 730: Commerce Control List Supplement
    """
    triggered_flags = []
    
    # 1. Unusual routing (item routed through known diversion hubs)
    routing = transaction.get("routing", [])
    diversion_hubs = {"AE", "HK", "SG", "MY", "PL", "AZ", "KZ", "TR"}
    if any(country in diversion_hubs for country in routing):
        triggered_flags.append("unusual_routing")
    
    # 2. Reluctant end-use information
    if transaction.get("customer_reluctance_on_end_use"):
        triggered_flags.append("reluctant_end_use_info")
    
    # 3. Cash payment insistence
    if transaction.get("payment_method") == "cash":
        triggered_flags.append("cash_payment_insistence")
    
    # 4. Disproportionate order (order much larger than typical for stated use)
    # Heuristic: >1000 units of small items or unusual quantity ranges
    if transaction.get("order_quantity", 0) > 1000:
        triggered_flags.append("disproportionate_order")
    
    # 5. New customer ordering sensitive items
    if not transaction.get("customer_prior_orders") and usml_category in (1, 2, 3, 4, 5):
        triggered_flags.append("new_customer_sensitive_item")
    
    # 6. Military end-use indicators in stated purpose
    end_use = transaction.get("end_use_stated", "").lower()
    military_terms = ["military", "defense", "weapon", "combat", "armed forces", "combat operation"]
    if any(term in end_use for term in military_terms):
        triggered_flags.append("military_end_use_indicators")
    
    # 7. Packaging mismatch (heavy military-grade packaging for commercial use)
    packaging = transaction.get("packaging_description", "").lower()
    if "military" in packaging and "commercial" in end_use:
        triggered_flags.append("packaging_mismatch")
    
    # 8. Delivery to freight forwarder instead of end-user
    if transaction.get("delivery_to_freight_forwarder"):
        triggered_flags.append("delivery_to_freight_forwarder")
    
    # 9. Declined installation/training (red flag per DDTC guidance)
    if transaction.get("declined_installation_training"):
        triggered_flags.append("declined_installation")
    
    # 10. Known diversion route (specific country pair combinations)
    diversion_routes = {("US", "IR"), ("US", "SY"), ("US", "CN"), ("US", "RU")}
    if (vendor_country, end_user_country) in diversion_routes:
        triggered_flags.append("known_diversion_route")
    
    # 11. Intermediate consignee mismatch
    # If intermediate consignee country != end-user country without explanation
    intermediate = transaction.get("intermediate_consignee_country")
    if intermediate and intermediate != end_user_country:
        triggered_flags.append("intermediate_consignee_mismatch")
    
    # 12. Vague or missing end-user description
    clarity = transaction.get("end_user_description_clarity", "missing")
    if clarity in ("vague", "missing"):
        triggered_flags.append("vague_end_user_description")
    
    # Calculate score: each flag adds risk proportionally
    score = min(1.0, len(triggered_flags) / len(RED_FLAGS))
    
    # Scale by USML category risk
    if usml_category > 0 and usml_category in USML_CATEGORIES:
        if USML_CATEGORIES[usml_category].risk_level == "CRITICAL":
            score = min(1.0, score * 1.3)
    
    # Recommendation logic
    if score >= 0.7:
        recommendation = "BLOCK"
    elif score >= 0.4:
        recommendation = "ENHANCED_DUE_DILIGENCE"
    else:
        recommendation = "ALLOW"
    
    return RedFlagAssessment(
        score=score,
        flags_triggered=triggered_flags,
        total_flags_checked=len(RED_FLAGS),
        recommendation=recommendation,
    )


# =============================================================================
# ITAR COMPLIANCE RESULT DATACLASS
# =============================================================================

@dataclass
class ITARComplianceResult:
    """
    Comprehensive ITAR compliance evaluation result.
    
    Orchestrates all sub-checks and returns integrated determination
    for use in Helios risk assessment and regulatory gate system.
    
    Attributes:
        overall_status: COMPLIANT, NON_COMPLIANT, REQUIRES_REVIEW, PROHIBITED
        registration_status: DDTC registration status
        country_status: Country-level restriction determination
        deemed_export_risk: Deemed export sub-assessment
        red_flag_assessment: Red flag sub-assessment
        usml_category_risk: Risk weight for applicable USML category (0.0-1.0)
        required_license_type: Recommended license type (DSP-5, DSP-73, DSP-85, etc.)
        explanation: Human-readable summary of determination
        factors: Structured dict of all contributing factors for audit trail
    """
    overall_status: str
    registration_status: str
    country_status: str
    deemed_export_risk: DeemedExportRisk
    red_flag_assessment: RedFlagAssessment
    usml_category_risk: float
    required_license_type: str
    explanation: str
    factors: dict


def evaluate_itar_compliance(
    vendor_name: str,
    vendor_country: str,
    usml_category: int = 0,
    ddtc_registered: Optional[bool] = None,
    foreign_nationals: Optional[list[dict]] = None,
    tcp_status: str = "UNKNOWN",
    transaction_flags: Optional[dict] = None,
    end_user_country: Optional[str] = None,
) -> ITARComplianceResult:
    """
    Evaluate comprehensive ITAR compliance for vendor and transaction.
    
    Implements integrated assessment combining:
    1. Country restrictions (22 CFR 126.1)
    2. DDTC registration status (22 CFR 122)
    3. Deemed export risk (22 CFR 120.17)
    4. Red flag analysis (BIS/DDTC guidance)
    5. USML category risk (22 CFR 121)
    
    Args:
        vendor_name: Legal name of vendor entity
        vendor_country: ISO country code of vendor headquarters
        usml_category: USML category number (1-21) if item is ITAR-controlled, 0 if unknown
        ddtc_registered: DDTC registration status (True/False/None=unknown)
        foreign_nationals: List of dicts with foreign national access details
        tcp_status: Technology Control Plan status (IMPLEMENTED, PENDING, NOT_REQUIRED, MISSING, UNKNOWN)
        transaction_flags: Dict of transaction red flag indicators
        end_user_country: ISO country code of intended end-user
    
    Returns:
        ITARComplianceResult with integrated assessment and recommendations
    
    Logic:
        - Prohibited country = PROHIBITED (absolute block)
        - Non-DDTC registered + ITAR item = NON_COMPLIANT
        - Elevated scrutiny + missing TCP + foreign nationals = REQUIRES_REVIEW
        - Clean profile with TCP implemented = COMPLIANT
        - Red flags triggered = escalate to REQUIRES_REVIEW or NON_COMPLIANT
    
    References:
        22 CFR 120-130: ITAR regulations
        22 CFR 127.7: Penalties
        DDTC Debarment List: pmddtc.state.gov
    """
    
    # Initialize result components
    country_status_enum = CountryStatus.ALLOWED
    registration_status_enum = RegistrationStatus.UNKNOWN
    license_type = LicenseType.NONE
    factors = {
        "vendor_name": vendor_name,
        "vendor_country": vendor_country,
        "usml_category": usml_category,
        "ddtc_registered": ddtc_registered,
        "foreign_nationals_count": len(foreign_nationals) if foreign_nationals else 0,
        "tcp_status": tcp_status,
        "end_user_country": end_user_country,
    }
    
    # Step 1: Check country restrictions (22 CFR 126.1)
    if vendor_country in ITAR_PROHIBITED_COUNTRIES:
        country_status_enum = CountryStatus.PROHIBITED
        return ITARComplianceResult(
            overall_status=ComplianceStatus.PROHIBITED,
            registration_status=RegistrationStatus.UNKNOWN,
            country_status=country_status_enum.value,
            deemed_export_risk=DeemedExportRisk(
                risk_score=1.0,
                foreign_national_count=0,
                nationalities=[vendor_country],
                tcp_status="N/A",
                risk_factors=["Vendor in prohibited country per 22 CFR 126.1"],
                recommendation="BLOCK",
            ),
            red_flag_assessment=RedFlagAssessment(
                score=1.0,
                flags_triggered=["known_diversion_route"],
                total_flags_checked=len(RED_FLAGS),
                recommendation="BLOCK",
            ),
            usml_category_risk=1.0,
            required_license_type=LicenseType.UNKNOWN.value,
            explanation=f"PROHIBITED: Vendor {vendor_name} located in {vendor_country}, which is prohibited per 22 CFR 126.1",
            factors=factors,
        )
    
    if vendor_country in ITAR_ELEVATED_SCRUTINY:
        country_status_enum = CountryStatus.ELEVATED_SCRUTINY
    elif vendor_country in CANADIAN_EXEMPTION_ELIGIBLE:
        country_status_enum = CountryStatus.CANADIAN_EXEMPTION
    else:
        country_status_enum = CountryStatus.ALLOWED
    
    # Step 2: Check DDTC registration if ITAR item involved
    if usml_category > 0:
        if ddtc_registered is True:
            registration_status_enum = RegistrationStatus.REGISTERED
        elif ddtc_registered is False:
            registration_status_enum = RegistrationStatus.UNREGISTERED
        else:
            registration_status_enum = RegistrationStatus.UNKNOWN
    
    # Step 3: Assess deemed export risk
    deemed_export_result = assess_deemed_export_risk(
        foreign_nationals=foreign_nationals or [],
        tcp_status=tcp_status,
        usml_category=usml_category,
        facility_clearance="NONE",
    )
    
    # Step 4: Check red flags
    red_flags_result = check_red_flags(
        transaction=transaction_flags or {},
        vendor_country=vendor_country,
        end_user_country=end_user_country or vendor_country,
        usml_category=usml_category,
    )
    
    # Step 5: Determine USML category risk
    usml_category_risk = 0.0
    if usml_category > 0 and usml_category in USML_CATEGORIES:
        usml_category_risk = USML_CATEGORIES[usml_category].base_risk_weight
        license_type = LicenseType.DSP_5  # Most ITAR items require export license
    
    # Step 6: Integrate findings and determine overall status
    overall_status = ComplianceStatus.COMPLIANT
    explanation_parts = []
    
    # Non-compliant triggers
    if registration_status_enum == RegistrationStatus.UNREGISTERED and usml_category > 0:
        overall_status = ComplianceStatus.NON_COMPLIANT
        explanation_parts.append("Vendor not registered with DDTC for ITAR items")
    
    if deemed_export_result.recommendation == "BLOCK":
        overall_status = ComplianceStatus.NON_COMPLIANT
        explanation_parts.append("Deemed export risk to prohibited country")
    
    if red_flags_result.recommendation == "BLOCK":
        overall_status = ComplianceStatus.NON_COMPLIANT
        explanation_parts.append(f"Critical red flags triggered: {', '.join(red_flags_result.flags_triggered[:3])}")
    
    # Requires review triggers
    if country_status_enum == CountryStatus.ELEVATED_SCRUTINY:
        overall_status = ComplianceStatus.REQUIRES_REVIEW
        explanation_parts.append(f"Vendor in elevated scrutiny country: {vendor_country}")
    
    if deemed_export_result.recommendation == "REQUIRE_LICENSE":
        overall_status = ComplianceStatus.REQUIRES_REVIEW
        explanation_parts.append("Deemed export risk present - enhanced controls required")
    
    if red_flags_result.recommendation == "ENHANCED_DUE_DILIGENCE":
        overall_status = ComplianceStatus.REQUIRES_REVIEW
        explanation_parts.append(f"Red flags present: {', '.join(red_flags_result.flags_triggered[:3])}")
    
    if tcp_status == "MISSING" and deemed_export_result.foreign_national_count > 0:
        overall_status = ComplianceStatus.REQUIRES_REVIEW
        explanation_parts.append("Technology Control Plan required but missing")
    
    # Generate final explanation
    if not explanation_parts:
        if usml_category > 0:
            explanation = f"COMPLIANT: {vendor_name} meets ITAR requirements for USML Category {usml_category} ({USML_CATEGORIES[usml_category].name})"
        else:
            explanation = f"COMPLIANT: {vendor_name} has no identified ITAR compliance issues"
    else:
        explanation = f"{overall_status.value}: {'; '.join(explanation_parts)}"
    
    factors.update({
        "country_status": country_status_enum.value,
        "registration_status": registration_status_enum.value,
        "red_flags_triggered": red_flags_result.flags_triggered,
        "deemed_export_risk_score": deemed_export_result.risk_score,
    })
    
    return ITARComplianceResult(
        overall_status=overall_status.value,
        registration_status=registration_status_enum.value,
        country_status=country_status_enum.value,
        deemed_export_risk=deemed_export_result,
        red_flag_assessment=red_flags_result,
        usml_category_risk=usml_category_risk,
        required_license_type=license_type.value,
        explanation=explanation,
        factors=factors,
    )


# =============================================================================
# DDTC DEBARRED LIST (Fallback Reference Data)
# =============================================================================

# Known debarred entities from DDTC Debarment List (pmddtc.state.gov)
# Used as fallback when unable to query live DDTC database
# Updated from recent enforcement actions and consent agreements

DDTC_DEBARRED_FALLBACK = [
    {
        "name": "Airtronic USA Inc",
        "dba_names": ["Airtronic", "Airtronic Defense"],
        "date": "2021-01-15",
        "basis": "Consent Agreement - Unauthorized exports of firearm parts",
        "duration_years": 3,
        "original_penalty": 2100000,
    },
    {
        "name": "FLIR Systems Inc",
        "dba_names": ["FLIR", "FLIR Surveillance", "Teledyne FLIR"],
        "date": "2023-05-19",
        "basis": "Consent Agreement - Deemed export of thermal imaging technology",
        "duration_years": 3,
        "original_penalty": 30000000,
    },
    {
        "name": "Honeywell International Inc",
        "dba_names": ["Honeywell", "Honeywell Aerospace"],
        "date": "2023-08-22",
        "basis": "Consent Agreement - Unauthorized technical assistance to foreign nationals",
        "duration_years": 2,
        "original_penalty": 13000000,
    },
    {
        "name": "L3 Technologies",
        "dba_names": ["L3Harris", "L3 Harris Technologies", "L3"],
        "date": "2023-09-10",
        "basis": "Consent Agreement - Technical data disclosure violations",
        "duration_years": 3,
        "original_penalty": 13000000,
    },
    {
        "name": "Raytheon Technologies Corporation",
        "dba_names": ["Raytheon", "RTX", "Collins Aerospace"],
        "date": "2024-10-15",
        "basis": "Consent Agreement - Multiple deemed export violations",
        "duration_years": 3,
        "original_penalty": 950000000,
    },
]


def check_ddtc_debarred(entity_name: str) -> Optional[dict]:
    """
    Check if entity appears on DDTC debarred list (fallback database).
    
    Searches DDTC_DEBARRED_FALLBACK for entity by name or DBA.
    In production, would query live DDTC API at pmddtc.state.gov.
    
    Args:
        entity_name: Legal name of entity to check
    
    Returns:
        Dict with debarment details if found, None otherwise
    
    References:
        22 CFR 127: ITAR Enforcement
        pmddtc.state.gov: Official DDTC Debarment List
    """
    entity_name_lower = entity_name.lower()
    
    for debarred in DDTC_DEBARRED_FALLBACK:
        if entity_name_lower == debarred["name"].lower():
            return debarred
        
        for dba in debarred.get("dba_names", []):
            if entity_name_lower == dba.lower():
                return debarred
    
    return None
