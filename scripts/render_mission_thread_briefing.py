#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import mission_thread_briefing
from seed_mission_thread_fixture import DEFAULT_FIXTURE_PATH, seed_fixture_by_id


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def render_markdown(briefing: dict) -> str:
    mission_thread = dict(briefing.get("mission_thread") or {})
    overview = dict(briefing.get("overview") or {})
    lines = [
        f"# {mission_thread.get('name') or briefing.get('mission_thread', {}).get('id')}",
        "",
        _normalize_text(briefing.get("operator_readout")),
        "",
        "## Overview",
        f"- Theater: {_normalize_text(mission_thread.get('theater') or 'unknown')}",
        f"- Mission type: {_normalize_text(mission_thread.get('mission_type') or 'unknown')}",
        f"- Members: {int(overview.get('member_count') or 0)}",
        f"- Entities: {int(overview.get('entity_count') or 0)}",
        f"- Relationships: {int(overview.get('relationship_count') or 0)}",
        "",
        "## Top Brittle Members",
    ]
    for row in briefing.get("top_brittle_members") or []:
        lines.append(
            f"- {_normalize_text(row.get('label'))}: brittle={row.get('brittle_node_score')} criticality={row.get('criticality')} action={_normalize_text(row.get('recommended_action'))}"
        )
    lines.extend(["", "## Top Control Path Exposures"])
    for row in briefing.get("top_control_path_exposures") or []:
        lines.append(
            f"- {_normalize_text(row.get('source_label'))} -> {_normalize_text(row.get('target_label'))} [{_normalize_text(row.get('rel_type'))}] score={row.get('intelligence_score')}"
        )
    lines.extend(["", "## Evidence Gaps"])
    for row in briefing.get("unresolved_evidence_gaps") or []:
        lines.append(f"- {_normalize_text(row.get('detail'))}")
    lines.extend(["", "## Recommended Mitigations"])
    for item in briefing.get("recommended_mitigations") or []:
        lines.append(f"- {_normalize_text(item)}")
    return "\n".join(lines).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a mission-thread briefing packet from a thread id or fixture.")
    parser.add_argument("--thread-id", help="Existing mission thread id to render.")
    parser.add_argument("--fixture-id", help="Fixture id to seed before rendering.")
    parser.add_argument("--fixture-path", default=str(DEFAULT_FIXTURE_PATH), help="Mission-thread fixture pack path.")
    parser.add_argument("--depth", type=int, default=2, help="Graph depth for the briefing.")
    parser.add_argument("--mode", default="control", help="Member passport mode for the briefing.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    parser.add_argument("--out", help="Optional output file path.")
    args = parser.parse_args(argv)

    thread_id = _normalize_text(args.thread_id)
    if args.fixture_id:
        seeded = seed_fixture_by_id(args.fixture_id, fixture_path=args.fixture_path, depth=args.depth)
        thread_id = _normalize_text(seeded.get("thread_id"))
    if not thread_id:
        parser.error("--thread-id or --fixture-id is required")

    briefing = mission_thread_briefing.build_mission_thread_briefing(
        thread_id,
        depth=args.depth,
        member_passport_mode=args.mode,
    )
    if briefing is None:
        parser.error(f"Mission thread not found: {thread_id}")

    payload = json.dumps(briefing, indent=2, sort_keys=True) if args.json else render_markdown(briefing)
    if args.out:
        output_path = Path(args.out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
