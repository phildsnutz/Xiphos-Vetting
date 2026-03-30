import importlib
import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_get_multi_entity_network_combines_roots_without_duplicate_relationships(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge_graph.db"))

    import knowledge_graph

    importlib.reload(knowledge_graph)
    knowledge_graph.init_kg_db()

    with knowledge_graph.get_kg_conn() as conn:
        for entity_id, name in (
            ("entity:a", "Vendor Root A"),
            ("entity:b", "Vendor Root B"),
            ("entity:c", "Shared Counterparty"),
        ):
            conn.execute(
                """
                INSERT INTO kg_entities
                (id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, last_updated, created_at)
                VALUES (?, ?, 'company', '[]', '{}', 'US', '[]', 0.9, datetime('now'), datetime('now'))
                """,
                (entity_id, name),
            )

        conn.execute(
            """
            INSERT INTO kg_relationships
            (source_entity_id, target_entity_id, rel_type, confidence, data_source, evidence, created_at)
            VALUES ('entity:a', 'entity:c', 'related_entity', 0.8, 'fixture', 'A to C', datetime('now'))
            """
        )
        conn.execute(
            """
            INSERT INTO kg_relationships
            (source_entity_id, target_entity_id, rel_type, confidence, data_source, evidence, created_at)
            VALUES ('entity:b', 'entity:c', 'related_entity', 0.8, 'fixture', 'B to C', datetime('now'))
            """
        )

    network = knowledge_graph.get_multi_entity_network(["entity:a", "entity:b"], depth=1, include_provenance=False)

    assert network["root_entity_id"] == "entity:a"
    assert network["root_entity_ids"] == ["entity:a", "entity:b"]
    assert network["entity_count"] == 3
    assert network["relationship_count"] == 2
    assert {rel["source_entity_id"] for rel in network["relationships"]} == {"entity:a", "entity:b"}


def test_get_vendor_graph_summary_prefers_multi_root_network(monkeypatch):
    import graph_ingest

    importlib.reload(graph_ingest)

    class FakeEntity:
        def __init__(self, entity_id: str):
            self.id = entity_id

    class FakeKG:
        def __init__(self):
            self.multi_root_calls = []

        def init_kg_db(self):
            return None

        def get_vendor_entities(self, vendor_id):
            return [FakeEntity("entity:a"), FakeEntity("entity:b")]

        def get_multi_entity_network(self, entity_ids, **kwargs):
            self.multi_root_calls.append((list(entity_ids), dict(kwargs)))
            return {
                "root_entity_id": "entity:a",
                "root_entity_ids": list(entity_ids),
                "entity_count": 2,
                "relationship_count": 1,
                "entities": {
                    "entity:a": {"id": "entity:a", "entity_type": "company", "canonical_name": "A"},
                    "entity:b": {"id": "entity:b", "entity_type": "company", "canonical_name": "B"},
                },
                "relationships": [
                    {
                        "source_entity_id": "entity:a",
                        "target_entity_id": "entity:b",
                        "rel_type": "related_entity",
                        "confidence": 0.8,
                        "claim_records": [],
                    }
                ],
            }

        def get_entity_network(self, *args, **kwargs):
            raise AssertionError("legacy per-root traversal should not run when multi-root traversal is available")

        def attach_relationship_provenance(self, relationships, **kwargs):
            return relationships

    fake_kg = FakeKG()
    monkeypatch.setattr(graph_ingest, "_safe_import_kg", lambda: fake_kg)
    monkeypatch.setattr(graph_ingest, "_filter_relationships_to_vendor_claims", lambda relationships, vendor_id: relationships)
    monkeypatch.setattr(graph_ingest, "_hydrate_missing_graph_entities", lambda kg, entities, rels: entities)

    summary = graph_ingest.get_vendor_graph_summary("vendor-1", depth=2)

    assert fake_kg.multi_root_calls == [
        (
            ["entity:a", "entity:b"],
            {
                "depth": 2,
                "include_provenance": False,
                "max_claim_records": 4,
                "max_evidence_records": 4,
            },
        )
    ]
    assert summary["root_entity_id"] == "entity:a"
    assert summary["root_entity_ids"] == ["entity:a", "entity:b"]
    assert summary["relationship_count"] == 1


def test_get_vendor_graph_summary_hydrates_only_vendor_scoped_relationships(monkeypatch):
    import graph_ingest

    importlib.reload(graph_ingest)

    class FakeEntity:
        def __init__(self, entity_id: str):
            self.id = entity_id

    class FakeConn:
        def execute(self, sql, params=None):
            class Cursor:
                @staticmethod
                def fetchall():
                    return [
                        {
                            "source_entity_id": "entity:a",
                            "target_entity_id": "entity:b",
                            "rel_type": "related_entity",
                            "vendor_id": "vendor-1",
                        },
                        {
                            "source_entity_id": "entity:a",
                            "target_entity_id": "entity:c",
                            "rel_type": "related_entity",
                            "vendor_id": "vendor-other",
                        },
                    ]

            return Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeKG:
        def __init__(self):
            self.hydrated_relationship_counts = []

        def init_kg_db(self):
            return None

        def get_vendor_entities(self, vendor_id):
            return [FakeEntity("entity:a")]

        def get_multi_entity_network(self, entity_ids, **kwargs):
            return {
                "root_entity_id": "entity:a",
                "root_entity_ids": list(entity_ids),
                "entities": {
                    "entity:a": {"id": "entity:a", "entity_type": "company", "canonical_name": "A"},
                    "entity:b": {"id": "entity:b", "entity_type": "company", "canonical_name": "B"},
                    "entity:c": {"id": "entity:c", "entity_type": "company", "canonical_name": "C"},
                },
                "relationships": [
                    {
                        "source_entity_id": "entity:a",
                        "target_entity_id": "entity:b",
                        "rel_type": "related_entity",
                        "confidence": 0.8,
                        "data_sources": [],
                        "evidence_snippets": [],
                    },
                    {
                        "source_entity_id": "entity:a",
                        "target_entity_id": "entity:c",
                        "rel_type": "related_entity",
                        "confidence": 0.8,
                        "data_sources": [],
                        "evidence_snippets": [],
                    },
                ],
            }

        def get_kg_conn(self):
            return FakeConn()

        def attach_relationship_provenance(self, relationships, **kwargs):
            self.hydrated_relationship_counts.append(len(relationships))
            for rel in relationships:
                rel["claim_records"] = [
                    {
                        "vendor_id": "vendor-1",
                        "data_source": "fixture",
                        "first_observed_at": "2026-03-29T00:00:00Z",
                        "last_observed_at": "2026-03-29T00:00:00Z",
                        "evidence_records": [],
                    }
                ]
            return relationships

    fake_kg = FakeKG()
    monkeypatch.setattr(graph_ingest, "_safe_import_kg", lambda: fake_kg)
    monkeypatch.setattr(graph_ingest, "_hydrate_missing_graph_entities", lambda kg, entities, rels: entities)

    summary = graph_ingest.get_vendor_graph_summary("vendor-1", depth=2)

    assert fake_kg.hydrated_relationship_counts == [1]
    assert summary["relationship_count"] == 1
    assert summary["relationships"][0]["target_entity_id"] == "entity:b"


def test_get_vendor_entities_uses_batched_entity_and_relationship_queries(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge_graph.db"))

    import knowledge_graph

    importlib.reload(knowledge_graph)
    knowledge_graph.init_kg_db()

    with knowledge_graph.get_kg_conn() as conn:
        for entity_id, name in (("entity:a", "A"), ("entity:b", "B")):
            conn.execute(
                """
                INSERT INTO kg_entities
                (id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, last_updated, created_at)
                VALUES (?, ?, 'company', '[]', '{}', 'US', '[]', 0.9, datetime('now'), datetime('now'))
                """,
                (entity_id, name),
            )
            conn.execute(
                "INSERT INTO kg_entity_vendors (entity_id, vendor_id) VALUES (?, 'vendor-1')",
                (entity_id,),
            )
        conn.execute(
            """
            INSERT INTO kg_relationships
            (source_entity_id, target_entity_id, rel_type, confidence, data_source, evidence, created_at)
            VALUES ('entity:a', 'entity:b', 'related_entity', 0.8, 'fixture', 'A to B', datetime('now'))
            """
        )

    entities = knowledge_graph.get_vendor_entities("vendor-1")

    assert [entity.id for entity in entities] == ["entity:a", "entity:b"]
    assert len(entities[0].relationships) == 1
    assert entities[0].relationships[0]["target_entity_id"] == "entity:b"
    assert entities[1].relationships == []


def test_map_entities_to_vendors_batches_lookup():
    import network_risk

    importlib.reload(network_risk)

    queries = []

    class FakeCursor:
        def fetchall(self):
            return [
                {"entity_id": "entity:a", "vendor_id": "vendor-a"},
                {"entity_id": "entity:c", "vendor_id": "vendor-c"},
            ]

    class FakeConn:
        def execute(self, sql, params):
            queries.append((sql, tuple(params)))
            return FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeKG:
        def get_kg_conn(self):
            return FakeConn()

    mapping = network_risk._map_entities_to_vendors(
        FakeKG(),
        {
            "entity:a": {},
            "entity:b": {},
            "entity:c": {},
        },
    )

    assert len(queries) == 1
    assert "IN (" in queries[0][0]
    assert queries[0][1] == ("entity:a", "entity:b", "entity:c")
    assert mapping == {
        "entity:a": ["vendor-a"],
        "entity:c": ["vendor-c"],
    }


def test_compute_network_risk_uses_topology_only_graph(monkeypatch):
    import network_risk

    importlib.reload(network_risk)

    class FakeEntity:
        def __init__(self):
            self.id = "entity:vendor"
            self.entity_type = "company"
            self.confidence = 0.95

    class FakeKG:
        def init_kg_db(self):
            return None

        def get_vendor_entities(self, vendor_id):
            return [FakeEntity()]

        def get_entity_network(self, entity_id, depth=2, **kwargs):
            assert kwargs.get("include_provenance") is False
            return {
                "entities": {
                    "entity:vendor": {"canonical_name": "Vendor"},
                    "entity:neighbor": {"canonical_name": "Neighbor"},
                },
                "relationships": [
                    {
                        "source_entity_id": "entity:vendor",
                        "target_entity_id": "entity:neighbor",
                        "rel_type": "owned_by",
                        "confidence": 0.9,
                    }
                ],
            }

        def get_kg_conn(self):
            class DummyConn:
                def execute(self, sql, params):
                    class DummyCursor:
                        def fetchall(self):
                            return [{"entity_id": "entity:neighbor", "vendor_id": "vendor-neighbor"}]
                    return DummyCursor()

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            return DummyConn()

    class FakeDB:
        @staticmethod
        def get_conn():
            raise AssertionError("postgres path should not be used in this test")

        @staticmethod
        def list_vendors(limit=10000):
            return []

    monkeypatch.setattr(network_risk, "_safe_import_kg", lambda: FakeKG())
    monkeypatch.setattr(network_risk, "_safe_import_db", lambda: FakeDB())
    monkeypatch.setattr(
        network_risk,
        "_get_all_vendor_scores",
        lambda db_mod: {
            "vendor-neighbor": {
                "calibrated_probability": 0.6,
                "calibrated_tier": "TIER_3_CONDITIONAL",
                "composite_score": 0.5,
                "is_hard_stop": False,
            }
        },
    )

    result = network_risk.compute_network_risk("vendor-root")

    assert result["neighbor_count"] == 1
    assert result["network_risk_level"] == "critical"
