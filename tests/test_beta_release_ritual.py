from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("/Users/tyegonzalez/Desktop/Helios-Package Merged/scripts/run_beta_release_ritual.py")
spec = importlib.util.spec_from_file_location("beta_release_ritual", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def _args(**overrides):
    values = {
        "base_url": "https://helios.xiphosllc.com",
        "email": "",
        "password": "",
        "token": "",
        "report_dir": "/tmp/reports",
        "print_json": False,
    }
    values.update(overrides)
    return module.argparse.Namespace(**values)


def test_current_product_prefers_token_when_available(monkeypatch):
    captured: dict[str, list[str]] = {}

    class FakeProc:
        returncode = 0
        stdout = json.dumps({"overall_verdict": "PASS"})
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        return FakeProc()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    args = _args(email="ops@example.com", password="secret")

    payload = module._run_json_script(module.CURRENT_PRODUCT_SCRIPT, args, "cached-token")

    assert payload["overall_verdict"] == "PASS"
    assert "--token" in captured["command"]
    assert "cached-token" in captured["command"]
    assert "--email" in captured["command"]
    assert "--password" in captured["command"]


def test_current_product_falls_back_to_credentials_without_token(monkeypatch):
    captured: dict[str, list[str]] = {}

    class FakeProc:
        returncode = 0
        stdout = json.dumps({"overall_verdict": "PASS"})
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        return FakeProc()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    args = _args(email="ops@example.com", password="secret")

    payload = module._run_json_script(module.CURRENT_PRODUCT_SCRIPT, args, "")

    assert payload["overall_verdict"] == "PASS"
    assert "--email" in captured["command"]
    assert "--password" in captured["command"]
    assert "--token" not in captured["command"]


def test_query_to_dossier_keeps_token_and_spec(monkeypatch):
    captured: dict[str, list[str]] = {}

    class FakeProc:
        returncode = 0
        stdout = json.dumps({"overall_verdict": "PASS"})
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        return FakeProc()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    args = _args(email="ops@example.com", password="secret")

    payload = module._run_json_script(module.QUERY_TO_DOSSIER_SCRIPT, args, "cached-token")

    assert payload["overall_verdict"] == "PASS"
    assert "--token" in captured["command"]
    assert "cached-token" in captured["command"]
    assert "--spec-file" in captured["command"]
