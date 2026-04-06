import os
import sys
import types


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import comparative_dossier


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
    }


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

    monkeypatch.setattr(comparative_dossier, "build_dossier_context", lambda vendor_id: context if vendor_id == "case-1" else None)

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
    assert "Lineage Read" in html
    assert "Legal Read" in html
    assert "Competitive pressure is currently visible from Leidos." in html
    assert "Protest pressure is attached in 1 case event." in html
    assert "Evidence Footprint" in html
    assert "Connectors run: 6" in html
    assert "Connectors with signal: 3" in html
    assert "Tribunal consensus" in html
    assert "Moderate" in html
    assert "TechFlow Defense" not in html
    assert "Pacific Experimentation Vehicle" not in html
    assert "Direct prime competition unlikely to succeed" not in html


def test_generate_vehicle_dossier_marks_unresolved_instead_of_inventing_rows(monkeypatch):
    monkeypatch.setattr(comparative_dossier, "build_dossier_context", lambda vendor_id: None)

    html = comparative_dossier.generate_vehicle_dossier(
        vehicle_name="ITEAMS",
        prime_contractor="Amentum",
        vendor_ids=["missing-case"],
        contract_data={"naics": "541715"},
    )

    assert "No linked Helios case context was found" in html
    assert "No confirmed subcontractor or teaming relationships are attached" in html
    assert "No predecessor, successor, incumbent, competed-on, or award-under relationships are attached" in html
    assert "Connectors run: 0" in html
    assert "Connectors with signal: 0" in html
    assert "TechFlow Defense" not in html
    assert "Acme Systems Integration" not in html


def test_generate_vehicle_dossier_renders_teaming_intelligence_section(monkeypatch):
    monkeypatch.setattr(comparative_dossier, "build_dossier_context", lambda vendor_id: None)
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
    monkeypatch.setattr(comparative_dossier, "build_dossier_context", lambda vendor_id: contexts.get(vendor_id))

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
    assert "Persistent across both compared vehicles." in html
    assert "Both vehicles are populated." in html
    assert "Litigation & Protest Profile" in html
    assert "C3PO corrective action protest" in html
    assert "Lineage Read" in html
    assert "Legal Read" in html
    assert "Acme Defense Systems" not in html
    assert "TechFlow Corp" not in html
    assert "Complete audit trail of vehicle evolution." not in html
