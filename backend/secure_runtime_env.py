"""Helpers for loading secure local runtime env files without committing secrets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


CONFIG_DIR = Path(os.environ.get("XIPHOS_CONFIG_DIR", "~/.config/xiphos")).expanduser()
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEPLOY_ENV_PATH = CONFIG_DIR / "deploy.env"
DEFAULT_HELIOS_ENV_PATH = CONFIG_DIR / "helios.env"
REPO_DEPLOY_ENV_PATH = REPO_ROOT / "deploy.env"


def runtime_env_path_candidates(explicit_path: str = "") -> list[Path]:
    """Return candidate env files for secure local runtime settings."""
    candidates: list[Path] = []
    explicit = explicit_path.strip()
    env_override = os.environ.get("XIPHOS_RUNTIME_ENV_FILE", "").strip()

    if explicit:
        raw_paths = (explicit,)
    elif env_override:
        raw_paths = (env_override,)
    else:
        raw_paths = (
            str(DEFAULT_DEPLOY_ENV_PATH),
            str(REPO_DEPLOY_ENV_PATH),
            str(DEFAULT_HELIOS_ENV_PATH),
        )

    for raw in raw_paths:
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path not in candidates:
            candidates.append(path)
    return candidates


def _parse_env_file(path: Path) -> dict[str, str]:
    payload: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        payload[key.strip()] = value.strip().strip("'").strip('"')
    return payload


def load_runtime_env(explicit_path: str = "", *, override: bool = False) -> dict[str, Any]:
    """
    Load secure local runtime env into ``os.environ``.

    Returns a sanitized summary that is safe to log or surface in reports.
    """
    checked_paths = [str(path) for path in runtime_env_path_candidates(explicit_path)]
    loaded_paths: list[str] = []
    available_keys: set[str] = set()
    injected_keys: list[str] = []
    for path in runtime_env_path_candidates(explicit_path):
        if not path.exists():
            continue

        payload = _parse_env_file(path)
        loaded_paths.append(str(path.resolve()))
        available_keys.update(payload.keys())
        for key, value in payload.items():
            if override or not os.environ.get(key, "").strip():
                os.environ[key] = value
                injected_keys.append(key)

    if loaded_paths:
        return {
            "loaded": True,
            "path": loaded_paths[0],
            "loaded_paths": loaded_paths,
            "paths_checked": checked_paths,
            "available_keys": sorted(available_keys),
            "injected_keys": sorted(injected_keys),
        }

    return {
        "loaded": False,
        "path": "",
        "loaded_paths": [],
        "paths_checked": checked_paths,
        "available_keys": [],
        "injected_keys": [],
    }


def ensure_runtime_env_loaded(
    required_keys: tuple[str, ...] = (),
    explicit_path: str = "",
    *,
    override: bool = False,
) -> dict[str, Any]:
    """
    Best-effort runtime env bootstrap for direct module use.

    This avoids the common local failure mode where deploy/server helpers know
    about secure env files but one-off connector imports do not.
    """
    normalized_keys = tuple(str(key or "").strip() for key in required_keys if str(key or "").strip())
    checked_paths = [str(path) for path in runtime_env_path_candidates(explicit_path)]
    if normalized_keys and any(os.environ.get(key, "").strip() for key in normalized_keys):
        return {
            "loaded": False,
            "path": "",
            "loaded_paths": [],
            "paths_checked": checked_paths,
            "available_keys": [],
            "injected_keys": [],
            "already_present": True,
        }

    result = load_runtime_env(explicit_path, override=override)
    result["already_present"] = False
    return result
