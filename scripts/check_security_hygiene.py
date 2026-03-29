#!/usr/bin/env python3
"""Check the workspace for high-risk shareability regressions."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_PLACEHOLDER_FILES = {
    ROOT / "backups" / "README.md",
    ROOT / "vps_snapshot" / "README.md",
}
DISALLOWED_PATHS = [
    ROOT / "deploy.env",
    ROOT / ".env",
    ROOT / ".env.local",
    ROOT / "CODEX_HANDOFF_20260322.md.orig",
]
SENSITIVE_MARKERS = [
    "Key passphrase:",
    "admin login:",
]
SOURCE_GLOBS = ("*.py", "*.sh")
DISALLOWED_SOURCE_LITERALS = (
    "helios2026",
)


def _unexpected_dir_contents(path: Path) -> list[str]:
    if not path.exists():
        return []
    violations: list[str] = []
    for child in path.rglob("*"):
        if child.is_dir():
            continue
        if child not in ALLOWED_PLACEHOLDER_FILES:
            violations.append(f"Sensitive artifact still present in workspace: {child.relative_to(ROOT)}")
    return violations


def check_workspace() -> list[str]:
    violations: list[str] = []

    for path in DISALLOWED_PATHS:
        if path.exists():
            violations.append(f"Sensitive file should not be present in shareable workspace: {path.relative_to(ROOT)}")

    violations.extend(_unexpected_dir_contents(ROOT / "backups"))
    violations.extend(_unexpected_dir_contents(ROOT / "vps_snapshot"))

    handoff = ROOT / "CODEX_HANDOFF_20260322.md"
    if handoff.exists():
        content = handoff.read_text(encoding="utf-8", errors="ignore")
        for marker in SENSITIVE_MARKERS:
            if marker in content:
                violations.append(f"Sanitized handoff still contains sensitive marker: {marker}")

    source_roots = [
        ROOT,
        ROOT / "backend",
        ROOT / "demos",
        ROOT / "scripts",
        ROOT / "tests",
    ]
    seen_files: set[Path] = set()
    for base in source_roots:
        if not base.exists():
            continue
        for pattern in SOURCE_GLOBS:
            for path in base.rglob(pattern):
                if path in seen_files or not path.is_file():
                    continue
                if path == Path(__file__).resolve():
                    continue
                seen_files.add(path)
                content = path.read_text(encoding="utf-8", errors="ignore")
                for literal in DISALLOWED_SOURCE_LITERALS:
                    if literal in content:
                        violations.append(
                            f"Executable source still contains disallowed literal '{literal}': {path.relative_to(ROOT)}"
                        )

    return violations


def main() -> int:
    violations = check_workspace()
    if violations:
        print(json.dumps({"status": "failed", "violations": violations}, indent=2))
        return 1
    print(json.dumps({"status": "ok", "violations": []}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
