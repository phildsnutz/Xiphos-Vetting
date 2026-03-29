from __future__ import annotations

import importlib
import os
import sys

import pytest

from backend.osint import uk_companies_house


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
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
    if server.HAS_AI:
        server.init_ai_tables()
    return server


def test_uk_companies_house_emits_graph_native_relationships(monkeypatch):
    monkeypatch.setattr(uk_companies_house, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(uk_companies_house, "_search_company", lambda *_: [{
        "company_number": "12345678",
        "title": "Example Defence Ltd",
        "company_status": "active",
        "date_of_creation": "2019-01-01",
        "company_type": "ltd",
        "address_snippet": "London, United Kingdom",
    }])
    monkeypatch.setattr(uk_companies_house, "_get_company_profile", lambda *_: {"sic_codes": ["62012"]})
    monkeypatch.setattr(uk_companies_house, "_get_officers", lambda *_: [{
        "name": "Jane Director",
        "officer_role": "director",
        "appointed_on": "2020-03-01",
        "nationality": "British",
    }])
    monkeypatch.setattr(uk_companies_house, "_get_psc", lambda *_: [{
        "name": "Strategic Holdings LLP",
        "kind": "corporate-entity-person-with-significant-control",
        "natures_of_control": ["ownership-of-shares-75-to-100-percent"],
        "notified_on": "2021-02-10",
        "nationality": "",
        "country_of_residence": "United Kingdom",
    }])
    monkeypatch.setattr(uk_companies_house, "_get_psc_statements", lambda *_: [{
        "statement": "psc-exists-but-not-identified",
        "statement_type": "psc-exists-but-not-identified",
    }])
    monkeypatch.setattr(uk_companies_house, "_get_filing_history", lambda *_: [
        {
            "date": "2026-02-10",
            "category": "confirmation-statement",
            "description": "confirmation statement made on 2026-02-01",
        },
        {
            "date": "2025-12-12",
            "category": "accounts",
            "description": "accounts with accounts type total exemption full",
        },
    ])
    monkeypatch.setattr(uk_companies_house.time, "sleep", lambda *_: None)

    result = uk_companies_house.enrich("Example Defence", country="GB")

    rel_types = {rel["type"] for rel in result.relationships}
    assert rel_types == {"officer_of", "beneficially_owned_by"}

    officer_rel = next(rel for rel in result.relationships if rel["type"] == "officer_of")
    assert officer_rel["source_entity"] == "Jane Director"
    assert officer_rel["target_entity"] == "Example Defence Ltd"
    assert officer_rel["source_entity_type"] == "person"
    assert officer_rel["structured_fields"]["standards"] == ["UK Companies House Officers Register"]

    psc_rel = next(rel for rel in result.relationships if rel["type"] == "beneficially_owned_by")
    assert psc_rel["source_entity"] == "Example Defence Ltd"
    assert psc_rel["target_entity"] == "Strategic Holdings LLP"
    assert psc_rel["target_entity_type"] == "holding_company"
    assert psc_rel["structured_fields"]["standards"] == ["UK PSC Register"]
    assert any(finding.title == "PSC statements: 1 disclosure records" for finding in result.findings)
    assert any(finding.title == "Filing history: 2 recent Companies House records" for finding in result.findings)
    assert result.structured_fields["summary"]["psc_statement_count"] == 1
    assert result.structured_fields["summary"]["filing_count"] == 2


def test_graph_ingest_preserves_uk_registry_control_paths(app_env):
    import graph_ingest

    report = {
        "vendor_name": "Example Defence Ltd",
        "country": "GB",
        "identifiers": {"uk_company_number": "12345678"},
        "findings": [],
        "relationships": [
            {
                "type": "beneficially_owned_by",
                "source_entity": "Example Defence Ltd",
                "target_entity": "Strategic Holdings LLP",
                "source_entity_type": "company",
                "target_entity_type": "holding_company",
                "data_source": "uk_companies_house",
                "confidence": 0.93,
                "evidence": "UK Companies House PSC register lists Strategic Holdings LLP as a PSC.",
                "structured_fields": {
                    "company_number": "12345678",
                    "standards": ["UK PSC Register"],
                },
            },
            {
                "type": "officer_of",
                "source_entity": "Jane Director",
                "target_entity": "Example Defence Ltd",
                "source_entity_type": "person",
                "target_entity_type": "company",
                "data_source": "uk_companies_house",
                "confidence": 0.88,
                "evidence": "UK Companies House officers register lists Jane Director as a director.",
                "structured_fields": {
                    "role": "director",
                    "standards": ["UK Companies House Officers Register"],
                },
            },
        ],
        "risk_signals": [],
    }

    stats = graph_ingest.ingest_enrichment_to_graph("case-uk-registry", "Example Defence Ltd", report)
    assert stats["relationships_created"] >= 2

    summary = graph_ingest.get_vendor_graph_summary("case-uk-registry", depth=1)
    relationship_types = {rel["rel_type"] for rel in summary["relationships"]}
    entity_types = {entity["entity_type"] for entity in summary["entities"]}

    assert {"beneficially_owned_by", "officer_of"}.issubset(relationship_types)
    assert {"holding_company", "person", "company"}.issubset(entity_types)


def test_uk_companies_house_uses_seeded_company_number_without_search(monkeypatch):
    monkeypatch.setattr(uk_companies_house, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(uk_companies_house, "_search_company", lambda *_: (_ for _ in ()).throw(AssertionError("search should not run")))
    monkeypatch.setattr(
        uk_companies_house,
        "_get_company_profile",
        lambda company_number, _api_key: {
            "company_name": "Example Defence Ltd",
            "company_status": "active",
            "date_of_creation": "2019-01-01",
            "type": "ltd",
            "registered_office_address": {
                "address_line_1": "1 Defence Way",
                "locality": "London",
                "country": "United Kingdom",
                "postal_code": "SW1A 1AA",
            },
            "sic_codes": ["62012"],
        },
    )
    monkeypatch.setattr(uk_companies_house, "_get_officers", lambda *_: [])
    monkeypatch.setattr(uk_companies_house, "_get_psc", lambda *_: [])
    monkeypatch.setattr(uk_companies_house, "_get_psc_statements", lambda *_: [])
    monkeypatch.setattr(uk_companies_house, "_get_filing_history", lambda *_: [])
    monkeypatch.setattr(uk_companies_house.time, "sleep", lambda *_: None)

    result = uk_companies_house.enrich(
        "Ignored Vendor Name",
        country="GB",
        uk_company_number="12345678",
    )

    assert result.identifiers["uk_company_number"] == "12345678"
    assert any("Example Defence Ltd" in finding.title for finding in result.findings)
