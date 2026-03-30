#!/usr/bin/env python3
"""
Review the current graph-training predicted-link cohort against the fixture
gold set and hard-negative set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from graph_embeddings import (  # noqa: E402
    GRAPH_CONSTRUCTION_GOLD_PATH,
    GRAPH_CONSTRUCTION_NEGATIVE_PATH,
    PREDICTED_LINK_REJECTION_REASONS,
    _load_fixture_rows,
    _normalize_match_text,
    _normalize_rel_type,
    get_prediction_review_stats,
    list_predicted_link_queue,
    review_predicted_links,
)


DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "graph_training_fixture_review"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review graph-training fixture queue against gold and negative fixtures.")
    parser.add_argument("--model-version", default="")
    parser.add_argument("--review-all-pending", action="store_true")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--reviewed-by", default="codex-fixture-review")
    parser.add_argument("--print-json", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _get_pg_url() -> str:
    pg_url = os.environ.get("XIPHOS_PG_URL")
    if not pg_url:
        raise SystemExit("XIPHOS_PG_URL environment variable not set")
    return pg_url


def _connect(pg_url: str):
    try:
        import psycopg2
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("psycopg2 is required") from exc
    return psycopg2.connect(pg_url)


def _current_model_version(pg_url: str) -> str:
    conn = _connect(pg_url)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT model_version
            FROM kg_embeddings
            ORDER BY trained_at DESC NULLS LAST, model_version DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        return str(row[0] or "").strip() if row else ""
    finally:
        cur.close()
        conn.close()


def _resolve_source_entity_ids(pg_url: str, source_names: set[str]) -> list[str]:
    normalized = sorted({_normalize_match_text(name) for name in source_names if _normalize_match_text(name)})
    if not normalized:
        return []
    conn = _connect(pg_url)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id
            FROM kg_entities
            WHERE LOWER(TRIM(COALESCE(canonical_name, ''))) = ANY(%s)
            ORDER BY canonical_name ASC
            """,
            (normalized,),
        )
        return [str(row[0]) for row in cur.fetchall() if row and row[0]]
    finally:
        cur.close()
        conn.close()


def _build_fixture_maps() -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]]]:
    gold_rows = _load_fixture_rows(GRAPH_CONSTRUCTION_GOLD_PATH)
    negative_rows = _load_fixture_rows(GRAPH_CONSTRUCTION_NEGATIVE_PATH)
    gold_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    negative_map: dict[tuple[str, str, str], dict[str, Any]] = {}

    for row in gold_rows:
        key = (
            _normalize_match_text(row.get("source_entity")),
            _normalize_match_text(row.get("target_entity")),
            _normalize_rel_type(row.get("relationship_type")),
        )
        gold_map[key] = row
    for row in negative_rows:
        key = (
            _normalize_match_text(row.get("source_entity")),
            _normalize_match_text(row.get("attempted_target")),
            _normalize_rel_type(row.get("attempted_relationship_type")),
        )
        negative_map[key] = row
    return gold_map, negative_map


def _derive_unmatched_rejection_reason(
    item: dict[str, Any],
    gold_map: dict[tuple[str, str, str], dict[str, Any]],
) -> str:
    source_name = _normalize_match_text(item.get("source_entity_name"))
    target_name = _normalize_match_text(item.get("target_entity_name"))
    rel_type = _normalize_rel_type(item.get("predicted_relation"))
    gold_targets_for_rel = {
        key[1]
        for key in gold_map
        if key[0] == source_name and key[2] == rel_type
    }
    if gold_targets_for_rel and target_name not in gold_targets_for_rel:
        return "wrong_target_entity"

    gold_relations_for_target = {
        key[2]
        for key in gold_map
        if key[0] == source_name and key[1] == target_name
    }
    if gold_relations_for_target and rel_type not in gold_relations_for_target:
        return "wrong_relationship_family"
    return "insufficient_support"


def _render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Graph Training Fixture Review",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Model version: `{summary['model_version']}`",
        f"- Review-all-pending: `{summary['review_all_pending']}`",
        f"- Reviewed by: `{summary['reviewed_by']}`",
        "",
        "## Outcome",
        "",
        f"- Candidate queue evaluated: `{summary['queue_count']}`",
        f"- Review actions applied: `{summary['review_action_count']}`",
        f"- Confirmed: `{summary['review_result'].get('confirmed_count', 0)}`",
        f"- Rejected: `{summary['review_result'].get('rejected_count', 0)}`",
        "",
        "## Post-Review Stats",
        "",
        f"- Total links: `{summary['post_review_stats'].get('total_links', 0)}`",
        f"- Reviewed links: `{summary['post_review_stats'].get('reviewed_links', 0)}`",
        f"- Pending links: `{summary['post_review_stats'].get('pending_links', 0)}`",
        f"- Confirmation rate: `{summary['post_review_stats'].get('confirmation_rate', 0.0):.2f}`",
        f"- Review coverage: `{summary['post_review_stats'].get('review_coverage_pct', 0.0):.2f}`",
        "",
        "## Sample Actions",
        "",
    ]
    for row in summary.get("sample_actions", []):
        lines.append(
            f"- #{row['id']} {row['source_entity_name']} -> {row['target_entity_name']} `{row['predicted_relation']}` confirmed `{row['confirmed']}` reason `{row.get('rejection_reason')}`"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    pg_url = _get_pg_url()
    model_version = args.model_version.strip() or _current_model_version(pg_url)
    gold_map, negative_map = _build_fixture_maps()
    source_names = {
        key[0]
        for key in [*gold_map.keys(), *negative_map.keys()]
        if key[0]
    }
    source_entity_ids = _resolve_source_entity_ids(pg_url, source_names)
    queue = list_predicted_link_queue(
        pg_url,
        reviewed=False,
        source_entity_ids=source_entity_ids,
        model_version=model_version or None,
        limit=args.limit,
    )

    reviews: list[dict[str, Any]] = []
    sample_actions: list[dict[str, Any]] = []
    for item in queue:
        key = (
            _normalize_match_text(item.get("source_entity_name")),
            _normalize_match_text(item.get("target_entity_name")),
            _normalize_rel_type(item.get("predicted_relation")),
        )
        action: dict[str, Any] | None = None
        if key in gold_map:
            action = {
                "id": int(item["id"]),
                "confirmed": True,
                "notes": "Confirmed against graph construction gold set.",
            }
        elif key in negative_map:
            rejection_reason = str(negative_map[key].get("rejection_reason") or "").strip()
            if rejection_reason not in PREDICTED_LINK_REJECTION_REASONS:
                rejection_reason = "insufficient_support"
            action = {
                "id": int(item["id"]),
                "confirmed": False,
                "rejection_reason": rejection_reason,
                "notes": "Rejected against graph construction hard negative set.",
            }
        elif args.review_all_pending:
            action = {
                "id": int(item["id"]),
                "confirmed": False,
                "rejection_reason": _derive_unmatched_rejection_reason(item, gold_map),
                "notes": "Rejected during fixture cohort review because the relation is not part of the approved fixture gold set.",
            }

        if action is None:
            continue
        reviews.append(action)
        if len(sample_actions) < 12:
            sample_actions.append(
                {
                    "id": int(item["id"]),
                    "source_entity_name": str(item.get("source_entity_name") or ""),
                    "target_entity_name": str(item.get("target_entity_name") or ""),
                    "predicted_relation": str(item.get("predicted_relation") or ""),
                    "confirmed": bool(action.get("confirmed")),
                    "rejection_reason": action.get("rejection_reason"),
                }
            )

    review_result: dict[str, Any] = {"confirmed_count": 0, "rejected_count": 0, "reviewed_items": []}
    if reviews:
        review_result = review_predicted_links(pg_url, reviews, reviewed_by=args.reviewed_by)

    post_review_stats = get_prediction_review_stats(
        pg_url,
        source_entity_ids=source_entity_ids,
        model_version=model_version or None,
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    report_dir = Path(args.report_dir) / stamp
    report_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": model_version,
        "reviewed_by": args.reviewed_by,
        "review_all_pending": bool(args.review_all_pending),
        "queue_count": len(queue),
        "review_action_count": len(reviews),
        "source_entity_ids": source_entity_ids,
        "review_result": review_result,
        "post_review_stats": post_review_stats,
        "sample_actions": sample_actions,
    }

    json_path = report_dir / "summary.json"
    md_path = report_dir / "summary.md"
    json_path.write_text(json.dumps(summary, indent=2, default=_json_default), encoding="utf-8")
    md_path.write_text(_render_markdown(summary), encoding="utf-8")

    if args.json_only:
        print(json.dumps(summary, indent=2, default=_json_default))
    elif args.print_json:
        print(json.dumps(summary, indent=2, default=_json_default))
        print(f"OK: graph training fixture review\nSummary: {json_path}")
    else:
        print(f"OK: graph training fixture review\nSummary: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
