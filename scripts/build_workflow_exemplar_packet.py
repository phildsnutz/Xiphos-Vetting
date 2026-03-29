#!/usr/bin/env python3
"""
Build a controlled three-lane workflow exemplar packet for customer-facing demos.

This packet is intentionally local and synthetic. It avoids attributing customer-
provided cyber or export evidence to real companies while still exercising the
real dossier generator, scoring path, and lane-specific evidence flows.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
DEFAULT_OUTPUT_DIR = ROOT / "docs" / "marketing" / "workflow_exemplar_packet_2026-03-24"
DEMO_USER_ID = "workflow-demo"


def _load_backend():
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        server = importlib.import_module("server")
    return server


@contextmanager
def local_demo_app():
    with tempfile.TemporaryDirectory(prefix="helios-workflow-packet-") as temp_dir:
        temp_path = Path(temp_dir)
        os.environ["XIPHOS_DB_PATH"] = str(temp_path / "xiphos-demo.db")
        os.environ["XIPHOS_SECURE_ARTIFACTS_DIR"] = str(temp_path / "secure-artifacts")
        os.environ["XIPHOS_AUTH_ENABLED"] = "false"
        os.environ["XIPHOS_DEV_MODE"] = "true"

        server = _load_backend()
        server.db.init_db()
        server.init_auth_db()
        if server.HAS_AI:
            server.init_ai_tables()

        import hardening  # type: ignore
        hardening.reset_rate_limiter()

        with server.app.test_client() as client:
            yield server, client


def _create_case(client, name: str, country: str, extra_payload: dict | None = None) -> str:
    payload = {
        "name": name,
        "country": country,
        "ownership": {
            "publicly_traded": False,
            "state_owned": False,
            "beneficial_owner_known": True,
            "ownership_pct_resolved": 0.85,
            "shell_layers": 0,
            "pep_connection": False,
        },
        "data_quality": {
            "has_lei": True,
            "has_cage": True,
            "has_duns": True,
            "has_tax_id": True,
            "has_audited_financials": True,
            "years_of_records": 8,
        },
        "exec": {
            "known_execs": 4,
            "adverse_media": 0,
            "pep_execs": 0,
            "litigation_history": 0,
        },
        "program": "dod_unclassified",
        "profile": "defense_acquisition",
    }
    if isinstance(extra_payload, dict):
        payload.update(extra_payload)

    response = client.post("/api/cases", json=payload)
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["case_id"]


def _save_demo_analysis(server, case_id: str, analysis: dict) -> None:
    import ai_analysis  # type: ignore

    vendor = server.db.get_vendor(case_id)
    score = server.db.get_latest_score(case_id) or {}
    enrichment = server.db.get_latest_enrichment(case_id)
    input_hash = ""
    if vendor and score:
        input_hash = ai_analysis.compute_analysis_fingerprint(vendor, score, enrichment)
    ai_analysis.save_analysis(
        case_id,
        provider="openai",
        model="gpt-4o",
        analysis=analysis,
        created_by=DEMO_USER_ID,
        input_hash=input_hash,
    )


def _counterparty_case(server, client):
    import foci_artifact_intake  # type: ignore

    case_id = _create_case(
        client,
        name="Allied Avionics Systems LLC",
        country="US",
        extra_payload={
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
        },
    )

    foci_artifact_intake.ingest_foci_artifact(
        case_id,
        "foci_mitigation_instrument",
        "ssa-summary.txt",
        b"Special Security Agreement covering 25% foreign ownership by Allied Parent Holdings in GB with board-level mitigation controls.",
        declared_foreign_owner="Allied Parent Holdings",
        declared_foreign_country="GB",
        declared_foreign_ownership_pct="25%",
        declared_mitigation_status="MITIGATED",
        declared_mitigation_type="SSA",
        uploaded_by=DEMO_USER_ID,
    )

    score_resp = client.post(f"/api/cases/{case_id}/score", json={})
    assert score_resp.status_code == 200, score_resp.get_data(as_text=True)
    score = score_resp.get_json()
    tier = score.get("calibrated", {}).get("calibrated_tier") or score.get("tier") or "TIER_3_CONDITIONAL"
    server.db.save_monitoring_log(
        vendor_id=case_id,
        previous_risk="TIER_4_APPROVED",
        current_risk=tier,
        risk_changed=tier != "TIER_4_APPROVED",
        new_findings_count=2,
        resolved_findings_count=0,
    )
    _save_demo_analysis(
        server,
        case_id,
        {
            "executive_summary": "Qualified approval is supportable because the foreign interest is identified and appears mitigated under a Special Security Agreement, but adjudicators should keep the ownership/control chain explicit in the record.",
            "risk_narrative": "The case is not a hard stop. The main issue is foreign ownership with mitigation documentation, which points to a controlled review posture rather than a clean pass.",
            "critical_concerns": ["Foreign ownership interest requires documented adjudication and mitigation review."],
            "mitigating_factors": ["Mitigation instrument indicates an SSA structure and known foreign parent."],
            "recommended_actions": ["Validate the SSA terms and board controls.", "Keep the vendor on watchlist monitoring for ownership/control changes."],
            "regulatory_exposure": "FOCI-sensitive adjudication with mitigated foreign ownership.",
            "confidence_assessment": "Medium-high confidence because the ownership and mitigation facts are explicit in the uploaded evidence.",
            "verdict": "QUALIFY",
        },
    )
    return {
        "case_id": case_id,
        "label": "Defense counterparty trust",
        "packet_slug": "defense-counterparty-trust-allied-avionics-systems-llc",
        "vendor_name": "Allied Avionics Systems LLC",
        "summary": "Mitigated foreign ownership with a documented SSA, resulting in a qualified-watch posture rather than a clean pass.",
    }


def _cyber_case(server, client):
    import sprs_import_intake  # type: ignore
    import oscal_intake  # type: ignore
    from artifact_vault import store_artifact  # type: ignore

    case_id = _create_case(
        client,
        name="Horizon Mission Systems LLC",
        country="US",
        extra_payload={
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
        },
    )

    sprs_import_intake.ingest_sprs_export(
        case_id,
        "Horizon Mission Systems LLC",
        "sprs-export.csv",
        (
            b"supplier_name,sprs_score,assessment_date,status,current_cmmc_level,poam\n"
            b"Horizon Mission Systems LLC,82,2026-03-02,Conditional,1,Yes\n"
        ),
        uploaded_by=DEMO_USER_ID,
    )

    oscal_intake.ingest_oscal_artifact(
        case_id,
        "poam.json",
        (
            b'{"plan-of-action-and-milestones":{"metadata":{"title":"Supplier POA&M"},'
            b'"system-characteristics":{"system-name":"Horizon Secure Fabric"},'
            b'"poam-items":[{"id":"poam-1","title":"Encrypt removable media","status":"open","due-date":"2026-04-15","control-id":"sc-28"},'
            b'{"id":"poam-2","title":"Tighten MFA enforcement","status":"open","due-date":"2026-04-22","control-id":"ia-2"}]}}'
        ),
        uploaded_by=DEMO_USER_ID,
    )

    nvd_payload = {
        "summary": {
            "vendor_name": "Horizon Mission Systems LLC",
            "product_terms": ["Mission Hub"],
            "unique_cve_count": 3,
            "high_or_critical_cve_count": 2,
            "critical_cve_count": 1,
            "kev_flagged_cve_count": 1,
            "latest_published": "2026-03-01T00:00:00Z",
        },
        "product_terms": ["Mission Hub"],
        "top_cves": [
            {"id": "CVE-2026-1001", "severity": "CRITICAL", "kev_date": "2026-03-05"},
            {"id": "CVE-2026-1002", "severity": "HIGH", "kev_date": ""},
        ],
    }
    store_artifact(
        case_id,
        "nvd_overlay",
        "nvd-overlay-demo.json",
        json.dumps(nvd_payload).encode("utf-8"),
        source_system="nvd_overlay",
        uploaded_by=DEMO_USER_ID,
        retention_class="cyber_posture",
        sensitivity="controlled",
        parse_status="parsed",
        structured_fields={
            "summary": nvd_payload["summary"],
            "product_terms": ["Mission Hub"],
            "notes": "Controlled demo overlay",
        },
    )

    score_resp = client.post(f"/api/cases/{case_id}/score", json={})
    assert score_resp.status_code == 200, score_resp.get_data(as_text=True)
    score = score_resp.get_json()
    tier = score.get("calibrated", {}).get("calibrated_tier") or score.get("tier") or "TIER_3_CONDITIONAL"
    server.db.save_monitoring_log(
        vendor_id=case_id,
        previous_risk="TIER_4_APPROVED",
        current_risk=tier,
        risk_changed=tier != "TIER_4_APPROVED",
        new_findings_count=3,
        resolved_findings_count=0,
    )
    _save_demo_analysis(
        server,
        case_id,
        {
            "executive_summary": "The supplier cyber posture should be treated as a review case because the current evidence supports only CMMC Level 1 readiness, active remediation remains open, and a critical product vulnerability is still present.",
            "risk_narrative": "This is not a hard disqualifier, but the current attestation and remediation state is below the expected posture for CUI-sensitive work.",
            "critical_concerns": ["Current CMMC level is below the required level for the mission context.", "Open remediation items and a KEV-linked critical vulnerability increase operational risk."],
            "mitigating_factors": ["Supplier provided structured SPRS and OSCAL evidence rather than unsupported claims."],
            "recommended_actions": ["Require remediation milestones before expanded scope.", "Track vulnerability closure and reassess after control evidence is refreshed."],
            "regulatory_exposure": "CMMC readiness gap with active remediation pressure.",
            "confidence_assessment": "High confidence because the posture is grounded in attestation, remediation, and vulnerability evidence.",
            "verdict": "REVIEW",
        },
    )
    return {
        "case_id": case_id,
        "label": "Supplier cyber trust",
        "packet_slug": "supplier-cyber-trust-horizon-mission-systems-llc",
        "vendor_name": "Horizon Mission Systems LLC",
        "summary": "CMMC readiness gap with active POA&M and critical vulnerability pressure.",
    }


def _export_case(server, client):
    import export_artifact_intake  # type: ignore

    case_id = _create_case(
        client,
        name="Orbital Sensor Dynamics GmbH",
        country="DE",
        extra_payload={
            "program": "cat_xi_electronics",
            "profile": "itar_trade_compliance",
            "export_authorization": {
                "request_type": "foreign_person_access",
                "recipient_name": "Orbital Sensor Dynamics GmbH",
                "destination_country": "DE",
                "jurisdiction_guess": "itar",
                "classification_guess": "USML Category XI",
                "item_or_data_summary": "Mission radar source code and diagnostic interface data",
                "end_use_summary": "Controlled mission-system integration support",
                "foreign_person_nationalities": ["IR"],
            },
        },
    )

    export_artifact_intake.ingest_export_artifact(
        case_id,
        "export_classification_memo",
        "classification-memo.txt",
        b"USML Category XI mission radar source code. Foreign person access review required. Deemed export restrictions apply. No license exception available.",
        uploaded_by=DEMO_USER_ID,
        declared_classification="USML Category XI",
        declared_jurisdiction="itar",
    )

    score_resp = client.post(f"/api/cases/{case_id}/score", json={})
    assert score_resp.status_code == 200, score_resp.get_data(as_text=True)
    score = score_resp.get_json()
    tier = score.get("calibrated", {}).get("calibrated_tier") or score.get("tier") or "TIER_1_DISQUALIFIED"
    server.db.save_monitoring_log(
        vendor_id=case_id,
        previous_risk="TIER_3_CONDITIONAL",
        current_risk=tier,
        risk_changed=True,
        new_findings_count=1,
        resolved_findings_count=0,
    )
    _save_demo_analysis(
        server,
        case_id,
        {
            "executive_summary": "This request should be treated as a hard export-control stop because the case indicates ITAR-controlled technical data and a foreign-person access request with Iranian nationality.",
            "risk_narrative": "The decision path is straightforward: the request is not a low-friction authorization scenario and requires formal stop/escalation handling.",
            "critical_concerns": ["Deemed export risk is high for the stated nationality and ITAR-controlled data.", "The classification and foreign-person context point away from an exception-based path."],
            "mitigating_factors": ["A classification memo is present, which supports defensible documentation."],
            "recommended_actions": ["Escalate to export counsel or trade compliance immediately.", "Block access until a formal authorization path is established."],
            "regulatory_exposure": "ITAR / deemed export risk with likely prohibition posture.",
            "confidence_assessment": "High confidence because the jurisdiction, classification, and foreign-person context are explicit in the case input and customer artifact.",
            "verdict": "BLOCK",
        },
    )
    return {
        "case_id": case_id,
        "label": "Export authorization",
        "packet_slug": "export-authorization-orbital-sensor-dynamics-gmbh",
        "vendor_name": "Orbital Sensor Dynamics GmbH",
        "summary": "ITAR-controlled foreign-person access request with high deemed-export risk and stop/escalate posture.",
    }


def _render_packet_index(items: list[dict], generated_at: str) -> str:
    lines = [
        "# Helios 3-Lane Workflow Exemplar Packet",
        "",
        f"Generated: {generated_at}",
        "",
        "This packet contains controlled workflow exemplars built locally to demonstrate the three primary Helios lanes without attributing synthetic cyber or export evidence to real companies.",
        "",
        "## Included Exemplars",
        "",
    ]
    for item in items:
        lines.extend(
            [
                f"### {item['label']}: {item['vendor_name']}",
                "",
                f"- Case ID: `{item['case_id']}`",
                f"- Summary: {item['summary']}",
                f"- HTML dossier: [{Path(item['html_path']).name}]({item['html_path']})",
                f"- PDF dossier: [{Path(item['pdf_path']).name}]({item['pdf_path']})",
                "",
            ]
        )
    lines.extend(
        [
            "## Why This Packet Exists",
            "",
            "- The existing live sample packet is strongest for the defense counterparty trust lane and remains the best proof of mature live product behavior.",
            "- This packet complements it by showing one controlled exemplar for each of the three primary Helios lanes.",
            "- These are demonstration artifacts, not claims about real customer-submitted cyber or export evidence for the named entities.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_packet(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().isoformat(timespec="seconds")

    with local_demo_app() as (server, client):
        items = [
            _counterparty_case(server, client),
            _cyber_case(server, client),
            _export_case(server, client),
        ]

        import dossier  # type: ignore
        import dossier_pdf  # type: ignore

        for item in items:
            html = dossier.generate_dossier(item["case_id"], user_id=DEMO_USER_ID, hydrate_ai=False)
            pdf = dossier_pdf.generate_pdf_dossier(item["case_id"], user_id=DEMO_USER_ID, hydrate_ai=False)

            html_path = output_dir / f"{item['packet_slug']}.html"
            pdf_path = output_dir / f"{item['packet_slug']}.pdf"
            html_path.write_text(html, encoding="utf-8")
            pdf_path.write_bytes(pdf)
            item["html_path"] = str(html_path)
            item["pdf_path"] = str(pdf_path)

    packet_index = output_dir / "HELIOS_3_LANE_WORKFLOW_EXEMPLAR_PACKET_2026-03-24.md"
    packet_index.write_text(_render_packet_index(items, generated_at), encoding="utf-8")

    summary = {
        "generated_at": generated_at,
        "packet_index": str(packet_index),
        "items": items,
    }
    (output_dir / "workflow-exemplar-packet-summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    summary = build_packet(DEFAULT_OUTPUT_DIR)
    print(f"Wrote {summary['packet_index']}")
    for item in summary["items"]:
        print(f"Exported {item['label']} -> {item['html_path']} and {item['pdf_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
