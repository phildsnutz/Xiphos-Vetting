#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_training_cohort as base  # type: ignore  # noqa: E402


def load_result_index(paths: list[Path]) -> dict[int, dict]:
    merged: dict[int, dict] = {}
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("results", []) if isinstance(payload, dict) else payload
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                sequence = int(row.get("sequence"))
            except Exception:
                continue
            merged[sequence] = row
    return merged


def select_repair_rows(cohort_rows: list[dict], result_index: dict[int, dict], *, repair_missing: bool = False) -> list[dict]:
    selected: list[dict] = []
    for row in cohort_rows:
        try:
            sequence = int(row["sequence"])
        except Exception:
            continue
        existing = result_index.get(sequence)
        if existing is None:
            if repair_missing:
                selected.append(row)
            continue
        if str(existing.get("status") or "") != "ok":
            selected.append(row)
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair failed or missing rows from a Helios training cohort run")
    parser.add_argument("--cohort-file", type=Path, required=True)
    parser.add_argument("--results-file", type=Path, nargs="+", required=True)
    parser.add_argument("--base-url", default=os.environ.get("HELIOS_BASE_URL") or os.environ.get("HELIOS_HOST") or "http://127.0.0.1:8080")
    parser.add_argument("--email", default=os.environ.get("HELIOS_LOGIN_EMAIL") or os.environ.get("HELIOS_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("HELIOS_LOGIN_PASSWORD") or os.environ.get("HELIOS_PASSWORD"))
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--skip-enrich", action="store_true")
    parser.add_argument("--repair-missing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-file", type=Path, default=ROOT / "docs" / "reports" / f"helios-training-cohort-repair-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    args = parser.parse_args()

    cohort_rows = base.load_rows(args.cohort_file)
    result_index = load_result_index(args.results_file)
    repair_rows = select_repair_rows(cohort_rows, result_index, repair_missing=args.repair_missing)

    if args.dry_run:
        print(json.dumps(repair_rows[: min(20, len(repair_rows))], indent=2))
        print(f"Rows selected for repair: {len(repair_rows)}")
        return 0

    if not repair_rows:
        args.output_file.parent.mkdir(parents=True, exist_ok=True)
        args.output_file.write_text(json.dumps([], indent=2), encoding="utf-8")
        print(args.output_file)
        print("No failed cohort rows to repair")
        return 0

    if not args.email or not args.password:
        raise SystemExit("Set HELIOS_EMAIL/HELIOS_PASSWORD or pass --email/--password")

    client = base.TrainingClient(args.base_url, args.email, args.password)
    cases = client.list_cases()
    case_index = base.build_case_index(cases)

    results: list[dict] = []
    total = len(repair_rows)
    for idx, row in enumerate(repair_rows, start=1):
        try:
            case_id, mode = base.ensure_case(client, case_index, row)
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
                "repair": True,
            }
            if enrichment:
                scoring = enrichment.get("scoring", {})
                summary = enrichment.get("enrichment", {})
                result["overall_risk"] = summary.get("overall_risk")
                result["composite_score"] = scoring.get("composite_score")
            print(f"[{idx}/{total}] repaired {row['name']} -> {mode} ({case_id})")
        except Exception as exc:
            result = {
                "sequence": row["sequence"],
                "name": row["name"],
                "bucket": row["bucket"],
                "action": row["action"],
                "status": "error",
                "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "repair": True,
            }
            print(f"[{idx}/{total}] ERROR {row['name']}: {exc}")
        results.append(result)
        base.write_results(results, args.output_file)
        if args.delay > 0 and idx < total:
            time.sleep(args.delay)

    success_count = sum(1 for item in results if item["status"] == "ok")
    error_count = len(results) - success_count
    print(
        json.dumps(
            {
                "selected": total,
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
