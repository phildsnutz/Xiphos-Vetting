#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import db  # type: ignore  # noqa: E402
from graph_ingest import get_vendor_graph_summary  # type: ignore  # noqa: E402
from monitor_scheduler import MonitorScheduler  # type: ignore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Queue a monitoring sweep for thin vendors.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--scan-limit", type=int, default=10000)
    parser.add_argument("--max-root-entities", type=int, default=1)
    parser.add_argument("--max-relationships", type=int, default=2)
    parser.add_argument("--require-zero-control", action="store_true", default=True)
    parser.add_argument("--allow-nonzero-control", dest="require_zero_control", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _row_matches(row: dict[str, object], args: argparse.Namespace) -> bool:
    if int(row.get("mapped_root_entities") or 0) > int(args.max_root_entities):
        return False
    if int(row.get("relationship_count") or 0) > int(args.max_relationships):
        return False
    if args.require_zero_control and int(row.get("control_path_count") or 0) > 0:
        return False
    return True


def _select_thin_vendor_rows(args: argparse.Namespace) -> list[dict[str, object]]:
    vendors = db.list_vendors(limit=max(int(args.scan_limit or 0), 1))
    rows: list[dict[str, object]] = []
    for vendor in vendors:
        vendor_id = str(vendor.get("id") or "")
        if not vendor_id:
            continue
        summary = get_vendor_graph_summary(vendor_id, depth=args.depth, include_provenance=False)
        intelligence = summary.get("intelligence") or {}
        row = {
            "vendor_id": vendor_id,
            "vendor_name": str(vendor.get("name") or ""),
            "mapped_root_entities": len(summary.get("root_entity_ids") or []),
            "relationship_count": int(summary.get("relationship_count") or 0),
            "control_path_count": int(intelligence.get("control_path_count") or 0),
        }
        if not _row_matches(row, args):
            continue
        rows.append(row)
        if len(rows) >= int(args.limit):
            break
    return rows


def main() -> int:
    args = parse_args()
    rows = _select_thin_vendor_rows(args)
    vendor_ids = [str(row.get("vendor_id") or "") for row in rows if str(row.get("vendor_id") or "")]
    payload = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "vendor_ids": vendor_ids,
        "count": len(vendor_ids),
        "selected_rows": rows,
        "criteria": {
            "scan_limit": int(args.scan_limit),
            "max_root_entities": int(args.max_root_entities),
            "max_relationships": int(args.max_relationships),
            "require_zero_control": bool(args.require_zero_control),
            "depth": int(args.depth),
        },
    }
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0
    scheduler = MonitorScheduler()
    summary = scheduler.run_sweep(vendor_ids=vendor_ids)
    payload["run_summary"] = summary
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
