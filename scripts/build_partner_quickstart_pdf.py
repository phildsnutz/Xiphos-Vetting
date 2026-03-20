#!/usr/bin/env python3
"""
Generate the partner quick-start PDF from a text source embedded in this script.

This keeps the public-facing guide editable even though the repo did not contain
an original source document for the previous PDF.
"""

from __future__ import annotations

import os
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer


OUTPUT = Path("docs/manuals/Xiphos_Helios_Partner_QuickStart.pdf")
PARTNER_URL = os.environ.get("XIPHOS_PARTNER_URL", "https://your-helios-url.example.com").strip()
SUPPORT_EMAIL = os.environ.get("XIPHOS_SUPPORT_EMAIL", "support@yourorg.com").strip()


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="GuideTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#102B46"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideSubtitle",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=14,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#4B647A"),
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="StepHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#102B46"),
            spaceBefore=10,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyTight",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=14,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BulletBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=13,
            leftIndent=12,
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="FooterNote",
            parent=styles["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#4B647A"),
            spaceBefore=12,
        )
    )
    return styles


def bullet_list(styles, items):
    return ListFlowable(
        [ListItem(Paragraph(item, styles["BulletBody"])) for item in items],
        bulletType="bullet",
        start="circle",
        leftIndent=18,
    )


def build_story():
    styles = build_styles()
    story = [
        Spacer(1, 0.35 * inch),
        Paragraph("Xiphos Helios Quick-Start Guide", styles["GuideTitle"]),
        Paragraph("Partner Quick-Start Guide", styles["GuideSubtitle"]),
        Paragraph(
            "Welcome to Helios. This guide walks you through your first vendor assessment in under five minutes.",
            styles["BodyTight"],
        ),
        Paragraph("Step 1: Log In", styles["StepHeading"]),
        Paragraph(
            f"Go to {PARTNER_URL} and enter the credentials provided to you. On your first login, you will be asked to set a new password. Choose something strong.",
            styles["BodyTight"],
        ),
        Paragraph("Step 2: Choose a Search Mode", styles["StepHeading"]),
        Paragraph(
            "The Helios landing page has two modes:",
            styles["BodyTight"],
        ),
        bullet_list(
            styles,
            [
                "Entity Search: type a company name to assess a single vendor.",
                "Contract Vehicle: search a contract vehicle or award family such as OASIS, CIO-SP3, or SEWP to find prime and subcontractor matches from public award data.",
            ],
        ),
        Spacer(1, 0.06 * inch),
        Paragraph('Try it now: type "Lockheed Martin" and press Enter.', styles["BodyTight"]),
        Paragraph("Step 3: Entity Resolution", styles["StepHeading"]),
        Paragraph(
            "Helios searches authoritative registries and returns candidate entities with identifiers such as UEI, CAGE, LEI, CIK, and ticker where available. Select the correct match before continuing.",
            styles["BodyTight"],
        ),
        Paragraph("Step 4: Confirm and Assess", styles["StepHeading"]),
        Paragraph(
            "Review the entity details, country, ownership context, and contract type. Then click Proceed with Assessment. Helios runs the regulatory and enrichment workflow for that case in about 30 to 60 seconds.",
            styles["BodyTight"],
        ),
        PageBreak(),
        Paragraph("Step 5: Read Your Results", styles["StepHeading"]),
        Paragraph(
            "The case detail shows the risk score, tier, factor contributions, and supporting findings. Lower risk percentages are better. Each factor explains what pushed the score up or down.",
            styles["BodyTight"],
        ),
        bullet_list(
            styles,
            [
                "Tier 4 Approved/Clear: low risk and standard processing.",
                "Tier 3 Conditional: moderate risk and proceed with conditions.",
                "Tier 2 Elevated: significant risk and senior review required.",
                "Tier 1 Disqualified: hard stop, cannot proceed.",
            ],
        ),
        Spacer(1, 0.08 * inch),
        Paragraph("Step 6: Generate a Dossier", styles["StepHeading"]),
        Paragraph(
            "Click Dossier to generate an audit-ready report you can download and share.",
            styles["BodyTight"],
        ),
        Paragraph("Contract Vehicle Workflow Tips", styles["StepHeading"]),
        bullet_list(
            styles,
            [
                "Use Contract Vehicle search to map awardee and subcontractor relationships around a vehicle or award family.",
                "Show Supply Chain Map visualizes prime-to-sub relationships for the returned matches.",
                "Create Draft Cases on vehicle results creates scored draft cases for each matched vendor. Run full enrichment per case when deeper review is warranted.",
                "Factor descriptions explain exactly what each score component measures.",
            ],
        ),
        Paragraph(f"Questions? Contact {SUPPORT_EMAIL}.", styles["FooterNote"]),
    ]
    return story


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title="Xiphos Helios Quick-Start Guide",
        author="Codex",
        subject="Partner Quick-Start Guide",
    )
    doc.build(build_story())
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
