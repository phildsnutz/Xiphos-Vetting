"""
Trade.gov Consolidated Screening List (CSL) Connector

The CSL combines 13 export screening lists from Commerce, State, and Treasury:
  - Entity List (BIS)
  - Denied Persons List (BIS)
  - Unverified List (BIS)
  - Military End User List (BIS)
  - Non-SDN Chinese Military-Industrial Complex Companies (OFAC)
  - Sectoral Sanctions Identifications (OFAC)
  - Foreign Sanctions Evaders (OFAC)
  - Palestinian Legislative Council (OFAC)
  - ITAR Debarred (DDTC / State Dept)
  - Nonproliferation Sanctions (State Dept)
  - And more...

CSV download, updated daily at 5 AM EST.
https://www.trade.gov/consolidated-screening-list
"""

import csv
import io
import time
import urllib.request
import urllib.error
from typing import Optional

from . import EnrichmentResult, Finding
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ofac import jaro_winkler

CSL_URL = "https://api.trade.gov/static/consolidated_screening_list/consolidated.csv"
USER_AGENT = "Xiphos-Vetting/2.1"

# Module-level cache
_csl_cache: Optional[list[dict]] = None
_csl_loaded_at: float = 0
_CACHE_TTL = 3600  # 1 hour


def _load_csl() -> list[dict]:
    """Download and parse the CSL CSV."""
    global _csl_cache, _csl_loaded_at

    if _csl_cache is not None and (time.time() - _csl_loaded_at) < _CACHE_TTL:
        return _csl_cache

    req = urllib.request.Request(CSL_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read().decode("utf-8-sig", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return _csl_cache or []

    reader = csv.DictReader(io.StringIO(data))
    records = []
    for row in reader:
        name = (row.get("name", "") or "").strip()
        if not name:
            continue
        records.append({
            "name": name,
            "alt_names": (row.get("alt_names", "") or "").strip(),
            "source": (row.get("source", "") or "").strip(),
            "source_list_url": (row.get("source_list_url", "") or "").strip(),
            "entity_number": (row.get("entity_number", "") or "").strip(),
            "type": (row.get("type", "") or "").strip(),
            "programs": (row.get("programs", "") or "").strip(),
            "addresses": (row.get("addresses", "") or "").strip(),
            "federal_register_notice": (row.get("federal_register_notice", "") or "").strip(),
            "start_date": (row.get("start_date", "") or "").strip(),
            "end_date": (row.get("end_date", "") or "").strip(),
            "remarks": (row.get("remarks", "") or "").strip()[:300],
        })

    _csl_cache = records
    _csl_loaded_at = time.time()
    return records


def enrich(vendor_name: str, country: str = "", threshold: float = 0.85, **ids) -> EnrichmentResult:
    """Screen a vendor against the full Consolidated Screening List."""
    t0 = time.time()
    result = EnrichmentResult(source="trade_csl", vendor_name=vendor_name)

    try:
        records = _load_csl()
        if not records:
            result.error = "Failed to load CSL data"
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        matches = []

        for rec in records:
            # Check primary name
            score = jaro_winkler(vendor_name, rec["name"])
            if score >= threshold:
                matches.append({"score": score, "matched_on": rec["name"], **rec})

            # Check alternate names
            for alt in rec["alt_names"].split(";"):
                alt = alt.strip()
                if alt:
                    score = jaro_winkler(vendor_name, alt)
                    if score >= threshold:
                        matches.append({"score": score, "matched_on": alt, **rec})

        matches.sort(key=lambda m: m["score"], reverse=True)

        # Deduplicate by entity_number
        seen = set()
        unique_matches = []
        for m in matches:
            key = m.get("entity_number", "") or m["name"]
            if key not in seen:
                seen.add(key)
                unique_matches.append(m)

        if unique_matches:
            for m in unique_matches[:10]:
                severity = "critical" if m["score"] > 0.95 else "high" if m["score"] > 0.88 else "medium"
                result.findings.append(Finding(
                    source="trade_csl", category="screening",
                    title=f"CSL MATCH ({m['score']:.1%}): {m['name']} [{m['source']}]",
                    detail=(
                        f"Matched on: {m['matched_on']} | Source list: {m['source']} | "
                        f"Programs: {m['programs']} | Type: {m['type']} | "
                        f"Remarks: {m['remarks']}"
                    ),
                    severity=severity,
                    confidence=m["score"],
                    url=m.get("source_list_url", ""),
                    raw_data=m,
                ))

                result.risk_signals.append({
                    "signal": "csl_match",
                    "severity": severity,
                    "detail": f"Matched '{m['matched_on']}' on {m['source']} (score: {m['score']:.3f})",
                })
        else:
            result.findings.append(Finding(
                source="trade_csl", category="screening",
                title="CSL clear",
                detail=f"No matches found for '{vendor_name}' against {len(records):,} CSL entries.",
                severity="info", confidence=0.8,
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
