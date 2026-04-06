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
_VEHICLE_REVISION_CUE_RE = re.compile(
    r"\b(not (?:a |the )?(?:company|vendor|entity)|(?:it'?s|it is) the vehicle|vehicle,? not (?:a |the )?(?:company|vendor|entity))\b",
    re.IGNORECASE,
)
_VENDOR_REVISION_CUE_RE = re.compile(
    r"\b(not (?:the )?vehicle|specific vendor|specific company|(?:it'?s|it is) the (?:vendor|company|entity))\b",
    re.IGNORECASE,
)
_VEHICLE_TOKEN_RE = re.compile(r"\b[A-Z]{2,}[ -]?\d{1,3}[A-Z0-9-]*\b")
_CORPORATE_SUFFIX_RE = re.compile(r"\b(inc|corp|corporation|llc|ltd|plc|lp|llp|co|company|gmbh|ag|sa|srl|bv|nv)\b", re.IGNORECASE)
_QUESTION_OPENERS = {"who", "what", "when", "where", "why", "how", "is", "are", "can", "do", "does", "should"}
_VEHICLE_ANCHOR_CUES = [
    re.compile(r"\b(?:follow[- ]on|pre[- ]solicitation|incumbent|current prime|prime is|we think|current vehicle|expired vehicle|net new)\b", re.IGNORECASE),
    re.compile(r"[?.!]"),
    re.compile(r",\s"),
]


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
_KNOWN_VEHICLE_PATTERNS = tuple(
    (alias, re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.IGNORECASE))
    for alias in sorted(_KNOWN_VEHICLE_SEEDS, key=len, reverse=True)
)


def _cut_before_cue(value: str, cues: list[re.Pattern[str]]) -> str:
    end = len(value)
    for cue in cues:
        match = cue.search(value)
        if match and match.start() < end:
            end = match.start()
    return value[:end]


def _clean_anchor_fragment(value: str) -> str:
    cleaned = _compact(value).strip(" ,:-")
    return cleaned.rstrip("?.! ").strip(" ,:-")


def _find_known_vehicle_mention(text: str) -> str | None:
    source = _compact(text)
    if not source:
        return None
    for _, pattern in _KNOWN_VEHICLE_PATTERNS:
        match = pattern.search(source)
        if match:
            return _clean_anchor_fragment(match.group(0))
    return None


def _find_graph_vehicle_mention(text: str) -> str | None:
    try:
        graph_hits = _search_knowledge_graph_memory(text)
    except Exception:
        graph_hits = []
    normalized_text = _normalize_seed(text)
    for hit in graph_hits:
        if str(hit.get("entity_type") or "").strip().lower() != "contract_vehicle":
            continue
        legal_name = _clean_anchor_fragment(str(hit.get("legal_name") or ""))
        if not legal_name:
            continue
        normalized_legal_name = _normalize_seed(legal_name)
        if normalized_legal_name == normalized_text or normalized_text.startswith(normalized_legal_name) or normalized_legal_name in normalized_text:
            return legal_name
    return None


def _extract_vehicle_anchor(text: str) -> str:
    source = _compact(text)
    known_vehicle = _find_known_vehicle_mention(source)
    if known_vehicle:
        return known_vehicle

    graph_vehicle = _find_graph_vehicle_mention(source)
    if graph_vehicle:
        return graph_vehicle

    token_match = _VEHICLE_TOKEN_RE.search(source)
    if token_match:
        return _clean_anchor_fragment(token_match.group(0))

    candidate = re.sub(r"^(?:we(?:'re| are)?\s+looking\s+at|looking\s+at|it(?:'s| is)|the\s+follow[- ]on\s+to|follow[- ]on\s+to)\s+", "", source, flags=re.IGNORECASE)
    candidate = re.sub(r"\b(contract vehicle|vehicle|solicitation|piid|task order|idiq|gwac|bpa)\b", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\bnot (?:a |the )?(?:company|vendor|entity)\b", "", candidate, flags=re.IGNORECASE)
    candidate = _cut_before_cue(candidate, _VEHICLE_ANCHOR_CUES)
    cleaned = _clean_anchor_fragment(candidate)
    return cleaned or source


def _extract_vendor_anchor(text: str) -> str:
    cleaned = re.sub(r"\b(vendor|supplier|company|entity)\b", "", text, flags=re.IGNORECASE)
    return _clean_anchor_fragment(cleaned) or _compact(text)


def _memory_signals(text: str) -> tuple[float, list[str], float, list[str]]:
    vehicle_reasons: list[str] = []
    vendor_reasons: list[str] = []
    vehicle_score = 0.0
    vendor_score = 0.0
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
        vendor_score = max(vendor_score, 0.86 if str(top.get("source")) == "local_vendor_memory" else 0.72)
        vendor_reasons.append(f"Local vendor memory already has {top.get('legal_name', 'a matching entity')} in frame.")
    for hit in graph_hits:
        legal_name = str(hit.get("legal_name") or "a matching entity").strip()
        entity_type = str(hit.get("entity_type") or "").strip().lower()
        if entity_type == "contract_vehicle":
            exact_match = _normalize_seed(legal_name) == _normalize_seed(text)
            vehicle_score = max(vehicle_score, 0.9 if exact_match else 0.84)
            vehicle_reasons.append(f"Graph memory already has {legal_name or 'a matching entity'} in frame as a contract vehicle.")
            continue
        vendor_score = max(vendor_score, 0.78)
        vendor_reasons.append(f"Graph memory already has {legal_name or 'a matching entity'} in frame as an entity.")
    return vehicle_score, vehicle_reasons, vendor_score, vendor_reasons


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
    revision_to_vehicle = bool(_VEHICLE_REVISION_CUE_RE.search(raw))
    revision_to_vendor = bool(_VENDOR_REVISION_CUE_RE.search(raw))
    known_vehicle_mention = _find_known_vehicle_mention(raw)

    if explicit_vehicle and not revision_to_vendor:
        vehicle_score = max(vehicle_score, 0.94)
        vehicle_reasons.append("The user explicitly described the target as a contract vehicle.")
    if explicit_vendor and not revision_to_vehicle:
        vendor_score = max(vendor_score, 0.9)
        vendor_reasons.append("The user explicitly described the target as a vendor or company.")
    if revision_to_vehicle:
        vehicle_score = max(vehicle_score, 0.96)
        vehicle_reasons.append("The user explicitly corrected the frame away from company or entity and back to a contract vehicle.")
    if revision_to_vendor:
        vendor_score = max(vendor_score, 0.96)
        vendor_reasons.append("The user explicitly corrected the frame away from a vehicle and back to a specific company or entity.")

    if known_vehicle_mention:
        known_vehicle_score = 0.9 if normalized == _normalize_seed(known_vehicle_mention) else 0.84
        vehicle_score = max(vehicle_score, known_vehicle_score)
        vehicle_reasons.append(
            "The input matches a known contract-vehicle seed."
            if known_vehicle_score >= 0.9
            else "The input names a known contract vehicle inside a larger phrase."
        )

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

    memory_vehicle_score, memory_vehicle_reasons, memory_vendor_score, memory_vendor_reasons = _memory_signals(raw)
    if memory_vehicle_score > 0:
        vehicle_score = max(vehicle_score, memory_vehicle_score)
        vehicle_reasons.extend(memory_vehicle_reasons)
    if memory_vendor_score > 0:
        vendor_score = max(vendor_score, memory_vendor_score)
        vendor_reasons.extend(memory_vendor_reasons)

    current = str(current_object_type or "").strip().lower() or None
    strong_vehicle_revision = vehicle_score >= 0.84 and vehicle_score >= vendor_score + 0.18
    strong_vendor_revision = vendor_score >= 0.84 and vendor_score >= vehicle_score + 0.18
    explicit_vehicle_revision = explicit_vehicle or revision_to_vehicle
    explicit_vendor_revision = explicit_vendor or revision_to_vendor
    if current == "vendor" and explicit_vehicle_revision:
        override_applied = True
        vehicle_score = max(vehicle_score, 0.98)
        vehicle_reasons.append("The new turn explicitly overrides the earlier vendor assumption.")
    elif current == "vendor" and strong_vehicle_revision:
        override_applied = True
        vehicle_score = max(vehicle_score, 0.97)
        vehicle_reasons.append("The new turn is strong enough to revise the earlier vendor frame back to a contract vehicle.")
    if current == "vehicle" and explicit_vendor_revision:
        override_applied = True
        vendor_score = max(vendor_score, 0.98)
        vendor_reasons.append("The new turn explicitly overrides the earlier vehicle assumption.")
    elif current == "vehicle" and strong_vendor_revision:
        override_applied = True
        vendor_score = max(vendor_score, 0.97)
        vendor_reasons.append("The new turn is strong enough to revise the earlier vehicle frame back to a specific company or entity.")
    if in_entity_narrowing and (explicit_vehicle_revision or strong_vehicle_revision):
        override_applied = True
        vehicle_score = max(vehicle_score, 0.99)
        vehicle_reasons.append("Entity narrowing should be abandoned because the new turn points back to a contract vehicle.")

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
