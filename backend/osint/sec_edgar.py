"""
SEC EDGAR Full-Text Search Connector - LIVE API

Real-time queries to SEC's EFTS full-text search API for:
  - Company filings (10-K, 10-Q, 8-K, DEF 14A)
  - Filing dates and form types
  - Company identity and regulatory status

API: https://efts.sec.gov/LATEST/search-index
No authentication required.
User-Agent header with contact email required.
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

from . import EnrichmentResult, Finding

EFTS = "https://efts.sec.gov/LATEST"
USER_AGENT = "Xiphos/4.0 (compliance-tool@xiphos.dev)"


def _get(url: str) -> dict | list | None:
    """GET request with proper headers."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "html" in content_type.lower() or raw[:20].startswith(b"<!DOCTYPE"):
                return None
            return json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query SEC EDGAR full-text search API for company intelligence."""
    t0 = time.time()
    result = EnrichmentResult(source="sec_edgar", vendor_name=vendor_name)

    try:
        # LIVE API call: Full-text search for filings
        encoded_name = urllib.parse.quote(f'"{vendor_name}"')
        url = (
            f"{EFTS}/search-index"
            f"?q={encoded_name}"
            f"&forms=10-K,10-Q,8-K,DEF+14A"
            f"&from=0"
            f"&size=5"
        )

        data = _get(url)

        if not data or "hits" not in data:
            result.findings.append(Finding(
                source="sec_edgar", category="identity",
                title="No SEC filings found",
                detail=f"No EDGAR filings found for '{vendor_name}'. Entity may be private, foreign, or non-reporting.",
                severity="medium", confidence=0.8,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        hits = data.get("hits", {}).get("hits", [])

        if not hits:
            result.findings.append(Finding(
                source="sec_edgar", category="identity",
                title="No SEC filings found",
                detail=f"No EDGAR filings found for '{vendor_name}'.",
                severity="medium", confidence=0.7,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Process results
        seen_ciks = set()
        for hit in hits:
            src = hit.get("_source", {})
            ciks = src.get("ciks", [])
            display_names = src.get("display_names", [])
            file_date = src.get("file_date", "")
            form_type = src.get("form", "")
            company_name = src.get("company_name", "")
            file_num = src.get("file_num", "")

            cik = ciks[0].lstrip("0") if ciks else ""

            if not cik or cik in seen_ciks:
                continue

            seen_ciks.add(cik)

            # Track identifiers
            if not result.identifiers.get("cik"):
                result.identifiers["cik"] = cik

            # Create finding for company/filing
            display_name = company_name or (display_names[0] if display_names else "") or vendor_name
            title_text = f"{display_name} - {form_type} ({file_date})"
            detail_parts = [
                f"CIK: {cik}",
                f"Company: {company_name}",
                f"Form: {form_type}",
                f"Filing Date: {file_date}",
                f"File Number: {file_num}",
            ]

            severity_map = {
                "10-K": "info",
                "10-Q": "info",
                "8-K": "low",
                "DEF 14A": "info",
            }
            severity = severity_map.get(form_type, "info")

            result.findings.append(Finding(
                source="sec_edgar", category="identity",
                title=title_text,
                detail="\n".join(detail_parts),
                severity=severity, confidence=0.95,
                url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                raw_data={"cik": cik, "form": form_type, "date": file_date},
            ))

        # Set identifier for public trading status if we found 10-K
        form_types_found = [h.get("_source", {}).get("form", "") for h in hits]
        if "10-K" in form_types_found or "10-Q" in form_types_found:
            result.identifiers["publicly_traded"] = True

        # Risk signal: 8-K filings (material events)
        if "8-K" in form_types_found:
            result.risk_signals.append({
                "signal": "sec_8k_filing",
                "severity": "low",
                "detail": "Entity has recent 8-K material event disclosure(s)",
            })

        # Risk signal: DEF 14A (proxy statements indicate public company)
        if "DEF 14A" in form_types_found:
            result.risk_signals.append({
                "signal": "sec_def14a_proxy",
                "severity": "info",
                "detail": "Entity has proxy statement (DEF 14A) on file",
            })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
