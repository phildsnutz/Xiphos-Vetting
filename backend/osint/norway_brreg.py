"""Norway Bronnoysund Register Centre public-registry connector.

This connector stays local-first and fixture-friendly:
it consumes a provider-neutral public JSON export that mirrors official
Brreg organisation and, when lawfully available, beneficial-owner data.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from . import EnrichmentResult, Finding


SOURCE_NAME = "norway_brreg"
USER_AGENT = "Xiphos-Vetting/2.1"


def _normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _dataset_url(ids: dict) -> str:
    for key in ("norway_brreg_url", "brreg_org_url", "norway_registry_url"):
        value = str(ids.get(key) or "").strip()
        if value:
            return value
    return str(os.environ.get("XIPHOS_NORWAY_BRREG_URL") or "").strip()


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
    known_org_number = str(ids.get("norway_org_number") or ids.get("organization_number") or "").strip()
    record_org_number = str(record.get("norway_org_number") or record.get("organization_number") or "").strip()
    if known_org_number and record_org_number == known_org_number:
        return True
    if _normalize_name(record.get("entity_name") or record.get("organization_name") or record.get("name") or "") != _normalize_name(vendor_name):
        return False
    country_code = str(country or "").strip().upper()
    if country_code and country_code not in {"NO", "NOR"}:
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

    if country and str(country).strip().upper() not in {"", "NO", "NOR"}:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    dataset_url = _dataset_url(ids)
    if not dataset_url:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    payload = _fetch_json(dataset_url)
    if not isinstance(payload, dict):
        result.error = "Unable to fetch Norway Brreg public dataset"
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    records = payload.get("records") or payload.get("entities") or payload.get("organisations")
    if not isinstance(records, list):
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="corporate_identity",
                title="Norway Brreg dataset shape unsupported",
                detail=(
                    "The configured Norway Brreg dataset does not expose a top-level "
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

    entity_name = str(record.get("entity_name") or record.get("organization_name") or record.get("name") or vendor_name).strip()
    org_number = str(record.get("norway_org_number") or record.get("organization_number") or "").strip()
    status = str(record.get("status") or record.get("entity_status") or "").strip()
    entity_type = str(record.get("entity_type") or record.get("organization_form") or "").strip()
    registered_on = str(record.get("registered_on") or record.get("incorporated_on") or record.get("registration_date") or "").strip()
    municipality = str(record.get("municipality") or record.get("registered_municipality") or "").strip()
    website = str(record.get("website") or "").strip()
    roles = [item for item in (record.get("roles") or record.get("officers") or []) if isinstance(item, dict)]
    beneficial_owners = [item for item in (record.get("beneficial_owners") or []) if isinstance(item, dict)]
    beneficial_owner_access = str(record.get("beneficial_owner_access") or "").strip()

    if org_number:
        result.identifiers["norway_org_number"] = org_number
    if website:
        result.identifiers["website"] = website
    result.identifiers["norway_brreg_url"] = dataset_url

    severity = "info"
    if status.lower() in {"under_avvikling", "under_liquidation", "dissolved", "deleted", "inactive"}:
        severity = "high"
        result.risk_signals.append(
            {
                "signal": "norway_entity_inactive",
                "source": SOURCE_NAME,
                "severity": "high",
                "confidence": 0.95,
                "summary": f"Brreg lists {entity_name} as {status or 'inactive'}",
                "detail": f"Organisation status is {status or 'inactive'} in Bronnoysund register data.",
            }
        )

    result.findings.append(
        Finding(
            source=SOURCE_NAME,
            category="corporate_identity",
            title=f"Norway Brreg: {entity_name} ({status or 'unknown status'})",
            detail=(
                f"Organisation number: {org_number or 'unavailable'}\n"
                f"Entity type: {entity_type or 'unavailable'}\n"
                f"Registered on: {registered_on or 'unavailable'}\n"
                f"Municipality: {municipality or 'unavailable'}\n"
                f"Website: {website or 'unavailable'}"
            ),
            severity=severity,
            confidence=0.92,
            url=dataset_url,
            raw_data={
                "norway_org_number": org_number,
                "status": status,
                "entity_type": entity_type,
            },
            source_class="public_connector",
            authority_level="official_registry",
            access_model="public_json",
            structured_fields={
                "summary": {
                    "norway_org_number": org_number,
                    "status": status,
                    "entity_type": entity_type,
                    "role_count": len(roles),
                    "beneficial_owner_count": len(beneficial_owners),
                    "beneficial_owner_access": beneficial_owner_access,
                }
            },
        )
    )

    if beneficial_owner_access:
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="beneficial_ownership",
                title="Norway beneficial-owner access posture",
                detail=beneficial_owner_access,
                severity="info",
                confidence=0.88,
                url=dataset_url,
                raw_data={"beneficial_owner_access": beneficial_owner_access},
                source_class="public_connector",
                authority_level="official_registry",
                access_model="public_json",
            )
        )

    for role in roles[:20]:
        name = str(role.get("name") or "").strip()
        if not name:
            continue
        result.relationships.append(
            {
                "type": "officer_of",
                "source_entity": name,
                "source_entity_type": "person",
                "source_identifiers": role.get("identifiers", {}) or {},
                "target_entity": entity_name,
                "target_entity_type": "company",
                "target_identifiers": {"norway_org_number": org_number},
                "country": "NO",
                "data_source": SOURCE_NAME,
                "confidence": 0.9,
                "evidence": "Bronnoysund Register Centre role record",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "role": str(role.get("role") or role.get("title") or "role_holder"),
                    "appointed_on": str(role.get("appointed_on") or role.get("start_date") or ""),
                    "ceased_on": str(role.get("ceased_on") or role.get("end_date") or ""),
                    "standards": ["Bronnoysund Register Centre"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_json",
            }
        )

    for owner in beneficial_owners[:20]:
        owner_name = str(owner.get("name") or "").strip()
        if not owner_name:
            continue
        result.relationships.append(
            {
                "type": "beneficially_owned_by",
                "source_entity": entity_name,
                "source_entity_type": "company",
                "source_identifiers": {"norway_org_number": org_number},
                "target_entity": owner_name,
                "target_entity_type": str(owner.get("entity_type") or "person"),
                "target_identifiers": owner.get("identifiers", {}) or {},
                "country": str(owner.get("country") or "NO"),
                "data_source": SOURCE_NAME,
                "confidence": 0.9,
                "evidence": "Bronnoysund beneficial-owner disclosure",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "control_description": str(owner.get("control_description") or owner.get("description") or ""),
                    "ownership_pct": owner.get("ownership_pct"),
                    "standards": ["Bronnoysund Beneficial Owners"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_json",
            }
        )

    result.structured_fields["summary"] = {
        "norway_org_number": org_number,
        "status": status,
        "entity_type": entity_type,
        "role_count": len(roles),
        "beneficial_owner_count": len(beneficial_owners),
        "beneficial_owner_access": beneficial_owner_access,
        "registered_on": registered_on,
        "municipality": municipality,
    }
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
