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


def _query_awards(vendor_name: str, award_type_codes: list[str], time_filter: list[dict], fields: list[str]) -> tuple[list[dict], bool]:
    """Query USAspending for a single award type group.

    Returns (results_list, has_more).  USAspending v2 uses cursor-based
    pagination and no longer provides a ``total`` count.  We infer "at
    least N" from the number of rows returned plus the ``hasNext`` flag.
    """
    payload = {
        "filters": {
            "recipient_search_text": [vendor_name],
            "time_period": time_filter,
            "award_type_codes": award_type_codes,
        },
        "fields": fields,
        "limit": 10,
        "page": 1,
        "sort": "Award Amount",
        "order": "desc",
    }
    resp = requests.post(f"{BASE}/search/spending_by_award/", json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    has_next = data.get("page_metadata", {}).get("hasNext", False)
    return results, has_next


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    result = EnrichmentResult(source="fpds_contracts", vendor_name=vendor_name)
    start = datetime.now()

    try:
        # USAspending v2 requires award_type_codes from a single group per
        # request.  Group 1: contracts (A-D).  Group 2: IDVs (IDV_*).
        contract_codes = ["A", "B", "C", "D"]
        idv_codes = ["IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B",
                      "IDV_B_C", "IDV_C", "IDV_D", "IDV_E"]

        time_filter = [{"start_date": "2019-01-01", "end_date": datetime.now().strftime("%Y-%m-%d")}]
        fields = ["Award ID", "Recipient Name", "Award Amount", "Awarding Agency",
                   "Start Date", "Description", "Contract Award Type"]

        all_awards: list[dict] = []
        any_has_more = False

        for codes in [contract_codes, idv_codes]:
            rows, has_more = _query_awards(vendor_name, codes, time_filter, fields)
            all_awards.extend(rows)
            any_has_more = any_has_more or has_more

        # Keep top 10 by award amount across both groups
        all_awards.sort(key=lambda a: float(a.get("Award Amount", 0) or 0), reverse=True)
        awards = all_awards[:10]
        # Best-effort count: number of rows we actually saw.  If either
        # query indicated more pages, append "+" in the display string.
        result_count = len(all_awards)
        count_label = f"{result_count}+" if any_has_more else str(result_count)

        if awards:
            total_value = sum(float(a.get("Award Amount", 0) or 0) for a in awards)
            agencies = list(set(a.get("Awarding Agency", "") for a in awards if a.get("Awarding Agency")))

            result.identifiers["fpds_contract_count"] = result_count
            result.identifiers["fpds_has_more"] = any_has_more
            result.identifiers["fpds_top_10_value"] = round(total_value, 2)

            result.findings.append(Finding(
                source="fpds_contracts", category="contract_history",
                title=f"FPDS: {count_label} federal contract awards found (since 2019)",
                detail=f"Top awards total ${total_value:,.0f}. "
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

            # Flag if limited contracts and no indication of more pages
            if result_count < 3 and not any_has_more:
                result.risk_signals.append({
                    "signal": "limited_contract_history",
                    "severity": "medium",
                    "detail": f"Only {result_count} federal contracts found since 2019. Limited procurement track record.",
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
