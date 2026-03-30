#!/usr/bin/env python3
"""
Run the graph-training tranche through the live xiphos container and store
the resulting artifact locally under docs/reports/.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import deploy  # noqa: E402


DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "live_graph_training_tranche"
DEFAULT_READINESS_DIR = ROOT / "docs" / "reports" / "readiness"
DEFAULT_BENCHMARK_DIR = ROOT / "docs" / "reports" / "graph_training_benchmark"
DEFAULT_NEO4J_GLOB = "neo4j_graph_drift_audit*"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the live Helios graph-training tranche.")
    parser.add_argument("--top-entities", type=int, default=4)
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--skip-queue", action="store_true")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _latest_nested_summary(base_dir: Path) -> Path | None:
    candidates = sorted(base_dir.glob("*/summary.json"))
    return candidates[-1] if candidates else None


def _latest_neo4j_report() -> Path | None:
    base = ROOT / "docs" / "reports"
    candidates = sorted(base.glob(f"{DEFAULT_NEO4J_GLOB}/neo4j-graph-drift-audit-*.json"))
    if candidates:
        return candidates[-1]
    candidates = sorted(base.glob(f"{DEFAULT_NEO4J_GLOB}/**/*.json"))
    return candidates[-1] if candidates else None


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _summary_verdict(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("overall_verdict", "prime_time_verdict", "verdict"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _render_markdown(summary: dict[str, Any]) -> str:
    missing_edge_metrics = (
        summary.get("stage_metrics", {}).get("missing_edge_recovery", {})
        if isinstance(summary.get("stage_metrics"), dict)
        else {}
    )
    lines = [
        "# Live Helios Graph Training Tranche",
        "",
        f"Generated: {summary['generated_at']}",
        f"Remote summary path: `{summary['remote_summary_path']}`",
        f"Remote markdown path: `{summary['remote_markdown_path']}`",
        "",
        "## Runtime",
        "",
        f"- Prime-time readiness: `{summary['readiness'].get('overall_verdict', 'UNKNOWN')}`",
        f"- Neo4j drift audit: `{summary['neo4j'].get('overall_verdict', 'UNKNOWN')}`",
        f"- Graph benchmark: `{summary['benchmark'].get('overall_verdict', 'UNKNOWN')}`",
        "",
        "## Review Loop",
        "",
        f"- Total predicted links: `{summary['review_stats'].get('total_links', 0)}`",
        f"- Reviewed links: `{summary['review_stats'].get('reviewed_links', 0)}`",
        f"- Confirmed links: `{summary['review_stats'].get('confirmed_links', 0)}`",
        f"- Confirmation rate: `{summary['review_stats'].get('confirmation_rate', 0.0):.2f}`",
        f"- Review coverage: `{summary['review_stats'].get('review_coverage_pct', 0.0):.2f}`",
        "",
        "## Missing Edge Recovery",
        "",
        f"- Pending links: `{summary['review_stats'].get('pending_links', 0)}`",
        f"- Unsupported promoted edge rate: `{summary['review_stats'].get('unsupported_promoted_edge_rate', 0.0):.2f}`",
        f"- Novel edge yield: `{missing_edge_metrics.get('novel_edge_yield', 0.0):.2f}`",
        f"- Median pending age (hours): `{missing_edge_metrics.get('median_pending_age_hours', 0.0):.2f}`",
        f"- Stale pending >24h: `{missing_edge_metrics.get('stale_pending_24h', 0)}`",
        f"- Stale pending >7d: `{missing_edge_metrics.get('stale_pending_7d', 0)}`",
        "",
        "## Queue Runs",
        "",
    ]
    for run in summary.get("queue_runs", []):
        lines.append(
            f"- {run.get('entity_name')} `{run.get('entity_id')}` queued `{run.get('queued_count', 0)}` new, reused `{run.get('existing_count', 0)}`, total `{run.get('count', 0)}`"
        )
    lines.extend(["", "## Stage Progress", ""])
    for stage in summary.get("stage_progress", []):
        lines.append(
            f"- {stage['stage_id']}: status `{stage['status']}`, benchmark `{stage['benchmark_verdict']}`. {stage['notes']}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    ssh = deploy.ssh_connect()
    try:
        secret_key = deploy.resolve_secret_key(ssh)
        compose_prefix = (
            f"cd {shlex.quote(deploy.REMOTE_DIR)} && "
            f"export XIPHOS_SECRET_KEY={shlex.quote(secret_key)} && "
        )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        remote_report_dir = f"/data/reports/graph_training_tranche_live/{stamp}"
        remote_cmd = [
            "python3",
            "/app/scripts/run_graph_training_tranche.py",
            "--top-entities",
            str(args.top_entities),
            "--top-k",
            str(args.top_k),
            "--report-dir",
            remote_report_dir,
            "--json-only",
        ]
        if args.skip_train:
            remote_cmd.append("--skip-train")
        if args.skip_queue:
            remote_cmd.append("--skip-queue")
        command = (
            compose_prefix
            + "docker compose exec -T xiphos "
            + " ".join(shlex.quote(part) for part in remote_cmd)
        )
        code, out, err = deploy.run_cmd(ssh, command, timeout=1800)
        if code != 0:
            raise SystemExit((err or out or "live graph training tranche failed").strip())
    finally:
        ssh.close()

    payload = json.loads(out)
    if not isinstance(payload, dict):
        raise SystemExit("live graph training tranche did not return a JSON object")

    readiness_path = _latest_nested_summary(DEFAULT_READINESS_DIR)
    benchmark_path = _latest_nested_summary(DEFAULT_BENCHMARK_DIR)
    neo4j_path = _latest_neo4j_report()
    readiness = _read_json(readiness_path) or {}
    benchmark = _read_json(benchmark_path) or {}
    neo4j = _read_json(neo4j_path) or {}

    summary = dict(payload)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    summary["remote_summary_path"] = f"{remote_report_dir}/summary.json"
    summary["remote_markdown_path"] = f"{remote_report_dir}/summary.md"
    summary["readiness"] = {
        "overall_verdict": _summary_verdict(readiness),
        "path": str(readiness_path) if readiness_path else None,
    }
    summary["neo4j"] = {
        "overall_verdict": _summary_verdict(neo4j),
        "path": str(neo4j_path) if neo4j_path else None,
    }
    summary["benchmark"] = {
        "overall_verdict": _summary_verdict(benchmark),
        "path": str(benchmark_path) if benchmark_path else None,
        "data_foundation_verdict": (benchmark.get("data_foundation") or {}).get("verdict")
        if isinstance(benchmark.get("data_foundation"), dict)
        else None,
    }

    local_dir = Path(args.report_dir) / stamp
    local_dir.mkdir(parents=True, exist_ok=True)
    json_path = local_dir / "summary.json"
    md_path = local_dir / "summary.md"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(summary), encoding="utf-8")

    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"OK: live graph training tranche\nSummary: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
