import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from osint import sam_subaward_reporting  # noqa: E402


def test_enrich_returns_configuration_finding_without_api_key(monkeypatch):
    monkeypatch.delenv("XIPHOS_SAM_API_KEY", raising=False)
    monkeypatch.delenv("SAM_GOV_API_KEY", raising=False)

    result = sam_subaward_reporting.enrich("Prime Vendor", country="US")

    assert result.findings
    assert result.findings[0].category == "configuration"
    assert "API key" in result.findings[0].detail


def test_enrich_aggregates_official_subcontract_reports(monkeypatch):
    monkeypatch.setenv("XIPHOS_SAM_API_KEY", "sam-test-key")

    def fake_search_prime_awards(vendor_name: str):
        assert vendor_name == "Prime Vendor"
        return [
            {
                "Award ID": "W15P7T24C0001",
                "Awarding Agency": "Department of Defense",
                "Award Amount": 2_500_000,
            }
        ]

    def fake_get_subcontracts_by_piid(piid: str, **_kwargs):
        assert piid == "W15P7T24C0001"
        return [
            {
                "subEntityLegalBusinessName": "Mercury Systems, Inc.",
                "subAwardAmount": "500000",
                "subEntityUei": "UEI-MERCURY",
                "subEntityParentLegalBusinessName": "Mercury Parent",
                "subBusinessType": "Small Business",
                "subAwardDescription": "Radar electronics support",
                "subAwardDate": "2026-01-04",
                "primeContractKey": "PRIMEKEY-1",
            },
            {
                "subEntityLegalBusinessName": "Mercury Systems, Inc.",
                "subAwardAmount": "250000",
                "subEntityUei": "UEI-MERCURY",
                "subEntityParentLegalBusinessName": "Mercury Parent",
                "subBusinessType": "Small Business",
                "subAwardDescription": "Follow-on support",
                "subAwardDate": "2026-02-14",
                "primeContractKey": "PRIMEKEY-1",
            },
            {
                "subEntityLegalBusinessName": "L3Harris Technologies, Inc.",
                "subAwardAmount": "300000",
                "subEntityUei": "UEI-L3",
                "subAwardDescription": "Payload systems integration",
                "subAwardDate": "2026-02-01",
                "primeContractKey": "PRIMEKEY-1",
            },
        ]

    monkeypatch.setattr(sam_subaward_reporting, "_search_prime_awards", fake_search_prime_awards)
    monkeypatch.setattr(sam_subaward_reporting, "_get_subcontracts_by_piid", fake_get_subcontracts_by_piid)

    result = sam_subaward_reporting.enrich("Prime Vendor", country="US")

    assert result.error == ""
    assert result.identifiers["sam_subaward_report_count"] == 3
    assert result.identifiers["sam_prime_contract_count"] == 1
    assert result.structured_fields["top_subcontractors"][0]["name"] == "Mercury Systems, Inc."

    relationships = {
        (rel["type"], rel["source_entity"], rel["target_entity"], rel["data_source"])
        for rel in result.relationships
    }
    assert ("subcontractor_of", "Prime Vendor", "Mercury Systems, Inc.", "sam_subaward_reporting") in relationships
    assert ("subcontractor_of", "Prime Vendor", "L3Harris Technologies, Inc.", "sam_subaward_reporting") in relationships

    titles = [finding.title for finding in result.findings]
    assert any(title.startswith("SAM subcontract reports:") for title in titles)
