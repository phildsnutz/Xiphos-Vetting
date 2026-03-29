"""Replayable first-party public assurance evidence fixture for the Supply Chain Assurance lane."""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from . import EnrichmentResult, Finding


SOURCE_NAME = "public_assurance_evidence_fixture"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "standards"
    / "public_assurance_evidence_fixture.json"
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
            authority_level="first_party_self_disclosed",
            access_model="local_json_fixture",
            structured_fields={"dataset_id": dataset.get("dataset_id", "")},
        )

    summary = dict(record.get("summary") or {})
    artifact_urls = [str(url) for url in (record.get("artifact_urls") or []) if str(url).strip()]
    artifact_kinds = [str(kind) for kind in (summary.get("artifact_kinds") or []) if str(kind).strip()]
    package_inventory = [
        dict(item)
        for item in (record.get("package_inventory") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    repository_urls = [
        str(url)
        for url in (record.get("repository_urls") or [])
        if str(url).strip()
    ]
    summary["artifact_urls"] = artifact_urls
    summary["artifact_kinds"] = artifact_kinds
    summary["public_artifact_count"] = len(artifact_urls)
    summary["package_inventory_count"] = len(package_inventory)
    summary["repository_count"] = len(repository_urls)

    artifact_ref = f"fixture://{dataset.get('dataset_id', '')}/{record.get('record_id', '')}"
    findings: list[Finding] = []

    evidence_bits = []
    if summary.get("sbom_present"):
        age = summary.get("sbom_fresh_days")
        evidence_bits.append(
            f"published {summary.get('sbom_format', 'SBOM')} SBOM"
            + (f" ({age} days old)" if age not in (None, "") else "")
        )
    if str(summary.get("vex_status") or "").lower() not in {"", "missing", "none", "unknown"}:
        evidence_bits.append(f"VEX status {summary['vex_status']}")
    if summary.get("security_txt_present"):
        evidence_bits.append("security.txt available")
    if summary.get("psirt_contact_present"):
        evidence_bits.append("PSIRT contact published")
    if summary.get("support_lifecycle_published"):
        evidence_bits.append("support lifecycle published")
    if summary.get("provenance_attested"):
        evidence_bits.append("provenance attestation disclosed")

    if evidence_bits:
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category="supply_chain_assurance",
                title="First-party public assurance evidence disclosed",
                detail=(
                    f"{vendor_name} publishes "
                    + ", ".join(evidence_bits)
                    + ". Helios can use this as first-party assurance evidence even before customer artifacts are attached."
                ),
                severity="low",
                confidence=0.86,
                raw_data={
                    "dataset_id": dataset.get("dataset_id", ""),
                    "record_id": record.get("record_id", ""),
                    "artifact_urls": artifact_urls,
                },
                artifact_ref=artifact_ref,
                structured_fields={
                    "dataset_id": dataset.get("dataset_id", ""),
                    "record_id": record.get("record_id", ""),
                    "summary": summary,
                },
                source_class="analyst_fixture",
                authority_level="first_party_self_disclosed",
                access_model="local_json_fixture",
            )
        )

    gaps = []
    if not summary.get("sbom_present"):
        gaps.append("published SBOM is missing")
    if str(summary.get("vex_status") or "").lower() in {"", "missing", "none", "unknown"}:
        gaps.append("no public VEX assertion is available")
    if not summary.get("provenance_attested"):
        gaps.append("provenance attestation is not publicly disclosed")
    if str(summary.get("secure_by_design_evidence") or "").lower() == "marketing_only":
        gaps.append("secure-by-design claims are marketing-level only")

    if gaps:
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category="supply_chain_assurance",
                title="Public assurance evidence remains incomplete",
                detail=f"{vendor_name} still has visible assurance gaps: " + "; ".join(gaps) + ".",
                severity="medium",
                confidence=0.82,
                raw_data={
                    "dataset_id": dataset.get("dataset_id", ""),
                    "record_id": record.get("record_id", ""),
                    "gaps": gaps,
                },
                artifact_ref=artifact_ref,
                structured_fields={
                    "dataset_id": dataset.get("dataset_id", ""),
                    "record_id": record.get("record_id", ""),
                    "summary": summary,
                },
                source_class="analyst_fixture",
                authority_level="first_party_self_disclosed",
                access_model="local_json_fixture",
            )
        )

    risk_signals = [
        {
            "signal": "public_assurance_evidence_present",
            "source": SOURCE_NAME,
            "severity": "low",
            "confidence": 0.86,
            "summary": f"First-party public assurance evidence disclosed for {vendor_name}",
            "record_id": record.get("record_id", ""),
        }
    ]
    if gaps:
        risk_signals.append(
            {
                "signal": "public_assurance_gap",
                "source": SOURCE_NAME,
                "severity": "medium",
                "confidence": 0.82,
                "summary": f"{len(gaps)} public assurance gaps remain visible",
                "record_id": record.get("record_id", ""),
            }
        )

    return EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        findings=findings,
        identifiers={
            "package_inventory": package_inventory,
            "repository_urls": repository_urls,
        },
        risk_signals=risk_signals,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        source_class="analyst_fixture",
        authority_level="first_party_self_disclosed",
        access_model="local_json_fixture",
        artifact_refs=[artifact_ref],
        structured_fields={
            "dataset_id": dataset.get("dataset_id", ""),
            "record_id": record.get("record_id", ""),
            "summary": summary,
        },
    )
