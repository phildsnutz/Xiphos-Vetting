#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_ownership_control_benchmark as benchmark  # type: ignore  # noqa: E402
import run_training_cohort as base  # type: ignore  # noqa: E402


DEFAULT_COHORT = ROOT / "docs" / "reports" / "HELIOS_CRITICAL_SUBSYSTEM_500_COHORT_2026-03-26.csv"
DEFAULT_OUTPUT = ROOT / "docs" / "reports" / f"helios-public-ownership-wave-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"


def _load_cohort_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _select_rows(
    rows: list[dict[str, str]],
    *,
    limit: int,
    only_buckets: set[str],
    only_actions: set[str],
    only_country: set[str],
    exclude_names: set[str],
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in rows:
        bucket = (row.get("bucket") or "").strip()
        action = (row.get("action") or "").strip()
        country = (row.get("country") or "").strip().upper()
        name = (row.get("name") or "").strip()
        if not name:
            continue
        if only_buckets and bucket not in only_buckets:
            continue
        if only_actions and action not in only_actions:
            continue
        if only_country and country not in only_country:
            continue
        if benchmark.normalize_name(name) in exclude_names:
            continue
        selected.append(row)
        if limit and len(selected) >= limit:
            break
    return selected


def _vendor_case_lookup(base_url: str, headers: dict[str, str]) -> dict[str, dict]:
    cases = benchmark.load_cases(base_url, headers)
    return benchmark.index_cases(cases)


def _fetch_supplier_passport(base_url: str, case_id: str, headers: dict[str, str]) -> dict[str, Any]:
    payload = benchmark.fetch_json(base_url, f"/api/cases/{case_id}/supplier-passport", headers, timeout=120)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected supplier-passport payload for {case_id}")
    return payload


def _ensure_wave_case(client: base.TrainingClient, case_index: dict[str, dict], row: dict[str, str]) -> tuple[str, str]:
    name = str(row.get("name") or "").strip()
    if not name:
        raise RuntimeError("missing row name")

    case = benchmark.choose_case(case_index, name)
    if case:
        case_id = str(case.get("case_id") or case.get("id") or "")
        if not case_id:
            raise RuntimeError(f"matched case missing id for {name}")
        return case_id, "existing"

    action = str(row.get("action") or "").strip().lower()
    if action != "create":
        raise RuntimeError(f"missing case for non-create row: {name}")

    created = client.create_case(
        name,
        str(row.get("country") or "").strip().upper() or "US",
        seed_metadata={
            "wave": "public_ownership",
            "bucket": row.get("bucket"),
            "priority": row.get("priority"),
            "cohort_name": name,
            "sources": row.get("sources"),
            "reason": row.get("reason"),
            "sequence": row.get("sequence"),
        },
    )
    case_id = str(created.get("case_id") or created.get("id") or "")
    if not case_id:
        raise RuntimeError(f"create response missing case id for {name}: {created}")

    canonical_name, _aliases = base.canonicalize_seed_name(name)
    case_index[benchmark.normalize_name(canonical_name)] = {
        "case_id": case_id,
        "vendor_name": canonical_name,
        "name": canonical_name,
    }
    return case_id, "created"


def _write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _build_summary(rows: list[dict[str, Any]], *, target_count: int | None = None) -> dict[str, Any]:
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    errors = [row for row in rows if row.get("status") != "ok"]
    control = [row for row in ok_rows if row.get("control_path_count", 0) > 0]
    ownership = [row for row in ok_rows if row.get("ownership_path_count", 0) > 0]
    intermediary = [row for row in ok_rows if row.get("intermediary_path_count", 0) > 0]
    bucket_counts = Counter(str(row.get("bucket") or "unknown") for row in ok_rows)
    case_mode_counts = Counter(str(row.get("case_mode") or "unknown") for row in ok_rows)
    return {
        "rows_selected": int(target_count if target_count is not None else len(rows)),
        "rows_completed": len(rows),
        "rows_ok": len(ok_rows),
        "rows_error": len(errors),
        "rows_with_control_paths": len(control),
        "rows_with_ownership_paths": len(ownership),
        "rows_with_intermediary_paths": len(intermediary),
        "control_path_rate_pct": round((len(control) / len(ok_rows)) * 100, 1) if ok_rows else 0.0,
        "ownership_path_rate_pct": round((len(ownership) / len(ok_rows)) * 100, 1) if ok_rows else 0.0,
        "bucket_mix": dict(bucket_counts),
        "case_mode_mix": dict(case_mode_counts),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the cheap-plus-official ownership collector wave across a Helios cohort")
    parser.add_argument("--cohort-file", type=Path, default=DEFAULT_COHORT)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("HELIOS_BASE_URL") or os.environ.get("HELIOS_HOST") or "http://127.0.0.1:8080",
    )
    parser.add_argument("--token", default=os.environ.get("HELIOS_TOKEN", ""))
    parser.add_argument("--email", default=os.environ.get("HELIOS_LOGIN_EMAIL") or os.environ.get("HELIOS_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("HELIOS_LOGIN_PASSWORD") or os.environ.get("HELIOS_PASSWORD"))
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--delay", type=float, default=0.6)
    parser.add_argument("--only-bucket", default="")
    parser.add_argument("--only-action", default="create")
    parser.add_argument("--only-country", default="US,GB,UK,GR")
    parser.add_argument("--include-benchmark", action="store_true")
    parser.add_argument("--output-file", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = _load_cohort_rows(args.cohort_file)
    exclude_names = set()
    if not args.include_benchmark:
        for names in benchmark.BENCHMARK_GROUPS.values():
            exclude_names.update(benchmark.normalize_name(name) for name in names)
    selected = _select_rows(
        rows,
        limit=args.limit,
        only_buckets={item for item in args.only_bucket.split(",") if item},
        only_actions={item for item in args.only_action.split(",") if item},
        only_country={item.strip().upper() for item in args.only_country.split(",") if item.strip()},
        exclude_names=exclude_names,
    )
    if not selected:
        raise SystemExit("No cohort rows selected for ownership wave")

    if args.dry_run:
        print(json.dumps(selected[: min(20, len(selected))], indent=2))
        print(f"Rows selected: {len(selected)}")
        return 0

    if not args.token and (not args.email or not args.password):
        raise SystemExit("Set HELIOS_TOKEN or HELIOS_EMAIL/HELIOS_PASSWORD, or pass --token / --email / --password")

    headers = benchmark.login(args.base_url, args.email or "", args.password or "", args.token)
    client = base.TrainingClient(args.base_url, args.email or "", args.password or "", token=args.token)
    case_index = _vendor_case_lookup(args.base_url, headers)

    results: list[dict[str, Any]] = []
    total = len(selected)
    for idx, row in enumerate(selected, start=1):
        name = str(row.get("name") or "")
        case_id = ""
        try:
            case_id, case_mode = _ensure_wave_case(client, case_index, row)
            client.enrich_and_score(case_id)
            passport = _fetch_supplier_passport(args.base_url, case_id, headers)
            evaluation = benchmark.evaluate_passport(passport)
            metrics = evaluation["control_path_metrics"]
            result = {
                "name": name,
                "bucket": row.get("bucket"),
                "country": row.get("country"),
                "case_id": case_id,
                "case_mode": case_mode,
                "status": "ok",
                "relationship_count": evaluation["relationship_count"],
                "entity_count": evaluation["entity_count"],
                "control_path_count": metrics["control_path_count"],
                "ownership_path_count": metrics["ownership_path_count"],
                "intermediary_path_count": metrics["intermediary_path_count"],
                "analyst_usefulness_score": evaluation["analyst_usefulness_score"],
                "workflow_control_label": evaluation["workflow_control_label"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            print(
                f"[{idx}/{total}] {name} -> control={metrics['control_path_count']} "
                f"ownership={metrics['ownership_path_count']} intermediary={metrics['intermediary_path_count']}"
            )
        except Exception as exc:
            status = "missing_case"
            if "missing case" not in str(exc).lower():
                status = "error"
            result = {
                "name": name,
                "bucket": row.get("bucket"),
                "country": row.get("country"),
                "status": status,
                "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if case_id:
                result["case_id"] = case_id
            print(f"[{idx}/{total}] ERROR {name}: {exc}")

        results.append(result)
        _write_output(
            args.output_file,
            {
                "base_url": args.base_url,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "cohort_file": str(args.cohort_file),
                "rows": results,
                "summary": _build_summary(results, target_count=total),
            },
        )
        if args.delay > 0 and idx < total:
            time.sleep(args.delay)

    summary = _build_summary(results, target_count=total)
    print(json.dumps(summary, indent=2))
    return 0 if summary["rows_error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
