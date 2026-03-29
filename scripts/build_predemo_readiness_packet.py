#!/usr/bin/env python3
"""
Build a one-command pre-demo readiness packet from the live Helios gates.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKET_DIR = ROOT / "docs" / "reports" / "predemo_readiness_packet"
DEFAULT_ACCEPTANCE_SET = ROOT / "fixtures" / "customer_demo" / "counterparty_acceptance_set.json"
DEFAULT_HARDENING_READINESS_DIR = ROOT / "docs" / "reports" / "readiness"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


helios_readiness = _load_module(ROOT / "scripts" / "run_helios_readiness_report.py", "run_helios_readiness_report")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Helios pre-demo readiness packet.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--packet-dir", default=str(DEFAULT_PACKET_DIR))
    parser.add_argument("--acceptance-set", default=str(DEFAULT_ACCEPTANCE_SET))
    parser.add_argument("--skip-live-run", action="store_true")
    parser.add_argument("--skip-customer-pdf", action="store_true")
    parser.add_argument("--ai-readiness-mode", choices=("full", "surface"), default="surface")
    parser.add_argument("--max-enrich-seconds", type=int, default=90)
    parser.add_argument("--max-dossier-seconds", type=int, default=60)
    parser.add_argument("--max-pdf-seconds", type=int, default=60)
    parser.add_argument("--max-ai-seconds", type=int, default=90)
    parser.add_argument("--max-warnings", type=int, default=2)
    parser.add_argument("--wait-for-ready-seconds", type=int, default=120)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def load_acceptance_set(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("counterparty acceptance set must contain a JSON list")
    entries: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise SystemExit("counterparty acceptance set entries must be objects")
        if not str(entry.get("company") or "").strip():
            raise SystemExit("counterparty acceptance set entries require company")
        entries.append(entry)
    return entries


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


def build_live_readiness_command(args: argparse.Namespace, output_dir: Path) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "scripts" / "run_helios_readiness_report.py"),
        "--print-json",
        "--report-dir",
        str(output_dir),
        "--ai-readiness-mode",
        args.ai_readiness_mode,
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
        *_common_auth_args(args),
    ]


def latest_summary_json(base_dir: Path) -> Path | None:
    candidates = sorted(base_dir.glob("*/summary.json"))
    return candidates[-1] if candidates else None


def prime_time_artifacts_for(readiness_summary_json: str | None) -> tuple[str | None, str | None]:
    if not readiness_summary_json:
        return None, None
    summary_path = Path(readiness_summary_json)
    parent = summary_path.parent
    json_path = parent / "prime-time.json"
    md_path = parent / "prime-time.md"
    return (str(md_path) if md_path.exists() else None, str(json_path) if json_path.exists() else None)


def latest_live_beta_hardening_reports(base_dir: Path) -> tuple[str | None, str | None]:
    json_candidates = sorted(base_dir.glob("helios-live-beta-hardening-report-*.json"))
    md_candidates = sorted(base_dir.glob("helios-live-beta-hardening-report-*.md"))
    json_path = str(json_candidates[-1]) if json_candidates else None
    md_path = str(md_candidates[-1]) if md_candidates else None
    return md_path, json_path


def prime_time_artifacts_from_hardening_report(hardening_report_json: str | None) -> tuple[str | None, str | None]:
    if not hardening_report_json:
        return None, None
    path = Path(hardening_report_json)
    if not path.exists():
        return None, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    prime_time = payload.get("prime_time") if isinstance(payload, dict) else None
    if not isinstance(prime_time, dict):
        return None, None
    md_path = prime_time.get("report_md")
    json_path = prime_time.get("report_json")
    return (
        str(md_path) if md_path else None,
        str(json_path) if json_path else None,
    )


def preferred_summary_json(*candidates: Path | None) -> Path | None:
    valid = [candidate for candidate in candidates if candidate is not None]
    if not valid:
        return None
    return max(valid, key=lambda path: (path.parent.name, path.stat().st_mtime))


def run_live_readiness(command: list[str]) -> dict[str, Any]:
    proc = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or proc.stdout.strip() or f"readiness command failed: {proc.returncode}")
    payload = json.loads(proc.stdout)
    if not isinstance(payload, dict):
        raise SystemExit("live readiness did not return a JSON object")
    return payload


def build_packet_summary(
    readiness_payload: dict[str, Any],
    acceptance_set: list[dict[str, Any]],
    acceptance_set_path: str,
    customer_pdf_path: str | None,
    live_beta_hardening_md: str | None = None,
    live_beta_hardening_json: str | None = None,
) -> dict[str, Any]:
    prime_time_md, prime_time_json = prime_time_artifacts_for(readiness_payload.get("report_json"))
    if not prime_time_md and not prime_time_json:
        prime_time_md, prime_time_json = prime_time_artifacts_from_hardening_report(live_beta_hardening_json)
    steps = readiness_payload.get("steps", [])
    pillar_verdicts: dict[str, str] = {}
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            pillar = str(step.get("pillar") or "").strip()
            if pillar and pillar not in pillar_verdicts:
                pillar_verdicts[pillar] = str(step.get("verdict") or "UNKNOWN")
            elif pillar:
                current = pillar_verdicts[pillar]
                next_verdict = str(step.get("verdict") or "UNKNOWN")
                if current != "NO_GO":
                    if next_verdict == "NO_GO":
                        pillar_verdicts[pillar] = "NO_GO"
                    elif next_verdict == "CAUTION" and current != "NO_GO":
                        pillar_verdicts[pillar] = "CAUTION"
                    elif current not in {"CAUTION", "NO_GO"}:
                        pillar_verdicts[pillar] = next_verdict

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "overall_verdict": readiness_payload.get("overall_verdict", "UNKNOWN"),
        "readiness_report_json": readiness_payload.get("report_json"),
        "readiness_report_md": readiness_payload.get("report_md"),
        "prime_time_report_json": prime_time_json,
        "prime_time_report_md": prime_time_md,
        "live_beta_hardening_report_md": live_beta_hardening_md,
        "live_beta_hardening_report_json": live_beta_hardening_json,
        "customer_release_matrix_pdf": customer_pdf_path,
        "counterparty_acceptance_set_size": len(acceptance_set),
        "counterparty_acceptance_set_path": acceptance_set_path,
        "pillar_verdicts": pillar_verdicts,
        "acceptance_archetypes": [
            {
                "company": entry["company"],
                "bucket": entry.get("bucket", ""),
                "archetype": entry.get("archetype", ""),
                "why_it_matters": entry.get("why_it_matters", ""),
            }
            for entry in acceptance_set
        ],
        "steps": steps,
    }


def write_packet(output_dir: Path, summary: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "summary.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Helios Pre-Demo Readiness Packet",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Overall verdict: **{summary['overall_verdict']}**",
        f"- Counterparty acceptance set size: {summary['counterparty_acceptance_set_size']}",
        f"- Counterparty acceptance set: [{Path(summary['counterparty_acceptance_set_path']).name}]({summary['counterparty_acceptance_set_path']})",
    ]
    if summary.get("readiness_report_md"):
        lines.append(f"- Live readiness report: [{Path(summary['readiness_report_md']).name}]({summary['readiness_report_md']})")
    if summary.get("prime_time_report_md"):
        lines.append(f"- Prime-time report: [{Path(summary['prime_time_report_md']).name}]({summary['prime_time_report_md']})")
    if summary.get("live_beta_hardening_report_md"):
        lines.append(
            f"- Live beta hardening report: [{Path(summary['live_beta_hardening_report_md']).name}]({summary['live_beta_hardening_report_md']})"
        )
    if summary.get("customer_release_matrix_pdf"):
        lines.append(
            f"- Customer release matrix PDF: [{Path(summary['customer_release_matrix_pdf']).name}]({summary['customer_release_matrix_pdf']})"
        )
    lines.extend(["", "## Pillar verdicts", ""])
    for pillar, verdict in summary.get("pillar_verdicts", {}).items():
        lines.append(f"- {pillar}: **{verdict}**")

    lines.extend(["", "## Counterparty acceptance set", ""])
    for entry in summary.get("acceptance_archetypes", []):
        lines.append(
            f"- {entry['company']}: {entry.get('archetype') or 'unlabeled'} | "
            f"{entry.get('bucket') or 'unbucketed'} | {entry.get('why_it_matters') or 'no note'}"
        )

    lines.extend(["", "## Fixed gate artifacts", ""])
    for step in summary.get("steps", []):
        if not isinstance(step, dict):
            continue
        label = f"{step.get('pillar', 'unknown')} / {step.get('name', 'unnamed')}"
        verdict = step.get("verdict", "UNKNOWN")
        lines.append(f"- {label}: **{verdict}**")
        artifact_md = step.get("artifact_md")
        artifact_json = step.get("artifact_json")
        if artifact_md:
            lines.append(f"  report: [{Path(str(artifact_md)).name}]({artifact_md})")
        if artifact_json:
            lines.append(f"  json: [{Path(str(artifact_json)).name}]({artifact_json})")

    md_path = output_dir / "summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path


def main() -> int:
    args = parse_args()
    acceptance_set = load_acceptance_set(args.acceptance_set)

    live_report_dir = Path(args.packet_dir) / "live_helios_readiness"
    if args.skip_live_run:
        latest = preferred_summary_json(
            latest_summary_json(live_report_dir),
            latest_summary_json(helios_readiness.DEFAULT_REPORT_DIR),
            latest_summary_json(DEFAULT_HARDENING_READINESS_DIR),
        )
        if not latest:
            raise SystemExit("no live readiness summary found to package")
        readiness_payload = json.loads(latest.read_text(encoding="utf-8"))
        readiness_payload.setdefault("report_json", str(latest))
        readiness_payload.setdefault("report_md", str(latest.with_suffix(".md")))
    else:
        readiness_payload = run_live_readiness(build_live_readiness_command(args, live_report_dir))

    customer_pdf_path = None
    if not args.skip_customer_pdf:
        customer_matrix = _load_module(
            ROOT / "scripts" / "build_customer_release_matrix_pdf.py",
            "build_customer_release_matrix_pdf_runtime",
        )
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_customer_release_matrix_pdf.py")],
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        customer_pdf_path = str(customer_matrix.OUTPUT_PDF)

    live_beta_hardening_md, live_beta_hardening_json = latest_live_beta_hardening_reports(ROOT / "docs" / "reports")
    summary = build_packet_summary(
        readiness_payload,
        acceptance_set,
        args.acceptance_set,
        customer_pdf_path,
        live_beta_hardening_md=live_beta_hardening_md,
        live_beta_hardening_json=live_beta_hardening_json,
    )
    output_dir = Path(args.packet_dir) / datetime.utcnow().strftime("%Y%m%d%H%M%S")
    md_path, json_path = write_packet(output_dir, summary)

    payload = {
        "overall_verdict": summary["overall_verdict"],
        "verdict": summary["overall_verdict"],
        "report_md": str(md_path),
        "report_json": str(json_path),
        "prime_time_report_md": summary.get("prime_time_report_md"),
        "prime_time_report_json": summary.get("prime_time_report_json"),
        "live_beta_hardening_report_md": summary.get("live_beta_hardening_report_md"),
        "live_beta_hardening_report_json": summary.get("live_beta_hardening_report_json"),
        "customer_release_matrix_pdf": customer_pdf_path,
    }
    if args.print_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"{summary['overall_verdict']}: pre-demo readiness packet")
        print(f"Report: {md_path}")
        print(f"JSON: {json_path}")
        if customer_pdf_path:
            print(f"Customer PDF: {customer_pdf_path}")
    return 0 if summary["overall_verdict"] == "GO" else 1 if summary["overall_verdict"] == "NO_GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
