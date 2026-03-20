"""
Xiphos v5.0 scoring engine tests -- validates FGAMLogit math,
geo risk lookups, ownership risk calculations, tier integration,
and sensitivity-aware scoring surface.

Sensitivity tiers use Xiphos program scrutiny labels (not classification markings):
  CRITICAL_SAP, CRITICAL_SCI, ELEVATED, ENHANCED, CONTROLLED, STANDARD, COMMERCIAL
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
    """Verify sensitivity tiers use Xiphos labels (not classification markings)."""
    def test_no_classification_markings(self):
        """Ensure no actual classification terms appear in the tier names."""
        for tier in SENSITIVITY_TIERS:
            assert "TOP_SECRET" not in tier
            assert "SECRET" not in tier or "ENHANCED" in tier  # ENHANCED replaced SECRET
            assert "SCI" not in tier or "CRITICAL_SCI" in tier  # wrapped in CRITICAL_
            assert "SAP" not in tier or "CRITICAL_SAP" in tier

    def test_uniform_baselines(self):
        """All baselines are uniform. Sensitivity differentiation comes from weights, not baseline."""
        base = BASELINE_LOGODDS["COMMERCIAL"]
        for sens in SENSITIVITY_TIERS:
            assert BASELINE_LOGODDS[sens] == base, f"{sens} baseline should equal COMMERCIAL"

    def test_weight_differentiation(self):
        """Higher sensitivity tiers should have higher weights on key factors."""
        # Ownership weight at CRITICAL_SAP (3.0) > COMMERCIAL (0.8)
        assert FACTOR_WEIGHTS["ownership"]["CRITICAL_SAP"] > FACTOR_WEIGHTS["ownership"]["COMMERCIAL"]
        # ITAR weight at ELEVATED (2.0) > COMMERCIAL (0.0)
        assert FACTOR_WEIGHTS["itar_exposure"]["ELEVATED"] > FACTOR_WEIGHTS["itar_exposure"]["COMMERCIAL"]

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
        tier = integrate_layers("REQUIRES_REVIEW", 0.20, "ENHANCED")
        assert tier == "TIER_2_CONDITIONAL_ACCEPTABLE"

    def test_requires_review_high_risk(self):
        tier = integrate_layers("REQUIRES_REVIEW", 0.70, "ENHANCED")
        assert tier == "TIER_1_CRITICAL_CONCERN"

    def test_critical_compliant_low_risk(self):
        tier = integrate_layers("COMPLIANT", 0.15, "CRITICAL_SAP")
        assert tier == "TIER_4_CRITICAL_QUALIFIED"

    def test_critical_compliant_high_risk(self):
        tier = integrate_layers("COMPLIANT", 0.50, "CRITICAL_SAP")
        assert tier == "TIER_2_HIGH_CONCERN"

    def test_critical_extreme_risk_escalates_to_tier_1(self):
        tier = integrate_layers("COMPLIANT", 0.90, "CRITICAL_SAP")
        assert tier == "TIER_1_CRITICAL_CONCERN"

    def test_elevated_moderate_risk_requires_conditional_review(self):
        tier = integrate_layers("COMPLIANT", 0.17, "ELEVATED")
        assert tier == "TIER_3_CONDITIONAL"

    def test_controlled_moderate_risk_requires_conditional_review(self):
        tier = integrate_layers("COMPLIANT", 0.22, "CONTROLLED")
        assert tier == "TIER_3_CONDITIONAL"


class TestCalibrationRegression:
    def test_shell_layering_is_not_automatic_disqualification(self):
        inp = VendorInputV5(
            name="Global Trade Holdings Ltd",
            country="CN",
            ownership=OwnershipProfile(
                publicly_traded=False,
                state_owned=False,
                beneficial_owner_known=False,
                ownership_pct_resolved=0.25,
                shell_layers=5,
                pep_connection=False,
            ),
            data_quality=DataQuality(
                has_lei=False,
                has_cage=False,
                has_duns=False,
                has_tax_id=False,
                has_audited_financials=False,
                years_of_records=3,
            ),
            exec_profile=ExecProfile(
                known_execs=5,
                adverse_media=8,
                pep_execs=2,
                litigation_history=10,
            ),
            dod=DoDContext(sensitivity="ELEVATED", supply_chain_tier=0),
        )

        result = score_vendor(inp, regulatory_status="COMPLIANT")
        assert result.combined_tier == "TIER_2_ELEVATED"

    def test_moderate_elevated_case_no_longer_auto_clears(self):
        inp = VendorInputV5(
            name="Precision Manufacturing Inc",
            country="DE",
            ownership=OwnershipProfile(
                publicly_traded=False,
                state_owned=False,
                beneficial_owner_known=True,
                ownership_pct_resolved=0.75,
                shell_layers=2,
                pep_connection=False,
            ),
            data_quality=DataQuality(
                has_lei=True,
                has_cage=True,
                has_duns=True,
                has_tax_id=False,
                has_audited_financials=True,
                years_of_records=9,
            ),
            exec_profile=ExecProfile(
                known_execs=18,
                adverse_media=1,
                pep_execs=0,
                litigation_history=1,
            ),
            dod=DoDContext(sensitivity="ELEVATED", supply_chain_tier=0),
        )

        result = score_vendor(inp, regulatory_status="COMPLIANT")
        assert result.combined_tier == "TIER_3_CONDITIONAL"

    def test_moderate_controlled_case_no_longer_auto_clears(self):
        inp = VendorInputV5(
            name="OptiQuant Solutions GmbH",
            country="DE",
            ownership=OwnershipProfile(
                publicly_traded=False,
                state_owned=False,
                beneficial_owner_known=False,
                ownership_pct_resolved=0.50,
                shell_layers=2,
                pep_connection=False,
            ),
            data_quality=DataQuality(
                has_lei=False,
                has_cage=True,
                has_duns=False,
                has_tax_id=False,
                has_audited_financials=False,
                years_of_records=6,
            ),
            exec_profile=ExecProfile(
                known_execs=12,
                adverse_media=2,
                pep_execs=0,
                litigation_history=4,
            ),
            dod=DoDContext(sensitivity="CONTROLLED", supply_chain_tier=0),
        )

        result = score_vendor(inp, regulatory_status="COMPLIANT")
        assert result.combined_tier == "TIER_3_CONDITIONAL"
