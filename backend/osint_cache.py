"""
OSINT Enrichment Cache

Thread-safe caching layer for OSINT connector results. Prevents redundant
API calls, respects rate limits, and enables instant re-queries within
the TTL window.

Storage: SQLite (same DB as main Xiphos data)
Default TTL: 4 hours for enrichment reports, 30 minutes for individual connectors
UN sanctions XML: cached for 24 hours (large 2MB file, updated daily)

Usage:
    from osint_cache import CachedEnrichment
    enricher = CachedEnrichment()
    report = enricher.enrich("BAE Systems plc", country="GB")
"""

import hashlib
import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from typing import Optional


# TTLs in seconds
DEFAULT_TTL = 4 * 3600        # 4 hours for full enrichment reports
CONNECTOR_TTL = 30 * 60       # 30 minutes for individual connector results
HEAVY_TTL = 24 * 3600         # 24 hours for large/slow sources (UN XML, etc.)
RATE_LIMIT_WINDOW = 2          # Minimum seconds between identical requests

# Connectors that should use longer TTL (expensive to fetch)
HEAVY_CONNECTORS = {"un_sanctions", "trade_csl", "icij_offshore"}

# Use XIPHOS_DB_PATH (matching Dockerfile/compose), with fallback to XIPHOS_DB for legacy compatibility
DB_PATH = os.environ.get("XIPHOS_DB_PATH", os.environ.get("XIPHOS_DB", "xiphos.db"))

_lock = threading.Lock()


def _cache_key(vendor_name: str, country: str, connector: str = "") -> str:
    """Generate a deterministic cache key."""
    raw = f"{vendor_name.strip().lower()}|{country.strip().lower()}|{connector}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _init_cache_table(conn: sqlite3.Connection):
    """Create cache table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS osint_cache (
            cache_key   TEXT PRIMARY KEY,
            vendor_name TEXT NOT NULL,
            country     TEXT DEFAULT '',
            connector   TEXT DEFAULT '',
            data        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            hit_count   INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cache_expires
        ON osint_cache(expires_at)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS osint_rate_limits (
            rate_key    TEXT PRIMARY KEY,
            last_call   REAL NOT NULL
        )
    """)
    conn.commit()


def _get_db() -> sqlite3.Connection:
    """Get a SQLite connection with cache tables initialized."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    _init_cache_table(conn)
    return conn


class CachedEnrichment:
    """Wraps the OSINT enrichment pipeline with intelligent caching."""

    def __init__(self, db_path: str = None):
        if db_path:
            global DB_PATH
            DB_PATH = db_path

    def get_cached(self, vendor_name: str, country: str = "") -> Optional[dict]:
        """Return cached enrichment report if fresh, else None."""
        key = _cache_key(vendor_name, country)
        now = datetime.utcnow().isoformat()

        try:
            conn = _get_db()
            row = conn.execute(
                "SELECT data, hit_count FROM osint_cache "
                "WHERE cache_key = ? AND connector = '' AND expires_at > ?",
                (key, now)
            ).fetchone()

            if row:
                conn.execute(
                    "UPDATE osint_cache SET hit_count = ? WHERE cache_key = ? AND connector = ''",
                    (row[1] + 1, key)
                )
                conn.commit()
                conn.close()
                return json.loads(row[0])

            conn.close()
        except Exception:
            pass
        return None

    def set_cached(self, vendor_name: str, country: str, report: dict, ttl: int = DEFAULT_TTL):
        """Store enrichment report in cache."""
        key = _cache_key(vendor_name, country)
        now = datetime.utcnow()
        expires = datetime.utcfromtimestamp(now.timestamp() + ttl)

        try:
            conn = _get_db()
            conn.execute(
                "INSERT OR REPLACE INTO osint_cache "
                "(cache_key, vendor_name, country, connector, data, created_at, expires_at, hit_count) "
                "VALUES (?, ?, ?, '', ?, ?, ?, 0)",
                (key, vendor_name, country, json.dumps(report),
                 now.isoformat(), expires.isoformat())
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def check_rate_limit(self, vendor_name: str, country: str = "") -> bool:
        """Return True if we should throttle this request."""
        rate_key = _cache_key(vendor_name, country, "rate")
        now = time.time()

        try:
            conn = _get_db()
            row = conn.execute(
                "SELECT last_call FROM osint_rate_limits WHERE rate_key = ?",
                (rate_key,)
            ).fetchone()

            if row and (now - row[0]) < RATE_LIMIT_WINDOW:
                conn.close()
                return True  # Too soon

            conn.execute(
                "INSERT OR REPLACE INTO osint_rate_limits (rate_key, last_call) VALUES (?, ?)",
                (rate_key, now)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        return False

    def enrich(self, vendor_name: str, country: str = "", force: bool = False,
               **kwargs) -> dict:
        """
        Cached enrichment. Returns cached result if fresh, otherwise
        runs the full pipeline and caches the result.

        Args:
            vendor_name: Entity name
            country: ISO-2 country code
            force: Bypass cache and force fresh enrichment
            **kwargs: Passed to enrich_vendor()
        """
        # Check cache first (unless forced)
        if not force:
            cached = self.get_cached(vendor_name, country)
            if cached:
                cached["_cached"] = True
                cached["_cache_hit"] = True
                return cached

        # Rate limit check
        if self.check_rate_limit(vendor_name, country):
            # If rate limited, try to return stale cache
            stale = self.get_cached(vendor_name, country)
            if stale:
                stale["_cached"] = True
                stale["_stale"] = True
                return stale

        # Import here to avoid circular imports
        from osint.enrichment import enrich_vendor

        report = enrich_vendor(vendor_name, country=country, **kwargs)
        report["_cached"] = False

        # Cache the result
        self.set_cached(vendor_name, country, report)

        return report

    def invalidate(self, vendor_name: str, country: str = ""):
        """Remove cached data for a vendor."""
        key = _cache_key(vendor_name, country)
        try:
            conn = _get_db()
            conn.execute(
                "DELETE FROM osint_cache WHERE cache_key = ?", (key,)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def cleanup_expired(self):
        """Remove all expired cache entries."""
        now = datetime.utcnow().isoformat()
        try:
            conn = _get_db()
            result = conn.execute(
                "DELETE FROM osint_cache WHERE expires_at < ?", (now,)
            )
            conn.commit()
            deleted = result.rowcount
            conn.close()
            return deleted
        except Exception:
            return 0

    def get_stats(self) -> dict:
        """Return cache statistics."""
        try:
            conn = _get_db()
            total = conn.execute("SELECT COUNT(*) FROM osint_cache").fetchone()[0]
            now = datetime.utcnow().isoformat()
            fresh = conn.execute(
                "SELECT COUNT(*) FROM osint_cache WHERE expires_at > ?", (now,)
            ).fetchone()[0]
            total_hits = conn.execute(
                "SELECT COALESCE(SUM(hit_count), 0) FROM osint_cache"
            ).fetchone()[0]
            conn.close()

            return {
                "total_entries": total,
                "fresh_entries": fresh,
                "expired_entries": total - fresh,
                "total_cache_hits": total_hits,
            }
        except Exception:
            return {"total_entries": 0, "fresh_entries": 0,
                    "expired_entries": 0, "total_cache_hits": 0}


# Module-level singleton
_enricher = None

def get_enricher() -> CachedEnrichment:
    global _enricher
    if _enricher is None:
        _enricher = CachedEnrichment()
    return _enricher
