import os
import sys
import types


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import graph_ingest


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
