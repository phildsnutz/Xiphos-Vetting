import importlib
import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def server_module(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-seed-memory.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        server = importlib.import_module("server")

    server.db.init_db()
    server.init_auth_db()
    yield server


def _create_case(server, case_id: str, name: str) -> str:
    server.db.upsert_vendor(
        case_id,
        name,
        "US",
        "dod_unclassified",
        {
            "ownership": {},
            "data_quality": {},
            "exec": {},
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
        },
        profile="defense_acquisition",
    )
    return case_id


def _save_enrichment(server, case_id: str, identifiers: dict, *, identifier_sources: dict | None = None, connector_status: dict | None = None):
    server.db.save_enrichment(
        case_id,
        {
            "overall_risk": "LOW",
            "summary": {"findings_total": 0, "critical": 0, "high": 0, "connectors_run": 1},
            "identifiers": identifiers,
            "identifier_sources": identifier_sources or {},
            "connector_status": connector_status or {},
            "findings": [],
            "total_elapsed_ms": 1,
        },
    )


def test_get_latest_peer_enrichment_matches_normalized_vendor_name(server_module):
    _create_case(server_module, "c-peer", "Berry Aviation, Inc.")
    _save_enrichment(
        server_module,
        "c-peer",
        {"cage": "0EA28", "uei": "V1HATBT1N7V5"},
        identifier_sources={"cage": ["public_search_ownership"], "uei": ["public_search_ownership"]},
        connector_status={"public_search_ownership": "ok"},
    )

    report = server_module.db.get_latest_peer_enrichment("Berry Aviation", exclude_vendor_id="c-current")

    assert report is not None
    assert report["identifiers"]["cage"] == "0EA28"
    assert report["identifiers"]["uei"] == "V1HATBT1N7V5"


def test_enrichment_seed_identifiers_uses_peer_case_memory_for_missing_ids(server_module):
    _create_case(server_module, "c-peer", "Columbia Helicopters, Inc.")
    _save_enrichment(
        server_module,
        "c-peer",
        {
            "website": "https://colheli.com",
            "cage": "7W206",
            "uei": "EBD3SM6LH8D3",
            "duns": "009673609",
        },
        identifier_sources={
            "website": ["public_html_ownership"],
            "cage": ["public_search_ownership"],
            "uei": ["public_search_ownership"],
            "duns": ["public_search_ownership"],
        },
        connector_status={"public_search_ownership": "ok", "public_html_ownership": "ok"},
    )

    _create_case(server_module, "c-current", "Columbia Helicopters")
    _save_enrichment(
        server_module,
        "c-current",
        {"website": "https://colheli.com"},
        identifier_sources={"website": ["public_html_ownership"]},
        connector_status={"public_html_ownership": "ok"},
    )

    seed = server_module._enrichment_seed_identifiers("c-current")

    assert seed["website"] == "https://colheli.com"
    assert seed["domain"] == "colheli.com"
    assert seed["cage"] == "7W206"
    assert seed["uei"] == "EBD3SM6LH8D3"
    assert seed["duns"] == "009673609"
    assert seed["__seed_identifier_sources"]["uei"] == ["public_search_ownership"]
    assert seed["__seed_connector_status"]["public_search_ownership"] == "ok"


def test_enrichment_seed_identifiers_does_not_overwrite_current_case_values(server_module):
    _create_case(server_module, "c-peer", "Example Systems, Inc.")
    _save_enrichment(
        server_module,
        "c-peer",
        {"website": "https://legacy.example.com", "cage": "OLD01"},
        identifier_sources={"website": ["public_html_ownership"], "cage": ["public_search_ownership"]},
        connector_status={"public_search_ownership": "ok"},
    )

    _create_case(server_module, "c-current", "Example Systems")
    _save_enrichment(
        server_module,
        "c-current",
        {"website": "https://example.com", "cage": "NEW99"},
        identifier_sources={"website": ["public_html_ownership"], "cage": ["sam_gov"]},
        connector_status={"sam_gov": "ok"},
    )

    seed = server_module._enrichment_seed_identifiers("c-current")

    assert seed["website"] == "https://example.com"
    assert seed["cage"] == "NEW99"
    assert seed["__seed_identifier_sources"]["cage"] == ["sam_gov"]
    assert seed["__seed_connector_status"]["sam_gov"] == "ok"


def test_enrichment_seed_identifiers_uses_case_seed_metadata_when_no_report_exists(server_module):
    server_module.db.upsert_vendor(
        "c-seeded",
        "Lion City Mission Systems Pte. Ltd.",
        "SG",
        "dod_unclassified",
        {
            "ownership": {},
            "data_quality": {},
            "exec": {},
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
            "seed_metadata": {
                "uen": "201912345N",
                "singapore_acra_url": "file:///tmp/acra.json",
            },
        },
        profile="defense_acquisition",
    )

    seed = server_module._enrichment_seed_identifiers("c-seeded")

    assert seed["uen"] == "201912345N"
    assert seed["singapore_acra_url"] == "file:///tmp/acra.json"


def test_enrichment_seed_identifiers_explicit_seed_metadata_overrides_peer_fixture_poison(server_module):
    _create_case(server_module, "c-peer", "FAUN Trackway")
    _save_enrichment(
        server_module,
        "c-peer",
        {"public_html_fixture_page": "file:///Users/tyegonzalez/Desktop/Helios-Package%20Merged/fixtures/public_html_ownership/faun_trackway_control.html"},
        identifier_sources={"public_html_fixture_page": ["public_html_ownership"]},
        connector_status={"public_html_ownership": "ok"},
    )

    server_module.db.upsert_vendor(
        "c-current",
        "FAUN Trackway",
        "DE",
        "dod_unclassified",
        {
            "ownership": {},
            "data_quality": {},
            "exec": {},
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
            "seed_metadata": {
                "public_html_fixture_page": "fixtures/public_html_ownership/faun_trackway_control.html",
                "public_html_fixture_only": True,
            },
        },
        profile="defense_acquisition",
    )

    seed = server_module._enrichment_seed_identifiers("c-current")

    assert seed["public_html_fixture_page"] == "fixtures/public_html_ownership/faun_trackway_control.html"
    assert "public_html_fixture_page" not in seed.get("__seed_identifier_sources", {})


def test_enrichment_seed_identifiers_explicit_seed_metadata_overrides_current_report_fixture_poison(server_module):
    server_module.db.upsert_vendor(
        "c-current",
        "Greensea IQ",
        "US",
        "dod_unclassified",
        {
            "ownership": {},
            "data_quality": {},
            "exec": {},
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
            "seed_metadata": {
                "public_html_fixture_page": "fixtures/public_html_ownership/greensea_iq_backer.html",
                "public_html_fixture_only": True,
            },
        },
        profile="defense_acquisition",
    )
    _save_enrichment(
        server_module,
        "c-current",
        {"public_html_fixture_page": "file:///Users/tyegonzalez/Desktop/Helios-Package%20Merged/fixtures/public_html_ownership/greensea_iq_backer.html"},
        identifier_sources={"public_html_fixture_page": ["public_html_ownership"]},
        connector_status={"public_html_ownership": "ok"},
    )

    seed = server_module._enrichment_seed_identifiers("c-current")

    assert seed["public_html_fixture_page"] == "fixtures/public_html_ownership/greensea_iq_backer.html"
    assert "public_html_fixture_page" not in seed.get("__seed_identifier_sources", {})
