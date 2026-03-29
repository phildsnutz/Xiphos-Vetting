import os
import sys
from types import SimpleNamespace


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import screening_api
from compliance_profiles import get_profile


def test_screening_request_normalizes_profile_and_sensitivity_defaults():
    req = screening_api.ScreeningRequest(
        vendor_name="  Acme Systems  ",
        vendor_country="us",
        profile="ITAR_TRADE",
    )

    valid, error = req.validate()

    assert valid, error
    assert req.vendor_name == "Acme Systems"
    assert req.vendor_country == "US"
    assert req.profile == "itar_trade_compliance"
    assert req.sensitivity == get_profile("itar_trade_compliance").sensitivity_default

    vendor_input = screening_api._build_vendor_input(req)
    assert vendor_input is not None
    assert vendor_input.compliance_profile == "itar_trade_compliance"
    assert vendor_input.dod.sensitivity == get_profile("itar_trade_compliance").sensitivity_default


def test_single_screen_uses_profile_gate_set_and_layered_scoring(monkeypatch):
    pending_gate = SimpleNamespace(
        gate_id=11,
        gate_name="Deemed Export Risk",
        state=SimpleNamespace(value="PENDING"),
        severity="HIGH",
        details="Foreign national access needs review.",
        regulation="22 CFR 120.17",
        mitigation="Add TCP and nationality review.",
        confidence=0.82,
    )
    assessment = SimpleNamespace(
        status=SimpleNamespace(value="REQUIRES_REVIEW"),
        failed_gates=[],
        pending_gates=[pending_gate],
        to_dict=lambda: {
            "status": "REQUIRES_REVIEW",
            "passed_gates": [],
            "failed_gates": [],
            "pending_gates": [],
            "gate_proximity_score": 0.37,
            "is_dod_eligible": True,
            "is_dod_qualified": False,
        },
    )

    captured = {}

    def fake_evaluate_regulatory_gates(inp):
        captured["enabled_gates"] = list(inp.enabled_gates)
        captured["sensitivity"] = inp.sensitivity
        return assessment

    def fake_score_vendor(inp, regulatory_status="NOT_EVALUATED", regulatory_findings=None, **_kwargs):
        captured["compliance_profile"] = inp.compliance_profile
        captured["regulatory_gate_proximity"] = inp.dod.regulatory_gate_proximity
        captured["score_regulatory_status"] = regulatory_status
        captured["score_regulatory_findings"] = list(regulatory_findings or [])
        return SimpleNamespace(
            calibrated_probability=0.62,
            calibrated_tier="TIER_2_ELEVATED_REVIEW",
            contributions={"regulatory_gate_proximity": 0.37},
            program_recommendation="HOLD_FOR_REVIEW",
        )

    monkeypatch.setattr(screening_api, "HAS_OFAC", False)
    monkeypatch.setattr(screening_api, "HAS_DECISION_ENGINE", False)
    monkeypatch.setattr(screening_api, "HAS_WORKFLOW", False)
    monkeypatch.setattr(screening_api, "HAS_GATES", True)
    monkeypatch.setattr(screening_api, "HAS_FGAM", True)
    monkeypatch.setattr(screening_api, "evaluate_regulatory_gates", fake_evaluate_regulatory_gates)
    monkeypatch.setattr(screening_api, "score_vendor", fake_score_vendor)

    req = screening_api.ScreeningRequest(
        vendor_name="AVIC",
        vendor_country="cn",
        profile="itar_trade_compliance",
    )
    valid, error = req.validate()
    assert valid, error

    result = screening_api._screen_single_vendor(req, "req-screening-api-1")
    expected_profile = get_profile("itar_trade_compliance")

    assert captured["enabled_gates"] == expected_profile.enabled_gate_ids
    assert captured["sensitivity"] == expected_profile.sensitivity_default
    assert captured["compliance_profile"] == "itar_trade_compliance"
    assert captured["regulatory_gate_proximity"] == 0.37
    assert captured["score_regulatory_status"] == "REQUIRES_REVIEW"
    assert captured["score_regulatory_findings"][0]["gate"] == 11
    assert result.profile == "itar_trade_compliance"
    assert result.regulatory_gates["enabled_gates"] == expected_profile.enabled_gate_ids
    assert result.regulatory_gates["findings"][0]["name"] == "Deemed Export Risk"
    assert result.risk_score["program_recommendation"] == "HOLD_FOR_REVIEW"
    assert result.recommendation == "HOLD_FOR_REVIEW"
