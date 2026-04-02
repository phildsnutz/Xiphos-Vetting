"""
AXIOM Monitor -- Persistent Intelligence Monitoring

Tier 3 of the AXIOM collection system. Provides scheduled monitoring of
contract vehicles, prime contractors, and subcontractor ecosystems with
change detection and alert generation.

Monitoring capabilities:
  - Periodic re-scanning of watched primes/vehicles
  - Change detection (new postings, removed postings, new companies)
  - Teaming shift alerts (new subs appearing, existing subs disappearing)
  - Hiring surge detection (sudden increase in positions)
  - Temporal intelligence (seasonal patterns, recompete indicators)

Architecture:
  - Uses existing MonitorScheduler threading pattern
  - Stores snapshots in axiom_monitor_snapshots table
  - Generates alerts via existing db.save_alert() system
  - REST API endpoints for managing watchlists

Change detection works by comparing current scraper results against the
most recent snapshot. Any delta (new entities, removed entities, position
count changes) generates an alert with severity based on the nature of
the change.
"""

import json
import logging
import threading
import time
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Monitoring intervals by priority tier (in hours)
MONITOR_INTERVALS = {
    "critical": 24,      # Daily: active vehicles with upcoming recompetes
    "high": 72,          # Every 3 days: watched primes on active vehicles
    "standard": 168,     # Weekly: general watchlist items
    "low": 720,          # Monthly: background monitoring
}

# Alert severity thresholds
HIRING_SURGE_THRESHOLD = 5      # New positions in single scan
POSITION_DROP_THRESHOLD = 0.5   # 50% reduction triggers alert
NEW_SUB_ALERT_SEVERITY = "medium"
SUB_DEPARTURE_ALERT_SEVERITY = "high"
HIRING_SURGE_ALERT_SEVERITY = "medium"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class WatchlistEntry:
    """An entry on the AXIOM monitoring watchlist."""
    id: str = ""
    prime_contractor: str = ""
    contract_name: str = ""
    vehicle_name: str = ""
    installation: str = ""
    website: str = ""
    priority: str = "standard"  # critical, high, standard, low
    last_scan_at: str = ""
    next_scan_at: str = ""
    scan_count: int = 0
    active: bool = True
    created_at: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class MonitorSnapshot:
    """Point-in-time snapshot of intelligence for a watchlist entry."""
    watchlist_id: str
    scan_timestamp: str
    entities: list[dict] = field(default_factory=list)  # {name, type, positions, confidence}
    relationships: list[dict] = field(default_factory=list)
    total_positions: int = 0
    sources_queried: list[str] = field(default_factory=list)
    raw_hash: str = ""  # Hash of entity names for quick diff


@dataclass
class ChangeAlert:
    """A detected change between snapshots."""
    alert_type: str  # new_sub, departed_sub, hiring_surge, position_drop, new_location
    severity: str    # info, low, medium, high, critical
    title: str
    description: str
    entities_involved: list[str] = field(default_factory=list)
    previous_value: str = ""
    current_value: str = ""
    watchlist_id: str = ""


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def init_axiom_monitor_tables():
    """Create AXIOM monitoring tables if they don't exist."""
    try:
        import db
        import os
        _is_pg = os.environ.get("HELIOS_DB_ENGINE", "sqlite").lower().strip() == "postgres"
        _auto_id = "SERIAL PRIMARY KEY" if _is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
        with db.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS axiom_watchlist (
                    id TEXT PRIMARY KEY,
                    prime_contractor TEXT NOT NULL,
                    contract_name TEXT DEFAULT '',
                    vehicle_name TEXT DEFAULT '',
                    installation TEXT DEFAULT '',
                    website TEXT DEFAULT '',
                    priority TEXT DEFAULT 'standard',
                    last_scan_at TEXT,
                    next_scan_at TEXT,
                    scan_count INTEGER DEFAULT 0,
                    active INTEGER DEFAULT 1,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS axiom_snapshots (
                    id {_auto_id},
                    watchlist_id TEXT NOT NULL,
                    scan_timestamp TEXT NOT NULL,
                    entities TEXT NOT NULL DEFAULT '[]',
                    relationships TEXT NOT NULL DEFAULT '[]',
                    total_positions INTEGER DEFAULT 0,
                    sources_queried TEXT NOT NULL DEFAULT '[]',
                    raw_hash TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (watchlist_id) REFERENCES axiom_watchlist(id)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_axiom_snapshots_watchlist
                ON axiom_snapshots(watchlist_id, scan_timestamp DESC)
            """)
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS axiom_alerts (
                    id {_auto_id},
                    watchlist_id TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    entities_involved TEXT DEFAULT '[]',
                    acknowledged INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (watchlist_id) REFERENCES axiom_watchlist(id)
                )
            """)
            conn.commit()
            logger.info("axiom_monitor: tables initialized")
    except Exception as e:
        logger.exception("axiom_monitor: table init failed: %s", e)


def _generate_id(*parts: str) -> str:
    """Generate a stable hash ID from parts."""
    raw = "|".join(str(p or "") for p in parts)
    return f"axiom:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def add_to_watchlist(prime_contractor: str, contract_name: str = "",
                     vehicle_name: str = "", installation: str = "",
                     website: str = "", priority: str = "standard",
                     metadata: dict = None) -> WatchlistEntry:
    """Add an entry to the AXIOM monitoring watchlist."""
    import db

    now = datetime.now(timezone.utc).isoformat()
    entry_id = _generate_id(prime_contractor, contract_name, vehicle_name)
    interval_hours = MONITOR_INTERVALS.get(priority, 168)
    next_scan = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()  # First scan in 1 hour

    entry = WatchlistEntry(
        id=entry_id,
        prime_contractor=prime_contractor,
        contract_name=contract_name,
        vehicle_name=vehicle_name,
        installation=installation,
        website=website,
        priority=priority,
        next_scan_at=next_scan,
        active=True,
        created_at=now,
        metadata=metadata or {},
    )

    with db.get_conn() as conn:
        conn.execute("""
            INSERT INTO axiom_watchlist (id, prime_contractor, contract_name, vehicle_name,
                installation, website, priority, next_scan_at, active, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                priority = excluded.priority,
                active = 1,
                next_scan_at = excluded.next_scan_at,
                updated_at = excluded.updated_at
        """, (
            entry.id, entry.prime_contractor, entry.contract_name,
            entry.vehicle_name, entry.installation, entry.website,
            entry.priority, entry.next_scan_at,
            json.dumps(entry.metadata), now, now,
        ))
        conn.commit()

    logger.info("axiom_monitor: added '%s' to watchlist (priority=%s)", prime_contractor, priority)
    return entry


def get_watchlist(active_only: bool = True) -> list[WatchlistEntry]:
    """Retrieve the current watchlist."""
    import db

    with db.get_conn() as conn:
        query = "SELECT * FROM axiom_watchlist"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY priority ASC, next_scan_at ASC"

        rows = conn.execute(query).fetchall()
        entries = []
        for row in rows:
            r = dict(row) if hasattr(row, 'keys') else {
                'id': row[0], 'prime_contractor': row[1], 'contract_name': row[2],
                'vehicle_name': row[3], 'installation': row[4], 'website': row[5],
                'priority': row[6], 'last_scan_at': row[7], 'next_scan_at': row[8],
                'scan_count': row[9], 'active': bool(row[10]),
                'metadata': json.loads(row[11] or '{}'),
                'created_at': row[12],
            }
            entries.append(WatchlistEntry(**{k: v for k, v in r.items() if k != 'updated_at'}))
        return entries


def get_latest_snapshot(watchlist_id: str) -> Optional[MonitorSnapshot]:
    """Get the most recent snapshot for a watchlist entry."""
    import db

    with db.get_conn() as conn:
        row = conn.execute("""
            SELECT * FROM axiom_snapshots
            WHERE watchlist_id = ?
            ORDER BY scan_timestamp DESC LIMIT 1
        """, (watchlist_id,)).fetchone()

        if not row:
            return None

        r = dict(row) if hasattr(row, 'keys') else {
            'watchlist_id': row[1], 'scan_timestamp': row[2],
            'entities': json.loads(row[3] or '[]'),
            'relationships': json.loads(row[4] or '[]'),
            'total_positions': row[5], 'sources_queried': json.loads(row[6] or '[]'),
            'raw_hash': row[7],
        }
        return MonitorSnapshot(**{k: v for k, v in r.items() if k not in ('id', 'created_at')})


def save_snapshot(snapshot: MonitorSnapshot):
    """Save a monitoring snapshot."""
    import db

    now = datetime.now(timezone.utc).isoformat()
    with db.get_conn() as conn:
        conn.execute("""
            INSERT INTO axiom_snapshots (watchlist_id, scan_timestamp, entities,
                relationships, total_positions, sources_queried, raw_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot.watchlist_id, snapshot.scan_timestamp,
            json.dumps(snapshot.entities), json.dumps(snapshot.relationships),
            snapshot.total_positions, json.dumps(snapshot.sources_queried),
            snapshot.raw_hash, now,
        ))
        conn.commit()


def save_alert(alert: ChangeAlert):
    """Save a change alert."""
    import db

    now = datetime.now(timezone.utc).isoformat()
    with db.get_conn() as conn:
        conn.execute("""
            INSERT INTO axiom_alerts (watchlist_id, alert_type, severity, title,
                description, entities_involved, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            alert.watchlist_id, alert.alert_type, alert.severity,
            alert.title, alert.description,
            json.dumps(alert.entities_involved), now,
        ))
        conn.commit()

    logger.info("axiom_monitor: alert [%s] %s: %s", alert.severity, alert.alert_type, alert.title)


def get_recent_alerts(limit: int = 20, severity: str = "") -> list[dict]:
    """Get recent AXIOM alerts."""
    import db

    with db.get_conn() as conn:
        query = "SELECT * FROM axiom_alerts"
        params = []
        if severity:
            query += " WHERE severity = ?"
            params.append(severity)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(row) if hasattr(row, 'keys') else row for row in rows]


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------

def detect_changes(current: MonitorSnapshot, previous: Optional[MonitorSnapshot],
                   watchlist_entry: WatchlistEntry) -> list[ChangeAlert]:
    """
    Compare current snapshot against previous to detect changes.

    Change types detected:
      - New subcontractor appearing
      - Existing subcontractor disappearing
      - Hiring surge (significant position count increase)
      - Position drop (significant decrease)
      - New installation/location
    """
    alerts = []

    if not previous:
        # First scan, no comparison possible
        if current.entities:
            alerts.append(ChangeAlert(
                alert_type="initial_scan",
                severity="info",
                title=f"Initial AXIOM scan: {watchlist_entry.prime_contractor}",
                description=(
                    f"First scan completed. Found {len(current.entities)} entities "
                    f"and {current.total_positions} positions."
                ),
                entities_involved=[e.get("name", "") for e in current.entities],
                watchlist_id=watchlist_entry.id,
            ))
        return alerts

    # Entity comparison
    prev_entities = {e.get("name", ""): e for e in previous.entities if e.get("name")}
    curr_entities = {e.get("name", ""): e for e in current.entities if e.get("name")}

    prev_names = set(prev_entities.keys())
    curr_names = set(curr_entities.keys())

    # New entities (potential new subcontractors)
    new_entities = curr_names - prev_names
    for name in new_entities:
        entity = curr_entities[name]
        alerts.append(ChangeAlert(
            alert_type="new_sub",
            severity=NEW_SUB_ALERT_SEVERITY,
            title=f"New entity detected: {name}",
            description=(
                f"{name} appeared in job postings for {watchlist_entry.prime_contractor} "
                f"({watchlist_entry.contract_name or watchlist_entry.vehicle_name or 'general'}). "
                f"Type: {entity.get('entity_type', 'company')}. "
                f"Positions: {entity.get('positions', 0)}. "
                f"This may indicate a new teaming arrangement."
            ),
            entities_involved=[name, watchlist_entry.prime_contractor],
            current_value=json.dumps(entity),
            watchlist_id=watchlist_entry.id,
        ))

    # Departed entities (subs that disappeared)
    departed = prev_names - curr_names
    for name in departed:
        entity = prev_entities[name]
        alerts.append(ChangeAlert(
            alert_type="departed_sub",
            severity=SUB_DEPARTURE_ALERT_SEVERITY,
            title=f"Entity no longer detected: {name}",
            description=(
                f"{name} no longer appears in job postings for "
                f"{watchlist_entry.prime_contractor}. Previously had "
                f"{entity.get('positions', 0)} positions. "
                f"This may indicate contract completion, teaming dissolution, "
                f"or transition to a different sub."
            ),
            entities_involved=[name, watchlist_entry.prime_contractor],
            previous_value=json.dumps(entity),
            watchlist_id=watchlist_entry.id,
        ))

    # Position count changes
    if previous.total_positions > 0 and current.total_positions > 0:
        delta = current.total_positions - previous.total_positions

        if delta >= HIRING_SURGE_THRESHOLD:
            alerts.append(ChangeAlert(
                alert_type="hiring_surge",
                severity=HIRING_SURGE_ALERT_SEVERITY,
                title=f"Hiring surge: {watchlist_entry.prime_contractor} +{delta} positions",
                description=(
                    f"Position count increased from {previous.total_positions} to "
                    f"{current.total_positions} (+{delta}). This may indicate "
                    f"new task order award, contract expansion, or recompete activity."
                ),
                entities_involved=[watchlist_entry.prime_contractor],
                previous_value=str(previous.total_positions),
                current_value=str(current.total_positions),
                watchlist_id=watchlist_entry.id,
            ))

        ratio = current.total_positions / previous.total_positions
        if ratio <= POSITION_DROP_THRESHOLD:
            alerts.append(ChangeAlert(
                alert_type="position_drop",
                severity="high",
                title=f"Position drop: {watchlist_entry.prime_contractor} {int((1-ratio)*100)}% decrease",
                description=(
                    f"Position count dropped from {previous.total_positions} to "
                    f"{current.total_positions} ({int((1-ratio)*100)}% decrease). "
                    f"This may indicate contract wind-down, task order completion, "
                    f"or workforce transition."
                ),
                entities_involved=[watchlist_entry.prime_contractor],
                previous_value=str(previous.total_positions),
                current_value=str(current.total_positions),
                watchlist_id=watchlist_entry.id,
            ))

    return alerts


# ---------------------------------------------------------------------------
# Scan execution
# ---------------------------------------------------------------------------

def scan_watchlist_entry(entry: WatchlistEntry) -> tuple[MonitorSnapshot, list[ChangeAlert]]:
    """
    Execute a single monitoring scan for a watchlist entry.

    Runs the careers_scraper, builds a snapshot, compares against the
    previous snapshot, and generates change alerts.

    Returns:
        Tuple of (current_snapshot, list_of_alerts)
    """
    import db

    logger.info("axiom_monitor: scanning '%s' (priority=%s)", entry.prime_contractor, entry.priority)
    now = datetime.now(timezone.utc)

    # Run scraper
    try:
        from osint.careers_scraper import enrich
        scraper_result = enrich(
            vendor_name=entry.prime_contractor,
            contract_name=entry.contract_name,
            vehicle_name=entry.vehicle_name,
            installation=entry.installation,
            website=entry.website,
        )
    except Exception as e:
        logger.exception("axiom_monitor: scraper failed for '%s': %s", entry.prime_contractor, e)
        return MonitorSnapshot(watchlist_id=entry.id, scan_timestamp=now.isoformat()), []

    # Build snapshot from scraper results
    entities = []
    total_positions = 0
    for finding in scraper_result.findings:
        if finding.category == "subcontractor_identification":
            raw = finding.raw_data or {}
            entities.append({
                "name": raw.get("sub_name", finding.title),
                "entity_type": "company",
                "positions": raw.get("position_count", 0),
                "confidence": finding.confidence,
                "locations": raw.get("locations", []),
                "clearances": raw.get("clearances", []),
            })
            total_positions += raw.get("position_count", 0)

    relationships = []
    for rel in scraper_result.relationships:
        relationships.append({
            "source": rel.get("source_entity", ""),
            "target": rel.get("target_entity", ""),
            "rel_type": rel.get("type", ""),
            "confidence": rel.get("confidence", 0.5),
        })

    # Build entity hash for quick comparison
    entity_names = sorted(e.get("name", "") for e in entities)
    raw_hash = hashlib.sha256("|".join(entity_names).encode()).hexdigest()[:16]

    snapshot = MonitorSnapshot(
        watchlist_id=entry.id,
        scan_timestamp=now.isoformat(),
        entities=entities,
        relationships=relationships,
        total_positions=total_positions,
        sources_queried=scraper_result.identifiers.get("careers_scraper_sources", []),
        raw_hash=raw_hash,
    )

    # Get previous snapshot and detect changes
    previous = get_latest_snapshot(entry.id)
    alerts = detect_changes(snapshot, previous, entry)

    # Save snapshot
    save_snapshot(snapshot)

    # Save alerts
    for alert in alerts:
        save_alert(alert)

    # Update watchlist entry
    interval = MONITOR_INTERVALS.get(entry.priority, 168)
    next_scan = (now + timedelta(hours=interval)).isoformat()

    with db.get_conn() as conn:
        conn.execute("""
            UPDATE axiom_watchlist
            SET last_scan_at = ?, next_scan_at = ?, scan_count = scan_count + 1, updated_at = ?
            WHERE id = ?
        """, (now.isoformat(), next_scan, now.isoformat(), entry.id))
        conn.commit()

    logger.info(
        "axiom_monitor: scan complete for '%s'. %d entities, %d positions, %d alerts",
        entry.prime_contractor, len(entities), total_positions, len(alerts),
    )

    return snapshot, alerts


# ---------------------------------------------------------------------------
# Daemon scheduler
# ---------------------------------------------------------------------------

class AxiomMonitorDaemon:
    """
    Background daemon that periodically scans watchlist entries.
    Follows the existing MonitorScheduler threading pattern.
    """

    def __init__(self, check_interval: int = 300):
        """
        Args:
            check_interval: Seconds between watchlist checks (default 5 min)
        """
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._check_interval = check_interval
        self._lock = threading.Lock()

    def start(self):
        """Start the monitoring daemon."""
        with self._lock:
            if self._running:
                logger.warning("axiom_monitor: daemon already running")
                return

            init_axiom_monitor_tables()
            self._running = True
            self._thread = threading.Thread(target=self._daemon_loop, daemon=True, name="axiom-monitor")
            self._thread.start()
            logger.info("axiom_monitor: daemon started (check_interval=%ds)", self._check_interval)

    def stop(self):
        """Stop the monitoring daemon."""
        with self._lock:
            self._running = False
            logger.info("axiom_monitor: daemon stop requested")

    def _daemon_loop(self):
        """Main daemon loop. Checks watchlist and scans due entries."""
        while self._running:
            try:
                self._check_and_scan()
            except Exception as e:
                logger.exception("axiom_monitor: daemon loop error: %s", e)

            # Sleep in small increments so stop() is responsive
            for _ in range(self._check_interval):
                if not self._running:
                    break
                time.sleep(1)

    def _check_and_scan(self):
        """Check watchlist for entries due for scanning."""
        now = datetime.now(timezone.utc).isoformat()

        try:
            watchlist = get_watchlist(active_only=True)
        except Exception as e:
            logger.warning("axiom_monitor: could not retrieve watchlist: %s", e)
            return

        due_entries = [
            entry for entry in watchlist
            if entry.next_scan_at and entry.next_scan_at <= now
        ]

        if due_entries:
            logger.info("axiom_monitor: %d entries due for scanning", len(due_entries))

        for entry in due_entries:
            if not self._running:
                break
            try:
                scan_watchlist_entry(entry)
            except Exception as e:
                logger.exception("axiom_monitor: scan failed for '%s': %s", entry.prime_contractor, e)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_daemon: Optional[AxiomMonitorDaemon] = None


def start_daemon(check_interval: int = 300):
    """Start the global AXIOM monitor daemon."""
    global _daemon
    if _daemon is None:
        _daemon = AxiomMonitorDaemon(check_interval=check_interval)
    _daemon.start()


def stop_daemon():
    """Stop the global AXIOM monitor daemon."""
    global _daemon
    if _daemon:
        _daemon.stop()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """CLI for managing the AXIOM monitor."""
    import argparse

    parser = argparse.ArgumentParser(description="AXIOM Persistent Monitor")
    sub = parser.add_subparsers(dest="command")

    # Add to watchlist
    add_cmd = sub.add_parser("add", help="Add entry to watchlist")
    add_cmd.add_argument("prime", help="Prime contractor name")
    add_cmd.add_argument("--contract", default="")
    add_cmd.add_argument("--vehicle", default="")
    add_cmd.add_argument("--installation", default="")
    add_cmd.add_argument("--website", default="")
    add_cmd.add_argument("--priority", default="standard", choices=list(MONITOR_INTERVALS.keys()))

    # List watchlist
    sub.add_parser("list", help="List watchlist entries")

    # Scan now
    scan_cmd = sub.add_parser("scan", help="Scan a specific entry now")
    scan_cmd.add_argument("prime", help="Prime contractor name to scan")

    # Scan all due
    sub.add_parser("scan-due", help="Scan all due entries")

    # Show alerts
    alerts_cmd = sub.add_parser("alerts", help="Show recent alerts")
    alerts_cmd.add_argument("--limit", type=int, default=20)
    alerts_cmd.add_argument("--severity", default="")

    # Start daemon
    daemon_cmd = sub.add_parser("daemon", help="Start monitoring daemon")
    daemon_cmd.add_argument("--interval", type=int, default=300)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    init_axiom_monitor_tables()

    if args.command == "add":
        entry = add_to_watchlist(
            args.prime, args.contract, args.vehicle,
            args.installation, args.website, args.priority,
        )
        print(f"Added: {entry.id} ({entry.prime_contractor})")

    elif args.command == "list":
        entries = get_watchlist()
        for e in entries:
            print(f"  [{e.priority}] {e.prime_contractor} | {e.contract_name or e.vehicle_name or 'general'} | scans: {e.scan_count} | next: {e.next_scan_at or 'unscheduled'}")

    elif args.command == "scan":
        entries = get_watchlist()
        match = [e for e in entries if args.prime.lower() in e.prime_contractor.lower()]
        if match:
            snapshot, alerts = scan_watchlist_entry(match[0])
            print(f"Scan complete: {len(snapshot.entities)} entities, {snapshot.total_positions} positions, {len(alerts)} alerts")
            for a in alerts:
                print(f"  [{a.severity}] {a.alert_type}: {a.title}")
        else:
            print(f"No watchlist entry found matching '{args.prime}'")

    elif args.command == "scan-due":
        entries = get_watchlist()
        now = datetime.now(timezone.utc).isoformat()
        due = [e for e in entries if e.next_scan_at and e.next_scan_at <= now]
        print(f"{len(due)} entries due for scanning")
        for entry in due:
            snapshot, alerts = scan_watchlist_entry(entry)
            print(f"  {entry.prime_contractor}: {len(alerts)} alerts")

    elif args.command == "alerts":
        alerts = get_recent_alerts(args.limit, args.severity)
        for a in alerts:
            a_dict = dict(a) if hasattr(a, 'keys') else a
            print(f"  [{a_dict.get('severity', '?')}] {a_dict.get('alert_type', '?')}: {a_dict.get('title', '?')}")

    elif args.command == "daemon":
        print(f"Starting AXIOM monitor daemon (check_interval={args.interval}s)")
        start_daemon(args.interval)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_daemon()
            print("Daemon stopped.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
