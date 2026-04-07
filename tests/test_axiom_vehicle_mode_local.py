import importlib
import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload(name: str):
    if name in sys.modules:
        return importlib.reload(sys.modules[name])
    return importlib.import_module(name)


def test_build_vehicle_mode_support_separates_truth_states(monkeypatch):
    axiom_agent = _reload("axiom_agent")

    monkeypatch.setattr(
        axiom_agent,
        "build_vehicle_intelligence_support",
        lambda **_: {
            "connectors_run": 3,
            "connectors_with_data": 2,
            "relationships": [
                {
                    "rel_type": "awarded_under",
                    "source_name": "ASTRO",
                    "target_name": "LEIA",
                    "evidence_summary": "Archived notice keeps LEIA attached to ASTRO.",
                    "data_source": "contract_opportunities_public",
                }
            ],
            "events": [],
            "findings": [
                {
                    "title": "Notice capture preserved LEIA customer signal",
                    "detail": "USINDOPACOM remains attached to the public notice trail.",
                    "source": "contract_opportunities_public",
                    "severity": "medium",
                }
            ],
        },
        raising=False,
    )
    monkeypatch.setattr(
        axiom_agent,
        "build_teaming_intelligence",
        lambda **_: {
            "supported": True,
            "observed_signals": [
                {
                    "source": "SMX",
                    "target": "LEIA",
                    "rel_type": "prime_contractor_of",
                    "connector": "sam_gov",
                    "snippet": "Observed as current prime on the vehicle.",
                }
            ],
            "top_conclusions": ["SMX remains the incumbent-core read on LEIA."],
        },
        raising=False,
    )

    target = axiom_agent.SearchTarget(
        prime_contractor="SMX",
        vehicle_name="LEIA",
        context="Map the teammate pressure and lineage.",
    )
    payload = axiom_agent._build_vehicle_mode_support(target)

    assert payload["vehicle_name"] == "LEIA"
    assert payload["graph_facts"][0]["rel_type"] == "prime_contractor_of"
    assert payload["support_evidence"]["connectors_with_data"] == 2
    assert payload["support_evidence"]["relationships"][0]["rel_type"] == "awarded_under"
    assert payload["predictions"][0] == "SMX remains the incumbent-core read on LEIA."
    assert any("No protest or litigation signal" in item for item in payload["unknowns"])


def test_build_analysis_prompt_includes_vehicle_mode_support_blocks():
    axiom_agent = _reload("axiom_agent")
    target = axiom_agent.SearchTarget(
        prime_contractor="SMX",
        vehicle_name="LEIA",
        context="Pressure the incumbent carryover story.",
    )
    prompt = axiom_agent._build_analysis_prompt(
        target,
        raw_findings=[{"title": "SMX posting", "detail": "LEIA support role"}],
        iteration=1,
        previous_entities=[],
        vehicle_mode_support={
            "graph_facts": [{"source": "SMX", "target": "LEIA", "rel_type": "prime_contractor_of"}],
            "support_evidence": {"connectors_run": 2, "connectors_with_data": 1},
            "predictions": ["SMX remains the visible anchor on LEIA."],
            "unknowns": ["No protest signal attached yet."],
        },
    )

    assert "GRAPH_FACTS:" in prompt
    assert "SUPPORT_EVIDENCE:" in prompt
    assert "PREDICTIONS:" in prompt
    assert "UNKNOWNS:" in prompt
    assert "do not silently merge them" in prompt.lower()
