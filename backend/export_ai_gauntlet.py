from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from export_ai_challenge import (
    _to_transaction_input,
    analyze_ambiguous_end_use,
    build_hybrid_posture,
)
from transaction_authorization import TransactionOrchestrator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = (
    ROOT / "fixtures" / "adversarial_gym" / "export_lane_ai_ambiguous_end_use_cases.json"
)


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _build_orchestrator() -> TransactionOrchestrator:
    orchestrator = TransactionOrchestrator()
    orchestrator._persist = lambda auth, txn: None  # type: ignore[attr-defined]
    return orchestrator


def _fraction_hit(expected: list[str], actual: list[str]) -> tuple[float, list[str], list[str]]:
    if not expected:
        return 1.0, [], []
    actual_set = set(actual)
    hits = [item for item in expected if item in actual_set]
    misses = [item for item in expected if item not in actual_set]
    return len(hits) / len(expected), hits, misses


def _fragment_fraction(expected: list[str], text: str) -> tuple[float, list[str], list[str]]:
    haystack = text.lower()
    if not expected:
        return 1.0, [], []
    hits = [fragment for fragment in expected if fragment.lower() in haystack]
    misses = [fragment for fragment in expected if fragment.lower() not in haystack]
    return len(hits) / len(expected), hits, misses


def evaluate_case(
    case: dict[str, Any], orchestrator: TransactionOrchestrator | None = None
) -> dict[str, Any]:
    expected = case["expected"]
    txn = _to_transaction_input(case["transaction_input"])
    auth = (orchestrator or _build_orchestrator()).authorize(txn)
    ai_assessment = analyze_ambiguous_end_use(txn, auth)
    hybrid_posture = build_hybrid_posture(auth, ai_assessment)

    disagreement_expected = bool(expected.get("expect_ai_disagreement"))
    disagreement_ok = ai_assessment["disagrees_with_deterministic"] == disagreement_expected

    deterministic_expected = str(expected.get("deterministic_posture") or auth.combined_posture)
    deterministic_ok = auth.combined_posture == deterministic_expected
    ambiguity_ratio, ambiguity_hits, ambiguity_misses = _fraction_hit(
        expected.get("ambiguity_flags", []), ai_assessment["ambiguity_flags"]
    )
    unexpected_ambiguity_flags = [
        flag for flag in ai_assessment["ambiguity_flags"] if flag not in expected.get("ambiguity_flags", [])
    ]
    missing_ratio, missing_hits, missing_misses = _fraction_hit(
        expected.get("missing_facts", []), ai_assessment["missing_facts"]
    )
    explanation_ratio, explanation_hits, explanation_misses = _fragment_fraction(
        expected.get("explanation_fragments", []), ai_assessment["explanation"]
    )
    hybrid_ok = hybrid_posture == expected["hybrid_posture"]

    safe_behavior = str(expected.get("safe_behavior") or "hold")
    if safe_behavior == "elevate":
        safe_behavior_ok = (
            ai_assessment["proposed_posture"] == "escalate" and hybrid_posture == "escalate"
        )
    elif safe_behavior == "no_downgrade":
        safe_behavior_ok = hybrid_posture == auth.combined_posture
    else:
        safe_behavior_ok = hybrid_posture == expected["hybrid_posture"]

    weighted_checks = [
        (0.25, 1.0 if hybrid_ok else 0.0),
        (0.15, 1.0 if disagreement_ok else 0.0),
        (0.20, ambiguity_ratio),
        (0.20, missing_ratio),
        (0.10, explanation_ratio),
        (0.10, 1.0 if safe_behavior_ok else 0.0),
    ]
    score = sum(weight * value for weight, value in weighted_checks)
    minimum_score = float(expected.get("minimum_score", 0.8))
    passed = hybrid_ok and score >= minimum_score and safe_behavior_ok

    return {
        "scenario_id": case["scenario_id"],
        "title": case["title"],
        "description": case.get("description", ""),
        "passed": passed,
        "score": round(score, 4),
        "minimum_score": minimum_score,
        "deterministic_posture": auth.combined_posture,
        "expected_deterministic_posture": deterministic_expected,
        "deterministic_ok": deterministic_ok,
        "ai_proposed_posture": ai_assessment["proposed_posture"],
        "hybrid_posture": hybrid_posture,
        "expected_hybrid_posture": expected["hybrid_posture"],
        "expected_ai_disagreement": disagreement_expected,
        "actual_ai_disagreement": ai_assessment["disagrees_with_deterministic"],
        "disagreement_ok": disagreement_ok,
        "ambiguity_hits": ambiguity_hits,
        "ambiguity_misses": ambiguity_misses,
        "unexpected_ambiguity_flags": unexpected_ambiguity_flags,
        "missing_fact_hits": missing_hits,
        "missing_fact_misses": missing_misses,
        "explanation_hits": explanation_hits,
        "explanation_misses": explanation_misses,
        "safe_behavior": safe_behavior,
        "safe_behavior_ok": safe_behavior_ok,
        "recommended_next_step": auth.recommended_next_step,
        "ai_assessment": ai_assessment,
        "transaction_input": case["transaction_input"],
    }


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    orchestrator = _build_orchestrator()
    results = [evaluate_case(case, orchestrator=orchestrator) for case in cases]
    passed_count = sum(1 for result in results if result["passed"])
    disagreement_correct = sum(1 for result in results if result["disagreement_ok"])
    deterministic_baseline_correct = sum(
        1
        for result in results
        if result["deterministic_posture"] == result["expected_hybrid_posture"]
    )
    hybrid_correct = sum(
        1 for result in results if result["hybrid_posture"] == result["expected_hybrid_posture"]
    )
    hybrid_outperformed = sum(
        1
        for result in results
        if result["deterministic_posture"] != result["expected_hybrid_posture"]
        and result["hybrid_posture"] == result["expected_hybrid_posture"]
    )
    no_regression_count = sum(
        1
        for result in results
        if result["deterministic_ok"] == (result["hybrid_posture"] == result["expected_hybrid_posture"])
        or result["hybrid_posture"] == result["expected_hybrid_posture"]
    )
    posture_distribution = Counter(result["hybrid_posture"] for result in results)
    return {
        "scenario_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "pass_rate": round(passed_count / len(results), 4) if results else 0.0,
        "deterministic_baseline_accuracy": round(deterministic_baseline_correct / len(results), 4)
        if results
        else 0.0,
        "hybrid_posture_accuracy": round(hybrid_correct / len(results), 4) if results else 0.0,
        "disagreement_accuracy": round(disagreement_correct / len(results), 4) if results else 0.0,
        "hybrid_outperformed_count": hybrid_outperformed,
        "no_regression_count": no_regression_count,
        "overall_score": round(
            sum(result["score"] for result in results) / len(results), 4
        )
        if results
        else 0.0,
        "posture_distribution": dict(sorted(posture_distribution.items())),
        "results": results,
        "failed_scenarios": [result for result in results if not result["passed"]],
    }


def render_markdown(report: dict[str, Any], fixture_path: str | Path) -> str:
    fixture_name = Path(fixture_path).name
    lines = [
        "# Helios AI-In-The-Loop Export Gauntlet",
        "",
        f"- Fixture: `{fixture_name}`",
        f"- Scenarios: `{report['scenario_count']}`",
        f"- Passed: `{report['passed_count']}`",
        f"- Failed: `{report['failed_count']}`",
        f"- Pass rate: `{report['pass_rate'] * 100:.1f}%`",
        f"- Deterministic baseline accuracy: `{report['deterministic_baseline_accuracy'] * 100:.1f}%`",
        f"- Hybrid posture accuracy: `{report['hybrid_posture_accuracy'] * 100:.1f}%`",
        f"- Disagreement accuracy: `{report['disagreement_accuracy'] * 100:.1f}%`",
        f"- Overall score: `{report['overall_score'] * 100:.1f}%`",
        f"- Hybrid outperformed deterministic on: `{report['hybrid_outperformed_count']}` scenarios",
        f"- Hybrid avoided regressions on: `{report['no_regression_count']}` scenarios",
        "",
        "## Hybrid Posture Distribution",
        "",
    ]
    for posture, count in report["posture_distribution"].items():
        lines.append(f"- `{posture}`: `{count}`")

    lines.extend(["", "## Scenario Results", ""])
    for result in report["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        ai_assessment = result["ai_assessment"]
        lines.extend(
            [
                f"### {result['title']}",
                "",
                f"- Status: `{status}`",
                f"- Score: `{result['score'] * 100:.1f}%`",
                f"- Deterministic posture: `{result['deterministic_posture']}`",
                f"- Expected deterministic posture: `{result['expected_deterministic_posture']}`",
                f"- AI proposed posture: `{result['ai_proposed_posture']}`",
                f"- Hybrid posture: `{result['hybrid_posture']}`",
                f"- Expected hybrid posture: `{result['expected_hybrid_posture']}`",
                f"- AI disagreement expected / actual: `{result['expected_ai_disagreement']}` / `{result['actual_ai_disagreement']}`",
                f"- Ambiguity flags: `{', '.join(ai_assessment['ambiguity_flags']) or 'none'}`",
                f"- Missing facts: `{', '.join(ai_assessment['missing_facts']) or 'none'}`",
                f"- AI explanation: {ai_assessment['explanation']}",
            ]
        )
        if result["ambiguity_misses"]:
            lines.append(f"- Ambiguity gaps: `{'; '.join(result['ambiguity_misses'])}`")
        if result["unexpected_ambiguity_flags"]:
            lines.append(
                f"- Ambiguity noise: `{'; '.join(result['unexpected_ambiguity_flags'])}`"
            )
        if result["missing_fact_misses"]:
            lines.append(f"- Missing-fact gaps: `{'; '.join(result['missing_fact_misses'])}`")
        if result["explanation_misses"]:
            lines.append(f"- Explanation gaps: `{'; '.join(result['explanation_misses'])}`")
        lines.append("")

    if report["failed_scenarios"]:
        lines.extend(["## Weak Spots", ""])
        for result in report["failed_scenarios"]:
            lines.append(
                f"- `{result['scenario_id']}` missed the target hybrid posture or produced weak ambiguity handling."
            )
    else:
        lines.extend(
            [
                "## Readout",
                "",
                "- The AI challenge layer is improving posture quality on ambiguous narratives without downgrading hard deterministic postures.",
                "- Helios is strongest when the deterministic floor owns hard stops and the AI layer owns ambiguity, missing facts, and disciplined escalation.",
            ]
        )

    return "\n".join(lines) + "\n"
