"""
CISA Known Exploited Vulnerabilities (KEV) Connector

Free JSON feed, no auth required.
Checks if vendor products appear in CISA's catalog of actively exploited vulnerabilities.
A vendor whose products have active KEV entries represents a cybersecurity supply chain risk.

Source: https://www.cisa.gov/known-exploited-vulnerabilities-catalog
Data: https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json
"""

import re

import requests
from datetime import datetime
from . import EnrichmentResult, Finding

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
TIMEOUT = 15
GENERIC_VENDOR_TOKENS = {
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "limited",
    "corp",
    "corporation",
    "co",
    "company",
    "group",
    "systems",
    "system",
    "solutions",
    "solution",
    "services",
    "service",
    "technologies",
    "technology",
    "tech",
    "international",
    "global",
    "defense",
    "aviation",
}


def _tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", (value or "").lower()) if token]


def _matches_vendor(vendor_name: str, vendor_project: str, product: str) -> bool:
    haystack_tokens = set(_tokenize(f"{vendor_project} {product}"))
    vendor_tokens = _tokenize(vendor_name)
    informative_tokens = [
        token for token in vendor_tokens if len(token) > 2 and token not in GENERIC_VENDOR_TOKENS
    ]
    if not informative_tokens:
        informative_tokens = [token for token in vendor_tokens if len(token) > 2]
    if not informative_tokens:
        return False
    overlap = [token for token in informative_tokens if token in haystack_tokens]
    if len(informative_tokens) == 1:
        return bool(overlap)
    return len(overlap) >= 2 or len(overlap) == len(informative_tokens)

def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    result = EnrichmentResult(source="cisa_kev", vendor_name=vendor_name)
    start = datetime.now()

    try:
        resp = requests.get(KEV_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        vulns = data.get("vulnerabilities", [])
        matches = []
        for v in vulns:
            vendor_project = v.get("vendorProject", "")
            product = v.get("product", "")
            if _matches_vendor(vendor_name, vendor_project, product):
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
