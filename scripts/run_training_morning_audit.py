#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests


def utc_now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def login(base_url: str, email: str, password: str) -> dict[str, str]:
    response = requests.post(
        f"{base_url.rstrip('/')}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def fetch_json(base_url: str, path: str, headers: dict[str, str]) -> dict | list:
    response = requests.get(f"{base_url.rstrip('/')}{path}", headers=headers, timeout=120)
    response.raise_for_status()
    return response.json()


def fetch_live_snapshot(base_url: str, email: str, password: str) -> dict:
    headers = login(base_url, email, password)
    portfolio = fetch_json(base_url, "/api/portfolio/snapshot", headers)
    graph = fetch_json(base_url, "/api/graph/stats", headers)
    case_payload = fetch_json(base_url, "/api/cases?limit=5000", headers)
    cases = case_payload if isinstance(case_payload, list) else case_payload.get("cases", case_payload.get("vendors", []))
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "portfolio_snapshot": portfolio,
        "graph_stats": graph,
        "case_count": len(cases),
    }


def diff_number(before: int | float | None, after: int | float | None) -> int | float | None:
    if before is None or after is None:
        return None
    return round(after - before, 3) if isinstance(after, float) or isinstance(before, float) else after - before


def summarize_results(results_file: Path | None) -> dict:
    if not results_file or not results_file.exists():
        return {}
    rows = json.loads(results_file.read_text())
    status_counts = Counter(row.get("status", "unknown") for row in rows)
    mode_counts = Counter(row.get("mode", "unknown") for row in rows if row.get("status") == "ok")
    bucket_counts = Counter(row.get("bucket", "unknown") for row in rows if row.get("status") == "ok")
    risk_counts = Counter(row.get("overall_risk", "unknown") for row in rows if row.get("status") == "ok")
    created_names = [row["name"] for row in rows if row.get("mode") == "create" and row.get("status") == "ok"]
    replayed_names = [row["name"] for row in rows if row.get("mode", "").startswith("replay") and row.get("status") == "ok"]
    return {
        "results_file": str(results_file),
        "row_count": len(rows),
        "status_counts": dict(status_counts),
        "mode_counts": dict(mode_counts),
        "bucket_counts": dict(bucket_counts),
        "risk_counts": dict(risk_counts),
        "created_count": len(created_names),
        "replayed_count": len(replayed_names),
        "created_sample": created_names[:15],
        "replayed_sample": replayed_names[:15],
    }


def render_markdown(baseline: dict, current: dict, run_summary: dict) -> str:
    base_portfolio = baseline["portfolio_snapshot"]
    curr_portfolio = current["portfolio_snapshot"]
    base_graph = baseline["graph_stats"]
    curr_graph = current["graph_stats"]

    def get(d: dict, key: str):
        return d.get(key)

    lines = [
        "# Helios Overnight Training Run Audit",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Delta",
        "",
        f"- Vendors: `{get(base_portfolio, 'total_vendors')}` -> `{get(curr_portfolio, 'total_vendors')}` "
        f"(`{diff_number(get(base_portfolio, 'total_vendors'), get(curr_portfolio, 'total_vendors')):+}`)",
        f"- Case count: `{baseline.get('case_count')}` -> `{current.get('case_count')}` "
        f"(`{diff_number(baseline.get('case_count'), current.get('case_count')):+}`)",
        f"- Linked vendors: `{get(base_graph, 'linked_vendors')}` -> `{get(curr_graph, 'linked_vendors')}` "
        f"(`{diff_number(get(base_graph, 'linked_vendors'), get(curr_graph, 'linked_vendors')):+}`)",
        f"- Graph entities: `{get(base_graph, 'entity_count')}` -> `{get(curr_graph, 'entity_count')}` "
        f"(`{diff_number(get(base_graph, 'entity_count'), get(curr_graph, 'entity_count')):+}`)",
        f"- Graph relationships: `{get(base_graph, 'relationship_count')}` -> `{get(curr_graph, 'relationship_count')}` "
        f"(`{diff_number(get(base_graph, 'relationship_count'), get(curr_graph, 'relationship_count')):+}`)",
        "",
        "## Tier Distribution",
        "",
    ]

    tier_keys = sorted(set(base_portfolio.get("tier_distribution", {})) | set(curr_portfolio.get("tier_distribution", {})))
    for key in tier_keys:
        before = base_portfolio.get("tier_distribution", {}).get(key, 0)
        after = curr_portfolio.get("tier_distribution", {}).get(key, 0)
        lines.append(f"- `{key}`: `{before}` -> `{after}` (`{after - before:+}`)")

    if run_summary:
        lines.extend(
            [
                "",
                "## Run Summary",
                "",
                f"- Results file: `{run_summary.get('results_file')}`",
                f"- Rows recorded: `{run_summary.get('row_count', 0)}`",
                f"- Created OK: `{run_summary.get('created_count', 0)}`",
                f"- Replayed OK: `{run_summary.get('replayed_count', 0)}`",
                f"- Status counts: `{run_summary.get('status_counts', {})}`",
                f"- Risk counts: `{run_summary.get('risk_counts', {})}`",
                "",
                "## Samples",
                "",
                f"- Created sample: `{run_summary.get('created_sample', [])}`",
                f"- Replayed sample: `{run_summary.get('replayed_sample', [])}`",
            ]
        )

    return "\n".join(lines) + "\n"


def command_capture_baseline(args: argparse.Namespace) -> int:
    snapshot = fetch_live_snapshot(args.base_url, args.email, args.password)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2))
    print(f"Baseline written to {args.output}")
    return 0


def command_compare(args: argparse.Namespace) -> int:
    baseline = json.loads(args.baseline.read_text())
    current = fetch_live_snapshot(args.base_url, args.email, args.password)
    run_summary = summarize_results(args.results_file)
    report_json = {
        "baseline_file": str(args.baseline),
        "baseline": baseline,
        "current": current,
        "run_summary": run_summary,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report_json, indent=2))
    args.output_md.write_text(render_markdown(baseline, current, run_summary))
    print(f"JSON report: {args.output_json}")
    print(f"Markdown report: {args.output_md}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture and compare hosted Helios overnight training metrics")
    parser.add_argument("--base-url", default=os.environ.get("HELIOS_BASE_URL") or "http://127.0.0.1:8080")
    parser.add_argument("--email", default=os.environ.get("HELIOS_LOGIN_EMAIL") or os.environ.get("HELIOS_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("HELIOS_LOGIN_PASSWORD") or os.environ.get("HELIOS_PASSWORD"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture-baseline")
    capture.add_argument("--output", type=Path, default=Path("docs/reports") / f"helios-training-baseline-{utc_now_slug()}.json")
    capture.set_defaults(func=command_capture_baseline)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--results-file", type=Path)
    compare.add_argument("--output-json", type=Path, default=Path("docs/reports") / f"helios-training-audit-{utc_now_slug()}.json")
    compare.add_argument("--output-md", type=Path, default=Path("docs/reports") / f"HELIOS_TRAINING_AUDIT_{utc_now_slug()}.md")
    compare.set_defaults(func=command_compare)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.email or not args.password:
        raise SystemExit("Set HELIOS_EMAIL/HELIOS_PASSWORD or pass --email/--password")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
