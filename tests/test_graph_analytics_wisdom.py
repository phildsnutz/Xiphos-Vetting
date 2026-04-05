import os
import sys
from collections import defaultdict


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from graph_analytics import GraphAnalytics  # type: ignore  # noqa: E402


def _build_loaded_graph() -> GraphAnalytics:
    analytics = GraphAnalytics()
    analytics.nodes = {
        "a": {"canonical_name": "Alpha Controls", "entity_type": "company"},
        "b": {"canonical_name": "Bridge Integrator", "entity_type": "company"},
        "c": {"canonical_name": "Co-Mention Noise", "entity_type": "company"},
        "s": {"canonical_name": "OFAC Entry", "entity_type": "sanctions_list"},
    }
    analytics.edges = [
        {
            "source": "a",
            "target": "b",
            "rel_type": "beneficially_owned_by",
            "confidence": 0.9,
            "intelligence_score": 0.95,
            "primary_edge_family": "ownership_control",
            "created_at": "",
        },
        {
            "source": "b",
            "target": "c",
            "rel_type": "mentioned_with",
            "confidence": 0.95,
            "intelligence_score": 0.12,
            "primary_edge_family": "identity_and_alias",
            "created_at": "",
        },
        {
            "source": "s",
            "target": "a",
            "rel_type": "sanctioned_on",
            "confidence": 0.9,
            "intelligence_score": 0.92,
            "primary_edge_family": "sanctions_and_legal",
            "created_at": "",
        },
    ]
    analytics.adj = defaultdict(
        list,
        {
            "a": [("b", 0), ("s", 2)],
            "b": [("a", 0), ("c", 1)],
            "c": [("b", 1)],
            "s": [("a", 2)],
        },
    )
    analytics.loaded = True
    return analytics


def test_graph_analytics_uses_edge_intelligence_for_weighted_degree_and_importance():
    analytics = _build_loaded_graph()

    degree = analytics.compute_degree_centrality()
    closeness = analytics.compute_closeness_centrality()
    centrality = analytics.compute_all_centrality()

    assert degree["a"]["weighted_degree"] > degree["b"]["weighted_degree"] > degree["c"]["weighted_degree"]
    assert closeness["a"]["closeness"] > closeness["c"]["closeness"]
    assert closeness["b"]["closeness"] > closeness["c"]["closeness"]
    assert centrality["a"]["local_edge_intelligence"] > centrality["b"]["local_edge_intelligence"] > centrality["c"]["local_edge_intelligence"]
    assert centrality["a"]["structural_importance"] > centrality["c"]["structural_importance"]
    assert centrality["a"]["decision_importance"] > centrality["b"]["decision_importance"] > centrality["c"]["decision_importance"]
    assert centrality["a"]["composite_importance"] == centrality["a"]["decision_importance"]


def test_graph_analytics_sanctions_exposure_ignores_weak_noise_paths():
    analytics = _build_loaded_graph()

    exposure = analytics.compute_sanctions_exposure()

    assert exposure["a"]["risk_level"] in {"HIGH", "CRITICAL"}
    assert exposure["b"]["exposure_score"] > 0.0
    assert exposure["c"]["risk_level"] == "CLEAR"


def test_graph_analytics_targeted_sanctions_exposure_matches_requested_entities():
    analytics = _build_loaded_graph()

    targeted = analytics.compute_targeted_sanctions_exposure(["a", "b", "c"])

    assert set(targeted.keys()) == {"a", "b", "c"}
    assert targeted["a"]["risk_level"] in {"HIGH", "CRITICAL"}
    assert targeted["b"]["exposure_score"] > 0.0
    assert targeted["c"]["risk_level"] == "CLEAR"


def test_graph_analytics_mission_importance_changes_with_focus_and_context():
    analytics = _build_loaded_graph()

    default_centrality = analytics.compute_all_centrality()
    mission_centrality = analytics.compute_all_centrality(
        mission_context={
            "focus_entity_ids": ["c"],
            "criticality": "mission_critical",
            "subsystem": "Co-Mention Noise",
        }
    )

    assert default_centrality["a"]["decision_importance"] > default_centrality["c"]["decision_importance"]
    assert mission_centrality["c"]["focus_proximity"] == 1.0
    assert mission_centrality["c"]["contextual_relevance"] == 1.0
    assert mission_centrality["c"]["mission_importance"] > mission_centrality["a"]["mission_importance"]
