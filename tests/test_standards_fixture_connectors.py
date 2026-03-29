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


def _reload_modules():
    for module_name in ["knowledge_graph", "graph_ingest"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
        else:
            __import__(module_name)
    return sys.modules["knowledge_graph"], sys.modules["graph_ingest"]


def test_ownership_fixture_returns_control_path_relationships():
    from osint.gleif_bods_ownership_fixture import enrich

    result = enrich("Horizon Mission Systems LLC", "US")
    rel_types = {rel["type"] for rel in result.relationships}

    assert result.has_data
    assert {"owned_by", "beneficially_owned_by", "routes_payment_through", "distributed_by"}.issubset(rel_types)


def test_openownership_bods_fixture_returns_beneficial_ownership_relationships():
    from osint.openownership_bods_fixture import enrich

    result = enrich("North Sea Mission Analytics Ltd", "GB")
    rel_types = {rel["type"] for rel in result.relationships}

    assert result.has_data
    assert {"owned_by", "beneficially_owned_by"}.issubset(rel_types)
    assert result.identifiers["uk_company_number"] == "09876543"


def test_cyber_fixture_returns_cross_pillar_relationships():
    from osint.cyclonedx_spdx_vex_fixture import enrich

    result = enrich("Horizon Mission Systems LLC", "US")
    rel_types = {rel["type"] for rel in result.relationships}

    assert result.has_data
    assert {
        "supplies_component",
        "supplies_component_to",
        "integrated_into",
        "depends_on_network",
        "depends_on_service",
        "operates_facility",
        "ships_via",
        "has_vulnerability",
    }.issubset(rel_types)


def test_standards_fixtures_ingest_new_node_families_into_graph(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path))

    kg, graph_ingest = _reload_modules()
    kg.init_kg_db()

    from osint import enrichment as enrichment_mod
    from osint.gleif_bods_ownership_fixture import enrich as ownership_enrich
    from osint.cyclonedx_spdx_vex_fixture import enrich as cyber_enrich

    report = enrichment_mod._build_report(
        "Horizon Mission Systems LLC",
        "US",
        [ownership_enrich("Horizon Mission Systems LLC", "US"), cyber_enrich("Horizon Mission Systems LLC", "US")],
        time.time(),
    )

    stats = graph_ingest.ingest_enrichment_to_graph("case-standards", "Horizon Mission Systems LLC", report)
    assert stats["relationships_created"] >= 6

    with kg.get_kg_conn() as conn:
        entity_types = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT entity_type FROM kg_entities"
            ).fetchall()
        }
        relationship_types = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT rel_type FROM kg_relationships"
            ).fetchall()
        }

    assert {"holding_company", "bank", "distributor", "component", "subsystem", "telecom_provider", "service", "facility", "shipment_route"}.issubset(entity_types)
    assert {"owned_by", "beneficially_owned_by", "routes_payment_through", "distributed_by", "depends_on_network", "depends_on_service", "operates_facility", "ships_via", "has_vulnerability"}.issubset(relationship_types)
