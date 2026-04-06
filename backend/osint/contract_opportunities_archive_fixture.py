"""Replayable archive-and-diff fixture for contract vehicle lineage signals."""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from . import EnrichmentResult, Finding


SOURCE_NAME = "contract_opportunities_archive_fixture"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "vehicle_intelligence"
    / "contract_vehicle_archive_fixture.json"
)


def _normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


@lru_cache(maxsize=1)
def _load_dataset() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _match_vehicle(vehicle_name: str) -> dict | None:
    normalized = _normalize_name(vehicle_name)
    dataset = _load_dataset()
    for vehicle in dataset.get("vehicles", []):
        names = [vehicle.get("vehicle_name", ""), *(vehicle.get("aliases") or [])]
        if any(_normalize_name(name) == normalized for name in names):
            return vehicle
    return None


def enrich(vendor_name: str, **_ids) -> EnrichmentResult:
    started = time.perf_counter()
    dataset = _load_dataset()
    vehicle = _match_vehicle(vendor_name)

    if not vehicle:
        return EnrichmentResult(
            source=SOURCE_NAME,
            vendor_name=vendor_name,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            source_class="analyst_fixture",
            authority_level="analyst_curated_fixture",
            access_model="local_json_fixture",
            structured_fields={"dataset_id": dataset.get("dataset_id", "")},
        )

    findings: list[Finding] = []
    for record in vehicle.get("findings", []) or []:
        if not isinstance(record, dict):
            continue
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category="vehicle_lineage",
                title=str(record.get("title") or "Archived lineage signal"),
                detail=str(record.get("detail") or ""),
                severity=str(record.get("severity") or "info"),
                confidence=float(record.get("confidence") or 0.0),
                raw_data={
                    "dataset_id": dataset.get("dataset_id", ""),
                    "vehicle_name": vehicle.get("vehicle_name", vendor_name),
                    "record_id": record.get("record_id", ""),
                },
                source_class="analyst_fixture",
                authority_level="analyst_curated_fixture",
                access_model="local_json_fixture",
                structured_fields={
                    "dataset_id": dataset.get("dataset_id", ""),
                    "vehicle_name": vehicle.get("vehicle_name", vendor_name),
                    "record_id": record.get("record_id", ""),
                },
            )
        )

    relationships = []
    for record in vehicle.get("records", []) or []:
        if not isinstance(record, dict):
            continue
        relationships.append(
            {
                "rel_type": str(record.get("rel_type") or ""),
                "source_name": str(record.get("source_entity") or ""),
                "target_name": str(record.get("target_entity") or ""),
                "data_source": SOURCE_NAME,
                "data_sources": [SOURCE_NAME],
                "corroboration_count": int(record.get("corroboration_count") or 1),
                "intelligence_tier": str(record.get("intelligence_tier") or "supported"),
                "evidence": str(record.get("summary") or ""),
                "evidence_summary": str(record.get("summary") or ""),
                "observed_at": str(record.get("observed_at") or ""),
                "source_urls": list(record.get("source_urls") or []),
                "source_notes": list(record.get("source_notes") or []),
                "fixture_record_id": str(record.get("record_id") or ""),
                "source_class": "analyst_fixture",
                "authority_level": "analyst_curated_fixture",
                "access_model": "local_json_fixture",
            }
        )

    return EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        findings=findings,
        relationships=relationships,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        source_class="analyst_fixture",
        authority_level="analyst_curated_fixture",
        access_model="local_json_fixture",
        structured_fields={
            "dataset_id": dataset.get("dataset_id", ""),
            "vehicle_name": vehicle.get("vehicle_name", vendor_name),
            "record_count": len(relationships),
        },
    )
