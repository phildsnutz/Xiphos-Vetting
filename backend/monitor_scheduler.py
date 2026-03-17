"""
Xiphos Continuous Monitoring Scheduler

Provides non-blocking background monitoring with:
- Periodic re-screening of vendors via OSINT enrichment
- Automatic tier change detection and alert generation
- Sweep progress tracking and async polling
- Rate limiting to avoid overloading external APIs

Usage:
    from monitor_scheduler import MonitorScheduler
    scheduler = MonitorScheduler(interval_hours=168)  # weekly
    scheduler.start()
    # ... server runs ...
    scheduler.stop()

Or trigger a sweep manually:
    sweep_id = scheduler.trigger_sweep()
    # Poll /api/monitor/sweep/{sweep_id} for results
"""

import threading
import time
import uuid
import json
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import asdict

import db
from scoring import score_vendor
from profiles import get_connector_list

try:
    from osint.enrichment import enrich_vendor
    HAS_OSINT = True
except ImportError:
    HAS_OSINT = False


class MonitorScheduler:
    """Background scheduler for continuous vendor monitoring."""

    def __init__(self, interval_hours: int = 168):
        """
        Args:
            interval_hours: Hours between re-screening each vendor (default: 168 = 1 week)
        """
        self.interval_hours = interval_hours
        self.interval_seconds = interval_hours * 3600
        self.running = False
        self._thread = None
        self._active_sweeps = {}  # sweep_id -> metadata
        self._sweep_lock = threading.Lock()

    def start(self):
        """Start background monitoring thread."""
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        print(f"[Scheduler] Monitoring scheduler started (interval: {self.interval_hours}h)")

    def stop(self):
        """Stop background monitoring thread."""
        if not self.running:
            return
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("[Scheduler] Monitoring scheduler stopped")

    def trigger_sweep(self, vendor_ids: Optional[list[str]] = None) -> str:
        """
        Trigger an immediate monitoring sweep.

        Args:
            vendor_ids: Specific vendor IDs to sweep, or None for all due vendors

        Returns:
            sweep_id for polling progress
        """
        sweep_id = str(uuid.uuid4())

        with self._sweep_lock:
            self._active_sweeps[sweep_id] = {
                "triggered_at": datetime.utcnow().isoformat(),
                "vendor_ids": vendor_ids,
                "status": "queued",
            }

        # Kick off in background thread
        thread = threading.Thread(
            target=self._execute_sweep,
            args=(sweep_id, vendor_ids),
            daemon=True
        )
        thread.start()

        return sweep_id

    def get_sweep_status(self, sweep_id: str) -> dict:
        """Get current status of a monitoring sweep."""
        # Check database first for completed/historical sweeps
        db_sweep = db.get_sweep(sweep_id)
        if db_sweep:
            return {
                "sweep_id": sweep_id,
                "status": db_sweep["status"],
                "total_vendors": db_sweep["total_vendors"],
                "processed": db_sweep["processed"],
                "risk_changes": db_sweep["risk_changes"],
                "new_alerts": db_sweep["new_alerts"],
                "started_at": db_sweep["started_at"],
                "completed_at": db_sweep["completed_at"],
            }

        # Check in-memory active sweeps
        with self._sweep_lock:
            if sweep_id in self._active_sweeps:
                return {
                    "sweep_id": sweep_id,
                    "status": self._active_sweeps[sweep_id].get("status", "unknown"),
                    "triggered_at": self._active_sweeps[sweep_id].get("triggered_at"),
                }

        return {"sweep_id": sweep_id, "status": "not_found"}

    def get_stale_vendors(self) -> list[dict]:
        """Find vendors not monitored within the interval."""
        vendors = db.list_vendors(limit=10000)
        cutoff_time = datetime.utcnow() - timedelta(seconds=self.interval_seconds)

        stale = []
        for vendor in vendors:
            latest_monitoring = db.get_monitoring_history(vendor["id"], limit=1)
            if not latest_monitoring:
                # Never monitored
                stale.append(vendor)
            else:
                last_check_str = latest_monitoring[0].get("checked_at")
                if not last_check_str:
                    stale.append(vendor)
                else:
                    # Parse the datetime string from database (format: YYYY-MM-DD HH:MM:SS)
                    try:
                        last_check = datetime.fromisoformat(last_check_str.replace(" ", "T"))
                    except ValueError:
                        # Fallback: try direct parsing
                        last_check = datetime.fromisoformat(last_check_str)

                    if last_check < cutoff_time:
                        stale.append(vendor)

        return stale

    def run_sweep(self, vendor_ids: Optional[list[str]] = None) -> dict:
        """
        Synchronous sweep execution (for testing or standalone use).

        Args:
            vendor_ids: Specific vendor IDs to sweep, or None for all due vendors

        Returns:
            Summary dict with:
            - vendors_checked
            - risk_changes (list of {vendor_id, vendor_name, old_tier, new_tier})
            - new_alerts_count
            - elapsed_seconds
        """
        t0 = time.time()
        summary = {
            "vendors_checked": 0,
            "risk_changes": [],
            "new_alerts_count": 0,
            "elapsed_seconds": 0,
        }

        if not HAS_OSINT:
            return summary

        # Determine which vendors to check
        if vendor_ids:
            vendors_to_check = [db.get_vendor(vid) for vid in vendor_ids]
            vendors_to_check = [v for v in vendors_to_check if v]
        else:
            vendors_to_check = self.get_stale_vendors()

        # Process each vendor
        for vendor in vendors_to_check:
            try:
                result = self._check_vendor(vendor)
                if result:
                    summary["vendors_checked"] += 1
                    if result["risk_changed"]:
                        summary["risk_changes"].append({
                            "vendor_id": vendor["id"],
                            "vendor_name": vendor["name"],
                            "old_tier": result["old_tier"],
                            "new_tier": result["new_tier"],
                        })
                        summary["new_alerts_count"] += 1
            except Exception as e:
                print(f"[Scheduler] Error checking {vendor['id']}: {e}")
                continue

            # Rate limit: 2 seconds between vendors
            time.sleep(2)

        summary["elapsed_seconds"] = time.time() - t0
        return summary

    def _execute_sweep(self, sweep_id: str, vendor_ids: Optional[list[str]] = None) -> None:
        """Execute a sweep in background (called from trigger_sweep)."""
        if not HAS_OSINT:
            db.update_sweep_progress(sweep_id, 0, 0, 0, "failed")
            return

        try:
            # Determine vendors
            if vendor_ids:
                vendors_to_check = [db.get_vendor(vid) for vid in vendor_ids]
                vendors_to_check = [v for v in vendors_to_check if v]
            else:
                vendors_to_check = self.get_stale_vendors()

            # Create sweep record
            db.create_sweep(sweep_id, len(vendors_to_check))

            # Mark as running
            with self._sweep_lock:
                if sweep_id in self._active_sweeps:
                    self._active_sweeps[sweep_id]["status"] = "running"

            # Process vendors
            processed = 0
            risk_changes = 0
            new_alerts = 0

            for vendor in vendors_to_check:
                try:
                    result = self._check_vendor(vendor)
                    if result:
                        processed += 1
                        if result["risk_changed"]:
                            risk_changes += 1
                            new_alerts += 1  # One alert per risk change
                except Exception as e:
                    print(f"[Scheduler] Error in sweep {sweep_id} for {vendor['id']}: {e}")
                    continue

                # Update progress
                db.update_sweep_progress(sweep_id, processed, risk_changes, new_alerts, "running")

                # Rate limit
                time.sleep(2)

            # Mark complete
            db.complete_sweep(sweep_id)

            with self._sweep_lock:
                if sweep_id in self._active_sweeps:
                    self._active_sweeps[sweep_id]["status"] = "completed"

        except Exception as e:
            print(f"[Scheduler] Error executing sweep {sweep_id}: {e}")
            db.update_sweep_progress(sweep_id, 0, 0, 0, "failed")
            with self._sweep_lock:
                if sweep_id in self._active_sweeps:
                    self._active_sweeps[sweep_id]["status"] = "failed"

    def _check_vendor(self, vendor: dict) -> Optional[dict]:
        """
        Check a single vendor for risk tier changes.

        Args:
            vendor: Vendor dict from database

        Returns:
            Result dict with risk_changed, old_tier, new_tier; or None on error
        """
        if not HAS_OSINT:
            return None

        vendor_id = vendor["id"]
        vendor_name = vendor["name"]
        vendor_country = vendor["country"]
        profile = vendor.get("profile", "defense_acquisition")

        try:
            # Get current score tier
            current_score = db.get_latest_score(vendor_id)
            old_tier = current_score.get("calibrated", {}).get("calibrated_tier", "unknown") if current_score else "unknown"

            # Get profile-specific connectors
            connectors = get_connector_list(profile)

            # Run fresh enrichment
            enrichment = enrich_vendor(
                vendor_name=vendor_name,
                country=vendor_country,
                connectors=connectors,
                parallel=True,
                timeout=60
            )

            # Save enrichment
            db.save_enrichment(vendor_id, enrichment)

            # Re-score with updated data
            vendor_input = vendor.get("vendor_input", {})
            score_result = score_vendor(vendor_input, profile=profile)

            # Convert dataclass to dict format expected by save_score()
            score_dict = {
                "calibrated": {
                    "calibrated_probability": score_result.calibrated_probability,
                    "calibrated_tier": score_result.calibrated_tier,
                    "interval": {
                        "lower": score_result.interval_lower,
                        "upper": score_result.interval_upper,
                        "coverage": score_result.interval_coverage,
                    }
                },
                "composite_score": score_result.composite_score,
                "is_hard_stop": score_result.calibrated_tier == "hard_stop",
            }

            # Save new score
            db.save_score(vendor_id, score_dict)

            # Compare tiers
            new_tier = score_result.calibrated_tier
            risk_changed = old_tier != new_tier

            # Generate alert if tier changed
            if risk_changed:
                severity = "critical" if new_tier == "hard_stop" else "high" if new_tier == "elevated" else "medium"
                db.save_alert(
                    vendor_id=vendor_id,
                    entity_name=vendor_name,
                    severity=severity,
                    title=f"Risk Tier Change: {old_tier} → {new_tier}",
                    description=f"Continuous monitoring detected risk tier change. "
                                f"Old: {old_tier}, New: {new_tier}. "
                                f"Re-screening via profile '{profile}'."
                )

            # Log monitoring check
            db.save_monitoring_log(
                vendor_id=vendor_id,
                previous_risk=old_tier,
                current_risk=new_tier,
                risk_changed=risk_changed,
                new_findings_count=enrichment.get("summary", {}).get("findings_total", 0),
                resolved_findings_count=0
            )

            return {
                "vendor_id": vendor_id,
                "risk_changed": risk_changed,
                "old_tier": old_tier,
                "new_tier": new_tier,
            }

        except Exception as e:
            print(f"[Scheduler] Error checking vendor {vendor_id}: {e}")
            return None

    def _scheduler_loop(self) -> None:
        """Main scheduler loop - runs background sweep periodically."""
        while self.running:
            try:
                # Find stale vendors and trigger sweep
                stale = self.get_stale_vendors()
                if stale:
                    sweep_id = str(uuid.uuid4())
                    vendor_ids = [v["id"] for v in stale]
                    print(f"[Scheduler] Triggering background sweep {sweep_id} for {len(vendor_ids)} vendors")
                    self._execute_sweep(sweep_id, vendor_ids)

            except Exception as e:
                print(f"[Scheduler] Error in scheduler loop: {e}")

            # Sleep for interval before next check
            time.sleep(self.interval_seconds)


# Global scheduler instance (initialized by server.py)
_scheduler: Optional[MonitorScheduler] = None


def get_scheduler() -> Optional[MonitorScheduler]:
    """Get the global scheduler instance."""
    return _scheduler


def init_scheduler(interval_hours: int = 168) -> MonitorScheduler:
    """Initialize and start the global scheduler."""
    global _scheduler
    _scheduler = MonitorScheduler(interval_hours=interval_hours)
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    """Stop the global scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
