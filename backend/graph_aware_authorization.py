"""
Graph-Aware Export Authorization

Enriches the standard export authorization guidance with knowledge graph
intelligence. Before rendering a final posture, this module queries the
knowledge graph for:

1. Entity network risk: Does the destination company or end-user have
   concerning graph connections (sanctions links, shell company patterns)?
2. Person network exposure: Do screened persons have 2nd/3rd degree
   sanctions contamination through the entity network?
3. Community risk: Is the destination entity in a high-risk community cluster?
4. Historical patterns: Have prior transactions with connected entities
   resulted in escalations or denials?

The graph layer can ELEVATE a posture (e.g., "likely_nlr" -> "escalate")
but never LOWER one. The rules engine is always the floor; the graph
intelligence is additive risk only.

Usage:
    from graph_aware_authorization import build_graph_aware_guidance

    guidance = build_graph_aware_guidance(case_input)
    # Returns standard guidance dict + "graph_intelligence" section
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _safe_import_analytics():
    try:
        from graph_analytics import GraphAnalytics
        return GraphAnalytics
    except ImportError:
        return None


def _safe_import_person_graph():
    try:
        from person_graph_ingest import get_person_network_risk
        return get_person_network_risk
    except ImportError:
        return None


def _safe_import_rules():
    try:
        from export_authorization_rules import build_export_authorization_guidance
        return build_export_authorization_guidance
    except ImportError:
        return None


def _safe_import_kg():
    try:
        import knowledge_graph as kg
        return kg
    except ImportError:
        return None


# Posture hierarchy (higher index = more restrictive)
POSTURE_HIERARCHY = [
    "likely_nlr",
    "likely_exception_or_exemption",
    "likely_license_required",
    "escalate",
    "likely_prohibited",
]


def _elevate_posture(current: str, new_posture: str) -> str:
    """Elevate posture to the more restrictive of current and new."""
    try:
        current_idx = POSTURE_HIERARCHY.index(current)
    except ValueError:
        current_idx = 0
    try:
        new_idx = POSTURE_HIERARCHY.index(new_posture)
    except ValueError:
        new_idx = 0

    return POSTURE_HIERARCHY[max(current_idx, new_idx)]


def query_entity_graph_risk(entity_name: str) -> dict:
    """
    Query the knowledge graph for risk signals around a named entity.
    Checks for sanctions connections, high-risk community membership,
    and suspicious network patterns.
    """
    kg = _safe_import_kg()
    AnalyticsClass = _safe_import_analytics()

    if not kg:
        return {"available": False}

    # Search for entity in graph
    try:
        entities = kg.find_entities_by_name(entity_name, entity_type="company")
        if not entities:
            entities = kg.find_entities_by_name(entity_name)
    except Exception as e:
        logger.warning(f"Entity search failed: {e}")
        return {"available": False, "error": str(e)}

    if not entities:
        return {"available": True, "found": False, "entity_name": entity_name}

    entity = entities[0]
    entity_id = entity.id

    # Get network
    try:
        network = kg.get_entity_network(entity_id, depth=2)
    except Exception:
        network = None

    risk_signals = []

    if network:
        for eid, ent_data in network.get("entities", {}).items():
            if eid == entity_id:
                continue

            etype = ent_data.get("entity_type", "")

            if etype in ("sanctions_list", "sanctions_entry"):
                risk_signals.append({
                    "signal": "SANCTIONS_NETWORK_CONNECTION",
                    "severity": "CRITICAL",
                    "entity": ent_data.get("canonical_name", ""),
                    "description": "Connected to sanctions entry within 2 hops",
                })
            elif etype == "export_control":
                risk_signals.append({
                    "signal": "EXPORT_CONTROL_LINK",
                    "severity": "HIGH",
                    "entity": ent_data.get("canonical_name", ""),
                    "description": "Connected to export control classification node",
                })

    # Compute sanctions exposure if analytics available
    sanctions_exposure = None
    if AnalyticsClass:
        try:
            analytics = AnalyticsClass()
            analytics.load_graph()
            exposure = analytics.compute_sanctions_exposure()
            if entity_id in exposure:
                sanctions_exposure = exposure[entity_id]
        except Exception:
            pass

    return {
        "available": True,
        "found": True,
        "entity_id": entity_id,
        "entity_name": entity.canonical_name,
        "entity_confidence": entity.confidence,
        "network_size": network.get("entity_count", 0) if network else 0,
        "risk_signals": risk_signals,
        "sanctions_exposure": sanctions_exposure,
    }


def build_graph_aware_guidance(case_input: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Build export authorization guidance enriched with graph intelligence.

    Steps:
    1. Run standard rules engine
    2. Query knowledge graph for destination entity risk
    3. Query knowledge graph for person network risk (if foreign persons listed)
    4. Elevate posture if graph signals warrant it
    5. Return combined guidance with graph_intelligence section
    """
    build_guidance = _safe_import_rules()
    if not build_guidance:
        return None

    # Step 1: Standard rules engine
    guidance = build_guidance(case_input)
    if not guidance:
        return None

    graph_intelligence = {
        "graph_available": False,
        "entity_risk": None,
        "person_risk": [],
        "posture_elevated": False,
        "elevation_reasons": [],
    }

    # Step 2: Query entity graph for destination
    destination = (case_input or {}).get("destination_company") or (case_input or {}).get("end_user_name")
    if destination:
        entity_risk = query_entity_graph_risk(destination)
        graph_intelligence["entity_risk"] = entity_risk
        graph_intelligence["graph_available"] = entity_risk.get("available", False)

        # Check for critical risk signals
        for signal in entity_risk.get("risk_signals", []):
            if signal["severity"] == "CRITICAL":
                graph_intelligence["posture_elevated"] = True
                graph_intelligence["elevation_reasons"].append(
                    f"Graph: {signal['description']} ({signal['entity']})"
                )

        # Check sanctions exposure
        exposure = entity_risk.get("sanctions_exposure", {})
        if exposure and exposure.get("risk_level") in ("CRITICAL", "HIGH"):
            graph_intelligence["posture_elevated"] = True
            graph_intelligence["elevation_reasons"].append(
                f"Graph: Sanctions exposure score {exposure.get('exposure_score', 0):.2f} ({exposure.get('risk_level')})"
            )

    # Step 3: Query person network risk
    get_person_risk = _safe_import_person_graph()
    persons_to_check = (case_input or {}).get("persons_screened", [])

    if get_person_risk and persons_to_check:
        for person in persons_to_check:
            pname = person.get("name", "")
            pnats = person.get("nationalities", [])
            if pname:
                try:
                    prisk = get_person_risk(pname, pnats)
                    graph_intelligence["person_risk"].append({
                        "name": pname,
                        **prisk,
                    })
                    if prisk.get("network_risk_level") in ("CRITICAL", "HIGH"):
                        graph_intelligence["posture_elevated"] = True
                        graph_intelligence["elevation_reasons"].append(
                            f"Graph: Person {pname} has {prisk['network_risk_level']} network risk"
                        )
                except Exception:
                    pass

    # Step 4: Elevate posture if needed
    if graph_intelligence["posture_elevated"]:
        original_posture = guidance["posture"]
        new_posture = _elevate_posture(original_posture, "escalate")
        if new_posture != original_posture:
            guidance["posture"] = new_posture
            guidance["posture_label"] = f"ESCALATE (graph-elevated from {original_posture})"
            guidance["factors"].append(
                "Knowledge graph analysis detected elevated risk: "
                + "; ".join(graph_intelligence["elevation_reasons"])
            )
            guidance["graph_elevated"] = True

    # Step 5: Attach graph intelligence
    guidance["graph_intelligence"] = graph_intelligence

    return guidance
