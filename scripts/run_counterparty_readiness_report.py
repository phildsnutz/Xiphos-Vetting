#!/usr/bin/env python3
"""
Run the counterparty readiness workflow as a single go/no-go report.

This script treats customer embarrassment as a release-engineering problem,
not a one-off company problem. It wires together:
  - authenticated read-only smoke
  - fixed counterparty lane packs for identity, dossier quality, and control paths
  - optional named-company demo gates

The result is a single readiness verdict:
  - GO
  - CAUTION
  - NO_GO
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

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "counterparty_readiness"
DEFAULT_PACK_MANIFEST = ROOT / "fixtures" / "customer_demo" / "counterparty_lane_pack.json"
TOKEN_CACHE_PATH = Path.home() / ".config" / "xiphos" / "readiness_token.json"


@dataclass
class StepResult:
    name: str
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
    parser = argparse.ArgumentParser(description="Run the Helios counterparty readiness workflow.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--pack-manifest", default=str(DEFAULT_PACK_MANIFEST))
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--skip-canary-pack", action="store_true")
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
    parser.add_argument("--step-timeout-seconds", type=int, default=600)
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


def _verdict_from_returncode(returncode: int) -> str:
    if returncode == 0:
        return "GO"
    if returncode == 2:
        return "CAUTION"
    return "NO_GO"


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def load_cached_token(args: argparse.Namespace) -> str:
    if not TOKEN_CACHE_PATH.exists():
        return ""
    try:
        payload = json.loads(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    if payload.get("base_url") != args.base_url.rstrip("/"):
        return ""
    if payload.get("email") != args.email:
        return ""
    return str(payload.get("token") or "").strip()


def store_cached_token(args: argparse.Namespace, token: str) -> None:
    TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE_PATH.write_text(
        json.dumps(
            {
                "base_url": args.base_url.rstrip("/"),
                "email": args.email,
                "token": token,
                "cached_at": datetime.utcnow().isoformat() + "Z",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def clear_cached_token() -> None:
    if TOKEN_CACHE_PATH.exists():
        TOKEN_CACHE_PATH.unlink()


def _remember_login_credentials(args: argparse.Namespace) -> None:
    email = str(getattr(args, "email", "") or "").strip()
    password = str(getattr(args, "password", "") or "").strip()
    if email:
        setattr(args, "_login_email", email)
    if password:
        setattr(args, "_login_password", password)


def _login_email(args: argparse.Namespace) -> str:
    return str(getattr(args, "_login_email", "") or getattr(args, "email", "") or "").strip()


def _login_password(args: argparse.Namespace) -> str:
    return str(getattr(args, "_login_password", "") or getattr(args, "password", "") or "").strip()


def ensure_access_token(args: argparse.Namespace, *, force_refresh: bool = False) -> None:
    _remember_login_credentials(args)
    if getattr(args, "token", "") and not force_refresh:
        return
    login_email = _login_email(args)
    login_password = _login_password(args)
    if not (login_email and login_password):
        return
    if not force_refresh:
        cached_token = load_cached_token(args)
        if cached_token:
            args.token = cached_token
            args.email = ""
            args.password = ""
            return
    response = requests.post(
        f"{args.base_url.rstrip('/')}/api/auth/login",
        json={"email": login_email, "password": login_password},
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError:
        if not force_refresh:
            cached_token = load_cached_token(args)
            if cached_token:
                args.token = cached_token
                args.email = ""
                args.password = ""
                return
        raise
    payload = response.json()
    token = str(payload.get("token") or "").strip()
    if not token:
        raise RuntimeError("readiness login succeeded without token")
    store_cached_token(args, token)
    args.token = token
    args.email = ""
    args.password = ""


def _smoke_failed_due_to_auth(result: StepResult) -> bool:
    combined = "\n".join(
        text
        for text in (str(result.stdout or ""), str(result.stderr or ""))
        if str(text or "").strip()
    ).lower()
    auth_markers = (
        "invalid or expired token",
        "401 unauthorized",
        '"error":"invalid or expired token"',
        "'error': 'invalid or expired token'",
    )
    return any(marker in combined for marker in auth_markers)


def _retry_smoke_with_fresh_token(args: argparse.Namespace, smoke_result: StepResult) -> StepResult:
    if smoke_result.verdict != "NO_GO" or not _smoke_failed_due_to_auth(smoke_result):
        return smoke_result
    if not (_login_email(args) and _login_password(args)):
        return smoke_result
    _progress("[counterparty readiness] smoke failed with stale auth, refreshing token and retrying once")
    clear_cached_token()
    args.token = ""
    ensure_access_token(args, force_refresh=True)
    return run_step("read_only_smoke", build_smoke_command(args))


def load_pack_manifest(path: str) -> list[dict[str, str]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("counterparty pack manifest must contain a JSON list")
    steps: list[dict[str, str]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise SystemExit("Each counterparty pack manifest entry must be an object")
        name = str(entry.get("name") or "").strip()
        pack_file = str(entry.get("pack_file") or "").strip()
        if not name or not pack_file:
            raise SystemExit("Each counterparty pack manifest entry needs name and pack_file")
        steps.append(
            {
                "name": name,
                "pack_file": pack_file,
                "connectors": list(entry.get("connectors") or []),
                "workers": int(entry.get("workers", 1) if entry.get("workers", 1) is not None else 1),
                "start_stagger_seconds": float(entry.get("start_stagger_seconds", 1.5) or 0.0),
                "transient_retries_per_company": int(
                    entry.get("transient_retries_per_company", 1)
                    if entry.get("transient_retries_per_company", 1) is not None
                    else 0
                ),
                "include_ai": bool(entry.get("include_ai", True)),
                "check_assistant": bool(entry.get("check_assistant", True)),
                "require_dossier_html": bool(entry.get("require_dossier_html", True)),
                "require_dossier_pdf": bool(entry.get("require_dossier_pdf", True)),
                "minimum_official_corroboration": str(entry.get("minimum_official_corroboration") or "missing"),
                "max_blocked_official_connectors": int(
                    entry.get("max_blocked_official_connectors", -1)
                    if entry.get("max_blocked_official_connectors", -1) is not None
                    else -1
                ),
            }
        )
    return steps


def run_step(
    name: str,
    command: list[str],
    *,
    artifact_dir: Path | None = None,
    timeout_seconds: int | None = None,
) -> StepResult:
    started = time.time()
    existing_artifacts = set(artifact_dir.rglob("summary.json")) if artifact_dir and artifact_dir.exists() else set()
    _progress(f"[counterparty readiness] starting {name}")
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
    artifact_json = None
    artifact_md = None
    if payload is None and artifact_dir is not None:
        latest_summary = _latest_new_summary_json(artifact_dir, existing_artifacts)
        if latest_summary and latest_summary.exists():
            artifact_json = str(latest_summary)
            artifact_md = str(latest_summary.with_suffix(".md"))
            payload = json.loads(latest_summary.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        artifact_json = payload.get("report_json") or payload.get("artifact_json") or artifact_json
        artifact_md = payload.get("report_md") or payload.get("artifact_md") or artifact_md
        artifacts = payload.get("artifacts")
        if isinstance(artifacts, dict):
            artifact_json = artifact_json or artifacts.get("json")
            artifact_md = artifact_md or artifacts.get("md")
        companies = payload.get("companies")
        if not artifact_json and isinstance(companies, list):
            # canary pack payloads do not contain artifact paths centrally
            if companies:
                artifact_json = str(companies[0].get("artifacts", {}).get("json", "")) or None
    _progress(
        f"[counterparty readiness] finished {name}: {_verdict_from_returncode(returncode)} "
        f"({elapsed:.1f}s)"
    )
    return StepResult(
        name=name,
        verdict=_verdict_from_returncode(returncode),
        command=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        artifact_json=artifact_json,
        artifact_md=artifact_md,
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


def build_smoke_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_local_smoke.py"),
        "--read-only",
        "--wait-for-ready-seconds",
        str(args.wait_for_ready_seconds),
        *_common_auth_args(args),
    ]
    return command


def build_canary_command(
    args: argparse.Namespace,
    *,
    pack_name: str,
    pack_file: str,
    include_ai: bool = True,
    check_assistant: bool = True,
    require_dossier_html: bool = True,
    require_dossier_pdf: bool = True,
    connectors: list[str] | None = None,
    workers: int = 1,
    start_stagger_seconds: float = 1.5,
    transient_retries_per_company: int = 1,
    minimum_official_corroboration: str = "missing",
    max_blocked_official_connectors: int = -1,
) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_counterparty_canary_pack.py"),
        "--report-dir",
        str(Path(args.report_dir) / "canary-pack" / pack_name),
        "--pack-file",
        str((ROOT / pack_file).resolve()),
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
        "--wait-for-ready-seconds",
        str(args.wait_for_ready_seconds),
        "--workers",
        str(max(workers, 1)),
        "--start-stagger-seconds",
        str(max(start_stagger_seconds, 0.0)),
        "--transient-retries-per-company",
        str(max(transient_retries_per_company, 0)),
        "--print-json",
        *_common_auth_args(args),
    ]
    if not (args.include_ai and include_ai):
        command.append("--skip-ai")
    command.extend(["--ai-readiness-mode", args.ai_readiness_mode])
    if not (args.check_assistant and check_assistant):
        command.append("--skip-assistant")
    if not require_dossier_html:
        command.append("--skip-dossier-html")
    if not require_dossier_pdf:
        command.append("--skip-dossier-pdf")
    if minimum_official_corroboration and minimum_official_corroboration != "missing":
        command.extend(["--minimum-official-corroboration", minimum_official_corroboration])
    if max_blocked_official_connectors >= 0:
        command.extend(["--max-blocked-official-connectors", str(max_blocked_official_connectors)])
    for connector in connectors or []:
        command.extend(["--connector", connector])
    return command


def build_company_command(args: argparse.Namespace, company: str) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_customer_demo_gate.py"),
        "--company",
        company,
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
        "--wait-for-ready-seconds",
        str(args.wait_for_ready_seconds),
        "--report-dir",
        str(Path(args.report_dir) / "companies"),
        "--print-json",
        *_common_auth_args(args),
    ]
    if not args.include_ai:
        command.append("--skip-ai")
    command.extend(["--ai-readiness-mode", args.ai_readiness_mode])
    if not args.check_assistant:
        command.append("--skip-assistant")
    minimum_official_corroboration = getattr(args, "minimum_official_corroboration", "missing")
    raw_max_blocked_official_connectors = getattr(args, "max_blocked_official_connectors", -1)
    max_blocked_official_connectors = int(
        raw_max_blocked_official_connectors
        if raw_max_blocked_official_connectors is not None
        else -1
    )
    if minimum_official_corroboration != "missing":
        command.extend(["--minimum-official-corroboration", minimum_official_corroboration])
    if max_blocked_official_connectors >= 0:
        command.extend(["--max-blocked-official-connectors", str(max_blocked_official_connectors)])
    return command


def write_report(output_dir: Path, results: list[StepResult]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    verdict = overall_verdict(results)
    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "overall_verdict": verdict,
        "verdict": verdict,
        "steps": [
            {
                "name": result.name,
                "verdict": result.verdict,
                "returncode": result.returncode,
                "command": result.command,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "payload": result.payload,
                "elapsed_seconds": round(result.elapsed_seconds, 3),
            }
            for result in results
        ],
    }
    json_path = output_dir / "summary.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Helios Counterparty Readiness Report",
        "",
        f"- Overall verdict: **{summary['overall_verdict']}**",
        f"- Generated: {summary['generated_at']}",
        "",
        "## Steps",
        "",
    ]
    for result in results:
        lines.extend(
            [
                f"### {result.name}",
                "",
                f"- Verdict: **{result.verdict}**",
                f"- Return code: `{result.returncode}`",
                f"- Command: `{ ' '.join(result.command) }`",
            ]
        )
        if result.artifact_md:
            lines.append(f"- Report: `{result.artifact_md}`")
        if result.artifact_json:
            lines.append(f"- JSON: `{result.artifact_json}`")
        if result.stderr.strip():
            lines.append(f"- stderr: `{result.stderr.strip()}`")
        if isinstance(result.payload, dict):
            if "overall_verdict" in result.payload:
                lines.append(f"- Payload verdict: **{result.payload['overall_verdict']}**")
            if "verdict" in result.payload:
                lines.append(f"- Payload verdict: **{result.payload['verdict']}**")
        lines.append("")

    md_path = output_dir / "summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path


def main() -> int:
    args = parse_args()
    if not args.token and not (args.email and args.password):
        raise SystemExit("readiness workflow requires --token or --email/--password")
    ensure_access_token(args)

    pack_manifest = load_pack_manifest(args.pack_manifest)
    results: list[StepResult] = []
    if not args.skip_smoke:
        smoke_result = run_step(
            "read_only_smoke",
            build_smoke_command(args),
            timeout_seconds=args.step_timeout_seconds,
        )
        smoke_result = _retry_smoke_with_fresh_token(args, smoke_result)
        results.append(smoke_result)
        if smoke_result.verdict == "NO_GO":
            output_dir = Path(args.report_dir) / datetime.utcnow().strftime("%Y%m%d%H%M%S")
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
                        "verdict": result.verdict,
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
                print(f"{summary['overall_verdict']}: counterparty readiness")
                print(f"Report: {md_path}")
                print(f"JSON: {json_path}")
            return 1
    if not args.skip_canary_pack:
        for pack_entry in pack_manifest:
            results.append(
                run_step(
                    pack_entry["name"],
                    build_canary_command(
                        args,
                        pack_name=pack_entry["name"],
                        pack_file=pack_entry["pack_file"],
                        include_ai=bool(pack_entry.get("include_ai", True)),
                        check_assistant=bool(pack_entry.get("check_assistant", True)),
                        require_dossier_html=bool(pack_entry.get("require_dossier_html", True)),
                        require_dossier_pdf=bool(pack_entry.get("require_dossier_pdf", True)),
                        connectors=list(pack_entry.get("connectors") or []),
                        workers=int(pack_entry.get("workers", 1) if pack_entry.get("workers", 1) is not None else 1),
                        start_stagger_seconds=float(pack_entry.get("start_stagger_seconds", 1.5) or 0.0),
                        transient_retries_per_company=int(
                            pack_entry.get("transient_retries_per_company", 1)
                            if pack_entry.get("transient_retries_per_company", 1) is not None
                            else 0
                        ),
                        minimum_official_corroboration=str(pack_entry.get("minimum_official_corroboration") or "missing"),
                        max_blocked_official_connectors=int(
                            pack_entry.get("max_blocked_official_connectors", -1)
                            if pack_entry.get("max_blocked_official_connectors", -1) is not None
                            else -1
                        ),
                    ),
                    artifact_dir=Path(args.report_dir) / "canary-pack" / pack_entry["name"],
                    timeout_seconds=args.step_timeout_seconds,
                )
            )
    for company in args.company:
        results.append(
            run_step(
                f"company_gate:{company}",
                build_company_command(args, company),
                artifact_dir=Path(args.report_dir) / "companies",
                timeout_seconds=args.step_timeout_seconds,
            )
        )

    output_dir = Path(args.report_dir) / datetime.utcnow().strftime("%Y%m%d%H%M%S")
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
                "verdict": result.verdict,
                "returncode": result.returncode,
                "elapsed_seconds": round(result.elapsed_seconds, 3),
            }
            for result in results
        ],
    }
    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"{summary['overall_verdict']}: counterparty readiness")
        print(f"Report: {md_path}")
        print(f"JSON: {json_path}")

    if summary["overall_verdict"] == "NO_GO":
        return 1
    if summary["overall_verdict"] == "CAUTION":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
