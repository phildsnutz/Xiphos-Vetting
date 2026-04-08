"""
Shared snapshot-aware GraphAnalytics runtime.

Graph-heavy routes should reuse one in-process analytics snapshot instead of
rebuilding the same graph world independently for every endpoint family.
"""

from __future__ import annotations

import logging
import time
import threading
from typing import Any, Callable

from graph_analytics import GraphAnalytics
from knowledge_graph import get_graph_snapshot_signature


LOGGER = logging.getLogger(__name__)
_RUNTIME_LOCK = threading.RLock()
_RUNTIME: dict[str, Any] = {
    "snapshot": "",
    "factory_key": "",
    "analytics": None,
    "warm_state": {
        "status": "idle",
        "started_at": None,
        "completed_at": None,
        "duration_ms": None,
        "error": "",
    },
}


def _factory_key(factory: Callable[[], Any]) -> str:
    module = getattr(factory, "__module__", "")
    qualname = getattr(factory, "__qualname__", getattr(factory, "__name__", repr(factory)))
    return f"{module}:{qualname}"


def load_cached_graph_analytics(
    *,
    analytics_factory: Callable[[], Any] = GraphAnalytics,
    limit: int = 50000,
):
    factory_key = _factory_key(analytics_factory)
    try:
        snapshot = get_graph_snapshot_signature()
    except Exception:
        snapshot = f"unavailable:{factory_key}"

    with _RUNTIME_LOCK:
        cached = _RUNTIME.get("analytics")
        cached_snapshot = str(_RUNTIME.get("snapshot") or "")
        cached_factory_key = str(_RUNTIME.get("factory_key") or "")
        cached_ready = cached is not None and bool(getattr(cached, "loaded", True))
        if cached_ready and cached_snapshot == snapshot and cached_factory_key == factory_key:
            return cached

        analytics = analytics_factory()
        load_graph = getattr(analytics, "load_graph", None)
        if callable(load_graph):
            try:
                load_graph(limit=limit)
            except TypeError:
                load_graph()

        _RUNTIME["snapshot"] = snapshot
        _RUNTIME["factory_key"] = factory_key
        _RUNTIME["analytics"] = analytics
        return analytics


def reset_cached_graph_analytics() -> None:
    with _RUNTIME_LOCK:
        _RUNTIME["snapshot"] = ""
        _RUNTIME["factory_key"] = ""
        _RUNTIME["analytics"] = None
        _RUNTIME["warm_state"] = {
            "status": "idle",
            "started_at": None,
            "completed_at": None,
            "duration_ms": None,
            "error": "",
        }


def get_graph_runtime_status() -> dict[str, Any]:
    with _RUNTIME_LOCK:
        state = dict(_RUNTIME.get("warm_state") or {})
        state["snapshot"] = str(_RUNTIME.get("snapshot") or "")
        state["factory_key"] = str(_RUNTIME.get("factory_key") or "")
        state["loaded"] = _RUNTIME.get("analytics") is not None
        return state


def warm_cached_graph_analytics(
    *,
    analytics_factory: Callable[[], Any] = GraphAnalytics,
    limit: int = 50000,
) -> dict[str, Any]:
    started_at = time.time()
    with _RUNTIME_LOCK:
        _RUNTIME["warm_state"] = {
            "status": "warming",
            "started_at": started_at,
            "completed_at": None,
            "duration_ms": None,
            "error": "",
        }

    try:
        analytics = load_cached_graph_analytics(
            analytics_factory=analytics_factory,
            limit=limit,
        )
        analytics.compute_all_centrality()
        analytics.detect_communities()
        analytics.compute_sanctions_exposure()
        analytics.compute_temporal_profile()
        completed_at = time.time()
        result = {
            "status": "ready",
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": round((completed_at - started_at) * 1000, 2),
            "error": "",
        }
        with _RUNTIME_LOCK:
            _RUNTIME["warm_state"] = result
        return result
    except Exception as exc:
        completed_at = time.time()
        message = str(exc)
        result = {
            "status": "failed",
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": round((completed_at - started_at) * 1000, 2),
            "error": message,
        }
        with _RUNTIME_LOCK:
            _RUNTIME["warm_state"] = result
        LOGGER.warning("graph_runtime: warm-up failed: %s", message)
        return result
