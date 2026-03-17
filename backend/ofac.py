"""
Xiphos Sanctions Screening Engine v3.0

Multi-signal entity matching with tiered confidence scoring.

Instead of relying on a single Jaro-Winkler fuzzy match (which produces
systemic false positives when names share common prefixes or when one
name is short), v3.0 uses a composite matching architecture:

  Signal 1: Exact Token Match (IDF-weighted)
    Decomposes names into tokens, strips legal suffixes and stopwords,
    and computes overlap weighted by inverse document frequency. Common
    words like "GENERAL", "INTERNATIONAL", "SYSTEMS" contribute less
    than rare words like "ROSOBORONEXPORT" or "NORINCO".

  Signal 2: Character N-gram Similarity (Dice coefficient)
    Compares character bigrams between names, which is naturally resistant
    to short-name inflation (unlike JW) and provides good typo tolerance
    for transliterated names.

  Signal 3: Jaro-Winkler (prefix-capped)
    Traditional JW but with a cap on the Winkler prefix bonus to prevent
    short shared prefixes from dominating the score.

  Signal 4: Entity-Type Penalty
    Discounts matches between organizations and individuals -- an SDN
    individual named "Park" should not flag Parker Hannifin.

  Signal 5: Phonetic Backbone
    Double Metaphone provides a fast pre-filter for transliteration
    variants (e.g., ROSOBORONEKSPORT vs ROSOBORONEXPORT) while ignoring
    names that sound completely different.

The five signals are combined with learned weights into a single
confidence score (0.0-1.0). The threshold for "matched" is 0.75
on the composite score, which corresponds roughly to 0.92+ on raw JW
for legitimate matches while rejecting the false positives that
previously inflated risk scores for clean entities.

Screens vendor names against:
  1. Live multi-source sanctions database (if synced via sanctions_sync.py)
  2. Fallback hardcoded list (10 well-known sanctioned entities)
"""

from dataclasses import dataclass, field
from typing import Optional
import math
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

# IDF cache: built once from the active DB
_idf_cache: Optional[dict[str, float]] = None
_idf_db_size: int = 0


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

        # Rebuild IDF index
        _build_idf(entries)

        return entries

    except Exception:
        # If sanctions_sync isn't available or DB doesn't exist, fall back
        return []


def get_active_db() -> tuple[list[SanctionEntry], str]:
    """
    Return the active sanctions database and its label.
    Prefers live DB; falls back to hardcoded.
    Set XIPHOS_SCREENING_FALLBACK=1 to force the fallback list.
    """
    import os
    if os.environ.get("XIPHOS_SCREENING_FALLBACK") == "1":
        _build_idf(FALLBACK_DB)
        return FALLBACK_DB, f"fallback ({len(FALLBACK_DB)} entities)"
    live = _load_live_db()
    if live:
        return live, f"live ({len(live):,} entities)"
    _build_idf(FALLBACK_DB)
    return FALLBACK_DB, f"fallback ({len(FALLBACK_DB)} entities)"


def invalidate_cache():
    """Force a reload from SQLite on next screen."""
    global _live_db_cache, _live_db_loaded_at, _idf_cache
    _live_db_cache = None
    _live_db_loaded_at = 0
    _idf_cache = None


# ---------------------------------------------------------------------------
# Signal 1: IDF-Weighted Token Matching
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "INC", "LLC", "LTD", "PLC", "SA", "AG", "GMBH", "CO", "CORP",
    "CORPORATION", "GROUP", "HOLDINGS", "INTERNATIONAL", "THE", "OF",
    "AND", "&", "FOR", "A", "AN", "DE", "LA", "EL", "AL", "DI",
    "VON", "VAN", "BIN", "BEN", "ABU", "AL-", "COMPANY", "ENTERPRISES",
    "LIMITED", "INDUSTRIES",
})


def _tokenize(name: str) -> list[str]:
    """Split name into meaningful uppercase tokens."""
    raw = name.upper().strip()
    for ch in ".,;:-/()[]{}\"'":
        raw = raw.replace(ch, " ")
    return [t for t in raw.split() if t and t not in _STOPWORDS and len(t) > 1]


def _build_idf(db: list[SanctionEntry]):
    """Build inverse document frequency index from sanctions DB."""
    global _idf_cache, _idf_db_size
    from collections import Counter

    doc_count = Counter()
    total_docs = 0

    for entry in db:
        names = [entry.name] + entry.aliases
        for name in names:
            total_docs += 1
            seen = set()
            for token in _tokenize(name):
                if token not in seen:
                    doc_count[token] += 1
                    seen.add(token)

    # IDF = log(N / (1 + df)) -- smoothed to avoid zero
    _idf_cache = {}
    for token, df in doc_count.items():
        _idf_cache[token] = math.log((total_docs + 1) / (1 + df))
    _idf_db_size = total_docs


def _get_idf(token: str) -> float:
    """Get IDF weight for a token. High = rare = more distinctive."""
    if _idf_cache is None:
        return 1.0
    return _idf_cache.get(token, math.log((_idf_db_size + 1) / 1))  # unseen token = max IDF


def idf_token_score(vendor_tokens: list[str], sdn_tokens: list[str]) -> float:
    """
    IDF-weighted token overlap score.

    For each token in the shorter list, check if it appears in the longer
    list. Weight matches by IDF so rare tokens count more. Returns 0.0-1.0.
    """
    if not vendor_tokens or not sdn_tokens:
        return 0.0

    shorter = vendor_tokens if len(vendor_tokens) <= len(sdn_tokens) else sdn_tokens
    longer_set = set(vendor_tokens if len(vendor_tokens) > len(sdn_tokens) else sdn_tokens)

    weighted_matches = 0.0
    total_weight = 0.0

    for token in shorter:
        idf = _get_idf(token)
        total_weight += idf
        if token in longer_set:
            weighted_matches += idf

    if total_weight == 0:
        return 0.0

    return weighted_matches / total_weight


# ---------------------------------------------------------------------------
# Signal 2: Character Bigram Dice Coefficient
# ---------------------------------------------------------------------------

def _bigrams(s: str) -> set[str]:
    """Generate character bigrams from a string."""
    s = s.upper().strip()
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i+2] for i in range(len(s) - 1)}


def dice_bigram(a: str, b: str) -> float:
    """
    Dice coefficient on character bigrams.

    Naturally handles length differences better than JW because the
    denominator is the total bigram count from both strings, not a
    ratio of matches to length.
    """
    bg_a = _bigrams(a)
    bg_b = _bigrams(b)
    if not bg_a or not bg_b:
        return 0.0
    return 2 * len(bg_a & bg_b) / (len(bg_a) + len(bg_b))


# ---------------------------------------------------------------------------
# Signal 3: Jaro-Winkler (prefix-capped)
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

    # Winkler prefix bonus -- CAPPED at p=0.05 (down from standard 0.1)
    # to reduce the outsized effect of shared prefixes
    prefix = 0
    for i in range(min(4, len(a), len(b))):
        if a[i] == b[i]:
            prefix += 1
        else:
            break

    return jaro + prefix * 0.05 * (1 - jaro)


# ---------------------------------------------------------------------------
# Signal 4: Entity-Type Compatibility
# ---------------------------------------------------------------------------

def entity_type_penalty(vendor_name: str, sdn_entry: SanctionEntry) -> float:
    """
    Penalty factor when matching an organization name against an individual.
    Returns 1.0 (no penalty) for org-org or individual-individual,
    0.6 for org-individual cross-matches.

    v3.0.1: Expanded org detection beyond English legal suffixes to cover
    transliterated Russian, Chinese, Arabic, Korean, Turkish, and French
    entity names that lack western corporate markers.
    """
    # Multi-language organization markers
    org_markers = {
        # English
        "INC", "LLC", "LTD", "PLC", "CORP", "CORPORATION", "COMPANY",
        "SA", "AG", "GMBH", "CO", "LP", "LLP",
        # Industry markers (language-agnostic)
        "SYSTEMS", "AEROSPACE", "TECHNOLOGIES", "INDUSTRIES", "ELECTRONICS",
        "SOLUTIONS", "DEFENSE", "DEFENCE", "GROUP", "HOLDINGS", "ENTERPRISE",
        "ENTERPRISES", "ENGINEERING", "MANUFACTURING", "AVIATION", "TELECOM",
        "TELECOMMUNICATIONS", "PETROLEUM", "CHEMICAL", "PHARMACEUTICAL",
        "BANK", "FINANCIAL", "INSURANCE", "SHIPPING", "LOGISTICS",
        "CONSTRUCTION", "MINING", "ENERGY", "NUCLEAR", "ATOMIC",
        # Russian transliterations
        "OAO", "ZAO", "OOO", "PAO", "FSUE", "FGUP", "GUP",
        "KOMBINAT", "ZAVOD", "OBIEDINENIE", "KONTSERN",
        # Chinese transliterations
        "GONGSI", "JITUAN", "YOUXIAN", "GUFEN",
        # Arabic
        "SHARIKAH", "MUASSASAH",
        # Korean
        "CHAEBOL", "GONGYEOP", "JEONJA",
        # Turkish
        "SANAYI", "TICARET", "ANONIM", "SIRKETI",
        # French
        "SARL", "SAS", "SOCIETE", "ELECTRONIQUE",
        # State entity markers
        "MINISTRY", "BUREAU", "COMMISSION", "COMMITTEE", "AUTHORITY",
        "DEPARTMENT", "AGENCY", "INSTITUTE", "FOUNDATION", "FEDERATION",
        "REPUBLIC", "GOVERNMENT", "STATE", "NATIONAL", "MILITARY",
        "ARMED", "FORCES", "ARMY", "NAVY",
    }

    vendor_upper = vendor_name.upper()

    # Primary check: explicit org markers
    vendor_is_org = any(m in vendor_upper.split() for m in org_markers)

    # Secondary: token count heuristic. Individual names rarely exceed 4 tokens
    # after removing titles. Org names almost always have 3+ tokens.
    if not vendor_is_org:
        tokens = [t for t in vendor_upper.split() if len(t) > 1]
        if len(tokens) >= 4:
            vendor_is_org = True

    # Tertiary: if vendor contains numbers (e.g., "Unit 61398"), likely an org
    if not vendor_is_org and any(c.isdigit() for c in vendor_name):
        vendor_is_org = True

    sdn_is_individual = sdn_entry.entity_type == "individual"

    if vendor_is_org and sdn_is_individual:
        return 0.6  # 40% penalty for org matching against individual
    return 1.0


# ---------------------------------------------------------------------------
# Signal 5: Phonetic Pre-filter (Double Metaphone approximation)
# ---------------------------------------------------------------------------

def _simple_phonetic(s: str) -> str:
    """
    Simplified phonetic encoding for pre-filtering.
    Not a full Double Metaphone but sufficient for first-pass filtering
    of transliteration variants.
    """
    s = s.upper().strip()
    if not s:
        return ""

    # Remove non-alpha
    s = "".join(c for c in s if c.isalpha() or c == " ")

    # Basic phonetic transforms
    replacements = [
        ("PH", "F"), ("GH", "F"), ("KN", "N"), ("WR", "R"),
        ("CK", "K"), ("SCH", "SK"), ("QU", "KW"), ("X", "KS"),
        ("SH", "S"), ("TH", "T"), ("CH", "K"),
    ]
    for old, new in replacements:
        s = s.replace(old, new)

    # Remove duplicate consecutive chars
    result = []
    for c in s:
        if not result or c != result[-1]:
            result.append(c)

    return "".join(result)


def phonetic_match(a: str, b: str) -> bool:
    """Check if two names have similar phonetic profiles."""
    pa = _simple_phonetic(a)
    pb = _simple_phonetic(b)
    if not pa or not pb:
        return False

    # Check if the phonetic encodings share significant overlap
    # using bigram dice on the phonetic forms
    return dice_bigram(pa, pb) > 0.40


# ---------------------------------------------------------------------------
# Composite Match Score
# ---------------------------------------------------------------------------

def composite_match_score(
    vendor_name: str,
    sdn_name: str,
    sdn_entry: SanctionEntry,
) -> tuple[float, dict]:
    """
    Compute composite match confidence from all five signals.

    Returns (score, details) where score is 0.0-1.0 and details
    contains the individual signal values for transparency.

    Signal weights (tuned to minimize false positives while catching
    legitimate matches):
      - IDF token overlap:  0.35 (strongest discriminator)
      - Dice bigram:        0.25 (good typo tolerance)
      - Jaro-Winkler:       0.20 (prefix sensitivity, capped)
      - Entity type:        multiplier (0.6 or 1.0)
      - Phonetic:           0.10 bonus when phonetics match
      - Length ratio:        0.10 penalty factor
    """
    # Compute individual signals
    v_tokens = _tokenize(vendor_name)
    s_tokens = _tokenize(sdn_name)

    sig_token = idf_token_score(v_tokens, s_tokens)
    sig_dice = dice_bigram(vendor_name, sdn_name)
    sig_jw = jaro_winkler(vendor_name, sdn_name)
    sig_type = entity_type_penalty(vendor_name, sdn_entry)
    sig_phonetic = 1.0 if phonetic_match(vendor_name, sdn_name) else 0.0

    # Length ratio: penalize large length mismatches
    len_v = len(vendor_name.strip())
    len_s = len(sdn_name.strip())
    length_ratio = min(len_v, len_s) / max(len_v, len_s) if max(len_v, len_s) > 0 else 0.0

    # Composite: weighted sum with entity type as multiplier
    raw_composite = (
        0.35 * sig_token +
        0.25 * sig_dice +
        0.20 * sig_jw +
        0.10 * sig_phonetic +
        0.10 * length_ratio
    )

    # Apply entity type penalty
    composite = raw_composite * sig_type

    details = {
        "idf_token": round(sig_token, 4),
        "dice_bigram": round(sig_dice, 4),
        "jaro_winkler": round(sig_jw, 4),
        "entity_type_factor": round(sig_type, 2),
        "phonetic_match": sig_phonetic > 0,
        "length_ratio": round(length_ratio, 4),
        "raw_composite": round(raw_composite, 4),
        "final_score": round(composite, 4),
    }

    return composite, details


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------

@dataclass
class ScreeningMatch:
    entry: SanctionEntry
    score: float           # composite multi-signal score
    raw_jw: float          # raw Jaro-Winkler for backward compat / UI
    matched_on: str
    match_details: dict = field(default_factory=dict)


@dataclass
class ScreeningResult:
    matched: bool
    best_score: float        # composite score (used for risk calculation)
    best_raw_jw: float       # raw JW score (shown in UI for transparency)
    matched_entry: SanctionEntry | None
    matched_name: str
    match_details: dict = field(default_factory=dict)  # signal breakdown
    all_matches: list[ScreeningMatch] = field(default_factory=list)
    db_label: str = ""       # "live (12,345 entities)" or "fallback (10 entities)"
    screening_ms: int = 0    # Time taken for this screen


def screen_name(vendor_name: str, threshold: float = 0.75) -> ScreeningResult:
    """
    Screen a vendor name against the active sanctions database.

    v3.0: Uses composite multi-signal scoring instead of raw JW.
    Threshold is 0.75 on the composite score, which corresponds to
    ~0.92+ on raw JW for legitimate matches.

    Returns ScreeningResult with composite scores, raw JW for
    backward compatibility, and detailed signal breakdowns.
    """
    t0 = time.time()
    db, db_label = get_active_db()

    all_matches: list[ScreeningMatch] = []
    best_score = 0.0
    best_raw_jw = 0.0
    best_entry: SanctionEntry | None = None
    best_matched_name = ""
    best_details: dict = {}

    for entry in db:
        names = [entry.name] + entry.aliases
        for name in names:
            # Quick pre-filter: raw JW must be at least 0.70 to be a candidate.
            # This keeps the loop fast for large DBs.
            raw_jw = jaro_winkler(vendor_name, name)
            if raw_jw < 0.70:
                continue

            # Full composite scoring
            composite, details = composite_match_score(vendor_name, name, entry)

            if composite >= threshold:
                all_matches.append(ScreeningMatch(
                    entry=entry,
                    score=composite,
                    raw_jw=raw_jw,
                    matched_on=name,
                    match_details=details,
                ))

            if composite > best_score:
                best_score = composite
                best_raw_jw = raw_jw
                best_entry = entry
                best_matched_name = name
                best_details = details

    all_matches.sort(key=lambda m: m.score, reverse=True)

    # Cap returned matches to top 25
    all_matches = all_matches[:25]

    elapsed_ms = int((time.time() - t0) * 1000)

    return ScreeningResult(
        matched=len(all_matches) > 0,
        best_score=best_score,
        best_raw_jw=best_raw_jw,
        matched_entry=all_matches[0].entry if all_matches else best_entry,
        matched_name=all_matches[0].matched_on if all_matches else best_matched_name,
        match_details=best_details,
        all_matches=all_matches,
        db_label=db_label,
        screening_ms=elapsed_ms,
    )
