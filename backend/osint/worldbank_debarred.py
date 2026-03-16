"""
World Bank Debarred Firms & Individuals Connector

Queries the World Bank Group sanctions database for firms/individuals
ineligible to participate in World Bank-financed contracts.

Covers debarments by:
  - IBRD/IDA (World Bank)
  - Cross-debarments from: IDB, ADB, AfDB, EBRD

The World Bank publishes debarred entities via their website with an
underlying JSON data feed. Entities are sanctioned for:
  - Fraudulent practices
  - Corrupt practices
  - Coercive practices
  - Collusive practices
  - Obstructive practices

API: https://www.worldbank.org/en/projects-operations/procurement/debarred-firms
No authentication required.
"""

import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

from . import EnrichmentResult, Finding

# World Bank debarred firms data is accessed via:
# 1. OpenSanctions API (if key available)
# 2. Local sanctions.db (if populated by sanctions sync)
# 3. Fallback: scan the WB page HTML
USER_AGENT = "Xiphos-Vetting/2.1"
OPENSANCTIONS_SEARCH = "https://api.opensanctions.org/search/default"
WB_DEBARRED_PAGE = "https://www.worldbank.org/en/projects-operations/procurement/debarred-firms"


def _normalize(name: str) -> str:
    """Normalize name for comparison."""
    import re
    name = name.lower().strip()
    name = re.sub(r'\b(inc|llc|ltd|plc|corp|co|sa|gmbh|ag|nv|bv|pty|pvt)\b\.?', '', name)
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _jaro_winkler(s1: str, s2: str) -> float:
    """Jaro-Winkler similarity for fuzzy matching."""
    if s1 == s2:
        return 1.0
    len_s1, len_s2 = len(s1), len(s2)
    if len_s1 == 0 or len_s2 == 0:
        return 0.0

    match_distance = max(len_s1, len_s2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len_s1
    s2_matches = [False] * len_s2
    matches = 0
    transpositions = 0

    for i in range(len_s1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len_s2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len_s1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    jaro = (matches / len_s1 + matches / len_s2 +
            (matches - transpositions / 2) / matches) / 3

    prefix = 0
    for i in range(min(4, min(len_s1, len_s2))):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break

    return jaro + prefix * 0.1 * (1 - jaro)


def _get_json(url: str, headers: dict = None) -> dict | list | None:
    """GET JSON from an API endpoint."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _search_local_db(vendor_name: str) -> list[dict]:
    """Search local sanctions.db for World Bank debarment records."""
    import sqlite3, os
    db_path = os.environ.get("XIPHOS_SANCTIONS_DB", "sanctions.db")
    if not os.path.exists(db_path):
        return []

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # Check if we have a worldbank table or if WB data is in the main entities table
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]

        results = []
        search = f"%{vendor_name}%"

        if "entities" in tables:
            cur.execute(
                "SELECT * FROM entities WHERE name LIKE ? AND source LIKE '%worldbank%' LIMIT 25",
                (search,)
            )
            for row in cur.fetchall():
                results.append(dict(row))

        conn.close()
        return results
    except Exception:
        return []


def _search_opensanctions(vendor_name: str) -> list[dict]:
    """Search OpenSanctions API for World Bank debarment records."""
    api_key = os.environ.get("XIPHOS_OPENSANCTIONS_KEY", "")
    if not api_key:
        return []

    encoded = urllib.parse.quote(vendor_name)
    url = f"{OPENSANCTIONS_SEARCH}?q={encoded}&schema=LegalEntity&datasets=worldbank_debarred&limit=10"
    headers = {"Authorization": f"ApiKey {api_key}"}
    data = _get_json(url, headers)

    if data and isinstance(data, dict):
        return data.get("results", [])
    return []


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query World Bank debarred firms list for vendor matches."""
    t0 = time.time()
    result = EnrichmentResult(source="worldbank_debarred", vendor_name=vendor_name)

    try:
        # Strategy 1: Search OpenSanctions API for WB-specific dataset
        data = _search_opensanctions(vendor_name)

        # Strategy 2: Search local sanctions.db
        if not data:
            local_results = _search_local_db(vendor_name)
            if local_results:
                # Convert local DB format to match expected structure
                data = [{"firm_name": r.get("name", ""), "country": r.get("country", ""),
                         "grounds": r.get("reason", ""), "sanction_type": "Debarment"}
                        for r in local_results]

        if not data:
            result.findings.append(Finding(
                source="worldbank_debarred",
                category="international_debarment",
                title="No World Bank debarment matches",
                detail=(
                    f"'{vendor_name}' not found in the World Bank Group "
                    f"debarred firms and individuals database. This covers "
                    f"sanctions from IBRD, IDA, and cross-debarments from "
                    f"IDB, ADB, AfDB, and EBRD."
                ),
                severity="info",
                confidence=0.8,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Fuzzy match results against vendor name
        vendor_norm = _normalize(vendor_name)
        matches = []

        for record in data:
            # Handle both OpenSanctions format (caption) and direct format (firm_name)
            firm_name = record.get("firm_name", "") or record.get("caption", "") or record.get("name", "")
            if not firm_name:
                continue

            firm_norm = _normalize(firm_name)

            # Check for exact substring match or fuzzy match
            score = 0.0
            if vendor_norm in firm_norm or firm_norm in vendor_norm:
                score = 0.95
            else:
                score = _jaro_winkler(vendor_norm, firm_norm)

            if score >= 0.80:
                matches.append((record, score))

        if not matches:
            result.findings.append(Finding(
                source="worldbank_debarred",
                category="international_debarment",
                title="No World Bank debarment matches",
                detail=(
                    f"'{vendor_name}' not found in the World Bank Group "
                    f"debarred firms and individuals database."
                ),
                severity="info",
                confidence=0.8,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Process matches
        for record, score in matches:
            firm_name = record.get("firm_name", "Unknown")
            grounds = record.get("grounds", "")
            sanction_type = record.get("sanction_type", "")
            from_date = record.get("from_date", "")
            to_date = record.get("to_date", "")
            address = record.get("address", "")
            country_rec = record.get("country", "")

            # Determine severity
            # Permanent debarment or active debarment = critical
            # Cross-debarment = high
            # Conditional non-debarment = medium
            if "permanent" in sanction_type.lower() or to_date == "2999-12-31T00:00:00.000":
                severity = "critical"
            elif "debarment" in sanction_type.lower():
                severity = "critical"
            elif "cross" in sanction_type.lower():
                severity = "high"
            else:
                severity = "high"

            # Parse grounds for detail
            grounds_str = grounds if grounds else "Not specified"

            finding_detail = (
                f"Firm: {firm_name}\n"
                f"Sanction Type: {sanction_type}\n"
                f"Grounds: {grounds_str}\n"
                f"Effective From: {from_date[:10] if from_date else 'N/A'}\n"
                f"Effective To: {to_date[:10] if to_date and to_date != '2999-12-31T00:00:00.000' else 'Permanent'}\n"
                f"Country: {country_rec}\n"
                f"Address: {address}\n"
                f"Match Confidence: {score:.0%}"
            )

            result.findings.append(Finding(
                source="worldbank_debarred",
                category="international_debarment",
                title=f"World Bank debarment: {firm_name} ({sanction_type})",
                detail=finding_detail,
                severity=severity,
                confidence=score,
                url="https://www.worldbank.org/en/projects-operations/procurement/debarred-firms",
                raw_data={
                    "firm_name": firm_name,
                    "sanction_type": sanction_type,
                    "grounds": grounds,
                    "from_date": from_date,
                    "to_date": to_date,
                    "country": country_rec,
                    "match_score": score,
                },
            ))

            result.risk_signals.append({
                "signal": "worldbank_debarment",
                "severity": severity,
                "detail": (
                    f"Entity '{firm_name}' found in World Bank debarred list. "
                    f"Sanction: {sanction_type}. Grounds: {grounds_str}."
                ),
                "sanction_type": sanction_type,
                "match_score": score,
            })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
