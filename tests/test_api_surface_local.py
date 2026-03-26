import importlib
import io
import os
import sys
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        import server  # type: ignore

        server = sys.modules["server"]

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    import hardening

    hardening.reset_rate_limiter()

    with server.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-auth-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "true")
    monkeypatch.delenv("XIPHOS_DEV_MODE", raising=False)
    monkeypatch.setenv("XIPHOS_SECRET_KEY", "test-secret-key")

    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        import server  # type: ignore

        server = sys.modules["server"]

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    import hardening
    import auth as auth_module

    hardening.reset_rate_limiter()
    auth_module.create_user("analyst@example.com", "AnalystPass123!", name="Analyst", role="analyst")

    with server.app.test_client() as test_client:
        login = test_client.post(
            "/api/auth/login",
            json={"email": "analyst@example.com", "password": "AnalystPass123!"},
        )
        assert login.status_code == 200
        token = login.get_json()["token"]
        yield {
            "client": test_client,
            "server": server,
            "headers": {"Authorization": f"Bearer {token}"},
        }


def _create_case(client, name="Acme Corp", country="US", headers=None, extra_payload=None):
    payload = {
        "name": name,
        "country": country,
        "ownership": {
            "publicly_traded": True,
            "state_owned": False,
            "beneficial_owner_known": True,
            "ownership_pct_resolved": 0.9,
            "shell_layers": 0,
            "pep_connection": False,
        },
        "data_quality": {
            "has_lei": True,
            "has_cage": True,
            "has_duns": True,
            "has_tax_id": True,
            "has_audited_financials": True,
            "years_of_records": 10,
        },
        "exec": {
            "known_execs": 5,
            "adverse_media": 0,
            "pep_execs": 0,
            "litigation_history": 0,
        },
        "program": "dod_unclassified",
        "profile": "defense_acquisition",
    }
    if extra_payload:
        payload.update(extra_payload)

    resp = client.post(
        "/api/cases",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.get_json()["case_id"]


def test_compare_profiles_route_returns_comparisons(client):
    resp = client.post(
        "/api/compare",
        json={
            "name": "Boeing",
            "country": "US",
            "profiles": ["defense_acquisition", "commercial_supply_chain"],
        },
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["entity"]["name"] == "Boeing"
    assert len(body["comparisons"]) == 2
    assert all("tier" in comparison for comparison in body["comparisons"])


def test_decision_routes_match_frontend_contract(client):
    case_id = _create_case(client, name="Decision Test Vendor")

    create_resp = client.post(
        f"/api/cases/{case_id}/decision",
        json={"decision": "approve", "reason": "Low risk and complete documentation"},
    )
    assert create_resp.status_code == 201
    created = create_resp.get_json()
    assert created["vendor_id"] == case_id
    assert created["decision_id"] > 0
    assert created["decision"] == "approve"

    list_resp = client.get(f"/api/cases/{case_id}/decisions?limit=5")
    assert list_resp.status_code == 200
    payload = list_resp.get_json()
    assert payload["vendor_id"] == case_id
    assert payload["latest_decision"]["decision"] == "approve"
    assert len(payload["decisions"]) == 1


def test_case_detail_route_includes_storyline_payload(client):
    case_id = _create_case(client, name="Storyline API Vendor")

    resp = client.get(f"/api/cases/{case_id}")
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["id"] == case_id
    assert body["storyline"]["version"] == "risk-storyline-v1"
    assert len(body["storyline"]["cards"]) >= 2
    assert any(card["type"] == "action" for card in body["storyline"]["cards"])


def test_graph_runtime_reports_active_database_paths(client, tmp_path):
    response = client.get("/api/graph/runtime")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data_dir"]["path"] == str((tmp_path / "data").resolve())
    assert payload["main_db"]["path"] == str((tmp_path / "xiphos-test.db").resolve())
    assert payload["kg_db"]["path"] == str((tmp_path / "knowledge-graph.db").resolve())
    assert payload["kg_db"]["tables"]["kg_entities"] == 0


def test_portfolio_snapshot_handles_mixed_alert_timestamp_types(client, monkeypatch):
    server = sys.modules["server"]
    recent_dt = datetime.utcnow() - timedelta(days=1)
    stale_str = (datetime.utcnow() - timedelta(days=20)).isoformat()

    monkeypatch.setattr(
        server.db,
        "list_alerts",
        lambda limit=500, unresolved_only=True: [
            {"created_at": recent_dt},
            {"created_at": stale_str},
        ],
    )

    response = client.get("/api/portfolio/snapshot")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["anomaly_count"] == 1


def test_dossier_pdf_handles_datetime_decision_timestamps(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Datetime PDF Vendor")

    decision_response = client.post(
        f"/api/cases/{case_id}/decision",
        json={"decision": "approve", "reason": "datetime regression"},
    )
    assert decision_response.status_code == 201

    original_get_decisions = server.db.get_decisions

    def _get_decisions_with_datetime(vendor_id, limit=10):
        decisions = original_get_decisions(vendor_id, limit=limit)
        if decisions:
            decisions[0]["created_at"] = datetime.utcnow()
        return decisions

    monkeypatch.setattr(server.db, "get_decisions", _get_decisions_with_datetime)

    response = client.post(f"/api/cases/{case_id}/dossier-pdf", json={})

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/pdf")


def test_server_entrypoint_is_after_last_route_definition():
    server_path = os.path.join(BACKEND_DIR, "server.py")
    source = open(server_path, "r", encoding="utf-8").read().splitlines()

    entrypoint_line = next(
        index for index, line in enumerate(source, 1) if line.strip() == 'if __name__ == "__main__":'
    )
    last_route_line = max(
        index for index, line in enumerate(source, 1) if line.lstrip().startswith("@app.route(")
    )

    assert entrypoint_line > last_route_line


def test_graph_ingest_persons_route_replays_case_screenings(client):
    import person_screening as ps  # type: ignore

    case_id = _create_case(client, name="Retroactive Person Graph Vendor")
    ps.init_person_screening_db()
    ps.screen_person(
        name="Jane Retro",
        nationalities=["GB"],
        employer="Acme Systems",
        item_classification="USML-Aircraft",
        case_id=case_id,
        screened_by="test-suite",
    )

    response = client.post(f"/api/graph/ingest-persons/{case_id}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["case_id"] == case_id
    assert payload["persons_ingested"] == 1
    assert payload["relationships_created"] >= 3
    assert payload["details"][0]["person_name"] == "Jane Retro"

    graph_response = client.get(f"/api/cases/{case_id}/graph?depth=1")
    assert graph_response.status_code == 200
    graph = graph_response.get_json()
    names = {entity["canonical_name"] for entity in graph["entities"]}
    assert "Jane Retro" in names
    assert "Acme Systems" in names


def test_authenticated_case_creation_supports_batch_training_runs(auth_client):
    client = auth_client["client"]
    headers = auth_client["headers"]

    created_ids = []
    for index in range(55):
        created_ids.append(
            _create_case(
                client,
                name=f"Batch Training Vendor {index:02d}",
                headers=headers,
            )
        )

    assert len(created_ids) == 55
    assert len(set(created_ids)) == 55


def test_case_detail_route_exposes_workflow_control_summary(client):
    case_id = _create_case(
        client,
        name="Export Control Summary Vendor",
        country="DE",
        extra_payload={
            "program": "dual_use_ear",
            "profile": "itar_trade_compliance",
            "export_authorization": {
                "request_type": "technical_data_release",
                "recipient_name": "Export Control Summary Vendor",
                "destination_country": "DE",
                "jurisdiction_guess": "ear",
                "classification_guess": "3A001",
                "item_or_data_summary": "Controlled avionics interface drawings",
                "end_use_summary": "Integration review",
            },
        },
    )

    resp = client.get(f"/api/cases/{case_id}")
    assert resp.status_code == 200

    body = resp.get_json()
    control = body["workflow_control_summary"]
    assert control["lane"] == "export"
    assert control["support_level"] == "triage_only"
    assert control["action_owner"] == "Trade compliance / export counsel"
    assert "government approval" in control["decision_boundary"]
    assert any("Customer export artifact" in item for item in control["missing_inputs"])


def test_case_list_route_exposes_explicit_workflow_lane(client):
    default_case_id = _create_case(client, name="Counterparty Lane Vendor")
    export_case_id = _create_case(
        client,
        name="Export Lane Vendor",
        country="DE",
        extra_payload={
            "program": "dual_use_ear",
            "profile": "itar_trade_compliance",
            "export_authorization": {
                "request_type": "technical_data_release",
                "recipient_name": "Export Lane Vendor",
                "destination_country": "DE",
                "jurisdiction_guess": "ear",
                "classification_guess": "3A001",
                "item_or_data_summary": "Guidance software build and interface drawings",
                "end_use_summary": "Dual-use avionics support",
            },
        },
    )

    resp = client.get("/api/cases")
    assert resp.status_code == 200

    cases = {case["id"]: case for case in resp.get_json()["cases"]}
    assert cases[default_case_id]["workflow_lane"] == "counterparty"
    assert cases[export_case_id]["workflow_lane"] == "export"


def test_beta_feedback_and_summary_routes_capture_signal(client):
    case_id = _create_case(client, name="Beta Ops Vendor")

    feedback_resp = client.post(
        "/api/beta/feedback",
        json={
            "summary": "Cyber upload copy is unclear",
            "details": "The upload step needs a clearer next action after the file is accepted.",
            "category": "confusion",
            "severity": "medium",
            "workflow_lane": "cyber",
            "screen": "case",
            "case_id": case_id,
            "metadata": {"shell_lane": "cyber"},
        },
    )
    assert feedback_resp.status_code == 201
    feedback_id = feedback_resp.get_json()["feedback_id"]
    assert feedback_id > 0

    event_resp = client.post(
        "/api/beta/events",
        json={
            "event_name": "screen_viewed",
            "workflow_lane": "cyber",
            "screen": "case",
            "case_id": case_id,
            "metadata": {"shell_lane": "cyber"},
        },
    )
    assert event_resp.status_code == 201

    list_resp = client.get("/api/beta/feedback?limit=10")
    assert list_resp.status_code == 200
    feedback = list_resp.get_json()["feedback"]
    assert len(feedback) == 1
    assert feedback[0]["summary"] == "Cyber upload copy is unclear"
    assert feedback[0]["workflow_lane"] == "cyber"

    summary_resp = client.get("/api/beta/ops/summary?hours=24")
    assert summary_resp.status_code == 200
    summary = summary_resp.get_json()
    assert summary["open_feedback_count"] == 1
    assert summary["feedback_last_24h"] == 1
    assert summary["recent_event_count"] == 1
    assert any(item["workflow_lane"] == "cyber" for item in summary["feedback_by_lane"])
    assert any(item["event_name"] == "screen_viewed" for item in summary["event_counts"])


def test_beta_ops_summary_requires_auditor_or_admin(auth_client):
    client = auth_client["client"]
    headers = auth_client["headers"]

    feedback_resp = client.post(
        "/api/beta/feedback",
        headers=headers,
        json={
            "summary": "Need clearer export CTA",
            "category": "request",
            "severity": "low",
            "workflow_lane": "export",
            "screen": "helios",
        },
    )
    assert feedback_resp.status_code == 201

    summary_resp = client.get("/api/beta/ops/summary?hours=24", headers=headers)
    assert summary_resp.status_code == 403


def test_case_detail_route_includes_export_authorization_context(client):
    case_id = _create_case(
        client,
        name="Helios Export Recipient",
        country="DE",
        extra_payload={
            "program": "dual_use_ear",
            "profile": "itar_trade_compliance",
            "export_authorization": {
                "request_type": "technical_data_release",
                "recipient_name": "Helios Export Recipient",
                "destination_country": "DE",
                "jurisdiction_guess": "ear",
                "classification_guess": "3A001",
                "item_or_data_summary": "Radar processing source code and interface drawings",
                "end_use_summary": "Evaluation for dual-use avionics integration support",
                "foreign_person_nationalities": ["DE", "PL"],
            },
        },
    )

    resp = client.get(f"/api/cases/{case_id}")
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["profile"] == "itar_trade_compliance"
    assert body["export_authorization"]["request_type"] == "technical_data_release"
    assert body["export_authorization"]["destination_country"] == "DE"
    assert body["export_authorization"]["foreign_person_nationalities"] == ["DE", "PL"]
    assert body["export_authorization_guidance"]["source"] == "bis_rules_engine"
    assert body["export_authorization_guidance"]["posture"] in {
        "likely_nlr",
        "likely_license_required",
        "likely_exception_or_exemption",
        "insufficient_confidence",
        "escalate",
    }
    assert body["export_authorization_guidance"]["official_references"]
    assert body["export_evidence_summary"]["posture"] == body["export_authorization_guidance"]["posture"]
    assert "technical data release" in body["export_evidence_summary"]["narrative"].lower()
    assert "3a001" in body["export_evidence_summary"]["narrative"].lower()


def test_export_artifact_routes_store_and_return_customer_records(client):
    case_id = _create_case(client, name="Export Artifact Vendor")

    upload_resp = client.post(
        f"/api/cases/{case_id}/export-artifacts",
        data={
            "artifact_type": "export_classification_memo",
            "declared_classification": "3A001",
            "declared_jurisdiction": "ear",
            "notes": "Customer classification memo",
            "file": (io.BytesIO(b"ECCN 3A001 memo with CCATS history and foreign person review."), "classification.txt"),
        },
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201
    artifact = upload_resp.get_json()["artifact"]
    assert artifact["artifact_type"] == "export_classification_memo"
    assert artifact["source_system"] == "export_artifact_upload"
    assert "3A001" in artifact["structured_fields"]["detected_classifications"]

    list_resp = client.get(f"/api/cases/{case_id}/export-artifacts")
    assert list_resp.status_code == 200
    records = list_resp.get_json()["artifacts"]
    assert len(records) == 1
    assert records[0]["id"] == artifact["id"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    latest = case_resp.get_json()["latest_export_artifact"]
    assert latest["id"] == artifact["id"]
    assert case_resp.get_json()["export_evidence_summary"] is None

    download_resp = client.get(f"/api/cases/{case_id}/export-artifacts/{artifact['id']}")
    assert download_resp.status_code == 200
    assert download_resp.data.startswith(b"ECCN 3A001")


def test_export_evidence_influences_rescore_gate_outcome(client):
    case_id = _create_case(
        client,
        name="Export Review Vendor",
        country="US",
        extra_payload={
            "program": "cat_xi_electronics",
            "profile": "itar_trade_compliance",
            "export_authorization": {
                "request_type": "foreign_person_access",
                "recipient_name": "Export Review Vendor",
                "destination_country": "US",
                "jurisdiction_guess": "itar",
                "classification_guess": "Category XI",
                "item_or_data_summary": "ITAR technical data package and interface documentation",
                "end_use_summary": "Engineering support access for program sustainment",
                "access_context": "Foreign person access to controlled technical data without implemented TCP",
                "foreign_person_nationalities": ["IR"],
            },
        },
    )

    rescore_resp = client.post(f"/api/cases/{case_id}/score", json={})
    assert rescore_resp.status_code == 200
    calibrated = rescore_resp.get_json()["calibrated"]
    assert calibrated["regulatory_status"] == "NON_COMPLIANT"
    finding = next(
        item for item in calibrated["regulatory_findings"]
        if item["name"] == "Deemed Export Risk"
    )
    assert "High deemed export risk" in finding["explanation"]
    assert "IR" in finding["explanation"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    export_summary = case_resp.get_json()["export_evidence_summary"]
    assert export_summary["posture"] == "likely_prohibited"


def test_foci_artifact_routes_store_and_surface_latest_customer_records(client):
    case_id = _create_case(client, name="FOCI Artifact Vendor")

    upload_resp = client.post(
        f"/api/cases/{case_id}/foci-artifacts",
        data={
            "artifact_type": "foci_mitigation_instrument",
            "declared_foreign_owner": "Allied Parent Holdings",
            "declared_foreign_country": "GB",
            "declared_foreign_ownership_pct": "25%",
            "declared_mitigation_status": "MITIGATED",
            "declared_mitigation_type": "SSA",
            "file": (
                io.BytesIO(
                    b"Special Security Agreement covering 25% foreign ownership and board observer governance rights."
                ),
                "ssa-summary.txt",
            ),
        },
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201
    artifact = upload_resp.get_json()["artifact"]
    assert artifact["artifact_type"] == "foci_mitigation_instrument"
    assert artifact["source_system"] == "foci_artifact_upload"
    assert artifact["structured_fields"]["declared_foreign_owner"] == "Allied Parent Holdings"
    assert artifact["structured_fields"]["declared_mitigation_type"] == "SSA"
    assert artifact["structured_fields"]["max_ownership_percent_mention"] == 25.0

    list_resp = client.get(f"/api/cases/{case_id}/foci-artifacts")
    assert list_resp.status_code == 200
    records = list_resp.get_json()["artifacts"]
    assert len(records) == 1
    assert records[0]["id"] == artifact["id"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    latest = case_resp.get_json()["latest_foci_artifact"]
    assert latest["id"] == artifact["id"]
    assert latest["structured_fields"]["declared_foreign_country"] == "GB"

    download_resp = client.get(f"/api/cases/{case_id}/foci-artifacts/{artifact['id']}")
    assert download_resp.status_code == 200
    assert download_resp.data.startswith(b"Special Security Agreement")

    assert latest["structured_fields"]["declared_foreign_country"] == "GB"


def test_customer_foci_evidence_influences_rescore_gate_outcome(client):
    case_id = _create_case(client, name="FOCI Scoring Vendor")

    upload_resp = client.post(
        f"/api/cases/{case_id}/foci-artifacts",
        data={
            "artifact_type": "foci_ownership_chart",
            "declared_foreign_owner": "Allied Parent Holdings",
            "declared_foreign_country": "GB",
            "declared_foreign_ownership_pct": "25%",
            "file": (
                io.BytesIO(
                    b"Ownership chart showing 25% foreign ownership by Allied Parent Holdings in GB with board observer rights."
                ),
                "ownership-chart.txt",
            ),
        },
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201

    rescore_resp = client.post(f"/api/cases/{case_id}/score", json={})
    assert rescore_resp.status_code == 200
    calibrated = rescore_resp.get_json()["calibrated"]
    assert calibrated["regulatory_status"] == "REQUIRES_REVIEW"
    foci_finding = next(
        finding for finding in calibrated["regulatory_findings"]
        if finding["name"] == "FOCI"
    )
    assert "25%" in foci_finding["explanation"]
    assert "GB" in foci_finding["explanation"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    foci_summary = case_resp.get_json()["foci_evidence_summary"]
    assert foci_summary["foreign_owner"] == "Allied Parent Holdings"
    assert foci_summary["foreign_ownership_pct_display"] == "25%"


def test_sprs_import_routes_store_and_surface_latest_customer_records(client):
    case_id = _create_case(client, name="Cyber Trust Vendor")

    upload_resp = client.post(
        f"/api/cases/{case_id}/sprs-imports",
        data={
            "file": (
                io.BytesIO(
                    b"supplier_name,sprs_score,assessment_date,status,current_cmmc_level,poam\n"
                    b"Cyber Trust Vendor,103,2026-03-01,Conditional,2,Yes\n"
                ),
                "sprs-export.csv",
            ),
        },
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201
    artifact = upload_resp.get_json()["import"]
    assert artifact["artifact_type"] == "sprs_export"
    assert artifact["source_system"] == "sprs_import"
    assert artifact["structured_fields"]["summary"]["assessment_score"] == 103
    assert artifact["structured_fields"]["summary"]["current_cmmc_level"] == 2
    assert artifact["structured_fields"]["summary"]["poam_active"] is True

    list_resp = client.get(f"/api/cases/{case_id}/sprs-imports")
    assert list_resp.status_code == 200
    records = list_resp.get_json()["imports"]
    assert len(records) == 1
    assert records[0]["id"] == artifact["id"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    latest = case_resp.get_json()["latest_sprs_import"]
    assert latest["id"] == artifact["id"]
    assert latest["structured_fields"]["summary"]["matched_supplier_name"] == "Cyber Trust Vendor"

    download_resp = client.get(f"/api/cases/{case_id}/sprs-imports/{artifact['id']}")
    assert download_resp.status_code == 200
    assert download_resp.data.startswith(b"supplier_name,sprs_score")


def test_customer_cyber_evidence_influences_rescore_gate_outcome(client):
    case_id = _create_case(client, name="CMMC Review Vendor")

    upload_resp = client.post(
        f"/api/cases/{case_id}/sprs-imports",
        data={
            "file": (
                io.BytesIO(
                    b"supplier_name,sprs_score,assessment_date,status,current_cmmc_level,poam\n"
                    b"CMMC Review Vendor,82,2026-03-02,Conditional,1,Yes\n"
                ),
                "sprs-export.csv",
            ),
        },
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201

    rescore_resp = client.post(f"/api/cases/{case_id}/score", json={})
    assert rescore_resp.status_code == 200
    calibrated = rescore_resp.get_json()["calibrated"]
    assert calibrated["regulatory_status"] == "REQUIRES_REVIEW"
    cmmc_finding = next(
        finding for finding in calibrated["regulatory_findings"]
        if finding["name"] == "CMMC 2.0"
    )
    assert "Level 1" in cmmc_finding["explanation"]
    assert "Level 2" in cmmc_finding["explanation"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    cyber_summary = case_resp.get_json()["cyber_evidence_summary"]
    assert cyber_summary["current_cmmc_level"] == 1
    assert cyber_summary["poam_active"] is True


def test_oscal_artifact_routes_store_and_surface_latest_customer_records(client):
    case_id = _create_case(client, name="Cyber Plan Vendor")

    upload_resp = client.post(
        f"/api/cases/{case_id}/oscal-artifacts",
        data={
            "file": (
                io.BytesIO(
                    b'{"plan-of-action-and-milestones":{"metadata":{"title":"Supplier POA&M"},'
                    b'"system-characteristics":{"system-name":"Supplier Secure Environment"},'
                    b'"poam-items":[{"id":"poam-1","title":"Encrypt removable media","status":"open","due-date":"2026-04-15","control-id":"sc-28"}]}}'
                ),
                "poam.json",
            ),
        },
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201
    artifact = upload_resp.get_json()["artifact"]
    assert artifact["artifact_type"] == "oscal_poam"
    assert artifact["source_system"] == "oscal_upload"
    assert artifact["structured_fields"]["summary"]["open_poam_items"] == 1

    list_resp = client.get(f"/api/cases/{case_id}/oscal-artifacts")
    assert list_resp.status_code == 200
    records = list_resp.get_json()["artifacts"]
    assert len(records) == 1
    assert records[0]["id"] == artifact["id"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    latest = case_resp.get_json()["latest_oscal_artifact"]
    assert latest["id"] == artifact["id"]
    assert latest["structured_fields"]["summary"]["system_name"] == "Supplier Secure Environment"

    download_resp = client.get(f"/api/cases/{case_id}/oscal-artifacts/{artifact['id']}")
    assert download_resp.status_code == 200
    assert download_resp.data.startswith(b'{"plan-of-action-and-milestones"')


def test_nvd_overlay_routes_store_and_surface_latest_generated_records(client, monkeypatch):
    case_id = _create_case(client, name="Cyber Product Vendor")

    import nvd_overlay  # type: ignore

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, params=None, headers=None, timeout=0):
        params = params or {}
        if "cpes/2.0" in url:
            return FakeResponse(
                {
                    "products": [
                        {
                            "cpe": {
                                "cpeName": "cpe:2.3:a:acme:secure_portal:1.0:*:*:*:*:*:*:*",
                                "titles": [{"lang": "en", "title": "Acme Secure Portal 1.0"}],
                            }
                        }
                    ]
                }
            )
        if "cves/2.0" in url:
            return FakeResponse(
                {
                    "vulnerabilities": [
                        {
                            "cve": {
                                "id": "CVE-2026-0001",
                                "published": "2026-01-10T00:00:00.000",
                                "descriptions": [{"lang": "en", "value": "Remote code execution vulnerability."}],
                                "metrics": {
                                    "cvssMetricV31": [
                                        {"cvssData": {"baseScore": 9.8, "baseSeverity": "CRITICAL"}}
                                    ]
                                },
                                "cisaExploitAdd": "2026-02-01",
                            }
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(nvd_overlay.requests, "get", fake_get)

    overlay_resp = client.post(
        f"/api/cases/{case_id}/nvd-overlays",
        json={"product_terms": ["Secure Portal"]},
    )
    assert overlay_resp.status_code == 201
    artifact = overlay_resp.get_json()["overlay"]
    assert artifact["artifact_type"] == "nvd_overlay"
    assert artifact["source_system"] == "nvd_overlay"
    assert artifact["structured_fields"]["summary"]["unique_cve_count"] == 1
    assert artifact["structured_fields"]["summary"]["kev_flagged_cve_count"] == 1

    list_resp = client.get(f"/api/cases/{case_id}/nvd-overlays")
    assert list_resp.status_code == 200
    records = list_resp.get_json()["overlays"]
    assert len(records) == 1
    assert records[0]["id"] == artifact["id"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    latest = case_resp.get_json()["latest_nvd_overlay"]
    assert latest["id"] == artifact["id"]
    assert latest["structured_fields"]["product_terms"] == ["Secure Portal"]

    download_resp = client.get(f"/api/cases/{case_id}/nvd-overlays/{artifact['id']}")
    assert download_resp.status_code == 200
    assert b'"unique_cve_count": 1' in download_resp.data


def test_enrichment_api_includes_evidence_lane_metadata(client):
    from osint import EnrichmentResult, Finding
    from osint import enrichment

    server = sys.modules["server"]
    case_id = _create_case(client, name="Evidence Lane Vendor")

    report = enrichment._build_report(
        "Evidence Lane Vendor",
        "US",
        [
            EnrichmentResult(
                source="sam_gov",
                vendor_name="Evidence Lane Vendor",
                findings=[
                    Finding(
                        source="sam_gov",
                        category="registration",
                        title="Active SAM registration",
                        detail="UEI and CAGE confirmed",
                        severity="low",
                        confidence=0.93,
                    )
                ],
                elapsed_ms=5,
            )
        ],
        time.time(),
    )
    server.db.save_enrichment(case_id, report)

    resp = client.get(f"/api/cases/{case_id}/enrichment")
    assert resp.status_code == 200
    body = resp.get_json()

    assert body["findings"][0]["source_class"] == "public_connector"
    assert body["findings"][0]["authority_level"] == "official_registry"
    assert body["connector_status"]["sam_gov"]["access_model"] == "public_api"
    assert body["evidence_lanes"]["source_classes"]["public_connector"] == 1


def test_case_monitor_route_queues_background_check(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Queued Monitor Vendor")
    trigger_calls = []

    class FakeScheduler:
        def trigger_sweep(self, vendor_ids=None):
            trigger_calls.append(vendor_ids)
            return "sweep-123"

        def get_sweep_status(self, sweep_id):
            assert sweep_id == "sweep-123"
            return {"status": "queued", "triggered_at": "2026-03-23T00:00:00Z"}

    monkeypatch.setattr(server, "HAS_MONITOR_SCHEDULER", True)
    monkeypatch.setattr(server, "_get_monitor_scheduler", lambda: FakeScheduler())

    resp = client.post(f"/api/cases/{case_id}/monitor")
    assert resp.status_code == 202

    body = resp.get_json()
    assert body["mode"] == "async"
    assert body["vendor_id"] == case_id
    assert body["sweep_id"] == "sweep-123"
    assert body["status"] == "queued"
    assert body["status_url"].endswith(f"/api/cases/{case_id}/monitor/sweep-123")
    assert trigger_calls == [[case_id]]


def test_case_monitor_status_route_includes_latest_result(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Queued Monitor Status Vendor")
    server.db.save_monitoring_log(
        vendor_id=case_id,
        previous_risk="TIER_4_CLEAR",
        current_risk="TIER_4_APPROVED",
        risk_changed=True,
        new_findings_count=2,
        resolved_findings_count=1,
    )

    class FakeScheduler:
        def get_sweep_status(self, sweep_id):
            assert sweep_id == "sweep-456"
            return {
                "status": "completed",
                "started_at": "2026-03-23T00:00:00Z",
                "completed_at": "2026-03-23T00:00:10Z",
                "total_vendors": 1,
                "processed": 1,
                "risk_changes": 1,
                "new_alerts": 1,
            }

    monkeypatch.setattr(server, "HAS_MONITOR_SCHEDULER", True)
    monkeypatch.setattr(server, "_get_monitor_scheduler", lambda: FakeScheduler())

    resp = client.get(f"/api/cases/{case_id}/monitor/sweep-456")
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["status"] == "completed"
    assert body["vendor_id"] == case_id
    assert body["latest_check"]["vendor_id"] == case_id
    assert body["latest_score"]["tier"] is not None


def test_case_monitoring_history_route_returns_recent_checks(client):
    case_id = _create_case(client, name="Monitoring History Vendor")

    server = sys.modules["server"]
    server.db.save_monitoring_log(
        vendor_id=case_id,
        previous_risk="TIER_4_CLEAR",
        current_risk="TIER_4_CLEAR",
        risk_changed=False,
        new_findings_count=0,
        resolved_findings_count=1,
    )
    time.sleep(0.01)
    server.db.save_monitoring_log(
        vendor_id=case_id,
        previous_risk="TIER_4_CLEAR",
        current_risk="TIER_4_APPROVED",
        risk_changed=True,
        new_findings_count=2,
        resolved_findings_count=0,
    )

    resp = client.get(f"/api/cases/{case_id}/monitoring?limit=5")
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["vendor_id"] == case_id
    assert body["vendor_name"] == "Monitoring History Vendor"
    assert len(body["monitoring_history"]) == 2
    assert body["monitoring_history"][0]["risk_changed"] in {0, 1, False, True}
    assert body["monitoring_history"][0]["vendor_id"] == case_id
    assert "checked_at" in body["monitoring_history"][0]


def test_dossier_route_requests_ai_hydration_by_default(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Dossier Hydration Vendor")
    captured = {}

    def fake_generate_dossier(vendor_id, user_id="", hydrate_ai=False):
        captured["vendor_id"] = vendor_id
        captured["user_id"] = user_id
        captured["hydrate_ai"] = hydrate_ai
        return "<html><body>AI Narrative Brief</body></html>"

    monkeypatch.setattr(server, "generate_dossier", fake_generate_dossier)

    resp = client.post(f"/api/cases/{case_id}/dossier", json={"format": "html"})
    assert resp.status_code == 200
    assert captured == {
        "vendor_id": case_id,
        "user_id": "dev",
        "hydrate_ai": True,
    }
    assert "AI Narrative Brief" in resp.get_data(as_text=True)


def test_dossier_route_returns_cache_busting_download_url(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Dossier Cache Bust Vendor")

    monkeypatch.setattr(
        server,
        "generate_dossier",
        lambda vendor_id, user_id="", hydrate_ai=False: "<html><body>fresh dossier</body></html>",
    )

    resp = client.post(f"/api/cases/{case_id}/dossier", json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert f"/api/dossiers/dossier-{case_id}-" in body["download_url"]


def test_dossier_pdf_route_requests_ai_hydration_by_default(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="PDF Dossier Hydration Vendor")
    captured = {}

    def fake_generate_pdf_dossier(vendor_id, user_id="", hydrate_ai=False):
        captured["vendor_id"] = vendor_id
        captured["user_id"] = user_id
        captured["hydrate_ai"] = hydrate_ai
        return b"%PDF-1.4 mocked"

    monkeypatch.setattr(server, "generate_pdf_dossier", fake_generate_pdf_dossier)

    resp = client.post(f"/api/cases/{case_id}/dossier-pdf", json={})
    assert resp.status_code == 200
    assert captured == {
        "vendor_id": case_id,
        "user_id": "dev",
        "hydrate_ai": True,
    }
    assert resp.data.startswith(b"%PDF-1.4")


def test_monitor_run_route_queues_background_sweep(client, monkeypatch):
    server = sys.modules["server"]
    trigger_calls = []

    class FakeScheduler:
        def trigger_sweep(self, vendor_ids=None):
            trigger_calls.append(vendor_ids)
            return "sweep-789"

        def get_sweep_status(self, sweep_id):
            assert sweep_id == "sweep-789"
            return {"status": "queued", "triggered_at": "2026-03-23T00:00:00Z"}

    monkeypatch.setattr(server, "HAS_MONITOR_SCHEDULER", True)
    monkeypatch.setattr(server, "_get_monitor_scheduler", lambda: FakeScheduler())

    resp = client.post("/api/monitor/run", json={})
    assert resp.status_code == 202

    body = resp.get_json()
    assert body["mode"] == "async"
    assert body["sweep_id"] == "sweep-789"
    assert body["status"] == "queued"
    assert body["status_url"].endswith("/api/monitor/sweep/sweep-789")
    assert trigger_calls == [None]


def test_batch_upload_and_report_flow(client):
    csv_bytes = io.BytesIO(b"name,country\nAcme Systems,US\nNorthwind GmbH,DE\n")
    upload_resp = client.post(
        "/api/batch/upload",
        data={"file": (csv_bytes, "vendors.csv")},
        content_type="multipart/form-data",
    )

    assert upload_resp.status_code == 201
    batch_id = upload_resp.get_json()["batch_id"]

    deadline = time.time() + 5
    detail = None
    while time.time() < deadline:
        detail_resp = client.get(f"/api/batch/{batch_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.get_json()
        if detail["status"] in {"completed", "failed"}:
            break
        time.sleep(0.1)

    assert detail is not None
    assert detail["total_vendors"] == 2
    assert detail["processed"] == 2
    assert len(detail["items"]) == 2

    report_resp = client.get(f"/api/batch/{batch_id}/report")
    assert report_resp.status_code == 200
    assert report_resp.headers["Content-Type"].startswith("text/csv")
    assert "vendor_name,country,status" in report_resp.get_data(as_text=True)


def test_ai_routes_expose_configuration_surface(client):
    providers_resp = client.get("/api/ai/providers")
    if providers_resp.status_code == 501:
        pytest.skip("AI module not available in this environment")

    assert providers_resp.status_code == 200
    providers = providers_resp.get_json()["providers"]
    assert len(providers) >= 1

    config_resp = client.get("/api/ai/config")
    assert config_resp.status_code == 200
    assert config_resp.get_json()["configured"] is False


def test_enrichment_timeout_returns_partial_results(monkeypatch):
    if "osint.enrichment" in sys.modules:
        enrichment = importlib.reload(sys.modules["osint.enrichment"])
    else:
        from osint import enrichment  # type: ignore

    from osint import EnrichmentResult, Finding

    class FastConnector:
        @staticmethod
        def enrich(vendor_name, country="", **_ids):
            return EnrichmentResult(
                source="fast_connector",
                vendor_name=vendor_name,
                findings=[Finding(source="fast_connector", category="test", title="Fast hit", detail="ok", severity="low", confidence=0.9)],
                elapsed_ms=5,
            )

    class SlowConnector:
        @staticmethod
        def enrich(vendor_name, country="", **_ids):
            time.sleep(0.2)
            return EnrichmentResult(source="slow_connector", vendor_name=vendor_name, elapsed_ms=200)

    monkeypatch.setattr(
        enrichment,
        "CONNECTORS",
        [("fast_connector", FastConnector), ("slow_connector", SlowConnector)],
    )

    report = enrichment.enrich_vendor("Timeout Test Vendor", timeout=0.05)
    assert report["summary"]["connectors_run"] == 2
    assert report["summary"]["errors"] == 1
    assert "slow_connector" in report["connector_status"]
    assert report["connector_status"]["slow_connector"]["error"]


def test_enrich_stream_route_emits_scored_and_done_events(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Streaming Test Vendor")

    def fake_stream(*_args, **_kwargs):
        yield "start", {"vendor_name": "Streaming Test Vendor"}
        yield "connector_done", {"connector": "fast_connector", "findings": 1}
        yield "complete", {
            "vendor_name": "Streaming Test Vendor",
            "overall_risk": "low",
            "findings": [],
            "summary": {"connectors_run": 1, "errors": 0},
            "connector_status": {
                "fast_connector": {"success": True, "error": None}
            },
        }

    monkeypatch.setattr(server, "enrich_vendor_streaming", fake_stream)
    monkeypatch.setattr(
        server,
        "augment_from_enrichment",
        lambda base_input, _report: SimpleNamespace(
            vendor_input=base_input,
            provenance={},
            extra_risk_signals={},
        ),
    )
    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *_args, **_kwargs: {"status": "pending", "job_id": "ai-job-stream"})

    resp = client.get(f"/api/cases/{case_id}/enrich-stream")
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"

    body = resp.get_data(as_text=True)
    assert "event: start" in body
    assert "event: connector_done" in body
    assert "event: complete" in body
    assert "event: scored" in body
    assert "event: analysis" in body
    assert "event: done" in body


def test_access_ticket_issues_short_lived_browser_ticket_for_enrich_stream(auth_client, monkeypatch):
    client = auth_client["client"]
    server = auth_client["server"]
    headers = auth_client["headers"]
    case_id = _create_case(client, name="Access Ticket Stream Vendor", headers=headers)

    def fake_stream(*_args, **_kwargs):
        yield "start", {"vendor_name": "Access Ticket Stream Vendor", "total_connectors": 1, "connector_names": ["fast_connector"]}
        yield "complete", {
            "vendor_name": "Access Ticket Stream Vendor",
            "overall_risk": "low",
            "findings": [],
            "summary": {"connectors_run": 1, "errors": 0},
            "connector_status": {"fast_connector": {"success": True, "error": None}},
        }

    monkeypatch.setattr(server, "enrich_vendor_streaming", fake_stream)
    monkeypatch.setattr(
        server,
        "augment_from_enrichment",
        lambda base_input, _report: SimpleNamespace(vendor_input=base_input, provenance={}, extra_risk_signals={}),
    )
    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *_args, **_kwargs: {"status": "pending", "job_id": "ai-job-stream"})

    ticket_resp = client.post(
        "/api/auth/access-ticket",
        json={"path": f"/api/cases/{case_id}/enrich-stream"},
        headers=headers,
    )
    assert ticket_resp.status_code == 200
    access_ticket = ticket_resp.get_json()["access_ticket"]

    resp = client.get(f"/api/cases/{case_id}/enrich-stream?access_ticket={access_ticket}")
    assert resp.status_code == 200
    assert "event: start" in resp.get_data(as_text=True)


def test_access_ticket_opens_dossier_without_bearer_in_query(auth_client, monkeypatch):
    client = auth_client["client"]
    server = auth_client["server"]
    headers = auth_client["headers"]
    case_id = _create_case(client, name="Access Ticket Dossier Vendor", headers=headers)

    monkeypatch.setattr(
        server,
        "generate_dossier",
        lambda vendor_id, user_id="", hydrate_ai=False: "<html><body>AI Narrative Brief</body></html>",
    )

    dossier_resp = client.post(f"/api/cases/{case_id}/dossier", json={}, headers=headers)
    assert dossier_resp.status_code == 200
    download_url = dossier_resp.get_json()["download_url"]

    ticket_resp = client.post(
        "/api/auth/access-ticket",
        json={"path": download_url},
        headers=headers,
    )
    assert ticket_resp.status_code == 200
    access_ticket = ticket_resp.get_json()["access_ticket"]

    served = client.get(f"{download_url}?access_ticket={access_ticket}")
    assert served.status_code == 200
    assert "AI Narrative Brief" in served.get_data(as_text=True)


def test_access_ticket_rejects_unsupported_path(auth_client):
    client = auth_client["client"]
    headers = auth_client["headers"]

    resp = client.post(
        "/api/auth/access-ticket",
        json={"path": "/api/cases"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_enrich_and_score_primes_ai_analysis(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Enrich And Score AI Vendor")

    monkeypatch.setattr(
        server,
        "enrich_vendor",
        lambda *args, **kwargs: {
            "overall_risk": "low",
            "findings": [],
            "summary": {"connectors_run": 1, "errors": 0},
            "identifiers": {},
            "total_elapsed_ms": 25,
            "connector_status": {"fast_connector": {"success": True, "error": None}},
        },
    )
    monkeypatch.setattr(server, "_persist_enrichment_artifacts", lambda *_args, **_kwargs: {"events": [], "graph": {"nodes": 3}})
    monkeypatch.setattr(
        server,
        "_canonical_rescore_from_enrichment",
        lambda *_args, **_kwargs: {
            "augmentation": SimpleNamespace(
                changes={},
                extra_risk_signals={},
                verified_identifiers={},
                provenance={},
            ),
            "score_dict": {
                "composite_score": 11,
                "is_hard_stop": False,
                "calibrated": {"calibrated_tier": "TIER_4_CLEAR", "calibrated_probability": 0.11},
            },
        },
    )
    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *_args, **_kwargs: {"status": "pending", "job_id": "ai-job-sync"})

    resp = client.post(f"/api/cases/{case_id}/enrich-and-score", json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ai_analysis"]["status"] == "pending"
    assert body["ai_analysis"]["job_id"] == "ai-job-sync"
