from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_thin_vendor_refresh_wave.py"
SPEC = importlib.util.spec_from_file_location("run_thin_vendor_refresh_wave", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_build_wave_report_flags_rel_only_when_control_families_do_not_move():
    selected_rows = [{"vendor_id": "v-1", "vendor_name": "Vendor 1"}]
    before = {
        "rows": [
            {
                "vendor_id": "v-1",
                "vendor_name": "Vendor 1",
                "relationship_count": 0,
                "control_path_count": 0,
                "ownership_edge_count": 0,
                "financing_edge_count": 0,
                "intermediary_edge_count": 0,
            }
        ],
        "coverage_metrics": {
            "zero_control_vendor_count": 1,
            "zero_relationship_vendor_count": 1,
        },
        "family_edge_totals": {
            "ownership_edge_total": 0,
            "financing_edge_total": 0,
            "intermediary_edge_total": 0,
        },
    }
    after = {
        "rows": [
            {
                "vendor_id": "v-1",
                "vendor_name": "Vendor 1",
                "relationship_count": 4,
                "control_path_count": 0,
                "ownership_edge_count": 0,
                "financing_edge_count": 0,
                "intermediary_edge_count": 0,
            }
        ],
        "coverage_metrics": {
            "zero_control_vendor_count": 1,
            "zero_relationship_vendor_count": 0,
        },
        "family_edge_totals": {
            "ownership_edge_total": 0,
            "financing_edge_total": 0,
            "intermediary_edge_total": 0,
        },
    }

    report = module._build_wave_report(selected_rows, before, after, {"vendors_checked": 1}, dry_run=False)

    assert report["kpi_gate"]["status"] == "REL_ONLY"
    assert report["kpi_gate"]["relationship_gain_total"] == 4
    assert report["kpi_gate"]["new_financing_edges"] == 0


def test_build_wave_report_passes_when_financing_edges_increase():
    selected_rows = [{"vendor_id": "v-1", "vendor_name": "Vendor 1"}]
    before = {
        "rows": [
            {
                "vendor_id": "v-1",
                "vendor_name": "Vendor 1",
                "relationship_count": 1,
                "control_path_count": 0,
                "ownership_edge_count": 0,
                "financing_edge_count": 0,
                "intermediary_edge_count": 0,
            }
        ],
        "coverage_metrics": {
            "zero_control_vendor_count": 1,
            "zero_relationship_vendor_count": 0,
        },
        "family_edge_totals": {
            "ownership_edge_total": 0,
            "financing_edge_total": 0,
            "intermediary_edge_total": 0,
        },
    }
    after = {
        "rows": [
            {
                "vendor_id": "v-1",
                "vendor_name": "Vendor 1",
                "relationship_count": 3,
                "control_path_count": 1,
                "ownership_edge_count": 0,
                "financing_edge_count": 2,
                "intermediary_edge_count": 0,
            }
        ],
        "coverage_metrics": {
            "zero_control_vendor_count": 0,
            "zero_relationship_vendor_count": 0,
        },
        "family_edge_totals": {
            "ownership_edge_total": 0,
            "financing_edge_total": 2,
            "intermediary_edge_total": 0,
        },
    }

    report = module._build_wave_report(selected_rows, before, after, {"vendors_checked": 1}, dry_run=False)

    assert report["kpi_gate"]["status"] == "PASS"
    assert report["kpi_gate"]["new_financing_edges"] == 2
    assert report["kpi_gate"]["zero_control_drop"] == 1
