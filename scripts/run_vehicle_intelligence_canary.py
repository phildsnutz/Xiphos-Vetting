#!/usr/bin/env python3
"""Run a focused vehicle-intelligence canary against a Helios instance."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "vehicle_intelligence_canary"


ITEAMS_DOSSIER_MARKERS = (
    "Competitive Teaming Map",
    "Vehicle Lineage & Competitive Landscape",
    "Litigation & Protest Profile",
    "Capture Outlook",
    "Evidence Footprint",
)

LEIA_DOSSIER_MARKERS = (
    "Vehicle Lineage & Competitive Landscape",
    "Litigation & Protest Profile",
    "Capture Outlook",
    "Evidence Footprint",
)

SUPPORT_ONLY_DOSSIER_MARKERS = (
    "Vehicle Lineage & Competitive Landscape",
    "Litigation & Protest Profile",
    "Capture Outlook",
    "Evidence Footprint",
)

COMPARATIVE_MARKERS = (
    "Vehicle Lineage Map",
    "Litigation & Protest Profile",
    "ITEAMS",
    "LEIA",
)


@dataclass
class CheckResult:
    name: str
    status: str
    duration_ms: int
    details: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Helios vehicle-intelligence canary.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 90,
) -> tuple[int, dict[str, str], Any]:
    data = None
    final_headers = {"Content-Type": "application/json"} if payload is not None else {}
    if headers:
        final_headers.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=final_headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        parsed = json.loads(body.decode("utf-8")) if body else None
        return response.status, dict(response.headers), parsed


def _validate_token(base_url: str, token: str) -> bool:
    try:
        status, _, _ = request_json(
            base_url,
            "GET",
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except Exception:
        return False
    return status == 200


def login_headers(base_url: str, email: str, password: str, token: str) -> dict[str, str]:
    if token:
        if _validate_token(base_url, token):
            return {"Authorization": f"Bearer {token}"}
        if not email or not password:
            raise RuntimeError("vehicle intelligence canary token is invalid or expired")
    if not email or not password:
        raise SystemExit("vehicle intelligence canary requires --token or --email/--password")
    status, _, payload = request_json(
        base_url,
        "POST",
        "/api/auth/login",
        {"email": email, "password": password},
        timeout=30,
    )
    if status != 200 or not isinstance(payload, dict) or not payload.get("token"):
        raise RuntimeError(f"auth login returned {status}")
    return {"Authorization": f"Bearer {payload['token']}"}


def _missing_markers(html: str, markers: tuple[str, ...]) -> list[str]:
    return [marker for marker in markers if marker not in html]


def _check_teaming(
    base_url: str,
    headers: dict[str, str],
    *,
    vehicle_name: str,
    observed_vendors: list[dict[str, Any]],
    scenario: dict[str, Any] | None = None,
) -> CheckResult:
    started = time.perf_counter()
    failures: list[str] = []
    details: dict[str, Any] = {"vehicle_name": vehicle_name}
    try:
        _, _, payload = request_json(
            base_url,
            "POST",
            "/api/cvi/teaming-intelligence",
            {
                "vehicle_name": vehicle_name,
                "observed_vendors": observed_vendors,
                "scenario": scenario or {},
            },
            headers=headers,
            timeout=90,
        )
        report = payload.get("report") if isinstance(payload, dict) else {}
        details["supported"] = bool(report.get("supported"))
        details["partner_count"] = len(report.get("assessed_partners") or [])
        details["scenario_state"] = str((report.get("scenario") or {}).get("state") or "")
        if not report.get("supported"):
            failures.append(f"{vehicle_name} teaming report was not supported")
        if len(report.get("assessed_partners") or []) < 2:
            failures.append(f"{vehicle_name} teaming report returned too few assessed partners")
        if scenario and str((report.get("scenario") or {}).get("state") or "") != "predicted":
            failures.append(f"{vehicle_name} teaming scenario did not produce predicted state")
    except Exception as exc:
        failures.append(str(exc))
    return CheckResult(
        name=f"teaming_intelligence_{vehicle_name.lower().replace(' ', '_')}",
        status="FAIL" if failures else "PASS",
        duration_ms=int((time.perf_counter() - started) * 1000),
        details=details,
        failures=failures,
    )


def _check_vehicle_dossier(
    base_url: str,
    headers: dict[str, str],
    *,
    vehicle_name: str,
    prime_contractor: str,
    markers: tuple[str, ...],
) -> CheckResult:
    started = time.perf_counter()
    failures: list[str] = []
    details: dict[str, Any] = {"vehicle_name": vehicle_name}
    try:
        _, _, payload = request_json(
            base_url,
            "POST",
            "/api/cvi/vehicle-dossier",
            {
                "vehicle_name": vehicle_name,
                "prime_contractor": prime_contractor,
                "vendor_ids": [f"support-only-{vehicle_name.lower()}"],
                "contract_data": {
                    "contract_id": f"{vehicle_name}-CANARY",
                    "award_date": "2026-04-06",
                    "task_orders": 3,
                },
            },
            headers=headers,
            timeout=120,
        )
        html = str((payload or {}).get("html") or "")
        missing = _missing_markers(html, markers)
        details["missing_markers"] = missing
        details["html_bytes"] = len(html.encode("utf-8"))
        if not html:
            failures.append(f"{vehicle_name} dossier returned empty html")
        if missing:
            failures.append(f"{vehicle_name} dossier missing markers: {', '.join(missing)}")
    except Exception as exc:
        failures.append(str(exc))
    return CheckResult(
        name=f"vehicle_dossier_{vehicle_name.lower()}",
        status="FAIL" if failures else "PASS",
        duration_ms=int((time.perf_counter() - started) * 1000),
        details=details,
        failures=failures,
    )


def _check_comparative(base_url: str, headers: dict[str, str]) -> CheckResult:
    started = time.perf_counter()
    failures: list[str] = []
    details: dict[str, Any] = {}
    try:
        _, _, payload = request_json(
            base_url,
            "POST",
            "/api/cvi/comparative",
            {
                "vehicle_configs": [
                    {
                        "vehicle_name": "ITEAMS",
                        "prime_contractor": "Amentum",
                        "vendor_ids": [],
                        "contract_data": {"contract_id": "ITEAMS-COMP", "award_date": "2025-01-10", "task_orders": 7},
                    },
                    {
                        "vehicle_name": "LEIA",
                        "prime_contractor": "SMX",
                        "vendor_ids": [],
                        "contract_data": {"contract_id": "LEIA-COMP", "award_date": "2025-03-12", "task_orders": 4},
                    },
                ]
            },
            headers=headers,
            timeout=120,
        )
        html = str((payload or {}).get("html") or "")
        missing = _missing_markers(html, COMPARATIVE_MARKERS)
        details["missing_markers"] = missing
        details["html_bytes"] = len(html.encode("utf-8"))
        if not html:
            failures.append("comparative dossier returned empty html")
        if missing:
            failures.append(f"comparative dossier missing markers: {', '.join(missing)}")
    except Exception as exc:
        failures.append(str(exc))
    return CheckResult(
        name="comparative_vehicle_dossier",
        status="FAIL" if failures else "PASS",
        duration_ms=int((time.perf_counter() - started) * 1000),
        details=details,
        failures=failures,
    )


def _check_axiom_vehicle_mode(base_url: str, headers: dict[str, str]) -> CheckResult:
    started = time.perf_counter()
    failures: list[str] = []
    details: dict[str, Any] = {}
    try:
        _, _, payload = request_json(
            base_url,
            "POST",
            "/api/axiom/search",
            {
                "prime_contractor": "Amentum",
                "vehicle_name": "ITEAMS",
                "context": "INDOPACOM mission services recompete",
            },
            headers=headers,
            timeout=120,
        )
        support = (payload or {}).get("vehicle_mode_support") if isinstance(payload, dict) else {}
        details["graph_fact_count"] = len((support or {}).get("graph_facts") or [])
        details["prediction_count"] = len((support or {}).get("predictions") or [])
        details["unknown_count"] = len((support or {}).get("unknowns") or [])
        details["support_connectors_with_data"] = int(((support or {}).get("support_evidence") or {}).get("connectors_with_data") or 0)
        if not isinstance(support, dict) or not support:
            failures.append("AXIOM search did not return vehicle_mode_support")
        else:
            for key in ("graph_facts", "support_evidence", "predictions", "unknowns"):
                if key not in support:
                    failures.append(f"vehicle_mode_support missing {key}")
            if int(((support.get("support_evidence") or {}).get("connectors_with_data") or 0) < 1):
                failures.append("vehicle_mode_support did not carry support evidence")
    except Exception as exc:
        failures.append(str(exc))
    return CheckResult(
        name="axiom_vehicle_mode",
        status="FAIL" if failures else "PASS",
        duration_ms=int((time.perf_counter() - started) * 1000),
        details=details,
        failures=failures,
    )


def _write_report(args: argparse.Namespace, checks: list[CheckResult]) -> tuple[Path, Path, str]:
    report_root = Path(args.report_dir)
    report_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    report_dir = report_root / stamp
    report_dir.mkdir(parents=True, exist_ok=True)

    overall_verdict = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
    payload = {
        "overall_verdict": overall_verdict,
        "generated_at": datetime.now().isoformat(),
        "base_url": args.base_url,
        "checks": [asdict(check) for check in checks],
    }
    json_path = report_dir / "summary.json"
    md_path = report_dir / "summary.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Vehicle Intelligence Canary",
        "",
        f"- Overall verdict: `{overall_verdict}`",
        f"- Base URL: `{args.base_url}`",
        "",
        "## Checks",
        "",
    ]
    for check in checks:
        lines.append(f"- `{check.name}`: `{check.status}` in `{check.duration_ms}ms`")
        for failure in check.failures:
            lines.append(f"  - failure: {failure}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path, overall_verdict


def main() -> int:
    args = parse_args()
    headers = login_headers(args.base_url, args.email, args.password, args.token)
    checks = [
        _check_teaming(
            args.base_url,
            headers,
            vehicle_name="ITEAMS",
            observed_vendors=[
                {"vendor_name": "Amentum", "role": "prime"},
                {"vendor_name": "HII Mission Technologies", "role": "subcontractor"},
                {"vendor_name": "SMX", "role": "subcontractor"},
            ],
            scenario={"recruit_partner": "HII Mission Technologies"},
        ),
        _check_teaming(
            args.base_url,
            headers,
            vehicle_name="LEIA",
            observed_vendors=[
                {"vendor_name": "SMX", "role": "prime"},
                {"vendor_name": "cBEYONData", "role": "subcontractor"},
                {"vendor_name": "HII Mission Technologies", "role": "challenger"},
            ],
            scenario={"recruit_partner": "HII Mission Technologies"},
        ),
        _check_teaming(
            args.base_url,
            headers,
            vehicle_name="OASIS",
            observed_vendors=[],
        ),
        _check_vehicle_dossier(args.base_url, headers, vehicle_name="ITEAMS", prime_contractor="Amentum", markers=ITEAMS_DOSSIER_MARKERS),
        _check_vehicle_dossier(args.base_url, headers, vehicle_name="LEIA", prime_contractor="SMX", markers=LEIA_DOSSIER_MARKERS),
        _check_vehicle_dossier(args.base_url, headers, vehicle_name="SEWP", prime_contractor="NASA SEWP Program Office", markers=SUPPORT_ONLY_DOSSIER_MARKERS),
        _check_vehicle_dossier(args.base_url, headers, vehicle_name="CIO-SP4", prime_contractor="NITAAC", markers=SUPPORT_ONLY_DOSSIER_MARKERS),
        _check_vehicle_dossier(
            args.base_url,
            headers,
            vehicle_name="OASIS",
            prime_contractor="Science Applications International Corporation",
            markers=SUPPORT_ONLY_DOSSIER_MARKERS,
        ),
        _check_comparative(args.base_url, headers),
        _check_axiom_vehicle_mode(args.base_url, headers),
    ]
    md_path, json_path, overall_verdict = _write_report(args, checks)
    payload = {
        "overall_verdict": overall_verdict,
        "report_md": str(md_path),
        "report_json": str(json_path),
        "checks": [asdict(check) for check in checks],
    }
    if args.print_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Wrote {md_path}")
        print(f"Wrote {json_path}")
    return 0 if overall_verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
