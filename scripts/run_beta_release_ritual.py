#!/usr/bin/env python3
"""Run the minimal beta release ritual against a target Helios instance."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "beta_release_ritual"
CURRENT_PRODUCT_SCRIPT = ROOT / "scripts" / "run_current_product_stress_harness.py"
QUERY_TO_DOSSIER_SCRIPT = ROOT / "scripts" / "run_live_query_to_dossier_canary.py"
VEHICLE_INTEL_SCRIPT = ROOT / "scripts" / "run_vehicle_intelligence_canary.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the minimal Helios beta release ritual.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _decode_json(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _run_json_script(script: Path, args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(script),
        "--base-url",
        args.base_url,
        "--print-json",
    ]
    if args.token:
        command.extend(["--token", args.token])
    elif args.email and args.password:
        command.extend(["--email", args.email, "--password", args.password])
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    payload = _decode_json(completed.stdout)
    if payload is None:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"{script.name} did not emit JSON"
        raise RuntimeError(detail)
    payload["exit_code"] = completed.returncode
    payload["script"] = script.name
    return payload


def _write_report(args: argparse.Namespace, results: list[dict[str, Any]]) -> tuple[Path, Path, str]:
    report_root = Path(args.report_dir)
    report_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    report_dir = report_root / stamp
    report_dir.mkdir(parents=True, exist_ok=True)

    overall_verdict = "PASS" if all(str(result.get("overall_verdict") or "") == "PASS" and int(result.get("exit_code") or 0) == 0 for result in results) else "FAIL"
    payload = {
        "overall_verdict": overall_verdict,
        "generated_at": datetime.now().isoformat(),
        "base_url": args.base_url,
        "results": results,
    }
    json_path = report_dir / "summary.json"
    md_path = report_dir / "summary.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Beta Release Ritual",
        "",
        f"- Overall verdict: `{overall_verdict}`",
        f"- Base URL: `{args.base_url}`",
        "",
        "## Gates",
        "",
    ]
    for result in results:
        lines.append(
            f"- `{result.get('script')}`: verdict `{result.get('overall_verdict', 'unknown')}` exit `{result.get('exit_code', -1)}`"
        )
        if result.get("report_md"):
            lines.append(f"  - report: `{result['report_md']}`")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path, overall_verdict


def main() -> int:
    args = parse_args()
    results = [
        _run_json_script(CURRENT_PRODUCT_SCRIPT, args),
        _run_json_script(QUERY_TO_DOSSIER_SCRIPT, args),
        _run_json_script(VEHICLE_INTEL_SCRIPT, args),
    ]
    md_path, json_path, overall_verdict = _write_report(args, results)
    payload = {
        "overall_verdict": overall_verdict,
        "report_md": str(md_path),
        "report_json": str(json_path),
        "results": results,
    }
    if args.print_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Wrote {md_path}")
        print(f"Wrote {json_path}")
    return 0 if overall_verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
