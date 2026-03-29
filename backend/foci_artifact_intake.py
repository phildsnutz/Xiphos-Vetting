"""
Secure intake helpers for customer-provided FOCI artifacts.

These uploads are customer-controlled records that rarely appear in public
registries: Form 328 filings, ownership charts, cap tables, board/KMP rosters,
and mitigation instruments. v1 stores the raw artifact in the secure vault and
extracts lightweight hints Helios can use for defense-counterparty trust work.
"""

from __future__ import annotations

import re
from typing import Any

from artifact_vault import store_artifact


SUPPORTED_FOCI_ARTIFACT_TYPES = {
    "foci_form_328": "Form 328 / foreign interests certificate",
    "foci_ownership_chart": "Ownership chart",
    "foci_cap_table_or_stock_ledger": "Cap table / stock ledger",
    "foci_kmp_or_board_list": "KMP / board list",
    "foci_mitigation_instrument": "Mitigation instrument",
    "foci_supporting_memo": "FOCI supporting memo",
}

_PERCENT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?%")
_FOREIGN_INFLUENCE_RE = re.compile(
    r"\bforeign ownership\b|\bforeign control\b|\bforeign influence\b|\bforeign interest(?:s)?\b|"
    r"\bbeneficial owner(?:ship)?\b|\bforeign affiliate\b|\bforeign parent\b|\bforeign person\b",
    re.IGNORECASE,
)
_GOVERNMENT_AFFILIATION_RE = re.compile(
    r"\bstate[- ]owned\b|\bgovernment[- ]owned\b|\bsovereign\b|\bministry\b|"
    r"\bstate enterprise\b|\bgovernment interest\b",
    re.IGNORECASE,
)
_GOVERNANCE_CONTROL_RE = re.compile(
    r"\bboard observer\b|\bboard seat\b|\bveto right(?:s)?\b|\bnegative control\b|"
    r"\breserved matter(?:s)?\b|\bspecial governance\b",
    re.IGNORECASE,
)
_CLEARANCE_RE = re.compile(
    r"\bFCL\b|\bfacility clearance\b|\bDCSA\b|\bDSS\b|\bNISPOM\b|\bsecurity clearance\b",
    re.IGNORECASE,
)

_MITIGATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SSA", re.compile(r"\bSSA\b|\bspecial security agreement\b", re.IGNORECASE)),
    ("SCA", re.compile(r"\bSCA\b|\bsecurity control agreement\b", re.IGNORECASE)),
    ("PROXY", re.compile(r"\bproxy agreement\b", re.IGNORECASE)),
    ("VOTING_TRUST", re.compile(r"\bvoting trust\b", re.IGNORECASE)),
    ("BOARD_RESOLUTION", re.compile(r"\bboard resolution\b", re.IGNORECASE)),
]


def _extract_text_hints(content: bytes) -> dict[str, Any]:
    text = content[:75_000].decode("utf-8", errors="ignore")
    percent_mentions = []
    for match in _PERCENT_RE.finditer(text):
        token = match.group(0)
        try:
            percent_mentions.append(float(token.rstrip("%")))
        except ValueError:
            continue

    mitigation_tokens = [
        label
        for label, pattern in _MITIGATION_PATTERNS
        if pattern.search(text)
    ]
    max_percent = max(percent_mentions) if percent_mentions else None
    return {
        "ownership_percent_mentions": percent_mentions[:8],
        "max_ownership_percent_mention": max_percent,
        "mitigation_tokens": mitigation_tokens,
        "contains_foreign_influence_terms": bool(_FOREIGN_INFLUENCE_RE.search(text)),
        "contains_government_affiliation_terms": bool(_GOVERNMENT_AFFILIATION_RE.search(text)),
        "contains_governance_control_terms": bool(_GOVERNANCE_CONTROL_RE.search(text)),
        "contains_clearance_terms": bool(_CLEARANCE_RE.search(text)),
    }


def ingest_foci_artifact(
    case_id: str,
    artifact_type: str,
    filename: str,
    content: bytes,
    *,
    uploaded_by: str = "",
    effective_date: str | None = None,
    notes: str = "",
    declared_foreign_owner: str = "",
    declared_foreign_country: str = "",
    declared_foreign_ownership_pct: str = "",
    declared_mitigation_status: str = "",
    declared_mitigation_type: str = "",
) -> dict:
    if artifact_type not in SUPPORTED_FOCI_ARTIFACT_TYPES:
        raise ValueError(f"Unsupported FOCI artifact type: {artifact_type}")

    hints = _extract_text_hints(content)
    structured_fields = {
        "artifact_label": SUPPORTED_FOCI_ARTIFACT_TYPES[artifact_type],
        "notes": str(notes or "").strip(),
        "declared_foreign_owner": str(declared_foreign_owner or "").strip(),
        "declared_foreign_country": str(declared_foreign_country or "").strip().upper(),
        "declared_foreign_ownership_pct": str(declared_foreign_ownership_pct or "").strip(),
        "declared_mitigation_status": str(declared_mitigation_status or "").strip().upper(),
        "declared_mitigation_type": str(declared_mitigation_type or "").strip().upper(),
        **hints,
    }
    parse_status = "parsed" if any(
        [
            structured_fields["declared_foreign_owner"],
            structured_fields["declared_foreign_country"],
            structured_fields["declared_foreign_ownership_pct"],
            structured_fields["declared_mitigation_status"],
            structured_fields["declared_mitigation_type"],
            structured_fields["ownership_percent_mentions"],
            structured_fields["mitigation_tokens"],
            structured_fields["contains_foreign_influence_terms"],
            structured_fields["contains_government_affiliation_terms"],
            structured_fields["contains_governance_control_terms"],
            structured_fields["contains_clearance_terms"],
        ]
    ) else "stored"

    return store_artifact(
        case_id,
        artifact_type,
        filename,
        content,
        source_system="foci_artifact_upload",
        uploaded_by=uploaded_by,
        retention_class="counterparty_trust",
        sensitivity="restricted",
        effective_date=effective_date,
        parse_status=parse_status,
        structured_fields=structured_fields,
    )
