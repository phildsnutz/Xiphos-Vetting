"""
Do Not Pay (DNP) Integration

Simulates Treasury's Do Not Pay Business Center checks, which consolidate
exclusions across multiple federal databases.

Consolidated lists checked:
- Consolidated Screening List (CSL) - Commerce, State, OFAC
- SAM.gov Exclusions (EPLS)
- Debarment List (GSA)
- Treasury Offset Program (TOP)
- Social Security Death Master File (restricted access in sim)

This connector provides a summary view of consolidated checks.
Note: Actual DNP requires .gov authentication. This is a simulation.

Reference: https://www.donotpay.treasury.gov
"""

import time
from . import EnrichmentResult, Finding


# Simulated consolidated exclusion lists
CONSOLIDATED_EXCLUSIONS = {
    # OFAC SDN-type entities
    "Sanctioned Trading Corp": {
        "lists": ["OFAC", "CSL"],
        "type": "Sanctioned Entity",
        "detail": "Designated under OFAC sanctions program",
    },
    # SAM Exclusions
    "Excluded Contractor Services": {
        "lists": ["SAM", "EPLS"],
        "type": "Excluded from Federal Contracts",
        "detail": "Excluded from federal procurement",
    },
    # GSA Debarment
    "Debarred Vendor Group": {
        "lists": ["GSA Debarment"],
        "type": "Debarred",
        "detail": "Debarred by GSA for cause",
    },
    # TOP (Treasury Offset)
    "Debt Collection Services LLC": {
        "lists": ["TOP"],
        "type": "Treasury Offset Program",
        "detail": "Subject to federal debt offset",
    },
    # Multi-list
    "Bad Actor International": {
        "lists": ["OFAC", "CSL", "SAM", "GSA Debarment"],
        "type": "Multiple Exclusion Lists",
        "detail": "Listed on multiple federal exclusion lists",
    },
}


def _fuzzy_match_exclusion(vendor_name: str, threshold: float = 0.75) -> tuple[bool, str]:
    """
    Fuzzy match vendor against simulated consolidated exclusion lists.
    Returns (matched, matched_entity).
    """
    vendor_lower = vendor_name.lower()

    for entity in CONSOLIDATED_EXCLUSIONS.keys():
        entity_lower = entity.lower()

        # Exact match or contains
        if entity_lower in vendor_lower or vendor_lower in entity_lower:
            return (True, entity)

        # Token overlap
        vendor_tokens = vendor_lower.split()
        entity_tokens = entity_lower.split()
        overlap = len(set(vendor_tokens) & set(entity_tokens))
        if overlap >= 2 and len(entity_tokens) >= 2:
            return (True, entity)

    return (False, "")


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """
    Consolidated Do Not Pay check across multiple federal exclusion lists.
    Simulated check provides summary of what would be checked.
    """
    t0 = time.time()
    result = EnrichmentResult(source="do_not_pay", vendor_name=vendor_name)

    try:
        uei = ids.get("uei", "")
        duns = ids.get("duns", "")

        # Check for match
        matched, matched_entity = _fuzzy_match_exclusion(vendor_name)

        if matched:
            excl_info = CONSOLIDATED_EXCLUSIONS[matched_entity]

            result.findings.append(
                Finding(
                    source="do_not_pay",
                    category="exclusion",
                    title=f"Do Not Pay: MATCH - {excl_info['type']}",
                    detail=(
                        f"Vendor matches consolidated Do Not Pay check: {matched_entity}. "
                        f"Type: {excl_info['type']}. Detail: {excl_info['detail']}. "
                        f"Listed on: {', '.join(excl_info['lists'])}. "
                        f"**CRITICAL: Do not pay this vendor. Vendor is disqualified from federal payments.**"
                    ),
                    severity="critical",
                    confidence=0.85,
                    url="https://www.donotpay.treasury.gov",
                    raw_data=excl_info,
                )
            )

            result.risk_signals.append(
                {
                    "signal": "do_not_pay_match",
                    "severity": "critical",
                    "detail": f"{excl_info['type']}: Listed on {', '.join(excl_info['lists'])}",
                }
            )

        else:
            # No match - provide consolidated check summary
            result.findings.append(
                Finding(
                    source="do_not_pay",
                    category="clearance",
                    title="Do Not Pay: Consolidated check completed (simulated)",
                    detail=(
                        f"'{vendor_name}' does not appear on simulated consolidated Do Not Pay list. "
                        f"Simulated check covers: OFAC, Consolidated Screening List, SAM.gov Exclusions, "
                        f"GSA Debarment, Treasury Offset Program, Death Master File. "
                        f"**NOTE: This is a simulated check for demo purposes. "
                        f"For production use, perform actual DNP check via Treasury portal: "
                        f"https://www.donotpay.treasury.gov** "
                        f"Recommend using UEI/DUNS for precise matching."
                    ),
                    severity="info",
                    confidence=0.70,
                    url="https://www.donotpay.treasury.gov",
                )
            )

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
