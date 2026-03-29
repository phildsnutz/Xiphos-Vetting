from __future__ import annotations

import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_singapore_acra_connector_normalizes_position_holders_and_owners(monkeypatch):
    from osint import singapore_acra

    fixture_payload = {
        "records": [
            {
                "entity_name": "Lion City Mission Systems Pte. Ltd.",
                "country": "SG",
                "uen": "201912345N",
                "status": "Live",
                "entity_type": "Private Company Limited by Shares",
                "registration_date": "2019-04-12",
                "primary_ssic": "62011",
                "secondary_ssic": "62021",
                "position_holders": [
                    {
                        "name": "Melissa Tan",
                        "role": "director",
                        "appointed_on": "2019-04-12",
                    }
                ],
                "owners_or_partners": [
                    {
                        "name": "Straits Strategic Holdings Pte. Ltd.",
                        "entity_type": "holding_company",
                        "country": "SG",
                        "share_pct": 75.0,
                        "interest_description": "Major shareholder",
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(singapore_acra, "_fetch_json", lambda _url: fixture_payload)

    result = singapore_acra.enrich(
        "Lion City Mission Systems Pte. Ltd.",
        country="SG",
        singapore_acra_url="https://example.test/acra-business-profile.json",
    )

    assert result.has_data
    assert result.identifiers["uen"] == "201912345N"
    assert result.structured_fields["summary"]["position_holder_count"] == 1
    assert result.structured_fields["summary"]["owner_or_partner_count"] == 1
    rel_types = {rel["type"] for rel in result.relationships}
    assert rel_types == {"officer_of", "owned_by"}
    assert "ACRA business profile" in result.findings[0].title
