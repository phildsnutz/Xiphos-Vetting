"""
RECAP/CourtListener Free Litigation Connector

Queries the free CourtListener RECAP Archive for federal court litigation data
WITHOUT requiring a paid API key. RECAP is a free, open archive of PACER documents
maintained by Free Law Project.

Data sources:
  - CourtListener RECAP search API (free, no auth)
  - Covers millions of federal court docket entries
  - Includes case metadata, parties, and document availability

API: https://www.courtlistener.com/api/rest/v4/
Rate limit: ~100 requests/day for unauthenticated users
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
import logging
from typing import Optional

from . import EnrichmentResult, Finding

logger = logging.getLogger(__name__)

BASE_URL = "https://www.courtlistener.com/api/rest/v4"
USER_AGENT = "Xiphos/5.2 (compliance-tool@xiphos.dev)"

# Federal court nature of suit codes that are high-risk for vendor vetting
HIGH_RISK_NOS = {
    # Fraud
    "370", "371", "375", "376",
    # Securities
    "850", "855", "856",
    # RICO
    "470",
    # Environmental
    "890", "893", "895",
    # Antitrust
    "410", "430",
    # Government contracts
    "153",
}

MEDIUM_RISK_NOS = {
    # Employment discrimination
    "442", "443", "445",
    # Labor
    "710", "720", "740", "751",
    # Patent/IP
    "820", "830", "840",
}


def _get(url: str) -> Optional[dict]:
    """GET request with proper headers. Returns None on error."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        logger.debug("RECAP request failed: %s -> %s", url, e)
        return None


def _classify_severity(nos_code: str, case_name: str) -> str:
    """Classify case severity based on nature-of-suit code and case name."""
    if nos_code in HIGH_RISK_NOS:
        return "high"

    if nos_code in MEDIUM_RISK_NOS:
        return "medium"

    # Check case name for high-risk keywords
    name_lower = case_name.lower()
    high_risk_keywords = ["fraud", "rico", "securities", "brib", "corrupt", "launder",
                          "sanction", "export control", "fcpa", "false claims", "qui tam"]
    medium_risk_keywords = ["breach", "negligence", "discrimination", "violation",
                            "copyright", "patent", "trademark", "antitrust"]

    if any(kw in name_lower for kw in high_risk_keywords):
        return "high"
    if any(kw in name_lower for kw in medium_risk_keywords):
        return "medium"

    return "low"


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """
    Search RECAP archive for federal litigation involving the vendor.
    Uses the free CourtListener search API (no auth required for basic search).
    """
    t0 = time.time()
    result = EnrichmentResult(source="recap_courts", vendor_name=vendor_name)

    try:
        # Search for dockets mentioning the vendor
        encoded = urllib.parse.quote(vendor_name)
        search_url = (
            f"{BASE_URL}/search/"
            f"?q=%22{encoded}%22"
            f"&type=r"  # RECAP dockets
            f"&order_by=score+desc"
            f"&format=json"
        )

        data = _get(search_url)

        if not data or "results" not in data:
            # Try the docket search endpoint as fallback
            docket_url = (
                f"{BASE_URL}/dockets/"
                f"?q=%22{encoded}%22"
                f"&order_by=-date_filed"
                f"&format=json"
            )
            data = _get(docket_url)

        if not data:
            result.findings.append(Finding(
                source="recap_courts", category="litigation",
                title="RECAP archive: search unavailable",
                detail=(
                    "CourtListener RECAP search returned no response. "
                    "This may be a rate limit or temporary outage. "
                    "Try again later or check courtlistener.com directly."
                ),
                severity="info", confidence=0.3,
                url=f"https://www.courtlistener.com/?q=%22{encoded}%22&type=r",
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        results_list = data.get("results", [])
        total_count = data.get("count", len(results_list))

        if total_count == 0:
            result.findings.append(Finding(
                source="recap_courts", category="litigation",
                title="RECAP archive: no federal litigation found",
                detail=(
                    f"No federal court dockets found in the RECAP archive for '{vendor_name}'. "
                    "Note: RECAP covers a significant but incomplete subset of PACER records. "
                    "Absence of results does not guarantee no litigation history."
                ),
                severity="info", confidence=0.6,
                url=f"https://www.courtlistener.com/?q=%22{encoded}%22&type=r",
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Process results
        high_risk_cases = []
        medium_risk_cases = []
        low_risk_cases = []
        courts_seen = set()

        for item in results_list[:20]:  # Process top 20 results
            case_name = item.get("caseName", item.get("case_name", ""))
            court = item.get("court", "")
            court_id = item.get("court_id", court)
            date_filed = item.get("dateFiled", item.get("date_filed", ""))
            nos = str(item.get("natureOfSuit", item.get("nature_of_suit", "")))
            docket_number = item.get("docketNumber", item.get("docket_number", ""))
            status = item.get("status", "")
            absolute_url = item.get("absolute_url", "")

            if court_id:
                courts_seen.add(court_id)

            severity = _classify_severity(nos, case_name)

            case_info = {
                "name": case_name,
                "court": court_id,
                "date": date_filed,
                "docket": docket_number,
                "nos": nos,
                "status": status,
                "url": f"https://www.courtlistener.com{absolute_url}" if absolute_url else "",
            }

            if severity == "high":
                high_risk_cases.append(case_info)
            elif severity == "medium":
                medium_risk_cases.append(case_info)
            else:
                low_risk_cases.append(case_info)

        # Generate findings based on risk categorization
        if high_risk_cases:
            case_summaries = []
            for c in high_risk_cases[:5]:
                case_summaries.append(
                    f"  - {c['name'][:80]} ({c['court']}, {c['date']}, {c['docket']})"
                )
            result.findings.append(Finding(
                source="recap_courts", category="litigation",
                title=f"HIGH-RISK litigation: {len(high_risk_cases)} case(s) involving fraud, securities, or government claims",
                detail=(
                    f"Found {len(high_risk_cases)} high-risk federal court cases potentially involving "
                    f"fraud, securities violations, RICO, or government claims:\n"
                    + "\n".join(case_summaries)
                ),
                severity="high",
                confidence=0.75,
                url=high_risk_cases[0].get("url", ""),
            ))

        if medium_risk_cases:
            case_summaries = []
            for c in medium_risk_cases[:5]:
                case_summaries.append(
                    f"  - {c['name'][:80]} ({c['court']}, {c['date']})"
                )
            result.findings.append(Finding(
                source="recap_courts", category="litigation",
                title=f"Litigation exposure: {len(medium_risk_cases)} case(s) involving employment, IP, or contract disputes",
                detail=(
                    f"Found {len(medium_risk_cases)} medium-risk federal cases:\n"
                    + "\n".join(case_summaries)
                ),
                severity="medium",
                confidence=0.7,
                url=medium_risk_cases[0].get("url", "") if medium_risk_cases else "",
            ))

        # Summary finding
        result.findings.append(Finding(
            source="recap_courts", category="litigation",
            title=f"Federal litigation profile: {total_count} total docket(s) across {len(courts_seen)} court(s)",
            detail=(
                f"RECAP archive search for '{vendor_name}':\n"
                f"  Total dockets found: {total_count}\n"
                f"  High-risk: {len(high_risk_cases)}\n"
                f"  Medium-risk: {len(medium_risk_cases)}\n"
                f"  Low-risk/routine: {len(low_risk_cases)}\n"
                f"  Courts: {', '.join(sorted(courts_seen)[:10])}\n"
                f"\nNote: RECAP covers ~80M+ documents from PACER. Coverage is significant but not complete."
            ),
            severity="info" if not high_risk_cases else "low",
            confidence=0.7,
            url=f"https://www.courtlistener.com/?q=%22{encoded}%22&type=r",
        ))

        # Risk signals
        if high_risk_cases:
            result.risk_signals.append({
                "signal": "federal_litigation_high_risk",
                "severity": "high",
                "detail": f"{len(high_risk_cases)} high-risk federal litigation cases detected",
            })
        if total_count > 50:
            result.risk_signals.append({
                "signal": "federal_litigation_volume",
                "severity": "medium",
                "detail": f"Entity involved in {total_count} federal court cases (high volume)",
            })

    except Exception as e:
        result.error = str(e)
        logger.warning("RECAP courts connector error for %s: %s", vendor_name, e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
