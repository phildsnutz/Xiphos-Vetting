import importlib
import os
import sys

import pytest


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USER", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    for module_name in [
        "neo4j_integration",
        "neo4j_api",
        "blueprint_registry",
        "server",
    ]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    if "server" not in sys.modules:
        import server  # type: ignore

    server = sys.modules["server"]
    server.db.init_db()
    server.init_auth_db()
    return server.app.test_client()


def test_neo4j_health_route_is_registered_without_runtime_config(client):
    response = client.get("/api/neo4j/health")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["neo4j_available"] is False
    assert payload["status"] == "unavailable"
    assert payload["configured"] is False
    assert payload["database"] == ""


def test_neo4j_sync_route_uses_shared_dev_mode_auth(client):
    response = client.post("/api/neo4j/sync")

    assert response.status_code == 503
    assert response.get_json()["error"] == "Neo4j not available"
