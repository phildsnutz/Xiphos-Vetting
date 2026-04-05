"""
Xiphos Dossier Generator

Generates comprehensive HTML intelligence-grade dossier reports for vendors.
Reports are self-contained (inline CSS, no external dependencies) and ready
for PDF export with proper print styling.

Usage:
    from dossier import generate_dossier
    html = generate_dossier("vendor-id-123")
    with open("dossier.html", "w") as f:
        f.write(html)
"""

from copy import deepcopy
from datetime import datetime
from html import escape
import threading
import time
from typing import Optional

import db
from event_extraction import compute_report_hash

try:
    from storyline import build_case_storyline
    HAS_STORYLINE = True
except ImportError:
    HAS_STORYLINE = False

try:
    from network_risk import compute_network_risk
    HAS_NETWORK_RISK = True
except ImportError:
    HAS_NETWORK_RISK = False

try:
    from foci_evidence import get_latest_foci_summary
    HAS_FOCI_EVIDENCE = True
except ImportError:
    HAS_FOCI_EVIDENCE = False

try:
    from cyber_evidence import get_latest_cyber_evidence_summary
    HAS_CYBER_EVIDENCE = True
except ImportError:
    HAS_CYBER_EVIDENCE = False

try:
    from export_evidence import get_export_evidence_summary
    HAS_EXPORT_EVIDENCE = True
except ImportError:
    HAS_EXPORT_EVIDENCE = False

try:
    from workflow_control_summary import build_workflow_control_summary
    HAS_WORKFLOW_CONTROL = True
except ImportError:
    HAS_WORKFLOW_CONTROL = False

try:
    from graph_ingest import get_vendor_graph_summary
    HAS_GRAPH_SUMMARY = True
except ImportError:
    HAS_GRAPH_SUMMARY = False

try:
    from supplier_passport import build_supplier_passport
    HAS_SUPPLIER_PASSPORT = True
except ImportError:
    HAS_SUPPLIER_PASSPORT = False


_DOSSIER_CONTEXT_CACHE: dict[tuple[str, str, str, str, str, bool], dict] = {}
_DOSSIER_CONTEXT_CACHE_LOCK = threading.Lock()
_DOSSIER_CONTEXT_TTL_SECONDS = 120


def _severity_color(severity: str) -> str:
    """Map severity level to hex color."""
    colors = {
        "critical": "#dc3545",
        "high": "#C4A052",
        "medium": "#ffc107",
        "low": "#0dcaf0",
        "info": "#6c757d",
    }
    return colors.get(severity, "#6c757d")


def _severity_badge(severity: str) -> str:
    """Generate HTML badge for severity level."""
    color = _severity_color(severity)
    return (
        f'<span style="display: inline-block; padding: 4px 8px; '
        f'background-color: {color}; color: white; border-radius: 3px; '
        f'font-size: 11px; font-weight: 600; text-transform: uppercase;">'
        f'{severity}</span>'
    )


def _tier_badge(tier: str) -> str:
    """Generate HTML badge for risk tier."""
    colors = {
        "clear": "#198754",
        "monitor": "#0dcaf0",
        "elevated": "#C4A052",
        "hard_stop": "#dc3545",
    }
    color = colors.get(tier.lower(), "#6c757d")
    display = tier.upper().replace("_", " ")
    return (
        f'<span style="display: inline-block; padding: 6px 12px; '
        f'background-color: {color}; color: white; border-radius: 4px; '
        f'font-size: 12px; font-weight: 600;">{display}</span>'
    )


def _progress_gauge(value: float, max_value: float = 100) -> str:
    """Generate CSS-only probability gauge visualization."""
    pct = min(100, max(0, (value / max_value) * 100))
    color = "#dc3545" if pct >= 70 else "#C4A052" if pct >= 40 else "#198754"

    return f'''
    <div style="width: 100%; background-color: #e9ecef; border-radius: 4px;
                height: 24px; overflow: hidden; margin: 8px 0;">
        <div style="width: {pct}%; background-color: {color}; height: 100%;
                    transition: width 0.3s ease; display: flex; align-items: center;
                    justify-content: flex-end; padding-right: 8px; color: white;
                    font-size: 11px; font-weight: bold;">
            {value:.0f}
        </div>
    </div>
    '''


def _format_monitor_tier(tier: Optional[str]) -> str:
    if not tier:
        return "Unknown"
    return str(tier).replace("TIER_", "").replace("_", " ").strip()


def _format_monitor_checked_at(checked_at: Optional[str]) -> str:
    if not checked_at:
        return "Latest check"
    text = str(checked_at)
    try:
        normalized = text.replace("Z", "+00:00").replace(" ", "T", 1) if "T" not in text else text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%b %d, %-I:%M %p")
    except Exception:
        return text


def _format_timestamp_value(value, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Render timestamp-like values safely from Postgres or string sources."""
    if not value:
        return "N/A"
    if isinstance(value, datetime):
        return value.strftime(fmt)

    text = str(value).strip()
    if not text:
        return "N/A"

    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime(fmt)
    except Exception:
        return text


def _summarize_recent_change(monitoring_history: list[dict]) -> dict:
    if not monitoring_history:
        return {
            "label": "Baseline",
            "detail": "No monitoring history yet",
            "pct": 18,
            "color": "#94A3B8",
        }

    latest = monitoring_history[0]
    checked_label = _format_monitor_checked_at(latest.get("checked_at"))
    previous_tier = _format_monitor_tier(latest.get("previous_risk"))
    current_tier = _format_monitor_tier(latest.get("current_risk"))
    new_findings = int(latest.get("new_findings_count", 0) or 0)

    if latest.get("risk_changed"):
        return {
            "label": "Tier shift",
            "detail": f"{previous_tier} -> {current_tier} • {checked_label}",
            "pct": 92,
            "color": "#C4A052",
        }

    if new_findings > 0:
        finding_label = "1 new finding" if new_findings == 1 else f"{new_findings} new findings"
        return {
            "label": "New findings",
            "detail": f"{finding_label} • {checked_label}",
            "pct": min(88, max(34, new_findings * 2)),
            "color": "#3B82F6",
        }

    return {
        "label": "Stable",
        "detail": f"No tier shift on latest check • {checked_label}",
        "pct": 28,
        "color": "#198754",
    }


PROGRAM_LABELS = {
    "dod_classified": "DoD / IC (Classified)",
    "dod_unclassified": "DoD (Unclassified)",
    "federal_non_dod": "Federal (Non-DoD)",
    "regulated_commercial": "Regulated Commercial",
    "commercial": "Commercial",
    "weapons_system": "DoD (Unclassified)",
    "mission_critical": "Federal (Non-DoD)",
    "nuclear_related": "DoD (Unclassified)",
    "intelligence_community": "DoD / IC (Classified)",
    "critical_infrastructure": "Federal (Non-DoD)",
    "dual_use": "Regulated Commercial",
    "standard_industrial": "Commercial",
    "commercial_off_shelf": "Commercial",
    "services": "Commercial",
}


def _workflow_lane_context(
    vendor: dict,
    cyber_summary: Optional[dict] = None,
    export_summary: Optional[dict] = None,
) -> dict:
    vendor_input = vendor.get("vendor_input", {}) if isinstance(vendor.get("vendor_input"), dict) else {}
    profile = str(vendor_input.get("profile", vendor.get("profile", "")) or "").lower()
    has_export_lane = (
        isinstance(export_summary, dict)
        or isinstance(vendor_input.get("export_authorization"), dict)
        or profile == "itar_trade_compliance"
    )
    has_cyber_lane = (
        isinstance(cyber_summary, dict)
        and any(value not in (None, "", [], {}, False) for value in cyber_summary.values())
    ) or profile in {"supplier_cyber_trust", "cmmc_supplier_review"}

    if has_export_lane:
        return {
            "label": "Export authorization",
            "title": "Export authorization brief",
            "summary_name": "export authorization brief",
        }
    if has_cyber_lane:
        return {
            "label": "Supply chain assurance",
            "title": "Supply chain assurance brief",
            "summary_name": "supply chain assurance brief",
        }
    return {
        "label": "Entity briefing",
        "title": "Entity intelligence brief",
        "summary_name": "entity intelligence brief",
    }


def _export_request_type_label(request_type: Optional[str]) -> str:
    mapping = {
        "item_transfer": "Item transfer",
        "foreign_person_access": "Foreign-person access",
        "technical_data_release": "Technical-data release",
    }
    return mapping.get(str(request_type or "").lower(), "Authorization review")


def _export_jurisdiction_label(jurisdiction: Optional[str]) -> str:
    mapping = {
        "itar": "ITAR / USML",
        "ear": "EAR / ECCN",
        "ofac_overlay": "OFAC overlay",
        "unknown": "Needs jurisdiction review",
    }
    return mapping.get(str(jurisdiction or "").lower(), "Unspecified")


def _workflow_lane_brief(
    vendor: dict,
    foci_summary: Optional[dict] = None,
    cyber_summary: Optional[dict] = None,
    export_summary: Optional[dict] = None,
) -> dict:
    lane = _workflow_lane_context(vendor, cyber_summary=cyber_summary, export_summary=export_summary)
    vendor_input = vendor.get("vendor_input", {}) if isinstance(vendor.get("vendor_input"), dict) else {}

    if lane["label"] == "Export authorization":
        export_input = vendor_input.get("export_authorization", {}) if isinstance(vendor_input.get("export_authorization"), dict) else {}
        request_type = str(export_summary.get("request_type") or export_input.get("request_type") or "")
        destination = str(export_summary.get("destination_country") or export_input.get("destination_country") or "")
        recipient = str(export_input.get("recipient_name") or vendor.get("name") or "this request")
        posture = str(export_summary.get("posture_label") or ("Request captured" if export_input else "Awaiting request"))
        next_action = (
            str(export_summary.get("recommended_next_step") or "")
            or str(export_summary.get("reason_summary") or "")
            or str(export_summary.get("narrative") or "")
            or (
                f"{_export_request_type_label(request_type)} for {destination or recipient}."
                if export_input else
                "Capture an export authorization request to move this lane into decision support mode."
            )
        )
        classification = str(export_summary.get("classification_display") or export_input.get("classification_guess") or "Needs review")
        return {
            "eyebrow": "Decision frame",
            "title": "Export authorization",
            "question": "Can this item, technical-data release, or foreign-person access request move forward under current control posture?",
            "outputs": "Likely prohibited / License required / Exception path / Likely NLR / Escalate",
            "evidence": "Classification memos, access-control records, customer export artifacts, and BIS or DDTC rule guidance.",
            "next_action": next_action,
            "stats": [
                {"label": "Authorization posture", "value": posture},
                {"label": "Request type", "value": _export_request_type_label(request_type) if request_type else "Awaiting request"},
                {"label": "Jurisdiction", "value": _export_jurisdiction_label(export_summary.get("jurisdiction_guess") or export_input.get("jurisdiction_guess"))},
                {"label": "Classification", "value": classification},
            ],
        }

    if lane["label"] == "Supply chain assurance":
        cyber_summary = cyber_summary if isinstance(cyber_summary, dict) else {}
        assessment_score = cyber_summary.get("assessment_score")
        current_level = int(cyber_summary.get("current_cmmc_level") or 0)
        open_poam_items = int(cyber_summary.get("open_poam_items") or 0)
        public_evidence_present = bool(cyber_summary.get("public_evidence_present"))
        high_critical_cves = int(
            cyber_summary.get("high_or_critical_cve_count")
            or cyber_summary.get("critical_cve_count")
            or 0
        )
        cyber_pressure = (
            bool(cyber_summary.get("poam_active"))
            or open_poam_items > 0
            or high_critical_cves > 0
            or (isinstance(assessment_score, (int, float)) and float(assessment_score) < 90)
        )
        next_action = (
            f"{open_poam_items} open POA&M item{'s' if open_poam_items != 1 else ''}"
            if open_poam_items > 0 else
            f"{high_critical_cves} high / critical CVE{'s' if high_critical_cves != 1 else ''} remain in scope."
            if high_critical_cves > 0 else
            "First-party public assurance evidence is in view, but customer-controlled artifacts are still missing."
            if public_evidence_present and not cyber_summary.get("sprs_artifact_id") and not cyber_summary.get("oscal_artifact_id") else
            "Customer attestation and remediation evidence is supporting the cyber readiness view."
            if cyber_summary else
            "Attach SPRS exports, OSCAL artifacts, SBOM or VEX evidence, and product references to ground supply chain assurance."
        )
        sprs_value = "Unknown"
        if isinstance(assessment_score, (int, float)):
            sprs_value = f"{float(assessment_score):.0f}"
        if current_level > 0:
            sprs_value = f"{sprs_value} • L{current_level}" if sprs_value != "Unknown" else f"L{current_level}"
        return {
            "eyebrow": "Decision frame",
            "title": "Supply chain assurance",
            "question": "Can this supplier, product, and dependency stack be trusted with CUI-sensitive or mission-critical work given attestation, remediation, provenance, and vulnerability evidence?",
            "outputs": "Ready / Qualified / Review / Blocked",
            "evidence": "SPRS exports, OSCAL SSP or POA&M artifacts, first-party public SBOM or VEX evidence, provenance attestations, lifecycle disclosures, and vulnerability overlays tied to the supplier and dependency stack.",
            "next_action": next_action,
            "stats": [
                {"label": "SPRS / CMMC", "value": sprs_value},
                {"label": "Open POA&M", "value": str(open_poam_items) if open_poam_items > 0 else "None captured"},
                {"label": "High / critical CVEs", "value": str(high_critical_cves) if high_critical_cves > 0 else "None captured"},
                {"label": "Readiness posture", "value": "Readiness gap in view" if cyber_pressure else "Readiness documented" if cyber_summary else "Awaiting evidence"},
            ],
        }

    foci_summary = foci_summary if isinstance(foci_summary, dict) else {}
    artifact_count = int(foci_summary.get("artifact_count") or 0)
    foreign_interest_present = bool(
        foci_summary.get("declared_foreign_owner")
        or foci_summary.get("declared_foreign_country")
        or foci_summary.get("declared_foreign_ownership_pct")
        or foci_summary.get("max_ownership_percent_mention")
    )
    mitigation_present = bool(
        foci_summary.get("declared_mitigation_type")
        or foci_summary.get("declared_mitigation_status")
        or foci_summary.get("contains_mitigation_terms")
    )
    foreign_interest_value = str(
        foci_summary.get("declared_foreign_ownership_pct")
        or (f"{foci_summary.get('max_ownership_percent_mention')}%" if isinstance(foci_summary.get("max_ownership_percent_mention"), (int, float)) else "")
        or foci_summary.get("declared_foreign_country")
        or "Not stated"
    )
    next_action = (
        f"{str(foci_summary.get('declared_mitigation_type') or foci_summary.get('declared_mitigation_status') or 'Mitigation evidence').replace('_', ' ')} captured for adjudication."
        if mitigation_present else
        f"Foreign counterparty context points to {str(foci_summary.get('declared_foreign_owner') or foci_summary.get('declared_foreign_country') or 'a foreign interest')} and needs explicit adjudication."
        if foreign_interest_present else
        "Customer ownership and governance evidence is attached and available to the decision flow."
        if foci_summary else
        "Upload Form 328 records, ownership charts, and mitigation instruments to ground the decision."
    )
    posture = (
        "Mitigation documented" if mitigation_present else
        "Foreign interest in view" if foreign_interest_present else
        "Control chain documented" if foci_summary else
        "Awaiting evidence"
    )
    return {
        "eyebrow": "Decision frame",
        "title": "Entity briefing",
        "question": "Can we award, keep, or qualify this supplier given ownership, foreign-influence, and network evidence?",
        "outputs": "Approved / Qualified / Review / Blocked",
        "evidence": "Form 328 records, ownership charts, mitigation instruments, SAM.gov registration, SAM.gov subaward reporting, and prime or sub relationship evidence.",
        "next_action": next_action,
        "stats": [
            {"label": "FOCI posture", "value": posture},
            {"label": "Artifacts", "value": str(artifact_count)},
            {"label": "Foreign interest", "value": foreign_interest_value},
            {"label": "Mitigation", "value": str(foci_summary.get("declared_mitigation_type") or foci_summary.get("declared_mitigation_status") or "Not stated").replace("_", " ")},
        ],
    }

# Human-readable source names for dossier display
SOURCE_DISPLAY_NAMES = {
    "dod_sam_exclusions": "SAM.gov Exclusions",
    "trade_csl": "Consolidated Screening List",
    "un_sanctions": "UN Security Council Sanctions",
    "opensanctions_pep": "Politically Exposed Persons (PEP)",
    "worldbank_debarred": "World Bank Debarment List",
    "icij_offshore": "ICIJ Offshore Leaks",
    "fara": "Foreign Agent Registration (FARA)",
    "gdelt_media": "Adverse Media (GDELT)",
    "google_news": "News Coverage",
    "sec_edgar": "SEC Filings (EDGAR)",
    "gleif_lei": "Legal Entity Identifier (GLEIF)",
    "opencorporates": "Corporate Registry (OpenCorporates)",
    "uk_companies_house": "UK Companies House",
    "corporations_canada": "Corporations Canada",
    "australia_abn_asic": "Australia ABN / ASIC",
    "singapore_acra": "Singapore ACRA",
    "new_zealand_companies_office": "New Zealand Companies Office / NZBN",
    "norway_brreg": "Norway Brreg",
    "netherlands_kvk": "Netherlands KVK",
    "france_inpi_rne": "France INPI / RNE",
    "wikidata_company": "Corporate Metadata (Wikidata)",
    "sam_gov": "SAM.gov Registration",
    "sam_subaward_reporting": "SAM.gov Subcontract Reporting",
    "usaspending": "Federal Contract Awards",
    "fpds_contracts": "Federal Procurement (FPDS)",
    "epa_echo": "EPA Environmental Compliance",
    "osha_safety": "OSHA Workplace Safety",
    "courtlistener": "Federal/State Court Dockets",
    "fdic_bankfind": "FDIC Banking Regulation",
    "cisa_kev": "CISA Known Vulnerabilities",
    "ofac_sdn": "OFAC Specially Designated Nationals",
    "eu_sanctions": "EU Consolidated Sanctions",
    "uk_hmt_sanctions": "UK HMT/OFSI Sanctions",
    "sbir_awards": "SBIR/STTR Innovation Awards",
    "sec_xbrl": "SEC Financial Data (XBRL)",
    "foci_artifact_upload": "Customer FOCI evidence",
    "sprs_import": "Customer SPRS evidence",
    "oscal_upload": "Customer OSCAL evidence",
    "nvd_overlay": "Customer NVD overlay",
    "public_assurance_evidence_fixture": "First-party public assurance evidence",
    "export_artifact_upload": "Customer export evidence",
    "bis_rules_engine": "BIS rules guidance",
}


def _source_display_name(source: str) -> str:
    """Convert a connector ID to a human-readable source name."""
    return SOURCE_DISPLAY_NAMES.get(source, source.replace("_", " ").title())


def _summarize_connector_error(error: str) -> str:
    message = str(error or "").strip()
    if not message:
        return "Source unavailable."
    lowered = message.lower()
    if "no such file or directory" in lowered:
        if "/fixtures/" in lowered or "fixtures/" in lowered:
            return "Fixture unavailable in this deployment."
        return "Source unavailable in this deployment."
    if "/app/" in message:
        return "Source unavailable in this deployment."
    return message[:80]


GRAPH_CONTROL_PATH_RELATIONSHIPS = {
    "backed_by",
    "led_by",
    "depends_on_network",
    "depends_on_service",
    "routes_payment_through",
    "distributed_by",
    "operates_facility",
    "ships_via",
    "owned_by",
    "beneficially_owned_by",
}


def _is_connector_gap_finding(finding: dict) -> bool:
    text = f"{finding.get('title', '')} {finding.get('detail', '')}".lower()
    return (
        "not configured" in text
        or "api key not configured" in text
        or "environment variable" in text
        or "api unavailable" in text
        or "unable to verify" in text
        or "cannot reach" in text
    )


def _is_clear_or_low_signal_finding(finding: dict) -> bool:
    title = (finding.get("title", "") or "").lower()
    detail = (finding.get("detail", "") or "").lower()
    source = (finding.get("source", "") or "").lower()
    category = (finding.get("category", "") or "").lower()
    severity = (finding.get("severity", "info") or "info").lower()

    low_signal_title_markers = (
        "no adverse media found",
        "no epa echo facilities found",
        "recap archive: no federal litigation found",
        "no world bank debarment matches",
        "no un security council sanctions matches",
        "eu sanctions: no matches found",
        "ofac sdn: no matches found",
        "no fara registrations found",
        "no icij matches found",
        "no osha inspection records found",
        "fdic bankfind - no matches",
        "cisa kev: no known exploited vulnerabilities found",
        "cross-domain clear:",
        "wikidata: no structured data found",
        "google news: no recent articles found",
        "no lei found",
        "sec xbrl: no cik found",
        "no sec filings found",
        "no usaspending recipient match",
    )
    low_signal_detail_markers = (
        "baseline articles found: 0",
        "absence of results does not guarantee",
        "cannot retrieve financial data without a cik",
        "no epa-regulated facilities matched",
        "no active or failed institutions matching",
        "not found in the un security council consolidated sanctions list",
        "not found on ofac specially designated nationals list",
        "not found on eu cfsp consolidated sanctions list",
    )
    if any(marker in title for marker in low_signal_title_markers):
        return True
    if any(marker in detail for marker in low_signal_detail_markers):
        return True

    if severity in {"info", "low"}:
        clear_markers = (
            "no matches found",
            "not found in",
            "no records found",
            "no known exploited vulnerabilities",
            "no structured data found",
            "no sec filings found",
            "clear",
        )
        if any(marker in title or marker in detail for marker in clear_markers):
            return True

    source_specific_noise = {
        "fdic_bankfind",
        "fara",
        "osha_safety",
        "wikidata_company",
        "google_news",
        "cisa_kev",
        "icij_offshore",
        "worldbank_debarred",
        "eu_sanctions",
        "ofac_sdn",
        "opensanctions_pep",
        "un_sanctions",
        "trade_csl",
        "gleif_lei",
    }
    if source in source_specific_noise and (
        title.startswith("no ")
        or " no " in f" {title} "
        or "no " in detail
        or "clear" in title
    ):
        return True

    if source == "sec_edgar" and category == "identity" and severity in {"info", "low"}:
        if "cik:" in detail and "filing date" in detail:
            return True
    if source == "sec_edgar" and "no sec filings found" in title:
        return True
    if source == "usaspending" and ("0 awards" in title or "0 awards" in detail):
        return True

    return False


def _finding_priority(finding: dict) -> tuple[int, float, float]:
    severity_rank = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
        "info": 4,
    }
    source_bonus = {
        "trade_csl": 0.0,
        "ofac_sdn": 0.0,
        "dod_sam_exclusions": 0.2,
        "worldbank_debarred": 0.3,
        "courtlistener": 0.4,
        "recap_courts": 0.4,
        "sec_edgar": 0.6,
        "usaspending": 0.5,
    }
    severity = severity_rank.get((finding.get("severity", "info") or "info").lower(), 5)
    confidence = float(finding.get("confidence", 0.0) or 0.0)
    source_weight = source_bonus.get((finding.get("source", "") or "").lower(), 0.8)
    return (severity, -confidence, source_weight)


def _curate_dossier_findings(enrichment: Optional[dict], limit: int = 8) -> list[dict]:
    """Select the highest-signal findings for premium dossier surfaces."""
    if not enrichment:
        return []

    findings = enrichment.get("findings", []) or []
    curated = [
        finding
        for finding in findings
        if not _is_connector_gap_finding(finding) and not _is_clear_or_low_signal_finding(finding)
    ]
    if not curated:
        return []
    curated.sort(key=_finding_priority)
    return curated[:limit]


def _is_clear_or_low_signal_event(event: dict) -> bool:
    title = (event.get("title", "") or "").lower()
    assessment = (event.get("assessment", "") or "").lower()
    severity = (event.get("severity", "info") or "info").lower()

    if _is_connector_gap_finding(event):
        return True
    if _is_clear_or_low_signal_finding(event):
        return True
    if title.startswith("no ") or " no " in f" {title} ":
        return True

    low_signal_assessment_markers = (
        "no federal court dockets found",
        "absence of results does not guarantee",
        "not found on",
        "not found in",
        "no active or failed institutions matching",
        "cannot retrieve financial data without a cik",
    )
    if any(marker in assessment for marker in low_signal_assessment_markers):
        return True

    return severity in {"info", "low"} and not assessment.strip()


def _render_hero_official_corroboration(passport: dict | None) -> str:
    identity = passport.get("identity") if isinstance(passport, dict) and isinstance(passport.get("identity"), dict) else {}
    official = identity.get("official_corroboration") if isinstance(identity.get("official_corroboration"), dict) else {}
    if not official:
        return ""

    coverage_level = str(official.get("coverage_level") or "missing").lower()
    coverage_label = str(official.get("coverage_label") or "No official corroboration captured")
    blocked_count = int(official.get("blocked_connector_count") or 0)
    core_count = int(official.get("core_official_identifier_count") or 0)
    relevant_connector_count = int(official.get("relevant_official_connector_count") or official.get("official_connector_count") or 0)
    meter_pct = {
        "strong": 100,
        "partial": 66,
        "public_only": 33,
        "missing": 10,
    }.get(coverage_level, 10)
    meter_color = {
        "strong": "#198754",
        "partial": "#C4A052",
        "public_only": "#dc3545",
        "missing": "#dc3545",
    }.get(coverage_level, "#dc3545")
    detail = f"{core_count} core official identifiers verified · {relevant_connector_count} relevant official checks"
    if blocked_count > 0:
        detail += f" · {blocked_count} relevant blocked checks"
    return f"""
                <div class="hero-signal-card">
                    <div class="hero-signal-label">Official corroboration</div>
                    <div class="hero-signal-value">{escape(coverage_label)}</div>
                    <div class="hero-signal-note">{escape(detail)}</div>
                    <div class="hero-signal-meter"><span style="width: {meter_pct}%; background: {meter_color};"></span></div>
                </div>
    """


def _generate_executive_summary(
    vendor: dict,
    score: dict,
    enrichment: Optional[dict],
    monitoring_history: Optional[list[dict]] = None,
    foci_summary: Optional[dict] = None,
    cyber_summary: Optional[dict] = None,
    export_summary: Optional[dict] = None,
    supplier_passport: Optional[dict] = None,
) -> str:
    """Generate executive summary section."""
    if not score:
        return ""

    calibrated = score.get("calibrated", {})
    probability = calibrated.get("calibrated_probability", 0)
    tier = calibrated.get("calibrated_tier", "unknown")

    # Get program label
    vendor_input = vendor.get("vendor_input", {}) if isinstance(vendor.get("vendor_input"), dict) else {}
    program_raw = vendor_input.get("program", vendor.get("program", ""))
    program_label = PROGRAM_LABELS.get(program_raw, program_raw)

    enrichment_info = ""
    source_coverage = "N/A"
    if enrichment:
        # Use the scored tier if available, not the raw enrichment overall_risk
        # The enrichment labels any single CRITICAL finding as "CRITICAL" overall,
        # even when the FGAMLogit score is 10% APPROVED. Use the scored result.
        osint_risk_label = enrichment.get('overall_risk', 'LOW')
        if score:
            cal = score.get("calibrated", {})
            scored_tier = cal.get("calibrated_tier", "")
            if "APPROVED" in scored_tier:
                osint_risk_label = "LOW"
            elif "REVIEW" in scored_tier or "ELEVATED" in scored_tier or "CONDITIONAL" in scored_tier:
                osint_risk_label = "MEDIUM"
            elif "BLOCKED" in scored_tier or "HARD_STOP" in scored_tier or "DENIED" in scored_tier:
                osint_risk_label = "CRITICAL"

        findings_count = enrichment.get('summary', {}).get('findings_total', 0)
        connectors_run = enrichment.get('summary', {}).get('connectors_run', 0)
        connectors_data = enrichment.get('summary', {}).get('connectors_with_data', 0)
        source_coverage = f"{connectors_data}/{connectors_run} sources"
        enrichment_info = f'''
            <div class="summary-stat-card">
                <div class="summary-stat-label">Intel Coverage</div>
                <div class="summary-stat-value">{escape(source_coverage)}</div>
                <div class="summary-stat-note">{findings_count} findings | OSINT {escape(osint_risk_label.title())}</div>
            </div>
        '''

    # Derive recommendation text from tier
    recommendation = calibrated.get("program_recommendation", "")
    if not recommendation:
        if "APPROVED" in tier or "QUALIFIED" in tier:
            recommendation = "APPROVED"
        elif "CONDITIONAL" in tier or "ACCEPTABLE" in tier:
            recommendation = "CONDITIONAL APPROVAL"
        elif "REVIEW" in tier or "ELEVATED" in tier or "CAUTION" in tier:
            recommendation = "ENHANCED DUE DILIGENCE"
        elif "BLOCKED" in tier or "CRITICAL" in tier or "DISQUALIFIED" in tier:
            recommendation = "REJECT"
        else:
            recommendation = "UNDER REVIEW"

    recommendation_label = recommendation.replace("_", " ").strip()
    rec_color = "#198754" if "APPROVED" in recommendation else "#C4A052" if "CONDITIONAL" in recommendation else "#dc3545"

    # Derive confidence descriptor
    ci_lo = calibrated.get("interval", {}).get("lower", 0)
    ci_hi = calibrated.get("interval", {}).get("upper", 0)
    ci_width = ci_hi - ci_lo
    confidence_desc = "High" if ci_width < 0.10 else "Moderate" if ci_width < 0.25 else "Low"
    confidence_pct = 92 if confidence_desc == "High" else 74 if confidence_desc == "Moderate" else 48
    risk_pct = max(0, min(100, round(float(probability or 0.0) * 100)))
    coverage_pct = 0
    recent_change = _summarize_recent_change(monitoring_history or [])
    lane = _workflow_lane_context(vendor, cyber_summary=cyber_summary, export_summary=export_summary)
    lane_brief = _workflow_lane_brief(
        vendor,
        foci_summary=foci_summary,
        cyber_summary=cyber_summary,
        export_summary=export_summary,
    )
    control_summary = build_workflow_control_summary(
        vendor,
        foci_summary=foci_summary,
        cyber_summary=cyber_summary,
        export_summary=export_summary,
    ) if HAS_WORKFLOW_CONTROL else None
    if enrichment:
        connectors_run = enrichment.get('summary', {}).get('connectors_run', 0) or 0
        connectors_data = enrichment.get('summary', {}).get('connectors_with_data', 0) or 0
        coverage_pct = round((connectors_data / connectors_run) * 100) if connectors_run else 0

    report_date = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    summary_line = (
        "Helios recommends "
        f"{recommendation_label.lower()} for {vendor.get('name', 'this vendor')} based on a "
        f"{probability:.1%} posterior risk estimate and {confidence_desc.lower()} assessment confidence in this "
        f"{lane['summary_name']}."
    )
    lane_stats_html = "".join(
        f'''
        <div class="hero-lane-stat">
            <div class="hero-lane-stat-label">{escape(stat['label'])}</div>
            <div class="hero-lane-stat-value">{escape(str(stat['value']))}</div>
        </div>
        '''
        for stat in lane_brief["stats"][:4]
    )
    control_missing_html = "".join(
        f'<li>{escape(item)}</li>'
        for item in ((control_summary or {}).get("missing_inputs") or [])[:3]
    ) or "<li>No major intake gap is currently flagged.</li>"
    control_summary_html = f'''
            <div class="hero-control-strip">
                <div class="hero-control-card">
                    <div class="hero-control-label">Control posture</div>
                    <div class="hero-control-value">{escape((control_summary or {}).get("label") or "Not assessed")}</div>
                    <div class="hero-control-copy">{escape((control_summary or {}).get("review_basis") or "No control summary available.")}</div>
                </div>
                <div class="hero-control-card">
                    <div class="hero-control-label">Action owner</div>
                    <div class="hero-control-value">{escape((control_summary or {}).get("action_owner") or "Analyst review")}</div>
                    <div class="hero-control-copy">{escape((control_summary or {}).get("decision_boundary") or "")}</div>
                </div>
                <div class="hero-control-card">
                    <div class="hero-control-label">Missing inputs</div>
                    <div class="hero-control-copy">
                        <ul class="hero-control-list">{control_missing_html}</ul>
                    </div>
                </div>
            </div>
    ''' if control_summary else ""
    official_corroboration_hero = _render_hero_official_corroboration(supplier_passport)

    return f'''
    <section class="hero-section">
        <div class="hero-panel">
            <div class="hero-topline">{escape(lane['title'])}</div>
            <div class="hero-head">
                <div>
                    <h1 class="hero-title">{escape(vendor.get('name', 'Unknown'))}</h1>
                    <p class="hero-summary">{escape(summary_line)}</p>
                </div>
                <div class="hero-chip-stack">
                    <span class="hero-chip" style="background:{rec_color}; color:white;">{escape(recommendation_label.upper())}</span>
                    <span class="hero-chip hero-chip-outline">{escape(lane['label'])}</span>
                    <span class="hero-chip hero-chip-outline">{escape(program_label)}</span>
                </div>
            </div>

            <div class="hero-stats-grid">
                <div class="summary-stat-card">
                    <div class="summary-stat-label">Risk posture</div>
                    <div class="summary-stat-value">{probability:.1%}</div>
                    <div class="summary-stat-note">Tier {escape(tier.replace('_', ' '))}</div>
                </div>
                <div class="summary-stat-card">
                    <div class="summary-stat-label">Assessment confidence</div>
                    <div class="summary-stat-value">{escape(confidence_desc)}</div>
                    <div class="summary-stat-note">CI {ci_lo:.1%} to {ci_hi:.1%}</div>
                </div>
                <div class="summary-stat-card">
                    <div class="summary-stat-label">Operating context</div>
                    <div class="summary-stat-value">{escape(vendor.get('country', '') or 'N/A')}</div>
                    <div class="summary-stat-note">{escape(program_label)}</div>
                </div>
                {enrichment_info}
            </div>

            <div class="hero-lane-brief">
                <div class="hero-lane-panel">
                    <div class="hero-lane-eyebrow">{escape(lane_brief['eyebrow'])}</div>
                    <div class="hero-lane-title">{escape(lane_brief['title'])}</div>
                    <div class="hero-lane-section-label">Core question</div>
                    <div class="hero-lane-copy">{escape(lane_brief['question'])}</div>
                    <div class="hero-lane-section-label">Decision outputs</div>
                    <div class="hero-lane-copy hero-lane-copy-strong">{escape(lane_brief['outputs'])}</div>
                    <div class="hero-lane-section-label">Evidence basis</div>
                    <div class="hero-lane-copy">{escape(lane_brief['evidence'])}</div>
                </div>
                <div class="hero-lane-panel">
                    <div class="hero-lane-eyebrow">Lane readout</div>
                    <div class="hero-lane-stats">{lane_stats_html}</div>
                    <div class="hero-lane-section-label">Immediate next action</div>
                    <div class="hero-lane-copy">{escape(lane_brief['next_action'])}</div>
                </div>
            </div>
            {control_summary_html}

            <div class="hero-signal-strip">
                <div class="hero-signal-card">
                    <div class="hero-signal-label">Risk signal</div>
                    <div class="hero-signal-value">{risk_pct}%</div>
                    <div class="hero-signal-meter"><span style="width: {risk_pct}%; background: {rec_color};"></span></div>
                </div>
                <div class="hero-signal-card">
                    <div class="hero-signal-label">Assessment confidence</div>
                    <div class="hero-signal-value">{escape(confidence_desc)}</div>
                    <div class="hero-signal-meter"><span style="width: {confidence_pct}%; background: #D4BF89;"></span></div>
                </div>
                <div class="hero-signal-card">
                    <div class="hero-signal-label">Connector coverage</div>
                    <div class="hero-signal-value">{coverage_pct}%</div>
                    <div class="hero-signal-meter"><span style="width: {coverage_pct}%; background: #7DD3FC;"></span></div>
                </div>
                {official_corroboration_hero}
                <div class="hero-signal-card">
                    <div class="hero-signal-label">Recent change</div>
                    <div class="hero-signal-value">{escape(recent_change['label'])}</div>
                    <div class="hero-signal-note">{escape(recent_change['detail'])}</div>
                    <div class="hero-signal-meter"><span style="width: {recent_change['pct']}%; background: {recent_change['color']};"></span></div>
                </div>
            </div>

            <div class="hero-note">
                <strong>Report date:</strong> {report_date}
                <span class="hero-note-divider">|</span>
                <strong>Classification:</strong> Controlled distribution
            </div>
        </div>
    </section>
    '''


def _storyline_type_label(card_type: str) -> str:
    labels = {
        "trigger": "Trigger",
        "impact": "Impact",
        "reach": "Reach",
        "action": "Action",
        "offset": "Offset",
    }
    return labels.get(str(card_type or "").lower(), "Signal")


def _storyline_trace_label(target: dict | None) -> str:
    if not isinstance(target, dict):
        return "Case detail"
    kind = str(target.get("kind", "") or "").lower()
    if kind == "graph_focus":
        return "Connected network"
    if kind == "evidence_tab":
        tab = str(target.get("tab", "") or "").lower()
        tab_map = {
            "findings": "Evidence findings",
            "events": "Normalized events",
            "intel": "Intel summary",
            "model": "Model reasoning",
        }
        return tab_map.get(tab, "Evidence detail")
    if kind == "deep_analysis":
        return "Model reasoning"
    if kind == "action_panel":
        return "Recommended actions"
    return "Case detail"


def _storyline_source_label(source_ref: dict) -> str:
    kind = str(source_ref.get("kind", "") or "").lower()
    source_id = str(source_ref.get("id", "") or "").strip()
    if kind == "hard_stop":
        return "Hard-stop rule"
    if kind == "flag":
        return "Advisory flag"
    if kind == "event":
        return "Normalized event"
    if kind == "finding":
        return "Source finding"
    if kind == "network_risk":
        return "Network risk"
    if kind == "score":
        return "Scoring model"
    if kind == "report":
        return "OSINT report"
    if kind == "intel_summary":
        return "Intel summary"
    if kind == "customer_artifact":
        return "Customer artifact"
    if kind == "export_guidance":
        return "Export rules layer"
    if source_id:
        return source_id.replace("_", " ").title()
    return "Case evidence"


def _build_dossier_storyline(
    vendor_id: str,
    vendor: dict,
    score: Optional[dict],
    enrichment: Optional[dict],
    case_events: list[dict],
    intel_summary: Optional[dict],
) -> Optional[dict]:
    if not HAS_STORYLINE or not isinstance(score, dict):
        return None

    network_risk = None
    if HAS_NETWORK_RISK:
        try:
            result = compute_network_risk(vendor_id)
            if isinstance(result, dict):
                network_risk = {
                    "score": result.get("network_risk_score", 0),
                    "level": result.get("network_risk_level", "none"),
                    "high_risk_neighbors": result.get("high_risk_neighbors", 0),
                    "neighbor_count": result.get("neighbor_count", 0),
                }
        except Exception as err:
            print(f"[dossier] Network risk lookup failed: {err}")
            network_risk = None

    foci_summary = get_latest_foci_summary(vendor_id) if HAS_FOCI_EVIDENCE else None
    cyber_summary = get_latest_cyber_evidence_summary(vendor_id) if HAS_CYBER_EVIDENCE else None
    vendor_input = vendor.get("vendor_input", {}) if isinstance(vendor.get("vendor_input"), dict) else {}
    export_summary = (
        get_export_evidence_summary(vendor_id, vendor_input.get("export_authorization"))
        if HAS_EXPORT_EVIDENCE else None
    )

    try:
        return build_case_storyline(
            vendor_id,
            vendor,
            score,
            report=enrichment,
            events=case_events,
            intel_summary=intel_summary,
            network_risk=network_risk,
            foci_summary=foci_summary,
            cyber_summary=cyber_summary,
            export_summary=export_summary,
        )
    except Exception as err:
        print(f"[dossier] Storyline generation failed: {err}")
        return None


def _generate_cyber_evidence_section(cyber_summary: Optional[dict]) -> str:
    if not isinstance(cyber_summary, dict):
        return ""

    chips = []
    current_level = int(cyber_summary.get("current_cmmc_level") or 0)
    if current_level > 0:
        chips.append(f"CMMC Level {current_level}")
    if cyber_summary.get("assessment_status"):
        chips.append(f"Status {escape(str(cyber_summary['assessment_status']))}")
    if cyber_summary.get("poam_active"):
        open_items = int(cyber_summary.get("open_poam_items") or 0)
        chips.append(
            f"POA&M active{f' ({open_items} open)' if open_items > 0 else ''}"
        )
    critical_cves = int(cyber_summary.get("critical_cve_count") or 0)
    if critical_cves > 0:
        chips.append(f"{critical_cves} critical CVE{'s' if critical_cves != 1 else ''}")
    kev_count = int(cyber_summary.get("kev_flagged_cve_count") or 0)
    if kev_count > 0:
        chips.append(f"{kev_count} KEV-linked issue{'s' if kev_count != 1 else ''}")
    if cyber_summary.get("system_name"):
        chips.append(f"System {escape(str(cyber_summary['system_name']))}")
    if cyber_summary.get("public_evidence_present"):
        chips.append("Public assurance evidence")
    if cyber_summary.get("sbom_present"):
        sbom_format = str(cyber_summary.get("sbom_format") or "SBOM")
        sbom_age = cyber_summary.get("sbom_fresh_days")
        chips.append(
            f"{sbom_format} SBOM"
            + (f" ({int(sbom_age)}d)" if isinstance(sbom_age, int) and sbom_age >= 0 else "")
        )
    vex_status = str(cyber_summary.get("vex_status") or "").strip()
    if vex_status and vex_status.lower() not in {"missing", "unknown", "none"}:
        chips.append(f"VEX {escape(vex_status.replace('_', ' '))}")
    if cyber_summary.get("provenance_attested"):
        chips.append("Provenance attested")
    if cyber_summary.get("support_lifecycle_published"):
        chips.append("Lifecycle published")
    if int(cyber_summary.get("open_source_advisory_count") or 0) > 0:
        chips.append(f"{int(cyber_summary.get('open_source_advisory_count') or 0)} OSS advisories")
    if int(cyber_summary.get("scorecard_low_repo_count") or 0) > 0:
        chips.append(f"{int(cyber_summary.get('scorecard_low_repo_count') or 0)} low-score repos")

    chip_html = "".join(f'<span class="storyline-source-chip">{chip}</span>' for chip in chips[:6])
    posture = "Customer cyber evidence"
    if current_level > 0 and current_level < 2:
        posture = "CMMC readiness gap"
    elif current_level >= 2 and not cyber_summary.get("poam_active") and critical_cves == 0 and kev_count == 0:
        posture = "Cyber readiness supported"
    elif cyber_summary.get("poam_active") or critical_cves > 0 or kev_count > 0:
        posture = "Remediation pressure present"
    elif cyber_summary.get("public_evidence_present"):
        posture = "Public assurance evidence in view"

    body_bits = []
    if current_level > 0:
        body_bits.append(f"Customer SPRS evidence reports current CMMC Level {current_level}")
    if cyber_summary.get("assessment_date"):
        body_bits.append(f"assessment date {escape(str(cyber_summary['assessment_date']))}")
    if cyber_summary.get("poam_active"):
        open_items = int(cyber_summary.get("open_poam_items") or 0)
        body_bits.append(
            f"active POA&M{' with ' + str(open_items) + ' open item' + ('s' if open_items != 1 else '') if open_items > 0 else ''}"
        )
    if critical_cves > 0 or kev_count > 0:
        vuln_bits = []
        if critical_cves > 0:
            vuln_bits.append(f"{critical_cves} critical CVE{'s' if critical_cves != 1 else ''}")
        if kev_count > 0:
            vuln_bits.append(f"{kev_count} KEV-linked issue{'s' if kev_count != 1 else ''}")
        body_bits.append("NVD overlay shows " + " and ".join(vuln_bits))
    if cyber_summary.get("public_evidence_present"):
        public_bits = []
        if cyber_summary.get("sbom_present"):
            sbom_desc = str(cyber_summary.get("sbom_format") or "SBOM")
            sbom_age = cyber_summary.get("sbom_fresh_days")
            if isinstance(sbom_age, int) and sbom_age >= 0:
                public_bits.append(f"{sbom_desc} SBOM published ({sbom_age} days old)")
            else:
                public_bits.append(f"{sbom_desc} SBOM published")
        if vex_status and vex_status.lower() not in {"missing", "unknown", "none"}:
            public_bits.append(f"VEX status {vex_status.replace('_', ' ')}")
        if cyber_summary.get("security_txt_present"):
            public_bits.append("security.txt available")
        if cyber_summary.get("psirt_contact_present"):
            public_bits.append("PSIRT contact published")
        if cyber_summary.get("support_lifecycle_published"):
            public_bits.append("support lifecycle published")
        if cyber_summary.get("provenance_attested"):
            public_bits.append("provenance attestation disclosed")
        if public_bits:
            body_bits.append("First-party public assurance evidence shows " + ", ".join(public_bits))
        if not cyber_summary.get("sprs_artifact_id") and not cyber_summary.get("oscal_artifact_id"):
            body_bits.append("Customer-controlled assurance artifacts are still missing")
    if int(cyber_summary.get("open_source_advisory_count") or 0) > 0:
        body_bits.append(
            f"Open-source package intelligence surfaced {int(cyber_summary.get('open_source_advisory_count') or 0)} advisory references across the declared package inventory"
        )
    if int(cyber_summary.get("scorecard_low_repo_count") or 0) > 0:
        body_bits.append(
            f"Repository hygiene remains weak across {int(cyber_summary.get('scorecard_low_repo_count') or 0)} source repositories based on OpenSSF Scorecard"
        )

    body_text = ". ".join(body_bits).strip()
    if body_text and not body_text.endswith("."):
        body_text += "."
    if not body_text:
        body_text = "Customer and first-party public supply chain assurance evidence is available for CMMC, remediation, provenance, and product vulnerability context."

    return f'''
    <section class="storyline-section">
        <div class="storyline-head">
            <div>
                <div class="storyline-topline">Customer cyber / compliance evidence</div>
                <h2>Cyber Evidence Summary</h2>
                <p class="storyline-intro">
                    Helios incorporates customer-provided attestation, remediation, and vulnerability evidence into the supplier trust narrative instead of treating it as a side attachment.
                </p>
            </div>
            <div class="storyline-callout">{escape(posture)}</div>
        </div>
        <div class="storyline-grid" style="grid-template-columns: 1fr;">
            <article class="storyline-card" style="--storyline-accent: #0F766E;">
                <div class="storyline-card-head">
                    <div class="storyline-rank">•</div>
                    <div class="storyline-meta-stack">
                        <div class="storyline-eyebrow">Supply chain assurance evidence</div>
                        <div class="storyline-confidence">Customer artifacts plus first-party public evidence</div>
                    </div>
                </div>
                <div class="storyline-title">Supplier cyber-readiness context</div>
                <div class="storyline-body">{body_text}</div>
                {f'<div class="storyline-sources">{chip_html}</div>' if chip_html else ''}
            </article>
        </div>
    </section>
    '''


def _generate_osint_findings(enrichment: Optional[dict]) -> str:
    """Generate OSINT findings section grouped by source."""
    if not enrichment:
        return ""

    findings = enrichment.get("findings", [])
    if not findings:
        return ""

    material_findings = []
    clear_checks = []
    connector_gaps = []
    for finding in findings:
        if _is_connector_gap_finding(finding):
            connector_gaps.append(finding)
        elif _is_clear_or_low_signal_finding(finding):
            clear_checks.append(finding)
        else:
            material_findings.append(finding)

    # Group material findings by source
    by_source = {}
    for f in material_findings:
        source = f.get("source", "Unknown")
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(f)

    # Sort by severity within each source
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    for source in by_source:
        by_source[source].sort(
            key=lambda f: severity_order.get(f.get("severity", "info"), 5)
        )

    findings_html = ""
    for source in sorted(by_source.keys()):
        source_findings = by_source[source]
        display_name = _source_display_name(source)

        # Border color based on highest severity in this source
        sev_colors = {"critical": "#dc3545", "high": "#C4A052", "medium": "#ffc107", "low": "#0dcaf0"}
        top_sev = source_findings[0].get("severity", "info") if source_findings else "info"
        border_color = sev_colors.get(top_sev, "#dee2e6")

        findings_html += f'''
        <div style="margin-bottom: 16px; border-left: 4px solid {border_color}; padding-left: 16px;">
            <strong style="color: #1a1f36; font-size: 13px;">
                {escape(display_name)}
            </strong>
            <div style="margin-top: 8px;">
        '''

        for f in source_findings:
            severity = f.get("severity", "info").lower()
            category = f.get("category", "")
            confidence = f.get("confidence", 0)

            findings_html += f'''
            <div style="margin-bottom: 12px; padding: 8px;
                        background-color: #f8f9fa; border-radius: 4px;">
                <div style="display: flex; align-items: center; justify-content: space-between;
                            margin-bottom: 4px;">
                    <span style="font-weight: 600; color: #1a1f36;">
                        {escape(f.get('title', 'Finding'))}
                    </span>
                    {_severity_badge(severity)}
                </div>
                {'<div style="font-size: 11px; color: #6c757d; margin-bottom: 4px;">' +
                 escape(category) + '</div>' if category else ''}
                {'<div style="font-size: 12px; color: #1a1f36; margin-bottom: 4px;">' +
                 escape(f.get('detail', '')) + '</div>' if f.get('detail') else ''}
                <div style="display: flex; gap: 12px; font-size: 11px; color: #6c757d;">
                    <span>Confidence: {confidence:.0%}</span>
                    {'<span><a href="' + escape(f.get('url', '')) +
                     '" style="color: #0d6efd; text-decoration: none;">View Source</a></span>'
                     if f.get('url') else ''}
                </div>
            </div>
            '''

        findings_html += '</div></div>'

    clear_checks_html = ""
    if clear_checks:
        by_clear_source = {}
        for finding in clear_checks:
            display_name = _source_display_name(finding.get("source", "Unknown"))
            by_clear_source.setdefault(display_name, []).append(finding)

        clear_items = ""
        for source_name in sorted(by_clear_source.keys()):
            titles = ", ".join(
                escape((item.get("title", "") or "").strip()) for item in by_clear_source[source_name][:3]
            )
            extra = len(by_clear_source[source_name]) - 3
            suffix = f" (+{extra} more)" if extra > 0 else ""
            clear_items += f'''
            <div style="padding: 8px 0; border-bottom: 1px solid #edf1f5; font-size: 12px; color: #445065;">
                <strong style="color: #1a1f36;">{escape(source_name)}</strong><br>
                <span>{titles}{suffix}</span>
            </div>
            '''

        clear_checks_html = f'''
        <details style="margin-top: 18px; border: 1px solid #d9e1ea; border-radius: 10px; background: #f8fafc;">
            <summary style="cursor: pointer; list-style: none; padding: 12px 14px; font-weight: 600; color: #1a1f36;">
                Clear checks &amp; benign returns ({len(clear_checks)})
            </summary>
            <div style="padding: 0 14px 12px;">
                <div style="font-size: 12px; color: #6c757d; margin-bottom: 10px;">
                    These sources returned no material adverse signal and are retained here for auditability without crowding the core narrative.
                </div>
                {clear_items}
            </div>
        </details>
        '''

    connector_gap_html = ""
    if connector_gaps:
        gap_list = "".join(
            f'<li style="margin-bottom: 4px;">{escape(_source_display_name(gap.get("source", "Unknown")))}: {escape(gap.get("detail", "") or gap.get("title", ""))}</li>'
            for gap in connector_gaps
        )
        connector_gap_html = f'''
        <details style="margin-top: 16px; padding: 12px; background: #fff7e6; border-radius: 10px;
                        border: 1px solid #f2d28b; font-size: 12px;">
            <summary style="cursor: pointer; font-weight: 600; color: #8a6116;">
                Connector gaps ({len(connector_gaps)} sources unavailable)
            </summary>
            <ul style="margin: 8px 0 0 16px; padding: 0; color: #856404;">
                {gap_list}
            </ul>
            <div style="margin-top: 8px; font-size: 11px; color: #856404;">
                Configure missing API keys in Admin &rarr; AI Settings to enable these sources.
            </div>
        </details>
        '''

    if not findings_html:
        findings_html = '''
        <div style="padding: 16px 18px; border: 1px solid #dceee4; border-radius: 12px; background: #f6fbf8;">
            <strong style="display: block; color: #0f5132; margin-bottom: 6px;">No material adverse findings surfaced in the configured checks.</strong>
            <div style="font-size: 12px; color: #4c6a58;">
                Helios retained full source coverage below for auditability, but the main intelligence narrative did not surface a materially adverse signal.
            </div>
        </div>
        '''

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #C4A052; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            OSINT Findings
        </h2>

        <div style="font-size: 13px; margin-bottom: 16px; color: #6c757d;">
            Total findings: <strong>{len(findings)}</strong> |
            Material signals: <strong style="color: #1a1f36;">{len(material_findings)}</strong> |
            Clear checks: <strong style="color: #198754;">{len(clear_checks)}</strong> |
            Connector gaps: <strong style="color: #C4A052;">{len(connector_gaps)}</strong> |
            Critical: <strong style="color: #dc3545;">
                {sum(1 for f in material_findings if f.get('severity') == 'critical')}
            </strong> |
            High: <strong style="color: #C4A052;">
                {sum(1 for f in material_findings if f.get('severity') == 'high')}
            </strong> |
            Medium: <strong style="color: #ffc107;">
                {sum(1 for f in material_findings if f.get('severity') == 'medium')}
            </strong>
        </div>

        {findings_html}
        {clear_checks_html}
        {connector_gap_html}
    </section>
    '''


def _generate_normalized_events(events: list[dict]) -> str:
    material_events = [event for event in events if not _is_clear_or_low_signal_event(event)]
    if not material_events:
        return ""

    rows = ""
    for event in material_events[:12]:
        date_range = event.get("date_range") or {}
        date_label = ""
        if date_range.get("start") or date_range.get("end"):
            date_label = f"{date_range.get('start') or '?'} to {date_range.get('end') or '?'}"
        rows += f'''
        <tr>
            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef;">{escape(event.get('event_type', '').replace('_', ' ').title())}</td>
            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef;">{escape(event.get('status', 'active').upper())}</td>
            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef;">{escape(event.get('jurisdiction', ''))}</td>
            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef;">{escape(date_label)}</td>
            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef;">{float(event.get('confidence', 0.0)):.0%}</td>
        </tr>
        '''

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #C4A052; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            Normalized Events
        </h2>
        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
                <tr style="text-align: left; color: #6c757d;">
                    <th style="padding: 8px 0; border-bottom: 2px solid #e9ecef;">Event</th>
                    <th style="padding: 8px 0; border-bottom: 2px solid #e9ecef;">Status</th>
                    <th style="padding: 8px 0; border-bottom: 2px solid #e9ecef;">Jurisdiction</th>
                    <th style="padding: 8px 0; border-bottom: 2px solid #e9ecef;">Date Range</th>
                    <th style="padding: 8px 0; border-bottom: 2px solid #e9ecef;">Confidence</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    </section>
    '''


def _get_dossier_analysis_data(
    vendor_id: str,
    vendor: dict,
    score: Optional[dict],
    enrichment: Optional[dict],
    user_id: str = "",
    hydrate_ai: bool = False,
) -> Optional[dict]:
    """Return cached AI analysis, optionally hydrating it on demand for dossier generation."""
    if not score:
        return None

    try:
        from ai_analysis import analyze_vendor, compute_analysis_fingerprint, get_ai_config, get_latest_analysis
    except ImportError:
        return None

    input_hash = ""
    try:
        input_hash = compute_analysis_fingerprint(vendor, score, enrichment)
        analysis_data = get_latest_analysis(vendor_id, user_id=user_id, input_hash=input_hash)
        if analysis_data or not hydrate_ai:
            return analysis_data

        if not user_id:
            return None

        if get_ai_config(user_id):
            # Do not issue a second live provider call while async warm-up is already in flight.
            # Keep the dossier honest and render the warming state until a real external analysis lands.
            return None

        generated = analyze_vendor(user_id, vendor, score, enrichment)
        refreshed = get_latest_analysis(vendor_id, user_id=user_id, input_hash=input_hash)
        if refreshed:
            return refreshed

        return {
            "analysis": generated.get("analysis", {}),
            "provider": generated.get("provider", "unknown"),
            "model": generated.get("model", "unknown"),
            "prompt_tokens": generated.get("prompt_tokens", 0),
            "completion_tokens": generated.get("completion_tokens", 0),
            "elapsed_ms": generated.get("elapsed_ms", 0),
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": user_id,
            "input_hash": input_hash,
            "prompt_version": generated.get("prompt_version", ""),
        }
    except Exception as e:
        print(f"[dossier] AI analysis lookup/hydration failed: {e}")
        return None


def clear_dossier_context_cache() -> None:
    with _DOSSIER_CONTEXT_CACHE_LOCK:
        _DOSSIER_CONTEXT_CACHE.clear()


def _dossier_ai_cache_stamp(
    vendor_id: str,
    *,
    user_id: str,
    score: Optional[dict],
    enrichment: Optional[dict],
    hydrate_ai: bool,
) -> str:
    if not hydrate_ai or not user_id or not score:
        return ""
    try:
        from ai_analysis import compute_analysis_fingerprint, get_latest_analysis

        vendor = db.get_vendor(vendor_id)
        if not vendor:
            return ""
        input_hash = compute_analysis_fingerprint(vendor, score, enrichment)
        cached = get_latest_analysis(vendor_id, user_id=user_id, input_hash=input_hash)
        if not cached:
            return "pending"
        analysis_id = cached.get("id") or cached.get("created_at") or cached.get("input_hash") or "ready"
        return f"ready:{analysis_id}"
    except Exception:
        return ""


def _dossier_context_cache_key(
    vendor_id: str,
    *,
    user_id: str,
    score: Optional[dict],
    enrichment: Optional[dict],
    hydrate_ai: bool,
) -> tuple[str, str, str, str, str, bool, str]:
    score_stamp = str((score or {}).get("scored_at") or "")
    enrichment_stamp = str((enrichment or {}).get("enriched_at") or "")
    report_hash = compute_report_hash(enrichment) if enrichment else ""
    ai_stamp = _dossier_ai_cache_stamp(
        vendor_id,
        user_id=user_id,
        score=score,
        enrichment=enrichment,
        hydrate_ai=hydrate_ai,
    )
    return (vendor_id, user_id, score_stamp, enrichment_stamp, report_hash, bool(hydrate_ai), ai_stamp)


def _get_cached_dossier_context(cache_key: tuple[str, str, str, str, str, bool, str]) -> Optional[dict]:
    now = time.time()
    with _DOSSIER_CONTEXT_CACHE_LOCK:
        expired = [
            key
            for key, value in _DOSSIER_CONTEXT_CACHE.items()
            if now - float(value.get("cached_at", 0.0) or 0.0) > _DOSSIER_CONTEXT_TTL_SECONDS
        ]
        for key in expired:
            _DOSSIER_CONTEXT_CACHE.pop(key, None)
        cached = _DOSSIER_CONTEXT_CACHE.get(cache_key)
        if not cached:
            return None
        return deepcopy(cached.get("context"))


def _store_cached_dossier_context(
    cache_key: tuple[str, str, str, str, str, bool, str],
    context: dict,
) -> None:
    with _DOSSIER_CONTEXT_CACHE_LOCK:
        _DOSSIER_CONTEXT_CACHE[cache_key] = {
            "cached_at": time.time(),
            "context": deepcopy(context),
        }


def build_dossier_context(vendor_id: str, user_id: str = "", hydrate_ai: bool = False) -> Optional[dict]:
    vendor = db.get_vendor(vendor_id)
    if not vendor:
        return None

    score = db.get_latest_score(vendor_id)
    enrichment = db.get_latest_enrichment(vendor_id)
    cache_key = _dossier_context_cache_key(
        vendor_id,
        user_id=user_id,
        score=score,
        enrichment=enrichment,
        hydrate_ai=hydrate_ai,
    )
    cached = _get_cached_dossier_context(cache_key)
    if cached is not None:
        return cached

    monitoring_history = db.get_monitoring_history(vendor_id, limit=10)
    decisions = db.get_decisions(vendor_id, limit=50)
    report_hash = compute_report_hash(enrichment) if enrichment else ""
    case_events = db.get_case_events(vendor_id, report_hash) if report_hash else []
    intel_summary = db.get_latest_intel_summary(vendor_id, user_id=user_id, report_hash=report_hash) if report_hash else None
    foci_summary = get_latest_foci_summary(vendor_id) if HAS_FOCI_EVIDENCE else None
    cyber_summary = get_latest_cyber_evidence_summary(vendor_id) if HAS_CYBER_EVIDENCE else None
    vendor_input = vendor.get("vendor_input", {}) if isinstance(vendor.get("vendor_input"), dict) else {}
    export_summary = (
        get_export_evidence_summary(vendor_id, vendor_input.get("export_authorization"))
        if HAS_EXPORT_EVIDENCE else None
    )
    storyline = _build_dossier_storyline(vendor_id, vendor, score, enrichment, case_events, intel_summary)
    graph_summary = None
    if HAS_GRAPH_SUMMARY:
        try:
            # The dossier and supplier passport both depend on vendor-scoped claim provenance
            # to keep control paths rooted to the active case instead of dropping them.
            graph_summary = get_vendor_graph_summary(
                vendor_id,
                depth=2,
                include_provenance=True,
                max_claim_records=2,
                max_evidence_records=2,
            )
        except Exception as err:
            print(f"[dossier] Graph provenance lookup failed: {err}")
            graph_summary = None
    supplier_passport = None
    if HAS_SUPPLIER_PASSPORT:
        try:
            supplier_passport = build_supplier_passport(
                vendor_id,
                vendor=vendor,
                score=score,
                enrichment=enrichment,
                foci_summary=foci_summary,
                cyber_summary=cyber_summary,
                export_summary=export_summary,
                graph_summary=graph_summary,
            )
        except Exception as err:
            print(f"[dossier] Supplier passport build failed: {err}")
            supplier_passport = None

    analysis_data = _get_dossier_analysis_data(
        vendor_id,
        vendor,
        score,
        enrichment,
        user_id=user_id,
        hydrate_ai=hydrate_ai,
    )
    analysis_state = "ready" if analysis_data and analysis_data.get("analysis") else "idle"
    if hydrate_ai and user_id and score and not analysis_data:
        try:
            from ai_analysis import get_ai_config

            analysis_state = "warming" if get_ai_config(user_id) else "idle"
        except Exception:
            analysis_state = "idle"

    context = {
        "vendor": vendor,
        "score": score,
        "enrichment": enrichment,
        "decisions": decisions,
        "monitoring_history": monitoring_history,
        "report_hash": report_hash,
        "case_events": case_events,
        "intel_summary": intel_summary,
        "foci_summary": foci_summary,
        "cyber_summary": cyber_summary,
        "export_summary": export_summary,
        "storyline": storyline,
        "graph_summary": graph_summary,
        "supplier_passport": supplier_passport,
        "analysis_data": analysis_data,
        "analysis_state": analysis_state,
    }
    _store_cached_dossier_context(cache_key, context)
    return context


def _generate_ai_narrative(vendor_id: str, vendor: dict, analysis_data: Optional[dict] = None) -> str:
    """Generate a premium Axiom assessment section from cached or freshly hydrated analysis."""
    if not analysis_data:
        return '''
        <section style="page-break-inside: avoid; margin-bottom: 32px;">
            <h2 style="color: #0A1628; border-bottom: 2px solid #C4A052; padding-bottom: 10px;
                       margin-bottom: 16px; font-size: 16px;">
                Axiom Assessment
            </h2>
            <div style="padding: 16px 18px; border-radius: 18px; background: linear-gradient(135deg, #0A1628 0%, #102033 100%);
                        color: white; box-shadow: 0 18px 36px rgba(10, 22, 40, 0.18);">
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px;">
                    <div style="font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: rgba(255,255,255,0.72);">
                        Executive judgment
                    </div>
                    <span style="display: inline-block; padding: 6px 12px; background-color: #64748B; color: white;
                                border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: 0.08em;">
                        PENDING
                    </span>
                </div>
                <div style="font-size: 14px; line-height: 1.75; color: #F8FAFC;">
                    Axiom is still warming for this case. The current posture, supplier passport,
                    and control evidence below are current; rerender once the assessment is ready.
                </div>
            </div>
        </section>
        '''

    analysis = analysis_data.get("analysis", {})
    if not analysis:
        return ""

    provider = analysis_data.get("provider", "unknown")
    model = analysis_data.get("model", "unknown")
    created = analysis_data.get("created_at", "")

    verdict = analysis.get("verdict", "UNKNOWN")
    verdict_colors = {
        "APPROVE": "#198754",
        "CONDITIONAL_APPROVE": "#ffc107",
        "ENHANCED_DUE_DILIGENCE": "#C4A052",
        "REJECT": "#dc3545",
    }
    verdict_color = verdict_colors.get(verdict, "#6c757d")
    verdict_display = verdict.replace("_", " ").title()
    executive_summary = escape(analysis.get("executive_summary", ""))
    risk_narrative = escape(analysis.get("risk_narrative", ""))
    regulatory_exposure = escape(analysis.get("regulatory_exposure", ""))
    confidence_assessment = escape(analysis.get("confidence_assessment", "N/A"))
    critical_concerns = analysis.get("critical_concerns", []) or []
    mitigating_factors = analysis.get("mitigating_factors", []) or []
    recommended_actions = analysis.get("recommended_actions", []) or []

    def _render_signal_list(items: list[str], accent: str, empty_state: str) -> str:
        if not items:
            return (
                f'<div style="padding: 10px 12px; border: 1px dashed #d6dde6; border-radius: 12px; '
                f'font-size: 12px; color: #6b7280; background: rgba(255,255,255,0.7);">{escape(empty_state)}</div>'
            )
        rows = []
        for idx, item in enumerate(items[:5], 1):
            rows.append(
                f'''
                <div style="display: flex; gap: 10px; align-items: flex-start; padding: 10px 0;
                            border-bottom: 1px solid rgba(15, 23, 42, 0.08);">
                    <div style="flex: 0 0 auto; min-width: 24px; height: 24px; border-radius: 999px;
                                background: {accent}; color: white; display: flex; align-items: center;
                                justify-content: center; font-size: 11px; font-weight: 700;">
                        {idx}
                    </div>
                    <div style="font-size: 12px; line-height: 1.65; color: #1f2937;">{escape(item)}</div>
                </div>
                '''
            )
        return "".join(rows)

    risk_narrative_html = ""
    if risk_narrative:
        risk_narrative_html = f'''
        <div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.12);
                    font-size: 12px; line-height: 1.7; color: #D6DEE8;">
            <strong style="display: block; margin-bottom: 4px; color: white;">Why this matters</strong>
            {risk_narrative}
        </div>
        '''

    regulatory_exposure_html = ""
    if regulatory_exposure:
        regulatory_exposure_html = f'''
        <div style="padding: 14px 16px; border-radius: 16px; background: white;
                    border: 1px solid rgba(15, 23, 42, 0.08); margin-bottom: 18px;">
            <strong style="display: block; font-size: 12px; color: #0f172a; margin-bottom: 8px; letter-spacing: 0.08em; text-transform: uppercase;">
                Regulatory and diligence exposure
            </strong>
            <div style="font-size: 12px; color: #1f2937; line-height: 1.75;">
                {regulatory_exposure}
            </div>
        </div>
        '''

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #0A1628; border-bottom: 2px solid #C4A052; padding-bottom: 10px;
                   margin-bottom: 16px; font-size: 16px;">
            Axiom Assessment
        </h2>
        <div style="padding: 10px 14px; background: linear-gradient(135deg, #fff8e7 0%, #fffdf5 100%);
                    border: 1px solid rgba(196, 160, 82, 0.28); border-left: 4px solid #C4A052;
                    border-radius: 12px; margin-bottom: 18px; font-size: 10px; color: #6B7280;
                    line-height: 1.6;">
            <strong style="color: #C4A052; letter-spacing: 0.06em;">AXIOM</strong> &mdash;
            This assessment complements the deterministic scoring engine, regulatory gates, and evidence-backed storyline.
            It adds qualitative judgment, narrative synthesis, and diligence guidance without overriding hard stops or tier classification.
        </div>

        <div style="display: grid; grid-template-columns: 1.5fr 1fr; gap: 14px; margin-bottom: 18px;">
            <div style="padding: 16px 18px; border-radius: 18px; background: linear-gradient(135deg, #0A1628 0%, #102033 100%);
                        color: white; box-shadow: 0 18px 36px rgba(10, 22, 40, 0.18);">
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px;">
                    <div style="font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: rgba(255,255,255,0.72);">
                        Executive judgment
                    </div>
                    <span style="display: inline-block; padding: 6px 12px; background-color: {verdict_color}; color: white;
                                border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: 0.08em;">
                        {verdict_display}
                    </span>
                </div>
                <div style="font-size: 15px; line-height: 1.75; color: #F8FAFC;">
                    {executive_summary}
                </div>
                {risk_narrative_html}
            </div>
            <div style="display: grid; gap: 10px;">
                <div style="padding: 14px 16px; border-radius: 16px; background: white; border: 1px solid rgba(15, 23, 42, 0.08);">
                    <div style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Confidence</div>
                    <div style="margin-top: 6px; font-size: 13px; line-height: 1.65; color: #0f172a;">{confidence_assessment}</div>
                </div>
                <div style="padding: 14px 16px; border-radius: 16px; background: white; border: 1px solid rgba(15, 23, 42, 0.08);">
                    <div style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Coverage</div>
                    <div style="margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap;">
                        <span style="display: inline-block; padding: 6px 10px; border-radius: 999px; background: rgba(220, 53, 69, 0.08);
                                     color: #dc3545; font-size: 11px; font-weight: 700;">{len(critical_concerns)} concern{'s' if len(critical_concerns) != 1 else ''}</span>
                        <span style="display: inline-block; padding: 6px 10px; border-radius: 999px; background: rgba(25, 135, 84, 0.08);
                                     color: #198754; font-size: 11px; font-weight: 700;">{len(mitigating_factors)} offset{'s' if len(mitigating_factors) != 1 else ''}</span>
                        <span style="display: inline-block; padding: 6px 10px; border-radius: 999px; background: rgba(13, 110, 253, 0.08);
                                     color: #0d6efd; font-size: 11px; font-weight: 700;">{len(recommended_actions)} action{'s' if len(recommended_actions) != 1 else ''}</span>
                    </div>
                    <div style="margin-top: 10px; font-size: 10px; color: #6b7280; line-height: 1.6;">
                        Provider {escape(provider)} / {escape(model)}<br>
                        Generated {escape(_format_timestamp_value(created))}
                    </div>
                </div>
            </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px;">
            <div style="padding: 16px; border-radius: 16px; background: rgba(220, 53, 69, 0.04); border: 1px solid rgba(220, 53, 69, 0.12);">
                <strong style="display: block; font-size: 12px; color: #dc3545; margin-bottom: 10px;">Critical concerns</strong>
                {_render_signal_list(critical_concerns, "#dc3545", "No material qualitative concerns surfaced beyond the deterministic case posture.")}
            </div>
            <div style="padding: 16px; border-radius: 16px; background: rgba(25, 135, 84, 0.04); border: 1px solid rgba(25, 135, 84, 0.12);">
                <strong style="display: block; font-size: 12px; color: #198754; margin-bottom: 10px;">Mitigating factors</strong>
                {_render_signal_list(mitigating_factors, "#198754", "No distinct qualitative offsets were added beyond the underlying score and storyline.")}
            </div>
            <div style="padding: 16px; border-radius: 16px; background: rgba(13, 110, 253, 0.04); border: 1px solid rgba(13, 110, 253, 0.12);">
                <strong style="display: block; font-size: 12px; color: #0d6efd; margin-bottom: 10px;">Recommended actions</strong>
                {_render_signal_list(recommended_actions, "#0d6efd", "No additional qualitative diligence steps were added by the AI brief.")}
            </div>
        </div>

        {regulatory_exposure_html}
    </section>
    '''


def _generate_audit_trail(vendor_id: str, score: dict, enrichment: Optional[dict]) -> str:
    """Generate audit trail with enrichment history."""
    score_history = db.get_score_history(vendor_id, limit=5)
    enrichment_history = db.get_enrichment_history(vendor_id, limit=5)

    audit_html = """
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;">
    """

    # Scoring history
    audit_html += """
    <div style="border: 1px solid #dee2e6; border-radius: 4px; padding: 12px;">
        <strong style="font-size: 13px;">Scoring History</strong>
        <div style="margin-top: 8px; font-size: 12px;">
    """
    for entry in score_history:
        audit_html += f'''
        <div style="padding: 4px 0; border-bottom: 1px solid #e9ecef;">
            {escape(_format_timestamp_value(entry.get('scored_at')))} –
            {_tier_badge(entry.get('calibrated_tier', 'unknown'))}
        </div>
        '''
    audit_html += "</div></div>"

    # Enrichment history
    audit_html += """
    <div style="border: 1px solid #dee2e6; border-radius: 4px; padding: 12px;">
        <strong style="font-size: 13px;">Enrichment History</strong>
        <div style="margin-top: 8px; font-size: 12px;">
    """
    for entry in enrichment_history:
        audit_html += f'''
        <div style="padding: 4px 0; border-bottom: 1px solid #e9ecef;">
            {escape(_format_timestamp_value(entry.get('enriched_at')))} –
            {entry.get('findings_total', 0)} findings,
            {_severity_badge(entry.get('overall_risk', 'LOW').lower())}
        </div>
        '''
    audit_html += "</div></div></div>"

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #C4A052; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            Audit Trail
        </h2>
        {audit_html}
        <div style="padding: 12px; background-color: #f8f9fa; border-radius: 4px; font-size: 12px;
                    color: #6c757d;">
            <strong>Data Freshness:</strong> Latest scoring and enrichment shown above.
            Reports generated on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}.
        </div>
    </section>
    '''


def _generate_data_freshness(enrichment: Optional[dict], score: dict) -> str:
    """Generate a data freshness and confidence assessment section."""
    if not enrichment:
        return ""

    connector_status = enrichment.get("connector_status", {})
    enriched_at = enrichment.get("enriched_at", "")
    total_elapsed_ms = enrichment.get("total_elapsed_ms", 0)

    # Categorize connectors
    successful = []
    failed = []
    for name, status in sorted(connector_status.items()):
        display = _source_display_name(name)
        if status.get("error"):
            failed.append({"name": display, "error": _summarize_connector_error(status["error"])})
        else:
            successful.append({
                "name": display,
                "findings": status.get("findings_count", 0),
                "elapsed_ms": status.get("elapsed_ms", 0),
            })

    # Overall confidence assessment
    total_connectors = len(connector_status)
    success_rate = len(successful) / max(total_connectors, 1)
    if success_rate >= 0.9:
        confidence_level = "HIGH"
        confidence_color = "#198754"
        confidence_desc = "Comprehensive coverage across all major intelligence sources."
    elif success_rate >= 0.7:
        confidence_level = "MODERATE"
        confidence_color = "#C4A052"
        confidence_desc = "Good coverage with some sources unavailable. Review connector gaps below."
    else:
        confidence_level = "LOW"
        confidence_color = "#dc3545"
        confidence_desc = "Significant gaps in source coverage. Results should be treated as preliminary."

    # Confidence interval from score
    cal = score.get("calibrated", {}) if score else {}
    ci_lo = cal.get("interval", {}).get("lower", 0)
    ci_hi = cal.get("interval", {}).get("upper", 0)
    with_signal = [s for s in successful if s["findings"] > 0]
    checked_clear = [s for s in successful if s["findings"] <= 0]
    enriched_label = escape(_format_timestamp_value(enriched_at))
    slowest = sorted(successful, key=lambda item: item["elapsed_ms"], reverse=True)[:5]

    source_pills = "".join(
        f'<span class="source-pill">{escape(item["name"])}</span>'
        for item in sorted(successful, key=lambda item: (-item["findings"], item["name"]))[:10]
    )
    signal_rows = "".join(
        f'''
        <tr>
            <td>{escape(item["name"])}</td>
            <td style="text-align:center;">{item["findings"]}</td>
            <td style="text-align:right;">{item["elapsed_ms"]}ms</td>
        </tr>
        '''
        for item in sorted(with_signal, key=lambda item: (-item["findings"], item["name"]))[:6]
    )
    failed_rows = "".join(
        f'''
        <div class="ops-note ops-note-warn">
            <strong>{escape(item["name"])}</strong>
            <span>{escape(item["error"])}</span>
        </div>
        '''
        for item in failed
    )
    slow_rows = "".join(
        f'''
        <tr>
            <td>{escape(item["name"])}</td>
            <td style="text-align:center;">{"Signal" if item["findings"] > 0 else "Clear"}</td>
            <td style="text-align:right;">{item["elapsed_ms"]}ms</td>
        </tr>
        '''
        for item in slowest
    )
    signal_band_html = ""
    if with_signal:
        signal_band_html = f'''
        <div class="coverage-band">
            <div class="coverage-band-title">Sources with the strongest signal</div>
            <table class="ops-table">
                <thead>
                    <tr>
                        <th>Source</th>
                        <th style="text-align:center;">Findings</th>
                        <th style="text-align:right;">Latency</th>
                    </tr>
                </thead>
                <tbody>{signal_rows}</tbody>
            </table>
        </div>
        '''
    failed_band_html = ""
    if failed:
        failed_band_html = f'''
        <div class="coverage-band">
            <div class="coverage-band-title">Unavailable sources</div>
            <div class="ops-stack">{failed_rows}</div>
        </div>
        '''

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #C4A052; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            Coverage &amp; Freshness
        </h2>

        <div class="coverage-grid">
            <div class="coverage-card">
                <div class="coverage-card-label">Assessment confidence</div>
                <div class="coverage-card-value" style="color: {confidence_color};">{confidence_level}</div>
                <div class="coverage-card-note">{confidence_desc}</div>
            </div>
            <div class="coverage-card">
                <div class="coverage-card-label">Source coverage</div>
                <div class="coverage-card-value">{len(successful)}/{total_connectors}</div>
                <div class="coverage-card-note">{len(with_signal)} with signal, {len(checked_clear)} clear, {len(failed)} unavailable</div>
            </div>
            <div class="coverage-card">
                <div class="coverage-card-label">Freshness</div>
                <div class="coverage-card-value">{enriched_label}</div>
                <div class="coverage-card-note">Completed in {total_elapsed_ms/1000:.1f}s</div>
            </div>
            <div class="coverage-card">
                <div class="coverage-card-label">Model interval</div>
                <div class="coverage-card-value">{ci_lo:.1%} – {ci_hi:.1%}</div>
                <div class="coverage-card-note">Posterior confidence band</div>
            </div>
        </div>

        <div class="coverage-band">
            <div class="coverage-band-title">Primary sources checked</div>
            <div class="source-pill-row">{source_pills}</div>
        </div>

        {signal_band_html}
        {failed_band_html}

        <details style="margin-top: 16px; border: 1px solid #d9e1ea; border-radius: 12px; background: #f8fafc;">
            <summary style="cursor: pointer; list-style: none; padding: 12px 14px; font-weight: 600; color: #1a1f36;">
                Operational connector log
            </summary>
            <div style="padding: 0 14px 12px;">
                <div style="font-size: 12px; color: #6c757d; margin-bottom: 10px;">
                    Slowest responding sources from the enrichment run. Use this section for technical auditability, not headline risk interpretation.
                </div>
                <table class="ops-table">
                    <thead>
                        <tr>
                            <th>Source</th>
                            <th style="text-align:center;">Result</th>
                            <th style="text-align:right;">Latency</th>
                        </tr>
                    </thead>
                    <tbody>{slow_rows}</tbody>
                </table>
            </div>
        </details>
    </section>
    '''


def generate_dossier(vendor_id: str, user_id: str = "", hydrate_ai: bool = False) -> str:
    from helios_core.brief_engine import generate_html_brief

    return generate_html_brief(vendor_id, user_id=user_id, hydrate_ai=hydrate_ai)
