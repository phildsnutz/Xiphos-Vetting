from __future__ import annotations

from backend.osint import wikidata_company


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


def test_wikidata_emits_graph_native_parent_relationship(monkeypatch):
    payload = {
        "results": {
            "bindings": [
                {
                    "item": {"value": "https://www.wikidata.org/entity/Q123"},
                    "itemLabel": {"value": "Acme Avionics"},
                    "parentLabel": {"value": "Horizon Mission Systems"},
                    "countryLabel": {"value": "United States"},
                    "websiteUrl": {"value": "https://acme.example"},
                }
            ]
        }
    }

    def fake_get(_url: str, params: dict, timeout: int):
        assert timeout == wikidata_company.TIMEOUT
        assert "Acme Avionics" in params["query"]
        return _FakeResponse(payload)

    monkeypatch.setattr(wikidata_company.requests, "get", fake_get)

    result = wikidata_company.enrich("Acme Avionics", country="US")

    assert result.identifiers["wikidata_id"] == "Q123"
    assert result.identifiers["website"] == "https://acme.example"
    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert relationship["type"] == "owned_by"
    assert relationship["target_entity"] == "Horizon Mission Systems"
    assert relationship["structured_fields"]["relationship_scope"] == "parent_company"
    assert relationship["evidence_url"] == "https://www.wikidata.org/wiki/Q123"
