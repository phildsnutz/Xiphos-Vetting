"""
CourtListener Litigation Connector

Queries CourtListener's API for active litigation:
  - RECAP/PACER dockets (federal court records)
  - State court dockets
  - Case names, filing dates, docket numbers

API: https://www.courtlistener.com/api/rest/v4/search/
Auth: Token via XIPHOS_COURTLISTENER_TOKEN env var (optional, free registration)
If token not provided, returns "not configured" finding like SAM.gov does.

Risk signals:
  - active_litigation: any litigation found
  - high_litigation_volume: count > 10
  - Severity escalated for fraud/criminal keywords in case names
"""

import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse

from . import EnrichmentResult, Finding

BASE = "https://www.courtlistener.com/api/rest/v4"
USER_AGENT = "Xiphos-Vetting/2.1"

# Keywords that elevate severity
FRAUD_KEYWORDS = {
    "fraud",
    "embezzlement",
    "money laundering",
    "bribery",
    "forgery",
    "scheme",
}

CRIMINAL_KEYWORDS = {
    "indictment",
    "criminal",
    "prosecution",
    "conviction",
    "felony",
    "misdemeanor",
    "guilty",
}


def _get(url: str, token: str | None = None) -> dict | None:
    """GET request to CourtListener API."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Token {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _has_risk_keywords(text: str) -> tuple[bool, str]:
    """Check if text contains fraud or criminal keywords."""
    text_lower = text.lower()

    for keyword in FRAUD_KEYWORDS:
        if keyword in text_lower:
            return True, "fraud"

    for keyword in CRIMINAL_KEYWORDS:
        if keyword in text_lower:
            return True, "criminal"

    return False, ""


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query CourtListener for litigation records."""
    t0 = time.time()
    result = EnrichmentResult(source="courtlistener", vendor_name=vendor_name)

    # Get token from environment
    token = os.environ.get("XIPHOS_COURTLISTENER_TOKEN")

    if not token:
        result.findings.append(Finding(
            source="courtlistener",
            category="litigation",
            title="CourtListener not configured",
            detail=(
                "CourtListener integration is not configured. To enable litigation checks, "
                "register for a free API token at https://www.courtlistener.com/register/ and "
                "set the XIPHOS_COURTLISTENER_TOKEN environment variable."
            ),
            severity="info",
            confidence=0.0,
        ))
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    try:
        # Query RECAP dockets (federal court)
        query_encoded = urllib.parse.quote(vendor_name)
        recap_url = (
            f"{BASE}/search/"
            f"?q={query_encoded}&type=r&order_by=-dateCreated&format=json"
        )
        recap_data = _get(recap_url, token)

        # Query state court dockets
        state_url = (
            f"{BASE}/search/"
            f"?q={query_encoded}&type=d&order_by=-dateCreated&format=json"
        )
        state_data = _get(state_url, token)

        # Combine results
        all_results = []
        recap_count = 0
        state_count = 0

        if recap_data and "results" in recap_data:
            recap_results = recap_data.get("results", [])
            all_results.extend(recap_results)
            recap_count = recap_data.get("count", 0)

        if state_data and "results" in state_data:
            state_results = state_data.get("results", [])
            all_results.extend(state_results)
            state_count = state_data.get("count", 0)

        total_count = recap_count + state_count

        if not all_results:
            result.findings.append(Finding(
                source="courtlistener",
                category="litigation",
                title="No active litigation found",
                detail=(
                    f"No active litigation records found for '{vendor_name}' "
                    f"in federal or state courts."
                ),
                severity="info",
                confidence=0.8,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Process litigation records
        has_fraud = False
        has_criminal = False

        for case in all_results:
            case_name = case.get("caseName", "")
            court = case.get("court", "")
            date_filed = case.get("dateFiled", "")
            docket_number = case.get("docketNumber", "")
            court_type = "Federal (RECAP)" if recap_count > 0 else "State Court"

            # Check for risk keywords
            has_keywords, keyword_type = _has_risk_keywords(case_name)
            if keyword_type == "fraud":
                has_fraud = True
            elif keyword_type == "criminal":
                has_criminal = True

            # Determine severity
            if has_keywords:
                if keyword_type == "criminal":
                    severity = "high"
                else:  # fraud
                    severity = "high"
            else:
                severity = "medium"

            finding_detail = (
                f"Case Name: {case_name}\n"
                f"Court: {court} ({court_type})\n"
                f"Docket Number: {docket_number}\n"
                f"Date Filed: {date_filed}"
            )

            result.findings.append(Finding(
                source="courtlistener",
                category="litigation",
                title=f"Litigation: {case_name[:80]}",
                detail=finding_detail,
                severity=severity,
                confidence=0.85,
                url=case.get("url", ""),
                raw_data={
                    "case_name": case_name,
                    "docket_number": docket_number,
                    "date_filed": date_filed,
                    "court": court,
                    "has_fraud_keywords": has_keywords and keyword_type == "fraud",
                    "has_criminal_keywords": has_keywords and keyword_type == "criminal",
                },
            ))

        # Add risk signals
        if total_count > 0:
            result.risk_signals.append({
                "signal": "active_litigation",
                "severity": "medium",
                "detail": f"Found {total_count} active litigation case(s) "
                         f"({recap_count} federal, {state_count} state)",
                "case_count": total_count,
                "federal_count": recap_count,
                "state_count": state_count,
            })

        if total_count > 10:
            result.risk_signals.append({
                "signal": "high_litigation_volume",
                "severity": "high",
                "detail": f"Vendor has {total_count} active litigation cases, exceeding high-volume threshold",
                "case_count": total_count,
            })

        if has_fraud or has_criminal:
            keyword_list = []
            if has_fraud:
                keyword_list.append("fraud")
            if has_criminal:
                keyword_list.append("criminal")
            keywords_str = "/".join(keyword_list)

            result.risk_signals.append({
                "signal": "litigation_with_serious_charges",
                "severity": "high",
                "detail": f"Litigation cases contain {keywords_str} keywords",
                "keywords": keyword_list,
            })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
