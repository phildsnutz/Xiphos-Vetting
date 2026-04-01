from __future__ import annotations

import uuid

from flask import jsonify, request


def register_mission_thread_routes(
    *,
    app,
    require_auth,
    mission_threads_module,
    mission_thread_briefing_module,
    log_audit,
    current_user_email_provider,
    current_user_id_provider,
):
    @app.route("/api/mission-threads", methods=["POST"])
    @require_auth("cases:create")
    def api_create_mission_thread():
        body = request.get_json(silent=True) or {}
        name = str(body.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Missing required field: name"}), 400

        created_by = current_user_email_provider() or current_user_id_provider()
        thread_id = str(body.get("id") or f"mt-{uuid.uuid4().hex[:10]}")
        try:
            payload = mission_threads_module.create_mission_thread(
                thread_id=thread_id,
                name=name,
                created_by=created_by,
                description=body.get("description", ""),
                lane=body.get("lane", ""),
                program=body.get("program", ""),
                theater=body.get("theater", ""),
                mission_type=body.get("mission_type", ""),
                status=body.get("status", "draft"),
            )
            log_audit(
                "mission_thread_created",
                "mission_thread",
                thread_id,
                detail=f"Created mission thread '{name}' by {created_by}",
            )
            return jsonify(payload), 201
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/mission-threads", methods=["GET"])
    @require_auth("cases:read")
    def api_list_mission_threads():
        limit = request.args.get("limit", 100, type=int)
        created_by = request.args.get("created_by", None)
        try:
            threads = mission_threads_module.list_mission_threads(
                created_by=created_by,
                limit=limit,
            )
            return jsonify({"mission_threads": threads, "total": len(threads)})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/mission-threads/<thread_id>", methods=["GET"])
    @require_auth("cases:read")
    def api_get_mission_thread(thread_id):
        try:
            payload = mission_threads_module.get_mission_thread(thread_id)
            if not payload:
                return jsonify({"error": "Mission thread not found"}), 404
            return jsonify(payload)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/mission-threads/<thread_id>/members", methods=["POST"])
    @require_auth("cases:create")
    def api_add_mission_thread_member(thread_id):
        body = request.get_json(silent=True) or {}
        entries = body.get("members") if isinstance(body.get("members"), list) else [body]
        if not entries or not any(isinstance(entry, dict) for entry in entries):
            return jsonify({"error": "Request body must contain a member payload"}), 400

        created_members = []
        try:
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                member = mission_threads_module.add_mission_thread_member(
                    thread_id,
                    vendor_id=entry.get("vendor_id", ""),
                    entity_id=entry.get("entity_id", ""),
                    role=entry.get("role", ""),
                    criticality=entry.get("criticality", "supporting"),
                    subsystem=entry.get("subsystem", ""),
                    site=entry.get("site", ""),
                    is_alternate=bool(entry.get("is_alternate")),
                    notes=entry.get("notes", ""),
                )
                created_members.append(member)
            log_audit(
                "mission_thread_member_added",
                "mission_thread",
                thread_id,
                detail=f"Added {len(created_members)} member(s) to mission thread",
            )
            if len(created_members) == 1:
                return jsonify(created_members[0]), 201
            return jsonify({"members": created_members, "total": len(created_members)}), 201
        except LookupError as exc:
            message = str(exc)
            status = 404 if "not found" in message.lower() else 400
            return jsonify({"error": message}), status
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/mission-threads/<thread_id>/summary", methods=["GET"])
    @require_auth("cases:read")
    def api_mission_thread_summary(thread_id):
        depth = request.args.get("depth", 2, type=int)
        try:
            payload = mission_threads_module.build_mission_thread_summary(thread_id, depth=depth)
            if not payload:
                return jsonify({"error": "Mission thread not found"}), 404
            return jsonify(payload)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/mission-threads/<thread_id>/graph", methods=["GET"])
    @require_auth("cases:read")
    def api_mission_thread_graph(thread_id):
        depth = request.args.get("depth", 2, type=int)
        try:
            payload = mission_threads_module.build_mission_thread_graph(thread_id, depth=depth)
            if not payload:
                return jsonify({"error": "Mission thread not found"}), 404
            return jsonify(payload)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/mission-threads/<thread_id>/briefing", methods=["GET"])
    @require_auth("cases:read")
    def api_mission_thread_briefing(thread_id):
        depth = request.args.get("depth", 2, type=int)
        mode = request.args.get("mode", "control", type=str)
        try:
            payload = mission_thread_briefing_module.build_mission_thread_briefing(
                thread_id,
                depth=depth,
                member_passport_mode=mode,
            )
            if not payload:
                return jsonify({"error": "Mission thread not found"}), 404
            return jsonify(payload)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/mission-threads/<thread_id>/members/<int:member_id>/passport", methods=["GET"])
    @require_auth("cases:read")
    def api_mission_thread_member_passport(thread_id, member_id):
        depth = request.args.get("depth", 2, type=int)
        mode = request.args.get("mode", "full", type=str)
        try:
            payload = mission_threads_module.build_mission_thread_member_passport(
                thread_id,
                member_id,
                depth=depth,
                mode=mode,
            )
            if not payload:
                return jsonify({"error": "Mission thread member not found"}), 404
            return jsonify(payload)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
