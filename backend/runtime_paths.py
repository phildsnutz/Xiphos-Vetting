"""
Runtime path and secret helpers for Xiphos.

Keeps mutable data out of source directories by default and centralizes
the environment contract for database/cache locations and secrets.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path


_PLACEHOLDER_SECRETS = {
    "",
    "CHANGE-ME-IN-PRODUCTION",
    "xiphos-dev-secret",
    "xiphos-dev-secret-change-in-production",
}
_EPHEMERAL_SECRETS: dict[str, str] = {}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (_project_root() / path).resolve()
    return path


def get_data_dir() -> str:
    configured = os.environ.get("XIPHOS_DATA_DIR", "").strip()
    path = _resolve_path(configured) if configured else (_project_root() / "var").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _path_from_env(env_var: str, filename: str) -> str:
    configured = os.environ.get(env_var, "").strip()
    path = _resolve_path(configured) if configured else Path(get_data_dir()) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_main_db_path() -> str:
    return _path_from_env("XIPHOS_DB_PATH", "xiphos.db")


def get_kg_db_path() -> str:
    return _path_from_env("XIPHOS_KG_DB_PATH", "knowledge_graph.db")


def get_sanctions_db_path() -> str:
    return _path_from_env("XIPHOS_SANCTIONS_DB", "sanctions.db")


def get_cache_dir() -> str:
    configured = os.environ.get("XIPHOS_CACHE_DIR", "").strip()
    path = _resolve_path(configured) if configured else Path(get_data_dir()) / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_secure_artifacts_dir() -> str:
    configured = os.environ.get("XIPHOS_SECURE_ARTIFACTS_DIR", "").strip()
    path = _resolve_path(configured) if configured else Path(get_data_dir()) / "secure_artifacts"
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return str(path)


def is_placeholder_secret(value: str | None) -> bool:
    return (value or "").strip() in _PLACEHOLDER_SECRETS


def get_secret(env_var: str, *, allow_ephemeral_dev: bool = False) -> str:
    value = os.environ.get(env_var, "").strip()
    if not is_placeholder_secret(value):
        return value

    if allow_ephemeral_dev:
        return _EPHEMERAL_SECRETS.setdefault(env_var, secrets.token_urlsafe(32))

    return ""


def get_ai_config_secret() -> str:
    ai_secret = get_secret("XIPHOS_AI_CONFIG_KEY")
    if ai_secret:
        return ai_secret

    auth_secret = get_secret("XIPHOS_SECRET_KEY")
    if auth_secret:
        return auth_secret

    dev_mode = os.environ.get("XIPHOS_DEV_MODE", "false").lower() == "true"
    auth_enabled = os.environ.get("XIPHOS_AUTH_ENABLED", "false").lower() == "true"
    if dev_mode and not auth_enabled:
        return get_secret("XIPHOS_AI_CONFIG_KEY", allow_ephemeral_dev=True)

    return ""
