from __future__ import annotations

import os
import sys
import json


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_openownership_public_connector_normalizes_public_bods_records(monkeypatch):
    from osint import openownership_bods_public

    monkeypatch.setattr(
        openownership_bods_public,
        "_fetch_json",
        lambda _url: {
            "records": [
                {
                    "record_id": "bods-live-001",
                    "name": "North Sea Mission Analytics Ltd",
                    "country": "GB",
                    "subject": {
                        "name": "North Sea Mission Analytics Ltd",
                        "entity_type": "company",
                        "identifiers": {
                            "uk_company_number": "09876543",
                            "lei": "529900NSMA0000000001",
                        },
                    },
                    "statements": [
                        {
                            "statement_id": "ooc-live-001",
                            "statement_type": "ownershipOrControlStatement",
                            "direct_or_indirect": "direct",
                            "interests": ["shareholding"],
                            "interested_party": {
                                "name": "Atlantic Strategic Holdings LLP",
                                "entity_type": "holding_company",
                                "country": "GB",
                                "identifiers": {"uk_company_number": "OC123456"},
                            },
                        },
                        {
                            "statement_id": "ooc-live-002",
                            "statement_type": "ownershipOrControlStatement",
                            "direct_or_indirect": "indirect",
                            "interests": ["significant-influence-or-control"],
                            "interested_party": {
                                "name": "Caledonia Family Trust",
                                "entity_type": "holding_company",
                                "country": "JE",
                                "identifiers": {"record_ref": "trust-001"},
                            },
                        },
                    ],
                }
            ]
        },
    )

    result = openownership_bods_public.enrich(
        "North Sea Mission Analytics Ltd",
        country="GB",
        openownership_bods_url="https://example.test/bods.json",
        uk_company_number="09876543",
    )

    assert result.has_data
    assert result.identifiers["uk_company_number"] == "09876543"
    assert result.identifiers["openownership_bods_url"] == "https://example.test/bods.json"
    rel_types = {rel["type"] for rel in result.relationships}
    assert rel_types == {"owned_by", "beneficially_owned_by"}
    assert result.structured_fields["summary"]["statement_count"] == 2
    assert result.findings[0].url == "https://example.test/bods.json"


def test_openownership_public_connector_supports_local_cached_dataset(tmp_path):
    from osint import openownership_bods_public

    cache_path = tmp_path / "openownership_bods_public.jsonl"
    cache_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "record_id": "bods-cache-001",
                        "name": "Atlas Signal Systems Ltd",
                        "country": "GB",
                        "subject": {
                            "name": "Atlas Signal Systems Ltd",
                            "entity_type": "company",
                            "identifiers": {
                                "uk_company_number": "01234567",
                                "lei": "529900ATLAS000000001",
                            },
                        },
                        "statements": [
                            {
                                "statement_id": "ooc-cache-001",
                                "statement_type": "ownershipOrControlStatement",
                                "direct_or_indirect": "direct",
                                "interested_party": {
                                    "name": "North Atlantic Defense Holdings LLP",
                                    "entity_type": "holding_company",
                                    "country": "GB",
                                },
                            }
                        ],
                    }
                )
            ]
        ),
        encoding="utf-8",
    )

    result = openownership_bods_public.enrich(
        "Atlas Signal Systems Ltd",
        country="GB",
        openownership_bods_path=str(cache_path),
        uk_company_number="01234567",
    )

    assert result.has_data
    assert result.identifiers["openownership_bods_path"] == str(cache_path.resolve())
    assert result.relationships[0]["type"] == "owned_by"
    assert result.relationships[0]["target_entity"] == "North Atlantic Defense Holdings LLP"
    assert result.artifact_refs == [str(cache_path.resolve())]
