#!/usr/bin/env python3
"""
Run the first live graph-training tranche:

- optionally train graph embeddings
- queue predicted links for top seed entities
- export reviewed labels for training
- emit a dashboard-style report beside readiness and Neo4j health
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from graph_embeddings import (  # noqa: E402
    ensure_prediction_tables,
    export_reviewed_link_labels,
    get_prediction_review_stats,
    list_predicted_link_queue,
    queue_predicted_links,
    train_and_save,
)


DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "graph_training_tranche"
DEFAULT_READINESS_DIR = ROOT / "docs" / "reports" / "readiness"
DEFAULT_BENCHMARK_DIR = ROOT / "docs" / "reports" / "graph_training_benchmark"
DEFAULT_NEO4J_GLOB = "neo4j_graph_drift_audit*"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Helios graph-training tranche A.")
    parser.add_argument("--top-entities", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--skip-queue", action="store_true")
    parser.add_argument("--entity-id", action="append", default=[])
    parser.add_argument("--readiness-dir", default=str(DEFAULT_READINESS_DIR))
    parser.add_argument("--benchmark-dir", default=str(DEFAULT_BENCHMARK_DIR))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def _latest_nested_summary(base_dir: Path) -> Path | None:
    candidates = sorted(base_dir.glob("*/summary.json"))
    return candidates[-1] if candidates else None


def _latest_neo4j_report() -> Path | None:
    base = ROOT / "docs" / "reports"
    candidates = sorted(base.glob(f"{DEFAULT_NEO4J_GLOB}/**/*.json"))
    return candidates[-1] if candidates else None


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


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


def _load_top_seed_entities(pg_url: str, limit: int) -> list[dict[str, Any]]:
    conn = _connect(pg_url)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT
                e.id,
                e.canonical_name,
                e.entity_type,
                COUNT(r.id) AS degree
            FROM kg_entities e
            LEFT JOIN kg_relationships r
              ON e.id = r.source_entity_id OR e.id = r.target_entity_id
            WHERE e.entity_type IN ('company', 'holding_company', 'person')
            GROUP BY e.id, e.canonical_name, e.entity_type
            HAVING COUNT(r.id) > 0
            ORDER BY degree DESC, e.canonical_name ASC
            LIMIT %s
            """,
            (max(1, limit),),
        )
        return [
            {
                "entity_id": str(row[0]),
                "canonical_name": str(row[1] or row[0]),
                "entity_type": str(row[2] or "unknown"),
                "degree": int(row[3] or 0),
            }
            for row in cur.fetchall()
        ]
    finally:
        cur.close()
        conn.close()


def _fetch_embedding_stats(pg_url: str) -> dict[str, Any]:
    ensure_prediction_tables(pg_url)
    conn = _connect(pg_url)
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*), MAX(trained_at), MAX(model_version) FROM kg_embeddings")
        entity_count, trained_at, model_version = cur.fetchone() or (0, None, None)
        cur.execute("SELECT COUNT(*) FROM kg_relation_embeddings")
        relation_count = int((cur.fetchone() or (0,))[0] or 0)
        review_stats = get_prediction_review_stats(pg_url)
        return {
            "entity_count": int(entity_count or 0),
            "relation_count": relation_count,
            "model_version": str(model_version or "unknown"),
            "trained_at": trained_at.isoformat() if trained_at else None,
            "review_stats": review_stats,
        }
    finally:
        cur.close()
        conn.close()


def _build_stage_progress(
    benchmark: dict[str, Any] | None,
    review_stats: dict[str, Any],
    training_result: dict[str, Any] | None,
    queue_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    benchmark_rows = benchmark.get("stage_results") if isinstance((benchmark or {}).get("stage_results"), list) else []
    benchmark_by_id = {
        str(row.get("stage_id")): str(row.get("verdict") or "UNKNOWN")
        for row in benchmark_rows
        if isinstance(row, dict) and row.get("stage_id")
    }
    seeded_candidates = sum(int(row.get("queued_count") or 0) for row in queue_runs)
    total_candidates = sum(int(row.get("count") or 0) for row in queue_runs)
    progress = [
        {
            "stage_id": "construction_training",
            "benchmark_verdict": benchmark_by_id.get("construction_training", "UNKNOWN"),
            "status": "active" if total_candidates > 0 else "seeded",
            "notes": f"{review_stats.get('reviewed_links', 0)} reviewed labels available; {seeded_candidates} new candidates seeded this tranche",
        },
        {
            "stage_id": "missing_edge_recovery",
            "benchmark_verdict": benchmark_by_id.get("missing_edge_recovery", "UNKNOWN"),
            "status": "active" if review_stats.get("reviewed_links", 0) > 0 else "seeded",
            "notes": f"confirmation_rate={review_stats.get('confirmation_rate', 0.0):.2f}; promoted_relationships={review_stats.get('promoted_relationships', 0)}",
        },
        {
            "stage_id": "temporal_recurrence_change",
            "benchmark_verdict": benchmark_by_id.get("temporal_recurrence_change", "UNKNOWN"),
            "status": "not_started",
            "notes": "Needs time-sliced relationship and monitor replay labels.",
        },
        {
            "stage_id": "subgraph_anomaly",
            "benchmark_verdict": benchmark_by_id.get("subgraph_anomaly", "UNKNOWN"),
            "status": "not_started",
            "notes": "Needs shell, diversion, and fourth-party anomaly labels.",
        },
        {
            "stage_id": "uncertainty_fusion",
            "benchmark_verdict": benchmark_by_id.get("uncertainty_fusion", "UNKNOWN"),
            "status": "not_started",
            "notes": "Needs adjudicated confidence labels and soft-rule calibration.",
        },
        {
            "stage_id": "graphrag_explanation",
            "benchmark_verdict": benchmark_by_id.get("graphrag_explanation", "UNKNOWN"),
            "status": "not_started",
            "notes": "Needs explanation faithfulness eval set.",
        },
    ]
    if training_result:
        progress[0]["training_loss"] = float(training_result.get("final_loss") or 0.0)
        progress[0]["embeddings_saved"] = int(training_result.get("embeddings_saved") or 0)
    return progress


def _render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Helios Graph Training Tranche",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Prime-time readiness: `{summary['readiness'].get('overall_verdict', 'UNKNOWN')}`",
        f"- Neo4j drift audit: `{summary['neo4j'].get('overall_verdict', 'UNKNOWN')}`",
        f"- Graph benchmark: `{summary['benchmark'].get('overall_verdict', 'UNKNOWN')}`",
        "",
        "## Embeddings",
        "",
        f"- Entities: `{summary['embedding_stats'].get('entity_count', 0)}`",
        f"- Relations: `{summary['embedding_stats'].get('relation_count', 0)}`",
        f"- Model version: `{summary['embedding_stats'].get('model_version')}`",
        f"- Trained at: `{summary['embedding_stats'].get('trained_at')}`",
        "",
        "## Analyst Review Loop",
        "",
        f"- Total predicted links: `{summary['review_stats'].get('total_links', 0)}`",
        f"- Reviewed links: `{summary['review_stats'].get('reviewed_links', 0)}`",
        f"- Confirmed links: `{summary['review_stats'].get('confirmed_links', 0)}`",
        f"- Rejected links: `{summary['review_stats'].get('rejected_links', 0)}`",
        f"- Confirmation rate: `{summary['review_stats'].get('confirmation_rate', 0.0):.2f}`",
        f"- Review coverage: `{summary['review_stats'].get('review_coverage_pct', 0.0):.2f}`",
        f"- Reviewed label export: `{summary['review_export'].get('output_path')}`",
        "",
        "## Seed Queue Runs",
        "",
    ]
    for run in summary.get("queue_runs", []):
        lines.extend(
            [
                f"- {run.get('entity_name')} `{run.get('entity_id')}`",
                f"  queued `{run.get('queued_count', 0)}` new, reused `{run.get('existing_count', 0)}`, total surfaced `{run.get('count', 0)}`",
            ]
        )
    lines.extend(["", "## Stage Progress", ""])
    for stage in summary.get("stage_progress", []):
        lines.append(
            f"- {stage['stage_id']}: status `{stage['status']}`, benchmark `{stage['benchmark_verdict']}`. {stage['notes']}"
        )
    lines.extend(["", "## Sample Review Queue", ""])
    for row in summary.get("sample_review_queue", []):
        lines.append(
            f"- #{row['id']} {row['source_entity_name']} -> {row['target_entity_name']} `{row['predicted_relation']}` family `{row['predicted_edge_family']}` score `{row['score']:.4f}` reviewed `{row['reviewed']}`"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    pg_url = _get_pg_url()

    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    report_dir = Path(args.report_dir) / stamp
    report_dir.mkdir(parents=True, exist_ok=True)

    readiness_path = _latest_nested_summary(Path(args.readiness_dir))
    benchmark_path = _latest_nested_summary(Path(args.benchmark_dir))
    neo4j_path = _latest_neo4j_report()

    training_result: dict[str, Any] | None = None
    if not args.skip_train:
        training_result = train_and_save(pg_url, dim=64)

    entity_ids = [str(item).strip() for item in args.entity_id if str(item).strip()]
    if not entity_ids:
        entity_ids = [row["entity_id"] for row in _load_top_seed_entities(pg_url, args.top_entities)]

    queue_runs: list[dict[str, Any]] = []
    if not args.skip_queue:
        for entity_id in entity_ids:
            queue_runs.append(queue_predicted_links(pg_url, entity_id, top_k=args.top_k))

    review_export = export_reviewed_link_labels(pg_url, report_dir / "reviewed_link_labels.json")
    review_stats = get_prediction_review_stats(pg_url)
    embedding_stats = _fetch_embedding_stats(pg_url)
    sample_review_queue = list_predicted_link_queue(pg_url, reviewed=False, limit=12)

    benchmark = _read_json(benchmark_path) or {}
    readiness = _read_json(readiness_path) or {}
    neo4j = _read_json(neo4j_path) or {}
    stage_progress = _build_stage_progress(benchmark, review_stats, training_result, queue_runs)

    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "readiness_summary": str(readiness_path) if readiness_path else None,
        "neo4j_summary": str(neo4j_path) if neo4j_path else None,
        "benchmark_summary": str(benchmark_path) if benchmark_path else None,
        "training_result": training_result,
        "embedding_stats": embedding_stats,
        "review_stats": review_stats,
        "review_export": review_export,
        "queue_runs": queue_runs,
        "sample_review_queue": sample_review_queue,
        "stage_progress": stage_progress,
        "readiness": {
            "overall_verdict": readiness.get("overall_verdict"),
            "path": str(readiness_path) if readiness_path else None,
        },
        "neo4j": {
            "overall_verdict": neo4j.get("overall_verdict"),
            "path": str(neo4j_path) if neo4j_path else None,
        },
        "benchmark": {
            "overall_verdict": benchmark.get("overall_verdict"),
            "path": str(benchmark_path) if benchmark_path else None,
            "data_foundation_verdict": (benchmark.get("data_foundation") or {}).get("verdict")
            if isinstance(benchmark.get("data_foundation"), dict)
            else None,
        },
    }

    json_path = report_dir / "summary.json"
    md_path = report_dir / "summary.md"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(summary), encoding="utf-8")

    if args.print_json:
        print(json.dumps(summary, indent=2))

    print(f"OK: graph training tranche\nSummary: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
