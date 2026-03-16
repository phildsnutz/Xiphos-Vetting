"""
GLEIF LEI Connector - LIVE API

Real-time queries to the Global LEI Foundation API for:
  - Legal Entity Identifier validation and lookup
  - Direct and ultimate parent relationships
  - Registration status (active, lapsed, retired)
  - Entity legal form and jurisdiction

Free API, no registration required.
API: https://api.gleif.org/api/v1
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

from . import EnrichmentResult, Finding

BASE = "https://api.gleif.org/api/v1"
USER_AGENT = "Xiphos/4.0 (compliance-tool@xiphos.dev)"


def _get(url: str) -> dict | None:
    """GET request to GLEIF API with proper headers."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.api+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query GLEIF API for LEI data and ownership chains."""
    t0 = time.time()
    result = EnrichmentResult(source="gleif_lei", vendor_name=vendor_name)

    try:
        lei = ids.get("lei")

        # Step 1: Search for LEI if not provided - LIVE API call
        if not lei:
            encoded_name = urllib.parse.quote(vendor_name)
            url = f"{BASE}/lei-records?filter[entity.names]={encoded_name}&page[size]=5"

            records_data = _get(url)
            if records_data and "data" in records_data:
                records = records_data.get("data", [])
                if records:
                    lei = records[0].get("id", "")

        if not lei:
            result.findings.append(Finding(
                source="gleif_lei", category="identity",
                title="No LEI found",
                detail=f"No Legal Entity Identifier found for '{vendor_name}' in GLEIF API.",
                severity="info", confidence=0.7,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Step 2: Get full LEI record - LIVE API call
        url = f"{BASE}/lei-records/{lei}"
        record = _get(url)

        if record and "data" in record:
            data = record["data"]
            attrs = data.get("attributes", {})
            entity = attrs.get("entity", {})
            reg = attrs.get("registration", {})

            legal_name = entity.get("legalName", {}).get("name", "") if isinstance(entity.get("legalName"), dict) else str(entity.get("legalName", ""))
            legal_jurisdiction = entity.get("jurisdiction", "")
            legal_form = entity.get("legalForm", {}).get("id", "") if isinstance(entity.get("legalForm"), dict) else str(entity.get("legalForm", ""))
            status = entity.get("status", "")
            reg_status = reg.get("status", "")
            initial_reg = reg.get("initialRegistrationDate", "")
            next_renewal = reg.get("nextRenewalDate", "")

            # Addresses
            legal_addr = entity.get("legalAddress", {})
            hq_addr = entity.get("headquartersAddress", {})

            legal_country = legal_addr.get("country", "")
            hq_country = hq_addr.get("country", "")

            result.identifiers["lei"] = lei
            result.identifiers["legal_jurisdiction"] = legal_jurisdiction
            result.identifiers["legal_name"] = legal_name

            detail_parts = [
                f"LEI: {lei}",
                f"Legal Name: {legal_name}",
                f"Status: {status}",
                f"Registration Status: {reg_status}",
                f"Jurisdiction: {legal_jurisdiction}",
                f"Legal Form: {legal_form}",
                f"Registered: {initial_reg}",
                f"Next Renewal: {next_renewal}",
                f"Legal Address Country: {legal_country}",
                f"HQ Country: {hq_country}",
            ]

            result.findings.append(Finding(
                source="gleif_lei", category="identity",
                title=f"LEI verified: {legal_name}",
                detail="\n".join(detail_parts),
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
                    "detail": f"LEI registration lapsed - not renewed since {next_renewal}",
                })
                result.findings.append(Finding(
                    source="gleif_lei", category="data_quality",
                    title="LEI registration lapsed",
                    detail=f"LEI {lei} registration not renewed. May indicate operational changes.",
                    severity="medium", confidence=0.9,
                ))

            if status == "INACTIVE":
                result.risk_signals.append({
                    "signal": "lei_entity_inactive",
                    "severity": "high",
                    "detail": "Entity status is INACTIVE in GLEIF records",
                })

            # Jurisdiction mismatch
            if country and legal_country and country.upper() != legal_country.upper():
                result.risk_signals.append({
                    "signal": "jurisdiction_mismatch",
                    "severity": "low",
                    "detail": f"Vendor country ({country}) differs from LEI jurisdiction ({legal_country})",
                })

            time.sleep(0.15)

            # Step 3: Get parent relationships - LIVE API calls
            parent_url = f"{BASE}/lei-records/{lei}/direct-parent"
            parent_data = _get(parent_url)

            if parent_data and "data" in parent_data:
                parent = parent_data["data"]
                if parent:
                    parent_lei = parent.get("id", "")
                    if parent_lei:
                        # Look up parent details
                        parent_detail_url = f"{BASE}/lei-records/{parent_lei}"
                        parent_detail = _get(parent_detail_url)
                        parent_name = ""
                        parent_country = ""

                        if parent_detail and "data" in parent_detail:
                            p_entity = parent_detail["data"].get("attributes", {}).get("entity", {})
                            parent_name = p_entity.get("legalName", {}).get("name", "") if isinstance(p_entity.get("legalName"), dict) else str(p_entity.get("legalName", ""))
                            parent_country = p_entity.get("legalAddress", {}).get("country", "")

                        result.findings.append(Finding(
                            source="gleif_lei", category="ownership",
                            title=f"Direct parent: {parent_name or parent_lei}",
                            detail=f"LEI: {parent_lei}\nCountry: {parent_country}",
                            severity="info", confidence=0.9,
                            url=f"https://search.gleif.org/#/record/{parent_lei}",
                        ))

                        result.relationships.append({
                            "type": "direct_parent",
                            "parent_lei": parent_lei,
                            "parent_name": parent_name,
                            "parent_country": parent_country,
                        })

                        time.sleep(0.15)

            # Ultimate parent
            ultimate_url = f"{BASE}/lei-records/{lei}/ultimate-parent"
            ultimate_data = _get(ultimate_url)

            if ultimate_data and "data" in ultimate_data:
                ultimate = ultimate_data["data"]
                if ultimate:
                    ultimate_lei = ultimate.get("id", "")
                    if ultimate_lei and ultimate_lei != parent_lei if 'parent_lei' in locals() else True:
                        ultimate_detail_url = f"{BASE}/lei-records/{ultimate_lei}"
                        ultimate_detail = _get(ultimate_detail_url)
                        ultimate_name = ""
                        ultimate_country = ""

                        if ultimate_detail and "data" in ultimate_detail:
                            u_entity = ultimate_detail["data"].get("attributes", {}).get("entity", {})
                            ultimate_name = u_entity.get("legalName", {}).get("name", "") if isinstance(u_entity.get("legalName"), dict) else str(u_entity.get("legalName", ""))
                            ultimate_country = u_entity.get("legalAddress", {}).get("country", "")

                        result.findings.append(Finding(
                            source="gleif_lei", category="ownership",
                            title=f"Ultimate parent: {ultimate_name or ultimate_lei}",
                            detail=f"LEI: {ultimate_lei}\nCountry: {ultimate_country}",
                            severity="info", confidence=0.9,
                            url=f"https://search.gleif.org/#/record/{ultimate_lei}",
                        ))

                        result.relationships.append({
                            "type": "ultimate_parent",
                            "parent_lei": ultimate_lei,
                            "parent_name": ultimate_name,
                            "parent_country": ultimate_country,
                        })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
