"""Vehicle-intelligence dossier support built from replayable archive and protest fixtures."""

from __future__ import annotations

from typing import Any

from osint.contract_opportunities_archive_fixture import enrich as archive_fixture_enrich
from osint.contract_vehicle_wayback import enrich as contract_vehicle_wayback_enrich
from osint.gao_bid_protests_fixture import enrich as gao_fixture_enrich
from osint.gao_bid_protests_public import enrich as gao_public_enrich
from osint.public_html_contract_vehicle import enrich as public_html_contract_vehicle_enrich


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

    seed_metadata = _seed_metadata(vendor)
    archive_result = archive_fixture_enrich(scoped_vehicle_name)
    gao_result = gao_fixture_enrich(scoped_vehicle_name)
    results = [archive_result, gao_result]
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
        "sources": [getattr(result, "source", "") for result in results if getattr(result, "source", "")],
    }
