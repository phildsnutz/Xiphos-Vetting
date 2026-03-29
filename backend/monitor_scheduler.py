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
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Optional

import db
from profiles import get_connector_list

try:
    from osint.enrichment import enrich_vendor
    HAS_OSINT = True
except ImportError:
    HAS_OSINT = False

from monitor_core import (
    SCORE_DELTA_ALERT_THRESHOLD,
    diff_findings,
    emit_registry_mutation_alerts,
    fingerprint_finding,
    is_registry_mutation_finding,
    run_monitor_check,
)

# Risk-tier-aware re-screening intervals
# Higher risk entities get more frequent monitoring
TIER_INTERVALS = {
    "TIER_1_PROHIBITED":         24,   # Legacy
    "TIER_1_DISQUALIFIED":       24,
    "TIER_1_CRITICAL_CONCERN":   24,
    "TIER_2_RESTRICTED":         72,   # Legacy
    "TIER_2_CAUTION":            72,
    "TIER_2_ELEVATED":           72,
    "TIER_3_CONDITIONAL":       168,   # Weekly
    "TIER_4_APPROVED":          720,   # Monthly
    "TIER_4_CLEAR":             720,
    "TIER_4_CRITICAL_QUALIFIED": 168,  # Weekly (qualified approval = watch closely)
}
DEFAULT_INTERVAL_HOURS = 168  # Weekly fallback

logger = logging.getLogger("xiphos.scheduler")


class MonitorScheduler:
    """Background scheduler for continuous vendor monitoring with tier-aware intervals."""

    def __init__(self, interval_hours: int = 168, email_config: dict = None):
        """
        Args:
            interval_hours: Default hours between re-screening (overridden by tier-specific intervals)
            email_config: Optional SMTP config for email alerts
                         {host, port, user, password, from_addr, to_addrs}
        """
        self.interval_hours = int(interval_hours)
        self.interval_seconds = int(interval_hours) * 3600
        self.email_config = email_config or {}
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

    @staticmethod
    def _fingerprint_finding(finding: dict) -> str:
        return fingerprint_finding(finding)

    @classmethod
    def _diff_findings(cls, old_findings: list[dict], new_findings: list[dict]) -> tuple[list[dict], list[dict]]:
        return diff_findings(old_findings, new_findings)

    @staticmethod
    def _is_registry_mutation_finding(finding: dict) -> bool:
        return is_registry_mutation_finding(finding)

    def _emit_registry_mutation_alerts(self, vendor_id: str, vendor_name: str, new_findings: list[dict]) -> None:
        emit_registry_mutation_alerts(vendor_id, vendor_name, new_findings)

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

        queued_total = len(vendor_ids) if vendor_ids else 0
        db.create_sweep(sweep_id, queued_total, status="queued")

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
        """Find vendors due for re-screening based on their risk tier.

        Each vendor's interval is determined by its current tier:
          TIER_1_PROHIBITED      -> every 24h  (daily)
          TIER_2_RESTRICTED      -> every 72h  (3 days)
          TIER_3_CONDITIONAL     -> every 168h (weekly)
          TIER_4_APPROVED        -> every 720h (monthly)
          TIER_4_CRITICAL_QUALIFIED -> every 168h (weekly)
        Vendors with no score yet or no monitoring history are always stale.
        """
        vendors = db.list_vendors(limit=10000)
        now = datetime.utcnow()

        stale = []
        for vendor in vendors:
            # Determine per-vendor interval from current tier
            latest_score = db.get_latest_score(vendor["id"])
            if latest_score:
                tier = latest_score.get("calibrated", {}).get("calibrated_tier", "")
                interval_hours = TIER_INTERVALS.get(tier, self.interval_hours)
            else:
                interval_hours = self.interval_hours

            cutoff = now - timedelta(hours=interval_hours)

            latest_monitoring = db.get_monitoring_history(vendor["id"], limit=1)
            if not latest_monitoring:
                stale.append(vendor)
                continue

            last_check_raw = latest_monitoring[0].get("checked_at")
            if not last_check_raw:
                stale.append(vendor)
                continue

            # PostgreSQL returns native datetime objects; SQLite returns strings
            if isinstance(last_check_raw, datetime):
                last_check = last_check_raw
            elif isinstance(last_check_raw, str):
                try:
                    last_check = datetime.fromisoformat(last_check_raw.replace(" ", "T"))
                except ValueError:
                    last_check = datetime.fromisoformat(last_check_raw)
            else:
                # Unexpected type, treat as stale
                stale.append(vendor)
                continue

            if last_check < cutoff:
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

            # Mark the queued sweep as running once work begins.
            db.start_sweep(sweep_id, len(vendors_to_check))

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

        try:
            result = run_monitor_check(
                vendor,
                connector_resolver=get_connector_list,
                enrich_func=enrich_vendor,
            )
            if not result:
                return None

            # Generate alert if tier changed
            if result["risk_changed"]:
                new_tier = str(result["new_tier"])
                severity = "critical" if "TIER_1" in new_tier else "high" if "TIER_2" in new_tier else "medium"
                alert_title = f"Risk Tier Change: {result['old_tier']} -> {result['new_tier']}"
                alert_desc = (
                    f"Continuous monitoring detected risk tier change for {result['vendor_name']}. "
                    f"Old: {result['old_tier']} ({result['old_score']}%), New: {result['new_tier']} ({result['new_score']}%). "
                    f"Re-screening via profile '{result['profile']}'."
                )
                db.save_alert(
                    vendor_id=result["vendor_id"],
                    entity_name=result["vendor_name"],
                    severity=severity,
                    title=alert_title,
                    description=alert_desc,
                )
                self._send_alert_email(result["vendor_name"], alert_title, alert_desc, severity)

            # Generate alert for significant score movement even without tier change
            elif result["score_delta_alert"]:
                direction = "increased" if float(result["new_score"]) > float(result["old_score"]) else "decreased"
                alert_title = f"Score Delta Alert: {result['vendor_name']} {direction} {result['score_delta']} pts"
                alert_desc = (
                    f"Risk score {direction} from {result['old_score']}% to {result['new_score']}% "
                    f"(delta: {result['score_delta']} pts, threshold: {SCORE_DELTA_ALERT_THRESHOLD}). "
                    f"Tier unchanged at {result['new_tier']}."
                )
                db.save_alert(
                    vendor_id=result["vendor_id"],
                    entity_name=result["vendor_name"],
                    severity="medium",
                    title=alert_title,
                    description=alert_desc,
                )
                self._send_alert_email(result["vendor_name"], alert_title, alert_desc, "medium")

            self._emit_registry_mutation_alerts(
                str(result["vendor_id"]),
                str(result["vendor_name"]),
                list(result["new_findings"]),
            )

            # Log monitoring check
            db.save_monitoring_log(
                vendor_id=str(result["vendor_id"]),
                previous_risk=str(result["old_tier"]),
                current_risk=str(result["new_tier"]),
                risk_changed=bool(result["risk_changed"]),
                new_findings_count=len(result["new_findings"]),
                resolved_findings_count=len(result["resolved_findings"]),
            )

            logger.info(
                "Checked %s: %s -> %s (score %d -> %d, delta %.1f)",
                result["vendor_name"],
                result["old_tier"],
                result["new_tier"],
                int(result["old_score"]),
                int(result["new_score"]),
                float(result["score_delta"]),
            )

            return result

        except Exception as e:
            vendor_id = vendor.get("id", "<unknown>")
            print(f"[Scheduler] Error checking vendor {vendor_id}: {e}")
            return None

    def _send_alert_email(self, vendor_name: str, title: str, description: str, severity: str) -> None:
        """Send email alert for risk changes and score delta events.

        Requires email_config with keys: host, port, user, password, from_addr, to_addrs.
        Silently skips if email is not configured.
        """
        if not self.email_config or not self.email_config.get("to_addrs"):
            return

        try:
            severity_colors = {
                "critical": "#dc2626", "high": "#ea580c",
                "medium": "#d97706", "low": "#2563eb", "info": "#6b7280",
            }
            color = severity_colors.get(severity, "#6b7280")

            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[Xiphos {severity.upper()}] {title}"
            msg["From"] = self.email_config.get("from_addr", "alerts@xiphos.dev")
            msg["To"] = ", ".join(self.email_config["to_addrs"])

            text_body = f"Xiphos Continuous Monitoring Alert\n\nVendor: {vendor_name}\nSeverity: {severity.upper()}\n\n{description}"

            html_body = f"""<html><body style="font-family:system-ui,sans-serif;color:#1e293b;">
<div style="border-left:4px solid {color};padding:12px 16px;margin:16px 0;background:#f8fafc;">
  <h2 style="margin:0 0 8px;color:{color};">[{severity.upper()}] {title}</h2>
  <p style="margin:0 0 4px;"><strong>Vendor:</strong> {vendor_name}</p>
  <p style="margin:0;">{description}</p>
</div>
<p style="font-size:12px;color:#94a3b8;">Xiphos Continuous Monitoring v5.2 | Automated alert</p>
</body></html>"""

            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            host = self.email_config.get("host", "smtp.gmail.com")
            port = int(self.email_config.get("port", 587))
            user = self.email_config.get("user", "")
            password = self.email_config.get("password", "")

            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls()
                if user and password:
                    server.login(user, password)
                server.send_message(msg)

            logger.info("Alert email sent for %s: %s", vendor_name, title)

        except Exception as e:
            logger.warning("Failed to send alert email for %s: %s", vendor_name, e)

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
                import traceback
                print(f"[Scheduler] Error in scheduler loop: {e}")
                traceback.print_exc()

            # Sleep for interval before next check
            time.sleep(int(self.interval_seconds))


# Global scheduler instance (initialized by server.py)
_scheduler: Optional[MonitorScheduler] = None


def get_scheduler() -> Optional[MonitorScheduler]:
    """Get the global scheduler instance."""
    return _scheduler


def init_scheduler(interval_hours: int = 168, email_config: dict = None) -> MonitorScheduler:
    """Initialize and start the global scheduler.

    Args:
        interval_hours: Default check interval (overridden per-vendor by tier).
        email_config: Optional SMTP config dict with keys:
                      host, port, user, password, from_addr, to_addrs
    """
    global _scheduler
    _scheduler = MonitorScheduler(interval_hours=interval_hours, email_config=email_config)
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    """Stop the global scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
