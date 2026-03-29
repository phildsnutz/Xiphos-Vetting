import importlib
import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def foci_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))

    for module_name in ["runtime_paths", "db", "artifact_vault", "foci_artifact_intake"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import db  # type: ignore
    import foci_artifact_intake  # type: ignore

    db.init_db()
    db.upsert_vendor(
        vendor_id="case-foci-1",
        name="Defense Counterparty Vendor",
        country="US",
        program="dod_unclassified",
        vendor_input={"name": "Defense Counterparty Vendor", "country": "US", "program": "dod_unclassified"},
        profile="defense_acquisition",
    )
    return {"db": db, "foci_artifact_intake": foci_artifact_intake}


def test_ingest_foci_artifact_extracts_mitigation_and_foreign_influence_hints(foci_env):
    foci_artifact_intake = foci_env["foci_artifact_intake"]

    record = foci_artifact_intake.ingest_foci_artifact(
        "case-foci-1",
        "foci_mitigation_instrument",
        "ssa-summary.txt",
        (
            b"Special Security Agreement for 25% foreign ownership. "
            b"Board observer rights and DCSA facility clearance review included."
        ),
        uploaded_by="analyst-1",
        declared_foreign_owner="Allied Parent Holdings",
        declared_foreign_country="GB",
        declared_mitigation_status="MITIGATED",
        declared_mitigation_type="SSA",
    )

    summary = record["structured_fields"]
    assert record["source_system"] == "foci_artifact_upload"
    assert record["artifact_type"] == "foci_mitigation_instrument"
    assert summary["declared_foreign_owner"] == "Allied Parent Holdings"
    assert summary["declared_foreign_country"] == "GB"
    assert summary["declared_mitigation_type"] == "SSA"
    assert summary["max_ownership_percent_mention"] == 25.0
    assert "SSA" in summary["mitigation_tokens"]
    assert summary["contains_foreign_influence_terms"] is True
    assert summary["contains_governance_control_terms"] is True
    assert summary["contains_clearance_terms"] is True


def test_ingest_foci_artifact_accepts_form_328_without_declared_fields(foci_env):
    foci_artifact_intake = foci_env["foci_artifact_intake"]

    record = foci_artifact_intake.ingest_foci_artifact(
        "case-foci-1",
        "foci_form_328",
        "form328.txt",
        b"Certificate Pertaining to Foreign Interests. Foreign ownership 12.5% with no current mitigation instrument.",
    )

    summary = record["structured_fields"]
    assert summary["artifact_label"] == "Form 328 / foreign interests certificate"
    assert summary["max_ownership_percent_mention"] == 12.5
    assert summary["contains_foreign_influence_terms"] is True
    assert record["parse_status"] == "parsed"
