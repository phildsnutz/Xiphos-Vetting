import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from osint import enrichment  # noqa: E402


def test_dod_sam_exclusions_timeout_is_not_retried(monkeypatch):
    calls = {"count": 0}

    def fake_run_connector_once(_mod, _vendor_name, _country, _ids, timeout_s=0):
        calls["count"] += 1
        raise TimeoutError(f"Connector timed out after {timeout_s}s")

    monkeypatch.setattr(enrichment, "_run_connector_once", fake_run_connector_once)
    monkeypatch.setattr(enrichment.time, "sleep", lambda *_args, **_kwargs: None)

    with pytest.raises(TimeoutError):
        enrichment._run_connector_with_timeout(
            object(),
            "Boeing",
            "US",
            {},
            connector_name="dod_sam_exclusions",
        )

    assert calls["count"] == 1


def test_standard_connector_still_retries_once(monkeypatch):
    calls = {"count": 0}

    def fake_run_connector_once(_mod, _vendor_name, _country, _ids, timeout_s=0):
        calls["count"] += 1
        raise TimeoutError(f"Connector timed out after {timeout_s}s")

    monkeypatch.setattr(enrichment, "_run_connector_once", fake_run_connector_once)
    monkeypatch.setattr(enrichment.time, "sleep", lambda *_args, **_kwargs: None)

    with pytest.raises(TimeoutError):
        enrichment._run_connector_with_timeout(
            object(),
            "Boeing",
            "US",
            {},
            connector_name="google_news",
        )

    assert calls["count"] == 2
