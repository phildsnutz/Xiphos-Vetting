#!/usr/bin/env python3
"""
Run a live dossier QA sweep against the VPS-backed Helios instance and export
the strongest sample cases into a customer pilot packet.

This is a higher-volume, dossier-first companion to run_live_beta_hardening_report.py.
It:
  - pulls live scored cases from the running container
  - builds a tier-diverse, non-synthetic cohort
  - warms AI narratives for the cohort
  - validates HTML/PDF dossier quality plus graph/monitoring parity
  - exports a best-3 sample packet with HTML + PDF dossiers
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import shlex
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader  # type: ignore
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"pypdf is required for live dossier QA: {exc}")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_USER_ID = "b24f39e7"
DEFAULT_LIMIT = 24

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

PACKET_LABELS = {
    "TIER_4_CLEAR": "Clear",
    "TIER_4_CRITICAL_QUALIFIED": "Qualified / Watchlist",
    "TIER_1_DISQUALIFIED": "Blocked",
}

TIER_TARGETS = [
    ("TIER_1_DISQUALIFIED", 4),
    ("TIER_3_CONDITIONAL", 2),
    ("TIER_4_CRITICAL_QUALIFIED", 1),
    ("TIER_4_APPROVED", 4),
    ("TIER_4_CLEAR", 13),
]

SYNTHETIC_PATTERNS = [
    re.compile(r"^DEPLOY_VERIFY$", re.IGNORECASE),
    re.compile(r"^AI Warm Verify\b", re.IGNORECASE),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a live dossier QA batch and export a 3-case pilot packet.")
    parser.add_argument("--host", default="root@24.199.122.225")
    parser.add_argument("--container", default="xiphos-xiphos-1")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--graph-depth", type=int, default=3)
    parser.add_argument("--warm-timeout", type=int, default=300)
    parser.add_argument(
        "--report-dir",
        default=str(ROOT / "docs" / "reports"),
    )
    parser.add_argument(
        "--packet-dir",
        default=str(ROOT / "docs" / "marketing" / "pilot_case_packet_2026-03-23"),
    )
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def is_synthetic_vendor(vendor: dict[str, Any]) -> bool:
    name = str(vendor.get("name") or "").strip()
    return any(pattern.search(name) for pattern in SYNTHETIC_PATTERNS)


def build_default_cohort(vendors: list[dict[str, Any]], limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    real_vendors = [vendor for vendor in vendors if not is_synthetic_vendor(vendor)]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for vendor in real_vendors:
        grouped[str(vendor.get("tier") or "unknown")].append(vendor)

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    for tier, quota in TIER_TARGETS:
        for vendor in grouped.get(tier, [])[:quota]:
            if vendor["id"] not in selected_ids and len(selected) < limit:
                selected.append(vendor)
                selected_ids.add(vendor["id"])

    if len(selected) < limit:
        for vendor in real_vendors:
            if vendor["id"] in selected_ids:
                continue
            selected.append(vendor)
            selected_ids.add(vendor["id"])
            if len(selected) >= limit:
                break

    return selected[:limit]


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text or "case"


def extract_pdf_text(pdf_base64: str) -> str:
    pdf_bytes = base64.b64decode(pdf_base64)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "".join(page.extract_text() or "" for page in reader.pages)


def list_live_scored_cases(host: str, container: str) -> list[dict[str, Any]]:
    remote_script = r"""
import json
import db

vendors = db.list_vendors_with_scores(limit=500)
out = []
for vendor in vendors:
    score = vendor.get("latest_score") or db.get_latest_score(vendor["id"]) or {}
    tier = (
        score.get("calibrated", {}).get("calibrated_tier")
        or score.get("tier")
        or score.get("calibrated_tier")
        or "unknown"
    )
    out.append({
        "id": vendor["id"],
        "name": vendor.get("name"),
        "tier": tier,
        "country": vendor.get("country"),
        "updated_at": vendor.get("updated_at"),
    })
print(json.dumps(out))
"""
    remote_command = (
        f"docker exec -i -w /app/backend {shlex.quote(container)} "
        f"python3 -c {shlex.quote(remote_script)}"
    )
    proc = subprocess.run(["ssh", host, remote_command], text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "failed to list live scored cases")
    return json.loads(proc.stdout)


def warm_and_collect(host: str, container: str, case_ids: list[str], graph_depth: int,
                     user_id: str, warm_timeout: int) -> list[dict[str, Any]]:
    payload = json.dumps(
        {
            "case_ids": case_ids,
            "graph_depth": graph_depth,
            "user_id": user_id,
            "warm_timeout": warm_timeout,
        }
    )
    remote_script = r"""
import base64
import json
import sqlite3
import sys
import time
import db
from ai_analysis import compute_analysis_fingerprint, get_latest_analysis
from dossier import generate_dossier
from dossier_pdf import generate_pdf_dossier
from graph_ingest import get_vendor_graph_summary
from server import _prime_ai_analysis_for_case

request = json.loads(sys.stdin.read())
case_ids = request["case_ids"]
graph_depth = int(request["graph_depth"])
user_id = request["user_id"]
warm_timeout = int(request["warm_timeout"])


def latest_job_status(case_id: str, created_by: str, input_hash: str):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id, status, error, started_at, completed_at "
            "FROM ai_analysis_jobs "
            "WHERE case_id = ? AND created_by = ? AND input_hash = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (case_id, created_by, input_hash),
        ).fetchone()
    if not row:
        return None
    return dict(row)


warm_states = {}
for case_id in case_ids:
    warm = _prime_ai_analysis_for_case(case_id, user_id)
    if warm.get("status") not in {"pending", "running"}:
        warm_states[case_id] = warm
        continue

    deadline = time.time() + max(30, warm_timeout)
    final_state = dict(warm)
    while time.time() < deadline:
        vendor = db.get_vendor(case_id)
        score = db.get_latest_score(case_id)
        enrichment = db.get_latest_enrichment(case_id)
        input_hash = compute_analysis_fingerprint(vendor, score, enrichment) if vendor and score else ""
        cached = get_latest_analysis(case_id, user_id=user_id, input_hash=input_hash) if input_hash else None
        if cached:
            final_state = {
                "status": "ready",
                "analysis_id": cached.get("id"),
                "input_hash": input_hash,
            }
            break
        job = latest_job_status(case_id, user_id, input_hash) if input_hash else None
        if job and job.get("status") == "failed":
            final_state = {
                "status": "failed",
                "error": job.get("error"),
                "input_hash": input_hash,
            }
            break
        time.sleep(2)
    else:
        final_state = {
            "status": "timeout",
            "error": f"warm-up did not complete within {warm_timeout}s",
        }

    warm_states[case_id] = final_state

results = []
for case_id in case_ids:
    vendor = db.get_vendor(case_id)
    if not vendor:
        results.append({"case_id": case_id, "error": "vendor not found"})
        continue

    score = db.get_latest_score(case_id) or {}
    enrichment = db.get_latest_enrichment(case_id)
    html = generate_dossier(case_id, user_id=user_id, hydrate_ai=False)
    pdf = generate_pdf_dossier(case_id, user_id=user_id, hydrate_ai=False)
    graph = get_vendor_graph_summary(case_id, depth=graph_depth)
    monitoring = db.get_monitoring_history(case_id, limit=1)
    fingerprint = compute_analysis_fingerprint(vendor, score, enrichment) if score else ""
    cached = get_latest_analysis(case_id, user_id=user_id, input_hash=fingerprint) if fingerprint else None

    latest_tier = (
        score.get("calibrated", {}).get("calibrated_tier")
        or score.get("tier")
        or score.get("calibrated_tier")
        or "unknown"
    )

    entity_ids = {entity.get("id") for entity in graph.get("entities", [])}
    results.append({
        "case_id": case_id,
        "vendor_name": vendor.get("name"),
        "country": vendor.get("country"),
        "tier": latest_tier,
        "warm_state": warm_states.get(case_id, {"status": "unknown"}),
        "html_markers": {k: (v in html) for k, v in {
            "executive_strip": "Recent change",
            "risk_storyline": "Risk Storyline",
            "ai_brief": "AI Narrative Brief",
            "executive_judgment": "Executive judgment",
        }.items()},
        "ai_ready": bool(cached),
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
                if rel.get("source_entity_id") not in entity_ids
                or rel.get("target_entity_id") not in entity_ids
            ),
            "corroborated_edges": sum(
                1 for rel in graph.get("relationships", []) if int(rel.get("corroboration_count") or 0) > 1
            ),
        },
        "html_base64": base64.b64encode(html.encode("utf-8")).decode("ascii"),
        "pdf_base64": base64.b64encode(pdf).decode("ascii"),
    })

print(json.dumps(results))
"""
    remote_command = (
        f"docker exec -i -w /app/backend {shlex.quote(container)} "
        f"python3 -c {shlex.quote(remote_script)}"
    )
    proc = subprocess.run(
        ["ssh", host, remote_command],
        input=payload,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "live dossier QA collect failed")
    return json.loads(proc.stdout)


def validate_result(case: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []

    if case.get("error"):
        failures.append(case["error"])
        return {**case, "failures": failures, "warnings": warnings, "pdf_markers": {}}

    html_markers = case["html_markers"]
    if not html_markers["executive_strip"]:
        failures.append("html dossier missing recent change strip")
    if not html_markers["risk_storyline"]:
        failures.append("html dossier missing risk storyline")
    if not html_markers["ai_brief"]:
        failures.append("html dossier missing AI brief")
    if not html_markers["executive_judgment"]:
        failures.append("html dossier missing executive judgment")

    pdf_text = extract_pdf_text(case["pdf_base64"]).upper()
    pdf_markers = {name: marker in pdf_text for name, marker in PDF_SECTION_CHECKS.items()}
    if not pdf_markers["executive_strip"]:
        failures.append("pdf dossier missing recent change strip")
    if not pdf_markers["risk_storyline"]:
        failures.append("pdf dossier missing risk storyline")
    if not pdf_markers["ai_brief"]:
        failures.append("pdf dossier missing AI brief")

    warm_state = case.get("warm_state") or {}
    if warm_state.get("status") not in {"ready", "completed"} and not case.get("ai_ready"):
        failures.append(f"ai warm-up not ready ({warm_state.get('status', 'unknown')})")

    if not case.get("monitoring_ready"):
        warnings.append("no monitoring history yet")

    graph = case["graph"]
    if graph.get("error"):
        failures.append(f"graph error: {graph['error']}")
    if graph.get("missing_endpoints"):
        failures.append(f"graph missing hydrated endpoints for {graph['missing_endpoints']} relationships")
    if not graph.get("root_entity_id"):
        warnings.append("graph root entity id missing")

    return {**case, "pdf_markers": pdf_markers, "failures": failures, "warnings": warnings}


def choose_packet_cases(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    passing = [result for result in results if not result.get("failures")]

    selections: list[dict[str, Any]] = []
    tier_preferences = [
        "TIER_4_CLEAR",
        "TIER_4_CRITICAL_QUALIFIED",
        "TIER_1_DISQUALIFIED",
    ]
    for tier in tier_preferences:
        for result in passing:
            if result.get("tier") == tier and result not in selections:
                selections.append(result)
                break
    return selections


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Helios Live Dossier QA Batch",
        "",
        f"Generated: {summary['generated_at']}",
        f"Host: {summary['host']}",
        f"User scope: {summary['user_id']}",
        f"Cohort size: {summary['cases_checked']}",
        f"Graph depth: {summary['graph_depth']}",
        "",
        "## Summary",
        "",
        f"- Cases checked: {summary['cases_checked']}",
        f"- Cases with failures: {summary['cases_with_failures']}",
        f"- Warning count: {summary['warning_count']}",
        f"- Selected pilot packet cases: {len(summary['packet_cases'])}",
        "",
        "## Cohort",
        "",
    ]

    for entry in summary["cohort"]:
        lines.append(f"- `{entry['tier']}` | `{entry['id']}` | {entry['name']}")

    lines.extend(["", "## Case Results", ""])
    for case in summary["cases"]:
        lines.extend(
            [
                f"### {case['vendor_name']} ({case['case_id']})",
                "",
                f"- Tier: {case['tier']}",
                f"- AI warm state: {case['warm_state'].get('status', 'unknown')}",
                f"- Monitoring history: {'present' if case['monitoring_ready'] else 'missing'}",
                f"- Graph: {case['graph']['entity_count']} entities, {case['graph']['relationship_count']} relationships, {case['graph']['corroborated_edges']} corroborated edges",
                f"- HTML markers: {', '.join(name for name, ok in case['html_markers'].items() if ok) or 'none'}",
                f"- PDF markers: {', '.join(name for name, ok in case['pdf_markers'].items() if ok) or 'none'}",
            ]
        )
        if case["failures"]:
            lines.append("- Failures:")
            for failure in case["failures"]:
                lines.append(f"  - {failure}")
        if case["warnings"]:
            lines.append("- Warnings:")
            for warning in case["warnings"]:
                lines.append(f"  - {warning}")
        lines.append("")

    if summary["packet_cases"]:
        lines.extend(["## 3-Case Pilot Packet", ""])
        for packet in summary["packet_cases"]:
            lines.append(f"- `{packet['tier']}` | {packet['vendor_name']} | {packet['packet_label']}")

    return "\n".join(lines).rstrip() + "\n"


def export_packet(packet_cases: list[dict[str, Any]], packet_dir: Path) -> list[dict[str, Any]]:
    packet_dir.mkdir(parents=True, exist_ok=True)
    exported: list[dict[str, Any]] = []

    for case in packet_cases:
        label = PACKET_LABELS.get(case["tier"], case["tier"])
        slug = slugify(case["vendor_name"])
        html_path = packet_dir / f"{label.lower().replace(' / ', '-').replace(' ', '-')}-{slug}.html"
        pdf_path = packet_dir / f"{label.lower().replace(' / ', '-').replace(' ', '-')}-{slug}.pdf"

        html_path.write_text(base64.b64decode(case["html_base64"]).decode("utf-8"), encoding="utf-8")
        pdf_path.write_bytes(base64.b64decode(case["pdf_base64"]))

        exported.append(
            {
                "case_id": case["case_id"],
                "vendor_name": case["vendor_name"],
                "tier": case["tier"],
                "packet_label": label,
                "html_path": str(html_path),
                "pdf_path": str(pdf_path),
            }
        )

    return exported


def render_packet_index(summary: dict[str, Any], exported: list[dict[str, Any]]) -> str:
    lines = [
        "# Helios 3-Case Sample Packet",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "This packet is the customer-facing leave-behind from the live dossier QA sweep. It contains three defense counterparty trust dossiers across the decision spectrum while the broader pilot package now covers three Helios workflows: defense counterparty trust, supplier cyber trust, and export authorization.",
        "",
        "## Included Cases",
        "",
    ]

    for item in exported:
        matching = next(case for case in summary["cases"] if case["case_id"] == item["case_id"])
        change = "present" if matching.get("monitoring_ready") else "not yet present"
        lines.extend(
            [
                f"### {item['packet_label']}: {item['vendor_name']}",
                "",
                f"- Case ID: `{item['case_id']}`",
                f"- Tier: `{item['tier']}`",
                f"- Country: `{matching.get('country') or 'unknown'}`",
                f"- Graph size: {matching['graph']['entity_count']} entities / {matching['graph']['relationship_count']} relationships",
                f"- Monitoring history: {change}",
                f"- HTML dossier: [{Path(item['html_path']).name}]({item['html_path']})",
                f"- PDF dossier: [{Path(item['pdf_path']).name}]({item['pdf_path']})",
                "",
            ]
        )

    lines.extend(
        [
            "## Why These Cases",
            "",
            "- `Defense counterparty trust` is the deepest current live lane, so these exported dossiers show the most mature end-to-end evidence, monitoring, graph, and dossier behavior.",
            "- `Clear` proves Helios can produce a premium affirmative decision, not just a risk escalation.",
            "- `Qualified / Watchlist` shows Helios handling nuance: approved posture plus ongoing visibility and change tracking.",
            "- `Blocked` proves hard-stop clarity and client-facing dossier discipline under adverse findings.",
            "- The same live product also supports supplier cyber trust and export authorization workflows; those lanes are represented in the pilot proposal and product flows even though this packet focuses on the counterparty lane.",
            "",
            "## Source Report",
            "",
            f"- QA report: [{Path(summary['report_md']).name}]({summary['report_md']})",
            f"- QA JSON: [{Path(summary['report_json']).name}]({summary['report_json']})",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()

    live_cases = list_live_scored_cases(args.host, args.container)
    cohort = build_default_cohort(live_cases, limit=args.limit)
    raw_results = warm_and_collect(
        args.host,
        args.container,
        [entry["id"] for entry in cohort],
        args.graph_depth,
        args.user_id,
        args.warm_timeout,
    )
    results = [validate_result(result) for result in raw_results]
    packet_cases = choose_packet_cases(results)

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    cohort_json_path = report_dir / f"helios-dossier-qa-cohort-{stamp}.json"
    cohort_md_path = report_dir / f"HELIOS_DOSSIER_QA_COHORT_{stamp}.md"
    report_json_path = report_dir / f"helios-live-dossier-qa-report-{stamp}.json"
    report_md_path = report_dir / f"helios-live-dossier-qa-report-{stamp}.md"

    cohort_json_path.write_text(json.dumps(cohort, indent=2), encoding="utf-8")
    cohort_md_path.write_text(
        "# Helios Dossier QA Cohort\n\n" + "\n".join(
            f"- `{entry['tier']}` | `{entry['id']}` | {entry['name']}" for entry in cohort
        ) + "\n",
        encoding="utf-8",
    )

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "host": args.host,
        "user_id": args.user_id,
        "graph_depth": args.graph_depth,
        "cases_checked": len(results),
        "cases_with_failures": sum(1 for result in results if result["failures"]),
        "warning_count": sum(len(result["warnings"]) for result in results),
        "cohort": cohort,
        "cases": [
            {
                key: value
                for key, value in result.items()
                if key not in {"html_base64", "pdf_base64"}
            }
            for result in results
        ],
        "packet_cases": [],
        "cohort_json": str(cohort_json_path),
        "cohort_md": str(cohort_md_path),
        "report_json": str(report_json_path),
        "report_md": str(report_md_path),
    }

    packet_dir = Path(args.packet_dir)
    exported = export_packet(packet_cases, packet_dir)
    summary["packet_cases"] = exported

    report_json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report_md_path.write_text(render_markdown(summary), encoding="utf-8")

    packet_index_path = packet_dir / "HELIOS_3_CASE_SAMPLE_PACKET_2026-03-23.md"
    packet_index_path.write_text(render_packet_index(summary, exported), encoding="utf-8")

    print(f"Wrote {cohort_md_path}")
    print(f"Wrote {cohort_json_path}")
    print(f"Wrote {report_md_path}")
    print(f"Wrote {report_json_path}")
    print(f"Wrote {packet_index_path}")
    for item in exported:
        print(f"Exported {item['vendor_name']} -> {item['html_path']} and {item['pdf_path']}")

    if args.print_json:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
