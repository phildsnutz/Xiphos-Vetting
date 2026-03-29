from __future__ import annotations

import importlib
import sys


def test_cyber_evidence_summary_merges_shared_threat_intel(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))

    for module_name in ["db", "cyber_evidence"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    if "db" not in sys.modules:
        import db  # type: ignore
    if "cyber_evidence" not in sys.modules:
        import cyber_evidence  # type: ignore

    db = sys.modules["db"]
    cyber_evidence = sys.modules["cyber_evidence"]
    db.init_db()

    case_id = "case-threat-intel"
    db.upsert_vendor(
        case_id,
        name="Apex Telemetry Systems",
        country="US",
        program="dod_unclassified",
        vendor_input={},
    )
    db.save_enrichment(
        case_id,
        {
            "overall_risk": "MEDIUM",
            "summary": {"connectors_run": 3, "connectors_with_data": 3, "findings_total": 3},
            "connector_status": {
                "public_assurance_evidence_fixture": {
                    "has_data": True,
                    "structured_fields": {
                        "summary": {
                            "public_evidence_present": True,
                            "evidence_quality": "strong",
                            "sbom_present": True,
                            "sbom_format": "CycloneDX",
                            "sbom_fresh_days": 7,
                            "vex_status": "not_affected",
                            "security_txt_present": True,
                            "psirt_contact_present": True,
                            "support_lifecycle_published": True,
                            "support_lifecycle_status": "published",
                            "provenance_attested": True,
                            "secure_by_design_evidence": "artifact_backed",
                            "artifact_kinds": ["sbom"],
                            "artifact_urls": ["https://trust.example/sbom.json"],
                        }
                    },
                },
                "mitre_attack_fixture": {
                    "has_data": True,
                    "structured_fields": {
                        "summary": {
                            "actor_families": ["Volt Typhoon"],
                            "campaigns": ["Edge-device access with living-off-the-land persistence"],
                            "technique_ids": ["T1190"],
                            "techniques": [{"id": "T1190", "name": "Exploit Public-Facing Application", "tactic": "Initial Access"}],
                            "tactics": ["Initial Access"],
                        }
                    },
                },
                "cisa_advisory_fixture": {
                    "has_data": True,
                    "structured_fields": {
                        "summary": {
                            "advisory_ids": ["AA24-057A"],
                            "advisory_titles": ["SVR Cyber Actors Adapt Tactics for Initial Cloud Access"],
                            "technique_ids": ["T1078"],
                            "sectors": ["defense industrial base"],
                            "mitigations": ["phishing-resistant MFA"],
                            "ioc_types": ["token_abuse"],
                        }
                    },
                },
            },
        },
    )

    summary = cyber_evidence.get_latest_cyber_evidence_summary(case_id)

    assert summary is not None
    assert summary["shared_threat_intel_present"] is True
    assert summary["attack_technique_ids"] == ["T1190", "T1078"]
    assert summary["cisa_advisory_ids"] == ["AA24-057A"]
