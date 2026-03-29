import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from osint import enrichment


def test_website_merge_prefers_public_search_over_wikidata():
    identifiers = {"website": "https://www.hellenicdefence.com"}
    identifier_sources = {"website": ["wikidata_company"]}
    connector_status = {
        "wikidata_company": {"authority_level": "third_party_public"},
        "public_search_ownership": {"authority_level": "third_party_public"},
    }
    connector_metadata = {}

    enrichment._merge_identifier_value(
        identifiers,
        identifier_sources,
        connector_status,
        connector_metadata,
        "public_search_ownership",
        "website",
        "https://eas.gr",
    )

    assert identifiers["website"] == "https://eas.gr"
    assert identifier_sources["website"] == ["public_search_ownership"]


def test_website_merge_prefers_public_search_over_public_html_for_canonical_root():
    identifiers = {"website": "https://www.hellenicdefence.com"}
    identifier_sources = {"website": ["public_html_ownership"]}
    connector_status = {
        "public_html_ownership": {"authority_level": "first_party_self_disclosed"},
        "public_search_ownership": {"authority_level": "third_party_public"},
    }
    connector_metadata = {}

    enrichment._merge_identifier_value(
        identifiers,
        identifier_sources,
        connector_status,
        connector_metadata,
        "public_search_ownership",
        "website",
        "https://eas.gr",
    )

    assert identifiers["website"] == "https://eas.gr"
    assert identifier_sources["website"] == ["public_search_ownership"]


def test_identifier_merge_same_source_refresh_replaces_stale_value():
    identifiers = {"duns": "081215850"}
    identifier_sources = {"duns": ["public_search_ownership"]}
    connector_status = {
        "public_search_ownership": {"authority_level": "third_party_public"},
    }
    connector_metadata = {}

    enrichment._merge_identifier_value(
        identifiers,
        identifier_sources,
        connector_status,
        connector_metadata,
        "public_search_ownership",
        "duns",
        "801478384",
    )

    assert identifiers["duns"] == "801478384"
    assert identifier_sources["duns"] == ["public_search_ownership"]
