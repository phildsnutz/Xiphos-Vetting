import os
import sys
import types
import json


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import graph_ingest  # noqa: E402


def test_backfill_all_vendors_passes_vendor_input(monkeypatch):
    fake_db = types.SimpleNamespace(
        list_vendors=lambda: [
            {
                "id": "case-1",
                "name": "Vector Mission Software",
                "vendor_input": {"seed_metadata": {"network_providers": ["Northbridge Networks"]}},
            }
        ],
        get_latest_enrichment=lambda case_id: {"identifiers": {}, "findings": [], "relationships": []},
    )
    monkeypatch.setitem(sys.modules, "db", fake_db)

    class FakeKg:
        @staticmethod
        def init_kg_db():
            return None

        @staticmethod
        def backfill_legacy_relationship_claims():
            return {}

    monkeypatch.setattr(graph_ingest, "_safe_import_kg", lambda: FakeKg())

    captured = {}

    def fake_ingest(vendor_id, vendor_name, enrichment_report, vendor_input=None):
        captured["vendor_id"] = vendor_id
        captured["vendor_name"] = vendor_name
        captured["vendor_input"] = vendor_input
        return {"entities_created": 1, "relationships_created": 2, "errors": []}

    monkeypatch.setattr(graph_ingest, "ingest_enrichment_to_graph", fake_ingest)

    summary = graph_ingest.backfill_all_vendors()

    assert summary["vendors_processed"] == 1
    assert captured["vendor_id"] == "case-1"
    assert captured["vendor_input"] == {"seed_metadata": {"network_providers": ["Northbridge Networks"]}}


def test_ingest_graph_training_fixture_gold_set_replays_through_ingest_contract(monkeypatch, tmp_path):
    fixture_rows = [
        {
            "source_entity": "Harbor Beacon Holdings",
            "target_entity": "U.S. Army",
            "relationship_type": "CONTRACTS_WITH",
            "edge_family": "contracts_and_programs",
            "evidence_text": "The U.S. Army awards Harbor Beacon Holdings a program contract.",
        },
        {
            "source_entity": "Secure Boot Module",
            "target_entity": "Vector Mission Software",
            "relationship_type": "INTEGRATED_INTO",
            "edge_family": "component_dependency",
            "evidence_text": "Secure Boot Module is integrated into Vector Mission Software.",
        },
    ]
    fixture_path = tmp_path / "graph_training_fixture.json"
    fixture_path.write_text(json.dumps(fixture_rows), encoding="utf-8")

    captured: list[dict] = []

    def fake_ingest(vendor_id, vendor_name, enrichment_report, vendor_input=None):
        captured.append(
            {
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "report": enrichment_report,
                "vendor_input": vendor_input,
            }
        )
        return {"entities_created": 2, "relationships_created": len(enrichment_report.get("relationships", [])), "errors": []}

    monkeypatch.setattr(graph_ingest, "ingest_enrichment_to_graph", fake_ingest)
    monkeypatch.setattr(graph_ingest, "PILLAR_BRIEFING_PACK_PATH", tmp_path / "missing.json")

    summary = graph_ingest.ingest_graph_training_fixture_gold_set(fixture_path)

    assert summary["sources_seeded"] == 2
    assert summary["rows_seeded"] == 2
    assert len(captured) == 2

    harbor_call = next(row for row in captured if row["vendor_name"] == "Harbor Beacon Holdings")
    harbor_rel = harbor_call["report"]["relationships"][0]
    assert harbor_call["report"]["primary_entity_type"] == "company"
    assert harbor_rel["type"] == "contracts_with"
    assert harbor_rel["target_entity_type"] == "government_agency"

    component_call = next(row for row in captured if row["vendor_name"] == "Secure Boot Module")
    component_rel = component_call["report"]["relationships"][0]
    assert component_call["report"]["primary_entity_type"] == "component"
    assert component_call["vendor_input"]["primary_entity_type"] == "component"
    assert component_rel["type"] == "integrated_into"
    assert component_rel["source_entity_type"] == "component"
