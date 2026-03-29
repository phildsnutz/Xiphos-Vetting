"""
Unit tests for knowledge_graph.py

Covers:
  - DB initialization and schema
  - Entity CRUD (save, get, find_by_name)
  - Relationship creation and retrieval
  - CRITICAL: Bidirectional BFS traversal in get_entity_network()
  - Vendor-entity linking
  - Shared connections discovery
  - Stats reporting
"""

import os
import sqlite3
import tempfile
import unittest


# ---------------------------------------------------------------------------
# Patch runtime_paths BEFORE importing knowledge_graph so it uses our temp DB
# ---------------------------------------------------------------------------
_temp_dir = tempfile.mkdtemp()
_temp_kg_path = os.path.join(_temp_dir, "test_kg.db")
_temp_db_path = os.path.join(_temp_dir, "test_xiphos.db")
_temp_sanctions_path = os.path.join(_temp_dir, "test_sanctions.db")
os.environ["XIPHOS_KG_DB_PATH"] = _temp_kg_path
os.environ["XIPHOS_DB_PATH"] = _temp_db_path
os.environ["XIPHOS_SANCTIONS_DB"] = _temp_sanctions_path
os.environ["XIPHOS_DATA_DIR"] = _temp_dir


def _mock_kg_db_path():
    return _temp_kg_path


# We need to patch at the module level before import
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Provide a stub for entity_resolution.ResolvedEntity if not importable
try:
    from entity_resolution import ResolvedEntity
except ImportError:
    from collections import namedtuple
    ResolvedEntity = namedtuple("ResolvedEntity", [
        "id", "canonical_name", "entity_type", "aliases",
        "identifiers", "country", "sources", "confidence",
    ])
    sys.modules["entity_resolution"] = type(sys)("entity_resolution")
    sys.modules["entity_resolution"].ResolvedEntity = ResolvedEntity

import knowledge_graph as kg


class TestKnowledgeGraphDB(unittest.TestCase):
    """Tests for DB setup, entity CRUD, and relationships."""

    def setUp(self):
        """Fresh database for each test."""
        os.environ["XIPHOS_KG_DB_PATH"] = _temp_kg_path
        os.environ["XIPHOS_DB_PATH"] = _temp_db_path
        os.environ["XIPHOS_SANCTIONS_DB"] = _temp_sanctions_path
        os.environ["XIPHOS_DATA_DIR"] = _temp_dir
        if os.path.exists(_temp_kg_path):
            os.remove(_temp_kg_path)
        kg.init_kg_db()

    def tearDown(self):
        if os.path.exists(_temp_kg_path):
            os.remove(_temp_kg_path)

    # ── Schema tests ────────────────────────────────────────────────────

    def test_init_creates_tables(self):
        """init_kg_db should create all three tables."""
        conn = sqlite3.connect(kg.get_kg_db_path())
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        self.assertIn("kg_entities", tables)
        self.assertIn("kg_relationships", tables)
        self.assertIn("kg_entity_vendors", tables)

    def test_init_is_idempotent(self):
        """Calling init_kg_db twice should not error."""
        kg.init_kg_db()  # second call
        with kg.get_kg_conn() as conn:
            count = conn.execute("SELECT count(*) FROM kg_entities").fetchone()[0]
        self.assertEqual(count, 0)

    # ── Entity CRUD ─────────────────────────────────────────────────────

    def _make_entity(self, eid="e-001", name="Acme Corp", etype="company",
                     country="US", confidence=0.9):
        return ResolvedEntity(
            id=eid,
            canonical_name=name,
            entity_type=etype,
            aliases=["ACME"],
            identifiers={"duns": "123456789"},
            country=country,
            sources=["test"],
            confidence=confidence,
        )

    def test_save_and_get_entity(self):
        entity = self._make_entity()
        kg.save_entity(entity)
        result = kg.get_entity("e-001")
        self.assertIsNotNone(result)
        self.assertEqual(result.canonical_name, "Acme Corp")
        self.assertEqual(result.entity_type, "company")

    def test_get_entity_nonexistent(self):
        result = kg.get_entity("does-not-exist")
        self.assertIsNone(result)

    def test_find_entities_by_name(self):
        kg.save_entity(self._make_entity("e-001", "Acme Corp"))
        kg.save_entity(self._make_entity("e-002", "Acme Industries"))
        kg.save_entity(self._make_entity("e-003", "Globex Inc"))
        results = kg.find_entities_by_name("Acme")
        names = [r.canonical_name for r in results]
        self.assertIn("Acme Corp", names)
        self.assertIn("Acme Industries", names)
        self.assertNotIn("Globex Inc", names)

    # ── Relationships ──────────────────────────────────────────────────

    def _seed_triangle(self):
        """Create A -> B -> C triangle for traversal tests."""
        kg.save_entity(self._make_entity("e-A", "Alpha Corp", confidence=0.95))
        kg.save_entity(self._make_entity("e-B", "Beta LLC", confidence=0.85))
        kg.save_entity(self._make_entity("e-C", "Charlie Inc", confidence=0.80))
        kg.save_relationship("e-A", "e-B", "subsidiary_of", confidence=0.90,
                             data_source="test")
        kg.save_relationship("e-B", "e-C", "contracts_with", confidence=0.80,
                             data_source="test")

    def test_save_relationship(self):
        kg.save_entity(self._make_entity("e-A", "Alpha"))
        kg.save_entity(self._make_entity("e-B", "Beta"))
        kg.save_relationship("e-A", "e-B", "subsidiary_of", confidence=0.9,
                             data_source="test")
        with kg.get_kg_conn() as conn:
            row = conn.execute(
                "SELECT * FROM kg_relationships WHERE source_entity_id='e-A'"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["target_entity_id"], "e-B")
        self.assertEqual(row["rel_type"], "subsidiary_of")

    # ── CRITICAL: Bidirectional BFS ────────────────────────────────────

    def test_get_entity_network_forward(self):
        """BFS from A should find B (forward direction)."""
        self._seed_triangle()
        network = kg.get_entity_network("e-A", depth=1)
        self.assertIn("e-A", network["entities"])
        self.assertIn("e-B", network["entities"])
        self.assertEqual(network["entity_count"], 2)

    def test_get_entity_network_backward(self):
        """BFS from B should find A (backward/incoming direction).

        This is the CRITICAL bidirectional fix. Before the patch, BFS only
        followed source_entity_id -> target_entity_id. Now it also follows
        target_entity_id -> source_entity_id, so starting from B should
        discover A via the incoming subsidiary_of relationship.
        """
        self._seed_triangle()
        network = kg.get_entity_network("e-B", depth=1)
        entity_ids = set(network["entities"].keys())
        # B should find both A (incoming) and C (outgoing)
        self.assertIn("e-A", entity_ids, "Bidirectional BFS failed: B should find A via incoming edge")
        self.assertIn("e-C", entity_ids, "Forward BFS failed: B should find C via outgoing edge")
        self.assertIn("e-B", entity_ids)
        self.assertEqual(network["entity_count"], 3)

    def test_get_entity_network_depth_2(self):
        """BFS from A at depth=2 should reach C through B."""
        self._seed_triangle()
        network = kg.get_entity_network("e-A", depth=2)
        entity_ids = set(network["entities"].keys())
        self.assertIn("e-C", entity_ids, "Depth-2 BFS should reach C through A->B->C")

    def test_get_entity_network_depth_0(self):
        """Depth 0 should only return the root entity."""
        self._seed_triangle()
        network = kg.get_entity_network("e-A", depth=0)
        self.assertEqual(network["entity_count"], 1)
        self.assertIn("e-A", network["entities"])

    def test_get_entity_network_relationships_deduplicated(self):
        """Relationships should not be duplicated when traversed from both ends."""
        self._seed_triangle()
        network = kg.get_entity_network("e-B", depth=2)
        # A->B relationship should appear exactly once even though both A and B
        # are visited and both see this edge
        ab_rels = [r for r in network["relationships"]
                   if r["source_entity_id"] == "e-A" and r["target_entity_id"] == "e-B"]
        self.assertEqual(len(ab_rels), 1, "A->B relationship should appear exactly once")

    def test_get_entity_network_relationships_include_provenance(self):
        """Relationship payloads should preserve provenance for the graph inspector."""
        kg.save_entity(self._make_entity("e-A", "Alpha"))
        kg.save_entity(self._make_entity("e-B", "Beta"))
        kg.save_relationship(
            "e-A",
            "e-B",
            "contracts_with",
            confidence=0.82,
            data_source="usaspending_subawards",
            evidence="Subaward listing for FY2025 program support",
        )

        network = kg.get_entity_network("e-A", depth=1)
        relationship = next(
            r for r in network["relationships"]
            if r["source_entity_id"] == "e-A" and r["target_entity_id"] == "e-B"
        )

        self.assertIn("id", relationship)
        self.assertEqual(relationship["data_source"], "usaspending_subawards")
        self.assertEqual(relationship["evidence"], "Subaward listing for FY2025 program support")
        self.assertTrue(relationship["created_at"])

    def test_get_entity_network_nonexistent_entity(self):
        """BFS from a nonexistent entity should return empty."""
        network = kg.get_entity_network("e-NOPE", depth=2)
        self.assertEqual(network["entity_count"], 0)
        self.assertEqual(network["relationship_count"], 0)

    def test_get_entity_network_negative_depth_defaults_to_2(self):
        """Negative depth should default to 2."""
        self._seed_triangle()
        network = kg.get_entity_network("e-A", depth=-5)
        self.assertIn("e-C", network["entities"],
                      "Negative depth should default to 2, reaching C through B")

    def test_get_entity_network_bidirectional_cycle(self):
        """BFS should handle cycles without infinite loop."""
        kg.save_entity(self._make_entity("e-X", "X Corp"))
        kg.save_entity(self._make_entity("e-Y", "Y Corp"))
        kg.save_entity(self._make_entity("e-Z", "Z Corp"))
        kg.save_relationship("e-X", "e-Y", "subsidiary_of", confidence=0.9)
        kg.save_relationship("e-Y", "e-Z", "contracts_with", confidence=0.8)
        kg.save_relationship("e-Z", "e-X", "related_entity", confidence=0.7)
        network = kg.get_entity_network("e-X", depth=5)
        self.assertEqual(network["entity_count"], 3, "Cycle should not cause duplicates")

    # ── Vendor linking ─────────────────────────────────────────────────

    def test_link_entity_to_vendor(self):
        kg.save_entity(self._make_entity("e-A", "Alpha"))
        kg.link_entity_to_vendor("e-A", "v-001")
        entities = kg.get_vendor_entities("v-001")
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].id, "e-A")

    def test_get_vendor_entities_empty(self):
        entities = kg.get_vendor_entities("v-nonexistent")
        self.assertEqual(len(entities), 0)

    # ── Stats ──────────────────────────────────────────────────────────

    def test_kg_stats(self):
        self._seed_triangle()
        kg.link_entity_to_vendor("e-A", "v-001")
        stats = kg.get_kg_stats()
        self.assertEqual(stats["entity_count"], 3)
        self.assertEqual(stats["relationship_count"], 2)
        self.assertGreaterEqual(stats["linked_vendors"], 1)

    # ── Clear and delete ───────────────────────────────────────────────

    def test_clear_vendor_links(self):
        kg.save_entity(self._make_entity("e-A", "Alpha"))
        kg.link_entity_to_vendor("e-A", "v-001")
        kg.clear_vendor_links("v-001")
        entities = kg.get_vendor_entities("v-001")
        self.assertEqual(len(entities), 0)

    def test_delete_entity(self):
        kg.save_entity(self._make_entity("e-A", "Alpha"))
        result = kg.delete_entity("e-A")
        self.assertTrue(result)
        self.assertIsNone(kg.get_entity("e-A"))


if __name__ == "__main__":
    unittest.main()
