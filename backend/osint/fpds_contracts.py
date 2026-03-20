"""
FPDS Federal Procurement Data Connector

Free access via USAspending/FPDS data. No auth required.
Queries federal contract award history to verify defense procurement track record.

Source: https://api.usaspending.gov/ (FPDS data is accessible via USAspending API v2)
"""

import requests
from datetime import datetime
from . import EnrichmentResult, Finding

BASE = "https://api.usaspending.gov/api/v2"
TIMEOUT = 15

def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    result = EnrichmentResult(source="fpds_contracts", vendor_name=vendor_name)
    start = datetime.now()

    try:
        # Search for awards by recipient name
        payload = {
            "filters": {
                "recipient_search_text": [vendor_name],
                "time_period": [{"start_date": "2019-01-01", "end_date": datetime.now().strftime("%Y-%m-%d")}],
            },
            "fields": ["Award ID", "Recipient Name", "Award Amount", "Awarding Agency",
                        "Start Date", "Description", "Contract Award Type"],
            "limit": 10,
            "page": 1,
            "sort": "Award Amount",
            "order": "desc",
        }

        resp = requests.post(f"{BASE}/search/spending_by_award/", json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        awards = data.get("results", [])
        total = data.get("page_metadata", {}).get("total", 0)

        if awards:
            total_value = sum(float(a.get("Award Amount", 0) or 0) for a in awards)
            agencies = list(set(a.get("Awarding Agency", "") for a in awards if a.get("Awarding Agency")))

            result.identifiers["fpds_contract_count"] = total
            result.identifiers["fpds_top_10_value"] = round(total_value, 2)

            result.findings.append(Finding(
                source="fpds_contracts", category="contract_history",
                title=f"FPDS: {total} federal contract awards found (since 2019)",
                detail=f"Top 10 awards total ${total_value:,.0f}. "
                       f"Awarding agencies: {', '.join(agencies[:5])}. "
                       f"Largest: ${float(awards[0].get('Award Amount', 0) or 0):,.0f} from {awards[0].get('Awarding Agency', 'N/A')}.",
                severity="info", confidence=0.8,
                url=f"https://www.usaspending.gov/search/?hash=recipient/{vendor_name}",
            ))

            # Check for DoD contracts specifically
            dod_agencies = [a for a in agencies if any(kw in a.upper() for kw in ["DEFENSE", "ARMY", "NAVY", "AIR FORCE", "DOD", "MISSILE", "SPACE"])]
            if dod_agencies:
                result.identifiers["has_dod_contracts"] = True
                result.findings.append(Finding(
                    source="fpds_contracts", category="contract_history",
                    title=f"DoD contract history confirmed ({len(dod_agencies)} defense agencies)",
                    detail=f"Confirmed DoD awards from: {', '.join(dod_agencies[:5])}",
                    severity="info", confidence=0.85,
                ))
            else:
                result.identifiers["has_dod_contracts"] = False

            # Flag if no recent contracts despite claiming defense work
            if total < 3:
                result.risk_signals.append({
                    "signal": "limited_contract_history",
                    "severity": "medium",
                    "detail": f"Only {total} federal contracts found since 2019. Limited procurement track record.",
                })

        else:
            result.findings.append(Finding(
                source="fpds_contracts", category="contract_history",
                title=f"FPDS: No federal contract awards found for '{vendor_name}'",
                detail="No federal procurement history in USAspending since 2019. Entity may operate under a different legal name or be new to government contracting.",
                severity="medium", confidence=0.6,
                url="https://www.usaspending.gov/search",
            ))
            result.identifiers["fpds_contract_count"] = 0
            result.risk_signals.append({
                "signal": "no_federal_contracts_fpds",
                "severity": "medium",
                "detail": "No federal contract awards found in FPDS/USAspending since 2019.",
            })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
    return result
