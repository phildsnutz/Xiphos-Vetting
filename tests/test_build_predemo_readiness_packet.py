from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_predemo_readiness_packet.py"
SPEC = importlib.util.spec_from_file_location("build_predemo_readiness_packet", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_load_acceptance_set_requires_companies(tmp_path):
    fixture = tmp_path / "acceptance.json"
    fixture.write_text(json.dumps([{"company": "Acme"}]), encoding="utf-8")
    loaded = module.load_acceptance_set(str(fixture))
    assert loaded == [{"company": "Acme"}]


def test_build_live_readiness_command_includes_surface_mode_and_wait():
    args = module.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="ops@example.com",
        password="secret",
        token="",
        ai_readiness_mode="surface",
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=120,
    )
    command = module.build_live_readiness_command(args, ROOT / "tmp" / "predemo")
    joined = " ".join(command)
    assert "--ai-readiness-mode surface" in joined
    assert "--wait-for-ready-seconds 120" in joined


def test_build_packet_summary_rolls_up_pillar_verdicts():
    readiness_dir = ROOT / "tmp" / "predemo-test"
    readiness_dir.mkdir(parents=True, exist_ok=True)
    (readiness_dir / "prime-time.md").write_text("prime", encoding="utf-8")
    (readiness_dir / "prime-time.json").write_text("{}", encoding="utf-8")
    readiness = {
        "overall_verdict": "GO",
        "report_json": str(readiness_dir / "summary.json"),
        "report_md": str(readiness_dir / "summary.md"),
        "steps": [
            {"pillar": "counterparty", "name": "identity", "verdict": "GO"},
            {"pillar": "export", "name": "ambiguous", "verdict": "GO"},
            {"pillar": "supply_chain_assurance", "name": "artifact", "verdict": "CAUTION"},
            {"pillar": "supply_chain_assurance", "name": "dependency", "verdict": "GO"},
        ],
    }
    summary = module.build_packet_summary(
        readiness,
        [{"company": "Acme", "bucket": "identity", "archetype": "prime", "why_it_matters": "coverage"}],
        str(ROOT / "fixtures" / "customer_demo" / "counterparty_acceptance_set.json"),
        "/tmp/customer.pdf",
        live_beta_hardening_md="/tmp/hardening.md",
        live_beta_hardening_json="/tmp/hardening.json",
    )
    assert summary["pillar_verdicts"]["counterparty"] == "GO"
    assert summary["pillar_verdicts"]["export"] == "GO"
    assert summary["pillar_verdicts"]["supply_chain_assurance"] == "CAUTION"
    assert summary["prime_time_report_md"].endswith("prime-time.md")
    assert summary["live_beta_hardening_report_md"] == "/tmp/hardening.md"


def test_write_packet_creates_summary_files(tmp_path):
    summary = {
        "generated_at": "2026-03-28T00:00:00Z",
        "overall_verdict": "GO",
        "counterparty_acceptance_set_size": 1,
        "counterparty_acceptance_set_path": str(ROOT / "fixtures" / "customer_demo" / "counterparty_acceptance_set.json"),
        "pillar_verdicts": {"counterparty": "GO"},
        "acceptance_archetypes": [
            {"company": "Acme", "bucket": "identity", "archetype": "prime", "why_it_matters": "coverage"}
        ],
        "steps": [{"pillar": "counterparty", "name": "identity", "verdict": "GO", "artifact_md": "a.md", "artifact_json": "a.json"}],
        "readiness_report_md": "tmp/out.md",
        "readiness_report_json": "tmp/out.json",
        "prime_time_report_md": "tmp/prime-time.md",
        "prime_time_report_json": "tmp/prime-time.json",
        "live_beta_hardening_report_md": "tmp/hardening.md",
        "live_beta_hardening_report_json": "tmp/hardening.json",
        "customer_release_matrix_pdf": "/tmp/customer.pdf",
    }
    md_path, json_path = module.write_packet(tmp_path, summary)
    assert md_path.exists()
    assert json_path.exists()
    assert "Helios Pre-Demo Readiness Packet" in md_path.read_text(encoding="utf-8")


def test_preferred_summary_json_uses_newer_report(tmp_path):
    older_dir = tmp_path / "older" / "20260328000000"
    newer_dir = tmp_path / "newer" / "20260329000000"
    older_dir.mkdir(parents=True)
    newer_dir.mkdir(parents=True)
    older = older_dir / "summary.json"
    newer = newer_dir / "summary.json"
    older.write_text("{}", encoding="utf-8")
    newer.write_text("{}", encoding="utf-8")
    assert module.preferred_summary_json(older, newer) == newer


def test_latest_live_beta_hardening_reports_returns_newest_pair(tmp_path):
    older_json = tmp_path / "helios-live-beta-hardening-report-20260328-000000.json"
    newer_json = tmp_path / "helios-live-beta-hardening-report-20260329-000000.json"
    older_md = tmp_path / "helios-live-beta-hardening-report-20260328-000000.md"
    newer_md = tmp_path / "helios-live-beta-hardening-report-20260329-000000.md"
    for path in [older_json, newer_json, older_md, newer_md]:
        path.write_text("", encoding="utf-8")
    md_path, json_path = module.latest_live_beta_hardening_reports(tmp_path)
    assert md_path == str(newer_md)
    assert json_path == str(newer_json)


def test_prime_time_artifacts_from_hardening_report_reads_paths(tmp_path):
    report = tmp_path / "helios-live-beta-hardening-report-20260329-000000.json"
    report.write_text(
        json.dumps(
            {
                "prime_time": {
                    "report_md": "/tmp/prime-time.md",
                    "report_json": "/tmp/prime-time.json",
                }
            }
        ),
        encoding="utf-8",
    )
    md_path, json_path = module.prime_time_artifacts_from_hardening_report(str(report))
    assert md_path == "/tmp/prime-time.md"
    assert json_path == "/tmp/prime-time.json"


def test_main_captures_customer_pdf_builder_output(monkeypatch, tmp_path, capsys):
    readiness_json = tmp_path / "readiness-summary.json"
    readiness_json.write_text(
        json.dumps(
            {
                "overall_verdict": "GO",
                "report_json": str(tmp_path / "readiness.json"),
                "report_md": str(tmp_path / "readiness.md"),
                "steps": [{"pillar": "counterparty", "name": "identity", "verdict": "GO"}],
            }
        ),
        encoding="utf-8",
    )

    args = module.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="",
        password="",
        token="abc123",
        packet_dir=str(tmp_path),
        acceptance_set=str(tmp_path / "acceptance.json"),
        skip_live_run=True,
        skip_customer_pdf=False,
        ai_readiness_mode="surface",
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=120,
        print_json=True,
    )

    calls: list[dict] = []

    class FakeCompleted:
        stdout = ""
        stderr = ""
        returncode = 0

    monkeypatch.setattr(module, "parse_args", lambda: args)
    monkeypatch.setattr(module, "load_acceptance_set", lambda path: [{"company": "Acme"}])
    monkeypatch.setattr(module, "latest_summary_json", lambda base_dir: readiness_json)
    monkeypatch.setattr(
        module,
        "_load_module",
        lambda path, name: type("FakeModule", (), {"OUTPUT_PDF": "/tmp/customer.pdf"})(),
    )

    def fake_run(*run_args, **run_kwargs):
        calls.append(run_kwargs)
        return FakeCompleted()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    code = module.main()
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["verdict"] == "GO"
    assert calls
    assert calls[0]["capture_output"] is True
    assert calls[0]["text"] is True
