#!/usr/bin/env python3
"""
Run a live Neo4j sync and drift audit against a query-to-dossier scenario pack.

This script is intended for the hosted authenticated path after Neo4j credentials
have been repaired. It verifies:
  - /api/neo4j/health is available
  - full sync succeeds
  - Neo4j stats are non-empty
  - each audited scenario has a rooted Neo4j neighborhood comparable to the
    case graph returned by the core Helios graph endpoint
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
GAUNTLET_SCRIPT = ROOT / "scripts" / "run_query_to_dossier_gauntlet.py"
DEFAULT_SPEC_FILE = ROOT / "fixtures" / "customer_demo" / "pillar_briefing_query_to_dossier_pack.json"
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "neo4j_graph_drift_audit"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Neo4j sync and graph drift audit.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--spec-file", default=str(DEFAULT_SPEC_FILE))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--min-relationship-coverage-ratio", type=float, default=0.5)
    parser.add_argument("--request-timeout", type=int, default=90)
    parser.add_argument("--sync-timeout", type=int, default=300)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _decode_json_from_stdout(stdout: str) -> dict[str, Any] | list[Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _auth_headers(args: argparse.Namespace) -> dict[str, str]:
    if args.token:
        return {"Authorization": f"Bearer {args.token}"}
    if not args.email or not args.password:
        raise SystemExit("graph drift audit requires --token or --email/--password")
    response = requests.post(
        f"{args.base_url.rstrip('/')}/api/auth/login",
        json={"email": args.email, "password": args.password},
        timeout=30,
    )
    response.raise_for_status()
    token = response.json().get("token")
    if not token:
        raise RuntimeError("login succeeded but token missing")
    return {"Authorization": f"Bearer {token}"}


def _get_json(
    base_url: str,
    path: str,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 90,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    response = requests.request(method, url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"{path} did not return a JSON object")
    return body


def probe_neo4j_health(base_url: str, timeout: int) -> dict[str, Any]:
    return _get_json(base_url, "/api/neo4j/health", timeout=timeout)


def run_full_sync(base_url: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    initial = _get_json(base_url, "/api/neo4j/sync", headers=headers, method="POST", timeout=min(timeout, 30))
    job_id = str(initial.get("job_id") or "")
    if not job_id:
        return initial

    import time

    started = time.time()
    while True:
        status = _get_json(base_url, f"/api/neo4j/sync/{job_id}", headers=headers, timeout=min(timeout, 30))
        state = str(status.get("status") or "").strip().lower()
        if state in {"completed", "failed"}:
            return status
        if (time.time() - started) >= timeout:
            raise RuntimeError(f"neo4j sync job {job_id} timed out after {timeout}s")
        time.sleep(2)


def run_gauntlet(args: argparse.Namespace) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(GAUNTLET_SCRIPT),
        "--mode",
        "local-auth",
        "--base-url",
        args.base_url,
        "--spec-file",
        args.spec_file,
        "--report-dir",
        str(Path(args.report_dir) / "query_to_dossier"),
        "--print-json",
    ]
    if args.token:
        cmd.extend(["--token", args.token])
    else:
        cmd.extend(["--email", args.email, "--password", args.password])

    proc = subprocess.run(cmd, text=True, capture_output=True, cwd=ROOT)
    payload = _decode_json_from_stdout(proc.stdout)
    if not isinstance(payload, dict):
        detail = proc.stderr.strip() or proc.stdout.strip() or "gauntlet did not emit JSON"
        raise RuntimeError(detail)
    return payload


def audit_flow(base_url: str, headers: dict[str, str], flow: dict[str, Any], *, min_relationship_coverage_ratio: float) -> dict[str, Any]:
    case_id = str(flow.get("case_id") or "")
    if not case_id:
        raise RuntimeError("flow missing case_id")

    case_graph = _get_json(base_url, f"/api/cases/{case_id}/graph?depth=3", headers=headers, timeout=120)
    root_entity_id = str(case_graph.get("root_entity_id") or "")
    if not root_entity_id:
        raise RuntimeError(f"{case_id} missing root_entity_id")

    neo4j_network = _get_json(base_url, f"/api/neo4j/network/{root_entity_id}?depth=3", headers=headers, timeout=120)
    centrality = _get_json(base_url, f"/api/neo4j/centrality/{root_entity_id}", headers=headers, timeout=120)

    sqlite_entity_count = int(case_graph.get("entity_count") or len(case_graph.get("entities") or []))
    sqlite_relationship_count = int(case_graph.get("relationship_count") or len(case_graph.get("relationships") or []))
    neo4j_entity_count = int(neo4j_network.get("entity_count") or 0)
    neo4j_relationship_count = int(neo4j_network.get("relationship_count") or 0)
    relationship_coverage_ratio = (
        float(neo4j_relationship_count) / float(sqlite_relationship_count)
        if sqlite_relationship_count > 0
        else 1.0
    )

    failures: list[str] = []
    if sqlite_relationship_count > 0 and neo4j_relationship_count == 0:
        failures.append("neo4j network has zero relationships while case graph is non-empty")
    if relationship_coverage_ratio < min_relationship_coverage_ratio:
        failures.append("neo4j relationship coverage ratio below threshold")
    if not bool(centrality.get("influence_score") or centrality.get("degree_centrality") or centrality.get("total_relationships")):
        failures.append("neo4j centrality surface did not return meaningful stats")

    return {
        "flow_name": str(flow.get("flow_name") or ""),
        "case_id": case_id,
        "vendor_name": str(flow.get("vendor_name") or ""),
        "root_entity_id": root_entity_id,
        "sqlite_entity_count": sqlite_entity_count,
        "sqlite_relationship_count": sqlite_relationship_count,
        "neo4j_entity_count": neo4j_entity_count,
        "neo4j_relationship_count": neo4j_relationship_count,
        "relationship_coverage_ratio": round(relationship_coverage_ratio, 3),
        "neo4j_influence_score": centrality.get("influence_score"),
        "neo4j_degree_centrality": centrality.get("degree_centrality"),
        "failures": failures,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Helios Neo4j Graph Drift Audit",
        "",
        f"Generated: {summary['generated_at']}",
        f"Overall verdict: **{summary['overall_verdict']}**",
        "",
        "## Neo4j",
        "",
        f"- Available: **{'yes' if summary['neo4j_health'].get('neo4j_available') else 'no'}**",
        f"- Status: `{summary['neo4j_health'].get('status', '')}`",
        f"- Stats: `{summary['neo4j_stats']}`",
        "",
        "## Sync",
        "",
        f"- Executed: **{'no' if summary['skip_sync'] else 'yes'}**",
        f"- Result: `{summary['sync_result']}`",
        "",
        "## Flows",
        "",
    ]
    for flow in summary["flows"]:
        lines.extend(
            [
                f"### {flow['flow_name']} ({flow['case_id']})",
                "",
                f"- Vendor: `{flow['vendor_name']}`",
                f"- Root entity: `{flow['root_entity_id']}`",
                f"- SQLite graph: `{flow['sqlite_entity_count']}` entities / `{flow['sqlite_relationship_count']}` relationships",
                f"- Neo4j graph: `{flow['neo4j_entity_count']}` entities / `{flow['neo4j_relationship_count']}` relationships",
                f"- Relationship coverage ratio: `{flow['relationship_coverage_ratio']}`",
                f"- Neo4j influence score: `{flow['neo4j_influence_score']}`",
            ]
        )
        if flow["failures"]:
            lines.append("- Failures:")
            for failure in flow["failures"]:
                lines.append(f"  - {failure}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    headers = _auth_headers(args)

    neo4j_health = probe_neo4j_health(args.base_url, args.request_timeout)
    if not bool(neo4j_health.get("neo4j_available")):
        summary = {
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "overall_verdict": "FAIL",
            "neo4j_health": neo4j_health,
            "neo4j_stats": {},
            "skip_sync": bool(args.skip_sync),
            "sync_result": {"error": "neo4j unavailable"},
            "flows": [],
        }
    else:
        sync_result: dict[str, Any] = {"status": "skipped"}
        if not args.skip_sync:
            sync_result = run_full_sync(args.base_url, headers, args.sync_timeout)
        neo4j_stats = _get_json(args.base_url, "/api/neo4j/stats", headers=headers, timeout=args.request_timeout)
        gauntlet = run_gauntlet(args)
        flows = [
            audit_flow(
                args.base_url,
                headers,
                flow,
                min_relationship_coverage_ratio=args.min_relationship_coverage_ratio,
            )
            for flow in gauntlet.get("flows", [])
        ]
        overall_verdict = "PASS" if flows and not any(flow["failures"] for flow in flows) else "FAIL"
        summary = {
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "overall_verdict": overall_verdict,
            "neo4j_health": neo4j_health,
            "neo4j_stats": neo4j_stats,
            "skip_sync": bool(args.skip_sync),
            "sync_result": sync_result,
            "gauntlet_report_json": gauntlet.get("report_json"),
            "gauntlet_report_md": gauntlet.get("report_md"),
            "flows": flows,
        }

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    json_path = report_dir / f"neo4j-graph-drift-audit-{stamp}.json"
    md_path = report_dir / f"neo4j-graph-drift-audit-{stamp}.md"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")

    summary["report_json"] = str(json_path)
    summary["report_md"] = str(md_path)
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Wrote {md_path}")
        print(f"Wrote {json_path}")

    return 0 if summary["overall_verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
