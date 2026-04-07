"""Lightweight HTTP transport helpers for collector workflows."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Mapping


def curl_json_get(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[dict | list | None, dict]:
    """Fetch JSON over curl to avoid slow Python TLS/socket behavior on some hosts."""
    curl_path = shutil.which("curl")
    if not curl_path:
        return None, {
            "status": 0,
            "throttled": False,
            "error": "curl is not available on this system.",
        }

    timeout_s = max(float(timeout_seconds), 0.1)
    connect_timeout_s = max(min(timeout_s, 3.0), 0.1)
    cmd = [
        curl_path,
        "--silent",
        "--show-error",
        "--location",
        "--ipv4",
        "--http1.1",
        "--max-time",
        f"{timeout_s:.3f}",
        "--connect-timeout",
        f"{connect_timeout_s:.3f}",
        "--write-out",
        "\n__XIPHOS_HTTP_STATUS__:%{http_code}",
        url,
    ]
    for key, value in (headers or {}).items():
        cmd.extend(["-H", f"{key}: {value}"])

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return None, {
            "status": 0,
            "throttled": False,
            "error": f"curl transport unavailable: {exc}",
        }

    stdout = completed.stdout or ""
    marker = "\n__XIPHOS_HTTP_STATUS__:"
    body, _, status_text = stdout.rpartition(marker)
    if not status_text:
        return None, {
            "status": 0,
            "throttled": False,
            "error": (completed.stderr or "curl transport returned no status marker.").strip(),
        }

    try:
        status = int(status_text.strip() or "0")
    except ValueError:
        status = 0

    parsed = None
    raw_body = body.strip()
    if raw_body:
        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError:
            parsed = None

    error = ""
    if completed.returncode != 0:
        error = (completed.stderr or "").strip() or f"curl exited with status {completed.returncode}."

    return parsed, {
        "status": status,
        "throttled": False,
        "error": error,
        "raw_body": raw_body[:500],
    }


def curl_json_get_to_file(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[dict | list | None, dict]:
    """Fetch JSON through a temp file to avoid large stdout pipe overhead."""
    curl_path = shutil.which("curl")
    if not curl_path:
        return None, {
            "status": 0,
            "throttled": False,
            "error": "curl is not available on this system.",
        }

    timeout_s = max(float(timeout_seconds), 0.1)
    connect_timeout_s = max(min(timeout_s, 3.0), 0.1)
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        body_path = tmp.name

    cmd = [
        curl_path,
        "--silent",
        "--show-error",
        "--location",
        "--ipv4",
        "--http1.1",
        "--max-time",
        f"{timeout_s:.3f}",
        "--connect-timeout",
        f"{connect_timeout_s:.3f}",
        "--output",
        body_path,
        "--write-out",
        "%{http_code}",
        url,
    ]
    for key, value in (headers or {}).items():
        cmd.extend(["-H", f"{key}: {value}"])

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        status_text = (completed.stdout or "").strip()
        try:
            status = int(status_text or "0")
        except ValueError:
            status = 0

        raw_body = ""
        parsed = None
        if os.path.exists(body_path):
            with open(body_path, "r", encoding="utf-8") as handle:
                raw_body = handle.read()
            if raw_body:
                try:
                    parsed = json.loads(raw_body)
                except json.JSONDecodeError:
                    parsed = None

        error = ""
        if completed.returncode != 0:
            error = (completed.stderr or "").strip() or f"curl exited with status {completed.returncode}."

        return parsed, {
            "status": status,
            "throttled": False,
            "error": error,
            "raw_body": raw_body[:500],
        }
    except Exception as exc:
        return None, {
            "status": 0,
            "throttled": False,
            "error": f"curl transport unavailable: {exc}",
        }
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass
