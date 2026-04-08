from __future__ import annotations

from pathlib import Path

from backend.osint import rss_public


class _Response:
    def __init__(self, content: bytes, *, content_type: str = "application/xml", url: str = "https://vector.example/feed.xml"):
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.url = url

    def raise_for_status(self):
        return None


def test_rss_public_fixture_extracts_contract_and_assurance_signals():
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "rss_public" / "vector_mission_feed.xml"

    result = rss_public.enrich(
        "Vector Mission Systems",
        country="US",
        rss_public_fixture_path=fixture_path.as_uri(),
        rss_public_fixture_only=True,
    )

    assert result.identifiers["rss_public_feed_title"] == "Vector Mission Systems Newsroom"
    assert result.identifiers["rss_public_latest_item_at"] == "2026-04-01T15:00:00Z"
    assert result.identifiers["rss_public_feed_url"].startswith("file://")
    assert len(result.structured_fields["items"]) == 3

    titles = [finding.title for finding in result.findings]
    assert any(title.startswith("First-party contract activity:") for title in titles)
    assert any(title.startswith("First-party assurance signal:") for title in titles)
    assert any(signal["signal"] == "first_party_contract_activity" for signal in result.risk_signals)
    assert any(signal["signal"] == "first_party_assurance_activity" for signal in result.risk_signals)


def test_rss_public_discovers_feed_from_homepage(monkeypatch):
    homepage = b"""
    <html>
      <head>
        <link rel="alternate" type="application/rss+xml" title="News feed" href="/news/feed.xml" />
      </head>
      <body>Vector Mission Systems</body>
    </html>
    """
    fixture_feed = (
        Path(__file__).resolve().parents[1] / "fixtures" / "rss_public" / "vector_mission_feed.xml"
    ).read_bytes()

    def fake_get(url: str, timeout: int = rss_public.TIMEOUT, headers: dict | None = None):
        if url == "https://vector.example":
            return _Response(homepage, content_type="text/html; charset=utf-8", url=url)
        if url == "https://vector.example/news/feed.xml":
            return _Response(fixture_feed, content_type="application/rss+xml", url=url)
        raise AssertionError(f"unexpected rss_public url: {url}")

    monkeypatch.setattr(rss_public.requests, "get", fake_get)

    result = rss_public.enrich("Vector Mission Systems", country="US", website="https://vector.example")

    assert result.identifiers["rss_public_feed_url"] == "https://vector.example/news/feed.xml"
    assert result.identifiers["rss_public_feed_title"] == "Vector Mission Systems Newsroom"
    assert any(finding.category == "contracts" for finding in result.findings)
