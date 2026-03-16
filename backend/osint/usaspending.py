"""
USAspending.gov Connector

Queries the USAspending API v2 for:
  - Federal contract award history by recipient
  - Total obligated amounts and award counts
  - Awarding agencies and NAICS codes
  - Contract types and set-aside programs

Free API, no key required.
API docs: https://api.usaspending.gov/
"""

import json
import time
import urllib.request
import urllib.error
from typing import Optional

from . import EnrichmentResult, Finding

BASE = "https://api.usaspending.gov/api/v2"
USER_AGENT = "Xiphos/4.0 (compliance-tool@xiphos.dev)"


def _post(url: str, payload: dict) -> dict | None:
    """POST JSON request."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _search_recipient(name: str) -> list[dict]:
    """Search for a recipient by name."""
    url = f"{BASE}/autocomplete/recipient/"
    data = _post(url, {"search_text": name, "limit": 5})
    if not data:
        return []
    return data.get("results", [])


def _get_recipient_profile(recipient_hash: str) -> dict | None:
    """Get detailed recipient profile."""
    url = f"{BASE}/recipient/{recipient_hash}/all/"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _search_awards(name: str, limit: int = 10) -> dict | None:
    """Search for awards by recipient name."""
    url = f"{BASE}/search/spending_by_award/"
    payload = {
        "filters": {
            "recipient_search_text": [name],
            "award_type_codes": ["A", "B", "C", "D"],  # Contracts only
            "time_period": [{"start_date": "2020-01-01", "end_date": "2026-12-31"}],
        },
        "fields": [
            "Award ID", "Recipient Name", "Award Amount",
            "Awarding Agency", "Start Date", "End Date",
            "Award Type", "Description", "NAICS Code",
        ],
        "page": 1,
        "limit": limit,
        "sort": "Award Amount",
        "order": "desc",
    }
    return _post(url, payload)


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query USAspending for federal contract history."""
    t0 = time.time()
    result = EnrichmentResult(source="usaspending", vendor_name=vendor_name)

    try:
        # Step 1: Search for recipient
        recipients = _search_recipient(vendor_name)

        if not recipients:
            result.findings.append(Finding(
                source="usaspending", category="contracts",
                title="No USAspending recipient match",
                detail=f"No federal contract recipient found matching '{vendor_name}'. "
                       f"Entity may not have federal contract history.",
                severity="info", confidence=0.5,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Use the first match
        top = recipients[0]
        recipient_name = top.get("recipient_name", vendor_name)

        result.findings.append(Finding(
            source="usaspending", category="identity",
            title=f"USAspending recipient: {recipient_name}",
            detail=f"Matched recipient in federal spending database.",
            severity="info", confidence=0.8,
            url=f"https://www.usaspending.gov/search/?hash=&filters=%7B%22recipientSearchText%22%3A%5B%22{urllib.request.quote(recipient_name)}%22%5D%7D",
        ))

        time.sleep(0.3)

        # Step 2: LIVE API call - Search for contract awards
        awards_data = _search_awards(vendor_name, limit=10)

        if awards_data and "results" in awards_data:
            awards = awards_data["results"]
            total_count = awards_data.get("page_metadata", {}).get("total", 0)

            total_amount = 0
            agencies = set()
            naics_codes = set()

            for award in awards:
                amt = award.get("Award Amount", 0) or 0
                total_amount += amt
                agency = award.get("Awarding Agency", "")
                if agency:
                    agencies.add(agency)
                naics = award.get("NAICS Code", "")
                if naics:
                    naics_codes.add(str(naics))

            # Set identifier for federal contractor
            if total_count > 0:
                result.identifiers["federal_contractor"] = True
                result.identifiers["total_obligations"] = total_amount

            result.findings.append(Finding(
                source="usaspending", category="contracts",
                title=f"Federal contracts: {total_count} awards, ${total_amount:,.0f} total",
                detail=(
                    f"Found {total_count} contract awards. "
                    f"Agencies: {', '.join(list(agencies)[:5])}. "
                    f"NAICS codes: {', '.join(list(naics_codes)[:5])}."
                ),
                severity="info", confidence=0.9,
                raw_data={
                    "total_awards": total_count,
                    "total_amount": total_amount,
                    "agencies": list(agencies),
                    "naics_codes": list(naics_codes),
                },
            ))

            # Report individual large awards
            for award in awards[:5]:
                amt = award.get("Award Amount", 0) or 0
                if amt > 0:
                    result.findings.append(Finding(
                        source="usaspending", category="contract_detail",
                        title=f"Award: ${amt:,.0f} -- {award.get('Awarding Agency', 'Unknown')}",
                        detail=(
                            f"ID: {award.get('Award ID', 'N/A')}\n"
                            f"Type: {award.get('Award Type', 'N/A')}\n"
                            f"Period: {award.get('Start Date', '?')} to {award.get('End Date', '?')}\n"
                            f"Description: {(award.get('Description', '') or '')[:200]}"
                        ),
                        severity="info", confidence=0.9,
                    ))

            # Risk signal: significant federal contractor
            if total_amount >= 1000000:
                result.risk_signals.append({
                    "signal": "significant_federal_contracts",
                    "severity": "info",
                    "detail": f"Entity is significant federal contractor (${total_amount:,.0f} total)",
                })
        else:
            result.findings.append(Finding(
                source="usaspending", category="contracts",
                title="No federal contracts found",
                detail=f"No federal contract history found for '{vendor_name}'.",
                severity="info", confidence=0.8,
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
