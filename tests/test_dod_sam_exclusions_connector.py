import importlib
import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _load_module():
    if "osint.dod_sam_exclusions" in sys.modules:
        return importlib.reload(sys.modules["osint.dod_sam_exclusions"])
    from osint import dod_sam_exclusions  # type: ignore

    return dod_sam_exclusions


def test_dod_sam_exclusions_builds_small_fast_query_url():
    dod_sam_exclusions = _load_module()

    url = dod_sam_exclusions._build_exclusions_url("Boeing")

    assert "exclusionName=Boeing" in url
    assert "page=0" in url
    assert "size=5" in url


def test_dod_sam_exclusions_get_uses_connector_timeout(monkeypatch):
    dod_sam_exclusions = _load_module()
    monkeypatch.setattr(dod_sam_exclusions, "API_KEY", "test-key")

    captured: dict[str, float] = {}

    def fake_curl_json_get(url, *, headers=None, timeout_seconds=0):
        captured["timeout"] = timeout_seconds
        return None, {"status": 0, "throttled": False, "error": "transport timed out"}

    monkeypatch.setattr(dod_sam_exclusions, "curl_json_get", fake_curl_json_get)

    payload, meta = dod_sam_exclusions._get("https://example.test", timeout_seconds=3.5)

    assert payload is None
    assert captured["timeout"] == 3.5
    assert "unavailable" in meta["error"].lower()


def test_dod_sam_exclusions_unavailable_result_is_honest_and_non_blocking(monkeypatch):
    dod_sam_exclusions = _load_module()
    monkeypatch.setattr(
        dod_sam_exclusions,
        "_get",
        lambda *_args, **_kwargs: (
            None,
            {
                "status": 0,
                "throttled": False,
                "error": "SAM.gov exclusions API unavailable: timed out",
            },
        ),
    )

    result = dod_sam_exclusions.enrich("Boeing", country="US")

    assert result.error == "SAM.gov exclusions API unavailable: timed out"
    assert result.findings[0].title == "DoD EPLS: Unable to verify (API unavailable)"
    assert result.findings[0].severity == "info"
    assert result.findings[0].confidence == 0.3


def test_dod_sam_exclusions_reads_excluded_entity_payload(monkeypatch):
    dod_sam_exclusions = _load_module()
    monkeypatch.setattr(
        dod_sam_exclusions,
        "_get",
        lambda *_args, **_kwargs: (
            {
                "totalRecords": 1,
                "excludedEntity": [
                    {
                        "name": "Boeing Company",
                        "exclusionType": "Procurement",
                        "reason": "Test reason",
                        "excludingAgency": "GSA",
                        "activeDate": "2026-01-01",
                    }
                ],
            },
            {"status": 200, "throttled": False, "error": ""},
        ),
    )

    result = dod_sam_exclusions.enrich("Boeing", country="US")

    assert any(f.title == "DoD EPLS MATCH: Boeing Company" for f in result.findings)
