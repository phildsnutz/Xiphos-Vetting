import importlib
import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from entity_resolution import ResolvedEntity


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        server = importlib.import_module("server")

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_KG:
        server.kg.init_kg_db()

    return server


def _create_thread(client, name="Pacific sustainment mesh"):
    resp = client.post("/api/mission-threads", json={"name": name, "lane": "counterparty"})
    assert resp.status_code == 201
    return resp.get_json()["id"]


def test_resilience_summary_ranks_brittle_members_and_thread_nodes(env):
    server = env
    client = server.app.test_client()

    thread_id = _create_thread(client)

    alpha = ResolvedEntity(
        id="entity:alpha",
        canonical_name="Vendor Alpha",
        entity_type="company",
        aliases=[],
        identifiers={"lei": "549300ALPHA"},
        country="US",
        relationships=[],
        sources=["fixture"],
        confidence=0.95,
        last_updated="2026-03-31T00:00:00Z",
    )
    beta = ResolvedEntity(
        id="entity:beta",
        canonical_name="Vendor Beta",
        entity_type="company",
        aliases=[],
        identifiers={"lei": "549300BETA"},
        country="US",
        relationships=[],
        sources=["fixture"],
        confidence=0.94,
        last_updated="2026-03-31T00:00:00Z",
    )
    gamma = ResolvedEntity(
        id="entity:gamma",
        canonical_name="Vendor Gamma",
        entity_type="company",
        aliases=[],
        identifiers={"lei": "549300GAMMA"},
        country="US",
        relationships=[],
        sources=["fixture"],
        confidence=0.93,
        last_updated="2026-03-31T00:00:00Z",
    )
    site = ResolvedEntity(
        id="entity:site-hnl",
        canonical_name="Honolulu Sustainment Site",
        entity_type="facility",
        aliases=[],
        identifiers={},
        country="US",
        relationships=[],
        sources=["fixture"],
        confidence=0.92,
        last_updated="2026-03-31T00:00:00Z",
    )
    subsystem = ResolvedEntity(
        id="entity:subsystem-radar",
        canonical_name="Radar Sustainment Mesh",
        entity_type="subsystem",
        aliases=[],
        identifiers={},
        country="US",
        relationships=[],
        sources=["fixture"],
        confidence=0.92,
        last_updated="2026-03-31T00:00:00Z",
    )

    for entity in (alpha, beta, gamma, site, subsystem):
        server.kg.save_entity(entity)

    server.kg.save_relationship(
        alpha.id,
        site.id,
        "supports_site",
        confidence=0.88,
        data_source="fixture",
        evidence="Alpha supports the Honolulu site",
        vendor_id="fixture-thread",
    )
    server.kg.save_relationship(
        alpha.id,
        beta.id,
        "substitutable_with",
        confidence=0.83,
        data_source="fixture",
        evidence="Beta is approved substitute for Alpha",
        vendor_id="fixture-thread",
    )
    server.kg.save_relationship(
        gamma.id,
        subsystem.id,
        "single_point_of_failure_for",
        confidence=0.91,
        data_source="fixture",
        evidence="Gamma is the only certified node for the radar sustainment mesh",
        vendor_id="fixture-thread",
    )
    server.kg.save_relationship(
        gamma.id,
        subsystem.id,
        "maintains_system_for",
        confidence=0.86,
        data_source="fixture",
        evidence="Gamma maintains the radar sustainment mesh",
        vendor_id="fixture-thread",
    )

    assert client.post(
        f"/api/mission-threads/{thread_id}/members",
        json={"entity_id": alpha.id, "role": "heavy_lift", "criticality": "critical", "subsystem": "lift", "site": "Honolulu"},
    ).status_code == 201
    assert client.post(
        f"/api/mission-threads/{thread_id}/members",
        json={"entity_id": beta.id, "role": "heavy_lift", "criticality": "important", "subsystem": "lift", "site": "Honolulu", "is_alternate": True},
    ).status_code == 201
    assert client.post(
        f"/api/mission-threads/{thread_id}/members",
        json={"entity_id": gamma.id, "role": "radar_maintenance", "criticality": "mission_critical", "subsystem": "radar", "site": "Guam"},
    ).status_code == 201

    summary_resp = client.get(f"/api/mission-threads/{thread_id}/summary")
    assert summary_resp.status_code == 200
    summary = summary_resp.get_json()

    resilience = summary["resilience"]["summary"]
    assert resilience["model_version"] == "mission-thread-resilience-v1"
    assert resilience["top_brittle_members"][0]["label"] == "Vendor Gamma"
    assert resilience["top_brittle_members"][0]["single_point_of_failure_signal"] > 0
    assert resilience["top_resilient_members"][0]["label"] in {"Vendor Alpha", "Vendor Beta"}
    assert summary["graph"]["top_nodes_by_mission_importance"]

    graph_resp = client.get(f"/api/mission-threads/{thread_id}/graph")
    assert graph_resp.status_code == 200
    graph = graph_resp.get_json()
    assert graph["relationship_type_distribution"]["supports_site"] == 1
    assert graph["relationship_type_distribution"]["substitutable_with"] == 1
    assert graph["relationship_type_distribution"]["single_point_of_failure_for"] == 1
    assert graph["relationship_type_distribution"]["maintains_system_for"] == 1
    assert graph["member_resilience"][0]["recommended_action"]
    gamma_entity = next(entity for entity in graph["entities"] if entity["id"] == "entity:gamma")
    assert gamma_entity["mission_importance"] > 0
