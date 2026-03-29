import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from transaction_authorization import (  # noqa: E402
    TransactionAuthorization,
    TransactionInput,
    TransactionOrchestratorEnhanced,
    TransactionPerson,
)


class _ScreeningResult:
    def __init__(self) -> None:
        self.id = "screen-1"
        self.screening_status = "CLEAR"
        self.composite_score = 0.1
        self.deemed_export = {"required": False}
        self.recommended_action = "allow"
        self.matched_lists = []


def test_parallel_helpers_do_not_mutate_shared_authorization_state():
    orchestrator = TransactionOrchestratorEnhanced()
    txn = TransactionInput(
        case_id="case-1",
        requested_by="tester",
        destination_country="GB",
        persons=[TransactionPerson(name="Alice Example", nationalities=["GB"])],
    )
    auth = TransactionAuthorization(id="txauth-1", case_id="case-1")

    orchestrator.build_graph = lambda _: {  # type: ignore[assignment]
        "posture": "escalate",
        "graph_intelligence": {"posture_elevated": True, "elevation_reasons": ["graph hit"]},
    }
    orchestrator.screen_person = lambda **_: _ScreeningResult()  # type: ignore[assignment]
    orchestrator.init_screening_db = lambda: None  # type: ignore[assignment]
    orchestrator.ingest_screening = None  # type: ignore[assignment]
    orchestrator.get_network_risk = None  # type: ignore[assignment]

    graph_result = orchestrator._run_graph_auth(txn, auth.id)
    person_result = orchestrator._run_person_screening(txn, auth.id)

    assert auth.pipeline_log == []
    assert graph_result.stage == "graph"
    assert graph_result.posture == "escalate"
    assert any(entry["stage"] == "graph_auth" for entry in graph_result.pipeline_log)
    assert person_result.stage == "person"
    assert len(person_result.person_results) == 1
    assert any(entry["stage"] == "person_screening" for entry in person_result.pipeline_log)


def test_authorize_merges_parallel_stage_results_on_main_thread():
    orchestrator = TransactionOrchestratorEnhanced()
    orchestrator.build_rules = lambda _: {  # type: ignore[assignment]
        "posture": "likely_nlr",
        "confidence": 0.92,
        "factors": ["clean destination"],
    }
    orchestrator.build_graph = lambda _: {  # type: ignore[assignment]
        "posture": "escalate",
        "graph_intelligence": {"posture_elevated": True, "elevation_reasons": ["graph hit"]},
    }
    orchestrator.screen_person = lambda **_: _ScreeningResult()  # type: ignore[assignment]
    orchestrator.init_screening_db = lambda: None  # type: ignore[assignment]
    orchestrator.ingest_screening = None  # type: ignore[assignment]
    orchestrator.get_network_risk = None  # type: ignore[assignment]
    orchestrator._persist = lambda auth, txn: None  # type: ignore[assignment]

    txn = TransactionInput(
        case_id="case-2",
        requested_by="tester",
        destination_country="GB",
        persons=[TransactionPerson(name="Alice Example", nationalities=["GB"])],
    )

    auth = orchestrator.authorize(txn)

    assert auth.combined_posture == "escalate"
    assert auth.graph_elevated is True
    assert auth.person_summary["total"] == 1
    stages = [entry["stage"] for entry in auth.pipeline_log]
    assert "graph_auth" in stages
    assert "person_screening" in stages
