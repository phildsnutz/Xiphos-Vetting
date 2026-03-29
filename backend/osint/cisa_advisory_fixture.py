"""Replayable CISA advisory fixture for shared threat-intel context."""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from . import EnrichmentResult, Finding


SOURCE_NAME = "cisa_advisory_fixture"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "standards"
    / "cisa_advisory_fixture.json"
)


def _normalize_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", (name or "").upper()).strip()


@lru_cache(maxsize=1)
def _load_dataset() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _find_record(vendor_name: str, country: str) -> dict | None:
    normalized = _normalize_name(vendor_name)
    country_code = (country or "").strip().upper()
    for record in _load_dataset().get("records", []):
        if _normalize_name(record.get("name", "")) != normalized:
            continue
        if country_code and (record.get("country", "") or "").upper() != country_code:
            continue
        return record
    return None


def enrich(vendor_name: str, country: str = "", **_ids) -> EnrichmentResult:
    started = time.perf_counter()
    dataset = _load_dataset()
    record = _find_record(vendor_name, country)
    if not record:
        return EnrichmentResult(
            source=SOURCE_NAME,
            vendor_name=vendor_name,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            source_class="analyst_fixture",
            authority_level="official_regulatory",
            access_model="local_json_fixture",
            structured_fields={"dataset_id": dataset.get("dataset_id", "")},
        )

    advisories = list(record.get("advisories", []) or [])
    advisory_ids = [str(item.get("advisory_id") or "") for item in advisories if str(item.get("advisory_id") or "").strip()]
    titles = [str(item.get("title") or "") for item in advisories if str(item.get("title") or "").strip()]
    technique_ids = sorted(
        {
            str(technique_id)
            for item in advisories
            for technique_id in (item.get("technique_ids") or [])
            if str(technique_id).strip()
        }
    )
    sectors = sorted(
        {
            str(sector)
            for item in advisories
            for sector in (item.get("sectors") or [])
            if str(sector).strip()
        }
    )
    mitigation_focus = sorted(
        {
            str(mitigation)
            for item in advisories
            for mitigation in (item.get("mitigations") or [])
            if str(mitigation).strip()
        }
    )
    ioc_types = sorted(
        {
            str(ioc_type)
            for item in advisories
            for ioc_type in (item.get("ioc_types") or [])
            if str(ioc_type).strip()
        }
    )

    findings = [
        Finding(
            source=SOURCE_NAME,
            category="threat_intelligence",
            title="CISA advisory context matched",
            detail=(
                f"{vendor_name} matched {len(advisories)} replayable CISA advisory records with "
                f"{len(technique_ids)} mapped techniques and {len(mitigation_focus)} mitigation themes."
            ),
            severity="medium" if advisories else "low",
            confidence=0.86,
            raw_data={
                "dataset_id": dataset.get("dataset_id", ""),
                "record_id": record.get("record_id", ""),
                "advisory_ids": advisory_ids,
            },
            artifact_ref=f"fixture://{dataset.get('dataset_id', '')}/{record.get('record_id', '')}",
            structured_fields={
                "dataset_id": dataset.get("dataset_id", ""),
                "record_id": record.get("record_id", ""),
                "summary": {
                    "advisory_ids": advisory_ids,
                    "advisory_titles": titles,
                    "technique_ids": technique_ids,
                    "sectors": sectors,
                    "mitigations": mitigation_focus,
                    "ioc_types": ioc_types,
                },
            },
            source_class="analyst_fixture",
            authority_level="official_regulatory",
            access_model="local_json_fixture",
        )
    ]

    return EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        findings=findings,
        risk_signals=[
            {
                "signal": "cisa_advisory_context_present",
                "source": SOURCE_NAME,
                "severity": "medium" if advisories else "low",
                "confidence": 0.86,
                "summary": f"{len(advisories)} CISA advisory records mapped to {vendor_name}",
                "record_id": record.get("record_id", ""),
            }
        ],
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        source_class="analyst_fixture",
        authority_level="official_regulatory",
        access_model="local_json_fixture",
        artifact_refs=[f"fixture://{dataset.get('dataset_id', '')}/{record.get('record_id', '')}"],
        structured_fields={
            "dataset_id": dataset.get("dataset_id", ""),
            "record_id": record.get("record_id", ""),
            "summary": {
                "advisory_ids": advisory_ids,
                "advisory_titles": titles,
                "technique_ids": technique_ids,
                "sectors": sectors,
                "mitigations": mitigation_focus,
                "ioc_types": ioc_types,
            },
        },
    )
