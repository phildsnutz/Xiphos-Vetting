import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


import dossier  # type: ignore  # noqa: E402


def test_build_dossier_context_caches_heavy_graph_and_passport_work(monkeypatch):
    vendor_id = "c-cache"
    calls = {"graph": 0, "passport": 0, "vehicle_intelligence": 0}

    monkeypatch.setattr(
        dossier.db,
        "get_vendor",
        lambda _vendor_id: {
            "id": vendor_id,
            "name": "Cache Vendor",
            "updated_at": "2026-03-27T12:02:00Z",
            "vendor_input": {"seed_metadata": {"contract_vehicle_name": "ITEAMS"}},
        },
    )
    monkeypatch.setattr(dossier.db, "get_latest_score", lambda _vendor_id: {"scored_at": "2026-03-27T12:00:00Z"})
    monkeypatch.setattr(dossier.db, "get_latest_enrichment", lambda _vendor_id: {"enriched_at": "2026-03-27T12:01:00Z"})
    monkeypatch.setattr(dossier.db, "get_monitoring_history", lambda _vendor_id, limit=10: [])
    monkeypatch.setattr(dossier.db, "get_decisions", lambda _vendor_id, limit=50: [])
    monkeypatch.setattr(dossier.db, "get_case_events", lambda _vendor_id, report_hash: [])
    monkeypatch.setattr(dossier.db, "get_latest_intel_summary", lambda _vendor_id, user_id="", report_hash="": None)
    monkeypatch.setattr(dossier, "HAS_FOCI_EVIDENCE", False)
    monkeypatch.setattr(dossier, "HAS_CYBER_EVIDENCE", False)
    monkeypatch.setattr(dossier, "HAS_EXPORT_EVIDENCE", False)
    monkeypatch.setattr(dossier, "_build_dossier_storyline", lambda *args, **kwargs: {"cards": []})
    monkeypatch.setattr(dossier, "_get_dossier_analysis_data", lambda *args, **kwargs: None)

    def fake_graph_summary(
        _vendor_id,
        depth=2,
        include_provenance=True,
        max_claim_records=4,
        max_evidence_records=4,
    ):
        calls["graph"] += 1
        assert depth == 2
        assert include_provenance is True
        assert max_claim_records == 2
        assert max_evidence_records == 2
        return {"entity_count": 1, "relationship_count": 1, "entities": [], "relationships": []}

    def fake_passport(_vendor_id, **kwargs):
        calls["passport"] += 1
        assert kwargs.get("graph_summary", {}).get("entity_count") == 1
        assert kwargs.get("vendor", {}).get("id") == vendor_id
        return {"identity": {}, "graph": {"entity_count": 1, "relationship_count": 1}}

    def fake_vehicle_intelligence(*, vehicle_name, vendor, sync_graph=False):
        calls["vehicle_intelligence"] += 1
        assert vehicle_name == "ITEAMS"
        assert vendor["id"] == vendor_id
        assert sync_graph is True
        return {
            "vehicle_name": vehicle_name,
            "connectors_run": 2,
            "connectors_with_data": 1,
            "relationships": [],
            "events": [],
            "findings": [],
        }

    monkeypatch.setattr(dossier, "HAS_GRAPH_SUMMARY", True)
    monkeypatch.setattr(dossier, "get_vendor_graph_summary", fake_graph_summary)
    monkeypatch.setattr(dossier, "HAS_SUPPLIER_PASSPORT", True)
    monkeypatch.setattr(dossier, "build_supplier_passport", fake_passport)
    monkeypatch.setattr(dossier, "HAS_VEHICLE_INTEL_SUPPORT", True)
    monkeypatch.setattr(dossier, "build_vehicle_intelligence_support", fake_vehicle_intelligence)

    dossier.clear_dossier_context_cache()
    first = dossier.build_dossier_context(vendor_id, user_id="dev", hydrate_ai=False, vehicle_name="ITEAMS")
    second = dossier.build_dossier_context(vendor_id, user_id="dev", hydrate_ai=False, vehicle_name="ITEAMS")
    third = dossier.build_dossier_context(vendor_id, user_id="dev", hydrate_ai=False, vehicle_name="LEIA")

    assert first is not None
    assert second is not None
    assert third is not None
    assert calls == {"graph": 2, "passport": 2, "vehicle_intelligence": 2}
    assert second["vendor"]["id"] == vendor_id
    assert first["vehicle_intelligence"]["vehicle_name"] == "ITEAMS"


def test_generate_ai_narrative_renders_pending_section_when_analysis_missing():
    html = dossier._generate_ai_narrative("c-ai", {"name": "AI Vendor"}, None)
    assert "Axiom Assessment" in html
    assert "Executive judgment" in html
    assert "PENDING" in html
