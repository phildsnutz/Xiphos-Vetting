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
    _render_html_brief,
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


def test_distilled_context_builds_intelligence_thesis_and_counterview():
    context = {
        "vendor": {
            "id": "acme-review",
            "name": "ACME DEFENSE SYSTEMS",
            "country": "US",
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
            "vendor_input": {},
        },
        "score": {
            "calibrated": {
                "calibrated_probability": 0.34,
                "calibrated_tier": "TIER_3_CONDITIONAL",
                "program_recommendation": "review",
                "interval": {"lower": 0.24, "upper": 0.42},
            }
        },
        "graph_summary": {
            "relationship_count": 1,
            "entity_count": 2,
            "relationships": [],
            "entities": [],
            "intelligence": {
                "claim_coverage_pct": 0.3,
                "thin_graph": True,
                "thin_control_paths": True,
                "missing_required_edge_families": ["ownership_control"],
            },
        },
        "enrichment": {
            "findings": [
                {
                    "title": "ICIJ: ACME Holdings (Panama Papers)",
                    "detail": "Name-proximity hit only. No confirmed identifier match.",
                    "severity": "medium",
                    "source": "icij_offshore",
                }
            ]
        },
        "supplier_passport": {
            "identity": {
                "identifiers": {"lei": "123"},
                "identifier_status": {"uei": {"state": "verified_absent"}},
                "official_corroboration": {"coverage_level": "public_only"},
            },
            "tribunal": {
                "recommended_label": "Watch / Conditional",
                "recommended_view": "watch",
                "consensus_level": "moderate",
                "views": [
                    {
                        "stance": "watch",
                        "label": "Watch / Conditional",
                        "summary": "Control-path coverage is still thin and should be improved before a clean decision.",
                        "reasons": [
                            "Control-path coverage is still thin and should be improved before a clean decision.",
                            "Official-source corroboration is too thin for a clean approval.",
                        ],
                    },
                    {
                        "stance": "approve",
                        "label": "Approve / Proceed",
                        "summary": "No hard-stop is active.",
                        "reasons": [
                            "No hard-stop is active.",
                            "Identifier anchors are strong enough to trust the entity match.",
                        ],
                    },
                ],
            },
            "graph": {"control_paths": [], "intelligence": {"claim_coverage_pct": 0.3}},
        },
        "analysis_state": "idle",
        "storyline": {"cards": []},
        "decisions": [],
    }

    payload = _distill_context(context)

    thesis = payload["thesis"]
    assert "REVIEW" in thesis["principal_judgment"]["headline"]
    assert thesis["counterview"]["label"] == "Why proceed"
    assert thesis["dark_space"]
    assert "Axiom" not in thesis["principal_judgment"]["headline"]


def test_rendered_html_uses_decision_thesis_and_not_axiom_heading():
    context = {
        "vendor": {
            "id": "render-case",
            "name": "RENDER TEST SYSTEMS",
            "country": "US",
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
            "vendor_input": {},
        },
        "score": {
            "calibrated": {
                "calibrated_probability": 0.22,
                "calibrated_tier": "TIER_3_CONDITIONAL",
                "program_recommendation": "review",
                "interval": {"lower": 0.18, "upper": 0.29},
            }
        },
        "graph_summary": {"relationship_count": 0, "entity_count": 1, "relationships": [], "entities": [], "intelligence": {}},
        "enrichment": {"findings": []},
        "supplier_passport": {
            "identity": {"identifiers": {}, "identifier_status": {}},
            "tribunal": {"recommended_label": "Watch / Conditional", "recommended_view": "watch", "views": []},
            "graph": {"control_paths": [], "intelligence": {}},
        },
        "analysis_state": "idle",
        "storyline": {"cards": []},
        "decisions": [],
    }

    payload = _distill_context(context)
    html = _render_html_brief(payload)

    assert "Decision Thesis" in html
    assert "Competing Case" in html
    assert "Axiom Assessment" not in html


def test_rendered_html_surfaces_procurement_footprint_when_available():
    context = {
        "vendor": {
            "id": "parsons-review",
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
                "interval": {"lower": 0.08, "upper": 0.16},
            }
        },
        "graph_summary": {
            "relationship_count": 4,
            "entity_count": 5,
            "relationships": [],
            "entities": [],
            "intelligence": {"claim_coverage_pct": 0.5, "missing_required_edge_families": []},
        },
        "enrichment": {"findings": []},
        "supplier_passport": {
            "identity": {"identifiers": {"lei": "549300ZXH0VRBSEPX752"}, "identifier_status": {}},
            "tribunal": {"recommended_label": "Approve", "recommended_view": "approve", "consensus_level": "strong"},
            "graph": {"control_paths": [], "intelligence": {"claim_coverage_pct": 0.5, "missing_required_edge_families": []}},
        },
        "vendor_procurement": {
            "findings": [
                {
                    "title": "Prime vehicle access: OASIS",
                    "detail": "OBSERVED: PARSONS CORPORATION appears as a direct prime on OASIS through visible GSA award flow.",
                    "severity": "info",
                    "source": "usaspending_vendor_live",
                }
            ],
            "prime_vehicles": [
                {
                    "vehicle_name": "OASIS",
                    "award_count": 2,
                    "total_amount": 89160609.89,
                    "agencies": ["GSA FAS AAS FEDSIM"],
                }
            ],
            "sub_vehicles": [
                {
                    "vehicle_name": "OASIS",
                    "total_amount": 61589735.08,
                    "counterparties": ["SMARTRONIX, LLC", "CACI TECHNOLOGIES, INC."],
                }
            ],
            "upstream_primes": [
                {
                    "name": "SMARTRONIX, LLC",
                    "total_amount": 45753840.13,
                    "count": 1,
                    "vehicles": ["OASIS"],
                }
            ],
            "downstream_subcontractors": [
                {
                    "name": "HII MISSION TECHNOLOGIES CORP",
                    "total_amount": 28503983.98,
                    "count": 1,
                    "vehicles": ["OASIS"],
                }
            ],
            "top_customers": [
                {
                    "agency": "General Services Administration",
                    "prime_awards": 2,
                    "subaward_rows": 2,
                    "prime_amount": 89160609.89,
                    "sub_amount": 61589735.08,
                }
            ],
            "award_momentum": {
                "prime_awards": 2,
                "subaward_rows": 2,
                "latest_activity_date": "2024-10-22",
            },
        },
        "analysis_state": "idle",
        "storyline": {"cards": []},
        "decisions": [],
    }

    payload = _distill_context(context)
    html = _render_html_brief(payload)

    assert payload["procurement_read"]["metrics"]["prime_vehicle_count"] == 1
    assert payload["procurement_read"]["metrics"]["sub_vehicle_count"] == 1
    assert any("mixed" in item.lower() for item in payload["procurement_read"]["implication_lines"])
    assert any("dual-posture" in item.lower() for item in payload["procurement_read"]["market_position_lines"])
    assert any("visible prime access includes oasis" in item.lower() for item in payload["procurement_read"]["implication_lines"])
    assert "Procurement Footprint" in html
    assert "Market Position Read" in html
    assert "Prime Vehicles" in html
    assert "Recurring Upstream Primes" in html
    assert "Recurring Downstream Subs" in html
    assert "OASIS" in html


def test_rendered_html_surfaces_ownership_control_read_when_available():
    context = {
        "vendor": {
            "id": "ownership-case",
            "name": "HORIZON MISSION SYSTEMS LLC",
            "country": "US",
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
            "vendor_input": {},
        },
        "score": {
            "calibrated": {
                "calibrated_probability": 0.11,
                "calibrated_tier": "TIER_4_APPROVED",
                "program_recommendation": "approved",
                "interval": {"lower": 0.08, "upper": 0.16},
            }
        },
        "graph_summary": {
            "relationship_count": 1,
            "entity_count": 2,
            "relationships": [],
            "entities": [],
            "intelligence": {"claim_coverage_pct": 0.75, "missing_required_edge_families": []},
        },
        "enrichment": {"findings": []},
        "supplier_passport": {
            "identity": {"identifiers": {"lei": "549300ABC123XYZ78901"}, "identifier_status": {}},
            "tribunal": {"recommended_label": "Approve", "recommended_view": "approve", "consensus_level": "strong"},
            "graph": {"control_paths": [], "intelligence": {"claim_coverage_pct": 0.75, "missing_required_edge_families": []}},
        },
        "vendor_procurement": {},
        "vendor_ownership": {
            "metrics": {
                "official_connectors_with_data": 1,
                "ownership_relationship_count": 1,
                "named_beneficial_owner_known": False,
                "controlling_parent_known": True,
            },
            "control_lines": ["Controlling parent resolves to Horizon Holdings; named beneficial owner is still not publicly resolved."],
            "registry_lines": ["LEI corroborated: 549300ABC123XYZ78901."],
            "gap_lines": ["Named beneficial owner is still not public even though the controlling parent path is resolved."],
            "oci_summary": {"controlling_parent_known": True, "controlling_parent": "Horizon Holdings"},
        },
        "analysis_state": "idle",
        "storyline": {"cards": []},
        "decisions": [],
    }

    payload = _distill_context(context)
    html = _render_html_brief(payload)

    assert payload["ownership_read"]["metrics"]["controlling_parent_known"] is True
    assert "Ownership &amp; Control Read" in html
    assert "Verified Control Read" in html
    assert "Controlling parent resolves to Horizon Holdings" in html


def test_summary_line_prefers_procurement_posture_over_weak_offshore_match():
    context = {
        "vendor": {
            "id": "lockheed-like",
            "name": "LOCKHEED MARTIN CORPORATION",
            "country": "US",
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
            "vendor_input": {},
        },
        "score": {
            "calibrated": {
                "calibrated_probability": 0.13,
                "calibrated_tier": "TIER_4_APPROVED",
                "program_recommendation": "approved",
                "interval": {"lower": 0.09, "upper": 0.18},
            }
        },
        "graph_summary": {
            "relationship_count": 2,
            "entity_count": 3,
            "relationships": [],
            "entities": [],
            "intelligence": {"claim_coverage_pct": 0.6, "missing_required_edge_families": []},
        },
        "enrichment": {
            "findings": [
                {
                    "title": "ICIJ: Offshore leak proximity requires disambiguation",
                    "detail": "Name-proximity hit only. No corporate-family corroboration yet.",
                    "severity": "medium",
                    "source": "icij_offshore",
                }
            ]
        },
        "supplier_passport": {
            "identity": {"identifiers": {"lei": "549300XYZ"}, "identifier_status": {}},
            "tribunal": {"recommended_label": "Approve", "recommended_view": "approve", "consensus_level": "strong"},
            "graph": {"control_paths": [], "intelligence": {"claim_coverage_pct": 0.6, "missing_required_edge_families": []}},
        },
        "vendor_procurement": {
            "upstream_primes": [
                {"name": "BELL TEXTRON INC.", "total_amount": 12000000.0, "count": 2, "vehicles": ["OASIS"]},
                {"name": "RAYTHEON COMPANY", "total_amount": 9000000.0, "count": 1, "vehicles": ["OASIS"]},
            ],
            "downstream_subcontractors": [
                {"name": "NORTHROP GRUMMAN SYSTEMS CORPORATION", "total_amount": 8000000.0, "count": 1, "vehicles": ["OASIS"]},
            ],
            "top_customers": [
                {"agency": "NAVAL AIR SYSTEMS COMMAND", "prime_awards": 0, "subaward_rows": 3, "prime_amount": 0.0, "sub_amount": 21000000.0},
            ],
            "award_momentum": {"latest_activity_date": "2025-02-14"},
        },
        "analysis_state": "idle",
        "storyline": {"cards": []},
        "decisions": [],
    }

    payload = _distill_context(context)

    assert "offshore leak proximity" not in payload["summary_line"].lower()
    assert "visible federal footprint" in payload["summary_line"].lower()
