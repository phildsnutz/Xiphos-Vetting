import importlib
import os
import sys
from types import SimpleNamespace


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload_module(name: str):
    if name in sys.modules:
        return importlib.reload(sys.modules[name])
    return importlib.import_module(name)


def test_resolve_runtime_ai_credentials_falls_back_to_env_provider(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-env")

    axiom_agent = _reload_module("axiom_agent")

    provider, model, api_key = axiom_agent.resolve_runtime_ai_credentials(
        user_id="",
        provider="anthropic",
        model="claude-sonnet-4-6",
        api_key="",
        provider_locked=False,
        model_locked=False,
    )

    assert provider == "openai"
    assert model == "gpt-4o"
    assert api_key == "sk-test-openai-env"


def test_resolve_runtime_ai_credentials_uses_lane_primary_when_defaults_are_unset(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-anthropic-lane")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    axiom_agent = _reload_module("axiom_agent")

    provider, model, api_key = axiom_agent.resolve_runtime_ai_credentials(
        user_id="",
        provider="anthropic",
        model="claude-sonnet-4-6",
        api_key="",
        provider_locked=False,
        model_locked=False,
        lane_id="mission_command",
    )

    assert provider == "anthropic"
    assert model == "claude-sonnet-4-6"
    assert api_key == "sk-test-anthropic-lane"


def test_resolve_runtime_ai_credentials_honors_locked_provider_env_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-anthropic-explicit")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-explicit")

    axiom_agent = _reload_module("axiom_agent")

    provider, model, api_key = axiom_agent.resolve_runtime_ai_credentials(
        user_id="",
        provider="anthropic",
        model="claude-sonnet-4-6",
        api_key="",
        provider_locked=True,
        model_locked=True,
        lane_id="mission_command",
    )

    assert provider == "anthropic"
    assert model == "claude-sonnet-4-6"
    assert api_key == "sk-test-anthropic-explicit"


def test_axiom_extract_route_uses_env_fallback_when_ai_config_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-anthropic-route")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    server = _reload_module("server")
    axiom_extractor = _reload_module("axiom_extractor")

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    captured: dict[str, str] = {}

    def fake_extract_from_text(*, content, context="", focus_entities=None, api_key="", provider="", model=""):
        captured["content"] = content
        captured["api_key"] = api_key
        captured["provider"] = provider
        captured["model"] = model
        return SimpleNamespace(
            entities=[],
            relationships=[],
            signals=[],
            contract_references=[],
            advisory_flags=[],
            elapsed_ms=1,
            error="",
        )

    monkeypatch.setattr(axiom_extractor, "extract_from_text", fake_extract_from_text)

    with server.app.test_client() as client:
        response = client.post(
            "/api/axiom/extract",
            json={"content": "SMX appears alongside two possible contractor names."},
        )

    assert response.status_code == 200
    assert captured["content"] == "SMX appears alongside two possible contractor names."
    assert captured["provider"] == "anthropic"
    assert captured["model"] == "claude-sonnet-4-6"
    assert captured["api_key"] == "sk-test-anthropic-route"


def test_axiom_search_ingest_uses_dev_fallback_without_provider_key(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    server = _reload_module("server")

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    with server.app.test_client() as client:
        response = client.post(
            "/api/axiom/search/ingest",
            json={
                "prime_contractor": "SMX",
                "vehicle_name": "ILS 2",
                "context": "Pressure ownership first.",
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "completed"
    assert payload["provider_backed"] is False
    assert payload["fallback_active"] is True
    assert payload["local_fallback"]["mode"] == "deterministic_dev_pressure"
    assert payload["entities"][0]["name"] == "SMX"
    assert payload["intelligence_gaps"]
    assert payload["kg_ingestion"]["entities_created"] == 0
    assert payload["kg_ingestion"]["status"] == "degraded"
    assert payload["runtime"]["fallback_active"] is True
    assert payload["readiness_contract"]["status"] == "degraded"
    assert payload["readiness_status"] == "degraded"
    assert payload["blocking_failures"] == []
    assert payload["usable_surface_count"] >= 1
    assert payload["connector_accounting"]["connector_calls_attempted"] == 0


def test_axiom_search_ingest_honors_explicit_lane_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-anthropic-route")

    server = _reload_module("server")
    axiom_agent = _reload_module("axiom_agent")

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    captured: dict[str, str] = {}

    def fake_run_agent(*, target, provider="", model="", user_id="", provider_locked=False, model_locked=False, lane_id=""):
        captured["lane_id"] = lane_id
        return axiom_agent.AgentResult(
            target=target,
            runtime={
                "lane_id": lane_id,
                "provider_requested": provider,
                "model_requested": model,
                "provider_used": provider,
                "model_used": model,
                "provider_backed": True,
                "fallback_active": False,
            },
        )

    monkeypatch.setattr(axiom_agent, "run_agent", fake_run_agent)
    monkeypatch.setattr(
        axiom_agent,
        "ingest_agent_result",
        lambda result, vendor_id="": {
            "entities_created": 0,
            "relationships_created": 0,
            "claims_created": 0,
            "evidence_created": 0,
        },
    )

    with server.app.test_client() as client:
        response = client.post(
            "/api/axiom/search/ingest",
            json={
                "prime_contractor": "Parsons Corporation",
                "lane_id": "edge_collection",
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert captured["lane_id"] == "edge_collection"
    assert payload["runtime"]["lane_id"] == "edge_collection"


def test_axiom_search_promotes_readiness_status_to_top_level(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-search-readiness.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-anthropic-route")

    server = _reload_module("server")
    axiom_agent = _reload_module("axiom_agent")

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    def fake_run_agent(*, target, provider="", model="", user_id="", provider_locked=False, model_locked=False, lane_id=""):
        return axiom_agent.AgentResult(
            target=target,
            entities=[
                axiom_agent.DiscoveredEntity(name="Parsons Corporation", entity_type="company", confidence=0.9),
                axiom_agent.DiscoveredEntity(name="Department of Defense", entity_type="government_agency", confidence=0.82),
            ],
            relationships=[
                axiom_agent.DiscoveredRelationship("Parsons Corporation", "Department of Defense", "contracts_with", 0.88),
                axiom_agent.DiscoveredRelationship("Parsons Corporation", "PARSON CORP", "former_name", 0.92),
            ],
            iterations=[
                axiom_agent.SearchIteration(
                    iteration=1,
                    connector_calls=[
                        {"success": True, "findings_count": 1, "has_data": True},
                        {"success": True, "relationship_count": 1, "has_data": True},
                        {"success": True, "identifiers": {"uei": "uei-1"}, "has_data": True},
                    ],
                )
            ],
            runtime={
                "lane_id": lane_id,
                "provider_requested": provider,
                "model_requested": model,
                "provider_used": provider,
                "model_used": model,
                "provider_backed": True,
                "fallback_active": False,
            },
        )

    monkeypatch.setattr(axiom_agent, "run_agent", fake_run_agent)

    with server.app.test_client() as client:
        response = client.post(
            "/api/axiom/search",
            json={
                "prime_contractor": "Parsons Corporation",
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "lane_id": "mission_command",
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["provider_backed"] is True
    assert payload["fallback_active"] is False
    assert payload["readiness_contract"]["status"] == "ready"
    assert payload["readiness_status"] == "ready"
    assert payload["blocking_failures"] == []
    assert payload["usable_surface_count"] >= 1
    assert payload["evidence_actions_attempted"] == 3


def test_axiom_search_normalizes_gap_payload_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-search-gaps.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-anthropic-route")

    server = _reload_module("server")
    axiom_agent = _reload_module("axiom_agent")

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    def fake_run_agent(*, target, provider="", model="", user_id="", provider_locked=False, model_locked=False, lane_id=""):
        return axiom_agent.AgentResult(
            target=target,
            intelligence_gaps=[
                {
                    "gap": "Prime vehicle and teammate visibility stayed weak on the first pass.",
                    "fillable_by": "automated_search",
                    "priority": "high",
                },
                {
                    "description": "Control path is still unresolved.",
                    "gap_type": "ownership_control",
                    "confidence": 0.82,
                    "priority": "high",
                },
            ],
            runtime={
                "lane_id": lane_id,
                "provider_requested": provider,
                "model_requested": model,
                "provider_used": provider,
                "model_used": model,
                "provider_backed": True,
                "fallback_active": False,
            },
        )

    monkeypatch.setattr(axiom_agent, "run_agent", fake_run_agent)

    with server.app.test_client() as client:
        response = client.post(
            "/api/axiom/search",
            json={
                "prime_contractor": "Kavaliro",
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "lane_id": "mission_command",
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["intelligence_gaps"][0]["description"] == "Prime vehicle and teammate visibility stayed weak on the first pass."
    assert payload["intelligence_gaps"][0]["gap_type"] == "vehicle_lineage"
    assert payload["intelligence_gaps"][1]["gap_type"] == "ownership_control"
    assert payload["intelligence_gaps"][1]["confidence"] == 0.82


def test_save_ai_config_accepts_gpt41(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_SECRET_KEY", "test-secret-key")

    ai_analysis = _reload_module("ai_analysis")

    ai_analysis.init_ai_tables()
    ai_analysis.save_ai_config("gpt41-user", "openai", "gpt-4.1", "sk-test-openai")

    saved = ai_analysis.get_ai_config("gpt41-user")
    assert saved is not None
    assert saved["provider"] == "openai"
    assert saved["model"] == "gpt-4.1"
