import os
import sys

from flask import Flask, g, jsonify, request


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import hardening  # type: ignore


def _build_app():
    app = Flask(__name__)

    @app.before_request
    def _inject_user():
        user_id = request.headers.get("X-Test-User", "").strip()
        g.user = {"sub": user_id} if user_id else {}

    @app.route("/route-a")
    @hardening.rate_limit(max_requests=1, window_seconds=60)
    def route_a():
        return jsonify({"ok": True, "route": "a"})

    @app.route("/route-b")
    @hardening.rate_limit(max_requests=1, window_seconds=60)
    def route_b():
        return jsonify({"ok": True, "route": "b"})

    return app


def test_rate_limit_buckets_are_scoped_per_route():
    hardening.reset_rate_limiter()
    app = _build_app()

    with app.test_client() as client:
        first = client.get("/route-a", headers={"X-Test-User": "user-1"})
        second = client.get("/route-b", headers={"X-Test-User": "user-1"})
        third = client.get("/route-a", headers={"X-Test-User": "user-1"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


def test_rate_limit_buckets_are_scoped_per_authenticated_user():
    hardening.reset_rate_limiter()
    app = _build_app()

    with app.test_client() as client:
        first = client.get("/route-a", headers={"X-Test-User": "user-1"})
        second = client.get("/route-a", headers={"X-Test-User": "user-2"})
        third = client.get("/route-a", headers={"X-Test-User": "user-1"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
