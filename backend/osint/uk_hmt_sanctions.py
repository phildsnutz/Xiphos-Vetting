"""
UK HM Treasury Sanctions List Connector

Queries the UK HMT consolidated sanctions list (OFSI).
Covers individuals and entities subject to UK financial sanctions.

Free, no auth required. Updated by HM Treasury Office of Financial Sanctions.
Source: https://www.gov.uk/government/publications/financial-sanctions-consolidated-list-of-targets
"""

import csv
import io
import requests
from datetime import datetime
from . import EnrichmentResult, Finding

TIMEOUT = 15
# HMT provides the consolidated list as downloadable CSV/XML
HMT_URL = "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.csv"


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Check vendor against UK HMT financial sanctions list."""
    result = EnrichmentResult(source="uk_hmt_sanctions", vendor_name=vendor_name)
    start = datetime.now()

    try:
        resp = requests.get(HMT_URL, timeout=TIMEOUT,
                           headers={"User-Agent": "Xiphos/5.0"})
        resp.raise_for_status()

        # Parse CSV content using proper CSV reader (handles quoted fields with commas)
        reader = csv.reader(io.StringIO(resp.text))
        vendor_lower = vendor_name.lower()
        vendor_words = [w.lower() for w in vendor_name.split() if len(w) >= 3]

        matches = []
        header_skipped = False
        for fields in reader:
            if not header_skipped:
                header_skipped = True
                continue
            if len(fields) < 6:
                continue

            # Name fields are at positions 2-5 typically
            full_name = " ".join(fields[2:6]).strip()
            if not full_name:
                continue

            name_lower = full_name.lower()

            # All vendor words must appear in the sanctions name
            if len(vendor_words) >= 1 and all(w in name_lower for w in vendor_words):
                group_type = fields[0].strip() if fields else ""
                group_id = fields[1].strip() if len(fields) > 1 else ""
                matches.append({
                    "name": full_name[:80],
                    "type": group_type,
                    "id": group_id,
                })
                if len(matches) >= 3:
                    break

        if matches:
            for m in matches:
                result.findings.append(Finding(
                    source="uk_hmt_sanctions",
                    category="sanctions",
                    title=f"UK HMT SANCTIONS MATCH: {m['name']}",
                    detail=f"Type: {m['type']} | ID: {m['id']} | Listed on UK OFSI consolidated sanctions list.",
                    severity="critical",
                    confidence=0.92,
                    url="https://www.gov.uk/government/publications/financial-sanctions-consolidated-list-of-targets",
                ))
            result.risk_signals.append({
                "signal": "uk_hmt_sanctions_match",
                "severity": "critical",
                "detail": f"UK HMT sanctions match: {matches[0]['name']}",
            })
        else:
            result.findings.append(Finding(
                source="uk_hmt_sanctions",
                category="clearance",
                title="UK HMT Sanctions: No matches found",
                detail=f"'{vendor_name}' not found on UK HMT/OFSI consolidated sanctions list.",
                severity="info",
                confidence=0.90,
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
    return result
