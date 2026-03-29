"""
Test suite for OSINT enrichment pipeline integration with FGAMLogit scoring.

Tests the seam where OSINT enrichment results (extra_hard_stops from trade_csl,
SAM exclusions, UN sanctions) get injected between Layer 1 and Layer 2 scoring.

Hard stops are dicts with at minimum a "trigger" key. score_vendor() extends
internal hard stops with extra_hard_stops, forcing p=1.0 and TIER_1_DISQUALIFIED.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fgamlogit import (
    VendorInputV5, OwnershipProfile, DataQuality, ExecProfile, DoDContext,
    score_vendor,
)


# =============================================================================
# HELPERS
# =============================================================================

def _vendor(name="Clean Tech Corp", country="US", sensitivity="COMMERCIAL",
            state_owned=False, foreign_ownership_pct=0.0,
            foreign_ownership_is_allied=True, pep_connection=False,
            shell_layers=0, adverse_media=0):
    """Build a VendorInputV5 with sensible clean-vendor defaults."""
    return VendorInputV5(
        name=name, country=country,
        ownership=OwnershipProfile(
            publicly_traded=True, state_owned=state_owned,
            beneficial_owner_known=True, ownership_pct_resolved=1.0,
            shell_layers=shell_layers, pep_connection=pep_connection,
            foreign_ownership_pct=foreign_ownership_pct,
            foreign_ownership_is_allied=foreign_ownership_is_allied,
        ),
        data_quality=DataQuality(
            has_lei=True, has_cage=True, has_duns=True, has_tax_id=True,
            has_audited_financials=True, years_of_records=10,
        ),
        exec_profile=ExecProfile(
            known_execs=15, adverse_media=adverse_media,
            pep_execs=0, litigation_history=0,
        ),
        dod=DoDContext(sensitivity=sensitivity, supply_chain_tier=0),
    )


def _tier_level(tier_str: str) -> int:
    """Extract tier number: TIER_1_DISQUALIFIED -> 1, TIER_4_CLEAR -> 4."""
    for i in range(1, 5):
        if f"TIER_{i}" in tier_str:
            return i
    return 0


# =============================================================================
# TestExtraHardStopsMechanism
# =============================================================================

class TestExtraHardStopsMechanism:
    """Core mechanism: extra_hard_stops force TIER_1 and p=1.0."""

    def test_single_hard_stop_forces_tier1(self):
        result = score_vendor(
            _vendor(), regulatory_status="COMPLIANT",
            extra_hard_stops=[{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"
        assert result.calibrated_probability == 1.0

    def test_multiple_hard_stops_all_fire(self):
        result = score_vendor(
            _vendor(), regulatory_status="COMPLIANT",
            extra_hard_stops=[
                {"trigger": "SAM_EXCLUSION", "source": "SAM.gov"},
                {"trigger": "UN_SANCTIONS", "source": "UN.org"},
                {"trigger": "BIS_ENTITY_LIST", "source": "trade.gov/csl"},
            ],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"
        assert result.calibrated_probability == 1.0

    def test_hard_stop_overrides_compliant_status(self):
        """COMPLIANT regulatory status cannot save a vendor with a hard stop."""
        result = score_vendor(
            _vendor(), regulatory_status="COMPLIANT",
            extra_hard_stops=[{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
        )
        assert _tier_level(result.combined_tier) == 1

    def test_hard_stop_overrides_requires_review(self):
        """REQUIRES_REVIEW + hard stop still produces TIER_1."""
        result = score_vendor(
            _vendor(), regulatory_status="REQUIRES_REVIEW",
            extra_hard_stops=[{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"
        assert result.calibrated_probability == 1.0

    def test_no_hard_stops_no_effect(self):
        """Empty extra_hard_stops does not alter normal scoring."""
        result_empty = score_vendor(
            _vendor(), regulatory_status="COMPLIANT", extra_hard_stops=[],
        )
        result_none = score_vendor(
            _vendor(), regulatory_status="COMPLIANT", extra_hard_stops=None,
        )
        assert result_empty.combined_tier == result_none.combined_tier
        assert result_empty.calibrated_probability == result_none.calibrated_probability
        assert _tier_level(result_empty.combined_tier) == 4  # clean vendor = TIER_4


# =============================================================================
# TestOSINTScreeningInteraction
# =============================================================================

class TestOSINTScreeningInteraction:
    """Interaction between ofac.screen_name() and OSINT extra_hard_stops."""

    def test_screen_name_catch_plus_hard_stop_redundancy(self):
        """Both screen_name() and extra_hard_stops flag same entity -> still TIER_1."""
        # Rosoboronexport is in the fallback DB, so screen_name catches it.
        # Adding extra_hard_stops is redundant safety -- result must still be TIER_1.
        os.environ["XIPHOS_SCREENING_FALLBACK"] = "1"
        try:
            result = score_vendor(
                _vendor(name="Rosoboronexport", country="RU",
                        state_owned=True, foreign_ownership_is_allied=False),
                regulatory_status="COMPLIANT",
                extra_hard_stops=[{"trigger": "OFAC_HIT", "source": "OFAC_SDN"}],
            )
            assert result.combined_tier == "TIER_1_DISQUALIFIED"
            assert result.calibrated_probability == 1.0
        finally:
            os.environ.pop("XIPHOS_SCREENING_FALLBACK", None)

    def test_screen_name_miss_rescued_by_hard_stop(self):
        """Vendor that screen_name() misses but OSINT catches -> TIER_1."""
        # "Clean Tech Corp" won't match any SDN entry.
        # But if OSINT enrichment found a trade_csl match, hard stop saves us.
        result = score_vendor(
            _vendor(), regulatory_status="COMPLIANT",
            extra_hard_stops=[{"trigger": "TRADE_CSL_MATCH", "source": "trade.gov/csl"}],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"
        assert result.calibrated_probability == 1.0

    def test_clean_screen_no_hard_stops_passes(self):
        """Clean vendor + no screen_name hit + no hard stops = normal pass."""
        result = score_vendor(
            _vendor(), regulatory_status="COMPLIANT", extra_hard_stops=[],
        )
        assert _tier_level(result.combined_tier) >= 3  # TIER_3 or TIER_4


# =============================================================================
# TestTradeCSLIntegration
# =============================================================================

class TestTradeCSLIntegration:
    """Simulate OSINT enrichment discovering trade.gov CSL matches."""

    def test_entity_list_match_as_hard_stop(self):
        result = score_vendor(
            _vendor(), regulatory_status="COMPLIANT",
            extra_hard_stops=[{
                "trigger": "BIS_ENTITY_LIST",
                "source": "trade.gov/consolidated-screening-list",
                "matched_name": "Huawei Technologies",
            }],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"

    def test_denied_persons_list_as_hard_stop(self):
        result = score_vendor(
            _vendor(), regulatory_status="COMPLIANT",
            extra_hard_stops=[{
                "trigger": "DENIED_PERSONS_LIST",
                "source": "trade.gov/consolidated-screening-list",
                "matched_name": "John Doe",
            }],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"

    def test_military_end_user_list_as_hard_stop(self):
        result = score_vendor(
            _vendor(), regulatory_status="COMPLIANT",
            extra_hard_stops=[{
                "trigger": "MILITARY_END_USER_LIST",
                "source": "trade.gov/consolidated-screening-list",
                "matched_name": "PLA Unit 61398",
            }],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"

    def test_multiple_csl_matches_compound(self):
        """Multiple CSL list matches for same vendor."""
        result = score_vendor(
            _vendor(), regulatory_status="COMPLIANT",
            extra_hard_stops=[
                {"trigger": "BIS_ENTITY_LIST", "source": "trade.gov/csl",
                 "matched_name": "Target Corp A"},
                {"trigger": "DENIED_PERSONS_LIST", "source": "trade.gov/csl",
                 "matched_name": "Target Corp A"},
                {"trigger": "MILITARY_END_USER_LIST", "source": "trade.gov/csl",
                 "matched_name": "Target Corp A"},
            ],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"
        assert result.calibrated_probability == 1.0


# =============================================================================
# TestSensitivityInteractionWithHardStops
# =============================================================================

class TestSensitivityInteractionWithHardStops:
    """Hard stops override at every sensitivity level."""

    def test_hard_stop_at_commercial_sensitivity(self):
        result = score_vendor(
            _vendor(sensitivity="COMMERCIAL"), regulatory_status="COMPLIANT",
            extra_hard_stops=[{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"

    def test_hard_stop_at_critical_sci_sensitivity(self):
        result = score_vendor(
            _vendor(sensitivity="CRITICAL_SCI"), regulatory_status="COMPLIANT",
            extra_hard_stops=[{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"

    def test_hard_stop_outcome_same_across_sensitivity(self):
        """Hard stop forces identical tier at COMMERCIAL and CRITICAL_SCI."""
        r_commercial = score_vendor(
            _vendor(sensitivity="COMMERCIAL"), regulatory_status="COMPLIANT",
            extra_hard_stops=[{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
        )
        r_critical = score_vendor(
            _vendor(sensitivity="CRITICAL_SCI"), regulatory_status="COMPLIANT",
            extra_hard_stops=[{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
        )
        assert r_commercial.combined_tier == r_critical.combined_tier == "TIER_1_DISQUALIFIED"


# =============================================================================
# TestHardStopContributionReporting
# =============================================================================

class TestHardStopContributionReporting:
    """Hard stops should appear in scoring contributions and findings."""

    def test_hard_stop_contribution_shows_prohibition(self):
        result = score_vendor(
            _vendor(), regulatory_status="COMPLIANT",
            extra_hard_stops=[{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
        )
        # contributions is a list of dicts with "factor" key
        prohibition_factors = [c for c in result.contributions
                               if c.get("factor") == "PROHIBITION"]
        assert len(prohibition_factors) >= 1, (
            f"Expected PROHIBITION contribution, got factors: "
            f"{[c.get('factor') for c in result.contributions]}"
        )

    def test_hard_stop_findings_mention_trigger(self):
        result = score_vendor(
            _vendor(), regulatory_status="COMPLIANT",
            extra_hard_stops=[{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
        )
        findings_text = " ".join(result.findings)
        assert "SAM_EXCLUSION" in findings_text or "Hard stop" in findings_text, (
            f"Findings should mention trigger. Got: {result.findings}"
        )


# =============================================================================
# TestIntegrationWithRegulatoryGates
# =============================================================================

class TestIntegrationWithRegulatoryGates:
    """Hard stops interact correctly with regulatory gate evaluation."""

    def test_hard_stop_alongside_non_compliant_gate(self):
        """NON_COMPLIANT regulatory status + hard stop = still TIER_1_DISQUALIFIED."""
        result = score_vendor(
            _vendor(), regulatory_status="NON_COMPLIANT",
            extra_hard_stops=[{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"
        assert result.calibrated_probability == 1.0

    def test_hard_stop_with_not_evaluated_status(self):
        """Hard stop forces TIER_1 even when regulatory_status is NOT_EVALUATED."""
        result = score_vendor(
            _vendor(), regulatory_status="NOT_EVALUATED",
            extra_hard_stops=[{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"
        assert result.calibrated_probability == 1.0

    def test_hard_stop_with_extra_metadata_fields(self):
        """Hard stop dict with extra metadata fields still triggers correctly."""
        result = score_vendor(
            _vendor(), regulatory_status="COMPLIANT",
            extra_hard_stops=[{
                "trigger": "SAM_EXCLUSION",
                "source": "SAM.gov",
                "matched_name": "Some Company",
                "matched_address": "123 Fake St",
                "confidence_score": 0.95,
                "last_updated": "2026-03-22",
            }],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"
        assert result.calibrated_probability == 1.0


# =============================================================================
# TestEdgeCases
# =============================================================================

class TestEdgeCases:
    """Edge cases in hard stop handling."""

    def test_empty_hard_stop_dict_raises(self):
        """Empty hard stop dict (no 'trigger' key) raises KeyError in score_vendor.
        This documents the contract: callers MUST include 'trigger' key."""
        with pytest.raises(KeyError):
            score_vendor(
                _vendor(), regulatory_status="COMPLIANT",
                extra_hard_stops=[{}],
            )

    def test_hard_stop_missing_trigger_raises(self):
        """Hard stop without 'trigger' key raises KeyError."""
        with pytest.raises(KeyError):
            score_vendor(
                _vendor(), regulatory_status="COMPLIANT",
                extra_hard_stops=[{"source": "SAM.gov"}],
            )

    def test_not_evaluated_no_hard_stops_clean_vendor(self):
        """NOT_EVALUATED status with no hard stops: vendor scored on factors alone."""
        result = score_vendor(
            _vendor(), regulatory_status="NOT_EVALUATED", extra_hard_stops=[],
        )
        # Clean US vendor with no hard stops should be TIER_4
        assert _tier_level(result.combined_tier) == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
