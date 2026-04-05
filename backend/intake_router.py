from __future__ import annotations

import re
from typing import Any

from contract_vehicle_search import VEHICLE_ALIASES
from entity_resolver import _search_knowledge_graph_memory, _search_local_vendor_memory


_VEHICLE_CUE_RE = re.compile(
    r"\b(vehicle|contract vehicle|recompete|follow-on|follow on|pre-solicitation|pre solicitation|solicitation|piid|award|task order|idiq|gwac|bpa)\b",
    re.IGNORECASE,
)
_VENDOR_CUE_RE = re.compile(
    r"\b(vendor|supplier|company|entity|teammate|partner|prime contractor|subcontractor|read on|assessment on|screen|trust read|competitive read|compete against)\b",
    re.IGNORECASE,
)
_VEHICLE_TOKEN_RE = re.compile(r"\b[A-Z]{2,}[ -]?\d{1,3}[A-Z0-9-]*\b")
_CORPORATE_SUFFIX_RE = re.compile(r"\b(inc|corp|corporation|llc|ltd|plc|lp|llp|co|company|gmbh|ag|sa|srl|bv|nv)\b", re.IGNORECASE)
_QUESTION_OPENERS = {"who", "what", "when", "where", "why", "how", "is", "are", "can", "do", "does", "should"}


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_seed(value: str) -> str:
    return _compact(value).rstrip("?.! ").lower()


def _vehicle_aliases() -> set[str]:
    aliases: set[str] = set()
    for key, values in VEHICLE_ALIASES.items():
        aliases.add(_normalize_seed(key))
        for value in values:
            aliases.add(_normalize_seed(value))
    return aliases


_KNOWN_VEHICLE_SEEDS = _vehicle_aliases()


def _extract_vehicle_anchor(text: str) -> str:
    source = _compact(text)
    cleaned = re.sub(r"\b(contract vehicle|vehicle|solicitation|piid|task order|idiq|gwac|bpa)\b", "", source, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" ,:-")
    return cleaned or source


def _extract_vendor_anchor(text: str) -> str:
    return _compact(re.sub(r"\b(vendor|supplier|company|entity)\b", "", text, flags=re.IGNORECASE).strip(" ,:-")) or _compact(text)


def _vendor_memory_signal(text: str) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    try:
        local_hits = _search_local_vendor_memory(text)
    except Exception:
        local_hits = []
    try:
        graph_hits = _search_knowledge_graph_memory(text)
    except Exception:
        graph_hits = []

    if local_hits:
        top = local_hits[0]
        score = max(score, 0.86 if str(top.get("source")) == "local_vendor_memory" else 0.72)
        reasons.append(f"Local vendor memory already has {top.get('legal_name', 'a matching entity')} in frame.")
    if graph_hits:
        top = graph_hits[0]
        score = max(score, 0.78)
        reasons.append(f"Graph memory already has {top.get('legal_name', 'a matching entity')} in frame.")
    return score, reasons


def route_intake(
    text: str,
    *,
    current_object_type: str | None = None,
    in_entity_narrowing: bool = False,
) -> dict[str, Any]:
    raw = _compact(text)
    normalized = _normalize_seed(raw)
    tokens = raw.split()
    opener = tokens[0].lower() if tokens else ""

    vehicle_score = 0.0
    vendor_score = 0.0
    vehicle_reasons: list[str] = []
    vendor_reasons: list[str] = []
    override_applied = False

    explicit_vehicle = bool(_VEHICLE_CUE_RE.search(raw))
    explicit_vendor = bool(_VENDOR_CUE_RE.search(raw))

    if explicit_vehicle:
        vehicle_score = max(vehicle_score, 0.94)
        vehicle_reasons.append("The user explicitly described the target as a contract vehicle.")
    if explicit_vendor:
        vendor_score = max(vendor_score, 0.9)
        vendor_reasons.append("The user explicitly described the target as a vendor or company.")

    if normalized in _KNOWN_VEHICLE_SEEDS:
        vehicle_score = max(vehicle_score, 0.9)
        vehicle_reasons.append("The input matches a known contract-vehicle seed.")

    if _VEHICLE_TOKEN_RE.search(raw):
        vehicle_score = max(vehicle_score, 0.7)
        vehicle_reasons.append("The token pattern looks like a contract vehicle or solicitation identifier.")

    if _CORPORATE_SUFFIX_RE.search(raw):
        vendor_score = max(vendor_score, 0.75)
        vendor_reasons.append("The name carries an operating-entity suffix.")

    if (
        raw
        and len(tokens) <= 6
        and re.search(r"[A-Za-z]", raw)
        and opener not in _QUESTION_OPENERS
    ):
        vendor_score = max(vendor_score, 0.42)
        vendor_reasons.append("The input reads like a named entity rather than a freeform question.")

    memory_score, memory_reasons = _vendor_memory_signal(raw)
    if memory_score > 0:
        vendor_score = max(vendor_score, memory_score)
        vendor_reasons.extend(memory_reasons)

    current = str(current_object_type or "").strip().lower() or None
    if current == "vendor" and explicit_vehicle:
        override_applied = True
        vehicle_score = max(vehicle_score, 0.98)
        vehicle_reasons.append("The new turn explicitly overrides the earlier vendor assumption.")
    if current == "vehicle" and explicit_vendor:
        override_applied = True
        vendor_score = max(vendor_score, 0.98)
        vendor_reasons.append("The new turn explicitly overrides the earlier vehicle assumption.")
    if in_entity_narrowing and explicit_vehicle:
        override_applied = True
        vehicle_score = max(vehicle_score, 0.99)
        vehicle_reasons.append("Entity narrowing should be abandoned because the user corrected the frame to a contract vehicle.")

    winning_mode: str | None = None
    max_score = max(vehicle_score, vendor_score)
    diff = abs(vehicle_score - vendor_score)
    clarifier_needed = False

    if max_score < 0.62 or diff < 0.16:
        clarifier_needed = True
    else:
        winning_mode = "vehicle" if vehicle_score > vendor_score else "vendor"

    if override_applied and max_score >= 0.8:
        clarifier_needed = False
        winning_mode = "vehicle" if vehicle_score >= vendor_score else "vendor"

    anchor_text = ""
    if winning_mode == "vehicle":
        anchor_text = _extract_vehicle_anchor(raw)
    elif winning_mode == "vendor":
        anchor_text = _extract_vendor_anchor(raw)

    return {
        "raw_input": raw,
        "winning_mode": winning_mode,
        "confidence": round(max_score, 3),
        "clarifier_needed": clarifier_needed,
        "override_applied": override_applied,
        "anchor_text": anchor_text,
        "hypotheses": [
            {"kind": "vehicle", "score": round(vehicle_score, 3), "reasons": vehicle_reasons[:4]},
            {"kind": "vendor", "score": round(vendor_score, 3), "reasons": vendor_reasons[:4]},
        ],
    }
