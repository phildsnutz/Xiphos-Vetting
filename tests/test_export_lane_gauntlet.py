import os
import sys
from pathlib import Path


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from export_lane_gauntlet import (  # type: ignore  # noqa: E402
    DEFAULT_FIXTURE,
    evaluate_cases,
    load_cases,
    render_markdown,
)


def test_export_lane_gauntlet_fixture_passes_cleanly():
    cases = load_cases(DEFAULT_FIXTURE)
    report = evaluate_cases(cases)

    assert report["scenario_count"] == 12
    assert report["failed_count"] == 0
    assert report["pass_rate"] == 1.0
    assert report["posture_accuracy"] == 1.0
    assert report["overall_score"] >= 0.85


def test_export_lane_gauntlet_markdown_contains_proof_summary():
    cases = load_cases(DEFAULT_FIXTURE)
    report = evaluate_cases(cases)
    markdown = render_markdown(report, Path(DEFAULT_FIXTURE).name)

    assert "# Helios Export Lane Gauntlet" in markdown
    assert "Scenarios: `12`" in markdown
    assert "Passed: `12`" in markdown
    assert "The shipment / destination / end-use packet cleared without scenario failures." in markdown
