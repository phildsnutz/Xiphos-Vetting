#!/usr/bin/env python3
"""
Evaluate whether Helios meets the current prime-time exit criteria.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_READINESS_DIR = ROOT / "docs" / "reports" / "helios_readiness"
DEFAULT_GATE_DIR = ROOT / "docs" / "reports" / "customer_demo_gate"
DEFAULT_QUERY_TO_DOSSIER_DIR = ROOT / "docs" / "reports" / "live_query_to_dossier_canary" / "query_to_dossier_gauntlet"
DEFAULT_GRAPH_TRAINING_BENCHMARK_DIR = ROOT / "docs" / "reports" / "graph_training_benchmark"
DEFAULT_ACCEPTANCE_SET = ROOT / "fixtures" / "customer_demo" / "counterparty_acceptance_set.json"
DEFAULT_STABLE_CANARY_PACK = ROOT / "fixtures" / "customer_demo" / "counterparty_canary_pack.json"
DEFAULT_CRITERIA = ROOT / "fixtures" / "customer_demo" / "prime_time_exit_criteria.json"

DEFAULT_FLAGSHIP_COMPANIES = {
    "Yorktown Systems Group": "yorktown-systems-group",
    "Berry Aviation, Inc.": "berry-aviation-inc",
    "Columbia Helicopters, Inc.": "columbia-helicopters-inc",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Helios against prime-time exit criteria.")
    parser.add_argument("--criteria", default=str(DEFAULT_CRITERIA))
    parser.add_argument("--readiness-summary", default="")
    parser.add_argument("--readiness-dir", default=str(DEFAULT_READINESS_DIR))
    parser.add_argument("--query-to-dossier-summary", default="")
    parser.add_argument("--query-to-dossier-dir", default=str(DEFAULT_QUERY_TO_DOSSIER_DIR))
    parser.add_argument("--graph-training-benchmark-summary", default="")
    parser.add_argument("--graph-training-benchmark-dir", default=str(DEFAULT_GRAPH_TRAINING_BENCHMARK_DIR))
    parser.add_argument("--acceptance-set", default=str(DEFAULT_ACCEPTANCE_SET))
    parser.add_argument("--stable-canary-pack", default=str(DEFAULT_STABLE_CANARY_PACK))
    parser.add_argument("--customer-demo-gate-dir", default=str(DEFAULT_GATE_DIR))
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _latest_summary_json(base_dir: Path, *, prefix: str | None = None) -> Path | None:
    pattern = "summary.json" if prefix is None else f"{prefix}-*/summary.json"
    candidates = sorted(base_dir.glob(pattern))
    return candidates[-1] if candidates else None


def _latest_nested_summary_json(base_dir: Path) -> Path | None:
    candidates = sorted(base_dir.glob("*/summary.json"))
    return candidates[-1] if candidates else None


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"expected JSON object in {path}")
    return payload


def _criterion(name: str, passed: bool, detail: str, *, actual: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "detail": detail,
        "actual": actual,
        "expected": expected,
    }


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    criteria = _read_json(Path(args.criteria))
    readiness_path = Path(args.readiness_summary) if args.readiness_summary else _latest_summary_json(Path(args.readiness_dir))
    if readiness_path is None:
        raise SystemExit("no readiness summary found")
    readiness = _read_json(readiness_path)
    query_to_dossier_path = (
        Path(args.query_to_dossier_summary)
        if args.query_to_dossier_summary
        else _latest_nested_summary_json(Path(args.query_to_dossier_dir))
    )
    if query_to_dossier_path is None:
        raise SystemExit("no query-to-dossier summary found")
    query_to_dossier = _read_json(query_to_dossier_path)
    graph_training_benchmark_path = (
        Path(args.graph_training_benchmark_summary)
        if args.graph_training_benchmark_summary
        else _latest_nested_summary_json(Path(args.graph_training_benchmark_dir))
    )
    graph_training_benchmark = (
        _read_json(graph_training_benchmark_path)
        if graph_training_benchmark_path is not None
        else {}
    )

    acceptance_set = json.loads(Path(args.acceptance_set).read_text(encoding="utf-8"))
    stable_pack = json.loads(Path(args.stable_canary_pack).read_text(encoding="utf-8"))
    if not isinstance(acceptance_set, list) or not isinstance(stable_pack, list):
        raise SystemExit("acceptance set and stable canary pack must be JSON lists")

    steps = readiness.get("steps") if isinstance(readiness.get("steps"), list) else []
    pillar_verdicts = {str(step.get("pillar")): str(step.get("verdict")) for step in steps if isinstance(step, dict)}
    counterparty_step = next(
        (step for step in steps if isinstance(step, dict) and str(step.get("pillar")) == "counterparty"),
        None,
    )

    checks: list[dict[str, Any]] = []
    overall_expected = str(criteria.get("overall_readiness_verdict") or "GO")
    overall_actual = str(readiness.get("verdict") or readiness.get("overall_verdict") or "UNKNOWN")
    checks.append(
        _criterion(
            "overall_readiness",
            overall_actual == overall_expected,
            f"overall readiness is {overall_actual}",
            actual=overall_actual,
            expected=overall_expected,
        )
    )

    required_pillars = criteria.get("required_pillars") if isinstance(criteria.get("required_pillars"), dict) else {}
    for pillar, expected in required_pillars.items():
        actual = pillar_verdicts.get(str(pillar), "UNKNOWN")
        checks.append(
            _criterion(
                f"pillar:{pillar}",
                actual == str(expected),
                f"{pillar} verdict is {actual}",
                actual=actual,
                expected=str(expected),
            )
        )

    min_stable = int(criteria.get("min_stable_canary_companies") or 0)
    checks.append(
        _criterion(
            "stable_canary_size",
            len(stable_pack) >= min_stable,
            f"stable counterparty canary pack has {len(stable_pack)} companies",
            actual=len(stable_pack),
            expected=min_stable,
        )
    )

    min_acceptance = int(criteria.get("min_acceptance_registry_companies") or 0)
    checks.append(
        _criterion(
            "acceptance_registry_size",
            len(acceptance_set) >= min_acceptance,
            f"acceptance registry has {len(acceptance_set)} companies",
            actual=len(acceptance_set),
            expected=min_acceptance,
        )
    )

    required_gauntlet_verdict = str(criteria.get("required_query_to_dossier_verdict") or "PASS")
    gauntlet_actual = str(query_to_dossier.get("overall_verdict") or "UNKNOWN")
    checks.append(
        _criterion(
            "query_to_dossier",
            gauntlet_actual == required_gauntlet_verdict,
            f"query-to-dossier gauntlet is {gauntlet_actual}",
            actual=gauntlet_actual,
            expected=required_gauntlet_verdict,
        )
    )
    oci_summary = query_to_dossier.get("oci_summary") if isinstance(query_to_dossier.get("oci_summary"), dict) else {}
    graph_summary = query_to_dossier.get("graph_summary") if isinstance(query_to_dossier.get("graph_summary"), dict) else {}
    neo4j_summary = query_to_dossier.get("neo4j_summary") if isinstance(query_to_dossier.get("neo4j_summary"), dict) else {}
    required_oci_flows = int(criteria.get("required_oci_flows_passed") or 0)
    if required_oci_flows:
        actual = int(oci_summary.get("passed_flows") or 0)
        checks.append(
            _criterion(
                "query_to_dossier_oci",
                actual >= required_oci_flows,
                f"query-to-dossier OCI passed {actual} required flows",
                actual=actual,
                expected=required_oci_flows,
            )
        )
    required_descriptor_only_oci = int(criteria.get("required_descriptor_only_oci_flows_passed") or 0)
    if required_descriptor_only_oci:
        actual = int(oci_summary.get("descriptor_only_passed_flows") or 0)
        checks.append(
            _criterion(
                "query_to_dossier_oci_descriptor_only",
                actual >= required_descriptor_only_oci,
                f"query-to-dossier OCI preserved descriptor-only ownership in {actual} flows",
                actual=actual,
                expected=required_descriptor_only_oci,
            )
        )
    required_graph_flows = int(criteria.get("required_graph_flows_passed") or 0)
    if required_graph_flows:
        actual = int(graph_summary.get("passed_flows") or 0)
        checks.append(
            _criterion(
                "query_to_dossier_graph",
                actual >= required_graph_flows,
                f"query-to-dossier graph requirements passed in {actual} flows",
                actual=actual,
                expected=required_graph_flows,
            )
        )
    max_thin_graph_flows = int(criteria.get("max_thin_graph_flows") or 0)
    if "max_thin_graph_flows" in criteria:
        actual = int(graph_summary.get("thin_graph_flows") or 0)
        checks.append(
            _criterion(
                "query_to_dossier_graph_thin",
                actual <= max_thin_graph_flows,
                f"query-to-dossier has {actual} thin graph flows",
                actual=actual,
                expected=max_thin_graph_flows,
            )
        )
    max_missing_required_graph_families_flows = int(criteria.get("max_missing_required_graph_families_flows") or 0)
    if "max_missing_required_graph_families_flows" in criteria:
        actual = int(graph_summary.get("flows_with_missing_required_edge_families") or 0)
        checks.append(
            _criterion(
                "query_to_dossier_graph_missing_families",
                actual <= max_missing_required_graph_families_flows,
                f"query-to-dossier has {actual} flows with missing required graph edge families",
                actual=actual,
                expected=max_missing_required_graph_families_flows,
            )
        )
    if "required_neo4j_available" in criteria:
        expected = bool(criteria.get("required_neo4j_available"))
        actual = bool(neo4j_summary.get("neo4j_available"))
        checks.append(
            _criterion(
                "neo4j_available",
                actual is expected,
                f"query-to-dossier Neo4j availability is {actual}",
                actual=actual,
                expected=expected,
            )
        )

    required_graph_training_verdict = criteria.get("required_graph_training_benchmark_verdict")
    if required_graph_training_verdict is not None:
        actual = str(graph_training_benchmark.get("overall_verdict") or "MISSING")
        checks.append(
            _criterion(
                "graph_training_benchmark",
                actual == str(required_graph_training_verdict),
                f"graph training benchmark is {actual}",
                actual=actual,
                expected=str(required_graph_training_verdict),
            )
        )

    required_graph_training_foundation = criteria.get("required_graph_training_data_foundation_verdict")
    if required_graph_training_foundation is not None:
        foundation = (
            graph_training_benchmark.get("data_foundation")
            if isinstance(graph_training_benchmark.get("data_foundation"), dict)
            else {}
        )
        actual = str(foundation.get("verdict") or "MISSING")
        checks.append(
            _criterion(
                "graph_training_data_foundation",
                actual == str(required_graph_training_foundation),
                f"graph training data foundation is {actual}",
                actual=actual,
                expected=str(required_graph_training_foundation),
            )
        )

    required_stage_verdicts = (
        criteria.get("required_graph_training_stage_verdicts")
        if isinstance(criteria.get("required_graph_training_stage_verdicts"), dict)
        else {}
    )
    if required_stage_verdicts:
        stage_rows = graph_training_benchmark.get("stage_results")
        stage_results = {
            str(row.get("stage_id")): str(row.get("verdict"))
            for row in stage_rows
            if isinstance(stage_rows, list) and isinstance(row, dict)
        }
        for stage_id, expected in required_stage_verdicts.items():
            actual = stage_results.get(str(stage_id), "MISSING")
            checks.append(
                _criterion(
                    f"graph_training_stage:{stage_id}",
                    actual == str(expected),
                    f"graph training stage {stage_id} is {actual}",
                    actual=actual,
                    expected=str(expected),
                )
            )

    max_counterparty_seconds = float(criteria.get("max_counterparty_readiness_seconds") or 0.0)
    counterparty_elapsed = (
        float(counterparty_step.get("elapsed_seconds") or 0.0)
        if isinstance(counterparty_step, dict)
        else 0.0
    )
    checks.append(
        _criterion(
            "counterparty_runtime",
            counterparty_elapsed <= max_counterparty_seconds,
            f"counterparty readiness completed in {counterparty_elapsed:.1f}s",
            actual=round(counterparty_elapsed, 3),
            expected=max_counterparty_seconds,
        )
    )

    gate_dir = Path(args.customer_demo_gate_dir)
    required_flagships = criteria.get("required_flagship_companies")
    if not isinstance(required_flagships, list):
        required_flagships = list(DEFAULT_FLAGSHIP_COMPANIES)
    flagship_results: list[dict[str, Any]] = []
    for company in required_flagships:
        slug = DEFAULT_FLAGSHIP_COMPANIES.get(str(company))
        latest = _latest_summary_json(gate_dir, prefix=slug) if slug else None
        payload = _read_json(latest) if latest else {}
        verdict = str(payload.get("verdict") or "MISSING")
        passed = verdict == "GO"
        checks.append(
            _criterion(
                f"flagship:{company}",
                passed,
                f"{company} gate verdict is {verdict}",
                actual=verdict,
                expected="GO",
            )
        )
        flagship_results.append(
            {
                "company": company,
                "verdict": verdict,
                "summary_json": str(latest) if latest else None,
            }
        )

    overall = "READY" if all(check["passed"] for check in checks) else "NOT_READY"
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "prime_time_verdict": overall,
        "criteria_path": str(Path(args.criteria)),
        "readiness_summary": str(readiness_path),
        "query_to_dossier_summary": str(query_to_dossier_path),
        "graph_training_benchmark_summary": str(graph_training_benchmark_path) if graph_training_benchmark_path else None,
        "checks": checks,
        "flagships": flagship_results,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Helios Prime-Time Readiness",
        "",
        f"- Verdict: **{summary['prime_time_verdict']}**",
        f"- Generated: {summary['generated_at']}",
        f"- Criteria: {summary['criteria_path']}",
        f"- Readiness summary: {summary['readiness_summary']}",
        f"- Query-to-dossier summary: {summary['query_to_dossier_summary']}",
        f"- Graph training benchmark summary: {summary.get('graph_training_benchmark_summary')}",
        "",
        "## Checks",
        "",
    ]
    for check in summary["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        expected = f" | expected `{check['expected']}`" if check.get("expected") is not None else ""
        actual = f" | actual `{check['actual']}`" if check.get("actual") is not None else ""
        lines.append(f"- {status} `{check['name']}`: {check['detail']}{actual}{expected}")

    lines.extend(["", "## Flagships", ""])
    for item in summary["flagships"]:
        lines.append(
            f"- {item['company']}: **{item['verdict']}**"
            + (f" | {item['summary_json']}" if item.get("summary_json") else "")
        )
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(summary: dict[str, Any], *, output_json: str = "", output_md: str = "") -> None:
    if output_json:
        path = Path(output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if output_md:
        path = Path(output_md)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(summary), encoding="utf-8")


def main() -> int:
    args = parse_args()
    summary = evaluate(args)
    write_outputs(summary, output_json=args.output_json, output_md=args.output_md)
    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"{summary['prime_time_verdict']}: prime-time readiness")
        print(f"Readiness summary: {summary['readiness_summary']}")
        for check in summary["checks"]:
            status = "PASS" if check["passed"] else "FAIL"
            print(f"- {status} {check['name']}: {check['detail']}")
    return 0 if summary["prime_time_verdict"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
