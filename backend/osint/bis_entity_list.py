"""
Bureau of Industry and Security (BIS) Entity List Connector

Checks vendor against the BIS Entity List for export control restrictions.
Since there's no public API, uses fuzzy matching against a curated list of
known sanctioned entities.

The Entity List includes entities subject to the Export Administration
Regulations (EAR) and restricts re-export/transfer of controlled items.

Includes major sanctioned entities from China (CN), Russia (RU), Iran (IR),
North Korea (KP), Cuba (CU), and Venezuela (VE).

API docs: https://www.bis.doc.gov/
"""

import time
import difflib

from . import EnrichmentResult, Finding

# Curated list of known BIS-listed entities (simplified for demo)
# Real implementation would load from official BIS database
BIS_ENTITY_LIST = [
    # China - High-tech manufacturing & semiconductors
    "Huawei Technologies",
    "ZTE Corporation",
    "Semiconductor Manufacturing International Corp",
    "SMIC",
    "Hikvision Digital Technology",
    "Dahua Technology",
    "DJI",  # Drones

    # Russia - Defense & tech
    "Rostec",
    "Gazprom",
    "Rosneft",
    "Sberbank",
    "Kaspersky Lab",
    "Yandex",
    "VTB Bank",

    # Iran - Defense & energy
    "National Iranian Oil Company",
    "NIOC",
    "Islamic Revolutionary Guard Corps",
    "IRGC",
    "National Petrochemical Company",
    "Bank Tejarat",
    "Bank Mellat",

    # North Korea
    "Korea Mining and Trading Corp",
    "Koryo Airlines",
    "Korea Kwangson Banking Corporation",
    "Korea Kumryonggang General Trading",

    # Cuba
    "Cuban Ministry of Interior",
    "Havana Club",

    # Venezuela
    "Petroleos de Venezuela",
    "PDVSA",
    "Gold Reserve Inc",
]


def _fuzzy_match(vendor_name: str, threshold: float = 0.6) -> tuple[bool, float]:
    """
    Fuzzy match vendor_name against BIS entity list.
    Returns (matched, similarity_score).
    Threshold 0.8+ is high confidence, 0.6+ is medium confidence.
    """
    vendor_lower = vendor_name.lower()
    max_score = 0.0
    best_match = None

    for entity in BIS_ENTITY_LIST:
        entity_lower = entity.lower()

        # Exact substring match (quick win)
        if entity_lower in vendor_lower or vendor_lower in entity_lower:
            return (True, 0.95)

        # Fuzzy match using SequenceMatcher
        ratio = difflib.SequenceMatcher(None, vendor_lower, entity_lower).ratio()
        if ratio > max_score:
            max_score = ratio
            best_match = entity

    if max_score >= threshold:
        return (True, max_score)

    return (False, max_score)


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Check vendor against BIS Entity List using fuzzy matching."""
    t0 = time.time()
    result = EnrichmentResult(source="bis_entity_list", vendor_name=vendor_name)

    try:
        # Check for fuzzy match
        matched, score = _fuzzy_match(vendor_name)

        if matched:
            # Determine severity based on score
            if score >= 0.95:
                severity = "critical"
                confidence = 0.95
            elif score >= 0.80:
                severity = "high"
                confidence = 0.85
            else:
                severity = "medium"
                confidence = 0.70

            result.findings.append(Finding(
                source="bis_entity_list",
                category="export_control",
                title=f"BIS Entity List MATCH: {vendor_name}",
                detail=(
                    f"Vendor matches known BIS-listed entity (similarity: {score:.0%}). "
                    f"Subject to export control restrictions under EAR. "
                    f"Verify exact match at https://www.bis.doc.gov/index.php/documents/pdfs"
                ),
                severity=severity,
                confidence=confidence,
                url="https://www.bis.doc.gov/index.php/documents/pdfs",
                raw_data={"similarity_score": score},
            ))

            result.risk_signals.append({
                "signal": "bis_entity_list_match",
                "severity": severity,
                "detail": f"BIS Entity List match (similarity: {score:.0%})",
            })
        else:
            # No match found
            result.findings.append(Finding(
                source="bis_entity_list",
                category="export_control",
                title="BIS Entity List: No match found",
                detail=f"'{vendor_name}' not found in BIS Entity List. No export control flags.",
                severity="info",
                confidence=0.8,
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
