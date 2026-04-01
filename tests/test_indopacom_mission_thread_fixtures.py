import importlib
import os
import sys

import pytest


ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
for path in (BACKEND_DIR, SCRIPTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


FIXTURE_PATH = os.path.join(
    ROOT_DIR,
    "fixtures",
    "mission_threads",
    "indopacom_contested_logistics_threads_v1.json",
)


def _reload_modules() -> None:
    for module_name in (
        "db",
        "knowledge_graph",
        "mission_threads",
        "graph_ingest",
        "graph_analytics",
        "resilience_scoring",
        "supplier_passport",
        "mission_thread_briefing",
        "seed_mission_thread_fixture",
    ):
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
        else:
            importlib.import_module(module_name)


def test_indopacom_fixture_headers_expose_three_theater_specific_scenarios():
    import seed_mission_thread_fixture

    headers = seed_mission_thread_fixture.list_fixture_headers(FIXTURE_PATH)
    assert [header["id"] for header in headers] == [
        "first_island_chain_ace_refuel_c2",
        "littoral_jpots_fuel_offload_mesh",
        "regional_mro_reciprocal_maintenance_gap",
    ]


@pytest.mark.parametrize(
    ("fixture_id", "expected_rel_types"),
    [
        (
            "first_island_chain_ace_refuel_c2",
            {"supports_site", "single_point_of_failure_for", "substitutable_with", "depends_on_network"},
        ),
        (
            "littoral_jpots_fuel_offload_mesh",
            {"distributed_by", "ships_via", "routes_payment_through", "single_point_of_failure_for"},
        ),
        (
            "regional_mro_reciprocal_maintenance_gap",
            {"maintains_system_for", "substitutable_with", "depends_on_service", "single_point_of_failure_for"},
        ),
    ],
)
def test_indopacom_fixtures_seed_brittle_mission_threads(tmp_path, monkeypatch, fixture_id, expected_rel_types):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    _reload_modules()

    import db
    import knowledge_graph as kg
    import mission_thread_briefing
    import seed_mission_thread_fixture

    db.init_db()
    kg.init_kg_db()

    result = seed_mission_thread_fixture.seed_fixture_by_id(
        fixture_id,
        fixture_path=FIXTURE_PATH,
        depth=2,
    )

    summary = result["summary"]
    graph = result["graph"]
    relationship_distribution = graph["relationship_type_distribution"]

    assert summary["member_count"] >= 4
    assert graph["entity_count"] >= 6
    assert graph["relationship_count"] >= len(expected_rel_types)
    for rel_type in expected_rel_types:
        assert relationship_distribution.get(rel_type, 0) >= 1

    briefing = mission_thread_briefing.build_mission_thread_briefing(
        result["thread_id"],
        depth=2,
        member_passport_mode="control",
    )
    assert briefing is not None
    assert briefing["top_brittle_members"]
    assert briefing["top_control_path_exposures"]
    assert briefing["recommended_mitigations"]

    exposure_rel_types = {row["rel_type"] for row in briefing["top_control_path_exposures"]}
    assert exposure_rel_types & expected_rel_types
