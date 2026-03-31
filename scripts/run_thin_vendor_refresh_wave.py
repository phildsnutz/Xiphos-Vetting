#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from monitor_scheduler import MonitorScheduler  # type: ignore  # noqa: E402
from scripts import run_provider_graph_vendor_coverage_audit as audit  # type: ignore  # noqa: E402
from scripts import trigger_thin_vendor_refresh as selector  # type: ignore  # noqa: E402


DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "thin_vendor_refresh_wave"


def utc_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a measured thin-vendor refresh wave with before/after KPIs.")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--scan-limit", type=int, default=10000)
    parser.add_argument("--max-root-entities", type=int, default=1)
    parser.add_argument("--max-relationships", type=int, default=2)
    parser.add_argument("--require-zero-control", action="store_true", default=True)
    parser.add_argument("--allow-nonzero-control", dest="require_zero_control", action="store_false")
    parser.add_argument("--exclude-name-token", action="append", default=list(selector._DEFAULT_EXCLUDED_NAME_TOKENS))
    parser.add_argument("--allow-duplicate-names", action="store_true")
    parser.add_argument("--vendor-id", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _selection_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    explicit_vendor_ids = [str(item).strip() for item in (args.vendor_id or []) if str(item).strip()]
    if explicit_vendor_ids:
        rows = audit.audit_vendor_rows(limit=max(len(explicit_vendor_ids), 1), depth=args.depth, vendor_ids=explicit_vendor_ids)
        return rows[: max(int(args.limit or 0), 1)]
    selection_args = argparse.Namespace(
        limit=int(args.limit),
        depth=int(args.depth),
        scan_limit=int(args.scan_limit),
        max_root_entities=int(args.max_root_entities),
        max_relationships=int(args.max_relationships),
        require_zero_control=bool(args.require_zero_control),
        exclude_name_token=list(args.exclude_name_token or []),
        allow_duplicate_names=bool(args.allow_duplicate_names),
    )
    return selector._select_thin_vendor_rows(selection_args)


def _rows_by_vendor(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("vendor_id") or ""): row for row in rows if str(row.get("vendor_id") or "")}


def _delta(before: int, after: int) -> int:
    return int(after) - int(before)


def _positive_delta(before: int, after: int) -> int:
    return max(_delta(before, after), 0)


def _build_wave_report(
    selected_rows: list[dict[str, Any]],
    before: dict[str, Any],
    after: dict[str, Any],
    run_summary: dict[str, Any] | None,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    vendor_ids = [str(row.get("vendor_id") or "") for row in selected_rows if str(row.get("vendor_id") or "")]
    before_rows = _rows_by_vendor(before.get("rows", []))
    after_rows = _rows_by_vendor(after.get("rows", []))

    improved_vendors: list[dict[str, Any]] = []
    for vendor_id in vendor_ids:
        before_row = before_rows.get(vendor_id, {})
        after_row = after_rows.get(vendor_id, {})
        deltas = {
            "relationship_delta": _delta(before_row.get("relationship_count") or 0, after_row.get("relationship_count") or 0),
            "control_path_delta": _delta(before_row.get("control_path_count") or 0, after_row.get("control_path_count") or 0),
            "ownership_edge_delta": _delta(before_row.get("ownership_edge_count") or 0, after_row.get("ownership_edge_count") or 0),
            "financing_edge_delta": _delta(before_row.get("financing_edge_count") or 0, after_row.get("financing_edge_count") or 0),
            "intermediary_edge_delta": _delta(before_row.get("intermediary_edge_count") or 0, after_row.get("intermediary_edge_count") or 0),
        }
        if not any(deltas.values()):
            continue
        improved_vendors.append(
            {
                "vendor_id": vendor_id,
                "vendor_name": str(after_row.get("vendor_name") or before_row.get("vendor_name") or ""),
                **deltas,
            }
        )

    before_cov = before.get("coverage_metrics", {})
    after_cov = after.get("coverage_metrics", {})
    before_families = before.get("family_edge_totals", {})
    after_families = after.get("family_edge_totals", {})

    zero_control_drop = int(before_cov.get("zero_control_vendor_count") or 0) - int(after_cov.get("zero_control_vendor_count") or 0)
    zero_relationship_drop = int(before_cov.get("zero_relationship_vendor_count") or 0) - int(after_cov.get("zero_relationship_vendor_count") or 0)
    new_ownership_edges = _positive_delta(before_families.get("ownership_edge_total") or 0, after_families.get("ownership_edge_total") or 0)
    new_financing_edges = _positive_delta(before_families.get("financing_edge_total") or 0, after_families.get("financing_edge_total") or 0)
    new_intermediary_edges = _positive_delta(before_families.get("intermediary_edge_total") or 0, after_families.get("intermediary_edge_total") or 0)
    relationship_gain = _positive_delta(
        sum(int(row.get("relationship_count") or 0) for row in before.get("rows", [])),
        sum(int(row.get("relationship_count") or 0) for row in after.get("rows", [])),
    )
    family_gain = new_ownership_edges + new_financing_edges + new_intermediary_edges
    control_gain_vendors = sum(1 for row in improved_vendors if int(row.get("control_path_delta") or 0) > 0)

    if zero_control_drop > 0 or family_gain > 0 or control_gain_vendors > 0:
        gate_status = "PASS"
        gate_reason = "Control-path lift detected."
    elif relationship_gain > 0:
        gate_status = "REL_ONLY"
        gate_reason = "Raw relationship lift without control-path family lift."
    else:
        gate_status = "NO_LIFT"
        gate_reason = "No meaningful graph lift detected."

    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "dry_run": bool(dry_run),
        "selected_vendor_count": len(vendor_ids),
        "selected_rows": selected_rows,
        "before": before,
        "after": after,
        "wave_summary": run_summary or {},
        "kpi_gate": {
            "status": gate_status,
            "reason": gate_reason,
            "zero_control_drop": zero_control_drop,
            "zero_relationship_drop": zero_relationship_drop,
            "new_ownership_edges": new_ownership_edges,
            "new_financing_edges": new_financing_edges,
            "new_intermediary_edges": new_intermediary_edges,
            "relationship_gain_total": relationship_gain,
            "control_path_gain_vendor_count": control_gain_vendors,
            "improved_vendor_count": len(improved_vendors),
        },
        "improved_vendors": improved_vendors,
    }


def render_markdown(report: dict[str, Any]) -> str:
    gate = report["kpi_gate"]
    before_cov = report["before"].get("coverage_metrics", {})
    after_cov = report["after"].get("coverage_metrics", {})
    lines = [
        "# Thin Vendor Refresh Wave",
        "",
        f"Generated: {report['generated_at']}",
        f"Selected vendors: `{report['selected_vendor_count']}`",
        f"KPI gate: `{gate['status']}`",
        "",
        "## KPI Gate",
        "",
        f"- Reason: {gate['reason']}",
        f"- Zero-control drop: `{gate['zero_control_drop']}`",
        f"- Zero-relationship drop: `{gate['zero_relationship_drop']}`",
        f"- New ownership edges: `{gate['new_ownership_edges']}`",
        f"- New financing edges: `{gate['new_financing_edges']}`",
        f"- New intermediary edges: `{gate['new_intermediary_edges']}`",
        f"- Relationship gain total: `{gate['relationship_gain_total']}`",
        f"- Vendors with control-path gain: `{gate['control_path_gain_vendor_count']}`",
        "",
        "## Coverage",
        "",
        f"- Before zero-control vendors: `{before_cov.get('zero_control_vendor_count', 0)}`",
        f"- After zero-control vendors: `{after_cov.get('zero_control_vendor_count', 0)}`",
        f"- Before zero-relationship vendors: `{before_cov.get('zero_relationship_vendor_count', 0)}`",
        f"- After zero-relationship vendors: `{after_cov.get('zero_relationship_vendor_count', 0)}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    selected_rows = _selection_rows(args)
    vendor_ids = [str(row.get("vendor_id") or "") for row in selected_rows if str(row.get("vendor_id") or "")]
    before_rows = audit.audit_vendor_rows(limit=max(len(vendor_ids), 1), depth=args.depth, vendor_ids=vendor_ids)
    before = audit.build_summary(before_rows, depth=args.depth, include_rows=True)

    run_summary: dict[str, Any] | None = None
    if not args.dry_run and vendor_ids:
        run_summary = MonitorScheduler().run_sweep(vendor_ids=vendor_ids)

    after_rows = audit.audit_vendor_rows(limit=max(len(vendor_ids), 1), depth=args.depth, vendor_ids=vendor_ids)
    after = audit.build_summary(after_rows, depth=args.depth, include_rows=True)

    report = _build_wave_report(selected_rows, before, after, run_summary, dry_run=args.dry_run)

    slug = utc_slug()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    report_json = args.report_dir / f"thin-vendor-refresh-wave-{slug}.json"
    report_md = args.report_dir / f"thin-vendor-refresh-wave-{slug}.md"
    report["report_json"] = str(report_json)
    report["report_markdown"] = str(report_md)
    report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report_md.write_text(render_markdown(report), encoding="utf-8")

    if args.print_json:
        print(json.dumps(report, indent=2))
    else:
        print(str(report_json))
        print(str(report_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
