import importlib
import os
import sys
import time

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        import server  # type: ignore
        server = sys.modules["server"]

    server.db.init_db()
    server.db.migrate_intelligence_tables()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    import hardening
    hardening.reset_rate_limiter()

    with server.app.test_client() as test_client:
        yield test_client


def _create_case(client, name="Acme Corp", country="US"):
    resp = client.post(
        "/api/cases",
        json={
            "name": name,
            "country": country,
            "ownership": {
                "publicly_traded": True,
                "state_owned": False,
                "beneficial_owner_known": True,
                "ownership_pct_resolved": 0.9,
                "shell_layers": 0,
                "pep_connection": False,
            },
            "data_quality": {
                "has_lei": True,
                "has_cage": True,
                "has_duns": True,
                "has_tax_id": True,
                "has_audited_financials": True,
                "years_of_records": 10,
            },
            "exec": {
                "known_execs": 5,
                "adverse_media": 0,
                "pep_execs": 0,
                "litigation_history": 0,
            },
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
        },
    )
    assert resp.status_code == 201
    return resp.get_json()["case_id"]


def _sample_report(name="Acme Corp"):
    return {
        "vendor_name": name,
        "country": "US",
        "overall_risk": "HIGH",
        "summary": {
            "findings_total": 3,
            "critical": 1,
            "high": 1,
            "medium": 1,
            "connectors_run": 3,
            "connectors_with_data": 3,
            "errors": 0,
        },
        "identifiers": {"uei": "ABC123"},
        "findings": [
            {
                "finding_id": "find-sanction-1",
                "source": "trade_csl",
                "category": "sanctions",
                "title": "Restricted party listing hit",
                "detail": "Entity appears on a restricted party screening list.",
                "severity": "critical",
                "confidence": 0.95,
                "url": "https://example.test/restricted-party",
            },
            {
                "finding_id": "find-lawsuit-1",
                "source": "courtlistener",
                "category": "litigation",
                "title": "Civil action filed in 2022",
                "detail": "Contract dispute complaint remains active in federal court.",
                "severity": "high",
                "confidence": 0.88,
                "url": "https://example.test/lawsuit",
            },
            {
                "finding_id": "find-fara-1",
                "source": "fara",
                "category": "registration",
                "title": "FARA registration terminated",
                "detail": "Foreign agent registration terminated in 2021.",
                "severity": "medium",
                "confidence": 0.71,
                "url": "https://example.test/fara",
            },
        ],
        "connector_status": {
            "trade_csl": {"has_data": True, "findings_count": 1, "elapsed_ms": 5, "error": None},
            "courtlistener": {"has_data": True, "findings_count": 1, "elapsed_ms": 6, "error": None},
            "fara": {"has_data": True, "findings_count": 1, "elapsed_ms": 4, "error": None},
        },
        "relationships": [],
        "risk_signals": [],
        "errors": [],
        "total_elapsed_ms": 15,
    }


def test_build_report_assigns_stable_finding_ids(monkeypatch):
    from osint import EnrichmentResult, Finding
    from osint import enrichment

    results = [
        EnrichmentResult(
            source="courtlistener",
            vendor_name="Stable Vendor",
            findings=[
                Finding(
                    source="courtlistener",
                    category="litigation",
                    title="Civil action filed",
                    detail="Complaint filed in 2022",
                    severity="high",
                    confidence=0.8,
                    url="https://example.test/case",
                )
            ],
            elapsed_ms=5,
        )
    ]

    report_a = enrichment._build_report("Stable Vendor", "US", results, time.time())
    report_b = enrichment._build_report("Stable Vendor", "US", results, time.time())

    assert report_a["findings"][0]["finding_id"]
    assert report_a["findings"][0]["finding_id"] == report_b["findings"][0]["finding_id"]
    assert report_a["report_hash"] == report_b["report_hash"]


def test_event_extraction_normalizes_key_findings():
    from event_extraction import extract_case_events

    report = _sample_report()
    events = extract_case_events("case-123", "Acme Corp", report)
    event_types = {event["event_type"] for event in events}

    assert "sanctions_hit" in event_types
    assert "lawsuit" in event_types
    assert "terminated_registration" in event_types


def test_intel_summary_async_enqueues_job(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Intel Queue Vendor")
    report = _sample_report("Intel Queue Vendor")
    server.db.save_enrichment(case_id, report)

    monkeypatch.setattr(server, "get_ai_config_row", lambda user_id: {"provider": "openai", "model": "gpt-4o"})
    monkeypatch.setattr(server, "compute_report_hash", lambda _report: "report-hash-1")
    monkeypatch.setattr(server.db, "get_latest_intel_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        server,
        "enqueue_intel_summary_job",
        lambda *args, **kwargs: {
            "created": True,
            "job": {
                "id": "intel-job-123",
                "status": "pending",
                "report_hash": "report-hash-1",
                "created_at": "2026-03-19T00:00:00Z",
                "started_at": None,
                "completed_at": None,
                "error": None,
            },
        },
    )

    started = {}

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            started["target"] = target
            started["args"] = args

        def start(self):
            started["started"] = True

    monkeypatch.setattr(server.threading, "Thread", FakeThread)

    resp = client.post(f"/api/cases/{case_id}/intel-summary-async", json={})
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["status"] == "pending"
    assert body["job_id"] == "intel-job-123"
    assert started["started"] is True


def test_intel_summary_status_returns_cached_summary(client):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Intel Cached Vendor")
    report = _sample_report("Intel Cached Vendor")
    server.db.save_enrichment(case_id, report)
    server.db.replace_case_events(case_id, report["report_hash"], [])
    server.db.save_intel_summary(
        case_id=case_id,
        user_id="dev",
        report_hash=report["report_hash"],
        summary={
            "items": [
                {
                    "title": "Restricted-party exposure",
                    "assessment": "Trade CSL produced a restricted-party hit.",
                    "status": "active",
                    "severity": "critical",
                    "confidence": 0.93,
                    "source_finding_ids": ["find-sanction-1"],
                    "connectors": ["trade_csl"],
                    "recommended_action": "Escalate for sanctions review.",
                }
            ],
            "stats": {"citation_coverage": 1.0, "finding_count_considered": 3},
        },
        provider="openai",
        model="gpt-4o",
        prompt_tokens=10,
        completion_tokens=20,
        elapsed_ms=300,
        prompt_version="intel-summary-2026-03-19",
    )

    resp = client.get(f"/api/cases/{case_id}/intel-summary-status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ready"
    assert body["summary"]["summary"]["items"][0]["source_finding_ids"] == ["find-sanction-1"]


def test_get_enrichment_includes_events_and_cached_intel_summary(client):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Intel Surface Vendor")
    report = _sample_report("Intel Surface Vendor")
    server.db.save_enrichment(case_id, report)
    vendor = server.db.get_vendor(case_id)
    assert vendor is not None
    server._persist_case_events(case_id, vendor, report)
    server.db.save_intel_summary(
        case_id=case_id,
        user_id="dev",
        report_hash=report["report_hash"],
        summary={
            "items": [
                {
                    "title": "Litigation exposure remains active",
                    "assessment": "Federal contract litigation is still active.",
                    "status": "active",
                    "severity": "high",
                    "confidence": 0.85,
                    "source_finding_ids": ["find-lawsuit-1"],
                    "connectors": ["courtlistener"],
                    "recommended_action": "Review the complaint and litigation posture.",
                }
            ],
            "stats": {"citation_coverage": 1.0, "finding_count_considered": 3},
        },
        provider="openai",
        model="gpt-4o",
        prompt_tokens=12,
        completion_tokens=24,
        elapsed_ms=320,
        prompt_version="intel-summary-2026-03-19",
    )

    resp = client.get(f"/api/cases/{case_id}/enrichment")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["report_hash"] == report["report_hash"]
    assert len(body["events"]) >= 2
    assert body["intel_summary"]["summary"]["items"][0]["title"] == "Litigation exposure remains active"


def test_dossier_includes_intel_summary_and_normalized_events(client):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Dossier Intel Vendor")
    report = _sample_report("Dossier Intel Vendor")
    server.db.save_enrichment(case_id, report)
    vendor = server.db.get_vendor(case_id)
    assert vendor is not None
    server._persist_case_events(case_id, vendor, report)
    server.db.save_intel_summary(
        case_id=case_id,
        user_id="dev",
        report_hash=report["report_hash"],
        summary={
            "items": [
                {
                    "title": "Sanctions hit requires immediate review",
                    "assessment": "Trade CSL produced a high-confidence restricted-party result.",
                    "status": "active",
                    "severity": "critical",
                    "confidence": 0.95,
                    "source_finding_ids": ["find-sanction-1"],
                    "connectors": ["trade_csl"],
                    "recommended_action": "Hold the case and escalate to compliance.",
                }
            ],
            "stats": {"citation_coverage": 1.0, "finding_count_considered": 3},
        },
        provider="openai",
        model="gpt-4o",
        prompt_tokens=12,
        completion_tokens=24,
        elapsed_ms=320,
        prompt_version="intel-summary-2026-03-19",
    )

    import dossier

    html = dossier.generate_dossier(case_id, user_id="dev")
    assert "Intel Summary" in html
    assert "Normalized Events" in html
    assert "Sanctions hit requires immediate review" in html
