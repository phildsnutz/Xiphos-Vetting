import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from storyline import build_case_storyline  # type: ignore


def _base_vendor():
    return {
        "id": "c-storyline",
        "name": "Test Vendor",
        "country": "US",
        "program": "dod_unclassified",
        "created_at": "2026-03-22T12:00:00Z",
    }


def test_storyline_blocked_case_prioritizes_trigger_impact_action():
    vendor = _base_vendor()
    score = {
        "calibrated": {
            "calibrated_tier": "TIER_1_DISQUALIFIED",
            "hard_stop_decisions": [
                {
                    "trigger": "Sanctions match found",
                    "explanation": "The vendor matched a denied-party source and cannot proceed until cleared.",
                    "confidence": 0.97,
                }
            ],
            "soft_flags": [],
            "contributions": [],
            "regulatory_status": "NON_COMPLIANT",
            "is_dod_eligible": False,
            "is_dod_qualified": False,
        }
    }

    storyline = build_case_storyline(vendor["id"], vendor, score)

    assert storyline is not None
    cards = storyline["cards"]
    assert [card["type"] for card in cards[:3]] == ["trigger", "impact", "action"]
    assert cards[0]["title"] == "Sanctions match found"
    assert cards[1]["title"] == "Federal procurement blocked"
    assert "Stop procurement" in cards[2]["title"]


def test_storyline_conditional_case_includes_flag_network_and_action():
    vendor = _base_vendor()
    score = {
        "calibrated": {
            "calibrated_tier": "TIER_3_CONDITIONAL",
            "hard_stop_decisions": [],
            "soft_flags": [
                {
                    "trigger": "Beneficial ownership unresolved",
                    "explanation": "Only part of the ownership chain could be verified.",
                    "confidence": 0.84,
                }
            ],
            "contributions": [{"factor": "Ownership Structure"}],
        }
    }
    network_risk = {"score": 7.2, "level": "medium", "high_risk_neighbors": 2, "neighbor_count": 5}

    storyline = build_case_storyline(vendor["id"], vendor, score, network_risk=network_risk)

    assert storyline is not None
    card_types = [card["type"] for card in storyline["cards"]]
    assert "trigger" in card_types
    assert "reach" in card_types
    assert "action" in card_types
    reach_card = next(card for card in storyline["cards"] if card["type"] == "reach")
    assert reach_card["cta_target"]["kind"] == "graph_focus"
    assert "+7.2 risk points" in reach_card["body"]


def test_storyline_clear_case_prefers_offset_then_action():
    vendor = _base_vendor()
    score = {
        "calibrated": {
            "calibrated_tier": "TIER_4_APPROVED",
            "hard_stop_decisions": [],
            "soft_flags": [],
            "contributions": [],
            "regulatory_status": "COMPLIANT",
            "is_dod_eligible": True,
            "is_dod_qualified": True,
            "interval": {"coverage": 0.93},
        }
    }
    report = {
        "report_hash": "r-clear-1",
        "summary": {"connectors_run": 12, "connectors_with_data": 5},
        "findings": [],
    }

    storyline = build_case_storyline(vendor["id"], vendor, score, report=report)

    assert storyline is not None
    cards = storyline["cards"]
    assert cards[0]["type"] == "offset"
    assert cards[1]["type"] == "action"
    assert cards[2]["type"] == "reach"
    assert cards[0]["severity"] == "positive"


def test_storyline_uses_active_event_when_no_flags_exist():
    vendor = _base_vendor()
    score = {
        "calibrated": {
            "calibrated_tier": "TIER_2_ELEVATED",
            "hard_stop_decisions": [],
            "soft_flags": [],
            "contributions": [{"factor": "Geography"}],
        }
    }
    events = [
        {
            "finding_id": "finding-1",
            "event_type": "lawsuit",
            "title": "Federal lawsuit filed",
            "assessment": "A federal complaint names the vendor in an active civil action.",
            "status": "active",
            "confidence": 0.81,
            "connector": "courtlistener",
        }
    ]

    storyline = build_case_storyline(vendor["id"], vendor, score, events=events)

    assert storyline is not None
    assert storyline["cards"][0]["type"] == "trigger"
    assert storyline["cards"][0]["title"] == "Federal lawsuit filed"
    assert storyline["cards"][0]["cta_target"]["tab"] == "events"


def test_storyline_dedupes_overlapping_trigger_and_reach_sources():
    vendor = _base_vendor()
    score = {
        "calibrated": {
            "calibrated_tier": "TIER_3_CONDITIONAL",
            "hard_stop_decisions": [],
            "soft_flags": [],
            "contributions": [{"factor": "Ownership Structure"}],
        }
    }
    report = {
        "report_hash": "r-storyline-2",
        "summary": {"connectors_run": 8, "connectors_with_data": 4},
        "findings": [
            {
                "finding_id": "finding-1",
                "title": "Beneficial owner chain remains unresolved",
                "detail": "The OSINT run could not verify the full control chain for the vendor.",
                "severity": "medium",
                "confidence": 0.83,
                "source": "opencorporates",
            }
        ],
    }
    intel_summary = {
        "summary": {
            "items": [
                {
                    "title": "Ownership gap remains the main review driver",
                    "assessment": "Multiple sources point to the same missing beneficial ownership evidence.",
                    "severity": "medium",
                    "confidence": 0.79,
                    "source_finding_ids": ["finding-1"],
                    "connectors": ["opencorporates", "gleif_lei"],
                }
            ]
        }
    }

    storyline = build_case_storyline(vendor["id"], vendor, score, report=report, intel_summary=intel_summary)

    assert storyline is not None
    referenced_cards = [
        card for card in storyline["cards"]
        if any(ref.get("id") == "finding-1" for ref in card.get("source_refs", []))
    ]
    assert len(referenced_cards) == 1


def test_storyline_uses_customer_foci_evidence_in_clear_case():
    vendor = _base_vendor()
    score = {
        "calibrated": {
            "calibrated_tier": "TIER_4_APPROVED",
            "hard_stop_decisions": [],
            "soft_flags": [],
            "contributions": [],
            "regulatory_status": "COMPLIANT",
            "is_dod_eligible": True,
            "is_dod_qualified": True,
            "interval": {"coverage": 0.91},
        }
    }
    foci_summary = {
        "artifact_type": "foci_mitigation_instrument",
        "artifact_label": "Mitigation instrument",
        "foreign_owner": "Allied Parent Holdings",
        "foreign_country": "GB",
        "foreign_ownership_pct_display": "25%",
        "mitigation_display": "SSA",
        "foreign_interest_indicated": True,
        "mitigation_present": True,
        "posture": "mitigated_foreign_interest",
        "narrative": "Customer ownership evidence shows 25% foreign ownership linked to Allied Parent Holdings, with SSA noted.",
    }

    storyline = build_case_storyline(vendor["id"], vendor, score, foci_summary=foci_summary)

    assert storyline is not None
    matching = [card for card in storyline["cards"] if "FOCI evidence" in card["title"]]
    assert matching
    assert matching[0]["type"] == "offset"
    assert "25% foreign ownership" in matching[0]["body"]


def test_storyline_uses_customer_cyber_evidence_for_cmmc_gap():
    vendor = _base_vendor()
    vendor["profile"] = "defense_acquisition"
    score = {
        "calibrated": {
            "calibrated_tier": "TIER_3_CONDITIONAL",
            "hard_stop_decisions": [],
            "soft_flags": [],
            "contributions": [],
            "regulatory_status": "REQUIRES_REVIEW",
            "is_dod_eligible": True,
            "is_dod_qualified": False,
            "interval": {"coverage": 0.91},
        }
    }
    cyber_summary = {
        "current_cmmc_level": 1,
        "assessment_date": "2026-03-02",
        "assessment_status": "Conditional",
        "poam_active": True,
        "open_poam_items": 2,
        "critical_cve_count": 1,
        "kev_flagged_cve_count": 1,
        "sprs_artifact_id": "artifact-sprs",
    }

    storyline = build_case_storyline(vendor["id"], vendor, score, cyber_summary=cyber_summary)

    assert storyline is not None
    matching = [card for card in storyline["cards"] if "CMMC readiness gap" in card["title"]]
    assert matching
    assert matching[0]["type"] == "reach"
    assert "Level 1" in matching[0]["body"]
    assert "Level 2" in matching[0]["body"]


def test_storyline_uses_export_evidence_for_license_review():
    vendor = _base_vendor()
    vendor["profile"] = "itar_trade_compliance"
    score = {
        "calibrated": {
            "calibrated_tier": "TIER_3_CONDITIONAL",
            "hard_stop_decisions": [],
            "soft_flags": [],
            "contributions": [],
            "regulatory_status": "REQUIRES_REVIEW",
            "is_dod_eligible": True,
            "is_dod_qualified": False,
            "interval": {"coverage": 0.91},
        }
    }
    export_summary = {
        "posture": "likely_license_required",
        "posture_label": "Likely license required",
        "confidence": 0.84,
        "request_type": "technical_data_release",
        "artifact_type": "export_classification_memo",
        "narrative": "Helios rules guidance indicates this technical data release requires formal export review for 3A001 to DE.",
    }

    storyline = build_case_storyline(vendor["id"], vendor, score, export_summary=export_summary)

    assert storyline is not None
    matching = [card for card in storyline["cards"] if "formal export review" in card["title"]]
    assert matching
    assert matching[0]["type"] == "reach"
    assert "3A001" in matching[0]["body"]
