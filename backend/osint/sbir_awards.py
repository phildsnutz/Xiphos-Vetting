"""
SBIR.gov Awards Connector

Searches SBIR (Small Business Innovation Research) and STTR awards.
Vendors with SBIR/STTR awards demonstrate government R&D engagement,
technical capability, and positive track record with federal agencies.

Free JSON API, no auth required.
Source: https://www.sbir.gov/api
"""

import requests
from datetime import datetime
from . import EnrichmentResult, Finding

TIMEOUT = 12
SBIR_API = "https://www.sbir.gov/api/awards.json"


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Search SBIR.gov for awards associated with vendor."""
    result = EnrichmentResult(source="sbir_awards", vendor_name=vendor_name)
    start = datetime.now()

    try:
        params = {
            "keyword": vendor_name,
            "rows": "10",
        }
        resp = requests.get(SBIR_API, params=params, timeout=TIMEOUT,
                           headers={"User-Agent": "Xiphos/5.0"})

        if resp.status_code == 200:
            data = resp.json()

            # SBIR API returns results in various formats
            awards = []
            if isinstance(data, list):
                awards = data
            elif isinstance(data, dict):
                awards = data.get("results", data.get("awards", []))

            matched_awards = []
            vendor_lower = vendor_name.lower()

            for award in awards[:20]:
                firm = award.get("firm", "") or award.get("company", "") or ""
                if not firm:
                    continue

                # Check if firm name matches
                firm_lower = firm.lower()
                vendor_words = [w for w in vendor_lower.split() if len(w) >= 3]
                if any(w in firm_lower for w in vendor_words):
                    matched_awards.append({
                        "firm": firm,
                        "title": award.get("award_title", award.get("title", ""))[:100],
                        "agency": award.get("agency", ""),
                        "branch": award.get("branch", ""),
                        "phase": award.get("phase", ""),
                        "program": award.get("program", ""),
                        "amount": award.get("award_amount", award.get("contract", "")),
                        "year": award.get("award_year", award.get("proposal_award_date", ""))[:4] if award.get("award_year") or award.get("proposal_award_date") else "",
                    })

            if matched_awards:
                # Group by agency
                agencies = set(a["agency"] for a in matched_awards if a.get("agency"))
                dod_awards = [a for a in matched_awards if a.get("agency") == "DOD" or "defense" in (a.get("agency") or "").lower()]

                result.findings.append(Finding(
                    source="sbir_awards",
                    category="government_contracts",
                    title=f"SBIR/STTR: {len(matched_awards)} award(s) found",
                    detail=f"Vendor has {len(matched_awards)} SBIR/STTR awards across {len(agencies)} agencies. "
                           f"{'Includes ' + str(len(dod_awards)) + ' DoD awards. ' if dod_awards else ''}"
                           f"Most recent: {matched_awards[0]['title'][:60]}",
                    severity="info",
                    confidence=0.85,
                    url="https://www.sbir.gov/awards",
                ))

                # SBIR awards are a positive legitimacy signal
                result.identifiers["sbir_award_count"] = len(matched_awards)
                result.identifiers["sbir_dod_awards"] = len(dod_awards)
                result.identifiers["sbir_agencies"] = list(agencies)

                if dod_awards:
                    result.risk_signals.append({
                        "signal": "sbir_dod_awards",
                        "severity": "info",
                        "detail": f"Vendor has {len(dod_awards)} DoD SBIR/STTR awards (positive legitimacy signal)",
                    })
            else:
                result.findings.append(Finding(
                    source="sbir_awards",
                    category="government_contracts",
                    title="SBIR/STTR: No awards found",
                    detail=f"No SBIR/STTR awards found for '{vendor_name}'.",
                    severity="info",
                    confidence=0.60,
                ))
        else:
            result.error = f"SBIR API returned {resp.status_code}"

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
    return result
