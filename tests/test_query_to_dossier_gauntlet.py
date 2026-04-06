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
    graph_step = next(step for step in result["steps"] if step["step"] == "graph")
    assert graph_step["details"]["root_entity_id"]
    pdf_step = next(step for step in result["steps"] if step["step"] == "dossier_pdf")
    assert pdf_step["details"]["content_disposition"].startswith("attachment; filename=dossier-")


def test_render_markdown_includes_flow_table():
    summary = {
        "generated_at": "2026-03-29T12:00:00Z",
        "mode": "fixture",
        "overall_verdict": "PASS",
        "graph_summary": {
            "required_flows": 1,
            "passed_flows": 1,
            "thin_graph_flows": 0,
            "flows_with_missing_required_edge_families": 0,
        },
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
    assert "- Graph required flows: `1`" in markdown
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
                    "expected_graph": {
                        "require_edge_families": ["ownership_control"],
                        "max_missing_required_edge_families": 0,
                        "min_claim_coverage_pct": 0.5,
                    },
                    "expected_tribunal_view": "watch",
                    "expected_assistant_view": "watch",
                    "expected_assistant_anomalies": [
                        "descriptor_only_ownership",
                        "named_owner_unresolved",
                    ],
                    "expected_dossier_fragments": [
                        "Descriptor-only ownership evidence",
                        "Owner class: Service-Disabled Veteran",
                    ],
                    "forbidden_dossier_fragments": [
                        "Invalid Date",
                        "Traceback",
                    ],
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
    assert specs[0]["expected_graph"]["require_edge_families"] == ["ownership_control"]
    assert specs[0]["expected_graph"]["max_missing_required_edge_families"] == 0
    assert specs[0]["expected_tribunal_view"] == "watch"
    assert specs[0]["expected_assistant_view"] == "watch"
    assert specs[0]["expected_assistant_anomalies"] == ["descriptor_only_ownership", "named_owner_unresolved"]
    assert specs[0]["expected_dossier_fragments"][0] == "Descriptor-only ownership evidence"
    assert specs[0]["forbidden_dossier_fragments"] == ["Invalid Date", "Traceback"]


def test_step_supplier_passport_validates_expected_oci():
    class FakeClient(module.BaseClient):
        def request_json(self, method, path, payload=None, timeout=60):
            return 200, {}, {
                "case_id": "c-123",
                "passport_version": "supplier-passport-v1",
                "posture": "review",
                "graph": {
                    "relationship_count": 3,
                    "network_relationship_count": 2,
                    "control_paths": [{"path": ["company", "person"]}],
                    "intelligence": {
                        "edge_family_counts": {
                            "ownership_control": 2,
                            "trade_and_logistics": 1,
                        },
                        "missing_required_edge_families": [],
                        "claim_coverage_pct": 0.67,
                        "legacy_unscoped_edge_count": 0,
                        "stale_edge_count": 0,
                        "thin_graph": False,
                    },
                },
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
                "workflow_lane": "counterparty",
                "tribunal": {
                    "recommended_view": "watch",
                    "consensus_level": "moderate",
                    "decision_gap": 0.14,
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
        expected_graph={
            "min_relationship_count": 3,
            "min_network_relationship_count": 2,
            "min_control_paths": 1,
            "require_edge_families": ["ownership_control"],
            "max_missing_required_edge_families": 0,
            "max_legacy_unscoped_edges": 0,
            "max_stale_edges": 0,
            "min_claim_coverage_pct": 0.5,
            "forbid_thin_graph": True,
        },
        expected_tribunal_view="watch",
    )

    assert details["oci_required"] is True
    assert details["oci_passed"] is True
    assert details["graph_required"] is True
    assert details["graph_passed"] is True
    assert details["oci"]["descriptor_only"] is True
    assert details["oci"]["owner_class_evidence_count"] == 1
    assert details["graph"]["control_path_count"] == 1
    assert details["graph"]["thin_graph"] is False
    assert details["tribunal_recommended_view"] == "watch"


def test_build_graph_summary_tracks_required_and_missing_family_flows():
    summary = module.build_graph_summary(
        [
            {
                "flow_name": "counterparty",
                "graph_required": True,
                "graph_passed": True,
                "graph_details": {
                    "thin_graph": False,
                    "missing_required_edge_families": [],
                },
            },
            {
                "flow_name": "cyber",
                "graph_required": True,
                "graph_passed": False,
                "graph_details": {
                    "thin_graph": True,
                    "missing_required_edge_families": ["cyber_supply_chain"],
                },
            },
            {
                "flow_name": "export",
                "graph_required": False,
            },
        ]
    )

    assert summary["required_flows"] == 2
    assert summary["passed_flows"] == 1
    assert summary["thin_graph_flows"] == 1
    assert summary["flows_with_missing_required_edge_families"] == 1
    assert summary["failed_flows"] == ["cyber"]


def test_step_assistant_plan_validates_expected_view_and_anomalies():
    class FakeClient(module.BaseClient):
        def request_json(self, method, path, payload=None, timeout=60):
            return 200, {}, {
                "case_id": "c-123",
                "version": "ai-control-plane-v1",
                "recommended_view": "watch",
                "anomalies": [
                    {"code": "descriptor_only_ownership"},
                    {"code": "named_owner_unresolved"},
                    {"code": "thin_control_resolution"},
                ],
                "plan": [{"tool_id": "supplier_passport"}],
            }

        def request_bytes(self, method, path, payload=None, headers=None, timeout=60):
            raise AssertionError("unused")

        def request_json_unauthenticated(self, method, path, payload=None, timeout=60):
            raise AssertionError("unused")

        def request_bytes_unauthenticated(self, method, path, payload=None, headers=None, timeout=60):
            raise AssertionError("unused")

    body = module._step_assistant_plan(
        FakeClient(),
        "c-123",
        "Trace the control path.",
        expected_view="watch",
        expected_anomaly_codes=["descriptor_only_ownership", "named_owner_unresolved"],
    )

    assert body["recommended_view"] == "watch"


def test_step_dossier_html_validates_expected_and_forbidden_fragments():
    class FakeClient(module.BaseClient):
        def request_json(self, method, path, payload=None, timeout=60):
            assert path == "/api/cases/c-123/dossier"
            return 200, {}, {
                "case_id": "c-123",
                "download_url": "/api/dossiers/dossier-c-123.html",
            }

        def request_bytes(self, method, path, payload=None, headers=None, timeout=60):
            assert path == "/api/dossiers/dossier-c-123.html"
            html = """
            <html>
              <body>
                <h1>Helios Intelligence Brief</h1>
                <h2>Axiom Assessment</h2>
                <h1>Supplier Passport</h1>
                <h2>Risk Storyline</h2>
                <h2>Graph Read</h2>
                <h2>Recommended Actions</h2>
                <h2>Evidence Ledger</h2>
                <p>Descriptor-only ownership evidence. No named beneficial owner resolved.</p>
                <p>Owner class: Service-Disabled Veteran.</p>
              </body>
            </html>
            """
            return 200, {"Content-Type": "text/html; charset=utf-8"}, html.encode("utf-8")

        def request_json_unauthenticated(self, method, path, payload=None, timeout=60):
            raise AssertionError("unused")

        def request_bytes_unauthenticated(self, method, path, payload=None, headers=None, timeout=60):
            raise AssertionError("unused")

    details = module._step_dossier_html(
        FakeClient(),
        "c-123",
        expected_fragments=[
            "Descriptor-only ownership evidence",
            "Owner class: Service-Disabled Veteran",
        ],
        forbidden_fragments=[
            "Invalid Date",
            "Traceback",
        ],
    )

    assert details["expected_fragments_checked"] == 2
    assert len(details["matched_expected_fragments"]) == 2
    assert details["forbidden_fragments_checked"] == 2
    assert "Descriptor-only ownership evidence" in details["expected_fragment_contexts"]


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


def test_main_passes_with_skip_when_mode_has_no_eligible_flows(monkeypatch, tmp_path, capsys):
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
    monkeypatch.setattr(
        module,
        "load_specs",
        lambda _path: [
            {
                "flow_name": "local_only",
                "enabled_modes": ["local-auth"],
                "compare_payload": {},
                "case_payload": {},
                "assistant_prompt": "",
                "expected_workflow_lane": "",
                "expected_oci": {},
                "expected_graph": {},
                "expected_tribunal_view": "",
                "expected_assistant_view": "",
                "expected_assistant_anomalies": [],
                "preserve_case_name": False,
                "run_enrich_and_score": False,
                "expected_dossier_fragments": [],
                "forbidden_dossier_fragments": [],
            }
        ],
    )

    exit_code = module.main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["overall_verdict"] == "PASS"
    assert payload["flows"] == []
    assert payload["skipped_reason"] == "no eligible flows for mode fixture"


def test_run_query_to_dossier_flow_returns_failed_flow_with_step_context(monkeypatch):
    class DummyClient(module.BaseClient):
        def request_json(self, method, path, payload=None, timeout=60):
            raise AssertionError("unused")

        def request_bytes(self, method, path, payload=None, headers=None, timeout=60):
            raise AssertionError("unused")

        def request_json_unauthenticated(self, method, path, payload=None, timeout=60):
            raise AssertionError("unused")

        def request_bytes_unauthenticated(self, method, path, payload=None, headers=None, timeout=60):
            raise AssertionError("unused")

    monkeypatch.setattr(module, "_step_health", lambda client: {"ok": True})
    monkeypatch.setattr(module, "_step_ai_providers", lambda client: {"provider_count": 1})
    monkeypatch.setattr(module, "_step_compare", lambda client, payload: {"comparison_count": 2})
    monkeypatch.setattr(
        module,
        "_step_create_case",
        lambda client, flow_name, case_payload, preserve_case_name=False: {
            "case_id": "c-123",
            "vendor_name": "Failure Fixture",
        },
    )
    monkeypatch.setattr(module, "_step_case_detail", lambda client, case_id, expected_workflow_lane="": {"workflow_lane": "counterparty"})

    def _timeout_graph(client, case_id):
        raise TimeoutError("timed out")

    monkeypatch.setattr(module, "_step_graph", _timeout_graph)

    result = module.run_query_to_dossier_flow(
        DummyClient(),
        {
            "flow_name": "timed_flow",
            "compare_payload": {},
            "case_payload": {},
            "assistant_prompt": "Trace the path",
            "expected_workflow_lane": "",
            "expected_oci": {},
            "expected_graph": {},
            "expected_tribunal_view": "",
            "expected_assistant_view": "",
            "expected_assistant_anomalies": [],
            "enabled_modes": ["fixture"],
            "preserve_case_name": False,
            "run_enrich_and_score": False,
            "expected_dossier_fragments": [],
            "forbidden_dossier_fragments": [],
        },
    )

    assert result["flow_verdict"] == "FAIL"
    assert result["case_id"] == "c-123"
    assert result["vendor_name"] == "Failure Fixture"
    assert result["failed_step"] == "graph"
    assert result["error"] == "timed out"
    assert result["steps"][-1]["step"] == "graph"
    assert result["steps"][-1]["status"] == "FAIL"


def test_main_fails_when_any_flow_record_fails(monkeypatch, tmp_path, capsys):
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
    monkeypatch.setattr(
        module,
        "run_fixture_flows",
        lambda specs=None: [
            {
                "flow_name": "broken",
                "flow_verdict": "FAIL",
                "case_id": "c-999",
                "vendor_name": "Broken Vendor",
                "steps": [{"step": "graph", "status": "FAIL", "duration_ms": 10, "details": {"error": "timed out"}}],
                "total_ms": 10,
                "warning_count": 0,
                "warnings": [],
                "oci_required": False,
                "oci_passed": False,
                "graph_required": False,
                "graph_passed": False,
            }
        ],
    )

    exit_code = module.main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["overall_verdict"] == "FAIL"
    assert payload["flows"][0]["flow_name"] == "fixture:broken"
