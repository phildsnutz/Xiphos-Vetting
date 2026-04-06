"""Replayable GAO bid protest fixture for contract-vehicle legal signals."""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from . import EnrichmentResult, Finding


SOURCE_NAME = "gao_bid_protests_fixture"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "vehicle_intelligence"
    / "gao_bid_protests_fixture.json"
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
            authority_level="official_program_system",
            access_model="local_json_fixture",
            structured_fields={"dataset_id": dataset.get("dataset_id", "")},
        )

    findings: list[Finding] = []
    for event in vehicle.get("events", []) or []:
        if not isinstance(event, dict):
            continue
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category="bid_protest",
                title=str(event.get("title") or "GAO bid protest"),
                detail=str(event.get("summary") or ""),
                severity="medium",
                confidence=float(event.get("confidence") or 0.0),
                url=str(event.get("url") or ""),
                raw_data={
                    "dataset_id": dataset.get("dataset_id", ""),
                    "vehicle_name": vehicle.get("vehicle_name", vendor_name),
                    "event_id": event.get("event_id", ""),
                    "status": event.get("status", ""),
                    "forum": event.get("forum", ""),
                    "protester": event.get("protester", ""),
                    "agency": event.get("agency", ""),
                    "decision_date": event.get("decision_date", ""),
                    "assessment": event.get("assessment", ""),
                    "summary": event.get("summary", ""),
                },
                source_class="analyst_fixture",
                authority_level="official_program_system",
                access_model="local_json_fixture",
                structured_fields={
                    "dataset_id": dataset.get("dataset_id", ""),
                    "vehicle_name": vehicle.get("vehicle_name", vendor_name),
                    "event_id": event.get("event_id", ""),
                    "status": event.get("status", ""),
                },
            )
        )

    return EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        findings=findings,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        source_class="analyst_fixture",
        authority_level="official_program_system",
        access_model="local_json_fixture",
        structured_fields={
            "dataset_id": dataset.get("dataset_id", ""),
            "vehicle_name": vehicle.get("vehicle_name", vendor_name),
            "event_count": len(findings),
        },
    )
