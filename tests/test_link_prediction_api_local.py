import importlib
import os
import sys

from flask import Flask


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload_fresh(module_name: str):
    if module_name in sys.modules:
        del sys.modules[module_name]
    return importlib.import_module(module_name)


def test_predicted_links_endpoint_can_persist_queue(monkeypatch):
    monkeypatch.setenv("XIPHOS_PG_URL", "postgresql://test")

    api = _reload_fresh("link_prediction_api")
    monkeypatch.setattr(api, "_get_entity_name", lambda pg_url, entity_id: "Acme Corp")
    monkeypatch.setattr(api, "_get_model_version", lambda pg_url: "model-123")
    monkeypatch.setattr(
        api,
        "get_predicted_links",
        lambda pg_url, entity_id, top_k=10: [
            {
                "target_entity_id": "ent-target",
                "target_name": "Target Co",
                "predicted_relation": "owned_by",
                "predicted_edge_family": "ownership_control",
                "score": 0.12,
            }
        ],
    )
    monkeypatch.setattr(
        api,
        "queue_predicted_links",
        lambda pg_url, entity_id, top_k=10: {
            "entity_id": entity_id,
            "entity_name": "Acme Corp",
            "queued_count": 1,
            "existing_count": 0,
            "count": 1,
            "items": [],
        },
    )

    app = Flask(__name__)
    app.register_blueprint(api.link_prediction_bp)
    client = app.test_client()

    response = client.get("/api/graph/predicted-links/ent-source?top_k=5&persist=true")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["entity_name"] == "Acme Corp"
    assert payload["persisted"] is True
    assert payload["queue_summary"]["queued_count"] == 1
    assert payload["count"] == 1


def test_review_queue_endpoint_returns_filtered_rows(monkeypatch):
    monkeypatch.setenv("XIPHOS_PG_URL", "postgresql://test")

    api = _reload_fresh("link_prediction_api")
    captured = {}

    def fake_list(pg_url, **kwargs):
        captured.update(kwargs)
        return [{"id": 7, "reviewed": False, "predicted_edge_family": "ownership_control"}]

    monkeypatch.setattr(api, "list_predicted_link_queue", fake_list)

    app = Flask(__name__)
    app.register_blueprint(api.link_prediction_bp)
    client = app.test_client()

    response = client.get(
        "/api/graph/predicted-links/review-queue"
        "?reviewed=false&confirmed=true&novel_only=true&edge_family=ownership_control&limit=20&offset=5"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["count"] == 1
    assert captured["reviewed"] is False
    assert captured["analyst_confirmed"] is True
    assert captured["novel_only"] is True
    assert captured["edge_family"] == "ownership_control"
    assert captured["limit"] == 20
    assert captured["offset"] == 5


def test_review_batch_endpoint_requires_reviews_list(monkeypatch):
    monkeypatch.setenv("XIPHOS_PG_URL", "postgresql://test")

    api = _reload_fresh("link_prediction_api")
    app = Flask(__name__)
    app.register_blueprint(api.link_prediction_bp)
    client = app.test_client()

    response = client.post("/api/graph/predicted-links/review-batch", json={})

    assert response.status_code == 400
    assert "reviews list is required" in response.get_json()["error"]


def test_single_review_endpoint_uses_review_helper(monkeypatch):
    monkeypatch.setenv("XIPHOS_PG_URL", "postgresql://test")

    api = _reload_fresh("link_prediction_api")
    monkeypatch.setattr(
        api,
        "review_predicted_links",
        lambda pg_url, reviews, reviewed_by="unknown": {
            "reviewed_at": "2026-03-30T08:00:00Z",
            "items": [
                {
                    "id": reviews[0]["id"],
                    "status": "confirmed",
                    "rejection_reason": None,
                    "relationship_created": True,
                    "promoted_relationship_id": 44,
                }
            ],
        },
    )

    app = Flask(__name__)
    app.register_blueprint(api.link_prediction_bp)
    client = app.test_client()

    response = client.post(
        "/api/graph/predicted-links/12/review",
        json={"confirmed": True, "notes": "Looks real"},
        headers={"X-User-Id": "analyst-1"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["id"] == 12
    assert payload["status"] == "confirmed"
    assert payload["relationship_created"] is True
    assert payload["promoted_relationship_id"] == 44
    assert payload["reviewed_by"] == "analyst-1"


def test_review_batch_endpoint_forwards_rejection_reason(monkeypatch):
    monkeypatch.setenv("XIPHOS_PG_URL", "postgresql://test")

    api = _reload_fresh("link_prediction_api")
    captured = {}

    def fake_review(pg_url, reviews, reviewed_by="unknown"):
        captured["reviews"] = reviews
        captured["reviewed_by"] = reviewed_by
        return {
            "reviewed_count": len(reviews),
            "confirmed_count": 0,
            "rejected_count": len(reviews),
            "reviewed_by": reviewed_by,
            "reviewed_at": "2026-03-30T08:00:00Z",
            "items": [
                {
                    "id": reviews[0]["id"],
                    "status": "rejected",
                    "rejection_reason": reviews[0].get("rejection_reason"),
                    "relationship_created": False,
                    "promoted_relationship_id": None,
                }
            ],
        }

    monkeypatch.setattr(api, "review_predicted_links", fake_review)

    app = Flask(__name__)
    app.register_blueprint(api.link_prediction_bp)
    client = app.test_client()

    response = client.post(
        "/api/graph/predicted-links/review-batch",
        json={"reviews": [{"id": 21, "confirmed": False, "rejection_reason": "wrong_target_entity", "notes": "wrong company"}]},
        headers={"X-User-Id": "analyst-2"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["rejected_count"] == 1
    assert captured["reviews"][0]["rejection_reason"] == "wrong_target_entity"
    assert captured["reviewed_by"] == "analyst-2"


def test_review_stats_endpoint_returns_helper_payload(monkeypatch):
    monkeypatch.setenv("XIPHOS_PG_URL", "postgresql://test")

    api = _reload_fresh("link_prediction_api")
    captured = {}

    def fake_stats(pg_url, source_entity_id=None):
        captured["source_entity_id"] = source_entity_id
        return {"total_links": 14, "reviewed_links": 5, "confirmation_rate": 0.6}

    monkeypatch.setattr(
        api,
        "get_prediction_review_stats",
        fake_stats,
    )

    app = Flask(__name__)
    app.register_blueprint(api.link_prediction_bp)
    client = app.test_client()

    response = client.get("/api/graph/predicted-links/review-stats?source_entity_id=ent-source")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total_links"] == 14
    assert payload["reviewed_links"] == 5
    assert payload["confirmation_rate"] == 0.6
    assert captured["source_entity_id"] == "ent-source"
