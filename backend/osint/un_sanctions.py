"""
UN Security Council Sanctions Connector

Queries the UN Security Council Consolidated Sanctions List directly:
  - Individuals subject to UN sanctions (travel bans, asset freezes)
  - Entities subject to UN sanctions
  - Associated aliases, nationalities, and designations
  - Sanctions committee designations (Al-Qaida, Taliban, DPRK, Iran, etc.)

Data Source: https://scsanctions.un.org/resources/xml/en/consolidated.xml
No authentication required. Updated regularly by the UN.

This provides a DIRECT check against UN sanctions rather than relying
on intermediary aggregators, ensuring primary source verification.
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Optional

from . import EnrichmentResult, Finding

# UN Security Council sanctions XML feed
CONSOLIDATED_XML = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
USER_AGENT = "Xiphos-Vetting/2.1"

# Shorter timeout since XML can be large
TIMEOUT = 30


def _normalize(name: str) -> str:
    """Normalize name for comparison."""
    import re
    name = name.lower().strip()
    name = re.sub(r'\b(inc|llc|ltd|plc|corp|co|sa|gmbh|ag|nv|bv)\b\.?', '', name)
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _name_match(query: str, candidate: str, threshold: float = 0.85) -> float:
    """Check if names match using substring and token overlap."""
    q_norm = _normalize(query)
    c_norm = _normalize(candidate)

    # Exact match
    if q_norm == c_norm:
        return 1.0

    # Substring match
    if q_norm in c_norm or c_norm in q_norm:
        shorter = min(len(q_norm), len(c_norm))
        longer = max(len(q_norm), len(c_norm))
        return shorter / longer if longer > 0 else 0.0

    # Token overlap
    q_tokens = set(q_norm.split())
    c_tokens = set(c_norm.split())
    if not q_tokens or not c_tokens:
        return 0.0

    overlap = q_tokens & c_tokens
    score = 2 * len(overlap) / (len(q_tokens) + len(c_tokens))
    return score


def _fetch_xml() -> ET.Element | None:
    """Fetch and parse the UN consolidated sanctions XML."""
    req = urllib.request.Request(CONSOLIDATED_XML, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            content = resp.read()
            return ET.fromstring(content)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ET.ParseError):
        return None


def _extract_individual_names(individual: ET.Element) -> list[str]:
    """Extract all name variations for an individual."""
    names = []

    # Primary name
    first = individual.findtext(".//FIRST_NAME", "")
    second = individual.findtext(".//SECOND_NAME", "")
    third = individual.findtext(".//THIRD_NAME", "")
    fourth = individual.findtext(".//FOURTH_NAME", "")

    parts = [p for p in [first, second, third, fourth] if p]
    if parts:
        names.append(" ".join(parts))

    # Aliases
    for alias in individual.findall(".//INDIVIDUAL_ALIAS"):
        alias_name = alias.findtext("ALIAS_NAME", "")
        if alias_name:
            names.append(alias_name)

    return names


def _extract_entity_names(entity: ET.Element) -> list[str]:
    """Extract all name variations for an entity."""
    names = []

    primary = entity.findtext(".//FIRST_NAME", "")
    if primary:
        names.append(primary)

    # Aliases
    for alias in entity.findall(".//ENTITY_ALIAS"):
        alias_name = alias.findtext("ALIAS_NAME", "")
        if alias_name:
            names.append(alias_name)

    return names


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query UN Security Council sanctions list for vendor matches."""
    t0 = time.time()
    result = EnrichmentResult(source="un_sanctions", vendor_name=vendor_name)

    try:
        root = _fetch_xml()

        if root is None:
            result.findings.append(Finding(
                source="un_sanctions",
                category="sanctions",
                title="UN Sanctions: Unable to fetch consolidated list",
                detail="Could not retrieve the UN Security Council consolidated sanctions XML.",
                severity="info",
                confidence=0.0,
            ))
            result.error = "Failed to fetch UN consolidated sanctions XML"
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        matches = []

        # Search individuals
        for individual in root.findall(".//INDIVIDUAL"):
            dataid = individual.findtext("DATAID", "")
            ref_num = individual.findtext("REFERENCE_NUMBER", "")
            listed_on = individual.findtext("LISTED_ON", "")
            comments = individual.findtext("COMMENTS1", "")
            un_list_type = individual.findtext("UN_LIST_TYPE", "")

            names = _extract_individual_names(individual)
            best_score = 0.0
            best_name = ""

            for name in names:
                score = _name_match(vendor_name, name)
                if score > best_score:
                    best_score = score
                    best_name = name

            if best_score >= 0.80:
                # Extract nationality
                nationalities = []
                for nat in individual.findall(".//NATIONALITY/VALUE"):
                    if nat.text:
                        nationalities.append(nat.text)

                # Extract designations
                designations = []
                for desig in individual.findall(".//DESIGNATION/VALUE"):
                    if desig.text:
                        designations.append(desig.text)

                matches.append({
                    "type": "individual",
                    "name": best_name,
                    "all_names": names,
                    "dataid": dataid,
                    "ref_num": ref_num,
                    "listed_on": listed_on,
                    "comments": comments,
                    "un_list_type": un_list_type,
                    "nationalities": nationalities,
                    "designations": designations,
                    "score": best_score,
                })

        # Search entities
        for entity in root.findall(".//ENTITY"):
            dataid = entity.findtext("DATAID", "")
            ref_num = entity.findtext("REFERENCE_NUMBER", "")
            listed_on = entity.findtext("LISTED_ON", "")
            comments = entity.findtext("COMMENTS1", "")
            un_list_type = entity.findtext("UN_LIST_TYPE", "")

            names = _extract_entity_names(entity)
            best_score = 0.0
            best_name = ""

            for name in names:
                score = _name_match(vendor_name, name)
                if score > best_score:
                    best_score = score
                    best_name = name

            if best_score >= 0.80:
                matches.append({
                    "type": "entity",
                    "name": best_name,
                    "all_names": names,
                    "dataid": dataid,
                    "ref_num": ref_num,
                    "listed_on": listed_on,
                    "comments": comments,
                    "un_list_type": un_list_type,
                    "nationalities": [],
                    "designations": [],
                    "score": best_score,
                })

        # Process matches
        if not matches:
            result.findings.append(Finding(
                source="un_sanctions",
                category="sanctions",
                title="No UN Security Council sanctions matches",
                detail=(
                    f"'{vendor_name}' not found in the UN Security Council "
                    f"Consolidated Sanctions List (individuals and entities)."
                ),
                severity="info",
                confidence=0.85,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        for match in matches:
            # UN sanctions matches are always critical
            severity = "critical"
            confidence = match["score"]

            aliases = [n for n in match["all_names"] if n != match["name"]]
            aliases_str = ", ".join(aliases[:5]) if aliases else "None"

            finding_detail = (
                f"Type: {match['type'].title()}\n"
                f"Name: {match['name']}\n"
                f"Aliases: {aliases_str}\n"
                f"UN List: {match['un_list_type']}\n"
                f"Reference: {match['ref_num']}\n"
                f"Listed On: {match['listed_on']}\n"
                f"Nationalities: {', '.join(match['nationalities']) if match['nationalities'] else 'N/A'}\n"
                f"Comments: {match['comments'][:300] if match['comments'] else 'N/A'}\n"
                f"Match Confidence: {confidence:.0%}"
            )

            result.findings.append(Finding(
                source="un_sanctions",
                category="sanctions",
                title=f"UN SANCTIONS: {match['name']} ({match['un_list_type']})",
                detail=finding_detail,
                severity=severity,
                confidence=confidence,
                url=f"https://scsanctions.un.org/search/?searchText={urllib.parse.quote(match['name'])}",
                raw_data={
                    "dataid": match["dataid"],
                    "ref_num": match["ref_num"],
                    "type": match["type"],
                    "un_list_type": match["un_list_type"],
                    "score": match["score"],
                },
            ))

            result.risk_signals.append({
                "signal": "un_sanctions_match",
                "severity": "critical",
                "detail": (
                    f"CRITICAL: {match['type'].title()} '{match['name']}' "
                    f"found on UN Security Council Consolidated Sanctions List. "
                    f"List: {match['un_list_type']}. Listed: {match['listed_on']}."
                ),
                "dataid": match["dataid"],
                "un_list_type": match["un_list_type"],
                "match_score": match["score"],
            })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
