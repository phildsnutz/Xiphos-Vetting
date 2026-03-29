"""Replayable standards-backed cyber supply-chain fixture using CycloneDX, SPDX, and VEX semantics."""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from . import EnrichmentResult, Finding


SOURCE_NAME = "cyclonedx_spdx_vex_fixture"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "standards"
    / "cyber_supply_chain_fixture.json"
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
            authority_level="standards_modeled_fixture",
            access_model="local_json_fixture",
            structured_fields={"dataset_id": dataset.get("dataset_id", "")},
        )

    artifact_ref = f"fixture://{dataset.get('dataset_id', '')}/{record.get('record_id', '')}"
    relationships = []
    for rel in record.get("relationships", []) or []:
        relationships.append(
            {
                **rel,
                "data_source": SOURCE_NAME,
                "confidence": 0.9 if rel.get("type") in {"supplies_component_to", "integrated_into"} else 0.82,
                "observed_at": record.get("observed_at", ""),
                "artifact_ref": artifact_ref,
                "evidence_title": "Standards-backed cyber supply-chain relationship",
                "structured_fields": {
                    "standards": list(dataset.get("standards", []) or []),
                    "record_id": record.get("record_id", ""),
                },
                "source_class": "analyst_fixture",
                "authority_level": "standards_modeled_fixture",
                "access_model": "local_json_fixture",
            }
        )

    findings = [
        Finding(
            source=SOURCE_NAME,
            category="cyber_supply_chain",
            title="Standards-backed cyber supply-chain path modeled",
            detail=(
                f"{vendor_name} matched the Helios cyber supply-chain fixture using {', '.join(dataset.get('standards', []) or [])}. "
                "Component, subsystem, service, telecom, facility, route, and vulnerability edges were prepared for graph ingestion."
            ),
            severity="medium",
            confidence=0.9,
            raw_data={
                "dataset_id": dataset.get("dataset_id", ""),
                "record_id": record.get("record_id", ""),
                "relationship_count": len(record.get("relationships", []) or []),
                "vex_assertions": record.get("vex_assertions", []),
            },
            artifact_ref=artifact_ref,
            structured_fields={
                "dataset_id": dataset.get("dataset_id", ""),
                "record_id": record.get("record_id", ""),
                "relationship_count": len(record.get("relationships", []) or []),
            },
            source_class="analyst_fixture",
            authority_level="standards_modeled_fixture",
            access_model="local_json_fixture",
        )
    ]

    affected_assertions = [item for item in (record.get("vex_assertions", []) or []) if item.get("status") == "affected"]
    for assertion in affected_assertions:
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category="cybersecurity",
                title=f"VEX assertion: {assertion.get('product', 'unknown product')} affected by {assertion.get('cve', 'unknown CVE')}",
                detail=assertion.get("justification", "VEX fixture marks the dependency as affected."),
                severity="high",
                confidence=0.88,
                raw_data=assertion,
                artifact_ref=artifact_ref,
                structured_fields={"dataset_id": dataset.get("dataset_id", ""), "record_id": record.get("record_id", "")},
                source_class="analyst_fixture",
                authority_level="standards_modeled_fixture",
                access_model="local_json_fixture",
            )
        )

    risk_signals = [
        {
            "signal": "cyber_supply_chain_modeled",
            "source": SOURCE_NAME,
            "severity": "medium",
            "confidence": 0.9,
            "summary": f"Standards-backed cyber supply-chain path modeled for {vendor_name}",
            "record_id": record.get("record_id", ""),
        }
    ]
    if affected_assertions:
        risk_signals.append(
            {
                "signal": "vex_affected_assertion",
                "source": SOURCE_NAME,
                "severity": "high",
                "confidence": 0.88,
                "summary": f"{len(affected_assertions)} VEX assertions remain affected",
                "record_id": record.get("record_id", ""),
            }
        )

    return EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        findings=findings,
        relationships=relationships,
        risk_signals=risk_signals,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        source_class="analyst_fixture",
        authority_level="standards_modeled_fixture",
        access_model="local_json_fixture",
        artifact_refs=[artifact_ref],
        structured_fields={"dataset_id": dataset.get("dataset_id", ""), "record_id": record.get("record_id", "")},
    )
