"""
BIS Consolidated Screening List (CSL) - LIVE API Connector

Real-time queries to the Trade.gov API for export screening lists:
  - Entity List (BIS)
  - Denied Persons List (BIS)
  - Unverified List (BIS)
  - Military End User List (BIS)
  - Non-SDN Chinese Military-Industrial Complex Companies (OFAC)
  - And 8+ others

API: https://api.trade.gov/consolidated_screening_list/v1/search
No authentication required. Real-time data from Commerce Department.
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

from . import EnrichmentResult, Finding

CSL_API = "https://api.trade.gov/consolidated_screening_list/v1/search"
USER_AGENT = "Xiphos/4.0 (compliance-tool@xiphos.dev)"


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query Trade.gov CSL API for export screening matches."""
    t0 = time.time()
    result = EnrichmentResult(source="trade_csl", vendor_name=vendor_name)

    try:
        # Build live API request - query the consolidated screening list
        encoded_name = urllib.parse.quote(vendor_name)
        url = (
            f"{CSL_API}"
            f"?q={encoded_name}"
            f"&sources=Entity+List,Denied+Persons+List,Unverified+List,Military+End+User+List,"
            f"Non-SDN+Chinese+Military-Industrial+Complex+Companies+List"
            f"&size=10"
        )

        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            result.error = f"CSL API unreachable: {str(e)}"
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        results = data.get("results", [])

        if not results:
            result.findings.append(Finding(
                source="trade_csl", category="screening",
                title="CSL clear",
                detail=f"No matches found for '{vendor_name}' in Trade.gov Consolidated Screening List.",
                severity="info", confidence=0.9,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Process matches
        for match in results[:10]:
            name = match.get("name", "")
            source = match.get("source", "")
            alt_names = match.get("alt_names", []) or []
            programs = match.get("programs", []) or []
            addresses = match.get("addresses", []) or []
            ids_list = match.get("ids", []) or []

            # Determine severity by source list
            severity_map = {
                "Entity List": "critical",
                "Denied Persons List": "critical",
                "Unverified List": "high",
                "Military End User List": "high",
                "Non-SDN Chinese Military-Industrial Complex Companies List": "medium",
            }
            severity = severity_map.get(source, "high")

            detail_parts = [
                f"Name: {name}",
                f"Source: {source}",
            ]

            if alt_names:
                detail_parts.append(f"Aliases: {'; '.join(alt_names[:3])}")

            if programs:
                detail_parts.append(f"Programs: {'; '.join(programs[:3])}")

            if addresses:
                detail_parts.append(f"Address: {addresses[0] if addresses else 'N/A'}")

            result.findings.append(Finding(
                source="trade_csl", category="screening",
                title=f"CSL MATCH: {name} [{source}]",
                detail="\n".join(detail_parts),
                severity=severity,
                confidence=0.95,
                url="https://www.trade.gov/consolidated-screening-list",
                raw_data=match,
            ))

            result.risk_signals.append({
                "signal": "csl_match",
                "severity": severity,
                "detail": f"Entity '{name}' found on {source}",
            })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
