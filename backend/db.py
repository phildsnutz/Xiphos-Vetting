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
from runtime_paths import get_main_db_path, get_secure_artifacts_dir


def _safe_json_loads(value):
    """Parse JSON string, or return value as-is if already a dict/list (PostgreSQL JSONB)."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)
from event_extraction import compute_report_hash

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
    result["enriched_at"] = row["enriched_at"]
    result["report_hash"] = row["report_hash"] or result.get("report_hash") or compute_report_hash(result)
    return result

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
                previous_risk TEXT,
                current_risk TEXT,
                risk_changed BOOLEAN NOT NULL DEFAULT 0,
                new_findings_count INTEGER DEFAULT 0,
                resolved_findings_count INTEGER DEFAULT 0,
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
        """)

        for statement in (
            "ALTER TABLE enrichment_reports ADD COLUMN report_hash TEXT",
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
    """Fetch vendors with their latest scores in a single query (avoids N+1)."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT v.id, v.name, v.country, v.program, v.profile, v.vendor_input,
                   v.created_at, sr.full_result, sr.scored_at
            FROM vendors v
            LEFT JOIN scoring_results sr ON sr.vendor_id = v.id
                AND sr.id = (
                    SELECT id FROM scoring_results
                    WHERE vendor_id = v.id
                    ORDER BY scored_at DESC, id DESC
                    LIMIT 1
                )
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


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


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
        cursor = conn.execute(
            """
            INSERT INTO beta_feedback
                (user_id, user_email, user_role, case_id, workflow_lane, screen,
                 category, severity, summary, details, status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
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
            ),
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
        cursor = conn.execute(
            """
            INSERT INTO beta_events
                (user_id, user_email, user_role, case_id, workflow_lane, screen, event_name, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id or None,
                user_email or None,
                user_role or None,
                case_id,
                workflow_lane,
                screen,
                event_name,
                json.dumps(metadata or {}),
            ),
        )
        return cursor.lastrowid


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
                        resolved_findings_count: int = 0) -> int:
    """Save a monitoring check result. Returns the row ID."""
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO monitoring_log
                (vendor_id, previous_risk, current_risk, risk_changed,
                 new_findings_count, resolved_findings_count)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (vendor_id, previous_risk, current_risk, risk_changed,
              new_findings_count, resolved_findings_count))
        return cursor.lastrowid


def get_monitoring_history(vendor_id: str, limit: int = 20) -> list[dict]:
    """Get monitoring check history for a vendor."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT vendor_id, previous_risk, current_risk, risk_changed,
                   new_findings_count, resolved_findings_count, checked_at
            FROM monitoring_log WHERE vendor_id = ?
            ORDER BY checked_at DESC LIMIT ?
        """, (vendor_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_recent_risk_changes(limit: int = 20) -> list[dict]:
    """Get recent vendors where risk tier changed during monitoring."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT vendor_id, previous_risk, current_risk, checked_at
            FROM monitoring_log WHERE risk_changed = 1
            ORDER BY checked_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


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
        vendor_count = conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
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
