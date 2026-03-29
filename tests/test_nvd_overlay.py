import importlib
import json
import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_nvd_get(url, params=None, headers=None, timeout=0):
    params = params or {}
    if "cpes/2.0" in url:
        keyword = str(params.get("keywordSearch") or "").lower()
        if "secure portal" in keyword:
            return _FakeResponse(
                {
                    "products": [
                        {
                            "cpe": {
                                "cpeName": "cpe:2.3:a:acme:secure_portal:1.0:*:*:*:*:*:*:*",
                                "titles": [{"lang": "en", "title": "Acme Secure Portal 1.0"}],
                            }
                        }
                    ]
                }
            )
        return _FakeResponse({"products": []})

    if "cves/2.0" in url:
        cpe_name = str(params.get("cpeName") or "")
        if "secure_portal" in cpe_name:
            return _FakeResponse(
                {
                    "vulnerabilities": [
                        {
                            "cve": {
                                "id": "CVE-2026-0001",
                                "published": "2026-01-10T00:00:00.000",
                                "descriptions": [{"lang": "en", "value": "Remote code execution vulnerability."}],
                                "metrics": {
                                    "cvssMetricV31": [
                                        {"cvssData": {"baseScore": 9.8, "baseSeverity": "CRITICAL"}}
                                    ]
                                },
                                "cisaExploitAdd": "2026-02-01",
                            }
                        },
                        {
                            "cve": {
                                "id": "CVE-2025-1111",
                                "published": "2025-12-05T00:00:00.000",
                                "descriptions": [{"lang": "en", "value": "Privilege escalation vulnerability."}],
                                "metrics": {
                                    "cvssMetricV31": [
                                        {"cvssData": {"baseScore": 7.5, "baseSeverity": "HIGH"}}
                                    ]
                                },
                            }
                        },
                    ]
                }
            )
        return _FakeResponse({"vulnerabilities": []})

    raise AssertionError(f"Unexpected NVD URL: {url}")


@pytest.fixture
def nvd_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    for module_name in ["runtime_paths", "db", "artifact_vault", "nvd_overlay"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import db  # type: ignore
    import nvd_overlay  # type: ignore

    db.init_db()
    db.upsert_vendor(
        vendor_id="case-nvd-1",
        name="Cyber Product Vendor",
        country="US",
        program="dod_unclassified",
        vendor_input={"name": "Cyber Product Vendor", "country": "US", "program": "dod_unclassified"},
        profile="defense_acquisition",
    )
    monkeypatch.setattr(nvd_overlay.requests, "get", _fake_nvd_get)
    return {"db": db, "nvd_overlay": nvd_overlay}


def test_build_nvd_overlay_summarizes_cves_and_kev_flags(nvd_env):
    nvd_overlay = nvd_env["nvd_overlay"]

    payload = nvd_overlay.build_nvd_overlay("Cyber Product Vendor", ["Secure Portal"])

    summary = payload["summary"]
    assert summary["product_terms"] == ["Secure Portal"]
    assert summary["matched_terms"] == 1
    assert summary["unique_cve_count"] == 2
    assert summary["high_or_critical_cve_count"] == 2
    assert summary["critical_cve_count"] == 1
    assert summary["kev_flagged_cve_count"] == 1
    assert payload["product_summaries"][0]["matched_cpes_count"] == 1
    assert payload["top_cves"][0]["cve_id"] == "CVE-2026-0001"


def test_create_nvd_overlay_artifact_persists_generated_overlay(nvd_env):
    nvd_overlay = nvd_env["nvd_overlay"]

    record = nvd_overlay.create_nvd_overlay_artifact(
        "case-nvd-1",
        "Cyber Product Vendor",
        ["Secure Portal"],
        uploaded_by="analyst-1",
    )

    assert record["artifact_type"] == "nvd_overlay"
    assert record["source_system"] == "nvd_overlay"
    assert record["source_class"] == "public_connector"
    assert record["authority_level"] == "official_regulatory"
    assert record["access_model"] == "public_api"
    assert record["structured_fields"]["summary"]["unique_cve_count"] == 2

    payload = json.loads(open(record["artifact_path"], "r", encoding="utf-8").read())
    assert payload["summary"]["kev_flagged_cve_count"] == 1
    assert payload["product_terms"] == ["Secure Portal"]
