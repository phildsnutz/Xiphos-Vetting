import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_validation_gate_accepts_official_source_fill():
    import axiom_gap_filler
    import validation_gate

    result = axiom_gap_filler.GapFillResult(
        gap=axiom_gap_filler.IntelligenceGap(
            gap_id="gap-1",
            description="Unknown teammate",
            entity_name="SMX",
            vehicle_name="ITEAMS",
            gap_type="subcontractor_identity",
        ),
        filled=True,
        fill_confidence=0.82,
        attempts=[
            axiom_gap_filler.FillAttempt(
                approach_name="regulatory_filing_mine",
                approach_reasoning="Official program systems exposed the teammate.",
                findings=[{"source": "sam_gov", "value": "Named subcontractor on active award"}],
            )
        ],
    )

    decision = validation_gate.validate_gap_fill_result(result)

    assert decision.outcome == "accepted"
    assert decision.confidence_label == "observed"
    assert decision.graph_action == "promote"


def test_validation_gate_holds_weak_public_signal_for_review():
    import axiom_gap_filler
    import validation_gate

    result = axiom_gap_filler.GapFillResult(
        gap=axiom_gap_filler.IntelligenceGap(
            gap_id="gap-2",
            description="Possible teammate from residue",
            entity_name="SMX",
            vehicle_name="ITEAMS",
            gap_type="subcontractor_identity",
        ),
        filled=True,
        fill_confidence=0.58,
        attempts=[
            axiom_gap_filler.FillAttempt(
                approach_name="proxy_indicator_hunt",
                approach_reasoning="A public job posting suggests the relationship.",
                findings=[{"source": "careers_scraper", "value": "Mission support engineer role"}],
            )
        ],
    )

    decision = validation_gate.validate_gap_fill_result(result)

    assert decision.outcome == "review"
    assert decision.confidence_label in {"inferred", "weakly_inferred"}
    assert decision.graph_action == "hold_review"
