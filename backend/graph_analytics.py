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

import logging
import math
from collections import defaultdict, deque
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


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

        self.loaded = True
        logger.info(f"Graph loaded: {len(self.nodes)} nodes, {len(self.edges)} edges")
        return True

    def _ensure_loaded(self):
        if not self.loaded:
            self.load_graph()

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
        n = len(self.nodes)
        if n == 0:
            return {}

        result = {}
        for nid in self.nodes:
            neighbors = self.adj.get(nid, [])
            degree = len(neighbors)
            weighted = sum(self.edges[eidx]["confidence"] for _, eidx in neighbors)
            result[nid] = {
                "degree": degree,
                "weighted_degree": round(weighted, 4),
                "normalized": round(degree / max(n - 1, 1), 4),
            }

        return result

    def compute_betweenness_centrality(self, sample_size: int = 200) -> dict:
        """
        Betweenness centrality: fraction of shortest paths passing through each node.
        Uses sampling for large graphs (Brandes algorithm with node sampling).

        Identifies bridge entities that connect otherwise-disconnected clusters.
        Critical for finding shell companies, intermediaries, and brokers.
        """
        self._ensure_loaded()
        n = len(self.nodes)
        if n < 3:
            return {nid: {"betweenness": 0.0, "normalized": 0.0} for nid in self.nodes}

        betweenness = defaultdict(float)
        node_list = list(self.nodes.keys())

        # Sample source nodes for scalability
        sources = node_list[:min(sample_size, n)]

        for s in sources:
            # BFS from s
            stack = []
            pred = defaultdict(list)
            sigma = defaultdict(float)
            sigma[s] = 1.0
            dist = {s: 0}
            queue = deque([s])

            while queue:
                v = queue.popleft()
                stack.append(v)
                for w, _ in self.adj.get(v, []):
                    if w not in dist:
                        dist[w] = dist[v] + 1
                        queue.append(w)
                    if dist[w] == dist[v] + 1:
                        sigma[w] += sigma[v]
                        pred[w].append(v)

            delta = defaultdict(float)
            while stack:
                w = stack.pop()
                for v in pred[w]:
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

    def compute_closeness_centrality(self) -> dict:
        """
        Closeness centrality: inverse of average shortest path length.
        Measures how quickly information (or risk) can reach a node.

        High closeness = entity is well-connected and can quickly be
        affected by network events (sanctions cascade, news propagation).
        """
        self._ensure_loaded()
        n = len(self.nodes)
        if n < 2:
            return {nid: {"closeness": 0.0, "avg_distance": 0.0} for nid in self.nodes}

        result = {}
        for nid in self.nodes:
            # BFS for shortest paths
            dist = {nid: 0}
            queue = deque([nid])
            while queue:
                v = queue.popleft()
                for w, _ in self.adj.get(v, []):
                    if w not in dist:
                        dist[w] = dist[v] + 1
                        queue.append(w)

            reachable = len(dist) - 1
            if reachable == 0:
                result[nid] = {"closeness": 0.0, "avg_distance": 0.0, "reachable": 0}
                continue

            total_dist = sum(dist.values())
            avg_dist = total_dist / reachable
            closeness = reachable / total_dist if total_dist > 0 else 0.0

            # Normalize by component size
            if reachable < n - 1:
                closeness *= (reachable / (n - 1))

            result[nid] = {
                "closeness": round(closeness, 4),
                "avg_distance": round(avg_dist, 2),
                "reachable": reachable,
            }

        return result

    def compute_pagerank(self, damping: float = 0.85, iterations: int = 50, tol: float = 1e-6) -> dict:
        """
        PageRank: iterative influence propagation.
        Adapted for compliance: high PageRank = entity whose risk status
        disproportionately affects many others through the network.

        Uses confidence-weighted edges for propagation strength.
        """
        self._ensure_loaded()
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
                    out_degree = len(self.adj.get(neighbor, []))
                    if out_degree > 0:
                        weight = self.edges[eidx]["confidence"]
                        incoming_sum += (rank[neighbor] * weight) / out_degree

                new_rank[nid] = (1.0 - damping) / n + damping * incoming_sum

            # Check convergence
            diff = sum(abs(new_rank[nid] - rank[nid]) for nid in node_list)
            rank = new_rank
            if diff < tol:
                break

        # Normalize to 0-1
        max_rank = max(rank.values()) if rank else 1.0
        result = {}
        for nid in node_list:
            result[nid] = {
                "pagerank": round(rank[nid], 6),
                "normalized": round(rank[nid] / max(max_rank, 1e-10), 4),
            }

        return result

    def compute_all_centrality(self) -> dict:
        """
        Compute all centrality metrics and return a composite score per entity.
        The composite blends degree (25%), betweenness (30%), closeness (20%),
        and PageRank (25%) into a single 0-1 importance score.
        """
        self._ensure_loaded()

        degree = self.compute_degree_centrality()
        betweenness = self.compute_betweenness_centrality()
        closeness = self.compute_closeness_centrality()
        pagerank = self.compute_pagerank()

        result = {}
        for nid in self.nodes:
            d = degree.get(nid, {}).get("normalized", 0)
            b = betweenness.get(nid, {}).get("normalized", 0)
            c = closeness.get(nid, {}).get("closeness", 0)
            p = pagerank.get(nid, {}).get("normalized", 0)

            composite = 0.25 * d + 0.30 * b + 0.20 * c + 0.25 * p

            result[nid] = {
                "entity_id": nid,
                "entity_name": self.nodes[nid].get("canonical_name", ""),
                "entity_type": self.nodes[nid].get("entity_type", ""),
                "degree": degree.get(nid, {}),
                "betweenness": betweenness.get(nid, {}),
                "closeness": closeness.get(nid, {}),
                "pagerank": pagerank.get(nid, {}),
                "composite_importance": round(composite, 4),
            }

        return result

    # -------------------------------------------------------------------
    # 2. COMMUNITY DETECTION
    # -------------------------------------------------------------------

    def detect_communities(self, max_iterations: int = 50) -> dict:
        """
        Label propagation community detection.

        Each node starts with its own label, then iteratively adopts
        the most common label among its neighbors (weighted by edge confidence).

        Returns: {
            "communities": {community_id: [entity_ids]},
            "node_labels": {entity_id: community_id},
            "count": int,
            "modularity": float
        }
        """
        self._ensure_loaded()
        if not self.nodes:
            return {"communities": {}, "node_labels": {}, "count": 0, "modularity": 0.0}

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
                    weight = self.edges[eidx]["confidence"]
                    label_weights[label] += weight

                if label_weights:
                    best_label = max(label_weights, key=label_weights.get)
                    if best_label != labels[nid]:
                        labels[nid] = best_label
                        changed = True

            if not changed:
                break

        # Group into communities
        communities = defaultdict(list)
        for nid, label in labels.items():
            communities[label].append(nid)

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

        # Enrich community data
        enriched_communities = {}
        for label, members in communities.items():
            member_data = []
            for mid in members:
                node = self.nodes.get(mid, {})
                member_data.append({
                    "id": mid,
                    "name": node.get("canonical_name", ""),
                    "type": node.get("entity_type", ""),
                    "confidence": node.get("confidence", 0),
                })
            enriched_communities[label] = {
                "members": member_data,
                "size": len(members),
                "types": list(set(self.nodes.get(m, {}).get("entity_type", "") for m in members)),
            }

        return {
            "communities": enriched_communities,
            "node_labels": labels,
            "count": len(communities),
            "modularity": round(modularity, 4),
        }

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

        # Compute path confidence (product of edge confidences)
        path_confidence = 1.0
        for edge in path_edges:
            path_confidence *= edge["confidence"]

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
        Uses Dijkstra with -log(confidence) as weight (minimizing negative log
        maximizes the product of confidences along the path).
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
                conf = max(self.edges[eidx]["confidence"], 0.001)
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
                    conf *= e["confidence"]
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

        # Import relationship weights
        try:
            from network_risk import RELATIONSHIP_WEIGHTS, HOP_DECAY
        except ImportError:
            RELATIONSHIP_WEIGHTS = {"sanctioned_on": 0.6, "sanctioned_person": 0.9}
            HOP_DECAY = 0.5

        # Find all sanctions-related entities
        sanctions_nodes = set()
        for nid, node in self.nodes.items():
            if node.get("entity_type") in ("sanctions_list", "sanctions_entry"):
                sanctions_nodes.add(nid)

        if not sanctions_nodes:
            return {nid: {"exposure_score": 0.0, "risk_level": "CLEAR"} for nid in self.nodes}

        # BFS from each sanctions node, propagating exposure
        exposure = defaultdict(float)
        nearest_sanction = {}  # Track which sanctions entry is nearest

        for sanction_id in sanctions_nodes:
            visited = set()
            queue = deque([(sanction_id, 1.0, 0)])  # (node, current_exposure, hops)

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
                        rel_type = self.edges[eidx]["rel_type"]
                        rel_weight = RELATIONSHIP_WEIGHTS.get(rel_type, 0.1)
                        edge_conf = self.edges[eidx]["confidence"]
                        propagated = current_exposure * rel_weight * edge_conf * HOP_DECAY
                        if propagated > 0.01:  # Threshold to avoid noise
                            queue.append((neighbor, propagated, hops + 1))

        # Classify risk levels
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

        # Combined score: weighted average
        combined_risk = (
            sanctions_risk * 0.40 +
            centrality_risk * 0.25 +
            cluster_risk * 0.15 +
            network_risk * 0.20
        )

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

    def compute_graph_intelligence(self) -> dict:
        """
        Compute a full intelligence summary of the knowledge graph.
        Returns a dashboard-ready payload with all analytics.
        """
        self._ensure_loaded()

        centrality = self.compute_all_centrality()
        communities = self.detect_communities()
        temporal = self.compute_temporal_profile()
        sanctions = self.compute_sanctions_exposure()

        # Top 10 most important entities
        top_entities = sorted(
            centrality.values(),
            key=lambda x: x.get("composite_importance", 0),
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
            "top_entities_by_importance": top_entities,
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
        }
