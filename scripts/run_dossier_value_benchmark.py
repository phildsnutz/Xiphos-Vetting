#!/usr/bin/env python3
"""
Value benchmark for Helios counterparty briefs.

The goal is not byte-for-byte golden rendering. The goal is to catch regressions
where the artifact stops being commercially useful even if the prose still looks
polished.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from helios_core.brief_engine import generate_html_brief  # type: ignore  # noqa: E402


DEFAULT_SPEC_PATH = ROOT / "fixtures" / "dossier_benchmark" / "value_benchmark_pack.json"
DEFAULT_REPORT_ROOT = ROOT / "docs" / "reports" / "dossier_value_benchmark"
DEFAULT_DIMENSION_WEIGHTS = {
    "opening_value": 0.2,
    "non_obvious_insight": 0.15,
    "procurement_specificity": 0.2,
    "ownership_control_clarity": 0.1,
    "signal_noise_discipline": 0.1,
    "provenance_honesty": 0.1,
    "decision_usefulness": 0.1,
    "readability": 0.05,
}
DEFAULT_FORBIDDEN_FRAGMENTS = [
    "Traceback (most recent call last)",
    "ModuleNotFoundError",
    "/Users/tyegonzalez/",
    "/app/backend",
    "jinja2.exceptions",
    "Graph change:",
    "Axiom is still warming",
    "No independent analytical challenge has been applied",
]


@dataclass
class DimensionScore:
    name: str
    score: int
    notes: list[str]


@dataclass
class CaseResult:
    vendor_id: str
    vendor_name: str
    verdict: str
    weighted_score_pct: float
    dimensions: list[DimensionScore]
    required_fragments_missing: list[str]
    forbidden_fragments_present: list[str]
    artifact_path: str


def _strip_html(html: str) -> str:
    no_style = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    no_tags = re.sub(r"<[^>]+>", " ", no_style)
    collapsed = re.sub(r"\s+", " ", unescape(no_tags)).strip()
    return collapsed


def _extract_summary_line(html: str) -> str:
    match = re.search(r'<div class="summary">(.*?)</div>', html, flags=re.S | re.I)
    if not match:
        return ""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", match.group(1)))).strip()


def _section_present(text: str, heading: str) -> bool:
    return heading.lower() in text.lower()


def _count_present(text: str, fragments: list[str]) -> int:
    return sum(1 for fragment in fragments if fragment.lower() in text.lower())


def score_opening_value(summary: str, text: str) -> DimensionScore:
    notes: list[str] = []
    score = 1
    if summary:
        score = 2
    if any(marker in summary.lower() for marker in ["direct access on", "recurring work under", "control path", "customer concentration"]):
        score = 4
        notes.append("opening leads with a commercially specific posture")
    if any(marker in summary.lower() for marker in ["prime", "vehicle", "upstream", "downstream"]):
        score = max(score, 5)
        notes.append("opening references concrete operating lanes")
    if "offshore leak proximity" in summary.lower():
        score = min(score, 3)
        notes.append("opening still spends attention on weak-match pressure")
    return DimensionScore("opening_value", max(0, min(score, 5)), notes)


def score_non_obvious_insight(text: str) -> DimensionScore:
    notes: list[str] = []
    markers = [
        "direct access on",
        "recurring work under",
        "recurs as upstream prime",
        "recurs as downstream subcontractor",
        "customer concentration",
        "dual-posture",
    ]
    hits = _count_present(text, markers)
    if hits >= 5:
        score = 5
    elif hits >= 3:
        score = 4
    elif hits >= 2:
        score = 3
    elif hits >= 1:
        score = 2
    else:
        score = 1
    if hits:
        notes.append(f"{hits} non-obvious market-pattern markers surfaced")
    return DimensionScore("non_obvious_insight", score, notes)


def score_procurement_specificity(text: str) -> DimensionScore:
    notes: list[str] = []
    required_sections = [
        "Procurement Footprint",
        "Prime Vehicles",
        "Subcontract Vehicles",
        "Recurring Upstream Primes",
        "Recurring Downstream Subs",
        "Customer Concentration",
    ]
    section_hits = _count_present(text, required_sections)
    named_lane_hits = _count_present(text, ["OASIS", "GSA IT GWAC", "SEAPORT-NXG", "PEOS", "Alliant", "SEWP"])
    if section_hits >= 6 and named_lane_hits >= 3:
        score = 5
    elif section_hits >= 4 and named_lane_hits >= 2:
        score = 4
    elif section_hits >= 3:
        score = 3
    elif section_hits >= 1:
        score = 2
    else:
        score = 1
    notes.append(f"{section_hits} procurement sections rendered")
    if named_lane_hits:
        notes.append(f"{named_lane_hits} named vehicle markers surfaced")
    return DimensionScore("procurement_specificity", score, notes)


def score_ownership_control_clarity(text: str) -> DimensionScore:
    notes: list[str] = []
    hits = _count_present(text, ["Supplier Passport", "Verification status", "control", "ownership", "Posture supported by"])
    if hits >= 5:
        score = 5
    elif hits >= 4:
        score = 4
    elif hits >= 3:
        score = 3
    elif hits >= 2:
        score = 2
    else:
        score = 1
    return DimensionScore("ownership_control_clarity", score, notes)


def score_signal_noise_discipline(summary: str, text: str) -> DimensionScore:
    notes: list[str] = []
    score = 5
    if "workflow control" in text.lower() or "public-source triage" in text.lower():
        score -= 2
        notes.append("internal process language leaked into artifact")
    if "offshore leak proximity" in summary.lower():
        score -= 1
        notes.append("weak-match caveat still appears in headline")
    if "what this implies" not in text.lower():
        score -= 1
    return DimensionScore("signal_noise_discipline", max(1, score), notes)


def score_provenance_honesty(text: str) -> DimensionScore:
    score = 1
    markers = _count_present(text, ["CONFIRMED", "UNCONFIRMED", "ASSESSED", "Posture is", "requires disambiguation"])
    if markers >= 5:
        score = 5
    elif markers >= 4:
        score = 4
    elif markers >= 3:
        score = 3
    elif markers >= 2:
        score = 2
    return DimensionScore("provenance_honesty", score, [])


def score_decision_usefulness(summary: str, text: str) -> DimensionScore:
    markers = _count_present(
        text,
        [
            "What changes the call",
            "Closure method",
            "Recurring Upstream Primes",
            "Recurring Downstream Subs",
            "Market Position Read",
        ],
    )
    if markers >= 5 and summary:
        score = 5
    elif markers >= 4:
        score = 4
    elif markers >= 3:
        score = 3
    elif markers >= 2:
        score = 2
    else:
        score = 1
    return DimensionScore("decision_usefulness", score, [])


def score_readability(text: str) -> DimensionScore:
    headings = _count_present(
        text,
        [
            "Decision Thesis",
            "Competing Case",
            "Dark Space",
            "Procurement Footprint",
            "Supplier Passport",
            "Evidence Ledger",
        ],
    )
    if headings >= 6:
        score = 5
    elif headings >= 5:
        score = 4
    elif headings >= 4:
        score = 3
    elif headings >= 3:
        score = 2
    else:
        score = 1
    return DimensionScore("readability", score, [])


def score_case(html: str) -> list[DimensionScore]:
    text = _strip_html(html)
    summary = _extract_summary_line(html)
    return [
        score_opening_value(summary, text),
        score_non_obvious_insight(text),
        score_procurement_specificity(text),
        score_ownership_control_clarity(text),
        score_signal_noise_discipline(summary, text),
        score_provenance_honesty(text),
        score_decision_usefulness(summary, text),
        score_readability(text),
    ]


def _weighted_score_pct(dimensions: list[DimensionScore], weights: dict[str, float]) -> float:
    total = 0.0
    weight_sum = 0.0
    for dimension in dimensions:
        weight = float(weights.get(dimension.name, 0.0))
        total += (dimension.score / 5.0) * weight
        weight_sum += weight
    if weight_sum <= 0:
        return 0.0
    return round((total / weight_sum) * 100.0, 1)


def load_specs(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("Benchmark spec file must be a JSON array")
    return [dict(item) for item in payload if isinstance(item, dict)]


def evaluate_case(spec: dict[str, Any], report_dir: Path, weights: dict[str, float]) -> CaseResult:
    vendor_id = str(spec.get("vendor_id") or "").strip()
    vendor_name = str(spec.get("vendor_name") or vendor_id).strip()
    html = generate_html_brief(vendor_id)
    artifact_path = report_dir / f"{vendor_name.lower().replace(' ', '-').replace('/', '-')}.html"
    artifact_path.write_text(html, encoding="utf-8")
    text = _strip_html(html)
    dimensions = score_case(html)
    weighted = _weighted_score_pct(dimensions, weights)

    required_fragments = [str(item) for item in (spec.get("required_fragments") or []) if str(item).strip()]
    forbidden_fragments = [str(item) for item in (spec.get("forbidden_fragments") or DEFAULT_FORBIDDEN_FRAGMENTS) if str(item).strip()]
    missing = [fragment for fragment in required_fragments if fragment.lower() not in text.lower()]
    present = [fragment for fragment in forbidden_fragments if fragment.lower() in text.lower()]

    min_weighted = float(spec.get("min_weighted_score_pct") or 0.0)
    min_dimensions = spec.get("min_dimension_scores") if isinstance(spec.get("min_dimension_scores"), dict) else {}
    verdict = "PASS"
    if weighted < min_weighted:
        verdict = "FAIL"
    for dimension in dimensions:
        minimum = int(min_dimensions.get(dimension.name, 0) or 0)
        if dimension.score < minimum:
            verdict = "FAIL"
            break
    if missing or present:
        verdict = "FAIL"

    return CaseResult(
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        verdict=verdict,
        weighted_score_pct=weighted,
        dimensions=dimensions,
        required_fragments_missing=missing,
        forbidden_fragments_present=present,
        artifact_path=str(artifact_path),
    )


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Helios Dossier Value Benchmark",
        "",
        f"- Generated: `{summary['generated_at']}`",
        f"- Overall verdict: **{summary['overall_verdict']}**",
        f"- Average weighted score: `{summary['average_weighted_score_pct']}`",
        f"- Cases: `{len(summary['cases'])}`",
        "",
    ]
    for case in summary["cases"]:
        lines.extend([
            f"## {case['vendor_name']}",
            "",
            f"- Verdict: **{case['verdict']}**",
            f"- Weighted score: `{case['weighted_score_pct']}`",
            f"- Artifact: {case['artifact_path']}",
            "",
            "| Dimension | Score | Notes |",
            "| --- | --- | --- |",
        ])
        for dimension in case["dimensions"]:
            notes = "; ".join(dimension["notes"]) if dimension["notes"] else ""
            lines.append(f"| `{dimension['name']}` | `{dimension['score']}` | {notes} |")
        if case["required_fragments_missing"]:
            lines.append("")
            lines.append("- Missing required fragments:")
            for fragment in case["required_fragments_missing"]:
                lines.append(f"  - `{fragment}`")
        if case["forbidden_fragments_present"]:
            lines.append("")
            lines.append("- Forbidden fragments present:")
            for fragment in case["forbidden_fragments_present"]:
                lines.append(f"  - `{fragment}`")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a value benchmark against Helios dossier artifacts")
    parser.add_argument("--spec-file", default=str(DEFAULT_SPEC_PATH))
    parser.add_argument("--report-dir", default="")
    args = parser.parse_args(argv)

    specs = load_specs(args.spec_file)
    if not specs:
        raise SystemExit("No dossier benchmark specs found")

    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    report_dir = Path(args.report_dir) if args.report_dir else DEFAULT_REPORT_ROOT / stamp
    report_dir.mkdir(parents=True, exist_ok=True)

    weights = dict(DEFAULT_DIMENSION_WEIGHTS)
    results = [evaluate_case(spec, report_dir, weights) for spec in specs]
    average = round(sum(item.weighted_score_pct for item in results) / len(results), 1)
    overall_verdict = "PASS" if all(item.verdict == "PASS" for item in results) else "FAIL"

    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "overall_verdict": overall_verdict,
        "average_weighted_score_pct": average,
        "cases": [
            {
                **asdict(result),
                "dimensions": [asdict(dimension) for dimension in result.dimensions],
            }
            for result in results
        ],
    }
    summary_json = report_dir / "summary.json"
    summary_md = report_dir / "summary.md"
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary_md.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({
        "overall_verdict": overall_verdict,
        "average_weighted_score_pct": average,
        "report_json": str(summary_json),
        "report_md": str(summary_md),
    }, indent=2))
    return 0 if overall_verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
