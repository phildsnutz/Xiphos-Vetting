"""Vehicle-intelligence dossier support built from replayable archive and protest fixtures."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from osint.contract_opportunities_archive_fixture import enrich as archive_fixture_enrich
from osint.contract_opportunities_public import enrich as contract_opportunities_public_enrich
from osint.contract_vehicle_wayback import enrich as contract_vehicle_wayback_enrich
from osint.gao_bid_protests_fixture import enrich as gao_fixture_enrich
from osint.gao_bid_protests_public import enrich as gao_public_enrich
from osint.public_html_contract_vehicle import enrich as public_html_contract_vehicle_enrich
from osint.usaspending_vehicle_live import enrich as usaspending_vehicle_live_enrich


SUPPORT_CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "vehicle_intelligence"
    / "vehicle_support_catalog.json"
)


def _seed_metadata(vendor: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(vendor, dict):
        return {}
    seed_metadata: dict[str, Any] = {}
    if isinstance(vendor.get("seed_metadata"), dict):
        seed_metadata.update(vendor.get("seed_metadata") or {})
    vendor_input = vendor.get("vendor_input") if isinstance(vendor.get("vendor_input"), dict) else {}
    nested = vendor_input.get("seed_metadata") if isinstance(vendor_input.get("seed_metadata"), dict) else {}
    seed_metadata.update(nested)
    return {
        str(key): value
        for key, value in seed_metadata.items()
        if not str(key).startswith("__") and value not in (None, "", [])
    }


def _support_vehicle_name(vehicle_name: str, vendor: dict[str, Any] | None) -> str:
    seed_metadata = _seed_metadata(vendor)
    explicit = seed_metadata.get("vehicle_intelligence_vehicle") or seed_metadata.get("contract_vehicle_name")
    resolved = str(explicit or vehicle_name or "").strip()
    return resolved


_PUBLIC_HTML_VEHICLE_KEYS = {
    "contract_vehicle_page",
    "contract_vehicle_pages",
    "contract_vehicle_public_html_page",
    "contract_vehicle_public_html_pages",
    "contract_vehicle_public_html_fixture_page",
    "contract_vehicle_public_html_fixture_pages",
}
_WAYBACK_VEHICLE_KEYS = {
    "contract_vehicle_archive_url",
    "contract_vehicle_archive_urls",
    "contract_vehicle_archive_seed_url",
    "contract_vehicle_archive_seed_urls",
    "contract_vehicle_wayback_fixture",
    "contract_vehicle_wayback_fixture_path",
}
_GAO_PUBLIC_KEYS = {
    "gao_public_url",
    "gao_public_urls",
    "gao_docket_url",
    "gao_docket_urls",
    "gao_decision_url",
    "gao_decision_urls",
    "gao_bid_protest_url",
    "gao_bid_protest_urls",
    "gao_public_html_fixture_page",
    "gao_public_html_fixture_pages",
}
_CONTRACT_OPPORTUNITY_NOTICE_KEYS = {
    "contract_opportunity_notice_url",
    "contract_opportunity_notice_urls",
    "contract_opportunity_notice_page",
    "contract_opportunity_notice_pages",
    "contract_opportunity_notice_fixture_page",
    "contract_opportunity_notice_fixture_pages",
}
_LIVE_VEHICLE_KEYS = {
    "contract_vehicle_live_fixture",
    "contract_vehicle_live_fixture_path",
    "contract_vehicle_live_fixture_vehicle",
    "contract_vehicle_live_limit",
    "contract_vehicle_live_include_subs",
}


def _normalize_vehicle_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _catalog_seed_metadata(vehicle_name: str) -> dict[str, Any]:
    if not SUPPORT_CATALOG_PATH.exists():
        return {}
    try:
        payload = json.loads(SUPPORT_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    normalized = _normalize_vehicle_name(vehicle_name)
    for record in payload.get("vehicles", []) or []:
        if not isinstance(record, dict):
            continue
        names = [record.get("vehicle_name", ""), *(record.get("aliases") or [])]
        if any(_normalize_vehicle_name(name) == normalized for name in names):
            seed_metadata = record.get("seed_metadata")
            return dict(seed_metadata) if isinstance(seed_metadata, dict) else {}
    return {}


def _merged_seed_metadata(vehicle_name: str, vendor: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    merged.update(_catalog_seed_metadata(vehicle_name))
    merged.update(_seed_metadata(vendor))
    return merged


def _public_html_vehicle_ids(seed_metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in seed_metadata.items()
        if key in _PUBLIC_HTML_VEHICLE_KEYS and value not in (None, "", [])
    }


def _wayback_vehicle_ids(seed_metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in seed_metadata.items()
        if key in _WAYBACK_VEHICLE_KEYS and value not in (None, "", [])
    }


def _gao_public_ids(seed_metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in seed_metadata.items()
        if key in _GAO_PUBLIC_KEYS and value not in (None, "", [])
    }


def _contract_opportunity_notice_ids(seed_metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in seed_metadata.items()
        if key in _CONTRACT_OPPORTUNITY_NOTICE_KEYS and value not in (None, "", [])
    }


def _live_vehicle_ids(seed_metadata: dict[str, Any], vendor: dict[str, Any] | None) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in seed_metadata.items()
        if key in _LIVE_VEHICLE_KEYS and value not in (None, "", [])
    }
    if isinstance(vendor, dict):
        prime_name = str(vendor.get("name") or "").strip()
        if prime_name:
            payload["prime_contractor_name"] = prime_name
    return payload


def _finding_to_dict(finding: Any) -> dict[str, Any]:
    return {
        "source": getattr(finding, "source", ""),
        "category": getattr(finding, "category", ""),
        "title": getattr(finding, "title", ""),
        "detail": getattr(finding, "detail", ""),
        "severity": getattr(finding, "severity", "info"),
        "confidence": float(getattr(finding, "confidence", 0.0) or 0.0),
        "url": getattr(finding, "url", ""),
        "raw_data": dict(getattr(finding, "raw_data", {}) or {}),
        "source_class": getattr(finding, "source_class", ""),
        "authority_level": getattr(finding, "authority_level", ""),
        "access_model": getattr(finding, "access_model", ""),
        "structured_fields": dict(getattr(finding, "structured_fields", {}) or {}),
    }


def _result_relationships(results: list[Any]) -> list[dict[str, Any]]:
    relationships = []
    for result in results:
        for relationship in getattr(result, "relationships", []) or []:
            if not isinstance(relationship, dict):
                continue
            relationships.append(dict(relationship))
    return relationships


def _result_observed_vendors(results: list[Any]) -> list[dict[str, Any]]:
    observed_by_name: dict[str, dict[str, Any]] = {}
    for result in results:
        structured = getattr(result, "structured_fields", {}) or {}
        for row in structured.get("observed_vendors") or []:
            if not isinstance(row, dict):
                continue
            vendor_name = str(row.get("vendor_name") or "").strip()
            if not vendor_name:
                continue
            key = _normalize_vehicle_name(vendor_name)
            candidate = dict(row)
            existing = observed_by_name.get(key)
            if existing is None:
                observed_by_name[key] = candidate
                continue
            if str(existing.get("role") or "") != str(candidate.get("role") or ""):
                existing["role"] = "prime+sub"
            try:
                existing_amount = float(existing.get("award_amount") or 0.0)
            except (TypeError, ValueError):
                existing_amount = 0.0
            try:
                candidate_amount = float(candidate.get("award_amount") or 0.0)
            except (TypeError, ValueError):
                candidate_amount = 0.0
            if candidate_amount > existing_amount:
                existing.update(candidate)
    return sorted(
        observed_by_name.values(),
        key=lambda row: (
            -(float(row.get("award_amount") or 0.0) if str(row.get("award_amount") or "").strip() else 0.0),
            str(row.get("vendor_name") or "").lower(),
        ),
    )


def _gao_events(results: list[Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for result in results:
        for finding in getattr(result, "findings", []) or []:
            raw = dict(getattr(finding, "raw_data", {}) or {})
            if getattr(finding, "category", "") != "bid_protest" and not raw.get("forum"):
                continue
            protester = str(raw.get("protester") or "").strip()
            agency = str(raw.get("agency") or "").strip()
            decision_date = str(raw.get("decision_date") or "").strip()
            summary_bits = []
            if protester:
                summary_bits.append(f"Protester: {protester}")
            if agency:
                summary_bits.append(f"Agency: {agency}")
            if decision_date:
                summary_bits.append(f"Decision date: {decision_date}")
            summary_line = " | ".join(summary_bits)
            assessment = str(raw.get("assessment") or getattr(finding, "detail", "") or "").strip()
            if summary_line and assessment:
                assessment = f"{summary_line}. {assessment}"
            elif summary_line:
                assessment = summary_line
            events.append(
                {
                    "title": getattr(finding, "title", "") or "GAO bid protest",
                    "status": str(raw.get("status") or "observed"),
                    "connector": getattr(finding, "source", ""),
                    "assessment": assessment,
                    "subject": getattr(finding, "title", "") or "GAO bid protest",
                    "forum": str(raw.get("forum") or "GAO"),
                    "event_id": str(raw.get("event_id") or ""),
                    "vehicle_name": str(raw.get("vehicle_name") or ""),
                    "event_date": str(raw.get("decision_date") or ""),
                    "url": getattr(finding, "url", ""),
                }
            )
    return events


def build_vehicle_intelligence_support(
    *,
    vehicle_name: str,
    vendor: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    scoped_vehicle_name = _support_vehicle_name(vehicle_name, vendor)
    if not scoped_vehicle_name:
        return None

    seed_metadata = _merged_seed_metadata(scoped_vehicle_name, vendor)
    archive_result = archive_fixture_enrich(scoped_vehicle_name)
    gao_result = gao_fixture_enrich(scoped_vehicle_name)
    live_vehicle_result = usaspending_vehicle_live_enrich(
        scoped_vehicle_name,
        **_live_vehicle_ids(seed_metadata, vendor),
    )
    results = [archive_result, gao_result, live_vehicle_result]
    contract_notice_ids = _contract_opportunity_notice_ids(seed_metadata)
    if contract_notice_ids:
        results.append(contract_opportunities_public_enrich(scoped_vehicle_name, **contract_notice_ids))
    gao_public_ids = _gao_public_ids(seed_metadata)
    if gao_public_ids:
        results.append(gao_public_enrich(scoped_vehicle_name, **gao_public_ids))
    wayback_ids = _wayback_vehicle_ids(seed_metadata)
    if wayback_ids:
        results.append(contract_vehicle_wayback_enrich(scoped_vehicle_name, **wayback_ids))
    public_html_ids = _public_html_vehicle_ids(seed_metadata)
    if public_html_ids:
        results.append(public_html_contract_vehicle_enrich(scoped_vehicle_name, **public_html_ids))

    findings = []
    for result in results:
        findings.extend(_finding_to_dict(finding) for finding in getattr(result, "findings", []) or [])

    relationships = _result_relationships(results)
    events = _gao_events(results)
    observed_vendors = _result_observed_vendors(results)
    connectors_with_data = sum(
        1
        for result in results
        if (getattr(result, "findings", None) or getattr(result, "identifiers", None) or getattr(result, "relationships", None))
    )

    return {
        "vehicle_name": scoped_vehicle_name,
        "connectors_run": len(results),
        "connectors_with_data": connectors_with_data,
        "relationships": relationships,
        "events": events,
        "findings": findings,
        "observed_vendors": observed_vendors,
        "sources": [getattr(result, "source", "") for result in results if getattr(result, "source", "")],
    }
