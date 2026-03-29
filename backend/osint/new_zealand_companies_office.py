"""New Zealand Companies Office / NZBN official-registry connector.

This connector stays inside the local-first collector lab posture:
it consumes a provider-neutral public JSON export that mirrors official
Companies Office and NZBN fields, while keeping live network access opt-in.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from . import EnrichmentResult, Finding


SOURCE_NAME = "new_zealand_companies_office"
USER_AGENT = "Xiphos-Vetting/2.1"


def _normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _dataset_url(ids: dict) -> str:
    for key in (
        "new_zealand_companies_office_url",
        "nz_companies_office_url",
        "nzbn_registry_url",
        "nz_registry_url",
    ):
        value = str(ids.get(key) or "").strip()
        if value:
            return value
    return str(os.environ.get("XIPHOS_NEW_ZEALAND_COMPANIES_OFFICE_URL") or "").strip()


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
    known_nzbn = str(ids.get("nzbn") or "").strip()
    known_company_number = str(ids.get("nz_company_number") or ids.get("company_number") or "").strip().upper()
    record_nzbn = str(record.get("nzbn") or "").strip()
    record_company_number = str(record.get("nz_company_number") or record.get("company_number") or "").strip().upper()
    if known_nzbn and record_nzbn == known_nzbn:
        return True
    if known_company_number and record_company_number == known_company_number:
        return True
    if _normalize_name(record.get("entity_name") or record.get("company_name") or record.get("name") or "") != _normalize_name(vendor_name):
        return False
    country_code = str(country or "").strip().upper()
    if country_code and country_code not in {"NZ", "NZL"}:
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

    if country and str(country).strip().upper() not in {"", "NZ", "NZL"}:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    dataset_url = _dataset_url(ids)
    if not dataset_url:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    payload = _fetch_json(dataset_url)
    if not isinstance(payload, dict):
        result.error = "Unable to fetch New Zealand Companies Office public dataset"
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    records = payload.get("records") or payload.get("entities") or payload.get("companies")
    if not isinstance(records, list):
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="corporate_identity",
                title="New Zealand Companies Office dataset shape unsupported",
                detail=(
                    "The configured New Zealand Companies Office dataset does not expose a top-level "
                    "`records`, `entities`, or `companies` array in the expected provider-neutral format."
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

    entity_name = str(record.get("entity_name") or record.get("company_name") or record.get("name") or vendor_name).strip()
    nzbn = str(record.get("nzbn") or "").strip()
    company_number = str(record.get("nz_company_number") or record.get("company_number") or "").strip()
    status = str(record.get("status") or record.get("entity_status") or "").strip()
    entity_type = str(record.get("entity_type") or record.get("company_type") or "").strip()
    incorporated_on = str(record.get("incorporated_on") or record.get("registered_on") or record.get("incorporation_date") or "").strip()
    region = str(record.get("region") or record.get("registered_office_region") or "").strip()
    industry = str(record.get("industry_description") or record.get("industry") or "").strip()
    trading_names = [
        str(item).strip()
        for item in (record.get("trading_names") or record.get("alternate_names") or [])
        if str(item).strip()
    ]
    officeholders = [item for item in (record.get("officeholders") or record.get("officers") or []) if isinstance(item, dict)]
    shareholdings = [item for item in (record.get("shareholdings") or record.get("parents") or []) if isinstance(item, dict)]

    if nzbn:
        result.identifiers["nzbn"] = nzbn
    if company_number:
        result.identifiers["nz_company_number"] = company_number
    result.identifiers["new_zealand_companies_office_url"] = dataset_url

    severity = "info"
    if status.lower() in {"removed", "inactive", "ceased", "liquidation", "liquidated"}:
        severity = "high"
        result.risk_signals.append(
            {
                "signal": "nz_company_inactive",
                "source": SOURCE_NAME,
                "severity": "high",
                "summary": f"New Zealand Companies Office lists {entity_name} as {status or 'inactive'}",
                "detail": f"Company status is {status or 'inactive'} on the New Zealand register.",
                "confidence": 0.95,
            }
        )

    result.findings.append(
        Finding(
            source=SOURCE_NAME,
            category="corporate_identity",
            title=f"New Zealand Companies Office: {entity_name} ({status or 'unknown status'})",
            detail=(
                f"NZBN: {nzbn or 'unavailable'}\n"
                f"Company number: {company_number or 'unavailable'}\n"
                f"Entity type: {entity_type or 'unavailable'}\n"
                f"Incorporated: {incorporated_on or 'unavailable'}\n"
                f"Region: {region or 'unavailable'}"
            ),
            severity=severity,
            confidence=0.92,
            url=dataset_url,
            raw_data={
                "nzbn": nzbn,
                "nz_company_number": company_number,
                "status": status,
                "entity_type": entity_type,
            },
            source_class="public_connector",
            authority_level="official_registry",
            access_model="public_json",
            structured_fields={
                "summary": {
                    "nzbn": nzbn,
                    "nz_company_number": company_number,
                    "status": status,
                    "entity_type": entity_type,
                    "officeholder_count": len(officeholders),
                    "shareholding_count": len(shareholdings),
                    "trading_name_count": len(trading_names),
                    "industry": industry,
                }
            },
        )
    )

    if trading_names:
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="corporate_identity",
                title=f"New Zealand register alternate names: {len(trading_names)}",
                detail="\n".join(trading_names[:8]),
                severity="info",
                confidence=0.86,
                url=dataset_url,
                raw_data={"trading_names": trading_names[:12]},
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
                    "nzbn": nzbn,
                    "nz_company_number": company_number,
                },
                "country": "NZ",
                "data_source": SOURCE_NAME,
                "confidence": 0.9,
                "evidence": "New Zealand Companies Office officeholder record",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "role": str(officeholder.get("role") or officeholder.get("title") or "officeholder"),
                    "appointed_on": str(officeholder.get("appointed_on") or officeholder.get("start_date") or ""),
                    "ceased_on": str(officeholder.get("ceased_on") or officeholder.get("end_date") or ""),
                    "standards": ["New Zealand Companies Register", "NZBN"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_json",
            }
        )

    for shareholding in shareholdings[:20]:
        holder_name = str(shareholding.get("name") or shareholding.get("holder_name") or "").strip()
        if not holder_name:
            continue
        result.relationships.append(
            {
                "type": "owned_by",
                "source_entity": entity_name,
                "source_entity_type": "company",
                "source_identifiers": {
                    "nzbn": nzbn,
                    "nz_company_number": company_number,
                },
                "target_entity": holder_name,
                "target_entity_type": str(shareholding.get("entity_type") or "company"),
                "target_identifiers": shareholding.get("identifiers", {}) or {},
                "country": str(shareholding.get("country") or "NZ"),
                "data_source": SOURCE_NAME,
                "confidence": 0.88,
                "evidence": "New Zealand Companies Office shareholder or parent disclosure",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "share_pct": shareholding.get("share_pct"),
                    "interest_description": str(
                        shareholding.get("interest_description")
                        or shareholding.get("description")
                        or ""
                    ),
                    "standards": ["New Zealand Companies Register"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_json",
            }
        )

    if shareholdings:
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="ownership",
                title=f"New Zealand register ownership disclosures: {len(shareholdings)}",
                detail="\n".join(
                    f"{str(item.get('name') or item.get('holder_name') or '').strip()}: "
                    f"{str(item.get('interest_description') or item.get('share_pct') or 'shareholding recorded')}"
                    for item in shareholdings[:6]
                    if str(item.get('name') or item.get('holder_name') or '').strip()
                ),
                severity="low",
                confidence=0.85,
                url=dataset_url,
                raw_data={"shareholdings": shareholdings[:12]},
                source_class="public_connector",
                authority_level="official_registry",
                access_model="public_json",
            )
        )

    result.structured_fields["summary"] = {
        "nzbn": nzbn,
        "nz_company_number": company_number,
        "status": status,
        "entity_type": entity_type,
        "officeholder_count": len(officeholders),
        "shareholding_count": len(shareholdings),
        "trading_name_count": len(trading_names),
        "industry": industry,
        "incorporated_on": incorporated_on,
        "region": region,
    }
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
