import importlib
import io
import os
import sys
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from entity_resolution import ResolvedEntity


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        server = importlib.import_module("server")
    graph_runtime = importlib.import_module("graph_runtime")
    graph_runtime.reset_cached_graph_analytics()

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    import hardening

    hardening.reset_rate_limiter()

    with server.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-auth-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "true")
    monkeypatch.delenv("XIPHOS_DEV_MODE", raising=False)
    monkeypatch.setenv("XIPHOS_SECRET_KEY", "test-secret-key")

    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        server = importlib.import_module("server")
    graph_runtime = importlib.import_module("graph_runtime")
    graph_runtime.reset_cached_graph_analytics()

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    import hardening
    import auth as auth_module

    hardening.reset_rate_limiter()
    auth_module.create_user("analyst@example.com", "AnalystPass123!", name="Analyst", role="analyst")

    with server.app.test_client() as test_client:
        login = test_client.post(
            "/api/auth/login",
            json={"email": "analyst@example.com", "password": "AnalystPass123!"},
        )
        assert login.status_code == 200
        token = login.get_json()["token"]
        yield {
            "client": test_client,
            "server": server,
            "headers": {"Authorization": f"Bearer {token}"},
        }


@pytest.fixture
def locked_host_client(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-host-lock.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")
    monkeypatch.setenv("XIPHOS_PUBLIC_BASE_URL", "https://helios.xiphosllc.com")

    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        server = importlib.import_module("server")
    graph_runtime = importlib.import_module("graph_runtime")
    graph_runtime.reset_cached_graph_analytics()

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()

    import hardening

    hardening.reset_rate_limiter()

    with server.app.test_client() as test_client:
        yield test_client


def _create_case(client, name="Acme Corp", country="US", headers=None, extra_payload=None, *, suppress_ai_prime=True):
    payload = {
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
    }
    if extra_payload:
        payload.update(extra_payload)

    server = sys.modules["server"]
    original_prime = getattr(server, "_prime_ai_analysis_for_case", None)
    if suppress_ai_prime:
        setattr(server, "_prime_ai_analysis_for_case", lambda *_args, **_kwargs: {"status": "suppressed"})
    try:
        resp = client.post(
            "/api/cases",
            json=payload,
            headers=headers,
        )
    finally:
        if suppress_ai_prime and original_prime is not None:
            setattr(server, "_prime_ai_analysis_for_case", original_prime)
    assert resp.status_code == 201
    return resp.get_json()["case_id"]


def test_compare_profiles_route_returns_comparisons(client):
    resp = client.post(
        "/api/compare",
        json={
            "name": "Boeing",
            "country": "US",
            "profiles": ["defense_acquisition", "commercial_supply_chain"],
        },
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["entity"]["name"] == "Boeing"
    assert len(body["comparisons"]) == 2
    assert all("tier" in comparison for comparison in body["comparisons"])


def test_decision_routes_match_frontend_contract(client):
    case_id = _create_case(client, name="Decision Test Vendor")

    create_resp = client.post(
        f"/api/cases/{case_id}/decision",
        json={"decision": "approve", "reason": "Low risk and complete documentation"},
    )
    assert create_resp.status_code == 201
    created = create_resp.get_json()
    assert created["vendor_id"] == case_id
    assert created["decision_id"] > 0
    assert created["decision"] == "approve"

    list_resp = client.get(f"/api/cases/{case_id}/decisions?limit=5")
    assert list_resp.status_code == 200
    payload = list_resp.get_json()
    assert payload["vendor_id"] == case_id
    assert payload["latest_decision"]["decision"] == "approve"
    assert len(payload["decisions"]) == 1


def test_case_detail_route_includes_storyline_payload(client):
    case_id = _create_case(client, name="Storyline API Vendor")

    resp = client.get(f"/api/cases/{case_id}")
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["id"] == case_id
    assert body["storyline"]["version"] == "risk-storyline-v1"
    assert len(body["storyline"]["cards"]) >= 2
    assert any(card["type"] == "action" for card in body["storyline"]["cards"])


def test_supplier_passport_route_returns_portable_summary(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Passport Route Vendor")
    captured = {"mode": None}

    def fake_build_supplier_passport(vendor_id, mode="full"):
        captured["mode"] = mode
        return {
            "passport_version": "supplier-passport-v1",
            "case_id": vendor_id,
            "posture": "approved",
            "vendor": {"name": "Passport Route Vendor"},
        }

    monkeypatch.setattr(server, "HAS_SUPPLIER_PASSPORT", True, raising=False)
    monkeypatch.setattr(
        server,
        "build_supplier_passport",
        fake_build_supplier_passport,
        raising=False,
    )

    response = client.get(f"/api/cases/{case_id}/supplier-passport?mode=light")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["case_id"] == case_id
    assert payload["passport_version"] == "supplier-passport-v1"
    assert payload["posture"] == "approved"
    assert captured["mode"] == "light"


def test_unexpected_get_host_redirects_to_canonical_domain(locked_host_client):
    response = locked_host_client.get(
        "/api/health?view=full",
        headers={"Host": "24.199.122.225.sslip.io"},
        follow_redirects=False,
    )

    assert response.status_code == 308
    assert response.headers["Location"] == "https://helios.xiphosllc.com/api/health?view=full"


def test_unexpected_post_host_is_rejected(locked_host_client):
    response = locked_host_client.post(
        "/api/cases",
        json={"name": "Blocked Host Vendor"},
        headers={"Host": "24.199.122.225.sslip.io"},
    )

    assert response.status_code == 421
    payload = response.get_json()
    assert payload["error"] == "Unexpected host header"
    assert payload["expected_host"] == "helios.xiphosllc.com"


def test_localhost_health_check_remains_allowed_with_host_lock(locked_host_client):
    response = locked_host_client.get(
        "/api/health",
        headers={"Host": "localhost"},
    )

    assert response.status_code == 200


def test_graph_full_intelligence_route_surfaces_decision_and_structural_importance(client, monkeypatch):
    server = sys.modules["server"]

    class FakeAnalytics:
        def __init__(self):
            self.nodes = {
                "node:vendor": {
                    "canonical_name": "Vendor Prime",
                    "entity_type": "company",
                    "confidence": 0.94,
                    "country": "US",
                    "created_at": "2026-03-31T00:00:00Z",
                },
                "node:bridge": {
                    "canonical_name": "Bridge Entity",
                    "entity_type": "company",
                    "confidence": 0.81,
                    "country": "GB",
                    "created_at": "2026-03-30T00:00:00Z",
                },
            }
            self.edges = [
                {
                    "source": "node:vendor",
                    "target": "node:bridge",
                    "rel_type": "contracts_with",
                    "confidence": 0.88,
                    "data_source": "fixture",
                    "created_at": "2026-03-31T00:00:00Z",
                }
            ]

        def load_graph(self):
            return None

        def compute_all_centrality(self):
            return {
                "node:vendor": {
                    "composite_importance": 0.71,
                    "structural_importance": 0.43,
                    "decision_importance": 0.71,
                    "degree": {"normalized": 0.8},
                    "betweenness": {"normalized": 0.1},
                    "pagerank": {"normalized": 0.6},
                },
                "node:bridge": {
                    "composite_importance": 0.39,
                    "structural_importance": 0.82,
                    "decision_importance": 0.39,
                    "degree": {"normalized": 0.5},
                    "betweenness": {"normalized": 0.7},
                    "pagerank": {"normalized": 0.4},
                },
            }

        def detect_communities(self):
            return {
                "count": 1,
                "modularity": 0.27,
                "node_labels": {"node:vendor": 7, "node:bridge": 7},
                "communities": {
                    7: {
                        "size": 2,
                        "members": [
                            {"id": "node:vendor"},
                            {"id": "node:bridge"},
                        ],
                        "types": ["company", "company"],
                    }
                },
            }

        def compute_sanctions_exposure(self):
            return {
                "node:vendor": {"exposure_score": 0.41, "risk_level": "HIGH"},
                "node:bridge": {"exposure_score": 0.0, "risk_level": "CLEAR"},
            }

        def compute_temporal_profile(self):
            return {"total_edges": 1, "growth_rate_pct": 0.0}

    monkeypatch.setattr(server, "HAS_GRAPH_ANALYTICS", True, raising=False)
    monkeypatch.setattr(server, "GraphAnalytics", FakeAnalytics, raising=False)

    response = client.get("/api/graph/full-intelligence")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["total_nodes"] == 2
    assert payload["nodes"][0]["centrality_decision"] >= 0.0
    assert payload["nodes"][0]["centrality_structural"] >= 0.0
    assert payload["top_by_importance"][0]["id"] == "node:vendor"
    assert payload["top_by_structural_importance"][0]["id"] == "node:bridge"


def test_graph_topology_route_returns_fast_baseline_payload(client, monkeypatch):
    server = sys.modules["server"]

    class FakeAnalytics:
        def __init__(self):
            self.nodes = {
                "node:vendor": {
                    "canonical_name": "Parsons Government Services",
                    "entity_type": "company",
                    "confidence": 0.97,
                    "country": "US",
                    "created_at": "2026-04-08T00:00:00Z",
                },
                "node:vehicle": {
                    "canonical_name": "OASIS",
                    "entity_type": "contract_vehicle",
                    "confidence": 0.74,
                    "country": "US",
                    "created_at": "2026-04-08T00:00:00Z",
                },
            }
            self.edges = [
                {
                    "source": "node:vendor",
                    "target": "node:vehicle",
                    "rel_type": "prime_on_vehicle",
                    "confidence": 0.83,
                    "data_source": "usaspending",
                    "created_at": "2026-04-08T00:00:00Z",
                }
            ]

        def load_graph(self):
            return None

    monkeypatch.setattr(server, "HAS_GRAPH_ANALYTICS", True, raising=False)
    monkeypatch.setattr(server, "GraphAnalytics", FakeAnalytics, raising=False)

    response = client.get("/api/graph/topology")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["total_nodes"] == 2
    assert payload["summary"]["total_edges"] == 1
    assert payload["summary"]["risk_distribution"]["CLEAR"] == 2
    assert payload["nodes"][0]["centrality_decision"] == 0
    assert payload["edges"][0]["rel_type"] == "prime_on_vehicle"
    assert payload["temporal"] is None


def test_supplier_passport_builder_combines_case_graph_and_control_paths(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(
        client,
        name="Passport Builder Vendor",
        extra_payload={
            "ownership": {
                "publicly_traded": False,
                "state_owned": False,
                "beneficial_owner_known": False,
                "ownership_pct_resolved": 0.35,
                "shell_layers": 2,
                "pep_connection": False,
            },
            "export_authorization": {
                "request_type": "item_transfer",
                "destination_country": "AE",
                "classification_guess": "EAR99",
            },
        },
    )

    server.db.save_score(
        case_id,
        {
            "composite_score": 19,
            "is_hard_stop": False,
            "calibrated": {
                "calibrated_probability": 0.41,
                "calibrated_tier": "TIER_3_REVIEW",
                "program_recommendation": "ENHANCED_DUE_DILIGENCE",
                "interval": {"lower": 0.31, "upper": 0.52, "coverage": 0.9},
            },
        },
    )
    server.db.save_enrichment(
        case_id,
        {
            "overall_risk": "MEDIUM",
            "summary": {"connectors_run": 6, "connectors_with_data": 4, "findings_total": 7},
            "identifiers": {"cage": "1ABC2", "uei": "UEI123456"},
            "connector_status": {
                "sam_gov": {
                    "has_data": True,
                    "error": "",
                    "structured_fields": {
                        "sam_api_status": {
                            "entity_lookup": {"status": 200, "throttled": False},
                            "exclusions_lookup": {"status": 200, "throttled": False},
                        }
                    },
                },
                "mitre_attack_fixture": {
                    "has_data": True,
                    "error": "",
                    "structured_fields": {
                        "summary": {
                            "actor_families": ["Volt Typhoon"],
                            "campaigns": ["Edge-device access with living-off-the-land persistence"],
                            "technique_ids": ["T1190", "T1078"],
                            "techniques": [
                                {"id": "T1190", "name": "Exploit Public-Facing Application", "tactic": "Initial Access"},
                                {"id": "T1078", "name": "Valid Accounts", "tactic": "Defense Evasion"}
                            ],
                            "tactics": ["Initial Access", "Defense Evasion"]
                        }
                    },
                },
                "cisa_advisory_fixture": {
                    "has_data": True,
                    "error": "",
                    "structured_fields": {
                        "summary": {
                            "advisory_ids": ["AA24-057A"],
                            "advisory_titles": ["SVR Cyber Actors Adapt Tactics for Initial Cloud Access"],
                            "technique_ids": ["T1078"],
                            "sectors": ["defense industrial base"],
                            "mitigations": ["phishing-resistant MFA"],
                            "ioc_types": ["token_abuse"]
                        }
                    },
                },
            },
        },
    )

    import supplier_passport

    monkeypatch.setattr(
        supplier_passport,
        "get_latest_foci_summary",
        lambda vendor_id: {"posture": "foreign_interest_requires_review", "foreign_owner": "Example Holdings"},
        raising=False,
    )
    monkeypatch.setattr(
        supplier_passport,
        "get_latest_cyber_evidence_summary",
        lambda vendor_id: {"current_cmmc_level": 2, "high_or_critical_cve_count": 1},
        raising=False,
    )
    monkeypatch.setattr(
        supplier_passport,
        "get_export_evidence_summary",
        lambda vendor_id, export_input: {"jurisdiction_guess": "ear", "posture": "likely_license_required"},
        raising=False,
    )
    monkeypatch.setattr(
        supplier_passport,
        "build_workflow_control_summary",
        lambda vendor, **kwargs: {"label": "Foreign interest in view", "action_owner": "Analyst review"},
        raising=False,
    )
    def fake_graph_summary(vendor_id, depth=2, **kwargs):
        assert depth == 2
        assert kwargs.get("include_provenance") is True
        assert kwargs.get("max_claim_records") == 2
        assert kwargs.get("max_evidence_records") == 2
        return {
            "entity_count": 3,
            "relationship_count": 3,
            "root_entity_ids": ["entity:a"],
            "entity_type_distribution": {"company": 2, "holding_company": 1},
            "relationship_type_distribution": {"beneficially_owned_by": 1, "contracts_with": 1},
            "entities": [
                {"id": "entity:a", "canonical_name": "Passport Builder Vendor"},
                {"id": "holding_company:example", "canonical_name": "Example Holdings"},
                {"id": "entity:b", "canonical_name": "Prime Integrator"},
            ],
            "relationships": [
                {
                    "source_entity_id": "entity:a",
                    "target_entity_id": "holding_company:example",
                    "rel_type": "beneficially_owned_by",
                    "confidence": 0.92,
                    "corroboration_count": 2,
                    "data_sources": ["gleif_bods_ownership_fixture"],
                    "created_at": "2026-03-26T00:00:00Z",
                    "claim_records": [
                        {
                            "claim_id": "claim:1",
                            "contradiction_state": "unreviewed",
                            "evidence_records": [
                                {
                                    "title": "Ownership filing",
                                    "url": "https://example.test/ownership",
                                    "artifact_ref": "fixture://ownership/1",
                                    "source": "gleif_bods_ownership_fixture",
                                }
                            ],
                        }
                    ],
                },
                {
                    "source_entity_id": "entity:a",
                    "target_entity_id": "entity:b",
                    "rel_type": "contracts_with",
                    "confidence": 0.81,
                    "corroboration_count": 1,
                    "data_sources": ["usaspending"],
                    "created_at": "2026-03-26T00:00:00Z",
                },
                {
                    "source_entity_id": "entity:b",
                    "target_entity_id": "holding_company:other",
                    "rel_type": "owned_by",
                    "confidence": 0.72,
                    "corroboration_count": 1,
                    "data_sources": ["google_news"],
                    "created_at": "2026-03-26T00:00:00Z",
                },
            ],
        }

    monkeypatch.setattr(
        supplier_passport,
        "get_vendor_graph_summary",
        fake_graph_summary,
        raising=False,
    )
    monkeypatch.setattr(
        supplier_passport,
        "compute_network_risk",
        lambda vendor_id: {
            "network_risk_score": 1.7,
            "network_risk_level": "medium",
            "neighbor_count": 4,
            "high_risk_neighbors": 1,
            "risk_contributors": [{"entity_name": "Example Holdings", "contribution": 1.2}],
        },
        raising=False,
    )

    passport = supplier_passport.build_supplier_passport(case_id)

    assert passport is not None
    assert passport["case_id"] == case_id
    assert passport["posture"] == "review"
    assert passport["identity"]["identifiers"]["cage"] == "1ABC2"
    assert passport["identity"]["identifier_status"]["cage"]["state"] == "verified_present"
    assert passport["identity"]["identifier_status"]["cage"]["authority_level"] == "official_registry"
    assert passport["identity"]["identifier_status"]["uei"]["state"] == "verified_present"
    assert passport["identity"]["official_corroboration"]["coverage_level"] == "strong"
    assert passport["identity"]["official_corroboration"]["official_identifiers_verified"] == ["cage", "uei"]
    assert passport["threat_intel"]["shared_threat_intel_present"] is True
    assert passport["threat_intel"]["attack_technique_ids"] == ["T1190", "T1078"]
    assert passport["threat_intel"]["cisa_advisory_ids"] == ["AA24-057A"]
    assert passport["ownership"]["foci_summary"]["foreign_owner"] == "Example Holdings"
    assert passport["graph"]["entity_count"] == 2
    assert passport["graph"]["relationship_count"] == 1
    assert passport["graph"]["network_entity_count"] == 3
    assert passport["graph"]["network_relationship_count"] == 3
    assert passport["graph"]["control_paths"][0]["rel_type"] == "beneficially_owned_by"
    assert passport["graph"]["control_paths"][0]["evidence_refs"][0]["url"] == "https://example.test/ownership"
    assert passport["graph"]["control_paths"][0]["intelligence_tier"] == "strong"
    assert passport["graph"]["control_paths"][0]["intelligence_score"] >= 0.75
    assert len(passport["graph"]["control_paths"]) == 1
    assert passport["graph"]["control_path_summary"]["ownership_count"] == 1
    assert passport["graph"]["control_path_summary"]["financing_count"] == 0
    assert passport["graph"]["control_path_summary"]["intermediary_count"] == 0
    assert passport["graph"]["claim_health"]["corroborated_paths"] == 1
    assert passport["graph"]["intelligence"]["workflow_lane"] == "export_authorization"
    assert passport["graph"]["intelligence"]["edge_family_counts"]["ownership_control"] == 2
    assert passport["graph"]["intelligence"]["edge_family_counts"]["contracts_and_programs"] == 1
    assert passport["graph"]["intelligence"]["missing_required_edge_families"] == ["trade_and_logistics"]
    assert passport["graph"]["intelligence"]["claim_coverage_pct"] == pytest.approx(1 / 3, rel=1e-3)
    assert passport["graph"]["intelligence"]["strong_edge_count"] >= 1
    assert passport["graph"]["intelligence"]["control_path_avg_intelligence_score"] >= 0.5
    assert passport["tribunal"]["recommended_view"] == "watch"
    assert passport["tribunal"]["signal_snapshot"]["graph_missing_required_edge_family_count"] == 1
    assert passport["tribunal"]["views"][0]["stance"] == "watch"
    assert passport["network_risk"]["level"] == "medium"


def test_supplier_passport_caches_expensive_graph_and_network_calls(client, monkeypatch):
    case_id = _create_case(client, name="Passport Cache Vendor")
    server = sys.modules["server"]
    server.db.save_enrichment(
        case_id,
        {
            "overall_risk": "LOW",
            "summary": {"connectors_run": 2, "connectors_with_data": 1, "findings_total": 1},
            "identifiers": {"website": "https://example.test"},
            "enriched_at": "2026-03-28T20:30:00Z",
        },
    )
    server.db.save_score(
        case_id,
        {
            "composite_score": 12,
            "is_hard_stop": False,
            "scored_at": "2026-03-28T20:31:00Z",
            "calibrated": {"calibrated_probability": 0.12, "calibrated_tier": "TIER_4_CLEAR"},
        },
    )

    import supplier_passport

    graph_calls = {"count": 0}
    network_calls = {"count": 0}

    def fake_graph_summary(vendor_id, depth=2, **kwargs):
        graph_calls["count"] += 1
        assert depth == 2
        return {
            "entity_count": 1,
            "relationship_count": 0,
            "root_entity_ids": ["entity:a"],
            "entities": [{"id": "entity:a", "canonical_name": "Passport Cache Vendor"}],
            "relationships": [],
            "entity_type_distribution": {"company": 1},
            "relationship_type_distribution": {},
        }

    def fake_network_risk(vendor_id):
        network_calls["count"] += 1
        return {
            "network_risk_score": 0.0,
            "network_risk_level": "none",
            "neighbor_count": 0,
            "high_risk_neighbors": 0,
            "risk_contributors": [],
        }

    monkeypatch.setattr(supplier_passport, "get_vendor_graph_summary", fake_graph_summary, raising=False)
    monkeypatch.setattr(supplier_passport, "compute_network_risk", fake_network_risk, raising=False)
    monkeypatch.setattr(supplier_passport, "_SUPPLIER_PASSPORT_CACHE", {}, raising=False)

    first = supplier_passport.build_supplier_passport(case_id)
    second = supplier_passport.build_supplier_passport(case_id)

    assert first is not None
    assert second is not None
    assert graph_calls["count"] == 1
    assert network_calls["count"] == 1


def test_supplier_passport_adds_mission_conditioned_graph_overlay(client, monkeypatch):
    case_id = _create_case(client, name="Mission Overlay Vendor")
    server = sys.modules["server"]
    server.db.save_enrichment(
        case_id,
        {
            "overall_risk": "LOW",
            "summary": {"connectors_run": 2, "connectors_with_data": 1, "findings_total": 1},
            "identifiers": {"website": "https://overlay.example"},
            "enriched_at": "2026-03-31T10:00:00Z",
        },
    )
    server.db.save_score(
        case_id,
        {
            "composite_score": 14,
            "is_hard_stop": False,
            "scored_at": "2026-03-31T10:01:00Z",
            "calibrated": {"calibrated_probability": 0.14, "calibrated_tier": "TIER_4_CLEAR"},
        },
    )

    import supplier_passport

    monkeypatch.setattr(
        supplier_passport,
        "get_vendor_graph_summary",
        lambda vendor_id, **kwargs: {
            "entity_count": 3,
            "relationship_count": 2,
            "root_entity_ids": ["entity:vendor"],
            "entity_type_distribution": {"company": 1, "facility": 1, "subsystem": 1},
            "relationship_type_distribution": {"supports_site": 1, "maintains_system_for": 1},
            "entities": [
                {"id": "entity:vendor", "canonical_name": "Mission Overlay Vendor", "entity_type": "company"},
                {"id": "entity:site", "canonical_name": "Honolulu Sustainment Site", "entity_type": "facility"},
                {"id": "entity:subsystem", "canonical_name": "Lift Pod", "entity_type": "subsystem"},
            ],
            "relationships": [
                {
                    "source_entity_id": "entity:vendor",
                    "target_entity_id": "entity:site",
                    "rel_type": "supports_site",
                    "confidence": 0.82,
                    "data_sources": ["fixture"],
                    "created_at": "2026-03-31T00:00:00Z",
                },
                {
                    "source_entity_id": "entity:vendor",
                    "target_entity_id": "entity:subsystem",
                    "rel_type": "maintains_system_for",
                    "confidence": 0.87,
                    "data_sources": ["fixture"],
                    "created_at": "2026-03-31T00:00:00Z",
                },
            ],
        },
        raising=False,
    )
    monkeypatch.setattr(supplier_passport, "compute_network_risk", lambda vendor_id: None, raising=False)
    monkeypatch.setattr(supplier_passport, "_SUPPLIER_PASSPORT_CACHE", {}, raising=False)

    passport = supplier_passport.build_supplier_passport(
        case_id,
        mission_context={
            "mission_thread_id": "mt-demo",
            "role": "heavy_lift_provider",
            "criticality": "mission_critical",
            "subsystem": "Lift Pod",
            "site": "Honolulu",
            "focus_entity_ids": ["entity:vendor"],
        },
    )

    assert passport["graph"]["mission_context"]["mission_thread_id"] == "mt-demo"
    assert passport["graph"]["mission_context"]["site"] == "Honolulu"
    assert passport["graph"]["top_nodes_by_mission_importance"]
    assert "mission_importance" in passport["graph"]["top_nodes_by_mission_importance"][0]


def test_supplier_passport_control_paths_prefer_intelligence_score_over_raw_confidence():
    import supplier_passport

    graph_summary = {
        "entities": [
            {"id": "vendor:1", "canonical_name": "Atlas Systems"},
            {"id": "entity:official_parent", "canonical_name": "Atlas Holdings"},
            {"id": "entity:speculative_bank", "canonical_name": "Borderless Clearing Bank"},
        ],
        "relationships": [
            {
                "source_entity_id": "vendor:1",
                "target_entity_id": "entity:speculative_bank",
                "rel_type": "routes_payment_through",
                "confidence": 0.92,
                "corroboration_count": 1,
                "data_sources": ["public_search_ownership"],
                "last_seen_at": "2024-01-05T00:00:00Z",
                "claim_records": [
                    {
                        "contradiction_state": "unreviewed",
                        "evidence_records": [
                            {
                                "authority_level": "third_party_public",
                                "url": "https://example.test/speculative-route",
                            }
                        ],
                    }
                ],
            },
            {
                "source_entity_id": "vendor:1",
                "target_entity_id": "entity:official_parent",
                "rel_type": "beneficially_owned_by",
                "confidence": 0.84,
                "corroboration_count": 2,
                "data_sources": ["openownership", "gleif_lei"],
                "last_seen_at": "2026-03-25T00:00:00Z",
                "claim_records": [
                    {
                        "contradiction_state": "unreviewed",
                        "structured_fields": {"authority_level": "official_registry"},
                        "evidence_records": [
                            {
                                "authority_level": "official_registry",
                                "url": "https://example.test/official-parent",
                            }
                        ],
                    }
                ],
            },
        ],
    }

    paths = supplier_passport._top_control_paths(graph_summary, limit=2)

    assert paths[0]["target_name"] == "Atlas Holdings"
    assert paths[0]["intelligence_tier"] == "strong"
    assert paths[0]["intelligence_score"] > paths[1]["intelligence_score"]
    assert paths[1]["authority_bucket"] == "third_party_public_only"


def test_supplier_passport_marks_sam_identifiers_unverified_when_throttled(client):
    server = sys.modules["server"]
    case_id = _create_case(client, name="SAM Throttle Vendor")

    server.db.save_enrichment(
        case_id,
        {
            "overall_risk": "LOW",
            "summary": {"connectors_run": 3, "connectors_with_data": 2, "findings_total": 2},
            "identifiers": {"website": "https://example.test"},
            "connector_status": {
                "sam_gov": {
                    "has_data": True,
                    "error": "SAM.gov rate limit reached.",
                    "structured_fields": {
                        "sam_api_status": {
                            "entity_lookup": {
                                "status": 429,
                                "throttled": True,
                                "next_access_time": "2026-Mar-28 00:00:00+0000 UTC",
                            },
                            "exclusions_lookup": {
                                "status": 429,
                                "throttled": True,
                                "next_access_time": "2026-Mar-28 00:00:00+0000 UTC",
                            },
                        }
                    },
                }
            },
        },
    )

    import supplier_passport

    passport = supplier_passport.build_supplier_passport(case_id)

    assert passport is not None
    assert passport["identity"]["identifier_status"]["cage"]["state"] == "unverified"
    assert passport["identity"]["identifier_status"]["uei"]["state"] == "unverified"
    assert passport["identity"]["identifier_status"]["cage"]["next_access_time"] == "2026-Mar-28 00:00:00+0000 UTC"
    assert passport["identity"]["official_corroboration"]["blocked_connector_count"] == 1
    assert passport["identity"]["official_corroboration"]["connectors"][0]["source"] == "sam_gov"


def test_supplier_passport_attributes_public_identifier_sources_without_claiming_sam(client):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Public Identifier Vendor")

    server.db.save_enrichment(
        case_id,
        {
            "overall_risk": "LOW",
            "summary": {"connectors_run": 4, "connectors_with_data": 2, "findings_total": 3},
            "identifiers": {
                "cage": "0EA28",
                "uei": "V1HATBT1N7V5",
                "duns": "123456789",
                "ncage": "A1B2C",
                "website": "https://berry.example",
            },
            "identifier_sources": {
                "cage": ["public_search_ownership"],
                "uei": ["public_search_ownership"],
                "duns": ["public_search_ownership"],
                "ncage": ["public_search_ownership"],
                "website": ["public_search_ownership"],
            },
            "connector_status": {
                "public_search_ownership": {
                    "has_data": True,
                    "error": "",
                    "authority_level": "third_party_public",
                    "access_model": "search_snippet_only",
                    "structured_fields": {},
                },
                "sam_gov": {
                    "has_data": True,
                    "error": "SAM.gov rate limit reached.",
                    "authority_level": "official_registry",
                    "access_model": "public_api",
                    "structured_fields": {
                        "sam_api_status": {
                            "entity_lookup": {
                                "status": 429,
                                "throttled": True,
                                "next_access_time": "2026-Mar-28 00:00:00+0000 UTC",
                            }
                        }
                    },
                },
            },
        },
    )

    import supplier_passport

    passport = supplier_passport.build_supplier_passport(case_id)

    assert passport is not None
    assert passport["identity"]["identifier_status"]["cage"]["state"] == "verified_present"
    assert passport["identity"]["identifier_status"]["cage"]["source"] == "public_search_ownership"
    assert passport["identity"]["identifier_status"]["cage"]["authority_level"] == "third_party_public"
    assert passport["identity"]["identifier_status"]["cage"]["verification_label"] == "Publicly captured"
    assert passport["identity"]["identifier_status"]["uei"]["source"] == "public_search_ownership"
    assert passport["identity"]["identifier_status"]["uei"]["verification_tier"] == "publicly_captured"
    assert passport["identity"]["identifier_status"]["duns"]["value"] == "123456789"
    assert passport["identity"]["identifier_status"]["ncage"]["value"] == "A1B2C"
    assert passport["identity"]["official_corroboration"]["coverage_level"] == "public_only"
    assert passport["identity"]["official_corroboration"]["blocked_connector_count"] == 1
    assert passport["identity"]["official_corroboration"]["official_identifiers_verified"] == []


def test_score_vendor_result_persists_ownership_snapshot(client):
    server = sys.modules["server"]
    vendor_input = {
        "name": "OCI Snapshot Vendor",
        "country": "US",
        "ownership": {
            "publicly_traded": False,
            "state_owned": False,
            "beneficial_owner_known": False,
            "named_beneficial_owner_known": False,
            "controlling_parent_known": False,
            "owner_class_known": True,
            "owner_class": "Service-Disabled Veteran",
            "ownership_pct_resolved": 0.55,
            "control_resolution_pct": 0.35,
            "shell_layers": 0,
            "pep_connection": False,
            "foreign_ownership_pct": 0.0,
            "foreign_ownership_is_allied": True,
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
            "known_execs": 2,
            "adverse_media": 0,
            "pep_execs": 0,
            "litigation_history": 0,
        },
        "program": "dod_unclassified",
        "profile": "defense_acquisition",
    }

    _result, score_dict = server._score_vendor_result(vendor_input)

    assert score_dict["ownership"]["owner_class_known"] is True
    assert score_dict["ownership"]["owner_class"] == "Service-Disabled Veteran"
    assert score_dict["ownership"]["named_beneficial_owner_known"] is False
    assert score_dict["ownership"]["ownership_pct_resolved"] == pytest.approx(0.55)
    assert score_dict["ownership"]["control_resolution_pct"] == pytest.approx(0.35)


def test_supplier_passport_prefers_scored_ownership_snapshot_over_raw_vendor_input(client):
    server = sys.modules["server"]
    case_id = _create_case(
        client,
        name="Descriptor Ownership Vendor",
        extra_payload={
            "ownership": {
                "publicly_traded": False,
                "state_owned": False,
                "beneficial_owner_known": True,
                "named_beneficial_owner_known": True,
                "ownership_pct_resolved": 0.9,
                "control_resolution_pct": 0.7,
                "shell_layers": 0,
                "pep_connection": False,
            }
        },
    )

    server.db.save_enrichment(
        case_id,
        {
            "overall_risk": "LOW",
            "summary": {"connectors_run": 2, "connectors_with_data": 1, "findings_total": 1},
            "findings": [
                {
                    "source": "public_html_ownership",
                    "authority_level": "first_party_self_disclosed",
                    "confidence": 0.82,
                    "detail": "Owned by a Service-Disabled Veteran.",
                    "structured_fields": {"ownership_descriptor": "Service-Disabled Veteran"},
                    "artifact_ref": "https://www.ysginc.com/article",
                }
            ],
            "relationships": [],
            "identifiers": {"website": "https://www.ysginc.com"},
            "enriched_at": "2026-03-29T21:00:00Z",
        },
    )
    server.db.save_score(
        case_id,
        {
            "composite_score": 21,
            "is_hard_stop": False,
            "calibrated": {"calibrated_probability": 0.21, "calibrated_tier": "TIER_3_WATCH"},
            "ownership": {
                "publicly_traded": False,
                "state_owned": False,
                "beneficial_owner_known": False,
                "named_beneficial_owner_known": False,
                "controlling_parent_known": False,
                "owner_class_known": True,
                "owner_class": "Service-Disabled Veteran",
                "ownership_pct_resolved": 0.55,
                "control_resolution_pct": 0.35,
                "shell_layers": 0,
                "pep_connection": False,
                "foreign_ownership_pct": 0.0,
                "foreign_ownership_is_allied": True,
            },
        },
    )

    import supplier_passport

    passport = supplier_passport.build_supplier_passport(case_id)

    assert passport is not None
    assert passport["ownership"]["analyst_readout"] == (
        "Descriptor-only ownership evidence. No named beneficial owner resolved. "
        "Owner class: Service-Disabled Veteran."
    )
    assert passport["ownership"]["profile"]["ownership_pct_resolved"] == pytest.approx(0.55)
    assert passport["ownership"]["profile"]["control_resolution_pct"] == pytest.approx(0.35)
    assert passport["ownership"]["profile"]["named_beneficial_owner_known"] is False
    assert passport["ownership"]["oci"]["descriptor_only"] is True
    assert passport["ownership"]["oci"]["ownership_gap"] == "descriptor_only_owner_class"
    assert passport["ownership"]["oci"]["ownership_resolution_pct"] == pytest.approx(0.55)
    assert passport["ownership"]["oci"]["control_resolution_pct"] == pytest.approx(0.35)
    assert "ownership_control" in passport["graph"]["intelligence"]["missing_required_edge_families"]
    assert passport["graph"]["intelligence"]["externally_satisfied_edge_families"] == []


def test_create_case_primes_ai_with_non_blocking_warmup(client, monkeypatch):
    server = sys.modules["server"]
    primed = {}

    def fake_prime(case_id_arg, user_id_arg, wait_seconds=99, poll_seconds=99.0):
        primed["case_id"] = case_id_arg
        primed["user_id"] = user_id_arg
        primed["wait_seconds"] = wait_seconds
        primed["poll_seconds"] = poll_seconds
        return {"status": "pending", "job_id": "ai-job-create"}

    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", fake_prime)

    response = client.post(
        "/api/cases",
        json={
            "name": "AI Primed On Create Vendor",
            "country": "US",
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

    assert response.status_code == 201
    payload = response.get_json()
    assert primed == {
        "case_id": payload["case_id"],
        "user_id": "dev",
        "wait_seconds": 0,
        "poll_seconds": 0.0,
    }


def test_graph_runtime_reports_active_database_paths(client, tmp_path):
    response = client.get("/api/graph/runtime")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data_dir"]["path"] == str((tmp_path / "data").resolve())
    assert payload["main_db"]["path"] == str((tmp_path / "xiphos-test.db").resolve())
    assert payload["kg_db"]["path"] == str((tmp_path / "knowledge-graph.db").resolve())
    assert payload["kg_db"]["tables"]["kg_entities"] == 0


def test_graph_provenance_endpoints_return_sources(client):
    case_id = _create_case(client, name="Graph Provenance Vendor")
    server = sys.modules["server"]
    server.kg.init_kg_db()
    alpha = ResolvedEntity(
        id="entity:test-alpha",
        canonical_name="Alpha Systems",
        entity_type="company",
        aliases=[],
        identifiers={},
        country="US",
        sources=["test"],
        confidence=0.9,
        last_updated="2026-03-30T19:00:00Z",
    )
    beta = ResolvedEntity(
        id="entity:test-beta",
        canonical_name="Beta Controls",
        entity_type="holding_company",
        aliases=[],
        identifiers={},
        country="US",
        sources=["test"],
        confidence=0.9,
        last_updated="2026-03-30T19:00:00Z",
    )
    server.kg.save_entity(alpha)
    server.kg.save_entity(beta)
    relationship_id = server.kg.save_relationship(
        "entity:test-alpha",
        "entity:test-beta",
        "owned_by",
        confidence=0.91,
        data_source="gleif_bods_ownership_fixture",
        evidence="Modeled ownership statement",
        observed_at="2026-03-30T18:55:00Z",
        evidence_url="https://example.test/ownership",
        artifact_ref="fixture://ownership/alpha-beta",
        evidence_title="Ownership page",
        source_class="analyst_fixture",
        authority_level="standards_modeled_fixture",
        access_model="local_json_fixture",
        vendor_id=case_id,
    )

    entity_resp = client.get("/api/graph/entity/entity:test-alpha/provenance")
    assert entity_resp.status_code == 200
    entity_body = entity_resp.get_json()
    assert entity_body["entity"]["canonical_name"] == "Alpha Systems"
    assert entity_body["corroboration_count"] >= 1
    assert entity_body["sources"][0]["connector"] == "gleif_bods_ownership_fixture"

    rel_resp = client.get(f"/api/graph/relationship/{relationship_id}/provenance")
    assert rel_resp.status_code == 200
    rel_body = rel_resp.get_json()
    assert rel_body["relationship"]["rel_type"] == "owned_by"
    assert rel_body["sources"][0]["url"] == "https://example.test/ownership"
    assert rel_body["corroboration_count"] >= 1


def test_portfolio_snapshot_handles_mixed_alert_timestamp_types(client, monkeypatch):
    server = sys.modules["server"]
    recent_dt = datetime.utcnow() - timedelta(days=1)
    stale_str = (datetime.utcnow() - timedelta(days=20)).isoformat()

    monkeypatch.setattr(
        server.db,
        "list_alerts",
        lambda limit=500, unresolved_only=True: [
            {"created_at": recent_dt},
            {"created_at": stale_str},
        ],
    )

    response = client.get("/api/portfolio/snapshot")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["anomaly_count"] == 1


def test_dossier_pdf_handles_datetime_decision_timestamps(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Datetime PDF Vendor")

    decision_response = client.post(
        f"/api/cases/{case_id}/decision",
        json={"decision": "approve", "reason": "datetime regression"},
    )
    assert decision_response.status_code == 201

    original_get_decisions = server.db.get_decisions

    def _get_decisions_with_datetime(vendor_id, limit=10):
        decisions = original_get_decisions(vendor_id, limit=limit)
        if decisions:
            decisions[0]["created_at"] = datetime.utcnow()
        return decisions

    monkeypatch.setattr(server.db, "get_decisions", _get_decisions_with_datetime)
    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *args, **kwargs: {"status": "queued"})

    response = client.post(f"/api/cases/{case_id}/dossier-pdf", json={})

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/pdf")


def test_dossier_pdf_premium_cover_includes_executive_strip_and_snapshot(client, monkeypatch):
    from pypdf import PdfReader

    server = sys.modules["server"]
    case_id = _create_case(client, name="Premium PDF Vendor")
    server.db.save_enrichment(
        case_id,
        {
            "vendor_name": "Premium PDF Vendor",
            "country": "US",
            "overall_risk": "MEDIUM",
            "enriched_at": "2026-03-30T19:15:00Z",
            "summary": {
                "findings_total": 1,
                "critical": 0,
                "high": 1,
                "medium": 0,
                "connectors_run": 2,
                "connectors_with_data": 1,
                "errors": 0,
            },
            "findings": [
                {
                    "source": "sam_gov",
                    "category": "contracts",
                    "title": "Active contracting signal",
                    "detail": "Prime contract evidence is present and requires analyst review.",
                    "severity": "high",
                    "confidence": 0.91,
                }
            ],
            "identifiers": {},
            "identifier_sources": {},
            "relationships": [],
            "risk_signals": [],
            "connector_status": {
                "sam_gov": {"has_data": True, "findings_count": 1, "elapsed_ms": 8, "error": None},
                "rss_public": {"has_data": False, "findings_count": 0, "elapsed_ms": 4, "error": None},
            },
            "errors": [],
            "evidence_lanes": {"source_classes": {}, "authority_levels": {}, "access_models": {}},
        },
    )

    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *args, **kwargs: {"status": "queued"})
    response = client.post(f"/api/cases/{case_id}/dossier-pdf", json={})

    assert response.status_code == 200
    pdf_text = "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(io.BytesIO(response.data)).pages
    ).lower()
    assert "top risk signal" in pdf_text
    assert "immediate next move" in pdf_text
    assert "evidence snapshot" in pdf_text


def test_server_entrypoint_is_after_last_route_definition():
    server_path = os.path.join(BACKEND_DIR, "server.py")
    source = open(server_path, "r", encoding="utf-8").read().splitlines()

    entrypoint_line = next(
        index for index, line in enumerate(source, 1) if line.strip() == 'if __name__ == "__main__":'
    )
    last_route_line = max(
        index for index, line in enumerate(source, 1) if line.lstrip().startswith("@app.route(")
    )

    assert entrypoint_line > last_route_line


def test_graph_ingest_persons_route_replays_case_screenings(client):
    import person_screening as ps  # type: ignore

    case_id = _create_case(client, name="Retroactive Person Graph Vendor")
    ps.init_person_screening_db()
    ps.screen_person(
        name="Jane Retro",
        nationalities=["GB"],
        employer="Acme Systems",
        item_classification="USML-Aircraft",
        case_id=case_id,
        screened_by="test-suite",
    )

    response = client.post(f"/api/graph/ingest-persons/{case_id}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["case_id"] == case_id
    assert payload["persons_ingested"] == 1
    assert payload["relationships_created"] >= 3
    assert payload["details"][0]["person_name"] == "Jane Retro"

    graph_response = client.get(f"/api/cases/{case_id}/graph?depth=1")
    assert graph_response.status_code == 200
    graph = graph_response.get_json()
    names = {entity["canonical_name"] for entity in graph["entities"]}
    assert "Jane Retro" in names
    assert "Acme Systems" in names


def test_authenticated_case_creation_supports_batch_training_runs(auth_client):
    client = auth_client["client"]
    headers = auth_client["headers"]

    created_ids = []
    for index in range(55):
        created_ids.append(
            _create_case(
                client,
                name=f"Batch Training Vendor {index:02d}",
                headers=headers,
            )
        )

    assert len(created_ids) == 55
    assert len(set(created_ids)) == 55


def test_case_detail_route_exposes_workflow_control_summary(client):
    case_id = _create_case(
        client,
        name="Export Control Summary Vendor",
        country="DE",
        extra_payload={
            "program": "dual_use_ear",
            "profile": "itar_trade_compliance",
            "export_authorization": {
                "request_type": "technical_data_release",
                "recipient_name": "Export Control Summary Vendor",
                "destination_country": "DE",
                "jurisdiction_guess": "ear",
                "classification_guess": "3A001",
                "item_or_data_summary": "Controlled avionics interface drawings",
                "end_use_summary": "Integration review",
            },
        },
    )

    resp = client.get(f"/api/cases/{case_id}")
    assert resp.status_code == 200

    body = resp.get_json()
    control = body["workflow_control_summary"]
    assert control["lane"] == "export"
    assert control["support_level"] == "triage_only"
    assert control["action_owner"] == "Trade compliance / export counsel"
    assert "government approval" in control["decision_boundary"]
    assert any("Customer export artifact" in item for item in control["missing_inputs"])


def test_case_list_route_exposes_explicit_workflow_lane(client):
    default_case_id = _create_case(client, name="Counterparty Lane Vendor")
    export_case_id = _create_case(
        client,
        name="Export Lane Vendor",
        country="DE",
        extra_payload={
            "program": "dual_use_ear",
            "profile": "itar_trade_compliance",
            "export_authorization": {
                "request_type": "technical_data_release",
                "recipient_name": "Export Lane Vendor",
                "destination_country": "DE",
                "jurisdiction_guess": "ear",
                "classification_guess": "3A001",
                "item_or_data_summary": "Guidance software build and interface drawings",
                "end_use_summary": "Dual-use avionics support",
            },
        },
    )

    resp = client.get("/api/cases")
    assert resp.status_code == 200

    cases = {case["id"]: case for case in resp.get_json()["cases"]}
    assert cases[default_case_id]["workflow_lane"] == "counterparty"
    assert cases[export_case_id]["workflow_lane"] == "export"


def test_beta_feedback_and_summary_routes_capture_signal(client):
    case_id = _create_case(client, name="Beta Ops Vendor")

    feedback_resp = client.post(
        "/api/beta/feedback",
        json={
            "summary": "Cyber upload copy is unclear",
            "details": "The upload step needs a clearer next action after the file is accepted.",
            "category": "confusion",
            "severity": "medium",
            "workflow_lane": "cyber",
            "screen": "case",
            "case_id": case_id,
            "metadata": {"shell_lane": "cyber"},
        },
    )
    assert feedback_resp.status_code == 201
    feedback_id = feedback_resp.get_json()["feedback_id"]
    assert feedback_id > 0

    event_resp = client.post(
        "/api/beta/events",
        json={
            "event_name": "screen_viewed",
            "workflow_lane": "cyber",
            "screen": "case",
            "case_id": case_id,
            "metadata": {"shell_lane": "cyber"},
        },
    )
    assert event_resp.status_code == 201

    list_resp = client.get("/api/beta/feedback?limit=10")
    assert list_resp.status_code == 200
    feedback = list_resp.get_json()["feedback"]
    assert len(feedback) == 1
    assert feedback[0]["summary"] == "Cyber upload copy is unclear"
    assert feedback[0]["workflow_lane"] == "cyber"

    summary_resp = client.get("/api/beta/ops/summary?hours=24")
    assert summary_resp.status_code == 200
    summary = summary_resp.get_json()
    assert summary["open_feedback_count"] == 1
    assert summary["feedback_last_24h"] == 1
    assert summary["recent_event_count"] == 1
    assert any(item["workflow_lane"] == "cyber" for item in summary["feedback_by_lane"])
    assert any(item["event_name"] == "screen_viewed" for item in summary["event_counts"])


def test_beta_ops_summary_requires_auditor_or_admin(auth_client):
    client = auth_client["client"]
    headers = auth_client["headers"]

    feedback_resp = client.post(
        "/api/beta/feedback",
        headers=headers,
        json={
            "summary": "Need clearer export CTA",
            "category": "request",
            "severity": "low",
            "workflow_lane": "export",
            "screen": "helios",
        },
    )
    assert feedback_resp.status_code == 201

    summary_resp = client.get("/api/beta/ops/summary?hours=24", headers=headers)
    assert summary_resp.status_code == 403


def test_case_detail_route_includes_export_authorization_context(client):
    case_id = _create_case(
        client,
        name="Helios Export Recipient",
        country="DE",
        extra_payload={
            "program": "dual_use_ear",
            "profile": "itar_trade_compliance",
            "export_authorization": {
                "request_type": "technical_data_release",
                "recipient_name": "Helios Export Recipient",
                "destination_country": "DE",
                "jurisdiction_guess": "ear",
                "classification_guess": "3A001",
                "item_or_data_summary": "Radar processing source code and interface drawings",
                "end_use_summary": "Evaluation for dual-use avionics integration support",
                "foreign_person_nationalities": ["DE", "PL"],
            },
        },
    )

    resp = client.get(f"/api/cases/{case_id}")
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["profile"] == "itar_trade_compliance"
    assert body["export_authorization"]["request_type"] == "technical_data_release"
    assert body["export_authorization"]["destination_country"] == "DE"
    assert body["export_authorization"]["foreign_person_nationalities"] == ["DE", "PL"]
    assert body["export_authorization_guidance"]["source"] == "bis_rules_engine"
    assert body["export_authorization_guidance"]["posture"] in {
        "likely_nlr",
        "likely_license_required",
        "likely_exception_or_exemption",
        "insufficient_confidence",
        "escalate",
    }
    assert body["export_authorization_guidance"]["official_references"]
    assert body["export_evidence_summary"]["posture"] == body["export_authorization_guidance"]["posture"]
    assert "technical data release" in body["export_evidence_summary"]["narrative"].lower()
    assert "3a001" in body["export_evidence_summary"]["narrative"].lower()


def test_export_artifact_routes_store_and_return_customer_records(client):
    case_id = _create_case(client, name="Export Artifact Vendor")

    upload_resp = client.post(
        f"/api/cases/{case_id}/export-artifacts",
        data={
            "artifact_type": "export_classification_memo",
            "declared_classification": "3A001",
            "declared_jurisdiction": "ear",
            "notes": "Customer classification memo",
            "file": (io.BytesIO(b"ECCN 3A001 memo with CCATS history and foreign person review."), "classification.txt"),
        },
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201
    artifact = upload_resp.get_json()["artifact"]
    assert artifact["artifact_type"] == "export_classification_memo"
    assert artifact["source_system"] == "export_artifact_upload"
    assert "3A001" in artifact["structured_fields"]["detected_classifications"]

    list_resp = client.get(f"/api/cases/{case_id}/export-artifacts")
    assert list_resp.status_code == 200
    records = list_resp.get_json()["artifacts"]
    assert len(records) == 1
    assert records[0]["id"] == artifact["id"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    latest = case_resp.get_json()["latest_export_artifact"]
    assert latest["id"] == artifact["id"]
    assert case_resp.get_json()["export_evidence_summary"] is None

    download_resp = client.get(f"/api/cases/{case_id}/export-artifacts/{artifact['id']}")
    assert download_resp.status_code == 200
    assert download_resp.data.startswith(b"ECCN 3A001")


def test_export_evidence_influences_rescore_gate_outcome(client):
    case_id = _create_case(
        client,
        name="Export Review Vendor",
        country="US",
        extra_payload={
            "program": "cat_xi_electronics",
            "profile": "itar_trade_compliance",
            "export_authorization": {
                "request_type": "foreign_person_access",
                "recipient_name": "Export Review Vendor",
                "destination_country": "US",
                "jurisdiction_guess": "itar",
                "classification_guess": "Category XI",
                "item_or_data_summary": "ITAR technical data package and interface documentation",
                "end_use_summary": "Engineering support access for program sustainment",
                "access_context": "Foreign person access to controlled technical data without implemented TCP",
                "foreign_person_nationalities": ["IR"],
            },
        },
    )

    rescore_resp = client.post(f"/api/cases/{case_id}/score", json={})
    assert rescore_resp.status_code == 200
    calibrated = rescore_resp.get_json()["calibrated"]
    assert calibrated["regulatory_status"] == "NON_COMPLIANT"
    finding = next(
        item for item in calibrated["regulatory_findings"]
        if item["name"] == "Deemed Export Risk"
    )
    assert "High deemed export risk" in finding["explanation"]
    assert "IR" in finding["explanation"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    export_summary = case_resp.get_json()["export_evidence_summary"]
    assert export_summary["posture"] == "likely_prohibited"


def test_foci_artifact_routes_store_and_surface_latest_customer_records(client):
    case_id = _create_case(client, name="FOCI Artifact Vendor")

    upload_resp = client.post(
        f"/api/cases/{case_id}/foci-artifacts",
        data={
            "artifact_type": "foci_mitigation_instrument",
            "declared_foreign_owner": "Allied Parent Holdings",
            "declared_foreign_country": "GB",
            "declared_foreign_ownership_pct": "25%",
            "declared_mitigation_status": "MITIGATED",
            "declared_mitigation_type": "SSA",
            "file": (
                io.BytesIO(
                    b"Special Security Agreement covering 25% foreign ownership and board observer governance rights."
                ),
                "ssa-summary.txt",
            ),
        },
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201
    artifact = upload_resp.get_json()["artifact"]
    assert artifact["artifact_type"] == "foci_mitigation_instrument"
    assert artifact["source_system"] == "foci_artifact_upload"
    assert artifact["structured_fields"]["declared_foreign_owner"] == "Allied Parent Holdings"
    assert artifact["structured_fields"]["declared_mitigation_type"] == "SSA"
    assert artifact["structured_fields"]["max_ownership_percent_mention"] == 25.0

    list_resp = client.get(f"/api/cases/{case_id}/foci-artifacts")
    assert list_resp.status_code == 200
    records = list_resp.get_json()["artifacts"]
    assert len(records) == 1
    assert records[0]["id"] == artifact["id"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    latest = case_resp.get_json()["latest_foci_artifact"]
    assert latest["id"] == artifact["id"]
    assert latest["structured_fields"]["declared_foreign_country"] == "GB"

    download_resp = client.get(f"/api/cases/{case_id}/foci-artifacts/{artifact['id']}")
    assert download_resp.status_code == 200
    assert download_resp.data.startswith(b"Special Security Agreement")

    assert latest["structured_fields"]["declared_foreign_country"] == "GB"


def test_customer_foci_evidence_influences_rescore_gate_outcome(client):
    case_id = _create_case(client, name="FOCI Scoring Vendor")

    upload_resp = client.post(
        f"/api/cases/{case_id}/foci-artifacts",
        data={
            "artifact_type": "foci_ownership_chart",
            "declared_foreign_owner": "Allied Parent Holdings",
            "declared_foreign_country": "GB",
            "declared_foreign_ownership_pct": "25%",
            "file": (
                io.BytesIO(
                    b"Ownership chart showing 25% foreign ownership by Allied Parent Holdings in GB with board observer rights."
                ),
                "ownership-chart.txt",
            ),
        },
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201

    rescore_resp = client.post(f"/api/cases/{case_id}/score", json={})
    assert rescore_resp.status_code == 200
    calibrated = rescore_resp.get_json()["calibrated"]
    assert calibrated["regulatory_status"] == "REQUIRES_REVIEW"
    foci_finding = next(
        finding for finding in calibrated["regulatory_findings"]
        if finding["name"] == "FOCI"
    )
    assert "25%" in foci_finding["explanation"]
    assert "GB" in foci_finding["explanation"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    foci_summary = case_resp.get_json()["foci_evidence_summary"]
    assert foci_summary["foreign_owner"] == "Allied Parent Holdings"
    assert foci_summary["foreign_ownership_pct_display"] == "25%"


def test_sprs_import_routes_store_and_surface_latest_customer_records(client):
    case_id = _create_case(client, name="Cyber Trust Vendor")

    upload_resp = client.post(
        f"/api/cases/{case_id}/sprs-imports",
        data={
            "file": (
                io.BytesIO(
                    b"supplier_name,sprs_score,assessment_date,status,current_cmmc_level,poam\n"
                    b"Cyber Trust Vendor,103,2026-03-01,Conditional,2,Yes\n"
                ),
                "sprs-export.csv",
            ),
        },
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201
    artifact = upload_resp.get_json()["import"]
    assert artifact["artifact_type"] == "sprs_export"
    assert artifact["source_system"] == "sprs_import"
    assert artifact["structured_fields"]["summary"]["assessment_score"] == 103
    assert artifact["structured_fields"]["summary"]["current_cmmc_level"] == 2
    assert artifact["structured_fields"]["summary"]["poam_active"] is True

    list_resp = client.get(f"/api/cases/{case_id}/sprs-imports")
    assert list_resp.status_code == 200
    records = list_resp.get_json()["imports"]
    assert len(records) == 1
    assert records[0]["id"] == artifact["id"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    latest = case_resp.get_json()["latest_sprs_import"]
    assert latest["id"] == artifact["id"]
    assert latest["structured_fields"]["summary"]["matched_supplier_name"] == "Cyber Trust Vendor"

    download_resp = client.get(f"/api/cases/{case_id}/sprs-imports/{artifact['id']}")
    assert download_resp.status_code == 200
    assert download_resp.data.startswith(b"supplier_name,sprs_score")


def test_customer_cyber_evidence_influences_rescore_gate_outcome(client):
    case_id = _create_case(client, name="CMMC Review Vendor")

    upload_resp = client.post(
        f"/api/cases/{case_id}/sprs-imports",
        data={
            "file": (
                io.BytesIO(
                    b"supplier_name,sprs_score,assessment_date,status,current_cmmc_level,poam\n"
                    b"CMMC Review Vendor,82,2026-03-02,Conditional,1,Yes\n"
                ),
                "sprs-export.csv",
            ),
        },
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201

    rescore_resp = client.post(f"/api/cases/{case_id}/score", json={})
    assert rescore_resp.status_code == 200
    calibrated = rescore_resp.get_json()["calibrated"]
    assert calibrated["regulatory_status"] == "REQUIRES_REVIEW"
    cmmc_finding = next(
        finding for finding in calibrated["regulatory_findings"]
        if finding["name"] == "CMMC 2.0"
    )
    assert "Level 1" in cmmc_finding["explanation"]
    assert "Level 2" in cmmc_finding["explanation"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    cyber_summary = case_resp.get_json()["cyber_evidence_summary"]
    assert cyber_summary["current_cmmc_level"] == 1
    assert cyber_summary["poam_active"] is True


def test_oscal_artifact_routes_store_and_surface_latest_customer_records(client):
    case_id = _create_case(client, name="Cyber Plan Vendor")

    upload_resp = client.post(
        f"/api/cases/{case_id}/oscal-artifacts",
        data={
            "file": (
                io.BytesIO(
                    b'{"plan-of-action-and-milestones":{"metadata":{"title":"Supplier POA&M"},'
                    b'"system-characteristics":{"system-name":"Supplier Secure Environment"},'
                    b'"poam-items":[{"id":"poam-1","title":"Encrypt removable media","status":"open","due-date":"2026-04-15","control-id":"sc-28"}]}}'
                ),
                "poam.json",
            ),
        },
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201
    artifact = upload_resp.get_json()["artifact"]
    assert artifact["artifact_type"] == "oscal_poam"
    assert artifact["source_system"] == "oscal_upload"
    assert artifact["structured_fields"]["summary"]["open_poam_items"] == 1

    list_resp = client.get(f"/api/cases/{case_id}/oscal-artifacts")
    assert list_resp.status_code == 200
    records = list_resp.get_json()["artifacts"]
    assert len(records) == 1
    assert records[0]["id"] == artifact["id"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    latest = case_resp.get_json()["latest_oscal_artifact"]
    assert latest["id"] == artifact["id"]
    assert latest["structured_fields"]["summary"]["system_name"] == "Supplier Secure Environment"

    download_resp = client.get(f"/api/cases/{case_id}/oscal-artifacts/{artifact['id']}")
    assert download_resp.status_code == 200
    assert download_resp.data.startswith(b'{"plan-of-action-and-milestones"')


def test_nvd_overlay_routes_store_and_surface_latest_generated_records(client, monkeypatch):
    case_id = _create_case(client, name="Cyber Product Vendor")

    import nvd_overlay  # type: ignore

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, params=None, headers=None, timeout=0):
        params = params or {}
        if "cpes/2.0" in url:
            return FakeResponse(
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
        if "cves/2.0" in url:
            return FakeResponse(
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
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(nvd_overlay.requests, "get", fake_get)

    overlay_resp = client.post(
        f"/api/cases/{case_id}/nvd-overlays",
        json={"product_terms": ["Secure Portal"]},
    )
    assert overlay_resp.status_code == 201
    artifact = overlay_resp.get_json()["overlay"]
    assert artifact["artifact_type"] == "nvd_overlay"
    assert artifact["source_system"] == "nvd_overlay"
    assert artifact["structured_fields"]["summary"]["unique_cve_count"] == 1
    assert artifact["structured_fields"]["summary"]["kev_flagged_cve_count"] == 1

    list_resp = client.get(f"/api/cases/{case_id}/nvd-overlays")
    assert list_resp.status_code == 200
    records = list_resp.get_json()["overlays"]
    assert len(records) == 1
    assert records[0]["id"] == artifact["id"]

    case_resp = client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    latest = case_resp.get_json()["latest_nvd_overlay"]
    assert latest["id"] == artifact["id"]
    assert latest["structured_fields"]["product_terms"] == ["Secure Portal"]

    download_resp = client.get(f"/api/cases/{case_id}/nvd-overlays/{artifact['id']}")
    assert download_resp.status_code == 200
    assert b'"unique_cve_count": 1' in download_resp.data


def test_enrichment_api_includes_evidence_lane_metadata(client):
    from osint import EnrichmentResult, Finding
    from osint import enrichment

    server = sys.modules["server"]
    case_id = _create_case(client, name="Evidence Lane Vendor")

    report = enrichment._build_report(
        "Evidence Lane Vendor",
        "US",
        [
            EnrichmentResult(
                source="sam_gov",
                vendor_name="Evidence Lane Vendor",
                findings=[
                    Finding(
                        source="sam_gov",
                        category="registration",
                        title="Active SAM registration",
                        detail="UEI and CAGE confirmed",
                        severity="low",
                        confidence=0.93,
                    )
                ],
                elapsed_ms=5,
            )
        ],
        time.time(),
    )
    server.db.save_enrichment(case_id, report)

    resp = client.get(f"/api/cases/{case_id}/enrichment")
    assert resp.status_code == 200
    body = resp.get_json()

    assert body["findings"][0]["source_class"] == "public_connector"
    assert body["findings"][0]["authority_level"] == "official_registry"
    assert body["connector_status"]["sam_gov"]["access_model"] == "public_api"
    assert body["evidence_lanes"]["source_classes"]["public_connector"] == 1


def test_enrichment_route_augments_connector_status_with_freshness(client):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Connector Freshness Vendor")
    report = {
        "vendor_name": "Connector Freshness Vendor",
        "country": "US",
        "overall_risk": "LOW",
        "enriched_at": "2026-03-30T19:15:00Z",
        "summary": {
            "findings_total": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "connectors_run": 1,
            "connectors_with_data": 0,
            "errors": 0,
        },
        "findings": [],
        "identifiers": {},
        "identifier_sources": {},
        "relationships": [],
        "risk_signals": [],
        "connector_status": {
            "sam_gov": {"has_data": False, "findings_count": 0, "elapsed_ms": 5, "error": None},
        },
        "errors": [],
        "evidence_lanes": {"source_classes": {}, "authority_levels": {}, "access_models": {}},
    }
    server.db.save_enrichment(case_id, report)

    resp = client.get(f"/api/cases/{case_id}/enrichment")
    assert resp.status_code == 200
    body = resp.get_json()
    status = body["connector_status"]["sam_gov"]
    assert status["last_checked_at"] == "2026-03-30T19:15:00Z"
    assert "next_scheduled_at" in status


def test_case_monitor_route_queues_background_check(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Queued Monitor Vendor")
    trigger_calls = []

    class FakeScheduler:
        def trigger_sweep(self, vendor_ids=None):
            trigger_calls.append(vendor_ids)
            return "sweep-123"

        def get_sweep_status(self, sweep_id):
            assert sweep_id == "sweep-123"
            return {"status": "queued", "triggered_at": "2026-03-23T00:00:00Z"}

    monkeypatch.setattr(server, "HAS_MONITOR_SCHEDULER", True)
    monkeypatch.setattr(server, "_get_monitor_scheduler", lambda: FakeScheduler())

    resp = client.post(f"/api/cases/{case_id}/monitor")
    assert resp.status_code == 202

    body = resp.get_json()
    assert body["mode"] == "async"
    assert body["vendor_id"] == case_id
    assert body["sweep_id"] == "sweep-123"
    assert body["status"] == "queued"
    assert body["status_url"].endswith(f"/api/cases/{case_id}/monitor/sweep-123")
    assert trigger_calls == [[case_id]]


def test_case_monitor_status_route_includes_latest_result(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Queued Monitor Status Vendor")
    server.db.save_monitoring_log(
        vendor_id=case_id,
        previous_risk="TIER_4_CLEAR",
        current_risk="TIER_4_APPROVED",
        risk_changed=True,
        new_findings_count=2,
        resolved_findings_count=1,
    )

    class FakeScheduler:
        def get_sweep_status(self, sweep_id):
            assert sweep_id == "sweep-456"
            return {
                "status": "completed",
                "started_at": "2026-03-23T00:00:00Z",
                "completed_at": "2026-03-23T00:00:10Z",
                "total_vendors": 1,
                "processed": 1,
                "risk_changes": 1,
                "new_alerts": 1,
            }

    monkeypatch.setattr(server, "HAS_MONITOR_SCHEDULER", True)
    monkeypatch.setattr(server, "_get_monitor_scheduler", lambda: FakeScheduler())

    resp = client.get(f"/api/cases/{case_id}/monitor/sweep-456")
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["status"] == "completed"
    assert body["vendor_id"] == case_id
    assert body["latest_check"]["vendor_id"] == case_id
    assert body["latest_score"]["tier"] is not None


def test_case_monitoring_history_route_returns_recent_checks(client):
    case_id = _create_case(client, name="Monitoring History Vendor")

    server = sys.modules["server"]
    server.db.save_monitoring_log(
        vendor_id=case_id,
        previous_risk="TIER_4_CLEAR",
        current_risk="TIER_4_CLEAR",
        risk_changed=False,
        new_findings_count=0,
        resolved_findings_count=1,
    )
    time.sleep(0.01)
    server.db.save_monitoring_log(
        vendor_id=case_id,
        previous_risk="TIER_4_CLEAR",
        current_risk="TIER_4_APPROVED",
        risk_changed=True,
        new_findings_count=2,
        resolved_findings_count=0,
    )

    resp = client.get(f"/api/cases/{case_id}/monitoring?limit=5")
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["vendor_id"] == case_id
    assert body["vendor_name"] == "Monitoring History Vendor"
    assert len(body["monitoring_history"]) == 2
    assert body["monitoring_history"][0]["risk_changed"] in {0, 1, False, True}
    assert body["monitoring_history"][0]["vendor_id"] == case_id
    assert "checked_at" in body["monitoring_history"][0]


def test_case_monitor_run_history_route_returns_delta_summary_and_scores(client):
    case_id = _create_case(client, name="Monitor Run History Vendor")

    server = sys.modules["server"]
    server.db.save_monitoring_log(
        vendor_id=case_id,
        run_id="sync:test-run",
        previous_risk="TIER_4_CLEAR",
        current_risk="TIER_3_CONDITIONAL",
        risk_changed=True,
        change_type="score_change",
        status="completed",
        score_before=18.5,
        score_after=27.0,
        new_findings_count=2,
        resolved_findings_count=1,
        delta_summary="Score increased +8.5%, Tier TIER_4_CLEAR -> TIER_3_CONDITIONAL, 2 new findings",
        sources_triggered=["ofac_sdn", "sam_gov"],
        started_at="2026-03-30T19:00:00Z",
        completed_at="2026-03-30T19:00:10Z",
    )

    resp = client.get(f"/api/cases/{case_id}/monitor/history?limit=5")
    assert resp.status_code == 200
    body = resp.get_json()

    assert body["vendor_id"] == case_id
    assert body["vendor_name"] == "Monitor Run History Vendor"
    assert len(body["runs"]) == 1
    run = body["runs"][0]
    assert run["run_id"] == "sync:test-run"
    assert run["status"] == "completed"
    assert run["score_before"] == 18.5
    assert run["score_after"] == 27.0
    assert run["new_findings_count"] == 2
    assert run["sources_triggered"] == ["ofac_sdn", "sam_gov"]
    assert "Score increased" in run["delta_summary"]


def test_monitor_changes_and_portfolio_changes_include_summary_metadata(client):
    case_id = _create_case(client, name="Portfolio Delta Vendor")
    server = sys.modules["server"]
    server.db.save_monitoring_log(
        vendor_id=case_id,
        run_id="sync:portfolio",
        previous_risk="TIER_4_CLEAR",
        current_risk="TIER_4_CLEAR",
        risk_changed=False,
        change_type="new_finding",
        status="completed",
        score_before=12.0,
        score_after=12.0,
        new_findings_count=1,
        delta_summary="1 new finding, Sources triggered: ofac_sdn",
        sources_triggered=["ofac_sdn"],
    )

    resp = client.get("/api/monitor/changes?limit=5")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["changes"]) == 1
    change = body["changes"][0]
    assert change["vendor_name"] == "Portfolio Delta Vendor"
    assert change["change_type"] == "new_finding"
    assert change["sources_triggered"] == ["ofac_sdn"]
    assert "new finding" in change["delta_summary"].lower()

    portfolio_resp = client.get("/api/portfolio/changes?since=24h&limit=5")
    assert portfolio_resp.status_code == 200
    portfolio_body = portfolio_resp.get_json()
    assert portfolio_body["total_count"] >= 1
    assert portfolio_body["changed"][0]["case_id"] == case_id
    assert portfolio_body["changed"][0]["name"] == "Portfolio Delta Vendor"
    assert portfolio_body["changed"][0]["change_type"] == "new_finding"


def test_dossier_route_primes_ai_and_uses_cached_generation_by_default(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Dossier Hydration Vendor")
    captured = {}
    primed = {}

    def fake_generate_dossier(vendor_id, user_id="", hydrate_ai=False):
        captured["vendor_id"] = vendor_id
        captured["user_id"] = user_id
        captured["hydrate_ai"] = hydrate_ai
        return "<html><body>Axiom Assessment</body></html>"

    def fake_prime(case_id_arg, user_id_arg, **kwargs):
        primed["case_id"] = case_id_arg
        primed["user_id"] = user_id_arg
        primed["kwargs"] = kwargs
        return {"status": "queued"}

    monkeypatch.setattr(server, "generate_dossier", fake_generate_dossier)
    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", fake_prime)

    resp = client.post(f"/api/cases/{case_id}/dossier", json={"format": "html"})
    assert resp.status_code == 200
    assert captured == {
        "vendor_id": case_id,
        "user_id": "dev",
        "hydrate_ai": True,
    }
    assert primed == {
        "case_id": case_id,
        "user_id": "dev",
        "kwargs": {"wait_seconds": 0, "poll_seconds": 0.0},
    }
    assert "Axiom Assessment" in resp.get_data(as_text=True)


def test_dossier_route_returns_cache_busting_download_url(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Dossier Cache Bust Vendor")

    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *args, **kwargs: {"status": "queued"})
    monkeypatch.setattr(
        server,
        "generate_dossier",
        lambda vendor_id, user_id="", hydrate_ai=False: "<html><body>fresh dossier</body></html>",
    )

    resp = client.post(f"/api/cases/{case_id}/dossier", json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert f"/api/dossiers/dossier-{case_id}-" in body["download_url"]


def test_dossier_pdf_route_primes_ai_and_uses_cached_generation_by_default(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="PDF Dossier Hydration Vendor")
    captured = {}
    primed = {}

    def fake_generate_pdf_dossier(vendor_id, user_id="", hydrate_ai=False):
        captured["vendor_id"] = vendor_id
        captured["user_id"] = user_id
        captured["hydrate_ai"] = hydrate_ai
        return b"%PDF-1.4 mocked"

    def fake_prime(case_id_arg, user_id_arg):
        primed["case_id"] = case_id_arg
        primed["user_id"] = user_id_arg
        return {"status": "queued"}

    monkeypatch.setattr(server, "generate_pdf_dossier", fake_generate_pdf_dossier)
    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", fake_prime)

    resp = client.post(f"/api/cases/{case_id}/dossier-pdf", json={})
    assert resp.status_code == 200
    assert captured == {
        "vendor_id": case_id,
        "user_id": "dev",
        "hydrate_ai": True,
    }
    assert primed == {"case_id": case_id, "user_id": "dev"}
    assert resp.data.startswith(b"%PDF-1.4")


def test_dossier_routes_allow_explicit_non_hydrated_ai_generation(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Explicit Cached Dossier Vendor")
    captured = {"html": None, "pdf": None}

    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *args, **kwargs: {"status": "queued"})
    monkeypatch.setattr(
        server,
        "generate_dossier",
        lambda vendor_id, user_id="", hydrate_ai=False: captured.__setitem__("html", hydrate_ai) or "<html><body>Axiom Assessment</body></html>",
    )
    monkeypatch.setattr(
        server,
        "generate_pdf_dossier",
        lambda vendor_id, user_id="", hydrate_ai=False: captured.__setitem__("pdf", hydrate_ai) or b"%PDF-1.4 mocked",
    )

    html_resp = client.post(f"/api/cases/{case_id}/dossier", json={"format": "html", "include_ai": True, "hydrate_ai": False})
    pdf_resp = client.post(f"/api/cases/{case_id}/dossier-pdf", json={"include_ai": True, "hydrate_ai": False})

    assert html_resp.status_code == 200
    assert pdf_resp.status_code == 200
    assert captured == {"html": False, "pdf": False}


def test_monitor_run_route_queues_background_sweep(client, monkeypatch):
    server = sys.modules["server"]
    trigger_calls = []

    class FakeScheduler:
        def trigger_sweep(self, vendor_ids=None):
            trigger_calls.append(vendor_ids)
            return "sweep-789"

        def get_sweep_status(self, sweep_id):
            assert sweep_id == "sweep-789"
            return {"status": "queued", "triggered_at": "2026-03-23T00:00:00Z"}

    monkeypatch.setattr(server, "HAS_MONITOR_SCHEDULER", True)
    monkeypatch.setattr(server, "_get_monitor_scheduler", lambda: FakeScheduler())

    resp = client.post("/api/monitor/run", json={})
    assert resp.status_code == 202

    body = resp.get_json()
    assert body["mode"] == "async"
    assert body["sweep_id"] == "sweep-789"
    assert body["status"] == "queued"
    assert body["status_url"].endswith("/api/monitor/sweep/sweep-789")
    assert trigger_calls == [None]


def test_batch_upload_and_report_flow(client):
    csv_bytes = io.BytesIO(b"name,country\nAcme Systems,US\nNorthwind GmbH,DE\n")
    upload_resp = client.post(
        "/api/batch/upload",
        data={"file": (csv_bytes, "vendors.csv")},
        content_type="multipart/form-data",
    )

    assert upload_resp.status_code == 201
    batch_id = upload_resp.get_json()["batch_id"]

    deadline = time.time() + 5
    detail = None
    while time.time() < deadline:
        detail_resp = client.get(f"/api/batch/{batch_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.get_json()
        if detail["status"] in {"completed", "failed"}:
            break
        time.sleep(0.1)

    assert detail is not None
    assert detail["total_vendors"] == 2
    assert detail["processed"] == 2
    assert len(detail["items"]) == 2

    report_resp = client.get(f"/api/batch/{batch_id}/report")
    assert report_resp.status_code == 200
    assert report_resp.headers["Content-Type"].startswith("text/csv")
    assert "vendor_name,country,status" in report_resp.get_data(as_text=True)


def test_ai_routes_expose_configuration_surface(client):
    providers_resp = client.get("/api/ai/providers")
    if providers_resp.status_code == 501:
        pytest.skip("AI module not available in this environment")

    assert providers_resp.status_code == 200
    providers = providers_resp.get_json()["providers"]
    assert len(providers) >= 1

    config_resp = client.get("/api/ai/config")
    assert config_resp.status_code == 200
    assert config_resp.get_json()["configured"] is False


def test_enrichment_timeout_returns_partial_results(monkeypatch):
    if "osint.enrichment" in sys.modules:
        enrichment = importlib.reload(sys.modules["osint.enrichment"])
    else:
        from osint import enrichment  # type: ignore

    from osint import EnrichmentResult, Finding

    class FastConnector:
        @staticmethod
        def enrich(vendor_name, country="", **_ids):
            return EnrichmentResult(
                source="fast_connector",
                vendor_name=vendor_name,
                findings=[Finding(source="fast_connector", category="test", title="Fast hit", detail="ok", severity="low", confidence=0.9)],
                elapsed_ms=5,
            )

    class SlowConnector:
        @staticmethod
        def enrich(vendor_name, country="", **_ids):
            time.sleep(0.2)
            return EnrichmentResult(source="slow_connector", vendor_name=vendor_name, elapsed_ms=200)

    monkeypatch.setattr(
        enrichment,
        "CONNECTORS",
        [("fast_connector", FastConnector), ("slow_connector", SlowConnector)],
    )

    report = enrichment.enrich_vendor("Timeout Test Vendor", timeout=0.05)
    assert report["summary"]["connectors_run"] == 2
    assert report["summary"]["errors"] == 1
    assert "slow_connector" in report["connector_status"]
    assert report["connector_status"]["slow_connector"]["error"]


def test_enrich_stream_route_emits_scored_and_done_events(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Streaming Test Vendor")

    def fake_stream(*_args, **_kwargs):
        yield "start", {"vendor_name": "Streaming Test Vendor"}
        yield "connector_done", {"connector": "fast_connector", "findings": 1}
        yield "complete", {
            "vendor_name": "Streaming Test Vendor",
            "overall_risk": "low",
            "findings": [],
            "summary": {"connectors_run": 1, "errors": 0},
            "connector_status": {
                "fast_connector": {"success": True, "error": None}
            },
        }

    monkeypatch.setattr(server, "enrich_vendor_streaming", fake_stream)
    monkeypatch.setattr(
        server,
        "augment_from_enrichment",
        lambda base_input, _report: SimpleNamespace(
            vendor_input=base_input,
            provenance={},
            extra_risk_signals={},
        ),
    )
    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *_args, **_kwargs: {"status": "pending", "job_id": "ai-job-stream"})

    resp = client.get(f"/api/cases/{case_id}/enrich-stream")
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"

    body = resp.get_data(as_text=True)
    assert "event: start" in body
    assert "event: connector_done" in body
    assert "event: complete" in body
    assert "event: scored" in body
    assert "event: analysis" in body
    assert "event: done" in body


def test_access_ticket_issues_short_lived_browser_ticket_for_enrich_stream(auth_client, monkeypatch):
    client = auth_client["client"]
    server = auth_client["server"]
    headers = auth_client["headers"]
    case_id = _create_case(client, name="Access Ticket Stream Vendor", headers=headers)

    def fake_stream(*_args, **_kwargs):
        yield "start", {"vendor_name": "Access Ticket Stream Vendor", "total_connectors": 1, "connector_names": ["fast_connector"]}
        yield "complete", {
            "vendor_name": "Access Ticket Stream Vendor",
            "overall_risk": "low",
            "findings": [],
            "summary": {"connectors_run": 1, "errors": 0},
            "connector_status": {"fast_connector": {"success": True, "error": None}},
        }

    monkeypatch.setattr(server, "enrich_vendor_streaming", fake_stream)
    monkeypatch.setattr(
        server,
        "augment_from_enrichment",
        lambda base_input, _report: SimpleNamespace(vendor_input=base_input, provenance={}, extra_risk_signals={}),
    )
    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *_args, **_kwargs: {"status": "pending", "job_id": "ai-job-stream"})

    ticket_resp = client.post(
        "/api/auth/access-ticket",
        json={"path": f"/api/cases/{case_id}/enrich-stream"},
        headers=headers,
    )
    assert ticket_resp.status_code == 200
    access_ticket = ticket_resp.get_json()["access_ticket"]

    resp = client.get(f"/api/cases/{case_id}/enrich-stream?access_ticket={access_ticket}")
    assert resp.status_code == 200
    assert "event: start" in resp.get_data(as_text=True)


def test_access_ticket_opens_dossier_without_bearer_in_query(auth_client, monkeypatch):
    client = auth_client["client"]
    server = auth_client["server"]
    headers = auth_client["headers"]
    case_id = _create_case(client, name="Access Ticket Dossier Vendor", headers=headers)

    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *args, **kwargs: {"status": "queued"})
    monkeypatch.setattr(
        server,
        "generate_dossier",
        lambda vendor_id, user_id="", hydrate_ai=False: "<html><body>Axiom Assessment</body></html>",
    )

    dossier_resp = client.post(f"/api/cases/{case_id}/dossier", json={}, headers=headers)
    assert dossier_resp.status_code == 200
    download_url = dossier_resp.get_json()["download_url"]

    ticket_resp = client.post(
        "/api/auth/access-ticket",
        json={"path": download_url},
        headers=headers,
    )
    assert ticket_resp.status_code == 200
    access_ticket = ticket_resp.get_json()["access_ticket"]

    served = client.get(f"{download_url}?access_ticket={access_ticket}")
    assert served.status_code == 200
    assert "Axiom Assessment" in served.get_data(as_text=True)


def test_access_ticket_rejects_unsupported_path(auth_client):
    client = auth_client["client"]
    headers = auth_client["headers"]

    resp = client.post(
        "/api/auth/access-ticket",
        json={"path": "/api/cases"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_enrich_and_score_primes_ai_analysis(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Enrich And Score AI Vendor")

    monkeypatch.setattr(
        server,
        "enrich_vendor",
        lambda *args, **kwargs: {
            "overall_risk": "low",
            "findings": [],
            "summary": {"connectors_run": 1, "errors": 0},
            "identifiers": {},
            "total_elapsed_ms": 25,
            "connector_status": {"fast_connector": {"success": True, "error": None}},
        },
    )
    monkeypatch.setattr(server, "_persist_enrichment_artifacts", lambda *_args, **_kwargs: {"events": [], "graph": {"nodes": 3}})
    monkeypatch.setattr(
        server,
        "_canonical_rescore_from_enrichment",
        lambda *_args, **_kwargs: {
            "augmentation": SimpleNamespace(
                changes={},
                extra_risk_signals={},
                verified_identifiers={},
                provenance={},
            ),
            "score_dict": {
                "composite_score": 11,
                "is_hard_stop": False,
                "calibrated": {"calibrated_tier": "TIER_4_CLEAR", "calibrated_probability": 0.11},
            },
        },
    )
    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *_args, **_kwargs: {"status": "pending", "job_id": "ai-job-sync"})

    resp = client.post(f"/api/cases/{case_id}/enrich-and-score", json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ai_analysis"]["status"] == "pending"
    assert body["ai_analysis"]["job_id"] == "ai-job-sync"


def test_case_enrich_routes_pass_force_flag_to_enrichment(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Force Refresh Vendor")
    enrich_calls = []

    def fake_enrich_vendor(vendor_name, country="", connectors=None, parallel=True, timeout=60, force=False, **ids):
        enrich_calls.append(
            {
                "vendor_name": vendor_name,
                "country": country,
                "connectors": connectors,
                "parallel": parallel,
                "force": force,
            }
        )
        return {
            "vendor_name": vendor_name,
            "country": country,
            "overall_risk": "LOW",
            "summary": {"connectors_run": 1, "errors": 0},
            "findings": [],
            "identifiers": {},
            "relationships": [],
            "risk_signals": [],
            "connector_status": {"sam_gov": {"has_data": False, "error": None}},
            "total_elapsed_ms": 5,
        }

    monkeypatch.setattr(server, "enrich_vendor", fake_enrich_vendor)
    monkeypatch.setattr(server, "_persist_enrichment_artifacts", lambda *_args, **_kwargs: {"events": [], "graph": {}})
    monkeypatch.setattr(
        server,
        "_canonical_rescore_from_enrichment",
        lambda *_args, **_kwargs: {
            "augmentation": SimpleNamespace(changes={}, extra_risk_signals={}, verified_identifiers={}, provenance={}),
            "score_dict": {
                "composite_score": 10,
                "is_hard_stop": False,
                "calibrated": {"calibrated_tier": "TIER_4_CLEAR", "calibrated_probability": 0.1},
            },
        },
    )
    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *_args, **_kwargs: {"status": "pending"})

    enrich_resp = client.post(
        f"/api/cases/{case_id}/enrich",
        json={"connectors": ["sam_gov"], "parallel": False, "force": True},
    )
    assert enrich_resp.status_code == 200

    enrich_and_score_resp = client.post(
        f"/api/cases/{case_id}/enrich-and-score",
        json={"connectors": ["sam_gov"], "force": True},
    )
    assert enrich_and_score_resp.status_code == 200

    assert len(enrich_calls) == 2
    assert all(call["force"] is True for call in enrich_calls)
    assert enrich_calls[0]["parallel"] is False
    assert enrich_calls[0]["connectors"] == ["sam_gov"]


def test_case_enrich_and_score_defaults_to_cyber_connector_subset(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(
        client,
        name="Cyber Connector Vendor",
        extra_payload={"profile": "supplier_cyber_trust"},
    )
    enrich_calls = []

    def fake_enrich_vendor(vendor_name, country="", connectors=None, parallel=True, timeout=60, force=False, **ids):
        enrich_calls.append({"vendor_name": vendor_name, "connectors": list(connectors or [])})
        return {
            "vendor_name": vendor_name,
            "country": country,
            "overall_risk": "LOW",
            "summary": {"connectors_run": len(connectors or []), "errors": 0},
            "findings": [],
            "identifiers": {},
            "relationships": [],
            "risk_signals": [],
            "connector_status": {},
            "total_elapsed_ms": 5,
        }

    monkeypatch.setattr(server, "enrich_vendor", fake_enrich_vendor)
    monkeypatch.setattr(server, "_persist_enrichment_artifacts", lambda *_args, **_kwargs: {"events": [], "graph": {}})
    monkeypatch.setattr(
        server,
        "_canonical_rescore_from_enrichment",
        lambda *_args, **_kwargs: {
            "augmentation": SimpleNamespace(changes={}, extra_risk_signals={}, verified_identifiers={}, provenance={}),
            "score_dict": {
                "composite_score": 10,
                "is_hard_stop": False,
                "calibrated": {"calibrated_tier": "TIER_4_CLEAR", "calibrated_probability": 0.1},
            },
        },
    )
    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", lambda *_args, **_kwargs: {"status": "pending"})

    resp = client.post(f"/api/cases/{case_id}/enrich-and-score", json={})

    assert resp.status_code == 200
    assert enrich_calls
    connectors = enrich_calls[0]["connectors"]
    assert "cisa_kev" in connectors
    assert "deps_dev" in connectors
    assert "public_html_ownership" in connectors
    assert "courtlistener" not in connectors
    assert "usaspending" not in connectors
    assert "fpds_contracts" not in connectors


def test_case_enrich_defaults_to_export_connector_subset(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(
        client,
        name="Export Connector Vendor",
        extra_payload={"profile": "trade_compliance"},
    )
    enrich_calls = []

    def fake_enrich_vendor(vendor_name, country="", connectors=None, parallel=True, timeout=60, force=False, **ids):
        enrich_calls.append({"vendor_name": vendor_name, "connectors": list(connectors or [])})
        return {
            "vendor_name": vendor_name,
            "country": country,
            "overall_risk": "LOW",
            "summary": {"connectors_run": len(connectors or []), "errors": 0},
            "findings": [],
            "identifiers": {},
            "relationships": [],
            "risk_signals": [],
            "connector_status": {},
            "total_elapsed_ms": 5,
        }

    monkeypatch.setattr(server, "enrich_vendor", fake_enrich_vendor)
    monkeypatch.setattr(server, "_persist_enrichment_artifacts", lambda *_args, **_kwargs: {"events": [], "graph": {}})

    resp = client.post(f"/api/cases/{case_id}/enrich", json={})

    assert resp.status_code == 200
    assert enrich_calls
    connectors = enrich_calls[0]["connectors"]
    assert "trade_csl" in connectors
    assert "public_search_ownership" in connectors
    assert "public_html_ownership" in connectors
    assert "cisa_kev" not in connectors
    assert "deps_dev" not in connectors
    assert "openssf_scorecard" not in connectors


def test_case_enrich_reuses_latest_enrichment_identifiers(client, monkeypatch):
    server = sys.modules["server"]
    case_id = _create_case(client, name="Identifier Seed Vendor")
    enrich_calls = []

    def fake_enrich_vendor(vendor_name, country="", connectors=None, parallel=True, timeout=60, force=False, **ids):
        enrich_calls.append({"vendor_name": vendor_name, "ids": ids})
        return {
            "vendor_name": vendor_name,
            "country": country,
            "overall_risk": "LOW",
            "summary": {"connectors_run": 1, "errors": 0},
            "findings": [],
            "identifiers": {},
            "relationships": [],
            "risk_signals": [],
            "connector_status": {"public_html_ownership": {"has_data": False, "error": None}},
            "total_elapsed_ms": 5,
        }

    monkeypatch.setattr(server, "enrich_vendor", fake_enrich_vendor)
    monkeypatch.setattr(
        server.db,
        "get_latest_enrichment",
        lambda _case_id: {"identifiers": {"website": "https://seeded.example/company", "lei": "LEI-123"}},
    )
    monkeypatch.setattr(server, "_persist_enrichment_artifacts", lambda *_args, **_kwargs: {"events": [], "graph": {}})

    resp = client.post(f"/api/cases/{case_id}/enrich", json={})

    assert resp.status_code == 200
    assert enrich_calls
    assert enrich_calls[0]["ids"]["website"] == "https://seeded.example/company"
    assert enrich_calls[0]["ids"]["domain"] == "seeded.example"
    assert enrich_calls[0]["ids"]["lei"] == "LEI-123"


def test_dossier_route_primes_ai_without_blocking(auth_client, monkeypatch):
    server = auth_client["server"]
    client = auth_client["client"]
    headers = auth_client["headers"]
    case_id = _create_case(client, name="Dossier Prime Vendor", headers=headers)

    calls = {}

    def _fake_prime(_case_id, _user_id, **kwargs):
        calls.update(kwargs)
        return {"status": "queued"}

    monkeypatch.setattr(server, "_prime_ai_analysis_for_case", _fake_prime)
    monkeypatch.setattr(server, "generate_dossier", lambda *_args, **_kwargs: "<html><body>ok</body></html>")

    response = client.post(f"/api/cases/{case_id}/dossier", headers=headers)

    assert response.status_code == 200
    assert calls["wait_seconds"] == 0
    assert calls["poll_seconds"] == 0.0
