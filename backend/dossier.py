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

import json
from datetime import datetime
from html import escape
from typing import Optional

import db


def _severity_color(severity: str) -> str:
    """Map severity level to hex color."""
    colors = {
        "critical": "#dc3545",
        "high": "#fd7e14",
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
        "elevated": "#fd7e14",
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
    color = "#dc3545" if pct >= 70 else "#fd7e14" if pct >= 40 else "#198754"

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


def _generate_executive_summary(vendor: dict, score: dict, enrichment: Optional[dict]) -> str:
    """Generate executive summary section."""
    if not score:
        return ""

    calibrated = score.get("calibrated", {})
    probability = calibrated.get("calibrated_probability", 0)
    tier = calibrated.get("calibrated_tier", "unknown")

    enrichment_info = ""
    if enrichment:
        enrichment_info = f"""
        <tr>
            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; font-weight: 600;">
                OSINT Risk
            </td>
            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef;">
                {_severity_badge(enrichment.get('overall_risk', 'LOW').lower())}
                ({enrichment.get('summary', {}).get('findings_total', 0)} findings)
            </td>
        </tr>
        """

    return f'''
    <section style="page-break-after: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #fd7e14; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            Executive Summary
        </h2>

        <table style="width: 100%; border-collapse: collapse;">
            <tr>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; font-weight: 600;">
                    Vendor Name
                </td>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef;">
                    {escape(vendor.get('name', 'Unknown'))}
                </td>
            </tr>
            <tr>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; font-weight: 600;">
                    Country
                </td>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef;">
                    {escape(vendor.get('country', ''))}
                </td>
            </tr>
            <tr>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; font-weight: 600;">
                    Risk Tier
                </td>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef;">
                    {_tier_badge(tier)}
                </td>
            </tr>
            <tr>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; font-weight: 600;">
                    Risk Probability
                </td>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef;">
                    {probability:.1%}
                </td>
            </tr>
            {enrichment_info}
            <tr>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; font-weight: 600;">
                    Report Date
                </td>
                <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef;">
                    {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
                </td>
            </tr>
        </table>

        <div style="margin-top: 16px; padding: 12px; background-color: #f8f9fa;
                    border-left: 4px solid #fd7e14; border-radius: 2px;">
            <strong>Classification: CONFIDENTIAL</strong><br>
            <small style="color: #6c757d;">
                For authorized recipients only. Unauthorized disclosure prohibited.
            </small>
        </div>
    </section>
    '''


def _generate_scoring_breakdown(score: dict) -> str:
    """Generate scoring breakdown with contributions."""
    if not score:
        return ""

    calibrated = score.get("calibrated", {})
    contributions = calibrated.get("contributions", {})

    contrib_html = ""
    if contributions:
        # Sort by absolute value, descending
        sorted_contrib = sorted(
            contributions.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )
        for factor, value in sorted_contrib[:8]:  # Top 8 factors
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
        <h2 style="color: #1a1f36; border-bottom: 3px solid #fd7e14; padding-bottom: 12px;
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

    # Group by source
    by_source = {}
    for f in findings:
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
        findings_html += f'''
        <div style="margin-bottom: 16px; border-left: 4px solid #dee2e6; padding-left: 16px;">
            <strong style="color: #1a1f36; font-size: 13px;">
                {escape(source)}
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

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #fd7e14; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            OSINT Findings
        </h2>

        <div style="font-size: 13px; margin-bottom: 16px; color: #6c757d;">
            Total findings: <strong>{len(findings)}</strong> |
            Critical: <strong style="color: #dc3545;">
                {sum(1 for f in findings if f.get('severity') == 'critical')}
            </strong> |
            High: <strong style="color: #fd7e14;">
                {sum(1 for f in findings if f.get('severity') == 'high')}
            </strong> |
            Medium: <strong style="color: #ffc107;">
                {sum(1 for f in findings if f.get('severity') == 'medium')}
            </strong>
        </div>

        {findings_html if findings else
         '<p style="color: #6c757d; font-style: italic;">No findings detected.</p>'}
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
        <h2 style="color: #1a1f36; border-bottom: 3px solid #fd7e14; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            Risk Signals Timeline
        </h2>
        {timeline_html if timeline_html else
         '<p style="color: #6c757d; font-style: italic;">No monitoring history available.</p>'}
    </section>
    '''


def _generate_ai_narrative(vendor_id: str, vendor: dict) -> str:
    """Generate AI intelligence narrative section from latest analysis."""
    try:
        from ai_analysis import get_latest_analysis
        analysis_data = get_latest_analysis(vendor_id)
    except (ImportError, Exception):
        return ""

    if not analysis_data:
        return ""

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
        "ENHANCED_DUE_DILIGENCE": "#fd7e14",
        "REJECT": "#dc3545",
    }
    verdict_color = verdict_colors.get(verdict, "#6c757d")
    verdict_display = verdict.replace("_", " ")

    # Critical concerns
    concerns_html = ""
    for i, concern in enumerate(analysis.get("critical_concerns", []), 1):
        concerns_html += f'''
        <div style="padding: 6px 0; border-bottom: 1px solid #e9ecef; font-size: 12px;">
            <span style="color: #dc3545; font-weight: 700; font-family: monospace;">{i:02d}</span>
            &nbsp; {escape(concern)}
        </div>
        '''

    # Mitigating factors
    mitigating_html = ""
    for i, factor in enumerate(analysis.get("mitigating_factors", []), 1):
        mitigating_html += f'''
        <div style="padding: 6px 0; border-bottom: 1px solid #e9ecef; font-size: 12px;">
            <span style="color: #198754; font-weight: 700; font-family: monospace;">{i:02d}</span>
            &nbsp; {escape(factor)}
        </div>
        '''

    # Recommended actions
    actions_html = ""
    for i, action in enumerate(analysis.get("recommended_actions", []), 1):
        actions_html += f'''
        <div style="padding: 6px 0; border-bottom: 1px solid #e9ecef; font-size: 12px;">
            <span style="color: #0d6efd; font-weight: 700; font-family: monospace;">{i:02d}</span>
            &nbsp; {escape(action)}
        </div>
        '''

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #fd7e14; padding-bottom: 12px;
                   margin-bottom: 20px; font-size: 18px;">
            AI Intelligence Assessment
        </h2>

        <div style="display: flex; align-items: center; justify-content: space-between;
                    margin-bottom: 16px;">
            <div>
                <span style="display: inline-block; padding: 8px 16px;
                            background-color: {verdict_color}; color: white;
                            border-radius: 4px; font-size: 14px; font-weight: 700;
                            letter-spacing: 1px;">
                    {verdict_display}
                </span>
            </div>
            <div style="font-size: 10px; color: #6c757d; text-align: right;">
                Provider: {escape(provider)} / {escape(model)}<br>
                Generated: {escape(created[:19] if created else 'N/A')}
            </div>
        </div>

        <div style="margin-bottom: 20px;">
            <strong style="font-size: 13px; color: #1a1f36;">Executive Summary</strong>
            <p style="font-size: 12px; line-height: 1.7; color: #1a1f36; margin-top: 8px;">
                {escape(analysis.get('executive_summary', ''))}
            </p>
        </div>

        <div style="margin-bottom: 20px;">
            <strong style="font-size: 13px; color: #1a1f36;">Risk Narrative</strong>
            <p style="font-size: 12px; line-height: 1.7; color: #1a1f36; margin-top: 8px;">
                {escape(analysis.get('risk_narrative', ''))}
            </p>
        </div>

        {f"""
        <div style="margin-bottom: 20px;">
            <strong style="font-size: 13px; color: #dc3545;">
                Critical Concerns ({len(analysis.get('critical_concerns', []))})
            </strong>
            <div style="margin-top: 8px;">{concerns_html}</div>
        </div>
        """ if concerns_html else ""}

        {f"""
        <div style="margin-bottom: 20px;">
            <strong style="font-size: 13px; color: #198754;">
                Mitigating Factors ({len(analysis.get('mitigating_factors', []))})
            </strong>
            <div style="margin-top: 8px;">{mitigating_html}</div>
        </div>
        """ if mitigating_html else ""}

        {f"""
        <div style="margin-bottom: 20px;">
            <strong style="font-size: 13px; color: #0d6efd;">
                Recommended Actions ({len(analysis.get('recommended_actions', []))})
            </strong>
            <div style="margin-top: 8px;">{actions_html}</div>
        </div>
        """ if actions_html else ""}

        <div style="margin-bottom: 20px;">
            <strong style="font-size: 13px; color: #1a1f36;">Regulatory Exposure</strong>
            <p style="font-size: 12px; line-height: 1.7; color: #1a1f36; margin-top: 8px;">
                {escape(analysis.get('regulatory_exposure', ''))}
            </p>
        </div>

        <div style="padding: 10px; background-color: #f8f9fa; border-radius: 4px;
                    font-size: 11px; color: #6c757d;">
            <strong>Confidence:</strong> {escape(analysis.get('confidence_assessment', 'N/A'))}
        </div>
    </section>
    '''


def _generate_recommended_actions(score: dict) -> str:
    """Generate recommended actions from marginal information values."""
    if not score:
        return ""

    calibrated = score.get("calibrated", {})
    miv = calibrated.get("marginal_information_values", {})

    if not miv:
        return ""

    # Sort by value, descending
    sorted_miv = sorted(miv.items(), key=lambda x: abs(x[1]), reverse=True)[:5]

    actions_html = ""
    for factor, value in sorted_miv:
        action = (
            f"Obtain additional information about {factor.replace('_', ' ').lower()} "
            f"to refine risk assessment (potential impact: {abs(value):.2%})"
        )
        actions_html += f'''
        <li style="margin-bottom: 8px; line-height: 1.6;">
            {escape(action)}
        </li>
        '''

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #fd7e14; padding-bottom: 12px;
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
            {escape(entry.get('scored_at', ''))} –
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
            {escape(entry.get('enriched_at', ''))} –
            {entry.get('findings_total', 0)} findings,
            {_severity_badge(entry.get('overall_risk', 'LOW').lower())}
        </div>
        '''
    audit_html += "</div></div></div>"

    return f'''
    <section style="page-break-inside: avoid; margin-bottom: 32px;">
        <h2 style="color: #1a1f36; border-bottom: 3px solid #fd7e14; padding-bottom: 12px;
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


def generate_dossier(vendor_id: str) -> str:
    """
    Generate a complete HTML dossier for a vendor.

    Args:
        vendor_id: The vendor's unique identifier

    Returns:
        Self-contained HTML string ready for display or PDF export
    """
    # Load all data from database
    vendor = db.get_vendor(vendor_id)
    if not vendor:
        return "<p>Vendor not found</p>"

    score = db.get_latest_score(vendor_id)
    enrichment = db.get_latest_enrichment(vendor_id)
    monitoring_history = db.get_monitoring_history(vendor_id, limit=10)

    # Build dossier sections
    sections = [
        _generate_executive_summary(vendor, score, enrichment),
        _generate_scoring_breakdown(score),
        _generate_ai_narrative(vendor_id, vendor),
        _generate_osint_findings(enrichment),
        _generate_risk_timeline(monitoring_history),
        _generate_recommended_actions(score),
        _generate_audit_trail(vendor_id, score, enrichment),
    ]

    # Combine into full HTML document
    html = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Xiphos Vendor Dossier – {escape(vendor.get('name', 'Unknown'))}</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}

            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen,
                            Ubuntu, Cantarell, sans-serif;
                color: #1a1f36;
                background-color: #f5f5f5;
                line-height: 1.6;
            }}

            /* Print styles for PDF */
            @media print {{
                body {{
                    background: white;
                }}
                .container {{
                    box-shadow: none;
                    margin: 0;
                }}
                section {{
                    page-break-inside: avoid;
                }}
                a {{
                    color: #0d6efd;
                    text-decoration: underline;
                }}
            }}

            .container {{
                max-width: 8.5in;
                margin: 20px auto;
                background: white;
                padding: 1in;
                box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
                position: relative;
            }}

            .header {{
                border-bottom: 3px solid #1a1f36;
                padding-bottom: 16px;
                margin-bottom: 32px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}

            .logo {{
                font-size: 20px;
                font-weight: 700;
                color: #fd7e14;
                letter-spacing: 2px;
            }}

            .logo-subtext {{
                font-size: 11px;
                color: #6c757d;
                font-weight: normal;
                letter-spacing: 1px;
            }}

            .classification {{
                text-align: right;
                font-size: 10px;
                font-weight: 700;
                color: #dc3545;
                text-transform: uppercase;
                letter-spacing: 1px;
            }}

            .watermark {{
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%) rotate(-45deg);
                font-size: 80px;
                font-weight: 700;
                color: rgba(220, 53, 69, 0.1);
                pointer-events: none;
                z-index: -1;
                white-space: nowrap;
            }}

            section {{
                margin-bottom: 32px;
                page-break-inside: avoid;
            }}

            h2 {{
                color: #1a1f36;
                border-bottom: 3px solid #fd7e14;
                padding-bottom: 12px;
                margin-bottom: 20px;
                font-size: 18px;
                font-weight: 700;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
            }}

            tr:last-child td {{
                border-bottom: none !important;
            }}

            .badge {{
                display: inline-block;
                padding: 4px 8px;
                border-radius: 3px;
                font-size: 11px;
                font-weight: 600;
                text-transform: uppercase;
                white-space: nowrap;
            }}

            .footer {{
                margin-top: 48px;
                padding-top: 16px;
                border-top: 1px solid #dee2e6;
                font-size: 10px;
                color: #6c757d;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <div class="watermark">CONFIDENTIAL</div>

        <div class="container">
            <div class="header">
                <div>
                    <div class="logo">
                        XIPHOS
                    </div>
                    <div class="logo-subtext">
                        Intelligence-Grade Vendor Assurance
                    </div>
                </div>
                <div class="classification">
                    ⚠ CONFIDENTIAL ⚠<br>
                    AUTHORIZED RECIPIENTS ONLY
                </div>
            </div>

            {''.join(sections)}

            <div class="footer">
                <strong>XIPHOS Intelligence Report</strong> | Vendor ID: {escape(vendor_id)}<br>
                Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} |
                Classification: CONFIDENTIAL<br>
                This document contains proprietary information and is intended solely for the
                use of authorized recipients.
            </div>
        </div>
    </body>
    </html>
    '''

    return html
