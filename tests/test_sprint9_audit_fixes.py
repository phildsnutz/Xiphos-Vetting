import importlib
import json
import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload(name: str):
    if name in sys.modules:
        return importlib.reload(sys.modules[name])
    return importlib.import_module(name)


def test_latest_score_prefers_newer_row_when_timestamps_tie(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))
    db = _reload("db")
    db.init_db()
    db.upsert_vendor(
        "v-audit-latest",
        "Latest Score Vendor",
        "US",
        "dod_unclassified",
        vendor_input={"name": "Latest Score Vendor"},
        profile="defense_acquisition",
    )

    scored_at = "2026-03-23 12:00:00"
    older = {"composite_score": 11, "calibrated": {"calibrated_tier": "TIER_4_CLEAR"}}
    newer = {"composite_score": 42, "calibrated": {"calibrated_tier": "TIER_2_ELEVATED"}}

    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO scoring_results
                (vendor_id, calibrated_probability, calibrated_tier, composite_score,
                 is_hard_stop, interval_lower, interval_upper, interval_coverage, full_result, scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "v-audit-latest",
                0.11,
                "TIER_4_CLEAR",
                11,
                0,
                0.0,
                0.0,
                0.0,
                json.dumps(older),
                scored_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO scoring_results
                (vendor_id, calibrated_probability, calibrated_tier, composite_score,
                 is_hard_stop, interval_lower, interval_upper, interval_coverage, full_result, scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "v-audit-latest",
                0.42,
                "TIER_2_ELEVATED",
                42,
                0,
                0.0,
                0.0,
                0.0,
                json.dumps(newer),
                scored_at,
            ),
        )

    latest = db.get_latest_score("v-audit-latest")
    assert latest is not None
    assert latest["composite_score"] == 42
    assert latest["calibrated"]["calibrated_tier"] == "TIER_2_ELEVATED"

    history = db.get_score_history("v-audit-latest", limit=2)
    assert history[0]["composite_score"] == 42
    assert history[1]["composite_score"] == 11

    listed = db.list_vendors_with_scores(limit=10)
    listed_vendor = next(row for row in listed if row["id"] == "v-audit-latest")
    assert listed_vendor["latest_score"]["composite_score"] == 42


def test_portfolio_read_permission_is_available():
    auth = _reload("auth")
    assert auth.PERMISSIONS["portfolio:read"] == 20


def test_trigger_sweep_persists_queued_status_immediately(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-monitor.db"))
    db = _reload("db")
    db.init_db()
    db.upsert_vendor(
        "v-monitor-queued",
        "Queued Monitor Vendor",
        "US",
        "dod_unclassified",
        vendor_input={"name": "Queued Monitor Vendor"},
        profile="defense_acquisition",
    )
    monitor_scheduler = _reload("monitor_scheduler")
    monkeypatch.setattr(
        monitor_scheduler.MonitorScheduler,
        "_execute_sweep",
        lambda self, sweep_id, vendor_ids=None: None,
    )

    scheduler = monitor_scheduler.MonitorScheduler()
    sweep_id = scheduler.trigger_sweep(vendor_ids=["v-monitor-queued"])

    persisted = db.get_sweep(sweep_id)
    assert persisted is not None
    assert persisted["status"] == "queued"
    assert persisted["total_vendors"] == 1

    other_scheduler = monitor_scheduler.MonitorScheduler()
    status = other_scheduler.get_sweep_status(sweep_id)
    assert status["status"] == "queued"
    assert status["total_vendors"] == 1
