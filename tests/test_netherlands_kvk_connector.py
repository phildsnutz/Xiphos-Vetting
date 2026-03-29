from __future__ import annotations

import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_netherlands_kvk_connector_normalizes_officers_shareholders_and_mutations(monkeypatch):
    from osint import netherlands_kvk

    fixture_payload = {
        "records": [
            {
                "entity_name": "Oranje Mission Analytics B.V.",
                "country": "NL",
                "kvk_number": "68456789",
                "establishment_number": "000036845678",
                "rsin": "858412345",
                "status": "Active",
                "legal_form": "Besloten Vennootschap",
                "registered_on": "2017-06-14",
                "region": "South Holland",
                "sbi_code": "62020",
                "website": "https://www.oranjemissionanalytics.nl",
                "trade_names": ["Oranje Mission Analytics"],
                "officers": [
                    {
                        "name": "Sanne de Vries",
                        "role": "Managing Director",
                        "appointed_on": "2017-06-14",
                    }
                ],
                "shareholders": [
                    {
                        "name": "Lowlands Strategic Holdings B.V.",
                        "entity_type": "holding_company",
                        "country": "NL",
                        "share_pct": 68.0,
                        "interest_description": "Majority shareholder",
                    }
                ],
                "mutations": [
                    {
                        "date": "2025-09-03",
                        "mutation_type": "address_update",
                        "summary": "Registered office updated in South Holland",
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(netherlands_kvk, "_fetch_json", lambda _url: fixture_payload)

    result = netherlands_kvk.enrich(
        "Oranje Mission Analytics B.V.",
        country="NL",
        netherlands_kvk_url="https://example.test/kvk-profile.json",
    )

    assert result.has_data
    assert result.identifiers["kvk_number"] == "68456789"
    assert result.structured_fields["summary"]["officer_count"] == 1
    assert result.structured_fields["summary"]["shareholder_count"] == 1
    assert result.structured_fields["summary"]["mutation_count"] == 1
    rel_types = {rel["type"] for rel in result.relationships}
    assert rel_types == {"officer_of", "owned_by"}
    assert "KVK profile" in result.findings[0].title
