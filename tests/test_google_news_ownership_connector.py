from pathlib import Path


class _Response:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


def test_google_news_emits_owned_by_from_rss_title(monkeypatch):
    from backend.osint import google_news

    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "rss_public_ownership"
        / "google_news_acquisition_feed.xml"
    ).read_bytes()

    monkeypatch.setattr(google_news.requests, "get", lambda *args, **kwargs: _Response(fixture))

    result = google_news.enrich("Greensea IQ", country="US")

    ownership_findings = [finding for finding in result.findings if finding.category == "ownership"]
    assert len(ownership_findings) == 1
    assert ownership_findings[0].title == "Media-reported ownership link: Northwind Holdings"
    assert ownership_findings[0].access_model == "rss_public"

    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert relationship["type"] == "owned_by"
    assert relationship["source_entity"] == "Greensea IQ"
    assert relationship["target_entity"] == "Northwind Holdings"
    assert relationship["structured_fields"]["relationship_scope"] == "media_reported_control"
    assert relationship["structured_fields"]["detection_method"] == "rss_title_acquires_vendor"


def test_google_news_emits_backed_by_from_alias_aware_rss_title(monkeypatch):
    from backend.osint import google_news

    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "rss_public_ownership"
        / "google_news_finance_feed.xml"
    ).read_bytes()

    monkeypatch.setattr(google_news.requests, "get", lambda *args, **kwargs: _Response(fixture))

    result = google_news.enrich("HTL / Herrick Technology Laboratories Inc", country="US")

    finance_findings = [finding for finding in result.findings if finding.category == "finance"]
    assert len(finance_findings) == 1
    assert finance_findings[0].title == "Media-reported financial backer: Blue Delta"
    assert finance_findings[0].access_model == "rss_public"

    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert relationship["type"] == "backed_by"
    assert relationship["source_entity"] == "HTL / Herrick Technology Laboratories Inc"
    assert relationship["target_entity"] == "Blue Delta"
    assert relationship["structured_fields"]["relationship_scope"] == "media_reported_financing"
    assert relationship["structured_fields"]["detection_method"] == "rss_title_backed_vendor"


def test_google_news_recovers_acquisition_titles_with_region_suffix_and_descriptor(monkeypatch):
    from backend.osint import google_news

    fixture = b"""
    <rss><channel>
      <item>
        <title>Codan to acquire Herndon-based Domo Tactical Communications</title>
        <link>https://example.test/domo-codan</link>
        <pubDate>Fri, 28 Mar 2026 10:00:00 GMT</pubDate>
        <source>Virginia Business</source>
      </item>
    </channel></rss>
    """

    monkeypatch.setattr(google_news.requests, "get", lambda *args, **kwargs: _Response(fixture))

    result = google_news.enrich("DOMO Tactical Communications US", country="US")

    ownership_findings = [finding for finding in result.findings if finding.category == "ownership"]
    assert len(ownership_findings) == 1
    assert ownership_findings[0].title == "Media-reported ownership link: Codan"

    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert relationship["type"] == "owned_by"
    assert relationship["source_entity"] == "DOMO Tactical Communications US"
    assert relationship["target_entity"] == "Codan"
    assert relationship["structured_fields"]["detection_method"] == "rss_title_acquires_vendor"
