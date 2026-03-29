import importlib
import os
import sys
import time

import pytest


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    for module_name in ["knowledge_graph", "graph_ingest", "server"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    if "server" not in sys.modules:
        import server  # type: ignore

    server = sys.modules["server"]
    server.db.init_db()
    server.init_auth_db()
    return server


def test_dataset_is_fixture_backed_with_provenance():
    import international_exhibitors

    dataset = international_exhibitors.load_exhibitor_dataset()
    company = dataset["companies"][0]

    assert dataset["dataset_id"] == "world_defense_exhibitors_2026"
    assert dataset["source_type"] == "analyst_fixture"
    assert company["provenance"]["dataset_id"] == dataset["dataset_id"]
    assert company["record_id"].startswith("intl-exh-2026-")


def test_fixture_connector_returns_provenance_and_event_relationships():
    from osint.international_exhibitors_fixture import enrich

    result = enrich("AVIC", "CN")

    assert result.has_data
    assert result.findings[0].source == "international_exhibitors_fixture"
    assert result.findings[0].raw_data["dataset_id"] == "world_defense_exhibitors_2026"
    assert any(rel["entity_type"] == "trade_show_event" for rel in result.relationships)


def test_ingest_script_targets_fixture_connector_for_graph_seed():
    import ingest_international_exhibitors as ingest_script

    assert ingest_script.build_fixture_enrich_payload() == {
        "connectors": ["international_exhibitors_fixture"]
    }


def test_fixture_connector_ingests_trade_show_entities_into_graph(app_env):
    import graph_ingest
    from osint import enrichment as enrichment_mod
    from osint.international_exhibitors_fixture import enrich

    result = enrich("AVIC", "CN")
    report = enrichment_mod._build_report("AVIC", "CN", [result], time.time())

    stats = graph_ingest.ingest_enrichment_to_graph("case-avic-fixture", "AVIC", report)
    assert stats["relationships_created"] >= 1

    summary = graph_ingest.get_vendor_graph_summary("case-avic-fixture", depth=1)
    entity_types = {entity["entity_type"] for entity in summary["entities"]}
    data_sources = {relationship["data_source"] for relationship in summary["relationships"]}

    assert "trade_show_event" in entity_types
    assert "international_exhibitors_fixture" in data_sources
