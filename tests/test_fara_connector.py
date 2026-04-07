import importlib
import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _load_module():
    if "osint.fara" in sys.modules:
        return importlib.reload(sys.modules["osint.fara"])
    from osint import fara  # type: ignore

    return fara


def test_fara_fetch_registrants_uses_cache(monkeypatch):
    fara = _load_module()
    monkeypatch.setattr(fara, "_REGISTRANT_CACHE", {})
    monkeypatch.setattr(fara, "REGISTRANT_CACHE_TTL_SECONDS", 3600)

    calls = {"count": 0}

    def fake_get_json(_url):
        calls["count"] += 1
        return {
            "REGISTRANTS_ACTIVE": {
                "ROW": [{"Name": "Acme Systems", "Registration_Number": "123"}]
            }
        }

    monkeypatch.setattr(fara, "_get_json", fake_get_json)

    rows_one = fara._fetch_registrants(fara.ACTIVE_REGISTRANTS)
    rows_two = fara._fetch_registrants(fara.ACTIVE_REGISTRANTS)

    assert calls["count"] == 1
    assert rows_one == rows_two
    assert rows_one[0]["Name"] == "Acme Systems"


def test_fara_enrich_without_match_returns_info_and_skips_principal_fetch(monkeypatch):
    fara = _load_module()
    monkeypatch.setattr(fara, "_REGISTRANT_CACHE", {})
    monkeypatch.setattr(fara, "_fetch_registrants", lambda _url: [])
    monkeypatch.setattr(fara.time, "sleep", lambda *_args, **_kwargs: None)

    result = fara.enrich("Acme Systems", country="US")

    assert result.findings[0].title == "No FARA registrations found"
    assert result.findings[0].severity == "info"


def test_fara_active_match_fetches_principal_with_short_delay(monkeypatch):
    fara = _load_module()
    monkeypatch.setattr(fara, "_REGISTRANT_CACHE", {})
    monkeypatch.setattr(
        fara,
        "_fetch_registrants",
        lambda url: (
            [{"Name": "Acme Systems", "Registration_Number": "123", "Registration_Date": "2024-01-01"}]
            if url == fara.ACTIVE_REGISTRANTS
            else []
        ),
    )

    delays = []
    monkeypatch.setattr(fara.time, "sleep", lambda seconds: delays.append(seconds))
    monkeypatch.setattr(
        fara,
        "_get_json",
        lambda url: {"ROWSET": {"ROW": {"FP_NAME": "Example Principal", "COUNTRY_NAME": "Canada"}}}
        if url == fara.ACTIVE_FP_TEMPLATE.format(reg_num="123")
        else {},
    )

    result = fara.enrich("Acme Systems", country="US")

    assert any(f.title.startswith("FARA: Acme Systems") for f in result.findings)
    assert delays == [fara.RATE_LIMIT_DELAY_SECONDS]
