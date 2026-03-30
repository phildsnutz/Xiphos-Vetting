import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import ownership_control_intelligence as oci
from ownership_control_intelligence import (
    _sanitize_ai_adjudication_output,
    build_oci_summary,
    classify_ownership_relationships,
    relationship_supports_named_owner_resolution,
)


def test_descriptor_owner_is_rejected_as_named_entity():
    relationships = [
        {
            "type": "owned_by",
            "source_entity": "Yorktown Systems Group",
            "target_entity": "Service-Disabled Veteran",
            "authority_level": "first_party_self_disclosed",
            "access_model": "public_html",
            "confidence": 0.82,
            "data_source": "public_html_ownership",
        }
    ]

    classified = classify_ownership_relationships(relationships)

    assert classified["named_owners"] == []
    assert classified["rejected_descriptors"][0]["target_name"] == "Service-Disabled Veteran"


def test_third_party_public_owned_by_does_not_count_as_named_owner():
    relationship = {
        "type": "owned_by",
        "source_entity": "Yorktown Systems Group",
        "target_entity": "Yorktown Funds",
        "authority_level": "third_party_public",
        "access_model": "search_public_html",
        "confidence": 0.78,
        "data_source": "public_search_ownership",
    }

    assert relationship_supports_named_owner_resolution(relationship) is False

    summary = build_oci_summary({}, [], [relationship])

    assert summary["named_beneficial_owner_known"] is False
    assert summary["named_owner_candidates"] == []
    assert summary["weak_owner_candidates"][0]["target_name"] == "Yorktown Funds"


def test_descriptor_only_evidence_sets_owner_class_without_named_owner():
    summary = build_oci_summary(
        {
            "beneficial_owner_known": False,
            "named_beneficial_owner_known": False,
            "owner_class_known": False,
            "ownership_pct_resolved": 0.0,
            "control_resolution_pct": 0.0,
        },
        [
            {
                "source": "public_html_ownership",
                "title": "Public site beneficial ownership descriptor: Service-Disabled Veteran",
                "detail": "Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran.",
                "confidence": 0.81,
                "structured_fields": {
                    "ownership_descriptor": "Service-Disabled Veteran",
                    "ownership_descriptor_scope": "self_disclosed_owner_descriptor",
                },
            }
        ],
        [],
    )

    assert summary["named_beneficial_owner_known"] is False
    assert summary["owner_class_known"] is True
    assert summary["owner_class"] == "Service-Disabled Veteran"
    assert summary["descriptor_only"] is True
    assert summary["ownership_gap"] == "descriptor_only_owner_class"
    assert summary["ownership_resolution_pct"] == 0.55
    assert summary["control_resolution_pct"] == 0.35


def test_subcontractor_business_types_do_not_override_subject_owner_class():
    summary = build_oci_summary(
        {
            "beneficial_owner_known": False,
            "named_beneficial_owner_known": False,
            "owner_class_known": False,
            "ownership_pct_resolved": 0.0,
            "control_resolution_pct": 0.0,
        },
        [
            {
                "source": "sam_subaward_reporting",
                "category": "subcontract_reporting",
                "title": "SAM subcontract reports: 305 subcontractor(s), $2,105,588,438 total",
                "detail": (
                    "Official SAM.gov subcontract reports show subcontractors including "
                    "LODSTAR CONSULTING, INC. [{'code': '23', 'name': 'Minority-Owned Business'}]."
                ),
                "confidence": 0.92,
                "structured_fields": {
                    "top_subcontractors": [
                        {"name": "LODSTAR CONSULTING, INC.", "business_type": "Minority-Owned Business"}
                    ]
                },
            },
            {
                "source": "sam_gov",
                "category": "registration",
                "title": "SAM authority record: YORKTOWN SYSTEMS GROUP INC",
                "detail": (
                    "UEI: L5LMQSN59YE5 | CAGE: 4VJW9 | Business types: For Profit Organization, "
                    "Veteran-Owned Business, Service-Disabled Veteran-Owned Business"
                ),
                "confidence": 0.9,
                "structured_fields": {},
            },
        ],
        [],
    )

    assert summary["owner_class_known"] is True
    assert summary["owner_class"] == "Service-Disabled Veteran"
    assert all(item["source"] != "sam_subaward_reporting" for item in summary["owner_class_evidence"])


def test_official_beneficial_owner_relationship_counts_as_named_owner():
    relationship = {
        "type": "beneficially_owned_by",
        "source_entity": "Example Vendor",
        "target_entity": "Acorn Holdings",
        "authority_level": "official_registry",
        "access_model": "public_api",
        "confidence": 0.88,
        "data_source": "uk_companies_house",
    }

    summary = build_oci_summary({}, [], [relationship])

    assert summary["named_beneficial_owner_known"] is True
    assert summary["controlling_parent_known"] is True
    assert summary["named_beneficial_owner"] == "Acorn Holdings"
    assert summary["controlling_parent"] == "Acorn Holdings"
    assert summary["ownership_resolution_pct"] >= 0.65
    assert summary["control_resolution_pct"] >= 0.65


def test_profile_named_owner_boolean_without_concrete_name_does_not_resolve_named_owner():
    summary = build_oci_summary(
        {
            "beneficial_owner_known": True,
            "named_beneficial_owner_known": True,
            "owner_class_known": False,
            "ownership_pct_resolved": 0.9,
            "control_resolution_pct": 0.65,
        },
        [],
        [],
    )

    assert summary["named_beneficial_owner_known"] is False
    assert summary["named_beneficial_owner"] is None
    assert summary["ownership_gap"] == "named_owner_unknown"
    assert summary["ownership_resolution_pct"] == 0.0
    assert summary["control_resolution_pct"] == 0.0


def test_ai_adjudication_sanitizer_rejects_invented_control_candidate():
    classified = {
        "named_owners": [],
        "controlling_parents": [],
        "controllers": [
            {"target_name": "Offset Strategic Services"},
        ],
        "rejected_descriptors": [],
        "weak_owner_candidates": [
            {"target_name": "Yorktown Funds"},
        ],
    }

    adjudication = _sanitize_ai_adjudication_output(
        {
            "owner_class": "Service-Disabled Veteran",
            "should_set_owner_class": True,
            "descriptor_only": True,
            "control_signal_present": True,
            "control_candidate": "Invented Parent Holdings",
            "dismissed_named_owner_candidates": ["Yorktown Funds", "Fake Owner"],
            "follow_up_queries": ["Yorktown Systems Group ultimate owner", "Yorktown OSG JV control"],
            "confidence": "high",
            "reason": "Descriptor evidence is real but no named owner is safely resolved.",
        },
        classified,
    )

    assert adjudication is not None
    assert adjudication["owner_class"] == "Service-Disabled Veteran"
    assert adjudication["should_set_owner_class"] is True
    assert adjudication["control_candidate"] is None
    assert adjudication["dismissed_named_owner_candidates"] == ["Yorktown Funds"]


def test_build_oci_summary_applies_ai_descriptor_adjudication_without_inventing_owner(monkeypatch):
    monkeypatch.setattr(
        oci,
        "_run_ai_adjudication",
        lambda owner_class_evidence, classified: {
            "owner_class": "Service-Disabled Veteran",
            "should_set_owner_class": True,
            "descriptor_only": True,
            "control_signal_present": True,
            "control_candidate": "Offset Strategic Services",
            "dismissed_named_owner_candidates": ["Yorktown Funds"],
            "follow_up_queries": ["Yorktown Systems Group parent company"],
            "confidence": "medium",
            "reason": "Descriptor evidence is credible, but named-owner evidence is still insufficient.",
            "provider": "openai",
            "model": "gpt-4o",
        },
    )

    summary = build_oci_summary(
        {
            "beneficial_owner_known": False,
            "named_beneficial_owner_known": False,
            "owner_class_known": False,
            "ownership_pct_resolved": 0.0,
            "control_resolution_pct": 0.0,
        },
        [],
        [
            {
                "type": "owned_by",
                "source_entity": "Yorktown Systems Group",
                "target_entity": "Yorktown Funds",
                "authority_level": "third_party_public",
                "access_model": "search_public_html",
                "confidence": 0.66,
                "data_source": "public_search_ownership",
            },
            {
                "type": "led_by",
                "source_entity": "Yorktown Systems Group",
                "target_entity": "Offset Strategic Services",
                "authority_level": "first_party_self_disclosed",
                "access_model": "public_html",
                "confidence": 0.72,
                "data_source": "public_html_ownership",
            },
        ],
    )

    assert summary["named_beneficial_owner_known"] is False
    assert summary["owner_class_known"] is True
    assert summary["owner_class"] == "Service-Disabled Veteran"
    assert summary["descriptor_only"] is True
    assert summary["adjudicator_mode"] == "rules_plus_ai"
    assert summary["ai_adjudication"]["control_candidate"] == "Offset Strategic Services"
