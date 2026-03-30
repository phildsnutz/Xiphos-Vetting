import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import knowledge_graph


def test_json_loads_accepts_native_postgres_jsonb_values():
    assert knowledge_graph._json_loads(["a", "b"], []) == ["a", "b"]
    assert knowledge_graph._json_loads({"lei": "123"}, {}) == {"lei": "123"}
    assert knowledge_graph._json_loads(None, []) == []


def test_save_relationship_uses_portable_confidence_upsert(monkeypatch):
    executed_sql: list[str] = []

    class FakeCursor:
        def __init__(self, lastrowid=1, row=None):
            self.lastrowid = lastrowid
            self._row = row
            self.rowcount = 1

        def fetchone(self):
            return self._row

        def fetchall(self):
            return []

    class FakeConn:
        def execute(self, sql, params=()):
            executed_sql.append(sql)
            normalized = " ".join(sql.split())
            if normalized.startswith("INSERT INTO kg_relationships") or normalized.startswith(
                "INSERT OR IGNORE INTO kg_relationships"
            ):
                return FakeCursor(lastrowid=1)
            return FakeCursor(lastrowid=0)

    @contextmanager
    def fake_get_kg_conn():
        yield FakeConn()

    monkeypatch.setattr(knowledge_graph, "get_kg_conn", fake_get_kg_conn)

    relationship_id = knowledge_graph.save_relationship(
        "ent-source",
        "ent-target",
        "depends_on_service",
        confidence=0.83,
        data_source="fixture",
        evidence="Service dependency from fixture",
        structured_fields={"authority_level": "analyst_curated_fixture"},
    )

    assert relationship_id == 1
    assert any(
        "WHEN excluded.confidence > kg_claims.confidence THEN excluded.confidence" in sql
        for sql in executed_sql
    )


def test_claim_record_queries_do_not_sort_timestamps_against_empty_strings():
    executed_sql: list[str] = []

    class FakeCursor:
        def fetchall(self):
            return []

    class FakeConn:
        def execute(self, sql, params=()):
            executed_sql.append(sql)
            return FakeCursor()

    knowledge_graph._fetch_claim_records_for_relationship(FakeConn(), "source", "target", "owned_by")
    knowledge_graph._fetch_claim_records_for_relationships(
        FakeConn(),
        [{"source_entity_id": "source", "target_entity_id": "target", "rel_type": "owned_by"}],
    )

    assert executed_sql
    assert all("COALESCE(e.observed_at, '')" not in sql for sql in executed_sql)
    assert all(
        "COALESCE(e.observed_at, c.last_observed_at, c.observed_at, c.updated_at) DESC" in sql
        for sql in executed_sql
    )


def test_retract_invalid_public_html_relationships_removes_legacy_bad_claims(monkeypatch, tmp_path):
    kg_path = tmp_path / "kg.sqlite"
    monkeypatch.setattr(knowledge_graph, "_use_postgres_kg", lambda: False)
    monkeypatch.setattr(knowledge_graph, "resolve_kg_db_path", lambda: str(kg_path))

    @contextmanager
    def fake_get_kg_conn():
        conn = sqlite3.connect(str(kg_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.create_function("GREATEST", 2, lambda a, b: max(a, b))
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(knowledge_graph, "get_kg_conn", fake_get_kg_conn)

    knowledge_graph.init_kg_db()

    source = knowledge_graph.ResolvedEntity(
        id="entity:test-source",
        canonical_name="Northern Channel Partners",
        entity_type="company",
        aliases=[],
        identifiers={},
        country="US",
        relationships=[],
        sources=["fixture"],
        confidence=0.9,
        last_updated=datetime.utcnow().isoformat() + "Z",
    )
    good_target = knowledge_graph.ResolvedEntity(
        id="holding_company:good",
        canonical_name="Unresolved Holding Layer 1 for Northern Channel Partners",
        entity_type="holding_company",
        aliases=[],
        identifiers={},
        country="US",
        relationships=[],
        sources=["fixture"],
        confidence=0.8,
        last_updated=datetime.utcnow().isoformat() + "Z",
    )
    bad_geo = knowledge_graph.ResolvedEntity(
        id="holding_company:ohio",
        canonical_name="Ohio",
        entity_type="holding_company",
        aliases=[],
        identifiers={},
        country="US",
        relationships=[],
        sources=["fixture"],
        confidence=0.7,
        last_updated=datetime.utcnow().isoformat() + "Z",
    )
    bad_terms = knowledge_graph.ResolvedEntity(
        id="holding_company:terms",
        canonical_name="Specific Terms",
        entity_type="holding_company",
        aliases=[],
        identifiers={},
        country="",
        relationships=[],
        sources=["fixture"],
        confidence=0.7,
        last_updated=datetime.utcnow().isoformat() + "Z",
    )
    for entity in (source, good_target, bad_geo, bad_terms):
        knowledge_graph.save_entity(entity)

    knowledge_graph.save_relationship(
        source.id,
        good_target.id,
        "owned_by",
        confidence=0.72,
        data_source="case_input_model",
        evidence="Case input models one unresolved holding layer.",
        vendor_id="c-live",
    )
    knowledge_graph.save_relationship(
        source.id,
        bad_geo.id,
        "owned_by",
        confidence=0.7,
        data_source="public_html_ownership",
        evidence="I grew up in a very poor part of Ohio and learned early how to work hard.",
        vendor_id="c-old-geo",
    )
    knowledge_graph.save_relationship(
        source.id,
        bad_terms.id,
        "owned_by",
        confidence=0.7,
        data_source="public_html_ownership",
        evidence='The FAQs are an integral part of the Specific Terms and Conditions of Sale.',
        vendor_id="c-old-terms",
    )

    prune_stats = knowledge_graph.retract_invalid_public_html_relationships(source.id)

    assert prune_stats == {"claims_deleted": 2, "relationships_deleted": 2}

    with knowledge_graph.get_kg_conn() as conn:
        remaining_relationships = conn.execute(
            """
            SELECT target_entity_id, rel_type, data_source
            FROM kg_relationships
            WHERE source_entity_id = ?
            ORDER BY target_entity_id
            """,
            (source.id,),
        ).fetchall()
        remaining_claims = conn.execute(
            """
            SELECT target_entity_id, rel_type, data_source
            FROM kg_claims
            WHERE source_entity_id = ?
            ORDER BY target_entity_id
            """,
            (source.id,),
        ).fetchall()

    assert [(row["target_entity_id"], row["rel_type"], row["data_source"]) for row in remaining_relationships] == [
        ("holding_company:good", "owned_by", "case_input_model"),
    ]
    assert [(row["target_entity_id"], row["rel_type"], row["data_source"]) for row in remaining_claims] == [
        ("holding_company:good", "owned_by", "case_input_model"),
    ]
