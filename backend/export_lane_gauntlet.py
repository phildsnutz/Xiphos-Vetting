from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from transaction_authorization import (
    TransactionAuthorization,
    TransactionInput,
    TransactionOrchestrator,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = (
    ROOT / "fixtures" / "adversarial_gym" / "export_lane_shipment_destination_end_use_cases.json"
)


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    fixture_path = Path(path)
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _build_orchestrator() -> TransactionOrchestrator:
    orchestrator = TransactionOrchestrator()
    # The gauntlet is a deterministic eval harness, not a persistence workflow.
    orchestrator._persist = lambda auth, txn: None  # type: ignore[attr-defined]
    return orchestrator


def _text_bag(auth: TransactionAuthorization) -> str:
    parts: list[str] = [
        auth.combined_posture,
        auth.combined_posture_label,
        auth.recommended_next_step,
    ]
    if auth.rules_guidance:
        parts.extend(
            [
                auth.rules_guidance.get("posture", ""),
                auth.rules_guidance.get("posture_label", ""),
                auth.rules_guidance.get("reason_summary", ""),
                auth.rules_guidance.get("recommended_next_step", ""),
            ]
        )
        parts.extend(auth.rules_guidance.get("factors", []))
        for flag in auth.rules_guidance.get("end_use_flags", []):
            parts.extend(
                [
                    flag.get("key", ""),
                    flag.get("label", ""),
                    flag.get("reference", ""),
                    flag.get("rationale", ""),
                ]
            )
    parts.extend(auth.escalation_reasons)
    parts.extend(auth.blocking_factors)
    parts.extend(auth.all_factors)
    if auth.license_exception:
        parts.extend(
            [
                auth.license_exception.get("exception_code", "") or "",
                auth.license_exception.get("exception_name", "") or "",
                auth.license_exception.get("recommendation", "") or "",
            ]
        )
        best_match = auth.license_exception.get("best_match") or {}
        if isinstance(best_match, dict):
            parts.extend(
                [
                    best_match.get("exception_code", "") or "",
                    best_match.get("ear_reference", "") or "",
                ]
            )
            parts.extend(best_match.get("conditions", []) or [])
    return " ".join(str(part) for part in parts if part).lower()


def _fraction_hit(expected: list[str], haystack: str) -> tuple[float, list[str], list[str]]:
    if not expected:
        return 1.0, [], []
    hits = [fragment for fragment in expected if fragment.lower() in haystack]
    misses = [fragment for fragment in expected if fragment.lower() not in haystack]
    return len(hits) / len(expected), hits, misses


def _check_license_expectation(
    expected_codes: list[str], auth: TransactionAuthorization
) -> tuple[float, str | None]:
    if not expected_codes:
        return 1.0, None
    actual = None
    if auth.license_exception and auth.license_exception.get("eligible"):
        actual = auth.license_exception.get("exception_code")
    if actual in expected_codes:
        return 1.0, actual
    return 0.0, actual


def evaluate_case(
    case: dict[str, Any], orchestrator: TransactionOrchestrator | None = None
) -> dict[str, Any]:
    expected = case["expected"]
    txn = TransactionInput(**case["transaction_input"])
    auth = (orchestrator or _build_orchestrator()).authorize(txn)
    text_bag = _text_bag(auth)

    expected_postures = expected.get("acceptable_postures") or [expected["posture"]]
    posture_ok = auth.combined_posture in expected_postures

    reason_ratio, reason_hits, reason_misses = _fraction_hit(
        expected.get("reason_fragments", []), text_bag
    )
    next_ratio, next_hits, next_misses = _fraction_hit(
        expected.get("next_step_fragments", []), text_bag
    )
    escalation_ratio, escalation_hits, escalation_misses = _fraction_hit(
        expected.get("escalation_fragments", []), text_bag
    )
    blocking_ratio, blocking_hits, blocking_misses = _fraction_hit(
        expected.get("blocking_fragments", []), text_bag
    )
    license_ratio, actual_exception = _check_license_expectation(
        expected.get("license_exception_any_of", []), auth
    )

    weighted_checks: list[tuple[float, float]] = [
        (0.45, 1.0 if posture_ok else 0.0),
        (0.20, reason_ratio),
        (0.15, next_ratio),
    ]
    if expected.get("escalation_fragments"):
        weighted_checks.append((0.10, escalation_ratio))
    if expected.get("blocking_fragments"):
        weighted_checks.append((0.05, blocking_ratio))
    if expected.get("license_exception_any_of"):
        weighted_checks.append((0.05, license_ratio))

    total_weight = sum(weight for weight, _ in weighted_checks) or 1.0
    score = sum(weight * value for weight, value in weighted_checks) / total_weight
    minimum_score = float(expected.get("minimum_score", 0.8))
    passed = posture_ok and score >= minimum_score

    return {
        "scenario_id": case["scenario_id"],
        "title": case["title"],
        "description": case.get("description", ""),
        "passed": passed,
        "score": round(score, 4),
        "minimum_score": minimum_score,
        "expected_postures": expected_postures,
        "actual_posture": auth.combined_posture,
        "rules_posture": auth.rules_posture,
        "posture_ok": posture_ok,
        "actual_confidence": auth.confidence,
        "expected_license_exception_any_of": expected.get("license_exception_any_of", []),
        "actual_license_exception": actual_exception,
        "reason_hits": reason_hits,
        "reason_misses": reason_misses,
        "next_step_hits": next_hits,
        "next_step_misses": next_misses,
        "escalation_hits": escalation_hits,
        "escalation_misses": escalation_misses,
        "blocking_hits": blocking_hits,
        "blocking_misses": blocking_misses,
        "recommended_next_step": auth.recommended_next_step,
        "rules_reason_summary": (auth.rules_guidance or {}).get("reason_summary", ""),
        "blocking_factors": auth.blocking_factors,
        "escalation_reasons": auth.escalation_reasons,
        "license_exception": auth.license_exception,
        "pipeline_log": auth.pipeline_log,
        "transaction_input": case["transaction_input"],
    }


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    orchestrator = _build_orchestrator()
    results = [evaluate_case(case, orchestrator=orchestrator) for case in cases]
    passed_count = sum(1 for result in results if result["passed"])
    posture_correct = sum(1 for result in results if result["posture_ok"])
    posture_distribution = Counter(result["actual_posture"] for result in results)
    failed = [result for result in results if not result["passed"]]
    return {
        "scenario_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "pass_rate": round(passed_count / len(results), 4) if results else 0.0,
        "posture_accuracy": round(posture_correct / len(results), 4) if results else 0.0,
        "overall_score": round(
            sum(result["score"] for result in results) / len(results), 4
        )
        if results
        else 0.0,
        "posture_distribution": dict(sorted(posture_distribution.items())),
        "results": results,
        "failed_scenarios": failed,
    }


def render_markdown(report: dict[str, Any], fixture_path: str | Path) -> str:
    fixture_name = Path(fixture_path).name
    lines = [
        "# Helios Export Lane Gauntlet",
        "",
        f"- Fixture: `{fixture_name}`",
        f"- Scenarios: `{report['scenario_count']}`",
        f"- Passed: `{report['passed_count']}`",
        f"- Failed: `{report['failed_count']}`",
        f"- Pass rate: `{report['pass_rate'] * 100:.1f}%`",
        f"- Posture accuracy: `{report['posture_accuracy'] * 100:.1f}%`",
        f"- Overall score: `{report['overall_score'] * 100:.1f}%`",
        "",
        "## Posture Distribution",
        "",
    ]
    for posture, count in report["posture_distribution"].items():
        lines.append(f"- `{posture}`: `{count}`")

    lines.extend(["", "## Scenario Results", ""])
    for result in report["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        lines.extend(
            [
                f"### {result['title']}",
                "",
                f"- Status: `{status}`",
                f"- Score: `{result['score'] * 100:.1f}%`",
                f"- Expected posture: `{', '.join(result['expected_postures'])}`",
                f"- Actual posture: `{result['actual_posture']}`",
                f"- Recommended next step: {result['recommended_next_step']}",
            ]
        )
        if result["actual_license_exception"] or result["expected_license_exception_any_of"]:
            lines.append(
                f"- License exception: expected `{', '.join(result['expected_license_exception_any_of']) or 'none'}`, actual `{result['actual_license_exception'] or 'none'}`"
            )
        if result["reason_misses"]:
            lines.append(f"- Reason gaps: `{'; '.join(result['reason_misses'])}`")
        if result["next_step_misses"]:
            lines.append(f"- Next-step gaps: `{'; '.join(result['next_step_misses'])}`")
        if result["escalation_misses"]:
            lines.append(f"- Escalation gaps: `{'; '.join(result['escalation_misses'])}`")
        if result["blocking_misses"]:
            lines.append(f"- Blocking gaps: `{'; '.join(result['blocking_misses'])}`")
        lines.append("")

    if report["failed_scenarios"]:
        lines.extend(["## Weak Spots", ""])
        for result in report["failed_scenarios"]:
            lines.append(
                f"- `{result['scenario_id']}` missed on posture `{result['actual_posture']}` or score `{result['score'] * 100:.1f}%`."
            )
    else:
        lines.extend(
            [
                "## Readout",
                "",
                "- The shipment / destination / end-use packet cleared without scenario failures.",
                "- The next useful expansion is more graph-elevated intermediary and end-user cases, not more easy allied shipments.",
            ]
        )

    return "\n".join(lines) + "\n"
