"""
Xiphos Continuous Monitoring Agent

Runs periodic OSINT re-enrichment on tracked vendors and generates
alerts when risk signals change. Designed to run as:
  1. A background thread in the Flask server
  2. A standalone cron-compatible CLI: python monitor.py --run-once
  3. A scheduled task: python monitor.py --daemon --interval 86400
"""

import threading
import time
import argparse
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

# Import from existing modules
import db
try:
    from osint.enrichment import enrich_vendor
    HAS_OSINT = True
except ImportError:
    HAS_OSINT = False

try:
    from portfolio_intelligence import AnomalyDetectorBank
    HAS_PORTFOLIO_INTEL = True
except ImportError:
    HAS_PORTFOLIO_INTEL = False

from monitor_core import (
    diff_findings,
    emit_registry_mutation_alerts,
    is_registry_mutation_finding,
    fingerprint_finding,
    run_monitor_check,
)


@dataclass
class MonitoringResult:
    """Results from a single vendor monitoring check."""
    vendor_id: str
    vendor_name: str
    previous_risk: str        # Calibrated tier before monitoring
    current_risk: str         # Calibrated tier after monitoring
    risk_changed: bool
    new_findings: list        # Findings not seen in previous enrichment
    resolved_findings: list   # Findings no longer present
    new_risk_signals: list
    elapsed_ms: int


class VendorMonitor:
    """Background monitoring engine for continuous vendor re-enrichment."""

    def __init__(self, check_interval: int = 86400):
        """
        Args:
            check_interval: Seconds between checks per vendor (default 24h)
        """
        self.check_interval = check_interval
        self._running = False
        self._thread = None

    @staticmethod
    def _fingerprint_finding(finding: dict) -> str:
        """Generate a stable hash for a finding based on source, title, severity."""
        return fingerprint_finding(finding)

    @staticmethod
    def _is_registry_mutation_finding(finding: dict) -> bool:
        return is_registry_mutation_finding(finding)

    def _emit_registry_mutation_alerts(self, vendor_id: str, vendor_name: str, new_findings: list[dict]) -> None:
        emit_registry_mutation_alerts(vendor_id, vendor_name, new_findings)

    def _diff_findings(self, old_findings: list, new_findings: list) -> tuple:
        """
        Compare two sets of findings.

        Args:
            old_findings: Previous findings list
            new_findings: Current findings list

        Returns:
            (new_findings_list, resolved_findings_list)
        """
        return diff_findings(old_findings, new_findings)

    def check_vendor(self, vendor_id: str) -> Optional[MonitoringResult]:
        """
        Run enrichment and compare to last known state.

        Args:
            vendor_id: The vendor to check

        Returns:
            MonitoringResult if check succeeds, None if vendor not found or error
        """
        if not HAS_OSINT:
            return None

        # Get vendor from DB
        vendor = db.get_vendor(vendor_id)
        if not vendor:
            return None
        try:
            monitor_result = run_monitor_check(vendor, enrich_func=enrich_vendor)
        except Exception as e:
            print(f"Error enriching {vendor_id}: {e}")
            return None
        if not monitor_result:
            return None

        result = MonitoringResult(
            vendor_id=vendor_id,
            vendor_name=vendor["name"],
            previous_risk=str(monitor_result["previous_risk"]),
            current_risk=str(monitor_result["current_risk"]),
            risk_changed=bool(monitor_result["risk_changed"]),
            new_findings=list(monitor_result["new_findings"]),
            resolved_findings=list(monitor_result["resolved_findings"]),
            new_risk_signals=list(monitor_result["new_risk_signals"]),
            elapsed_ms=int(monitor_result["elapsed_ms"]),
        )

        # Run anomaly detectors (Phase 4)
        anomalies = []
        if HAS_PORTFOLIO_INTEL:
            try:
                bank = AnomalyDetectorBank()
                vendor_data = vendor.get("data", vendor)
                if isinstance(vendor_data, str):
                    import json as _json
                    vendor_data = _json.loads(vendor_data)
                previous = db.get_latest_enrichment(vendor_id)
                prev_data = previous.get("vendor_data", {}) if previous else {}
                anomalies = bank.run_all(
                    vendor_id, result.new_findings, previous.get("findings", []) if previous else [],
                    current_data=vendor_data, prev_data=prev_data
                )
                for a in anomalies:
                    db.save_anomaly(
                        vendor_id, vendor["name"], a.detector,
                        a.severity, a.title, a.detail,
                        str(a.evidence) if a.evidence else ""
                    )
            except Exception as e:
                print(f"[monitor] anomaly detection error for {vendor_id}: {e}")

        # Alert directly off the canonical score change from this monitoring run.
        score_delta = float(monitor_result["score_delta"])
        if score_delta >= 5.0:
            previous_score_pct = float(monitor_result["previous_score"])
            current_score_pct = float(monitor_result["current_score"])
            direction = "increased" if current_score_pct > previous_score_pct else "decreased"
            db.save_alert(
                vendor_id,
                vendor["name"],
                "high" if result.risk_changed else "medium",
                f"Score drift: {previous_score_pct}% -> {current_score_pct}% ({direction} {score_delta:.1f}pp)",
                f"Tier: {result.previous_risk} -> {result.current_risk}",
            )

        self._emit_registry_mutation_alerts(vendor_id, vendor["name"], result.new_findings)

        # Log monitoring check
        db.save_monitoring_log(
            vendor_id=vendor_id,
            previous_risk=result.previous_risk,
            current_risk=result.current_risk,
            risk_changed=result.risk_changed,
            new_findings_count=len(result.new_findings),
            resolved_findings_count=len(result.resolved_findings)
        )

        return result

    def check_all_vendors(self) -> list[MonitoringResult]:
        """
        Check all vendors that haven't been checked within check_interval.

        Returns:
            List of MonitoringResult objects
        """
        if not HAS_OSINT:
            return []

        vendors = db.list_vendors(limit=1000)
        cutoff_time = (datetime.utcnow() - timedelta(seconds=self.check_interval)).isoformat()

        results = []
        for vendor in vendors:
            # Get latest enrichment timestamp
            latest = db.get_latest_enrichment(vendor["id"])
            last_check = latest.get("enriched_at") if latest else None

            # Check if vendor needs re-enrichment
            if not last_check or last_check < cutoff_time:
                result = self.check_vendor(vendor["id"])
                if result:
                    results.append(result)

        return results

    def start_daemon(self):
        """Start background monitoring thread."""
        self._running = True
        self._thread = threading.Thread(target=self._daemon_loop, daemon=True)
        self._thread.start()
        print(f"Monitoring daemon started (interval: {self.check_interval}s)")

    def stop_daemon(self):
        """Stop background monitoring thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("Monitoring daemon stopped")

    def _daemon_loop(self):
        """Main daemon loop - runs continuously."""
        while self._running:
            try:
                results = self.check_all_vendors()

                # Generate alerts for risk changes
                for r in results:
                    if r.risk_changed:
                        severity = "critical" if r.current_risk in ("CRITICAL", "HIGH") else "high"
                        db.save_alert(
                            vendor_id=r.vendor_id,
                            entity_name=r.vendor_name,
                            severity=severity,
                            title=f"Risk tier changed: {r.previous_risk} → {r.current_risk}",
                            description=f"Monitoring detected risk level change. "
                                       f"New findings: {len(r.new_findings)}, "
                                       f"Resolved: {len(r.resolved_findings)}"
                        )

                    # Alert on new critical/high findings
                    for finding in r.new_findings:
                        if finding.get("severity") in ("critical", "high"):
                            db.save_alert(
                                vendor_id=r.vendor_id,
                                entity_name=r.vendor_name,
                                severity=finding.get("severity"),
                                title=f"[MONITOR] {finding.get('title', 'New finding')}",
                                description=finding.get("detail", "")
                            )

                if results:
                    print(f"[{datetime.utcnow().isoformat()}] "
                          f"Checked {len(results)} vendors, "
                          f"{sum(1 for r in results if r.risk_changed)} risk changes")

            except Exception as e:
                print(f"Error in monitoring loop: {e}")

            time.sleep(self.check_interval)


# CLI interface
def main():
    parser = argparse.ArgumentParser(
        description="Xiphos Monitoring Agent - Continuous vendor re-enrichment"
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run a single check cycle and exit"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Start as background daemon"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=86400,
        help="Check interval in seconds (default: 86400 = 24 hours)"
    )
    parser.add_argument(
        "--vendor",
        type=str,
        help="Check specific vendor ID only"
    )

    args = parser.parse_args()

    # Initialize database
    db.init_db()

    # Create monitor instance
    monitor = VendorMonitor(check_interval=args.interval)

    if args.vendor:
        # Check single vendor
        print(f"Checking vendor: {args.vendor}")
        result = monitor.check_vendor(args.vendor)
        if result:
            print(f"  Previous risk: {result.previous_risk}")
            print(f"  Current risk: {result.current_risk}")
            print(f"  Risk changed: {result.risk_changed}")
            print(f"  New findings: {len(result.new_findings)}")
            print(f"  Resolved findings: {len(result.resolved_findings)}")
            print(f"  New risk signals: {len(result.new_risk_signals)}")
            print(f"  Elapsed: {result.elapsed_ms}ms")
        else:
            print("  Error: vendor not found or OSINT not available")

    elif args.run_once:
        # Run single cycle
        print("Running single monitoring cycle...")
        results = monitor.check_all_vendors()
        print(f"Checked {len(results)} vendors")
        for r in results:
            if r.risk_changed:
                print(f"  {r.vendor_name}: {r.previous_risk} → {r.current_risk}")

    elif args.daemon:
        # Start daemon
        monitor.start_daemon()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
            monitor.stop_daemon()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
