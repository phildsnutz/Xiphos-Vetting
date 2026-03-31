from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_provider_graph_vendor_coverage_audit.py"
SPEC = importlib.util.spec_from_file_location("run_provider_graph_vendor_coverage_audit", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_build_summary_counts_zero_control_and_relationship_buckets():
    rows = [
        {"vendor_id": "v-1", "mapped_root_entities": 1, "relationship_count": 0, "control_path_count": 0},
        {"vendor_id": "v-2", "mapped_root_entities": 1, "relationship_count": 2, "control_path_count": 0},
        {"vendor_id": "v-3", "mapped_root_entities": 3, "relationship_count": 4, "control_path_count": 2},
    ]

    summary = module.build_summary(rows, depth=3, include_rows=True)

    assert summary["coverage_metrics"]["zero_control_vendor_count"] == 2
    assert summary["coverage_metrics"]["zero_relationship_vendor_count"] == 1
    assert summary["mapped_entity_buckets"]["1"] == 2
    assert summary["control_path_buckets"]["0"] == 2
    assert len(summary["rows"]) == 3


def test_render_markdown_mentions_provider_neutral_surface():
    summary = {
        "generated_at": "2026-03-31T00:00:00Z",
        "graph_depth": 3,
        "global_counts": {"vendor_count": 5},
        "coverage_metrics": {
            "single_entity_vendor_count": 4,
            "single_entity_vendor_pct": 0.8,
            "zero_relationship_vendor_count": 2,
            "zero_relationship_vendor_pct": 0.4,
            "zero_control_vendor_count": 3,
            "zero_control_vendor_pct": 0.6,
            "vendors_with_any_control_path": 2,
        },
    }
    markdown = module.render_markdown(summary)
    assert "product-visible graph surface" in markdown
    assert "Zero-control vendors" in markdown
