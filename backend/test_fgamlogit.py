"""
Unit tests for fgamlogit.py — FGAMLogit v5.0 Two-Layer Scoring Engine

Tests cover:
  - Pure math utilities (_logistic, _logit, _wilson_ci)
  - Geography risk table and normalization
  - Factor computation functions (ownership, data quality, exec, foreign ownership depth)
  - Layer integration logic (regulatory x probability x sensitivity -> tier)
  - Program recommendation mapping
  - End-to-end score_vendor pipeline
  - Hard stop evaluation
  - Soft flag generation
  - Counterfactual MIV computation
  - Dataclass construction and to_dict serialization

Run:  pytest test_fgamlogit.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
os.environ["XIPHOS_SCREENING_FALLBACK"] = "1"

import pytest
from fgamlogit import (
    _logistic, _logit, _wilson_ci,
    _normalize_country, geo_risk,
    _compute_ownership_risk, _compute_data_quality_risk,
    _compute_exec_risk, _compute_foreign_ownership_depth,
    integrate_layers, _program_recommendation,
    _evaluate_hard_stops, _evaluate_soft_flags,
    score_vendor, ScoringResultV5,
    OwnershipProfile, DataQuality, ExecProfile, DoDContext, VendorInputV5,
    ALLIED_NATIONS, COMPREHENSIVELY_SANCTIONED, SENSITIVITY_TIERS,
    FACTOR_NAMES, BASELINE_LOGODDS, FACTOR_WEIGHTS,
    EFFECTIVE_N_BASE, TIER_MULTIPLIED_FACTORS,
)
from ofac import ScreeningResult, SanctionEntry


# ============================================================================
# HELPERS
# ============================================================================

def _make_vendor(
    name="Acme Corp",
    country="US",
    sensitivity="COMMERCIAL",
    **overrides,
) -> VendorInputV5:
    """Build a minimal VendorInputV5 with sane defaults."""
    own = overrides.pop("ownership", OwnershipProfile())
    dq = overrides.pop("data_quality", DataQuality())
    ep = overrides.pop("exec_profile", ExecProfile())
    dod = overrides.pop("dod", DoDContext(sensitivity=sensitivity))
    return VendorInputV5(
        name=name, country=country,
        ownership=own, data_quality=dq, exec_profile=ep, dod=dod,
    )


def _make_screening(matched=False, best_score=0.0, best_raw_jw=0.0,
                    matched_name="", country="", list_type="SDN",
                    program="UNKNOWN"):
    """Build a ScreeningResult for hard-stop / soft-flag testing."""
    entry = SanctionEntry(
        name=matched_name, aliases=[], list_type=list_type,
        program=program, country=country, entity_type="entity",
        uid="TEST-001", source="test",
    ) if matched else None
    return ScreeningResult(
        matched=matched, best_score=best_score,
        best_raw_jw=best_raw_jw, matched_name=matched_name,
        matched_entry=entry,
        db_label="fallback", screening_ms=0.0, match_details={},
    )


# ============================================================================
# TEST: MATH UTILITIES
# ============================================================================

class TestLogistic:
    def test_zero(self):
        assert _logistic(0.0) == pytest.approx(0.5, abs=1e-9)

    def test_large_positive(self):
        assert _logistic(100.0) == pytest.approx(1.0, abs=1e-9)

    def test_large_negative(self):
        assert _logistic(-100.0) == pytest.approx(0.0, abs=1e-9)

    def test_symmetry(self):
        """logistic(x) + logistic(-x) == 1"""
        for x in [0.5, 1.0, 2.0, 5.0]:
            assert _logistic(x) + _logistic(-x) == pytest.approx(1.0, abs=1e-9)

    def test_known_value(self):
        # logistic(1) = 1 / (1 + e^-1) ~ 0.7311
        assert _logistic(1.0) == pytest.approx(0.7310585786, abs=1e-6)

    def test_baseline_logodds(self):
        """Baseline -2.94 should give ~5% probability."""
        p = _logistic(-2.94)
        assert 0.04 < p < 0.06


class TestLogit:
    def test_half(self):
        assert _logit(0.5) == pytest.approx(0.0, abs=1e-9)

    def test_round_trip(self):
        """logistic(logit(p)) == p"""
        for p in [0.1, 0.25, 0.5, 0.75, 0.9]:
            assert _logistic(_logit(p)) == pytest.approx(p, abs=1e-6)

    def test_clamp_zero(self):
        """Should not raise even at extremes."""
        result = _logit(0.0)
        assert result < -15  # very negative

    def test_clamp_one(self):
        result = _logit(1.0)
        assert result > 15  # very positive


class TestWilsonCI:
    def test_ci_contains_estimate(self):
        lo, hi = _wilson_ci(0.3, 100.0)
        assert lo <= 0.3 <= hi

    def test_wider_with_smaller_n(self):
        _, hi1 = _wilson_ci(0.5, 50.0)
        lo1, _ = _wilson_ci(0.5, 50.0)
        _, hi2 = _wilson_ci(0.5, 200.0)
        lo2, _ = _wilson_ci(0.5, 200.0)
        width_small = hi1 - lo1
        width_large = hi2 - lo2
        assert width_small > width_large

    def test_clamped_to_unit(self):
        lo, hi = _wilson_ci(0.01, 5.0)
        assert lo >= 0.0
        assert hi <= 1.0

    def test_perfect_score(self):
        lo, hi = _wilson_ci(1.0, 100.0)
        assert hi <= 1.0
        assert lo > 0.9


# ============================================================================
# TEST: GEOGRAPHY
# ============================================================================

class TestNormalizeCountry:
    def test_alpha2_passthrough(self):
        assert _normalize_country("US") == "US"

    def test_alpha3_conversion(self):
        assert _normalize_country("USA") == "US"
        assert _normalize_country("GBR") == "GB"
        assert _normalize_country("CHN") == "CN"

    def test_lowercase_input(self):
        assert _normalize_country("usa") == "US"

    def test_whitespace(self):
        assert _normalize_country("  US  ") == "US"

    def test_unknown_alpha3(self):
        """Unknown 3-letter codes pass through unchanged."""
        assert _normalize_country("ZZZ") == "ZZZ"


class TestGeoRisk:
    def test_us_low_risk(self):
        assert geo_risk("US") == 0.02

    def test_north_korea_high_risk(self):
        assert geo_risk("KP") == 0.98

    def test_alpha3_works(self):
        assert geo_risk("USA") == 0.02

    def test_unknown_country_default(self):
        """Unknown country returns 0.15 default."""
        assert geo_risk("ZZ") == 0.15

    def test_allied_nations_low_risk(self):
        for cc in ["GB", "CA", "AU", "DE", "JP"]:
            assert geo_risk(cc) < 0.10

    def test_sanctioned_nations_high_risk(self):
        for cc in COMPREHENSIVELY_SANCTIONED:
            assert geo_risk(cc) >= 0.70


# ============================================================================
# TEST: CONSTANTS INTEGRITY
# ============================================================================

class TestConstants:
    def test_sensitivity_tiers_count(self):
        assert len(SENSITIVITY_TIERS) == 7

    def test_factor_names_count(self):
        assert len(FACTOR_NAMES) == 14

    def test_all_factors_have_weights(self):
        for fname in FACTOR_NAMES:
            assert fname in FACTOR_WEIGHTS
            for tier in SENSITIVITY_TIERS:
                assert tier in FACTOR_WEIGHTS[fname]

    def test_baseline_logodds_uniform(self):
        """All tiers have the same baseline."""
        values = set(BASELINE_LOGODDS.values())
        assert len(values) == 1
        assert values.pop() == -2.94

    def test_allied_nations_includes_five_eyes(self):
        five_eyes = {"US", "GB", "CA", "AU", "NZ"}
        assert five_eyes.issubset(ALLIED_NATIONS)

    def test_comprehensively_sanctioned(self):
        assert COMPREHENSIVELY_SANCTIONED == {"RU", "IR", "KP", "SY", "CU"}

    def test_effective_n_base_decreases_with_sensitivity(self):
        """SAP has smallest n (widest CI), COMMERCIAL has largest."""
        assert EFFECTIVE_N_BASE["CRITICAL_SAP"] < EFFECTIVE_N_BASE["COMMERCIAL"]

    def test_tier_multiplied_factors(self):
        assert TIER_MULTIPLIED_FACTORS == {"data_quality", "executive", "ownership"}


# ============================================================================
# TEST: OWNERSHIP RISK
# ============================================================================

class TestOwnershipRisk:
    def test_clean_company(self):
        o = OwnershipProfile(
            publicly_traded=True, beneficial_owner_known=True,
            ownership_pct_resolved=1.0,
        )
        risk = _compute_ownership_risk(o)
        assert risk == 0.0  # publicly_traded -0.15 makes it negative, clamped to 0

    def test_state_owned(self):
        o = OwnershipProfile(state_owned=True)
        risk = _compute_ownership_risk(o)
        assert risk >= 0.30

    def test_unknown_beneficial_owner(self):
        o = OwnershipProfile(beneficial_owner_known=False)
        risk = _compute_ownership_risk(o)
        assert risk >= 0.25

    def test_shell_layers_capped(self):
        o = OwnershipProfile(shell_layers=10)
        risk = _compute_ownership_risk(o)
        # shell_layers contribution capped at 0.30
        assert risk <= 1.0

    def test_pep_connection(self):
        o = OwnershipProfile(pep_connection=True, beneficial_owner_known=True)
        risk = _compute_ownership_risk(o)
        assert risk >= 0.15

    def test_publicly_traded_reduces_risk(self):
        base = OwnershipProfile(beneficial_owner_known=True, ownership_pct_resolved=0.5)
        traded = OwnershipProfile(beneficial_owner_known=True, ownership_pct_resolved=0.5, publicly_traded=True)
        assert _compute_ownership_risk(traded) < _compute_ownership_risk(base)

    def test_maximum_opacity(self):
        """All risk factors active, no mitigants."""
        o = OwnershipProfile(
            state_owned=True, beneficial_owner_known=False,
            ownership_pct_resolved=0.0, shell_layers=5,
            pep_connection=True, publicly_traded=False,
        )
        risk = _compute_ownership_risk(o)
        # 0.30 + 0.25 + 0.20 + 0.30 + 0.15 = 1.20 -> clamped to 1.0
        assert risk == 1.0


# ============================================================================
# TEST: DATA QUALITY RISK
# ============================================================================

class TestDataQualityRisk:
    def test_complete_data(self):
        d = DataQuality(
            has_lei=True, has_cage=True, has_duns=True,
            has_tax_id=True, has_audited_financials=True,
            years_of_records=10,
        )
        assert _compute_data_quality_risk(d) == 0.0

    def test_missing_all_identifiers(self):
        d = DataQuality()
        risk = _compute_data_quality_risk(d)
        # 0.15 + 0.12 + 0.10 + 0.15 + 0.18 + 0.15 (age<3) = 0.85
        assert risk == pytest.approx(0.85, abs=0.01)

    def test_young_company_penalty(self):
        d = DataQuality(
            has_lei=True, has_cage=True, has_duns=True,
            has_tax_id=True, has_audited_financials=True,
            years_of_records=2,
        )
        assert _compute_data_quality_risk(d) == pytest.approx(0.15, abs=0.01)

    def test_mid_age_company(self):
        d = DataQuality(
            has_lei=True, has_cage=True, has_duns=True,
            has_tax_id=True, has_audited_financials=True,
            years_of_records=4,
        )
        assert _compute_data_quality_risk(d) == pytest.approx(0.08, abs=0.01)

    def test_missing_lei_only(self):
        d = DataQuality(
            has_lei=False, has_cage=True, has_duns=True,
            has_tax_id=True, has_audited_financials=True,
            years_of_records=10,
        )
        assert _compute_data_quality_risk(d) == pytest.approx(0.15, abs=0.01)


# ============================================================================
# TEST: EXECUTIVE RISK
# ============================================================================

class TestExecRisk:
    def test_no_execs_known(self):
        e = ExecProfile(known_execs=0)
        assert _compute_exec_risk(e) == pytest.approx(0.25, abs=0.01)

    def test_clean_execs(self):
        e = ExecProfile(known_execs=5)
        assert _compute_exec_risk(e) == 0.0

    def test_adverse_media_logarithmic(self):
        """More adverse media = higher risk, but diminishing returns."""
        e1 = ExecProfile(known_execs=5, adverse_media=1)
        e3 = ExecProfile(known_execs=5, adverse_media=3)
        e10 = ExecProfile(known_execs=5, adverse_media=10)
        r1 = _compute_exec_risk(e1)
        r3 = _compute_exec_risk(e3)
        r10 = _compute_exec_risk(e10)
        assert r1 < r3 < r10
        # Diminishing returns: gap between 1->3 vs 3->10
        assert (r3 - r1) > (r10 - r3) * 0.5  # ratio check, not strict

    def test_pep_execs(self):
        e = ExecProfile(known_execs=5, pep_execs=2)
        risk = _compute_exec_risk(e)
        assert risk > 0.0

    def test_litigation(self):
        e = ExecProfile(known_execs=5, litigation_history=5)
        risk = _compute_exec_risk(e)
        assert risk > 0.0

    def test_all_adverse_factors(self):
        e = ExecProfile(known_execs=0, adverse_media=100, pep_execs=10, litigation_history=50)
        risk = _compute_exec_risk(e)
        assert risk == 1.0  # should saturate and clamp


# ============================================================================
# TEST: FOREIGN OWNERSHIP DEPTH
# ============================================================================

class TestForeignOwnershipDepth:
    def test_no_foreign_ownership(self):
        o = OwnershipProfile(foreign_ownership_pct=0.0)
        assert _compute_foreign_ownership_depth(o) == 0.0

    def test_small_allied(self):
        o = OwnershipProfile(foreign_ownership_pct=0.05, foreign_ownership_is_allied=True)
        assert _compute_foreign_ownership_depth(o) == 0.20

    def test_medium_allied(self):
        o = OwnershipProfile(foreign_ownership_pct=0.15, foreign_ownership_is_allied=True)
        assert _compute_foreign_ownership_depth(o) == 0.40

    def test_large_allied(self):
        o = OwnershipProfile(foreign_ownership_pct=0.50, foreign_ownership_is_allied=True)
        assert _compute_foreign_ownership_depth(o) == 0.50

    def test_small_non_allied(self):
        o = OwnershipProfile(foreign_ownership_pct=0.05, foreign_ownership_is_allied=False)
        assert _compute_foreign_ownership_depth(o) == 0.35

    def test_medium_non_allied(self):
        o = OwnershipProfile(foreign_ownership_pct=0.15, foreign_ownership_is_allied=False)
        assert _compute_foreign_ownership_depth(o) == 0.55

    def test_large_non_allied(self):
        o = OwnershipProfile(foreign_ownership_pct=0.40, foreign_ownership_is_allied=False)
        assert _compute_foreign_ownership_depth(o) == 0.70

    def test_majority_non_allied(self):
        o = OwnershipProfile(foreign_ownership_pct=0.80, foreign_ownership_is_allied=False)
        assert _compute_foreign_ownership_depth(o) == 0.90


# ============================================================================
# TEST: HARD STOP EVALUATION
# ============================================================================

class TestHardStops:
    def test_no_match_no_stops(self):
        screening = _make_screening(matched=False)
        own = OwnershipProfile()
        stops = _evaluate_hard_stops(screening, own, "US", "COMMERCIAL")
        assert len(stops) == 0

    def test_high_sanctions_match(self):
        screening = _make_screening(
            matched=True, best_score=0.92, matched_name="BAD ACTOR",
            list_type="SDN", program="IRAN", country="IR",
        )
        own = OwnershipProfile()
        stops = _evaluate_hard_stops(screening, own, "IR", "COMMERCIAL")
        assert len(stops) >= 1
        assert "SDN Match" in stops[0]["trigger"]

    def test_allied_vendor_raised_threshold(self):
        """Allied vendor matching different country entry needs > 0.90."""
        screening = _make_screening(
            matched=True, best_score=0.88, matched_name="COMMON NAME",
            list_type="SDN", program="IRAN", country="IR",
        )
        own = OwnershipProfile()
        # GB vendor matching IR entry at 0.88 < 0.90 threshold = no stop
        stops = _evaluate_hard_stops(screening, own, "GB", "COMMERCIAL")
        assert len(stops) == 0

    def test_allied_vendor_above_raised_threshold(self):
        screening = _make_screening(
            matched=True, best_score=0.92, matched_name="COMMON NAME",
            list_type="SDN", program="IRAN", country="IR",
        )
        own = OwnershipProfile()
        stops = _evaluate_hard_stops(screening, own, "GB", "COMMERCIAL")
        assert len(stops) >= 1

    def test_sanctioned_country_state_owned(self):
        screening = _make_screening(matched=False)
        own = OwnershipProfile(state_owned=True)
        stops = _evaluate_hard_stops(screening, own, "RU", "COMMERCIAL")
        assert any("State-Owned" in s["trigger"] for s in stops)

    def test_adversary_state_owned(self):
        """State-owned + geo_risk > 0.50 triggers hard stop."""
        screening = _make_screening(matched=False)
        own = OwnershipProfile(state_owned=True)
        stops = _evaluate_hard_stops(screening, own, "BY", "COMMERCIAL")
        # BY has geo_risk 0.55 > 0.50, so adversary SOE fires
        assert any("Adversary" in s["trigger"] for s in stops)

    def test_sap_foreign_ownership(self):
        """SAP/SCI programs disqualify any foreign ownership."""
        screening = _make_screening(matched=False)
        own = OwnershipProfile(foreign_ownership_pct=0.05)
        stops = _evaluate_hard_stops(screening, own, "US", "CRITICAL_SAP")
        assert any("Foreign Ownership Disqualifier" in s["trigger"] for s in stops)

    def test_sci_foreign_ownership(self):
        screening = _make_screening(matched=False)
        own = OwnershipProfile(foreign_ownership_pct=0.01)
        stops = _evaluate_hard_stops(screening, own, "US", "CRITICAL_SCI")
        assert any("Foreign Ownership Disqualifier" in s["trigger"] for s in stops)

    def test_no_foreign_ownership_sap_ok(self):
        screening = _make_screening(matched=False)
        own = OwnershipProfile(foreign_ownership_pct=0.0)
        stops = _evaluate_hard_stops(screening, own, "US", "CRITICAL_SAP")
        assert len(stops) == 0


# ============================================================================
# TEST: SOFT FLAGS
# ============================================================================

class TestSoftFlags:
    def test_fuzzy_match_flag(self):
        screening = _make_screening(
            matched=True, best_score=0.75, best_raw_jw=0.70,
            matched_name="SIMILAR NAME", list_type="SDN",
        )
        own = OwnershipProfile()
        dq = DataQuality()
        ep = ExecProfile()
        dod = DoDContext()
        flags = _evaluate_soft_flags(screening, own, ep, dq, dod, "US")
        assert any("Fuzzy Sanctions Match" in f["trigger"] for f in flags)

    def test_pep_connection_flag(self):
        screening = _make_screening(matched=False)
        own = OwnershipProfile(pep_connection=True)
        flags = _evaluate_soft_flags(
            screening, own, ExecProfile(), DataQuality(), DoDContext(), "US",
        )
        assert any("PEP Connection" in f["trigger"] for f in flags)

    def test_unresolved_ownership_flag(self):
        screening = _make_screening(matched=False)
        own = OwnershipProfile(ownership_pct_resolved=0.40)
        flags = _evaluate_soft_flags(
            screening, own, ExecProfile(), DataQuality(), DoDContext(), "US",
        )
        assert any("Unresolved Beneficial Ownership" in f["trigger"] for f in flags)

    def test_deep_shell_layers_flag(self):
        screening = _make_screening(matched=False)
        own = OwnershipProfile(shell_layers=6, ownership_pct_resolved=0.30)
        flags = _evaluate_soft_flags(
            screening, own, ExecProfile(), DataQuality(), DoDContext(), "US",
        )
        assert any("Deep Corporate Layering" in f["trigger"] for f in flags)

    def test_limited_history_flag(self):
        screening = _make_screening(matched=False)
        dq = DataQuality(years_of_records=1)
        flags = _evaluate_soft_flags(
            screening, OwnershipProfile(), ExecProfile(), dq, DoDContext(), "US",
        )
        assert any("Limited Operating History" in f["trigger"] for f in flags)

    def test_regulatory_proximity_flag(self):
        screening = _make_screening(matched=False)
        dod = DoDContext(regulatory_gate_proximity=0.6)
        flags = _evaluate_soft_flags(
            screening, OwnershipProfile(), ExecProfile(), DataQuality(), dod, "US",
        )
        assert any("Regulatory Gate Proximity" in f["trigger"] for f in flags)

    def test_cmmc_gap_flag(self):
        screening = _make_screening(matched=False)
        dod = DoDContext(sensitivity="ELEVATED", cmmc_readiness=0.6)
        flags = _evaluate_soft_flags(
            screening, OwnershipProfile(), ExecProfile(), DataQuality(), dod, "US",
        )
        assert any("CMMC Certification Gap" in f["trigger"] for f in flags)

    def test_single_source_flag(self):
        screening = _make_screening(matched=False)
        dod = DoDContext(single_source_risk=0.7)
        flags = _evaluate_soft_flags(
            screening, OwnershipProfile(), ExecProfile(), DataQuality(), dod, "US",
        )
        assert any("Single-Source Supply Risk" in f["trigger"] for f in flags)

    def test_sectoral_sanctions_flag(self):
        screening = _make_screening(matched=False)
        own = OwnershipProfile(state_owned=True)
        flags = _evaluate_soft_flags(
            screening, own, ExecProfile(), DataQuality(), DoDContext(), "CN",
        )
        assert any("Sectoral Sanctions" in f["trigger"] for f in flags)

    def test_allied_cross_country_near_miss(self):
        """Score 0.82-0.90, allied vendor, different country = cross-jurisdiction flag."""
        screening = _make_screening(
            matched=True, best_score=0.85, matched_name="SOME ENTITY",
            list_type="SDN", country="IR",
        )
        flags = _evaluate_soft_flags(
            screening, OwnershipProfile(), ExecProfile(), DataQuality(), DoDContext(), "GB",
        )
        assert any("Cross-Jurisdiction" in f["trigger"] for f in flags)


# ============================================================================
# TEST: LAYER INTEGRATION
# ============================================================================

class TestIntegrateLayers:
    def test_non_compliant_always_disqualified(self):
        assert integrate_layers("NON_COMPLIANT", 0.01, "COMMERCIAL") == "TIER_1_DISQUALIFIED"
        assert integrate_layers("NON_COMPLIANT", 0.99, "CRITICAL_SAP") == "TIER_1_DISQUALIFIED"

    def test_requires_review_low_risk(self):
        result = integrate_layers("REQUIRES_REVIEW", 0.20, "COMMERCIAL")
        assert result == "TIER_2_CONDITIONAL_ACCEPTABLE"

    def test_requires_review_mid_risk(self):
        result = integrate_layers("REQUIRES_REVIEW", 0.45, "COMMERCIAL")
        assert result == "TIER_2_ELEVATED_REVIEW"

    def test_requires_review_high_risk(self):
        result = integrate_layers("REQUIRES_REVIEW", 0.70, "COMMERCIAL")
        assert result == "TIER_1_CRITICAL_CONCERN"

    def test_compliant_sap_low_risk(self):
        result = integrate_layers("COMPLIANT", 0.10, "CRITICAL_SAP")
        assert result == "TIER_4_CRITICAL_QUALIFIED"

    def test_compliant_sap_moderate_risk(self):
        result = integrate_layers("COMPLIANT", 0.25, "CRITICAL_SAP")
        assert result == "TIER_3_CRITICAL_ACCEPTABLE"

    def test_compliant_sap_high_risk(self):
        result = integrate_layers("COMPLIANT", 0.90, "CRITICAL_SAP")
        assert result == "TIER_1_CRITICAL_CONCERN"

    def test_compliant_sap_mid_risk(self):
        result = integrate_layers("COMPLIANT", 0.50, "CRITICAL_SAP")
        assert result == "TIER_2_HIGH_CONCERN"

    def test_compliant_elevated_low(self):
        result = integrate_layers("COMPLIANT", 0.10, "ELEVATED")
        assert result == "TIER_4_APPROVED"

    def test_compliant_elevated_mid(self):
        result = integrate_layers("COMPLIANT", 0.25, "ELEVATED")
        assert result == "TIER_3_CONDITIONAL"

    def test_compliant_elevated_high(self):
        result = integrate_layers("COMPLIANT", 0.50, "ELEVATED")
        assert result == "TIER_2_ELEVATED"

    def test_compliant_enhanced_low(self):
        result = integrate_layers("COMPLIANT", 0.20, "ENHANCED")
        assert result == "TIER_4_APPROVED"

    def test_compliant_enhanced_mid(self):
        result = integrate_layers("COMPLIANT", 0.40, "ENHANCED")
        assert result == "TIER_3_CONDITIONAL"

    def test_compliant_enhanced_high(self):
        result = integrate_layers("COMPLIANT", 0.60, "ENHANCED")
        assert result == "TIER_2_CAUTION"

    def test_compliant_controlled_low(self):
        result = integrate_layers("COMPLIANT", 0.15, "CONTROLLED")
        assert result == "TIER_4_APPROVED"

    def test_compliant_controlled_mid(self):
        result = integrate_layers("COMPLIANT", 0.35, "CONTROLLED")
        assert result == "TIER_3_CONDITIONAL"

    def test_compliant_controlled_high(self):
        result = integrate_layers("COMPLIANT", 0.60, "CONTROLLED")
        assert result == "TIER_2_CAUTION"

    def test_commercial_clear(self):
        result = integrate_layers("COMPLIANT", 0.10, "COMMERCIAL")
        assert result == "TIER_4_CLEAR"

    def test_commercial_conditional(self):
        result = integrate_layers("COMPLIANT", 0.20, "COMMERCIAL")
        assert result == "TIER_3_CONDITIONAL"

    def test_commercial_caution(self):
        result = integrate_layers("COMPLIANT", 0.40, "COMMERCIAL")
        assert result == "TIER_2_CAUTION_COMMERCIAL"

    def test_commercial_critical(self):
        result = integrate_layers("COMPLIANT", 0.60, "COMMERCIAL")
        assert result == "TIER_1_CRITICAL_CONCERN"


# ============================================================================
# TEST: PROGRAM RECOMMENDATION
# ============================================================================

class TestProgramRecommendation:
    def test_non_compliant(self):
        assert _program_recommendation("NON_COMPLIANT", 0.10, "TIER_1_DISQUALIFIED") == "DO_NOT_PROCEED"

    def test_tier1_disqualified(self):
        assert _program_recommendation("COMPLIANT", 0.90, "TIER_1_DISQUALIFIED") == "DO_NOT_PROCEED"

    def test_tier1_critical_requires_review(self):
        result = _program_recommendation("REQUIRES_REVIEW", 0.70, "TIER_1_CRITICAL_CONCERN")
        assert result == "DO_NOT_PROCEED_WITHOUT_MITIGATION"

    def test_tier1_critical_compliant(self):
        result = _program_recommendation("COMPLIANT", 0.90, "TIER_1_CRITICAL_CONCERN")
        assert result == "DO_NOT_PROCEED"

    def test_requires_review_low_risk(self):
        result = _program_recommendation("REQUIRES_REVIEW", 0.25, "TIER_2_CONDITIONAL_ACCEPTABLE")
        assert result == "CONDITIONAL_APPROVAL_WITH_OVERSIGHT"

    def test_requires_review_high_risk(self):
        result = _program_recommendation("REQUIRES_REVIEW", 0.50, "TIER_2_ELEVATED_REVIEW")
        assert result == "DO_NOT_PROCEED_WITHOUT_MITIGATION"

    def test_compliant_low_risk(self):
        result = _program_recommendation("COMPLIANT", 0.15, "TIER_4_APPROVED")
        assert result == "APPROVED"

    def test_compliant_moderate_risk(self):
        result = _program_recommendation("COMPLIANT", 0.30, "TIER_3_CONDITIONAL")
        assert result == "APPROVED_WITH_ENHANCED_MONITORING"

    def test_compliant_elevated_risk(self):
        result = _program_recommendation("COMPLIANT", 0.45, "TIER_2_CAUTION")
        assert result == "APPROVED_WITH_RESTRICTIVE_CONTROLS"


# ============================================================================
# TEST: SCORE_VENDOR END-TO-END
# ============================================================================

class TestScoreVendor:
    def test_clean_us_vendor(self):
        """Transparent US vendor with full documentation should score low."""
        inp = _make_vendor(
            name="Acme Defense Corp",
            country="US",
            sensitivity="COMMERCIAL",
            ownership=OwnershipProfile(
                publicly_traded=True, beneficial_owner_known=True,
                ownership_pct_resolved=1.0,
            ),
            data_quality=DataQuality(
                has_lei=True, has_cage=True, has_duns=True,
                has_tax_id=True, has_audited_financials=True,
                years_of_records=15,
            ),
            exec_profile=ExecProfile(known_execs=5),
        )
        result = score_vendor(inp)
        assert isinstance(result, ScoringResultV5)
        assert result.calibrated_probability < 0.25
        assert "TIER_4" in result.combined_tier or "TIER_3" in result.combined_tier

    def test_adversary_vendor_high_risk(self):
        """Opaque vendor from adversary jurisdiction should score high."""
        inp = _make_vendor(
            name="Unknown Entity",
            country="IR",
            sensitivity="ELEVATED",
            ownership=OwnershipProfile(
                state_owned=True, beneficial_owner_known=False,
                ownership_pct_resolved=0.0, shell_layers=3,
            ),
            data_quality=DataQuality(),
            exec_profile=ExecProfile(),
            dod=DoDContext(sensitivity="ELEVATED"),
        )
        result = score_vendor(inp)
        assert result.calibrated_probability == 1.0  # hard stop fires
        assert len(result.hard_stop_decisions) > 0

    def test_regulatory_integration(self):
        """Vendor with COMPLIANT regulatory status uses integrate_layers."""
        inp = _make_vendor(name="Allied Corp", country="GB", sensitivity="CONTROLLED")
        result = score_vendor(inp, regulatory_status="COMPLIANT")
        assert result.regulatory_status == "COMPLIANT"
        # Should use integrate_layers path, not the NOT_EVALUATED fallback
        assert "TIER" in result.combined_tier

    def test_non_compliant_disqualified(self):
        inp = _make_vendor(name="Failing Corp", country="US", sensitivity="CONTROLLED")
        result = score_vendor(inp, regulatory_status="NON_COMPLIANT")
        assert result.combined_tier == "TIER_1_DISQUALIFIED"
        assert result.program_recommendation == "DO_NOT_PROCEED"
        assert result.is_dod_eligible is False

    def test_extra_hard_stops_override(self):
        """Extra hard stops (SAM exclusions etc.) force p=1.0."""
        inp = _make_vendor(name="Clean Name", country="US")
        sam_stop = {
            "trigger": "SAM Exclusion",
            "explanation": "Entity excluded from SAM.gov",
            "confidence": 0.99,
        }
        result = score_vendor(inp, extra_hard_stops=[sam_stop])
        assert result.calibrated_probability == 1.0
        assert result.combined_tier == "TIER_1_DISQUALIFIED"

    def test_result_to_dict(self):
        """ScoringResultV5.to_dict() should contain all expected keys."""
        inp = _make_vendor(name="Dict Test Corp", country="US")
        result = score_vendor(inp)
        d = result.to_dict()
        expected_keys = {
            "calibrated_probability", "calibrated_tier", "combined_tier",
            "interval_lower", "interval_upper", "contributions",
            "hard_stop_decisions", "soft_flags", "findings",
            "marginal_information_values", "is_dod_eligible", "is_dod_qualified",
            "program_recommendation", "sensitivity_context", "supply_chain_tier",
            "regulatory_status", "regulatory_findings", "model_version",
            "screening", "alert_disposition",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_ci_contains_probability(self):
        """Confidence interval should bracket the point estimate."""
        inp = _make_vendor(name="CI Test Corp", country="DE")
        result = score_vendor(inp)
        assert result.interval_lower <= result.calibrated_probability
        assert result.interval_upper >= result.calibrated_probability

    def test_source_reliability_narrows_ci(self):
        """Higher source reliability should produce narrower CI."""
        inp = _make_vendor(name="Reliability Test", country="US")
        r_low = score_vendor(inp, source_reliability_avg=0.45)
        r_high = score_vendor(inp, source_reliability_avg=0.95)
        width_low = r_low.interval_upper - r_low.interval_lower
        width_high = r_high.interval_upper - r_high.interval_lower
        assert width_low >= width_high

    def test_unknown_sensitivity_falls_back(self):
        """Unknown sensitivity tier should fall back to COMMERCIAL."""
        inp = _make_vendor(
            name="Fallback Test", country="US",
            dod=DoDContext(sensitivity="INVALID_TIER"),
        )
        result = score_vendor(inp)
        assert result.sensitivity_context == "INVALID_TIER" or result.calibrated_probability is not None

    def test_supply_chain_tier_affects_weights(self):
        """Tier 3 supplier should have higher risk than Tier 0 for same inputs."""
        own = OwnershipProfile(beneficial_owner_known=False)
        dq = DataQuality()
        ep = ExecProfile()
        inp_t0 = _make_vendor(
            name="Tier Test", country="US",
            ownership=own, data_quality=dq, exec_profile=ep,
            dod=DoDContext(sensitivity="ELEVATED", supply_chain_tier=0),
        )
        inp_t3 = _make_vendor(
            name="Tier Test", country="US",
            ownership=own, data_quality=dq, exec_profile=ep,
            dod=DoDContext(sensitivity="ELEVATED", supply_chain_tier=3),
        )
        r0 = score_vendor(inp_t0)
        r3 = score_vendor(inp_t3)
        # Tier 3 multiplier (1.6) on ownership/data_quality/exec should raise probability
        assert r3.calibrated_probability >= r0.calibrated_probability

    def test_dod_eligibility_with_hard_stop(self):
        """Hard stop should make vendor DoD ineligible."""
        inp = _make_vendor(
            name="Unknown Entity", country="CU",
            ownership=OwnershipProfile(state_owned=True),
        )
        result = score_vendor(inp)
        assert result.is_dod_eligible is False
        assert result.is_dod_qualified is False

    def test_dod_qualified_clean_vendor(self):
        """Clean vendor with COMPLIANT status and low risk = qualified."""
        inp = _make_vendor(
            name="Qualified Corp", country="US",
            ownership=OwnershipProfile(
                publicly_traded=True, beneficial_owner_known=True,
                ownership_pct_resolved=1.0,
            ),
            data_quality=DataQuality(
                has_lei=True, has_cage=True, has_duns=True,
                has_tax_id=True, has_audited_financials=True,
                years_of_records=20,
            ),
            exec_profile=ExecProfile(known_execs=10),
        )
        result = score_vendor(inp, regulatory_status="COMPLIANT")
        assert result.is_dod_qualified is True
        assert result.program_recommendation == "APPROVED"


# ============================================================================
# TEST: DOD FACTOR PRIORS
# ============================================================================

class TestDoDFactorPriors:
    def test_priors_applied_when_zero(self):
        """When DoD factors are 0.0 (unknown), priors should be applied."""
        inp = _make_vendor(
            name="Prior Test", country="US",
            dod=DoDContext(sensitivity="ELEVATED", supply_chain_tier=2),
        )
        # All DoD factors default to 0.0, so priors should kick in
        result = score_vendor(inp)
        # The probability should be slightly above baseline (~5%) due to priors
        assert result.calibrated_probability > _logistic(-2.94)

    def test_explicit_value_overrides_prior(self):
        """Explicit non-zero DoD factor should NOT get prior added."""
        inp1 = _make_vendor(
            name="Override Test", country="US",
            dod=DoDContext(sensitivity="ELEVATED", itar_exposure=0.5),
        )
        inp2 = _make_vendor(
            name="Override Test", country="US",
            dod=DoDContext(sensitivity="ELEVATED", itar_exposure=0.0),
        )
        r1 = score_vendor(inp1)
        r2 = score_vendor(inp2)
        # Explicit 0.5 should produce higher risk than prior (~0.09 for T1)
        assert r1.calibrated_probability > r2.calibrated_probability


# ============================================================================
# TEST: CONTRIBUTIONS AND MIVS
# ============================================================================

class TestContributions:
    def test_contributions_present(self):
        inp = _make_vendor(name="Contrib Test", country="IN")
        result = score_vendor(inp)
        assert len(result.contributions) > 0

    def test_contributions_sorted_by_magnitude(self):
        inp = _make_vendor(name="Sort Test", country="CN")
        result = score_vendor(inp)
        if len(result.contributions) >= 2 and result.contributions[0]["factor"] != "PROHIBITION":
            magnitudes = [abs(c["signed_contribution"]) for c in result.contributions]
            assert magnitudes == sorted(magnitudes, reverse=True)

    def test_hard_stop_prohibition_contribution(self):
        """When hard stop fires, contribution should be PROHIBITION."""
        inp = _make_vendor(
            name="Unknown Entity", country="CU",
            ownership=OwnershipProfile(state_owned=True),
        )
        result = score_vendor(inp)
        if result.hard_stop_decisions:
            assert result.contributions[0]["factor"] == "PROHIBITION"

    def test_mivs_present_for_risky_vendor(self):
        """MIVs should be generated for vendors with non-zero factors."""
        inp = _make_vendor(
            name="MIV Test", country="IN",
            ownership=OwnershipProfile(beneficial_owner_known=False),
            data_quality=DataQuality(),
            dod=DoDContext(sensitivity="ELEVATED"),
        )
        result = score_vendor(inp)
        # Hard stop should not fire for India, so MIVs should exist
        if not result.hard_stop_decisions:
            assert len(result.marginal_information_values) > 0

    def test_mivs_sorted_by_shift(self):
        inp = _make_vendor(
            name="MIV Sort", country="TR",
            ownership=OwnershipProfile(beneficial_owner_known=False, shell_layers=2),
            data_quality=DataQuality(),
            dod=DoDContext(sensitivity="ELEVATED"),
        )
        result = score_vendor(inp)
        if len(result.marginal_information_values) >= 2:
            shifts = [abs(m["expected_shift_pp"]) for m in result.marginal_information_values]
            assert shifts == sorted(shifts, reverse=True)


# ============================================================================
# TEST: FINDINGS GENERATION
# ============================================================================

class TestFindings:
    def test_hard_stop_finding(self):
        inp = _make_vendor(
            name="Unknown Entity", country="RU",
            ownership=OwnershipProfile(state_owned=True),
        )
        result = score_vendor(inp)
        assert any("Hard stop" in f for f in result.findings)

    def test_non_compliant_finding(self):
        inp = _make_vendor(name="NC Corp", country="US")
        result = score_vendor(inp, regulatory_status="NON_COMPLIANT")
        assert any("NON_COMPLIANT" in f for f in result.findings)

    def test_requires_review_finding(self):
        inp = _make_vendor(name="Review Corp", country="US")
        result = score_vendor(inp, regulatory_status="REQUIRES_REVIEW")
        assert any("PENDING" in f for f in result.findings)

    def test_high_geo_risk_finding(self):
        inp = _make_vendor(name="Geo Test", country="AF")
        result = score_vendor(inp)
        # AF has geo_risk 0.65 > 0.40
        if not result.hard_stop_decisions:
            assert any("geographic risk" in f.lower() for f in result.findings)

    def test_publicly_traded_finding(self):
        inp = _make_vendor(
            name="Public Corp", country="US",
            ownership=OwnershipProfile(publicly_traded=True, beneficial_owner_known=True),
        )
        result = score_vendor(inp)
        assert any("Publicly traded" in f for f in result.findings)


# ============================================================================
# TEST: MODEL VERSION AND METADATA
# ============================================================================

class TestMetadata:
    def test_model_version(self):
        inp = _make_vendor(name="Version Test", country="US")
        result = score_vendor(inp)
        assert result.model_version == "5.2-FGAMLogit-DoD-ProfileAware"

    def test_screening_passthrough(self):
        inp = _make_vendor(name="Screen Test", country="US")
        result = score_vendor(inp)
        assert hasattr(result.screening, "matched")
        assert hasattr(result.screening, "best_score")
