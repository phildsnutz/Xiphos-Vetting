import os
import sys
from pathlib import Path


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from osint import public_html_contract_vehicle  # noqa: E402


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "vehicle_intelligence" / "public_html"


def test_public_html_contract_vehicle_extracts_lineage_signals_from_fixture_pages():
    result = public_html_contract_vehicle.enrich(
        "ITEAMS",
        contract_vehicle_public_html_fixture_pages=[
            str(FIXTURE_DIR / "iteams_lineage_snapshot.html"),
            str(FIXTURE_DIR / "iteams_archive_notice.html"),
        ],
    )

    assert result.source == "public_html_contract_vehicle"
    assert result.error == ""
    assert len(result.relationships) >= 4
    assert any(
        rel["rel_type"] == "predecessor_of"
        and rel["source_name"] == "IPIESS"
        and rel["target_name"] == "ITEAMS"
        for rel in result.relationships
    )
    assert any(
        rel["rel_type"] == "awarded_under"
        and rel["source_name"] == "OASIS"
        and rel["corroboration_count"] == 2
        for rel in result.relationships
    )
    assert any(rel["rel_type"] == "funded_by" and "USINDOPACOM" in rel["source_name"] for rel in result.relationships)
    assert any(rel["rel_type"] == "performed_at" and "Camp Smith" in rel["source_name"] for rel in result.relationships)
    assert any(finding.title.startswith("Public vehicle signal: predecessor of") for finding in result.findings)


def test_public_html_contract_vehicle_uses_http_trust_and_reports_tls_failure(monkeypatch):
    calls: list[bool | str] = []

    class _FakeResponse:
        status_code = 200
        url = "https://example.test/opportunity"
        text = "<html><body><p>Awarded under OASIS.</p></body></html>"

        def raise_for_status(self):
            return None

    def fake_get(url, headers=None, timeout=None, verify=None):
        assert url == "https://example.test/opportunity"
        assert timeout == public_html_contract_vehicle.TIMEOUT
        calls.append(verify)
        return _FakeResponse()

    monkeypatch.setattr(public_html_contract_vehicle, "_verify_ssl", lambda: "/tmp/test-chain.pem")
    monkeypatch.setattr(public_html_contract_vehicle.requests, "get", fake_get)

    result = public_html_contract_vehicle.enrich(
        "ITEAMS",
        contract_vehicle_pages=["https://example.test/opportunity"],
    )

    assert result.error == ""
    assert calls == ["/tmp/test-chain.pem"]
    assert any(rel["rel_type"] == "awarded_under" and rel["source_name"] == "OASIS" for rel in result.relationships)
