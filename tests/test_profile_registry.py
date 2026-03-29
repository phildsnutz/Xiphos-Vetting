import os
import sys


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from compliance_profiles import ComplianceProfile, get_profile
from fgamlogit import (
    DataQuality,
    DoDContext,
    ExecProfile,
    OwnershipProfile,
    VendorInputV5,
    score_vendor,
)
from profiles import profile_to_dict


def _clean_vendor(profile: str) -> VendorInputV5:
    return VendorInputV5(
        name="Precision Systems Group",
        country="US",
        ownership=OwnershipProfile(
            publicly_traded=True,
            beneficial_owner_known=True,
            ownership_pct_resolved=1.0,
        ),
        data_quality=DataQuality(
            has_lei=True,
            has_cage=True,
            has_duns=True,
            has_tax_id=True,
            has_audited_financials=True,
            years_of_records=12,
        ),
        exec_profile=ExecProfile(known_execs=8),
        dod=DoDContext(sensitivity="CONTROLLED", supply_chain_tier=1),
        compliance_profile=profile,
    )


def test_legacy_profile_enum_accepts_runtime_profile_ids():
    assert ComplianceProfile("defense_acquisition") == ComplianceProfile.DEFENSE_ACQUISITION
    assert ComplianceProfile("itar_trade_compliance") == ComplianceProfile.ITAR_TRADE
    assert ComplianceProfile("university_research_security") == ComplianceProfile.UNIVERSITY_RESEARCH


def test_canonical_profile_payload_contains_scoring_fields():
    profile = get_profile("itar_trade_compliance")
    payload = profile_to_dict(profile)

    assert payload["id"] == "itar_trade_compliance"
    assert payload["enum_name"] == "ITAR_TRADE"
    assert "DEEMED_EXPORT" in payload["enabled_gates"]
    assert payload["baseline_shift"] == 0.15


def test_score_vendor_applies_profile_behavior_for_runtime_profile_id():
    defense_result = score_vendor(_clean_vendor("defense_acquisition"), regulatory_status="COMPLIANT")
    itar_result = score_vendor(_clean_vendor("itar_trade_compliance"), regulatory_status="COMPLIANT")

    assert itar_result.calibrated_probability > defense_result.calibrated_probability
