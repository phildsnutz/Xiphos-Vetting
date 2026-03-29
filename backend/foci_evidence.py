"""Helpers for summarizing customer-provided FOCI artifacts."""

from __future__ import annotations

import re
from typing import Any

try:
    from artifact_vault import list_case_artifacts
    HAS_ARTIFACT_VAULT = True
except ImportError:
    HAS_ARTIFACT_VAULT = False


_PERCENT_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def _coerce_pct(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _PERCENT_RE.search(str(value))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "_")


def summarize_foci_artifact(record: dict | None) -> dict | None:
    if not isinstance(record, dict):
        return None

    fields = record.get("structured_fields") or {}
    if not isinstance(fields, dict):
        fields = {}

    mitigation_tokens = [
        _normalize_token(item)
        for item in (fields.get("mitigation_tokens") or [])
        if str(item or "").strip()
    ]
    mitigation_type = _normalize_token(fields.get("declared_mitigation_type"))
    mitigation_status = _normalize_token(fields.get("declared_mitigation_status"))
    ownership_pct = _coerce_pct(fields.get("declared_foreign_ownership_pct"))
    if ownership_pct is None:
        ownership_pct = _coerce_pct(fields.get("max_ownership_percent_mention"))

    foreign_owner = str(fields.get("declared_foreign_owner") or "").strip()
    foreign_country = str(fields.get("declared_foreign_country") or "").strip().upper()
    mitigation_present = bool(
        mitigation_type
        or mitigation_tokens
        or mitigation_status in {"MITIGATED", "IN_PROGRESS"}
    )
    foreign_interest_indicated = bool(
        (ownership_pct is not None and ownership_pct > 0)
        or foreign_owner
        or foreign_country
        or fields.get("contains_foreign_influence_terms")
        or fields.get("contains_government_affiliation_terms")
    )

    if foreign_interest_indicated and mitigation_present:
        posture = "mitigated_foreign_interest"
    elif foreign_interest_indicated:
        posture = "foreign_interest_requires_review"
    else:
        posture = "resolved_control_chain"

    pct_display = f"{ownership_pct:g}%" if ownership_pct is not None else "Not stated"
    owner_display = foreign_owner or foreign_country or "Not stated"
    mitigation_display = mitigation_type or (mitigation_tokens[0] if mitigation_tokens else "") or mitigation_status or "Not stated"

    if posture == "mitigated_foreign_interest":
        narrative = (
            f"Customer ownership evidence shows {pct_display} foreign ownership linked to {owner_display}, "
            f"with {mitigation_display.replace('_', ' ')} noted."
        )
    elif posture == "foreign_interest_requires_review":
        narrative = (
            f"Customer ownership evidence indicates {pct_display} foreign ownership or influence tied to {owner_display}; "
            "the control chain should be adjudicated before approval."
        )
    else:
        narrative = (
            "Customer ownership evidence supports a resolved control chain with no explicit foreign ownership or control signal "
            "in the attached material."
        )

    return {
        "artifact_id": record.get("id"),
        "artifact_type": record.get("artifact_type"),
        "artifact_label": str(fields.get("artifact_label") or record.get("artifact_type") or "FOCI artifact"),
        "filename": record.get("filename"),
        "foreign_owner": foreign_owner,
        "foreign_country": foreign_country,
        "foreign_ownership_pct": ownership_pct,
        "foreign_ownership_pct_display": pct_display,
        "mitigation_status": mitigation_status,
        "mitigation_type": mitigation_type,
        "mitigation_display": mitigation_display.replace("_", " "),
        "mitigation_tokens": mitigation_tokens,
        "foreign_interest_indicated": foreign_interest_indicated,
        "mitigation_present": mitigation_present,
        "contains_governance_control_terms": bool(fields.get("contains_governance_control_terms")),
        "contains_government_affiliation_terms": bool(fields.get("contains_government_affiliation_terms")),
        "contains_clearance_terms": bool(fields.get("contains_clearance_terms")),
        "posture": posture,
        "narrative": narrative,
    }


def get_latest_foci_artifact(case_id: str) -> dict | None:
    if not HAS_ARTIFACT_VAULT:
        return None
    for record in list_case_artifacts(case_id, limit=20):
        if record.get("source_system") == "foci_artifact_upload":
            return record
    return None


def get_latest_foci_summary(case_id: str) -> dict | None:
    return summarize_foci_artifact(get_latest_foci_artifact(case_id))


def build_foci_gate_overlay(summary: dict | None, *, base_foreign_ownership_pct: float = 0.0) -> dict:
    if not isinstance(summary, dict):
        return {}

    overlay: dict[str, Any] = {}
    foreign_interest = bool(summary.get("foreign_interest_indicated"))
    mitigation_present = bool(summary.get("mitigation_present"))
    pct = summary.get("foreign_ownership_pct")
    pct_ratio = None
    if isinstance(pct, (int, float)):
        pct_ratio = max(0.0, float(pct) / 100.0)

    if pct_ratio is not None:
        overlay["entity_foreign_ownership_pct"] = max(float(base_foreign_ownership_pct or 0.0), pct_ratio)
    elif foreign_interest and base_foreign_ownership_pct <= 0:
        overlay["entity_foreign_ownership_pct"] = 0.01

    if summary.get("foreign_country"):
        overlay["foreign_controlling_country"] = str(summary["foreign_country"]).upper()

    mitigation_status = _normalize_token(summary.get("mitigation_status"))
    mitigation_type = _normalize_token(summary.get("mitigation_type"))
    if mitigation_type:
        overlay["foci_mitigation_type"] = mitigation_type

    if mitigation_status in {"MITIGATED", "IN_PROGRESS"}:
        overlay["entity_foci_mitigation_status"] = mitigation_status
    elif foreign_interest and not mitigation_present:
        overlay["entity_foci_mitigation_status"] = "UNMITIGATED"
    elif foreign_interest and mitigation_present:
        overlay["entity_foci_mitigation_status"] = "IN_PROGRESS"

    return overlay
