"""
Xiphos Helios -- Phase 4: Portfolio Intelligence

Score drift detection, deterministic anomaly detectors, and portfolio
trend analytics.  This module is consumed by:
  - monitor.py (during re-enrichment sweeps)
  - server.py  (portfolio analytics API routes)
  - portfolio-screen.tsx (frontend trend charts)

Architecture:
  1. ScoreDriftDetector   -- re-scores a vendor, computes pp delta, fires alerts
  2. AnomalyDetectorBank  -- bank of deterministic detectors (sanctions hit,
                             ownership change, media spike, financial downgrade)
  3. PortfolioAnalytics   -- aggregate trend calculations for the dashboard
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional

import db

try:
    from fgamlogit import score_vendor, build_vendor_input
    HAS_SCORING = True
except ImportError:
    HAS_SCORING = False

try:
    from osint.enrichment import enrich_vendor
    HAS_OSINT = True
except ImportError:
    HAS_OSINT = False


# ---------------------------------------------------------------------------
#  Data types
# ---------------------------------------------------------------------------

@dataclass
class DriftResult:
    vendor_id: str
    vendor_name: str
    previous_score: float
    current_score: float
    delta_pp: float          # percentage-point shift (signed)
    previous_tier: str
    current_tier: str
    tier_changed: bool
    factors_changed: list    # factors with largest absolute delta
    timestamp: str = ""

    @property
    def severity(self) -> str:
        abs_d = abs(self.delta_pp)
        if abs_d >= 20 or self.tier_changed:
            return "critical"
        if abs_d >= 10:
            return "high"
        if abs_d >= 5:
            return "medium"
        return "low"


@dataclass
class Anomaly:
    detector: str            # e.g. "sanctions_hit", "ownership_change"
    severity: str            # critical / high / medium / low
    title: str
    detail: str
    vendor_id: str = ""
    vendor_name: str = ""
    evidence: dict = field(default_factory=dict)


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio risk posture."""
    timestamp: str
    total_vendors: int
    tier_distribution: dict  # {"TIER_1": 3, "TIER_2": 5, ...}
    avg_score: float
    median_score: float
    max_score: float
    hard_stop_count: int
    elevated_count: int      # TIER_1 + TIER_2
    anomaly_count: int       # anomalies detected since last snapshot


# ---------------------------------------------------------------------------
#  1. Score Drift Detector
# ---------------------------------------------------------------------------

class ScoreDriftDetector:
    """Re-scores a vendor and measures the probability delta."""

    ALERT_THRESHOLD_PP = 5.0   # fire alert if |delta| >= 5pp

    def check(self, vendor_id: str) -> Optional[DriftResult]:
        if not HAS_SCORING:
            return None

        vendor = db.get_vendor(vendor_id)
        if not vendor:
            return None

        prev_score_row = db.get_latest_score(vendor_id)
        if not prev_score_row:
            return None  # no baseline to compare against

        prev_full = prev_score_row.get("full_result", {})
        if isinstance(prev_full, str):
            import json
            prev_full = json.loads(prev_full)

        prev_cal = prev_full.get("calibrated", prev_full)
        prev_prob = prev_cal.get("calibrated_probability", 0)
        prev_tier = prev_cal.get("calibrated_tier", "UNKNOWN")
        prev_contributions = {
            c["factor"]: c["signed_contribution"]
            for c in prev_cal.get("contributions", [])
        }

        # Build fresh input from stored vendor data
        vendor_data = vendor.get("data", vendor)
        if isinstance(vendor_data, str):
            import json
            vendor_data = json.loads(vendor_data)

        try:
            inp = build_vendor_input(vendor_data)
            result = score_vendor(inp)
        except Exception as e:
            print(f"[drift] scoring failed for {vendor_id}: {e}")
            return None

        cur_cal = result.get("calibrated", result)
        cur_prob = cur_cal.get("calibrated_probability", 0)
        cur_tier = cur_cal.get("calibrated_tier", "UNKNOWN")
        cur_contributions = {
            c["factor"]: c["signed_contribution"]
            for c in cur_cal.get("contributions", [])
        }

        delta_pp = (cur_prob - prev_prob) * 100

        # Find factors with largest change
        all_factors = set(prev_contributions) | set(cur_contributions)
        factor_deltas = []
        for f in all_factors:
            old_c = prev_contributions.get(f, 0)
            new_c = cur_contributions.get(f, 0)
            d = (new_c - old_c) * 100
            if abs(d) > 0.5:
                factor_deltas.append({
                    "factor": f,
                    "previous_pp": round(old_c * 100, 2),
                    "current_pp": round(new_c * 100, 2),
                    "delta_pp": round(d, 2)
                })
        factor_deltas.sort(key=lambda x: abs(x["delta_pp"]), reverse=True)

        return DriftResult(
            vendor_id=vendor_id,
            vendor_name=vendor.get("name", ""),
            previous_score=round(prev_prob * 100, 1),
            current_score=round(cur_prob * 100, 1),
            delta_pp=round(delta_pp, 1),
            previous_tier=prev_tier,
            current_tier=cur_tier,
            tier_changed=prev_tier != cur_tier,
            factors_changed=factor_deltas[:5],
            timestamp=datetime.utcnow().isoformat()
        )


# ---------------------------------------------------------------------------
#  2. Deterministic Anomaly Detectors
# ---------------------------------------------------------------------------

def detect_sanctions_hit(vendor_id: str, findings: list, prev_findings: list) -> list[Anomaly]:
    """Detect new sanctions list matches that didn't exist before."""
    anomalies = []
    sanctions_sources = {
        "ofac_sdn", "eu_sanctions", "uk_hmt", "un_sanctions",
        "trade_csl", "opensanctions"
    }

    prev_sanctions = {
        f.get("title", "") for f in prev_findings
        if f.get("source", "").lower().replace("-", "_") in sanctions_sources
        or "sanction" in f.get("source", "").lower()
    }

    for f in findings:
        source = f.get("source", "").lower().replace("-", "_")
        is_sanctions = (source in sanctions_sources
                        or "sanction" in source
                        or "SDN" in f.get("title", ""))
        if is_sanctions and f.get("title", "") not in prev_sanctions:
            anomalies.append(Anomaly(
                detector="sanctions_hit",
                severity="critical",
                title=f"New sanctions match: {f.get('title', 'Unknown')}",
                detail=f"Source: {f.get('source', 'unknown')}. {f.get('detail', '')}",
                vendor_id=vendor_id,
                evidence={"finding": f}
            ))
    return anomalies


def detect_ownership_change(vendor_id: str, current_data: dict, prev_data: dict) -> list[Anomaly]:
    """Detect changes in ownership structure."""
    anomalies = []

    cur_owner = current_data.get("ownership", {})
    prev_owner = prev_data.get("ownership", {})

    # State-owned status changed
    if cur_owner.get("state_owned") and not prev_owner.get("state_owned"):
        anomalies.append(Anomaly(
            detector="ownership_change",
            severity="critical",
            title="Entity now classified as state-owned",
            detail="Ownership data indicates state ownership where none was previously recorded.",
            vendor_id=vendor_id,
            evidence={"current": cur_owner, "previous": prev_owner}
        ))

    # Beneficial ownership resolution dropped significantly
    cur_pct = cur_owner.get("ownership_pct_resolved", 1.0)
    prev_pct = prev_owner.get("ownership_pct_resolved", 1.0)
    if prev_pct > 0.5 and cur_pct < 0.3:
        anomalies.append(Anomaly(
            detector="ownership_change",
            severity="high",
            title="Beneficial ownership transparency decreased",
            detail=f"Resolved ownership dropped from {prev_pct:.0%} to {cur_pct:.0%}.",
            vendor_id=vendor_id,
            evidence={"previous_pct": prev_pct, "current_pct": cur_pct}
        ))

    # Shell layers increased
    cur_shells = cur_owner.get("shell_layers", 0)
    prev_shells = prev_owner.get("shell_layers", 0)
    if cur_shells > prev_shells + 1:
        anomalies.append(Anomaly(
            detector="ownership_change",
            severity="high",
            title=f"Shell company layers increased ({prev_shells} to {cur_shells})",
            detail="Additional corporate layers detected in ownership chain.",
            vendor_id=vendor_id
        ))

    # PEP connection appeared
    if cur_owner.get("pep_connection") and not prev_owner.get("pep_connection"):
        anomalies.append(Anomaly(
            detector="ownership_change",
            severity="high",
            title="Politically exposed person (PEP) connection detected",
            detail="New PEP linkage found in ownership or executive structure.",
            vendor_id=vendor_id
        ))

    return anomalies


def detect_media_spike(vendor_id: str, findings: list, prev_findings: list) -> list[Anomaly]:
    """Detect 3x+ spike in adverse media volume."""
    anomalies = []
    media_sources = {"google_news", "gdelt_media", "gdelt"}

    prev_media = [f for f in prev_findings
                  if f.get("source", "").lower().replace("-", "_") in media_sources]
    cur_media = [f for f in findings
                 if f.get("source", "").lower().replace("-", "_") in media_sources]

    prev_count = max(len(prev_media), 1)  # avoid division by zero
    cur_count = len(cur_media)
    ratio = cur_count / prev_count

    if cur_count >= 5 and ratio >= 3.0:
        anomalies.append(Anomaly(
            detector="media_spike",
            severity="high",
            title=f"Adverse media volume spiked {ratio:.1f}x ({prev_count} to {cur_count})",
            detail=f"Detected {cur_count} adverse media findings vs {len(prev_media)} previously. "
                   f"Review for emerging reputational or legal risks.",
            vendor_id=vendor_id,
            evidence={"previous_count": len(prev_media), "current_count": cur_count,
                      "ratio": round(ratio, 1)}
        ))

    # Also flag if any individual media finding is CRITICAL severity
    for f in cur_media:
        if f.get("severity") == "critical":
            title = f.get("title", "Unknown")
            if not any(pf.get("title") == title for pf in prev_media):
                anomalies.append(Anomaly(
                    detector="media_spike",
                    severity="critical",
                    title=f"Critical adverse media: {title[:80]}",
                    detail=f.get("detail", ""),
                    vendor_id=vendor_id,
                    evidence={"finding": f}
                ))

    return anomalies


def detect_financial_downgrade(vendor_id: str, current_data: dict, prev_data: dict) -> list[Anomaly]:
    """Detect significant financial stability deterioration."""
    anomalies = []

    cur_fin = current_data.get("financial_stability", 0.2)
    prev_fin = prev_data.get("financial_stability", 0.2)

    # If financial risk score jumped above 0.6 (was below 0.4)
    if isinstance(cur_fin, (int, float)) and isinstance(prev_fin, (int, float)):
        if cur_fin > 0.6 and prev_fin < 0.4:
            anomalies.append(Anomaly(
                detector="financial_downgrade",
                severity="high",
                title="Financial stability deteriorated significantly",
                detail=f"Financial risk score moved from {prev_fin:.2f} to {cur_fin:.2f}. "
                       f"Review for bankruptcy risk, covenant violations, or credit downgrades.",
                vendor_id=vendor_id,
                evidence={"previous": prev_fin, "current": cur_fin}
            ))

    return anomalies


def detect_debarment(vendor_id: str, findings: list, prev_findings: list) -> list[Anomaly]:
    """Detect new debarment/exclusion list matches."""
    anomalies = []
    exclusion_sources = {"sam_exclusions", "dod_sam_exclusions", "worldbank_debarred"}

    prev_exclusions = {f.get("title", "") for f in prev_findings
                       if f.get("source", "").lower().replace("-", "_") in exclusion_sources}

    for f in findings:
        source = f.get("source", "").lower().replace("-", "_")
        if source in exclusion_sources and f.get("title", "") not in prev_exclusions:
            anomalies.append(Anomaly(
                detector="debarment",
                severity="critical",
                title=f"New exclusion/debarment: {f.get('title', 'Unknown')}",
                detail=f"Source: {f.get('source')}. {f.get('detail', '')}",
                vendor_id=vendor_id,
                evidence={"finding": f}
            ))

    return anomalies


class AnomalyDetectorBank:
    """Runs all deterministic anomaly detectors and returns combined results."""

    DETECTORS = [
        detect_sanctions_hit,
        detect_media_spike,
        detect_debarment,
    ]

    STRUCTURAL_DETECTORS = [
        detect_ownership_change,
        detect_financial_downgrade,
    ]

    def run_all(self, vendor_id: str,
                current_findings: list, prev_findings: list,
                current_data: dict = None, prev_data: dict = None) -> list[Anomaly]:
        """Run all detectors and return combined anomaly list."""
        anomalies = []

        for detector in self.DETECTORS:
            try:
                results = detector(vendor_id, current_findings, prev_findings)
                anomalies.extend(results)
            except Exception as e:
                print(f"[anomaly] {detector.__name__} error for {vendor_id}: {e}")

        if current_data and prev_data:
            for detector in self.STRUCTURAL_DETECTORS:
                try:
                    results = detector(vendor_id, current_data, prev_data)
                    anomalies.extend(results)
                except Exception as e:
                    print(f"[anomaly] {detector.__name__} error for {vendor_id}: {e}")

        return anomalies


# ---------------------------------------------------------------------------
#  3. Portfolio Analytics
# ---------------------------------------------------------------------------

class PortfolioAnalytics:
    """Aggregate portfolio risk posture and trend calculations."""

    @staticmethod
    def current_snapshot() -> PortfolioSnapshot:
        """Generate a point-in-time snapshot of portfolio risk posture."""
        vendors = db.list_vendors(limit=10000)
        scores = []
        tier_dist = {}
        hard_stops = 0

        for v in vendors:
            latest = db.get_latest_score(v["id"])
            if not latest:
                continue

            full = latest.get("full_result", {})
            if isinstance(full, str):
                import json
                full = json.loads(full)

            cal = full.get("calibrated", full)
            prob = cal.get("calibrated_probability", 0)
            tier = cal.get("calibrated_tier", "UNKNOWN")
            is_stop = latest.get("is_hard_stop", False)

            scores.append(prob * 100)
            tier_dist[tier] = tier_dist.get(tier, 0) + 1
            if is_stop:
                hard_stops += 1

        if not scores:
            scores = [0]

        sorted_scores = sorted(scores)
        n = len(sorted_scores)
        median = sorted_scores[n // 2] if n % 2 else (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2

        elevated = sum(v for k, v in tier_dist.items()
                       if k in ("TIER_1_HARD_STOP", "TIER_2_ELEVATED"))

        # Count recent anomalies (last 7 days)
        recent_alerts = db.list_alerts(limit=500, unresolved_only=True)
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        recent_anomalies = sum(1 for a in recent_alerts
                               if a.get("created_at", "") >= week_ago)

        return PortfolioSnapshot(
            timestamp=datetime.utcnow().isoformat(),
            total_vendors=len(vendors),
            tier_distribution=tier_dist,
            avg_score=round(sum(scores) / len(scores), 1),
            median_score=round(median, 1),
            max_score=round(max(scores), 1),
            hard_stop_count=hard_stops,
            elevated_count=elevated,
            anomaly_count=recent_anomalies
        )

    @staticmethod
    def score_history(vendor_id: str, limit: int = 30) -> list[dict]:
        """Get score history for a single vendor (for trend chart)."""
        rows = db.get_score_history(vendor_id, limit=limit)
        return [
            {
                "timestamp": r.get("scored_at", ""),
                "score": r.get("composite_score", 0),
                "probability": r.get("calibrated_probability", 0),
                "tier": r.get("calibrated_tier", ""),
            }
            for r in rows
        ]

    @staticmethod
    def portfolio_trend(days: int = 30) -> list[dict]:
        """
        Get daily portfolio posture over time.
        Returns one data point per day with avg/max/elevated counts.
        """
        monitoring_history = db.get_all_monitoring_history(limit=days * 50)

        # Group by date
        daily = {}
        for entry in monitoring_history:
            date = entry.get("checked_at", "")[:10]
            if not date:
                continue
            if date not in daily:
                daily[date] = {
                    "date": date,
                    "checks": 0,
                    "risk_changes": 0,
                    "new_findings_total": 0,
                }
            daily[date]["checks"] += 1
            if entry.get("risk_changed"):
                daily[date]["risk_changes"] += 1
            daily[date]["new_findings_total"] += entry.get("new_findings_count", 0)

        return sorted(daily.values(), key=lambda d: d["date"])
