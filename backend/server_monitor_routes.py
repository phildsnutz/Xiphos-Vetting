from __future__ import annotations

from flask import jsonify, request


def register_monitor_routes(
    *,
    app,
    require_auth,
    db,
    monitor_available,
    monitor_scheduler_available,
    vendor_monitor_cls_provider,
    monitor_scheduler_provider,
    serialize_monitor_status,
    serialize_monitor_run,
    parse_since_hours,
):
    @app.route("/api/cases/<case_id>/monitor", methods=["POST"])
    @require_auth("monitor:run")
    def api_monitor_vendor(case_id):
        """Queue or run a monitoring check on a specific vendor."""
        has_monitor = bool(monitor_available())
        has_monitor_scheduler = bool(monitor_scheduler_available())
        vendor_monitor_cls = vendor_monitor_cls_provider()
        if not has_monitor and not has_monitor_scheduler:
            return jsonify({"error": "Monitoring module not available"}), 501
        v = db.get_vendor(case_id)
        if not v:
            return jsonify({"error": "Case not found"}), 404

        body = request.get_json(silent=True) or {}
        if body.get("sync") or not has_monitor_scheduler:
            if not has_monitor or vendor_monitor_cls is None:
                return jsonify({"error": "Synchronous monitoring is not available"}), 501
            monitor = vendor_monitor_cls()
            result = monitor.check_vendor(case_id)
            if result is None:
                return jsonify({"error": "Monitoring check failed"}), 500
            return jsonify(
                {
                    "run_id": result.run_id,
                    "vendor_id": result.vendor_id,
                    "vendor_name": result.vendor_name,
                    "previous_risk": result.previous_risk,
                    "current_risk": result.current_risk,
                    "risk_changed": result.risk_changed,
                    "score_before": result.score_before,
                    "score_after": result.score_after,
                    "new_findings_count": len(result.new_findings),
                    "resolved_findings_count": len(result.resolved_findings),
                    "sources_triggered": list(result.sources_triggered or []),
                    "delta_summary": result.delta_summary,
                    "started_at": result.started_at,
                    "completed_at": result.completed_at,
                    "new_findings": result.new_findings[:10],
                    "new_risk_signals": result.new_risk_signals[:10],
                    "elapsed_ms": result.elapsed_ms,
                    "mode": "sync",
                }
            )

        scheduler = monitor_scheduler_provider()
        sweep_id = scheduler.trigger_sweep(vendor_ids=[case_id])
        status = scheduler.get_sweep_status(sweep_id)
        payload = serialize_monitor_status(sweep_id, status, vendor_id=case_id)
        payload["mode"] = "async"
        payload["message"] = (
            f"Monitoring check queued for {v['name']}. "
            f"Poll /api/cases/{case_id}/monitor/{sweep_id} for status."
        )
        payload["status_url"] = f"/api/cases/{case_id}/monitor/{sweep_id}"
        return jsonify(payload), 202

    @app.route("/api/cases/<case_id>/monitor/<sweep_id>")
    @require_auth("monitor:read")
    def api_monitor_vendor_status(case_id, sweep_id):
        """Poll status for a queued single-vendor monitoring check."""
        if not monitor_scheduler_available():
            return jsonify({"error": "Monitoring scheduler not available"}), 501
        if not db.get_vendor(case_id):
            return jsonify({"error": "Case not found"}), 404

        scheduler = monitor_scheduler_provider()
        status = scheduler.get_sweep_status(sweep_id)
        if status.get("status") == "not_found":
            return jsonify({"error": "Sweep not found"}), 404
        return jsonify(serialize_monitor_status(sweep_id, status, vendor_id=case_id))

    @app.route("/api/cases/<case_id>/monitoring")
    @require_auth("monitor:read")
    def api_monitor_vendor_history(case_id):
        """Return recent monitoring history for a specific vendor case."""
        vendor = db.get_vendor(case_id)
        if not vendor:
            return jsonify({"error": "Case not found"}), 404

        limit = request.args.get("limit", 10, type=int)
        limit = max(1, min(limit, 50))
        history = db.get_monitoring_history(case_id, limit=limit)
        latest_score = db.get_latest_score(case_id)

        return jsonify(
            {
                "vendor_id": case_id,
                "vendor_name": vendor["name"],
                "monitoring_history": history,
                "latest_score": {
                    "tier": ((latest_score or {}).get("calibrated", {}) or {}).get("calibrated_tier"),
                    "composite_score": (latest_score or {}).get("composite_score"),
                }
                if latest_score
                else None,
            }
        )

    @app.route("/api/cases/<case_id>/monitor/history")
    @require_auth("monitor:read")
    def api_monitor_case_run_history(case_id):
        """Return monitor-run history with delta summaries for a specific case."""
        vendor = db.get_vendor(case_id)
        if not vendor:
            return jsonify({"error": "Case not found"}), 404

        limit = request.args.get("limit", 10, type=int)
        limit = max(1, min(limit, 50))
        runs = [serialize_monitor_run(entry) for entry in db.get_monitor_run_history(case_id, limit=limit)]
        return jsonify(
            {
                "vendor_id": case_id,
                "vendor_name": vendor["name"],
                "runs": runs,
            }
        )

    @app.route("/api/monitor/run", methods=["POST"])
    @require_auth("monitor:run")
    def api_monitor_all():
        """Run or queue a monitoring sweep on all vendors."""
        has_monitor = bool(monitor_available())
        has_monitor_scheduler = bool(monitor_scheduler_available())
        vendor_monitor_cls = vendor_monitor_cls_provider()
        if not has_monitor and not has_monitor_scheduler:
            return jsonify({"error": "Monitoring module not available"}), 501

        body = request.get_json(silent=True) or {}
        interval = body.get("interval", 86400)
        if not body.get("sync") and has_monitor_scheduler:
            scheduler = monitor_scheduler_provider()
            vendor_ids = body.get("vendor_ids")
            sweep_id = scheduler.trigger_sweep(vendor_ids=vendor_ids if isinstance(vendor_ids, list) else None)
            status = scheduler.get_sweep_status(sweep_id)
            payload = serialize_monitor_status(sweep_id, status)
            payload["mode"] = "async"
            payload["message"] = f"Monitoring sweep queued. Poll /api/monitor/sweep/{sweep_id} for status."
            payload["status_url"] = f"/api/monitor/sweep/{sweep_id}"
            return jsonify(payload), 202

        if not has_monitor or vendor_monitor_cls is None:
            return jsonify({"error": "Synchronous monitoring is not available"}), 501
        monitor = vendor_monitor_cls(check_interval=interval)
        results = monitor.check_all_vendors()

        changes = [r for r in results if r.risk_changed]
        return jsonify(
            {
                "vendors_checked": len(results),
                "risk_changes": len(changes),
                "mode": "sync",
                "changes": [
                    {
                        "vendor_id": r.vendor_id,
                        "vendor_name": r.vendor_name,
                        "previous_risk": r.previous_risk,
                        "current_risk": r.current_risk,
                        "new_findings_count": len(r.new_findings),
                    }
                    for r in changes
                ],
            }
        )

    @app.route("/api/monitor/sweep/<sweep_id>")
    @require_auth("monitor:read")
    def api_monitor_sweep_status(sweep_id):
        """Poll status for a queued portfolio monitoring sweep."""
        if not monitor_scheduler_available():
            return jsonify({"error": "Monitoring scheduler not available"}), 501

        scheduler = monitor_scheduler_provider()
        status = scheduler.get_sweep_status(sweep_id)
        if status.get("status") == "not_found":
            return jsonify({"error": "Sweep not found"}), 404
        return jsonify(serialize_monitor_status(sweep_id, status))

    @app.route("/api/monitor/changes")
    @require_auth("monitor:read")
    def api_monitor_changes():
        """Get recent risk changes from monitoring."""
        limit = request.args.get("limit", 20, type=int)
        since_hours = parse_since_hours(request.args.get("since"))
        try:
            changes = [serialize_monitor_run(entry) for entry in db.get_recent_monitor_changes(limit, since_hours=since_hours)]
            return jsonify({"changes": changes})
        except Exception:
            return jsonify({"changes": [], "note": "Monitoring log table not initialized"})

    @app.route("/api/portfolio/changes")
    @require_auth("monitor:read")
    def api_portfolio_changes():
        """Return recent portfolio changes for the top-strip summary UI."""
        since_hours = parse_since_hours(request.args.get("since")) or 24
        limit = request.args.get("limit", 20, type=int)
        changed_entries = [serialize_monitor_run(entry) for entry in db.get_recent_monitor_changes(limit, since_hours=since_hours)]
        total_count = len(db.list_vendors(limit=10000))
        changed_vendor_ids = {str(entry.get("vendor_id") or "") for entry in changed_entries if entry.get("vendor_id")}
        return jsonify(
            {
                "changed": [
                    {
                        "case_id": entry.get("vendor_id"),
                        "name": entry.get("vendor_name") or "",
                        "change_type": entry.get("change_type") or "no_change",
                        "summary": entry.get("delta_summary") or "",
                        "timestamp": entry.get("completed_at") or entry.get("checked_at"),
                    }
                    for entry in changed_entries
                ],
                "unchanged_count": max(0, total_count - len(changed_vendor_ids)),
                "total_count": total_count,
            }
        )
