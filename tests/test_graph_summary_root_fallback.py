from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("/Users/tyegonzalez/Desktop/Helios-Package Merged/backend/graph_ingest.py")
spec = importlib.util.spec_from_file_location("graph_ingest_root_fallback", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class _FakeKg:
    def init_kg_db(self):
        return None

    def get_vendor_entities(self, vendor_id):
        return []


class _FakeDb:
    @staticmethod
    def get_vendor(vendor_id):
        return {
            "id": vendor_id,
            "name": "Fallback Vendor",
            "country": "US",
            "updated_at": "2026-03-29T10:00:00",
            "lei": "5493001KJTIIGC8Y1R12",
        }


def test_get_vendor_graph_summary_returns_synthetic_root_when_graph_empty(monkeypatch):
    monkeypatch.setattr(module, "_safe_import_kg", lambda: _FakeKg())
    monkeypatch.setattr(module, "_safe_import_db", lambda: _FakeDb())

    summary = module.get_vendor_graph_summary("vendor-1", depth=3)

    assert summary["root_entity_id"]
    assert summary["root_entity_ids"] == [summary["root_entity_id"]]
    assert summary["entity_count"] == 1
    assert summary["relationship_count"] == 0
    assert len(summary["entities"]) == 1
    entity = summary["entities"][0]
    assert entity["id"] == summary["root_entity_id"]
    assert entity["canonical_name"] == "Fallback Vendor"
    assert entity["sources"] == ["vendor_record_fallback"]
    assert entity["synthetic"] is True
