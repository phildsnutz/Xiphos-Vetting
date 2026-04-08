from __future__ import annotations

from typing import Any


def _clean(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _join_sentences(*parts: Any) -> str:
    cleaned: list[str] = []
    for part in parts:
        text = _clean(part)
        if not text:
            continue
        cleaned.append(text.rstrip(". "))
    if not cleaned:
        return ""
    return ". ".join(cleaned) + "."


def _summarize(text: str, limit: int = 220) -> str:
    value = " ".join(_clean(text).split())
    if len(value) <= limit:
        return value
    clipped = value[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return clipped + "..."


def _label_for_stance(value: str) -> str:
    normalized = _clean(value).lower()
    if normalized == "approve":
        return "Why proceed"
    if normalized == "watch":
        return "Why hold"
    if normalized == "deny":
        return "Why stop"
    return "Competing case"


def _is_weak_match_signal(signal: dict[str, Any] | None) -> bool:
    item = signal if isinstance(signal, dict) else {}
    title = _clean(item.get("title")).lower()
    read = _clean(item.get("read")).lower()
    source = _clean(item.get("source")).lower()
    markers = ("offshore leak proximity", "name or entity-proximity", "requires disambiguation")
    if source == "icij offshore":
        return True
    return any(marker in title or marker in read for marker in markers)


def _is_generic_line(value: str) -> bool:
    lowered = _clean(value).lower()
    generic_markers = (
        "proceed with standard procurement workflow",
        "routine monitoring discipline",
        "standard processing is possible",
        "the available evidence does not currently justify",
        "the current evidence does not yet support",
        "no material findings have been established",
    )
    return any(marker in lowered for marker in generic_markers)


def _build_graph_read(graph_summary: dict[str, Any] | None) -> list[str]:
    if not isinstance(graph_summary, dict):
        return []
    intelligence = graph_summary.get("intelligence") if isinstance(graph_summary.get("intelligence"), dict) else {}
    lines: list[str] = []
    missing_families = [
        str(item).replace("_", " ")
        for item in (intelligence.get("missing_required_edge_families") or [])
        if str(item).strip()
    ]
    claim_coverage_pct = round(float(intelligence.get("claim_coverage_pct") or 0.0) * 100)
    public_only_edges = int(intelligence.get("third_party_public_only_edge_count") or 0)
    official_edges = int(intelligence.get("official_or_modeled_edge_count") or 0)
    contradicted_edges = int(intelligence.get("contradicted_edge_count") or 0)
    stale_edges = int(intelligence.get("stale_edge_count") or 0)
    thin_graph = bool(intelligence.get("thin_graph"))
    thin_control_paths = bool(intelligence.get("thin_control_paths"))

    if thin_graph:
        lines.append("The network picture is still structurally thin, so silence should not be mistaken for comfort.")
    if thin_control_paths:
        lines.append("Control-path coverage is still too thin to treat ownership or hidden-control questions as settled.")
    if missing_families:
        lines.append(
            "Required relationship families are still missing: " + ", ".join(missing_families[:3]) + "."
        )
    if contradicted_edges > 0:
        lines.append(
            f"{contradicted_edges} contradicted graph claim{'s' if contradicted_edges != 1 else ''} still lower confidence in the network read."
        )
    if stale_edges > 0:
        lines.append(
            f"{stale_edges} stale graph edge{'s' if stale_edges != 1 else ''} weaken the freshness of the dependency picture."
        )
    if public_only_edges > 0 and official_edges == 0:
        lines.append(
            "The network picture is still dominated by public-only evidence rather than official or modeled corroboration."
        )
    if claim_coverage_pct > 0 and not lines:
        lines.append(f"Network claims are {claim_coverage_pct}% claim-backed, which is enough to treat the graph as directional rather than decorative.")
    return lines[:3]


def _build_support_points(
    *,
    recommendation: dict[str, Any],
    procurement_read: dict[str, Any] | None,
    material_signals: list[dict[str, Any]],
    what_holds: list[str],
    graph_lines: list[str],
    posture_assessment: dict[str, Any],
) -> list[str]:
    points: list[str] = []
    procurement_points = []
    if isinstance(procurement_read, dict):
        procurement_points = [
            _clean(item)
            for item in ((procurement_read.get("market_position_lines") or []) + (procurement_read.get("implication_lines") or []))
            if _clean(item)
        ]
    recommendation_label = _clean(recommendation.get("label"))
    if recommendation_label == "APPROVED" and procurement_points:
        points.extend(procurement_points[:2])
    if material_signals and not (recommendation_label == "APPROVED" and procurement_points):
        lead = material_signals[0]
        points.append(_join_sentences(lead.get("title"), lead.get("read")))
    elif procurement_points:
        points.extend(procurement_points[:1])
    points.extend(item for item in what_holds[:2] if _clean(item))
    points.extend(item for item in graph_lines[:2] if _clean(item))
    if not points:
        points.append(_clean(recommendation.get("summary"), "The current record does not yet support a sharper intelligence read."))
    if posture_assessment.get("authority"):
        points.append(_clean(posture_assessment["authority"]))
    deduped: list[str] = []
    seen: set[str] = set()
    for point in points:
        if _is_generic_line(point):
            continue
        lowered = point.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(point)
    if not deduped:
        deduped.append(_clean(recommendation.get("summary"), "The current record does not yet support a sharper intelligence read."))
    return deduped[:4]


def _build_principal_headline(
    vendor_name: str,
    recommendation: dict[str, Any],
    procurement_read: dict[str, Any] | None,
    material_signals: list[dict[str, Any]],
) -> str:
    label = _clean(recommendation.get("label"), "PENDING")
    procurement_read = procurement_read if isinstance(procurement_read, dict) else {}
    market_position_lines = [_clean(item) for item in (procurement_read.get("market_position_lines") or []) if _clean(item)]
    if label == "APPROVED":
        prime_names = [_clean(item) for item in (procurement_read.get("top_prime_vehicle_names") or []) if _clean(item)]
        upstream_names = [_clean(item) for item in (procurement_read.get("top_upstream_prime_names") or []) if _clean(item)]
        lead_customer = _clean(procurement_read.get("lead_customer"))
        prime_share = float((procurement_read.get("metrics") or {}).get("prime_share_pct") or 0.0)
        if prime_names:
            prime_phrase = ", ".join(prime_names[:3])
            if upstream_names:
                if lead_customer:
                    return (
                        f"{label} holds with direct access on {prime_phrase}, recurring work under {', '.join(upstream_names[:2])}, "
                        f"and visible demand concentrated around {lead_customer}."
                    )
                return f"{label} holds with direct access on {prime_phrase}, plus recurring work under {', '.join(upstream_names[:2])}."
            if lead_customer and prime_share > 0:
                return f"{label} holds with direct access on {prime_phrase} and {prime_share:.1f}% of visible federal dollars arriving through prime awards."
            return f"{label} holds with direct access on {prime_phrase}."
        if market_position_lines:
            return f"{label} holds with {market_position_lines[0].rstrip('.').lower()}."
    if label == "REVIEW" and market_position_lines:
        return f"{label} holds with {market_position_lines[0].rstrip('.').lower()}."
    if material_signals and _is_weak_match_signal(material_signals[0]) and market_position_lines:
        market_line = market_position_lines[0].rstrip(".")
        if label == "APPROVED":
            return f"{label} holds with {market_line.lower()}."
        if label == "REVIEW":
            return f"{label} holds with {market_line.lower()}."
        if label == "BLOCKED":
            return f"{label} holds against a backdrop where {market_line.lower()}."
    if material_signals:
        lead = material_signals[0]
        lead_title = _clean(lead.get("title"))
        if label == "APPROVED":
            return f"{label} holds, but {lead_title.lower()} is the main remaining pressure."
        if label == "REVIEW":
            return f"{label} holds because {lead_title.lower()} is still unresolved."
        if label == "BLOCKED":
            return f"{label} holds because {lead_title.lower()} materially changes the call."
        return f"{vendor_name} remains unsettled because {lead_title.lower()} is still open."
    return f"{vendor_name} currently reads {label} on the available record."


def _build_principal_narrative(
    vendor_name: str,
    recommendation: dict[str, Any],
    posture_assessment: dict[str, Any],
    support_points: list[str],
) -> str:
    label = _clean(recommendation.get("label"), "PENDING")
    posture_line = _clean(posture_assessment.get("narrative"))
    if support_points:
        support_line = support_points[0]
    else:
        support_line = _clean(recommendation.get("summary"))
    return _join_sentences(
        f"{vendor_name} currently reads {label}",
        support_line,
        posture_line,
    )


def _select_counterview(tribunal: dict[str, Any] | None, recommended_view: str) -> dict[str, Any]:
    if not isinstance(tribunal, dict):
        return {}
    views = [row for row in (tribunal.get("views") or []) if isinstance(row, dict)]
    if not views:
        return {}
    candidates = [view for view in views if _clean(view.get("stance")).lower() != recommended_view.lower()]
    if not candidates:
        return views[0]

    preferred_order: dict[str, tuple[str, ...]] = {
        "approve": ("watch", "deny"),
        "watch": ("deny", "approve"),
        "deny": ("watch", "approve"),
    }
    for preferred in preferred_order.get(recommended_view.lower(), ()):
        matching = [view for view in candidates if _clean(view.get("stance")).lower() == preferred]
        informative = [view for view in matching if not _is_generic_line(_clean(view.get("summary")))]
        if informative:
            return informative[0]
        if matching:
            return matching[0]

    informative = [view for view in candidates if not _is_generic_line(_clean(view.get("summary")))]
    if informative:
        return informative[0]
    return candidates[0]


def _build_counterview(
    *,
    recommendation: dict[str, Any],
    tribunal: dict[str, Any] | None,
    material_signals: list[dict[str, Any]],
    graph_lines: list[str],
) -> dict[str, Any]:
    recommended_view = _clean((tribunal or {}).get("recommended_view") or "")
    competing = _select_counterview(tribunal, recommended_view)
    if not competing:
        return {
            "label": "Competing Case",
            "headline": "No structured counterview is currently available.",
            "narrative": "The dossier does not yet have a competing analytical case strong enough to summarize cleanly.",
            "reasons": [],
            "why_not_current": "No countervailing view has enough structure to displace the current posture.",
        }

    reasons = [_clean(item) for item in (competing.get("reasons") or []) if _clean(item)]
    if not reasons and material_signals:
        reasons.append(_clean(material_signals[0].get("read")))
    if not reasons and graph_lines:
        reasons.append(graph_lines[0])
    stance = _clean(competing.get("stance"))
    headline = _clean(competing.get("summary")) or f"{_label_for_stance(stance)} remains plausible."
    if _is_generic_line(headline) and material_signals:
        lead = material_signals[0]
        lead_title = _clean(lead.get("title"), "the lead signal")
        lead_read = _clean(lead.get("read"))
        if _clean(recommendation.get("label")) == "APPROVED":
            stance = "watch"
            headline = f"{lead_title} could still justify a hold."
            reasons = [lead_read, *reasons]
        elif _clean(recommendation.get("label")) == "REVIEW":
            headline = f"{lead_title} could still harden into a stop case."
            reasons = [lead_read, *reasons]
    why_not_current = (
        "This view does not currently win because the evidence either remains too thin, too conditional, or is outweighed by the stronger competing case."
    )
    if _clean(recommendation.get("label")) == "APPROVED" and stance == "watch":
        why_not_current = "This view does not currently win because the case pressure is real but not yet strong enough to displace forward motion."
    elif _clean(recommendation.get("label")) == "REVIEW" and stance == "approve":
        why_not_current = "This view does not currently win because the record is not clean enough to justify approval without qualifications."
    elif _clean(recommendation.get("label")) == "REVIEW" and stance == "deny":
        why_not_current = "This view does not currently win because the case pressure is meaningful but not yet a clean hard-stop."
    elif _clean(recommendation.get("label")) == "BLOCKED":
        why_not_current = "This view does not currently win because the adverse-control or hard-stop case is stronger than the proceed case."

    return {
        "label": _label_for_stance(stance),
        "headline": headline,
        "narrative": _join_sentences(headline, reasons[0] if reasons else "", why_not_current),
        "reasons": reasons[:3],
        "why_not_current": why_not_current,
    }


def _build_dark_space(
    *,
    gaps: list[str],
    graph_lines: list[str],
    posture_assessment: dict[str, Any],
) -> list[str]:
    dark_space: list[str] = []
    dark_space.extend(_clean(item) for item in gaps[:4] if _clean(item))
    if int(posture_assessment.get("unconfirmed_count") or 0) > 0:
        dark_space.append(
            f"{int(posture_assessment.get('unconfirmed_count') or 0)} unconfirmed finding{'s' if int(posture_assessment.get('unconfirmed_count') or 0) != 1 else ''} still limit how cleanly the case can be carried."
        )
    for line in graph_lines:
        if "thin" in line.lower() or "missing" in line.lower() or "contradicted" in line.lower():
            dark_space.append(line)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in dark_space:
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(item)
    return deduped[:4]


def build_intelligence_thesis(
    *,
    vendor_name: str,
    recommendation: dict[str, Any],
    supplier_passport: dict[str, Any] | None,
    graph_summary: dict[str, Any] | None,
    procurement_read: dict[str, Any] | None,
    material_signals: list[dict[str, Any]],
    decision_shifters: list[str],
    what_holds: list[str],
    gaps: list[str],
    posture_assessment: dict[str, Any],
) -> dict[str, Any]:
    tribunal = (
        supplier_passport.get("tribunal")
        if isinstance(supplier_passport, dict) and isinstance(supplier_passport.get("tribunal"), dict)
        else {}
    )
    graph_lines = _build_graph_read(graph_summary)
    support_points = _build_support_points(
        recommendation=recommendation,
        procurement_read=procurement_read,
        material_signals=material_signals,
        what_holds=what_holds,
        graph_lines=graph_lines,
        posture_assessment=posture_assessment,
    )
    principal_headline = _build_principal_headline(vendor_name, recommendation, procurement_read, material_signals)
    principal_narrative = _build_principal_narrative(
        vendor_name,
        recommendation,
        posture_assessment,
        support_points,
    )
    counterview = _build_counterview(
        recommendation=recommendation,
        tribunal=tribunal,
        material_signals=material_signals,
        graph_lines=graph_lines,
    )
    dark_space = _build_dark_space(
        gaps=gaps,
        graph_lines=graph_lines,
        posture_assessment=posture_assessment,
    )

    thesis_line = _join_sentences(principal_headline, counterview.get("why_not_current"))

    return {
        "thesis_line": thesis_line,
        "principal_judgment": {
            "headline": principal_headline,
            "narrative": principal_narrative,
            "support_points": support_points[:4],
        },
        "counterview": counterview,
        "dark_space": dark_space,
        "collection_priority": [_clean(item) for item in decision_shifters[:4] if _clean(item)],
    }
