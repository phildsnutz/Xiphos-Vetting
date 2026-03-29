from __future__ import annotations

from backend.osint import opencorporates


def test_opencorporates_emits_graph_native_officer_relationships(monkeypatch):
    monkeypatch.setattr(opencorporates, "API_KEY", "test-key")
    monkeypatch.setattr(
        opencorporates,
        "_search_companies",
        lambda *_args, **_kwargs: [
            {
                "name": "Example Defense Ltd",
                "company_number": "12345678",
                "jurisdiction_code": "gb",
                "current_status": "Active",
                "company_type": "ltd",
                "incorporation_date": "2021-01-01",
                "registered_address_in_full": "London",
                "opencorporates_url": "https://opencorporates.example/company/gb/12345678",
            }
        ],
    )
    monkeypatch.setattr(
        opencorporates,
        "_get_officers",
        lambda *_args, **_kwargs: [
            {
                "name": "Alice Smith",
                "position": "director",
                "start_date": "2022-02-02",
                "inactive": False,
            },
            {
                "name": "Bob Jones",
                "position": "secretary",
                "start_date": "2023-03-03",
                "inactive": True,
            },
        ],
    )
    monkeypatch.setattr(opencorporates.time, "sleep", lambda *_args, **_kwargs: None)

    result = opencorporates.enrich("Example Defense", country="GB")

    assert result.error == ""
    assert result.identifiers["company_number"] == "12345678"
    assert result.identifiers["officers_count"] == 1
    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert relationship["type"] == "officer_of"
    assert relationship["source_entity"] == "Alice Smith"
    assert relationship["target_entity"] == "Example Defense Ltd"
    assert relationship["source_entity_type"] == "person"
    assert relationship["target_entity_type"] == "company"
    assert relationship["data_source"] == "opencorporates"
    assert relationship["authority_level"] == "public_registry_aggregator"
    assert relationship["access_model"] == "public_api"
    assert relationship["source_class"] == "public_connector"
    assert relationship["structured_fields"]["position"] == "director"
    assert relationship["structured_fields"]["company_number"] == "12345678"

