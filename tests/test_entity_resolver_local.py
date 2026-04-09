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


def test_resolve_entity_merges_graph_memory_for_exact_memory_anchor(monkeypatch):
    monkeypatch.setattr(
        entity_resolver,
        "_search_local_vendor_memory",
        lambda text: [
            {
                "legal_name": "PARSONS CORPORATION",
                "local_vendor_id": "case-parsons",
                "source": "local_vendor_memory",
                "confidence": 0.99,
                "country": "US",
            }
        ],
    )
    graph_lookup = {"called": False}

    def _fake_graph_memory(_text):
        graph_lookup["called"] = True
        return [
            {
                "legal_name": "PARSONS CORPORATION",
                "graph_entity_id": "kg-parsons",
                "source": "knowledge_graph",
                "confidence": 0.985,
                "country": "US",
                "graph_relationship_count": 4,
            }
        ]

    monkeypatch.setattr(entity_resolver, "_search_knowledge_graph_memory", _fake_graph_memory)

    def _should_not_run(*args, **kwargs):
        raise AssertionError("external registry fanout should be skipped for exact memory anchors")

    monkeypatch.setattr(entity_resolver, "_search_sec_edgar", _should_not_run)
    monkeypatch.setattr(entity_resolver, "_search_gleif", _should_not_run)
    monkeypatch.setattr(entity_resolver, "_search_opencorporates", _should_not_run)
    monkeypatch.setattr(entity_resolver, "_search_wikidata", _should_not_run)
    attached = {"candidates": None}

    def _attach(candidates):
        attached["candidates"] = candidates
        return candidates

    monkeypatch.setattr(entity_resolver, "_attach_graph_candidate_relationships", _attach)

    results = entity_resolver.resolve_entity("Parsons")

    assert graph_lookup["called"] is True
    assert len(results) == 1
    assert results[0]["legal_name"] == "PARSONS CORPORATION"
    assert results[0]["graph_entity_id"] == "kg-parsons"
    assert "knowledge_graph" in str(results[0]["source"])
    assert attached["candidates"] is not None
