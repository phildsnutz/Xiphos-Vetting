"""Replayable Open Ownership BODS fixture for beneficial ownership and control paths."""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from . import EnrichmentResult, Finding


SOURCE_NAME = "openownership_bods_fixture"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "standards"
    / "openownership_bods_fixture.json"
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


def _relationship(
    record: dict,
    statement: dict,
    target: dict,
    *,
    rel_type: str,
    confidence: float,
) -> dict:
    dataset = _load_dataset()
    subject = record.get("subject") or {}
    statement_id = str(statement.get("statement_id") or "")
    record_id = str(record.get("record_id") or "")
    artifact_ref = f"fixture://{dataset.get('dataset_id', '')}/{record_id}"
    return {
        "type": rel_type,
        "source_entity": subject.get("name", record.get("name", "")),
        "source_entity_type": subject.get("entity_type", "company"),
        "source_identifiers": subject.get("identifiers", {}) or {},
        "target_entity": target.get("name", ""),
        "target_entity_type": target.get("entity_type", "holding_company"),
        "target_identifiers": target.get("identifiers", {}) or {},
        "country": target.get("country", record.get("country", "")),
        "data_source": SOURCE_NAME,
        "confidence": confidence,
        "evidence": str(statement.get("evidence") or "BODS ownership or control statement modeled in local fixture"),
        "observed_at": record.get("observed_at", ""),
        "valid_from": statement.get("valid_from", record.get("valid_from", "")),
        "artifact_ref": artifact_ref,
        "evidence_title": "Open Ownership BODS ownership statement",
        "structured_fields": {
            "standards": list(dataset.get("standards", []) or []),
            "record_id": record_id,
            "statement_id": statement_id,
            "statement_type": statement.get("statement_type", "ownershipOrControlStatement"),
            "direct_or_indirect": statement.get("direct_or_indirect", ""),
            "interests": list(statement.get("interests", []) or []),
            "beneficial_ownership_pct": statement.get("beneficial_ownership_pct"),
            "component_records": list(statement.get("component_records", []) or []),
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

    subject = record.get("subject") or {}
    statements = list(record.get("statements", []) or [])
    direct_count = 0
    indirect_count = 0
    relationships: list[dict] = []

    for statement in statements:
        target = statement.get("interested_party") or {}
        if not target.get("name"):
            continue
        direct = str(statement.get("direct_or_indirect") or "").lower() == "direct"
        rel_type = "owned_by" if direct else "beneficially_owned_by"
        confidence = 0.92 if direct else 0.88
        relationships.append(
            _relationship(
                record,
                statement,
                target,
                rel_type=rel_type,
                confidence=confidence,
            )
        )
        if direct:
            direct_count += 1
        else:
            indirect_count += 1

    findings = [
        Finding(
            source=SOURCE_NAME,
            category="ownership",
            title="Open Ownership BODS control path modeled",
            detail=(
                f"{subject.get('name', vendor_name)} matched a replayable BODS ownership fixture. "
                f"{direct_count} direct and {indirect_count} indirect ownership or control statements were normalized into graph-native relationships."
            ),
            severity="medium" if indirect_count else "low",
            confidence=0.9,
            raw_data={
                "dataset_id": dataset.get("dataset_id", ""),
                "record_id": record.get("record_id", ""),
                "statement_count": len(statements),
            },
            artifact_ref=f"fixture://{dataset.get('dataset_id', '')}/{record.get('record_id', '')}",
            structured_fields={
                "dataset_id": dataset.get("dataset_id", ""),
                "record_id": record.get("record_id", ""),
                "summary": {
                    "statement_count": len(statements),
                    "direct_statement_count": direct_count,
                    "indirect_statement_count": indirect_count,
                    "interested_parties": [
                        str((statement.get("interested_party") or {}).get("name") or "")
                        for statement in statements
                        if (statement.get("interested_party") or {}).get("name")
                    ],
                },
            },
            source_class="analyst_fixture",
            authority_level="standards_modeled_fixture",
            access_model="local_json_fixture",
        )
    ]

    identifiers = dict(subject.get("identifiers", {}) or {})
    if record.get("record_id"):
        identifiers["openownership_record_id"] = record["record_id"]

    risk_signals = [
        {
            "signal": "openownership_bods_modeled",
            "source": SOURCE_NAME,
            "severity": "medium" if indirect_count else "low",
            "confidence": 0.9,
            "summary": f"{len(statements)} BODS ownership/control statements modeled for {subject.get('name', vendor_name)}",
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
        structured_fields={
            "dataset_id": dataset.get("dataset_id", ""),
            "record_id": record.get("record_id", ""),
            "summary": {
                "statement_count": len(statements),
                "direct_statement_count": direct_count,
                "indirect_statement_count": indirect_count,
            },
        },
    )
