#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))
import bulk_ingest  # type: ignore  # noqa: E402


def normalize_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", name.upper()).strip()


def canonicalize_seed_name(name: str) -> tuple[str, list[str]]:
    raw_name = str(name or "").strip()
    if not raw_name:
        return "", []

    segments = [segment.strip() for segment in re.split(r"\s+\|\s+|\|", raw_name) if segment.strip()]
    if len(segments) <= 1:
        return raw_name, []

    canonical_name = segments[0]
    aliases: list[str] = []
    seen = {normalize_name(canonical_name)}
    for segment in segments[1:]:
        normalized = normalize_name(segment)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(segment)
    return canonical_name, aliases


class TrainingClient(bulk_ingest.HeliosClient):
    def __init__(self, host: str, email: str, password: str, token: str = ""):
        self._email = email
        self._password = password
        self._token = token
        super().__init__(host, email, password)

    def _login(self, email: str, password: str):
        if self._token:
            self.token = self._token
            self.session.headers["Authorization"] = f"Bearer {self.token}"
            return
        super()._login(email, password)

    def _request(self, method: str, path: str, *, retry_on_401: bool = True, **kwargs) -> requests.Response:
        request_url = f"{self.host}{path}"
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = self.session.request(method, request_url, **kwargs)
                if response.status_code == 401 and retry_on_401:
                    bulk_ingest.log.warning("Training cohort auth expired, re-authenticating and retrying once")
                    self._login(self._email, self._password)
                    response = self.session.request(method, request_url, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exc = exc
                if isinstance(exc, requests.HTTPError):
                    status_code = getattr(getattr(exc, "response", None), "status_code", 0) or 0
                    if status_code and status_code not in {429, 500, 502, 503, 504}:
                        raise
                if attempt >= 2:
                    raise
                bulk_ingest.log.warning(
                    "Transient request failure on %s %s (%s), retrying %d/2",
                    method,
                    path,
                    str(exc)[:120],
                    attempt + 1,
                )
                time.sleep(0.75 * (attempt + 1))
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Unhandled request failure for {method} {path}")

    def list_cases(self, limit: int = 5000) -> list[dict]:
        response = self._request(
            "GET",
            "/api/cases",
            params={"limit": limit},
            timeout=60,
        )
        payload = response.json()
        if isinstance(payload, list):
            return payload
        return payload.get("cases", payload.get("vendors", []))

    def create_case(self, name: str, country: str, *, seed_metadata: dict | None = None) -> dict:
        canonical_name, aliases = canonicalize_seed_name(name)
        payload = {
            "name": canonical_name,
            "country": country,
            "program": "standard_industrial",
            "profile": "defense_acquisition",
        }
        merged_seed_metadata = dict(seed_metadata or {})
        if aliases:
            merged_seed_metadata.setdefault("raw_name", name)
            merged_seed_metadata["aliases"] = aliases
        if merged_seed_metadata:
            payload["seed_metadata"] = merged_seed_metadata
        response = self._request(
            "POST",
            "/api/cases",
            json=payload,
            timeout=30,
        )
        return response.json()

    def enrich_and_score(self, case_id: str) -> dict:
        response = self._request(
            "POST",
            f"/api/cases/{case_id}/enrich-and-score",
            json={},
            timeout=120,
        )
        return response.json()

    def enrich(self, case_id: str) -> dict:
        response = self._request(
            "POST",
            f"/api/cases/{case_id}/enrich",
            json={},
            timeout=120,
        )
        return response.json()


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
    canonical_name, aliases = canonicalize_seed_name(row["name"])
    normalized = normalize_name(canonical_name)
    existing = case_index.get(normalized)
    if row["action"] == "replay":
        if not existing:
            raise RuntimeError(f"Replay target missing in Helios: {row['name']}")
        return resolve_case_id(existing), "replay"
    if existing:
        return resolve_case_id(existing), "replay_existing"
    seed_metadata = {"cohort_name": row["name"]} if aliases else None
    created = client.create_case(row["name"], row["country"], seed_metadata=seed_metadata)
    case_id = resolve_case_id(created)
    if not case_id:
        raise RuntimeError(f"Create response missing case id for {row['name']}: {created}")
    case_index[normalized] = {"name": canonical_name, "case_id": case_id}
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
