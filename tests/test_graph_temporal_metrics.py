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


def test_temporal_recurrence_metrics_pass_fixture_thresholds():
    graph_embeddings = _reload_fresh("graph_embeddings")

    metrics = graph_embeddings.get_temporal_recurrence_change_metrics("")

    assert metrics["temporal_cases_evaluated"] == 10
    assert metrics["change_detection_f1"] >= 0.8
    assert metrics["recurrence_auc"] >= 0.85
    assert metrics["lead_time_gain_vs_heuristic"] >= 0.2
    assert metrics["temporal_case_count_by_family"]["ownership_control"] == 4
    assert metrics["temporal_case_count_by_family"]["trade_and_logistics"] == 2
    assert metrics["temporal_case_count_by_family"]["contracts_and_programs"] == 2
    assert metrics["temporal_case_count_by_family"]["sanctions_and_legal"] == 2


def test_temporal_recurrence_metrics_include_replay_details():
    graph_embeddings = _reload_fresh("graph_embeddings")

    metrics = graph_embeddings.get_temporal_recurrence_change_metrics("")
    scenario = next(row for row in metrics["temporal_case_results"] if row["scenario_id"] == "contract_shift_signaled_before_award_change")

    assert scenario["change_prediction"] == 1
    assert scenario["model_alert_step"] == 1
    assert scenario["event_step"] == 2
    assert scenario["lead_time_gain"] >= 1.0
    assert any("contradiction" in trigger["triggers"] for trigger in scenario["trigger_rows"])
