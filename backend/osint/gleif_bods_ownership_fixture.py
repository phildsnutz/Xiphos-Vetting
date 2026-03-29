"""Replayable standards-backed ownership fixture using GLEIF Level 2 and BODS semantics."""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from . import EnrichmentResult, Finding


SOURCE_NAME = "gleif_bods_ownership_fixture"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "standards"
    / "ownership_control_fixture.json"
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


def _ownership_relationship(
    vendor_name: str,
    record: dict,
    *,
    rel_type: str,
    target: dict,
    evidence: str,
    confidence: float,
) -> dict:
    return {
        "type": rel_type,
        "source_entity": vendor_name,
        "source_entity_type": "company",
        "source_identifiers": {"lei": record.get("lei", "")},
        "target_entity": target.get("name", ""),
        "target_entity_type": target.get("entity_type", "holding_company"),
        "target_identifiers": target.get("identifiers", {}) or {},
        "country": target.get("country", record.get("country", "")),
        "data_source": SOURCE_NAME,
        "confidence": confidence,
        "evidence": evidence,
        "observed_at": record.get("observed_at", ""),
        "valid_from": record.get("valid_from", ""),
        "artifact_ref": f"fixture://{_load_dataset().get('dataset_id', '')}/{record.get('record_id', '')}",
        "evidence_title": "Standards-backed ownership path",
        "structured_fields": {
            "standards": list(_load_dataset().get("standards", []) or []),
            "record_id": record.get("record_id", ""),
        },
        "source_class": "analyst_fixture",
        "authority_level": "standards_modeled_fixture",
        "access_model": "local_json_fixture",
    }


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

    relationships: list[dict] = []
    direct_parent = record.get("direct_parent") or {}
    if direct_parent.get("name"):
        relationships.append(
            _ownership_relationship(
                vendor_name,
                record,
                rel_type="owned_by",
                target=direct_parent,
                evidence="GLEIF Level 2 direct parent relationship modeled in local standards fixture",
                confidence=0.93,
            )
        )

    ultimate_parent = record.get("ultimate_parent") or {}
    if ultimate_parent.get("name"):
        relationships.append(
            _ownership_relationship(
                vendor_name,
                record,
                rel_type="beneficially_owned_by",
                target=ultimate_parent,
                evidence="GLEIF Level 2 ultimate parent relationship modeled in local standards fixture",
                confidence=0.91,
            )
        )

    for owner in record.get("beneficial_owners", []) or []:
        pct = owner.get("ownership_pct")
        relationships.append(
            _ownership_relationship(
                vendor_name,
                record,
                rel_type="beneficially_owned_by",
                target=owner,
                evidence=f"BODS-style beneficial ownership statement modeled at {pct}% ownership" if pct else "BODS-style beneficial ownership statement modeled in local fixture",
                confidence=0.89,
            )
        )

    for control in record.get("control_path", []) or []:
        relationships.append(
            {
                "type": control.get("type", "related_entity"),
                "source_entity": vendor_name,
                "source_entity_type": "company",
                "source_identifiers": {"lei": record.get("lei", "")},
                "target_entity": control.get("target_entity", ""),
                "target_entity_type": control.get("target_entity_type", "company"),
                "country": control.get("country", record.get("country", "")),
                "data_source": SOURCE_NAME,
                "confidence": 0.82,
                "evidence": control.get("evidence", "Standards-backed control-path relationship modeled in local fixture"),
                "observed_at": record.get("observed_at", ""),
                "valid_from": record.get("valid_from", ""),
                "artifact_ref": f"fixture://{dataset.get('dataset_id', '')}/{record.get('record_id', '')}",
                "evidence_title": "Standards-backed control-path relationship",
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
            category="ownership",
            title="Standards-backed ownership path modeled",
            detail=(
                f"{vendor_name} matched the Helios ownership fixture using {', '.join(dataset.get('standards', []) or [])}. "
                f"Direct parent, beneficial ownership, and control-path relationships were modeled for graph ingestion."
            ),
            severity="medium",
            confidence=0.9,
            raw_data={
                "dataset_id": dataset.get("dataset_id", ""),
                "record_id": record.get("record_id", ""),
                "direct_parent": direct_parent,
                "ultimate_parent": ultimate_parent,
                "beneficial_owners": record.get("beneficial_owners", []),
            },
            artifact_ref=f"fixture://{dataset.get('dataset_id', '')}/{record.get('record_id', '')}",
            structured_fields={
                "dataset_id": dataset.get("dataset_id", ""),
                "record_id": record.get("record_id", ""),
                "standard_count": len(dataset.get("standards", []) or []),
            },
            source_class="analyst_fixture",
            authority_level="standards_modeled_fixture",
            access_model="local_json_fixture",
        )
    ]

    identifiers = {"lei": record.get("lei", ""), "ownership_fixture_record_id": record.get("record_id", "")}
    risk_signals = [
        {
            "signal": "ownership_control_path_modeled",
            "source": SOURCE_NAME,
            "severity": "medium",
            "confidence": 0.9,
            "summary": f"Ownership and control-path edges modeled for {vendor_name}",
            "record_id": record.get("record_id", ""),
        }
    ]

    return EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        findings=findings,
        identifiers=identifiers,
        relationships=relationships,
        risk_signals=risk_signals,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        source_class="analyst_fixture",
        authority_level="standards_modeled_fixture",
        access_model="local_json_fixture",
        artifact_refs=[f"fixture://{dataset.get('dataset_id', '')}/{record.get('record_id', '')}"],
        structured_fields={"dataset_id": dataset.get("dataset_id", ""), "record_id": record.get("record_id", "")},
    )
