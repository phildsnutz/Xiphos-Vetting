from __future__ import annotations

import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_corporations_canada_connector_normalizes_directors_and_isc(monkeypatch):
    from osint import corporations_canada

    fixture_payload = {
        "records": [
            {
                "corporation_name": "Northern Mission Systems Inc.",
                "country": "CA",
                "ca_corporation_number": "1234567",
                "business_number": "765432109RC0001",
                "status": "Active",
                "governing_legislation": "CBCA",
                "incorporation_date": "2021-05-04",
                "directors": [
                    {
                        "name": "Avery North",
                        "role": "director",
                        "appointed_on": "2021-05-04",
                    }
                ],
                "individuals_with_significant_control": [
                    {
                        "name": "Jordan Vale",
                        "entity_type": "person",
                        "country": "CA",
                        "control_description": "25% or more of voting shares",
                        "became_isc_on": "2022-01-15",
                    }
                ],
                "filings": [
                    {
                        "date": "2026-01-10",
                        "category": "annual_return",
                        "description": "Annual return filed",
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(corporations_canada, "_fetch_json", lambda _url: fixture_payload)

    result = corporations_canada.enrich(
        "Northern Mission Systems Inc.",
        country="CA",
        corporations_canada_url="https://example.test/corporations-canada.json",
    )

    assert result.has_data
    assert result.identifiers["ca_corporation_number"] == "1234567"
    assert result.identifiers["business_number"] == "765432109RC0001"
    assert result.structured_fields["summary"]["isc_count"] == 1
    rel_types = {rel["type"] for rel in result.relationships}
    assert rel_types == {"officer_of", "beneficially_owned_by"}
    assert any("ISC records: 1 public disclosures" in finding.title for finding in result.findings)
