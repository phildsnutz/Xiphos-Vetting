"""
Secure intake helpers for customer-provided SPRS exports.

v1 accepts customer-controlled CSV or JSON exports, stores the raw artifact in
the secure vault, and extracts a small summary Helios can use for supplier
cyber-trust workflows:

- matched supplier name
- SPRS / assessment score
- assessment date
- status
- current CMMC level
- POA&M hint
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from artifact_vault import store_artifact


SPRS_ARTIFACT_TYPE = "sprs_export"

_NORMALIZE_KEY_RE = re.compile(r"[^a-z0-9]+")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

_SUPPLIER_KEYS = {
    "supplier_name",
    "vendor_name",
    "entity_name",
    "contractor_name",
    "company_name",
    "name",
}
_SCORE_KEYS = {
    "sprs_score",
    "score",
    "assessment_score",
    "basic_assessment_score",
    "supplier_score",
}
_DATE_KEYS = {
    "assessment_date",
    "submitted_date",
    "score_date",
    "date",
    "assessment_submitted_date",
}
_STATUS_KEYS = {
    "status",
    "assessment_status",
    "cmmc_status",
    "result",
}
_LEVEL_KEYS = {
    "cmmc_level",
    "current_cmmc_level",
    "level",
    "certification_level",
}
_POAM_KEYS = {
    "poam",
    "poam_active",
    "has_poam",
    "poam_status",
    "plan_of_action",
}


def _normalize_key(value: object) -> str:
    return _NORMALIZE_KEY_RE.sub("_", str(value or "").strip().lower()).strip("_")


def _normalize_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _parse_number(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = _NUMBER_RE.search(text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _parse_bool(value: object) -> bool | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"true", "yes", "y", "1", "active", "open"}:
        return True
    if text in {"false", "no", "n", "0", "inactive", "closed", "none"}:
        return False
    return None


def _coerce_rows(filename: str, content: bytes) -> list[dict[str, Any]]:
    name = filename.lower()
    if name.endswith(".json"):
        payload = json.loads(content.decode("utf-8"))
        if isinstance(payload, dict):
            if isinstance(payload.get("records"), list):
                payload = payload["records"]
            else:
                payload = [payload]
        rows: list[dict[str, Any]] = []
        for item in payload if isinstance(payload, list) else []:
            if isinstance(item, dict):
                rows.append({_normalize_key(key): value for key, value in item.items()})
        return rows

    text = content.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        rows.append({_normalize_key(key): value for key, value in row.items() if key})
    return rows


def _extract_summary(rows: list[dict[str, Any]], *, vendor_name: str) -> dict[str, Any]:
    normalized_vendor = _normalize_name(vendor_name)
    chosen: dict[str, Any] | None = None
    for row in rows:
        supplier_name = next((row[key] for key in _SUPPLIER_KEYS if key in row and row[key]), "")
        if supplier_name and _normalize_name(supplier_name) == normalized_vendor:
            chosen = row
            break
    if chosen is None and rows:
        chosen = rows[0]
    chosen = chosen or {}

    supplier_name = next((chosen[key] for key in _SUPPLIER_KEYS if key in chosen and chosen[key]), vendor_name)
    score_value = next((_parse_number(chosen[key]) for key in _SCORE_KEYS if key in chosen and chosen[key] not in (None, "")), None)
    date_value = next((str(chosen[key]).strip() for key in _DATE_KEYS if key in chosen and chosen[key]), "")
    status_value = next((str(chosen[key]).strip() for key in _STATUS_KEYS if key in chosen and chosen[key]), "")
    level_value = next((_parse_number(chosen[key]) for key in _LEVEL_KEYS if key in chosen and chosen[key] not in (None, "")), None)
    poam_value = next((_parse_bool(chosen[key]) for key in _POAM_KEYS if key in chosen), None)

    return {
        "vendor_name": vendor_name,
        "matched_supplier_name": str(supplier_name or vendor_name).strip(),
        "matched_exact_vendor": _normalize_name(supplier_name) == normalized_vendor if supplier_name else False,
        "assessment_score": score_value,
        "assessment_date": date_value,
        "status": status_value,
        "current_cmmc_level": int(level_value) if level_value is not None else None,
        "poam_active": poam_value,
        "record_count": len(rows),
        "available_fields": sorted(chosen.keys()),
    }


def ingest_sprs_export(
    case_id: str,
    vendor_name: str,
    filename: str,
    content: bytes,
    *,
    uploaded_by: str = "",
    effective_date: str | None = None,
    notes: str = "",
) -> dict:
    rows = _coerce_rows(filename, content)
    summary = _extract_summary(rows, vendor_name=vendor_name)
    structured_fields = {
        "summary": summary,
        "notes": str(notes or "").strip(),
        "record_count": len(rows),
        "parse_mode": "json" if filename.lower().endswith(".json") else "csv",
    }
    parse_status = "parsed" if rows else "stored"

    return store_artifact(
        case_id,
        SPRS_ARTIFACT_TYPE,
        filename,
        content,
        source_system="sprs_import",
        uploaded_by=uploaded_by,
        retention_class="cyber_attestation",
        sensitivity="restricted",
        effective_date=effective_date,
        parse_status=parse_status,
        structured_fields=structured_fields,
    )
