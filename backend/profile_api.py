"""Compliance profile API blueprint."""

from __future__ import annotations

from flask import Blueprint, jsonify

from auth import require_auth
from profiles import get_profile, list_profiles, profile_to_dict


profile_bp = Blueprint("profiles", __name__, url_prefix="/api/profiles")


@profile_bp.route("", methods=["GET"])
@require_auth("health:read")
def list_profile_configs():
    """List all compliance profiles."""
    return jsonify({"profiles": [profile_to_dict(profile) for profile in list_profiles()]})


@profile_bp.route("/<profile_id>", methods=["GET"])
@require_auth("health:read")
def get_profile_config(profile_id: str):
    """Get a single compliance profile by ID."""
    profile = get_profile(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify(profile_to_dict(profile))
