import importlib
import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload_backend_modules():
    for module_name in [
        "db",
        "knowledge_graph",
        "seed_iteams_knowledge_graph",
        "teaming_intelligence",
    ]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])


def _seed_iteams_graph(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.delenv("XIPHOS_PG_URL", raising=False)
    monkeypatch.setenv("XIPHOS_DB_ENGINE", "sqlite")
    monkeypatch.setenv("HELIOS_DB_ENGINE", "sqlite")
    _reload_backend_modules()

    import knowledge_graph
    import seed_iteams_knowledge_graph

    knowledge_graph.init_kg_db()
    seed_iteams_knowledge_graph.seed_iteams_graph()


def test_build_teaming_intelligence_classifies_seeded_iteams_graph(tmp_path, monkeypatch):
    _seed_iteams_graph(tmp_path, monkeypatch)
    import teaming_intelligence

    report = teaming_intelligence.build_teaming_intelligence(
        vehicle_name="ITEAMS",
        observed_vendors=[
            {"vendor_name": "Amentum", "role": "prime", "award_amount": 250_000_000},
            {"vendor_name": "HII Mission Technologies", "role": "subcontractor"},
            {"vendor_name": "SMX", "role": "subcontractor"},
        ],
    )

    assert report["supported"] is True
    classes = {partner["entity_name"]: partner["classification"] for partner in report["assessed_partners"]}
    assert classes["Amentum Holdings, Inc."] == "incumbent-core"
    assert classes["Kupono Government Services"] == "locked"
    assert classes["SMX"] == "emerging"
    assert classes["HII Mission Technologies"] == "recruitable"
    assert any("incumbent-core" in conclusion or "incumbent core" in conclusion.lower() for conclusion in report["top_conclusions"])


def test_build_teaming_intelligence_returns_predicted_scenario_for_recruitable_partner(tmp_path, monkeypatch):
    _seed_iteams_graph(tmp_path, monkeypatch)
    import teaming_intelligence

    report = teaming_intelligence.build_teaming_intelligence(
        vehicle_name="ITEAMS",
        observed_vendors=[
            {"vendor_name": "Amentum", "role": "prime"},
            {"vendor_name": "HII Mission Technologies", "role": "subcontractor"},
        ],
        scenario={"recruit_partner": "HII Mission Technologies"},
    )

    assert report["scenario"]["state"] == "predicted"
    assert report["scenario"]["classification_basis"] == "recruitable"
    assert report["scenario"]["recommendation"] == "preferred_recruit"


def test_build_teaming_intelligence_supports_leia_when_graph_signal_exists(tmp_path, monkeypatch):
    _seed_iteams_graph(tmp_path, monkeypatch)
    import teaming_intelligence

    report = teaming_intelligence.build_teaming_intelligence(
        vehicle_name="LEIA",
        observed_vendors=[
            {"vendor_name": "SMX", "role": "prime"},
            {"vendor_name": "cBEYONData", "role": "subcontractor"},
            {"vendor_name": "HII Mission Technologies", "role": "challenger"},
        ],
    )

    assert report["supported"] is True
    classes = {partner["entity_name"]: partner["classification"] for partner in report["assessed_partners"]}
    assert classes["SMX"] == "incumbent-core"
    assert classes["cBEYONData"] == "locked"
    assert classes["HII Mission Technologies"] == "emerging"
    assert any("LEIA" in conclusion for conclusion in report["top_conclusions"])


def test_build_teaming_intelligence_returns_unsupported_for_unknown_vehicle(tmp_path, monkeypatch):
    _seed_iteams_graph(tmp_path, monkeypatch)
    import teaming_intelligence

    report = teaming_intelligence.build_teaming_intelligence(vehicle_name="NO_SUCH_VEHICLE")

    assert report["supported"] is False
    assert "NO_SUCH_VEHICLE" in report["message"]
    assert report["assessed_partners"] == []
