"""
ICIJ Offshore Leaks Connector

Queries the ICIJ Offshore Leaks API for exposure in:
  - Panama Papers
  - Paradise Papers
  - Pandora Papers
  - Bahamas Leaks
  - Offshore Leaks

API: https://offshoreleaks.icij.org/api/v1/reconcile
No authentication required. Score >= 40 is treated as a match.

Each match can have types: Officer, Entity, Intermediary, Address
"""

import json
import time
import urllib.request
import urllib.error
from typing import Optional

from . import EnrichmentResult, Finding

BASE = "https://offshoreleaks.icij.org/api/v1"
USER_AGENT = "Xiphos-Vetting/2.1"

# Mapping of investigation names to sources
INVESTIGATION_SOURCES = {
    "Panama Papers": "panama_papers",
    "Paradise Papers": "paradise_papers",
    "Pandora Papers": "pandora_papers",
    "Bahamas Leaks": "bahamas_leaks",
    "Offshore Leaks": "offshore_leaks",
}


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
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _parse_investigation_source(description: str) -> str | None:
    """Extract investigation source from description."""
    for inv_name, source_key in INVESTIGATION_SOURCES.items():
        if inv_name in description:
            return source_key
    return None


def _query_reconcile(name: str, endpoint: str = "reconcile") -> list[dict]:
    """Query the reconciliation API."""
    payload = {"queries": {"q0": {"query": name}}}
    url = f"{BASE}/{endpoint}"
    data = _post(url, payload)
    if not data:
        return []

    # Response format: {"q0": {"result": [...]}}
    results = data.get("q0", {}).get("result", [])
    return results


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query ICIJ Offshore Leaks for vendor exposure."""
    t0 = time.time()
    result = EnrichmentResult(source="icij_offshore", vendor_name=vendor_name)

    try:
        # Query main reconcile endpoint
        matches = _query_reconcile(vendor_name)

        # Also try individual investigation endpoints for higher precision
        panama_matches = _query_reconcile(vendor_name, "reconcile/panama-papers")
        pandora_matches = _query_reconcile(vendor_name, "reconcile/pandora-papers")

        # Combine and deduplicate by ID
        all_matches = matches + panama_matches + pandora_matches
        seen_ids = set()
        unique_matches = []

        for match in all_matches:
            match_id = match.get("id", "")
            if match_id not in seen_ids:
                seen_ids.add(match_id)
                unique_matches.append(match)

        if not unique_matches:
            result.findings.append(Finding(
                source="icij_offshore",
                category="offshore_exposure",
                title="No ICIJ matches found",
                detail=f"'{vendor_name}' not found in ICIJ Offshore Leaks databases "
                       f"(Panama Papers, Paradise Papers, Pandora Papers, Bahamas Leaks, Offshore Leaks).",
                severity="info",
                confidence=0.8,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Process matches
        for match in unique_matches:
            match_id = match.get("id", "")
            name = match.get("name", "")
            description = match.get("description", "")
            score = match.get("score", 0)
            match_types = match.get("types", [])

            # Only report if score >= 40
            if score < 40:
                continue

            # Determine severity based on score and type
            if score >= 80:
                severity = "critical"
            elif score >= 60:
                severity = "high"
            else:
                severity = "medium"

            # Parse investigation source from description
            source = _parse_investigation_source(description)
            source_str = source or "unknown_investigation"

            # Determine type string for detail (types are dicts with name/id)
            types_str = ", ".join(
                t.get("name", str(t)) if isinstance(t, dict) else str(t)
                for t in match_types
            ) if match_types else "Unknown"

            finding_title = f"ICIJ match: {name} (Score: {score})"
            finding_detail = (
                f"ICIJ ID: {match_id}\n"
                f"Match Score: {score}/100\n"
                f"Entity Types: {types_str}\n"
                f"Investigation: {source_str}\n"
                f"Description: {description}"
            )

            result.findings.append(Finding(
                source="icij_offshore",
                category="offshore_exposure",
                title=finding_title,
                detail=finding_detail,
                severity=severity,
                confidence=score / 100.0,
                url=f"https://offshoreleaks.icij.org/search?q={match_id}",
                raw_data={
                    "id": match_id,
                    "score": score,
                    "types": match_types,
                    "investigation": source_str,
                },
            ))

            result.risk_signals.append({
                "signal": "offshore_entity_match",
                "severity": severity,
                "detail": f"Entity '{name}' matched in ICIJ {source_str.replace('_', ' ').title()} "
                         f"with confidence score {score}/100",
                "match_id": match_id,
                "score": score,
            })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
