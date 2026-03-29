"""Netherlands KVK official-registry connector.

This connector stays inside the local-first collector lab posture:
it consumes a provider-neutral public JSON export that mirrors official KVK
entity profile and mutation fields, while keeping live network access opt-in.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from . import EnrichmentResult, Finding


SOURCE_NAME = "netherlands_kvk"
USER_AGENT = "Xiphos-Vetting/2.1"


def _normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _dataset_url(ids: dict) -> str:
    for key in (
        "netherlands_kvk_url",
        "kvk_profile_url",
        "kvk_api_url",
        "netherlands_registry_url",
    ):
        value = str(ids.get(key) or "").strip()
        if value:
            return value
    return str(os.environ.get("XIPHOS_NETHERLANDS_KVK_URL") or "").strip()


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
    known_kvk = str(ids.get("kvk_number") or ids.get("kvk") or "").strip()
    record_kvk = str(record.get("kvk_number") or record.get("kvk") or "").strip()
    if known_kvk and record_kvk == known_kvk:
        return True
    if _normalize_name(record.get("entity_name") or record.get("registered_name") or record.get("name") or "") != _normalize_name(vendor_name):
        return False
    country_code = str(country or "").strip().upper()
    if country_code and country_code not in {"NL", "NLD"}:
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

    if country and str(country).strip().upper() not in {"", "NL", "NLD"}:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    dataset_url = _dataset_url(ids)
    if not dataset_url:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    payload = _fetch_json(dataset_url)
    if not isinstance(payload, dict):
        result.error = "Unable to fetch Netherlands KVK public dataset"
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    records = payload.get("records") or payload.get("entities") or payload.get("profiles")
    if not isinstance(records, list):
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="corporate_identity",
                title="Netherlands KVK dataset shape unsupported",
                detail=(
                    "The configured Netherlands KVK dataset does not expose a top-level "
                    "`records`, `entities`, or `profiles` array in the expected provider-neutral format."
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

    entity_name = str(record.get("entity_name") or record.get("registered_name") or record.get("name") or vendor_name).strip()
    kvk_number = str(record.get("kvk_number") or record.get("kvk") or "").strip()
    establishment_number = str(record.get("establishment_number") or "").strip()
    rsin = str(record.get("rsin") or "").strip()
    status = str(record.get("status") or record.get("entity_status") or "").strip()
    legal_form = str(record.get("legal_form") or "").strip()
    registered_on = str(record.get("registered_on") or record.get("incorporated_on") or "").strip()
    sbi_code = str(record.get("sbi_code") or "").strip()
    region = str(record.get("region") or record.get("registered_region") or "").strip()
    website = str(record.get("website") or "").strip()
    trade_names = [str(item).strip() for item in (record.get("trade_names") or record.get("business_names") or []) if str(item).strip()]
    officers = [item for item in (record.get("officers") or record.get("functionaries") or []) if isinstance(item, dict)]
    shareholders = [item for item in (record.get("shareholders") or record.get("owners") or []) if isinstance(item, dict)]
    mutations = [item for item in (record.get("mutations") or record.get("recent_changes") or []) if isinstance(item, dict)]

    if kvk_number:
        result.identifiers["kvk_number"] = kvk_number
    if establishment_number:
        result.identifiers["kvk_establishment_number"] = establishment_number
    if rsin:
        result.identifiers["rsin"] = rsin
    if website:
        result.identifiers["website"] = website
    result.identifiers["netherlands_kvk_url"] = dataset_url

    severity = "info"
    if status.lower() in {"inactive", "deregistered", "removed", "discontinued"}:
        severity = "high"
        result.risk_signals.append(
            {
                "signal": "netherlands_entity_inactive",
                "source": SOURCE_NAME,
                "severity": "high",
                "confidence": 0.95,
                "summary": f"KVK lists {entity_name} as {status or 'inactive'}",
                "detail": f"Entity status is {status or 'inactive'} in KVK registry data.",
            }
        )

    result.findings.append(
        Finding(
            source=SOURCE_NAME,
            category="corporate_identity",
            title=f"KVK profile: {entity_name} ({status or 'unknown status'})",
            detail=(
                f"KVK number: {kvk_number or 'unavailable'}\n"
                f"Establishment number: {establishment_number or 'unavailable'}\n"
                f"Legal form: {legal_form or 'unavailable'}\n"
                f"Registered on: {registered_on or 'unavailable'}\n"
                f"Region: {region or 'unavailable'}\n"
                f"SBI code: {sbi_code or 'unavailable'}"
            ),
            severity=severity,
            confidence=0.92,
            url=dataset_url,
            raw_data={
                "kvk_number": kvk_number,
                "status": status,
                "legal_form": legal_form,
            },
            source_class="public_connector",
            authority_level="official_registry",
            access_model="public_json",
            structured_fields={
                "summary": {
                    "kvk_number": kvk_number,
                    "status": status,
                    "legal_form": legal_form,
                    "officer_count": len(officers),
                    "shareholder_count": len(shareholders),
                    "mutation_count": len(mutations),
                }
            },
        )
    )

    if trade_names:
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="corporate_identity",
                title=f"KVK trade names: {len(trade_names)}",
                detail="\n".join(trade_names[:8]),
                severity="info",
                confidence=0.88,
                url=dataset_url,
                raw_data={"trade_names": trade_names[:12]},
                source_class="public_connector",
                authority_level="official_registry",
                access_model="public_json",
            )
        )

    for officer in officers[:20]:
        name = str(officer.get("name") or "").strip()
        if not name:
            continue
        result.relationships.append(
            {
                "type": "officer_of",
                "source_entity": name,
                "source_entity_type": "person",
                "source_identifiers": officer.get("identifiers", {}) or {},
                "target_entity": entity_name,
                "target_entity_type": "company",
                "target_identifiers": {"kvk_number": kvk_number},
                "country": "NL",
                "data_source": SOURCE_NAME,
                "confidence": 0.9,
                "evidence": "KVK functionary record",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "role": str(officer.get("role") or officer.get("title") or "functionary"),
                    "appointed_on": str(officer.get("appointed_on") or officer.get("start_date") or ""),
                    "ceased_on": str(officer.get("ceased_on") or officer.get("end_date") or ""),
                    "standards": ["KVK"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_json",
            }
        )

    for shareholder in shareholders[:20]:
        name = str(shareholder.get("name") or "").strip()
        if not name:
            continue
        result.relationships.append(
            {
                "type": "owned_by",
                "source_entity": entity_name,
                "source_entity_type": "company",
                "source_identifiers": {"kvk_number": kvk_number},
                "target_entity": name,
                "target_entity_type": str(shareholder.get("entity_type") or "company"),
                "target_identifiers": shareholder.get("identifiers", {}) or {},
                "country": str(shareholder.get("country") or "NL"),
                "data_source": SOURCE_NAME,
                "confidence": 0.88,
                "evidence": "KVK shareholder or ownership record",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "interest_description": str(shareholder.get("interest_description") or shareholder.get("role") or "shareholder"),
                    "share_pct": shareholder.get("share_pct"),
                    "standards": ["KVK"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_json",
            }
        )

    for mutation in mutations[:12]:
        summary = str(mutation.get("summary") or mutation.get("description") or "").strip()
        if not summary:
            continue
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="corporate_identity",
                title=f"KVK mutation: {summary[:90]}",
                detail=(
                    f"Mutation date: {mutation.get('date') or 'unavailable'}\n"
                    f"Type: {mutation.get('mutation_type') or 'unavailable'}"
                ),
                severity="info",
                confidence=0.84,
                url=dataset_url,
                raw_data={"mutation": mutation},
                source_class="public_connector",
                authority_level="official_registry",
                access_model="public_json",
            )
        )

    result.structured_fields["summary"] = {
        "kvk_number": kvk_number,
        "status": status,
        "legal_form": legal_form,
        "officer_count": len(officers),
        "shareholder_count": len(shareholders),
        "mutation_count": len(mutations),
    }
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
