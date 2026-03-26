#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
FIXTURE_DIR = ROOT / "fixtures" / "training_run"
REPORT_DIR = ROOT / "docs" / "reports"
HOSTED_VENDORS_FILE = Path("/tmp/helios_hosted_vendors.tsv")
SOF_RAW_FILE = BACKEND_DIR / "sof_week_2024_exhibitors.json"
SOF_SCORED_FILE = ROOT / "sof-week-intel" / "src" / "data" / "vendors.ts"
INTL_FIXTURE_FILE = ROOT / "fixtures" / "international_exhibitors" / "world_defense_exhibitors_2026.json"

PUBLIC_SOURCES = {
    "ausa_2025": {
        "label": "AUSA Annual Meeting 2025",
        "url": "https://meetings.ausa.org/annual/2025/exhibitor_exhibitor_list.cfm",
        "pattern": re.compile(r'>\s*([^<]+)</a>\s*</u>\s*</td>\s*<td class="tb-text-center">', re.I),
        "fixture_file": FIXTURE_DIR / "ausa_annual_2025_exhibitors.json",
        "priority": 4,
    },
    "afa_2025": {
        "label": "AFA Air, Space & Cyber 2025",
        "url": "https://www.afa.org/air-space-cyber-conference/exhibitor-directory/",
        "pattern": re.compile(r"<div class='afa-exhibitor[^>]*>.*?<h4><a [^>]+>([^<]+)</a>&nbsp;\| Booth", re.I | re.S),
        "fixture_file": FIXTURE_DIR / "afa_air_space_cyber_2025_exhibitors.json",
        "priority": 2,
    },
    "mdm_2025": {
        "label": "Modern Day Marine 2025",
        "url": "https://modernday2025.smallworldlabs.com/exhibitors",
        "pattern": re.compile(r'<a class="generic-option-link" href="/co/[^"]+"[^>]*>([^<]+)</a>', re.I),
        "fixture_file": FIXTURE_DIR / "modern_day_marine_2025_exhibitors.json",
        "priority": 3,
    },
}

SOURCE_PRIORITY = {
    "sof_raw": 5,
    "ausa_2025": 4,
    "mdm_2025": 3,
    "afa_2025": 2,
}

ANCHOR_TOKENS = (
    "aerospace",
    "aircraft",
    "airborne",
    "autonomy",
    "aviation",
    "communications",
    "defense",
    "electronics",
    "intelligence",
    "mission",
    "robotics",
    "satellite",
    "space",
    "systems",
    "tactical",
    "technologies",
)

SUPPLIER_TOKENS = (
    "logistics",
    "manufacturing",
    "materials",
    "optics",
    "power",
    "research",
    "signal",
    "solutions",
    "support",
    "test",
    "training",
)

EXTRA_SKIP_SUBSTRINGS = (
    "aid society",
    "air force ",
    "air force district",
    "air force enlisted village",
    "air warrior courage",
    "air university",
    "american red cross",
    "armed services ymca",
    "association of old crows",
    "battle monuments foundation",
    "blue cross blue shield",
    "charitable",
    "chamber of commerce",
    "courage foundation",
    "district of washington",
    "embassy of ",
    "exchange service",
    "foundation",
    "office of special investigations",
    "operational energy",
    "program office",
    "school of ",
    "university",
    "village",
    "warrior",
    "ymca",
)

EXTRA_SKIP_PREFIXES = (
    "afit ",
    "afrl",
    "afsc ",
    "afwerx",
    "air force",
    "army ",
    "defense industrial base",
    "dod ",
    "navy ",
    "u.s. ",
    "us ",
)

HIGH_RISK_COUNTRY_ORDER = {
    "CN": 0,
    "RU": 1,
    "BY": 2,
    "TR": 3,
    "AE": 4,
    "RS": 5,
    "IN": 6,
    "PK": 7,
    "SA": 8,
    "SG": 9,
}

ALLIED_COUNTRIES = (
    "AU",
    "BE",
    "BR",
    "CA",
    "CH",
    "CZ",
    "DE",
    "ES",
    "FI",
    "FR",
    "GB",
    "IL",
    "IT",
    "JP",
    "KR",
    "NL",
    "NO",
    "PL",
    "RO",
    "SA",
    "SE",
    "SG",
    "ZA",
)


def load_bulk_ingest_module():
    sys.path.insert(0, str(BACKEND_DIR))
    import bulk_ingest  # type: ignore

    return bulk_ingest


BULK_INGEST = load_bulk_ingest_module()


@dataclass
class Candidate:
    name: str
    country: str
    action: str
    bucket: str
    priority: int
    sources: list[str] = field(default_factory=list)
    reason: str = ""


def normalize_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", html.unescape(name).upper()).strip()


def dedupe_display_names(names: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        cleaned = html.unescape(name).strip()
        key = normalize_name(cleaned)
        if not cleaned or not key or key in seen:
            continue
        deduped.append(cleaned)
        seen.add(key)
    return deduped


def is_commercial_candidate(name: str) -> bool:
    if not BULK_INGEST.filter_commercial_vendors([name]):
        return False
    lowered = name.lower().strip()
    if any(token in lowered for token in EXTRA_SKIP_SUBSTRINGS):
        return False
    if any(lowered.startswith(prefix) for prefix in EXTRA_SKIP_PREFIXES):
        return False
    return True


def load_hosted_vendor_names(path: Path) -> set[str]:
    if not path.exists():
        raise FileNotFoundError(f"Hosted vendor export not found: {path}")
    hosted: set[str] = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        hosted.add(normalize_name(line.split("\t", 1)[0]))
    return hosted


def load_scored_sof_names() -> set[str]:
    if not SOF_SCORED_FILE.exists():
        return set()
    text = SOF_SCORED_FILE.read_text()
    rows = re.findall(r'\{ name: "(.*?)", country: "(.*?)", tier: "(.*?)"', text)
    return {normalize_name(name) for name, _, _ in rows}


def fetch_public_source(source_key: str) -> dict:
    config = PUBLIC_SOURCES[source_key]
    response = requests.get(config["url"], timeout=30)
    response.raise_for_status()
    names = dedupe_display_names(config["pattern"].findall(response.text))
    payload = {
        "dataset_id": f"{source_key}_exhibitors",
        "display_name": config["label"],
        "source_url": config["url"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(names),
        "names": names,
    }
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    config["fixture_file"].write_text(json.dumps(payload, indent=2))
    return payload


def load_public_source(source_key: str, refresh: bool) -> dict:
    config = PUBLIC_SOURCES[source_key]
    fixture_file: Path = config["fixture_file"]
    if refresh or not fixture_file.exists():
        return fetch_public_source(source_key)
    return json.loads(fixture_file.read_text())


def load_sof_raw_names() -> list[str]:
    payload = json.loads(SOF_RAW_FILE.read_text())
    return dedupe_display_names(payload["exhibitors"])


def load_intl_fixture_rows() -> list[dict]:
    payload = json.loads(INTL_FIXTURE_FILE.read_text())
    return payload.get("companies", payload.get("exhibitors", []))


def candidate_score(name: str, sources: set[str], scored_sof_names: set[str]) -> int:
    lowered = name.lower()
    score = sum(SOURCE_PRIORITY.get(source, 0) for source in sources)
    if len(sources) > 1:
        score += 5 * (len(sources) - 1)
    if normalize_name(name) in scored_sof_names:
        score += 8
    score += sum(1 for token in ANCHOR_TOKENS if token in lowered)
    score += sum(1 for token in SUPPLIER_TOKENS if token in lowered)
    if "amazon web services" in lowered or "boeing" in lowered or "anduril" in lowered or "lockheed" in lowered:
        score += 3
    return score


def build_new_us_candidates(hosted_names: set[str], scored_sof_names: set[str], refresh_public_sources: bool) -> list[dict]:
    source_names: dict[str, list[str]] = {"sof_raw": load_sof_raw_names()}
    for source_key in PUBLIC_SOURCES:
        source_names[source_key] = load_public_source(source_key, refresh_public_sources)["names"]

    candidates: dict[str, dict] = {}
    for source_key, names in source_names.items():
        for name in names:
            if not is_commercial_candidate(name):
                continue
            normalized = normalize_name(name)
            if not normalized or normalized in hosted_names:
                continue
            country = BULK_INGEST.guess_country(name)
            if country != "US":
                continue
            record = candidates.setdefault(
                normalized,
                {
                    "name": name,
                    "country": "US",
                    "sources": set(),
                },
            )
            record["sources"].add(source_key)
            if len(name) > len(record["name"]):
                record["name"] = name

    scored_records: list[dict] = []
    for record in candidates.values():
        record["sources"] = sorted(record["sources"], key=lambda key: (-SOURCE_PRIORITY.get(key, 0), key))
        record["score"] = candidate_score(record["name"], set(record["sources"]), scored_sof_names)
        scored_records.append(record)

    scored_records.sort(
        key=lambda item: (
            -item["score"],
            -len(item["sources"]),
            item["name"].lower(),
        )
    )
    return scored_records


def build_replay_candidates(hosted_names: set[str]) -> tuple[list[dict], list[dict], list[dict]]:
    high_risk: list[dict] = []
    allied: list[dict] = []
    partners: list[dict] = []
    for row in load_intl_fixture_rows():
        name = row["name"].strip()
        normalized = normalize_name(name)
        if normalized not in hosted_names:
            continue
        country = row.get("country", "unknown")
        sectors = row.get("sectors", [])
        record = {
            "name": name,
            "country": country,
            "sectors": sectors,
            "reason": ", ".join(sectors[:3]) if sectors else "fixture-backed defense exhibitor",
        }
        if country in HIGH_RISK_COUNTRY_ORDER:
            high_risk.append(record)
        elif country in ALLIED_COUNTRIES:
            allied.append(record)
        elif country != "US":
            partners.append(record)

    high_risk.sort(
        key=lambda item: (
            HIGH_RISK_COUNTRY_ORDER[item["country"]],
            -len(item["sectors"]),
            item["name"].lower(),
        )
    )
    allied.sort(
        key=lambda item: (
            item["country"],
            -len(item["sectors"]),
            item["name"].lower(),
        )
    )
    partners.sort(
        key=lambda item: (
            item["country"],
            -len(item["sectors"]),
            item["name"].lower(),
        )
    )
    return high_risk, allied, partners


def slice_bucket(records: list[dict], size: int, bucket: str, action: str, reason_prefix: str) -> list[Candidate]:
    selected: list[Candidate] = []
    for index, record in enumerate(records[:size], start=1):
        if action == "create":
            reason = f"{reason_prefix}; source overlap: {', '.join(record['sources'])}"
            sources = record["sources"]
            priority = record["score"]
        else:
            reason = f"{reason_prefix}; sectors: {record['reason']}"
            sources = ["world_defense_exhibitors_2026"]
            priority = 1000 - index
        selected.append(
            Candidate(
                name=record["name"],
                country=record["country"],
                action=action,
                bucket=bucket,
                priority=priority,
                sources=sources,
                reason=reason,
            )
        )
    return selected


def write_cohort_files(candidates: list[Candidate], date_slug: str) -> tuple[Path, Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = REPORT_DIR / f"HELIOS_TONIGHT_1000_ENTITY_COHORT_{date_slug}.csv"
    json_path = REPORT_DIR / f"HELIOS_TONIGHT_1000_ENTITY_COHORT_{date_slug}.json"
    md_path = REPORT_DIR / f"HELIOS_TONIGHT_1000_ENTITY_COHORT_{date_slug}.md"

    rows = []
    for sequence, candidate in enumerate(candidates, start=1):
        rows.append(
            {
                "sequence": sequence,
                "action": candidate.action,
                "bucket": candidate.bucket,
                "name": candidate.name,
                "country": candidate.country,
                "priority": candidate.priority,
                "sources": ";".join(candidate.sources),
                "reason": candidate.reason,
            }
        )

    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["sequence", "action", "bucket", "name", "country", "priority", "sources", "reason"],
        )
        writer.writeheader()
        writer.writerows(rows)

    json_path.write_text(json.dumps(rows, indent=2))

    bucket_counts = Counter(candidate.bucket for candidate in candidates)
    action_counts = Counter(candidate.action for candidate in candidates)
    md_lines = [
        "# Helios Tonight 1000-Entity Cohort",
        "",
        f"Date: {date_slug}",
        "",
        "## Summary",
        "",
        f"- Total rows: `{len(candidates)}`",
        f"- Create rows: `{action_counts.get('create', 0)}`",
        f"- Replay rows: `{action_counts.get('replay', 0)}`",
        "",
        "## Bucket Counts",
        "",
    ]
    for bucket, count in bucket_counts.items():
        md_lines.append(f"- `{bucket}`: `{count}`")
    md_lines.extend(
        [
            "",
            "## Files",
            "",
            f"- CSV: `{csv_path}`",
            f"- JSON: `{json_path}`",
        ]
    )
    md_path.write_text("\n".join(md_lines) + "\n")
    return csv_path, json_path, md_path


def build_cohort(hosted_vendor_file: Path, refresh_public_sources: bool, date_slug: str) -> tuple[list[Candidate], dict]:
    hosted_names = load_hosted_vendor_names(hosted_vendor_file)
    scored_sof_names = load_scored_sof_names()
    new_us_candidates = build_new_us_candidates(hosted_names, scored_sof_names, refresh_public_sources)
    high_risk_candidates, allied_candidates, partner_candidates = build_replay_candidates(hosted_names)

    if len(new_us_candidates) < 750:
        raise RuntimeError(f"Need at least 750 new US candidates, found {len(new_us_candidates)}")
    if len(high_risk_candidates) < 100:
        raise RuntimeError(f"Need at least 100 high-risk replay candidates, found {len(high_risk_candidates)}")
    allied_partner_candidates = allied_candidates + partner_candidates
    if len(allied_partner_candidates) < 150:
        raise RuntimeError(f"Need at least 150 allied/partner replay candidates, found {len(allied_partner_candidates)}")

    anchors = slice_bucket(
        new_us_candidates[:350],
        350,
        "create_us_anchor",
        "create",
        "new US exhibitor or prime-style anchor for graph expansion",
    )
    suppliers = slice_bucket(
        new_us_candidates[350:600],
        250,
        "create_us_supplier",
        "create",
        "new US supplier or sub-tier defense company for graph edge growth",
    )
    reserve = slice_bucket(
        new_us_candidates[600:750],
        150,
        "create_us_reserve",
        "create",
        "new US reserve slot to fill the overnight queue with vetted defense exhibitors",
    )
    high_risk = slice_bucket(
        high_risk_candidates,
        100,
        "replay_high_risk_foreign",
        "replay",
        "existing high-risk foreign defense entity replay to stress sanctions and network-risk paths",
    )
    allied = slice_bucket(
        allied_partner_candidates,
        150,
        "replay_allied_partner_foreign",
        "replay",
        "existing allied or partner foreign defense replay to deepen cross-border graph context",
    )

    cohort = anchors + suppliers + high_risk + allied + reserve
    if len(cohort) != 1000:
        raise RuntimeError(f"Cohort length mismatch: expected 1000, got {len(cohort)}")

    summary = {
        "date": date_slug,
        "hosted_vendor_count": len(hosted_names),
        "new_us_candidate_pool": len(new_us_candidates),
        "high_risk_replay_pool": len(high_risk_candidates),
        "allied_replay_pool": len(allied_candidates),
        "partner_replay_pool": len(partner_candidates),
        "bucket_counts": Counter(candidate.bucket for candidate in cohort),
    }
    return cohort, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Helios 1000-entity overnight training cohort")
    parser.add_argument("--hosted-vendors-file", type=Path, default=HOSTED_VENDORS_FILE)
    parser.add_argument("--refresh-public-sources", action="store_true")
    parser.add_argument("--date-slug", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    cohort, summary = build_cohort(
        hosted_vendor_file=args.hosted_vendors_file,
        refresh_public_sources=args.refresh_public_sources,
        date_slug=args.date_slug,
    )
    csv_path, json_path, md_path = write_cohort_files(cohort, args.date_slug)

    print(f"Built {len(cohort)} cohort rows")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    print(f"MD: {md_path}")
    print("Summary:", json.dumps(summary, default=lambda obj: dict(obj), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
