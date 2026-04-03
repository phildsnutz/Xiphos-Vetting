#!/usr/bin/env python3
"""
Generate a beta-readiness hardening report from the current Helios dataset.

The report validates the most expensive/high-visibility surfaces:
  - dossier HTML
  - dossier PDF
  - graph payload integrity
  - monitoring history presence
  - AI narrative presence

It is designed to be a repeatable pre-beta / pre-hotfix gate, not just an
ad hoc smoke script.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
REPORTS_DIR = ROOT / "docs" / "reports"
GRAPH_95_STATUS_PATH = ROOT / "GRAPH_95_STATUS.md"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import db  # noqa: E402
from ai_analysis import compute_analysis_fingerprint, get_latest_analysis  # noqa: E402
from dossier import generate_dossier  # noqa: E402
from dossier_pdf import generate_pdf_dossier  # noqa: E402
from graph_ingest import get_vendor_graph_summary  # noqa: E402
from secure_runtime_env import load_runtime_env  # noqa: E402

try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover - graceful degradation
    PdfReader = None


HTML_SECTION_CHECKS = {
    "executive_strip": "Recent change",
    "risk_storyline": "Risk Storyline",
    "supplier_passport": "Supplier passport",
    "ai_brief": "AI Narrative Brief",
    "executive_judgment": "Executive judgment",
}

PDF_SECTION_CHECKS = {
    "executive_strip": "RECENT CHANGE",
    "risk_storyline": "RISK STORYLINE",
    "supplier_passport": "SUPPLIER PASSPORT",
    "ai_brief": "AI NARRATIVE BRIEF",
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


@dataclass
class CaseResult:
    case_id: str
    vendor_name: str
    tier: str
    html_ok: bool
    pdf_ok: bool
    graph_ok: bool
    ai_ready: bool
    ai_expected: bool
    monitoring_ready: bool
    graph_entities: int
    graph_relationships: int
    graph_corroborated_edges: int
    graph_missing_endpoints: int
    html_ms: int
    pdf_ms: int
    graph_ms: int
    failures: list[str]
    warnings: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Helios beta hardening report.")
    parser.add_argument("--case-id", action="append", default=[], help="Specific case/vendor IDs to validate")
    parser.add_argument(
        "--cohort-file",
        default="",
        help="Optional JSON cohort file with case objects containing at least an `id` field",
    )
    parser.add_argument("--limit", type=int, default=10, help="Number of recent cases to check when no case IDs are supplied")
    parser.add_argument("--graph-depth", type=int, default=3, help="Graph depth to validate")
    parser.add_argument(
        "--report-dir",
        default=str(ROOT / "docs" / "reports"),
        help="Directory where markdown/json reports should be written",
    )
    parser.add_argument("--readiness-base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--readiness-email", default="")
    parser.add_argument("--readiness-password", default="")
    parser.add_argument("--readiness-token", default="")
    parser.add_argument("--readiness-company", action="append", default=[])
    parser.add_argument("--skip-readiness", action="store_true")
    parser.add_argument("--skip-prime-time", action="store_true")
    parser.add_argument("--skip-query-to-dossier", action="store_true")
    parser.add_argument("--skip-thin-vendor-wave", action="store_true")
    parser.add_argument("--thin-vendor-wave-limit", type=int, default=10)
    parser.add_argument("--thin-vendor-wave-depth", type=int, default=3)
    parser.add_argument("--thin-vendor-wave-scan-limit", type=int, default=10000)
    parser.add_argument("--thin-vendor-wave-max-root-entities", type=int, default=1)
    parser.add_argument("--thin-vendor-wave-max-relationships", type=int, default=2)
    parser.add_argument("--gauntlet-mode", choices=("fixture", "local-auth", "both"), default="fixture")
    parser.add_argument("--gauntlet-base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--gauntlet-email", default="")
    parser.add_argument("--gauntlet-password", default="")
    parser.add_argument("--gauntlet-token", default="")
    parser.add_argument(
        "--gauntlet-spec-file",
        default=str(ROOT / "fixtures" / "customer_demo" / "query_to_dossier_canary_pack.json"),
    )
    parser.add_argument("--require-neo4j", action="store_true")
    parser.add_argument("--allow-missing-neo4j", dest="require_neo4j", action="store_false")
    parser.add_argument("--runtime-env-file", default="")
    parser.add_argument("--skip-runtime-env", action="store_true")
    parser.add_argument("--warm-monitoring", action="store_true", help="Attempt one local monitoring pass before warning")
    parser.add_argument("--print-json", action="store_true", help="Print the JSON summary to stdout")
    return parser.parse_args()


def load_case_ids_from_cohort(cohort_file: str) -> list[str]:
    if not cohort_file:
        return []
    payload = json.loads(Path(cohort_file).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("Cohort file must contain a JSON list")
    case_ids = []
    for entry in payload:
        if not isinstance(entry, dict) or not entry.get("id"):
            raise SystemExit("Each cohort entry must be an object with an `id` field")
        case_ids.append(str(entry["id"]))
    return case_ids


def _decode_json_from_stdout(stdout: str) -> dict[str, Any] | list[Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def select_cases(case_ids: list[str], limit: int) -> list[dict[str, Any]]:
    if case_ids:
        selected = []
        for case_id in case_ids:
            vendor = db.get_vendor(case_id)
            if not vendor:
                raise SystemExit(f"Unknown case/vendor id: {case_id}")
            vendor["latest_score"] = db.get_latest_score(case_id)
            selected.append(vendor)
        return selected

    vendors = db.list_vendors_with_scores(limit=max(limit, 1))
    return [vendor for vendor in vendors if vendor.get("latest_score")]


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if PdfReader is None:
        warnings.append("pypdf unavailable; skipped PDF text checks")
        return "", warnings
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        warnings.append("PDF text extraction returned empty text")
    return text, warnings


def validate_graph_payload(graph: dict[str, Any]) -> tuple[bool, dict[str, int], list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    if graph.get("error"):
        return False, {
            "entities": 0,
            "relationships": 0,
            "corroborated_edges": 0,
            "missing_endpoints": 0,
        }, [f"graph error: {graph['error']}"], warnings

    entities = graph.get("entities", [])
    relationships = graph.get("relationships", [])
    entity_ids = {entity.get("id") for entity in entities}
    missing_endpoints = 0
    corroborated_edges = 0

    for rel in relationships:
        if rel.get("source_entity_id") not in entity_ids or rel.get("target_entity_id") not in entity_ids:
            missing_endpoints += 1
        if int(rel.get("corroboration_count") or 0) > 1:
            corroborated_edges += 1

    if relationships and not entities:
        failures.append("graph returned relationships with no entities")
    if missing_endpoints:
        failures.append(f"graph missing hydrated endpoints for {missing_endpoints} relationships")
    if not graph.get("root_entity_id"):
        warnings.append("graph root entity id missing")

    return not failures, {
        "entities": len(entities),
        "relationships": len(relationships),
        "corroborated_edges": corroborated_edges,
        "missing_endpoints": missing_endpoints,
    }, failures, warnings


def validate_section_checks(document: str, checks: dict[str, str], prefix: str) -> tuple[bool, list[str]]:
    failures = [f"{prefix} missing {name.replace('_', ' ')}" for name, marker in checks.items() if marker not in document]
    return not failures, failures


def resolve_cached_analysis(case_id: str, input_hash: str) -> tuple[dict[str, Any] | None, str]:
    if not input_hash:
        return None, "dev"

    cached = get_latest_analysis(case_id, user_id="dev", input_hash=input_hash)
    if cached:
        return cached, str(cached.get("created_by") or "dev")

    cached = get_latest_analysis(case_id, input_hash=input_hash)
    if cached:
        return cached, str(cached.get("created_by") or "dev")

    return None, "dev"


def _warm_monitoring_history(case_id: str) -> bool:
    try:
        from monitor import VendorMonitor
    except Exception:
        return False

    try:
        monitor = VendorMonitor(check_interval=0)
        monitor.check_vendor(case_id)
    except Exception:
        return False

    return bool(db.get_monitoring_history(case_id, limit=1))


def run_case(vendor: dict[str, Any], graph_depth: int, *, warm_monitoring: bool = False) -> CaseResult:
    case_id = vendor["id"]
    vendor_name = vendor.get("name") or "Unknown"
    latest_score = vendor.get("latest_score") or db.get_latest_score(case_id) or {}
    enrichment = db.get_latest_enrichment(case_id)
    tier = (
        latest_score.get("calibrated", {}).get("calibrated_tier")
        or latest_score.get("tier")
        or latest_score.get("calibrated_tier")
        or "unknown"
    )
    failures: list[str] = []
    warnings: list[str] = []
    ai_fingerprint = compute_analysis_fingerprint(vendor, latest_score, enrichment) if latest_score else ""
    cached_analysis, analysis_user_id = resolve_cached_analysis(case_id, ai_fingerprint)

    start = time.perf_counter()
    html = generate_dossier(case_id, user_id=analysis_user_id, hydrate_ai=not bool(cached_analysis))
    html_ms = int((time.perf_counter() - start) * 1000)
    html_checks = dict(HTML_SECTION_CHECKS)
    cached_analysis, analysis_user_id = resolve_cached_analysis(case_id, ai_fingerprint)
    ai_expected = bool(cached_analysis)
    if not ai_expected:
        html_checks.pop("ai_brief", None)
        html_checks.pop("executive_judgment", None)
    html_ok, html_failures = validate_section_checks(html, html_checks, "html dossier")
    failures.extend(html_failures)

    start = time.perf_counter()
    pdf_bytes = generate_pdf_dossier(case_id, user_id=analysis_user_id, hydrate_ai=False)
    pdf_ms = int((time.perf_counter() - start) * 1000)
    pdf_text, pdf_warnings = extract_pdf_text(pdf_bytes)
    warnings.extend(pdf_warnings)
    pdf_checks = dict(PDF_SECTION_CHECKS)
    if not ai_expected:
        pdf_checks.pop("ai_brief", None)
    pdf_ok, pdf_failures = validate_section_checks(pdf_text.upper(), pdf_checks, "pdf dossier")
    failures.extend(pdf_failures)

    start = time.perf_counter()
    graph = get_vendor_graph_summary(case_id, depth=graph_depth)
    graph_ms = int((time.perf_counter() - start) * 1000)
    graph_ok, graph_stats, graph_failures, graph_warnings = validate_graph_payload(graph)
    failures.extend(graph_failures)
    warnings.extend(graph_warnings)

    monitoring_history = db.get_monitoring_history(case_id, limit=1)
    monitoring_ready = bool(monitoring_history)
    if not monitoring_ready and warm_monitoring:
        monitoring_ready = _warm_monitoring_history(case_id)
    if not monitoring_ready:
        warnings.append("no monitoring history yet")

    ai_ready = "AI Narrative Brief" in html
    if ai_expected and not ai_ready:
        failures.append("ai narrative brief missing from html dossier")
    elif not ai_expected and not ai_ready:
        warnings.append("ai brief not warmed yet")

    return CaseResult(
        case_id=case_id,
        vendor_name=vendor_name,
        tier=str(tier),
        html_ok=html_ok,
        pdf_ok=pdf_ok,
        graph_ok=graph_ok,
        ai_ready=ai_ready,
        ai_expected=ai_expected,
        monitoring_ready=monitoring_ready,
        graph_entities=graph_stats["entities"],
        graph_relationships=graph_stats["relationships"],
        graph_corroborated_edges=graph_stats["corroborated_edges"],
        graph_missing_endpoints=graph_stats["missing_endpoints"],
        html_ms=html_ms,
        pdf_ms=pdf_ms,
        graph_ms=graph_ms,
        failures=failures,
        warnings=warnings,
    )


def build_summary(results: list[CaseResult], graph_depth: int) -> dict[str, Any]:
    failure_count = sum(1 for result in results if result.failures)
    warning_count = sum(len(result.warnings) for result in results)
    html_failures = sum(1 for result in results if not result.html_ok)
    pdf_failures = sum(1 for result in results if not result.pdf_ok)
    graph_failures = sum(1 for result in results if not result.graph_ok)
    ai_missing = sum(1 for result in results if result.ai_expected and not result.ai_ready)
    ai_not_warmed = sum(1 for result in results if not result.ai_expected)
    monitoring_missing = sum(1 for result in results if not result.monitoring_ready)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "graph_depth": graph_depth,
        "cases_checked": len(results),
        "cases_with_failures": failure_count,
        "warning_count": warning_count,
        "html_failures": html_failures,
        "pdf_failures": pdf_failures,
        "graph_failures": graph_failures,
        "ai_missing": ai_missing,
        "ai_not_warmed": ai_not_warmed,
        "monitoring_missing": monitoring_missing,
        "tiers": dict(Counter(result.tier for result in results)),
        "cases": [result.__dict__ for result in results],
    }


def _gate_success(verdict: str, success_values: set[str]) -> bool:
    return verdict in success_values | {"SKIPPED"}


def _is_local_base_url(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "0.0.0.0"}


def _local_neo4j_runtime_status(runtime_env_file: str, *, skip_runtime_env: bool) -> dict[str, Any]:
    runtime_env = {
        "loaded": False,
        "path": "",
        "available_keys": [],
        "injected_keys": [],
        "paths_checked": [],
    }
    if not skip_runtime_env:
        runtime_env = load_runtime_env(runtime_env_file)

    configured = bool(os.environ.get("NEO4J_URI", "").strip() and os.environ.get("NEO4J_PASSWORD", "").strip())
    database = os.environ.get("NEO4J_DATABASE", "").strip() or os.environ.get("NEO4J_USER", "").strip()
    if not configured:
        return {
            "status": "unverified",
            "configured": False,
            "database": database,
            "runtime_env": runtime_env,
        }

    try:
        from neo4j_integration import get_neo4j_database, is_neo4j_available

        available = is_neo4j_available()
        return {
            "status": "available" if available else "unavailable",
            "configured": True,
            "database": get_neo4j_database() or database,
            "runtime_env": runtime_env,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "configured": True,
            "database": database,
            "runtime_env": runtime_env,
            "error": str(exc),
        }


def probe_neo4j_health(base_url: str, *, runtime_env_file: str = "", skip_runtime_env: bool = False) -> dict[str, Any]:
    local_runtime = _local_neo4j_runtime_status(runtime_env_file, skip_runtime_env=skip_runtime_env)
    req = urllib.request.Request(f"{base_url.rstrip('/')}/api/neo4j/health", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
            payload = json.loads(body.decode("utf-8")) if body else {}
            server_status = str(payload.get("status") or "").strip() or "unverified"
            if server_status not in {"available", "unavailable"}:
                server_status = "unverified"
            return {
                "http_status": resp.status,
                "neo4j_available": bool(payload.get("neo4j_available")),
                "status": server_status,
                "server_status": server_status,
                "server_configured": (bool(payload.get("configured")) if "configured" in payload else None),
                "database": str(payload.get("database") or local_runtime.get("database") or ""),
                "timestamp": str(payload.get("timestamp") or ""),
                "local_runtime_status": str(local_runtime.get("status") or "unverified"),
                "local_runtime_configured": bool(local_runtime.get("configured")),
                "local_runtime_env": local_runtime.get("runtime_env") or {},
                "probe_scope": "local" if _is_local_base_url(base_url) else "remote",
            }
    except Exception as exc:
        return {
            "http_status": 0,
            "neo4j_available": False,
            "status": "unverified",
            "server_status": "unverified",
            "timestamp": "",
            "error": str(exc),
            "database": str(local_runtime.get("database") or ""),
            "local_runtime_status": str(local_runtime.get("status") or "unverified"),
            "local_runtime_configured": bool(local_runtime.get("configured")),
            "local_runtime_env": local_runtime.get("runtime_env") or {},
            "probe_scope": "local" if _is_local_base_url(base_url) else "remote",
        }


def _overall_verdict(summary: dict[str, Any]) -> str:
    if summary["cases_with_failures"] > 0:
        return "FAIL"
    neo4j = summary.get("neo4j") if isinstance(summary.get("neo4j"), dict) else {}
    if bool(neo4j.get("required")) and str(neo4j.get("status") or "") != "available":
        return "FAIL"
    gauntlet_verdict = str(summary["query_to_dossier"]["overall_verdict"])
    readiness_verdict = str(summary["readiness"]["overall_verdict"])
    prime_time_verdict = str(summary["prime_time"]["prime_time_verdict"])
    if gauntlet_verdict == "PASS" and readiness_verdict == "GO" and prime_time_verdict == "READY":
        return "PASS"
    if _gate_success(gauntlet_verdict, {"PASS"}) and _gate_success(readiness_verdict, {"GO"}) and _gate_success(prime_time_verdict, {"READY"}):
        return "PASS_WITH_SKIPS"
    return "FAIL"


def render_markdown(summary: dict[str, Any]) -> str:
    graph_95 = summary.get("graph_95") if isinstance(summary.get("graph_95"), dict) else {}
    thin_vendor_wave = summary.get("thin_vendor_wave") if isinstance(summary.get("thin_vendor_wave"), dict) else {}
    thin_vendor_kpi = thin_vendor_wave.get("kpi_gate") if isinstance(thin_vendor_wave.get("kpi_gate"), dict) else {}
    lines = [
        "# Helios Beta Hardening Report",
        "",
        f"Generated: {summary['generated_at']}",
        f"Graph depth: {summary['graph_depth']}",
        "",
        "## Summary",
        "",
        f"- Cases checked: {summary['cases_checked']}",
        f"- Cases with failures: {summary['cases_with_failures']}",
        f"- HTML dossier failures: {summary['html_failures']}",
        f"- PDF dossier failures: {summary['pdf_failures']}",
        f"- Graph failures: {summary['graph_failures']}",
        f"- Cases missing AI brief despite cached analysis: {summary['ai_missing']}",
        f"- Cases without warmed AI yet: {summary['ai_not_warmed']}",
        f"- Cases missing monitoring history: {summary['monitoring_missing']}",
        f"- Total warnings: {summary['warning_count']}",
        "",
        "## Neo4j",
        "",
        f"- Required: **{'yes' if summary['neo4j']['required'] else 'no'}**",
        f"- Available: **{'yes' if summary['neo4j']['neo4j_available'] else 'no'}**",
        f"- Status: `{summary['neo4j']['status']}`",
        f"- Probe scope: `{summary['neo4j'].get('probe_scope', '')}`",
        f"- Server status: `{summary['neo4j'].get('server_status', '')}`",
        f"- Server configured: `{summary['neo4j'].get('server_configured', 'unknown')}`",
        f"- Local runtime status: `{summary['neo4j'].get('local_runtime_status', '')}`",
        f"- Local runtime env: `{(summary['neo4j'].get('local_runtime_env') or {}).get('path', '')}`",
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
        "## Tier Mix",
        "",
    ]
    for tier, count in sorted(summary["tiers"].items()):
        lines.append(f"- {tier}: {count}")

    lines.extend(["", "## Case Results", ""])

    for case in summary["cases"]:
        lines.extend([
            f"### {case['vendor_name']} ({case['case_id']})",
            "",
            f"- Tier: {case['tier']}",
            f"- HTML dossier: {'PASS' if case['html_ok'] else 'FAIL'} in {case['html_ms']} ms",
            f"- PDF dossier: {'PASS' if case['pdf_ok'] else 'FAIL'} in {case['pdf_ms']} ms",
            f"- Graph payload: {'PASS' if case['graph_ok'] else 'FAIL'} in {case['graph_ms']} ms",
            f"- Graph counts: {case['graph_entities']} entities, {case['graph_relationships']} relationships, {case['graph_corroborated_edges']} corroborated edges",
            f"- Monitoring history: {'present' if case['monitoring_ready'] else 'missing'}",
            f"- AI brief: {'present' if case['ai_ready'] else ('not warmed yet' if not case['ai_expected'] else 'missing')}",
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

    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_helios_readiness_report.py"),
        "--report-dir",
        str(Path(args.report_dir) / "readiness"),
        "--print-json",
        "--base-url",
        args.readiness_base_url,
    ]
    if args.readiness_token:
        command.extend(["--token", args.readiness_token])
    else:
        if args.readiness_email:
            command.extend(["--email", args.readiness_email])
        if args.readiness_password:
            command.extend(["--password", args.readiness_password])
    for company in args.readiness_company:
        command.extend(["--company", company])
    proc = subprocess.run(command, text=True, capture_output=True, cwd=ROOT)
    if proc.returncode not in {0, 1, 2}:
        stderr = proc.stderr.strip() or "unknown readiness error"
        raise RuntimeError(f"helios readiness failed: {stderr}")
    payload = _decode_json_from_stdout(proc.stdout)
    if not isinstance(payload, dict):
        detail = proc.stderr.strip() or proc.stdout.strip() or "readiness did not emit JSON"
        raise RuntimeError(f"helios readiness failed: {detail}")
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

    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_query_to_dossier_gauntlet.py"),
        "--mode",
        args.gauntlet_mode,
        "--report-dir",
        str(Path(args.report_dir) / "query-to-dossier"),
        "--base-url",
        args.gauntlet_base_url,
        "--print-json",
    ]
    if args.gauntlet_spec_file:
        command.extend(["--spec-file", args.gauntlet_spec_file])
    if args.gauntlet_token:
        command.extend(["--token", args.gauntlet_token])
    else:
        if args.gauntlet_email:
            command.extend(["--email", args.gauntlet_email])
        if args.gauntlet_password:
            command.extend(["--password", args.gauntlet_password])

    proc = subprocess.run(command, text=True, capture_output=True, cwd=ROOT)
    if proc.returncode not in {0, 1}:
        stderr = proc.stderr.strip() or "unknown gauntlet error"
        raise RuntimeError(f"query-to-dossier gauntlet failed: {stderr}")
    payload = _decode_json_from_stdout(proc.stdout)
    if not isinstance(payload, dict):
        detail = proc.stderr.strip() or proc.stdout.strip() or "query-to-dossier gauntlet did not emit JSON"
        raise RuntimeError(f"query-to-dossier gauntlet failed: {detail}")
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
    output_json = report_dir / f"helios-prime-time-{stamp}.json"
    output_md = report_dir / f"helios-prime-time-{stamp}.md"
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
    proc = subprocess.run(command, text=True, capture_output=True, cwd=ROOT)
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

    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_thin_vendor_refresh_wave.py"),
        "--report-dir",
        str(Path(args.report_dir) / "thin_vendor_refresh_wave"),
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
    proc = subprocess.run(command, text=True, capture_output=True, cwd=ROOT)
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "unknown thin-vendor wave error"
        raise RuntimeError(f"thin-vendor wave failed: {stderr}")
    payload = _decode_json_from_stdout(proc.stdout)
    if not isinstance(payload, dict):
        detail = proc.stderr.strip() or proc.stdout.strip() or "thin-vendor wave did not emit JSON"
        raise RuntimeError(f"thin-vendor wave failed: {detail}")
    payload["returncode"] = proc.returncode
    payload["report_md"] = str(payload.get("report_markdown") or "")
    return payload


def main() -> int:
    args = parse_args()
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    selected_case_ids = list(args.case_id)
    selected_case_ids.extend(load_case_ids_from_cohort(args.cohort_file))
    deduped_case_ids = list(dict.fromkeys(selected_case_ids))

    vendors = select_cases(deduped_case_ids, args.limit)
    if not vendors:
        raise SystemExit("No scored cases found for hardening report")

    results = [run_case(vendor, args.graph_depth, warm_monitoring=args.warm_monitoring) for vendor in vendors]
    summary = build_summary(results, args.graph_depth)
    summary["neo4j"] = probe_neo4j_health(
        args.gauntlet_base_url,
        runtime_env_file=args.runtime_env_file,
        skip_runtime_env=args.skip_runtime_env,
    )
    summary["neo4j"]["required"] = bool(args.require_neo4j)
    summary["query_to_dossier"] = run_query_to_dossier(args)
    summary["readiness"] = run_readiness(args)
    summary["graph_95"] = _load_graph_95_status()
    summary["thin_vendor_wave"] = run_thin_vendor_wave(args)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    summary["prime_time"] = run_prime_time(args, summary["readiness"], summary["query_to_dossier"], report_dir, stamp)
    summary["overall_verdict"] = _overall_verdict(summary)
    json_path = report_dir / f"helios-beta-hardening-report-{stamp}.json"
    md_path = report_dir / f"helios-beta-hardening-report-{stamp}.md"

    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")

    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    if args.print_json:
        print(json.dumps(summary, indent=2))
    return 0 if summary["overall_verdict"] in {"PASS", "PASS_WITH_SKIPS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
