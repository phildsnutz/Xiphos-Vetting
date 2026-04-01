import importlib
import os
import sys


ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
for path in (BACKEND_DIR, SCRIPTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


def test_mission_thread_briefing_route_and_module_use_seeded_amentum_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    for module_name in (
        "db",
        "knowledge_graph",
        "mission_threads",
        "mission_thread_briefing",
        "seed_mission_thread_fixture",
        "server",
    ):
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
        else:
            importlib.import_module(module_name)

    import mission_thread_briefing
    import seed_mission_thread_fixture
    import server

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_KG:
        server.kg.init_kg_db()

    seeded = seed_mission_thread_fixture.seed_fixture_by_id("amentum_honolulu_contested_logistics", depth=2)
    thread_id = seeded["thread_id"]

    briefing = mission_thread_briefing.build_mission_thread_briefing(thread_id, depth=2, member_passport_mode="control")
    assert briefing is not None
    assert briefing["briefing_version"] == "mission-thread-briefing-v1"
    assert briefing["mission_thread"]["id"] == thread_id
    assert briefing["top_brittle_members"]
    assert briefing["top_control_path_exposures"]
    assert briefing["unresolved_evidence_gaps"]
    assert briefing["recommended_mitigations"]
    assert briefing["member_briefs"]

    client = server.app.test_client()
    response = client.get(f"/api/mission-threads/{thread_id}/briefing?depth=2&mode=control")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["mission_thread"]["id"] == thread_id
    assert payload["top_control_path_exposures"][0]["rel_type"] in {
        "routes_payment_through",
        "single_point_of_failure_for",
        "supports_site",
    }
