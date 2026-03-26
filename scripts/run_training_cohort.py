#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))
import bulk_ingest  # type: ignore


def normalize_name(name: str) -> str:
    import re

    return re.sub(r"[^A-Z0-9]+", " ", name.upper()).strip()


class TrainingClient(bulk_ingest.HeliosClient):
    def list_cases(self, limit: int = 5000) -> list[dict]:
        response = self.session.get(
            f"{self.host}/api/cases",
            params={"limit": limit},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        return payload.get("cases", payload.get("vendors", []))


def load_rows(path: Path) -> list[dict]:
    with path.open() as handle:
        return list(csv.DictReader(handle))


def select_rows(rows: list[dict], offset: int, limit: int, only_buckets: set[str], only_actions: set[str]) -> list[dict]:
    selected = [
        row
        for row in rows
        if (not only_buckets or row["bucket"] in only_buckets)
        and (not only_actions or row["action"] in only_actions)
    ]
    if offset:
        selected = selected[offset:]
    if limit:
        selected = selected[:limit]
    return selected


def build_case_index(cases: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for case in cases:
        name = (case.get("vendor_name") or case.get("name") or "").strip()
        if not name:
            continue
        index[normalize_name(name)] = case
    return index


def resolve_case_id(case: dict) -> str:
    return case.get("case_id") or case.get("id") or ""


def ensure_case(client: TrainingClient, case_index: dict[str, dict], row: dict) -> tuple[str, str]:
    normalized = normalize_name(row["name"])
    existing = case_index.get(normalized)
    if row["action"] == "replay":
        if not existing:
            raise RuntimeError(f"Replay target missing in Helios: {row['name']}")
        return resolve_case_id(existing), "replay"
    if existing:
        return resolve_case_id(existing), "replay_existing"
    created = client.create_case(row["name"], row["country"])
    case_id = resolve_case_id(created)
    if not case_id:
        raise RuntimeError(f"Create response missing case id for {row['name']}: {created}")
    case_index[normalized] = {"name": row["name"], "case_id": case_id}
    return case_id, "create"


def write_results(results: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a mixed create/replay Helios training cohort")
    parser.add_argument("--cohort-file", type=Path, required=True)
    parser.add_argument("--base-url", default=os.environ.get("HELIOS_BASE_URL") or os.environ.get("HELIOS_HOST") or "http://127.0.0.1:8080")
    parser.add_argument("--email", default=os.environ.get("HELIOS_LOGIN_EMAIL") or os.environ.get("HELIOS_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("HELIOS_LOGIN_PASSWORD") or os.environ.get("HELIOS_PASSWORD"))
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--only-bucket", default="")
    parser.add_argument("--only-action", default="")
    parser.add_argument("--skip-enrich", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-file", type=Path, default=ROOT / "docs" / "reports" / f"helios-training-cohort-run-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    args = parser.parse_args()

    rows = load_rows(args.cohort_file)
    selected = select_rows(
        rows,
        offset=args.offset,
        limit=args.limit,
        only_buckets={item for item in args.only_bucket.split(",") if item},
        only_actions={item for item in args.only_action.split(",") if item},
    )
    if not selected:
        raise SystemExit("No cohort rows selected")

    if args.dry_run:
        print(json.dumps(selected[: min(20, len(selected))], indent=2))
        print(f"Selected rows: {len(selected)}")
        return 0

    if not args.email or not args.password:
        raise SystemExit("Set HELIOS_EMAIL/HELIOS_PASSWORD or pass --email/--password")

    client = TrainingClient(args.base_url, args.email, args.password)
    cases = client.list_cases()
    case_index = build_case_index(cases)

    results: list[dict] = []
    for idx, row in enumerate(selected, start=1):
        try:
            case_id, mode = ensure_case(client, case_index, row)
            enrichment = None
            if not args.skip_enrich:
                enrichment = client.enrich_and_score(case_id)
            result = {
                "sequence": row["sequence"],
                "name": row["name"],
                "bucket": row["bucket"],
                "action": row["action"],
                "mode": mode,
                "country": row["country"],
                "case_id": case_id,
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if enrichment:
                scoring = enrichment.get("scoring", {})
                summary = enrichment.get("enrichment", {})
                result["overall_risk"] = summary.get("overall_risk")
                result["composite_score"] = scoring.get("composite_score")
            print(f"[{idx}/{len(selected)}] {row['name']} -> {mode} ({case_id})")
        except Exception as exc:
            result = {
                "sequence": row["sequence"],
                "name": row["name"],
                "bucket": row["bucket"],
                "action": row["action"],
                "status": "error",
                "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            print(f"[{idx}/{len(selected)}] ERROR {row['name']}: {exc}")
        results.append(result)
        write_results(results, args.output_file)
        if args.delay > 0 and idx < len(selected):
            time.sleep(args.delay)

    success_count = sum(1 for item in results if item["status"] == "ok")
    error_count = len(results) - success_count
    print(
        json.dumps(
            {
                "selected": len(selected),
                "success_count": success_count,
                "error_count": error_count,
                "output_file": str(args.output_file),
            },
            indent=2,
        )
    )
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
