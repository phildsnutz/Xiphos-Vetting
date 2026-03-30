from __future__ import annotations

import importlib
import os
import sys


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload_fresh(module_name: str):
    if module_name in sys.modules:
        del sys.modules[module_name]
    return importlib.import_module(module_name)


def test_uncertainty_fusion_metrics_pass_fixture_thresholds():
    graph_embeddings = _reload_fresh("graph_embeddings")

    metrics = graph_embeddings.get_uncertainty_fusion_metrics("", review_stats={"unsupported_promoted_edge_rate": 0.0})

    assert metrics["edge_cases_evaluated"] == 10
    assert metrics["decision_cases_evaluated"] == 8
    assert metrics["edge_confidence_ece"] <= 0.05
    assert metrics["decision_confidence_ece"] <= 0.05
    assert metrics["decision_brier_score"] <= 0.12
    assert metrics["high_confidence_unsupported_claim_rate"] == 0.0


def test_subgraph_anomaly_metrics_pass_fixture_thresholds():
    graph_embeddings = _reload_fresh("graph_embeddings")

    metrics = graph_embeddings.get_subgraph_anomaly_metrics()

    assert metrics["anomaly_cases_evaluated"] == 18
    assert metrics["shell_layering_auprc"] >= 0.85
    assert metrics["transshipment_auprc"] >= 0.82
    assert metrics["cyber_fourth_party_auprc"] >= 0.8
    assert metrics["false_positive_rate"] <= 0.08


def test_graphrag_explanation_metrics_pass_fixture_thresholds():
    graph_embeddings = _reload_fresh("graph_embeddings")

    metrics = graph_embeddings.get_graphrag_explanation_metrics()

    assert metrics["explanation_cases_evaluated"] == 3
    assert metrics["provenance_coverage"] >= 0.95
    assert metrics["unsupported_explanation_claims"] == 0
    assert metrics["required_path_mention_rate"] >= 0.9
