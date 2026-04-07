import importlib
import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _load_module():
    if "osint.careers_scraper" in sys.modules:
        return importlib.reload(sys.modules["osint.careers_scraper"])
    from osint import careers_scraper  # type: ignore

    return careers_scraper


def test_careers_scraper_skips_company_guessing_without_website(monkeypatch):
    careers_scraper = _load_module()
    monkeypatch.setattr(careers_scraper, "ENABLE_COMPANY_GUESSING", False)

    session = object()
    called = {"count": 0}

    def fake_safe_get(*_args, **_kwargs):
        called["count"] += 1
        return None

    monkeypatch.setattr(careers_scraper, "_safe_get", fake_safe_get)

    posts = careers_scraper._scrape_company_careers(session, "Acme Systems", "")

    assert posts == []
    assert called["count"] == 0


def test_careers_scraper_limits_company_career_candidates(monkeypatch):
    careers_scraper = _load_module()
    monkeypatch.setattr(careers_scraper, "ENABLE_COMPANY_GUESSING", True)
    monkeypatch.setattr(careers_scraper, "MAX_COMPANY_CAREERS_CANDIDATES", 2)

    seen_urls: list[str] = []

    def fake_safe_get(_session, url, **_kwargs):
        seen_urls.append(url)
        return None

    monkeypatch.setattr(careers_scraper, "_safe_get", fake_safe_get)

    careers_scraper._scrape_company_careers(object(), "Acme Systems", "")

    assert len(seen_urls) == 2


def test_careers_scraper_uses_sam_website_when_present(monkeypatch):
    careers_scraper = _load_module()
    monkeypatch.setattr(careers_scraper, "ENABLE_CLEARANCEJOBS", False)
    monkeypatch.setattr(careers_scraper, "ENABLE_INDEED", False)
    monkeypatch.setattr(careers_scraper, "_sleep_if_needed", lambda: None)
    monkeypatch.setattr(careers_scraper, "_get_session", lambda: object())

    captured = {}

    def fake_company_careers(_session, _vendor_name, website=""):
        captured["website"] = website
        return []

    monkeypatch.setattr(careers_scraper, "_scrape_company_careers", fake_company_careers)

    result = careers_scraper.enrich("Acme Systems", sam_website="sam.gov/entity/ABC123")

    assert captured["website"] == "sam.gov/entity/ABC123"
    assert result.findings[0].title == "No job postings found for 'Acme Systems'"


def test_careers_scraper_defaults_disable_indeed(monkeypatch):
    careers_scraper = _load_module()
    monkeypatch.setattr(careers_scraper, "ENABLE_CLEARANCEJOBS", False)
    monkeypatch.setattr(careers_scraper, "ENABLE_INDEED", False)
    monkeypatch.setattr(careers_scraper, "_sleep_if_needed", lambda: None)
    monkeypatch.setattr(careers_scraper, "_get_session", lambda: object())
    monkeypatch.setattr(careers_scraper, "_scrape_company_careers", lambda *_args, **_kwargs: [])

    called = {"indeed": 0}

    def fake_indeed(*_args, **_kwargs):
        called["indeed"] += 1
        return []

    monkeypatch.setattr(careers_scraper, "_scrape_indeed", fake_indeed)

    careers_scraper.enrich("Acme Systems")

    assert called["indeed"] == 0
