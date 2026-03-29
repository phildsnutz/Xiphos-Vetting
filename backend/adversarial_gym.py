"""Replayable adversarial scenario gym for Helios trust surfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from decision_tribunal import build_decision_tribunal_from_signals


DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "adversarial_gym"
    / "critical_subsystem_scenarios.json"
)


def load_scenarios(path: str | None = None) -> list[dict[str, Any]]:
    fixture_path = Path(path).expanduser().resolve() if path else DEFAULT_FIXTURE
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [item for item in data if isinstance(item, dict)]


def evaluate_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    tribunal = build_decision_tribunal_from_signals(scenario.get("signal_packet") or {})
    expected = scenario.get("expected") or {}
    recommended = tribunal["recommended_view"]
    target_view = next(
        (view for view in tribunal["views"] if view["stance"] == expected.get("recommended_view")),
        None,
    )
    required_signal_keys = [str(item) for item in (expected.get("required_signal_keys") or [])]
    matched_signal_keys = set(target_view.get("signal_keys") or []) if isinstance(target_view, dict) else set()
    signal_gaps = [item for item in required_signal_keys if item not in matched_signal_keys]
    min_score = float(expected.get("minimum_score") or 0.0)
    score_ok = bool(target_view) and float(target_view.get("score") or 0.0) >= min_score
    view_ok = recommended == expected.get("recommended_view")
    passed = view_ok and score_ok and not signal_gaps
    return {
        "scenario_id": scenario.get("scenario_id"),
        "title": scenario.get("title"),
        "description": scenario.get("description"),
        "recommended_view": recommended,
        "expected_view": expected.get("recommended_view"),
        "consensus_level": tribunal.get("consensus_level"),
        "decision_gap": tribunal.get("decision_gap"),
        "required_signal_keys": required_signal_keys,
        "signal_gaps": signal_gaps,
        "minimum_score": min_score,
        "target_score": float(target_view.get("score") or 0.0) if isinstance(target_view, dict) else 0.0,
        "passed": passed,
        "tribunal": tribunal,
    }


def evaluate_scenarios(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [evaluate_scenario(scenario) for scenario in scenarios]
    passed = sum(1 for row in rows if row["passed"])
    return {
        "scenario_count": len(rows),
        "passed_count": passed,
        "failed_count": len(rows) - passed,
        "pass_rate": round((passed / len(rows)) if rows else 0.0, 3),
        "rows": rows,
    }


def render_markdown(report: dict[str, Any], fixture_path: str) -> str:
    lines = [
        "# Helios Adversarial Gym Report",
        "",
        f"Fixture: `{fixture_path}`",
        "",
        "## Summary",
        "",
        f"- Scenarios: `{report['scenario_count']}`",
        f"- Passed: `{report['passed_count']}`",
        f"- Failed: `{report['failed_count']}`",
        f"- Pass rate: `{report['pass_rate']}`",
        "",
        "## Results",
        "",
    ]

    for row in report["rows"]:
        lines.append(f"### {row['title']}")
        lines.append("")
        lines.append(f"- Expected view: `{row['expected_view']}`")
        lines.append(f"- Recommended view: `{row['recommended_view']}`")
        lines.append(f"- Consensus: `{row['consensus_level']}`")
        lines.append(f"- Decision gap: `{row['decision_gap']}`")
        lines.append(f"- Target score: `{row['target_score']}`")
        lines.append(f"- Status: `{'pass' if row['passed'] else 'fail'}`")
        if row["signal_gaps"]:
            lines.append(f"- Missing signal keys: `{', '.join(row['signal_gaps'])}`")
        lines.append("")
        for view in row["tribunal"]["views"]:
            lines.append(
                f"- `{view['label']}`: `{view['score']}`"
                f" via {', '.join(view['signal_keys']) or 'baseline'}"
            )
        lines.append("")

    return "\n".join(lines)
