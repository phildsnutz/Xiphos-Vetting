import importlib
import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def sprs_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))

    for module_name in ["runtime_paths", "db", "artifact_vault", "sprs_import_intake"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import db  # type: ignore
    import sprs_import_intake  # type: ignore

    db.init_db()
    db.upsert_vendor(
        vendor_id="case-sprs-1",
        name="Cyber Trust Vendor",
        country="US",
        program="dod_unclassified",
        vendor_input={"name": "Cyber Trust Vendor", "country": "US", "program": "dod_unclassified"},
        profile="defense_acquisition",
    )
    return {"db": db, "sprs_import_intake": sprs_import_intake}


def test_ingest_sprs_export_matches_vendor_row_and_extracts_summary(sprs_env):
    sprs_import_intake = sprs_env["sprs_import_intake"]

    record = sprs_import_intake.ingest_sprs_export(
        "case-sprs-1",
        "Cyber Trust Vendor",
        "sprs.csv",
        (
            b"supplier_name,sprs_score,assessment_date,status,current_cmmc_level,poam\n"
            b"Other Vendor,80,2026-01-01,Active,1,No\n"
            b"Cyber Trust Vendor,109,2026-03-02,Conditional,2,Yes\n"
        ),
        uploaded_by="analyst-1",
        notes="Customer SPRS export",
    )

    summary = record["structured_fields"]["summary"]
    assert record["artifact_type"] == "sprs_export"
    assert record["source_system"] == "sprs_import"
    assert summary["matched_supplier_name"] == "Cyber Trust Vendor"
    assert summary["matched_exact_vendor"] is True
    assert summary["assessment_score"] == 109
    assert summary["assessment_date"] == "2026-03-02"
    assert summary["status"] == "Conditional"
    assert summary["current_cmmc_level"] == 2
    assert summary["poam_active"] is True
    assert record["structured_fields"]["notes"] == "Customer SPRS export"


def test_ingest_sprs_export_accepts_json_records_payload(sprs_env):
    sprs_import_intake = sprs_env["sprs_import_intake"]

    record = sprs_import_intake.ingest_sprs_export(
        "case-sprs-1",
        "Cyber Trust Vendor",
        "sprs.json",
        (
            b'{"records":[{"vendor_name":"Cyber Trust Vendor","assessment_score":"95","assessment_date":"2026-03-10",'
            b'"assessment_status":"Active","cmmc_level":"3","poam_status":"No"}]}'
        ),
    )

    summary = record["structured_fields"]["summary"]
    assert summary["assessment_score"] == 95
    assert summary["assessment_date"] == "2026-03-10"
    assert summary["status"] == "Active"
    assert summary["current_cmmc_level"] == 3
    assert summary["poam_active"] is False
