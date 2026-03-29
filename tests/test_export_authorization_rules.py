import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from export_authorization_rules import build_export_authorization_guidance  # noqa: E402


def test_rules_layer_flags_prohibited_destinations():
    guidance = build_export_authorization_guidance(
        {
            "request_type": "item_transfer",
            "destination_country": "RU",
            "jurisdiction_guess": "itar",
            "classification_guess": "USML Category VIII",
            "item_or_data_summary": "Fire-control component",
        }
    )

    assert guidance is not None
    assert guidance["posture"] == "likely_prohibited"
    assert guidance["country_analysis"]["country_bucket"] == "E:1 / prohibited destination" or "prohibited" in guidance["country_analysis"]["country_bucket"].lower()
    assert guidance["source_class"] == "rules_layer"


def test_rules_layer_supports_low_friction_ear99_paths():
    guidance = build_export_authorization_guidance(
        {
            "request_type": "item_transfer",
            "destination_country": "DE",
            "jurisdiction_guess": "ear",
            "classification_guess": "EAR99",
            "item_or_data_summary": "Commercial test fixture",
            "end_use_summary": "Routine integration support for civil avionics maintenance",
        }
    )

    assert guidance is not None
    assert guidance["posture"] == "likely_nlr"
    assert guidance["classification_analysis"]["classification_family"] == "ear99"
    assert guidance["official_references"]


def test_rules_layer_escalates_part_744_style_red_flags():
    guidance = build_export_authorization_guidance(
        {
            "request_type": "technical_data_release",
            "destination_country": "AE",
            "jurisdiction_guess": "ear",
            "classification_guess": "3A001",
            "item_or_data_summary": "Radar processing firmware and interface documentation",
            "end_use_summary": "Missile guidance and launch vehicle integration study",
        }
    )

    assert guidance is not None
    assert guidance["posture"] == "escalate"
    assert guidance["end_use_flags"][0]["severity"] == "critical"
    assert any("744" in ref["note"] or "744" in ref["title"] for ref in guidance["official_references"])


def test_rules_layer_requires_more_confidence_without_classification():
    guidance = build_export_authorization_guidance(
        {
            "request_type": "foreign_person_access",
            "destination_country": "US",
            "jurisdiction_guess": "ear",
            "foreign_person_nationalities": ["IN"],
            "access_context": "Foreign national engineer needs source-code access for debugging.",
        }
    )

    assert guidance is not None
    assert guidance["posture"] == "insufficient_confidence"
    assert guidance["classification_analysis"]["known"] is False


def test_rules_layer_treats_hong_kong_as_high_scrutiny():
    guidance = build_export_authorization_guidance(
        {
            "request_type": "item_transfer",
            "destination_country": "HK",
            "jurisdiction_guess": "ear",
            "classification_guess": "EAR99",
            "item_or_data_summary": "Commercial network appliance",
            "end_use_summary": "Telecom monitoring deployment",
        }
    )

    assert guidance is not None
    assert guidance["country_analysis"]["country_bucket"] == "high-scrutiny destination"


def test_rules_layer_does_not_trigger_ew_flag_from_gateway_word():
    guidance = build_export_authorization_guidance(
        {
            "request_type": "item_transfer",
            "destination_country": "JP",
            "jurisdiction_guess": "ear",
            "classification_guess": "5A002",
            "item_or_data_summary": "Encrypted communications gateway for civil satellite ground station",
            "end_use_summary": "Civil satellite communications gateway for commercial uplink operations",
        }
    )

    assert guidance is not None
    assert guidance["posture"] == "likely_exception_or_exemption"
    assert guidance["end_use_flags"] == []
