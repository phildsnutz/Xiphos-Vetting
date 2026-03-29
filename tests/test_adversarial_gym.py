import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from adversarial_gym import DEFAULT_FIXTURE, evaluate_scenarios, load_scenarios  # type: ignore  # noqa: E402


def test_adversarial_gym_fixture_passes_expected_views():
    scenarios = load_scenarios(str(DEFAULT_FIXTURE))
    report = evaluate_scenarios(scenarios)

    assert report["scenario_count"] >= 5
    assert report["failed_count"] == 0
    assert report["pass_rate"] == 1.0
