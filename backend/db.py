"""
Persistence layer for Xiphos v2.0.

Supports both SQLite (default) and PostgreSQL backends.
Set HELIOS_DB_ENGINE=postgres and XIPHOS_PG_URL to use PostgreSQL.

Stores vendors, scoring results, alerts, and screening history.
Survives server restarts. Auto-creates schema on first run.
"""

import sqlite3
import json
import os
import re
import shutil
import logging
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from helios_core.room_contract import (
    DEFAULT_MISSION_BRIEF_ROOM,
    canonicalize_mission_brief_room,
    mission_brief_room_sql,
)
from runtime_paths import get_main_db_path, get_secure_artifacts_dir
from event_extraction import compute_report_hash


def _safe_json_loads(value):
    """Parse JSON string, or return value as-is if already a dict/list (PostgreSQL JSONB)."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)

logger = logging.getLogger(__name__)

_LEGAL_SUFFIX_TOKENS = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "llc",
    "ltd",
    "limited",
    "lp",
    "llp",
    "plc",
    "gmbh",
    "ag",
    "sa",
    "srl",
    "bv",
    "nv",
}


def _normalize_vendor_name_for_match(name: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", str(name or "").lower())
    while tokens and tokens[-1] in _LEGAL_SUFFIX_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def _row_to_enrichment_report(row) -> dict | None:
    if not row:
        return None
    result = _safe_json_loads(row["full_report"])
    result["enriched_at"] = result.get("enriched_at") or row["enriched_at"]
    result["report_hash"] = row["report_hash"] or result.get("report_hash") or compute_report_hash(result)
    return result


def _row_to_mission_brief(row) -> dict | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "room": canonicalize_mission_brief_room(row["room"]),
        "case_id": row["case_id"],
        "object_type": row["object_type"],
        "engagement_type": row["engagement_type"],
        "collection_depth": row["collection_depth"],
        "timeline": row["timeline"],
        "status": row["status"],
        "question_count": row["question_count"],
        "confidence_score": row["confidence_score"],
        "primary_targets": _safe_json_loads(row["primary_targets"]) or {},
        "known_context": _safe_json_loads(row["known_context"]) or {},
        "priority_requirements": _safe_json_loads(row["priority_requirements"]) or [],
        "authorized_tiers": _safe_json_loads(row["authorized_tiers"]) or [],
        "summary": row["summary"],
        "notes": _safe_json_loads(row["notes"]) or [],
        "created_by": row["created_by"],
        "created_by_email": row["created_by_email"],
        "created_by_role": row["created_by_role"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_assistant_run(row) -> dict | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "workflow_lane": row["workflow_lane"],
        "objective": row["objective"],
        "playbook_id": row["playbook_id"],
        "status": row["status"],
        "analyst_prompt": row["analyst_prompt"],
        "plan_payload": _safe_json_loads(row["plan_payload"]) or {},
        "execution_payload": _safe_json_loads(row["execution_payload"]) or {},
        "last_error": row["last_error"] or "",
        "created_by": row["created_by"] or "",
        "created_by_email": row["created_by_email"] or "",
        "created_by_role": row["created_by_role"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

# ---------------------------------------------------------------------------
# Engine selection: set HELIOS_DB_ENGINE=postgres to use PostgreSQL
# ---------------------------------------------------------------------------
_DB_ENGINE = os.environ.get("HELIOS_DB_ENGINE", "sqlite").lower().strip()
_use_postgres = _DB_ENGINE in ("postgres", "postgresql", "pg")

if _use_postgres:
    try:
        from db_postgres import get_conn as _pg_get_conn, init_db as _pg_init_db
        logger.info("PostgreSQL backend selected (HELIOS_DB_ENGINE=%s)", _DB_ENGINE)
    except ImportError as e:
        logger.error("PostgreSQL backend requested but db_postgres.py failed to import: %s", e)
        logger.warning("Falling back to SQLite backend")
        _use_postgres = False


def get_db_path() -> str:
    return get_main_db_path()


@contextmanager
def _sqlite_get_conn():
    """SQLite context manager for database connections with WAL mode."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_conn():
    """Context manager for database connections. Routes to PostgreSQL or SQLite."""
    if _use_postgres:
        return _pg_get_conn()
    return _sqlite_get_conn()


def init_db():
    """Create tables if they don't exist. Includes migration for existing databases."""
    if _use_postgres:
        _pg_init_db()
        return
    with _sqlite_get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS vendors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                country TEXT NOT NULL,
                program TEXT NOT NULL DEFAULT 'standard_industrial',
                profile TEXT NOT NULL DEFAULT 'defense_acquisition',
                vendor_input JSON NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS scoring_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id TEXT NOT NULL REFERENCES vendors(id),
                calibrated_probability REAL NOT NULL,
                calibrated_tier TEXT NOT NULL,
                composite_score INTEGER NOT NULL,
                is_hard_stop BOOLEAN NOT NULL DEFAULT 0,
                interval_lower REAL,
                interval_upper REAL,
                interval_coverage REAL,
                full_result JSON NOT NULL,
                scored_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id TEXT NOT NULL REFERENCES vendors(id),
                entity_name TEXT NOT NULL,
                severity TEXT NOT NULL CHECK(severity IN ('critical', 'high', 'medium', 'low')),
                title TEXT NOT NULL,
                description TEXT,
                resolved BOOLEAN NOT NULL DEFAULT 0,
                resolved_by TEXT,
                resolved_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS screening_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_name TEXT NOT NULL,
                matched BOOLEAN NOT NULL,
                best_score REAL,
                matched_name TEXT,
                matched_list TEXT,
                result_json JSON,
                screened_at TEXT NOT NULL DEFAULT (datetime('now')),
                screened_by TEXT DEFAULT 'system'
            );

            CREATE INDEX IF NOT EXISTS idx_scoring_vendor ON scoring_results(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_scoring_tier ON scoring_results(calibrated_tier);
            CREATE INDEX IF NOT EXISTS idx_alerts_vendor ON alerts(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
            CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON alerts(resolved);
            CREATE INDEX IF NOT EXISTS idx_screening_date ON screening_log(screened_at);

            CREATE TABLE IF NOT EXISTS enrichment_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id TEXT NOT NULL REFERENCES vendors(id),
                overall_risk TEXT NOT NULL,
                findings_total INTEGER NOT NULL DEFAULT 0,
                critical_count INTEGER NOT NULL DEFAULT 0,
                high_count INTEGER NOT NULL DEFAULT 0,
                identifiers JSON,
                connectors_run INTEGER NOT NULL DEFAULT 0,
                total_elapsed_ms INTEGER NOT NULL DEFAULT 0,
                report_hash TEXT,
                full_report JSON NOT NULL,
                enriched_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_enrichment_vendor ON enrichment_reports(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_enrichment_risk ON enrichment_reports(overall_risk);

            CREATE TABLE IF NOT EXISTS monitoring_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id TEXT NOT NULL REFERENCES vendors(id),
                run_id TEXT,
                previous_risk TEXT,
                current_risk TEXT,
                risk_changed BOOLEAN NOT NULL DEFAULT 0,
                change_type TEXT NOT NULL DEFAULT 'no_change',
                status TEXT NOT NULL DEFAULT 'completed',
                score_before REAL,
                score_after REAL,
                new_findings_count INTEGER DEFAULT 0,
                resolved_findings_count INTEGER DEFAULT 0,
                delta_summary TEXT,
                sources_triggered JSON,
                started_at TEXT,
                completed_at TEXT,
                checked_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_monitoring_vendor ON monitoring_log(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_monitoring_checked ON monitoring_log(checked_at);
            CREATE INDEX IF NOT EXISTS idx_monitoring_risk_changed ON monitoring_log(risk_changed);

            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id TEXT NOT NULL REFERENCES vendors(id),
                decision TEXT NOT NULL CHECK(decision IN ('approve', 'reject', 'escalate')),
                decided_by TEXT,
                decided_by_email TEXT,
                reason TEXT,
                posterior_at_decision REAL,
                tier_at_decision TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_decisions_vendor ON decisions(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);

            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY,
                uploaded_by TEXT NOT NULL,
                uploaded_by_email TEXT,
                filename TEXT NOT NULL,
                total_vendors INTEGER NOT NULL,
                processed INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS batch_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL REFERENCES batches(id),
                vendor_name TEXT NOT NULL,
                country TEXT NOT NULL,
                case_id TEXT,
                tier TEXT,
                posterior REAL,
                findings_count INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_batch_uploaded_by ON batches(uploaded_by);
            CREATE INDEX IF NOT EXISTS idx_batch_status ON batches(status);
            CREATE INDEX IF NOT EXISTS idx_batch_items_batch ON batch_items(batch_id);
            CREATE INDEX IF NOT EXISTS idx_batch_items_status ON batch_items(status);

            CREATE TABLE IF NOT EXISTS monitor_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sweep_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                total_vendors INTEGER NOT NULL DEFAULT 0,
                processed INTEGER NOT NULL DEFAULT 0,
                risk_changes INTEGER NOT NULL DEFAULT 0,
                new_alerts INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS monitor_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_monitor_schedules_status ON monitor_schedules(status);
            CREATE INDEX IF NOT EXISTS idx_monitor_schedules_created ON monitor_schedules(created_at);

            CREATE TABLE IF NOT EXISTS intel_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL REFERENCES vendors(id),
                created_by TEXT,
                report_hash TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                elapsed_ms INTEGER DEFAULT 0,
                summary JSON NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_intel_summaries_case_user_hash ON intel_summaries(case_id, created_by, report_hash);

            CREATE TABLE IF NOT EXISTS intel_summary_jobs (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES vendors(id),
                created_by TEXT,
                report_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                summary_id INTEGER,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                started_at TEXT,
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_intel_jobs_case_user_hash ON intel_summary_jobs(case_id, created_by, report_hash);

            CREATE TABLE IF NOT EXISTS case_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL REFERENCES vendors(id),
                report_hash TEXT NOT NULL,
                finding_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                date_range JSON,
                jurisdiction TEXT,
                status TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.0,
                source_refs JSON,
                source_finding_ids JSON,
                connector TEXT,
                normalization_method TEXT NOT NULL DEFAULT 'deterministic',
                severity TEXT,
                title TEXT,
                assessment TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_case_events_case_hash ON case_events(case_id, report_hash);
            CREATE INDEX IF NOT EXISTS idx_case_events_event_type ON case_events(event_type);

            CREATE TABLE IF NOT EXISTS artifact_records (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES vendors(id),
                artifact_type TEXT NOT NULL,
                source_system TEXT NOT NULL DEFAULT '',
                source_class TEXT NOT NULL DEFAULT '',
                authority_level TEXT NOT NULL DEFAULT '',
                access_model TEXT NOT NULL DEFAULT '',
                uploaded_by TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL,
                content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                storage_ref TEXT NOT NULL UNIQUE,
                retention_class TEXT NOT NULL DEFAULT 'standard',
                sensitivity TEXT NOT NULL DEFAULT 'controlled',
                effective_date TEXT,
                parse_status TEXT NOT NULL DEFAULT 'pending',
                structured_fields JSON,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_artifact_records_case ON artifact_records(case_id);
            CREATE INDEX IF NOT EXISTS idx_artifact_records_type ON artifact_records(artifact_type);
            CREATE INDEX IF NOT EXISTS idx_artifact_records_created ON artifact_records(created_at);

            CREATE TABLE IF NOT EXISTS beta_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                user_email TEXT,
                user_role TEXT,
                case_id TEXT REFERENCES vendors(id),
                workflow_lane TEXT NOT NULL DEFAULT '',
                screen TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'general',
                severity TEXT NOT NULL DEFAULT 'medium',
                summary TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                metadata JSON,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_beta_feedback_created ON beta_feedback(created_at);
            CREATE INDEX IF NOT EXISTS idx_beta_feedback_status ON beta_feedback(status);
            CREATE INDEX IF NOT EXISTS idx_beta_feedback_lane ON beta_feedback(workflow_lane);

            CREATE TABLE IF NOT EXISTS beta_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                user_email TEXT,
                user_role TEXT,
                case_id TEXT REFERENCES vendors(id),
                workflow_lane TEXT NOT NULL DEFAULT '',
                screen TEXT NOT NULL DEFAULT '',
                event_name TEXT NOT NULL,
                metadata JSON,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_beta_events_created ON beta_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_beta_events_lane ON beta_events(workflow_lane);
            CREATE INDEX IF NOT EXISTS idx_beta_events_name ON beta_events(event_name);

            CREATE TABLE IF NOT EXISTS graph_workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                pinned_nodes TEXT DEFAULT '[]',
                annotations TEXT DEFAULT '{}',
                filter_state TEXT DEFAULT '{}',
                layout_mode TEXT DEFAULT 'cose',
                viewport TEXT DEFAULT '{}',
                node_positions TEXT DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_graph_workspaces_created_by ON graph_workspaces(created_by);
            CREATE INDEX IF NOT EXISTS idx_graph_workspaces_created_at ON graph_workspaces(created_at);

            CREATE TABLE IF NOT EXISTS mission_threads (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                lane TEXT NOT NULL DEFAULT '',
                program TEXT NOT NULL DEFAULT '',
                theater TEXT NOT NULL DEFAULT '',
                mission_type TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS mission_thread_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_thread_id TEXT NOT NULL REFERENCES mission_threads(id) ON DELETE CASCADE,
                vendor_id TEXT REFERENCES vendors(id) ON DELETE CASCADE,
                entity_id TEXT,
                role TEXT NOT NULL DEFAULT '',
                criticality TEXT NOT NULL DEFAULT 'supporting',
                subsystem TEXT NOT NULL DEFAULT '',
                site TEXT NOT NULL DEFAULT '',
                is_alternate BOOLEAN NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS mission_thread_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_thread_id TEXT NOT NULL REFERENCES mission_threads(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS mission_thread_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_thread_id TEXT NOT NULL REFERENCES mission_threads(id) ON DELETE CASCADE,
                note_type TEXT NOT NULL DEFAULT 'general',
                body TEXT NOT NULL,
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_mission_threads_created_by ON mission_threads(created_by);
            CREATE INDEX IF NOT EXISTS idx_mission_threads_updated_at ON mission_threads(updated_at);
            CREATE INDEX IF NOT EXISTS idx_mission_thread_members_thread ON mission_thread_members(mission_thread_id);
            CREATE INDEX IF NOT EXISTS idx_mission_thread_members_vendor ON mission_thread_members(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_mission_thread_members_entity ON mission_thread_members(entity_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mission_thread_roles_unique
                ON mission_thread_roles(mission_thread_id, role);
            CREATE INDEX IF NOT EXISTS idx_mission_thread_notes_thread ON mission_thread_notes(mission_thread_id);

            CREATE TABLE IF NOT EXISTS assistant_runs (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
                workflow_lane TEXT NOT NULL DEFAULT '',
                objective TEXT NOT NULL DEFAULT '',
                playbook_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'planned',
                analyst_prompt TEXT NOT NULL DEFAULT '',
                plan_payload JSON,
                execution_payload JSON,
                last_error TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_by_email TEXT NOT NULL DEFAULT '',
                created_by_role TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_assistant_runs_case ON assistant_runs(case_id);
            CREATE INDEX IF NOT EXISTS idx_assistant_runs_status ON assistant_runs(status);
            CREATE INDEX IF NOT EXISTS idx_assistant_runs_updated ON assistant_runs(updated_at);

            CREATE TABLE IF NOT EXISTS neo4j_sync_jobs (
                job_id TEXT PRIMARY KEY,
                sync_kind TEXT NOT NULL DEFAULT 'full',
                status TEXT NOT NULL DEFAULT 'queued',
                since_timestamp TEXT,
                requested_by TEXT DEFAULT '',
                requested_by_email TEXT DEFAULT '',
                entities_synced INTEGER NOT NULL DEFAULT 0,
                relationships_synced INTEGER NOT NULL DEFAULT 0,
                duration_ms REAL NOT NULL DEFAULT 0,
                error TEXT,
                metadata JSON,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                started_at TEXT,
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_neo4j_sync_jobs_status ON neo4j_sync_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_neo4j_sync_jobs_created ON neo4j_sync_jobs(created_at);

            CREATE TABLE IF NOT EXISTS mission_briefs (
                id TEXT PRIMARY KEY,
                room TEXT NOT NULL DEFAULT 'stoa',
                case_id TEXT REFERENCES vendors(id),
                object_type TEXT,
                engagement_type TEXT,
                collection_depth TEXT NOT NULL DEFAULT 'full_picture',
                timeline TEXT,
                status TEXT NOT NULL DEFAULT 'scoped',
                question_count INTEGER NOT NULL DEFAULT 0,
                confidence_score REAL NOT NULL DEFAULT 0,
                primary_targets JSON NOT NULL DEFAULT '{}',
                known_context JSON NOT NULL DEFAULT '{}',
                priority_requirements JSON NOT NULL DEFAULT '[]',
                authorized_tiers JSON NOT NULL DEFAULT '[]',
                summary TEXT,
                notes JSON NOT NULL DEFAULT '[]',
                created_by TEXT,
                created_by_email TEXT,
                created_by_role TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_mission_briefs_case ON mission_briefs(case_id);
            CREATE INDEX IF NOT EXISTS idx_mission_briefs_room ON mission_briefs(room);
            CREATE INDEX IF NOT EXISTS idx_mission_briefs_updated ON mission_briefs(updated_at);
        """)
        conn.execute(f"UPDATE mission_briefs SET room = {mission_brief_room_sql('room')}")

        for statement in (
            "ALTER TABLE enrichment_reports ADD COLUMN report_hash TEXT",
            "ALTER TABLE monitoring_log ADD COLUMN run_id TEXT",
            "ALTER TABLE monitoring_log ADD COLUMN change_type TEXT NOT NULL DEFAULT 'no_change'",
            "ALTER TABLE monitoring_log ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'",
            "ALTER TABLE monitoring_log ADD COLUMN score_before REAL",
            "ALTER TABLE monitoring_log ADD COLUMN score_after REAL",
            "ALTER TABLE monitoring_log ADD COLUMN delta_summary TEXT",
            "ALTER TABLE monitoring_log ADD COLUMN sources_triggered JSON",
            "ALTER TABLE monitoring_log ADD COLUMN started_at TEXT",
            "ALTER TABLE monitoring_log ADD COLUMN completed_at TEXT",
        ):
            try:
                conn.execute(statement)
            except sqlite3.OperationalError:
                pass

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_enrichment_vendor_hash ON enrichment_reports(vendor_id, report_hash)"
        )


# ---- Vendor CRUD ----

def upsert_vendor(vendor_id: str, name: str, country: str, program: str,
                  vendor_input: dict, profile: str = "defense_acquisition") -> str:
    """
    Insert or update a vendor. Returns the vendor ID.

    Args:
        vendor_id: Unique vendor identifier
        name: Vendor name
        country: ISO-2 country code
        program: Program type (e.g., weapons_system, standard_industrial)
        vendor_input: Full vendor input JSON (ownership, data_quality, exec data)
        profile: Compliance profile ID (default: defense_acquisition)
    """
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO vendors (id, name, country, program, profile, vendor_input, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                country=excluded.country,
                program=excluded.program,
                profile=excluded.profile,
                vendor_input=excluded.vendor_input,
                updated_at=datetime('now')
        """, (vendor_id, name, country, program, profile, json.dumps(vendor_input)))
    return vendor_id


def get_vendor(vendor_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if not row:
            return None
        # sqlite3.Row is dict-like but use [] for access
        profile = row["profile"] if "profile" in row.keys() else "defense_acquisition"
        return {
            "id": row["id"], "name": row["name"], "country": row["country"],
            "program": row["program"], "profile": profile,
            "vendor_input": _safe_json_loads(row["vendor_input"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }


def list_vendors(limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM vendors ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            {"id": r["id"], "name": r["name"], "country": r["country"],
             "program": r["program"], "profile": r["profile"] if "profile" in r.keys() else "defense_acquisition",
             "vendor_input": _safe_json_loads(r["vendor_input"]),
             "created_at": r["created_at"]}
            for r in rows
        ]


def list_vendors_with_scores(limit: int = 100) -> list[dict]:
    """Fetch vendors with their latest scores in a single query (avoids N+1).

    Deduplicates by LOWER(name): when multiple vendor rows share the same
    normalised name, only the most-recently-updated row is returned.  This
    prevents repeated smoke-tests, deploy-verify runs, and re-intakes from
    cluttering the portfolio view (C1 audit finding).
    """
    with get_conn() as conn:
        rows = conn.execute("""
            WITH deduped AS (
                SELECT id, name, country, program, profile, vendor_input,
                       created_at, updated_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY LOWER(TRIM(name))
                           ORDER BY updated_at DESC, created_at DESC
                       ) AS rn
                FROM vendors
            )
            SELECT v.id, v.name, v.country, v.program, v.profile, v.vendor_input,
                   v.created_at, sr.full_result, sr.scored_at
            FROM deduped v
            LEFT JOIN scoring_results sr ON sr.vendor_id = v.id
                AND sr.id = (
                    SELECT id FROM scoring_results
                    WHERE vendor_id = v.id
                    ORDER BY scored_at DESC, id DESC
                    LIMIT 1
                )
            WHERE v.rn = 1
            ORDER BY v.updated_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        results = []
        for r in rows:
            score = None
            if r["full_result"]:
                score = _safe_json_loads(r["full_result"])
                score["scored_at"] = r["scored_at"]
            results.append({
                "id": r["id"], "name": r["name"], "country": r["country"],
                "program": r["program"],
                "profile": r["profile"] if "profile" in r.keys() else "defense_acquisition",
                "vendor_input": _safe_json_loads(r["vendor_input"]),
                "created_at": r["created_at"],
                "latest_score": score,
            })
        return results


def save_mission_brief(
    brief_id: str,
    *,
    room: str = DEFAULT_MISSION_BRIEF_ROOM,
    case_id: str | None = None,
    object_type: str | None = None,
    engagement_type: str | None = None,
    collection_depth: str = "full_picture",
    timeline: str | None = None,
    status: str = "scoped",
    question_count: int = 0,
    confidence_score: float = 0.0,
    primary_targets: dict | None = None,
    known_context: dict | None = None,
    priority_requirements: list[str] | None = None,
    authorized_tiers: list[str] | None = None,
    summary: str | None = None,
    notes: list[str] | None = None,
    created_by: str = "",
    created_by_email: str = "",
    created_by_role: str = "",
) -> dict:
    canonical_room = canonicalize_mission_brief_room(room)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO mission_briefs (
                id,
                room,
                case_id,
                object_type,
                engagement_type,
                collection_depth,
                timeline,
                status,
                question_count,
                confidence_score,
                primary_targets,
                known_context,
                priority_requirements,
                authorized_tiers,
                summary,
                notes,
                created_by,
                created_by_email,
                created_by_role,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                room = excluded.room,
                case_id = COALESCE(excluded.case_id, mission_briefs.case_id),
                object_type = COALESCE(excluded.object_type, mission_briefs.object_type),
                engagement_type = COALESCE(excluded.engagement_type, mission_briefs.engagement_type),
                collection_depth = excluded.collection_depth,
                timeline = COALESCE(excluded.timeline, mission_briefs.timeline),
                status = excluded.status,
                question_count = excluded.question_count,
                confidence_score = excluded.confidence_score,
                primary_targets = excluded.primary_targets,
                known_context = excluded.known_context,
                priority_requirements = excluded.priority_requirements,
                authorized_tiers = excluded.authorized_tiers,
                summary = COALESCE(excluded.summary, mission_briefs.summary),
                notes = excluded.notes,
                created_by = CASE
                    WHEN mission_briefs.created_by = '' THEN excluded.created_by
                    ELSE mission_briefs.created_by
                END,
                created_by_email = CASE
                    WHEN mission_briefs.created_by_email = '' THEN excluded.created_by_email
                    ELSE mission_briefs.created_by_email
                END,
                created_by_role = CASE
                    WHEN mission_briefs.created_by_role = '' THEN excluded.created_by_role
                    ELSE mission_briefs.created_by_role
                END,
                updated_at = datetime('now')
            """,
            (
                brief_id,
                canonical_room,
                case_id,
                object_type,
                engagement_type,
                collection_depth,
                timeline,
                status,
                int(question_count or 0),
                float(confidence_score or 0.0),
                json.dumps(primary_targets or {}),
                json.dumps(known_context or {}),
                json.dumps(priority_requirements or []),
                json.dumps(authorized_tiers or []),
                summary,
                json.dumps(notes or []),
                created_by,
                created_by_email,
                created_by_role,
            ),
        )
        row = conn.execute("SELECT * FROM mission_briefs WHERE id = ?", (brief_id,)).fetchone()
    mission_brief = _row_to_mission_brief(row)
    return mission_brief or {"id": brief_id}


def get_mission_brief(brief_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM mission_briefs WHERE id = ?", (brief_id,)).fetchone()
    return _row_to_mission_brief(row)


def get_latest_case_mission_brief(case_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM mission_briefs
            WHERE case_id = ?
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()
    return _row_to_mission_brief(row)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _normalize_db_timestamp(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _decode_json_list(value) -> list:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return value
    parsed = _safe_json_loads(value)
    return parsed if isinstance(parsed, list) else []


def _monitoring_row_to_dict(row) -> dict:
    result = dict(row)
    for key in ("checked_at", "started_at", "completed_at"):
        result[key] = _normalize_db_timestamp(result.get(key))
    result["sources_triggered"] = _decode_json_list(result.get("sources_triggered"))
    return result


def delete_vendor(vendor_id: str) -> bool:
    secure_case_dir = Path(get_secure_artifacts_dir()) / vendor_id
    dossier_dir = Path(__file__).resolve().parent / "dossiers"

    with get_conn() as conn:
        vendor_exists = conn.execute(
            "SELECT 1 FROM vendors WHERE id = ?",
            (vendor_id,),
        ).fetchone()
        if not vendor_exists:
            return False

        for table_name, key_name in (
            ("artifact_records", "case_id"),
            ("case_events", "case_id"),
            ("intel_summary_jobs", "case_id"),
            ("intel_summaries", "case_id"),
            ("person_screenings", "case_id"),
            ("transaction_authorizations", "case_id"),
            ("authorization_audit", "case_id"),
            ("monitoring_log", "vendor_id"),
            ("decisions", "vendor_id"),
            ("enrichment_reports", "vendor_id"),
            ("alerts", "vendor_id"),
            ("scoring_results", "vendor_id"),
            ("batch_items", "case_id"),
            ("ai_analysis_jobs", "case_id"),
            ("ai_analyses", "vendor_id"),
            ("beta_feedback", "case_id"),
            ("beta_events", "case_id"),
        ):
            if _table_exists(conn, table_name):
                conn.execute(f"DELETE FROM {table_name} WHERE {key_name} = ?", (vendor_id,))

        conn.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))

    try:
        import knowledge_graph as kg  # type: ignore

        kg.clear_vendor_links(vendor_id)
    except Exception:
        pass

    shutil.rmtree(secure_case_dir, ignore_errors=True)
    if dossier_dir.exists():
        for path in dossier_dir.glob(f"dossier-{vendor_id}-*.html"):
            path.unlink(missing_ok=True)
    return True


# ---- Scoring results ----

def save_score(vendor_id: str, result_dict: dict) -> int:
    """Save a scoring result. Returns the row ID."""
    cal = result_dict.get("calibrated", {})
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO scoring_results
                (vendor_id, calibrated_probability, calibrated_tier, composite_score,
                 is_hard_stop, interval_lower, interval_upper, interval_coverage, full_result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            vendor_id,
            cal.get("calibrated_probability", 0),
            cal.get("calibrated_tier", "unknown"),
            result_dict.get("composite_score", 0),
            result_dict.get("is_hard_stop", False),
            cal.get("interval", {}).get("lower", 0),
            cal.get("interval", {}).get("upper", 0),
            cal.get("interval", {}).get("coverage", 0),
            json.dumps(result_dict),
        ))
        return cursor.lastrowid


def get_latest_score(vendor_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT full_result, scored_at FROM scoring_results
            WHERE vendor_id = ?
            ORDER BY scored_at DESC, id DESC
            LIMIT 1
        """, (vendor_id,)).fetchone()
        if not row:
            return None
        result = _safe_json_loads(row["full_result"])
        result["scored_at"] = row["scored_at"]
        return result


def get_score_history(vendor_id: str, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT calibrated_probability, calibrated_tier, composite_score, scored_at
            FROM scoring_results WHERE vendor_id = ?
            ORDER BY scored_at DESC, id DESC LIMIT ?
        """, (vendor_id, limit)).fetchall()
        return [dict(r) for r in rows]


# ---- Alerts ----

def save_alert(vendor_id: str, entity_name: str, severity: str,
               title: str, description: str = "") -> int:
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO alerts (vendor_id, entity_name, severity, title, description)
            VALUES (?, ?, ?, ?, ?)
        """, (vendor_id, entity_name, severity, title, description))
        return cursor.lastrowid


def save_alerts_batch(alerts: list[dict]) -> int:
    """Insert multiple alerts in a single transaction. Each dict needs:
    vendor_id, entity_name, severity, title, description (optional)."""
    if not alerts:
        return 0
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO alerts (vendor_id, entity_name, severity, title, description)
            VALUES (:vendor_id, :entity_name, :severity, :title, :description)
        """, [
            {
                "vendor_id": a["vendor_id"],
                "entity_name": a["entity_name"],
                "severity": a["severity"],
                "title": a["title"],
                "description": a.get("description", ""),
            }
            for a in alerts
        ])
        return len(alerts)


def list_alerts(limit: int = 50, unresolved_only: bool = False) -> list[dict]:
    with get_conn() as conn:
        query = "SELECT * FROM alerts"
        if unresolved_only:
            query += " WHERE resolved = 0"
        query += " ORDER BY id DESC LIMIT ?"
        rows = conn.execute(query, (limit,)).fetchall()
        return [dict(r) for r in rows]


def resolve_alert(alert_id: int, resolved_by: str = "analyst") -> bool:
    with get_conn() as conn:
        cursor = conn.execute("""
            UPDATE alerts SET resolved = 1, resolved_by = ?, resolved_at = datetime('now')
            WHERE id = ? AND resolved = 0
        """, (resolved_by, alert_id))
        return cursor.rowcount > 0


# ---- Screening log ----

def log_screening(query_name: str, result: dict) -> int:
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO screening_log (query_name, matched, best_score, matched_name,
                                       matched_list, result_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            query_name,
            result.get("matched", False),
            result.get("best_score", 0),
            result.get("matched_name", ""),
            result.get("matched_entry", {}).get("list", "") if result.get("matched_entry") else "",
            json.dumps(result),
        ))
        return cursor.lastrowid


def get_screening_history(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM screening_log ORDER BY screened_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---- Enrichment reports ----

def save_enrichment(vendor_id: str, report: dict) -> int:
    """Save an OSINT enrichment report. Returns the row ID."""
    summary = report.get("summary", {})
    report_hash = report.get("report_hash") or compute_report_hash(report)
    report["report_hash"] = report_hash
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO enrichment_reports
                (vendor_id, overall_risk, findings_total, critical_count, high_count,
                 identifiers, connectors_run, total_elapsed_ms, report_hash, full_report)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            vendor_id,
            report.get("overall_risk", "UNKNOWN"),
            summary.get("findings_total", 0),
            summary.get("critical", 0),
            summary.get("high", 0),
            json.dumps(report.get("identifiers", {})),
            summary.get("connectors_run", 0),
            report.get("total_elapsed_ms", 0),
            report_hash,
            json.dumps(report),
        ))
        return cursor.lastrowid


def get_latest_enrichment(vendor_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT full_report, enriched_at, report_hash FROM enrichment_reports
            WHERE vendor_id = ? ORDER BY enriched_at DESC LIMIT 1
        """, (vendor_id,)).fetchone()
        return _row_to_enrichment_report(row)


def get_latest_peer_enrichment(vendor_name: str, *, exclude_vendor_id: str = "", candidate_limit: int = 100) -> dict | None:
    normalized = _normalize_vendor_name_for_match(vendor_name)
    if not normalized:
        return None

    lower_name = str(vendor_name or "").strip().lower()
    exclude_clause = "AND v.id != ?" if exclude_vendor_id else ""
    params: list[object] = [lower_name]
    if exclude_vendor_id:
        params.append(exclude_vendor_id)

    with get_conn() as conn:
        exact_row = conn.execute(
            f"""
            SELECT er.full_report, er.enriched_at, er.report_hash
            FROM vendors v
            JOIN enrichment_reports er ON er.vendor_id = v.id
            WHERE lower(v.name) = ?
            {exclude_clause}
            ORDER BY er.enriched_at DESC
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        if exact_row:
            return _row_to_enrichment_report(exact_row)

        primary_token = normalized.split()[0] if normalized.split() else ""
        if not primary_token:
            return None

        like_params: list[object] = [f"%{primary_token}%"]
        if exclude_vendor_id:
            like_params.append(exclude_vendor_id)
        like_params.append(int(candidate_limit))
        candidate_rows = conn.execute(
            f"""
            SELECT v.name, er.full_report, er.enriched_at, er.report_hash
            FROM vendors v
            JOIN enrichment_reports er ON er.vendor_id = v.id
            WHERE lower(v.name) LIKE ?
            {exclude_clause}
            ORDER BY er.enriched_at DESC
            LIMIT ?
            """,
            tuple(like_params),
        ).fetchall()

    for row in candidate_rows:
        if _normalize_vendor_name_for_match(row["name"]) == normalized:
            return _row_to_enrichment_report(row)
    return None


def get_enrichment_history(vendor_id: str, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT overall_risk, findings_total, critical_count, high_count,
                   connectors_run, total_elapsed_ms, enriched_at
            FROM enrichment_reports WHERE vendor_id = ?
            ORDER BY enriched_at DESC LIMIT ?
        """, (vendor_id, limit)).fetchall()
        return [dict(r) for r in rows]


# ---- Secure artifact vault ----

def create_artifact_record(
    artifact_id: str,
    case_id: str,
    artifact_type: str,
    *,
    source_system: str = "",
    source_class: str = "",
    authority_level: str = "",
    access_model: str = "",
    uploaded_by: str = "",
    filename: str,
    content_type: str = "application/octet-stream",
    size_bytes: int = 0,
    sha256: str = "",
    storage_ref: str,
    retention_class: str = "standard",
    sensitivity: str = "controlled",
    effective_date: str | None = None,
    parse_status: str = "pending",
    structured_fields: dict | None = None,
) -> str:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO artifact_records
                (id, case_id, artifact_type, source_system, source_class, authority_level, access_model,
                 uploaded_by, filename, content_type, size_bytes, sha256, storage_ref,
                 retention_class, sensitivity, effective_date, parse_status, structured_fields)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                case_id,
                artifact_type,
                source_system,
                source_class,
                authority_level,
                access_model,
                uploaded_by,
                filename,
                content_type,
                int(size_bytes),
                sha256,
                storage_ref,
                retention_class,
                sensitivity,
                effective_date,
                parse_status,
                json.dumps(structured_fields or {}),
            ),
        )
    return artifact_id


def update_artifact_record(artifact_id: str, **updates) -> bool:
    allowed = {
        "source_system",
        "source_class",
        "authority_level",
        "access_model",
        "uploaded_by",
        "filename",
        "content_type",
        "size_bytes",
        "sha256",
        "storage_ref",
        "retention_class",
        "sensitivity",
        "effective_date",
        "parse_status",
        "structured_fields",
    }
    payload = {key: value for key, value in updates.items() if key in allowed}
    if not payload:
        return False
    if "structured_fields" in payload:
        payload["structured_fields"] = json.dumps(payload["structured_fields"] or {})
    payload["updated_at"] = datetime.utcnow().isoformat() + "Z"
    assignments = ", ".join(f"{field} = ?" for field in payload)
    with get_conn() as conn:
        cursor = conn.execute(
            f"UPDATE artifact_records SET {assignments} WHERE id = ?",
            (*payload.values(), artifact_id),
        )
        return cursor.rowcount > 0


def get_artifact_record(artifact_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM artifact_records WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["structured_fields"] = _safe_json_loads(row["structured_fields"]) if row["structured_fields"] else {}
        return result


def list_artifact_records(case_id: str, artifact_type: str | None = None, limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        if artifact_type:
            rows = conn.execute(
                """
                SELECT * FROM artifact_records
                WHERE case_id = ? AND artifact_type = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (case_id, artifact_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM artifact_records
                WHERE case_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (case_id, limit),
            ).fetchall()
        records = []
        for row in rows:
            item = dict(row)
            item["structured_fields"] = _safe_json_loads(row["structured_fields"]) if row["structured_fields"] else {}
            records.append(item)
        return records


# ---- Beta ops ----

def save_beta_feedback(
    *,
    user_id: str = "",
    user_email: str = "",
    user_role: str = "",
    case_id: str | None = None,
    workflow_lane: str = "",
    screen: str = "",
    category: str = "general",
    severity: str = "medium",
    summary: str,
    details: str = "",
    status: str = "open",
    metadata: dict | None = None,
) -> int:
    with get_conn() as conn:
        params = (
            user_id or None,
            user_email or None,
            user_role or None,
            case_id,
            workflow_lane,
            screen,
            category,
            severity,
            summary,
            details,
            status,
            json.dumps(metadata or {}),
        )
        if _use_postgres:
            row = conn.execute(
                """
                INSERT INTO beta_feedback
                    (user_id, user_email, user_role, case_id, workflow_lane, screen,
                     category, severity, summary, details, status, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                params,
            ).fetchone()
            return int((row or {}).get("id") or 0)
        cursor = conn.execute(
            """
            INSERT INTO beta_feedback
                (user_id, user_email, user_role, case_id, workflow_lane, screen,
                 category, severity, summary, details, status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )
        return cursor.lastrowid


def list_beta_feedback(limit: int = 100, status: str = "", workflow_lane: str = "") -> list[dict]:
    query = "SELECT * FROM beta_feedback WHERE 1=1"
    params: list[object] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if workflow_lane:
        query += " AND workflow_lane = ?"
        params.append(workflow_lane)
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        entries = []
        for row in rows:
            item = dict(row)
            item["metadata"] = _safe_json_loads(row["metadata"]) if row["metadata"] else {}
            entries.append(item)
        return entries


def save_beta_event(
    *,
    user_id: str = "",
    user_email: str = "",
    user_role: str = "",
    case_id: str | None = None,
    workflow_lane: str = "",
    screen: str = "",
    event_name: str,
    metadata: dict | None = None,
) -> int:
    with get_conn() as conn:
        params = (
            user_id or None,
            user_email or None,
            user_role or None,
            case_id,
            workflow_lane,
            screen,
            event_name,
            json.dumps(metadata or {}),
        )
        if _use_postgres:
            row = conn.execute(
                """
                INSERT INTO beta_events
                    (user_id, user_email, user_role, case_id, workflow_lane, screen, event_name, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                params,
            ).fetchone()
            return int((row or {}).get("id") or 0)
        cursor = conn.execute(
            """
            INSERT INTO beta_events
                (user_id, user_email, user_role, case_id, workflow_lane, screen, event_name, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )
        return cursor.lastrowid


def save_assistant_run(
    *,
    run_id: str,
    case_id: str,
    workflow_lane: str = "",
    objective: str = "",
    playbook_id: str = "",
    status: str = "planned",
    analyst_prompt: str = "",
    plan_payload: dict | None = None,
    execution_payload: dict | None = None,
    last_error: str = "",
    created_by: str = "",
    created_by_email: str = "",
    created_by_role: str = "",
) -> str:
    payload = (
        run_id,
        case_id,
        workflow_lane,
        objective,
        playbook_id,
        status,
        analyst_prompt,
        json.dumps(plan_payload or {}),
        json.dumps(execution_payload or {}),
        last_error,
        created_by,
        created_by_email,
        created_by_role,
    )
    with get_conn() as conn:
        if _use_postgres:
            conn.execute(
                """
                INSERT INTO assistant_runs
                    (id, case_id, workflow_lane, objective, playbook_id, status,
                     analyst_prompt, plan_payload, execution_payload, last_error,
                     created_by, created_by_email, created_by_role)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
        else:
            conn.execute(
                """
                INSERT INTO assistant_runs
                    (id, case_id, workflow_lane, objective, playbook_id, status,
                     analyst_prompt, plan_payload, execution_payload, last_error,
                     created_by, created_by_email, created_by_role)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
    return run_id


def update_assistant_run(
    run_id: str,
    *,
    status: str | None = None,
    plan_payload: dict | None = None,
    execution_payload: dict | None = None,
    last_error: str | None = None,
) -> None:
    updates: list[str] = []
    params: list[object] = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if plan_payload is not None:
        updates.append("plan_payload = ?")
        params.append(json.dumps(plan_payload))
    if execution_payload is not None:
        updates.append("execution_payload = ?")
        params.append(json.dumps(execution_payload))
    if last_error is not None:
        updates.append("last_error = ?")
        params.append(last_error)
    if not updates:
        return
    updates.append("updated_at = datetime('now')" if not _use_postgres else "updated_at = NOW()")
    params.append(run_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE assistant_runs SET {', '.join(updates)} WHERE id = ?",
            params,
        )


def get_assistant_run(run_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM assistant_runs WHERE id = ?", (run_id,)).fetchone()
    return _row_to_assistant_run(row)


def list_case_assistant_runs(case_id: str, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM assistant_runs WHERE case_id = ? ORDER BY updated_at DESC, created_at DESC LIMIT ?",
            (case_id, limit),
        ).fetchall()
    return [_row_to_assistant_run(row) for row in rows if row]


def get_beta_ops_summary(hours: int = 168) -> dict:
    window_clause = f"-{max(1, int(hours))} hours"
    with get_conn() as conn:
        open_feedback = conn.execute(
            "SELECT COUNT(*) FROM beta_feedback WHERE status = 'open'"
        ).fetchone()[0]
        feedback_last_24h = conn.execute(
            "SELECT COUNT(*) FROM beta_feedback WHERE created_at >= datetime('now', '-24 hours')"
        ).fetchone()[0]
        event_count = conn.execute(
            "SELECT COUNT(*) FROM beta_events WHERE created_at >= datetime('now', ?)",
            (window_clause,),
        ).fetchone()[0]
        feedback_by_severity = [
            dict(row) for row in conn.execute(
                """
                SELECT severity, COUNT(*) AS count
                FROM beta_feedback
                WHERE created_at >= datetime('now', ?)
                GROUP BY severity
                ORDER BY count DESC, severity ASC
                """,
                (window_clause,),
            ).fetchall()
        ]
        feedback_by_lane = [
            dict(row) for row in conn.execute(
                """
                SELECT workflow_lane, COUNT(*) AS count
                FROM beta_feedback
                WHERE created_at >= datetime('now', ?)
                GROUP BY workflow_lane
                ORDER BY count DESC, workflow_lane ASC
                """,
                (window_clause,),
            ).fetchall()
        ]
        event_counts = [
            dict(row) for row in conn.execute(
                """
                SELECT event_name, COUNT(*) AS count
                FROM beta_events
                WHERE created_at >= datetime('now', ?)
                GROUP BY event_name
                ORDER BY count DESC, event_name ASC
                LIMIT 10
                """,
                (window_clause,),
            ).fetchall()
        ]
        event_counts_by_lane = [
            dict(row) for row in conn.execute(
                """
                SELECT workflow_lane, COUNT(*) AS count
                FROM beta_events
                WHERE created_at >= datetime('now', ?)
                GROUP BY workflow_lane
                ORDER BY count DESC, workflow_lane ASC
                """,
                (window_clause,),
            ).fetchall()
        ]
        return {
            "hours": max(1, int(hours)),
            "open_feedback_count": open_feedback,
            "feedback_last_24h": feedback_last_24h,
            "recent_event_count": event_count,
            "feedback_by_severity": feedback_by_severity,
            "feedback_by_lane": feedback_by_lane,
            "event_counts": event_counts,
            "event_counts_by_lane": event_counts_by_lane,
        }


def replace_case_events(case_id: str, report_hash: str, events: list[dict]) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM case_events WHERE case_id = ? AND report_hash = ?",
            (case_id, report_hash),
        )
        for event in events:
            conn.execute(
                """
                INSERT INTO case_events
                    (case_id, report_hash, finding_id, event_type, subject, date_range, jurisdiction,
                     status, confidence, source_refs, source_finding_ids, connector,
                     normalization_method, severity, title, assessment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    report_hash,
                    event.get("finding_id", ""),
                    event.get("event_type", ""),
                    event.get("subject", ""),
                    json.dumps(event.get("date_range") or {}),
                    event.get("jurisdiction", ""),
                    event.get("status", "active"),
                    float(event.get("confidence") or 0.0),
                    json.dumps(event.get("source_refs") or []),
                    json.dumps(event.get("source_finding_ids") or []),
                    event.get("connector", ""),
                    event.get("normalization_method", "deterministic"),
                    event.get("severity", "info"),
                    event.get("title", ""),
                    event.get("assessment", ""),
                ),
            )


def get_case_events(case_id: str, report_hash: str | None = None) -> list[dict]:
    query = """
        SELECT * FROM case_events
        WHERE case_id = ?
    """
    params: list[object] = [case_id]
    if report_hash:
        query += " AND report_hash = ?"
        params.append(report_hash)
    query += " ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'historical' THEN 1 ELSE 2 END, confidence DESC, id ASC"

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [
            {
                **dict(row),
                "date_range": _safe_json_loads(row["date_range"]) if row["date_range"] else {},
                "source_refs": _safe_json_loads(row["source_refs"]) if row["source_refs"] else [],
                "source_finding_ids": _safe_json_loads(row["source_finding_ids"]) if row["source_finding_ids"] else [],
            }
            for row in rows
        ]


def save_intel_summary(
    case_id: str,
    user_id: str,
    report_hash: str,
    summary: dict,
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    elapsed_ms: int = 0,
    prompt_version: str = "",
) -> int:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO intel_summaries
                (case_id, created_by, report_hash, prompt_version, provider, model,
                 prompt_tokens, completion_tokens, elapsed_ms, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                user_id,
                report_hash,
                prompt_version,
                provider,
                model,
                prompt_tokens,
                completion_tokens,
                elapsed_ms,
                json.dumps(summary),
            ),
        )
        return cursor.lastrowid


def get_latest_intel_summary(case_id: str, user_id: str = "", report_hash: str = "") -> dict | None:
    query = "SELECT * FROM intel_summaries WHERE case_id = ?"
    params: list[object] = [case_id]
    if user_id:
        query += " AND created_by = ?"
        params.append(user_id)
    if report_hash:
        query += " AND report_hash = ?"
        params.append(report_hash)
    query += " ORDER BY created_at DESC, id DESC LIMIT 1"

    with get_conn() as conn:
        row = conn.execute(query, params).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "case_id": row["case_id"],
            "created_by": row["created_by"],
            "report_hash": row["report_hash"],
            "prompt_version": row["prompt_version"],
            "provider": row["provider"],
            "model": row["model"],
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
            "elapsed_ms": row["elapsed_ms"],
            "summary": _safe_json_loads(row["summary"]),
            "created_at": row["created_at"],
        }


# ---- Monitoring log ----

def save_monitoring_log(vendor_id: str, previous_risk: str, current_risk: str,
                        risk_changed: bool, new_findings_count: int = 0,
                        resolved_findings_count: int = 0, *, run_id: str = "",
                        change_type: str = "no_change", status: str = "completed",
                        score_before: float | None = None, score_after: float | None = None,
                        delta_summary: str = "", sources_triggered: list[str] | None = None,
                        started_at: str = "", completed_at: str = "") -> int:
    """Save a monitoring check result. Returns the row ID."""
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO monitoring_log
                (vendor_id, run_id, previous_risk, current_risk, risk_changed,
                 change_type, status, score_before, score_after,
                 new_findings_count, resolved_findings_count, delta_summary,
                 sources_triggered, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            vendor_id,
            run_id or None,
            previous_risk,
            current_risk,
            risk_changed,
            change_type or "no_change",
            status or "completed",
            score_before,
            score_after,
            new_findings_count,
            resolved_findings_count,
            delta_summary or "",
            json.dumps(list(sources_triggered or [])),
            started_at or None,
            completed_at or None,
        ))
        return cursor.lastrowid


def get_monitoring_history(vendor_id: str, limit: int = 20) -> list[dict]:
    """Get monitoring check history for a vendor."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, vendor_id, run_id, previous_risk, current_risk, risk_changed,
                   change_type, status, score_before, score_after,
                   new_findings_count, resolved_findings_count, delta_summary,
                   sources_triggered, started_at, completed_at, checked_at
            FROM monitoring_log WHERE vendor_id = ?
            ORDER BY checked_at DESC LIMIT ?
        """, (vendor_id, limit)).fetchall()
        return [_monitoring_row_to_dict(r) for r in rows]


def get_monitor_run_history(vendor_id: str, limit: int = 20) -> list[dict]:
    """Get monitor-run history joined with vendor name for case-detail history surfaces."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ml.id, ml.vendor_id, v.name AS vendor_name, ml.run_id,
                   ml.previous_risk, ml.current_risk, ml.risk_changed,
                   ml.change_type, ml.status, ml.score_before, ml.score_after,
                   ml.new_findings_count, ml.resolved_findings_count,
                   ml.delta_summary, ml.sources_triggered,
                   ml.started_at, ml.completed_at, ml.checked_at
            FROM monitoring_log ml
            JOIN vendors v ON v.id = ml.vendor_id
            WHERE ml.vendor_id = ?
            ORDER BY ml.checked_at DESC, ml.id DESC
            LIMIT ?
        """, (vendor_id, limit)).fetchall()
        return [_monitoring_row_to_dict(r) for r in rows]


def get_recent_risk_changes(limit: int = 20) -> list[dict]:
    """Get recent vendors where risk tier changed during monitoring."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT vendor_id, previous_risk, current_risk, checked_at
            FROM monitoring_log WHERE CAST(risk_changed AS INTEGER) = 1
            ORDER BY checked_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [_monitoring_row_to_dict(r) for r in rows]


def _monitor_since_clause(since_hours: int | None) -> tuple[str, list]:
    if not since_hours or since_hours <= 0:
        return "", []
    if _use_postgres:
        return " AND ml.checked_at >= NOW() - (%s * INTERVAL '1 hour') ", [since_hours]
    return " AND ml.checked_at >= datetime('now', ?) ", [f"-{since_hours} hours"]


def get_recent_monitor_changes(limit: int = 20, since_hours: int | None = None) -> list[dict]:
    """Get recent meaningful portfolio changes from monitoring with summary metadata."""
    time_clause, time_params = _monitor_since_clause(since_hours)
    query = f"""
        SELECT ml.id, ml.vendor_id, v.name AS vendor_name, ml.run_id,
               ml.previous_risk, ml.current_risk, ml.risk_changed,
               ml.change_type, ml.status, ml.score_before, ml.score_after,
               ml.new_findings_count, ml.resolved_findings_count,
               ml.delta_summary, ml.sources_triggered,
               ml.started_at, ml.completed_at, ml.checked_at
        FROM monitoring_log ml
        JOIN vendors v ON v.id = ml.vendor_id
        WHERE (
            (ml.risk_changed IS NOT NULL AND CAST(ml.risk_changed AS INTEGER) != 0)
            OR COALESCE(ml.new_findings_count, 0) > 0
            OR ABS(COALESCE(ml.score_after, 0) - COALESCE(ml.score_before, 0)) >= 0.01
            OR COALESCE(ml.change_type, 'no_change') != 'no_change'
        )
        {time_clause}
        ORDER BY ml.checked_at DESC, ml.id DESC
        LIMIT ?
    """
    params = [*time_params, limit]
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [_monitoring_row_to_dict(r) for r in rows]


def get_all_monitoring_history(limit: int = 500) -> list[dict]:
    """Get monitoring history across all vendors (for portfolio trend)."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT vendor_id, previous_risk, current_risk, risk_changed,
                   new_findings_count, resolved_findings_count, checked_at
            FROM monitoring_log
            ORDER BY checked_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def save_anomaly(vendor_id: str, entity_name: str, detector: str,
                 severity: str, title: str, detail: str = "",
                 evidence: str = "") -> int:
    """Save an anomaly as an alert with detector metadata."""
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO alerts (vendor_id, entity_name, severity, title,
                                description)
            VALUES (?, ?, ?, ?, ?)
        """, (vendor_id, entity_name, severity,
              f"[{detector.upper()}] {title}", f"{detail}\n\n{evidence}".strip()))
        return cursor.lastrowid


# ---- Stats ----

def get_stats() -> dict:
    with get_conn() as conn:
        vendor_count = conn.execute("SELECT COUNT(DISTINCT LOWER(TRIM(name))) FROM vendors").fetchone()[0]
        alert_count = conn.execute("SELECT COUNT(*) FROM alerts WHERE resolved = 0").fetchone()[0]
        screening_count = conn.execute("SELECT COUNT(*) FROM screening_log").fetchone()[0]

        tier_dist = {}
        rows = conn.execute("""
            SELECT s.calibrated_tier, COUNT(*) as cnt
            FROM scoring_results s
            INNER JOIN (
                SELECT vendor_id, MAX(scored_at) as latest
                FROM scoring_results GROUP BY vendor_id
            ) latest ON s.vendor_id = latest.vendor_id AND s.scored_at = latest.latest
            GROUP BY s.calibrated_tier
        """).fetchall()
        for r in rows:
            tier_dist[r["calibrated_tier"]] = r["cnt"]

        return {
            "vendors": vendor_count,
            "unresolved_alerts": alert_count,
            "screenings": screening_count,
            "tier_distribution": tier_dist,
        }


# ---- Decisions ----

def save_decision(vendor_id: str, decision: str, user_id: str | None = None,
                  email: str | None = None, reason: str | None = None,
                  posterior: float | None = None, tier: str | None = None) -> int:
    """Save an approval/rejection/escalation decision. Returns the row ID."""
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO decisions
                (vendor_id, decision, decided_by, decided_by_email, reason,
                 posterior_at_decision, tier_at_decision)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (vendor_id, decision, user_id, email, reason, posterior, tier))
        return cursor.lastrowid


def get_decisions(vendor_id: str, limit: int = 50) -> list[dict]:
    """Get all decisions for a vendor, most recent first."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, vendor_id, decision, decided_by, decided_by_email, reason,
                   posterior_at_decision, tier_at_decision, created_at
            FROM decisions WHERE vendor_id = ?
            ORDER BY created_at DESC LIMIT ?
        """, (vendor_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_latest_decision(vendor_id: str) -> dict | None:
    """Get the most recent decision for a vendor."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT id, vendor_id, decision, decided_by, decided_by_email, reason,
                   posterior_at_decision, tier_at_decision, created_at
            FROM decisions WHERE vendor_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (vendor_id,)).fetchone()
        return dict(row) if row else None


# ---- Batch import ----

def create_batch(batch_id: str, uploaded_by: str, uploaded_by_email: str,
                 filename: str, total_vendors: int) -> str:
    """Create a new batch record. Returns the batch ID."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO batches (id, uploaded_by, uploaded_by_email, filename, total_vendors, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (batch_id, uploaded_by, uploaded_by_email, filename, total_vendors))
    return batch_id


def update_batch_progress(batch_id: str, processed: int, status: str) -> bool:
    """Update batch progress. Returns True if successful."""
    with get_conn() as conn:
        cursor = conn.execute("""
            UPDATE batches SET processed = ?, status = ?
            WHERE id = ?
        """, (processed, status, batch_id))
        return cursor.rowcount > 0


def complete_batch(batch_id: str) -> bool:
    """Mark batch as completed. Returns True if successful."""
    with get_conn() as conn:
        cursor = conn.execute("""
            UPDATE batches SET status = 'completed', completed_at = datetime('now')
            WHERE id = ?
        """, (batch_id,))
        return cursor.rowcount > 0


def fail_batch(batch_id: str) -> bool:
    """Mark batch as failed. Returns True if successful."""
    with get_conn() as conn:
        cursor = conn.execute("""
            UPDATE batches SET status = 'failed', completed_at = datetime('now')
            WHERE id = ?
        """, (batch_id,))
        return cursor.rowcount > 0


def add_batch_item(batch_id: str, vendor_name: str, country: str,
                   case_id: str | None = None, tier: str | None = None,
                   posterior: float | None = None, findings_count: int | None = None,
                   status: str = "pending", error: str | None = None) -> int:
    """Add an item to a batch. Returns the row ID."""
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO batch_items
                (batch_id, vendor_name, country, case_id, tier, posterior, findings_count, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (batch_id, vendor_name, country, case_id, tier, posterior, findings_count, status, error))
        return cursor.lastrowid


def update_batch_item(batch_item_id: int, case_id: str | None = None, tier: str | None = None,
                      posterior: float | None = None, findings_count: int | None = None,
                      status: str | None = None, error: str | None = None) -> bool:
    """Update a batch item. Returns True if successful."""
    updates = []
    params = []
    if case_id is not None:
        updates.append("case_id = ?")
        params.append(case_id)
    if tier is not None:
        updates.append("tier = ?")
        params.append(tier)
    if posterior is not None:
        updates.append("posterior = ?")
        params.append(posterior)
    if findings_count is not None:
        updates.append("findings_count = ?")
        params.append(findings_count)
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if error is not None:
        updates.append("error = ?")
        params.append(error)

    if not updates:
        return False

    params.append(batch_item_id)
    with get_conn() as conn:
        cursor = conn.execute(f"""
            UPDATE batch_items SET {', '.join(updates)}
            WHERE id = ?
        """, params)
        return cursor.rowcount > 0


def get_batches(uploaded_by: str | None = None, limit: int = 100) -> list[dict]:
    """Get batches, optionally filtered by uploaded_by. Returns most recent first."""
    with get_conn() as conn:
        if uploaded_by:
            rows = conn.execute("""
                SELECT * FROM batches WHERE uploaded_by = ?
                ORDER BY created_at DESC LIMIT ?
            """, (uploaded_by, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM batches
                ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_batch(batch_id: str) -> dict | None:
    """Get a single batch with all its items."""
    with get_conn() as conn:
        batch_row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if not batch_row:
            return None

        items_rows = conn.execute("""
            SELECT * FROM batch_items WHERE batch_id = ?
            ORDER BY created_at ASC
        """, (batch_id,)).fetchall()

        return {
            **dict(batch_row),
            "items": [dict(r) for r in items_rows],
        }


def get_batch_items(batch_id: str, limit: int = 1000) -> list[dict]:
    """Get all items in a batch."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM batch_items WHERE batch_id = ?
            ORDER BY created_at ASC LIMIT ?
        """, (batch_id, limit)).fetchall()
        return [dict(r) for r in rows]


# ---- Migration ----

def migrate_add_profile_column():
    """
    Migrate existing vendors table to add profile column if it doesn't exist.
    Safe to call multiple times. Called automatically during server startup.
    """
    with get_conn() as conn:
        try:
            conn.execute("SELECT profile FROM vendors LIMIT 1")
        except Exception:
            try:
                conn.execute("""
                    ALTER TABLE vendors ADD COLUMN profile TEXT NOT NULL DEFAULT 'defense_acquisition'
                """)
                logger.info("Migration: Added 'profile' column to vendors table")
            except Exception as migration_e:
                logger.warning(f"Migration: Profile column already exists or skipped: {migration_e}")


def migrate_intelligence_tables():
    """Additive migrations for intel summary and event storage tables."""
    with get_conn() as conn:
        for statement in (
            "ALTER TABLE enrichment_reports ADD COLUMN report_hash TEXT",
        ):
            try:
                conn.execute(statement)
            except Exception as e:
                logger.debug(f"Migration: Column likely already exists, skipping: {e}")


# ---- Monitoring schedules ----

def create_sweep(sweep_id: str, total_vendors: int, status: str = "running") -> str:
    """Create a new monitoring sweep record. Returns the sweep_id."""
    started_at = "datetime('now')" if status == "running" else "NULL"
    with get_conn() as conn:
        conn.execute(
            f"""
            INSERT INTO monitor_schedules (sweep_id, status, total_vendors, started_at)
            VALUES (?, ?, ?, {started_at})
            """,
            (sweep_id, status, total_vendors),
        )
    return sweep_id


def start_sweep(sweep_id: str, total_vendors: int) -> bool:
    """Mark a queued monitoring sweep as running and set its workload size."""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE monitor_schedules
            SET status = 'running',
                total_vendors = ?,
                started_at = COALESCE(started_at, datetime('now'))
            WHERE sweep_id = ?
            """,
            (total_vendors, sweep_id),
        )
        return cursor.rowcount > 0


def update_sweep_progress(sweep_id: str, processed: int, risk_changes: int, new_alerts: int, status: str) -> bool:
    """Update sweep progress. Returns True if successful."""
    with get_conn() as conn:
        cursor = conn.execute("""
            UPDATE monitor_schedules
            SET processed = ?, risk_changes = ?, new_alerts = ?, status = ?
            WHERE sweep_id = ?
        """, (processed, risk_changes, new_alerts, status, sweep_id))
        return cursor.rowcount > 0


def complete_sweep(sweep_id: str) -> bool:
    """Mark sweep as completed. Returns True if successful."""
    with get_conn() as conn:
        cursor = conn.execute("""
            UPDATE monitor_schedules SET status = 'completed', completed_at = datetime('now')
            WHERE sweep_id = ?
        """, (sweep_id,))
        return cursor.rowcount > 0


def get_sweep(sweep_id: str) -> dict | None:
    """Get a monitoring sweep by ID."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM monitor_schedules WHERE sweep_id = ?", (sweep_id,)).fetchone()
        return dict(row) if row else None


def get_latest_sweep() -> dict | None:
    """Get the most recent monitoring sweep."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT * FROM monitor_schedules
            ORDER BY created_at DESC LIMIT 1
        """).fetchone()
        return dict(row) if row else None


def get_monitor_config(key: str, default: str = "") -> str:
    """Get monitoring configuration value."""
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM monitor_config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


# ---- Neo4j sync jobs ----

def create_neo4j_sync_job(
    job_id: str,
    *,
    sync_kind: str = "full",
    since_timestamp: str = "",
    requested_by: str = "",
    requested_by_email: str = "",
    metadata: dict | None = None,
    status: str = "queued",
) -> str:
    """Create a durable Neo4j sync job record."""
    started_at = "datetime('now')" if status == "running" else "NULL"
    with get_conn() as conn:
        conn.execute(
            f"""
            INSERT INTO neo4j_sync_jobs (
                job_id,
                sync_kind,
                status,
                since_timestamp,
                requested_by,
                requested_by_email,
                metadata,
                started_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, {started_at})
            """,
            (
                job_id,
                sync_kind,
                status,
                since_timestamp or None,
                requested_by or "",
                requested_by_email or "",
                json.dumps(metadata or {}),
            ),
        )
    return job_id


def start_neo4j_sync_job(job_id: str) -> bool:
    """Mark a Neo4j sync job as running."""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE neo4j_sync_jobs
            SET status = 'running',
                started_at = COALESCE(started_at, datetime('now')),
                error = NULL
            WHERE job_id = ?
            """,
            (job_id,),
        )
        return cursor.rowcount > 0


def complete_neo4j_sync_job(
    job_id: str,
    *,
    entities_synced: int,
    relationships_synced: int,
    duration_ms: float,
    metadata: dict | None = None,
) -> bool:
    """Mark a Neo4j sync job as completed."""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE neo4j_sync_jobs
            SET status = 'completed',
                entities_synced = ?,
                relationships_synced = ?,
                duration_ms = ?,
                metadata = ?,
                completed_at = datetime('now')
            WHERE job_id = ?
            """,
            (
                int(entities_synced or 0),
                int(relationships_synced or 0),
                float(duration_ms or 0),
                json.dumps(metadata or {}),
                job_id,
            ),
        )
        return cursor.rowcount > 0


def fail_neo4j_sync_job(
    job_id: str,
    *,
    error: str,
    duration_ms: float = 0,
    metadata: dict | None = None,
) -> bool:
    """Mark a Neo4j sync job as failed."""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE neo4j_sync_jobs
            SET status = 'failed',
                duration_ms = ?,
                error = ?,
                metadata = ?,
                completed_at = datetime('now')
            WHERE job_id = ?
            """,
            (
                float(duration_ms or 0),
                error,
                json.dumps(metadata or {}),
                job_id,
            ),
        )
        return cursor.rowcount > 0


def get_neo4j_sync_job(job_id: str) -> dict | None:
    """Fetch a Neo4j sync job by ID."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM neo4j_sync_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["metadata"] = _safe_json_loads(result.get("metadata")) or {}
        return result


def get_latest_neo4j_sync_job() -> dict | None:
    """Fetch the most recent Neo4j sync job."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM neo4j_sync_jobs
            ORDER BY created_at DESC, job_id DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["metadata"] = _safe_json_loads(result.get("metadata")) or {}
        return result


def get_active_neo4j_sync_job() -> dict | None:
    """Fetch the newest queued or running Neo4j sync job."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM neo4j_sync_jobs
            WHERE status IN ('queued', 'running')
            ORDER BY created_at DESC, job_id DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["metadata"] = _safe_json_loads(result.get("metadata")) or {}
        return result


def set_monitor_config(key: str, value: str) -> None:
    """Set monitoring configuration value."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO monitor_config (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')
        """, (key, value))


# ---- Graph Workspace CRUD ----

def create_workspace(workspace_id: str, name: str, created_by: str, description: str = "",
                     pinned_nodes: list | None = None, annotations: dict | None = None,
                     filter_state: dict | None = None, layout_mode: str = "cose",
                     viewport: dict | None = None, node_positions: dict | None = None) -> dict:
    """Create a new graph workspace. Returns the workspace dict."""
    pinned_nodes_json = json.dumps(pinned_nodes or [])
    annotations_json = json.dumps(annotations or {})
    filter_state_json = json.dumps(filter_state or {})
    viewport_json = json.dumps(viewport or {})
    node_positions_json = json.dumps(node_positions or {})

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO graph_workspaces
            (id, name, description, created_by, pinned_nodes, annotations, filter_state, layout_mode, viewport, node_positions)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (workspace_id, name, description, created_by, pinned_nodes_json, annotations_json,
              filter_state_json, layout_mode, viewport_json, node_positions_json))

    return get_workspace(workspace_id)


def get_workspace(workspace_id: str) -> dict | None:
    """Get a workspace by ID."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM graph_workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if not row:
            return None
        ws = dict(row)
        # Parse JSON fields
        ws["pinned_nodes"] = _safe_json_loads(ws["pinned_nodes"])
        ws["annotations"] = _safe_json_loads(ws["annotations"])
        ws["filter_state"] = _safe_json_loads(ws["filter_state"])
        ws["viewport"] = _safe_json_loads(ws["viewport"])
        ws["node_positions"] = _safe_json_loads(ws["node_positions"])
        return ws


def list_workspaces(created_by: str | None = None) -> list[dict]:
    """List all workspaces, optionally filtered by creator."""
    with get_conn() as conn:
        if created_by:
            rows = conn.execute(
                "SELECT * FROM graph_workspaces WHERE created_by = ? ORDER BY updated_at DESC",
                (created_by,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM graph_workspaces ORDER BY updated_at DESC"
            ).fetchall()

        workspaces = []
        for row in rows:
            ws = dict(row)
            ws["pinned_nodes"] = _safe_json_loads(ws["pinned_nodes"])
            ws["annotations"] = _safe_json_loads(ws["annotations"])
            ws["filter_state"] = _safe_json_loads(ws["filter_state"])
            ws["viewport"] = _safe_json_loads(ws["viewport"])
            ws["node_positions"] = _safe_json_loads(ws["node_positions"])
            workspaces.append(ws)
        return workspaces


def update_workspace(workspace_id: str, **updates) -> dict | None:
    """Update a workspace with provided fields. Returns updated workspace."""
    allowed_fields = {
        "name", "description", "pinned_nodes", "annotations", "filter_state",
        "layout_mode", "viewport", "node_positions"
    }

    # Filter to allowed fields
    updates = {k: v for k, v in updates.items() if k in allowed_fields}
    if not updates:
        return get_workspace(workspace_id)

    # Convert JSON fields
    json_fields = {"pinned_nodes", "annotations", "filter_state", "viewport", "node_positions"}
    for field in json_fields:
        if field in updates and updates[field] is not None:
            updates[field] = json.dumps(updates[field])

    # Build update query
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    set_clause += ", updated_at = datetime('now')"
    values = list(updates.values()) + [workspace_id]

    with get_conn() as conn:
        conn.execute(
            f"UPDATE graph_workspaces SET {set_clause} WHERE id = ?",
            values
        )

    return get_workspace(workspace_id)


def delete_workspace(workspace_id: str) -> bool:
    """Delete a workspace by ID. Returns True if deleted."""
    with get_conn() as conn:
        cursor = conn.execute("DELETE FROM graph_workspaces WHERE id = ?", (workspace_id,))
        return cursor.rowcount > 0
