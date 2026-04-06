import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


import run_beta_quality_harness as harness


class FakeApiClient:
    def __init__(self, json_responses=None, byte_responses=None):
        self.json_responses = dict(json_responses or {})
        self.byte_responses = dict(byte_responses or {})

    def request_json(self, method, path, payload=None, *, timeout=30):
        key = (method, path)
        if key not in self.json_responses:
            raise AssertionError(f"Missing fake JSON response for {key}")
        return self.json_responses[key]

    def request_bytes(self, method, path, payload=None, *, timeout=30):
        key = (method, path)
        if key not in self.byte_responses:
            raise AssertionError(f"Missing fake bytes response for {key}")
        return self.byte_responses[key]


def test_validate_monitor_history_requires_completed_numeric_scores():
    result = harness.validate_monitor_history(
        {
            "runs": [
                {
                    "run_id": "run-1",
                    "status": "completed",
                    "delta_summary": "",
                    "score_before": "high",
                    "score_after": None,
                    "new_findings_count": 2,
                }
            ]
        }
    )

    assert result.passed is False
    assert "latest monitor run delta_summary is empty" in result.failures
    assert "latest monitor run score_before is not numeric" in result.failures
    assert "latest monitor run score_after is not numeric" in result.failures


def test_validate_graph_integrity_flags_self_edges_orphans_and_missing_types():
    result = harness.validate_graph_integrity(
        {
            "root_entity_id": "vendor-1",
            "entities": [
                {"id": "vendor-1"},
                {"id": "agency-1"},
                {"id": "orphan-1"},
            ],
            "relationships": [
                {
                    "source_entity_id": "vendor-1",
                    "target_entity_id": "vendor-1",
                    "rel_type": "contracts_with",
                    "corroboration_count": 1,
                }
            ],
        },
        {"required_relationship_types": ["owned_by"]},
    )

    assert result.passed is False
    assert "graph contains 2 orphan node(s)" in result.failures
    assert "graph contains 1 self-referencing edge(s)" in result.failures
    assert "graph missing required relationship types: owned_by" in result.failures


def test_run_case_harness_passes_happy_path(monkeypatch):
    html = """
    <html>
      <body>
        Helios Intelligence Brief
        Risk Storyline
        Supplier Passport
        Graph Read
        Axiom Assessment
        Recommended Actions
        Evidence Ledger
      </body>
    </html>
    """
    html = html + ("evidence " * 800)
    pdf_text = """
    HELIOS INTELLIGENCE BRIEF
    RISK STORYLINE
    SUPPLIER PASSPORT
    GRAPH READ
    AXIOM ASSESSMENT
    RECOMMENDED ACTIONS
    EVIDENCE LEDGER
    """
    monkeypatch.setattr(harness, "extract_pdf_text", lambda _: (pdf_text, []))

    client = FakeApiClient(
        json_responses={
            ("GET", "/api/cases/case-1"): (
                200,
                {},
                {"id": "case-1", "vendor_name": "Acme Systems", "workflow_lane": "counterparty"},
            ),
            ("POST", "/api/cases/case-1/monitor"): (200, {}, {"mode": "sync"}),
            ("GET", "/api/cases/case-1/monitor/history?limit=10"): (
                200,
                {},
                {
                    "runs": [
                        {
                            "run_id": "run-1",
                            "status": "completed",
                            "delta_summary": "Score decreased -3.0%",
                            "score_before": 80.0,
                            "score_after": 77.0,
                            "change_type": "score_delta",
                            "new_findings_count": 1,
                        }
                    ]
                },
            ),
            ("GET", "/api/cases/case-1/analysis-status"): (
                200,
                {},
                {"status": "ready", "case_id": "case-1"},
            ),
            ("GET", "/api/cases/case-1/analysis"): (
                200,
                {},
                {
                    "analysis": {
                        "executive_summary": "The supplier is acceptable with monitoring.",
                        "risk_narrative": "No disqualifying signal surfaced.",
                        "recommended_actions": ["Continue monitoring"],
                    },
                    "provider": "openai",
                    "model": "gpt-5.4",
                },
            ),
            ("GET", "/api/cases/case-1/graph?depth=3"): (
                200,
                {},
                {
                    "root_entity_id": "vendor-1",
                    "entities": [{"id": "vendor-1"}, {"id": "agency-1"}],
                    "relationships": [
                        {
                            "source_entity_id": "vendor-1",
                            "target_entity_id": "agency-1",
                            "rel_type": "contracts_with",
                            "corroboration_count": 2,
                        }
                    ],
                },
            ),
        },
        byte_responses={
            ("POST", "/api/cases/case-1/dossier"): (200, {}, html.encode("utf-8")),
            ("POST", "/api/cases/case-1/dossier-pdf"): (200, {}, b"%PDF-1.7 " + (b"x" * 5000)),
        },
    )

    result = harness.run_case_harness(
        client,
        {
            "id": "case-1",
            "required_relationship_types": ["contracts_with"],
            "graph_entity_min": 2,
        },
        graph_depth=3,
        analysis_timeout_seconds=5,
        monitor_history_wait_seconds=1,
        trigger_monitor=True,
        trigger_ai=True,
    )

    assert result.overall_passed is True
    assert result.checks["monitor_history"].passed is True
    assert result.checks["ai_narrative"].passed is True
    assert result.checks["dossier_integrity"].passed is True
    assert result.checks["graph_integrity"].passed is True
