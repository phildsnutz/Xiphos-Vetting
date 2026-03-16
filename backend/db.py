"""
SQLite persistence layer for Xiphos v2.0.

Stores vendors, scoring results, alerts, and screening history.
Survives server restarts. Auto-creates schema on first run.
"""

import sqlite3
import json
import os
from datetime import datetime
from contextlib import contextmanager

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "xiphos.db")


def get_db_path() -> str:
    return os.environ.get("XIPHOS_DB_PATH", DEFAULT_DB_PATH)


@contextmanager
def get_conn():
    """Context manager for database connections with WAL mode."""
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


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS vendors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                country TEXT NOT NULL,
                program TEXT NOT NULL DEFAULT 'standard_industrial',
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
        """)


# ---- Vendor CRUD ----

def upsert_vendor(vendor_id: str, name: str, country: str, program: str,
                  vendor_input: dict) -> str:
    """Insert or update a vendor. Returns the vendor ID."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO vendors (id, name, country, program, vendor_input, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                country=excluded.country,
                program=excluded.program,
                vendor_input=excluded.vendor_input,
                updated_at=datetime('now')
        """, (vendor_id, name, country, program, json.dumps(vendor_input)))
    return vendor_id


def get_vendor(vendor_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"], "name": row["name"], "country": row["country"],
            "program": row["program"], "vendor_input": json.loads(row["vendor_input"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }


def list_vendors(limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM vendors ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            {"id": r["id"], "name": r["name"], "country": r["country"],
             "program": r["program"], "vendor_input": json.loads(r["vendor_input"]),
             "created_at": r["created_at"]}
            for r in rows
        ]


def delete_vendor(vendor_id: str) -> bool:
    with get_conn() as conn:
        cursor = conn.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))
        return cursor.rowcount > 0


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
            WHERE vendor_id = ? ORDER BY scored_at DESC LIMIT 1
        """, (vendor_id,)).fetchone()
        if not row:
            return None
        result = json.loads(row["full_result"])
        result["scored_at"] = row["scored_at"]
        return result


def get_score_history(vendor_id: str, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT calibrated_probability, calibrated_tier, composite_score, scored_at
            FROM scoring_results WHERE vendor_id = ?
            ORDER BY scored_at DESC LIMIT ?
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
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO enrichment_reports
                (vendor_id, overall_risk, findings_total, critical_count, high_count,
                 identifiers, connectors_run, total_elapsed_ms, full_report)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            vendor_id,
            report.get("overall_risk", "UNKNOWN"),
            summary.get("findings_total", 0),
            summary.get("critical", 0),
            summary.get("high", 0),
            json.dumps(report.get("identifiers", {})),
            summary.get("connectors_run", 0),
            report.get("total_elapsed_ms", 0),
            json.dumps(report),
        ))
        return cursor.lastrowid


def get_latest_enrichment(vendor_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT full_report, enriched_at FROM enrichment_reports
            WHERE vendor_id = ? ORDER BY enriched_at DESC LIMIT 1
        """, (vendor_id,)).fetchone()
        if not row:
            return None
        result = json.loads(row["full_report"])
        result["enriched_at"] = row["enriched_at"]
        return result


def get_enrichment_history(vendor_id: str, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT overall_risk, findings_total, critical_count, high_count,
                   connectors_run, total_elapsed_ms, enriched_at
            FROM enrichment_reports WHERE vendor_id = ?
            ORDER BY enriched_at DESC LIMIT ?
        """, (vendor_id, limit)).fetchall()
        return [dict(r) for r in rows]


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
