"""
SEC XBRL Financial Data Connector

Fetches actual financial data from SEC EDGAR XBRL API for public companies.
Provides revenue, total assets, total liabilities, net income, and debt ratios.

This populates the `financial_stability` scoring factor which otherwise has no data.

Free, no auth required (10 req/sec rate limit).
Source: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
"""

import requests
from datetime import datetime
from . import EnrichmentResult, Finding

TIMEOUT = 12
UA = "Xiphos/5.0 (tye.gonzalez@xiphosllc.com)"
BASE = "https://data.sec.gov"


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Fetch financial data from SEC XBRL for a vendor (requires CIK)."""
    result = EnrichmentResult(source="sec_xbrl", vendor_name=vendor_name)
    start = datetime.now()

    cik = ids.get("cik", "")

    # If no CIK provided, try to look up from company tickers
    if not cik:
        try:
            resp = requests.get("https://efts.sec.gov/LATEST/search-index?q=%22" +
                               requests.utils.quote(vendor_name) + "%22&dateRange=custom&startdt=2024-01-01&forms=10-K",
                               headers={"User-Agent": UA}, timeout=8)
            # Fallback: search company_tickers for CIK
            resp2 = requests.get("https://www.sec.gov/files/company_tickers.json",
                                headers={"User-Agent": UA}, timeout=10)
            if resp2.status_code == 200:
                tickers = resp2.json()
                vendor_lower = vendor_name.lower()
                for _, entry in tickers.items():
                    if vendor_lower in entry.get("title", "").lower():
                        cik = str(entry.get("cik_str", ""))
                        break
        except Exception:
            pass

    if not cik:
        result.findings.append(Finding(
            source="sec_xbrl", category="financial",
            title=f"SEC XBRL: No CIK found for '{vendor_name}' (private company or not US-listed)",
            detail="Cannot retrieve financial data without a CIK. Entity may be private or non-US.",
            severity="info", confidence=0.5,
        ))
        result.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
        return result

    try:
        # Pad CIK to 10 digits
        cik_padded = cik.zfill(10)

        # Fetch company facts (all XBRL data)
        url = f"{BASE}/api/xbrl/companyfacts/CIK{cik_padded}.json"
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)

        if resp.status_code == 200:
            data = resp.json()
            facts = data.get("facts", {})
            us_gaap = facts.get("us-gaap", {})

            # Extract key financial metrics (most recent annual filing)
            def _get_latest_annual(concept: str) -> dict | None:
                concept_data = us_gaap.get(concept, {})
                units = concept_data.get("units", {})
                usd_entries = units.get("USD", [])
                # Filter to annual (10-K) filings
                annual = [e for e in usd_entries if e.get("form") == "10-K"]
                if annual:
                    return sorted(annual, key=lambda x: x.get("end", ""), reverse=True)[0]
                return None

            revenue = _get_latest_annual("Revenues") or _get_latest_annual("RevenueFromContractWithCustomerExcludingAssessedTax")
            total_assets = _get_latest_annual("Assets")
            total_liabilities = _get_latest_annual("Liabilities")
            net_income = _get_latest_annual("NetIncomeLoss")
            total_equity = _get_latest_annual("StockholdersEquity")

            financials = {}
            if revenue:
                financials["revenue"] = revenue.get("val", 0)
                financials["revenue_period"] = revenue.get("end", "")
            if total_assets:
                financials["total_assets"] = total_assets.get("val", 0)
            if total_liabilities:
                financials["total_liabilities"] = total_liabilities.get("val", 0)
            if net_income:
                financials["net_income"] = net_income.get("val", 0)
            if total_equity:
                financials["total_equity"] = total_equity.get("val", 0)

            # Compute ratios
            if financials.get("total_assets") and financials.get("total_liabilities"):
                debt_ratio = financials["total_liabilities"] / financials["total_assets"]
                financials["debt_ratio"] = round(debt_ratio, 3)

            if financials.get("revenue") and financials.get("net_income"):
                profit_margin = financials["net_income"] / financials["revenue"]
                financials["profit_margin"] = round(profit_margin, 3)

            if financials:
                # Format as human-readable
                rev_str = f"${financials.get('revenue', 0) / 1e9:.1f}B" if financials.get("revenue") else "N/A"
                assets_str = f"${financials.get('total_assets', 0) / 1e9:.1f}B" if financials.get("total_assets") else "N/A"
                debt_str = f"{financials.get('debt_ratio', 0):.1%}" if financials.get("debt_ratio") else "N/A"

                result.findings.append(Finding(
                    source="sec_xbrl", category="financial",
                    title=f"SEC XBRL: Financial data retrieved (CIK {cik})",
                    detail=f"Revenue: {rev_str} | Assets: {assets_str} | Debt Ratio: {debt_str} | Period: {financials.get('revenue_period', 'N/A')}",
                    severity="info", confidence=0.90,
                    url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K",
                ))

                result.identifiers.update(financials)
                result.identifiers["cik"] = cik
                result.identifiers["has_audited_financials"] = True

                # Financial health risk signals
                if financials.get("debt_ratio", 0) > 0.80:
                    result.risk_signals.append({
                        "signal": "high_debt_ratio",
                        "severity": "medium",
                        "detail": f"Debt-to-assets ratio {financials['debt_ratio']:.1%} exceeds 80% threshold",
                    })
                if financials.get("net_income", 0) < 0:
                    result.risk_signals.append({
                        "signal": "negative_net_income",
                        "severity": "medium",
                        "detail": f"Net income is negative: ${financials['net_income'] / 1e6:.0f}M",
                    })
            else:
                result.findings.append(Finding(
                    source="sec_xbrl", category="financial",
                    title=f"SEC XBRL: CIK {cik} found but no standard financial data",
                    detail="Entity is SEC-registered but XBRL financial data is not available in standard format.",
                    severity="info", confidence=0.60,
                ))
        else:
            result.findings.append(Finding(
                source="sec_xbrl", category="financial",
                title=f"SEC XBRL: Could not fetch data for CIK {cik}",
                detail=f"API returned {resp.status_code}.",
                severity="info", confidence=0.5,
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
    return result
