"""
Amentum Contested Logistics Demo Case

Creates a realistic multi-vendor supply chain scenario for Amentum's
Center for Contested Logistics / USINDOPACOM mission.

Scenario: Amentum is standing up a forward-deployed sustainment hub in the
Western Pacific. They need to vet a supply chain of 8 vendors across:
  - Predictive maintenance electronics (EAR-controlled FPGAs / accelerators)
  - Maritime spares and repair parts (ITAR-controlled propulsion components)
  - Fuel and consumables (commercial, but routed through sanctioned corridors)
  - Cyber/network infrastructure (CMMC-scoped comms gear)

The demo surfaces:
  1. Counterparty lane: sanctions hits, adverse media, litigation, ownership opacity
  2. Export lane: ITAR/EAR classification, country tier analysis, deemed export triggers
  3. Cyber lane: CMMC readiness, NIST 800-171 gaps, supply chain cyber risk

Run:
    python demo_amentum_contested_logistics.py          # Creates the demo
    python demo_amentum_contested_logistics.py --clean  # Removes demo data
"""

import json
import sys
import logging
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Demo vendor definitions
# ---------------------------------------------------------------------------

DEMO_PROGRAM = "INDOPACOM Contested Logistics"
DEMO_PREFIX = "demo-amentum-"

VENDORS = [
    # ---- HIGH RISK: sanctions proximity + ownership opacity ----
    {
        "id": f"{DEMO_PREFIX}01-pacrim-maritime",
        "name": "PacRim Maritime Solutions Pte Ltd",
        "country": "SG",
        "profile": "defense_acquisition",
        "notes": "Singapore-registered maritime spares provider. Supplies propulsion seals, "
                 "shaft couplings, and diesel injector assemblies for DDG-class vessels. "
                 "Beneficial ownership traces to a Shenzhen-based holding company (Haiyun "
                 "Holdings Ltd) that also holds equity in a Myanmar-flagged shipping line "
                 "under OFAC advisory.",
        "export_authorization": {
            "jurisdiction_guess": "itar",
            "request_type": "physical_export",
            "destination_country": "SG",
            "classification_guess": "USML-XIII",
            "item_or_data_summary": "Gas turbine hot-section repair kits and propulsion shaft seals for DDG-51 class",
            "end_use_summary": "Forward depot stock for USINDOPACOM afloat sustainment",
            "access_context": "Vendor warehouse staff include PRC and Myanmar nationals",
            "foreign_person_nationalities": ["CN", "MM"],
        },
        "risk_tier": "critical",
        "demo_findings": {
            "sanctions": "Haiyun Holdings Ltd (UBO) appears on OFAC Sectoral Sanctions list (SSI); "
                         "Myanmar shipping subsidiary under OFAC General License 4 review",
            "ownership": "3-layer corporate structure: PacRim (SG) -> Haiyun Holdings (HK) -> "
                         "Shenzhen Haiyun Group (CN). Beneficial owner Chen Guowei holds 68% "
                         "through nominee arrangement",
            "adverse_media": "2024 Reuters investigation linked Haiyun fleet to sanctioned "
                             "Myanmar fuel transshipments",
            "litigation": "None found",
        },
    },
    # ---- HIGH RISK: deemed export + dual-use tech ----
    {
        "id": f"{DEMO_PREFIX}02-quantumleap-analytics",
        "name": "QuantumLeap Analytics Co., Ltd",
        "country": "TW",
        "profile": "defense_acquisition",
        "notes": "Taipei-based predictive maintenance analytics firm. Provides edge AI "
                 "accelerator boards and MerlinMx-compatible firmware for condition-based "
                 "maintenance on rotary-wing aircraft. Engineering team includes nationals "
                 "from PRC and Iran on H-1B equivalent visas.",
        "export_authorization": {
            "jurisdiction_guess": "ear",
            "request_type": "deemed_export",
            "destination_country": "TW",
            "classification_guess": "3A001",
            "item_or_data_summary": "Xilinx Versal AI Edge FPGA dev kits with DoD-specific firmware "
                                    "for predictive maintenance signal processing",
            "end_use_summary": "Integration into Amentum SupplyTrac / MerlinMx analytics pipeline "
                               "for UH-60 fleet health monitoring",
            "access_context": "Development team of 12 includes 3 PRC nationals and 1 Iranian "
                              "national with access to source code and hardware schematics",
            "foreign_person_nationalities": ["CN", "CN", "CN", "IR"],
        },
        "risk_tier": "high",
        "demo_findings": {
            "sanctions": "No direct SDN match. Iranian national Reza Mohammadi flagged on "
                         "BIS Entity List supplement (employer cross-reference)",
            "ownership": "Clean: 100% Taiwanese ownership, publicly traded on TWSE",
            "adverse_media": "2025 Nikkei Asia report on PRC talent recruitment programs "
                             "targeting Taiwanese semiconductor engineers",
            "deemed_export": "4 foreign nationals from controlled countries (3x CN, 1x IR) "
                             "with access to EAR 3A001 technology. Deemed export license "
                             "required under EAR 734.2(b)(2)(ii)",
        },
    },
    # ---- MODERATE RISK: CMMC gaps + cyber supply chain ----
    {
        "id": f"{DEMO_PREFIX}03-ironforge-cyber",
        "name": "IronForge Cyber Systems LLC",
        "country": "US",
        "profile": "defense_acquisition",
        "notes": "Virginia-based CMMC Level 2 candidate providing tactical mesh networking "
                 "equipment and encrypted logistics comms for forward-deployed sustainment "
                 "nodes. POA&M shows 14 open NIST 800-171 controls. Supplies radios that "
                 "handle CUI in transit.",
        "export_authorization": None,
        "risk_tier": "moderate",
        "demo_findings": {
            "sanctions": "Clean",
            "ownership": "Clean: US-owned, veteran-founded SDVOSB",
            "cmmc": "CMMC Level 2 assessment scheduled Q3 2026. Current POA&M has 14 open "
                    "controls including AC.L2-3.1.3 (CUI flow enforcement), SC.L2-3.13.11 "
                    "(FIPS-validated crypto), and IR.L2-3.6.1 (incident handling). Self-assessed "
                    "SPRS score: 68/110",
            "cyber_risk": "Uses Huawei-manufactured chipsets in 2 of 5 radio SKUs. Firmware "
                          "update pipeline routes through Hong Kong CDN. No SBOM provided for "
                          "embedded OS components",
        },
    },
    # ---- MODERATE RISK: country risk + transshipment ----
    {
        "id": f"{DEMO_PREFIX}04-palawan-fuel",
        "name": "Palawan Energy & Logistics Corp",
        "country": "PH",
        "profile": "standard_industrial",
        "notes": "Philippines-based fuel and consumables broker. Arranges JP-5 aviation fuel "
                 "and diesel marine fuel deliveries across Western Pacific. Uses subcontracted "
                 "tankers flagged in Liberia and Marshall Islands.",
        "export_authorization": {
            "jurisdiction_guess": "ear",
            "request_type": "physical_export",
            "destination_country": "PH",
            "classification_guess": "EAR99",
            "item_or_data_summary": "JP-5 aviation turbine fuel, F-76 diesel marine fuel (commercial grade)",
            "end_use_summary": "Fuel provisioning for USINDOPACOM forward-deployed assets, "
                               "including Amentum-managed fuel farms on Guam and Palau",
            "access_context": "Fuel delivery crews are Filipino and Liberian nationals",
            "foreign_person_nationalities": ["PH", "LR"],
        },
        "risk_tier": "moderate",
        "demo_findings": {
            "sanctions": "No direct hits. One subcontracted tanker (MV Oceanus Star, Marshall "
                         "Islands flag) was previously chartered by entity on UN Panel of Experts "
                         "DPRK sanctions watchlist (2023)",
            "ownership": "Philippine family office (Reyes Group) holds 85%. 15% held by undisclosed "
                         "offshore investor via BVI entity",
            "adverse_media": "2025 Philippine Daily Inquirer report on fuel adulteration "
                             "allegations in Subic Bay deliveries (subsequently cleared)",
            "transshipment": "Fuel routing through Kaohsiung, Taiwan and Busan, South Korea "
                             "creates potential diversion monitoring gap",
        },
    },
    # ---- LOW RISK: clean US prime sub ----
    {
        "id": f"{DEMO_PREFIX}05-cascade-defense",
        "name": "Cascade Defense Logistics Inc",
        "country": "US",
        "profile": "defense_acquisition",
        "notes": "Washington State SDVOSB providing warehousing, kitting, and last-mile "
                 "delivery for mil-spec spares. GSA Schedule holder. CMMC Level 2 certified. "
                 "Active SeaPort-NxG and DLA SOCOM Tailored Logistics Support (TLS) contracts.",
        "export_authorization": None,
        "risk_tier": "low",
        "demo_findings": {
            "sanctions": "Clean",
            "ownership": "Clean: 100% US veteran-owned. SAM.gov active, CAGE code verified",
            "cmmc": "CMMC Level 2 certified (C3PAO assessment completed Jan 2026). "
                    "SPRS score: 104/110. All POA&M items closed.",
            "litigation": "None. Clean FAPIIS record.",
        },
    },
    # ---- LOW RISK: allied nation partner ----
    {
        "id": f"{DEMO_PREFIX}06-komatsu-heavylift",
        "name": "Komatsu Heavy Lift & Transport KK",
        "country": "JP",
        "profile": "defense_acquisition",
        "notes": "Osaka-based heavy equipment and material handling provider. Supplies "
                 "container handling systems, portable cranes, and MHE for expeditionary "
                 "logistics nodes. Long-standing FMS relationship with US Army.",
        "export_authorization": {
            "jurisdiction_guess": "ear",
            "request_type": "physical_export",
            "destination_country": "JP",
            "classification_guess": "EAR99",
            "item_or_data_summary": "40-ton rough terrain container handler (commercial)",
            "end_use_summary": "Material handling at Amentum-operated forward logistics node, "
                               "Japan (Camp Zama / Yokosuka)",
            "access_context": "All personnel are Japanese nationals with existing DoD base access",
            "foreign_person_nationalities": ["JP"],
        },
        "risk_tier": "low",
        "demo_findings": {
            "sanctions": "Clean",
            "ownership": "Clean: publicly traded on TSE, majority Japanese institutional ownership",
            "adverse_media": "None relevant",
            "export": "EAR99 classification, Japan is Tier 1 country. No license required.",
        },
    },
    # ---- CRITICAL RISK: sanctions match + shell structure ----
    {
        "id": f"{DEMO_PREFIX}07-caspian-metals",
        "name": "Caspian Strategic Metals FZE",
        "country": "AE",
        "profile": "standard_industrial",
        "notes": "Dubai free zone entity supplying specialty alloys and corrosion-resistant "
                 "fasteners for maritime applications. Claims ISO 9001 but certificate issuer "
                 "is not ANAB-accredited. Pricing 40% below market.",
        "export_authorization": {
            "jurisdiction_guess": "ear",
            "request_type": "physical_export",
            "destination_country": "AE",
            "classification_guess": "1C002",
            "item_or_data_summary": "Inconel 718 and Hastelloy C-276 alloy fasteners and flanges",
            "end_use_summary": "Spare parts for seawater cooling systems on Navy auxiliary vessels",
            "access_context": "Vendor personnel are UAE, Iranian, and Russian nationals",
            "foreign_person_nationalities": ["AE", "IR", "RU"],
        },
        "risk_tier": "critical",
        "demo_findings": {
            "sanctions": "Director Farhad Nazari appears on OFAC SDN list (sanctions program: IRAN). "
                         "Company shares registered address with 3 other FZE entities previously "
                         "designated under E.O. 13846 (Iran petroleum sanctions)",
            "ownership": "Opaque: FZE structure with no public registry. Beneficial owner believed "
                         "to be Iranian national via nominee shareholder. Cross-references to "
                         "IRGC-affiliated procurement network (C4ADS research)",
            "adverse_media": "2025 Al Jazeera investigation on sanctions evasion through Dubai "
                             "free zones named Caspian Strategic Metals as a shell entity",
            "litigation": "US DOJ civil forfeiture action (Case 1:25-cv-04812) targeting assets "
                          "of affiliated entity in same free zone",
            "counterfeit_risk": "Below-market pricing + non-accredited ISO certificate are "
                                "strong indicators of counterfeit or diverted material",
        },
    },
    # ---- HIGH RISK: PRC military-civil fusion concern ----
    {
        "id": f"{DEMO_PREFIX}08-skybridge-satcom",
        "name": "SkyBridge SatCom (Shenzhen) Ltd",
        "country": "CN",
        "profile": "defense_acquisition",
        "notes": "Shenzhen-based satellite communications equipment manufacturer. Produces "
                 "low-cost VSAT terminals marketed for maritime logistics tracking. Multiple "
                 "PLA-affiliated research institutes listed as co-patent holders. Equipment "
                 "would provide real-time position data on US logistics movements.",
        "export_authorization": {
            "jurisdiction_guess": "ear",
            "request_type": "physical_export",
            "destination_country": "CN",
            "classification_guess": "5A001",
            "item_or_data_summary": "Ku-band VSAT terminals with AES-256 encryption for maritime "
                                    "asset tracking and logistics C2",
            "end_use_summary": "Real-time tracking of Amentum-managed logistics vessels and "
                               "container movements across Western Pacific",
            "access_context": "All engineering and manufacturing personnel are PRC nationals. "
                              "Factory located in Shenzhen SEZ adjacent to PLA Navy research campus",
            "foreign_person_nationalities": ["CN"],
        },
        "risk_tier": "critical",
        "demo_findings": {
            "sanctions": "On BIS Entity List (Supplement No. 4 to Part 744). License required "
                         "for all EAR items, presumption of denial. Parent company Shenzhen "
                         "Haiwei Technology Group on DOD 1260H Chinese Military Company list",
            "ownership": "State-influenced: 35% held by Shenzhen municipal investment fund, "
                         "20% by PLA-affiliated National University of Defense Technology spin-off",
            "adverse_media": "2025 CSIS report on PRC military-civil fusion in satellite comms. "
                             "Named as procurement front for PLA Strategic Support Force",
            "counterintelligence": "VSAT terminals would transmit position/logistics data through "
                                   "PRC-controlled ground stations. NCSC advisory (2025-041) warns "
                                   "against PRC-origin tracking equipment in DoD supply chains",
        },
    },
]

# Demo persons for person screening across the supply chain
DEMO_PERSONS = [
    {
        "name": "Chen Guowei",
        "nationalities": ["CN"],
        "employer": "Haiyun Holdings Ltd (UBO of PacRim Maritime)",
        "item_classification": "ITAR-USML-XIII",
        "case_id": f"{DEMO_PREFIX}01-pacrim-maritime",
        "role": "Beneficial owner, Shenzhen-based. Controls PacRim through nominee structure.",
    },
    {
        "name": "Reza Mohammadi",
        "nationalities": ["IR"],
        "employer": "QuantumLeap Analytics Co., Ltd",
        "item_classification": "EAR-3A001",
        "case_id": f"{DEMO_PREFIX}02-quantumleap-analytics",
        "role": "Senior FPGA Engineer, Iranian national. Access to controlled source code.",
    },
    {
        "name": "Dr. Li Xiuying",
        "nationalities": ["CN"],
        "employer": "QuantumLeap Analytics Co., Ltd",
        "item_classification": "EAR-3A001",
        "case_id": f"{DEMO_PREFIX}02-quantumleap-analytics",
        "role": "ML Research Lead, PRC national. Formerly at Tsinghua University AI Lab.",
    },
    {
        "name": "Farhad Nazari",
        "nationalities": ["IR"],
        "employer": "Caspian Strategic Metals FZE",
        "item_classification": "EAR-1C002",
        "case_id": f"{DEMO_PREFIX}07-caspian-metals",
        "role": "Director. Appears on OFAC SDN list (Iran sanctions program).",
    },
    {
        "name": "James Harrington",
        "nationalities": ["US"],
        "employer": "Cascade Defense Logistics Inc",
        "item_classification": "EAR99",
        "case_id": f"{DEMO_PREFIX}05-cascade-defense",
        "role": "VP Operations. US national, active Secret clearance. Clean record.",
    },
    {
        "name": "Yuki Tanaka",
        "nationalities": ["JP"],
        "employer": "Komatsu Heavy Lift & Transport KK",
        "item_classification": "EAR99",
        "case_id": f"{DEMO_PREFIX}06-komatsu-heavylift",
        "role": "Program Manager. Japanese national with DoD base access badge.",
    },
]


def _build_enrichment_report(vendor: dict) -> dict:
    """Build a full enrichment report matching the real enrichment schema.

    Produces rich findings with source, severity, title, detail, category,
    confidence, and connector fields so the dossier generator renders full
    content in all four chapters.
    """
    risk_tier = vendor["risk_tier"]
    vendor_name = vendor["name"]
    country = vendor["country"]

    risk_map = {"critical": "CRITICAL", "high": "HIGH", "moderate": "MODERATE", "low": "LOW"}
    overall_risk = risk_map.get(risk_tier, "UNKNOWN")

    # ------------------------------------------------------------------
    # Build per-vendor rich findings
    # ------------------------------------------------------------------
    finding_list = _get_rich_findings(vendor)

    # Add universal clear-check findings for audit completeness
    clear_checks = [
        {"source": "us_sam_exclusions", "severity": "info", "category": "debarment",
         "title": "SAM.gov Exclusions Check", "confidence": 1.0,
         "detail": f"No active exclusions found for {vendor_name} in SAM.gov EPLS database."},
        {"source": "us_debar_list", "severity": "info", "category": "debarment",
         "title": "Federal Debarment Check", "confidence": 1.0,
         "detail": f"No debarment or suspension records found across DoD, DoS, or DoE lists."},
        {"source": "interpol_notices", "severity": "info", "category": "law_enforcement",
         "title": "Interpol Red Notice Check", "confidence": 0.95,
         "detail": "No Interpol Red or Blue notices found for key personnel."},
        {"source": "eu_sanctions", "severity": "info", "category": "sanctions",
         "title": "EU Consolidated Sanctions Check", "confidence": 1.0,
         "detail": f"No matches for {vendor_name} on EU consolidated financial sanctions list."},
        {"source": "un_sanctions", "severity": "info", "category": "sanctions",
         "title": "UN Security Council Sanctions Check", "confidence": 1.0,
         "detail": f"No matches on UN Security Council consolidated list."},
    ]
    all_findings = finding_list + clear_checks

    severity_counts = {"critical": 0, "high": 0, "moderate": 0, "low": 0, "info": 0}
    for f in all_findings:
        sev = f.get("severity", "info").lower()
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    material_count = sum(severity_counts[s] for s in ("critical", "high", "moderate"))
    connectors_run = max(len(all_findings), 12)
    connectors_with_data = len([f for f in all_findings if f.get("severity") != "info"])

    return {
        "vendor_id": vendor["id"],
        "vendor_name": vendor_name,
        "overall_risk": overall_risk,
        "identifiers": {
            "name": vendor_name,
            "country": country,
            "program": DEMO_PROGRAM,
            "profile": vendor.get("profile", "defense_acquisition"),
        },
        "summary": {
            "findings_total": len(all_findings),
            "critical": severity_counts.get("critical", 0),
            "high": severity_counts.get("high", 0),
            "moderate": severity_counts.get("moderate", 0),
            "low": severity_counts.get("low", 0),
            "connectors_run": connectors_run,
            "connectors_with_data": connectors_with_data,
        },
        "findings": all_findings,
        "total_elapsed_ms": 4800 + (len(all_findings) * 320),
        "report_hash": uuid.uuid4().hex[:16],
    }


# ------------------------------------------------------------------
# Rich per-vendor findings
# ------------------------------------------------------------------

VENDOR_FINDINGS: dict[str, list[dict]] = {}

# PacRim Maritime Solutions Pte Ltd (SG) - CRITICAL
VENDOR_FINDINGS[f"{DEMO_PREFIX}01-pacrim-maritime"] = [
    {"source": "ofac_sdn", "severity": "critical", "category": "sanctions",
     "title": "OFAC Sectoral Sanctions Identification (SSI) - Beneficial Owner",
     "confidence": 0.92,
     "detail": "Haiyun Holdings Ltd, the ultimate beneficial owner of PacRim Maritime Solutions "
               "through a Hong Kong intermediary, appears on the OFAC Sectoral Sanctions "
               "Identifications (SSI) List under Directives 1 and 4. Haiyun is subject to "
               "prohibitions on new debt and equity transactions with US persons. A Myanmar-flagged "
               "shipping subsidiary (Oceanic Star Line Co.) is currently under OFAC General License "
               "4 review for sanctioned petroleum transshipments."},
    {"source": "corporate_registry", "severity": "high", "category": "ownership",
     "title": "Opaque Multi-Layer Corporate Structure with Nominee Arrangement",
     "confidence": 0.88,
     "detail": "PacRim Maritime Solutions Pte Ltd (Singapore UEN 201812345K) is a wholly-owned "
               "subsidiary of Haiyun Holdings Ltd (Hong Kong CR No. 2876543), which is in turn "
               "controlled by Shenzhen Haiyun Group Co., Ltd (USCC 91440300MA5F1234X8). Beneficial "
               "owner Chen Guowei holds 68% equity through a nominee shareholder arrangement "
               "registered in the British Virgin Islands. The nominee structure was identified "
               "through Singapore ACRA filings cross-referenced with Hong Kong Companies Registry."},
    {"source": "adverse_media", "severity": "high", "category": "adverse_media",
     "title": "Reuters Investigation Links UBO Fleet to Sanctioned Fuel Transshipments",
     "confidence": 0.85,
     "detail": "A 2024 Reuters investigative report titled 'Shadow Fleet: How Chinese shipping "
               "networks evade Myanmar sanctions' identified Haiyun Holdings' fleet as facilitating "
               "fuel deliveries to Myanmar military junta entities subject to US and EU sanctions. "
               "The report cited AIS tracking data showing 14 ship-to-ship transfers in the "
               "Andaman Sea between Haiyun-controlled tankers and Myanmar Navy auxiliaries between "
               "March and September 2024."},
    {"source": "country_risk", "severity": "moderate", "category": "jurisdiction",
     "title": "Singapore Jurisdiction - Elevated Transshipment Risk",
     "confidence": 0.80,
     "detail": "Singapore is a Tier 1 country under EAR but is a known transshipment hub for "
               "controlled goods destined for sanctioned end users. BIS has issued multiple "
               "Temporary Denial Orders involving Singapore-registered entities in the past 24 "
               "months. PacRim's warehouse operations in Jurong Port Industrial Zone are adjacent "
               "to free trade zone facilities with limited customs oversight."},
    {"source": "litigation_search", "severity": "low", "category": "litigation",
     "title": "No Active Litigation Found",
     "confidence": 0.90,
     "detail": "No civil or criminal litigation records found for PacRim Maritime Solutions Pte "
               "Ltd in Singapore Supreme Court, US federal courts (PACER), or UK Courts & "
               "Tribunals Service databases. Parent entity Haiyun Holdings has one archived "
               "commercial dispute in Hong Kong (HCA 2019/2847, settled 2020)."},
]

# QuantumLeap Analytics Co., Ltd (TW) - HIGH
VENDOR_FINDINGS[f"{DEMO_PREFIX}02-quantumleap-analytics"] = [
    {"source": "bis_entity_list", "severity": "critical", "category": "export_control",
     "title": "BIS Entity List Cross-Reference - Iranian National Employee",
     "confidence": 0.78,
     "detail": "Iranian national Reza Mohammadi, Senior FPGA Engineer at QuantumLeap Analytics, "
               "was previously employed by Pardis Technology Park (Tehran), which appears on the "
               "BIS Entity List (Supplement No. 4 to Part 744) under the Iran sanctions program. "
               "While Mohammadi himself is not listed, the prior employer association combined with "
               "his Iranian nationality creates a deemed export prohibition for EAR-controlled "
               "3A001 technology under Section 734.2(b)(2)(ii). License application would face "
               "presumption of denial for Iran-destination deemed exports."},
    {"source": "deemed_export_analysis", "severity": "high", "category": "export_control",
     "title": "Deemed Export Trigger - 4 Foreign Nationals from Controlled Countries",
     "confidence": 0.95,
     "detail": "QuantumLeap's 12-person development team includes 3 PRC nationals and 1 Iranian "
               "national with access to EAR 3A001 controlled technology (Xilinx Versal AI Edge "
               "FPGAs and associated firmware source code). Under EAR 734.2(b)(2)(ii), release of "
               "controlled technology to foreign nationals constitutes a deemed export to their "
               "home country. PRC nationals require a deemed export license for 3A001 items (China "
               "is subject to 3A001 controls for NS and AT reasons). The Iranian national triggers "
               "comprehensive embargo provisions. Combined, this creates a mandatory license "
               "requirement before any technology access is granted."},
    {"source": "adverse_media", "severity": "moderate", "category": "talent_recruitment",
     "title": "PRC Talent Recruitment Program Exposure - Nikkei Asia Report",
     "confidence": 0.72,
     "detail": "A 2025 Nikkei Asia report documented PRC state-sponsored talent recruitment "
               "programs (including the Thousand Talents Plan successor programs) actively "
               "targeting Taiwanese semiconductor engineers. While QuantumLeap Analytics is not "
               "named specifically, the report identifies FPGA design firms in the Hsinchu Science "
               "Park corridor as primary targets. Three of QuantumLeap's PRC-national engineers "
               "hold concurrent academic affiliations with mainland Chinese universities, which "
               "is a common indicator of talent program participation."},
    {"source": "corporate_registry", "severity": "low", "category": "ownership",
     "title": "Clean Ownership Structure - Publicly Traded",
     "confidence": 0.95,
     "detail": "QuantumLeap Analytics Co., Ltd (TWSE: 6789) is publicly traded on the Taiwan "
               "Stock Exchange with 100% Taiwanese institutional and retail ownership. No foreign "
               "government or state-owned enterprise holdings identified. Annual reports and "
               "corporate governance filings are current through Q4 2025."},
    {"source": "financial_analysis", "severity": "moderate", "category": "financial",
     "title": "Revenue Concentration Risk - Single Customer Dependency",
     "confidence": 0.70,
     "detail": "QuantumLeap derives approximately 62% of revenue from defense and government "
               "analytics contracts. Loss of US market access due to deemed export violations "
               "would materially impact financial viability, creating counterparty risk for "
               "long-term supply agreements."},
]

# IronForge Cyber Systems LLC (US) - MODERATE
VENDOR_FINDINGS[f"{DEMO_PREFIX}03-ironforge-cyber"] = [
    {"source": "cmmc_assessment", "severity": "high", "category": "cybersecurity",
     "title": "CMMC Level 2 Readiness Gap - 14 Open NIST 800-171 Controls",
     "confidence": 0.92,
     "detail": "IronForge Cyber Systems self-assessment shows a SPRS score of 68/110 with 14 "
               "open NIST 800-171 controls. Critical gaps include: AC.L2-3.1.3 (CUI flow "
               "enforcement - not implemented), SC.L2-3.13.11 (FIPS 140-2 validated cryptography "
               "- partially implemented with non-FIPS modules in two radio SKUs), IR.L2-3.6.1 "
               "(incident handling capability - documented but not tested), and AU.L2-3.3.1 "
               "(system-level auditing - incomplete on embedded systems). CMMC Level 2 C3PAO "
               "assessment is scheduled for Q3 2026, with Phase 2 enforcement beginning November "
               "2026. Current POA&M timeline shows 8 controls targeted for closure by June 2026 "
               "and remaining 6 by September 2026."},
    {"source": "supply_chain_cyber", "severity": "high", "category": "supply_chain",
     "title": "PRC-Origin Chipsets in Tactical Communications Equipment",
     "confidence": 0.88,
     "detail": "Hardware teardown analysis reveals that 2 of IronForge's 5 tactical mesh radio "
               "SKUs (models IF-MR200 and IF-MR200E) use Huawei HiSilicon Balong 711 baseband "
               "chipsets. These components are subject to NDAA Section 889 prohibitions on the "
               "use of covered telecommunications equipment by federal agencies and contractors. "
               "Additionally, the firmware update pipeline for these radios routes through a CDN "
               "hosted in Hong Kong (AS58453 - ChinaMobile International), creating a potential "
               "supply chain compromise vector. IronForge has not provided a Software Bill of "
               "Materials (SBOM) for the embedded real-time OS running on these chipsets."},
    {"source": "corporate_registry", "severity": "low", "category": "ownership",
     "title": "Clean US Ownership - Veteran-Founded SDVOSB",
     "confidence": 0.98,
     "detail": "IronForge Cyber Systems LLC is a verified Service-Disabled Veteran-Owned Small "
               "Business (SDVOSB) registered with SBA VetCert. 100% US-owned by founder and CEO "
               "Marcus Chen (former US Army Signal Corps, 15 years). SAM.gov registration active, "
               "CAGE code 8J4K2 verified. No foreign ownership, control, or influence (FOCI) "
               "indicators identified."},
    {"source": "contract_history", "severity": "low", "category": "past_performance",
     "title": "Active Federal Contract Portfolio",
     "confidence": 0.90,
     "detail": "IronForge holds 3 active federal contracts: DLA SOCOM TLS (W52P1J-22-D-0034, "
               "$4.2M ceiling), US Army PEO C3T tactical mesh pilot (W15QKN-24-C-0089, $1.8M), "
               "and a SBIR Phase II with DARPA (HR0011-23-C-0156, $750K). Past performance "
               "ratings available for 2 completed contracts show 'Satisfactory' and 'Very Good' "
               "in CPARS. No terminations for cause or default."},
]

# Palawan Energy & Logistics Corp (PH) - MODERATE
VENDOR_FINDINGS[f"{DEMO_PREFIX}04-palawan-fuel"] = [
    {"source": "vessel_screening", "severity": "moderate", "category": "sanctions",
     "title": "Subcontracted Tanker Previously Chartered by DPRK-Linked Entity",
     "confidence": 0.75,
     "detail": "MV Oceanus Star (IMO 9234567, Marshall Islands flag), a tanker subcontracted by "
               "Palawan Energy for JP-5 fuel deliveries, was previously chartered by Shenyang "
               "Marine Trading Co. in 2023. Shenyang Marine appeared in a 2023 UN Panel of "
               "Experts report (S/2023/171) as a suspected intermediary in DPRK petroleum "
               "sanctions evasion. The charter relationship ended in Q4 2023 and no subsequent "
               "DPRK-linked activity has been identified for the vessel. Current AIS tracking "
               "shows normal commercial operations in the Western Pacific."},
    {"source": "corporate_registry", "severity": "moderate", "category": "ownership",
     "title": "Partial Ownership Opacity - BVI Entity Holds 15% Stake",
     "confidence": 0.72,
     "detail": "Palawan Energy & Logistics Corp (SEC Philippines CR No. CS201809876) is 85% "
               "owned by the Reyes Group, a Philippine family office with verified beneficial "
               "ownership. However, 15% is held by Coral Bay Investments Ltd, a British Virgin "
               "Islands entity with no publicly available beneficial ownership information. BVI "
               "corporate registry does not disclose shareholders. The Reyes Group has stated "
               "that Coral Bay is an investment vehicle for a Singapore-based family office, but "
               "independent verification has not been possible."},
    {"source": "adverse_media", "severity": "low", "category": "adverse_media",
     "title": "Fuel Adulteration Allegations - Subsequently Cleared",
     "confidence": 0.65,
     "detail": "A 2025 Philippine Daily Inquirer article reported allegations of JP-5 fuel "
               "adulteration at Palawan Energy's Subic Bay storage facility. The Philippine "
               "Department of Energy conducted an investigation and cleared Palawan Energy of "
               "all allegations in a finding issued June 2025. Fuel quality testing results "
               "met all MIL-DTL-5624 specifications."},
    {"source": "transshipment_analysis", "severity": "moderate", "category": "diversion",
     "title": "Fuel Routing Creates Potential Diversion Monitoring Gap",
     "confidence": 0.70,
     "detail": "Palawan Energy's standard fuel delivery routing passes through Kaohsiung (Taiwan) "
               "and Busan (South Korea) prior to final delivery to Amentum-managed fuel farms on "
               "Guam and Palau. Each transshipment point creates a potential diversion opportunity "
               "where fuel quantities could be redirected to unauthorized end users. Current "
               "monitoring relies on commercial bills of lading and port manifests, which are "
               "subject to manipulation. Continuous AIS tracking of tanker movements is "
               "recommended to close this gap."},
]

# Cascade Defense Logistics Inc (US) - LOW
VENDOR_FINDINGS[f"{DEMO_PREFIX}05-cascade-defense"] = [
    {"source": "cmmc_assessment", "severity": "low", "category": "cybersecurity",
     "title": "CMMC Level 2 Certified - All Controls Closed",
     "confidence": 0.98,
     "detail": "Cascade Defense Logistics achieved CMMC Level 2 certification via C3PAO "
               "assessment completed January 2026 (Certificate No. CMMC-2026-04821). SPRS "
               "score: 104/110. All POA&M items from the assessment have been closed. The 6 "
               "remaining points relate to optional enhanced controls beyond the Level 2 baseline. "
               "Annual surveillance assessment scheduled for January 2027."},
    {"source": "corporate_registry", "severity": "low", "category": "ownership",
     "title": "Verified US Veteran-Owned - SAM.gov Active",
     "confidence": 0.99,
     "detail": "Cascade Defense Logistics Inc is a verified SDVOSB (SBA VetCert No. VET-2021-"
               "09234). 100% owned by James Harrington, US Army veteran (retired O-5). SAM.gov "
               "registration active through March 2027. CAGE code 5R2M7 verified. DUNS: "
               "08-765-4321. No FOCI indicators. FAPIIS record clean with zero administrative "
               "agreements, terminations, or deficiency reports."},
    {"source": "contract_history", "severity": "low", "category": "past_performance",
     "title": "Strong Federal Past Performance",
     "confidence": 0.95,
     "detail": "Active contracts include GSA Schedule (GS-07F-0345Y), DLA SOCOM Tailored "
               "Logistics Support (SPE4AX-23-D-0078, $8.5M ceiling), and SeaPort-NxG "
               "(N00178-22-D-4321). CPARS ratings across 5 completed contracts average "
               "'Very Good' with one 'Exceptional' rating on a USSOCOM kitting contract. "
               "No delinquent deliveries or quality deficiency reports."},
]

# Komatsu Heavy Lift & Transport KK (JP) - LOW
VENDOR_FINDINGS[f"{DEMO_PREFIX}06-komatsu-heavylift"] = [
    {"source": "export_classification", "severity": "low", "category": "export_control",
     "title": "EAR99 Classification - No License Required",
     "confidence": 0.95,
     "detail": "40-ton rough terrain container handler is classified EAR99 (commercial item, "
               "not on the Commerce Control List). Japan is a Country Group A:1 (Wassenaar "
               "Arrangement, Australia Group, MTCR, NSG). No license required for export or "
               "reexport of EAR99 items to Japan. FMS relationship with US Army established "
               "since 2008 with active Security Assistance agreements."},
    {"source": "corporate_registry", "severity": "low", "category": "ownership",
     "title": "Clean Ownership - Publicly Traded on TSE",
     "confidence": 0.98,
     "detail": "Komatsu Heavy Lift & Transport KK (TSE: 6305) is a publicly traded subsidiary "
               "of Komatsu Ltd, one of Japan's largest industrial equipment manufacturers. "
               "Majority Japanese institutional ownership. No foreign government holdings "
               "identified. Corporate governance meets Tokyo Stock Exchange Prime Market "
               "requirements."},
    {"source": "sanctions_screening", "severity": "low", "category": "sanctions",
     "title": "Clean Sanctions Screening",
     "confidence": 1.0,
     "detail": "No matches on OFAC SDN, Sectoral Sanctions, Non-SDN Menu-Based Sanctions, or "
               "BIS Entity/Denied Persons/Unverified lists. No matches on Japanese METI export "
               "control end-user lists. Clean across all 7 US, EU, UK, and UN sanctions databases."},
]

# Caspian Strategic Metals FZE (AE) - CRITICAL
VENDOR_FINDINGS[f"{DEMO_PREFIX}07-caspian-metals"] = [
    {"source": "ofac_sdn", "severity": "critical", "category": "sanctions",
     "title": "OFAC SDN Match - Company Director Farhad Nazari",
     "confidence": 0.97,
     "detail": "Director Farhad Nazari (DOB: 1974-03-15, Iranian passport M12345678) appears on "
               "the OFAC Specially Designated Nationals (SDN) list under the Iran sanctions "
               "program (E.O. 13599, E.O. 13846). SDN entry ID: NAZARI, Farhad [IRAN]. "
               "Associated with Iranian procurement networks targeting specialty metals and "
               "alloys for defense applications. Any transaction involving Nazari or entities "
               "he controls is prohibited for US persons under 31 CFR Part 560. Caspian Strategic "
               "Metals FZE is 50%-or-more owned or controlled by Nazari, making the entity itself "
               "blocked under OFAC's 50 Percent Rule."},
    {"source": "ofac_address_crossref", "severity": "critical", "category": "sanctions",
     "title": "Shared Registered Address with Previously Designated Entities",
     "confidence": 0.90,
     "detail": "Caspian Strategic Metals FZE is registered at Office 1204, Al Shafar Tower 1, "
               "Barsha Heights (TECOM), Dubai, UAE. OFAC records show that three other free zone "
               "entities previously designated under E.O. 13846 (Iran petroleum sanctions) shared "
               "this exact registered address: Petro Gulf Trading FZE (designated 2023-04-12), "
               "Caspian Commodities DMCC (designated 2023-04-12), and Golden Horizon Metals FZE "
               "(designated 2024-01-18). The concentration of designated entities at a single "
               "address is a strong indicator of a coordinated procurement network."},
    {"source": "corporate_registry", "severity": "high", "category": "ownership",
     "title": "Opaque FZE Structure - Nominee Shareholder, Iranian UBO",
     "confidence": 0.85,
     "detail": "Caspian Strategic Metals FZE is registered in the Dubai Technology and Media "
               "Free Zone (DTMFZ) under license number FZ-2022-87654. Dubai free zone entities "
               "have no public beneficial ownership registry. Corporate documents filed with DTMFZ "
               "list a UAE national (Mohammed Al-Rashidi) as the sole shareholder of record, but "
               "C4ADS network analysis and financial intelligence indicate that Farhad Nazari "
               "(Iranian national, OFAC SDN listed) is the actual beneficial owner operating "
               "through a nominee arrangement. Al-Rashidi appears as a nominee shareholder for "
               "at least 4 other FZE entities in the same free zone."},
    {"source": "adverse_media", "severity": "high", "category": "adverse_media",
     "title": "Al Jazeera Investigation - Named as Sanctions Evasion Shell Entity",
     "confidence": 0.82,
     "detail": "A 2025 Al Jazeera investigative documentary titled 'Dubai's Shadow Trade: How "
               "Iran Evades Western Sanctions' specifically named Caspian Strategic Metals FZE as "
               "a shell entity used to procure specialty alloys and corrosion-resistant materials "
               "for the Iranian defense industry. The investigation included leaked internal "
               "documents showing invoices routed through Turkish intermediaries before reaching "
               "end users at Isfahan Steel Complex, which is involved in Iran's ballistic missile "
               "program. The documentary aired in February 2025 and has been cited in subsequent "
               "Congressional testimony."},
    {"source": "litigation_search", "severity": "high", "category": "litigation",
     "title": "US DOJ Civil Forfeiture Action - Affiliated Entity",
     "confidence": 0.88,
     "detail": "The US Department of Justice filed a civil forfeiture complaint (Case No. "
               "1:25-cv-04812-JPO, SDNY) in March 2025 targeting $2.7 million in assets held "
               "by Golden Horizon Metals FZE, an entity at the same Dubai address as Caspian "
               "Strategic Metals. The complaint alleges that Golden Horizon was used to facilitate "
               "procurement of controlled commodities for Iranian end users in violation of IEEPA "
               "and ITSR. The forfeiture action names Farhad Nazari as a person of interest in "
               "the underlying investigation."},
    {"source": "counterfeit_indicators", "severity": "moderate", "category": "supply_chain",
     "title": "Below-Market Pricing and Non-Accredited ISO Certificate",
     "confidence": 0.78,
     "detail": "Caspian Strategic Metals quotes Inconel 718 fasteners and Hastelloy C-276 flanges "
               "at prices 38-42% below current market rates for certified aerospace-grade material. "
               "The company's ISO 9001:2015 certificate (Certificate No. QMS-2023-AE-4567) was "
               "issued by 'Global Quality Certifications FZE,' which is not accredited by ANAB, "
               "UKAS, or any IAF member accreditation body. These are strong indicators of "
               "counterfeit, substandard, or diverted material. The combination of below-market "
               "pricing and non-accredited quality certification has been identified by GIDEP as "
               "a primary counterfeit risk indicator for specialty alloys."},
]

# SkyBridge SatCom (Shenzhen) Ltd (CN) - CRITICAL
VENDOR_FINDINGS[f"{DEMO_PREFIX}08-skybridge-satcom"] = [
    {"source": "bis_entity_list", "severity": "critical", "category": "export_control",
     "title": "BIS Entity List - License Required, Presumption of Denial",
     "confidence": 0.98,
     "detail": "SkyBridge SatCom (Shenzhen) Ltd appears on the BIS Entity List (Supplement No. 4 "
               "to Part 744) effective March 2024. All exports, reexports, and transfers of EAR "
               "items to SkyBridge require a BIS license with a presumption of denial. The listing "
               "cites 'activities contrary to the national security and foreign policy interests "
               "of the United States' including procurement of dual-use satellite communications "
               "technology for PLA end users."},
    {"source": "dod_1260h", "severity": "critical", "category": "military_affiliation",
     "title": "DOD 1260H Chinese Military Company List - Parent Entity",
     "confidence": 0.95,
     "detail": "SkyBridge SatCom's parent company, Shenzhen Haiwei Technology Group, appears on "
               "the Department of Defense Section 1260H list of Chinese Military Companies "
               "(published June 2025). Entities on this list are identified as operating in the "
               "defense and related materiel sector or surveillance technology sector of the PRC. "
               "US persons are prohibited from engaging in securities transactions involving "
               "Haiwei Technology Group under E.O. 14032."},
    {"source": "corporate_registry", "severity": "high", "category": "ownership",
     "title": "State-Influenced Ownership - PLA University Equity Stake",
     "confidence": 0.90,
     "detail": "SkyBridge SatCom ownership structure: 35% held by Shenzhen Municipal Science & "
               "Technology Innovation Investment Fund (state-owned), 20% held by Nudt Innovation "
               "Technology Co. Ltd (a spin-off of the National University of Defense Technology, "
               "which is directly subordinate to the PLA Central Military Commission), 30% held "
               "by Shenzhen Haiwei Technology Group (DOD 1260H listed), and 15% by individual "
               "PRC national investors. The combined state and military ownership exceeds 85%, "
               "making this entity effectively a PRC government-controlled enterprise with direct "
               "PLA affiliation."},
    {"source": "counterintelligence", "severity": "critical", "category": "counterintelligence",
     "title": "NCSC Advisory - PRC-Origin Tracking Equipment in DoD Supply Chains",
     "confidence": 0.93,
     "detail": "NCSC Advisory 2025-041 (published September 2025) specifically warns against "
               "the use of PRC-manufactured satellite tracking and positioning equipment in US "
               "Department of Defense logistics and supply chain operations. The advisory states "
               "that VSAT terminals manufactured by PRC entities transmit telemetry data through "
               "ground stations operated by PRC state-owned telecommunications companies, creating "
               "a persistent intelligence collection opportunity. SkyBridge's Ku-band VSAT "
               "terminals would transmit real-time position and logistics data on Amentum-managed "
               "vessels and container movements to ground stations in Shenzhen and Hainan, both "
               "locations with significant PLA signals intelligence infrastructure."},
    {"source": "adverse_media", "severity": "moderate", "category": "military_civil_fusion",
     "title": "CSIS Report - PRC Military-Civil Fusion in Satellite Communications",
     "confidence": 0.85,
     "detail": "A 2025 Center for Strategic and International Studies (CSIS) report titled "
               "'Tracking the Trackers: PRC Military-Civil Fusion in Commercial Satellite "
               "Communications' identifies SkyBridge SatCom as one of 12 Shenzhen-based companies "
               "with documented links between commercial satellite communications products and PLA "
               "Strategic Support Force procurement programs. The report notes that 4 of "
               "SkyBridge's 7 active patents list co-inventors affiliated with PLA research "
               "institutes."},
]


def _get_rich_findings(vendor: dict) -> list[dict]:
    """Return pre-built rich findings for a vendor, or generate generic ones."""
    vid = vendor["id"]
    if vid in VENDOR_FINDINGS:
        return VENDOR_FINDINGS[vid]

    # Fallback: build from demo_findings text
    findings = vendor.get("demo_findings", {})
    risk_tier = vendor["risk_tier"]
    result = []
    for category, detail in findings.items():
        if not detail or detail == "Clean" or str(detail).startswith("None"):
            continue
        if category in ("sanctions", "counterintelligence") and risk_tier in ("critical", "high"):
            sev = "critical"
        elif category in ("ownership", "deemed_export", "cyber_risk", "counterfeit_risk"):
            sev = "high"
        elif category in ("adverse_media", "cmmc", "transshipment"):
            sev = "moderate"
        else:
            sev = "low"
        result.append({
            "source": f"xiphos_{category}",
            "severity": sev,
            "category": category,
            "title": f"{category.replace('_', ' ').title()} Finding",
            "detail": detail,
            "confidence": 0.80,
        })
    return result


def _build_scoring_result(vendor: dict) -> dict:
    """Build a full FGAMLogit scoring result with contributions for the dossier."""
    risk_tier = vendor["risk_tier"]

    tier_config = {
        "critical": {
            "composite_score": 92,
            "calibrated_probability": 0.89,
            "calibrated_tier": "BLOCKED_CRITICAL",
            "is_hard_stop": True,
            "interval": {"lower": 0.82, "upper": 0.95, "coverage": 0.90},
        },
        "high": {
            "composite_score": 74,
            "calibrated_probability": 0.68,
            "calibrated_tier": "ELEVATED_REVIEW",
            "is_hard_stop": False,
            "interval": {"lower": 0.58, "upper": 0.78, "coverage": 0.90},
        },
        "moderate": {
            "composite_score": 48,
            "calibrated_probability": 0.38,
            "calibrated_tier": "CONDITIONAL_REVIEW",
            "is_hard_stop": False,
            "interval": {"lower": 0.28, "upper": 0.48, "coverage": 0.90},
        },
        "low": {
            "composite_score": 18,
            "calibrated_probability": 0.12,
            "calibrated_tier": "APPROVED_LOW",
            "is_hard_stop": False,
            "interval": {"lower": 0.06, "upper": 0.19, "coverage": 0.90},
        },
    }

    cfg = tier_config.get(risk_tier, tier_config["moderate"])
    contributions = _build_contributions(vendor)

    return {
        "composite_score": cfg["composite_score"],
        "calibrated_probability": cfg["calibrated_probability"],
        "calibrated_tier": cfg["calibrated_tier"],
        "is_hard_stop": cfg["is_hard_stop"],
        "calibration": {
            "calibrated_probability": cfg["calibrated_probability"],
            "calibrated_tier": cfg["calibrated_tier"],
            "interval": cfg["interval"],
            "contributions": contributions,
        },
        "factors": _build_factor_breakdown(vendor),
        "gate_results": _build_gate_results(vendor),
    }


def _build_contributions(vendor: dict) -> list[dict]:
    """Build signed factor contributions for the scoring breakdown chart."""
    risk_tier = vendor["risk_tier"]
    findings = vendor.get("demo_findings", {})

    # Base contribution profiles per tier
    if risk_tier == "critical":
        return [
            {"factor": "sanctions_screening", "raw_score": 0.95, "confidence": 0.95,
             "signed_contribution": 0.28,
             "description": "Direct SDN or Entity List match detected"},
            {"factor": "ownership_transparency", "raw_score": 0.85, "confidence": 0.88,
             "signed_contribution": 0.22,
             "description": "Opaque or nominee ownership structure"},
            {"factor": "adverse_media_signal", "raw_score": 0.75, "confidence": 0.82,
             "signed_contribution": 0.15,
             "description": "Investigative journalism or government reports"},
            {"factor": "country_jurisdiction_risk", "raw_score": 0.70, "confidence": 0.90,
             "signed_contribution": 0.12,
             "description": "Elevated jurisdiction or transshipment risk"},
            {"factor": "financial_anomaly", "raw_score": 0.60, "confidence": 0.70,
             "signed_contribution": 0.08,
             "description": "Pricing or financial pattern anomalies"},
            {"factor": "litigation_exposure", "raw_score": 0.50, "confidence": 0.75,
             "signed_contribution": 0.05,
             "description": "Active or recent enforcement actions"},
            {"factor": "past_performance", "raw_score": 0.10, "confidence": 0.50,
             "signed_contribution": -0.02,
             "description": "Limited or no federal past performance"},
        ]
    elif risk_tier == "high":
        return [
            {"factor": "export_control_risk", "raw_score": 0.80, "confidence": 0.90,
             "signed_contribution": 0.22,
             "description": "Deemed export triggers or controlled classification"},
            {"factor": "personnel_screening", "raw_score": 0.75, "confidence": 0.85,
             "signed_contribution": 0.18,
             "description": "Foreign nationals from controlled countries"},
            {"factor": "adverse_media_signal", "raw_score": 0.55, "confidence": 0.72,
             "signed_contribution": 0.10,
             "description": "Talent recruitment or technology transfer concerns"},
            {"factor": "country_jurisdiction_risk", "raw_score": 0.40, "confidence": 0.80,
             "signed_contribution": 0.08,
             "description": "Allied country but elevated personnel risk"},
            {"factor": "ownership_transparency", "raw_score": 0.15, "confidence": 0.95,
             "signed_contribution": -0.05,
             "description": "Transparent public ownership verified"},
            {"factor": "financial_stability", "raw_score": 0.30, "confidence": 0.70,
             "signed_contribution": 0.06,
             "description": "Revenue concentration risk"},
        ]
    elif risk_tier == "moderate":
        return [
            {"factor": "cybersecurity_posture", "raw_score": 0.55, "confidence": 0.88,
             "signed_contribution": 0.14,
             "description": "CMMC gaps or NIST 800-171 open controls"},
            {"factor": "supply_chain_integrity", "raw_score": 0.50, "confidence": 0.80,
             "signed_contribution": 0.10,
             "description": "Component origin or firmware supply chain concerns"},
            {"factor": "country_jurisdiction_risk", "raw_score": 0.30, "confidence": 0.75,
             "signed_contribution": 0.06,
             "description": "Moderate jurisdiction risk or transshipment exposure"},
            {"factor": "ownership_transparency", "raw_score": 0.25, "confidence": 0.80,
             "signed_contribution": 0.04,
             "description": "Minor ownership opacity or offshore elements"},
            {"factor": "sanctions_screening", "raw_score": 0.10, "confidence": 0.95,
             "signed_contribution": -0.03,
             "description": "No direct sanctions matches"},
            {"factor": "past_performance", "raw_score": 0.20, "confidence": 0.85,
             "signed_contribution": -0.04,
             "description": "Satisfactory federal contract history"},
        ]
    else:  # low
        return [
            {"factor": "sanctions_screening", "raw_score": 0.05, "confidence": 0.98,
             "signed_contribution": -0.08,
             "description": "Clean across all sanctions databases"},
            {"factor": "ownership_transparency", "raw_score": 0.05, "confidence": 0.99,
             "signed_contribution": -0.06,
             "description": "Fully transparent US ownership verified"},
            {"factor": "past_performance", "raw_score": 0.10, "confidence": 0.95,
             "signed_contribution": -0.05,
             "description": "Strong federal past performance record"},
            {"factor": "cybersecurity_posture", "raw_score": 0.10, "confidence": 0.92,
             "signed_contribution": -0.04,
             "description": "CMMC certified or strong security posture"},
            {"factor": "country_jurisdiction_risk", "raw_score": 0.05, "confidence": 0.95,
             "signed_contribution": -0.03,
             "description": "US or allied nation, low jurisdiction risk"},
            {"factor": "financial_stability", "raw_score": 0.15, "confidence": 0.80,
             "signed_contribution": 0.02,
             "description": "Small business scale factor"},
        ]


def _build_factor_breakdown(vendor: dict) -> list:
    """Build FGAMLogit factor breakdown for demo scoring."""
    risk_tier = vendor["risk_tier"]
    findings = vendor.get("demo_findings", {})
    factors = []

    # Sanctions factor
    sanctions_detail = findings.get("sanctions", "Clean")
    if "SDN" in sanctions_detail or "Entity List" in sanctions_detail:
        factors.append({"name": "sanctions_screening", "score": 95, "weight": 0.25,
                        "detail": "Direct SDN/Entity List match"})
    elif "advisory" in sanctions_detail.lower() or "watchlist" in sanctions_detail.lower():
        factors.append({"name": "sanctions_screening", "score": 55, "weight": 0.25,
                        "detail": "Indirect sanctions exposure via related entity"})
    else:
        factors.append({"name": "sanctions_screening", "score": 5, "weight": 0.25,
                        "detail": "No sanctions matches found"})

    # Ownership factor
    ownership_detail = findings.get("ownership", "Clean")
    if "opaque" in ownership_detail.lower() or "nominee" in ownership_detail.lower():
        factors.append({"name": "ownership_transparency", "score": 85, "weight": 0.20,
                        "detail": "Opaque or nominee ownership structure"})
    elif "offshore" in ownership_detail.lower() or "undisclosed" in ownership_detail.lower():
        factors.append({"name": "ownership_transparency", "score": 55, "weight": 0.20,
                        "detail": "Partial ownership opacity"})
    else:
        factors.append({"name": "ownership_transparency", "score": 10, "weight": 0.20,
                        "detail": "Transparent ownership verified"})

    # Adverse media factor
    media_detail = findings.get("adverse_media", "")
    if "investigation" in media_detail.lower() or "evasion" in media_detail.lower():
        factors.append({"name": "adverse_media", "score": 75, "weight": 0.15,
                        "detail": "Significant adverse media findings"})
    elif media_detail and media_detail != "None relevant":
        factors.append({"name": "adverse_media", "score": 40, "weight": 0.15,
                        "detail": "Minor adverse media mentions"})
    else:
        factors.append({"name": "adverse_media", "score": 5, "weight": 0.15,
                        "detail": "No significant adverse media"})

    # Country risk factor
    country = vendor["country"]
    country_risk = {
        "CN": 80, "IR": 90, "RU": 85, "MM": 75, "AE": 50,
        "SG": 25, "PH": 35, "TW": 20, "JP": 10, "US": 5,
    }
    score = country_risk.get(country, 30)
    factors.append({"name": "country_risk", "score": score, "weight": 0.15,
                    "detail": f"Country risk assessment for {country}"})

    # Financial / contract risk
    if risk_tier == "critical":
        factors.append({"name": "financial_risk", "score": 70, "weight": 0.10,
                        "detail": "Below-market pricing or financial anomalies"})
    elif risk_tier == "high":
        factors.append({"name": "financial_risk", "score": 45, "weight": 0.10,
                        "detail": "Limited financial transparency"})
    else:
        factors.append({"name": "financial_risk", "score": 15, "weight": 0.10,
                        "detail": "Standard financial posture"})

    # Regulatory compliance
    cmmc = findings.get("cmmc", "")
    if cmmc and "open controls" in cmmc.lower():
        factors.append({"name": "regulatory_compliance", "score": 55, "weight": 0.15,
                        "detail": f"CMMC gaps: {cmmc[:80]}"})
    elif cmmc and "certified" in cmmc.lower():
        factors.append({"name": "regulatory_compliance", "score": 10, "weight": 0.15,
                        "detail": "CMMC Level 2 certified"})
    else:
        factors.append({"name": "regulatory_compliance", "score": 25, "weight": 0.15,
                        "detail": "Standard regulatory posture"})

    return factors


def _build_gate_results(vendor: dict) -> list:
    """Build gate check results for demo scoring."""
    findings = vendor.get("demo_findings", {})
    gates = []

    # Sanctions gate
    sanctions_detail = findings.get("sanctions", "Clean")
    is_sdn = "SDN" in sanctions_detail or "Entity List" in sanctions_detail
    gates.append({
        "gate": "SANCTIONS_SCREENING",
        "passed": not is_sdn,
        "detail": "SDN/Entity List match detected" if is_sdn else "No prohibited party matches",
        "is_hard_stop": is_sdn,
    })

    # Debarment gate
    gates.append({
        "gate": "DEBARMENT_CHECK",
        "passed": True,
        "detail": "No federal debarment records found",
        "is_hard_stop": False,
    })

    # Country restrictions gate
    country = vendor["country"]
    embargoed = country in ("IR", "KP", "CU", "SY", "RU")
    gates.append({
        "gate": "COUNTRY_RESTRICTIONS",
        "passed": not embargoed,
        "detail": f"Comprehensive embargo applies to {country}" if embargoed else f"{country} not under comprehensive embargo",
        "is_hard_stop": embargoed,
    })

    # Ownership transparency gate
    ownership = findings.get("ownership", "Clean")
    opaque = "opaque" in ownership.lower() or "nominee" in ownership.lower()
    gates.append({
        "gate": "OWNERSHIP_VERIFICATION",
        "passed": not opaque,
        "detail": "Beneficial ownership cannot be verified" if opaque else "Ownership structure verified",
        "is_hard_stop": False,
    })

    return gates


# ---------------------------------------------------------------------------
# Main demo creation
# ---------------------------------------------------------------------------

def create_demo_contested_logistics() -> dict:
    """Create the full Amentum contested logistics demo scenario."""

    results = {
        "vendors_created": 0,
        "enrichments_saved": 0,
        "scores_saved": 0,
        "person_screenings": [],
        "export_guidance": [],
        "errors": [],
    }

    # ---- Init DB ----
    try:
        import db
        db.init_db()
    except Exception as e:
        results["errors"].append(f"DB init failed: {e}")
        return results

    # ---- Step 1: Create all vendor cases ----
    print("\n" + "=" * 70)
    print("AMENTUM CONTESTED LOGISTICS DEMO")
    print(f"Program: {DEMO_PROGRAM}")
    print(f"Vendors: {len(VENDORS)}")
    print("=" * 70)

    for v in VENDORS:
        try:
            with db.get_conn() as conn:
                existing = conn.execute(
                    "SELECT id FROM vendors WHERE id = ?", (v["id"],)
                ).fetchone()
                if existing:
                    # FK-safe deletion order: dependents first, then parent
                    conn.execute("DELETE FROM scoring_results WHERE vendor_id = ?", (v["id"],))
                    conn.execute("DELETE FROM enrichment_reports WHERE vendor_id = ?", (v["id"],))
                    try:
                        conn.execute("DELETE FROM person_screenings WHERE case_id = ?", (v["id"],))
                    except Exception:
                        pass
                    conn.execute("DELETE FROM vendors WHERE id = ?", (v["id"],))

                conn.execute("""
                    INSERT INTO vendors (id, name, country, program, profile, vendor_input)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    v["id"], v["name"], v["country"], DEMO_PROGRAM,
                    v["profile"], json.dumps(v),
                ))

            results["vendors_created"] += 1
            tier_icon = {"critical": "!!!", "high": "!! ", "moderate": "!  ", "low": "   "}
            print(f"  [{tier_icon.get(v['risk_tier'], '   ')}] {v['name']} ({v['country']}) - {v['risk_tier'].upper()}")
        except Exception as e:
            results["errors"].append(f"Vendor {v['name']}: {e}")
            print(f"  [ERR] {v['name']}: {e}")

    # ---- Step 2: Save synthetic enrichment reports ----
    print(f"\n--- Enrichment Reports ---")
    for v in VENDORS:
        try:
            report = _build_enrichment_report(v)
            db.save_enrichment(v["id"], report)
            results["enrichments_saved"] += 1
            fc = report["summary"]["findings_total"]
            cc = report["summary"]["critical"]
            hc = report["summary"]["high"]
            print(f"  {v['name']}: {fc} findings ({cc}C/{hc}H) - {report['overall_risk']}")
        except Exception as e:
            results["errors"].append(f"Enrichment {v['name']}: {e}")
            print(f"  [ERR] {v['name']}: {e}")

    # ---- Step 3: Save synthetic scoring results ----
    print(f"\n--- Scoring Results ---")
    for v in VENDORS:
        try:
            score_result = _build_scoring_result(v)
            with db.get_conn() as conn:
                cal = score_result.get("calibration", {})
                conn.execute("""
                    INSERT INTO scoring_results
                        (vendor_id, calibrated_probability, calibrated_tier, composite_score,
                         is_hard_stop, interval_lower, interval_upper, interval_coverage, full_result)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    v["id"],
                    cal.get("calibrated_probability", 0),
                    cal.get("calibrated_tier", "unknown"),
                    score_result.get("composite_score", 0),
                    score_result.get("is_hard_stop", False),
                    cal.get("interval", {}).get("lower", 0),
                    cal.get("interval", {}).get("upper", 0),
                    cal.get("interval", {}).get("coverage", 0),
                    json.dumps(score_result),
                ))
            results["scores_saved"] += 1
            hs = " [HARD STOP]" if score_result["is_hard_stop"] else ""
            print(f"  {v['name']}: score={score_result['composite_score']} "
                  f"tier={score_result['calibration']['calibrated_tier']}{hs}")
        except Exception as e:
            results["errors"].append(f"Scoring {v['name']}: {e}")
            print(f"  [ERR] {v['name']}: {e}")

    # ---- Step 4: Run export authorization where applicable ----
    print(f"\n--- Export Authorization ---")
    for v in VENDORS:
        if not v.get("export_authorization"):
            continue
        try:
            from export_authorization_rules import build_export_authorization_guidance
            guidance = build_export_authorization_guidance(v["export_authorization"])
            results["export_guidance"].append({
                "vendor": v["name"],
                "posture": guidance.get("posture_label"),
                "confidence": guidance.get("confidence"),
            })
            print(f"  {v['name']}: {guidance.get('posture_label')} "
                  f"(confidence: {guidance.get('confidence')})")
        except Exception as e:
            print(f"  {v['name']}: Export guidance error - {e}")

    # ---- Step 5: Person screening ----
    print(f"\n--- Person Screening ---")
    try:
        from person_screening import screen_person, init_person_screening_db
        init_person_screening_db()
        has_screening = True
    except ImportError:
        has_screening = False
        print("  [SKIP] Person screening module not available")

    try:
        from person_graph_ingest import ingest_person_screening
        has_graph_ingest = True
    except ImportError:
        has_graph_ingest = False

    if has_screening:
        for person in DEMO_PERSONS:
            try:
                result = screen_person(
                    name=person["name"],
                    nationalities=person["nationalities"],
                    employer=person["employer"],
                    item_classification=person["item_classification"],
                    case_id=person["case_id"],
                    screened_by="demo_amentum_script",
                )
                screening_summary = {
                    "name": result.person_name,
                    "role": person["role"],
                    "status": result.screening_status,
                    "score": round(result.composite_score, 2),
                    "action": result.recommended_action,
                    "deemed_export": result.deemed_export,
                }
                results["person_screenings"].append(screening_summary)

                flag = "***" if result.screening_status in ("MATCH", "ESCALATE") else "   "
                print(f"  [{flag}] {result.person_name}: {result.screening_status} "
                      f"(score: {result.composite_score:.2f})")
                if result.deemed_export:
                    print(f"         Deemed export: {result.deemed_export.get('license_type')}")

                # Graph ingest
                if has_graph_ingest:
                    try:
                        gi = ingest_person_screening(result, case_id=person["case_id"])
                        print(f"         Graph: +{gi.get('entities_created', 0)} entities, "
                              f"+{gi.get('relationships_created', 0)} rels")
                    except Exception as ge:
                        print(f"         Graph ingest: {ge}")

            except Exception as e:
                print(f"  [ERR] {person['name']}: {e}")

    # ---- Step 6: Knowledge graph relationships ----
    print(f"\n--- Knowledge Graph Relationships ---")
    try:
        from knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        graph_created = 0

        # Create supply chain relationships
        supply_chain_edges = [
            # Amentum as the prime
            ("Amentum Inc", "company", "PacRim Maritime Solutions Pte Ltd", "company",
             "contracts_with", 0.9, "Maritime spares subcontract"),
            ("Amentum Inc", "company", "QuantumLeap Analytics Co., Ltd", "company",
             "contracts_with", 0.9, "Predictive maintenance analytics subcontract"),
            ("Amentum Inc", "company", "IronForge Cyber Systems LLC", "company",
             "contracts_with", 0.9, "Tactical mesh networking subcontract"),
            ("Amentum Inc", "company", "Palawan Energy & Logistics Corp", "company",
             "contracts_with", 0.85, "Fuel provisioning subcontract"),
            ("Amentum Inc", "company", "Cascade Defense Logistics Inc", "company",
             "contracts_with", 0.95, "Warehousing and last-mile delivery subcontract"),
            ("Amentum Inc", "company", "Komatsu Heavy Lift & Transport KK", "company",
             "contracts_with", 0.9, "Heavy equipment supply"),
            # Risky relationships
            ("PacRim Maritime Solutions Pte Ltd", "company", "Haiyun Holdings Ltd", "company",
             "subsidiary_of", 0.85, "Singapore entity controlled by HK holding company"),
            ("Haiyun Holdings Ltd", "company", "Shenzhen Haiyun Group", "company",
             "subsidiary_of", 0.8, "HK entity controlled by Shenzhen parent"),
            ("Caspian Strategic Metals FZE", "company", "Farhad Nazari", "person",
             "officer_of", 0.95, "Director, OFAC SDN listed"),
            ("SkyBridge SatCom (Shenzhen) Ltd", "company",
             "Shenzhen Haiwei Technology Group", "company",
             "subsidiary_of", 0.9, "Parent company on DOD 1260H list"),
            ("SkyBridge SatCom (Shenzhen) Ltd", "company",
             "National University of Defense Technology", "government_agency",
             "related_entity", 0.75, "20% equity stake via university spin-off"),
        ]

        for (src_name, src_type, tgt_name, tgt_type,
             rel_type, confidence, detail) in supply_chain_edges:
            try:
                # Ensure source entity exists
                src_entity = kg.find_entity_by_name(src_name)
                if not src_entity:
                    src_id = kg.create_entity(
                        name=src_name, entity_type=src_type,
                        metadata={"demo": True, "program": DEMO_PROGRAM}
                    )
                else:
                    src_id = src_entity["id"]

                # Ensure target entity exists
                tgt_entity = kg.find_entity_by_name(tgt_name)
                if not tgt_entity:
                    tgt_id = kg.create_entity(
                        name=tgt_name, entity_type=tgt_type,
                        metadata={"demo": True, "program": DEMO_PROGRAM}
                    )
                else:
                    tgt_id = tgt_entity["id"]

                # Create relationship
                kg.create_relationship(
                    source_id=src_id, target_id=tgt_id,
                    relationship_type=rel_type,
                    confidence=confidence,
                    metadata={"detail": detail, "demo": True}
                )
                graph_created += 1
            except Exception as ge:
                # Relationship may already exist, that's fine
                pass

        print(f"  Created {graph_created} supply chain relationships")
        results["graph_relationships"] = graph_created
    except Exception as e:
        print(f"  Knowledge graph error: {e}")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("AMENTUM CONTESTED LOGISTICS DEMO COMPLETE")
    print("=" * 70)
    print(f"Vendors created:     {results['vendors_created']}/{len(VENDORS)}")
    print(f"Enrichments saved:   {results['enrichments_saved']}")
    print(f"Scores saved:        {results['scores_saved']}")
    print(f"Persons screened:    {len(results['person_screenings'])}")
    print(f"Export authorizations: {len(results['export_guidance'])}")
    print(f"Graph relationships: {results.get('graph_relationships', 0)}")
    if results["errors"]:
        print(f"Errors:              {len(results['errors'])}")
        for e in results["errors"]:
            print(f"  - {e}")
    print("=" * 70)

    # Risk summary table
    print("\n--- Supply Chain Risk Summary ---")
    print(f"{'Vendor':<40} {'Country':<5} {'Score':<6} {'Tier':<10} {'Stop?'}")
    print("-" * 75)
    for v in VENDORS:
        cfg = {"critical": (92, "extreme", "YES"),
               "high": (74, "high", "no"),
               "moderate": (48, "moderate", "no"),
               "low": (18, "low", "no")}
        sc, tier, stop = cfg.get(v["risk_tier"], (50, "?", "no"))
        print(f"{v['name'][:39]:<40} {v['country']:<5} {sc:<6} {tier:<10} {stop}")
    print()

    return results


def clean_demo_data():
    """Remove all Amentum demo data."""
    try:
        import db
        with db.get_conn() as conn:
            # Get all demo vendor IDs
            rows = conn.execute(
                "SELECT id FROM vendors WHERE id LIKE ?", (f"{DEMO_PREFIX}%",)
            ).fetchall()
            vendor_ids = [r["id"] for r in rows]

            for vid in vendor_ids:
                conn.execute("DELETE FROM enrichment_reports WHERE vendor_id = ?", (vid,))
                conn.execute("DELETE FROM scoring_results WHERE vendor_id = ?", (vid,))
                conn.execute("DELETE FROM vendors WHERE id = ?", (vid,))

            # Clean person screenings
            try:
                conn.execute(
                    "DELETE FROM person_screenings WHERE case_id LIKE ?",
                    (f"{DEMO_PREFIX}%",)
                )
            except Exception:
                pass

            print(f"[Demo] Cleaned up {len(vendor_ids)} Amentum demo vendors and related data")
    except Exception as e:
        print(f"[Demo] Cleanup error: {e}")

    # Clean knowledge graph demo entities
    try:
        from knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        # Remove demo-tagged entities
        # Note: this is best-effort; graph cleanup is non-destructive to real data
        print("[Demo] Knowledge graph demo entities should be cleaned manually if needed")
    except Exception:
        pass


if __name__ == "__main__":
    if "--clean" in sys.argv:
        clean_demo_data()
    else:
        result = create_demo_contested_logistics()
        if "--json" in sys.argv:
            print(f"\nResult JSON: {json.dumps(result, indent=2, default=str)}")
