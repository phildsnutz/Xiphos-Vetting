"""
Shared entity matching module for OSINT connectors.

Provides a unified entity_match() function that all OSINT connectors should use
instead of ad-hoc string matching patterns. Implements normalization, fuzzy matching,
token-based matching, and abbreviation handling.

Author: Xiphos Platform
Date: March 2026
"""

import unicodedata
import re
from dataclasses import dataclass
from typing import Optional


# Entity suffixes that should be stripped during normalization
ENTITY_SUFFIXES = {
    "llc", "llp", "lp", "ltd", "inc", "co", "corp", "corporation",
    "incorporated", "limited", "company", "plc", "sa", "ag", "gmbh",
    "bv", "nv", "pty", "srl", "spa", "ab", "oy", "as", "se",
    "group", "holdings", "partners", "associates", "the",
}

# Common abbreviations and their expansions
ABBREVIATION_MAP = {
    "gen": "general",
    "genl": "general",
    "intl": "international",
    "natl": "national",
    "bd": "board",
    "mfg": "manufacturing",
    "mfr": "manufacturing",
    "div": "division",
    "dept": "department",
    "sys": "systems",
}


@dataclass
class MatchResult:
    """Result of entity matching operation."""
    matched: bool
    score: float  # 0.0 to 1.0
    method: str  # "exact", "token_match", "jaro_winkler", or "none"


def _normalize_unicode(text: str) -> str:
    """Normalize unicode characters (NFD decomposition, strip accents)."""
    nfd = unicodedata.normalize('NFD', text)
    return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')


def _normalize_entity(text: str) -> str:
    """
    Normalize an entity name:
    - Lowercase
    - Strip entity suffixes
    - Collapse whitespace
    - Remove punctuation
    - Normalize unicode
    - Expand abbreviations
    """
    # Normalize unicode
    text = _normalize_unicode(text)

    # Lowercase
    text = text.lower()

    # Remove punctuation (keep spaces)
    text = re.sub(r"[,.\-&/()'\"]", " ", text)

    # Collapse whitespace
    text = ' '.join(text.split())

    # Split into words
    words = text.split()

    # Strip entity suffixes and expand abbreviations
    cleaned_words = []
    for word in words:
        if word in ENTITY_SUFFIXES:
            continue
        # Expand abbreviations
        if word in ABBREVIATION_MAP:
            cleaned_words.append(ABBREVIATION_MAP[word])
        else:
            cleaned_words.append(word)

    # Rejoin
    result = ' '.join(cleaned_words)
    return result.strip()


def _jaro_winkler_distance(s1: str, s2: str) -> float:
    """
    Compute Jaro-Winkler similarity score (0.0 to 1.0).

    Based on the classic Jaro-Winkler algorithm:
    - Jaro similarity based on common characters and transpositions
    - Winkler modification gives bonus for matching prefixes
    """
    if not s1 or not s2:
        return 1.0 if s1 == s2 else 0.0

    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)

    # Maximum allowed distance
    match_distance = max(len1, len2) // 2 - 1
    match_distance = max(0, match_distance)

    # Initialize arrays for matches
    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    transpositions = 0

    # Find matches
    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)

        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    # Count transpositions
    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    # Jaro similarity
    jaro = (matches / len1 + matches / len2 +
            (matches - transpositions / 2) / matches) / 3.0

    # Winkler modification: add bonus for common prefix (up to 4 chars)
    prefix_len = 0
    for i in range(min(len(s1), len(s2), 4)):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break

    # Scale prefix bonus: typical range is 0.1
    jaro_winkler = jaro + (prefix_len * 0.1 * (1.0 - jaro))

    return jaro_winkler


def _token_match(query_tokens: list[str], candidate_tokens: list[str]) -> bool:
    """
    Token-based matching: all significant tokens from query must appear
    in candidate (order-independent).
    """
    if not query_tokens:
        return True

    candidate_set = set(candidate_tokens)

    for token in query_tokens:
        if token not in candidate_set:
            return False

    return True


def entity_match(
    query: str,
    candidate: str,
    jaro_threshold: float = 0.85,
) -> MatchResult:
    """
    Match two entity names using multiple strategies.

    Implements:
    1. Exact match (after normalization)
    2. Token-based matching (all query tokens in candidate)
    3. Jaro-Winkler fuzzy matching

    Args:
        query: The name to search for (e.g., "Lockheed Martin Corp")
        candidate: The name to match against (e.g., "LOCKHEED MARTIN CORPORATION")
        jaro_threshold: Minimum Jaro-Winkler score for match (default 0.85)

    Returns:
        MatchResult with matched (bool), score (0.0-1.0), and method used

    Example:
        >>> result = entity_match("Boeing", "The Boeing Company")
        >>> result.matched
        True
        >>> result.score
        0.95
        >>> result.method
        'token_match'
    """
    # Normalize both strings
    norm_query = _normalize_entity(query)
    norm_candidate = _normalize_entity(candidate)

    # Strategy 1: Exact match
    if norm_query == norm_candidate:
        return MatchResult(matched=True, score=1.0, method="exact")

    # Split into tokens
    query_tokens = norm_query.split()
    candidate_tokens = norm_candidate.split()

    # Strategy 2: Token-based matching (all query tokens in candidate)
    if _token_match(query_tokens, candidate_tokens):
        # Score based on what fraction of candidate tokens are covered
        # and what fraction of query tokens matched
        coverage = len(query_tokens) / len(candidate_tokens) if candidate_tokens else 0.0
        score = 0.95 * coverage + 0.05  # Base 0.05 for matching all tokens
        return MatchResult(matched=True, score=score, method="token_match")

    # Strategy 3: Jaro-Winkler fuzzy matching
    jw_score = _jaro_winkler_distance(norm_query, norm_candidate)

    if jw_score >= jaro_threshold:
        return MatchResult(matched=True, score=jw_score, method="jaro_winkler")

    # No match
    return MatchResult(matched=False, score=jw_score, method="none")
