#!/usr/bin/env python3

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import fgamlogit
import ofac
from fgamlogit import (
    DataQuality,
    DoDContext,
    ExecProfile,
    OwnershipProfile,
    STANDALONE_TIER_THRESHOLDS,
    SANCTIONS_HARD_STOP_THRESHOLD_DEFAULT,
    VendorInputV5,
    score_vendor,
)
from ofac import ScreeningResult


def test_screen_name_returns_policy_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ofac, "get_active_db", lambda: ([], "test-db"))

    result = ofac.screen_name("Clean Vendor LLC")

    assert result.policy_basis["composite_threshold"] == ofac.SCREENING_COMPOSITE_THRESHOLD_DEFAULT
    assert result.policy_basis["prefilter"]["jaro_winkler_floor"] == ofac.SCREENING_PREFILTER_JW_FLOOR
    assert (
        result.policy_basis["post_match_gates"]["distinctive_token_min"]
        == ofac.SCREENING_DISTINCTIVE_TOKEN_MIN
    )


def test_score_vendor_exposes_policy_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    screening = ScreeningResult(
        matched=False,
        best_score=0.0,
        best_raw_jw=0.0,
        matched_entry=None,
        matched_name="",
        match_details={},
        all_matches=[],
        db_label="test-db",
        screening_ms=1,
        policy_basis={"composite_threshold": 0.75},
    )
    disposition = SimpleNamespace(
        override_risk_weight=0.0,
        category="clear",
        confidence_band="low",
        recommended_action="AUTO_CLEAR",
        explanation="No sanctions concerns detected.",
        classification_factors=[],
    )

    monkeypatch.setattr(fgamlogit, "screen_name", lambda *args, **kwargs: screening)
    monkeypatch.setattr(fgamlogit, "classify_alert", lambda *args, **kwargs: disposition)

    inp = VendorInputV5(
        name="Acme Defense",
        country="US",
        ownership=OwnershipProfile(),
        data_quality=DataQuality(has_cage=True, has_duns=True),
        exec_profile=ExecProfile(),
        dod=DoDContext(sensitivity="COMMERCIAL", supply_chain_tier=1),
    )

    result = score_vendor(inp, regulatory_status="NOT_EVALUATED", source_reliability_avg=0.80)
    payload = result.to_dict()

    assert payload["screening"]["policy_basis"]["composite_threshold"] == 0.75
    assert payload["policy"]["mode"] == "standalone"
    assert payload["policy"]["sanctions_policy"]["hard_stop_threshold_default"] == SANCTIONS_HARD_STOP_THRESHOLD_DEFAULT
    assert payload["policy"]["standalone_thresholds"] == STANDALONE_TIER_THRESHOLDS
    assert payload["policy"]["uncertainty"]["effective_n_final"] >= payload["policy"]["uncertainty"]["effective_n_base"]
