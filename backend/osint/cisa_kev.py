"""
CISA Known Exploited Vulnerabilities (KEV) Connector

Free JSON feed, no auth required.
Checks if vendor products appear in CISA's catalog of actively exploited vulnerabilities.
A vendor whose products have active KEV entries represents a cybersecurity supply chain risk.

Source: https://www.cisa.gov/known-exploited-vulnerabilities-catalog
Data: https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json
"""

import requests
from datetime import datetime
from . import EnrichmentResult, Finding

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
TIMEOUT = 15

def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    result = EnrichmentResult(source="cisa_kev", vendor_name=vendor_name)
    start = datetime.now()

    try:
        resp = requests.get(KEV_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        vulns = data.get("vulnerabilities", [])
        vendor_lower = vendor_name.lower()
        # Extract key words from vendor name for matching
        keywords = [w.lower() for w in vendor_name.split() if len(w) > 3]

        matches = []
        for v in vulns:
            vendor_project = (v.get("vendorProject", "") + " " + v.get("product", "")).lower()
            if any(kw in vendor_project for kw in keywords):
                matches.append(v)

        if matches:
            result.identifiers["kev_matches"] = len(matches)
            severity = "high" if len(matches) >= 3 else "medium" if len(matches) >= 1 else "info"
            result.findings.append(Finding(
                source="cisa_kev", category="cybersecurity",
                title=f"CISA KEV: {len(matches)} known exploited vulnerabilities found",
                detail=f"Products associated with '{vendor_name}' appear in {len(matches)} CISA KEV entries. "
                       f"Most recent: {matches[0].get('cveID', 'N/A')} - {matches[0].get('vulnerabilityName', 'N/A')}. "
                       f"These are actively exploited in the wild and represent supply chain cybersecurity risk.",
                severity=severity, confidence=0.7,
                url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
            ))
            for m in matches[:5]:
                result.findings.append(Finding(
                    source="cisa_kev", category="cybersecurity",
                    title=f"KEV: {m.get('cveID', 'N/A')} - {m.get('vulnerabilityName', 'N/A')[:60]}",
                    detail=f"Vendor: {m.get('vendorProject', 'N/A')} | Product: {m.get('product', 'N/A')} | "
                           f"Added: {m.get('dateAdded', 'N/A')} | Due: {m.get('dueDate', 'N/A')} | "
                           f"Description: {m.get('shortDescription', 'N/A')[:200]}",
                    severity="medium", confidence=0.8,
                    url=f"https://nvd.nist.gov/vuln/detail/{m.get('cveID', '')}",
                ))

            result.risk_signals.append({
                "signal": "cisa_kev_exposure",
                "severity": severity,
                "detail": f"{len(matches)} products in CISA KEV catalog. Active exploitation confirmed.",
            })
        else:
            result.findings.append(Finding(
                source="cisa_kev", category="cybersecurity",
                title="CISA KEV: No known exploited vulnerabilities found",
                detail=f"No products associated with '{vendor_name}' appear in the CISA KEV catalog ({len(vulns)} total entries checked).",
                severity="info", confidence=0.6,
                url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
    return result
