"""
Integration tests: Layer 1 (regulatory_gates) -> Layer 2 (fgamlogit) pipeline.

These tests validate the CONTRACT between the two layers:
  - RegulatoryAssessment.status feeds into score_vendor(regulatory_status=...)
  - RegulatoryAssessment.gate_proximity_score feeds into DoDContext.regulatory_gate_proximity
  - Combined tier and program recommendation reflect both layers' verdicts

Each test runs a vendor profile through BOTH layers end-to-end,
verifying that the handoff produces consistent, expected outcomes.

Run:  pytest test_integration.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
os.environ["XIPHOS_SCREENING_FALLBACK"] = "1"

from regulatory_gates import (
    evaluate_regulatory_gates, RegulatoryGateInput,
    ITARInput, EARInput, CMMCInput, FOCIInput,
    BerryAmendmentInput, GateState, RegulatoryStatus,
)
from fgamlogit import (
    score_vendor, VendorInputV5,
)
from test_fixtures import (
    clean_us_prime, allied_conditional, adversary_soe,
    opaque_shell_company, sap_candidate, cmmc_pending,
    single_source_critical, chinese_tech_company, clean_commercial,
)


# ============================================================================
# HELPERS
# ============================================================================

def _run_pipeline(
    vendor: VendorInputV5,
    gate_input: RegulatoryGateInput,
):
    """
    Full two-layer pipeline:
      1. Evaluate regulatory gates (Layer 1)
      2. Feed results into score_vendor (Layer 2)
      3. Return both results for assertion
    """
    # Layer 1
    assessment = evaluate_regulatory_gates(gate_input)

    # Handoff: wire Layer 1 outputs into Layer 2 inputs
    vendor.dod.regulatory_gate_proximity = assessment.gate_proximity_score

    # Build regulatory findings list for Layer 2
    findings = []
    for g in assessment.failed_gates:
        findings.append({
            "gate": g.gate_name, "state": g.state.value,
            "severity": g.severity, "details": g.details,
        })
    for g in assessment.pending_gates:
        findings.append({
            "gate": g.gate_name, "state": g.state.value,
            "severity": g.severity, "details": g.details,
        })

    # Layer 2
    result = score_vendor(
        vendor,
        regulatory_status=assessment.status.value,
        regulatory_findings=findings,
    )

    return assessment, result


def _make_clean_gate_input(entity_name="Acme Corp", country="US",
                           sensitivity="ELEVATED", tier=0):
    """Gate input where all gates PASS or SKIP (no failures)."""
    return RegulatoryGateInput(
        entity_name=entity_name,
        entity_country=country,
        sensitivity=sensitivity,
        supply_chain_tier=tier,
    )


# ============================================================================
# TEST: CLEAN VENDOR THROUGH BOTH LAYERS
# ============================================================================

class TestCleanPipeline:
    def test_clean_us_prime_full_pipeline(self):
        """Clean US prime: all gates pass, low probability, APPROVED."""
        vendor = clean_us_prime()
        gates = _make_clean_gate_input(
            entity_name=vendor.name, country=vendor.country,
            sensitivity=vendor.dod.sensitivity,
            tier=vendor.dod.supply_chain_tier,
        )
        assessment, result = _run_pipeline(vendor, gates)

        # Layer 1: all gates should pass or skip
        assert assessment.status == RegulatoryStatus.COMPLIANT
        assert len(assessment.failed_gates) == 0
        assert assessment.is_dod_eligible is True
        assert assessment.is_dod_qualified is True

        # Layer 2: low risk, approved
        assert result.calibrated_probability < 0.20
        assert "TIER_4" in result.combined_tier
        assert result.program_recommendation == "APPROVED"
        assert result.is_dod_eligible is True
        assert result.is_dod_qualified is True

    def test_clean_commercial_full_pipeline(self):
        """Commercial vendor with no DoD gates, straight through."""
        vendor = clean_commercial()
        gates = _make_clean_gate_input(
            entity_name=vendor.name, sensitivity="COMMERCIAL",
        )
        assessment, result = _run_pipeline(vendor, gates)

        assert assessment.status == RegulatoryStatus.COMPLIANT
        assert result.calibrated_probability < 0.20
        assert "TIER_4" in result.combined_tier or "TIER_3" in result.combined_tier


# ============================================================================
# TEST: ITAR FAILURE CASCADING TO LAYER 2
# ============================================================================

class TestITARFailureCascade:
    def test_itar_pending_allied_produces_requires_review(self):
        """ITAR-controlled item with allied foreign ownership -> PENDING -> REQUIRES_REVIEW."""
        vendor = allied_conditional()
        gates = RegulatoryGateInput(
            entity_name=vendor.name,
            entity_country=vendor.country,
            sensitivity="ELEVATED",
            supply_chain_tier=1,
            itar=ITARInput(
                item_is_itar_controlled=True,
                entity_foreign_ownership_pct=0.30,
                entity_nationality_of_control="GB",
                entity_has_itar_compliance_certification=False,
                entity_manufacturing_process_certified=False,
                entity_has_approved_voting_agreement=False,
                entity_foci_status="UNMITIGATED",
            ),
        )
        assessment, result = _run_pipeline(vendor, gates)

        # Layer 1: ITAR is PENDING for allied nation (not outright FAIL)
        assert assessment.status == RegulatoryStatus.REQUIRES_REVIEW
        assert any(g.gate_name == "ITAR" for g in assessment.pending_gates)
        assert assessment.gate_proximity_score > 0.0

        # Layer 2: REQUIRES_REVIEW with moderate risk = conditional
        assert "TIER_2" in result.combined_tier or "TIER_3" in result.combined_tier
        assert result.program_recommendation in (
            "CONDITIONAL_APPROVAL_WITH_OVERSIGHT",
            "DO_NOT_PROCEED_WITHOUT_MITIGATION",
        )

    def test_itar_pass_with_compliance_cert(self):
        """ITAR item but entity has full compliance -> PASS -> normal scoring."""
        vendor = clean_us_prime()
        gates = RegulatoryGateInput(
            entity_name=vendor.name,
            entity_country="US",
            sensitivity="ELEVATED",
            supply_chain_tier=0,
            itar=ITARInput(
                item_is_itar_controlled=True,
                entity_foreign_ownership_pct=0.0,
                entity_nationality_of_control="US",
                entity_has_itar_compliance_certification=True,
                entity_manufacturing_process_certified=True,
            ),
        )
        assessment, result = _run_pipeline(vendor, gates)

        assert assessment.status == RegulatoryStatus.COMPLIANT
        assert result.calibrated_probability < 0.25
        assert result.program_recommendation == "APPROVED"


# ============================================================================
# TEST: CMMC PENDING CASCADING TO LAYER 2
# ============================================================================

class TestCMMCPendingCascade:
    def test_cmmc_gap1_pending_conditional(self):
        """CMMC gap=1 with POAM -> PENDING -> REQUIRES_REVIEW -> CONDITIONAL."""
        vendor = cmmc_pending()
        gates = RegulatoryGateInput(
            entity_name=vendor.name,
            entity_country="US",
            sensitivity="CONTROLLED",
            supply_chain_tier=2,
            cmmc=CMMCInput(
                handles_cui=True,
                required_cmmc_level=2,
                current_cmmc_level=1,
                entity_has_active_poam=True,
            ),
        )
        assessment, result = _run_pipeline(vendor, gates)

        # Layer 1: CMMC pending (gate name may include version suffix)
        assert assessment.status == RegulatoryStatus.REQUIRES_REVIEW
        assert any("CMMC" in g.gate_name and g.state == GateState.PENDING
                   for g in assessment.pending_gates)

        # Layer 2: REQUIRES_REVIEW maps to conditional range
        assert "TIER_2" in result.combined_tier or "TIER_3" in result.combined_tier
        assert result.program_recommendation in (
            "CONDITIONAL_APPROVAL_WITH_OVERSIGHT",
            "DO_NOT_PROCEED_WITHOUT_MITIGATION",
        )

    def test_cmmc_gap2_fail_disqualified(self):
        """CMMC gap >= 2 -> FAIL -> NON_COMPLIANT regardless of POAM."""
        vendor = cmmc_pending()
        gates = RegulatoryGateInput(
            entity_name=vendor.name,
            entity_country="US",
            sensitivity="CONTROLLED",
            supply_chain_tier=2,
            cmmc=CMMCInput(
                handles_cui=True,
                required_cmmc_level=3,
                current_cmmc_level=1,
                entity_has_active_poam=True,
            ),
        )
        assessment, result = _run_pipeline(vendor, gates)

        assert assessment.status == RegulatoryStatus.NON_COMPLIANT
        assert result.combined_tier == "TIER_1_DISQUALIFIED"
        assert result.program_recommendation == "DO_NOT_PROCEED"


# ============================================================================
# TEST: FOCI + SANCTIONS DOUBLE HIT
# ============================================================================

class TestDoubleHit:
    def test_adversary_soe_both_layers_block(self):
        """Russian SOE: FOCI fails in Layer 1, sanctions hard stop in Layer 2.
        Both layers independently block the entity."""
        vendor = adversary_soe()
        gates = RegulatoryGateInput(
            entity_name=vendor.name,
            entity_country="RU",
            sensitivity="ELEVATED",
            supply_chain_tier=2,
            foci=FOCIInput(
                entity_foreign_ownership_pct=1.0,
                entity_foreign_control_pct=1.0,
                foreign_controlling_country="RU",
                entity_foci_mitigation_status="UNMITIGATED",
            ),
        )
        assessment, result = _run_pipeline(vendor, gates)

        # Layer 1: FOCI should fail (adversary, unmitigated)
        assert assessment.status == RegulatoryStatus.NON_COMPLIANT
        assert any(g.gate_name == "FOCI" for g in assessment.failed_gates)

        # Layer 2: hard stop fires (state-owned in sanctioned country)
        assert result.calibrated_probability == 1.0
        assert len(result.hard_stop_decisions) > 0
        assert result.combined_tier == "TIER_1_DISQUALIFIED"
        assert result.is_dod_eligible is False

    def test_chinese_tech_with_ear_pending(self):
        """Chinese tech company with EAR-controlled item and no export procedures.
        EAR gate goes PENDING (remediable), but combined with high geo risk = elevated."""
        vendor = chinese_tech_company()
        gates = RegulatoryGateInput(
            entity_name=vendor.name,
            entity_country="CN",
            sensitivity="ELEVATED",
            supply_chain_tier=3,
            ear=EARInput(
                item_ear_ccl_category="3A001",
                entity_foreign_origin_content_pct=0.60,
                entity_has_export_control_procedures=False,
            ),
        )
        assessment, result = _run_pipeline(vendor, gates)

        # Layer 1: EAR goes PENDING (remediation possible)
        assert assessment.status == RegulatoryStatus.REQUIRES_REVIEW

        # Layer 2: REQUIRES_REVIEW + high geo risk from CN = elevated concern
        assert "TIER_1" in result.combined_tier or "TIER_2" in result.combined_tier


# ============================================================================
# TEST: SAP CANDIDATE WITH CLEAN GATES
# ============================================================================

class TestSAPPipeline:
    def test_sap_clean_all_layers(self):
        """SAP candidate with zero foreign ownership, all gates clean."""
        vendor = sap_candidate()
        gates = _make_clean_gate_input(
            entity_name=vendor.name, country="US",
            sensitivity="CRITICAL_SAP", tier=1,
        )
        assessment, result = _run_pipeline(vendor, gates)

        assert assessment.status == RegulatoryStatus.COMPLIANT
        assert result.calibrated_probability < 0.20
        assert "CRITICAL_QUALIFIED" in result.combined_tier
        assert result.program_recommendation == "APPROVED"

    def test_sap_with_foreign_ownership_hard_stop(self):
        """SAP candidate with any foreign ownership -> Layer 2 hard stop."""
        vendor = sap_candidate()
        # Inject 5% foreign ownership
        vendor.ownership.foreign_ownership_pct = 0.05
        gates = _make_clean_gate_input(
            entity_name=vendor.name, country="US",
            sensitivity="CRITICAL_SAP", tier=1,
        )
        assessment, result = _run_pipeline(vendor, gates)

        # Layer 1 still passes (FOCI not triggered without FOCI input)
        assert assessment.status == RegulatoryStatus.COMPLIANT

        # Layer 2 catches it via hard stop rule
        assert result.calibrated_probability == 1.0
        assert any("Foreign Ownership Disqualifier" in s["trigger"]
                    for s in result.hard_stop_decisions)
        assert result.combined_tier == "TIER_1_DISQUALIFIED"


# ============================================================================
# TEST: GATE PROXIMITY SCORE FLOWS TO LAYER 2
# ============================================================================

class TestGateProximityHandoff:
    def test_proximity_increases_probability(self):
        """Higher gate proximity score should increase Layer 2 probability."""
        vendor_clean = clean_us_prime()
        vendor_pending = clean_us_prime()

        gates_clean = _make_clean_gate_input(
            entity_name=vendor_clean.name, sensitivity="ELEVATED",
        )
        gates_pending = RegulatoryGateInput(
            entity_name=vendor_pending.name,
            entity_country="US",
            sensitivity="ELEVATED",
            supply_chain_tier=0,
            cmmc=CMMCInput(
                handles_cui=True,
                required_cmmc_level=2,
                current_cmmc_level=1,
                entity_has_active_poam=True,
            ),
        )

        _, result_clean = _run_pipeline(vendor_clean, gates_clean)
        assessment_pending, result_pending = _run_pipeline(vendor_pending, gates_pending)

        # The pending vendor should have higher gate proximity
        assert assessment_pending.gate_proximity_score > 0.0
        # And higher overall probability (or at least not lower)
        assert result_pending.calibrated_probability >= result_clean.calibrated_probability

    def test_multiple_pending_gates_stack(self):
        """Multiple pending gates should produce higher proximity than one."""
        vendor = clean_us_prime()

        gates_one = RegulatoryGateInput(
            entity_name=vendor.name,
            entity_country="US",
            sensitivity="ELEVATED",
            supply_chain_tier=0,
            cmmc=CMMCInput(
                handles_cui=True, required_cmmc_level=2,
                current_cmmc_level=1, entity_has_active_poam=True,
            ),
        )
        assessment_one = evaluate_regulatory_gates(gates_one)

        vendor2 = clean_us_prime()
        gates_two = RegulatoryGateInput(
            entity_name=vendor2.name,
            entity_country="US",
            sensitivity="ELEVATED",
            supply_chain_tier=0,
            cmmc=CMMCInput(
                handles_cui=True, required_cmmc_level=2,
                current_cmmc_level=1, entity_has_active_poam=True,
            ),
            foci=FOCIInput(
                entity_foreign_ownership_pct=0.15,
                entity_foreign_control_pct=0.10,
                foreign_controlling_country="DE",
                entity_foci_mitigation_status="IN_PROGRESS",
                entity_has_facility_clearance=True,
            ),
        )
        assessment_two = evaluate_regulatory_gates(gates_two)

        assert assessment_two.gate_proximity_score >= assessment_one.gate_proximity_score


# ============================================================================
# TEST: SINGLE SOURCE + BERRY AMENDMENT
# ============================================================================

class TestSupplyChainIntegration:
    def test_single_source_with_berry_pass(self):
        """Single source supplier, Berry applies but domestic = PASS."""
        vendor = single_source_critical()
        # Override to US for Berry compliance
        vendor.country = "US"
        gates = RegulatoryGateInput(
            entity_name=vendor.name,
            entity_country="US",
            sensitivity="ELEVATED",
            supply_chain_tier=2,
            berry=BerryAmendmentInput(
                applies_to_contract=True,
                item_category="specialty_metals",
                item_origin_country="US",
                entity_manufacturing_country="US",
            ),
        )
        assessment, result = _run_pipeline(vendor, gates)

        # Berry passes (domestic manufacturing)
        assert not any(g.gate_name == "Berry Amendment" and g.state == GateState.FAIL
                       for g in assessment.failed_gates)

        # But single source risk still elevates Layer 2
        assert result.calibrated_probability > 0.15
        assert any("Single-Source" in f["trigger"] for f in result.soft_flags) or \
               any("single source" in f.lower() for f in result.findings)


# ============================================================================
# TEST: CONTRACT INVARIANTS
# ============================================================================

class TestContractInvariants:
    def test_status_string_matches_enum(self):
        """Layer 1 RegulatoryStatus.value must be a string Layer 2 accepts."""
        for status in RegulatoryStatus:
            # These are the strings Layer 2 checks for
            assert status.value in (
                "COMPLIANT", "NON_COMPLIANT", "REQUIRES_REVIEW",
            )

    def test_non_compliant_always_disqualifies(self):
        """Invariant: NON_COMPLIANT from Layer 1 ALWAYS produces TIER_1_DISQUALIFIED in Layer 2."""
        vendor = clean_us_prime()
        gates = RegulatoryGateInput(
            entity_name=vendor.name,
            entity_country="US",
            sensitivity="ELEVATED",
            cmmc=CMMCInput(
                handles_cui=True, required_cmmc_level=3,
                current_cmmc_level=1,
            ),
        )
        assessment, result = _run_pipeline(vendor, gates)

        if assessment.status == RegulatoryStatus.NON_COMPLIANT:
            assert result.combined_tier == "TIER_1_DISQUALIFIED"
            assert result.program_recommendation == "DO_NOT_PROCEED"

    def test_compliant_never_disqualified_without_hard_stop(self):
        """Invariant: COMPLIANT + no hard stops should never be TIER_1_DISQUALIFIED."""
        vendor = clean_us_prime()
        gates = _make_clean_gate_input(
            entity_name=vendor.name, sensitivity="ELEVATED",
        )
        assessment, result = _run_pipeline(vendor, gates)

        assert assessment.status == RegulatoryStatus.COMPLIANT
        if not result.hard_stop_decisions:
            assert "DISQUALIFIED" not in result.combined_tier

    def test_gate_proximity_bounded_zero_one(self):
        """Gate proximity score should always be in [0, 1]."""
        for fixture_fn in [clean_us_prime, allied_conditional, cmmc_pending,
                           single_source_critical, clean_commercial]:
            vendor = fixture_fn()
            gates = _make_clean_gate_input(
                entity_name=vendor.name, country=vendor.country,
                sensitivity=vendor.dod.sensitivity,
            )
            assessment = evaluate_regulatory_gates(gates)
            assert 0.0 <= assessment.gate_proximity_score <= 1.0

    def test_probability_bounded_zero_one(self):
        """Layer 2 probability should always be in [0, 1]."""
        for fixture_fn in [clean_us_prime, adversary_soe, opaque_shell_company,
                           chinese_tech_company, clean_commercial]:
            vendor = fixture_fn()
            gates = _make_clean_gate_input(
                entity_name=vendor.name, country=vendor.country,
                sensitivity=vendor.dod.sensitivity,
            )
            _, result = _run_pipeline(vendor, gates)
            assert 0.0 <= result.calibrated_probability <= 1.0

    def test_ci_always_brackets_probability(self):
        """Confidence interval should always contain the point estimate."""
        for fixture_fn in [clean_us_prime, allied_conditional, cmmc_pending,
                           opaque_shell_company]:
            vendor = fixture_fn()
            gates = _make_clean_gate_input(
                entity_name=vendor.name, country=vendor.country,
                sensitivity=vendor.dod.sensitivity,
            )
            _, result = _run_pipeline(vendor, gates)
            assert result.interval_lower <= result.calibrated_probability
            assert result.interval_upper >= result.calibrated_probability
