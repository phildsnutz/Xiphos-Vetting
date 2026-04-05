from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


MODULE_PATH = Path("/Users/tyegonzalez/Desktop/Helios-Package Merged/scripts/run_beta_hardening_report.py")
spec = importlib.util.spec_from_file_location("beta_hardening_report", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_validate_graph_payload_flags_missing_endpoints():
    graph = {
        "root_entity_id": "root-1",
        "entities": [{"id": "root-1"}, {"id": "other-1"}],
        "relationships": [
            {
                "source_entity_id": "root-1",
                "target_entity_id": "missing-entity",
                "rel_type": "contracts_with",
                "corroboration_count": 2,
            }
        ],
    }

    ok, stats, failures, warnings = module.validate_graph_payload(graph)

    assert ok is False
    assert stats["corroborated_edges"] == 1
    assert stats["missing_endpoints"] == 1
    assert any("missing hydrated endpoints" in failure for failure in failures)
    assert warnings == []


def test_validate_section_checks_reports_missing_markers():
    ok, failures = module.validate_section_checks(
        "Risk Storyline only",
        {"risk_storyline": "Risk Storyline", "ai_brief": "Axiom Assessment"},
        "html dossier",
    )

    assert ok is False
    assert failures == ["html dossier missing ai brief"]


def test_hardening_checks_include_supplier_passport_marker():
    assert module.HTML_SECTION_CHECKS["supplier_passport"] == "Supplier passport"
    assert module.PDF_SECTION_CHECKS["supplier_passport"] == "SUPPLIER PASSPORT"


def test_load_case_ids_from_cohort_reads_json(tmp_path):
    cohort = tmp_path / "cohort.json"
    cohort.write_text('[{"id":"case-1"},{"id":"case-2"}]', encoding="utf-8")

    assert module.load_case_ids_from_cohort(str(cohort)) == ["case-1", "case-2"]


def test_resolve_cached_analysis_falls_back_to_any_creator(monkeypatch):
    calls = []

    def fake_get_latest_analysis(case_id, user_id="", input_hash=""):
        calls.append((case_id, user_id, input_hash))
        if user_id == "dev":
            return None
        return {"created_by": "operator-1", "input_hash": input_hash}

    monkeypatch.setattr(module, "get_latest_analysis", fake_get_latest_analysis)

    cached, creator = module.resolve_cached_analysis("case-1", "hash-1")

    assert cached == {"created_by": "operator-1", "input_hash": "hash-1"}
    assert creator == "operator-1"
    assert calls == [("case-1", "dev", "hash-1"), ("case-1", "", "hash-1")]


def test_render_markdown_includes_readiness_section():
    summary = {
        "generated_at": "2026-03-27T12:00:00",
        "graph_depth": 3,
        "cases_checked": 1,
        "cases_with_failures": 0,
        "html_failures": 0,
        "pdf_failures": 0,
        "graph_failures": 0,
        "ai_missing": 0,
        "ai_not_warmed": 0,
        "monitoring_missing": 0,
        "warning_count": 0,
        "tiers": {"TIER_4_CLEAR": 1},
        "neo4j": {
            "required": True,
            "neo4j_available": True,
            "status": "healthy",
        },
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
                "zero_control_drop": 4,
                "new_ownership_edges": 6,
                "new_financing_edges": 1,
                "new_intermediary_edges": 2,
            },
        },
        "cases": [
            {
                "vendor_name": "Demo Vendor",
                "case_id": "c-1",
                "tier": "TIER_4_CLEAR",
                "html_ok": True,
                "pdf_ok": True,
                "graph_ok": True,
                "html_ms": 1,
                "pdf_ms": 1,
                "graph_ms": 1,
                "graph_entities": 1,
                "graph_relationships": 1,
                "graph_corroborated_edges": 0,
                "monitoring_ready": True,
                "ai_ready": True,
                "ai_expected": True,
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


def test_run_readiness_parses_subprocess_payload(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = json.dumps({"overall_verdict": "GO", "report_md": "/tmp/a.md", "report_json": "/tmp/a.json", "steps": []})
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: FakeProc())
    args = module.argparse.Namespace(
        skip_readiness=False,
        report_dir="/tmp/reports",
        readiness_base_url="http://127.0.0.1:8080",
        readiness_email="",
        readiness_password="",
        readiness_token="",
        readiness_company=[],
    )
    payload = module.run_readiness(args)
    assert payload["overall_verdict"] == "GO"
    assert payload["returncode"] == 0


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


def test_run_prime_time_parses_subprocess_payload(monkeypatch, tmp_path):
    class FakeProc:
        returncode = 0
        stdout = json.dumps({"prime_time_verdict": "READY", "checks": [], "flagships": []})
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: FakeProc())
    readiness = {"report_json": str(tmp_path / "readiness.json")}
    query_to_dossier = {"report_json": str(tmp_path / "query-to-dossier.json")}
    payload = module.run_prime_time(
        module.argparse.Namespace(skip_prime_time=False),
        readiness,
        query_to_dossier,
        tmp_path,
        "20260329-010101",
    )
    assert payload["prime_time_verdict"] == "READY"
    assert payload["report_json"].endswith(".json")
    assert payload["returncode"] == 0


def test_run_query_to_dossier_parses_subprocess_payload(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = json.dumps({"overall_verdict": "PASS", "report_md": "/tmp/g.md", "report_json": "/tmp/g.json", "flows": []})
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: FakeProc())
    args = module.argparse.Namespace(
        skip_query_to_dossier=False,
        gauntlet_mode="fixture",
        gauntlet_base_url="http://127.0.0.1:8080",
        gauntlet_email="",
        gauntlet_password="",
        gauntlet_token="",
        gauntlet_spec_file="",
        report_dir="/tmp/reports",
    )
    payload = module.run_query_to_dossier(args)
    assert payload["overall_verdict"] == "PASS"
    assert payload["returncode"] == 0


def test_run_thin_vendor_wave_parses_subprocess_payload(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = json.dumps(
            {
                "kpi_gate": {
                    "status": "PASS",
                    "zero_control_drop": 2,
                    "new_ownership_edges": 3,
                    "new_financing_edges": 1,
                    "new_intermediary_edges": 0,
                },
                "report_json": "/tmp/thin-wave.json",
                "report_markdown": "/tmp/thin-wave.md",
            }
        )
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: FakeProc())
    args = module.argparse.Namespace(
        skip_thin_vendor_wave=False,
        thin_vendor_wave_limit=10,
        thin_vendor_wave_depth=3,
        thin_vendor_wave_scan_limit=10000,
        thin_vendor_wave_max_root_entities=1,
        thin_vendor_wave_max_relationships=2,
        report_dir="/tmp/reports",
    )
    payload = module.run_thin_vendor_wave(args)
    assert payload["kpi_gate"]["status"] == "PASS"
    assert payload["report_md"] == "/tmp/thin-wave.md"
    assert payload["returncode"] == 0


def test_warm_monitoring_history_returns_true_when_history_appears(monkeypatch):
    class FakeMonitor:
        def __init__(self, check_interval=0):
            self.check_interval = check_interval

        def check_vendor(self, case_id):
            return {"vendor_id": case_id}

    calls = {"count": 0}

    def fake_get_history(case_id, limit=1):
        calls["count"] += 1
        return [{"vendor_id": case_id}]

    fake_monitor_module = types.ModuleType("monitor")
    fake_monitor_module.VendorMonitor = FakeMonitor
    monkeypatch.setitem(sys.modules, "monitor", fake_monitor_module)
    monkeypatch.setattr(module.db, "get_monitoring_history", fake_get_history)

    assert module._warm_monitoring_history("case-1") is True
