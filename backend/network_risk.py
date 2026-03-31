"""
Network Risk Propagation Engine

Computes a "Network Risk Score" for each vendor based on the aggregate risk
of its graph neighbors, weighted by learned edge intelligence and hop distance.

Design principles:
  - Informational overlay (Stage 1): does NOT modify the FGAMLogit score
  - Bidirectional: risk flows subsidiary -> parent AND parent -> subsidiary
  - Capped at +/- 5 points to prevent runaway cascading
  - Propagation only crosses edges that clear their empirical family trust floor
  - Maximum 2 hops (direct neighbors + one hop further)
  - Explainable: every score modifier includes an evidence trail

Propagation posture:
  - relation strength comes from fixture-backed family reliability
  - edge truth comes from the learned intelligence score
  - longer paths decay harmonically rather than by another hand-tuned table
"""

import logging
import os
from typing import Optional

from graph_ingest import annotate_graph_relationship_intelligence
from learned_weighting import get_edge_family_reliability_profile

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────

MAX_MODIFIER_POINTS = 5.0      # Cap on absolute score adjustment
MAX_HOPS = 2                   # Maximum traversal depth

# Risk thresholds for classifying neighbor risk level
RISK_THRESHOLDS = {
    "critical": 40.0,   # Score >= 40% is critical risk
    "high": 25.0,       # Score >= 25% is high risk
    "medium": 15.0,     # Score >= 15% is medium risk
}


def _safe_import_kg():
    try:
        import knowledge_graph as kg
        return kg
    except ImportError:
        return None


def _safe_import_db():
    try:
        import db
        return db
    except ImportError:
        return None


def compute_network_risk(vendor_id: str) -> dict:
    """
    Compute the network risk score for a vendor.

    Returns:
        {
            "vendor_id": str,
            "network_risk_score": float,       # The modifier (-5.0 to +5.0)
            "network_risk_level": str,          # "none", "low", "medium", "high", "critical"
            "risk_contributors": [...],         # Entities contributing to risk
            "propagation_paths": [...],         # How risk reached this vendor
            "neighbor_count": int,              # Total neighbors analyzed
            "high_risk_neighbors": int,         # Neighbors with elevated risk
            "graph_density": float,             # Connectivity metric
            "confidence": float,                # Overall confidence in the score
        }
    """
    kg = _safe_import_kg()
    db_mod = _safe_import_db()

    if not kg or not db_mod:
        return _empty_result(vendor_id, "Modules unavailable")

    try:
        kg.init_kg_db()

        # Get entities linked to this vendor
        entities = kg.get_vendor_entities(vendor_id)
        if not entities:
            return _empty_result(vendor_id, "No graph entities")

        # Get the primary entity (highest confidence company entity)
        primary = _get_primary_entity(entities)
        if not primary:
            return _empty_result(vendor_id, "No primary entity found")

        # Get 2-hop network
        primary_id = getattr(primary, "id", getattr(primary, "entity_id", ""))
        network = kg.get_entity_network(
            primary_id,
            depth=MAX_HOPS,
            include_provenance=True,
            max_claim_records=2,
            max_evidence_records=2,
        )
        all_entities = network.get("entities", {})
        all_relationships = annotate_graph_relationship_intelligence(network.get("relationships", []))

        if not all_relationships:
            return _empty_result(vendor_id, "No relationships in graph")

        # Get risk scores for all neighbor vendors
        vendor_scores = _get_all_vendor_scores(db_mod)

        # Map entities to their vendor scores (if they're linked to a vendor)
        entity_vendor_map = _map_entities_to_vendors(kg, all_entities)

        # BFS propagation from primary entity
        risk_contributions = []
        visited = {primary_id}
        frontier = [(primary_id, 0, 1.0, [])]  # (entity_id, hop, cumulative_weight, path)

        while frontier:
            current_id, hop, weight, path = frontier.pop(0)

            if hop >= MAX_HOPS:
                continue

            # Find all relationships involving this entity (bidirectional)
            neighbors = _get_neighbor_records(current_id, all_relationships)

            for neighbor in neighbors:
                neighbor_id = neighbor["neighbor_id"]
                rel_type = neighbor["rel_type"]
                confidence = float(neighbor["confidence"])
                direction = neighbor["direction"]
                relationship = neighbor["relationship"]
                if neighbor_id in visited:
                    continue
                if not _edge_is_propagation_eligible(relationship):
                    continue

                visited.add(neighbor_id)

                edge_strength = _edge_strength(relationship)
                propagation_prior = _propagation_prior(relationship)
                hop_factor = _hop_decay_factor(hop)
                prop_weight = weight * edge_strength * propagation_prior * hop_factor

                # Get the neighbor's risk score
                neighbor_entity = all_entities.get(neighbor_id, {})
                neighbor_name = neighbor_entity.get("canonical_name", "Unknown")
                neighbor_vendor_ids = entity_vendor_map.get(neighbor_id, [])

                neighbor_risk = 0.0
                neighbor_vendor_id = None
                for vid in neighbor_vendor_ids:
                    if vid == vendor_id:
                        continue  # Don't self-propagate
                    score = vendor_scores.get(vid, {})
                    risk_pct = score.get("calibrated_probability", 0)
                    if risk_pct is None:
                        risk_pct = score.get("calibrated", {}).get("calibrated_probability", 0) if isinstance(score.get("calibrated"), dict) else 0
                    risk_pct = (risk_pct or 0) * 100  # Convert 0-1 probability to 0-100 pct
                    if risk_pct > neighbor_risk:
                        neighbor_risk = risk_pct
                        neighbor_vendor_id = vid

                if neighbor_risk > 0:
                    contribution = neighbor_risk * prop_weight / 100.0  # Normalize
                    new_path = path + [{
                        "entity_name": neighbor_name,
                        "entity_id": neighbor_id,
                        "rel_type": rel_type,
                        "direction": direction,
                        "confidence": confidence,
                        "hop": hop + 1,
                    }]

                    risk_contributions.append({
                        "entity_name": neighbor_name,
                        "entity_id": neighbor_id,
                        "vendor_id": neighbor_vendor_id,
                        "risk_score_pct": neighbor_risk,
                        "propagation_weight": round(prop_weight, 4),
                        "edge_strength": round(edge_strength, 4),
                        "propagation_prior": round(propagation_prior, 4),
                        "contribution": round(contribution, 4),
                        "rel_type": rel_type,
                        "confidence": confidence,
                        "hop": hop + 1,
                        "path": new_path,
                    })

                # Continue BFS
                frontier.append((neighbor_id, hop + 1, prop_weight, path + [{
                    "entity_name": neighbor_name,
                    "entity_id": neighbor_id,
                    "rel_type": rel_type,
                    "direction": direction,
                    "confidence": confidence,
                    "hop": hop + 1,
                }]))

        # Aggregate contributions
        total_modifier = sum(c["contribution"] for c in risk_contributions)

        # Cap at +/- MAX_MODIFIER_POINTS
        capped_modifier = max(-MAX_MODIFIER_POINTS, min(MAX_MODIFIER_POINTS, total_modifier))

        # Sort contributors by impact
        risk_contributions.sort(key=lambda x: x["contribution"], reverse=True)

        # Classify risk level
        risk_level = _classify_risk(capped_modifier, risk_contributions)

        # Compute confidence in the network score
        if risk_contributions:
            avg_confidence = sum(c["confidence"] for c in risk_contributions) / len(risk_contributions)
        else:
            avg_confidence = 0.0

        # Count high-risk neighbors
        high_risk_count = sum(1 for c in risk_contributions if c["risk_score_pct"] >= RISK_THRESHOLDS["high"])

        # Graph density (relationships per entity)
        graph_density = len(all_relationships) / max(len(all_entities), 1)

        return {
            "vendor_id": vendor_id,
            "network_risk_score": round(capped_modifier, 2),
            "network_risk_level": risk_level,
            "risk_contributors": risk_contributions[:10],  # Top 10
            "propagation_paths": _extract_key_paths(risk_contributions[:5]),
            "neighbor_count": len(visited) - 1,  # Exclude self
            "high_risk_neighbors": high_risk_count,
            "graph_density": round(graph_density, 2),
            "confidence": round(avg_confidence, 2),
            "propagation_model": "empirical_bayes_edge_intelligence_v1",
            "total_entities_analyzed": len(all_entities),
            "total_relationships_analyzed": len(all_relationships),
            "uncapped_modifier": round(total_modifier, 2),
        }

    except Exception as e:
        logger.warning("Network risk computation failed for %s: %s", vendor_id, e)
        return _empty_result(vendor_id, str(e))


def compute_portfolio_network_risk() -> dict:
    """
    Compute network risk scores for all vendors in the portfolio.
    Returns a summary with per-vendor scores and portfolio-level stats.
    """
    db_mod = _safe_import_db()
    if not db_mod:
        return {"error": "db module unavailable"}

    vendors = db_mod.list_vendors(limit=10000)
    results = []

    for v in vendors:
        vid = v.get("id", "")
        name = v.get("name", "")
        nr = compute_network_risk(vid)
        results.append({
            "vendor_id": vid,
            "vendor_name": name,
            "network_risk_score": nr.get("network_risk_score", 0),
            "network_risk_level": nr.get("network_risk_level", "none"),
            "neighbor_count": nr.get("neighbor_count", 0),
            "high_risk_neighbors": nr.get("high_risk_neighbors", 0),
        })

    # Sort by network risk (highest first)
    results.sort(key=lambda x: abs(x["network_risk_score"]), reverse=True)

    # Portfolio summary
    scores = [r["network_risk_score"] for r in results]
    return {
        "vendors": results,
        "portfolio_stats": {
            "total_vendors": len(results),
            "vendors_with_network_risk": sum(1 for s in scores if s > 0),
            "max_network_risk": max(scores) if scores else 0,
            "avg_network_risk": sum(scores) / len(scores) if scores else 0,
            "risk_distribution": {
                "none": sum(1 for r in results if r["network_risk_level"] == "none"),
                "low": sum(1 for r in results if r["network_risk_level"] == "low"),
                "medium": sum(1 for r in results if r["network_risk_level"] == "medium"),
                "high": sum(1 for r in results if r["network_risk_level"] == "high"),
                "critical": sum(1 for r in results if r["network_risk_level"] == "critical"),
            },
        },
    }


# ── Internal helpers ──────────────────────────────────────────────────────

def _get_primary_entity(entities) -> Optional[object]:
    """Get the primary (highest confidence) company entity."""
    companies = [e for e in entities if getattr(e, "entity_type", "") == "company"]
    if companies:
        return max(companies, key=lambda e: getattr(e, "confidence", 0))
    return entities[0] if entities else None


def _get_neighbors(entity_id: str, relationships: list) -> list:
    """Get all neighbors of an entity (bidirectional). Returns [(entity_id, rel_type, confidence, direction)]."""
    neighbors = []
    for r in relationships:
        src = r.get("source_entity_id", "")
        tgt = r.get("target_entity_id", "")
        rel_type = r.get("rel_type", "")
        confidence = r.get("confidence", 0.5)

        if src == entity_id:
            neighbors.append((tgt, rel_type, confidence, "outgoing"))
        elif tgt == entity_id:
            neighbors.append((src, rel_type, confidence, "incoming"))

    return neighbors


def _get_neighbor_records(entity_id: str, relationships: list[dict]) -> list[dict]:
    neighbors: list[dict] = []
    for relationship in relationships:
        src = relationship.get("source_entity_id", "")
        tgt = relationship.get("target_entity_id", "")
        if src == entity_id:
            neighbors.append(
                {
                    "neighbor_id": tgt,
                    "rel_type": str(relationship.get("rel_type") or ""),
                    "confidence": float(relationship.get("confidence") or 0.5),
                    "direction": "outgoing",
                    "relationship": relationship,
                }
            )
        elif tgt == entity_id:
            neighbors.append(
                {
                    "neighbor_id": src,
                    "rel_type": str(relationship.get("rel_type") or ""),
                    "confidence": float(relationship.get("confidence") or 0.5),
                    "direction": "incoming",
                    "relationship": relationship,
                }
            )
    return neighbors


def _hop_decay_factor(hop: int) -> float:
    return 1.0 / float(hop + 1)


def _edge_strength(relationship: dict) -> float:
    strength = float(
        relationship.get("learned_truth_probability")
        or relationship.get("intelligence_score")
        or relationship.get("confidence")
        or 0.0
    )
    return max(0.0, min(strength, 1.0))


def _edge_is_propagation_eligible(relationship: dict) -> bool:
    edge_strength = _edge_strength(relationship)
    profile = get_edge_family_reliability_profile()
    family = str(
        relationship.get("primary_edge_family")
        or (
            (relationship.get("edge_families") or ["other"])[0]
            if isinstance(relationship.get("edge_families"), list)
            else "other"
        )
        or "other"
    )
    if family in {"identity_and_alias", "other"}:
        return False
    if profile is None:
        return edge_strength >= 0.5
    family_floor = float(profile.posterior_mean_by_family.get(family, profile.global_posterior_mean))
    return edge_strength >= family_floor


def _propagation_prior(relationship: dict) -> float:
    profile = get_edge_family_reliability_profile()
    if profile is None:
        return 0.5
    family = str(
        relationship.get("primary_edge_family")
        or (
            (relationship.get("edge_families") or ["other"])[0]
            if isinstance(relationship.get("edge_families"), list)
            else "other"
        )
        or "other"
    )
    return float(profile.posterior_mean_by_family.get(family, profile.global_posterior_mean))


def _get_all_vendor_scores(db_mod) -> dict:
    """Get latest scores for all vendors. Returns {vendor_id: score_dict}.

    Read directly from scoring_results columns first because the serialized
    full_result payload does not always expose calibrated_probability at the
    top level in historical rows.
    """
    scores = {}
    try:
        engine = os.environ.get("HELIOS_DB_ENGINE", "sqlite").lower().strip()
        use_postgres = engine in ("postgres", "postgresql", "pg")
        if use_postgres:
            with db_mod.get_conn() as conn:
                rows = conn.execute("""
                    SELECT sr.vendor_id, sr.calibrated_probability, sr.calibrated_tier,
                           sr.composite_score, sr.is_hard_stop
                    FROM scoring_results sr
                    INNER JOIN (
                        SELECT vendor_id, MAX(id) AS max_id
                        FROM scoring_results
                        GROUP BY vendor_id
                    ) latest ON sr.id = latest.max_id
                """).fetchall()
        else:
            import sqlite3

            db_path = db_mod.get_db_path() if hasattr(db_mod, "get_db_path") else db_mod.DB_PATH
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT sr.vendor_id, sr.calibrated_probability, sr.calibrated_tier,
                       sr.composite_score, sr.is_hard_stop
                FROM scoring_results sr
                INNER JOIN (
                    SELECT vendor_id, MAX(id) AS max_id
                    FROM scoring_results
                    GROUP BY vendor_id
                ) latest ON sr.id = latest.max_id
            """).fetchall()
        for row in rows:
            scores[row["vendor_id"]] = {
                "calibrated_probability": row["calibrated_probability"],
                "calibrated_tier": row["calibrated_tier"],
                "composite_score": row["composite_score"],
                "is_hard_stop": bool(row["is_hard_stop"]),
            }
        if not use_postgres:
            conn.close()
    except Exception as exc:
        print(f"[network_risk] _get_all_vendor_scores error: {exc}")
        vendors = db_mod.list_vendors(limit=10000)
        for vendor in vendors:
            vendor_id = vendor.get("id", "")
            score = db_mod.get_latest_score(vendor_id)
            if score:
                scores[vendor_id] = score
    return scores


def _map_entities_to_vendors(kg, entities: dict) -> dict:
    """Map entity IDs to their linked vendor IDs. Returns {entity_id: [vendor_ids]}."""
    entity_ids = [str(eid or "").strip() for eid in entities if str(eid or "").strip()]
    if not entity_ids:
        return {}

    entity_vendor_map: dict[str, list[str]] = {}
    batch_size = 500
    try:
        with kg.get_kg_conn() as conn:
            for offset in range(0, len(entity_ids), batch_size):
                chunk = entity_ids[offset: offset + batch_size]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT entity_id, vendor_id FROM kg_entity_vendors WHERE entity_id IN ({placeholders})",
                    chunk,
                ).fetchall()
                for row in rows:
                    entity_id = str(row["entity_id"] if not isinstance(row, tuple) else row[0] or "")
                    vendor_id = str(row["vendor_id"] if not isinstance(row, tuple) else row[1] or "")
                    if not entity_id or not vendor_id:
                        continue
                    entity_vendor_map.setdefault(entity_id, []).append(vendor_id)
    except Exception:
        return {}
    return entity_vendor_map


def _classify_risk(modifier: float, contributions: list) -> str:
    """Classify the network risk level."""
    if modifier <= 0 or not contributions:
        return "none"
    if modifier >= 4.0 or any(c["risk_score_pct"] >= RISK_THRESHOLDS["critical"] for c in contributions):
        return "critical"
    if modifier >= 2.5 or any(c["risk_score_pct"] >= RISK_THRESHOLDS["high"] for c in contributions):
        return "high"
    if modifier >= 1.0:
        return "medium"
    return "low"


def _extract_key_paths(contributions: list) -> list:
    """Extract the most significant propagation paths for display."""
    paths = []
    for c in contributions:
        if c.get("path"):
            path_str = " -> ".join(
                f"{step['entity_name']} ({step['rel_type']}, {step['confidence']:.0%})"
                for step in c["path"]
            )
            paths.append({
                "description": path_str,
                "total_risk_contribution": c["contribution"],
                "source_vendor": c.get("vendor_id", ""),
                "source_risk": c.get("risk_score_pct", 0),
            })
    return paths


def _empty_result(vendor_id: str, reason: str = "") -> dict:
    """Return an empty network risk result."""
    return {
        "vendor_id": vendor_id,
        "network_risk_score": 0.0,
        "network_risk_level": "none",
        "risk_contributors": [],
        "propagation_paths": [],
        "neighbor_count": 0,
        "high_risk_neighbors": 0,
        "graph_density": 0.0,
        "confidence": 0.0,
        "total_entities_analyzed": 0,
        "total_relationships_analyzed": 0,
        "uncapped_modifier": 0.0,
        "note": reason,
    }
