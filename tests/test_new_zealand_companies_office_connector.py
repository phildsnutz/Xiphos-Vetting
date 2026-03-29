from __future__ import annotations

import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_new_zealand_companies_office_connector_normalizes_officers_and_shareholdings(monkeypatch):
    from osint import new_zealand_companies_office

    fixture_payload = {
        "records": [
            {
                "entity_name": "Harbour Mission Analytics Limited",
                "country": "NZ",
                "nzbn": "9429041234567",
                "nz_company_number": "9182736",
                "status": "Registered",
                "entity_type": "NZ Limited Company",
                "incorporated_on": "2020-04-18",
                "region": "Wellington",
                "industry_description": "Defence software and analytics",
                "trading_names": ["Harbour Mission Analytics"],
                "officeholders": [
                    {
                        "name": "Aroha Bennett",
                        "role": "director",
                        "appointed_on": "2020-04-18",
                    }
                ],
                "shareholdings": [
                    {
                        "name": "Southern Horizon Holdings Limited",
                        "entity_type": "holding_company",
                        "country": "NZ",
                        "share_pct": 62.5,
                        "interest_description": "Majority voting shares",
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(new_zealand_companies_office, "_fetch_json", lambda _url: fixture_payload)

    result = new_zealand_companies_office.enrich(
        "Harbour Mission Analytics Limited",
        country="NZ",
        new_zealand_companies_office_url="https://example.test/nz-registry.json",
    )

    assert result.has_data
    assert result.identifiers["nzbn"] == "9429041234567"
    assert result.identifiers["nz_company_number"] == "9182736"
    assert result.structured_fields["summary"]["officeholder_count"] == 1
    assert result.structured_fields["summary"]["shareholding_count"] == 1
    rel_types = {rel["type"] for rel in result.relationships}
    assert rel_types == {"officer_of", "owned_by"}
    assert "New Zealand Companies Office" in result.findings[0].title
