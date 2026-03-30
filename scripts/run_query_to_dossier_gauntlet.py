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
DEFAULT_FORBIDDEN_DOSSIER_FRAGMENTS = [
    "Invalid Date",
    "Traceback (most recent call last)",
    "No such file or directory",
    "/Users/tyegonzalez/",
    "/app/backend",
    "ModuleNotFoundError",
    "ImportError:",
    "KeyError:",
    "TypeError:",
    "jinja2.exceptions",
]
DEFAULT_SPECS = [
    {
        "flow_name": "counterparty_defense",
        "expected_workflow_lane": "counterparty",
        "enabled_modes": ["fixture", "local-auth"],
    }
]


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

    def request_json_unauthenticated(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout: int = 60,
    ) -> tuple[int, dict[str, str], Any]:
        raise NotImplementedError

    def request_bytes_unauthenticated(
        self,
        method: str,
        path: str,
        payload: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> tuple[int, dict[str, str], bytes]:
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

    def request_json_unauthenticated(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout: int = 60,
    ) -> tuple[int, dict[str, str], Any]:
        data = None
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, dict(resp.headers), json.loads(body.decode("utf-8")) if body else None

    def request_bytes_unauthenticated(
        self,
        method: str,
        path: str,
        payload: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> tuple[int, dict[str, str], bytes]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload,
            headers=headers or {},
            method=method,
        )
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

    def request_json_unauthenticated(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout: int = 60,
    ) -> tuple[int, dict[str, str], Any]:
        response = self.client.open(path, method=method, json=payload)
        return response.status_code, dict(response.headers), response.get_json(silent=True)

    def request_bytes_unauthenticated(
        self,
        method: str,
        path: str,
        payload: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> tuple[int, dict[str, str], bytes]:
        response = self.client.open(path, method=method, data=payload, headers=headers or {})
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


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_fragment_list(raw: Any, *, field_name: str) -> list[str]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise SystemExit(f"gauntlet spec {field_name} must be a JSON list when provided")
    items = [str(item).strip() for item in raw if str(item).strip()]
    return items


def load_specs(spec_file: str) -> list[dict[str, Any]]:
    if not spec_file:
        payload = DEFAULT_SPECS
    else:
        payload = json.loads(Path(spec_file).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise SystemExit("gauntlet spec file must contain a non-empty JSON list")
    specs: list[dict[str, Any]] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise SystemExit("gauntlet spec entries must be JSON objects")
        enabled_modes_raw = entry.get("enabled_modes") or ["fixture", "local-auth"]
        if not isinstance(enabled_modes_raw, list) or not enabled_modes_raw:
            raise SystemExit("gauntlet spec enabled_modes must be a non-empty list")
        enabled_modes = [str(item).strip() for item in enabled_modes_raw if str(item).strip()]
        if not all(item in {"fixture", "local-auth"} for item in enabled_modes):
            raise SystemExit("gauntlet spec enabled_modes may only contain fixture and local-auth")
        expected_oci = entry.get("expected_oci") or {}
        if expected_oci and not isinstance(expected_oci, dict):
            raise SystemExit("gauntlet spec expected_oci must be a JSON object when provided")
        expected_graph = entry.get("expected_graph") or {}
        if expected_graph and not isinstance(expected_graph, dict):
            raise SystemExit("gauntlet spec expected_graph must be a JSON object when provided")
        expected_assistant_anomalies = _normalize_fragment_list(
            entry.get("expected_assistant_anomalies"),
            field_name="expected_assistant_anomalies",
        )
        expected_dossier_fragments = _normalize_fragment_list(
            entry.get("expected_dossier_fragments"),
            field_name="expected_dossier_fragments",
        )
        forbidden_dossier_fragments = _normalize_fragment_list(
            entry.get("forbidden_dossier_fragments"),
            field_name="forbidden_dossier_fragments",
        )
        specs.append(
            {
                "flow_name": str(entry.get("flow_name") or f"flow_{index + 1}"),
                "compare_payload": _deep_merge(DEFAULT_COMPARE_PAYLOAD, entry.get("compare_payload") or {}),
                "case_payload": _deep_merge(DEFAULT_CASE_PAYLOAD, entry.get("case_payload") or {}),
                "assistant_prompt": str(entry.get("assistant_prompt") or ASSISTANT_PROMPT),
                "expected_workflow_lane": str(entry.get("expected_workflow_lane") or "").strip(),
                "expected_oci": dict(expected_oci),
                "expected_graph": dict(expected_graph),
                "expected_tribunal_view": str(entry.get("expected_tribunal_view") or "").strip().lower(),
                "expected_assistant_view": str(entry.get("expected_assistant_view") or "").strip().lower(),
                "expected_assistant_anomalies": expected_assistant_anomalies,
                "enabled_modes": enabled_modes,
                "preserve_case_name": bool(entry.get("preserve_case_name")),
                "run_enrich_and_score": bool(entry.get("run_enrich_and_score")),
                "expected_dossier_fragments": expected_dossier_fragments,
                "forbidden_dossier_fragments": forbidden_dossier_fragments or list(DEFAULT_FORBIDDEN_DOSSIER_FRAGMENTS),
            }
        )
    return specs


def _specs_for_mode(specs: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    return [spec for spec in specs if mode in (spec.get("enabled_modes") or [])]


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


def run_query_to_dossier_flow(client: BaseClient, spec: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    results: list[StepResult] = []
    warnings: list[str] = []
    case_id = ""
    vendor_name = ""
    health: dict[str, Any] | None = None
    dossier_html: dict[str, Any] | None = None
    passport: dict[str, Any] | None = None

    try:
        health = _run_step(
            results,
            "health",
            lambda: _step_health(client),
        )
        _run_step(results, "ai_providers", lambda: _step_ai_providers(client))
        _run_step(results, "compare", lambda: _step_compare(client, spec["compare_payload"]))
        created = _run_step(
            results,
            "create_case",
            lambda: _step_create_case(
                client,
                flow_name=spec["flow_name"],
                case_payload=spec["case_payload"],
                preserve_case_name=bool(spec.get("preserve_case_name")),
            ),
        )
        case_id = created["case_id"]
        vendor_name = created["vendor_name"]
        _run_step(
            results,
            "case_detail",
            lambda: _step_case_detail(client, case_id, expected_workflow_lane=spec.get("expected_workflow_lane", "")),
        )
        if spec.get("run_enrich_and_score"):
            _run_step(results, "enrich_and_score", lambda: _step_enrich_and_score(client, case_id))
        _run_step(results, "graph", lambda: _step_graph(client, case_id))
        passport = _run_step(
            results,
            "supplier_passport",
            lambda: _step_supplier_passport(
                client,
                case_id,
                expected_oci=spec.get("expected_oci") or {},
                expected_graph=spec.get("expected_graph") or {},
                expected_tribunal_view=spec.get("expected_tribunal_view") or "",
            ),
        )
        plan = _run_step(
            results,
            "assistant_plan",
            lambda: _step_assistant_plan(
                client,
                case_id,
                spec["assistant_prompt"],
                expected_view=spec.get("expected_assistant_view") or "",
                expected_anomaly_codes=spec.get("expected_assistant_anomalies") or [],
            ),
        )
        _run_step(results, "assistant_execute", lambda: _step_assistant_execute(client, case_id, plan))
        dossier_html = _run_step(
            results,
            "dossier_html",
            lambda: _step_dossier_html(
                client,
                case_id,
                expected_fragments=spec.get("expected_dossier_fragments") or [],
                forbidden_fragments=spec.get("forbidden_dossier_fragments") or [],
            ),
        )
        _run_step(results, "browser_dossier_access", lambda: _step_browser_dossier_access(client, dossier_html["download_url"]))
        _run_step(results, "dossier_pdf", lambda: _step_dossier_pdf(client, case_id))
    except Exception as exc:
        total_ms = int((time.perf_counter() - started) * 1000)
        return {
            "flow_verdict": "FAIL",
            "case_id": case_id,
            "vendor_name": vendor_name,
            "health": health,
            "download_url": (dossier_html or {}).get("download_url"),
            "oci_required": bool(spec.get("expected_oci")),
            "oci_passed": False,
            "oci_details": (passport or {}).get("oci"),
            "graph_required": bool(spec.get("expected_graph")),
            "graph_passed": False,
            "graph_details": (passport or {}).get("graph"),
            "warning_count": len(warnings),
            "warnings": warnings,
            "steps": [asdict(item) for item in results],
            "total_ms": total_ms,
            "flow_name": spec["flow_name"],
            "error": str(exc),
            "failed_step": results[-1].step if results else "",
        }

    total_ms = int((time.perf_counter() - started) * 1000)
    return {
        "flow_verdict": "PASS",
        "case_id": case_id,
        "vendor_name": vendor_name,
        "health": health,
        "download_url": (dossier_html or {}).get("download_url"),
        "oci_required": bool((passport or {}).get("oci_required")),
        "oci_passed": bool((passport or {}).get("oci_passed", not (passport or {}).get("oci_required"))),
        "oci_details": (passport or {}).get("oci"),
        "graph_required": bool((passport or {}).get("graph_required")),
        "graph_passed": bool((passport or {}).get("graph_passed", not (passport or {}).get("graph_required"))),
        "graph_details": (passport or {}).get("graph"),
        "warning_count": len(warnings),
        "warnings": warnings,
        "steps": [asdict(item) for item in results],
        "total_ms": total_ms,
        "flow_name": spec["flow_name"],
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


def _step_compare(client: BaseClient, compare_payload: dict[str, Any]) -> dict[str, Any]:
    status, _, body = client.request_json("POST", "/api/compare", payload=compare_payload, timeout=45)
    _assert(status == 200 and isinstance(body, dict), f"/api/compare returned {status}")
    comparisons = body.get("comparisons") or []
    entity = body.get("entity") or {}
    _assert(entity.get("name") == compare_payload["name"], "compare entity name mismatch")
    _assert(len(comparisons) >= 1, "compare returned no profile comparisons")
    _assert(all("tier" in item for item in comparisons), "compare response missing tier")
    return {"comparison_count": len(comparisons)}


def _step_create_case(
    client: BaseClient,
    *,
    flow_name: str,
    case_payload: dict[str, Any],
    preserve_case_name: bool = False,
) -> dict[str, Any]:
    payload = _deep_merge(DEFAULT_CASE_PAYLOAD, case_payload)
    if preserve_case_name:
        payload["name"] = str(case_payload.get("name") or payload.get("name") or flow_name)
    else:
        payload["name"] = f"{flow_name} {int(time.time())}"
    status, _, body = client.request_json("POST", "/api/cases", payload=payload, timeout=45)
    _assert(status == 201 and isinstance(body, dict), f"/api/cases returned {status}")
    case_id = body.get("case_id")
    _assert(bool(case_id), "case creation did not return case_id")
    return {"case_id": case_id, "vendor_name": payload["name"]}


def _step_case_detail(client: BaseClient, case_id: str, *, expected_workflow_lane: str = "") -> dict[str, Any]:
    status, _, body = client.request_json("GET", f"/api/cases/{case_id}", timeout=45)
    _assert(status == 200 and isinstance(body, dict), f"/api/cases/{case_id} returned {status}")
    _assert(body.get("id") == case_id, "case detail id mismatch")
    _assert("storyline" in body, "case detail missing storyline field")
    if expected_workflow_lane:
        _assert(body.get("workflow_lane") == expected_workflow_lane, "workflow lane mismatch")
    return {
        "has_storyline": body.get("storyline") is not None,
        "workflow_lane": body.get("workflow_lane"),
    }


def _step_graph(client: BaseClient, case_id: str) -> dict[str, Any]:
    status, _, body = client.request_json("GET", f"/api/cases/{case_id}/graph?depth=3", timeout=45)
    _assert(status == 200 and isinstance(body, dict), f"/api/cases/{case_id}/graph returned {status}")
    _assert(not body.get("error"), f"graph returned error: {body.get('error')}")
    entities = body.get("entities") or []
    relationships = body.get("relationships") or []
    root_entity_id = str(body.get("root_entity_id") or "")
    _assert(isinstance(entities, list), "graph entities payload is not a list")
    _assert(isinstance(relationships, list), "graph relationships payload is not a list")
    _assert(bool(root_entity_id), "graph root entity id missing")
    return {"entity_count": len(entities), "relationship_count": len(relationships), "root_entity_id": root_entity_id}


def _step_enrich_and_score(client: BaseClient, case_id: str) -> dict[str, Any]:
    status, _, body = client.request_json("POST", f"/api/cases/{case_id}/enrich-and-score", payload={}, timeout=180)
    _assert(status == 200 and isinstance(body, dict), f"/api/cases/{case_id}/enrich-and-score returned {status}")
    enrichment = body.get("enrichment") if isinstance(body.get("enrichment"), dict) else {}
    scoring = body.get("scoring") if isinstance(body.get("scoring"), dict) else {}
    _assert(body.get("case_id") == case_id, "enrich-and-score case id mismatch")
    _assert(bool(enrichment), "enrich-and-score missing enrichment payload")
    _assert(bool(scoring), "enrich-and-score missing scoring payload")
    return {
        "overall_risk": enrichment.get("overall_risk"),
        "connectors_with_data": int((enrichment.get("summary") or {}).get("connectors_with_data") or 0),
        "findings_total": int((enrichment.get("summary") or {}).get("findings_total") or 0),
        "calibrated_tier": (scoring.get("calibrated") or {}).get("calibrated_tier"),
    }


def _validate_expected_oci(passport: dict[str, Any], expected_oci: dict[str, Any]) -> dict[str, Any]:
    ownership = passport.get("ownership") if isinstance(passport.get("ownership"), dict) else {}
    oci = ownership.get("oci") if isinstance(ownership.get("oci"), dict) else {}
    _assert(bool(oci), "supplier passport missing ownership.oci")

    if "named_beneficial_owner_known" in expected_oci:
        _assert(
            bool(oci.get("named_beneficial_owner_known")) == bool(expected_oci["named_beneficial_owner_known"]),
            "OCI named_beneficial_owner_known mismatch",
        )
    if "owner_class_known" in expected_oci:
        _assert(
            bool(oci.get("owner_class_known")) == bool(expected_oci["owner_class_known"]),
            "OCI owner_class_known mismatch",
        )
    if "descriptor_only" in expected_oci:
        _assert(
            bool(oci.get("descriptor_only")) == bool(expected_oci["descriptor_only"]),
            "OCI descriptor_only mismatch",
        )
    if expected_oci.get("owner_class"):
        _assert(str(oci.get("owner_class") or "") == str(expected_oci["owner_class"]), "OCI owner_class mismatch")
    if expected_oci.get("ownership_gap"):
        _assert(str(oci.get("ownership_gap") or "") == str(expected_oci["ownership_gap"]), "OCI ownership_gap mismatch")
    if "min_ownership_resolution_pct" in expected_oci:
        _assert(
            float(oci.get("ownership_resolution_pct") or 0.0) >= float(expected_oci["min_ownership_resolution_pct"]),
            "OCI ownership_resolution_pct below threshold",
        )
    if "min_control_resolution_pct" in expected_oci:
        _assert(
            float(oci.get("control_resolution_pct") or 0.0) >= float(expected_oci["min_control_resolution_pct"]),
            "OCI control_resolution_pct below threshold",
        )
    if expected_oci.get("require_owner_class_evidence"):
        evidence = oci.get("owner_class_evidence") if isinstance(oci.get("owner_class_evidence"), list) else []
        _assert(bool(evidence), "OCI owner_class_evidence missing")

    return {
        "named_beneficial_owner_known": bool(oci.get("named_beneficial_owner_known")),
        "owner_class_known": bool(oci.get("owner_class_known")),
        "owner_class": str(oci.get("owner_class") or ""),
        "descriptor_only": bool(oci.get("descriptor_only")),
        "ownership_gap": str(oci.get("ownership_gap") or ""),
        "ownership_resolution_pct": float(oci.get("ownership_resolution_pct") or 0.0),
        "control_resolution_pct": float(oci.get("control_resolution_pct") or 0.0),
        "owner_class_evidence_count": len(oci.get("owner_class_evidence") or []),
    }


def _validate_expected_graph(passport: dict[str, Any], expected_graph: dict[str, Any]) -> dict[str, Any]:
    graph = passport.get("graph") if isinstance(passport.get("graph"), dict) else {}
    intelligence = graph.get("intelligence") if isinstance(graph.get("intelligence"), dict) else {}
    control_paths = graph.get("control_paths") if isinstance(graph.get("control_paths"), list) else []
    _assert(bool(graph), "supplier passport missing graph payload")

    if "min_relationship_count" in expected_graph:
        _assert(
            int(graph.get("relationship_count") or 0) >= int(expected_graph["min_relationship_count"]),
            "graph relationship_count below threshold",
        )
    if "min_network_relationship_count" in expected_graph:
        _assert(
            int(graph.get("network_relationship_count") or 0) >= int(expected_graph["min_network_relationship_count"]),
            "graph network_relationship_count below threshold",
        )
    if "min_control_paths" in expected_graph:
        _assert(
            len(control_paths) >= int(expected_graph["min_control_paths"]),
            "graph control_paths below threshold",
        )
    required_edge_families = [str(item).strip() for item in (expected_graph.get("require_edge_families") or []) if str(item).strip()]
    for family in required_edge_families:
        _assert(
            int((intelligence.get("edge_family_counts") or {}).get(family) or 0) > 0,
            f"graph missing required edge family: {family}",
        )
    if "max_missing_required_edge_families" in expected_graph:
        _assert(
            len(intelligence.get("missing_required_edge_families") or []) <= int(expected_graph["max_missing_required_edge_families"]),
            "graph intelligence missing_required_edge_families above threshold",
        )
    if "max_legacy_unscoped_edges" in expected_graph:
        _assert(
            int(intelligence.get("legacy_unscoped_edge_count") or 0) <= int(expected_graph["max_legacy_unscoped_edges"]),
            "graph intelligence legacy_unscoped_edge_count above threshold",
        )
    if "max_stale_edges" in expected_graph:
        _assert(
            int(intelligence.get("stale_edge_count") or 0) <= int(expected_graph["max_stale_edges"]),
            "graph intelligence stale_edge_count above threshold",
        )
    if "min_claim_coverage_pct" in expected_graph:
        _assert(
            float(intelligence.get("claim_coverage_pct") or 0.0) >= float(expected_graph["min_claim_coverage_pct"]),
            "graph intelligence claim_coverage_pct below threshold",
        )
    if "forbid_thin_graph" in expected_graph and bool(expected_graph["forbid_thin_graph"]):
        _assert(not bool(intelligence.get("thin_graph")), "graph intelligence still marks the graph thin")

    return {
        "relationship_count": int(graph.get("relationship_count") or 0),
        "network_relationship_count": int(graph.get("network_relationship_count") or 0),
        "control_path_count": len(control_paths),
        "edge_family_counts": dict(intelligence.get("edge_family_counts") or {}),
        "missing_required_edge_families": list(intelligence.get("missing_required_edge_families") or []),
        "claim_coverage_pct": float(intelligence.get("claim_coverage_pct") or 0.0),
        "legacy_unscoped_edge_count": int(intelligence.get("legacy_unscoped_edge_count") or 0),
        "stale_edge_count": int(intelligence.get("stale_edge_count") or 0),
        "thin_graph": bool(intelligence.get("thin_graph")),
    }


def _step_supplier_passport(
    client: BaseClient,
    case_id: str,
    expected_oci: dict[str, Any] | None = None,
    expected_graph: dict[str, Any] | None = None,
    *,
    expected_tribunal_view: str = "",
) -> dict[str, Any]:
    mode = "full" if expected_tribunal_view else "light"
    status, _, body = client.request_json("GET", f"/api/cases/{case_id}/supplier-passport?mode={mode}", timeout=60)
    _assert(status == 200 and isinstance(body, dict), f"/api/cases/{case_id}/supplier-passport returned {status}")
    _assert(body.get("case_id") == case_id, "supplier passport case id mismatch")
    _assert(bool(body.get("passport_version")), "supplier passport version missing")
    expected_oci = expected_oci or {}
    expected_graph = expected_graph or {}
    oci = _validate_expected_oci(body, expected_oci) if expected_oci else None
    graph = _validate_expected_graph(body, expected_graph) if expected_graph else None
    tribunal = body.get("tribunal") if isinstance(body.get("tribunal"), dict) else {}
    if expected_tribunal_view:
        _assert(str(tribunal.get("recommended_view") or "").lower() == expected_tribunal_view, "supplier passport tribunal recommended_view mismatch")
    return {
        "passport_version": body.get("passport_version"),
        "posture": body.get("posture"),
        "workflow_lane": body.get("workflow_lane"),
        "tribunal_recommended_view": tribunal.get("recommended_view"),
        "tribunal_consensus_level": tribunal.get("consensus_level"),
        "tribunal_decision_gap": tribunal.get("decision_gap"),
        "oci_required": bool(expected_oci),
        "oci_passed": True if expected_oci else False,
        "oci": oci,
        "graph_required": bool(expected_graph),
        "graph_passed": True if expected_graph else False,
        "graph": graph,
    }


def _step_assistant_plan(
    client: BaseClient,
    case_id: str,
    assistant_prompt: str,
    *,
    expected_view: str = "",
    expected_anomaly_codes: list[str] | None = None,
) -> dict[str, Any]:
    status, _, body = client.request_json(
        "POST",
        f"/api/cases/{case_id}/assistant-plan",
        payload={"prompt": assistant_prompt},
        timeout=60,
    )
    _assert(status == 200 and isinstance(body, dict), f"/api/cases/{case_id}/assistant-plan returned {status}")
    plan = body.get("plan") or []
    _assert(body.get("case_id") == case_id, "assistant plan case id mismatch")
    _assert(body.get("version") == "ai-control-plane-v1", "assistant plan version mismatch")
    _assert(len(plan) >= 1, "assistant plan returned no steps")
    if expected_view:
        _assert(str(body.get("recommended_view") or "").lower() == expected_view, "assistant plan recommended_view mismatch")
    anomaly_codes = [str(item.get("code") or "").strip() for item in (body.get("anomalies") or []) if isinstance(item, dict)]
    missing_anomalies = [code for code in (expected_anomaly_codes or []) if code not in anomaly_codes]
    _assert(not missing_anomalies, f"assistant plan missing expected anomalies: {', '.join(missing_anomalies)}")
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


def _find_fragment_context(text: str, fragment: str, *, radius: int = 90) -> str:
    lower_text = text.lower()
    lower_fragment = fragment.lower()
    index = lower_text.find(lower_fragment)
    if index < 0:
        return ""
    start = max(0, index - radius)
    end = min(len(text), index + len(fragment) + radius)
    snippet = text[start:end].replace("\n", " ").replace("\r", " ")
    return " ".join(snippet.split())


def _step_dossier_html(
    client: BaseClient,
    case_id: str,
    *,
    expected_fragments: list[str] | None = None,
    forbidden_fragments: list[str] | None = None,
) -> dict[str, Any]:
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
    expected_fragments = expected_fragments or []
    forbidden_fragments = forbidden_fragments or []

    matched_expected: list[str] = []
    missing_expected: list[str] = []
    expected_contexts: dict[str, str] = {}
    for fragment in expected_fragments:
        if fragment.lower() in html_text.lower():
            matched_expected.append(fragment)
            expected_contexts[fragment] = _find_fragment_context(html_text, fragment)
        else:
            missing_expected.append(fragment)
    _assert(not missing_expected, f"dossier html missing expected fragments: {', '.join(missing_expected)}")

    forbidden_hits = [fragment for fragment in forbidden_fragments if fragment.lower() in html_text.lower()]
    _assert(not forbidden_hits, f"dossier html contains forbidden fragments: {', '.join(forbidden_hits)}")

    return {
        "download_url": download_url,
        "html_bytes": len(html_bytes),
        "expected_fragments_checked": len(expected_fragments),
        "matched_expected_fragments": matched_expected,
        "forbidden_fragments_checked": len(forbidden_fragments),
        "expected_fragment_contexts": expected_contexts,
    }


def _step_browser_dossier_access(client: BaseClient, download_url: str) -> dict[str, Any]:
    status, _, ticket_body = client.request_json(
        "POST",
        "/api/auth/access-ticket",
        payload={"path": download_url},
        timeout=30,
    )
    _assert(status == 200 and isinstance(ticket_body, dict), f"/api/auth/access-ticket returned {status}")
    access_ticket = str(ticket_body.get("access_ticket") or "")
    _assert(access_ticket, "browser access ticket missing")
    _assert(ticket_body.get("path") == download_url, "browser access ticket path mismatch")

    separator = "&" if "?" in download_url else "?"
    protected_path = f"{download_url}{separator}access_ticket={access_ticket}"
    html_status, html_headers, html_bytes = client.request_bytes_unauthenticated("GET", protected_path, timeout=90)
    html_text = html_bytes.decode("utf-8", errors="replace")
    _assert(html_status == 200, f"browser dossier access returned {html_status}")
    _assert(
        "text/html" in _normalize_headers(html_headers).get("Content-Type", ""),
        "browser dossier access did not return html",
    )
    for marker in HTML_MARKERS:
        _assert(marker.lower() in html_text.lower(), f"browser dossier html missing marker: {marker}")

    reopen_status, reopen_headers, reopen_bytes = client.request_bytes_unauthenticated("GET", protected_path, timeout=90)
    reopen_text = reopen_bytes.decode("utf-8", errors="replace")
    _assert(reopen_status == 200, f"browser dossier reopen returned {reopen_status}")
    _assert(
        "text/html" in _normalize_headers(reopen_headers).get("Content-Type", ""),
        "browser dossier reopen did not return html",
    )
    for marker in HTML_MARKERS:
        _assert(marker.lower() in reopen_text.lower(), f"browser dossier reopen missing marker: {marker}")

    return {
        "permission": ticket_body.get("permission"),
        "expires_in": int(ticket_body.get("expires_in") or 0),
        "html_bytes": len(html_bytes),
        "reopen_html_bytes": len(reopen_bytes),
    }


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
    _assert(
        normalized_headers.get("Content-Disposition", "").startswith("attachment; filename=dossier-"),
        "dossier pdf missing download filename",
    )
    _assert(len(pdf_bytes) > 0, "dossier pdf was empty")
    _assert(pdf_bytes.startswith(b"%PDF-"), "dossier pdf bytes missing pdf header")
    return {
        "pdf_bytes": len(pdf_bytes),
        "content_disposition": normalized_headers.get("Content-Disposition", ""),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Helios Query-to-Dossier Gauntlet",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Mode: `{summary['mode']}`",
        f"- Overall verdict: **{summary['overall_verdict']}**",
        "",
    ]
    if summary.get("skipped_reason"):
        lines.extend(
            [
                f"- Skipped: `{summary['skipped_reason']}`",
                "",
            ]
        )
    oci_summary = summary.get("oci_summary") if isinstance(summary.get("oci_summary"), dict) else {}
    if oci_summary:
        lines.extend(
            [
                f"- OCI required flows: `{oci_summary.get('required_flows', 0)}`",
                f"- OCI passed flows: `{oci_summary.get('passed_flows', 0)}`",
                f"- OCI descriptor-only passed flows: `{oci_summary.get('descriptor_only_passed_flows', 0)}`",
                "",
            ]
        )
    graph_summary = summary.get("graph_summary") if isinstance(summary.get("graph_summary"), dict) else {}
    if graph_summary:
        lines.extend(
            [
                f"- Graph required flows: `{graph_summary.get('required_flows', 0)}`",
                f"- Graph passed flows: `{graph_summary.get('passed_flows', 0)}`",
                f"- Graph thin flows: `{graph_summary.get('thin_graph_flows', 0)}`",
                f"- Graph missing-family flows: `{graph_summary.get('flows_with_missing_required_edge_families', 0)}`",
                "",
            ]
        )
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
    parser.add_argument("--spec-file", default="")
    parser.add_argument("--report-dir", default=str(ROOT / "docs" / "reports"))
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def run_fixture_flow() -> dict[str, Any]:
    return run_fixture_flows()[0]


def run_fixture_flows(specs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    specs = specs or load_specs("")
    with fixture_client_context() as client:
        return [run_query_to_dossier_flow(client, spec) for spec in _specs_for_mode(specs, "fixture")]


def run_local_auth_flow(base_url: str, email: str, password: str, token: str) -> dict[str, Any]:
    return run_local_auth_flows(base_url, email, password, token)[0]


def run_local_auth_flows(
    base_url: str,
    email: str,
    password: str,
    token: str,
    specs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    specs = specs or load_specs("")
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif email and password:
        login = login_http(base_url, email, password)
        headers["Authorization"] = f"Bearer {login['token']}"
    else:
        raise SystemExit("local-auth mode requires --token or --email/--password")
    client = HttpGauntletClient(base_url, headers=headers)
    return [run_query_to_dossier_flow(client, spec) for spec in _specs_for_mode(specs, "local-auth")]


def build_oci_summary(flows: list[dict[str, Any]]) -> dict[str, Any]:
    oci_flows = [flow for flow in flows if flow.get("oci_required")]
    passed = [flow for flow in oci_flows if flow.get("oci_passed")]
    descriptor_only_passed = [
        flow
        for flow in passed
        if isinstance(flow.get("oci_details"), dict) and bool(flow["oci_details"].get("descriptor_only"))
    ]
    return {
        "required_flows": len(oci_flows),
        "passed_flows": len(passed),
        "descriptor_only_passed_flows": len(descriptor_only_passed),
        "failed_flows": [str(flow.get("flow_name") or "") for flow in oci_flows if not flow.get("oci_passed")],
    }


def build_graph_summary(flows: list[dict[str, Any]]) -> dict[str, Any]:
    graph_flows = [flow for flow in flows if flow.get("graph_required")]
    passed = [flow for flow in graph_flows if flow.get("graph_passed")]
    thin_graph_flows = [
        flow
        for flow in graph_flows
        if isinstance(flow.get("graph_details"), dict) and bool(flow["graph_details"].get("thin_graph"))
    ]
    missing_family_flows = [
        flow
        for flow in graph_flows
        if isinstance(flow.get("graph_details"), dict) and bool(flow["graph_details"].get("missing_required_edge_families"))
    ]
    return {
        "required_flows": len(graph_flows),
        "passed_flows": len(passed),
        "thin_graph_flows": len(thin_graph_flows),
        "flows_with_missing_required_edge_families": len(missing_family_flows),
        "failed_flows": [str(flow.get("flow_name") or "") for flow in graph_flows if not flow.get("graph_passed")],
    }


def main() -> int:
    args = parse_args()
    specs = load_specs(args.spec_file)
    flows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    if args.mode in {"fixture", "both"}:
        try:
            fixture_flows = run_fixture_flows(specs)
            for flow in fixture_flows:
                flow["flow_name"] = f"fixture:{flow['flow_name']}"
            flows.extend(fixture_flows)
        except Exception as exc:
            failures.append({"flow_name": "fixture", "error": str(exc)})

    if args.mode in {"local-auth", "both"}:
        try:
            local_auth_flows = run_local_auth_flows(args.base_url, args.email, args.password, args.token, specs)
            for flow in local_auth_flows:
                flow["flow_name"] = f"local-auth:{flow['flow_name']}"
            flows.extend(local_auth_flows)
        except Exception as exc:
            failures.append({"flow_name": "local-auth", "error": str(exc)})

    skipped_reason = ""
    has_failed_flows = any(str(flow.get("flow_verdict") or "PASS") != "PASS" for flow in flows)
    if failures or has_failed_flows:
        overall_verdict = "FAIL"
    elif flows:
        overall_verdict = "PASS"
    else:
        overall_verdict = "PASS"
        skipped_reason = f"no eligible flows for mode {args.mode}"
    summary = {
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "mode": args.mode,
        "overall_verdict": overall_verdict,
        "flows": flows,
        "oci_summary": build_oci_summary(flows),
        "graph_summary": build_graph_summary(flows),
        "failures": failures,
        "skipped_reason": skipped_reason,
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
