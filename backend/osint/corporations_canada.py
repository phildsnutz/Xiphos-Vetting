"""Corporations Canada public registry connector.

This connector is intentionally local-first and provider-neutral:
it consumes a public JSON export that mirrors official federal corporation
and ISC disclosure records from Corporations Canada.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from . import EnrichmentResult, Finding


SOURCE_NAME = "corporations_canada"
USER_AGENT = "Xiphos-Vetting/2.1"


def _normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _dataset_url(ids: dict) -> str:
    for key in ("corporations_canada_url", "ca_corporations_url"):
        value = str(ids.get(key) or "").strip()
        if value:
            return value
    return str(os.environ.get("XIPHOS_CORPORATIONS_CANADA_URL") or "").strip()


def _fetch_json(url: str) -> dict | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _record_matches(record: dict, vendor_name: str, country: str, ids: dict) -> bool:
    known_corp_number = str(ids.get("ca_corporation_number") or ids.get("corporation_number") or "").strip().upper()
    known_business_number = str(ids.get("business_number") or "").strip().upper()
    record_corp_number = str(record.get("ca_corporation_number") or record.get("corporation_number") or "").strip().upper()
    record_bn = str(record.get("business_number") or "").strip().upper()
    if known_corp_number and record_corp_number == known_corp_number:
        return True
    if known_business_number and record_bn == known_business_number:
        return True
    if _normalize_name(record.get("corporation_name") or record.get("name") or "") != _normalize_name(vendor_name):
        return False
    country_code = str(country or "").strip().upper()
    if country_code and country_code not in {"CA", "CAN"}:
        return False
    return True


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    started = time.perf_counter()
    result = EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        source_class="public_connector",
        authority_level="official_registry",
        access_model="public_json",
    )

    if country and str(country).strip().upper() not in {"", "CA", "CAN"}:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    dataset_url = _dataset_url(ids)
    if not dataset_url:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    payload = _fetch_json(dataset_url)
    if not isinstance(payload, dict):
        result.error = "Unable to fetch Corporations Canada public dataset"
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    records = payload.get("records") or payload.get("corporations")
    if not isinstance(records, list):
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="corporate_identity",
                title="Corporations Canada dataset shape unsupported",
                detail=(
                    "The configured Corporations Canada public dataset does not expose a top-level "
                    "`records` or `corporations` array in the expected provider-neutral format."
                ),
                severity="info",
                confidence=0.8,
                url=dataset_url,
                raw_data={"top_level_keys": sorted(payload.keys())[:12]},
                source_class="public_connector",
                authority_level="official_registry",
                access_model="public_json",
            )
        )
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    record = next((item for item in records if isinstance(item, dict) and _record_matches(item, vendor_name, country, ids)), None)
    if not isinstance(record, dict):
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    corp_name = str(record.get("corporation_name") or record.get("name") or vendor_name).strip()
    corp_number = str(record.get("ca_corporation_number") or record.get("corporation_number") or "").strip()
    business_number = str(record.get("business_number") or "").strip()
    status = str(record.get("status") or "").strip()
    incorporation_date = str(record.get("incorporation_date") or record.get("date_of_creation") or "").strip()
    legislation = str(record.get("governing_legislation") or record.get("legislation") or "CBCA").strip()
    directors = [item for item in (record.get("directors") or []) if isinstance(item, dict)]
    isc_entries = [
        item
        for item in (
            record.get("individuals_with_significant_control")
            or record.get("isc")
            or []
        )
        if isinstance(item, dict)
    ]
    filings = [item for item in (record.get("filings") or []) if isinstance(item, dict)]

    if corp_number:
        result.identifiers["ca_corporation_number"] = corp_number
    if business_number:
        result.identifiers["business_number"] = business_number
    result.identifiers["corporations_canada_url"] = dataset_url

    severity = "info"
    if status.lower() in {"dissolved", "inactive", "discontinued"}:
        severity = "high"
        result.risk_signals.append(
            {
                "signal": "canadian_corporation_inactive",
                "source": SOURCE_NAME,
                "severity": "high",
                "confidence": 0.95,
                "summary": f"Corporations Canada lists {corp_name} as {status or 'inactive'}",
            }
        )

    result.findings.append(
        Finding(
            source=SOURCE_NAME,
            category="corporate_identity",
            title=f"Corporations Canada: {corp_name} ({status or 'unknown status'})",
            detail=(
                f"Corporation Number: {corp_number or 'unavailable'}\n"
                f"Business Number: {business_number or 'unavailable'}\n"
                f"Legislation: {legislation or 'unavailable'}\n"
                f"Incorporated: {incorporation_date or 'unavailable'}"
            ),
            severity=severity,
            confidence=0.92,
            url=dataset_url,
            raw_data={
                "corporation_number": corp_number,
                "business_number": business_number,
                "status": status,
            },
            source_class="public_connector",
            authority_level="official_registry",
            access_model="public_json",
            structured_fields={
                "summary": {
                    "corporation_number": corp_number,
                    "business_number": business_number,
                    "status": status,
                    "director_count": len(directors),
                    "isc_count": len(isc_entries),
                    "filing_count": len(filings),
                }
            },
        )
    )

    for director in directors[:20]:
        name = str(director.get("name") or "").strip()
        if not name:
            continue
        result.relationships.append(
            {
                "type": "officer_of",
                "source_entity": name,
                "source_entity_type": "person",
                "source_identifiers": director.get("identifiers", {}) or {},
                "target_entity": corp_name,
                "target_entity_type": "company",
                "target_identifiers": {
                    "ca_corporation_number": corp_number,
                    "business_number": business_number,
                },
                "country": "CA",
                "data_source": SOURCE_NAME,
                "confidence": 0.9,
                "evidence": "Corporations Canada director record",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "role": str(director.get("role") or director.get("officer_role") or "director"),
                    "appointed_on": str(director.get("appointed_on") or director.get("start_date") or ""),
                    "resigned_on": str(director.get("resigned_on") or ""),
                    "standards": ["Corporations Canada Directors Register"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_json",
            }
        )

    for isc_entry in isc_entries[:20]:
        isc_name = str(isc_entry.get("name") or "").strip()
        if not isc_name:
            continue
        result.relationships.append(
            {
                "type": "beneficially_owned_by",
                "source_entity": corp_name,
                "source_entity_type": "company",
                "source_identifiers": {
                    "ca_corporation_number": corp_number,
                    "business_number": business_number,
                },
                "target_entity": isc_name,
                "target_entity_type": str(isc_entry.get("entity_type") or "person"),
                "target_identifiers": isc_entry.get("identifiers", {}) or {},
                "country": str(isc_entry.get("country") or "CA"),
                "data_source": SOURCE_NAME,
                "confidence": 0.94,
                "evidence": "Corporations Canada ISC disclosure",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "control_description": str(
                        isc_entry.get("control_description")
                        or isc_entry.get("description")
                        or isc_entry.get("significant_control_description")
                        or ""
                    ),
                    "became_isc_on": str(isc_entry.get("became_isc_on") or isc_entry.get("start_date") or ""),
                    "ceased_isc_on": str(isc_entry.get("ceased_isc_on") or isc_entry.get("end_date") or ""),
                    "address_for_service": str(isc_entry.get("address_for_service") or ""),
                    "standards": ["Corporations Canada ISC Register"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_json",
            }
        )

    if isc_entries:
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="ownership",
                title=f"Corporations Canada ISC records: {len(isc_entries)} public disclosures",
                detail=(
                    f"{corp_name} has {len(isc_entries)} public ISC disclosures "
                    "available through Corporations Canada."
                ),
                severity="medium",
                confidence=0.9,
                url=dataset_url,
                raw_data={"isc_count": len(isc_entries)},
                source_class="public_connector",
                authority_level="official_registry",
                access_model="public_json",
            )
        )
    if filings:
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="corporate_identity",
                title=f"Corporations Canada filings: {len(filings)} recent records",
                detail=f"{corp_name} matched {len(filings)} filing or transaction records in the configured export.",
                severity="info",
                confidence=0.88,
                url=dataset_url,
                raw_data={"filing_count": len(filings)},
                source_class="public_connector",
                authority_level="official_registry",
                access_model="public_json",
            )
        )

    result.structured_fields = {
        "summary": {
            "corporation_number": corp_number,
            "business_number": business_number,
            "status": status,
            "director_count": len(directors),
            "isc_count": len(isc_entries),
            "filing_count": len(filings),
            "dataset_url": dataset_url,
        }
    }
    result.artifact_refs = [dataset_url]
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
