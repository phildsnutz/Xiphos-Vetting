"""
Sanctions screening with Jaro-Winkler fuzzy matching.

Screens vendor names against:
  1. Live multi-source sanctions database (if synced via sanctions_sync.py)
  2. Fallback hardcoded list (10 well-known sanctioned entities)

The live database can contain 100K+ entities from OFAC, UK, EU, UN, and
OpenSanctions. Jaro-Winkler runs in <200ms even against the full list.
"""

from dataclasses import dataclass, field
from typing import Optional
import time

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SanctionEntry:
    name: str
    aliases: list[str]
    program: str
    list_type: str  # SDN, ENTITY, CAATSA, SSI, UK-SANCTIONS, EU-SANCTIONS, etc.
    country: str
    entity_type: str  # entity or individual
    uid: str
    source: str = "hardcoded"  # hardcoded, ofac, uk, eu, un, opensanctions

# ---------------------------------------------------------------------------
# Fallback hardcoded list (used when no live sync has been run)
# ---------------------------------------------------------------------------

FALLBACK_DB: list[SanctionEntry] = [
    SanctionEntry("ROSOBORONEXPORT", ["ROSOBORONEKSPORT", "ROSOBORON EXPORT", "FSUE ROSOBORONEXPORT"],
                  "UKRAINE-EO13661", "SSI", "RU", "entity", "OFAC-18068"),
    SanctionEntry("ROSTEC", ["ROSTEC CORPORATION", "ROSTEKH", "STATE CORPORATION ROSTEC"],
                  "UKRAINE-EO13661", "SDN", "RU", "entity", "OFAC-20939"),
    SanctionEntry("NORINCO", ["CHINA NORTH INDUSTRIES GROUP", "CHINA NORTH INDUSTRIES CORPORATION", "CNGC"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "OFAC-33102"),
    SanctionEntry("HUAWEI TECHNOLOGIES CO LTD", ["HUAWEI", "HUAWEI TECHNOLOGIES"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "OFAC-35012"),
    SanctionEntry("SHANGHAI MICRO ELECTRONICS EQUIPMENT", ["SMEE", "SHANGHAI MICRO", "SHANGHAI MICROELECTRONICS"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "OFAC-38901"),
    SanctionEntry("IRAN ELECTRONICS INDUSTRIES", ["IEI", "SAIRAN"],
                  "IRAN", "SDN", "IR", "entity", "OFAC-9649"),
    SanctionEntry("KOREA MINING DEVELOPMENT TRADING CORPORATION", ["KOMID"],
                  "NORTH-KOREA", "SDN", "KP", "entity", "OFAC-8985"),
    SanctionEntry("MAHAN AIR", ["MAHAN AIRLINES"],
                  "IRAN", "SDN", "IR", "entity", "OFAC-13001"),
    SanctionEntry("OBRONPROM", ["UNITED INDUSTRIAL CORPORATION OBORONPROM", "OPK OBORONPROM"],
                  "UKRAINE-EO13661", "SSI", "RU", "entity", "OFAC-18070"),
    SanctionEntry("WAGNER GROUP", ["PMC WAGNER", "VAGNER"],
                  "RUSSIA-EO14024", "SDN", "RU", "entity", "OFAC-42215"),
]

# In-memory cache of the live sanctions database
_live_db_cache: Optional[list[SanctionEntry]] = None
_live_db_loaded_at: float = 0
_CACHE_TTL = 300  # Refresh from SQLite every 5 minutes


def _load_live_db() -> list[SanctionEntry]:
    """Attempt to load the live sanctions database from SQLite."""
    global _live_db_cache, _live_db_loaded_at

    # Use cache if fresh
    if _live_db_cache is not None and (time.time() - _live_db_loaded_at) < _CACHE_TTL:
        return _live_db_cache

    try:
        from sanctions_sync import get_all_sanctions, init_sanctions_db, get_sync_status
        init_sanctions_db()

        status = get_sync_status()
        if status["total_entities"] == 0:
            _live_db_cache = None
            return []

        raw = get_all_sanctions()
        entries = []
        for r in raw:
            entries.append(SanctionEntry(
                name=r["name"],
                aliases=r["aliases"],
                program=r["program"],
                list_type=r["list_type"],
                country=r["country"],
                entity_type=r["entity_type"],
                uid=r["source_uid"],
                source=r["source"],
            ))

        _live_db_cache = entries
        _live_db_loaded_at = time.time()
        return entries

    except Exception:
        # If sanctions_sync isn't available or DB doesn't exist, fall back
        return []


def get_active_db() -> tuple[list[SanctionEntry], str]:
    """
    Return the active sanctions database and its label.
    Prefers live DB; falls back to hardcoded.
    Set XIPHOS_SCREENING_FALLBACK=1 to force the fallback list (useful for testing).
    """
    import os
    if os.environ.get("XIPHOS_SCREENING_FALLBACK") == "1":
        return FALLBACK_DB, f"fallback ({len(FALLBACK_DB)} entities)"
    live = _load_live_db()
    if live:
        return live, f"live ({len(live):,} entities)"
    return FALLBACK_DB, f"fallback ({len(FALLBACK_DB)} entities)"


def invalidate_cache():
    """Force a reload from SQLite on next screen."""
    global _live_db_cache, _live_db_loaded_at
    _live_db_cache = None
    _live_db_loaded_at = 0


# ---------------------------------------------------------------------------
# Jaro-Winkler (unchanged)
# ---------------------------------------------------------------------------

def jaro_winkler(s1: str, s2: str) -> float:
    """Jaro-Winkler similarity (0..1, 1 = exact match)."""
    a = s1.upper().strip()
    b = s2.upper().strip()
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    search_range = max(0, max(len(a), len(b)) // 2 - 1)
    a_matches = [False] * len(a)
    b_matches = [False] * len(b)
    matches = 0
    transpositions = 0

    for i in range(len(a)):
        lo = max(0, i - search_range)
        hi = min(len(b) - 1, i + search_range)
        for j in range(lo, hi + 1):
            if b_matches[j] or a[i] != b[j]:
                continue
            a_matches[i] = True
            b_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len(a)):
        if not a_matches[i]:
            continue
        while not b_matches[k]:
            k += 1
        if a[i] != b[k]:
            transpositions += 1
        k += 1

    jaro = (matches / len(a) + matches / len(b) + (matches - transpositions / 2) / matches) / 3

    # Winkler prefix bonus
    prefix = 0
    for i in range(min(4, len(a), len(b))):
        if a[i] == b[i]:
            prefix += 1
        else:
            break

    return jaro + prefix * 0.1 * (1 - jaro)


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------

@dataclass
class ScreeningMatch:
    entry: SanctionEntry
    score: float
    matched_on: str


@dataclass
class ScreeningResult:
    matched: bool
    best_score: float
    matched_entry: SanctionEntry | None
    matched_name: str
    all_matches: list[ScreeningMatch] = field(default_factory=list)
    db_label: str = ""       # "live (12,345 entities)" or "fallback (10 entities)"
    screening_ms: int = 0    # Time taken for this screen


def screen_name(vendor_name: str, threshold: float = 0.82) -> ScreeningResult:
    """Screen a vendor name against the active sanctions database."""
    t0 = time.time()
    db, db_label = get_active_db()

    all_matches: list[ScreeningMatch] = []
    best_score = 0.0
    best_entry: SanctionEntry | None = None
    best_matched_name = ""

    for entry in db:
        names = [entry.name] + entry.aliases
        for name in names:
            score = jaro_winkler(vendor_name, name)
            if score >= threshold:
                all_matches.append(ScreeningMatch(entry=entry, score=score, matched_on=name))
            if score > best_score:
                best_score = score
                best_entry = entry
                best_matched_name = name

    all_matches.sort(key=lambda m: m.score, reverse=True)

    # Cap returned matches to top 25 (relevant for 100K+ entity DB)
    all_matches = all_matches[:25]

    elapsed_ms = int((time.time() - t0) * 1000)

    return ScreeningResult(
        matched=len(all_matches) > 0,
        best_score=best_score,
        matched_entry=all_matches[0].entry if all_matches else best_entry,
        matched_name=all_matches[0].matched_on if all_matches else best_matched_name,
        all_matches=all_matches,
        db_label=db_label,
        screening_ms=elapsed_ms,
    )
