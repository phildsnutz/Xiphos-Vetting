import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_training_morning_audit.py"
SPEC = importlib.util.spec_from_file_location("run_training_morning_audit", SCRIPT_PATH)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(audit)


def test_summarize_results_tracks_missing_sequences_and_auth_errors(tmp_path: Path):
    results_file = tmp_path / "results.json"
    results_file.write_text(
        json.dumps(
            [
                {"sequence": "1", "name": "Vendor A", "status": "ok", "mode": "create"},
                {"sequence": "2", "name": "Vendor B", "status": "error", "error": "401 Client Error: UNAUTHORIZED"},
            ]
        ),
        encoding="utf-8",
    )
    cohort_file = tmp_path / "cohort.csv"
    cohort_file.write_text(
        "sequence,name,bucket,action,country\n1,Vendor A,a,create,US\n2,Vendor B,a,create,US\n3,Vendor C,a,create,US\n",
        encoding="utf-8",
    )

    summary = audit.summarize_results([results_file], cohort_file=cohort_file)

    assert summary["row_count"] == 2
    assert summary["expected_total"] == 3
    assert summary["missing_sequence_count"] == 1
    assert summary["missing_sequences_sample"] == ["3"]
    assert summary["error_reason_counts"]["auth_expired"] == 1
