"""
Xiphos Authentication, RBAC, and Audit Logging

JWT-based authentication with role-based access control for defense
acquisition vendor vetting workflows.

Roles:
  admin    - Full access: user management, system config, all operations
  analyst  - Score vendors, run enrichments, generate dossiers, manage cases
  reviewer - Read-only access to cases, scores, and enrichment reports
  auditor  - Read-only access to everything including audit logs

Audit logging captures every authenticated API action with:
  - Who (user_id, email, role)
  - What (action, resource, resource_id)
  - When (timestamp, UTC)
  - Where (IP address, user-agent)
  - Outcome (status_code, error if any)

Storage: SQLite (same DB as main app for simplicity).
Production recommendation: swap to PostgreSQL + dedicated audit service.
"""

import os
import json
import time
import uuid
import hmac
import hashlib
import base64
import sqlite3
import functools
from datetime import datetime, timedelta, timezone

from flask import request, jsonify, g
from runtime_paths import get_main_db_path, get_secret

# ---- Configuration ----
AUTH_ENABLED = os.environ.get("XIPHOS_AUTH_ENABLED", "false").lower() == "true"

# SECRET_KEY: must be set in production if AUTH_ENABLED.
# In dev/test when auth is disabled, an ephemeral process-local key is used.
SECRET_KEY = get_secret("XIPHOS_SECRET_KEY", allow_ephemeral_dev=not AUTH_ENABLED)
if AUTH_ENABLED and not SECRET_KEY:
    raise RuntimeError(
        "SECURITY ERROR: XIPHOS_AUTH_ENABLED=true but XIPHOS_SECRET_KEY is missing or placeholder-valued. "
        "Set a strong XIPHOS_SECRET_KEY environment variable before starting the server."
    )

TOKEN_EXPIRY_HOURS = int(os.environ.get("XIPHOS_TOKEN_EXPIRY_HOURS", "8"))

# Password hashing iterations (PBKDF2-SHA256)
HASH_ITERATIONS = 260_000


# ---- Role Definitions ----
ROLES = {
    "admin":    {"level": 100, "description": "Full system access"},
    "analyst":  {"level": 50,  "description": "Score, enrich, generate dossiers"},
    "reviewer": {"level": 20,  "description": "Read-only access to cases and reports"},
    "auditor":  {"level": 30,  "description": "Read-only access including audit logs"},
}

# Permission matrix: action -> minimum role level
PERMISSIONS = {
    # Case management
    "cases:read":          20,   # reviewer+
    "cases:create":        50,   # analyst+
    "cases:score":         50,   # analyst+
    "cases:enrich":        50,   # analyst+
    "cases:dossier":       50,   # analyst+
    "cases:decide":        50,   # analyst+

    # Screening
    "screen:run":          50,   # analyst+
    "screen:read":         20,   # reviewer+

    # Monitoring
    "monitor:run":         50,   # analyst+
    "monitor:read":        20,   # reviewer+

    # Alerts
    "alerts:read":         20,   # reviewer+
    "alerts:resolve":      50,   # analyst+

    # Graph / entity resolution
    "graph:read":          20,   # reviewer+

    # Enrichment
    "enrich:run":          50,   # analyst+
    "enrich:read":         20,   # reviewer+

    # AI Analysis
    "ai:config":           50,   # analyst+
    "ai:analyze":          50,   # analyst+

    # Public endpoints (no auth required)
    "public":              0,    # anyone (unauthenticated, rate-limited)
    "health:read":         0,    # anyone (even unauthenticated)

    # Admin
    "users:manage":        100,  # admin only
    "audit:read":          30,   # auditor+
    "system:config":       100,  # admin only
}


# ---- Database Setup ----
def _get_auth_db_path():
    return get_main_db_path()


def init_auth_db():
    """Create auth and audit tables."""
    db_path = _get_auth_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          TEXT PRIMARY KEY,
            email       TEXT UNIQUE NOT NULL,
            name        TEXT NOT NULL DEFAULT '',
            role        TEXT NOT NULL DEFAULT 'reviewer',
            password_hash TEXT NOT NULL,
            salt        TEXT NOT NULL,
            active      INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
            last_login  TEXT
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
            user_id     TEXT,
            email       TEXT,
            role        TEXT,
            action      TEXT NOT NULL,
            resource    TEXT,
            resource_id TEXT,
            method      TEXT,
            path        TEXT,
            ip_address  TEXT,
            user_agent  TEXT,
            status_code INTEGER,
            detail      TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
        CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
    """)

    # Migration: add must_change_password column to existing databases
    try:
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Set must_change_password=1 for all partner accounts (non-admin) that haven't changed yet
    conn.execute("""
        UPDATE users SET must_change_password = 1
        WHERE role != 'admin' AND must_change_password = 0
        AND last_login IS NULL
    """)
    conn.commit()
    conn.close()


# ---- Password Hashing (PBKDF2-SHA256) ----
def _hash_password(password: str, salt: str = "") -> tuple[str, str]:
    """Hash a password with PBKDF2-SHA256. Returns (hash, salt)."""
    if not salt:
        salt = base64.b64encode(os.urandom(32)).decode("utf-8")
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        HASH_ITERATIONS,
    )
    return base64.b64encode(dk).decode("utf-8"), salt


def _verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify a password against stored hash."""
    computed, _ = _hash_password(password, salt)
    return hmac.compare_digest(computed, stored_hash)


# ---- JWT-like Token (HMAC-SHA256, no external deps) ----
def _create_token(user_id: str, email: str, role: str) -> str:
    """Create a signed bearer token."""
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + TOKEN_EXPIRY_HOURS * 3600,
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).decode()
    sig = hmac.new(
        SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def _decode_token(token: str) -> dict | None:
    """Decode and verify a bearer token. Returns payload or None."""
    parts = token.split(".")
    if len(parts) != 2:
        return None
    payload_b64, sig = parts
    expected_sig = hmac.new(
        SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except (json.JSONDecodeError, ValueError):
        return None
    # Check expiry
    if payload.get("exp", 0) < time.time():
        return None
    return payload


# ---- Audit Logging ----
def log_audit(action: str, resource: str = "", resource_id: str = "",
              status_code: int = 200, detail: str = ""):
    """Write an entry to the audit log."""
    user = getattr(g, "user", None) or {}
    try:
        db_path = _get_auth_db_path()
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("""
            INSERT INTO audit_log
                (user_id, email, role, action, resource, resource_id,
                 method, path, ip_address, user_agent, status_code, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user.get("sub", "anonymous"),
            user.get("email", ""),
            user.get("role", ""),
            action,
            resource,
            resource_id,
            request.method if request else "",
            request.path if request else "",
            request.remote_addr if request else "",
            (request.headers.get("User-Agent", "") if request else "")[:200],
            status_code,
            detail[:1000] if detail else "",
        ))
        conn.commit()
        conn.close()
    except Exception:
        pass  # Audit logging should never break the main application


def get_audit_log(limit: int = 100, offset: int = 0,
                  user_id: str = "", action: str = "") -> list[dict]:
    """Query audit log entries."""
    db_path = _get_auth_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM audit_log WHERE 1=1"
    params: list = []

    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)
    if action:
        query += " AND action = ?"
        params.append(action)

    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- User Management ----
def create_user(email: str, password: str, name: str = "",
                role: str = "reviewer", must_change_password: bool = True) -> dict:
    """Create a new user. Returns user dict (no password).
    must_change_password defaults to True so new users are forced to set their own password."""
    if role not in ROLES:
        raise ValueError(f"Invalid role: {role}")

    user_id = str(uuid.uuid4())[:8]
    pw_hash, salt = _hash_password(password)

    db_path = _get_auth_db_path()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            INSERT INTO users (id, email, name, role, password_hash, salt, must_change_password)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, email, name, role, pw_hash, salt, 1 if must_change_password else 0))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError(f"User with email '{email}' already exists")
    conn.close()

    return {"id": user_id, "email": email, "name": name, "role": role, "must_change_password": must_change_password}


def authenticate(email: str, password: str) -> dict | None:
    """Authenticate user. Returns token dict or None."""
    db_path = _get_auth_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM users WHERE email = ? AND active = 1", (email,)
    ).fetchone()

    if not row:
        conn.close()
        return None

    if not _verify_password(password, row["password_hash"], row["salt"]):
        conn.close()
        return None

    # Update last login
    conn.execute(
        "UPDATE users SET last_login = datetime('now') WHERE id = ?",
        (row["id"],)
    )
    conn.commit()
    conn.close()

    token = _create_token(row["id"], row["email"], row["role"])
    must_change = bool(row["must_change_password"]) if "must_change_password" in row.keys() else False
    return {
        "token": token,
        "user": {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "role": row["role"],
        },
        "must_change_password": must_change,
        "expires_in": TOKEN_EXPIRY_HOURS * 3600,
    }


def list_users() -> list[dict]:
    """List all users (no passwords)."""
    db_path = _get_auth_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, email, name, role, active, created_at, last_login FROM users"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- Flask Middleware ----
def require_auth(permission: str):
    """
    Decorator that enforces authentication and RBAC on a Flask route.

    Usage:
        @app.route("/api/cases", methods=["POST"])
        @require_auth("cases:create")
        def create_case():
            ...

    When AUTH_ENABLED is False, protected routes only allow anonymous admin
    passthrough if XIPHOS_DEV_MODE=true. Otherwise, public endpoints remain
    anonymous and protected routes still require a valid token.
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            # Only allow unauthenticated access if AUTH is disabled AND XIPHOS_DEV_MODE is explicitly set
            dev_mode = os.environ.get("XIPHOS_DEV_MODE", "false").lower() == "true"
            if not AUTH_ENABLED and dev_mode:
                # Dev mode: everyone is admin (only with explicit XIPHOS_DEV_MODE=true)
                g.user = {"sub": "dev", "email": "dev@xiphos", "role": "admin"}
                return f(*args, **kwargs)

            # Public endpoints (permission level 0) allow anonymous access
            required_level = PERMISSIONS.get(permission, 100)
            if required_level == 0:
                g.user = {"sub": "anonymous", "email": "", "role": ""}
                return f(*args, **kwargs)

            # Extract token from Authorization header (preferred) or query param (SSE only)
            auth_header = request.headers.get("Authorization", "")
            token = None
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            elif request.args.get("sse_token") or request.args.get("token"):
                # Query-string tokens only for SSE endpoints (EventSource cannot set headers)
                # Restrict to streaming paths to minimize token exposure in URLs/logs
                sse_paths = ("/enrich-stream", "/monitor-stream")
                if any(request.path.endswith(p) for p in sse_paths):
                    token = request.args.get("sse_token") or request.args.get("token")
                # Non-SSE endpoints must use Authorization header

            if not token:
                log_audit("auth_failed", detail="Missing bearer token")
                return jsonify({"error": "Authentication required"}), 401
            payload = _decode_token(token)
            if not payload:
                log_audit("auth_failed", detail="Invalid or expired token")
                return jsonify({"error": "Invalid or expired token"}), 401

            # Check RBAC
            required_level = PERMISSIONS.get(permission, 100)
            user_role = payload.get("role", "")
            user_level = ROLES.get(user_role, {}).get("level", 0)

            if user_level < required_level:
                log_audit(
                    "access_denied",
                    detail=f"Role '{user_role}' lacks permission '{permission}'"
                )
                return jsonify({
                    "error": f"Insufficient permissions. Required: {permission}"
                }), 403

            # Set user context for downstream use
            g.user = payload
            return f(*args, **kwargs)

        return wrapper
    return decorator


# ---- Auth API Routes ----
def register_auth_routes(app):
    """Register authentication and user management routes on the Flask app."""

    @app.route("/api/auth/login", methods=["POST"])
    def auth_login():
        """Authenticate and receive a bearer token. Rate limited: 5 per 5 min per IP."""
        # Rate limit: import here to avoid circular imports at module level
        from hardening import rate_limit as _rl, validate_auth_input as _vai

        # Inline rate check (5 attempts per 5 minutes per IP)
        from hardening import _limiter
        client_ip = request.remote_addr or "unknown"
        if not _limiter.is_allowed(f"login:{client_ip}", 5, 300):
            log_audit("login_rate_limited", detail=f"Rate limited login from {client_ip}")
            return jsonify({
                "error": "Too many login attempts. Try again in 5 minutes.",
                "retry_after_seconds": 300,
            }), 429

        body = request.get_json(silent=True) or {}

        # Validate input
        valid, err = _vai(body)
        if not valid:
            return jsonify({"error": err}), 400

        email = body.get("email", "")
        password = body.get("password", "")

        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400

        result = authenticate(email, password)
        if not result:
            log_audit("login_failed", detail=f"Failed login for {email}")
            return jsonify({"error": "Invalid credentials"}), 401

        log_audit("login_success", detail=f"User {email} logged in")
        return jsonify(result)

    @app.route("/api/auth/me", methods=["GET"])
    @require_auth("cases:read")
    def auth_me():
        """Get current user info from token."""
        return jsonify(g.user)

    @app.route("/api/auth/users", methods=["GET"])
    @require_auth("users:manage")
    def auth_list_users():
        """List all users (admin only)."""
        return jsonify(list_users())

    @app.route("/api/auth/users", methods=["POST"])
    @require_auth("users:manage")
    def auth_create_user():
        """Create a new user (admin only)."""
        body = request.get_json(silent=True) or {}
        try:
            user = create_user(
                email=body.get("email", ""),
                password=body.get("password", ""),
                name=body.get("name", ""),
                role=body.get("role", "reviewer"),
            )
            log_audit("user_created", "user", user["id"],
                      detail=f"Created user {user['email']} with role {user['role']}")
            return jsonify(user), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/auth/change-password", methods=["POST"])
    @require_auth("cases:read")
    def auth_change_password():
        """Change password for current user. Required on first login when must_change_password is set."""
        body = request.get_json(silent=True) or {}
        new_password = body.get("new_password", "")
        if not new_password or len(new_password) < 8:
            return jsonify({"error": "New password must be at least 8 characters"}), 400

        user_id = g.user["sub"]
        pw_hash, salt = _hash_password(new_password)
        db_path = _get_auth_db_path()
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE users SET password_hash = ?, salt = ?, must_change_password = 0, updated_at = datetime('now') WHERE id = ?",
            (pw_hash, salt, user_id)
        )
        conn.commit()
        conn.close()
        log_audit("password_changed", "user", user_id, detail=f"Password changed for user {g.user['email']}")
        return jsonify({"status": "ok", "message": "Password updated successfully"})

    @app.route("/api/audit", methods=["GET"])
    @require_auth("audit:read")
    def auth_audit_log():
        """Query audit log (auditor+ only)."""
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)
        user_id = request.args.get("user_id", "")
        action = request.args.get("action", "")
        entries = get_audit_log(limit, offset, user_id, action)
        return jsonify(entries)

    @app.route("/api/auth/setup", methods=["POST"])
    def auth_setup():
        """
        One-time setup: create the initial admin user.
        Only works when no users exist in the database.
        Rate-limited to prevent brute force on setup.
        """
        # Rate limit: max 5 attempts per minute (for mistyped credentials, etc)
        from hardening import _limiter
        key = request.remote_addr or "unknown"
        if not _limiter.is_allowed(f"setup:{key}", max_requests=5, window_seconds=60):
            return jsonify({"error": "Setup endpoint rate limited. Too many attempts."}), 429
        db_path = _get_auth_db_path()
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()

        if count > 0:
            return jsonify({"error": "Setup already complete. Users exist."}), 400

        body = request.get_json(silent=True) or {}

        from hardening import validate_auth_input as _vai
        valid, err = _vai(body, is_setup=True)
        if not valid:
            return jsonify({"error": err}), 400

        email = body.get("email", "")
        password = body.get("password", "")
        name = body.get("name", "Admin")

        try:
            user = create_user(email, password, name, role="admin")
            log_audit("setup_complete", "system", "",
                      detail=f"Initial admin user created: {email}")
            token_data = authenticate(email, password)
            return jsonify({
                "message": "Admin user created successfully",
                "user": user,
                "token": token_data["token"] if token_data else None,
            }), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
