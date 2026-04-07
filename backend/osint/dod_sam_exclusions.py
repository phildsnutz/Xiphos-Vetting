"""
DoD SAM.gov Exclusions (EPLS) Connector

Checks if a vendor is on the Excluded Parties List System (EPLS).
Uses the public SAM.gov API: https://api.sam.gov/entity-information/v3/exclusions

This is a primary sanctions/exclusions check. If the API is unreachable,
the connector returns an explicit availability finding instead of inventing data.

API docs: https://open.gsa.gov/api/entity-api/
"""

import os
import time
import urllib.parse
from datetime import datetime, timezone

from http_transport import curl_json_get

from . import EnrichmentResult, Finding

BASE = "https://api.sam.gov/entity-information/v4/exclusions"
# Use the same SAM API key as entity resolver (configured in docker-compose)
API_KEY = os.environ.get("SAM_GOV_API_KEY", os.environ.get("XIPHOS_SAM_API_KEY", ""))

USER_AGENT = "Xiphos-Vetting/2.1"
_RATE_LIMIT_UNTIL: str = ""
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("XIPHOS_DOD_SAM_EXCLUSIONS_TIMEOUT_SECONDS", "6"))
RESULT_PAGE_SIZE = int(os.environ.get("XIPHOS_DOD_SAM_EXCLUSIONS_PAGE_SIZE", "5"))


def _get_api_key() -> str:
    return (
        API_KEY
        or os.environ.get("XIPHOS_SAM_API_KEY", "")
        or os.environ.get("SAM_GOV_API_KEY", "")
        or os.environ.get("XIPHOS_SAM_GOV_API_KEY", "")
    )


def _parse_next_access_time(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace(" UTC", "")
    try:
        return datetime.strptime(normalized, "%Y-%b-%d %H:%M:%S%z")
    except Exception:
        return None


def _rate_limit_active() -> bool:
    until = _parse_next_access_time(_RATE_LIMIT_UNTIL)
    if until is None:
        return False
    return datetime.now(timezone.utc) < until.astimezone(timezone.utc)


def _mark_rate_limit(next_access_time: str = "") -> None:
    global _RATE_LIMIT_UNTIL
    _RATE_LIMIT_UNTIL = str(next_access_time or "").strip()


def _rate_limit_meta() -> dict:
    return {
        "status": 429,
        "throttled": True,
        "next_access_time": _RATE_LIMIT_UNTIL,
        "error": (
            f"SAM.gov exclusions rate limit reached. API access resumes at {_RATE_LIMIT_UNTIL}."
            if _RATE_LIMIT_UNTIL
            else "SAM.gov exclusions rate limit reached."
        ),
    }


def _build_exclusions_url(vendor_name: str, *, page_size: int | None = None) -> str:
    encoded = urllib.parse.quote(vendor_name)
    size = max(int(page_size or RESULT_PAGE_SIZE), 1)
    return f"{BASE}?exclusionName={encoded}&page=0&size={size}"


def _get(url: str, *, timeout_seconds: float = REQUEST_TIMEOUT_SECONDS) -> tuple[dict | None, dict]:
    """GET with optional API key and explicit status metadata."""
    if _rate_limit_active():
        return None, _rate_limit_meta()

    api_key = _get_api_key()
    if api_key:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}api_key={api_key}"

    headers = {
        "User-Agent": USER_AGENT,
    }
    try:
        payload, meta = curl_json_get(
            url,
            headers=headers,
            timeout_seconds=timeout_seconds,
        )
        if meta["status"] == 429:
            next_access_time = ""
            if isinstance(payload, dict):
                next_access_time = str(payload.get("nextAccessTime", "") or "")
            _mark_rate_limit(next_access_time)
            return payload, _rate_limit_meta()
        if meta["status"] >= 400:
            message = ""
            if isinstance(payload, dict):
                message = str(payload.get("message", "") or payload.get("description", "") or "")
            return payload, {
                "status": meta["status"],
                "throttled": False,
                "error": message or f"SAM.gov exclusions API returned HTTP {meta['status']}.",
            }
        if meta["status"] == 0:
            raise RuntimeError(meta["error"] or "curl transport returned no status.")
        return payload, {"status": meta["status"], "throttled": False, "error": ""}
    except Exception as exc:
        return None, {
            "status": 0,
            "throttled": False,
            "error": f"SAM.gov exclusions API unavailable: {exc}",
        }


    # _simulated_finding REMOVED: no fake/notional data in production code


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query SAM.gov EPLS for vendor exclusion status."""
    t0 = time.time()
    result = EnrichmentResult(source="dod_sam_exclusions", vendor_name=vendor_name)
    result.structured_fields = {}

    try:
        # Try to query the API
        url = _build_exclusions_url(vendor_name)
        data, meta = _get(url, timeout_seconds=REQUEST_TIMEOUT_SECONDS)

        api_available = data is not None

        if api_available and data:
            results = data.get("excludedEntity", data.get("results", []))

            if results:
                # Found exclusions
                for exc in results[:5]:
                    exc_name = exc.get("name", "")
                    exc_type = exc.get("exclusionType", "")
                    reason = exc.get("reason", "")
                    agency = exc.get("excludingAgency", "")
                    active_date = exc.get("activeDate", "")

                    result.findings.append(Finding(
                        source="dod_sam_exclusions",
                        category="exclusion",
                        title=f"DoD EPLS MATCH: {exc_name}",
                        detail=(
                            f"Type: {exc_type} | Reason: {reason} | "
                            f"Agency: {agency} | Active: {active_date}"
                        ),
                        severity="critical",
                        confidence=0.95,
                        url="https://sam.gov/content/exclusions",
                        raw_data=exc,
                    ))

                    result.risk_signals.append({
                        "signal": "dod_sam_exclusion",
                        "severity": "critical",
                        "detail": f"Excluded from federal contracts: {exc_type}",
                    })
            else:
                # API check succeeded, no match found
                result.findings.append(Finding(
                    source="dod_sam_exclusions",
                    category="clearance",
                    title="DoD EPLS: Vendor not on exclusions list",
                    detail=f"'{vendor_name}' verified not on DoD Excluded Parties List.",
                    severity="info",
                    confidence=0.95,
                ))

        else:
            result.structured_fields["sam_api_status"] = dict(meta)
            if meta.get("throttled"):
                detail = meta.get("error") or "SAM.gov exclusions lookup rate-limited."
                result.error = detail
                result.findings.append(Finding(
                    source="dod_sam_exclusions",
                    category="availability",
                    title="DoD EPLS: Unable to verify (rate limit reached)",
                    detail=detail,
                    severity="info",
                    confidence=1.0,
                    structured_fields=dict(meta),
                ))
            else:
                detail = (
                    str(meta.get("error") or "")
                    or f"Cannot reach SAM.gov Exclusions API. Recommendation: verify '{vendor_name}' manually at https://sam.gov/content/exclusions"
                )
                result.error = detail
                result.findings.append(Finding(
                    source="dod_sam_exclusions",
                    category="clearance",
                    title="DoD EPLS: Unable to verify (API unavailable)",
                    detail=detail,
                    severity="info",
                    confidence=0.3,
                    structured_fields=dict(meta),
                ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
