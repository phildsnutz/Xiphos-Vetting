"""
SAM.gov Connector

Queries the GSA Entity Management API for:
  - Entity registration status (UEI, CAGE, DUNS)
  - Exclusion records (debarment, suspension, ineligibility)
  - Entity details (address, business type, NAICS codes)

Free public API: 10 requests/day without key, 1000/day with key.
API docs: https://open.gsa.gov/api/entity-api/
"""

import json
import time
import urllib.request
import urllib.error
from typing import Optional

from . import EnrichmentResult, Finding

# Public API base -- no key needed for basic access (10/day)
BASE = "https://api.sam.gov/entity-information/v3"
EXCLUSIONS_BASE = "https://api.sam.gov/entity-information/v2/exclusions"

# For higher rate limits, set XIPHOS_SAM_API_KEY env var
import os
API_KEY = os.environ.get("XIPHOS_SAM_API_KEY", "")

USER_AGENT = "Xiphos-Vetting/2.1"


def _get(url: str) -> dict | None:
    """GET with optional API key."""
    if API_KEY:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}api_key={API_KEY}"

    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _search_entities(name: str) -> list[dict]:
    """Search for entity registrations by name. Requires API key."""
    if not API_KEY:
        return []  # API key required for entity search
    encoded = urllib.request.quote(name)
    url = f"{BASE}/entities?legalBusinessName={encoded}&registrationStatus=A&includeSections=entityRegistration&page=0&size=5"
    data = _get(url)
    if not data:
        return []
    return data.get("entityData", [])


def _search_exclusions(name: str) -> list[dict]:
    """Search for exclusion records by name. Requires API key."""
    if not API_KEY:
        return []  # API key required for exclusion search
    encoded = urllib.request.quote(name)
    url = f"{EXCLUSIONS_BASE}?q={encoded}&page=0&size=10"
    data = _get(url)
    if not data:
        return []
    return data.get("results", [])


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query SAM.gov for entity registration and exclusion data."""
    t0 = time.time()
    result = EnrichmentResult(source="sam_gov", vendor_name=vendor_name)

    try:
        # SAM.gov requires a free API key from https://sam.gov/content/entity-information
        if not API_KEY:
            result.findings.append(Finding(
                source="sam_gov", category="configuration",
                title="SAM.gov API key not configured",
                detail="Set XIPHOS_SAM_API_KEY environment variable with a free key from "
                       "https://sam.gov/content/entity-information to enable SAM.gov lookups. "
                       "Free tier: 10 requests/day. Production: 1,000/day.",
                severity="info", confidence=1.0,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Step 1: Search for entity registration
        entities = _search_entities(vendor_name)

        if entities:
            for entity in entities[:3]:
                reg = entity.get("entityRegistration", {})
                uei = reg.get("ueiSAM", "")
                cage = reg.get("cageCode", "")
                legal_name = reg.get("legalBusinessName", "")
                dba = reg.get("dbaName", "")
                status = reg.get("registrationStatus", "")
                expiry = reg.get("registrationExpirationDate", "")
                entity_url = reg.get("entityURL", "")
                purpose = reg.get("purposeOfRegistrationDesc", "")

                # Physical address
                addr = reg.get("physicalAddress", {})
                city = addr.get("city", "")
                state_province = addr.get("stateOrProvinceCode", "")
                country_code = addr.get("countryCode", "")
                zip_code = addr.get("zipCode", "")

                # Business types
                biz_types = reg.get("businessTypes", [])

                if uei:
                    result.identifiers["uei"] = uei
                if cage:
                    result.identifiers["cage"] = cage

                result.findings.append(Finding(
                    source="sam_gov", category="registration",
                    title=f"SAM registered: {legal_name}",
                    detail=(
                        f"UEI: {uei} | CAGE: {cage} | Status: {status} | "
                        f"Expires: {expiry} | Location: {city}, {state_province} {country_code} {zip_code} | "
                        f"Purpose: {purpose}"
                    ),
                    severity="info", confidence=0.9,
                    url=f"https://sam.gov/entity/{uei}",
                    raw_data={"uei": uei, "cage": cage, "status": status,
                              "business_types": biz_types, "expiry": expiry},
                ))

                # Check registration health
                if status != "Active":
                    result.risk_signals.append({
                        "signal": "sam_inactive_registration",
                        "severity": "high",
                        "detail": f"SAM registration status: {status}",
                    })
                    result.findings.append(Finding(
                        source="sam_gov", category="registration",
                        title=f"SAM registration not active: {status}",
                        detail=f"Entity '{legal_name}' has SAM status '{status}'. Active registration required for federal contracts.",
                        severity="high", confidence=0.9,
                    ))

        else:
            result.findings.append(Finding(
                source="sam_gov", category="registration",
                title="No SAM registration found",
                detail=f"No active SAM.gov entity registration found for '{vendor_name}'. "
                       f"Entity may not be registered for federal contracting.",
                severity="medium" if country in ("US", "USA", "") else "info",
                confidence=0.6,
            ))

        time.sleep(0.5)  # Be respectful of rate limits

        # Step 2: Check exclusions (debarment, suspension)
        exclusions = _search_exclusions(vendor_name)

        if exclusions:
            for exc in exclusions:
                exc_name = exc.get("name", "")
                exc_type = exc.get("exclusionType", "")
                exc_program = exc.get("exclusionProgram", "")
                agency = exc.get("excludingAgency", "")
                active_date = exc.get("activeDate", "")
                termination_date = exc.get("terminationDate", "")
                classification = exc.get("classification", {})
                class_type = classification.get("type", "")

                severity = "critical"
                if termination_date and termination_date < time.strftime("%Y-%m-%d"):
                    severity = "medium"  # Historical exclusion

                result.findings.append(Finding(
                    source="sam_gov", category="exclusion",
                    title=f"EXCLUSION: {exc_name} -- {exc_type}",
                    detail=(
                        f"Type: {exc_type} | Program: {exc_program} | Agency: {agency} | "
                        f"Active: {active_date} | Terminates: {termination_date or 'Indefinite'} | "
                        f"Classification: {class_type}"
                    ),
                    severity=severity, confidence=0.85,
                    url="https://sam.gov/search/?page=1&pageSize=25&sort=-relevance&sfm%5Bstatus%5D%5Bis_active%5D=true&sfm%5BsimpleSearch%5D%5BkeywordRadio%5D=ALL",
                    raw_data=exc,
                ))

                result.risk_signals.append({
                    "signal": "sam_exclusion",
                    "severity": severity,
                    "detail": f"{exc_type} by {agency}, active since {active_date}",
                })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
