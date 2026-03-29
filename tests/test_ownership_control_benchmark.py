import importlib.util
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_ownership_control_benchmark.py"
SPEC = importlib.util.spec_from_file_location("run_ownership_control_benchmark", SCRIPT_PATH)
benchmark = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(benchmark)


def test_evaluate_passport_counts_control_and_intermediary_paths():
    passport = {
        "posture": "review",
        "graph": {
            "entity_count": 4,
            "relationship_count": 5,
            "control_paths": [
                {
                    "rel_type": "beneficially_owned_by",
                    "source_name": "Vendor A",
                    "target_name": "Holding Co",
                    "confidence": 0.92,
                    "corroboration_count": 2,
                    "data_sources": ["ownership_fixture"],
                },
                {
                    "rel_type": "routes_payment_through",
                    "source_name": "Vendor A",
                    "target_name": "Trade Bank",
                    "confidence": 0.88,
                    "corroboration_count": 1,
                    "data_sources": ["bank_fixture"],
                },
                {
                    "rel_type": "backed_by",
                    "source_name": "Vendor A",
                    "target_name": "Blue Delta",
                    "confidence": 0.63,
                    "corroboration_count": 1,
                    "data_sources": ["google_news"],
                },
            ],
        },
        "identity": {
            "connectors_with_data": 3,
            "findings_total": 6,
        },
        "ownership": {
            "oci": {
                "owner_class_known": True,
                "owner_class": "Service-Disabled Veteran",
                "descriptor_only": True,
                "ownership_gap": "descriptor_only_owner_class",
                "ownership_resolution_pct": 0.55,
                "control_resolution_pct": 0.35,
                "owner_class_evidence": [{"source": "public_html_ownership", "artifact": "https://www.ysginc.com/article"}],
            },
            "workflow_control": {
                "label": "Foreign interest in view",
                "action_owner": "Analyst review",
            },
            "foci_summary": {
                "foreign_country": "CN",
            },
        },
    }

    result = benchmark.evaluate_passport(passport)

    assert result["entity_count"] == 4
    assert result["relationship_count"] == 5
    assert result["control_path_metrics"]["has_control_path"] is True
    assert result["control_path_metrics"]["has_upstream_ownership"] is True
    assert result["control_path_metrics"]["has_intermediary_visibility"] is True
    assert result["control_path_metrics"]["relationship_mix"]["backed_by"] == 1
    assert result["oci_metrics"]["owner_class_known"] is True
    assert result["oci_metrics"]["descriptor_only"] is True
    assert result["jurisdiction_signal"] == "CN"
    assert result["analyst_usefulness_score"] >= 4


def test_render_markdown_includes_missing_case_detail():
    markdown = benchmark.render_markdown(
        [
            {"group": "tier1_zero_link", "name": "Missing Vendor", "status": "missing_case", "detail": "No matching case found"},
            {
                "group": "tier2_low_link",
                "name": "Present Vendor",
                "case_id": "c-123",
                "status": "ok",
                "evaluation": {
                    "posture": "review",
                    "entity_count": 3,
                    "relationship_count": 2,
                    "connectors_with_data": 2,
                    "workflow_control_label": "Foreign interest in view",
                    "analyst_usefulness_score": 3,
                    "control_path_metrics": {
                        "has_control_path": True,
                        "has_upstream_ownership": True,
                        "has_intermediary_visibility": False,
                        "control_path_count": 1,
                        "ownership_path_count": 1,
                        "intermediary_path_count": 0,
                    },
                },
            },
        ],
        "http://example.test",
    )

    assert "Missing Vendor" in markdown
    assert "missing_case" in markdown
    assert "Present Vendor" in markdown
    assert "Analyst usefulness proxy" in markdown


def test_build_summary_flags_missing_supplier_passport_route():
    rows = [
        {"group": "tier1_zero_link", "name": "Vendor A", "case_id": "c-1", "status": "proxy_ok", "mode": "proxy", "evaluation": {"control_path_metrics": {"has_control_path": False, "has_upstream_ownership": False, "has_intermediary_visibility": False}}},
        {"group": "tier1_zero_link", "name": "Vendor B", "case_id": "c-2", "status": "proxy_ok", "mode": "proxy", "evaluation": {"control_path_metrics": {"has_control_path": False, "has_upstream_ownership": False, "has_intermediary_visibility": False}}},
    ]

    summary = benchmark.build_summary(rows)

    assert summary["cases_evaluated"] == 2
    assert summary["proxy_cases"] == 2
    assert summary["supplier_passport_route_available"] is False
    assert summary["deployment_gap"] == "supplier_passport_route_missing"
    assert "group_summary" in summary
    assert "benchmark_score_pct" in summary


def test_render_markdown_calls_out_deployment_gap():
    markdown = benchmark.render_markdown(
        [
            {"group": "tier2_low_link", "name": "Vendor A", "case_id": "c-1", "status": "passport_error", "detail": "404 Client Error: NOT FOUND"},
        ],
        "http://example.test",
    )

    assert "Deployment gap" in markdown
    assert "supplier-passport" in markdown


def test_build_proxy_passport_extracts_control_paths():
    proxy_passport = benchmark.build_proxy_passport(
        {
            "id": "c-1",
            "vendor_name": "Vendor A",
            "country": "US",
            "profile": "defense_acquisition",
            "program": "dod_unclassified",
            "score": {
                "composite_score": 22,
                "calibrated": {"calibrated_tier": "TIER_2_REVIEW", "calibrated_probability": 0.44},
            },
            "workflow_control_summary": {"label": "Foreign interest in view", "action_owner": "Analyst"},
        },
        {
            "overall_risk": "MEDIUM",
            "enriched_at": "2026-03-26T10:00:00Z",
            "identifiers": {"cage": "1ABC2"},
            "summary": {"connectors_with_data": 4, "findings_total": 7},
        },
        {
            "entity_count": 4,
            "relationship_count": 5,
            "entities": [
                {"id": "entity:vendor", "canonical_name": "Vendor A"},
                {"id": "entity:holdco", "canonical_name": "Holding Co"},
            ],
            "relationships": [
                {
                    "source_entity_id": "entity:vendor",
                    "target_entity_id": "entity:holdco",
                    "rel_type": "owned_by",
                    "confidence": 0.91,
                    "corroboration_count": 2,
                    "data_sources": ["ownership_fixture"],
                }
            ],
        },
        {"network_risk_score": 1.2, "network_risk_level": "medium"},
    )

    result = benchmark.evaluate_passport(proxy_passport)

    assert result["posture"] == "review"
    assert result["connectors_with_data"] == 4
    assert result["control_path_metrics"]["control_path_count"] == 1
    assert result["control_path_metrics"]["has_upstream_ownership"] is True


def test_build_summary_weights_zero_link_success_more_heavily():
    rows = [
        {
            "group": "tier1_zero_link",
            "name": "Hefring Marine",
            "case_id": "c-1",
            "status": "ok",
            "evaluation": {
                "workflow_control_label": None,
                "analyst_usefulness_score": 3,
                "control_path_metrics": {
                    "has_control_path": True,
                    "has_upstream_ownership": True,
                    "has_intermediary_visibility": False,
                },
            },
        },
        {
            "group": "tier2_low_link",
            "name": "Greensea IQ",
            "case_id": "c-2",
            "status": "ok",
            "evaluation": {
                "workflow_control_label": "Foreign interest in view",
                "analyst_usefulness_score": 3,
                "control_path_metrics": {
                    "has_control_path": False,
                    "has_upstream_ownership": True,
                    "has_intermediary_visibility": False,
                },
            },
        },
        {
            "group": "tier3_high_yield",
            "name": "HII",
            "case_id": "c-3",
            "status": "ok",
            "evaluation": {
                "workflow_control_label": "Foreign interest in view",
                "analyst_usefulness_score": 4,
                "control_path_metrics": {
                    "has_control_path": True,
                    "has_upstream_ownership": True,
                    "has_intermediary_visibility": True,
                },
            },
        },
    ]

    summary = benchmark.build_summary(rows)

    assert summary["group_summary"]["tier1_zero_link"]["successes"] == 1
    assert summary["group_summary"]["tier2_low_link"]["successes"] == 1
    assert summary["group_summary"]["tier3_high_yield"]["successes"] == 1
    assert summary["benchmark_score_pct"] > 0


def test_descriptor_only_oci_group_requires_preserved_unknown_named_owner():
    row = {
        "group": "oci_descriptor_only",
        "name": "Yorktown Systems Group",
        "case_id": "c-oci",
        "status": "ok",
        "evaluation": {
            "workflow_control_label": None,
            "analyst_usefulness_score": 2,
            "control_path_metrics": {
                "has_control_path": False,
                "has_upstream_ownership": False,
                "has_intermediary_visibility": False,
            },
            "oci_metrics": {
                "owner_class_known": True,
                "descriptor_only": True,
                "named_beneficial_owner_known": False,
                "ownership_gap": "descriptor_only_owner_class",
                "ownership_resolution_pct": 0.55,
                "control_resolution_pct": 0.35,
                "owner_class_evidence_count": 1,
            },
        },
    }

    summary = benchmark.build_summary([row])

    assert benchmark._row_succeeds(row) is True
    assert summary["group_summary"]["oci_descriptor_only"]["successes"] == 1
    assert summary["descriptor_only_cases"] == 1
    assert summary["cases_with_owner_class_signal"] == 1


def test_compare_to_baseline_detects_improvement():
    baseline_rows = [
        {
            "group": "tier2_low_link",
            "name": "Vendor A",
            "status": "ok",
            "evaluation": {
                "relationship_count": 1,
                "analyst_usefulness_score": 1,
                "control_path_metrics": {
                    "control_path_count": 0,
                    "ownership_path_count": 0,
                    "intermediary_path_count": 0,
                },
            },
        }
    ]
    current_rows = [
        {
            "group": "tier2_low_link",
            "name": "Vendor A",
            "status": "ok",
            "evaluation": {
                "relationship_count": 4,
                "analyst_usefulness_score": 4,
                "control_path_metrics": {
                    "control_path_count": 2,
                    "ownership_path_count": 1,
                    "intermediary_path_count": 1,
                },
            },
        }
    ]

    delta = benchmark.compare_to_baseline(current_rows, baseline_rows)

    assert delta["compared_cases"] == 1
    assert delta["improved_cases"] == 1
    assert delta["regressed_cases"] == 0
    assert delta["control_path_delta_total"] == 2
    assert delta["top_improvements"][0]["name"] == "Vendor A"


def test_login_uses_bearer_token_without_auth_request():
    with patch.object(benchmark.requests, "post") as mock_post:
        headers = benchmark.login("http://example.test", "analyst@example.test", "secret", token="token-123")

    mock_post.assert_not_called()
    assert headers == {"Authorization": "Bearer token-123"}
