import importlib
import os
import sys
from types import ModuleType

from flask import Blueprint, Flask


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload_fresh(module_name: str):
    if module_name in sys.modules:
        del sys.modules[module_name]
    return importlib.import_module(module_name)


def test_neo4j_sync_respects_shared_dev_mode_auth(monkeypatch):
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    _reload_fresh("auth")
    neo4j_api = _reload_fresh("neo4j_api")

    monkeypatch.setattr(neo4j_api, "is_neo4j_available", lambda: True)
    scheduler = neo4j_api.get_neo4j_sync_scheduler()
    monkeypatch.setattr(
        scheduler,
        "queue_full_sync",
        lambda **kwargs: {
            "job_id": "job-123",
            "sync_kind": "full",
            "status": "queued",
            "metadata": {},
            "entities_synced": 0,
            "relationships_synced": 0,
            "duration_ms": 0,
        },
    )

    app = Flask(__name__)
    app.register_blueprint(neo4j_api.neo4j_bp)
    client = app.test_client()

    response = client.post("/api/neo4j/sync")

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["status"] == "queued"
    assert payload["job_id"] == "job-123"
    assert payload["status_url"].endswith("/api/neo4j/sync/job-123")


def test_neo4j_sync_route_supports_opt_in_blocking_mode(monkeypatch):
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    _reload_fresh("auth")
    neo4j_api = _reload_fresh("neo4j_api")

    monkeypatch.setattr(neo4j_api, "is_neo4j_available", lambda: True)
    monkeypatch.setattr(
        neo4j_api,
        "full_sync_from_postgres",
        lambda: {
            "status": "success",
            "entities_synced": 4,
            "relationships_synced": 3,
            "duration_ms": 12,
            "error": None,
        },
    )

    app = Flask(__name__)
    app.register_blueprint(neo4j_api.neo4j_bp)
    client = app.test_client()

    response = client.post("/api/neo4j/sync", json={"sync": True})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "success"
    assert payload["entities_synced"] == 4
    assert payload["relationships_synced"] == 3


def test_blueprint_registry_registers_available_modules_and_skips_missing(monkeypatch):
    import blueprint_registry

    fake_link = ModuleType("link_prediction_api")
    fake_link.link_prediction_bp = Blueprint("link_prediction", __name__)
    fake_feedback = ModuleType("feedback_api")
    fake_feedback.feedback_bp = Blueprint("feedback", __name__)

    def fake_import(module_name: str):
        if module_name == "link_prediction_api":
            return fake_link
        if module_name == "feedback_api":
            return fake_feedback
        if module_name == "neo4j_api":
            raise ImportError("neo4j unavailable")
        raise ImportError(module_name)

    monkeypatch.setattr(blueprint_registry.importlib, "import_module", fake_import)

    app = Flask(__name__)
    registered = blueprint_registry.register_optional_blueprints(app, __import__("logging").getLogger("test"))

    assert registered == ["link_prediction", "feedback"]
    assert "link_prediction" in app.blueprints
    assert "feedback" in app.blueprints
