"""
Xiphos scoring engine tests -- validates Bayesian scoring math,
geo risk lookups, and ownership risk calculations.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from scoring import geo_risk, ownership_risk, OwnershipProfile


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
        score = ownership_risk(o)
        assert score == 0.0, f"Clean profile should be 0, got {score}"

    def test_state_owned(self):
        o = OwnershipProfile(state_owned=True)
        score = ownership_risk(o)
        assert score >= 0.30

    def test_shell_layers_capped(self):
        o = OwnershipProfile(shell_layers=10)
        score = ownership_risk(o)
        # shell layers capped at 0.30 + unknown beneficial owner 0.25 + unresolved 0.20
        assert score <= 1.0

    def test_pep_connection(self):
        o = OwnershipProfile(pep_connection=True)
        score = ownership_risk(o)
        assert score >= 0.15

    def test_score_bounded(self):
        o = OwnershipProfile(
            state_owned=True,
            pep_connection=True,
            shell_layers=5,
        )
        score = ownership_risk(o)
        assert 0.0 <= score <= 1.0
