"""
Xiphos v2.7 -- Production Hardening Module

Rate limiting, input validation, CORS lockdown, and security headers.
"""

import os
import re
import time
import threading
from functools import wraps
from collections import defaultdict

from flask import request, jsonify


# =============================================================================
# 1. Rate Limiter (in-memory, per-IP)
# =============================================================================

class RateLimiter:
    """
    Sliding-window rate limiter.

    Each key (typically an IP) gets a deque of timestamps. When a request
    arrives, we prune timestamps older than the window, then check count.
    Thread-safe via a lock.
    """

    def __init__(self):
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            bucket = self._buckets[key]
            # Prune old entries
            self._buckets[key] = [ts for ts in bucket if ts > cutoff]
            bucket = self._buckets[key]

            if len(bucket) >= max_requests:
                return False

            bucket.append(now)
            return True

    def remaining(self, key: str, max_requests: int, window_seconds: int) -> int:
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets.get(key, [])
            active = [ts for ts in bucket if ts > cutoff]
            return max(0, max_requests - len(active))


# Global limiter instance
_limiter = RateLimiter()


def rate_limit(max_requests: int = 10, window_seconds: int = 60, key_func=None):
    """
    Decorator to rate-limit a Flask route.

    Usage:
        @app.route("/api/auth/login", methods=["POST"])
        @rate_limit(max_requests=5, window_seconds=300)  # 5 per 5 min
        def login():
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if key_func:
                key = key_func()
            else:
                key = request.remote_addr or "unknown"

            if not _limiter.is_allowed(key, max_requests, window_seconds):
                remaining = _limiter.remaining(key, max_requests, window_seconds)
                return jsonify({
                    "error": "Rate limit exceeded. Try again later.",
                    "retry_after_seconds": window_seconds,
                }), 429

            return f(*args, **kwargs)
        return wrapper
    return decorator


# =============================================================================
# 2. Input Validation
# =============================================================================

# Max lengths for common fields
MAX_VENDOR_NAME = 200
MAX_COUNTRY_CODE = 4
MAX_EMAIL = 254
MAX_PASSWORD = 128
MAX_NAME = 200
MAX_PROGRAM = 50

# Safe characters for vendor names (letters, digits, spaces, basic punctuation)
VENDOR_NAME_PATTERN = re.compile(r"^[\w\s\.\,\-\&\'\(\)\/\#\+]+$", re.UNICODE)

# ISO 3166-1 alpha-2 (plus a few common extras)
COUNTRY_PATTERN = re.compile(r"^[A-Z]{2,3}$")


def validate_vendor_input(body: dict) -> tuple[bool, str]:
    """
    Validate vendor creation/screening input.
    Returns (is_valid, error_message).
    """
    name = body.get("name", "")
    country = body.get("country", "")

    if not name or not isinstance(name, str):
        return False, "Vendor name is required"

    if len(name) > MAX_VENDOR_NAME:
        return False, f"Vendor name too long (max {MAX_VENDOR_NAME} characters)"

    if not VENDOR_NAME_PATTERN.match(name):
        return False, "Vendor name contains invalid characters"

    if country:
        if not isinstance(country, str):
            return False, "Country must be a string"
        if len(country) > MAX_COUNTRY_CODE:
            return False, f"Country code too long (max {MAX_COUNTRY_CODE} characters)"
        if not COUNTRY_PATTERN.match(country.upper()):
            return False, "Country must be a valid ISO 3166-1 alpha-2/3 code (e.g., US, GB, DEU)"

    return True, ""


def validate_auth_input(body: dict, is_setup: bool = False) -> tuple[bool, str]:
    """
    Validate authentication input (login, setup, user creation).
    """
    email = body.get("email", "")
    password = body.get("password", "")

    if not email or not isinstance(email, str):
        return False, "Email is required"

    if len(email) > MAX_EMAIL:
        return False, f"Email too long (max {MAX_EMAIL} characters)"

    # Basic email format check
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return False, "Invalid email format"

    if not password or not isinstance(password, str):
        return False, "Password is required"

    if len(password) < 8:
        return False, "Password must be at least 8 characters"

    if len(password) > MAX_PASSWORD:
        return False, f"Password too long (max {MAX_PASSWORD} characters)"

    if is_setup:
        name = body.get("name", "")
        if name and len(name) > MAX_NAME:
            return False, f"Name too long (max {MAX_NAME} characters)"

    return True, ""


def validate_program(program: str) -> tuple[bool, str]:
    """Validate program type."""
    if not isinstance(program, str):
        return False, "Program must be a string"
    if len(program) > MAX_PROGRAM:
        return False, f"Program type too long (max {MAX_PROGRAM} characters)"
    valid_programs = [
        "standard_industrial", "weapons_system", "mission_critical",
        "nuclear_related", "intelligence_community", "critical_infrastructure",
    ]
    if program and program not in valid_programs:
        return False, f"Invalid program type. Valid: {', '.join(valid_programs)}"
    return True, ""


# =============================================================================
# 3. CORS Lockdown
# =============================================================================

def configure_cors(app, allowed_origins=None):
    """
    Configure CORS for production.

    If XIPHOS_CORS_ORIGINS is set, only those origins are allowed.
    Otherwise, in dev mode, allow all origins.

    Usage in server.py:
        configure_cors(app)
    """
    from flask_cors import CORS

    env_origins = os.environ.get("XIPHOS_CORS_ORIGINS", "")

    if allowed_origins:
        origins = allowed_origins
    elif env_origins:
        origins = [o.strip() for o in env_origins.split(",") if o.strip()]
    else:
        # No wildcard with credentials (spec violation). Default to same-origin only.
        # Set XIPHOS_CORS_ORIGINS for cross-origin access.
        origins = []

    if origins:
        CORS(app, origins=origins, supports_credentials=True)
    # If no origins configured, Flask default is same-origin only (no CORS headers)


# =============================================================================
# 4. Security Headers
# =============================================================================

def add_security_headers(app):
    """
    Add standard security headers to all responses.
    """
    @app.after_request
    def _security_headers(response):
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # XSS protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Content Security Policy (basic)
        if response.content_type and "text/html" in response.content_type:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; "
                "font-src 'self'; "
                "connect-src 'self'; "
                "frame-ancestors 'none'"
            )
        # HSTS (only effective over HTTPS, harmless over HTTP)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def reset_rate_limiter() -> None:
    """Test helper to clear the in-memory rate limiter state."""
    _limiter.reset()
