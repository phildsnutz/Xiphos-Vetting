"""
Migrate data from SQLite to PostgreSQL for Xiphos v2.0.

Reads from SQLite databases:
    - Main database: XIPHOS_DB_PATH or var/xiphos.db
    - Knowledge graph: XIPHOS_KG_DB_PATH or var/knowledge_graph.db
    - Sanctions: XIPHOS_SANCTIONS_DB or var/sanctions.db

Writes to PostgreSQL:
    - XIPHOS_PG_URL (format: postgresql://user:pass@host:port/dbname)

Features:
    - Batch inserts (100 rows per batch)
    - JSON column handling (text -> JSONB)
    - Progress reporting per table
    - --dry-run flag for preview
    - --tables flag to migrate specific tables only
    - Total row counts per table
"""

import os
import sys
import json
import sqlite3
import logging
import argparse
from pathlib import Path
from typing import Optional, List

import psycopg2
from psycopg2 import extras

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MigrationConfig:
    """Configuration for migration."""

    def __init__(self):
        # SQLite paths
        self.sqlite_db = os.environ.get(
            "XIPHOS_DB_PATH",
            Path(__file__).resolve().parent.parent / "var" / "xiphos.db"
        )
        self.sqlite_kg_db = os.environ.get(
            "XIPHOS_KG_DB_PATH",
            Path(__file__).resolve().parent.parent / "var" / "knowledge_graph.db"
        )
        self.sqlite_sanctions_db = os.environ.get(
            "XIPHOS_SANCTIONS_DB",
            Path(__file__).resolve().parent.parent / "var" / "sanctions.db"
        )

        # PostgreSQL URL
        self.pg_url = os.environ.get("XIPHOS_PG_URL")
        if not self.pg_url:
            raise ValueError(
                "XIPHOS_PG_URL environment variable not set. "
                "Format: postgresql://user:pass@host:port/dbname"
            )

    def validate_sources(self) -> None:
        """Validate that source databases exist."""
        if not Path(self.sqlite_db).exists():
            logger.warning(f"SQLite DB not found: {self.sqlite_db}")
        if not Path(self.sqlite_kg_db).exists():
            logger.warning(f"Knowledge graph DB not found: {self.sqlite_kg_db}")
        if not Path(self.sqlite_sanctions_db).exists():
            logger.warning(f"Sanctions DB not found: {self.sqlite_sanctions_db}")


class SqliteMigrator:
    """Handles SQLite to PostgreSQL migration."""

    BATCH_SIZE = 100

    # Tables to migrate from main database
    MAIN_DB_TABLES = [
        "vendors",
        "scoring_results",
        "alerts",
        "screening_log",
        "enrichment_reports",
        "monitoring_log",
        "decisions",
        "batches",
        "batch_items",
        "monitor_schedules",
        "monitor_config",
        "intel_summaries",
        "intel_summary_jobs",
        "case_events",
        "artifact_records",
        "beta_feedback",
        "beta_events",
        "graph_workspaces",
        "transaction_authorizations",
        "authorization_audit",
        "person_screenings",
        "export_templates",
    ]

    # Tables to migrate from knowledge graph database
    KG_DB_TABLES = [
        "kg_entities",
        "kg_relationships",
        "kg_entity_vendors",
    ]

    # JSON columns that need special handling
    JSON_COLUMNS = {
        "vendors": ["vendor_input"],
        "scoring_results": ["full_result"],
        "screening_log": ["result_json"],
        "enrichment_reports": ["identifiers", "full_report"],
        "case_events": ["date_range", "source_refs", "source_finding_ids"],
        "artifact_records": ["structured_fields"],
        "beta_feedback": ["metadata"],
        "beta_events": ["metadata"],
        "kg_entities": ["aliases", "identifiers", "sources"],
        "kg_relationships": [],
        "kg_entity_vendors": [],
        "transaction_authorizations": [
            "person_summary", "license_exception", "escalation_reasons",
            "blocking_factors", "all_factors", "rules_guidance",
            "graph_intelligence", "person_results", "pipeline_log"
        ],
        "authorization_audit": ["request_payload", "pipeline_log"],
        "person_screenings": [],
        "export_templates": [],
        "intel_summaries": ["summary"],
        "monitor_config": [],
    }

    def __init__(self, config: MigrationConfig, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.pg_conn: Optional[psycopg2.extensions.connection] = None
        self.stats = {}

    def connect_postgres(self) -> None:
        """Connect to PostgreSQL."""
        try:
            self.pg_conn = psycopg2.connect(self.config.pg_url)
            logger.info("Connected to PostgreSQL")
        except psycopg2.OperationalError as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    def disconnect_postgres(self) -> None:
        """Disconnect from PostgreSQL."""
        if self.pg_conn:
            self.pg_conn.close()
            logger.info("Disconnected from PostgreSQL")

    def _get_table_schema(self, sqlite_conn: sqlite3.Connection, table_name: str) -> dict:
        """Get column names and types from SQLite."""
        cursor = sqlite_conn.execute(f"PRAGMA table_info({table_name})")
        columns = {}
        for row in cursor:
            col_name = row[1]
            col_type = row[2]
            columns[col_name] = col_type
        return columns

    # Boolean columns that are BOOLEAN in PostgreSQL but INTEGER in SQLite
    BOOLEAN_COLUMNS = {
        "resolved", "is_hard_stop", "matched", "risk_changed",
        "graph_elevated", "state_owned", "publicly_traded",
        "beneficial_owner_known", "pep_connection",
        "has_lei", "has_cage", "has_duns", "has_tax_id",
        "has_audited_financials",
    }

    def _get_pg_columns(self, table_name: str) -> set:
        """Get the set of column names that exist in the PostgreSQL table."""
        pg_cursor = self.pg_conn.cursor()
        pg_cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table_name,)
        )
        cols = {row[0] for row in pg_cursor.fetchall()}
        pg_cursor.close()
        return cols

    def _convert_value(self, value: any, col_name: str, table_name: str) -> any:
        """Convert SQLite value to PostgreSQL format."""
        if value is None:
            return None

        # Handle boolean columns (SQLite stores as 0/1, PG needs True/False)
        if col_name in self.BOOLEAN_COLUMNS:
            if isinstance(value, int):
                return bool(value)
            return value

        # Handle JSON columns: wrap with psycopg2.extras.Json for JSONB
        json_cols = self.JSON_COLUMNS.get(table_name, [])
        if col_name in json_cols:
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    return extras.Json(parsed)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Failed to parse JSON in {table_name}.{col_name}: {value[:50]}")
                    return value
            elif isinstance(value, (dict, list)):
                return extras.Json(value)

        # Handle dict/list values in non-declared JSON columns (safety net)
        if isinstance(value, (dict, list)):
            return extras.Json(value)

        return value

    def migrate_table(self, sqlite_conn: sqlite3.Connection, table_name: str) -> int:
        """
        Migrate a single table from SQLite to PostgreSQL.

        Args:
            sqlite_conn: SQLite connection
            table_name: Name of table to migrate

        Returns:
            Number of rows migrated
        """
        # Check if table exists in SQLite
        cursor = sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        if not cursor.fetchone():
            logger.warning(f"Table {table_name} not found in SQLite")
            return 0

        # Get schema
        schema = self._get_table_schema(sqlite_conn, table_name)
        if not schema:
            logger.warning(f"No columns found for table {table_name}")
            return 0

        sqlite_column_names = list(schema.keys())

        # Filter to only columns that exist in PostgreSQL (handles schema drift)
        pg_columns = self._get_pg_columns(table_name)
        if not pg_columns:
            logger.warning(f"Table {table_name} not found in PostgreSQL or has no columns")
            return 0

        column_names = [c for c in sqlite_column_names if c in pg_columns]
        skipped_cols = set(sqlite_column_names) - set(column_names)
        if skipped_cols:
            logger.info(f"  Skipping columns not in PG: {skipped_cols}")

        # Count total rows
        count_cursor = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table_name}")
        total_rows = count_cursor.fetchone()[0]

        if total_rows == 0:
            logger.info(f"{table_name}: 0 rows (skipping)")
            return 0

        logger.info(f"Migrating {table_name}: {total_rows} rows...")

        if self.dry_run:
            logger.info(f"  [DRY-RUN] Would migrate {total_rows} rows")
            return total_rows

        # Fetch and insert in batches (select only the columns we're migrating)
        cursor = sqlite_conn.execute(f"SELECT {','.join(column_names)} FROM {table_name}")
        rows_migrated = 0
        pg_cursor = self.pg_conn.cursor()

        while True:
            rows = cursor.fetchmany(self.BATCH_SIZE)
            if not rows:
                break

            # Convert rows
            converted_rows = []
            for row in rows:
                converted_row = []
                for i, val in enumerate(row):
                    col_name = column_names[i]
                    converted_val = self._convert_value(val, col_name, table_name)
                    converted_row.append(converted_val)
                converted_rows.append(tuple(converted_row))

            # Insert batch with ON CONFLICT DO NOTHING for idempotent re-runs
            try:
                placeholders = ",".join(["%s"] * len(column_names))
                insert_sql = (
                    f"INSERT INTO {table_name} ({','.join(column_names)}) "
                    f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                )
                pg_cursor.executemany(insert_sql, converted_rows)
                rows_migrated += len(converted_rows)
                logger.debug(f"  Inserted {rows_migrated}/{total_rows} rows")
            except psycopg2.Error as e:
                logger.error(f"Error inserting into {table_name}: {e}")
                self.pg_conn.rollback()
                raise

        self.pg_conn.commit()
        pg_cursor.close()
        logger.info(f"{table_name}: {rows_migrated} rows migrated")
        return rows_migrated

    def _fix_sequences(self) -> None:
        """Reset all SERIAL sequences to MAX(id)+1 after migration.

        When SQLite rows are inserted with explicit IDs, the PostgreSQL
        auto-increment sequences remain at their initial value. This causes
        UniqueViolation errors on subsequent INSERTs that rely on nextval().
        """
        if self.dry_run:
            logger.info("  [DRY-RUN] Would reset sequences")
            return

        pg_cursor = self.pg_conn.cursor()
        # Find all serial sequences in the public schema
        pg_cursor.execute("""
            SELECT
                t.relname AS table_name,
                a.attname AS column_name,
                pg_get_serial_sequence(t.relname::text, a.attname::text) AS seq_name
            FROM pg_class t
            JOIN pg_attribute a ON a.attrelid = t.oid
            WHERE t.relnamespace = 'public'::regnamespace
              AND t.relkind = 'r'
              AND pg_get_serial_sequence(t.relname::text, a.attname::text) IS NOT NULL
        """)
        sequences = pg_cursor.fetchall()

        fixed = 0
        for table_name, col_name, seq_name in sequences:
            pg_cursor.execute(
                f"SELECT COALESCE(MAX({col_name}), 0) FROM {table_name}"
            )
            max_val = pg_cursor.fetchone()[0]
            if max_val > 0:
                pg_cursor.execute(f"SELECT setval('{seq_name}', {max_val + 1})")
                new_val = pg_cursor.fetchone()[0]
                logger.info(f"  {seq_name}: reset to {new_val} (max {col_name}={max_val})")
                fixed += 1

        self.pg_conn.commit()
        pg_cursor.close()
        logger.info(f"Reset {fixed} sequences")

    def migrate_database(self, db_path: str, tables: List[str], db_type: str = "main") -> dict:
        """
        Migrate all specified tables from SQLite database.

        Args:
            db_path: Path to SQLite database
            tables: List of table names to migrate
            db_type: Label for database (main, kg, sanctions)

        Returns:
            Dictionary with migration stats
        """
        if not Path(db_path).exists():
            logger.warning(f"Database not found: {db_path}")
            return {}

        logger.info(f"Connecting to {db_type} database: {db_path}")
        sqlite_conn = sqlite3.connect(db_path)
        sqlite_conn.row_factory = sqlite3.Row

        stats = {}
        for table_name in tables:
            try:
                row_count = self.migrate_table(sqlite_conn, table_name)
                stats[table_name] = row_count
            except Exception as e:
                logger.error(f"Failed to migrate {table_name}: {e}")
                stats[table_name] = f"ERROR: {str(e)}"

        sqlite_conn.close()
        return stats

    def run(self, specific_tables: Optional[List[str]] = None) -> None:
        """
        Run migration with optional table filtering.

        Args:
            specific_tables: If provided, only migrate these tables
        """
        self.connect_postgres()

        try:
            # Determine which tables to migrate
            main_tables = specific_tables or self.MAIN_DB_TABLES
            kg_tables = specific_tables or self.KG_DB_TABLES

            # Filter to requested tables
            if specific_tables:
                main_tables = [t for t in main_tables if t in self.MAIN_DB_TABLES]
                kg_tables = [t for t in specific_tables if t in self.KG_DB_TABLES]

            # Migrate main database
            logger.info("=" * 60)
            logger.info("Migrating main database")
            logger.info("=" * 60)
            main_stats = self.migrate_database(
                str(self.config.sqlite_db),
                main_tables,
                "main"
            )
            self.stats.update(main_stats)

            # Migrate knowledge graph database (disable FK checks for ordering)
            if kg_tables:
                logger.info("=" * 60)
                logger.info("Migrating knowledge graph database")
                logger.info("=" * 60)

                # Temporarily disable FK triggers for KG tables
                pg_cursor = self.pg_conn.cursor()
                for t in ["kg_entity_vendors", "kg_relationships"]:
                    pg_cursor.execute(f"ALTER TABLE IF EXISTS {t} DISABLE TRIGGER ALL")
                self.pg_conn.commit()
                pg_cursor.close()

                kg_stats = self.migrate_database(
                    str(self.config.sqlite_kg_db),
                    kg_tables,
                    "knowledge_graph"
                )
                self.stats.update(kg_stats)

                # Re-enable FK triggers
                pg_cursor = self.pg_conn.cursor()
                for t in ["kg_entity_vendors", "kg_relationships"]:
                    pg_cursor.execute(f"ALTER TABLE IF EXISTS {t} ENABLE TRIGGER ALL")
                self.pg_conn.commit()
                pg_cursor.close()

            # Fix PostgreSQL sequences after migration
            # When rows are inserted with explicit IDs (from SQLite), the PG
            # auto-increment sequences are not updated, causing UniqueViolation
            # errors on subsequent INSERTs that rely on the sequence.
            logger.info("=" * 60)
            logger.info("Resetting PostgreSQL sequences")
            logger.info("=" * 60)
            self._fix_sequences()

            # Print summary
            logger.info("=" * 60)
            logger.info("Migration Summary")
            logger.info("=" * 60)
            total_rows = 0
            for table_name, count in self.stats.items():
                if isinstance(count, int):
                    logger.info(f"{table_name}: {count} rows")
                    total_rows += count
                else:
                    logger.error(f"{table_name}: {count}")

            logger.info(f"Total rows migrated: {total_rows}")
            if self.dry_run:
                logger.info("[DRY-RUN] No data was actually written")

        finally:
            self.disconnect_postgres()


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate SQLite data to PostgreSQL for Xiphos"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without writing data"
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        help="Migrate only specific tables (space-separated list)"
    )

    args = parser.parse_args()

    try:
        config = MigrationConfig()
        config.validate_sources()

        migrator = SqliteMigrator(config, dry_run=args.dry_run)
        migrator.run(specific_tables=args.tables)

        if args.dry_run:
            logger.info("Dry-run completed successfully")
        else:
            logger.info("Migration completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
