import os
import sys
from pathlib import Path


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from supply_chain_assurance_gauntlet import (  # type: ignore  # noqa: E402
    DEFAULT_FIXTURE,
    evaluate_cases,
    load_cases,
    render_markdown,
)
from supply_chain_assurance_ai_challenge import build_hybrid_assurance_review  # type: ignore  # noqa: E402


def test_supply_chain_assurance_gauntlet_fixture_passes_cleanly():
    cases = load_cases(DEFAULT_FIXTURE)
    report = evaluate_cases(cases)

    assert report["scenario_count"] == 8
    assert report["failed_count"] == 0
    assert report["pass_rate"] == 1.0
    assert report["deterministic_baseline_accuracy"] == 0.375
    assert report["hybrid_posture_accuracy"] == 1.0
    assert report["hybrid_outperformed_count"] == 5
    assert report["no_regression_count"] == 8
    assert report["overall_score"] >= 0.95


def test_supply_chain_assurance_markdown_contains_proof_readout():
    cases = load_cases(DEFAULT_FIXTURE)
    report = evaluate_cases(cases)
    markdown = render_markdown(report, Path(DEFAULT_FIXTURE).name)

    assert "# Helios Supply Chain Assurance Gauntlet" in markdown
    assert "Scenarios: `8`" in markdown
    assert "Deterministic baseline accuracy: `37.5%`" in markdown
    assert "Hybrid posture accuracy: `100.0%`" in markdown
    assert "Hybrid outperformed deterministic on: `5` scenarios" in markdown
    assert "The AI challenge layer is improving assurance quality" in markdown


def test_build_hybrid_assurance_review_returns_typed_payload_for_live_evidence():
    review = build_hybrid_assurance_review(
        {
            "sprs_artifact_id": "artifact:sprs",
            "oscal_artifact_id": "artifact:oscal",
            "nvd_artifact_id": "artifact:nvd",
            "current_cmmc_level": 2,
            "assessment_status": "passed",
            "poam_active": False,
            "open_poam_items": 0,
            "total_control_references": 143,
            "high_or_critical_cve_count": 1,
            "critical_cve_count": 0,
            "kev_flagged_cve_count": 0,
            "product_terms": ["satcom gateway", "firmware updater"],
            "artifact_sources": ["sprs_import", "oscal_upload", "nvd_overlay"],
            "threat_pressure": "high",
            "attack_technique_ids": ["T1190", "T1078", "T1090", "T1583"],
            "attack_actor_families": ["APT29"],
            "cisa_advisory_ids": ["AA24-057A", "AA22-047A"],
            "threat_sectors": ["defense industrial base"],
            "open_source_risk_level": "medium",
            "open_source_advisory_count": 3,
            "scorecard_low_repo_count": 1,
        },
        vendor={"id": "c-123", "name": "Assurance Vendor", "profile": "defense_acquisition", "program": "dod_unclassified"},
        supplier_passport={"network_risk": {"high_risk_neighbors": 1}},
    )

    assert review is not None
    assert review["version"] == "assurance-hybrid-review-v1"
    assert review["deterministic_posture"] in {"qualified", "review", "blocked", "ready"}
    assert review["ai_proposed_posture"] in {"qualified", "review", "blocked", "ready"}
    assert review["final_posture"] in {"qualified", "review", "blocked", "ready"}
    assert review["safe_boundary"]["ai_can_elevate"] is True
    assert review["threat_pressure"] == "high"
    assert review["attack_technique_ids"] == ["T1190", "T1078", "T1090", "T1583"]
    assert review["cisa_advisory_ids"] == ["AA24-057A", "AA22-047A"]
    assert "active_threat_pressure" in review["ambiguity_flags"]


def test_supply_chain_assurance_split_fixtures_pass_cleanly():
    fixture_names = [
        "supply_chain_assurance_artifact_quality_cases.json",
        "supply_chain_assurance_dependency_concentration_cases.json",
        "supply_chain_assurance_procurement_readiness_cases.json",
    ]

    for fixture_name in fixture_names:
        fixture_path = Path(DEFAULT_FIXTURE).with_name(fixture_name)
        report = evaluate_cases(load_cases(fixture_path))
        assert report["failed_count"] == 0, fixture_name
        assert report["scenario_count"] >= 2, fixture_name
