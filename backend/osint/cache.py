"""
OSINT Enrichment Cache

Per-connector, per-vendor result caching to avoid redundant API calls
during re-enrichment within a configurable time window.

Sanctions/critical sources: 4-hour TTL (must stay fresh)
Identity/context sources: 24-hour TTL (changes slowly)
Media/news sources: 2-hour TTL (changes frequently)

Cache is stored in-memory with optional SQLite persistence.
Thread-safe for concurrent access from the enrichment pipeline.
"""

import json
import time
import hashlib
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# TTL configuration by connector category (seconds)
TTL_SANCTIONS = 4 * 3600       # 4 hours for sanctions/exclusion lists
TTL_IDENTITY = 24 * 3600       # 24 hours for corporate identity sources
TTL_MEDIA = 2 * 3600           # 2 hours for news/media sources
TTL_DEFAULT = 12 * 3600        # 12 hours for everything else

CONNECTOR_TTL = {
    # Sanctions (4h)
    "dod_sam_exclusions": TTL_SANCTIONS,
    "trade_csl": TTL_SANCTIONS,
    "un_sanctions": TTL_SANCTIONS,
    "ofac_sdn": TTL_SANCTIONS,
    "eu_sanctions": TTL_SANCTIONS,
    "uk_hmt_sanctions": TTL_SANCTIONS,
    "opensanctions_pep": TTL_SANCTIONS,
    "worldbank_debarred": TTL_SANCTIONS,
    # Media (2h)
    "gdelt_media": TTL_MEDIA,
    "google_news": TTL_MEDIA,
    # Identity (24h)
    "sec_edgar": TTL_IDENTITY,
    "gleif_lei": TTL_IDENTITY,
    "opencorporates": TTL_IDENTITY,
    "uk_companies_house": TTL_IDENTITY,
    "corporations_canada": TTL_IDENTITY,
    "australia_abn_asic": TTL_IDENTITY,
    "singapore_acra": TTL_IDENTITY,
    "new_zealand_companies_office": TTL_IDENTITY,
    "norway_brreg": TTL_IDENTITY,
    "wikidata_company": TTL_IDENTITY,
    "public_html_ownership": TTL_IDENTITY,
    "sam_gov": TTL_IDENTITY,
    "usaspending": TTL_IDENTITY,
    "fpds_contracts": TTL_IDENTITY,
    "sbir_awards": TTL_IDENTITY,
    "sec_xbrl": TTL_IDENTITY,
    # Litigation (24h - court records change slowly)
    "recap_courts": TTL_IDENTITY,
}


def _cache_key(vendor_name: str, connector_name: str, country: str = "", variant: str = "") -> str:
    """Generate a stable cache key for a vendor + connector combination."""
    raw = f"{vendor_name.strip().lower()}|{connector_name}|{country.strip().upper()}|{variant.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class EnrichmentCache:
    """Thread-safe in-memory cache for OSINT enrichment results."""

    def __init__(self, enabled: bool = True, max_entries: int = 5000):
        self._enabled = enabled
        self._max_entries = max_entries
        self._store: dict[str, dict] = {}  # key -> {result_json, timestamp, connector, vendor}
        self._lock = threading.Lock()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0, "stores": 0}

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def stats(self) -> dict:
        with self._lock:
            fresh = sum(1 for v in self._store.values() if not self._is_expired(v))
            expired = len(self._store) - fresh
            return {
                **self._stats,
                "total_entries": len(self._store),
                "fresh_entries": fresh,
                "expired_entries": expired,
            }

    def _is_expired(self, entry: dict) -> bool:
        connector = entry.get("connector", "")
        ttl = CONNECTOR_TTL.get(connector, TTL_DEFAULT)
        return (time.time() - entry["timestamp"]) > ttl

    def get(self, vendor_name: str, connector_name: str, country: str = "", variant: str = "") -> Optional[dict]:
        """
        Retrieve a cached result if it exists and is not expired.
        Returns None on miss.
        """
        if not self._enabled:
            return None

        key = _cache_key(vendor_name, connector_name, country, variant)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._stats["misses"] += 1
                return None
            if self._is_expired(entry):
                del self._store[key]
                self._stats["misses"] += 1
                return None
            self._stats["hits"] += 1
            return json.loads(entry["result_json"])

    def put(self, vendor_name: str, connector_name: str, country: str, result_data: dict, variant: str = ""):
        """Store an enrichment result in the cache."""
        if not self._enabled:
            return

        key = _cache_key(vendor_name, connector_name, country, variant)
        result_json = json.dumps(result_data, default=str)

        with self._lock:
            # Evict oldest entries if at capacity
            if len(self._store) >= self._max_entries and key not in self._store:
                oldest_key = min(self._store, key=lambda k: self._store[k]["timestamp"])
                del self._store[oldest_key]
                self._stats["evictions"] += 1

            self._store[key] = {
                "result_json": result_json,
                "timestamp": time.time(),
                "connector": connector_name,
                "vendor": vendor_name,
                "country": country.strip().upper(),
                "variant": variant,
            }
            self._stats["stores"] += 1

    def invalidate(self, vendor_name: str, connector_name: str = "", country: str = "", variant: str = ""):
        """Invalidate cache entries. If connector_name is empty, invalidate all entries for the vendor."""
        if not self._enabled:
            return

        with self._lock:
            if connector_name:
                vendor_lower = vendor_name.strip().lower()
                country_upper = country.strip().upper()
                if variant:
                    key = _cache_key(vendor_name, connector_name, country, variant)
                    self._store.pop(key, None)
                    return
                to_remove = [
                    k
                    for k, v in self._store.items()
                    if v.get("vendor", "").strip().lower() == vendor_lower
                    and v.get("connector") == connector_name
                    and (not country_upper or v.get("country", "") == country_upper)
                ]
                for k in to_remove:
                    del self._store[k]
            else:
                # Invalidate all entries for this vendor
                vendor_lower = vendor_name.strip().lower()
                to_remove = [k for k, v in self._store.items() if v["vendor"].strip().lower() == vendor_lower]
                for k in to_remove:
                    del self._store[k]

    def clear(self):
        """Clear the entire cache."""
        with self._lock:
            self._store.clear()
            self._stats = {"hits": 0, "misses": 0, "evictions": 0, "stores": 0}

    def vendor_freshness(self, vendor_name: str) -> dict:
        """Get per-connector freshness info for a vendor."""
        vendor_lower = vendor_name.strip().lower()
        now = time.time()
        connectors = {}
        with self._lock:
            for entry in self._store.values():
                if entry["vendor"].strip().lower() != vendor_lower:
                    continue
                cn = entry["connector"]
                ts = entry["timestamp"]
                ttl = CONNECTOR_TTL.get(cn, TTL_DEFAULT)
                age = now - ts
                connectors[cn] = {
                    "cached_at": ts,
                    "age_seconds": round(age),
                    "ttl_seconds": ttl,
                    "fresh": age < ttl,
                    "expires_in": max(0, round(ttl - age)),
                }
        total = len(connectors)
        fresh = sum(1 for v in connectors.values() if v["fresh"])
        return {
            "vendor": vendor_name,
            "connectors_cached": total,
            "connectors_fresh": fresh,
            "connectors_expired": total - fresh,
            "details": connectors,
        }

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        with self._lock:
            expired_keys = [k for k, v in self._store.items() if self._is_expired(v)]
            for k in expired_keys:
                del self._store[k]
            return len(expired_keys)


# Module-level singleton
_cache = EnrichmentCache(enabled=True)


def get_cache() -> EnrichmentCache:
    """Get the global enrichment cache instance."""
    return _cache
