#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / "fixtures" / "adversarial_gym" / "graph_training_benchmark_suite_v1.json"
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "graph_training_benchmark"
DEFAULT_TRANCHE_DIRS = [
    Path("/data/reports/graph_training_tranche_live"),
    ROOT / "docs" / "reports" / "live_graph_training_tranche",
    ROOT / "docs" / "reports" / "graph_training_tranche",
]


def utc_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the Helios graph training benchmark contract.")
    parser.add_argument("--suite", default=str(DEFAULT_SUITE))
    parser.add_argument("--results-json", default="")
    parser.add_argument("--embedding-stats-json", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--tranche-summary-json", default="")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"expected JSON object in {path}")
    return payload


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit(f"expected JSON list in {path}")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _latest_nested_summary(base_dir: Path) -> Path | None:
    candidates = sorted(base_dir.glob("**/summary.json"))
    return candidates[-1] if candidates else None


def _resolve_tranche_summary(path: str) -> Path | None:
    if path:
        tranche_path = Path(path)
        return tranche_path if tranche_path.exists() else None
    for base_dir in DEFAULT_TRANCHE_DIRS:
        candidate = _latest_nested_summary(base_dir)
        if candidate is not None:
            return candidate
    return None


def _criterion(name: str, passed: bool, detail: str, *, actual: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "detail": detail,
        "actual": actual,
        "expected": expected,
    }


def _login(base_url: str, email: str, password: str, token: str) -> dict[str, str]:
    if token:
        return {"Authorization": f"Bearer {token}"}
    if not (base_url and email and password):
        return {}
    response = requests.post(
        f"{base_url.rstrip('/')}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    response.raise_for_status()
    token_value = response.json().get("token")
    if not token_value:
        raise RuntimeError("login succeeded but no token was returned")
    return {"Authorization": f"Bearer {token_value}"}


def _fetch_embedding_stats(args: argparse.Namespace) -> dict[str, Any]:
    if args.embedding_stats_json:
        return _read_json(Path(args.embedding_stats_json))
    tranche_payload = _load_tranche_summary(args.tranche_summary_json)
    tranche_embedding_stats = (
        tranche_payload.get("embedding_stats") if isinstance(tranche_payload.get("embedding_stats"), dict) else {}
    )
    tranche_review_stats = (
        tranche_payload.get("review_stats") if isinstance(tranche_payload.get("review_stats"), dict) else {}
    )
    if tranche_embedding_stats or tranche_review_stats:
        stats = dict(tranche_embedding_stats)
        if tranche_review_stats:
            stats.setdefault("review_stats", tranche_review_stats)
            stats.setdefault("predicted_links_count", int(tranche_review_stats.get("total_links") or 0))
            stats.setdefault("predicted_links_reviewed", int(tranche_review_stats.get("reviewed_links") or 0))
            stats.setdefault("predicted_links_confirmed", int(tranche_review_stats.get("confirmed_links") or 0))
            stats.setdefault(
                "predicted_links_confirmation_rate",
                float(tranche_review_stats.get("confirmation_rate") or 0.0),
            )
            stats.setdefault(
                "predicted_links_review_coverage_pct",
                float(tranche_review_stats.get("review_coverage_pct") or 0.0),
            )
            stats.setdefault(
                "predicted_links_by_edge_family",
                list(tranche_review_stats.get("by_edge_family") or []),
            )
        return stats
    if not args.base_url:
        return {}
    headers = _login(args.base_url, args.email, args.password, args.token)
    response = requests.get(
        f"{args.base_url.rstrip('/')}/api/graph/embedding-stats",
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _load_tranche_summary(path: str) -> dict[str, Any]:
    tranche_path = _resolve_tranche_summary(path)
    if tranche_path is None:
        return {}
    return _read_json(tranche_path)


def _load_results(path: str, tranche_path: str = "") -> dict[str, Any]:
    if not path:
        tranche_payload = _load_tranche_summary(tranche_path)
        stage_metrics = tranche_payload.get("stage_metrics")
        return stage_metrics if isinstance(stage_metrics, dict) else {}
    payload = _read_json(Path(path))
    stage_metrics = payload.get("stage_metrics")
    return stage_metrics if isinstance(stage_metrics, dict) else {}


def evaluate_data_foundation(suite: dict[str, Any], *, embedding_stats: dict[str, Any]) -> dict[str, Any]:
    config = suite.get("data_foundation") if isinstance(suite.get("data_foundation"), dict) else {}
    gold_config = config.get("construction_gold_set") if isinstance(config.get("construction_gold_set"), dict) else {}
    negative_config = config.get("hard_negative_set") if isinstance(config.get("hard_negative_set"), dict) else {}
    review_config = config.get("review_table") if isinstance(config.get("review_table"), dict) else {}

    gold_rows = _read_json_list(ROOT / str(gold_config.get("path")))
    negative_rows = _read_json_list(ROOT / str(negative_config.get("path")))

    gold_edge_families = sorted({str(row.get("edge_family") or "") for row in gold_rows if row.get("edge_family")})
    negative_reasons = sorted({str(row.get("rejection_reason") or "") for row in negative_rows if row.get("rejection_reason")})

    checks = [
        _criterion(
            "foundation_gold_rows",
            len(gold_rows) >= int(gold_config.get("min_rows") or 0),
            f"construction gold set has {len(gold_rows)} rows",
            actual=len(gold_rows),
            expected=int(gold_config.get("min_rows") or 0),
        ),
        _criterion(
            "foundation_gold_edge_families",
            len(gold_edge_families) >= int(gold_config.get("min_edge_families") or 0),
            f"construction gold set covers {len(gold_edge_families)} edge families",
            actual=len(gold_edge_families),
            expected=int(gold_config.get("min_edge_families") or 0),
        ),
        _criterion(
            "foundation_negative_rows",
            len(negative_rows) >= int(negative_config.get("min_rows") or 0),
            f"hard negative set has {len(negative_rows)} rows",
            actual=len(negative_rows),
            expected=int(negative_config.get("min_rows") or 0),
        ),
    ]

    for family in gold_config.get("required_edge_families") or []:
        checks.append(
            _criterion(
                f"foundation_edge_family:{family}",
                str(family) in gold_edge_families,
                f"construction gold set covers edge family {family}",
                actual=str(family) in gold_edge_families,
                expected=True,
            )
        )

    for reason in negative_config.get("required_rejection_reasons") or []:
        checks.append(
            _criterion(
                f"foundation_rejection_reason:{reason}",
                str(reason) in negative_reasons,
                f"hard negative set covers rejection reason {reason}",
                actual=str(reason) in negative_reasons,
                expected=True,
            )
        )

    reviewed_links = int(embedding_stats.get("predicted_links_reviewed") or 0)
    confirmed_links = int(embedding_stats.get("predicted_links_confirmed") or 0)
    review_stats = embedding_stats.get("review_stats") if isinstance(embedding_stats.get("review_stats"), dict) else {}
    if review_stats:
        reviewed_links = int(review_stats.get("reviewed_links") or reviewed_links)
        confirmed_links = int(review_stats.get("confirmed_links") or confirmed_links)
    checks.append(
        _criterion(
            "foundation_reviewed_links",
            reviewed_links >= int(review_config.get("min_reviewed_links") or 0),
            f"review table has {reviewed_links} reviewed predicted links",
            actual=reviewed_links,
            expected=int(review_config.get("min_reviewed_links") or 0),
        )
    )
    checks.append(
        _criterion(
            "foundation_confirmed_links",
            confirmed_links >= int(review_config.get("min_confirmed_links") or 0),
            f"review table has {confirmed_links} confirmed predicted links",
            actual=confirmed_links,
            expected=int(review_config.get("min_confirmed_links") or 0),
        )
    )

    verdict = "PASS" if all(check["passed"] for check in checks) else "FAIL"
    return {
        "verdict": verdict,
        "construction_gold_rows": len(gold_rows),
        "construction_gold_edge_families": gold_edge_families,
        "hard_negative_rows": len(negative_rows),
        "hard_negative_rejection_reasons": negative_reasons,
        "reviewed_predicted_links": reviewed_links,
        "confirmed_predicted_links": confirmed_links,
        "checks": checks,
    }


def _evaluate_metric(metric_name: str, expected: Any, actual_metrics: dict[str, Any]) -> dict[str, Any]:
    if metric_name.endswith("_min"):
        actual_key = metric_name[:-4]
        actual_value = actual_metrics.get(actual_key)
        passed = actual_value is not None and float(actual_value) >= float(expected)
        detail = f"{actual_key} is {actual_value}"
        return _criterion(metric_name, passed, detail, actual=actual_value, expected=expected)
    if metric_name.endswith("_max"):
        actual_key = metric_name[:-4]
        actual_value = actual_metrics.get(actual_key)
        passed = actual_value is not None and float(actual_value) <= float(expected)
        detail = f"{actual_key} is {actual_value}"
        return _criterion(metric_name, passed, detail, actual=actual_value, expected=expected)
    actual_value = actual_metrics.get(metric_name)
    passed = actual_value == expected
    detail = f"{metric_name} is {actual_value}"
    return _criterion(metric_name, passed, detail, actual=actual_value, expected=expected)


def evaluate_training_stack(suite: dict[str, Any], *, stage_metrics: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for stage in suite.get("training_stack") or []:
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("stage_id") or "")
        metrics_cfg = stage.get("metrics") if isinstance(stage.get("metrics"), dict) else {}
        actual_metrics = stage_metrics.get(stage_id) if isinstance(stage_metrics.get(stage_id), dict) else {}
        checks = [_evaluate_metric(metric_name, expected, actual_metrics) for metric_name, expected in metrics_cfg.items()]
        verdict = "PASS" if checks and all(check["passed"] for check in checks) else "FAIL"
        results.append(
            {
                "stage_id": stage_id,
                "objective": str(stage.get("objective") or ""),
                "datasets": list(stage.get("datasets") or []),
                "actual_metrics": actual_metrics,
                "checks": checks,
                "verdict": verdict,
            }
        )
    return results


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    suite = _read_json(Path(args.suite))
    tranche_path = _resolve_tranche_summary(args.tranche_summary_json)
    tranche_summary = _read_json(tranche_path) if tranche_path is not None else {}
    embedding_stats = _fetch_embedding_stats(args)
    stage_metrics = _load_results(args.results_json, args.tranche_summary_json)

    data_foundation = evaluate_data_foundation(suite, embedding_stats=embedding_stats)
    stage_results = evaluate_training_stack(suite, stage_metrics=stage_metrics)
    overall_verdict = "PASS" if data_foundation["verdict"] == "PASS" and stage_results and all(stage["verdict"] == "PASS" for stage in stage_results) else "FAIL"

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "suite_path": str(Path(args.suite)),
        "suite_version": str(suite.get("suite_version") or "unknown"),
        "overall_verdict": overall_verdict,
        "data_foundation": data_foundation,
        "stage_results": stage_results,
        "stage_metrics": stage_metrics,
        "embedding_stats": embedding_stats,
        "tranche_summary": str(tranche_path) if tranche_path else None,
        "tranche_generated_at": tranche_summary.get("generated_at"),
        "results_json": args.results_json or None,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Helios Graph Training Benchmark",
        "",
        f"- Verdict: **{summary['overall_verdict']}**",
        f"- Generated: {summary['generated_at']}",
        f"- Suite: {summary['suite_path']}",
        f"- Version: `{summary['suite_version']}`",
        "",
        "## Data Foundation",
        "",
        f"- Verdict: **{summary['data_foundation']['verdict']}**",
        f"- Gold rows: `{summary['data_foundation']['construction_gold_rows']}`",
        f"- Hard negatives: `{summary['data_foundation']['hard_negative_rows']}`",
        f"- Reviewed predicted links: `{summary['data_foundation']['reviewed_predicted_links']}`",
        f"- Confirmed predicted links: `{summary['data_foundation']['confirmed_predicted_links']}`",
        "",
    ]
    for check in summary["data_foundation"]["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        lines.append(f"- {status} `{check['name']}`: {check['detail']} | actual `{check['actual']}` | expected `{check['expected']}`")

    lines.extend(["", "## Training Stages", ""])
    for stage in summary["stage_results"]:
        lines.append(f"### {stage['stage_id']}")
        lines.append("")
        lines.append(f"- Verdict: **{stage['verdict']}**")
        if stage["actual_metrics"]:
            lines.append(f"- Actual metrics: `{stage['actual_metrics']}`")
        else:
            lines.append("- Actual metrics: `missing`")
        for check in stage["checks"]:
            status = "PASS" if check["passed"] else "FAIL"
            lines.append(f"- {status} `{check['name']}`: {check['detail']} | actual `{check['actual']}` | expected `{check['expected']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(summary: dict[str, Any], *, output_json: str, output_md: str, report_dir: str) -> tuple[str, str]:
    if output_json and output_md:
        json_path = Path(output_json)
        md_path = Path(output_md)
    else:
        stamp = utc_slug()
        base = Path(report_dir) / stamp
        json_path = base / "summary.json"
        md_path = base / "summary.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    return str(json_path), str(md_path)


def main() -> int:
    args = parse_args()
    summary = evaluate(args)
    json_path, md_path = write_outputs(summary, output_json=args.output_json, output_md=args.output_md, report_dir=args.report_dir)
    summary["report_json"] = json_path
    summary["report_md"] = md_path
    Path(json_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"{summary['overall_verdict']}: graph training benchmark")
        print(f"Summary: {json_path}")
    return 0 if summary["overall_verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
