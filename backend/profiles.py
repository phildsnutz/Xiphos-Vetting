"""
Xiphos Compliance Profiles System v2.0

Defines configurable compliance profiles for 5 vertical markets, each with:
- Entity labeling (vendor/end-user/collaborator/sub-awardee/supplier)
- Program type categories
- OSINT connector orchestration priorities and weights
- Hard stop rules
- Required and optional fields
- UI configuration
- Regulatory references

NOTE: Scoring weights and tier thresholds are NOT in profiles. The v5.0
FGAMLogit engine (fgamlogit.py) owns all scoring parameters via its
sensitivity-aware weight matrices and integrate_layers() tier logic.
"""

from dataclasses import dataclass, field
from typing import Optional

try:
    from osint.enrichment import CONNECTORS as ACTIVE_CONNECTOR_MODULES
    ACTIVE_CONNECTORS = {name for name, _ in ACTIVE_CONNECTOR_MODULES}
except Exception:
    ACTIVE_CONNECTORS = set()


@dataclass
class ComplianceProfile:
    """
    A compliance profile defines how a vendor/entity is screened for a
    specific vertical market or regulatory domain.

    Scoring configuration (factor weights, tier thresholds) is managed
    by fgamlogit.py, not here. This profile controls: entity labeling,
    program types, connector orchestration, hard stop rules, form fields,
    UI styling, and regulatory references.
    """
    id: str
    name: str
    description: str
    entity_label: str
    program_types: list[dict]
    connector_priority: list[str]
    connector_weights: dict
    hard_stop_rules: list[str]
    required_fields: list[str]
    optional_fields: list[dict]
    ui_config: dict = field(default_factory=dict)
    regulatory_references: list[dict] = field(default_factory=list)


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
        connector_priority=[
            "dod_sam_exclusions", "trade_csl", "ofac_sdn", "un_sanctions",
            "opensanctions_pep", "worldbank_debarred", "icij_offshore", "fara",
            "gdelt_media", "google_news", "sec_edgar", "sec_xbrl", "gleif_lei",
            "opencorporates", "uk_companies_house", "sam_gov", "usaspending",
            "fpds_contracts", "epa_echo", "osha_safety", "courtlistener",
            "fdic_bankfind",
        ],
        connector_weights={},
        hard_stop_rules=[
            "sanctions_match", "sanctioned_country_sensitive", "sanctioned_state_owned",
            "adversary_state_owned", "sectoral_state_weapons", "shell_depth", "opaque_high_risk",
        ],
        required_fields=["name", "country"],
        optional_fields=[
            {"id": "program", "label": "Program Type", "type": "select"},
            {"id": "cage_code", "label": "CAGE Code", "type": "text"},
            {"id": "duns", "label": "DUNS Number", "type": "text"},
        ],
        ui_config={
            "color": "#0052CC",
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
        connector_priority=[
            "trade_csl", "ofac_sdn", "un_sanctions", "eu_sanctions",
            "uk_hmt_sanctions", "dod_sam_exclusions", "opensanctions_pep",
            "worldbank_debarred", "sec_edgar", "sec_xbrl", "gleif_lei",
            "opencorporates", "uk_companies_house", "sam_gov", "usaspending",
            "fpds_contracts", "gdelt_media", "google_news", "fara",
        ],
        connector_weights={
            "ofac_sdn": 1.5,
            "trade_csl": 1.4,
            "un_sanctions": 1.5,
        },
        hard_stop_rules=[
            "sanctions_match", "sanctioned_country_sensitive", "sanctioned_state_owned",
            "adversary_state_owned", "sectoral_state_weapons",
        ],
        required_fields=["name", "country", "usml_category"],
        optional_fields=[
            {"id": "usml_category", "label": "USML Category", "type": "select"},
            {"id": "end_use_statement", "label": "End-Use Statement", "type": "textarea"},
            {"id": "intermediate_consignee", "label": "Intermediate Consignee", "type": "text"},
            {"id": "freight_forwarder", "label": "Freight Forwarder", "type": "text"},
            {"id": "license_type", "label": "License Type", "type": "select"},
        ],
        ui_config={
            "color": "#DC3545",
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
        connector_priority=[
            "opensanctions_pep", "ofac_sdn", "un_sanctions", "dod_sam_exclusions",
            "trade_csl", "worldbank_debarred", "icij_offshore", "fara",
            "gdelt_media", "google_news", "sec_edgar", "gleif_lei",
            "opencorporates", "courtlistener", "uk_companies_house",
        ],
        connector_weights={
            "opensanctions_pep": 1.6,
            "ofac_sdn": 1.4,
        },
        hard_stop_rules=[
            "sanctions_match", "sanctioned_country_sensitive", "sanctioned_state_owned",
            "adversary_state_owned",
        ],
        required_fields=["name", "country", "research_domain"],
        optional_fields=[
            {"id": "research_domain", "label": "Research Domain", "type": "select"},
            {"id": "home_institution", "label": "Home Institution", "type": "text"},
            {"id": "funding_source", "label": "Funding Source", "type": "text"},
            {"id": "visa_status", "label": "Visa Status", "type": "select"},
            {"id": "collaboration_type", "label": "Collaboration Type", "type": "select"},
        ],
        ui_config={
            "color": "#6F42C1",
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
        connector_priority=[
            "sam_gov", "usaspending", "fpds_contracts", "dod_sam_exclusions",
            "ofac_sdn", "un_sanctions", "trade_csl", "worldbank_debarred",
            "sec_edgar", "gleif_lei", "fdic_bankfind", "opencorporates",
            "courtlistener",
        ],
        connector_weights={
            "sam_gov": 1.8,
            "usaspending": 1.5,
        },
        hard_stop_rules=[
            "sanctions_match", "sanctioned_country_sensitive", "sanctioned_state_owned",
        ],
        required_fields=["name", "country"],
        optional_fields=[
            {"id": "uei_number", "label": "UEI Number", "type": "text"},
            {"id": "grant_program", "label": "Grant Program", "type": "select"},
            {"id": "award_amount", "label": "Award Amount", "type": "number"},
            {"id": "agency", "label": "Funding Agency", "type": "select"},
        ],
        ui_config={
            "color": "#20C997",
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
        connector_priority=[
            "ofac_sdn", "trade_csl", "dod_sam_exclusions", "un_sanctions",
            "sec_edgar", "sec_xbrl", "gleif_lei", "opencorporates", "epa_echo",
            "osha_safety", "uk_companies_house", "gdelt_media", "google_news",
            "worldbank_debarred", "courtlistener",
        ],
        connector_weights={
            "epa_echo": 1.3,
            "osha_safety": 1.2,
        },
        hard_stop_rules=[
            "sanctions_match", "sanctioned_country_sensitive", "sanctioned_state_owned",
        ],
        required_fields=["name", "country"],
        optional_fields=[
            {"id": "industry_sector", "label": "Industry Sector", "type": "select"},
            {"id": "product_category", "label": "Product Category", "type": "select"},
            {"id": "import_volume", "label": "Annual Import Volume", "type": "text"},
            {"id": "hs_code", "label": "HS Code(s)", "type": "text"},
        ],
        ui_config={
            "color": "#FFC107",
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


def get_connector_list(profile_id: str) -> Optional[list[str]]:
    """Return the ordered list of OSINT connectors for a profile."""
    profile = get_profile(profile_id)
    if not profile:
        return None
    if not ACTIVE_CONNECTORS:
        return profile.connector_priority
    return [name for name in profile.connector_priority if name in ACTIVE_CONNECTORS]


def validate_profile_id(profile_id: str) -> bool:
    """Check if a profile ID is valid."""
    return profile_id in PROFILES


def profile_to_dict(profile: ComplianceProfile) -> dict:
    """Convert a ComplianceProfile to a JSON-serializable dict."""
    connector_priority = profile.connector_priority
    connector_weights = profile.connector_weights
    if ACTIVE_CONNECTORS:
        connector_priority = [name for name in connector_priority if name in ACTIVE_CONNECTORS]
        connector_weights = {
            name: weight for name, weight in connector_weights.items()
            if name in ACTIVE_CONNECTORS
        }

    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "entity_label": profile.entity_label,
        "program_types": profile.program_types,
        "connector_priority": connector_priority,
        "connector_weights": connector_weights,
        "hard_stop_rules": profile.hard_stop_rules,
        "required_fields": profile.required_fields,
        "optional_fields": profile.optional_fields,
        "ui_config": profile.ui_config,
        "regulatory_references": profile.regulatory_references,
    }
