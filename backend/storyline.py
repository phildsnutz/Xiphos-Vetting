"""Deterministic top-of-case storyline cards for Helios."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import re


_MAX_TITLE_LEN = 96
_MAX_BODY_LEN = 220
_WEAK_FINDING_PATTERNS = (
    "no match",
    "no adverse",
    "no sanctions",
    "no debarment",
    "not found",
    "unable to verify",
    "api unavailable",
    "not configured",
)
_PLACEHOLDER_FINDING_TITLE = "OSINT finding"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any, max_len: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "item"


def _tier_band(tier: str) -> str:
    normalized = str(tier or "").upper()
    if normalized.startswith("TIER_1"):
        return "critical"
    if normalized.startswith("TIER_2"):
        return "elevated"
    if normalized.startswith("TIER_3"):
        return "conditional"
    return "clear"


def _severity_from_network(level: str, score: float) -> str:
    normalized = str(level or "").lower()
    if normalized == "critical":
        return "critical"
    if normalized == "high":
        return "high"
    if normalized == "medium":
        return "medium"
    if score > 0:
        return "low"
    return "positive"


def _parse_created_at(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(candidate.replace(" ", "T"))
        except ValueError:
            return None


def _next_review_date(created_at: str | None, days: int) -> str | None:
    base = _parse_created_at(created_at)
    if not base:
        return None
    return (base + timedelta(days=days)).date().isoformat()


def _first_material_finding(report: dict | None) -> dict[str, Any] | None:
    if not isinstance(report, dict):
        return None
    findings = report.get("findings") or []
    prioritized = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    sorted_findings = sorted(
        [finding for finding in findings if isinstance(finding, dict)],
        key=lambda finding: (
            prioritized.get(str(finding.get("severity", "info")).lower(), 5),
            -float(finding.get("confidence") or 0.0),
        ),
    )
    for finding in sorted_findings:
        title = str(finding.get("title", "") or "")
        detail = str(finding.get("detail", "") or "")
        lowered = f"{title} {detail}".lower()
        if any(token in lowered for token in _WEAK_FINDING_PATTERNS):
            continue
        return finding
    return None


def _first_active_event(events: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    if not events:
        return None
    sorted_events = sorted(
        [event for event in events if isinstance(event, dict)],
        key=lambda event: (
            event.get("status") != "active",
            -float(event.get("confidence") or 0.0),
        ),
    )
    return sorted_events[0] if sorted_events else None


def _top_intel_item(intel_summary: dict | None) -> dict[str, Any] | None:
    if not isinstance(intel_summary, dict):
        return None
    summary = intel_summary.get("summary") or {}
    items = summary.get("items") or []
    if not items:
        return None
    sorted_items = sorted(
        [item for item in items if isinstance(item, dict)],
        key=lambda item: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(str(item.get("severity", "medium")).lower(), 5),
            -float(item.get("confidence") or 0.0),
        ),
    )
    return sorted_items[0] if sorted_items else None


def _action_recommendations(cal: dict[str, Any], created_at: str | None) -> list[str]:
    band = _tier_band(cal.get("calibrated_tier", ""))
    if band == "critical":
        return [
            "Stop procurement and escalate to compliance.",
            "Document the hard-stop trigger in the case file.",
        ]

    if band == "elevated":
        factor_names = [
            str(item.get("factor", "") or "").lower()
            for item in (cal.get("contributions") or [])
        ]
        factor_names = factor_names[:6]
        recommendations: list[str] = []

        if any("ownership" in factor for factor in factor_names):
            recommendations.append("Request beneficial ownership documentation and confirm the control chain.")
        if any("data" in factor or "quality" in factor for factor in factor_names):
            recommendations.append("Request CAGE, LEI, and DUNS identifiers to improve entity confidence.")
        if any("geograph" in factor or "location" in factor for factor in factor_names):
            recommendations.append("Verify end-use and transshipment controls before approval.")
        if any("sanction" in factor for factor in factor_names):
            recommendations.append("Run a manual sanctions review against the primary screened lists.")
        if any("executive" in factor or "principal" in factor for factor in factor_names):
            recommendations.append("Run enhanced background checks on key principals.")
        if not recommendations:
            recommendations.append("Complete enhanced diligence before approving this vendor.")
        return recommendations[:2]

    if band == "conditional":
        review_date = _next_review_date(created_at, 180)
        recommendations = [
            "Approve for standard procurement with routine monitoring.",
            "Monitor for adverse media alerts and risk changes.",
        ]
        if review_date:
            recommendations.insert(1, f"Schedule re-screening on {review_date}.")
        else:
            recommendations.insert(1, "Schedule re-screening in 6 months.")
        return recommendations[:2]

    review_date = _next_review_date(created_at, 365)
    recommendations = ["Proceed with standard procurement workflow."]
    if review_date:
        recommendations.append(f"Schedule annual re-screening on {review_date}.")
    else:
        recommendations.append("Schedule annual re-screening.")
    return recommendations


def _add_card(cards: list[dict[str, Any]], seen: set[tuple[str, str]], card: dict[str, Any]) -> None:
    title = _clean_text(card.get("title", ""), _MAX_TITLE_LEN)
    body = _clean_text(card.get("body", ""), _MAX_BODY_LEN)
    if not title or not body:
        return

    source_refs = [ref for ref in (card.get("source_refs") or []) if isinstance(ref, dict)]
    primary_ref = source_refs[0] if source_refs else None
    if primary_ref and str(card.get("type")) in {"trigger", "reach"}:
        primary_key = f"{primary_ref.get('kind', '')}:{primary_ref.get('id', '')}"
        for existing in cards:
            existing_refs = [ref for ref in (existing.get("source_refs") or []) if isinstance(ref, dict)]
            existing_primary = existing_refs[0] if existing_refs else None
            if not existing_primary:
                continue
            existing_key = f"{existing_primary.get('kind', '')}:{existing_primary.get('id', '')}"
            if existing_key == primary_key and str(existing.get("type")) in {"trigger", "reach"}:
                return

    key = (str(card.get("type", "")), title.lower())
    if key in seen:
        return
    seen.add(key)

    card["title"] = title
    card["body"] = body
    card["confidence"] = max(0.0, min(float(card.get("confidence") or 0.0), 1.0))
    card["source_refs"] = source_refs
    cards.append(card)


def build_case_storyline(
    case_id: str,
    vendor: dict[str, Any],
    score: dict[str, Any] | None,
    *,
    report: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    intel_summary: dict[str, Any] | None = None,
    network_risk: dict[str, Any] | None = None,
    foci_summary: dict[str, Any] | None = None,
    cyber_summary: dict[str, Any] | None = None,
    export_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(score, dict):
        return None

    cal = score.get("calibrated") or {}
    if not isinstance(cal, dict):
        return None

    tier = str(cal.get("calibrated_tier", "") or "")
    band = _tier_band(tier)
    stops = [item for item in (cal.get("hard_stop_decisions") or []) if isinstance(item, dict)]
    flags = [item for item in (cal.get("soft_flags") or []) if isinstance(item, dict)]
    report = report if isinstance(report, dict) else None
    events = [event for event in (events or []) if isinstance(event, dict)]
    intel_item = _top_intel_item(intel_summary)
    active_event = _first_active_event(events)
    material_finding = _first_material_finding(report)
    cards: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    if stops:
        stop = stops[0]
        _add_card(
            cards,
            seen,
            {
                "id": f"trigger-{_slug(stop.get('trigger', 'hard-stop'))}",
                "type": "trigger",
                "title": stop.get("trigger") or "Hard-stop condition detected",
                "body": stop.get("explanation") or "A hard-stop condition prevents procurement until resolved.",
                "severity": "critical",
                "confidence": stop.get("confidence") or 0.9,
                "cta_label": "Open evidence",
                "cta_target": {"kind": "evidence_tab", "tab": "findings"},
                "source_refs": [{"kind": "hard_stop", "id": "hard-stop-0"}],
            },
        )

        impact_title = "Compliance block in effect"
        if str(cal.get("regulatory_status", "")).upper() == "NON_COMPLIANT":
            impact_title = "Federal procurement blocked"
        _add_card(
            cards,
            seen,
            {
                "id": "impact-hard-stop",
                "type": "impact",
                "title": impact_title,
                "body": "This case should not proceed until the blocking condition is cleared or formally overridden.",
                "severity": "critical",
                "confidence": max(float(stop.get("confidence") or 0.9), 0.9),
                "cta_label": "View model reasoning",
                "cta_target": {"kind": "deep_analysis", "section": "model"},
                "source_refs": [{"kind": "score", "id": tier or "tier-critical"}],
            },
        )
    elif flags:
        flag = flags[0]
        _add_card(
            cards,
            seen,
            {
                "id": f"trigger-{_slug(flag.get('trigger', 'flag'))}",
                "type": "trigger",
                "title": flag.get("trigger") or "Review trigger detected",
                "body": flag.get("explanation") or "A review flag was raised for this vendor.",
                "severity": "high" if band == "elevated" else "medium",
                "confidence": flag.get("confidence") or 0.75,
                "cta_label": "Open evidence",
                "cta_target": {"kind": "evidence_tab", "tab": "findings"},
                "source_refs": [{"kind": "flag", "id": "flag-0"}],
            },
        )
    elif active_event:
        _add_card(
            cards,
            seen,
            {
                "id": f"trigger-{_slug(active_event.get('event_type', 'event'))}",
                "type": "trigger",
                "title": active_event.get("title") or str(active_event.get("event_type", "Normalized event")).replace("_", " ").title(),
                "body": active_event.get("assessment") or "A normalized event from the current evidence set requires attention.",
                "severity": "high" if band in {"critical", "elevated"} else "medium",
                "confidence": active_event.get("confidence") or 0.7,
                "cta_label": "Open events",
                "cta_target": {"kind": "evidence_tab", "tab": "events"},
                "source_refs": [{"kind": "event", "id": f"{active_event.get('finding_id', 'event')}-{active_event.get('event_type', 'event')}"}],
            },
        )
    elif material_finding and band != "clear":
        _add_card(
            cards,
            seen,
            {
                "id": f"trigger-{_slug(material_finding.get('title', _PLACEHOLDER_FINDING_TITLE))}",
                "type": "trigger",
                "title": material_finding.get("title") or _PLACEHOLDER_FINDING_TITLE,
                "body": material_finding.get("detail") or material_finding.get("title") or "A material OSINT finding requires review.",
                "severity": str(material_finding.get("severity", "medium")).lower(),
                "confidence": material_finding.get("confidence") or 0.65,
                "cta_label": "View source finding",
                "cta_target": {"kind": "evidence_tab", "tab": "findings", "finding_id": material_finding.get("finding_id")},
                "source_refs": [{"kind": "finding", "id": material_finding.get("finding_id") or "finding-0"}],
            },
        )

    if band == "elevated":
        _add_card(
            cards,
            seen,
            {
                "id": "impact-enhanced-review",
                "type": "impact",
                "title": "Enhanced diligence required before approval",
                "body": "The current evidence set justifies a deeper review before this vendor is cleared to proceed.",
                "severity": "high",
                "confidence": 0.82,
                "cta_label": "View model reasoning",
                "cta_target": {"kind": "deep_analysis", "section": "model"},
                "source_refs": [{"kind": "score", "id": tier or "tier-elevated"}],
            },
        )
    elif band == "conditional":
        _add_card(
            cards,
            seen,
            {
                "id": "impact-standard-monitoring",
                "type": "impact",
                "title": "Standard processing is possible with monitoring",
                "body": "The vendor appears workable, but Helios recommends periodic review and alert monitoring before the case is considered routine.",
                "severity": "medium",
                "confidence": 0.76,
                "cta_label": "View model reasoning",
                "cta_target": {"kind": "deep_analysis", "section": "model"},
                "source_refs": [{"kind": "score", "id": tier or "tier-conditional"}],
            },
        )

    if isinstance(foci_summary, dict):
        foreign_interest = bool(foci_summary.get("foreign_interest_indicated"))
        mitigation_present = bool(foci_summary.get("mitigation_present"))
        owner_display = str(
            foci_summary.get("foreign_owner")
            or foci_summary.get("foreign_country")
            or "the foreign-linked counterparty"
        )
        pct_display = str(foci_summary.get("foreign_ownership_pct_display") or "Not stated")
        mitigation_display = str(foci_summary.get("mitigation_display") or "mitigation not stated")
        narrative = str(foci_summary.get("narrative") or "").strip()

        if foreign_interest:
            card_type = "offset" if band == "clear" and mitigation_present else "reach"
            severity = "positive" if band == "clear" and mitigation_present else "high" if not mitigation_present else "medium"
            title = (
                "Customer FOCI evidence shows disclosed foreign ownership with mitigation"
                if mitigation_present
                else "Customer FOCI evidence confirms foreign ownership requiring adjudication"
            )
            body = narrative or (
                f"Customer ownership records indicate {pct_display} foreign ownership tied to {owner_display}, "
                f"with {mitigation_display} noted."
                if mitigation_present
                else f"Customer ownership records indicate {pct_display} foreign ownership tied to {owner_display}; "
                "the control chain should be adjudicated before approval."
            )
            _add_card(
                cards,
                seen,
                {
                    "id": "reach-foci-evidence",
                    "type": card_type,
                    "title": title,
                    "body": body,
                    "severity": severity,
                    "confidence": 0.84,
                    "cta_label": "Open evidence",
                    "cta_target": {"kind": "evidence_tab", "tab": "findings"},
                    "source_refs": [{"kind": "customer_artifact", "id": str(foci_summary.get("artifact_type") or "foci_artifact")}],
                },
            )
        elif band == "clear":
            _add_card(
                cards,
                seen,
                {
                    "id": "offset-foci-evidence",
                    "type": "offset",
                    "title": "Customer ownership evidence supports a resolved control chain",
                    "body": narrative or "Customer ownership records do not indicate explicit foreign ownership or control concerns in the attached material.",
                    "severity": "positive",
                    "confidence": 0.8,
                    "cta_label": "Open evidence",
                    "cta_target": {"kind": "evidence_tab", "tab": "findings"},
                    "source_refs": [{"kind": "customer_artifact", "id": str(foci_summary.get("artifact_type") or "foci_artifact")}],
                },
            )

    if isinstance(cyber_summary, dict):
        profile = str(vendor.get("profile", "") or "")
        required_level = 2 if profile == "defense_acquisition" else 0
        current_level = int(cyber_summary.get("current_cmmc_level") or 0)
        poam_active = bool(cyber_summary.get("poam_active"))
        open_poam_items = int(cyber_summary.get("open_poam_items") or 0)
        critical_cves = int(cyber_summary.get("critical_cve_count") or 0)
        kev_count = int(cyber_summary.get("kev_flagged_cve_count") or 0)
        assessment_date = str(cyber_summary.get("assessment_date") or "").strip()
        assessment_status = str(cyber_summary.get("assessment_status") or "").strip()

        if current_level > 0 or poam_active or critical_cves > 0 or kev_count > 0:
            if current_level > 0 and required_level > 0 and current_level < required_level:
                body = (
                    f"Customer SPRS evidence shows current CMMC Level {current_level} against a likely Level {required_level} requirement"
                    + (" with an active POA&M." if poam_active else ".")
                )
                if critical_cves or kev_count:
                    body += (
                        f" NVD context adds {critical_cves} critical CVE"
                        f"{'s' if critical_cves != 1 else ''}"
                        f" and {kev_count} KEV-linked issue{'s' if kev_count != 1 else ''}."
                    )
                if assessment_date:
                    body += f" Latest assessment: {assessment_date}."
                _add_card(
                    cards,
                    seen,
                    {
                        "id": "reach-cmmc-gap",
                        "type": "reach",
                        "title": "Customer cyber evidence shows a CMMC readiness gap",
                        "body": body,
                        "severity": "high" if current_level <= 1 else "medium",
                        "confidence": 0.83,
                        "cta_label": "Open evidence",
                        "cta_target": {"kind": "evidence_tab", "tab": "findings"},
                        "source_refs": [{"kind": "customer_artifact", "id": str(cyber_summary.get("sprs_artifact_id") or "sprs_import")}],
                    },
                )
            elif band == "clear" and current_level >= 2 and not poam_active and critical_cves == 0 and kev_count == 0:
                body = (
                    f"Customer cyber evidence supports a stronger trust posture with CMMC Level {current_level}"
                    + (f" confirmed on {assessment_date}." if assessment_date else " confirmed.")
                )
                if assessment_status:
                    body += f" Assessment status: {assessment_status}."
                _add_card(
                    cards,
                    seen,
                    {
                        "id": "offset-cmmc-ready",
                        "type": "offset",
                        "title": "Customer cyber evidence supports supplier readiness",
                        "body": body,
                        "severity": "positive",
                        "confidence": 0.8,
                        "cta_label": "Open evidence",
                        "cta_target": {"kind": "evidence_tab", "tab": "findings"},
                        "source_refs": [{"kind": "customer_artifact", "id": str(cyber_summary.get("sprs_artifact_id") or "sprs_import")}],
                    },
                )
            elif poam_active or critical_cves > 0 or kev_count > 0:
                body = "Customer cyber evidence indicates unresolved remediation pressure"
                details = []
                if open_poam_items > 0:
                    details.append(f"{open_poam_items} open POA&M item{'s' if open_poam_items != 1 else ''}")
                elif poam_active:
                    details.append("an active POA&M")
                if critical_cves > 0:
                    details.append(f"{critical_cves} critical CVE{'s' if critical_cves != 1 else ''}")
                if kev_count > 0:
                    details.append(f"{kev_count} KEV-linked issue{'s' if kev_count != 1 else ''}")
                if details:
                    body = f"{body}: " + ", ".join(details) + "."
                _add_card(
                    cards,
                    seen,
                    {
                        "id": "reach-cyber-remediation",
                        "type": "reach",
                        "title": "Customer cyber evidence indicates unresolved remediation pressure",
                        "body": body,
                        "severity": "medium",
                        "confidence": 0.78,
                        "cta_label": "Open evidence",
                        "cta_target": {"kind": "evidence_tab", "tab": "findings"},
                        "source_refs": [{"kind": "customer_artifact", "id": str(cyber_summary.get("oscal_artifact_id") or cyber_summary.get("nvd_artifact_id") or "cyber_evidence")}],
                    },
                )

    if isinstance(export_summary, dict):
        posture = str(export_summary.get("posture") or "")
        narrative = str(export_summary.get("narrative") or "").strip()
        confidence = float(export_summary.get("confidence") or 0.0)
        artifact_id = str(export_summary.get("artifact_type") or export_summary.get("artifact_id") or "export_evidence")
        request_type = str(export_summary.get("request_type") or "export request").replace("_", " ")

        if posture == "likely_prohibited":
            _add_card(
                cards,
                seen,
                {
                    "id": "trigger-export-prohibited",
                    "type": "trigger",
                    "title": "Authorization posture indicates likely prohibition",
                    "body": narrative or f"Helios rules guidance indicates this {request_type} is likely prohibited and should not proceed without formal escalation.",
                    "severity": "critical",
                    "confidence": confidence or 0.9,
                    "cta_label": "Open evidence",
                    "cta_target": {"kind": "evidence_tab", "tab": "findings"},
                    "source_refs": [
                        {"kind": "export_guidance", "id": "bis_rules_engine"},
                        {"kind": "customer_artifact", "id": artifact_id},
                    ],
                },
            )
        elif posture in {"likely_license_required", "escalate", "insufficient_confidence"}:
            _add_card(
                cards,
                seen,
                {
                    "id": "reach-export-review",
                    "type": "reach",
                    "title": "Authorization posture requires formal export review",
                    "body": narrative or f"Helios rules guidance indicates this {request_type} requires formal export review before release, transfer, or access approval.",
                    "severity": "high" if posture in {"likely_license_required", "escalate"} else "medium",
                    "confidence": confidence or 0.76,
                    "cta_label": "Open evidence",
                    "cta_target": {"kind": "evidence_tab", "tab": "findings"},
                    "source_refs": [
                        {"kind": "export_guidance", "id": "bis_rules_engine"},
                        {"kind": "customer_artifact", "id": artifact_id},
                    ],
                },
            )
        elif band == "clear" and posture in {"likely_exception_or_exemption", "likely_nlr"}:
            _add_card(
                cards,
                seen,
                {
                    "id": "offset-export-lower-friction",
                    "type": "offset",
                    "title": "Authorization posture suggests a lower-friction path",
                    "body": narrative or f"Helios rules guidance suggests a lower-friction authorization path for this {request_type}, subject to final export-control review.",
                    "severity": "positive",
                    "confidence": confidence or 0.72,
                    "cta_label": "Open evidence",
                    "cta_target": {"kind": "evidence_tab", "tab": "findings"},
                    "source_refs": [
                        {"kind": "export_guidance", "id": "bis_rules_engine"},
                        {"kind": "customer_artifact", "id": artifact_id},
                    ],
                },
            )

    if network_risk and float(network_risk.get("score") or 0.0) > 0:
        score_value = float(network_risk.get("score") or 0.0)
        neighbor_count = int(network_risk.get("neighbor_count") or 0)
        high_risk_neighbors = int(network_risk.get("high_risk_neighbors") or 0)
        body = (
            f"The connected network adds +{score_value:.1f} risk points"
            + (f" across {neighbor_count} linked entities" if neighbor_count else "")
            + (f", including {high_risk_neighbors} high-risk neighbors." if high_risk_neighbors else ".")
        )
        _add_card(
            cards,
            seen,
            {
                "id": "reach-network-risk",
                "type": "reach",
                "title": "Connected entity exposure raises review priority",
                "body": body,
                "severity": _severity_from_network(network_risk.get("level", "none"), score_value),
                "confidence": 0.74,
                "cta_label": "Open graph",
                "cta_target": {"kind": "graph_focus", "depth": 3},
                "source_refs": [{"kind": "network_risk", "id": case_id}],
            },
        )
    elif active_event:
        event_count = len(events)
        connectors = sorted({event.get("connector", "") for event in events if event.get("connector")})
        connector_text = f" across {len(connectors)} evidence sources" if connectors else ""
        _add_card(
            cards,
            seen,
            {
                "id": "reach-events",
                "type": "reach",
                "title": f"{event_count} normalized event{'s' if event_count != 1 else ''} require context",
                "body": (active_event.get("assessment") or "The current findings normalize into reusable events.")
                + connector_text,
                "severity": "medium" if band != "clear" else "low",
                "confidence": active_event.get("confidence") or 0.7,
                "cta_label": "Open events",
                "cta_target": {"kind": "evidence_tab", "tab": "events"},
                "source_refs": [{"kind": "event", "id": f"{active_event.get('finding_id', 'event')}-{active_event.get('event_type', 'event')}"}],
            },
        )
    elif intel_item:
        cited_ids = list(intel_item.get("source_finding_ids") or [])
        connectors = list(intel_item.get("connectors") or [])
        connector_text = f" across {len(connectors)} corroborating sources" if connectors else ""
        _add_card(
            cards,
            seen,
            {
                "id": "reach-intel-summary",
                "type": "reach",
                "title": intel_item.get("title") or "Cross-source intelligence summary available",
                "body": (intel_item.get("assessment") or "Helios synthesized multiple findings into one analyst-facing summary.") + connector_text,
                "severity": str(intel_item.get("severity", "medium")).lower(),
                "confidence": intel_item.get("confidence") or 0.72,
                "cta_label": "Open intel summary",
                "cta_target": {"kind": "evidence_tab", "tab": "intel", "finding_id": cited_ids[0] if cited_ids else None},
                "source_refs": [{"kind": "finding", "id": finding_id} for finding_id in cited_ids] or [{"kind": "intel_summary", "id": "item-0"}],
            },
        )
    elif band == "clear" and report:
        summary = report.get("summary") or {}
        checked = int(summary.get("connectors_run") or 0)
        with_data = int(summary.get("connectors_with_data") or 0)
        if checked > 0:
            _add_card(
                cards,
                seen,
                {
                    "id": "reach-coverage",
                    "type": "reach",
                    "title": f"Coverage across {checked} screened sources",
                    "body": f"Helios checked {checked} sources, with {with_data} returning data and no material blockers surfaced in the current run.",
                    "severity": "low",
                    "confidence": 0.68,
                    "cta_label": "Open evidence",
                    "cta_target": {"kind": "evidence_tab", "tab": "findings"},
                    "source_refs": [{"kind": "report", "id": report.get("report_hash") or case_id}],
                },
            )

    if band == "clear":
        offset_title = "Regulatory gates pass cleanly" if str(cal.get("regulatory_status", "")).upper() == "COMPLIANT" else "No material blockers detected"
        offset_body = (
            "Helios did not detect any hard-stop conditions or advisory flags in the current scoring pass."
            if not flags and not stops
            else "The current case state remains clear despite minor background signals."
        )
        if cal.get("is_dod_eligible") is True and cal.get("is_dod_qualified") is True:
            offset_body = "The case remains eligible and qualified for DoD-style review with no blocking conditions detected."
        _add_card(
            cards,
            seen,
            {
                "id": "offset-clear",
                "type": "offset",
                "title": offset_title,
                "body": offset_body,
                "severity": "positive",
                "confidence": max(float(cal.get("interval", {}).get("coverage") or 0.0), 0.7),
                "cta_label": "View model reasoning",
                "cta_target": {"kind": "deep_analysis", "section": "model"},
                "source_refs": [{"kind": "score", "id": tier or "tier-clear"}],
            },
        )

    for idx, recommendation in enumerate(_action_recommendations(cal, vendor.get("created_at"))):
        if idx > 0 and band == "clear":
            # Keep clear cases compact.
            break
        _add_card(
            cards,
            seen,
            {
                "id": f"action-{_slug(recommendation)}",
                "type": "action",
                "title": recommendation,
                "body": (
                    "This is the clearest next operational step for the current case state."
                    if band in {"critical", "elevated"}
                    else "This keeps the case moving while preserving routine monitoring discipline."
                ),
                "severity": "critical" if band == "critical" else "medium" if band == "conditional" else "low" if band == "clear" else "high",
                "confidence": 0.78,
                "cta_label": "Open actions",
                "cta_target": {"kind": "action_panel"},
                "source_refs": [{"kind": "score", "id": tier or f"tier-{band}"}],
            },
        )
        break

    ordering = {
        "critical": {"trigger": 0, "impact": 1, "action": 2, "reach": 3, "offset": 4},
        "elevated": {"trigger": 0, "impact": 1, "reach": 2, "action": 3, "offset": 4},
        "conditional": {"trigger": 0, "impact": 1, "reach": 2, "action": 3, "offset": 4},
        "clear": {"offset": 0, "action": 1, "reach": 2, "impact": 3, "trigger": 4},
    }
    ordered_cards = sorted(cards, key=lambda card: ordering[band].get(str(card.get("type", "")), 99))
    max_cards = {"critical": 4, "elevated": 5, "conditional": 5, "clear": 3}[band]
    ordered = ordered_cards[:max_cards]
    if not ordered:
        return None

    for index, card in enumerate(ordered, start=1):
        card["rank"] = index

    return {
        "version": "risk-storyline-v1",
        "case_id": case_id,
        "generated_at": _utc_now_iso(),
        "cards": ordered,
    }
