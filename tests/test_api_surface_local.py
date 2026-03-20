import importlib
import io
import os
import sys
import time
from types import SimpleNamespace

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
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

    with server.app.test_client() as test_client:
        yield test_client


def _create_case(client, name="Acme Corp", country="US"):
    resp = client.post(
        "/api/cases",
        json={
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
        },
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

    resp = client.get(f"/api/cases/{case_id}/enrich-stream")
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"

    body = resp.get_data(as_text=True)
    assert "event: start" in body
    assert "event: connector_done" in body
    assert "event: complete" in body
    assert "event: scored" in body
    assert "event: done" in body
