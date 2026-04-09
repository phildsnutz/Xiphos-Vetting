import importlib
import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload_module(name: str):
    if name in sys.modules:
        return importlib.reload(sys.modules[name])
    return importlib.import_module(name)


def test_axiom_ingest_writes_entities_and_relationships_on_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    knowledge_graph = _reload_module("knowledge_graph")
    axiom_agent = _reload_module("axiom_agent")

    knowledge_graph.init_kg_db()

    result = axiom_agent.AgentResult(
        target=axiom_agent.SearchTarget(prime_contractor="Parsons Corporation"),
        entities=[
            axiom_agent.DiscoveredEntity(
                name="Parsons Corporation",
                entity_type="company",
                confidence=0.91,
                attributes={"ticker": "PSN"},
            ),
            axiom_agent.DiscoveredEntity(
                name="Carey Smith",
                entity_type="person",
                confidence=0.77,
                attributes={"role": "chair_ceo"},
            ),
        ],
        relationships=[
            axiom_agent.DiscoveredRelationship(
                source_entity="Carey Smith",
                target_entity="Parsons Corporation",
                rel_type="officer_of",
                confidence=0.84,
                evidence=["SEC filing"],
            )
        ],
    )

    summary = axiom_agent.ingest_agent_result(result, vendor_id="case-parsons")

    assert summary["entities_created"] >= 2
    assert summary["relationships_created"] == 1

    with knowledge_graph.get_kg_conn() as conn:
        entity_count = conn.execute("SELECT COUNT(*) FROM kg_entities").fetchone()[0]
        relationship_row = conn.execute(
            """
            SELECT rel_type, source_entity_id, target_entity_id
            FROM kg_relationships
            WHERE rel_type = 'officer_of'
            """
        ).fetchone()

    assert entity_count >= 2
    assert relationship_row is not None
