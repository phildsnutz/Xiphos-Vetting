from __future__ import annotations

import urllib.parse

from backend.osint import gdelt_media


def test_gdelt_media_parallel_aux_queries_still_populates_tone_and_country_signals(monkeypatch):
    calls: list[str] = []

    def fake_get(url: str, retries: int = 2, timeout_s: int = gdelt_media.REQUEST_TIMEOUT):
        calls.append(url)
        if "mode=ArtList" in url and "(sanctions" in urllib.parse.unquote(url):
            return {
                "articles": [
                    {
                        "url": "https://example.test/risk",
                        "title": "Vector Mission Software fraud investigation expands",
                        "seendate": "2026-03-30",
                        "domain": "reuters.com",
                        "language": "English",
                    }
                ]
            }
        if "mode=ToneChart" in url:
            return {"tonechart": [{"tone": -6.0}, {"tone": -6.0}]}
        if "mode=TimelineSourceCountry" in url:
            return {
                "timeline": [
                    {"series": "United States", "data": [{"value": 7}]},
                    {"series": "China", "data": [{"value": 4}]},
                ]
            }
        raise AssertionError(f"unexpected gdelt url: {url}")

    monkeypatch.setattr(gdelt_media, "_get", fake_get)
    monkeypatch.setattr(gdelt_media, "_ml_available", False)
    monkeypatch.setattr(gdelt_media, "_ml_classify", None)

    result = gdelt_media.enrich("Vector Mission Software", country="US")

    assert result.identifiers["gdelt_avg_tone"] == -6.0
    assert result.identifiers["gdelt_tone_sample_size"] == 2
    assert result.identifiers["gdelt_coverage_countries"]["United States"] == 7
    assert any(signal["signal"] == "adverse_media_coverage" for signal in result.risk_signals)
    assert any(signal["signal"] == "strongly_negative_media_tone" for signal in result.risk_signals)
    assert any("mode=ToneChart" in url for url in calls)
    assert any("mode=TimelineSourceCountry" in url for url in calls)


def test_gdelt_media_skips_aux_queries_when_risk_query_returns_no_articles(monkeypatch):
    calls: list[str] = []

    def fake_get(url: str, retries: int = 2, timeout_s: int = gdelt_media.REQUEST_TIMEOUT):
        calls.append(url)
        if "mode=ArtList" in url and "(sanctions" in urllib.parse.unquote(url):
            return {"articles": []}
        raise AssertionError(f"unexpected gdelt url: {url}")

    monkeypatch.setattr(gdelt_media, "_get", fake_get)
    monkeypatch.setattr(gdelt_media, "_ml_available", False)
    monkeypatch.setattr(gdelt_media, "_ml_classify", None)

    result = gdelt_media.enrich("Vector Mission Software", country="US")

    assert result.findings[0].title == "No adverse media found"
    assert all("mode=ToneChart" not in url for url in calls)
    assert all("mode=TimelineSourceCountry" not in url for url in calls)
