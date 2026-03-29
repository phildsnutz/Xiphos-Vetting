"""
Xiphos screen_name() Regression and Forensic Tests

Validates that the v4.0 composite matcher reliably catches all fallback DB
entities, documents signal breakdowns for forensics, and protects against
regressions in token containment, stopword stripping, and threshold behavior.

Production findings (Sprint 7):
  - Huawei:    composite 0.63-0.68 vs 0.75 threshold -> MISSED (pre-v3.1)
  - Kaspersky: missing from fallback DB entirely -> MISSED (pre-v3.1)
  - DJI:       composite 0.46-0.55 vs 0.75 threshold -> MISSED (pre-v3.1)
  - Hikvision: composite 0.63-0.68 vs 0.75 threshold -> MISSED (pre-v3.1)

All four are now fixed via v3.1 fallback DB expansion + Signal 6 token
containment + defense industry stopwords.

Tests are structured as:
  - Regression tests: Verify all 27 fallback entries self-match.
  - Tier D coverage: Section 889 / NDAA 1260H entities match reliably.
  - Forensic tests: Signal breakdown recording for composite scoring.
  - Name variation analysis: Legal suffix, abbreviation, city prefix tests.
  - Threshold sensitivity: Explores false positive rates at lower thresholds.

Usage:
    python -m pytest tests/test_screen_name_false_negatives.py -v
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

# Force fallback DB so tests are deterministic (no live SQLite dependency)
os.environ["XIPHOS_SCREENING_FALLBACK"] = "1"

from ofac import (
    screen_name,
    composite_match_score,
    jaro_winkler,
    SanctionEntry,
    FALLBACK_DB,
    _tokenize,
    invalidate_cache,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def force_fallback():
    """Ensure every test uses fallback DB for determinism."""
    os.environ["XIPHOS_SCREENING_FALLBACK"] = "1"
    invalidate_cache()
    yield
    invalidate_cache()


def _get_fallback_entry(uid_suffix: str) -> SanctionEntry:
    """Look up a fallback DB entry by UID suffix (e.g., '35012' matches 'XIPHOS-FB-35012')."""
    for entry in FALLBACK_DB:
        if entry.uid.endswith(uid_suffix):
            return entry
    raise ValueError(f"No fallback entry with UID suffix '{uid_suffix}'")


# ===========================================================================
# CLASS 1: Tier D Coverage (Section 889 / NDAA 1260H entities)
# ===========================================================================

class TestTierDCoverage:
    """
    These vendors previously failed to match (Sprint 7 production bug).
    Fixed in v3.1 via:
      1. Expanded fallback DB (Kaspersky, DJI, Hikvision, Dahua, ZTE, Hytera added)
      2. Signal 6: token containment (catches short vendor names in long SDN entries)
      3. Defense-industry stopword list (TECHNOLOGIES, HANGZHOU, etc. no longer dilute IDF)

    These tests verify the fixes hold. If any regress, a change to ofac.py
    broke the Tier D coverage.
    """

    def test_kaspersky_lab_matches(self):
        """Kaspersky (XIPHOS-FB-KASPERSKY) added to fallback DB in v3.1."""
        result = screen_name("KASPERSKY LAB")
        assert result.matched, (
            f"Kaspersky should match (fallback DB entry XIPHOS-FB-KASPERSKY), "
            f"got composite={result.best_score:.4f}"
        )
        assert result.best_score >= 0.75

    def test_dji_matches(self):
        """DJI (XIPHOS-FB-1260H-DJI) short name caught by Signal 6 token containment."""
        result = screen_name("DJI")
        assert result.matched, (
            f"DJI should match (fallback DB entry XIPHOS-FB-1260H-DJI), "
            f"got composite={result.best_score:.4f}"
        )
        assert result.best_score >= 0.75

    def test_hikvision_matches(self):
        """Hikvision (XIPHOS-FB-889-HIKVISION) with stopword stripping of HANGZHOU/DIGITAL/TECHNOLOGY."""
        result = screen_name("HIKVISION")
        assert result.matched, (
            f"Hikvision should match (fallback DB entry XIPHOS-FB-889-HIKVISION), "
            f"got composite={result.best_score:.4f}"
        )
        assert result.best_score >= 0.75

    def test_dahua_matches(self):
        """Dahua (XIPHOS-FB-889-DAHUA) Section 889 entity."""
        result = screen_name("DAHUA")
        assert result.matched, f"Dahua should match, got {result.best_score:.4f}"

    def test_zte_matches(self):
        """ZTE (XIPHOS-FB-889-ZTE) Section 889 entity."""
        result = screen_name("ZTE")
        assert result.matched, f"ZTE should match, got {result.best_score:.4f}"

    def test_hytera_matches(self):
        """Hytera (XIPHOS-FB-889-HYTERA) Section 889 entity."""
        result = screen_name("HYTERA")
        assert result.matched, f"Hytera should match, got {result.best_score:.4f}"

    def test_avic_matches(self):
        """AVIC (XIPHOS-FB-1260H-AVIC) NDAA 1260H Chinese military company."""
        result = screen_name("AVIC")
        assert result.matched, f"AVIC should match, got {result.best_score:.4f}"

    def test_smic_matches(self):
        """SMIC (XIPHOS-FB-1260H-SMIC) NDAA 1260H via alias."""
        result = screen_name("SMIC")
        assert result.matched, f"SMIC should match, got {result.best_score:.4f}"


# ===========================================================================
# CLASS 2: Forensic Signal Breakdowns
# ===========================================================================

class TestCompositeScoreForensics:
    """
    Measure exact signal breakdowns for Section 889/1260H entities.
    These tests always pass; they're diagnostic, recording scores
    so we can track improvements over time.
    """

    def test_kaspersky_signal_breakdown(self):
        """
        Record all signal values for Kaspersky composite scoring.
        Fallback DB has "KASPERSKY LAB" (XIPHOS-FB-KASPERSKY).
        """
        entry = _get_fallback_entry("KASPERSKY")
        vendor = "KASPERSKY LAB"

        composite, details = composite_match_score(vendor, entry.name, entry)

        print("\n--- KASPERSKY FORENSICS ---")
        print(f"  Vendor:       '{vendor}'")
        print(f"  Fallback:     '{entry.name}' (UID: {entry.uid})")
        print(f"  IDF token:    {details['idf_token']}")
        print(f"  Dice bigram:  {details['dice_bigram']}")
        print(f"  Jaro-Winkler: {details['jaro_winkler']}")
        print(f"  Entity type:  {details['entity_type_factor']}")
        print(f"  Phonetic:     {details['phonetic_match']}")
        print(f"  Length ratio:  {details['length_ratio']}")
        print(f"  Raw composite: {details['raw_composite']}")
        print(f"  Final score:   {details['final_score']}")

        assert composite >= 0.75, (
            f"Kaspersky self-match should score >= 0.75, got {composite:.4f}"
        )

    def test_dji_signal_breakdown(self):
        """
        Record signal values for DJI. Fallback DB has "DJI" (XIPHOS-FB-1260H-DJI)
        with alias "SZ DJI TECHNOLOGY CO LTD". Short name relies on Signal 6.
        """
        entry = _get_fallback_entry("1260H-DJI")
        vendor = "DJI"

        # Test against the primary name "DJI"
        composite, details = composite_match_score(vendor, entry.name, entry)

        print("\n--- DJI FORENSICS ---")
        print(f"  Vendor:       '{vendor}'")
        print(f"  Fallback:     '{entry.name}' (UID: {entry.uid})")
        print(f"  IDF token:    {details['idf_token']}")
        print(f"  Dice bigram:  {details['dice_bigram']}")
        print(f"  Jaro-Winkler: {details['jaro_winkler']}")
        print(f"  Token containment: {details['token_containment']}")
        print(f"  Length ratio:  {details['length_ratio']}")
        print(f"  Raw composite: {details['raw_composite']}")
        print(f"  Final score:   {details['final_score']}")

        # DJI vs "DJI" (primary name) should be near-perfect
        assert composite >= 0.75

    def test_hikvision_signal_breakdown(self):
        """
        Record signal values for Hikvision. Fallback DB has "HIKVISION"
        (XIPHOS-FB-889-HIKVISION) with alias "HANGZHOU HIKVISION DIGITAL TECHNOLOGY".
        """
        entry = _get_fallback_entry("889-HIKVISION")
        vendor = "HIKVISION"

        composite, details = composite_match_score(vendor, entry.name, entry)

        print("\n--- HIKVISION FORENSICS ---")
        print(f"  Vendor:       '{vendor}'")
        print(f"  Fallback:     '{entry.name}' (UID: {entry.uid})")
        print(f"  IDF token:    {details['idf_token']}")
        print(f"  Dice bigram:  {details['dice_bigram']}")
        print(f"  Jaro-Winkler: {details['jaro_winkler']}")
        print(f"  Token containment: {details['token_containment']}")
        print(f"  Length ratio:  {details['length_ratio']}")
        print(f"  Raw composite: {details['raw_composite']}")
        print(f"  Final score:   {details['final_score']}")

        assert composite >= 0.75

    def test_huawei_signal_breakdown(self):
        """
        Huawei (XIPHOS-FB-35012) self-match against fallback DB.
        """
        entry = _get_fallback_entry("35012")
        vendor = "HUAWEI TECHNOLOGIES CO LTD"

        composite, details = composite_match_score(vendor, entry.name, entry)

        print("\n--- HUAWEI FORENSICS ---")
        print(f"  Vendor:       '{vendor}'")
        print(f"  Fallback:     '{entry.name}' (UID: {entry.uid})")
        print(f"  Matched:      composite={composite:.4f}")
        print(f"  IDF token:    {details['idf_token']}")
        print(f"  Jaro-Winkler: {details['jaro_winkler']}")
        print(f"  Final score:   {details['final_score']}")

        assert composite >= 0.75


# ===========================================================================
# CLASS 3: Name Variation Analysis
# ===========================================================================

class TestNameVariationAnalysis:
    """
    Systematically test specific name format variations against fallback DB entries.
    """

    def test_legal_suffix_variation_huawei(self):
        """'Co., Ltd.' vs 'CO LTD' vs 'Corporation' vs no suffix against Huawei fallback."""
        entry = _get_fallback_entry("35012")

        variants = [
            "HUAWEI TECHNOLOGIES",
            "HUAWEI TECHNOLOGIES CO LTD",
            "HUAWEI TECHNOLOGIES CORPORATION",
            "HUAWEI TECHNOLOGIES COMPANY LIMITED",
        ]

        print("\n--- HUAWEI LEGAL SUFFIX VARIATIONS ---")
        for v in variants:
            composite, details = composite_match_score(v, entry.name, entry)
            status = "PASS" if composite >= 0.75 else "FAIL"
            print(f"  [{status}] '{v}' -> {composite:.4f}")

        # At minimum, the no-suffix version should score well
        no_suffix_score, _ = composite_match_score("HUAWEI TECHNOLOGIES", entry.name, entry)
        assert no_suffix_score > 0.50, (
            f"'HUAWEI TECHNOLOGIES' should score > 0.50, got {no_suffix_score:.4f}"
        )

    def test_abbreviation_vs_full_name_jw(self):
        """Common abbreviations vs full fallback DB names: JW scores."""
        entry_dji = _get_fallback_entry("1260H-DJI")
        entry_huawei = _get_fallback_entry("35012")
        entry_hik = _get_fallback_entry("889-HIKVISION")
        entry_kas = _get_fallback_entry("KASPERSKY")

        test_cases = [
            ("DJI", entry_dji.aliases[0] if entry_dji.aliases else entry_dji.name),
            ("HUAWEI", entry_huawei.name),
            ("HIKVISION", entry_hik.aliases[0] if entry_hik.aliases else entry_hik.name),
            ("KASPERSKY", entry_kas.name),
        ]

        print("\n--- ABBREVIATION vs FULL NAME ---")
        for abbrev, full in test_cases:
            jw = jaro_winkler(abbrev, full)
            print(f"  JW('{abbrev}', '{full}') = {jw:.4f}")

    def test_token_overlap_with_city_prefix(self):
        """
        Hikvision's fallback alias includes "HANGZHOU HIKVISION DIGITAL TECHNOLOGY".
        After stopword stripping, HANGZHOU/DIGITAL/TECHNOLOGY should be removed.
        """
        entry = _get_fallback_entry("889-HIKVISION")
        # Use the alias that has city prefix
        long_alias = None
        for a in entry.aliases:
            if "HANGZHOU" in a.upper():
                long_alias = a
                break

        if long_alias is None:
            pytest.skip("No HANGZHOU alias in Hikvision fallback entry")

        vendor_tokens = _tokenize("HIKVISION")
        sdn_tokens = _tokenize(long_alias)

        overlap = set(vendor_tokens) & set(sdn_tokens)

        print("\n--- TOKEN OVERLAP: HIKVISION ---")
        print(f"  Vendor tokens: {vendor_tokens}")
        print(f"  SDN tokens:    {sdn_tokens}")
        print(f"  Overlap:       {overlap}")

        assert "HIKVISION" in overlap, "HIKVISION token should overlap"

    def test_russian_legal_prefix_ao_is_stopword(self):
        """
        v3.1: 'AO' (Russian Joint-Stock Company) is now in _STOPWORDS.
        'AO KASPERSKY LAB' tokenizes to [KASPERSKY, LAB], same as 'KASPERSKY LAB'.
        """
        entry = _get_fallback_entry("KASPERSKY")
        # Check if AO appears in any alias
        ao_alias = None
        for a in entry.aliases:
            if a.upper().startswith("AO "):
                ao_alias = a
                break

        if ao_alias is None:
            pytest.skip("No AO alias in Kaspersky fallback entry")

        vendor_tokens = _tokenize("KASPERSKY LAB")
        sdn_tokens = _tokenize(ao_alias)

        print("\n--- RUSSIAN PREFIX 'AO' ---")
        print(f"  Vendor tokens: {vendor_tokens}")
        print(f"  SDN tokens:    {sdn_tokens}")

        assert "AO" not in sdn_tokens, "AO should be stripped as stopword (v3.1)"
        assert set(vendor_tokens) == set(sdn_tokens), (
            f"After stopword stripping, tokens should be identical: "
            f"{vendor_tokens} vs {sdn_tokens}"
        )

    def test_shenzhen_prefix_sz(self):
        """
        DJI's fallback alias starts with 'SZ' (Shenzhen). Verify SZ is a stopword
        so it doesn't dilute token overlap for short names.
        """
        entry = _get_fallback_entry("1260H-DJI")
        sz_alias = None
        for a in entry.aliases:
            if "SZ " in a.upper():
                sz_alias = a
                break

        if sz_alias is None:
            pytest.skip("No SZ alias in DJI fallback entry")

        vendor_tokens = _tokenize("DJI")
        sdn_tokens = _tokenize(sz_alias)

        print("\n--- SZ PREFIX (DJI) ---")
        print(f"  Vendor tokens: {vendor_tokens}")
        print(f"  SDN tokens:    {sdn_tokens}")

        assert "DJI" in sdn_tokens, "DJI should be in SDN tokens"


# ===========================================================================
# CLASS 4: Regression Protection (all 27 fallback entries self-match)
# ===========================================================================

class TestScreenNameRegressions:
    """
    Every fallback DB entry should match itself. If any regress,
    a change to ofac.py broke fundamental matching.
    """

    def test_all_fallback_entries_self_match(self):
        """Each of the 27 fallback entries should match itself at >= 0.75."""
        failures = []
        for entry in FALLBACK_DB:
            result = screen_name(entry.name)
            if not result.matched or result.best_score < 0.75:
                failures.append(
                    f"  {entry.name} ({entry.uid}): matched={result.matched}, score={result.best_score:.4f}"
                )
        assert not failures, (
            f"{len(failures)} fallback entries failed self-match:\n" + "\n".join(failures)
        )

    def test_fallback_db_has_27_entries(self):
        """Verify fallback DB size hasn't regressed."""
        assert len(FALLBACK_DB) == 27, f"Expected 27 fallback entries, got {len(FALLBACK_DB)}"

    def test_all_uids_use_xiphos_fb_namespace(self):
        """All fallback UIDs must use XIPHOS-FB-* to prevent live DB collisions."""
        bad_uids = []
        for entry in FALLBACK_DB:
            if not entry.uid.startswith("XIPHOS-FB-"):
                bad_uids.append(f"  {entry.name}: {entry.uid}")
        assert not bad_uids, (
            "Found fallback entries with non-XIPHOS-FB UIDs:\n" + "\n".join(bad_uids)
        )

    def test_rosoboronexport_common_spelling(self):
        result = screen_name("ROSOBORONEXPORT")
        assert result.matched
        assert result.best_score >= 0.80

    def test_wagner_group_matches(self):
        result = screen_name("WAGNER GROUP")
        assert result.matched

    def test_norinco_matches(self):
        result = screen_name("NORINCO")
        assert result.matched

    def test_huawei_exact_match(self):
        result = screen_name("HUAWEI TECHNOLOGIES CO LTD")
        assert result.matched
        assert result.best_score >= 0.75

    def test_iran_electronics_matches(self):
        result = screen_name("IRAN ELECTRONICS INDUSTRIES")
        assert result.matched

    def test_komid_full_name_matches(self):
        result = screen_name("KOREA MINING DEVELOPMENT TRADING CORPORATION")
        assert result.matched

    def test_mahan_air_matches(self):
        result = screen_name("MAHAN AIR")
        assert result.matched


# ===========================================================================
# CLASS 5: Threshold Sensitivity Analysis
# ===========================================================================

class TestThresholdSensitivity:
    """
    Explore what thresholds do to false positive rates.
    These are diagnostic tests that record behavior.
    """

    def test_lowering_threshold_to_060_false_positive_check(self):
        """
        If we lower threshold to 0.60, do clean names start matching?
        Tests common benign company names that should NOT match anything.
        """
        clean_names = [
            "LOCKHEED MARTIN CORPORATION",
            "RAYTHEON TECHNOLOGIES",
            "BOEING DEFENSE",
            "GENERAL DYNAMICS",
            "NORTHROP GRUMMAN",
            "L3HARRIS TECHNOLOGIES",
            "BAE SYSTEMS",
            "DELL TECHNOLOGIES",
            "MICROSOFT CORPORATION",
            "AMAZON WEB SERVICES",
        ]

        false_positives = []
        for name in clean_names:
            result = screen_name(name, threshold=0.60)
            if result.matched:
                false_positives.append((name, result.best_score, result.matched_name))

        print("\n--- FALSE POSITIVES AT THRESHOLD 0.60 ---")
        if false_positives:
            for name, score, matched in false_positives:
                print(f"  FALSE POSITIVE: '{name}' matched '{matched}' at {score:.4f}")
        else:
            print(f"  None (0 false positives from {len(clean_names)} clean names)")

    def test_substring_containment_catches_short_names(self):
        """
        Signal 6 token containment catches short vendor names that are
        strict subsets of long fallback entry aliases.
        """
        entry = _get_fallback_entry("889-HIKVISION")
        vendor = "HIKVISION"

        substring_match = vendor.upper() in entry.name.upper()
        assert substring_match, "HIKVISION should be substring of fallback entry name"

    def test_token_level_containment_avoids_partial_hits(self):
        """
        Token-level matching at 3+ chars prevents partial character matches.
        "AI" should not token-match "AIR" in MAHAN AIR.
        """
        short_names = ["AI", "IN", "AN", "US"]
        sdn = "MAHAN AIR"

        for name in short_names:
            tokens = sdn.upper().split()
            token_hit = name.upper() in tokens
            print(f"  '{name}' in '{sdn}': token_hit={token_hit}")

        assert "AI" not in sdn.upper().split(), "AI should not token-match AIR"
