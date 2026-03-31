import argparse
import importlib.util
import requests
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_customer_demo_gate.py"
SPEC = importlib.util.spec_from_file_location("run_customer_demo_gate", SCRIPT_PATH)
gate = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def test_is_suspicious_website_rejects_recruiting_host():
    reason = gate.is_suspicious_website("https://ats.rippling.com/columbia-helicopters/jobs")
    assert reason == "suspicious website host: ats.rippling.com"


def test_validate_identifier_expectation_detects_mismatch():
    failures = gate.validate_identifier_expectation(
        {"cage": {"value": "7W206"}},
        "cage",
        "0EA28",
    )
    assert failures == ["expected CAGE 0EA28, got 7W206"]


def test_validate_identifier_expectation_accepts_matching_cik():
    failures = gate.validate_identifier_expectation(
        {"cik": {"value": "12927"}},
        "cik",
        "12927",
    )
    assert failures == []


def test_check_dossier_text_flags_banned_phrase():
    failures, warnings = gate.check_dossier_text(
        "Defense counterparty trust dossier\nRecent change\nRisk Storyline\nSupplier passport\nAI Narrative Brief\nExecutive judgment\n0 years of verifiable records",
        gate.HTML_SECTION_CHECKS,
        include_ai=True,
        label="html dossier",
    )
    assert "html dossier contains banned phrase: 0 years of verifiable records" in failures
    assert warnings == []


def test_analyze_passport_flags_empty_graph_and_missing_ids():
    passport = {
        "identity": {"identifiers": {}, "identifier_status": {}},
        "graph": {"entity_count": 0, "relationship_count": 0, "network_entity_count": 0},
        "monitoring": {"check_count": 0},
        "ownership": {"profile": {"ownership_pct_resolved": 0.8}},
    }

    failures, warnings = gate.analyze_passport(
        passport,
        company_name="Test Vendor",
        expected_domain="",
        expected_cage="",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        expected_min_control_paths=0,
        expected_control_target="",
        warn_on_empty_control_paths=True,
        require_monitoring_history=True,
    )

    assert "website missing" in failures
    assert "no key identifiers captured" in failures
    assert "graph network entity count is zero" in failures
    assert "supplier passport control graph is empty" in failures
    assert "supplier passport has no control-path relationships" in warnings
    assert "no monitoring history yet" in warnings


def test_analyze_passport_skips_pack_irrelevant_warnings_by_default():
    passport = {
        "identity": {
            "identifiers": {"website": "https://example.com"},
            "identifier_status": {"website": {"value": "https://example.com"}},
        },
        "graph": {"entity_count": 1, "relationship_count": 0, "network_entity_count": 1},
        "monitoring": {"check_count": 0},
        "ownership": {"profile": {}},
    }

    failures, warnings = gate.analyze_passport(
        passport,
        company_name="Example Systems",
        expected_domain="example.com",
        expected_cage="",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        expected_min_control_paths=0,
        expected_control_target="",
    )

    assert failures == []
    assert warnings == []


def test_analyze_passport_warns_when_identity_is_public_only_without_official_corroboration():
    passport = {
        "identity": {
            "identifiers": {"website": "https://example.com", "cage": "AB123"},
            "identifier_status": {
                "website": {"value": "https://example.com"},
                "cage": {"value": "AB123"},
            },
            "official_corroboration": {
                "coverage_level": "public_only",
                "blocked_connector_count": 1,
            },
        },
        "graph": {"entity_count": 1, "relationship_count": 0, "network_entity_count": 1},
        "monitoring": {"check_count": 1},
        "ownership": {"profile": {}},
    }

    failures, warnings = gate.analyze_passport(
        passport,
        company_name="Example Systems",
        expected_domain="example.com",
        expected_cage="",
        expected_uei="",
        expected_duns="",
        expected_cik="",
    )

    assert failures == []
    assert "identity is relying on public capture without strong official corroboration" in warnings
    assert "1 official connector checks were blocked or throttled" in warnings


def test_analyze_passport_fails_when_official_corroboration_threshold_is_not_met():
    passport = {
        "identity": {
            "identifiers": {"website": "https://example.com", "uk_company_number": "12345678"},
            "identifier_status": {
                "website": {"value": "https://example.com"},
                "uk_company_number": {"value": "12345678"},
            },
            "official_corroboration": {
                "coverage_level": "partial",
                "blocked_connector_count": 0,
            },
        },
        "graph": {"entity_count": 1, "relationship_count": 0, "network_entity_count": 1},
        "monitoring": {"check_count": 1},
        "ownership": {"profile": {}},
    }

    failures, warnings = gate.analyze_passport(
        passport,
        company_name="Example Systems",
        expected_domain="example.com",
        expected_cage="",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        minimum_official_corroboration="strong",
    )

    assert "official corroboration below required threshold: need strong, got partial" in failures
    assert warnings == []


def test_analyze_passport_ignores_irrelevant_foreign_registry_blockage():
    passport = {
        "vendor": {"country": "US"},
        "identity": {
            "identifiers": {
                "website": "https://berryaviation.com",
                "cage": "0EA28",
                "uei": "V1HATBT1N7V5",
                "legal_jurisdiction": "US-TX",
            },
            "identifier_status": {
                "website": {"value": "https://berryaviation.com"},
                "cage": {"value": "0EA28"},
                "uei": {"value": "V1HATBT1N7V5"},
                "legal_jurisdiction": {"value": "US-TX"},
            },
            "official_corroboration": {
                "coverage_level": "strong",
                "blocked_connector_count": 5,
                "connectors": [
                    {"source": "sam_gov", "has_data": True, "error": "", "throttled": False},
                    {"source": "corporations_canada", "has_data": False, "error": "timeout", "throttled": False},
                    {"source": "australia_abn_asic", "has_data": False, "error": "timeout", "throttled": False},
                    {"source": "singapore_acra", "has_data": False, "error": "timeout", "throttled": False},
                    {"source": "new_zealand_companies_office", "has_data": False, "error": "timeout", "throttled": False},
                    {"source": "uk_companies_house", "has_data": False, "error": "timeout", "throttled": False},
                ],
            },
        },
        "graph": {"entity_count": 1, "relationship_count": 0, "network_entity_count": 1},
        "monitoring": {"check_count": 1},
        "ownership": {"profile": {}},
    }

    failures, warnings = gate.analyze_passport(
        passport,
        company_name="Berry Aviation, Inc.",
        expected_domain="berryaviation.com",
        expected_cage="",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        minimum_official_corroboration="strong",
        max_blocked_official_connectors=3,
    )

    assert failures == []
    assert warnings == []


def test_analyze_passport_warns_on_high_threat_pressure():
    passport = {
        "identity": {
            "identifiers": {"website": "https://example.com"},
            "identifier_status": {"website": {"value": "https://example.com"}},
        },
        "graph": {"entity_count": 1, "relationship_count": 1, "network_entity_count": 1},
        "monitoring": {"check_count": 1},
        "ownership": {"profile": {}},
        "threat_intel": {
            "threat_pressure": "high",
            "cisa_advisory_ids": ["AA24-057A", "AA22-047A"],
            "attack_technique_ids": ["T1190", "T1078", "T1090", "T1583"],
        },
    }

    failures, warnings = gate.analyze_passport(
        passport,
        company_name="Example Systems",
        expected_domain="example.com",
        expected_cage="",
        expected_uei="",
        expected_duns="",
        expected_cik="",
    )

    assert failures == []
    assert "active threat pressure is high with 2 CISA advisories and 4 ATT&CK techniques in scope" in warnings


def test_analyze_passport_warns_on_high_open_source_pressure():
    passport = {
        "identity": {
            "identifiers": {"website": "https://example.com"},
            "identifier_status": {"website": {"value": "https://example.com"}},
        },
        "graph": {"entity_count": 1, "relationship_count": 1, "network_entity_count": 1},
        "monitoring": {"check_count": 1},
        "ownership": {"profile": {}},
        "cyber": {
            "open_source_risk_level": "high",
            "open_source_advisory_count": 5,
            "scorecard_low_repo_count": 2,
        },
    }

    failures, warnings = gate.analyze_passport(
        passport,
        company_name="Example Systems",
        expected_domain="example.com",
        expected_cage="",
        expected_uei="",
        expected_duns="",
        expected_cik="",
    )

    assert failures == []
    assert "open-source assurance pressure is high with 5 advisories and 2 low-score repositories" in warnings


def test_gate_verdict_escalates_only_when_failures_or_warning_budget_hit():
    assert gate.gate_verdict([], [], 2) == "GO"
    assert gate.gate_verdict([], ["a", "b", "c"], 2) == "CAUTION"
    assert gate.gate_verdict(["bad"], [], 2) == "NO_GO"


def test_supplier_passport_mode_uses_light_for_identity_checks():
    assert gate.supplier_passport_mode(
        expected_min_control_paths=0,
        expected_control_target="",
        warn_on_empty_control_paths=False,
    ) == "light"


def test_supplier_passport_mode_uses_control_for_control_path_checks():
    assert gate.supplier_passport_mode(
        expected_min_control_paths=1,
        expected_control_target="Codan",
        warn_on_empty_control_paths=True,
    ) == "control"


def test_analyze_passport_enforces_control_path_expectations():
    passport = {
        "identity": {
            "identifiers": {"website": "https://example.com"},
            "identifier_status": {"website": {"value": "https://example.com"}},
        },
        "graph": {
            "entity_count": 2,
            "relationship_count": 1,
            "network_entity_count": 2,
            "network_relationship_count": 1,
            "control_paths": [
                {
                    "source_name": "Example Systems",
                    "target_name": "Codan",
                    "rel_type": "owned_by",
                }
            ],
        },
        "monitoring": {"check_count": 1},
        "ownership": {"profile": {}},
    }

    failures, warnings = gate.analyze_passport(
        passport,
        company_name="Example Systems",
        expected_domain="example.com",
        expected_cage="",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        expected_min_control_paths=1,
        expected_control_target="Codan",
        warn_on_empty_control_paths=True,
        require_monitoring_history=False,
    )

    assert failures == []
    assert warnings == []


def test_analyze_passport_accepts_first_initial_plus_surname_control_target_match():
    passport = {
        "identity": {
            "identifiers": {"website": "https://example.com"},
            "identifier_status": {"website": {"value": "https://example.com"}},
        },
        "graph": {
            "entity_count": 2,
            "relationship_count": 1,
            "network_entity_count": 2,
            "network_relationship_count": 1,
            "control_paths": [
                {
                    "source_name": "Example Systems",
                    "target_name": "Michael Hascall",
                    "rel_type": "led_by",
                }
            ],
        },
        "monitoring": {"check_count": 1},
        "ownership": {"profile": {}},
    }

    failures, warnings = gate.analyze_passport(
        passport,
        company_name="Example Systems",
        expected_domain="example.com",
        expected_cage="",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        expected_min_control_paths=1,
        expected_control_target="Mike Hascall",
        warn_on_empty_control_paths=True,
        require_monitoring_history=False,
    )

    assert failures == []
    assert warnings == []


def test_run_demo_gate_uses_expected_domain_and_company_name(tmp_path):
    class FakeClient:
        def __init__(self):
            self.calls = []
            self.passport_modes = []

        def request_json(self, method, path, **kwargs):
            self.calls.append((method, path))
            if path == "/api/cases":
                return {"case_id": "c-demo1"}
            if path.endswith("/supplier-passport"):
                self.passport_modes.append((kwargs.get("params") or {}).get("mode"))
                return {
                    "identity": {
                        "identifiers": {"website": "https://example.com", "cage": "AB123"},
                        "identifier_status": {
                            "website": {"value": "https://example.com"},
                            "cage": {"value": "AB123"},
                        },
                    },
                    "graph": {"entity_count": 1, "relationship_count": 1, "network_entity_count": 1, "network_relationship_count": 1},
                    "monitoring": {"check_count": 1},
                    "ownership": {"profile": {"ownership_pct_resolved": 0.2}},
                }
            if path.endswith("/analysis-status"):
                return {"status": "ready"}
            if path.endswith("/assistant-plan"):
                return {"analyst_prompt": "prompt", "plan": [{"tool_id": "supplier_passport", "required": True}]}
            if path.endswith("/assistant-execute"):
                return {"executed_steps": [{"tool_id": "supplier_passport"}]}
            if path.endswith("/enrich-and-score"):
                return {"status": "ok"}
            raise AssertionError(path)

        def request_text(self, method, path, **kwargs):
            return "Defense counterparty trust dossier\nRecent change\nRisk Storyline\nSupplier passport\nAI Narrative Brief\nExecutive judgment"

        def request_bytes(self, method, path, **kwargs):
            from reportlab.pdfgen import canvas
            from io import BytesIO

            buff = BytesIO()
            pdf = canvas.Canvas(buff)
            pdf.drawString(72, 720, "DEFENSE COUNTERPARTY TRUST DOSSIER")
            pdf.drawString(72, 700, "RECENT CHANGE")
            pdf.drawString(72, 680, "RISK STORYLINE")
            pdf.drawString(72, 660, "SUPPLIER PASSPORT")
            pdf.drawString(72, 640, "AI NARRATIVE BRIEF")
            pdf.save()
            return buff.getvalue()

    args = argparse.Namespace(
        base_url="http://example.test",
        email="",
        password="",
        token="token",
        company="Example Systems",
        country="US",
        case_id="",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=True,
        ai_readiness_mode="full",
        check_assistant=True,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=0,
        auto_stabilize=True,
        expected_domain="example.com",
        expected_cage="AB123",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        expected_min_control_paths=0,
        expected_control_target="",
        warn_on_empty_control_paths=True,
        require_monitoring_history=False,
        report_dir=str(tmp_path),
        print_json=False,
    )

    fake = FakeClient()
    result = gate.run_demo_gate(args, client=fake)

    assert result.company_name == "Example Systems"
    assert result.case_id == "c-demo1"
    assert result.verdict == "GO"
    assert result.assistant_ok is True
    assert fake.passport_modes == ["control"]


def test_run_demo_gate_normalizes_local_fixture_seed_paths_before_case_create(tmp_path):
    fixture_uri = (gate.ROOT / "fixtures" / "public_html_ownership" / "faun_trackway_control.html").resolve().as_uri()
    captured = {}

    class FakeClient:
        def request_json(self, method, path, **kwargs):
            if path == "/api/cases":
                captured["payload"] = kwargs.get("json") or {}
                return {"case_id": "c-demo-fixture"}
            if path.endswith("/enrich-and-score"):
                return {"status": "ok"}
            if path.endswith("/supplier-passport"):
                return {
                    "identity": {
                        "identifiers": {"website": "https://fauntrackway.com"},
                        "identifier_status": {"website": {"value": "https://fauntrackway.com"}},
                    },
                    "graph": {"entity_count": 1, "relationship_count": 1, "network_entity_count": 1, "network_relationship_count": 1},
                    "monitoring": {"check_count": 1},
                    "ownership": {"profile": {"ownership_pct_resolved": 0.2}},
                }
            if path.endswith("/analysis-status"):
                return {"status": "ready"}
            if path.endswith("/assistant-plan"):
                return {"analyst_prompt": "prompt", "plan": [{"tool_id": "supplier_passport", "required": True}]}
            if path.endswith("/assistant-execute"):
                return {"executed_steps": [{"tool_id": "supplier_passport"}]}
            raise AssertionError(path)

        def request_text(self, method, path, **kwargs):
            return "Defense counterparty trust dossier\nRecent change\nRisk Storyline\nSupplier passport\nAI Narrative Brief\nExecutive judgment"

        def request_bytes(self, method, path, **kwargs):
            from io import BytesIO

            from reportlab.pdfgen import canvas

            buff = BytesIO()
            pdf = canvas.Canvas(buff)
            pdf.drawString(72, 720, "DEFENSE COUNTERPARTY TRUST DOSSIER")
            pdf.drawString(72, 700, "RECENT CHANGE")
            pdf.drawString(72, 680, "RISK STORYLINE")
            pdf.drawString(72, 660, "SUPPLIER PASSPORT")
            pdf.drawString(72, 640, "AI NARRATIVE BRIEF")
            pdf.save()
            return buff.getvalue()

    args = argparse.Namespace(
        base_url="http://example.test",
        email="",
        password="",
        token="token",
        company="FAUN Trackway",
        country="US",
        case_id="",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=True,
        ai_readiness_mode="full",
        check_assistant=True,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=0,
        auto_stabilize=True,
        expected_domain="fauntrackway.com",
        expected_cage="",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        expected_min_control_paths=0,
        expected_control_target="",
        warn_on_empty_control_paths=False,
        require_monitoring_history=False,
        report_dir=str(tmp_path),
        print_json=False,
        seed_metadata={
            "website": "https://fauntrackway.com",
            "public_html_fixture_only": True,
            "public_html_fixture_page": fixture_uri,
        },
    )

    result = gate.run_demo_gate(args, client=FakeClient())

    assert result.case_id == "c-demo-fixture"
    assert captured["payload"]["seed_metadata"]["public_html_fixture_page"] == "fixtures/public_html_ownership/faun_trackway_control.html"


def test_run_demo_gate_auto_stabilizes_before_final_verdict(tmp_path):
    class FakeClient:
        def __init__(self):
            self.phase = 0
            self.enrich_calls = []

        def request_json(self, method, path, **kwargs):
            if path == "/api/cases":
                return {"case_id": "c-demo2"}
            if path.endswith("/enrich-and-score"):
                payload = kwargs.get("json") or {}
                self.enrich_calls.append(payload)
                if payload.get("connectors"):
                    self.phase = 1
                return {"status": "ok"}
            if path.endswith("/supplier-passport"):
                if self.phase == 0:
                    return {
                        "identity": {"identifiers": {}, "identifier_status": {}},
                        "graph": {"entity_count": 0, "relationship_count": 0, "network_entity_count": 0, "network_relationship_count": 0},
                        "monitoring": {"check_count": 0},
                        "ownership": {"profile": {"ownership_pct_resolved": 0.8}},
                    }
                return {
                    "identity": {
                        "identifiers": {"website": "https://example.com", "cage": "AB123"},
                        "identifier_status": {
                            "website": {"value": "https://example.com"},
                            "cage": {"value": "AB123"},
                        },
                    },
                    "graph": {"entity_count": 1, "relationship_count": 1, "network_entity_count": 1, "network_relationship_count": 1},
                    "monitoring": {"check_count": 1},
                    "ownership": {"profile": {"ownership_pct_resolved": 0.2}},
                }
            if path.endswith("/analysis-status"):
                return {"status": "ready"}
            if path.endswith("/assistant-plan"):
                return {"analyst_prompt": "prompt", "plan": [{"tool_id": "supplier_passport", "required": True}]}
            if path.endswith("/assistant-execute"):
                return {"executed_steps": [{"tool_id": "supplier_passport"}]}
            raise AssertionError(path)

        def request_text(self, method, path, **kwargs):
            return "Defense counterparty trust dossier\nRecent change\nRisk Storyline\nSupplier passport\nAI Narrative Brief\nExecutive judgment"

        def request_bytes(self, method, path, **kwargs):
            from reportlab.pdfgen import canvas
            from io import BytesIO

            buff = BytesIO()
            pdf = canvas.Canvas(buff)
            pdf.drawString(72, 720, "DEFENSE COUNTERPARTY TRUST DOSSIER")
            pdf.drawString(72, 700, "RECENT CHANGE")
            pdf.drawString(72, 680, "RISK STORYLINE")
            pdf.drawString(72, 660, "SUPPLIER PASSPORT")
            pdf.drawString(72, 640, "AI NARRATIVE BRIEF")
            pdf.save()
            return buff.getvalue()

    args = argparse.Namespace(
        base_url="http://example.test",
        email="",
        password="",
        token="token",
        company="Example Systems",
        country="US",
        case_id="",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=True,
        ai_readiness_mode="full",
        check_assistant=True,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        auto_stabilize=True,
        expected_domain="example.com",
        expected_cage="AB123",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        expected_min_control_paths=0,
        expected_control_target="",
        warn_on_empty_control_paths=True,
        require_monitoring_history=False,
        report_dir=str(tmp_path),
        print_json=False,
    )

    fake = FakeClient()
    result = gate.run_demo_gate(args, client=fake)

    assert result.verdict == "GO"
    assert result.stabilization_steps == []
    assert fake.enrich_calls[0]["connectors"] == list(gate.READINESS_PRIMARY_CONNECTORS)


def test_run_demo_gate_surface_mode_accepts_pending_ai_without_warning(tmp_path):
    class FakeClient:
        def request_json(self, method, path, **kwargs):
            if path == "/api/cases":
                return {"case_id": "c-surface"}
            if path.endswith("/enrich-and-score"):
                return {"status": "ok"}
            if path.endswith("/supplier-passport"):
                return {
                    "identity": {
                        "identifiers": {"website": "https://example.com", "cage": "AB123"},
                        "identifier_status": {
                            "website": {"value": "https://example.com"},
                            "cage": {"value": "AB123"},
                        },
                    },
                    "graph": {"entity_count": 1, "relationship_count": 1, "network_entity_count": 1, "network_relationship_count": 1},
                    "monitoring": {"check_count": 1},
                    "ownership": {"profile": {"ownership_pct_resolved": 0.2}},
                }
            if path.endswith("/analysis-status"):
                return {"status": "pending"}
            if path.endswith("/assistant-plan"):
                return {"analyst_prompt": "prompt", "plan": [{"tool_id": "supplier_passport", "required": True}]}
            if path.endswith("/assistant-execute"):
                return {"executed_steps": [{"tool_id": "supplier_passport"}]}
            raise AssertionError(path)

        def request_text(self, method, path, **kwargs):
            return "Defense counterparty trust dossier\nRecent change\nRisk Storyline\nSupplier passport\nAI Narrative Brief\nExecutive judgment"

        def request_bytes(self, method, path, **kwargs):
            from reportlab.pdfgen import canvas
            from io import BytesIO

            buff = BytesIO()
            pdf = canvas.Canvas(buff)
            pdf.drawString(72, 720, "DEFENSE COUNTERPARTY TRUST DOSSIER")
            pdf.drawString(72, 700, "RECENT CHANGE")
            pdf.drawString(72, 680, "RISK STORYLINE")
            pdf.drawString(72, 660, "SUPPLIER PASSPORT")
            pdf.drawString(72, 640, "AI NARRATIVE BRIEF")
            pdf.save()
            return buff.getvalue()

    args = argparse.Namespace(
        base_url="http://example.test",
        email="",
        password="",
        token="token",
        company="Example Systems",
        country="US",
        case_id="",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=True,
        ai_readiness_mode="surface",
        check_assistant=True,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=0,
        auto_stabilize=False,
        expected_domain="example.com",
        expected_cage="AB123",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        expected_min_control_paths=0,
        expected_control_target="",
        warn_on_empty_control_paths=True,
        require_monitoring_history=False,
        report_dir=str(tmp_path),
        print_json=False,
    )

    result = gate.run_demo_gate(args, client=FakeClient())

    assert result.verdict == "GO"
    assert result.warnings == []


def test_run_demo_gate_surface_mode_allows_missing_ai_brief_until_ready(tmp_path):
    class FakeClient:
        def request_json(self, method, path, **kwargs):
            if path == "/api/cases":
                return {"case_id": "c-demo"}
            if path.endswith("/enrich-and-score"):
                return {"status": "ok"}
            if path.endswith("/supplier-passport"):
                return {
                    "identity": {
                        "identifiers": {
                            "website": "https://example.com",
                            "cage": "AB123",
                        },
                        "identifier_status": {
                            "website": {"value": "https://example.com"},
                            "cage": {"value": "AB123"},
                        },
                    },
                    "graph": {
                        "entity_count": 1,
                        "relationship_count": 1,
                        "network_entity_count": 1,
                        "network_relationship_count": 1,
                        "control_paths": [],
                        "claim_health": {},
                    },
                    "monitoring": {"check_count": 1},
                    "ownership": {"profile": {}},
                }
            if path.endswith("/analysis-status"):
                return {"status": "running"}
            if path.endswith("/assistant-plan"):
                return {"plan": [{"tool_id": "supplier_passport", "required": True}], "analyst_prompt": "demo"}
            if path.endswith("/assistant-execute"):
                return {"executed_steps": [{"tool_id": "supplier_passport"}]}
            raise AssertionError(path)

        def request_text(self, method, path, **kwargs):
            return "Defense counterparty trust dossier\nRecent change\nRisk Storyline\nSupplier passport\nExecutive judgment"

        def request_bytes(self, method, path, **kwargs):
            from io import BytesIO

            from reportlab.pdfgen import canvas

            buff = BytesIO()
            pdf = canvas.Canvas(buff)
            pdf.drawString(72, 720, "DEFENSE COUNTERPARTY TRUST DOSSIER")
            pdf.drawString(72, 700, "RECENT CHANGE")
            pdf.drawString(72, 680, "RISK STORYLINE")
            pdf.drawString(72, 660, "SUPPLIER PASSPORT")
            pdf.save()
            return buff.getvalue()

    args = argparse.Namespace(
        base_url="http://example.test",
        email="",
        password="",
        token="token",
        company="Example Systems",
        country="US",
        case_id="",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=True,
        ai_readiness_mode="surface",
        check_assistant=True,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=0,
        auto_stabilize=False,
        expected_domain="example.com",
        expected_cage="AB123",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        expected_min_control_paths=0,
        expected_control_target="",
        warn_on_empty_control_paths=True,
        require_monitoring_history=False,
        report_dir=str(tmp_path),
        print_json=False,
    )

    result = gate.run_demo_gate(args, client=FakeClient())

    assert result.verdict == "GO"
    assert all("missing ai brief" not in failure for failure in result.failures)
    assert result.warnings == []


def test_run_demo_gate_surface_mode_skips_assistant_execute(tmp_path):
    class FakeClient:
        def request_json(self, method, path, **kwargs):
            if path == "/api/cases":
                return {"case_id": "c-demo"}
            if path.endswith("/enrich-and-score"):
                return {"status": "ok"}
            if path.endswith("/supplier-passport"):
                return {
                    "identity": {
                        "identifiers": {"website": "https://example.com", "cage": "AB123"},
                        "identifier_status": {
                            "website": {"value": "https://example.com"},
                            "cage": {"value": "AB123"},
                        },
                    },
                    "graph": {"entity_count": 1, "relationship_count": 1, "network_entity_count": 1, "network_relationship_count": 1},
                    "monitoring": {"check_count": 1},
                    "ownership": {"profile": {}},
                }
            if path.endswith("/analysis-status"):
                return {"status": "ready"}
            if path.endswith("/assistant-plan"):
                return {"plan": [{"tool_id": "supplier_passport", "required": True}], "analyst_prompt": "demo"}
            if path.endswith("/assistant-execute"):
                raise AssertionError("surface mode should not execute assistant tools")
            raise AssertionError(path)

        def request_text(self, method, path, **kwargs):
            return "Defense counterparty trust dossier\nRecent change\nRisk Storyline\nSupplier passport\nAI Narrative Brief\nExecutive judgment"

        def request_bytes(self, method, path, **kwargs):
            from io import BytesIO

            from reportlab.pdfgen import canvas

            buff = BytesIO()
            pdf = canvas.Canvas(buff)
            pdf.drawString(72, 720, "DEFENSE COUNTERPARTY TRUST DOSSIER")
            pdf.drawString(72, 700, "RECENT CHANGE")
            pdf.drawString(72, 680, "RISK STORYLINE")
            pdf.drawString(72, 660, "SUPPLIER PASSPORT")
            pdf.drawString(72, 640, "AI NARRATIVE BRIEF")
            pdf.save()
            return buff.getvalue()

    args = argparse.Namespace(
        base_url="http://example.test",
        email="",
        password="",
        token="token",
        company="Example Systems",
        country="US",
        case_id="",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=True,
        ai_readiness_mode="surface",
        check_assistant=True,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=0,
        auto_stabilize=False,
        expected_domain="example.com",
        expected_cage="AB123",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        expected_min_control_paths=0,
        expected_control_target="",
        warn_on_empty_control_paths=False,
        require_monitoring_history=False,
        report_dir=str(tmp_path),
        print_json=False,
    )

    result = gate.run_demo_gate(args, client=FakeClient())

    assert result.verdict == "GO"
    assert result.assistant_ok is True


def test_run_demo_gate_surface_mode_requests_non_ai_dossier_while_warming(tmp_path):
    calls = {"html_include_ai": None, "pdf_include_ai": None}

    class FakeClient:
        def request_json(self, method, path, **kwargs):
            if path == "/api/cases":
                return {"case_id": "c-demo"}
            if path.endswith("/enrich-and-score"):
                return {"status": "ok"}
            if path.endswith("/supplier-passport"):
                return {
                    "identity": {
                        "identifiers": {"website": "https://example.com", "cage": "AB123"},
                        "identifier_status": {
                            "website": {"value": "https://example.com"},
                            "cage": {"value": "AB123"},
                        },
                    },
                    "graph": {"entity_count": 1, "relationship_count": 1, "network_entity_count": 1, "network_relationship_count": 1},
                    "monitoring": {"check_count": 1},
                    "ownership": {"profile": {}},
                }
            if path.endswith("/analysis-status"):
                return {"status": "running"}
            if path.endswith("/assistant-plan"):
                return {"plan": [{"tool_id": "supplier_passport", "required": True}], "analyst_prompt": "demo"}
            raise AssertionError(path)

        def request_text(self, method, path, **kwargs):
            calls["html_include_ai"] = (kwargs.get("json") or {}).get("include_ai")
            return "Defense counterparty trust dossier\nRecent change\nRisk Storyline\nSupplier passport\nExecutive judgment"

        def request_bytes(self, method, path, **kwargs):
            from io import BytesIO

            from reportlab.pdfgen import canvas

            calls["pdf_include_ai"] = (kwargs.get("json") or {}).get("include_ai")
            buff = BytesIO()
            pdf = canvas.Canvas(buff)
            pdf.drawString(72, 720, "DEFENSE COUNTERPARTY TRUST DOSSIER")
            pdf.drawString(72, 700, "RECENT CHANGE")
            pdf.drawString(72, 680, "RISK STORYLINE")
            pdf.drawString(72, 660, "SUPPLIER PASSPORT")
            pdf.save()
            return buff.getvalue()

    args = argparse.Namespace(
        base_url="http://example.test",
        email="",
        password="",
        token="token",
        company="Example Systems",
        country="US",
        case_id="",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=True,
        ai_readiness_mode="surface",
        check_assistant=True,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=0,
        auto_stabilize=False,
        expected_domain="example.com",
        expected_cage="AB123",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        expected_min_control_paths=0,
        expected_control_target="",
        warn_on_empty_control_paths=False,
        require_monitoring_history=False,
        report_dir=str(tmp_path),
        print_json=False,
    )

    result = gate.run_demo_gate(args, client=FakeClient())

    assert result.verdict == "GO"
    assert calls == {"html_include_ai": False, "pdf_include_ai": False}


def test_run_demo_gate_can_skip_dossier_surfaces_for_targeted_gate(tmp_path):
    calls = {"html": 0, "pdf": 0}

    class FakeClient:
        def __init__(self):
            self.passport_modes = []

        def request_json(self, method, path, **kwargs):
            if path == "/api/cases":
                return {"case_id": "c-demo"}
            if path.endswith("/enrich-and-score"):
                return {"status": "ok"}
            if path.endswith("/supplier-passport"):
                self.passport_modes.append((kwargs.get("params") or {}).get("mode"))
                return {
                    "identity": {
                        "identifiers": {"website": "https://example.com", "cage": "AB123"},
                        "identifier_status": {
                            "website": {"value": "https://example.com"},
                            "cage": {"value": "AB123"},
                        },
                    },
                    "graph": {
                        "entity_count": 2,
                        "relationship_count": 1,
                        "network_entity_count": 2,
                        "network_relationship_count": 1,
                        "control_paths": [{"source_name": "Example", "target_name": "Codan", "rel_type": "owned_by"}],
                    },
                    "monitoring": {"check_count": 1},
                    "ownership": {"profile": {}},
                }
            raise AssertionError(path)

        def request_text(self, method, path, **kwargs):
            calls["html"] += 1
            raise AssertionError("html dossier should be skipped")

        def request_bytes(self, method, path, **kwargs):
            calls["pdf"] += 1
            raise AssertionError("pdf dossier should be skipped")

    args = argparse.Namespace(
        base_url="http://example.test",
        email="",
        password="",
        token="token",
        company="Example Systems",
        country="US",
        case_id="",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=False,
        ai_readiness_mode="surface",
        check_assistant=False,
        require_dossier_html=False,
        require_dossier_pdf=False,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=0,
        auto_stabilize=False,
        expected_domain="example.com",
        expected_cage="AB123",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        expected_min_control_paths=1,
        expected_control_target="Codan",
        warn_on_empty_control_paths=True,
        require_monitoring_history=False,
        report_dir=str(tmp_path),
        print_json=False,
    )

    fake = FakeClient()
    result = gate.run_demo_gate(args, client=fake)

    assert result.verdict == "GO"
    assert calls == {"html": 0, "pdf": 0}
    assert Path(result.artifacts["html"]).read_text(encoding="utf-8").startswith("HTML dossier skipped")
    assert Path(result.artifacts["pdf"]).read_text(encoding="utf-8").startswith("PDF dossier skipped")
    assert fake.passport_modes == ["control"]


def test_run_demo_gate_returns_structured_failure_on_timeout(tmp_path):
    class TimeoutClient:
        def request_json(self, method, path, **kwargs):
            if path == "/api/cases":
                return {"case_id": "c-timeout"}
            if path.endswith("/enrich-and-score"):
                return {"status": "ok"}
            if path.endswith("/analysis-status"):
                return {"status": "ready"}
            raise AssertionError(f"unexpected request_json call: {method} {path}")

        def request_text(self, method, path, **kwargs):
            raise requests.ReadTimeout("timed out")

        def request_bytes(self, method, path, **kwargs):
            raise AssertionError("request_bytes should not run after timeout")

    args = argparse.Namespace(
        base_url="http://example.test",
        email="",
        password="",
        token="token",
        company="Timeout Vendor",
        country="US",
        case_id="",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=True,
        ai_readiness_mode="full",
        check_assistant=True,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        auto_stabilize=True,
        expected_domain="",
        expected_cage="",
        expected_uei="",
        expected_duns="",
        expected_cik="",
        warn_on_empty_control_paths=True,
        require_monitoring_history=False,
        report_dir=str(tmp_path),
        print_json=False,
    )

    result = gate.run_demo_gate(args, client=TimeoutClient())

    assert result.verdict == "NO_GO"
    assert any("ReadTimeout" in failure for failure in result.failures)
    assert Path(result.artifacts["html"]).exists()
    assert Path(result.artifacts["pdf"]).exists()
