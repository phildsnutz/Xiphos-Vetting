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

from monitor_scheduler import MonitorScheduler  # type: ignore  # noqa: E402
from scripts.run_provider_graph_vendor_coverage_audit import audit_vendor_rows  # type: ignore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Queue a monitoring sweep for thin vendors.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--max-root-entities", type=int, default=1)
    parser.add_argument("--max-relationships", type=int, default=2)
    parser.add_argument("--require-zero-control", action="store_true", default=True)
    parser.add_argument("--allow-nonzero-control", dest="require_zero_control", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _select_thin_vendor_ids(args: argparse.Namespace) -> list[str]:
    rows = audit_vendor_rows(limit=10000, depth=args.depth)
    selected: list[str] = []
    for row in rows:
        if int(row.get("mapped_root_entities") or 0) > int(args.max_root_entities):
            continue
        if int(row.get("relationship_count") or 0) > int(args.max_relationships):
            continue
        if args.require_zero_control and int(row.get("control_path_count") or 0) > 0:
            continue
        vendor_id = str(row.get("vendor_id") or "")
        if vendor_id:
            selected.append(vendor_id)
        if len(selected) >= int(args.limit):
            break
    return selected


def main() -> int:
    args = parse_args()
    vendor_ids = _select_thin_vendor_ids(args)
    payload = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "vendor_ids": vendor_ids,
        "count": len(vendor_ids),
        "criteria": {
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
    sweep_id = scheduler.trigger_sweep(vendor_ids=vendor_ids)
    payload["sweep_id"] = sweep_id
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
