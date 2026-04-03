"""Helpers for loading secure local runtime env files without committing secrets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


CONFIG_DIR = Path(os.environ.get("XIPHOS_CONFIG_DIR", "~/.config/xiphos")).expanduser()
DEFAULT_HELIOS_ENV_PATH = CONFIG_DIR / "helios.env"


def runtime_env_path_candidates(explicit_path: str = "") -> list[Path]:
    """Return candidate env files for secure local runtime settings."""
    candidates: list[Path] = []
    explicit = explicit_path.strip()
    env_override = os.environ.get("XIPHOS_RUNTIME_ENV_FILE", "").strip()

    if explicit:
        raw_paths = (explicit,)
    else:
        raw_paths = (env_override, str(DEFAULT_HELIOS_ENV_PATH))

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
    for path in runtime_env_path_candidates(explicit_path):
        if not path.exists():
            continue

        payload = _parse_env_file(path)
        injected_keys: list[str] = []
        for key, value in payload.items():
            if override or not os.environ.get(key, "").strip():
                os.environ[key] = value
                injected_keys.append(key)

        return {
            "loaded": True,
            "path": str(path.resolve()),
            "paths_checked": checked_paths,
            "available_keys": sorted(payload.keys()),
            "injected_keys": sorted(injected_keys),
        }

    return {
        "loaded": False,
        "path": "",
        "paths_checked": checked_paths,
        "available_keys": [],
        "injected_keys": [],
    }
