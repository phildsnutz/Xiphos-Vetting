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


def test_axiom_extract_route_uses_env_fallback_when_ai_config_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-route")

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
    assert captured["provider"] == "openai"
    assert captured["model"] == "gpt-4o"
    assert captured["api_key"] == "sk-test-openai-route"
