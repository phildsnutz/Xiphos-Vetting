"""
Secure intake helpers for export-authorization artifacts.

These uploads are customer-controlled records that rarely exist in public
datasets: classification memos, license history, CCATS / CJ outcomes, access
approvals, and related internal evidence. v1 stores the raw artifact securely
and extracts lightweight hints that help Helios frame the case.
"""

from __future__ import annotations

import re
from typing import Any

from artifact_vault import store_artifact


SUPPORTED_EXPORT_ARTIFACT_TYPES = {
    "export_classification_memo": "Classification memo",
    "export_ccats_or_cj": "CCATS / Commodity Jurisdiction",
    "export_license_history": "License history",
    "export_access_control_record": "Access-control record",
    "export_technology_control_plan": "Technology control plan",
    "export_deccs_or_snapr_export": "DECCS / SNAP-R export",
}

_ECCN_RE = re.compile(r"\b[0-9][A-E][0-9]{3}\b", re.IGNORECASE)
_USML_RE = re.compile(r"\b(?:USML|CATEGORY\s+[IVXLC]+|CAT\s+[IVXLC]+)\b", re.IGNORECASE)
_LICENSE_TOKEN_RE = re.compile(r"\b(?:DSP-5|DSP-73|DSP-85|TAA|MLA|WDA|CCATS|CJ|SNAP-R|DECCS)\b", re.IGNORECASE)
_FOREIGN_PERSON_RE = re.compile(r"\bforeign person\b|\bdeemed export\b|\bnationality\b", re.IGNORECASE)


def _extract_text_hints(content: bytes) -> dict[str, Any]:
    text = content[:50_000].decode("utf-8", errors="ignore")
    classifications = sorted({match.group(0).upper() for match in _ECCN_RE.finditer(text)})
    usml_hits = sorted({match.group(0).upper() for match in _USML_RE.finditer(text)})
    license_tokens = sorted({match.group(0).upper() for match in _LICENSE_TOKEN_RE.finditer(text)})
    return {
        "detected_classifications": classifications[:6],
        "detected_usml_references": usml_hits[:6],
        "detected_license_tokens": license_tokens[:10],
        "contains_foreign_person_terms": bool(_FOREIGN_PERSON_RE.search(text)),
    }


def ingest_export_artifact(
    case_id: str,
    artifact_type: str,
    filename: str,
    content: bytes,
    *,
    uploaded_by: str = "",
    effective_date: str | None = None,
    notes: str = "",
    declared_classification: str = "",
    declared_jurisdiction: str = "",
) -> dict:
    if artifact_type not in SUPPORTED_EXPORT_ARTIFACT_TYPES:
        raise ValueError(f"Unsupported export artifact type: {artifact_type}")

    hints = _extract_text_hints(content)
    structured_fields = {
        "artifact_label": SUPPORTED_EXPORT_ARTIFACT_TYPES[artifact_type],
        "notes": str(notes or "").strip(),
        "declared_classification": str(declared_classification or "").strip().upper(),
        "declared_jurisdiction": str(declared_jurisdiction or "").strip().lower(),
        **hints,
    }
    parse_status = "parsed" if any(
        [
            structured_fields["detected_classifications"],
            structured_fields["detected_usml_references"],
            structured_fields["detected_license_tokens"],
            structured_fields["contains_foreign_person_terms"],
            structured_fields["declared_classification"],
            structured_fields["declared_jurisdiction"],
        ]
    ) else "stored"

    return store_artifact(
        case_id,
        artifact_type,
        filename,
        content,
        source_system="export_artifact_upload",
        uploaded_by=uploaded_by,
        retention_class="export_control",
        sensitivity="restricted",
        effective_date=effective_date,
        parse_status=parse_status,
        structured_fields=structured_fields,
    )
