import importlib
import os
import sys
import threading


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_full_sync_reads_from_knowledge_graph_database(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge_graph.db"))

    import knowledge_graph
    import neo4j_integration

    importlib.reload(knowledge_graph)
    importlib.reload(neo4j_integration)

    knowledge_graph.init_kg_db()
    with knowledge_graph.get_kg_conn() as conn:
        conn.execute(
            """
            INSERT INTO kg_entities
            (id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, risk_level, sanctions_exposure, last_updated, created_at)
            VALUES (?, ?, ?, '[]', '{}', ?, '[]', ?, ?, ?, datetime('now'), datetime('now'))
            """,
            ("entity:test-sync", "Test Sync Entity", "company", "US", 0.95, "low", 0.0),
        )
        conn.execute(
            """
            INSERT INTO kg_relationships
            (source_entity_id, target_entity_id, rel_type, confidence, data_source, evidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            ("entity:test-sync", "entity:test-sync", "related_entity", 0.8, "test", "self-link"),
        )

    captured = {}

    def fake_sync_entities(rows):
        captured["entities"] = rows
        return {"synced_count": len(rows), "failed_count": 0, "duration_ms": 1}

    def fake_sync_relationships(rows):
        captured["relationships"] = rows
        return {"synced_count": len(rows), "failed_count": 0, "duration_ms": 1}

    monkeypatch.setattr(neo4j_integration, "sync_entities_to_neo4j", fake_sync_entities)
    monkeypatch.setattr(neo4j_integration, "sync_relationships_to_neo4j", fake_sync_relationships)

    result = neo4j_integration.full_sync_from_postgres()

    assert result["entities_synced"] == 1
    assert result["relationships_synced"] == 1
    assert captured["entities"][0]["id"] == "entity:test-sync"
    assert captured["relationships"][0]["rel_type"] == "related_entity"


def test_sync_entities_normalizes_snake_case_labels_for_new_entity_types(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge_graph.db"))

    import neo4j_integration

    importlib.reload(neo4j_integration)

    captured: dict[str, object] = {}

    class DummySession:
        def run(self, cypher, **kwargs):
            captured.setdefault("runs", []).append((cypher, kwargs))

            class Result:
                @staticmethod
                def single():
                    return {"count": len(kwargs["entities"])}

            return Result()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyDriver:
        def session(self):
            return DummySession()

    monkeypatch.setattr(neo4j_integration, "get_neo4j_driver", lambda: DummyDriver())

    result = neo4j_integration.sync_entities_to_neo4j(
        [
            {"id": "component:test", "canonical_name": "Widget", "entity_type": "component", "aliases": [], "identifiers": {}, "country": "US", "sources": [], "confidence": 0.9, "risk_level": "high", "sanctions_exposure": 0.0, "created_at": "2026-03-26T00:00:00Z"},
            {"id": "subsystem:test", "canonical_name": "Control Module", "entity_type": "subsystem", "aliases": [], "identifiers": {}, "country": "US", "sources": [], "confidence": 0.9, "risk_level": "high", "sanctions_exposure": 0.0, "created_at": "2026-03-26T00:00:00Z"},
            {"id": "holding_company:test", "canonical_name": "HoldCo", "entity_type": "holding_company", "aliases": [], "identifiers": {}, "country": "CN", "sources": [], "confidence": 0.95, "risk_level": "critical", "sanctions_exposure": 0.0, "created_at": "2026-03-26T00:00:00Z"},
        ]
    )

    runs = captured["runs"]
    assert result["synced_count"] == 3
    assert any(":Component" in cypher for cypher, _ in runs)
    assert any(":Subsystem" in cypher for cypher, _ in runs)
    assert any(":HoldingCompany" in cypher for cypher, _ in runs)


def test_get_neo4j_driver_initializes_once_under_concurrency(monkeypatch):
    import neo4j_integration

    importlib.reload(neo4j_integration)

    monkeypatch.setenv("NEO4J_URI", "bolt://example")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")

    barrier = threading.Barrier(2)
    calls: list[str] = []

    class DummyDriver:
        def verify_connectivity(self):
            return None

        def close(self):
            return None

    def fake_driver(*args, **kwargs):
        barrier.wait(timeout=2)
        calls.append("driver")
        return DummyDriver()

    monkeypatch.setattr(neo4j_integration.GraphDatabase, "driver", fake_driver)

    results: list[object] = []

    def worker():
        results.append(neo4j_integration.get_neo4j_driver())

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=2)

    assert len(calls) == 1
    assert len(results) == 3
    assert results[0] is results[1] is results[2]
