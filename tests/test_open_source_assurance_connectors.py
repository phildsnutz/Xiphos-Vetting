from __future__ import annotations

import importlib
import os
import sys
import time


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_osv_connector_surfaces_package_advisories(monkeypatch):
    from osint import osv_dev

    monkeypatch.setattr(
        osv_dev,
        "_post_json",
        lambda _url, _payload: {
            "results": [
                {"vulns": [{"id": "OSV-2026-0001"}, {"id": "OSV-2026-0002"}]},
                {"vulns": []},
            ]
        },
    )

    result = osv_dev.enrich(
        "Horizon Mission Systems LLC",
        "US",
        package_inventory=[
            {"ecosystem": "PyPI", "name": "telemetry-core", "version": "2.4.1"},
            {"ecosystem": "npm", "name": "@horizon/ground-station", "version": "7.2.0"},
        ],
    )

    assert result.has_data
    summary = result.structured_fields["summary"]
    assert summary["osv_vulnerability_count"] == 2
    assert summary["osv_advisory_ids"] == ["OSV-2026-0001", "OSV-2026-0002"]


def test_deps_dev_connector_maps_repositories_and_attestations(monkeypatch):
    from osint import deps_dev

    monkeypatch.setattr(
        deps_dev,
        "_get_json",
        lambda _url: {
            "advisoryKeys": [{"id": "OSV-2026-0001"}],
            "relatedProjects": [{"projectKey": {"id": "github.com/horizon-mission/telemetry-core"}}],
            "attestations": [{"verified": True}],
            "slsaProvenances": [{"verified": True}],
            "links": [{"label": "repository", "url": "https://github.com/horizon-mission/telemetry-core"}],
        },
    )

    result = deps_dev.enrich(
        "Horizon Mission Systems LLC",
        "US",
        package_inventory=[
            {"ecosystem": "PyPI", "name": "telemetry-core", "version": "2.4.1"},
        ],
    )

    assert result.has_data
    assert result.identifiers["repository_urls"] == ["https://github.com/horizon-mission/telemetry-core"]
    summary = result.structured_fields["summary"]
    assert summary["deps_dev_advisory_count"] == 1
    assert summary["deps_dev_verified_attestations"] == 1
    assert summary["deps_dev_verified_slsa_provenances"] == 1


def test_scorecard_connector_surfaces_repo_hygiene(monkeypatch):
    from osint import openssf_scorecard

    monkeypatch.setattr(
        openssf_scorecard,
        "_get_json",
        lambda _url: {
            "score": 6.4,
            "date": "2026-03-28",
            "checks": [
                {"name": "Branch-Protection", "score": 2},
                {"name": "Pinned-Dependencies", "score": 4},
            ],
        },
    )

    result = openssf_scorecard.enrich(
        "Horizon Mission Systems LLC",
        "US",
        repository_urls=["https://github.com/horizon-mission/telemetry-core"],
    )

    assert result.has_data
    summary = result.structured_fields["summary"]
    assert summary["repository_count"] == 1
    assert summary["scorecard_low_repo_count"] == 1
    assert summary["scorecard_repo_scores"][0]["critical_checks"] == [
        "Branch-Protection",
        "Pinned-Dependencies",
    ]


def test_cyber_summary_merges_open_source_assurance_signals(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))

    import db
    import cyber_evidence

    importlib.reload(db)
    importlib.reload(cyber_evidence)

    db.init_db()
    db.upsert_vendor(
        "case-open-source-assurance",
        "Horizon Mission Systems LLC",
        "US",
        "dod_unclassified",
        {},
    )

    from osint.public_assurance_evidence_fixture import enrich as public_assurance_enrich
    from osint.osv_dev import enrich as osv_enrich
    from osint.deps_dev import enrich as deps_enrich
    from osint.openssf_scorecard import enrich as scorecard_enrich
    from osint import enrichment as enrichment_mod

    monkeypatch.setattr(
        sys.modules["osint.osv_dev"],
        "_post_json",
        lambda _url, _payload: {"results": [{"vulns": [{"id": "OSV-2026-0001"}]}, {"vulns": []}]},
    )
    monkeypatch.setattr(
        sys.modules["osint.deps_dev"],
        "_get_json",
        lambda _url: {
            "advisoryKeys": [{"id": "OSV-2026-0001"}],
            "relatedProjects": [{"projectKey": {"id": "github.com/horizon-mission/telemetry-core"}}],
            "attestations": [{"verified": True}],
            "slsaProvenances": [{"verified": True}],
            "links": [{"label": "repository", "url": "https://github.com/horizon-mission/telemetry-core"}],
        },
    )
    monkeypatch.setattr(
        sys.modules["osint.openssf_scorecard"],
        "_get_json",
        lambda _url: {
            "score": 6.4,
            "date": "2026-03-28",
            "checks": [{"name": "Branch-Protection", "score": 2}],
        },
    )

    package_inventory = [
        {"ecosystem": "PyPI", "name": "telemetry-core", "version": "2.4.1"},
        {"ecosystem": "npm", "name": "@horizon/ground-station", "version": "7.2.0"},
    ]
    repository_urls = ["https://github.com/horizon-mission/telemetry-core"]
    report = enrichment_mod._build_report(
        "Horizon Mission Systems LLC",
        "US",
        [
            public_assurance_enrich("Horizon Mission Systems LLC", "US"),
            osv_enrich("Horizon Mission Systems LLC", "US", package_inventory=package_inventory),
            deps_enrich("Horizon Mission Systems LLC", "US", package_inventory=package_inventory),
            scorecard_enrich("Horizon Mission Systems LLC", "US", repository_urls=repository_urls),
        ],
        time.time(),
    )
    db.save_enrichment("case-open-source-assurance", report)

    summary = cyber_evidence.get_latest_cyber_evidence_summary("case-open-source-assurance")

    assert summary is not None
    assert summary["package_inventory_present"] is True
    assert summary["package_inventory_count"] == 2
    assert summary["open_source_advisory_count"] == 1
    assert summary["scorecard_low_repo_count"] == 1
    assert summary["open_source_risk_level"] == "high"
    assert "osv_dev" in summary["artifact_sources"]
    assert "deps_dev" in summary["artifact_sources"]
    assert "openssf_scorecard" in summary["artifact_sources"]
