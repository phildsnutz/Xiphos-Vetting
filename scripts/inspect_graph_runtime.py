#!/usr/bin/env python3
"""Inspect the active Helios graph runtime paths and table counts."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime_paths import get_data_dir, get_kg_db_path, get_main_db_path


def _table_count(path: str, table: str) -> int | None:
    try:
        conn = sqlite3.connect(path)
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()
    except Exception:
        return None


def _print_db_summary(label: str, path: str, tables: list[str]) -> None:
    print(f"{label}: {path}")
    resolved = Path(path)
    print(f"  resolved_path: {resolved.resolve(strict=False)}")
    print(f"  exists: {resolved.exists()}")
    print(f"  is_symlink: {resolved.is_symlink()}")
    if resolved.is_symlink():
        print(f"  symlink_target: {os.readlink(resolved)}")
    if resolved.exists():
        print(f"  size_bytes: {resolved.stat().st_size}")
    for table in tables:
        print(f"  {table}: {_table_count(path, table)}")


def main() -> None:
    print("Helios Runtime Graph Inspection")
    print(f"data_dir: {get_data_dir()}")
    print(f"env.XIPHOS_DB_PATH: {os.environ.get('XIPHOS_DB_PATH', '')}")
    print(f"env.XIPHOS_KG_DB_PATH: {os.environ.get('XIPHOS_KG_DB_PATH', '')}")
    _print_db_summary(
        "main_db",
        get_main_db_path(),
        ["vendors", "alerts"],
    )
    _print_db_summary(
        "kg_db",
        get_kg_db_path(),
        ["kg_entities", "kg_relationships", "kg_entity_vendors"],
    )


if __name__ == "__main__":
    main()
