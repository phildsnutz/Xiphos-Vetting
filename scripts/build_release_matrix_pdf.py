#!/usr/bin/env python3
"""
Build a one-page Helios release-matrix PDF for the fixed 9-pack gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output" / "pdf"
REPORT_DIR = ROOT / "docs" / "reports"
OUTPUT_PDF = OUTPUT_DIR / "HELIOS_RELEASE_MATRIX_2026-03-28.pdf"
OUTPUT_MD = REPORT_DIR / "HELIOS_RELEASE_MATRIX_2026-03-28.md"


@dataclass(frozen=True)
class PackRow:
    pillar: str
    name: str
    fixture: str
    focus: str
    status: str


COUNTERPARTY_PACKS: tuple[tuple[str, str, str], ...] = (
    (
        "counterparty_identity_foundation",
        "fixtures/customer_demo/counterparty_identity_foundation_pack.json",
        "Identifiers, official website, baseline entity resolution",
    ),
    (
        "counterparty_dossier_quality",
        "fixtures/customer_demo/counterparty_dossier_quality_pack.json",
        "HTML, PDF, passport, AI brief, assistant surface",
    ),
    (
        "counterparty_control_paths",
        "fixtures/customer_demo/counterparty_control_path_pack.json",
        "Ownership and control-path depth on weak-but-critical names",
    ),
)

EXPORT_PACKS: tuple[tuple[str, str, str], ...] = (
    (
        "export_ambiguous_end_use",
        "fixtures/adversarial_gym/export_lane_ai_ambiguous_end_use_cases.json",
        "Ambiguous end-use narratives and safe escalation",
    ),
    (
        "export_transshipment_diversion",
        "fixtures/adversarial_gym/export_lane_ai_transshipment_diversion_cases.json",
        "Transshipment, diversion, intermediaries, reroute risk",
    ),
    (
        "export_defense_services_foreign_person",
        "fixtures/adversarial_gym/export_lane_ai_defense_services_foreign_person_cases.json",
        "Defense services, foreign-person access, TTCP and provisos",
    ),
)

ASSURANCE_PACKS: tuple[tuple[str, str, str], ...] = (
    (
        "supply_chain_assurance_artifact_quality",
        "fixtures/adversarial_gym/supply_chain_assurance_artifact_quality_cases.json",
        "SBOM, VEX, provenance, public assurance evidence quality",
    ),
    (
        "supply_chain_assurance_dependency_concentration",
        "fixtures/adversarial_gym/supply_chain_assurance_dependency_concentration_cases.json",
        "Shared providers, dependency concentration, correlated blast radius",
    ),
    (
        "supply_chain_assurance_procurement_readiness",
        "fixtures/adversarial_gym/supply_chain_assurance_procurement_readiness_cases.json",
        "CMMC and procurement evidence sufficiency under pressure",
    ),
)


def latest_summary_json(base_dir: Path) -> Path | None:
    candidates = sorted(base_dir.glob("*/summary.json"))
    return candidates[-1] if candidates else None


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_count(rel_path: str) -> int:
    payload = load_json(ROOT / rel_path)
    if not isinstance(payload, list):
        raise ValueError(f"fixture is not a list: {rel_path}")
    return len(payload)


def current_counterparty_statuses() -> dict[str, str]:
    ready_summary = latest_summary_json(REPORT_DIR / "live_counterparty_readiness")
    if ready_summary:
        payload = load_json(ready_summary)
        step_map = {
            str(step.get("name")): str(step.get("verdict"))
            for step in payload.get("steps", [])
            if isinstance(step, dict)
        }
        return {
            "counterparty_identity_foundation": step_map.get("counterparty_identity_foundation", "UNKNOWN"),
            "counterparty_dossier_quality": step_map.get("counterparty_dossier_quality", "UNKNOWN"),
            "counterparty_control_paths": step_map.get("counterparty_control_paths", "UNKNOWN"),
        }

    if (REPORT_DIR / "live_counterparty_readiness").exists():
        return {name: "REVALIDATING" for name, _, _ in COUNTERPARTY_PACKS}
    return {name: "UNKNOWN" for name, _, _ in COUNTERPARTY_PACKS}


def current_multi_lane_statuses() -> dict[str, str]:
    ready_summary = latest_summary_json(REPORT_DIR / "live_helios_readiness")
    if not ready_summary:
        return {}
    payload = load_json(ready_summary)
    return {
        str(step.get("name")): str(step.get("verdict"))
        for step in payload.get("steps", [])
        if isinstance(step, dict)
    }


def build_rows() -> list[PackRow]:
    multi = current_multi_lane_statuses()
    counterparty = current_counterparty_statuses()
    rows: list[PackRow] = []
    for name, fixture, focus in COUNTERPARTY_PACKS:
        status = counterparty.get(name, "UNKNOWN")
        if status == "REVALIDATING":
            status = "RETESTING"
        rows.append(PackRow("Counterparty", name, fixture, focus, status))
    for name, fixture, focus in EXPORT_PACKS:
        rows.append(PackRow("Export", name, fixture, focus, multi.get(name, "UNKNOWN")))
    for name, fixture, focus in ASSURANCE_PACKS:
        rows.append(PackRow("Supply Chain Assurance", name, fixture, focus, multi.get(name, "UNKNOWN")))
    return rows


def status_color(status: str):
    normalized = status.upper()
    if normalized == "GO":
        return colors.HexColor("#0F8A5F")
    if normalized in {"CAUTION", "REVALIDATING", "IN_PROGRESS"}:
        return colors.HexColor("#B7791F")
    if normalized == "NO_GO":
        return colors.HexColor("#C53030")
    return colors.HexColor("#475569")


def build_markdown(rows: list[PackRow]) -> str:
    total_cases = sum(fixture_count(row.fixture) for row in rows)
    lines = [
        "# Helios Release Matrix",
        "",
        "- Date: 2026-03-28",
        "- Fixed packs: 9",
        f"- Total fixed scenarios and companies: {total_cases}",
        "- Model: 3 packs per pillar, mandatory release gate, customer-path stabilization first",
        "",
        "| Pillar | Pack | Cases | Focus | Status |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.pillar} | {row.name} | {fixture_count(row.fixture)} | {row.focus} | {row.status} |"
        )
    lines.extend(
        [
            "",
            "## Current read",
            "",
            "- Export is green on all 3 packs.",
            "- Supply Chain Assurance is green on all 3 packs.",
            "- Counterparty is the only pillar still under live revalidation after the dossier and readiness-path fixes.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_pdf(rows: list[PackRow]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=23,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=6,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#334155"),
    )
    small = ParagraphStyle(
        "Small",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#475569"),
    )

    total_cases = sum(fixture_count(row.fixture) for row in rows)
    story: list = []
    story.append(Paragraph("Helios Release Matrix", title))
    story.append(
        Paragraph(
            "Nine fixed packs now define release readiness. The gate checks real customer paths, not synthetic unit-only success.",
            body,
        )
    )
    story.append(Spacer(1, 0.08 * inch))
    story.append(
        Paragraph(
            f"Snapshot: 3 pillars | 9 fixed packs | {total_cases} fixed scenarios and companies | Export and Supply Chain Assurance green | Counterparty revalidating after systemic dossier and readiness fixes.",
            body,
        )
    )
    story.append(Spacer(1, 0.12 * inch))

    table_data = [
        ["Pillar", "Pack", "Cases", "Focus", "Status"],
    ]
    for row in rows:
        table_data.append(
            [
                Paragraph(row.pillar, small),
                Paragraph(row.name.replace("_", "<br/>"), small),
                Paragraph(str(fixture_count(row.fixture)), body),
                Paragraph(row.focus, small),
                Paragraph(
                    f"<font color='{status_color(row.status).hexval()}'>"
                    f"<b>{row.status}</b></font>",
                    body,
                ),
            ]
        )

    table = Table(table_data, colWidths=[1.55 * inch, 1.8 * inch, 0.5 * inch, 3.9 * inch, 0.9 * inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 1), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ]
        )
    )
    story.append(table)

    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=landscape(letter),
        leftMargin=0.45 * inch,
        rightMargin=0.45 * inch,
        topMargin=0.3 * inch,
        bottomMargin=0.25 * inch,
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
