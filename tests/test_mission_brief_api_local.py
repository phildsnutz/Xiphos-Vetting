import importlib
import os
import sys

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

    for module_name in ["db", "server"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    if "server" not in sys.modules:
        import server  # type: ignore

    server = sys.modules["server"]
    server.db.init_db()
    server.init_auth_db()

    with server.app.test_client() as test_client:
        yield test_client


def test_create_mission_brief_persists_phase_zero_context(client):
    response = client.post(
        "/api/mission-briefs",
        json={
            "room": "front_porch",
            "object_type": "vehicle",
            "engagement_type": "contract_vehicle_intelligence",
            "status": "scoped",
            "question_count": 2,
            "confidence_score": 0.64,
            "primary_targets": {
                "vehicle_name": "ILS 2",
                "incumbent_prime": "Amentum",
            },
            "known_context": {
                "vehicle_timing": "pre solicitation",
                "weighted_first": "the vehicle ecosystem",
            },
            "priority_requirements": [
                "Work the full picture first.",
                "Treat timing as pre-solicitation and pressure continuity.",
            ],
            "authorized_tiers": ["public_record", "graph_context", "axiom_gap_closure"],
            "summary": "Contract vehicle intelligence on ILS 2, pre solicitation, Amentum incumbent.",
        },
    )

    assert response.status_code == 201
    payload = response.get_json()["mission_brief"]
    assert payload["object_type"] == "vehicle"
    assert payload["primary_targets"]["vehicle_name"] == "ILS 2"
    assert payload["known_context"]["vehicle_timing"] == "pre solicitation"
    assert payload["question_count"] == 2


def test_update_mission_brief_links_case_and_status(client):
    import server

    server.db.upsert_vendor(
        "c-brief123",
        "SMX",
        "US",
        "dod_unclassified",
        {
            "name": "SMX",
            "country": "US",
            "ownership": {},
            "data_quality": {},
            "exec": {},
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
        },
    )

    create_response = client.post(
        "/api/mission-briefs",
        json={
            "object_type": "vendor",
            "engagement_type": "vendor_assessment",
            "primary_targets": {"vendor_name": "SMX"},
            "summary": "Vendor assessment on SMX.",
        },
    )
    brief_id = create_response.get_json()["mission_brief"]["id"]

    update_response = client.put(
        f"/api/mission-briefs/{brief_id}",
        json={
            "case_id": "c-brief123",
            "object_type": "vendor",
            "engagement_type": "vendor_assessment",
            "status": "brief_ready",
            "question_count": 0,
            "confidence_score": 0.81,
            "primary_targets": {"vendor_name": "SMX"},
            "known_context": {"weighted_first": "full picture"},
            "priority_requirements": ["Work the full picture first."],
            "authorized_tiers": ["public_record", "graph_context", "axiom_gap_closure"],
            "summary": "Vendor assessment on SMX. Weight the full picture first without shrinking the scope.",
            "notes": [
                "3 sources with data produced 4 surviving findings in the returned brief.",
                "The graph changed the read with 6 relationships and 1 visible control path.",
            ],
        },
    )

    assert update_response.status_code == 200
    payload = update_response.get_json()["mission_brief"]
    assert payload["case_id"] == "c-brief123"
    assert payload["status"] == "brief_ready"
    assert payload["notes"][0].startswith("3 sources with data")

    get_response = client.get(f"/api/mission-briefs/{brief_id}")
    assert get_response.status_code == 200
    assert get_response.get_json()["mission_brief"]["case_id"] == "c-brief123"
