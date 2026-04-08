"""
PostgreSQL persistence layer for Xiphos v2.0 with transparent SQLite compatibility.

Provides get_conn() and init_db() with identical interface to db.py's SQLite
versions. Translates SQLite parameter style (?) to PostgreSQL (%s) and sqlite3.Row
to RealDictCursor (dict-like objects).

Requires:
    - psycopg2
    - Environment variable XIPHOS_PG_URL (format: postgresql://user:pass@host:port/dbname)
"""

import os
import logging
from contextlib import contextmanager
from typing import Optional
import psycopg2
from psycopg2 import pool, extras

logger = logging.getLogger(__name__)

# Global connection pool (lazy initialized)
_pool: Optional[pool.ThreadedConnectionPool] = None


KG_PROVENANCE_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS kg_entities (
        id TEXT PRIMARY KEY,
        canonical_name TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        aliases JSONB NOT NULL DEFAULT '[]',
        identifiers JSONB NOT NULL DEFAULT '{}',
        country TEXT,
        sources JSONB NOT NULL DEFAULT '[]',
        confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        risk_level TEXT NOT NULL DEFAULT 'unknown',
        sanctions_exposure DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        last_updated TIMESTAMP NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS kg_relationships (
        id SERIAL PRIMARY KEY,
        source_entity_id TEXT NOT NULL,
        target_entity_id TEXT NOT NULL,
        rel_type TEXT NOT NULL,
        confidence DOUBLE PRECISION NOT NULL DEFAULT 0.7,
        data_source TEXT,
        evidence TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        FOREIGN KEY (source_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
        FOREIGN KEY (target_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS kg_entity_vendors (
        entity_id TEXT NOT NULL,
        vendor_id TEXT NOT NULL,
        linked_at TIMESTAMP NOT NULL DEFAULT NOW(),
        PRIMARY KEY (entity_id, vendor_id),
        FOREIGN KEY (entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS kg_asserting_agents (
        id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        agent_type TEXT NOT NULL DEFAULT 'system',
        metadata JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS kg_source_activities (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        activity_type TEXT NOT NULL DEFAULT 'observation',
        occurred_at TIMESTAMP,
        metadata JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS kg_claims (
        id TEXT PRIMARY KEY,
        claim_key TEXT NOT NULL UNIQUE,
        source_entity_id TEXT NOT NULL,
        target_entity_id TEXT,
        rel_type TEXT NOT NULL,
        claim_type TEXT NOT NULL DEFAULT 'relationship',
        claim_value TEXT,
        confidence DOUBLE PRECISION NOT NULL DEFAULT 0.7,
        contradiction_state TEXT NOT NULL DEFAULT 'unreviewed',
        validity_start TIMESTAMP,
        validity_end TIMESTAMP,
        observed_at TIMESTAMP,
        first_observed_at TIMESTAMP NOT NULL DEFAULT NOW(),
        last_observed_at TIMESTAMP NOT NULL DEFAULT NOW(),
        data_source TEXT,
        vendor_id TEXT,
        source_activity_id TEXT,
        asserting_agent_id TEXT,
        structured_fields JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        FOREIGN KEY (source_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
        FOREIGN KEY (target_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
        FOREIGN KEY (source_activity_id) REFERENCES kg_source_activities(id) ON DELETE SET NULL,
        FOREIGN KEY (asserting_agent_id) REFERENCES kg_asserting_agents(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS kg_evidence (
        id TEXT PRIMARY KEY,
        claim_id TEXT NOT NULL,
        source TEXT,
        title TEXT,
        url TEXT,
        artifact_ref TEXT,
        snippet TEXT,
        raw_data JSONB NOT NULL DEFAULT '{}',
        structured_fields JSONB NOT NULL DEFAULT '{}',
        source_class TEXT,
        authority_level TEXT,
        access_model TEXT,
        observed_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        FOREIGN KEY (claim_id) REFERENCES kg_claims(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS kg_graph_staging (
        id TEXT PRIMARY KEY,
        proposal_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'staged',
        entity_id TEXT,
        source_entity_id TEXT,
        target_entity_id TEXT,
        relationship_id TEXT,
        rel_type TEXT,
        annotation_type TEXT,
        flag_type TEXT,
        severity TEXT,
        proposed_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        source_tier TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL DEFAULT '',
        reasoning TEXT NOT NULL DEFAULT '',
        evidence JSONB NOT NULL DEFAULT '[]',
        supporting_claim_ids JSONB NOT NULL DEFAULT '[]',
        structured_fields JSONB NOT NULL DEFAULT '{}',
        vendor_id TEXT,
        proposed_by_agent_id TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        reviewed_at TIMESTAMP,
        reviewed_by TEXT,
        review_outcome TEXT,
        review_notes TEXT,
        FOREIGN KEY (entity_id) REFERENCES kg_entities(id) ON DELETE SET NULL,
        FOREIGN KEY (source_entity_id) REFERENCES kg_entities(id) ON DELETE SET NULL,
        FOREIGN KEY (target_entity_id) REFERENCES kg_entities(id) ON DELETE SET NULL,
        FOREIGN KEY (proposed_by_agent_id) REFERENCES kg_asserting_agents(id) ON DELETE SET NULL
    );

    CREATE INDEX IF NOT EXISTS idx_kg_entities_name ON kg_entities(canonical_name);
    CREATE INDEX IF NOT EXISTS idx_kg_entities_type ON kg_entities(entity_type);
    CREATE INDEX IF NOT EXISTS idx_kg_entities_country ON kg_entities(country);
    CREATE INDEX IF NOT EXISTS idx_kg_relationships_source ON kg_relationships(source_entity_id);
    CREATE INDEX IF NOT EXISTS idx_kg_relationships_target ON kg_relationships(target_entity_id);
    CREATE INDEX IF NOT EXISTS idx_kg_relationships_type ON kg_relationships(rel_type);
    CREATE INDEX IF NOT EXISTS idx_kg_entity_vendors_vendor ON kg_entity_vendors(vendor_id);
    CREATE INDEX IF NOT EXISTS idx_kg_claims_source ON kg_claims(source_entity_id);
    CREATE INDEX IF NOT EXISTS idx_kg_claims_target ON kg_claims(target_entity_id);
    CREATE INDEX IF NOT EXISTS idx_kg_claims_rel_type ON kg_claims(rel_type);
    CREATE INDEX IF NOT EXISTS idx_kg_claims_vendor ON kg_claims(vendor_id);
    CREATE INDEX IF NOT EXISTS idx_kg_evidence_claim ON kg_evidence(claim_id);
    CREATE INDEX IF NOT EXISTS idx_kg_graph_staging_status ON kg_graph_staging(status);
    CREATE INDEX IF NOT EXISTS idx_kg_graph_staging_type ON kg_graph_staging(proposal_type);
    CREATE INDEX IF NOT EXISTS idx_kg_graph_staging_vendor ON kg_graph_staging(vendor_id);
    CREATE INDEX IF NOT EXISTS idx_kg_graph_staging_entity ON kg_graph_staging(entity_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_relationships_unique
        ON kg_relationships(
            source_entity_id,
            target_entity_id,
            rel_type,
            COALESCE(data_source, ''),
            COALESCE(evidence, '')
        );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_evidence_unique
        ON kg_evidence(
            claim_id,
            COALESCE(url, ''),
            COALESCE(artifact_ref, ''),
            COALESCE(snippet, '')
        );
"""


def _get_pool() -> pool.ThreadedConnectionPool:
    """Lazy-initialize and return the connection pool."""
    global _pool
    if _pool is not None:
        return _pool

    pg_url = os.environ.get("XIPHOS_PG_URL")
    if not pg_url:
        raise ValueError(
            "XIPHOS_PG_URL environment variable not set. "
            "Format: postgresql://user:pass@host:port/dbname"
        )

    try:
        _pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=pg_url,
            connect_timeout=5
        )
        logger.info("PostgreSQL connection pool initialized")
    except psycopg2.OperationalError as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        raise

    return _pool


def shutdown_pool():
    """Close all connections in the pool. Call on application shutdown."""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL connection pool closed")


class RowProxy(dict):
    """Dict subclass that also supports integer-indexed access like sqlite3.Row.

    This allows both `row["col"]` and `row[0]` to work transparently.
    """

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

    def keys(self):
        return super().keys()


class PgCursorWrapper:
    """Wraps psycopg2 RealDictCursor to match sqlite3.Row behavior."""

    def __init__(self, cursor: extras.RealDictCursor):
        self._cursor = cursor

    def fetchone(self) -> Optional[RowProxy]:
        """Fetch one row as a RowProxy (supports both dict and int access)."""
        row = self._cursor.fetchone()
        return RowProxy(row) if row else None

    def fetchall(self) -> list[RowProxy]:
        """Fetch all rows as list of RowProxy objects."""
        return [RowProxy(row) for row in self._cursor.fetchall()]

    @property
    def lastrowid(self) -> Optional[int]:
        """Return last inserted row ID."""
        return getattr(self._cursor, 'lastrowid', None)

    @property
    def rowcount(self) -> int:
        """Return number of rows affected."""
        return self._cursor.rowcount

    def __iter__(self):
        """Support iteration over cursor."""
        for row in self._cursor:
            yield RowProxy(row)


class PgDirectCursor:
    """Cursor wrapper that translates SQL and returns RowProxy dicts.
    Used when code calls conn.cursor() directly instead of conn.execute()."""

    def __init__(self, pg_conn, translate_fn):
        self._cursor = pg_conn.cursor(cursor_factory=extras.RealDictCursor)
        self._translate = translate_fn

    def execute(self, sql: str, params=None):
        translated = self._translate(sql)
        self._cursor.execute(translated, params)
        return self

    def executemany(self, sql: str, params_list):
        translated = self._translate(sql)
        for params in params_list:
            self._cursor.execute(translated, params)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        return RowProxy(row) if row else None

    def fetchall(self):
        return [RowProxy(r) for r in self._cursor.fetchall()]

    def fetchmany(self, size=100):
        return [RowProxy(r) for r in self._cursor.fetchmany(size)]

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return getattr(self._cursor, 'lastrowid', None)

    def close(self):
        self._cursor.close()

    def __iter__(self):
        for row in self._cursor:
            yield RowProxy(row)


class PgConnectionWrapper:
    """Wraps psycopg2 connection to match sqlite3.Connection interface."""

    def __init__(self, pg_conn):
        self._conn = pg_conn
        self._cursor = None

    def cursor(self):
        """Return a cursor-like object for direct cursor usage patterns.
        The returned object wraps psycopg2 cursor with SQL translation."""
        return PgDirectCursor(self._conn, self._translate_sql)

    def execute(self, sql: str, params: tuple = None) -> PgCursorWrapper:
        """
        Execute SQL with SQLite parameter style (?) translation.

        Args:
            sql: SQL statement with ? placeholders
            params: Parameters to bind

        Returns:
            PgCursorWrapper for fetching results
        """
        # Translate SQLite ? style to PostgreSQL %s style
        translated_sql = self._translate_sql(sql)

        try:
            cursor = self._conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute(translated_sql, params or ())
            return PgCursorWrapper(cursor)
        except psycopg2.Error as e:
            logger.error(f"Execute failed: {e}\nSQL: {translated_sql}\nParams: {params}")
            raise

    def executemany(self, sql: str, param_list) -> None:
        """
        Execute the same SQL with multiple parameter sets (SQLite compatibility).

        Args:
            sql: SQL with placeholders
            param_list: Iterable of parameter tuples
        """
        translated_sql = self._translate_sql(sql)
        try:
            cursor = self._conn.cursor()
            for params in param_list:
                cursor.execute(translated_sql, params)
            self._cursor = PgCursorWrapper(cursor)
        except psycopg2.Error as e:
            logger.error(f"Executemany failed: {e}\nSQL: {translated_sql}")
            raise

    def executescript(self, sql: str) -> None:
        """
        Execute multiple SQL statements (SQLite compatibility).

        Splits by `;` and executes each non-empty statement.

        Args:
            sql: SQL script with multiple statements separated by ;
        """
        statements = [s.strip() for s in sql.split(";")]

        try:
            cursor = self._conn.cursor()
            for stmt in statements:
                if stmt:
                    translated = self._translate_sql(stmt)
                    cursor.execute(translated)
            cursor.close()
        except psycopg2.Error as e:
            logger.error(f"Executescript failed: {e}")
            raise

    def commit(self) -> None:
        """Commit the current transaction."""
        self._conn.commit()
        logger.debug("Transaction committed")

    def rollback(self) -> None:
        """Rollback the current transaction."""
        self._conn.rollback()
        logger.debug("Transaction rolled back")

    def close(self) -> None:
        """Mark connection for return to pool (do not close underlying pg connection)."""
        if self._cursor:
            self._cursor.close()
        # NOTE: Do NOT call self._conn.close() here. The pool's putconn()
        # handles returning the connection. Closing it would destroy a pooled conn.
        logger.debug("Connection released")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()

    @staticmethod
    def _translate_sql(sql: str) -> str:
        """
        Translate SQLite SQL to PostgreSQL.

        - Replace ? with %s
        - Replace datetime('now') with NOW()
        - Replace AUTOINCREMENT (remove it, PostgreSQL uses SERIAL)
        - Replace boolean = 0/1 with = FALSE/TRUE
        - Replace SET col = 1/0 for boolean columns with TRUE/FALSE
        """
        import re

        # Replace SQLite named params :name with PostgreSQL %(name)s
        # Negative lookbehind avoids matching PostgreSQL :: cast syntax
        translated = re.sub(r'(?<!:):(\w+)', r'%(\1)s', sql)

        uses_insert_or_ignore = bool(re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", translated, flags=re.IGNORECASE))
        if uses_insert_or_ignore:
            translated = re.sub(
                r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
                "INSERT INTO",
                translated,
                flags=re.IGNORECASE,
            )

        # Replace ? with %s (positional params)
        translated = translated.replace("?", "%s")

        # Replace datetime('now') with NOW()
        translated = translated.replace("datetime('now')", "NOW()")

        # Remove AUTOINCREMENT (PostgreSQL uses SERIAL)
        translated = translated.replace(" AUTOINCREMENT", "")

        # Boolean column comparisons: col = 0 -> col = FALSE, col = 1 -> col = TRUE
        # Match known boolean columns followed by = 0 or = 1
        bool_cols = (
            r'resolved', r'is_hard_stop', r'matched', r'risk_changed',
            r'graph_elevated', r'state_owned', r'publicly_traded',
            r'beneficial_owner_known', r'pep_connection',
            r'has_lei', r'has_cage', r'has_duns', r'has_tax_id',
            r'has_audited_financials',
        )
        for col in bool_cols:
            translated = re.sub(
                rf'({col}\s*=\s*)0\b', r'\g<1>FALSE', translated
            )
            translated = re.sub(
                rf'({col}\s*=\s*)1\b', r'\g<1>TRUE', translated
            )

        # Also handle DEFAULT 0 -> DEFAULT FALSE for boolean columns in DDL
        translated = translated.replace("BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE")
        translated = translated.replace("BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE")
        translated = translated.replace("BOOLEAN NOT NULL DEFAULT 1", "BOOLEAN NOT NULL DEFAULT TRUE")
        translated = translated.replace("BOOLEAN DEFAULT 1", "BOOLEAN DEFAULT TRUE")

        if uses_insert_or_ignore and "ON CONFLICT" not in translated.upper():
            translated = translated.rstrip().rstrip(";")
            translated = f"{translated} ON CONFLICT DO NOTHING"

        return translated


@contextmanager
def get_conn() -> PgConnectionWrapper:
    """
    Context manager for PostgreSQL connections with transaction handling.

    Usage:
        with get_conn() as conn:
            conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,))

    Yields:
        PgConnectionWrapper with sqlite3-compatible interface

    Commits on successful exit, rolls back on exception, closes finally.
    """
    pg_pool = _get_pool()
    pg_conn = pg_pool.getconn()
    wrapper = PgConnectionWrapper(pg_conn)

    try:
        yield wrapper
        wrapper.commit()
    except Exception as e:
        wrapper.rollback()
        logger.error(f"Connection error: {e}")
        raise
    finally:
        pg_pool.putconn(pg_conn)


def init_db():
    """
    Create all tables with PostgreSQL DDL if they don't exist.

    Converts from SQLite schema in db.py:
    - INTEGER PRIMARY KEY AUTOINCREMENT -> SERIAL PRIMARY KEY
    - TEXT PRIMARY KEY -> TEXT PRIMARY KEY
    - BOOLEAN DEFAULT 0 -> BOOLEAN DEFAULT FALSE
    - datetime('now') -> NOW()
    - JSON -> JSONB
    - REAL -> DOUBLE PRECISION
    """
    with get_conn() as conn:
        # Main xiphos tables
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS vendors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                country TEXT NOT NULL,
                program TEXT NOT NULL DEFAULT 'standard_industrial',
                profile TEXT NOT NULL DEFAULT 'defense_acquisition',
                vendor_input JSONB NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS scoring_results (
                id SERIAL PRIMARY KEY,
                vendor_id TEXT NOT NULL REFERENCES vendors(id),
                calibrated_probability DOUBLE PRECISION NOT NULL,
                calibrated_tier TEXT NOT NULL,
                composite_score INTEGER NOT NULL,
                is_hard_stop BOOLEAN NOT NULL DEFAULT FALSE,
                interval_lower DOUBLE PRECISION,
                interval_upper DOUBLE PRECISION,
                interval_coverage DOUBLE PRECISION,
                full_result JSONB NOT NULL,
                scored_at TIMESTAMP NOT NULL DEFAULT NOW(),
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id SERIAL PRIMARY KEY,
                vendor_id TEXT NOT NULL REFERENCES vendors(id),
                entity_name TEXT NOT NULL,
                severity TEXT NOT NULL CHECK(severity IN ('critical', 'high', 'medium', 'low')),
                title TEXT NOT NULL,
                description TEXT,
                resolved BOOLEAN NOT NULL DEFAULT FALSE,
                resolved_by TEXT,
                resolved_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS screening_log (
                id SERIAL PRIMARY KEY,
                query_name TEXT NOT NULL,
                matched BOOLEAN NOT NULL,
                best_score DOUBLE PRECISION,
                matched_name TEXT,
                matched_list TEXT,
                result_json JSONB,
                screened_at TIMESTAMP NOT NULL DEFAULT NOW(),
                screened_by TEXT DEFAULT 'system'
            );

            CREATE INDEX IF NOT EXISTS idx_scoring_vendor ON scoring_results(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_scoring_tier ON scoring_results(calibrated_tier);
            CREATE INDEX IF NOT EXISTS idx_alerts_vendor ON alerts(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
            CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON alerts(resolved);
            CREATE INDEX IF NOT EXISTS idx_screening_date ON screening_log(screened_at);

            CREATE TABLE IF NOT EXISTS enrichment_reports (
                id SERIAL PRIMARY KEY,
                vendor_id TEXT NOT NULL REFERENCES vendors(id),
                overall_risk TEXT NOT NULL,
                findings_total INTEGER NOT NULL DEFAULT 0,
                critical_count INTEGER NOT NULL DEFAULT 0,
                high_count INTEGER NOT NULL DEFAULT 0,
                identifiers JSONB,
                connectors_run INTEGER NOT NULL DEFAULT 0,
                total_elapsed_ms INTEGER NOT NULL DEFAULT 0,
                report_hash TEXT,
                full_report JSONB NOT NULL,
                enriched_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_enrichment_vendor ON enrichment_reports(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_enrichment_risk ON enrichment_reports(overall_risk);
            CREATE INDEX IF NOT EXISTS idx_enrichment_vendor_hash ON enrichment_reports(vendor_id, report_hash);

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
                primary_targets TEXT NOT NULL DEFAULT '{}',
                known_context TEXT NOT NULL DEFAULT '{}',
                priority_requirements TEXT NOT NULL DEFAULT '[]',
                authorized_tiers TEXT NOT NULL DEFAULT '[]',
                summary TEXT,
                notes TEXT NOT NULL DEFAULT '[]',
                created_by TEXT,
                created_by_email TEXT,
                created_by_role TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_mission_briefs_case ON mission_briefs(case_id);
            CREATE INDEX IF NOT EXISTS idx_mission_briefs_room ON mission_briefs(room);
            CREATE INDEX IF NOT EXISTS idx_mission_briefs_updated ON mission_briefs(updated_at);

            CREATE TABLE IF NOT EXISTS monitoring_log (
                id SERIAL PRIMARY KEY,
                vendor_id TEXT NOT NULL REFERENCES vendors(id),
                run_id TEXT,
                previous_risk TEXT,
                current_risk TEXT,
                risk_changed BOOLEAN NOT NULL DEFAULT FALSE,
                change_type TEXT NOT NULL DEFAULT 'no_change',
                status TEXT NOT NULL DEFAULT 'completed',
                score_before DOUBLE PRECISION,
                score_after DOUBLE PRECISION,
                new_findings_count INTEGER DEFAULT 0,
                resolved_findings_count INTEGER DEFAULT 0,
                delta_summary TEXT,
                sources_triggered JSONB,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                checked_at TIMESTAMP NOT NULL DEFAULT NOW(),
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_monitoring_vendor ON monitoring_log(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_monitoring_checked ON monitoring_log(checked_at);
            CREATE INDEX IF NOT EXISTS idx_monitoring_risk_changed ON monitoring_log(risk_changed);

            CREATE TABLE IF NOT EXISTS decisions (
                id SERIAL PRIMARY KEY,
                vendor_id TEXT NOT NULL REFERENCES vendors(id),
                decision TEXT NOT NULL CHECK(decision IN ('approve', 'reject', 'escalate')),
                decided_by TEXT,
                decided_by_email TEXT,
                reason TEXT,
                posterior_at_decision DOUBLE PRECISION,
                tier_at_decision TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
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
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS batch_items (
                id SERIAL PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES batches(id),
                vendor_name TEXT NOT NULL,
                country TEXT NOT NULL,
                case_id TEXT,
                tier TEXT,
                posterior DOUBLE PRECISION,
                findings_count INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_batch_uploaded_by ON batches(uploaded_by);
            CREATE INDEX IF NOT EXISTS idx_batch_status ON batches(status);
            CREATE INDEX IF NOT EXISTS idx_batch_items_batch ON batch_items(batch_id);
            CREATE INDEX IF NOT EXISTS idx_batch_items_status ON batch_items(status);

            CREATE TABLE IF NOT EXISTS monitor_schedules (
                id SERIAL PRIMARY KEY,
                sweep_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                total_vendors INTEGER NOT NULL DEFAULT 0,
                processed INTEGER NOT NULL DEFAULT 0,
                risk_changes INTEGER NOT NULL DEFAULT 0,
                new_alerts INTEGER NOT NULL DEFAULT 0,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS monitor_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_monitor_schedules_status ON monitor_schedules(status);
            CREATE INDEX IF NOT EXISTS idx_monitor_schedules_created ON monitor_schedules(created_at);

            CREATE TABLE IF NOT EXISTS intel_summaries (
                id SERIAL PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES vendors(id),
                created_by TEXT,
                report_hash TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                elapsed_ms INTEGER DEFAULT 0,
                summary JSONB NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
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
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                started_at TIMESTAMP,
                completed_at TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_intel_jobs_case_user_hash ON intel_summary_jobs(case_id, created_by, report_hash);

            CREATE TABLE IF NOT EXISTS case_events (
                id SERIAL PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES vendors(id),
                report_hash TEXT NOT NULL,
                finding_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                date_range JSONB,
                jurisdiction TEXT,
                status TEXT NOT NULL,
                confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                source_refs JSONB,
                source_finding_ids JSONB,
                connector TEXT,
                normalization_method TEXT NOT NULL DEFAULT 'deterministic',
                severity TEXT,
                title TEXT,
                assessment TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
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
                structured_fields JSONB,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_artifact_records_case ON artifact_records(case_id);
            CREATE INDEX IF NOT EXISTS idx_artifact_records_type ON artifact_records(artifact_type);
            CREATE INDEX IF NOT EXISTS idx_artifact_records_created ON artifact_records(created_at);

            CREATE TABLE IF NOT EXISTS beta_feedback (
                id SERIAL PRIMARY KEY,
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
                metadata JSONB,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_beta_feedback_created ON beta_feedback(created_at);
            CREATE INDEX IF NOT EXISTS idx_beta_feedback_status ON beta_feedback(status);
            CREATE INDEX IF NOT EXISTS idx_beta_feedback_lane ON beta_feedback(workflow_lane);

            CREATE TABLE IF NOT EXISTS beta_events (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                user_email TEXT,
                user_role TEXT,
                case_id TEXT REFERENCES vendors(id),
                workflow_lane TEXT NOT NULL DEFAULT '',
                screen TEXT NOT NULL DEFAULT '',
                event_name TEXT NOT NULL,
                metadata JSONB,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_beta_events_created ON beta_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_beta_events_lane ON beta_events(workflow_lane);
            CREATE INDEX IF NOT EXISTS idx_beta_events_name ON beta_events(event_name);

            CREATE TABLE IF NOT EXISTS graph_workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_by TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
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
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS mission_thread_members (
                id SERIAL PRIMARY KEY,
                mission_thread_id TEXT NOT NULL REFERENCES mission_threads(id) ON DELETE CASCADE,
                vendor_id TEXT REFERENCES vendors(id) ON DELETE CASCADE,
                entity_id TEXT,
                role TEXT NOT NULL DEFAULT '',
                criticality TEXT NOT NULL DEFAULT 'supporting',
                subsystem TEXT NOT NULL DEFAULT '',
                site TEXT NOT NULL DEFAULT '',
                is_alternate BOOLEAN NOT NULL DEFAULT FALSE,
                notes TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS mission_thread_roles (
                id SERIAL PRIMARY KEY,
                mission_thread_id TEXT NOT NULL REFERENCES mission_threads(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (mission_thread_id, role)
            );

            CREATE TABLE IF NOT EXISTS mission_thread_notes (
                id SERIAL PRIMARY KEY,
                mission_thread_id TEXT NOT NULL REFERENCES mission_threads(id) ON DELETE CASCADE,
                note_type TEXT NOT NULL DEFAULT 'general',
                body TEXT NOT NULL,
                created_by TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_mission_threads_created_by ON mission_threads(created_by);
            CREATE INDEX IF NOT EXISTS idx_mission_threads_updated_at ON mission_threads(updated_at);
            CREATE INDEX IF NOT EXISTS idx_mission_thread_members_thread ON mission_thread_members(mission_thread_id);
            CREATE INDEX IF NOT EXISTS idx_mission_thread_members_vendor ON mission_thread_members(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_mission_thread_members_entity ON mission_thread_members(entity_id);
            CREATE INDEX IF NOT EXISTS idx_mission_thread_notes_thread ON mission_thread_notes(mission_thread_id);

            CREATE TABLE IF NOT EXISTS assistant_runs (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
                workflow_lane TEXT NOT NULL DEFAULT '',
                objective TEXT NOT NULL DEFAULT '',
                playbook_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'planned',
                analyst_prompt TEXT NOT NULL DEFAULT '',
                plan_payload JSONB,
                execution_payload JSONB,
                last_error TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_by_email TEXT NOT NULL DEFAULT '',
                created_by_role TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
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
                duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
                error TEXT,
                metadata JSONB,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                started_at TIMESTAMP,
                completed_at TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_neo4j_sync_jobs_status ON neo4j_sync_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_neo4j_sync_jobs_created ON neo4j_sync_jobs(created_at);
        """)
        for statement in (
            "ALTER TABLE enrichment_reports ADD COLUMN IF NOT EXISTS report_hash TEXT",
            "ALTER TABLE monitoring_log ADD COLUMN IF NOT EXISTS run_id TEXT",
            "ALTER TABLE monitoring_log ADD COLUMN IF NOT EXISTS change_type TEXT NOT NULL DEFAULT 'no_change'",
            "ALTER TABLE monitoring_log ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed'",
            "ALTER TABLE monitoring_log ADD COLUMN IF NOT EXISTS score_before DOUBLE PRECISION",
            "ALTER TABLE monitoring_log ADD COLUMN IF NOT EXISTS score_after DOUBLE PRECISION",
            "ALTER TABLE monitoring_log ADD COLUMN IF NOT EXISTS delta_summary TEXT",
            "ALTER TABLE monitoring_log ADD COLUMN IF NOT EXISTS sources_triggered JSONB",
            "ALTER TABLE monitoring_log ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
            "ALTER TABLE monitoring_log ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
        ):
            try:
                conn.execute(statement)
            except Exception:
                logger.debug("PostgreSQL migration skipped for statement: %s", statement)

        # Transaction authorization tables
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS transaction_authorizations (
                id TEXT PRIMARY KEY,
                case_id TEXT,
                transaction_type TEXT NOT NULL,
                classification TEXT,
                destination_country TEXT,
                destination_company TEXT,
                end_user TEXT,
                combined_posture TEXT NOT NULL,
                combined_posture_label TEXT,
                confidence DOUBLE PRECISION,
                rules_posture TEXT,
                rules_confidence DOUBLE PRECISION,
                graph_posture TEXT,
                graph_elevated BOOLEAN DEFAULT FALSE,
                persons_screened INTEGER DEFAULT 0,
                person_summary JSONB,
                license_exception JSONB,
                escalation_reasons JSONB,
                blocking_factors JSONB,
                all_factors JSONB,
                recommended_next_step TEXT,
                rules_guidance JSONB,
                graph_intelligence JSONB,
                person_results JSONB,
                pipeline_log JSONB,
                requested_by TEXT,
                duration_ms DOUBLE PRECISION,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS authorization_audit (
                id TEXT PRIMARY KEY,
                case_id TEXT,
                timestamp TIMESTAMP NOT NULL,
                request_payload JSONB,
                combined_posture TEXT,
                confidence DOUBLE PRECISION,
                pipeline_log JSONB,
                analyst_email TEXT,
                review_status TEXT DEFAULT 'pending',
                review_notes TEXT,
                reviewed_by TEXT,
                reviewed_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                FOREIGN KEY (case_id) REFERENCES vendors(id) ON DELETE SET NULL
            );
        """)

        # Person screening tables
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS person_screenings (
                id TEXT PRIMARY KEY,
                case_id TEXT,
                person_name TEXT NOT NULL,
                nationalities TEXT DEFAULT '[]',
                employer TEXT,
                screening_status TEXT NOT NULL CHECK(
                    screening_status IN ('CLEAR', 'MATCH', 'PARTIAL_MATCH', 'ESCALATE')
                ),
                matched_lists TEXT DEFAULT '[]',
                composite_score DOUBLE PRECISION NOT NULL,
                deemed_export TEXT,
                recommended_action TEXT NOT NULL,
                screened_by TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_person_case ON person_screenings(case_id);
            CREATE INDEX IF NOT EXISTS idx_person_status ON person_screenings(screening_status);
            CREATE INDEX IF NOT EXISTS idx_person_name ON person_screenings(person_name);
        """)

        # Export templates table
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS export_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_by TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                last_used_at TIMESTAMP,
                template_data TEXT NOT NULL,
                usage_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_export_templates_name ON export_templates(name);
            CREATE INDEX IF NOT EXISTS idx_export_templates_created_by ON export_templates(created_by);
        """)

        # Knowledge graph tables
        conn.executescript(KG_PROVENANCE_SCHEMA_SQL)

        logger.info("PostgreSQL database initialization complete")
