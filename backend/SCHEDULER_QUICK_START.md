# Monitoring Scheduler - Quick Start Guide

## Enable Scheduler at Startup

```bash
export XIPHOS_MONITOR_ENABLED=true
export XIPHOS_MONITOR_INTERVAL_HOURS=168  # weekly (default)
python server.py
```

The scheduler will start automatically in the background.

## Check Scheduler Status

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8080/api/monitor/schedule
```

Returns:
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

## Trigger Manual Sweep

```bash
# Sweep all due vendors
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8080/api/monitor/sweep
```

Returns:
```json
{
  "sweep_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued"
}
```

Or sweep specific vendors:
```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"vendor_ids": ["vendor-001", "vendor-002"]}' \
  http://localhost:8080/api/monitor/sweep
```

## Check Sweep Progress

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8080/api/monitor/sweep/550e8400-e29b-41d4-a716-446655440000
```

Responses:

**Running:**
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

**Completed:**
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

## Change Interval (Admin Only)

```bash
curl -X POST \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"interval_hours": 24}' \
  http://localhost:8080/api/monitor/schedule
```

## Disable/Enable (Admin Only)

```bash
# Disable
curl -X POST \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}' \
  http://localhost:8080/api/monitor/schedule
```

## Poll Loop Example

```bash
#!/bin/bash

SWEEP_ID=$1
TOKEN=$2
API="http://localhost:8080"

while true; do
  status=$(curl -s -H "Authorization: Bearer $TOKEN" \
    "$API/api/monitor/sweep/$SWEEP_ID")

  state=$(echo $status | jq -r '.status')
  processed=$(echo $status | jq '.processed // 0')
  total=$(echo $status | jq '.total_vendors // 0')

  echo "[$state] $processed/$total"

  if [[ "$state" == "completed" || "$state" == "failed" ]]; then
    echo "Final: $(echo $status | jq '.')"
    break
  fi

  sleep 2
done
```

## Key Points

- **Non-blocking**: Sweeps run in background threads
- **Rate limited**: 2-second delay between vendors
- **Alert generation**: Automatic alerts on tier changes
- **Profile-aware**: Uses vendor-specific OSINT connectors
- **Thread-safe**: Safe for concurrent requests

## Permissions

- **GET /api/monitor/schedule** - Requires `monitor:read`
- **POST /api/monitor/schedule** - Requires `admin`
- **POST /api/monitor/sweep** - Requires `analyst`
- **GET /api/monitor/sweep/{id}** - Requires `monitor:read`

## Common Configurations

### Development (Check Every Hour)
```bash
export XIPHOS_MONITOR_ENABLED=true
export XIPHOS_MONITOR_INTERVAL_HOURS=1
```

### Production (Check Weekly)
```bash
export XIPHOS_MONITOR_ENABLED=true
export XIPHOS_MONITOR_INTERVAL_HOURS=168
```

### High-Risk (Check Daily)
```bash
export XIPHOS_MONITOR_ENABLED=true
export XIPHOS_MONITOR_INTERVAL_HOURS=24
```

### Disabled (Manual Only)
```bash
# Don't set XIPHOS_MONITOR_ENABLED
# Or set to false
export XIPHOS_MONITOR_ENABLED=false
```

## Verify Installation

```bash
# Check that tables exist
sqlite3 xiphos.db ".schema monitor_schedules"
sqlite3 xiphos.db ".schema monitor_config"

# Check server logs for startup message
tail -f server.log | grep -i "scheduler"
```

## Troubleshooting

### Scheduler not starting?
```bash
# Check environment variable
echo $XIPHOS_MONITOR_ENABLED

# Check server logs
grep -i "scheduler" server.log
```

### Sweeps not progressing?
```bash
# Check database for errors
sqlite3 xiphos.db "SELECT * FROM monitor_schedules ORDER BY created_at DESC LIMIT 5;"

# Check that vendors exist
sqlite3 xiphos.db "SELECT COUNT(*) FROM vendors;"
```

### Want to check a specific vendor?
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"vendor_ids": ["vendor-id"]}' \
  http://localhost:8080/api/monitor/sweep
```

## Next Steps

1. Enable with `XIPHOS_MONITOR_ENABLED=true`
2. Start server: `python server.py`
3. Trigger sweep: `curl -X POST ... /api/monitor/sweep`
4. Poll results: `curl -H ... /api/monitor/sweep/{sweep_id}`
5. Check alerts: `curl ... /api/alerts`

For detailed documentation, see `MONITORING_SCHEDULER.md`
