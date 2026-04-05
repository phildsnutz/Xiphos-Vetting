from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from helios_core.recommendations import resolve_case_recommendation


_COLOR_BY_POSTURE = {
    "approved": "#198754",
    "review": "#C4A052",
    "blocked": "#dc3545",
    "pending": "#6c757d",
}


def _program_label(program_labels: dict[str, str], vendor: dict[str, Any]) -> str:
    vendor_input = vendor.get("vendor_input", {}) if isinstance(vendor.get("vendor_input"), dict) else {}
    program_raw = vendor_input.get("program", vendor.get("program", "")) or ""
    return program_labels.get(program_raw, program_raw or "Not set")


def _clean_detail(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _severity_rank(severity: str) -> int:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    return order.get(str(severity or "info").lower(), 5)


def _collect_graph_holds(graph_summary: dict[str, Any] | None) -> list[str]:
    if not isinstance(graph_summary, dict):
        return []
    relationships = graph_summary.get("relationships") or []
    holds: list[str] = []
    for rel in relationships[:4]:
        if not isinstance(rel, dict):
            continue
        source_name = str(rel.get("source_name") or rel.get("source_entity_name") or rel.get("source_entity_id") or "").strip()
        target_name = str(rel.get("target_name") or rel.get("target_entity_name") or rel.get("target_entity_id") or "").strip()
        rel_type = str(rel.get("rel_type") or "related_to").replace("_", " ")
        corroboration = int(rel.get("corroboration_count") or len(rel.get("data_sources") or []) or 1)
        if source_name and target_name:
            holds.append(f"{source_name} {rel_type} {target_name} with {corroboration} corroborating record{'s' if corroboration != 1 else ''}.")
    return holds


def _collect_passport_holds(context: dict[str, Any]) -> list[str]:
    passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}
    holds: list[str] = []
    threat = passport.get("threat_intel") if isinstance(passport.get("threat_intel"), dict) else {}
    advisories = [str(item) for item in (threat.get("cisa_advisory_ids") or []) if str(item).strip()]
    if advisories:
        holds.append("Threat context includes " + ", ".join(advisories[:3]) + ".")

    control_paths = (passport.get("graph") or {}).get("control_paths") if isinstance(passport.get("graph"), dict) else []
    for rel in control_paths[:2]:
        if not isinstance(rel, dict):
            continue
        source_name = _clean_detail(rel.get("source_name"))
        target_name = _clean_detail(rel.get("target_name"))
        rel_type = _clean_detail(rel.get("rel_type")).replace("_", " ")
        if source_name and target_name:
            holds.append(f"{source_name} {rel_type} {target_name}.")

    foci_summary = context.get("foci_summary") if isinstance(context.get("foci_summary"), dict) else {}
    foreign_owner = _clean_detail(foci_summary.get("declared_foreign_owner"))
    ownership_pct = _clean_detail(
        foci_summary.get("declared_foreign_ownership_pct")
        or (f"{foci_summary.get('max_ownership_percent_mention')}%" if isinstance(foci_summary.get("max_ownership_percent_mention"), (int, float)) else "")
    )
    mitigation_type = _clean_detail(foci_summary.get("declared_mitigation_type") or foci_summary.get("declared_mitigation_status"))
    if foreign_owner or ownership_pct or mitigation_type:
        detail = ", ".join(bit for bit in [foreign_owner, ownership_pct, mitigation_type] if bit)
        holds.append(f"FOCI evidence is carrying {detail}.")

    cyber_summary = context.get("cyber_summary") if isinstance(context.get("cyber_summary"), dict) else {}
    cyber_bits = []
    current_level = cyber_summary.get("current_cmmc_level")
    if current_level:
        cyber_bits.append(f"CMMC Level {current_level}")
    open_poam_items = int(cyber_summary.get("open_poam_items") or 0)
    if cyber_summary.get("poam_active"):
        cyber_bits.append(
            f"POA&M active{f' with {open_poam_items} open item' + ('s' if open_poam_items != 1 else '') if open_poam_items > 0 else ''}"
        )
    if open_poam_items > 0:
        cyber_bits.append(f"{open_poam_items} open POA&M item{'s' if open_poam_items != 1 else ''}")
    if cyber_bits:
        holds.append("Cyber evidence is carrying " + ", ".join(cyber_bits) + ".")

    export_summary = context.get("export_summary") if isinstance(context.get("export_summary"), dict) else {}
    classification = _clean_detail(export_summary.get("classification_display") or export_summary.get("classification_guess"))
    if classification:
        holds.append(f"Export control evidence is anchored to {classification}.")

    return holds


def _collect_passport_gaps(context: dict[str, Any]) -> list[str]:
    passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}
    gaps: list[str] = []

    identity = passport.get("identity") if isinstance(passport.get("identity"), dict) else {}
    identifier_status = identity.get("identifier_status") if isinstance(identity.get("identifier_status"), dict) else {}
    for key, value in identifier_status.items():
        if not isinstance(value, dict):
            continue
        state = str(value.get("state") or "")
        if state in {"verified_present", "verified_partial"}:
            continue
        retry = _clean_detail(value.get("next_access_time"))
        reason = _clean_detail(value.get("reason"))
        line = f"{str(key).upper()} is still {state.replace('_', ' ') or 'unverified'}."
        if retry:
            line += f" Retry after {retry}."
        elif reason:
            line += f" {reason}"
        gaps.append(line.strip())

    ownership = passport.get("ownership") if isinstance(passport.get("ownership"), dict) else {}
    workflow_control = ownership.get("workflow_control") if isinstance(ownership.get("workflow_control"), dict) else {}
    label = _clean_detail(workflow_control.get("label"))
    review_basis = _clean_detail(workflow_control.get("review_basis"))
    if label or review_basis:
        gaps.append(". ".join(bit for bit in [label, review_basis] if bit) + ".")

    return gaps


def _collect_evidence_findings(context: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}

    threat = passport.get("threat_intel") if isinstance(passport.get("threat_intel"), dict) else {}
    advisories = [str(item) for item in (threat.get("cisa_advisory_ids") or []) if str(item).strip()]
    if advisories:
        findings.append(
            {
                "title": "Threat context",
                "detail": "Threat intelligence includes " + ", ".join(advisories[:3]) + ".",
                "severity": str(threat.get("threat_pressure") or "medium").lower(),
                "source": "threat_intel",
            }
        )

    control_paths = (passport.get("graph") or {}).get("control_paths") if isinstance(passport.get("graph"), dict) else []
    for rel in control_paths[:2]:
        if not isinstance(rel, dict):
            continue
        evidence_refs = rel.get("evidence_refs") or []
        evidence_title = ""
        if evidence_refs and isinstance(evidence_refs[0], dict):
            evidence_title = _clean_detail(evidence_refs[0].get("title"))
        findings.append(
            {
                "title": evidence_title or "Control path",
                "detail": " ".join(
                    bit
                    for bit in [
                        _clean_detail(rel.get("source_name")),
                        _clean_detail(rel.get("rel_type")).replace("_", " "),
                        _clean_detail(rel.get("target_name")),
                    ]
                    if bit
                ),
                "severity": "medium",
                "source": "graph_control",
            }
        )

    ownership = passport.get("ownership") if isinstance(passport.get("ownership"), dict) else {}
    workflow_control = ownership.get("workflow_control") if isinstance(ownership.get("workflow_control"), dict) else {}
    label = _clean_detail(workflow_control.get("label"))
    review_basis = _clean_detail(workflow_control.get("review_basis"))
    if label or review_basis:
        findings.append(
            {
                "title": label or "Workflow control",
                "detail": review_basis or _clean_detail(workflow_control.get("action_owner"), "Analyst review is still required."),
                "severity": "medium",
                "source": "workflow_control",
            }
        )

    foci_summary = context.get("foci_summary") if isinstance(context.get("foci_summary"), dict) else {}
    foreign_owner = _clean_detail(foci_summary.get("declared_foreign_owner"))
    ownership_pct = _clean_detail(
        foci_summary.get("declared_foreign_ownership_pct")
        or (f"{foci_summary.get('max_ownership_percent_mention')}%" if isinstance(foci_summary.get("max_ownership_percent_mention"), (int, float)) else "")
    )
    mitigation_type = _clean_detail(foci_summary.get("declared_mitigation_type") or foci_summary.get("declared_mitigation_status"))
    if foreign_owner or ownership_pct or mitigation_type:
        findings.append(
            {
                "title": "FOCI evidence",
                "detail": ", ".join(bit for bit in [foreign_owner, ownership_pct, mitigation_type] if bit),
                "severity": "medium",
                "source": "foci_evidence",
            }
        )

    cyber_summary = context.get("cyber_summary") if isinstance(context.get("cyber_summary"), dict) else {}
    current_level = cyber_summary.get("current_cmmc_level")
    open_poam_items = int(cyber_summary.get("open_poam_items") or 0)
    cyber_detail_bits = []
    if current_level:
        cyber_detail_bits.append(f"CMMC Level {current_level}")
    if cyber_summary.get("poam_active"):
        cyber_detail_bits.append(
            f"POA&M active{f' with {open_poam_items} open item' + ('s' if open_poam_items != 1 else '') if open_poam_items > 0 else ''}"
        )
    if open_poam_items > 0:
        cyber_detail_bits.append(f"POA&M active with {open_poam_items} open item{'s' if open_poam_items != 1 else ''}")
    if cyber_detail_bits:
        findings.append(
            {
                "title": "Cyber evidence",
                "detail": ", ".join(cyber_detail_bits),
                "severity": "medium" if open_poam_items > 0 else "low",
                "source": "cyber_evidence",
            }
        )

    export_summary = context.get("export_summary") if isinstance(context.get("export_summary"), dict) else {}
    classification = _clean_detail(export_summary.get("classification_display") or export_summary.get("classification_guess"))
    posture = _clean_detail(export_summary.get("posture_label"))
    if classification or posture:
        findings.append(
            {
                "title": "Export evidence",
                "detail": ", ".join(bit for bit in [classification, posture] if bit),
                "severity": "medium",
                "source": "export_evidence",
            }
        )

    return findings


def _collect_gap_lines(context: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}
    identity = passport.get("identity") if isinstance(passport.get("identity"), dict) else {}
    identifier_status = identity.get("identifier_status") if isinstance(identity.get("identifier_status"), dict) else {}
    missing_ids = []
    for key, value in identifier_status.items():
        if not isinstance(value, dict):
            continue
        state = str(value.get("state") or "")
        if state not in {"verified_present", "verified_partial"}:
            missing_ids.append(key.upper())
    if missing_ids:
        gaps.append("Identity anchors still thin on: " + ", ".join(missing_ids[:4]) + ".")

    graph_summary = context.get("graph_summary") if isinstance(context.get("graph_summary"), dict) else {}
    intelligence = graph_summary.get("intelligence") if isinstance(graph_summary.get("intelligence"), dict) else {}
    missing_families = intelligence.get("missing_required_edge_families") if isinstance(intelligence.get("missing_required_edge_families"), list) else []
    if missing_families:
        gaps.append(
            "Graph fabric is still missing: "
            + ", ".join(str(family).replace("_", " ") for family in missing_families[:4])
            + "."
        )
    contradicted = int(intelligence.get("contradicted_edge_count") or 0)
    if contradicted > 0:
        gaps.append(f"{contradicted} contradicted graph claim{'s' if contradicted != 1 else ''} still need adjudication.")
    stale = int(intelligence.get("stale_edge_count") or 0)
    if stale > 0:
        gaps.append(f"{stale} graph edge{'s' if stale != 1 else ''} are stale enough to justify refresh.")

    analysis_data = context.get("analysis_data")
    analysis_state = str(context.get("analysis_state") or "idle")
    if not analysis_data:
        if analysis_state == "warming":
            gaps.append("Axiom is still warming this brief against the current evidence bundle.")
        else:
            gaps.append("Axiom has not yet added a separate challenge layer beyond the current evidence bundle.")
    return gaps


def _build_axiom_assessment(context: dict[str, Any], recommendation: dict[str, Any]) -> dict[str, Any]:
    analysis_data = context.get("analysis_data") if isinstance(context.get("analysis_data"), dict) else {}
    analysis = analysis_data.get("analysis") if isinstance(analysis_data.get("analysis"), dict) else {}
    analysis_state = str(context.get("analysis_state") or "idle")
    storyline = context.get("storyline") if isinstance(context.get("storyline"), dict) else {}
    cards = storyline.get("cards") if isinstance(storyline.get("cards"), list) else []
    score = context.get("score") if isinstance(context.get("score"), dict) else {}
    calibrated = score.get("calibrated") if isinstance(score.get("calibrated"), dict) else {}
    probability = float(calibrated.get("calibrated_probability") or 0.0)
    graph_summary = context.get("graph_summary") if isinstance(context.get("graph_summary"), dict) else {}
    graph_intelligence = graph_summary.get("intelligence") if isinstance(graph_summary.get("intelligence"), dict) else {}
    claim_coverage_pct = float(graph_intelligence.get("claim_coverage_pct") or 0.0)

    if analysis:
        summary = _clean_detail(
            analysis.get("executive_summary"),
            "Axiom did not add a usable executive judgment even though the challenge layer is present.",
        )
        support = _clean_detail(
            analysis.get("risk_narrative") or analysis.get("regulatory_exposure"),
            recommendation["summary"],
        )
        confidence = _clean_detail(
            analysis.get("confidence_assessment"),
            f"{round(probability * 100)}% model-estimated risk with {round(claim_coverage_pct * 100)}% graph claim coverage.",
        )
        concerns = [str(item) for item in (analysis.get("critical_concerns") or []) if str(item).strip()]
        offsets = [str(item) for item in (analysis.get("mitigating_factors") or []) if str(item).strip()]
        actions = [str(item) for item in (analysis.get("recommended_actions") or []) if str(item).strip()]
    elif analysis_state == "warming":
        summary = "Axiom is still warming the challenge layer against the current evidence bundle."
        support = "The deterministic posture, supplier passport, and graph-backed evidence below are current; the authored challenge layer has not landed yet."
        confidence = f"{round(probability * 100)}% model-estimated risk with {round(claim_coverage_pct * 100)}% graph claim coverage while Axiom is still warming."
        concerns = []
        offsets = []
        actions = []
    else:
        lead_card = cards[0] if cards else {}
        title = _clean_detail(lead_card.get("title"), f"Helios is holding this case at {recommendation['label']}.")
        body = _clean_detail(lead_card.get("body"), recommendation["summary"])
        summary = f"{title} {body}".strip()
        support = recommendation["summary"]
        confidence = f"{round(probability * 100)}% posterior risk with {round(claim_coverage_pct * 100)}% graph claim coverage."
        concerns = []
        offsets = []
        actions = []

    if not concerns:
        concerns = _collect_gap_lines(context)[:3]
    if not offsets:
        offsets = _collect_graph_holds(context.get("graph_summary"))[:3]
    if not actions:
        actions = _collect_gap_lines(context)[:2]

    return {
        "summary": summary,
        "support": support,
        "confidence": confidence,
        "concerns": concerns[:4],
        "offsets": offsets[:4],
        "actions": actions[:4],
    }


def _distill_context(context: dict[str, Any]) -> dict[str, Any]:
    from dossier import PROGRAM_LABELS, _curate_dossier_findings

    vendor = context["vendor"]
    score = context.get("score") if isinstance(context.get("score"), dict) else {}
    calibrated = score.get("calibrated") if isinstance(score.get("calibrated"), dict) else {}
    supplier_passport = context.get("supplier_passport") if isinstance(context.get("supplier_passport"), dict) else {}
    latest_decision = None
    decisions = context.get("decisions")
    if isinstance(decisions, list) and decisions:
        latest_decision = decisions[0]

    recommendation = resolve_case_recommendation(
        score=score,
        supplier_passport=supplier_passport,
        latest_decision=latest_decision,
    )

    graph_summary = context.get("graph_summary") if isinstance(context.get("graph_summary"), dict) else {}
    relationships = graph_summary.get("relationships") if isinstance(graph_summary.get("relationships"), list) else []
    top_relationships = []
    for rel in relationships[:5]:
        if not isinstance(rel, dict):
            continue
        top_relationships.append(
            {
                "rel_type": str(rel.get("rel_type") or "related_to").replace("_", " "),
                "source": _clean_detail(rel.get("source_name") or rel.get("source_entity_name") or rel.get("source_entity_id")),
                "target": _clean_detail(rel.get("target_name") or rel.get("target_entity_name") or rel.get("target_entity_id")),
                "evidence": _clean_detail(rel.get("evidence_summary") or rel.get("evidence")),
                "corroboration": int(rel.get("corroboration_count") or len(rel.get("data_sources") or []) or 1),
            }
        )

    enrichment = context.get("enrichment") if isinstance(context.get("enrichment"), dict) else {}
    curated_findings = []
    for finding in _curate_dossier_findings(enrichment, limit=8):
        if not isinstance(finding, dict):
            continue
        curated_findings.append(
            {
                "title": _clean_detail(finding.get("title"), "Untitled finding"),
                "detail": _clean_detail(finding.get("detail") or finding.get("assessment"), "No analyst-ready detail attached."),
                "severity": str(finding.get("severity") or "info").lower(),
                "source": _clean_detail(finding.get("source"), "unknown"),
            }
        )
    curated_findings.extend(_collect_evidence_findings(context))
    curated_findings.sort(key=lambda item: (_severity_rank(item["severity"]), item["title"]))

    passport_identity = supplier_passport.get("identity") if isinstance(supplier_passport.get("identity"), dict) else {}
    identifiers = passport_identity.get("identifiers") if isinstance(passport_identity.get("identifiers"), dict) else {}
    identity_lines = []
    for key in ("cage", "uei", "lei", "cik"):
        value = identifiers.get(key)
        if value:
            identity_lines.append(f"{key.upper()}: {value}")

    storyline = context.get("storyline") if isinstance(context.get("storyline"), dict) else {}
    story_cards = storyline.get("cards") if isinstance(storyline.get("cards"), list) else []
    what_holds = []
    for card in story_cards[:3]:
        if not isinstance(card, dict):
            continue
        title = _clean_detail(card.get("title"))
        body = _clean_detail(card.get("body"))
        if title or body:
            what_holds.append(f"{title}. {body}".strip(". "))
    what_holds.extend(_collect_graph_holds(graph_summary))
    what_holds.extend(_collect_passport_holds(context))

    axiom = _build_axiom_assessment(context, recommendation)
    gaps = _collect_gap_lines(context)
    gaps.extend(_collect_passport_gaps(context))

    probability = round(float(calibrated.get("calibrated_probability") or 0.0) * 100)
    confidence_low = round(float((calibrated.get("interval") or {}).get("lower") or 0.0) * 100)
    confidence_high = round(float((calibrated.get("interval") or {}).get("upper") or 0.0) * 100)

    graph_intelligence = graph_summary.get("intelligence") if isinstance(graph_summary.get("intelligence"), dict) else {}
    graph_read = {
        "relationship_count": int(graph_summary.get("relationship_count") or len(relationships)),
        "entity_count": int(graph_summary.get("entity_count") or len(graph_summary.get("entities") or [])),
        "claim_coverage_pct": round(float(graph_intelligence.get("claim_coverage_pct") or 0.0) * 100),
        "edge_family_count": len(graph_intelligence.get("edge_family_counts") or {}),
        "top_relationships": top_relationships,
    }

    summary_line = (
        f"{vendor.get('name', 'Unknown')} is currently held at {recommendation['label']} "
        f"with {probability}% model-estimated risk and a {confidence_low}% to {confidence_high}% confidence band."
    )

    return {
        "vendor_name": vendor.get("name", "Unknown"),
        "country": vendor.get("country", "Unknown"),
        "program_label": _program_label(PROGRAM_LABELS, vendor),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "recommendation": recommendation,
        "summary_line": summary_line,
        "identity_lines": identity_lines,
        "axiom": axiom,
        "what_holds": what_holds[:6],
        "gaps": gaps[:6],
        "graph_read": graph_read,
        "findings": curated_findings,
    }


def _html_badge(label: str, posture: str) -> str:
    return f'<span class="badge badge-{escape(posture)}">{escape(label)}</span>'


def _html_list(items: list[str], empty_text: str) -> str:
    if not items:
        return f'<li class="empty-line">{escape(empty_text)}</li>'
    return "".join(f"<li>{escape(item)}</li>" for item in items)


def _render_html_brief(payload: dict[str, Any]) -> str:
    recommendation = payload["recommendation"]
    posture = recommendation["posture"]
    graph_read = payload["graph_read"]
    finding_rows = "".join(
        f"""
        <tr>
            <td>{escape(item['title'])}</td>
            <td>{escape(item['source'].replace('_', ' ').title())}</td>
            <td>{escape(item['severity'].upper())}</td>
            <td>{escape(item['detail'])}</td>
        </tr>
        """
        for item in payload["findings"][:8]
    ) or '<tr><td colspan="4" class="empty-line">No material findings survived curation.</td></tr>'

    graph_cards = "".join(
        f"""
        <div class="graph-card">
            <div class="graph-card-title">{escape(rel['source'])} → {escape(rel['target'])}</div>
            <div class="graph-card-chip">{escape(rel['rel_type'].title())} · {rel['corroboration']} record{'s' if rel['corroboration'] != 1 else ''}</div>
            <div class="graph-card-body">{escape(rel['evidence'] or 'No narrative evidence summary is attached yet.')}</div>
        </div>
        """
        for rel in graph_read["top_relationships"]
    ) or '<div class="graph-card"><div class="graph-card-body">The graph did not return a usable relationship set for this case.</div></div>'

    identity_html = "".join(f"<span class=\"identity-chip\">{escape(line)}</span>" for line in payload["identity_lines"]) or '<span class="identity-chip muted">Identity anchors are still thin.</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Helios Brief | {escape(payload['vendor_name'])}</title>
  <style>
    :root {{
      --bg: #07111b;
      --surface: #0d1724;
      --surface-2: #111d2d;
      --ink: #e8edf3;
      --muted: #8ea0b6;
      --line: #1f3147;
      --gold: #c4a052;
      --approved: #198754;
      --review: #c4a052;
      --blocked: #dc3545;
      --pending: #6c757d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: linear-gradient(180deg, #07111b 0%, #0a1628 100%);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      line-height: 1.6;
    }}
    .page {{ max-width: 1080px; margin: 0 auto; padding: 32px 28px 56px; }}
    .hero {{
      background: linear-gradient(135deg, rgba(17,29,45,0.96) 0%, rgba(10,22,40,0.98) 100%);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 24px 48px rgba(0,0,0,0.22);
    }}
    .eyebrow {{
      color: var(--gold);
      font-size: 12px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      font-weight: 700;
      margin-bottom: 10px;
    }}
    h1 {{ margin: 0; font-size: 34px; line-height: 1.15; }}
    .hero-meta {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      align-items: center;
      margin-top: 16px;
      color: var(--muted);
      font-size: 13px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 7px 12px;
      color: white;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
    }}
    .badge-approved {{ background: var(--approved); }}
    .badge-review {{ background: var(--review); color: #07111b; }}
    .badge-blocked {{ background: var(--blocked); }}
    .badge-pending {{ background: var(--pending); }}
    .summary {{
      margin-top: 18px;
      font-size: 16px;
      color: #dce5ee;
      max-width: 860px;
    }}
    .identity-row {{
      margin-top: 16px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .identity-chip {{
      display: inline-flex;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.09);
      font-size: 12px;
      color: #d7e2ee;
    }}
    .identity-chip.muted {{ color: var(--muted); }}
    .grid {{
      display: grid;
      gap: 18px;
      grid-template-columns: 1.4fr 1fr;
      margin-top: 22px;
    }}
    .card {{
      background: rgba(13,23,36,0.94);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px;
    }}
    .card h2 {{
      margin: 0 0 10px;
      font-size: 18px;
      color: white;
    }}
    .support-line {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 12px;
    }}
    .axiom-summary {{
      font-size: 15px;
      color: #edf3f9;
    }}
    .subtle {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 10px;
    }}
    .split {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      margin-top: 18px;
    }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 0 0 8px; color: #d8e2ed; }}
    .empty-line {{ color: var(--muted); }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .metric {{
      padding: 14px;
      border-radius: 16px;
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.06);
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 700;
    }}
    .metric-value {{
      margin-top: 6px;
      font-size: 24px;
      font-weight: 700;
      color: white;
    }}
    .graph-grid {{
      display: grid;
      gap: 12px;
      margin-top: 14px;
    }}
    .graph-card {{
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 16px;
      padding: 14px;
    }}
    .graph-card-title {{ font-weight: 700; color: white; }}
    .graph-card-chip {{
      display: inline-flex;
      margin-top: 8px;
      padding: 5px 9px;
      border-radius: 999px;
      background: rgba(196,160,82,0.14);
      color: #e5c98c;
      font-size: 11px;
      font-weight: 700;
    }}
    .graph-card-body {{
      margin-top: 10px;
      font-size: 13px;
      color: #d8e2ed;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 14px;
      font-size: 13px;
    }}
    th, td {{
      text-align: left;
      padding: 12px 10px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .ledger {{
      margin-top: 20px;
    }}
    @media print {{
      body {{ background: white; color: black; }}
      .page {{ max-width: none; padding: 0; }}
      .hero, .card {{ box-shadow: none; break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="eyebrow">Helios Intelligence Brief</div>
      <h1>{escape(payload['vendor_name'])}</h1>
      <div class="hero-meta">
        {_html_badge(recommendation['label'], posture)}
        <span>{escape(payload['country'])}</span>
        <span>{escape(payload['program_label'])}</span>
        <span>{escape(payload['generated_at'])}</span>
      </div>
      <div class="summary">{escape(payload['summary_line'])}</div>
      <div class="identity-row">{identity_html}</div>
    </section>

    <section class="grid">
      <article class="card">
        <h2>Axiom Assessment</h2>
        <div class="support-line">{escape(payload['axiom']['confidence'])}</div>
        <div class="axiom-summary">{escape(payload['axiom']['summary'])}</div>
        <div class="subtle">{escape(payload['axiom']['support'])}</div>
        <div class="split">
          <div>
            <h2 style="font-size:16px;">What holds</h2>
            <ul>{_html_list(payload['what_holds'], 'No durable hold is ready to state cleanly yet.')}</ul>
          </div>
          <div>
            <h2 style="font-size:16px;">What needs to be closed</h2>
            <ul>{_html_list(payload['gaps'], 'No material open gap is currently called out.')}</ul>
          </div>
        </div>
      </article>

      <article class="card">
        <h2>Graph Read</h2>
        <div class="support-line">The graph is treated as the reasoning spine, not a sidebar.</div>
        <div class="metrics">
          <div class="metric"><div class="metric-label">Relationships</div><div class="metric-value">{graph_read['relationship_count']}</div></div>
          <div class="metric"><div class="metric-label">Entities</div><div class="metric-value">{graph_read['entity_count']}</div></div>
          <div class="metric"><div class="metric-label">Claim Coverage</div><div class="metric-value">{graph_read['claim_coverage_pct']}%</div></div>
          <div class="metric"><div class="metric-label">Edge Families</div><div class="metric-value">{graph_read['edge_family_count']}</div></div>
        </div>
        <div class="graph-grid">{graph_cards}</div>
      </article>
    </section>

    <section class="card ledger">
      <h2>Evidence Ledger</h2>
      <div class="support-line">Low-signal absence noise is stripped. Only material surviving findings are shown here.</div>
      <table>
        <thead>
          <tr>
            <th>Finding</th>
            <th>Source</th>
            <th>Severity</th>
            <th>Why it matters</th>
          </tr>
        </thead>
        <tbody>
          {finding_rows}
        </tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""


def generate_html_brief(vendor_id: str, user_id: str = "", hydrate_ai: bool = False) -> str:
    from dossier import build_dossier_context

    context = build_dossier_context(vendor_id, user_id=user_id, hydrate_ai=hydrate_ai)
    if not context:
        return "<p>Vendor not found</p>"
    payload = _distill_context(context)
    return _render_html_brief(payload)


def generate_pdf_brief(vendor_id: str, user_id: str = "", hydrate_ai: bool = False) -> bytes:
    from dossier import build_dossier_context

    context = build_dossier_context(vendor_id, user_id=user_id, hydrate_ai=hydrate_ai)
    if not context:
        raise ValueError(f"Vendor {vendor_id} not found")
    payload = _distill_context(context)
    recommendation = payload["recommendation"]
    accent = HexColor(_COLOR_BY_POSTURE[recommendation["posture"]])

    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("BriefTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=HexColor("#0A1628"))
    heading = ParagraphStyle("BriefHeading", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=HexColor("#0A1628"), spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("BriefBody", parent=styles["BodyText"], fontSize=9.5, leading=13, textColor=HexColor("#334155"))
    muted = ParagraphStyle("BriefMuted", parent=body, fontSize=8, leading=11, textColor=HexColor("#64748B"))
    bullet = ParagraphStyle("BriefBullet", parent=body, leftIndent=14, bulletIndent=0, spaceAfter=4)

    story: list[Any] = []
    story.append(Paragraph("HELIOS", ParagraphStyle("Brand", parent=muted, fontName="Helvetica-Bold", textColor=HexColor("#C4A052"), letterSpacing=1.2)))
    story.append(Paragraph("Intelligence Brief", ParagraphStyle("SubBrand", parent=muted, fontName="Helvetica-Bold", textColor=HexColor("#475569"))))
    story.append(Spacer(1, 0.12 * inch))
    story.append(Paragraph(payload["vendor_name"], title))
    hero = Table(
        [[
            Paragraph(
                f"<b>{recommendation['label']}</b><br/>{escape(payload['summary_line'])}",
                ParagraphStyle("HeroBody", parent=body, textColor=colors.white, fontSize=10.5, leading=14),
            )
        ]],
        colWidths=[7.3 * inch],
    )
    hero.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#0A1628")),
        ("BOX", (0, 0), (-1, -1), 1, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(Spacer(1, 0.08 * inch))
    story.append(hero)
    story.append(Spacer(1, 0.08 * inch))
    meta = f"{payload['country']} | {payload['program_label']} | Generated {payload['generated_at']}"
    story.append(Paragraph(meta, muted))
    top_risk_signal = payload["findings"][0]["title"] if payload["findings"] else recommendation["summary"]
    immediate_next_move = payload["axiom"]["actions"][0] if payload["axiom"]["actions"] else payload["gaps"][0] if payload["gaps"] else recommendation["summary"]
    evidence_snapshot = (
        f"{payload['graph_read']['relationship_count']} relationships, "
        f"{payload['graph_read']['entity_count']} entities, "
        f"{len(payload['findings'])} curated findings."
    )
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph(f"Top risk signal: {top_risk_signal}", body))
    story.append(Paragraph(f"Immediate next move: {immediate_next_move}", body))
    story.append(Paragraph(f"Evidence snapshot: {evidence_snapshot}", muted))

    if payload["identity_lines"]:
        story.append(Spacer(1, 0.08 * inch))
        story.append(Paragraph("Identity anchors: " + " | ".join(payload["identity_lines"]), body))

    story.append(Spacer(1, 0.14 * inch))
    story.append(Paragraph("Axiom Assessment", heading))
    story.append(Paragraph(payload["axiom"]["summary"], body))
    story.append(Paragraph(payload["axiom"]["support"], body))
    story.append(Paragraph(f"Confidence read: {payload['axiom']['confidence']}", muted))

    if payload["what_holds"]:
        story.append(Paragraph("What holds", heading))
        for item in payload["what_holds"]:
            story.append(Paragraph(item, bullet, bulletText="•"))

    if payload["gaps"]:
        story.append(Paragraph("What needs to be closed", heading))
        for item in payload["gaps"]:
            story.append(Paragraph(item, bullet, bulletText="•"))

    story.append(Paragraph("Graph Read", heading))
    graph_metrics = Table(
        [[
            Paragraph(f"<b>Relationships</b><br/>{payload['graph_read']['relationship_count']}", body),
            Paragraph(f"<b>Entities</b><br/>{payload['graph_read']['entity_count']}", body),
            Paragraph(f"<b>Claim coverage</b><br/>{payload['graph_read']['claim_coverage_pct']}%", body),
            Paragraph(f"<b>Edge families</b><br/>{payload['graph_read']['edge_family_count']}", body),
        ]],
        colWidths=[1.78 * inch, 1.78 * inch, 1.78 * inch, 1.78 * inch],
    )
    graph_metrics.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#D8E0EA")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(graph_metrics)
    story.append(Spacer(1, 0.08 * inch))
    for rel in payload["graph_read"]["top_relationships"]:
        story.append(Paragraph(f"<b>{rel['source']} → {rel['target']}</b> | {rel['rel_type'].title()} | {rel['corroboration']} record{'s' if rel['corroboration'] != 1 else ''}", body))
        story.append(Paragraph(rel["evidence"] or "No narrative evidence summary is attached yet.", muted))

    story.append(Paragraph("Evidence Ledger", heading))
    ledger_rows = [["Finding", "Source", "Severity", "Why it matters"]]
    for item in payload["findings"][:8]:
        ledger_rows.append([
            item["title"],
            item["source"].replace("_", " ").title(),
            item["severity"].upper(),
            item["detail"],
        ])
    if len(ledger_rows) == 1:
        ledger_rows.append(["No material findings survived curation.", "", "", ""])
    ledger = Table(ledger_rows, colWidths=[1.85 * inch, 1.35 * inch, 0.9 * inch, 3.35 * inch])
    ledger.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#0A1628")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#D8E0EA")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#FFFFFF"), HexColor("#F8FAFC")]),
    ]))
    story.append(ledger)

    doc.build(story)
    return pdf_buffer.getvalue()
