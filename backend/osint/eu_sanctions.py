"""
EU Consolidated Sanctions (CFSP) Connector

Queries the European Union consolidated sanctions list maintained by DG FISMA.
Covers individuals and entities subject to EU financial sanctions.

Free XML download, no auth required. Updated by the European Commission.
Source: https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from . import EnrichmentResult, Finding

TIMEOUT = 15
EU_SANCTIONS_URL = "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Check vendor against EU CFSP consolidated sanctions list."""
    result = EnrichmentResult(source="eu_sanctions", vendor_name=vendor_name)
    start = datetime.now()

    try:
        resp = requests.get(EU_SANCTIONS_URL, timeout=TIMEOUT,
                           headers={"User-Agent": "Xiphos/5.0"})
        resp.raise_for_status()

        root = ET.fromstring(resp.content)

        vendor_lower = vendor_name.lower()
        vendor_words = [w.lower() for w in vendor_name.split() if len(w) >= 3]

        matches = []

        # EU sanctions XML uses <sanctionEntity> elements
        for entity in root.iter():
            if 'Entity' not in entity.tag and 'nameAlias' not in entity.tag:
                continue

            # Try to find name elements
            for name_elem in entity.iter():
                if 'wholeName' in name_elem.tag or 'lastName' in name_elem.tag:
                    name_text = name_elem.text or ""
                    if not name_text:
                        continue

                    name_lower = name_text.lower()
                    if all(w in name_lower for w in vendor_words):
                        # Get regulation info
                        reg = ""
                        for reg_elem in entity.iter():
                            if 'regulation' in reg_elem.tag.lower():
                                reg_title = reg_elem.get("regulationType", "")
                                reg_num = reg_elem.get("publicationUrl", "")
                                reg = f"{reg_title} {reg_num}".strip()
                                break

                        matches.append({
                            "name": name_text,
                            "regulation": reg,
                        })

                        if len(matches) >= 3:
                            break
            if len(matches) >= 3:
                break

        if matches:
            for m in matches:
                result.findings.append(Finding(
                    source="eu_sanctions",
                    category="sanctions",
                    title=f"EU SANCTIONS MATCH: {m['name']}",
                    detail=f"Listed on EU CFSP consolidated sanctions list. {m.get('regulation', '')}",
                    severity="critical",
                    confidence=0.92,
                    url="https://sanctionsmap.eu/",
                ))
            result.risk_signals.append({
                "signal": "eu_sanctions_match",
                "severity": "critical",
                "detail": f"EU CFSP sanctions match: {matches[0]['name']}",
            })
        else:
            result.findings.append(Finding(
                source="eu_sanctions",
                category="clearance",
                title="EU Sanctions: No matches found",
                detail=f"'{vendor_name}' not found on EU CFSP consolidated sanctions list.",
                severity="info",
                confidence=0.90,
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
    return result
