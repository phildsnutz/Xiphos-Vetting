from __future__ import annotations

import time


def test_shared_threat_intel_substrate_combines_attack_and_cisa_fixture_summaries():
    from osint import enrichment as enrichment_mod
    from osint.mitre_attack_fixture import enrich as attack_enrich
    from osint.cisa_advisory_fixture import enrich as advisory_enrich
    from threat_intel_substrate import build_threat_intel_summary

    report = enrichment_mod._build_report(
        "Apex Telemetry Systems",
        "US",
        [
            attack_enrich("Apex Telemetry Systems", "US"),
            advisory_enrich("Apex Telemetry Systems", "US"),
        ],
        time.time(),
    )

    summary = build_threat_intel_summary(report)

    assert summary is not None
    assert summary["shared_threat_intel_present"] is True
    assert summary["attack_actor_families"] == ["Volt Typhoon"]
    assert summary["attack_technique_ids"] == ["T1190", "T1078", "T1090", "T1098", "T1583"]
    assert summary["cisa_advisory_ids"] == ["AA24-057A", "AA22-047A"]
    assert summary["threat_pressure"] == "high"
