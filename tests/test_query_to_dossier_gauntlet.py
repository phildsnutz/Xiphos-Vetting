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
        "browser_dossier_access",
        "dossier_pdf",
    ]
    assert all(step["status"] == "PASS" for step in result["steps"])
    browser_step = next(step for step in result["steps"] if step["step"] == "browser_dossier_access")
    assert browser_step["details"]["permission"] == "cases:dossier"
    assert browser_step["details"]["reopen_html_bytes"] > 0
    pdf_step = next(step for step in result["steps"] if step["step"] == "dossier_pdf")
    assert pdf_step["details"]["content_disposition"].startswith("attachment; filename=dossier-")


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


def test_load_specs_merges_defaults_and_expected_lane(tmp_path):
    spec_file = tmp_path / "gauntlet-pack.json"
    spec_file.write_text(
        json.dumps(
            [
                {
                    "flow_name": "export_trade",
                    "expected_workflow_lane": "export",
                    "enabled_modes": ["local-auth"],
                    "preserve_case_name": True,
                    "run_enrich_and_score": True,
                    "case_payload": {
                        "name": "Yorktown Systems Group",
                        "profile": "trade_compliance",
                        "export_authorization": {"destination_country": "AE"},
                    },
                    "expected_oci": {
                        "descriptor_only": True,
                        "owner_class": "Service-Disabled Veteran",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    specs = module.load_specs(str(spec_file))

    assert len(specs) == 1
    assert specs[0]["flow_name"] == "export_trade"
    assert specs[0]["expected_workflow_lane"] == "export"
    assert specs[0]["enabled_modes"] == ["local-auth"]
    assert specs[0]["preserve_case_name"] is True
    assert specs[0]["run_enrich_and_score"] is True
    assert specs[0]["case_payload"]["profile"] == "trade_compliance"
    assert specs[0]["case_payload"]["name"] == "Yorktown Systems Group"
    assert specs[0]["case_payload"]["export_authorization"]["destination_country"] == "AE"
    assert specs[0]["compare_payload"]["name"] == "Boeing"
    assert specs[0]["expected_oci"]["owner_class"] == "Service-Disabled Veteran"


def test_step_supplier_passport_validates_expected_oci():
    class FakeClient(module.BaseClient):
        def request_json(self, method, path, payload=None, timeout=60):
            return 200, {}, {
                "case_id": "c-123",
                "passport_version": "supplier-passport-v1",
                "posture": "review",
                "ownership": {
                    "oci": {
                        "named_beneficial_owner_known": False,
                        "owner_class_known": True,
                        "owner_class": "Service-Disabled Veteran",
                        "descriptor_only": True,
                        "ownership_gap": "descriptor_only_owner_class",
                        "ownership_resolution_pct": 0.55,
                        "control_resolution_pct": 0.35,
                        "owner_class_evidence": [{"source": "public_html_ownership"}],
                    }
                },
            }

        def request_bytes(self, method, path, payload=None, headers=None, timeout=60):
            raise AssertionError("unused")

        def request_json_unauthenticated(self, method, path, payload=None, timeout=60):
            raise AssertionError("unused")

        def request_bytes_unauthenticated(self, method, path, payload=None, headers=None, timeout=60):
            raise AssertionError("unused")

    details = module._step_supplier_passport(
        FakeClient(),
        "c-123",
        expected_oci={
            "named_beneficial_owner_known": False,
            "owner_class_known": True,
            "owner_class": "Service-Disabled Veteran",
            "descriptor_only": True,
            "ownership_gap": "descriptor_only_owner_class",
            "min_ownership_resolution_pct": 0.5,
            "min_control_resolution_pct": 0.3,
            "require_owner_class_evidence": True,
        },
    )

    assert details["oci_required"] is True
    assert details["oci_passed"] is True
    assert details["oci"]["descriptor_only"] is True
    assert details["oci"]["owner_class_evidence_count"] == 1


def test_main_fixture_mode_prints_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(module, "parse_args", lambda: module.argparse.Namespace(
        mode="fixture",
        base_url="http://127.0.0.1:8080",
        email="",
        password="",
        token="",
        spec_file="",
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
