"""
Optional NVD product vulnerability overlay for supplier cyber-trust workflows.

This module intentionally does not turn Helios into a vulnerability management
tool. It adds a scoped, analyst-driven posture overlay when a user provides a
small set of supplier product or software references.

The overlay:
- looks up likely CPE matches for each supplied product term
- fetches CVE context for the strongest matching CPE names
- summarizes total / high / critical / KEV-linked CVE exposure
- stores the generated report in the secure artifact vault
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, UTC
from typing import Any

import requests

from artifact_vault import store_artifact


NVD_OVERLAY_ARTIFACT_TYPE = "nvd_overlay"

NVD_CPE_URL = "https://services.nvd.nist.gov/rest/json/cpes/2.0"
NVD_CVE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

TIMEOUT = 20
MAX_PRODUCT_TERMS = 8
MAX_CPE_MATCHES_PER_TERM = 3
MAX_CVE_PER_CPE = 20
MAX_TOP_CVES = 8

_WS_RE = re.compile(r"\s+")


def _headers() -> dict[str, str]:
    api_key = os.environ.get("XIPHOS_NVD_API_KEY") or os.environ.get("NVD_API_KEY") or ""
    if not api_key:
        return {}
    return {"apiKey": api_key}


def _normalize_term(value: object) -> str:
    text = _WS_RE.sub(" ", str(value or "").strip())
    return text[:120]


def _normalize_terms(product_terms: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for term in product_terms:
        cleaned = _normalize_term(term)
        key = cleaned.lower()
        if len(cleaned) < 2 or key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
        if len(normalized) >= MAX_PRODUCT_TERMS:
            break
    return normalized


def _request_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(url, params=params, headers=_headers(), timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _extract_cpe_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in payload.get("products") or []:
        if not isinstance(item, dict):
            continue
        cpe = item.get("cpe") if isinstance(item.get("cpe"), dict) else item
        if not isinstance(cpe, dict):
            continue
        cpe_name = str(cpe.get("cpeName") or cpe.get("criteria") or "").strip()
        titles = cpe.get("titles") if isinstance(cpe.get("titles"), list) else []
        title = ""
        for entry in titles:
            if isinstance(entry, dict) and str(entry.get("lang", "")).lower() == "en" and entry.get("title"):
                title = str(entry["title"]).strip()
                break
        if not title and titles:
            first = titles[0]
            if isinstance(first, dict):
                title = str(first.get("title") or "").strip()

        vendor = ""
        product = ""
        parts = cpe_name.split(":")
        if len(parts) >= 5:
            vendor = parts[3]
            product = parts[4]

        records.append(
            {
                "cpe_name": cpe_name,
                "title": title or cpe_name,
                "vendor": vendor.replace("_", " "),
                "product": product.replace("_", " "),
                "deprecated": bool(cpe.get("deprecated")),
                "last_modified": str(cpe.get("lastModified") or ""),
            }
        )
    return records


def _extract_cvss(cve: dict[str, Any]) -> tuple[float | None, str]:
    metrics = cve.get("metrics") if isinstance(cve.get("metrics"), dict) else {}
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cvss_data = entry.get("cvssData") if isinstance(entry.get("cvssData"), dict) else {}
            score = cvss_data.get("baseScore")
            severity = str(
                cvss_data.get("baseSeverity")
                or entry.get("baseSeverity")
                or ""
            ).strip().upper()
            try:
                numeric = float(score)
            except (TypeError, ValueError):
                numeric = None
            if numeric is not None or severity:
                return numeric, severity
    return None, ""


def _severity_label(score: float | None, severity: str) -> str:
    if severity:
        return severity.upper()
    if score is None:
        return "UNKNOWN"
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW"


def _extract_description(cve: dict[str, Any]) -> str:
    descriptions = cve.get("descriptions") if isinstance(cve.get("descriptions"), list) else []
    for entry in descriptions:
        if isinstance(entry, dict) and str(entry.get("lang", "")).lower() == "en" and entry.get("value"):
            return str(entry["value"]).strip()
    if descriptions and isinstance(descriptions[0], dict):
        return str(descriptions[0].get("value") or "").strip()
    return ""


def _extract_cves(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in payload.get("vulnerabilities") or []:
        cve = item.get("cve") if isinstance(item, dict) and isinstance(item.get("cve"), dict) else None
        if not cve:
            continue
        score, severity = _extract_cvss(cve)
        records.append(
            {
                "cve_id": str(cve.get("id") or "").strip(),
                "published": str(cve.get("published") or ""),
                "last_modified": str(cve.get("lastModified") or ""),
                "score": score,
                "severity": _severity_label(score, severity),
                "description": _extract_description(cve)[:280],
                "kev_date": str(cve.get("cisaExploitAdd") or ""),
                "detail_url": f"https://nvd.nist.gov/vuln/detail/{cve.get('id', '')}",
            }
        )
    return records


def _fetch_cpe_matches(term: str) -> list[dict[str, Any]]:
    payload = _request_json(
        NVD_CPE_URL,
        {
            "keywordSearch": term,
            "resultsPerPage": MAX_CPE_MATCHES_PER_TERM,
        },
    )
    records = _extract_cpe_records(payload)
    return [record for record in records if record.get("cpe_name")][:MAX_CPE_MATCHES_PER_TERM]


def _fetch_cves_for_cpe(cpe_name: str) -> list[dict[str, Any]]:
    payload = _request_json(
        NVD_CVE_URL,
        {
            "cpeName": cpe_name,
            "resultsPerPage": MAX_CVE_PER_CPE,
        },
    )
    return _extract_cves(payload)


def build_nvd_overlay(vendor_name: str, product_terms: list[str]) -> dict[str, Any]:
    terms = _normalize_terms(product_terms)
    if not terms:
        raise ValueError("At least one product or software reference is required")

    product_summaries: list[dict[str, Any]] = []
    unique_cves: dict[str, dict[str, Any]] = {}
    total_cpe_matches = 0

    for term in terms:
        cpe_matches = _fetch_cpe_matches(term)
        total_cpe_matches += len(cpe_matches)
        term_cves: dict[str, dict[str, Any]] = {}

        for cpe in cpe_matches:
            for cve in _fetch_cves_for_cpe(cpe["cpe_name"]):
                if not cve.get("cve_id"):
                    continue
                term_cves[cve["cve_id"]] = cve
                unique_cves[cve["cve_id"]] = cve

        ordered_term_cves = sorted(
            term_cves.values(),
            key=lambda item: (
                item.get("score") or 0.0,
                item.get("published") or "",
            ),
            reverse=True,
        )
        product_summaries.append(
            {
                "term": term,
                "matched_cpes_count": len(cpe_matches),
                "matched_cpes": cpe_matches,
                "cve_count": len(term_cves),
                "high_or_critical_cves": sum(
                    1 for item in term_cves.values() if item.get("severity") in {"HIGH", "CRITICAL"}
                ),
                "kev_flagged_cves": sum(1 for item in term_cves.values() if item.get("kev_date")),
                "top_cves": ordered_term_cves[:3],
            }
        )

    ordered_cves = sorted(
        unique_cves.values(),
        key=lambda item: (
            item.get("score") or 0.0,
            item.get("published") or "",
        ),
        reverse=True,
    )
    latest_published = max((item.get("published") or "" for item in unique_cves.values()), default="")
    summary = {
        "vendor_name": vendor_name,
        "product_terms": terms,
        "matched_terms": sum(1 for item in product_summaries if item["matched_cpes_count"] > 0),
        "total_cpe_matches": total_cpe_matches,
        "unique_cve_count": len(unique_cves),
        "high_or_critical_cve_count": sum(
            1 for item in unique_cves.values() if item.get("severity") in {"HIGH", "CRITICAL"}
        ),
        "critical_cve_count": sum(1 for item in unique_cves.values() if item.get("severity") == "CRITICAL"),
        "kev_flagged_cve_count": sum(1 for item in unique_cves.values() if item.get("kev_date")),
        "latest_published": latest_published,
    }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "vendor_name": vendor_name,
        "product_terms": terms,
        "summary": summary,
        "product_summaries": product_summaries,
        "top_cves": ordered_cves[:MAX_TOP_CVES],
        "references": [
            {
                "title": "NVD CPE API",
                "url": "https://nvd.nist.gov/developers/products",
            },
            {
                "title": "NVD CVE API",
                "url": "https://nvd.nist.gov/developers/vulnerabilities",
            },
        ],
    }


def create_nvd_overlay_artifact(
    case_id: str,
    vendor_name: str,
    product_terms: list[str],
    *,
    uploaded_by: str = "",
    notes: str = "",
    effective_date: str | None = None,
) -> dict:
    payload = build_nvd_overlay(vendor_name, product_terms)
    structured_fields = {
        "summary": payload["summary"],
        "product_terms": payload["product_terms"],
        "notes": str(notes or "").strip(),
    }
    content = json.dumps(payload, sort_keys=True).encode("utf-8")
    filename = f"nvd-overlay-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}.json"
    return store_artifact(
        case_id,
        NVD_OVERLAY_ARTIFACT_TYPE,
        filename,
        content,
        source_system="nvd_overlay",
        uploaded_by=uploaded_by,
        retention_class="cyber_posture",
        sensitivity="controlled",
        effective_date=effective_date,
        parse_status="parsed",
        structured_fields=structured_fields,
    )
