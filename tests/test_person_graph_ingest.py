import importlib
import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def graph_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    for module_name in [
        "runtime_paths",
        "person_screening",
        "entity_resolution",
        "knowledge_graph",
        "person_graph_ingest",
        "graph_ingest",
    ]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import knowledge_graph as kg  # type: ignore

    kg.init_kg_db()
    return kg


def _screening_payload(case_id: str | None = "case-person-123") -> dict:
    return {
        "person_name": "Jane Doe",
        "nationalities": ["GB"],
        "employer": "Acme Systems",
        "screening_status": "CLEAR",
        "matched_lists": [],
        "deemed_export": None,
        "composite_score": 0.12,
        "id": "screening-123",
        "case_id": case_id,
    }


def test_person_screening_links_case_bucket_entities(graph_env):
    import graph_ingest  # type: ignore
    import person_graph_ingest as pgi  # type: ignore

    case_id = "case-person-123"
    result = pgi.ingest_person_screening(_screening_payload(case_id), case_id=case_id)

    assert result["entities_created"] >= 3
    assert result["relationships_created"] >= 3

    person_id = pgi._generate_person_entity_id("Jane Doe", ["GB"])
    employer_id = pgi._generate_employer_entity_id("Acme Systems")
    country_id = pgi._generate_country_entity_id("GB")

    linked_ids = {entity.id for entity in graph_env.get_vendor_entities(case_id)}
    assert {person_id, employer_id, country_id}.issubset(linked_ids)

    with graph_env.get_kg_conn() as conn:
        vendor_link_count = conn.execute(
            "SELECT COUNT(*) FROM kg_entity_vendors WHERE vendor_id = ?",
            (case_id,),
        ).fetchone()[0]
    assert vendor_link_count >= 3

    summary = graph_ingest.get_vendor_graph_summary(case_id, depth=1)
    summary_ids = {entity["id"] for entity in summary["entities"]}
    assert {person_id, employer_id, country_id, f"case:{case_id}"}.issubset(summary_ids)
    assert summary["entity_count"] >= 4
    assert summary["relationship_count"] >= 3


def test_person_screening_without_case_id_does_not_link_vendor_bucket(graph_env):
    import person_graph_ingest as pgi  # type: ignore

    result = pgi.ingest_person_screening(_screening_payload(case_id=None), case_id=None)
    assert result["entities_created"] >= 2

    with graph_env.get_kg_conn() as conn:
        vendor_link_count = conn.execute(
            "SELECT COUNT(*) FROM kg_entity_vendors WHERE vendor_id = ?",
            ("case-person-123",),
        ).fetchone()[0]
    assert vendor_link_count == 0


def test_ingest_persons_for_case_replays_saved_screenings(graph_env):
    import person_graph_ingest as pgi  # type: ignore
    import person_screening as ps  # type: ignore

    case_id = "case-person-replay"
    ps.init_person_screening_db()
    ps.screen_person(
        name="Alex Doe",
        nationalities=["CN"],
        employer="Northwind Labs",
        item_classification="USML-Aircraft",
        case_id=case_id,
        screened_by="test-suite",
    )

    result = pgi.ingest_persons_for_case(case_id)

    assert result["case_id"] == case_id
    assert result["persons_ingested"] == 1
    assert result["entities_created"] >= 3
    assert result["relationships_created"] >= 3
    assert result["details"][0]["person_name"] == "Alex Doe"

    linked_ids = {entity.id for entity in graph_env.get_vendor_entities(case_id)}
    assert pgi._generate_person_entity_id("Alex Doe", ["CN"]) in linked_ids
