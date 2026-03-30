import importlib
import os
import sys


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from entity_resolution import ResolvedEntity  # noqa: E402


def _reload_kg():
    if "knowledge_graph" in sys.modules:
        importlib.reload(sys.modules["knowledge_graph"])
    else:
        importlib.import_module("knowledge_graph")
    return sys.modules["knowledge_graph"]


def _reload_graph_ingest():
    if "graph_ingest" in sys.modules:
        importlib.reload(sys.modules["graph_ingest"])
    else:
        importlib.import_module("graph_ingest")
    return sys.modules["graph_ingest"]


def _entity(entity_id: str, name: str, entity_type: str = "company") -> ResolvedEntity:
    return ResolvedEntity(
        id=entity_id,
        canonical_name=name,
        entity_type=entity_type,
        aliases=[],
        identifiers={},
        country="US",
        sources=["test"],
        confidence=0.9,
        last_updated="2026-03-26T12:00:00Z",
    )


def test_save_relationship_creates_claims_and_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path))
    kg = _reload_kg()
    kg.init_kg_db()

    kg.save_entity(_entity("entity:a", "Alpha Systems"))
    kg.save_entity(_entity("entity:b", "Beta Controls"))

    kg.save_relationship(
        "entity:a",
        "entity:b",
        "owned_by",
        confidence=0.91,
        data_source="gleif_bods_ownership_fixture",
        evidence="Modeled ultimate parent statement",
        observed_at="2026-03-26T08:00:00Z",
        valid_from="2025-01-01T00:00:00Z",
        artifact_ref="fixture://ownership/ownership-fixture-001",
        evidence_url="https://example.com/ownership",
        evidence_title="Ownership control path",
        structured_fields={"standards": ["GLEIF Level 2", "BODS"]},
        source_class="analyst_fixture",
        authority_level="standards_modeled_fixture",
        access_model="local_json_fixture",
        vendor_id="case-alpha",
    )

    with kg.get_kg_conn() as conn:
        claim_count = conn.execute("SELECT COUNT(*) FROM kg_claims").fetchone()[0]
        evidence_count = conn.execute("SELECT COUNT(*) FROM kg_evidence").fetchone()[0]
        agent_count = conn.execute("SELECT COUNT(*) FROM kg_asserting_agents").fetchone()[0]
        activity_count = conn.execute("SELECT COUNT(*) FROM kg_source_activities").fetchone()[0]

    assert claim_count == 1
    assert evidence_count == 1
    assert agent_count == 1
    assert activity_count == 1

    stats = kg.get_kg_stats()
    assert stats["claim_count"] == 1
    assert stats["evidence_count"] == 1


def test_entity_network_aggregates_corroborating_relationships(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path))
    kg = _reload_kg()
    kg.init_kg_db()

    kg.save_entity(_entity("entity:a", "Alpha Systems"))
    kg.save_entity(_entity("entity:b", "Beta Controls"))

    kg.save_relationship(
        "entity:a",
        "entity:b",
        "beneficially_owned_by",
        confidence=0.86,
        data_source="gleif_bods_ownership_fixture",
        evidence="Modeled ownership statement one",
        evidence_url="https://example.test/ownership-one",
        artifact_ref="fixture://ownership/one",
    )
    kg.save_relationship(
        "entity:a",
        "entity:b",
        "beneficially_owned_by",
        confidence=0.89,
        data_source="opencorporates",
        evidence="Modeled ownership statement two",
        evidence_url="https://example.test/ownership-two",
        artifact_ref="fixture://ownership/two",
    )

    network = kg.get_entity_network("entity:a", depth=1)
    assert network["relationship_count"] == 1
    relationship = network["relationships"][0]
    assert relationship["corroboration_count"] == 2
    assert relationship["data_sources"] == ["gleif_bods_ownership_fixture", "opencorporates"]
    assert len(relationship["evidence_snippets"]) == 2
    assert relationship["confidence"] == 0.89
    assert len(relationship["claim_records"]) == 2
    first_claim = relationship["claim_records"][0]
    assert first_claim["claim_id"].startswith("claim:")
    assert first_claim["evidence_records"][0]["url"].startswith("https://example.test/")
    assert first_claim["evidence_records"][0]["artifact_ref"].startswith("fixture://ownership/")


def test_entity_network_can_skip_full_provenance_hydration(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path))
    kg = _reload_kg()
    kg.init_kg_db()

    kg.save_entity(_entity("entity:a", "Alpha Systems"))
    kg.save_entity(_entity("entity:b", "Beta Controls"))

    kg.save_relationship(
        "entity:a",
        "entity:b",
        "beneficially_owned_by",
        confidence=0.86,
        data_source="gleif_bods_ownership_fixture",
        evidence="Modeled ownership statement",
        evidence_url="https://example.test/ownership",
        artifact_ref="fixture://ownership/one",
    )

    network = kg.get_entity_network("entity:a", depth=1, include_provenance=False)

    assert network["relationship_count"] == 1
    relationship = network["relationships"][0]
    assert relationship["corroboration_count"] == 1
    assert relationship["claim_records"] == []

    hydrated = kg.attach_relationship_provenance(network["relationships"], max_claim_records=1, max_evidence_records=1)
    assert len(hydrated[0]["claim_records"]) == 1
    assert len(hydrated[0]["claim_records"][0]["evidence_records"]) == 1


def test_save_relationship_scopes_claims_by_vendor(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path))
    kg = _reload_kg()
    kg.init_kg_db()

    kg.save_entity(_entity("entity:a", "Alpha Systems"))
    kg.save_entity(_entity("entity:b", "Beta Controls"))

    kwargs = {
        "confidence": 0.86,
        "data_source": "public_html_ownership",
        "evidence": "Ownership statement on company site",
        "artifact_ref": "https://example.test/ownership",
        "evidence_url": "https://example.test/ownership",
        "evidence_title": "Ownership page",
    }
    kg.save_relationship("entity:a", "entity:b", "owned_by", vendor_id="case-alpha", **kwargs)
    kg.save_relationship("entity:a", "entity:b", "owned_by", vendor_id="case-bravo", **kwargs)

    with kg.get_kg_conn() as conn:
        claim_count = conn.execute("SELECT COUNT(*) FROM kg_claims").fetchone()[0]
        vendor_ids = {
            row["vendor_id"]
            for row in conn.execute("SELECT vendor_id FROM kg_claims").fetchall()
        }

    assert claim_count == 2
    assert vendor_ids == {"case-alpha", "case-bravo"}


def test_clear_vendor_graph_state_removes_stale_vendor_relationships(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path))
    kg = _reload_kg()
    kg.init_kg_db()

    kg.save_entity(_entity("entity:a", "Alpha Systems"))
    kg.save_entity(_entity("entity:bad", "Bad Parent", entity_type="holding_company"))
    kg.link_entity_to_vendor("entity:a", "case-alpha")
    kg.link_entity_to_vendor("entity:bad", "case-alpha")
    kg.save_relationship(
        "entity:a",
        "entity:bad",
        "owned_by",
        confidence=0.7,
        data_source="public_html_ownership",
        evidence="Legacy ownership claim",
        artifact_ref="https://bad.example/ownership",
        evidence_url="https://bad.example/ownership",
        evidence_title="Legacy ownership page",
        vendor_id="case-alpha",
    )

    kg.clear_vendor_graph_state("case-alpha")

    with kg.get_kg_conn() as conn:
        claim_count = conn.execute("SELECT COUNT(*) FROM kg_claims").fetchone()[0]
        rel_count = conn.execute("SELECT COUNT(*) FROM kg_relationships").fetchone()[0]
        vendor_link_count = conn.execute("SELECT COUNT(*) FROM kg_entity_vendors WHERE vendor_id = 'case-alpha'").fetchone()[0]

    assert claim_count == 0
    assert rel_count == 0
    assert vendor_link_count == 0


def test_backfill_legacy_relationship_claims_scopes_existing_edges_to_vendor(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path))
    kg = _reload_kg()
    kg.init_kg_db()

    kg.save_entity(_entity("entity:vendor", "Legacy Vendor"))
    kg.save_entity(_entity("entity:agency", "Department of Defense", entity_type="government_agency"))
    kg.link_entity_to_vendor("entity:vendor", "case-legacy")

    with kg.get_kg_conn() as conn:
        conn.execute(
            """
            INSERT INTO kg_relationships (
                source_entity_id,
                target_entity_id,
                rel_type,
                confidence,
                data_source,
                evidence
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "entity:vendor",
                "entity:agency",
                "contracts_with",
                0.88,
                "usaspending",
                "Legacy contract evidence",
            ),
        )

    stats = kg.backfill_legacy_relationship_claims()

    assert stats["legacy_relationships_scanned"] == 1
    assert stats["relationships_backfilled"] == 1
    assert stats["claims_backfilled"] == 1
    assert stats["evidence_backfilled"] == 1
    assert stats["relationships_without_vendor_scope"] == 0

    network = kg.get_entity_network("entity:vendor", depth=1)
    relationship = network["relationships"][0]
    assert len(relationship["claim_records"]) == 1
    assert relationship["claim_records"][0]["vendor_id"] == "case-legacy"
    assert relationship["claim_records"][0]["structured_fields"]["backfilled_legacy_claim"] is True
    assert relationship["claim_records"][0]["evidence_records"][0]["artifact_ref"].startswith("kg-relationship://")


def test_graph_intelligence_summary_tracks_edge_families_and_uncertainty():
    graph_ingest = _reload_graph_ingest()

    summary = graph_ingest.build_graph_intelligence_summary(
        {
            "entity_count": 4,
            "relationship_count": 3,
            "relationships": [
                {
                    "source_entity_id": "entity:vendor",
                    "target_entity_id": "entity:owner",
                    "rel_type": "beneficially_owned_by",
                    "confidence": 0.93,
                    "corroboration_count": 2,
                    "last_seen_at": "2026-03-28T12:00:00Z",
                    "claim_records": [
                        {
                            "contradiction_state": "unreviewed",
                            "structured_fields": {"authority_level": "official_registry"},
                            "evidence_records": [
                                {
                                    "authority_level": "official_registry",
                                    "url": "https://example.test/ownership",
                                }
                            ],
                        }
                    ],
                },
                {
                    "source_entity_id": "entity:vendor",
                    "target_entity_id": "bank:1",
                    "rel_type": "routes_payment_through",
                    "confidence": 0.61,
                    "corroboration_count": 1,
                    "last_seen_at": "2024-01-01T12:00:00Z",
                    "legacy_unscoped": True,
                    "claim_records": [
                        {
                            "contradiction_state": "contradicted",
                            "evidence_records": [
                                {
                                    "authority_level": "third_party_public",
                                    "url": "https://example.test/route",
                                }
                            ],
                        }
                    ],
                },
                {
                    "source_entity_id": "entity:vendor",
                    "target_entity_id": "msp:1",
                    "rel_type": "depends_on_service",
                    "confidence": 0.58,
                    "corroboration_count": 1,
                    "last_seen_at": "2026-03-20T12:00:00Z",
                    "claim_records": [],
                },
            ],
        },
        workflow_lane="supplier_cyber_trust",
    )

    assert summary["thin_graph"] is False
    assert summary["edge_family_counts"]["ownership_control"] == 1
    assert summary["edge_family_counts"]["cyber_supply_chain"] == 1
    assert summary["edge_family_counts"]["trade_and_logistics"] == 1
    assert summary["required_edge_families"] == ["ownership_control", "cyber_supply_chain"]
    assert summary["missing_required_edge_families"] == []
    assert summary["official_or_modeled_edge_count"] == 1
    assert summary["third_party_public_only_edge_count"] == 1
    assert summary["legacy_unscoped_edge_count"] == 1
    assert summary["contradicted_edge_count"] == 1
    assert summary["stale_edge_count"] >= 1
    assert summary["claim_coverage_pct"] == 0.6667
    assert summary["evidence_coverage_pct"] == 0.6667


def test_graph_intelligence_summary_accepts_external_ownership_coverage():
    graph_ingest = _reload_graph_ingest()

    summary = graph_ingest.build_graph_intelligence_summary(
        {
            "entity_count": 1,
            "relationship_count": 0,
            "relationships": [],
        },
        workflow_lane="defense_counterparty_trust",
        satisfied_required_edge_families=["ownership_control"],
    )

    assert summary["required_edge_families"] == ["ownership_control"]
    assert summary["present_required_edge_families"] == ["ownership_control"]
    assert summary["externally_satisfied_edge_families"] == ["ownership_control"]
    assert summary["missing_required_edge_families"] == []


def test_ingest_enrichment_to_graph_models_case_input_relationships(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path))
    kg = _reload_kg()
    graph_ingest = _reload_graph_ingest()
    kg.init_kg_db()

    stats = graph_ingest.ingest_enrichment_to_graph(
        "case-modeled",
        "Vector Mission Software",
        {
            "vendor_name": "Vector Mission Software",
            "country": "US",
            "identifiers": {},
            "findings": [],
            "relationships": [],
            "connector_status": {},
        },
        vendor_input={
            "name": "Vector Mission Software",
            "country": "US",
            "profile": "supplier_cyber_trust",
            "ownership": {
                "shell_layers": 2,
                "pep_connection": True,
                "parent_chain": ["Vector Mission Holdings"],
                "financing_entities": ["North Harbor Capital"],
                "payment_banks": ["Atlantic Settlement Bank"],
            },
            "seed_metadata": {
                "product_terms": [
                    "mission firmware",
                    "remote update service",
                    "telemetry gateway",
                ],
                "network_providers": ["Orbital Mesh Telecom"],
                "service_providers": ["Harbor Patch Signing Service"],
                "facilities": ["Vector Mission West Integration Lab"],
                "component_suppliers": [
                    {"supplier": "Beacon Firmware Works", "component": "secure boot module"},
                ],
            },
            "export_authorization": {
                "destination_country": "AE",
                "destination_company": "Desert Trade Hub",
                "end_use_summary": "Regional distributor support with onward delivery not yet resolved",
                "transit_countries": ["NL", "AE"],
            },
        },
    )

    assert stats["relationships_created"] >= 12

    summary = graph_ingest.get_vendor_graph_summary("case-modeled", depth=2)
    relationship_types = {rel["rel_type"] for rel in summary["relationships"]}

    assert {
        "owned_by",
        "led_by",
        "backed_by",
        "routes_payment_through",
        "supplies_component",
        "depends_on_service",
        "depends_on_network",
        "distributed_by",
        "ships_via",
        "operates_facility",
        "integrated_into",
    }.issubset(relationship_types)
