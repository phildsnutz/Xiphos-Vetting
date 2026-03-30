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
            "masked_holdout_hits_at_10": 0.82,
            "masked_holdout_mrr": 0.5,
            "mean_withheld_target_rank": 4.2,
            "masked_holdout_queries_evaluated": 7,
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
        tranche_summary_json="",
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
        tranche_summary_json="",
        report_dir=str(tmp_path / "reports"),
        output_json="",
        output_md="",
        print_json=False,
    )

    summary = module.evaluate(args)
    assert summary["data_foundation"]["verdict"] == "PASS"
    assert summary["overall_verdict"] == "FAIL"
    assert any(stage["verdict"] == "FAIL" for stage in summary["stage_results"])


def test_graph_training_benchmark_uses_tranche_summary_for_defaults(tmp_path):
    tranche_dir = tmp_path / "live_graph_training_tranche" / "20260330150000" / "20260330150100"
    tranche_dir.mkdir(parents=True)
    tranche_path = tranche_dir / "summary.json"
    tranche_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-30T15:00:00Z",
                "embedding_stats": {
                    "entity_count": 10,
                    "relation_count": 4,
                    "model_version": "model-1",
                    "trained_at": "2026-03-30T14:59:00Z",
                },
                "review_stats": {
                    "total_links": 25,
                    "reviewed_links": 11,
                    "confirmed_links": 7,
                    "confirmation_rate": 7 / 11,
                    "review_coverage_pct": 11 / 25,
                    "by_edge_family": [],
                },
                "stage_metrics": _pass_stage_metrics(),
            }
        ),
        encoding="utf-8",
    )

    args = module.argparse.Namespace(
        suite=str(module.DEFAULT_SUITE),
        results_json="",
        embedding_stats_json="",
        base_url="",
        token="",
        email="",
        password="",
        tranche_summary_json=str(tranche_path),
        report_dir=str(tmp_path / "reports"),
        output_json="",
        output_md="",
        print_json=False,
    )

    summary = module.evaluate(args)
    assert summary["overall_verdict"] == "PASS"
    assert summary["data_foundation"]["reviewed_predicted_links"] == 11
    assert summary["data_foundation"]["confirmed_predicted_links"] == 7
    missing_edge_stage = next(stage for stage in summary["stage_results"] if stage["stage_id"] == "missing_edge_recovery")
    assert missing_edge_stage["actual_metrics"]["masked_holdout_hits_at_10"] == 0.82
    assert missing_edge_stage["actual_metrics"]["mean_withheld_target_rank"] == 4.2
