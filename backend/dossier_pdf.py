"""
Xiphos PDF Dossier Generator

Generates professional PDF compliance dossiers using reportlab.
Compatible with defense/procurement workflows and ready for archival.
"""

from io import BytesIO
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib import colors

import db
from event_extraction import compute_report_hash
from dossier import PROGRAM_LABELS
from dossier import _build_dossier_storyline
from dossier import _curate_dossier_findings
from dossier import _summarize_recent_change
from dossier import _get_dossier_analysis_data
from dossier import _is_clear_or_low_signal_event
from dossier import _is_connector_gap_finding
from dossier import _source_display_name
from dossier import _workflow_lane_context
from dossier import _workflow_lane_brief

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


def _recommendation_from_tier(tier: str) -> str:
    tier_upper = (tier or "").upper()
    if "APPROVED" in tier_upper or "QUALIFIED" in tier_upper:
        return "APPROVED"
    if "CONDITIONAL" in tier_upper or "ACCEPTABLE" in tier_upper:
        return "CONDITIONAL APPROVAL"
    if "REVIEW" in tier_upper or "ELEVATED" in tier_upper or "CAUTION" in tier_upper:
        return "ENHANCED DUE DILIGENCE"
    if "BLOCKED" in tier_upper or "HARD_STOP" in tier_upper or "DENIED" in tier_upper or "DISQUALIFIED" in tier_upper:
        return "REJECT"
    return "UNDER REVIEW"


def _format_timestamp_value(value, fmt: str = "%Y-%m-%d") -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return ""
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(text)
            except (TypeError, ValueError):
                return text

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime(fmt)


def _storyline_type_label(card_type: str) -> str:
    labels = {
        "trigger": "Trigger",
        "impact": "Impact",
        "reach": "Reach",
        "action": "Action",
        "offset": "Offset",
    }
    return labels.get(str(card_type or "").lower(), "Signal")


def _storyline_source_label(source_ref: dict) -> str:
    kind = str(source_ref.get("kind", "") or "").lower()
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
    return "Case evidence"


def _storyline_trace_label(target: dict | None) -> str:
    if not isinstance(target, dict):
        return "Case detail"
    kind = str(target.get("kind", "") or "").lower()
    if kind == "graph_focus":
        return "Connected network"
    if kind == "action_panel":
        return "Recommended actions"
    if kind == "deep_analysis":
        return "Model reasoning"
    if kind == "evidence_tab":
        tab = str(target.get("tab", "") or "").lower()
        tab_map = {
            "findings": "Evidence findings",
            "events": "Normalized events",
            "intel": "Intel summary",
            "model": "Model reasoning",
        }
        return tab_map.get(tab, "Evidence detail")
    return "Case detail"


def _append_storyline_section(story, storyline, styles_bundle) -> None:
    cards = storyline.get("cards") if isinstance(storyline, dict) else None
    if not isinstance(cards, list) or not cards:
        return

    heading_style = styles_bundle["heading"]
    normal_style = styles_bundle["normal"]
    muted_style = styles_bundle["muted"]

    label_style = ParagraphStyle(
        "StorylineLabel",
        parent=muted_style,
        fontSize=7,
        leading=9,
        textColor=HexColor("#6B7280"),
        fontName="Helvetica-Bold",
    )
    title_style = ParagraphStyle(
        "StorylineTitle",
        parent=normal_style,
        fontSize=10.5,
        leading=13,
        textColor=HexColor("#111827"),
        fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "StorylineBody",
        parent=normal_style,
        fontSize=8.5,
        leading=11.5,
        textColor=HexColor("#374151"),
    )
    meta_style = ParagraphStyle(
        "StorylineMeta",
        parent=muted_style,
        fontSize=7.5,
        leading=10,
        textColor=HexColor("#6B7280"),
    )
    intro_style = ParagraphStyle(
        "StorylineIntro",
        parent=normal_style,
        fontSize=8.5,
        leading=11.5,
        textColor=HexColor("#4B5563"),
    )

    story.append(Paragraph("RISK STORYLINE", heading_style))
    story.append(Paragraph(
        "Helios distills the case into the few evidence-backed signals a reviewer should understand before reading the full finding set.",
        intro_style,
    ))
    story.append(Spacer(1, 0.08 * inch))

    row_cards = []
    for card in cards[:5]:
        severity = str(card.get("severity", "info") or "info").lower()
        accent = HexColor("#10B981" if severity == "positive" else _severity_color(severity))
        confidence_pct = round(float(card.get("confidence") or 0.0) * 100)
        source_labels = [
            _storyline_source_label(ref)
            for ref in (card.get("source_refs") or [])
            if isinstance(ref, dict)
        ][:3]
        meta_bits = [f"{confidence_pct}% confidence", _storyline_trace_label(card.get("cta_target"))]
        if source_labels:
            meta_bits.append(", ".join(source_labels))

        card_table = Table(
            [
                [Paragraph(f"{int(card.get('rank') or 0) or '•'}  {_storyline_type_label(card.get('type', ''))}".upper(), label_style)],
                [Paragraph(str(card.get("title", "Storyline item")), title_style)],
                [Paragraph(str(card.get("body", "")), body_style)],
                [Paragraph(" | ".join(meta_bits), meta_style)],
            ],
            colWidths=[3.55 * inch],
        )
        card_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#D8E0EA")),
            ("LINEBEFORE", (0, 0), (0, -1), 4, accent),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        row_cards.append(card_table)
        if len(row_cards) == 2:
            row = Table([row_cards], colWidths=[3.65 * inch, 3.65 * inch])
            row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(row)
            story.append(Spacer(1, 0.08 * inch))
            row_cards = []

    if row_cards:
        if len(row_cards) == 1:
            row_cards.append(Spacer(1, 0.01 * inch))
        row = Table([row_cards], colWidths=[3.65 * inch, 3.65 * inch])
        row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(row)
        story.append(Spacer(1, 0.12 * inch))


def _append_foci_evidence_section(story, foci_summary, styles_bundle) -> None:
    if not isinstance(foci_summary, dict):
        return

    heading_style = styles_bundle["heading"]
    normal_style = styles_bundle["normal"]
    muted_style = styles_bundle["muted"]

    title_style = ParagraphStyle(
        "FociTitle",
        parent=normal_style,
        fontSize=10.5,
        leading=13,
        textColor=HexColor("#111827"),
        fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "FociBody",
        parent=normal_style,
        fontSize=8.5,
        leading=11.5,
        textColor=HexColor("#374151"),
    )
    meta_style = ParagraphStyle(
        "FociMeta",
        parent=muted_style,
        fontSize=7.5,
        leading=10,
        textColor=HexColor("#6B7280"),
    )

    meta_bits = []
    if foci_summary.get("foreign_country"):
        meta_bits.append(f"Country {foci_summary['foreign_country']}")
    if foci_summary.get("foreign_ownership_pct_display"):
        meta_bits.append(f"Ownership {foci_summary['foreign_ownership_pct_display']}")
    if foci_summary.get("mitigation_display") and str(foci_summary.get("mitigation_display")) != "Not stated":
        meta_bits.append(f"Mitigation {foci_summary['mitigation_display']}")
    if foci_summary.get("contains_governance_control_terms"):
        meta_bits.append("Governance-control terms detected")

    story.append(Paragraph("FOCI EVIDENCE SUMMARY", heading_style))
    card = Table(
        [
            [Paragraph(str(foci_summary.get("artifact_label") or "Customer FOCI evidence"), meta_style)],
            [Paragraph(f"Foreign counterparty: {str(foci_summary.get('foreign_owner') or 'Not stated')}", title_style)],
            [Paragraph(str(foci_summary.get("narrative") or ""), body_style)],
            [Paragraph(" | ".join(meta_bits) if meta_bits else "Customer-controlled ownership / control evidence", meta_style)],
        ],
        colWidths=[7.15 * inch],
    )
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#D8E0EA")),
        ("LINEBEFORE", (0, 0), (0, -1), 4, HexColor("#3B82F6")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(card)
    story.append(Spacer(1, 0.12 * inch))


def _append_cyber_evidence_section(story, cyber_summary, styles_bundle) -> None:
    if not isinstance(cyber_summary, dict):
        return

    heading_style = styles_bundle["heading"]
    normal_style = styles_bundle["normal"]
    muted_style = styles_bundle["muted"]

    title_style = ParagraphStyle(
        "CyberTitle",
        parent=normal_style,
        fontSize=10.5,
        leading=13,
        textColor=HexColor("#111827"),
        fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "CyberBody",
        parent=normal_style,
        fontSize=8.5,
        leading=11.5,
        textColor=HexColor("#374151"),
    )
    meta_style = ParagraphStyle(
        "CyberMeta",
        parent=muted_style,
        fontSize=7.5,
        leading=10,
        textColor=HexColor("#6B7280"),
    )

    current_level = int(cyber_summary.get("current_cmmc_level") or 0)
    poam_active = bool(cyber_summary.get("poam_active"))
    open_poam_items = int(cyber_summary.get("open_poam_items") or 0)
    critical_cves = int(cyber_summary.get("critical_cve_count") or 0)
    kev_count = int(cyber_summary.get("kev_flagged_cve_count") or 0)

    meta_bits = []
    if current_level > 0:
        meta_bits.append(f"CMMC Level {current_level}")
    if cyber_summary.get("assessment_status"):
        meta_bits.append(f"Status {str(cyber_summary['assessment_status'])}")
    if poam_active:
        meta_bits.append(
            f"POA&M active{f' ({open_poam_items} open)' if open_poam_items > 0 else ''}"
        )
    if critical_cves > 0:
        meta_bits.append(f"{critical_cves} critical CVE{'s' if critical_cves != 1 else ''}")
    if kev_count > 0:
        meta_bits.append(f"{kev_count} KEV-linked issue{'s' if kev_count != 1 else ''}")

    posture = "Customer cyber evidence"
    if current_level > 0 and current_level < 2:
        posture = "CMMC readiness gap"
    elif current_level >= 2 and not poam_active and critical_cves == 0 and kev_count == 0:
        posture = "Cyber readiness supported"
    elif poam_active or critical_cves > 0 or kev_count > 0:
        posture = "Remediation pressure present"

    body_bits = []
    if current_level > 0:
        body_bits.append(f"Customer SPRS evidence reports current CMMC Level {current_level}")
    if cyber_summary.get("assessment_date"):
        body_bits.append(f"assessment date {str(cyber_summary['assessment_date'])}")
    if poam_active:
        body_bits.append(
            f"active POA&M{' with ' + str(open_poam_items) + ' open item' + ('s' if open_poam_items != 1 else '') if open_poam_items > 0 else ''}"
        )
    if critical_cves > 0 or kev_count > 0:
        vuln_bits = []
        if critical_cves > 0:
            vuln_bits.append(f"{critical_cves} critical CVE{'s' if critical_cves != 1 else ''}")
        if kev_count > 0:
            vuln_bits.append(f"{kev_count} KEV-linked issue{'s' if kev_count != 1 else ''}")
        body_bits.append("NVD overlay shows " + " and ".join(vuln_bits))
    body_text = ". ".join(body_bits).strip()
    if body_text and not body_text.endswith("."):
        body_text += "."
    if not body_text:
        body_text = "Customer cyber-trust artifacts are attached for CMMC, POA&M, and product vulnerability context."

    story.append(Paragraph("CYBER EVIDENCE SUMMARY", heading_style))
    card = Table(
        [
            [Paragraph("Customer cyber evidence", meta_style)],
            [Paragraph("Supplier cyber-readiness context", title_style)],
            [Paragraph(body_text, body_style)],
            [Paragraph(" | ".join([posture] + meta_bits) if meta_bits else posture, meta_style)],
        ],
        colWidths=[7.15 * inch],
    )
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#D8E0EA")),
        ("LINEBEFORE", (0, 0), (0, -1), 4, HexColor("#0F766E")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(card)
    story.append(Spacer(1, 0.12 * inch))


def _append_export_evidence_section(story, export_summary, styles_bundle) -> None:
    if not isinstance(export_summary, dict):
        return

    heading_style = styles_bundle["heading"]
    normal_style = styles_bundle["normal"]
    muted_style = styles_bundle["muted"]

    title_style = ParagraphStyle(
        "ExportTitle",
        parent=normal_style,
        fontSize=10.5,
        leading=13,
        textColor=HexColor("#111827"),
        fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "ExportBody",
        parent=normal_style,
        fontSize=8.5,
        leading=11.5,
        textColor=HexColor("#374151"),
    )
    meta_style = ParagraphStyle(
        "ExportMeta",
        parent=muted_style,
        fontSize=7.5,
        leading=10,
        textColor=HexColor("#6B7280"),
    )

    meta_bits = []
    if export_summary.get("destination_country"):
        meta_bits.append(f"Destination {str(export_summary['destination_country'])}")
    if export_summary.get("classification_display"):
        meta_bits.append(f"Classification {str(export_summary['classification_display'])}")
    if export_summary.get("jurisdiction_guess"):
        meta_bits.append(f"Jurisdiction {str(export_summary['jurisdiction_guess']).upper()}")
    if export_summary.get("contains_foreign_person_terms"):
        meta_bits.append("Foreign-person access context")
    meta_bits.extend(str(token) for token in (export_summary.get("detected_license_tokens") or [])[:3])

    story.append(Paragraph("EXPORT EVIDENCE SUMMARY", heading_style))
    card = Table(
        [
            [Paragraph(str(export_summary.get("request_type") or "Export authorization request").replace("_", " ").title(), meta_style)],
            [Paragraph(f"Authorization posture: {str(export_summary.get('posture_label') or 'Export review')}", title_style)],
            [Paragraph(str(export_summary.get("narrative") or ""), body_style)],
            [Paragraph(" | ".join(meta_bits) if meta_bits else str(export_summary.get("recommended_next_step") or ""), meta_style)],
        ],
        colWidths=[7.15 * inch],
    )
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#D8E0EA")),
        ("LINEBEFORE", (0, 0), (0, -1), 4, HexColor("#7C3AED")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(card)
    story.append(Spacer(1, 0.12 * inch))


def _make_signal_bar(width_inches: float, fill_pct: int, color_hex: str) -> Table:
    fill_width = max(0.18, width_inches * max(0, min(fill_pct, 100)) / 100.0)
    bar = Table(
        [["", ""]],
        colWidths=[fill_width * inch, max((width_inches - fill_width), 0.18) * inch],
        rowHeights=[0.1 * inch],
    )
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), HexColor(color_hex)),
        ("BACKGROUND", (1, 0), (1, 0), HexColor("#D5DDE7")),
        ("LINEBEFORE", (0, 0), (-1, -1), 0, colors.white),
        ("LINEAFTER", (0, 0), (-1, -1), 0, colors.white),
        ("LINEABOVE", (0, 0), (-1, -1), 0, colors.white),
        ("LINEBELOW", (0, 0), (-1, -1), 0, colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return bar


def generate_pdf_dossier(vendor_id: str, user_id: str = "", hydrate_ai: bool = False) -> bytes:
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
    monitoring_history = db.get_monitoring_history(vendor_id, limit=10)
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

    analysis_data = _get_dossier_analysis_data(
        vendor_id,
        vendor,
        score,
        enrichment,
        user_id=user_id,
        hydrate_ai=hydrate_ai,
    )

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
        wordWrap='CJK',  # Force wrap on any character (prevents URL overflow)
    )

    muted_style = ParagraphStyle(
        'CustomMuted',
        parent=styles['Normal'],
        fontSize=8,
        textColor=HexColor("#6B7280"),
        spaceAfter=4,
        wordWrap='CJK',
    )

    # === HEADER: Xiphos Helios branding ===
    header_style = ParagraphStyle(
        'Header', parent=styles['Title'], fontSize=9, textColor=HexColor("#C4A052"),
        fontName='Helvetica-Bold', spaceAfter=0, letterSpacing=3,
    )
    header_main = ParagraphStyle(
        'HeaderMain', parent=styles['Title'], fontSize=24, textColor=HexColor("#0A1628"),
        fontName='Helvetica', spaceAfter=2, letterSpacing=4,
    )

    story.append(Paragraph("HELIOS", header_style))
    story.append(Paragraph("Vendor Compliance Dossier", header_main))
    story.append(Paragraph(
        '<font color="#C4A052">____________________</font>',
        ParagraphStyle('Rule', parent=styles['Normal'], spaceAfter=4)
    ))
    story.append(Paragraph("Vendor Compliance Dossier", muted_style))

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

    if score:
        cal = score.get("calibrated", {})
        tier_key = cal.get("calibrated_tier", "unknown")
        recommendation = _recommendation_from_tier(tier_key)
        recommendation_color = _tier_color(tier_key)
        probability = round(float(cal.get("calibrated_probability", 0.0)) * 100)
        lo = round(float(cal.get("interval", {}).get("lower", 0.0)) * 100)
        hi = round(float(cal.get("interval", {}).get("upper", 0.0)) * 100)
        connectors_run = enrichment.get("summary", {}).get("connectors_run", 0) if enrichment else 0
        connectors_with_data = enrichment.get("summary", {}).get("connectors_with_data", 0) if enrichment else 0
        program_label = PROGRAM_LABELS.get(vendor.get("program", ""), vendor.get("program", "") or "Program not set")
        ci_width = float(cal.get("interval", {}).get("upper", 0.0)) - float(cal.get("interval", {}).get("lower", 0.0))
        confidence_label = "High" if ci_width < 0.10 else "Moderate" if ci_width < 0.25 else "Low"
        confidence_pct = 92 if confidence_label == "High" else 74 if confidence_label == "Moderate" else 48
        coverage_pct = round((connectors_with_data / connectors_run) * 100) if connectors_run else 0
        recent_change = _summarize_recent_change(monitoring_history)
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

        hero_title = ParagraphStyle(
            "HeroTitle",
            parent=styles["Title"],
            fontSize=19,
            leading=24,
            textColor=HexColor("#FFFFFF"),
            fontName="Helvetica-Bold",
        )
        hero_body = ParagraphStyle(
            "HeroBody",
            parent=normal_style,
            fontSize=9.5,
            leading=14,
            textColor=HexColor("#D6DEE8"),
        )
        hero_chip = ParagraphStyle(
            "HeroChip",
            parent=normal_style,
            fontSize=9,
            leading=11,
            textColor=HexColor("#FFFFFF"),
            fontName="Helvetica-Bold",
        )
        metric_label_style = ParagraphStyle(
            "MetricLabel",
            parent=muted_style,
            fontSize=7.5,
            textColor=HexColor("#AAB4C3"),
            leading=10,
        )
        metric_value_style = ParagraphStyle(
            "MetricValue",
            parent=normal_style,
            fontSize=12,
            textColor=HexColor("#FFFFFF"),
            fontName="Helvetica-Bold",
            leading=15,
        )

        hero_summary = Table(
            [[
                Paragraph(
                    f"<font size='8' color='#D4BF89'>{lane['title'].upper()}</font><br/>{vendor['name']}<br/><font size='10' color='#D6DEE8'>"
                    f"Helios recommends {recommendation.lower()} based on a {probability}% posterior risk estimate "
                    f"and {confidence_label.lower()} assessment confidence in this {lane['summary_name']}.</font>",
                    hero_title,
                ),
                Table(
                    [[Paragraph(recommendation, hero_chip)]],
                    colWidths=[1.6 * inch],
                ),
            ]],
            colWidths=[5.6 * inch, 1.55 * inch],
        )
        hero_summary.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#0A1628")),
            ("LEFTPADDING", (0, 0), (-1, -1), 16),
            ("RIGHTPADDING", (0, 0), (-1, -1), 16),
            ("TOPPADDING", (0, 0), (-1, -1), 16),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ]))
        hero_summary._cellvalues[0][1].setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor(recommendation_color)),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(hero_summary)

        lane_section_label = ParagraphStyle(
            "LaneSectionLabel",
            parent=muted_style,
            fontSize=7.2,
            textColor=HexColor("#AAB4C3"),
            leading=9,
            fontName="Helvetica-Bold",
        )
        lane_section_value = ParagraphStyle(
            "LaneSectionValue",
            parent=normal_style,
            fontSize=8.7,
            textColor=HexColor("#FFFFFF"),
            leading=12,
        )
        lane_section_value_strong = ParagraphStyle(
            "LaneSectionValueStrong",
            parent=lane_section_value,
            fontName="Helvetica-Bold",
        )
        lane_stat_label = ParagraphStyle(
            "LaneStatLabel",
            parent=muted_style,
            fontSize=6.8,
            textColor=HexColor("#AAB4C3"),
            leading=8,
            fontName="Helvetica-Bold",
        )
        lane_stat_value = ParagraphStyle(
            "LaneStatValue",
            parent=normal_style,
            fontSize=8.4,
            textColor=HexColor("#FFFFFF"),
            leading=10.5,
            fontName="Helvetica-Bold",
        )

        lane_stats_table = Table(
            [[
                Table([
                    [Paragraph(stat["label"].upper(), lane_stat_label)],
                    [Paragraph(str(stat["value"]), lane_stat_value)],
                ], colWidths=[1.55 * inch])
                for stat in lane_brief["stats"][:2]
            ], [
                Table([
                    [Paragraph(stat["label"].upper(), lane_stat_label)],
                    [Paragraph(str(stat["value"]), lane_stat_value)],
                ], colWidths=[1.55 * inch])
                for stat in lane_brief["stats"][2:4]
            ]],
            colWidths=[1.62 * inch, 1.62 * inch],
        )
        lane_stats_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#0F1E2F")),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#1F334A")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, HexColor("#1F334A")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))

        lane_brief_table = Table([[
            Table([
                [Paragraph(lane_brief["eyebrow"].upper(), lane_section_label)],
                [Paragraph(lane_brief["title"], metric_value_style)],
                [Paragraph("CORE QUESTION", lane_section_label)],
                [Paragraph(lane_brief["question"], lane_section_value)],
                [Paragraph("DECISION OUTPUTS", lane_section_label)],
                [Paragraph(lane_brief["outputs"], lane_section_value_strong)],
                [Paragraph("EVIDENCE BASIS", lane_section_label)],
                [Paragraph(lane_brief["evidence"], lane_section_value)],
            ], colWidths=[3.75 * inch]),
            Table([
                [Paragraph("LANE READOUT", lane_section_label)],
                [lane_stats_table],
                [Paragraph("IMMEDIATE NEXT ACTION", lane_section_label)],
                [Paragraph(lane_brief["next_action"], lane_section_value)],
            ], colWidths=[3.2 * inch]),
        ]], colWidths=[3.85 * inch, 3.25 * inch])
        lane_brief_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#0F1E2F")),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#1F334A")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, HexColor("#1F334A")),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(Spacer(1, 0.09 * inch))
        story.append(lane_brief_table)

        if control_summary:
            control_label_style = ParagraphStyle(
                "ControlLabel",
                parent=muted_style,
                fontSize=6.8,
                textColor=HexColor("#AAB4C3"),
                leading=8,
                fontName="Helvetica-Bold",
            )
            control_value_style = ParagraphStyle(
                "ControlValue",
                parent=normal_style,
                fontSize=9,
                textColor=HexColor("#FFFFFF"),
                leading=11.5,
                fontName="Helvetica-Bold",
            )
            control_copy_style = ParagraphStyle(
                "ControlCopy",
                parent=normal_style,
                fontSize=8,
                textColor=HexColor("#D6DEE8"),
                leading=10.5,
            )
            missing_items = (control_summary.get("missing_inputs") or [])[:3]
            missing_text = "<br/>".join(f"• {item}" for item in missing_items) if missing_items else "• No major intake gap is currently flagged."
            control_table = Table([[
                Table([
                    [Paragraph("CONTROL POSTURE", control_label_style)],
                    [Paragraph(str(control_summary.get("label") or "Not assessed"), control_value_style)],
                    [Paragraph(str(control_summary.get("review_basis") or ""), control_copy_style)],
                ], colWidths=[2.3 * inch]),
                Table([
                    [Paragraph("ACTION OWNER", control_label_style)],
                    [Paragraph(str(control_summary.get("action_owner") or "Analyst review"), control_value_style)],
                    [Paragraph(str(control_summary.get("decision_boundary") or ""), control_copy_style)],
                ], colWidths=[2.3 * inch]),
                Table([
                    [Paragraph("MISSING INPUTS", control_label_style)],
                    [Paragraph(missing_text, control_copy_style)],
                ], colWidths=[2.3 * inch]),
            ]], colWidths=[2.4 * inch, 2.4 * inch, 2.4 * inch])
            control_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), HexColor("#0F1E2F")),
                ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#1F334A")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, HexColor("#1F334A")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(Spacer(1, 0.09 * inch))
            story.append(control_table)

        metric_table = Table([[
            Table([
                [Paragraph("Risk posture", metric_label_style)],
                [Paragraph(f"{probability}%", metric_value_style)],
                [Paragraph(f"Tier {str(tier_key).replace('_', ' ').upper()}", hero_body)],
            ], colWidths=[1.77 * inch]),
            Table([
                [Paragraph("Assessment confidence", metric_label_style)],
                [Paragraph(confidence_label, metric_value_style)],
                [Paragraph(f"CI {lo}% to {hi}%", hero_body)],
            ], colWidths=[1.77 * inch]),
            Table([
                [Paragraph("Intel coverage", metric_label_style)],
                [Paragraph(f"{connectors_with_data}/{connectors_run}", metric_value_style)],
                [Paragraph("sources with data", hero_body)],
            ], colWidths=[1.77 * inch]),
            Table([
                [Paragraph("Operating context", metric_label_style)],
                [Paragraph(vendor.get("country", "N/A") or "N/A", metric_value_style)],
                [Paragraph(program_label, hero_body)],
            ], colWidths=[1.77 * inch]),
        ]], colWidths=[1.83 * inch, 1.83 * inch, 1.83 * inch, 1.83 * inch])
        metric_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#0F1E2F")),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#1F334A")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, HexColor("#1F334A")),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        for card in metric_table._cellvalues[0]:
            card.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), HexColor("#0F1E2F")),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
        story.append(metric_table)
        signal_label_style = ParagraphStyle(
            "SignalLabel",
            parent=muted_style,
            fontSize=7,
            textColor=HexColor("#6B7280"),
            leading=9,
            fontName="Helvetica-Bold",
        )
        signal_value_style = ParagraphStyle(
            "SignalValue",
            parent=normal_style,
            fontSize=10,
            textColor=HexColor("#111827"),
            leading=12,
            fontName="Helvetica-Bold",
        )
        signal_cards = []
        for label, value, note, pct, color_hex in [
            ("Risk signal", f"{probability}%", f"Tier {str(tier_key).replace('_', ' ').upper()}", probability, recommendation_color),
            ("Assessment confidence", confidence_label, f"CI {lo}% to {hi}%", confidence_pct, "#C4A052"),
            ("Coverage depth", f"{coverage_pct}%", f"{connectors_with_data}/{connectors_run} sources with data", coverage_pct, "#3B82F6"),
            ("Recent change", recent_change["label"], recent_change["detail"], recent_change["pct"], recent_change["color"]),
        ]:
            card = Table(
                [
                    [Paragraph(label.upper(), signal_label_style)],
                    [Paragraph(value, signal_value_style)],
                    [Paragraph(str(note), muted_style)],
                    [_make_signal_bar(2.15, pct, color_hex)],
                ],
                colWidths=[2.2 * inch],
            )
            card.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#D8E0EA")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            signal_cards.append(card)
        signal_table = Table([signal_cards], colWidths=[1.75 * inch, 1.75 * inch, 1.75 * inch, 1.75 * inch])
        signal_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(Spacer(1, 0.09 * inch))
        story.append(signal_table)
        story.append(Spacer(1, 0.18 * inch))

    _append_storyline_section(
        story,
        storyline,
        {"heading": heading_style, "normal": normal_style, "muted": muted_style},
    )
    _append_foci_evidence_section(
        story,
        foci_summary,
        {"heading": heading_style, "normal": normal_style, "muted": muted_style},
    )
    _append_cyber_evidence_section(
        story,
        cyber_summary,
        {"heading": heading_style, "normal": normal_style, "muted": muted_style},
    )
    _append_export_evidence_section(
        story,
        export_summary,
        {"heading": heading_style, "normal": normal_style, "muted": muted_style},
    )

    # === ENTITY SUMMARY ===
    story.append(Paragraph("ENTITY SUMMARY", heading_style))

    summary_data = [
        ["Vendor Name", vendor["name"]],
        ["Country", vendor["country"]],
        ["Profile", vendor.get("profile", "defense_acquisition")],
        ["Program", vendor.get("program", "standard_industrial")],
        ["Case Created", _format_timestamp_value(vendor.get("created_at"), "%Y-%m-%d %H:%M:%S")],
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
        recommendation = _recommendation_from_tier(cal.get("calibrated_tier", "unknown"))
        recommendation_color = _tier_color(cal.get("calibrated_tier", "unknown"))
        connectors_run = enrichment.get("summary", {}).get("connectors_run", 0) if enrichment else 0
        connectors_with_data = enrichment.get("summary", {}).get("connectors_with_data", 0) if enrichment else 0

        # Tier badge
        tier_color = _tier_color(cal.get("calibrated_tier", "unknown"))

        risk_data = [
            ["Risk Tier", Paragraph(f"<font color='{tier_color}'><b>{tier}</b></font>", normal_style)],
            ["Posterior Probability", f"{round(posterior * 100)}%"],
            ["Composite Score", f"{composite}/100"],
            ["Confidence Interval", f"{round(lo * 100)}% - {round(hi * 100)}%"],
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

        summary_banner = Table(
            [[
                Paragraph(
                    f"<font color='#FFFFFF'><b>{recommendation}</b></font><br/>"
                    f"<font color='#D6DEE8'>Risk {round(posterior * 100)}% | "
                    f"CI {round(lo * 100)}%-{round(hi * 100)}% | "
                    f"Coverage {connectors_with_data}/{connectors_run} connectors</font>",
                    ParagraphStyle(
                        "RecommendationBanner",
                        parent=normal_style,
                        fontSize=10,
                        textColor=HexColor("#FFFFFF"),
                        leading=14,
                    ),
                )
            ]],
            colWidths=[7.5 * inch],
        )
        summary_banner.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), HexColor(recommendation_color)),
            ('LEFTPADDING', (0, 0), (-1, -1), 14),
            ('RIGHTPADDING', (0, 0), (-1, -1), 14),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))
        story.append(Spacer(1, 0.08*inch))
        story.append(summary_banner)

    story.append(Spacer(1, 0.15*inch))

    # === CONTRIBUTING FACTORS ===
    if score and cal.get("contributions"):
        story.append(Paragraph("CONTRIBUTING RISK FACTORS", heading_style))

        contrib_data = [
            ["Factor", "Raw Score", "Contribution", "Weight", "Description"],
        ]

        for ct in sorted(cal.get("contributions", []), key=lambda x: abs(x.get("signed_contribution", 0)), reverse=True):
            raw = f"{ct.get('raw_score', 0):.2f}"
            contrib = f"{ct.get('signed_contribution', 0):+.3f} pp"
            weight = f"{ct.get('weight', 0):.1f}"
            desc = Paragraph(ct.get('description', ''), normal_style)

            contrib_data.append([
                ct.get("factor", "Unknown"),
                raw,
                contrib,
                weight,
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

    # === AI ANALYSIS ===
    if analysis_data and isinstance(analysis_data.get("analysis"), dict):
        analysis = analysis_data.get("analysis") or {}
        verdict = str(analysis.get("verdict", "UNDER REVIEW")).replace("_", " ").title()
        concerns = analysis.get("critical_concerns") or []
        offsets = analysis.get("mitigating_factors") or []
        actions = analysis.get("recommended_actions") or []

        story.append(Paragraph("AI NARRATIVE BRIEF", heading_style))
        advisory_style = ParagraphStyle(
            'Advisory', parent=muted_style, fontSize=7.5, textColor=HexColor("#C4A052"),
            borderColor=HexColor("#C4A052"), borderWidth=0, borderPadding=4,
        )
        story.append(Paragraph(
            "<b>ADVISORY LAYER</b> - This AI brief complements the deterministic engine and evidence trail. "
            "It does not override tier classification, hard-stop decisions, or regulatory findings.",
            advisory_style,
        ))
        story.append(Spacer(1, 0.05*inch))

        ai_summary_table = Table(
            [[
                Paragraph(
                    f"<b>Executive judgment</b><br/>{analysis.get('executive_summary', '') or 'No AI executive summary available.'}",
                    normal_style,
                ),
                Paragraph(
                    f"<b>Verdict</b><br/>{verdict}<br/><font color='#6B7280'>"
                    f"Provider {analysis_data.get('provider', 'unknown')} / {analysis_data.get('model', 'unknown')}</font>",
                    normal_style,
                ),
            ]],
            colWidths=[5.4 * inch, 2.0 * inch],
        )
        ai_summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#D6DEE8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(ai_summary_table)
        story.append(Spacer(1, 0.08 * inch))

        if analysis.get("risk_narrative"):
            story.append(Paragraph("<b>Why this matters</b>", subheading_style))
            story.append(Paragraph(analysis.get("risk_narrative", ""), normal_style))

        def _append_brief_list(title: str, items: list[str], accent: str) -> None:
            story.append(Paragraph(title, ParagraphStyle(
                f"{title}-style",
                parent=subheading_style,
                textColor=HexColor(accent),
            )))
            if items:
                for item in items[:5]:
                    story.append(Paragraph(f"• {item}", normal_style))
            else:
                story.append(Paragraph("No additional items surfaced in this category.", muted_style))
            story.append(Spacer(1, 0.04 * inch))

        _append_brief_list("Critical concerns", concerns, "#DC2626")
        _append_brief_list("Mitigating factors", offsets, "#198754")
        _append_brief_list("Recommended actions", actions, "#0D6EFD")

        if analysis.get("regulatory_exposure"):
            story.append(Paragraph("Regulatory and diligence exposure", subheading_style))
            story.append(Paragraph(analysis.get("regulatory_exposure", ""), normal_style))
        if analysis.get("confidence_assessment"):
            story.append(Paragraph(
                f"<b>Confidence:</b> {analysis.get('confidence_assessment', '')}",
                muted_style,
            ))
        story.append(Spacer(1, 0.1*inch))

    # === INTEL SUMMARY ===
    summary_payload = (intel_summary or {}).get("summary") or {}
    summary_items = summary_payload.get("items") or []
    if summary_items:
        story.append(Paragraph("INTEL SUMMARY", heading_style))
        for item in summary_items[:5]:
            story.append(Paragraph(f"<b>{item.get('title', 'Intel Summary Item')}</b>", subheading_style))
            meta = (
                f"Status: {str(item.get('status', 'active')).upper()} | "
                f"Severity: {str(item.get('severity', 'medium')).upper()} | "
                f"Confidence: {round(float(item.get('confidence', 0.0)) * 100)}%"
            )
            story.append(Paragraph(meta, muted_style))
            story.append(Paragraph(item.get('assessment', ''), normal_style))
            citations = ", ".join(item.get('source_finding_ids') or []) or "No citations"
            story.append(Paragraph(f"<i>Citations:</i> {citations}", muted_style))
            if item.get('recommended_action'):
                story.append(Paragraph(f"<b>Recommended action:</b> {item.get('recommended_action')}", normal_style))
            story.append(Spacer(1, 0.08*inch))
        story.append(Spacer(1, 0.08*inch))

    # === NORMALIZED EVENTS ===
    material_events = [event for event in case_events if not _is_clear_or_low_signal_event(event)]
    if material_events:
        story.append(Paragraph("NORMALIZED EVENTS", heading_style))
        event_rows = [["Event", "Status", "Jurisdiction", "Confidence", "Assessment"]]
        for event in material_events[:12]:
            event_rows.append([
                str(event.get('event_type', '')).replace('_', ' ').title(),
                str(event.get('status', 'active')).upper(),
                event.get('jurisdiction', ''),
                f"{round(float(event.get('confidence', 0.0)) * 100)}%",
                (event.get('assessment', '') or '')[:90],
            ])
        event_table = Table(event_rows, colWidths=[1.3*inch, 1.0*inch, 1.0*inch, 0.8*inch, 3.4*inch])
        event_table.setStyle(TableStyle([
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
        story.append(event_table)
        story.append(Spacer(1, 0.12*inch))

    # === OSINT ENRICHMENT ===
    if enrichment:
        story.append(Paragraph("OSINT ENRICHMENT SUMMARY", heading_style))

        summary = enrichment.get("summary", {})
        connector_status = enrichment.get("connector_status", {}) or {}
        # Reconcile overall_risk with scored tier (same logic as HTML dossier)
        osint_label = enrichment.get('overall_risk', 'UNKNOWN')
        if score:
            scored_tier = (score.get("calibrated", {}).get("calibrated_tier", "") or "").upper()
            if "APPROVED" in scored_tier:
                osint_label = "LOW"
            elif "REVIEW" in scored_tier or "ELEVATED" in scored_tier or "CONDITIONAL" in scored_tier:
                osint_label = "MEDIUM"
            elif "BLOCKED" in scored_tier or "HARD_STOP" in scored_tier or "DENIED" in scored_tier:
                osint_label = "CRITICAL"

        story.append(Paragraph(
            f"<b>Overall Risk:</b> {osint_label} | "
            f"<b>Connectors:</b> {summary.get('connectors_run', 0)} ran "
            f"({summary.get('connectors_with_data', 0)} with data) | "
            f"<b>Findings:</b> {summary.get('findings_total', 0)} total",
            normal_style
        ))

        story.append(Spacer(1, 0.08*inch))

        # Key evidence snapshot -- filter out connector gaps and low-signal clears
        findings = _curate_dossier_findings(enrichment, limit=10)
        if findings:
            story.append(Paragraph("KEY EVIDENCE SNAPSHOT", subheading_style))

            cell_style = ParagraphStyle('CellWrap', parent=normal_style, fontSize=7, wordWrap='CJK')
            findings_data = [
                ["Severity", "Source", "Title", "Detail"],
            ]

            for finding in findings:
                findings_data.append([
                    finding.get("severity", "LOW").upper(),
                    Paragraph(_source_display_name(finding.get("source", "")), cell_style),
                    Paragraph(finding.get("title", ""), cell_style),
                    Paragraph(finding.get("detail", ""), cell_style),
                ])

            findings_table = Table(findings_data, colWidths=[0.7*inch, 1.3*inch, 2.2*inch, 3.3*inch])
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

        connector_gaps = [
            finding for finding in enrichment.get("findings", [])
            if _is_connector_gap_finding(finding)
        ]
        if connector_gaps:
            story.append(Spacer(1, 0.08*inch))
            story.append(Paragraph(
                f"<b>Connector gaps:</b> {len(connector_gaps)} configured-source checks were unavailable at generation time.",
                muted_style,
            ))

        successful_sources = []
        failed_sources = []
        for name, status in sorted(connector_status.items()):
            display = _source_display_name(name)
            if status.get("error"):
                failed_sources.append(display)
            else:
                successful_sources.append({
                    "name": display,
                    "findings": status.get("findings_count", 0),
                    "elapsed_ms": status.get("elapsed_ms", 0),
                })

        if connector_status:
            story.append(Spacer(1, 0.1*inch))
            story.append(Paragraph("COVERAGE & FRESHNESS", subheading_style))
            coverage_cards = Table([[
                Paragraph(
                    f"<font color='#9FB0C5'>Source coverage</font><br/><font color='#FFFFFF' size='13'><b>{len(successful_sources)}/{len(connector_status)}</b></font><br/><font color='#D6DEE8'>Sources responded successfully</font>",
                    ParagraphStyle("CoverageCardText", parent=normal_style, fontSize=8.5, leading=11, textColor=HexColor("#FFFFFF")),
                ),
                Paragraph(
                    f"<font color='#9FB0C5'>Sources with signal</font><br/><font color='#FFFFFF' size='13'><b>{sum(1 for s in successful_sources if s['findings'] > 0)}</b></font><br/><font color='#D6DEE8'>Returned material or identity findings</font>",
                    ParagraphStyle("CoverageCardText2", parent=normal_style, fontSize=8.5, leading=11, textColor=HexColor("#FFFFFF")),
                ),
                Paragraph(
                    f"<font color='#9FB0C5'>Freshness</font><br/><font color='#FFFFFF' size='13'><b>{str(enrichment.get('enriched_at', '') or '')[:19] or 'N/A'}</b></font><br/><font color='#D6DEE8'>Completed in {round(float(enrichment.get('total_elapsed_ms', 0) or 0) / 1000, 1)}s</font>",
                    ParagraphStyle("CoverageCardText3", parent=normal_style, fontSize=8.5, leading=11, textColor=HexColor("#FFFFFF")),
                ),
            ]], colWidths=[2.45 * inch, 2.45 * inch, 2.45 * inch])
            coverage_cards.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), HexColor("#102033")),
                ('BOX', (0, 0), (-1, -1), 0.5, HexColor("#1F334A")),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, HexColor("#1F334A")),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ]))
            story.append(coverage_cards)

            if successful_sources:
                strongest = sorted(successful_sources, key=lambda item: (-item["findings"], item["name"]))[:6]
                strongest_line = ", ".join(
                    f"{item['name']} ({item['findings']})" for item in strongest if item["findings"] > 0
                )
                if strongest_line:
                    story.append(Spacer(1, 0.06*inch))
                    story.append(Paragraph(
                        f"<b>Strongest source returns:</b> {strongest_line}",
                        muted_style,
                    ))

            if failed_sources:
                story.append(Spacer(1, 0.04*inch))
                story.append(Paragraph(
                    f"<b>Unavailable sources:</b> {', '.join(failed_sources[:6])}",
                    muted_style,
                ))

        story.append(Spacer(1, 0.15*inch))

    # === DECISION HISTORY ===
    if decisions:
        story.append(Paragraph("DECISION HISTORY", heading_style))

        decision_data = [
            ["Date", "Decision", "Decided By", "Reason"],
        ]

        for decision in decisions[:10]:  # Last 10 decisions
            decision_data.append([
                _format_timestamp_value(decision.get("created_at")),
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
