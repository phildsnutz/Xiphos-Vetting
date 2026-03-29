#!/usr/bin/env python3
"""
Build a cleaner customer-facing Helios release-matrix PDF.
"""

from __future__ import annotations

from collections import defaultdict
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from build_release_matrix_pdf import OUTPUT_DIR, REPORT_DIR, build_rows, fixture_count


OUTPUT_PDF = OUTPUT_DIR / "HELIOS_RELEASE_MATRIX_CUSTOMER_2026-03-28.pdf"
OUTPUT_MD = REPORT_DIR / "HELIOS_RELEASE_MATRIX_CUSTOMER_2026-03-28.md"


def status_label(status: str) -> str:
    normalized = status.upper()
    if normalized == "GO":
        return "Release-ready"
    if normalized in {"REVALIDATING", "RETESTING", "IN_PROGRESS", "CAUTION"}:
        return "Final live retest"
    if normalized == "NO_GO":
        return "Hold"
    return "In review"


def status_color(status: str):
    normalized = status.upper()
    if normalized == "GO":
        return colors.HexColor("#0F8A5F")
    if normalized in {"REVALIDATING", "RETESTING", "IN_PROGRESS", "CAUTION"}:
        return colors.HexColor("#B7791F")
    if normalized == "NO_GO":
        return colors.HexColor("#C53030")
    return colors.HexColor("#475569")


def pillar_summary(rows):
    by_pillar = defaultdict(list)
    for row in rows:
        by_pillar[row.pillar].append(row)
    return by_pillar


DISPLAY_NAME = {
    "counterparty_identity_foundation": "Identity foundation",
    "counterparty_dossier_quality": "Dossier quality",
    "counterparty_control_paths": "Control paths",
    "export_ambiguous_end_use": "Ambiguous end use",
    "export_transshipment_diversion": "Transshipment and diversion",
    "export_defense_services_foreign_person": "Defense services and foreign person",
    "supply_chain_assurance_artifact_quality": "Artifact quality",
    "supply_chain_assurance_dependency_concentration": "Dependency concentration",
    "supply_chain_assurance_procurement_readiness": "Procurement readiness",
}


def build_markdown(rows) -> str:
    total_cases = sum(fixture_count(row.fixture) for row in rows)
    by_pillar = pillar_summary(rows)
    lines = [
        "# Helios Release Matrix",
        "",
        "- Date: 2026-03-28",
        "- Fixed packs: 9",
        f"- Fixed scenarios and companies: {total_cases}",
        "",
        "| Pillar | Packs | Fixed coverage | Current state |",
        "| --- | ---: | --- | --- |",
    ]
    for pillar, entries in by_pillar.items():
        state = status_label("GO" if all(row.status == "GO" for row in entries) else entries[0].status)
        lines.append(
            f"| {pillar} | {len(entries)} | {sum(fixture_count(row.fixture) for row in entries)} cases | {state} |"
        )
    lines.extend(
        [
            "",
            "## Fixed coverage",
            "",
        ]
    )
    for row in rows:
        lines.append(f"- {row.pillar}: {row.name} ({fixture_count(row.fixture)} cases) - {row.focus}")
    return "\n".join(lines) + "\n"


def build_pdf(rows) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=19,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=7.2,
        leading=8.2,
        textColor=colors.HexColor("#334155"),
    )
    small = ParagraphStyle(
        "Small",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=6.0,
        leading=6.8,
        textColor=colors.HexColor("#475569"),
    )

    total_cases = sum(fixture_count(row.fixture) for row in rows)
    by_pillar = pillar_summary(rows)

    story = []
    story.append(Paragraph("Helios Release Assurance Matrix", title))
    story.append(
        Paragraph(
            "Helios now uses fixed release packs across Counterparty, Export, and Supply Chain Assurance. This replaces ad hoc spot-checking with replayable customer-path validation.",
            body,
        )
    )
    story.append(Spacer(1, 0.04 * inch))
    story.append(
        Paragraph(
            f"Snapshot: 3 pillars | 9 fixed packs | {total_cases} fixed scenarios and companies | Export and Supply Chain Assurance release-ready | Counterparty in final live retest after systemic hardening.",
            body,
        )
    )
    story.append(Spacer(1, 0.06 * inch))

    summary_data = [["Pillar", "Packs", "Coverage", "Current state", "What it proves"]]
    proof_text = {
        "Counterparty": "Identity quality, dossier quality, control-path trust before analyst review.",
        "Export": "Hybrid rules plus AI challenge across ambiguous use, diversion, and defense-services access.",
        "Supply Chain Assurance": "Artifact quality, dependency concentration, and procurement-readiness evidence under stress.",
    }
    for pillar in ("Counterparty", "Export", "Supply Chain Assurance"):
        entries = by_pillar[pillar]
        overall = "GO" if all(row.status == "GO" for row in entries) else entries[0].status
        summary_data.append(
            [
                Paragraph(pillar, small),
                Paragraph(str(len(entries)), body),
                Paragraph(f"{sum(fixture_count(row.fixture) for row in entries)} cases", body),
                Paragraph(
                    f"<font color='{status_color(overall).hexval()}'><b>{status_label(overall)}</b></font>",
                    body,
                ),
                Paragraph(proof_text[pillar], small),
            ]
        )

    summary_table = Table(summary_data, colWidths=[1.42 * inch, 0.46 * inch, 0.72 * inch, 0.96 * inch, 5.54 * inch], repeatRows=1)
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 7.0),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 0.05 * inch))

    pack_data = [["Pillar", "Pack", "Cases", "Focus"]]
    for row in rows:
        pack_data.append(
            [
                Paragraph(row.pillar, small),
                Paragraph(DISPLAY_NAME.get(row.name, row.name.replace("_", " ")), small),
                Paragraph(str(fixture_count(row.fixture)), body),
                Paragraph(row.focus, small),
            ]
        )
    pack_table = Table(pack_data, colWidths=[1.36 * inch, 1.54 * inch, 0.4 * inch, 6.1 * inch], repeatRows=1)
    pack_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 7.0),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(pack_table)

    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=landscape(letter),
        leftMargin=0.28 * inch,
        rightMargin=0.28 * inch,
        topMargin=0.18 * inch,
        bottomMargin=0.14 * inch,
    )
    doc.build(story)


def main() -> int:
    rows = build_rows()
    OUTPUT_MD.write_text(build_markdown(rows), encoding="utf-8")
    build_pdf(rows)
    print(OUTPUT_PDF)
    print(OUTPUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
