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
            "title": "Export authorization dossier",
            "summary_name": "export authorization workflow",
        }
    if has_cyber_lane:
        return {
            "label": "Supply chain assurance",
            "title": "Supply chain assurance dossier",
            "summary_name": "supply chain assurance workflow",
        }
    return {
        "label": "Defense counterparty trust",
        "title": "Defense counterparty trust dossier",
        "summary_name": "defense counterparty trust workflow",
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
            "eyebrow": "Current workflow lane",
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
            "eyebrow": "Current workflow lane",
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
        "eyebrow": "Current workflow lane",
        "title": "Defense counterparty trust",
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


def _graph_rel_label(rel_type: str) -> str:
    return rel_type.replace("_", " ").title()


def _graph_entity_name(entity_map: dict[str, dict], entity_id: str) -> str:
    entity = entity_map.get(entity_id) or {}
    return str(entity.get("canonical_name") or entity_id)


def _graph_relationship_priority(rel: dict) -> float:
    corroboration = float(rel.get("corroboration_count") or len(rel.get("data_sources", []) or []) or 1)
    confidence = float(rel.get("confidence") or 0.0)
    rel_type = str(rel.get("rel_type") or "")
    control_bonus = 100 if rel_type in GRAPH_CONTROL_PATH_RELATIONSHIPS else 0
    sanction_bonus = 120 if rel_type in {"sanctioned_on", "sanctioned_person"} else 0
    return sanction_bonus + control_bonus + corroboration * 12 + confidence * 100


def _generate_graph_provenance_section(graph_summary: Optional[dict]) -> str:
    if not isinstance(graph_summary, dict):
        return ""

    relationships = graph_summary.get("relationships") or []
    entities = graph_summary.get("entities") or []
    intelligence = graph_summary.get("intelligence") if isinstance(graph_summary.get("intelligence"), dict) else {}
    if not isinstance(relationships, list) or not relationships:
        return ""

    entity_map = {
        str(entity.get("id")): entity
        for entity in entities
        if isinstance(entity, dict) and entity.get("id")
    }

    source_counts: dict[str, int] = {}
    corroborated_count = 0
    control_path_count = 0
    for rel in relationships:
        data_sources = rel.get("data_sources") or []
        if not data_sources and rel.get("data_source"):
            data_sources = [rel.get("data_source")]
        corroboration_count = int(rel.get("corroboration_count") or len(data_sources) or 1)
        if corroboration_count > 1:
            corroborated_count += 1
        if str(rel.get("rel_type") or "") in GRAPH_CONTROL_PATH_RELATIONSHIPS:
            control_path_count += 1
        for source in data_sources:
            if not source:
                continue
            source_counts[source] = source_counts.get(source, 0) + 1

    top_sources = sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    highlighted_relationships = sorted(
        relationships,
        key=_graph_relationship_priority,
        reverse=True,
    )[:6]

    claim_coverage = float(intelligence.get("claim_coverage_pct") or 0.0)
    missing_families = intelligence.get("missing_required_edge_families") if isinstance(intelligence.get("missing_required_edge_families"), list) else []
    edge_family_counts = intelligence.get("edge_family_counts") if isinstance(intelligence.get("edge_family_counts"), dict) else {}
    metric_cards = [
        ("Relationships", graph_summary.get("relationship_count") or len(relationships)),
        ("Corroborated", corroborated_count),
        ("Edge families", len(edge_family_counts)),
        ("Claim-backed", f"{round(claim_coverage * 100)}%"),
    ]
    metric_html = "".join(
        f"""
        <div style=\"padding: 14px; border: 1px solid #e9ecef; border-radius: 10px; background: #f8fafc;\">
            <div style=\"font-size: 11px; color: #6c757d; text-transform: uppercase; letter-spacing: 0.06em;\">{escape(label)}</div>
            <div style=\"font-size: 24px; font-weight: 700; color: #1a1f36; margin-top: 4px;\">{escape(str(value))}</div>
        </div>
        """
        for label, value in metric_cards
    )

    source_html = ""
    if top_sources:
        source_html = "".join(
            f'<span style="display:inline-flex; padding:4px 8px; border-radius:999px; background:#eef2ff; color:#1d4ed8; font-size:11px; font-weight:700;">{escape(_source_display_name(source))} · {count}</span>'
            for source, count in top_sources
        )
        source_html = f'<div style="display:flex; gap:8px; flex-wrap:wrap; margin-top: 10px;">{source_html}</div>'

    graph_health_parts: list[str] = []
    if intelligence:
        if intelligence.get("workflow_lane"):
            graph_health_parts.append(f"Lane: {str(intelligence.get('workflow_lane') or '').replace('_', ' ')}")
        if intelligence.get("thin_graph"):
            graph_health_parts.append("Graph is thin enough that silence should not be treated as comfort.")
        if missing_families:
            graph_health_parts.append(
                "Missing lane edge families: "
                + ", ".join(str(family).replace("_", " ") for family in missing_families)
            )
        if int(intelligence.get("legacy_unscoped_edge_count") or 0) > 0:
            graph_health_parts.append(
                f"{int(intelligence.get('legacy_unscoped_edge_count') or 0)} legacy unscoped edge(s) are still visible."
            )
        if int(intelligence.get("stale_edge_count") or 0) > 0:
            graph_health_parts.append(
                f"{int(intelligence.get('stale_edge_count') or 0)} stale edge(s) need refresh."
            )
        if int(intelligence.get("contradicted_edge_count") or 0) > 0:
            graph_health_parts.append(
                f"{int(intelligence.get('contradicted_edge_count') or 0)} contradicted edge(s) are present."
            )
    graph_health_html = (
        f'<div style="margin-top:10px; font-size:12px; color:#475569; line-height:1.55;">{"<br/>".join(escape(part) for part in graph_health_parts)}</div>'
        if graph_health_parts
        else ""
    )
    family_html = ""
    if edge_family_counts:
        family_html = "".join(
            f'<span style="display:inline-flex; padding:4px 8px; border-radius:999px; background:#f8fafc; color:#0f172a; border:1px solid #dbe4ee; font-size:11px; font-weight:700;">{escape(str(family).replace("_", " "))} · {count}</span>'
            for family, count in sorted(edge_family_counts.items(), key=lambda item: (-int(item[1]), item[0]))[:6]
        )
        family_html = (
            '<div style="display:flex; gap:8px; flex-wrap:wrap; margin-top: 10px;">'
            + family_html
            + '</div>'
        )

    rows_html = ""
    for rel in highlighted_relationships:
        data_sources = rel.get("data_sources") or []
        if not data_sources and rel.get("data_source"):
            data_sources = [rel.get("data_source")]
        evidence_summary = str(rel.get("evidence_summary") or rel.get("evidence") or "").strip()
        if len(evidence_summary) > 240:
            evidence_summary = evidence_summary[:237].rstrip() + "..."
        rows_html += f"""
        <div style=\"padding: 14px; border: 1px solid #e9ecef; border-radius: 10px; background: #ffffff;\">
            <div style=\"display:flex; justify-content:space-between; gap:12px; align-items:flex-start; flex-wrap:wrap;\">
                <div style=\"font-size: 13px; font-weight: 700; color: #1a1f36;\">
                    {escape(_graph_entity_name(entity_map, str(rel.get('source_entity_id') or '')))}
                    <span style=\"color:#6c757d; font-weight:500;\"> → </span>
                    {escape(_graph_entity_name(entity_map, str(rel.get('target_entity_id') or '')))}
                </div>
                <div style=\"display:flex; gap:8px; flex-wrap:wrap;\">
                    <span style=\"display:inline-flex; padding:4px 8px; border-radius:999px; background:#fff7ed; color:#c2410c; font-size:11px; font-weight:700;\">{escape(_graph_rel_label(str(rel.get('rel_type') or 'related_entity')))}</span>
                    <span style=\"display:inline-flex; padding:4px 8px; border-radius:999px; background:#fffbeb; color:#b45309; font-size:11px; font-weight:700;\">{int(rel.get('corroboration_count') or len(data_sources) or 1)} records</span>
                </div>
            </div>
            {f'<div style="margin-top:8px; font-size:12px; color:#1a1f36; line-height:1.55;">{escape(evidence_summary)}</div>' if evidence_summary else ''}
            <div style=\"display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-top:8px; font-size:11px; color:#6c757d;\">
                <div>
                    First seen: {escape(str(rel.get('first_seen_at') or rel.get('created_at') or 'Unknown'))}
                    &nbsp;|&nbsp;
                    Last seen: {escape(str(rel.get('last_seen_at') or rel.get('created_at') or 'Unknown'))}
                </div>
                <div>{escape(', '.join(_source_display_name(source) for source in data_sources[:3]))}</div>
            </div>
        </div>
        """

    return f"""
    <section style=\"page-break-inside: avoid; margin-bottom: 32px;\">
        <h2 style=\"color: #1a1f36; border-bottom: 3px solid #C4A052; padding-bottom: 12px; margin-bottom: 20px; font-size: 18px;\">
            Graph Provenance Snapshot
        </h2>
        <div style=\"font-size: 13px; color: #4b5563; margin-bottom: 14px;\">
            Corroborated relationship view across the case graph. This is the shortest path from raw connector output to a defensible analyst narrative.
        </div>
        <div style=\"display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px;\">
            {metric_html}
        </div>
        {source_html}
        {family_html}
        {graph_health_html}
        <div style=\"display:grid; gap:10px; margin-top: 14px;\">
            {rows_html}
        </div>
    </section>
    """


def _passport_field(label: str, value: str) -> str:
    return f"""
    <div style=\"padding: 12px 14px; border: 1px solid #e9ecef; border-radius: 10px; background: #ffffff;\">
        <div style=\"font-size: 11px; color: #6c757d; text-transform: uppercase; letter-spacing: 0.06em;\">{escape(label)}</div>
        <div style=\"font-size: 14px; font-weight: 700; color: #1a1f36; margin-top: 4px;\">{escape(value)}</div>
    </div>
    """


def _identifier_state_label(item: dict | None) -> str:
    if isinstance(item, dict):
        label = str(item.get("verification_label") or "").strip()
        if label:
            return label
        state = str(item.get("state") or "missing")
        authority = str(item.get("authority_level") or "")
    else:
        state = str(item or "missing")
        authority = ""
    normalized = state.lower()
    authority = authority.lower()
    if normalized == "verified_present":
        if authority == "first_party_self_disclosed":
            return "Publicly disclosed"
        if authority in {"third_party_public", "public_registry_aggregator"}:
            return "Publicly captured"
        return "Verified"
    if normalized == "verified_absent":
        return "Verified absent"
    if normalized == "unverified":
        return "Unverified"
    return "Missing"


def _render_identifier_status_rows(identity: dict) -> str:
    identifiers = identity.get("identifiers") if isinstance(identity.get("identifiers"), dict) else {}
    identifier_status = identity.get("identifier_status") if isinstance(identity.get("identifier_status"), dict) else {}
    if not identifier_status and identifiers:
        identifier_status = {
            key: {
                "state": "verified_present",
                "value": value,
                "source": None,
                "reason": None,
                "next_access_time": None,
            }
            for key, value in identifiers.items()
            if value not in (None, "")
        }

    ordered_keys = [key for key in ("cage", "uei", "duns", "ncage", "lei", "cik", "website") if key in identifier_status]
    ordered_keys.extend(key for key in identifier_status.keys() if key not in ordered_keys)
    if not ordered_keys:
        return '<div style="font-size: 13px; color: #1a1f36; margin-top: 4px; line-height: 1.55;">No captured identifiers yet</div>'

    rows = ""
    for key in ordered_keys:
        item = identifier_status.get(key)
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "missing")
        value = item.get("value")
        source = str(item.get("source") or "").strip()
        reason = str(item.get("reason") or "").strip()
        next_access_time = str(item.get("next_access_time") or "").strip()
        primary = str(value) if value not in (None, "") else _identifier_state_label(item)
        meta_parts = []
        if source:
            meta_parts.append(_source_display_name(source))
        if state == "unverified" and reason:
            meta_parts.append(reason)
        elif state == "verified_absent" and source:
            meta_parts.append("No verified value returned")
        if next_access_time:
            meta_parts.append(f"Retry after {next_access_time}")
        meta = " · ".join(part for part in meta_parts if part)
        rows += f"""
        <div style="display:flex; justify-content:space-between; gap:14px; padding:10px 0; border-bottom:1px solid #e9ecef; align-items:flex-start;">
            <div style="min-width:96px; font-size:11px; color:#6c757d; text-transform:uppercase; letter-spacing:0.06em;">{escape(key)}</div>
            <div style="flex:1; text-align:right;">
                <div style="font-size:13px; color:#1a1f36; font-weight:700;">{escape(primary)}</div>
                {f'<div style="font-size:11px; color:#6b7280; margin-top:4px; line-height:1.45;">{escape(meta)}</div>' if meta else ''}
            </div>
        </div>
        """
    return rows


def _render_official_corroboration(identity: dict) -> str:
    official = (
        identity.get("official_corroboration")
        if isinstance(identity.get("official_corroboration"), dict)
        else {}
    )
    if not official:
        return ""

    coverage_label = str(official.get("coverage_label") or "No official corroboration captured")
    verified = [str(item).upper() for item in (official.get("official_identifiers_verified") or []) if item]
    public_only = [str(item).upper() for item in (official.get("public_capture_fields") or []) if item]
    blocked = official.get("blocked_connectors") if isinstance(official.get("blocked_connectors"), list) else []
    country_hints = [str(item).upper() for item in (official.get("country_hints") or []) if item]
    relevant_connector_count = int(official.get("relevant_official_connector_count") or official.get("official_connector_count") or 0)
    relevant_connectors_with_data = int(
        official.get("relevant_official_connectors_with_data")
        or official.get("official_connectors_with_data")
        or 0
    )
    blocked_labels = [
        str(item.get("label") or item.get("source") or "").strip()
        for item in blocked
        if isinstance(item, dict)
    ]
    meta_parts = [
        f"{relevant_connector_count} relevant official connectors checked",
        f"{relevant_connectors_with_data} with data",
    ]
    if blocked:
        meta_parts.append(f"{len(blocked)} relevant blocked")
    summary_lines = [coverage_label, " · ".join(meta_parts)]
    if country_hints:
        summary_lines.append(f"Jurisdiction hints: {', '.join(country_hints)}")
    if verified:
        summary_lines.append(f"Officially corroborated: {', '.join(verified)}")
    if public_only:
        summary_lines.append(f"Public capture only: {', '.join(public_only)}")
    if blocked_labels:
        summary_lines.append(f"Relevant blocked official checks: {', '.join(blocked_labels)}")
    body = "<br/>".join(escape(line) for line in summary_lines if line)
    return f"""
        <div style=\"margin-top: 14px; padding: 12px 14px; border-radius: 10px; background: #f8fafc; border: 1px solid #e9ecef;\">
            <div style=\"font-size: 11px; color: #6c757d; text-transform: uppercase; letter-spacing: 0.06em;\">Official corroboration</div>
            <div style=\"margin-top: 6px; font-size: 13px; color: #1a1f36; line-height: 1.6;\">{body}</div>
        </div>
    """


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


def _render_threat_intel_summary(threat_intel: dict) -> str:
    if not isinstance(threat_intel, dict) or not threat_intel.get("shared_threat_intel_present"):
        return ""

    actors = ", ".join(str(item) for item in (threat_intel.get("attack_actor_families") or [])[:3])
    techniques = ", ".join(str(item) for item in (threat_intel.get("attack_technique_ids") or [])[:4])
    advisories = ", ".join(str(item) for item in (threat_intel.get("cisa_advisory_ids") or [])[:3])
    pressure = str(threat_intel.get("threat_pressure") or "unknown").replace("_", " ").title()
    sources = ", ".join(_source_display_name(str(source)) for source in (threat_intel.get("threat_intel_sources") or [])[:3])
    sectors = ", ".join(str(item) for item in (threat_intel.get("threat_sectors") or [])[:3])

    rows = "".join(
        [
            _passport_field("Threat pressure", pressure),
            _passport_field("Actor families", actors or "None surfaced"),
            _passport_field("ATT&CK techniques", techniques or "None surfaced"),
            _passport_field("CISA advisories", advisories or "None surfaced"),
            _passport_field("Sectors", sectors or "None surfaced"),
            _passport_field("Sources", sources or "No threat-intel sources"),
        ]
    )
    return f"""
        <div style=\"margin-top: 14px; padding: 12px 14px; border-radius: 10px; background: #f8fafc; border: 1px solid #e9ecef;\">
            <div style=\"font-size: 11px; color: #6c757d; text-transform: uppercase; letter-spacing: 0.06em;\">Threat context</div>
            <div style=\"display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:10px; margin-top: 8px;\">
                {rows}
            </div>
        </div>
    """


def _render_ownership_control_summary(ownership: dict) -> str:
    if not isinstance(ownership, dict):
        return ""
    oci = ownership.get("oci") if isinstance(ownership.get("oci"), dict) else {}
    if not oci:
        return ""
    analyst_readout = str(ownership.get("analyst_readout") or "").strip()
    named_owner = str(oci.get("named_beneficial_owner") or "Unknown")
    owner_class = str(oci.get("owner_class") or "Unknown")
    controlling_parent = str(oci.get("controlling_parent") or "Unknown")
    ownership_pct = float(oci.get("ownership_resolution_pct") or 0.0)
    control_pct = float(oci.get("control_resolution_pct") or 0.0)
    gap = str(oci.get("ownership_gap") or "unknown").replace("_", " ")
    descriptor_only = "Yes" if oci.get("descriptor_only") else "No"
    owner_class_evidence = (
        oci.get("owner_class_evidence")
        if isinstance(oci.get("owner_class_evidence"), list)
        else []
    )
    rows = "".join(
        [
            _passport_field("Named owner", "Known" if oci.get("named_beneficial_owner_known") else "Unknown"),
            _passport_field("Named owner entity", named_owner),
            _passport_field("Owner class", owner_class if oci.get("owner_class_known") else "Unknown"),
            _passport_field("Controlling parent", controlling_parent if oci.get("controlling_parent_known") else "Unknown"),
            _passport_field("Descriptor-only", descriptor_only),
            _passport_field("Ownership gap", gap.title()),
            _passport_field("Ownership resolved", f"{round(ownership_pct * 100)}%"),
            _passport_field("Control resolved", f"{round(control_pct * 100)}%"),
        ]
    )
    notes: list[str] = []
    if analyst_readout:
        notes.append(analyst_readout)
    if oci.get("descriptor_only"):
        notes.append("Descriptor-only evidence was captured without inventing a named owner.")
    rejected = oci.get("rejected_descriptor_relationships") if isinstance(oci.get("rejected_descriptor_relationships"), list) else []
    if rejected:
        notes.append(f"{len(rejected)} descriptor-like ownership targets were rejected as non-entities.")
    notes.append(f"Current ownership gap: {gap}.")
    note_html = "<br/>".join(escape(note) for note in notes if note)
    evidence_cards = "".join(
        [
            f"""
            <div style=\"padding: 10px 12px; border-radius: 8px; background: #ffffff; border: 1px solid #dbe4ee;\">
                <div style=\"font-size: 12px; font-weight: 600; color: #0f172a;\">{escape(str(item.get('descriptor') or item.get('title') or 'Owner class evidence'))}</div>
                <div style=\"font-size: 11px; color: #475569; margin-top: 4px;\">{escape(str(item.get('title') or 'First-party ownership descriptor evidence'))}</div>
                <div style=\"font-size: 11px; color: #64748b; margin-top: 4px;\">Source: {escape(str(item.get('source') or 'unknown'))} | Confidence: {float(item.get('confidence') or 0.0):.2f}</div>
                <div style=\"font-size: 11px; color: #334155; margin-top: 4px; overflow-wrap: anywhere;\">{escape(str(item.get('artifact') or item.get('url') or ''))}</div>
            </div>
            """
            for item in owner_class_evidence[:3]
            if isinstance(item, dict)
        ]
    )
    evidence_html = (
        f"""
            <div style=\"margin-top: 10px;\">
                <div style=\"font-size: 11px; color: #6c757d; text-transform: uppercase; letter-spacing: 0.06em;\">Owner-class evidence</div>
                <div style=\"display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:10px; margin-top: 8px;\">
                    {evidence_cards}
                </div>
            </div>
        """
        if evidence_cards
        else ""
    )
    return f"""
        <div style=\"margin-top: 14px; padding: 12px 14px; border-radius: 10px; background: #f8fafc; border: 1px solid #e9ecef;\">
            <div style=\"font-size: 11px; color: #6c757d; text-transform: uppercase; letter-spacing: 0.06em;\">Ownership / control intelligence</div>
            <div style=\"display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:10px; margin-top: 8px;\">
                {rows}
            </div>
            <div style=\"margin-top: 8px; font-size: 12px; color: #475569; line-height: 1.5;\">{note_html}</div>
            {evidence_html}
        </div>
    """


def _generate_supplier_passport_section(passport: Optional[dict]) -> str:
    if not isinstance(passport, dict):
        return ""

    vendor = passport.get("vendor") if isinstance(passport.get("vendor"), dict) else {}
    score = passport.get("score") if isinstance(passport.get("score"), dict) else {}
    identity = passport.get("identity") if isinstance(passport.get("identity"), dict) else {}
    ownership = passport.get("ownership") if isinstance(passport.get("ownership"), dict) else {}
    graph = passport.get("graph") if isinstance(passport.get("graph"), dict) else {}
    threat_intel = passport.get("threat_intel") if isinstance(passport.get("threat_intel"), dict) else {}
    artifacts = passport.get("artifacts") if isinstance(passport.get("artifacts"), dict) else {}
    monitoring = passport.get("monitoring") if isinstance(passport.get("monitoring"), dict) else {}
    tribunal = passport.get("tribunal") if isinstance(passport.get("tribunal"), dict) else {}
    workflow_control = ownership.get("workflow_control") if isinstance(ownership.get("workflow_control"), dict) else {}
    control_paths = graph.get("control_paths") if isinstance(graph.get("control_paths"), list) else []
    control_path_summary = graph.get("control_path_summary") if isinstance(graph.get("control_path_summary"), dict) else {}
    claim_health = graph.get("claim_health") if isinstance(graph.get("claim_health"), dict) else {}

    posture = str(passport.get("posture") or "pending").replace("_", " ").title()
    probability = score.get("calibrated_probability")
    probability_label = f"{float(probability) * 100:.1f}%" if isinstance(probability, (int, float)) else "Unknown"
    latest_check = monitoring.get("latest_check") if isinstance(monitoring.get("latest_check"), dict) else {}
    latest_check_text = str(latest_check.get("checked_at") or "No monitoring yet")

    metric_grid = "".join(
        [
            _passport_field("Posture", posture),
            _passport_field("Tier", str(score.get("calibrated_tier") or "Pending").replace("_", " ")),
            _passport_field("Risk estimate", probability_label),
            _passport_field("Program", str(vendor.get("program_label") or vendor.get("program") or "Unknown")),
            _passport_field("Connectors with data", str(identity.get("connectors_with_data", 0))),
            _passport_field("Graph control paths", str(len(control_paths))),
            _passport_field("Artifacts", str(artifacts.get("count", 0))),
            _passport_field("Latest monitoring", latest_check_text),
        ]
    )
    focus_lines: list[str] = []
    financing_count = int(control_path_summary.get("financing_count") or 0)
    intermediary_count = int(control_path_summary.get("intermediary_count") or 0)
    top_financing_paths = control_path_summary.get("top_financing_paths") if isinstance(control_path_summary.get("top_financing_paths"), list) else []
    top_intermediary_paths = control_path_summary.get("top_intermediary_paths") if isinstance(control_path_summary.get("top_intermediary_paths"), list) else []
    if financing_count > 0:
        focus_lines.append(f"{financing_count} financing or payment-route path{'s' if financing_count != 1 else ''} captured.")
    if intermediary_count > 0:
        focus_lines.append(f"{intermediary_count} service or network intermediary path{'s' if intermediary_count != 1 else ''} captured.")
    for path in top_financing_paths[:2]:
        label = str(path.get("label") or "Financing path")
        source_name = str(path.get("source_name") or "Subject")
        target_name = str(path.get("target_name") or "Target")
        focus_lines.append(f"{label}: {source_name} -> {target_name}")
    for path in top_intermediary_paths[:2]:
        label = str(path.get("label") or "Intermediary path")
        source_name = str(path.get("source_name") or "Subject")
        target_name = str(path.get("target_name") or "Target")
        focus_lines.append(f"{label}: {source_name} -> {target_name}")
    focus_html = ""
    if focus_lines:
        focus_items = "".join(f"<li>{escape(line)}</li>" for line in focus_lines)
        focus_html = f"""
        <div style="margin-top: 14px; padding: 12px 14px; border-radius: 10px; background: #f8fafc; border: 1px solid #e9ecef;">
            <div style="font-size: 11px; color: #6c757d; text-transform: uppercase; letter-spacing: 0.06em;">Control-path focus</div>
            <ul style="margin: 8px 0 0; padding-left: 18px; color: #334155; font-size: 12px;">{focus_items}</ul>
        </div>
        """

    control_cards = ""
    for path in control_paths[:4]:
        source_name = str(path.get("source_name") or path.get("source_entity_id") or "Unknown")
        target_name = str(path.get("target_name") or path.get("target_entity_id") or "Unknown")
        rel_type = str(path.get("rel_type") or "related_entity").replace("_", " ").title()
        corroboration = int(path.get("corroboration_count") or 0)
        confidence = float(path.get("confidence") or 0.0)
        connectors = ", ".join(_source_display_name(source) for source in (path.get("data_sources") or [])[:3])
        evidence_refs = path.get("evidence_refs") if isinstance(path.get("evidence_refs"), list) else []
        freshness_line = ""
        if path.get("last_seen_at"):
            freshness_line = f"Last observed: {path.get('last_seen_at')}"
        evidence_html = ""
        if evidence_refs:
            evidence_lines = "".join(
                f"<li><strong>{escape(str(ref.get('title') or 'Evidence'))}</strong>"
                f"{' · ' + escape(str(ref.get('source') or '')) if ref.get('source') else ''}"
                f"{' · ' + escape(str(ref.get('artifact_ref') or '')) if ref.get('artifact_ref') else ''}</li>"
                for ref in evidence_refs[:2]
            )
            evidence_html = f"""
            <div style="margin-top:10px; font-size:12px; color:#475569;">
                <div style="font-weight:700; color:#1f2937; margin-bottom:4px;">Evidence refs</div>
                <ul style="margin:0; padding-left:18px;">{evidence_lines}</ul>
            </div>
            """
        control_cards += f"""
        <article class="storyline-card" style="--storyline-accent: #0F766E;">
            <div class="storyline-card-head">
                <div class="storyline-rank">•</div>
                <div class="storyline-meta-stack">
                    <div class="storyline-eyebrow">{escape(rel_type)}</div>
                    <div class="storyline-confidence">{corroboration} records · {int(confidence * 100)}% confidence</div>
                </div>
            </div>
            <div class="storyline-title">{escape(source_name)} → {escape(target_name)}</div>
            <div class="storyline-body">{escape(connectors or 'No source labels captured')}</div>
            {'<div class="storyline-body" style="margin-top:8px;">' + escape(freshness_line) + '</div>' if freshness_line else ''}
            {evidence_html}
        </article>
        """
    if not control_cards:
        control_cards = """
        <article class="storyline-card" style="--storyline-accent: #94A3B8;">
            <div class="storyline-card-head">
                <div class="storyline-rank">•</div>
                <div class="storyline-meta-stack">
                    <div class="storyline-eyebrow">Control paths</div>
                    <div class="storyline-confidence">Awaiting richer ownership and intermediary evidence</div>
                </div>
            </div>
            <div class="storyline-title">No analyst-grade control path is captured yet</div>
            <div class="storyline-body">This case is a candidate for ownership/control enrichment, not a finished trust artifact.</div>
        </article>
        """

    workflow_basis = str(workflow_control.get("review_basis") or "Workflow control summary not available.")
    action_owner = str(workflow_control.get("action_owner") or "Analyst review")
    recommended_view = str(tribunal.get("recommended_label") or tribunal.get("recommended_view") or "No recommendation yet")
    consensus = str(tribunal.get("consensus_level") or "contested").title()
    decision_gap = tribunal.get("decision_gap")
    tribunal_views = tribunal.get("views") if isinstance(tribunal.get("views"), list) else []
    recommended_reasons = ""
    if tribunal_views:
        top_view = tribunal_views[0] if isinstance(tribunal_views[0], dict) else {}
        reasons = top_view.get("reasons") if isinstance(top_view.get("reasons"), list) else []
        if reasons:
            reason_items = "".join(f"<li>{escape(str(reason))}</li>" for reason in reasons[:3])
            recommended_reasons = f"<ul style=\"margin:8px 0 0; padding-left:18px; color:#475569; font-size:12px;\">{reason_items}</ul>"
    claim_health_body = (
        f"{int(claim_health.get('corroborated_paths') or 0)} corroborated paths • "
        f"{int(claim_health.get('contradicted_claims') or 0)} contradicted claims • "
        f"{int(claim_health.get('stale_paths') or 0)} stale paths"
    )
    freshest_observation = str(claim_health.get("freshest_observation_at") or "No fresh control-path timestamp")
    identifiers_html = f"""
        <div style=\"margin-top: 14px; padding: 12px 14px; border-radius: 10px; background: #f8fafc; border: 1px solid #e9ecef;\">
            <div style=\"font-size: 11px; color: #6c757d; text-transform: uppercase; letter-spacing: 0.06em;\">Identity anchors</div>
            <div style=\"margin-top: 4px;\">{_render_identifier_status_rows(identity)}</div>
        </div>
    """
    official_corroboration_html = _render_official_corroboration(identity)
    ownership_control_html = _render_ownership_control_summary(ownership)
    threat_intel_html = _render_threat_intel_summary(threat_intel)

    return f"""
    <section class="storyline-section">
        <div class="storyline-head">
            <div>
                <div class="storyline-topline">Supplier passport</div>
                <h2 style="border-bottom:none; padding-bottom:0; margin-bottom:8px;">Portable trust artifact</h2>
                <p class="storyline-intro">
                    Helios condenses identity, score, ownership, graph, monitoring, and artifact coverage into one portable trust object.
                </p>
            </div>
            <div class="storyline-callout">{escape(posture)}</div>
        </div>
        <div style="display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:10px;">
            {metric_grid}
        </div>
        {focus_html}
        {identifiers_html}
        {official_corroboration_html}
        {ownership_control_html}
        {threat_intel_html}
        <div class="storyline-grid" style="margin-top: 14px;">
            <article class="storyline-card" style="--storyline-accent: #3B82F6;">
                <div class="storyline-card-head">
                    <div class="storyline-rank">•</div>
                    <div class="storyline-meta-stack">
                        <div class="storyline-eyebrow">Workflow control</div>
                        <div class="storyline-confidence">{escape(action_owner)}</div>
                    </div>
                </div>
                <div class="storyline-title">{escape(str(workflow_control.get('label') or 'Decision support posture'))}</div>
                <div class="storyline-body">{escape(workflow_basis)}</div>
            </article>
            <article class="storyline-card" style="--storyline-accent: #7C3AED;">
                <div class="storyline-card-head">
                    <div class="storyline-rank">•</div>
                    <div class="storyline-meta-stack">
                        <div class="storyline-eyebrow">Decision tribunal</div>
                        <div class="storyline-confidence">{escape(consensus)} consensus{f' · gap {decision_gap}' if decision_gap is not None else ''}</div>
                    </div>
                </div>
                <div class="storyline-title">{escape(recommended_view)}</div>
                <div class="storyline-body">Helios now shows the strongest approve, watch, and deny view instead of a single unexplained recommendation.</div>
                {recommended_reasons}
            </article>
            <article class="storyline-card" style="--storyline-accent: #C4A052;">
                <div class="storyline-card-head">
                    <div class="storyline-rank">•</div>
                    <div class="storyline-meta-stack">
                        <div class="storyline-eyebrow">Claim health</div>
                        <div class="storyline-confidence">{escape(freshest_observation)}</div>
                    </div>
                </div>
                <div class="storyline-title">Control-path evidence quality</div>
                <div class="storyline-body">{escape(claim_health_body)}</div>
            </article>
            {control_cards}
        </div>
    </section>
    """


def _generate_dossier_chapter_nav() -> str:
    items = [
        (
            "Decision brief",
            "Read this first",
            "Recommendation, storyline, and trust posture for the subject in one pass.",
        ),
        (
            "Control evidence",
            "Why Helios believes it",
            "Identity, ownership, graph, and lane-specific evidence that supports the posture.",
        ),
        (
            "Analyst narrative",
            "What a reviewer should do",
            "AI brief, intelligence summary, and the highest-signal evidence worth carrying forward.",
        ),
        (
            "Operations appendix",
            "Audit and traceability",
            "Full finding coverage, event log, freshness, and audit trail for review or archival use.",
        ),
    ]
    cards = "".join(
        f"""
        <article class="chapter-nav-card">
            <div class="chapter-nav-kicker">{escape(kicker)}</div>
            <div class="chapter-nav-title">{escape(title)}</div>
            <div class="chapter-nav-copy">{escape(copy)}</div>
        </article>
        """
        for title, kicker, copy in items
    )
    return f"""
    <section class="chapter-nav-shell">
        <div class="chapter-nav-head">
            <div>
                <div class="chapter-nav-topline">Report map</div>
                <h2 style="border-bottom:none; padding-bottom:0; margin-bottom:6px;">How to read this dossier</h2>
                <p class="chapter-nav-intro">
                    Helios now separates the executive read path from the underlying evidence and audit material so the report stops behaving like a raw export.
                </p>
            </div>
        </div>
        <div class="chapter-nav-grid">{cards}</div>
    </section>
    """


def _wrap_dossier_chapter(kicker: str, title: str, summary: str, body: str, tone: str = "light") -> str:
    if not body.strip():
        return ""
    return f"""
    <section class="chapter-shell chapter-shell-{escape(tone)}">
        <div class="chapter-head">
            <div class="chapter-head-copy">
                <div class="chapter-kicker">{escape(kicker)}</div>
                <h2 class="chapter-title">{escape(title)}</h2>
                <p class="chapter-summary">{escape(summary)}</p>
            </div>
        </div>
        <div class="chapter-body">
            {body}
        </div>
    </section>
    """


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


def _generate_storyline_section(storyline: Optional[dict]) -> str:
    cards = storyline.get("cards") if isinstance(storyline, dict) else None
    if not isinstance(cards, list) or not cards:
        return ""

    cards_html = ""
    for card in cards[:5]:
        severity = str(card.get("severity", "info") or "info").lower()
        accent = "#10B981" if severity == "positive" else _severity_color(severity)
        rank = int(card.get("rank") or 0)
        evidence_refs = [
            _storyline_source_label(ref)
            for ref in (card.get("source_refs") or [])
            if isinstance(ref, dict)
        ]
        evidence_refs = evidence_refs[:3]
        confidence_pct = round(float(card.get("confidence") or 0.0) * 100)
        trace_label = _storyline_trace_label(card.get("cta_target"))
        source_chips = "".join(
            f'<span class="storyline-source-chip">{escape(label)}</span>'
            for label in evidence_refs
        )
        cards_html += f'''
        <article class="storyline-card" style="--storyline-accent: {accent};">
            <div class="storyline-card-head">
                <div class="storyline-rank">{rank or "•"}</div>
                <div class="storyline-meta-stack">
                    <div class="storyline-eyebrow">{escape(_storyline_type_label(card.get("type", "")))}</div>
                    <div class="storyline-confidence">{confidence_pct}% confidence</div>
                </div>
            </div>
            <div class="storyline-title">{escape(card.get("title", "Storyline item"))}</div>
            <div class="storyline-body">{escape(card.get("body", ""))}</div>
            {f'<div class="storyline-trace"><strong>Follow-through:</strong> {escape(trace_label)}</div>' if trace_label else ''}
            {f'<div class="storyline-sources">{source_chips}</div>' if source_chips else ''}
        </article>
        '''

    return f'''
    <section class="storyline-section">
        <div class="storyline-head">
            <div>
                <div class="storyline-topline">What matters first</div>
                <h2>Risk Storyline</h2>
                <p class="storyline-intro">
                    Helios distills the case into the few evidence-backed signals a reviewer should understand
                    before reading the full finding set.
                </p>
            </div>
            <div class="storyline-callout">Deterministic narrative built from scored risk, normalized events, intelligence, and network context.</div>
        </div>
        <div class="storyline-grid">
            {cards_html}
        </div>
    </section>
    '''


def _generate_foci_evidence_section(foci_summary: Optional[dict]) -> str:
    if not isinstance(foci_summary, dict):
        return ""

    chips = []
    if foci_summary.get("foreign_country"):
        chips.append(f"Country {escape(str(foci_summary['foreign_country']))}")
    if foci_summary.get("foreign_ownership_pct_display"):
        chips.append(f"Ownership {escape(str(foci_summary['foreign_ownership_pct_display']))}")
    if foci_summary.get("mitigation_display") and str(foci_summary.get("mitigation_display")) != "Not stated":
        chips.append(f"Mitigation {escape(str(foci_summary['mitigation_display']))}")
    if foci_summary.get("contains_governance_control_terms"):
        chips.append("Governance-control terms detected")
    if foci_summary.get("contains_clearance_terms"):
        chips.append("Clearance terms detected")

    chip_html = "".join(f'<span class="storyline-source-chip">{chip}</span>' for chip in chips[:5])
    owner_text = escape(str(foci_summary.get("foreign_owner") or "Not stated"))
    artifact_label = escape(str(foci_summary.get("artifact_label") or "FOCI artifact"))
    posture = str(foci_summary.get("posture") or "").replace("_", " ").title()
    narrative = escape(str(foci_summary.get("narrative") or ""))

    return f'''
    <section class="storyline-section">
        <div class="storyline-head">
            <div>
                <div class="storyline-topline">Customer ownership / control evidence</div>
                <h2>FOCI Evidence Summary</h2>
                <p class="storyline-intro">
                    Helios incorporates customer-provided ownership and mitigation records into the counterparty trust narrative, not just public-source screening.
                </p>
            </div>
            <div class="storyline-callout">{escape(posture)}</div>
        </div>
        <div class="storyline-grid" style="grid-template-columns: 1fr;">
            <article class="storyline-card" style="--storyline-accent: #3B82F6;">
                <div class="storyline-card-head">
                    <div class="storyline-rank">•</div>
                    <div class="storyline-meta-stack">
                        <div class="storyline-eyebrow">{artifact_label}</div>
                        <div class="storyline-confidence">Customer-controlled evidence</div>
                    </div>
                </div>
                <div class="storyline-title">Foreign counterparty: {owner_text}</div>
                <div class="storyline-body">{narrative}</div>
                {f'<div class="storyline-sources">{chip_html}</div>' if chip_html else ''}
            </article>
        </div>
    </section>
    '''


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


def _generate_export_evidence_section(export_summary: Optional[dict]) -> str:
    if not isinstance(export_summary, dict):
        return ""

    chips = []
    if export_summary.get("destination_country"):
        chips.append(f"Destination {escape(str(export_summary['destination_country']))}")
    if export_summary.get("classification_display"):
        chips.append(f"Classification {escape(str(export_summary['classification_display']))}")
    if export_summary.get("jurisdiction_guess"):
        chips.append(f"Jurisdiction {escape(str(export_summary['jurisdiction_guess']).upper())}")
    if export_summary.get("contains_foreign_person_terms"):
        chips.append("Foreign-person access context")
    license_tokens = [escape(str(token)) for token in (export_summary.get("detected_license_tokens") or [])[:4]]
    chips.extend(license_tokens)

    chip_html = "".join(f'<span class="storyline-source-chip">{chip}</span>' for chip in chips[:6])
    posture = escape(str(export_summary.get("posture_label") or "Export review"))
    narrative = escape(str(export_summary.get("narrative") or ""))
    next_step = escape(str(export_summary.get("recommended_next_step") or ""))
    request_label = escape(str(export_summary.get("request_type") or "export authorization request").replace("_", " ").title())
    confidence_pct = round(float(export_summary.get("confidence") or 0.0) * 100)

    return f'''
    <section class="storyline-section">
        <div class="storyline-head">
            <div>
                <div class="storyline-topline">Export authorization evidence</div>
                <h2>Export Evidence Summary</h2>
                <p class="storyline-intro">
                    Helios combines customer export records with the BIS rules layer so the authorization posture is explicit, sourced, and reviewable.
                </p>
            </div>
            <div class="storyline-callout">{posture}</div>
        </div>
        <div class="storyline-grid" style="grid-template-columns: 1fr;">
            <article class="storyline-card" style="--storyline-accent: #7C3AED;">
                <div class="storyline-card-head">
                    <div class="storyline-rank">•</div>
                    <div class="storyline-meta-stack">
                        <div class="storyline-eyebrow">{request_label}</div>
                        <div class="storyline-confidence">{confidence_pct}% confidence</div>
                    </div>
                </div>
                <div class="storyline-title">Authorization posture: {posture}</div>
                <div class="storyline-body">{narrative}</div>
                {f'<div class="storyline-sources">{chip_html}</div>' if chip_html else ''}
                {f'<div class="storyline-support"><strong>Next step:</strong> {next_step}</div>' if next_step else ''}
            </article>
        </div>
    </section>
    '''


def _generate_scoring_breakdown(score: dict) -> str:
    """Generate scoring breakdown with contributions."""
    if not score:
        return ""

    calibrated = score.get("calibrated", {})
    contributions = calibrated.get("contributions", [])

    contrib_html = ""
    if contributions:
        # contributions is a list of dicts: [{factor, raw_score, confidence, signed_contribution, description}]
        if isinstance(contributions, list):
            sorted_contrib = sorted(contributions, key=lambda x: abs(x.get("signed_contribution", 0)), reverse=True)
            items = [(c.get("factor", "Unknown"), c.get("signed_contribution", 0)) for c in sorted_contrib]
        else:
            # Legacy fallback: dict format
            items = sorted(contributions.items(), key=lambda x: abs(x[1]), reverse=True)

        for factor, value in items[:8]:  # Top 8 factors
            pct = abs(value * 100)
            color = "#dc3545" if value > 0 else "#198754"
            sign = "+" if value > 0 else ""
            contrib_html += f'''
            <tr>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; width: 40%;">
                    {escape(factor.replace('_', ' ').title())}
                </td>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; flex-grow: 1;">
                    <div style="width: 100%; background-color: #e9ecef; border-radius: 2px;
                                height: 16px; overflow: hidden;">
                        <div style="width: {pct}%; background-color: {color};
                                    height: 100%;"></div>
                    </div>
                </td>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; text-align: right;
                           width: 20%; color: {color}; font-weight: 600;">
                    {sign}{value:+.2f}
                </td>
            </tr>
            '''

    probability = calibrated.get("calibrated_probability", 0)
    interval = calibrated.get("interval", {})

    return f'''
    <section style="page-break-after: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #C4A052; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            Bayesian Scoring Breakdown
        </h2>

        <div style="margin-bottom: 24px;">
            <strong style="font-size: 14px;">Overall Risk Probability</strong>
            {_progress_gauge(probability * 100, 100)}
            <div style="text-align: right; font-size: 12px; color: #6c757d; margin-top: 4px;">
                Confidence Interval: {interval.get('lower', 0):.1%} – {interval.get('upper', 1):.1%}
                ({interval.get('coverage', 0):.0%} coverage)
            </div>
        </div>

        <div style="margin-bottom: 24px;">
            <strong style="font-size: 14px;">Factor Contributions (Top 8)</strong>
            <table style="width: 100%; border-collapse: collapse; margin-top: 12px;">
                {contrib_html}
            </table>
        </div>

        <div style="padding: 12px; background-color: #f8f9fa; border-radius: 4px; font-size: 13px;">
            <strong>Composite Score:</strong> {score.get('composite_score', 0)}<br>
            <strong>Hard Stop:</strong> {'Yes' if score.get('is_hard_stop') else 'No'}
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


def _generate_intel_summary_section(summary_record: Optional[dict]) -> str:
    if not summary_record:
        return ""

    payload = summary_record.get("summary") if "summary" in summary_record else summary_record
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not items:
        return ""

    items_html = ""
    for item in items:
        citations = ", ".join(escape(fid) for fid in item.get("source_finding_ids", []))
        connectors = ", ".join(escape(connector) for connector in item.get("connectors", []))
        items_html += f'''
        <div style="margin-bottom: 14px; padding: 12px; background-color: #f8f9fa; border-radius: 4px;">
            <div style="display: flex; justify-content: space-between; gap: 12px; margin-bottom: 6px;">
                <strong style="color: #1a1f36;">{escape(item.get('title', 'Intel Summary Item'))}</strong>
                {_severity_badge(item.get('severity', 'medium'))}
            </div>
            <div style="font-size: 13px; color: #1a1f36; margin-bottom: 6px;">
                {escape(item.get('assessment', ''))}
            </div>
            <div style="font-size: 11px; color: #6c757d; display: flex; gap: 12px; flex-wrap: wrap;">
                <span>Status: {escape(item.get('status', 'active').upper())}</span>
                <span>Confidence: {float(item.get('confidence', 0.0)):.0%}</span>
                {f'<span>Connectors: {connectors}</span>' if connectors else ''}
                {f'<span>Citations: {citations}</span>' if citations else ''}
            </div>
            <div style="margin-top: 8px; font-size: 12px; color: #6c757d;">
                <strong>Recommended Action:</strong> {escape(item.get('recommended_action', 'Review cited evidence.'))}
            </div>
        </div>
        '''

    stats = payload.get("stats", {}) if isinstance(payload, dict) else {}
    coverage = float(stats.get("citation_coverage", 0.0))

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #C4A052; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            Intel Summary
        </h2>
        <div style="font-size: 12px; color: #6c757d; margin-bottom: 14px;">
            Citation coverage: <strong>{coverage:.0%}</strong>
        </div>
        {items_html}
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


def _generate_key_evidence_snapshot(enrichment: Optional[dict]) -> str:
    curated = _curate_dossier_findings(enrichment, limit=6)
    if not curated:
        return ""

    cards = ""
    for finding in curated:
        source = _source_display_name(finding.get("source", "source"))
        severity = (finding.get("severity", "info") or "info").lower()
        detail = (finding.get("detail", "") or "").strip()
        if len(detail) > 220:
            detail = detail[:217].rstrip() + "..."
        cards += f'''
        <div class="evidence-card">
            <div class="evidence-card-top">
                <span class="evidence-source">{escape(source)}</span>
                {_severity_badge(severity)}
            </div>
            <div class="evidence-title">{escape(finding.get('title', 'Finding'))}</div>
            {f'<div class="evidence-detail">{escape(detail)}</div>' if detail else ''}
        </div>
        '''

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2>Key Evidence Snapshot</h2>
        <div class="evidence-grid">
            {cards}
        </div>
    </section>
    '''


def _generate_risk_timeline(monitoring_history: list) -> str:
    """Generate risk signals timeline."""
    if not monitoring_history:
        return ""

    timeline_html = ""
    for entry in monitoring_history[:10]:  # Last 10 checks
        risk_changed = entry.get("risk_changed", False)
        prev_risk = entry.get("previous_risk", "N/A")
        curr_risk = entry.get("current_risk", "N/A")
        checked_at = entry.get("checked_at", "")

        status_color = "#dc3545" if risk_changed else "#198754"
        status_text = "Changed" if risk_changed else "Stable"

        timeline_html += f'''
        <div style="display: flex; margin-bottom: 12px; padding: 8px;
                    background-color: #f8f9fa; border-radius: 4px;">
            <div style="width: 14px; height: 14px; border-radius: 50%;
                        background-color: {status_color}; margin-right: 12px;
                        margin-top: 2px; flex-shrink: 0;"></div>
            <div style="flex-grow: 1; font-size: 13px;">
                <strong>{checked_at}</strong><br>
                <span style="color: #6c757d; font-size: 12px;">
                    {prev_risk} → {curr_risk} ({status_text})
                </span>
                <br>
                <span style="color: #6c757d; font-size: 11px;">
                    {entry.get('new_findings_count', 0)} new,
                    {entry.get('resolved_findings_count', 0)} resolved
                </span>
            </div>
        </div>
        '''

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #C4A052; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            Risk Signals Timeline
        </h2>
        {timeline_html if timeline_html else
         '<p style="color: #6c757d; font-style: italic;">No monitoring history available.</p>'}
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
    """Generate a premium AI narrative brief section from cached or freshly hydrated analysis."""
    if not analysis_data:
        return '''
        <section style="page-break-inside: avoid; margin-bottom: 32px;">
            <h2 style="color: #0A1628; border-bottom: 2px solid #C4A052; padding-bottom: 10px;
                       margin-bottom: 16px; font-size: 16px;">
                AI Narrative Brief
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
                    The AI challenge layer is still warming for this case. The deterministic posture, supplier passport,
                    and control evidence below are current; rerender once background analysis is ready.
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
            AI Narrative Brief
        </h2>
        <div style="padding: 10px 14px; background: linear-gradient(135deg, #fff8e7 0%, #fffdf5 100%);
                    border: 1px solid rgba(196, 160, 82, 0.28); border-left: 4px solid #C4A052;
                    border-radius: 12px; margin-bottom: 18px; font-size: 10px; color: #6B7280;
                    line-height: 1.6;">
            <strong style="color: #C4A052; letter-spacing: 0.06em;">ADVISORY LAYER</strong> &mdash;
            This AI brief complements the deterministic scoring engine, regulatory gates, and evidence-backed storyline.
            It never overrides hard stops or tier classification; it adds qualitative judgment, narrative synthesis, and diligence guidance.
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


def _generate_recommended_actions(score: dict) -> str:
    """Generate recommended actions from marginal information values."""
    if not score:
        return ""

    calibrated = score.get("calibrated", {})
    miv = calibrated.get("marginal_information_values", [])

    if not miv:
        return ""

    # miv is a list of dicts: [{recommendation, expected_info_gain_pp, tier_change_probability}]
    # Sort by expected info gain, descending
    if isinstance(miv, list):
        sorted_miv = sorted(miv, key=lambda x: abs(x.get("expected_info_gain_pp", 0)), reverse=True)[:5]
    else:
        # Legacy fallback: dict format
        sorted_miv = [{"recommendation": k, "expected_info_gain_pp": v} for k, v in
                      sorted(miv.items(), key=lambda x: abs(x[1]), reverse=True)[:5]]

    actions_html = ""
    for item in sorted_miv:
        rec = item.get("recommendation", "Unknown")
        gain = item.get("expected_info_gain_pp", 0)
        action = (
            f"{rec} "
            f"(potential impact: {abs(gain):.1f} pp)"
        )
        actions_html += f'''
        <li style="margin-bottom: 8px; line-height: 1.6;">
            {escape(action)}
        </li>
        '''

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #C4A052; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            Recommended Actions
        </h2>
        <ul style="margin: 0; padding-left: 20px; font-size: 13px;">
            {actions_html}
        </ul>
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


def _generate_alert_disposition_section(score: dict) -> str:
    """Generate Alert Disposition Classification section.

    Renders 4-tier classification with color-coded badge, confidence band,
    recommended action, override risk weight, and classification factors.
    Only renders if score dict has "alert_disposition" key.
    """
    if not score:
        return ""

    disposition = score.get("alert_disposition")
    if not disposition:
        return ""

    # Map disposition category to color
    category_colors = {
        "DEFINITE": "#dc3545",    # Red
        "PROBABLE": "#fd7e14",    # Orange
        "POSSIBLE": "#ffc107",    # Yellow
        "UNLIKELY": "#198754",    # Green
    }

    category = disposition.get("category", "UNKNOWN").upper()
    color = category_colors.get(category, "#6c757d")
    confidence_band = disposition.get("confidence_band", "UNKNOWN").upper()
    recommended_action = disposition.get("recommended_action", "UNKNOWN").upper()
    override_risk_weight = disposition.get("override_risk_weight", 0)
    classification_factors = disposition.get("classification_factors", {})
    explanation = disposition.get("explanation", "")

    # Build classification factors table
    factors_html = ""
    for factor_key, factor_value in sorted(classification_factors.items()):
        display_key = factor_key.replace("_", " ").title()
        factors_html += f'''
        <tr>
            <td style="padding: 8px; border-bottom: 1px solid #e9ecef; font-weight: 500;">
                {escape(display_key)}
            </td>
            <td style="padding: 8px; border-bottom: 1px solid #e9ecef;">
                {escape(str(factor_value))}
            </td>
        </tr>
        '''

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #C4A052; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            Alert Disposition Classification
        </h2>

        <div style="margin-bottom: 24px;">
            <strong style="font-size: 14px;">Classification Category</strong>
            <div style="margin-top: 8px;">
                <span style="display: inline-block; padding: 8px 16px; background-color: {color};
                            color: white; border-radius: 4px; font-weight: 600; font-size: 13px;">
                    {escape(category)}
                </span>
            </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px;">
            <div style="padding: 12px; background-color: #f8f9fa; border-radius: 4px;">
                <strong style="font-size: 12px; color: #6c757d; text-transform: uppercase;">
                    Confidence Band
                </strong>
                <div style="margin-top: 4px; font-size: 13px;">
                    {escape(confidence_band)}
                </div>
            </div>
            <div style="padding: 12px; background-color: #f8f9fa; border-radius: 4px;">
                <strong style="font-size: 12px; color: #6c757d; text-transform: uppercase;">
                    Risk Weight Override
                </strong>
                <div style="margin-top: 4px; font-size: 13px;">
                    {override_risk_weight:.2%}
                </div>
            </div>
        </div>

        <div style="margin-bottom: 24px;">
            <strong style="font-size: 14px;">Recommended Action</strong>
            <div style="margin-top: 8px; padding: 12px; background-color: #f8f9fa;
                        border-left: 4px solid {color}; border-radius: 4px;">
                {escape(recommended_action)}
            </div>
        </div>

        <div style="margin-bottom: 24px;">
            <strong style="font-size: 14px;">Classification Factors</strong>
            <table style="width: 100%; border-collapse: collapse; margin-top: 12px;
                         border: 1px solid #dee2e6; border-radius: 4px; overflow: hidden;">
                <thead>
                    <tr style="background-color: #f8f9fa;">
                        <th style="padding: 12px; text-align: left; font-weight: 600;
                                   border-bottom: 2px solid #dee2e6; font-size: 12px;">
                            Factor
                        </th>
                        <th style="padding: 12px; text-align: left; font-weight: 600;
                                   border-bottom: 2px solid #dee2e6; font-size: 12px;">
                            Value
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {factors_html}
                </tbody>
            </table>
        </div>

        <div style="padding: 12px; background-color: #f0f5ff; border-left: 4px solid #0066cc;
                    border-radius: 4px; font-size: 13px; line-height: 1.6;">
            <strong>Explanation:</strong><br>
            {escape(explanation)}
        </div>
    </section>
    '''


def _generate_itar_compliance_section(score: dict) -> str:
    """Generate ITAR Compliance Assessment section.

    Renders overall ITAR status with color-coded badge, USML category details,
    country restriction status, deemed export risk subsection, red flag assessment,
    and required license type recommendation.
    Only renders if score dict has "itar_compliance" key.
    """
    if not score:
        return ""

    itar = score.get("itar_compliance")
    if not itar:
        return ""

    overall_status = itar.get("overall_status", "UNKNOWN").upper()

    # Map overall status to color
    status_colors = {
        "COMPLIANT": "#198754",      # Green
        "REQUIRES_REVIEW": "#ffc107", # Yellow
        "NON_COMPLIANT": "#fd7e14",   # Orange
        "PROHIBITED": "#8b0000",      # Dark red
    }
    status_color = status_colors.get(overall_status, "#6c757d")

    country_status = itar.get("country_status", "UNKNOWN")
    required_license = itar.get("required_license_type", "UNKNOWN")
    explanation = itar.get("explanation", "")

    # USML Category details
    usml_category = itar.get("usml_category_info", {})
    usml_number = usml_category.get("number", "N/A")
    usml_name = usml_category.get("name", "Unknown")
    usml_risk_level = usml_category.get("risk_level", "UNKNOWN").upper()
    usml_base_weight = usml_category.get("base_risk_weight", 0)

    # Deemed export risk subsection
    deemed_export = itar.get("deemed_export_risk", {})
    deemed_risk_score = deemed_export.get("risk_score", 0) * 100  # Convert to percentage
    tcp_status = deemed_export.get("tcp_status", "UNKNOWN")
    foreign_national_count = deemed_export.get("foreign_national_count", 0)
    nationalities = deemed_export.get("nationalities", [])
    deemed_risk_factors = deemed_export.get("risk_factors", [])

    # Build risk factors list
    risk_factors_html = ""
    for factor in deemed_risk_factors[:5]:  # Top 5 factors
        risk_factors_html += f'''
        <li style="margin-bottom: 6px; font-size: 12px;">
            {escape(factor)}
        </li>
        '''

    if len(deemed_risk_factors) > 5:
        risk_factors_html += f'''
        <li style="margin-bottom: 6px; font-size: 12px; color: #6c757d; font-style: italic;">
            +{len(deemed_risk_factors) - 5} additional factors
        </li>
        '''

    # Red flag assessment
    red_flags = itar.get("red_flag_assessment", {})
    red_flag_score = red_flags.get("score", 0) * 100  # Convert to percentage
    flags_triggered = red_flags.get("flags_triggered", [])
    total_flags_checked = red_flags.get("total_flags_checked", 0)

    # Build triggered flags list
    flags_html = ""
    for flag in flags_triggered[:5]:  # Top 5 flags
        flags_html += f'''
        <li style="margin-bottom: 6px; font-size: 12px;">
            {escape(flag)}
        </li>
        '''

    if len(flags_triggered) > 5:
        flags_html += f'''
        <li style="margin-bottom: 6px; font-size: 12px; color: #6c757d; font-style: italic;">
            +{len(flags_triggered) - 5} additional flags
        </li>
        '''

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #C4A052; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            ITAR Compliance Assessment
        </h2>

        <div style="margin-bottom: 24px;">
            <strong style="font-size: 14px;">Overall ITAR Status</strong>
            <div style="margin-top: 8px;">
                <span style="display: inline-block; padding: 8px 16px; background-color: {status_color};
                            color: white; border-radius: 4px; font-weight: 600; font-size: 13px;">
                    {escape(overall_status)}
                </span>
            </div>
        </div>

        <div style="margin-bottom: 24px;">
            <strong style="font-size: 14px;">USML Category Details</strong>
            <div style="margin-top: 8px; padding: 12px; background-color: #f8f9fa;
                        border-radius: 4px; border: 1px solid #dee2e6;">
                <div style="margin-bottom: 8px;">
                    <strong style="color: #445065;">Category Number:</strong> {escape(str(usml_number))}
                </div>
                <div style="margin-bottom: 8px;">
                    <strong style="color: #445065;">Category Name:</strong> {escape(usml_name)}
                </div>
                <div style="margin-bottom: 8px;">
                    <strong style="color: #445065;">Risk Level:</strong>
                    <span style="display: inline-block; padding: 2px 6px; background-color:
                                {('#dc3545' if usml_risk_level == 'CRITICAL' else '#C4A052' if usml_risk_level == 'HIGH' else '#ffc107')};
                                color: white; border-radius: 2px; font-size: 11px;">
                        {escape(usml_risk_level)}
                    </span>
                </div>
                <div>
                    <strong style="color: #445065;">Base Risk Weight:</strong> {usml_base_weight:.2%}
                </div>
            </div>
        </div>

        <div style="margin-bottom: 24px;">
            <strong style="font-size: 14px;">Country Restriction Status</strong>
            <div style="margin-top: 8px; padding: 12px; background-color: #f8f9fa;
                        border-radius: 4px;">
                {escape(country_status.upper())}
            </div>
        </div>

        <div style="margin-bottom: 24px;">
            <strong style="font-size: 14px;">Deemed Export Risk Assessment</strong>
            <div style="margin-top: 8px; padding: 12px; background-color: #f8f9fa;
                        border-radius: 4px; border: 1px solid #dee2e6;">
                <div style="margin-bottom: 12px;">
                    <strong style="font-size: 12px;">Risk Score</strong>
                    {_progress_gauge(deemed_risk_score, 100)}
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px;">
                    <div>
                        <strong style="font-size: 12px; color: #6c757d; text-transform: uppercase;">
                            TCP Status
                        </strong>
                        <div style="margin-top: 4px; font-size: 12px;">
                            {escape(tcp_status)}
                        </div>
                    </div>
                    <div>
                        <strong style="font-size: 12px; color: #6c757d; text-transform: uppercase;">
                            Foreign Nationals
                        </strong>
                        <div style="margin-top: 4px; font-size: 12px;">
                            {foreign_national_count} identified
                            {f'({", ".join(escape(n) for n in nationalities[:3])})' if nationalities else ''}
                        </div>
                    </div>
                </div>
                <div>
                    <strong style="font-size: 12px;">Risk Factors</strong>
                    <ul style="margin: 8px 0 0 0; padding-left: 20px;">
                        {risk_factors_html if risk_factors_html else '<li style="font-size: 12px; color: #6c757d;">No significant risk factors identified</li>'}
                    </ul>
                </div>
            </div>
        </div>

        <div style="margin-bottom: 24px;">
            <strong style="font-size: 14px;">Red Flag Assessment</strong>
            <div style="margin-top: 8px; padding: 12px; background-color: #f8f9fa;
                        border-radius: 4px; border: 1px solid #dee2e6;">
                <div style="margin-bottom: 12px;">
                    <strong style="font-size: 12px;">Red Flag Score</strong>
                    {_progress_gauge(red_flag_score, 100)}
                    <div style="font-size: 11px; color: #6c757d; margin-top: 4px;">
                        {len(flags_triggered)} of {total_flags_checked} flags triggered
                    </div>
                </div>
                <div>
                    <strong style="font-size: 12px;">Triggered Flags</strong>
                    <ul style="margin: 8px 0 0 0; padding-left: 20px;">
                        {flags_html if flags_html else '<li style="font-size: 12px; color: #6c757d;">No red flags triggered</li>'}
                    </ul>
                </div>
            </div>
        </div>

        <div style="margin-bottom: 24px;">
            <strong style="font-size: 14px;">Required License Type</strong>
            <div style="margin-top: 8px; padding: 12px; background-color: #f8f9fa;
                        border-radius: 4px; font-family: monospace; font-size: 13px;">
                {escape(required_license)}
            </div>
        </div>

        <div style="padding: 12px; background-color: #f0f5ff; border-left: 4px solid #0066cc;
                    border-radius: 4px; font-size: 13px; line-height: 1.6;">
            <strong>Assessment Summary:</strong><br>
            {escape(explanation)}
        </div>
    </section>
    '''


def generate_dossier(vendor_id: str, user_id: str = "", hydrate_ai: bool = False) -> str:
    from helios_core.brief_engine import generate_html_brief

    return generate_html_brief(vendor_id, user_id=user_id, hydrate_ai=hydrate_ai)
