from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

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
