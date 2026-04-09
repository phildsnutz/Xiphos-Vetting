from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import secure_runtime_env
from secure_runtime_env import load_runtime_env


def test_load_runtime_env_reads_explicit_file(tmp_path, monkeypatch):
    env_path = tmp_path / "helios.env"
    env_path.write_text(
        "\n".join(
            [
                "NEO4J_URI=neo4j+s://example.databases.neo4j.io",
                "NEO4J_USER=test-user",
                "NEO4J_PASSWORD=secret",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USER", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    result = load_runtime_env(str(env_path))

    assert result["loaded"] is True
    assert result["path"] == str(env_path.resolve())
    assert result["available_keys"] == ["NEO4J_PASSWORD", "NEO4J_URI", "NEO4J_USER"]
    assert "NEO4J_URI" in result["injected_keys"]


def test_load_runtime_env_reports_missing_file(tmp_path):
    result = load_runtime_env(str(tmp_path / "missing.env"))

    assert result["loaded"] is False
    assert result["path"] == ""
    assert result["available_keys"] == []


def test_load_runtime_env_falls_back_to_repo_deploy_env(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    deploy_env_path = repo_dir / "deploy.env"
    deploy_env_path.write_text("XIPHOS_SAM_API_KEY=sam-auto-test\n", encoding="utf-8")

    monkeypatch.delenv("XIPHOS_RUNTIME_ENV_FILE", raising=False)
    monkeypatch.delenv("XIPHOS_SAM_API_KEY", raising=False)
    monkeypatch.setattr(secure_runtime_env, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(secure_runtime_env, "DEFAULT_DEPLOY_ENV_PATH", config_dir / "deploy.env")
    monkeypatch.setattr(secure_runtime_env, "DEFAULT_HELIOS_ENV_PATH", config_dir / "helios.env")
    monkeypatch.setattr(secure_runtime_env, "REPO_DEPLOY_ENV_PATH", deploy_env_path)

    result = secure_runtime_env.load_runtime_env()

    assert result["loaded"] is True
    assert result["path"] == str(deploy_env_path.resolve())
    assert "XIPHOS_SAM_API_KEY" in result["available_keys"]
    assert os.environ["XIPHOS_SAM_API_KEY"] == "sam-auto-test"
