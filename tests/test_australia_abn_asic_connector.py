from __future__ import annotations

import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_australia_abn_asic_connector_normalizes_officeholders(monkeypatch):
    from osint import australia_abn_asic

    fixture_payload = {
        "records": [
            {
                "entity_name": "Southern Range Robotics Pty Ltd",
                "country": "AU",
                "abn": "53123456789",
                "acn": "123456789",
                "status": "Active",
                "entity_type": "Australian Proprietary Company",
                "registered_on": "2019-08-14",
                "gst_status": "Registered",
                "state": "QLD",
                "business_names": ["Southern Range Robotics"],
                "officeholders": [
                    {
                        "name": "Amelia Hart",
                        "role": "director",
                        "appointed_on": "2019-08-14",
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(australia_abn_asic, "_fetch_json", lambda _url: fixture_payload)

    result = australia_abn_asic.enrich(
        "Southern Range Robotics Pty Ltd",
        country="AU",
        australia_abn_asic_url="https://example.test/australia-registry.json",
    )

    assert result.has_data
    assert result.identifiers["abn"] == "53123456789"
    assert result.identifiers["acn"] == "123456789"
    assert result.structured_fields["summary"]["officeholder_count"] == 1
    assert result.relationships[0]["type"] == "officer_of"
    assert "ABR / ASIC" in result.findings[0].title
