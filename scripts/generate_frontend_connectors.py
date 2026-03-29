#!/usr/bin/env python3
"""Generate frontend connector metadata from the canonical backend registry."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_CONNECTORS = REPO_ROOT / "frontend" / "src" / "lib" / "connectors.ts"
sys.path.insert(0, str(BACKEND_DIR))

from osint.connector_registry import get_frontend_connector_meta  # type: ignore


def render_frontend_connector_ts() -> str:
    meta = get_frontend_connector_meta()
    lines = [
        "// Generated from backend/osint/connector_registry.py. Do not edit manually.",
        "export const CONNECTOR_META = {",
    ]
    for name, entry in meta.items():
        lines.append(
            f"  {name}: {{ label: {json.dumps(entry['label'])}, category: {json.dumps(entry['category'])}, description: {json.dumps(entry['description'])} }},"
        )
    lines.extend(
        [
            "} as const;",
            "",
            "export type ConnectorName = keyof typeof CONNECTOR_META;",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    FRONTEND_CONNECTORS.write_text(render_frontend_connector_ts(), encoding="utf-8")
    print(f"Wrote {FRONTEND_CONNECTORS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
