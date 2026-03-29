import importlib
import os
import sys

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
        server = importlib.import_module("server")

    server.db.init_db()
    server.init_auth_db()
    with server.app.test_client() as test_client:
        yield test_client


def test_profiles_blueprint_lists_canonical_profiles(client):
    response = client.get("/api/profiles")

    assert response.status_code == 200
    payload = response.get_json()
    ids = {profile["id"] for profile in payload["profiles"]}
    assert "defense_acquisition" in ids
    assert "itar_trade_compliance" in ids


def test_profiles_blueprint_returns_404_for_unknown_profile(client):
    response = client.get("/api/profiles/not-a-real-profile")

    assert response.status_code == 404
    assert response.get_json()["error"] == "Profile not found"
