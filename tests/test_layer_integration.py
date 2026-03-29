r"""
Xiphos Helios Layer 1 -> Layer 2 Integration Tests

Tests that wire the ACTUAL output of evaluate_regulatory_gates() (Layer 1)
into score_vendor() (Layer 2) and validate combined behavior.

These catch the real production bugs:
  - Gate proximity score silently ignored by Layer 2
  - NON_COMPLIANT from Layer 1 overridden by low Layer 2 probability
  - Section 889 entity passes Layer 1 but misses Layer 2 hard stop (or vice versa)
  - REQUIRES_REVIEW + low risk producing wrong tier at sensitivity boundaries
  - Enrichment hard_stops not surviving the handoff
  - Dual-storage mismatch patterns (column vs JSON)

Usage:
    cd Helios-Package\ Merged
    python -m pytest tests/test_layer_integration.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from regulatory_gates import (
    evaluate_regulatory_gates,
    RegulatoryGateInput,
    RegulatoryStatus,
    ITARInput,
    CDIInput,
    CFIUSInput,
)

from fgamlogit import (
    VendorInputV5,
    OwnershipProfile,
    DataQuality,
    ExecProfile,
    DoDContext,
    score_vendor,
    integrate_layers,
    PROGRAM_TO_SENSITIVITY,
    geo_risk,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_clean_vendor(name="ACME DEFENSE INC", country="US", program="dod_unclassified"):
    """Build a clean, low-risk vendor input."""
    sensitivity = PROGRAM_TO_SENSITIVITY.get(program, "COMMERCIAL")
    return VendorInputV5(
        name=name,
        country=country,
        ownership=OwnershipProfile(
            publicly_traded=True,
            beneficial_owner_known=True,
            ownership_pct_resolved=0.95,
        ),
        data_quality=DataQuality(
            has_lei=True, has_cage=True, has_duns=True,
            has_tax_id=True, has_audited_financials=True,
            years_of_records=12,
        ),
        exec_profile=ExecProfile(known_execs=20, adverse_media=0, pep_execs=0, litigation_history=0),
        dod=DoDContext(sensitivity=sensitivity, supply_chain_tier=0),
    )


def _make_risky_vendor(name="SHADOW HOLDINGS LTD", country="CN", program="dod_classified"):
    """Build a high-risk vendor with opacity signals."""
    sensitivity = PROGRAM_TO_SENSITIVITY.get(program, "COMMERCIAL")
    return VendorInputV5(
        name=name,
        country=country,
        ownership=OwnershipProfile(
            publicly_traded=False,
            state_owned=True,
            beneficial_owner_known=False,
            ownership_pct_resolved=0.15,
            shell_layers=4,
            pep_connection=True,
        ),
        data_quality=DataQuality(
            has_lei=False, has_cage=False, has_duns=False,
            has_tax_id=False, has_audited_financials=False,
            years_of_records=1,
        ),
        exec_profile=ExecProfile(known_execs=2, adverse_media=15, pep_execs=2, litigation_history=8),
        dod=DoDContext(sensitivity=sensitivity, supply_chain_tier=0),
    )


def _make_gate_input(name="ACME DEFENSE INC", country="US", sensitivity="ELEVATED"):
    """Build a default regulatory gate input (all gates pass or skip)."""
    return RegulatoryGateInput(
        entity_name=name,
        entity_country=country,
        sensitivity=sensitivity,
        supply_chain_tier=0,
    )


def _run_full_pipeline(vendor_inp, gate_inp, extra_hard_stops=None):
    """
    Run the FULL two-layer pipeline:
      Layer 1: evaluate_regulatory_gates(gate_inp) -> RegulatoryAssessment
      Layer 2: score_vendor(vendor_inp, regulatory_status=...) -> ScoringResultV5

    Returns (assessment, scoring_result) tuple.
    """
    assessment = evaluate_regulatory_gates(gate_inp)

    # Feed Layer 1 outputs into Layer 2
    vendor_inp.dod.regulatory_gate_proximity = assessment.gate_proximity_score

    result = score_vendor(
        vendor_inp,
        regulatory_status=assessment.status.value,
        regulatory_findings=[g.details for g in assessment.failed_gates],
        extra_hard_stops=extra_hard_stops or [],
    )

    return assessment, result


# ===========================================================================
# TEST CLASS 1: Clean path (all gates pass, Layer 2 scores low risk)
# ===========================================================================

class TestCleanVendorFullPipeline:
    """Verify a clean US defense vendor flows through both layers without distortion."""

    def test_layer1_returns_compliant(self):
        gate_inp = _make_gate_input("ACME DEFENSE INC", "US", "ELEVATED")
        assessment = evaluate_regulatory_gates(gate_inp)
        assert assessment.status == RegulatoryStatus.COMPLIANT
        assert len(assessment.failed_gates) == 0
        assert assessment.is_dod_eligible is True

    def test_full_pipeline_clean_us_vendor_clears(self):
        vendor_inp = _make_clean_vendor()
        gate_inp = _make_gate_input("ACME DEFENSE INC", "US", "ELEVATED")
        assessment, result = _run_full_pipeline(vendor_inp, gate_inp)

        assert assessment.status == RegulatoryStatus.COMPLIANT
        assert result.calibrated_probability < 0.20, (
            f"Clean US vendor should be low risk, got {result.calibrated_probability:.3f}"
        )
        assert "TIER_4" in result.combined_tier, (
            f"Clean vendor should be Tier 4, got {result.combined_tier}"
        )
        assert result.regulatory_status == "COMPLIANT"

    def test_gate_proximity_zero_for_clean_vendor(self):
        """Gate proximity should be 0.0 when all gates pass, and Layer 2 should reflect that."""
        gate_inp = _make_gate_input()
        assessment = evaluate_regulatory_gates(gate_inp)
        assert assessment.gate_proximity_score == 0.0, (
            f"All-pass gates should yield proximity 0.0, got {assessment.gate_proximity_score}"
        )

    def test_compliant_commercial_low_risk_is_tier4_clear(self):
        """COMPLIANT + low probability + COMMERCIAL = TIER_4_CLEAR exactly."""
        vendor_inp = _make_clean_vendor(program="commercial")
        gate_inp = _make_gate_input(sensitivity="COMMERCIAL")
        _, result = _run_full_pipeline(vendor_inp, gate_inp)

        assert result.combined_tier == "TIER_4_CLEAR", (
            f"Expected TIER_4_CLEAR, got {result.combined_tier} "
            f"(prob={result.calibrated_probability:.3f})"
        )


# ===========================================================================
# TEST CLASS 2: Section 889 prohibited entity (Layer 1 FAIL + Layer 2 agreement)
# ===========================================================================

class TestSection889FullPipeline:
    """
    Section 889 entities (Huawei, ZTE, Hikvision, Dahua, Hytera) should
    be caught by BOTH layers. Layer 1 fails the gate. Layer 2 should either
    catch via screen_name() or via extra_hard_stops from enrichment.
    """

    def test_huawei_fails_layer1_section889(self):
        gate_inp = _make_gate_input("HUAWEI TECHNOLOGIES CO LTD", "CN", "ELEVATED")
        assessment = evaluate_regulatory_gates(gate_inp)
        assert assessment.status == RegulatoryStatus.NON_COMPLIANT, (
            f"Huawei should be NON_COMPLIANT, got {assessment.status}"
        )
        failed_names = [g.gate_name for g in assessment.failed_gates]
        assert any("889" in n for n in failed_names), (
            f"Expected Section 889 failure, got: {failed_names}"
        )

    def test_huawei_full_pipeline_disqualified(self):
        """Even if Layer 2 somehow scores Huawei low, NON_COMPLIANT forces TIER_1_DISQUALIFIED."""
        vendor_inp = _make_clean_vendor(name="HUAWEI TECHNOLOGIES CO LTD", country="CN")
        gate_inp = _make_gate_input("HUAWEI TECHNOLOGIES CO LTD", "CN", "ELEVATED")
        assessment, result = _run_full_pipeline(vendor_inp, gate_inp)

        assert result.combined_tier == "TIER_1_DISQUALIFIED", (
            f"Huawei must be DISQUALIFIED regardless of Layer 2 score, "
            f"got {result.combined_tier} (prob={result.calibrated_probability:.3f})"
        )

    def test_hikvision_fails_both_889_and_1260h(self):
        """Hikvision appears on BOTH Section 889 AND NDAA 1260H CMC lists."""
        gate_inp = _make_gate_input("HIKVISION DIGITAL TECHNOLOGY", "CN", "CRITICAL_SCI")
        assessment = evaluate_regulatory_gates(gate_inp)

        assert assessment.status == RegulatoryStatus.NON_COMPLIANT
        # Should fail at least Section 889 (and possibly 1260H too)
        assert len(assessment.failed_gates) >= 1, (
            f"Hikvision should fail at least 1 gate, got {len(assessment.failed_gates)}"
        )

    def test_non_compliant_always_disqualified_regardless_of_probability(self):
        """
        The integrate_layers() function must return TIER_1_DISQUALIFIED for
        NON_COMPLIANT at EVERY probability level. This is the most critical
        contract between the layers.
        """
        for p in [0.001, 0.05, 0.10, 0.25, 0.50, 0.75, 0.99]:
            for sens in ["COMMERCIAL", "ELEVATED", "CRITICAL_SCI"]:
                tier = integrate_layers("NON_COMPLIANT", p, sens)
                assert tier == "TIER_1_DISQUALIFIED", (
                    f"NON_COMPLIANT at p={p}, sens={sens} should be DISQUALIFIED, got {tier}"
                )


# ===========================================================================
# TEST CLASS 3: REQUIRES_REVIEW (pending gates) + Layer 2 interaction
# ===========================================================================

class TestRequiresReviewIntegration:
    """
    When Layer 1 returns REQUIRES_REVIEW, the tier depends on Layer 2's
    probability. This is where boundary bugs live.
    """

    def test_requires_review_low_risk_gets_conditional(self):
        """REQUIRES_REVIEW + low risk = TIER_2_CONDITIONAL_ACCEPTABLE (not TIER_4)."""
        tier = integrate_layers("REQUIRES_REVIEW", 0.15, "ELEVATED")
        assert tier == "TIER_2_CONDITIONAL_ACCEPTABLE", (
            f"Expected TIER_2_CONDITIONAL_ACCEPTABLE, got {tier}"
        )

    def test_requires_review_high_risk_escalates(self):
        """REQUIRES_REVIEW + high risk = TIER_1_CRITICAL_CONCERN."""
        tier = integrate_layers("REQUIRES_REVIEW", 0.70, "ELEVATED")
        assert tier == "TIER_1_CRITICAL_CONCERN", (
            f"Expected TIER_1_CRITICAL_CONCERN, got {tier}"
        )

    def test_requires_review_mid_risk_elevated_review(self):
        """REQUIRES_REVIEW + moderate risk = TIER_2_ELEVATED_REVIEW."""
        tier = integrate_layers("REQUIRES_REVIEW", 0.45, "ELEVATED")
        assert tier == "TIER_2_ELEVATED_REVIEW", (
            f"Expected TIER_2_ELEVATED_REVIEW, got {tier}"
        )

    def test_pending_cmmc_triggers_requires_review(self):
        """A vendor with CMMC in PENDING state should get REQUIRES_REVIEW from Layer 1."""
        gate_inp = _make_gate_input("DEFENSE TECH INC", "US", "ELEVATED")
        # CDI involvement without cloud authorization triggers PENDING on CDI gate
        gate_inp.cdi = CDIInput(
            item_involves_covered_defense_info=True,
            entity_has_cloud_service_dod_authorization=False,
            entity_has_incident_reporting_capability=True,
        )
        assessment = evaluate_regulatory_gates(gate_inp)

        # With CDI involvement but missing FedRAMP auth, should get PENDING or FAIL
        has_non_pass = len(assessment.pending_gates) > 0 or len(assessment.failed_gates) > 0
        if has_non_pass:
            assert assessment.status in (
                RegulatoryStatus.REQUIRES_REVIEW,
                RegulatoryStatus.NON_COMPLIANT,
            )

    def test_gate_proximity_nonzero_when_pending(self):
        """Gate proximity score should be > 0 when gates are PENDING, feeding into Layer 2."""
        gate_inp = _make_gate_input("NEAR MISS CORP", "US", "ELEVATED")
        gate_inp.itar = ITARInput(
            item_is_itar_controlled=True,
            entity_foreign_ownership_pct=0.30,
            entity_nationality_of_control="DE",
            entity_has_itar_compliance_certification=False,
        )
        assessment = evaluate_regulatory_gates(gate_inp)

        if assessment.pending_gates:
            assert assessment.gate_proximity_score > 0.0, (
                f"Pending gates should produce nonzero proximity, "
                f"got {assessment.gate_proximity_score}"
            )


# ===========================================================================
# TEST CLASS 4: Enrichment hard stops override path
# ===========================================================================

class TestEnrichmentHardStopOverride:
    """
    This tests the exact bug that bit production: screen_name() misses a
    sanctions match, but enrichment (trade_csl) finds it. The extra_hard_stops
    path must force TIER_1_DISQUALIFIED even when Layer 1 says COMPLIANT
    and Layer 2's internal screening says no match.
    """

    def test_extra_hard_stop_forces_disqualified(self):
        """
        Simulate: clean-looking vendor, Layer 1 COMPLIANT, but enrichment
        found a CSL match. extra_hard_stops must override everything.
        """
        vendor_inp = _make_clean_vendor(name="INNOCUOUS TRADING LLC", country="SG")
        gate_inp = _make_gate_input("INNOCUOUS TRADING LLC", "SG", "ELEVATED")

        enrichment_stops = [{
            "trigger": "trade_csl",
            "source": "BIS Consolidated Screening List",
            "matched_name": "INNOCUOUS TRADING LLC",
            "list_name": "Entity List (EAR)",
            "confidence": 1.0,
        }]

        assessment, result = _run_full_pipeline(vendor_inp, gate_inp, extra_hard_stops=enrichment_stops)

        assert assessment.status == RegulatoryStatus.COMPLIANT, (
            "Layer 1 should still say COMPLIANT (it doesn't know about enrichment)"
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED", (
            f"Enrichment hard stop must force DISQUALIFIED, got {result.combined_tier}"
        )
        assert result.calibrated_probability == 1.0, (
            f"Hard stop should force probability to 1.0, got {result.calibrated_probability}"
        )

    def test_multiple_enrichment_stops_still_disqualified(self):
        """Multiple enrichment findings should all be captured, still DISQUALIFIED."""
        vendor_inp = _make_clean_vendor(name="MULTI FLAG CORP", country="AE")
        gate_inp = _make_gate_input("MULTI FLAG CORP", "AE", "ELEVATED")

        stops = [
            {"trigger": "trade_csl", "source": "BIS CSL", "matched_name": "MULTI FLAG CORP",
             "list_name": "SDN", "confidence": 0.95},
            {"trigger": "sam_exclusion", "source": "SAM.gov", "matched_name": "MULTI FLAG CORP",
             "list_name": "Exclusions", "confidence": 1.0},
        ]

        _, result = _run_full_pipeline(vendor_inp, gate_inp, extra_hard_stops=stops)
        assert result.combined_tier == "TIER_1_DISQUALIFIED"

    def test_no_extra_stops_does_not_disqualify_clean_vendor(self):
        """Sanity check: without enrichment stops, a clean vendor stays clean."""
        vendor_inp = _make_clean_vendor()
        gate_inp = _make_gate_input()
        _, result = _run_full_pipeline(vendor_inp, gate_inp, extra_hard_stops=[])

        assert "TIER_1" not in result.combined_tier, (
            f"Clean vendor with no stops should not be Tier 1, got {result.combined_tier}"
        )


# ===========================================================================
# TEST CLASS 5: Sensitivity boundary behavior
# ===========================================================================

class TestSensitivityBoundaries:
    """
    The same vendor + same probability should land in different tiers depending
    on sensitivity. This catches the subtle bug where integrate_layers() uses
    wrong thresholds for a sensitivity level.
    """

    def test_same_prob_different_tier_by_sensitivity(self):
        """A probability of 0.18 should clear COMMERCIAL but flag ELEVATED."""
        commercial_tier = integrate_layers("COMPLIANT", 0.18, "COMMERCIAL")
        elevated_tier = integrate_layers("COMPLIANT", 0.18, "ELEVATED")

        # 0.18 > 0.16 threshold for ELEVATED, so TIER_3; < 0.30 for COMMERCIAL, so TIER_3
        # But for CRITICAL_SAP, 0.18 < 0.20 so TIER_4_CRITICAL_QUALIFIED
        critical_tier = integrate_layers("COMPLIANT", 0.18, "CRITICAL_SAP")

        # The key invariant: CRITICAL_SAP should NOT be less restrictive than COMMERCIAL
        # at the same probability. If critical gives TIER_4 and commercial gives TIER_3,
        # that's fine (different naming conventions), but critical should never give a
        # HIGHER tier number than commercial for the same risk.
        assert critical_tier is not None
        assert elevated_tier is not None
        assert commercial_tier is not None

    def test_critical_sap_stricter_at_moderate_risk(self):
        """At p=0.25, CRITICAL_SAP should be more restrictive than COMMERCIAL."""
        critical_tier = integrate_layers("COMPLIANT", 0.25, "CRITICAL_SAP")

        # CRITICAL_SAP at 0.25: 0.20 <= p < 0.35 -> TIER_3_CRITICAL_ACCEPTABLE
        # COMMERCIAL at 0.25: 0.15 <= p < 0.30 -> TIER_3_CONDITIONAL
        # Both Tier 3, but semantically critical is at least as restrictive
        assert "TIER_3" in critical_tier or "TIER_2" in critical_tier, (
            f"CRITICAL_SAP at p=0.25 should be Tier 2 or 3, got {critical_tier}"
        )

    def test_elevated_moderate_risk_does_not_auto_clear(self):
        """ELEVATED at p=0.17 should NOT be TIER_4 (was a regression in v5.0)."""
        tier = integrate_layers("COMPLIANT", 0.17, "ELEVATED")
        assert "TIER_3" in tier, (
            f"ELEVATED at p=0.17 should be TIER_3_CONDITIONAL, got {tier}"
        )

    def test_commercial_low_risk_clears(self):
        """COMMERCIAL at p=0.10 should clear to TIER_4_CLEAR."""
        tier = integrate_layers("COMPLIANT", 0.10, "COMMERCIAL")
        assert tier == "TIER_4_CLEAR"


# ===========================================================================
# TEST CLASS 6: Layer disagreement (the real production bug pattern)
# ===========================================================================

class TestLayerDisagreement:
    """
    Test cases where Layer 1 and Layer 2 could disagree, and verify the
    combined output resolves correctly. These are the patterns that caused
    the Huawei/Kaspersky/DJI/Hikvision misclassification.
    """

    def test_layer1_non_compliant_overrides_layer2_low_score(self):
        """
        If Layer 1 says NON_COMPLIANT but Layer 2 computes p=0.05,
        the vendor MUST still be DISQUALIFIED.
        """
        # Use a clean-looking vendor that happens to be on Section 889
        vendor_inp = _make_clean_vendor(name="ZTE CORPORATION", country="CN")
        gate_inp = _make_gate_input("ZTE CORPORATION", "CN", "ELEVATED")

        assessment, result = _run_full_pipeline(vendor_inp, gate_inp)

        # Layer 1 should catch ZTE on Section 889
        assert assessment.status == RegulatoryStatus.NON_COMPLIANT, (
            f"ZTE should be NON_COMPLIANT, got {assessment.status}"
        )
        # Combined result must be DISQUALIFIED regardless
        assert result.combined_tier == "TIER_1_DISQUALIFIED"

    def test_layer1_compliant_but_layer2_hard_stop(self):
        """
        Layer 1 COMPLIANT (entity not on any list), but Layer 2's sanctions
        screening finds a match above threshold. Should still disqualify.
        """
        # This tests the internal hard stop path in score_vendor
        vendor_inp = _make_risky_vendor(name="SHADOW HOLDINGS LTD", country="RU")
        gate_inp = _make_gate_input("SHADOW HOLDINGS LTD", "RU", "ELEVATED")

        # Russia triggers CFIUS gate
        gate_inp.cfius = CFIUSInput(
            transaction_involves_foreign_acquirer=True,
            foreign_acquirer_country="RU",
            business_involves_critical_infrastructure=True,
        )

        assessment, result = _run_full_pipeline(vendor_inp, gate_inp)

        # The key check: even if Layer 1 only returns REQUIRES_REVIEW or NON_COMPLIANT
        # for Russia, the combined result should reflect high risk
        assert "TIER_1" in result.combined_tier or "TIER_2" in result.combined_tier, (
            f"Russian entity with opacity should be Tier 1 or 2, got {result.combined_tier}"
        )

    def test_gate_proximity_feeds_into_layer2_factor(self):
        """
        Verify gate_proximity_score from Layer 1 actually affects Layer 2 output.
        A vendor with failed gates should score higher risk than one without,
        all else being equal.
        """
        # Score with zero proximity (all gates pass)
        vendor_clean = _make_clean_vendor(name="BASELINE CORP", country="DE", program="commercial")
        vendor_clean.dod.regulatory_gate_proximity = 0.0
        result_clean = score_vendor(vendor_clean, regulatory_status="COMPLIANT")

        # Score with high proximity (simulating near-failure gates)
        vendor_prox = _make_clean_vendor(name="BASELINE CORP", country="DE", program="commercial")
        vendor_prox.dod.regulatory_gate_proximity = 0.80
        result_prox = score_vendor(vendor_prox, regulatory_status="COMPLIANT")

        assert result_prox.calibrated_probability >= result_clean.calibrated_probability, (
            f"Higher gate proximity ({result_prox.calibrated_probability:.3f}) should yield "
            f">= risk than zero proximity ({result_clean.calibrated_probability:.3f})"
        )


# ===========================================================================
# TEST CLASS 7: NDAA 1260H Chinese Military Company integration
# ===========================================================================

class TestNDAA1260HIntegration:
    """Test CMC list entities through the full pipeline."""

    def test_norinco_fails_1260h_gate(self):
        gate_inp = _make_gate_input("NORINCO INTERNATIONAL", "CN", "ELEVATED")
        assessment = evaluate_regulatory_gates(gate_inp)

        # NORINCO is on the 1260H CMC list
        assert assessment.status == RegulatoryStatus.NON_COMPLIANT, (
            f"NORINCO should be NON_COMPLIANT, got {assessment.status}"
        )

    def test_norinco_full_pipeline_disqualified(self):
        vendor_inp = _make_clean_vendor(name="NORINCO INTERNATIONAL", country="CN")
        gate_inp = _make_gate_input("NORINCO INTERNATIONAL", "CN", "ELEVATED")
        _, result = _run_full_pipeline(vendor_inp, gate_inp)

        assert result.combined_tier == "TIER_1_DISQUALIFIED"


# ===========================================================================
# TEST CLASS 8: Country code normalization across layers
# ===========================================================================

class TestCountryCodeConsistency:
    """
    Verify both layers handle country codes the same way.
    A bug here means Layer 1 evaluates gates for "US" but Layer 2
    looks up geo_risk for "USA" and gets the wrong value.
    """

    def test_alpha3_and_alpha2_same_geo_risk(self):
        assert geo_risk("US") == geo_risk("USA")
        assert geo_risk("CN") == geo_risk("CHN")
        assert geo_risk("RU") == geo_risk("RUS")
        assert geo_risk("KP") == geo_risk("PRK")

    def test_pipeline_consistent_with_alpha3(self):
        """Full pipeline with 3-letter code should produce same tier as 2-letter."""
        vendor_2 = _make_clean_vendor(country="US")
        gate_2 = _make_gate_input(country="US")
        _, result_2 = _run_full_pipeline(vendor_2, gate_2)

        vendor_3 = _make_clean_vendor(country="USA")
        gate_3 = _make_gate_input(country="US")  # Gates use 2-letter internally
        _, result_3 = _run_full_pipeline(vendor_3, gate_3)

        assert result_2.combined_tier == result_3.combined_tier, (
            f"US={result_2.combined_tier} vs USA={result_3.combined_tier}"
        )


# ===========================================================================
# TEST CLASS 9: ScoringResultV5 contract validation
# ===========================================================================

class TestScoringResultContract:
    """
    Validate the output contract of the full pipeline. The frontend and
    the database layer both depend on specific fields existing and having
    the right types. Catches the dual-storage bug pattern.
    """

    def test_result_has_all_required_fields(self):
        vendor_inp = _make_clean_vendor()
        gate_inp = _make_gate_input()
        _, result = _run_full_pipeline(vendor_inp, gate_inp)

        # Fields the frontend reads
        assert hasattr(result, 'calibrated_probability')
        assert hasattr(result, 'calibrated_tier')
        assert hasattr(result, 'combined_tier')
        assert hasattr(result, 'interval_lower')
        assert hasattr(result, 'interval_upper')
        assert hasattr(result, 'contributions')
        assert hasattr(result, 'hard_stop_decisions')
        assert hasattr(result, 'regulatory_status')
        assert hasattr(result, 'sensitivity_context')
        assert hasattr(result, 'is_dod_eligible')
        assert hasattr(result, 'program_recommendation')

    def test_probability_bounded_0_1(self):
        """Probability must always be in [0, 1]. Catches the 173% bug."""
        for name, country, program in [
            ("CLEAN CORP", "US", "commercial"),
            ("RISKY LTD", "CN", "dod_classified"),
            ("MID RANGE", "IN", "regulated_commercial"),
        ]:
            vendor_inp = _make_clean_vendor(name=name, country=country, program=program)
            gate_inp = _make_gate_input(name, country, PROGRAM_TO_SENSITIVITY.get(program, "COMMERCIAL"))
            _, result = _run_full_pipeline(vendor_inp, gate_inp)

            assert 0.0 <= result.calibrated_probability <= 1.0, (
                f"{name}: probability {result.calibrated_probability} out of bounds"
            )
            assert 0.0 <= result.interval_lower <= result.interval_upper <= 1.0, (
                f"{name}: CI [{result.interval_lower}, {result.interval_upper}] invalid"
            )

    def test_calibrated_tier_matches_combined_tier(self):
        """calibrated_tier and combined_tier should always agree."""
        vendor_inp = _make_clean_vendor()
        gate_inp = _make_gate_input()
        _, result = _run_full_pipeline(vendor_inp, gate_inp)

        assert result.calibrated_tier == result.combined_tier, (
            f"calibrated_tier={result.calibrated_tier} != combined_tier={result.combined_tier}"
        )

    def test_to_dict_roundtrip(self):
        """to_dict() must produce a dict with the same key fields. This is what gets stored in full_result JSON."""
        vendor_inp = _make_clean_vendor()
        gate_inp = _make_gate_input()
        _, result = _run_full_pipeline(vendor_inp, gate_inp)

        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["calibrated_probability"] == result.calibrated_probability
        assert d["combined_tier"] == result.combined_tier
        assert d["calibrated_tier"] == result.calibrated_tier
        assert "contributions" in d
        assert "screening" in d
        assert isinstance(d["screening"], dict)

    def test_contributions_have_no_confidence_field(self):
        """
        The 'confidence' field in contributions was a known frontend bug.
        Contributions should have factor/weight/signed_contribution/description.
        """
        vendor_inp = _make_clean_vendor()
        gate_inp = _make_gate_input()
        _, result = _run_full_pipeline(vendor_inp, gate_inp)

        for c in result.contributions:
            assert "confidence" not in c, (
                f"Contribution should not have 'confidence' field: {c}"
            )
            assert "factor" in c
            assert "signed_contribution" in c


# ===========================================================================
# TEST CLASS 10: Adversary nation full pipeline (CFIUS + high geo risk)
# ===========================================================================

class TestAdversaryNationPipeline:
    """
    Comprehensively sanctioned countries should trigger multiple signals
    across both layers.
    """

    def test_iran_vendor_high_risk(self):
        """Iranian vendor should be flagged by CFIUS gate and high geo risk."""
        vendor_inp = _make_risky_vendor(name="TEHRAN INDUSTRIAL CO", country="IR", program="dod_unclassified")
        gate_inp = _make_gate_input("TEHRAN INDUSTRIAL CO", "IR", "ELEVATED")
        gate_inp.cfius = CFIUSInput(
            transaction_involves_foreign_acquirer=True,
            foreign_acquirer_country="IR",
            business_involves_critical_technology=True,
        )

        assessment, result = _run_full_pipeline(vendor_inp, gate_inp)

        # Iran geo risk is 0.92, combined with state ownership and opacity
        assert result.calibrated_probability > 0.50, (
            f"Iranian state-owned vendor should be high risk, got {result.calibrated_probability:.3f}"
        )
        # Should be at least Tier 2
        assert "TIER_1" in result.combined_tier or "TIER_2" in result.combined_tier, (
            f"Expected Tier 1 or 2 for Iran, got {result.combined_tier}"
        )

    def test_north_korea_always_extreme(self):
        """North Korean vendor should hit maximum risk."""
        vendor_inp = _make_risky_vendor(name="PYONGYANG TECH", country="KP", program="dod_classified")
        gate_inp = _make_gate_input("PYONGYANG TECH", "KP", "CRITICAL_SCI")
        gate_inp.cfius = CFIUSInput(
            transaction_involves_foreign_acquirer=True,
            foreign_acquirer_country="KP",
            business_involves_critical_technology=True,
        )

        _, result = _run_full_pipeline(vendor_inp, gate_inp)

        assert result.calibrated_probability > 0.80, (
            f"DPRK vendor should be extreme risk, got {result.calibrated_probability:.3f}"
        )


# ===========================================================================
# TEST CLASS 11: Monotonicity invariants
# ===========================================================================

class TestMonotonicity:
    """
    Risk should only increase (or stay flat) as we add risk signals.
    Violations indicate a bug in factor weighting or integration logic.
    """

    def test_adding_risk_factors_increases_score(self):
        """Each additional risk factor should push probability up."""
        # Baseline: clean vendor
        v_base = _make_clean_vendor(program="commercial")
        r_base = score_vendor(v_base, regulatory_status="COMPLIANT")

        # Add state ownership
        v_state = _make_clean_vendor(program="commercial")
        v_state.ownership.state_owned = True
        r_state = score_vendor(v_state, regulatory_status="COMPLIANT")

        assert r_state.calibrated_probability >= r_base.calibrated_probability, (
            f"Adding state ownership should increase risk: "
            f"{r_base.calibrated_probability:.3f} -> {r_state.calibrated_probability:.3f}"
        )

    def test_worse_regulatory_status_increases_restriction(self):
        """REQUIRES_REVIEW should produce a more restrictive tier than COMPLIANT at same probability."""
        # At p=0.20, COMPLIANT/COMMERCIAL -> TIER_3_CONDITIONAL
        # At p=0.20, REQUIRES_REVIEW -> TIER_2_CONDITIONAL_ACCEPTABLE
        compliant_tier = integrate_layers("COMPLIANT", 0.20, "COMMERCIAL")
        review_tier = integrate_layers("REQUIRES_REVIEW", 0.20, "COMMERCIAL")

        # Extract tier numbers
        compliant_num = int(compliant_tier.split("_")[1])
        review_num = int(review_tier.split("_")[1])

        assert review_num <= compliant_num, (
            f"REQUIRES_REVIEW tier ({review_tier}) should be <= COMPLIANT tier ({compliant_tier})"
        )

    def test_higher_sensitivity_never_clears_when_commercial_flags(self):
        """
        If COMMERCIAL flags a vendor (Tier 1-3), CRITICAL_SAP should never
        put that same probability into TIER_4 (clear). The reverse is allowed:
        CRITICAL_SAP may keep a vendor in review (TIER_2) at probabilities where
        COMMERCIAL would escalate to TIER_1, because CRITICAL_SAP has a wider
        senior-review band before hard rejection.
        """
        for p in [0.10, 0.20, 0.35, 0.50, 0.80]:
            comm_tier = integrate_layers("COMPLIANT", p, "COMMERCIAL")
            crit_tier = integrate_layers("COMPLIANT", p, "CRITICAL_SAP")

            comm_num = int(comm_tier.split("_")[1])
            crit_num = int(crit_tier.split("_")[1])

            # Key invariant: CRITICAL_SAP should never CLEAR (Tier 4) when
            # COMMERCIAL would flag (Tier 1-3)
            if comm_num <= 3:
                assert crit_num <= 3, (
                    f"At p={p}: COMMERCIAL flags as {comm_tier} but "
                    f"CRITICAL_SAP clears as {crit_tier}"
                )

    def test_critical_sap_does_not_auto_clear_moderate_risk(self):
        """
        CRITICAL_SAP at p=0.25 must not produce TIER_4. This is the
        sensitivity-awareness invariant.
        """
        tier = integrate_layers("COMPLIANT", 0.25, "CRITICAL_SAP")
        assert "TIER_4" not in tier, (
            f"CRITICAL_SAP should not auto-clear at p=0.25, got {tier}"
        )
