#!/usr/bin/env python3
"""Run the query-to-dossier gauntlet against a live authenticated Helios instance."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
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
    if args.print_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Wrote {payload.get('report_md', '')}")
        print(f"Wrote {payload.get('report_json', '')}")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
