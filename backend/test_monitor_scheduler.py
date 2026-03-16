#!/usr/bin/env python3
"""
Test suite for the monitoring scheduler module.

Tests database integration, sweep execution, and status tracking.
"""

import sys
import time
import json
import sqlite3
import os
from datetime import datetime, timedelta

# Import modules
import db
from monitor_scheduler import MonitorScheduler, init_scheduler, get_scheduler

def test_db_init():
    """Test database initialization with new tables."""
    print("\n[Test] Database initialization...")

    # Clean up old test database if it exists
    db_path = db.get_db_path()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except:
            pass

    db.init_db()

    # Verify tables exist
    conn = sqlite3.connect(db.get_db_path())
    cursor = conn.cursor()

    # Check monitor_schedules table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='monitor_schedules'")
    assert cursor.fetchone() is not None, "monitor_schedules table not created"

    # Check monitor_config table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='monitor_config'")
    assert cursor.fetchone() is not None, "monitor_config table not created"

    conn.close()
    print("  ✓ Tables created successfully")


def test_monitor_config():
    """Test monitoring configuration functions."""
    print("\n[Test] Monitoring configuration...")

    # Set and get config
    db.set_monitor_config("test_key", "test_value")
    value = db.get_monitor_config("test_key")
    assert value == "test_value", f"Config value mismatch: {value}"

    # Test default value
    missing = db.get_monitor_config("missing_key", "default")
    assert missing == "default", "Default value not returned"

    # Update config
    db.set_monitor_config("test_key", "updated_value")
    value = db.get_monitor_config("test_key")
    assert value == "updated_value", "Config update failed"

    print("  ✓ Configuration functions work correctly")


def test_sweep_lifecycle():
    """Test sweep creation, progress tracking, and completion."""
    print("\n[Test] Sweep lifecycle...")

    sweep_id = "test-sweep-001"

    # Create sweep
    db.create_sweep(sweep_id, 5)
    sweep = db.get_sweep(sweep_id)
    assert sweep is not None, "Sweep not created"
    assert sweep["sweep_id"] == sweep_id, "Sweep ID mismatch"
    assert sweep["status"] == "running", "Sweep status should be 'running'"
    assert sweep["total_vendors"] == 5, "Total vendors mismatch"
    print("  ✓ Sweep creation works")

    # Update progress
    db.update_sweep_progress(sweep_id, 2, 1, 1, "running")
    sweep = db.get_sweep(sweep_id)
    assert sweep["processed"] == 2, "Processed count mismatch"
    assert sweep["risk_changes"] == 1, "Risk changes mismatch"
    print("  ✓ Progress update works")

    # Complete sweep
    db.complete_sweep(sweep_id)
    sweep = db.get_sweep(sweep_id)
    assert sweep["status"] == "completed", "Sweep status should be 'completed'"
    assert sweep["completed_at"] is not None, "Completed timestamp missing"
    print("  ✓ Sweep completion works")

    # Get latest sweep
    latest = db.get_latest_sweep()
    assert latest is not None, "Latest sweep not found"
    assert latest["sweep_id"] == sweep_id, "Latest sweep ID mismatch"
    print("  ✓ Latest sweep retrieval works")


def test_scheduler_initialization():
    """Test scheduler initialization."""
    print("\n[Test] Scheduler initialization...")

    scheduler = MonitorScheduler(interval_hours=24)
    assert scheduler.interval_hours == 24, "Interval hours mismatch"
    assert scheduler.interval_seconds == 24 * 3600, "Interval seconds mismatch"
    assert not scheduler.running, "Scheduler should not be running initially"
    print("  ✓ Scheduler instantiation works")


def test_stale_vendors():
    """Test finding stale vendors (those due for re-screening)."""
    print("\n[Test] Stale vendor detection...")

    # Create test vendor
    vendor_id = "test-vendor-001"
    db.upsert_vendor(
        vendor_id=vendor_id,
        name="Test Vendor",
        country="US",
        program="standard_industrial",
        vendor_input={"name": "Test Vendor", "country": "US"},
        profile="defense_acquisition"
    )

    # Create scheduler with 1-hour interval
    scheduler = MonitorScheduler(interval_hours=1)

    # New vendor should be stale (never monitored)
    stale = scheduler.get_stale_vendors()
    vendor_ids = [v["id"] for v in stale]
    assert vendor_id in vendor_ids, "New vendor should be marked as stale"
    print("  ✓ New vendors marked as stale")

    # Simulate monitoring check
    db.save_monitoring_log(
        vendor_id=vendor_id,
        previous_risk="LOW",
        current_risk="LOW",
        risk_changed=False
    )

    # Now it shouldn't be stale (just checked)
    scheduler.interval_seconds = 3600  # 1 hour
    stale = scheduler.get_stale_vendors()
    vendor_ids = [v["id"] for v in stale]

    # Debug: check what we got
    if vendor_id in vendor_ids:
        monitoring = db.get_monitoring_history(vendor_id, limit=1)
        if monitoring:
            print(f"    DEBUG: last_check={monitoring[0].get('checked_at')}")
            cutoff = (datetime.utcnow() - timedelta(seconds=3600)).isoformat()
            print(f"    DEBUG: cutoff_time={cutoff}")
            print(f"    DEBUG: comparison: {monitoring[0].get('checked_at')} < {cutoff} = {monitoring[0].get('checked_at') < cutoff}")

    assert vendor_id not in vendor_ids, "Recently checked vendor should not be stale"
    print("  ✓ Recently monitored vendors not marked as stale")

    # Simulate old check (2 hours ago)
    conn = sqlite3.connect(db.get_db_path())
    old_time = (datetime.utcnow() - timedelta(hours=2)).isoformat()
    conn.execute(
        "UPDATE monitoring_log SET checked_at = ? WHERE vendor_id = ?",
        (old_time, vendor_id)
    )
    conn.commit()
    conn.close()

    # Now it should be stale again
    stale = scheduler.get_stale_vendors()
    vendor_ids = [v["id"] for v in stale]
    assert vendor_id in vendor_ids, "Old vendor should be marked as stale"
    print("  ✓ Old monitored vendors marked as stale after interval")


def test_sweep_status():
    """Test sweep status retrieval."""
    print("\n[Test] Sweep status retrieval...")

    scheduler = MonitorScheduler()
    sweep_id = "test-sweep-status"

    # Create a sweep
    db.create_sweep(sweep_id, 3)
    db.update_sweep_progress(sweep_id, 1, 0, 0, "running")

    # Get status
    status = scheduler.get_sweep_status(sweep_id)
    assert status["sweep_id"] == sweep_id, "Sweep ID mismatch"
    assert status["status"] == "running", "Status mismatch"
    assert status["processed"] == 1, "Processed count mismatch"
    print("  ✓ Sweep status retrieval works")

    # Non-existent sweep
    status = scheduler.get_sweep_status("nonexistent")
    assert status["status"] == "not_found", "Should return not_found for missing sweep"
    print("  ✓ Missing sweep returns not_found")


def test_trigger_sweep():
    """Test manual sweep triggering."""
    print("\n[Test] Sweep triggering...")

    scheduler = MonitorScheduler(interval_hours=1)
    # Don't start background scheduler

    # Trigger a sweep
    sweep_id = scheduler.trigger_sweep()
    assert sweep_id is not None, "Sweep ID not returned"

    # Wait briefly for async execution
    time.sleep(0.5)

    # Check status
    status = scheduler.get_sweep_status(sweep_id)
    assert status["sweep_id"] == sweep_id, "Sweep ID mismatch"
    assert status["status"] in ("queued", "running", "completed", "failed"), f"Unexpected status: {status['status']}"
    print(f"  ✓ Sweep triggered with ID {sweep_id[:8]}... (status: {status['status']})")


def run_all_tests():
    """Run all test cases."""
    print("\n" + "="*60)
    print("Xiphos Monitoring Scheduler - Test Suite")
    print("="*60)

    try:
        test_db_init()
        test_monitor_config()
        test_sweep_lifecycle()
        test_scheduler_initialization()
        test_stale_vendors()
        test_sweep_status()
        test_trigger_sweep()

        print("\n" + "="*60)
        print("All tests passed! ✓")
        print("="*60 + "\n")
        return 0

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
