"""
Xiphos v5.0 scoring engine tests -- validates FGAMLogit math,
geo risk lookups, ownership risk calculations, tier integration,
and sensitivity-aware scoring surface.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from fgamlogit import (
    geo_risk, OwnershipProfile, DataQuality, ExecProfile, DoDContext,
    VendorInputV5, score_vendor, integrate_layers,
    _compute_ownership_risk, _compute_data_quality_risk, _compute_exec_risk,
    _logistic, _wilson_ci, BASELINE_LOGODDS, FACTOR_WEIGHTS, SENSITIVITY_TIERS,
)


class TestGeoRisk:
    def test_known_country(self):
        assert geo_risk("US") == 0.02

    def test_high_risk_country(self):
        assert geo_risk("KP") == 0.98

    def test_unknown_country_defaults(self):
        assert geo_risk("XX") == 0.30

    def test_case_insensitive(self):
        assert geo_risk("us") == geo_risk("US")


class TestOwnershipRisk:
    def test_clean_profile(self):
        o = OwnershipProfile(
            publicly_traded=True,
            beneficial_owner_known=True,
            ownership_pct_resolved=1.0,
        )
        score = _compute_ownership_risk(o)
        assert score == 0.0, f"Clean profile should be 0, got {score}"

    def test_state_owned(self):
        o = OwnershipProfile(state_owned=True)
        score = _compute_ownership_risk(o)
        assert score >= 0.30

    def test_shell_layers_capped(self):
        o = OwnershipProfile(shell_layers=10)
        score = _compute_ownership_risk(o)
        assert score <= 1.0

    def test_pep_connection(self):
        o = OwnershipProfile(pep_connection=True)
        score = _compute_ownership_risk(o)
        assert score >= 0.15

    def test_score_bounded(self):
        o = OwnershipProfile(
            state_owned=True,
            pep_connection=True,
            shell_layers=5,
        )
        score = _compute_ownership_risk(o)
        assert 0.0 <= score <= 1.0


class TestFGAMLogitMath:
    def test_logistic_zero(self):
        assert _logistic(0.0) == 0.5

    def test_logistic_large_positive(self):
        assert _logistic(100.0) > 0.999

    def test_logistic_large_negative(self):
        assert _logistic(-100.0) < 0.001

    def test_wilson_ci_bounds(self):
        lo, hi = _wilson_ci(0.5, 100.0)
        assert 0.0 <= lo < 0.5
        assert 0.5 < hi <= 1.0

    def test_wilson_ci_narrow_with_large_n(self):
        lo1, hi1 = _wilson_ci(0.5, 10.0)
        lo2, hi2 = _wilson_ci(0.5, 1000.0)
        assert (hi2 - lo2) < (hi1 - lo1)


class TestSensitivitySurface:
    """Verify that higher sensitivity tiers produce higher baseline risk."""
    def test_baseline_ordering(self):
        # SAP should have highest baseline, COMMERCIAL lowest
        assert BASELINE_LOGODDS["SAP"] > BASELINE_LOGODDS["SCI"]
        assert BASELINE_LOGODDS["SCI"] > BASELINE_LOGODDS["TOP_SECRET"]
        assert BASELINE_LOGODDS["TOP_SECRET"] > BASELINE_LOGODDS["SECRET"]
        assert BASELINE_LOGODDS["SECRET"] > BASELINE_LOGODDS["CUI"]
        assert BASELINE_LOGODDS["CUI"] > BASELINE_LOGODDS["COMMERCIAL"]

    def test_commercial_and_unclassified_equal(self):
        assert BASELINE_LOGODDS["COMMERCIAL"] == BASELINE_LOGODDS["UNCLASSIFIED"]

    def test_all_14_factors_have_weights(self):
        for sens in SENSITIVITY_TIERS:
            for factor_name, weights in FACTOR_WEIGHTS.items():
                assert sens in weights, f"Missing weight for {factor_name} at {sens}"


class TestLayerIntegration:
    def test_non_compliant_always_disqualified(self):
        for p in [0.01, 0.25, 0.50, 0.90]:
            tier = integrate_layers("NON_COMPLIANT", p, "COMMERCIAL")
            assert tier == "TIER_1_DISQUALIFIED"

    def test_compliant_low_risk_clears(self):
        tier = integrate_layers("COMPLIANT", 0.10, "COMMERCIAL")
        assert tier == "TIER_4_CLEAR"

    def test_requires_review_low_risk(self):
        tier = integrate_layers("REQUIRES_REVIEW", 0.20, "SECRET")
        assert tier == "TIER_2_CONDITIONAL_ACCEPTABLE"

    def test_requires_review_high_risk(self):
        tier = integrate_layers("REQUIRES_REVIEW", 0.70, "SECRET")
        assert tier == "TIER_1_CRITICAL_CONCERN"

    def test_sap_compliant_low_risk(self):
        tier = integrate_layers("COMPLIANT", 0.15, "SAP")
        assert tier == "TIER_4_SAP_QUALIFIED"

    def test_sap_compliant_high_risk(self):
        tier = integrate_layers("COMPLIANT", 0.50, "SAP")
        assert tier == "TIER_2_ELEVATED_CONCERN"
