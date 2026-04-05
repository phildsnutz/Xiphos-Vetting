from __future__ import annotations

from typing import Any


_RANK = {
    "pending": 0,
    "approved": 1,
    "review": 2,
    "blocked": 3,
}

_LABEL = {
    "pending": "PENDING",
    "approved": "APPROVED",
    "review": "REVIEW",
    "blocked": "BLOCKED",
}

_SUMMARY = {
    "pending": "The evidence bundle is still incomplete enough that Helios should not pretend the picture is settled.",
    "approved": "The visible record is holding cleanly enough for Helios to support forward motion without manufacturing friction.",
    "review": "The visible record contains enough uncertainty, pressure, or unresolved control context that Helios should force analyst review.",
    "blocked": "The visible record contains a hard stop or material adverse control signal that should block progress until contradicted with stronger evidence.",
}


def _normalize_posture(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "pending"
    if any(token in text for token in ("block", "reject", "deny", "hard stop", "disqual")):
        return "blocked"
    if any(token in text for token in ("review", "watch", "conditional", "elevated", "caution", "escalate")):
        return "review"
    if any(token in text for token in ("approve", "qualified", "clear", "ready", "acceptable", "mitigated")):
        return "approved"
    return "pending"


def _tier_posture(score: dict[str, Any] | None) -> str:
    calibrated = (score or {}).get("calibrated") if isinstance(score, dict) else None
    tier = str((calibrated or {}).get("calibrated_tier") or "").upper()
    if any(token in tier for token in ("BLOCK", "HARD_STOP", "DENIED", "DISQUALIFIED")):
        return "blocked"
    if any(token in tier for token in ("REVIEW", "ELEVATED", "CONDITIONAL", "CAUTION", "WATCH")):
        return "review"
    if any(token in tier for token in ("APPROVED", "QUALIFIED", "CLEAR", "ACCEPTABLE")):
        return "approved"
    return "pending"


def resolve_case_recommendation(
    *,
    score: dict[str, Any] | None = None,
    supplier_passport: dict[str, Any] | None = None,
    latest_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score_posture = _tier_posture(score)
    passport_posture = _normalize_posture((supplier_passport or {}).get("posture"))
    decision_posture = _normalize_posture((latest_decision or {}).get("decision"))
    tribunal_posture = "pending"

    if isinstance(supplier_passport, dict):
        tribunal = supplier_passport.get("tribunal") if isinstance(supplier_passport.get("tribunal"), dict) else {}
        label = tribunal.get("recommended_label") or tribunal.get("recommended_view")
        tribunal_posture = _normalize_posture(label)

    signals = []
    if score_posture != "pending":
        signals.append(("score", score_posture))
    if passport_posture != "pending":
        signals.append(("passport", passport_posture))
    if decision_posture != "pending":
        signals.append(("decision", decision_posture))

    final_posture = "pending"
    final_sources: list[str] = []
    for source, posture in signals:
        if _RANK[posture] >= _RANK[final_posture]:
            if _RANK[posture] > _RANK[final_posture]:
                final_sources = [source]
            else:
                final_sources.append(source)
            final_posture = posture

    if final_posture == "pending" and tribunal_posture != "pending":
        final_posture = tribunal_posture
        final_sources = ["tribunal"]
    elif tribunal_posture == "blocked" and _RANK[final_posture] < _RANK["blocked"]:
        final_posture = "blocked"
        final_sources = sorted(set(final_sources + ["tribunal"]))

    return {
        "posture": final_posture,
        "label": _LABEL[final_posture],
        "summary": _SUMMARY[final_posture],
        "sources": final_sources,
        "score_posture": score_posture,
        "passport_posture": passport_posture,
        "decision_posture": decision_posture,
        "tribunal_posture": tribunal_posture,
    }
