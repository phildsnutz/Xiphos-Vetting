"""France INPI / RNE official-registry connector.

This connector stays local-first and fixture-friendly:
it consumes a provider-neutral JSON export that mirrors official RNE identity
fields and, when lawfully available, gated beneficial-owner data.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from . import EnrichmentResult, Finding


SOURCE_NAME = "france_inpi_rne"
USER_AGENT = "Xiphos-Vetting/2.1"


def _normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _dataset_url(ids: dict) -> str:
    for key in ("france_inpi_rne_url", "inpi_rne_url", "france_registry_url"):
        value = str(ids.get(key) or "").strip()
        if value:
            return value
    return str(os.environ.get("XIPHOS_FRANCE_INPI_RNE_URL") or "").strip()


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
    known_siren = str(ids.get("fr_siren") or ids.get("siren") or "").strip()
    record_siren = str(record.get("fr_siren") or record.get("siren") or "").strip()
    if known_siren and record_siren == known_siren:
        return True
    if _normalize_name(record.get("entity_name") or record.get("registered_name") or record.get("name") or "") != _normalize_name(vendor_name):
        return False
    country_code = str(country or "").strip().upper()
    if country_code and country_code not in {"FR", "FRA"}:
        return False
    return True


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    started = time.perf_counter()
    result = EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        source_class="public_connector",
        authority_level="official_registry",
        access_model="gated_api",
    )

    if country and str(country).strip().upper() not in {"", "FR", "FRA"}:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    dataset_url = _dataset_url(ids)
    if not dataset_url:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    payload = _fetch_json(dataset_url)
    if not isinstance(payload, dict):
        result.error = "Unable to fetch France INPI / RNE dataset"
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    records = payload.get("records") or payload.get("entities") or payload.get("companies")
    if not isinstance(records, list):
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="corporate_identity",
                title="France INPI / RNE dataset shape unsupported",
                detail=(
                    "The configured France INPI / RNE dataset does not expose a top-level "
                    "`records`, `entities`, or `companies` array in the expected provider-neutral format."
                ),
                severity="info",
                confidence=0.8,
                url=dataset_url,
                raw_data={"top_level_keys": sorted(payload.keys())[:12]},
                source_class="public_connector",
                authority_level="official_registry",
                access_model="gated_api",
            )
        )
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    record = next((item for item in records if isinstance(item, dict) and _record_matches(item, vendor_name, country, ids)), None)
    if not isinstance(record, dict):
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    entity_name = str(record.get("entity_name") or record.get("registered_name") or record.get("name") or vendor_name).strip()
    fr_siren = str(record.get("fr_siren") or record.get("siren") or "").strip()
    fr_siret = str(record.get("fr_siret") or record.get("siret") or "").strip()
    status = str(record.get("status") or record.get("entity_status") or "").strip()
    legal_form = str(record.get("legal_form") or record.get("entity_type") or "").strip()
    registered_on = str(record.get("registered_on") or record.get("registration_date") or "").strip()
    ape_code = str(record.get("ape_code") or record.get("naf_code") or "").strip()
    city = str(record.get("registered_city") or record.get("city") or "").strip()
    website = str(record.get("website") or "").strip()
    officers = [item for item in (record.get("officers") or record.get("representatives") or []) if isinstance(item, dict)]
    beneficial_owners = [item for item in (record.get("beneficial_owners") or []) if isinstance(item, dict)]
    beneficial_owner_access = str(record.get("beneficial_owner_access") or "").strip()

    if fr_siren:
        result.identifiers["fr_siren"] = fr_siren
    if fr_siret:
        result.identifiers["fr_siret"] = fr_siret
    if website:
        result.identifiers["website"] = website
    result.identifiers["france_inpi_rne_url"] = dataset_url

    severity = "info"
    if status.lower() in {"inactive", "dissolved", "deleted", "closed"}:
        severity = "high"
        result.risk_signals.append(
            {
                "signal": "france_entity_inactive",
                "source": SOURCE_NAME,
                "severity": "high",
                "confidence": 0.95,
                "summary": f"INPI lists {entity_name} as {status or 'inactive'}",
                "detail": f"Entity status is {status or 'inactive'} in France RNE data.",
            }
        )

    result.findings.append(
        Finding(
            source=SOURCE_NAME,
            category="corporate_identity",
            title=f"France INPI / RNE: {entity_name} ({status or 'unknown status'})",
            detail=(
                f"SIREN: {fr_siren or 'unavailable'}\n"
                f"SIRET: {fr_siret or 'unavailable'}\n"
                f"Legal form: {legal_form or 'unavailable'}\n"
                f"Registered on: {registered_on or 'unavailable'}\n"
                f"City: {city or 'unavailable'}\n"
                f"APE code: {ape_code or 'unavailable'}"
            ),
            severity=severity,
            confidence=0.92,
            url=dataset_url,
            raw_data={
                "fr_siren": fr_siren,
                "status": status,
                "legal_form": legal_form,
            },
            source_class="public_connector",
            authority_level="official_registry",
            access_model="gated_api",
            structured_fields={
                "summary": {
                    "fr_siren": fr_siren,
                    "status": status,
                    "legal_form": legal_form,
                    "officer_count": len(officers),
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
                title="France INPI beneficial-owner access posture",
                detail=beneficial_owner_access,
                severity="info",
                confidence=0.9,
                url=dataset_url,
                raw_data={"beneficial_owner_access": beneficial_owner_access},
                source_class="public_connector",
                authority_level="official_registry",
                access_model="gated_api",
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
                "target_identifiers": {"fr_siren": fr_siren},
                "country": "FR",
                "data_source": SOURCE_NAME,
                "confidence": 0.9,
                "evidence": "INPI / RNE representative record",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "role": str(officer.get("role") or officer.get("title") or "representative"),
                    "appointed_on": str(officer.get("appointed_on") or officer.get("start_date") or ""),
                    "ceased_on": str(officer.get("ceased_on") or officer.get("end_date") or ""),
                    "standards": ["INPI", "RNE"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "gated_api",
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
                "source_identifiers": {"fr_siren": fr_siren},
                "target_entity": owner_name,
                "target_entity_type": str(owner.get("entity_type") or "person"),
                "target_identifiers": owner.get("identifiers", {}) or {},
                "country": str(owner.get("country") or "FR"),
                "data_source": SOURCE_NAME,
                "confidence": 0.9,
                "evidence": "INPI beneficial-owner disclosure",
                "evidence_url": dataset_url,
                "artifact_ref": dataset_url,
                "structured_fields": {
                    "control_description": str(owner.get("control_description") or owner.get("description") or ""),
                    "share_pct": owner.get("share_pct"),
                    "standards": ["INPI", "RNE", "Beneficial Ownership"],
                },
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "gated_api",
            }
        )

    result.structured_fields["summary"] = {
        "fr_siren": fr_siren,
        "status": status,
        "legal_form": legal_form,
        "officer_count": len(officers),
        "beneficial_owner_count": len(beneficial_owners),
        "beneficial_owner_access": beneficial_owner_access,
    }
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
