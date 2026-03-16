"""
Xiphos PDF Dossier Generator

Generates professional PDF compliance dossiers using reportlab.
Compatible with defense/procurement workflows and ready for archival.
"""

from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib import colors

import db


def _severity_color(severity: str) -> str:
    """Map severity level to hex color."""
    colors_map = {
        "critical": "#DC2626",
        "high": "#F59E0B",
        "medium": "#EAB308",
        "low": "#3B82F6",
        "info": "#6B7280",
    }
    return colors_map.get(severity.lower(), "#6B7280")


def _tier_color(tier: str) -> str:
    """Map tier to hex color for PDF."""
    colors_map = {
        "clear": "#10B981",
        "monitor": "#F59E0B",
        "elevated": "#EF4444",
        "hard_stop": "#DC2626",
    }
    return colors_map.get(tier.lower(), "#6B7280")


def generate_pdf_dossier(vendor_id: str) -> bytes:
    """
    Generate a professional PDF dossier for a vendor.

    Returns:
        bytes: PDF file content
    """
    # Gather all data
    vendor = db.get_vendor(vendor_id)
    if not vendor:
        raise ValueError(f"Vendor {vendor_id} not found")

    score = db.get_latest_score(vendor_id)
    enrichment = db.get_latest_enrichment(vendor_id)
    decisions = db.get_decisions(vendor_id, limit=50)

    # Create PDF in memory
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch,
    )

    # Story (content)
    story = []

    # Get styles
    styles = getSampleStyleSheet()

    # Create custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=HexColor("#FFFFFF"),
        spaceAfter=6,
        fontName='Helvetica-Bold',
    )

    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=HexColor("#1F2937"),
        spaceAfter=10,
        spaceBefore=10,
        fontName='Helvetica-Bold',
    )

    subheading_style = ParagraphStyle(
        'CustomSubHeading',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=HexColor("#374151"),
        spaceAfter=6,
        fontName='Helvetica-Bold',
    )

    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=9,
        textColor=HexColor("#374151"),
        spaceAfter=6,
    )

    muted_style = ParagraphStyle(
        'CustomMuted',
        parent=styles['Normal'],
        fontSize=8,
        textColor=HexColor("#6B7280"),
        spaceAfter=4,
    )

    # === HEADER with CUI banner ===
    header_data = [[Paragraph("XIPHOS COMPLIANCE DOSSIER", title_style)]]
    header_table = Table(header_data, colWidths=[7.5*inch])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), HexColor("#1F2937")),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(header_table)

    # CUI banner
    cui_style = ParagraphStyle(
        'CUIStyle',
        parent=styles['Normal'],
        fontSize=8,
        textColor=HexColor("#FFFFFF"),
        alignment=1,  # center
        fontName='Helvetica-Bold',
    )
    story.append(Table(
        [[Paragraph("CONTROLLED UNCLASSIFIED INFORMATION (CUI)", cui_style)]],
        colWidths=[7.5*inch]
    ).setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), HexColor("#DC2626")),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ])))

    story.append(Spacer(1, 0.1*inch))

    # Metadata line
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(
        f"<b>Generated:</b> {now} | <b>Case ID:</b> {vendor_id} | <b>Subject:</b> {vendor['name']}",
        muted_style
    ))
    story.append(Spacer(1, 0.15*inch))

    # === ENTITY SUMMARY ===
    story.append(Paragraph("ENTITY SUMMARY", heading_style))

    summary_data = [
        ["Vendor Name", vendor["name"]],
        ["Country", vendor["country"]],
        ["Profile", vendor.get("profile", "defense_acquisition")],
        ["Program", vendor.get("program", "standard_industrial")],
        ["Case Created", vendor["created_at"]],
    ]

    summary_table = Table(summary_data, colWidths=[2.5*inch, 5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), HexColor("#F3F4F6")),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor("#1F2937")),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor("#E5E7EB")),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.15*inch))

    # === RISK ASSESSMENT ===
    story.append(Paragraph("RISK ASSESSMENT", heading_style))

    if score:
        cal = score.get("calibrated", {})
        tier = cal.get("calibrated_tier", "unknown").upper().replace("_", " ")
        posterior = cal.get("calibrated_probability", 0)
        composite = score.get("composite_score", 0)
        lo = cal.get("interval", {}).get("lower", 0)
        hi = cal.get("interval", {}).get("upper", 0)

        # Tier badge
        tier_color = _tier_color(cal.get("calibrated_tier", "unknown"))

        risk_data = [
            ["Risk Tier", f"<font color='{tier_color}'><b>{tier}</b></font>"],
            ["Posterior Probability", f"{round(posterior * 100)}%"],
            ["Composite Score", f"{composite}/100"],
            ["Confidence Interval", f"{round(lo * 100)}% – {round(hi * 100)}%"],
            ["Mean Confidence", f"{round(cal.get('calibrated_confidence', 0) * 100)}%"],
        ]

        risk_table = Table(risk_data, colWidths=[2.5*inch, 5*inch])
        risk_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), HexColor("#F3F4F6")),
            ('TEXTCOLOR', (0, 0), (-1, -1), HexColor("#1F2937")),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor("#E5E7EB")),
        ]))
        story.append(risk_table)

    story.append(Spacer(1, 0.15*inch))

    # === CONTRIBUTING FACTORS ===
    if score and cal.get("contributions"):
        story.append(Paragraph("CONTRIBUTING RISK FACTORS", heading_style))

        contrib_data = [
            ["Factor", "Raw Score", "Contribution", "Confidence", "Description"],
        ]

        for ct in sorted(cal.get("contributions", []), key=lambda x: abs(x.get("signed_contribution", 0)), reverse=True):
            raw = f"{ct.get('raw_score', 0):.2f}"
            contrib = f"{ct.get('signed_contribution', 0):+.3f} pp"
            conf = f"{round(ct.get('confidence', 0) * 100)}%"
            desc = ct.get('description', '')[:50]

            contrib_data.append([
                ct.get("factor", "Unknown"),
                raw,
                contrib,
                conf,
                desc,
            ])

        contrib_table = Table(contrib_data, colWidths=[1.5*inch, 0.9*inch, 1.1*inch, 1*inch, 3*inch])
        contrib_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor("#1F2937")),
            ('TEXTCOLOR', (0, 0), (-1, 0), HexColor("#FFFFFF")),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor("#E5E7EB")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor("#FFFFFF"), HexColor("#F9FAFB")]),
        ]))
        story.append(contrib_table)
        story.append(Spacer(1, 0.15*inch))

    # === HARD STOPS ===
    if score and cal.get("hard_stop_decisions"):
        story.append(Paragraph("HARD STOP RULES TRIGGERED", heading_style))

        for stop in cal.get("hard_stop_decisions", []):
            story.append(Paragraph(f"<b>{stop.get('trigger', 'Unknown')}</b>", subheading_style))
            story.append(Paragraph(stop.get('explanation', ''), normal_style))
            story.append(Paragraph(
                f"<i>Confidence: {round(stop.get('confidence', 0) * 100)}%</i>",
                muted_style
            ))
            story.append(Spacer(1, 0.08*inch))

        story.append(Spacer(1, 0.1*inch))

    # === SOFT FLAGS ===
    if score and cal.get("soft_flags"):
        story.append(Paragraph("SOFT FLAGS", heading_style))

        for flag in cal.get("soft_flags", []):
            story.append(Paragraph(f"<b>{flag.get('trigger', 'Unknown')}</b>", subheading_style))
            story.append(Paragraph(flag.get('explanation', ''), normal_style))
            story.append(Paragraph(
                f"<i>Confidence: {round(flag.get('confidence', 0) * 100)}%</i>",
                muted_style
            ))
            story.append(Spacer(1, 0.08*inch))

        story.append(Spacer(1, 0.1*inch))

    # === OSINT ENRICHMENT ===
    if enrichment:
        story.append(Paragraph("OSINT ENRICHMENT SUMMARY", heading_style))

        summary = enrichment.get("summary", {})
        story.append(Paragraph(
            f"<b>Overall Risk:</b> {enrichment.get('overall_risk', 'UNKNOWN')} | "
            f"<b>Connectors:</b> {summary.get('connectors_run', 0)} ran "
            f"({summary.get('connectors_with_data', 0)} with data) | "
            f"<b>Findings:</b> {summary.get('findings_total', 0)} total",
            normal_style
        ))

        story.append(Spacer(1, 0.08*inch))

        # Findings breakdown
        findings = enrichment.get("findings", [])
        if findings:
            story.append(Paragraph("TOP FINDINGS", subheading_style))

            findings_data = [
                ["Severity", "Source", "Title", "Detail"],
            ]

            for finding in findings[:15]:  # Top 15 findings
                findings_data.append([
                    finding.get("severity", "LOW").upper(),
                    finding.get("source", "")[:20],
                    finding.get("title", "")[:30],
                    finding.get("detail", "")[:40],
                ])

            findings_table = Table(findings_data, colWidths=[1*inch, 1.5*inch, 2*inch, 3*inch])
            findings_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor("#1F2937")),
                ('TEXTCOLOR', (0, 0), (-1, 0), HexColor("#FFFFFF")),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('GRID', (0, 0), (-1, -1), 0.5, HexColor("#E5E7EB")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor("#FFFFFF"), HexColor("#F9FAFB")]),
            ]))
            story.append(findings_table)

        story.append(Spacer(1, 0.15*inch))

    # === DECISION HISTORY ===
    if decisions:
        story.append(Paragraph("DECISION HISTORY", heading_style))

        decision_data = [
            ["Date", "Decision", "Decided By", "Reason"],
        ]

        for decision in decisions[:10]:  # Last 10 decisions
            decision_data.append([
                decision.get("created_at", "")[:10],
                decision.get("decision", "").upper(),
                decision.get("decided_by", "Unknown")[:20],
                decision.get("reason", "")[:40] if decision.get("reason") else "—",
            ])

        decision_table = Table(decision_data, colWidths=[1.5*inch, 1.2*inch, 2*inch, 2.8*inch])
        decision_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor("#1F2937")),
            ('TEXTCOLOR', (0, 0), (-1, 0), HexColor("#FFFFFF")),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor("#E5E7EB")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor("#FFFFFF"), HexColor("#F9FAFB")]),
        ]))
        story.append(decision_table)
        story.append(Spacer(1, 0.15*inch))

    # === FOOTER ===
    story.append(Spacer(1, 0.2*inch))

    footer_table = Table(
        [[Paragraph("CONTROLLED UNCLASSIFIED INFORMATION (CUI)", cui_style)]],
        colWidths=[7.5*inch]
    ).setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), HexColor("#DC2626")),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(footer_table)

    story.append(Spacer(1, 0.08*inch))

    disclaimer = (
        "This report was generated by the Xiphos Intelligence Engine. All findings should be independently verified. "
        "This document contains Controlled Unclassified Information (CUI) and must be handled according to applicable "
        "regulations and organizational policies."
    )
    story.append(Paragraph(disclaimer, muted_style))

    # Build PDF
    doc.build(story)

    # Return bytes
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()
