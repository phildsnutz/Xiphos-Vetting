"""
BIS Consolidated Screening List (CSL) - LIVE DATA Connector

Downloads the full CSL JSON from Trade.gov and searches locally:
  - Entity List (BIS)
  - Denied Persons List (BIS)
  - Unverified List (BIS)
  - Military End User List (BIS)
  - Non-SDN Chinese Military-Industrial Complex Companies (OFAC)
  - SDN List (OFAC)
  - ITAR Debarred (State Dept)
  - And 5+ others

Data: https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.json
Updated daily at 5:00 AM EST by Commerce Department.
No authentication required.

Strategy: Download full JSON (~31 MB), cache 24 hours, search in-memory.
"""

import json
import os
import re
import threading
import time
import urllib.request
import urllib.error

from . import EnrichmentResult, Finding

CSL_URL = "https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.json"
USER_AGENT = "Xiphos/4.0 (compliance-tool@xiphos.dev)"
CACHE_FILE = "/tmp/trade_csl_consolidated.json"
CACHE_TTL = 86400  # 24 hours
DOWNLOAD_TIMEOUT = 60  # 31 MB takes ~25s on a fast connection

# Module-level cache to avoid re-parsing JSON on every call
_cached_entries: list[dict] | None = None
_cache_loaded_at: float = 0.0
_cache_lock = threading.Lock()


def _normalize(name: str) -> str:
    """Normalize name for comparison."""
    name = name.lower().strip()
    name = re.sub(r'\b(inc|llc|ltd|plc|corp|co|sa|gmbh|ag|nv|bv)\b\.?', '', name)
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _name_match(query: str, candidate: str) -> float:
    """Score name similarity (0.0 to 1.0)."""
    q = _normalize(query)
    c = _normalize(candidate)

    if not q or not c:
        return 0.0

    # Exact match
    if q == c:
        return 1.0

    # Substring containment
    if q in c or c in q:
        shorter = min(len(q), len(c))
        longer = max(len(q), len(c))
        return shorter / longer if longer > 0 else 0.0

    # Token overlap (Dice coefficient)
    q_tokens = set(q.split())
    c_tokens = set(c.split())
    if not q_tokens or not c_tokens:
        return 0.0

    overlap = q_tokens & c_tokens
    return 2 * len(overlap) / (len(q_tokens) + len(c_tokens))


def _load_csl_data() -> list[dict]:
    """Load CSL data from cache or download fresh."""
    global _cached_entries, _cache_loaded_at

    with _cache_lock:
        now = time.time()

        # Check in-memory cache first
        if _cached_entries is not None and (now - _cache_loaded_at) < CACHE_TTL:
            return _cached_entries

        # Check file cache
        if os.path.exists(CACHE_FILE):
            cache_age = now - os.path.getmtime(CACHE_FILE)
            if cache_age < CACHE_TTL:
                try:
                    with open(CACHE_FILE, 'r') as f:
                        data = json.load(f)
                        _cached_entries = data.get("results", [])
                        _cache_loaded_at = now
                        return _cached_entries
                except (json.JSONDecodeError, IOError):
                    pass  # Fall through to download

        # Download fresh from Trade.gov
        req = urllib.request.Request(CSL_URL, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })

        try:
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read()

                # Validate we got JSON, not HTML
                if "html" in content_type.lower() or raw[:20].startswith(b"<!DOCTYPE"):
                    raise ValueError(f"CSL API returned HTML instead of JSON (Content-Type: {content_type})")

                # Cache to file
                try:
                    with open(CACHE_FILE, 'wb') as f:
                        f.write(raw)
                except IOError:
                    pass  # Cache write failed, continue with data

                data = json.loads(raw)
                _cached_entries = data.get("results", [])
                _cache_loaded_at = now
                return _cached_entries

        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            # Try stale cache as fallback
            if os.path.exists(CACHE_FILE):
                try:
                    with open(CACHE_FILE, 'r') as f:
                        data = json.load(f)
                        _cached_entries = data.get("results", [])
                        _cache_loaded_at = now
                        return _cached_entries
                except (json.JSONDecodeError, IOError):
                    pass
            raise RuntimeError(f"CSL download failed and no cache available: {e}")


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Search Trade.gov CSL data for export screening matches."""
    t0 = time.time()
    result = EnrichmentResult(source="trade_csl", vendor_name=vendor_name)

    try:
        entries = _load_csl_data()

        if not entries:
            result.error = "CSL data empty or unavailable"
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Search for matches
        matches = []
        for entry in entries:
            name = entry.get("name", "")
            score = _name_match(vendor_name, name)

            # Also check alt_names
            alt_names = entry.get("alt_names", []) or []
            for alt in alt_names:
                if isinstance(alt, str):
                    alt_score = _name_match(vendor_name, alt)
                    if alt_score > score:
                        score = alt_score

            if score >= 0.80:
                matches.append((score, entry))

        # Sort by score descending
        matches.sort(key=lambda x: x[0], reverse=True)

        if not matches:
            result.findings.append(Finding(
                source="trade_csl", category="screening",
                title="CSL clear",
                detail=(
                    f"No matches found for '{vendor_name}' in Trade.gov "
                    f"Consolidated Screening List ({len(entries):,} entries screened)."
                ),
                severity="info", confidence=0.9,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Process top matches (cap at 10)
        for score, match in matches[:10]:
            name = match.get("name", "")
            source = match.get("source", "")
            alt_names = match.get("alt_names", []) or []
            programs = match.get("programs", []) or []
            addresses = match.get("addresses", []) or []
            remarks = match.get("remarks", "")

            # Determine severity by source list
            severity = "high"  # default
            if "Entity List" in source:
                severity = "critical"
            elif "Denied Persons" in source:
                severity = "critical"
            elif "SDN" in source and "Non-SDN" not in source:
                severity = "critical"
            elif "ITAR Debarred" in source:
                severity = "critical"
            elif "Military End User" in source:
                severity = "high"
            elif "Unverified" in source:
                severity = "high"
            elif "Non-SDN" in source:
                severity = "medium"

            detail_parts = [
                f"Name: {name}",
                f"Source: {source}",
                f"Match Score: {score:.0%}",
            ]

            if alt_names:
                alias_strs = [a for a in alt_names if isinstance(a, str)]
                if alias_strs:
                    detail_parts.append(f"Aliases: {'; '.join(alias_strs[:5])}")

            if programs:
                prog_strs = [p for p in programs if isinstance(p, str)]
                if prog_strs:
                    detail_parts.append(f"Programs: {'; '.join(prog_strs[:3])}")

            if addresses:
                addr = addresses[0]
                if isinstance(addr, dict):
                    addr_str = ", ".join(filter(None, [
                        addr.get("address", ""),
                        addr.get("city", ""),
                        addr.get("state", ""),
                        addr.get("country", ""),
                    ]))
                else:
                    addr_str = str(addr)
                detail_parts.append(f"Address: {addr_str}")

            if remarks:
                detail_parts.append(f"Remarks: {remarks[:200]}")

            result.findings.append(Finding(
                source="trade_csl", category="screening",
                title=f"CSL MATCH: {name} [{source}]",
                detail="\n".join(detail_parts),
                severity=severity,
                confidence=score,
                url=match.get("source_information_url", "https://www.trade.gov/consolidated-screening-list"),
                raw_data=match,
            ))

            result.risk_signals.append({
                "signal": "csl_match",
                "severity": severity,
                "detail": f"Entity '{name}' found on {source} (match: {score:.0%})",
            })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
