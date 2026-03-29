import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_country_specific_connectors_do_not_leak_into_global_pool():
    import osint.enrichment as enrichment

    overlaps = (
        enrichment.GLOBAL_CONNECTORS & enrichment.UK_ONLY_CONNECTORS
        | enrichment.GLOBAL_CONNECTORS & enrichment.CANADA_ONLY_CONNECTORS
        | enrichment.GLOBAL_CONNECTORS & enrichment.AUSTRALIA_ONLY_CONNECTORS
        | enrichment.GLOBAL_CONNECTORS & enrichment.SINGAPORE_ONLY_CONNECTORS
        | enrichment.GLOBAL_CONNECTORS & enrichment.NEW_ZEALAND_ONLY_CONNECTORS
        | enrichment.GLOBAL_CONNECTORS & enrichment.NORWAY_ONLY_CONNECTORS
        | enrichment.GLOBAL_CONNECTORS & enrichment.NETHERLANDS_ONLY_CONNECTORS
        | enrichment.GLOBAL_CONNECTORS & enrichment.FRANCE_ONLY_CONNECTORS
    )
    assert overlaps == set()


def test_norway_connector_is_filtered_for_us_vendor():
    import osint.enrichment as enrichment

    active = [(name, None) for name in ("norway_brreg", "public_search_ownership", "sam_gov")]
    filtered = enrichment._filter_connectors_by_country(active, "US")

    assert ("norway_brreg", None) not in filtered
    assert ("public_search_ownership", None) in filtered
    assert ("sam_gov", None) in filtered


def test_netherlands_connector_is_filtered_for_us_vendor():
    import osint.enrichment as enrichment

    active = [(name, None) for name in ("netherlands_kvk", "public_search_ownership", "sam_gov")]
    filtered = enrichment._filter_connectors_by_country(active, "US")

    assert ("netherlands_kvk", None) not in filtered
    assert ("public_search_ownership", None) in filtered
    assert ("sam_gov", None) in filtered


def test_france_connector_is_filtered_for_us_vendor():
    import osint.enrichment as enrichment

    active = [(name, None) for name in ("france_inpi_rne", "public_search_ownership", "sam_gov")]
    filtered = enrichment._filter_connectors_by_country(active, "US")

    assert ("france_inpi_rne", None) not in filtered
    assert ("public_search_ownership", None) in filtered
    assert ("sam_gov", None) in filtered
