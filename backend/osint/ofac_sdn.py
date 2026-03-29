"""
OFAC SDN (Specially Designated Nationals) Direct Connector

Queries the US Treasury OFAC SDN list directly via XML download.
This is the primary authoritative source for US sanctions designations.

Free, no auth required. Updated frequently by Treasury.
Source: https://www.treasury.gov/ofac/downloads/sdn.xml
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from . import EnrichmentResult, Finding

TIMEOUT = 15
SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.xml"
# Use compressed version for bandwidth savings (~92% smaller)
SDN_URL_COMPRESSED = "https://www.treasury.gov/ofac/downloads/sdn.xml.zip"


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Check vendor against OFAC SDN list (direct Treasury XML feed)."""
    result = EnrichmentResult(source="ofac_sdn", vendor_name=vendor_name)
    start = datetime.now()

    try:
        # Use the regular XML (compressed would need zipfile handling)
        resp = requests.get(SDN_URL, timeout=TIMEOUT,
                           headers={"User-Agent": "Xiphos/5.0"})
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        # Try both namespaced and non-namespaced
        entries = root.findall(".//sdnEntry") or root.findall(".//{*}sdnEntry")

        vendor_words = [w.lower() for w in vendor_name.split() if len(w) >= 3]

        matches = []
        for entry in entries:
            # Get entity name
            last_name = entry.findtext("lastName", "") or entry.findtext("{*}lastName", "")
            first_name = entry.findtext("firstName", "") or entry.findtext("{*}firstName", "")
            sdn_type = entry.findtext("sdnType", "") or entry.findtext("{*}sdnType", "")

            full_name = f"{first_name} {last_name}".strip() if first_name else last_name
            if not full_name:
                continue

            name_lower = full_name.lower()

            # Match: ALL vendor words (3+ chars) must appear in the SDN name.
            # One direction only to prevent false positives from short SDN names.
            if len(vendor_words) >= 1 and all(w in name_lower for w in vendor_words):
                # Get program info
                programs = entry.findall("programList/program") or entry.findall("{*}programList/{*}program")
                program_names = [p.text for p in programs if p.text] if programs else []

                uid = entry.findtext("uid", "") or entry.findtext("{*}uid", "")

                matches.append({
                    "name": full_name,
                    "type": sdn_type,
                    "uid": uid,
                    "programs": program_names,
                })

                if len(matches) >= 5:
                    break

        if matches:
            for m in matches:
                result.findings.append(Finding(
                    source="ofac_sdn",
                    category="sanctions",
                    title=f"OFAC SDN MATCH: {m['name']}",
                    detail=f"Type: {m['type']} | UID: {m['uid']} | Programs: {', '.join(m['programs'][:3])}",
                    severity="critical",
                    confidence=0.95,
                    url="https://sanctionssearch.ofac.treas.gov/",
                ))
            result.risk_signals.append({
                "signal": "ofac_sdn_match",
                "severity": "critical",
                "detail": f"OFAC SDN match: {matches[0]['name']}",
            })
        else:
            result.findings.append(Finding(
                source="ofac_sdn",
                category="clearance",
                title="OFAC SDN: No matches found",
                detail=f"'{vendor_name}' not found on OFAC Specially Designated Nationals list.",
                severity="info",
                confidence=0.95,
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
    return result
