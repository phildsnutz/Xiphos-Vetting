#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from adversarial_gym import DEFAULT_FIXTURE, evaluate_scenarios, load_scenarios, render_markdown  # type: ignore


def utc_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Helios adversarial scenario gym.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE), help="Path to adversarial scenario fixture JSON.")
    parser.add_argument("--output-json", default="", help="Optional output JSON path.")
    parser.add_argument("--output-md", default="", help="Optional output markdown path.")
    args = parser.parse_args()

    scenarios = load_scenarios(args.fixture)
    report = evaluate_scenarios(scenarios)
    markdown = render_markdown(report, args.fixture)

    output_json = Path(args.output_json) if args.output_json else ROOT / "docs" / "reports" / f"helios-adversarial-gym-{utc_slug()}.json"
    output_md = Path(args.output_md) if args.output_md else ROOT / "docs" / "reports" / f"HELIOS_ADVERSARIAL_GYM_{utc_slug()}.md"
    output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    output_md.write_text(markdown, encoding="utf-8")

    print(f"Adversarial gym complete: {report['passed_count']}/{report['scenario_count']} passed")
    print(output_json)
    print(output_md)
    return 0 if report["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
