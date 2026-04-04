import importlib
import os
import sys
from collections import defaultdict

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload_module(name: str):
    if name in sys.modules:
        return importlib.reload(sys.modules[name])
    return importlib.import_module(name)


def _entity(entity_id: str, name: str, *, entity_type: str = "company"):
    from entity_resolution import ResolvedEntity

    return ResolvedEntity(
        id=entity_id,
        canonical_name=name,
        entity_type=entity_type,
        aliases=[],
        identifiers={},
        country="US",
        sources=["test_fixture"],
        confidence=0.93,
        last_updated="2026-04-04T12:00:00Z",
    )


@pytest.fixture
def graph_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")
    monkeypatch.setenv("XIPHOS_DB_ENGINE", "sqlite")
    monkeypatch.delenv("XIPHOS_PG_URL", raising=False)

    kg = _reload_module("knowledge_graph")
    kg.init_kg_db()

    kg.save_entity(_entity("entity:smx", "SMX"))
    kg.save_entity(_entity("entity:amentum", "Amentum"))
    kg.save_entity(_entity("entity:ils2", "ILS 2", entity_type="contract_vehicle"))
    kg.link_entity_to_vendor("entity:smx", "case-smx")

    kg.save_relationship(
        "entity:smx",
        "entity:amentum",
        "competitor_of",
        confidence=0.87,
        data_source="fixture://competitive",
        evidence="Fixture competitor relationship",
        observed_at="2026-04-04T12:00:00Z",
        artifact_ref="fixture://competitive/1",
        evidence_url="https://example.test/competitive",
        evidence_title="Competitive overlap",
        vendor_id="case-smx",
    )
    kg.save_relationship(
        "entity:smx",
        "entity:ils2",
        "pursuing_vehicle",
        confidence=0.82,
        data_source="fixture://vehicle",
        evidence="Fixture vehicle relationship",
        observed_at="2026-04-04T12:00:00Z",
        artifact_ref="fixture://vehicle/1",
        evidence_url="https://example.test/vehicle",
        evidence_title="Vehicle context",
        vendor_id="case-smx",
    )

    axiom_graph_interface = _reload_module("axiom_graph_interface")
    server = _reload_module("server")
    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    return {
        "kg": kg,
        "agi": axiom_graph_interface,
        "server": server,
    }


def test_axiom_graph_interface_profile_and_staging_review(graph_env):
    agi = graph_env["agi"]

    profile = agi.graph_profile(vendor_id="case-smx", workflow_lane="counterparty")
    assert profile["status"] == "ok"
    assert profile["structured_payload"]["entity"]["name"] == "SMX"
    assert profile["structured_payload"]["direct_relationship_counts"]["competitor_of"] == 1
    assert profile["structured_payload"]["state_mix"]["observed"] >= 1

    staged = agi.graph_assert(
        "entity:smx",
        "entity:amentum",
        "related_to",
        confidence=0.74,
        reasoning="Analyst suspects a deeper control path.",
        vendor_id="case-smx",
    )
    assert staged["status"] == "staged"

    queue = agi.graph_staging_queue(vendor_id="case-smx", status="staged")
    assert queue["structured_payload"]["count"] >= 1
    staging_id = queue["structured_payload"]["items"][0]["staging_id"]

    reviewed = agi.graph_review_staging(
        staging_id,
        review_outcome="promote",
        reviewed_by="analyst@example.com",
        review_notes="Promotion approved in test.",
    )
    assert reviewed["status"] == "ok"
    assert reviewed["structured_payload"]["review_outcome"] == "promote"
    assert reviewed["structured_payload"]["status"] == "reviewed_promoted"


def test_axiom_graph_routes_expose_interrogation_and_review(graph_env):
    server = graph_env["server"]

    with server.app.test_client() as client:
        profile = client.post(
            "/api/axiom/graph/profile",
            json={"vendor_id": "case-smx", "workflow_lane": "counterparty"},
        )
        assert profile.status_code == 200
        profile_body = profile.get_json()
        assert profile_body["status"] == "ok"
        assert profile_body["structured_payload"]["entity"]["name"] == "SMX"

        staged = client.post(
            "/api/axiom/graph/annotate",
            json={
                "entity_id": "entity:smx",
                "annotation_type": "analyst_note",
                "content": "Potential BD overlap worth follow-up.",
                "confidence": 0.66,
                "vendor_id": "case-smx",
            },
        )
        assert staged.status_code == 200
        staged_id = staged.get_json()["structured_payload"]["staging_id"]

        queue = client.get("/api/axiom/graph/staging?vendor_id=case-smx&status=staged")
        assert queue.status_code == 200
        queue_body = queue.get_json()
        assert queue_body["structured_payload"]["count"] >= 1

        review = client.post(
            f"/api/axiom/graph/staging/{staged_id}/review",
            json={"review_outcome": "hold", "review_notes": "Need one more corroborating source."},
        )
        assert review.status_code == 200
        review_body = review.get_json()
        assert review_body["structured_payload"]["status"] == "reviewed_hold"
        assert review_body["structured_payload"]["review_outcome"] == "hold"


def test_detect_communities_reports_algorithm_and_bridge_entities():
    graph_analytics = _reload_module("graph_analytics")
    analytics = graph_analytics.GraphAnalytics()
    analytics.nodes = {
        "a": {"canonical_name": "Alpha", "entity_type": "company"},
        "b": {"canonical_name": "Bravo", "entity_type": "company"},
        "c": {"canonical_name": "Charlie", "entity_type": "company"},
        "d": {"canonical_name": "Delta", "entity_type": "company"},
    }
    analytics.edges = [
        {"source": "a", "target": "b", "rel_type": "teamed_with", "confidence": 0.9},
        {"source": "b", "target": "c", "rel_type": "teamed_with", "confidence": 0.9},
        {"source": "c", "target": "a", "rel_type": "teamed_with", "confidence": 0.9},
        {"source": "c", "target": "d", "rel_type": "brokered_by", "confidence": 0.7},
    ]
    analytics.adj = defaultdict(
        list,
        {
            "a": [("b", 0), ("c", 2)],
            "b": [("a", 0), ("c", 1)],
            "c": [("b", 1), ("a", 2), ("d", 3)],
            "d": [("c", 3)],
        },
    )
    analytics.loaded = True

    result = analytics.detect_communities()

    assert result["algorithm"] in {"leiden", "louvain", "label_propagation"}
    assert result["count"] >= 1
    first = next(iter(result["communities"].values()))
    assert "density" in first
    assert "bridge_entities" in first
