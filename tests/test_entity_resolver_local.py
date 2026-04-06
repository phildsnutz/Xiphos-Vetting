import os
import sys
from contextlib import contextmanager


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


import entity_resolver  # type: ignore  # noqa: E402
import knowledge_graph  # type: ignore  # noqa: E402


class _FakeRows:
    def fetchall(self):
        return []


class _RecordingConn:
    def __init__(self):
        self.queries: list[str] = []

    def execute(self, query, params):
        self.queries.append(str(query))
        return _FakeRows()


def test_graph_memory_search_casts_aliases_to_text_for_postgres_compat(monkeypatch):
    recorder = _RecordingConn()

    @contextmanager
    def _fake_conn():
        yield recorder

    monkeypatch.setattr(knowledge_graph, "get_kg_conn", _fake_conn)

    results = entity_resolver._search_knowledge_graph_memory("LEIA")

    assert results == []
    assert recorder.queries
    assert "CAST(COALESCE(e.aliases, '[]') AS TEXT)" in recorder.queries[0]
