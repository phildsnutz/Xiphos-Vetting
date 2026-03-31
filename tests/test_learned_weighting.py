import json
import os
import sys
from pathlib import Path


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from decision_tribunal import build_decision_tribunal_from_signals  # type: ignore  # noqa: E402
from learned_weighting import (  # type: ignore  # noqa: E402
    TRIBUNAL_CALIBRATION_PATH,
    TRIBUNAL_TRAINING_PATH,
    get_edge_truth_model,
    get_tribunal_model,
    predict_edge_truth_probability,
    predict_tribunal_probabilities,
)


def _load_tribunal_cases() -> list[dict]:
    payload = json.loads(Path(TRIBUNAL_TRAINING_PATH).read_text(encoding="utf-8"))
    return payload["cases"]


def _load_tribunal_calibration_cases() -> list[dict]:
    payload = json.loads(Path(TRIBUNAL_CALIBRATION_PATH).read_text(encoding="utf-8"))
    return payload["cases"]


def test_edge_truth_model_prefers_scoped_official_relationships():
    model = get_edge_truth_model()
    assert model is not None
    assert model.training_count >= 10

    strong_row = {
        "primary_edge_family": "ownership_control",
        "authority_bucket": "official_or_modeled",
        "temporal_state": "active",
        "descriptor_only": False,
        "legacy_unscoped": False,
        "corroboration_count": 3,
        "claim_records": [
            {
                "evidence_records": [
                    {
                        "authority_level": "official_registry",
                        "url": "https://registry.example.test/owner",
                    }
                ]
            }
        ],
    }
    weak_row = {
        "primary_edge_family": "ownership_control",
        "authority_bucket": "third_party_public_only",
        "temporal_state": "unknown",
        "descriptor_only": True,
        "legacy_unscoped": True,
        "corroboration_count": 1,
        "claim_records": [],
    }

    strong = predict_edge_truth_probability(strong_row)
    weak = predict_edge_truth_probability(weak_row)

    assert strong["probability"] > weak["probability"]
    assert strong["hierarchical_prior"] > weak["hierarchical_prior"]
    assert weak["probability"] < 0.5


def test_tribunal_model_prefers_target_stance_for_anchor_cases():
    model = get_tribunal_model()
    assert model is not None
    assert model.training_count == 11
    assert model.calibration_count == len(_load_tribunal_calibration_cases())
    assert model.temperature > 0.0

    cases = {row["case_id"]: row for row in _load_tribunal_cases()}
    sample_ids = (
        "deny_hidden_control_pressure",
        "approve_domestic_clear",
        "watch_graph_thin_cyber",
    )
    for case_id in sample_ids:
        case = cases[case_id]
        probabilities = predict_tribunal_probabilities(case["signal_packet"], case.get("heuristic_scores"))
        assert probabilities is not None
        predicted = max(probabilities.items(), key=lambda item: item[1])[0]
        assert predicted == case["target_view"]


def test_decision_tribunal_exposes_learned_score_metadata():
    tribunal = build_decision_tribunal_from_signals(
        {
            "posture": "approved",
            "latest_decision": "approve",
            "workflow_lane": "defense_counterparty_trust",
            "connector_coverage": 5,
            "identifier_count": 3,
            "control_path_count": 2,
            "ownership_path_count": 1,
            "intermediary_path_count": 0,
            "contradicted_path_count": 0,
            "stale_path_count": 0,
            "corroborated_path_count": 2,
            "official_coverage_thin": False,
            "graph_thin": False,
            "graph_missing_required_edge_family_count": 0,
            "graph_claim_coverage_pct": 0.9,
            "graph_official_edge_count": 3,
            "graph_public_only_edge_count": 0,
            "named_owner_known": True,
            "controlling_parent_known": True,
            "ownership_evidence_thin": False,
            "control_evidence_thin": False,
            "foreign_control_risk": False,
            "mitigated_foreign_interest": False,
            "cyber_gap": False,
            "export_prohibited": False,
            "export_review_required": False,
            "network_score": 0.1,
            "network_level": "low",
        }
    )

    assert tribunal["version"] == "decision-tribunal-v5"
    assert tribunal["score_training_count"] == 11
    assert tribunal["score_calibration_count"] == len(_load_tribunal_calibration_cases())
    assert tribunal["score_temperature"] > 0.0
    assert tribunal["recommended_view"] == "approve"
    assert tribunal["decision_posture"] == "confident"
    assert tribunal["requires_human_escalation"] is False
    assert tribunal["calibration_band"]["top_probability"] >= tribunal["calibration_band"]["confidence_floor"]
    assert tribunal["calibration_band"]["entropy"] <= tribunal["calibration_band"]["entropy_ceiling"]
    assert tribunal["calibration_band"]["temperature"] == tribunal["score_temperature"]
    assert all(view["score_source"] == "learned_softmax_v1" for view in tribunal["views"])
    assert all("heuristic_score" in view for view in tribunal["views"])


def test_decision_tribunal_marks_low_margin_cases_for_human_escalation():
    tribunal = build_decision_tribunal_from_signals(
        {
            "posture": "approved",
            "latest_decision": "",
            "workflow_lane": "supplier_cyber_trust",
            "connector_coverage": 4,
            "identifier_count": 2,
            "control_path_count": 0,
            "ownership_path_count": 0,
            "intermediary_path_count": 0,
            "contradicted_path_count": 0,
            "stale_path_count": 0,
            "corroborated_path_count": 0,
            "network_score": 0.1,
            "network_level": "low",
            "official_coverage_thin": False,
            "ownership_resolution_pct": 0.4,
            "control_resolution_pct": 0.0,
            "named_owner_known": False,
            "descriptor_only": False,
            "ownership_evidence_thin": True,
            "control_evidence_thin": True,
            "shell_layers": 1,
            "pep_connection": False,
            "graph_thin": True,
            "graph_missing_required_edge_family_count": 1,
            "graph_claim_coverage_pct": 0.0,
            "graph_evidence_coverage_pct": 0.0,
        }
    )

    assert tribunal["recommended_view"] == "watch"
    assert tribunal["requires_human_escalation"] is True
    assert tribunal["decision_posture"] in {"abstain", "escalate"}
