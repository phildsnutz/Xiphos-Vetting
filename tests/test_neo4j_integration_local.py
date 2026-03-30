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

        def close(self):
            return None

    class DummyDriver:
        def session(self, **kwargs):
            captured.setdefault("session_kwargs", []).append(kwargs)
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
    assert captured["session_kwargs"] == [{}]
    assert any(":Component" in cypher for cypher, _ in runs)
    assert any(":Subsystem" in cypher for cypher, _ in runs)
    assert any(":HoldingCompany" in cypher for cypher, _ in runs)


def test_get_neo4j_database_prefers_explicit_env_and_then_aura_user(monkeypatch):
    import neo4j_integration

    importlib.reload(neo4j_integration)

    monkeypatch.delenv("NEO4J_DATABASE", raising=False)
    monkeypatch.setenv("NEO4J_USER", "8479bb89")
    assert neo4j_integration.get_neo4j_database() == "8479bb89"

    monkeypatch.setenv("NEO4J_DATABASE", "helios")
    assert neo4j_integration.get_neo4j_database() == "helios"

    monkeypatch.delenv("NEO4J_DATABASE", raising=False)
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    assert neo4j_integration.get_neo4j_database() is None


def test_is_neo4j_available_uses_explicit_database(monkeypatch):
    import neo4j_integration

    importlib.reload(neo4j_integration)

    monkeypatch.setenv("NEO4J_URI", "bolt://example")
    monkeypatch.setenv("NEO4J_USER", "8479bb89")
    monkeypatch.setenv("NEO4J_DATABASE", "8479bb89")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")

    captured: dict[str, object] = {}

    class DummyResult:
        @staticmethod
        def single():
            return {"ok": 1}

    class DummySession:
        def __init__(self, **kwargs):
            captured["session_kwargs"] = kwargs

        def run(self, cypher, **kwargs):
            captured["cypher"] = cypher
            return DummyResult()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyDriver:
        def session(self, **kwargs):
            return DummySession(**kwargs)

        def close(self):
            return None

    monkeypatch.setattr(neo4j_integration.GraphDatabase, "driver", lambda *args, **kwargs: DummyDriver())

    assert neo4j_integration.is_neo4j_available() is True
    assert captured["session_kwargs"] == {"database": "8479bb89"}
    assert captured["cypher"] == "RETURN 1 AS ok"


def test_get_neo4j_driver_initializes_once_under_concurrency(monkeypatch):
    import neo4j_integration

    importlib.reload(neo4j_integration)

    monkeypatch.setenv("NEO4J_URI", "bolt://example")
    monkeypatch.setenv("NEO4J_USER", "8479bb89")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")

    barrier = threading.Barrier(2)
    calls: list[str] = []
    session_kwargs: list[dict[str, object]] = []

    class DummyDriver:
        def session(self, **kwargs):
            session_kwargs.append(kwargs)

            class DummySession:
                @staticmethod
                def run(*args, **kwargs):
                    class DummyResult:
                        @staticmethod
                        def single():
                            return {"ok": 1}

                    return DummyResult()

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            return DummySession()

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
    assert session_kwargs == [{"database": "8479bb89"}]


def test_get_graph_stats_neo4j_returns_counts(monkeypatch):
    import neo4j_integration

    importlib.reload(neo4j_integration)

    class DummyResult:
        def __init__(self, rows):
            self.rows = rows

        def __iter__(self):
            return iter(self.rows)

        def single(self):
            return self.rows[0] if self.rows else None

    class DummySession:
        def run(self, cypher, **kwargs):
            if "RETURN label, count(*) as count" in cypher:
                return DummyResult(
                    [
                        {"label": "Company", "count": 2},
                        {"label": "Person", "count": 1},
                    ]
                )
            if "RETURN type(r) as rel_type, count(r) as count" in cypher:
                return DummyResult(
                    [
                        {"rel_type": "OWNED_BY", "count": 2},
                        {"rel_type": "OFFICER_OF", "count": 1},
                    ]
                )
            if "RETURN count(n) as total_nodes" in cypher:
                return DummyResult([{"total_nodes": 3}])
            raise AssertionError(f"unexpected cypher: {cypher}")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def close(self):
            return None

    class DummyDriver:
        def session(self, **kwargs):
            return DummySession()

    monkeypatch.setattr(neo4j_integration, "get_neo4j_driver", lambda: DummyDriver())

    stats = neo4j_integration.get_graph_stats_neo4j()

    assert stats == {
        "node_count": 3,
        "relationship_count": 3,
        "node_types": {"Company": 2, "Person": 1},
        "relationship_types": {"OWNED_BY": 2, "OFFICER_OF": 1},
    }


def test_sync_relationships_preserves_relationship_identity(monkeypatch):
    import neo4j_integration

    importlib.reload(neo4j_integration)

    captured: dict[str, object] = {}

    class DummySession:
        def run(self, cypher, **kwargs):
            captured.setdefault("runs", []).append((cypher, kwargs))

            class Result:
                @staticmethod
                def single():
                    return {"count": len(kwargs["rels"])}

            return Result()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def close(self):
            return None

    class DummyDriver:
        def session(self, **kwargs):
            return DummySession()

    monkeypatch.setattr(neo4j_integration, "get_neo4j_driver", lambda: DummyDriver())

    result = neo4j_integration.sync_relationships_to_neo4j(
        [
            {
                "id": 101,
                "source_entity_id": "entity:a",
                "target_entity_id": "entity:b",
                "rel_type": "owned_by",
                "confidence": 0.9,
                "data_source": "source_a",
                "evidence": "row a",
                "created_at": "2026-03-29T00:00:00Z",
            },
            {
                "id": 102,
                "source_entity_id": "entity:a",
                "target_entity_id": "entity:b",
                "rel_type": "owned_by",
                "confidence": 0.8,
                "data_source": "source_b",
                "evidence": "row b",
                "created_at": "2026-03-29T01:00:00Z",
            },
        ]
    )

    assert result["synced_count"] == 2
    cypher, kwargs = captured["runs"][0]
    assert "MERGE (source)-[r:OWNED_BY {kg_id: rel.kg_id}]->(target)" in cypher
    assert kwargs["rels"][0]["kg_id"] == "101"
    assert kwargs["rels"][1]["kg_id"] == "102"


def test_sync_entities_chunks_large_batches(monkeypatch):
    import neo4j_integration

    importlib.reload(neo4j_integration)
    monkeypatch.setattr(neo4j_integration, "NEO4J_ENTITY_BATCH_SIZE", 1)

    captured: dict[str, object] = {}

    class DummySession:
        def run(self, cypher, **kwargs):
            captured.setdefault("runs", []).append(kwargs["entities"])

            class Result:
                @staticmethod
                def single():
                    return {"count": len(kwargs["entities"])}

            return Result()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def close(self):
            return None

    class DummyDriver:
        def session(self, **kwargs):
            return DummySession()

    monkeypatch.setattr(neo4j_integration, "get_neo4j_driver", lambda: DummyDriver())

    result = neo4j_integration.sync_entities_to_neo4j(
        [
            {"id": "company:a", "canonical_name": "A", "entity_type": "company", "aliases": [], "identifiers": {}, "country": "US", "sources": [], "confidence": 0.9, "risk_level": "low", "sanctions_exposure": 0.0, "created_at": "2026-03-29T00:00:00Z"},
            {"id": "company:b", "canonical_name": "B", "entity_type": "company", "aliases": [], "identifiers": {}, "country": "US", "sources": [], "confidence": 0.9, "risk_level": "low", "sanctions_exposure": 0.0, "created_at": "2026-03-29T00:00:00Z"},
        ]
    )

    assert result["synced_count"] == 2
    assert len(captured["runs"]) == 2
    assert captured["runs"][0][0]["id"] == "company:a"
    assert captured["runs"][1][0]["id"] == "company:b"


def test_sync_relationships_chunks_large_batches(monkeypatch):
    import neo4j_integration

    importlib.reload(neo4j_integration)
    monkeypatch.setattr(neo4j_integration, "NEO4J_REL_BATCH_SIZE", 1)

    captured: dict[str, object] = {}

    class DummySession:
        def run(self, cypher, **kwargs):
            captured.setdefault("runs", []).append(kwargs["rels"])

            class Result:
                @staticmethod
                def single():
                    return {"count": len(kwargs["rels"])}

            return Result()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def close(self):
            return None

    class DummyDriver:
        def session(self, **kwargs):
            return DummySession()

    monkeypatch.setattr(neo4j_integration, "get_neo4j_driver", lambda: DummyDriver())

    result = neo4j_integration.sync_relationships_to_neo4j(
        [
            {
                "id": 201,
                "source_entity_id": "entity:a",
                "target_entity_id": "entity:b",
                "rel_type": "subcontractor_of",
                "confidence": 0.9,
                "data_source": "source_a",
                "evidence": "row a",
                "created_at": "2026-03-29T00:00:00Z",
            },
            {
                "id": 202,
                "source_entity_id": "entity:a",
                "target_entity_id": "entity:c",
                "rel_type": "subcontractor_of",
                "confidence": 0.8,
                "data_source": "source_b",
                "evidence": "row b",
                "created_at": "2026-03-29T01:00:00Z",
            },
        ]
    )

    assert result["synced_count"] == 2
    assert len(captured["runs"]) == 2
    assert captured["runs"][0][0]["kg_id"] == "201"
    assert captured["runs"][1][0]["kg_id"] == "202"


def test_sync_relationships_uses_type_specific_batch_size_override(monkeypatch):
    import neo4j_integration

    importlib.reload(neo4j_integration)
    monkeypatch.setattr(neo4j_integration, "NEO4J_REL_BATCH_SIZE", 10)
    monkeypatch.setattr(neo4j_integration, "_REL_BATCH_SIZE_OVERRIDES", {"FILED_WITH": 2})

    captured: dict[str, object] = {}

    class DummySession:
        def run(self, cypher, **kwargs):
            captured.setdefault("runs", []).append(kwargs["rels"])

            class Result:
                @staticmethod
                def single():
                    return {"count": len(kwargs["rels"])}

            return Result()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def close(self):
            return None

    class DummyDriver:
        def session(self, **kwargs):
            return DummySession()

    monkeypatch.setattr(neo4j_integration, "get_neo4j_driver", lambda: DummyDriver())

    result = neo4j_integration.sync_relationships_to_neo4j(
        [
            {
                "id": 401,
                "source_entity_id": "entity:a",
                "target_entity_id": "entity:b",
                "rel_type": "filed_with",
                "confidence": 0.9,
                "data_source": "source_a",
                "evidence": "row a",
                "created_at": "2026-03-29T00:00:00Z",
            },
            {
                "id": 402,
                "source_entity_id": "entity:c",
                "target_entity_id": "entity:d",
                "rel_type": "filed_with",
                "confidence": 0.8,
                "data_source": "source_b",
                "evidence": "row b",
                "created_at": "2026-03-29T01:00:00Z",
            },
            {
                "id": 403,
                "source_entity_id": "entity:e",
                "target_entity_id": "entity:f",
                "rel_type": "filed_with",
                "confidence": 0.7,
                "data_source": "source_c",
                "evidence": "row c",
                "created_at": "2026-03-29T02:00:00Z",
            },
        ]
    )

    assert result["synced_count"] == 3
    assert len(captured["runs"]) == 2
    assert len(captured["runs"][0]) == 2
    assert len(captured["runs"][1]) == 1


def test_sync_relationships_recovers_from_deadlock_by_falling_back_to_serial_writes(monkeypatch):
    import neo4j_integration

    importlib.reload(neo4j_integration)
    monkeypatch.setattr(neo4j_integration, "NEO4J_REL_BATCH_SIZE", 2)

    captured: dict[str, object] = {"calls": []}

    class DeadlockError(Exception):
        code = "Neo.TransientError.Transaction.DeadlockDetected"

    class DummySession:
        def run(self, cypher, **kwargs):
            captured["calls"].append(kwargs)
            rels = kwargs.get("rels")
            if rels is not None:
                if len(rels) > 1:
                    raise DeadlockError("deadlock")

                class Result:
                    @staticmethod
                    def single():
                        return {"count": len(rels)}

                return Result()

            rel = kwargs["rel"]

            class Result:
                @staticmethod
                def single():
                    return {"count": 1 if rel else 0}

            return Result()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def close(self):
            return None

    class DummyDriver:
        def session(self, **kwargs):
            return DummySession()

    monkeypatch.setattr(neo4j_integration, "get_neo4j_driver", lambda: DummyDriver())

    result = neo4j_integration.sync_relationships_to_neo4j(
        [
            {
                "id": 301,
                "source_entity_id": "entity:a",
                "target_entity_id": "entity:b",
                "rel_type": "subcontractor_of",
                "confidence": 0.9,
                "data_source": "source_a",
                "evidence": "row a",
                "created_at": "2026-03-29T00:00:00Z",
            },
            {
                "id": 302,
                "source_entity_id": "entity:a",
                "target_entity_id": "entity:c",
                "rel_type": "subcontractor_of",
                "confidence": 0.8,
                "data_source": "source_b",
                "evidence": "row b",
                "created_at": "2026-03-29T01:00:00Z",
            },
        ]
    )

    assert result["synced_count"] == 2
    assert result["failed_count"] == 0
    assert len(captured["calls"]) == 3
    assert len(captured["calls"][0]["rels"]) == 2
    assert captured["calls"][1]["rel"]["kg_id"] == "301"
    assert captured["calls"][2]["rel"]["kg_id"] == "302"


def test_full_sync_clears_relationships_before_resync(tmp_path, monkeypatch):
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

    calls: list[str] = []
    monkeypatch.setattr(neo4j_integration, "sync_entities_to_neo4j", lambda rows: calls.append("entities") or {"synced_count": len(rows), "failed_count": 0, "duration_ms": 1})
    monkeypatch.setattr(neo4j_integration, "clear_neo4j_relationships", lambda: calls.append("clear") or {"deleted_count": 9, "duration_ms": 1})
    monkeypatch.setattr(neo4j_integration, "sync_relationships_to_neo4j", lambda rows: calls.append("relationships") or {"synced_count": len(rows), "failed_count": 0, "duration_ms": 1})

    result = neo4j_integration.full_sync_from_postgres()

    assert result["entities_synced"] == 1
    assert result["relationships_synced"] == 0
    assert calls == ["entities", "clear", "relationships"]
