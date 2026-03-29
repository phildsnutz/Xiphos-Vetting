from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_helios_readiness_report.py"
SPEC = importlib.util.spec_from_file_location("run_helios_readiness_report", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_overall_verdict_rolls_up_worst_case():
    results = [
        module.StepResult("counterparty", "counterparty", "GO", ["python"], 0, "", ""),
        module.StepResult("export", "export", "NO_GO", ["python"], 1, "", ""),
        module.StepResult("assurance", "supply_chain_assurance", "GO", ["python"], 0, "", ""),
    ]
    assert module.overall_verdict(results) == "NO_GO"


def test_build_lane_command_selects_export_script(tmp_path):
    command, artifact_json, artifact_md = module.build_lane_command(
        "export_ambiguous_end_use",
        "export",
        "fixtures/adversarial_gym/export_lane_ai_ambiguous_end_use_cases.json",
        tmp_path,
    )
    joined = " ".join(command)
    assert "run_export_ai_gauntlet.py" in joined
    assert str(artifact_json).endswith("export/export_ambiguous_end_use.json")
    assert str(artifact_md).endswith("export/export_ambiguous_end_use.md")


def test_run_step_loads_artifact_json_when_stdout_is_not_json(tmp_path, monkeypatch):
    artifact_json = tmp_path / "artifact.json"
    artifact_md = tmp_path / "artifact.md"
    artifact_json.write_text(json.dumps({"pass_rate": 1.0, "passed_count": 8, "scenario_count": 8}), encoding="utf-8")
    artifact_md.write_text("# report\n", encoding="utf-8")

    class FakeProc:
        returncode = 0
        stdout = "gauntlet complete\n"
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: FakeProc())
    result = module.run_step(
        "export_ambiguous_end_use",
        "export",
        ["python", "gauntlet.py"],
        artifact_json=artifact_json,
        artifact_md=artifact_md,
    )
    assert result.verdict == "GO"
    assert result.payload == {"pass_rate": 1.0, "passed_count": 8, "scenario_count": 8}
    assert result.artifact_json == str(artifact_json)


def test_run_step_uses_report_paths_from_payload(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = json.dumps({"overall_verdict": "GO", "report_json": "tmp/out.json", "report_md": "tmp/out.md"})
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: FakeProc())
    result = module.run_step("counterparty", "counterparty", ["python", "counterparty.py"], counterparty=True)
    assert result.artifact_json == "tmp/out.json"
    assert result.artifact_md == "tmp/out.md"


def test_load_lane_pack_requires_complete_entries(tmp_path):
    lane_pack = tmp_path / "lane.json"
    lane_pack.write_text(
        json.dumps([{"name": "export_pack", "pillar": "export", "fixture": "fixtures/a.json"}]),
        encoding="utf-8",
    )
    loaded = module.load_lane_pack(str(lane_pack))
    assert loaded == [{"name": "export_pack", "pillar": "export", "fixture": "fixtures/a.json"}]


def test_default_lane_pack_contains_three_export_and_three_assurance_steps():
    loaded = module.load_lane_pack(str(module.DEFAULT_LANE_PACK))
    export_steps = [entry for entry in loaded if entry["pillar"] == "export"]
    assurance_steps = [entry for entry in loaded if entry["pillar"] == "supply_chain_assurance"]
    assert len(export_steps) == 3
    assert len(assurance_steps) == 3


def test_build_counterparty_command_includes_ready_wait():
    args = module.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="ops@example.com",
        password="secret",
        token="",
        company=[],
        country="US",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=True,
        ai_readiness_mode="surface",
        check_assistant=True,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        minimum_official_corroboration="strong",
        max_blocked_official_connectors=3,
        wait_for_ready_seconds=180,
        report_dir=str(ROOT / "tmp" / "helios"),
    )
    command = module.build_counterparty_command(args)
    joined = " ".join(command)
    assert "--wait-for-ready-seconds 180" in joined
    assert "--ai-readiness-mode surface" in joined
    assert "--minimum-official-corroboration strong" in joined
    assert "--max-blocked-official-connectors 3" in joined
    assert "--print-json" in command


def test_write_report_includes_verdict_alias(tmp_path):
    results = [
        module.StepResult("counterparty", "counterparty", "GO", ["python"], 0, "", ""),
        module.StepResult("export", "export", "GO", ["python"], 0, "", ""),
    ]
    _, json_path = module.write_report(tmp_path, results)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["overall_verdict"] == "GO"
    assert payload["verdict"] == "GO"
