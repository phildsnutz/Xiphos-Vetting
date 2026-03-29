"""Fixture-backed international defense exhibitor dataset helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path


FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "international_exhibitors"
    / "world_defense_exhibitors_2026.json"
)


def normalize_exhibitor_name(name: str) -> str:
    """Normalize names for fixture lookup and ingest dedup."""
    return re.sub(r"[^A-Z0-9]+", " ", (name or "").upper()).strip()


def load_exhibitor_dataset(path: Path = FIXTURE_PATH) -> dict:
    """Load the full provenance-backed dataset."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_defense_companies(path: Path = FIXTURE_PATH) -> list[dict]:
    """Load just the exhibitor records."""
    return list(load_exhibitor_dataset(path).get("companies", []))


def find_exhibitor(name: str, country: str = "", path: Path = FIXTURE_PATH) -> dict | None:
    """Lookup a single exhibitor by normalized name and optional country."""
    normalized = normalize_exhibitor_name(name)
    country_code = (country or "").strip().upper()
    for company in load_defense_companies(path):
        if normalize_exhibitor_name(company.get("name", "")) != normalized:
            continue
        if country_code and company.get("country", "").upper() != country_code:
            continue
        return company
    return None


# Backward-compatible export used by existing ingest scripts.
defense_companies = load_defense_companies()
