"""HTTP trust helpers for local collector workflows."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


_DISABLE_VALUES = {"0", "false", "no", "off"}
_TRUSTSTORE_ATTEMPTED = False
_TRUSTSTORE_READY = False


def _bundle_from_env(env_names: Iterable[str]) -> str | None:
    for env_name in env_names:
        raw = (os.environ.get(env_name) or "").strip()
        if not raw:
            continue
        return str(Path(raw).expanduser())
    return None


def _install_system_truststore_if_available() -> bool:
    global _TRUSTSTORE_ATTEMPTED, _TRUSTSTORE_READY
    if _TRUSTSTORE_ATTEMPTED:
        return _TRUSTSTORE_READY

    _TRUSTSTORE_ATTEMPTED = True
    try:
        import truststore  # type: ignore

        truststore.inject_into_ssl()
        _TRUSTSTORE_READY = True
    except Exception:
        _TRUSTSTORE_READY = False
    return _TRUSTSTORE_READY


def resolve_verify_target(
    *,
    verify_env: str,
    bundle_envs: Iterable[str] = (),
) -> bool | str:
    raw_verify = (os.environ.get(verify_env) or "true").strip().lower()
    if raw_verify in _DISABLE_VALUES:
        return False

    bundle = _bundle_from_env([*bundle_envs, "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"])
    if bundle:
        return bundle

    _install_system_truststore_if_available()
    return True
