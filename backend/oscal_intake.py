"""
Secure intake helpers for customer-provided OSCAL artifacts.

v1 accepts OSCAL JSON for System Security Plans (SSP) and
Plan of Action & Milestones (POA&M) exports, stores the raw artifact in the
secure vault, and extracts a small summary Helios can use for CMMC workflows:

- document type and system name
- control-family highlights
- open remediation item counts
- top remediation items with due dates when present
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from artifact_vault import store_artifact


OSCAL_ARTIFACT_TYPES = {
    "oscal_ssp": "OSCAL SSP",
    "oscal_poam": "OSCAL POA&M",
}

_CONTROL_ID_RE = re.compile(r"\b([a-z]{2})-\d+[a-z0-9.-]*\b", re.IGNORECASE)
_STATUS_OPEN = {"open", "ongoing", "in_progress", "planned", "active", "not_satisfied"}
_STATUS_CLOSED = {"closed", "complete", "completed", "resolved", "satisfied"}


def _normalize_status(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _extract_control_families(node: Any, counter: Counter[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = str(key).lower()
            if lowered in {"control-id", "control_id", "control-ids", "control_ids", "implemented-requirement-id"}:
                values = value if isinstance(value, list) else [value]
                for item in values:
                    match = _CONTROL_ID_RE.search(str(item or ""))
                    if match:
                        counter[match.group(1).upper()] += 1
            _extract_control_families(value, counter)
    elif isinstance(node, list):
        for item in node:
            _extract_control_families(item, counter)


def _find_first_string(node: dict[str, Any], *paths: tuple[str, ...]) -> str:
    for path in paths:
        current: Any = node
        for segment in path:
            if not isinstance(current, dict) or segment not in current:
                current = None
                break
            current = current[segment]
        if isinstance(current, str) and current.strip():
            return current.strip()
    return ""


def _parse_poam_items(document: dict[str, Any]) -> tuple[int, int, list[dict[str, Any]]]:
    items = document.get("poam-items") or document.get("poam_items") or []
    if not isinstance(items, list):
        return 0, 0, []

    open_count = 0
    closed_count = 0
    highlights: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        status = _normalize_status(
            item.get("status")
            or item.get("state")
            or _find_first_string(item, ("status", "state"), ("metadata", "state"))
        )
        title = str(
            item.get("title")
            or item.get("description")
            or item.get("remarks")
            or item.get("id")
            or "Untitled remediation item"
        ).strip()
        due_date = _find_first_string(
            item,
            ("deadline",),
            ("due-date",),
            ("due_date",),
            ("scheduled-completion-date",),
            ("scheduled_completion_date",),
        )

        is_closed = status in _STATUS_CLOSED
        is_open = status in _STATUS_OPEN or not is_closed
        if is_closed:
            closed_count += 1
        elif is_open:
            open_count += 1

        if is_open and len(highlights) < 5:
            highlights.append(
                {
                    "title": title[:140],
                    "status": status or "open",
                    "due_date": due_date,
                }
            )

    return open_count, closed_count, highlights


def _extract_summary(document_type: str, document: dict[str, Any]) -> dict[str, Any]:
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    system_info = document.get("system-characteristics") if isinstance(document.get("system-characteristics"), dict) else {}
    system_name = (
        _find_first_string(
            document,
            ("system-characteristics", "system-name"),
            ("system_characteristics", "system_name"),
            ("import-profile", "title"),
        )
        or _find_first_string(metadata, ("title",), ("system-name",))
        or "Unnamed system"
    )

    family_counter: Counter[str] = Counter()
    _extract_control_families(document, family_counter)
    control_family_highlights = [
        {"family": family, "count": count}
        for family, count in family_counter.most_common(5)
    ]

    open_items = 0
    closed_items = 0
    remediation_highlights: list[dict[str, Any]] = []
    if document_type == "oscal_poam":
        open_items, closed_items, remediation_highlights = _parse_poam_items(document)

    return {
        "document_type": document_type,
        "document_label": OSCAL_ARTIFACT_TYPES.get(document_type, document_type.replace("_", " ")),
        "system_name": system_name,
        "document_uuid": str(metadata.get("uuid") or document.get("uuid") or "").strip(),
        "last_modified": str(metadata.get("last-modified") or metadata.get("last_modified") or "").strip(),
        "control_family_highlights": control_family_highlights,
        "total_control_references": sum(family_counter.values()),
        "open_poam_items": open_items,
        "closed_poam_items": closed_items,
        "remediation_highlights": remediation_highlights,
        "has_security_sensitivity_level": bool(system_info.get("security-sensitivity-level") or system_info.get("security_sensitivity_level")),
    }


def ingest_oscal_artifact(
    case_id: str,
    filename: str,
    content: bytes,
    *,
    uploaded_by: str = "",
    effective_date: str | None = None,
    notes: str = "",
) -> dict:
    payload = json.loads(content.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("OSCAL upload must be a JSON object")

    if isinstance(payload.get("system-security-plan"), dict):
        document_type = "oscal_ssp"
        document = payload["system-security-plan"]
    elif isinstance(payload.get("plan-of-action-and-milestones"), dict):
        document_type = "oscal_poam"
        document = payload["plan-of-action-and-milestones"]
    else:
        raise ValueError("Unsupported OSCAL document type")

    summary = _extract_summary(document_type, document)
    structured_fields = {
        "summary": summary,
        "notes": str(notes or "").strip(),
        "parse_mode": "json",
    }

    return store_artifact(
        case_id,
        document_type,
        filename,
        content,
        source_system="oscal_upload",
        uploaded_by=uploaded_by,
        retention_class="cyber_attestation",
        sensitivity="restricted",
        effective_date=effective_date,
        parse_status="parsed",
        structured_fields=structured_fields,
    )
