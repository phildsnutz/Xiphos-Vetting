#!/usr/bin/env python3
"""
Run the graph-training fixture review through the live xiphos container and
store the resulting artifact locally.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import deploy  # noqa: E402


DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "live_graph_training_fixture_review"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live graph-training fixture review.")
    parser.add_argument("--model-version", default="")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--review-all-pending", action="store_true")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _render_markdown(summary: dict) -> str:
    lines = [
        "# Live Graph Training Fixture Review",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Remote summary path: `{summary['remote_summary_path']}`",
        f"- Model version: `{summary.get('model_version')}`",
        f"- Review-all-pending: `{summary.get('review_all_pending')}`",
        "",
        "## Outcome",
        "",
        f"- Queue count: `{summary.get('queue_count', 0)}`",
        f"- Review action count: `{summary.get('review_action_count', 0)}`",
        f"- Confirmed: `{summary.get('review_result', {}).get('confirmed_count', 0)}`",
        f"- Rejected: `{summary.get('review_result', {}).get('rejected_count', 0)}`",
        "",
        "## Post Review Stats",
        "",
        f"- Reviewed links: `{summary.get('post_review_stats', {}).get('reviewed_links', 0)}`",
        f"- Pending links: `{summary.get('post_review_stats', {}).get('pending_links', 0)}`",
        f"- Confirmation rate: `{summary.get('post_review_stats', {}).get('confirmation_rate', 0.0):.2f}`",
        f"- Review coverage: `{summary.get('post_review_stats', {}).get('review_coverage_pct', 0.0):.2f}`",
    ]
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
        remote_report_dir = f"/data/reports/graph_training_fixture_review_live/{stamp}"
        remote_cmd = [
            "python3",
            "/app/scripts/review_graph_training_fixture_queue.py",
            "--report-dir",
            remote_report_dir,
            "--limit",
            str(args.limit),
            "--json-only",
        ]
        if args.model_version.strip():
            remote_cmd.extend(["--model-version", args.model_version.strip()])
        if args.review_all_pending:
            remote_cmd.append("--review-all-pending")
        command = (
            compose_prefix
            + "docker compose exec -T xiphos "
            + " ".join(shlex.quote(part) for part in remote_cmd)
        )
        code, out, err = deploy.run_cmd(ssh, command, timeout=1800)
        if code != 0:
            raise SystemExit((err or out or "live graph training fixture review failed").strip())
    finally:
        ssh.close()

    payload = json.loads(out)
    if not isinstance(payload, dict):
        raise SystemExit("live graph training fixture review did not return a JSON object")

    summary = dict(payload)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    summary["remote_summary_path"] = f"{remote_report_dir}/summary.json"
    summary["remote_markdown_path"] = f"{remote_report_dir}/summary.md"

    local_dir = Path(args.report_dir) / stamp
    local_dir.mkdir(parents=True, exist_ok=True)
    json_path = local_dir / "summary.json"
    md_path = local_dir / "summary.md"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(summary), encoding="utf-8")

    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"OK: live graph training fixture review\nSummary: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
