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


def test_stoa_acceptance_matrix_admits_ambiguity_for_vehicle_seed_when_graph_entity_memory_is_strong(monkeypatch):
    monkeypatch.setattr(
        intake_router,
        "_search_knowledge_graph_memory",
        lambda text: [{"legal_name": "LEIA, Inc.", "source": "knowledge_graph"}],
    )

    routed = intake_router.route_intake("LEIA")

    assert routed["winning_mode"] is None
    assert routed["clarifier_needed"] is True
    assert routed["hypotheses"][0]["kind"] == "vehicle"
    assert routed["hypotheses"][0]["score"] >= 0.9
    assert routed["hypotheses"][1]["kind"] == "vendor"
    assert routed["hypotheses"][1]["score"] >= 0.78


@pytest.mark.parametrize(
    "text",
    [
        "LEIA contract vehicle",
        "LEIA vehicle",
        "LEIA not a company",
    ],
)
def test_stoa_acceptance_matrix_vehicle_corrections_pivot_immediately_from_entity_narrowing(text):
    routed = intake_router.route_intake(
        text,
        current_object_type="vendor",
        in_entity_narrowing=True,
    )

    assert routed["winning_mode"] == "vehicle"
    assert routed["override_applied"] is True
    assert routed["clarifier_needed"] is False
    assert routed["anchor_text"] == "LEIA"


def test_stoa_acceptance_matrix_prefers_vendor_when_local_memory_is_strong(monkeypatch):
    monkeypatch.setattr(
        intake_router,
        "_search_local_vendor_memory",
        lambda text: [{"legal_name": "SMX LLC", "source": "local_vendor_memory"}],
    )

    routed = intake_router.route_intake("SMX")

    assert routed["winning_mode"] == "vendor"
    assert routed["clarifier_needed"] is False
    assert routed["anchor_text"] == "SMX"


def test_stoa_acceptance_matrix_handles_presolicitation_prime_vehicle_opening():
    routed = intake_router.route_intake("ILS 2 pre solicitation Amentum is prime")

    assert routed["winning_mode"] == "vehicle"
    assert routed["clarifier_needed"] is False
    assert routed["anchor_text"] == "ILS 2"


def test_stoa_router_admits_uncertainty_for_short_named_entity_without_memory():
    routed = intake_router.route_intake("SMX")

    assert routed["winning_mode"] is None
    assert routed["clarifier_needed"] is True


def test_stoa_router_admits_uncertainty_when_vehicle_and_vendor_signals_collide():
    routed = intake_router.route_intake("LEIA vendor")

    assert routed["winning_mode"] is None
    assert routed["clarifier_needed"] is True
