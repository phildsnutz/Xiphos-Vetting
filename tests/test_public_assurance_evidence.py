import importlib
import os
import sys
import time


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_public_assurance_fixture_returns_first_party_summary():
    from osint.public_assurance_evidence_fixture import enrich

    result = enrich("Horizon Mission Systems LLC", "US")

    assert result.has_data
    assert result.source == "public_assurance_evidence_fixture"
    summary = result.structured_fields["summary"]
    assert summary["sbom_present"] is True
    assert summary["vex_status"] == "not_affected"
    assert summary["provenance_attested"] is True
    assert summary["package_inventory_count"] == 2
    assert summary["repository_count"] == 1
    assert "sbom" in summary["artifact_kinds"]
    assert len(result.identifiers["package_inventory"]) == 2
    assert result.identifiers["repository_urls"] == ["https://github.com/horizon-mission/telemetry-core"]


def test_cyber_summary_includes_public_assurance_without_customer_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))

    import db
    import cyber_evidence

    importlib.reload(db)
    importlib.reload(cyber_evidence)

    db.init_db()
    db.upsert_vendor(
        "case-public-assurance",
        "Horizon Mission Systems LLC",
        "US",
        "dod_unclassified",
        {},
    )

    from osint.public_assurance_evidence_fixture import enrich
    from osint import enrichment as enrichment_mod

    report = enrichment_mod._build_report(
        "Horizon Mission Systems LLC",
        "US",
        [enrich("Horizon Mission Systems LLC", "US")],
        time.time(),
    )
    db.save_enrichment("case-public-assurance", report)

    summary = cyber_evidence.get_latest_cyber_evidence_summary("case-public-assurance")

    assert summary is not None
    assert summary["public_evidence_present"] is True
    assert summary["sbom_present"] is True
    assert summary["vex_status"] == "not_affected"
    assert summary["provenance_attested"] is True
    assert "public_sbom" in summary["artifact_sources"]
    assert "public_assurance_evidence_fixture" in summary["artifact_sources"]


def test_workflow_control_summary_treats_public_assurance_as_partial_support():
    from workflow_control_summary import build_workflow_control_summary

    summary = build_workflow_control_summary(
        {"id": "case-1", "name": "Horizon Mission Systems LLC", "profile": "defense_acquisition"},
        cyber_summary={
            "public_evidence_present": True,
            "sbom_present": True,
            "vex_status": "not_affected",
            "provenance_attested": True,
            "artifact_sources": ["public_sbom", "public_vex", "public_provenance"],
        },
    )

    assert summary["lane"] == "cyber"
    assert summary["support_level"] == "partial"
    assert "Public" in summary["label"]
    assert "first-party public assurance evidence" in summary["review_basis"].lower()


def test_dossier_cyber_section_mentions_public_assurance_evidence():
    from dossier import _generate_cyber_evidence_section

    html = _generate_cyber_evidence_section(
        {
            "public_evidence_present": True,
            "sbom_present": True,
            "sbom_format": "CycloneDX",
            "sbom_fresh_days": 21,
            "vex_status": "not_affected",
            "security_txt_present": True,
            "psirt_contact_present": True,
            "support_lifecycle_published": True,
            "provenance_attested": True,
            "artifact_sources": [
                "public_sbom",
                "public_vex",
                "public_security_txt",
                "public_provenance",
                "public_support_lifecycle",
            ],
        }
    )

    assert "Public assurance evidence" in html
    assert "First-party public assurance evidence shows" in html
    assert "CycloneDX SBOM published (21 days old)" in html


def test_hybrid_assurance_review_uses_public_assurance_fields():
    from supply_chain_assurance_ai_challenge import build_hybrid_assurance_review

    review = build_hybrid_assurance_review(
        {
            "public_evidence_present": True,
            "sbom_present": True,
            "sbom_format": "CycloneDX",
            "sbom_fresh_days": 14,
            "vex_status": "not_affected",
            "provenance_attested": True,
            "support_lifecycle_published": True,
            "secure_by_design_evidence": "artifact_backed",
            "artifact_sources": [
                "public_sbom",
                "public_vex",
                "public_provenance",
                "public_support_lifecycle",
            ],
        },
        vendor={"id": "case-2", "name": "Horizon Mission Systems LLC", "profile": "defense_acquisition", "program": "dod_unclassified"},
        supplier_passport={"network_risk": {"high_risk_neighbors": 0}},
    )

    assert review is not None
    assert "SBOM published" in review["deterministic_reason_summary"]
    assert review["artifact_sources"] == [
        "public_sbom",
        "public_vex",
        "public_provenance",
        "public_support_lifecycle",
    ]
