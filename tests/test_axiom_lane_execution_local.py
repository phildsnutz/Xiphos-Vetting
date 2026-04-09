import importlib
import json
import os
import sys
import time


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload_module(name: str):
    if name in sys.modules:
        return importlib.reload(sys.modules[name])
    return importlib.import_module(name)


def test_run_agent_skips_careers_search_and_long_sleeps_in_mission_command(monkeypatch):
    axiom_agent = _reload_module("axiom_agent")

    scraper_queries: list[str] = []
    web_queries: list[str] = []
    sleep_calls: list[float] = []
    connector_calls: list[str] = []
    llm_calls = {"count": 0}

    def fake_call_llm(**kwargs):
        llm_calls["count"] += 1
        return json.dumps(
            {
                "entities": [
                    {
                        "name": "Parsons Corporation",
                        "entity_type": "company",
                        "confidence": 0.91,
                        "evidence": ["Connector evidence held."],
                    }
                ],
                "relationships": [],
                "connector_requests": [],
                "follow_up_queries": [],
                "reasoning": "Connector pressure completed.",
                "intelligence_gaps": [],
                "search_complete": True,
            }
        )

    monkeypatch.setattr(
        axiom_agent,
        "resolve_runtime_ai_credentials",
        lambda **kwargs: ("anthropic", "claude-sonnet-4-6", "sk-test-anthropic"),
    )
    monkeypatch.setattr(axiom_agent, "_build_vehicle_mode_support", lambda target: {})
    monkeypatch.setattr(axiom_agent, "_run_scraper", lambda query, target: scraper_queries.append(query) or [])
    monkeypatch.setattr(axiom_agent, "_run_web_search", lambda query: web_queries.append(query) or [])
    monkeypatch.setattr(axiom_agent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(
        axiom_agent,
        "_run_connector",
        lambda name, vendor_name, **kwargs: connector_calls.append(name) or {
            "success": True,
            "connector_name": name,
            "vendor_name": vendor_name,
            "findings_count": 1,
            "findings": [
                {
                    "category": "registry",
                    "title": "SAM anchor",
                    "detail": "Parsons SAM identity held.",
                    "severity": "info",
                    "confidence": 0.82,
                    "url": "",
                }
            ],
            "has_data": True,
            "identifiers": {},
            "relationship_count": 0,
            "relationships": [],
            "structured_fields": {},
            "error": "",
            "elapsed_ms": 1,
        },
    )
    monkeypatch.setattr(axiom_agent.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    result = axiom_agent.run_agent(
        target=axiom_agent.SearchTarget(prime_contractor="Parsons Corporation"),
        provider="anthropic",
        model="claude-sonnet-4-6",
        lane_id="mission_command",
    )

    assert scraper_queries == []
    assert web_queries == []
    assert connector_calls == ["fpds_contracts", "usaspending"]
    assert result.total_connector_calls == 2
    assert result.runtime["lane_id"] == "mission_command"
    assert len(result.iterations) == 2
    assert result.iterations[0].follow_up_queries == []
    assert llm_calls["count"] == 1
    assert sleep_calls == []


def test_run_agent_keeps_broad_scraper_in_edge_collection(monkeypatch):
    axiom_agent = _reload_module("axiom_agent")

    scraper_queries: list[str] = []
    sleep_calls: list[float] = []

    monkeypatch.setattr(
        axiom_agent,
        "resolve_runtime_ai_credentials",
        lambda **kwargs: ("anthropic", "claude-sonnet-4-6", "sk-test-anthropic"),
    )
    monkeypatch.setattr(axiom_agent, "_build_vehicle_mode_support", lambda target: {})
    monkeypatch.setattr(
        axiom_agent,
        "_run_scraper",
        lambda query, target: scraper_queries.append(query)
        or [
            {
                "category": "careers",
                "title": "Public job signal",
                "detail": "A broad careers signal held.",
                "severity": "info",
                "confidence": 0.6,
            }
        ],
    )
    monkeypatch.setattr(axiom_agent, "_call_llm", lambda **kwargs: json.dumps(
        {
            "entities": [],
            "relationships": [],
            "connector_requests": [],
            "follow_up_queries": [],
            "reasoning": "Broad sweep completed.",
            "intelligence_gaps": [],
            "search_complete": True,
        }
    ))
    monkeypatch.setattr(axiom_agent.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    result = axiom_agent.run_agent(
        target=axiom_agent.SearchTarget(prime_contractor="Parsons Corporation"),
        provider="anthropic",
        model="claude-sonnet-4-6",
        lane_id="edge_collection",
    )

    assert scraper_queries == ["Parsons Corporation"]
    assert result.runtime["lane_id"] == "edge_collection"
    assert 2.0 in sleep_calls


def test_mission_command_settings_prioritize_focus_specific_connectors():
    axiom_agent = _reload_module("axiom_agent")

    settings = axiom_agent._mission_command_settings(
        axiom_agent.SearchTarget(
            prime_contractor="Parsons Corporation",
            context="ownership control and procurement posture",
        )
    )

    assert settings["focus"] == "ownership_procurement"
    assert settings["max_connector_requests_per_iteration"] == 3
    assert settings["allowed_connectors"][:4] == (
        "fpds_contracts",
        "usaspending",
        "public_search_ownership",
        "sec_edgar",
    )
    assert "sam_gov" in settings["allowed_connectors"]


def test_mission_command_prefetch_connector_requests_follow_focus_order():
    axiom_agent = _reload_module("axiom_agent")

    requests = axiom_agent._build_prefetched_connector_requests(
        axiom_agent.SearchTarget(
            prime_contractor="Parsons Corporation",
            context="ownership control and procurement posture",
        ),
        axiom_agent.LaneExecutionProfile(
            allowed_connectors=("fpds_contracts", "usaspending", "public_search_ownership", "sec_edgar"),
            max_connector_requests_per_iteration=3,
        ),
    )

    assert [request["name"] for request in requests] == [
        "fpds_contracts",
        "usaspending",
        "public_search_ownership",
    ]


def test_mission_command_second_pass_prompt_is_compact_and_terminal():
    axiom_agent = _reload_module("axiom_agent")

    profile = axiom_agent.LaneExecutionProfile(
        allowed_connectors=("sam_gov", "sec_edgar"),
        tactical_focus="ownership_control",
        tactical_instruction="Prioritize clean control-path honesty.",
    )
    prompt = axiom_agent._build_analysis_prompt(
        target=axiom_agent.SearchTarget(
            prime_contractor="Parsons Corporation",
            context="ownership control",
        ),
        raw_findings=[{"category": "connector_finding", "title": "SEC filing", "detail": "Parent disclosure held."}],
        iteration=2,
        previous_entities=["Parsons Corporation"],
        lane_profile=profile,
        vehicle_mode_support=None,
    )

    assert "FINAL TACTICAL SYNTHESIS PASS" in prompt
    assert '"connector_requests": []' in prompt
    assert '"follow_up_queries": []' in prompt
    assert "Do not request more connectors." in prompt


def test_execute_connector_requests_runs_tactical_batch_in_parallel(monkeypatch):
    axiom_agent = _reload_module("axiom_agent")

    def fake_run_connector(name, vendor_name, **kwargs):
        time.sleep(0.08)
        return {
            "success": True,
            "connector_name": name,
            "vendor_name": vendor_name,
            "findings_count": 0,
            "findings": [],
            "has_data": True,
            "identifiers": {},
            "relationship_count": 0,
            "relationships": [],
            "structured_fields": {},
            "error": "",
            "elapsed_ms": 80,
        }

    monkeypatch.setattr(axiom_agent, "_run_connector", fake_run_connector)

    profile = axiom_agent.LaneExecutionProfile(max_parallel_connector_requests=3)
    requests = [
        {"name": "sam_gov", "vendor_name": "Parsons Corporation", "parameters": {}},
        {"name": "fpds_contracts", "vendor_name": "Parsons Corporation", "parameters": {}},
        {"name": "usaspending", "vendor_name": "Parsons Corporation", "parameters": {}},
    ]

    start = time.perf_counter()
    results = axiom_agent._execute_connector_requests(requests, profile)
    elapsed = time.perf_counter() - start

    assert [result["connector_name"] for result in results] == ["sam_gov", "fpds_contracts", "usaspending"]
    assert elapsed < 0.18


def test_run_agent_accepts_string_intelligence_gaps(monkeypatch):
    axiom_agent = _reload_module("axiom_agent")

    monkeypatch.setattr(
        axiom_agent,
        "resolve_runtime_ai_credentials",
        lambda **kwargs: ("anthropic", "claude-sonnet-4-6", "sk-test-anthropic"),
    )
    monkeypatch.setattr(axiom_agent, "_build_vehicle_mode_support", lambda target: {})
    monkeypatch.setattr(axiom_agent, "_run_scraper", lambda query, target: [])
    monkeypatch.setattr(
        axiom_agent,
        "_call_llm",
        lambda **kwargs: json.dumps(
            {
                "entities": [],
                "relationships": [],
                "connector_requests": [],
                "follow_up_queries": [],
                "reasoning": "Thin ownership picture.",
                "intelligence_gaps": [
                    "Beneficial ownership remains unresolved.",
                    {"gap": "Vehicle-specific sub visibility is thin.", "fillable_by": "automated_search", "priority": "high"},
                ],
                "search_complete": True,
            }
        ),
    )

    result = axiom_agent.run_agent(
        target=axiom_agent.SearchTarget(
            prime_contractor="Parsons Corporation",
            context="ownership control",
        ),
        provider="anthropic",
        model="claude-sonnet-4-6",
        lane_id="mission_command",
    )

    assert result.error == ""
    assert [gap["gap"] for gap in result.intelligence_gaps] == [
        "Beneficial ownership remains unresolved.",
        "Vehicle-specific sub visibility is thin.",
    ]
