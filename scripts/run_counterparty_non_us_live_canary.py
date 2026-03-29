#!/usr/bin/env python3
"""Run the live non-US official-corroboration canary pack.

This runner is intentionally strict:
- only identity/corroboration surfaces are exercised
- env-backed live dataset URLs are required for sources that remain local-first
- it fails fast if the operator has not configured the required live source inputs
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK_FILE = ROOT / "fixtures" / "customer_demo" / "counterparty_non_us_live_canary_pack.json"
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "counterparty_non_us_live_canary"
CANARY_SCRIPT = ROOT / "scripts" / "run_counterparty_canary_pack.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the live non-US official corroboration canary pack.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--pack-file", default=str(DEFAULT_PACK_FILE))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--start-stagger-seconds", type=float, default=1.0)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _expanded_seed(entry: dict) -> dict[str, str]:
    seed = {}
    for key, value in (entry.get("seed_metadata") or {}).items():
        seed[str(key)] = os.path.expandvars(str(value)) if isinstance(value, str) else str(value)
    return seed


def _missing_required_seeds(entry: dict) -> list[str]:
    seed = _expanded_seed(entry)
    missing: list[str] = []
    for key in entry.get("required_seed_keys") or []:
        value = str(seed.get(str(key)) or "").strip()
        if not value or value.startswith("$"):
            missing.append(str(key))
    return missing


def validate_pack(path: str) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("non-US live canary pack must be a JSON list")
    missing_report: list[str] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise SystemExit("non-US live canary pack entries must be objects")
        missing = _missing_required_seeds(entry)
        if missing:
            missing_report.append(f"{entry.get('company', 'unknown company')}: {', '.join(missing)}")
    if missing_report:
        raise SystemExit(
            "missing required live seed metadata for non-US canary pack:\n- " + "\n- ".join(missing_report)
        )
    return payload


def main() -> int:
    args = parse_args()
    validate_pack(args.pack_file)

    cmd = [
        sys.executable,
        str(CANARY_SCRIPT),
        "--base-url",
        args.base_url,
        "--pack-file",
        args.pack_file,
        "--report-dir",
        args.report_dir,
        "--workers",
        str(args.workers),
        "--start-stagger-seconds",
        str(args.start_stagger_seconds),
        "--skip-ai",
        "--skip-assistant",
        "--skip-dossier-html",
        "--skip-dossier-pdf",
        "--minimum-official-corroboration",
        "strong",
        "--max-blocked-official-connectors",
        "0",
    ]
    if args.email:
        cmd.extend(["--email", args.email])
    if args.password:
        cmd.extend(["--password", args.password])
    if args.token:
        cmd.extend(["--token", args.token])
    if args.print_json:
        cmd.append("--print-json")

    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
