from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_prime_time_readiness.py"
SPEC = importlib.util.spec_from_file_location("evaluate_prime_time_readiness", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_evaluate_prime_time_readiness_ready(tmp_path):
    readiness_dir = tmp_path / "helios_readiness" / "20260329020000"
    readiness_dir.mkdir(parents=True)
    readiness_summary = readiness_dir / "summary.json"
    readiness_summary.write_text(
        json.dumps(
            {
                "verdict": "GO",
                "steps": [
                    {"pillar": "counterparty", "verdict": "GO", "elapsed_seconds": 320.0},
                    {"pillar": "export", "verdict": "GO", "elapsed_seconds": 1.0},
                    {"pillar": "supply_chain_assurance", "verdict": "GO", "elapsed_seconds": 1.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    gauntlet_dir = tmp_path / "live_query_to_dossier_canary" / "query_to_dossier_gauntlet" / "20260329020000"
    gauntlet_dir.mkdir(parents=True)
    query_to_dossier_summary = gauntlet_dir / "summary.json"
    query_to_dossier_summary.write_text(
        json.dumps(
            {
                "overall_verdict": "PASS",
                "oci_summary": {
                    "required_flows": 1,
                    "passed_flows": 1,
                    "descriptor_only_passed_flows": 1,
                },
            }
        ),
        encoding="utf-8",
    )

    acceptance_set = tmp_path / "acceptance.json"
    acceptance_set.write_text(json.dumps([{"company": f"Company {i}"} for i in range(15)]), encoding="utf-8")
    stable_pack = tmp_path / "stable-pack.json"
    stable_pack.write_text(json.dumps([{"company": f"Canary {i}"} for i in range(10)]), encoding="utf-8")
    gate_dir = tmp_path / "customer_demo_gate"
    for slug in module.DEFAULT_FLAGSHIP_COMPANIES.values():
        summary_dir = gate_dir / f"{slug}-20260329020000"
        summary_dir.mkdir(parents=True)
        (summary_dir / "summary.json").write_text(json.dumps({"verdict": "GO"}), encoding="utf-8")

    args = module.argparse.Namespace(
        criteria=str(module.DEFAULT_CRITERIA),
        readiness_summary=str(readiness_summary),
        readiness_dir=str(tmp_path / "helios_readiness"),
        query_to_dossier_summary=str(query_to_dossier_summary),
        query_to_dossier_dir=str(tmp_path / "live_query_to_dossier_canary" / "query_to_dossier_gauntlet"),
        acceptance_set=str(acceptance_set),
        stable_canary_pack=str(stable_pack),
        customer_demo_gate_dir=str(gate_dir),
        output_json="",
        output_md="",
        print_json=False,
    )

    summary = module.evaluate(args)
    assert summary["prime_time_verdict"] == "READY"


def test_evaluate_prime_time_readiness_fails_counterparty_runtime(tmp_path):
    readiness_dir = tmp_path / "helios_readiness" / "20260329020000"
    readiness_dir.mkdir(parents=True)
    readiness_summary = readiness_dir / "summary.json"
    readiness_summary.write_text(
        json.dumps(
            {
                "verdict": "GO",
                "steps": [
                    {"pillar": "counterparty", "verdict": "GO", "elapsed_seconds": 700.0},
                    {"pillar": "export", "verdict": "GO", "elapsed_seconds": 1.0},
                    {"pillar": "supply_chain_assurance", "verdict": "GO", "elapsed_seconds": 1.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    gauntlet_dir = tmp_path / "live_query_to_dossier_canary" / "query_to_dossier_gauntlet" / "20260329020000"
    gauntlet_dir.mkdir(parents=True)
    query_to_dossier_summary = gauntlet_dir / "summary.json"
    query_to_dossier_summary.write_text(
        json.dumps(
            {
                "overall_verdict": "PASS",
                "oci_summary": {
                    "required_flows": 1,
                    "passed_flows": 1,
                    "descriptor_only_passed_flows": 1,
                },
            }
        ),
        encoding="utf-8",
    )

    acceptance_set = tmp_path / "acceptance.json"
    acceptance_set.write_text(json.dumps([{"company": f"Company {i}"} for i in range(15)]), encoding="utf-8")
    stable_pack = tmp_path / "stable-pack.json"
    stable_pack.write_text(json.dumps([{"company": f"Canary {i}"} for i in range(10)]), encoding="utf-8")
    gate_dir = tmp_path / "customer_demo_gate"
    for slug in module.DEFAULT_FLAGSHIP_COMPANIES.values():
        summary_dir = gate_dir / f"{slug}-20260329020000"
        summary_dir.mkdir(parents=True)
        (summary_dir / "summary.json").write_text(json.dumps({"verdict": "GO"}), encoding="utf-8")

    args = module.argparse.Namespace(
        criteria=str(module.DEFAULT_CRITERIA),
        readiness_summary=str(readiness_summary),
        readiness_dir=str(tmp_path / "helios_readiness"),
        query_to_dossier_summary=str(query_to_dossier_summary),
        query_to_dossier_dir=str(tmp_path / "live_query_to_dossier_canary" / "query_to_dossier_gauntlet"),
        acceptance_set=str(acceptance_set),
        stable_canary_pack=str(stable_pack),
        customer_demo_gate_dir=str(gate_dir),
        output_json="",
        output_md="",
        print_json=False,
    )

    summary = module.evaluate(args)
    assert summary["prime_time_verdict"] == "NOT_READY"
    runtime_check = next(check for check in summary["checks"] if check["name"] == "counterparty_runtime")
    assert runtime_check["passed"] is False


def test_evaluate_prime_time_readiness_fails_query_to_dossier(tmp_path):
    readiness_dir = tmp_path / "helios_readiness" / "20260329020000"
    readiness_dir.mkdir(parents=True)
    readiness_summary = readiness_dir / "summary.json"
    readiness_summary.write_text(
        json.dumps(
            {
                "verdict": "GO",
                "steps": [
                    {"pillar": "counterparty", "verdict": "GO", "elapsed_seconds": 320.0},
                    {"pillar": "export", "verdict": "GO", "elapsed_seconds": 1.0},
                    {"pillar": "supply_chain_assurance", "verdict": "GO", "elapsed_seconds": 1.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    gauntlet_dir = tmp_path / "live_query_to_dossier_canary" / "query_to_dossier_gauntlet" / "20260329020000"
    gauntlet_dir.mkdir(parents=True)
    query_to_dossier_summary = gauntlet_dir / "summary.json"
    query_to_dossier_summary.write_text(
        json.dumps(
            {
                "overall_verdict": "FAIL",
                "oci_summary": {
                    "required_flows": 1,
                    "passed_flows": 0,
                    "descriptor_only_passed_flows": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    acceptance_set = tmp_path / "acceptance.json"
    acceptance_set.write_text(json.dumps([{"company": f"Company {i}"} for i in range(15)]), encoding="utf-8")
    stable_pack = tmp_path / "stable-pack.json"
    stable_pack.write_text(json.dumps([{"company": f"Canary {i}"} for i in range(10)]), encoding="utf-8")
    gate_dir = tmp_path / "customer_demo_gate"
    for slug in module.DEFAULT_FLAGSHIP_COMPANIES.values():
        summary_dir = gate_dir / f"{slug}-20260329020000"
        summary_dir.mkdir(parents=True)
        (summary_dir / "summary.json").write_text(json.dumps({"verdict": "GO"}), encoding="utf-8")

    args = module.argparse.Namespace(
        criteria=str(module.DEFAULT_CRITERIA),
        readiness_summary=str(readiness_summary),
        readiness_dir=str(tmp_path / "helios_readiness"),
        query_to_dossier_summary=str(query_to_dossier_summary),
        query_to_dossier_dir=str(tmp_path / "live_query_to_dossier_canary" / "query_to_dossier_gauntlet"),
        acceptance_set=str(acceptance_set),
        stable_canary_pack=str(stable_pack),
        customer_demo_gate_dir=str(gate_dir),
        output_json="",
        output_md="",
        print_json=False,
    )

    summary = module.evaluate(args)
    assert summary["prime_time_verdict"] == "NOT_READY"
    gauntlet_check = next(check for check in summary["checks"] if check["name"] == "query_to_dossier")
    assert gauntlet_check["passed"] is False


def test_write_outputs_writes_json_and_markdown(tmp_path):
    summary = {
        "generated_at": "2026-03-29T00:00:00Z",
        "prime_time_verdict": "READY",
        "criteria_path": "/tmp/criteria.json",
        "readiness_summary": "/tmp/readiness.json",
        "query_to_dossier_summary": "/tmp/query-to-dossier.json",
        "checks": [{"name": "overall_readiness", "passed": True, "detail": "overall readiness is GO", "actual": "GO", "expected": "GO"}],
        "flagships": [{"company": "Yorktown Systems Group", "verdict": "GO", "summary_json": "/tmp/yorktown.json"}],
    }
    output_json = tmp_path / "prime-time.json"
    output_md = tmp_path / "prime-time.md"

    module.write_outputs(summary, output_json=str(output_json), output_md=str(output_md))

    assert json.loads(output_json.read_text(encoding="utf-8"))["prime_time_verdict"] == "READY"
    markdown = output_md.read_text(encoding="utf-8")
    assert "## Checks" in markdown
    assert "Yorktown Systems Group" in markdown
    assert "/tmp/query-to-dossier.json" in markdown


def test_evaluate_prime_time_readiness_fails_missing_required_oci_flow(tmp_path):
    readiness_dir = tmp_path / "helios_readiness" / "20260329020000"
    readiness_dir.mkdir(parents=True)
    readiness_summary = readiness_dir / "summary.json"
    readiness_summary.write_text(
        json.dumps(
            {
                "verdict": "GO",
                "steps": [
                    {"pillar": "counterparty", "verdict": "GO", "elapsed_seconds": 320.0},
                    {"pillar": "export", "verdict": "GO", "elapsed_seconds": 1.0},
                    {"pillar": "supply_chain_assurance", "verdict": "GO", "elapsed_seconds": 1.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    gauntlet_dir = tmp_path / "live_query_to_dossier_canary" / "query_to_dossier_gauntlet" / "20260329020000"
    gauntlet_dir.mkdir(parents=True)
    query_to_dossier_summary = gauntlet_dir / "summary.json"
    query_to_dossier_summary.write_text(
        json.dumps(
            {
                "overall_verdict": "PASS",
                "oci_summary": {
                    "required_flows": 1,
                    "passed_flows": 0,
                    "descriptor_only_passed_flows": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    acceptance_set = tmp_path / "acceptance.json"
    acceptance_set.write_text(json.dumps([{"company": f"Company {i}"} for i in range(15)]), encoding="utf-8")
    stable_pack = tmp_path / "stable-pack.json"
    stable_pack.write_text(json.dumps([{"company": f"Canary {i}"} for i in range(10)]), encoding="utf-8")
    gate_dir = tmp_path / "customer_demo_gate"
    for slug in module.DEFAULT_FLAGSHIP_COMPANIES.values():
        summary_dir = gate_dir / f"{slug}-20260329020000"
        summary_dir.mkdir(parents=True)
        (summary_dir / "summary.json").write_text(json.dumps({"verdict": "GO"}), encoding="utf-8")

    args = module.argparse.Namespace(
        criteria=str(module.DEFAULT_CRITERIA),
        readiness_summary=str(readiness_summary),
        readiness_dir=str(tmp_path / "helios_readiness"),
        query_to_dossier_summary=str(query_to_dossier_summary),
        query_to_dossier_dir=str(tmp_path / "live_query_to_dossier_canary" / "query_to_dossier_gauntlet"),
        acceptance_set=str(acceptance_set),
        stable_canary_pack=str(stable_pack),
        customer_demo_gate_dir=str(gate_dir),
        output_json="",
        output_md="",
        print_json=False,
    )

    summary = module.evaluate(args)
    assert summary["prime_time_verdict"] == "NOT_READY"
    oci_check = next(check for check in summary["checks"] if check["name"] == "query_to_dossier_oci")
    assert oci_check["passed"] is False
