#!/usr/bin/env python3
"""
Canonical end-to-end gauntlet for the Helios analyst path from query to dossier.

This harness is intentionally layered:
  - fixture mode: deterministic in-process Flask client with isolated temp data
  - local-auth mode: real HTTP flow against a running local server with auth

Assertions are invariant-based instead of byte-for-byte goldens so healthy
evolution of narrative copy or rendering does not create false regressions.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


DEFAULT_COMPARE_PAYLOAD = {
    "name": "Boeing",
    "country": "US",
    "profiles": ["defense_acquisition", "commercial_supply_chain"],
}

DEFAULT_CASE_PAYLOAD = {
    "name": "Gauntlet Vendor",
    "country": "US",
    "ownership": {
        "publicly_traded": False,
        "state_owned": False,
        "beneficial_owner_known": True,
        "ownership_pct_resolved": 0.9,
        "shell_layers": 0,
        "pep_connection": False,
    },
    "data_quality": {
        "has_lei": True,
        "has_cage": True,
        "has_duns": True,
        "has_tax_id": True,
        "has_audited_financials": True,
        "years_of_records": 8,
    },
    "exec": {
        "known_execs": 4,
        "adverse_media": 0,
        "pep_execs": 0,
        "litigation_history": 0,
    },
    "program": "dod_unclassified",
    "profile": "defense_acquisition",
}

ASSISTANT_PROMPT = "Trace the strongest control path and explain the current risk posture."
HTML_MARKERS = ("<html", "Supplier passport", "Risk Storyline")


@dataclass
class StepResult:
    step: str
    status: str
    duration_ms: int
    details: dict[str, Any]


class GauntletFailure(RuntimeError):
    pass


class BaseClient:
    def request_json(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 60) -> tuple[int, dict[str, str], Any]:
        raise NotImplementedError

    def request_bytes(self, method: str, path: str, payload: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 60) -> tuple[int, dict[str, str], bytes]:
        raise NotImplementedError


class HttpGauntletClient(BaseClient):
    def __init__(self, base_url: str, headers: dict[str, str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}

    def request_json(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 60) -> tuple[int, dict[str, str], Any]:
        data = None
        headers = dict(self.headers)
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, dict(resp.headers), json.loads(body.decode("utf-8")) if body else None

    def request_bytes(
        self,
        method: str,
        path: str,
        payload: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> tuple[int, dict[str, str], bytes]:
        req_headers = dict(self.headers)
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(f"{self.base_url}{path}", data=payload, headers=req_headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()


class FlaskGauntletClient(BaseClient):
    def __init__(self, client, headers: dict[str, str] | None = None):
        self.client = client
        self.headers = headers or {}

    def request_json(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 60) -> tuple[int, dict[str, str], Any]:
        response = self.client.open(path, method=method, json=payload, headers=self.headers)
        return response.status_code, dict(response.headers), response.get_json(silent=True)

    def request_bytes(
        self,
        method: str,
        path: str,
        payload: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> tuple[int, dict[str, str], bytes]:
        req_headers = dict(self.headers)
        if headers:
            req_headers.update(headers)
        response = self.client.open(path, method=method, data=payload, headers=req_headers)
        return response.status_code, dict(response.headers), response.get_data()


@contextmanager
def _temporary_env(updates: dict[str, str | None]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def fixture_client_context() -> Iterator[BaseClient]:
    with tempfile.TemporaryDirectory(prefix="helios-gauntlet-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        env = {
            "XIPHOS_DATA_DIR": str(tmp_root / "data"),
            "XIPHOS_DB_PATH": str(tmp_root / "xiphos-fixture.db"),
            "XIPHOS_KG_DB_PATH": str(tmp_root / "knowledge-graph.db"),
            "XIPHOS_SECURE_ARTIFACTS_DIR": str(tmp_root / "secure-artifacts"),
            "XIPHOS_AUTH_ENABLED": "true",
            "XIPHOS_SECRET_KEY": "gauntlet-secret-key",
            "XIPHOS_DEV_MODE": None,
        }
        with _temporary_env(env):
            if "server" in sys.modules:
                server = importlib.reload(sys.modules["server"])
            else:
                server = importlib.import_module("server")

            server.db.init_db()
            server.init_auth_db()
            if server.HAS_AI:
                server.init_ai_tables()

            import auth as auth_module
            import hardening

            hardening.reset_rate_limiter()
            auth_module.create_user("analyst@example.com", "AnalystPass123!", name="Analyst", role="analyst")

            previous_disable = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
            try:
                with server.app.test_client() as test_client:
                    login = test_client.post(
                        "/api/auth/login",
                        json={"email": "analyst@example.com", "password": "AnalystPass123!"},
                    )
                    if login.status_code != 200:
                        raise GauntletFailure(f"fixture login failed: {login.status_code}")
                    token = login.get_json()["token"]
                    yield FlaskGauntletClient(test_client, {"Authorization": f"Bearer {token}"})
            finally:
                logging.disable(previous_disable)


def _assert(condition: bool, message: str):
    if not condition:
        raise GauntletFailure(message)


def _normalize_headers(headers: dict[str, Any]) -> dict[str, str]:
    return {str(key): str(value) for key, value in headers.items()}


def _run_step(results: list[StepResult], step: str, fn):
    started = time.perf_counter()
    try:
        details = fn()
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        results.append(
            StepResult(
                step=step,
                status="FAIL",
                duration_ms=duration_ms,
                details={"error": str(exc)},
            )
        )
        raise
    duration_ms = int((time.perf_counter() - started) * 1000)
    results.append(
        StepResult(
            step=step,
            status="PASS",
            duration_ms=duration_ms,
            details=details or {},
        )
    )
    return details


def login_http(base_url: str, email: str, password: str) -> dict[str, Any]:
    payload = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        return json.loads(body.decode("utf-8"))


def run_query_to_dossier_flow(client: BaseClient, *, case_name_prefix: str = "Gauntlet Vendor") -> dict[str, Any]:
    results: list[StepResult] = []
    warnings: list[str] = []

    health = _run_step(
        results,
        "health",
        lambda: _step_health(client),
    )
    _run_step(results, "ai_providers", lambda: _step_ai_providers(client))
    _run_step(results, "compare", lambda: _step_compare(client))
    created = _run_step(results, "create_case", lambda: _step_create_case(client, case_name_prefix=case_name_prefix))
    case_id = created["case_id"]
    _run_step(results, "case_detail", lambda: _step_case_detail(client, case_id))
    _run_step(results, "graph", lambda: _step_graph(client, case_id))
    _run_step(results, "supplier_passport", lambda: _step_supplier_passport(client, case_id))
    plan = _run_step(results, "assistant_plan", lambda: _step_assistant_plan(client, case_id))
    _run_step(results, "assistant_execute", lambda: _step_assistant_execute(client, case_id, plan))
    dossier_html = _run_step(results, "dossier_html", lambda: _step_dossier_html(client, case_id))
    _run_step(results, "dossier_pdf", lambda: _step_dossier_pdf(client, case_id))

    total_ms = sum(item.duration_ms for item in results)
    return {
        "flow_verdict": "PASS",
        "case_id": case_id,
        "vendor_name": created["vendor_name"],
        "health": health,
        "download_url": dossier_html.get("download_url"),
        "warning_count": len(warnings),
        "warnings": warnings,
        "steps": [asdict(item) for item in results],
        "total_ms": total_ms,
    }


def _step_health(client: BaseClient) -> dict[str, Any]:
    status, _, body = client.request_json("GET", "/api/health", timeout=30)
    _assert(status == 200 and isinstance(body, dict), f"/api/health returned {status}")
    return {
        "osint_connectors": int(body.get("osint_connector_count", 0)),
        "osint_enabled": body.get("osint_enabled"),
    }


def _step_ai_providers(client: BaseClient) -> dict[str, Any]:
    status, _, body = client.request_json("GET", "/api/ai/providers", timeout=30)
    _assert(status == 200 and isinstance(body, dict), f"/api/ai/providers returned {status}")
    providers = body.get("providers") or []
    _assert(isinstance(providers, list) and len(providers) >= 1, "ai providers surface returned no providers")
    return {"provider_count": len(providers)}


def _step_compare(client: BaseClient) -> dict[str, Any]:
    status, _, body = client.request_json("POST", "/api/compare", payload=DEFAULT_COMPARE_PAYLOAD, timeout=45)
    _assert(status == 200 and isinstance(body, dict), f"/api/compare returned {status}")
    comparisons = body.get("comparisons") or []
    entity = body.get("entity") or {}
    _assert(entity.get("name") == DEFAULT_COMPARE_PAYLOAD["name"], "compare entity name mismatch")
    _assert(len(comparisons) >= 1, "compare returned no profile comparisons")
    _assert(all("tier" in item for item in comparisons), "compare response missing tier")
    return {"comparison_count": len(comparisons)}


def _step_create_case(client: BaseClient, *, case_name_prefix: str) -> dict[str, Any]:
    payload = dict(DEFAULT_CASE_PAYLOAD)
    payload["name"] = f"{case_name_prefix} {int(time.time())}"
    status, _, body = client.request_json("POST", "/api/cases", payload=payload, timeout=45)
    _assert(status == 201 and isinstance(body, dict), f"/api/cases returned {status}")
    case_id = body.get("case_id")
    _assert(bool(case_id), "case creation did not return case_id")
    return {"case_id": case_id, "vendor_name": payload["name"]}


def _step_case_detail(client: BaseClient, case_id: str) -> dict[str, Any]:
    status, _, body = client.request_json("GET", f"/api/cases/{case_id}", timeout=45)
    _assert(status == 200 and isinstance(body, dict), f"/api/cases/{case_id} returned {status}")
    _assert(body.get("id") == case_id, "case detail id mismatch")
    _assert("storyline" in body, "case detail missing storyline field")
    return {"has_storyline": body.get("storyline") is not None}


def _step_graph(client: BaseClient, case_id: str) -> dict[str, Any]:
    status, _, body = client.request_json("GET", f"/api/cases/{case_id}/graph?depth=3", timeout=45)
    _assert(status == 200 and isinstance(body, dict), f"/api/cases/{case_id}/graph returned {status}")
    _assert(not body.get("error"), f"graph returned error: {body.get('error')}")
    entities = body.get("entities") or []
    relationships = body.get("relationships") or []
    _assert(isinstance(entities, list), "graph entities payload is not a list")
    _assert(isinstance(relationships, list), "graph relationships payload is not a list")
    _assert(bool(body.get("root_entity_id")), "graph root entity id missing")
    return {"entity_count": len(entities), "relationship_count": len(relationships)}


def _step_supplier_passport(client: BaseClient, case_id: str) -> dict[str, Any]:
    status, _, body = client.request_json("GET", f"/api/cases/{case_id}/supplier-passport?mode=light", timeout=60)
    _assert(status == 200 and isinstance(body, dict), f"/api/cases/{case_id}/supplier-passport returned {status}")
    _assert(body.get("case_id") == case_id, "supplier passport case id mismatch")
    _assert(bool(body.get("passport_version")), "supplier passport version missing")
    return {
        "passport_version": body.get("passport_version"),
        "posture": body.get("posture"),
    }


def _step_assistant_plan(client: BaseClient, case_id: str) -> dict[str, Any]:
    status, _, body = client.request_json(
        "POST",
        f"/api/cases/{case_id}/assistant-plan",
        payload={"prompt": ASSISTANT_PROMPT},
        timeout=60,
    )
    _assert(status == 200 and isinstance(body, dict), f"/api/cases/{case_id}/assistant-plan returned {status}")
    plan = body.get("plan") or []
    _assert(body.get("case_id") == case_id, "assistant plan case id mismatch")
    _assert(body.get("version") == "ai-control-plane-v1", "assistant plan version mismatch")
    _assert(len(plan) >= 1, "assistant plan returned no steps")
    return body


def _step_assistant_execute(client: BaseClient, case_id: str, plan_body: dict[str, Any]) -> dict[str, Any]:
    approved_tool_ids = [step["tool_id"] for step in plan_body.get("plan", []) if step.get("required")]
    _assert(bool(approved_tool_ids), "assistant plan produced no required tools to approve")
    status, _, body = client.request_json(
        "POST",
        f"/api/cases/{case_id}/assistant-execute",
        payload={
            "prompt": plan_body.get("analyst_prompt") or ASSISTANT_PROMPT,
            "approved_tool_ids": approved_tool_ids,
        },
        timeout=60,
    )
    _assert(status == 200 and isinstance(body, dict), f"/api/cases/{case_id}/assistant-execute returned {status}")
    executed_steps = body.get("executed_steps") or []
    _assert(body.get("case_id") == case_id, "assistant execute case id mismatch")
    _assert(body.get("version") == "ai-control-plane-execution-v1", "assistant execute version mismatch")
    _assert(len(executed_steps) >= 1, "assistant execute returned no executed steps")
    return {"executed_steps": len(executed_steps)}


def _step_dossier_html(client: BaseClient, case_id: str) -> dict[str, Any]:
    status, _, body = client.request_json(
        "POST",
        f"/api/cases/{case_id}/dossier",
        payload={"include_ai": False},
        timeout=90,
    )
    _assert(status == 200 and isinstance(body, dict), f"/api/cases/{case_id}/dossier returned {status}")
    download_url = body.get("download_url")
    _assert(body.get("case_id") == case_id, "dossier html case id mismatch")
    _assert(bool(download_url), "dossier html missing download_url")

    html_status, html_headers, html_bytes = client.request_bytes("GET", download_url, timeout=90)
    html_text = html_bytes.decode("utf-8", errors="replace")
    _assert(html_status == 200, f"dossier download returned {html_status}")
    _assert("text/html" in _normalize_headers(html_headers).get("Content-Type", ""), "dossier download did not return html")
    for marker in HTML_MARKERS:
        _assert(marker.lower() in html_text.lower(), f"dossier html missing marker: {marker}")
    return {"download_url": download_url, "html_bytes": len(html_bytes)}


def _step_dossier_pdf(client: BaseClient, case_id: str) -> dict[str, Any]:
    status, headers, pdf_bytes = client.request_bytes(
        "POST",
        f"/api/cases/{case_id}/dossier-pdf",
        payload=b'{"include_ai": false}',
        headers={"Content-Type": "application/json"},
        timeout=120,
    )
    normalized_headers = _normalize_headers(headers)
    _assert(status == 200, f"/api/cases/{case_id}/dossier-pdf returned {status}")
    _assert(normalized_headers.get("Content-Type", "").startswith("application/pdf"), "dossier pdf did not return application/pdf")
    _assert(len(pdf_bytes) > 0, "dossier pdf was empty")
    return {"pdf_bytes": len(pdf_bytes)}


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Helios Query-to-Dossier Gauntlet",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Mode: `{summary['mode']}`",
        f"- Overall verdict: **{summary['overall_verdict']}**",
        "",
    ]
    for flow in summary["flows"]:
        lines.extend(
            [
                f"## {flow['flow_name']}",
                "",
                f"- Verdict: **{flow['flow_verdict']}**",
                f"- Total time: `{flow['total_ms']} ms`",
                f"- Case ID: `{flow.get('case_id', '')}`",
                f"- Vendor: `{flow.get('vendor_name', '')}`",
                "",
                "| Step | Status | Duration (ms) | Notes |",
                "| --- | --- | ---: | --- |",
            ]
        )
        for step in flow["steps"]:
            notes = json.dumps(step["details"], sort_keys=True)
            lines.append(f"| `{step['step']}` | `{step['status']}` | `{step['duration_ms']}` | `{notes}` |")
        lines.append("")
    return "\n".join(lines)


def write_report(summary: dict[str, Any], report_dir: Path) -> tuple[Path, Path]:
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    output_dir = report_dir / "query_to_dossier_gauntlet" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "summary.md"
    json_path = output_dir / "summary.json"
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return md_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Helios query-to-dossier gauntlet.")
    parser.add_argument("--mode", choices=("fixture", "local-auth", "both"), default="fixture")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--report-dir", default=str(ROOT / "docs" / "reports"))
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def run_fixture_flow() -> dict[str, Any]:
    with fixture_client_context() as client:
        return run_query_to_dossier_flow(client, case_name_prefix="Fixture Gauntlet Vendor")


def run_local_auth_flow(base_url: str, email: str, password: str, token: str) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif email and password:
        login = login_http(base_url, email, password)
        headers["Authorization"] = f"Bearer {login['token']}"
    else:
        raise SystemExit("local-auth mode requires --token or --email/--password")
    client = HttpGauntletClient(base_url, headers=headers)
    return run_query_to_dossier_flow(client, case_name_prefix="Local Auth Gauntlet Vendor")


def main() -> int:
    args = parse_args()
    flows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    if args.mode in {"fixture", "both"}:
        try:
            flow = run_fixture_flow()
            flow["flow_name"] = "fixture"
            flows.append(flow)
        except Exception as exc:
            failures.append({"flow_name": "fixture", "error": str(exc)})

    if args.mode in {"local-auth", "both"}:
        try:
            flow = run_local_auth_flow(args.base_url, args.email, args.password, args.token)
            flow["flow_name"] = "local-auth"
            flows.append(flow)
        except Exception as exc:
            failures.append({"flow_name": "local-auth", "error": str(exc)})

    overall_verdict = "PASS" if flows and not failures else "FAIL"
    summary = {
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "mode": args.mode,
        "overall_verdict": overall_verdict,
        "flows": flows,
        "failures": failures,
    }
    md_path, json_path = write_report(summary, Path(args.report_dir))
    summary["report_md"] = str(md_path)
    summary["report_json"] = str(json_path)
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Wrote gauntlet report to {md_path}")

    return 0 if overall_verdict == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(json.dumps({"overall_verdict": "FAIL", "error": f"{exc.code} {exc.reason}: {body}"}, indent=2))
        raise SystemExit(1)
