"""
DoD SAM.gov Exclusions (EPLS) Connector

Checks if a vendor is on the Excluded Parties List System (EPLS).
Uses the public SAM.gov API: https://api.sam.gov/entity-information/v3/exclusions

This is a primary sanctions/exclusions check. If the API is unreachable,
returns a simulated finding based on vendor name/country characteristics.

API docs: https://open.gsa.gov/api/entity-api/
"""

import json
import time
import urllib.request
import urllib.error
from typing import Optional

from . import EnrichmentResult, Finding

BASE = "https://api.sam.gov/entity-information/v3/exclusions"

# Public demo key (limited)
DEMO_KEY = "DEMO_KEY"

import os
API_KEY = os.environ.get("XIPHOS_SAM_API_KEY", DEMO_KEY)

USER_AGENT = "Xiphos-Vetting/2.1"


def _get(url: str) -> dict | None:
    """GET with optional API key."""
    sep = "&" if "?" in url else "?"
    url_with_key = f"{url}{sep}api_key={API_KEY}"

    req = urllib.request.Request(url_with_key, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _simulated_finding(vendor_name: str, country: str = "") -> bool:
    """
    Simulate a finding based on vendor name/country characteristics.
    Returns True if vendor should be flagged (simulated match).
    """
    # Simulate matching based on name patterns (for demo purposes)
    name_lower = vendor_name.lower()
    suspicious_patterns = ["tech", "defense", "military", "arms", "export"]

    # If from certain countries and has suspicious keywords
    risky_countries = ["CN", "RU", "IR", "KP", "CU", "VE"]
    has_suspicious = any(p in name_lower for p in suspicious_patterns)

    return country in risky_countries and has_suspicious


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query SAM.gov EPLS for vendor exclusion status."""
    t0 = time.time()
    result = EnrichmentResult(source="dod_sam_exclusions", vendor_name=vendor_name)

    try:
        # Try to query the API
        encoded = urllib.request.quote(vendor_name)
        url = f"{BASE}?q={encoded}&page=0&size=10"
        data = _get(url)

        api_available = data is not None

        if api_available and data:
            results = data.get("results", [])

            if results:
                # Found exclusions
                for exc in results[:5]:
                    exc_name = exc.get("name", "")
                    exc_type = exc.get("exclusionType", "")
                    reason = exc.get("reason", "")
                    agency = exc.get("excludingAgency", "")
                    active_date = exc.get("activeDate", "")

                    result.findings.append(Finding(
                        source="dod_sam_exclusions",
                        category="exclusion",
                        title=f"DoD EPLS MATCH: {exc_name}",
                        detail=(
                            f"Type: {exc_type} | Reason: {reason} | "
                            f"Agency: {agency} | Active: {active_date}"
                        ),
                        severity="critical",
                        confidence=0.95,
                        url="https://sam.gov/content/exclusions",
                        raw_data=exc,
                    ))

                    result.risk_signals.append({
                        "signal": "dod_sam_exclusion",
                        "severity": "critical",
                        "detail": f"Excluded from federal contracts: {exc_type}",
                    })
            else:
                # API check succeeded, no match found
                result.findings.append(Finding(
                    source="dod_sam_exclusions",
                    category="clearance",
                    title="DoD EPLS: Vendor not on exclusions list",
                    detail=f"'{vendor_name}' verified not on DoD Excluded Parties List.",
                    severity="info",
                    confidence=0.95,
                ))

        else:
            # API unreachable - use simulation
            if _simulated_finding(vendor_name, country):
                result.findings.append(Finding(
                    source="dod_sam_exclusions",
                    category="exclusion",
                    title=f"DoD EPLS WARNING: Vendor profile suggests risk",
                    detail=(
                        f"'{vendor_name}' from {country or 'Unknown'} matches risk profile. "
                        f"Unable to verify against live EPLS (API unavailable). "
                        f"Recommend manual verification at https://sam.gov"
                    ),
                    severity="critical",
                    confidence=0.65,
                    url="https://sam.gov/content/exclusions",
                ))

                result.risk_signals.append({
                    "signal": "dod_sam_unreachable_risk",
                    "severity": "critical",
                    "detail": "Vendor profile suggests EPLS risk; API unavailable for verification",
                })
            else:
                result.findings.append(Finding(
                    source="dod_sam_exclusions",
                    category="clearance",
                    title="DoD EPLS: Unable to verify (API unavailable)",
                    detail=(
                        f"Cannot reach SAM.gov API (may be offline). "
                        f"Recommendation: verify '{vendor_name}' manually at https://sam.gov/content/exclusions"
                    ),
                    severity="info",
                    confidence=0.5,
                ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
