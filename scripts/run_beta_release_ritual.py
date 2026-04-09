#!/usr/bin/env python3
"""Run the minimal beta release ritual against a target Helios instance."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "beta_release_ritual"
CURRENT_PRODUCT_SCRIPT = ROOT / "scripts" / "run_current_product_stress_harness.py"
QUERY_TO_DOSSIER_SCRIPT = ROOT / "scripts" / "run_live_query_to_dossier_canary.py"
VEHICLE_INTEL_SCRIPT = ROOT / "scripts" / "run_vehicle_intelligence_canary.py"
RELEASE_SPEC_FILE = ROOT / "fixtures" / "customer_demo" / "query_to_dossier_release_pack.json"
READINESS_TOKEN_PATH = Path.home() / ".config" / "xiphos" / "readiness_token.json"
DEPLOY_ENV_PATH = Path.home() / ".config" / "xiphos" / "deploy.env"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the minimal Helios beta release ritual.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = None
    request_headers = dict(headers or {})
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        return json.loads(body.decode("utf-8")) if body else {}


def _cached_token(base_url: str) -> str:
    if not READINESS_TOKEN_PATH.exists():
        return ""
    try:
        payload = json.loads(READINESS_TOKEN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ""
    cached_base_url = str(payload.get("base_url") or "").rstrip("/")
    if cached_base_url and cached_base_url != base_url.rstrip("/"):
        return ""
    return str(payload.get("token") or "").strip()


def _deploy_credentials(args: argparse.Namespace) -> tuple[str, str]:
    if args.email and args.password:
        return args.email, args.password
    if not DEPLOY_ENV_PATH.exists():
        return "", ""
    try:
        lines = DEPLOY_ENV_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return "", ""
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    email = values.get("XIPHOS_DEPLOY_ADMIN_EMAIL") or values.get("XIPHOS_DEPLOY_LOGIN_EMAIL") or ""
    password = values.get("XIPHOS_DEPLOY_ADMIN_PASSWORD") or values.get("XIPHOS_DEPLOY_LOGIN_PASSWORD") or ""
    return email, password


def _token_is_valid(base_url: str, token: str) -> bool:
    if not token:
        return False
    try:
        payload = _request_json(
            base_url,
            "GET",
            "/api/auth/me",
            timeout=15,
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception:
        return False
    return isinstance(payload, dict) and bool(
        payload.get("sub")
        or payload.get("email")
        or payload.get("role")
        or payload.get("user")
    )


def _login_token(args: argparse.Namespace) -> str:
    email, password = _deploy_credentials(args)
    if args.token and _token_is_valid(args.base_url, args.token):
        return args.token
    cached = _cached_token(args.base_url)
    if cached and _token_is_valid(args.base_url, cached):
        return cached
    if not (email and password):
        raise RuntimeError("beta release ritual requires --token or --email/--password")
    payload = _request_json(
        args.base_url,
        "POST",
        "/api/auth/login",
        {"email": email, "password": password},
        timeout=30,
    )
    token = str(payload.get("token") or "").strip()
    if not token:
        raise RuntimeError("beta release ritual login did not return a token")
    return token


def _decode_json(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _run_json_script(script: Path, args: argparse.Namespace, token: str) -> dict[str, Any]:
    command = [
        sys.executable,
        str(script),
        "--base-url",
        args.base_url,
        "--print-json",
    ]
    if token:
        command.extend(["--token", token])
    if script == QUERY_TO_DOSSIER_SCRIPT:
        command.extend(["--spec-file", str(RELEASE_SPEC_FILE)])
    if script == CURRENT_PRODUCT_SCRIPT:
        email, password = _deploy_credentials(args)
        if email and password:
            command.extend(["--email", email, "--password", password])
        elif not token:
            raise RuntimeError("current product stress harness requires a token or deploy credentials")
    if script == VEHICLE_INTEL_SCRIPT:
        email, password = _deploy_credentials(args)
        if email and password:
            command.extend(["--email", email, "--password", password])
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    payload = _decode_json(completed.stdout)
    if payload is None:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"{script.name} did not emit JSON"
        raise RuntimeError(detail)
    payload["exit_code"] = completed.returncode
    payload["script"] = script.name
    return payload


def _write_report(args: argparse.Namespace, results: list[dict[str, Any]]) -> tuple[Path, Path, str]:
    report_root = Path(args.report_dir)
    report_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    report_dir = report_root / stamp
    report_dir.mkdir(parents=True, exist_ok=True)

    overall_verdict = "PASS" if all(str(result.get("overall_verdict") or "") == "PASS" and int(result.get("exit_code") or 0) == 0 for result in results) else "FAIL"
    payload = {
        "overall_verdict": overall_verdict,
        "generated_at": datetime.now().isoformat(),
        "base_url": args.base_url,
        "results": results,
    }
    json_path = report_dir / "summary.json"
    md_path = report_dir / "summary.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Beta Release Ritual",
        "",
        f"- Overall verdict: `{overall_verdict}`",
        f"- Base URL: `{args.base_url}`",
        "",
        "## Gates",
        "",
    ]
    for result in results:
        lines.append(
            f"- `{result.get('script')}`: verdict `{result.get('overall_verdict', 'unknown')}` exit `{result.get('exit_code', -1)}`"
        )
        if result.get("report_md"):
            lines.append(f"  - report: `{result['report_md']}`")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path, overall_verdict


def main() -> int:
    args = parse_args()
    token = _login_token(args)
    results = [
        _run_json_script(CURRENT_PRODUCT_SCRIPT, args, token),
        _run_json_script(QUERY_TO_DOSSIER_SCRIPT, args, token),
        _run_json_script(VEHICLE_INTEL_SCRIPT, args, token),
    ]
    md_path, json_path, overall_verdict = _write_report(args, results)
    payload = {
        "overall_verdict": overall_verdict,
        "report_md": str(md_path),
        "report_json": str(json_path),
        "results": results,
    }
    if args.print_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Wrote {md_path}")
        print(f"Wrote {json_path}")
    return 0 if overall_verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
