from __future__ import annotations

import json

from backend.osint import gleif_lei


def _gleif_record(record_id: str, legal_name: str, jurisdiction: str, legal_country: str) -> dict:
    return {
        "id": record_id,
        "attributes": {
            "entity": {
                "legalName": {"name": legal_name},
                "jurisdiction": jurisdiction,
                "legalAddress": {"country": legal_country},
                "headquartersAddress": {"country": legal_country},
                "status": "ACTIVE",
                "legalForm": {"id": "XX"},
            },
            "registration": {
                "status": "ISSUED",
                "initialRegistrationDate": "2020-01-01",
                "nextRenewalDate": "2027-01-01",
            },
        },
    }


def test_gleif_prefers_high_confidence_us_match(monkeypatch):
    search_payload = {
        "data": [
            _gleif_record("wrong", "Gazelle.ia Inc. / Gazelle.ai Inc.", "CA", "CA"),
            _gleif_record("right", "B.E. Meyers & Co., Inc.", "US-CA", "US"),
        ]
    }
    detail_payload = {"data": _gleif_record("right", "B.E. Meyers & Co., Inc.", "US-CA", "US")}

    def fake_get(url: str):
        if "filter[fulltext]" in url:
            return search_payload
        if url.endswith("/lei-records/right"):
            return detail_payload
        return None

    monkeypatch.setattr(gleif_lei, "_get", fake_get)
    monkeypatch.setattr(gleif_lei.time, "sleep", lambda *_: None)

    result = gleif_lei.enrich("B.E. Meyers & Co., Inc.", country="US")

    assert result.identifiers["lei"] == "right"
    assert result.identifiers["legal_name"] == "B.E. Meyers & Co., Inc."
    assert result.identifiers["legal_jurisdiction"] == "US-CA"


def test_gleif_rejects_foreign_match_for_us_vendor(monkeypatch):
    search_payload = {
        "data": [
            _gleif_record("foreign", "Axon Financial GmbH", "CH", "CH"),
        ]
    }

    def fake_get(url: str):
        if "filter[fulltext]" in url:
            return search_payload
        raise AssertionError(f"unexpected detail lookup: {url}")

    monkeypatch.setattr(gleif_lei, "_get", fake_get)
    monkeypatch.setattr(gleif_lei.time, "sleep", lambda *_: None)

    result = gleif_lei.enrich("Axon", country="US")

    assert "lei" not in result.identifiers
    assert any(f.title == "No high-confidence LEI found" for f in result.findings)


def test_gleif_emits_graph_native_parent_relationships(monkeypatch):
    search_payload = {"data": [_gleif_record("right", "B.E. Meyers & Co., Inc.", "US-CA", "US")]}
    detail_payload = {"data": _gleif_record("right", "B.E. Meyers & Co., Inc.", "US-CA", "US")}
    direct_parent_payload = {"data": {"id": "parent-lei"}}
    direct_parent_detail = {"data": _gleif_record("parent-lei", "Mission Holdings LLC", "US-DE", "US")}
    ultimate_parent_payload = {"data": {"id": "ultimate-lei"}}
    ultimate_parent_detail = {"data": _gleif_record("ultimate-lei", "Strategic Capital Group", "US-VA", "US")}

    def fake_get(url: str):
        if "filter[fulltext]" in url:
            return search_payload
        if url.endswith("/lei-records/right"):
            return detail_payload
        if url.endswith("/lei-records/right/direct-parent"):
            return direct_parent_payload
        if url.endswith("/lei-records/parent-lei"):
            return direct_parent_detail
        if url.endswith("/lei-records/right/ultimate-parent"):
            return ultimate_parent_payload
        if url.endswith("/lei-records/ultimate-lei"):
            return ultimate_parent_detail
        raise AssertionError(f"unexpected GLEIF lookup: {url}")

    monkeypatch.setattr(gleif_lei, "_get", fake_get)
    monkeypatch.setattr(gleif_lei.time, "sleep", lambda *_: None)

    result = gleif_lei.enrich("B.E. Meyers & Co., Inc.", country="US")

    rel_types = {rel["type"] for rel in result.relationships}
    assert rel_types == {"owned_by", "beneficially_owned_by"}

    direct_rel = next(rel for rel in result.relationships if rel["type"] == "owned_by")
    assert direct_rel["target_entity"] == "Mission Holdings LLC"
    assert direct_rel["target_identifiers"]["lei"] == "parent-lei"
    assert direct_rel["target_entity_type"] == "holding_company"
    assert direct_rel["structured_fields"]["relationship_scope"] == "direct_parent"
    assert direct_rel["structured_fields"]["standards"] == ["GLEIF Level 2"]

    ultimate_rel = next(rel for rel in result.relationships if rel["type"] == "beneficially_owned_by")
    assert ultimate_rel["target_entity"] == "Strategic Capital Group"
    assert ultimate_rel["target_identifiers"]["lei"] == "ultimate-lei"
    assert ultimate_rel["structured_fields"]["relationship_scope"] == "ultimate_parent"


def test_gleif_supports_local_cache_path(tmp_path, monkeypatch):
    cache_path = tmp_path / "gleif_lei_cache.jsonl"
    cache_path.write_text(
        json.dumps(
            {
                "vendor_name": "B.E. Meyers & Co., Inc.",
                "country": "US",
                "source": "gleif_lei",
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_api",
                "identifiers": {
                    "lei": "right",
                    "legal_name": "B.E. Meyers & Co., Inc.",
                    "legal_jurisdiction": "US-CA",
                },
                "findings": [
                    {
                        "source": "gleif_lei",
                        "category": "identity",
                        "title": "LEI verified: B.E. Meyers & Co., Inc.",
                        "detail": "cached",
                        "severity": "info",
                        "confidence": 0.95,
                    }
                ],
                "relationships": [
                    {
                        "type": "owned_by",
                        "target_entity": "Mission Holdings LLC",
                        "target_identifiers": {"lei": "parent-lei"},
                    }
                ],
                "risk_signals": [],
                "artifact_refs": [],
                "structured_fields": {"cache_mode": "local"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(gleif_lei, "_get", lambda _url: (_ for _ in ()).throw(AssertionError("live lookup should not run")))

    result = gleif_lei.enrich(
        "B.E. Meyers & Co., Inc.",
        country="US",
        gleif_cache_path=str(cache_path),
    )

    assert result.identifiers["lei"] == "right"
    assert result.identifiers["gleif_cache_path"] == str(cache_path.resolve())
    assert result.relationships[0]["target_entity"] == "Mission Holdings LLC"
    assert result.artifact_refs == [str(cache_path.resolve())]
