#!/usr/bin/env python3
"""
Run the Helios multi-lane readiness workflow.

This is the release-engineering gate that aggregates:
  - Counterparty readiness and stabilization
  - Export fixed canary packs
  - Supply Chain Assurance fixed canary packs

The output is a single readiness verdict for the product, not a one-lane
diagnostic.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "helios_readiness"
DEFAULT_LANE_PACK = ROOT / "fixtures" / "customer_demo" / "lane_canary_pack.json"


@dataclass
class StepResult:
    name: str
    pillar: str
    verdict: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    artifact_json: str | None = None
    artifact_md: str | None = None
    payload: dict[str, Any] | None = None
    elapsed_seconds: float = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Helios multi-lane readiness workflow.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--lane-pack", default=str(DEFAULT_LANE_PACK))
    parser.add_argument("--skip-counterparty", action="store_true")
    parser.add_argument("--skip-export", action="store_true")
    parser.add_argument("--skip-assurance", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--company", action="append", default=[])
    parser.add_argument("--country", default="US")
    parser.add_argument("--program", default="dod_unclassified")
    parser.add_argument("--profile", default="defense_acquisition")
    parser.add_argument("--include-ai", action="store_true", default=True)
    parser.add_argument("--skip-ai", dest="include_ai", action="store_false")
    parser.add_argument("--ai-readiness-mode", choices=("full", "surface"), default="surface")
    parser.add_argument("--check-assistant", action="store_true", default=True)
    parser.add_argument("--skip-assistant", dest="check_assistant", action="store_false")
    parser.add_argument("--max-enrich-seconds", type=int, default=90)
    parser.add_argument("--max-dossier-seconds", type=int, default=60)
    parser.add_argument("--max-pdf-seconds", type=int, default=60)
    parser.add_argument("--max-ai-seconds", type=int, default=90)
    parser.add_argument("--max-warnings", type=int, default=2)
    parser.add_argument(
        "--minimum-official-corroboration",
        choices=("missing", "public_only", "partial", "strong"),
        default="strong",
    )
    parser.add_argument("--max-blocked-official-connectors", type=int, default=3)
    parser.add_argument("--wait-for-ready-seconds", type=int, default=120)
    parser.add_argument("--step-timeout-seconds", type=int, default=1800)
    parser.add_argument("--counterparty-step-timeout-seconds", type=int, default=600)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _common_auth_args(args: argparse.Namespace) -> list[str]:
    auth: list[str] = ["--base-url", args.base_url]
    if args.token:
        auth.extend(["--token", args.token])
    else:
        if args.email:
            auth.extend(["--email", args.email])
        if args.password:
            auth.extend(["--password", args.password])
    return auth


def _decode_json_from_stdout(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _latest_summary_json(base_dir: Path) -> Path | None:
    candidates = sorted(base_dir.rglob("summary.json"))
    return candidates[-1] if candidates else None


def _latest_new_summary_json(base_dir: Path, existing: set[Path]) -> Path | None:
    candidates = sorted(path for path in base_dir.rglob("summary.json") if path not in existing)
    return candidates[-1] if candidates else None


def _coerce_subprocess_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def load_lane_pack(path: str) -> list[dict[str, str]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("Lane canary pack must contain a JSON list")
    steps: list[dict[str, str]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise SystemExit("Each lane canary entry must be an object")
        name = str(entry.get("name") or "").strip()
        pillar = str(entry.get("pillar") or "").strip()
        fixture = str(entry.get("fixture") or "").strip()
        if not name or not pillar or not fixture:
            raise SystemExit("Each lane canary entry needs name, pillar, and fixture")
        steps.append({"name": name, "pillar": pillar, "fixture": fixture})
    return steps


def _counterparty_enabled(args: argparse.Namespace) -> bool:
    return not args.skip_counterparty


def _gauntlet_enabled(args: argparse.Namespace, pillar: str) -> bool:
    if pillar == "export":
        return not args.skip_export
    if pillar == "supply_chain_assurance":
        return not args.skip_assurance
    return True


def _verdict_from_returncode(returncode: int, *, counterparty: bool = False) -> str:
    if counterparty:
        if returncode == 0:
            return "GO"
        if returncode == 2:
            return "CAUTION"
        return "NO_GO"
    return "GO" if returncode == 0 else "NO_GO"


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def build_counterparty_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_counterparty_readiness_report.py"),
        "--report-dir",
        str(Path(args.report_dir) / "counterparty"),
        "--country",
        args.country,
        "--program",
        args.program,
        "--profile",
        args.profile,
        "--max-enrich-seconds",
        str(args.max_enrich_seconds),
        "--max-dossier-seconds",
        str(args.max_dossier_seconds),
        "--max-pdf-seconds",
        str(args.max_pdf_seconds),
        "--max-ai-seconds",
        str(args.max_ai_seconds),
        "--max-warnings",
        str(args.max_warnings),
        "--minimum-official-corroboration",
        args.minimum_official_corroboration,
        "--max-blocked-official-connectors",
        str(args.max_blocked_official_connectors),
        "--wait-for-ready-seconds",
        str(args.wait_for_ready_seconds),
        "--step-timeout-seconds",
        str(args.counterparty_step_timeout_seconds),
        "--print-json",
        *_common_auth_args(args),
    ]
    if not args.include_ai:
        command.append("--skip-ai")
    command.extend(["--ai-readiness-mode", args.ai_readiness_mode])
    if not args.check_assistant:
        command.append("--skip-assistant")
    for company in args.company:
        command.extend(["--company", company])
    return command


def build_lane_command(
    name: str,
    pillar: str,
    fixture: str,
    report_dir: Path,
) -> tuple[list[str], Path, Path]:
    safe_name = name.replace("/", "-")
    output_json = report_dir / pillar / f"{safe_name}.json"
    output_md = report_dir / pillar / f"{safe_name}.md"
    output_json.parent.mkdir(parents=True, exist_ok=True)

    if pillar == "export":
        script = ROOT / "scripts" / "run_export_ai_gauntlet.py"
    elif pillar == "supply_chain_assurance":
        script = ROOT / "scripts" / "run_supply_chain_assurance_gauntlet.py"
    else:
        raise SystemExit(f"Unsupported readiness pillar: {pillar}")

    command = [
        sys.executable,
        str(script),
        "--fixture",
        str((ROOT / fixture).resolve()),
        "--output-json",
        str(output_json),
        "--output-md",
        str(output_md),
    ]
    return command, output_json, output_md


def run_step(
    name: str,
    pillar: str,
    command: list[str],
    *,
    counterparty: bool = False,
    artifact_json: Path | None = None,
    artifact_md: Path | None = None,
    artifact_dir: Path | None = None,
    timeout_seconds: int | None = None,
) -> StepResult:
    started = time.time()
    existing_artifacts = set(artifact_dir.rglob("summary.json")) if artifact_dir and artifact_dir.exists() else set()
    _progress(f"[helios readiness] starting {name}")
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=timeout_seconds if timeout_seconds and timeout_seconds > 0 else None,
        )
        returncode = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = _coerce_subprocess_text(exc.stdout)
        stderr = _coerce_subprocess_text(exc.stderr).strip()
        timeout_note = f"step timed out after {int(timeout_seconds or 0)}s"
        stderr = f"{stderr}\n{timeout_note}".strip() if stderr else timeout_note
    elapsed = time.time() - started
    payload = _decode_json_from_stdout(stdout)
    resolved_artifact_json = str(artifact_json) if artifact_json else None
    resolved_artifact_md = str(artifact_md) if artifact_md else None

    if payload is None and artifact_dir is not None:
        latest_summary = _latest_new_summary_json(artifact_dir, existing_artifacts)
        if latest_summary and latest_summary.exists():
            resolved_artifact_json = str(latest_summary)
            resolved_artifact_md = str(latest_summary.with_suffix(".md"))
            payload = json.loads(latest_summary.read_text(encoding="utf-8"))

    if payload is None and artifact_json and artifact_json.exists():
        payload = json.loads(artifact_json.read_text(encoding="utf-8"))

    if not resolved_artifact_json and isinstance(payload, dict):
        resolved_artifact_json = payload.get("report_json") or payload.get("artifact_json")
        resolved_artifact_md = payload.get("report_md") or payload.get("artifact_md") or resolved_artifact_md
    _progress(
        f"[helios readiness] finished {name}: "
        f"{_verdict_from_returncode(returncode, counterparty=counterparty)} ({elapsed:.1f}s)"
    )

    return StepResult(
        name=name,
        pillar=pillar,
        verdict=_verdict_from_returncode(returncode, counterparty=counterparty),
        command=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        artifact_json=resolved_artifact_json,
        artifact_md=resolved_artifact_md,
        payload=payload,
        elapsed_seconds=elapsed,
    )


def overall_verdict(results: list[StepResult]) -> str:
    verdicts = {result.verdict for result in results}
    if "NO_GO" in verdicts:
        return "NO_GO"
    if "CAUTION" in verdicts:
        return "CAUTION"
    return "GO"


def write_report(output_dir: Path, results: list[StepResult]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    verdict = overall_verdict(results)
    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "overall_verdict": verdict,
        "verdict": verdict,
        "pillars": sorted({result.pillar for result in results}),
        "steps": [
            {
                "name": result.name,
                "pillar": result.pillar,
                "verdict": result.verdict,
                "returncode": result.returncode,
                "command": result.command,
                "artifact_json": result.artifact_json,
                "artifact_md": result.artifact_md,
                "elapsed_seconds": round(result.elapsed_seconds, 3),
                "stdout": result.stdout,
                "stderr": result.stderr,
                "payload": result.payload,
            }
            for result in results
        ],
    }

    json_path = output_dir / "summary.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Helios Readiness Report",
        "",
        f"- Overall verdict: **{summary['overall_verdict']}**",
        f"- Generated: {summary['generated_at']}",
        f"- Pillars: {', '.join(summary['pillars'])}",
        "",
        "## Steps",
        "",
    ]
    for result in results:
        lines.extend(
            [
                f"### {result.name}",
                "",
                f"- Pillar: `{result.pillar}`",
                f"- Verdict: **{result.verdict}**",
                f"- Return code: `{result.returncode}`",
                f"- Command: `{ ' '.join(result.command) }`",
            ]
        )
        if result.artifact_md:
            lines.append(f"- Report: `{result.artifact_md}`")
        if result.artifact_json:
            lines.append(f"- JSON: `{result.artifact_json}`")
        if isinstance(result.payload, dict):
            if "overall_verdict" in result.payload:
                lines.append(f"- Payload verdict: **{result.payload['overall_verdict']}**")
            elif "pass_rate" in result.payload:
                lines.append(f"- Pass rate: `{float(result.payload['pass_rate']) * 100:.1f}%`")
            elif "passed_count" in result.payload and "scenario_count" in result.payload:
                lines.append(
                    f"- Passed: `{result.payload['passed_count']}` / `{result.payload['scenario_count']}`"
                )
        if result.stderr.strip():
            lines.append(f"- stderr: `{result.stderr.strip()}`")
        lines.append("")

    md_path = output_dir / "summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path


def main() -> int:
    args = parse_args()
    lane_pack = load_lane_pack(args.lane_pack)
    results: list[StepResult] = []

    if _counterparty_enabled(args):
        if not args.token and not (args.email and args.password):
            raise SystemExit("counterparty readiness requires --token or --email/--password")
        results.append(
            run_step(
                "counterparty",
                "counterparty",
                build_counterparty_command(args),
                counterparty=True,
                artifact_dir=Path(args.report_dir) / "counterparty",
                timeout_seconds=args.step_timeout_seconds,
            )
        )

    report_dir = Path(args.report_dir)
    for lane in lane_pack:
        pillar = lane["pillar"]
        if not _gauntlet_enabled(args, pillar):
            continue
        command, artifact_json, artifact_md = build_lane_command(
            lane["name"],
            pillar,
            lane["fixture"],
            report_dir,
        )
        results.append(
            run_step(
                lane["name"],
                pillar,
                command,
                artifact_json=artifact_json,
                artifact_md=artifact_md,
                timeout_seconds=args.step_timeout_seconds,
            )
        )

    if not results:
        raise SystemExit("No readiness steps selected")

    output_dir = report_dir / datetime.utcnow().strftime("%Y%m%d%H%M%S")
    md_path, json_path = write_report(output_dir, results)
    verdict = overall_verdict(results)
    summary = {
        "overall_verdict": verdict,
        "verdict": verdict,
        "report_md": str(md_path),
        "report_json": str(json_path),
        "steps": [
            {
                "name": result.name,
                "pillar": result.pillar,
                "verdict": result.verdict,
                "returncode": result.returncode,
                "artifact_json": result.artifact_json,
                "artifact_md": result.artifact_md,
                "elapsed_seconds": round(result.elapsed_seconds, 3),
            }
            for result in results
        ],
    }
    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"{summary['overall_verdict']}: helios readiness")
        print(f"Report: {md_path}")
        print(f"JSON: {json_path}")

    if summary["overall_verdict"] == "NO_GO":
        return 1
    if summary["overall_verdict"] == "CAUTION":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
