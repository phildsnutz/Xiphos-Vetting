from pathlib import Path
import importlib.util


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_live_dossier_qa_batch.py"
SPEC = importlib.util.spec_from_file_location("run_live_dossier_qa_batch", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_build_default_cohort_filters_synthetic_and_hits_tier_targets():
    vendors = [
        {"id": "a1", "name": "DEPLOY_VERIFY", "tier": "TIER_4_APPROVED"},
        {"id": "a2", "name": "AI Warm Verify 1", "tier": "TIER_4_APPROVED"},
        {"id": "d1", "name": "Blocked 1", "tier": "TIER_1_DISQUALIFIED"},
        {"id": "d2", "name": "Blocked 2", "tier": "TIER_1_DISQUALIFIED"},
        {"id": "d3", "name": "Blocked 3", "tier": "TIER_1_DISQUALIFIED"},
        {"id": "d4", "name": "Blocked 4", "tier": "TIER_1_DISQUALIFIED"},
        {"id": "c1", "name": "Conditional 1", "tier": "TIER_3_CONDITIONAL"},
        {"id": "c2", "name": "Conditional 2", "tier": "TIER_3_CONDITIONAL"},
        {"id": "q1", "name": "Qualified", "tier": "TIER_4_CRITICAL_QUALIFIED"},
        {"id": "p1", "name": "Approved 1", "tier": "TIER_4_APPROVED"},
        {"id": "p2", "name": "Approved 2", "tier": "TIER_4_APPROVED"},
        {"id": "p3", "name": "Approved 3", "tier": "TIER_4_APPROVED"},
        {"id": "p4", "name": "Approved 4", "tier": "TIER_4_APPROVED"},
        {"id": "cl1", "name": "Clear 1", "tier": "TIER_4_CLEAR"},
        {"id": "cl2", "name": "Clear 2", "tier": "TIER_4_CLEAR"},
        {"id": "cl3", "name": "Clear 3", "tier": "TIER_4_CLEAR"},
        {"id": "cl4", "name": "Clear 4", "tier": "TIER_4_CLEAR"},
    ]

    cohort = MODULE.build_default_cohort(vendors, limit=12)

    assert all(v["name"] != "DEPLOY_VERIFY" for v in cohort)
    assert all(not v["name"].startswith("AI Warm Verify") for v in cohort)
    assert [v["tier"] for v in cohort[:4]] == ["TIER_1_DISQUALIFIED"] * 4
    assert any(v["tier"] == "TIER_4_CRITICAL_QUALIFIED" for v in cohort)


def test_choose_packet_cases_prefers_clear_qualified_and_blocked():
    results = [
        {"case_id": "x", "vendor_name": "Clear Co", "tier": "TIER_4_CLEAR", "failures": []},
        {"case_id": "y", "vendor_name": "Qualified Co", "tier": "TIER_4_CRITICAL_QUALIFIED", "failures": []},
        {"case_id": "z", "vendor_name": "Blocked Co", "tier": "TIER_1_DISQUALIFIED", "failures": []},
        {"case_id": "bad", "vendor_name": "Broken", "tier": "TIER_4_CLEAR", "failures": ["oops"]},
    ]

    packet = MODULE.choose_packet_cases(results)

    assert [item["case_id"] for item in packet] == ["x", "y", "z"]
