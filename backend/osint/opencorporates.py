"""
OpenCorporates Connector

Queries the OpenCorporates API for:
  - Company search and identity resolution
  - Officers and directors
  - Filings and status
  - Jurisdiction and incorporation details
  - Branch/subsidiary detection

Free tier: limited requests, no API key needed for basic search.
Paid tiers available for production use.
API docs: https://api.opencorporates.com/documentation/API-Reference
"""

import json
import os
import time
import urllib.request
import urllib.error

from . import EnrichmentResult, Finding

BASE = "https://api.opencorporates.com/v0.4"
USER_AGENT = "Xiphos-Vetting/2.1"

# Set XIPHOS_OPENCORP_KEY for higher rate limits
API_KEY = os.environ.get("XIPHOS_OPENCORP_KEY", "")


def _get(url: str) -> dict | None:
    if API_KEY:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}api_token={API_KEY}"

    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _search_companies(name: str, jurisdiction: str = "") -> list[dict]:
    """Search for companies by name."""
    encoded = urllib.request.quote(name)
    url = f"{BASE}/companies/search?q={encoded}&per_page=5"
    if jurisdiction:
        url += f"&jurisdiction_code={jurisdiction.lower()}"
    data = _get(url)
    if not data:
        return []
    results = data.get("results", {})
    companies = results.get("companies", [])
    return [c.get("company", {}) for c in companies]


def _get_company(jurisdiction: str, company_number: str) -> dict | None:
    """Get full company details."""
    url = f"{BASE}/companies/{jurisdiction.lower()}/{company_number}"
    data = _get(url)
    if not data:
        return None
    return data.get("results", {}).get("company", {})


def _get_officers(jurisdiction: str, company_number: str) -> list[dict]:
    """Get officers/directors for a company."""
    url = f"{BASE}/companies/{jurisdiction.lower()}/{company_number}/officers?per_page=20"
    data = _get(url)
    if not data:
        return []
    officers = data.get("results", {}).get("officers", [])
    return [o.get("officer", {}) for o in officers]


# Map two-letter country codes to OpenCorporates jurisdiction codes
COUNTRY_TO_JURISDICTION = {
    "US": "us", "GB": "gb", "UK": "gb", "DE": "de", "FR": "fr",
    "CA": "ca", "AU": "au", "IE": "ie", "NL": "nl", "CH": "ch",
    "JP": "jp", "SG": "sg", "HK": "hk", "IN": "in", "BR": "br",
    "IL": "il", "KR": "kr", "SE": "se", "NO": "no", "DK": "dk",
    "FI": "fi", "IT": "it", "ES": "es", "BE": "be", "AT": "at",
}


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query OpenCorporates for company data."""
    t0 = time.time()
    result = EnrichmentResult(source="opencorporates", vendor_name=vendor_name)

    try:
        # OpenCorporates API requires an API token
        if not API_KEY:
            result.findings.append(Finding(
                source="opencorporates", category="configuration",
                title="OpenCorporates API key not configured",
                detail="Set XIPHOS_OPENCORP_KEY environment variable with an API token from "
                       "https://opencorporates.com/api_accounts/new to enable corporate registry lookups. "
                       "Free tier available for low-volume use.",
                severity="info", confidence=1.0,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        jurisdiction = COUNTRY_TO_JURISDICTION.get(country.upper(), "")

        # Step 1: Search for company
        companies = _search_companies(vendor_name, jurisdiction)

        if not companies:
            # Try without jurisdiction filter
            if jurisdiction:
                companies = _search_companies(vendor_name)

        if not companies:
            result.findings.append(Finding(
                source="opencorporates", category="identity",
                title="No OpenCorporates match",
                detail=f"No company records found for '{vendor_name}' in OpenCorporates. "
                       f"Entity may use a different legal name or may not be in covered jurisdictions.",
                severity="info", confidence=0.4,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Use the best match
        company = companies[0]
        co_name = company.get("name", "")
        co_number = company.get("company_number", "")
        co_jurisdiction = company.get("jurisdiction_code", "")
        co_status = company.get("current_status", "")
        co_type = company.get("company_type", "")
        co_incorporation_date = company.get("incorporation_date", "")
        co_dissolution_date = company.get("dissolution_date", "")
        co_registered_address = company.get("registered_address_in_full", "")
        co_url = company.get("opencorporates_url", "")
        result.identifiers["opencorporates_url"] = co_url
        result.identifiers["company_number"] = co_number
        result.identifiers["jurisdiction"] = co_jurisdiction
        if co_incorporation_date:
            result.identifiers["incorporation_date"] = co_incorporation_date
        if co_type:
            result.identifiers["company_type"] = co_type

        result.findings.append(Finding(
            source="opencorporates", category="identity",
            title=f"Corporate record: {co_name}",
            detail=(
                f"Number: {co_number} | Jurisdiction: {co_jurisdiction} | "
                f"Status: {co_status} | Type: {co_type} | "
                f"Incorporated: {co_incorporation_date} | "
                f"Address: {co_registered_address}"
            ),
            severity="info", confidence=0.85,
            url=co_url,
            raw_data=company,
        ))

        # Status checks
        if co_status and co_status.lower() in ("dissolved", "liquidation", "struck off", "inactive", "closed"):
            result.risk_signals.append({
                "signal": "company_dissolved",
                "severity": "high",
                "detail": f"Company status: {co_status} (dissolved/inactive)",
            })
            result.findings.append(Finding(
                source="opencorporates", category="status",
                title=f"Company status: {co_status}",
                detail=f"'{co_name}' is listed as '{co_status}' in {co_jurisdiction}. "
                       f"Dissolution date: {co_dissolution_date or 'N/A'}.",
                severity="high", confidence=0.9,
                url=co_url,
            ))

        # Very recent incorporation (potential shell)
        if co_incorporation_date:
            try:
                from datetime import datetime
                inc_date = datetime.strptime(co_incorporation_date, "%Y-%m-%d")
                age_days = (datetime.now() - inc_date).days
                if age_days < 365:
                    result.risk_signals.append({
                        "signal": "recently_incorporated",
                        "severity": "medium",
                        "detail": f"Incorporated {age_days} days ago ({co_incorporation_date})",
                    })
                    result.findings.append(Finding(
                        source="opencorporates", category="status",
                        title=f"Recently incorporated ({age_days} days ago)",
                        detail=f"'{co_name}' was incorporated on {co_incorporation_date}. "
                               f"Very young companies may warrant additional due diligence.",
                        severity="medium", confidence=0.8,
                    ))
            except (ValueError, TypeError):
                pass

        time.sleep(0.5)  # Rate limiting for free tier

        # Step 2: Get officers if we have the details
        if co_jurisdiction and co_number:
            officers = _get_officers(co_jurisdiction, co_number)

            if officers:
                officer_names = []
                for off in officers[:15]:
                    off_name = off.get("name", "")
                    off_position = off.get("position", "")
                    off_start = off.get("start_date", "")
                    off_end = off.get("end_date", "")
                    off_inactive = off.get("inactive", False)

                    if off_name:
                        officer_names.append(f"{off_name} ({off_position})")
                        if not off_inactive:
                            result.relationships.append({
                                "type": "officer_of",
                                "source_entity": off_name,
                                "target_entity": co_name,
                                "source_entity_type": "person",
                                "target_entity_type": "company",
                                "data_source": "opencorporates",
                                "confidence": 0.82,
                                "evidence": (
                                    f"OpenCorporates lists {off_name} as {off_position or 'an officer'} "
                                    f"of {co_name} in {co_jurisdiction}."
                                ),
                                "evidence_url": f"{co_url}/officers" if co_url else "",
                                "structured_fields": {
                                    "position": off_position,
                                    "start_date": off_start,
                                    "end_date": off_end,
                                    "inactive": bool(off_inactive),
                                    "company_number": co_number,
                                    "jurisdiction": co_jurisdiction,
                                    "standards": ["OpenCorporates Officers"],
                                },
                                "authority_level": "public_registry_aggregator",
                                "access_model": "public_api",
                                "source_class": "public_connector",
                            })

                active_count = sum(1 for o in officers if not o.get("inactive", False))
                result.identifiers["officers_count"] = active_count
                result.findings.append(Finding(
                    source="opencorporates", category="officers",
                    title=f"Officers/directors: {active_count} active, {len(officers)} total",
                    detail=f"Key personnel: {'; '.join(officer_names[:8])}",
                    severity="info", confidence=0.8,
                    url=f"{co_url}/officers" if co_url else "",
                ))

                # Check for frequent director turnover
                resigned = [o for o in officers if o.get("end_date")]
                if len(resigned) > 5:
                    result.risk_signals.append({
                        "signal": "high_director_turnover",
                        "severity": "low",
                        "detail": f"{len(resigned)} officers have end dates (potential high turnover)",
                    })

            # Report other matches (potential related entities)
            if len(companies) > 1:
                related = [c.get("name", "") for c in companies[1:4]]
                if related:
                    result.findings.append(Finding(
                        source="opencorporates", category="related",
                        title=f"Similar entities found: {len(companies) - 1}",
                        detail=f"Other matches: {'; '.join(related)}. May indicate subsidiaries, branches, or namesakes.",
                        severity="info", confidence=0.5,
                    ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
