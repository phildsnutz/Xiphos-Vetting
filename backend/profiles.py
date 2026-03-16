"""
Xiphos Compliance Profiles System v1.0

Defines configurable compliance profiles for 5 vertical markets, each with:
- Entity labeling (vendor/end-user/collaborator/sub-awardee/supplier)
- Program type categories
- Risk factor weights for the Bayesian engine
- Connector orchestration priorities
- Hard stop rules
- Tier thresholds
- Required and optional fields
- UI configuration
- Regulatory references

This system allows Xiphos to scale from defense acquisition (current) to
ITAR trade compliance, university research security, grants compliance,
and commercial supply chain vetting.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ComplianceProfile:
    """
    A compliance profile defines how a vendor/entity is screened for a
    specific vertical market or regulatory domain.
    """
    id: str                          # e.g., "defense_acquisition"
    name: str                        # e.g., "Defense Acquisition"
    description: str
    entity_label: str                # "Vendor", "Collaborator", "End-User", "Sub-Awardee", "Supplier"
    program_types: list[dict]        # [{"id": "weapons_system", "label": "Weapons System"}, ...]
    risk_factors: list[dict]         # [{"name": "Sanctions", "weight": 5.0}, ...]
    connector_priority: list[str]    # Ordered connector names to run
    connector_weights: dict          # Override severity weights per connector
    hard_stop_rules: list[str]       # Active hard stop rules (e.g., "sanctioned_country_sensitive")
    tier_thresholds: dict            # {"hard_stop": 0.60, "elevated": 0.30, "monitor": 0.15}
    required_fields: list[str]       # Beyond name/country
    optional_fields: list[dict]      # [{"id": "field_name", "label": "Field Label", "type": "text"}, ...]
    ui_config: dict = field(default_factory=dict)  # Color, terminology, etc.
    regulatory_references: list[dict] = field(default_factory=list)  # URLs and regulations


# ============================================================================
# PROFILE REGISTRY
# ============================================================================

PROFILES = {
    "defense_acquisition": ComplianceProfile(
        id="defense_acquisition",
        name="Defense Acquisition",
        description="Traditional defense prime/subcontractor vetting with DFARS/ITAR focus",
        entity_label="Vendor",
        program_types=[
            {"id": "weapons_system", "label": "Weapons System"},
            {"id": "mission_critical", "label": "Mission Critical"},
            {"id": "nuclear_related", "label": "Nuclear-Related"},
            {"id": "intelligence_community", "label": "Intelligence Community"},
            {"id": "critical_infrastructure", "label": "Critical Infrastructure"},
            {"id": "dual_use", "label": "Dual-Use"},
            {"id": "standard_industrial", "label": "Standard Industrial"},
            {"id": "commercial_off_shelf", "label": "Commercial Off-Shelf (COTS)"},
            {"id": "services", "label": "Services"},
        ],
        risk_factors=[
            {"name": "Sanctions", "weight": 5.0},
            {"name": "Geography", "weight": 2.5},
            {"name": "Ownership", "weight": 3.0},
            {"name": "Data Quality", "weight": 1.5},
            {"name": "Executive", "weight": 2.0},
        ],
        connector_priority=[
            "dod_sam_exclusions", "bis_entity_list", "cfius_risk", "trade_csl",
            "un_sanctions", "opensanctions_pep", "worldbank_debarred", "icij_offshore",
            "fara", "gdelt_media", "sec_edgar", "gleif_lei", "opencorporates",
            "uk_companies_house", "sam_gov", "usaspending", "epa_echo", "osha_safety",
            "courtlistener", "fdic_bankfind",
        ],
        connector_weights={},  # Use defaults
        hard_stop_rules=[
            "sanctions_match", "sanctioned_country_sensitive", "sanctioned_state_owned",
            "adversary_state_owned", "sectoral_state_weapons", "shell_depth", "opaque_high_risk",
        ],
        tier_thresholds={"hard_stop": 0.60, "elevated": 0.30, "monitor": 0.15},
        required_fields=["name", "country"],
        optional_fields=[
            {"id": "program", "label": "Program Type", "type": "select"},
            {"id": "cage_code", "label": "CAGE Code", "type": "text"},
            {"id": "duns", "label": "DUNS Number", "type": "text"},
        ],
        ui_config={
            "color": "#0052CC",  # DoD blue
            "icon": "shield",
            "risk_label": "Compliance Risk",
        },
        regulatory_references=[
            {"name": "DFARS 252.204-7018", "url": "https://www.dfars.mil", "description": "Beneficial Ownership"},
            {"name": "ITAR Part 120-129", "url": "https://www.pmddtc.state.gov", "description": "Arms Control"},
            {"name": "EAR Part 730-774", "url": "https://www.bis.doc.gov", "description": "Export Control"},
        ],
    ),

    "itar_trade_compliance": ComplianceProfile(
        id="itar_trade_compliance",
        name="ITAR Trade Compliance",
        description="Export control vetting with USML category tracking and deemed export rules",
        entity_label="End-User",
        program_types=[
            {"id": "cat_i_firearms", "label": "Cat I: Firearms"},
            {"id": "cat_ii_artillery", "label": "Cat II: Artillery"},
            {"id": "cat_iii_ammunition", "label": "Cat III: Ammunition"},
            {"id": "cat_iv_launch_vehicles", "label": "Cat IV: Launch Vehicles"},
            {"id": "cat_v_explosives", "label": "Cat V: Explosives"},
            {"id": "cat_vi_naval", "label": "Cat VI: Naval"},
            {"id": "cat_vii_ground_vehicles", "label": "Cat VII: Ground Vehicles"},
            {"id": "cat_viii_aircraft", "label": "Cat VIII: Aircraft"},
            {"id": "cat_ix_military_training", "label": "Cat IX: Military Training"},
            {"id": "cat_x_protective", "label": "Cat X: Protective Equipment"},
            {"id": "cat_xi_electronics", "label": "Cat XI: Electronics"},
            {"id": "cat_xii_fire_control", "label": "Cat XII: Fire Control"},
            {"id": "cat_xiii_materials", "label": "Cat XIII: Materials"},
            {"id": "cat_xiv_toxicological", "label": "Cat XIV: Toxicological"},
            {"id": "cat_xv_spacecraft", "label": "Cat XV: Spacecraft"},
            {"id": "cat_xvi_nuclear", "label": "Cat XVI: Nuclear"},
            {"id": "cat_xvii_classified", "label": "Cat XVII: Classified"},
            {"id": "cat_xviii_directed_energy", "label": "Cat XVIII: Directed Energy"},
            {"id": "cat_xix_gas_turbine", "label": "Cat XIX: Gas Turbine"},
            {"id": "cat_xx_submersible", "label": "Cat XX: Submersible"},
            {"id": "cat_xxi_misc", "label": "Cat XXI: Miscellaneous"},
            {"id": "dual_use_ear", "label": "Dual-Use (EAR)"},
        ],
        risk_factors=[
            {"name": "Sanctions", "weight": 6.0},
            {"name": "Geography", "weight": 3.0},
            {"name": "Ownership", "weight": 2.5},
            {"name": "Data Quality", "weight": 1.0},
            {"name": "Executive", "weight": 1.5},
            {"name": "End-Use", "weight": 3.5},
            {"name": "Deemed Export", "weight": 2.0},
        ],
        connector_priority=[
            "bis_entity_list", "trade_csl", "un_sanctions", "dod_sam_exclusions",
            "cfius_risk", "opensanctions_pep", "worldbank_debarred",
            "sec_edgar", "gleif_lei", "opencorporates", "uk_companies_house",
            "sam_gov", "usaspending", "gdelt_media", "fara",
        ],
        connector_weights={
            "bis_entity_list": 1.5,
            "trade_csl": 1.4,
            "un_sanctions": 1.5,
        },
        hard_stop_rules=[
            "sanctions_match", "sanctioned_country_sensitive", "sanctioned_state_owned",
            "adversary_state_owned", "sectoral_state_weapons",
        ],
        tier_thresholds={"hard_stop": 0.50, "elevated": 0.25, "monitor": 0.12},
        required_fields=["name", "country", "usml_category"],
        optional_fields=[
            {"id": "usml_category", "label": "USML Category", "type": "select"},
            {"id": "end_use_statement", "label": "End-Use Statement", "type": "textarea"},
            {"id": "intermediate_consignee", "label": "Intermediate Consignee", "type": "text"},
            {"id": "freight_forwarder", "label": "Freight Forwarder", "type": "text"},
            {"id": "license_type", "label": "License Type", "type": "select"},
        ],
        ui_config={
            "color": "#DC3545",  # Danger red for strict compliance
            "icon": "alert-triangle",
            "risk_label": "Export Control Risk",
        },
        regulatory_references=[
            {"name": "ITAR Part 120-129", "url": "https://www.pmddtc.state.gov", "description": "International Traffic in Arms Regulations"},
            {"name": "EAR Part 730-774", "url": "https://www.bis.doc.gov", "description": "Export Administration Regulations"},
            {"name": "OFAC SDN", "url": "https://ofac.treasury.gov", "description": "Sanctions Lists"},
        ],
    ),

    "university_research_security": ComplianceProfile(
        id="university_research_security",
        name="University Research Security",
        description="Collaborator vetting for sensitive research with talent and institutional risk assessment",
        entity_label="Collaborator",
        program_types=[
            {"id": "ai_ml", "label": "AI/Machine Learning"},
            {"id": "quantum_computing", "label": "Quantum Computing"},
            {"id": "semiconductors", "label": "Semiconductors"},
            {"id": "hypersonics", "label": "Hypersonics"},
            {"id": "biotech", "label": "Biotechnology"},
            {"id": "nuclear_science", "label": "Nuclear Science"},
            {"id": "space_technology", "label": "Space Technology"},
            {"id": "cyber_security", "label": "Cybersecurity"},
            {"id": "advanced_materials", "label": "Advanced Materials"},
            {"id": "energy_storage", "label": "Energy Storage"},
            {"id": "general_research", "label": "General Research"},
        ],
        risk_factors=[
            {"name": "Sanctions", "weight": 4.0},
            {"name": "Geography", "weight": 3.5},
            {"name": "Ownership", "weight": 2.0},
            {"name": "Data Quality", "weight": 1.0},
            {"name": "Executive", "weight": 1.5},
            {"name": "Talent Program", "weight": 4.0},
            {"name": "Institutional Risk", "weight": 3.0},
        ],
        connector_priority=[
            "bis_entity_list", "opensanctions_pep", "un_sanctions", "dod_sam_exclusions",
            "cfius_risk", "trade_csl", "worldbank_debarred", "icij_offshore",
            "fara", "gdelt_media", "sec_edgar", "gleif_lei", "opencorporates",
            "courtlistener", "uk_companies_house",
        ],
        connector_weights={
            "opensanctions_pep": 1.6,
            "bis_entity_list": 1.4,
        },
        hard_stop_rules=[
            "sanctions_match", "sanctioned_country_sensitive", "sanctioned_state_owned",
            "adversary_state_owned",
        ],
        tier_thresholds={"hard_stop": 0.55, "elevated": 0.28, "monitor": 0.14},
        required_fields=["name", "country", "research_domain"],
        optional_fields=[
            {"id": "research_domain", "label": "Research Domain", "type": "select"},
            {"id": "home_institution", "label": "Home Institution", "type": "text"},
            {"id": "funding_source", "label": "Funding Source", "type": "text"},
            {"id": "visa_status", "label": "Visa Status", "type": "select"},
            {"id": "collaboration_type", "label": "Collaboration Type", "type": "select"},
        ],
        ui_config={
            "color": "#6F42C1",  # Purple for academic
            "icon": "graduation-cap",
            "risk_label": "Research Security Risk",
        },
        regulatory_references=[
            {"name": "EO 14028", "url": "https://www.whitehouse.gov", "description": "Cybersecurity Executive Order"},
            {"name": "CFIUS Rules", "url": "https://home.treasury.gov/cfius", "description": "Foreign Investment in US Tech"},
            {"name": "NSF Vetting", "url": "https://www.nsf.gov", "description": "National Science Foundation Guidelines"},
        ],
    ),

    "grants_compliance": ComplianceProfile(
        id="grants_compliance",
        name="Grants Compliance",
        description="Sub-awardee vetting for federal/foundation grants with SAM.gov and USASPENDING integration",
        entity_label="Sub-Awardee",
        program_types=[
            {"id": "federal_grant", "label": "Federal Grant"},
            {"id": "state_grant", "label": "State Grant"},
            {"id": "foundation_grant", "label": "Foundation Grant"},
            {"id": "cooperative_agreement", "label": "Cooperative Agreement"},
            {"id": "subcontract", "label": "Subcontract"},
        ],
        risk_factors=[
            {"name": "Sanctions", "weight": 4.0},
            {"name": "Geography", "weight": 1.5},
            {"name": "Ownership", "weight": 2.0},
            {"name": "Data Quality", "weight": 3.0},
            {"name": "Executive", "weight": 1.5},
            {"name": "Past Performance", "weight": 3.0},
            {"name": "Financial Stability", "weight": 2.5},
        ],
        connector_priority=[
            "sam_gov", "usaspending", "dod_sam_exclusions", "bis_entity_list",
            "un_sanctions", "trade_csl", "worldbank_debarred", "sec_edgar",
            "gleif_lei", "fdic_bankfind", "opencorporates", "courtlistener",
        ],
        connector_weights={
            "sam_gov": 1.8,
            "usaspending": 1.5,
        },
        hard_stop_rules=[
            "sanctions_match", "sanctioned_country_sensitive", "sanctioned_state_owned",
        ],
        tier_thresholds={"hard_stop": 0.55, "elevated": 0.30, "monitor": 0.15},
        required_fields=["name", "country"],
        optional_fields=[
            {"id": "uei_number", "label": "UEI Number", "type": "text"},
            {"id": "grant_program", "label": "Grant Program", "type": "select"},
            {"id": "award_amount", "label": "Award Amount", "type": "number"},
            {"id": "agency", "label": "Funding Agency", "type": "select"},
        ],
        ui_config={
            "color": "#20C997",  # Green for grants
            "icon": "check-circle",
            "risk_label": "Award Compliance Risk",
        },
        regulatory_references=[
            {"name": "2 CFR 200", "url": "https://www.ecfr.gov", "description": "Uniform Administrative Requirements"},
            {"name": "SAM.gov", "url": "https://www.sam.gov", "description": "System for Award Management"},
            {"name": "USASPENDING.gov", "url": "https://www.usaspending.gov", "description": "Federal Spending Data"},
        ],
    ),

    "commercial_supply_chain": ComplianceProfile(
        id="commercial_supply_chain",
        name="Commercial Supply Chain",
        description="Supplier vetting for commercial goods with regulatory compliance and ESG assessment",
        entity_label="Supplier",
        program_types=[
            {"id": "pharmaceutical_api", "label": "Pharmaceutical APIs"},
            {"id": "automotive_safety", "label": "Automotive Safety"},
            {"id": "electronics_component", "label": "Electronics Components"},
            {"id": "food_ingredient", "label": "Food Ingredients"},
            {"id": "chemical_raw_material", "label": "Chemical Raw Materials"},
            {"id": "textile_material", "label": "Textile Materials"},
            {"id": "general_commercial", "label": "General Commercial"},
        ],
        risk_factors=[
            {"name": "Sanctions", "weight": 3.0},
            {"name": "Geography", "weight": 2.0},
            {"name": "Ownership", "weight": 2.0},
            {"name": "Data Quality", "weight": 2.0},
            {"name": "Executive", "weight": 1.5},
            {"name": "Regulatory Compliance", "weight": 3.5},
            {"name": "ESG", "weight": 2.0},
        ],
        connector_priority=[
            "bis_entity_list", "trade_csl", "dod_sam_exclusions", "un_sanctions",
            "sec_edgar", "gleif_lei", "opencorporates", "epa_echo", "osha_safety",
            "uk_companies_house", "gdelt_media", "worldbank_debarred", "courtlistener",
        ],
        connector_weights={
            "epa_echo": 1.3,
            "osha_safety": 1.2,
        },
        hard_stop_rules=[
            "sanctions_match", "sanctioned_country_sensitive", "sanctioned_state_owned",
        ],
        tier_thresholds={"hard_stop": 0.60, "elevated": 0.35, "monitor": 0.18},
        required_fields=["name", "country"],
        optional_fields=[
            {"id": "industry_sector", "label": "Industry Sector", "type": "select"},
            {"id": "product_category", "label": "Product Category", "type": "select"},
            {"id": "import_volume", "label": "Annual Import Volume", "type": "text"},
            {"id": "hs_code", "label": "HS Code(s)", "type": "text"},
        ],
        ui_config={
            "color": "#FFC107",  # Amber for caution
            "icon": "package",
            "risk_label": "Supply Chain Risk",
        },
        regulatory_references=[
            {"name": "FDA Import Rules", "url": "https://www.fda.gov", "description": "Food and Drug Administration"},
            {"name": "REACH", "url": "https://echa.europa.eu", "description": "European Chemical Regulations"},
            {"name": "Conflict Minerals", "url": "https://www.sec.gov", "description": "SEC Dodd-Frank Reporting"},
        ],
    ),
}


# ============================================================================
# API FUNCTIONS
# ============================================================================

def get_profile(profile_id: str) -> Optional[ComplianceProfile]:
    """Retrieve a compliance profile by ID."""
    return PROFILES.get(profile_id)


def list_profiles() -> list[ComplianceProfile]:
    """Return all compliance profiles."""
    return list(PROFILES.values())


def get_default_profile() -> ComplianceProfile:
    """Return the default profile (defense acquisition)."""
    return PROFILES["defense_acquisition"]


def get_factor_weights(profile_id: str) -> Optional[dict]:
    """
    Return the risk factor weights for a profile.
    Format: {"Sanctions": 5.0, "Geography": 2.5, ...}
    """
    profile = get_profile(profile_id)
    if not profile:
        return None
    return {f["name"]: f["weight"] for f in profile.risk_factors}


def get_tier_thresholds(profile_id: str) -> Optional[dict]:
    """
    Return the tier thresholds for a profile.
    Format: {"hard_stop": 0.60, "elevated": 0.30, "monitor": 0.15}
    """
    profile = get_profile(profile_id)
    if not profile:
        return None
    return profile.tier_thresholds


def get_connector_list(profile_id: str) -> Optional[list[str]]:
    """
    Return the ordered list of connectors to run for a profile.
    """
    profile = get_profile(profile_id)
    if not profile:
        return None
    return profile.connector_priority


def validate_profile_id(profile_id: str) -> bool:
    """Check if a profile ID is valid."""
    return profile_id in PROFILES


def profile_to_dict(profile: ComplianceProfile) -> dict:
    """Convert a ComplianceProfile to a JSON-serializable dict."""
    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "entity_label": profile.entity_label,
        "program_types": profile.program_types,
        "risk_factors": profile.risk_factors,
        "connector_priority": profile.connector_priority,
        "connector_weights": profile.connector_weights,
        "hard_stop_rules": profile.hard_stop_rules,
        "tier_thresholds": profile.tier_thresholds,
        "required_fields": profile.required_fields,
        "optional_fields": profile.optional_fields,
        "ui_config": profile.ui_config,
        "regulatory_references": profile.regulatory_references,
    }
