import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from export_artifact_intake import ingest_export_artifact


def test_ingest_export_artifact_extracts_control_hints(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "artifact-intake.db"))

    import db

    db.init_db()
    db.upsert_vendor(
        "c-export",
        "Export Vendor",
        "US",
        "dual_use_ear",
        {"name": "Export Vendor", "country": "US", "program": "dual_use_ear"},
        profile="itar_trade_compliance",
    )

    record = ingest_export_artifact(
        "c-export",
        "export_classification_memo",
        "classification.txt",
        (
            b"ECCN 3A001 technical note.\n"
            b"Potential CCATS follow-up.\n"
            b"Foreign person access requires deemed export review.\n"
        ),
        uploaded_by="analyst-1",
        declared_classification="3A001",
        declared_jurisdiction="ear",
    )

    fields = record["structured_fields"]
    assert fields["declared_classification"] == "3A001"
    assert fields["declared_jurisdiction"] == "ear"
    assert "3A001" in fields["detected_classifications"]
    assert "CCATS" in fields["detected_license_tokens"]
    assert fields["contains_foreign_person_terms"] is True
    assert record["parse_status"] == "parsed"
