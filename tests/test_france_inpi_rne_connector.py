from __future__ import annotations

import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_france_inpi_rne_connector_normalizes_identity_and_gated_beneficial_ownership(monkeypatch):
    from osint import france_inpi_rne

    fixture_payload = {
        "records": [
            {
                "entity_name": "Hexagone Mission Systems SAS",
                "country": "FR",
                "fr_siren": "552100554",
                "fr_siret": "55210055400013",
                "status": "Active",
                "legal_form": "SAS",
                "registration_date": "2020-05-14",
                "ape_code": "6202A",
                "registered_city": "Paris",
                "officers": [
                    {
                        "name": "Claire Durand",
                        "role": "Présidente",
                        "appointed_on": "2020-05-14",
                    }
                ],
                "beneficial_owners": [
                    {
                        "name": "Hexagone Strategic Holdings SAS",
                        "entity_type": "company",
                        "country": "FR",
                        "share_pct": 82.0,
                        "control_description": "Détention directe supérieure à 50%",
                    }
                ],
                "beneficial_owner_access": "INPI beneficial-owner access is gated to authorized users or legitimate-interest workflows.",
            }
        ]
    }
    monkeypatch.setattr(france_inpi_rne, "_fetch_json", lambda _url: fixture_payload)

    result = france_inpi_rne.enrich(
        "Hexagone Mission Systems SAS",
        country="FR",
        france_inpi_rne_url="https://example.test/inpi-rne.json",
    )

    assert result.has_data
    assert result.identifiers["fr_siren"] == "552100554"
    assert result.identifiers["fr_siret"] == "55210055400013"
    assert result.structured_fields["summary"]["beneficial_owner_count"] == 1
    rel_types = {rel["type"] for rel in result.relationships}
    assert rel_types == {"officer_of", "beneficially_owned_by"}
    assert any("beneficial-owner access posture" in finding.title.lower() for finding in result.findings)
