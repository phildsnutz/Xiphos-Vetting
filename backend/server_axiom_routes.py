"""
AXIOM Intelligence API Routes

REST API endpoints for the AXIOM (Automated eXtraction of Intelligence from
Open Media) collection system. Provides endpoints for:
  - Agentic search (Tier 2): POST /api/axiom/search
  - Extraction (Tier 2): POST /api/axiom/extract
  - Watchlist management (Tier 3): CRUD on /api/axiom/watchlist
  - Monitoring scans (Tier 3): POST /api/axiom/scan
  - Alerts (Tier 3): GET /api/axiom/alerts
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from flask import g, jsonify, request

logger = logging.getLogger(__name__)


def register_axiom_routes(*, app, require_auth, db):
    """Register all AXIOM API routes on the Flask app."""

    def _dev_axiom_fallback_allowed(error: str) -> bool:
        if os.environ.get("XIPHOS_DEV_MODE", "false").lower() != "true":
            return False
        lowered = str(error or "").lower()
        return "no api key available" in lowered or "configure ai provider" in lowered

    def _build_local_axiom_fallback(*, target, vendor_id: str = "", error: str = "", include_ingestion: bool = False):
        graph_context = {}
        try:
            if vendor_id:
                from ai_analysis import _sanitize_graph_context

                graph_context = _sanitize_graph_context(vendor_id) or {}
        except Exception:
            graph_context = {}

        entities = [
            {
                "name": target.prime_contractor,
                "entity_type": "company",
                "confidence": 0.92,
            }
        ]
        seen_entities = {target.prime_contractor.lower()}

        if target.vehicle_name:
            entities.append(
                {
                    "name": target.vehicle_name,
                    "entity_type": "contract_vehicle",
                    "confidence": 0.58,
                }
            )
            seen_entities.add(target.vehicle_name.lower())

        for item in (graph_context.get("top_entities_by_degree") or [])[:3]:
            name = str(item.get("name") or "").strip()
            if not name or name.lower() in seen_entities:
                continue
            entities.append(
                {
                    "name": name,
                    "entity_type": str(item.get("entity_type") or "entity"),
                    "confidence": 0.67,
                }
            )
            seen_entities.add(name.lower())

        relationships = []
        seen_relationships: set[tuple[str, str, str]] = set()
        if target.vehicle_name:
            seed_key = (target.prime_contractor.lower(), target.vehicle_name.lower(), "associated_with")
            relationships.append(
                {
                    "source_entity": target.prime_contractor,
                    "target_entity": target.vehicle_name,
                    "rel_type": "associated_with",
                    "confidence": 0.38,
                    "evidence": [
                        "Mission brief carried both the entity and vehicle context into the AXIOM pressure fallback.",
                    ],
                }
            )
            seen_relationships.add(seed_key)

        for rel in (graph_context.get("top_relationships") or [])[:4]:
            source_name = str(rel.get("source") or "").strip()
            target_name = str(rel.get("target") or "").strip()
            rel_type = str(rel.get("type") or "related_entity").strip() or "related_entity"
            if not source_name or not target_name:
                continue
            dedupe_key = (source_name.lower(), target_name.lower(), rel_type.lower())
            if dedupe_key in seen_relationships:
                continue
            relationships.append(
                {
                    "source_entity": source_name,
                    "target_entity": target_name,
                    "rel_type": rel_type,
                    "confidence": float(rel.get("confidence") or 0.62),
                    "evidence": [
                        "Derived from the current graph context because no external provider key is configured in dev mode.",
                    ],
                }
            )
            seen_relationships.add(dedupe_key)

        gaps = []
        for family in (graph_context.get("missing_required_edge_families") or [])[:2]:
            family_text = str(family or "").replace("_", " ").strip()
            if not family_text:
                continue
            gaps.append(
                {
                    "gap_type": "graph_gap",
                    "description": f"The graph is still missing {family_text} around {target.prime_contractor}.",
                    "confidence": 0.81,
                }
            )

        if graph_context.get("thin_graph") or len(relationships) < 2:
            gaps.append(
                {
                    "gap_type": "relationship_fabric",
                    "description": f"The relationship fabric around {target.prime_contractor} is still too thin to freeze as stable truth.",
                    "confidence": 0.76,
                }
            )

        if target.vehicle_name:
            gaps.append(
                {
                    "gap_type": "vehicle_lineage",
                    "description": f"The incumbent and teammate lineage around {target.vehicle_name} still needs direct pressure.",
                    "confidence": 0.72,
                }
            )

        if not gaps:
            gaps.append(
                {
                    "gap_type": "control_path_pressure",
                    "description": f"Pressure ownership and control around {target.prime_contractor} until the control story either holds or breaks.",
                    "confidence": 0.61,
                }
            )

        advisory = []
        top_entities = [str(item.get("name") or "").strip() for item in (graph_context.get("top_entities_by_degree") or [])[:3]]
        top_entities = [item for item in top_entities if item]
        if top_entities:
            advisory.append(
                {
                    "opportunity_type": "graph_pressure",
                    "description": f"Use the current graph around {', '.join(top_entities)} to decide which weak edge changes the call fastest.",
                    "priority": "high",
                }
            )
        if target.vehicle_name:
            advisory.append(
                {
                    "opportunity_type": "vehicle_pressure",
                    "description": f"Work the incumbent path, teammate network, and likely transition story around {target.vehicle_name}.",
                    "priority": "high",
                }
            )
        network_risk_level = str(graph_context.get("network_risk_level") or "").lower()
        if network_risk_level in {"high", "critical"}:
            advisory.append(
                {
                    "opportunity_type": "network_risk",
                    "description": f"The graph is already carrying {network_risk_level} network risk. Pressure the nodes causing that propagation before trusting the quiet surface story.",
                    "priority": "high",
                }
            )
        if not advisory:
            advisory.append(
                {
                    "opportunity_type": "pressure_thread",
                    "description": f"Keep pressure on ownership, control, and teammate structure around {target.prime_contractor} until the weak edge stops moving.",
                    "priority": "medium",
                }
            )

        response = {
            "status": "completed",
            "iteration": 1,
            "entities": entities,
            "relationships": relationships,
            "intelligence_gaps": gaps,
            "advisory_opportunities": advisory,
            "advisory": advisory,
            "total_queries": 1,
            "total_findings": len(entities) + len(relationships),
            "total_connector_calls": 0,
            "elapsed_ms": 0,
            "local_fallback": {
                "mode": "deterministic_dev_pressure",
                "reason": error or "No external provider key available in dev mode.",
            },
        }
        if include_ingestion:
            response["kg_ingestion"] = {
                "entities_created": 0,
                "relationships_created": 0,
                "claims_created": 0,
                "evidence_created": 0,
            }
        return response

    def _watchlist_priority(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized == "medium":
            return "standard"
        if normalized in {"critical", "high", "standard", "low"}:
            return normalized
        return "standard"

    def _alert_priority(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized == "info":
            return "low"
        if normalized in {"critical", "high", "medium", "low"}:
            return normalized
        return "low"

    def _parse_json_list(value):
        if isinstance(value, list):
            return value
        if not value:
            return []
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except (TypeError, ValueError, json.JSONDecodeError):
                return []
        return []

    def _serialize_watchlist_entry(entry):
        return {
            "id": entry.id,
            "target": entry.prime_contractor,
            "prime_contractor": entry.prime_contractor,
            "contract_name": entry.contract_name,
            "vehicle": entry.vehicle_name,
            "vehicle_name": entry.vehicle_name,
            "installation": entry.installation,
            "priority": entry.priority,
            "last_scan": entry.last_scan_at,
            "last_scan_at": entry.last_scan_at,
            "next_scan_at": entry.next_scan_at,
            "scan_count": entry.scan_count,
            "status": "idle" if entry.active else "inactive",
            "active": entry.active,
            "created_at": entry.created_at,
        }

    def _maybe_queue_neo4j_sync(*, since_timestamp: str, requested_by: str = "", requested_by_email: str = ""):
        try:
            from neo4j_integration import is_neo4j_available
            from neo4j_sync_scheduler import get_neo4j_sync_scheduler

            if not is_neo4j_available():
                return {"status": "unavailable"}

            job = get_neo4j_sync_scheduler().queue_incremental_sync(
                since_timestamp,
                requested_by=requested_by,
                requested_by_email=requested_by_email,
                metadata={"requested_via": "axiom_search_ingest"},
            )
            return {
                "status": job.get("status") or "queued",
                "job_id": job.get("job_id"),
                "status_url": f"/api/neo4j/sync/{job.get('job_id')}" if job.get("job_id") else None,
                "reused_existing_job": bool(job.get("reused_existing_job")),
            }
        except Exception as exc:
            logger.warning("axiom_routes: Neo4j sync queue failed: %s", exc)
            return {"status": "failed", "error": str(exc)}

    # -------------------------------------------------------------------
    # Tier 2: Agentic Search
    # -------------------------------------------------------------------

    @app.route("/api/axiom/search", methods=["POST"])
    @require_auth("cases:enrich")
    def api_axiom_search():
        """
        Launch an AXIOM agentic search.

        Request body:
        {
            "prime_contractor": "SMX Technologies",    // required
            "contract_name": "LEIA",                   // optional
            "vehicle_name": "ASTRO",                   // optional
            "installation": "Camp Smith",              // optional
            "website": "https://smxtech.com",          // optional
            "known_subs": ["The Unconventional"],      // optional
            "context": "INDOPACOM IT services",        // optional
            "provider": "anthropic",                   // optional, default anthropic
            "model": "claude-sonnet-4-6"             // optional
        }

        Returns:
        {
            "entities": [...],
            "relationships": [...],
            "intelligence_gaps": [...],
            "advisory_opportunities": [...],
            "iterations": [...],
            "total_queries": int,
            "total_findings": int,
            "elapsed_ms": int
        }
        """
        try:
            from axiom_agent import run_agent, SearchTarget

            body = request.get_json(silent=True) or {}
            prime = str(body.get("prime_contractor") or body.get("target_entity") or "").strip()
            if not prime:
                return jsonify({"error": "Missing required field: prime_contractor"}), 400

            target = SearchTarget(
                prime_contractor=prime,
                contract_name=str(body.get("contract_name") or body.get("contract") or ""),
                vehicle_name=str(body.get("vehicle_name") or body.get("vehicle") or ""),
                installation=str(body.get("installation") or ""),
                website=str(body.get("website") or ""),
                known_subs=body.get("known_subs") or body.get("knownSubs") or [],
                context=str(body.get("context") or body.get("domain_focus") or ""),
            )

            # Get user ID from Flask g context (set by require_auth)
            user_id = g.user.get("sub", "") if getattr(g, "user", None) else ""

            result = run_agent(
                target=target,
                provider=body.get("provider", "anthropic"),
                model=body.get("model", "claude-sonnet-4-6"),
                user_id=user_id,
                provider_locked="provider" in body,
                model_locked="model" in body,
            )

            if result.error:
                if _dev_axiom_fallback_allowed(result.error):
                    return jsonify(_build_local_axiom_fallback(target=target, error=result.error)), 200
                return jsonify({"error": result.error, "partial_result": result.to_dict()}), 500

            response = result.to_dict()
            response["status"] = "completed"
            response["iteration"] = len(result.iterations)
            return jsonify(response), 200

        except ImportError as e:
            logger.error("axiom_routes: axiom_agent not available: %s", e)
            return jsonify({"error": "AXIOM agent module not available"}), 503
        except Exception as exc:
            logger.exception("axiom_routes: search failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/axiom/search/ingest", methods=["POST"])
    @require_auth("cases:enrich")
    def api_axiom_search_ingest():
        """
        Run an AXIOM search AND ingest results into the Knowledge Graph.

        Same request body as /api/axiom/search, with additional response:
        {
            ...,
            "kg_ingestion": {
                "entities_created": int,
                "relationships_created": int,
                "claims_created": int,
                "evidence_created": int
            }
        }
        """
        try:
            from axiom_agent import run_agent, ingest_agent_result, SearchTarget

            body = request.get_json(silent=True) or {}
            prime = str(body.get("prime_contractor") or body.get("target_entity") or "").strip()
            if not prime:
                return jsonify({"error": "Missing required field: prime_contractor"}), 400

            target = SearchTarget(
                prime_contractor=prime,
                contract_name=str(body.get("contract_name") or body.get("contract") or ""),
                vehicle_name=str(body.get("vehicle_name") or body.get("vehicle") or ""),
                installation=str(body.get("installation") or ""),
                website=str(body.get("website") or ""),
                known_subs=body.get("known_subs") or body.get("knownSubs") or [],
                context=str(body.get("context") or body.get("domain_focus") or ""),
            )

            user_id = g.user.get("sub", "") if getattr(g, "user", None) else ""
            user_email = g.user.get("email", "") if getattr(g, "user", None) else ""

            result = run_agent(
                target=target,
                provider=body.get("provider", "anthropic"),
                model=body.get("model", "claude-sonnet-4-6"),
                user_id=user_id,
                provider_locked="provider" in body,
                model_locked="model" in body,
            )

            if result.error:
                if _dev_axiom_fallback_allowed(result.error):
                    return jsonify(
                        _build_local_axiom_fallback(
                            target=target,
                            vendor_id=str(body.get("vendor_id") or ""),
                            error=result.error,
                            include_ingestion=True,
                        )
                    ), 200
                return jsonify({"error": result.error, "partial_result": result.to_dict()}), 500

            # Ingest into KG
            sync_since = datetime.now(timezone.utc).isoformat()
            kg_summary = ingest_agent_result(result, vendor_id=body.get("vendor_id", ""))

            response = result.to_dict()
            response["status"] = "completed"
            response["iteration"] = len(result.iterations)
            response["kg_ingestion"] = kg_summary
            if kg_summary.get("entities_created") or kg_summary.get("relationships_created"):
                response["neo4j_sync"] = _maybe_queue_neo4j_sync(
                    since_timestamp=sync_since,
                    requested_by=user_id,
                    requested_by_email=user_email,
                )
            return jsonify(response), 200

        except ImportError as e:
            return jsonify({"error": "AXIOM agent module not available"}), 503
        except Exception as exc:
            logger.exception("axiom_routes: search+ingest failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # -------------------------------------------------------------------
    # Tier 2: Extraction
    # -------------------------------------------------------------------

    @app.route("/api/axiom/extract", methods=["POST"])
    @require_auth("cases:enrich")
    def api_axiom_extract():
        """
        Extract structured intelligence from raw text content.

        Request body:
        {
            "content": "raw text to analyze",         // required
            "context": "mission context",              // optional
            "focus_entities": ["entity1", "entity2"],  // optional
            "provider": "anthropic",                   // optional
            "model": "claude-sonnet-4-6"             // optional
        }
        """
        try:
            from axiom_extractor import extract_from_text
            from axiom_agent import resolve_runtime_ai_credentials

            body = request.get_json(silent=True) or {}
            content = body.get("content", "").strip()
            if not content:
                return jsonify({"error": "Missing required field: content"}), 400

            user_id = g.user.get("sub", "") if getattr(g, "user", None) else ""

            # Resolve API key
            provider, model, api_key = resolve_runtime_ai_credentials(
                user_id=user_id,
                provider=body.get("provider", "anthropic"),
                model=body.get("model", "claude-sonnet-4-6"),
                provider_locked="provider" in body,
                model_locked="model" in body,
            )

            result = extract_from_text(
                content=content,
                context=body.get("context", ""),
                focus_entities=body.get("focus_entities"),
                api_key=api_key,
                provider=provider,
                model=model,
            )

            return jsonify({
                "entities": [{"name": e.name, "entity_type": e.entity_type,
                              "confidence": e.confidence, "context": e.context,
                              "attributes": e.attributes} for e in result.entities],
                "relationships": [{"source": r.source, "target": r.target,
                                   "rel_type": r.rel_type, "confidence": r.confidence,
                                   "evidence_text": r.evidence_text} for r in result.relationships],
                "signals": [{"signal_type": s.signal_type, "description": s.description,
                             "confidence": s.confidence, "entities_involved": s.entities_involved,
                             "temporal": s.temporal} for s in result.signals],
                "contract_references": result.contract_references,
                "advisory_flags": result.advisory_flags,
                "elapsed_ms": result.elapsed_ms,
                "error": result.error,
            }), 200

        except ImportError:
            return jsonify({"error": "AXIOM extractor module not available"}), 503
        except Exception as exc:
            logger.exception("axiom_routes: extract failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/axiom/extract/batch", methods=["POST"])
    @require_auth("cases:enrich")
    def api_axiom_extract_batch():
        """
        Extract intelligence from a batch of job postings.

        Request body:
        {
            "postings": [{"title": "...", "company": "...", ...}],  // required
            "context": "mission context",                            // optional
            "provider": "anthropic",                                 // optional
            "model": "claude-sonnet-4-6"                           // optional
        }
        """
        try:
            from axiom_extractor import extract_from_job_postings
            from axiom_agent import resolve_runtime_ai_credentials

            body = request.get_json(silent=True) or {}
            postings = body.get("postings", [])
            if not postings:
                return jsonify({"error": "Missing required field: postings"}), 400

            user_id = g.user.get("sub", "") if getattr(g, "user", None) else ""

            provider, model, api_key = resolve_runtime_ai_credentials(
                user_id=user_id,
                provider=body.get("provider", "anthropic"),
                model=body.get("model", "claude-sonnet-4-6"),
                provider_locked="provider" in body,
                model_locked="model" in body,
            )

            result = extract_from_job_postings(
                postings=postings,
                context=body.get("context", ""),
                api_key=api_key,
                provider=provider,
                model=model,
            )

            return jsonify({
                "entities": [{"name": e.name, "entity_type": e.entity_type,
                              "confidence": e.confidence, "context": e.context,
                              "attributes": e.attributes} for e in result.entities],
                "relationships": [{"source": r.source, "target": r.target,
                                   "rel_type": r.rel_type, "confidence": r.confidence,
                                   "evidence_text": r.evidence_text} for r in result.relationships],
                "signals": [{"signal_type": s.signal_type, "description": s.description,
                             "confidence": s.confidence} for s in result.signals],
                "contract_references": result.contract_references,
                "advisory_flags": result.advisory_flags,
                "elapsed_ms": result.elapsed_ms,
            }), 200

        except ImportError:
            return jsonify({"error": "AXIOM extractor module not available"}), 503
        except Exception as exc:
            logger.exception("axiom_routes: batch extract failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # -------------------------------------------------------------------
    # Tier 3: Watchlist Management
    # -------------------------------------------------------------------

    @app.route("/api/axiom/watchlist", methods=["GET"])
    @require_auth("monitor:read")
    def api_axiom_watchlist_list():
        """List all AXIOM watchlist entries."""
        try:
            from axiom_monitor import get_watchlist, init_axiom_monitor_tables
            init_axiom_monitor_tables()

            active_only = request.args.get("active", "true").lower() == "true"
            entries = get_watchlist(active_only=active_only)
            serialized = [_serialize_watchlist_entry(e) for e in entries]

            return jsonify({
                "watchlist": serialized,
                "entries": serialized,
                "count": len(entries),
            }), 200

        except ImportError:
            return jsonify({"error": "AXIOM monitor module not available"}), 503
        except Exception as exc:
            logger.exception("axiom_routes: watchlist list failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/axiom/watchlist", methods=["POST"])
    @require_auth("monitor:run")
    def api_axiom_watchlist_add():
        """
        Add entry to AXIOM watchlist.

        Request body:
        {
            "prime_contractor": "SMX Technologies",  // required
            "contract_name": "LEIA",                 // optional
            "vehicle_name": "ASTRO",                 // optional
            "installation": "Camp Smith",            // optional
            "website": "",                           // optional
            "priority": "critical"                   // optional: critical|high|standard|low
        }
        """
        try:
            from axiom_monitor import add_to_watchlist, init_axiom_monitor_tables
            init_axiom_monitor_tables()

            body = request.get_json(silent=True) or {}
            prime = str(body.get("prime_contractor") or body.get("target") or "").strip()
            if not prime:
                return jsonify({"error": "Missing required field: prime_contractor"}), 400

            entry = add_to_watchlist(
                prime_contractor=prime,
                contract_name=str(body.get("contract_name") or body.get("contract") or ""),
                vehicle_name=str(body.get("vehicle_name") or body.get("vehicle") or ""),
                installation=str(body.get("installation") or ""),
                website=str(body.get("website") or ""),
                priority=_watchlist_priority(body.get("priority", "standard")),
                metadata=body.get("metadata"),
            )

            payload = _serialize_watchlist_entry(entry)
            payload["message"] = f"Added {prime} to AXIOM watchlist"
            return jsonify(payload), 201

        except ImportError:
            return jsonify({"error": "AXIOM monitor module not available"}), 503
        except Exception as exc:
            logger.exception("axiom_routes: watchlist add failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # -------------------------------------------------------------------
    # Tier 3: Manual Scan
    # -------------------------------------------------------------------

    @app.route("/api/axiom/scan/<watchlist_id>", methods=["POST"])
    @require_auth("monitor:run")
    def api_axiom_scan(watchlist_id):
        """Trigger an immediate scan for a watchlist entry."""
        try:
            from axiom_monitor import (
                get_watchlist, scan_watchlist_entry, init_axiom_monitor_tables
            )
            init_axiom_monitor_tables()

            entries = get_watchlist(active_only=False)
            match = [e for e in entries if e.id == watchlist_id]
            if not match:
                return jsonify({"error": f"Watchlist entry not found: {watchlist_id}"}), 404

            snapshot, alerts = scan_watchlist_entry(match[0])

            return jsonify({
                "watchlist_id": watchlist_id,
                "entities_found": len(snapshot.entities),
                "total_positions": snapshot.total_positions,
                "alerts_generated": len(alerts),
                "alerts": [
                    {
                        "alert_type": a.alert_type,
                        "severity": a.severity,
                        "title": a.title,
                        "description": a.description,
                    }
                    for a in alerts
                ],
                "scan_timestamp": snapshot.scan_timestamp,
            }), 200

        except ImportError:
            return jsonify({"error": "AXIOM monitor module not available"}), 503
        except Exception as exc:
            logger.exception("axiom_routes: scan failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # -------------------------------------------------------------------
    # Tier 3: Alerts
    # -------------------------------------------------------------------

    @app.route("/api/axiom/alerts", methods=["GET"])
    @require_auth("alerts:read")
    def api_axiom_alerts():
        """Get recent AXIOM change alerts."""
        try:
            from axiom_monitor import get_recent_alerts, get_watchlist, init_axiom_monitor_tables
            init_axiom_monitor_tables()

            limit = int(request.args.get("limit", 20))
            severity = request.args.get("severity", "")

            alerts = get_recent_alerts(limit=limit, severity=severity)
            watchlist_by_id = {entry.id: entry for entry in get_watchlist(active_only=False)}
            normalized = []
            for alert in alerts:
                entry = watchlist_by_id.get(alert.get("watchlist_id", ""))
                entities_involved = _parse_json_list(alert.get("entities_involved"))
                normalized.append({
                    "id": alert.get("id"),
                    "type": alert.get("alert_type"),
                    "alert_type": alert.get("alert_type"),
                    "severity": alert.get("severity"),
                    "priority": _alert_priority(alert.get("severity")),
                    "title": alert.get("title"),
                    "target": entry.prime_contractor if entry else (entities_involved[0] if entities_involved else ""),
                    "details": alert.get("description"),
                    "description": alert.get("description"),
                    "timestamp": alert.get("created_at"),
                    "created_at": alert.get("created_at"),
                    "watchlist_entry_id": alert.get("watchlist_id"),
                    "watchlist_id": alert.get("watchlist_id"),
                    "entities_involved": entities_involved,
                })

            return jsonify({
                "alerts": normalized,
                "count": len(normalized),
            }), 200

        except ImportError:
            return jsonify({"error": "AXIOM monitor module not available"}), 503
        except Exception as exc:
            logger.exception("axiom_routes: alerts failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # -------------------------------------------------------------------
    # Tier 3: Daemon Control
    # -------------------------------------------------------------------

    @app.route("/api/axiom/daemon/start", methods=["POST"])
    @require_auth("monitor:run")
    def api_axiom_daemon_start():
        """Start the AXIOM monitoring daemon."""
        try:
            from axiom_monitor import start_daemon

            body = request.get_json(silent=True) or {}
            interval = int(body.get("check_interval", 300))

            start_daemon(check_interval=interval)
            return jsonify({"message": "AXIOM daemon started", "check_interval": interval}), 200

        except ImportError:
            return jsonify({"error": "AXIOM monitor module not available"}), 503
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/axiom/daemon/stop", methods=["POST"])
    @require_auth("monitor:run")
    def api_axiom_daemon_stop():
        """Stop the AXIOM monitoring daemon."""
        try:
            from axiom_monitor import stop_daemon

            stop_daemon()
            return jsonify({"message": "AXIOM daemon stop requested"}), 200

        except ImportError:
            return jsonify({"error": "AXIOM monitor module not available"}), 503
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # -------------------------------------------------------------------
    # Health check
    # -------------------------------------------------------------------

    @app.route("/api/axiom/health", methods=["GET"])
    def api_axiom_health():
        """Check AXIOM system availability."""
        status = {"agent": False, "extractor": False, "monitor": False}

        try:
            import axiom_agent
            status["agent"] = True
        except ImportError:
            pass

        try:
            import axiom_extractor
            status["extractor"] = True
        except ImportError:
            pass

        try:
            import axiom_monitor
            status["monitor"] = True
        except ImportError:
            pass

        all_ok = all(status.values())
        return jsonify({"status": "ok" if all_ok else "degraded", "components": status}), 200

    logger.info("axiom_routes: registered %d AXIOM API endpoints", 10)
