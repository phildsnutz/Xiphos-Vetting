from __future__ import annotations

import os

from flask import jsonify, request


def register_graph_surface_routes(
    *,
    app,
    require_auth,
    db,
    has_kg,
    kg_module,
    current_enrichment_report,
    ingest_case_graph,
):
    @app.route("/api/cases/<case_id>/graph")
    @require_auth("enrich:read")
    def api_case_graph(case_id):
        """Get the knowledge graph for a vendor case (entities + relationships)."""
        v = db.get_vendor(case_id)
        if not v:
            return jsonify({"error": "Case not found"}), 404
        try:
            requested_depth = request.args.get("depth", default=3, type=int) or 3
            requested_depth = max(1, min(requested_depth, 4))
            from graph_ingest import get_vendor_graph_summary

            graph = get_vendor_graph_summary(case_id, depth=requested_depth)
            if graph.get("relationship_count", 0) == 0:
                report = current_enrichment_report(case_id)
                if report:
                    ingest_case_graph(case_id, v, report)
                    graph = get_vendor_graph_summary(case_id, depth=requested_depth)
            return jsonify(graph)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/graph/stats")
    @require_auth("enrich:read")
    def api_graph_stats():
        """Get overall knowledge graph statistics."""
        try:
            from knowledge_graph import get_kg_stats, init_kg_db

            init_kg_db()
            stats = get_kg_stats()
            return jsonify(stats)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/graph/entity/<entity_id>/provenance")
    @require_auth("cases:read")
    def api_graph_entity_provenance(entity_id):
        if not has_kg:
            return jsonify({"error": "Knowledge graph module not available"}), 501
        try:
            kg_module.init_kg_db()
            payload = kg_module.get_entity_provenance(entity_id)
            if not payload:
                return jsonify({"error": "Entity not found"}), 404
            return jsonify(payload)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/graph/relationship/<int:relationship_id>/provenance")
    @require_auth("cases:read")
    def api_graph_relationship_provenance(relationship_id):
        if not has_kg:
            return jsonify({"error": "Knowledge graph module not available"}), 501
        try:
            kg_module.init_kg_db()
            payload = kg_module.get_relationship_provenance(relationship_id)
            if not payload:
                return jsonify({"error": "Relationship not found"}), 404
            return jsonify(payload)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/graph/runtime")
    @require_auth("admin:read")
    def api_graph_runtime():
        """Expose the active graph runtime paths and table counts for diagnostics."""
        try:
            import sqlite3 as _sqlite3
            from pathlib import Path as _Path

            from runtime_paths import get_data_dir, get_kg_db_path, get_main_db_path
            from knowledge_graph import init_kg_db

            init_kg_db()

            def _table_count(path: str, table: str):
                try:
                    conn = _sqlite3.connect(path)
                    try:
                        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    finally:
                        conn.close()
                except Exception:
                    return None

            def _db_summary(path: str, tables: list[str]) -> dict:
                resolved = _Path(path)
                summary = {
                    "path": str(resolved),
                    "resolved_path": str(resolved.resolve(strict=False)),
                    "exists": resolved.exists(),
                    "is_symlink": resolved.is_symlink(),
                    "configured_env": "",
                    "tables": {},
                }
                if resolved.is_symlink():
                    summary["symlink_target"] = os.readlink(resolved)
                if resolved.exists():
                    summary["size_bytes"] = resolved.stat().st_size
                for table in tables:
                    summary["tables"][table] = _table_count(path, table)
                return summary

            main_db_path = get_main_db_path()
            kg_db_path = get_kg_db_path()

            main_summary = _db_summary(main_db_path, ["vendors", "alerts", "scoring_results"])
            main_summary["configured_env"] = os.environ.get("XIPHOS_DB_PATH", "")

            kg_summary = _db_summary(kg_db_path, ["kg_entities", "kg_relationships", "kg_entity_vendors"])
            kg_summary["configured_env"] = os.environ.get("XIPHOS_KG_DB_PATH", "")

            return jsonify(
                {
                    "data_dir": {
                        "path": get_data_dir(),
                        "configured_env": os.environ.get("XIPHOS_DATA_DIR", ""),
                    },
                    "main_db": main_summary,
                    "kg_db": kg_summary,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/graph/export")
    @require_auth("admin:read")
    def api_graph_export():
        """Export the full knowledge graph (admin only)."""
        try:
            from knowledge_graph import export_graph, init_kg_db

            init_kg_db()
            data = export_graph()
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
