#!/usr/bin/env python3
"""Build a local-first GLEIF cache for the current vendor cohort."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import db  # type: ignore  # noqa: E402
from osint import gleif_lei  # type: ignore  # noqa: E402


DEFAULT_OUTPUT = ROOT / "var" / "gleif_lei_cache.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--country", default="")
    parser.add_argument("--vendor-id", action="append", default=[])
    parser.add_argument("--delay", type=float, default=0.15)
    return parser.parse_args()


def _select_vendors(args: argparse.Namespace) -> list[dict]:
    vendors = db.list_vendors(limit=max(int(args.limit or 0), 1))
    selected: list[dict] = []
    wanted = {str(item).strip() for item in args.vendor_id if str(item).strip()}
    wanted_country = str(args.country or "").strip().upper()
    for vendor in vendors:
        vendor_id = str(vendor.get("id") or "")
        country = str(vendor.get("country") or "").strip().upper()
        if wanted and vendor_id not in wanted:
            continue
        if wanted_country and country != wanted_country:
            continue
        selected.append(vendor)
        if args.vendor_id and len(selected) >= len(wanted):
            break
    return selected


def _serialize_result(vendor: dict, result) -> dict:
    return {
        "vendor_id": str(vendor.get("id") or ""),
        "vendor_name": str(vendor.get("name") or ""),
        "country": str(vendor.get("country") or "").strip().upper(),
        "cached_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": result.source,
        "source_class": result.source_class,
        "authority_level": result.authority_level,
        "access_model": result.access_model,
        "identifiers": result.identifiers,
        "findings": [
            {
                "source": finding.source,
                "category": finding.category,
                "title": finding.title,
                "detail": finding.detail,
                "severity": finding.severity,
                "confidence": finding.confidence,
                "url": finding.url,
                "raw_data": finding.raw_data,
                "timestamp": finding.timestamp,
                "source_class": finding.source_class,
                "authority_level": finding.authority_level,
                "access_model": finding.access_model,
                "artifact_ref": finding.artifact_ref,
                "structured_fields": finding.structured_fields,
            }
            for finding in result.findings
        ],
        "relationships": result.relationships,
        "risk_signals": result.risk_signals,
        "artifact_refs": result.artifact_refs,
        "structured_fields": result.structured_fields,
        "error": result.error,
        "has_data": result.has_data,
    }


def main() -> int:
    args = parse_args()
    vendors = _select_vendors(args)
    if not vendors:
        raise SystemExit("No vendors selected for GLEIF cache sync")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for idx, vendor in enumerate(vendors, start=1):
        vendor_name = str(vendor.get("name") or "").strip()
        country = str(vendor.get("country") or "").strip().upper()
        ids = {
            "lei": vendor.get("lei"),
            "force_live": True,
        }
        result = gleif_lei.enrich(vendor_name, country=country, **ids)
        rows.append(_serialize_result(vendor, result))
        if args.delay > 0 and idx < len(vendors):
            time.sleep(args.delay)

    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")

    print(str(args.output.resolve()))
    print(json.dumps({"vendors": len(vendors), "rows_with_data": sum(1 for row in rows if row.get("has_data"))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
