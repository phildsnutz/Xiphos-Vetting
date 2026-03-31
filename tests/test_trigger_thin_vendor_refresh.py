from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "trigger_thin_vendor_refresh.py"
SPEC = importlib.util.spec_from_file_location("trigger_thin_vendor_refresh", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_select_thin_vendor_rows_stops_after_limit(monkeypatch):
    vendors = [
        {"id": "v-1", "name": "Vendor 1"},
        {"id": "v-2", "name": "Vendor 2"},
        {"id": "v-3", "name": "Vendor 3"},
    ]
    calls: list[str] = []
    monkeypatch.setattr(module.db, "list_vendors", lambda limit=10000: vendors)

    def fake_summary(vendor_id, depth=3, include_provenance=False):
        calls.append(vendor_id)
        if vendor_id in {"v-1", "v-2"}:
            return {"root_entity_ids": [f"root:{vendor_id}"], "relationship_count": 0, "intelligence": {"control_path_count": 0}}
        return {"root_entity_ids": [f"root:{vendor_id}"], "relationship_count": 50, "intelligence": {"control_path_count": 3}}

    monkeypatch.setattr(module, "get_vendor_graph_summary", fake_summary)
    args = module.argparse.Namespace(
        limit=2,
        depth=3,
        scan_limit=10000,
        max_root_entities=1,
        max_relationships=2,
        require_zero_control=True,
        exclude_name_token=[],
        allow_duplicate_names=False,
    )

    rows = module._select_thin_vendor_rows(args)

    assert [row["vendor_id"] for row in rows] == ["v-1", "v-2"]
    assert calls == ["v-1", "v-2"]


def test_select_thin_vendor_rows_skips_synthetic_names(monkeypatch):
    vendors = [
        {"id": "v-1", "name": "DEPLOY_VERIFY"},
        {"id": "v-2", "name": "Smoke Vendor 1774733565"},
        {"id": "v-3", "name": "Yorktown graph diag 20260330"},
        {"id": "v-4", "name": "Real Vendor"},
    ]
    calls: list[str] = []
    monkeypatch.setattr(module.db, "list_vendors", lambda limit=10000: vendors)

    def fake_summary(vendor_id, depth=3, include_provenance=False):
        calls.append(vendor_id)
        return {"root_entity_ids": [f"root:{vendor_id}"], "relationship_count": 0, "intelligence": {"control_path_count": 0}}

    monkeypatch.setattr(module, "get_vendor_graph_summary", fake_summary)
    args = module.argparse.Namespace(
        limit=1,
        depth=3,
        scan_limit=10000,
        max_root_entities=1,
        max_relationships=2,
        require_zero_control=True,
        exclude_name_token=["DEPLOY_VERIFY", "SMOKE", "GRAPH DIAG"],
        allow_duplicate_names=False,
    )

    rows = module._select_thin_vendor_rows(args)

    assert [row["vendor_id"] for row in rows] == ["v-4"]
    assert calls == ["v-4"]


def test_select_thin_vendor_rows_dedupes_vendor_names(monkeypatch):
    vendors = [
        {"id": "v-1", "name": "Yorktown Systems Group"},
        {"id": "v-2", "name": "Yorktown Systems Group"},
        {"id": "v-3", "name": "Greensea IQ"},
    ]
    calls: list[str] = []
    monkeypatch.setattr(module.db, "list_vendors", lambda limit=10000: vendors)

    def fake_summary(vendor_id, depth=3, include_provenance=False):
        calls.append(vendor_id)
        return {"root_entity_ids": [f"root:{vendor_id}"], "relationship_count": 0, "intelligence": {"control_path_count": 0}}

    monkeypatch.setattr(module, "get_vendor_graph_summary", fake_summary)
    args = module.argparse.Namespace(
        limit=10,
        depth=3,
        scan_limit=10000,
        max_root_entities=1,
        max_relationships=2,
        require_zero_control=True,
        exclude_name_token=[],
        allow_duplicate_names=False,
    )

    rows = module._select_thin_vendor_rows(args)

    assert [row["vendor_id"] for row in rows] == ["v-1", "v-3"]
    assert calls == ["v-1", "v-3"]
