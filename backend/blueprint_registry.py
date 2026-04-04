"""Shared blueprint registration helpers for the main Helios Flask app."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Sequence

from flask import Flask


OPTIONAL_BLUEPRINTS: Sequence[tuple[str, str, str]] = (
    ("link_prediction_api", "link_prediction_bp", "link_prediction"),
    ("feedback_api", "feedback_bp", "feedback"),
    ("neo4j_api", "neo4j_bp", "neo4j"),
    ("screening_api", "screening_bp", "batch_screening"),
    ("server_cvi_routes", "cvi_bp", "cvi"),
)


def register_optional_blueprints(app: Flask, logger: logging.Logger) -> list[str]:
    """Register optional blueprints without hard-coding import blocks in server.py."""
    registered: list[str] = []
    for module_name, blueprint_attr, label in OPTIONAL_BLUEPRINTS:
        try:
            module = importlib.import_module(module_name)
            blueprint = getattr(module, blueprint_attr)
            app.register_blueprint(blueprint)
            logger.info("Registered %s blueprint", label)
            registered.append(label)
        except ImportError as exc:
            logger.warning("%s not available: %s", module_name, exc)
    return registered
