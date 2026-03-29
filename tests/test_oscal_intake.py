import importlib
import json
import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def oscal_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))

    for module_name in ["runtime_paths", "db", "artifact_vault", "oscal_intake"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import db  # type: ignore
    import oscal_intake  # type: ignore

    db.init_db()
    db.upsert_vendor(
        vendor_id="case-oscal-1",
        name="Cyber Trust Vendor",
        country="US",
        program="dod_unclassified",
        vendor_input={"name": "Cyber Trust Vendor", "country": "US", "program": "dod_unclassified"},
        profile="defense_acquisition",
    )
    return {"db": db, "oscal_intake": oscal_intake}


def test_ingest_oscal_ssp_extracts_control_family_summary(oscal_env):
    oscal_intake = oscal_env["oscal_intake"]
    payload = {
        "system-security-plan": {
            "metadata": {
                "title": "Supplier SSP",
                "uuid": "ssp-uuid-1",
                "last-modified": "2026-03-20T00:00:00Z",
            },
            "system-characteristics": {"system-name": "Supplier Secure Environment"},
            "control-implementation": {
                "implemented-requirements": [
                    {"control-id": "ac-1"},
                    {"control-id": "ac-2"},
                    {"control-id": "sc-7"},
                ]
            },
        }
    }

    record = oscal_intake.ingest_oscal_artifact(
        "case-oscal-1",
        "ssp.json",
        json.dumps(payload).encode("utf-8"),
        uploaded_by="analyst-1",
    )

    summary = record["structured_fields"]["summary"]
    assert record["artifact_type"] == "oscal_ssp"
    assert summary["system_name"] == "Supplier Secure Environment"
    assert summary["total_control_references"] == 3
    assert summary["control_family_highlights"][0]["family"] == "AC"
    assert summary["control_family_highlights"][0]["count"] == 2


def test_ingest_oscal_poam_extracts_open_items_and_highlights(oscal_env):
    oscal_intake = oscal_env["oscal_intake"]
    payload = {
        "plan-of-action-and-milestones": {
            "metadata": {"title": "Supplier POA&M"},
            "system-characteristics": {"system-name": "Supplier Secure Environment"},
            "poam-items": [
                {
                    "id": "poam-1",
                    "title": "Encrypt removable media",
                    "status": "open",
                    "due-date": "2026-04-15",
                    "control-id": "sc-28",
                },
                {
                    "id": "poam-2",
                    "title": "Tighten access review cadence",
                    "status": "completed",
                    "control-id": "ac-2",
                },
            ],
        }
    }

    record = oscal_intake.ingest_oscal_artifact(
        "case-oscal-1",
        "poam.json",
        json.dumps(payload).encode("utf-8"),
    )

    summary = record["structured_fields"]["summary"]
    assert record["artifact_type"] == "oscal_poam"
    assert summary["open_poam_items"] == 1
    assert summary["closed_poam_items"] == 1
    assert summary["remediation_highlights"][0]["title"] == "Encrypt removable media"
    assert summary["remediation_highlights"][0]["due_date"] == "2026-04-15"
