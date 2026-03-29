from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from osint import EnrichmentResult
from osint import enrichment


def test_enrich_vendor_preserves_seeded_identifiers_and_provenance_on_partial_rerun(monkeypatch):
    result = EnrichmentResult(
        source="public_search_ownership",
        vendor_name="Berry Aviation, Inc.",
        identifiers={"duns": "131827925"},
        source_class="public_connector",
        authority_level="third_party_public",
        access_model="search_public_html",
    )

    monkeypatch.setattr(enrichment, "CONNECTORS", [("public_search_ownership", object())])
    monkeypatch.setattr(enrichment, "_filter_connectors_by_country", lambda active, country: active)
    monkeypatch.setattr(
        enrichment,
        "_run_connector_cached",
        lambda mod, vendor_name, country, ids, connector_name=None, skip_cache=False: result,
    )

    report = enrichment.enrich_vendor(
        "Berry Aviation, Inc.",
        country="US",
        connectors=["public_search_ownership"],
        parallel=False,
        force=True,
        **{
            "cage": "0EA28",
            "uei": "V1HATBT1N7V5",
            "__seed_identifier_sources": {
                "cage": ["public_search_ownership"],
                "uei": ["public_search_ownership"],
            },
            "__seed_connector_status": {
                "public_search_ownership": {
                    "has_data": True,
                    "error": "",
                    "authority_level": "third_party_public",
                    "access_model": "search_public_html",
                    "structured_fields": {},
                }
            },
        },
    )

    assert report["identifiers"]["cage"] == "0EA28"
    assert report["identifiers"]["uei"] == "V1HATBT1N7V5"
    assert report["identifiers"]["duns"] == "131827925"
    assert report["identifier_sources"]["cage"] == ["public_search_ownership"]
    assert report["identifier_sources"]["uei"] == ["public_search_ownership"]
    assert report["identifier_sources"]["duns"] == ["public_search_ownership"]


def test_build_report_preserves_present_identifier_when_later_connector_is_unverified():
    public_result = EnrichmentResult(
        source="public_search_ownership",
        vendor_name="Columbia Helicopters, Inc.",
        identifiers={"uei": "EBD3SM6LH8D3"},
        source_class="public_connector",
        authority_level="third_party_public",
        access_model="search_public_html",
    )
    sam_result = EnrichmentResult(
        source="sam_gov",
        vendor_name="Columbia Helicopters, Inc.",
        identifiers={"uei": None},
        error="SAM.gov rate limit reached",
        source_class="gated_federal_source",
        authority_level="official_program_system",
        access_model="authenticated_api",
        structured_fields={
            "sam_api_status": {
                "entity_search": {
                    "throttled": True,
                    "next_access_time": "2026-Mar-29 00:00:00+0000 UTC",
                }
            }
        },
    )

    report = enrichment._build_report("Columbia Helicopters, Inc.", "US", [public_result, sam_result], 0.0)

    assert report["identifiers"]["uei"] == "EBD3SM6LH8D3"
    assert report["identifier_sources"]["uei"] == ["public_search_ownership"]


def test_build_report_prefers_stronger_identifier_source_over_weaker_conflict():
    public_result = EnrichmentResult(
        source="public_search_ownership",
        vendor_name="Boeing",
        identifiers={"website": "https://boeing.mediaroom.com"},
        source_class="public_connector",
        authority_level="third_party_public",
        access_model="search_public_html",
    )
    official_result = EnrichmentResult(
        source="public_html_ownership",
        vendor_name="Boeing",
        identifiers={"website": "https://www.boeing.com"},
        source_class="public_connector",
        authority_level="first_party_self_disclosed",
        access_model="public_html",
    )

    report = enrichment._build_report("Boeing", "US", [public_result, official_result], 0.0)

    assert report["identifiers"]["website"] == "https://www.boeing.com"
    assert report["identifier_sources"]["website"] == ["public_html_ownership"]
