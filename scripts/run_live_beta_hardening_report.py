#!/usr/bin/env python3
"""
Run the beta hardening report against the live VPS-backed Helios instance.

This script executes inside the running container via SSH, collects:
  - dossier HTML markers
  - PDF bytes
  - graph integrity stats
  - monitoring history presence
  - AI brief presence

It then validates the PDF locally and writes Markdown + JSON reports.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader  # type: ignore
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"pypdf is required for live hardening reports: {exc}")


ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "docs" / "reports"
GRAPH_95_STATUS_PATH = ROOT / "GRAPH_95_STATUS.md"

HTML_SECTION_CHECKS = {
    "hero": "Helios Intelligence Brief",
    "risk_storyline": "Risk Storyline",
    "supplier_passport": "Supplier Passport",
    "graph_read": "Graph Read",
    "ai_brief": "Axiom Assessment",
    "recommended_actions": "Recommended Actions",
    "evidence_ledger": "Evidence Ledger",
}

PDF_SECTION_CHECKS = {
    "risk_storyline": "RISK STORYLINE",
    "supplier_passport": "SUPPLIER PASSPORT",
    "graph_read": "GRAPH READ",
    "ai_brief": "AXIOM ASSESSMENT",
    "recommended_actions": "RECOMMENDED ACTIONS",
    "evidence_ledger": "EVIDENCE LEDGER",
}


def _latest_nested_summary(base_dir: Path) -> Path | None:
    candidates = sorted(base_dir.glob("*/summary.json"))
    return candidates[-1] if candidates else None


def _load_graph_95_status() -> dict[str, Any]:
    benchmark_path = _latest_nested_summary(REPORTS_DIR / "graph_training_benchmark")
    benchmark_payload: dict[str, Any] = {}
    if benchmark_path and benchmark_path.exists():
        try:
            parsed = json.loads(benchmark_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                benchmark_payload = parsed
        except Exception:
            benchmark_payload = {}
    return {
        "benchmark_overall_verdict": str(benchmark_payload.get("overall_verdict") or "UNKNOWN"),
        "benchmark_report_json": str(benchmark_path) if benchmark_path else "",
        "status_md": str(GRAPH_95_STATUS_PATH) if GRAPH_95_STATUS_PATH.exists() else "",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Helios beta hardening report against the live host.")
    parser.add_argument("--host", default=os.environ.get("XIPHOS_LIVE_SSH_TARGET", ""))
    parser.add_argument("--ssh-key", default="")
    parser.add_argument("--container", default="xiphos-xiphos-1")
    parser.add_argument(
        "--user-id",
        default="",
        help="AI analysis user scope to validate. Leave blank to use org-default/global scope.",
    )
    parser.add_argument(
        "--cohort-file",
        default=str(ROOT / "docs" / "reports" / "helios-dense-case-replay-cohort-20260323.json"),
    )
    parser.add_argument("--graph-depth", type=int, default=3)
    parser.add_argument(
        "--report-dir",
        default=str(ROOT / "docs" / "reports"),
    )
    parser.add_argument("--skip-readiness", action="store_true")
    parser.add_argument("--skip-prime-time", action="store_true")
    parser.add_argument("--skip-query-to-dossier", action="store_true")
    parser.add_argument("--skip-thin-vendor-wave", action="store_true")
    parser.add_argument("--thin-vendor-wave-limit", type=int, default=10)
    parser.add_argument("--thin-vendor-wave-depth", type=int, default=3)
    parser.add_argument("--thin-vendor-wave-scan-limit", type=int, default=10000)
    parser.add_argument("--thin-vendor-wave-max-root-entities", type=int, default=1)
    parser.add_argument("--thin-vendor-wave-max-relationships", type=int, default=2)
    parser.add_argument(
        "--gauntlet-spec-file",
        default=str(ROOT / "fixtures" / "customer_demo" / "query_to_dossier_canary_pack.json"),
    )
    parser.add_argument("--readiness-base-url", default=os.environ.get("XIPHOS_LIVE_BASE_URL", ""))
    parser.add_argument("--readiness-email", default="")
    parser.add_argument("--readiness-password", default="")
    parser.add_argument("--readiness-token", default="")
    parser.add_argument("--readiness-company", action="append", default=[])
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def load_cohort(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("Cohort file must contain a JSON list")
    return payload


def _decode_json_from_stdout(stdout: str) -> dict[str, Any] | list[Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def remote_collect(
    host: str,
    container: str,
    case_ids: list[str],
    graph_depth: int,
    user_id: str,
    *,
    ssh_key: str = "",
) -> list[dict[str, Any]]:
    payload = json.dumps(
        {
            "case_ids": case_ids,
            "graph_depth": graph_depth,
            "user_id": user_id,
            "html_section_checks": HTML_SECTION_CHECKS,
        }
    )
    remote_script = r"""
import base64
import io
import json
import sys
import db
from ai_analysis import compute_analysis_fingerprint, get_latest_analysis
from dossier import generate_dossier
from dossier_pdf import generate_pdf_dossier
from graph_ingest import get_vendor_graph_summary

request = json.loads(sys.stdin.read())
results = []
for case_id in request["case_ids"]:
    user_id = request.get("user_id", "")
    vendor = db.get_vendor(case_id)
    if not vendor:
        results.append({"case_id": case_id, "error": "vendor not found"})
        continue

    score = db.get_latest_score(case_id) or {}
    enrichment = db.get_latest_enrichment(case_id)
    html = generate_dossier(case_id, user_id=user_id, hydrate_ai=False)
    pdf = generate_pdf_dossier(case_id, user_id=user_id, hydrate_ai=False)
    graph = get_vendor_graph_summary(case_id, depth=request["graph_depth"])
    monitoring = db.get_monitoring_history(case_id, limit=1)
    fingerprint = compute_analysis_fingerprint(vendor, score, enrichment) if score else ""
    cached = get_latest_analysis(case_id, user_id=user_id, input_hash=fingerprint) if fingerprint else None

    latest_tier = (
        score.get("calibrated", {}).get("calibrated_tier")
        or score.get("tier")
        or score.get("calibrated_tier")
        or "unknown"
    )

    results.append({
        "case_id": case_id,
        "vendor_name": vendor.get("name"),
        "tier": latest_tier,
        "html_markers": {
            name: (marker in html)
            for name, marker in request.get("html_section_checks", {}).items()
        },
        "ai_expected": bool(cached),
        "monitoring_ready": bool(monitoring),
        "monitoring_latest": monitoring[0] if monitoring else None,
        "graph": {
            "entity_count": graph.get("entity_count", 0),
            "relationship_count": graph.get("relationship_count", 0),
            "root_entity_id": graph.get("root_entity_id"),
            "error": graph.get("error"),
            "missing_endpoints": sum(
                1
                for rel in graph.get("relationships", [])
                if rel.get("source_entity_id") not in {e.get("id") for e in graph.get("entities", [])}
                or rel.get("target_entity_id") not in {e.get("id") for e in graph.get("entities", [])}
            ),
            "corroborated_edges": sum(
                1 for rel in graph.get("relationships", []) if int(rel.get("corroboration_count") or 0) > 1
            ),
        },
        "pdf_base64": base64.b64encode(pdf).decode("ascii"),
    })

print(json.dumps(results, default=str))
"""
    remote_command = (
        f"docker exec -i -w /app/backend {shlex.quote(container)} "
        f"python3 -c {shlex.quote(remote_script)}"
    )
    ssh_command = ["ssh", "-o", "BatchMode=yes"]
    if ssh_key:
        ssh_command.extend(["-i", ssh_key, "-o", "IdentitiesOnly=yes"])
    ssh_command.extend([host, remote_command])
    proc = subprocess.run(
        ssh_command,
        input=payload,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "unknown remote error"
        raise RuntimeError(f"live hardening remote collect failed: {stderr}")
    payload = _decode_json_from_stdout(proc.stdout)
    if not isinstance(payload, list):
        detail = proc.stderr.strip() or proc.stdout.strip() or "live hardening remote collect did not emit JSON"
        raise RuntimeError(f"live hardening remote collect failed: {detail}")
    return payload


def extract_pdf_text(pdf_base64: str) -> str:
    pdf_bytes = base64.b64decode(pdf_base64)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "".join(page.extract_text() or "" for page in reader.pages)


def validate_result(case: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []

    if case.get("error"):
        failures.append(case["error"])
        return {
            **case,
            "failures": failures,
            "warnings": warnings,
            "pdf_markers": {},
        }

    html_markers = case["html_markers"]
    for name, present in html_markers.items():
        if not present:
            failures.append(f"html dossier missing {name.replace('_', ' ')}")

    pdf_text = extract_pdf_text(case["pdf_base64"]).upper()
    pdf_markers = {name: marker in pdf_text for name, marker in PDF_SECTION_CHECKS.items()}
    for name, present in pdf_markers.items():
        if not present:
            failures.append(f"pdf dossier missing {name.replace('_', ' ')}")

    graph = case["graph"]
    if graph.get("error"):
        failures.append(f"graph error: {graph['error']}")
    if graph.get("missing_endpoints"):
        failures.append(f"graph missing endpoints for {graph['missing_endpoints']} relationships")
    if not graph.get("root_entity_id"):
        warnings.append("graph root entity id missing")
    if not case.get("monitoring_ready"):
        warnings.append("no monitoring history yet")

    return {
        **case,
        "pdf_markers": pdf_markers,
        "failures": failures,
        "warnings": warnings,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    neo4j = summary.get("neo4j") if isinstance(summary.get("neo4j"), dict) else {}
    graph_95 = summary.get("graph_95") if isinstance(summary.get("graph_95"), dict) else {}
    thin_vendor_wave = summary.get("thin_vendor_wave") if isinstance(summary.get("thin_vendor_wave"), dict) else {}
    thin_vendor_kpi = thin_vendor_wave.get("kpi_gate") if isinstance(thin_vendor_wave.get("kpi_gate"), dict) else {}
    lines = [
        "# Helios Live Beta Hardening Report",
        "",
        f"Generated: {summary['generated_at']}",
        f"Host: {summary['host']}",
        f"User scope: {summary['user_id'] or 'org-default/global'}",
        f"Graph depth: {summary['graph_depth']}",
        "",
        "## Summary",
        "",
        f"- Cases checked: {summary['cases_checked']}",
        f"- Cases with failures: {summary['cases_with_failures']}",
        f"- Warning count: {summary['warning_count']}",
        "",
        "## Neo4j",
        "",
        f"- Required: **{'yes' if neo4j.get('required') else 'no'}**",
        f"- Available: **{'yes' if neo4j.get('neo4j_available') else 'no'}**",
        f"- Status: `{neo4j.get('status') or 'unknown'}`",
        "",
        "## Query To Dossier",
        "",
        f"- Gauntlet verdict: **{summary['query_to_dossier']['overall_verdict']}**",
        f"- Gauntlet report: {summary['query_to_dossier']['report_md']}",
        "",
        "## Readiness",
        "",
        f"- Readiness verdict: **{summary['readiness']['overall_verdict']}**",
        f"- Readiness report: {summary['readiness']['report_md']}",
        "",
        "## Prime Time",
        "",
        f"- Prime-time verdict: **{summary['prime_time']['prime_time_verdict']}**",
        f"- Prime-time report: {summary['prime_time']['report_md']}",
        "",
        "## Graph 9.5",
        "",
        f"- Graph benchmark verdict: **{graph_95.get('benchmark_overall_verdict') or 'UNKNOWN'}**",
        f"- Graph benchmark report: {graph_95.get('benchmark_report_json') or ''}",
        f"- Graph status memo: {graph_95.get('status_md') or ''}",
        "",
        "## Thin Vendor Wave",
        "",
        f"- Wave verdict: **{thin_vendor_kpi.get('status') or thin_vendor_wave.get('status') or 'SKIPPED'}**",
        f"- Wave report: {thin_vendor_wave.get('report_md') or ''}",
        f"- Wave report json: {thin_vendor_wave.get('report_json') or ''}",
        f"- Zero-control drop: `{thin_vendor_kpi.get('zero_control_drop', 0)}`",
        f"- New ownership edges: `{thin_vendor_kpi.get('new_ownership_edges', 0)}`",
        f"- New financing edges: `{thin_vendor_kpi.get('new_financing_edges', 0)}`",
        f"- New intermediary edges: `{thin_vendor_kpi.get('new_intermediary_edges', 0)}`",
        "",
        "## Cohort Results",
        "",
    ]

    for case in summary["cases"]:
        lines.extend([
            f"### {case['vendor_name']} ({case['case_id']})",
            "",
            f"- Tier: {case['tier']}",
            f"- Monitoring history: {'present' if case['monitoring_ready'] else 'missing'}",
            f"- Graph: {case['graph']['entity_count']} entities, {case['graph']['relationship_count']} relationships, {case['graph']['corroborated_edges']} corroborated edges",
            f"- AI expected: {'yes' if case['ai_expected'] else 'no'}",
            f"- HTML markers: {', '.join(name for name, ok in case['html_markers'].items() if ok) or 'none'}",
            f"- PDF markers: {', '.join(name for name, ok in case['pdf_markers'].items() if ok) or 'none'}",
        ])
        if case["failures"]:
            lines.append("- Failures:")
            for failure in case["failures"]:
                lines.append(f"  - {failure}")
        if case["warnings"]:
            lines.append("- Warnings:")
            for warning in case["warnings"]:
                lines.append(f"  - {warning}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run_readiness(args: argparse.Namespace) -> dict[str, Any]:
    if args.skip_readiness:
        return {
            "overall_verdict": "SKIPPED",
            "report_md": "",
            "report_json": "",
            "steps": [],
        }
    if not args.readiness_token and not (args.readiness_email and args.readiness_password):
        raise SystemExit("live beta hardening now requires readiness auth or --skip-readiness")

    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_helios_readiness_report.py"),
        "--report-dir",
        str(Path(args.report_dir) / "readiness"),
        "--print-json",
        "--base-url",
        args.readiness_base_url,
        "--skip-export",
        "--skip-assurance",
        "--max-enrich-seconds",
        "60",
        "--max-dossier-seconds",
        "60",
        "--max-pdf-seconds",
        "60",
        "--max-ai-seconds",
        "45",
        "--wait-for-ready-seconds",
        "45",
        "--counterparty-step-timeout-seconds",
        "180",
    ]
    if args.readiness_token:
        command.extend(["--token", args.readiness_token])
    else:
        command.extend(["--email", args.readiness_email, "--password", args.readiness_password])
    for company in args.readiness_company:
        command.extend(["--company", company])

    proc = subprocess.run(command, text=True, capture_output=True)
    if proc.returncode not in {0, 1, 2}:
        stderr = proc.stderr.strip() or "unknown readiness error"
        raise RuntimeError(f"counterparty readiness failed: {stderr}")
    payload = _decode_json_from_stdout(proc.stdout)
    if not isinstance(payload, dict):
        detail = proc.stderr.strip() or proc.stdout.strip() or "counterparty readiness did not emit JSON"
        raise RuntimeError(f"counterparty readiness failed: {detail}")
    payload["returncode"] = proc.returncode
    return payload


def run_query_to_dossier(args: argparse.Namespace) -> dict[str, Any]:
    if args.skip_query_to_dossier:
        return {
            "overall_verdict": "SKIPPED",
            "report_md": "",
            "report_json": "",
            "flows": [],
        }
    if not args.readiness_token and not (args.readiness_email and args.readiness_password):
        raise SystemExit("live beta hardening query-to-dossier now requires readiness auth or --skip-query-to-dossier")

    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_live_query_to_dossier_canary.py"),
        "--base-url",
        args.readiness_base_url,
        "--spec-file",
        args.gauntlet_spec_file,
        "--report-dir",
        str(Path(args.report_dir) / "query-to-dossier"),
        "--print-json",
    ]
    if args.readiness_token:
        command.extend(["--token", args.readiness_token])
    else:
        command.extend(["--email", args.readiness_email, "--password", args.readiness_password])

    proc = subprocess.run(command, text=True, capture_output=True)
    if proc.returncode not in {0, 1}:
        stderr = proc.stderr.strip() or "unknown gauntlet error"
        raise RuntimeError(f"live query-to-dossier gauntlet failed: {stderr}")
    payload = _decode_json_from_stdout(proc.stdout)
    if not isinstance(payload, dict):
        detail = proc.stderr.strip() or proc.stdout.strip() or "live query-to-dossier gauntlet did not emit JSON"
        raise RuntimeError(f"live query-to-dossier gauntlet failed: {detail}")
    payload["returncode"] = proc.returncode
    return payload


def run_prime_time(
    args: argparse.Namespace,
    readiness: dict[str, Any],
    query_to_dossier: dict[str, Any],
    report_dir: Path,
    stamp: str,
) -> dict[str, Any]:
    if args.skip_prime_time:
        return {
            "prime_time_verdict": "SKIPPED",
            "report_md": "",
            "report_json": "",
        }
    readiness_json = readiness.get("report_json")
    if not readiness_json:
        raise RuntimeError("prime-time evaluation requires readiness report_json")
    query_to_dossier_json = query_to_dossier.get("report_json")
    if not query_to_dossier_json:
        raise RuntimeError("prime-time evaluation requires query-to-dossier report_json")
    output_json = report_dir / f"helios-live-prime-time-{stamp}.json"
    output_md = report_dir / f"helios-live-prime-time-{stamp}.md"
    command = [
        sys.executable,
        str(ROOT / "scripts" / "evaluate_prime_time_readiness.py"),
        "--readiness-summary",
        str(readiness_json),
        "--query-to-dossier-summary",
        str(query_to_dossier_json),
        "--output-json",
        str(output_json),
        "--output-md",
        str(output_md),
        "--print-json",
    ]
    proc = subprocess.run(command, text=True, capture_output=True)
    if proc.returncode not in {0, 1}:
        stderr = proc.stderr.strip() or "unknown prime-time error"
        raise RuntimeError(f"prime-time evaluation failed: {stderr}")
    payload = _decode_json_from_stdout(proc.stdout)
    if not isinstance(payload, dict):
        detail = proc.stderr.strip() or proc.stdout.strip() or "prime-time evaluation did not emit JSON"
        raise RuntimeError(f"prime-time evaluation failed: {detail}")
    payload["returncode"] = proc.returncode
    payload["report_json"] = str(output_json)
    payload["report_md"] = str(output_md)
    return payload


def run_thin_vendor_wave(args: argparse.Namespace) -> dict[str, Any]:
    if args.skip_thin_vendor_wave:
        return {
            "status": "SKIPPED",
            "report_md": "",
            "report_json": "",
            "kpi_gate": {"status": "SKIPPED"},
        }

    remote_command = [
        "docker",
        "exec",
        "-i",
        "-w",
        "/app",
        args.container,
        "python3",
        "scripts/run_thin_vendor_refresh_wave.py",
        "--report-dir",
        "/app/docs/reports/thin_vendor_refresh_wave",
        "--limit",
        str(args.thin_vendor_wave_limit),
        "--depth",
        str(args.thin_vendor_wave_depth),
        "--scan-limit",
        str(args.thin_vendor_wave_scan_limit),
        "--max-root-entities",
        str(args.thin_vendor_wave_max_root_entities),
        "--max-relationships",
        str(args.thin_vendor_wave_max_relationships),
        "--print-json",
    ]
    ssh_command = ["ssh", "-o", "BatchMode=yes"]
    if args.ssh_key:
        ssh_command.extend(["-i", args.ssh_key, "-o", "IdentitiesOnly=yes"])
    ssh_command.extend([args.host, shlex.join(remote_command)])
    proc = subprocess.run(ssh_command, text=True, capture_output=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "unknown live thin-vendor wave error"
        raise RuntimeError(f"live thin-vendor wave failed: {stderr}")
    payload = _decode_json_from_stdout(proc.stdout)
    if not isinstance(payload, dict):
        detail = proc.stderr.strip() or proc.stdout.strip() or "live thin-vendor wave did not emit JSON"
        raise RuntimeError(f"live thin-vendor wave failed: {detail}")
    payload["returncode"] = proc.returncode
    payload["report_md"] = str(payload.get("report_markdown") or "")
    return payload


def _gate_success(verdict: str, success_values: set[str]) -> bool:
    return verdict in success_values | {"SKIPPED"}


def _overall_verdict(summary: dict[str, Any]) -> str:
    if summary["cases_with_failures"] > 0:
        return "FAIL"
    neo4j = summary.get("neo4j") if isinstance(summary.get("neo4j"), dict) else {}
    if bool(neo4j.get("required")) and not bool(neo4j.get("neo4j_available")):
        return "FAIL"
    gauntlet_verdict = str(summary["query_to_dossier"]["overall_verdict"])
    readiness_verdict = str(summary["readiness"]["overall_verdict"])
    prime_time_verdict = str(summary["prime_time"]["prime_time_verdict"])
    if gauntlet_verdict == "PASS" and readiness_verdict == "GO" and prime_time_verdict == "READY":
        return "PASS"
    if _gate_success(gauntlet_verdict, {"PASS"}) and _gate_success(readiness_verdict, {"GO"}) and _gate_success(prime_time_verdict, {"READY"}):
        return "PASS_WITH_SKIPS"
    return "FAIL"


def main() -> int:
    args = parse_args()
    if not args.host:
        raise SystemExit("set --host or XIPHOS_LIVE_SSH_TARGET for live beta hardening")
    if not args.skip_readiness and not args.readiness_base_url:
        raise SystemExit("set --readiness-base-url or XIPHOS_LIVE_BASE_URL for live beta hardening")
    if not args.skip_query_to_dossier and not args.readiness_base_url:
        raise SystemExit("set --readiness-base-url or XIPHOS_LIVE_BASE_URL for live beta hardening")
    cohort = load_cohort(args.cohort_file)
    case_ids = [entry["id"] for entry in cohort]
    raw_results = remote_collect(
        args.host,
        args.container,
        case_ids,
        args.graph_depth,
        args.user_id,
        ssh_key=args.ssh_key,
    )
    results = [validate_result(result) for result in raw_results]

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "host": args.host,
        "user_id": args.user_id,
        "graph_depth": args.graph_depth,
        "cases_checked": len(results),
        "cases_with_failures": sum(1 for result in results if result["failures"]),
        "warning_count": sum(len(result["warnings"]) for result in results),
        "query_to_dossier": run_query_to_dossier(args),
        "readiness": run_readiness(args),
        "graph_95": _load_graph_95_status(),
        "thin_vendor_wave": run_thin_vendor_wave(args),
        "cases": results,
    }
    summary["neo4j"] = dict(summary["query_to_dossier"].get("neo4j_summary") or {})
    summary["neo4j"]["required"] = bool(summary["query_to_dossier"].get("require_neo4j", True))
    summary["prime_time"] = run_prime_time(args, summary["readiness"], summary["query_to_dossier"], report_dir, stamp)
    summary["overall_verdict"] = _overall_verdict(summary)

    json_path = report_dir / f"helios-live-beta-hardening-report-{stamp}.json"
    md_path = report_dir / f"helios-live-beta-hardening-report-{stamp}.md"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")

    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    if args.print_json:
        print(json.dumps(summary, indent=2))
    return 0 if summary["overall_verdict"] in {"PASS", "PASS_WITH_SKIPS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
