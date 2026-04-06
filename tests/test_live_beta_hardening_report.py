from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("/Users/tyegonzalez/Desktop/Helios-Package Merged/scripts/run_live_beta_hardening_report.py")
spec = importlib.util.spec_from_file_location("live_beta_hardening_report", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_render_markdown_includes_readiness_section():
    summary = {
        "generated_at": "2026-03-27T12:00:00",
        "host": "root@example",
        "user_id": "demo",
        "graph_depth": 3,
        "cases_checked": 1,
        "cases_with_failures": 0,
        "warning_count": 0,
        "query_to_dossier": {
            "overall_verdict": "PASS",
            "report_md": "/tmp/gauntlet.md",
            "report_json": "/tmp/gauntlet.json",
            "flows": [],
        },
        "readiness": {
            "overall_verdict": "GO",
            "report_md": "/tmp/readiness.md",
            "report_json": "/tmp/readiness.json",
            "steps": [],
        },
        "prime_time": {
            "prime_time_verdict": "READY",
            "report_md": "/tmp/prime-time.md",
            "report_json": "/tmp/prime-time.json",
        },
        "graph_95": {
            "benchmark_overall_verdict": "PASS",
            "benchmark_report_json": "/tmp/graph-benchmark.json",
            "status_md": "/tmp/GRAPH_95_STATUS.md",
        },
        "thin_vendor_wave": {
            "status": "PASS",
            "report_md": "/tmp/thin-wave.md",
            "report_json": "/tmp/thin-wave.json",
            "kpi_gate": {
                "status": "PASS",
                "zero_control_drop": 3,
                "new_ownership_edges": 5,
                "new_financing_edges": 1,
                "new_intermediary_edges": 1,
            },
        },
        "cases": [
            {
                "vendor_name": "Demo Vendor",
                "case_id": "c-1",
                "tier": "TIER_4_CLEAR",
                "monitoring_ready": True,
                "graph": {"entity_count": 1, "relationship_count": 1, "corroborated_edges": 0},
                "ai_expected": True,
                "html_markers": {"hero": True, "risk_storyline": True, "supplier_passport": True},
                "pdf_markers": {"risk_storyline": True, "supplier_passport": True, "graph_read": True},
                "failures": [],
                "warnings": [],
            }
        ],
    }
    markdown = module.render_markdown(summary)
    assert "## Query To Dossier" in markdown
    assert "Gauntlet verdict: **PASS**" in markdown
    assert "## Readiness" in markdown
    assert "Readiness verdict: **GO**" in markdown
    assert "## Prime Time" in markdown
    assert "Prime-time verdict: **READY**" in markdown
    assert "## Graph 9.5" in markdown
    assert "Graph benchmark verdict: **PASS**" in markdown
    assert "## Thin Vendor Wave" in markdown
    assert "Wave verdict: **PASS**" in markdown


def test_run_readiness_requires_auth_without_skip():
    args = module.argparse.Namespace(
        skip_readiness=False,
        readiness_base_url="http://127.0.0.1:8080",
        readiness_email="",
        readiness_password="",
        readiness_token="",
        readiness_company=[],
        report_dir="/tmp/reports",
    )
    try:
        module.run_readiness(args)
    except SystemExit as exc:
        assert "requires readiness auth" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_run_readiness_parses_subprocess_payload(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = json.dumps({"overall_verdict": "GO", "report_md": "/tmp/a.md", "report_json": "/tmp/a.json", "steps": []})
        stderr = ""

    def fake_run(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    args = module.argparse.Namespace(
        skip_readiness=False,
        readiness_base_url="http://127.0.0.1:8080",
        readiness_email="ops@example.com",
        readiness_password="secret",
        readiness_token="",
        readiness_company=["Yorktown Systems Group"],
        report_dir="/tmp/reports",
    )
    payload = module.run_readiness(args)
    assert payload["overall_verdict"] == "GO"
    assert payload["returncode"] == 0


def test_run_prime_time_parses_subprocess_payload(monkeypatch, tmp_path):
    class FakeProc:
        returncode = 0
        stdout = json.dumps({"prime_time_verdict": "READY", "checks": [], "flagships": []})
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: FakeProc())
    readiness = {"report_json": str(tmp_path / "readiness.json")}
    query_to_dossier = {"report_json": str(tmp_path / "query-to-dossier.json")}
    args = module.argparse.Namespace(skip_prime_time=False)
    payload = module.run_prime_time(args, readiness, query_to_dossier, tmp_path, "20260329-010101")
    assert payload["prime_time_verdict"] == "READY"
    assert payload["report_md"].endswith(".md")
    assert payload["returncode"] == 0


def test_run_query_to_dossier_requires_auth_without_skip():
    args = module.argparse.Namespace(
        skip_query_to_dossier=False,
        readiness_base_url="http://127.0.0.1:8080",
        readiness_email="",
        readiness_password="",
        readiness_token="",
        gauntlet_spec_file="/tmp/spec.json",
        report_dir="/tmp/reports",
    )
    try:
        module.run_query_to_dossier(args)
    except SystemExit as exc:
        assert "requires readiness auth" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_run_query_to_dossier_parses_subprocess_payload(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = json.dumps({"overall_verdict": "PASS", "report_md": "/tmp/g.md", "report_json": "/tmp/g.json", "flows": []})
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: FakeProc())
    args = module.argparse.Namespace(
        skip_query_to_dossier=False,
        readiness_base_url="http://127.0.0.1:8080",
        readiness_email="ops@example.com",
        readiness_password="secret",
        readiness_token="",
        gauntlet_spec_file="/tmp/spec.json",
        report_dir="/tmp/reports",
    )
    payload = module.run_query_to_dossier(args)
    assert payload["overall_verdict"] == "PASS"
    assert payload["returncode"] == 0


def test_run_thin_vendor_wave_parses_remote_payload(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = json.dumps(
            {
                "kpi_gate": {
                    "status": "PASS",
                    "zero_control_drop": 2,
                    "new_ownership_edges": 4,
                    "new_financing_edges": 1,
                    "new_intermediary_edges": 0,
                },
                "report_json": "/app/docs/reports/thin_vendor_refresh_wave/thin-wave.json",
                "report_markdown": "/app/docs/reports/thin_vendor_refresh_wave/thin-wave.md",
            }
        )
        stderr = ""

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return FakeProc()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    args = module.argparse.Namespace(
        skip_thin_vendor_wave=False,
        thin_vendor_wave_limit=10,
        thin_vendor_wave_depth=3,
        thin_vendor_wave_scan_limit=10000,
        thin_vendor_wave_max_root_entities=1,
        thin_vendor_wave_max_relationships=2,
        host="root@example",
        ssh_key="/tmp/id_ed25519",
        container="xiphos-xiphos-1",
    )
    payload = module.run_thin_vendor_wave(args)
    assert payload["kpi_gate"]["status"] == "PASS"
    assert payload["report_md"].endswith("thin-wave.md")
    assert captured["command"][:4] == ["ssh", "-o", "BatchMode=yes", "-i"]


def test_remote_collect_uses_ssh_key_when_provided(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = "[]"
        stderr = ""

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return FakeProc()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    payload = module.remote_collect(
        "root@example",
        "xiphos-xiphos-1",
        ["case-1"],
        3,
        "demo",
        ssh_key="/tmp/id_ed25519",
    )

    assert payload == []
    assert captured["command"][:4] == ["ssh", "-o", "BatchMode=yes", "-i"]
    assert "/tmp/id_ed25519" in captured["command"]
    assert "default=str" in captured["command"][-1]


def test_load_graph_95_status_reads_latest_benchmark(tmp_path, monkeypatch):
    benchmark_dir = tmp_path / "reports" / "graph_training_benchmark" / "20260330213029"
    benchmark_dir.mkdir(parents=True)
    (benchmark_dir / "summary.json").write_text(json.dumps({"overall_verdict": "PASS"}), encoding="utf-8")
    status_md = tmp_path / "GRAPH_95_STATUS.md"
    status_md.write_text("# status\n", encoding="utf-8")

    monkeypatch.setattr(module, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(module, "GRAPH_95_STATUS_PATH", status_md)

    payload = module._load_graph_95_status()

    assert payload["benchmark_overall_verdict"] == "PASS"
    assert payload["benchmark_report_json"].endswith("summary.json")
    assert payload["status_md"].endswith("GRAPH_95_STATUS.md")
