from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from helios_core.intelligence_thesis import build_intelligence_thesis
from helios_core.recommendations import resolve_case_recommendation


_COLOR_BY_POSTURE = {
    "approved": "#198754",
    "review": "#C4A052",
    "blocked": "#dc3545",
    "pending": "#6c757d",
}


def _program_label(program_labels: dict[str, str], vendor: dict[str, Any]) -> str:
    vendor_input = vendor.get("vendor_input", {}) if isinstance(vendor.get("vendor_input"), dict) else {}
    program_raw = vendor_input.get("program", vendor.get("program", "")) or ""
    return program_labels.get(program_raw, program_raw or "Not set")


def _clean_detail(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _human_entity_label(value: Any) -> str:
    text = _clean_detail(value)
    if not text:
        return ""
    lowered = text.lower()
    id_prefixes = ("axiom:", "entity:", "cik:", "lei:", "uei:", "cage:", "sec_edgar:", "sam:", "kg:")
    if lowered.startswith(id_prefixes):
        return ""
    if len(text) > 40 and ":" in text and " " not in text:
        return ""
    return text


def _join_sentences(*parts: Any) -> str:
    cleaned: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if not text:
            continue
        text = text.rstrip(". ")
        if text:
            cleaned.append(text)
    if not cleaned:
        return ""
    return ". ".join(cleaned) + "."


def _severity_rank(severity: str) -> int:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    return order.get(str(severity or "info").lower(), 5)


# --- Confidence tagging ---
# CONFIRMED: Directly observed in an authoritative registry or filing (SAM, FPDS, SEC, OFAC, etc.)
# INFERRED: Derived from pattern analysis, graph reasoning, or secondary sources
# ASSESSED: Analyst or model judgment applied to incomplete evidence
# UNCONFIRMED: Single-source or uncorroborated claim

_CONFIRMED_SOURCES = frozenset({
    "sam", "fpds", "usaspending", "sbir", "dla_cage", "fara", "fedramp", "piee",
    "ofac", "csl", "un_sanctions", "eu_sanctions", "uk_hmt", "worldbank",
    "sec", "sec_edgar", "gleif", "opencorporates", "courtlistener", "recap",
    "opensanctions", "usaspending_vendor_live", "usaspending_vehicle_live",
})

_INFERRED_SOURCES = frozenset({
    "graph_control", "graph_intelligence", "network_risk", "careers_scraper",
    "gdelt", "google_news", "concentration_risk",
})

_UNCONFIRMED_SOURCES = frozenset({
    "icij_offshore",
})


def _confidence_tag(source: str, severity: str = "info", corroboration: int = 1) -> str:
    """Assign epistemic confidence tag based on source type and corroboration count."""
    source_key = source.lower().replace(" ", "_")
    if source_key in _UNCONFIRMED_SOURCES:
        return "UNCONFIRMED"
    if source_key in _CONFIRMED_SOURCES:
        return "CONFIRMED"
    if source_key in _INFERRED_SOURCES:
        return "INFERRED" if corroboration >= 2 else "UNCONFIRMED"
    if severity in ("critical", "high") and corroboration >= 2:
        return "CONFIRMED"
    if corroboration >= 2:
        return "INFERRED"
    return "ASSESSED"


def _collect_graph_holds(graph_summary: dict[str, Any] | None) -> list[str]:
    if not isinstance(graph_summary, dict):
        return []
    relationships = graph_summary.get("relationships") or []
    holds: list[str] = []
    for rel in relationships[:4]:
        if not isinstance(rel, dict):
            continue
        source_name = _human_entity_label(rel.get("source_name") or rel.get("source_entity_name") or rel.get("source_entity_id"))
        target_name = _human_entity_label(rel.get("target_name") or rel.get("target_entity_name") or rel.get("target_entity_id"))
        rel_type = str(rel.get("rel_type") or "related_to").replace("_", " ")
        corroboration = int(rel.get("corroboration_count") or len(rel.get("data_sources") or []) or 1)
        if source_name and target_name:
            holds.append(f"{source_name} {rel_type} {target_name} with {corroboration} corroborating record{'s' if corroboration != 1 else ''}.")
    return holds


def _collect_passport_holds(context: dict[str, Any]) -> list[str]:
    passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}
    holds: list[str] = []
    threat = passport.get("threat_intel") if isinstance(passport.get("threat_intel"), dict) else {}
    advisories = [str(item) for item in (threat.get("cisa_advisory_ids") or []) if str(item).strip()]
    if advisories:
        holds.append("Threat context includes " + ", ".join(advisories[:3]) + ".")

    control_paths = (passport.get("graph") or {}).get("control_paths") if isinstance(passport.get("graph"), dict) else []
    for rel in control_paths[:2]:
        if not isinstance(rel, dict):
            continue
        source_name = _clean_detail(rel.get("source_name"))
        target_name = _clean_detail(rel.get("target_name"))
        rel_type = _clean_detail(rel.get("rel_type")).replace("_", " ")
        if source_name and target_name:
            holds.append(f"{source_name} {rel_type} {target_name}.")

    foci_summary = context.get("foci_summary") if isinstance(context.get("foci_summary"), dict) else {}
    foreign_owner = _clean_detail(foci_summary.get("declared_foreign_owner"))
    ownership_pct = _clean_detail(
        foci_summary.get("declared_foreign_ownership_pct")
        or (f"{foci_summary.get('max_ownership_percent_mention')}%" if isinstance(foci_summary.get("max_ownership_percent_mention"), (int, float)) else "")
    )
    mitigation_type = _clean_detail(foci_summary.get("declared_mitigation_type") or foci_summary.get("declared_mitigation_status"))
    if foreign_owner or ownership_pct or mitigation_type:
        detail = ", ".join(bit for bit in [foreign_owner, ownership_pct, mitigation_type] if bit)
        holds.append(f"FOCI evidence is carrying {detail}.")

    cyber_summary = context.get("cyber_summary") if isinstance(context.get("cyber_summary"), dict) else {}
    cyber_bits = []
    current_level = cyber_summary.get("current_cmmc_level")
    if current_level:
        cyber_bits.append(f"CMMC Level {current_level}")
    open_poam_items = int(cyber_summary.get("open_poam_items") or 0)
    if cyber_summary.get("poam_active"):
        cyber_bits.append(
            f"POA&M active{f' with {open_poam_items} open item' + ('s' if open_poam_items != 1 else '') if open_poam_items > 0 else ''}"
        )
    if open_poam_items > 0:
        cyber_bits.append(f"{open_poam_items} open POA&M item{'s' if open_poam_items != 1 else ''}")
    if cyber_bits:
        holds.append("Cyber evidence is carrying " + ", ".join(cyber_bits) + ".")

    export_summary = context.get("export_summary") if isinstance(context.get("export_summary"), dict) else {}
    classification = _clean_detail(export_summary.get("classification_display") or export_summary.get("classification_guess"))
    if classification:
        holds.append(f"Export control evidence is anchored to {classification}.")

    return holds


def _workflow_control_gap_line(workflow_control: dict[str, Any]) -> str:
    label = _clean_detail(workflow_control.get("label"))
    review_basis = _clean_detail(workflow_control.get("review_basis"))
    lowered = " ".join(bit.lower() for bit in [label, review_basis] if bit)
    if not lowered:
        return ""
    if "public-source" in lowered:
        return (
            "Ownership and control posture still rests on public-source relationship and screening data. "
            "Registry-grade corroboration is still missing."
        )
    return _join_sentences(label, review_basis)


def _tribunal_counterview_line(tribunal: dict[str, Any]) -> str:
    views = tribunal.get("views") if isinstance(tribunal.get("views"), list) else []
    if not views:
        return ""
    top_view = views[0] if isinstance(views[0], dict) else {}
    summary = _clean_detail(top_view.get("summary"))
    reasons = top_view.get("reasons") if isinstance(top_view.get("reasons"), list) else []
    if summary:
        return "Countervailing review: " + summary
    if reasons:
        reason = _clean_detail(reasons[0])
        if reason:
            return "Countervailing review: " + reason
    return ""


def _collect_passport_gaps(context: dict[str, Any]) -> list[str]:
    passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}
    gaps: list[str] = []

    ownership = passport.get("ownership") if isinstance(passport.get("ownership"), dict) else {}
    workflow_control = ownership.get("workflow_control") if isinstance(ownership.get("workflow_control"), dict) else {}
    workflow_gap = _workflow_control_gap_line(workflow_control)
    if workflow_gap:
        gaps.append(workflow_gap)

    tribunal = passport.get("tribunal") if isinstance(passport.get("tribunal"), dict) else {}
    tribunal_gap = _tribunal_counterview_line(tribunal)
    if tribunal_gap:
        gaps.append(tribunal_gap)

    return gaps


def _collect_evidence_findings(context: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}

    threat = passport.get("threat_intel") if isinstance(passport.get("threat_intel"), dict) else {}
    advisories = [str(item) for item in (threat.get("cisa_advisory_ids") or []) if str(item).strip()]
    if advisories:
        findings.append(
            {
                "title": "Threat context",
                "detail": "Threat intelligence includes " + ", ".join(advisories[:3]) + ".",
                "severity": str(threat.get("threat_pressure") or "medium").lower(),
                "source": "threat_intel",
                "confidence": "CONFIRMED",
            }
        )

    control_paths = (passport.get("graph") or {}).get("control_paths") if isinstance(passport.get("graph"), dict) else []
    for rel in control_paths[:2]:
        if not isinstance(rel, dict):
            continue
        evidence_refs = rel.get("evidence_refs") or []
        evidence_title = ""
        if evidence_refs and isinstance(evidence_refs[0], dict):
            evidence_title = _clean_detail(evidence_refs[0].get("title"))
        findings.append(
            {
                "title": evidence_title or "Control path",
                "detail": " ".join(
                    bit
                    for bit in [
                        _clean_detail(rel.get("source_name")),
                        _clean_detail(rel.get("rel_type")).replace("_", " "),
                        _clean_detail(rel.get("target_name")),
                    ]
                    if bit
                ),
                "severity": "medium",
                "source": "graph_control",
                "confidence": "INFERRED",
            }
        )

    ownership = passport.get("ownership") if isinstance(passport.get("ownership"), dict) else {}
    foci_summary = context.get("foci_summary") if isinstance(context.get("foci_summary"), dict) else {}
    foreign_owner = _clean_detail(foci_summary.get("declared_foreign_owner"))
    ownership_pct = _clean_detail(
        foci_summary.get("declared_foreign_ownership_pct")
        or (f"{foci_summary.get('max_ownership_percent_mention')}%" if isinstance(foci_summary.get("max_ownership_percent_mention"), (int, float)) else "")
    )
    mitigation_type = _clean_detail(foci_summary.get("declared_mitigation_type") or foci_summary.get("declared_mitigation_status"))
    if foreign_owner or ownership_pct or mitigation_type:
        findings.append(
            {
                "title": "FOCI evidence",
                "detail": ", ".join(bit for bit in [foreign_owner, ownership_pct, mitigation_type] if bit),
                "severity": "medium",
                "source": "foci_evidence",
                "confidence": "CONFIRMED" if foreign_owner else "INFERRED",
            }
        )

    cyber_summary = context.get("cyber_summary") if isinstance(context.get("cyber_summary"), dict) else {}
    current_level = cyber_summary.get("current_cmmc_level")
    open_poam_items = int(cyber_summary.get("open_poam_items") or 0)
    cyber_detail_bits = []
    if current_level:
        cyber_detail_bits.append(f"CMMC Level {current_level}")
    if cyber_summary.get("poam_active"):
        cyber_detail_bits.append(
            f"POA&M active{f' with {open_poam_items} open item' + ('s' if open_poam_items != 1 else '') if open_poam_items > 0 else ''}"
        )
    if open_poam_items > 0:
        cyber_detail_bits.append(f"POA&M active with {open_poam_items} open item{'s' if open_poam_items != 1 else ''}")
    if cyber_detail_bits:
        findings.append(
            {
                "title": "Cyber evidence",
                "detail": ", ".join(cyber_detail_bits),
                "severity": "medium" if open_poam_items > 0 else "low",
                "source": "cyber_evidence",
                "confidence": "CONFIRMED" if current_level else "INFERRED",
            }
        )

    export_summary = context.get("export_summary") if isinstance(context.get("export_summary"), dict) else {}
    classification = _clean_detail(export_summary.get("classification_display") or export_summary.get("classification_guess"))
    posture = _clean_detail(export_summary.get("posture_label"))
    if classification or posture:
        findings.append(
            {
                "title": "Export evidence",
                "detail": ", ".join(bit for bit in [classification, posture] if bit),
                "severity": "medium",
                "source": "export_evidence",
                "confidence": "CONFIRMED" if classification else "ASSESSED",
            }
        )

    return findings


def _build_procurement_read(context: dict[str, Any]) -> dict[str, Any]:
    support = context.get("vendor_procurement") if isinstance(context.get("vendor_procurement"), dict) else {}
    if not support:
        return {
            "metrics": {
                "prime_vehicle_count": 0,
                "sub_vehicle_count": 0,
                "prime_award_count": 0,
                "subaward_row_count": 0,
            },
            "market_position_lines": [],
            "prime_vehicle_lines": [],
            "sub_vehicle_lines": [],
            "upstream_prime_lines": [],
            "downstream_sub_lines": [],
            "customer_lines": [],
            "implication_lines": [],
        }

    prime_vehicles = [row for row in (support.get("prime_vehicles") or []) if isinstance(row, dict)]
    sub_vehicles = [row for row in (support.get("sub_vehicles") or []) if isinstance(row, dict)]
    upstream_primes = [row for row in (support.get("upstream_primes") or []) if isinstance(row, dict)]
    downstream_subs = [row for row in (support.get("downstream_subcontractors") or []) if isinstance(row, dict)]
    top_customers = [row for row in (support.get("top_customers") or []) if isinstance(row, dict)]
    momentum = support.get("award_momentum") if isinstance(support.get("award_momentum"), dict) else {}

    prime_vehicle_lines = [
        _join_sentences(
            f"{row.get('vehicle_name', 'Unknown vehicle')} appears as direct prime access",
            f"{row.get('award_count', 0)} observed award row(s) worth ${float(row.get('total_amount') or 0.0):,.0f}",
            f"Agencies: {', '.join(row.get('agencies') or [])}" if row.get("agencies") else "",
        )
        for row in prime_vehicles[:4]
    ]
    sub_vehicle_lines = [
        _join_sentences(
            f"{row.get('vehicle_name', 'Unknown vehicle')} appears in subcontract flow",
            f"${float(row.get('total_amount') or 0.0):,.0f} observed under {', '.join(row.get('counterparties') or []) or 'named primes not surfaced'}",
        )
        for row in sub_vehicles[:4]
    ]
    upstream_prime_lines = [
        _join_sentences(
            f"{row.get('name', 'Unknown')} recurs as upstream prime",
            f"${float(row.get('total_amount') or 0.0):,.0f} across {row.get('count', 0)} observed row(s)",
            f"Vehicles: {', '.join(row.get('vehicles') or [])}" if row.get("vehicles") else "",
        )
        for row in upstream_primes[:3]
    ]
    downstream_sub_lines = [
        _join_sentences(
            f"{row.get('name', 'Unknown')} recurs as downstream subcontractor",
            f"${float(row.get('total_amount') or 0.0):,.0f} across {row.get('count', 0)} observed row(s)",
            f"Vehicles: {', '.join(row.get('vehicles') or [])}" if row.get("vehicles") else "",
        )
        for row in downstream_subs[:3]
    ]
    customer_lines = [
        _join_sentences(
            f"{row.get('agency', 'Unknown agency')} dominates visible customer flow",
            f"${float((row.get('prime_amount') or 0.0) + (row.get('sub_amount') or 0.0)):,.0f} combined visible value",
            f"{row.get('prime_awards', 0)} direct award row(s) and {row.get('subaward_rows', 0)} subcontract row(s)",
        )
        for row in top_customers[:4]
    ]

    implication_lines: list[str] = []
    named_prime_vehicles = [str(row.get("vehicle_name") or "").strip() for row in prime_vehicles[:3] if str(row.get("vehicle_name") or "").strip()]
    named_sub_vehicles = [str(row.get("vehicle_name") or "").strip() for row in sub_vehicles[:3] if str(row.get("vehicle_name") or "").strip()]
    named_upstream_primes = [str(row.get("name") or "").strip() for row in upstream_primes[:3] if str(row.get("name") or "").strip()]
    named_downstream_subs = [str(row.get("name") or "").strip() for row in downstream_subs[:3] if str(row.get("name") or "").strip()]
    named_customers = [str(row.get("agency") or "").strip() for row in top_customers[:3] if str(row.get("agency") or "").strip()]
    if prime_vehicles and sub_vehicles:
        implication_lines.append(
            "Procurement posture is mixed rather than one-dimensional: direct vehicle access exists, but the vendor also rides under other primes on adjacent work."
        )
    elif prime_vehicles:
        implication_lines.append(
            "Procurement posture is prime-led: visible vehicle access comes directly rather than mainly through another contractor."
        )
    elif sub_vehicles:
        implication_lines.append(
            "Visible federal access is subcontract-heavy, which means the company may depend on upstream primes for market entry on key work."
        )
    if named_prime_vehicles:
        implication_lines.append(
            "Visible prime access includes " + ", ".join(named_prime_vehicles) + "."
        )
    if named_sub_vehicles:
        implication_lines.append(
            "Visible subcontract lanes include " + ", ".join(named_sub_vehicles) + "."
        )
    if len(upstream_primes) >= 2:
        implication_lines.append(
            "Teaming posture is not random. The same upstream primes recur, which is more informative than one-off subcontract mentions."
        )
    if named_upstream_primes:
        implication_lines.append(
            "Repeated upstream prime relationships include " + ", ".join(named_upstream_primes) + "."
        )
    if top_customers:
        lead_customer = top_customers[0]
        implication_lines.append(
            _join_sentences(
                f"Customer concentration tilts toward {lead_customer.get('agency', 'the lead customer')}",
                f"Latest visible activity is {momentum.get('latest_activity_date') or 'undated'}",
            )
        )
    if not implication_lines and support.get("findings"):
        first = support["findings"][0]
        if isinstance(first, dict):
            implication_lines.append(_clean_detail(first.get("detail")))

    market_position_lines: list[str] = []
    if named_prime_vehicles and named_upstream_primes:
        market_position_lines.append(
            f"The visible federal footprint is dual-posture rather than purely prime-led: direct access shows on {', '.join(named_prime_vehicles)}, while repeated upstream primes include {', '.join(named_upstream_primes)}."
        )
    elif named_prime_vehicles:
        market_position_lines.append(
            _join_sentences(
                "The visible federal footprint is prime-led",
                f"Direct access shows on {', '.join(named_prime_vehicles)}",
            )
        )
    elif named_upstream_primes:
        market_position_lines.append(
            _join_sentences(
                "The visible federal footprint is carried mainly through upstream primes",
                f"Repeated prime relationships include {', '.join(named_upstream_primes)}",
            )
        )
    if named_downstream_subs:
        market_position_lines.append(
            _join_sentences(
                "Parsons also carries meaningful downstream performers on its own work",
                f"Visible downstream names include {', '.join(named_downstream_subs)}",
            )
        )
    if named_customers:
        market_position_lines.append(
            _join_sentences(
                "Customer concentration is not diffuse",
                f"Visible demand clusters around {', '.join(named_customers)}",
            )
        )

    return {
        "metrics": {
            "prime_vehicle_count": len(prime_vehicles),
            "sub_vehicle_count": len(sub_vehicles),
            "prime_award_count": int(momentum.get("prime_awards") or len(support.get("prime_awards") or [])),
            "subaward_row_count": int(momentum.get("subaward_rows") or len(support.get("subaward_rows") or [])),
        },
        "top_prime_vehicle_names": [str(row.get("vehicle_name") or "").strip() for row in prime_vehicles[:4] if str(row.get("vehicle_name") or "").strip()],
        "top_sub_vehicle_names": [str(row.get("vehicle_name") or "").strip() for row in sub_vehicles[:4] if str(row.get("vehicle_name") or "").strip()],
        "top_upstream_prime_names": [str(row.get("name") or "").strip() for row in upstream_primes[:4] if str(row.get("name") or "").strip()],
        "lead_customer": str(top_customers[0].get("agency") or "").strip() if top_customers else "",
        "market_position_lines": [line for line in market_position_lines if line],
        "prime_vehicle_lines": [line for line in prime_vehicle_lines if line],
        "sub_vehicle_lines": [line for line in sub_vehicle_lines if line],
        "upstream_prime_lines": [line for line in upstream_prime_lines if line],
        "downstream_sub_lines": [line for line in downstream_sub_lines if line],
        "customer_lines": [line for line in customer_lines if line],
        "implication_lines": [line for line in implication_lines if line],
    }


def _collect_gap_lines(context: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}
    identity = passport.get("identity") if isinstance(passport.get("identity"), dict) else {}
    identifier_status = identity.get("identifier_status") if isinstance(identity.get("identifier_status"), dict) else {}
    missing_ids = []
    for key, value in identifier_status.items():
        if not isinstance(value, dict):
            continue
        state = str(value.get("state") or "")
        if state not in {"verified_present", "verified_partial"}:
            missing_ids.append(key.upper())
    if missing_ids:
        gaps.append("Identity anchors still thin on: " + ", ".join(missing_ids[:4]) + ".")

    graph_summary = context.get("graph_summary") if isinstance(context.get("graph_summary"), dict) else {}
    intelligence = graph_summary.get("intelligence") if isinstance(graph_summary.get("intelligence"), dict) else {}
    missing_families = intelligence.get("missing_required_edge_families") if isinstance(intelligence.get("missing_required_edge_families"), list) else []
    if missing_families:
        gaps.append(
            "Graph fabric is still missing: "
            + ", ".join(str(family).replace("_", " ") for family in missing_families[:4])
            + "."
        )
    contradicted = int(intelligence.get("contradicted_edge_count") or 0)
    if contradicted > 0:
        gaps.append(f"{contradicted} contradicted graph claim{'s' if contradicted != 1 else ''} still need adjudication.")
    stale = int(intelligence.get("stale_edge_count") or 0)
    if stale > 0:
        gaps.append(f"{stale} graph edge{'s' if stale != 1 else ''} are stale enough to justify refresh.")

    return gaps


def _summarize_signal_detail(detail: str, limit: int = 210) -> str:
    text = _clean_detail(detail)
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return clipped + "…"


def _material_signal_from_finding(finding: dict[str, Any]) -> dict[str, str] | None:
    title = _clean_detail(finding.get("title"), "Material signal")
    detail = _clean_detail(finding.get("detail"), "No analyst-ready detail attached.")
    source = _clean_detail(finding.get("source"), "unknown").lower()
    severity = str(finding.get("severity") or "info").lower()
    confidence = finding.get("confidence", _confidence_tag(source, severity))
    text = f"{title} {detail}".lower()

    if source == "workflow_control" or "public-source triage" in text or "workflow control" in text:
        return None

    signal = {
        "title": title,
        "read": _summarize_signal_detail(detail),
        "next_check": "Determine whether this finding changes the risk posture or requires documentation only. Method: cross-reference against primary source filings.",
        "source": source.replace("_", " ").title(),
        "severity": severity,
        "confidence": confidence,
    }

    if "beneficial ownership" in text or "ownership trace" in text or "ownership resolution" in text:
        signal["title"] = "Beneficial ownership structure unresolved"
        signal["confidence"] = "UNCONFIRMED"
        signal["read"] = (
            "OBSERVED: Disclosure filings exist. UNCONFIRMED: Named control paths have not been traced to natural persons. "
            + _summarize_signal_detail(detail)
        )
        signal["next_check"] = "Obtain SEC Schedule 13D/G or state registry filings. Trace each >5% holder to a natural person or known entity. Obtainable via SEC EDGAR or state SOS."
        return signal

    if "concentration risk" in text or ("subcontractor" in text and "30%" in text):
        signal["title"] = "Subcontract concentration creates single-point-of-failure risk"
        signal["confidence"] = "INFERRED"
        signal["read"] = _summarize_signal_detail(
            "INFERRED: A single subcontractor controls a disproportionate share of reported subaward flow. "
            "If this entity exits or fails, mission continuity is at risk. " + detail
        )
        signal["next_check"] = "Verify subcontractor is (a) still actively performing, (b) not sole-source for critical capability, (c) replaceable within contract terms. Obtainable via FPDS subaward records and SAM entity status."
        return signal

    if source == "icij_offshore" or "panama papers" in text or "pandora papers" in text or "offshore" in text:
        signal["title"] = "Offshore leak proximity requires disambiguation"
        signal["confidence"] = "UNCONFIRMED"
        signal["read"] = _summarize_signal_detail(
            "UNCONFIRMED: This is a name or entity-proximity match in leaked financial records. "
            "Not proof of wrongdoing. Requires disambiguation against confirmed identifiers. " + detail
        )
        signal["next_check"] = "Cross-reference ICIJ entity against CAGE, UEI, LEI, or named officers in SEC/registry filings. If no identifier overlap, downgrade to coincidental match."
        return signal

    if source == "graph_control":
        signal["title"] = "Network relationship requires classification"
        signal["confidence"] = "INFERRED"
        signal["read"] = _summarize_signal_detail(
            "INFERRED: A structurally significant relationship exists in the entity network, "
            "but its operational significance (ownership, teaming, financing, or incidental) has not been classified. " + detail
        )
        signal["next_check"] = "Classify relationship type using contract records (FPDS), corporate filings (SEC/SOS), or teaming agreement disclosures. Required before dependency assessment."
        return signal

    if "executive" in text and ("screened" in text or "screening" in text):
        signal["title"] = "Executive screening coverage is incomplete"
        signal["confidence"] = "ASSESSED"
        signal["read"] = _summarize_signal_detail(
            "ASSESSED: Screening coverage does not extend to all named officers or directors. "
            "Partial screening creates a false-negative risk. " + detail
        )
        signal["next_check"] = "Obtain full officer/director list from SEC proxy statement or state SOS annual report. Screen all named individuals against OFAC SDN, BIS Entity List, and debarment databases."
        return signal

    if "sanction" in text or source in ("ofac", "csl", "un_sanctions", "eu_sanctions", "uk_hmt", "opensanctions"):
        signal["confidence"] = "CONFIRMED"
        signal["read"] = _summarize_signal_detail("CONFIRMED: " + detail)
        signal["next_check"] = "Verify match is exact (not fuzzy name match). If confirmed, this is a binary disqualifier. If fuzzy, obtain full legal name and identifiers for disambiguation."
        return signal

    return signal


def _build_material_signals(findings: list[dict[str, Any]], gaps: list[str], actions: list[str]) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    seen: set[str] = set()
    for finding in findings:
        signal = _material_signal_from_finding(finding)
        if not signal:
            continue
        key = signal["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        signals.append(signal)
        if len(signals) >= 4:
            break

    if len(signals) < 3:
        for gap in gaps:
            lower = gap.lower()
            if "identity anchors still thin" in lower:
                title = "Identity verification incomplete"
                read = gap
                next_check = "Obtain missing identifiers from SAM.gov, CAGE validation, or state SOS records. Without full identity anchors, entity disambiguation is unreliable."
            elif "missing" in lower and ("graph" in lower or "relationship" in lower):
                title = "Critical relationship families unverified"
                read = gap
                next_check = "Query FPDS for teaming/subcontract relationships. Cross-reference SEC filings for ownership links. Missing families create blind spots in the dependency assessment."
            elif "contradicted" in lower:
                title = "Contradicted claims require adjudication"
                read = gap
                next_check = "Identify the conflicting sources. Determine which source is authoritative for the claim type. If unresolvable, flag as disputed in the posture assessment."
            else:
                continue
            if title.lower() in seen:
                continue
            seen.add(title.lower())
            signals.append(
                {
                    "title": title,
                    "read": _summarize_signal_detail(read),
                    "next_check": next_check,
                    "source": "Dossier context",
                    "severity": "medium",
                }
            )
            if len(signals) >= 4:
                break

    if not signals and actions:
        signals.append(
            {
                "title": "Open analyst action required",
                "read": _summarize_signal_detail(actions[0]),
                "next_check": _summarize_signal_detail(actions[0]),
                "source": "Analytical Review",
                "severity": "medium",
                "confidence": "ASSESSED",
            }
        )
    return signals[:4]


def _build_decision_shifters(material_signals: list[dict[str, str]], gaps: list[str], actions: list[str]) -> list[str]:
    """Build prioritized, conditional closure actions. Each item should state:
    what to do, what source to use, and what changes if the answer is X vs Y."""
    shifters: list[str] = []
    seen: set[str] = set()

    # Priority 1: Closure methods from material signals (these are the highest-impact unknowns)
    for signal in material_signals:
        text = _clean_detail(signal.get("next_check"))
        if not text:
            continue
        confidence = signal.get("confidence", "ASSESSED")
        if confidence == "UNCONFIRMED":
            text = f"[PRIORITY] {text}"
        if text.lower() not in seen:
            shifters.append(text)
            seen.add(text.lower())

    # Priority 2: Analyst-recommended actions
    for item in actions:
        text = _clean_detail(item)
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        shifters.append(text)
        seen.add(lowered)
        if len(shifters) >= 5:
            break

    # Priority 3: Gap-derived actions (lowest priority, only if we still have room)
    for item in gaps:
        text = _clean_detail(item)
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        shifters.append(text)
        seen.add(lowered)
        if len(shifters) >= 5:
            break

    return shifters[:5]


def _compose_summary_line(
    vendor_name: str,
    recommendation: dict[str, Any],
    probability: int,
    confidence_low: int,
    confidence_high: int,
    material_signals: list[dict[str, str]],
) -> str:
    label = recommendation["label"]
    if material_signals:
        lead = material_signals[0]
        severity = lead.get("severity", "info").lower()
        if severity in ("critical", "high"):
            return (
                f"{lead['title']}. {lead['read']} "
                f"Current posture: {label} ({probability}% risk, {confidence_low}%-{confidence_high}% band)."
            )
        return (
            f"{vendor_name} reads {label} at {probability}% risk, "
            f"but the open question is {lead['title'].lower()}. {lead['read']}"
        )
    return (
        f"{vendor_name} reads {label}. {probability}% model risk "
        f"({confidence_low}%-{confidence_high}% confidence band). "
        "No material signals have been promoted above baseline findings."
    )


def _graph_change_line(context: dict[str, Any]) -> str:
    graph_summary = context.get("graph_summary") if isinstance(context.get("graph_summary"), dict) else {}
    intelligence = graph_summary.get("intelligence") if isinstance(graph_summary.get("intelligence"), dict) else {}
    relationship_count = int(graph_summary.get("relationship_count") or len(graph_summary.get("relationships") or []))
    entity_count = int(graph_summary.get("entity_count") or len(graph_summary.get("entities") or []))
    claim_coverage_pct = round(float(intelligence.get("claim_coverage_pct") or 0.0) * 100)
    contradicted = int(intelligence.get("contradicted_edge_count") or 0)
    stale = int(intelligence.get("stale_edge_count") or 0)
    missing_families = intelligence.get("missing_required_edge_families") if isinstance(intelligence.get("missing_required_edge_families"), list) else []

    if contradicted > 0:
        return (
            f"{contradicted} contradicted claim{'s' if contradicted != 1 else ''} "
            f"in the relationship graph. The network read cannot be treated as settled until these are adjudicated."
        )
    if relationship_count > 0 or claim_coverage_pct > 0:
        parts: list[str] = []
        if relationship_count > 0:
            parts.append(f"{relationship_count} corroborated relationship{'s' if relationship_count != 1 else ''}")
        if entity_count > 0:
            parts.append(f"{entity_count} mapped entit{'ies' if entity_count != 1 else 'y'}")
        if claim_coverage_pct > 0:
            parts.append(f"{claim_coverage_pct}% claim coverage")
        return "Network evidence base: " + ", ".join(parts) + "."
    if missing_families:
        families = ", ".join(str(family).replace("_", " ") for family in missing_families[:3])
        return "Network evidence is incomplete. Missing relationship families: " + families + "."
    if stale > 0:
        return f"Network evidence includes {stale} stale edge{'s' if stale != 1 else ''} requiring refresh before the dependency read is reliable."
    return "No corroborated network relationships have been established for this entity."


def _recommendation_authority_line(recommendation: dict[str, Any]) -> str:
    source_labels = {
        "score": "quantitative risk model",
        "passport": "supplier passport verification",
        "decision": "prior decision history",
        "tribunal": "adversarial review",
    }
    sources = [source_labels.get(str(source), str(source).replace("_", " ")) for source in recommendation.get("sources") or []]
    if not sources:
        return "ASSESSED: Posture is provisional. No converging evidence sources support the current recommendation."
    joined = ", ".join(sources)
    return f"Posture supported by: {joined}."


def _build_passport_snapshot(context: dict[str, Any], recommendation: dict[str, Any], probability: int) -> dict[str, Any]:
    passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}
    score = context.get("score") if isinstance(context.get("score"), dict) else {}
    calibrated = score.get("calibrated") if isinstance(score.get("calibrated"), dict) else {}
    enrichment = context.get("enrichment") if isinstance(context.get("enrichment"), dict) else {}

    identity = passport.get("identity") if isinstance(passport.get("identity"), dict) else {}
    official = identity.get("official_corroboration") if isinstance(identity.get("official_corroboration"), dict) else {}
    verified_ids = [str(item).upper() for item in (official.get("official_identifiers_verified") or []) if str(item).strip()]
    coverage = _clean_detail(official.get("coverage_level")).replace("_", " ").title()

    ownership = passport.get("ownership") if isinstance(passport.get("ownership"), dict) else {}
    workflow_control = ownership.get("workflow_control") if isinstance(ownership.get("workflow_control"), dict) else {}
    tribunal = passport.get("tribunal") if isinstance(passport.get("tribunal"), dict) else {}
    tribunal_view = _clean_detail(tribunal.get("recommended_view") or tribunal.get("recommended_label")).replace("_", " ").title()
    tribunal_consensus = _clean_detail(tribunal.get("consensus_level")).replace("_", " ").title()
    tribunal_gap = tribunal.get("decision_gap")

    network_risk = passport.get("network_risk") if isinstance(passport.get("network_risk"), dict) else {}
    network_level = _clean_detail(network_risk.get("level")).replace("_", " ").title()

    graph = passport.get("graph") if isinstance(passport.get("graph"), dict) else {}
    intelligence = graph.get("intelligence") if isinstance(graph.get("intelligence"), dict) else {}
    workflow_lane = _clean_detail(intelligence.get("workflow_lane")).replace("_", " ").title()
    missing_families = [
        str(item).replace("_", " ")
        for item in (intelligence.get("missing_required_edge_families") or [])
        if str(item).strip()
    ]

    threat = passport.get("threat_intel") if isinstance(passport.get("threat_intel"), dict) else {}
    advisories = [str(item) for item in (threat.get("cisa_advisory_ids") or []) if str(item).strip()]

    enrichment_summary = enrichment.get("summary") if isinstance(enrichment.get("summary"), dict) else {}
    connectors_with_data = enrichment_summary.get("connectors_with_data")

    tier = _clean_detail(
        (calibrated.get("calibrated_tier") if isinstance(calibrated, dict) else "")
        or score.get("tier")
        or score.get("calibrated_tier")
    ).replace("_", " ").upper()

    cards = [
        ("Posture", recommendation["label"]),
        ("Tier", tier or "PENDING"),
        ("Risk estimate", f"{probability}%"),
    ]
    if workflow_lane:
        cards.append(("Workflow lane", workflow_lane))
    elif connectors_with_data not in (None, ""):
        cards.append(("Sources with signal", str(connectors_with_data)))

    lines: list[str] = []
    if coverage or verified_ids:
        verified_text = ", ".join(verified_ids[:4]) if verified_ids else "no official identifiers verified yet"
        if coverage:
            lines.append(f"Official corroboration is {coverage.lower()} with {verified_text}.")
        else:
            lines.append(f"Official corroboration currently verifies {verified_text}.")
    workflow_line = _workflow_control_gap_line(workflow_control)
    if workflow_line:
        lines.append(workflow_line)
    if tribunal_view or tribunal_consensus:
        tribunal_bits = [bit for bit in [tribunal_view, tribunal_consensus] if bit]
        tribunal_text = ", ".join(tribunal_bits)
        if tribunal_gap not in (None, ""):
            try:
                tribunal_text += f", decision gap {float(tribunal_gap):.2f}"
            except Exception:
                tribunal_text += f", decision gap {tribunal_gap}"
        lines.append(f"Tribunal view is {tribunal_text}.")
    if network_level:
        lines.append(f"Network risk is currently {network_level.lower()}.")
    if advisories:
        lines.append("Threat context includes " + ", ".join(advisories[:3]) + ".")
    if missing_families:
        lines.append("Passport graph still needs " + ", ".join(missing_families[:3]) + ".")

    if not lines:
        lines.append("Identity and control verification remain too thin to summarize cleanly.")

    return {
        "cards": cards,
        "lines": lines[:5],
    }


def _build_axiom_assessment(context: dict[str, Any], recommendation: dict[str, Any]) -> dict[str, Any]:
    analysis_data = context.get("analysis_data") if isinstance(context.get("analysis_data"), dict) else {}
    analysis = analysis_data.get("analysis") if isinstance(analysis_data.get("analysis"), dict) else {}
    analysis_state = str(context.get("analysis_state") or "idle")
    storyline = context.get("storyline") if isinstance(context.get("storyline"), dict) else {}
    cards = storyline.get("cards") if isinstance(storyline.get("cards"), list) else []
    score = context.get("score") if isinstance(context.get("score"), dict) else {}
    calibrated = score.get("calibrated") if isinstance(score.get("calibrated"), dict) else {}
    probability = float(calibrated.get("calibrated_probability") or 0.0)
    graph_summary = context.get("graph_summary") if isinstance(context.get("graph_summary"), dict) else {}
    graph_intelligence = graph_summary.get("intelligence") if isinstance(graph_summary.get("intelligence"), dict) else {}
    claim_coverage_pct = float(graph_intelligence.get("claim_coverage_pct") or 0.0)
    vendor = context.get("vendor") if isinstance(context.get("vendor"), dict) else {}
    vendor_name = _clean_detail(vendor.get("name"), "this entity")

    if analysis:
        summary = _clean_detail(
            analysis.get("executive_summary"),
            recommendation["summary"],
        )
        support = _clean_detail(
            analysis.get("risk_narrative") or analysis.get("regulatory_exposure"),
            recommendation["summary"],
        )
        confidence = _clean_detail(
            analysis.get("confidence_assessment"),
            f"ASSESSED: {round(probability * 100)}% model risk, {round(claim_coverage_pct * 100)}% multi-source corroboration.",
        )
        concerns = [str(item) for item in (analysis.get("critical_concerns") or []) if str(item).strip()]
        offsets = [str(item) for item in (analysis.get("mitigating_factors") or []) if str(item).strip()]
        actions = [str(item) for item in (analysis.get("recommended_actions") or []) if str(item).strip()]
    elif analysis_state == "warming":
        summary = recommendation["summary"]
        support = (
            f"{vendor_name} assessed at {recommendation['label']} based on quantitative scoring, "
            "supplier-passport verification, and corroborated network evidence."
        )
        confidence = (
            f"ASSESSED: {round(probability * 100)}% model risk. "
            f"{round(claim_coverage_pct * 100)}% of claims are corroborated by multiple sources."
        )
        concerns = []
        offsets = []
        actions = []
    else:
        lead_card = cards[0] if cards else {}
        title = _clean_detail(lead_card.get("title"))
        body = _clean_detail(lead_card.get("body"))
        if title and body:
            summary = _join_sentences(title, body)
        elif title:
            summary = title
        elif body:
            summary = body
        else:
            summary = recommendation["summary"]
        support = (
            f"{vendor_name} assessed at {recommendation['label']} based on available record. "
            + recommendation["summary"]
        )
        if claim_coverage_pct > 0:
            confidence = (
                f"ASSESSED: {round(probability * 100)}% model risk. "
                f"{round(claim_coverage_pct * 100)}% of claims are corroborated by multiple sources."
            )
        else:
            confidence = (
                f"ASSESSED: {round(probability * 100)}% model risk. "
                "No multi-source corroboration established yet."
            )
        concerns = []
        offsets = []
        actions = []

    if not concerns:
        concerns = _collect_gap_lines(context)[:3]
    if not offsets:
        offsets = _collect_graph_holds(context.get("graph_summary"))[:3]
    if not actions:
        actions = _collect_gap_lines(context)[:2]

    return {
        "summary": summary,
        "support": support,
        "graph_change": _graph_change_line(context),
        "confidence": confidence,
        "concerns": concerns[:4],
        "offsets": offsets[:4],
        "actions": actions[:4],
    }


def _distill_context(context: dict[str, Any]) -> dict[str, Any]:
    from dossier import PROGRAM_LABELS, _curate_dossier_findings

    vendor = context["vendor"]
    score = context.get("score") if isinstance(context.get("score"), dict) else {}
    calibrated = score.get("calibrated") if isinstance(score.get("calibrated"), dict) else {}
    supplier_passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}
    vendor_procurement = context.get("vendor_procurement") if isinstance(context.get("vendor_procurement"), dict) else {}
    latest_decision = None
    decisions = context.get("decisions")
    if isinstance(decisions, list) and decisions:
        latest_decision = decisions[0]

    recommendation = resolve_case_recommendation(
        score=score,
        supplier_passport=supplier_passport,
        latest_decision=latest_decision,
    )

    graph_summary = context.get("graph_summary") if isinstance(context.get("graph_summary"), dict) else {}
    relationships = graph_summary.get("relationships") if isinstance(graph_summary.get("relationships"), list) else []
    entity_name_map: dict[str, str] = {}
    for entity in graph_summary.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        entity_id = _clean_detail(entity.get("id"))
        canonical_name = _clean_detail(entity.get("canonical_name") or entity.get("name") or entity.get("label"))
        if entity_id and canonical_name:
            entity_name_map[entity_id] = canonical_name
    top_relationships = []
    for rel in relationships[:5]:
        if not isinstance(rel, dict):
            continue
        source = _human_entity_label(
            rel.get("source_name")
            or rel.get("source_entity_name")
            or entity_name_map.get(_clean_detail(rel.get("source_entity_id")))
            or rel.get("source_entity_id")
        )
        target = _human_entity_label(
            rel.get("target_name")
            or rel.get("target_entity_name")
            or entity_name_map.get(_clean_detail(rel.get("target_entity_id")))
            or rel.get("target_entity_id")
        )
        if not source or not target:
            continue
        top_relationships.append(
            {
                "rel_type": str(rel.get("rel_type") or "related_to").replace("_", " "),
                "source": source,
                "target": target,
                "evidence": _clean_detail(rel.get("evidence_summary") or rel.get("evidence")),
                "corroboration": int(rel.get("corroboration_count") or len(rel.get("data_sources") or []) or 1),
            }
        )

    enrichment = context.get("enrichment") if isinstance(context.get("enrichment"), dict) else {}
    curated_findings = []
    for finding in _curate_dossier_findings(enrichment, limit=8):
        if not isinstance(finding, dict):
            continue
        source = _clean_detail(finding.get("source"), "unknown")
        severity = str(finding.get("severity") or "info").lower()
        tag = _confidence_tag(source, severity)
        curated_findings.append(
            {
                "title": _clean_detail(finding.get("title"), "Untitled finding"),
                "detail": _clean_detail(finding.get("detail") or finding.get("assessment"), "No analyst-ready detail attached."),
                "severity": severity,
                "source": source,
                "confidence": tag,
            }
        )
    for finding in (vendor_procurement.get("findings") or []):
        if not isinstance(finding, dict):
            continue
        source = _clean_detail(finding.get("source"), "unknown")
        severity = str(finding.get("severity") or "info").lower()
        curated_findings.append(
            {
                "title": _clean_detail(finding.get("title"), "Untitled finding"),
                "detail": _clean_detail(finding.get("detail") or finding.get("assessment"), "No analyst-ready detail attached."),
                "severity": severity,
                "source": source,
                "confidence": _confidence_tag(source, severity),
                "next_check": _clean_detail(
                    (finding.get("structured_fields") or {}).get("next_check")
                    or finding.get("next_check"),
                ),
            }
        )
    curated_findings.extend(_collect_evidence_findings(context))
    normalized_findings = []
    for finding in curated_findings:
        signal_hint = _material_signal_from_finding(finding)
        normalized = dict(finding)
        if signal_hint:
            normalized["confidence"] = signal_hint.get("confidence", normalized.get("confidence"))
            normalized["next_check"] = signal_hint.get("next_check", normalized.get("next_check"))
        else:
            normalized["next_check"] = normalized.get("next_check") or "Validate whether this materially changes the call."
        normalized_findings.append(normalized)
    curated_findings = normalized_findings
    curated_findings.sort(key=lambda item: (_severity_rank(item["severity"]), item["title"]))

    passport_identity = supplier_passport.get("identity") if isinstance(supplier_passport.get("identity"), dict) else {}
    identifiers = passport_identity.get("identifiers") if isinstance(passport_identity.get("identifiers"), dict) else {}
    identity_lines = []
    for key in ("cage", "uei", "lei", "cik"):
        value = identifiers.get(key)
        if value:
            identity_lines.append(f"{key.upper()}: {value}")

    storyline = context.get("storyline") if isinstance(context.get("storyline"), dict) else {}
    procurement_read = _build_procurement_read(context)
    story_cards = storyline.get("cards") if isinstance(storyline.get("cards"), list) else []
    what_holds = []
    for card in story_cards[:3]:
        if not isinstance(card, dict):
            continue
        title = _clean_detail(card.get("title"))
        body = _clean_detail(card.get("body"))
        if title or body:
            joined = _join_sentences(title, body)
            if joined:
                what_holds.append(joined)
    what_holds.extend(_collect_graph_holds(graph_summary))
    what_holds.extend(_collect_passport_holds(context))
    what_holds.extend(procurement_read.get("implication_lines") or [])

    axiom = _build_axiom_assessment(context, recommendation)
    gaps = _collect_gap_lines(context)
    gaps.extend(_collect_passport_gaps(context))
    material_signals = _build_material_signals(curated_findings, gaps, axiom["actions"])
    decision_shifters = _build_decision_shifters(material_signals, gaps, axiom["actions"])

    probability = round(float(calibrated.get("calibrated_probability") or 0.0) * 100)
    confidence_low = round(float((calibrated.get("interval") or {}).get("lower") or 0.0) * 100)
    confidence_high = round(float((calibrated.get("interval") or {}).get("upper") or 0.0) * 100)

    graph_intelligence = graph_summary.get("intelligence") if isinstance(graph_summary.get("intelligence"), dict) else {}
    graph_read = {
        "relationship_count": int(graph_summary.get("relationship_count") or len(relationships)),
        "entity_count": int(graph_summary.get("entity_count") or len(graph_summary.get("entities") or [])),
        "claim_coverage_pct": round(float(graph_intelligence.get("claim_coverage_pct") or 0.0) * 100),
        "edge_family_count": len(graph_intelligence.get("edge_family_counts") or {}),
        "top_relationships": top_relationships,
    }

    recommended_actions = axiom["actions"][:4] if axiom["actions"] else gaps[:4]

    # Build posture assessment from decision-relevant evidence, not platform state.
    unconfirmed_count = sum(1 for f in curated_findings if f.get("confidence") == "UNCONFIRMED")
    confirmed_count = sum(1 for f in curated_findings if f.get("confidence") == "CONFIRMED")
    inferred_count = sum(1 for f in curated_findings if f.get("confidence") == "INFERRED")
    assessed_count = sum(1 for f in curated_findings if f.get("confidence") == "ASSESSED")
    critical_count = sum(1 for f in curated_findings if f.get("severity") in ("critical", "high"))
    total_findings = len(curated_findings)

    if critical_count > 0 and unconfirmed_count > confirmed_count:
        posture_narrative = (
            f"Posture is PROVISIONAL. {critical_count} high-severity finding{'s' if critical_count != 1 else ''} "
            f"with {unconfirmed_count} unconfirmed claim{'s' if unconfirmed_count != 1 else ''}. "
            "The evidence base does not yet support a confident disposition."
        )
    elif total_findings == 0:
        posture_narrative = (
            "Posture is INSUFFICIENT. No material findings have been established. "
            "The current disposition is based on absence of negative signal, not presence of positive evidence."
        )
    elif unconfirmed_count == 0 and assessed_count == 0 and total_findings > 0:
        posture_narrative = (
            f"Posture is SUPPORTED. All {total_findings} finding{'s' if total_findings != 1 else ''} "
            f"are confirmed or inferred from multiple sources. "
            f"{recommendation['label']} disposition can be carried with stated confidence."
        )
    else:
        assessed_clause = ""
        if assessed_count > 0:
            assessed_clause = f" and {assessed_count} assessed"
        posture_narrative = (
            f"Posture is CONDITIONAL. {confirmed_count} confirmed, {inferred_count} inferred, "
            f"{unconfirmed_count} unconfirmed{assessed_clause} "
            f"finding{'s' if total_findings != 1 else ''}. "
            f"Disposition of {recommendation['label']} holds IF the unconfirmed items resolve favorably."
        )

    posture_assessment = {
        "narrative": posture_narrative,
        "authority": _recommendation_authority_line(recommendation),
        "probability": probability,
        "confidence_low": confidence_low,
        "confidence_high": confidence_high,
        "total_findings": total_findings,
        "confirmed_count": confirmed_count,
        "inferred_count": inferred_count,
        "assessed_count": assessed_count,
        "unconfirmed_count": unconfirmed_count,
        "critical_count": critical_count,
    }

    thesis = build_intelligence_thesis(
        vendor_name=vendor.get("name", "Unknown"),
        recommendation=recommendation,
        supplier_passport=supplier_passport,
        graph_summary=graph_summary,
        procurement_read=procurement_read,
        material_signals=material_signals,
        decision_shifters=decision_shifters,
        what_holds=what_holds[:6],
        gaps=gaps[:6],
        posture_assessment=posture_assessment,
    )

    summary_line = thesis.get("thesis_line") or _compose_summary_line(
        vendor.get("name", "Unknown"),
        recommendation,
        probability,
        confidence_low,
        confidence_high,
        material_signals,
    )

    # Build prioritized gap closure roadmap
    gap_roadmap = []
    for idx, gap in enumerate(gaps[:6], start=1):
        priority = "HIGH" if idx <= 2 else "MEDIUM" if idx <= 4 else "LOW"
        gap_roadmap.append({"priority": priority, "gap": gap, "step": idx})

    return {
        "vendor_name": vendor.get("name", "Unknown"),
        "country": vendor.get("country", "Unknown"),
        "program_label": _program_label(PROGRAM_LABELS, vendor),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "recommendation": recommendation,
        "summary_line": summary_line,
        "identity_lines": identity_lines,
        "axiom": axiom,
        "recommendation_authority": _recommendation_authority_line(recommendation),
        "passport_snapshot": _build_passport_snapshot(context, recommendation, probability),
        "procurement_read": procurement_read,
        "what_holds": what_holds[:6],
        "gaps": gaps[:6],
        "gap_roadmap": gap_roadmap,
        "posture_assessment": posture_assessment,
        "thesis": thesis,
        "material_signals": material_signals,
        "decision_shifters": decision_shifters,
        "recommended_actions": recommended_actions,
        "graph_read": graph_read,
        "findings": curated_findings,
    }


def _html_badge(label: str, posture: str) -> str:
    return f'<span class="badge badge-{escape(posture)}">{escape(label)}</span>'


def _html_list(items: list[str], empty_text: str) -> str:
    if not items:
        return f'<li class="empty-line">{escape(empty_text)}</li>'
    return "".join(f"<li>{escape(item)}</li>" for item in items)


def _render_html_brief(payload: dict[str, Any]) -> str:
    recommendation = payload["recommendation"]
    posture = recommendation["posture"]
    graph_read = payload["graph_read"]
    procurement_read = payload.get("procurement_read") or {}
    thesis = payload.get("thesis") or {}
    principal_judgment = thesis.get("principal_judgment") or {}
    counterview = thesis.get("counterview") or {}
    dark_space = thesis.get("dark_space") or []
    procurement_read = payload.get("procurement_read") or {}
    material_signals = payload.get("material_signals") or []
    decision_shifters = payload.get("decision_shifters") or []
    finding_rows = "".join(
        f"""
        <tr>
            <td><span class="confidence-tag tag-{escape(item.get('confidence', 'ASSESSED').lower())}">{escape(item.get('confidence', 'ASSESSED'))}</span></td>
            <td>{escape(item['title'])}</td>
            <td>{escape(item['source'].replace('_', ' ').title())}</td>
            <td>{escape(item['detail'])}</td>
            <td>{escape(item.get('next_check') or 'Validate whether this materially changes the call.')}</td>
        </tr>
        """
        for item in payload["findings"][:8]
    ) or '<tr><td colspan="5" class="empty-line">No material findings survived curation.</td></tr>'

    graph_cards = "".join(
        f"""
        <div class="graph-card">
            <div class="graph-card-title">{escape(rel['source'])} → {escape(rel['target'])}</div>
            <div class="graph-card-chip">{escape(rel['rel_type'].title())} · {rel['corroboration']} record{'s' if rel['corroboration'] != 1 else ''}</div>
            <div class="graph-card-body">{escape(rel['evidence'] or 'No narrative evidence summary is attached yet.')}</div>
        </div>
        """
        for rel in graph_read["top_relationships"]
    ) or '<div class="graph-card"><div class="graph-card-body">No corroborated relationships established for this entity.</div></div>'

    signal_cards = "".join(
        f"""
        <div class="graph-card">
            <div class="graph-card-title">
                <span class="confidence-tag tag-{escape(signal.get('confidence', 'ASSESSED').lower())}">{escape(signal.get('confidence', 'ASSESSED'))}</span>
                {escape(signal['title'])}
            </div>
            <div class="graph-card-chip">{escape(signal['source'])}</div>
            <div class="graph-card-body">{escape(signal['read'])}</div>
            <div class="subtle" style="margin-top:10px;"><strong>Closure method:</strong> {escape(signal['next_check'])}</div>
        </div>
        """
        for signal in material_signals
    ) or '<div class="graph-card"><div class="graph-card-body">No decision-moving signals promoted above baseline findings.</div></div>'

    identity_html = "".join(f"<span class=\"identity-chip\">{escape(line)}</span>" for line in payload["identity_lines"]) or '<span class="identity-chip muted">Identity anchors are still thin.</span>'
    passport_cards = "".join(
        f"""
        <div class="metric">
          <div class="metric-label">{escape(label)}</div>
          <div class="metric-value passport-metric-value">{escape(value)}</div>
        </div>
        """
        for label, value in payload["passport_snapshot"]["cards"]
    )
    passport_lines = "".join(f"<li>{escape(line)}</li>" for line in payload["passport_snapshot"]["lines"])
    action_rows = "".join(
        f"""
        <tr>
          <td>{idx}</td>
          <td>{escape(item)}</td>
        </tr>
        """
        for idx, item in enumerate(payload["recommended_actions"], start=1)
    ) or '<tr><td colspan="2" class="empty-line">No recommended actions at this time.</td></tr>'
    shifter_list = _html_list(decision_shifters, "No decision-shifting actions identified.")
    procurement_metrics = procurement_read.get("metrics") or {}
    procurement_market_read = _html_list(procurement_read.get("market_position_lines") or [], "No procurement market-position read established yet.")
    procurement_prime_lines = _html_list(procurement_read.get("prime_vehicle_lines") or [], "No direct prime vehicle access observed.")
    procurement_sub_lines = _html_list(procurement_read.get("sub_vehicle_lines") or [], "No subcontract vehicle access observed.")
    procurement_upstream_lines = _html_list(procurement_read.get("upstream_prime_lines") or [], "No recurring upstream primes surfaced.")
    procurement_downstream_lines = _html_list(procurement_read.get("downstream_sub_lines") or [], "No recurring downstream subcontractors surfaced.")
    procurement_customer_lines = _html_list(procurement_read.get("customer_lines") or [], "No customer concentration surfaced.")
    procurement_implications = _html_list(procurement_read.get("implication_lines") or [], "No procurement implications established yet.")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Helios Brief | {escape(payload['vendor_name'])}</title>
  <style>
    :root {{
      --bg: #07111b;
      --surface: #0d1724;
      --surface-2: #111d2d;
      --ink: #e8edf3;
      --muted: #8ea0b6;
      --line: #1f3147;
      --gold: #c4a052;
      --approved: #198754;
      --review: #c4a052;
      --blocked: #dc3545;
      --pending: #6c757d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: linear-gradient(180deg, #07111b 0%, #0a1628 100%);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      line-height: 1.6;
    }}
    .page {{ max-width: 1080px; margin: 0 auto; padding: 32px 28px 56px; }}
    .hero {{
      background: linear-gradient(135deg, rgba(17,29,45,0.96) 0%, rgba(10,22,40,0.98) 100%);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 24px 48px rgba(0,0,0,0.22);
    }}
    .eyebrow {{
      color: var(--gold);
      font-size: 12px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      font-weight: 700;
      margin-bottom: 10px;
    }}
    h1 {{ margin: 0; font-size: 34px; line-height: 1.15; }}
    .hero-meta {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      align-items: center;
      margin-top: 16px;
      color: var(--muted);
      font-size: 13px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 7px 12px;
      color: white;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
    }}
    .badge-approved {{ background: var(--approved); }}
    .badge-review {{ background: var(--review); color: #07111b; }}
    .badge-blocked {{ background: var(--blocked); }}
    .badge-pending {{ background: var(--pending); }}
    .summary {{
      margin-top: 18px;
      font-size: 16px;
      color: #dce5ee;
      max-width: 860px;
    }}
    .identity-row {{
      margin-top: 16px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .identity-chip {{
      display: inline-flex;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.09);
      font-size: 12px;
      color: #d7e2ee;
    }}
    .identity-chip.muted {{ color: var(--muted); }}
    .grid {{
      display: grid;
      gap: 18px;
      grid-template-columns: 1.4fr 1fr;
      margin-top: 22px;
    }}
    .card {{
      background: rgba(13,23,36,0.94);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px;
    }}
    .card h2 {{
      margin: 0 0 10px;
      font-size: 18px;
      color: white;
    }}
    .support-line {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 12px;
    }}
    .axiom-summary {{
      font-size: 15px;
      color: #edf3f9;
    }}
    .subtle {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 10px;
    }}
    .split {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      margin-top: 18px;
    }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 0 0 8px; color: #d8e2ed; }}
    .empty-line {{ color: var(--muted); }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .metric {{
      padding: 14px;
      border-radius: 16px;
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.06);
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 700;
    }}
    .metric-value {{
      margin-top: 6px;
      font-size: 24px;
      font-weight: 700;
      color: white;
    }}
    .passport-metric-value {{
      font-size: 18px;
      line-height: 1.3;
    }}
    .graph-grid {{
      display: grid;
      gap: 12px;
      margin-top: 14px;
    }}
    .graph-card {{
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 16px;
      padding: 14px;
    }}
    .graph-card-title {{ font-weight: 700; color: white; }}
    .graph-card-chip {{
      display: inline-flex;
      margin-top: 8px;
      padding: 5px 9px;
      border-radius: 999px;
      background: rgba(196,160,82,0.14);
      color: #e5c98c;
      font-size: 11px;
      font-weight: 700;
    }}
    .graph-card-body {{
      margin-top: 10px;
      font-size: 13px;
      color: #d8e2ed;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 14px;
      font-size: 13px;
    }}
    th, td {{
      text-align: left;
      padding: 12px 10px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .ledger {{
      margin-top: 20px;
    }}
    .section-card {{
      margin-top: 20px;
      background: rgba(13,23,36,0.94);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px;
    }}
    .confidence-tag {{
      display: inline-flex;
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .tag-confirmed {{ background: rgba(25,135,84,0.18); color: #4ade80; }}
    .tag-inferred {{ background: rgba(196,160,82,0.18); color: #e5c98c; }}
    .tag-assessed {{ background: rgba(108,117,125,0.18); color: #94a3b8; }}
    .tag-unconfirmed {{ background: rgba(220,53,69,0.18); color: #f87171; }}
    @media print {{
      body {{ background: white; color: black; }}
      .page {{ max-width: none; padding: 0; }}
      .hero, .card {{ box-shadow: none; break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="eyebrow">Helios Intelligence Brief</div>
      <h1>{escape(payload['vendor_name'])}</h1>
      <div class="hero-meta">
        {_html_badge(recommendation['label'], posture)}
        <span>{escape(payload['country'])}</span>
        <span>{escape(payload['program_label'])}</span>
        <span>{escape(payload['generated_at'])}</span>
      </div>
      <div class="summary">{escape(payload['summary_line'])}</div>
      <div class="identity-row">{identity_html}</div>
    </section>

    <section class="grid">
      <article class="card">
        <h2>Decision Thesis</h2>
        <div class="axiom-summary">{escape(principal_judgment.get('headline') or payload['summary_line'])}</div>
        <div class="subtle">{escape(principal_judgment.get('narrative') or payload['axiom']['summary'])}</div>
        <div class="support-line">{escape(payload['posture_assessment']['authority'])}</div>
        <div class="split">
          <div>
            <h2 style="font-size:16px;">Why this read holds</h2>
            <ul>{_html_list(principal_judgment.get('support_points') or payload['what_holds'], 'No confirmed support points established.')}</ul>
          </div>
          <div>
            <h2 style="font-size:16px;">What changes the call</h2>
            <ul>{shifter_list}</ul>
          </div>
        </div>
      </article>

      <article class="card">
        <h2>{escape(counterview.get('label') or 'Competing Case')}</h2>
        <div class="axiom-summary">{escape(counterview.get('headline') or payload['axiom']['summary'])}</div>
        <div class="subtle">{escape(counterview.get('narrative') or payload['axiom']['support'])}</div>
        <div class="split" style="margin-top: 16px;">
          <div>
            <h2 style="font-size:16px;">Why it does not win</h2>
            <ul>{_html_list(counterview.get('reasons') or [counterview.get('why_not_current')], 'No competing case is strong enough to summarize cleanly.')}</ul>
          </div>
          <div>
            <h2 style="font-size:16px;">Dark space</h2>
            <ul>{_html_list(dark_space, 'No material dark space identified.')}</ul>
          </div>
        </div>
      </article>
    </section>

    <section class="section-card">
      <h2>Procurement Footprint</h2>
      <div class="support-line">Prime vehicles, subcontract vehicles, recurring teammates, and customer concentration derived from public federal award flow.</div>
      <div class="metrics">
        <div class="metric"><div class="metric-label">Prime Vehicles</div><div class="metric-value">{int(procurement_metrics.get('prime_vehicle_count') or 0)}</div></div>
        <div class="metric"><div class="metric-label">Sub Vehicles</div><div class="metric-value">{int(procurement_metrics.get('sub_vehicle_count') or 0)}</div></div>
        <div class="metric"><div class="metric-label">Direct Awards</div><div class="metric-value">{int(procurement_metrics.get('prime_award_count') or 0)}</div></div>
        <div class="metric"><div class="metric-label">Subaward Rows</div><div class="metric-value">{int(procurement_metrics.get('subaward_row_count') or 0)}</div></div>
      </div>
      <div style="margin-top: 18px;">
        <h2 style="font-size:16px;">Market Position Read</h2>
        <ul>{procurement_market_read}</ul>
      </div>
      <div class="split" style="margin-top: 16px;">
        <div>
          <h2 style="font-size:16px;">Prime Vehicles</h2>
          <ul>{procurement_prime_lines}</ul>
        </div>
        <div>
          <h2 style="font-size:16px;">Subcontract Vehicles</h2>
          <ul>{procurement_sub_lines}</ul>
        </div>
      </div>
      <div class="split" style="margin-top: 16px;">
        <div>
          <h2 style="font-size:16px;">Recurring Upstream Primes</h2>
          <ul>{procurement_upstream_lines}</ul>
        </div>
        <div>
          <h2 style="font-size:16px;">Recurring Downstream Subs</h2>
          <ul>{procurement_downstream_lines}</ul>
        </div>
      </div>
      <div class="split" style="margin-top: 16px;">
        <div>
          <h2 style="font-size:16px;">Customer Concentration</h2>
          <ul>{procurement_customer_lines}</ul>
        </div>
        <div>
          <h2 style="font-size:16px;">What this implies</h2>
          <ul>{procurement_implications}</ul>
        </div>
      </div>
    </section>

    <section class="section-card">
      <h2>Supplier Passport</h2>
      <div class="support-line">Identity verification, control posture, and review authority for this entity.</div>
      <div class="metrics">
        {passport_cards}
      </div>
      <div class="split" style="margin-top: 16px;">
        <div>
          <h2 style="font-size:16px;">Verification status</h2>
          <ul>{passport_lines or '<li class="empty-line">Insufficient verification data for summary.</li>'}</ul>
        </div>
        <div>
          <h2 style="font-size:16px;">Closure Roadmap</h2>
          <table style="margin-top: 0;">
            <thead>
              <tr>
                <th style="width:56px;">Step</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {action_rows}
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="section-card">
      <h2>Material Signals</h2>
      <div class="support-line">Findings promoted to analyst attention. Each signal carries an epistemic confidence tag and a specific closure method.</div>
      <div class="graph-grid">{signal_cards}</div>
    </section>

    <section class="section-card">
      <h2>Gap Analysis</h2>
      <div class="support-line">Prioritized unknowns. What is missing matters more than what is present.</div>
      <table>
        <thead>
          <tr>
            <th style="width:80px;">Priority</th>
            <th style="width:40px;">#</th>
            <th>Gap</th>
          </tr>
        </thead>
        <tbody>
          {"".join(
              f'<tr><td><span class="confidence-tag tag-{"confirmed" if item["priority"] == "HIGH" else "assessed" if item["priority"] == "MEDIUM" else "inferred"}">{escape(item["priority"])}</span></td><td>{item["step"]}</td><td>{escape(item["gap"])}</td></tr>'
              for item in payload.get("gap_roadmap", [])
          ) or '<tr><td colspan="3" class="empty-line">No material gaps identified.</td></tr>'}
        </tbody>
      </table>
    </section>

    <section class="section-card">
      <h2>Posture Assessment</h2>
      <div class="support-line">Convergence of evidence supporting the current disposition.</div>
      <div class="axiom-summary">{escape(payload['posture_assessment']['narrative'])}</div>
      <div class="subtle" style="margin-top:12px;">{escape(payload['posture_assessment']['authority'])}</div>
      <div class="metrics" style="margin-top:16px;">
        <div class="metric"><div class="metric-label">Model Risk</div><div class="metric-value">{payload['posture_assessment']['probability']}%</div></div>
        <div class="metric"><div class="metric-label">Confidence Band</div><div class="metric-value">{payload['posture_assessment']['confidence_low']}%-{payload['posture_assessment']['confidence_high']}%</div></div>
        <div class="metric"><div class="metric-label">Confirmed</div><div class="metric-value">{payload['posture_assessment']['confirmed_count']}/{payload['posture_assessment']['total_findings']}</div></div>
        <div class="metric"><div class="metric-label">Unconfirmed</div><div class="metric-value">{payload['posture_assessment']['unconfirmed_count']}</div></div>
      </div>
    </section>

    <section class="section-card">
      <h2>Risk Storyline</h2>
      <div class="support-line">Observed, unusual, and unresolved signals. The shortest read for a decision-maker.</div>
      <div class="split">
        <div>
          <h2 style="font-size:16px;">Observed (confirmed)</h2>
          <ul>{_html_list(payload['what_holds'], 'No confirmed holds established.')}</ul>
        </div>
        <div>
          <h2 style="font-size:16px;">Unusual (requires explanation)</h2>
          <ul>{_html_list([signal['read'] for signal in material_signals], 'No non-routine signals identified.')}</ul>
        </div>
      </div>
      <div style="margin-top: 18px;">
        <h2 style="font-size:16px;">Unresolved (open items)</h2>
        <ul>{_html_list(payload['gaps'], 'No unresolved gaps identified.')}</ul>
      </div>
    </section>

    <section class="section-card">
      <h2>Network and Dependency Read</h2>
      <div class="support-line">Relationships affecting dependency, control, teaming, or exposure. Corroboration counts indicate multi-source verification.</div>
      <div class="metrics">
        <div class="metric"><div class="metric-label">Relationships</div><div class="metric-value">{graph_read['relationship_count']}</div></div>
        <div class="metric"><div class="metric-label">Entities</div><div class="metric-value">{graph_read['entity_count']}</div></div>
        <div class="metric"><div class="metric-label">Claim Coverage</div><div class="metric-value">{graph_read['claim_coverage_pct']}%</div></div>
        <div class="metric"><div class="metric-label">Edge Families</div><div class="metric-value">{graph_read['edge_family_count']}</div></div>
      </div>
      <div class="graph-grid">{graph_cards}</div>
    </section>

    <section class="card ledger">
      <h2>Evidence Ledger</h2>
      <div class="support-line">Supporting evidence with confidence classification and recommended closure actions.</div>
      <table>
        <thead>
          <tr>
            <th style="width:100px;">Confidence</th>
            <th>Signal</th>
            <th>Source</th>
            <th>Why it matters</th>
            <th>Next check</th>
          </tr>
        </thead>
        <tbody>
          {finding_rows}
        </tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""


def generate_html_brief(vendor_id: str, user_id: str = "", hydrate_ai: bool = False) -> str:
    from dossier import build_dossier_context

    context = build_dossier_context(vendor_id, user_id=user_id, hydrate_ai=hydrate_ai)
    if not context:
        return "<p>Vendor not found</p>"
    payload = _distill_context(context)
    return _render_html_brief(payload)


def generate_pdf_brief(vendor_id: str, user_id: str = "", hydrate_ai: bool = False) -> bytes:
    from dossier import build_dossier_context

    context = build_dossier_context(vendor_id, user_id=user_id, hydrate_ai=hydrate_ai)
    if not context:
        raise ValueError(f"Vendor {vendor_id} not found")
    payload = _distill_context(context)
    recommendation = payload["recommendation"]
    accent = HexColor(_COLOR_BY_POSTURE[recommendation["posture"]])
    thesis = payload.get("thesis") or {}
    principal_judgment = thesis.get("principal_judgment") or {}
    counterview = thesis.get("counterview") or {}
    dark_space = thesis.get("dark_space") or []

    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("BriefTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=HexColor("#0A1628"))
    heading = ParagraphStyle("BriefHeading", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=HexColor("#0A1628"), spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("BriefBody", parent=styles["BodyText"], fontSize=9.5, leading=13, textColor=HexColor("#334155"))
    muted = ParagraphStyle("BriefMuted", parent=body, fontSize=8, leading=11, textColor=HexColor("#64748B"))
    bullet = ParagraphStyle("BriefBullet", parent=body, leftIndent=14, bulletIndent=0, spaceAfter=4)

    story: list[Any] = []
    story.append(Paragraph("HELIOS", ParagraphStyle("Brand", parent=muted, fontName="Helvetica-Bold", textColor=HexColor("#C4A052"), letterSpacing=1.2)))
    story.append(Paragraph("Intelligence Brief", ParagraphStyle("SubBrand", parent=muted, fontName="Helvetica-Bold", textColor=HexColor("#475569"))))
    story.append(Spacer(1, 0.12 * inch))
    story.append(Paragraph(payload["vendor_name"], title))
    hero = Table(
        [[
            Paragraph(
                f"<b>{recommendation['label']}</b><br/>{escape(payload['summary_line'])}",
                ParagraphStyle("HeroBody", parent=body, textColor=colors.white, fontSize=10.5, leading=14),
            )
        ]],
        colWidths=[7.3 * inch],
    )
    hero.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#0A1628")),
        ("BOX", (0, 0), (-1, -1), 1, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(Spacer(1, 0.08 * inch))
    story.append(hero)
    story.append(Spacer(1, 0.08 * inch))
    meta = f"{payload['country']} | {payload['program_label']} | Generated {payload['generated_at']}"
    story.append(Paragraph(meta, muted))
    top_risk_signal = (
        payload["material_signals"][0]["title"]
        if payload.get("material_signals")
        else payload["findings"][0]["title"] if payload["findings"] else recommendation["summary"]
    )
    immediate_next_move = (
        payload["decision_shifters"][0]
        if payload.get("decision_shifters")
        else payload["axiom"]["actions"][0] if payload["axiom"]["actions"] else payload["gaps"][0] if payload["gaps"] else recommendation["summary"]
    )
    evidence_snapshot = (
        f"{payload['graph_read']['relationship_count']} relationships, "
        f"{payload['graph_read']['entity_count']} entities, "
        f"{len(payload['material_signals']) or len(payload['findings'])} promoted signals."
    )
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph(f"Top risk signal: {top_risk_signal}", body))
    story.append(Paragraph(f"Immediate next move: {immediate_next_move}", body))
    story.append(Paragraph(f"Evidence snapshot: {evidence_snapshot}", muted))

    if payload["identity_lines"]:
        story.append(Spacer(1, 0.08 * inch))
        story.append(Paragraph("Identity anchors: " + " | ".join(payload["identity_lines"]), body))

    story.append(Spacer(1, 0.14 * inch))
    story.append(Paragraph("Decision Thesis", heading))
    story.append(Paragraph(principal_judgment.get("headline") or payload["summary_line"], body))
    story.append(Paragraph(principal_judgment.get("narrative") or payload["axiom"]["summary"], body))
    story.append(Paragraph(payload["posture_assessment"]["authority"], muted))
    if principal_judgment.get("support_points"):
        story.append(Paragraph("Why this read holds", heading))
        for item in principal_judgment["support_points"][:4]:
            story.append(Paragraph(item, bullet, bulletText="•"))
    if payload["decision_shifters"]:
        story.append(Paragraph("What changes the call", heading))
        for item in payload["decision_shifters"]:
            story.append(Paragraph(item, bullet, bulletText="•"))

    story.append(Paragraph(counterview.get("label") or "Competing Case", heading))
    story.append(Paragraph(counterview.get("headline") or payload["axiom"]["summary"], body))
    story.append(Paragraph(counterview.get("narrative") or payload["axiom"]["support"], body))
    if counterview.get("reasons"):
        story.append(Paragraph("Why it does not win", heading))
        for item in counterview["reasons"][:3]:
            story.append(Paragraph(item, bullet, bulletText="•"))
    if dark_space:
        story.append(Paragraph("Dark space", heading))
        for item in dark_space:
            story.append(Paragraph(item, bullet, bulletText="•"))

    story.append(Paragraph("Material Signals", heading))
    for signal in payload["material_signals"]:
        confidence = signal.get("confidence", "ASSESSED")
        story.append(Paragraph(f"<b>[{confidence}] {signal['title']}</b>", body))
        story.append(Paragraph(signal["read"], body))
        story.append(Paragraph(f"Closure method: {signal['next_check']}", muted))

    story.append(Paragraph("Procurement Footprint", heading))
    procurement_metrics = procurement_read.get("metrics") or {}
    procurement_table = Table(
        [[
            Paragraph(f"<b>Prime vehicles</b><br/>{int(procurement_metrics.get('prime_vehicle_count') or 0)}", body),
            Paragraph(f"<b>Sub vehicles</b><br/>{int(procurement_metrics.get('sub_vehicle_count') or 0)}", body),
            Paragraph(f"<b>Direct awards</b><br/>{int(procurement_metrics.get('prime_award_count') or 0)}", body),
            Paragraph(f"<b>Subaward rows</b><br/>{int(procurement_metrics.get('subaward_row_count') or 0)}", body),
        ]],
        colWidths=[1.78 * inch, 1.78 * inch, 1.78 * inch, 1.78 * inch],
    )
    procurement_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#D8E0EA")),
        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#D8E0EA")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(procurement_table)
    for section_title, items in (
        ("Market Position Read", procurement_read.get("market_position_lines") or []),
        ("Prime Vehicles", procurement_read.get("prime_vehicle_lines") or []),
        ("Subcontract Vehicles", procurement_read.get("sub_vehicle_lines") or []),
        ("Recurring Upstream Primes", procurement_read.get("upstream_prime_lines") or []),
        ("Recurring Downstream Subs", procurement_read.get("downstream_sub_lines") or []),
        ("Customer Concentration", procurement_read.get("customer_lines") or []),
        ("What this implies", procurement_read.get("implication_lines") or []),
    ):
        story.append(Paragraph(section_title, heading))
        for item in items[:4]:
            story.append(Paragraph(item, bullet, bulletText="•"))

    story.append(Paragraph("Supplier Passport", heading))
    passport_rows = [[Paragraph(f"<b>{label}</b>", body), Paragraph(value, body)] for label, value in payload["passport_snapshot"]["cards"]]
    if passport_rows:
        passport_table = Table(passport_rows, colWidths=[2.0 * inch, 5.1 * inch])
        passport_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#D8E0EA")),
            ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#D8E0EA")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(passport_table)
    for line in payload["passport_snapshot"]["lines"]:
        story.append(Paragraph(line, bullet, bulletText="•"))

    # Posture Assessment section in PDF
    story.append(Paragraph("Posture Assessment", heading))
    story.append(Paragraph(payload["posture_assessment"]["narrative"], body))
    story.append(Paragraph(payload["posture_assessment"]["authority"], muted))

    # Gap Analysis section in PDF
    if payload.get("gap_roadmap"):
        story.append(Paragraph("Gap Analysis", heading))
        for item in payload["gap_roadmap"]:
            story.append(Paragraph(f"[{item['priority']}] {item['gap']}", bullet, bulletText="•"))

    story.append(Paragraph("Risk Storyline", heading))
    if payload["what_holds"]:
        story.append(Paragraph("Observed (confirmed)", heading))
        for item in payload["what_holds"]:
            story.append(Paragraph(item, bullet, bulletText="•"))
    if payload["material_signals"]:
        story.append(Paragraph("Unusual (requires explanation)", heading))
        for signal in payload["material_signals"]:
            story.append(Paragraph(signal["read"], bullet, bulletText="•"))
    if payload["gaps"]:
        story.append(Paragraph("Unresolved (open items)", heading))
        for item in payload["gaps"]:
            story.append(Paragraph(item, bullet, bulletText="•"))

    story.append(Paragraph("Network and Dependency Read", heading))
    graph_metrics = Table(
        [[
            Paragraph(f"<b>Relationships</b><br/>{payload['graph_read']['relationship_count']}", body),
            Paragraph(f"<b>Entities</b><br/>{payload['graph_read']['entity_count']}", body),
            Paragraph(f"<b>Claim coverage</b><br/>{payload['graph_read']['claim_coverage_pct']}%", body),
            Paragraph(f"<b>Edge families</b><br/>{payload['graph_read']['edge_family_count']}", body),
        ]],
        colWidths=[1.78 * inch, 1.78 * inch, 1.78 * inch, 1.78 * inch],
    )
    graph_metrics.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#D8E0EA")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(graph_metrics)
    story.append(Spacer(1, 0.08 * inch))
    for rel in payload["graph_read"]["top_relationships"]:
        story.append(Paragraph(f"<b>{rel['source']} → {rel['target']}</b> | {rel['rel_type'].title()} | {rel['corroboration']} record{'s' if rel['corroboration'] != 1 else ''}", body))
        story.append(Paragraph(rel["evidence"] or "No narrative evidence summary available.", muted))

    story.append(Paragraph("Evidence Ledger", heading))
    ledger_rows = [["Confidence", "Signal", "Source", "Why it matters", "Next check"]]
    for item in payload["findings"][:8]:
        next_check = item.get("next_check") or "Validate whether this materially changes the call."
        ledger_rows.append([
            item.get("confidence", "ASSESSED"),
            item["title"],
            item["source"].replace("_", " ").title(),
            item["detail"],
            next_check,
        ])
    if len(ledger_rows) == 1:
        ledger_rows.append(["", "No material findings survived curation.", "", "", ""])
    ledger = Table(ledger_rows, colWidths=[0.85 * inch, 1.4 * inch, 1.0 * inch, 2.3 * inch, 1.6 * inch])
    ledger.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#0A1628")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#D8E0EA")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#FFFFFF"), HexColor("#F8FAFC")]),
    ]))
    story.append(ledger)

    doc.build(story)
    return pdf_buffer.getvalue()
