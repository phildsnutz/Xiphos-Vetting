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
BACKEND_DIR = ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import bulk_ingest  # type: ignore


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_slug() -> str:
    return utc_now().strftime("%Y%m%d-%H%M%S")


def normalize_name(name: str) -> str:
    import re

    return re.sub(r"[^A-Z0-9]+", " ", str(name or "").upper()).strip()


def parse_wait_until(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith(" UTC"):
        text = text[:-4]
        try:
            return datetime.strptime(text, "%Y-%b-%d %H:%M:%S%z").astimezone(timezone.utc)
        except Exception:
            return None
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(timezone.utc)
    except Exception:
        return None


class SamRetryClient(bulk_ingest.HeliosClient):
    def list_cases(self, limit: int = 5000) -> list[dict]:
        response = self.session.get(
            f"{self.host}/api/cases",
            params={"limit": limit},
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        return payload.get("cases", payload.get("vendors", []))

    def get_case_enrichment(self, case_id: str) -> dict | None:
        response = self.session.get(f"{self.host}/api/cases/{case_id}/enrichment", timeout=120)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def enrich_case_force(self, case_id: str, connectors: list[str] | None = None) -> dict:
        payload: dict = {"force": True}
        if connectors:
            payload["connectors"] = connectors
        response = self.session.post(
            f"{self.host}/api/cases/{case_id}/enrich-and-score",
            json=payload,
            timeout=180,
        )
        response.raise_for_status()
        return response.json()


def load_results(paths: list[Path]) -> list[dict]:
    merged: list[dict] = []
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        if isinstance(payload, list):
            merged.extend(payload)
        elif isinstance(payload, dict):
            rerun_results = payload.get("rerun_results")
            candidates = payload.get("candidates")
            if isinstance(rerun_results, list):
                merged.extend(rerun_results)
            elif isinstance(candidates, list):
                merged.extend(candidates)
    return merged


def build_case_index(cases: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for case in cases:
        name = (case.get("vendor_name") or case.get("name") or "").strip()
        if not name:
            continue
        index[normalize_name(name)] = case
    return index


def resolve_case_id(case: dict | None) -> str:
    if not case:
        return ""
    return str(case.get("case_id") or case.get("id") or "")


def _sam_titles(report: dict | None) -> set[str]:
    if not isinstance(report, dict):
        return set()
    titles = set()
    for finding in report.get("findings", []):
        if finding.get("source") == "sam_gov":
            titles.add(str(finding.get("title") or ""))
    return titles


def _sam_next_access_time(report: dict | None) -> str:
    if not isinstance(report, dict):
        return ""
    connector_status = report.get("connector_status", {}) or {}
    sam_status = connector_status.get("sam_gov", {}) or {}
    structured = sam_status.get("structured_fields", {}) or {}
    sam_api_status = structured.get("sam_api_status", {}) or {}
    for key in ("entity_lookup", "exclusions_lookup"):
        meta = sam_api_status.get(key, {}) or {}
        next_access = str(meta.get("next_access_time") or "")
        if next_access:
            return next_access
    return ""


def sam_retry_needed(report: dict | None, country: str = "") -> tuple[bool, str]:
    if not isinstance(report, dict):
        return True, "missing_enrichment_report"

    identifiers = report.get("identifiers", {}) or {}
    has_uei = bool(str(identifiers.get("uei") or "").strip())
    has_cage = bool(str(identifiers.get("cage") or "").strip())
    legal_jurisdiction = str(identifiers.get("legal_jurisdiction") or "").upper()
    normalized_country = str(country or "").upper()

    if normalized_country == "US" and legal_jurisdiction and not legal_jurisdiction.startswith("US"):
        return True, "identity_jurisdiction_mismatch"

    if has_uei and has_cage:
        return False, "sam_identifiers_present"

    connector_status = report.get("connector_status", {}) or {}
    sam_status = connector_status.get("sam_gov", {}) or {}
    sam_error = str(sam_status.get("error") or "")
    titles = _sam_titles(report)

    if "rate limit" in sam_error.lower():
        return True, "sam_rate_limited"
    if any("rate limit" in title.lower() for title in titles):
        return True, "sam_rate_limited"
    if "SAM.gov registration lookup unavailable" in titles:
        return True, "sam_lookup_unavailable"
    if "No SAM registration found" in titles:
        return True, "sam_missing_identifiers"

    return not (has_uei and has_cage), "sam_identifiers_missing"


def collect_candidates(results: list[dict], case_index: dict[str, dict], client: SamRetryClient) -> tuple[list[dict], datetime | None]:
    candidates: list[dict] = []
    wait_candidates: list[datetime] = []

    for row in results:
        matched_case = case_index.get(normalize_name(row.get("name", "")))
        country = str(row.get("country") or (matched_case or {}).get("country") or "").upper()
        if country != "US":
            continue

        case_id = str(row.get("case_id") or "")
        if not case_id:
            case_id = resolve_case_id(matched_case)
        if not case_id:
            continue

        report = client.get_case_enrichment(case_id)
        needs_retry, reason = sam_retry_needed(report, country=country)
        if not needs_retry:
            continue

        next_access = _sam_next_access_time(report)
        wait_until = parse_wait_until(next_access)
        if wait_until is not None:
            wait_candidates.append(wait_until)

        candidates.append(
            {
                "name": row.get("name"),
                "case_id": case_id,
                "country": country,
                "reason": reason,
                "current_identifiers": (report or {}).get("identifiers", {}),
                "next_access_time": next_access,
            }
        )

    wait_until = max(wait_candidates) if wait_candidates else None
    return candidates, wait_until


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def wait_until(target: datetime) -> None:
    while True:
        remaining = (target - utc_now()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(300, max(5, remaining)))


def run_retry_pass(args: argparse.Namespace) -> int:
    explicit_wait_until = parse_wait_until(args.wait_until)
    if explicit_wait_until is not None and not args.dry_run and utc_now() < explicit_wait_until:
        wait_until(explicit_wait_until)

    results = load_results(args.results_file)
    client = SamRetryClient(args.base_url, args.email, args.password)
    cases = client.list_cases()
    case_index = build_case_index(cases)
    candidates, derived_wait_until = collect_candidates(results, case_index, client)

    summary = {
        "captured_at": utc_now().isoformat(),
        "base_url": args.base_url,
        "results_files": [str(path) for path in args.results_file],
        "candidate_count": len(candidates),
        "candidates": candidates,
    }

    effective_wait_until = explicit_wait_until or derived_wait_until
    if effective_wait_until is not None:
        summary["wait_until"] = effective_wait_until.isoformat()

    if args.dry_run:
        write_json(args.output_file, summary)
        print(json.dumps(summary, indent=2))
        return 0

    if explicit_wait_until is None and effective_wait_until is not None and utc_now() < effective_wait_until:
        wait_until(effective_wait_until)

    rerun_results: list[dict] = []
    for idx, candidate in enumerate(candidates, start=1):
        case_id = candidate["case_id"]
        try:
            response = client.enrich_case_force(case_id)
            latest = client.get_case_enrichment(case_id)
            identifiers = (latest or {}).get("identifiers", {})
            rerun_results.append(
                {
                    "index": idx,
                    "name": candidate["name"],
                    "case_id": case_id,
                    "status": "ok",
                    "uei": identifiers.get("uei", ""),
                    "cage": identifiers.get("cage", ""),
                    "overall_risk": response.get("enrichment", {}).get("overall_risk"),
                    "timestamp": utc_now().isoformat(),
                }
            )
            print(f"[{idx}/{len(candidates)}] {candidate['name']} -> UEI={identifiers.get('uei', '') or 'N/A'} CAGE={identifiers.get('cage', '') or 'N/A'}")
        except Exception as exc:
            rerun_results.append(
                {
                    "index": idx,
                    "name": candidate["name"],
                    "case_id": case_id,
                    "status": "error",
                    "error": str(exc),
                    "timestamp": utc_now().isoformat(),
                }
            )
            print(f"[{idx}/{len(candidates)}] ERROR {candidate['name']}: {exc}")

        write_json(
            args.output_file,
            {
                **summary,
                "completed_at": utc_now().isoformat(),
                "rerun_results": rerun_results,
            },
        )

    final_payload = {
        **summary,
        "completed_at": utc_now().isoformat(),
        "rerun_results": rerun_results,
        "success_count": sum(1 for item in rerun_results if item.get("status") == "ok"),
        "error_count": sum(1 for item in rerun_results if item.get("status") == "error"),
    }
    write_json(args.output_file, final_payload)
    print(json.dumps({"output_file": str(args.output_file), "candidate_count": len(candidates), "success_count": final_payload["success_count"], "error_count": final_payload["error_count"]}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Force a SAM-focused re-enrichment pass for US cases missing UEI/CAGE data")
    parser.add_argument("--results-file", type=Path, nargs="+", required=True)
    parser.add_argument("--base-url", default=os.environ.get("HELIOS_BASE_URL") or os.environ.get("HELIOS_HOST") or "http://127.0.0.1:8080")
    parser.add_argument("--email", default=os.environ.get("HELIOS_LOGIN_EMAIL") or os.environ.get("HELIOS_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("HELIOS_LOGIN_PASSWORD") or os.environ.get("HELIOS_PASSWORD"))
    parser.add_argument("--wait-until", default="", help="Optional absolute UTC time to wait for before rerunning, either ISO-8601 or SAM nextAccessTime format.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-file", type=Path, default=ROOT / "docs" / "reports" / f"helios-sam-reenrichment-pass-{utc_now_slug()}.json")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.email or not args.password:
        raise SystemExit("Set HELIOS_EMAIL/HELIOS_PASSWORD or pass --email/--password")
    return run_retry_pass(args)


if __name__ == "__main__":
    raise SystemExit(main())
