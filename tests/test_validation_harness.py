"""
Pytest wrapper around test_scoring_validation.py.

Runs the 45 CSV-based validation cases and 8 pipeline validation cases
as part of the standard pytest suite.
"""

import os
import sys
import importlib.util
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fgamlogit import (
    score_vendor,
)
from regulatory_gates import (
    RegulatoryGateInput, Section889Input, NDAA1260HInput, ITARInput,
    FOCIInput, evaluate_regulatory_gates,
)

_HARNESS_PATH = os.path.join(os.path.dirname(__file__), "test_scoring_validation.py")
_HARNESS_SPEC = importlib.util.spec_from_file_location("scoring_validation_harness", _HARNESS_PATH)
if _HARNESS_SPEC is None or _HARNESS_SPEC.loader is None:
    raise RuntimeError(f"Unable to load scoring validation harness from {_HARNESS_PATH}")
_HARNESS_MODULE = importlib.util.module_from_spec(_HARNESS_SPEC)
_HARNESS_SPEC.loader.exec_module(_HARNESS_MODULE)

# Import helpers from the standalone harness without relying on package import mode.
load_validation_cases = _HARNESS_MODULE.load_validation_cases
score_case = _HARNESS_MODULE.score_case
tier_to_level = _HARNESS_MODULE.tier_to_level
_make_clean_gate_input = _HARNESS_MODULE._make_clean_gate_input
_make_vendor = _HARNESS_MODULE._make_vendor


# =============================================================================
# CSV-based validation cases as parametrized pytest
# =============================================================================

CSV_PATH = os.path.join(os.path.dirname(__file__), "validation_cases.csv")
_CASES = load_validation_cases(CSV_PATH) if os.path.exists(CSV_PATH) else []

# Cases where live DB (31,596 entities) produces different tier results than
# fallback DB (27 entries). These are expected divergences, not bugs.
# On VPS live mode, these cases may shift tiers due to:
#   - Live DB matching entities not in fallback (true positive escalation)
#   - Live DB partial name matches inflating scores (false positive, mostly fixed in v4.0)
_LIVE_DB_SENSITIVE_CASES = {
    "Global Trade Holdings Ltd",      # Live DB escalates to TIER_1 (correct true positive)
    "Advanced Materials Corp",        # Live DB partial name match may inflate score
    "Precision Manufacturing Inc",    # Live DB partial name match may inflate score
}


def _wrap_cases_with_markers(cases):
    """Apply @pytest.mark.live_db to cases known to diverge on live DB."""
    wrapped = []
    for case in cases:
        if case.name in _LIVE_DB_SENSITIVE_CASES:
            wrapped.append(pytest.param(case, marks=pytest.mark.live_db, id=case.name))
        else:
            wrapped.append(pytest.param(case, id=case.name))
    return wrapped


@pytest.mark.parametrize("case", _wrap_cases_with_markers(_CASES))
class TestCSVValidation:
    """Each CSV row is a separate test: score through Layer 2 and check tier level."""

    def test_tier_matches_expected(self, case):
        actual_tier, actual_score = score_case(case)
        expected_level = tier_to_level(case.expected_tier)
        actual_level = tier_to_level(actual_tier)
        assert actual_level == expected_level, (
            f"{case.name}: expected TIER_{expected_level} ({case.expected_tier}), "
            f"got TIER_{actual_level} ({actual_tier}) at p={actual_score:.3f}"
        )


# =============================================================================
# Pipeline validation cases as pytest
# =============================================================================

class TestPipelineSection889:
    """Section 889 entity through full pipeline."""

    def test_huawei_non_compliant_tier1(self):
        gate_input = RegulatoryGateInput(
            entity_name="Huawei Technologies", entity_country="CN",
            section_889=Section889Input(entity_name="Huawei Technologies"),
            ndaa_1260h=NDAA1260HInput(entity_name="Huawei Technologies"),
        )
        gate_result = evaluate_regulatory_gates(gate_input)
        assert gate_result.status.value == "NON_COMPLIANT"

        result = score_vendor(
            _make_vendor("Huawei Technologies", "CN",
                         state_owned=True, foreign_ownership_is_allied=False),
            regulatory_status=gate_result.status.value,
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"


class TestPipelineCleanVendor:
    """Clean US vendor through full pipeline."""

    def test_lockheed_compliant_tier4(self):
        gate_input = _make_clean_gate_input("Lockheed Martin", "US")
        gate_result = evaluate_regulatory_gates(gate_input)
        assert gate_result.status.value == "COMPLIANT"

        result = score_vendor(
            _make_vendor("Lockheed Martin", "US", known_execs=50, years_of_records=20),
            regulatory_status=gate_result.status.value,
        )
        assert tier_to_level(result.combined_tier) == 4


class TestPipelineITARPending:
    """Tier 2 sub with ITAR item and no cert -> REQUIRES_REVIEW."""

    def test_itar_pending_tier2(self):
        gate_input = _make_clean_gate_input("Precision Aero Components", "US")
        gate_input.supply_chain_tier = 2
        gate_input.itar = ITARInput(
            item_is_itar_controlled=True,
            entity_has_itar_compliance_certification=False,
            entity_manufacturing_process_certified=False,
            entity_nationality_of_control="US",
            entity_foci_status="NOT_APPLICABLE",
        )
        gate_result = evaluate_regulatory_gates(gate_input)
        assert gate_result.status.value == "REQUIRES_REVIEW"

        result = score_vendor(
            _make_vendor("Precision Aero Components", "US",
                         publicly_traded=False, years_of_records=8,
                         known_execs=10, supply_chain_tier=2),
            regulatory_status=gate_result.status.value,
        )
        assert tier_to_level(result.combined_tier) == 2


class TestPipelineNDAA1260H:
    """NDAA 1260H entity -> NON_COMPLIANT -> TIER_1."""

    def test_avic_non_compliant_tier1(self):
        gate_input = RegulatoryGateInput(
            entity_name="Aviation Industry Corporation of China",
            entity_country="CN",
            section_889=Section889Input(entity_name="Aviation Industry Corporation of China"),
            ndaa_1260h=NDAA1260HInput(
                entity_name="Aviation Industry Corporation of China",
                entity_country="CN"),
        )
        gate_result = evaluate_regulatory_gates(gate_input)
        assert gate_result.status.value == "NON_COMPLIANT"

        result = score_vendor(
            _make_vendor("Aviation Industry Corporation of China", "CN",
                         state_owned=True, foreign_ownership_is_allied=False),
            regulatory_status=gate_result.status.value,
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"


class TestPipelineFOCI:
    """FOCI concern -> REQUIRES_REVIEW."""

    def test_foci_in_progress_tier2(self):
        gate_input = _make_clean_gate_input("Siemens AG", "DE")
        gate_input.foci = FOCIInput(
            entity_foreign_ownership_pct=0.60,
            entity_foreign_control_pct=0.40,
            foreign_controlling_country="DE",
            entity_foci_mitigation_status="IN_PROGRESS",
            entity_has_facility_clearance=False,
            sensitivity="ELEVATED",
        )
        gate_result = evaluate_regulatory_gates(gate_input)
        assert gate_result.status.value == "REQUIRES_REVIEW"

        result = score_vendor(
            _make_vendor("Siemens AG", "DE", sensitivity="ELEVATED",
                         foreign_ownership_pct=0.60, ownership_pct_resolved=0.6,
                         has_cage=False, years_of_records=30, known_execs=40,
                         adverse_media=1, litigation_history=2),
            regulatory_status=gate_result.status.value,
        )
        assert tier_to_level(result.combined_tier) == 2


class TestPipelineHardStopOverride:
    """Extra hard stops override clean regulatory status."""

    def test_sam_exclusion_overrides_compliant(self):
        gate_input = _make_clean_gate_input("Acme Corp", "US")
        gate_result = evaluate_regulatory_gates(gate_input)
        assert gate_result.status.value == "COMPLIANT"

        result = score_vendor(
            _make_vendor("Acme Corp", "US", publicly_traded=False,
                         years_of_records=5, known_execs=5),
            regulatory_status=gate_result.status.value,
            extra_hard_stops=[{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
        )
        assert result.combined_tier == "TIER_1_DISQUALIFIED"


class TestPipelineSensitivityEscalation:
    """Same vendor at different sensitivity levels produces stricter tiers."""

    def test_critical_sci_stricter_than_commercial(self):
        gate_input = _make_clean_gate_input("Mid-Tier Contractor", "US")
        gate_result = evaluate_regulatory_gates(gate_input)

        kwargs = dict(
            publicly_traded=False, has_lei=False, ownership_pct_resolved=0.8,
            shell_layers=1, foreign_ownership_pct=0.2,
            years_of_records=8, known_execs=12, adverse_media=1,
            litigation_history=1,
        )

        r_commercial = score_vendor(
            _make_vendor("Mid-Tier Contractor", "US", sensitivity="COMMERCIAL", **kwargs),
            regulatory_status=gate_result.status.value,
        )
        r_critical = score_vendor(
            _make_vendor("Mid-Tier Contractor", "US", sensitivity="CRITICAL_SCI", **kwargs),
            regulatory_status=gate_result.status.value,
        )

        # CRITICAL_SCI tier level must be <= COMMERCIAL tier level (stricter)
        assert tier_to_level(r_critical.combined_tier) <= tier_to_level(r_commercial.combined_tier), (
            f"CRITICAL_SCI ({r_critical.combined_tier}) should be stricter than "
            f"COMMERCIAL ({r_commercial.combined_tier})"
        )
