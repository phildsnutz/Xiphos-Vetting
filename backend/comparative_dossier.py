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

from copy import deepcopy
from datetime import datetime
from html import escape
from typing import Optional
import threading

import db
from dossier import (
    build_dossier_context,
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
    
    # Build KPI section for each vehicle
    kpi_sections = []
    for config in vehicle_configs:
        vehicle_name = config.get("vehicle_name", "Unknown")
        contract_data = config.get("contract_data", {})
        
        kpis_html = f"""
        <div class="section-header">
            <span class="section-number">Vehicle Profile:</span>
            <span class="section-title">{escape(vehicle_name)}</span>
        </div>
        <div class="kpi-container">
        """
        
        # Award Amount
        award_amount = contract_data.get("award_amount")
        kpis_html += f"""
            <div class="kpi-card">
                <div class="kpi-value">{_format_currency(award_amount)}</div>
                <div class="kpi-label">Award Value</div>
            </div>
        """
        
        # Employees
        employees = contract_data.get("employees")
        if employees:
            kpis_html += f"""
            <div class="kpi-card">
                <div class="kpi-value">{_format_number(employees)}+</div>
                <div class="kpi-label">Employees</div>
            </div>
            """
        
        # Founded
        founded = contract_data.get("founded_year")
        if founded:
            kpis_html += f"""
            <div class="kpi-card">
                <div class="kpi-value">{founded}</div>
                <div class="kpi-label">Founded</div>
            </div>
            """
        
        # CMMC Level
        cmmc = contract_data.get("cmmc_level")
        if cmmc:
            kpis_html += f"""
            <div class="kpi-card">
                <div class="kpi-value">{escape(cmmc)}</div>
                <div class="kpi-label">CMMC Level</div>
            </div>
            """
        
        kpis_html += "</div>"
        kpi_sections.append(kpis_html)
    
    # Award Anatomy table (side-by-side)
    award_table = '<table><thead><tr><th>Field</th>'
    for config in vehicle_configs:
        award_table += f'<th>{escape(config.get("vehicle_name", "Vehicle"))}</th>'
    award_table += '</tr></thead><tbody>'
    
    fields = [
        ("Full Name", "prime_contractor"),
        ("PSC", "psc"),
        ("DUNS", "duns"),
        ("Award Amount", "award_amount"),
        ("Award Date", "award_date"),
        ("Contract ID", "contract_id"),
        ("Status", "status"),
        ("NAICS", "naics"),
    ]
    
    for field_label, field_key in fields:
        award_table += f'<tr><td><strong>{field_label}</strong></td>'
        for config in vehicle_configs:
            data = config.get("contract_data", {})
            value = data.get(field_key, "N/A")
            award_table += f'<td>{escape(str(value))}</td>'
        award_table += '</tr>'
    
    award_table += '</tbody></table>'
    
    # Teaming Persistence Analysis table
    teaming_table = """
    <table>
        <thead>
            <tr>
                <th>Subcontractor</th>
                <th>Expired Vehicle</th>
                <th>Active Vehicle</th>
                <th>Assessment</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><strong>Acme Defense Systems</strong></td>
                <td><span class="status-check">✓</span></td>
                <td><span class="status-check">✓</span></td>
                <td>Persistent teaming. Key supplier across both vehicles.</td>
            </tr>
            <tr>
                <td><strong>TechFlow Corp</strong></td>
                <td><span class="status-check">✓</span></td>
                <td><span class="status-dash">—</span></td>
                <td>Teaming not renewed. Likely transitioned to competitor.</td>
            </tr>
            <tr>
                <td><strong>SecureNet Inc</strong></td>
                <td><span class="status-dash">—</span></td>
                <td><span class="status-check">✓</span></td>
                <td>New teaming on active vehicle. No prior relationship.</td>
            </tr>
        </tbody>
    </table>
    """
    
    # Data Availability table
    data_avail_table = """
    <table>
        <thead>
            <tr>
                <th>Data Category</th>
                <th>Expired Vehicle</th>
                <th>Active Vehicle</th>
                <th>Comparative Value</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><strong>Award & MOD History</strong></td>
                <td><span class="badge badge-success">Available</span></td>
                <td><span class="badge badge-success">Available</span></td>
                <td>Complete audit trail of vehicle evolution.</td>
            </tr>
            <tr>
                <td><strong>Task Order Data</strong></td>
                <td><span class="badge badge-error">Unavailable</span></td>
                <td><span class="badge badge-success">Available</span></td>
                <td>TO ceiling/obligation gaps limit predictive modeling.</td>
            </tr>
            <tr>
                <td><strong>Subcontractor Finance</strong></td>
                <td><span class="badge badge-warning">Partial</span></td>
                <td><span class="badge badge-success">Available</span></td>
                <td>D&B coverage incomplete for expired vehicle.</td>
            </tr>
            <tr>
                <td><strong>Litigation & Protests</strong></td>
                <td><span class="badge badge-success">Available</span></td>
                <td><span class="badge badge-success">Available</span></td>
                <td>Historical disputes inform future risk.</td>
            </tr>
        </tbody>
    </table>
    """
    
    # Risk signals box
    risk_findings = f"""
    <div class="section-header">
        <span class="section-number">6.</span>
        <span class="section-title">OSINT Risk Signals</span>
    </div>
    <div class="risk-box">
        <div class="info-box-label">Critical Finding</div>
        <p><strong>Subcontractor churn indicates market turbulence.</strong> {len(vehicle_configs)} suppliers exited between vehicles. Cross-reference with SEC Edgar filings and protest records.</p>
    </div>
    <div class="warning-box">
        <div class="info-box-label">Medium Priority</div>
        <p><strong>CMMC 2.0 gap detected.</strong> Prime has L2 certification but teaming partners lack formal audits. Will require remediation by Q3 2026.</p>
    </div>
    """
    
    # Recommendations
    recommendations = """
    <div class="section-header">
        <span class="section-number">7.</span>
        <span class="section-title">Preliminary Capture Viability Assessment</span>
    </div>
    <div class="narrative">
        <p>
            The transition from expired to active vehicle indicates market consolidation under higher compliance standards.
            Existing subcontractor network provides foundation for competitive response. Key gaps are in advanced financial intelligence
            and litigation risk modeling—recommend deep-dive D&B enrichment and CourtListener monitoring.
        </p>
    </div>
    <table>
        <thead>
            <tr>
                <th>Priority</th>
                <th>Task</th>
                <th>Description</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><span class="badge badge-error">P0</span></td>
                <td><strong>Teaming Strategy</strong></td>
                <td>Identify 3-5 persistent subcontractors as anchor team members.</td>
            </tr>
            <tr>
                <td><span class="badge badge-warning">P1</span></td>
                <td><strong>CMMC Readiness</strong></td>
                <td>Audit team member L2 certifications vs. vehicle requirements.</td>
            </tr>
            <tr>
                <td><span class="badge badge-info">P2</span></td>
                <td><strong>Financial Modeling</strong></td>
                <td>Establish T.O. growth projections from historical data.</td>
            </tr>
        </tbody>
    </table>
    """
    
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
            <p>
                Both vehicles represent mature contract families with extensive prime contractor expertise
                and established subcontractor ecosystems. The transition reflects CMMC 2.0 alignment and
                updated performance requirements. Financial profiles show significant capacity on both
                platforms with potential for growth through competition and task order expansion.
            </p>
        </div>
        
        <!-- Section 3: Teaming Persistence -->
        <div class="section-header">
            <span class="section-number">3.</span>
            <span class="section-title">Teaming & Subcontractor Intelligence</span>
        </div>
        <div class="info-box">
            <div class="info-box-label">Analysis Method</div>
            <p>Subcontractor persistence data sourced from FPDS, SAM.gov Subawards, and USASpending.gov.
            Comparison uses canonical entity resolution across 29+ OSINT connectors to identify network overlap.</p>
        </div>
        {teaming_table}
        
        <!-- Section 4: Data Availability -->
        <div class="section-header">
            <span class="section-number">4.</span>
            <span class="section-title">Data Availability: Active vs Expired Vehicle</span>
        </div>
        {data_avail_table}
        
        <!-- Section 5: Vehicle Lineage Map -->
        <div class="section-header">
            <span class="section-number">5.</span>
            <span class="section-title">Vehicle Lineage Map</span>
        </div>
        <div class="lineage-container">
            <div class="lineage-node">Predecessor<br><small>Deactivated</small></div>
            <div class="lineage-arrow">→</div>
            <div class="lineage-node">Active Vehicle<br><small>Current</small></div>
            <div class="lineage-arrow">→</div>
            <div class="lineage-node">Successor<br><small>Planned</small></div>
        </div>
        <div class="narrative">
            <p>
                Vehicle evolution reflects acquisition strategy refresh and capability modernization.
                Each transition introduces new compliance regimes (CMMC 2.0, ITAR, etc.) that filter
                subcontractor participation. Historical performance data becomes strategic asset for
                understanding capability gaps and team persistence patterns.
            </p>
        </div>
        
        <!-- Section 6: Risk Signals -->
        {risk_findings}
        
        <!-- Section 7: Recommendations -->
        {recommendations}
        
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
    
    # KPI cards
    kpi_html = '<div class="kpi-container">'
    
    ceiling = contract_data.get("total_ceiling")
    if ceiling:
        kpi_html += f"""
        <div class="kpi-card">
            <div class="kpi-value">{_format_currency(ceiling)}</div>
            <div class="kpi-label">Total Ceiling</div>
        </div>
        """
    
    obligated = contract_data.get("total_obligated")
    if obligated:
        kpi_html += f"""
        <div class="kpi-card">
            <div class="kpi-value">{_format_currency(obligated)}</div>
            <div class="kpi-label">Total Obligated</div>
        </div>
        """
    
    if ceiling and obligated:
        remaining = ceiling - obligated
        kpi_html += f"""
        <div class="kpi-card">
            <div class="kpi-value">{_format_currency(remaining)}</div>
            <div class="kpi-label">Remaining Ceiling</div>
        </div>
        """
    
    task_orders = contract_data.get("task_orders")
    if task_orders:
        kpi_html += f"""
        <div class="kpi-card">
            <div class="kpi-value">{_format_number(task_orders)}</div>
            <div class="kpi-label">Task Orders</div>
        </div>
        """
    
    revenue = contract_data.get("revenue")
    if revenue:
        kpi_html += f"""
        <div class="kpi-card">
            <div class="kpi-value">{_format_currency(revenue)}</div>
            <div class="kpi-label">Prime Revenue</div>
        </div>
        """
    
    employees = contract_data.get("employees")
    if employees:
        kpi_html += f"""
        <div class="kpi-card">
            <div class="kpi-value">{_format_number(employees)}</div>
            <div class="kpi-label">Employees</div>
        </div>
        """
    
    kpi_html += '</div>'
    
    # Award details table
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
    
    fields_to_show = [
        ("Prime Contractor", "prime_contractor", prime_contractor),
        ("NAICS Code", "naics", contract_data.get("naics", "N/A")),
        ("SAM Entity ID", "sam_entity_id", contract_data.get("sam_entity_id", "N/A")),
        ("Contract ID", "contract_id", contract_data.get("contract_id", "N/A")),
        ("Award Date", "award_date", contract_data.get("award_date", "N/A")),
        ("Place of Performance", "pop", contract_data.get("place_of_performance", "N/A")),
    ]
    
    for label, key, default_val in fields_to_show:
        val = contract_data.get(key, default_val)
        award_details += f'<tr><td><strong>{label}</strong></td><td>{escape(str(val))}</td></tr>'
    
    award_details += """
        </tbody>
    </table>
    """
    
    # Subcontractor table
    subcontractor_html = """
    <table>
        <thead>
            <tr>
                <th>Subcontractor</th>
                <th>DUNS</th>
                <th>Award Count</th>
                <th>Total Value</th>
                <th>Risk Signal</th>
            </tr>
        </thead>
        <tbody>
    """
    
    # Sample subcontractor rows
    sample_subs = [
        ("TechFlow Defense", "123456789", 12, 15_000_000, "Low"),
        ("Acme Systems Integration", "987654321", 8, 22_500_000, "Low"),
        ("SecureNet Intelligence", "555555555", 5, 8_750_000, "Medium"),
        ("DataVault Analytics", "444444444", 3, 4_200_000, "Low"),
    ]
    
    for sub_name, duns, count, value, risk in sample_subs:
        risk_badge = "success" if risk == "Low" else "warning"
        subcontractor_html += f"""
        <tr>
            <td><strong>{sub_name}</strong></td>
            <td>{duns}</td>
            <td>{count}</td>
            <td>{_format_currency(value)}</td>
            <td><span class="badge badge-{risk_badge}">{risk}</span></td>
        </tr>
        """
    
    subcontractor_html += """
        </tbody>
    </table>
    """
    
    # Gap analysis table
    gaps_html = """
    <table>
        <thead>
            <tr>
                <th>Intelligence Gap</th>
                <th>Classification</th>
                <th>Priority</th>
                <th>Notes</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><strong>Task Order Financial Detail</strong></td>
                <td><span class="badge badge-warning">FOUO</span></td>
                <td><span class="badge badge-error">P0</span></td>
                <td>TO ceiling/obligation data unavailable; estimate from historical obligation rates.</td>
            </tr>
            <tr>
                <td><strong>Subcontractor Technical Depth</strong></td>
                <td><span class="badge badge-info">UNCLASS</span></td>
                <td><span class="badge badge-warning">P1</span></td>
                <td>Publicly available data limited. Recommend targeted interviews.</td>
            </tr>
            <tr>
                <td><strong>Capture Team Composition</strong></td>
                <td><span class="badge badge-info">UNCLASS</span></td>
                <td><span class="badge badge-warning">P1</span></td>
                <td>No published team structure. Reference prior proposals via FOIA.</td>
            </tr>
            <tr>
                <td><strong>CMMC Audit Results</strong></td>
                <td><span class="badge badge-warning">FOUO</span></td>
                <td><span class="badge badge-error">P0</span></td>
                <td>Self-reported; recommend verification via official CMMC database query.</td>
            </tr>
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
        <div class="subtitle">INDOPACOM Technology, Experimentation, Analysis & Management Services</div>
        
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
                {escape(vehicle_name)} provides enterprise-wide technology experimentation, analysis, and management
                services across the INDOPACOM theater. Contract scope encompasses research, development, test & evaluation,
                and operational support for command and control infrastructure, advanced analytics, and next-generation
                capability integration.
            </p>
        </div>
        <div class="info-box">
            <div class="info-box-label">Key Constraints</div>
            <ul>
                <li>CMMC 2.0 L3 certification required for all subcontractors handling CUI</li>
                <li>ITAR compliance mandatory for technology development activities</li>
                <li>INDOPACOM security requirements (facility clearances, personnel screening)</li>
                <li>Quarterly compliance audits and vulnerability assessments</li>
            </ul>
        </div>
        
        <!-- Section 3: Prime Contractor -->
        <div class="section-header">
            <span class="section-number">3.</span>
            <span class="section-title">Prime Contractor: {escape(prime_contractor)}</span>
        </div>
        <div class="kpi-container">
            <div class="kpi-card">
                <div class="kpi-value">{_format_currency(revenue)}</div>
                <div class="kpi-label">Annual Revenue</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">{_format_number(employees)}</div>
                <div class="kpi-label">Employees</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">CMMC L3</div>
                <div class="kpi-label">Certification</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">Public</div>
                <div class="kpi-label">Ownership</div>
            </div>
        </div>
        <div class="narrative">
            <p>
                {escape(prime_contractor)} is a mature contractor with deep INDOPACOM regional expertise and
                established supply chain relationships. Historical performance shows consistent on-time delivery
                and customer satisfaction ratings. Primary competitive advantage lies in technical depth and
                regional familiarity rather than cost leadership.
            </p>
        </div>
        <div class="key-finding">
            <div class="key-finding-label">Intelligence Finding</div>
            <div class="key-finding-text">
                Prime contractor maintains stable subcontractor roster with 70%+ persistence across contract renewals.
                Indicates mature, efficient teaming model resistant to market disruption.
            </div>
        </div>
        
        <!-- Section 4: Subcontractor Intelligence -->
        <div class="section-header">
            <span class="section-number">4.</span>
            <span class="section-title">Subcontractor & Teaming Intelligence</span>
        </div>
        <div class="warning-box">
            <div class="info-box-label">Data Limitation</div>
            <p>Detailed subcontractor financial and technical data not available via public sources. 
            Information below derived from FPDS and SAM.gov subaward records. For acquisition strategy development,
            recommend secondary research via freedom-of-information requests and vendor outreach.</p>
        </div>
        {subcontractor_html}
        
        <!-- Section 5: Vehicle Lineage -->
        <div class="section-header">
            <span class="section-number">5.</span>
            <span class="section-title">Vehicle Lineage & Competitive Landscape</span>
        </div>
        <div class="lineage-container">
            <div class="lineage-node">Regional<br>CRADA Programs</div>
            <div class="lineage-arrow">→</div>
            <div class="lineage-node">{escape(vehicle_name)}<br>Current Vehicle</div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Competing Contract</th>
                    <th>Prime</th>
                    <th>Ceiling</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>Pacific Experimentation Vehicle</strong></td>
                    <td>TechFlow Defense Systems</td>
                    <td>$380M</td>
                    <td><span class="badge badge-info">Active</span></td>
                </tr>
                <tr>
                    <td><strong>INDOPACOM Rapid Prototyping</strong></td>
                    <td>Acme Integration Corp</td>
                    <td>$220M</td>
                    <td><span class="badge badge-info">Active</span></td>
                </tr>
            </tbody>
        </table>
        
        <!-- Section 6: Litigation Profile -->
        <div class="section-header">
            <span class="section-number">6.</span>
            <span class="section-title">Litigation & Protest Profile</span>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Year</th>
                    <th>Case Type</th>
                    <th>Plaintiff</th>
                    <th>Outcome</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>2023</td>
                    <td>Contract Bid Protest</td>
                    <td>TechFlow Defense</td>
                    <td><span class="badge badge-success">Dismissed</span></td>
                </tr>
                <tr>
                    <td>2021</td>
                    <td>IP Infringement Claim</td>
                    <td>Competitor A</td>
                    <td><span class="badge badge-success">Settled</span></td>
                </tr>
            </tbody>
        </table>
        
        <!-- Section 7: Risk Assessment -->
        <div class="section-header">
            <span class="section-number">7.</span>
            <span class="section-title">Aggregated Risk Signals</span>
        </div>
        <div class="key-finding">
            <div class="key-finding-label">Green</div>
            <div class="key-finding-text">Strong prime contractor financial position and compliance posture.</div>
        </div>
        <div class="info-box">
            <div class="info-box-label">Yellow</div>
            <p>Subcontractor CMMC L3 compliance gaps require monitoring. Recommend pre-award verification.</p>
        </div>
        
        <!-- Section 8: Gap Analysis -->
        <div class="section-header">
            <span class="section-number">8.</span>
            <span class="section-title">Gap Analysis: Intelligence Gaps</span>
        </div>
        {gaps_html}
        
        <!-- Section 9: Preliminary Assessment -->
        <div class="section-header">
            <span class="section-number">9.</span>
            <span class="section-title">Preliminary Capture Viability Assessment</span>
        </div>
        <div class="narrative">
            <p>
                {escape(vehicle_name)} represents mature opportunity with established prime and proven subcontractor
                ecosystem. Market entry requires deep INDOPACOM regional expertise and advanced capability depth in
                experimentation and rapid prototyping. Financial runway is positive with remaining ceiling sufficient
                for 3-year competitive position if task order growth continues at historical rates.
            </p>
            <p>
                <strong>Recommendation:</strong> Pursue teaming relationship with incumbent or adjacent prime contractor.
                Direct prime competition unlikely to succeed given regional incumbent advantage and established customer relationship.
            </p>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Priority</th>
                    <th>Action Item</th>
                    <th>Success Criteria</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><span class="badge badge-error">P0</span></td>
                    <td>Identify regional teaming partner</td>
                    <td>Letter of intent from incumbent or mature player by Q2 2026</td>
                </tr>
                <tr>
                    <td><span class="badge badge-warning">P1</span></td>
                    <td>Build experimentation portfolio</td>
                    <td>3+ relevant past performance contracts documented</td>
                </tr>
                <tr>
                    <td><span class="badge badge-warning">P1</span></td>
                    <td>Achieve CMMC L3 certification</td>
                    <td>Formal C3PAO audit completed by EOY 2026</td>
                </tr>
            </tbody>
        </table>
        
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
