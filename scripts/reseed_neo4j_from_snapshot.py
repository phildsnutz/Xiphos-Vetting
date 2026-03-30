#!/usr/bin/env python3
"""
Reseed Neo4j from a SQLite knowledge-graph snapshot with visible progress.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _load_env_file(path: Path) -> None:
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="Path to SQLite KG snapshot")
    parser.add_argument("--env-file", default=str(Path.home() / ".config/xiphos/helios.env"))
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--skip-entities", action="store_true")
    parser.add_argument("--skip-clear", action="store_true")
    args = parser.parse_args()

    os.environ["XIPHOS_KG_DB_PATH"] = str(Path(args.snapshot).expanduser().resolve())
    os.environ["XIPHOS_NEO4J_REL_BATCH_SIZE"] = str(max(1, args.batch_size))
    _load_env_file(Path(args.env_file).expanduser().resolve())

    import neo4j_integration as n

    conn = sqlite3.connect(os.environ["XIPHOS_KG_DB_PATH"])
    conn.row_factory = sqlite3.Row
    entities = [dict(row) for row in conn.execute("SELECT * FROM kg_entities")]
    rels_by_type: dict[str, list[dict[str, object]]] = {}
    for row in conn.execute(
        "SELECT * FROM kg_relationships ORDER BY rel_type, source_entity_id, target_entity_id, id"
    ):
        rel = dict(row)
        rels_by_type.setdefault(str(rel["rel_type"]), []).append(rel)
    conn.close()

    print(
        json.dumps(
            {
                "snapshot": os.environ["XIPHOS_KG_DB_PATH"],
                "entity_count": len(entities),
                "relationship_count": sum(len(v) for v in rels_by_type.values()),
                "batch_size": max(1, args.batch_size),
            },
            indent=2,
        ),
        flush=True,
    )
    if args.skip_entities:
        print(json.dumps({"entity_sync": "skipped"}, indent=2), flush=True)
    else:
        print(json.dumps({"entity_sync": n.sync_entities_to_neo4j(entities)}, indent=2), flush=True)

    if not args.skip_clear:
        print(json.dumps({"clear_relationships": n.clear_neo4j_relationships()}, indent=2), flush=True)

    for rel_type, rels in sorted(rels_by_type.items(), key=lambda item: (-len(item[1]), item[0])):
        result = n.sync_relationships_to_neo4j(rels)
        stats = n.get_graph_stats_neo4j()
        print(
            json.dumps(
                {
                    "rel_type": rel_type,
                    "input": len(rels),
                    "result": result,
                    "aura_relationship_count": stats["relationship_count"],
                },
                indent=2,
            ),
            flush=True,
        )
        if result.get("failed_count"):
            break

    print(json.dumps({"final_stats": n.get_graph_stats_neo4j()}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
