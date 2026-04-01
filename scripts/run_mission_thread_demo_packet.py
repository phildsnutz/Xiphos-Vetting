#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from render_mission_thread_briefing import render_markdown
from seed_mission_thread_fixture import DEFAULT_FIXTURE_PATH, seed_fixture_by_id

import mission_thread_briefing


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "mission_thread_demo"


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", _normalize_text(value).lower()).strip("-")
    return cleaned or "mission-thread"


def _walkthrough_steps(briefing: dict[str, Any]) -> list[str]:
    thread = dict(briefing.get("mission_thread") or {})
    brittle = list(briefing.get("top_brittle_members") or [])
    exposures = list(briefing.get("top_control_path_exposures") or [])
    mitigations = list(briefing.get("recommended_mitigations") or [])
    steps = [
        f"Open the '{_normalize_text(thread.get('name') or thread.get('id'))}' mission thread in the Threads tab.",
        "Lead with the operator brief and explain why this thread matters in contested sustainment terms.",
    ]
    if brittle:
        steps.append(f"Click the top brittle member '{_normalize_text(brittle[0].get('label'))}' and explain why it is mission-critical.")
    if exposures:
        top = exposures[0]
        steps.append(
            f"Show the control-path exposure '{_normalize_text(top.get('source_label'))} -> {_normalize_text(top.get('target_label'))}' to ground the risk in evidence."
        )
    if mitigations:
        steps.append(f"Close on the recommended mitigation '{_normalize_text(mitigations[0])}'.")
    return steps


def build_demo_packet(
    *,
    fixture_id: str | None = None,
    thread_id: str | None = None,
    fixture_path: str | Path = DEFAULT_FIXTURE_PATH,
    output_root: str | Path = DEFAULT_REPORT_DIR,
    depth: int = 2,
    mode: str = "control",
) -> dict[str, Any]:
    resolved_thread_id = _normalize_text(thread_id)
    fixture_summary = None
    if fixture_id:
      fixture_summary = seed_fixture_by_id(fixture_id, fixture_path=fixture_path, depth=depth)
      resolved_thread_id = _normalize_text(fixture_summary.get("thread_id"))
    if not resolved_thread_id:
        raise ValueError("thread_id or fixture_id is required")

    briefing = mission_thread_briefing.build_mission_thread_briefing(
        resolved_thread_id,
        depth=depth,
        member_passport_mode=mode,
    )
    if briefing is None:
        raise LookupError(f"Mission thread not found: {resolved_thread_id}")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    thread_name = _normalize_text((briefing.get("mission_thread") or {}).get("name") or resolved_thread_id)
    output_dir = Path(output_root) / f"{_slugify(thread_name)}-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    packet = {
        "packet_version": "mission-thread-demo-packet-v1",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "fixture_id": _normalize_text(fixture_id),
        "thread_id": resolved_thread_id,
        "thread_name": thread_name,
        "operator_readout": _normalize_text(briefing.get("operator_readout")),
        "walkthrough_steps": _walkthrough_steps(briefing),
        "briefing": briefing,
        "seed_summary": fixture_summary,
    }

    summary_json_path = output_dir / "summary.json"
    summary_md_path = output_dir / "summary.md"
    briefing_json_path = output_dir / "briefing.json"
    briefing_md_path = output_dir / "briefing.md"

    summary_json_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    summary_md_path.write_text(
        "\n".join(
            [
                f"# {thread_name}",
                "",
                _normalize_text(briefing.get("operator_readout")),
                "",
                "## Walkthrough",
                *[f"{idx}. {step}" for idx, step in enumerate(packet["walkthrough_steps"], start=1)],
                "",
                "## Top Brittle Members",
                *[
                    f"- {_normalize_text(item.get('label'))}: brittle={item.get('brittle_node_score')} action={_normalize_text(item.get('recommended_action'))}"
                    for item in list(briefing.get("top_brittle_members") or [])[:5]
                ],
                "",
                "## Top Control Path Exposures",
                *[
                    f"- {_normalize_text(item.get('source_label'))} -> {_normalize_text(item.get('target_label'))} [{_normalize_text(item.get('rel_type'))}]"
                    for item in list(briefing.get("top_control_path_exposures") or [])[:5]
                ],
            ]
        ).rstrip()
        + "\n",
        encoding="utf-8",
    )
    briefing_json_path.write_text(json.dumps(briefing, indent=2), encoding="utf-8")
    briefing_md_path.write_text(render_markdown(briefing), encoding="utf-8")

    packet["artifacts"] = {
        "output_dir": str(output_dir),
        "summary_json": str(summary_json_path),
        "summary_md": str(summary_md_path),
        "briefing_json": str(briefing_json_path),
        "briefing_md": str(briefing_md_path),
    }
    summary_json_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    return packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a local mission-thread demo packet from a seeded fixture or existing thread.")
    parser.add_argument("--fixture-id", help="Fixture id to seed and package.")
    parser.add_argument("--thread-id", help="Existing mission thread id to package.")
    parser.add_argument("--fixture-path", default=str(DEFAULT_FIXTURE_PATH), help="Fixture pack path.")
    parser.add_argument("--output-root", default=str(DEFAULT_REPORT_DIR), help="Report output root directory.")
    parser.add_argument("--depth", type=int, default=2, help="Graph depth for briefing generation.")
    parser.add_argument("--mode", default="control", help="Passport mode for briefing member cards.")
    parser.add_argument("--json", action="store_true", help="Print packet JSON to stdout.")
    args = parser.parse_args(argv)

    packet = build_demo_packet(
        fixture_id=args.fixture_id,
        thread_id=args.thread_id,
        fixture_path=args.fixture_path,
        output_root=args.output_root,
        depth=args.depth,
        mode=args.mode,
    )

    if args.json:
        print(json.dumps(packet, indent=2))
    else:
        print(packet["artifacts"]["summary_md"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
