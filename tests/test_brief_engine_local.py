import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from helios_core.brief_engine import (  # type: ignore  # noqa: E402
    _build_axiom_assessment,
    _build_material_signals,
    _confidence_tag,
    _collect_gap_lines,
    _collect_graph_holds,
    _collect_passport_gaps,
    _distill_context,
)
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
    assert all("independent analytical challenge" not in line.lower() for line in grouped_gaps)
    assert any(line.startswith("Countervailing review:") for line in passport_gaps)
    assert all("Public-source triage" not in line for line in passport_gaps)
    assert all("verified absent" not in line for line in passport_gaps)
    assert "assessed at" in axiom["support"].lower()
    assert "graph change:" not in axiom["graph_change"].lower()
    assert "No multi-source corroboration established yet." in axiom["confidence"]


def test_axiom_assessment_calls_out_when_graph_tightens_the_read():
    context = {
        "vendor": {"name": "Example Entity"},
        "score": {"calibrated": {"calibrated_probability": 0.16}},
        "analysis_state": "idle",
        "graph_summary": {
            "relationship_count": 3,
            "entity_count": 4,
            "relationships": [{}, {}, {}],
            "entities": [{}, {}, {}, {}],
            "intelligence": {"claim_coverage_pct": 0.42},
        },
        "supplier_passport": {"identity": {"identifier_status": {}}},
    }

    axiom = _build_axiom_assessment(
        context,
        {
            "label": "REVIEW",
            "summary": "The visible record contains enough uncertainty, pressure, or unresolved control context that Helios should force analyst review.",
        },
    )

    assert "Example Entity assessed at REVIEW" in axiom["support"]
    assert "Network evidence base:" in axiom["graph_change"]
    assert "42% claim coverage" in axiom["graph_change"]


def test_material_signals_promote_decision_useful_language_and_skip_internal_workflow_noise():
    findings = [
        {
            "title": "Concentration risk: 1 subcontractor(s) exceed 30% of subaward spend",
            "detail": "TECHNICAL ASSURANCE, INC. controls 57.1% of reported subaward dollars.",
            "severity": "medium",
            "source": "sam_subaward_reporting",
        },
        {
            "title": "Beneficial ownership disclosures: 5 filings",
            "detail": "Found 5 Schedule 13D/13G filings indicating investors with >5% beneficial ownership stakes.",
            "severity": "low",
            "source": "sec_edgar",
        },
        {
            "title": "Workflow control",
            "detail": "Public-source ownership, relationship, and screening data only.",
            "severity": "medium",
            "source": "workflow_control",
        },
    ]

    signals = _build_material_signals(findings, [], [])

    titles = [item["title"] for item in signals]
    assert "Subcontract concentration creates single-point-of-failure risk" in titles
    assert "Beneficial ownership structure unresolved" in titles
    assert all(title != "Workflow control" for title in titles)


def test_collect_graph_holds_filters_raw_axiom_ids():
    holds = _collect_graph_holds(
        {
            "relationships": [
                {
                    "source_name": "axiom:4cb118be566032727b5d",
                    "target_name": "axiom:d3a4201479db5783d1f6",
                    "rel_type": "incumbent_on",
                    "corroboration_count": 1,
                },
                {
                    "source_name": "Parsons Corporation",
                    "target_name": "Technical Assurance, Inc.",
                    "rel_type": "subcontractor_of",
                    "corroboration_count": 2,
                },
            ]
        }
    )

    assert len(holds) == 1
    assert "Parsons Corporation subcontractor of Technical Assurance, Inc." in holds[0]


def test_confidence_tag_treats_icij_as_unconfirmed():
    assert _confidence_tag("icij_offshore") == "UNCONFIRMED"
    assert _confidence_tag("sec_edgar") == "CONFIRMED"


def test_distilled_posture_stays_conditional_when_decision_moving_signals_are_unconfirmed():
    context = {
        "vendor": {
            "id": "parsons-like",
            "name": "PARSONS CORPORATION",
            "country": "US",
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
            "vendor_input": {},
        },
        "score": {
            "calibrated": {
                "calibrated_probability": 0.12,
                "calibrated_tier": "TIER_4_APPROVED",
                "program_recommendation": "approved",
                "interval": {"lower": 0.08, "upper": 0.17},
            }
        },
        "graph_summary": {
            "relationship_count": 2,
            "entity_count": 3,
            "relationships": [],
            "entities": [],
            "intelligence": {"claim_coverage_pct": 1.0, "missing_required_edge_families": []},
        },
        "enrichment": {
            "findings": [
                {
                    "title": "ICIJ: Parsons Music Corporation (Panama Papers)",
                    "detail": "Entity: Parsons Music Corporation. Name-proximity hit only.",
                    "severity": "medium",
                    "source": "icij_offshore",
                },
                {
                    "title": "Beneficial ownership disclosures: 5 filings",
                    "detail": "Found 5 Schedule 13D/13G filings indicating investors with >5% beneficial ownership stakes.",
                    "severity": "low",
                    "source": "sec_edgar",
                },
            ]
        },
        "supplier_passport": {
            "identity": {
                "identifiers": {"lei": "549300ZXH0VRBSEPX752", "cik": "275880"},
                "identifier_status": {
                    "cage": {"state": "verified_absent"},
                    "uei": {"state": "verified_absent"},
                },
            },
            "tribunal": {"recommended_label": "Approve", "recommended_view": "approve", "consensus_level": "strong"},
            "graph": {"control_paths": [], "intelligence": {"claim_coverage_pct": 1.0, "missing_required_edge_families": []}},
        },
        "analysis_state": "idle",
        "storyline": {"cards": []},
        "decisions": [],
    }

    payload = _distill_context(context)

    icij_row = next(item for item in payload["findings"] if item["source"] == "icij_offshore")
    ownership_row = next(item for item in payload["findings"] if item["title"] == "Beneficial ownership disclosures: 5 filings")

    assert icij_row["confidence"] == "UNCONFIRMED"
    assert "Cross-reference ICIJ entity against CAGE" in icij_row["next_check"]
    assert ownership_row["confidence"] == "UNCONFIRMED"
    assert payload["posture_assessment"]["narrative"].startswith("Posture is CONDITIONAL.")
    assert "SUPPORTED" not in payload["posture_assessment"]["narrative"]
