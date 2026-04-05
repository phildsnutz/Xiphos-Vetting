import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from helios_core.brief_engine import _build_axiom_assessment, _collect_gap_lines, _collect_passport_gaps  # type: ignore  # noqa: E402
from helios_core.recommendations import resolve_case_recommendation  # type: ignore  # noqa: E402


def test_recommendation_does_not_downgrade_clean_approved_case_for_watch_only_tribunal():
    recommendation = resolve_case_recommendation(
        score={"calibrated": {"calibrated_tier": "TIER_4_APPROVED"}},
        supplier_passport={
            "posture": "approved",
            "tribunal": {"recommended_label": "Watch / Conditional"},
        },
        latest_decision=None,
    )

    assert recommendation["posture"] == "approved"
    assert recommendation["label"] == "APPROVED"
    assert recommendation["score_posture"] == "approved"
    assert recommendation["passport_posture"] == "approved"
    assert recommendation["tribunal_posture"] == "review"


def test_brief_gap_language_groups_identity_thinness_and_keeps_tribunal_as_counterview():
    context = {
        "score": {"calibrated": {"calibrated_probability": 0.08}},
        "analysis_state": "idle",
        "graph_summary": {"intelligence": {"claim_coverage_pct": 0.0}},
        "supplier_passport": {
            "identity": {
                "identifier_status": {
                    "cage": {"state": "verified_absent"},
                    "uei": {"state": "verified_absent"},
                    "lei": {"state": "verified_absent"},
                }
            },
            "ownership": {
                "workflow_control": {
                    "label": "Public-source triage",
                    "review_basis": "Public-source ownership, relationship, and screening data only.",
                }
            },
            "tribunal": {
                "views": [
                    {
                        "summary": "Control-path coverage is still thin and should be improved before a clean decision.",
                    }
                ]
            },
        },
    }

    grouped_gaps = _collect_gap_lines(context)
    passport_gaps = _collect_passport_gaps(context)
    axiom = _build_axiom_assessment(context, {"label": "APPROVED", "summary": "The visible record is holding cleanly enough for Helios to support forward motion without manufacturing friction."})

    assert "Identity anchors still thin on: CAGE, UEI, LEI." in grouped_gaps
    assert all("verified absent" not in line for line in grouped_gaps)
    assert any(line.startswith("Tribunal counterview:") for line in passport_gaps)
    assert all("verified absent" not in line for line in passport_gaps)
    assert "The graph has not yet added corroborated claim coverage." in axiom["confidence"]
