from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from osint import EnrichmentResult, Finding
from osint import enrichment
from osint.cache import get_cache


class _FakeSearchConnector:
    def enrich(self, vendor_name: str, country: str = "", **ids):
        return EnrichmentResult(
            source="public_search_ownership",
            vendor_name=vendor_name,
            identifiers={"website": "https://eas.gr"},
            findings=[
                Finding(
                    source="public_search_ownership",
                    category="identity",
                    title="Public search discovered official site candidate: https://eas.gr",
                    detail="fixture",
                )
            ],
            source_class="public_connector",
            authority_level="third_party_public",
            access_model="search_public_html",
        )


class _FakeHtmlConnector:
    def __init__(self):
        self.calls: list[str] = []

    def enrich(self, vendor_name: str, country: str = "", **ids):
        website = str(ids.get("website") or ids.get("domain") or "")
        self.calls.append(website)
        if website == "https://eas.gr":
            return EnrichmentResult(
                source="public_html_ownership",
                vendor_name=vendor_name,
                identifiers={"website": "https://eas.gr"},
                findings=[
                    Finding(
                        source="public_html_ownership",
                        category="ownership",
                        title="Public site ownership hint: Hellenic Ministry of Finance",
                        detail="fixture",
                    )
                ],
                relationships=[
                    {
                        "type": "owned_by",
                        "source_entity": vendor_name,
                        "target_entity": "Hellenic Ministry of Finance",
                        "data_source": "public_html_ownership",
                        "confidence": 0.76,
                    }
                ],
                source_class="public_connector",
                authority_level="first_party_self_disclosed",
                access_model="public_html",
            )
        if website:
            return EnrichmentResult(
                source="public_html_ownership",
                vendor_name=vendor_name,
                identifiers={"website": website},
                source_class="public_connector",
                authority_level="first_party_self_disclosed",
                access_model="public_html",
            )
        return EnrichmentResult(
            source="public_html_ownership",
            vendor_name=vendor_name,
            source_class="public_connector",
            authority_level="first_party_self_disclosed",
            access_model="public_html",
        )


def test_enrich_vendor_replays_public_html_after_search_discovers_canonical_website(monkeypatch):
    fake_html = _FakeHtmlConnector()
    monkeypatch.setattr(
        enrichment,
        "CONNECTORS",
        [("public_search_ownership", _FakeSearchConnector()), ("public_html_ownership", fake_html)],
    )
    monkeypatch.setattr(enrichment, "_filter_connectors_by_country", lambda active, country: active)

    report = enrichment.enrich_vendor(
        "HELLENIC DEFENCE SYSTEMS SA",
        country="GR",
        connectors=["public_search_ownership", "public_html_ownership"],
        parallel=False,
        force=True,
        website="https://www.hellenicdefence.com",
        __seed_identifier_sources={"website": ["public_html_ownership"]},
    )

    assert report["identifiers"]["website"] == "https://eas.gr"
    assert report["identifier_sources"]["website"] == ["public_search_ownership", "public_html_ownership"]
    assert any(rel["target_entity"] == "Hellenic Ministry of Finance" for rel in report["relationships"])
    assert fake_html.calls == ["https://www.hellenicdefence.com", "https://eas.gr"]


def test_public_html_cache_variant_includes_website_seed(monkeypatch):
    cache = get_cache()
    cache.clear()
    fake_html = _FakeHtmlConnector()

    result_one = enrichment._run_connector_cached(
        fake_html,
        "HELLENIC DEFENCE SYSTEMS SA",
        "GR",
        {"website": "https://www.hellenicdefence.com"},
        connector_name="public_html_ownership",
        skip_cache=False,
    )
    result_two = enrichment._run_connector_cached(
        fake_html,
        "HELLENIC DEFENCE SYSTEMS SA",
        "GR",
        {"website": "https://eas.gr"},
        connector_name="public_html_ownership",
        skip_cache=False,
    )

    assert result_one.identifiers["website"] == "https://www.hellenicdefence.com"
    assert result_two.identifiers["website"] == "https://eas.gr"
    assert fake_html.calls == ["https://www.hellenicdefence.com", "https://eas.gr"]


def test_public_html_connector_uses_extended_timeout_budget(monkeypatch):
    captured: dict[str, int] = {}

    def fake_run_connector_once(mod, vendor_name, country, ids, timeout_s=0):
        captured["timeout_s"] = timeout_s
        return EnrichmentResult(
            source="public_html_ownership",
            vendor_name=vendor_name,
            source_class="public_connector",
            authority_level="first_party_self_disclosed",
            access_model="public_html",
        )

    monkeypatch.setattr(enrichment, "_run_connector_once", fake_run_connector_once)

    enrichment._run_connector_with_timeout(
        object(),
        "HELLENIC DEFENCE SYSTEMS SA",
        "GR",
        {"website": "https://eas.gr"},
        connector_name="public_html_ownership",
    )

    assert captured["timeout_s"] == enrichment.CONNECTOR_EXECUTION_TIMEOUTS["public_html_ownership"]


class _FakePackageInventoryConnector:
    def enrich(self, vendor_name: str, country: str = "", **_ids):
        return EnrichmentResult(
            source="public_assurance_evidence_fixture",
            vendor_name=vendor_name,
            identifiers={
                "package_inventory": [
                    {"ecosystem": "PyPI", "name": "telemetry-core", "version": "2.4.1"},
                ]
            },
            findings=[
                Finding(
                    source="public_assurance_evidence_fixture",
                    category="supply_chain_assurance",
                    title="Fixture exposed package inventory",
                    detail="fixture",
                )
            ],
            source_class="analyst_fixture",
            authority_level="first_party_self_disclosed",
            access_model="local_json_fixture",
        )


class _FakeOsvConnector:
    def __init__(self):
        self.calls: list[str] = []

    def enrich(self, vendor_name: str, country: str = "", **ids):
        inventory = ids.get("package_inventory") or []
        self.calls.append(str(inventory))
        if inventory:
            return EnrichmentResult(
                source="osv_dev",
                vendor_name=vendor_name,
                findings=[
                    Finding(
                        source="osv_dev",
                        category="supply_chain_assurance",
                        title="OSV advisories surfaced",
                        detail="fixture",
                    )
                ],
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="public_api",
            )
        return EnrichmentResult(
            source="osv_dev",
            vendor_name=vendor_name,
            source_class="public_connector",
            authority_level="third_party_public",
            access_model="public_api",
        )


def test_enrich_vendor_replays_package_collectors_after_inventory_discovery(monkeypatch):
    fake_osv = _FakeOsvConnector()
    monkeypatch.setattr(
        enrichment,
        "CONNECTORS",
        [("public_assurance_evidence_fixture", _FakePackageInventoryConnector()), ("osv_dev", fake_osv)],
    )
    monkeypatch.setattr(enrichment, "_filter_connectors_by_country", lambda active, country: active)

    report = enrichment.enrich_vendor(
        "Horizon Mission Systems LLC",
        country="US",
        connectors=["public_assurance_evidence_fixture", "osv_dev"],
        parallel=False,
        force=True,
    )

    assert any(finding["source"] == "osv_dev" for finding in report["findings"])
    assert fake_osv.calls == ["[]", "[{'ecosystem': 'PyPI', 'name': 'telemetry-core', 'version': '2.4.1'}]"]
