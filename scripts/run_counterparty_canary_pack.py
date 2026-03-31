#!/usr/bin/env python3
"""
Run the customer demo gate across the fixed counterparty acceptance set.

This is the systemic safety check for next week:
if the acceptance set does not stay green, Helios is not stable enough to trust in
front of a customer.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = ROOT / "scripts" / "run_customer_demo_gate.py"
DEFAULT_PACK_FILE = ROOT / "fixtures" / "customer_demo" / "counterparty_canary_pack.json"
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "counterparty_canary_pack"

SPEC = importlib.util.spec_from_file_location("run_customer_demo_gate", GATE_SCRIPT)
gate = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the fixed counterparty counterparty acceptance set.")
    parser.add_argument("--base-url", default=gate.DEFAULT_BASE_URL)
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--pack-file", default=str(DEFAULT_PACK_FILE))
    parser.add_argument("--program", default="dod_unclassified")
    parser.add_argument("--profile", default="defense_acquisition")
    parser.add_argument("--connector", action="append", default=[])
    parser.add_argument("--include-ai", action="store_true", default=True)
    parser.add_argument("--skip-ai", dest="include_ai", action="store_false")
    parser.add_argument("--ai-readiness-mode", choices=("full", "surface"), default="surface")
    parser.add_argument("--check-assistant", action="store_true", default=True)
    parser.add_argument("--skip-assistant", dest="check_assistant", action="store_false")
    parser.add_argument("--require-dossier-html", action="store_true", default=True)
    parser.add_argument("--skip-dossier-html", dest="require_dossier_html", action="store_false")
    parser.add_argument("--require-dossier-pdf", action="store_true", default=True)
    parser.add_argument("--skip-dossier-pdf", dest="require_dossier_pdf", action="store_false")
    parser.add_argument("--max-enrich-seconds", type=int, default=90)
    parser.add_argument("--max-dossier-seconds", type=int, default=60)
    parser.add_argument("--max-pdf-seconds", type=int, default=60)
    parser.add_argument("--max-ai-seconds", type=int, default=90)
    parser.add_argument("--max-warnings", type=int, default=2)
    parser.add_argument(
        "--minimum-official-corroboration",
        choices=("missing", "public_only", "partial", "strong"),
        default="missing",
    )
    parser.add_argument("--max-blocked-official-connectors", type=int, default=-1)
    parser.add_argument("--wait-for-ready-seconds", type=int, default=0)
    parser.add_argument("--auto-stabilize", action="store_true", default=True)
    parser.add_argument("--skip-auto-stabilize", dest="auto_stabilize", action="store_false")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--start-stagger-seconds", type=float, default=1.5)
    parser.add_argument("--transient-retries-per-company", type=int, default=1)
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def load_pack(path: str) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("counterparty acceptance set must be a JSON list")
    for entry in payload:
        if not isinstance(entry, dict):
            raise SystemExit("counterparty acceptance set entries must be objects")
        if "connectors" in entry and not isinstance(entry["connectors"], list):
            raise SystemExit("counterparty acceptance set entry connectors must be a list")
        if "seed_metadata" in entry and not isinstance(entry["seed_metadata"], dict):
            raise SystemExit("counterparty acceptance set entry seed_metadata must be an object")
        if "fixture_files" in entry and not isinstance(entry["fixture_files"], dict):
            raise SystemExit("counterparty acceptance set entry fixture_files must be an object")
    return payload


def overall_verdict(results: list[dict]) -> str:
    verdicts = {item["verdict"] for item in results}
    if "NO_GO" in verdicts:
        return "NO_GO"
    if "CAUTION" in verdicts:
        return "CAUTION"
    return "GO"


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _build_gate_namespace(
    args: argparse.Namespace,
    entry: dict,
    *,
    output_dir: Path,
    wait_for_ready_seconds: int,
) -> argparse.Namespace:
    repo_relative_fixture_keys = {"public_html_fixture_page", "public_html_fixture_pages"}
    seed_metadata = {
        str(key): os.path.expandvars(str(value)) if isinstance(value, str) else value
        for key, value in dict(entry.get("seed_metadata") or {}).items()
    }
    for key, raw_path in (entry.get("fixture_files") or {}).items():
        fixture_path = Path(str(raw_path))
        if str(key) in repo_relative_fixture_keys and not fixture_path.is_absolute():
            seed_metadata[str(key)] = str(raw_path)
            continue
        if not fixture_path.is_absolute():
            fixture_path = (ROOT / fixture_path).resolve()
        seed_metadata[str(key)] = fixture_path.as_uri()
    return argparse.Namespace(
        base_url=args.base_url,
        email=args.email,
        password=args.password,
        token=args.token,
        company=entry["company"],
        country=entry.get("country", "US"),
        case_id="",
        program=args.program,
        profile=args.profile,
        connector=list(entry.get("connectors") or args.connector),
        include_ai=args.include_ai,
        ai_readiness_mode=args.ai_readiness_mode,
        check_assistant=args.check_assistant,
        require_dossier_html=args.require_dossier_html,
        require_dossier_pdf=args.require_dossier_pdf,
        max_enrich_seconds=args.max_enrich_seconds,
        max_dossier_seconds=args.max_dossier_seconds,
        max_pdf_seconds=args.max_pdf_seconds,
        max_ai_seconds=args.max_ai_seconds,
        max_warnings=args.max_warnings,
        wait_for_ready_seconds=wait_for_ready_seconds,
        auto_stabilize=args.auto_stabilize,
        expected_domain=entry.get("expected_domain", ""),
        expected_cage=entry.get("expected_cage", ""),
        expected_uei=entry.get("expected_uei", ""),
        expected_duns=entry.get("expected_duns", ""),
        expected_cik=entry.get("expected_cik", ""),
        expected_uen=entry.get("expected_uen", ""),
        expected_nzbn=entry.get("expected_nzbn", ""),
        expected_nz_company_number=entry.get("expected_nz_company_number", ""),
        expected_norway_org_number=entry.get("expected_norway_org_number", ""),
        expected_abn=entry.get("expected_abn", ""),
        expected_acn=entry.get("expected_acn", ""),
        expected_business_number=entry.get("expected_business_number", ""),
        expected_ca_corporation_number=entry.get("expected_ca_corporation_number", ""),
        expected_kvk_number=entry.get("expected_kvk_number", ""),
        expected_fr_siren=entry.get("expected_fr_siren", ""),
        expected_min_control_paths=int(entry.get("expected_min_control_paths", 0) or 0),
        expected_control_target=entry.get("expected_control_target", ""),
        warn_on_empty_control_paths=bool(
            entry.get("warn_on_empty_control_paths", False)
            or entry.get("expected_min_control_paths")
            or entry.get("expected_control_target")
        ),
        seed_metadata=seed_metadata,
        require_monitoring_history=bool(entry.get("require_monitoring_history", False)),
        max_blocked_official_connectors=(
            int(entry["max_blocked_official_connectors"])
            if "max_blocked_official_connectors" in entry and entry.get("max_blocked_official_connectors") is not None
            else int(args.max_blocked_official_connectors)
        ),
        minimum_official_corroboration=(
            str(entry.get("minimum_official_corroboration") or "").strip()
            or str(args.minimum_official_corroboration)
        ),
        report_dir=str(output_dir),
        print_json=False,
    )


def _has_transient_failure(payload: dict) -> bool:
    failure_text = "\n".join(str(item) for item in payload.get("failures") or []).lower()
    transient_markers = (
        "connection aborted",
        "remote end closed connection without response",
        "connection refused",
        "readtimeout",
        "read timed out",
        "service not ready",
        "temporarily unavailable",
    )
    return any(marker in failure_text for marker in transient_markers)


def _run_entry(index: int, total: int, entry: dict, args: argparse.Namespace, output_dir: Path) -> tuple[int, dict]:
    _progress(f"[counterparty canary {index}/{total}] starting {entry['company']}")
    started = time.time()
    payload: dict | None = None
    max_attempts = max(1, int(args.transient_retries_per_company) + 1)
    for attempt in range(1, max_attempts + 1):
        ns = _build_gate_namespace(args, entry, output_dir=output_dir, wait_for_ready_seconds=0)
        result = gate.run_demo_gate(ns)
        gate.write_report(Path(result.artifacts["html"]).parent, result)
        payload = asdict(result)
        if result.verdict != "NO_GO" or not _has_transient_failure(payload) or attempt >= max_attempts:
            break
        backoff_seconds = float(min(2 ** (attempt - 1), 4))
        _progress(
            f"[counterparty canary {index}/{total}] transient failure for {entry['company']} "
            f"on attempt {attempt}/{max_attempts}, retrying in {backoff_seconds:.1f}s"
        )
        time.sleep(backoff_seconds)
    assert payload is not None
    payload["bucket"] = entry.get("bucket", "")
    _progress(
        f"[counterparty canary {index}/{total}] {payload['verdict']} {entry['company']} "
        f"({time.time() - started:.1f}s)"
    )
    return index, payload


def write_report(output_dir: Path, results: list[dict]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    verdict = overall_verdict(results)
    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "overall_verdict": verdict,
        "verdict": verdict,
        "companies": results,
    }
    json_path = output_dir / "summary.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Helios Counterparty Acceptance Set",
        "",
        f"- Overall verdict: **{summary['overall_verdict']}**",
        f"- Companies checked: {len(results)}",
        "",
    ]
    for item in results:
        lines.extend(
            [
                f"## {item['company_name']}",
                "",
                f"- Verdict: **{item['verdict']}**",
                f"- Bucket: {item.get('bucket') or 'unlabeled'}",
                f"- Case ID: `{item['case_id']}`",
                f"- Failures: {len(item['failures'])}",
                f"- Warnings: {len(item['warnings'])}",
                f"- HTML: [{Path(item['artifacts']['html']).name}]({item['artifacts']['html']})",
                f"- PDF: [{Path(item['artifacts']['pdf']).name}]({item['artifacts']['pdf']})",
                "",
            ]
        )
        if item["failures"]:
            lines.append("Failures:")
            lines.extend([f"- {entry}" for entry in item["failures"]])
            lines.append("")
        if item["warnings"]:
            lines.append("Warnings:")
            lines.extend([f"- {entry}" for entry in item["warnings"]])
            lines.append("")

    md_path = output_dir / "summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path


def main() -> int:
    args = parse_args()
    pack = load_pack(args.pack_file)
    wait_client = gate.DemoGateClient(
        args.base_url,
        email=args.email,
        password=args.password,
        token=args.token,
        timeout=max(args.max_enrich_seconds, args.max_dossier_seconds, args.max_pdf_seconds, args.max_ai_seconds, 30),
    )
    try:
        if args.wait_for_ready_seconds:
            wait_client.wait_until_ready(args.wait_for_ready_seconds)
        if not args.token:
            wait_client._login()
    finally:
        wait_client.close()

    output_dir = Path(args.report_dir) / datetime.utcnow().strftime("%Y%m%d%H%M%S")
    results_by_index: dict[int, dict] = {}
    total = len(pack)

    if args.workers <= 1:
        for index, entry in enumerate(pack, start=1):
            _, payload = _run_entry(index, total, entry, args, output_dir)
            results_by_index[index] = payload
            write_report(output_dir, [results_by_index[i] for i in sorted(results_by_index)])
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {}
            for index, entry in enumerate(pack, start=1):
                futures[executor.submit(_run_entry, index, total, entry, args, output_dir)] = index
                if args.start_stagger_seconds > 0 and index < total:
                    time.sleep(args.start_stagger_seconds)
            for future in as_completed(futures):
                index, payload = future.result()
                results_by_index[index] = payload
                write_report(output_dir, [results_by_index[i] for i in sorted(results_by_index)])

    results = [results_by_index[i] for i in sorted(results_by_index)]
    md_path, json_path = write_report(output_dir, results)
    verdict = overall_verdict(results)
    summary = {
        "overall_verdict": verdict,
        "verdict": verdict,
        "companies": results,
        "report_md": str(md_path),
        "report_json": str(json_path),
    }
    if args.print_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"{overall_verdict(results)}: counterparty acceptance set ({len(results)} companies)")
        print(f"Report: {md_path}")
        print(f"JSON: {json_path}")

    if overall_verdict(results) == "NO_GO":
        return 1
    if overall_verdict(results) == "CAUTION":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
