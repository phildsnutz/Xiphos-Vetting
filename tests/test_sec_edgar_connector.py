import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from osint import sec_edgar


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
