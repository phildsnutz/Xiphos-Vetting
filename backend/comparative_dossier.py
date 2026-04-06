"""
Xiphos Comparative Dossier & Vehicle Dossier Generator

Generates professional intelligence-grade HTML dossiers comparing contract
vehicles (comparative) or analyzing single vehicles (single). Output is
production-quality, light-themed, $25K-$50K deliverable grade.

These reports are self-contained HTML (inline CSS, no external dependencies)
and print-optimized for PDF export.

Usage:
    from comparative_dossier import generate_comparative_dossier, generate_vehicle_dossier
    
    # Comparative (two+ vehicles head-to-head)
    html = generate_comparative_dossier(
        vehicle_configs=[
            {"vehicle_name": "LEIA", "prime": "Amentum", "data": {...}},
            {"vehicle_name": "C3PO", "prime": "Other Prime", "data": {...}}
        ],
        title="SOCPAC C5ISR Vehicle Lineage Analysis",
        subtitle="Teaming Persistence & Active vs Expired Data Comparison"
    )
    
    # Single vehicle
    html = generate_vehicle_dossier(
        vehicle_name="ITEAMS",
        prime_contractor="DynCorp International",
        vendor_ids=["v1", "v2"],
        contract_data={...}
    )
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime
from html import escape
import re
from typing import Any, Optional
import threading

import db
from dossier import (
    build_dossier_context,
    _curate_dossier_findings,
    SOURCE_DISPLAY_NAMES,
    _source_display_name,
)

try:
    from knowledge_graph import get_kg_conn
    HAS_KG = True
except ImportError:
    HAS_KG = False


# Light-theme color palette
COLORS = {
    "white": "#FFFFFF",
    "blue_header": "#2563EB",
    "blue_light": "#3B82F6",
    "orange": "#F97316",
    "green": "#22C55E",
    "red": "#EF4444",
    "yellow": "#F59E0B",
    "gray_light": "#F1F5F9",
    "gray_border": "#E2E8F0",
    "text_primary": "#1E293B",
    "text_secondary": "#475569",
    "text_muted": "#94A3B8",
    "gold": "#C4A052",
}

BASE_CSS = """
<style>
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background-color: #FFFFFF;
    color: #1E293B;
    line-height: 1.6;
    font-size: 14px;
}

.page-wrapper {
    max-width: 1100px;
    margin: 0 auto;
    padding: 48px;
    background-color: #FFFFFF;
}

/* Header area */
.header-badges {
    display: flex;
    gap: 12px;
    margin-bottom: 24px;
    flex-wrap: wrap;
}

.badge-category {
    display: inline-block;
    padding: 6px 12px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: white;
}

.badge-orange {
    background-color: #F97316;
}

.badge-blue {
    background-color: #3B82F6;
}

.badge-green {
    background-color: #22C55E;
}

h1 {
    font-size: 28px;
    font-weight: 700;
    color: #1E293B;
    margin-bottom: 8px;
    line-height: 1.2;
}

.subtitle {
    font-size: 16px;
    color: #475569;
    margin-bottom: 16px;
    font-weight: 500;
}

.header-meta {
    display: flex;
    gap: 32px;
    font-size: 13px;
    color: #64748B;
    margin-bottom: 48px;
    border-bottom: 1px solid #E2E8F0;
    padding-bottom: 16px;
}

.header-meta-item {
    display: flex;
    align-items: center;
    gap: 8px;
}

/* Section headers */
.section-header {
    background-color: #2563EB;
    color: white;
    padding: 12px 16px;
    margin-top: 48px;
    margin-bottom: 24px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    gap: 12px;
}

.section-number {
    font-weight: 700;
    font-size: 16px;
}

.section-title {
    font-size: 16px;
    font-weight: 600;
}

/* KPI cards */
.kpi-container {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
}

.kpi-card {
    background-color: #F1F5F9;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    padding: 20px;
    text-align: center;
}

.kpi-value {
    font-size: 32px;
    font-weight: 700;
    color: #1E293B;
    margin-bottom: 8px;
}

.kpi-label {
    font-size: 13px;
    color: #64748B;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* Tables */
table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 32px;
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    overflow: hidden;
}

thead {
    background-color: #F1F5F9;
}

th {
    padding: 12px 16px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
    color: #1E293B;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid #E2E8F0;
}

td {
    padding: 12px 16px;
    border-bottom: 1px solid #E2E8F0;
    color: #475569;
}

tbody tr:nth-child(even) {
    background-color: #F8FAFC;
}

tbody tr:hover {
    background-color: #F1F5F9;
}

/* Status badges */
.badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 3px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    white-space: nowrap;
}

.badge-success {
    background-color: #DCF8E8;
    color: #166534;
}

.badge-error {
    background-color: #FEE2E2;
    color: #991B1B;
}

.badge-warning {
    background-color: #FEF3C7;
    color: #92400E;
}

.badge-info {
    background-color: #DBEAFE;
    color: #1E40AF;
}

.badge-neutral {
    background-color: #E2E8F0;
    color: #334155;
}

/* Status indicators */
.status-check {
    color: #22C55E;
    font-weight: bold;
}

.status-x {
    color: #EF4444;
    font-weight: bold;
}

.status-dash {
    color: #94A3B8;
}

/* Narrative/info sections */
.narrative {
    background-color: #FFFFFF;
    padding: 20px;
    margin-bottom: 32px;
    line-height: 1.8;
    color: #475569;
}

.info-box {
    background-color: #EFF6FF;
    border-left: 4px solid #3B82F6;
    padding: 16px;
    margin-bottom: 24px;
    border-radius: 4px;
}

.info-box-label {
    font-size: 12px;
    font-weight: 700;
    color: #1E40AF;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 8px;
}

.warning-box {
    background-color: #FEF3C7;
    border-left: 4px solid #F59E0B;
    padding: 16px;
    margin-bottom: 24px;
    border-radius: 4px;
    color: #92400E;
}

.risk-box {
    background-color: #FEE2E2;
    border-left: 4px solid #EF4444;
    padding: 16px;
    margin-bottom: 24px;
    border-radius: 4px;
    color: #991B1B;
}

/* Lists */
ul, ol {
    margin-left: 20px;
    margin-bottom: 16px;
}

li {
    margin-bottom: 8px;
}

/* Key findings */
.key-finding {
    background-color: #F1F5F9;
    border-left: 4px solid #C4A052;
    padding: 16px;
    margin-bottom: 16px;
    border-radius: 4px;
}

.key-finding-label {
    font-size: 12px;
    font-weight: 700;
    color: #C4A052;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 8px;
}

.key-finding-text {
    color: #1E293B;
    font-weight: 500;
}

/* Prose formatting */
p {
    margin-bottom: 16px;
}

strong {
    font-weight: 700;
    color: #1E293B;
}

em {
    font-style: italic;
    color: #475569;
}

/* Grid layouts */
.grid-2col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 32px;
    margin-bottom: 32px;
}

.grid-item {
    background-color: #F1F5F9;
    padding: 20px;
    border-radius: 6px;
    border: 1px solid #E2E8F0;
}

/* Lineage diagram styling */
.lineage-container {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 20px;
    margin: 32px 0;
    padding: 24px;
    background-color: #F8FAFC;
    border-radius: 6px;
}

.lineage-node {
    background-color: #3B82F6;
    color: white;
    padding: 12px 20px;
    border-radius: 4px;
    font-weight: 600;
    min-width: 150px;
    text-align: center;
}

.lineage-arrow {
    color: #94A3B8;
    font-size: 20px;
}

/* Print styles */
@media print {
    body {
        background-color: white;
    }
    
    .page-wrapper {
        padding: 40px;
    }
    
    .section-header {
        page-break-after: avoid;
    }
    
    table {
        page-break-inside: avoid;
    }
    
    .kpi-container {
        page-break-inside: avoid;
    }
}

/* Responsive */
@media (max-width: 768px) {
    .page-wrapper {
        padding: 24px;
    }
    
    .header-meta {
        flex-direction: column;
        gap: 8px;
    }
    
    .kpi-container {
        grid-template-columns: repeat(2, 1fr);
    }
    
    .grid-2col {
        grid-template-columns: 1fr;
        gap: 24px;
    }
    
    .lineage-container {
        flex-direction: column;
        gap: 12px;
    }
    
    table {
        font-size: 12px;
    }
    
    th, td {
        padding: 10px 12px;
    }
}
</style>
"""


def _format_currency(value: Optional[float]) -> str:
    """Format numeric value as currency."""
    if value is None:
        return "N/A"
    if value >= 1_000_000:
        return f"${value/1_000_000:.1f}M"
    elif value >= 1_000:
        return f"${value/1_000:.1f}K"
    return f"${value:.0f}"


def _format_number(value: Optional[int]) -> str:
    """Format numeric value with thousands separator."""
    if value is None:
        return "N/A"
    return f"{value:,}"


def _status_cell(present: bool, expired: bool = False) -> str:
    """Return HTML for status indicator cell."""
    if present and not expired:
        return '<span class="status-check">✓</span>'
    elif expired:
        return '<span class="status-dash">—</span>'
    else:
        return '<span class="status-x">✗</span>'


def _badge(text: str, badge_type: str = "info") -> str:
    """Generate HTML badge."""
    return f'<span class="badge badge-{badge_type}">{escape(text)}</span>'


_TEAMING_RELATIONSHIP_TYPES = {
    "subcontractor_of",
    "prime_contractor_of",
    "teamed_with",
    "incumbent_on",
}
_LINEAGE_RELATIONSHIP_TYPES = {
    "awarded_under",
    "predecessor_of",
    "successor_of",
    "competed_on",
    "incumbent_on",
    "funded_by",
    "performed_at",
}
_RELATIONSHIP_LABELS = {
    "subcontractor_of": "Subcontractor signal",
    "prime_contractor_of": "Prime relationship",
    "teamed_with": "Teaming signal",
    "incumbent_on": "Incumbency signal",
    "awarded_under": "Awarded under",
    "predecessor_of": "Predecessor path",
    "successor_of": "Successor path",
    "competed_on": "Competitive pressure",
    "funded_by": "Funding path",
    "performed_at": "Performance location",
}
_SEVERITY_PRIORITY = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _normalize_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _clean_text(value: object, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        candidate = _clean_text(value)
        if not candidate:
            continue
        marker = candidate.lower()
        if marker in seen:
            continue
        seen.add(marker)
        ordered.append(candidate)
    return ordered


def _load_case_contexts(vendor_ids: list[str] | None, *, vehicle_name: str = "") -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for vendor_id in vendor_ids or []:
        normalized = _clean_text(vendor_id)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        try:
            context = build_dossier_context(normalized, vehicle_name=vehicle_name)
        except Exception:
            context = None
        if isinstance(context, dict):
            contexts.append(context)
    return contexts


def _context_vehicle_intelligence(context: dict[str, Any]) -> dict[str, Any]:
    vehicle_intelligence = context.get("vehicle_intelligence")
    return vehicle_intelligence if isinstance(vehicle_intelligence, dict) else {}


def _context_relationships(context: dict[str, Any]) -> list[dict[str, Any]]:
    relationships: list[dict[str, Any]] = []
    graph_summary = context.get("graph_summary") if isinstance(context.get("graph_summary"), dict) else {}
    for rel in graph_summary.get("relationships") or []:
        if isinstance(rel, dict):
            relationships.append(rel)
    for rel in _context_vehicle_intelligence(context).get("relationships") or []:
        if isinstance(rel, dict):
            relationships.append(rel)
    return relationships


def _context_case_events(context: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for event in context.get("case_events") if isinstance(context.get("case_events"), list) else []:
        if isinstance(event, dict):
            events.append(event)
    for event in _context_vehicle_intelligence(context).get("events") or []:
        if isinstance(event, dict):
            events.append(event)
    return events


def _context_findings(context: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    enrichment = context.get("enrichment") if isinstance(context.get("enrichment"), dict) else {}
    for finding in enrichment.get("findings") if isinstance(enrichment.get("findings"), list) else []:
        if isinstance(finding, dict):
            findings.append(finding)
    for finding in _context_vehicle_intelligence(context).get("findings") or []:
        if isinstance(finding, dict):
            findings.append(finding)
    return findings


def _pick_primary_context(contexts: list[dict[str, Any]], prime_contractor: str) -> dict[str, Any] | None:
    prime_key = _normalize_name(prime_contractor)
    for context in contexts:
        vendor = context.get("vendor") if isinstance(context.get("vendor"), dict) else {}
        if _normalize_name(vendor.get("name")) == prime_key:
            return context
    return contexts[0] if contexts else None


def _relationship_sources(rel: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    for item in rel.get("data_sources") or []:
        label = _source_display_name(_clean_text(item))
        if label:
            sources.append(label)
    for claim_record in rel.get("claim_records") or []:
        if not isinstance(claim_record, dict):
            continue
        for evidence_record in claim_record.get("evidence_records") or []:
            if not isinstance(evidence_record, dict):
                continue
            label = _source_display_name(
                _clean_text(evidence_record.get("source") or evidence_record.get("title"))
            )
            if label:
                sources.append(label)
    return _dedupe_preserve(sources) or ["Graph provenance"]


def _relationship_counterpart(rel: dict[str, Any], focal_names: set[str]) -> str:
    source = _clean_text(
        rel.get("source_name") or rel.get("source_entity_name") or rel.get("source_entity_id"),
        "Unresolved source",
    )
    target = _clean_text(
        rel.get("target_name") or rel.get("target_entity_name") or rel.get("target_entity_id"),
        "Unresolved target",
    )
    source_key = _normalize_name(source)
    target_key = _normalize_name(target)
    if source_key in focal_names and target_key not in focal_names:
        return target
    if target_key in focal_names and source_key not in focal_names:
        return source
    if source_key and source_key not in focal_names:
        return source
    if target_key and target_key not in focal_names:
        return target
    return target or source or "Unresolved entity"


def _relationship_rows(
    contexts: list[dict[str, Any]],
    *,
    vehicle_name: str,
    prime_contractor: str,
    rel_types: set[str],
    limit: int = 8,
) -> list[dict[str, Any]]:
    focal_names = {
        _normalize_name(vehicle_name),
        _normalize_name(prime_contractor),
    }
    for context in contexts:
        vendor = context.get("vendor") if isinstance(context.get("vendor"), dict) else {}
        focal_name = _normalize_name(vendor.get("name"))
        if focal_name:
            focal_names.add(focal_name)

    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for context in contexts:
        for rel in _context_relationships(context):
            if not isinstance(rel, dict):
                continue
            rel_type = _clean_text(rel.get("rel_type")).lower()
            if rel_type not in rel_types:
                continue
            entity = _relationship_counterpart(rel, focal_names)
            signal = _RELATIONSHIP_LABELS.get(rel_type, rel_type.replace("_", " ").title())
            corroboration_count = int(
                rel.get("corroboration_count")
                or len(rel.get("data_sources") or [])
                or len(rel.get("claim_records") or [])
                or 1
            )
            tier = _clean_text(rel.get("intelligence_tier") or rel.get("temporal_state"), "observed").replace("_", " ")
            evidence = _clean_text(
                rel.get("evidence_summary") or rel.get("evidence"),
                "Current graph edge has no narrative evidence summary attached yet.",
            )
            provenance = ", ".join(_relationship_sources(rel)[:2])
            key = (_normalize_name(entity), rel_type)
            candidate = {
                "entity": entity,
                "signal": signal,
                "corroboration": f"{corroboration_count} record{'s' if corroboration_count != 1 else ''}",
                "provenance": provenance,
                "assessment": f"{tier.title()}: {evidence}",
                "_corroboration_count": corroboration_count,
            }
            existing = rows_by_key.get(key)
            if existing is None or candidate["_corroboration_count"] > existing["_corroboration_count"]:
                rows_by_key[key] = candidate

    rows = list(rows_by_key.values())
    rows.sort(key=lambda item: (-item["_corroboration_count"], item["entity"].lower(), item["signal"].lower()))
    for item in rows:
        item.pop("_corroboration_count", None)
    return rows[:limit]


def _event_rows(contexts: list[dict[str, Any]], limit: int = 6) -> list[dict[str, str]]:
    rows_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for context in contexts:
        for event in _context_case_events(context):
            if not isinstance(event, dict):
                continue
            title = _clean_text(event.get("title") or event.get("subject") or event.get("event_type"), "Observed event")
            source = _source_display_name(_clean_text(event.get("connector"), "case_evidence"))
            status = _clean_text(event.get("status"), "observed").replace("_", " ").title()
            assessment = _clean_text(event.get("assessment"), "No analyst narrative is attached yet.")
            event_date = _clean_text(event.get("event_date") or event.get("date") or event.get("observed_at"))
            key = (_normalize_name(title), source.lower())
            rows_by_key[key] = {
                "event": title,
                "status": status,
                "source": source,
                "assessment": assessment,
                "_event_date": event_date,
            }
    rows = list(rows_by_key.values())
    rows.sort(
        key=lambda item: (
            item.get("_event_date", ""),
            item["status"].lower(),
            item["event"].lower(),
        ),
        reverse=True,
    )
    for row in rows:
        row.pop("_event_date", None)
    return rows[:limit]


def _lineage_bucket(signal: str) -> str:
    normalized = signal.lower()
    if "predecessor" in normalized:
        return "predecessor"
    if "successor" in normalized:
        return "successor"
    if "incumb" in normalized:
        return "incumbency"
    if "compet" in normalized:
        return "competition"
    if "fund" in normalized:
        return "funding"
    if "perform" in normalized:
        return "performance"
    if "award" in normalized:
        return "award"
    return "other"


def _render_lineage_briefing(rows: list[dict[str, Any]], *, subject_label: str) -> str:
    if not rows:
        return f"""
        <div class="info-box">
            <div class="info-box-label">Lineage Read</div>
            <p>No predecessor, successor, incumbent, competed-on, funding, or performance-path evidence is attached to {escape(subject_label)} yet. This is an evidence gap, not a clean lineage conclusion.</p>
        </div>
        """

    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(_lineage_bucket(row["signal"]), []).append(row)

    bullets: list[str] = []
    if buckets.get("predecessor"):
        names = ", ".join(row["entity"] for row in buckets["predecessor"][:3])
        bullets.append(f"Predecessor path observed through {names}.")
    if buckets.get("successor"):
        names = ", ".join(row["entity"] for row in buckets["successor"][:3])
        bullets.append(f"Successor path observed through {names}.")
    if buckets.get("incumbency"):
        names = ", ".join(row["entity"] for row in buckets["incumbency"][:3])
        bullets.append(f"Incumbency pressure appears against {names}.")
    if buckets.get("competition"):
        names = ", ".join(row["entity"] for row in buckets["competition"][:3])
        bullets.append(f"Competitive pressure is currently visible from {names}.")
    if buckets.get("award"):
        names = ", ".join(row["entity"] for row in buckets["award"][:3])
        bullets.append(f"Award scaffold remains attached through {names}.")
    if buckets.get("performance"):
        names = ", ".join(row["entity"] for row in buckets["performance"][:2])
        bullets.append(f"Place-of-performance context is attached through {names}.")
    if buckets.get("funding"):
        names = ", ".join(row["entity"] for row in buckets["funding"][:2])
        bullets.append(f"Funding-path context is attached through {names}.")
    if not bullets:
        bullets.append("Helios has lineage-related graph signals, but they are not yet strong enough to describe as a predecessor, successor, or competitive path.")

    strongest = rows[0]
    return f"""
    <div class="info-box">
        <div class="info-box-label">Lineage Read</div>
        <p>{escape(subject_label)} currently has {len(rows)} graph-backed lineage signal{'s' if len(rows) != 1 else ''}. Strongest observed path: {escape(strongest['signal'])} via {escape(strongest['entity'])}.</p>
        <ul>
            {"".join(f"<li>{escape(item)}</li>" for item in bullets[:4])}
        </ul>
    </div>
    """


def _event_bucket(row: dict[str, str]) -> str:
    merged = f"{row.get('event', '')} {row.get('assessment', '')}".lower()
    if "protest" in merged or "gao" in merged or "corrective action" in merged:
        return "protest"
    if "court" in merged or "litig" in merged or "docket" in merged or "complaint" in merged:
        return "litigation"
    return "other"


def _render_event_briefing(rows: list[dict[str, str]], *, subject_label: str) -> str:
    if not rows:
        return f"""
        <div class="warning-box">
            <div class="info-box-label">Legal Read</div>
            <p>No case-level protest or litigation events are attached to {escape(subject_label)} in the current evidence bundle. Helios should treat that as an unresolved legal picture, not as a clean bill of health.</p>
        </div>
        """

    status_counts = Counter(row["status"] for row in rows)
    bucket_counts = Counter(_event_bucket(row) for row in rows)
    top_row = rows[0]
    status_summary = ", ".join(
        f"{count} {status.lower()}" for status, count in sorted(status_counts.items(), key=lambda item: (-item[1], item[0].lower()))
    )
    source_summary = ", ".join(_dedupe_preserve([row["source"] for row in rows])[:3])

    bullets: list[str] = []
    if bucket_counts.get("protest"):
        bullets.append(f"Protest pressure is attached in {bucket_counts['protest']} case event{'s' if bucket_counts['protest'] != 1 else ''}.")
    if bucket_counts.get("litigation"):
        bullets.append(f"Federal litigation signal is attached in {bucket_counts['litigation']} event{'s' if bucket_counts['litigation'] != 1 else ''}.")
    if top_row:
        bullets.append(f"Top attached event: {top_row['event']} ({top_row['status'].lower()}).")
    if source_summary:
        bullets.append(f"Current legal signal is sourced through {source_summary}.")

    return f"""
    <div class="info-box">
        <div class="info-box-label">Legal Read</div>
        <p>{escape(subject_label)} currently has {len(rows)} attached legal event{'s' if len(rows) != 1 else ''}. Status mix: {escape(status_summary)}.</p>
        <ul>
            {"".join(f"<li>{escape(item)}</li>" for item in bullets[:4])}
        </ul>
    </div>
    """


def _finding_rows(contexts: list[dict[str, Any]], limit: int = 6) -> list[dict[str, str]]:
    rows_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for context in contexts:
        enrichment = context.get("enrichment") if isinstance(context.get("enrichment"), dict) else {}
        for finding in _curate_dossier_findings(enrichment, limit=limit):
            if not isinstance(finding, dict):
                continue
            title = _clean_text(finding.get("title"), "Material finding")
            source = _source_display_name(_clean_text(finding.get("source"), "unknown"))
            severity = _clean_text(finding.get("severity"), "info").lower()
            detail = _clean_text(
                finding.get("detail") or finding.get("assessment"),
                "No analyst detail was attached to this finding.",
            )
            rows_by_key[(_normalize_name(title), source.lower())] = {
                "title": title,
                "source": source,
                "severity": severity,
                "detail": detail,
            }
        for finding in _context_vehicle_intelligence(context).get("findings") or []:
            if not isinstance(finding, dict):
                continue
            title = _clean_text(finding.get("title"), "Material finding")
            source = _source_display_name(_clean_text(finding.get("source"), "unknown"))
            severity = _clean_text(finding.get("severity"), "info").lower()
            detail = _clean_text(
                finding.get("detail") or finding.get("assessment"),
                "No analyst detail was attached to this finding.",
            )
            rows_by_key[(_normalize_name(title), source.lower())] = {
                "title": title,
                "source": source,
                "severity": severity,
                "detail": detail,
            }
    rows = list(rows_by_key.values())
    rows.sort(key=lambda item: (_SEVERITY_PRIORITY.get(item["severity"], 5), item["title"].lower()))
    return rows[:limit]


def _evidence_footprint(contexts: list[dict[str, Any]]) -> dict[str, Any]:
    connectors_run = 0
    connectors_with_data = 0
    source_counts: dict[str, int] = {}

    for context in contexts:
        enrichment = context.get("enrichment") if isinstance(context.get("enrichment"), dict) else {}
        summary = enrichment.get("summary") if isinstance(enrichment.get("summary"), dict) else {}
        connectors_run += int(summary.get("connectors_run") or 0)
        connectors_with_data += int(summary.get("connectors_with_data") or 0)
        vehicle_intelligence = _context_vehicle_intelligence(context)
        connectors_run += int(vehicle_intelligence.get("connectors_run") or 0)
        connectors_with_data += int(vehicle_intelligence.get("connectors_with_data") or 0)

        for rel in _context_relationships(context):
            if not isinstance(rel, dict):
                continue
            for label in _relationship_sources(rel):
                source_counts[label] = source_counts.get(label, 0) + 1

        for event in _context_case_events(context):
            if not isinstance(event, dict):
                continue
            label = _source_display_name(_clean_text(event.get("connector"), "case_evidence"))
            source_counts[label] = source_counts.get(label, 0) + 1

        for finding in _context_findings(context):
            if not isinstance(finding, dict):
                continue
            label = _source_display_name(_clean_text(finding.get("source"), "unknown"))
            source_counts[label] = source_counts.get(label, 0) + 1

    top_sources = sorted(source_counts.items(), key=lambda item: (-item[1], item[0].lower()))[:4]
    return {
        "linked_case_count": len(contexts),
        "connectors_run": connectors_run,
        "connectors_with_data": connectors_with_data,
        "top_sources": top_sources,
    }


def _passport_snapshot(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {
            "recommended_view": "Unresolved",
            "consensus_level": "Unresolved",
            "network_relationship_count": 0,
            "missing_families": [],
        }

    supplier_passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}
    tribunal = supplier_passport.get("tribunal") if isinstance(supplier_passport.get("tribunal"), dict) else {}
    passport_graph = supplier_passport.get("graph") if isinstance(supplier_passport.get("graph"), dict) else {}
    graph_intelligence = passport_graph.get("intelligence") if isinstance(passport_graph.get("intelligence"), dict) else {}

    recommended_view = _clean_text(tribunal.get("recommended_view"), "Unresolved").replace("_", " ").title()
    consensus_level = _clean_text(tribunal.get("consensus_level"), "Unresolved").replace("_", " ").title()
    network_relationship_count = int(
        passport_graph.get("network_relationship_count")
        or passport_graph.get("relationship_count")
        or 0
    )
    missing_families = _dedupe_preserve(
        [str(family).replace("_", " ") for family in (graph_intelligence.get("missing_required_edge_families") or []) if family]
    )
    return {
        "recommended_view": recommended_view,
        "consensus_level": consensus_level,
        "network_relationship_count": network_relationship_count,
        "missing_families": missing_families,
    }


def _case_recommendation(context: dict[str, Any] | None) -> str:
    if not context:
        return "Unresolved"
    score = context.get("score") if isinstance(context.get("score"), dict) else {}
    calibrated = score.get("calibrated") if isinstance(score.get("calibrated"), dict) else {}
    recommendation = _clean_text(calibrated.get("program_recommendation"))
    if recommendation:
        return recommendation.replace("_", " ").title()
    tier = _clean_text(calibrated.get("calibrated_tier"))
    if tier:
        return tier.replace("_", " ").title()
    passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}
    tribunal = passport.get("tribunal") if isinstance(passport.get("tribunal"), dict) else {}
    recommended_view = _clean_text(tribunal.get("recommended_view"))
    if recommended_view:
        return recommended_view.replace("_", " ").title()
    return "Unresolved"


def _case_probability_pct(context: dict[str, Any] | None) -> int:
    if not context:
        return 0
    score = context.get("score") if isinstance(context.get("score"), dict) else {}
    calibrated = score.get("calibrated") if isinstance(score.get("calibrated"), dict) else {}
    return round(float(calibrated.get("calibrated_probability") or 0.0) * 100)


def _graph_claim_coverage_pct(context: dict[str, Any] | None) -> int:
    if not context:
        return 0
    graph_summary = context.get("graph_summary") if isinstance(context.get("graph_summary"), dict) else {}
    intelligence = graph_summary.get("intelligence") if isinstance(graph_summary.get("intelligence"), dict) else {}
    return round(float(intelligence.get("claim_coverage_pct") or 0.0) * 100)


def _graph_relationship_count(context: dict[str, Any] | None) -> int:
    if not context:
        return 0
    graph_summary = context.get("graph_summary") if isinstance(context.get("graph_summary"), dict) else {}
    return int(graph_summary.get("relationship_count") or len(graph_summary.get("relationships") or []))


def _gap_rows(
    *,
    vehicle_name: str,
    contexts: list[dict[str, Any]],
    contract_data: dict[str, Any],
    teaming_rows: list[dict[str, Any]],
    lineage_rows: list[dict[str, Any]],
    event_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    if not contexts:
        gaps.append(
            {
                "gap": "Helios case context",
                "classification": "UNCLASS",
                "priority": "P0",
                "notes": "No live Helios case context is attached for the requested vendor IDs, so graph-backed vehicle reasoning cannot fire.",
            }
        )
    if not teaming_rows:
        gaps.append(
            {
                "gap": "Subcontractor and teaming map",
                "classification": "UNCLASS",
                "priority": "P0",
                "notes": f"No confirmed subcontractor or teaming relationships are attached to {vehicle_name} in the current evidence bundle.",
            }
        )
    if not lineage_rows:
        gaps.append(
            {
                "gap": "Vehicle lineage",
                "classification": "UNCLASS",
                "priority": "P1",
                "notes": "No predecessor, successor, incumbent, competed-on, or award-under relationships are attached to the graph yet.",
            }
        )
    if not event_rows:
        gaps.append(
            {
                "gap": "Litigation and protest profile",
                "classification": "UNCLASS",
                "priority": "P1",
                "notes": "No case-level protest or litigation events are attached to the current evidence bundle.",
            }
        )
    if not _clean_text(contract_data.get("contract_id")):
        gaps.append(
            {
                "gap": "Award identifier",
                "classification": "UNCLASS",
                "priority": "P1",
                "notes": "Contract ID or award identifier was not supplied in the request metadata.",
            }
        )
    if not contract_data.get("task_orders"):
        gaps.append(
            {
                "gap": "Task order visibility",
                "classification": "UNCLASS",
                "priority": "P1",
                "notes": "Task order count or obligation detail was not supplied, so the runway view is still metadata-thin.",
            }
        )

    missing_families: list[str] = []
    thin_graph_cases: list[str] = []
    for context in contexts:
        vendor = context.get("vendor") if isinstance(context.get("vendor"), dict) else {}
        graph_summary = context.get("graph_summary") if isinstance(context.get("graph_summary"), dict) else {}
        intelligence = graph_summary.get("intelligence") if isinstance(graph_summary.get("intelligence"), dict) else {}
        for family in intelligence.get("missing_required_edge_families") or []:
            if isinstance(family, str):
                missing_families.append(family)
        relationship_count = int(graph_summary.get("relationship_count") or len(graph_summary.get("relationships") or []))
        claim_coverage_pct = round(float(intelligence.get("claim_coverage_pct") or 0.0) * 100)
        if relationship_count > 0 and claim_coverage_pct < 50:
            thin_graph_cases.append(_clean_text(vendor.get("name"), "linked case"))

    missing_families = _dedupe_preserve([family.replace("_", " ") for family in missing_families])
    if missing_families:
        gaps.append(
            {
                "gap": "Required capture graph families",
                "classification": "UNCLASS",
                "priority": "P0",
                "notes": "Missing required edge families: " + ", ".join(missing_families) + ".",
            }
        )
    if thin_graph_cases:
        gaps.append(
            {
                "gap": "Graph claim coverage",
                "classification": "UNCLASS",
                "priority": "P1",
                "notes": "Claim coverage is still thin for " + ", ".join(_dedupe_preserve(thin_graph_cases)) + ".",
            }
        )

    if not gaps:
        gaps.append(
            {
                "gap": "Current blocking gaps",
                "classification": "UNCLASS",
                "priority": "P2",
                "notes": "No blocking evidence gaps are attached beyond normal collection expansion and refresh discipline.",
            }
        )
    gaps.sort(key=lambda item: (item["priority"], item["gap"].lower()))
    return gaps


def _action_rows(vehicle_support: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for gap in vehicle_support.get("gaps", [])[:4]:
        gap_name = gap["gap"]
        if gap_name == "Helios case context":
            action = "Bind requested vendor IDs to a live Helios case"
            success = "At least one linked case returns score, graph, and supplier-passport context on rerender."
        elif gap_name == "Subcontractor and teaming map":
            action = "Resolve real teammate and subcontractor edges"
            success = "Vehicle rerender shows named teammate rows with claim-backed provenance instead of unresolved state."
        elif gap_name == "Vehicle lineage":
            action = "Promote predecessor, successor, and competed-on signals"
            success = "Lineage section shows named adjacent vehicles or competitors with evidence summaries."
        elif gap_name == "Litigation and protest profile":
            action = "Run protest and litigation sweep"
            success = "Vehicle rerender attaches case-level event rows or an explicit evidence gap artifact."
        elif gap_name == "Required capture graph families":
            action = "Close capture-intelligence family gaps"
            success = "Graph summary no longer reports missing required capture families."
        elif gap_name == "Graph claim coverage":
            action = "Increase graph claim coverage on linked case"
            success = "Claim-backed coverage clears 50% on the next dossier render."
        else:
            action = "Refresh submitted award metadata"
            success = "Key request metadata fields are filled with current contract identifiers and task-order detail."
        rows.append(
            {
                "priority": gap["priority"],
                "action": action,
                "success": success,
            }
        )
    return rows


def _build_vehicle_support(
    *,
    vehicle_name: str,
    prime_contractor: str,
    vendor_ids: list[str] | None,
    contract_data: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = contract_data or {}
    contexts = _load_case_contexts(vendor_ids, vehicle_name=vehicle_name)
    primary_context = _pick_primary_context(contexts, prime_contractor)
    teaming_rows = _relationship_rows(
        contexts,
        vehicle_name=vehicle_name,
        prime_contractor=prime_contractor,
        rel_types=_TEAMING_RELATIONSHIP_TYPES,
    )
    lineage_rows = _relationship_rows(
        contexts,
        vehicle_name=vehicle_name,
        prime_contractor=prime_contractor,
        rel_types=_LINEAGE_RELATIONSHIP_TYPES,
    )
    event_rows = _event_rows(contexts)
    finding_rows = _finding_rows(contexts)
    gaps = _gap_rows(
        vehicle_name=vehicle_name,
        contexts=contexts,
        contract_data=payload,
        teaming_rows=teaming_rows,
        lineage_rows=lineage_rows,
        event_rows=event_rows,
    )
    evidence_footprint = _evidence_footprint(contexts)
    passport_snapshot = _passport_snapshot(primary_context)
    return {
        "vehicle_name": vehicle_name,
        "prime_contractor": prime_contractor,
        "vendor_ids": list(vendor_ids or []),
        "contract_data": payload,
        "contexts": contexts,
        "primary_context": primary_context,
        "teaming_rows": teaming_rows,
        "lineage_rows": lineage_rows,
        "event_rows": event_rows,
        "finding_rows": finding_rows,
        "gaps": gaps,
        "recommendation": _case_recommendation(primary_context),
        "probability_pct": _case_probability_pct(primary_context),
        "claim_coverage_pct": _graph_claim_coverage_pct(primary_context),
        "relationship_count": _graph_relationship_count(primary_context),
        "evidence_footprint": evidence_footprint,
        "passport_snapshot": passport_snapshot,
    }


def _render_signal_table(rows: list[dict[str, Any]], empty_message: str) -> str:
    table_rows = rows or [
        {
            "entity": "Unresolved",
            "signal": "Unresolved",
            "corroboration": "0 records",
            "provenance": "No linked evidence bundle",
            "assessment": empty_message,
        }
    ]
    body = "".join(
        f"""
        <tr>
            <td><strong>{escape(str(row['entity']))}</strong></td>
            <td>{escape(str(row['signal']))}</td>
            <td>{escape(str(row['corroboration']))}</td>
            <td>{escape(str(row['provenance']))}</td>
            <td>{escape(str(row['assessment']))}</td>
        </tr>
        """
        for row in table_rows
    )
    return f"""
    <table>
        <thead>
            <tr>
                <th>Observed Entity</th>
                <th>Signal</th>
                <th>Corroboration</th>
                <th>Provenance</th>
                <th>Assessment</th>
            </tr>
        </thead>
        <tbody>{body}</tbody>
    </table>
    """


def _render_event_table(rows: list[dict[str, str]], empty_message: str) -> str:
    table_rows = rows or [
        {
            "event": "No attached case event",
            "status": "Unresolved",
            "source": "Current evidence bundle",
            "assessment": empty_message,
        }
    ]
    body = "".join(
        f"""
        <tr>
            <td><strong>{escape(row['event'])}</strong></td>
            <td>{escape(row['status'])}</td>
            <td>{escape(row['source'])}</td>
            <td>{escape(row['assessment'])}</td>
        </tr>
        """
        for row in table_rows
    )
    return f"""
    <table>
        <thead>
            <tr>
                <th>Event</th>
                <th>Status</th>
                <th>Source</th>
                <th>Assessment</th>
            </tr>
        </thead>
        <tbody>{body}</tbody>
    </table>
    """


def _render_gap_table(rows: list[dict[str, str]]) -> str:
    body = "".join(
        f"""
        <tr>
            <td><strong>{escape(row['gap'])}</strong></td>
            <td>{_badge(row['classification'], 'info')}</td>
            <td>{_badge(row['priority'], 'error' if row['priority'] == 'P0' else 'warning' if row['priority'] == 'P1' else 'neutral')}</td>
            <td>{escape(row['notes'])}</td>
        </tr>
        """
        for row in rows
    )
    return f"""
    <table>
        <thead>
            <tr>
                <th>Intelligence Gap</th>
                <th>Classification</th>
                <th>Priority</th>
                <th>Notes</th>
            </tr>
        </thead>
        <tbody>{body}</tbody>
    </table>
    """


def _render_action_table(rows: list[dict[str, str]]) -> str:
    body = "".join(
        f"""
        <tr>
            <td>{_badge(row['priority'], 'error' if row['priority'] == 'P0' else 'warning' if row['priority'] == 'P1' else 'neutral')}</td>
            <td><strong>{escape(row['action'])}</strong></td>
            <td>{escape(row['success'])}</td>
        </tr>
        """
        for row in rows
    )
    return f"""
    <table>
        <thead>
            <tr>
                <th>Priority</th>
                <th>Action Item</th>
                <th>Success Criteria</th>
            </tr>
        </thead>
        <tbody>{body}</tbody>
    </table>
    """


def _render_teaming_intelligence_section(report: dict[str, Any] | None) -> str:
    if not report:
        return """
        <div class="info-box">
            <div class="info-box-label">Teaming Intelligence</div>
            <p>Competitive teaming intelligence is not attached to this dossier render yet.</p>
        </div>
        """

    top_conclusions = report.get("top_conclusions") or []
    assessed_partners = report.get("assessed_partners") or []
    if not assessed_partners:
        message = escape(str(report.get("message") or "Helios could not build an assessed partner map from the current graph snapshot."))
        return f"""
        <div class="info-box">
            <div class="info-box-label">Teaming Intelligence</div>
            <p>{message}</p>
        </div>
        """

    rows = []
    for partner in assessed_partners[:6]:
        evidence = partner.get("evidence") or []
        strongest = evidence[0] if evidence else {}
        rows.append(
            {
                "entity": partner.get("display_name") or partner.get("entity_name") or "Unknown",
                "signal": f"{partner.get('classification', 'unknown')} · {partner.get('confidence_label', 'low')} confidence",
                "corroboration": f"{len(evidence)} evidence rows",
                "provenance": strongest.get("connector") or "knowledge_graph",
                "assessment": partner.get("rationale") or strongest.get("snippet") or "Graph-backed signal",
            }
        )

    summary_html = ""
    if top_conclusions:
        bullets = "".join(f"<li>{escape(str(item))}</li>" for item in top_conclusions[:4])
        summary_html = f"""
        <div class="info-box">
            <div class="info-box-label">Aegis Teaming Read</div>
            <ul>{bullets}</ul>
        </div>
        """

    return summary_html + _render_signal_table(rows, "No assessed partner map survived the current graph snapshot.")


def _render_findings_html(rows: list[dict[str, str]], empty_message: str) -> str:
    if not rows:
        return f"""
        <div class="info-box">
            <div class="info-box-label">Evidence State</div>
            <p>{escape(empty_message)}</p>
        </div>
        """
    fragments = []
    for row in rows[:4]:
        severity = row["severity"]
        badge_type = "error" if severity == "critical" else "warning" if severity in {"high", "medium"} else "info"
        fragments.append(
            f"""
            <div class="key-finding">
                <div class="key-finding-label">{escape(row['source'])} · {escape(severity.upper())}</div>
                <div class="key-finding-text">{escape(row['title'])}</div>
                <p>{escape(row['detail'])}</p>
                <div>{_badge(severity.upper(), badge_type)}</div>
            </div>
            """
        )
    return "".join(fragments)


def _availability_badge(kind: str) -> str:
    normalized = kind.lower()
    if normalized == "available":
        return _badge("Available", "success")
    if normalized == "partial":
        return _badge("Partial", "warning")
    return _badge("Unresolved", "error")


def _render_data_availability_table(vehicle_supports: list[dict[str, Any]]) -> str:
    categories: list[tuple[str, str]] = [
        ("Linked Helios case", "contexts"),
        ("Graph relationship evidence", "graph"),
        ("Teaming evidence", "teaming"),
        ("Litigation / protest events", "events"),
        ("Material findings", "findings"),
    ]
    header = "<table><thead><tr><th>Data Category</th>"
    for support in vehicle_supports:
        header += f"<th>{escape(support['vehicle_name'])}</th>"
    header += "<th>Comparative Value</th></tr></thead><tbody>"
    rows = []
    for label, key in categories:
        states: list[str] = []
        for support in vehicle_supports:
            if key == "contexts":
                state = "available" if support["contexts"] else "unresolved"
            elif key == "graph":
                state = "available" if support["relationship_count"] > 0 else "unresolved"
            elif key == "teaming":
                state = "available" if support["teaming_rows"] else "unresolved"
            elif key == "events":
                state = "available" if support["event_rows"] else "unresolved"
            else:
                state = "available" if support["finding_rows"] else "unresolved"
            states.append(state)
        comparative_value = (
            "Both vehicles are populated."
            if states and all(state == "available" for state in states)
            else "Only one side is populated."
            if "available" in states
            else "Both sides are still unresolved."
        )
        row = f"<tr><td><strong>{escape(label)}</strong></td>"
        for state in states:
            row += f"<td>{_availability_badge(state)}</td>"
        row += f"<td>{escape(comparative_value)}</td></tr>"
        rows.append(row)
    return header + "".join(rows) + "</tbody></table>"


def _comparative_teaming_rows(vehicle_supports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(vehicle_supports) < 2:
        return []
    first, second = vehicle_supports[0], vehicle_supports[1]
    first_entities = {row["entity"]: row for row in first["teaming_rows"]}
    second_entities = {row["entity"]: row for row in second["teaming_rows"]}
    names = sorted(
        {name for name in first_entities} | {name for name in second_entities},
        key=lambda item: item.lower(),
    )
    rows: list[dict[str, Any]] = []
    for name in names[:8]:
        on_first = name in first_entities
        on_second = name in second_entities
        if on_first and on_second:
            assessment = "Persistent across both compared vehicles."
        elif on_first:
            assessment = f"Observed only on {first['vehicle_name']}."
        else:
            assessment = f"Observed only on {second['vehicle_name']}."
        rows.append(
            {
                "entity": name,
                "first": _status_cell(on_first),
                "second": _status_cell(on_second),
                "assessment": assessment,
            }
        )
    return rows


def _render_comparative_teaming_table(vehicle_supports: list[dict[str, Any]]) -> str:
    rows = _comparative_teaming_rows(vehicle_supports)
    if len(vehicle_supports) < 2:
        return _render_signal_table([], "Comparative teaming analysis requires two populated vehicle supports.")
    first_name = vehicle_supports[0]["vehicle_name"]
    second_name = vehicle_supports[1]["vehicle_name"]
    if not rows:
        rows = [
            {
                "entity": "No shared teammate evidence attached",
                "first": _status_cell(False),
                "second": _status_cell(False),
                "assessment": "The compared vehicles do not yet have named teammate overlap in the current evidence bundle.",
            }
        ]
    body = "".join(
        f"""
        <tr>
            <td><strong>{escape(row['entity'])}</strong></td>
            <td>{row['first']}</td>
            <td>{row['second']}</td>
            <td>{escape(row['assessment'])}</td>
        </tr>
        """
        for row in rows
    )
    return f"""
    <table>
        <thead>
            <tr>
                <th>Observed Entity</th>
                <th>{escape(first_name)}</th>
                <th>{escape(second_name)}</th>
                <th>Assessment</th>
            </tr>
        </thead>
        <tbody>{body}</tbody>
    </table>
    """


def _aggregated_lineage_rows(vehicle_supports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for support in vehicle_supports:
        for row in support["lineage_rows"]:
            rows.append(
                {
                    "vehicle": support["vehicle_name"],
                    "entity": row["entity"],
                    "signal": row["signal"],
                    "provenance": row["provenance"],
                    "assessment": row["assessment"],
                }
            )
    return rows


def _aggregated_event_rows(vehicle_supports: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for support in vehicle_supports:
        for row in support["event_rows"]:
            rows.append(
                {
                    "vehicle": support["vehicle_name"],
                    "event": row["event"],
                    "status": row["status"],
                    "source": row["source"],
                    "assessment": row["assessment"],
                }
            )
    return rows


def _render_comparative_event_table(vehicle_supports: list[dict[str, Any]]) -> str:
    rows = _aggregated_event_rows(vehicle_supports)
    if not rows:
        rows = [
            {
                "vehicle": "Unresolved",
                "event": "No attached protest or litigation event",
                "status": "Unresolved",
                "source": "Current evidence bundle",
                "assessment": "The compared vehicles do not yet have case-level protest or litigation events attached.",
            }
        ]
    body = "".join(
        f"""
        <tr>
            <td><strong>{escape(row['vehicle'])}</strong></td>
            <td>{escape(row['event'])}</td>
            <td>{escape(row['status'])}</td>
            <td>{escape(row['source'])}</td>
            <td>{escape(row['assessment'])}</td>
        </tr>
        """
        for row in rows[:10]
    )
    return f"""
    <table>
        <thead>
            <tr>
                <th>Vehicle</th>
                <th>Event</th>
                <th>Status</th>
                <th>Source</th>
                <th>Assessment</th>
            </tr>
        </thead>
        <tbody>{body}</tbody>
    </table>
    """


def generate_comparative_dossier(
    vehicle_configs: list[dict],
    title: str = "",
    subtitle: str = "",
    analyst_name: str = "AXIOM Intelligence Module",
    classification: str = "UNCLASSIFIED // FOUO",
) -> str:
    """
    Generate comparative dossier HTML for 2+ vehicles.
    
    Args:
        vehicle_configs: List of dicts with vehicle_name, prime_contractor, vendor_ids, contract_data
        title: Main title (auto-generated if empty)
        subtitle: Subtitle (auto-generated if empty)
        analyst_name: Analyst/team name for footer
        classification: Classification line
    
    Returns:
        Self-contained HTML string
    """
    
    if not vehicle_configs or len(vehicle_configs) < 2:
        raise ValueError("Comparative dossier requires 2+ vehicles")
    
    if not title:
        v1 = vehicle_configs[0].get("vehicle_name", "Vehicle A")
        v2 = vehicle_configs[1].get("vehicle_name", "Vehicle B")
        title = f"SOCPAC C5ISR Vehicle Lineage: {v1} to {v2}"
    
    if not subtitle:
        subtitle = "Teaming Persistence Analysis + Active vs Expired Data Comparison"
    
    now = datetime.utcnow().strftime("%Y-%m-%d")
    vehicle_supports = [
        _build_vehicle_support(
            vehicle_name=_clean_text(config.get("vehicle_name"), "Unknown Vehicle"),
            prime_contractor=_clean_text(config.get("prime_contractor"), "Unknown Prime"),
            vendor_ids=config.get("vendor_ids"),
            contract_data=config.get("contract_data", {}),
        )
        for config in vehicle_configs
    ]

    kpi_sections: list[str] = []
    comparative_summary_lines: list[str] = []
    for support in vehicle_supports:
        contract_data = support["contract_data"]
        kpi_cards = [
            ("Award / Ceiling", _format_currency(contract_data.get("award_amount") or contract_data.get("total_ceiling"))),
            ("Current Helios View", support["recommendation"]),
            ("Graph Claim Coverage", f"{support['claim_coverage_pct']}%"),
            ("Graph Relationships", str(support["relationship_count"])),
        ]
        if contract_data.get("employees"):
            kpi_cards.append(("Employees", _format_number(contract_data.get("employees"))))
        kpi_html = f"""
        <div class="section-header">
            <span class="section-number">Vehicle Profile:</span>
            <span class="section-title">{escape(support['vehicle_name'])}</span>
        </div>
        <div class="kpi-container">
            {"".join(
                f'''
            <div class="kpi-card">
                <div class="kpi-value">{escape(str(value))}</div>
                <div class="kpi-label">{escape(label)}</div>
            </div>
                '''
                for label, value in kpi_cards[:5]
            )}
        </div>
        """
        kpi_sections.append(kpi_html)
        if support["contexts"]:
            comparative_summary_lines.append(
                f"{support['vehicle_name']} currently carries {support['recommendation']} with "
                f"{support['probability_pct']}% modeled risk, {support['claim_coverage_pct']}% claim coverage, "
                f"and {support['relationship_count']} graph relationships."
            )
        else:
            comparative_summary_lines.append(
                f"{support['vehicle_name']} is currently metadata-first because no linked Helios case context was attached."
            )

    award_table = "<table><thead><tr><th>Field</th>"
    for support in vehicle_supports:
        award_table += f"<th>{escape(support['vehicle_name'])}</th>"
    award_table += "</tr></thead><tbody>"
    fields = [
        ("Prime Contractor", "prime_contractor"),
        ("Contract ID", "contract_id"),
        ("Award Date", "award_date"),
        ("Status", "status"),
        ("NAICS", "naics"),
        ("Task Orders", "task_orders"),
        ("Ceiling", "total_ceiling"),
    ]
    for field_label, field_key in fields:
        award_table += f"<tr><td><strong>{escape(field_label)}</strong></td>"
        for support in vehicle_supports:
            contract_data = support["contract_data"]
            if field_key == "prime_contractor":
                value = support["prime_contractor"]
            else:
                value = contract_data.get(field_key, "N/A")
            if field_key in {"total_ceiling"} and value not in ("N/A", None, ""):
                value = _format_currency(float(value))
            award_table += f"<td>{escape(str(value))}</td>"
        award_table += "</tr>"
    award_table += "</tbody></table>"

    aggregated_lineage_rows = _aggregated_lineage_rows(vehicle_supports)
    if aggregated_lineage_rows:
        lineage_body = "".join(
            f"""
            <tr>
                <td><strong>{escape(row['vehicle'])}</strong></td>
                <td>{escape(row['entity'])}</td>
                <td>{escape(row['signal'])}</td>
                <td>{escape(row['provenance'])}</td>
                <td>{escape(row['assessment'])}</td>
            </tr>
            """
            for row in aggregated_lineage_rows[:10]
        )
    else:
        lineage_body = """
            <tr>
                <td><strong>Unresolved</strong></td>
                <td>No attached lineage evidence</td>
                <td>Vehicle lineage</td>
                <td>Current evidence bundle</td>
                <td>No predecessor, successor, incumbent, or competed-on relationship is attached yet.</td>
            </tr>
        """
    lineage_table = f"""
    <table>
        <thead>
            <tr>
                <th>Vehicle</th>
                <th>Observed Entity</th>
                <th>Signal</th>
                <th>Provenance</th>
                <th>Assessment</th>
            </tr>
        </thead>
        <tbody>{lineage_body}</tbody>
    </table>
    """
    lineage_briefing_html = _render_lineage_briefing(
        [
            {
                "entity": row["entity"],
                "signal": row["signal"],
                "provenance": row["provenance"],
                "assessment": row["assessment"],
            }
            for row in aggregated_lineage_rows
        ],
        subject_label="the compared vehicles",
    )
    comparative_event_rows = _aggregated_event_rows(vehicle_supports)
    litigation_briefing_html = _render_event_briefing(
        [
            {
                "event": row["event"],
                "status": row["status"],
                "source": row["source"],
                "assessment": row["assessment"],
            }
            for row in comparative_event_rows
        ],
        subject_label="the compared vehicles",
    )

    aggregated_findings = []
    for support in vehicle_supports:
        for row in support["finding_rows"]:
            finding = dict(row)
            finding["title"] = f"{support['vehicle_name']}: {row['title']}"
            aggregated_findings.append(finding)
    aggregated_findings.sort(key=lambda item: (_SEVERITY_PRIORITY.get(item["severity"], 5), item["title"].lower()))

    aggregated_actions: list[dict[str, str]] = []
    seen_actions: set[tuple[str, str]] = set()
    for support in vehicle_supports:
        for row in _action_rows(support):
            marker = (row["action"], row["success"])
            if marker in seen_actions:
                continue
            seen_actions.add(marker)
            aggregated_actions.append(row)

    # Assemble complete HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Comparative Dossier</title>
    {BASE_CSS}
</head>
<body>
    <div class="page-wrapper">
        <!-- Header -->
        <div class="header-badges">
            <span class="badge-category badge-orange">SUBCONTRACTOR ANALYSIS</span>
            <span class="badge-category badge-blue">ENRICHMENT</span>
            <span class="badge-category badge-green">INTELLIGENCE ANALYSIS</span>
        </div>
        
        <h1>{escape(title)}</h1>
        <div class="subtitle">{escape(subtitle)}</div>
        
        <div class="header-meta">
            <div class="header-meta-item"><strong>Date:</strong> {now}</div>
            <div class="header-meta-item"><strong>Classification:</strong> {escape(classification)}</div>
            <div class="header-meta-item"><strong>Analyst:</strong> {escape(analyst_name)}</div>
        </div>
        
        <!-- Section 1: Award Anatomy -->
        <div class="section-header">
            <span class="section-number">1.</span>
            <span class="section-title">Award Anatomy: Side-by-Side</span>
        </div>
        {award_table}
        
        <!-- Section 2: Vehicle Profiles + KPIs -->
        {"".join(kpi_sections)}
        
        <div class="narrative">
            {"".join(f"<p>{escape(line)}</p>" for line in comparative_summary_lines)}
        </div>
        
        <!-- Section 3: Teaming Persistence -->
        <div class="section-header">
            <span class="section-number">3.</span>
            <span class="section-title">Teaming & Subcontractor Intelligence</span>
        </div>
        <div class="info-box">
            <div class="info-box-label">Analysis Method</div>
            <p>Comparative teaming rows below are derived from the current Helios graph and attached case contexts. Where no live case context exists, the dossier leaves the row unresolved instead of inventing teammate history.</p>
        </div>
        {_render_comparative_teaming_table(vehicle_supports)}
        
        <!-- Section 4: Data Availability -->
        <div class="section-header">
            <span class="section-number">4.</span>
            <span class="section-title">Data Availability: Active vs Expired Vehicle</span>
        </div>
        {_render_data_availability_table(vehicle_supports)}
        
        <!-- Section 5: Vehicle Lineage Map -->
        <div class="section-header">
            <span class="section-number">5.</span>
            <span class="section-title">Vehicle Lineage Map</span>
        </div>
        {lineage_briefing_html}
        {lineage_table}
        <div class="narrative">
            <p>
                This lineage section is graph-backed. If Helios has not yet promoted predecessor, successor, incumbent, or competed-on relationships for a compared vehicle, that uncertainty remains explicit in the table above.
            </p>
        </div>
        
        <!-- Section 6: Litigation & Protest Profile -->
        <div class="section-header">
            <span class="section-number">6.</span>
            <span class="section-title">Litigation & Protest Profile</span>
        </div>
        {litigation_briefing_html}
        {_render_comparative_event_table(vehicle_supports)}

        <!-- Section 7: Risk Signals -->
        <div class="section-header">
            <span class="section-number">7.</span>
            <span class="section-title">OSINT Risk Signals</span>
        </div>
        {_render_findings_html(aggregated_findings, "No material comparative findings survived curation across the attached vehicle contexts.")}
        
        <!-- Section 8: Recommendations -->
        <div class="section-header">
            <span class="section-number">8.</span>
            <span class="section-title">Preliminary Capture Viability Assessment</span>
        </div>
        <div class="narrative">
            <p>
                This comparative read is only as strong as the linked case evidence behind each vehicle. The current recommendation set below is derived from attached graph gaps, case-event coverage, and teammate persistence signals rather than canned capture heuristics.
            </p>
        </div>
        {_render_action_table(aggregated_actions[:5] or [{"priority": "P2", "action": "Refresh vehicle evidence bundle", "success": "Rerender once live case context is attached for both compared vehicles."}])}
        
        <div style="margin-top: 64px; padding-top: 32px; border-top: 1px solid #E2E8F0; font-size: 12px; color: #94A3B8;">
            <p><strong>Report Generated:</strong> {now} | <strong>Analyst:</strong> {escape(analyst_name)}</p>
            <p><strong>Classification:</strong> {escape(classification)}</p>
            <p>This report contains OSINT synthesis and analytical assessment. Conclusions reflect available
            public sources and modeling confidence levels noted in each section.</p>
        </div>
    </div>
</body>
</html>
"""
    
    return html


def generate_vehicle_dossier(
    vehicle_name: str,
    prime_contractor: str,
    vendor_ids: list[str] = None,
    contract_data: dict = None,
    analyst_name: str = "AXIOM Intelligence Module",
    classification: str = "UNCLASSIFIED // FOUO",
) -> str:
    """
    Generate single-vehicle dossier HTML (ITEAMS format).
    
    Args:
        vehicle_name: Contract vehicle name (e.g., "ITEAMS")
        prime_contractor: Prime contractor legal name
        vendor_ids: List of vendor/subcontractor IDs to analyze
        contract_data: Dict with contract metadata
        analyst_name: Analyst/team name
        classification: Classification line
    
    Returns:
        Self-contained HTML string
    """
    
    if not contract_data:
        contract_data = {}

    vendor_ids = vendor_ids or []
    now = datetime.utcnow().strftime("%Y-%m-%d")
    vehicle_support = _build_vehicle_support(
        vehicle_name=vehicle_name,
        prime_contractor=prime_contractor,
        vendor_ids=vendor_ids,
        contract_data=contract_data,
    )
    try:
        from teaming_intelligence import build_teaming_intelligence

        teaming_report = build_teaming_intelligence(
            vehicle_name=vehicle_name,
            observed_vendors=[{"vendor_name": prime_contractor, "role": "prime"}],
        )
    except Exception:
        teaming_report = None

    ceiling = contract_data.get("total_ceiling")
    obligated = contract_data.get("total_obligated")
    remaining = ceiling - obligated if ceiling and obligated else None
    kpi_cards = [
        ("Total Ceiling", _format_currency(ceiling)),
        ("Total Obligated", _format_currency(obligated)),
        ("Remaining Ceiling", _format_currency(remaining)),
        ("Task Orders", _format_number(contract_data.get("task_orders"))),
        ("Helios View", vehicle_support["recommendation"]),
        ("Graph Claim Coverage", f"{vehicle_support['claim_coverage_pct']}%"),
    ]
    if contract_data.get("revenue"):
        kpi_cards.append(("Prime Revenue", _format_currency(contract_data.get("revenue"))))
    if contract_data.get("employees"):
        kpi_cards.append(("Employees", _format_number(contract_data.get("employees"))))
    kpi_html = '<div class="kpi-container">' + "".join(
        f"""
        <div class="kpi-card">
            <div class="kpi-value">{escape(str(value))}</div>
            <div class="kpi-label">{escape(label)}</div>
        </div>
        """
        for label, value in kpi_cards[:8]
    ) + "</div>"

    award_rows = [
        ("Prime Contractor", prime_contractor),
        ("NAICS Code", contract_data.get("naics", "N/A")),
        ("SAM Entity ID", contract_data.get("sam_entity_id", "N/A")),
        ("Contract ID", contract_data.get("contract_id", "N/A")),
        ("Award Date", contract_data.get("award_date", "N/A")),
        ("Place of Performance", contract_data.get("place_of_performance", "N/A")),
        ("Task Orders", contract_data.get("task_orders", "N/A")),
    ]
    award_details = """
    <table>
        <thead>
            <tr>
                <th>Field</th>
                <th>Value</th>
            </tr>
        </thead>
        <tbody>
    """
    award_details += "".join(
        f"<tr><td><strong>{escape(str(label))}</strong></td><td>{escape(str(value))}</td></tr>"
        for label, value in award_rows
    )
    award_details += "</tbody></table>"

    if vehicle_support["contexts"]:
        prime_narrative = (
            f"{prime_contractor} is linked to {vehicle_support['relationship_count']} graph relationships with "
            f"{vehicle_support['claim_coverage_pct']}% claim coverage. Current Helios posture is "
            f"{vehicle_support['recommendation']} at {vehicle_support['probability_pct']}% modeled risk."
        )
    else:
        prime_narrative = (
            "No linked Helios case context was found for the requested vendor IDs. This prime section is constrained "
            "to the submitted award metadata and explicitly leaves unresolved areas open."
        )

    top_finding = vehicle_support["finding_rows"][0] if vehicle_support["finding_rows"] else None
    if top_finding:
        key_finding_html = f"""
        <div class="key-finding">
            <div class="key-finding-label">{escape(top_finding['source'])} · {escape(top_finding['severity'].upper())}</div>
            <div class="key-finding-text">{escape(top_finding['title'])}</div>
            <p>{escape(top_finding['detail'])}</p>
        </div>
        """
    else:
        key_finding_html = """
        <div class="info-box">
            <div class="info-box-label">Evidence State</div>
            <p>No material prime-contractor finding survived curation on the linked case context.</p>
        </div>
        """

    subcontractor_html = _render_signal_table(
        vehicle_support["teaming_rows"],
        "No confirmed subcontractor or teaming relationships are attached to the current evidence bundle.",
    )
    teaming_intelligence_html = _render_teaming_intelligence_section(teaming_report)
    lineage_html = _render_signal_table(
        vehicle_support["lineage_rows"],
        "No predecessor, successor, incumbent, competed-on, or award-under relationships are attached to this vehicle yet.",
    )
    lineage_briefing_html = _render_lineage_briefing(
        vehicle_support["lineage_rows"],
        subject_label=vehicle_name,
    )
    litigation_html = _render_event_table(
        vehicle_support["event_rows"],
        "No case-level protest or litigation events are attached to this vehicle in the current evidence bundle.",
    )
    litigation_briefing_html = _render_event_briefing(
        vehicle_support["event_rows"],
        subject_label=vehicle_name,
    )
    gaps_html = _render_gap_table(vehicle_support["gaps"])
    actions_html = _render_action_table(_action_rows(vehicle_support))

    if vehicle_support["contexts"]:
        assessment_copy = (
            f"{vehicle_name} currently reads as {vehicle_support['recommendation']} with "
            f"{vehicle_support['probability_pct']}% modeled risk. The graph is carrying "
            f"{vehicle_support['relationship_count']} relationships at {vehicle_support['claim_coverage_pct']}% claim coverage."
        )
    else:
        assessment_copy = (
            f"{vehicle_name} is currently a metadata-first read because Helios could not attach a live case context "
            "for the supplied vendor IDs."
        )
    blocking_gap_notes = "; ".join(gap["notes"] for gap in vehicle_support["gaps"][:2])
    evidence_footprint = vehicle_support["evidence_footprint"]
    passport_snapshot = vehicle_support["passport_snapshot"]
    top_source_text = ", ".join(
        f"{source} ({count})" for source, count in evidence_footprint["top_sources"]
    ) or "No concentrated public-source signal is attached yet."
    missing_family_text = ", ".join(passport_snapshot["missing_families"]) or "No required capture graph families are currently flagged as missing."
    evidence_footprint_html = f"""
        <div class="info-box">
            <div class="info-box-label">Evidence Footprint</div>
            <ul>
                <li>Linked Helios cases: {evidence_footprint['linked_case_count']}</li>
                <li>Connectors run: {evidence_footprint['connectors_run']}</li>
                <li>Connectors with signal: {evidence_footprint['connectors_with_data']}</li>
                <li>Top contributing sources: {escape(top_source_text)}</li>
            </ul>
        </div>
    """
    supplier_passport_html = f"""
        <table>
            <thead>
                <tr>
                    <th>Supplier Passport Field</th>
                    <th>Current Read</th>
                </tr>
            </thead>
            <tbody>
                <tr><td><strong>Recommended view</strong></td><td>{escape(passport_snapshot['recommended_view'])}</td></tr>
                <tr><td><strong>Tribunal consensus</strong></td><td>{escape(passport_snapshot['consensus_level'])}</td></tr>
                <tr><td><strong>Network relationships</strong></td><td>{passport_snapshot['network_relationship_count']}</td></tr>
                <tr><td><strong>Required graph families</strong></td><td>{escape(missing_family_text)}</td></tr>
            </tbody>
        </table>
    """

    # Assemble complete HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vehicle Dossier: {escape(vehicle_name)}</title>
    {BASE_CSS}
</head>
<body>
    <div class="page-wrapper">
        <!-- Header -->
        <div class="header-badges">
            <span class="badge-category badge-orange">CONTRACT VEHICLE</span>
            <span class="badge-category badge-blue">INTELLIGENCE ANALYSIS</span>
        </div>
        
        <h1>{escape(vehicle_name)}</h1>
        <div class="subtitle">Contract Vehicle Intelligence Dossier</div>
        
        <div class="header-meta">
            <div class="header-meta-item"><strong>Prime:</strong> {escape(prime_contractor)}</div>
            <div class="header-meta-item"><strong>NAICS:</strong> {contract_data.get("naics", "N/A")}</div>
            <div class="header-meta-item"><strong>Date:</strong> {now}</div>
            <div class="header-meta-item"><strong>Classification:</strong> {escape(classification)}</div>
        </div>
        
        <!-- Section 1: Award Anatomy -->
        <div class="section-header">
            <span class="section-number">1.</span>
            <span class="section-title">Award Anatomy</span>
        </div>
        {kpi_html}
        {award_details}
        
        <!-- Section 2: Mission Scope -->
        <div class="section-header">
            <span class="section-number">2.</span>
            <span class="section-title">Mission Scope & Requirements</span>
        </div>
        <div class="narrative">
            <p>
                {escape(vehicle_name)} is currently being summarized through the live evidence Helios has for the linked vendor IDs plus the submitted award metadata. This section is intentionally factual: it does not invent scope language beyond what Helios can actually anchor.
            </p>
        </div>
        {evidence_footprint_html}
        <div class="info-box">
            <div class="info-box-label">Key Constraints</div>
            <ul>
                <li>Submitted award metadata: Contract ID {escape(str(contract_data.get("contract_id", "not supplied")))}</li>
                <li>Linked vendor IDs: {escape(", ".join(vehicle_support["vendor_ids"]) or "none supplied")}</li>
                <li>Current Helios view: {escape(vehicle_support["recommendation"])}</li>
                <li>Graph coverage: {vehicle_support['claim_coverage_pct']}% claim coverage across {vehicle_support['relationship_count']} relationships</li>
            </ul>
        </div>
        
        <!-- Section 3: Prime Contractor -->
        <div class="section-header">
            <span class="section-number">3.</span>
            <span class="section-title">Prime Contractor: {escape(prime_contractor)}</span>
        </div>
        <div class="kpi-container">
            <div class="kpi-card">
                <div class="kpi-value">{_format_currency(contract_data.get("revenue"))}</div>
                <div class="kpi-label">Annual Revenue</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">{_format_number(contract_data.get("employees"))}</div>
                <div class="kpi-label">Employees</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">{escape(vehicle_support['recommendation'])}</div>
                <div class="kpi-label">Current Helios View</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">{vehicle_support['claim_coverage_pct']}%</div>
                <div class="kpi-label">Graph Claim Coverage</div>
            </div>
        </div>
        <div class="narrative">
            <p>{escape(prime_narrative)}</p>
        </div>
        {supplier_passport_html}
        {key_finding_html}
        
        <!-- Section 4: Subcontractor Intelligence -->
        <div class="section-header">
            <span class="section-number">4.</span>
            <span class="section-title">Subcontractor & Teaming Intelligence</span>
        </div>
        <div class="warning-box">
            <div class="info-box-label">Data Limitation</div>
            <p>The rows below are evidence-bound. If Helios has not attached named subcontractor or teaming edges to the current vehicle context, the table stays unresolved instead of fabricating roster data.</p>
        </div>
        {subcontractor_html}
        
        <!-- Section 5: Competitive Teaming Map -->
        <div class="section-header">
            <span class="section-number">5.</span>
            <span class="section-title">Competitive Teaming Map</span>
        </div>
        <div class="warning-box">
            <div class="info-box-label">State Contract</div>
            <p>This section separates observed graph signals from Helios assessed partner classes. It does not turn prediction into graph fact.</p>
        </div>
        {teaming_intelligence_html}

        <!-- Section 6: Vehicle Lineage -->
        <div class="section-header">
            <span class="section-number">6.</span>
            <span class="section-title">Vehicle Lineage & Competitive Landscape</span>
        </div>
        {lineage_briefing_html}
        {lineage_html}
        
        <!-- Section 7: Litigation Profile -->
        <div class="section-header">
            <span class="section-number">7.</span>
            <span class="section-title">Litigation & Protest Profile</span>
        </div>
        {litigation_briefing_html}
        {litigation_html}
        
        <!-- Section 8: Risk Assessment -->
        <div class="section-header">
            <span class="section-number">8.</span>
            <span class="section-title">Aggregated Risk Signals</span>
        </div>
        <div class="info-box">
            <div class="info-box-label">Source Concentration</div>
            <p>{escape(top_source_text)}</p>
        </div>
        {_render_findings_html(vehicle_support['finding_rows'], "No material vehicle-specific findings survived curation on the linked case context.")}
        
        <!-- Section 9: Gap Analysis -->
        <div class="section-header">
            <span class="section-number">9.</span>
            <span class="section-title">Gap Analysis: Intelligence Gaps</span>
        </div>
        {gaps_html}
        
        <!-- Section 10: Preliminary Assessment -->
        <div class="section-header">
            <span class="section-number">10.</span>
            <span class="section-title">Preliminary Capture Viability Assessment</span>
        </div>
        <div class="narrative">
            <p>{escape(assessment_copy)}</p>
            <p><strong>Current blockers:</strong> {escape(blocking_gap_notes)}</p>
        </div>
        {actions_html}
        
        <div style="margin-top: 64px; padding-top: 32px; border-top: 1px solid #E2E8F0; font-size: 12px; color: #94A3B8;">
            <p><strong>Report Generated:</strong> {now} | <strong>Analyst:</strong> {escape(analyst_name)}</p>
            <p><strong>Classification:</strong> {escape(classification)}</p>
            <p>This report contains OSINT synthesis and analytical assessment. Conclusions reflect available
            public sources and modeling confidence levels noted in each section.</p>
        </div>
    </div>
</body>
</html>
"""
    
    return html
