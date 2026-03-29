"""Australia ABN / ASIC official-registry connector.

This connector stays inside the local-first collector lab posture:
it consumes a provider-neutral public JSON export that mirrors official ABR
and ASIC register fields, while keeping live network access opt-in.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from . import EnrichmentResult, Finding


SOURCE_NAME = "australia_abn_asic"
USER_AGENT = "Xiphos-Vetting/2.1"


def _normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _dataset_url(ids: dict) -> str:
    for key in (
        "australia_abn_asic_url",
        "australia_registry_url",
        "abn_lookup_url",
        "asic_registry_url",
    ):
        value = str(ids.get(key) or "").strip()
        if value:
            return value
    return str(os.environ.get("XIPHOS_AUSTRALIA_ABN_ASIC_URL") or "").strip()


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
    known_abn = str(ids.get("abn") or "").strip()
    known_acn = str(ids.get("acn") or "").strip()
    record_abn = str(record.get("abn") or record.get("australian_business_number") or "").strip()
    record_acn = str(record.get("acn") or record.get("australian_company_number") or "").strip()
    if known_abn and record_abn == known_abn:
        return True
    if known_acn and record_acn == known_acn:
        return True
    if _normalize_name(record.get("entity_name") or record.get("organisation_name") or record.get("name") or "") != _normalize_name(vendor_name):
        return False
    country_code = str(country or "").strip().upper()
    if country_code and country_code not in {"AU", "AUS"}:
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

    if country and str(country).strip().upper() not in {"", "AU", "AUS"}:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    dataset_url = _dataset_url(ids)
    if not dataset_url:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    payload = _fetch_json(dataset_url)
    if not isinstance(payload, dict):
        result.error = "Unable to fetch Australia ABN/ASIC public dataset"
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    records = payload.get("records") or payload.get("entities") or payload.get("organisations")
    if not isinstance(records, list):
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="corporate_identity",
                title="Australia ABN / ASIC dataset shape unsupported",
                detail=(
                    "The configured Australia ABN / ASIC dataset does not expose a top-level "
                    "`records`, `entities`, or `organisations` array in the expected provider-neutral format."
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

    entity_name = str(record.get("entity_name") or record.get("organisation_name") or record.get("name") or vendor_name).strip()
    abn = str(record.get("abn") or record.get("australian_business_number") or "").strip()
    acn = str(record.get("acn") or record.get("australian_company_number") or "").strip()
    status = str(record.get("status") or record.get("entity_status") or "").strip()
    entity_type = str(record.get("entity_type") or record.get("organisation_type") or "").strip()
    registered_on = str(record.get("registered_on") or record.get("registration_date") or "").strip()
    gst_status = str(record.get("gst_status") or "").strip()
    state = str(record.get("state") or record.get("jurisdiction") or "").strip()
    officeholders = [item for item in (record.get("officeholders") or record.get("officers") or []) if isinstance(item, dict)]
    business_names = [str(item).strip() for item in (record.get("business_names") or record.get("trading_names") or []) if str(item).strip()]

    if abn:
        result.identifiers["abn"] = abn
    if acn:
        result.identifiers["acn"] = acn
    result.identifiers["australia_abn_asic_url"] = dataset_url

    severity = "info"
    if status.lower() in {"cancelled", "deregistered", "inactive"}:
        severity = "high"
        result.risk_signals.append(
            {
                "signal": "australian_entity_inactive",
                "source": SOURCE_NAME,
                "severity": "high",
                "confidence": 0.95,
                "summary": f"ABR / ASIC lists {entity_name} as {status or 'inactive'}",
            }
        )

    result.findings.append(
        Finding(
            source=SOURCE_NAME,
            category="corporate_identity",
            title=f"ABR / ASIC: {entity_name} ({status or 'unknown status'})",
            detail=(
                f"ABN: {abn or 'unavailable'}\n"
                f"ACN: {acn or 'unavailable'}\n"
                f"Entity type: {entity_type or 'unavailable'}\n"
                f"Registered: {registered_on or 'unavailable'}\n"
                f"State: {state or 'unavailable'}"
            ),
            severity=severity,
            confidence=0.92,
            url=dataset_url,
            raw_data={
                "abn": abn,
                "acn": acn,
                "status": status,
                "entity_type": entity_type,
            },
            source_class="public_connector",
            authority_level="official_registry",
            access_model="public_json",
            structured_fields={
                "summary": {
                    "abn": abn,
                    "acn": acn,
                    "status": status,
                    "entity_type": entity_type,
                    "officeholder_count": len(officeholders),
                    "business_name_count": len(business_names),
                    "gst_status": gst_status,
                }
            },
        )
    )

    if business_names:
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="corporate_identity",
                title=f"ABR / ASIC alternate names: {len(business_names)}",
                detail="\n".join(business_names[:8]),
                severity="info",
                confidence=0.88,
                url=dataset_url,
                raw_data={"business_names": business_names[:12]},
                source_class="public_connector",
                authority_level="official_registry",
                access_model="public_json",
            )
        )

    for officeholder in officeholders[:20]:
        name = str(officeholder.get("name") or "").strip()
        if not name:
            continue
        result.relationships.append(
            {
                "type": "officer_of",
                "source_entity": name,
                "source_entity_type": "person",
                "source_identifiers": officeholder.get("identifiers", {}) or {},
                "target_entity": entity_name,
                "target_entity_type": "company",
                "target_identifiers": {
                    "abn": abn,
                    "acn": acn,
                },
                "country": "AU",
                "data_source": SOURCE_NAME,
                "confidence": 0.9,
                "evidence": "ABR / ASIC officeholder record",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "role": str(officeholder.get("role") or officeholder.get("title") or "officeholder"),
                    "appointed_on": str(officeholder.get("appointed_on") or officeholder.get("start_date") or ""),
                    "ceased_on": str(officeholder.get("ceased_on") or officeholder.get("end_date") or ""),
                    "standards": ["ABR", "ASIC Register"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_json",
            }
        )

    result.structured_fields["summary"] = {
        "abn": abn,
        "acn": acn,
        "status": status,
        "entity_type": entity_type,
        "officeholder_count": len(officeholders),
        "business_name_count": len(business_names),
        "gst_status": gst_status,
        "registered_on": registered_on,
        "state": state,
    }
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
