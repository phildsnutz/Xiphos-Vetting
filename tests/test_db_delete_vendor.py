import importlib
import sqlite3
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_delete_vendor_removes_dependent_rows_and_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "kg-test.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    for module_name in ["runtime_paths", "db", "artifact_vault", "ai_analysis", "knowledge_graph"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import db  # type: ignore
    import ai_analysis  # type: ignore
    import artifact_vault  # type: ignore
    import knowledge_graph as kg  # type: ignore

    db.init_db()
    ai_analysis.init_ai_tables()
    kg.init_kg_db()

    vendor_id = "case-delete-1"
    db.upsert_vendor(
        vendor_id=vendor_id,
        name="Delete Vendor",
        country="US",
        program="dod_unclassified",
        vendor_input={"name": "Delete Vendor", "country": "US", "program": "dod_unclassified"},
        profile="defense_acquisition",
    )
    db.save_score(
        vendor_id,
        {
            "composite_score": 12,
            "is_hard_stop": False,
            "calibrated": {
                "calibrated_probability": 0.12,
                "calibrated_tier": "TIER_4_CLEAR",
                "interval": {"lower": 0.08, "upper": 0.16, "coverage": 0.95},
            },
        },
    )
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO intel_summaries (case_id, created_by, report_hash, prompt_version, provider, model, summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (vendor_id, "tester", "hash-1", "prompt-v1", "openai", "gpt-4o", '{"items": []}'),
        )
        conn.execute(
            "INSERT INTO intel_summary_jobs (id, case_id, created_by, report_hash, status) VALUES (?, ?, ?, ?, ?)",
            ("job-1", vendor_id, "tester", "hash-1", "completed"),
        )
        conn.execute(
            "INSERT INTO case_events (case_id, report_hash, finding_id, event_type, subject, status) VALUES (?, ?, ?, ?, ?, ?)",
            (vendor_id, "hash-1", "finding-1", "review", "Delete Vendor", "active"),
        )

    artifact_vault.store_artifact(
        vendor_id,
        "foci_ownership_chart",
        "ownership-chart.txt",
        b"Ownership chart",
        source_system="foci_artifact_upload",
        uploaded_by="tester",
    )
    ai_analysis.save_analysis(
        vendor_id,
        provider="openai",
        model="gpt-4o",
        analysis={"executive_summary": "delete me"},
        created_by="tester",
        input_hash="hash-1",
    )
    with sqlite3.connect(db.get_db_path()) as conn:
        conn.execute(
            "INSERT INTO ai_analysis_jobs (id, case_id, created_by, input_hash, status) VALUES (?, ?, ?, ?, ?)",
            ("ai-job-1", vendor_id, "tester", "hash-1", "completed"),
        )
        conn.commit()

    entity_id = "entity-delete-1"
    with sqlite3.connect(kg.get_kg_db_path()) as conn:
        conn.execute(
            "INSERT INTO kg_entities (id, canonical_name, entity_type, last_updated) VALUES (?, ?, ?, datetime('now'))",
            (entity_id, "Delete Vendor Entity", "organization"),
        )
        conn.execute(
            "INSERT INTO kg_entity_vendors (entity_id, vendor_id) VALUES (?, ?)",
            (entity_id, vendor_id),
        )
        conn.commit()

    dossier_dir = BACKEND_DIR / "dossiers"
    dossier_dir.mkdir(parents=True, exist_ok=True)
    dossier_path = dossier_dir / f"dossier-{vendor_id}-test.html"
    dossier_path.write_text("<html>delete me</html>", encoding="utf-8")

    assert db.delete_vendor(vendor_id) is True

    assert db.get_vendor(vendor_id) is None
    assert not (tmp_path / "secure-artifacts" / vendor_id).exists()
    assert not dossier_path.exists()

    with sqlite3.connect(db.get_db_path()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM artifact_records WHERE case_id = ?", (vendor_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM intel_summaries WHERE case_id = ?", (vendor_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM intel_summary_jobs WHERE case_id = ?", (vendor_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM case_events WHERE case_id = ?", (vendor_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ai_analyses WHERE vendor_id = ?", (vendor_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ai_analysis_jobs WHERE case_id = ?", (vendor_id,)).fetchone()[0] == 0

    with sqlite3.connect(kg.get_kg_db_path()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM kg_entity_vendors WHERE vendor_id = ?", (vendor_id,)).fetchone()[0] == 0


def test_save_analysis_returns_inserted_row_id_with_sqlite_row(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    for module_name in ["runtime_paths", "db", "ai_analysis"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import db  # type: ignore
    import ai_analysis  # type: ignore

    db.init_db()
    ai_analysis.init_ai_tables()

    analysis_id = ai_analysis.save_analysis(
        "case-ai-row",
        provider="local_fallback",
        model="local-fallback-v1",
        analysis={"executive_summary": "persisted"},
        created_by="tester",
        input_hash="hash-ai-row",
    )

    assert isinstance(analysis_id, int)
    assert analysis_id > 0
