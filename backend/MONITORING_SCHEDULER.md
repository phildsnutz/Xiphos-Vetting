# Xiphos Continuous Monitoring Scheduler

## Overview

The Monitoring Scheduler provides automated, non-blocking continuous vendor re-screening via OSINT enrichment. It detects risk tier changes and generates alerts when vendors' risk profiles shift during periodic monitoring.

## Features

- **Automatic Periodic Monitoring**: Re-screens vendors on a configurable interval (default: weekly)
- **Tier Change Detection**: Automatically detects when vendor risk tiers change and creates alerts
- **Non-Blocking Sweeps**: Monitoring runs in background threads without blocking API requests
- **Async Progress Tracking**: Poll endpoints for sweep status and results
- **Rate Limiting**: Includes 2-second delays between vendors to avoid overloading external APIs
- **Profile-Aware Screening**: Uses vendor-specific compliance profiles to select appropriate OSINT connectors
- **Persistent Tracking**: Stores sweep metadata and monitoring history in database

## Architecture

### Components

1. **MonitorScheduler class** (`monitor_scheduler.py`)
   - Main scheduler that manages background threads
   - Triggers sweeps on interval or manually
   - Tracks active sweeps

2. **Database Tables**
   - `monitor_schedules`: Tracks sweep progress and results
   - `monitor_config`: Stores scheduler configuration

3. **API Endpoints** (integrated in `server.py`)
   - `GET /api/monitor/schedule` - Get scheduler status
   - `POST /api/monitor/schedule` - Update scheduler settings (admin)
   - `POST /api/monitor/sweep` - Trigger immediate sweep
   - `GET /api/monitor/sweep/{sweep_id}` - Poll sweep progress

## Setup & Configuration

### Environment Variables

```bash
# Enable the scheduler on server startup
export XIPHOS_MONITOR_ENABLED=true

# Set monitoring interval in hours (default: 168 = 1 week)
export XIPHOS_MONITOR_INTERVAL_HOURS=168
```

### Initialization

The scheduler is automatically initialized on server startup if `XIPHOS_MONITOR_ENABLED=true`:

```python
# In server.py startup sequence:
if HAS_SCHEDULER and monitor_enabled:
    init_scheduler(interval_hours=interval_hours)
    # Scheduler starts background thread automatically
```

### Standalone Usage

```python
from monitor_scheduler import MonitorScheduler

# Create and start scheduler
scheduler = MonitorScheduler(interval_hours=168)  # weekly
scheduler.start()

# Trigger immediate sweep
sweep_id = scheduler.trigger_sweep()

# Poll results
status = scheduler.get_sweep_status(sweep_id)

# Stop scheduler
scheduler.stop()
```

## API Usage

### Get Scheduler Status

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/monitor/schedule
```

**Response:**
```json
{
  "enabled": true,
  "interval_hours": 168,
  "vendors_due": 5,
  "last_sweep": "2026-03-16T19:30:00",
  "last_sweep_status": "completed",
  "next_sweep_estimate": "2026-03-23T19:30:00"
}
```

### Update Scheduler Settings (Admin Only)

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"interval_hours": 24, "enabled": true}' \
  http://localhost:8080/api/monitor/schedule
```

### Trigger Immediate Sweep

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/monitor/sweep
```

**Response:**
```json
{
  "sweep_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "Monitoring sweep queued. Poll /api/monitor/sweep/{sweep_id} for progress."
}
```

### Trigger Sweep for Specific Vendors

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"vendor_ids": ["vendor-001", "vendor-002"]}' \
  http://localhost:8080/api/monitor/sweep
```

### Poll Sweep Progress

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/monitor/sweep/{sweep_id}
```

**Response (running):**
```json
{
  "sweep_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "total_vendors": 5,
  "processed": 2,
  "risk_changes": 1,
  "new_alerts": 1,
  "started_at": "2026-03-16T19:35:00"
}
```

**Response (completed):**
```json
{
  "sweep_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "total_vendors": 5,
  "processed": 5,
  "risk_changes": 1,
  "new_alerts": 1,
  "started_at": "2026-03-16T19:35:00",
  "completed_at": "2026-03-16T19:37:30"
}
```

## Database Schema

### monitor_schedules Table

Tracks each monitoring sweep execution.

```sql
CREATE TABLE monitor_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sweep_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending, running, completed, failed
    total_vendors INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    risk_changes INTEGER NOT NULL DEFAULT 0,
    new_alerts INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### monitor_config Table

Stores scheduler configuration settings.

```sql
CREATE TABLE monitor_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### Helper Functions

```python
# Create new sweep
sweep_id = db.create_sweep(sweep_id, total_vendors=10)

# Update progress during sweep
db.update_sweep_progress(sweep_id, processed=5, risk_changes=1, new_alerts=1, status='running')

# Mark complete
db.complete_sweep(sweep_id)

# Retrieve sweep details
sweep = db.get_sweep(sweep_id)

# Get most recent sweep
latest = db.get_latest_sweep()

# Configuration management
db.set_monitor_config("interval_hours", "168")
interval = db.get_monitor_config("interval_hours", "168")
```

## Monitoring Workflow

### Per-Vendor Check Process

For each vendor in a sweep:

1. **Retrieve Profile**: Get vendor's compliance profile (e.g., "defense_acquisition")
2. **Select Connectors**: Use profile-specific OSINT connector list
3. **Run Enrichment**: Execute enrich_vendor() with selected connectors
4. **Save Report**: Store enrichment report in database
5. **Re-Score**: Run score_vendor() with updated enrichment data
6. **Compare Tiers**: Compare old vs. new calibrated_tier
7. **Generate Alert** (if tier changed):
   - Severity: "critical" if new tier is "hard_stop", else "high" or "medium"
   - Title: "Risk Tier Change: {old_tier} → {new_tier}"
   - Description: Details about change and profile used
8. **Log Entry**: Save monitoring check to monitoring_log table

### Rate Limiting

- Sequential vendor processing (no parallel)
- 2-second delay between vendors
- Prevents overloading external OSINT APIs

### Stale Vendor Detection

A vendor is considered "due for monitoring" if:
- It has never been monitored, OR
- Its last monitoring check was > `interval_hours` ago

Example: With 168-hour interval (1 week):
```python
cutoff_time = datetime.utcnow() - timedelta(hours=168)
stale = [v for v in vendors if v.last_check < cutoff_time]
```

## Alert Generation

When a vendor's tier changes during monitoring, an alert is created:

```python
db.save_alert(
    vendor_id="vendor-001",
    entity_name="ACME Corp",
    severity="high",  # critical, high, medium based on new tier
    title="Risk Tier Change: elevated → hard_stop",
    description="Continuous monitoring detected risk tier change..."
)
```

Alert severity mapping:
- New tier = "hard_stop" → severity = "critical"
- New tier = "elevated" → severity = "high"
- Other changes → severity = "medium"

## Example Workflows

### Enable Scheduler on Server Startup

```bash
export XIPHOS_MONITOR_ENABLED=true
export XIPHOS_MONITOR_INTERVAL_HOURS=24  # Daily
python server.py
# Scheduler starts automatically in background
```

### Manual Weekly Sweep

```bash
# Trigger sweep
response=$(curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/monitor/sweep)
sweep_id=$(echo $response | jq -r '.sweep_id')

# Poll until complete
while true; do
  status=$(curl -s -H "Authorization: Bearer $TOKEN" \
    http://localhost:8080/api/monitor/sweep/$sweep_id)

  if [[ $(echo $status | jq -r '.status') == "completed" ]]; then
    echo "Sweep complete: $(echo $status | jq '.risk_changes') changes"
    break
  fi

  sleep 2
done
```

### Change Interval to Daily

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"interval_hours": 24}' \
  http://localhost:8080/api/monitor/schedule
```

### Disable Scheduler

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}' \
  http://localhost:8080/api/monitor/schedule
```

## Testing

Run the test suite to verify scheduler functionality:

```bash
cd backend
python test_monitor_scheduler.py
```

Tests cover:
- Database table creation
- Configuration management
- Sweep lifecycle (create, update, complete)
- Stale vendor detection
- Sweep status tracking
- Manual sweep triggering

## Performance Considerations

### Interval Tuning

- **Hourly (24)**: High resource usage, catches changes quickly, expensive
- **Daily (24)**: Balanced approach, catches most issues quickly
- **Weekly (168)**: Default, good for production, lower load
- **Monthly (720)**: Low resource usage, may miss issues

### Vendor Count Impact

With 2-second delays between vendors:
- 100 vendors = ~200 seconds = 3.3 minutes
- 500 vendors = ~1000 seconds = 16.7 minutes
- 1000 vendors = ~2000 seconds = 33 minutes

### API Rate Limits

External APIs (SAM.gov, SEC EDGAR, etc.) have rate limits. The 2-second delay helps respect these, but may need adjustment for large vendor portfolios.

## Troubleshooting

### Scheduler Not Starting

Check environment variables:
```bash
echo $XIPHOS_MONITOR_ENABLED
echo $XIPHOS_MONITOR_INTERVAL_HOURS
```

Check server logs for import errors:
```bash
grep -i "monitor_scheduler" server.log
```

### Sweeps Not Completing

Check for stuck threads:
- Monitor processes for hanging enrichment calls
- Verify external API connectivity
- Check database locks

### Missing Alerts

Verify monitoring_log entries are created:
```sql
SELECT COUNT(*) FROM monitoring_log WHERE risk_changed = 1;
SELECT * FROM alerts ORDER BY created_at DESC LIMIT 10;
```

## Implementation Notes

- Scheduler uses Python threading (daemon threads)
- Each sweep runs in its own thread (non-blocking)
- Database operations use WAL mode for concurrent access
- SQLite UNIQUE constraint on sweep_id prevents duplicates
- Monitoring history is preserved permanently

## Security

- Scheduler requires "admin" role for configuration changes
- "analyst" role can trigger manual sweeps
- "monitor:read" permission to view schedule/results
- All database operations use parameterized queries (SQL injection safe)
- No sensitive data logged (credentials, keys)
