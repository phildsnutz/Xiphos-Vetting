import importlib
import os
import sqlite3
import sys
import time

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    for module_name in ["knowledge_graph", "graph_ingest", "monitor_scheduler", "monitor", "server"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    if "server" not in sys.modules:
        import server  # type: ignore

    server = sys.modules["server"]
    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    return server


@pytest.fixture
def client(app_env):
    with app_env.app.test_client() as test_client:
        yield test_client


def _create_case(client, name="Prime Vendor", country="US"):
    resp = client.post(
        "/api/cases",
        json={
            "name": name,
            "country": country,
            "ownership": {"beneficial_owner_known": True},
            "data_quality": {"has_cage": True, "has_duns": True},
            "exec": {"known_execs": 2},
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
        },
    )
    assert resp.status_code == 201
    return resp.get_json()["case_id"]


def test_build_report_preserves_raw_data_for_graph_ingest(app_env):
    from osint import EnrichmentResult, Finding
    from osint import enrichment as enrichment_mod
    import graph_ingest

    result = EnrichmentResult(
        source="usaspending",
        vendor_name="Prime Vendor",
        findings=[
            Finding(
                source="usaspending",
                category="supply_chain",
                title="Supply Chain Concentration",
                detail="Top subcontractors present",
                severity="medium",
                confidence=0.9,
                raw_data={
                    "top_subcontractors": [
                        {"name": "Sub Vendor LLC", "amount": 1250000, "count": 3},
                    ],
                },
            )
        ],
        relationships=[
            {
                "type": "subcontractor_of",
                "source_entity": "Prime Vendor",
                "target_entity": "Sub Vendor LLC",
                "data_source": "usaspending_subawards",
                "amount": 1250000,
                "count": 3,
            }
        ],
        elapsed_ms=10,
    )

    report = enrichment_mod._build_report("Prime Vendor", "US", [result], time.time())

    assert report["findings"][0]["raw_data"]["top_subcontractors"][0]["name"] == "Sub Vendor LLC"
    assert report["relationships"][0]["target_entity"] == "Sub Vendor LLC"

    stats = graph_ingest.ingest_enrichment_to_graph("case-graph-1", "Prime Vendor", report)
    assert stats["relationships_created"] >= 1


def test_enrich_route_ingests_graph_for_plain_enrichment(client, app_env, monkeypatch):
    case_id = _create_case(client, name="Prime Vendor")

    def fake_enrich(**_kwargs):
        return {
            "vendor_name": "Prime Vendor",
            "country": "US",
            "overall_risk": "MEDIUM",
            "summary": {"findings_total": 1, "critical": 0, "high": 0, "medium": 1, "connectors_run": 1, "connectors_with_data": 1, "errors": 0},
            "identifiers": {},
            "findings": [
                {
                    "source": "usaspending",
                    "category": "supply_chain",
                    "title": "Supply Chain Concentration",
                    "detail": "Top subcontractors present",
                    "severity": "medium",
                    "confidence": 0.9,
                    "raw_data": {
                        "top_subcontractors": [
                            {"name": "Sub Vendor LLC", "amount": 1250000, "count": 3},
                        ],
                    },
                }
            ],
            "relationships": [
                {
                    "type": "subcontractor_of",
                    "source_entity": "Prime Vendor",
                    "target_entity": "Sub Vendor LLC",
                    "data_source": "usaspending_subawards",
                    "amount": 1250000,
                    "count": 3,
                }
            ],
            "risk_signals": [],
            "connector_status": {"usaspending": {"has_data": True, "findings_count": 1, "elapsed_ms": 5, "error": ""}},
            "errors": [],
        }

    monkeypatch.setattr(app_env, "enrich_vendor", fake_enrich)

    enrich_resp = client.post(f"/api/cases/{case_id}/enrich")
    assert enrich_resp.status_code == 200

    graph_resp = client.get(f"/api/cases/{case_id}/graph")
    assert graph_resp.status_code == 200
    graph = graph_resp.get_json()
    assert graph["relationship_count"] >= 1


def test_graph_ingest_preserves_prime_contractor_relationships(app_env):
    import graph_ingest

    report = {
        "vendor_name": "Prime Vendor",
        "country": "US",
        "identifiers": {},
        "findings": [],
        "relationships": [
            {
                "type": "prime_contractor_of",
                "source_entity": "MANTECH ADVANCED SYSTEMS INTERNATIONAL, INC.",
                "target_entity": "Prime Vendor",
                "data_source": "usaspending_subawards",
                "amount": 2250000,
                "count": 2,
            }
        ],
        "risk_signals": [],
    }

    stats = graph_ingest.ingest_enrichment_to_graph("case-prime-rel", "Prime Vendor", report)
    assert stats["relationships_created"] >= 1

    summary = graph_ingest.get_vendor_graph_summary("case-prime-rel", depth=1)
    rel_types = {rel["rel_type"] for rel in summary["relationships"]}
    assert "prime_contractor_of" in rel_types


def test_graph_ingest_preserves_subaward_source_provenance(app_env):
    import graph_ingest

    report = {
        "vendor_name": "Prime Vendor",
        "country": "US",
        "identifiers": {},
        "findings": [],
        "relationships": [
            {
                "type": "subcontractor_of",
                "source_entity": "Prime Vendor",
                "target_entity": "Mercury Systems, Inc.",
                "data_source": "sam_subaward_reporting",
                "amount": 750000,
                "count": 2,
            }
        ],
        "risk_signals": [],
    }

    stats = graph_ingest.ingest_enrichment_to_graph("case-sam-subaward-source", "Prime Vendor", report)
    assert stats["relationships_created"] >= 1

    summary = graph_ingest.get_vendor_graph_summary("case-sam-subaward-source", depth=1)
    sources = {rel["data_source"] for rel in summary["relationships"]}
    assert "sam_subaward_reporting" in sources


def test_graph_ingest_preserves_component_path_relationships_and_typed_nodes(app_env):
    import graph_ingest

    report = {
        "vendor_name": "Critical Widget Co",
        "country": "US",
        "identifiers": {},
        "findings": [],
        "relationships": [
            {
                "type": "supplies_component_to",
                "source_entity": "Critical Widget Co",
                "target_entity": "F-35 / Ejection Seat Control Module",
                "source_entity_type": "company",
                "target_entity_type": "subsystem",
                "data_source": "critical_subsystem_fixture",
                "confidence": 0.92,
                "evidence": "Supplier tied to subsystem control module",
            },
            {
                "type": "integrated_into",
                "source_entity": "Inertial Sensor Widget",
                "target_entity": "F-35 / Ejection Seat Control Module",
                "source_entity_type": "component",
                "target_entity_type": "subsystem",
                "data_source": "critical_subsystem_fixture",
                "confidence": 0.9,
                "evidence": "Component placement inside subsystem",
            },
            {
                "type": "owned_by",
                "source_entity": "Critical Widget Co",
                "target_entity": "Shenzhen Precision Holdings",
                "source_entity_type": "company",
                "target_entity_type": "holding_company",
                "data_source": "critical_subsystem_fixture",
                "confidence": 0.95,
                "evidence": "Ownership chain from fixture",
            },
            {
                "type": "beneficially_owned_by",
                "source_entity": "Shenzhen Precision Holdings",
                "target_entity": "PLA Strategic Systems Group",
                "source_entity_type": "holding_company",
                "target_entity_type": "company",
                "data_source": "critical_subsystem_fixture",
                "confidence": 0.95,
                "evidence": "Beneficial ownership chain from fixture",
            },
        ],
        "risk_signals": [],
    }

    stats = graph_ingest.ingest_enrichment_to_graph("case-component-path", "Critical Widget Co", report)
    assert stats["relationships_created"] >= 4

    summary = graph_ingest.get_vendor_graph_summary("case-component-path", depth=2)
    entity_types = {entity["entity_type"] for entity in summary["entities"]}
    relationship_types = {rel["rel_type"] for rel in summary["relationships"]}

    assert {"component", "subsystem", "holding_company", "company"}.issubset(entity_types)
    assert {
        "supplies_component_to",
        "integrated_into",
        "owned_by",
        "beneficially_owned_by",
    }.issubset(relationship_types)


def test_graph_ingest_preserves_backed_by_control_paths(app_env):
    import graph_ingest

    report = {
        "vendor_name": "Herrick Technology Laboratories",
        "country": "US",
        "identifiers": {},
        "findings": [],
        "relationships": [
            {
                "type": "backed_by",
                "source_entity": "Herrick Technology Laboratories",
                "target_entity": "Blue Delta",
                "source_entity_type": "company",
                "target_entity_type": "holding_company",
                "data_source": "google_news",
                "confidence": 0.62,
                "evidence": "Ron Sayco Joins Blue Delta-Backed Herrick Technology Laboratories as CFO - GovCon Wire",
                "structured_fields": {
                    "relationship_scope": "media_reported_financing",
                    "detection_method": "rss_title_backed_vendor",
                    "source_name": "GovCon Wire",
                },
            },
        ],
        "risk_signals": [],
    }

    stats = graph_ingest.ingest_enrichment_to_graph("case-backed-by-rel", "Herrick Technology Laboratories", report)
    assert stats["relationships_created"] >= 1

    summary = graph_ingest.get_vendor_graph_summary("case-backed-by-rel", depth=1)
    relationship_types = {rel["rel_type"] for rel in summary["relationships"]}
    assert "backed_by" in relationship_types


def test_graph_reingest_replaces_stale_vendor_owned_by_paths(app_env):
    import graph_ingest

    stale_report = {
        "vendor_name": "Columbia Helicopters, Inc.",
        "country": "US",
        "identifiers": {"lei": "549300DV5B5ZO815U462"},
        "findings": [],
        "relationships": [
            {
                "type": "owned_by",
                "source_entity": "Columbia Helicopters, Inc.",
                "target_entity": "Rippling",
                "source_entity_type": "company",
                "target_entity_type": "holding_company",
                "data_source": "public_html_ownership",
                "confidence": 0.7,
                "evidence": "Legacy ownership statement",
                "artifact_ref": "https://ats.rippling.com",
                "evidence_url": "https://ats.rippling.com",
                "evidence_title": "Legacy ownership page",
            },
        ],
        "risk_signals": [],
    }
    fresh_report = {
        "vendor_name": "Columbia Helicopters, Inc.",
        "country": "US",
        "identifiers": {"lei": "549300DV5B5ZO815U462"},
        "findings": [],
        "relationships": [
            {
                "type": "owned_by",
                "source_entity": "Columbia Helicopters, Inc.",
                "target_entity": "Bristow Group",
                "source_entity_type": "company",
                "target_entity_type": "holding_company",
                "data_source": "google_news",
                "confidence": 0.66,
                "evidence": "Bristow Group acquires Columbia Helicopters",
                "artifact_ref": "google-news://columbia/bristow-group",
                "evidence_url": "https://news.example/bristow-group",
                "evidence_title": "Ownership article",
            },
        ],
        "risk_signals": [],
    }

    graph_ingest.ingest_enrichment_to_graph("case-columbia", "Columbia Helicopters, Inc.", stale_report)
    stale_summary = graph_ingest.get_vendor_graph_summary("case-columbia", depth=1)
    stale_targets = {rel["target_entity_id"]: rel for rel in stale_summary["relationships"] if rel["rel_type"] == "owned_by"}
    assert any("Rippling" in rel["evidence_summary"] or "Rippling" in rel.get("target_entity_id", "") for rel in stale_summary["relationships"]) or len(stale_targets) == 1

    graph_ingest.ingest_enrichment_to_graph("case-columbia", "Columbia Helicopters, Inc.", fresh_report)
    fresh_summary = graph_ingest.get_vendor_graph_summary("case-columbia", depth=1)
    ownership_targets = {
        rel["target_entity_id"]
        for rel in fresh_summary["relationships"]
        if rel["rel_type"] == "owned_by"
    }
    entity_names = {entity["id"]: entity["canonical_name"] for entity in fresh_summary["entities"]}
    target_names = {entity_names[target_id] for target_id in ownership_targets}

    assert "Bristow Group" in target_names
    assert "Rippling" not in target_names


def test_graph_summary_excludes_stale_relationships_from_other_cases(app_env):
    import graph_ingest

    stale_report = {
        "vendor_name": "Yorktown Systems Group",
        "country": "US",
        "identifiers": {"uei": "L5LMQSN59YE5"},
        "findings": [],
        "relationships": [
            {
                "type": "owned_by",
                "source_entity": "Yorktown Systems Group",
                "target_entity": "Service-Disabled Veteran",
                "source_entity_type": "company",
                "target_entity_type": "holding_company",
                "data_source": "public_search_ownership",
                "confidence": 0.60,
                "evidence": "Yorktown Systems Group is owned by a Service-Disabled Veteran.",
                "artifact_ref": "https://www.ysginc.com/the-u-s-army-awards-offset-systems-group-829m-idiq-contract/",
                "evidence_url": "https://www.ysginc.com/the-u-s-army-awards-offset-systems-group-829m-idiq-contract/",
                "evidence_title": "Legacy ownership snippet",
            },
        ],
        "risk_signals": [],
    }
    fresh_report = {
        "vendor_name": "Yorktown Systems Group",
        "country": "US",
        "identifiers": {"uei": "L5LMQSN59YE5"},
        "findings": [],
        "relationships": [],
        "risk_signals": [],
    }

    graph_ingest.ingest_enrichment_to_graph("case-yorktown-stale", "Yorktown Systems Group", stale_report)
    graph_ingest.ingest_enrichment_to_graph("case-yorktown-fresh", "Yorktown Systems Group", fresh_report)

    fresh_summary = graph_ingest.get_vendor_graph_summary("case-yorktown-fresh", depth=1)
    light_summary = graph_ingest.get_vendor_graph_summary(
        "case-yorktown-fresh",
        depth=1,
        include_provenance=False,
        max_claim_records=0,
        max_evidence_records=0,
    )

    assert all(rel["rel_type"] != "owned_by" for rel in fresh_summary["relationships"])
    assert all(rel["rel_type"] != "owned_by" for rel in light_summary["relationships"])


def test_monitor_scheduler_uses_canonical_rescore_helpers(app_env, monkeypatch):
    import monitor_scheduler

    vendor_id = "monitor-case-1"
    app_env.db.upsert_vendor(
        vendor_id=vendor_id,
        name="Monitor Vendor",
        country="US",
        program="dod_unclassified",
        vendor_input={"name": "Monitor Vendor", "country": "US", "program": "dod_unclassified"},
        profile="defense_acquisition",
    )
    app_env.db.save_score(
        vendor_id,
        {
            "calibrated": {"calibrated_tier": "TIER_4_APPROVED", "calibrated_probability": 0.08},
            "composite_score": 8,
            "is_hard_stop": False,
        },
    )

    monkeypatch.setattr(
        monitor_scheduler,
        "enrich_vendor",
        lambda **_kwargs: {
            "vendor_name": "Monitor Vendor",
            "country": "US",
            "overall_risk": "HIGH",
            "summary": {"findings_total": 1, "critical": 0, "high": 1, "medium": 0, "connectors_run": 1, "connectors_with_data": 1, "errors": 0},
            "identifiers": {},
            "findings": [],
            "relationships": [],
            "risk_signals": [],
            "connector_status": {},
            "errors": [],
        },
    )
    monkeypatch.setattr(monitor_scheduler, "get_connector_list", lambda _profile: [])

    calls = {"persist": 0, "rescore": 0}

    def fake_persist(case_id, vendor, report):
        calls["persist"] += 1
        assert case_id == vendor_id
        assert vendor["name"] == "Monitor Vendor"
        assert report["overall_risk"] == "HIGH"
        return {"events": [], "graph": None}

    def fake_rescore(case_id, vendor, report):
        calls["rescore"] += 1
        return {
            "score_dict": {
                "calibrated": {"calibrated_tier": "TIER_2_ELEVATED", "calibrated_probability": 0.31},
                "composite_score": 31,
                "is_hard_stop": False,
            }
        }

    monkeypatch.setattr(app_env, "_persist_enrichment_artifacts", fake_persist)
    monkeypatch.setattr(app_env, "_canonical_rescore_from_enrichment", fake_rescore)

    scheduler = monitor_scheduler.MonitorScheduler(interval_hours=1)
    result = scheduler._check_vendor(app_env.db.get_vendor(vendor_id))

    assert calls == {"persist": 1, "rescore": 1}
    assert result["risk_changed"] is True
    assert result["old_tier"] == "TIER_4_APPROVED"
    assert result["new_tier"] == "TIER_2_ELEVATED"


def test_case_graph_route_honors_depth_query(client, app_env, monkeypatch):
    import graph_ingest

    case_id = _create_case(client, name="Graph Depth Vendor")
    calls = []

    def fake_summary(vendor_id: str, depth: int = 3):
        calls.append((vendor_id, depth))
        return {
            "vendor_id": vendor_id,
            "graph_depth": depth,
            "entity_count": 0,
            "relationship_count": 0,
            "entities": [],
            "relationships": [],
        }

    monkeypatch.setattr(graph_ingest, "get_vendor_graph_summary", fake_summary)

    resp = client.get(f"/api/cases/{case_id}/graph?depth=4")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["graph_depth"] == 4
    assert calls == [(case_id, 4)]


def test_monitor_scheduler_emits_kvk_registry_mutation_alert(app_env, monkeypatch):
    import monitor_scheduler

    vendor_id = "monitor-kvk-1"
    app_env.db.upsert_vendor(
        vendor_id=vendor_id,
        name="Oranje Mission Analytics B.V.",
        country="NL",
        program="dod_unclassified",
        vendor_input={"name": "Oranje Mission Analytics B.V.", "country": "NL", "program": "dod_unclassified"},
        profile="defense_acquisition",
    )
    app_env.db.save_score(
        vendor_id,
        {
            "calibrated": {"calibrated_tier": "TIER_4_APPROVED", "calibrated_probability": 0.08},
            "composite_score": 8,
            "is_hard_stop": False,
        },
    )

    monkeypatch.setattr(
        monitor_scheduler.db,
        "get_latest_enrichment",
        lambda _vendor_id: {
            "identifiers": {"kvk_number": "68456789"},
            "findings": [],
        },
    )
    monkeypatch.setattr(
        monitor_scheduler,
        "enrich_vendor",
        lambda **_kwargs: {
            "vendor_name": "Oranje Mission Analytics B.V.",
            "country": "NL",
            "overall_risk": "LOW",
            "summary": {"findings_total": 1, "critical": 0, "high": 0, "medium": 0, "connectors_run": 1, "connectors_with_data": 1, "errors": 0},
            "identifiers": {"kvk_number": "68456789"},
            "findings": [
                {
                    "source": "netherlands_kvk",
                    "category": "corporate_identity",
                    "title": "KVK mutation: bestuur gewijzigd",
                    "detail": "Mutation date: 2026-03-29\nType: officer_update",
                    "severity": "info",
                    "confidence": 0.84,
                    "raw_data": {"mutation": {"mutation_type": "officer_update"}},
                }
            ],
            "relationships": [],
            "risk_signals": [],
            "connector_status": {},
            "errors": [],
        },
    )
    monkeypatch.setattr(monitor_scheduler, "get_connector_list", lambda _profile: ["netherlands_kvk"])
    monkeypatch.setattr(app_env, "_persist_enrichment_artifacts", lambda *_args, **_kwargs: {"events": [], "graph": None})
    monkeypatch.setattr(
        app_env,
        "_canonical_rescore_from_enrichment",
        lambda *_args, **_kwargs: {
            "score_dict": {
                "calibrated": {"calibrated_tier": "TIER_4_APPROVED", "calibrated_probability": 0.08},
                "composite_score": 8,
                "is_hard_stop": False,
            }
        },
    )

    scheduler = monitor_scheduler.MonitorScheduler(interval_hours=1)
    result = scheduler._check_vendor(app_env.db.get_vendor(vendor_id))
    alerts = app_env.db.list_alerts(limit=10)

    assert result["risk_changed"] is False
    assert any(alert["title"] == "Registry Mutation Alert: Oranje Mission Analytics B.V." for alert in alerts)


def test_init_kg_db_dedupes_legacy_relationship_rows(app_env):
    import knowledge_graph

    kg_path = os.environ["XIPHOS_KG_DB_PATH"]
    conn = sqlite3.connect(kg_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS kg_entities (
                id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                aliases JSON NOT NULL DEFAULT '[]',
                identifiers JSON NOT NULL DEFAULT '{}',
                country TEXT,
                sources JSON NOT NULL DEFAULT '[]',
                confidence REAL NOT NULL DEFAULT 0.0,
                last_updated TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS kg_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_entity_id TEXT NOT NULL,
                target_entity_id TEXT NOT NULL,
                rel_type TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.7,
                data_source TEXT,
                evidence TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        conn.execute(
            "INSERT OR REPLACE INTO kg_entities (id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, last_updated) VALUES (?, ?, ?, '[]', '{}', '', '[]', 1.0, datetime('now'))",
            ("entity-a", "Entity A", "company"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO kg_entities (id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, last_updated) VALUES (?, ?, ?, '[]', '{}', '', '[]', 1.0, datetime('now'))",
            ("entity-b", "Entity B", "company"),
        )
        conn.execute(
            "INSERT INTO kg_relationships (source_entity_id, target_entity_id, rel_type, confidence, data_source, evidence) VALUES (?, ?, ?, ?, ?, ?)",
            ("entity-a", "entity-b", "related_entity", 0.8, None, None),
        )
        conn.execute(
            "INSERT INTO kg_relationships (source_entity_id, target_entity_id, rel_type, confidence, data_source, evidence) VALUES (?, ?, ?, ?, ?, ?)",
            ("entity-a", "entity-b", "related_entity", 0.8, "", ""),
        )
        conn.commit()
    finally:
        conn.close()

    knowledge_graph.init_kg_db()

    conn = sqlite3.connect(kg_path)
    try:
        rows = conn.execute(
            """
            SELECT COUNT(*) FROM kg_relationships
            WHERE source_entity_id = ? AND target_entity_id = ? AND rel_type = ?
            """,
            ("entity-a", "entity-b", "related_entity"),
        ).fetchone()[0]
        assert rows == 1
    finally:
        conn.close()


def test_vendor_graph_summary_hydrates_missing_relationship_endpoints(app_env):
    import knowledge_graph
    import graph_ingest

    knowledge_graph.init_kg_db()
    kg_path = os.environ["XIPHOS_KG_DB_PATH"]
    conn = sqlite3.connect(kg_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO kg_entities
                (id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, last_updated)
            VALUES (?, ?, ?, '[]', '{}', ?, '[]', ?, datetime('now'))
            """,
            ("entity-root", "Root Vendor", "company", "US", 0.98),
        )
        conn.execute(
            "INSERT OR IGNORE INTO kg_entity_vendors (entity_id, vendor_id) VALUES (?, ?)",
            ("entity-root", "vendor-graph-hydrate"),
        )
        conn.execute(
            """
            INSERT INTO kg_relationships
                (source_entity_id, target_entity_id, rel_type, confidence, data_source, evidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("entity-root", "cik:1535527", "filed_with", 0.7, "sec_edgar", "Legacy endpoint row"),
        )
        conn.commit()
    finally:
        conn.close()

    summary = graph_ingest.get_vendor_graph_summary("vendor-graph-hydrate", depth=1)

    entity_ids = {entity["id"] for entity in summary["entities"]}
    assert "entity-root" in entity_ids
    assert "cik:1535527" in entity_ids

    hydrated = next(entity for entity in summary["entities"] if entity["id"] == "cik:1535527")
    assert hydrated["canonical_name"] == "CIK 1535527"
    assert hydrated["entity_type"] == "company"
    assert hydrated["synthetic"] is True


def test_vendor_graph_summary_aggregates_corroborating_edge_sources(app_env):
    import knowledge_graph
    import graph_ingest

    knowledge_graph.init_kg_db()
    with knowledge_graph.get_kg_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO kg_entities
                (id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, last_updated)
            VALUES (?, ?, ?, '[]', '{}', ?, '[]', ?, datetime('now'))
            """,
            ("entity-root", "Root Vendor", "company", "US", 0.98),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO kg_entities
                (id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, last_updated)
            VALUES (?, ?, ?, '[]', '{}', ?, '[]', ?, datetime('now'))
            """,
            ("entity-target", "Target Vendor", "company", "US", 0.91),
        )
        conn.execute(
            "INSERT OR IGNORE INTO kg_entity_vendors (entity_id, vendor_id) VALUES (?, ?)",
            ("entity-root", "vendor-corroborated-edge"),
        )
        conn.execute(
            """
            INSERT INTO kg_relationships
                (source_entity_id, target_entity_id, rel_type, confidence, data_source, evidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "entity-root",
                "entity-target",
                "contracts_with",
                0.74,
                "usaspending",
                "Federal contract relationship ($2,400,000 total obligations)",
                "2026-03-20 10:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO kg_relationships
                (source_entity_id, target_entity_id, rel_type, confidence, data_source, evidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "entity-root",
                "entity-target",
                "contracts_with",
                0.86,
                "fpds_contracts",
                "Contract award corroborated in FPDS",
                "2026-03-22 14:30:00",
            ),
        )

    summary = graph_ingest.get_vendor_graph_summary("vendor-corroborated-edge", depth=1)
    relationships = [
        rel for rel in summary["relationships"]
        if rel["source_entity_id"] == "entity-root"
        and rel["target_entity_id"] == "entity-target"
        and rel["rel_type"] == "contracts_with"
    ]

    assert len(relationships) == 1
    relationship = relationships[0]
    assert relationship["confidence"] == 0.86
    assert relationship["corroboration_count"] == 2
    assert relationship["data_sources"] == ["usaspending", "fpds_contracts"]
    assert relationship["first_seen_at"] == "2026-03-20 10:00:00"
    assert relationship["last_seen_at"] == "2026-03-22 14:30:00"
    assert len(relationship["evidence_snippets"]) == 2
    assert relationship["evidence_summary"] == "2 award records via USAspending and FPDS Contracts; total $2.4M, largest $2.4M."


def test_vendor_graph_summary_normalizes_weak_entity_names(app_env):
    import knowledge_graph
    import graph_ingest

    knowledge_graph.init_kg_db()

    with knowledge_graph.get_kg_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO kg_entities
                (id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, last_updated)
            VALUES (?, ?, ?, '[]', '{}', ?, ?, ?, datetime('now'))
            """,
            ("entity:weak-sec-subsidiary", "Entity Name", "company", "Unknown", '["sec_edgar_ex21"]', 0.9),
        )
        conn.execute(
            "INSERT OR IGNORE INTO kg_entity_vendors (entity_id, vendor_id) VALUES (?, ?)",
            ("entity:weak-sec-subsidiary", "vendor-weak-name"),
        )

    summary = graph_ingest.get_vendor_graph_summary("vendor-weak-name", depth=1)
    entity = next(item for item in summary["entities"] if item["id"] == "entity:weak-sec-subsidiary")
    assert entity["canonical_name"] == "Unresolved SEC subsidiary"
    assert entity["country"] == ""


def test_sec_edgar_exhibit_21_parser_skips_placeholder_headers():
    from osint import sec_edgar

    text = """
    Exhibit 21
    Entity Name
    Jurisdiction
    Example Subsidiary LLC
    Delaware
    """

    subsidiaries = sec_edgar._parse_exhibit_21(text, "Example Parent Corp")
    assert subsidiaries == [{"name": "Example Subsidiary LLC", "jurisdiction": "Delaware"}]
