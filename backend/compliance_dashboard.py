"""
Unified compliance dashboard aggregator.

Provides a single-pane-of-glass view across all 3 compliance lanes:
Counterparty, Cyber (Knowledge Graph), and Export.

Uses the existing db.get_conn() interface and correct table names
(vendors, scoring_results, alerts, enrichment_reports, etc.).
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


TIER_BUCKETS = {
    "BLOCKED": "BLOCKED",
    "WATCH": "WATCH",
    "REVIEW": "REVIEW",
    "QUALIFIED": "QUALIFIED",
    "APPROVED": "APPROVED",
}


def _normalize_tier_bucket(tier: Optional[str]) -> str:
    value = str(tier or "").upper().strip()
    if not value:
        return "UNKNOWN"
    if value in TIER_BUCKETS:
        return value
    if value.startswith("TIER_1"):
        return "BLOCKED"
    if value.startswith("TIER_2"):
        return "REVIEW"
    if value.startswith("TIER_3"):
        return "WATCH"
    if value == "TIER_4_CRITICAL_QUALIFIED":
        return "QUALIFIED"
    if value.startswith("TIER_4") or value.startswith("TIER_5"):
        return "APPROVED"
    return value


def _import_db():
    try:
        import db as _db
        return _db
    except ImportError:
        return None


def _import_kg():
    try:
        import knowledge_graph as _kg
        return _kg
    except ImportError:
        return None


def get_compliance_dashboard(case_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Aggregate compliance data across all 3 lanes for a unified dashboard.

    If case_id is provided, filters data to that specific case.
    Otherwise returns global aggregated metrics.
    """
    dashboard = {
        "summary": _get_summary(case_id),
        "counterparty_lane": _get_counterparty_lane(case_id),
        "export_lane": _get_export_lane(case_id),
        "cyber_lane": _get_cyber_lane(case_id),
        "cross_lane_insights": _get_cross_lane_insights(case_id),
        "activity_feed": _get_activity_feed(case_id),
        "generated_at": datetime.utcnow().isoformat(),
    }
    return dashboard


# ---------------------------------------------------------------------------
# Summary KPIs
# ---------------------------------------------------------------------------

def _get_summary(case_id: Optional[str] = None) -> Dict[str, Any]:
    """Top-level KPIs across all lanes."""
    db = _import_db()
    if not db:
        return {"error": "db module unavailable"}

    try:
        with db.get_conn() as conn:
            # Total cases (vendors)
            if case_id:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM vendors WHERE id = ?", (case_id,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) as cnt FROM vendors").fetchone()
            total_cases = row["cnt"] if row else 0

            # Unresolved alerts
            if case_id:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM alerts WHERE vendor_id = ? AND resolved = 0",
                    (case_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM alerts WHERE resolved = 0"
                ).fetchone()
            total_alerts = row["cnt"] if row else 0

            # Risk distribution from latest scoring per vendor
            risk_dist = {}
            rows = conn.execute("""
                SELECT sr.calibrated_tier, COUNT(*) as cnt
                FROM scoring_results sr
                INNER JOIN (
                    SELECT vendor_id, MAX(id) as max_id
                    FROM scoring_results GROUP BY vendor_id
                ) latest ON sr.id = latest.max_id
                GROUP BY sr.calibrated_tier
            """).fetchall()
            for r in rows:
                bucket = _normalize_tier_bucket(r["calibrated_tier"])
                risk_dist[bucket] = risk_dist.get(bucket, 0) + r["cnt"]

            # Compliance score
            score = _calculate_compliance_score(risk_dist)

            # Total export authorizations
            tx_count = 0
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM transaction_authorizations"
                ).fetchone()
                tx_count = row["cnt"] if row else 0
            except Exception:
                pass

            return {
                "total_cases": total_cases,
                "total_alerts": total_alerts,
                "risk_distribution": risk_dist,
                "compliance_score": score,
                "total_authorizations": tx_count,
                "timestamp": datetime.utcnow().isoformat(),
            }
    except Exception as e:
        logger.error(f"Error getting summary: {e}")
        return {
            "total_cases": 0, "total_alerts": 0,
            "risk_distribution": {}, "compliance_score": 0.0,
            "error": str(e),
        }


def _calculate_compliance_score(risk_dist: dict) -> float:
    """
    Compliance score (0-100) from tier distribution.
    APPROVED=100, QUALIFIED=75, REVIEW=25, WATCH=10, BLOCKED=0
    """
    weights = {"APPROVED": 100, "QUALIFIED": 75, "REVIEW": 25, "WATCH": 10, "BLOCKED": 0}
    total_points = 0
    total_cases = 0
    for tier, count in risk_dist.items():
        total_points += weights.get(tier, 50) * count
        total_cases += count
    return round(total_points / total_cases, 1) if total_cases > 0 else 0.0


# ---------------------------------------------------------------------------
# Counterparty Lane
# ---------------------------------------------------------------------------

def _get_counterparty_lane(case_id: Optional[str] = None) -> Dict[str, Any]:
    """Counterparty vendor screening metrics."""
    db = _import_db()
    if not db:
        return {"error": "db module unavailable"}

    try:
        with db.get_conn() as conn:
            # Cases screened
            row = conn.execute("SELECT COUNT(*) as cnt FROM vendors").fetchone()
            cases_screened = row["cnt"] if row else 0

            # High risk (BLOCKED or WATCH from latest score)
            row = conn.execute("""
                SELECT COUNT(*) as cnt FROM scoring_results sr
                INNER JOIN (
                    SELECT vendor_id, MAX(id) as max_id
                    FROM scoring_results GROUP BY vendor_id
                ) latest ON sr.id = latest.max_id
                WHERE sr.calibrated_tier IN (
                    'BLOCKED', 'WATCH',
                    'TIER_1_DISQUALIFIED', 'TIER_1_CRITICAL_CONCERN',
                    'TIER_2_ELEVATED', 'TIER_2_ELEVATED_REVIEW', 'TIER_2_CONDITIONAL_ACCEPTABLE',
                    'TIER_2_HIGH_CONCERN', 'TIER_2_CAUTION', 'TIER_2_CAUTION_COMMERCIAL',
                    'TIER_3_CONDITIONAL', 'TIER_3_CRITICAL_ACCEPTABLE'
                )
            """).fetchone()
            high_risk = row["cnt"] if row else 0

            # Pending reviews
            row = conn.execute("""
                SELECT COUNT(*) as cnt FROM scoring_results sr
                INNER JOIN (
                    SELECT vendor_id, MAX(id) as max_id
                    FROM scoring_results GROUP BY vendor_id
                ) latest ON sr.id = latest.max_id
                WHERE sr.calibrated_tier IN (
                    'REVIEW',
                    'TIER_2_ELEVATED', 'TIER_2_ELEVATED_REVIEW', 'TIER_2_CONDITIONAL_ACCEPTABLE',
                    'TIER_2_HIGH_CONCERN', 'TIER_2_CAUTION', 'TIER_2_CAUTION_COMMERCIAL'
                )
            """).fetchone()
            pending_reviews = row["cnt"] if row else 0

            # Recent screenings (top 5)
            recent_rows = conn.execute("""
                SELECT v.id, v.name, v.country, sr.calibrated_tier, sr.calibrated_probability,
                       sr.scored_at
                FROM vendors v
                LEFT JOIN scoring_results sr ON v.id = sr.vendor_id
                INNER JOIN (
                    SELECT vendor_id, MAX(id) as max_id
                    FROM scoring_results GROUP BY vendor_id
                ) latest ON sr.id = latest.max_id
                ORDER BY sr.scored_at DESC
                LIMIT 5
            """).fetchall()
            recent = [
                {
                    "case_id": r["id"], "vendor_name": r["name"],
                    "country": r["country"], "tier": _normalize_tier_bucket(r["calibrated_tier"]),
                    "probability": r["calibrated_probability"],
                    "scored_at": r["scored_at"],
                }
                for r in recent_rows
            ]

            # Risk trend (last 30 days)
            thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
            trend_rows = conn.execute("""
                SELECT DATE(scored_at) as day, calibrated_tier, COUNT(*) as cnt
                FROM scoring_results
                WHERE scored_at >= ?
                GROUP BY DATE(scored_at), calibrated_tier
                ORDER BY DATE(scored_at)
            """, (thirty_days_ago,)).fetchall()

            risk_trend = {}
            for r in trend_rows:
                day = r["day"]
                if day not in risk_trend:
                    risk_trend[day] = {}
                bucket = _normalize_tier_bucket(r["calibrated_tier"])
                risk_trend[day][bucket] = risk_trend[day].get(bucket, 0) + r["cnt"]

            return {
                "cases_screened": cases_screened,
                "high_risk_vendors": high_risk,
                "pending_reviews": pending_reviews,
                "recent_screenings": recent,
                "risk_trend": [
                    {"date": d, **tiers} for d, tiers in sorted(risk_trend.items())
                ],
            }
    except Exception as e:
        logger.error(f"Error getting counterparty lane: {e}")
        return {"cases_screened": 0, "high_risk_vendors": 0, "pending_reviews": 0,
                "recent_screenings": [], "risk_trend": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Export Lane
# ---------------------------------------------------------------------------

def _get_export_lane(case_id: Optional[str] = None) -> Dict[str, Any]:
    """Export authorization metrics."""
    db = _import_db()
    if not db:
        return {"error": "db module unavailable"}

    try:
        with db.get_conn() as conn:
            # Total authorizations
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM transaction_authorizations"
            ).fetchone()
            total = row["cnt"] if row else 0

            # Posture distribution
            posture_rows = conn.execute("""
                SELECT combined_posture, COUNT(*) as cnt
                FROM transaction_authorizations
                GROUP BY combined_posture
            """).fetchall()
            posture_dist = {r["combined_posture"]: r["cnt"] for r in posture_rows}

            # Recent authorizations (top 5)
            recent_rows = conn.execute("""
                SELECT id, case_id, transaction_type, destination_country,
                       combined_posture, combined_posture_label, confidence,
                       duration_ms, created_at
                FROM transaction_authorizations
                ORDER BY created_at DESC
                LIMIT 5
            """).fetchall()
            recent = [dict(r) for r in recent_rows]

            # Pending license applications (escalate or license_required)
            row = conn.execute("""
                SELECT COUNT(*) as cnt FROM transaction_authorizations
                WHERE combined_posture IN ('likely_license_required', 'escalate')
            """).fetchone()
            pending_license = row["cnt"] if row else 0

            return {
                "total_authorizations": total,
                "posture_distribution": posture_dist,
                "recent_authorizations": recent,
                "pending_license_applications": pending_license,
            }
    except Exception as e:
        logger.error(f"Error getting export lane: {e}")
        return {"total_authorizations": 0, "posture_distribution": {},
                "recent_authorizations": [], "pending_license_applications": 0,
                "error": str(e)}


# ---------------------------------------------------------------------------
# Cyber / Knowledge Graph Lane
# ---------------------------------------------------------------------------

def _get_cyber_lane(case_id: Optional[str] = None) -> Dict[str, Any]:
    """Knowledge graph and cyber risk metrics."""
    kg = _import_kg()
    if not kg:
        return {"error": "knowledge_graph module unavailable"}

    try:
        from runtime_paths import get_kg_db_path
        import sqlite3

        kg_path = get_kg_db_path()
        conn = sqlite3.connect(kg_path)
        conn.row_factory = sqlite3.Row

        # Entity and relationship counts
        ent_row = conn.execute("SELECT COUNT(*) as cnt FROM kg_entities").fetchone()
        rel_row = conn.execute("SELECT COUNT(*) as cnt FROM kg_relationships").fetchone()
        entities = ent_row["cnt"] if ent_row else 0
        relationships = rel_row["cnt"] if rel_row else 0

        # Entity type distribution
        type_rows = conn.execute("""
            SELECT entity_type, COUNT(*) as cnt FROM kg_entities
            GROUP BY entity_type ORDER BY cnt DESC
        """).fetchall()
        entity_types = {r["entity_type"]: r["cnt"] for r in type_rows}

        # Community count (distinct community_id)
        try:
            comm_row = conn.execute(
                "SELECT COUNT(DISTINCT community_id) as cnt FROM kg_entities WHERE community_id IS NOT NULL"
            ).fetchone()
            communities = comm_row["cnt"] if comm_row else 0
        except Exception:
            communities = 0

        # High centrality entities (top 5)
        try:
            cent_rows = conn.execute("""
                SELECT e.id as entity_id,
                       e.canonical_name as name,
                       e.entity_type,
                       COUNT(r.id) as centrality_score
                FROM kg_entities
                LEFT JOIN kg_relationships r
                  ON e.id = r.source_entity_id OR e.id = r.target_entity_id
                GROUP BY e.id, e.canonical_name, e.entity_type
                ORDER BY centrality_score DESC
                LIMIT 5
            """).fetchall()
            high_centrality = [dict(r) for r in cent_rows]
        except Exception:
            high_centrality = []

        conn.close()

        return {
            "entities_in_graph": entities,
            "relationships": relationships,
            "communities": communities,
            "entity_types": entity_types,
            "high_centrality_entities": high_centrality,
        }
    except Exception as e:
        logger.error(f"Error getting cyber lane: {e}")
        return {"entities_in_graph": 0, "relationships": 0, "communities": 0,
                "entity_types": {}, "high_centrality_entities": [],
                "error": str(e)}


# ---------------------------------------------------------------------------
# Cross-Lane Insights
# ---------------------------------------------------------------------------

def _get_cross_lane_insights(case_id: Optional[str] = None) -> Dict[str, Any]:
    """Cross-lane correlation insights."""
    db = _import_db()
    if not db:
        return {"error": "db module unavailable"}

    try:
        with db.get_conn() as conn:
            # Vendors with export issues (prohibited or escalate posture)
            try:
                rows = conn.execute("""
                    SELECT ta.case_id, v.name, ta.combined_posture, MAX(ta.created_at) as latest
                    FROM transaction_authorizations ta
                    JOIN vendors v ON ta.case_id = v.id
                    WHERE ta.combined_posture IN ('likely_prohibited', 'escalate')
                    GROUP BY ta.case_id, v.name, ta.combined_posture
                    ORDER BY latest DESC
                    LIMIT 10
                """).fetchall()
                vendors_export_issues = [dict(r) for r in rows]
            except Exception:
                vendors_export_issues = []

            # High-risk vendors with unresolved alerts
            try:
                rows = conn.execute("""
                    SELECT v.id, v.name, v.country,
                           COUNT(a.id) as alert_count
                    FROM vendors v
                    JOIN alerts a ON v.id = a.vendor_id AND a.resolved = 0
                    JOIN scoring_results sr ON v.id = sr.vendor_id
                    INNER JOIN (
                        SELECT vendor_id, MAX(id) as max_id
                        FROM scoring_results GROUP BY vendor_id
                    ) latest ON sr.id = latest.max_id
                    WHERE sr.calibrated_tier IN (
                        'BLOCKED', 'WATCH',
                        'TIER_1_DISQUALIFIED', 'TIER_1_CRITICAL_CONCERN',
                        'TIER_2_ELEVATED', 'TIER_2_ELEVATED_REVIEW', 'TIER_2_CONDITIONAL_ACCEPTABLE',
                        'TIER_2_HIGH_CONCERN', 'TIER_2_CAUTION', 'TIER_2_CAUTION_COMMERCIAL',
                        'TIER_3_CONDITIONAL', 'TIER_3_CRITICAL_ACCEPTABLE'
                    )
                    GROUP BY v.id, v.name, v.country
                    ORDER BY alert_count DESC
                    LIMIT 10
                """).fetchall()
                high_risk_alerts = [dict(r) for r in rows]
            except Exception:
                high_risk_alerts = []

            # Compliance gaps
            gaps = []
            # Vendors without any enrichment
            try:
                row = conn.execute("""
                    SELECT COUNT(*) as cnt FROM vendors v
                    LEFT JOIN enrichment_reports er ON v.id = er.vendor_id
                    WHERE er.id IS NULL
                """).fetchone()
                unenriched = row["cnt"] if row else 0
                if unenriched > 0:
                    gaps.append({
                        "type": "missing_enrichment",
                        "severity": "medium",
                        "message": f"{unenriched} vendor(s) have no enrichment reports",
                        "count": unenriched,
                    })
            except Exception:
                pass

            # Vendors without scoring
            try:
                row = conn.execute("""
                    SELECT COUNT(*) as cnt FROM vendors v
                    LEFT JOIN scoring_results sr ON v.id = sr.vendor_id
                    WHERE sr.id IS NULL
                """).fetchone()
                unscored = row["cnt"] if row else 0
                if unscored > 0:
                    gaps.append({
                        "type": "missing_scoring",
                        "severity": "high",
                        "message": f"{unscored} vendor(s) have no risk score",
                        "count": unscored,
                    })
            except Exception:
                pass

        return {
            "vendors_with_export_issues": vendors_export_issues,
            "high_risk_with_alerts": high_risk_alerts,
            "compliance_gaps": gaps,
        }
    except Exception as e:
        logger.error(f"Error getting cross-lane insights: {e}")
        return {"vendors_with_export_issues": [], "high_risk_with_alerts": [],
                "compliance_gaps": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Activity Feed
# ---------------------------------------------------------------------------

def _get_activity_feed(case_id: Optional[str] = None, limit: int = 20) -> List[Dict]:
    """Unified activity feed across all lanes."""
    db = _import_db()
    if not db:
        return []

    activities = []
    try:
        with db.get_conn() as conn:
            # Recent decisions
            try:
                rows = conn.execute("""
                    SELECT d.vendor_id, v.name as vendor_name, d.decision,
                           d.decided_by, d.reason, d.created_at
                    FROM decisions d
                    JOIN vendors v ON d.vendor_id = v.id
                    ORDER BY d.created_at DESC LIMIT 10
                """).fetchall()
                for r in rows:
                    activities.append({
                        "type": "decision",
                        "case_id": r["vendor_id"],
                        "vendor_name": r["vendor_name"],
                        "detail": f"{r['decision']} by {r['decided_by'] or 'system'}",
                        "timestamp": r["created_at"],
                    })
            except Exception:
                pass

            # Recent screenings
            try:
                rows = conn.execute("""
                    SELECT query_name, matched, best_score, matched_list, screened_at
                    FROM screening_log
                    ORDER BY screened_at DESC LIMIT 10
                """).fetchall()
                for r in rows:
                    activities.append({
                        "type": "screening",
                        "detail": f"Screened '{r['query_name']}' - {'MATCH' if r['matched'] else 'clear'}"
                                  + (f" ({r['matched_list']})" if r['matched'] else ""),
                        "timestamp": r["screened_at"],
                    })
            except Exception:
                pass

            # Recent monitoring sweeps
            try:
                rows = conn.execute("""
                    SELECT ml.vendor_id, v.name, ml.previous_risk, ml.current_risk,
                           ml.risk_changed, ml.checked_at
                    FROM monitoring_log ml
                    JOIN vendors v ON ml.vendor_id = v.id
                    WHERE CAST(ml.risk_changed AS INTEGER) = 1
                    ORDER BY ml.checked_at DESC LIMIT 10
                """).fetchall()
                for r in rows:
                    activities.append({
                        "type": "risk_change",
                        "case_id": r["vendor_id"],
                        "vendor_name": r["name"],
                        "detail": f"Risk changed: {r['previous_risk']} -> {r['current_risk']}",
                        "timestamp": r["checked_at"],
                    })
            except Exception:
                pass

            # Recent export authorizations
            try:
                rows = conn.execute("""
                    SELECT id, case_id, destination_country,
                           combined_posture_label, created_at
                    FROM transaction_authorizations
                    ORDER BY created_at DESC LIMIT 10
                """).fetchall()
                for r in rows:
                    activities.append({
                        "type": "export_authorization",
                        "case_id": r["case_id"],
                        "detail": f"Export auth to {r['destination_country']}: {r['combined_posture_label']}",
                        "timestamp": r["created_at"],
                    })
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Error getting activity feed: {e}")

    # Sort all activities by timestamp descending, take top N
    activities.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return activities[:limit]
