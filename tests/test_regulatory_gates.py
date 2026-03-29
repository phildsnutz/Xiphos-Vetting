"""
Comprehensive unit tests for regulatory_gates.py module.

Tests all 10 regulatory gates, helper functions, and the orchestrator.
Pure Python tests (no DB, no I/O, no mocking required).

Test coverage:
  - _normalize() — string normalization
  - _matches_list() — entity matching logic
  - evaluate_section_889() — Gate 1
  - evaluate_itar() — Gate 2
  - evaluate_ear() — Gate 3
  - evaluate_specialty_metals() — Gate 4
  - evaluate_cdi() — Gate 5
  - evaluate_cmmc() — Gate 6
  - evaluate_foci() — Gate 7
  - evaluate_ndaa_1260h() — Gate 8
  - evaluate_cfius() — Gate 9
  - evaluate_berry_amendment() — Gate 10
  - _compute_gate_proximity() — proximity scoring
  - evaluate_regulatory_gates() — orchestrator
  - quick_screen() — convenience name-only check
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import pytest
from regulatory_gates import (
    GateState, RegulatoryStatus,
    Section889Input, ITARInput, EARInput, SpecialtyMetalsInput, CDIInput,
    CMMCInput, FOCIInput, NDAA1260HInput, CFIUSInput, BerryAmendmentInput,
    DeemedExportGateInput, RedFlagGateInput, USMLControlGateInput,
    RegulatoryGateInput,
    GateResult, _normalize, _matches_list,
    evaluate_section_889, evaluate_itar, evaluate_ear, evaluate_specialty_metals,
    evaluate_cdi, evaluate_cmmc, evaluate_foci, evaluate_ndaa_1260h,
    evaluate_cfius, evaluate_berry_amendment,
    evaluate_deemed_export_risk, evaluate_red_flags, evaluate_usml_control,
    _compute_gate_proximity, evaluate_regulatory_gates,
    quick_screen,
    SECTION_889_PROHIBITED,
)


# ─────────────────────────────────────────────────────────────────────────────
# TestNormalize
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalize:
    """Test _normalize() helper function."""

    def test_normalize_basic_case(self):
        """Test basic case normalization."""
        result = _normalize("Huawei Technologies")
        assert result == "HUAWEI TECHNOLOGIES"

    def test_normalize_with_punctuation(self):
        """Test punctuation stripping."""
        result = _normalize("Huawei, Inc. (USA) & Co.")
        # _normalize strips punctuation but may leave multiple spaces
        assert "HUAWEI" in result
        assert "INC" in result
        assert "USA" in result
        assert "CO" in result

    def test_normalize_empty_string(self):
        """Test empty string handling."""
        result = _normalize("")
        assert result == ""


# ─────────────────────────────────────────────────────────────────────────────
# TestMatchesList
# ─────────────────────────────────────────────────────────────────────────────

class TestMatchesList:
    """Test _matches_list() matching logic."""

    def test_matches_list_direct_key_match(self):
        """Test direct key match against prohibited dict."""
        matched, key = _matches_list("HUAWEI TECHNOLOGIES", SECTION_889_PROHIBITED)
        assert matched is True
        assert key == "HUAWEI"

    def test_matches_list_alias_match(self):
        """Test alias matching."""
        matched, key = _matches_list("HONOR DEVICE TECHNOLOGIES", SECTION_889_PROHIBITED)
        assert matched is True
        assert key == "HUAWEI"

    def test_matches_list_substring_containment(self):
        """Test substring containment matching."""
        matched, key = _matches_list("SHENZHEN ZTE CORPORATION", SECTION_889_PROHIBITED)
        assert matched is True
        assert key == "ZTE"

    def test_matches_list_no_match(self):
        """Test non-matching entity."""
        matched, key = _matches_list("LOCKHEED MARTIN CORPORATION", SECTION_889_PROHIBITED)
        assert matched is False
        assert key == ""

    def test_matches_list_case_insensitive(self):
        """Test case-insensitive matching."""
        matched, key = _matches_list("huawei tech", SECTION_889_PROHIBITED)
        assert matched is True
        assert key == "HUAWEI"


# ─────────────────────────────────────────────────────────────────────────────
# TestSection889
# ─────────────────────────────────────────────────────────────────────────────

class TestSection889:
    """Test Gate 1: Section 889 (FY2019 NDAA) — Prohibited telecom entities."""

    def test_section_889_huawei_direct_match(self):
        """Test FAIL for direct Huawei match."""
        inp = Section889Input(entity_name="Huawei Technologies")
        result = evaluate_section_889(inp)
        assert result.state == GateState.FAIL
        assert result.gate_id == 1
        assert result.severity == "CRITICAL"

    def test_section_889_zte_alias_match(self):
        """Test FAIL for ZTE alias."""
        inp = Section889Input(entity_name="Zhongxing Telecommunication Equipment")
        result = evaluate_section_889(inp)
        assert result.state == GateState.FAIL

    def test_section_889_subsidiary_match(self):
        """Test FAIL when subsidiary is on prohibited list."""
        inp = Section889Input(
            entity_name="Clean Company",
            subsidiaries=["Hikvision Digital Technology"]
        )
        result = evaluate_section_889(inp)
        assert result.state == GateState.FAIL

    def test_section_889_clean_entity_pass(self):
        """Test PASS for clean entity."""
        inp = Section889Input(entity_name="Lockheed Martin Corporation")
        result = evaluate_section_889(inp)
        assert result.state == GateState.PASS

    def test_section_889_parent_company_match(self):
        """Test FAIL when parent company is prohibited."""
        inp = Section889Input(
            entity_name="Subsidiary LLC",
            parent_companies=["Dahua Technology"]
        )
        result = evaluate_section_889(inp)
        assert result.state == GateState.FAIL


# ─────────────────────────────────────────────────────────────────────────────
# TestITAR
# ─────────────────────────────────────────────────────────────────────────────

class TestITAR:
    """Test Gate 2: ITAR Compliance — US Munitions List items."""

    def test_itar_not_controlled_skip(self):
        """Test SKIP when item is not ITAR-controlled."""
        inp = ITARInput(item_is_itar_controlled=False)
        result = evaluate_itar(inp)
        assert result.state == GateState.SKIP
        assert result.gate_id == 2

    def test_itar_tier2_certified_pass(self):
        """Test PASS for Tier 2-3 with ITAR certification."""
        inp = ITARInput(
            item_is_itar_controlled=True,
            supply_chain_tier=2,
            entity_has_itar_compliance_certification=True,
            entity_manufacturing_process_certified=True
        )
        result = evaluate_itar(inp)
        assert result.state == GateState.PASS

    def test_itar_tier2_uncertified_pending(self):
        """Test PENDING for Tier 2-3 without certification."""
        inp = ITARInput(
            item_is_itar_controlled=True,
            supply_chain_tier=3,
            entity_has_itar_compliance_certification=False
        )
        result = evaluate_itar(inp)
        assert result.state == GateState.PENDING

    def test_itar_sap_with_foreign_ownership_fail(self):
        """Test FAIL for SAP/SCI with any foreign ownership."""
        inp = ITARInput(
            item_is_itar_controlled=True,
            sensitivity="CRITICAL_SAP",
            supply_chain_tier=0,
            entity_foreign_ownership_pct=5.0
        )
        result = evaluate_itar(inp)
        assert result.state == GateState.FAIL
        assert result.severity == "CRITICAL"

    def test_itar_sap_no_foreign_ownership_pass(self):
        """Test PASS for SAP/SCI with 0% foreign ownership."""
        inp = ITARInput(
            item_is_itar_controlled=True,
            sensitivity="CRITICAL_SCI",
            supply_chain_tier=0,
            entity_foreign_ownership_pct=0.0
        )
        result = evaluate_itar(inp)
        assert result.state == GateState.PASS

    def test_itar_elevated_with_voting_agreement_pass(self):
        """Test PASS for ELEVATED with voting agreement and FOCI mitigated."""
        inp = ITARInput(
            item_is_itar_controlled=True,
            sensitivity="ELEVATED",
            supply_chain_tier=0,
            entity_foreign_ownership_pct=10.0,
            entity_has_approved_voting_agreement=True,
            entity_foci_status="MITIGATED"
        )
        result = evaluate_itar(inp)
        assert result.state == GateState.PASS

    def test_itar_elevated_without_mitigation_pending(self):
        """Test PENDING for ELEVATED with foreign ownership but no mitigation."""
        inp = ITARInput(
            item_is_itar_controlled=True,
            sensitivity="ELEVATED",
            supply_chain_tier=0,
            entity_foreign_ownership_pct=15.0,
            entity_has_approved_voting_agreement=False,
            entity_foci_status="UNMITIGATED"
        )
        result = evaluate_itar(inp)
        assert result.state == GateState.PENDING

    def test_itar_controlled_with_foci_mitigated_low_cmmc_pending(self):
        """Test PENDING for CONTROLLED with FOCI mitigated but low CMMC."""
        inp = ITARInput(
            item_is_itar_controlled=True,
            sensitivity="CONTROLLED",
            supply_chain_tier=1,
            entity_foreign_ownership_pct=20.0,
            entity_foci_status="MITIGATED",
            entity_cmmc_level=1
        )
        result = evaluate_itar(inp)
        assert result.state == GateState.PENDING


# ─────────────────────────────────────────────────────────────────────────────
# TestCMMC
# ─────────────────────────────────────────────────────────────────────────────

class TestCMMC:
    """Test Gate 6: CMMC 2.0 — Cybersecurity maturity."""

    def test_cmmc_no_cui_skip(self):
        """Test SKIP when entity doesn't handle CUI."""
        inp = CMMCInput(handles_cui=False)
        result = evaluate_cmmc(inp)
        assert result.state == GateState.SKIP
        assert result.gate_id == 6

    def test_cmmc_current_meets_required_pass(self):
        """Test PASS when current level >= required level."""
        inp = CMMCInput(
            handles_cui=True,
            required_cmmc_level=2,
            current_cmmc_level=2
        )
        result = evaluate_cmmc(inp)
        assert result.state == GateState.PASS

    def test_cmmc_gap_with_active_poam(self):
        """Test level gap with active POAM. Gate may FAIL or PENDING depending on gap size."""
        inp = CMMCInput(
            handles_cui=True,
            required_cmmc_level=3,
            current_cmmc_level=1,
            entity_has_active_poam=True
        )
        result = evaluate_cmmc(inp)
        # Large gap (3 vs 1) may FAIL even with POAM
        assert result.state in (GateState.FAIL, GateState.PENDING)

    def test_cmmc_gap_without_poam_fail(self):
        """Test FAIL for level gap without POAM."""
        inp = CMMCInput(
            handles_cui=True,
            required_cmmc_level=2,
            current_cmmc_level=0,
            entity_has_active_poam=False
        )
        result = evaluate_cmmc(inp)
        assert result.state == GateState.FAIL


# ─────────────────────────────────────────────────────────────────────────────
# TestFOCI
# ─────────────────────────────────────────────────────────────────────────────

class TestFOCI:
    """Test Gate 7: FOCI (Foreign Ownership/Control) — NIS Regulation 32 CFR Part 2004."""

    def test_foci_no_foreign_ownership_pass(self):
        """Test PASS when entity has no foreign ownership."""
        inp = FOCIInput(
            entity_foreign_ownership_pct=0.0,
            entity_foreign_control_pct=0.0
        )
        result = evaluate_foci(inp)
        assert result.state == GateState.PASS

    def test_foci_mitigated_pass(self):
        """Test PASS when FOCI is mitigated."""
        inp = FOCIInput(
            entity_foreign_ownership_pct=25.0,
            entity_foci_mitigation_status="MITIGATED",
            dss_approval_obtained=True
        )
        result = evaluate_foci(inp)
        assert result.state == GateState.PASS

    def test_foci_in_progress_pending(self):
        """Test PENDING when FOCI mitigation is in progress."""
        inp = FOCIInput(
            entity_foreign_ownership_pct=30.0,
            entity_foci_mitigation_status="IN_PROGRESS"
        )
        result = evaluate_foci(inp)
        assert result.state == GateState.PENDING

    def test_foci_unmitigated_high_ownership(self):
        """Test non-PASS for unmitigated high foreign ownership."""
        inp = FOCIInput(
            entity_foreign_ownership_pct=50.0,
            entity_foreign_control_pct=0.0,
            entity_foci_mitigation_status="UNMITIGATED"
        )
        result = evaluate_foci(inp)
        # Unmitigated 50% ownership should not pass
        assert result.state in (GateState.FAIL, GateState.PENDING)


# ─────────────────────────────────────────────────────────────────────────────
# TestNDAA1260H
# ─────────────────────────────────────────────────────────────────────────────

class TestNDAA1260H:
    """Test Gate 8: NDAA Section 1260H CMC List — Chinese Military Companies."""

    def test_ndaa_1260h_norinco_match_fail(self):
        """Test FAIL for NORINCO match."""
        inp = NDAA1260HInput(entity_name="China North Industries Group Corporation")
        result = evaluate_ndaa_1260h(inp)
        assert result.state == GateState.FAIL
        assert result.gate_id == 8

    def test_ndaa_1260h_avic_alias_fail(self):
        """Test FAIL for AVIC alias."""
        inp = NDAA1260HInput(entity_name="Aviation Industry Corporation of China")
        result = evaluate_ndaa_1260h(inp)
        assert result.state == GateState.FAIL

    def test_ndaa_1260h_clean_entity_pass(self):
        """Test PASS for clean entity."""
        inp = NDAA1260HInput(entity_name="Boeing Defense, Space & Security")
        result = evaluate_ndaa_1260h(inp)
        assert result.state == GateState.PASS


# ─────────────────────────────────────────────────────────────────────────────
# TestCFIUS
# ─────────────────────────────────────────────────────────────────────────────

class TestCFIUS:
    """Test Gate 9: CFIUS Jurisdiction — Foreign investment screening."""

    def test_cfius_no_foreign_acquirer_skip(self):
        """Test SKIP when no foreign acquirer involved."""
        inp = CFIUSInput(transaction_involves_foreign_acquirer=False)
        result = evaluate_cfius(inp)
        assert result.state == GateState.SKIP
        assert result.gate_id == 9

    def test_cfius_mandatory_filing_not_filed_fail(self):
        """Test FAIL for mandatory filing that wasn't filed."""
        inp = CFIUSInput(
            transaction_involves_foreign_acquirer=True,
            foreign_acquirer_country="CN",
            business_involves_critical_technology=True,
            transaction_is_mandatory_filing=True,
            cfius_notice_filed=False
        )
        result = evaluate_cfius(inp)
        assert result.state == GateState.FAIL

    def test_cfius_clearance_obtained_pass(self):
        """Test PASS when CFIUS clearance obtained."""
        inp = CFIUSInput(
            transaction_involves_foreign_acquirer=True,
            foreign_acquirer_country="CA",
            transaction_is_mandatory_filing=True,
            cfius_notice_filed=True,
            cfius_clearance_obtained=True
        )
        result = evaluate_cfius(inp)
        assert result.state == GateState.PASS


# ─────────────────────────────────────────────────────────────────────────────
# TestGateProximity
# ─────────────────────────────────────────────────────────────────────────────

class TestGateProximity:
    """Test _compute_gate_proximity() scoring."""

    def test_gate_proximity_no_failures_zero(self):
        """Test 0.0 score when no failures or pending."""
        score = _compute_gate_proximity([], [])
        assert score == 0.0

    def test_gate_proximity_one_critical_fail(self):
        """Test non-zero score with one CRITICAL failure."""
        gate = GateResult(
            gate_id=1, gate_name="Section 889",
            state=GateState.FAIL, severity="CRITICAL",
            regulation="Test", details="Test", mitigation="N/A", confidence=0.9
        )
        score = _compute_gate_proximity([gate], [])
        assert 0.0 < score <= 1.0

    def test_gate_proximity_mix_of_fail_and_pending(self):
        """Test scoring with mix of failed and pending gates."""
        fail_gate = GateResult(
            gate_id=1, gate_name="Section 889",
            state=GateState.FAIL, severity="HIGH",
            regulation="Test", details="Test", mitigation="N/A", confidence=0.9
        )
        pending_gate = GateResult(
            gate_id=2, gate_name="ITAR",
            state=GateState.PENDING, severity="MEDIUM",
            regulation="Test", details="Test", mitigation="N/A", confidence=0.85
        )
        score = _compute_gate_proximity([fail_gate], [pending_gate])
        assert 0.0 < score <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# TestOrchestrator
# ─────────────────────────────────────────────────────────────────────────────

class TestOrchestrator:
    """Test evaluate_regulatory_gates() orchestrator."""

    def test_orchestrator_all_clean_compliant(self):
        """Test COMPLIANT status when all gates pass/skip."""
        inp = RegulatoryGateInput(
            entity_name="Clean Company Inc",
            entity_country="US",
            sensitivity="COMMERCIAL"
        )
        assessment = evaluate_regulatory_gates(inp)
        assert assessment.status == RegulatoryStatus.COMPLIANT
        assert len(assessment.failed_gates) == 0
        assert assessment.is_dod_eligible is True
        assert assessment.is_dod_qualified is True

    def test_orchestrator_one_fail_non_compliant(self):
        """Test NON_COMPLIANT status with one gate failure."""
        inp = RegulatoryGateInput(
            entity_name="Huawei Technologies",
            entity_country="CN",
            sensitivity="COMMERCIAL"
        )
        assessment = evaluate_regulatory_gates(inp)
        assert assessment.status == RegulatoryStatus.NON_COMPLIANT
        assert len(assessment.failed_gates) > 0
        assert assessment.is_dod_eligible is False

    def test_orchestrator_one_pending_requires_review(self):
        """Test REQUIRES_REVIEW status with pending gates but no failures."""
        inp = RegulatoryGateInput(
            entity_name="Foreign-Owned Corp",
            entity_country="CA",
            sensitivity="CONTROLLED",
            itar=ITARInput(
                item_is_itar_controlled=True,
                sensitivity="CONTROLLED",
                entity_foreign_ownership_pct=25.0,
                entity_foci_status="IN_PROGRESS"
            )
        )
        assessment = evaluate_regulatory_gates(inp)
        assert assessment.status == RegulatoryStatus.REQUIRES_REVIEW
        assert len(assessment.failed_gates) == 0
        assert len(assessment.pending_gates) > 0

    def test_orchestrator_huawei_triggers_889_fail(self):
        """Test that Huawei triggers Section 889 failure."""
        inp = RegulatoryGateInput(
            entity_name="Huawei Technologies",
            section_889=Section889Input(entity_name="Huawei Technologies")
        )
        assessment = evaluate_regulatory_gates(inp)
        assert assessment.status == RegulatoryStatus.NON_COMPLIANT
        # Find the Section 889 gate result
        section_889_failures = [g for g in assessment.failed_gates if g.gate_id == 1]
        assert len(section_889_failures) > 0

    def test_orchestrator_dod_eligibility_flags(self):
        """Test DoD eligibility flags are set correctly."""
        # Clean entity
        inp_clean = RegulatoryGateInput(
            entity_name="Raytheon Technologies",
            sensitivity="COMMERCIAL"
        )
        assessment_clean = evaluate_regulatory_gates(inp_clean)
        assert assessment_clean.is_dod_eligible is True
        assert assessment_clean.is_dod_qualified is True

        # Entity with failures
        inp_fail = RegulatoryGateInput(
            entity_name="Huawei",
            section_889=Section889Input(entity_name="Huawei")
        )
        assessment_fail = evaluate_regulatory_gates(inp_fail)
        assert assessment_fail.is_dod_eligible is False
        assert assessment_fail.is_dod_qualified is False


# ─────────────────────────────────────────────────────────────────────────────
# TestQuickScreen
# ─────────────────────────────────────────────────────────────────────────────

class TestQuickScreen:
    """Test quick_screen() convenience function."""

    def test_quick_screen_clean_entity(self):
        """Test quick_screen with clean entity."""
        result = quick_screen("Lockheed Martin Corporation")
        assert result["matched_section_889"] is False
        assert result["matched_cmc"] is False

    def test_quick_screen_889_match(self):
        """Test quick_screen with Section 889 prohibited entity."""
        result = quick_screen("Huawei Technologies", parent_companies=["Clean Corp"])
        assert result["matched_section_889"] is True
        assert result["is_disqualified"] is True

    def test_quick_screen_cmc_match(self):
        """Test quick_screen with CMC list match."""
        result = quick_screen(
            "Clean Subsidiary",
            parent_companies=["Aviation Industry Corporation of China"]
        )
        assert result["matched_cmc"] is True
        assert result["is_disqualified"] is True


# ─────────────────────────────────────────────────────────────────────────────
# TestEAR (minimal coverage)
# ─────────────────────────────────────────────────────────────────────────────

class TestEAR:
    """Test Gate 3: EAR — Dual-use item controls."""

    def test_ear_no_ccl_category_skip(self):
        """Test SKIP when item has no CCL category."""
        inp = EARInput(item_ear_ccl_category="")
        result = evaluate_ear(inp)
        assert result.state == GateState.SKIP
        assert result.gate_id == 3


# ─────────────────────────────────────────────────────────────────────────────
# TestSpecialtyMetals (minimal coverage)
# ─────────────────────────────────────────────────────────────────────────────

class TestSpecialtyMetals:
    """Test Gate 4: DFARS Specialty Metals — Melting/refining origin."""

    def test_specialty_metals_no_metals_skip(self):
        """Test SKIP when item contains no specialty metals."""
        inp = SpecialtyMetalsInput(item_contains_specialty_metals=False)
        result = evaluate_specialty_metals(inp)
        assert result.state == GateState.SKIP
        assert result.gate_id == 4


# ─────────────────────────────────────────────────────────────────────────────
# TestCDI (minimal coverage)
# ─────────────────────────────────────────────────────────────────────────────

class TestCDI:
    """Test Gate 5: DFARS CDI — Covered Defense Info handling."""

    def test_cdi_no_defense_info_skip(self):
        """Test SKIP when item doesn't involve covered defense info."""
        inp = CDIInput(item_involves_covered_defense_info=False)
        result = evaluate_cdi(inp)
        assert result.state == GateState.SKIP
        assert result.gate_id == 5


# ─────────────────────────────────────────────────────────────────────────────
# TestBerryAmendment (minimal coverage)
# ─────────────────────────────────────────────────────────────────────────────

class TestBerryAmendment:
    """Test Gate 10: Berry Amendment — Domestic source requirements."""

    def test_berry_amendment_doesnt_apply_skip(self):
        """Test SKIP when Berry Amendment doesn't apply."""
        inp = BerryAmendmentInput(applies_to_contract=False)
        result = evaluate_berry_amendment(inp)
        assert result.state == GateState.SKIP
        assert result.gate_id == 10


# ─────────────────────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegration:
    """Integration tests for realistic scenarios."""

    def test_integration_us_prime_contractor_clean(self):
        """Test clean US prime contractor scenario."""
        inp = RegulatoryGateInput(
            entity_name="Raytheon Technologies Corporation",
            entity_country="US",
            sensitivity="SECRET",
            supply_chain_tier=0,
            section_889=Section889Input(
                entity_name="Raytheon Technologies Corporation"
            ),
            ndaa_1260h=NDAA1260HInput(
                entity_name="Raytheon Technologies Corporation",
                entity_country="US"
            ),
            cmmc=CMMCInput(
                handles_cui=True,
                required_cmmc_level=2,
                current_cmmc_level=3
            ),
            foci=FOCIInput(
                entity_foreign_ownership_pct=0.0,
                entity_foreign_control_pct=0.0
            )
        )
        assessment = evaluate_regulatory_gates(inp)
        assert assessment.status == RegulatoryStatus.COMPLIANT
        assert assessment.is_dod_qualified is True

    def test_integration_foreign_owned_needs_mitigation(self):
        """Test foreign-owned entity needing FOCI mitigation."""
        inp = RegulatoryGateInput(
            entity_name="Allied European Supplier",
            entity_country="DE",
            sensitivity="CONTROLLED",
            supply_chain_tier=1,
            section_889=Section889Input(
                entity_name="Allied European Supplier"
            ),
            foci=FOCIInput(
                entity_foreign_ownership_pct=40.0,
                foreign_controlling_country="DE",
                entity_foci_mitigation_status="IN_PROGRESS"
            )
        )
        assessment = evaluate_regulatory_gates(inp)
        assert assessment.status == RegulatoryStatus.REQUIRES_REVIEW
        assert assessment.is_dod_eligible is True
        assert assessment.is_dod_qualified is False

    def test_integration_prohibited_entity_fails_immediately(self):
        """Test that prohibited entity fails immediately."""
        inp = RegulatoryGateInput(
            entity_name="Hikvision Digital Technology",
            sensitivity="UNCLASSIFIED",
            section_889=Section889Input(
                entity_name="Hikvision Digital Technology"
            )
        )
        assessment = evaluate_regulatory_gates(inp)
        assert assessment.status == RegulatoryStatus.NON_COMPLIANT
        assert assessment.is_dod_eligible is False


# ─────────────────────────────────────────────────────────────────────────────
# TestDeemedExportGate
# ─────────────────────────────────────────────────────────────────────────────

class TestDeemedExportGate:
    """Test Gate 11: Deemed Export Risk (22 CFR 120.17)."""

    def test_deemed_export_no_foreign_nationals_skip(self):
        """Test SKIP when no foreign nationals provided."""
        inp = DeemedExportGateInput(foreign_nationals=[])
        result = evaluate_deemed_export_risk(inp)
        assert result.gate_id == 11
        assert result.state == GateState.SKIP
        assert result.severity == "MEDIUM"

    def test_deemed_export_high_risk_fail(self):
        """Test FAIL when risk score >= 0.70."""
        inp = DeemedExportGateInput(
            foreign_nationals=[
                {"nationality": "CN", "role": "engineer", "access_level": "technical_data"},
                {"nationality": "IR", "role": "manager", "access_level": "technical_data"},
            ],
            tcp_status="MISSING",
            usml_category=1,
            facility_clearance="NONE"
        )
        result = evaluate_deemed_export_risk(inp)
        assert result.gate_id == 11
        assert result.state == GateState.FAIL
        assert result.severity == "CRITICAL"

    def test_deemed_export_moderate_risk_pending(self):
        """Test PENDING when risk score 0.30-0.69."""
        inp = DeemedExportGateInput(
            foreign_nationals=[
                {"nationality": "DE", "role": "analyst", "access_level": "technical_data"},
            ],
            tcp_status="PENDING",
            usml_category=0,
            facility_clearance="UNCLASSIFIED"
        )
        result = evaluate_deemed_export_risk(inp)
        assert result.gate_id == 11
        assert result.state == GateState.PENDING
        assert result.severity == "HIGH"

    def test_deemed_export_low_risk_pass(self):
        """Test PASS when risk score < 0.30."""
        inp = DeemedExportGateInput(
            foreign_nationals=[
                {"nationality": "CA", "role": "contractor", "access_level": "general"},
            ],
            tcp_status="IMPLEMENTED",
            usml_category=0,
            facility_clearance="UNCLASSIFIED"
        )
        result = evaluate_deemed_export_risk(inp)
        assert result.gate_id == 11
        assert result.state == GateState.PASS


# ─────────────────────────────────────────────────────────────────────────────
# TestRedFlagGate
# ─────────────────────────────────────────────────────────────────────────────

class TestRedFlagGate:
    """Test Gate 12: End-Use Red Flags (BIS/DDTC)."""

    def test_red_flags_no_transaction_skip(self):
        """Test SKIP when no transaction data provided."""
        inp = RedFlagGateInput(transaction={})
        result = evaluate_red_flags(inp)
        assert result.gate_id == 12
        assert result.state == GateState.SKIP
        assert result.severity == "MEDIUM"

    def test_red_flags_high_score_fail(self):
        """Test FAIL when score >= 0.60."""
        inp = RedFlagGateInput(
            transaction={
                "routing": ["AE", "HK"],
                "customer_reluctance_on_end_use": True,
                "payment_method": "cash",
                "order_quantity": 1,
                "customer_prior_orders": False,
                "end_use_stated": "",
                "packaging_description": "discrete",
                "delivery_to_freight_forwarder": True,
                "declined_installation_training": True,
                "end_user_description_clarity": "missing",
            },
            vendor_country="SG",
            end_user_country="KP",
            usml_category=1
        )
        result = evaluate_red_flags(inp)
        assert result.gate_id == 12
        assert result.state == GateState.FAIL
        assert result.severity == "HIGH"

    def test_red_flags_moderate_score_pending(self):
        """Test PENDING when score 0.25-0.59."""
        inp = RedFlagGateInput(
            transaction={
                "routing": ["AE"],
                "customer_reluctance_on_end_use": False,
                "payment_method": "wire",
                "order_quantity": 10,
                "customer_prior_orders": False,
                "end_use_stated": "commercial",
                "packaging_description": "standard",
                "delivery_to_freight_forwarder": True,
                "declined_installation_training": False,
                "end_user_description_clarity": "vague",
            },
            vendor_country="US",
            end_user_country="RU"
        )
        result = evaluate_red_flags(inp)
        assert result.gate_id == 12
        assert result.state == GateState.PENDING
        assert result.severity == "MEDIUM"

    def test_red_flags_low_score_pass(self):
        """Test PASS when score < 0.25."""
        inp = RedFlagGateInput(
            transaction={
                "routing": ["US"],
                "customer_reluctance_on_end_use": False,
                "payment_method": "letter_of_credit",
                "order_quantity": 100,
                "customer_prior_orders": True,
                "end_use_stated": "detailed technical description",
                "packaging_description": "standard commercial",
                "delivery_to_freight_forwarder": False,
                "declined_installation_training": False,
                "end_user_description_clarity": "detailed",
            },
            vendor_country="US",
            end_user_country="FR"
        )
        result = evaluate_red_flags(inp)
        assert result.gate_id == 12
        assert result.state == GateState.PASS


# ─────────────────────────────────────────────────────────────────────────────
# TestUSMLControlGate
# ─────────────────────────────────────────────────────────────────────────────

class TestUSMLControlGate:
    """Test Gate 13: USML Category Control (22 CFR 121)."""

    def test_usml_control_no_category_skip(self):
        """Test SKIP when usml_category is 0."""
        inp = USMLControlGateInput(usml_category=0)
        result = evaluate_usml_control(inp)
        assert result.gate_id == 13
        assert result.state == GateState.SKIP

    def test_usml_control_critical_to_prohibited_fail(self):
        """Test FAIL when CRITICAL category to prohibited country."""
        inp = USMLControlGateInput(
            usml_category=1,  # Firearms (CRITICAL)
            vendor_country="CN",  # China (prohibited)
            itar_prohibited_countries=["CN", "IR", "KP", "SY", "CU"],
            itar_elevated_scrutiny_countries=["RU", "BY", "VE", "ZW"]
        )
        result = evaluate_usml_control(inp)
        assert result.gate_id == 13
        assert result.state == GateState.FAIL
        assert result.severity == "CRITICAL"

    def test_usml_control_high_to_elevated_pending(self):
        """Test PENDING when HIGH category to elevated scrutiny country."""
        inp = USMLControlGateInput(
            usml_category=12,  # Assume HIGH risk category
            vendor_country="RU",  # Russia (elevated scrutiny)
            itar_prohibited_countries=["CN", "IR", "KP", "SY", "CU"],
            itar_elevated_scrutiny_countries=["RU", "BY", "VE", "ZW"]
        )
        result = evaluate_usml_control(inp)
        assert result.gate_id == 13
        assert result.state == GateState.PENDING
        assert result.severity == "HIGH"

    def test_usml_control_any_to_friendly_pass(self):
        """Test PASS for any category to friendly country."""
        inp = USMLControlGateInput(
            usml_category=1,
            vendor_country="DE",  # Germany (NATO ally)
            itar_prohibited_countries=["CN", "IR", "KP", "SY", "CU"],
            itar_elevated_scrutiny_countries=["RU", "BY", "VE", "ZW"]
        )
        result = evaluate_usml_control(inp)
        assert result.gate_id == 13
        assert result.state == GateState.PASS


# ─────────────────────────────────────────────────────────────────────────────
# TestOptionalGatesIntegration
# ─────────────────────────────────────────────────────────────────────────────

class TestOptionalGatesIntegration:
    """Test integration of optional ITAR gates (11-13)."""

    def test_itar_gates_only_run_when_enabled(self):
        """Test that gates 11-13 only run when enabled."""
        inp = RegulatoryGateInput(
            entity_name="Test Corp",
            enabled_gates=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],  # Exclude 11-13
            section_889=Section889Input(entity_name="Test Corp"),
            deemed_export=DeemedExportGateInput(
                foreign_nationals=[{"nationality": "CN", "role": "engineer", "access_level": "technical_data"}],
                tcp_status="MISSING"
            )
        )
        assessment = evaluate_regulatory_gates(inp)
        # Gates 11-13 should not be in results
        gate_ids = [r.gate_id for r in assessment.passed_gates + assessment.failed_gates + assessment.pending_gates + assessment.skipped_gates]
        assert 11 not in gate_ids
        assert 12 not in gate_ids
        assert 13 not in gate_ids

    def test_itar_gates_all_enabled(self):
        """Test evaluation with all gates 1-13 enabled."""
        inp = RegulatoryGateInput(
            entity_name="Export Test Corp",
            entity_country="US",
            enabled_gates=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
            section_889=Section889Input(entity_name="Export Test Corp"),
            deemed_export=DeemedExportGateInput(
                foreign_nationals=[
                    {"nationality": "CA", "role": "contractor", "access_level": "general"}
                ],
                tcp_status="IMPLEMENTED"
            ),
            red_flag=RedFlagGateInput(
                transaction={
                    "routing": ["US"],
                    "customer_reluctance_on_end_use": False,
                    "payment_method": "wire",
                    "customer_prior_orders": True,
                },
                vendor_country="US",
                end_user_country="FR"
            ),
            usml_control=USMLControlGateInput(
                usml_category=0,  # Not applicable
            )
        )
        assessment = evaluate_regulatory_gates(inp)
        # All gates should be evaluated
        all_gate_ids = [r.gate_id for r in assessment.passed_gates + assessment.failed_gates + assessment.pending_gates + assessment.skipped_gates]
        assert 11 in all_gate_ids or any(r.gate_id == 11 for r in assessment.skipped_gates)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
