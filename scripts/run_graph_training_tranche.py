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
    ensure_prediction_tables,
    export_reviewed_link_labels,
    get_graph_construction_training_metrics,
    get_missing_edge_recovery_metrics,
    get_novel_edge_discovery_metrics,
    get_prediction_review_stats,
    list_predicted_link_queue,
    queue_predicted_links,
    train_and_save,
)
from graph_ingest import ingest_graph_training_fixture_gold_set  # noqa: E402


DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "graph_training_tranche"
DEFAULT_READINESS_DIR = ROOT / "docs" / "reports" / "readiness"
DEFAULT_BENCHMARK_DIR = ROOT / "docs" / "reports" / "graph_training_benchmark"
DEFAULT_NEO4J_GLOB = "neo4j_graph_drift_audit*"


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Helios graph-training tranche A.")
    parser.add_argument("--top-entities", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--skip-queue", action="store_true")
    parser.add_argument("--skip-fixture-seed", action="store_true")
    parser.add_argument("--entity-id", action="append", default=[])
    parser.add_argument("--readiness-dir", default=str(DEFAULT_READINESS_DIR))
    parser.add_argument("--benchmark-dir", default=str(DEFAULT_BENCHMARK_DIR))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--print-json", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args()


def _latest_nested_summary(base_dir: Path) -> Path | None:
    candidates = sorted(base_dir.glob("*/summary.json"))
    return candidates[-1] if candidates else None


def _latest_neo4j_report() -> Path | None:
    base = ROOT / "docs" / "reports"
    candidates = sorted(base.glob(f"{DEFAULT_NEO4J_GLOB}/neo4j-graph-drift-audit-*.json"))
    if candidates:
        return candidates[-1]
    candidates = sorted(base.glob(f"{DEFAULT_NEO4J_GLOB}/**/*.json"))
    return candidates[-1] if candidates else None


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _summary_verdict(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("overall_verdict", "prime_time_verdict", "verdict"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


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
    if limit <= 0:
        return []
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
            (limit,),
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


def _load_fixture_seed_entities(pg_url: str) -> list[dict[str, Any]]:
    source_names: set[str] = set()
    for path, source_field in (
        (GRAPH_CONSTRUCTION_GOLD_PATH, "source_entity"),
        (GRAPH_CONSTRUCTION_NEGATIVE_PATH, "source_entity"),
    ):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            continue
        for row in payload:
            if not isinstance(row, dict):
                continue
            source_name = str(row.get(source_field) or "").strip()
            if source_name:
                source_names.add(source_name.lower())

    if not source_names:
        return []

    conn = _connect(pg_url)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, canonical_name, entity_type, 0 AS degree
            FROM kg_entities
            WHERE LOWER(canonical_name) = ANY(%s)
            ORDER BY canonical_name ASC
            """,
            (sorted(source_names),),
        )
        rows = [
            {
                "entity_id": str(row[0]),
                "canonical_name": str(row[1] or row[0]),
                "entity_type": str(row[2] or "unknown"),
                "degree": int(row[3] or 0),
            }
            for row in cur.fetchall()
        ]
        resolved_names = {str(row["canonical_name"]).strip().lower() for row in rows}
        unresolved = [name for name in sorted(source_names) if name not in resolved_names]
        if not unresolved:
            return rows

        from entity_resolution import normalize_name
        from ofac import jaro_winkler

        cur.execute("SELECT id, canonical_name, entity_type FROM kg_entities WHERE canonical_name IS NOT NULL")
        candidates = [
            (
                str(row[0]),
                str(row[1]),
                str(row[2] or "unknown"),
                normalize_name(str(row[1])),
            )
            for row in cur.fetchall()
            if row[0] and row[1]
        ]
        seen_ids = {str(row["entity_id"]) for row in rows}
        for unresolved_name in unresolved:
            normalized_unresolved = normalize_name(unresolved_name)
            best: tuple[str, str, str, float] | None = None
            for entity_id, canonical_name, entity_type, normalized_candidate in candidates:
                if not normalized_candidate:
                    continue
                score = jaro_winkler(normalized_unresolved, normalized_candidate)
                if normalized_unresolved and normalized_candidate:
                    if normalized_unresolved in normalized_candidate or normalized_candidate in normalized_unresolved:
                        score = max(score, 0.96)
                if best is None or score > best[3]:
                    best = (entity_id, canonical_name, entity_type, score)
            if best and best[3] >= 0.9 and best[0] not in seen_ids:
                rows.append(
                    {
                        "entity_id": best[0],
                        "canonical_name": best[1],
                        "entity_type": best[2],
                        "degree": 0,
                    }
                )
                seen_ids.add(best[0])
        return rows
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
    stage_metrics: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    benchmark_rows = benchmark.get("stage_results") if isinstance((benchmark or {}).get("stage_results"), list) else []
    benchmark_by_id = {
        str(row.get("stage_id")): str(row.get("verdict") or "UNKNOWN")
        for row in benchmark_rows
        if isinstance(row, dict) and row.get("stage_id")
    }
    seeded_candidates = sum(int(row.get("queued_count") or 0) for row in queue_runs)
    total_candidates = sum(int(row.get("count") or 0) for row in queue_runs)
    construction_metrics = stage_metrics.get("construction_training") if isinstance(stage_metrics.get("construction_training"), dict) else {}
    recovery_metrics = stage_metrics.get("missing_edge_recovery") if isinstance(stage_metrics.get("missing_edge_recovery"), dict) else {}
    novelty_metrics = stage_metrics.get("novel_edge_discovery") if isinstance(stage_metrics.get("novel_edge_discovery"), dict) else {}
    progress = [
        {
            "stage_id": "construction_training",
            "benchmark_verdict": benchmark_by_id.get("construction_training", "UNKNOWN"),
            "status": "active" if total_candidates > 0 else "seeded",
            "notes": (
                f"{review_stats.get('reviewed_links', 0)} reviewed labels available; "
                f"{seeded_candidates} new candidates seeded this tranche; "
                f"edge_family_micro_f1={construction_metrics.get('edge_family_micro_f1', 0.0):.2f}"
            ),
        },
        {
            "stage_id": "missing_edge_recovery",
            "benchmark_verdict": benchmark_by_id.get("missing_edge_recovery", "UNKNOWN"),
            "status": "active" if review_stats.get("reviewed_links", 0) > 0 else "seeded",
            "notes": (
                f"protocol={recovery_metrics.get('evaluation_protocol', 'unknown')}; "
                f"masked_hits@10={recovery_metrics.get('masked_holdout_hits_at_10', 0.0):.2f}; "
                f"holdout_queries={recovery_metrics.get('masked_holdout_queries_evaluated', 0)}; "
                f"mean_rank={recovery_metrics.get('mean_withheld_target_rank', 0.0):.2f}; "
                f"unsupported_promoted_edge_rate={review_stats.get('unsupported_promoted_edge_rate', 0.0):.2f}"
            ),
        },
        {
            "stage_id": "novel_edge_discovery",
            "benchmark_verdict": "INFO",
            "status": "active" if review_stats.get("reviewed_links", 0) > 0 else "seeded",
            "notes": (
                f"confirmation_rate={novelty_metrics.get('analyst_confirmation_rate', 0.0):.2f}; "
                f"promoted_relationships={novelty_metrics.get('promoted_relationships', 0)}; "
                f"pending_links={novelty_metrics.get('pending_links', 0)}; "
                f"novel_edge_yield={novelty_metrics.get('novel_edge_yield', 0.0):.2f}"
            ),
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


def _build_stage_metrics(
    pg_url: str,
    review_stats: dict[str, Any],
    queue_runs: list[dict[str, Any]],
    training_result: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    recovery = review_stats.get("missing_edge_recovery") if isinstance(review_stats.get("missing_edge_recovery"), dict) else {}
    seeded_candidates = sum(int(row.get("queued_count") or 0) for row in queue_runs)
    total_candidates = sum(int(row.get("count") or 0) for row in queue_runs)
    construction_metrics = get_graph_construction_training_metrics(pg_url)
    construction_metrics.update(
        {
            "reviewed_labels": int(review_stats.get("reviewed_links") or 0),
            "rejected_labels": int(review_stats.get("rejected_links") or 0),
            "confirmed_labels": int(review_stats.get("confirmed_links") or 0),
            "prediction_pool_size": int(review_stats.get("total_links") or 0),
            "seeded_candidates_this_run": seeded_candidates,
            "surfaced_candidates_this_run": total_candidates,
        }
    )
    if training_result:
        construction_metrics["final_loss"] = float(training_result.get("final_loss") or 0.0)
        construction_metrics["embeddings_saved"] = int(training_result.get("embeddings_saved") or 0)
    missing_edge_metrics = get_missing_edge_recovery_metrics(pg_url, review_stats=review_stats)
    novel_edge_metrics = get_novel_edge_discovery_metrics(review_stats)
    return {
        "construction_training": construction_metrics,
        "missing_edge_recovery": {**missing_edge_metrics},
        "novel_edge_discovery": {
            **novel_edge_metrics,
            "pending_links": int(review_stats.get("pending_links") or 0),
            "existing_pending_links": int(review_stats.get("existing_pending_links") or 0),
            "mean_review_latency_hours": float(recovery.get("mean_review_latency_hours") or 0.0),
            "median_pending_age_hours": float(recovery.get("median_pending_age_hours") or 0.0),
            "p95_pending_age_hours": float(recovery.get("p95_pending_age_hours") or 0.0),
            "stale_pending_24h": int(recovery.get("stale_pending_24h") or 0),
            "stale_pending_7d": int(recovery.get("stale_pending_7d") or 0),
        },
    }


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
        f"- Fixture seed rows: `{summary.get('fixture_seed', {}).get('rows_seeded', 0)}`",
        f"- Fixture seed sources: `{summary.get('fixture_seed', {}).get('sources_seeded', 0)}`",
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
        f"- Pending links: `{summary['review_stats'].get('pending_links', 0)}`",
        f"- Confirmation rate: `{summary['review_stats'].get('confirmation_rate', 0.0):.2f}`",
        f"- Review coverage: `{summary['review_stats'].get('review_coverage_pct', 0.0):.2f}`",
        f"- Unsupported promoted edge rate: `{summary['review_stats'].get('unsupported_promoted_edge_rate', 0.0):.2f}`",
        f"- Reviewed label export: `{summary['review_export'].get('output_path')}`",
        "",
        "## Missing Edge Recovery",
        "",
        f"- Evaluation protocol: `{summary['stage_metrics']['missing_edge_recovery'].get('evaluation_protocol', 'unknown')}`",
        f"- Masked holdout hits@10: `{summary['stage_metrics']['missing_edge_recovery'].get('masked_holdout_hits_at_10', 0.0):.2f}`",
        f"- Masked holdout MRR: `{summary['stage_metrics']['missing_edge_recovery'].get('masked_holdout_mrr', 0.0):.2f}`",
        f"- Mean withheld target rank: `{summary['stage_metrics']['missing_edge_recovery'].get('mean_withheld_target_rank', 0.0):.2f}`",
        f"- Holdout queries evaluated: `{summary['stage_metrics']['missing_edge_recovery'].get('masked_holdout_queries_evaluated', 0)}`",
        f"- Affected source entities: `{summary['stage_metrics']['missing_edge_recovery'].get('holdout_source_entity_count', 0)}`",
        f"- Recovery queue candidates: `{summary['stage_metrics']['missing_edge_recovery'].get('recovery_queue_candidate_count', 0)}`",
        "",
        "## Novel Edge Discovery",
        "",
        f"- Novel edge yield: `{summary['stage_metrics']['novel_edge_discovery'].get('novel_edge_yield', 0.0):.2f}`",
        f"- Mean review latency (hours): `{summary['stage_metrics']['novel_edge_discovery'].get('mean_review_latency_hours', 0.0):.2f}`",
        f"- Median pending age (hours): `{summary['stage_metrics']['novel_edge_discovery'].get('median_pending_age_hours', 0.0):.2f}`",
        f"- P95 pending age (hours): `{summary['stage_metrics']['novel_edge_discovery'].get('p95_pending_age_hours', 0.0):.2f}`",
        f"- Stale pending >24h: `{summary['stage_metrics']['novel_edge_discovery'].get('stale_pending_24h', 0)}`",
        f"- Stale pending >7d: `{summary['stage_metrics']['novel_edge_discovery'].get('stale_pending_7d', 0)}`",
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

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    report_dir = Path(args.report_dir) / stamp
    report_dir.mkdir(parents=True, exist_ok=True)

    readiness_path = _latest_nested_summary(Path(args.readiness_dir))
    benchmark_path = _latest_nested_summary(Path(args.benchmark_dir))
    neo4j_path = _latest_neo4j_report()

    fixture_seed: dict[str, Any] | None = None
    if not args.skip_fixture_seed:
        fixture_seed = ingest_graph_training_fixture_gold_set()

    training_result: dict[str, Any] | None = None
    if not args.skip_train:
        training_result = train_and_save(pg_url, dim=64)

    entity_ids = [str(item).strip() for item in args.entity_id if str(item).strip()]
    if not entity_ids:
        combined_seed_entities = _load_fixture_seed_entities(pg_url) + _load_top_seed_entities(pg_url, args.top_entities)
        deduped_entity_ids: list[str] = []
        seen: set[str] = set()
        for row in combined_seed_entities:
            entity_id = str(row.get("entity_id") or "").strip()
            if not entity_id or entity_id in seen:
                continue
            deduped_entity_ids.append(entity_id)
            seen.add(entity_id)
        entity_ids = deduped_entity_ids

    queue_runs: list[dict[str, Any]] = []
    if not args.skip_queue:
        for entity_id in entity_ids:
            queue_runs.append(queue_predicted_links(pg_url, entity_id, top_k=args.top_k))

    review_scope_entity_ids = entity_ids or None
    embedding_stats = _fetch_embedding_stats(pg_url)
    current_model_version = str(embedding_stats.get("model_version") or "").strip() or None
    review_export = export_reviewed_link_labels(pg_url, report_dir / "reviewed_link_labels.json")
    review_stats = get_prediction_review_stats(
        pg_url,
        source_entity_ids=review_scope_entity_ids,
        model_version=current_model_version,
    )
    embedding_stats["review_stats"] = review_stats
    sample_review_queue = list_predicted_link_queue(
        pg_url,
        reviewed=False,
        source_entity_ids=review_scope_entity_ids,
        model_version=current_model_version,
        limit=12,
    )

    benchmark = _read_json(benchmark_path) or {}
    readiness = _read_json(readiness_path) or {}
    neo4j = _read_json(neo4j_path) or {}
    stage_metrics = _build_stage_metrics(pg_url, review_stats, queue_runs, training_result)
    stage_progress = _build_stage_progress(benchmark, review_stats, training_result, queue_runs, stage_metrics)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_dir": str(report_dir),
        "readiness_summary": str(readiness_path) if readiness_path else None,
        "neo4j_summary": str(neo4j_path) if neo4j_path else None,
        "benchmark_summary": str(benchmark_path) if benchmark_path else None,
        "fixture_seed": fixture_seed,
        "training_result": training_result,
        "embedding_stats": embedding_stats,
        "review_stats": review_stats,
        "review_export": review_export,
        "queue_runs": queue_runs,
        "review_scope_entity_ids": review_scope_entity_ids or [],
        "review_scope_model_version": current_model_version,
        "sample_review_queue": sample_review_queue,
        "stage_progress": stage_progress,
        "stage_metrics": stage_metrics,
        "readiness": {
            "overall_verdict": _summary_verdict(readiness),
            "path": str(readiness_path) if readiness_path else None,
        },
        "neo4j": {
            "overall_verdict": _summary_verdict(neo4j),
            "path": str(neo4j_path) if neo4j_path else None,
        },
        "benchmark": {
            "overall_verdict": _summary_verdict(benchmark),
            "path": str(benchmark_path) if benchmark_path else None,
            "data_foundation_verdict": (benchmark.get("data_foundation") or {}).get("verdict")
            if isinstance(benchmark.get("data_foundation"), dict)
            else None,
        },
    }

    json_path = report_dir / "summary.json"
    md_path = report_dir / "summary.md"
    summary["report_json_path"] = str(json_path)
    summary["report_markdown_path"] = str(md_path)
    json_path.write_text(json.dumps(summary, indent=2, default=_json_default), encoding="utf-8")
    md_path.write_text(_render_markdown(summary), encoding="utf-8")

    if args.json_only:
        print(json.dumps(summary, indent=2, default=_json_default))
    elif args.print_json:
        print(json.dumps(summary, indent=2, default=_json_default))
        print(f"OK: graph training tranche\nSummary: {json_path}")
    else:
        print(f"OK: graph training tranche\nSummary: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
