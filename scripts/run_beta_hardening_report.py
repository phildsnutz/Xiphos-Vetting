#!/usr/bin/env python3
"""
Generate a beta-readiness hardening report from the current Helios dataset.

The report validates the most expensive/high-visibility surfaces:
  - dossier HTML
  - dossier PDF
  - graph payload integrity
  - monitoring history presence
  - AI narrative presence

It is designed to be a repeatable pre-beta / pre-hotfix gate, not just an
ad hoc smoke script.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import db  # noqa: E402
from ai_analysis import compute_analysis_fingerprint, get_latest_analysis  # noqa: E402
from dossier import generate_dossier  # noqa: E402
from dossier_pdf import generate_pdf_dossier  # noqa: E402
from graph_ingest import get_vendor_graph_summary  # noqa: E402

try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover - graceful degradation
    PdfReader = None


HTML_SECTION_CHECKS = {
    "executive_strip": "Recent change",
    "risk_storyline": "Risk Storyline",
    "ai_brief": "AI Narrative Brief",
    "executive_judgment": "Executive judgment",
}

PDF_SECTION_CHECKS = {
    "executive_strip": "RECENT CHANGE",
    "risk_storyline": "RISK STORYLINE",
    "ai_brief": "AI NARRATIVE BRIEF",
}


@dataclass
class CaseResult:
    case_id: str
    vendor_name: str
    tier: str
    html_ok: bool
    pdf_ok: bool
    graph_ok: bool
    ai_ready: bool
    ai_expected: bool
    monitoring_ready: bool
    graph_entities: int
    graph_relationships: int
    graph_corroborated_edges: int
    graph_missing_endpoints: int
    html_ms: int
    pdf_ms: int
    graph_ms: int
    failures: list[str]
    warnings: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Helios beta hardening report.")
    parser.add_argument("--case-id", action="append", default=[], help="Specific case/vendor IDs to validate")
    parser.add_argument(
        "--cohort-file",
        default="",
        help="Optional JSON cohort file with case objects containing at least an `id` field",
    )
    parser.add_argument("--limit", type=int, default=10, help="Number of recent cases to check when no case IDs are supplied")
    parser.add_argument("--graph-depth", type=int, default=3, help="Graph depth to validate")
    parser.add_argument(
        "--report-dir",
        default=str(ROOT / "docs" / "reports"),
        help="Directory where markdown/json reports should be written",
    )
    parser.add_argument("--print-json", action="store_true", help="Print the JSON summary to stdout")
    return parser.parse_args()


def load_case_ids_from_cohort(cohort_file: str) -> list[str]:
    if not cohort_file:
        return []
    payload = json.loads(Path(cohort_file).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("Cohort file must contain a JSON list")
    case_ids = []
    for entry in payload:
        if not isinstance(entry, dict) or not entry.get("id"):
            raise SystemExit("Each cohort entry must be an object with an `id` field")
        case_ids.append(str(entry["id"]))
    return case_ids


def select_cases(case_ids: list[str], limit: int) -> list[dict[str, Any]]:
    if case_ids:
        selected = []
        for case_id in case_ids:
            vendor = db.get_vendor(case_id)
            if not vendor:
                raise SystemExit(f"Unknown case/vendor id: {case_id}")
            vendor["latest_score"] = db.get_latest_score(case_id)
            selected.append(vendor)
        return selected

    vendors = db.list_vendors_with_scores(limit=max(limit, 1))
    return [vendor for vendor in vendors if vendor.get("latest_score")]


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if PdfReader is None:
        warnings.append("pypdf unavailable; skipped PDF text checks")
        return "", warnings
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        warnings.append("PDF text extraction returned empty text")
    return text, warnings


def validate_graph_payload(graph: dict[str, Any]) -> tuple[bool, dict[str, int], list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    if graph.get("error"):
        return False, {
            "entities": 0,
            "relationships": 0,
            "corroborated_edges": 0,
            "missing_endpoints": 0,
        }, [f"graph error: {graph['error']}"], warnings

    entities = graph.get("entities", [])
    relationships = graph.get("relationships", [])
    entity_ids = {entity.get("id") for entity in entities}
    missing_endpoints = 0
    corroborated_edges = 0

    for rel in relationships:
        if rel.get("source_entity_id") not in entity_ids or rel.get("target_entity_id") not in entity_ids:
            missing_endpoints += 1
        if int(rel.get("corroboration_count") or 0) > 1:
            corroborated_edges += 1

    if relationships and not entities:
        failures.append("graph returned relationships with no entities")
    if missing_endpoints:
        failures.append(f"graph missing hydrated endpoints for {missing_endpoints} relationships")
    if not graph.get("root_entity_id"):
        warnings.append("graph root entity id missing")

    return not failures, {
        "entities": len(entities),
        "relationships": len(relationships),
        "corroborated_edges": corroborated_edges,
        "missing_endpoints": missing_endpoints,
    }, failures, warnings


def validate_section_checks(document: str, checks: dict[str, str], prefix: str) -> tuple[bool, list[str]]:
    failures = [f"{prefix} missing {name.replace('_', ' ')}" for name, marker in checks.items() if marker not in document]
    return not failures, failures


def resolve_cached_analysis(case_id: str, input_hash: str) -> tuple[dict[str, Any] | None, str]:
    if not input_hash:
        return None, "dev"

    cached = get_latest_analysis(case_id, user_id="dev", input_hash=input_hash)
    if cached:
        return cached, str(cached.get("created_by") or "dev")

    cached = get_latest_analysis(case_id, input_hash=input_hash)
    if cached:
        return cached, str(cached.get("created_by") or "dev")

    return None, "dev"


def run_case(vendor: dict[str, Any], graph_depth: int) -> CaseResult:
    case_id = vendor["id"]
    vendor_name = vendor.get("name") or "Unknown"
    latest_score = vendor.get("latest_score") or db.get_latest_score(case_id) or {}
    enrichment = db.get_latest_enrichment(case_id)
    tier = (
        latest_score.get("calibrated", {}).get("calibrated_tier")
        or latest_score.get("tier")
        or latest_score.get("calibrated_tier")
        or "unknown"
    )
    failures: list[str] = []
    warnings: list[str] = []
    ai_fingerprint = compute_analysis_fingerprint(vendor, latest_score, enrichment) if latest_score else ""
    cached_analysis, analysis_user_id = resolve_cached_analysis(case_id, ai_fingerprint)

    start = time.perf_counter()
    html = generate_dossier(case_id, user_id=analysis_user_id, hydrate_ai=not bool(cached_analysis))
    html_ms = int((time.perf_counter() - start) * 1000)
    html_checks = dict(HTML_SECTION_CHECKS)
    cached_analysis, analysis_user_id = resolve_cached_analysis(case_id, ai_fingerprint)
    ai_expected = bool(cached_analysis)
    if not ai_expected:
        html_checks.pop("ai_brief", None)
        html_checks.pop("executive_judgment", None)
    html_ok, html_failures = validate_section_checks(html, html_checks, "html dossier")
    failures.extend(html_failures)

    start = time.perf_counter()
    pdf_bytes = generate_pdf_dossier(case_id, user_id=analysis_user_id, hydrate_ai=False)
    pdf_ms = int((time.perf_counter() - start) * 1000)
    pdf_text, pdf_warnings = extract_pdf_text(pdf_bytes)
    warnings.extend(pdf_warnings)
    pdf_checks = dict(PDF_SECTION_CHECKS)
    if not ai_expected:
        pdf_checks.pop("ai_brief", None)
    pdf_ok, pdf_failures = validate_section_checks(pdf_text.upper(), pdf_checks, "pdf dossier")
    failures.extend(pdf_failures)

    start = time.perf_counter()
    graph = get_vendor_graph_summary(case_id, depth=graph_depth)
    graph_ms = int((time.perf_counter() - start) * 1000)
    graph_ok, graph_stats, graph_failures, graph_warnings = validate_graph_payload(graph)
    failures.extend(graph_failures)
    warnings.extend(graph_warnings)

    monitoring_history = db.get_monitoring_history(case_id, limit=1)
    monitoring_ready = bool(monitoring_history)
    if not monitoring_ready:
        warnings.append("no monitoring history yet")

    ai_ready = "AI Narrative Brief" in html
    if ai_expected and not ai_ready:
        failures.append("ai narrative brief missing from html dossier")
    elif not ai_expected and not ai_ready:
        warnings.append("ai brief not warmed yet")

    return CaseResult(
        case_id=case_id,
        vendor_name=vendor_name,
        tier=str(tier),
        html_ok=html_ok,
        pdf_ok=pdf_ok,
        graph_ok=graph_ok,
        ai_ready=ai_ready,
        ai_expected=ai_expected,
        monitoring_ready=monitoring_ready,
        graph_entities=graph_stats["entities"],
        graph_relationships=graph_stats["relationships"],
        graph_corroborated_edges=graph_stats["corroborated_edges"],
        graph_missing_endpoints=graph_stats["missing_endpoints"],
        html_ms=html_ms,
        pdf_ms=pdf_ms,
        graph_ms=graph_ms,
        failures=failures,
        warnings=warnings,
    )


def build_summary(results: list[CaseResult], graph_depth: int) -> dict[str, Any]:
    failure_count = sum(1 for result in results if result.failures)
    warning_count = sum(len(result.warnings) for result in results)
    html_failures = sum(1 for result in results if not result.html_ok)
    pdf_failures = sum(1 for result in results if not result.pdf_ok)
    graph_failures = sum(1 for result in results if not result.graph_ok)
    ai_missing = sum(1 for result in results if result.ai_expected and not result.ai_ready)
    ai_not_warmed = sum(1 for result in results if not result.ai_expected)
    monitoring_missing = sum(1 for result in results if not result.monitoring_ready)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "graph_depth": graph_depth,
        "cases_checked": len(results),
        "cases_with_failures": failure_count,
        "warning_count": warning_count,
        "html_failures": html_failures,
        "pdf_failures": pdf_failures,
        "graph_failures": graph_failures,
        "ai_missing": ai_missing,
        "ai_not_warmed": ai_not_warmed,
        "monitoring_missing": monitoring_missing,
        "tiers": dict(Counter(result.tier for result in results)),
        "cases": [result.__dict__ for result in results],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Helios Beta Hardening Report",
        "",
        f"Generated: {summary['generated_at']}",
        f"Graph depth: {summary['graph_depth']}",
        "",
        "## Summary",
        "",
        f"- Cases checked: {summary['cases_checked']}",
        f"- Cases with failures: {summary['cases_with_failures']}",
        f"- HTML dossier failures: {summary['html_failures']}",
        f"- PDF dossier failures: {summary['pdf_failures']}",
        f"- Graph failures: {summary['graph_failures']}",
        f"- Cases missing AI brief despite cached analysis: {summary['ai_missing']}",
        f"- Cases without warmed AI yet: {summary['ai_not_warmed']}",
        f"- Cases missing monitoring history: {summary['monitoring_missing']}",
        f"- Total warnings: {summary['warning_count']}",
        "",
        "## Tier Mix",
        "",
    ]
    for tier, count in sorted(summary["tiers"].items()):
        lines.append(f"- {tier}: {count}")

    lines.extend(["", "## Case Results", ""])

    for case in summary["cases"]:
        lines.extend([
            f"### {case['vendor_name']} ({case['case_id']})",
            "",
            f"- Tier: {case['tier']}",
            f"- HTML dossier: {'PASS' if case['html_ok'] else 'FAIL'} in {case['html_ms']} ms",
            f"- PDF dossier: {'PASS' if case['pdf_ok'] else 'FAIL'} in {case['pdf_ms']} ms",
            f"- Graph payload: {'PASS' if case['graph_ok'] else 'FAIL'} in {case['graph_ms']} ms",
            f"- Graph counts: {case['graph_entities']} entities, {case['graph_relationships']} relationships, {case['graph_corroborated_edges']} corroborated edges",
            f"- Monitoring history: {'present' if case['monitoring_ready'] else 'missing'}",
            f"- AI brief: {'present' if case['ai_ready'] else ('not warmed yet' if not case['ai_expected'] else 'missing')}",
        ])
        if case["failures"]:
            lines.append("- Failures:")
            for failure in case["failures"]:
                lines.append(f"  - {failure}")
        if case["warnings"]:
            lines.append("- Warnings:")
            for warning in case["warnings"]:
                lines.append(f"  - {warning}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    selected_case_ids = list(args.case_id)
    selected_case_ids.extend(load_case_ids_from_cohort(args.cohort_file))
    deduped_case_ids = list(dict.fromkeys(selected_case_ids))

    vendors = select_cases(deduped_case_ids, args.limit)
    if not vendors:
        raise SystemExit("No scored cases found for hardening report")

    results = [run_case(vendor, args.graph_depth) for vendor in vendors]
    summary = build_summary(results, args.graph_depth)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = report_dir / f"helios-beta-hardening-report-{stamp}.json"
    md_path = report_dir / f"helios-beta-hardening-report-{stamp}.md"

    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")

    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    if args.print_json:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
