#!/usr/bin/env python3
"""
Ingest international defense exhibitors into Helios.

Default behavior:
  1. Create a case for each fixture record
  2. Run the local fixture connector to seed provenance into the enrichment
     report contract and knowledge graph

Optional behavior:
  3. `--enrich` runs the broader live connector pass after the local fixture pass
"""

from __future__ import annotations

import argparse
import os
import time

import requests

from international_exhibitors import (
    load_defense_companies,
    load_exhibitor_dataset,
    normalize_exhibitor_name,
)


API_BASE = (
    os.environ.get("HELIOS_BASE_URL")
    or os.environ.get("HELIOS_HOST")
    or "http://127.0.0.1:8080"
).rstrip("/")
FIXTURE_CONNECTORS = ["international_exhibitors_fixture"]

# Map 2-letter ISO codes to full country names for Helios
COUNTRY_MAP = {
    "US": "US",
    "CN": "China",
    "RU": "Russia",
    "IN": "India",
    "TR": "Turkey",
    "FR": "France",
    "GB": "United Kingdom",
    "DE": "Germany",
    "KR": "South Korea",
    "IL": "Israel",
    "AE": "UAE",
    "IT": "Italy",
    "JP": "Japan",
    "SA": "Saudi Arabia",
    "ES": "Spain",
    "SE": "Sweden",
    "NL": "Netherlands",
    "AU": "Australia",
    "BR": "Brazil",
    "PK": "Pakistan",
    "ZA": "South Africa",
    "SG": "Singapore",
    "NO": "Norway",
    "FI": "Finland",
    "PL": "Poland",
    "CZ": "Czech Republic",
    "RO": "Romania",
    "UA": "Ukraine",
    "BY": "Belarus",
    "CA": "Canada",
    "BE": "Belgium",
    "AT": "Austria",
    "CH": "Switzerland",
    "GR": "Greece",
    "PT": "Portugal",
    "DK": "Denmark",
    "EG": "Egypt",
    "JO": "Jordan",
    "MY": "Malaysia",
    "TH": "Thailand",
    "VN": "Vietnam",
    "ID": "Indonesia",
    "PH": "Philippines",
    "TW": "Taiwan",
    "MX": "Mexico",
    "AR": "Argentina",
    "CL": "Chile",
    "CO": "Colombia",
    "KW": "Kuwait",
    "QA": "Qatar",
    "BH": "Bahrain",
    "OM": "Oman",
    "RS": "Serbia",
    "HR": "Croatia",
    "BG": "Bulgaria",
    "SK": "Slovakia",
    "LT": "Lithuania",
    "LV": "Latvia",
    "EE": "Estonia",
    "IR": "Iran",
    "IQ": "Iraq",
    "NG": "Nigeria",
}

# Programs for different country risk profiles
PROGRAM_MAP = {
    "CN": "defense_acquisition",
    "RU": "defense_acquisition",
    "IR": "defense_acquisition",
    "BY": "defense_acquisition",
    "KP": "defense_acquisition",
    "PK": "defense_acquisition",
    "TR": "defense_acquisition",
    "IL": "defense_acquisition",
    "SA": "defense_acquisition",
    "AE": "defense_acquisition",
    "IN": "defense_acquisition",
    "KR": "defense_acquisition",
    "US": "standard_industrial",
    "GB": "standard_industrial",
    "FR": "standard_industrial",
    "DE": "standard_industrial",
    "AU": "standard_industrial",
    "CA": "standard_industrial",
    "JP": "standard_industrial",
}


def get_token() -> str:
    existing_token = os.environ.get("HELIOS_TOKEN", "").strip()
    if existing_token:
        return existing_token

    login_email = (os.environ.get("HELIOS_LOGIN_EMAIL") or os.environ.get("HELIOS_EMAIL") or "").strip()
    login_password = (os.environ.get("HELIOS_LOGIN_PASSWORD") or os.environ.get("HELIOS_PASSWORD") or "").strip()
    if not login_email or not login_password:
        raise RuntimeError(
            "Set HELIOS_TOKEN or HELIOS_LOGIN_EMAIL/HELIOS_LOGIN_PASSWORD before running a live ingest."
        )

    resp = requests.post(
        f"{API_BASE}/api/auth/login",
        json={"email": login_email, "password": login_password},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def get_existing_vendors(token: str) -> set[str]:
    """Get existing vendor names to avoid duplicates."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{API_BASE}/api/cases", params={"limit": 5000}, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    cases = data if isinstance(data, list) else data.get("cases", [])
    return {
        normalize_exhibitor_name(c.get("vendor_name", c.get("name", "")))
        for c in cases
        if c.get("vendor_name") or c.get("name")
    }


def build_case_payload(company: dict) -> dict:
    """Build the case-create payload from a fixture record."""
    country = company["country"]
    return {
        "name": company["name"],
        "country": country,
        "program": PROGRAM_MAP.get(country, "defense_acquisition"),
        "profile": "defense_acquisition",
    }


def build_fixture_enrich_payload() -> dict:
    """Use the replayable local fixture to seed graph ingest and provenance."""
    return {"connectors": list(FIXTURE_CONNECTORS)}


def build_live_enrich_payload(connectors_arg: str | None) -> dict:
    if not connectors_arg:
        return {}
    connectors = [item.strip() for item in connectors_arg.split(",") if item.strip()]
    return {"connectors": connectors} if connectors else {}


def create_case(token: str, company: dict):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return requests.post(
        f"{API_BASE}/api/cases",
        json=build_case_payload(company),
        headers=headers,
        timeout=30,
    )


def enrich_case(token: str, case_id: str, payload: dict):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return requests.post(
        f"{API_BASE}/api/cases/{case_id}/enrich-and-score",
        json=payload,
        headers=headers,
        timeout=120,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest international exhibitors into Helios")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not create cases")
    parser.add_argument("--country", type=str, help="Comma-separated country codes to filter (for example CN,RU,TR)")
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Run the broader live connector pass after the local fixture graph-seed pass",
    )
    parser.add_argument(
        "--connectors",
        type=str,
        help="Comma-separated connector names for the optional live enrichment pass",
    )
    parser.add_argument(
        "--no-fixture-enrich",
        action="store_true",
        help="Skip the local fixture connector pass that seeds provenance into the knowledge graph",
    )
    parser.add_argument("--batch-size", type=int, default=25, help="Cases per batch (API rate limit is 30/min)")
    parser.add_argument(
        "--skip-existing",
        dest="skip_existing",
        action="store_true",
        default=True,
        help="Skip vendors already in Helios (default)",
    )
    parser.add_argument(
        "--include-existing",
        dest="skip_existing",
        action="store_false",
        help="Attempt ingest even if a matching case already exists",
    )
    args = parser.parse_args()

    dataset = load_exhibitor_dataset()
    companies = load_defense_companies()
    if args.country:
        codes = {code.strip().upper() for code in args.country.split(",") if code.strip()}
        companies = [company for company in companies if company["country"] in codes]
        print(f"Filtered to {len(companies)} companies from: {', '.join(sorted(codes))}")
    else:
        print(
            f"Dataset {dataset['dataset_id']} v{dataset['version']}: "
            f"{len(companies)} companies from {len({c['country'] for c in companies})} countries"
        )

    if args.dry_run:
        print("\n[DRY RUN] Would create the following cases:")
        from collections import Counter

        by_country = Counter(company["country"] for company in companies)
        for code, count in by_country.most_common():
            name = COUNTRY_MAP.get(code, code)
            print(f"  {code} ({name}): {count} companies")
        print(f"\nTotal: {len(companies)} fixture-backed vendor cases")
        return

    print("Authenticating with Helios API...")
    token = get_token()

    existing = set()
    if args.skip_existing:
        print("Fetching existing vendors...")
        existing = get_existing_vendors(token)
        print(f"Found {len(existing)} existing vendors")

    to_create = []
    skipped = 0
    for company in companies:
        if normalize_exhibitor_name(company["name"]) in existing:
            skipped += 1
        else:
            to_create.append(company)

    print(f"Will create {len(to_create)} new cases ({skipped} already exist)")
    if not to_create:
        print("Nothing to do!")
        return

    created = 0
    failed = 0
    fixture_seeded = 0
    enriched = 0
    batch_size = args.batch_size
    total = len(to_create)
    live_payload = build_live_enrich_payload(args.connectors)
    fixture_payload = build_fixture_enrich_payload()

    for i in range(0, total, batch_size):
        batch = to_create[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size
        print(f"\n--- Batch {batch_num}/{total_batches} ({len(batch)} companies) ---")

        for company in batch:
            country_name = COUNTRY_MAP.get(company["country"], company["country"])
            try:
                resp = create_case(token, company)
                if resp.status_code == 429:
                    print("  ! Rate limited. Waiting 60s...")
                    time.sleep(60)
                    token = get_token()
                    resp = create_case(token, company)

                if resp.status_code != 201:
                    print(f"  X {company['name']}: {resp.status_code} {resp.text[:100]}")
                    failed += 1
                    continue

                data = resp.json()
                case_id = data.get("case_id", "?")
                score = data.get("composite_score", "?")
                tier = data.get("calibrated", {}).get("combined_tier", "?")
                print(f"  + {company['name']} ({country_name}): score={score}, tier={tier}")
                created += 1

                if not args.no_fixture_enrich:
                    try:
                        fixture_resp = enrich_case(token, case_id, fixture_payload)
                        if fixture_resp.status_code in (200, 201, 202):
                            fixture_seeded += 1
                        else:
                            print(
                                f"    [fixture enrich failed: {fixture_resp.status_code} "
                                f"{fixture_resp.text[:100]}]"
                            )
                    except Exception as exc:
                        print(f"    [fixture enrich failed: {type(exc).__name__}: {exc}]")

                if args.enrich:
                    try:
                        enrich_resp = enrich_case(token, case_id, live_payload)
                        if enrich_resp.status_code in (200, 201, 202):
                            enriched += 1
                        else:
                            print(
                                f"    [live enrich failed: {enrich_resp.status_code} "
                                f"{enrich_resp.text[:100]}]"
                            )
                    except Exception as exc:
                        print(f"    [live enrich failed: {type(exc).__name__}: {exc}]")

            except Exception as exc:
                print(f"  X {company['name']}: {type(exc).__name__}: {exc}")
                failed += 1

        if i + batch_size < total:
            wait = 65
            print(f"  Waiting {wait}s for rate limit reset...")
            time.sleep(wait)

    print(f"\n{'=' * 60}")
    print("INGEST COMPLETE")
    print(f"  Created:        {created}")
    print(f"  Failed:         {failed}")
    print(f"  Skipped:        {skipped}")
    if not args.no_fixture_enrich:
        print(f"  Fixture seeded: {fixture_seeded}")
    if args.enrich:
        print(f"  Live enriched:  {enriched}")
    print(f"  Total in Helios: {len(existing) + created}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
