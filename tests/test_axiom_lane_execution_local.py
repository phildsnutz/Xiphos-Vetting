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
    assert connector_calls == [
        "public_search_ownership",
        "fpds_contracts",
        "sam_subaward_reporting",
        "sam_gov",
    ]
    assert result.total_connector_calls == 4
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
        "public_search_ownership",
        "sec_edgar",
        "fpds_contracts",
        "sam_gov",
    )
    assert "gleif_lei" in settings["allowed_connectors"]


def test_mission_command_general_pressure_uses_mid_market_connector_mix():
    axiom_agent = _reload_module("axiom_agent")

    settings = axiom_agent._mission_command_settings(
        axiom_agent.SearchTarget(
            prime_contractor="Kavaliro",
            context="",
        )
    )

    assert settings["focus"] == "general_pressure"
    assert settings["max_connector_requests_per_iteration"] == 4
    assert settings["allowed_connectors"][:4] == (
        "public_search_ownership",
        "fpds_contracts",
        "sam_subaward_reporting",
        "sam_gov",
    )


def test_mission_command_prefetch_connector_requests_follow_focus_order():
    axiom_agent = _reload_module("axiom_agent")

    requests = axiom_agent._build_prefetched_connector_requests(
        axiom_agent.SearchTarget(
            prime_contractor="Parsons Corporation",
            context="ownership control and procurement posture",
        ),
        axiom_agent.LaneExecutionProfile(
            allowed_connectors=("public_search_ownership", "sec_edgar", "fpds_contracts", "sam_gov"),
            max_connector_requests_per_iteration=3,
        ),
    )

    assert [request["name"] for request in requests] == [
        "public_search_ownership",
        "sec_edgar",
        "fpds_contracts",
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
    assert "Ignore routine CDN, hosting, or generic service dependencies" in prompt


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


def test_prune_relationships_for_ownership_lane_caps_noise():
    axiom_agent = _reload_module("axiom_agent")

    relationships = [
        axiom_agent.DiscoveredRelationship("Parsons Corporation", f"Subsidiary {idx}", "subsidiary_of", 0.9 - idx * 0.01)
        for idx in range(10)
    ]
    relationships.extend(
        [
            axiom_agent.DiscoveredRelationship("Parsons Corporation", "Department of Defense", "contracts_with", 0.88),
            axiom_agent.DiscoveredRelationship("Parsons Corporation", "Department of Energy", "contracts_with", 0.86),
            axiom_agent.DiscoveredRelationship("Parsons Corporation", "General Services Administration", "contracts_with", 0.84),
            axiom_agent.DiscoveredRelationship("Parsons Corporation", "NASA", "contracts_with", 0.82),
            axiom_agent.DiscoveredRelationship("Parsons Corporation", "Homeland Security", "contracts_with", 0.8),
            axiom_agent.DiscoveredRelationship("Parsons Corporation", "PARSON CORP", "former_name", 0.9),
            axiom_agent.DiscoveredRelationship("Parsons Corporation", "Parsons Government Services Inc.", "former_name", 0.85),
            axiom_agent.DiscoveredRelationship("Parsons Corporation", "Legacy Parsons", "former_name", 0.8),
        ]
    )

    pruned = axiom_agent._prune_relationships_for_lane(
        relationships,
        axiom_agent.LaneExecutionProfile(tactical_focus="ownership_procurement"),
    )

    counts: dict[str, int] = {}
    for relationship in pruned:
        counts[relationship.rel_type] = counts.get(relationship.rel_type, 0) + 1

    assert counts["subsidiary_of"] == 8
    assert counts["contracts_with"] == 4
    assert counts["former_name"] == 2
    assert len(pruned) == 14


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


def test_build_connector_summary_finding_carries_connector_digest():
    axiom_agent = _reload_module("axiom_agent")

    finding = axiom_agent._build_connector_summary_finding(
        {
            "connector_name": "fpds_contracts",
            "has_data": True,
            "findings": [
                {"title": "FPDS: 12 federal contract awards found (since 2019)"},
                {"title": "DoD contract history confirmed (3 defense agencies)"},
            ],
            "relationship_count": 0,
            "identifiers": {"fpds_contract_count": 12, "has_dod_contracts": True},
            "structured_fields": {},
        }
    )

    assert finding is not None
    assert finding["connector_source"] == "fpds_contracts"
    assert "12 federal contract awards" in finding["detail"]
    assert "identifiers" in finding["detail"]


def test_build_connector_summary_finding_surfaces_top_customer_and_ownership_counts():
    axiom_agent = _reload_module("axiom_agent")

    finding = axiom_agent._build_connector_summary_finding(
        {
            "connector_name": "sec_edgar",
            "has_data": True,
            "findings": [],
            "relationship_count": 2,
            "identifiers": {"cik": "275880"},
            "structured_fields": {
                "top_customers": ["Savannah River Operations Office", "U.S. Army Corps of Engineers"],
                "beneficial_ownership_filing_count": 5,
                "insider_filing_count": 276,
            },
        }
    )

    assert finding is not None
    assert "Savannah River Operations Office" in finding["detail"]
    assert "beneficial ownership filings: 5" in finding["detail"]
    assert "insider filings: 276" in finding["detail"]


def test_mission_command_suppresses_routine_dependency_entities(monkeypatch):
    axiom_agent = _reload_module("axiom_agent")

    llm_calls = {"count": 0}

    def fake_call_llm(**kwargs):
        llm_calls["count"] += 1
        return json.dumps(
            {
                "entities": [
                    {
                        "name": "Cloudflare",
                        "entity_type": "company",
                        "confidence": 0.78,
                        "evidence": ["Website resolved behind Cloudflare."],
                    }
                ],
                "relationships": [
                    {
                        "source_entity": "Parsons Corporation",
                        "target_entity": "Cloudflare",
                        "rel_type": "related_entity",
                        "confidence": 0.78,
                        "evidence": ["Public web infrastructure dependency."],
                    }
                ],
                "connector_requests": [],
                "follow_up_queries": [],
                "reasoning": "Cloudflare is not a control-path actor.",
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
    monkeypatch.setattr(axiom_agent, "_run_scraper", lambda query, target: [])
    monkeypatch.setattr(axiom_agent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(
        axiom_agent,
        "_run_connector",
        lambda name, vendor_name, **kwargs: {
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
            "elapsed_ms": 1,
        },
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

    assert llm_calls["count"] == 1
    assert [entity.name for entity in result.entities] == ["Parsons Corporation"]
    assert result.relationships == []


def test_mission_command_suppresses_routine_dependency_connector_relationships(monkeypatch):
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
                "reasoning": "No controlling shareholder surfaced.",
                "intelligence_gaps": [],
                "search_complete": True,
            }
        ),
    )
    monkeypatch.setattr(
        axiom_agent,
        "_run_connector",
        lambda name, vendor_name, **kwargs: {
            "success": True,
            "connector_name": name,
            "vendor_name": vendor_name,
            "findings_count": 0,
            "findings": [],
            "has_data": True,
            "identifiers": {},
            "relationship_count": 1,
            "relationships": [
                {
                    "source_entity": "Parsons Corporation",
                    "target_entity": "Cloudflare",
                    "rel_type": "related_entity",
                    "confidence": 0.81,
                    "evidence_summary": "Website resolves behind Cloudflare CDN.",
                }
            ],
            "structured_fields": {},
            "error": "",
            "elapsed_ms": 1,
        },
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

    assert [entity.name for entity in result.entities] == ["Parsons Corporation"]
    assert result.relationships == []


def test_mission_command_anchors_target_entity_from_connector_identifiers(monkeypatch):
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
                "reasoning": "Parsons is publicly traded with no controlling shareholder surfaced.",
                "intelligence_gaps": [],
                "search_complete": True,
            }
        ),
    )

    def fake_run_connector(name, vendor_name, **kwargs):
        identifiers = {}
        if name == "public_search_ownership":
            identifiers = {"uei": "FFCMDLMXRK49", "cage": "9R677", "website": "https://www.parsons.com"}
        elif name == "sec_edgar":
            identifiers = {"cik": "275880", "tickers": ["PSN"], "exchanges": ["NYSE"]}
        elif name == "fpds_contracts":
            identifiers = {"fpds_contract_count": 20, "has_dod_contracts": True}
        return {
            "success": True,
            "connector_name": name,
            "vendor_name": vendor_name,
            "findings_count": 0,
            "findings": [],
            "has_data": True,
            "identifiers": identifiers,
            "relationship_count": 0,
            "relationships": [],
            "structured_fields": {},
            "error": "",
            "elapsed_ms": 1,
        }

    monkeypatch.setattr(axiom_agent, "_run_connector", fake_run_connector)

    result = axiom_agent.run_agent(
        target=axiom_agent.SearchTarget(
            prime_contractor="Parsons Corporation",
            context="ownership control and procurement posture",
        ),
        provider="anthropic",
        model="claude-sonnet-4-6",
        lane_id="mission_command",
    )

    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.name == "Parsons Corporation"
    assert entity.attributes["uei"] == "FFCMDLMXRK49"
    assert entity.attributes["cik"] == "275880"
    assert entity.attributes["tickers"] == ["PSN"]
    assert entity.attributes["has_dod_contracts"] is True


def test_mission_command_preserves_connector_relationship_type_field(monkeypatch):
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
                "reasoning": "Customer concentration is confirmed.",
                "intelligence_gaps": [],
                "search_complete": True,
            }
        ),
    )
    monkeypatch.setattr(
        axiom_agent,
        "_run_connector",
        lambda name, vendor_name, **kwargs: {
            "success": True,
            "connector_name": name,
            "vendor_name": vendor_name,
            "findings_count": 0,
            "findings": [],
            "has_data": True,
            "identifiers": {},
            "relationship_count": 1,
            "relationships": [
                {
                    "type": "contracts_with",
                    "source_entity": "Parsons Corporation",
                    "target_entity": "Savannah River Operations Office",
                    "confidence": 0.84,
                    "evidence_summary": "FPDS returned recent contract awards from Savannah River Operations Office.",
                }
            ],
            "structured_fields": {},
            "error": "",
            "elapsed_ms": 1,
        },
    )

    result = axiom_agent.run_agent(
        target=axiom_agent.SearchTarget(
            prime_contractor="Parsons Corporation",
            context="procurement posture",
        ),
        provider="anthropic",
        model="claude-sonnet-4-6",
        lane_id="mission_command",
    )

    assert any(rel.rel_type == "contracts_with" for rel in result.relationships)
    assert any(rel.target_entity == "Savannah River Operations Office" for rel in result.relationships)


def test_mission_command_maps_legacy_subsidiary_connector_shape(monkeypatch):
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
                "reasoning": "Subsidiary map is available from SEC Exhibit 21.",
                "intelligence_gaps": [],
                "search_complete": True,
            }
        ),
    )
    monkeypatch.setattr(
        axiom_agent,
        "_run_connector",
        lambda name, vendor_name, **kwargs: {
            "success": True,
            "connector_name": name,
            "vendor_name": vendor_name,
            "findings_count": 0,
            "findings": [],
            "has_data": True,
            "identifiers": {},
            "relationship_count": 1,
            "relationships": [
                {
                    "type": "subsidiary_of",
                    "entity": "Parsons Government Services, Inc.",
                    "confidence": 0.9,
                    "jurisdiction": "Delaware",
                }
            ],
            "structured_fields": {},
            "error": "",
            "elapsed_ms": 1,
        },
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

    assert any(
        rel.rel_type == "subsidiary_of"
        and rel.source_entity == "Parsons Government Services, Inc."
        and rel.target_entity == "Parsons Corporation"
        for rel in result.relationships
    )
