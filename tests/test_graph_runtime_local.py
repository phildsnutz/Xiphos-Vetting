import importlib
import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_warm_cached_graph_analytics_primes_shared_runtime(monkeypatch):
    graph_runtime = importlib.import_module("graph_runtime")
    graph_runtime.reset_cached_graph_analytics()
    monkeypatch.setattr(graph_runtime, "get_graph_snapshot_signature", lambda: "snapshot-1")

    class StubAnalytics:
        def __init__(self):
            self.loaded = False
            self.calls = []

        def load_graph(self, limit=50000):
            self.loaded = True
            self.calls.append(("load_graph", limit))

        def compute_all_centrality(self):
            self.calls.append("centrality")
            return {"n-1": {}}

        def detect_communities(self):
            self.calls.append("communities")
            return {"count": 0}

        def compute_sanctions_exposure(self):
            self.calls.append("sanctions")
            return {}

        def compute_temporal_profile(self):
            self.calls.append("temporal")
            return {"timeline": []}

    result = graph_runtime.warm_cached_graph_analytics(analytics_factory=StubAnalytics)

    assert result["status"] == "ready"
    analytics = graph_runtime.load_cached_graph_analytics(analytics_factory=StubAnalytics)
    assert analytics.loaded is True
    assert ("load_graph", 50000) in analytics.calls
    assert "centrality" in analytics.calls
    assert "communities" in analytics.calls
    assert "sanctions" in analytics.calls
    assert "temporal" in analytics.calls

    status = graph_runtime.get_graph_runtime_status()
    assert status["status"] == "ready"
    assert status["loaded"] is True
