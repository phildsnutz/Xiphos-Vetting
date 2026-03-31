"""
Unit tests for network_risk.py

Covers:
  - Helper functions (_get_neighbors, _classify_risk, _get_primary_entity, etc.)
  - Score capping at MAX_MODIFIER_POINTS
  - Empty/missing data handling
  - CRITICAL: _get_all_vendor_scores reads from DB columns (not JSON)
  - CRITICAL: _map_entities_to_vendors uses context manager correctly
  - Integration: compute_network_risk with mocked KG and DB
"""

import os
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from collections import namedtuple
from contextlib import contextmanager

# ---------------------------------------------------------------------------
# Setup path and stubs
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_temp_dir = tempfile.mkdtemp()
_temp_kg_path = os.path.join(_temp_dir, "test_kg.db")
_temp_db_path = os.path.join(_temp_dir, "test_xiphos.db")
_temp_sanctions_path = os.path.join(_temp_dir, "test_sanctions.db")
os.environ["XIPHOS_KG_DB_PATH"] = _temp_kg_path
os.environ["XIPHOS_DB_PATH"] = _temp_db_path
os.environ["XIPHOS_SANCTIONS_DB"] = _temp_sanctions_path
os.environ["XIPHOS_DATA_DIR"] = _temp_dir

# Stub entity_resolution
try:
    from entity_resolution import ResolvedEntity
except ImportError:
    ResolvedEntity = namedtuple("ResolvedEntity", [
        "id", "canonical_name", "entity_type", "aliases",
        "identifiers", "country", "sources", "confidence",
    ])
    sys.modules["entity_resolution"] = type(sys)("entity_resolution")
    sys.modules["entity_resolution"].ResolvedEntity = ResolvedEntity

import network_risk as nr


class TestGetNeighbors(unittest.TestCase):
    """Test the _get_neighbors helper for bidirectional traversal."""

    def test_outgoing_edge(self):
        rels = [{"source_entity_id": "A", "target_entity_id": "B",
                 "rel_type": "subsidiary_of", "confidence": 0.9}]
        result = nr._get_neighbors("A", rels)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], ("B", "subsidiary_of", 0.9, "outgoing"))

    def test_incoming_edge(self):
        rels = [{"source_entity_id": "A", "target_entity_id": "B",
                 "rel_type": "subsidiary_of", "confidence": 0.9}]
        result = nr._get_neighbors("B", rels)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], ("A", "subsidiary_of", 0.9, "incoming"))

    def test_bidirectional_discovery(self):
        """Entity at center of star should find all neighbors."""
        rels = [
            {"source_entity_id": "center", "target_entity_id": "out1",
             "rel_type": "contracts_with", "confidence": 0.8},
            {"source_entity_id": "in1", "target_entity_id": "center",
             "rel_type": "subsidiary_of", "confidence": 0.9},
            {"source_entity_id": "in2", "target_entity_id": "center",
             "rel_type": "subcontractor_of", "confidence": 0.7},
        ]
        result = nr._get_neighbors("center", rels)
        neighbor_ids = {r[0] for r in result}
        self.assertEqual(neighbor_ids, {"out1", "in1", "in2"})

    def test_no_neighbors(self):
        rels = [{"source_entity_id": "X", "target_entity_id": "Y",
                 "rel_type": "related_entity", "confidence": 0.5}]
        result = nr._get_neighbors("Z", rels)
        self.assertEqual(result, [])

    def test_self_loop_handled(self):
        """A self-loop (A->A) hits the if/elif: only the outgoing branch fires."""
        rels = [{"source_entity_id": "A", "target_entity_id": "A",
                 "rel_type": "alias_of", "confidence": 0.99}]
        result = nr._get_neighbors("A", rels)
        # Uses if/elif, so only the first matching branch (outgoing) fires
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][3], "outgoing")


class TestClassifyRisk(unittest.TestCase):

    def test_zero_modifier_is_none(self):
        self.assertEqual(nr._classify_risk(0.0, []), "none")

    def test_negative_modifier_is_none(self):
        self.assertEqual(nr._classify_risk(-1.0, [{"risk_score_pct": 50}]), "none")

    def test_low_risk(self):
        self.assertEqual(nr._classify_risk(0.5, [{"risk_score_pct": 10}]), "low")

    def test_medium_risk(self):
        self.assertEqual(nr._classify_risk(1.5, [{"risk_score_pct": 10}]), "medium")

    def test_high_risk_by_modifier(self):
        self.assertEqual(nr._classify_risk(2.5, [{"risk_score_pct": 10}]), "high")

    def test_high_risk_by_neighbor_score(self):
        self.assertEqual(nr._classify_risk(0.5, [{"risk_score_pct": 30}]), "high")

    def test_critical_risk_by_modifier(self):
        self.assertEqual(nr._classify_risk(4.5, [{"risk_score_pct": 10}]), "critical")

    def test_critical_risk_by_neighbor_score(self):
        self.assertEqual(nr._classify_risk(0.5, [{"risk_score_pct": 50}]), "critical")


class TestGetPrimaryEntity(unittest.TestCase):

    def test_selects_highest_confidence_company(self):
        entities = [
            ResolvedEntity(id="e1", canonical_name="A", entity_type="company",
                           aliases=[], identifiers={}, country="US", sources=[], confidence=0.7),
            ResolvedEntity(id="e2", canonical_name="B", entity_type="company",
                           aliases=[], identifiers={}, country="US", sources=[], confidence=0.95),
            ResolvedEntity(id="e3", canonical_name="C", entity_type="person",
                           aliases=[], identifiers={}, country="US", sources=[], confidence=0.99),
        ]
        result = nr._get_primary_entity(entities)
        self.assertEqual(result.id, "e2")

    def test_falls_back_to_first_when_no_companies(self):
        entities = [
            ResolvedEntity(id="e1", canonical_name="Person A", entity_type="person",
                           aliases=[], identifiers={}, country="US", sources=[], confidence=0.9),
        ]
        result = nr._get_primary_entity(entities)
        self.assertEqual(result.id, "e1")

    def test_empty_list_returns_none(self):
        self.assertIsNone(nr._get_primary_entity([]))


class TestEmptyResult(unittest.TestCase):

    def test_structure(self):
        result = nr._empty_result("v-123", "test reason")
        self.assertEqual(result["vendor_id"], "v-123")
        self.assertEqual(result["network_risk_score"], 0.0)
        self.assertEqual(result["network_risk_level"], "none")
        self.assertEqual(result["note"], "test reason")
        self.assertEqual(result["neighbor_count"], 0)


class TestGetAllVendorScores(unittest.TestCase):
    """CRITICAL: Validates that scores are read from DB columns, not JSON."""

    def setUp(self):
        if os.path.exists(_temp_db_path):
            os.remove(_temp_db_path)
        conn = sqlite3.connect(_temp_db_path)
        conn.execute("""
            CREATE TABLE scoring_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id TEXT,
                calibrated_probability REAL,
                calibrated_tier TEXT,
                composite_score INTEGER,
                is_hard_stop BOOLEAN,
                full_result TEXT,
                scored_at TEXT
            )
        """)
        # Insert test data: two scores for same vendor (should pick latest by id)
        conn.execute("""
            INSERT INTO scoring_results
            (vendor_id, calibrated_probability, calibrated_tier, composite_score, is_hard_stop, full_result)
            VALUES ('v-001', 0.18, 'TIER_4_CLEAR', 22, 0, '{}')
        """)
        conn.execute("""
            INSERT INTO scoring_results
            (vendor_id, calibrated_probability, calibrated_tier, composite_score, is_hard_stop, full_result)
            VALUES ('v-001', 1.0, 'TIER_1_DISQUALIFIED', 100, 1, '{}')
        """)
        conn.execute("""
            INSERT INTO scoring_results
            (vendor_id, calibrated_probability, calibrated_tier, composite_score, is_hard_stop, full_result)
            VALUES ('v-002', 0.05, 'TIER_4_CLEAR', 8, 0, '{}')
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        if os.path.exists(_temp_db_path):
            os.remove(_temp_db_path)

    def test_reads_latest_score_per_vendor(self):
        """Should pick the row with highest id per vendor (latest score)."""
        mock_db = MagicMock()
        mock_db.get_db_path.return_value = _temp_db_path
        scores = nr._get_all_vendor_scores(mock_db)
        # v-001 should have the LATEST score (id=2)
        self.assertEqual(scores["v-001"]["calibrated_probability"], 1.0)
        self.assertEqual(scores["v-001"]["calibrated_tier"], "TIER_1_DISQUALIFIED")
        self.assertTrue(scores["v-001"]["is_hard_stop"])
        # v-002 should be present
        self.assertAlmostEqual(scores["v-002"]["calibrated_probability"], 0.05)

    def test_reads_from_columns_not_json(self):
        """The function must read calibrated_probability from the column, not from full_result JSON."""
        # Insert a row where full_result JSON has WRONG probability but column is correct
        conn = sqlite3.connect(_temp_db_path)
        conn.execute("""
            INSERT INTO scoring_results
            (vendor_id, calibrated_probability, calibrated_tier, composite_score, is_hard_stop, full_result)
            VALUES ('v-003', 0.75, 'TIER_2_ELEVATED', 60, 0,
                    '{"calibrated_probability": 0.10}')
        """)
        conn.commit()
        conn.close()

        mock_db = MagicMock()
        mock_db.get_db_path.return_value = _temp_db_path
        scores = nr._get_all_vendor_scores(mock_db)
        # Should read 0.75 from column, NOT 0.10 from JSON
        self.assertAlmostEqual(scores["v-003"]["calibrated_probability"], 0.75)

    def test_uses_db_context_manager_for_postgres_mode(self):
        """PostgreSQL mode should read via db_mod.get_conn() instead of opening a SQLite path directly."""
        @contextmanager
        def fake_get_conn():
            conn = sqlite3.connect(_temp_db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

        mock_db = MagicMock()
        mock_db.get_conn = fake_get_conn
        mock_db.get_db_path.side_effect = AssertionError("sqlite path should not be used in postgres mode")

        with patch.dict(os.environ, {"HELIOS_DB_ENGINE": "postgres"}, clear=False):
            scores = nr._get_all_vendor_scores(mock_db)

        self.assertEqual(scores["v-001"]["calibrated_tier"], "TIER_1_DISQUALIFIED")
        self.assertIn("v-002", scores)

    def test_fallback_on_db_error(self):
        """If direct SQL fails, should fall back to db_mod.list_vendors()."""
        mock_db = MagicMock()
        mock_db.get_db_path.return_value = "/nonexistent/path.db"
        mock_db.list_vendors.return_value = [{"id": "v-fallback"}]
        mock_db.get_latest_score.return_value = {"calibrated_probability": 0.5}
        scores = nr._get_all_vendor_scores(mock_db)
        self.assertIn("v-fallback", scores)
        mock_db.list_vendors.assert_called_once()


class TestMapEntitiesToVendors(unittest.TestCase):
    """CRITICAL: Validates context manager usage (was broken before patch)."""

    def setUp(self):
        # Use knowledge_graph's own API so we respect the actual schema
        import knowledge_graph as kg_mod
        self.kg_mod = kg_mod
        kg_mod.init_kg_db()
        entity = ResolvedEntity(id="e-1", canonical_name="Test", entity_type="company",
                                aliases=[], identifiers={}, country="US", sources=["test"], confidence=0.9)
        kg_mod.save_entity(entity)
        kg_mod.link_entity_to_vendor("e-1", "v-001")
        kg_mod.link_entity_to_vendor("e-1", "v-002")

    def tearDown(self):
        self.kg_mod.delete_entity("e-1")
        self.kg_mod.clear_vendor_links("v-001")
        self.kg_mod.clear_vendor_links("v-002")

    def test_maps_entity_to_vendor_ids(self):
        """Should return {entity_id: [vendor_ids]} using context manager."""
        entities = {"e-1": {"canonical_name": "Test"}}
        result = nr._map_entities_to_vendors(self.kg_mod, entities)
        self.assertIn("e-1", result)
        self.assertIn("v-001", result["e-1"])
        self.assertIn("v-002", result["e-1"])

    def test_missing_entity_returns_empty(self):
        entities = {"e-nonexistent": {"canonical_name": "Ghost"}}
        result = nr._map_entities_to_vendors(self.kg_mod, entities)
        self.assertNotIn("e-nonexistent", result)


class TestComputeNetworkRiskIntegration(unittest.TestCase):
    """Integration test: compute_network_risk with mocked modules."""

    def _build_mock_kg(self, entities, network, vendor_entities):
        mock = MagicMock()
        mock.init_kg_db.return_value = None
        mock.get_vendor_entities.return_value = vendor_entities

        mock.get_entity_network.return_value = network

        # Mock get_kg_conn as a context manager
        @contextmanager
        def fake_conn():
            conn = sqlite3.connect(":memory:")
            conn.execute("""
                CREATE TABLE kg_entity_vendors (
                    entity_id TEXT, vendor_id TEXT
                )
            """)
            yield conn
            conn.close()

        mock.get_kg_conn = fake_conn
        return mock

    def _build_mock_db(self, scores):
        mock = MagicMock()
        mock.get_db_path.return_value = ":memory:"
        mock.list_vendors.return_value = []
        mock.get_latest_score.return_value = None
        return mock

    @patch.object(nr, "_safe_import_kg")
    @patch.object(nr, "_safe_import_db")
    @patch.object(nr, "_get_all_vendor_scores")
    @patch.object(nr, "_map_entities_to_vendors")
    def test_basic_risk_propagation(self, mock_map, mock_scores, mock_db, mock_kg):
        """A vendor with a high-risk neighbor should get a positive network risk score."""
        primary = ResolvedEntity("e-primary", "Primary Corp", "company",
                                 [], {}, "US", [], 0.95)
        mock_kg.return_value = self._build_mock_kg(
            entities={},
            network={
                "entities": {
                    "e-primary": {"canonical_name": "Primary Corp"},
                    "e-neighbor": {"canonical_name": "Bad Neighbor Inc"},
                },
                "relationships": [
                    {
                        "source_entity_id": "e-primary",
                        "target_entity_id": "e-neighbor",
                        "rel_type": "subsidiary_of",
                        "confidence": 0.90,
                        "corroboration_count": 2,
                        "last_seen_at": "2026-03-28T12:00:00Z",
                        "claim_records": [
                            {
                                "evidence_records": [
                                    {
                                        "authority_level": "official_registry",
                                        "url": "https://example.test/subsidiary",
                                    }
                                ]
                            }
                        ],
                    },
                ],
            },
            vendor_entities=[primary],
        )
        mock_db.return_value = MagicMock()
        mock_scores.return_value = {
            "v-neighbor": {
                "calibrated_probability": 0.80,  # 80% risk
                "calibrated_tier": "TIER_1_DISQUALIFIED",
                "composite_score": 90,
                "is_hard_stop": True,
            }
        }
        mock_map.return_value = {"e-neighbor": ["v-neighbor"]}

        result = nr.compute_network_risk("v-primary")
        self.assertGreater(result["network_risk_score"], 0,
                           "Vendor with high-risk subsidiary neighbor should have positive network risk")
        self.assertIn(result["network_risk_level"], ["medium", "high", "critical"])
        self.assertEqual(result["propagation_model"], "empirical_bayes_edge_intelligence_v1")

    @patch.object(nr, "_safe_import_kg")
    @patch.object(nr, "_safe_import_db")
    @patch.object(nr, "_get_all_vendor_scores")
    @patch.object(nr, "_map_entities_to_vendors")
    def test_intelligence_weighted_propagation_penalizes_weak_edges(self, mock_map, mock_scores, mock_db, mock_kg):
        primary = ResolvedEntity("e-primary", "Primary Corp", "company",
                                 [], {}, "US", [], 0.95)

        def compute_for_relationship(relationship):
            mock_kg.return_value = self._build_mock_kg(
                entities={},
                network={
                    "entities": {
                        "e-primary": {"canonical_name": "Primary Corp"},
                        "e-neighbor": {"canonical_name": "Neighbor Entity"},
                    },
                    "relationships": [relationship],
                },
                vendor_entities=[primary],
            )
            mock_db.return_value = MagicMock()
            mock_scores.return_value = {
                "v-neighbor": {
                    "calibrated_probability": 0.80,
                    "calibrated_tier": "TIER_1_DISQUALIFIED",
                    "composite_score": 90,
                    "is_hard_stop": True,
                }
            }
            mock_map.return_value = {"e-neighbor": ["v-neighbor"]}
            return nr.compute_network_risk("v-primary")

        strong_result = compute_for_relationship(
            {
                "source_entity_id": "e-primary",
                "target_entity_id": "e-neighbor",
                "rel_type": "beneficially_owned_by",
                "confidence": 0.90,
                "corroboration_count": 2,
                "last_seen_at": "2026-03-28T12:00:00Z",
                "claim_records": [
                    {
                        "evidence_records": [
                            {
                                "authority_level": "official_registry",
                                "url": "https://example.test/owner",
                            }
                        ]
                    }
                ],
            }
        )
        weak_result = compute_for_relationship(
            {
                "source_entity_id": "e-primary",
                "target_entity_id": "e-neighbor",
                "rel_type": "mentioned_with",
                "confidence": 0.90,
                "descriptor_only": True,
                "legacy_unscoped": True,
                "corroboration_count": 1,
                "last_seen_at": "2026-03-28T12:00:00Z",
                "claim_records": [],
            }
        )

        self.assertGreater(strong_result["network_risk_score"], weak_result["network_risk_score"])
        self.assertEqual(weak_result["risk_contributors"], [])
        self.assertGreater(strong_result["risk_contributors"][0]["edge_strength"], 0.8)

    @patch.object(nr, "_safe_import_kg")
    @patch.object(nr, "_safe_import_db")
    @patch.object(nr, "_get_all_vendor_scores")
    @patch.object(nr, "_map_entities_to_vendors")
    def test_propagation_requires_edge_to_clear_learned_truth_threshold(self, mock_map, mock_scores, mock_db, mock_kg):
        primary = ResolvedEntity("e-primary", "Primary Corp", "company",
                                 [], {}, "US", [], 0.95)
        mock_kg.return_value = self._build_mock_kg(
            entities={},
            network={
                "entities": {
                    "e-primary": {"canonical_name": "Primary Corp"},
                    "e-neighbor": {"canonical_name": "Low Trust Neighbor"},
                },
                "relationships": [
                    {
                        "source_entity_id": "e-primary",
                        "target_entity_id": "e-neighbor",
                        "rel_type": "mentioned_with",
                        "confidence": 0.95,
                        "descriptor_only": True,
                        "legacy_unscoped": True,
                        "corroboration_count": 1,
                        "last_seen_at": "2026-03-28T12:00:00Z",
                        "claim_records": [],
                    }
                ],
            },
            vendor_entities=[primary],
        )
        mock_db.return_value = MagicMock()
        mock_scores.return_value = {
            "v-neighbor": {
                "calibrated_probability": 0.95,
                "calibrated_tier": "TIER_1_DISQUALIFIED",
                "composite_score": 99,
                "is_hard_stop": True,
            }
        }
        mock_map.return_value = {"e-neighbor": ["v-neighbor"]}

        result = nr.compute_network_risk("v-primary")

        self.assertEqual(result["network_risk_score"], 0.0)
        self.assertEqual(result["risk_contributors"], [])

    @patch.object(nr, "_safe_import_kg")
    @patch.object(nr, "_safe_import_db")
    def test_missing_modules_returns_empty(self, mock_db, mock_kg):
        mock_kg.return_value = None
        mock_db.return_value = None
        result = nr.compute_network_risk("v-test")
        self.assertEqual(result["network_risk_score"], 0.0)
        self.assertEqual(result["network_risk_level"], "none")

    @patch.object(nr, "_safe_import_kg")
    @patch.object(nr, "_safe_import_db")
    def test_no_entities_returns_empty(self, mock_db, mock_kg):
        mock_kg.return_value = MagicMock()
        mock_kg.return_value.init_kg_db.return_value = None
        mock_kg.return_value.get_vendor_entities.return_value = []
        mock_db.return_value = MagicMock()
        result = nr.compute_network_risk("v-test")
        self.assertEqual(result["network_risk_score"], 0.0)


class TestScoreCapping(unittest.TestCase):
    """Verify the +/- 5 point cap on network risk modifier."""

    def test_cap_positive(self):
        # If uncapped modifier would be 10, it should be capped at 5
        capped = max(-nr.MAX_MODIFIER_POINTS, min(nr.MAX_MODIFIER_POINTS, 10.0))
        self.assertEqual(capped, 5.0)

    def test_cap_negative(self):
        capped = max(-nr.MAX_MODIFIER_POINTS, min(nr.MAX_MODIFIER_POINTS, -10.0))
        self.assertEqual(capped, -5.0)

    def test_within_bounds_unchanged(self):
        capped = max(-nr.MAX_MODIFIER_POINTS, min(nr.MAX_MODIFIER_POINTS, 2.5))
        self.assertEqual(capped, 2.5)


class TestExtractKeyPaths(unittest.TestCase):

    def test_extracts_paths(self):
        contributions = [{
            "path": [
                {"entity_name": "Bad Corp", "rel_type": "subsidiary_of", "confidence": 0.9},
            ],
            "contribution": 1.5,
            "vendor_id": "v-bad",
            "risk_score_pct": 80,
        }]
        paths = nr._extract_key_paths(contributions)
        self.assertEqual(len(paths), 1)
        self.assertIn("Bad Corp", paths[0]["description"])

    def test_empty_paths(self):
        self.assertEqual(nr._extract_key_paths([]), [])

    def test_no_path_key_skipped(self):
        contributions = [{"contribution": 1.0}]
        paths = nr._extract_key_paths(contributions)
        self.assertEqual(len(paths), 0)


if __name__ == "__main__":
    unittest.main()
