import os
import sys
from pathlib import Path


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from osint import gao_bid_protests_public  # noqa: E402


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "vehicle_intelligence" / "gao_public"


def test_gao_public_connector_parses_docket_fixture():
    result = gao_bid_protests_public.enrich(
        "ITEAMS",
        gao_public_html_fixture_pages=[str(FIXTURE_DIR / "gao_docket_iteams_fixture.html")],
    )

    assert result.source == "gao_bid_protests_public"
    assert result.error == ""
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.raw_data["page_type"] == "docket"
    assert finding.raw_data["status"] == "dismissed"
    assert finding.raw_data["protester"] == "Leidos, Inc."
    assert finding.raw_data["solicitation_number"] == "N66001-24-R-0012"
    assert finding.raw_data["agency"].startswith("Department of the Navy")


def test_gao_public_connector_parses_decision_fixture():
    result = gao_bid_protests_public.enrich(
        "ITEAMS",
        gao_public_html_fixture_pages=[str(FIXTURE_DIR / "gao_decision_iteams_fixture.html")],
    )

    assert result.error == ""
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.raw_data["page_type"] == "decision"
    assert finding.raw_data["status"] == "denied"
    assert finding.raw_data["event_id"] == "B-422999.1"
    assert "bridge and transition evaluation is denied" in finding.detail


def test_gao_public_connector_returns_honest_disabled_message_for_live_urls(monkeypatch):
    monkeypatch.delenv("XIPHOS_ENABLE_GAO_BROWSER_CAPTURE", raising=False)

    result = gao_bid_protests_public.enrich(
        "ITEAMS",
        gao_public_urls=["https://www.gao.gov/docket/b-422818.1"],
    )

    assert result.findings == []
    assert "live GAO browser capture is disabled" in result.error
    assert result.structured_fields["live_capture_enabled"] is False


def test_gao_public_connector_uses_live_capture_when_enabled(monkeypatch):
    monkeypatch.setenv("XIPHOS_ENABLE_GAO_BROWSER_CAPTURE", "1")
    fixture_path = FIXTURE_DIR / "gao_docket_iteams_fixture.html"

    def fake_capture(url: str, **_kwargs):
        return fixture_path.read_text(encoding="utf-8"), url

    monkeypatch.setattr(gao_bid_protests_public, "capture_rendered_html", fake_capture)

    result = gao_bid_protests_public.enrich(
        "ITEAMS",
        gao_public_urls=["https://www.gao.gov/docket/b-422818.1"],
    )

    assert result.error == ""
    assert len(result.findings) == 1
    assert result.findings[0].raw_data["status"] == "dismissed"
    assert result.structured_fields["live_capture_enabled"] is True
