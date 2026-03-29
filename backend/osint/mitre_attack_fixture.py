"""Replayable MITRE ATT&CK fixture for shared threat-intel context."""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from . import EnrichmentResult, Finding


SOURCE_NAME = "mitre_attack_fixture"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "standards"
    / "mitre_attack_fixture.json"
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
            authority_level="third_party_public",
            access_model="local_json_fixture",
            structured_fields={"dataset_id": dataset.get("dataset_id", "")},
        )

    summary = dict(record.get("summary") or {})
    techniques = list(summary.get("techniques", []) or [])
    technique_ids = [str(item.get("id") or "") for item in techniques if str(item.get("id") or "").strip()]
    tactic_names = sorted(
        {
            str(item.get("tactic") or "").strip()
            for item in techniques
            if str(item.get("tactic") or "").strip()
        }
    )
    actor_families = [str(item) for item in (summary.get("actor_families") or []) if str(item).strip()]
    campaigns = [str(item) for item in (summary.get("campaigns") or []) if str(item).strip()]

    findings = [
        Finding(
            source=SOURCE_NAME,
            category="threat_intelligence",
            title="ATT&CK threat patterns mapped",
            detail=(
                f"{vendor_name} matched replayable ATT&CK threat context with "
                f"{len(actor_families)} actor families, {len(technique_ids)} techniques, and {len(campaigns)} campaigns."
            ),
            severity="medium" if technique_ids else "low",
            confidence=0.82,
            raw_data={
                "dataset_id": dataset.get("dataset_id", ""),
                "record_id": record.get("record_id", ""),
                "technique_ids": technique_ids,
            },
            artifact_ref=f"fixture://{dataset.get('dataset_id', '')}/{record.get('record_id', '')}",
            structured_fields={
                "dataset_id": dataset.get("dataset_id", ""),
                "record_id": record.get("record_id", ""),
                "summary": {
                    "actor_families": actor_families,
                    "campaigns": campaigns,
                    "technique_ids": technique_ids,
                    "techniques": techniques,
                    "tactics": tactic_names,
                    "references": list(summary.get("references", []) or []),
                },
            },
            source_class="analyst_fixture",
            authority_level="third_party_public",
            access_model="local_json_fixture",
        )
    ]

    return EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        findings=findings,
        risk_signals=[
            {
                "signal": "attack_threat_pattern_present",
                "source": SOURCE_NAME,
                "severity": "medium" if technique_ids else "low",
                "confidence": 0.82,
                "summary": f"{len(technique_ids)} ATT&CK techniques mapped to {vendor_name}",
                "record_id": record.get("record_id", ""),
            }
        ],
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        source_class="analyst_fixture",
        authority_level="third_party_public",
        access_model="local_json_fixture",
        artifact_refs=[f"fixture://{dataset.get('dataset_id', '')}/{record.get('record_id', '')}"],
        structured_fields={
            "dataset_id": dataset.get("dataset_id", ""),
            "record_id": record.get("record_id", ""),
            "summary": {
                "actor_families": actor_families,
                "campaigns": campaigns,
                "technique_ids": technique_ids,
                "techniques": techniques,
                "tactics": tactic_names,
                "references": list(summary.get("references", []) or []),
            },
        },
    )
