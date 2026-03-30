#!/usr/bin/env python3
"""Run the query-to-dossier gauntlet against a live authenticated Helios instance."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GAUNTLET_SCRIPT = ROOT / "scripts" / "run_query_to_dossier_gauntlet.py"
DEFAULT_SPEC_FILE = ROOT / "fixtures" / "customer_demo" / "query_to_dossier_canary_pack.json"
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "live_query_to_dossier_canary"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the hosted query-to-dossier canary.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--spec-file", default=str(DEFAULT_SPEC_FILE))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--require-neo4j", action="store_true", default=True)
    parser.add_argument("--allow-missing-neo4j", dest="require_neo4j", action="store_false")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _decode_json_from_stdout(stdout: str) -> dict[str, Any] | list[Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def probe_neo4j_health(base_url: str) -> dict[str, Any]:
    req = urllib.request.Request(f"{base_url.rstrip('/')}/api/neo4j/health", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
            payload = json.loads(body.decode("utf-8")) if body else {}
            return {
                "http_status": resp.status,
                "neo4j_available": bool(payload.get("neo4j_available")),
                "status": str(payload.get("status") or ""),
                "timestamp": str(payload.get("timestamp") or ""),
            }
    except Exception as exc:
        return {
            "http_status": 0,
            "neo4j_available": False,
            "status": "probe_failed",
            "timestamp": "",
            "error": str(exc),
        }


def _persist_augmented_summary(payload: dict[str, Any]) -> None:
    report_json = payload.get("report_json")
    if report_json:
        json_path = Path(str(report_json))
        if json_path.exists():
            json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    report_md = payload.get("report_md")
    neo4j = payload.get("neo4j_summary") if isinstance(payload.get("neo4j_summary"), dict) else {}
    if report_md and neo4j:
        md_path = Path(str(report_md))
        if md_path.exists():
            extra = [
                "",
                "## Neo4j",
                "",
                f"- Required: `{'yes' if payload.get('require_neo4j') else 'no'}`",
                f"- Available: `{'yes' if neo4j.get('neo4j_available') else 'no'}`",
                f"- Status: `{neo4j.get('status', '')}`",
            ]
            md_path.write_text(md_path.read_text(encoding="utf-8").rstrip() + "\n" + "\n".join(extra) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    cmd = [
        sys.executable,
        str(GAUNTLET_SCRIPT),
        "--mode",
        "local-auth",
        "--base-url",
        args.base_url,
        "--spec-file",
        args.spec_file,
        "--report-dir",
        args.report_dir,
        "--print-json",
    ]
    if args.token:
        cmd.extend(["--token", args.token])
    else:
        if args.email:
            cmd.extend(["--email", args.email])
        if args.password:
            cmd.extend(["--password", args.password])

    proc = subprocess.run(cmd, text=True, capture_output=True, cwd=ROOT)
    payload = _decode_json_from_stdout(proc.stdout)
    if not isinstance(payload, dict):
        detail = proc.stderr.strip() or proc.stdout.strip() or "live query-to-dossier canary did not emit JSON"
        raise RuntimeError(detail)
    neo4j_summary = probe_neo4j_health(args.base_url)
    payload["neo4j_summary"] = neo4j_summary
    payload["require_neo4j"] = bool(args.require_neo4j)
    if args.require_neo4j and not bool(neo4j_summary.get("neo4j_available")):
        payload["overall_verdict"] = "FAIL"
        failures = payload.get("failures")
        if not isinstance(failures, list):
            failures = []
            payload["failures"] = failures
        failures.append({"flow_name": "neo4j", "error": "neo4j health unavailable"})
    _persist_augmented_summary(payload)
    if args.print_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Wrote {payload.get('report_md', '')}")
        print(f"Wrote {payload.get('report_json', '')}")
    if args.require_neo4j and not bool(neo4j_summary.get("neo4j_available")):
        return 1
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
