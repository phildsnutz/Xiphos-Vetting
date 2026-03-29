import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_training_cohort_repair.py"
SPEC = importlib.util.spec_from_file_location("run_training_cohort_repair", SCRIPT_PATH)
repair = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(repair)


def test_select_repair_rows_returns_failed_sequences():
    cohort_rows = [
        {"sequence": "1", "name": "Vendor A", "bucket": "a", "action": "create", "country": "US"},
        {"sequence": "2", "name": "Vendor B", "bucket": "a", "action": "create", "country": "US"},
        {"sequence": "3", "name": "Vendor C", "bucket": "a", "action": "create", "country": "US"},
    ]
    result_index = {
        1: {"sequence": 1, "status": "ok"},
        2: {"sequence": 2, "status": "error"},
    }

    rows = repair.select_repair_rows(cohort_rows, result_index)

    assert [row["sequence"] for row in rows] == ["2"]


def test_select_repair_rows_can_include_missing_sequences():
    cohort_rows = [
        {"sequence": "1", "name": "Vendor A", "bucket": "a", "action": "create", "country": "US"},
        {"sequence": "2", "name": "Vendor B", "bucket": "a", "action": "create", "country": "US"},
    ]
    result_index = {
        1: {"sequence": 1, "status": "ok"},
    }

    rows = repair.select_repair_rows(cohort_rows, result_index, repair_missing=True)

    assert [row["sequence"] for row in rows] == ["2"]
