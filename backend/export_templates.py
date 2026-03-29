"""
Export Transaction Templates (S13-04)

Allows users to save, load, and execute transaction authorization templates.
Templates capture common transaction patterns (jurisdiction, item type,
destination rules) for quick re-use.

Schema:
  export_templates table:
    - id TEXT PK (tpl-<uuid8>)
    - name TEXT NOT NULL UNIQUE
    - created_by TEXT NOT NULL
    - created_at TEXT NOT NULL
    - last_used_at TEXT nullable
    - template_data JSON NOT NULL
      {
        "jurisdiction_guess": "ear" | "itar",
        "classification_guess": str (ECCN or USML),
        "item_or_data_summary": str,
        "destination_country": str,
        "destination_company": str,
        "end_use_summary": str,
        "access_context": str,
      }
    - usage_count INT DEFAULT 0

Usage:
    from export_templates import (
        save_template, load_template, list_templates,
        execute_template, init_templates_db
    )
    init_templates_db()
    result = save_template("My ITAR Export", {...})
    templates = list_templates()
    exec_result = execute_template(template_id)
"""

import json
import uuid
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def _safe_import_db():
    try:
        import db
        return db
    except ImportError:
        return None


def init_templates_db():
    """Create export_templates table if it doesn't exist."""
    db_mod = _safe_import_db()
    if not db_mod:
        return

    with db_mod.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS export_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                template_data TEXT NOT NULL,
                usage_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_export_templates_name
            ON export_templates(name)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_export_templates_created_by
            ON export_templates(created_by)
        """)


def save_template(
    name: str,
    template_data: dict,
    created_by: str = "system",
) -> dict:
    """
    Save a new export transaction template.

    Args:
        name: Unique template name
        template_data: Dict with transaction fields (jurisdiction, classification, etc.)
        created_by: User creating the template

    Returns:
        dict with id, name, created_at, or error
    """
    db_mod = _safe_import_db()
    if not db_mod:
        return {"error": "Database module unavailable"}

    try:
        init_templates_db()
    except Exception:
        pass

    tpl_id = f"tpl-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()

    try:
        with db_mod.get_conn() as conn:
            conn.execute("""
                INSERT INTO export_templates
                (id, name, created_by, created_at, template_data, usage_count)
                VALUES (?, ?, ?, ?, ?, 0)
            """, (tpl_id, name, created_by, now, json.dumps(template_data)))

        logger.info(f"Saved export template: {name} (id={tpl_id})")
        return {
            "id": tpl_id,
            "name": name,
            "created_at": now,
        }
    except Exception as e:
        logger.error(f"Failed to save template {name}: {e}")
        return {"error": str(e)}


def load_template(template_id: str) -> dict:
    """
    Load a template by ID.

    Args:
        template_id: Template ID

    Returns:
        dict with template data, or error
    """
    db_mod = _safe_import_db()
    if not db_mod:
        return {"error": "Database module unavailable"}

    try:
        with db_mod.get_conn() as conn:
            row = conn.execute("""
                SELECT id, name, created_by, created_at, template_data, usage_count
                FROM export_templates WHERE id = ?
            """, (template_id,)).fetchone()

            if not row:
                return {"error": "Template not found"}

            template_data = json.loads(row["template_data"])
            return {
                "id": row["id"],
                "name": row["name"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "usage_count": row["usage_count"],
                "template_data": template_data,
            }
    except Exception as e:
        logger.error(f"Failed to load template {template_id}: {e}")
        return {"error": str(e)}


def list_templates(created_by: Optional[str] = None) -> dict:
    """
    List all templates, optionally filtered by creator.

    Args:
        created_by: Filter to templates created by this user

    Returns:
        dict with templates list
    """
    db_mod = _safe_import_db()
    if not db_mod:
        return {"templates": [], "total": 0}

    try:
        with db_mod.get_conn() as conn:
            if created_by:
                rows = conn.execute("""
                    SELECT id, name, created_by, created_at, usage_count
                    FROM export_templates
                    WHERE created_by = ?
                    ORDER BY created_at DESC
                """, (created_by,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, name, created_by, created_at, usage_count
                    FROM export_templates
                    ORDER BY created_at DESC
                """).fetchall()

            templates = [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "created_by": r["created_by"],
                    "created_at": r["created_at"],
                    "usage_count": r["usage_count"],
                }
                for r in rows
            ]

            return {
                "templates": templates,
                "total": len(templates),
            }
    except Exception as e:
        logger.error(f"Failed to list templates: {e}")
        return {"templates": [], "total": 0}


def execute_template(template_id: str) -> dict:
    """
    Load a template and return its data ready for authorization.
    Also increments usage_count and updates last_used_at.

    Args:
        template_id: Template ID

    Returns:
        dict with template_data and execution metadata
    """
    db_mod = _safe_import_db()
    if not db_mod:
        return {"error": "Database module unavailable"}

    tpl = load_template(template_id)
    if "error" in tpl:
        return tpl

    # Update usage tracking
    try:
        now = datetime.utcnow().isoformat()
        with db_mod.get_conn() as conn:
            conn.execute("""
                UPDATE export_templates
                SET usage_count = usage_count + 1, last_used_at = ?
                WHERE id = ?
            """, (now, template_id))

        logger.info(f"Executed template {template_id} (now used {tpl['usage_count'] + 1} times)")
    except Exception as e:
        logger.warning(f"Failed to update template usage: {e}")

    return {
        "template_id": template_id,
        "template_name": tpl["name"],
        "transaction_data": tpl["template_data"],
    }
