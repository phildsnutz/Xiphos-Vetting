"""
Xiphos Sanctions Screening Engine v4.0

Multi-signal entity matching with tiered confidence scoring and
dual-source screening architecture.

v4.0 changes (Sprint 7+):
  - Dual-source screening: ALWAYS merges live DB + fallback overlay.
    The fallback DB contains hardcoded Section 889 / NDAA 1260H entities
    that may not exist in live SDN data under the same name format.
    Best match from either source wins.
  - Minimum distinctive tokens gate: Rejects matches where fewer than
    2 distinctive (non-stopword, non-suffix) tokens overlap. Eliminates
    false positives like "General Dynamics" matching "Fuel and Oil
    Dynamics FZE" (only 1 distinctive shared token: DYNAMICS).
  - Country metadata confirmation: When vendor country is known and
    differs from SDN entry country, applies a confidence discount.
  - Expanded stopword coverage for common business/industry terms.

Composite matching architecture (6 signals):

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

  Signal 6: Asymmetric Token Containment
    Catches short vendor names (DJI, ZTE) that are strict subsets of
    long SDN entries with city prefixes and legal suffixes.

The six signals are combined with learned weights into a single
confidence score (0.0-1.0). The threshold for "matched" is 0.75
on the composite score, which corresponds roughly to 0.92+ on raw JW
for legitimate matches while rejecting the false positives that
previously inflated risk scores for clean entities.

Screens vendor names against:
  1. Live multi-source sanctions database (if synced via sanctions_sync.py)
  2. Fallback hardcoded watchlist (27 Section 889/1260H/SDN entities)
  3. Both sources merged when live DB is available (best match wins)
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
    # --- Original 10 entries (v1.0) ---
    SanctionEntry("ROSOBORONEXPORT", ["ROSOBORONEKSPORT", "ROSOBORON EXPORT", "FSUE ROSOBORONEXPORT"],
                  "UKRAINE-EO13661", "SSI", "RU", "entity", "XIPHOS-FB-18068"),
    SanctionEntry("ROSTEC", ["ROSTEC CORPORATION", "ROSTEKH", "STATE CORPORATION ROSTEC"],
                  "UKRAINE-EO13661", "SDN", "RU", "entity", "XIPHOS-FB-20939"),
    SanctionEntry("NORINCO", ["CHINA NORTH INDUSTRIES GROUP", "CHINA NORTH INDUSTRIES CORPORATION", "CNGC"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-33102"),
    SanctionEntry("HUAWEI TECHNOLOGIES CO LTD", ["HUAWEI", "HUAWEI TECHNOLOGIES"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-35012"),
    SanctionEntry("SHANGHAI MICRO ELECTRONICS EQUIPMENT", ["SMEE", "SHANGHAI MICRO", "SHANGHAI MICROELECTRONICS"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-38901"),
    SanctionEntry("IRAN ELECTRONICS INDUSTRIES", ["IEI", "SAIRAN"],
                  "IRAN", "SDN", "IR", "entity", "XIPHOS-FB-9649"),
    SanctionEntry("KOREA MINING DEVELOPMENT TRADING CORPORATION", ["KOMID"],
                  "NORTH-KOREA", "SDN", "KP", "entity", "XIPHOS-FB-8985"),
    SanctionEntry("MAHAN AIR", ["MAHAN AIRLINES"],
                  "IRAN", "SDN", "IR", "entity", "XIPHOS-FB-13001"),
    SanctionEntry("OBRONPROM", ["UNITED INDUSTRIAL CORPORATION OBORONPROM", "OPK OBORONPROM"],
                  "UKRAINE-EO13661", "SSI", "RU", "entity", "XIPHOS-FB-18070"),
    SanctionEntry("WAGNER GROUP", ["PMC WAGNER", "VAGNER"],
                  "RUSSIA-EO14024", "SDN", "RU", "entity", "XIPHOS-FB-42215"),

    # --- Section 889 entities (v3.1 -- Tier D coverage) ---
    SanctionEntry("ZTE CORPORATION", ["ZTE", "ZTE CORP", "ZTE MICROELECTRONICS", "ZHONGXING TELECOMMUNICATION"],
                  "CHINA-NDAA-889", "ENTITY", "CN", "entity", "XIPHOS-FB-889-ZTE"),
    SanctionEntry("HYTERA COMMUNICATIONS", ["HYTERA", "HYTERA COMMUNICATIONS CORP", "HYTERA MOBILFUNK"],
                  "CHINA-NDAA-889", "ENTITY", "CN", "entity", "XIPHOS-FB-889-HYTERA"),
    SanctionEntry("HIKVISION", ["HIKVISION DIGITAL TECHNOLOGY", "HANGZHOU HIKVISION",
                                "HIKVISION INTERNATIONAL", "EZVIZ", "HK HIKVISION"],
                  "CHINA-NDAA-889", "ENTITY", "CN", "entity", "XIPHOS-FB-889-HIKVISION"),
    SanctionEntry("DAHUA TECHNOLOGY", ["DAHUA", "HANGZHOU DAHUA", "DAHUA SECURITY",
                                       "ZHEJIANG DAHUA", "IMOU LIFE"],
                  "CHINA-NDAA-889", "ENTITY", "CN", "entity", "XIPHOS-FB-889-DAHUA"),

    # --- NDAA 1260H Chinese Military Companies (v3.1) ---
    SanctionEntry("KASPERSKY LAB", ["KASPERSKY", "AO KASPERSKY LAB", "KASPERSKY LABS ZAO"],
                  "RUSSIA-EO14071", "ENTITY", "RU", "entity", "XIPHOS-FB-KASPERSKY"),
    SanctionEntry("DJI", ["SZ DJI TECHNOLOGY CO LTD", "DA JIANG INNOVATIONS",
                          "DJI TECHNOLOGY", "DJI INNOVATION"],
                  "CHINA-MILITARY-ENTITIES", "ENTITY", "CN", "entity", "XIPHOS-FB-1260H-DJI"),
    SanctionEntry("AVIC", ["AVIATION INDUSTRY CORPORATION OF CHINA", "AVIC INTERNATIONAL",
                           "AVIC AEROSPACE", "AVIC SYSTEMS"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-1260H-AVIC"),
    SanctionEntry("CHINA AEROSPACE SCIENCE AND TECHNOLOGY", ["CASC", "CHINA AEROSPACE SCIENCE", "CAST"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-1260H-CASC"),
    SanctionEntry("CHINA AEROSPACE SCIENCE AND INDUSTRY", ["CASIC"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-1260H-CASIC"),
    SanctionEntry("CHINA ELECTRONICS TECHNOLOGY GROUP", ["CETC", "CEC", "CHINA ELECTRONICS CORPORATION"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-1260H-CETC"),
    SanctionEntry("CHINA GENERAL NUCLEAR POWER", ["CGN", "CHINA GENERAL NUCLEAR", "CGN NUCLEAR"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-1260H-CGN"),
    SanctionEntry("CHINA NATIONAL NUCLEAR CORPORATION", ["CNNC"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-1260H-CNNC"),
    SanctionEntry("CHINA SHIPBUILDING INDUSTRY CORPORATION", ["CSIC"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-1260H-CSIC"),
    SanctionEntry("CHINA STATE SHIPBUILDING CORPORATION", ["CSSC"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-1260H-CSSC"),
    SanctionEntry("SEMICONDUCTOR MANUFACTURING INTERNATIONAL CORPORATION", ["SMIC"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-1260H-SMIC"),
    SanctionEntry("COMAC", ["COMMERCIAL AIRCRAFT CORPORATION OF CHINA"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-1260H-COMAC"),
    SanctionEntry("INSPUR GROUP", ["INSPUR", "INSPUR ELECTRONIC INFORMATION"],
                  "CHINA-EO13959", "ENTITY", "CN", "entity", "XIPHOS-FB-1260H-INSPUR"),
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

    v4.0 dual-source architecture:
      - When live DB is available, MERGE live + fallback entries.
        The fallback DB contains hardcoded Section 889/1260H entities
        whose names may not match reliably in the live SDN data (e.g.,
        ZTE Corporation appears as a different name format in OFAC SDN).
        Deduplication by UID prevents double-counting.
      - When only fallback is available, use fallback alone.
      - XIPHOS_SCREENING_FALLBACK=1 forces fallback-only mode
        (deterministic, useful for testing).
    """
    import os
    if os.environ.get("XIPHOS_SCREENING_FALLBACK") == "1":
        _build_idf(FALLBACK_DB)
        return FALLBACK_DB, f"fallback ({len(FALLBACK_DB)} entities)"
    live = _load_live_db()
    if live:
        # Merge: start with live, overlay fallback entries not already present
        live_uids = {e.uid for e in live}
        merged = list(live)
        overlay_count = 0
        for fb_entry in FALLBACK_DB:
            if fb_entry.uid not in live_uids:
                merged.append(fb_entry)
                overlay_count += 1
        _build_idf(merged)
        return merged, f"live+overlay ({len(live):,} live + {overlay_count} overlay)"
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

def _load_stopwords() -> frozenset:
    """
    Load stopwords from stopwords.json config file.

    Falls back to a minimal hardcoded set if the JSON file is missing.
    The JSON file is organized by category (legal_suffixes, russian_legal,
    chinese_geographic, defense_industry, business_descriptors,
    geographic_directional) for maintainability. All categories are
    merged into a single flat set at load time.
    """
    import json
    import os

    # Try loading from JSON config (same directory as this module)
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stopwords.json")
    try:
        with open(config_path) as f:
            data = json.load(f)
        words = set()
        for key, value in data.items():
            if isinstance(value, list):
                words.update(value)
        return frozenset(words)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Hardcoded fallback (minimal set to keep the engine functional)
    return frozenset({
        "INC", "LLC", "LTD", "PLC", "SA", "AG", "GMBH", "CO", "CORP",
        "CORPORATION", "GROUP", "HOLDINGS", "INTERNATIONAL", "THE", "OF",
        "AND", "&", "FOR", "COMPANY", "ENTERPRISES", "LIMITED", "INDUSTRIES",
        "TECHNOLOGIES", "TECHNOLOGY", "SYSTEMS", "SOLUTIONS", "SERVICES",
        "DIGITAL", "ELECTRONICS", "COMMUNICATIONS", "DEFENSE", "DEFENCE",
        "AEROSPACE", "ENGINEERING", "ADVANCED", "GLOBAL", "GENERAL",
        "NATIONAL", "STATE", "DYNAMICS", "MANUFACTURING", "TRADING",
    })


_STOPWORDS = _load_stopwords()


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
    IDF-weighted token overlap score with fuzzy fallback.

    For each token in the shorter list, check if it appears in the longer
    list. Weight matches by IDF so rare tokens count more. Returns 0.0-1.0.

    v5.4.1: When exact match fails, try JW >= 0.90 against each token in the
    longer set to catch singular/plural and minor transliteration variants
    (e.g. PETROLEO vs PETROLEOS, ALUMINIUM vs ALUMINUM).
    """
    if not vendor_tokens or not sdn_tokens:
        return 0.0

    shorter = vendor_tokens if len(vendor_tokens) <= len(sdn_tokens) else sdn_tokens
    longer = vendor_tokens if len(vendor_tokens) > len(sdn_tokens) else sdn_tokens
    longer_set = set(longer)

    weighted_matches = 0.0
    total_weight = 0.0

    for token in shorter:
        idf = _get_idf(token)
        total_weight += idf
        if token in longer_set:
            weighted_matches += idf
        else:
            # Fuzzy fallback: JW >= 0.90 on individual tokens
            for lt in longer:
                if jaro_winkler(token, lt) >= 0.90:
                    weighted_matches += idf * 0.85  # slight discount for fuzzy match
                    break

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

    # Tertiary: conjunction pattern ("X and Y", "X & Y") strongly indicates
    # a company name, not a person (e.g., "Johnson and Johnson", "Ernst & Young").
    if not vendor_is_org:
        if " AND " in vendor_upper or " & " in vendor_upper:
            vendor_is_org = True

    # Quaternary: if vendor contains numbers (e.g., "Unit 61398"), likely an org
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

def _token_containment(vendor_tokens: list[str], sdn_tokens: list[str]) -> float:
    """
    Signal 6: Asymmetric token containment.

    Checks whether ALL vendor tokens appear in the SDN token set.
    Returns 1.0 if the vendor name is fully "contained" in the SDN name
    at the token level, 0.0 if none match.

    This catches the DJI/Hikvision failure mode where a short vendor name
    (1-2 distinctive tokens) is a strict subset of a long SDN entry
    (5+ tokens with city prefixes and legal suffixes). Character-level
    metrics (JW, Dice) fail here due to length ratio, but at the token
    level the match is unambiguous.

    Minimum vendor token length of 3 chars to avoid false positives
    from 2-char tokens like "AI", "US", etc.
    """
    if not vendor_tokens or not sdn_tokens:
        return 0.0

    sdn_set = set(sdn_tokens)
    eligible = [t for t in vendor_tokens if len(t) >= 3]
    if not eligible:
        return 0.0

    matched = sum(1 for t in eligible if t in sdn_set)
    return matched / len(eligible)


def _count_distinctive_tokens(v_tokens: list[str], s_tokens: list[str]) -> int:
    """
    Count the number of distinctive tokens shared between two token lists.

    A token is "distinctive" if it has IDF weight above the median (i.e.,
    it's not a generic business term that survived stopword removal).
    Minimum token length of 3 to exclude abbreviations.

    Per ACAMS/Wolfsberg guidance, matches with fewer than 2 distinctive
    shared tokens are overwhelmingly false positives.
    """
    if not v_tokens or not s_tokens:
        return 0

    v_set = set(t for t in v_tokens if len(t) >= 3)
    s_set = set(t for t in s_tokens if len(t) >= 3)
    shared = v_set & s_set

    if not shared:
        return 0

    # A token is "distinctive" if its IDF is above the corpus median.
    # For small corpora, use 1.5 as a reasonable floor (log(N/df) > 1.5
    # means the token appears in fewer than ~22% of documents).
    idf_threshold = SCREENING_DISTINCTIVE_TOKEN_IDF_FLOOR
    distinctive = [t for t in shared if _get_idf(t) >= idf_threshold]

    return len(distinctive)


def composite_match_score(
    vendor_name: str,
    sdn_name: str,
    sdn_entry: SanctionEntry,
    vendor_country: str = "",
) -> tuple[float, dict]:
    """
    Compute composite match confidence from six signals with
    post-match validation gates.

    Returns (score, details) where score is 0.0-1.0 and details
    contains the individual signal values for transparency.

    Signal weights (v4.0):
      - IDF token overlap:     0.30
      - Dice bigram:           0.20
      - Jaro-Winkler:          0.15
      - Token containment:     0.15
      - Entity type:           multiplier (0.6 or 1.0)
      - Phonetic:              0.10 bonus when phonetics match
      - Length ratio:           0.10 penalty factor

    Post-match gates (v4.0):
      - Minimum distinctive tokens: <2 shared distinctive tokens = 50% penalty
      - Country mismatch: known vendor country != SDN country = 30% penalty
      - Single-token SDN guard: SDN has 1 token, vendor has 2+ = 50% penalty
    """
    # Compute individual signals
    v_tokens = _tokenize(vendor_name)
    s_tokens = _tokenize(sdn_name)

    sig_token = idf_token_score(v_tokens, s_tokens)
    sig_dice = dice_bigram(vendor_name, sdn_name)
    sig_jw = jaro_winkler(vendor_name, sdn_name)
    sig_type = entity_type_penalty(vendor_name, sdn_entry)
    sig_phonetic = 1.0 if phonetic_match(vendor_name, sdn_name) else 0.0
    sig_containment = _token_containment(v_tokens, s_tokens)

    # Length ratio: penalize large length mismatches
    len_v = len(vendor_name.strip())
    len_s = len(sdn_name.strip())
    length_ratio = min(len_v, len_s) / max(len_v, len_s) if max(len_v, len_s) > 0 else 0.0

    # Composite: weighted sum with entity type as multiplier
    raw_composite = (
        0.30 * sig_token +
        0.20 * sig_dice +
        0.15 * sig_jw +
        0.15 * sig_containment +
        0.10 * sig_phonetic +
        0.10 * length_ratio
    )

    # Apply entity type penalty
    composite = raw_composite * sig_type

    # --- Post-match validation gates (v4.0) ---

    # Gate 1: Minimum distinctive tokens (ACAMS/Wolfsberg best practice)
    # Matches with <2 distinctive shared tokens are overwhelmingly
    # false positives. This kills "General Dynamics" matching
    # "Fuel and Oil Dynamics FZE" (only 1 shared distinctive token).
    #
    # Exceptions:
    #   - Token containment >= 0.95 (short name fully in long SDN)
    #   - BOTH token lists are empty/all-stopwords AND JW >= 0.88.
    #     This handles the edge case where a hypothetically sanctioned
    #     entity has a purely generic name ("General Dynamics") that
    #     reduces entirely to stopwords. In that case, character-level
    #     signals (JW, Dice) are the only reliable discriminator.
    distinctive_count = _count_distinctive_tokens(v_tokens, s_tokens)
    both_empty = (len(v_tokens) == 0 and len(s_tokens) == 0)
    if distinctive_count < SCREENING_DISTINCTIVE_TOKEN_MIN and sig_containment < SCREENING_CONTAINMENT_BYPASS_RATIO:
        if both_empty and sig_jw >= SCREENING_ALL_STOPWORD_JW_BYPASS:
            pass  # Skip penalty: rely on JW/Dice for all-stopword names
        else:
            composite *= SCREENING_DISTINCTIVE_TOKEN_PENALTY_MULTIPLIER

    # Gate 2: Country metadata confirmation (Wolfsberg guidance)
    # When vendor country is known and SDN entry has a country,
    # mismatches indicate likely false positive. Apply discount.
    country_mismatch = False
    if vendor_country and sdn_entry.country:
        vc = vendor_country.upper().strip()
        sc = sdn_entry.country.upper().strip()
        if vc and sc and vc != sc:
            # Allied countries matching adversary-nation SDN entries
            # is a stronger false-positive signal than intra-region mismatch
            country_mismatch = True
            composite *= SCREENING_COUNTRY_MISMATCH_PENALTY_MULTIPLIER

    # Gate 3: Single-token SDN guard (existing)
    # SDN "JOHNSON" matching "Johnson and Johnson" is almost always
    # a false positive.
    if len(s_tokens) <= 1 and len(v_tokens) >= 2:
        composite *= SCREENING_SINGLE_TOKEN_SDN_PENALTY_MULTIPLIER

    details = {
        "idf_token": round(sig_token, 4),
        "dice_bigram": round(sig_dice, 4),
        "jaro_winkler": round(sig_jw, 4),
        "token_containment": round(sig_containment, 4),
        "entity_type_factor": round(sig_type, 2),
        "phonetic_match": sig_phonetic > 0,
        "length_ratio": round(length_ratio, 4),
        "raw_composite": round(raw_composite, 4),
        "distinctive_tokens": distinctive_count,
        "country_mismatch": country_mismatch,
        "final_score": round(composite, 4),
    }

    return composite, details


# ---------------------------------------------------------------------------
# Screening policy metadata
# ---------------------------------------------------------------------------

SCREENING_COMPOSITE_THRESHOLD_DEFAULT = 0.75
SCREENING_PREFILTER_JW_FLOOR = 0.70
SCREENING_PREFILTER_TOKEN_OVERLAP_RATIO = 0.50
SCREENING_DISTINCTIVE_TOKEN_MIN = 2
SCREENING_DISTINCTIVE_TOKEN_IDF_FLOOR = 1.5
SCREENING_DISTINCTIVE_TOKEN_PENALTY_MULTIPLIER = 0.50
SCREENING_CONTAINMENT_BYPASS_RATIO = 0.95
SCREENING_ALL_STOPWORD_JW_BYPASS = 0.88
SCREENING_COUNTRY_MISMATCH_PENALTY_MULTIPLIER = 0.70
SCREENING_SINGLE_TOKEN_SDN_PENALTY_MULTIPLIER = 0.50


def _screening_policy_basis(threshold: float) -> dict:
    return {
        "composite_threshold": round(threshold, 4),
        "prefilter": {
            "jaro_winkler_floor": SCREENING_PREFILTER_JW_FLOOR,
            "token_overlap_ratio": SCREENING_PREFILTER_TOKEN_OVERLAP_RATIO,
        },
        "signal_weights": {
            "idf_token": 0.30,
            "dice_bigram": 0.20,
            "jaro_winkler": 0.15,
            "token_containment": 0.15,
            "phonetic_bonus": 0.10,
            "length_ratio": 0.10,
        },
        "post_match_gates": {
            "distinctive_token_min": SCREENING_DISTINCTIVE_TOKEN_MIN,
            "distinctive_token_idf_floor": SCREENING_DISTINCTIVE_TOKEN_IDF_FLOOR,
            "distinctive_token_penalty_multiplier": SCREENING_DISTINCTIVE_TOKEN_PENALTY_MULTIPLIER,
            "containment_bypass_ratio": SCREENING_CONTAINMENT_BYPASS_RATIO,
            "all_stopword_jw_bypass": SCREENING_ALL_STOPWORD_JW_BYPASS,
            "country_mismatch_penalty_multiplier": SCREENING_COUNTRY_MISMATCH_PENALTY_MULTIPLIER,
            "single_token_sdn_penalty_multiplier": SCREENING_SINGLE_TOKEN_SDN_PENALTY_MULTIPLIER,
        },
    }


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
    policy_basis: dict = field(default_factory=dict)


def screen_name(
    vendor_name: str,
    threshold: float = SCREENING_COMPOSITE_THRESHOLD_DEFAULT,
    vendor_country: str = "",
) -> ScreeningResult:
    """
    Screen a vendor name against the active sanctions database.

    v4.0: Uses composite multi-signal scoring with post-match
    validation gates (distinctive tokens, country confirmation).
    Dual-source architecture merges live DB with fallback overlay.

    Args:
        vendor_name: Entity name to screen.
        threshold: Composite score threshold (default 0.75).
        vendor_country: Optional ISO country code for the vendor.
            When provided, enables country-mismatch penalty that
            suppresses false positives between unrelated entities
            in different jurisdictions.

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

    # Pre-compute vendor tokens once for cheap token-overlap gate
    _vendor_tokens_set = set(_tokenize(vendor_name))

    for entry in db:
        names = [entry.name] + entry.aliases
        for name in names:
            # Two-gate pre-filter (disjunctive OR):
            # Gate 1: JW >= 0.70 catches most same-order matches (fast)
            # Gate 2: token overlap >= 50% catches reordered/transliterated
            #         names that JW misses (cheap set intersection)
            # A candidate passes if EITHER gate fires.
            raw_jw = jaro_winkler(vendor_name, name)
            if raw_jw < SCREENING_PREFILTER_JW_FLOOR:
                # Gate 2: check token overlap before skipping
                sdn_tokens_set = set(_tokenize(name))
                if _vendor_tokens_set and sdn_tokens_set:
                    overlap = len(_vendor_tokens_set & sdn_tokens_set)
                    min_len = min(len(_vendor_tokens_set), len(sdn_tokens_set))
                    if overlap / min_len < SCREENING_PREFILTER_TOKEN_OVERLAP_RATIO:
                        continue
                else:
                    continue

            # Full composite scoring with optional country metadata
            composite, details = composite_match_score(
                vendor_name, name, entry, vendor_country=vendor_country
            )

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
        policy_basis=_screening_policy_basis(threshold),
    )
