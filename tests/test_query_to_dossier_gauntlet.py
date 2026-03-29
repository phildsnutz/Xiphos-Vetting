from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("/Users/tyegonzalez/Desktop/Helios-Package Merged/scripts/run_query_to_dossier_gauntlet.py")
spec = importlib.util.spec_from_file_location("query_to_dossier_gauntlet", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_fixture_flow_passes_end_to_end():
    result = module.run_fixture_flow()

    assert result["flow_verdict"] == "PASS"
    assert result["case_id"].startswith("c-")
    assert result["download_url"].startswith("/api/dossiers/")
    assert [step["step"] for step in result["steps"]] == [
        "health",
        "ai_providers",
        "compare",
        "create_case",
        "case_detail",
        "graph",
        "supplier_passport",
        "assistant_plan",
        "assistant_execute",
        "dossier_html",
        "dossier_pdf",
    ]
    assert all(step["status"] == "PASS" for step in result["steps"])


def test_render_markdown_includes_flow_table():
    summary = {
        "generated_at": "2026-03-29T12:00:00Z",
        "mode": "fixture",
        "overall_verdict": "PASS",
        "flows": [
            {
                "flow_name": "fixture",
                "flow_verdict": "PASS",
                "total_ms": 1234,
                "case_id": "c-123",
                "vendor_name": "Fixture Vendor",
                "steps": [
                    {
                        "step": "compare",
                        "status": "PASS",
                        "duration_ms": 12,
                        "details": {"comparison_count": 2},
                    }
                ],
            }
        ],
        "failures": [],
    }

    markdown = module.render_markdown(summary)

    assert "# Helios Query-to-Dossier Gauntlet" in markdown
    assert "## fixture" in markdown
    assert "| `compare` | `PASS` | `12` |" in markdown


def test_main_fixture_mode_prints_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(module, "parse_args", lambda: module.argparse.Namespace(
        mode="fixture",
        base_url="http://127.0.0.1:8080",
        email="",
        password="",
        token="",
        report_dir=str(tmp_path),
        print_json=True,
    ))

    exit_code = module.main()
    captured = capsys.readouterr().out
    payload = json.loads(captured)

    assert exit_code == 0
    assert payload["overall_verdict"] == "PASS"
    assert Path(payload["report_md"]).exists()
    assert Path(payload["report_json"]).exists()
