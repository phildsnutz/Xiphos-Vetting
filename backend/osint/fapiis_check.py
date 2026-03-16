"""
FAPIIS (Federal Awardee Performance and Integrity Information System) Check

Screens vendors against FAPIIS for known adverse Federal performance history.
FAPIIS consolidates suspension/debarment, termination for cause, defective pricing,
and other integrity information.

Note: Real FAPIIS requires .gov credentials. This connector simulates checks against
a curated list of known adverse entities and recommends manual verification against
the live FAPIIS portal.

Reference: https://www.sam.gov/content/faq (FAPIIS section)
"""

import time
from . import EnrichmentResult, Finding


# Simulated database of entities with known FAPIIS adverse findings
FAPIIS_ADVERSE_ENTITIES = {
    # Terminations for cause/default (simulated examples)
    "Universal Contractor Inc": {
        "finding_type": "Termination for Default",
        "detail": "Contract terminated for failure to perform",
        "agency": "DoD",
    },
    "Integrity Systems Corp": {
        "finding_type": "Administrative Agreement",
        "detail": "Administrative action on suspicion of impropriety",
        "agency": "GSA",
    },
    "Performance Failures LLC": {
        "finding_type": "Termination for Cause",
        "detail": "Persistent failure to meet contract requirements",
        "agency": "HHS",
    },
    "Defective Pricing Services": {
        "finding_type": "Defective Pricing Finding",
        "detail": "Submitted inaccurate pricing data",
        "agency": "DoD",
    },
    "NonResponsible Vendor Group": {
        "finding_type": "Non-responsibility Determination",
        "detail": "Deemed not qualified to receive federal contracts",
        "agency": "GSA",
    },
    "Suspension Services International": {
        "finding_type": "Suspended",
        "detail": "Suspended from federal contracting pending investigation",
        "agency": "DOJ",
    },
}


def _fuzzy_match_fapiis(vendor_name: str, threshold: float = 0.75) -> tuple[bool, str]:
    """
    Fuzzy match vendor against simulated FAPIIS adverse list.
    Returns (matched, matched_entity).
    """
    vendor_lower = vendor_name.lower()

    for entity in FAPIIS_ADVERSE_ENTITIES.keys():
        entity_lower = entity.lower()

        # Exact match or contains
        if entity_lower in vendor_lower or vendor_lower in entity_lower:
            return (True, entity)

        # Simple token overlap for demo
        vendor_tokens = vendor_lower.split()
        entity_tokens = entity_lower.split()
        overlap = len(set(vendor_tokens) & set(entity_tokens))
        if overlap >= 2 and len(entity_tokens) >= 2:
            return (True, entity)

    return (False, "")


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """
    Check vendor against FAPIIS adverse finding database.
    Simulated check recommends manual verification against live FAPIIS portal.
    """
    t0 = time.time()
    result = EnrichmentResult(source="fapiis_check", vendor_name=vendor_name)

    try:
        uei = ids.get("uei", "")
        duns = ids.get("duns", "")

        # Check for match
        matched, matched_entity = _fuzzy_match_fapiis(vendor_name)

        if matched:
            fapiis_info = FAPIIS_ADVERSE_ENTITIES[matched_entity]

            result.findings.append(
                Finding(
                    source="fapiis_check",
                    category="fapiis",
                    title=f"FAPIIS: {fapiis_info['finding_type']} - {matched_entity}",
                    detail=(
                        f"Vendor matches known entity with FAPIIS finding: {matched_entity}. "
                        f"Finding type: {fapiis_info['finding_type']}. "
                        f"Detail: {fapiis_info['detail']}. "
                        f"Reporting agency: {fapiis_info['agency']}. "
                        f"**IMPORTANT: Verify against live FAPIIS portal at "
                        f"https://www.sam.gov/content/faq (FAPIIS section) before making award decisions.**"
                    ),
                    severity="high",
                    confidence=0.75,
                    url="https://www.sam.gov/content/faq",
                    raw_data=fapiis_info,
                )
            )

            result.risk_signals.append(
                {
                    "signal": "fapiis_adverse_finding",
                    "severity": "high",
                    "detail": f"{fapiis_info['finding_type']}: {fapiis_info['detail']}",
                }
            )

        else:
            # No match found - provide verification info
            result.findings.append(
                Finding(
                    source="fapiis_check",
                    category="fapiis",
                    title="FAPIIS: No adverse findings detected (simulated check)",
                    detail=(
                        f"'{vendor_name}' does not match simulated FAPIIS adverse findings database. "
                        f"**IMPORTANT: This is a simulated check. You must verify against the live FAPIIS portal "
                        f"at https://www.sam.gov/content/faq before making federal awards.** "
                        f"FAPIIS consolidates suspension/debarment, terminations, defective pricing, "
                        f"and administrative actions. "
                        f"Recommend using UEI (Universal Entity ID) or DUNS for precise matching."
                    ),
                    severity="info",
                    confidence=0.70,
                    url="https://www.sam.gov/content/faq",
                )
            )

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
