from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_live_query_to_dossier_canary.py"
SPEC = importlib.util.spec_from_file_location("run_live_query_to_dossier_canary", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_live_canary_fails_when_neo4j_is_required_and_unavailable(tmp_path, monkeypatch):
    report_json = tmp_path / "summary.json"
    report_md = tmp_path / "summary.md"
    report_json.write_text(json.dumps({"overall_verdict": "PASS"}), encoding="utf-8")
    report_md.write_text("# Report\n", encoding="utf-8")

    class DummyProc:
        returncode = 0
        stdout = json.dumps(
            {
                "overall_verdict": "PASS",
                "report_json": str(report_json),
                "report_md": str(report_md),
            }
        )
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: DummyProc())
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: module.argparse.Namespace(
            base_url="http://127.0.0.1:8080",
            email="",
            password="",
            token="token",
            spec_file=str(tmp_path / "spec.json"),
            report_dir=str(tmp_path),
            require_neo4j=True,
            print_json=False,
        ),
    )
    monkeypatch.setattr(
        module,
        "probe_neo4j_health",
        lambda _base_url: {
            "http_status": 200,
            "neo4j_available": False,
            "status": "unavailable",
            "timestamp": "2026-03-29T00:00:00Z",
        },
    )

    exit_code = module.main()

    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["overall_verdict"] == "FAIL"
    assert payload["neo4j_summary"]["neo4j_available"] is False

