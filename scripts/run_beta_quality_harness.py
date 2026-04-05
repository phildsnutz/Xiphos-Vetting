#!/usr/bin/env python3
"""
Run a repeatable beta quality harness against a running Helios API.

The harness validates the highest-signal beta surfaces for one or more cases:
  - dossier HTML and PDF integrity
  - graph entity and relationship integrity
  - monitoring trigger plus monitor-history persistence
  - AI narrative readiness and content presence

It is API-driven so it can run against local dev, staging, or hosted Helios.
"""

from __future__ import annotations

import argparse
import io
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "beta_quality_harness"

HTML_SECTION_CHECKS = {
    "executive_strip": "Recent change",
    "risk_storyline": "Risk Storyline",
    "supplier_passport": "Supplier passport",
    "graph_provenance": "Graph Provenance Snapshot",
    "ai_brief": "Axiom Assessment",
    "recommended_actions": "Recommended Actions",
    "findings_table": "OSINT Findings",
}

PDF_SECTION_CHECKS = {
    "risk_storyline": "RISK STORYLINE",
    "supplier_passport": "SUPPLIER PASSPORT",
    "graph_provenance": "GRAPH PROVENANCE SNAPSHOT",
    "ai_brief": "AXIOM ASSESSMENT",
    "executive_action": "EXECUTIVE ACTION",
    "evidence_snapshot": "EVIDENCE SNAPSHOT",
}


class ApiClientProtocol(Protocol):
    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int = 30,
    ) -> tuple[int, dict[str, str], Any]: ...

    def request_bytes(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int = 30,
    ) -> tuple[int, dict[str, str], bytes]: ...


@dataclass
class CheckResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseHarnessResult:
    case_id: str
    vendor_name: str
    overall_passed: bool
    checks: dict[str, CheckResult]
    failures: list[str]
    warnings: list[str]
    workflow_lane: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "vendor_name": self.vendor_name,
            "workflow_lane": self.workflow_lane,
            "overall_passed": self.overall_passed,
            "checks": {name: asdict(result) for name, result in self.checks.items()},
            "failures": list(self.failures),
            "warnings": list(self.warnings),
        }


class HttpApiClient:
    def __init__(self, base_url: str, headers: dict[str, str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers or {})

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int = 30,
    ) -> tuple[int, dict[str, str], Any]:
        status, headers, body = self.request_bytes(method, path, payload, timeout=timeout)
        if not body:
            return status, headers, None
        return status, headers, json.loads(body.decode("utf-8"))

    def request_bytes(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int = 30,
    ) -> tuple[int, dict[str, str], bytes]:
        data = None
        headers = dict(self.headers)
        if payload is not None:
            headers.setdefault("Content-Type", "application/json")
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Helios beta quality harness.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--login-wait-seconds", type=int, default=0)
    parser.add_argument("--case-id", action="append", default=[], help="Case/vendor id to validate")
    parser.add_argument("--replay-file", default="", help="Optional JSON file with case descriptors")
    parser.add_argument("--limit", type=int, default=5, help="Recent-case fallback when no explicit case IDs are given")
    parser.add_argument("--graph-depth", type=int, default=3)
    parser.add_argument("--analysis-timeout-seconds", type=int, default=120)
    parser.add_argument("--monitor-history-wait-seconds", type=int, default=10)
    parser.add_argument("--skip-monitor-trigger", action="store_true")
    parser.add_argument("--skip-ai-trigger", action="store_true")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _bool_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def login_with_retry(base_url: str, email: str, password: str, *, wait_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + max(wait_seconds, 0)
    last_error: Exception | None = None
    while True:
        try:
            client = HttpApiClient(base_url)
            status, _, payload = client.request_json(
                "POST",
                "/api/auth/login",
                {"email": email, "password": password},
                timeout=20,
            )
            if status == 200 and isinstance(payload, dict):
                return payload
            last_error = RuntimeError(f"auth login returned {status}")
        except Exception as exc:  # pragma: no cover - network fallback
            last_error = exc

        if time.monotonic() >= deadline:
            raise last_error or RuntimeError("auth login failed")
        time.sleep(2.0)


def load_replay_cases(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("Replay file must contain a JSON list")
    cases: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict) or not entry.get("id"):
            raise SystemExit("Each replay entry must be an object with at least an `id` field")
        cases.append(dict(entry))
    return cases


def select_cases(client: ApiClientProtocol, args: argparse.Namespace) -> list[dict[str, Any]]:
    explicit: list[dict[str, Any]] = [{"id": case_id} for case_id in args.case_id]
    if args.replay_file:
        explicit.extend(load_replay_cases(args.replay_file))
    if explicit:
        deduped: dict[str, dict[str, Any]] = {}
        for entry in explicit:
            deduped[str(entry["id"])] = entry
        return list(deduped.values())

    status, _, payload = client.request_json("GET", f"/api/cases?limit={max(args.limit, 1)}", timeout=30)
    if status != 200 or not isinstance(payload, dict):
        raise SystemExit(f"/api/cases returned {status}")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SystemExit("No cases found for beta quality harness")
    return [{"id": case.get("id"), "name": case.get("vendor_name"), "workflow_lane": case.get("workflow_lane")} for case in cases if case.get("id")]


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


def validate_section_checks(document: str, checks: dict[str, str], prefix: str) -> tuple[bool, list[str]]:
    failures = [f"{prefix} missing {name.replace('_', ' ')}" for name, marker in checks.items() if marker not in document]
    return not failures, failures


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


def validate_dossier_outputs(html: str, pdf_bytes: bytes) -> CheckResult:
    failures: list[str] = []
    warnings: list[str] = []
    html_ok, html_failures = validate_section_checks(html, HTML_SECTION_CHECKS, "html dossier")
    failures.extend(html_failures)
    pdf_text, pdf_warnings = extract_pdf_text(pdf_bytes)
    warnings.extend(pdf_warnings)
    pdf_ok, pdf_failures = validate_section_checks(pdf_text.upper(), PDF_SECTION_CHECKS, "pdf dossier")
    failures.extend(pdf_failures)
    if len(html.strip()) < 4000:
        failures.append("html dossier body is unexpectedly short")
    if len(pdf_bytes) < 4000:
        failures.append("pdf dossier bytes are unexpectedly short")
    return CheckResult(
        passed=html_ok and pdf_ok and not failures,
        failures=failures,
        warnings=warnings,
        metrics={
            "html_length": len(html),
            "pdf_bytes": len(pdf_bytes),
            "pdf_text_length": len(pdf_text),
        },
    )


def validate_graph_integrity(graph: dict[str, Any], spec: dict[str, Any]) -> CheckResult:
    passed, stats, failures, warnings = validate_graph_payload(graph)
    entities = graph.get("entities", []) if isinstance(graph, dict) else []
    relationships = graph.get("relationships", []) if isinstance(graph, dict) else []
    entity_ids = {str(entity.get("id")) for entity in entities if isinstance(entity, dict) and entity.get("id") is not None}
    incident_ids: set[str] = set()
    relationship_types: set[str] = set()
    self_edges = 0
    for rel in relationships:
        source_id = str(rel.get("source_entity_id") or "")
        target_id = str(rel.get("target_entity_id") or "")
        if source_id:
            incident_ids.add(source_id)
        if target_id:
            incident_ids.add(target_id)
        if source_id and source_id == target_id:
            self_edges += 1
        rel_type = str(rel.get("rel_type") or rel.get("relationship_type") or "").strip()
        if rel_type:
            relationship_types.add(rel_type)

    orphan_nodes = 0
    if len(entity_ids) > 1:
        orphan_nodes = len(entity_ids - incident_ids)
        if orphan_nodes:
            failures.append(f"graph contains {orphan_nodes} orphan node(s)")
    if self_edges:
        failures.append(f"graph contains {self_edges} self-referencing edge(s)")

    min_entities = spec.get("graph_entity_min")
    if _bool_number(min_entities) and stats["entities"] < int(min_entities):
        failures.append(f"graph entity count {stats['entities']} below minimum {int(min_entities)}")
    max_entities = spec.get("graph_entity_max")
    if _bool_number(max_entities) and stats["entities"] > int(max_entities):
        failures.append(f"graph entity count {stats['entities']} above maximum {int(max_entities)}")

    required_relationship_types = spec.get("required_relationship_types")
    if isinstance(required_relationship_types, list) and required_relationship_types:
        missing_types = [
            rel_type for rel_type in required_relationship_types
            if str(rel_type) not in relationship_types
        ]
        if missing_types:
            failures.append(f"graph missing required relationship types: {', '.join(sorted(str(item) for item in missing_types))}")

    return CheckResult(
        passed=passed and not failures,
        failures=failures,
        warnings=warnings,
        metrics={
            **stats,
            "orphan_nodes": orphan_nodes,
            "self_edges": self_edges,
            "relationship_types": sorted(relationship_types),
        },
    )


def validate_monitor_history(payload: dict[str, Any]) -> CheckResult:
    failures: list[str] = []
    warnings: list[str] = []
    runs = payload.get("runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list) or not runs:
        return CheckResult(False, ["monitor history is empty"], warnings, {"run_count": 0})

    latest = next((run for run in runs if str(run.get("status") or "") == "completed"), runs[0])
    delta_summary = str(latest.get("delta_summary") or "").strip()
    if str(latest.get("status") or "") != "completed":
        failures.append(f"latest monitor run status is {latest.get('status')}")
    if not delta_summary:
        failures.append("latest monitor run delta_summary is empty")
    if not _bool_number(latest.get("score_before")):
        failures.append("latest monitor run score_before is not numeric")
    if not _bool_number(latest.get("score_after")):
        failures.append("latest monitor run score_after is not numeric")

    return CheckResult(
        passed=not failures,
        failures=failures,
        warnings=warnings,
        metrics={
            "run_count": len(runs),
            "latest_run_id": latest.get("run_id"),
            "latest_status": latest.get("status"),
            "change_type": latest.get("change_type"),
            "new_findings_count": latest.get("new_findings_count"),
            "score_before": latest.get("score_before"),
            "score_after": latest.get("score_after"),
        },
    )


def _analysis_payload_has_content(payload: dict[str, Any]) -> bool:
    analysis = payload.get("analysis") if isinstance(payload, dict) else None
    if not isinstance(analysis, dict):
        return False
    text_fields = (
        "executive_summary",
        "risk_narrative",
        "confidence_assessment",
        "verdict",
        "regulatory_exposure",
    )
    list_fields = (
        "critical_concerns",
        "mitigating_factors",
        "recommended_actions",
    )
    if any(str(analysis.get(field) or "").strip() for field in text_fields):
        return True
    return any(isinstance(analysis.get(field), list) and analysis.get(field) for field in list_fields)


def validate_ai_narrative(status_payload: dict[str, Any], analysis_payload: dict[str, Any]) -> CheckResult:
    failures: list[str] = []
    warnings: list[str] = []
    status = str(status_payload.get("status") or "").strip()
    if status != "ready":
        failures.append(f"analysis status is {status or 'missing'}")
    if not _analysis_payload_has_content(analysis_payload):
        failures.append("analysis payload is empty")
    return CheckResult(
        passed=not failures,
        failures=failures,
        warnings=warnings,
        metrics={
            "status": status,
            "provider": analysis_payload.get("provider") if isinstance(analysis_payload, dict) else None,
            "model": analysis_payload.get("model") if isinstance(analysis_payload, dict) else None,
        },
    )


def _poll_analysis_ready(
    client: ApiClientProtocol,
    case_id: str,
    *,
    timeout_seconds: int,
) -> tuple[int, dict[str, str], Any]:
    deadline = time.monotonic() + max(timeout_seconds, 0)
    while True:
        status, headers, payload = client.request_json("GET", f"/api/cases/{case_id}/analysis-status", timeout=30)
        if status != 200:
            return status, headers, payload
        if isinstance(payload, dict) and str(payload.get("status") or "") in {"ready", "failed"}:
            return status, headers, payload
        if time.monotonic() >= deadline:
            return status, headers, payload
        time.sleep(2.0)


def _wait_for_monitor_history(
    client: ApiClientProtocol,
    case_id: str,
    *,
    timeout_seconds: int,
) -> tuple[int, dict[str, str], Any]:
    deadline = time.monotonic() + max(timeout_seconds, 0)
    while True:
        status, headers, payload = client.request_json("GET", f"/api/cases/{case_id}/monitor/history?limit=10", timeout=30)
        if status == 200 and isinstance(payload, dict) and isinstance(payload.get("runs"), list) and payload.get("runs"):
            return status, headers, payload
        if time.monotonic() >= deadline:
            return status, headers, payload
        time.sleep(1.0)


def run_case_harness(
    client: ApiClientProtocol,
    spec: dict[str, Any],
    *,
    graph_depth: int,
    analysis_timeout_seconds: int,
    monitor_history_wait_seconds: int,
    trigger_monitor: bool,
    trigger_ai: bool,
) -> CaseHarnessResult:
    case_id = str(spec["id"])
    failures: list[str] = []
    warnings: list[str] = []
    checks: dict[str, CheckResult] = {}

    detail_status, _, detail_payload = client.request_json("GET", f"/api/cases/{case_id}", timeout=30)
    if detail_status != 200 or not isinstance(detail_payload, dict):
        result = CheckResult(False, [f"/api/cases/{case_id} returned {detail_status}"], [], {})
        return CaseHarnessResult(
            case_id=case_id,
            vendor_name=str(spec.get("name") or case_id),
            workflow_lane=str(spec.get("workflow_lane") or ""),
            overall_passed=False,
            checks={"case_detail": result},
            failures=list(result.failures),
            warnings=[],
        )

    vendor_name = str(detail_payload.get("vendor_name") or spec.get("name") or case_id)
    workflow_lane = str(detail_payload.get("workflow_lane") or spec.get("workflow_lane") or "")

    if trigger_monitor:
        monitor_status, _, monitor_payload = client.request_json(
            "POST",
            f"/api/cases/{case_id}/monitor",
            {"sync": True},
            timeout=180,
        )
        if monitor_status not in {200, 202}:
            checks["monitor_trigger"] = CheckResult(False, [f"/api/cases/{case_id}/monitor returned {monitor_status}"], [], {})
        else:
            checks["monitor_trigger"] = CheckResult(
                True,
                [],
                [],
                {
                    "status_code": monitor_status,
                    "mode": monitor_payload.get("mode") if isinstance(monitor_payload, dict) else None,
                },
            )
    else:
        checks["monitor_trigger"] = CheckResult(True, [], ["monitor trigger skipped"], {"skipped": True})

    history_status, _, history_payload = _wait_for_monitor_history(
        client,
        case_id,
        timeout_seconds=monitor_history_wait_seconds,
    )
    if history_status != 200 or not isinstance(history_payload, dict):
        checks["monitor_history"] = CheckResult(False, [f"/api/cases/{case_id}/monitor/history returned {history_status}"], [], {})
    else:
        checks["monitor_history"] = validate_monitor_history(history_payload)

    analysis_status_code, _, analysis_status_payload = client.request_json(
        "GET",
        f"/api/cases/{case_id}/analysis-status",
        timeout=30,
    )
    if trigger_ai and analysis_status_code == 200 and isinstance(analysis_status_payload, dict):
        current_status = str(analysis_status_payload.get("status") or "")
        if current_status != "ready":
            client.request_json("POST", f"/api/cases/{case_id}/analyze-async", {}, timeout=30)
            analysis_status_code, _, analysis_status_payload = _poll_analysis_ready(
                client,
                case_id,
                timeout_seconds=analysis_timeout_seconds,
            )
    elif not trigger_ai:
        warnings.append("analysis trigger skipped")

    analysis_payload: Any = None
    if analysis_status_code == 200 and isinstance(analysis_status_payload, dict) and str(analysis_status_payload.get("status") or "") == "ready":
        _, _, analysis_payload = client.request_json("GET", f"/api/cases/{case_id}/analysis", timeout=30)
    if not isinstance(analysis_status_payload, dict):
        checks["ai_narrative"] = CheckResult(False, [f"/api/cases/{case_id}/analysis-status returned {analysis_status_code}"], [], {})
    else:
        checks["ai_narrative"] = validate_ai_narrative(
            analysis_status_payload,
            analysis_payload if isinstance(analysis_payload, dict) else {},
        )

    dossier_html_status, _, dossier_html_bytes = client.request_bytes(
        "POST",
        f"/api/cases/{case_id}/dossier",
        {"format": "html", "include_ai": True},
        timeout=120,
    )
    dossier_pdf_status, _, dossier_pdf_bytes = client.request_bytes(
        "POST",
        f"/api/cases/{case_id}/dossier-pdf",
        {"include_ai": True},
        timeout=120,
    )
    if dossier_html_status != 200:
        checks["dossier_integrity"] = CheckResult(False, [f"/api/cases/{case_id}/dossier returned {dossier_html_status}"], [], {})
    elif dossier_pdf_status != 200:
        checks["dossier_integrity"] = CheckResult(False, [f"/api/cases/{case_id}/dossier-pdf returned {dossier_pdf_status}"], [], {})
    else:
        html = dossier_html_bytes.decode("utf-8", errors="ignore")
        checks["dossier_integrity"] = validate_dossier_outputs(html, dossier_pdf_bytes)

    graph_status, _, graph_payload = client.request_json("GET", f"/api/cases/{case_id}/graph?depth={graph_depth}", timeout=60)
    if graph_status != 200 or not isinstance(graph_payload, dict):
        checks["graph_integrity"] = CheckResult(False, [f"/api/cases/{case_id}/graph returned {graph_status}"], [], {})
    else:
        checks["graph_integrity"] = validate_graph_integrity(graph_payload, spec)

    for name, result in checks.items():
        if not result.passed:
            failures.extend(f"{name}: {item}" for item in result.failures)
        warnings.extend(f"{name}: {item}" for item in result.warnings)

    return CaseHarnessResult(
        case_id=case_id,
        vendor_name=vendor_name,
        workflow_lane=workflow_lane,
        overall_passed=not failures,
        checks=checks,
        failures=failures,
        warnings=warnings,
    )


def build_summary(
    results: list[CaseHarnessResult],
    *,
    base_url: str,
    graph_depth: int,
    replay_file: str,
) -> dict[str, Any]:
    cases_with_failures = sum(1 for result in results if not result.overall_passed)
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": base_url,
        "graph_depth": graph_depth,
        "replay_file": replay_file,
        "cases_checked": len(results),
        "cases_with_failures": cases_with_failures,
        "overall_verdict": "PASS" if cases_with_failures == 0 else "FAIL",
        "cases": [result.to_dict() for result in results],
    }
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Helios Beta Quality Harness",
        "",
        f"Generated: {summary['generated_at']}",
        f"Base URL: {summary['base_url']}",
        f"Graph depth: {summary['graph_depth']}",
        f"Overall verdict: **{summary['overall_verdict']}**",
        "",
        "## Summary",
        "",
        f"- Cases checked: {summary['cases_checked']}",
        f"- Cases with failures: {summary['cases_with_failures']}",
    ]
    if summary.get("replay_file"):
        lines.append(f"- Replay file: `{summary['replay_file']}`")
    lines.extend(["", "## Case Results", ""])

    for case in summary["cases"]:
        lines.extend([
            f"### {case['vendor_name']} ({case['case_id']})",
            "",
            f"- Workflow lane: `{case.get('workflow_lane') or 'unknown'}`",
            f"- Verdict: **{'PASS' if case['overall_passed'] else 'FAIL'}**",
        ])
        for check_name, check in case["checks"].items():
            lines.append(f"- {check_name}: {'PASS' if check['passed'] else 'FAIL'}")
            if check.get("failures"):
                for failure in check["failures"]:
                    lines.append(f"  - {failure}")
            if check.get("warnings"):
                for warning in check["warnings"]:
                    lines.append(f"  - warning: {warning}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    headers: dict[str, str] = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    elif args.email and args.password:
        login = login_with_retry(
            args.base_url,
            args.email,
            args.password,
            wait_seconds=args.login_wait_seconds,
        )
        headers["Authorization"] = f"Bearer {login['token']}"

    client = HttpApiClient(args.base_url, headers=headers)
    selected_cases = select_cases(client, args)
    results = [
        run_case_harness(
            client,
            spec,
            graph_depth=args.graph_depth,
            analysis_timeout_seconds=args.analysis_timeout_seconds,
            monitor_history_wait_seconds=args.monitor_history_wait_seconds,
            trigger_monitor=not args.skip_monitor_trigger,
            trigger_ai=not args.skip_ai_trigger,
        )
        for spec in selected_cases
    ]
    summary = build_summary(
        results,
        base_url=args.base_url,
        graph_depth=args.graph_depth,
        replay_file=args.replay_file,
    )

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output_dir = Path(args.report_dir) / stamp
    output_dir.mkdir(parents=True, exist_ok=True)
    output_json = output_dir / "summary.json"
    output_md = output_dir / "summary.md"
    output_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    output_md.write_text(render_markdown(summary), encoding="utf-8")
    summary["report_json"] = str(output_json)
    summary["report_md"] = str(output_md)

    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"{summary['overall_verdict']}: beta quality harness ({len(results)} cases)")
        print(f"JSON: {output_json}")
        print(f"Markdown: {output_md}")

    return 0 if summary["overall_verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
