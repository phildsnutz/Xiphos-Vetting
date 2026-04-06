#!/usr/bin/env python3
"""
Canonical current-product Helios stress harness.

This is the baseline gate for the product as it exists now, not the legacy
multi-lane platform. It validates:
  - public Stoa intake behavior
  - carried brief into Aegis
  - graph-backed AXIOM interrogation endpoints
  - current-product authenticated case workflow

The goal is a decision-ready report for local-first hardening and later
droplet sizing, not a generic regression dump.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FRONT_PORCH_SCRIPT = ROOT / "scripts" / "run_front_porch_browser_regression.py"
AEGIS_CARRYOVER_SCRIPT = ROOT / "scripts" / "run_war_room_carryover_regression.py"
SMOKE_SCRIPT = ROOT / "scripts" / "run_local_smoke.py"
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "current_product_stress_harness"


@dataclass
class CheckResult:
    name: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def request_json(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 60) -> tuple[int, dict[str, str], Any]:
    data = None
    final_headers = {"Content-Type": "application/json"} if payload is not None else {}
    if headers:
        final_headers.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{base_url.rstrip('/')}{path}", data=data, headers=final_headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        return resp.status, dict(resp.headers), json.loads(body.decode("utf-8")) if body else None


def login_headers(base_url: str, email: str, password: str, token: str) -> dict[str, str]:
    if token:
        return {"Authorization": f"Bearer {token}"}
    if not email or not password:
        return {}
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


def run_script(cmd: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def extract_result_payload(output: str) -> dict[str, Any] | None:
    lines = output.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() != "### Result":
            continue
        for candidate in lines[idx + 1:]:
            text = candidate.strip()
            if not text:
                continue
            if not text.startswith("{"):
                return None
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


def run_browser_regression(script_path: Path, base_url: str, email: str, password: str, *, check_name: str | None = None) -> CheckResult:
    cmd = [sys.executable, str(script_path), "--base-url", base_url]
    if email:
        cmd.extend(["--email", email])
    if password:
        cmd.extend(["--password", password])
    code, stdout, stderr = run_script(cmd)
    status = "PASS" if code == 0 else "FAIL"
    detail = stdout or stderr
    parsed_result = extract_result_payload(stdout)
    details: dict[str, Any] = {"output": detail}
    if parsed_result is not None:
        details["result"] = parsed_result
    return CheckResult(
        name=check_name or script_path.stem,
        status=status,
        details=details,
        failures=[] if code == 0 else [detail or f"{script_path.name} exited {code}"],
    )


def evaluate_room_contract(stoa_check: CheckResult, aegis_check: CheckResult) -> CheckResult:
    failures: list[str] = []
    details: dict[str, Any] = {}

    stoa_result = stoa_check.details.get("result")
    aegis_result = aegis_check.details.get("result")

    if isinstance(stoa_result, dict):
        details["stoa"] = stoa_result
    if isinstance(aegis_result, dict):
        details["aegis"] = aegis_result

    if stoa_check.status != "PASS":
        failures.append("Stoa browser regression did not pass")
    elif not isinstance(stoa_result, dict):
        failures.append("Stoa browser regression did not return structured room-contract data")
    else:
        if stoa_result.get("clarifying_state") != "visible":
            failures.append(f"Stoa clarifying state drifted: {stoa_result.get('clarifying_state')}")
        if stoa_result.get("leia_path") != "ambiguity_then_vehicle":
            failures.append(f"LEIA path drifted: {stoa_result.get('leia_path')}")
        if stoa_result.get("smx_path") != "vendor_first":
            failures.append(f"SMX path drifted: {stoa_result.get('smx_path')}")
        if stoa_result.get("handoff") not in {"brief_open", "ready"}:
            failures.append(f"Unexpected Stoa handoff state: {stoa_result.get('handoff')}")

    if aegis_check.status != "PASS":
        failures.append("Aegis carryover regression did not pass")
    elif not isinstance(aegis_result, dict):
        failures.append("Aegis carryover regression did not return structured room-contract data")
    else:
        if aegis_result.get("carryover") != "passed":
            failures.append(f"Aegis carryover drifted: {aegis_result.get('carryover')}")

    return CheckResult(
        name="room_contract",
        status="FAIL" if failures else "PASS",
        details=details,
        failures=failures,
    )


def _latency_stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    def pct(p: int) -> float:
        idx = max(0, min(len(ordered) - 1, int(round((p / 100) * (len(ordered) - 1)))))
        return round(ordered[idx], 1)
    return {
        "count": len(values),
        "p50_ms": pct(50),
        "p95_ms": pct(95),
        "max_ms": round(max(values), 1),
        "avg_ms": round(statistics.mean(values), 1),
    }


def run_graph_timing(base_url: str, headers: dict[str, str]) -> CheckResult:
    failures: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}

    try:
        t = time.perf_counter()
        _, _, health = request_json(base_url, "GET", "/api/health", headers=headers, timeout=30)
        details["health_ms"] = round((time.perf_counter() - t) * 1000, 1)
        details["connector_count"] = int((health or {}).get("osint_connector_count") or 0)
    except Exception as exc:
        return CheckResult("graph_timing", "FAIL", failures=[f"health failed: {exc}"])

    try:
        t = time.perf_counter()
        _, _, resolve_smx = request_json(
            base_url,
            "POST",
            "/api/resolve",
            {"name": "SMX", "country": "US", "use_ai": False, "max_candidates": 6},
            headers=headers,
            timeout=45,
        )
        details["resolve_smx_ms"] = round((time.perf_counter() - t) * 1000, 1)
        candidates = resolve_smx.get("candidates") if isinstance(resolve_smx, dict) else []
        details["resolve_smx_candidates"] = len(candidates or [])
    except Exception as exc:
        failures.append(f"resolve SMX failed: {exc}")
        candidates = []

    try:
        t = time.perf_counter()
        _, _, resolve_vehicle = request_json(
            base_url,
            "POST",
            "/api/resolve",
            {"name": "ILS 2", "country": "US", "use_ai": False, "max_candidates": 6},
            headers=headers,
            timeout=45,
        )
        details["resolve_vehicle_ms"] = round((time.perf_counter() - t) * 1000, 1)
        vehicle_candidates = resolve_vehicle.get("candidates") if isinstance(resolve_vehicle, dict) else []
        details["resolve_vehicle_candidates"] = len(vehicle_candidates or [])
    except Exception as exc:
        failures.append(f"resolve ILS 2 failed: {exc}")

    try:
        t = time.perf_counter()
        _, _, communities = request_json(base_url, "GET", "/api/graph/analytics/communities", headers=headers, timeout=120)
        details["communities_ms"] = round((time.perf_counter() - t) * 1000, 1)
        details["communities_algorithm"] = str((communities or {}).get("algorithm") or "")
        community_map = communities.get("communities") if isinstance(communities, dict) else {}
        first_community = next(iter(community_map.values())) if isinstance(community_map, dict) and community_map else {}
        members = first_community.get("members") if isinstance(first_community, dict) else []
        entity_id = ""
        if isinstance(members, list) and members:
            entity_id = str((members[0] or {}).get("id") or "")
        if not entity_id and candidates:
            entity_id = str((candidates[0] or {}).get("entity_id") or "")
        if not entity_id:
            failures.append("No entity id available for graph interrogation timing")
        else:
            details["entity_id"] = entity_id
            profile_times: list[float] = []
            anomaly_times: list[float] = []
            for _ in range(3):
                t = time.perf_counter()
                request_json(
                    base_url,
                    "POST",
                    "/api/axiom/graph/profile",
                    {"entity_id": entity_id},
                    headers=headers,
                    timeout=120,
                )
                profile_times.append((time.perf_counter() - t) * 1000)

                t = time.perf_counter()
                request_json(
                    base_url,
                    "POST",
                    "/api/axiom/graph/anomalies",
                    {"entity_id": entity_id},
                    headers=headers,
                    timeout=120,
                )
                anomaly_times.append((time.perf_counter() - t) * 1000)

            details["graph_profile"] = _latency_stats(profile_times)
            details["graph_anomalies"] = _latency_stats(anomaly_times)
    except Exception as exc:
        failures.append(f"communities/graph interrogation failed: {exc}")

    if details.get("communities_ms", 0) and details["communities_ms"] > 1500:
        warnings.append("Community detection is above the 1.5s comfort band")
    if isinstance(details.get("graph_profile"), dict) and float(details["graph_profile"].get("p95_ms", 0)) > 3000:
        warnings.append("Graph profile p95 exceeds 3s")
    if isinstance(details.get("graph_anomalies"), dict) and float(details["graph_anomalies"].get("p95_ms", 0)) > 3000:
        warnings.append("Graph anomalies p95 exceeds 3s")

    return CheckResult(
        name="graph_timing",
        status="FAIL" if failures else "PASS",
        details=details,
        failures=failures,
        warnings=warnings,
    )


def _token_from_headers(headers: dict[str, str]) -> str:
    auth = headers.get("Authorization", "").strip()
    if not auth.lower().startswith("bearer "):
        return ""
    return auth.split(" ", 1)[1].strip()


def run_authenticated_case_flow(base_url: str, email: str, password: str, token: str, headers: dict[str, str]) -> CheckResult:
    if not (token or (email and password)):
        return CheckResult("authenticated_case_flow", "SKIP", warnings=["No credentials provided"])

    cmd = [sys.executable, str(SMOKE_SCRIPT), "--base-url", base_url, "--skip-stream", "--skip-runtime-env"]
    smoke_token = token or _token_from_headers(headers)
    if smoke_token:
        cmd.extend(["--token", smoke_token])
    elif email and password:
        cmd.extend(["--email", email, "--password", password])
    else:
        return CheckResult(
            "authenticated_case_flow",
            "FAIL",
            failures=["Authenticated case flow could not acquire a token or credentials"],
        )
    code, stdout, stderr = run_script(cmd)
    return CheckResult(
        name="authenticated_case_flow",
        status="PASS" if code == 0 else "FAIL",
        details={"output": stdout or stderr},
        failures=[] if code == 0 else [stdout or stderr or "authenticated case flow failed"],
    )


def write_reports(report_dir: Path, summary: dict[str, Any]) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    json_path = report_dir / f"current_product_stress_harness_{stamp}.json"
    md_path = report_dir / f"current_product_stress_harness_{stamp}.md"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Current Product Stress Harness",
        "",
        f"Generated: {summary['generated_at']}",
        f"Base URL: {summary['base_url']}",
        f"Overall verdict: {summary['overall_verdict']}",
        "",
        "## Checks",
        "",
    ]
    for check in summary["checks"]:
        lines.append(f"### {check['name']}")
        lines.append("")
        lines.append(f"- Status: `{check['status']}`")
        if check["failures"]:
            lines.append(f"- Failures: {', '.join(check['failures'])}")
        if check["warnings"]:
            lines.append(f"- Warnings: {', '.join(check['warnings'])}")
        if check["details"]:
            lines.append("- Details:")
            for key, value in check["details"].items():
                lines.append(f"  - {key}: `{value}`")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the canonical current-product Helios stress harness.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8113")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")

    health_status, _, health = request_json(base_url, "GET", "/api/health", timeout=30)
    if health_status != 200 or not isinstance(health, dict):
        raise SystemExit("/api/health failed")

    checks: list[CheckResult] = []
    stoa_check = run_browser_regression(
        FRONT_PORCH_SCRIPT,
        base_url,
        "",
        "",
        check_name="stoa_browser_regression",
    )
    aegis_check = run_browser_regression(
        AEGIS_CARRYOVER_SCRIPT,
        base_url,
        args.email,
        args.password,
        check_name="aegis_carryover_regression",
    )
    checks.append(stoa_check)
    checks.append(aegis_check)
    checks.append(evaluate_room_contract(stoa_check, aegis_check))

    headers = login_headers(base_url, args.email, args.password, args.token)
    checks.append(run_graph_timing(base_url, headers))
    checks.append(run_authenticated_case_flow(base_url, args.email, args.password, args.token, headers))

    overall_verdict = "PASS"
    if any(check.status == "FAIL" for check in checks):
        overall_verdict = "FAIL"

    summary = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "base_url": base_url,
        "overall_verdict": overall_verdict,
        "health": health,
        "checks": [asdict(check) for check in checks],
    }
    md_path, json_path = write_reports(Path(args.report_dir), summary)
    summary["report_md"] = str(md_path)
    summary["report_json"] = str(json_path)

    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Wrote {md_path}")
        print(f"Wrote {json_path}")

    return 0 if overall_verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
