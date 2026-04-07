from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("/Users/tyegonzalez/Desktop/Helios-Package Merged/scripts/run_vehicle_intelligence_canary.py")
spec = importlib.util.spec_from_file_location("vehicle_intelligence_canary", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_login_headers_accepts_valid_token(monkeypatch):
    monkeypatch.setattr(module, "_validate_token", lambda base_url, token: token == "good-token")

    headers = module.login_headers("https://helios.xiphosllc.com", "", "", "good-token")

    assert headers == {"Authorization": "Bearer good-token"}


def test_login_headers_falls_back_to_login_when_token_is_stale(monkeypatch):
    def fake_request_json(base_url, method, path, payload=None, headers=None, timeout=90):
        assert path == "/api/auth/login"
        return 200, {}, {"token": "fresh-token"}

    monkeypatch.setattr(module, "_validate_token", lambda base_url, token: False)
    monkeypatch.setattr(module, "request_json", fake_request_json)

    headers = module.login_headers("https://helios.xiphosllc.com", "ops@example.com", "secret", "stale-token")

    assert headers == {"Authorization": "Bearer fresh-token"}


def test_login_headers_rejects_invalid_token_without_credentials(monkeypatch):
    monkeypatch.setattr(module, "_validate_token", lambda base_url, token: False)

    try:
        module.login_headers("https://helios.xiphosllc.com", "", "", "stale-token")
    except RuntimeError as exc:
        assert "invalid or expired" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for stale token")
