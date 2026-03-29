import importlib
import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from ai_control_plane import (  # type: ignore  # noqa: E402
    build_case_assistant_plan,
    infer_objective,
    prepare_case_assistant_execution,
    prepare_case_assistant_feedback,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        server = importlib.import_module("server")

    server.db.init_db()
    server.init_auth_db()
    with server.app.test_client() as test_client:
        yield test_client


def _create_case(client, name="Control Plane Vendor", country="US", extra_payload=None):
    payload = {
        "name": name,
        "country": country,
        "program": "dod_unclassified",
        "profile": "defense_acquisition",
        "ownership": {"beneficial_owner_known": False, "shell_layers": 2},
        "data_quality": {"has_lei": False, "has_cage": True, "has_duns": False, "years_of_records": 3},
    }
    if extra_payload:
        payload.update(extra_payload)
    response = client.post(
        "/api/cases",
        json=payload,
    )
    assert response.status_code == 201
    return response.get_json()["case_id"]


def test_infer_objective_routes_control_and_identity_prompts():
    assert infer_objective("Trace the control path to a hidden PLA owner") == "trace_control_path"
    assert infer_objective("Check why the UEI and LEI look wrong here") == "data_repair"
    assert infer_objective("Review the export license posture and explain any ambiguity") == "export_review"


def test_build_case_assistant_plan_flags_missing_identifiers_and_thin_graph():
    plan = build_case_assistant_plan(
        case_id="c-123",
        analyst_prompt="Why does this result look wrong?",
        vendor={"name": "Vendor A"},
        supplier_passport={
            "posture": "review",
            "tribunal": {"recommended_view": "watch", "consensus_level": "moderate"},
            "identity": {
                "identifiers": {"cage": "1ABC2", "uei": "", "lei": ""},
                "connectors_with_data": 2,
                "official_corroboration": {"coverage_level": "public_only", "blocked_connector_count": 1},
            },
            "cyber": {
                "open_source_risk_level": "high",
                "open_source_advisory_count": 4,
                "scorecard_low_repo_count": 2,
            },
            "threat_intel": {
                "threat_pressure": "high",
                "attack_technique_ids": ["T1190", "T1078", "T1090", "T1583"],
                "cisa_advisory_ids": ["AA24-057A", "AA22-047A"],
            },
            "graph": {
                "relationship_count": 1,
                "control_paths": [],
                "claim_health": {"contradicted_claims": 1, "stale_paths": 1},
            },
        },
    )

    assert plan["objective"] == "data_repair"
    anomaly_codes = {item["code"] for item in plan["anomalies"]}
    assert "missing_core_identifiers" in anomaly_codes
    assert "thin_graph" in anomaly_codes
    assert "official_corroboration_thin" in anomaly_codes
    assert "official_connector_blocked" in anomaly_codes
    assert "high_threat_pressure" in anomaly_codes
    assert "open_source_pressure" in anomaly_codes
    assert any(step["tool_id"] == "identity_repair" for step in plan["plan"])


def test_assistant_plan_route_returns_typed_plan(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client)
    server.db.save_score(
        case_id,
        {
            "composite_score": 19,
            "is_hard_stop": False,
            "calibrated": {"calibrated_tier": "TIER_3_REVIEW"},
        },
    )
    server.db.save_enrichment(
        case_id,
        {
            "summary": {"findings_total": 3, "connectors_with_data": 2},
            "identifiers": {"cage": "1ABC2"},
        },
    )
    monkeypatch.setattr(
        server,
        "build_supplier_passport",
        lambda _case_id: {
            "posture": "review",
            "tribunal": {"recommended_view": "watch", "consensus_level": "moderate"},
            "network_risk": {"score": 1.2, "level": "medium"},
            "identity": {"identifiers": {"cage": "1ABC2"}, "connectors_with_data": 2},
            "graph": {
                "relationship_count": 1,
                "control_paths": [],
                "claim_health": {"contradicted_claims": 0, "stale_paths": 0},
            },
        },
    )

    response = client.post(
        f"/api/cases/{case_id}/assistant-plan",
        json={"prompt": "Trace the control path and explain why this vendor is risky"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["version"] == "ai-control-plane-v1"
    assert body["objective"] == "trace_control_path"
    assert body["recommended_view"] == "watch"
    assert any(step["tool_id"] == "supplier_passport" for step in body["plan"])


def test_prepare_case_assistant_execution_blocks_unplanned_or_unsafe_tools():
    executable, blocked = prepare_case_assistant_execution(
        [
            {"tool_id": "case_snapshot"},
            {"tool_id": "supplier_passport"},
            {"tool_id": "dossier"},
        ],
        ["case_snapshot", "dossier", "ghost_tool"],
    )

    assert executable == ["case_snapshot"]
    blocked_ids = {item["tool_id"] for item in blocked}
    assert blocked_ids == {"dossier", "ghost_tool"}


def test_prepare_case_assistant_feedback_turns_tool_gap_into_training_signal():
    payload = prepare_case_assistant_feedback(
        prompt="Trace the control path to the supplier owner",
        objective="trace_control_path",
        verdict="rejected",
        feedback_type="tool_missing",
        comment="It needed graph_probe and enrichment findings to be trustworthy",
        approved_tool_ids=["case_snapshot", "supplier_passport"],
        executed_tool_ids=["case_snapshot"],
        suggested_tool_ids=["graph_probe", "enrichment_findings"],
        anomaly_codes=["thin_graph"],
    )

    assert payload["category"] == "request"
    assert payload["severity"] == "high"
    assert payload["training_signal"]["feedback_type"] == "tool_missing"
    assert payload["training_signal"]["suggested_tool_ids"] == ["graph_probe", "enrichment_findings"]


def test_assistant_execute_route_runs_approved_safe_tools(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Execution Vendor")
    server.db.save_score(
        case_id,
        {
            "composite_score": 41,
            "is_hard_stop": False,
            "calibrated": {"calibrated_tier": "TIER_3_REVIEW"},
        },
    )
    server.db.save_enrichment(
        case_id,
        {
            "summary": {"findings_total": 4, "connectors_with_data": 3},
            "identifiers": {"cage": "1ABC2", "uei": "uei-123"},
        },
    )
    monkeypatch.setattr(
        server,
        "build_supplier_passport",
        lambda _case_id: {
            "case_id": _case_id,
            "posture": "review",
            "tribunal": {"recommended_view": "watch", "consensus_level": "moderate"},
            "network_risk": {"score": 1.2, "level": "medium"},
            "identity": {"identifiers": {"cage": "1ABC2", "uei": "uei-123"}, "connectors_with_data": 3},
            "graph": {
                "entity_count": 3,
                "relationship_count": 4,
                "control_paths": [{"rel_type": "owned_by", "confidence": 0.88}],
                "claim_health": {"contradicted_claims": 0, "stale_paths": 0},
            },
        },
    )

    response = client.post(
        f"/api/cases/{case_id}/assistant-execute",
        json={
            "prompt": "Trace the control path and explain why this vendor is risky",
            "approved_tool_ids": ["case_snapshot", "supplier_passport", "dossier"],
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["version"] == "ai-control-plane-execution-v1"
    assert [step["tool_id"] for step in body["executed_steps"]] == ["case_snapshot", "supplier_passport"]
    assert {item["tool_id"] for item in body["blocked_tools"]} == {"dossier"}


def test_assistant_execute_route_returns_hybrid_assurance_review(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Assurance Execution Vendor")
    server.db.save_score(
        case_id,
        {
            "composite_score": 27,
            "is_hard_stop": False,
            "calibrated": {"calibrated_tier": "TIER_3_REVIEW"},
        },
    )
    server.db.save_enrichment(
        case_id,
        {
            "summary": {"findings_total": 5, "connectors_with_data": 3},
            "identifiers": {"cage": "1ABC2"},
        },
    )
    monkeypatch.setattr(
        server,
        "build_supplier_passport",
        lambda _case_id: {
            "case_id": _case_id,
            "vendor": {"name": "Assurance Execution Vendor"},
            "posture": "review",
            "tribunal": {"recommended_view": "watch", "consensus_level": "moderate"},
            "network_risk": {"score": 1.1, "level": "medium", "high_risk_neighbors": 1},
            "identity": {"identifiers": {"cage": "1ABC2"}, "connectors_with_data": 3},
            "graph": {
                "entity_count": 2,
                "relationship_count": 2,
                "control_paths": [{"rel_type": "depends_on", "confidence": 0.74}],
                "claim_health": {"contradicted_claims": 0, "stale_paths": 0},
            },
        },
    )
    monkeypatch.setattr(
        server,
        "get_latest_cyber_evidence_summary",
        lambda _case_id: {
            "sprs_artifact_id": "artifact:sprs",
            "oscal_artifact_id": "artifact:oscal",
            "nvd_artifact_id": "artifact:nvd",
            "current_cmmc_level": 2,
            "assessment_status": "passed",
            "poam_active": False,
            "open_poam_items": 0,
            "total_control_references": 90,
            "high_or_critical_cve_count": 1,
            "critical_cve_count": 0,
            "kev_flagged_cve_count": 0,
            "product_terms": ["satcom firmware"],
            "artifact_sources": ["sprs_import", "oscal_upload", "nvd_overlay"],
            "threat_pressure": "high",
            "attack_technique_ids": ["T1190", "T1078", "T1090", "T1583"],
            "attack_actor_families": ["APT29"],
            "cisa_advisory_ids": ["AA24-057A", "AA22-047A"],
            "threat_sectors": ["defense industrial base"],
            "threat_intel_sources": ["mitre_attack_fixture", "cisa_advisory_fixture"],
            "open_source_risk_level": "medium",
            "open_source_advisory_count": 3,
            "scorecard_low_repo_count": 1,
        },
    )

    response = client.post(
        f"/api/cases/{case_id}/assistant-execute",
        json={
            "prompt": "Review the cyber evidence and supply chain assurance posture.",
            "approved_tool_ids": ["cyber_evidence"],
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert [step["tool_id"] for step in body["executed_steps"]] == ["cyber_evidence"]
    result = body["executed_steps"][0]["result"]
    assert result["hybrid_review"]["version"] == "assurance-hybrid-review-v1"
    assert result["hybrid_review"]["deterministic_posture"] in {"qualified", "review", "blocked", "ready"}
    assert isinstance(result["hybrid_review"]["ambiguity_flags"], list)
    assert result["hybrid_review"]["threat_pressure"] == "high"
    assert result["hybrid_review"]["cisa_advisory_ids"] == ["AA24-057A", "AA22-047A"]
    assert result["hybrid_review"]["open_source_advisory_count"] == 3


def test_assistant_execute_route_returns_hybrid_export_review(client):
    case_id = _create_case(
        client,
        name="Export Control Plane Vendor",
        extra_payload={
            "export_authorization": {
                "request_type": "item_transfer",
                "recipient_name": "Northern Channel Partners",
                "destination_country": "CA",
                "jurisdiction_guess": "ear",
                "classification_guess": "EAR99",
                "item_or_data_summary": "Commercial edge compute gateway",
                "end_use_summary": "Evaluation support for maritime analytics customer",
                "access_context": "Reseller staging before onward delivery",
                "notes": "Channel partner will ship onward to final customer in another jurisdiction",
            }
        },
    )

    response = client.post(
        f"/api/cases/{case_id}/assistant-execute",
        json={
            "prompt": "Review the export license posture and explain any ambiguity.",
            "approved_tool_ids": ["export_guidance"],
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert [step["tool_id"] for step in body["executed_steps"]] == ["export_guidance"]
    result = body["executed_steps"][0]["result"]
    assert result["hybrid_review"]["version"] == "export-hybrid-review-v1"
    assert result["hybrid_review"]["deterministic_posture"] == "likely_nlr"
    assert result["hybrid_review"]["final_posture"] == "escalate"
    assert result["hybrid_review"]["disagrees_with_deterministic"] is True


def test_assistant_feedback_route_captures_structured_training_signal(client):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Feedback Vendor")

    response = client.post(
        f"/api/cases/{case_id}/assistant-feedback",
        json={
            "prompt": "Trace the control path and explain why this vendor is risky",
            "objective": "trace_control_path",
            "verdict": "rejected",
            "feedback_type": "tool_missing",
            "comment": "The plan needed graph_probe before I would trust it.",
            "approved_tool_ids": ["case_snapshot", "supplier_passport"],
            "executed_tool_ids": ["case_snapshot"],
            "suggested_tool_ids": ["graph_probe"],
            "anomaly_codes": ["thin_graph"],
        },
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["training_signal"]["feedback_type"] == "tool_missing"
    feedback = server.db.list_beta_feedback(limit=5)
    assert feedback[0]["screen"] == "assistant_control_plane"
    assert feedback[0]["metadata"]["suggested_tool_ids"] == ["graph_probe"]
