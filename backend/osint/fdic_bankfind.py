"""
FDIC BankFind Connector

Queries the Federal Deposit Insurance Corporation (FDIC) public database
of insured institutions and bank failures.

Useful for:
  1. Vetting financial institutions (confirming legitimacy, active status)
  2. Detecting vendors falsely claiming to be banks
  3. Identifying failed banks in vendor history

APIs (free, no auth required):
  - Active institutions: GET https://banks.data.fdic.gov/api/institutions?search={name}&limit=10
  - Failed banks: GET https://banks.data.fdic.gov/api/failures?filters=INSTNAME:"{name}"&limit=10

Returns institution details: INSTNAME, CITY, STNAME, CERT, ACTIVE, ENDEFYMD, CHANGECODE, INSTCAT

Risk signals:
  - fdic_bank_failure: Found in failures database (severity "critical")
  - fdic_inactive_institution: ACTIVE != 1 (severity "high")
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

from . import EnrichmentResult, Finding

BANKS_API_URL = "https://banks.data.fdic.gov/api/institutions"
FAILURES_API_URL = "https://banks.data.fdic.gov/api/failures"
USER_AGENT = "Xiphos-Vetting/2.1"


def _search_banks(name: str, limit: int = 10) -> list[dict]:
    """Query active FDIC institutions."""
    params = urllib.parse.urlencode({
        "search": name,
        "limit": limit
    })
    url = f"{BANKS_API_URL}?{params}"

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
            result = json.loads(data)
            return result.get("data", [])
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return []


def _search_failures(name: str, limit: int = 10) -> list[dict]:
    """Query FDIC failed banks database."""
    filters = f'INSTNAME:"{name}"'
    params = urllib.parse.urlencode({
        "filters": filters,
        "limit": limit
    })
    url = f"{FAILURES_API_URL}?{params}"

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
            result = json.loads(data)
            return result.get("data", [])
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return []


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Screen a vendor against FDIC institution and failure databases."""
    t0 = time.time()
    result = EnrichmentResult(source="fdic_bankfind", vendor_name=vendor_name)

    # Search for failed banks first (higher priority)
    failures = _search_failures(vendor_name)

    if failures:
        for failure in failures:
            cert = failure.get("CERT", "unknown")
            inst_name = failure.get("INSTNAME", vendor_name)
            city = failure.get("CITY", "")
            state = failure.get("STNAME", "")
            fail_date = failure.get("FAILDATE", "")

            # Store identifier
            if cert and cert != "unknown":
                result.identifiers["fdic_cert"] = cert

            location = f"{city}, {state}".strip(", ")

            result.findings.append(Finding(
                source="fdic_bankfind", category="financial_regulatory",
                title=f"FDIC BANK FAILURE: {inst_name} (CERT {cert})",
                detail=(
                    f"Institution name: {inst_name} | Location: {location} | "
                    f"Certificate #: {cert} | Failure date: {fail_date}"
                ),
                severity="critical",
                confidence=0.95,
                url=f"https://banks.data.fdic.gov/api/failures?filters=CERT:{cert}",
                raw_data=failure,
            ))

            result.risk_signals.append({
                "signal": "fdic_bank_failure",
                "severity": "critical",
                "detail": f"Institution '{inst_name}' (CERT {cert}) failed on {fail_date}.",
            })
    else:
        # If no failures, search active institutions
        institutions = _search_banks(vendor_name)

        if institutions:
            for inst in institutions:
                cert = inst.get("CERT", "unknown")
                inst_name = inst.get("INSTNAME", vendor_name)
                city = inst.get("CITY", "")
                state = inst.get("STNAME", "")
                active = inst.get("ACTIVE", 0)
                end_date = inst.get("ENDEFYMD", "")
                inst_cat = inst.get("INSTCAT", "unknown")

                # Store identifier
                if cert and cert != "unknown":
                    result.identifiers["fdic_cert"] = cert

                location = f"{city}, {state}".strip(", ")

                if active == 1:
                    # Active institution
                    result.findings.append(Finding(
                        source="fdic_bankfind", category="financial_regulatory",
                        title=f"FDIC Insured Institution: {inst_name} (CERT {cert})",
                        detail=(
                            f"Institution name: {inst_name} | Location: {location} | "
                            f"Certificate #: {cert} | Status: ACTIVE | "
                            f"Category: {inst_cat}"
                        ),
                        severity="info",
                        confidence=0.9,
                        url=f"https://banks.data.fdic.gov/api/institutions?search={cert}",
                        raw_data=inst,
                    ))
                else:
                    # Inactive institution
                    result.findings.append(Finding(
                        source="fdic_bankfind", category="financial_regulatory",
                        title=f"FDIC Inactive Institution: {inst_name} (CERT {cert})",
                        detail=(
                            f"Institution name: {inst_name} | Location: {location} | "
                            f"Certificate #: {cert} | Status: INACTIVE | "
                            f"End of year date: {end_date} | Category: {inst_cat}"
                        ),
                        severity="high",
                        confidence=0.9,
                        url=f"https://banks.data.fdic.gov/api/institutions?search={cert}",
                        raw_data=inst,
                    ))

                    result.risk_signals.append({
                        "signal": "fdic_inactive_institution",
                        "severity": "high",
                        "detail": f"Institution '{inst_name}' (CERT {cert}) is marked as inactive.",
                    })
        else:
            # No matches in either database
            result.findings.append(Finding(
                source="fdic_bankfind", category="financial_regulatory",
                title="FDIC BankFind - No matches",
                detail=(
                    f"No active or failed institutions matching '{vendor_name}' found in FDIC databases. "
                    f"If vendor claims to be a financial institution, this is an informational finding. "
                    f"For defense contractors, no FDIC match is expected."
                ),
                severity="info",
                confidence=0.85,
            ))

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
