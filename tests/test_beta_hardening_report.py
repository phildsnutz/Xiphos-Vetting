from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("/Users/tyegonzalez/Desktop/Helios-Package Merged/scripts/run_beta_hardening_report.py")
spec = importlib.util.spec_from_file_location("beta_hardening_report", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_validate_graph_payload_flags_missing_endpoints():
    graph = {
        "root_entity_id": "root-1",
        "entities": [{"id": "root-1"}, {"id": "other-1"}],
        "relationships": [
            {
                "source_entity_id": "root-1",
                "target_entity_id": "missing-entity",
                "rel_type": "contracts_with",
                "corroboration_count": 2,
            }
        ],
    }

    ok, stats, failures, warnings = module.validate_graph_payload(graph)

    assert ok is False
    assert stats["corroborated_edges"] == 1
    assert stats["missing_endpoints"] == 1
    assert any("missing hydrated endpoints" in failure for failure in failures)
    assert warnings == []


def test_validate_section_checks_reports_missing_markers():
    ok, failures = module.validate_section_checks(
        "Risk Storyline only",
        {"risk_storyline": "Risk Storyline", "ai_brief": "AI Narrative Brief"},
        "html dossier",
    )

    assert ok is False
    assert failures == ["html dossier missing ai brief"]


def test_load_case_ids_from_cohort_reads_json(tmp_path):
    cohort = tmp_path / "cohort.json"
    cohort.write_text('[{"id":"case-1"},{"id":"case-2"}]', encoding="utf-8")

    assert module.load_case_ids_from_cohort(str(cohort)) == ["case-1", "case-2"]


def test_resolve_cached_analysis_falls_back_to_any_creator(monkeypatch):
    calls = []

    def fake_get_latest_analysis(case_id, user_id="", input_hash=""):
        calls.append((case_id, user_id, input_hash))
        if user_id == "dev":
            return None
        return {"created_by": "operator-1", "input_hash": input_hash}

    monkeypatch.setattr(module, "get_latest_analysis", fake_get_latest_analysis)

    cached, creator = module.resolve_cached_analysis("case-1", "hash-1")

    assert cached == {"created_by": "operator-1", "input_hash": "hash-1"}
    assert creator == "operator-1"
    assert calls == [("case-1", "dev", "hash-1"), ("case-1", "", "hash-1")]
