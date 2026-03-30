from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_graph_training_benchmark.py"
SPEC = importlib.util.spec_from_file_location("run_graph_training_benchmark", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def _pass_stage_metrics() -> dict[str, dict[str, float]]:
    return {
        "construction_training": {
            "edge_family_micro_f1": 0.94,
            "ownership_control_precision": 0.99,
            "ownership_control_recall": 0.92,
            "entity_resolution_pairwise_f1": 0.99,
            "false_merge_rate": 0.001,
            "descriptor_only_false_owner_rate": 0.0,
        },
        "missing_edge_recovery": {
            "ownership_control_hits_at_10": 0.82,
            "ownership_control_mrr": 0.5,
            "intermediary_route_hits_at_10": 0.71,
            "intermediary_route_mrr": 0.36,
            "cyber_dependency_hits_at_10": 0.74,
            "analyst_confirmation_rate": 0.7,
            "unsupported_promoted_edge_rate": 0.0,
        },
        "temporal_recurrence_change": {
            "change_detection_f1": 0.82,
            "recurrence_auc": 0.86,
            "lead_time_gain_vs_heuristic": 0.24,
        },
        "subgraph_anomaly": {
            "shell_layering_auprc": 0.87,
            "transshipment_auprc": 0.84,
            "cyber_fourth_party_auprc": 0.81,
            "false_positive_rate": 0.05,
        },
        "uncertainty_fusion": {
            "edge_confidence_ece": 0.03,
            "decision_confidence_ece": 0.03,
            "decision_brier_score": 0.1,
            "high_confidence_unsupported_claim_rate": 0.0,
        },
        "graphrag_explanation": {
            "provenance_coverage": 0.97,
            "unsupported_explanation_claims": 0,
            "required_path_mention_rate": 0.93,
        },
    }


def test_graph_training_benchmark_passes_with_complete_metrics(tmp_path):
    results_json = tmp_path / "results.json"
    results_json.write_text(json.dumps({"stage_metrics": _pass_stage_metrics()}), encoding="utf-8")

    args = module.argparse.Namespace(
        suite=str(module.DEFAULT_SUITE),
        results_json=str(results_json),
        embedding_stats_json="",
        base_url="",
        token="",
        email="",
        password="",
        report_dir=str(tmp_path / "reports"),
        output_json="",
        output_md="",
        print_json=False,
    )

    summary = module.evaluate(args)
    assert summary["data_foundation"]["verdict"] == "PASS"
    assert summary["overall_verdict"] == "PASS"


def test_graph_training_benchmark_fails_without_stage_metrics(tmp_path):
    args = module.argparse.Namespace(
        suite=str(module.DEFAULT_SUITE),
        results_json="",
        embedding_stats_json="",
        base_url="",
        token="",
        email="",
        password="",
        report_dir=str(tmp_path / "reports"),
        output_json="",
        output_md="",
        print_json=False,
    )

    summary = module.evaluate(args)
    assert summary["data_foundation"]["verdict"] == "PASS"
    assert summary["overall_verdict"] == "FAIL"
    assert any(stage["verdict"] == "FAIL" for stage in summary["stage_results"])
