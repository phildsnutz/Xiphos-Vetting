"""
SEC EDGAR Connector

Queries the SEC EDGAR REST API (data.sec.gov) for:
  - Company identity (CIK, ticker, SIC code)
  - Recent filings (10-K, 10-Q, 8-K, DEF 14A)
  - Insider ownership (Forms 3, 4, 5)
  - Subsidiary disclosures (Exhibit 21)
  - Officer/director changes (8-K Item 5.02)

No API key required. Rate limit: 10 req/s.
Must include User-Agent header with contact email.
"""

import json
import time
import urllib.request
import urllib.error
from typing import Optional

from . import EnrichmentResult, Finding

BASE = "https://data.sec.gov"
EFTS = "https://efts.sec.gov/LATEST"
USER_AGENT = "Xiphos-Vetting/2.1 (tye.gonzalez@gmail.com)"


def _get(url: str) -> dict | list | None:
    """GET request with proper headers."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _search_company(name: str) -> list[dict]:
    """Full-text search for company by name. Returns list of matches with CIK."""
    url = f"{EFTS}/search-index?q=%22{urllib.request.quote(name)}%22&dateRange=custom&startdt=2020-01-01&forms=10-K,10-Q&from=0&size=5"
    data = _get(url)
    if not data or "hits" not in data:
        return []
    hits = data.get("hits", {}).get("hits", [])
    results = []
    seen_ciks = set()
    for h in hits:
        src = h.get("_source", {})
        ciks = src.get("ciks", [])
        display_names = src.get("display_names", [])
        cik = ciks[0].lstrip("0") if ciks else ""
        entity_name = display_names[0].split("(CIK")[0].strip() if display_names else ""
        if cik and cik not in seen_ciks:
            seen_ciks.add(cik)
            results.append({
                "entity_name": entity_name,
                "cik": cik,
                "file_date": src.get("file_date", ""),
                "form_type": src.get("form", ""),
            })
    return results


def _lookup_cik(name: str) -> Optional[str]:
    """Try to resolve company name to CIK via the tickers file."""
    url = "https://www.sec.gov/files/company_tickers.json"
    data = _get(url)
    if not data:
        return None

    name_upper = name.upper().strip()
    # Try exact-ish match first (name contained in title or vice versa)
    for _, entry in data.items():
        title = entry.get("title", "").upper()
        # Strip common suffixes like /FI/, /ADR/, INC, CORP for matching
        title_clean = title.split("/")[0].strip()
        if name_upper in title_clean or title_clean in name_upper:
            return str(entry.get("cik_str", ""))

    # Try word-level match (all words in query appear in title)
    name_words = name_upper.split()
    if len(name_words) >= 2:
        for _, entry in data.items():
            title = entry.get("title", "").upper()
            if all(w in title for w in name_words):
                return str(entry.get("cik_str", ""))

    return None


def _get_company_facts(cik: str) -> dict | None:
    """Get all XBRL facts for a company."""
    padded = cik.zfill(10)
    url = f"{BASE}/api/xbrl/companyfacts/CIK{padded}.json"
    return _get(url)


def _get_submissions(cik: str) -> dict | None:
    """Get recent filings/submissions for a company."""
    padded = cik.zfill(10)
    url = f"{BASE}/submissions/CIK{padded}.json"
    return _get(url)


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query SEC EDGAR for company intelligence."""
    t0 = time.time()
    result = EnrichmentResult(source="sec_edgar", vendor_name=vendor_name)

    try:
        # Step 1: Resolve CIK
        cik = ids.get("cik")
        if not cik:
            cik = _lookup_cik(vendor_name)
        if not cik:
            # Try full-text search
            matches = _search_company(vendor_name)
            if matches:
                cik = matches[0]["cik"]
                result.findings.append(Finding(
                    source="sec_edgar", category="identity",
                    title=f"SEC match: {matches[0]['entity_name']}",
                    detail=f"Matched to CIK {cik} via EDGAR full-text search. "
                           f"Latest filing: {matches[0].get('form_type', 'N/A')} on {matches[0].get('file_date', 'N/A')}",
                    severity="info", confidence=0.7,
                    url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                ))

        if not cik:
            result.findings.append(Finding(
                source="sec_edgar", category="identity",
                title="No SEC filing found",
                detail=f"No EDGAR match for '{vendor_name}'. Entity may be private, foreign, or non-reporting.",
                severity="info", confidence=0.5,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        result.identifiers["cik"] = cik
        time.sleep(0.12)  # Rate limiting

        # Step 2: Get submissions (filings list + company metadata)
        subs = _get_submissions(cik)
        if subs:
            # Company metadata
            name_official = subs.get("name", "")
            sic = subs.get("sic", "")
            sic_desc = subs.get("sicDescription", "")
            state = subs.get("stateOfIncorporation", "")
            tickers = subs.get("tickers", [])
            exchanges = subs.get("exchanges", [])

            result.identifiers["sic"] = sic
            result.identifiers["state_of_incorporation"] = state
            if tickers:
                result.identifiers["ticker"] = tickers[0]

            result.findings.append(Finding(
                source="sec_edgar", category="identity",
                title=f"SEC registrant: {name_official}",
                detail=f"CIK: {cik} | SIC: {sic} ({sic_desc}) | "
                       f"State: {state} | Tickers: {', '.join(tickers)} on {', '.join(exchanges)}",
                severity="info", confidence=0.95,
                url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
            ))

            # Recent filings analysis
            recent = subs.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])

            # Check for concerning filing types
            concerning = {
                "NT 10-K": "Late annual report notification",
                "NT 10-Q": "Late quarterly report notification",
                "8-K": "Material event disclosure",
                "SC 13D": "Beneficial ownership >5% (activist/change)",
                "SC 13D/A": "Amended beneficial ownership >5%",
                "DEFA14A": "Proxy fight / contested election",
                "15-12G": "Deregistration (going dark)",
            }

            for i, form in enumerate(forms[:50]):
                if form in concerning:
                    result.findings.append(Finding(
                        source="sec_edgar", category="filing_event",
                        title=f"Filing: {form} ({dates[i] if i < len(dates) else 'N/A'})",
                        detail=concerning[form],
                        severity="medium" if form.startswith("NT") or form == "15-12G" else "low",
                        confidence=0.9,
                        url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{accessions[i].replace('-', '')}/",
                    ))

            # Count filing frequency (health signal)
            annual_count = sum(1 for f in forms[:20] if f in ("10-K", "10-K/A"))
            quarterly_count = sum(1 for f in forms[:20] if f in ("10-Q", "10-Q/A"))

            if annual_count == 0 and len(forms) > 5:
                result.risk_signals.append({
                    "signal": "no_recent_annual_report",
                    "severity": "high",
                    "detail": "No 10-K found in recent filings",
                })
                result.findings.append(Finding(
                    source="sec_edgar", category="data_quality",
                    title="Missing annual report",
                    detail="No 10-K filing found in recent submission history. May indicate deregistration or compliance issues.",
                    severity="high", confidence=0.8,
                ))

        time.sleep(0.12)

        # Step 3: Get financial facts (revenue, assets, etc.)
        facts = _get_company_facts(cik)
        if facts and "facts" in facts:
            us_gaap = facts["facts"].get("us-gaap", {})

            # Extract key financial metrics
            for concept, label in [
                ("Revenues", "Revenue"),
                ("Assets", "Total Assets"),
                ("StockholdersEquity", "Stockholders Equity"),
                ("NetIncomeLoss", "Net Income/Loss"),
            ]:
                concept_data = us_gaap.get(concept, {})
                units = concept_data.get("units", {})
                usd = units.get("USD", [])
                if usd:
                    latest = sorted(usd, key=lambda x: x.get("end", ""), reverse=True)
                    if latest:
                        val = latest[0].get("val", 0)
                        period = latest[0].get("end", "")
                        result.findings.append(Finding(
                            source="sec_edgar", category="financial",
                            title=f"{label}: ${val:,.0f}",
                            detail=f"Period ending {period}. From XBRL concept {concept}.",
                            severity="info", confidence=0.95,
                            raw_data={"concept": concept, "value": val, "period": period},
                        ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
