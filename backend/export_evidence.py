"""Helpers for normalizing export-authorization evidence into a narrative summary."""

from __future__ import annotations

import re
from typing import Any

try:
    from artifact_vault import list_case_artifacts
    HAS_ARTIFACT_VAULT = True
except ImportError:
    HAS_ARTIFACT_VAULT = False

try:
    from export_artifact_intake import SUPPORTED_EXPORT_ARTIFACT_TYPES
except ImportError:
    SUPPORTED_EXPORT_ARTIFACT_TYPES = {}

try:
    from export_authorization_rules import build_export_authorization_guidance
    HAS_EXPORT_RULES = True
except ImportError:
    HAS_EXPORT_RULES = False


_ECCN_RE = re.compile(r"^\s*[0-9][A-E][0-9]{3}\s*$", re.IGNORECASE)
_ROMAN_MAP = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
    "XI": 11,
    "XII": 12,
    "XIII": 13,
    "XIV": 14,
    "XV": 15,
    "XVI": 16,
    "XVII": 17,
    "XVIII": 18,
    "XIX": 19,
    "XX": 20,
    "XXI": 21,
}
_PROGRAM_USML_RE = re.compile(r"^cat_([ivxlc]+)_", re.IGNORECASE)
_USML_TEXT_RE = re.compile(r"(?:USML|CATEGORY|CAT)\s+([IVXLC]+)", re.IGNORECASE)


def _latest_export_artifact(case_id: str) -> dict | None:
    if not HAS_ARTIFACT_VAULT:
        return None
    for record in list_case_artifacts(case_id, limit=30):
        if record.get("source_system") == "export_artifact_upload":
            return record
    return None


def _parse_usml_category(summary: dict | None, *, program: str = "") -> int:
    if not isinstance(summary, dict):
        return 0

    candidates = [str(summary.get("classification_display") or "").strip()]
    candidates.extend(str(value).strip() for value in (summary.get("detected_usml_references") or []))
    for candidate in candidates:
        match = _USML_TEXT_RE.search(candidate)
        if match:
            return _ROMAN_MAP.get(match.group(1).upper(), 0)

    program_match = _PROGRAM_USML_RE.match(str(program or "").strip())
    if program_match:
        return _ROMAN_MAP.get(program_match.group(1).upper(), 0)
    return 0


def build_export_gate_overlay(
    summary: dict | None,
    *,
    profile: str = "",
    program: str = "",
    foreign_ownership_pct: float = 0.0,
    foci_status: str = "NOT_APPLICABLE",
    cmmc_level: int = 0,
) -> dict:
    if not isinstance(summary, dict):
        return {}

    jurisdiction = str(summary.get("jurisdiction_guess") or "").strip().lower()
    classification_display = str(summary.get("classification_display") or "").strip().upper()
    posture = str(summary.get("posture") or "").strip().lower()
    artifact_type = str(summary.get("artifact_type") or "").strip()
    destination_country = str(summary.get("destination_country") or "").strip().upper() or "US"
    foreign_person_nationalities = [
        str(value or "").strip().upper()
        for value in (summary.get("foreign_person_nationalities") or [])
        if str(value or "").strip()
    ]

    has_document_package = bool(summary.get("artifact_id")) or bool(summary.get("detected_license_tokens"))
    has_procedures = has_document_package or artifact_type in {
        "export_technology_control_plan",
        "export_access_control_record",
        "export_classification_memo",
    }
    training_current = artifact_type in {
        "export_technology_control_plan",
        "export_access_control_record",
    }
    tcp_status = "IMPLEMENTED" if training_current else ("MISSING" if foreign_person_nationalities else "NOT_REQUIRED")

    usml_category = _parse_usml_category(summary, program=program)
    is_itar_controlled = jurisdiction == "itar" or usml_category > 0 or bool(summary.get("detected_usml_references"))
    ear_category = classification_display if _ECCN_RE.match(classification_display) else ""
    if profile == "itar_trade_compliance" and program == "dual_use_ear" and not ear_category:
        ear_category = classification_display if classification_display != "NEEDS CLASSIFICATION" else ""

    ear_foreign_content_pct = 0.0
    if ear_category:
        if posture in {"likely_license_required", "escalate", "insufficient_confidence", "likely_prohibited"}:
            ear_foreign_content_pct = 0.26
        elif posture in {"likely_exception_or_exemption", "likely_nlr"}:
            ear_foreign_content_pct = 0.10

    return {
        "itar": {
            "item_is_itar_controlled": is_itar_controlled,
            "entity_foreign_ownership_pct": float(foreign_ownership_pct or 0.0),
            "entity_nationality_of_control": destination_country,
            "entity_has_itar_compliance_certification": has_document_package,
            "entity_manufacturing_process_certified": False,
            "entity_has_approved_voting_agreement": str(foci_status).upper() == "MITIGATED",
            "entity_foci_status": str(foci_status or "NOT_APPLICABLE").upper(),
            "entity_cmmc_level": int(cmmc_level or 0),
        },
        "ear": {
            "item_ear_ccl_category": ear_category,
            "entity_foreign_origin_content_pct": ear_foreign_content_pct,
            "entity_has_export_control_procedures": has_procedures,
            "entity_has_export_control_document_package": has_document_package,
            "entity_export_control_deemed_export_training_current": training_current,
        },
        "deemed_export": {
            "foreign_nationals": [
                {"nationality": nat, "role": "request_subject", "access_level": "controlled"}
                for nat in foreign_person_nationalities
            ],
            "tcp_status": tcp_status,
            "usml_category": usml_category,
            "facility_clearance": "UNCLASSIFIED",
        },
        "usml_control": {
            "usml_category": usml_category,
            "vendor_country": destination_country,
        },
    }


def apply_export_risk_overlay(
    summary: dict | None,
    *,
    current_itar: float = 0.0,
    current_ear: float = 0.0,
) -> dict[str, float]:
    if not isinstance(summary, dict):
        return {
            "itar_exposure": float(current_itar or 0.0),
            "ear_control_status": float(current_ear or 0.0),
        }

    jurisdiction = str(summary.get("jurisdiction_guess") or "").strip().lower()
    classification_display = str(summary.get("classification_display") or "").strip().upper()
    posture = str(summary.get("posture") or "").strip().lower()
    has_usml_refs = bool(summary.get("detected_usml_references"))
    has_eccn = bool(_ECCN_RE.match(classification_display))

    itar_score = float(current_itar or 0.0)
    ear_score = float(current_ear or 0.0)

    if jurisdiction == "itar" or has_usml_refs:
        if posture == "likely_prohibited":
            itar_score = max(itar_score, 0.92)
        elif posture in {"likely_license_required", "escalate"}:
            itar_score = max(itar_score, 0.72)
        elif posture == "insufficient_confidence":
            itar_score = max(itar_score, 0.56)
        else:
            itar_score = max(itar_score, 0.34)

    if jurisdiction == "ear" or has_eccn:
        if posture == "likely_prohibited":
            ear_score = max(ear_score, 0.88)
        elif posture in {"likely_license_required", "escalate"}:
            ear_score = max(ear_score, 0.66)
        elif posture == "insufficient_confidence":
            ear_score = max(ear_score, 0.52)
        elif posture == "likely_exception_or_exemption":
            ear_score = max(ear_score, 0.34)
        elif posture == "likely_nlr":
            ear_score = max(ear_score, 0.16)

    return {
        "itar_exposure": round(min(itar_score, 0.98), 4),
        "ear_control_status": round(min(ear_score, 0.98), 4),
    }


def get_export_evidence_summary(case_id: str, case_input: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(case_input, dict) or not case_input:
        return None

    guidance = build_export_authorization_guidance(case_input) if HAS_EXPORT_RULES else None
    artifact = _latest_export_artifact(case_id)
    structured_fields = (artifact or {}).get("structured_fields") or {}

    declared_classification = str(structured_fields.get("declared_classification") or case_input.get("classification_guess") or "").strip().upper()
    declared_jurisdiction = str(structured_fields.get("declared_jurisdiction") or case_input.get("jurisdiction_guess") or "").strip().lower()
    detected_classifications = [
        value for value in (
            [declared_classification] if declared_classification else []
        ) + list(structured_fields.get("detected_classifications") or [])
        if value
    ]
    # preserve order, drop duplicates
    detected_classifications = list(dict.fromkeys(detected_classifications))[:6]
    detected_usml_references = list(dict.fromkeys(structured_fields.get("detected_usml_references") or []))[:6]
    detected_license_tokens = list(dict.fromkeys(structured_fields.get("detected_license_tokens") or []))[:10]
    destination_country = str(case_input.get("destination_country") or "").strip().upper()
    foreign_person_nationalities = [
        str(value or "").strip().upper()
        for value in (case_input.get("foreign_person_nationalities") or [])
        if str(value or "").strip()
    ]

    posture = str((guidance or {}).get("posture") or "insufficient_confidence")
    posture_label = str((guidance or {}).get("posture_label") or "Insufficient confidence")
    reason_summary = str((guidance or {}).get("reason_summary") or "").strip()
    recommended_next_step = str((guidance or {}).get("recommended_next_step") or "").strip()
    confidence = float((guidance or {}).get("confidence") or 0.0)

    item_label = str(case_input.get("request_type") or "export request").replace("_", " ").strip()
    classification_display = declared_classification or (", ".join(detected_usml_references[:1]) if detected_usml_references else "Needs classification")
    artifact_type = str((artifact or {}).get("artifact_type") or "")
    artifact_label = SUPPORTED_EXPORT_ARTIFACT_TYPES.get(artifact_type, "Customer export artifact") if artifact_type else ""

    if posture == "likely_prohibited":
        narrative = (
            f"Helios rules guidance indicates this {item_label} is likely prohibited for destination or foreign-person context"
            + (f" involving {destination_country}" if destination_country else "")
            + (f", classified as {classification_display}" if classification_display else "")
            + "."
        )
    elif posture in {"likely_license_required", "escalate", "insufficient_confidence"}:
        narrative = (
            f"Helios rules guidance indicates this {item_label} requires formal export review"
            + (f" for {classification_display}" if classification_display else "")
            + (f" to {destination_country}" if destination_country else "")
            + "."
        )
    else:
        narrative = (
            f"Helios rules guidance suggests a lower-friction authorization posture for this {item_label}"
            + (f" with {classification_display}" if classification_display else "")
            + (f" to {destination_country}" if destination_country else "")
            + "."
        )

    if artifact_label:
        narrative += f" Customer evidence includes {artifact_label.lower()}."
    if reason_summary:
        narrative += f" {reason_summary}"

    return {
        "posture": posture,
        "posture_label": posture_label,
        "confidence": confidence,
        "reason_summary": reason_summary,
        "recommended_next_step": recommended_next_step,
        "request_type": str(case_input.get("request_type") or "").strip(),
        "recipient_name": str(case_input.get("recipient_name") or "").strip(),
        "destination_country": destination_country,
        "jurisdiction_guess": declared_jurisdiction or str(case_input.get("jurisdiction_guess") or "").strip().lower(),
        "classification_display": classification_display,
        "foreign_person_nationalities": foreign_person_nationalities,
        "artifact_id": (artifact or {}).get("id"),
        "artifact_type": artifact_type,
        "artifact_label": artifact_label,
        "detected_classifications": detected_classifications,
        "detected_usml_references": detected_usml_references,
        "detected_license_tokens": detected_license_tokens,
        "contains_foreign_person_terms": bool(structured_fields.get("contains_foreign_person_terms")) or bool(foreign_person_nationalities),
        "narrative": narrative.strip(),
        "escalation_required": posture in {"likely_prohibited", "likely_license_required", "escalate", "insufficient_confidence"},
        "official_references": (guidance or {}).get("official_references") or [],
    }
