import importlib
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
SCRIPTS_DIR = ROOT_DIR / "scripts"
for path in (str(BACKEND_DIR), str(SCRIPTS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def test_demo_packet_builds_amentum_artifacts(tmp_path, monkeypatch):
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
        "mission_thread_briefing",
        "seed_mission_thread_fixture",
        "run_mission_thread_demo_packet",
    ):
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
        else:
            importlib.import_module(module_name)

    import db
    import knowledge_graph as kg
    import run_mission_thread_demo_packet

    db.init_db()
    kg.init_kg_db()

    packet = run_mission_thread_demo_packet.build_demo_packet(
        fixture_id="amentum_honolulu_contested_logistics",
        output_root=tmp_path / "reports",
    )

    assert packet["thread_id"] == "mt-fixture-amentum-honolulu"
    assert packet["walkthrough_steps"]

    artifacts = packet["artifacts"]
    summary_md = Path(artifacts["summary_md"])
    briefing_md = Path(artifacts["briefing_md"])
    summary_json = Path(artifacts["summary_json"])

    assert summary_md.exists()
    assert briefing_md.exists()
    assert summary_json.exists()

    summary_text = summary_md.read_text(encoding="utf-8")
    assert "Walkthrough" in summary_text
    assert "Top Brittle Members" in summary_text
    assert "Amentum Honolulu contested logistics thread" in summary_text
