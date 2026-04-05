import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


import intake_router  # type: ignore  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_memory(monkeypatch):
    monkeypatch.setattr(intake_router, "_search_local_vendor_memory", lambda text: [])
    monkeypatch.setattr(intake_router, "_search_knowledge_graph_memory", lambda text: [])


def test_route_intake_prefers_known_vehicle_seed():
    routed = intake_router.route_intake("LEIA")

    assert routed["winning_mode"] == "vehicle"
    assert routed["clarifier_needed"] is False


def test_route_intake_allows_vehicle_override_during_entity_narrowing():
    routed = intake_router.route_intake(
        "LEIA contract vehicle",
        current_object_type="vendor",
        in_entity_narrowing=True,
    )

    assert routed["winning_mode"] == "vehicle"
    assert routed["override_applied"] is True
    assert routed["clarifier_needed"] is False


def test_route_intake_prefers_vendor_when_local_memory_is_strong(monkeypatch):
    monkeypatch.setattr(
        intake_router,
        "_search_local_vendor_memory",
        lambda text: [{"legal_name": "SMX LLC", "source": "local_vendor_memory"}],
    )

    routed = intake_router.route_intake("SMX")

    assert routed["winning_mode"] == "vendor"
    assert routed["clarifier_needed"] is False


def test_route_intake_handles_existing_vehicle_style_prompt():
    routed = intake_router.route_intake("ILS 2 pre solicitation Amentum is prime")

    assert routed["winning_mode"] == "vehicle"
    assert routed["clarifier_needed"] is False
