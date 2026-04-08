#!/usr/bin/env python3
"""
Run the same Helios AI analysis prompt through multiple configured providers and
write a side-by-side comparison report.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import db  # type: ignore  # noqa: E402
import ai_analysis  # type: ignore  # noqa: E402


DEFAULT_REPORT_ROOT = ROOT / "docs" / "reports" / "ai_provider_faceoff"


@dataclass
class ProviderResult:
    config_id: str
    provider: str
    model: str
    status: str
    elapsed_ms: int
    verdict: str
    executive_summary: str
    recommended_actions: list[str]
    error: str
    output_path: str


def _resolve_case_id(case_id: str, case_name: str) -> str:
    if case_id:
        vendor = db.get_vendor(case_id)
        if not vendor:
            raise SystemExit(f"Case not found: {case_id}")
        return case_id

    if not case_name:
        raise SystemExit("Provide --case-id or --case-name")

    matches = [
        vendor for vendor in db.list_vendors(limit=500)
        if case_name.lower() in str(vendor.get("name") or "").lower()
    ]
    if not matches:
        raise SystemExit(f"No case matches name fragment: {case_name}")
    return str(matches[0]["id"])


def _load_case_bundle(case_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    vendor = db.get_vendor(case_id)
    if not vendor:
        raise SystemExit(f"Case not found: {case_id}")
    score = db.get_latest_score(case_id)
    if not score:
        raise SystemExit(f"No score found for case: {case_id}")
    enrichment = db.get_latest_enrichment(case_id)
    return vendor, score, enrichment


def _run_provider(config_id: str, prompt: str, report_dir: Path) -> ProviderResult:
    config = ai_analysis._get_exact_ai_config(config_id)  # type: ignore[attr-defined]
    if not config:
        return ProviderResult(
            config_id=config_id,
            provider="missing",
            model="missing",
            status="missing",
            elapsed_ms=0,
            verdict="",
            executive_summary="",
            recommended_actions=[],
            error="Config not found or could not be decrypted",
            output_path="",
        )

    provider = str(config["provider"])
    model = str(config["model"])
    api_key = str(config["api_key"])
    caller = ai_analysis.PROVIDER_CALLERS.get(provider)
    if not caller:
        return ProviderResult(
            config_id=config_id,
            provider=provider,
            model=model,
            status="unsupported",
            elapsed_ms=0,
            verdict="",
            executive_summary="",
            recommended_actions=[],
            error=f"Unsupported provider: {provider}",
            output_path="",
        )

    started = time.time()
    try:
        result = caller(api_key, model, prompt)
        elapsed_ms = int((time.time() - started) * 1000)
        analysis = ai_analysis._parse_analysis_json(result["text"])  # type: ignore[attr-defined]
        output_path = report_dir / f"{config_id}.json"
        output_path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
        return ProviderResult(
            config_id=config_id,
            provider=provider,
            model=model,
            status="ok",
            elapsed_ms=elapsed_ms,
            verdict=str(analysis.get("verdict") or ""),
            executive_summary=str(analysis.get("executive_summary") or ""),
            recommended_actions=[
                str(item) for item in analysis.get("recommended_actions", [])
                if isinstance(item, str)
            ],
            error="",
            output_path=str(output_path),
        )
    except Exception as exc:  # pragma: no cover - live path
        elapsed_ms = int((time.time() - started) * 1000)
        return ProviderResult(
            config_id=config_id,
            provider=provider,
            model=model,
            status="error",
            elapsed_ms=elapsed_ms,
            verdict="",
            executive_summary="",
            recommended_actions=[],
            error=str(exc),
            output_path="",
        )


def _write_summary(
    report_dir: Path,
    case_id: str,
    vendor: dict[str, Any],
    results: list[ProviderResult],
) -> Path:
    lines = [
        f"# AI Provider Faceoff",
        "",
        f"- Generated: {datetime.utcnow().isoformat()}Z",
        f"- Case ID: `{case_id}`",
        f"- Vendor: `{vendor.get('name', '')}`",
        "",
        "| Config | Provider | Model | Status | Latency ms | Verdict |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for result in results:
        lines.append(
            f"| `{result.config_id}` | `{result.provider}` | `{result.model}` | `{result.status}` | {result.elapsed_ms} | `{result.verdict}` |"
        )

    for result in results:
        lines.extend([
            "",
            f"## {result.config_id}",
            "",
            f"- Provider: `{result.provider}`",
            f"- Model: `{result.model}`",
            f"- Status: `{result.status}`",
            f"- Latency: `{result.elapsed_ms} ms`",
        ])
        if result.error:
            lines.append(f"- Error: `{result.error}`")
            continue
        lines.append(f"- Verdict: `{result.verdict}`")
        lines.append(f"- Executive Summary: {result.executive_summary or '_none_'}")
        lines.append("- Recommended Actions:")
        if result.recommended_actions:
            for action in result.recommended_actions[:5]:
                lines.append(f"  - {action}")
        else:
            lines.append("  - _none_")
        lines.append(f"- Output: [{Path(result.output_path).name}]({Path(result.output_path)})" if result.output_path else "- Output: _none_")

    summary_path = report_dir / "summary.md"
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AI provider side-by-side analysis on one Helios case")
    parser.add_argument("--case-id", default="", help="Vendor/case id")
    parser.add_argument("--case-name", default="", help="Case name fragment if case id is unknown")
    parser.add_argument(
        "--config-id",
        action="append",
        dest="config_ids",
        default=[],
        help="Exact ai_config row ids to compare (repeatable)",
    )
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT), help="Report root directory")
    args = parser.parse_args()

    case_id = _resolve_case_id(args.case_id, args.case_name)
    vendor, score, enrichment = _load_case_bundle(case_id)
    prompt = ai_analysis._build_prompt(vendor, score, enrichment)  # type: ignore[attr-defined]

    config_ids = args.config_ids or ["__org_default__", "__anthropic_backup__", "__openai_backup__", "__gemma_backup__"]
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    report_dir = Path(args.report_root) / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)

    results = [_run_provider(config_id, prompt, report_dir) for config_id in config_ids]
    summary_path = _write_summary(report_dir, case_id, vendor, results)
    (report_dir / "results.json").write_text(
        json.dumps([asdict(result) for result in results], indent=2),
        encoding="utf-8",
    )

    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
