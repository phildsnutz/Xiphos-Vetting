import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


import readiness_contract  # type: ignore  # noqa: E402


def test_build_readiness_contract_marks_ready_when_surfaces_hold():
    contract, accounting = readiness_contract.build_readiness_contract(
        enrichment={
            "summary": {"connectors_run": 4, "connectors_with_data": 3, "findings_total": 12},
            "connector_status": {
                "sam_gov": {"has_data": True},
                "fpds_contracts": {"has_data": True},
                "public_search_ownership": {"has_data": True},
            },
        },
        ownership={
            "connectors_run": 3,
            "connectors_with_data": 2,
            "official_connectors_with_data": 1,
            "metrics": {"ownership_relationship_count": 2, "official_connectors_with_data": 1},
            "connector_status": {
                "sec_edgar": {"has_data": True, "authority_level": "official_registry"},
                "public_search_ownership": {"has_data": True},
            },
        },
        procurement={
            "connectors_run": 1,
            "connectors_with_data": 1,
            "relationships": [{"rel_type": "prime_contractor_of"}],
            "top_customers": [{"name": "US Army"}],
        },
        graph={
            "relationship_count": 4,
            "relationships": [{"rel_type": "parent_of"}],
            "intelligence": {
                "thin_graph": False,
                "control_path_count": 2,
                "missing_required_edge_families": [],
            },
        },
        agent_result={
            "iteration": 1,
            "entities": [{"name": "Parsons"}],
            "relationships": [{"source_entity": "Parsons", "target_entity": "PSC", "rel_type": "related_entity"}] * 2,
            "intelligence_gaps": [],
            "iterations": [
                {
                    "connector_calls": [
                        {"success": True, "findings_count": 1},
                        {"success": True, "relationship_count": 1},
                        {"success": True, "identifiers": {"uei": "uei-1"}},
                    ]
                }
            ],
        },
    )

    assert accounting["connector_calls_attempted"] == 3
    assert accounting["connector_calls_with_data"] == 3
    assert contract["status"] == "ready"
    assert contract["usable_surface_count"] >= 4
    assert contract["surfaces"]["axiom_gap_closure"]["status"] == "ready"


def test_build_readiness_contract_marks_degraded_for_local_fallback():
    contract, accounting = readiness_contract.build_readiness_contract(
        enrichment=None,
        ownership=None,
        procurement=None,
        graph=None,
        agent_result={
            "iteration": 1,
            "entities": [{"name": "Parsons"}],
            "relationships": [],
            "intelligence_gaps": [{"description": "No clean control path held."}],
            "iterations": [],
        },
        local_fallback={"mode": "deterministic_dev_pressure", "reason": "No API key available."},
    )

    assert accounting["connector_calls_attempted"] == 0
    assert contract["status"] == "degraded"
    assert contract["surfaces"]["axiom_gap_closure"]["status"] == "degraded"
    assert "No API key available." in contract["surfaces"]["axiom_gap_closure"]["unresolved_reasons"][0]
