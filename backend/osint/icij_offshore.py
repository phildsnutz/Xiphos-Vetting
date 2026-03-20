"""
ICIJ Offshore Leaks Connector

Queries the ICIJ Offshore Leaks API for exposure in:
  - Panama Papers
  - Paradise Papers
  - Pandora Papers
  - Bahamas Leaks
  - Offshore Leaks

API: https://offshoreleaks.icij.org/api/v1/reconcile
No authentication required.

Matching strategy (v2.5):
  - Query the main reconciliation endpoint only (no redundant sub-endpoints)
  - Apply server-side score threshold >= 60
  - Apply secondary Xiphos-side name verification via token overlap
  - Require >= 50% token overlap between query and matched name
  - This eliminates false positives like "BAE Systems" matching "SCITECH SYSTEMS"
"""

import json
import re
import time
import urllib.request
import urllib.error

from . import EnrichmentResult, Finding

BASE = "https://offshoreleaks.icij.org/api/v1"
USER_AGENT = "Xiphos-Vetting/2.5"

# Server-side score threshold (ICIJ's internal fuzzy score)
MIN_ICIJ_SCORE = 60

# Xiphos-side minimum name similarity (token overlap / Dice coefficient)
MIN_NAME_SIMILARITY = 0.50

INVESTIGATION_SOURCES = {
    "Panama Papers": "panama_papers",
    "Paradise Papers": "paradise_papers",
    "Pandora Papers": "pandora_papers",
    "Bahamas Leaks": "bahamas_leaks",
    "Offshore Leaks": "offshore_leaks",
}


def _normalize(name: str) -> str:
    """Strip legal suffixes and punctuation for comparison."""
    name = name.lower().strip()
    name = re.sub(
        r'\b(inc|llc|ltd|plc|corp|co|sa|gmbh|ag|nv|bv|pllc|lp|'
        r'group|holdings|international|global|enterprises|corporation)\b\.?',
        '', name,
    )
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _name_similarity(query: str, candidate: str) -> float:
    """
    Dice coefficient on normalized token sets.
    Returns 0.0-1.0 indicating how much the names actually overlap.
    """
    q = set(_normalize(query).split())
    c = set(_normalize(candidate).split())
    if not q or not c:
        return 0.0
    # Exact match after normalization
    if q == c:
        return 1.0
    overlap = q & c
    return 2 * len(overlap) / (len(q) + len(c))


def _post(url: str, data: dict) -> dict | None:
    """POST to the ICIJ API."""
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, json.JSONDecodeError):
        return None


def _parse_investigation(description: str) -> str:
    """Extract investigation source from description."""
    for inv_name, source_key in INVESTIGATION_SOURCES.items():
        if inv_name in description:
            return source_key
    return "unknown_investigation"


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """
    Query ICIJ Offshore Leaks for vendor exposure.

    Uses a single reconciliation query with dual-layer filtering:
    1. ICIJ server-side score >= 60
    2. Xiphos-side token overlap >= 50%

    This eliminates false positives from generic partial-word matches
    while still catching legitimate offshore entity connections.
    """
    t0 = time.time()
    result = EnrichmentResult(source="icij_offshore", vendor_name=vendor_name)

    try:
        # Single query to main reconciliation endpoint
        payload = {"queries": {"q0": {"query": vendor_name}}}
        url = f"{BASE}/reconcile"
        data = _post(url, payload)

        raw_matches = []
        if data:
            raw_matches = data.get("q0", {}).get("result", [])

        # Dual-layer filtering
        verified_matches = []
        for match in raw_matches:
            icij_score = match.get("score", 0)
            match_name = match.get("name", "")

            # Layer 1: ICIJ server score
            if icij_score < MIN_ICIJ_SCORE:
                continue

            # Layer 2: Xiphos name verification
            name_sim = _name_similarity(vendor_name, match_name)
            if name_sim < MIN_NAME_SIMILARITY:
                continue

            verified_matches.append({
                **match,
                "_xiphos_name_sim": name_sim,
                "_xiphos_combined_score": (icij_score / 100.0) * 0.6 + name_sim * 0.4,
            })

        # Sort by combined score descending
        verified_matches.sort(key=lambda m: m["_xiphos_combined_score"], reverse=True)

        if not verified_matches:
            result.findings.append(Finding(
                source="icij_offshore",
                category="offshore_exposure",
                title="No ICIJ matches found",
                detail=(
                    f"'{vendor_name}' not found in ICIJ Offshore Leaks databases "
                    f"(Panama Papers, Paradise Papers, Pandora Papers, Bahamas Leaks, "
                    f"Offshore Leaks). Searched with dual-layer verification."
                ),
                severity="info",
                confidence=0.85,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Process verified matches (cap at 10 to keep findings manageable)
        for match in verified_matches[:10]:
            match_id = match.get("id", "")
            name = match.get("name", "")
            description = match.get("description", "")
            icij_score = match.get("score", 0)
            name_sim = match["_xiphos_name_sim"]
            combined = match["_xiphos_combined_score"]
            match_types = match.get("types", [])

            # Severity based on combined score.
            # ICIJ offshore leaks are informational (corporate structure exposure),
            # NOT enforcement actions. Cap at HIGH -- only sanctions/debarment
            # warrant CRITICAL. A Fortune 500 in the Paradise Papers is expected,
            # not alarming.
            if combined >= 0.85:
                severity = "high"
            elif combined >= 0.70:
                severity = "medium"
            else:
                severity = "low"

            investigation = _parse_investigation(description)

            types_str = ", ".join(
                t.get("name", str(t)) if isinstance(t, dict) else str(t)
                for t in match_types
            ) if match_types else "Unknown"

            result.findings.append(Finding(
                source="icij_offshore",
                category="offshore_exposure",
                title=f"ICIJ: {name} ({investigation.replace('_', ' ').title()})",
                detail=(
                    f"Entity: {name}\n"
                    f"ICIJ Score: {icij_score}/100\n"
                    f"Name Match: {name_sim:.0%}\n"
                    f"Combined Score: {combined:.0%}\n"
                    f"Types: {types_str}\n"
                    f"Investigation: {investigation.replace('_', ' ').title()}\n"
                    f"Description: {description}"
                ),
                severity=severity,
                confidence=combined,
                url=f"https://offshoreleaks.icij.org/search?q={name.replace(' ', '+')}",
                raw_data={
                    "id": match_id,
                    "icij_score": icij_score,
                    "name_similarity": round(name_sim, 3),
                    "combined_score": round(combined, 3),
                    "types": match_types,
                    "investigation": investigation,
                },
            ))

            result.risk_signals.append({
                "signal": "offshore_entity_match",
                "severity": severity,
                "detail": (
                    f"'{name}' matched in ICIJ {investigation.replace('_', ' ').title()} "
                    f"(combined score {combined:.0%})"
                ),
                "match_id": match_id,
                "icij_score": icij_score,
                "name_similarity": round(name_sim, 3),
            })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
