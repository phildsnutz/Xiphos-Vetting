from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("/Users/tyegonzalez/Desktop/Helios-Package Merged/scripts/run_dossier_value_benchmark.py")
spec = importlib.util.spec_from_file_location("dossier_value_benchmark", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


SAMPLE_HTML = """
<html>
  <body>
    <div class="summary">APPROVED holds with direct access on GSA IT GWAC and recurring work under SMARTRONIX, LLC.</div>
    <h2>Decision Thesis</h2>
    <h2>Competing Case</h2>
    <h2>Dark Space</h2>
    <h2>Procurement Footprint</h2>
    <h2>Market Position Read</h2>
    <h2>Prime Vehicles</h2>
    <h2>Subcontract Vehicles</h2>
    <h2>Recurring Upstream Primes</h2>
    <h2>Recurring Downstream Subs</h2>
    <h2>Customer Concentration</h2>
    <h2>Supplier Passport</h2>
    <h2>Evidence Ledger</h2>
    <div>CONFIRMED</div>
    <div>UNCONFIRMED</div>
    <div>ASSESSED</div>
    <div>What changes the call</div>
    <div>Closure method</div>
    <div>OASIS</div>
    <div>SEAPORT-NXG</div>
  </body>
</html>
"""


def test_score_case_rewards_procurement_specificity():
    dimensions = {item.name: item.score for item in module.score_case(SAMPLE_HTML)}

    assert dimensions["opening_value"] >= 4
    assert dimensions["procurement_specificity"] == 5
    assert dimensions["decision_usefulness"] >= 4


def test_render_markdown_lists_case_dimensions():
    summary = {
        "generated_at": "2026-04-07T12:00:00Z",
        "overall_verdict": "PASS",
        "average_weighted_score_pct": 81.5,
        "cases": [
            {
                "vendor_id": "c-1",
                "vendor_name": "PARSONS CORPORATION",
                "verdict": "PASS",
                "weighted_score_pct": 81.5,
                "artifact_path": "/tmp/parsons.html",
                "required_fragments_missing": [],
                "forbidden_fragments_present": [],
                "dimensions": [
                    {"name": "opening_value", "score": 5, "notes": ["opening leads with a commercially specific posture"]},
                    {"name": "procurement_specificity", "score": 5, "notes": []},
                ],
            }
        ],
    }

    markdown = module.render_markdown(summary)

    assert "# Helios Dossier Value Benchmark" in markdown
    assert "## PARSONS CORPORATION" in markdown
    assert "| `opening_value` | `5` |" in markdown


def test_load_specs_reads_json_array(tmp_path):
    payload = [
        {
            "vendor_id": "c-123",
            "vendor_name": "Example Vendor",
            "required_fragments": ["Decision Thesis"],
        }
    ]
    spec_path = tmp_path / "benchmark.json"
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    specs = module.load_specs(str(spec_path))

    assert len(specs) == 1
    assert specs[0]["vendor_name"] == "Example Vendor"
