import importlib
import os
import sys
import json
from pathlib import Path

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


def test_training_dashboard_endpoint_returns_payload(monkeypatch):
    monkeypatch.setenv("XIPHOS_PG_URL", "postgresql://test")

    api = _reload_fresh("link_prediction_api")
    monkeypatch.setattr(
        api,
        "build_training_dashboard_payload",
        lambda: {
            "generated_at": "2026-03-30T13:30:00Z",
            "readiness": {"verdict": "NOT_READY"},
            "neo4j": {"verdict": "PASS"},
            "benchmark": {"verdict": "FAIL", "stage_results": []},
            "live_tranche": {"reviewed_links": 27, "intermediary_route_queries_evaluated": 0, "cyber_dependency_queries_evaluated": 0},
        },
    )

    app = Flask(__name__)
    app.register_blueprint(api.link_prediction_bp)
    client = app.test_client()

    response = client.get("/api/graph/training-dashboard")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["neo4j"]["verdict"] == "PASS"
    assert payload["benchmark"]["verdict"] == "FAIL"
    assert payload["live_tranche"]["reviewed_links"] == 27


def test_build_training_dashboard_payload_reads_runtime_report_roots(monkeypatch, tmp_path):
    monkeypatch.setenv("XIPHOS_PG_URL", "postgresql://test")

    api = _reload_fresh("link_prediction_api")
    app_reports = tmp_path / "app-reports"
    runtime_reports = tmp_path / "runtime-reports"
    monkeypatch.setattr(api, "REPORT_SEARCH_ROOTS", [app_reports, runtime_reports])

    (app_reports / "graph_training_benchmark" / "20260330150000").mkdir(parents=True)
    (runtime_reports / "graph_training_tranche_live" / "20260330150100" / "20260330150200").mkdir(parents=True)

    (app_reports / "graph_training_benchmark" / "20260330150000" / "summary.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-03-30T15:00:00Z",
                "overall_verdict": "FAIL",
                "data_foundation": {"verdict": "PASS"},
                "stage_results": [{"stage_id": "construction_training", "verdict": "FAIL", "objective": "test"}],
            }
        ),
        encoding="utf-8",
    )
    (runtime_reports / "graph_training_tranche_live" / "20260330150100" / "20260330150200" / "summary.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-03-30T15:01:00Z",
                "review_stats": {
                    "reviewed_links": 39,
                    "pending_links": 797,
                    "novel_pending_links": 797,
                    "confirmed_links": 20,
                    "rejected_links": 19,
                    "review_coverage_pct": 0.04,
                    "confirmation_rate": 0.51,
                },
                "stage_metrics": {
                    "missing_edge_recovery": {
                        "ownership_control_hits_at_10": 1.0,
                        "ownership_control_mrr": 0.95,
                        "intermediary_route_queries_evaluated": 5,
                        "cyber_dependency_queries_evaluated": 9,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    payload = api.build_training_dashboard_payload()
    assert payload["benchmark"]["verdict"] == "FAIL"
    assert payload["benchmark"]["data_foundation_verdict"] == "PASS"
    assert payload["live_tranche"]["reviewed_links"] == 39
    assert payload["live_tranche"]["intermediary_route_queries_evaluated"] == 5
    assert payload["live_tranche"]["cyber_dependency_queries_evaluated"] == 9
    assert Path(payload["live_tranche"]["path"]).parent.name == "20260330150200"


def test_build_training_dashboard_payload_uses_runtime_fallbacks(monkeypatch, tmp_path):
    monkeypatch.setenv("XIPHOS_PG_URL", "postgresql://test")

    api = _reload_fresh("link_prediction_api")
    monkeypatch.setattr(api, "REPORT_SEARCH_ROOTS", [tmp_path / "app-reports", tmp_path / "runtime-reports"])
    monkeypatch.setattr(
        api,
        "_runtime_neo4j_fallback",
        lambda tranche: {
            "verdict": "PASS",
            "generated_at": "2026-03-30T16:00:00Z",
            "path": None,
            "node_count": 8313,
            "relationship_count": 21146,
            "runtime_status": "available",
            "runtime_error": None,
            "source": "runtime_health",
        },
    )
    monkeypatch.setattr(
        api,
        "_runtime_readiness_fallback",
        lambda tranche: {
            "verdict": "UNKNOWN",
            "generated_at": None,
            "path": None,
            "runtime_status": "ok",
            "runtime_error": None,
            "runtime_vendor_count": 42,
            "runtime_unresolved_alerts": 3,
            "source": "runtime_health",
        },
    )

    payload = api.build_training_dashboard_payload()
    assert payload["neo4j"]["verdict"] == "PASS"
    assert payload["neo4j"]["node_count"] == 8313
    assert payload["neo4j"]["runtime_status"] == "available"
    assert payload["readiness"]["verdict"] == "UNKNOWN"
    assert payload["readiness"]["runtime_status"] == "ok"
    assert payload["readiness"]["runtime_vendor_count"] == 42


def test_build_training_dashboard_payload_uses_runtime_benchmark_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("XIPHOS_PG_URL", "postgresql://test")

    api = _reload_fresh("link_prediction_api")
    app_reports = tmp_path / "app-reports"
    runtime_reports = tmp_path / "runtime-reports"
    monkeypatch.setattr(api, "REPORT_SEARCH_ROOTS", [app_reports, runtime_reports])
    monkeypatch.setattr(api, "_runtime_neo4j_fallback", lambda tranche: {"verdict": "PASS", "runtime_status": "available", "node_count": 10, "relationship_count": 20, "generated_at": None, "path": None, "runtime_error": None, "source": "runtime_health"})
    monkeypatch.setattr(api, "_runtime_readiness_fallback", lambda tranche: {"verdict": "UNKNOWN", "runtime_status": "ok", "runtime_vendor_count": 2, "runtime_unresolved_alerts": 1, "generated_at": None, "path": None, "runtime_error": None, "source": "runtime_health"})
    monkeypatch.setattr(api, "BENCHMARK_SUITE_PATH", tmp_path / "suite.json")

    (runtime_reports / "graph_training_tranche_live" / "20260330160000" / "20260330160001").mkdir(parents=True)
    (runtime_reports / "graph_training_tranche_live" / "20260330160000" / "20260330160001" / "summary.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-03-30T16:00:01Z",
                "stage_metrics": {
                    "construction_training": {
                        "edge_family_micro_f1": 0.25,
                        "ownership_control_precision": 0.2,
                        "ownership_control_recall": 0.1,
                        "entity_resolution_pairwise_f1": 1.0,
                        "false_merge_rate": 0.0,
                        "descriptor_only_false_owner_rate": 0.0,
                        "gold_positive_rows_evaluated": 13,
                        "hard_negative_rows_evaluated": 10,
                    },
                    "missing_edge_recovery": {
                        "evaluation_protocol": "family_balanced_masked_holdout",
                        "masked_holdout_hits_at_10": 0.9,
                        "masked_holdout_mrr": 0.6,
                        "mean_withheld_target_rank": 3.5,
                        "ownership_control_hits_at_10": 0.9,
                        "ownership_control_mrr": 0.6,
                        "intermediary_route_queries_evaluated": 2,
                        "cyber_dependency_queries_evaluated": 0,
                        "masked_holdout_queries_evaluated": 7,
                        "unsupported_promoted_edge_rate": 0.0,
                    },
                    "novel_edge_discovery": {
                        "novel_edge_yield": 0.0,
                        "analyst_confirmation_rate": 0.0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "suite.json").write_text(
        json.dumps(
            {
                "data_foundation": {
                    "construction_gold_set": {"min_rows": 12},
                    "hard_negative_set": {"min_rows": 10},
                },
                "training_stack": [
                    {
                        "stage_id": "construction_training",
                        "objective": "construction",
                        "metrics": {
                            "edge_family_micro_f1_min": 0.93,
                            "ownership_control_precision_min": 0.98,
                            "ownership_control_recall_min": 0.9,
                            "entity_resolution_pairwise_f1_min": 0.985,
                            "false_merge_rate_max": 0.005,
                            "descriptor_only_false_owner_rate_max": 0.0,
                        },
                    },
                    {
                        "stage_id": "missing_edge_recovery",
                        "objective": "missing edge",
                        "metrics": {
                            "masked_holdout_hits_at_10_min": 0.8,
                            "masked_holdout_mrr_min": 0.45,
                            "mean_withheld_target_rank_max": 10.0,
                            "masked_holdout_queries_evaluated_min": 7,
                            "unsupported_promoted_edge_rate_max": 0.0,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = api.build_training_dashboard_payload()
    assert payload["benchmark"]["source"] == "tranche_runtime"
    assert payload["benchmark"]["verdict"] == "FAIL"
    assert payload["benchmark"]["data_foundation_verdict"] == "PASS"
    assert payload["benchmark"]["total_stage_count"] == 2
