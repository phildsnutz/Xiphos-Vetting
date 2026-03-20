"""Deterministic normalization of enrichment findings into reusable case events."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_EVENT_TYPES = {
    "lawsuit",
    "debarment",
    "terminated_registration",
    "ownership_change",
    "executive_risk",
    "sanctions_hit",
}

_STATUS_VALUES = {"active", "historical", "resolved"}
_JURISDICTION_BY_SOURCE = {
    "courtlistener": "US",
    "trade_csl": "US",
    "dod_sam_exclusions": "US",
    "sam_gov": "US",
    "usaspending": "US",
    "fpds_contracts": "US",
    "ofac_sdn": "US",
    "fara": "US",
    "sec_edgar": "US",
    "sec_xbrl": "US",
    "epa_echo": "US",
    "osha_safety": "US",
    "fdic_bankfind": "US",
    "worldbank_debarred": "MULTI",
    "un_sanctions": "UN",
    "eu_sanctions": "EU",
    "uk_hmt_sanctions": "UK",
    "uk_companies_house": "UK",
    "opencorporates": "GLOBAL",
    "gleif_lei": "GLOBAL",
    "gdelt_media": "GLOBAL",
    "google_news": "GLOBAL",
}
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean(value: Any, max_len: int = 240) -> str:
    text = _WHITESPACE_RE.sub(" ", str(value or "")).strip()
    return text[:max_len]


def compute_report_hash(report: dict | None) -> str:
    """Stable fingerprint for the substance of an enrichment report.

    Ignores transient timing/fetch metadata so cached summaries/events survive
    harmless reruns with the same substantive findings.
    """
    if not isinstance(report, dict):
        return ""

    findings = []
    for finding in report.get("findings", []) or []:
        findings.append({
            "finding_id": finding.get("finding_id") or _stable_finding_id(report.get("vendor_name", ""), finding),
            "source": finding.get("source", ""),
            "category": finding.get("category", ""),
            "title": _clean(finding.get("title", ""), 280),
            "detail": _clean(finding.get("detail", ""), 600),
            "severity": finding.get("severity", "info"),
            "url": finding.get("url", ""),
        })

    payload = {
        "vendor_name": report.get("vendor_name", ""),
        "country": report.get("country", ""),
        "overall_risk": report.get("overall_risk", ""),
        "summary": {
            "findings_total": (report.get("summary") or {}).get("findings_total", 0),
            "critical": (report.get("summary") or {}).get("critical", 0),
            "high": (report.get("summary") or {}).get("high", 0),
            "medium": (report.get("summary") or {}).get("medium", 0),
            "connectors_run": (report.get("summary") or {}).get("connectors_run", 0),
            "connectors_with_data": (report.get("summary") or {}).get("connectors_with_data", 0),
        },
        "identifiers": report.get("identifiers", {}),
        "findings": findings,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _stable_finding_id(vendor_name: str, finding: dict) -> str:
    key = "|".join([
        _clean(vendor_name, 120).lower(),
        _clean(finding.get("source", ""), 80).lower(),
        _clean(finding.get("category", ""), 80).lower(),
        _clean(finding.get("title", ""), 280).lower(),
        _clean(finding.get("detail", ""), 500).lower(),
        _clean(finding.get("url", ""), 240).lower(),
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _extract_date_range(text: str) -> dict[str, str | None]:
    dates = _DATE_RE.findall(text)
    if dates:
        start = dates[0]
        end = dates[-1]
        return {"start": start, "end": end if end != start else start}

    years = [match.group(0) for match in _YEAR_RE.finditer(text)]
    if years:
        start = years[0]
        end = years[-1]
        return {"start": f"{start}-01-01", "end": f"{end}-12-31" if end != start else f"{start}-12-31"}

    return {"start": None, "end": None}


def _infer_status(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("terminated", "resolved", "settled", "dismissed", "closed", "expired", "former", "ended")):
        return "resolved"
    if any(token in lowered for token in ("historical", "previously", "formerly", "past", "archived")):
        return "historical"
    return "active"


def _infer_jurisdiction(source: str, text: str, country: str) -> str:
    lowered = text.lower()
    if "united kingdom" in lowered or "uk " in lowered or lowered.endswith(" uk"):
        return "UK"
    if "european union" in lowered or " eu " in lowered:
        return "EU"
    if "united states" in lowered or "u.s." in lowered or " us " in lowered:
        return "US"
    return _JURISDICTION_BY_SOURCE.get(source, country or "GLOBAL")


def _is_negative_result(finding: dict) -> bool:
    """Return True if the finding is a clear/negative result (no match found)."""
    severity = (finding.get("severity") or "").lower()
    text = f"{finding.get('title', '')} {finding.get('detail', '')}".lower()

    # INFO severity with negative language = clean check, not a real finding
    if severity == "info" and any(neg in text for neg in (
        "not found", "no match", "no pep", "no sanctions", "no debarment",
        "not configured", "not on", "clear", "no active", "no known",
        "no osha", "no products associated", "unable to verify",
        "api key not con", "integration is not",
        "no articles found", "no inspection records",
        "not found among", "no world bank",
    )):
        return True

    # LOW severity with missing data = informational, not adverse
    if severity in ("info", "low") and any(neg in text for neg in (
        "set xiphos_", "environment vari", "register for",
        "cannot reach", "api unavailable",
    )):
        return True

    return False


def _event_type_for_finding(finding: dict) -> str | None:
    source = (finding.get("source") or "").lower()
    category = (finding.get("category") or "").lower()
    text = f"{finding.get('title', '')} {finding.get('detail', '')}".lower()

    # Skip negative/clean results entirely -- these are NOT events
    if _is_negative_result(finding):
        return None

    if source == "courtlistener" or any(token in text for token in ("lawsuit", "complaint", "litigation", "docket", "civil action", "sued", "settlement")):
        return "lawsuit"

    if source in {"worldbank_debarred", "dod_sam_exclusions"} or "debar" in category or any(token in text for token in ("debarred", "suspension", "exclusion list", "excluded from")):
        return "debarment"

    if source in {"trade_csl", "ofac_sdn", "un_sanctions", "eu_sanctions", "uk_hmt_sanctions"} or "sanction" in category or any(token in text for token in ("sanction", "sdn", "blocked property", "restricted party")):
        return "sanctions_hit"

    if source == "fara" and any(token in text for token in ("terminated", "termination", "registration ended", "registration terminated")):
        return "terminated_registration"

    if source in {"sec_edgar", "gleif_lei", "opencorporates", "uk_companies_house", "sam_gov"} and any(token in text for token in ("acquired", "merger", "merged", "ownership", "beneficial owner", "parent company", "subsidiary", "shareholder", "controller", "ultimate owner")):
        return "ownership_change"

    if any(token in text for token in ("chief executive", "ceo", "director", "officer", "pep", "politically exposed", "executive", "board member")):
        return "executive_risk"

    return None


def _event_confidence(finding: dict, event_type: str) -> float:
    base = float(finding.get("confidence") or 0.55)
    if event_type in {"sanctions_hit", "debarment"}:
        base = max(base, 0.82)
    elif event_type == "lawsuit":
        base = max(base, 0.74)
    elif event_type in {"ownership_change", "executive_risk", "terminated_registration"}:
        base = max(base, 0.68)
    return max(0.5, min(base, 0.98))


def _normalize_event(case_id: str, vendor_name: str, country: str, finding: dict, event_type: str, method: str = "deterministic") -> dict:
    finding_id = finding.get("finding_id") or _stable_finding_id(vendor_name, finding)
    text = _clean(f"{finding.get('title', '')} {finding.get('detail', '')}", 900)
    return {
        "case_id": case_id,
        "finding_id": finding_id,
        "event_type": event_type if event_type in _EVENT_TYPES else "executive_risk",
        "subject": _clean(vendor_name, 160),
        "date_range": _extract_date_range(text),
        "jurisdiction": _infer_jurisdiction(finding.get("source", ""), text, country),
        "status": _infer_status(text),
        "confidence": _event_confidence(finding, event_type),
        "source_refs": [ref for ref in (finding_id, finding.get("url", "")) if ref],
        "source_finding_ids": [finding_id],
        "connector": finding.get("source", ""),
        "normalization_method": method,
        "severity": finding.get("severity", "info"),
        "title": _clean(finding.get("title", ""), 200),
        "assessment": _clean(finding.get("detail") or finding.get("title", ""), 320),
    }


def extract_case_events(case_id: str, vendor_name: str, report: dict) -> list[dict]:
    """Convert enrichment findings into reusable normalized case events."""
    if not isinstance(report, dict):
        return []

    country = report.get("country", "") or ""
    findings = report.get("findings", []) or []
    events: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for finding in findings:
        event_type = _event_type_for_finding(finding)
        if not event_type:
            continue
        normalized = _normalize_event(case_id, vendor_name, country, finding, event_type)
        key = (normalized["finding_id"], normalized["event_type"])
        if key in seen:
            continue
        seen.add(key)
        events.append(normalized)

    events.sort(key=lambda event: (event["status"] != "active", -event["confidence"], event["event_type"]))
    return events
