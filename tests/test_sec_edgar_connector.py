import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from osint import EnrichmentResult, sec_edgar


def test_sec_edgar_does_not_mark_public_for_unvalidated_search_hits(monkeypatch):
    def fake_get(_url: str):
        return {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "ciks": ["0001535778"],
                            "display_names": ["MSC Income Fund, Inc."],
                            "company_name": "MSC Income Fund, Inc.",
                            "file_date": "2023-05-12",
                            "form": "10-Q",
                            "file_num": "814-00939",
                        }
                    },
                    {
                        "_source": {
                            "ciks": ["0001396440"],
                            "display_names": ["Main Street Capital CORP"],
                            "company_name": "Main Street Capital CORP",
                            "file_date": "2023-05-05",
                            "form": "10-Q",
                            "file_num": "814-00746",
                        }
                    },
                ]
            }
        }

    monkeypatch.setattr(sec_edgar, "_get", fake_get)
    monkeypatch.setattr(sec_edgar, "_deep_parse_company", lambda *_args, **_kwargs: None)

    result = sec_edgar.enrich("Berry Aviation Inc", country="US")

    assert result.identifiers.get("publicly_traded") is not True
    assert result.identifiers.get("cik_confidence") != "high"


def test_sec_edgar_marks_public_for_validated_company_match(monkeypatch):
    def fake_get(url: str):
        if "search-index" in url:
            return {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "ciks": ["0000936468"],
                                "display_names": ["Lockheed Martin Corp"],
                                "company_name": "Lockheed Martin Corp",
                                "file_date": "2025-01-28",
                                "form": "10-K",
                                "file_num": "001-11437",
                            }
                        }
                    ]
                }
            }
        return {"name": "Lockheed Martin Corp"}

    monkeypatch.setattr(sec_edgar, "_get", fake_get)

    result = sec_edgar.enrich("Lockheed Martin Corporation", country="US")

    assert result.identifiers.get("cik") == "936468"
    assert result.identifiers.get("cik_confidence") == "high"
    assert result.identifiers.get("publicly_traded") is True


def test_sec_edgar_parse_financing_document_extracts_credit_counterparties():
    text = """
    <DOCUMENT><TYPE>EX-10<TEXT>
    CREDIT AGREEMENT dated as of March 1, 2026 among Example Defense Systems, Inc.
    and JPMorgan Chase Bank, N.A., as administrative agent and lender.
    The receivables are processed through Wells Fargo Bank, National Association.
    </TEXT></DOCUMENT>
    """

    relationships = sec_edgar._parse_financing_document(text, "Example Defense Systems, Inc.")

    rel_types = {(item["type"], item["target_entity"]) for item in relationships}
    assert ("backed_by", "JPMorgan Chase Bank, N.A.") in rel_types
    assert ("routes_payment_through", "Wells Fargo Bank, National Association") in rel_types


def test_sec_edgar_parse_financing_document_extracts_account_bank_and_deposit_bank():
    text = """
    <DOCUMENT><TYPE>EX-10<TEXT>
    This CREDIT AGREEMENT is entered into with Citibank, N.A., as account bank and paying agent.
    The concentration account is maintained at Bank of America, N.A.
    </TEXT></DOCUMENT>
    """

    relationships = sec_edgar._parse_financing_document(text, "Example Defense Systems, Inc.")

    rel_types = {(item["type"], item["target_entity"]) for item in relationships}
    assert ("routes_payment_through", "Citibank, N.A.") in rel_types
    assert ("routes_payment_through", "Bank of America, N.A.") in rel_types


def test_sec_edgar_deep_parse_extracts_ex10_financing_relationships(monkeypatch):
    def fake_get(url: str):
        if url.endswith("CIK0000936468.json"):
            return {
                "name": "Lockheed Martin Corp",
                "filings": {
                    "recent": {
                        "form": ["8-K"],
                        "filingDate": ["2026-02-14"],
                        "accessionNumber": ["0000936468-26-000001"],
                    }
                },
            }
        if url.endswith("/index.json"):
            return {
                "directory": {
                    "item": [
                        {"name": "ex10-credit-agreement.htm"},
                    ]
                }
            }
        return None

    monkeypatch.setattr(sec_edgar, "_get", fake_get)
    monkeypatch.setattr(
        sec_edgar,
        "_fetch_text",
        lambda _url: """
        <DOCUMENT><TYPE>EX-10<TEXT>
        This CREDIT AGREEMENT is entered into with PNC Bank, National Association, as administrative agent.
        </TEXT></DOCUMENT>
        """,
    )

    result = EnrichmentResult(source="sec_edgar", vendor_name="Lockheed Martin Corporation")
    sec_edgar._deep_parse_company("936468", "Lockheed Martin Corporation", result)

    assert any(rel["type"] == "backed_by" and rel["target_entity"] == "PNC Bank, National Association" for rel in result.relationships)
    assert any("financing counterparties" in finding.title.lower() for finding in result.findings)
