import sys

sys.path.insert(0, "/Users/tyegonzalez/Desktop/Helios-Package Merged/backend")

from osint import EnrichmentResult  # noqa: E402
from osint import usaspending  # noqa: E402


def test_exactish_name_match_is_strict_for_parent_vs_subsidiary():
    assert usaspending._exactish_name_match(
        "General Atomics Aeronautical Systems, Inc.",
        ["General Atomics Aeronautical Systems Inc"],
    )
    assert not usaspending._exactish_name_match(
        "General Atomics",
        ["General Atomics Aeronautical Systems, Inc."],
    )


def test_extract_supply_chain_collects_primes_and_subs(monkeypatch):
    vendor = "General Atomics Aeronautical Systems, Inc."
    result = EnrichmentResult(source="usaspending", vendor_name=vendor)

    def fake_search_subaward_awards(name, limit=50):
        return {
            "results": [
                {
                    "Prime Recipient Name": "MANTECH ADVANCED SYSTEMS INTERNATIONAL, INC.",
                    "Sub-Awardee Name": vendor,
                    "Sub-Award Amount": 1_200_000,
                    "Prime Award ID": "PRIME-1",
                },
                {
                    "Prime Recipient Name": "GENERAL ATOMICS",
                    "Sub-Awardee Name": vendor,
                    "Sub-Award Amount": 800_000,
                    "Prime Award ID": "PRIME-2",
                },
            ]
        }

    def fake_get_subawards_for_award(award_id, limit=50):
        return {
            "results": [
                {"recipient_name": vendor, "amount": 999},
                {"recipient_name": "Mercury Systems, Inc.", "amount": 500_000},
                {"recipient_name": "L3Harris Technologies, Inc.", "amount": 250_000},
            ]
        }

    monkeypatch.setattr(usaspending, "_search_subaward_awards", fake_search_subaward_awards)
    monkeypatch.setattr(usaspending, "_get_subawards_for_award", fake_get_subawards_for_award)

    awards = [{"generated_internal_id": "CONT_AWD_XYZ", "Awarding Agency": "Department of Defense"}]
    usaspending._extract_supply_chain(vendor, result, recipient_name=vendor, awards=awards)

    rel_types = {(rel["type"], rel.get("source_entity"), rel.get("target_entity")) for rel in result.relationships}
    assert ("prime_contractor_of", "MANTECH ADVANCED SYSTEMS INTERNATIONAL, INC.", vendor) in rel_types
    assert ("subcontractor_of", vendor, "Mercury Systems, Inc.") in rel_types
    assert ("subcontractor_of", vendor, "L3Harris Technologies, Inc.") in rel_types

    titles = [finding.title for finding in result.findings if finding.category == "supply_chain"]
    assert any("Prime contractor relationships" in title for title in titles)
    assert any("Supply chain:" in title for title in titles)
