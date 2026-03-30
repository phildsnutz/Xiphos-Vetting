import os
import sys
import types
from contextlib import contextmanager


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

fake_psycopg2 = types.ModuleType("psycopg2")
fake_pool = types.ModuleType("pool")
fake_pool.ThreadedConnectionPool = object
fake_extras = types.ModuleType("extras")
fake_extras.RealDictCursor = object
fake_psycopg2.pool = fake_pool
fake_psycopg2.extras = fake_extras
fake_psycopg2.OperationalError = Exception
sys.modules.setdefault("psycopg2", fake_psycopg2)
sys.modules.setdefault("psycopg2.pool", fake_pool)
sys.modules.setdefault("psycopg2.extras", fake_extras)

import db_postgres
from db_postgres import PgConnectionWrapper


def test_translate_sql_rewrites_insert_or_ignore():
    sql = "INSERT OR IGNORE INTO kg_entity_vendors (entity_id, vendor_id) VALUES (?, ?)"

    translated = PgConnectionWrapper._translate_sql(sql)

    assert translated == "INSERT INTO kg_entity_vendors (entity_id, vendor_id) VALUES (%s, %s) ON CONFLICT DO NOTHING"


def test_init_db_includes_provenance_kg_tables(monkeypatch):
    scripts: list[str] = []

    class FakeConn:
        def executescript(self, sql):
            scripts.append(sql)

    @contextmanager
    def fake_get_conn():
        yield FakeConn()

    monkeypatch.setattr(db_postgres, "get_conn", fake_get_conn)

    db_postgres.init_db()

    combined = "\n".join(scripts)
    assert "CREATE TABLE IF NOT EXISTS kg_claims" in combined
    assert "CREATE TABLE IF NOT EXISTS kg_evidence" in combined
    assert "CREATE TABLE IF NOT EXISTS kg_source_activities" in combined
    assert "CREATE TABLE IF NOT EXISTS kg_asserting_agents" in combined
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_evidence_unique" in combined
