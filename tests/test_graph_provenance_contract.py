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
