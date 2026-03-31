#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import db  # type: ignore  # noqa: E402
from graph_ingest import get_vendor_graph_summary  # type: ignore  # noqa: E402


DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "graph_vendor_coverage_audit"
OWNERSHIP_RELATION_TYPES = {"owned_by", "beneficially_owned_by"}
FINANCING_RELATION_TYPES = {"backed_by", "routes_payment_through"}
INTERMEDIARY_RELATION_TYPES = {"depends_on_service", "depends_on_network"}


def utc_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provider-neutral vendor graph coverage audit.")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--vendor-id", action="append", default=[])
    parser.add_argument("--include-rows", action="store_true")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _bucket_count(count: int) -> str:
    if count <= 2:
        return str(count)
    if count <= 5:
        return "3-5"
    if count <= 10:
        return "6-10"
    return "11+"


def _bucket_mapped_entities(count: int) -> str:
    if count <= 1:
        return str(count)
    if count == 2:
        return "2"
    if count <= 5:
        return "3-5"
    if count <= 10:
        return "6-10"
    return "11+"


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(part / whole, 4)


def _bucket_report(rows: list[dict[str, Any]], key: str, bucket_fn) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter[bucket_fn(int(row.get(key) or 0))] += 1
    ordered: dict[str, int] = {}
    for name in ("0", "1", "2", "3-5", "6-10", "11+"):
        if name in counter:
            ordered[name] = int(counter[name])
    return ordered


def _selected_vendors(limit: int, vendor_ids: list[str] | None = None) -> list[dict[str, Any]]:
    wanted = [str(item).strip() for item in (vendor_ids or []) if str(item).strip()]
    if wanted:
        rows: list[dict[str, Any]] = []
        for vendor_id in wanted:
            vendor = db.get_vendor(vendor_id)
            if vendor:
                rows.append(vendor)
        return rows
    return db.list_vendors(limit=max(int(limit or 0), 1))


def audit_vendor_rows(limit: int, depth: int, vendor_ids: list[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    vendors = _selected_vendors(limit, vendor_ids=vendor_ids)
    for vendor in vendors:
        vendor_id = str(vendor.get("id") or "")
        summary = get_vendor_graph_summary(vendor_id, depth=depth, include_provenance=False)
        intelligence = summary.get("intelligence") or {}
        relationship_type_distribution = summary.get("relationship_type_distribution") or {}
        rows.append(
            {
                "vendor_id": vendor_id,
                "vendor_name": str(vendor.get("name") or ""),
                "mapped_root_entities": len(summary.get("root_entity_ids") or []),
                "entity_count": int(summary.get("entity_count") or 0),
                "relationship_count": int(summary.get("relationship_count") or 0),
                "control_path_count": int(intelligence.get("control_path_count") or 0),
                "ownership_edge_count": sum(int(relationship_type_distribution.get(rel_type) or 0) for rel_type in OWNERSHIP_RELATION_TYPES),
                "financing_edge_count": sum(int(relationship_type_distribution.get(rel_type) or 0) for rel_type in FINANCING_RELATION_TYPES),
                "intermediary_edge_count": sum(
                    int(relationship_type_distribution.get(rel_type) or 0) for rel_type in INTERMEDIARY_RELATION_TYPES
                ),
                "thin_graph": bool(intelligence.get("thin_graph")),
                "thin_control_paths": bool(intelligence.get("thin_control_paths")),
            }
        )
    return rows


def build_summary(rows: list[dict[str, Any]], *, depth: int, include_rows: bool) -> dict[str, Any]:
    vendor_count = len(rows)
    mapped_entity_buckets = _bucket_report(rows, "mapped_root_entities", _bucket_mapped_entities)
    relationship_buckets = _bucket_report(rows, "relationship_count", _bucket_count)
    control_path_buckets = _bucket_report(rows, "control_path_count", _bucket_count)
    zero_relationship = relationship_buckets.get("0", 0)
    zero_control = control_path_buckets.get("0", 0)
    single_mapped = mapped_entity_buckets.get("1", 0)
    ownership_total = sum(int(row.get("ownership_edge_count") or 0) for row in rows)
    financing_total = sum(int(row.get("financing_edge_count") or 0) for row in rows)
    intermediary_total = sum(int(row.get("intermediary_edge_count") or 0) for row in rows)

    top_dense = sorted(rows, key=lambda row: (int(row.get("relationship_count") or 0), row.get("vendor_id") or ""), reverse=True)[:10]
    zero_control_rows = [row for row in rows if int(row.get("control_path_count") or 0) == 0][:10]

    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "graph_depth": depth,
        "global_counts": {
            "vendor_count": vendor_count,
        },
        "mapped_entity_buckets": mapped_entity_buckets,
        "relationship_buckets": relationship_buckets,
        "control_path_buckets": control_path_buckets,
        "coverage_metrics": {
            "average_mapped_entities_per_vendor": round(sum(int(row.get("mapped_root_entities") or 0) for row in rows) / vendor_count, 4) if vendor_count else 0.0,
            "single_entity_vendor_count": single_mapped,
            "single_entity_vendor_pct": _pct(single_mapped, vendor_count),
            "zero_relationship_vendor_count": zero_relationship,
            "zero_relationship_vendor_pct": _pct(zero_relationship, vendor_count),
            "zero_control_vendor_count": zero_control,
            "zero_control_vendor_pct": _pct(zero_control, vendor_count),
            "vendors_with_any_control_path": vendor_count - zero_control,
            "vendors_with_any_ownership_edge": sum(1 for row in rows if int(row.get("ownership_edge_count") or 0) > 0),
            "vendors_with_any_financing_edge": sum(1 for row in rows if int(row.get("financing_edge_count") or 0) > 0),
            "vendors_with_any_intermediary_edge": sum(1 for row in rows if int(row.get("intermediary_edge_count") or 0) > 0),
        },
        "family_edge_totals": {
            "ownership_edge_total": ownership_total,
            "financing_edge_total": financing_total,
            "intermediary_edge_total": intermediary_total,
        },
        "samples": {
            "sample_dense_vendor_ids": [str(row.get("vendor_id") or "") for row in top_dense],
            "sample_zero_control_vendor_ids": [str(row.get("vendor_id") or "") for row in zero_control_rows],
        },
        "diagnosis": {
            "headline": "Provider-neutral audit of vendor-scoped graph depth.",
            "note": "This audit runs through db.list_vendors plus graph_ingest.get_vendor_graph_summary, so it reflects the product-visible graph surface rather than a raw SQLite snapshot.",
        },
    }
    if include_rows:
        summary["rows"] = rows
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    coverage = summary["coverage_metrics"]
    lines = [
        "# Provider-Neutral Vendor Graph Coverage Audit",
        "",
        f"Generated: {summary['generated_at']}",
        f"Graph depth: `{summary['graph_depth']}`",
        "",
        "## Verdict",
        "",
        "- This audit reflects the product-visible graph surface.",
        "- It runs through the provider-neutral graph summary path.",
        "- Thinness here is the real operator problem, not just snapshot storage drift.",
        "",
        "## Coverage",
        "",
        f"- Vendors audited: `{summary['global_counts']['vendor_count']}`",
        f"- Single-root vendors: `{coverage['single_entity_vendor_count']}` (`{coverage['single_entity_vendor_pct'] * 100:.1f}%`)",
        f"- Zero-relationship vendors: `{coverage['zero_relationship_vendor_count']}` (`{coverage['zero_relationship_vendor_pct'] * 100:.1f}%`)",
        f"- Zero-control vendors: `{coverage['zero_control_vendor_count']}` (`{coverage['zero_control_vendor_pct'] * 100:.1f}%`)",
        f"- Vendors with any control path: `{coverage['vendors_with_any_control_path']}`",
        f"- Vendors with ownership edges: `{coverage['vendors_with_any_ownership_edge']}`",
        f"- Vendors with financing edges: `{coverage['vendors_with_any_financing_edge']}`",
        f"- Vendors with intermediary edges: `{coverage['vendors_with_any_intermediary_edge']}`",
        "",
        "## Family Totals",
        "",
        f"- Ownership edges: `{summary['family_edge_totals']['ownership_edge_total']}`",
        f"- Financing edges: `{summary['family_edge_totals']['financing_edge_total']}`",
        f"- Intermediary edges: `{summary['family_edge_totals']['intermediary_edge_total']}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    rows = audit_vendor_rows(args.limit, args.depth, vendor_ids=args.vendor_id)
    summary = build_summary(rows, depth=args.depth, include_rows=args.include_rows)
    slug = utc_slug()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    report_json = args.report_dir / f"provider-graph-vendor-coverage-audit-{slug}.json"
    report_md = args.report_dir / f"provider-graph-vendor-coverage-audit-{slug}.md"
    summary["report_json"] = str(report_json)
    summary["report_markdown"] = str(report_md)
    report_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report_md.write_text(render_markdown(summary), encoding="utf-8")
    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(str(report_json))
        print(str(report_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
