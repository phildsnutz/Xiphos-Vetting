import importlib
import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    for module_name in [
        "axiom_gap_filler",
        "comparative_dossier",
        "gap_advisory_pipeline",
        "server_cvi_routes",
        "server",
    ]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    if "server" not in sys.modules:
        import server  # type: ignore

    server = sys.modules["server"]
    server.db.init_db()
    server.init_auth_db()

    with server.app.test_client() as test_client:
        yield test_client


def test_cvi_health_route_reports_components(client):
    response = client.get("/api/cvi/health")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] in {"ok", "degraded"}
    assert set(payload["components"]) == {
        "comparative",
        "vehicle_dossier",
        "teaming_intelligence",
        "gap_advisory",
        "gap_filler",
    }


def test_cvi_vehicle_dossier_route_returns_html(client, monkeypatch):
    import comparative_dossier

    monkeypatch.setattr(
        comparative_dossier,
        "generate_vehicle_dossier",
        lambda **_: "<html><body>vehicle dossier</body></html>",
    )

    response = client.post(
        "/api/cvi/vehicle-dossier",
        json={
            "vehicle_name": "ITEAMS",
            "prime_contractor": "Amentum",
            "vendor_ids": ["amentum_iteams"],
            "contract_data": {"contract_number": "N0016424F3004"},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "completed"
    assert "vehicle dossier" in payload["html"]
    assert payload["metadata"]["title"] == "ITEAMS Vehicle Dossier"


def test_cvi_teaming_intelligence_route_returns_report(client, monkeypatch):
    import teaming_intelligence

    monkeypatch.setattr(
        teaming_intelligence,
        "build_teaming_intelligence",
        lambda **_: {
            "analysis_scope": "multi_vehicle_capture_v1",
            "supported": True,
            "generated_at": "2026-04-06T00:00:00Z",
            "vehicle_name": "ITEAMS",
            "state_contract": {
                "observed": "facts",
                "assessed": "assessment",
                "predicted": "prediction",
            },
            "graph_snapshot_signature": "kgsnapshot:test",
            "observed_signals": [],
            "assessed_partners": [],
            "top_conclusions": ["Amentum remains the incumbent core."],
            "map": {"nodes": [], "edges": []},
            "scenario": None,
        },
    )

    response = client.post(
        "/api/cvi/teaming-intelligence",
        json={
            "vehicle_name": "ITEAMS",
            "observed_vendors": [{"vendor_name": "Amentum", "role": "prime"}],
            "scenario": {"recruit_partner": "SMX"},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "completed"
    assert payload["report"]["analysis_scope"] == "multi_vehicle_capture_v1"
    assert payload["report"]["top_conclusions"] == ["Amentum remains the incumbent core."]


def test_cvi_teaming_intelligence_route_hydrates_observed_vendors_from_vehicle_support(client, monkeypatch):
    import teaming_intelligence
    import vehicle_intel_support

    captured = {}

    def fake_support(**kwargs):
        captured["support_scope"] = kwargs.get("support_scope")
        captured["sync_graph"] = kwargs.get("sync_graph")
        return {
            "observed_vendors": [
                {"vendor_name": "Science Applications International Corporation", "role": "prime", "award_amount": 188000000},
                {"vendor_name": "Torch Technologies, Inc.", "role": "prime", "award_amount": 76000000},
            ]
        }

    monkeypatch.setattr(vehicle_intel_support, "build_vehicle_intelligence_support", fake_support, raising=False)

    def fake_build_teaming_intelligence(**kwargs):
        captured["observed_vendors"] = kwargs.get("observed_vendors", [])
        return {
            "analysis_scope": "multi_vehicle_capture_v1",
            "supported": True,
            "generated_at": "2026-04-07T00:00:00Z",
            "vehicle_name": kwargs.get("vehicle_name"),
            "state_contract": {
                "observed": "facts",
                "assessed": "assessment",
                "predicted": "prediction",
            },
            "graph_snapshot_signature": "kgsnapshot:test",
            "observed_signals": [],
            "assessed_partners": [],
            "top_conclusions": ["Hydrated observed vendor roster used."],
            "map": {"nodes": [], "edges": []},
            "scenario": None,
        }

    monkeypatch.setattr(teaming_intelligence, "build_teaming_intelligence", fake_build_teaming_intelligence)

    response = client.post(
        "/api/cvi/teaming-intelligence",
        json={
            "vehicle_name": "OASIS",
            "prime_contractor": "Science Applications International Corporation",
        },
    )

    assert response.status_code == 200
    assert captured["observed_vendors"][0]["vendor_name"] == "Science Applications International Corporation"
    assert len(captured["observed_vendors"]) == 2
    assert captured["support_scope"] == "market"
    assert captured["sync_graph"] is True


def test_cvi_gap_advisory_route_serializes_pipeline_result(client, monkeypatch):
    import gap_advisory_pipeline

    proposal = gap_advisory_pipeline.AdvisoryProposal(
        proposal_id="prop-1",
        title="ITEAMS Gap Closure",
        client_company="INDOPACOM",
        vehicle_name="ITEAMS",
        gaps_addressed=[{"gap_id": "gap-1"}],
        scope_of_work="Map the unknown subcontractor network.",
        methodology=["FOIA targeting", "subaward correlation"],
        deliverables=["Gap memo"],
        estimated_value=25000,
        estimated_duration_days=14,
        priority="high",
        data_sources_required=["SAM.gov"],
        fill_methods=["automated_search"],
        confidence_of_fill=0.72,
    )

    monkeypatch.setattr(
        gap_advisory_pipeline,
        "run_gap_advisory_pipeline",
        lambda **_: gap_advisory_pipeline.PipelineResult(
            total_gaps_identified=5,
            gaps_filled_by_axiom=2,
            gaps_remaining=3,
            proposals_generated=[proposal],
            total_pipeline_value=25000,
            axiom_fill_results=[{"gap_type": "subcontractor_identity", "status": "filled"}],
            elapsed_ms=1234,
        ),
    )

    response = client.post(
        "/api/cvi/gap-advisory",
        json={
            "vendor_ids": ["amentum_iteams"],
            "vehicle_name": "ITEAMS",
            "client_company": "INDOPACOM",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "completed"
    assert payload["pipeline_result"]["gaps_identified"] == 5
    assert payload["pipeline_result"]["gaps_filled_by_axiom"] == 2
    assert payload["pipeline_result"]["gaps_remaining"] == 3
    assert payload["proposals"][0]["proposal_id"] == "prop-1"


def test_cvi_fill_gaps_route_converts_inputs_and_serializes_results(client, monkeypatch):
    import axiom_gap_filler
    import knowledge_graph

    captured = {}

    def fake_fill_gaps(gaps, api_key="", provider="", model="", user_id="", max_attempts_per_gap=3):
        captured["gaps"] = gaps
        captured["provider"] = provider
        captured["model"] = model
        captured["user_id"] = user_id
        captured["max_attempts_per_gap"] = max_attempts_per_gap
        return [
            axiom_gap_filler.GapFillResult(
                gap=gaps[0],
                filled=True,
                fill_confidence=0.84,
                attempts=[
                    axiom_gap_filler.FillAttempt(
                        approach_name="regulatory_filing_mine",
                        approach_reasoning="Official award data exposed the missing teammate.",
                        findings=[{"source": "sam_gov", "value": "Named mission support subcontractor"}],
                    )
                ],
                final_classification="filled",
            )
        ]

    monkeypatch.setattr(axiom_gap_filler, "fill_gaps", fake_fill_gaps)

    response = client.post(
        "/api/cvi/fill-gaps",
        json={
            "vehicle_name": "ITEAMS",
            "gaps": [
                {
                    "id": "gap-1",
                    "description": "Unknown subcontractor identity",
                    "gap_type": "subcontractor_identity",
                    "severity": "high",
                    "affected_vendor": "Amentum",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "completed"
    assert payload["summary"]["total_gaps"] == 1
    assert payload["summary"]["closed"] == 1
    assert payload["results"][0]["gap_id"] == "gap-1"
    assert payload["results"][0]["status"] == "closed"
    assert payload["results"][0]["confidence"] == pytest.approx(0.84)
    assert payload["results"][0]["validation"]["outcome"] == "accepted"
    assert payload["results"][0]["graph_promotion"]["status"] == "promoted"
    assert payload["graph_promotion"]["promoted_claims"] == 1
    assert captured["gaps"][0].entity_name == "Amentum"
    assert captured["gaps"][0].vehicle_name == "ITEAMS"
    with knowledge_graph.get_kg_conn() as conn:
        claim_count = conn.execute("SELECT COUNT(*) FROM kg_claims").fetchone()[0]
        evidence_count = conn.execute("SELECT COUNT(*) FROM kg_evidence").fetchone()[0]
    assert claim_count == 1
    assert evidence_count == 1


def test_attempt_axiom_fill_uses_current_gap_filler_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    for module_name in ["knowledge_graph", "gap_advisory_pipeline"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
    import axiom_gap_filler
    import gap_advisory_pipeline
    import knowledge_graph

    captured = {}
    knowledge_graph.init_kg_db()

    monkeypatch.setattr(gap_advisory_pipeline.db, "get_vendor", lambda vendor_id: {"name": "Amentum"})

    def fake_fill_gaps(gaps, api_key="", provider="", model="", user_id="", max_attempts_per_gap=3):
        captured["gaps"] = gaps
        captured["api_key"] = api_key
        captured["provider"] = provider
        captured["model"] = model
        captured["user_id"] = user_id
        return [
            axiom_gap_filler.GapFillResult(
                gap=gaps[0],
                filled=True,
                fill_confidence=0.91,
                attempts=[
                    axiom_gap_filler.FillAttempt(
                        approach_name="regulatory_filing_mine",
                        approach_reasoning="Official contract records resolved the teammate.",
                        findings=[{"source": "usaspending", "value": "Subaward record ties SMX to ITEAMS"}],
                    )
                ],
                final_classification="filled",
            )
        ]

    monkeypatch.setattr(gap_advisory_pipeline, "fill_gaps", fake_fill_gaps)

    filled, unfilled = gap_advisory_pipeline.attempt_axiom_fill(
        [
            {
                "gap_id": "gap-123",
                "gap_type": "subcontractor_identity",
                "description": "Unknown teammate",
                "severity": "critical",
                "affected_entities": ["SMX"],
                "vehicle_name": "ITEAMS",
            }
        ],
        vendor_id="amentum_iteams",
        api_key="k",
        provider="anthropic",
        model="claude-sonnet-4-6",
        user_id="system",
    )

    assert len(filled) == 1
    assert unfilled == []
    assert captured["gaps"][0].gap_id == "gap-123"
    assert captured["gaps"][0].entity_name == "SMX"
    assert captured["gaps"][0].priority == "critical"
    assert captured["user_id"] == "system"
    assert filled[0]["axiom_validation"]["outcome"] == "accepted"
    assert filled[0]["axiom_graph_promotion"]["status"] == "promoted"


def test_attempt_axiom_fill_demotes_weak_single_source_results(monkeypatch):
    import axiom_gap_filler
    import gap_advisory_pipeline

    monkeypatch.setattr(gap_advisory_pipeline.db, "get_vendor", lambda vendor_id: {"name": "Amentum"})

    def fake_fill_gaps(gaps, api_key="", provider="", model="", user_id="", max_attempts_per_gap=3):
        return [
            axiom_gap_filler.GapFillResult(
                gap=gaps[0],
                filled=True,
                fill_confidence=0.62,
                attempts=[
                    axiom_gap_filler.FillAttempt(
                        approach_name="proxy_indicator_hunt",
                        approach_reasoning="A job posting implied the missing teammate.",
                        findings=[{"source": "careers_scraper", "value": "Job posting for mission support engineer"}],
                    )
                ],
                final_classification="filled",
            )
        ]

    monkeypatch.setattr(gap_advisory_pipeline, "fill_gaps", fake_fill_gaps)

    filled, unfilled = gap_advisory_pipeline.attempt_axiom_fill(
        [
            {
                "gap_id": "gap-weak",
                "gap_type": "subcontractor_identity",
                "description": "Possible teammate inferred from a job post",
                "severity": "high",
                "affected_entities": ["SMX"],
                "vehicle_name": "ITEAMS",
            }
        ],
        vendor_id="amentum_iteams",
        api_key="k",
        provider="anthropic",
        model="claude-sonnet-4-6",
        user_id="system",
    )

    assert filled == []
    assert len(unfilled) == 1
    assert unfilled[0]["axiom_validation"]["outcome"] == "review"


def test_gap_pipeline_generates_proposals_per_vendor_not_cumulative(monkeypatch):
    import gap_advisory_pipeline

    monkeypatch.setattr(gap_advisory_pipeline, "build_dossier_context", lambda vendor_id, user_id="": {"vendor_id": vendor_id})
    monkeypatch.setattr(
        gap_advisory_pipeline,
        "extract_gaps_from_context",
        lambda vendor_id, dossier_context=None: [
            {
                "gap_id": f"gap-{vendor_id}",
                "gap_type": "subcontractor_identity",
                "description": f"Gap for {vendor_id}",
                "severity": "high",
            }
        ],
    )
    monkeypatch.setattr(
        gap_advisory_pipeline,
        "attempt_axiom_fill",
        lambda gaps, vendor_id, api_key="", provider="anthropic", model="claude-sonnet-4-6", user_id="": ([], gaps),
    )

    proposal_batch_sizes = []

    def fake_generate_advisory_proposals(unfilled_gaps, vendor_id, vehicle_name="", client_company=""):
        proposal_batch_sizes.append((vendor_id, len(unfilled_gaps)))
        return []

    monkeypatch.setattr(gap_advisory_pipeline, "generate_advisory_proposals", fake_generate_advisory_proposals)

    gap_advisory_pipeline.run_gap_advisory_pipeline(
        vendor_ids=["v1", "v2"],
        vehicle_name="ITEAMS",
        client_company="INDOPACOM",
        skip_axiom_fill=False,
    )

    assert proposal_batch_sizes == [("v1", 1), ("v2", 1)]
