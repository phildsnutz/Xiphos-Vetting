import importlib
import os
import stat
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def artifact_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    for module_name in ["runtime_paths", "db", "artifact_vault"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import db  # type: ignore
    import artifact_vault  # type: ignore

    db.init_db()
    db.upsert_vendor(
        vendor_id="case-art-1",
        name="Artifact Vendor",
        country="US",
        program="dod_unclassified",
        vendor_input={"name": "Artifact Vendor", "country": "US", "program": "dod_unclassified"},
        profile="defense_acquisition",
    )
    return {"db": db, "artifact_vault": artifact_vault, "tmp_path": tmp_path}


def test_store_artifact_persists_private_file_and_metadata(artifact_env):
    artifact_vault = artifact_env["artifact_vault"]

    record = artifact_vault.store_artifact(
        "case-art-1",
        "sprs_export",
        "../../SPRS Export 2026-03.csv",
        b"score,status\n110,conditional\n",
        source_system="sprs_import",
        uploaded_by="analyst-1",
        retention_class="pilot",
        sensitivity="sensitive",
        structured_fields={"supplier_id": "ABC123", "score": 110},
    )

    assert record is not None
    assert record["filename"] == "SPRS_Export_2026-03.csv"
    assert record["source_class"] == "gated_federal_source"
    assert record["authority_level"] == "official_program_system"
    assert record["access_model"] == "customer_upload"
    assert record["retention_class"] == "pilot"
    assert record["sensitivity"] == "sensitive"
    assert record["structured_fields"]["score"] == 110
    assert record["storage_ref"].startswith("case-art-1/")
    assert ".." not in record["storage_ref"]
    assert record["exists"] is True

    path = record["artifact_path"]
    assert os.path.isfile(path)
    assert artifact_vault.read_artifact_bytes(record["id"]) == b"score,status\n110,conditional\n"

    if os.name != "nt":
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode & 0o077 == 0


def test_list_case_artifacts_and_update_round_trip(artifact_env):
    artifact_vault = artifact_env["artifact_vault"]
    db = artifact_env["db"]

    record = artifact_vault.store_artifact(
        "case-art-1",
        "foci_disclosure",
        "Form328.pdf",
        b"%PDF-form-328",
        source_system="foci_artifact_upload",
        parse_status="pending",
        structured_fields={"foreign_interest_flag": True},
    )

    updated = db.update_artifact_record(
        record["id"],
        parse_status="parsed",
        structured_fields={"foreign_interest_flag": True, "review_status": "needs_review"},
    )
    assert updated is True

    records = artifact_vault.list_case_artifacts("case-art-1")
    assert len(records) == 1
    assert records[0]["id"] == record["id"]
    assert records[0]["parse_status"] == "parsed"
    assert records[0]["structured_fields"]["review_status"] == "needs_review"
