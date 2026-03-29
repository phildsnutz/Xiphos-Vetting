import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from decision_tribunal import build_decision_tribunal_from_signals  # type: ignore  # noqa: E402


def test_decision_tribunal_prefers_deny_for_hidden_control_pressure():
    tribunal = build_decision_tribunal_from_signals(
        {
            "posture": "review",
            "latest_decision": "escalate",
            "connector_coverage": 6,
            "identifier_count": 3,
            "control_path_count": 5,
            "ownership_path_count": 2,
            "intermediary_path_count": 2,
            "contradicted_path_count": 0,
            "stale_path_count": 0,
            "network_score": 2.8,
            "network_level": "high",
            "foreign_control_risk": True,
            "export_review_required": True,
            "cyber_gap": True,
            "critical_cves": 2,
            "kev_count": 1,
        }
    )

    assert tribunal["recommended_view"] == "deny"
    assert tribunal["consensus_level"] in {"strong", "moderate", "contested"}
    assert tribunal["views"][0]["stance"] == "deny"
    assert "foreign_control_risk" in tribunal["views"][0]["signal_keys"]


def test_decision_tribunal_prefers_approve_for_clean_allied_supplier():
    tribunal = build_decision_tribunal_from_signals(
        {
            "posture": "approved",
            "latest_decision": "approve",
            "connector_coverage": 6,
            "identifier_count": 4,
            "control_path_count": 2,
            "ownership_path_count": 1,
            "intermediary_path_count": 0,
            "contradicted_path_count": 0,
            "stale_path_count": 0,
            "network_score": 0.0,
            "network_level": "none",
            "mitigated_foreign_interest": True,
            "export_review_required": False,
            "export_prohibited": False,
            "cyber_gap": False,
        }
    )

    assert tribunal["recommended_view"] == "approve"
    approve_view = next(view for view in tribunal["views"] if view["stance"] == "approve")
    assert approve_view["score"] >= 0.6
    assert "approved_posture" in approve_view["signal_keys"]
