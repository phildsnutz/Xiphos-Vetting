import os
import sys
from pathlib import Path


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from export_ai_gauntlet import (  # type: ignore  # noqa: E402
    DEFAULT_FIXTURE,
    evaluate_cases,
    load_cases,
    render_markdown,
)

SECOND_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "adversarial_gym" / "export_lane_ai_transshipment_diversion_cases.json"
THIRD_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "adversarial_gym" / "export_lane_ai_defense_services_foreign_person_cases.json"


def test_export_ai_gauntlet_fixture_passes_cleanly():
    cases = load_cases(DEFAULT_FIXTURE)
    report = evaluate_cases(cases)

    assert report["scenario_count"] == 8
    assert report["failed_count"] == 0
    assert report["pass_rate"] == 1.0
    assert report["deterministic_baseline_accuracy"] == 0.5
    assert report["hybrid_posture_accuracy"] == 1.0
    assert report["hybrid_outperformed_count"] == 4
    assert report["no_regression_count"] == 8
    assert report["overall_score"] >= 0.95


def test_export_ai_transshipment_fixture_passes_cleanly():
    cases = load_cases(SECOND_FIXTURE)
    report = evaluate_cases(cases)

    assert report["scenario_count"] == 6
    assert report["failed_count"] == 0
    assert report["pass_rate"] == 1.0
    assert report["hybrid_posture_accuracy"] == 1.0
    assert report["hybrid_outperformed_count"] == 2
    assert report["no_regression_count"] == 6
    assert report["overall_score"] >= 0.95


def test_export_ai_defense_services_fixture_passes_cleanly():
    cases = load_cases(THIRD_FIXTURE)
    report = evaluate_cases(cases)

    assert report["scenario_count"] == 7
    assert report["failed_count"] == 0
    assert report["pass_rate"] == 1.0
    assert report["deterministic_baseline_accuracy"] == 0.5714
    assert report["hybrid_posture_accuracy"] == 1.0
    assert report["hybrid_outperformed_count"] == 3
    assert report["no_regression_count"] == 7
    assert report["overall_score"] >= 0.95


def test_export_ai_gauntlet_markdown_contains_side_by_side_proof():
    cases = load_cases(DEFAULT_FIXTURE)
    report = evaluate_cases(cases)
    markdown = render_markdown(report, Path(DEFAULT_FIXTURE).name)

    assert "# Helios AI-In-The-Loop Export Gauntlet" in markdown
    assert "Scenarios: `8`" in markdown
    assert "Deterministic baseline accuracy: `50.0%`" in markdown
    assert "Hybrid posture accuracy: `100.0%`" in markdown
    assert "Hybrid outperformed deterministic on: `4` scenarios" in markdown
    assert "The AI challenge layer is improving posture quality on ambiguous narratives" in markdown
