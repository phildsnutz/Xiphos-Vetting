"""Singapore ACRA official-registry connector.

This connector stays inside the local-first collector lab posture:
it consumes a provider-neutral public JSON export that mirrors official
ACRA business profile fields, while keeping live network access opt-in.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from . import EnrichmentResult, Finding


SOURCE_NAME = "singapore_acra"
USER_AGENT = "Xiphos-Vetting/2.1"


def _normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _dataset_url(ids: dict) -> str:
    for key in (
        "singapore_acra_url",
        "acra_business_profile_url",
        "acra_eiq_url",
        "singapore_registry_url",
    ):
        value = str(ids.get(key) or "").strip()
        if value:
            return value
    return str(os.environ.get("XIPHOS_SINGAPORE_ACRA_URL") or "").strip()


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
    known_uen = str(ids.get("uen") or "").strip().upper()
    record_uen = str(record.get("uen") or "").strip().upper()
    if known_uen and record_uen == known_uen:
        return True
    if _normalize_name(record.get("entity_name") or record.get("business_name") or record.get("name") or "") != _normalize_name(vendor_name):
        return False
    country_code = str(country or "").strip().upper()
    if country_code and country_code not in {"SG", "SGP"}:
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

    if country and str(country).strip().upper() not in {"", "SG", "SGP"}:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    dataset_url = _dataset_url(ids)
    if not dataset_url:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    payload = _fetch_json(dataset_url)
    if not isinstance(payload, dict):
        result.error = "Unable to fetch Singapore ACRA public dataset"
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    records = payload.get("records") or payload.get("entities") or payload.get("business_profiles")
    if not isinstance(records, list):
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="corporate_identity",
                title="Singapore ACRA dataset shape unsupported",
                detail=(
                    "The configured Singapore ACRA dataset does not expose a top-level "
                    "`records`, `entities`, or `business_profiles` array in the expected provider-neutral format."
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

    entity_name = str(record.get("entity_name") or record.get("business_name") or record.get("name") or vendor_name).strip()
    uen = str(record.get("uen") or "").strip()
    status = str(record.get("status") or record.get("entity_status") or "").strip()
    entity_type = str(record.get("entity_type") or record.get("business_type") or "").strip()
    registration_date = str(record.get("registration_date") or record.get("incorporated_on") or "").strip()
    primary_ssic = str(record.get("primary_ssic") or "").strip()
    secondary_ssic = str(record.get("secondary_ssic") or "").strip()
    position_holders = [item for item in (record.get("position_holders") or record.get("officers") or []) if isinstance(item, dict)]
    owners_or_partners = [item for item in (record.get("owners_or_partners") or record.get("owners") or record.get("partners") or []) if isinstance(item, dict)]

    if uen:
        result.identifiers["uen"] = uen
    result.identifiers["singapore_acra_url"] = dataset_url

    severity = "info"
    if status.lower() in {"struck off", "dissolved", "cancelled", "terminated", "inactive"}:
        severity = "high"
        result.risk_signals.append(
            {
                "signal": "singapore_entity_inactive",
                "source": SOURCE_NAME,
                "severity": "high",
                "confidence": 0.95,
                "summary": f"ACRA lists {entity_name} as {status or 'inactive'}",
                "detail": f"Entity status is {status or 'inactive'} in the ACRA business profile.",
            }
        )

    result.findings.append(
        Finding(
            source=SOURCE_NAME,
            category="corporate_identity",
            title=f"ACRA business profile: {entity_name} ({status or 'unknown status'})",
            detail=(
                f"UEN: {uen or 'unavailable'}\n"
                f"Entity type: {entity_type or 'unavailable'}\n"
                f"Registration date: {registration_date or 'unavailable'}\n"
                f"Primary SSIC: {primary_ssic or 'unavailable'}\n"
                f"Secondary SSIC: {secondary_ssic or 'unavailable'}"
            ),
            severity=severity,
            confidence=0.92,
            url=dataset_url,
            raw_data={
                "uen": uen,
                "status": status,
                "entity_type": entity_type,
            },
            source_class="public_connector",
            authority_level="official_registry",
            access_model="public_json",
            structured_fields={
                "summary": {
                    "uen": uen,
                    "status": status,
                    "entity_type": entity_type,
                    "position_holder_count": len(position_holders),
                    "owner_or_partner_count": len(owners_or_partners),
                    "primary_ssic": primary_ssic,
                    "secondary_ssic": secondary_ssic,
                }
            },
        )
    )

    for holder in position_holders[:20]:
        name = str(holder.get("name") or "").strip()
        if not name:
            continue
        result.relationships.append(
            {
                "type": "officer_of",
                "source_entity": name,
                "source_entity_type": "person",
                "source_identifiers": holder.get("identifiers", {}) or {},
                "target_entity": entity_name,
                "target_entity_type": "company",
                "target_identifiers": {"uen": uen},
                "country": "SG",
                "data_source": SOURCE_NAME,
                "confidence": 0.9,
                "evidence": "ACRA business profile position holder record",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "role": str(holder.get("role") or holder.get("position") or "position_holder"),
                    "appointed_on": str(holder.get("appointed_on") or holder.get("start_date") or ""),
                    "ceased_on": str(holder.get("ceased_on") or holder.get("end_date") or ""),
                    "standards": ["ACRA Business Profile"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_json",
            }
        )

    for owner in owners_or_partners[:20]:
        name = str(owner.get("name") or "").strip()
        if not name:
            continue
        result.relationships.append(
            {
                "type": "owned_by",
                "source_entity": entity_name,
                "source_entity_type": "company",
                "source_identifiers": {"uen": uen},
                "target_entity": name,
                "target_entity_type": str(owner.get("entity_type") or "person"),
                "target_identifiers": owner.get("identifiers", {}) or {},
                "country": str(owner.get("country") or "SG"),
                "data_source": SOURCE_NAME,
                "confidence": 0.88,
                "evidence": "ACRA business profile owner or partner record",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "interest_description": str(owner.get("interest_description") or owner.get("role") or "owner_or_partner"),
                    "share_pct": owner.get("share_pct"),
                    "standards": ["ACRA Business Profile"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_json",
            }
        )

    result.structured_fields["summary"] = {
        "uen": uen,
        "status": status,
        "entity_type": entity_type,
        "position_holder_count": len(position_holders),
        "owner_or_partner_count": len(owners_or_partners),
        "primary_ssic": primary_ssic,
        "secondary_ssic": secondary_ssic,
        "registration_date": registration_date,
    }
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
