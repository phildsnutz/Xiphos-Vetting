"""
Graph Analytics Engine for Helios Knowledge Graph

World-class graph analytics inspired by Palantir Gotham, Sayari Graph,
and i2 Analyst's Notebook patterns. Provides centrality metrics, community
detection, path analysis, temporal analysis, and risk propagation scoring
that transform the knowledge graph from a data store into an intelligence
platform.

Algorithms implemented:
  1. Centrality Analysis
     - Degree centrality (connection count, weighted)
     - Betweenness centrality (bridge detection)
     - Closeness centrality (information access speed)
     - PageRank (influence propagation)

  2. Community Detection
     - Label propagation (fast, scalable)
     - Modularity-based grouping

  3. Path Analysis
     - Shortest path (BFS)
     - All paths up to k hops
     - Critical path (highest confidence route)

  4. Temporal Analysis
     - Entity/relationship timeline
     - Activity windows and dormancy detection
     - Burst detection (sudden relationship formation)

  5. Risk Propagation
     - Multi-hop cascade with decay
     - Sanctions contamination scoring
     - Network exposure index

Usage:
    from graph_analytics import GraphAnalytics
    analytics = GraphAnalytics()
    centrality = analytics.compute_centrality()
    communities = analytics.detect_communities()
    path = analytics.shortest_path(entity_a, entity_b)
"""

import heapq
import logging
import math
import sys
import threading
from collections import defaultdict, deque
from datetime import datetime
from typing import Optional

from graph_ingest import annotate_graph_relationship_intelligence

try:
    import networkx as nx
    from networkx.algorithms import community as nx_community
except ImportError:  # pragma: no cover
    nx = None
    nx_community = None

_matplotlib_import_blocked = False
if "matplotlib" not in sys.modules:
    # python-igraph eagerly touches drawing imports. In our runtime, an
    # incompatible matplotlib wheel can poison Leiden import even though we do
    # not render graphs server-side. Force the optional drawing path to no-op.
    sys.modules["matplotlib"] = None
    _matplotlib_import_blocked = True
try:
    import igraph as ig
    import leidenalg
except ImportError:  # pragma: no cover
    ig = None
    leidenalg = None
finally:  # pragma: no branch
    if _matplotlib_import_blocked and sys.modules.get("matplotlib") is None:
        del sys.modules["matplotlib"]

logger = logging.getLogger(__name__)

_MISSION_CRITICALITY_ORDER = (
    "supporting",
    "important",
    "high",
    "critical",
    "mission_critical",
)
_MISSION_CRITICALITY_INDEX = {label: idx for idx, label in enumerate(_MISSION_CRITICALITY_ORDER)}


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _mission_criticality_score(value: object) -> float:
    normalized = _normalize_text(value).lower().replace(" ", "_")
    if normalized in {"primary", "essential"}:
        normalized = "high"
    if normalized not in _MISSION_CRITICALITY_INDEX:
        normalized = "supporting"
    return round((_MISSION_CRITICALITY_INDEX[normalized] + 1) / len(_MISSION_CRITICALITY_ORDER), 4)


def _safe_import_kg():
    try:
        import knowledge_graph as kg
        return kg
    except ImportError:
        return None


class GraphAnalytics:
    """
    In-memory graph analytics engine.
    Loads the full graph from SQLite into adjacency structures,
    then runs algorithms on the in-memory representation.
    """

    def __init__(self):
        self.nodes = {}          # {id: {canonical_name, entity_type, confidence, country, ...}}
        self.edges = []          # [{source, target, rel_type, confidence, data_source, created_at}]
        self.adj = defaultdict(list)   # adjacency list: {id: [(neighbor_id, edge_idx), ...]}
        self.loaded = False
        self._cache_lock = threading.RLock()
        self._memo: dict[tuple, object] = {}

    def load_graph(self, limit: int = 50000) -> bool:
        """Load the full knowledge graph into memory for analysis."""
        kg = _safe_import_kg()
        if not kg:
            logger.warning("Knowledge graph module not available")
            return False

        try:
            export = kg.export_graph(limit_entities=limit)
        except Exception as e:
            logger.error(f"Failed to export graph: {e}")
            return False

        self.nodes = export.get("entities", {})
        raw_rels = export.get("relationships", [])

        self.edges = []
        self.adj = defaultdict(list)

        for i, rel in enumerate(raw_rels):
            src = rel.get("source_entity_id", "")
            tgt = rel.get("target_entity_id", "")
            if src and tgt and src in self.nodes and tgt in self.nodes:
                edge = {
                    "source": src,
                    "target": tgt,
                    "rel_type": rel.get("rel_type", ""),
                    "confidence": rel.get("confidence", 0.5),
                    "data_source": rel.get("data_source", ""),
                    "evidence": rel.get("evidence", ""),
                    "created_at": rel.get("created_at", ""),
                }
                idx = len(self.edges)
                self.edges.append(edge)
                self.adj[src].append((tgt, idx))
                self.adj[tgt].append((src, idx))  # Undirected for analytics

        self.edges = annotate_graph_relationship_intelligence(self.edges)

        self.loaded = True
        with self._cache_lock:
            self._memo = {}
        logger.info(f"Graph loaded: {len(self.nodes)} nodes, {len(self.edges)} edges")
        return True

    def _ensure_loaded(self):
        if not self.loaded:
            self.load_graph()

    def _memoized(self, key: tuple, loader):
        with self._cache_lock:
            cached = self._memo.get(key)
        if cached is not None:
            return cached
        value = loader()
        with self._cache_lock:
            self._memo[key] = value
        return value

    def _edge_strength(self, edge: dict) -> float:
        return max(
            0.0,
            min(
                float(
                    edge.get("learned_truth_probability")
                    or edge.get("intelligence_score")
                    or edge.get("confidence")
                    or 0.0
                ),
                1.0,
            ),
        )

    def _node_local_edge_strength(self, entity_id: str) -> float:
        neighbors = self.adj.get(entity_id, [])
        if not neighbors:
            return 0.0
        total = sum(self._edge_strength(self.edges[eidx]) for _, eidx in neighbors)
        return total / len(neighbors)

    def _edge_distance(self, edge: dict) -> float:
        return 1.0 / max(self._edge_strength(edge), 1e-6)

    def _interrogation_degree_row(self, entity_id: str) -> dict:
        neighbors = self.adj.get(entity_id, [])
        n = len(self.nodes)
        degree = len(neighbors)
        weighted = sum(self._edge_strength(self.edges[eidx]) for _, eidx in neighbors)
        avg_edge_strength = (weighted / degree) if degree else 0.0
        normalized = degree / max(n - 1, 1) if n > 1 else 0.0
        weighted_normalized = min(1.0, (normalized * 0.55) + (avg_edge_strength * 0.45))
        return {
            "degree": degree,
            "weighted_degree": round(weighted, 4),
            "normalized": round(normalized, 4),
            "weighted_normalized": round(weighted_normalized, 4),
        }

    def _interrogation_bridge_row(self, entity_id: str) -> dict:
        neighbors = [neighbor for neighbor, _ in self.adj.get(entity_id, [])]
        if len(neighbors) <= 1:
            return {"betweenness": 0.0, "normalized": 0.0}

        neighbor_sets: list[set[str]] = []
        two_hop_reach: set[str] = set()
        for neighbor in neighbors[:24]:
            reach = {candidate for candidate, _ in self.adj.get(neighbor, []) if candidate != entity_id}
            neighbor_sets.append(reach)
            two_hop_reach.update(reach)

        pair_count = 0
        total_overlap = 0.0
        for index, left in enumerate(neighbor_sets):
            for right in neighbor_sets[index + 1 :]:
                union = left | right
                overlap = (len(left & right) / len(union)) if union else 0.0
                total_overlap += overlap
                pair_count += 1

        avg_overlap = (total_overlap / pair_count) if pair_count else 0.0
        reach_ratio = len(two_hop_reach - set(neighbors) - {entity_id}) / max(len(self.nodes) - 1, 1)
        bridge_score = min(1.0, max(0.0, ((1.0 - avg_overlap) * 0.72) + (reach_ratio * 0.28)))
        return {
            "betweenness": round(bridge_score, 4),
            "normalized": round(bridge_score, 4),
        }

    def _interrogation_influence_row(self, entity_id: str, *, degree_score: float, closeness_score: float) -> dict:
        neighbors = [neighbor for neighbor, _ in self.adj.get(entity_id, [])]
        if not neighbors:
            return {"pagerank": 0.0, "normalized": 0.0}

        second_hop: set[str] = set()
        neighbor_intelligence: list[float] = []
        for neighbor in neighbors[:32]:
            second_hop.update(candidate for candidate, _ in self.adj.get(neighbor, []) if candidate != entity_id)
            neighbor_intelligence.append(self._node_local_edge_strength(neighbor))

        second_hop_ratio = len(second_hop - {entity_id}) / max(len(self.nodes) - 1, 1)
        neighbor_score = (sum(neighbor_intelligence) / len(neighbor_intelligence)) if neighbor_intelligence else 0.0
        influence = min(
            1.0,
            max(
                0.0,
                (degree_score * 0.38)
                + (closeness_score * 0.27)
                + (second_hop_ratio * 0.2)
                + (neighbor_score * 0.15),
            ),
        )
        return {
            "pagerank": round(influence, 6),
            "normalized": round(influence, 4),
        }

    def _mission_focus_proximity(self, focus_entity_ids: list[str]) -> dict[str, float]:
        if not focus_entity_ids:
            return {nid: 1.0 for nid in self.nodes}

        min_distance = {nid: float("inf") for nid in self.nodes}
        for focus_id in focus_entity_ids:
            if focus_id not in self.nodes:
                continue
            _, _, _, distances = self._weighted_shortest_path_tree(focus_id)
            for nid, distance in distances.items():
                min_distance[nid] = min(min_distance.get(nid, float("inf")), distance)

        proximity: dict[str, float] = {}
        for nid in self.nodes:
            distance = min_distance.get(nid, float("inf"))
            if math.isinf(distance):
                proximity[nid] = 0.0
            else:
                proximity[nid] = round(1.0 / (1.0 + max(distance, 0.0)), 4)
        return proximity

    def _node_contextual_relevance(self, node: dict, mission_context: dict[str, object] | None) -> float:
        if not isinstance(mission_context, dict):
            return 1.0

        tokens = [
            _normalize_text(mission_context.get("role")).lower(),
            _normalize_text(mission_context.get("subsystem")).lower(),
            _normalize_text(mission_context.get("site")).lower(),
        ]
        tokens = [token for token in tokens if token]
        if not tokens:
            return 1.0

        haystack = " ".join(
            [
                _normalize_text(node.get("canonical_name")).lower(),
                _normalize_text(node.get("entity_type")).lower(),
            ]
        )
        matched = sum(1 for token in tokens if token in haystack)
        return round(matched / len(tokens), 4) if tokens else 1.0

    def _weighted_shortest_path_tree(self, source_id: str) -> tuple[list[str], dict[str, list[str]], dict[str, float], dict[str, float]]:
        stack: list[str] = []
        predecessors: dict[str, list[str]] = defaultdict(list)
        path_counts: dict[str, float] = defaultdict(float)
        path_counts[source_id] = 1.0
        distances: dict[str, float] = {source_id: 0.0}
        heap: list[tuple[float, str]] = [(0.0, source_id)]

        while heap:
            current_distance, current = heapq.heappop(heap)
            if current_distance > distances.get(current, float("inf")) + 1e-12:
                continue
            stack.append(current)
            for neighbor, eidx in self.adj.get(current, []):
                edge_distance = self._edge_distance(self.edges[eidx])
                candidate = current_distance + edge_distance
                neighbor_distance = distances.get(neighbor, float("inf"))
                if candidate + 1e-12 < neighbor_distance:
                    distances[neighbor] = candidate
                    heapq.heappush(heap, (candidate, neighbor))
                    path_counts[neighbor] = path_counts[current]
                    predecessors[neighbor] = [current]
                elif abs(candidate - neighbor_distance) <= 1e-12:
                    path_counts[neighbor] += path_counts[current]
                    predecessors[neighbor].append(current)

        return stack, predecessors, path_counts, distances

    # -------------------------------------------------------------------
    # 1. CENTRALITY ANALYSIS
    # -------------------------------------------------------------------

    def compute_degree_centrality(self) -> dict:
        """
        Degree centrality: number of connections per node.
        Weighted variant uses sum of edge confidences.

        Returns: {entity_id: {degree, weighted_degree, normalized}}
        """
        self._ensure_loaded()

        def _compute():
            n = len(self.nodes)
            if n == 0:
                return {}

            result = {}
            max_weighted = 0.0
            for nid in self.nodes:
                neighbors = self.adj.get(nid, [])
                degree = len(neighbors)
                weighted = sum(self._edge_strength(self.edges[eidx]) for _, eidx in neighbors)
                max_weighted = max(max_weighted, weighted)
                result[nid] = {
                    "degree": degree,
                    "weighted_degree": round(weighted, 4),
                    "normalized": round(degree / max(n - 1, 1), 4),
                }

            for nid in result:
                weighted_degree = float(result[nid]["weighted_degree"])
                result[nid]["weighted_normalized"] = round(weighted_degree / max(max_weighted, 1e-10), 4)

            return result

        return self._memoized(("degree_centrality",), _compute)

    def compute_betweenness_centrality(self, sample_size: int = 200) -> dict:
        """
        Betweenness centrality: fraction of shortest paths passing through each node.
        Uses sampling for large graphs (Brandes algorithm with node sampling).

        Identifies bridge entities that connect otherwise-disconnected clusters.
        Critical for finding shell companies, intermediaries, and brokers.
        """
        self._ensure_loaded()
        sample_key = max(1, int(sample_size or 1))

        def _compute():
            n = len(self.nodes)
            if n < 3:
                return {nid: {"betweenness": 0.0, "normalized": 0.0} for nid in self.nodes}

            betweenness = defaultdict(float)
            node_list = list(self.nodes.keys())

            # Sample source nodes for scalability
            sources = node_list[:min(sample_key, n)]

            for s in sources:
                stack, pred, sigma, _ = self._weighted_shortest_path_tree(s)
                delta = defaultdict(float)
                while stack:
                    w = stack.pop()
                    for v in pred[w]:
                        if sigma[w] > 0:
                            delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
                    if w != s:
                        betweenness[w] += delta[w]

            # Normalize
            max_b = max(betweenness.values()) if betweenness else 1.0

            result = {}
            for nid in self.nodes:
                b = betweenness.get(nid, 0.0)
                result[nid] = {
                    "betweenness": round(b, 4),
                    "normalized": round(b / max(max_b, 1e-10), 4),
                }

            return result

        return self._memoized(("betweenness_centrality", sample_key), _compute)

    def compute_closeness_centrality(self) -> dict:
        """
        Closeness centrality: inverse of average shortest path length.
        Measures how quickly information (or risk) can reach a node.

        High closeness = entity is well-connected and can quickly be
        affected by network events (sanctions cascade, news propagation).
        """
        self._ensure_loaded()

        def _compute():
            n = len(self.nodes)
            if n < 2:
                return {nid: {"closeness": 0.0, "avg_distance": 0.0} for nid in self.nodes}

            result = {}
            for nid in self.nodes:
                result[nid] = self.compute_closeness_for_entity(nid)

            return result

        return self._memoized(("closeness_centrality",), _compute)

    def compute_closeness_for_entity(self, entity_id: str) -> dict:
        """Cheap closeness calculation for a single entity during interrogation."""
        self._ensure_loaded()
        normalized_entity_id = str(entity_id or "").strip()
        if normalized_entity_id not in self.nodes:
            return {"closeness": 0.0, "avg_distance": 0.0, "reachable": 0}

        def _compute():
            n = len(self.nodes)
            if n < 2:
                return {"closeness": 0.0, "avg_distance": 0.0, "reachable": 0}

            _, _, _, dist = self._weighted_shortest_path_tree(normalized_entity_id)
            reachable = len(dist) - 1
            if reachable == 0:
                return {"closeness": 0.0, "avg_distance": 0.0, "reachable": 0}

            total_dist = sum(dist.values())
            avg_dist = total_dist / reachable
            closeness = reachable / total_dist if total_dist > 0 else 0.0
            if reachable < n - 1:
                closeness *= (reachable / (n - 1))

            return {
                "closeness": round(closeness, 4),
                "avg_distance": round(avg_dist, 2),
                "reachable": reachable,
            }

        return self._memoized(("closeness_entity", normalized_entity_id), _compute)

    def compute_pagerank(self, damping: float = 0.85, iterations: int = 50, tol: float = 1e-6) -> dict:
        """
        PageRank: iterative influence propagation.
        Adapted for compliance: high PageRank = entity whose risk status
        disproportionately affects many others through the network.

        Uses intelligence-weighted edges for propagation strength.
        """
        self._ensure_loaded()
        cache_key = ("pagerank", round(float(damping), 4), max(1, int(iterations or 1)), float(tol))

        def _compute():
            n = len(self.nodes)
            if n == 0:
                return {}

            node_list = list(self.nodes.keys())
            rank = {nid: 1.0 / n for nid in node_list}

            for _ in range(iterations):
                new_rank = {}
                for nid in node_list:
                    incoming_sum = 0.0
                    for neighbor, eidx in self.adj.get(nid, []):
                        outgoing_edges = self.adj.get(neighbor, [])
                        outgoing_weight = sum(self._edge_strength(self.edges[out_idx]) for _, out_idx in outgoing_edges)
                        if outgoing_weight > 0:
                            weight = self._edge_strength(self.edges[eidx])
                            incoming_sum += (rank[neighbor] * weight) / outgoing_weight

                    new_rank[nid] = (1.0 - damping) / n + damping * incoming_sum

                diff = sum(abs(new_rank[nid] - rank[nid]) for nid in node_list)
                rank = new_rank
                if diff < tol:
                    break

            max_rank = max(rank.values()) if rank else 1.0
            result = {}
            for nid in node_list:
                result[nid] = {
                    "pagerank": round(rank[nid], 6),
                    "normalized": round(rank[nid] / max(max_rank, 1e-10), 4),
                }

            return result

        return self._memoized(cache_key, _compute)

    def _compose_centrality_row(
        self,
        entity_id: str,
        *,
        degree: dict,
        betweenness: dict,
        closeness: dict,
        pagerank: dict,
        mission_context: Optional[dict] = None,
    ) -> dict:
        normalized_mission_context = mission_context if isinstance(mission_context, dict) else None
        focus_entity_ids = [
            str(focus_id)
            for focus_id in ((normalized_mission_context or {}).get("focus_entity_ids") or [])
            if str(focus_id)
        ]
        focus_proximity = self._mission_focus_proximity(focus_entity_ids)
        mission_criticality = _mission_criticality_score((normalized_mission_context or {}).get("criticality"))

        d = degree.get("weighted_normalized", 0)
        b = betweenness.get("normalized", 0)
        c = closeness.get("closeness", 0)
        p = pagerank.get("normalized", 0)
        local_edge_intelligence = self._node_local_edge_strength(entity_id)
        structural_components = [d, b, c, p]
        safe_structural = [max(float(value), 1e-6) for value in structural_components]
        structural_importance = math.prod(safe_structural) ** (1.0 / len(safe_structural))
        decision_components = [structural_importance, max(float(local_edge_intelligence), 1e-6)]
        decision_importance = math.prod(decision_components) ** (1.0 / len(decision_components))
        node_focus_proximity = focus_proximity.get(entity_id, 1.0 if normalized_mission_context is None else 0.0)
        contextual_relevance = self._node_contextual_relevance(self.nodes[entity_id], normalized_mission_context)
        if normalized_mission_context is None:
            mission_importance = decision_importance
        else:
            mission_components = [
                max(float(decision_importance), 1e-6),
                max(float(node_focus_proximity), 1e-6),
                max(float(mission_criticality), 1e-6),
                max(float(contextual_relevance), 1e-6),
            ]
            mission_importance = math.prod(mission_components) ** (1.0 / len(mission_components))

        return {
            "entity_id": entity_id,
            "entity_name": self.nodes[entity_id].get("canonical_name", ""),
            "entity_type": self.nodes[entity_id].get("entity_type", ""),
            "degree": degree,
            "betweenness": betweenness,
            "closeness": closeness,
            "pagerank": pagerank,
            "local_edge_intelligence": round(local_edge_intelligence, 4),
            "structural_importance": round(structural_importance, 4),
            "decision_importance": round(decision_importance, 4),
            "focus_proximity": round(node_focus_proximity, 4),
            "contextual_relevance": round(contextual_relevance, 4),
            "mission_importance": round(mission_importance, 4),
            "composite_importance": round(decision_importance, 4),
        }

    def compute_all_centrality(self, mission_context: Optional[dict] = None) -> dict:
        """
        Compute all centrality metrics and return both structural and decision
        importance per entity.

        Structural importance answers: "how central is this node in the graph?"
        Decision importance answers: "how central is it once edge trust is
        considered?"
        """
        self._ensure_loaded()

        cache_key = (
            "all_centrality",
            tuple(sorted((mission_context or {}).get("focus_entity_ids") or [])),
            _normalize_text((mission_context or {}).get("criticality")).lower(),
            _normalize_text((mission_context or {}).get("role")).lower(),
            _normalize_text((mission_context or {}).get("subsystem")).lower(),
            _normalize_text((mission_context or {}).get("site")).lower(),
        )

        def _compute():
            degree = self.compute_degree_centrality()
            betweenness = self.compute_betweenness_centrality()
            closeness = self.compute_closeness_centrality()
            pagerank = self.compute_pagerank()
            result = {}
            for nid in self.nodes:
                result[nid] = self._compose_centrality_row(
                    nid,
                    degree=degree.get(nid, {}),
                    betweenness=betweenness.get(nid, {}),
                    closeness=closeness.get(nid, {}),
                    pagerank=pagerank.get(nid, {}),
                    mission_context=mission_context,
                )
            return result

        return self._memoized(cache_key, _compute)

    def compute_interrogation_centrality(self, entity_id: str, mission_context: Optional[dict] = None) -> dict:
        """
        Faster single-entity structural read for AXIOM interrogation.

        AXIOM needs a disciplined local topology read, not a full graph-wide
        PageRank or sampled Brandes pass every time it asks about one entity.
        Dedicated graph analytics routes still expose the heavier global
        metrics when an operator explicitly opens that room.
        """
        self._ensure_loaded()
        normalized_entity_id = str(entity_id or "").strip()
        if normalized_entity_id not in self.nodes:
            return {}

        degree = self._interrogation_degree_row(normalized_entity_id)
        closeness = self.compute_closeness_for_entity(normalized_entity_id)
        betweenness = self._interrogation_bridge_row(normalized_entity_id)
        pagerank = self._interrogation_influence_row(
            normalized_entity_id,
            degree_score=float(degree.get("weighted_normalized") or 0.0),
            closeness_score=float(closeness.get("closeness") or 0.0),
        )
        return self._compose_centrality_row(
            normalized_entity_id,
            degree=degree,
            betweenness=betweenness,
            closeness=closeness,
            pagerank=pagerank,
            mission_context=mission_context,
        )

    def _percentile_rank(self, values: list[float], current: float) -> float:
        cleaned = [float(value) for value in values if value is not None]
        if not cleaned:
            return 0.0
        below = sum(1 for value in cleaned if value < current)
        equal = sum(1 for value in cleaned if abs(value - current) <= 1e-12)
        return round((below + (equal * 0.5)) / len(cleaned), 4)

    def describe_entity_topology(self, entity_id: str, mission_context: Optional[dict] = None) -> dict:
        """
        Summarize where an entity sits in the graph without exposing raw metric
        maps. This is the AXIOM-facing topology read for Layer 1 reasoning.
        """
        self._ensure_loaded()
        normalized_entity_id = str(entity_id or "").strip()
        if normalized_entity_id not in self.nodes:
            return {}

        centrality = self.compute_interrogation_centrality(normalized_entity_id, mission_context=mission_context)
        degree_row = centrality.get("degree") if isinstance(centrality.get("degree"), dict) else {}
        betweenness_row = centrality.get("betweenness") if isinstance(centrality.get("betweenness"), dict) else {}
        pagerank_row = centrality.get("pagerank") if isinstance(centrality.get("pagerank"), dict) else {}
        degree_count = int(degree_row.get("degree") or 0)
        degree_score = float(degree_row.get("weighted_normalized") or 0.0)
        betweenness_score = float(betweenness_row.get("normalized") or 0.0)
        pagerank_score = float(pagerank_row.get("normalized") or 0.0)
        degree_percentile = round(max(0.0, min(degree_score, 1.0)), 4)
        betweenness_percentile = round(max(0.0, min(betweenness_score, 1.0)), 4)
        pagerank_percentile = round(max(0.0, min(pagerank_score, 1.0)), 4)

        role = "contextual_node"
        tags: list[str] = []
        supporting_facts: list[str] = []
        if betweenness_percentile >= 0.8 and degree_count <= 4:
            role = "gatekeeper"
            tags.extend(["bridge", "chokepoint"])
            supporting_facts.append(
                f"Betweenness is in the {int(round(betweenness_percentile * 100))}th percentile while degree stays at {degree_count}."
            )
        elif pagerank_percentile >= 0.82 and degree_percentile >= 0.6:
            role = "core_influencer"
            tags.extend(["influential", "well-connected"])
            supporting_facts.append(
                f"Influence is in the {int(round(pagerank_percentile * 100))}th percentile with above-median connectivity."
            )
        elif degree_percentile >= 0.8:
            role = "dense_hub"
            tags.extend(["hub", "high-connectivity"])
            supporting_facts.append(
                f"Connectivity is in the {int(round(degree_percentile * 100))}th percentile."
            )
        elif betweenness_percentile >= 0.72:
            role = "bridge"
            tags.extend(["bridge"])
            supporting_facts.append(
                f"Betweenness is in the {int(round(betweenness_percentile * 100))}th percentile."
            )
        elif degree_percentile <= 0.25 and pagerank_percentile <= 0.25:
            role = "peripheral"
            tags.extend(["peripheral"])
            supporting_facts.append("The entity is still sitting on the edge of the current relationship fabric.")
        else:
            supporting_facts.append("The entity is connected enough to matter, but it is not yet a dominant node in the visible graph.")

        mission_importance = float(centrality.get("mission_importance") or 0.0)
        if mission_importance >= 0.7:
            tags.append("mission-relevant")
            supporting_facts.append(
                f"Mission importance is reading {mission_importance:.2f} once the current brief context is applied."
            )

        return {
            "entity_id": normalized_entity_id,
            "role": role,
            "tags": sorted(set(tags)),
            "degree_percentile": degree_percentile,
            "betweenness_percentile": betweenness_percentile,
            "influence_percentile": pagerank_percentile,
            "degree_count": degree_count,
            "mission_importance": round(mission_importance, 4),
            "supporting_facts": supporting_facts[:4],
        }

    def compute_suspicious_absences(self, entity_id: str) -> list[dict]:
        """
        Find graph patterns that peer entities in the same community commonly
        show, but the target entity does not. This is a structural expectation
        model, not a simple transitive closure check.
        """
        self._ensure_loaded()
        normalized_entity_id = str(entity_id or "").strip()
        if normalized_entity_id not in self.nodes:
            return []

        cache_key = ("suspicious_absences", normalized_entity_id)

        def _compute():
            communities = self.detect_communities()
            community_id = str((communities.get("node_labels") or {}).get(normalized_entity_id) or "")
            community = (communities.get("communities") or {}).get(community_id) if community_id else None
            if not isinstance(community, dict):
                return []

            members = [member for member in (community.get("members") or []) if isinstance(member, dict)]
            if len(members) < 3:
                return []

            entity_type = str(self.nodes.get(normalized_entity_id, {}).get("entity_type") or "")
            same_type_peers = [
                str(member.get("id") or "")
                for member in members
                if str(member.get("id") or "")
                and str(member.get("id") or "") != normalized_entity_id
                and str(member.get("type") or "") == entity_type
            ]
            peer_ids = same_type_peers or [
                str(member.get("id") or "")
                for member in members
                if str(member.get("id") or "") and str(member.get("id") or "") != normalized_entity_id
            ]
            peer_ids = [peer_id for peer_id in peer_ids if peer_id in self.nodes]
            if len(peer_ids) < 2:
                return []

            entity_targets = set()
            entity_rel_types = set()
            for neighbor, eidx in self.adj.get(normalized_entity_id, []):
                entity_targets.add(neighbor)
                entity_rel_types.add(str(self.edges[eidx].get("rel_type") or ""))

            peer_target_support: defaultdict[str, int] = defaultdict(int)
            peer_rel_support: defaultdict[str, int] = defaultdict(int)
            for peer_id in peer_ids:
                peer_targets_seen = set()
                peer_rels_seen = set()
                for neighbor, eidx in self.adj.get(peer_id, []):
                    if neighbor in {normalized_entity_id, peer_id}:
                        continue
                    rel_type = str(self.edges[eidx].get("rel_type") or "")
                    if rel_type and rel_type not in peer_rels_seen:
                        peer_rel_support[rel_type] += 1
                        peer_rels_seen.add(rel_type)
                    if neighbor not in peer_targets_seen:
                        peer_target_support[neighbor] += 1
                        peer_targets_seen.add(neighbor)

            threshold = max(2, math.ceil(len(peer_ids) * 0.6))
            density = float(community.get("density") or 0.0)
            absences: list[dict] = []

            for target_id, support in sorted(peer_target_support.items(), key=lambda item: (-item[1], item[0])):
                if target_id in entity_targets or support < threshold:
                    continue
                support_ratio = support / max(len(peer_ids), 1)
                confidence = min(0.48 + (support_ratio * 0.25) + (density * 0.18), 0.9)
                target_node = self.nodes.get(target_id, {})
                absences.append(
                    {
                        "type": "suspicious_absence",
                        "confidence": round(confidence, 4),
                        "community_id": community_id,
                        "peer_count": len(peer_ids),
                        "support_count": int(support),
                        "expected_target_id": target_id,
                        "expected_target_name": str(target_node.get("canonical_name") or target_id),
                        "description": (
                            f"Peers in {community_id} repeatedly connect to {target_node.get('canonical_name', target_id)}, "
                            f"but {self.nodes.get(normalized_entity_id, {}).get('canonical_name', normalized_entity_id)} does not."
                        ),
                    }
                )

            for rel_type, support in sorted(peer_rel_support.items(), key=lambda item: (-item[1], item[0])):
                if rel_type in entity_rel_types or support < threshold:
                    continue
                support_ratio = support / max(len(peer_ids), 1)
                confidence = min(0.44 + (support_ratio * 0.22) + (density * 0.14), 0.84)
                absences.append(
                    {
                        "type": "missing_relationship_pattern",
                        "confidence": round(confidence, 4),
                        "community_id": community_id,
                        "peer_count": len(peer_ids),
                        "support_count": int(support),
                        "rel_type": rel_type,
                        "description": (
                            f"Peers in {community_id} commonly carry {rel_type} edges, but "
                            f"{self.nodes.get(normalized_entity_id, {}).get('canonical_name', normalized_entity_id)} does not."
                        ),
                    }
                )

            absences.sort(key=lambda item: (-float(item.get("confidence") or 0.0), str(item.get("type") or "")))
            return absences[:5]

        return self._memoized(cache_key, _compute)

    # -------------------------------------------------------------------
    # 2. COMMUNITY DETECTION
    # -------------------------------------------------------------------

    def _community_nx_graph(self):
        self._ensure_loaded()
        if nx is None:
            return None
        graph = nx.Graph()
        for nid in self.nodes:
            graph.add_node(nid)
        for edge in self.edges:
            source = edge.get("source")
            target = edge.get("target")
            if not source or not target or source == target:
                continue
            weight = self._edge_strength(edge)
            if graph.has_edge(source, target):
                graph[source][target]["weight"] += weight
            else:
                graph.add_edge(source, target, weight=weight)
        return graph

    def _finalize_community_result(self, community_members: list[set[str]], *, modularity: float, algorithm: str) -> dict:
        ordered_sets = sorted(
            [set(members) for members in community_members if members],
            key=lambda members: (-len(members), sorted(members)),
        )
        node_labels: dict[str, str] = {}
        enriched_communities: dict[str, dict] = {}

        for idx, members in enumerate(ordered_sets):
            label = f"community_{idx}"
            member_data = []
            bridge_candidates: list[dict] = []
            internal_edge_count = 0
            for mid in sorted(members):
                node = self.nodes.get(mid, {})
                member_data.append(
                    {
                        "id": mid,
                        "name": node.get("canonical_name", ""),
                        "type": node.get("entity_type", ""),
                        "confidence": node.get("confidence", 0),
                    }
                )
                node_labels[mid] = label
                neighbors = self.adj.get(mid, [])
                internal_neighbors = 0
                external_neighbors = 0
                for neighbor, eidx in neighbors:
                    if neighbor in members:
                        internal_neighbors += 1
                        if mid < neighbor:
                            internal_edge_count += 1
                    else:
                        external_neighbors += 1
                if external_neighbors:
                    bridge_candidates.append(
                        {
                            "id": mid,
                            "name": node.get("canonical_name", ""),
                            "type": node.get("entity_type", ""),
                            "cross_community_edges": external_neighbors,
                            "internal_edges": internal_neighbors,
                        }
                    )

            possible_edges = max((len(members) * (len(members) - 1)) / 2.0, 1.0)
            density = round(internal_edge_count / possible_edges, 4) if len(members) > 1 else 1.0
            bridge_candidates.sort(
                key=lambda item: (-int(item["cross_community_edges"]), -int(item["internal_edges"]), str(item["name"]))
            )
            enriched_communities[label] = {
                "members": member_data,
                "size": len(members),
                "types": sorted({self.nodes.get(m, {}).get("entity_type", "") for m in members if self.nodes.get(m)}),
                "density": density,
                "bridge_entities": bridge_candidates[:5],
            }

        return {
            "communities": enriched_communities,
            "node_labels": node_labels,
            "count": len(enriched_communities),
            "modularity": round(float(modularity or 0.0), 4),
            "algorithm": algorithm,
        }

    def _detect_communities_leiden(self) -> dict | None:
        if ig is None or leidenalg is None:
            return None
        self._ensure_loaded()
        if not self.nodes:
            return {"communities": {}, "node_labels": {}, "count": 0, "modularity": 0.0, "algorithm": "leiden"}

        node_ids = list(self.nodes.keys())
        node_index = {node_id: idx for idx, node_id in enumerate(node_ids)}
        graph = ig.Graph()
        graph.add_vertices(len(node_ids))
        graph.vs["name"] = node_ids
        edge_weights: dict[tuple[int, int], float] = defaultdict(float)
        for edge in self.edges:
            source = edge.get("source")
            target = edge.get("target")
            if source not in node_index or target not in node_index or source == target:
                continue
            left = node_index[source]
            right = node_index[target]
            key = (left, right) if left < right else (right, left)
            edge_weights[key] += self._edge_strength(edge)
        if edge_weights:
            graph.add_edges(list(edge_weights.keys()))
            graph.es["weight"] = list(edge_weights.values())
        partition = leidenalg.find_partition(
            graph,
            leidenalg.ModularityVertexPartition,
            weights=graph.es["weight"] if graph.ecount() else None,
            seed=42,
        )
        community_sets = [{node_ids[index] for index in community} for community in partition]
        return self._finalize_community_result(
            community_sets,
            modularity=float(getattr(partition, "modularity", 0.0) or 0.0),
            algorithm="leiden",
        )

    def _detect_communities_louvain(self) -> dict | None:
        if nx is None or nx_community is None or not hasattr(nx_community, "louvain_communities"):
            return None
        graph = self._community_nx_graph()
        if graph is None:
            return None
        if graph.number_of_nodes() == 0:
            return {"communities": {}, "node_labels": {}, "count": 0, "modularity": 0.0, "algorithm": "louvain"}
        communities = nx_community.louvain_communities(graph, weight="weight", seed=42)
        modularity = nx_community.modularity(graph, communities, weight="weight") if communities else 0.0
        return self._finalize_community_result([set(group) for group in communities], modularity=modularity, algorithm="louvain")

    def _detect_communities_label_propagation(self, max_iterations: int = 50) -> dict:
        """Weighted label propagation fallback when stronger community engines are unavailable."""
        self._ensure_loaded()
        if not self.nodes:
            return {"communities": {}, "node_labels": {}, "count": 0, "modularity": 0.0, "algorithm": "label_propagation"}

        # Initialize: each node is its own community
        labels = {nid: nid for nid in self.nodes}

        for iteration in range(max_iterations):
            changed = False
            node_list = list(self.nodes.keys())

            # Process in random-ish order (reverse every other iteration)
            if iteration % 2 == 1:
                node_list.reverse()

            for nid in node_list:
                neighbors = self.adj.get(nid, [])
                if not neighbors:
                    continue

                # Count weighted votes for each label
                label_weights = defaultdict(float)
                for neighbor, eidx in neighbors:
                    label = labels[neighbor]
                    weight = self._edge_strength(self.edges[eidx])
                    label_weights[label] += weight

                if label_weights:
                    best_label = max(label_weights, key=label_weights.get)
                    if best_label != labels[nid]:
                        labels[nid] = best_label
                        changed = True

            if not changed:
                break

        communities = defaultdict(set)
        for nid, label in labels.items():
            communities[label].add(nid)

        # Compute modularity (quality metric for community structure)
        m = len(self.edges) or 1
        modularity = 0.0
        for community_members in communities.values():
            member_set = set(community_members)
            for nid in community_members:
                ki = len(self.adj.get(nid, []))
                for neighbor, eidx in self.adj.get(nid, []):
                    if neighbor in member_set:
                        kj = len(self.adj.get(neighbor, []))
                        modularity += 1.0 - (ki * kj) / (2.0 * m)
        modularity /= (2.0 * m)

        return self._finalize_community_result(
            list(communities.values()),
            modularity=modularity,
            algorithm="label_propagation",
        )

    def detect_communities(self, max_iterations: int = 50, algorithm: str = "auto") -> dict:
        """
        Detect communities using the strongest available algorithm.

        Order:
          1. Leiden when `igraph` + `leidenalg` are installed
          2. NetworkX Louvain fallback
          3. Weighted label propagation fallback
        """
        requested = str(algorithm or "auto").strip().lower()

        def _compute():
            if requested in {"auto", "leiden"}:
                leiden_result = self._detect_communities_leiden()
                if leiden_result is not None:
                    return leiden_result
                if requested == "leiden":
                    logger.warning("graph_analytics: Leiden requested but igraph/leidenalg unavailable, falling back")
            if requested in {"auto", "louvain"}:
                louvain_result = self._detect_communities_louvain()
                if louvain_result is not None:
                    return louvain_result
                if requested == "louvain":
                    logger.warning("graph_analytics: Louvain requested but networkx support unavailable, falling back")
            return self._detect_communities_label_propagation(max_iterations=max_iterations)

        return self._memoized(("communities", requested, max_iterations), _compute)

    # -------------------------------------------------------------------
    # 3. PATH ANALYSIS
    # -------------------------------------------------------------------

    def shortest_path(self, source_id: str, target_id: str) -> Optional[dict]:
        """
        Find shortest path between two entities using BFS.
        Returns the path with entities, relationships, and hop count.
        """
        self._ensure_loaded()
        if source_id not in self.nodes or target_id not in self.nodes:
            return None

        # BFS
        parent = {source_id: None}
        parent_edge = {source_id: None}
        queue = deque([source_id])

        while queue:
            current = queue.popleft()
            if current == target_id:
                break

            for neighbor, eidx in self.adj.get(current, []):
                if neighbor not in parent:
                    parent[neighbor] = current
                    parent_edge[neighbor] = eidx
                    queue.append(neighbor)

        if target_id not in parent:
            return None  # No path exists

        # Reconstruct path
        path_nodes = []
        path_edges = []
        current = target_id
        while current is not None:
            path_nodes.append(current)
            if parent_edge.get(current) is not None:
                path_edges.append(self.edges[parent_edge[current]])
            current = parent.get(current)

        path_nodes.reverse()
        path_edges.reverse()

        # Compute path confidence from intelligence-weighted edges.
        path_confidence = 1.0
        for edge in path_edges:
            path_confidence *= self._edge_strength(edge)

        return {
            "source": source_id,
            "target": target_id,
            "hops": len(path_edges),
            "path_confidence": round(path_confidence, 4),
            "nodes": [
                {
                    "id": nid,
                    "name": self.nodes.get(nid, {}).get("canonical_name", ""),
                    "type": self.nodes.get(nid, {}).get("entity_type", ""),
                }
                for nid in path_nodes
            ],
            "edges": path_edges,
        }

    def critical_path(self, source_id: str, target_id: str) -> Optional[dict]:
        """
        Find the highest-confidence path between two entities.
        Uses Dijkstra with -log(edge_strength) as weight, so stronger and
        better-supported paths beat merely short ones.
        """
        self._ensure_loaded()
        if source_id not in self.nodes or target_id not in self.nodes:
            return None

        import heapq

        # Dijkstra with -log(confidence) weights
        dist = {source_id: 0.0}
        parent = {source_id: None}
        parent_edge = {source_id: None}
        heap = [(0.0, source_id)]

        while heap:
            d, current = heapq.heappop(heap)
            if current == target_id:
                break
            if d > dist.get(current, float('inf')):
                continue

            for neighbor, eidx in self.adj.get(current, []):
                conf = max(self._edge_strength(self.edges[eidx]), 0.001)
                edge_weight = -math.log(conf)
                new_dist = d + edge_weight

                if new_dist < dist.get(neighbor, float('inf')):
                    dist[neighbor] = new_dist
                    parent[neighbor] = current
                    parent_edge[neighbor] = eidx
                    heapq.heappush(heap, (new_dist, neighbor))

        if target_id not in parent:
            return None

        # Reconstruct
        path_nodes = []
        path_edges = []
        current = target_id
        while current is not None:
            path_nodes.append(current)
            if parent_edge.get(current) is not None:
                path_edges.append(self.edges[parent_edge[current]])
            current = parent.get(current)

        path_nodes.reverse()
        path_edges.reverse()

        path_confidence = math.exp(-dist[target_id]) if target_id in dist else 0.0

        return {
            "source": source_id,
            "target": target_id,
            "hops": len(path_edges),
            "path_confidence": round(path_confidence, 4),
            "algorithm": "dijkstra_max_confidence",
            "nodes": [
                {
                    "id": nid,
                    "name": self.nodes.get(nid, {}).get("canonical_name", ""),
                    "type": self.nodes.get(nid, {}).get("entity_type", ""),
                }
                for nid in path_nodes
            ],
            "edges": path_edges,
        }

    def all_paths(self, source_id: str, target_id: str, max_hops: int = 4) -> list:
        """
        Find all paths between two entities up to max_hops.
        Returns list of paths sorted by confidence (highest first).
        """
        self._ensure_loaded()
        if source_id not in self.nodes or target_id not in self.nodes:
            return []

        results = []

        def dfs(current, target, visited, path_nodes, path_edges, depth):
            if depth > max_hops:
                return
            if current == target and path_edges:
                conf = 1.0
                for e in path_edges:
                    conf *= self._edge_strength(e)
                results.append({
                    "hops": len(path_edges),
                    "path_confidence": round(conf, 4),
                    "nodes": [
                        {"id": nid, "name": self.nodes.get(nid, {}).get("canonical_name", "")}
                        for nid in path_nodes + [current]
                    ],
                    "edges": list(path_edges),
                })
                return

            visited.add(current)
            for neighbor, eidx in self.adj.get(current, []):
                if neighbor not in visited:
                    dfs(neighbor, target, visited,
                        path_nodes + [current], path_edges + [self.edges[eidx]],
                        depth + 1)
            visited.discard(current)

        dfs(source_id, target_id, set(), [], [], 0)
        results.sort(key=lambda p: p["path_confidence"], reverse=True)
        return results[:50]  # Cap at 50 paths

    # -------------------------------------------------------------------
    # 4. TEMPORAL ANALYSIS
    # -------------------------------------------------------------------

    def compute_temporal_profile(self) -> dict:
        """
        Analyze temporal patterns in entity and relationship creation.
        Detects activity bursts, dormancy periods, and growth trends.
        """
        self._ensure_loaded()

        # Parse timestamps
        edge_times = []
        for edge in self.edges:
            ts = edge.get("created_at", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00").replace("+00:00", ""))
                    edge_times.append(dt)
                except (ValueError, TypeError):
                    pass

        if not edge_times:
            return {"timeline": [], "bursts": [], "growth_rate": 0}

        edge_times.sort()

        # Monthly activity histogram
        monthly = defaultdict(int)
        for dt in edge_times:
            key = f"{dt.year}-{dt.month:02d}"
            monthly[key] += 1

        timeline = [{"month": k, "relationships_added": v} for k, v in sorted(monthly.items())]

        # Burst detection: months with > 2x average activity
        avg_activity = sum(monthly.values()) / max(len(monthly), 1)
        bursts = [
            {"month": k, "count": v, "multiplier": round(v / max(avg_activity, 1), 1)}
            for k, v in monthly.items()
            if v > 2 * avg_activity
        ]

        # Growth rate (last 3 months vs previous 3 months)
        sorted_months = sorted(monthly.keys())
        if len(sorted_months) >= 6:
            recent = sum(monthly[m] for m in sorted_months[-3:])
            previous = sum(monthly[m] for m in sorted_months[-6:-3])
            growth_rate = ((recent - previous) / max(previous, 1)) * 100
        else:
            growth_rate = 0

        return {
            "timeline": timeline,
            "bursts": bursts,
            "total_edges": len(edge_times),
            "date_range": {
                "earliest": edge_times[0].isoformat() if edge_times else None,
                "latest": edge_times[-1].isoformat() if edge_times else None,
            },
            "growth_rate_pct": round(growth_rate, 1),
        }

    # -------------------------------------------------------------------
    # 5. RISK PROPAGATION (SANCTIONS CASCADE)
    # -------------------------------------------------------------------

    def compute_sanctions_exposure(self) -> dict:
        """
        Compute sanctions exposure for every entity in the graph.
        Entities directly linked to sanctions entries get high exposure.
        Risk decays through network hops with relationship-type weighting.

        Returns: {entity_id: {exposure_score, risk_level, contributing_sanctions, path_to_nearest}}
        """
        self._ensure_loaded()

        def _compute():
            try:
                from network_risk import _hop_decay_factor, _propagation_prior
            except ImportError:
                def _hop_decay_factor(hops):
                    return 1.0 / float(hops + 1)

                def _propagation_prior(_relationship):
                    return 0.5

            sanctions_nodes = set()
            for nid, node in self.nodes.items():
                if node.get("entity_type") in ("sanctions_list", "sanctions_entry"):
                    sanctions_nodes.add(nid)

            if not sanctions_nodes:
                return {nid: {"exposure_score": 0.0, "risk_level": "CLEAR"} for nid in self.nodes}

            exposure = defaultdict(float)
            nearest_sanction = {}

            for sanction_id in sanctions_nodes:
                visited = set()
                queue = deque([(sanction_id, 1.0, 0)])

                while queue:
                    current, current_exposure, hops = queue.popleft()
                    if current in visited or hops > 4:
                        continue
                    visited.add(current)

                    if current != sanction_id:
                        exposure[current] = max(exposure[current], current_exposure)
                        if current not in nearest_sanction or current_exposure > nearest_sanction[current][1]:
                            nearest_sanction[current] = (sanction_id, current_exposure, hops)

                    for neighbor, eidx in self.adj.get(current, []):
                        if neighbor not in visited:
                            relationship = self.edges[eidx]
                            rel_weight = _propagation_prior(relationship)
                            edge_conf = self._edge_strength(relationship)
                            propagated = current_exposure * rel_weight * edge_conf * _hop_decay_factor(hops)
                            if propagated > 0.01:
                                queue.append((neighbor, propagated, hops + 1))

            result = {}
            for nid in self.nodes:
                score = exposure.get(nid, 0.0)
                if score >= 0.7:
                    level = "CRITICAL"
                elif score >= 0.4:
                    level = "HIGH"
                elif score >= 0.15:
                    level = "MEDIUM"
                elif score > 0:
                    level = "LOW"
                else:
                    level = "CLEAR"

                entry = {
                    "exposure_score": round(score, 4),
                    "risk_level": level,
                }
                if nid in nearest_sanction:
                    sid, _, hops = nearest_sanction[nid]
                    entry["nearest_sanction"] = {
                        "id": sid,
                        "name": self.nodes.get(sid, {}).get("canonical_name", ""),
                        "hops": hops,
                    }

                result[nid] = entry

            return result

        return self._memoized(("sanctions_exposure",), _compute)

    def compute_targeted_sanctions_exposure(self, entity_ids: list[str] | tuple[str, ...], max_hops: int = 4) -> dict:
        """
        Compute sanctions exposure only for the requested entities.

        This is the interrogation path. AXIOM usually needs the target entity
        and a small set of immediate neighbors, not a full graph-wide exposure
        map. We search outward from each requested entity and stop once the best
        reachable sanctions path is no longer improvable.
        """
        self._ensure_loaded()

        normalized_ids = tuple(sorted({str(entity_id or "").strip() for entity_id in (entity_ids or []) if str(entity_id or "").strip()}))
        if not normalized_ids:
            return {}

        cache_key = ("sanctions_exposure_targeted", normalized_ids, max(1, int(max_hops or 1)))

        def _compute():
            try:
                from network_risk import _hop_decay_factor, _propagation_prior
            except ImportError:
                def _hop_decay_factor(hops):
                    return 1.0 / float(hops + 1)

                def _propagation_prior(_relationship):
                    return 0.5

            sanctions_nodes = {
                nid
                for nid, node in self.nodes.items()
                if node.get("entity_type") in ("sanctions_list", "sanctions_entry")
            }
            if not sanctions_nodes:
                return {entity_id: {"exposure_score": 0.0, "risk_level": "CLEAR"} for entity_id in normalized_ids}

            def _classify(score: float) -> str:
                if score >= 0.7:
                    return "CRITICAL"
                if score >= 0.4:
                    return "HIGH"
                if score >= 0.15:
                    return "MEDIUM"
                if score > 0:
                    return "LOW"
                return "CLEAR"

            results: dict[str, dict] = {}
            for entity_id in normalized_ids:
                if entity_id not in self.nodes:
                    results[entity_id] = {"exposure_score": 0.0, "risk_level": "CLEAR"}
                    continue
                if entity_id in sanctions_nodes:
                    results[entity_id] = {
                        "exposure_score": 1.0,
                        "risk_level": "CRITICAL",
                        "nearest_sanction": {
                            "id": entity_id,
                            "name": self.nodes.get(entity_id, {}).get("canonical_name", ""),
                            "hops": 0,
                        },
                    }
                    continue

                best_score = 0.0
                best_sanction = ""
                best_hops = 0
                best_seen: dict[str, float] = {entity_id: 1.0}
                heap: list[tuple[float, int, str]] = [(-1.0, 0, entity_id)]

                while heap:
                    neg_score, hops, current = heapq.heappop(heap)
                    current_score = -neg_score
                    if current_score + 1e-12 < best_seen.get(current, 0.0):
                        continue
                    if hops > max_hops:
                        continue
                    if current in sanctions_nodes and current != entity_id:
                        if current_score > best_score:
                            best_score = current_score
                            best_sanction = current
                            best_hops = hops
                        # Further traversal from a sanctions node can only reduce
                        # the score, so this branch is done.
                        continue
                    if hops >= max_hops:
                        continue
                    if best_score > 0 and current_score <= best_score:
                        continue

                    for neighbor, eidx in self.adj.get(current, []):
                        relationship = self.edges[eidx]
                        rel_weight = _propagation_prior(relationship)
                        edge_conf = self._edge_strength(relationship)
                        propagated = current_score * rel_weight * edge_conf * _hop_decay_factor(hops)
                        if propagated <= 0.01:
                            continue
                        if propagated <= best_seen.get(neighbor, 0.0):
                            continue
                        best_seen[neighbor] = propagated
                        heapq.heappush(heap, (-propagated, hops + 1, neighbor))

                entry = {
                    "exposure_score": round(best_score, 4),
                    "risk_level": _classify(best_score),
                }
                if best_sanction:
                    entry["nearest_sanction"] = {
                        "id": best_sanction,
                        "name": self.nodes.get(best_sanction, {}).get("canonical_name", ""),
                        "hops": best_hops,
                    }
                results[entity_id] = entry

            return results

        return self._memoized(cache_key, _compute)

    # -------------------------------------------------------------------
    # 6. SUMMARY / DASHBOARD DATA
    # -------------------------------------------------------------------

    # -------------------------------------------------------------------
    # 7. PERSON-SPECIFIC ANALYTICS (S13-03)
    # -------------------------------------------------------------------

    def compute_person_centrality(self) -> dict:
        """
        Compute centrality metrics for person nodes specifically.
        Returns betweenness, degree, and PageRank for persons only.

        Returns:
            dict with structure:
            {
                "person_id": {
                    "name": str,
                    "betweenness": float,
                    "degree": int,
                    "pagerank": float,
                    "risk_neighbors": [entity_id, ...],
                }
            }
        """
        self._ensure_loaded()

        person_centrality = {}

        for nid, node in self.nodes.items():
            if node.get("entity_type") != "person":
                continue

            # Betweenness: how many shortest paths go through this person
            between = self._betweenness_centrality([nid]).get(nid, 0.0)

            # Degree: how many connections
            degree = len([x[0] for x in self.adj.get(nid, [])])

            # PageRank: influence in network
            pr_scores = self._pagerank_iter()
            pagerank = pr_scores.get(nid, 0.0)

            # Find high-risk neighbors
            risk_neighbors = []
            for neighbor_id, _ in self.adj.get(nid, []):
                neighbor = self.nodes.get(neighbor_id, {})
                neighbor_type = neighbor.get("entity_type", "")
                if neighbor_type == "sanctions_list":
                    risk_neighbors.append(neighbor_id)

            person_centrality[nid] = {
                "name": node.get("canonical_name", nid),
                "betweenness": round(between, 4),
                "degree": degree,
                "pagerank": round(pagerank, 4),
                "risk_neighbors": risk_neighbors,
            }

        return person_centrality

    def detect_person_communities(self) -> dict:
        """
        Detect person clusters: groups of persons connected through
        shared employers, nationalities, or sanctions lists.

        Returns:
            dict with structure:
            {
                "communities": {
                    "community_0": {
                        "person_ids": [id, ...],
                        "size": int,
                        "cohesion": float,
                        "connection_type": "employer" | "nationality" | "sanctions",
                    }
                },
                "total_persons": int,
            }
        """
        # Get all person nodes
        person_nodes = [nid for nid, n in self.nodes.items() if n.get("entity_type") == "person"]

        if not person_nodes:
            return {"communities": {}, "total_persons": 0}

        # Union-Find for connected components
        parent = {nid: nid for nid in person_nodes}

        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Connect persons sharing employer or nationality
        for p1_idx, p1_id in enumerate(person_nodes):
            p1_neighbors = set(n[0] for n in self.adj.get(p1_id, []))

            for p2_id in person_nodes[p1_idx + 1:]:
                p2_neighbors = set(n[0] for n in self.adj.get(p2_id, []))

                # Shared employer
                if p1_neighbors & p2_neighbors:
                    shared = p1_neighbors & p2_neighbors
                    for shared_id in shared:
                        if self.nodes.get(shared_id, {}).get("entity_type") == "company":
                            union(p1_id, p2_id)
                            break

                # Shared sanctions exposure
                if not (find(p1_id) == find(p2_id)):
                    for n1 in p1_neighbors:
                        if self.nodes.get(n1, {}).get("entity_type") == "sanctions_list":
                            if n1 in p2_neighbors:
                                union(p1_id, p2_id)
                                break

        # Group by community
        communities_map = defaultdict(list)
        for nid in person_nodes:
            root = find(nid)
            communities_map[root].append(nid)

        communities = {}
        for i, (root, member_ids) in enumerate(communities_map.items()):
            communities[f"community_{i}"] = {
                "person_ids": member_ids,
                "size": len(member_ids),
                "cohesion": 1.0 if len(member_ids) == 1 else 0.7,
                "connection_type": "mixed",
            }

        return {
            "communities": communities,
            "total_persons": len(person_nodes),
        }

    def compute_person_risk_score(self, person_entity_id: str) -> dict:
        """
        Compute a combined risk score for a person based on:
          - Sanctions proximity (direct hits, employer hits)
          - Network centrality (betweenness)
          - Co-national/co-employer clusters

        Returns:
            {
                "person_id": str,
                "name": str,
                "network_risk_score": float (0-1),
                "sanctions_risk": float (0-1),
                "centrality_risk": float (0-1),
                "cluster_risk": float (0-1),
                "combined_risk": float (0-1),
                "risk_level": "CLEAR" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
                "risk_factors": [str, ...],
            }
        """
        person = self.nodes.get(person_entity_id)
        if not person or person.get("entity_type") != "person":
            return {
                "person_id": person_entity_id,
                "error": "Person not found in graph",
            }

        sanctions_risk = 0.0
        risk_factors = []

        # Check for direct sanctions connections
        neighbors = set(n[0] for n in self.adj.get(person_entity_id, []))
        for neighbor_id in neighbors:
            neighbor = self.nodes.get(neighbor_id, {})
            if neighbor.get("entity_type") == "sanctions_list":
                sanctions_risk = max(sanctions_risk, 0.95)
                risk_factors.append(f"Direct sanctions match: {neighbor.get('canonical_name')}")

        # Check employer for sanctions connections
        for neighbor_id in neighbors:
            neighbor = self.nodes.get(neighbor_id, {})
            if neighbor.get("entity_type") == "company":
                emp_neighbors = set(n[0] for n in self.adj.get(neighbor_id, []))
                for emp_neighbor in emp_neighbors:
                    if self.nodes.get(emp_neighbor, {}).get("entity_type") == "sanctions_list":
                        sanctions_risk = max(sanctions_risk, 0.65)
                        risk_factors.append(f"Employer {neighbor.get('canonical_name')} linked to sanctions")
                        break

        # Centrality risk: high betweenness = bridge person connecting risk clusters
        centrality = self.compute_person_centrality()
        person_cent = centrality.get(person_entity_id, {})
        betweenness = person_cent.get("betweenness", 0.0)
        degree = person_cent.get("degree", 0)

        centrality_risk = min(betweenness + (degree / 10.0), 1.0)
        if betweenness > 0.5:
            risk_factors.append(f"High betweenness centrality ({betweenness:.2f}): bridge person")

        # Cluster risk: in large co-national or co-employer group
        communities = self.detect_person_communities()
        cluster_risk = 0.0
        for com_id, com in communities.get("communities", {}).items():
            if person_entity_id in com.get("person_ids", []):
                cluster_size = com.get("size", 1)
                if cluster_size > 5:
                    cluster_risk = 0.3
                    risk_factors.append(f"Member of large person cluster ({cluster_size} persons)")
                break

        # Network risk: sanctions exposure score
        network_risk = 0.0
        sanctions_scores = self.compute_sanctions_exposure()
        sanc_entry = sanctions_scores.get(person_entity_id, {})
        if sanc_entry.get("risk_level") != "CLEAR":
            network_risk = min(sanc_entry.get("exposure_score", 0.0), 1.0)
            risk_factors.append(f"Network sanctions exposure: {sanc_entry.get('risk_level')}")

        # Combined score: union of risk channels, avoiding another arbitrary weight table.
        combined_risk = 1.0
        for component in (sanctions_risk, centrality_risk, cluster_risk, network_risk):
            combined_risk *= (1.0 - max(0.0, min(float(component), 1.0)))
        combined_risk = 1.0 - combined_risk

        # Classify risk level
        if combined_risk >= 0.8:
            risk_level = "CRITICAL"
        elif combined_risk >= 0.6:
            risk_level = "HIGH"
        elif combined_risk >= 0.4:
            risk_level = "MEDIUM"
        elif combined_risk > 0.0:
            risk_level = "LOW"
        else:
            risk_level = "CLEAR"

        return {
            "person_id": person_entity_id,
            "name": person.get("canonical_name", ""),
            "network_risk_score": round(network_risk, 4),
            "sanctions_risk": round(sanctions_risk, 4),
            "centrality_risk": round(centrality_risk, 4),
            "cluster_risk": round(cluster_risk, 4),
            "combined_risk": round(combined_risk, 4),
            "risk_level": risk_level,
            "risk_factors": risk_factors,
        }

    def compute_graph_intelligence(self, mission_context: Optional[dict] = None) -> dict:
        """
        Compute a full intelligence summary of the knowledge graph.
        Returns a dashboard-ready payload with all analytics.
        """
        self._ensure_loaded()

        centrality = self.compute_all_centrality(mission_context=mission_context)
        communities = self.detect_communities()
        temporal = self.compute_temporal_profile()
        sanctions = self.compute_sanctions_exposure()

        # Top 10 most important entities for operator decision-making
        top_decision_entities = sorted(
            centrality.values(),
            key=lambda x: x.get("decision_importance", x.get("composite_importance", 0)),
            reverse=True,
        )[:10]
        top_structural_entities = sorted(
            centrality.values(),
            key=lambda x: x.get("structural_importance", 0),
            reverse=True,
        )[:10]
        top_mission_entities = sorted(
            centrality.values(),
            key=lambda x: x.get("mission_importance", x.get("decision_importance", x.get("composite_importance", 0))),
            reverse=True,
        )[:10]

        # Top risk entities
        top_risk = sorted(
            [(nid, data) for nid, data in sanctions.items() if data["risk_level"] != "CLEAR"],
            key=lambda x: x[1]["exposure_score"],
            reverse=True,
        )[:10]

        # Risk distribution
        risk_dist = defaultdict(int)
        for data in sanctions.values():
            risk_dist[data["risk_level"]] += 1

        return {
            "graph_size": {
                "nodes": len(self.nodes),
                "edges": len(self.edges),
            },
            "top_entities_by_importance": top_mission_entities if isinstance(mission_context, dict) else top_decision_entities,
            "top_entities_by_decision_importance": top_decision_entities,
            "top_entities_by_structural_importance": top_structural_entities,
            "top_entities_by_mission_importance": top_mission_entities,
            "top_entities_by_risk": [
                {
                    "entity_id": nid,
                    "entity_name": self.nodes.get(nid, {}).get("canonical_name", ""),
                    "entity_type": self.nodes.get(nid, {}).get("entity_type", ""),
                    **data,
                }
                for nid, data in top_risk
            ],
            "risk_distribution": dict(risk_dist),
            "communities": {
                "count": communities["count"],
                "modularity": communities["modularity"],
                "largest_community_size": max(
                    (c["size"] for c in communities["communities"].values()),
                    default=0,
                ),
            },
            "temporal": temporal,
            "mission_context_applied": isinstance(mission_context, dict),
        }
