#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


BENCHMARK_GROUPS: dict[str, list[str]] = {
    "tier1_zero_link": [
        "Hefring Marine",
        "HTL / Herrick Technology Laboratories Inc",
    ],
    "tier2_low_link": [
        "Greensea IQ",
        "Gulf Coast Underwriters",
        "Haley Strategic Partners LLC",
        "Hascall-Denke",
        "HELLENIC DEFENCE SYSTEMS SA",
        "Holosun Technologies Inc",
        "Holtec Security International",
    ],
    "tier3_high_yield": [
        "HII",
        "GM Defense",
        "IAI North America",
        "HPE",
        "Haivision",
        "Hoffman Engineering",
        "Globalstar",
        "goTenna",
    ],
}
GROUP_WEIGHTS = {
    "tier1_zero_link": 3,
    "tier2_low_link": 2,
    "tier3_high_yield": 1,
}

OWNERSHIP_REL_TYPES = {"owned_by", "beneficially_owned_by"}
INTERMEDIARY_REL_TYPES = {
    "backed_by",
    "routes_payment_through",
    "depends_on_network",
    "depends_on_service",
    "distributed_by",
    "operates_facility",
    "ships_via",
}
CONTROL_PATH_REL_TYPES = OWNERSHIP_REL_TYPES | INTERMEDIARY_REL_TYPES


def utc_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def login(base_url: str, email: str, password: str, token: str = "") -> dict[str, str]:
    if token:
        return {"Authorization": f"Bearer {token}"}
    response = requests.post(
        f"{base_url.rstrip('/')}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def fetch_json(base_url: str, path: str, headers: dict[str, str], timeout: int = 120) -> dict | list:
    response = requests.get(f"{base_url.rstrip('/')}{path}", headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def load_cases(base_url: str, headers: dict[str, str]) -> list[dict]:
    payload = fetch_json(base_url, "/api/cases?limit=5000", headers)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("cases", payload.get("vendors", []))
    return []


def normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def index_cases(cases: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for case in cases:
        key = normalize_name(str(case.get("vendor_name") or case.get("name") or ""))
        index.setdefault(key, []).append(case)
    for key in index:
        index[key].sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return index


def choose_case(case_index: dict[str, list[dict]], name: str) -> dict | None:
    matches = case_index.get(normalize_name(name)) or []
    return matches[0] if matches else None


def _control_path_metrics(passport: dict[str, Any]) -> dict[str, Any]:
    control_paths = (((passport.get("graph") or {}).get("control_paths")) or []) if isinstance(passport, dict) else []
    ownership_paths = [row for row in control_paths if str(row.get("rel_type") or "") in OWNERSHIP_REL_TYPES]
    intermediary_paths = [row for row in control_paths if str(row.get("rel_type") or "") in INTERMEDIARY_REL_TYPES]
    rel_counter = Counter(str(row.get("rel_type") or "unknown") for row in control_paths)
    return {
        "control_path_count": len(control_paths),
        "ownership_path_count": len(ownership_paths),
        "intermediary_path_count": len(intermediary_paths),
        "relationship_mix": dict(rel_counter),
        "has_control_path": bool(control_paths),
        "has_upstream_ownership": bool(ownership_paths),
        "has_intermediary_visibility": bool(intermediary_paths),
    }


def evaluate_passport(passport: dict[str, Any]) -> dict[str, Any]:
    graph = passport.get("graph") or {}
    identity = passport.get("identity") or {}
    ownership = passport.get("ownership") or {}
    foci_summary = ownership.get("foci_summary") if isinstance(ownership, dict) else {}
    control = ownership.get("workflow_control") if isinstance(ownership, dict) else {}
    metrics = _control_path_metrics(passport)

    jurisdiction_signal = str(
        (foci_summary or {}).get("foreign_country")
        or (passport.get("vendor") or {}).get("country")
        or ""
    ).upper()

    analyst_usefulness = 0
    if metrics["has_control_path"]:
        analyst_usefulness += 1
    if metrics["has_upstream_ownership"]:
        analyst_usefulness += 1
    if metrics["has_intermediary_visibility"]:
        analyst_usefulness += 1
    if int(graph.get("relationship_count") or 0) >= 3:
        analyst_usefulness += 1
    if control:
        analyst_usefulness += 1

    return {
        "posture": passport.get("posture"),
        "entity_count": int(graph.get("entity_count") or 0),
        "relationship_count": int(graph.get("relationship_count") or 0),
        "connectors_with_data": int(identity.get("connectors_with_data") or 0),
        "findings_total": int(identity.get("findings_total") or 0),
        "jurisdiction_signal": jurisdiction_signal,
        "workflow_control_label": (control or {}).get("label"),
        "workflow_control_owner": (control or {}).get("action_owner"),
        "control_path_metrics": metrics,
        "analyst_usefulness_score": analyst_usefulness,
    }


def _row_succeeds(row: dict[str, Any]) -> bool:
    if row.get("status") not in {"ok", "proxy_ok"}:
        return False
    evaluation = row.get("evaluation") or {}
    metrics = evaluation.get("control_path_metrics") or {}
    analyst = int(evaluation.get("analyst_usefulness_score") or 0)
    workflow_control = bool(evaluation.get("workflow_control_label"))
    group = str(row.get("group") or "")
    if group == "tier1_zero_link":
        return bool(metrics.get("has_control_path"))
    if group == "tier2_low_link":
        return analyst >= 3 and (
            bool(metrics.get("has_control_path"))
            or bool(metrics.get("has_upstream_ownership"))
            or bool(metrics.get("has_intermediary_visibility"))
            or workflow_control
        )
    if group == "tier3_high_yield":
        return analyst >= 4 and (
            bool(metrics.get("has_control_path"))
            or bool(metrics.get("has_upstream_ownership"))
            or workflow_control
        )
    return analyst >= 3


def summarize_groups(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for group, names in BENCHMARK_GROUPS.items():
        matching = [row for row in rows if row.get("group") == group]
        resolved = [row for row in matching if row.get("status") in {"ok", "proxy_ok"}]
        successes = [row for row in resolved if _row_succeeds(row)]
        summary[group] = {
            "cases_total": len(names),
            "cases_found": len(matching),
            "cases_resolved": len(resolved),
            "successes": len(successes),
            "success_rate_pct": round((len(successes) / len(names)) * 100, 1) if names else 0.0,
            "weight": GROUP_WEIGHTS.get(group, 1),
        }
    return summary


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    present = [row for row in rows if row.get("status") in {"ok", "proxy_ok"}]
    missing = [row for row in rows if row.get("status") == "missing_case"]
    passport_errors = [row for row in rows if row.get("status") in {"passport_error", "proxy_error"}]
    with_control = [row for row in present if row["evaluation"]["control_path_metrics"]["has_control_path"]]
    with_ownership = [row for row in present if row["evaluation"]["control_path_metrics"]["has_upstream_ownership"]]
    with_intermediary = [row for row in present if row["evaluation"]["control_path_metrics"]["has_intermediary_visibility"]]
    group_summary = summarize_groups(rows)
    weighted_total = sum(
        int(group["cases_total"]) * int(group["weight"]) for group in group_summary.values()
    )
    weighted_success = sum(
        int(group["successes"]) * int(group["weight"]) for group in group_summary.values()
    )
    route_missing = any(row.get("mode") == "proxy" for row in rows) or (
        bool(passport_errors)
        and len(passport_errors) == len(rows) - len(missing)
        and all("404" in str(row.get("detail") or "") for row in passport_errors)
    )
    return {
        "cases_evaluated": len(rows),
        "cases_resolved": len(present),
        "missing_cases": len(missing),
        "passport_errors": len(passport_errors),
        "proxy_cases": sum(1 for row in rows if row.get("status") == "proxy_ok"),
        "cases_with_control_paths": len(with_control),
        "cases_with_upstream_ownership": len(with_ownership),
        "cases_with_intermediary_visibility": len(with_intermediary),
        "benchmark_score_pct": round((weighted_success / weighted_total) * 100, 1) if weighted_total else 0.0,
        "group_summary": group_summary,
        "supplier_passport_route_available": not route_missing,
        "deployment_gap": "supplier_passport_route_missing" if route_missing else None,
    }


def _snapshot_evaluation(row: dict[str, Any]) -> dict[str, int]:
    evaluation = row.get("evaluation") or {}
    metrics = evaluation.get("control_path_metrics") or {}
    return {
        "relationship_count": int(evaluation.get("relationship_count") or 0),
        "control_path_count": int(metrics.get("control_path_count") or 0),
        "ownership_path_count": int(metrics.get("ownership_path_count") or 0),
        "intermediary_path_count": int(metrics.get("intermediary_path_count") or 0),
        "analyst_usefulness_score": int(evaluation.get("analyst_usefulness_score") or 0),
    }


def compare_to_baseline(rows: list[dict[str, Any]], baseline_rows: list[dict[str, Any]]) -> dict[str, Any]:
    current_index = {
        str(row.get("name") or ""): row
        for row in rows
        if row.get("status") in {"ok", "proxy_ok"} and row.get("name")
    }
    baseline_index = {
        str(row.get("name") or ""): row
        for row in baseline_rows
        if row.get("status") in {"ok", "proxy_ok"} and row.get("name")
    }
    improvements: list[dict[str, Any]] = []
    improved = 0
    regressed = 0
    unchanged = 0
    relationship_delta_total = 0
    control_path_delta_total = 0
    ownership_path_delta_total = 0
    intermediary_path_delta_total = 0
    usefulness_delta_total = 0

    for name in sorted(set(current_index) & set(baseline_index)):
        current = _snapshot_evaluation(current_index[name])
        baseline = _snapshot_evaluation(baseline_index[name])
        delta = {
            key: current[key] - baseline[key]
            for key in current
        }
        relationship_delta_total += delta["relationship_count"]
        control_path_delta_total += delta["control_path_count"]
        ownership_path_delta_total += delta["ownership_path_count"]
        intermediary_path_delta_total += delta["intermediary_path_count"]
        usefulness_delta_total += delta["analyst_usefulness_score"]
        delta_score = (
            delta["analyst_usefulness_score"] * 10
            + delta["control_path_count"] * 6
            + delta["ownership_path_count"] * 4
            + delta["intermediary_path_count"] * 4
            + delta["relationship_count"]
        )
        if delta_score > 0:
            improved += 1
        elif delta_score < 0:
            regressed += 1
        else:
            unchanged += 1
        improvements.append(
            {
                "name": name,
                "delta_score": delta_score,
                **delta,
            }
        )

    improvements.sort(
        key=lambda item: (
            -int(item["delta_score"]),
            -int(item["analyst_usefulness_score"]),
            -int(item["control_path_count"]),
            -int(item["relationship_count"]),
            str(item["name"]),
        )
    )
    return {
        "compared_cases": len(improvements),
        "improved_cases": improved,
        "regressed_cases": regressed,
        "unchanged_cases": unchanged,
        "relationship_delta_total": relationship_delta_total,
        "control_path_delta_total": control_path_delta_total,
        "ownership_path_delta_total": ownership_path_delta_total,
        "intermediary_path_delta_total": intermediary_path_delta_total,
        "usefulness_delta_total": usefulness_delta_total,
        "top_improvements": improvements[:5],
    }


def render_markdown(
    rows: list[dict[str, Any]],
    base_url: str,
    *,
    summary: dict[str, Any] | None = None,
    baseline_delta: dict[str, Any] | None = None,
) -> str:
    generated = datetime.now(timezone.utc).isoformat()
    summary = summary or build_summary(rows)
    lines = [
        "# Helios Ownership / Control Benchmark Report",
        "",
        f"Generated: {generated}",
        "",
        f"Base URL: `{base_url}`",
        "",
        "## Summary",
        "",
    ]

    lines.extend(
        [
            f"- Cases evaluated: `{summary['cases_evaluated']}`",
            f"- Cases resolved in environment: `{summary['cases_resolved']}`",
            f"- Missing cases: `{summary['missing_cases']}`",
            f"- Passport fetch errors: `{summary['passport_errors']}`",
            f"- Proxy-scored cases: `{summary['proxy_cases']}`",
            f"- Cases with control paths: `{summary['cases_with_control_paths']}`",
            f"- Cases with upstream ownership: `{summary['cases_with_upstream_ownership']}`",
            f"- Cases with intermediary visibility: `{summary['cases_with_intermediary_visibility']}`",
            f"- Weighted benchmark score: `{summary['benchmark_score_pct']}`%",
            "",
        ]
    )
    lines.extend(["## Group Scorecard", ""])
    for group, metrics in summary.get("group_summary", {}).items():
        lines.append(
            f"- `{group}`: `{metrics['successes']}` / `{metrics['cases_total']}` success, `{metrics['success_rate_pct']}`% at weight `{metrics['weight']}`"
        )
    lines.append("")
    if not summary["supplier_passport_route_available"]:
        lines.extend(
            [
                "> Deployment gap: `/api/cases/<id>/supplier-passport` is missing on this environment.",
                "> This benchmark cannot score ownership/control depth until the current build is deployed.",
                "",
            ]
        )
    if baseline_delta:
        lines.extend(
            [
                "## Baseline Delta",
                "",
                f"- Compared cases: `{baseline_delta['compared_cases']}`",
                f"- Improved cases: `{baseline_delta['improved_cases']}`",
                f"- Regressed cases: `{baseline_delta['regressed_cases']}`",
                f"- Unchanged cases: `{baseline_delta['unchanged_cases']}`",
                f"- Relationship delta total: `{baseline_delta['relationship_delta_total']}`",
                f"- Control-path delta total: `{baseline_delta['control_path_delta_total']}`",
                f"- Ownership-path delta total: `{baseline_delta['ownership_path_delta_total']}`",
                f"- Intermediary-path delta total: `{baseline_delta['intermediary_path_delta_total']}`",
                f"- Analyst usefulness delta total: `{baseline_delta['usefulness_delta_total']}`",
                "",
            ]
        )
        if baseline_delta.get("top_improvements"):
            lines.append("### Top Improvements")
            lines.append("")
            for item in baseline_delta["top_improvements"]:
                lines.append(
                    f"- `{item['name']}`: delta score `{item['delta_score']}`, usefulness `{item['analyst_usefulness_score']:+}`, control `{item['control_path_count']:+}`, ownership `{item['ownership_path_count']:+}`, intermediary `{item['intermediary_path_count']:+}`, relationships `{item['relationship_count']:+}`"
                )
            lines.append("")
    lines.extend(["## Results", ""])

    for row in rows:
        lines.append(f"### {row['name']}")
        lines.append("")
        if row.get("status") != "ok":
            if row.get("status") == "proxy_ok":
                evaluation = row["evaluation"]
                metrics = evaluation["control_path_metrics"]
                lines.append("- Status: `proxy_ok`")
                lines.append("- Source: fallback to case detail + enrichment + graph endpoints")
                lines.extend(
                    [
                        f"- Group: `{row['group']}`",
                        f"- Case ID: `{row['case_id']}`",
                        f"- Posture: `{evaluation['posture']}`",
                        f"- Graph: `{evaluation['entity_count']}` entities / `{evaluation['relationship_count']}` relationships",
                        f"- Connectors with data: `{evaluation['connectors_with_data']}`",
                        f"- Control paths: `{metrics['control_path_count']}`",
                        f"- Ownership paths: `{metrics['ownership_path_count']}`",
                        f"- Intermediary paths: `{metrics['intermediary_path_count']}`",
                        f"- Workflow control: `{evaluation.get('workflow_control_label') or 'None'}`",
                        f"- Analyst usefulness proxy: `{evaluation['analyst_usefulness_score']}` / `5`",
                    ]
                )
                lines.append("")
                continue
            lines.append(f"- Status: `{row['status']}`")
            if row.get("detail"):
                lines.append(f"- Detail: {row['detail']}")
            lines.append("")
            continue
        evaluation = row["evaluation"]
        metrics = evaluation["control_path_metrics"]
        lines.extend(
            [
                f"- Group: `{row['group']}`",
                f"- Case ID: `{row['case_id']}`",
                f"- Posture: `{evaluation['posture']}`",
                f"- Graph: `{evaluation['entity_count']}` entities / `{evaluation['relationship_count']}` relationships",
                f"- Connectors with data: `{evaluation['connectors_with_data']}`",
                f"- Control paths: `{metrics['control_path_count']}`",
                f"- Ownership paths: `{metrics['ownership_path_count']}`",
                f"- Intermediary paths: `{metrics['intermediary_path_count']}`",
                f"- Workflow control: `{evaluation.get('workflow_control_label') or 'None'}`",
                f"- Analyst usefulness proxy: `{evaluation['analyst_usefulness_score']}` / `5`",
            ]
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def _passport_posture_from_case_detail(detail: dict[str, Any]) -> str:
    score = detail.get("score") if isinstance(detail.get("score"), dict) else {}
    calibrated = score.get("calibrated") if isinstance(score.get("calibrated"), dict) else {}
    tier = str(calibrated.get("calibrated_tier") or "").upper()
    if any(token in tier for token in ("BLOCKED", "HARD_STOP", "DENIED", "DISQUALIFIED")):
        return "blocked"
    if any(token in tier for token in ("REVIEW", "ELEVATED", "CAUTION", "CONDITIONAL")):
        return "review"
    if any(token in tier for token in ("APPROVED", "QUALIFIED", "CLEAR", "ACCEPTABLE")):
        return "approved"
    return "pending"


def _control_paths_from_graph(graph: dict[str, Any]) -> list[dict[str, Any]]:
    relationships = graph.get("relationships") if isinstance(graph, dict) else []
    entities = graph.get("entities") if isinstance(graph, dict) else []
    entity_lookup = {
        str(entity.get("id")): entity
        for entity in entities
        if isinstance(entity, dict) and entity.get("id")
    }
    rows: list[dict[str, Any]] = []
    for rel in relationships or []:
        if not isinstance(rel, dict):
            continue
        rel_type = str(rel.get("rel_type") or "")
        if rel_type not in CONTROL_PATH_REL_TYPES:
            continue
        data_sources = rel.get("data_sources") or ([rel.get("data_source")] if rel.get("data_source") else [])
        source_id = str(rel.get("source_entity_id") or "")
        target_id = str(rel.get("target_entity_id") or "")
        rows.append(
            {
                "rel_type": rel_type,
                "source_entity_id": source_id,
                "source_name": (entity_lookup.get(source_id) or {}).get("canonical_name") or source_id,
                "target_entity_id": target_id,
                "target_name": (entity_lookup.get(target_id) or {}).get("canonical_name") or target_id,
                "confidence": float(rel.get("confidence") or 0.0),
                "corroboration_count": int(rel.get("corroboration_count") or len(data_sources) or 1),
                "data_sources": [str(item) for item in data_sources if item],
                "first_seen_at": rel.get("first_seen_at") or rel.get("created_at"),
                "last_seen_at": rel.get("last_seen_at") or rel.get("created_at"),
            }
        )
    rows.sort(key=lambda row: (-int(row["corroboration_count"]), -float(row["confidence"]), str(row["rel_type"])))
    return rows[:5]


def build_proxy_passport(
    detail: dict[str, Any],
    enrichment: dict[str, Any] | None,
    graph: dict[str, Any] | None,
    network_risk: dict[str, Any] | None,
) -> dict[str, Any]:
    enrichment = enrichment if isinstance(enrichment, dict) else {}
    graph = graph if isinstance(graph, dict) else {}
    summary = enrichment.get("summary") if isinstance(enrichment.get("summary"), dict) else {}
    score = detail.get("score") if isinstance(detail.get("score"), dict) else {}
    calibrated = score.get("calibrated") if isinstance(score.get("calibrated"), dict) else {}
    return {
        "posture": _passport_posture_from_case_detail(detail),
        "vendor": {
            "id": detail.get("id"),
            "name": detail.get("vendor_name") or detail.get("name"),
            "country": detail.get("country"),
            "profile": detail.get("profile"),
            "program": detail.get("program"),
        },
        "score": {
            "composite_score": score.get("composite_score"),
            "calibrated_probability": calibrated.get("calibrated_probability"),
            "calibrated_tier": calibrated.get("calibrated_tier"),
        },
        "identity": {
            "identifiers": enrichment.get("identifiers") if isinstance(enrichment.get("identifiers"), dict) else {},
            "connectors_with_data": int(summary.get("connectors_with_data") or 0),
            "findings_total": int(summary.get("findings_total") or 0),
            "overall_risk": enrichment.get("overall_risk"),
            "enriched_at": enrichment.get("enriched_at"),
        },
        "ownership": {
            "workflow_control": detail.get("workflow_control_summary") if isinstance(detail.get("workflow_control_summary"), dict) else {},
            "foci_summary": detail.get("foci_evidence_summary") if isinstance(detail.get("foci_evidence_summary"), dict) else {},
        },
        "graph": {
            "entity_count": int(graph.get("entity_count") or len(graph.get("entities") or [])),
            "relationship_count": int(graph.get("relationship_count") or len(graph.get("relationships") or [])),
            "control_paths": _control_paths_from_graph(graph),
        },
        "network_risk": network_risk if isinstance(network_risk, dict) else None,
    }


def run_benchmark(base_url: str, email: str, password: str, token: str = "") -> dict[str, Any]:
    headers = login(base_url, email, password, token=token)
    cases = load_cases(base_url, headers)
    case_index = index_cases(cases)
    rows: list[dict[str, Any]] = []
    for group, names in BENCHMARK_GROUPS.items():
        for name in names:
            case = choose_case(case_index, name)
            if not case:
                rows.append({"group": group, "name": name, "status": "missing_case", "detail": "No matching case found"})
                continue
            case_id = str(case.get("id") or "")
            try:
                passport = fetch_json(base_url, f"/api/cases/{case_id}/supplier-passport", headers)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    try:
                        detail = fetch_json(base_url, f"/api/cases/{case_id}", headers, timeout=30)
                        enrichment = fetch_json(base_url, f"/api/cases/{case_id}/enrichment", headers, timeout=30)
                        graph = fetch_json(base_url, f"/api/cases/{case_id}/graph?depth=3", headers, timeout=30)
                        try:
                            network_risk = fetch_json(base_url, f"/api/cases/{case_id}/network-risk", headers, timeout=15)
                        except Exception:
                            network_risk = None
                        proxy_passport = build_proxy_passport(
                            detail if isinstance(detail, dict) else {},
                            enrichment if isinstance(enrichment, dict) else {},
                            graph if isinstance(graph, dict) else {},
                            network_risk if isinstance(network_risk, dict) else {},
                        )
                        rows.append(
                            {
                                "group": group,
                                "name": name,
                                "case_id": case_id,
                                "status": "proxy_ok",
                                "mode": "proxy",
                                "detail": "supplier-passport route missing; used case detail + enrichment + graph fallback",
                                "evaluation": evaluate_passport(proxy_passport),
                            }
                        )
                        continue
                    except Exception as fallback_exc:
                        rows.append(
                            {
                                "group": group,
                                "name": name,
                                "case_id": case_id,
                                "status": "proxy_error",
                                "mode": "proxy",
                                "detail": f"{exc}; fallback failed: {fallback_exc}",
                            }
                        )
                        continue
                rows.append({"group": group, "name": name, "case_id": case_id, "status": "passport_error", "detail": str(exc)})
                continue
            rows.append(
                {
                    "group": group,
                    "name": name,
                    "case_id": case_id,
                    "status": "ok",
                    "mode": "supplier_passport",
                    "evaluation": evaluate_passport(passport if isinstance(passport, dict) else {}),
                }
            )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "summary": build_summary(rows),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ownership/control benchmark packet against a Helios environment")
    parser.add_argument("--base-url", default=os.environ.get("HELIOS_BASE_URL") or "http://127.0.0.1:8080")
    parser.add_argument("--token", default=os.environ.get("HELIOS_TOKEN", ""))
    parser.add_argument("--email", default=os.environ.get("HELIOS_LOGIN_EMAIL") or os.environ.get("HELIOS_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("HELIOS_LOGIN_PASSWORD") or os.environ.get("HELIOS_PASSWORD"))
    parser.add_argument("--baseline-json", type=Path)
    parser.add_argument("--output-json", type=Path, default=Path("docs/reports") / f"helios-ownership-control-benchmark-{utc_slug()}.json")
    parser.add_argument("--output-md", type=Path, default=Path("docs/reports") / f"HELIOS_OWNERSHIP_CONTROL_BENCHMARK_{utc_slug()}.md")
    args = parser.parse_args()

    if not args.token and (not args.email or not args.password):
        raise SystemExit("Set HELIOS_TOKEN or HELIOS_EMAIL/HELIOS_PASSWORD, or pass --token / --email / --password")

    report = run_benchmark(args.base_url, args.email, args.password, token=args.token)
    baseline_delta = None
    if args.baseline_json:
        baseline_payload = json.loads(args.baseline_json.read_text(encoding="utf-8"))
        baseline_rows = baseline_payload.get("rows", []) if isinstance(baseline_payload, dict) else baseline_payload
        baseline_delta = compare_to_baseline(report["rows"], baseline_rows if isinstance(baseline_rows, list) else [])
        report["baseline_delta"] = baseline_delta
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2))
    args.output_md.write_text(
        render_markdown(
            report["rows"],
            args.base_url,
            summary=report["summary"],
            baseline_delta=baseline_delta,
        )
    )
    print(args.output_json)
    print(args.output_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
