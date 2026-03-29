"""Replayable local fixture connector for international defense exhibitors."""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from . import EnrichmentResult, Finding


SOURCE_NAME = "international_exhibitors_fixture"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "international_exhibitors"
    / "world_defense_exhibitors_2026.json"
)
HIGH_RISK_COUNTRIES = {"CN", "RU", "IR", "KP", "BY"}
ELEVATED_COUNTRIES = {"TR", "PK", "SA", "AE", "IN"}


def _normalize_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", (name or "").upper()).strip()


@lru_cache(maxsize=1)
def _load_dataset() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _find_company(vendor_name: str, country: str) -> dict | None:
    dataset = _load_dataset()
    normalized = _normalize_name(vendor_name)
    country_code = (country or "").strip().upper()
    for company in dataset.get("companies", []):
        if _normalize_name(company.get("name", "")) != normalized:
            continue
        if country_code and company.get("country", "").upper() != country_code:
            continue
        return company
    return None


def _severity(country: str) -> str:
    cc = (country or "").strip().upper()
    if cc in HIGH_RISK_COUNTRIES:
        return "high"
    if cc in ELEVATED_COUNTRIES:
        return "medium"
    return "info"


def _confidence(country: str) -> float:
    cc = (country or "").strip().upper()
    if cc in HIGH_RISK_COUNTRIES:
        return 0.94
    if cc in ELEVATED_COUNTRIES:
        return 0.9
    return 0.86


def enrich(vendor_name: str, country: str = "", **_ids) -> EnrichmentResult:
    started = time.perf_counter()
    dataset = _load_dataset()
    company = _find_company(vendor_name, country)

    if not company:
        return EnrichmentResult(
            source=SOURCE_NAME,
            vendor_name=vendor_name,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            source_class="analyst_fixture",
            authority_level="analyst_curated_fixture",
            access_model="local_json_fixture",
            structured_fields={"dataset_id": dataset.get("dataset_id", "")},
        )

    country_code = company.get("country", "")
    sectors = list(company.get("sectors", []) or [])
    compiled_from = list((dataset.get("provenance") or {}).get("compiled_from", []))
    detail = (
        f"{company['name']} appears in the Helios international defense exhibitor fixture "
        f"for {country_code or 'unknown country'} with sectors: {', '.join(sectors) or 'unspecified'}."
    )

    relationships = [
        {
            "type": "mentioned_with",
            "source_entity": company["name"],
            "target_entity": event_name,
            "entity_type": "trade_show_event",
            "data_source": SOURCE_NAME,
            "confidence": 0.92,
            "evidence": f"Analyst-curated exhibitor fixture references {event_name}",
        }
        for event_name in compiled_from[:3]
    ]

    confidence = _confidence(country_code)
    finding = Finding(
        source=SOURCE_NAME,
        category="trade_show_presence",
        title="Listed in international defense exhibitor fixture",
        detail=detail,
        severity=_severity(country_code),
        confidence=confidence,
        raw_data={
            "dataset_id": dataset.get("dataset_id", ""),
            "dataset_version": dataset.get("version", ""),
            "record_id": company.get("record_id", ""),
            "country": country_code,
            "sectors": sectors,
            "compiled_from": compiled_from,
            "company_provenance": company.get("provenance", {}),
            "dataset_provenance": dataset.get("provenance", {}),
        },
        source_class="analyst_fixture",
        authority_level="analyst_curated_fixture",
        access_model="local_json_fixture",
        structured_fields={
            "dataset_id": dataset.get("dataset_id", ""),
            "record_id": company.get("record_id", ""),
            "country": country_code,
            "sector_count": len(sectors),
        },
    )

    risk_signals = [
        {
            "signal": "international_defense_exhibitor",
            "source": SOURCE_NAME,
            "severity": _severity(country_code),
            "confidence": confidence,
            "country": country_code,
            "record_id": company.get("record_id", ""),
            "summary": detail,
        }
    ]

    return EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        findings=[finding],
        identifiers={
            "exhibitor_record_id": company.get("record_id", ""),
            "exhibitor_dataset_id": dataset.get("dataset_id", ""),
        },
        relationships=relationships,
        risk_signals=risk_signals,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        source_class="analyst_fixture",
        authority_level="analyst_curated_fixture",
        access_model="local_json_fixture",
        structured_fields={
            "dataset_id": dataset.get("dataset_id", ""),
            "record_id": company.get("record_id", ""),
            "country": country_code,
        },
    )
