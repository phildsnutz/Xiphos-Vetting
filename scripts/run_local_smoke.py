#!/usr/bin/env python3
"""
Run a lightweight end-to-end smoke test against a running Xiphos server.

Designed for local validation and CI. Works in dev mode without auth, or
against an authenticated environment when login credentials are provided.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def request_json(base_url: str, method: str, path: str, payload=None, headers=None, timeout: int = 30):
    data = None
    final_headers = {"Content-Type": "application/json"} if payload is not None else {}
    if headers:
        final_headers.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=final_headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        return resp.status, dict(resp.headers), json.loads(body.decode("utf-8")) if body else None


def request_bytes(base_url: str, method: str, path: str, data=None, headers=None, timeout: int = 30):
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, dict(resp.headers), resp.read()


def multipart_upload(base_url: str, path: str, filename: str, content: str, headers=None, timeout: int = 30):
    boundary = "----xiphossmokeboundary"
    body = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: text/csv\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    upload_headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if headers:
        upload_headers.update(headers)
    return request_bytes(base_url, "POST", path, body, headers=upload_headers, timeout=timeout)


def fail(message: str):
    print(f"FAIL: {message}")
    sys.exit(1)


def login_with_retry(base_url: str, email: str, password: str, *, wait_seconds: int, poll_seconds: float = 2.0):
    deadline = time.monotonic() + max(wait_seconds, 0)
    last_error: Exception | None = None
    while True:
        try:
            status, _, login = request_json(
                base_url,
                "POST",
                "/api/auth/login",
                {"email": email, "password": password},
                timeout=20,
            )
            if status == 200:
                return login
            last_error = RuntimeError(f"auth login returned {status}")
        except Exception as exc:
            last_error = exc

        if time.monotonic() >= deadline:
            if last_error:
                raise last_error
            raise RuntimeError("auth login failed")
        time.sleep(poll_seconds)


def wait_for_health(base_url: str, *, headers=None, wait_seconds: int, poll_seconds: float = 2.0):
    deadline = time.monotonic() + max(wait_seconds, 0)
    last_error: Exception | None = None
    while True:
        try:
            status, _, health = request_json(base_url, "GET", "/api/health", headers=headers, timeout=20)
            if status == 200:
                return health
            last_error = RuntimeError(f"/api/health returned {status}")
        except Exception as exc:
            last_error = exc

        if time.monotonic() >= deadline:
            if last_error:
                raise last_error
            raise RuntimeError("health check failed")
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local Xiphos smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--skip-stream", action="store_true")
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--wait-for-ready-seconds", type=int, default=0)
    args = parser.parse_args()

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    elif args.email and args.password:
        try:
            login = login_with_retry(
                args.base_url,
                args.email,
                args.password,
                wait_seconds=args.wait_for_ready_seconds,
            )
        except Exception as exc:
            fail(f"auth login failed: {exc}")
        headers["Authorization"] = f"Bearer {login['token']}"

    print("PASS: starting smoke")

    try:
        health = wait_for_health(
            args.base_url,
            headers=headers,
            wait_seconds=args.wait_for_ready_seconds,
        )
    except Exception as exc:
        fail(f"/api/health failed: {exc}")
    print(f"PASS: health ({health.get('osint_connector_count', 0)} connectors)")

    status, _, providers = request_json(args.base_url, "GET", "/api/ai/providers", headers=headers, timeout=20)
    if status != 200 or not providers.get("providers"):
        fail(f"/api/ai/providers returned {status}")
    print("PASS: ai providers")

    if args.read_only:
        if "Authorization" not in headers:
            fail("read-only smoke requires auth credentials or token")

        status, _, snapshot = request_json(
            args.base_url,
            "GET",
            "/api/portfolio/snapshot",
            headers=headers,
            timeout=30,
        )
        if status != 200 or not isinstance(snapshot, dict):
            fail(f"/api/portfolio/snapshot returned {status}")
        print("PASS: portfolio snapshot")

        status, _, changes = request_json(
            args.base_url,
            "GET",
            "/api/monitor/changes?limit=1",
            headers=headers,
            timeout=30,
        )
        if status != 200 or "changes" not in (changes or {}):
            fail(f"/api/monitor/changes returned {status}")
        print("PASS: monitor changes")

        print("PASS: read-only smoke complete")
        return 0

    status, _, compare = request_json(
        args.base_url,
        "POST",
        "/api/compare",
        {"name": "Boeing", "country": "US", "profiles": ["defense_acquisition", "commercial_supply_chain"]},
        headers=headers,
        timeout=30,
    )
    if status != 200 or len(compare.get("comparisons", [])) != 2:
        fail(f"/api/compare returned {status}")
    print("PASS: compare")

    vendor_name = f"Smoke Vendor {int(time.time())}"
    status, _, created = request_json(
        args.base_url,
        "POST",
        "/api/cases",
        {
            "name": vendor_name,
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
        },
        headers=headers,
        timeout=30,
    )
    if status != 201:
        fail(f"/api/cases returned {status}")
    case_id = created["case_id"]
    print("PASS: create case")

    status, _, decision = request_json(
        args.base_url,
        "POST",
        f"/api/cases/{case_id}/decision",
        {"decision": "approve", "reason": "smoke-test"},
        headers=headers,
        timeout=30,
    )
    if status != 201 or decision.get("decision") != "approve":
        fail(f"/api/cases/{case_id}/decision returned {status}")
    print("PASS: decision create")

    status, _, decisions = request_json(
        args.base_url,
        "GET",
        f"/api/cases/{case_id}/decisions?limit=5",
        headers=headers,
        timeout=30,
    )
    if status != 200 or decisions.get("latest_decision", {}).get("decision") != "approve":
        fail(f"/api/cases/{case_id}/decisions returned {status}")
    print("PASS: decision list")

    status, _, passport = request_json(
        args.base_url,
        "GET",
        f"/api/cases/{case_id}/supplier-passport",
        headers=headers,
        timeout=30,
    )
    if status != 200 or passport.get("case_id") != case_id or not passport.get("passport_version"):
        fail(f"/api/cases/{case_id}/supplier-passport returned {status}")
    print("PASS: supplier passport")

    status, _, assistant_plan = request_json(
        args.base_url,
        "POST",
        f"/api/cases/{case_id}/assistant-plan",
        {"prompt": "Trace the strongest control path and explain the current risk posture."},
        headers=headers,
        timeout=30,
    )
    if (
        status != 200
        or assistant_plan.get("case_id") != case_id
        or assistant_plan.get("version") != "ai-control-plane-v1"
        or not assistant_plan.get("plan")
    ):
        fail(f"/api/cases/{case_id}/assistant-plan returned {status}")
    print("PASS: assistant plan")

    approved_tool_ids = [
        step["tool_id"]
        for step in assistant_plan.get("plan", [])
        if step.get("required")
    ]
    status, _, assistant_exec = request_json(
        args.base_url,
        "POST",
        f"/api/cases/{case_id}/assistant-execute",
        {"prompt": assistant_plan.get("analyst_prompt"), "approved_tool_ids": approved_tool_ids},
        headers=headers,
        timeout=30,
    )
    if (
        status != 200
        or assistant_exec.get("case_id") != case_id
        or assistant_exec.get("version") != "ai-control-plane-execution-v1"
        or not assistant_exec.get("executed_steps")
    ):
        fail(f"/api/cases/{case_id}/assistant-execute returned {status}")
    print("PASS: assistant execute")

    status, _, assistant_feedback = request_json(
        args.base_url,
        "POST",
        f"/api/cases/{case_id}/assistant-feedback",
        {
            "prompt": assistant_plan.get("analyst_prompt"),
            "objective": assistant_plan.get("objective"),
            "verdict": "partial",
            "feedback_type": "tool_missing",
            "comment": "Smoke path: capture a structured analyst correction.",
            "approved_tool_ids": approved_tool_ids,
            "executed_tool_ids": [step.get("tool_id") for step in assistant_exec.get("executed_steps", [])],
            "suggested_tool_ids": ["graph_probe"],
            "anomaly_codes": [item.get("code") for item in assistant_plan.get("anomalies", []) if item.get("code")],
        },
        headers=headers,
        timeout=30,
    )
    if status != 201 or assistant_feedback.get("status") != "ok" or not assistant_feedback.get("feedback_id"):
        fail(f"/api/cases/{case_id}/assistant-feedback returned {status}")
    print("PASS: assistant feedback")

    status, pdf_headers, pdf_bytes = request_bytes(
        args.base_url,
        "POST",
        f"/api/cases/{case_id}/dossier-pdf",
        b"{}",
        headers={"Content-Type": "application/json", **headers},
        timeout=60,
    )
    if status != 200 or not pdf_headers.get("Content-Type", "").startswith("application/pdf") or len(pdf_bytes) == 0:
        fail(f"/api/cases/{case_id}/dossier-pdf returned {status}")
    print("PASS: dossier pdf")

    status, _, batch_body = multipart_upload(
        args.base_url,
        "/api/batch/upload",
        "vendors.csv",
        "name,country\nAcme Systems,US\nNorthwind GmbH,DE\n",
        headers=headers,
        timeout=60,
    )
    if status != 201:
        fail(f"/api/batch/upload returned {status}")
    batch = json.loads(batch_body.decode("utf-8"))
    batch_id = batch["batch_id"]

    detail = None
    for _ in range(60):
        status, _, detail = request_json(args.base_url, "GET", f"/api/batch/{batch_id}", headers=headers, timeout=30)
        if status != 200:
            fail(f"/api/batch/{batch_id} returned {status}")
        if detail["status"] in {"completed", "failed"}:
            break
        time.sleep(0.1)
    if not detail or detail["status"] != "completed":
        fail(f"batch {batch_id} did not complete successfully")

    status, csv_headers, csv_bytes = request_bytes(
        args.base_url,
        "GET",
        f"/api/batch/{batch_id}/report",
        headers=headers,
        timeout=30,
    )
    if status != 200 or not csv_headers.get("Content-Type", "").startswith("text/csv") or b"vendor_name,country,status" not in csv_bytes:
        fail(f"/api/batch/{batch_id}/report returned {status}")
    print("PASS: batch upload/report")

    if not args.skip_stream:
        status, _, stream_bytes = request_bytes(
            args.base_url,
            "GET",
            f"/api/cases/{case_id}/enrich-stream",
            headers=headers,
            timeout=120,
        )
        text = stream_bytes.decode("utf-8", errors="replace")
        if status != 200:
            fail(f"/api/cases/{case_id}/enrich-stream returned {status}")
        required = ("event: start", "event: complete", "event: scored", "event: done")
        if not all(marker in text for marker in required) or "event: error" in text:
            fail("enrich-stream did not complete cleanly")
        print("PASS: enrich stream")

    print("PASS: smoke complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        fail(f"{exc.code} {exc.reason}: {body}")
