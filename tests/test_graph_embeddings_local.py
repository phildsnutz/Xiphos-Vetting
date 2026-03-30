import importlib
import os
import sys


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload_fresh(module_name: str):
    if module_name in sys.modules:
        del sys.modules[module_name]
    return importlib.import_module(module_name)


def test_allow_predicted_link_rejects_descriptor_owner_targets():
    module = _reload_fresh("graph_embeddings")

    assert module._allow_predicted_link("company", "OWNED_BY", "unknown", "Service-Disabled Veteran") is False
    assert module._allow_predicted_link("company", "OWNED_BY", "unknown", "family-owned") is False


def test_allow_predicted_link_rejects_marketing_and_wrong_target_classes():
    module = _reload_fresh("graph_embeddings")

    assert module._allow_predicted_link("company", "DEPENDS_ON_SERVICE", "unknown", "Microsoft Azure partners") is False
    assert module._allow_predicted_link("company", "LITIGANT_IN", "company", "Beacon Strategic Capital") is False
    assert module._allow_predicted_link("company", "SCREENED_FOR", "company", "RTX CORPORATION") is False


def test_allow_predicted_link_keeps_high_signal_contract_and_route_targets():
    module = _reload_fresh("graph_embeddings")

    assert module._allow_predicted_link("company", "CONTRACTS_WITH", "government_agency", "U.S. Army") is True
    assert module._allow_predicted_link("company", "SHIPS_VIA", "unknown", "Turkiye") is True


def test_allow_predicted_link_rejects_placeholder_and_wrong_official_targets():
    module = _reload_fresh("graph_embeddings")

    assert module._allow_predicted_link("company", "OWNED_BY", "holding_company", "Unresolved Holding Layer 2 for Vector Mission Software") is False
    assert module._allow_predicted_link("company", "SHIPS_VIA", "shipment_route", "Northern Channel Partners modeled transit via AE") is False
    assert module._allow_predicted_link("company", "FILED_WITH", "government_agency", "Spire Global, Inc.") is False


def test_prepare_prediction_rows_dedupes_and_diversifies_relations():
    module = _reload_fresh("graph_embeddings")

    class FakeTrainer:
        def predict_links(self, entity_id, top_k=10):
            return [
                {"target_entity_id": "gov-1", "predicted_relation": "contracts_with", "score": 0.11, "target_name": "U.S. Army"},
                {"target_entity_id": "gov-2", "predicted_relation": "contracts_with", "score": 0.12, "target_name": "Department of State"},
                {"target_entity_id": "gov-3", "predicted_relation": "contracts_with", "score": 0.13, "target_name": "Department of Veterans Affairs"},
                {"target_entity_id": "gov-4", "predicted_relation": "contracts_with", "score": 0.14, "target_name": "Department of Energy"},
                {"target_entity_id": "gov-5", "predicted_relation": "contracts_with", "score": 0.15, "target_name": "Department of Homeland Security"},
                {"target_entity_id": "own-1", "predicted_relation": "owned_by", "score": 0.16, "target_name": "Beacon Strategic Capital"},
                {"target_entity_id": "own-2", "predicted_relation": "owned_by", "score": 0.17, "target_name": "Unresolved Holding Layer 2 for Harbor Beacon Holdings"},
                {"target_entity_id": "case-1", "predicted_relation": "litigant_in", "score": 0.18, "target_name": "Case No. 24-cv-1182"},
                {"target_entity_id": "case-2", "predicted_relation": "filed_with", "score": 0.19, "target_name": "Spire Global, Inc."},
                {"target_entity_id": "other-1", "predicted_relation": "screened_for", "score": 0.10, "target_name": "RTX CORPORATION"},
            ]

    entity_rows = {
        "src-1": {"entity_id": "src-1", "canonical_name": "Harbor Beacon Holdings", "entity_type": "company"},
        "gov-1": {"entity_id": "gov-1", "canonical_name": "U.S. Army", "entity_type": "government_agency"},
        "gov-2": {"entity_id": "gov-2", "canonical_name": "Department of State", "entity_type": "government_agency"},
        "gov-3": {"entity_id": "gov-3", "canonical_name": "Department of Veterans Affairs", "entity_type": "government_agency"},
        "gov-4": {"entity_id": "gov-4", "canonical_name": "Department of Energy", "entity_type": "government_agency"},
        "gov-5": {"entity_id": "gov-5", "canonical_name": "Department of Homeland Security", "entity_type": "government_agency"},
        "own-1": {"entity_id": "own-1", "canonical_name": "Beacon Strategic Capital", "entity_type": "holding_company"},
        "own-2": {"entity_id": "own-2", "canonical_name": "Unresolved Holding Layer 2 for Harbor Beacon Holdings", "entity_type": "holding_company"},
        "case-1": {"entity_id": "case-1", "canonical_name": "Case No. 24-cv-1182", "entity_type": "court_case"},
        "case-2": {"entity_id": "case-2", "canonical_name": "Spire Global, Inc.", "entity_type": "government_agency"},
        "other-1": {"entity_id": "other-1", "canonical_name": "RTX CORPORATION", "entity_type": "company"},
    }

    module._fetch_entity_map = lambda cur, entity_ids: {entity_id: entity_rows[entity_id] for entity_id in entity_ids if entity_id in entity_rows}
    rows = module._prepare_prediction_rows(cur=None, trainer=FakeTrainer(), entity_id="src-1", top_k=4)

    assert [row["predicted_relation"] for row in rows].count("contracts_with") <= 4
    assert any(row["predicted_relation"] == "owned_by" and row["target_name"] == "Beacon Strategic Capital" for row in rows)
    assert all("Unresolved Holding Layer" not in row["target_name"] for row in rows)
    assert all(row["target_name"] != "Spire Global, Inc." for row in rows)
    assert all(row["predicted_relation"] != "screened_for" for row in rows)


def test_prepare_prediction_rows_applies_relation_specific_reranking():
    module = _reload_fresh("graph_embeddings")

    class FakeTrainer:
        def predict_links(self, entity_id, top_k=10):
            return [
                {"target_entity_id": "bank-weaker", "predicted_relation": "routes_payment_through", "score": 0.12, "target_name": "Harbor Settlement Bank"},
                {"target_entity_id": "corp-stronger", "predicted_relation": "routes_payment_through", "score": 0.09, "target_name": "North Harbor Capital"},
                {"target_entity_id": "case-weaker", "predicted_relation": "litigant_in", "score": 0.16, "target_name": "Case No. 24-cv-1182"},
                {"target_entity_id": "court-stronger", "predicted_relation": "litigant_in", "score": 0.13, "target_name": "Beacon Strategic Capital"},
                {"target_entity_id": "agency-weaker", "predicted_relation": "contracts_with", "score": 0.15, "target_name": "U.S. Army"},
                {"target_entity_id": "company-stronger", "predicted_relation": "contracts_with", "score": 0.12, "target_name": "Raytheon Company"},
            ]

    entity_rows = {
        "src-1": {"entity_id": "src-1", "canonical_name": "Harbor Beacon Holdings", "entity_type": "company"},
        "bank-weaker": {"entity_id": "bank-weaker", "canonical_name": "Harbor Settlement Bank", "entity_type": "bank"},
        "corp-stronger": {"entity_id": "corp-stronger", "canonical_name": "North Harbor Capital", "entity_type": "holding_company"},
        "case-weaker": {"entity_id": "case-weaker", "canonical_name": "Case No. 24-cv-1182", "entity_type": "court_case"},
        "court-stronger": {"entity_id": "court-stronger", "canonical_name": "Beacon Strategic Capital", "entity_type": "holding_company"},
        "agency-weaker": {"entity_id": "agency-weaker", "canonical_name": "U.S. Army", "entity_type": "government_agency"},
        "company-stronger": {"entity_id": "company-stronger", "canonical_name": "Raytheon Company", "entity_type": "company"},
    }

    module._fetch_entity_map = lambda cur, entity_ids: {entity_id: entity_rows[entity_id] for entity_id in entity_ids if entity_id in entity_rows}
    rows = module._prepare_prediction_rows(cur=None, trainer=FakeTrainer(), entity_id="src-1", top_k=6)

    names_in_order = [row["target_name"] for row in rows]
    assert "Raytheon Company" not in names_in_order
    assert "North Harbor Capital" not in names_in_order
    assert "Beacon Strategic Capital" not in names_in_order
    assert "Harbor Settlement Bank" in names_in_order
    assert "Case No. 24-cv-1182" in names_in_order


def test_evaluate_construction_fixture_rows_uses_pending_and_rejected_candidate_state():
    module = _reload_fresh("graph_embeddings")

    gold_rows = [
        {
            "source_entity": "Harbor Beacon Holdings",
            "target_entity": "Beacon Strategic Capital",
            "relationship_type": "OWNED_BY",
            "edge_family": "ownership_control",
        },
        {
            "source_entity": "Yorktown Systems Group",
            "target_entity": "U.S. Army",
            "relationship_type": "CONTRACTS_WITH",
            "edge_family": "contracts_and_programs",
        },
    ]
    negative_rows = [
        {
            "source_entity": "Yorktown Systems Group",
            "attempted_target": "Service-Disabled Veteran",
            "attempted_relationship_type": "OWNED_BY",
            "edge_family": "ownership_control",
            "rejection_reason": "descriptor_only_not_entity",
        }
    ]
    prediction_state = {
        ("harbor beacon holdings", "beacon strategic capital", "owned_by"): {
            "confirmed_candidate": False,
            "pending_candidate": True,
            "rejected_candidate": False,
        },
        ("yorktown systems group", "service-disabled veteran", "owned_by"): {
            "confirmed_candidate": False,
            "pending_candidate": False,
            "rejected_candidate": True,
        },
    }
    existing_edges = {
        ("yorktown systems group", "u.s. army", "contracts_with"),
    }

    metrics = module._evaluate_construction_fixture_rows(
        gold_rows,
        negative_rows,
        existing_edges=existing_edges,
        prediction_state=prediction_state,
    )

    assert metrics["edge_family_micro_f1"] == 1.0
    assert metrics["ownership_control_precision"] == 1.0
    assert metrics["ownership_control_recall"] == 1.0
    assert metrics["descriptor_only_false_owner_rate"] == 0.0
    assert metrics["gold_candidate_coverage"] == 1.0
    assert metrics["negative_rejection_coverage"] == 1.0
