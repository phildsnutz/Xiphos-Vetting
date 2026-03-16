# Xiphos Monitor & Dossier Modules

## Overview

Two new modules extend Xiphos with continuous monitoring and intelligence-grade reporting:

### 1. **monitor.py** - Continuous Monitoring Agent
Periodically re-enriches vendors and detects risk profile changes.

#### Features
- **Background daemon**: Runs as a Flask background thread
- **CLI interface**: Can run as standalone or cron job
- **Change detection**: Finds new/resolved findings and risk tier shifts
- **Alert generation**: Creates database alerts on risk changes
- **Configurable intervals**: Default 24-hour check cycles

#### Usage
```bash
# Background daemon (24hr intervals)
python monitor.py --daemon --interval 86400

# Single check cycle
python monitor.py --run-once

# Check specific vendor
python monitor.py --vendor vendor-id-123

# Cron-friendly (once daily)
0 2 * * * cd /app && python monitor.py --run-once
```

#### Database
Added `monitoring_log` table tracking:
- `vendor_id`, `previous_risk`, `current_risk`
- `risk_changed` (boolean)
- `new_findings_count`, `resolved_findings_count`
- `checked_at` (timestamp)

New DB functions:
- `save_monitoring_log()` - Record a check result
- `get_monitoring_history(vendor_id)` - Last 20 checks
- `get_recent_risk_changes()` - All vendors with tier changes

#### Integration with Flask
```python
# In server.py startup, after initializing db:
from monitor import VendorMonitor

monitor = VendorMonitor(check_interval=86400)
monitor.start_daemon()
# Runs in background, generates alerts automatically
```

---

### 2. **dossier.py** - Intelligence-Grade Dossier Generator
Generates comprehensive HTML/PDF reports for vendor risk assessment.

#### Features
- **Self-contained HTML**: Inline CSS, no external dependencies
- **Professional design**: Dark navy header, color-coded severity badges
- **6 sections**:
  1. Executive Summary (name, country, tier, score)
  2. Bayesian Scoring Breakdown (contributions, confidence interval)
  3. OSINT Findings (grouped by source, sorted by severity)
  4. Risk Signals Timeline (monitoring history)
  5. Recommended Actions (marginal information values)
  6. Audit Trail (scoring & enrichment history)
- **PDF-ready**: Proper print styles, page breaks, watermark
- **Color coding**:
  - Severity: CRITICAL=red, HIGH=orange, MEDIUM=yellow, LOW=blue
  - Tiers: CLEAR=green, MONITOR=blue, ELEVATED=orange, HARD_STOP=red

#### Usage
```python
from dossier import generate_dossier

# Get HTML
html = generate_dossier("vendor-id-123")

# Save to file
with open("dossier.html", "w") as f:
    f.write(html)

# Serve via Flask
@app.route("/api/cases/<case_id>/dossier")
def api_generate_dossier(case_id):
    html = generate_dossier(case_id)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}
```

#### Visual Elements
- **Probability gauge**: CSS-only bar chart (red/orange/green)
- **Contribution bars**: Horizontal bars showing factor impact
- **Timeline**: Vertical dots with status indicators
- **Badges**: Color-coded severity/tier indicators
- **Watermark**: "CONFIDENTIAL" semi-transparent overlay
- **Print footer**: Classification stamp

#### Branding
- "XIPHOS | Intelligence-Grade Vendor Assurance" header
- Dark navy (#1a1f36) primary color
- Orange accent (#fd7e14) for emphasis
- Modern sans-serif typography

---

## Database Changes

Updated `/backend/db.py` with:

```sql
CREATE TABLE monitoring_log (
    id INTEGER PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    previous_risk TEXT,
    current_risk TEXT,
    risk_changed BOOLEAN,
    new_findings_count INTEGER,
    resolved_findings_count INTEGER,
    checked_at TEXT DEFAULT (datetime('now'))
);
```

Added indices for efficient querying by vendor, date, and risk changes.

---

## API Endpoint Suggestions

Add to `server.py`:

```python
from dossier import generate_dossier
from monitor import VendorMonitor

# Initialize monitor at server startup
monitor = VendorMonitor(check_interval=86400)
monitor.start_daemon()

@app.route("/api/cases/<case_id>/dossier")
def api_get_dossier(case_id):
    """Generate vendor intelligence dossier (PDF-ready HTML)"""
    html = generate_dossier(case_id)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}

@app.route("/api/cases/<case_id>/monitoring")
def api_monitoring_history(case_id):
    """Get monitoring check history"""
    history = db.get_monitoring_history(case_id, limit=20)
    return jsonify({"monitoring_history": history})

@app.route("/api/monitoring/recent-changes")
def api_recent_risk_changes():
    """Get recent vendors with risk tier changes"""
    changes = db.get_recent_risk_changes(limit=20)
    return jsonify({"recent_changes": changes})
```

---

## Architecture Notes

### VendorMonitor Design
- Uses finding fingerprints (MD5 of source+title+severity) to detect duplicates
- Compares old vs new enrichments to identify changes
- Generates alerts automatically for risk tier shifts
- Thread-safe background operation with clean shutdown

### Dossier Design
- All styling is inline (no external CSS files)
- Print media queries for PDF export
- Lazy loads data from DB only when needed
- Handles missing data gracefully (no crashes)
- HTML escaping prevents XSS vulnerabilities

---

## Testing

```bash
# Create test vendor
curl -X POST http://localhost:8080/api/cases \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Vendor", "country": "US"}'

# Get vendor ID from response, then test monitor
python monitor.py --vendor <vendor-id>

# Generate dossier
curl http://localhost:8080/api/cases/<vendor-id>/dossier > dossier.html

# Open in browser or convert to PDF with:
# wkhtmltopdf dossier.html dossier.pdf
```
