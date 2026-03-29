import os
import sqlite3
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _create_ai_config_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE ai_config (
            user_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            api_key_enc TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()


def test_migrate_legacy_ai_config_rows_copies_missing_rows_without_overwrite(tmp_path):
    import ai_analysis

    legacy_db = tmp_path / "legacy.db"
    active_db = tmp_path / "active.db"

    legacy_conn = sqlite3.connect(legacy_db)
    legacy_conn.row_factory = sqlite3.Row
    _create_ai_config_table(legacy_conn)
    legacy_conn.executemany(
        """
        INSERT INTO ai_config (user_id, provider, model, api_key_enc, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("__org_default__", "anthropic", "claude-sonnet-4-6", "enc-org", "2026-03-27T00:00:00Z", "2026-03-27T00:00:00Z"),
            ("__openai_backup__", "openai", "gpt-4o", "enc-backup", "2026-03-27T00:00:00Z", "2026-03-27T00:00:00Z"),
            ("user-123", "anthropic", "claude-sonnet-4-6", "enc-user", "2026-03-27T00:00:00Z", "2026-03-27T00:00:00Z"),
        ],
    )
    legacy_conn.commit()
    legacy_conn.close()

    active_conn = sqlite3.connect(active_db)
    active_conn.row_factory = sqlite3.Row
    _create_ai_config_table(active_conn)
    active_conn.execute(
        """
        INSERT INTO ai_config (user_id, provider, model, api_key_enc, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("user-123", "openai", "gpt-4o-mini", "enc-existing", "2026-03-28T00:00:00Z", "2026-03-28T00:00:00Z"),
    )
    active_conn.commit()

    migrated = ai_analysis._migrate_legacy_ai_config_rows(active_conn, str(legacy_db))
    active_conn.commit()

    assert migrated == 2

    rows = {
        row["user_id"]: dict(row)
        for row in active_conn.execute(
            "SELECT user_id, provider, model, api_key_enc FROM ai_config ORDER BY user_id"
        ).fetchall()
    }
    active_conn.close()

    assert rows["__org_default__"]["provider"] == "anthropic"
    assert rows["__org_default__"]["model"] == "claude-sonnet-4-6"
    assert rows["__openai_backup__"]["provider"] == "openai"
    assert rows["user-123"]["provider"] == "openai"
    assert rows["user-123"]["model"] == "gpt-4o-mini"
    assert rows["user-123"]["api_key_enc"] == "enc-existing"
