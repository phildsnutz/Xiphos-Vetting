import os
import sys
import types
from pathlib import Path


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import comparative_dossier
import vehicle_intel_support


LIVE_VEHICLE_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "vehicle_intelligence" / "usaspending_vehicle_live_fixture.json"


def _make_context(*, vendor_name: str, relationships: list[dict], events: list[dict], findings: list[dict]):
    return {
        "vendor": {
            "id": f"case-{vendor_name.lower().replace(' ', '-')}",
            "name": vendor_name,
            "country": "US",
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
            "vendor_input": {},
        },
        "score": {
            "calibrated": {
                "calibrated_probability": 0.42,
                "calibrated_tier": "watch",
                "program_recommendation": "watch",
            }
        },
        "graph_summary": {
            "relationship_count": len(relationships),
            "entity_count": len(relationships) + 1,
            "relationships": relationships,
            "intelligence": {
                "claim_coverage_pct": 0.67,
                "missing_required_edge_families": [],
            },
        },
        "case_events": events,
        "enrichment": {
            "summary": {
                "connectors_run": 6,
                "connectors_with_data": 3,
            },
            "findings": findings,
        },
        "supplier_passport": {
            "graph": {
                "relationship_count": len(relationships),
                "network_relationship_count": len(relationships),
                "control_paths": [],
                "intelligence": {
                    "claim_coverage_pct": 0.67,
                    "missing_required_edge_families": [],
                },
            },
            "tribunal": {
                "recommended_view": "watch",
                "consensus_level": "moderate",
            },
        },
        "vehicle_intelligence": None,
    }


def _support_with_live_fixture(vehicle_name: str, prime_contractor: str) -> dict:
    return vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name=vehicle_name,
        vendor={
            "id": f"support-{vehicle_name.lower().replace(' ', '-')}",
            "name": prime_contractor,
            "vendor_input": {
                "seed_metadata": {
                    "contract_vehicle_name": vehicle_name,
                    "contract_vehicle_live_fixture_path": str(LIVE_VEHICLE_FIXTURE_PATH),
                }
            },
        },
    )


def test_generate_vehicle_dossier_uses_live_case_context(monkeypatch):
    context = _make_context(
        vendor_name="Amentum",
        relationships=[
            {
                "rel_type": "subcontractor_of",
                "source_name": "Kauai Labs",
                "target_name": "Amentum",
                "evidence": "SAM subaward record",
                "corroboration_count": 2,
                "data_sources": ["sam_gov"],
                "intelligence_tier": "supported",
            },
            {
                "rel_type": "competed_on",
                "source_name": "Leidos",
                "target_name": "ITEAMS",
                "evidence": "GAO protest filing",
                "corroboration_count": 1,
                "data_sources": ["courtlistener"],
                "intelligence_tier": "supported",
            },
        ],
        events=[
            {
                "title": "ITEAMS award protest",
                "status": "dismissed",
                "connector": "courtlistener",
                "assessment": "GAO dismissed the protest without staying performance.",
            }
        ],
        findings=[
            {
                "title": "Amentum teammate persistence detected",
                "detail": "SAM.gov subaward history shows Kauai Labs recurring on the current vehicle context.",
                "severity": "high",
                "source": "sam_gov",
            }
        ],
    )

    context["vehicle_intelligence"] = {
        "vehicle_name": "ITEAMS",
        "connectors_run": 2,
        "connectors_with_data": 2,
        "relationships": [
            {
                "rel_type": "awarded_under",
                "source_name": "OASIS",
                "target_name": "ITEAMS",
                "evidence": "Archived SAM opportunity snapshot",
                "evidence_summary": "Archived SAM opportunity snapshot",
                "corroboration_count": 2,
                "data_sources": ["contract_opportunities_archive_fixture"],
                "intelligence_tier": "supported",
            }
        ],
        "events": [
            {
                "title": "ITEAMS task-order protest",
                "status": "dismissed",
                "connector": "gao_bid_protests_fixture",
                "assessment": "Protester: Leidos. GAO dismissed the protest after limited corrective action.",
            }
        ],
        "findings": [
            {
                "title": "Archived lineage trail keeps ITEAMS tied to OASIS",
                "detail": "Archive and diff captures preserve the OASIS scaffolding around ITEAMS.",
                "severity": "medium",
                "source": "contract_opportunities_archive_fixture",
            }
        ],
    }

    monkeypatch.setattr(
        comparative_dossier,
        "build_dossier_context",
        lambda vendor_id, **_: context if vendor_id == "case-1" else None,
    )

    html = comparative_dossier.generate_vehicle_dossier(
        vehicle_name="ITEAMS",
        prime_contractor="Amentum",
        vendor_ids=["case-1"],
        contract_data={
            "naics": "541715",
            "contract_id": "N00164-24-F-3004",
            "award_date": "2024-04-03",
            "task_orders": 17,
            "revenue": 13400000000,
            "employees": 53000,
        },
    )

    assert "Kauai Labs" in html
    assert "SAM subaward record" in html
    assert "ITEAMS award protest" in html
    assert "ITEAMS task-order protest" in html
    assert "Lineage Read" in html
    assert "Competitive Landscape" in html
    assert "Legal Read" in html
    assert "Legal Pressure" in html
    assert "Award scaffold remains attached through OASIS." in html
    assert "Competitive pressure is currently visible from Leidos." in html
    assert "Award scaffold still ties ITEAMS to OASIS." in html
    assert "Named competitive pressure currently comes from Leidos." in html
    assert "Protest pressure is attached in 2 case events." in html
    assert "Protester: Leidos" in html
    assert "Named protest actors include Leidos." in html
    assert "Capture Outlook" in html
    assert "Evidence Footprint" in html
    assert "Sources queried: 8" in html
    assert "Sources with findings: 5" in html
    assert "Contract Opportunities Archive Fixture" in html
    assert "GAO Bid Protests Fixture" in html
    assert "Tribunal consensus" in html
    assert "Moderate" in html
    assert "TechFlow Defense" not in html
    assert "Pacific Experimentation Vehicle" not in html
    assert "Direct prime competition unlikely to succeed" not in html


def test_generate_vehicle_dossier_marks_unresolved_instead_of_inventing_rows(monkeypatch):
    monkeypatch.setattr(comparative_dossier, "build_dossier_context", lambda vendor_id, **_: None)

    html = comparative_dossier.generate_vehicle_dossier(
        vehicle_name="NO_SUCH_VEHICLE",
        prime_contractor="Unknown Prime",
        vendor_ids=["missing-case"],
        contract_data={"naics": "541715"},
    )

    assert "No linked vendor cases available" in html
    assert "No confirmed subcontractor or teaming relationships are attached" in html
    assert "No predecessor, successor, incumbent, competed-on, or award-under relationships are attached" in html
    assert "Sources queried: 0" in html
    assert "Sources with findings: 0" in html
    assert "TechFlow Defense" not in html
    assert "Acme Systems Integration" not in html


def test_generate_vehicle_dossier_uses_vehicle_support_without_linked_case(monkeypatch):
    monkeypatch.setattr(comparative_dossier, "build_dossier_context", lambda vendor_id, **_: None)
    monkeypatch.setattr(
        comparative_dossier,
        "build_vehicle_intelligence_support",
        lambda *, vehicle_name, vendor=None, sync_graph=False: _support_with_live_fixture(vehicle_name, str((vendor or {}).get("name") or "SMX")),
    )

    html = comparative_dossier.generate_vehicle_dossier(
        vehicle_name="LEIA",
        prime_contractor="SMX",
        vendor_ids=["missing-case"],
        contract_data={"naics": "541512"},
    )

    assert "vehicle-scoped support evidence only" in html
    assert "Lineage Read" in html
    assert "Award scaffold remains attached through ASTRO." in html
    assert "LEIA is currently being worked from vehicle-scoped support evidence." in html
    assert "Evidence Footprint" in html
    assert "Contract Opportunities Public" in html
    assert "Contract Opportunities Archive Fixture" in html
    assert "Sources with findings: 3" in html


def test_generate_vehicle_dossier_uses_support_only_path_for_broader_seeded_vehicle_set(monkeypatch):
    monkeypatch.setattr(comparative_dossier, "build_dossier_context", lambda vendor_id, **_: None)
    monkeypatch.setattr(
        comparative_dossier,
        "build_vehicle_intelligence_support",
        lambda *, vehicle_name, vendor=None, sync_graph=False: _support_with_live_fixture(vehicle_name, str((vendor or {}).get("name") or vehicle_name)),
    )

    sewp_html = comparative_dossier.generate_vehicle_dossier(
        vehicle_name="SEWP",
        prime_contractor="NASA SEWP Program Office",
        vendor_ids=["support-only-sewp"],
        contract_data={"naics": "541519"},
    )
    cio_html = comparative_dossier.generate_vehicle_dossier(
        vehicle_name="CIO-SP4",
        prime_contractor="NITAAC",
        vendor_ids=["support-only-cio-sp4"],
        contract_data={"naics": "541512"},
    )

    for html in (sewp_html, cio_html):
        assert "vehicle-scoped support evidence only" in html
        assert "Lineage Read" in html
        assert "Legal Read" in html
        assert "Capture Outlook" in html
        assert "Evidence Footprint" in html
        assert "Contract Opportunities Public" in html
        assert "Sources with findings: 2" in html
        assert "No case-level protest or litigation events are attached" in html

    assert "SEWP V" in sewp_html
    assert "NASA SEWP Program Office" in sewp_html
    assert "CIO-SP3" in cio_html
    assert "NIH Information Technology Acquisition and Assessment Center" in cio_html


def test_generate_vehicle_dossier_support_only_non_seeded_vehicle_uses_live_award_support(monkeypatch):
    monkeypatch.setattr(comparative_dossier, "build_dossier_context", lambda vendor_id, **_: None)
    monkeypatch.setattr(
        comparative_dossier,
        "build_vehicle_intelligence_support",
        lambda *, vehicle_name, vendor=None, sync_graph=False: _support_with_live_fixture(vehicle_name, str((vendor or {}).get("name") or "Science Applications International Corporation")),
    )

    html = comparative_dossier.generate_vehicle_dossier(
        vehicle_name="OASIS",
        prime_contractor="Science Applications International Corporation",
        vendor_ids=["support-only-oasis"],
        contract_data={"naics": "541611"},
    )

    assert "vehicle-scoped support evidence only" in html
    assert "Live award picture" in html
    assert "USAspending" in html
    assert "Vehicle Live" in html
    assert "General Services Administration" in html
    assert "OASIS Systems, LLC" in html
    assert "Sources with findings: 1" in html


def test_generate_vehicle_dossier_lineage_read_uses_wayback_support_relationships(monkeypatch):
    context = _make_context(
        vendor_name="Amentum",
        relationships=[],
        events=[],
        findings=[],
    )
    context["vehicle_intelligence"] = {
        "vehicle_name": "ITEAMS",
        "connectors_run": 1,
        "connectors_with_data": 1,
        "relationships": [
            {
                "rel_type": "awarded_under",
                "source_name": "OASIS",
                "target_name": "ITEAMS",
                "evidence": "Archived capture preserved contract family context.",
                "evidence_summary": "Archived capture preserved contract family context.",
                "corroboration_count": 2,
                "data_sources": ["contract_vehicle_wayback"],
                "intelligence_tier": "supported",
            },
            {
                "rel_type": "predecessor_of",
                "source_name": "IPIESS",
                "target_name": "ITEAMS",
                "evidence": "Seeded archive captures preserve predecessor transition language.",
                "evidence_summary": "Seeded archive captures preserve predecessor transition language.",
                "corroboration_count": 2,
                "data_sources": ["contract_vehicle_wayback"],
                "intelligence_tier": "supported",
            },
        ],
        "events": [],
        "findings": [
            {
                "title": "Wayback capture preserved ITEAMS lineage",
                "detail": "Archive snapshots keep the predecessor and award scaffold in frame.",
                "severity": "medium",
                "source": "contract_vehicle_wayback",
            }
        ],
    }

    monkeypatch.setattr(
        comparative_dossier,
        "build_dossier_context",
        lambda vendor_id, **_: context if vendor_id == "case-1" else None,
    )

    html = comparative_dossier.generate_vehicle_dossier(
        vehicle_name="ITEAMS",
        prime_contractor="Amentum",
        vendor_ids=["case-1"],
        contract_data={"naics": "541715"},
    )

    assert "Lineage Read" in html
    assert "Award scaffold remains attached through OASIS." in html
    assert "Predecessor path observed through IPIESS." in html
    assert "Follow-on posture still traces back to IPIESS." in html
    assert "Contract Vehicle Wayback" in html


def test_generate_vehicle_dossier_renders_teaming_intelligence_section(monkeypatch):
    monkeypatch.setattr(comparative_dossier, "build_dossier_context", lambda vendor_id, **_: None)
    fake_module = types.SimpleNamespace(
        build_teaming_intelligence=lambda **_: {
            "top_conclusions": [
                "Amentum remains the incumbent-core read on ITEAMS.",
                "Kupono reads as locked to the incumbent.",
            ],
            "assessed_partners": [
                {
                    "entity_name": "Amentum Holdings, Inc.",
                    "display_name": "Amentum",
                    "classification": "incumbent-core",
                    "confidence_label": "high",
                    "rationale": "Observed as current prime on the vehicle.",
                    "evidence": [{"connector": "sam_gov", "snippet": "Prime on ITEAMS"}],
                },
                {
                    "entity_name": "Kupono Government Services",
                    "display_name": "Kupono",
                    "classification": "locked",
                    "confidence_label": "medium",
                    "rationale": "Confirmed teammate relationship to the incumbent.",
                    "evidence": [{"connector": "sam_gov", "snippet": "JV partnership on PMRF"}],
                },
            ],
        }
    )
    monkeypatch.setitem(sys.modules, "teaming_intelligence", fake_module)

    html = comparative_dossier.generate_vehicle_dossier(
        vehicle_name="ITEAMS",
        prime_contractor="Amentum",
        vendor_ids=["missing-case"],
        contract_data={"naics": "541715"},
    )

    assert "Competitive Teaming Map" in html
    assert "Aegis Teaming Read" in html
    assert "Kupono" in html


def test_generate_comparative_dossier_uses_observed_overlap_not_sample_rows(monkeypatch):
    contexts = {
        "case-leia": _make_context(
            vendor_name="SMX",
            relationships=[
                {
                    "rel_type": "teamed_with",
                    "source_name": "Kauai Labs",
                    "target_name": "SMX",
                    "evidence": "USASpending award teammate signal",
                    "corroboration_count": 2,
                    "data_sources": ["usaspending"],
                    "intelligence_tier": "supported",
                },
                {
                    "rel_type": "predecessor_of",
                    "source_name": "LEIA Bridge",
                    "target_name": "LEIA",
                    "evidence": "Program lineage evidence",
                    "corroboration_count": 1,
                    "data_sources": ["analyst_curated_fixture"],
                    "intelligence_tier": "supported",
                },
            ],
            events=[],
            findings=[
                {
                    "title": "LEIA teammate overlap confirmed",
                    "detail": "Kauai Labs is present on the live LEIA case context.",
                    "severity": "medium",
                    "source": "usaspending",
                }
            ],
        ),
        "case-c3po": _make_context(
            vendor_name="Amentum",
            relationships=[
                {
                    "rel_type": "teamed_with",
                    "source_name": "Kauai Labs",
                    "target_name": "Amentum",
                    "evidence": "SAM subaward recurrence",
                    "corroboration_count": 3,
                    "data_sources": ["sam_gov"],
                    "intelligence_tier": "supported",
                },
                {
                    "rel_type": "teamed_with",
                    "source_name": "Sentinel Ops",
                    "target_name": "Amentum",
                    "evidence": "Additional teammate detected",
                    "corroboration_count": 1,
                    "data_sources": ["public_html"],
                    "intelligence_tier": "tentative",
                },
            ],
            events=[
                {
                    "title": "C3PO corrective action protest",
                    "status": "corrective_action",
                    "connector": "courtlistener",
                    "assessment": "A corrective-action signal is attached to the compared vehicle context.",
                }
            ],
            findings=[],
        ),
    }
    monkeypatch.setattr(comparative_dossier, "build_dossier_context", lambda vendor_id, **_: contexts.get(vendor_id))

    html = comparative_dossier.generate_comparative_dossier(
        vehicle_configs=[
            {
                "vehicle_name": "LEIA",
                "prime_contractor": "SMX",
                "vendor_ids": ["case-leia"],
                "contract_data": {"contract_id": "LEIA-1", "award_date": "2024-01-10", "task_orders": 5},
            },
            {
                "vehicle_name": "C3PO",
                "prime_contractor": "Amentum",
                "vendor_ids": ["case-c3po"],
                "contract_data": {"contract_id": "C3PO-1", "award_date": "2024-02-20", "task_orders": 8},
            },
        ]
    )

    assert "Kauai Labs" in html
    assert "Both vehicles are populated." in html
    assert "Litigation & Protest Profile" in html
    assert "C3PO corrective action protest" in html
    assert "Lineage Read" in html
    assert "Legal Read" in html
    assert "Competitive Landscape" in html
    assert "Acme Defense Systems" not in html
    assert "TechFlow Corp" not in html
    assert "Complete audit trail of vehicle evolution." not in html


def test_generate_comparative_dossier_support_only_proves_multiple_seeded_vehicles(monkeypatch):
    monkeypatch.setattr(comparative_dossier, "build_dossier_context", lambda *_, **__: None)

    html = comparative_dossier.generate_comparative_dossier(
        vehicle_configs=[
            {
                "vehicle_name": "ITEAMS",
                "prime_contractor": "Amentum",
                "vendor_ids": ["missing-iteams-case"],
                "contract_data": {"contract_id": "ITEAMS-001", "award_date": "2025-01-10", "task_orders": 7},
            },
            {
                "vehicle_name": "LEIA",
                "prime_contractor": "SMX",
                "vendor_ids": ["missing-leia-case"],
                "contract_data": {"contract_id": "LEIA-002", "award_date": "2025-03-22", "task_orders": 4},
            },
        ]
    )

    assert "ITEAMS" in html
    assert "LEIA" in html
    assert "Vehicle Lineage Map" in html
    assert "Litigation & Protest Profile" in html
    assert "Contract Opportunities Public" in html
    assert "Teaming relationships are derived from corroborated graph evidence" in html
    assert "Both vehicles are populated." in html
