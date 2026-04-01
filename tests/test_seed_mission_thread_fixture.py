import importlib
import os
import sys


ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
for path in (BACKEND_DIR, SCRIPTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


def test_seed_amentum_fixture_builds_thread_graph_and_passport(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    for module_name in (
        "db",
        "knowledge_graph",
        "mission_threads",
        "graph_ingest",
        "graph_analytics",
        "resilience_scoring",
        "supplier_passport",
        "seed_mission_thread_fixture",
    ):
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
        else:
            importlib.import_module(module_name)

    import db
    import knowledge_graph as kg
    import mission_threads
    import seed_mission_thread_fixture

    db.init_db()
    kg.init_kg_db()

    result = seed_mission_thread_fixture.seed_fixture_by_id("amentum_honolulu_contested_logistics", depth=2)

    assert result["thread_id"] == "mt-fixture-amentum-honolulu"
    assert len(result["seeded_vendor_ids"]) == 3
    assert "entity:distributed-sustainment-orchestrator" in result["seeded_entity_ids"]
    assert result["relationship_seed_count"] == 6

    summary = result["summary"]
    assert summary["member_count"] == 4
    assert summary["vendor_member_count"] == 3
    assert summary["graph"]["entity_count"] >= 6
    assert summary["graph"]["relationship_count"] >= 6
    assert summary["graph"]["relationship_type_distribution"]["supports_site"] == 1
    assert summary["graph"]["relationship_type_distribution"]["single_point_of_failure_for"] == 1
    assert summary["graph"]["relationship_type_distribution"]["substitutable_with"] == 1
    assert summary["resilience"]["summary"]["top_brittle_members"]

    graph = mission_threads.build_mission_thread_graph("mt-fixture-amentum-honolulu", depth=2, include_provenance=False)
    assert graph is not None
    assert graph["resilience_summary"]["model_version"] == "mission-thread-resilience-v1"
    assert graph["analytics"]["top_nodes_by_mission_importance"]

    passports = [
        mission_threads.build_mission_thread_member_passport("mt-fixture-amentum-honolulu", member_id, depth=2)
        for member_id in result["seeded_member_ids"]
    ]
    vendor_passports = [passport for passport in passports if passport and passport.get("supplier_passport")]
    assert vendor_passports
    primary = vendor_passports[0]
    assert primary["mission_context"]["focus_node_ids"]
    assert primary["supplier_passport"]["graph"]["mission_context"]["mission_thread_id"] == "mt-fixture-amentum-honolulu"
    assert primary["supplier_passport"]["graph"]["top_nodes_by_mission_importance"]
