"""
Xiphos Compliance Profiles System

Canonical profile registry shared by the API, scoring, gate selection,
and connector orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

try:
    from osint.connector_registry import ACTIVE_CONNECTOR_NAMES
    ACTIVE_CONNECTORS = set(ACTIVE_CONNECTOR_NAMES)
except Exception:
    ACTIVE_CONNECTORS = set()


GATE_NAME_TO_ID = {
    "SECTION_889": 1,
    "ITAR": 2,
    "EAR": 3,
    "DFARS_SPECIALTY_METALS": 4,
    "DFARS_COVERED_DEFENSE_INFO": 5,
    "CMMC": 6,
    "FOCI": 7,
    "NDAA_1260H": 8,
    "CFIUS": 9,
    "BERRY_AMENDMENT": 10,
    "DEEMED_EXPORT": 11,
    "RED_FLAGS": 12,
    "USML_CONTROL": 13,
}

CANONICAL_GATES = tuple(GATE_NAME_TO_ID.keys())

CANONICAL_FACTORS = (
    "sanctions",
    "geography",
    "ownership",
    "data_quality",
    "executive",
    "regulatory_gate_proximity",
    "itar_exposure",
    "ear_control_status",
    "foreign_ownership_depth",
    "cmmc_readiness",
    "single_source_risk",
    "geopolitical_sector_exposure",
    "financial_stability",
    "compliance_history",
)

SENSITIVITY_TIERS = (
    "CRITICAL_SAP",
    "CRITICAL_SCI",
    "ELEVATED",
    "ENHANCED",
    "CONTROLLED",
    "STANDARD",
    "COMMERCIAL",
)

PROFILE_ID_TO_ENUM_NAME = {
    "defense_acquisition": "DEFENSE_ACQUISITION",
    "itar_trade_compliance": "ITAR_TRADE",
    "university_research_security": "UNIVERSITY_RESEARCH",
    "grants_compliance": "GRANTS_COMPLIANCE",
    "commercial_supply_chain": "COMMERCIAL_SUPPLY_CHAIN",
}

DEFAULT_PROFILE_ID = "defense_acquisition"


@dataclass(frozen=True)
class ComplianceProfile:
    """
    Canonical compliance profile definition.

    API/UI callers use the lower-case `id`. Legacy scorer and batch-screening
    callers can still resolve the matching `enum_name`.
    """

    id: str
    enum_name: str
    name: str
    description: str
    entity_label: str
    program_types: list[dict]
    connector_priority: list[str]
    connector_weights: dict
    hard_stop_rules: list[str]
    required_fields: list[str]
    optional_fields: list[dict]
    baseline_shift: float = 0.0
    weight_overrides: dict[str, float] = field(default_factory=dict)
    enabled_gate_names: tuple[str, ...] = field(default_factory=tuple)
    terminology_overrides: dict[str, str] = field(default_factory=dict)
    sensitivity_default: str = "COMMERCIAL"
    additional_hard_stops: list[str] = field(default_factory=list)
    ui_config: dict = field(default_factory=dict)
    regulatory_references: list[dict] = field(default_factory=list)

    @property
    def enabled_gate_ids(self) -> list[int]:
        return [
            GATE_NAME_TO_ID[name]
            for name in self.enabled_gate_names
            if name in GATE_NAME_TO_ID
        ]

    @property
    def enabled_gates(self) -> list[str]:
        return list(self.enabled_gate_names)

    @property
    def ui_labels(self) -> dict[str, str]:
        return dict(self.terminology_overrides)

    def __post_init__(self):
        unknown_gates = set(self.enabled_gate_names) - set(GATE_NAME_TO_ID)
        if unknown_gates:
            raise ValueError(f"Unknown gates for profile '{self.id}': {sorted(unknown_gates)}")
        if self.sensitivity_default not in SENSITIVITY_TIERS:
            raise ValueError(
                f"Invalid sensitivity_default '{self.sensitivity_default}' for profile '{self.id}'"
            )


PROFILES = {
    "defense_acquisition": ComplianceProfile(
        id="defense_acquisition",
        enum_name=PROFILE_ID_TO_ENUM_NAME["defense_acquisition"],
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
            "international_exhibitors_fixture",
            "dod_sam_exclusions", "trade_csl", "ofac_sdn", "un_sanctions",
            "opensanctions_pep", "worldbank_debarred", "icij_offshore", "fara",
            "gdelt_media", "google_news", "sec_edgar", "sec_xbrl", "gleif_lei",
            "gleif_bods_ownership_fixture",
            "openownership_bods_fixture",
            "openownership_bods_public",
            "opencorporates", "uk_companies_house", "corporations_canada", "australia_abn_asic", "singapore_acra", "new_zealand_companies_office", "norway_brreg", "netherlands_kvk", "france_inpi_rne", "sam_gov", "sam_subaward_reporting",
            "usaspending", "fpds_contracts", "epa_echo", "osha_safety",
            "courtlistener", "fdic_bankfind", "mitre_attack_fixture", "cisa_advisory_fixture",
            "cyclonedx_spdx_vex_fixture",
            "public_assurance_evidence_fixture",
            "osv_dev", "deps_dev", "openssf_scorecard",
        ],
        connector_weights={},
        hard_stop_rules=[
            "sanctions_match", "sanctioned_country_sensitive", "sanctioned_state_owned",
            "adversary_state_owned", "sectoral_state_weapons", "shell_depth",
            "opaque_high_risk",
        ],
        required_fields=["name", "country"],
        optional_fields=[
            {"id": "program", "label": "Program Type", "type": "select"},
            {"id": "cage_code", "label": "CAGE Code", "type": "text"},
            {"id": "duns", "label": "DUNS Number", "type": "text"},
        ],
        baseline_shift=0.0,
        weight_overrides={},
        enabled_gate_names=(
            "SECTION_889",
            "ITAR",
            "EAR",
            "DFARS_SPECIALTY_METALS",
            "DFARS_COVERED_DEFENSE_INFO",
            "CMMC",
            "FOCI",
            "NDAA_1260H",
            "CFIUS",
            "BERRY_AMENDMENT",
        ),
        terminology_overrides={},
        sensitivity_default="ELEVATED",
        additional_hard_stops=[],
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
        enum_name=PROFILE_ID_TO_ENUM_NAME["itar_trade_compliance"],
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
            "international_exhibitors_fixture",
            "trade_csl", "ofac_sdn", "un_sanctions", "eu_sanctions",
            "uk_hmt_sanctions", "dod_sam_exclusions", "opensanctions_pep",
            "worldbank_debarred", "sec_edgar", "sec_xbrl", "gleif_lei",
            "gleif_bods_ownership_fixture",
            "openownership_bods_fixture",
            "openownership_bods_public",
            "opencorporates", "uk_companies_house", "corporations_canada", "australia_abn_asic", "singapore_acra", "new_zealand_companies_office", "norway_brreg", "netherlands_kvk", "france_inpi_rne", "sam_gov",
            "sam_subaward_reporting", "usaspending", "fpds_contracts",
            "gdelt_media", "google_news", "fara", "mitre_attack_fixture", "cisa_advisory_fixture",
            "cyclonedx_spdx_vex_fixture",
            "public_assurance_evidence_fixture",
            "osv_dev", "deps_dev", "openssf_scorecard",
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
        baseline_shift=0.15,
        weight_overrides={
            "sanctions": 1.3,
            "geography": 1.5,
            "ownership": 1.2,
            "itar_exposure": 1.4,
            "foreign_ownership_depth": 1.3,
        },
        enabled_gate_names=(
            "SECTION_889",
            "ITAR",
            "EAR",
            "FOCI",
            "NDAA_1260H",
            "CFIUS",
            "DEEMED_EXPORT",
            "RED_FLAGS",
            "USML_CONTROL",
        ),
        terminology_overrides={
            "vendor": "foreign_party",
            "program": "defense_article_category",
            "item": "usml_classification",
            "supply_chain": "export_chain",
        },
        sensitivity_default="CRITICAL_SAP",
        additional_hard_stops=[
            "USML_CATEGORY_MISMATCH",
            "DEEMED_EXPORT_VIOLATION",
            "END_USE_RED_FLAG",
            "MILITARY_END_USER_FLAG",
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
        enum_name=PROFILE_ID_TO_ENUM_NAME["university_research_security"],
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
            "gleif_bods_ownership_fixture",
            "openownership_bods_fixture",
            "openownership_bods_public",
            "opencorporates", "courtlistener", "uk_companies_house", "corporations_canada", "australia_abn_asic", "singapore_acra", "new_zealand_companies_office", "norway_brreg", "netherlands_kvk", "france_inpi_rne",
            "mitre_attack_fixture", "cisa_advisory_fixture",
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
        baseline_shift=0.05,
        weight_overrides={
            "geography": 1.4,
            "ownership": 0.8,
            "compliance_history": 1.2,
        },
        enabled_gate_names=(
            "SECTION_889",
            "FOCI",
            "NDAA_1260H",
        ),
        terminology_overrides={
            "vendor": "collaborator",
            "program": "research_domain",
            "supply_chain": "research_institution_chain",
            "item": "research_technology_area",
        },
        sensitivity_default="ELEVATED",
        additional_hard_stops=[
            "TALENT_PROGRAM_MATCH",
            "PLA_AFFILIATED_INSTITUTION",
            "MILITARY_CIVIL_FUSION_FLAG",
            "FOREIGN_GOVERNMENT_OWNERSHIP",
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
        enum_name=PROFILE_ID_TO_ENUM_NAME["grants_compliance"],
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
            "sam_gov", "sam_subaward_reporting", "usaspending", "fpds_contracts",
            "dod_sam_exclusions", "ofac_sdn", "un_sanctions", "trade_csl",
            "worldbank_debarred", "sec_edgar", "gleif_lei", "gleif_bods_ownership_fixture", "openownership_bods_fixture", "openownership_bods_public", "corporations_canada", "australia_abn_asic", "singapore_acra", "new_zealand_companies_office", "norway_brreg", "netherlands_kvk", "france_inpi_rne", "fdic_bankfind",
            "opencorporates", "courtlistener", "mitre_attack_fixture", "cisa_advisory_fixture",
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
        baseline_shift=0.0,
        weight_overrides={
            "financial_stability": 1.3,
            "ownership": 0.7,
            "data_quality": 1.1,
        },
        enabled_gate_names=(
            "SECTION_889",
            "NDAA_1260H",
        ),
        terminology_overrides={
            "vendor": "sub_awardee",
            "program": "grant_program",
            "supply_chain": "sub_awardee_chain",
            "item": "award_type",
        },
        sensitivity_default="COMMERCIAL",
        additional_hard_stops=[
            "SAM_GOV_EXCLUSION",
            "FAPIIS_SUSPENSION",
            "FEDERAL_DEBARMENT",
            "DO_NOT_PAY_FLAG",
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
        enum_name=PROFILE_ID_TO_ENUM_NAME["commercial_supply_chain"],
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
            "sec_edgar", "sec_xbrl", "gleif_lei", "gleif_bods_ownership_fixture", "openownership_bods_fixture", "openownership_bods_public", "opencorporates", "corporations_canada", "australia_abn_asic", "singapore_acra", "new_zealand_companies_office", "norway_brreg", "netherlands_kvk", "france_inpi_rne", "epa_echo",
            "osha_safety", "uk_companies_house", "gdelt_media", "google_news",
            "worldbank_debarred", "courtlistener", "mitre_attack_fixture", "cisa_advisory_fixture", "cyclonedx_spdx_vex_fixture",
            "public_assurance_evidence_fixture",
            "osv_dev", "deps_dev", "openssf_scorecard",
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
        baseline_shift=0.0,
        weight_overrides={
            "financial_stability": 1.2,
            "sanctions": 0.9,
            "compliance_history": 1.3,
            "data_quality": 1.1,
        },
        enabled_gate_names=("SECTION_889",),
        terminology_overrides={
            "vendor": "supplier",
            "program": "product_category",
            "supply_chain": "supplier_chain",
            "item": "component_type",
        },
        sensitivity_default="COMMERCIAL",
        additional_hard_stops=[
            "PRODUCT_RECALL_FLAG",
            "ENVIRONMENTAL_VIOLATION",
            "LABOR_VIOLATION",
            "REACH_ROHS_VIOLATION",
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

PROFILE_ENUM_NAME_TO_ID = {
    profile.enum_name: profile.id
    for profile in PROFILES.values()
}
PROFILE_ENUM_TO_ID = dict(PROFILE_ENUM_NAME_TO_ID)


def normalize_profile_id(profile_ref: Optional[str]) -> str:
    text = str(profile_ref or "").strip()
    if not text:
        return DEFAULT_PROFILE_ID

    if text in PROFILES:
        return text

    lowered = text.lower()
    if lowered in PROFILES:
        return lowered

    upper = text.upper()
    if upper in PROFILE_ENUM_NAME_TO_ID:
        return PROFILE_ENUM_NAME_TO_ID[upper]

    return lowered


def resolve_profile_id(profile_ref: Optional[str]) -> str:
    normalized = normalize_profile_id(profile_ref)
    return normalized if normalized in PROFILES else DEFAULT_PROFILE_ID


def get_profile(profile_id: str) -> Optional[ComplianceProfile]:
    return PROFILES.get(normalize_profile_id(profile_id))


def list_profiles() -> list[ComplianceProfile]:
    return list(PROFILES.values())


def get_default_profile() -> ComplianceProfile:
    return PROFILES[DEFAULT_PROFILE_ID]


def get_connector_list(profile_id: str) -> Optional[list[str]]:
    profile = get_profile(profile_id)
    if not profile:
        return None
    if not ACTIVE_CONNECTORS:
        return profile.connector_priority
    return [name for name in profile.connector_priority if name in ACTIVE_CONNECTORS]


def get_enabled_gate_ids(profile_id: str) -> list[int]:
    profile = get_profile(profile_id)
    if not profile:
        return get_default_profile().enabled_gate_ids
    return profile.enabled_gate_ids


def get_sensitivity_default(profile_id: str) -> str:
    profile = get_profile(profile_id)
    if not profile:
        return get_default_profile().sensitivity_default
    return profile.sensitivity_default


def validate_profile_id(profile_id: str) -> bool:
    return normalize_profile_id(profile_id) in PROFILES


def get_active_gates(profile_id: str) -> list[str]:
    profile = get_profile(profile_id)
    if not profile:
        return get_default_profile().enabled_gates
    return profile.enabled_gates


def get_baseline_shift(profile_id: str) -> float:
    profile = get_profile(profile_id)
    if not profile:
        return get_default_profile().baseline_shift
    return profile.baseline_shift


def get_ui_labels(profile_id: str) -> dict[str, str]:
    profile = get_profile(profile_id)
    if not profile:
        return get_default_profile().ui_labels
    return profile.ui_labels


def get_hard_stops(profile_id: str) -> list[str]:
    profile = get_profile(profile_id)
    if not profile:
        return list(get_default_profile().additional_hard_stops)
    return list(profile.additional_hard_stops)


def get_priority_connectors(profile_id: str) -> list[str]:
    connector_list = get_connector_list(profile_id)
    if connector_list is not None:
        return connector_list
    return list(get_default_profile().connector_priority)


def get_profile_info(profile_id: str) -> dict:
    profile = get_profile(profile_id)
    if not profile:
        profile = get_default_profile()
    return {
        "name": profile.enum_name,
        "profile_id": profile.id,
        "display_name": profile.name,
        "description": profile.description,
        "gates": profile.enabled_gates,
        "connectors": get_priority_connectors(profile.id),
        "sensitivity_default": profile.sensitivity_default,
        "baseline_shift": profile.baseline_shift,
        "weight_overrides": dict(profile.weight_overrides),
        "ui_labels": profile.ui_labels,
        "hard_stops": list(profile.additional_hard_stops),
    }


def profile_to_dict(profile: ComplianceProfile) -> dict:
    connector_priority = profile.connector_priority
    connector_weights = profile.connector_weights
    if ACTIVE_CONNECTORS:
        connector_priority = [name for name in profile.connector_priority if name in ACTIVE_CONNECTORS]
        connector_weights = {
            name: weight
            for name, weight in profile.connector_weights.items()
            if name in ACTIVE_CONNECTORS
        }

    return {
        "id": profile.id,
        "enum_name": profile.enum_name,
        "name": profile.name,
        "description": profile.description,
        "entity_label": profile.entity_label,
        "program_types": profile.program_types,
        "connector_priority": connector_priority,
        "connector_weights": connector_weights,
        "hard_stop_rules": profile.hard_stop_rules,
        "required_fields": profile.required_fields,
        "optional_fields": profile.optional_fields,
        "enabled_gates": list(profile.enabled_gate_names),
        "enabled_gate_ids": profile.enabled_gate_ids,
        "sensitivity_default": profile.sensitivity_default,
        "baseline_shift": profile.baseline_shift,
        "weight_overrides": profile.weight_overrides,
        "additional_hard_stops": profile.additional_hard_stops,
        "terminology_overrides": profile.terminology_overrides,
        "ui_labels": profile.ui_labels,
        "ui_config": profile.ui_config,
        "regulatory_references": profile.regulatory_references,
    }
