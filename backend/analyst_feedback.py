"""
Analyst Feedback Loop and Scoring Weight Calibration Module (Sprint 15-01)

Collects feedback from compliance analysts on scoring results and uses that data
to calibrate the FGAMLogit scoring engine weights. Supports feedback on vendor
tiers, individual factors, and override suggestions.

Database tables:
- analyst_feedback: Individual feedback records (agree/disagree/override)
- scoring_calibration: Calibration history and active weight versions

Functions work with PostgreSQL via db.get_conn() for production deployments.
"""

import logging
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from db import get_conn

logger = logging.getLogger(__name__)

# Default FGAMLogit factor weights (from fgamlogit.py)
DEFAULT_WEIGHTS = {
    "geography": 0.15,
    "ownership_opacity": 0.20,
    "financial_health": 0.12,
    "sanctions_proximity": 0.25,
    "data_quality": 0.10,
    "cyber_risk": 0.12,
    "export_control_risk": 0.06,
}

TIER_HIERARCHY = {
    "GREEN": 1,
    "YELLOW": 2,
    "ORANGE": 3,
    "RED": 4,
}


@dataclass
class AnalystFeedback:
    """Single analyst feedback record."""
    vendor_id: str
    scoring_result_id: int
    analyst_action: str  # 'agree', 'disagree', 'override'
    original_tier: str
    original_score: float
    analyst_tier: Optional[str] = None
    analyst_notes: Optional[str] = None
    factor_overrides: Optional[Dict[str, float]] = None
    created_by: str = "analyst"
    id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class CalibrationResult:
    """Weight calibration result."""
    factor_name: str
    original_weight: float
    calibrated_weight: float
    sample_size: int
    accuracy_before: Optional[float] = None
    accuracy_after: Optional[float] = None
    model_version: str = "1.0"
    id: Optional[int] = None
    calibrated_at: Optional[datetime] = None


def init_feedback_tables() -> None:
    """Create analyst_feedback and scoring_calibration tables if they don't exist."""
    with get_conn() as conn:
        cur = conn.cursor()

        # Create analyst_feedback table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS analyst_feedback (
                id SERIAL PRIMARY KEY,
                vendor_id TEXT NOT NULL,
                scoring_result_id INTEGER,
                analyst_action TEXT NOT NULL,
                original_tier TEXT NOT NULL,
                original_score FLOAT NOT NULL,
                analyst_tier TEXT,
                analyst_notes TEXT,
                factor_overrides JSONB,
                created_at TIMESTAMP DEFAULT NOW(),
                created_by TEXT DEFAULT 'analyst'
            );
        """)

        # Create index on vendor_id and created_at for fast queries
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_analyst_feedback_vendor_id
            ON analyst_feedback(vendor_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_analyst_feedback_created_at
            ON analyst_feedback(created_at DESC);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_analyst_feedback_action
            ON analyst_feedback(analyst_action);
        """)

        # Create scoring_calibration table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scoring_calibration (
                id SERIAL PRIMARY KEY,
                factor_name TEXT NOT NULL,
                original_weight FLOAT NOT NULL,
                calibrated_weight FLOAT NOT NULL,
                sample_size INTEGER NOT NULL,
                accuracy_before FLOAT,
                accuracy_after FLOAT,
                calibrated_at TIMESTAMP DEFAULT NOW(),
                model_version TEXT NOT NULL
            );
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_scoring_calibration_factor
            ON scoring_calibration(factor_name);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_scoring_calibration_calibrated_at
            ON scoring_calibration(calibrated_at DESC);
        """)

        logger.info("Analyst feedback tables initialized successfully")


def save_feedback(
    vendor_id: str,
    scoring_result_id: int,
    action: str,
    original_tier: str,
    original_score: float,
    analyst_tier: Optional[str] = None,
    notes: Optional[str] = None,
    factor_overrides: Optional[Dict[str, float]] = None,
    created_by: str = "analyst",
) -> Dict[str, Any]:
    """
    Save analyst feedback on a scoring result.

    Args:
        vendor_id: The vendor being scored
        scoring_result_id: ID of the scoring_results row
        action: 'agree', 'disagree', or 'override'
        original_tier: Original tier from scoring (GREEN/YELLOW/ORANGE/RED)
        original_score: Original FGAMLogit score
        analyst_tier: Analyst's suggested tier (only for disagree/override)
        notes: Analyst notes/justification
        factor_overrides: Dict of factor -> weight if analyst overrode factors
        created_by: Analyst name/ID

    Returns:
        Dict with feedback record including id, created_at
    """
    if action not in ("agree", "disagree", "override"):
        raise ValueError(f"Invalid action: {action}. Must be agree, disagree, or override")

    if action in ("disagree", "override") and not analyst_tier:
        raise ValueError(f"action={action} requires analyst_tier to be set")

    with get_conn() as conn:
        cur = conn.cursor()

        factor_overrides_json = json.dumps(factor_overrides) if factor_overrides else None

        cur.execute("""
            INSERT INTO analyst_feedback
            (vendor_id, scoring_result_id, analyst_action, original_tier, original_score,
             analyst_tier, analyst_notes, factor_overrides, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at, vendor_id, analyst_action, original_tier, original_score,
                      analyst_tier, analyst_notes, factor_overrides, created_by;
        """,
        (
            vendor_id,
            scoring_result_id,
            action,
            original_tier,
            original_score,
            analyst_tier,
            notes,
            factor_overrides_json,
            created_by,
        ),
        )

        result = cur.fetchone()

        if result:
            feedback_id, created_at, *_ = result
            logger.info(
                f"Saved feedback for vendor {vendor_id}: action={action}, id={feedback_id}"
            )
            return {
                "id": feedback_id,
                "vendor_id": vendor_id,
                "scoring_result_id": scoring_result_id,
                "analyst_action": action,
                "original_tier": original_tier,
                "original_score": original_score,
                "analyst_tier": analyst_tier,
                "analyst_notes": notes,
                "factor_overrides": factor_overrides,
                "created_by": created_by,
                "created_at": created_at.isoformat() if created_at else None,
            }
        else:
            raise RuntimeError("Failed to insert feedback record")


def get_feedback(
    vendor_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Retrieve analyst feedback records with optional filters.

    Args:
        vendor_id: Filter by vendor (optional)
        action: Filter by action type: 'agree', 'disagree', 'override' (optional)
        limit: Max records to return (default 50)
        offset: Pagination offset (default 0)

    Returns:
        List of feedback dicts
    """
    with get_conn() as conn:
        cur = conn.cursor()

        query = "SELECT * FROM analyst_feedback WHERE 1=1"
        params = []

        if vendor_id:
            query += " AND vendor_id = %s"
            params.append(vendor_id)

        if action:
            if action not in ("agree", "disagree", "override"):
                raise ValueError(f"Invalid action filter: {action}")
            query += " AND analyst_action = %s"
            params.append(action)

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        rows = cur.fetchall()

        results = []
        for row in rows:
            (
                feedback_id,
                v_id,
                scoring_id,
                analyst_action,
                orig_tier,
                orig_score,
                analyst_tier,
                analyst_notes,
                factor_overrides_json,
                created_at,
                created_by,
            ) = row

            results.append({
                "id": feedback_id,
                "vendor_id": v_id,
                "scoring_result_id": scoring_id,
                "analyst_action": analyst_action,
                "original_tier": orig_tier,
                "original_score": orig_score,
                "analyst_tier": analyst_tier,
                "analyst_notes": analyst_notes,
                "factor_overrides": (
                    json.loads(factor_overrides_json)
                    if factor_overrides_json
                    else None
                ),
                "created_at": created_at.isoformat() if created_at else None,
                "created_by": created_by,
            })

        return results


def get_feedback_stats() -> Dict[str, Any]:
    """
    Compute aggregate feedback statistics.

    Returns:
        Dict with:
        - total: total feedback records
        - agree_count, disagree_count, override_count: counts by action
        - agree_rate, disagree_rate: percentages
        - tier_confusion_matrix: matrix of (original_tier, analyst_tier) mismatches
        - most_overridden_factors: top factors in factor_overrides
        - recent_feedback_count: last 30 days
    """
    with get_conn() as conn:
        cur = conn.cursor()

        # Total counts
        cur.execute("SELECT COUNT(*) FROM analyst_feedback")
        total = cur.fetchone()[0]

        cur.execute(
            "SELECT analyst_action, COUNT(*) FROM analyst_feedback GROUP BY analyst_action"
        )
        action_counts = {row[0]: row[1] for row in cur.fetchall()}

        # Compute rates
        agree_count = action_counts.get("agree", 0)
        disagree_count = action_counts.get("disagree", 0)
        override_count = action_counts.get("override", 0)

        agree_rate = agree_count / total if total > 0 else 0
        disagree_rate = disagree_count / total if total > 0 else 0

        # Tier confusion matrix: count (original_tier, analyst_tier) pairs
        cur.execute("""
            SELECT original_tier, analyst_tier, COUNT(*) as count
            FROM analyst_feedback
            WHERE analyst_tier IS NOT NULL
            GROUP BY original_tier, analyst_tier
        """)
        confusion = {}
        for orig, analyst, count in cur.fetchall():
            key = f"{orig}->{analyst}"
            confusion[key] = count

        # Most frequently overridden factors
        cur.execute("""
            SELECT factor_overrides FROM analyst_feedback
            WHERE factor_overrides IS NOT NULL
        """)
        factor_counts = {}
        for (overrides_json,) in cur.fetchall():
            if overrides_json:
                overrides = json.loads(overrides_json)
                for factor in overrides.keys():
                    factor_counts[factor] = factor_counts.get(factor, 0) + 1

        most_overridden = sorted(
            factor_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]

        # Recent feedback (last 30 days)
        cur.execute("""
            SELECT COUNT(*) FROM analyst_feedback
            WHERE created_at > NOW() - INTERVAL '30 days'
        """)
        recent_count = cur.fetchone()[0]

        return {
            "total": total,
            "agree_count": agree_count,
            "disagree_count": disagree_count,
            "override_count": override_count,
            "agree_rate": round(agree_rate, 3),
            "disagree_rate": round(disagree_rate, 3),
            "tier_confusion_matrix": confusion,
            "most_overridden_factors": dict(most_overridden),
            "recent_feedback_count": recent_count,
        }


def calibrate_weights(min_samples: int = 30) -> Dict[str, Any]:
    """
    Calibrate FGAMLogit weights using analyst feedback.

    Algorithm:
    1. Load all 'disagree' and 'override' feedback records with factor_overrides
    2. For each factor, compute the average weight analysts prefer
    3. Blend: new_weight = 0.7 * original + 0.3 * analyst_avg (conservative blend)
    4. Normalize weights to sum to 1.0
    5. Save to scoring_calibration table
    6. Return calibration results

    Args:
        min_samples: Minimum feedback records needed per factor to calibrate

    Returns:
        Dict with:
        - status: 'calibrated' or 'insufficient_data'
        - weights: Dict of calibrated weights (or original if insufficient data)
        - sample_size: Number of disagree/override records used
        - factor_details: List of tuples (factor, original, calibrated, samples)
        - accuracy_improvement: Estimated improvement (placeholder)
        - calibrated_at: timestamp
        - model_version: '1.0'
    """
    with get_conn() as conn:
        cur = conn.cursor()

        # Get all disagree/override feedback with factor_overrides
        cur.execute("""
            SELECT factor_overrides, analyst_action
            FROM analyst_feedback
            WHERE analyst_action IN ('disagree', 'override')
            AND factor_overrides IS NOT NULL
        """)

        rows = cur.fetchall()
        sample_size = len(rows)

        # Accumulate factor preferences
        factor_weights: Dict[str, List[float]] = {f: [] for f in DEFAULT_WEIGHTS.keys()}

        for (overrides_json, action) in rows:
            if overrides_json:
                overrides = json.loads(overrides_json)
                for factor, weight in overrides.items():
                    if factor in factor_weights:
                        factor_weights[factor].append(weight)

        # Check if we have enough samples
        factors_with_data = [
            f for f, weights in factor_weights.items() if len(weights) >= min_samples
        ]

        if not factors_with_data:
            logger.warning(
                f"Insufficient calibration data: only {sample_size} disagree/override records; "
                f"need {min_samples} per factor. Using default weights."
            )
            return {
                "status": "insufficient_data",
                "weights": DEFAULT_WEIGHTS.copy(),
                "sample_size": sample_size,
                "min_samples_required": min_samples,
                "factors_with_sufficient_data": factors_with_data,
            }

        # Compute blended weights
        calibrated_weights = {}
        for factor, original_weight in DEFAULT_WEIGHTS.items():
            if len(factor_weights[factor]) >= min_samples:
                analyst_avg = sum(factor_weights[factor]) / len(factor_weights[factor])
                # Conservative blend: 70% original, 30% analyst preference
                blended = 0.7 * original_weight + 0.3 * analyst_avg
                calibrated_weights[factor] = blended
            else:
                # Not enough data, keep original
                calibrated_weights[factor] = original_weight

        # Normalize to sum to 1.0
        total = sum(calibrated_weights.values())
        if total > 0:
            calibrated_weights = {f: w / total for f, w in calibrated_weights.items()}

        # Save calibration records
        for factor in DEFAULT_WEIGHTS.keys():
            original = DEFAULT_WEIGHTS[factor]
            calibrated = calibrated_weights.get(factor, original)
            num_samples = len(factor_weights.get(factor, []))

            cur.execute("""
                INSERT INTO scoring_calibration
                (factor_name, original_weight, calibrated_weight, sample_size, model_version)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, calibrated_at;
            """,
            (factor, original, calibrated, num_samples, "1.0"),
            )
            cur.fetchone()

        # Build response
        factor_details = []
        for factor in DEFAULT_WEIGHTS.keys():
            original = DEFAULT_WEIGHTS[factor]
            calibrated = calibrated_weights.get(factor, original)
            num_samples = len(factor_weights.get(factor, []))
            factor_details.append({
                "factor": factor,
                "original_weight": round(original, 4),
                "calibrated_weight": round(calibrated, 4),
                "samples": num_samples,
            })

        logger.info(
            f"Weights calibrated successfully from {sample_size} feedback records. "
            f"Factors with sufficient data: {len(factors_with_data)}"
        )

        return {
            "status": "calibrated",
            "weights": {f: round(w, 4) for f, w in calibrated_weights.items()},
            "sample_size": sample_size,
            "factors_with_sufficient_data": factors_with_data,
            "factor_details": factor_details,
            "accuracy_improvement": 0.0,  # Placeholder
            "calibrated_at": datetime.utcnow().isoformat(),
            "model_version": "1.0",
        }


def get_active_weights() -> Dict[str, Any]:
    """
    Get the currently active weights (calibrated if available, default otherwise).

    Returns:
        Dict with:
        - weights: {factor_name: weight}
        - source: 'calibrated' or 'default'
        - calibrated_at: timestamp if calibrated, None otherwise
        - model_version: version string
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Check if we have recent calibration (within 90 days)
            cur.execute("""
                SELECT factor_name, calibrated_weight, calibrated_at, model_version
                FROM scoring_calibration
                WHERE calibrated_at > NOW() - INTERVAL '90 days'
                ORDER BY calibrated_at DESC, id DESC
            """)

            rows = cur.fetchall()

            if rows:
                # Use most recent calibration
                calibrated_at = rows[0][2]
                model_version = rows[0][3]

                weights = {}
                for factor_name, calibrated_weight, _, _ in rows:
                    weights[factor_name] = calibrated_weight

                # Verify we have all factors
                if len(weights) == len(DEFAULT_WEIGHTS):
                    return {
                        "weights": {f: round(w, 4) for f, w in weights.items()},
                        "source": "calibrated",
                        "calibrated_at": calibrated_at.isoformat() if calibrated_at else None,
                        "model_version": model_version,
                    }

            # Fall back to defaults
            return {
                "weights": DEFAULT_WEIGHTS.copy(),
                "source": "default",
                "calibrated_at": None,
                "model_version": "1.0",
            }

    except Exception as e:
        logger.error(f"Error getting active weights: {e}")
        # Return defaults on error
        return {
            "weights": DEFAULT_WEIGHTS.copy(),
            "source": "default",
            "calibrated_at": None,
            "model_version": "1.0",
        }
