"""
GLEIF LEI Connector

Queries the Global LEI Foundation API for:
  - Legal Entity Identifier validation and lookup
  - Direct and ultimate parent relationships
  - Registration status (active, lapsed, retired)
  - Entity legal form and jurisdiction

Free API, no registration required, up to 200 records per request.
API docs: https://www.gleif.org/en/lei-data/gleif-api
"""

import json
import time
import urllib.request
import urllib.error
from typing import Optional

from . import EnrichmentResult, Finding

BASE = "https://api.gleif.org/api/v1"
USER_AGENT = "Xiphos-Vetting/2.1"


def _get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.api+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _search_lei(name: str) -> list[dict]:
    """Fuzzy search for LEI records by entity name."""
    encoded = urllib.request.quote(name)
    url = f"{BASE}/lei-records?filter[fulltext]={encoded}&page[size]=5"
    data = _get(url)
    if not data:
        return []
    return data.get("data", [])


def _get_relationships(lei: str) -> dict:
    """Get direct and ultimate parent for a given LEI."""
    parents = {}

    # Direct parent
    url = f"{BASE}/lei-records/{lei}/direct-parent"
    data = _get(url)
    if data and "data" in data:
        parent = data["data"]
        if parent:
            attrs = parent.get("attributes", {})
            rel = attrs.get("relationship", {})
            parents["direct_parent"] = {
                "lei": parent.get("id", ""),
                "type": rel.get("type", ""),
                "status": rel.get("status", ""),
            }

    # Ultimate parent
    url = f"{BASE}/lei-records/{lei}/ultimate-parent"
    data = _get(url)
    if data and "data" in data:
        parent = data["data"]
        if parent:
            attrs = parent.get("attributes", {})
            rel = attrs.get("relationship", {})
            parents["ultimate_parent"] = {
                "lei": parent.get("id", ""),
                "type": rel.get("type", ""),
                "status": rel.get("status", ""),
            }

    return parents


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query GLEIF for LEI data and ownership chains."""
    t0 = time.time()
    result = EnrichmentResult(source="gleif_lei", vendor_name=vendor_name)

    try:
        lei = ids.get("lei")

        # Step 1: Search for LEI if not provided
        if not lei:
            records = _search_lei(vendor_name)
            if records:
                # Use first match
                rec = records[0]
                lei = rec.get("id", "")

        if not lei:
            result.findings.append(Finding(
                source="gleif_lei", category="identity",
                title="No LEI found",
                detail=f"No Legal Entity Identifier found for '{vendor_name}'. "
                       f"Entity may not have an LEI or name may not match GLEIF records.",
                severity="info", confidence=0.5,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Step 2: Get full LEI record
        url = f"{BASE}/lei-records/{lei}"
        record = _get(url)

        if record and "data" in record:
            data = record["data"]
            attrs = data.get("attributes", {})
            entity = attrs.get("entity", {})
            reg = attrs.get("registration", {})

            legal_name = entity.get("legalName", {}).get("name", "")
            legal_jurisdiction = entity.get("jurisdiction", "")
            legal_form = entity.get("legalForm", {}).get("id", "")
            status = entity.get("status", "")
            reg_status = reg.get("status", "")
            initial_reg = reg.get("initialRegistrationDate", "")
            next_renewal = reg.get("nextRenewalDate", "")
            managing_lou = reg.get("managingLou", "")

            # Addresses
            legal_addr = entity.get("legalAddress", {})
            hq_addr = entity.get("headquartersAddress", {})

            legal_country = legal_addr.get("country", "")
            hq_country = hq_addr.get("country", "")

            result.identifiers["lei"] = lei
            result.identifiers["legal_jurisdiction"] = legal_jurisdiction

            result.findings.append(Finding(
                source="gleif_lei", category="identity",
                title=f"LEI verified: {legal_name}",
                detail=(
                    f"LEI: {lei} | Status: {status} | Registration: {reg_status} | "
                    f"Jurisdiction: {legal_jurisdiction} | Legal form: {legal_form} | "
                    f"Registered: {initial_reg} | Next renewal: {next_renewal} | "
                    f"Legal address country: {legal_country} | HQ country: {hq_country}"
                ),
                severity="info", confidence=0.95,
                url=f"https://search.gleif.org/#/record/{lei}",
                raw_data={"lei": lei, "status": status, "reg_status": reg_status,
                          "jurisdiction": legal_jurisdiction},
            ))

            # Check registration health
            if reg_status == "LAPSED":
                result.risk_signals.append({
                    "signal": "lei_lapsed",
                    "severity": "medium",
                    "detail": f"LEI registration has lapsed (not renewed since {next_renewal})",
                })
                result.findings.append(Finding(
                    source="gleif_lei", category="data_quality",
                    title="LEI registration lapsed",
                    detail=f"LEI {lei} has LAPSED registration status. Entity has not renewed. "
                           f"This may indicate reduced transparency or operational changes.",
                    severity="medium", confidence=0.9,
                ))

            if status == "INACTIVE":
                result.risk_signals.append({
                    "signal": "lei_entity_inactive",
                    "severity": "high",
                    "detail": "GLEIF reports entity as INACTIVE",
                })

            # Jurisdiction mismatch detection
            if country and legal_country and country.upper() != legal_country.upper():
                result.risk_signals.append({
                    "signal": "jurisdiction_mismatch",
                    "severity": "low",
                    "detail": f"Vendor country ({country}) differs from LEI legal jurisdiction ({legal_country})",
                })

            time.sleep(0.15)

            # Step 3: Get parent relationships
            parents = _get_relationships(lei)

            for rel_type, info in parents.items():
                parent_lei = info.get("lei", "")
                if parent_lei:
                    # Look up parent name
                    parent_url = f"{BASE}/lei-records/{parent_lei}"
                    parent_data = _get(parent_url)
                    parent_name = ""
                    parent_country = ""
                    if parent_data and "data" in parent_data:
                        p_entity = parent_data["data"].get("attributes", {}).get("entity", {})
                        parent_name = p_entity.get("legalName", {}).get("name", "")
                        parent_country = p_entity.get("legalAddress", {}).get("country", "")

                    label = "Direct parent" if rel_type == "direct_parent" else "Ultimate parent"
                    result.findings.append(Finding(
                        source="gleif_lei", category="ownership",
                        title=f"{label}: {parent_name or parent_lei}",
                        detail=f"LEI: {parent_lei} | Country: {parent_country} | Relationship: {info.get('type', 'N/A')}",
                        severity="info", confidence=0.9,
                        url=f"https://search.gleif.org/#/record/{parent_lei}",
                    ))

                    result.relationships.append({
                        "type": rel_type,
                        "parent_lei": parent_lei,
                        "parent_name": parent_name,
                        "parent_country": parent_country,
                    })

                    time.sleep(0.15)

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
