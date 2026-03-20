#!/usr/bin/env python3
"""
Validate that a Markdown handoff contains the required sections.

Usage:
  python3 scripts/validate_handoff.py docs/AGENT_HANDOFF_TEMPLATE.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


REQUIRED_HEADINGS = [
    "Metadata",
    "Objective",
    "What Changed",
    "Files Changed",
    "API And Contract Changes",
    "Env Vars And Runtime Assumptions",
    "Data, ML, And Migrations",
    "Verification",
    "Not Verified",
    "Known Risks And Sharp Edges",
    "Questions For The Next Agent",
    "Recommended Next Actions",
]


def extract_headings(text: str) -> set[str]:
    headings: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^##\s+(.*\S)\s*$", line)
        if match:
            headings.add(match.group(1).strip())
    return headings


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/validate_handoff.py <path-to-markdown>")
        return 2

    path = Path(sys.argv[1]).expanduser().resolve()
    if not path.exists():
        print(f"FAIL: file not found: {path}")
        return 2

    text = path.read_text(encoding="utf-8")
    headings = extract_headings(text)
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in headings]

    if missing:
        print(f"FAIL: handoff is missing {len(missing)} required section(s):")
        for heading in missing:
            print(f"- {heading}")
        return 1

    print(f"PASS: {path} contains all required handoff sections.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
