#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "graph_vendor_coverage_audit"
DEFAULT_DB_CANDIDATES = (
    ROOT / "var" / "knowledge_graph.live.snapshot.db",
    ROOT / "var" / "knowledge_graph.db",
)
CONTROL_PATH_RELATION_TYPES = (
    "owned_by",
    "beneficially_owned_by",
    "backed_by",
    "routes_payment_through",
    "depends_on_service",
    "depends_on_network",
    "distributed_by",
    "operates_facility",
    "ships_via",
)


def utc_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def choose_default_db() -> Path:
    for candidate in DEFAULT_DB_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_DB_CANDIDATES[-1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit vendor-level graph coverage and control-path depth.")
    parser.add_argument("--db-path", type=Path, default=choose_default_db())
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
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


def _bucket_report(rows: list[sqlite3.Row], bucket_fn) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter[bucket_fn(int(row["count"] or 0))] += 1
    ordered: dict[str, int] = {}
    for key in ("0", "1", "2", "3-5", "6-10", "11+"):
        if key in counter:
            ordered[key] = int(counter[key])
    return ordered


def run_audit(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        raise SystemExit(f"knowledge graph database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    control_placeholders = ",".join("?" for _ in CONTROL_PATH_RELATION_TYPES)
    try:
        global_counts = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM kg_entities) AS entity_count,
                (SELECT COUNT(*) FROM kg_relationships) AS relationship_count,
                (SELECT COUNT(*) FROM kg_claims) AS claim_count,
                (SELECT COUNT(*) FROM kg_evidence) AS evidence_count,
                (SELECT COUNT(*) FROM kg_entity_vendors) AS vendor_link_count,
                (SELECT COUNT(DISTINCT vendor_id) FROM kg_entity_vendors) AS vendor_count
            """
        ).fetchone()

        mapped_entities = conn.execute(
            """
            SELECT vendor_id, COUNT(DISTINCT entity_id) AS count
            FROM kg_entity_vendors
            GROUP BY vendor_id
            ORDER BY count DESC, vendor_id ASC
            """
        ).fetchall()
        root_relationships = conn.execute(
            """
            SELECT v.vendor_id, COUNT(DISTINCT r.id) AS count
            FROM kg_entity_vendors v
            LEFT JOIN kg_relationships r
              ON r.source_entity_id = v.entity_id
            GROUP BY v.vendor_id
            ORDER BY count DESC, v.vendor_id ASC
            """
        ).fetchall()
        control_paths = conn.execute(
            f"""
            SELECT v.vendor_id, COUNT(DISTINCT r.id) AS count
            FROM kg_entity_vendors v
            LEFT JOIN kg_relationships r
              ON r.source_entity_id = v.entity_id
             AND r.rel_type IN ({control_placeholders})
            GROUP BY v.vendor_id
            ORDER BY count DESC, v.vendor_id ASC
            """,
            CONTROL_PATH_RELATION_TYPES,
        ).fetchall()
        relationship_type_rows = conn.execute(
            """
            SELECT rel_type, COUNT(*) AS count
            FROM kg_relationships
            GROUP BY rel_type
            ORDER BY count DESC, rel_type ASC
            """
        ).fetchall()
        entity_type_rows = conn.execute(
            """
            SELECT entity_type, COUNT(*) AS count
            FROM kg_entities
            GROUP BY entity_type
            ORDER BY count DESC, entity_type ASC
            """
        ).fetchall()
    finally:
        conn.close()

    vendor_count = int(global_counts["vendor_count"] or 0)
    mapped_entity_buckets = _bucket_report(mapped_entities, _bucket_mapped_entities)
    root_relationship_buckets = _bucket_report(root_relationships, _bucket_count)
    control_path_buckets = _bucket_report(control_paths, _bucket_count)

    zero_mapped = mapped_entity_buckets.get("0", 0)
    single_mapped = mapped_entity_buckets.get("1", 0)
    zero_relationship = root_relationship_buckets.get("0", 0)
    zero_control = control_path_buckets.get("0", 0)
    relationship_type_distribution = {
        str(row["rel_type"]): int(row["count"] or 0)
        for row in relationship_type_rows
    }
    entity_type_distribution = {
        str(row["entity_type"]): int(row["count"] or 0)
        for row in entity_type_rows
    }
    average_mapped_entities = round(
        sum(int(row["count"] or 0) for row in mapped_entities) / vendor_count,
        4,
    ) if vendor_count else 0.0

    top_dense_vendor_rows = root_relationships[:10]
    sample_dense_vendor_ids = [str(row["vendor_id"]) for row in top_dense_vendor_rows]
    sample_zero_control_vendor_ids = [
        str(row["vendor_id"])
        for row in control_paths
        if int(row["count"] or 0) == 0
    ][:10]

    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "db_path": str(db_path),
        "global_counts": {
            "entity_count": int(global_counts["entity_count"] or 0),
            "relationship_count": int(global_counts["relationship_count"] or 0),
            "claim_count": int(global_counts["claim_count"] or 0),
            "evidence_count": int(global_counts["evidence_count"] or 0),
            "vendor_link_count": int(global_counts["vendor_link_count"] or 0),
            "vendor_count": vendor_count,
        },
        "relationship_type_distribution": relationship_type_distribution,
        "entity_type_distribution": entity_type_distribution,
        "mapped_entity_buckets": mapped_entity_buckets,
        "root_relationship_buckets_proxy": root_relationship_buckets,
        "control_path_buckets_proxy": control_path_buckets,
        "coverage_metrics": {
            "average_mapped_entities_per_vendor": average_mapped_entities,
            "single_entity_vendor_count": single_mapped,
            "single_entity_vendor_pct": _pct(single_mapped, vendor_count),
            "zero_relationship_vendor_count_proxy": zero_relationship,
            "zero_relationship_vendor_pct_proxy": _pct(zero_relationship, vendor_count),
            "zero_control_vendor_count_proxy": zero_control,
            "zero_control_vendor_pct_proxy": _pct(zero_control, vendor_count),
            "vendors_with_any_relationship_proxy": vendor_count - zero_relationship,
            "vendors_with_any_control_path_proxy": vendor_count - zero_control,
        },
        "control_path_relation_types": list(CONTROL_PATH_RELATION_TYPES),
        "samples": {
            "sample_dense_vendor_ids": sample_dense_vendor_ids,
            "sample_zero_control_vendor_ids": sample_zero_control_vendor_ids,
        },
        "diagnosis": {
            "headline": "The live KG is globally large but vendor-scoped control graphs are thin.",
            "locality_gap": (
                "Most vendors map to one entity and never grow a meaningful ownership, financing, bank-route, "
                "or service-intermediary neighborhood."
            ),
            "proxy_note": (
                "Relationship and control-path buckets are a root-entity proxy from vendor-linked source entities. "
                "The dossier path is stricter because it filters down to vendor-scoped claims, so real case-level "
                "thinness is usually worse than this report."
            ),
            "priority_gap": (
                "The missing edge families are still ownership/control and intermediary evidence, not generic "
                "company discovery."
            ),
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    global_counts = summary["global_counts"]
    coverage = summary["coverage_metrics"]
    lines = [
        "# Helios Vendor Graph Coverage Audit",
        "",
        f"Generated: {summary['generated_at']}",
        f"Database: `{summary['db_path']}`",
        "",
        "## Verdict",
        "",
        "- The live knowledge graph is not globally thin.",
        "- The vendor-scoped control graph is thin.",
        "- The gap is ownership, financing, bank-route, and intermediary coverage per vendor.",
        "",
        "## Global Counts",
        "",
        f"- Entities: `{global_counts['entity_count']}`",
        f"- Relationships: `{global_counts['relationship_count']}`",
        f"- Claims: `{global_counts['claim_count']}`",
        f"- Evidence records: `{global_counts['evidence_count']}`",
        f"- Vendor links: `{global_counts['vendor_link_count']}`",
        f"- Distinct vendor IDs: `{global_counts['vendor_count']}`",
        "",
        "## Vendor Coverage",
        "",
        f"- Average mapped entities per vendor: `{coverage['average_mapped_entities_per_vendor']}`",
        f"- Vendors with exactly 1 mapped entity: `{coverage['single_entity_vendor_count']}` (`{coverage['single_entity_vendor_pct']:.1%}`)",
        f"- Vendors with 0 root-entity relationships (proxy): `{coverage['zero_relationship_vendor_count_proxy']}` (`{coverage['zero_relationship_vendor_pct_proxy']:.1%}`)",
        f"- Vendors with 0 control-path edges (proxy): `{coverage['zero_control_vendor_count_proxy']}` (`{coverage['zero_control_vendor_pct_proxy']:.1%}`)",
        f"- Vendors with any control-path edge (proxy): `{coverage['vendors_with_any_control_path_proxy']}`",
        "",
        "## Buckets",
        "",
        f"- Mapped entities per vendor: `{summary['mapped_entity_buckets']}`",
        f"- Root relationships per vendor (proxy): `{summary['root_relationship_buckets_proxy']}`",
        f"- Control-path relationships per vendor (proxy): `{summary['control_path_buckets_proxy']}`",
        "",
        "## Relationship Mix",
        "",
        f"- Top relationship types: `{dict(list(summary['relationship_type_distribution'].items())[:12])}`",
        f"- Entity types: `{summary['entity_type_distribution']}`",
        "",
        "## Diagnosis",
        "",
        f"- {summary['diagnosis']['headline']}",
        f"- {summary['diagnosis']['locality_gap']}",
        f"- {summary['diagnosis']['proxy_note']}",
        f"- {summary['diagnosis']['priority_gap']}",
        "",
        "## Samples",
        "",
        f"- Dense vendor IDs: `{summary['samples']['sample_dense_vendor_ids']}`",
        f"- Zero-control vendor IDs: `{summary['samples']['sample_zero_control_vendor_ids']}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    summary = run_audit(args.db_path)
    slug = utc_slug()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.report_dir / f"graph-vendor-coverage-audit-{slug}.json"
    md_path = args.report_dir / f"graph-vendor-coverage-audit-{slug}.md"
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    payload = {
        **summary,
        "report_json": str(json_path),
        "report_markdown": str(md_path),
    }
    if args.print_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"JSON report: {json_path}")
        print(f"Markdown report: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
