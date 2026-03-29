#!/usr/bin/env python3
"""
Evaluate whether Helios meets the current prime-time exit criteria.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_READINESS_DIR = ROOT / "docs" / "reports" / "helios_readiness"
DEFAULT_GATE_DIR = ROOT / "docs" / "reports" / "customer_demo_gate"
DEFAULT_ACCEPTANCE_SET = ROOT / "fixtures" / "customer_demo" / "counterparty_acceptance_set.json"
DEFAULT_STABLE_CANARY_PACK = ROOT / "fixtures" / "customer_demo" / "counterparty_canary_pack.json"
DEFAULT_CRITERIA = ROOT / "fixtures" / "customer_demo" / "prime_time_exit_criteria.json"

DEFAULT_FLAGSHIP_COMPANIES = {
    "Yorktown Systems Group": "yorktown-systems-group",
    "Berry Aviation, Inc.": "berry-aviation-inc",
    "Columbia Helicopters, Inc.": "columbia-helicopters-inc",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Helios against prime-time exit criteria.")
    parser.add_argument("--criteria", default=str(DEFAULT_CRITERIA))
    parser.add_argument("--readiness-summary", default="")
    parser.add_argument("--readiness-dir", default=str(DEFAULT_READINESS_DIR))
    parser.add_argument("--acceptance-set", default=str(DEFAULT_ACCEPTANCE_SET))
    parser.add_argument("--stable-canary-pack", default=str(DEFAULT_STABLE_CANARY_PACK))
    parser.add_argument("--customer-demo-gate-dir", default=str(DEFAULT_GATE_DIR))
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _latest_summary_json(base_dir: Path, *, prefix: str | None = None) -> Path | None:
    pattern = "summary.json" if prefix is None else f"{prefix}-*/summary.json"
    candidates = sorted(base_dir.glob(pattern))
    return candidates[-1] if candidates else None


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"expected JSON object in {path}")
    return payload


def _criterion(name: str, passed: bool, detail: str, *, actual: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "detail": detail,
        "actual": actual,
        "expected": expected,
    }


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    criteria = _read_json(Path(args.criteria))
    readiness_path = Path(args.readiness_summary) if args.readiness_summary else _latest_summary_json(Path(args.readiness_dir))
    if readiness_path is None:
        raise SystemExit("no readiness summary found")
    readiness = _read_json(readiness_path)

    acceptance_set = json.loads(Path(args.acceptance_set).read_text(encoding="utf-8"))
    stable_pack = json.loads(Path(args.stable_canary_pack).read_text(encoding="utf-8"))
    if not isinstance(acceptance_set, list) or not isinstance(stable_pack, list):
        raise SystemExit("acceptance set and stable canary pack must be JSON lists")

    steps = readiness.get("steps") if isinstance(readiness.get("steps"), list) else []
    pillar_verdicts = {str(step.get("pillar")): str(step.get("verdict")) for step in steps if isinstance(step, dict)}
    counterparty_step = next(
        (step for step in steps if isinstance(step, dict) and str(step.get("pillar")) == "counterparty"),
        None,
    )

    checks: list[dict[str, Any]] = []
    overall_expected = str(criteria.get("overall_readiness_verdict") or "GO")
    overall_actual = str(readiness.get("verdict") or readiness.get("overall_verdict") or "UNKNOWN")
    checks.append(
        _criterion(
            "overall_readiness",
            overall_actual == overall_expected,
            f"overall readiness is {overall_actual}",
            actual=overall_actual,
            expected=overall_expected,
        )
    )

    required_pillars = criteria.get("required_pillars") if isinstance(criteria.get("required_pillars"), dict) else {}
    for pillar, expected in required_pillars.items():
        actual = pillar_verdicts.get(str(pillar), "UNKNOWN")
        checks.append(
            _criterion(
                f"pillar:{pillar}",
                actual == str(expected),
                f"{pillar} verdict is {actual}",
                actual=actual,
                expected=str(expected),
            )
        )

    min_stable = int(criteria.get("min_stable_canary_companies") or 0)
    checks.append(
        _criterion(
            "stable_canary_size",
            len(stable_pack) >= min_stable,
            f"stable counterparty canary pack has {len(stable_pack)} companies",
            actual=len(stable_pack),
            expected=min_stable,
        )
    )

    min_acceptance = int(criteria.get("min_acceptance_registry_companies") or 0)
    checks.append(
        _criterion(
            "acceptance_registry_size",
            len(acceptance_set) >= min_acceptance,
            f"acceptance registry has {len(acceptance_set)} companies",
            actual=len(acceptance_set),
            expected=min_acceptance,
        )
    )

    max_counterparty_seconds = float(criteria.get("max_counterparty_readiness_seconds") or 0.0)
    counterparty_elapsed = (
        float(counterparty_step.get("elapsed_seconds") or 0.0)
        if isinstance(counterparty_step, dict)
        else 0.0
    )
    checks.append(
        _criterion(
            "counterparty_runtime",
            counterparty_elapsed <= max_counterparty_seconds,
            f"counterparty readiness completed in {counterparty_elapsed:.1f}s",
            actual=round(counterparty_elapsed, 3),
            expected=max_counterparty_seconds,
        )
    )

    gate_dir = Path(args.customer_demo_gate_dir)
    required_flagships = criteria.get("required_flagship_companies")
    if not isinstance(required_flagships, list):
        required_flagships = list(DEFAULT_FLAGSHIP_COMPANIES)
    flagship_results: list[dict[str, Any]] = []
    for company in required_flagships:
        slug = DEFAULT_FLAGSHIP_COMPANIES.get(str(company))
        latest = _latest_summary_json(gate_dir, prefix=slug) if slug else None
        payload = _read_json(latest) if latest else {}
        verdict = str(payload.get("verdict") or "MISSING")
        passed = verdict == "GO"
        checks.append(
            _criterion(
                f"flagship:{company}",
                passed,
                f"{company} gate verdict is {verdict}",
                actual=verdict,
                expected="GO",
            )
        )
        flagship_results.append(
            {
                "company": company,
                "verdict": verdict,
                "summary_json": str(latest) if latest else None,
            }
        )

    overall = "READY" if all(check["passed"] for check in checks) else "NOT_READY"
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "prime_time_verdict": overall,
        "criteria_path": str(Path(args.criteria)),
        "readiness_summary": str(readiness_path),
        "checks": checks,
        "flagships": flagship_results,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Helios Prime-Time Readiness",
        "",
        f"- Verdict: **{summary['prime_time_verdict']}**",
        f"- Generated: {summary['generated_at']}",
        f"- Criteria: {summary['criteria_path']}",
        f"- Readiness summary: {summary['readiness_summary']}",
        "",
        "## Checks",
        "",
    ]
    for check in summary["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        expected = f" | expected `{check['expected']}`" if check.get("expected") is not None else ""
        actual = f" | actual `{check['actual']}`" if check.get("actual") is not None else ""
        lines.append(f"- {status} `{check['name']}`: {check['detail']}{actual}{expected}")

    lines.extend(["", "## Flagships", ""])
    for item in summary["flagships"]:
        lines.append(
            f"- {item['company']}: **{item['verdict']}**"
            + (f" | {item['summary_json']}" if item.get("summary_json") else "")
        )
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(summary: dict[str, Any], *, output_json: str = "", output_md: str = "") -> None:
    if output_json:
        path = Path(output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if output_md:
        path = Path(output_md)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(summary), encoding="utf-8")


def main() -> int:
    args = parse_args()
    summary = evaluate(args)
    write_outputs(summary, output_json=args.output_json, output_md=args.output_md)
    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"{summary['prime_time_verdict']}: prime-time readiness")
        print(f"Readiness summary: {summary['readiness_summary']}")
        for check in summary["checks"]:
            status = "PASS" if check["passed"] else "FAIL"
            print(f"- {status} {check['name']}: {check['detail']}")
    return 0 if summary["prime_time_verdict"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
