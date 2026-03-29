"""
UK Companies House Connector

Queries the Companies House REST API for UK company data:
  - Company search and profile
  - Officers (directors, secretaries)
  - Persons with Significant Control (PSC) / Beneficial Ownership
  - Filing history
  - Company status (active, dissolved, liquidation)

API: https://developer.company-information.service.gov.uk/
Free API key required (register at developer portal).
Env: XIPHOS_COMPANIES_HOUSE_KEY

PSC data reveals beneficial ownership chains critical for
defense supply chain vetting of UK-incorporated entities.
"""

import json
import time
import base64
import urllib.request
import urllib.error
import urllib.parse
import os

from . import EnrichmentResult, Finding

BASE = "https://api.company-information.service.gov.uk"
USER_AGENT = "Xiphos-Vetting/2.1"


def _get_api_key() -> str:
    """Get Companies House API key from environment."""
    return os.environ.get("XIPHOS_COMPANIES_HOUSE_KEY", "")


def _get(url: str, api_key: str) -> dict | None:
    """GET request to Companies House API with Basic auth."""
    # Companies House uses API key as username with empty password
    auth = base64.b64encode(f"{api_key}:".encode()).decode()
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Authorization": f"Basic {auth}",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _search_company(name: str, api_key: str) -> list[dict]:
    """Search for a company by name."""
    encoded = urllib.parse.quote(name)
    url = f"{BASE}/search/companies?q={encoded}&items_per_page=5"
    data = _get(url, api_key)
    if data and "items" in data:
        return data["items"]
    return []


def _get_company_profile(company_number: str, api_key: str) -> dict | None:
    """Get detailed company profile."""
    url = f"{BASE}/company/{company_number}"
    return _get(url, api_key)


def _company_profile_search_stub(profile: dict, company_number: str) -> dict:
    address = profile.get("registered_office_address") or {}
    address_snippet = ", ".join(
        part
        for part in [
            str(address.get("address_line_1") or "").strip(),
            str(address.get("locality") or "").strip(),
            str(address.get("country") or "").strip(),
            str(address.get("postal_code") or "").strip(),
        ]
        if part
    )
    return {
        "company_number": company_number,
        "title": profile.get("company_name", ""),
        "company_status": profile.get("company_status", ""),
        "date_of_creation": profile.get("date_of_creation", ""),
        "company_type": profile.get("type", ""),
        "address_snippet": address_snippet,
    }


def _get_officers(company_number: str, api_key: str) -> list[dict]:
    """Get list of company officers."""
    url = f"{BASE}/company/{company_number}/officers?items_per_page=50"
    data = _get(url, api_key)
    if data and "items" in data:
        return data["items"]
    return []


def _get_psc(company_number: str, api_key: str) -> list[dict]:
    """Get Persons with Significant Control (beneficial owners)."""
    url = f"{BASE}/company/{company_number}/persons-with-significant-control?items_per_page=50"
    data = _get(url, api_key)
    if data and "items" in data:
        return data["items"]
    return []


def _get_psc_statements(company_number: str, api_key: str) -> list[dict]:
    """Get PSC statement records when available."""
    url = f"{BASE}/company/{company_number}/persons-with-significant-control-statements?items_per_page=50"
    data = _get(url, api_key)
    if data and "items" in data:
        return data["items"]
    return []


def _get_filing_history(company_number: str, api_key: str) -> list[dict]:
    """Get recent filing history records."""
    url = f"{BASE}/company/{company_number}/filing-history?items_per_page=25"
    data = _get(url, api_key)
    if data and "items" in data:
        return data["items"]
    return []


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query UK Companies House for company data and beneficial ownership."""
    t0 = time.time()
    result = EnrichmentResult(source="uk_companies_house", vendor_name=vendor_name)

    api_key = _get_api_key()
    if not api_key:
        result.findings.append(Finding(
            source="uk_companies_house",
            category="corporate_identity",
            title="UK Companies House: API key not configured",
            detail=(
                "Set XIPHOS_COMPANIES_HOUSE_KEY environment variable with a free API key "
                "from https://developer.company-information.service.gov.uk/"
            ),
            severity="info",
            confidence=1.0,
        ))
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    # Skip non-UK entities unless country is unknown
    if country and country.upper() not in ("GB", "UK", ""):
        result.findings.append(Finding(
            source="uk_companies_house",
            category="corporate_identity",
            title="UK Companies House: Non-UK entity skipped",
            detail=f"Companies House covers UK-registered entities only. Entity country: {country}",
            severity="info",
            confidence=1.0,
        ))
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    try:
        company_number = str(ids.get("uk_company_number") or ids.get("company_number") or "").strip()
        profile = None
        search_results: list[dict] = []

        # Step 1: Resolve the company either from a seeded official company number
        # or from public name search.
        if company_number:
            profile = _get_company_profile(company_number, api_key)
            if profile:
                search_results = [_company_profile_search_stub(profile, company_number)]
        if not search_results:
            search_results = _search_company(vendor_name, api_key)

        if not search_results:
            result.findings.append(Finding(
                source="uk_companies_house",
                category="corporate_identity",
                title="No UK Companies House matches",
                detail=f"No companies found matching '{vendor_name}' in the UK Companies House register.",
                severity="info",
                confidence=0.7,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Take the best match (first result)
        best = search_results[0]
        company_number = best.get("company_number", "")
        company_name = best.get("title", "")
        company_status = best.get("company_status", "")
        date_of_creation = best.get("date_of_creation", "")
        company_type = best.get("company_type", "")
        address_snippet = best.get("address_snippet", "")

        result.identifiers["uk_company_number"] = company_number

        # Company status check
        if company_status in ("dissolved", "liquidation", "receivership", "administration"):
            severity = "high"
            result.risk_signals.append({
                "signal": "uk_company_inactive",
                "severity": "high",
                "detail": f"Company '{company_name}' status: {company_status}",
                "company_number": company_number,
            })
        else:
            severity = "info"

        result.findings.append(Finding(
            source="uk_companies_house",
            category="corporate_identity",
            title=f"UK Company: {company_name} ({company_status})",
            detail=(
                f"Company Number: {company_number}\n"
                f"Name: {company_name}\n"
                f"Status: {company_status}\n"
                f"Type: {company_type}\n"
                f"Incorporated: {date_of_creation}\n"
                f"Address: {address_snippet}"
            ),
            severity=severity,
            confidence=0.9,
            url=f"https://find-and-update.company-information.service.gov.uk/company/{company_number}",
            raw_data=best,
        ))

        # Step 2: Get detailed profile
        time.sleep(0.3)
        profile = profile or _get_company_profile(company_number, api_key)
        if profile:
            sic_codes = profile.get("sic_codes", [])
            if sic_codes:
                result.identifiers["uk_sic_codes"] = ",".join(sic_codes)

            # Check for overseas entity flag
            if profile.get("is_community_interest_company"):
                result.findings.append(Finding(
                    source="uk_companies_house",
                    category="corporate_identity",
                    title="Community Interest Company (CIC)",
                    detail=f"{company_name} is registered as a Community Interest Company.",
                    severity="info",
                    confidence=1.0,
                ))

        # Step 3: Get officers
        time.sleep(0.3)
        officers = _get_officers(company_number, api_key)

        active_officers = [o for o in officers if not o.get("resigned_on")]
        resigned_officers = [o for o in officers if o.get("resigned_on")]

        if officers:
            officer_details = []
            for officer in active_officers[:10]:
                name = officer.get("name", "")
                role = officer.get("officer_role", "")
                appointed = officer.get("appointed_on", "")
                nationality = officer.get("nationality", "")
                officer_details.append(f"  {name} - {role} (appointed: {appointed}, nationality: {nationality})")

                # Add relationship for knowledge graph
                result.relationships.append({
                    "type": "officer_of",
                    "source_entity": name,
                    "target_entity": company_name,
                    "source_entity_type": "person",
                    "target_entity_type": "company",
                    "data_source": "uk_companies_house",
                    "confidence": 0.88,
                    "evidence": (
                        f"UK Companies House lists {name} as {role or 'an officer'} "
                        f"of {company_name}."
                    ),
                    "evidence_url": (
                        f"https://find-and-update.company-information.service.gov.uk/company/"
                        f"{company_number}/officers"
                    ),
                    "structured_fields": {
                        "role": role,
                        "appointed_on": appointed,
                        "nationality": nationality,
                        "company_number": company_number,
                        "standards": ["UK Companies House Officers Register"],
                    },
                    "authority_level": "official_registry",
                    "access_model": "public_api",
                    "source_class": "public_connector",
                })

            result.findings.append(Finding(
                source="uk_companies_house",
                category="officers",
                title=f"Officers: {len(active_officers)} active, {len(resigned_officers)} resigned",
                detail=(
                    f"Company: {company_name} ({company_number})\n"
                    f"Active Officers:\n" + "\n".join(officer_details[:10])
                ),
                severity="info",
                confidence=0.95,
                url=f"https://find-and-update.company-information.service.gov.uk/company/{company_number}/officers",
            ))

        # Step 4: Get PSC (Beneficial Ownership)
        time.sleep(0.3)
        pscs = _get_psc(company_number, api_key)

        if pscs:
            psc_details = []
            for psc in pscs:
                psc_name = psc.get("name", psc.get("name_elements", {}).get("surname", "Unknown"))
                kind = psc.get("kind", "")
                natures = psc.get("natures_of_control", [])
                notified = psc.get("notified_on", "")
                nationality = psc.get("nationality", "")
                country_of_residence = psc.get("country_of_residence", "")

                natures_str = ", ".join(natures) if natures else "Not specified"
                psc_details.append(
                    f"  {psc_name} ({kind})\n"
                    f"    Control: {natures_str}\n"
                    f"    Notified: {notified}\n"
                    f"    Nationality: {nationality}, Residence: {country_of_residence}"
                )

                # Check for corporate PSC (could indicate layered ownership)
                if "corporate" in kind.lower() or "legal" in kind.lower():
                    result.risk_signals.append({
                        "signal": "corporate_beneficial_owner",
                        "severity": "medium",
                        "detail": (
                            f"Corporate beneficial owner detected: {psc_name}. "
                            f"This may indicate layered ownership structure."
                        ),
                        "psc_name": psc_name,
                        "kind": kind,
                    })

                # Add relationship
                target_entity_type = "holding_company" if any(
                    token in kind.lower() for token in ("corporate", "legal")
                ) else "person"
                result.relationships.append({
                    "type": "beneficially_owned_by",
                    "source_entity": company_name,
                    "target_entity": psc_name,
                    "source_entity_type": "company",
                    "target_entity_type": target_entity_type,
                    "data_source": "uk_companies_house",
                    "confidence": 0.93,
                    "evidence": (
                        f"UK Companies House PSC register lists {psc_name} as a person with "
                        f"significant control over {company_name}."
                    ),
                    "evidence_url": (
                        f"https://find-and-update.company-information.service.gov.uk/company/"
                        f"{company_number}/persons-with-significant-control"
                    ),
                    "structured_fields": {
                        "kind": kind,
                        "natures_of_control": natures,
                        "notified_on": notified,
                        "nationality": nationality,
                        "country_of_residence": country_of_residence,
                        "company_number": company_number,
                        "standards": ["UK PSC Register"],
                    },
                    "authority_level": "official_registry",
                    "access_model": "public_api",
                    "source_class": "public_connector",
                })

            # Determine PSC severity
            corporate_pscs = [p for p in pscs if "corporate" in p.get("kind", "").lower()]
            psc_severity = "medium" if corporate_pscs else "info"

            result.findings.append(Finding(
                source="uk_companies_house",
                category="beneficial_ownership",
                title=f"PSC Register: {len(pscs)} persons with significant control",
                detail=(
                    f"Company: {company_name} ({company_number})\n"
                    f"Beneficial Owners:\n" + "\n".join(psc_details)
                ),
                severity=psc_severity,
                confidence=0.95,
                url=f"https://find-and-update.company-information.service.gov.uk/company/{company_number}/persons-with-significant-control",
            ))
        else:
            # No PSC data could be a red flag for larger companies
            result.findings.append(Finding(
                source="uk_companies_house",
                category="beneficial_ownership",
                title="No PSC data available",
                detail=(
                    f"No Persons with Significant Control found for {company_name}. "
                    f"This may indicate PSC exemption (e.g., traded on regulated market) "
                    f"or incomplete filing."
                ),
                severity="low",
                confidence=0.6,
            ))

        # Step 5: Get PSC statements
        time.sleep(0.3)
        psc_statements = _get_psc_statements(company_number, api_key)
        if psc_statements:
            statement_kinds = sorted(
                {
                    str(statement.get("statement") or statement.get("statement_type") or "").strip()
                    for statement in psc_statements
                    if str(statement.get("statement") or statement.get("statement_type") or "").strip()
                }
            )
            result.findings.append(Finding(
                source="uk_companies_house",
                category="beneficial_ownership",
                title=f"PSC statements: {len(psc_statements)} disclosure records",
                detail=(
                    f"Companies House exposes {len(psc_statements)} PSC statement records for {company_name}. "
                    + (f"Statement types: {', '.join(statement_kinds)}." if statement_kinds else "Statement types were not labeled in the response.")
                ),
                severity="info",
                confidence=0.88,
                url=f"https://find-and-update.company-information.service.gov.uk/company/{company_number}/persons-with-significant-control",
                raw_data={"statement_kinds": statement_kinds, "count": len(psc_statements)},
                structured_fields={
                    "company_number": company_number,
                    "statement_count": len(psc_statements),
                    "statement_kinds": statement_kinds,
                    "standards": ["UK PSC Register", "Companies House PSC Statements"],
                },
            ))

        # Step 6: Get filing history
        time.sleep(0.3)
        filing_history = _get_filing_history(company_number, api_key)
        if filing_history:
            recent_items = filing_history[:5]
            filing_categories = sorted(
                {
                    str(item.get("category") or "").strip()
                    for item in filing_history
                    if str(item.get("category") or "").strip()
                }
            )
            recent_lines = [
                f"  {item.get('date', '')} - {item.get('description', item.get('type', 'filing'))}"
                for item in recent_items
            ]
            result.findings.append(Finding(
                source="uk_companies_house",
                category="corporate_identity",
                title=f"Filing history: {len(filing_history)} recent Companies House records",
                detail=(
                    f"Recent filing activity for {company_name} ({company_number}).\n"
                    + "\n".join(recent_lines)
                    + (f"\nCategories: {', '.join(filing_categories)}" if filing_categories else "")
                ),
                severity="info",
                confidence=0.9,
                url=f"https://find-and-update.company-information.service.gov.uk/company/{company_number}/filing-history",
                raw_data={"count": len(filing_history), "categories": filing_categories},
                structured_fields={
                    "company_number": company_number,
                    "filing_count": len(filing_history),
                    "filing_categories": filing_categories,
                    "recent_filing_dates": [
                        str(item.get("date") or "")
                        for item in recent_items
                        if str(item.get("date") or "").strip()
                    ],
                    "standards": ["UK Companies House Filing History"],
                },
            ))

        # Check for other search results that might be related entities
        if len(search_results) > 1:
            related = []
            for sr in search_results[1:5]:
                related.append(f"  {sr.get('title', '')} ({sr.get('company_number', '')}) - {sr.get('company_status', '')}")
            if related:
                result.findings.append(Finding(
                    source="uk_companies_house",
                    category="related_entities",
                    title=f"Related UK companies: {len(search_results) - 1} additional matches",
                    detail="Other companies matching search:\n" + "\n".join(related),
                    severity="info",
                    confidence=0.5,
                ))

    except Exception as e:
        result.error = str(e)

    result.structured_fields = {
        "summary": {
            "company_number": result.identifiers.get("uk_company_number", ""),
            "company_status": company_status if "company_status" in locals() else "",
            "active_officer_count": len(active_officers) if "active_officers" in locals() else 0,
            "psc_count": len(pscs) if "pscs" in locals() else 0,
            "psc_statement_count": len(psc_statements) if "psc_statements" in locals() else 0,
            "filing_count": len(filing_history) if "filing_history" in locals() else 0,
        }
    }
    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
