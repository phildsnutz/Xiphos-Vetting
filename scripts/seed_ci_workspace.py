#!/usr/bin/env python3
"""Seed a deterministic auth user and smoke case for CI jobs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import db  # type: ignore
from auth import create_user, init_auth_db, list_users  # type: ignore
from server import _score_and_persist  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Helios CI auth and case data.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="CI Admin")
    parser.add_argument("--case-id", default="ci-seeded-case")
    parser.add_argument("--vendor-name", default="CI SEEDED EXPORT CASE")
    parser.add_argument("--country", default="US")
    return parser.parse_args()


def ensure_user(email: str, password: str, name: str) -> None:
    init_auth_db()
    existing = next((user for user in list_users() if user.get("email", "").lower() == email.lower()), None)
    if existing:
        print(f"CI user already present: {email}")
        return
    create_user(email, password, name=name, role="admin", must_change_password=False)
    print(f"Created CI user: {email}")


def ensure_case(case_id: str, vendor_name: str, country: str) -> None:
    existing = db.get_vendor(case_id)
    if existing:
        print(f"CI case already present: {case_id}")
        return

    vendor = {
        "id": case_id,
        "name": vendor_name,
        "country": country,
        "ownership": {
            "publicly_traded": True,
            "state_owned": False,
            "beneficial_owner_known": True,
            "ownership_pct_resolved": 0.92,
            "shell_layers": 0,
            "pep_connection": False,
        },
        "data_quality": {
            "has_lei": True,
            "has_cage": True,
            "has_duns": True,
            "has_tax_id": True,
            "has_audited_financials": True,
            "years_of_records": 12,
        },
        "exec": {
            "known_execs": 8,
            "adverse_media": 0,
            "pep_execs": 0,
            "litigation_history": 0,
        },
        "program": "dod_unclassified",
        "profile": "defense_acquisition",
        "export_authorization": {
            "request_type": "item_transfer",
            "recipient_name": "CI Meridian UK Ltd",
            "destination_country": "GB",
            "jurisdiction_guess": "ear",
            "classification_guess": "3A001",
            "item_or_data_summary": "Seeded CI export-control transaction",
            "end_use_summary": "Integration test validation",
            "access_context": "CI harness workspace",
            "foreign_person_nationalities": ["GB"],
        },
    }

    _score_and_persist(case_id, vendor)
    print(f"Created CI case: {case_id}")


def main() -> int:
    args = parse_args()
    db.init_db()
    ensure_user(args.email, args.password, args.name)
    ensure_case(args.case_id, args.vendor_name, args.country)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
