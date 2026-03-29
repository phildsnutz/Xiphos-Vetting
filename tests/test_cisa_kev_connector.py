from __future__ import annotations

from backend.osint import cisa_kev


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_cisa_kev_ignores_generic_systems_group_overlap(monkeypatch):
    payload = {
        "vulnerabilities": [
            {
                "cveID": "CVE-2026-25108",
                "vendorProject": "Soliton Systems K.K.",
                "product": "FileZen",
                "vulnerabilityName": "OS Command Injection",
                "dateAdded": "2026-03-01",
                "dueDate": "2026-03-21",
                "shortDescription": "Example",
            }
        ]
    }

    monkeypatch.setattr(cisa_kev.requests, "get", lambda *args, **kwargs: _FakeResponse(payload))

    result = cisa_kev.enrich("Yorktown Systems Group", country="US")

    assert result.findings[0].title == "CISA KEV: No known exploited vulnerabilities found"
    assert "kev_matches" not in result.identifiers


def test_cisa_kev_matches_on_informative_vendor_token(monkeypatch):
    payload = {
        "vulnerabilities": [
            {
                "cveID": "CVE-2026-25108",
                "vendorProject": "Soliton Systems K.K.",
                "product": "FileZen",
                "vulnerabilityName": "OS Command Injection",
                "dateAdded": "2026-03-01",
                "dueDate": "2026-03-21",
                "shortDescription": "Example",
            }
        ]
    }

    monkeypatch.setattr(cisa_kev.requests, "get", lambda *args, **kwargs: _FakeResponse(payload))

    result = cisa_kev.enrich("Soliton Systems", country="JP")

    assert result.identifiers["kev_matches"] == 1
    assert result.findings[0].title == "CISA KEV: 1 known exploited vulnerabilities found"
