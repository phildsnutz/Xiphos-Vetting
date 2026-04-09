"""Replayable local proximity connector for analyst-provided vehicle and teammate context."""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from . import EnrichmentResult, Finding


SOURCE_NAME = "axiom_known_proximity"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "axiom_known_proximity"
    / "mission_vehicle_proximity_v1.json"
)


def _normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


@lru_cache(maxsize=1)
def _load_dataset() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _find_record(vendor_name: str) -> dict | None:
    normalized = _normalize_name(vendor_name)
    for record in _load_dataset().get("records", []):
        candidate_names = [str(record.get("vendor_name") or "")]
        candidate_names.extend(str(alias or "") for alias in (record.get("aliases") or []))
        if any(_normalize_name(name) == normalized for name in candidate_names if name.strip()):
            return record
    return None


def _artifact_ref(dataset_id: str, record_id: str) -> str:
    return f"fixture://{dataset_id}/{record_id}"


def enrich(vendor_name: str, country: str = "", **_ids) -> EnrichmentResult:
    started = time.perf_counter()
    dataset = _load_dataset()
    record = _find_record(vendor_name)
    if not record:
        return EnrichmentResult(
            source=SOURCE_NAME,
            vendor_name=vendor_name,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            source_class="analyst_fixture",
            authority_level="analyst_curated_fixture",
            access_model="local_json_fixture",
            structured_fields={"dataset_id": dataset.get("dataset_id", "")},
        )

    dataset_id = str(dataset.get("dataset_id") or "")
    record_id = str(record.get("record_id") or "")
    confidence = float(record.get("confidence") or 0.72)
    website = str(record.get("website") or "").strip()
    cage = str(record.get("cage") or "").strip()
    prime_paths = [str(item).strip() for item in (record.get("prime_paths") or []) if str(item).strip()]
    teammate_paths = [str(item).strip() for item in (record.get("teammate_paths") or []) if str(item).strip()]
    vehicle_mentions = [str(item).strip() for item in (record.get("vehicle_mentions") or []) if str(item).strip()]
    source_note = str(record.get("source_note") or "").strip()
    artifact_ref = _artifact_ref(dataset_id, record_id)

    findings: list[Finding] = []
    if prime_paths or teammate_paths:
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category="teaming_proximity",
                title=f"Analyst proximity seed: {record.get('vendor_name') or vendor_name}",
                detail=(
                    f"{record.get('vendor_name') or vendor_name} is carried in local mission memory near "
                    f"{', '.join(teammate_paths + prime_paths)}. Treat this as analyst-curated proximity that needs official corroboration, not as a registry fact."
                ),
                severity="info",
                confidence=confidence,
                raw_data={"dataset_id": dataset_id, "record_id": record_id, "source_note": source_note},
                artifact_ref=artifact_ref,
                structured_fields={
                    "dataset_id": dataset_id,
                    "record_id": record_id,
                    "prime_paths": prime_paths,
                    "teammate_paths": teammate_paths,
                },
                source_class="analyst_fixture",
                authority_level="analyst_curated_fixture",
                access_model="local_json_fixture",
            )
        )
    if vehicle_mentions:
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category="vehicle_proximity",
                title="Analyst vehicle seed: grey-zone vehicle adjacency held",
                detail=(
                    f"{record.get('vendor_name') or vendor_name} is carried against vehicle context for "
                    f"{', '.join(vehicle_mentions)} in local mission memory. Keep this visible as a pressure clue until official support lands."
                ),
                severity="info",
                confidence=max(0.68, confidence - 0.02),
                raw_data={"dataset_id": dataset_id, "record_id": record_id, "source_note": source_note},
                artifact_ref=artifact_ref,
                structured_fields={
                    "dataset_id": dataset_id,
                    "record_id": record_id,
                    "vehicle_mentions": vehicle_mentions,
                },
                source_class="analyst_fixture",
                authority_level="analyst_curated_fixture",
                access_model="local_json_fixture",
            )
        )

    relationships: list[dict] = []
    for prime_name in prime_paths:
        relationships.append(
            {
                "type": "subcontractor_of",
                "source_entity": record.get("vendor_name") or vendor_name,
                "source_entity_type": "company",
                "target_entity": prime_name,
                "target_entity_type": "company",
                "data_source": SOURCE_NAME,
                "confidence": confidence,
                "evidence": f"{source_note} Prime-path proximity keeps {prime_name} in frame.",
                "artifact_ref": artifact_ref,
                "structured_fields": {
                    "dataset_id": dataset_id,
                    "record_id": record_id,
                    "relationship_scope": "analyst_curated_prime_path",
                },
                "source_class": "analyst_fixture",
                "authority_level": "analyst_curated_fixture",
                "access_model": "local_json_fixture",
            }
        )
    for teammate_name in teammate_paths:
        relationships.append(
            {
                "type": "teamed_with",
                "source_entity": record.get("vendor_name") or vendor_name,
                "source_entity_type": "company",
                "target_entity": teammate_name,
                "target_entity_type": "company",
                "data_source": SOURCE_NAME,
                "confidence": max(0.68, confidence - 0.02),
                "evidence": f"{source_note} Teaming proximity keeps {teammate_name} attached to the working thread.",
                "artifact_ref": artifact_ref,
                "structured_fields": {
                    "dataset_id": dataset_id,
                    "record_id": record_id,
                    "relationship_scope": "analyst_curated_teammate_path",
                },
                "source_class": "analyst_fixture",
                "authority_level": "analyst_curated_fixture",
                "access_model": "local_json_fixture",
            }
        )
    for vehicle_name in vehicle_mentions:
        relationships.append(
            {
                "type": "competed_on",
                "source_entity": record.get("vendor_name") or vendor_name,
                "source_entity_type": "company",
                "target_entity": vehicle_name,
                "target_entity_type": "contract_vehicle",
                "data_source": SOURCE_NAME,
                "confidence": max(0.66, confidence - 0.04),
                "evidence": f"{source_note} Vehicle proximity keeps {vehicle_name} in the pressure map.",
                "artifact_ref": artifact_ref,
                "structured_fields": {
                    "dataset_id": dataset_id,
                    "record_id": record_id,
                    "relationship_scope": "analyst_curated_vehicle_proximity",
                },
                "source_class": "analyst_fixture",
                "authority_level": "analyst_curated_fixture",
                "access_model": "local_json_fixture",
            }
        )

    identifiers = {}
    if website:
        identifiers["website"] = website
    if cage:
        identifiers["cage"] = cage

    return EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        findings=findings,
        identifiers=identifiers,
        relationships=relationships,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        source_class="analyst_fixture",
        authority_level="analyst_curated_fixture",
        access_model="local_json_fixture",
        artifact_refs=[artifact_ref],
        structured_fields={
            "dataset_id": dataset_id,
            "record_id": record_id,
            "prime_paths": prime_paths,
            "teammate_paths": teammate_paths,
            "vehicle_mentions": vehicle_mentions,
        },
    )
