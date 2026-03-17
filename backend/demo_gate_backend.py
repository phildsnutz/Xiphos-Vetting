"""
Demo Gate Backend Module
Handles email capture, registration, and rate limiting for the Xiphos demo.

Tables:
  - demo_leads: Stores email capture data with tracking
"""

import sqlite3
import json
import secrets
from datetime import datetime, timedelta
from functools import wraps

# ============================================================================
# DATABASE SETUP
# ============================================================================

DEMO_DB = "demo_leads.db"


def init_demo_db():
    """Initialize demo_leads table if it doesn't exist."""
    conn = sqlite3.connect(DEMO_DB)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS demo_leads (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            organization TEXT,
            role TEXT,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            ip_address TEXT,
            demo_runs INTEGER DEFAULT 0,
            last_demo_at TEXT,
            session_token TEXT,
            session_expires_at TEXT
        )
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_email ON demo_leads(email)
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_ip ON demo_leads(ip_address)
    """)

    conn.commit()
    conn.close()


def get_demo_db():
    """Get a database connection."""
    conn = sqlite3.connect(DEMO_DB)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================================
# DEMO LEAD OPERATIONS
# ============================================================================

def register_demo_lead(email: str, name: str, organization: str = None,
                      role: str = None, source: str = None, ip_address: str = None) -> dict:
    """
    Register a new demo lead or update existing one.
    Creates a session token valid for 24 hours.

    Returns:
        dict with lead_id, session_token, session_expires_at, is_new (bool)
    """
    conn = get_demo_db()
    c = conn.cursor()

    email = email.strip().lower()

    try:
        # Check if lead already exists
        c.execute("SELECT id, session_token, session_expires_at FROM demo_leads WHERE email = ?",
                  (email,))
        existing = c.fetchone()

        now = datetime.utcnow().isoformat()
        expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()
        session_token = secrets.token_urlsafe(32)

        if existing:
            # Update existing lead
            c.execute("""
                UPDATE demo_leads
                SET session_token = ?, session_expires_at = ?,
                    demo_runs = demo_runs + 1, last_demo_at = ?
                WHERE id = ?
            """, (session_token, expires_at, now, existing["id"]))

            conn.commit()
            conn.close()

            return {
                "lead_id": existing["id"],
                "session_token": session_token,
                "session_expires_at": expires_at,
                "is_new": False,
            }
        else:
            # Create new lead
            lead_id = f"lead_{secrets.token_hex(8)}"
            c.execute("""
                INSERT INTO demo_leads
                (id, email, name, organization, role, source, created_at, ip_address,
                 demo_runs, last_demo_at, session_token, session_expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """, (lead_id, email, name, organization, role, source, now, ip_address,
                  now, session_token, expires_at))

            conn.commit()
            conn.close()

            return {
                "lead_id": lead_id,
                "session_token": session_token,
                "session_expires_at": expires_at,
                "is_new": True,
            }

    except sqlite3.IntegrityError as e:
        conn.close()
        raise ValueError(f"Email already registered: {email}")
    except Exception as e:
        conn.close()
        raise


def verify_session_token(session_token: str) -> dict or None:
    """
    Verify a session token and return lead info if valid.

    Returns:
        dict with lead info if token is valid and not expired, None otherwise
    """
    conn = get_demo_db()
    c = conn.cursor()

    now = datetime.utcnow().isoformat()

    c.execute("""
        SELECT id, email, name, organization, role, session_expires_at
        FROM demo_leads
        WHERE session_token = ? AND session_expires_at > ?
    """, (session_token, now))

    result = c.fetchone()
    conn.close()

    if result:
        return {
            "lead_id": result["id"],
            "email": result["email"],
            "name": result["name"],
            "organization": result["organization"],
            "role": result["role"],
            "session_expires_at": result["session_expires_at"],
        }

    return None


def check_rate_limit(email: str) -> tuple[bool, dict]:
    """
    Check if email has exceeded demo runs for today (10 per day limit).

    Returns:
        (is_allowed: bool, info: dict with details)
    """
    conn = get_demo_db()
    c = conn.cursor()

    email = email.strip().lower()
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    c.execute("""
        SELECT demo_runs, last_demo_at FROM demo_leads
        WHERE email = ?
    """, (email,))

    result = c.fetchone()
    conn.close()

    if not result:
        return True, {"runs_today": 0, "limit": 10}

    # Count runs since today started
    last_demo = datetime.fromisoformat(result["last_demo_at"]) if result["last_demo_at"] else None

    if last_demo and last_demo.isoformat() >= today_start:
        # Last run was today, check total count
        if result["demo_runs"] >= 10:
            return False, {
                "runs_today": result["demo_runs"],
                "limit": 10,
                "message": "You've reached the demo limit for today. Please try again tomorrow."
            }

    return True, {"runs_today": result["demo_runs"], "limit": 10}


def get_all_leads(offset: int = 0, limit: int = 100) -> tuple[list[dict], int]:
    """
    Get all demo leads (admin endpoint).

    Returns:
        (leads: list, total_count: int)
    """
    conn = get_demo_db()
    c = conn.cursor()

    # Get total count
    c.execute("SELECT COUNT(*) as count FROM demo_leads")
    total = c.fetchone()["count"]

    # Get paginated results
    c.execute("""
        SELECT id, email, name, organization, role, source, created_at,
               demo_runs, last_demo_at
        FROM demo_leads
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, (limit, offset))

    leads = [dict(row) for row in c.fetchall()]
    conn.close()

    return leads, total


def export_leads_csv() -> str:
    """
    Export all demo leads as CSV string.

    Returns:
        CSV content (string)
    """
    import csv
    import io

    conn = get_demo_db()
    c = conn.cursor()

    c.execute("""
        SELECT id, email, name, organization, role, source, created_at,
               demo_runs, last_demo_at
        FROM demo_leads
        ORDER BY created_at DESC
    """)

    leads = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["ID", "Email", "Name", "Organization", "Role", "Source",
                     "Created At", "Demo Runs", "Last Demo At"])

    for lead in leads:
        writer.writerow([
            lead["id"],
            lead["email"],
            lead["name"],
            lead["organization"],
            lead["role"],
            lead["source"],
            lead["created_at"],
            lead["demo_runs"],
            lead["last_demo_at"],
        ])

    return output.getvalue()


# ============================================================================
# FLASK ROUTE HANDLERS (to be imported in server.py)
# ============================================================================

def register_demo_routes(app, require_auth=None):
    """
    Register demo gate routes on the Flask app.

    Args:
        app: Flask application
        require_auth: optional decorator function for authenticated endpoints
    """
    from flask import request, jsonify

    @app.route("/api/demo/register", methods=["POST"])
    def api_demo_register():
        """
        Register for demo access.

        Request body:
        {
            "email": "user@example.com",
            "name": "John Doe",
            "organization": "ACME Corp",
            "role": "Procurement Manager",
            "source": "LinkedIn"  // LinkedIn, Referral, Conference, Search, Other
        }

        Response:
        {
            "success": true,
            "lead_id": "lead_...",
            "session_token": "...",
            "session_expires_at": "2026-03-18T...",
            "is_new": true
        }
        """
        body = request.get_json(silent=True) or {}

        email = (body.get("email") or "").strip()
        name = (body.get("name") or "").strip()
        organization = (body.get("organization") or "").strip() or None
        role = (body.get("role") or "").strip() or None
        source = (body.get("source") or "").strip() or "Other"

        # Validate required fields
        if not email or "@" not in email:
            return jsonify({"error": "Valid email is required"}), 400
        if not name or len(name) < 2:
            return jsonify({"error": "Full name is required (min 2 characters)"}), 400

        # Validate source
        valid_sources = ["LinkedIn", "Referral", "Conference", "Search", "Other"]
        if source not in valid_sources:
            source = "Other"

        ip_address = request.remote_addr

        try:
            result = register_demo_lead(
                email=email,
                name=name,
                organization=organization,
                role=role,
                source=source,
                ip_address=ip_address
            )

            return jsonify({
                "success": True,
                **result
            }), 201

        except ValueError as e:
            return jsonify({"error": str(e)}), 409
        except Exception as e:
            return jsonify({"error": "Failed to register: " + str(e)}), 500


    @app.route("/api/demo/verify-session", methods=["GET"])
    def api_demo_verify_session():
        """
        Verify a demo session token.

        Query params:
        - token: session token

        Response:
        {
            "valid": true,
            "lead": { ... }
        }
        or
        {
            "valid": false
        }
        """
        token = request.args.get("token", "").strip()

        if not token:
            return jsonify({"valid": False}), 400

        lead = verify_session_token(token)

        if lead:
            return jsonify({
                "valid": True,
                "lead": lead
            })
        else:
            return jsonify({"valid": False}), 401


    @app.route("/api/demo/check-rate-limit", methods=["GET"])
    def api_demo_check_rate_limit():
        """
        Check if email has demo runs available for today.

        Query params:
        - email: email address

        Response:
        {
            "allowed": true,
            "runs_today": 2,
            "limit": 10
        }
        """
        email = request.args.get("email", "").strip()

        if not email or "@" not in email:
            return jsonify({"error": "Valid email is required"}), 400

        allowed, info = check_rate_limit(email)

        return jsonify({
            "allowed": allowed,
            **info
        })


    @app.route("/api/demo/leads", methods=["GET"])
    def api_demo_leads():
        """
        Get all demo leads (admin-only).

        Query params:
        - offset: pagination offset (default: 0)
        - limit: results per page (default: 100, max: 500)
        - format: 'json' (default) or 'csv'

        Requires authentication and admin role.
        """
        # Check authentication if require_auth is provided
        if require_auth:
            require_auth("admin")(lambda: None)()

        try:
            offset = int(request.args.get("offset", 0))
            limit = int(request.args.get("limit", 100))
            format_type = request.args.get("format", "json")

            offset = max(0, offset)
            limit = min(500, max(1, limit))

            if format_type == "csv":
                csv_content = export_leads_csv()
                from flask import make_response
                response = make_response(csv_content)
                response.headers["Content-Type"] = "text/csv"
                response.headers["Content-Disposition"] = "attachment; filename=demo_leads.csv"
                return response

            leads, total = get_all_leads(offset=offset, limit=limit)

            return jsonify({
                "leads": leads,
                "total": total,
                "offset": offset,
                "limit": limit,
                "pages": (total + limit - 1) // limit
            })

        except Exception as e:
            return jsonify({"error": str(e)}), 500


# ============================================================================
# INITIALIZATION
# ============================================================================

if __name__ == "__main__":
    init_demo_db()
    print("Demo database initialized.")
