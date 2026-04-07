"""Live USAspending vehicle collector for contract-vehicle support.

This connector is the public-data backbone for support-only vehicle dossiers:
  - it queries the existing USAspending vehicle search helper live
  - it can replay fixture payloads for local-first collector development
  - it emits provider-neutral findings and relationships instead of route-local JSON
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from contract_vehicle_search import search_contract_vehicle

from . import EnrichmentResult, Finding


SOURCE_NAME = "usaspending_vehicle_live"
REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_KEYS = (
    "contract_vehicle_live_fixture",
    "contract_vehicle_live_fixture_path",
)
FIXTURE_VEHICLE_KEYS = (
    "contract_vehicle_live_fixture_vehicle",
    "contract_vehicle_name",
)
MAX_PRIMES = 10
MAX_SUBS = 10
MAX_AGENCIES = 4


def _normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _safe_amount(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _format_currency(value: Any) -> str:
    amount = _safe_amount(value)
    if amount <= 0:
        return "$0"
    return f"${amount:,.0f}"


def _resolve_fixture_payload(ids: dict[str, Any]) -> dict[str, Any]:
    for key in FIXTURE_KEYS:
        raw = ids.get(key)
        if not raw:
            continue
        path = Path(str(raw))
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _match_fixture_vehicle(vehicle_name: str, payload: dict[str, Any], ids: dict[str, Any]) -> dict[str, Any] | None:
    normalized_target = _normalize_name(
        str(
            ids.get("contract_vehicle_live_fixture_vehicle")
            or ids.get("contract_vehicle_name")
            or vehicle_name
        )
    )
    for vehicle in payload.get("vehicles", []) or []:
        if not isinstance(vehicle, dict):
            continue
        names = [vehicle.get("vehicle_name", ""), *(vehicle.get("aliases") or [])]
        if any(_normalize_name(name) == normalized_target for name in names):
            return vehicle
    return None


def _search_payload(vehicle_name: str, ids: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    payload = _resolve_fixture_payload(ids)
    if payload:
        matched = _match_fixture_vehicle(vehicle_name, payload, ids)
        if matched:
            return {
                "vehicle_name": matched.get("vehicle_name") or vehicle_name,
                "search_terms": matched.get("search_terms") or [vehicle_name],
                "primes": list(matched.get("primes") or []),
                "subs": list(matched.get("subs") or []),
                "unique_vendors": list(matched.get("unique_vendors") or []),
                "total_primes": int(matched.get("total_primes") or len(matched.get("primes") or [])),
                "total_subs": int(matched.get("total_subs") or len(matched.get("subs") or [])),
                "total_unique": int(matched.get("total_unique") or len(matched.get("unique_vendors") or [])),
                "idv_awards_checked": int(matched.get("idv_awards_checked") or 0),
                "errors": list(matched.get("errors") or []),
            }, True

    include_subs = bool(ids.get("contract_vehicle_live_include_subs", True))
    raw_limit = ids.get("contract_vehicle_live_limit", 18)
    try:
        limit = max(6, min(int(raw_limit or 18), 30))
    except (TypeError, ValueError):
        limit = 18
    return search_contract_vehicle(vehicle_name, include_subs=include_subs, limit=limit), False


def _search_url(vehicle_name: str) -> str:
    return f"https://www.usaspending.gov/search/?hash=vehicle/{vehicle_name}"


def _evidence_snippet(row: dict[str, Any], *, vehicle_name: str, role_label: str) -> str:
    pieces: list[str] = [f"Observed as {role_label} on {vehicle_name} via live USAspending vehicle search."]
    award_id = str(row.get("award_id") or "").strip()
    if award_id:
        pieces.append(f"Award ID: {award_id}.")
    agency = str(row.get("awarding_agency") or row.get("awarding_sub_agency") or row.get("prime_recipient") or "").strip()
    if agency:
        pieces.append(f"Top counterparty or agency: {agency}.")
    amount = _safe_amount(row.get("award_amount"))
    if amount > 0:
        pieces.append(f"Observed amount: {_format_currency(amount)}.")
    description = str(row.get("description") or "").strip()
    if description:
        pieces.append(description[:220].rstrip(".") + ".")
    return " ".join(piece for piece in pieces if piece)


def _observed_vendors(payload: dict[str, Any]) -> list[dict[str, Any]]:
    observed_by_name: dict[str, dict[str, Any]] = {}
    for source_key, default_role in (("primes", "prime"), ("subs", "subcontractor"), ("unique_vendors", "")):
        for row in payload.get(source_key, []) or []:
            if not isinstance(row, dict):
                continue
            vendor_name = str(row.get("vendor_name") or "").strip()
            if not vendor_name:
                continue
            key = _normalize_name(vendor_name)
            role = str(row.get("role") or default_role or "").strip() or "prime"
            award_amount = _safe_amount(row.get("award_amount"))
            existing = observed_by_name.get(key)
            candidate = {
                "vendor_name": vendor_name,
                "role": role,
                "award_amount": award_amount,
                "award_id": str(row.get("award_id") or row.get("prime_award_id") or "").strip(),
                "awarding_agency": str(row.get("awarding_agency") or "").strip(),
                "description": str(row.get("description") or "").strip(),
            }
            if existing is None:
                observed_by_name[key] = candidate
                continue
            if existing["role"] != candidate["role"]:
                existing["role"] = "prime+sub"
            if candidate["award_amount"] > existing["award_amount"]:
                existing.update(candidate)
    return sorted(observed_by_name.values(), key=lambda row: (-row.get("award_amount", 0.0), row["vendor_name"].lower()))


def _relationship(
    *,
    rel_type: str,
    source_name: str,
    target_name: str,
    evidence: str,
    confidence: float,
    source_urls: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "rel_type": rel_type,
        "source_name": source_name,
        "target_name": target_name,
        "data_source": SOURCE_NAME,
        "data_sources": [SOURCE_NAME],
        "corroboration_count": 1,
        "intelligence_tier": "supported",
        "evidence": evidence,
        "evidence_summary": evidence,
        "observed_at": "",
        "source_urls": list(source_urls or []),
        "source_notes": ["USAspending live vehicle search"],
        "source_class": "public_connector",
        "authority_level": "official_program_system",
        "access_model": "public_api",
        "confidence": confidence,
    }


def _agency_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    by_agency: dict[str, dict[str, Any]] = {}
    for row in [*(payload.get("primes") or []), *(payload.get("subs") or [])]:
        if not isinstance(row, dict):
            continue
        agency = str(row.get("awarding_agency") or row.get("awarding_sub_agency") or "").strip()
        if not agency:
            continue
        key = _normalize_name(agency)
        bucket = by_agency.setdefault(
            key,
            {
                "agency": agency,
                "award_count": 0,
                "total_amount": 0.0,
                "vendors": [],
            },
        )
        bucket["award_count"] += 1
        bucket["total_amount"] += _safe_amount(row.get("award_amount"))
        vendor_name = str(row.get("vendor_name") or "").strip()
        if vendor_name and vendor_name not in bucket["vendors"]:
            bucket["vendors"].append(vendor_name)
    rows = list(by_agency.values())
    rows.sort(key=lambda item: (-item["award_count"], -item["total_amount"], item["agency"].lower()))
    return rows[:MAX_AGENCIES]


def enrich(vendor_name: str, **ids) -> EnrichmentResult:
    started = time.perf_counter()
    result = EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        source_class="public_connector",
        authority_level="official_program_system",
        access_model="public_api",
    )

    payload, used_fixture = _search_payload(vendor_name, ids)
    observed_vendors = _observed_vendors(payload)
    search_url = _search_url(vendor_name)
    focal_prime = str(ids.get("prime_contractor_name") or "").strip()
    focal_prime_key = _normalize_name(focal_prime)

    total_primes = int(payload.get("total_primes") or len(payload.get("primes") or []))
    total_subs = int(payload.get("total_subs") or len(payload.get("subs") or []))
    total_unique = int(payload.get("total_unique") or len(observed_vendors))

    if total_primes or total_subs:
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="vehicle_market",
                title=f"Live award picture: {total_primes} prime and {total_subs} subcontractor signals on {vendor_name}",
                detail=(
                    f"USAspending live vehicle search observed {total_unique} unique vendors tied to {vendor_name}. "
                    f"Prime roster: {', '.join(row['vendor_name'] for row in observed_vendors[:3]) or 'none observed'}."
                ),
                severity="info",
                confidence=0.78,
                url=search_url,
                raw_data={
                    "vehicle_name": vendor_name,
                    "total_primes": total_primes,
                    "total_subs": total_subs,
                    "used_fixture": used_fixture,
                },
                source_class="public_connector",
                authority_level="official_program_system",
                access_model="public_api",
                structured_fields={
                    "vehicle_name": vendor_name,
                    "total_primes": total_primes,
                    "total_subs": total_subs,
                    "total_unique": total_unique,
                    "used_fixture": used_fixture,
                },
            )
        )

    if payload.get("errors"):
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="vehicle_market",
                title="Live vehicle search returned partial errors",
                detail=" ; ".join(str(item.get("message") or "") for item in (payload.get("errors") or [])[:3] if isinstance(item, dict)),
                severity="low",
                confidence=0.5,
                url=search_url,
                raw_data={"errors": payload.get("errors") or []},
                source_class="public_connector",
                authority_level="official_program_system",
                access_model="public_api",
            )
        )

    if payload.get("primes"):
        top_prime = payload["primes"][0]
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="vehicle_market",
                title=f"Top observed prime on {vendor_name}: {top_prime.get('vendor_name', 'Unknown')}",
                detail=_evidence_snippet(top_prime, vehicle_name=vendor_name, role_label="prime"),
                severity="info",
                confidence=0.74,
                url=search_url,
                raw_data={"vehicle_name": vendor_name, "row": dict(top_prime)},
                source_class="public_connector",
                authority_level="official_program_system",
                access_model="public_api",
            )
        )

    if payload.get("subs"):
        top_sub = payload["subs"][0]
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="vehicle_market",
                title=f"Top observed subcontractor on {vendor_name}: {top_sub.get('vendor_name', 'Unknown')}",
                detail=_evidence_snippet(top_sub, vehicle_name=vendor_name, role_label="subcontractor"),
                severity="info",
                confidence=0.7,
                url=search_url,
                raw_data={"vehicle_name": vendor_name, "row": dict(top_sub)},
                source_class="public_connector",
                authority_level="official_program_system",
                access_model="public_api",
            )
        )

    relationships: list[dict[str, Any]] = []
    seen_relationships: set[tuple[str, str, str]] = set()

    for row in (payload.get("primes") or [])[:MAX_PRIMES]:
        if not isinstance(row, dict):
            continue
        vendor = str(row.get("vendor_name") or "").strip()
        if not vendor:
            continue
        evidence = _evidence_snippet(row, vehicle_name=vendor_name, role_label="prime")
        key = ("prime_contractor_of", _normalize_name(vendor), _normalize_name(vendor_name))
        if key not in seen_relationships:
            seen_relationships.add(key)
            relationships.append(
                _relationship(
                    rel_type="prime_contractor_of",
                    source_name=vendor,
                    target_name=vendor_name,
                    evidence=evidence,
                    confidence=0.82,
                    source_urls=[search_url],
                )
            )
        if focal_prime_key and _normalize_name(vendor) != focal_prime_key:
            comp_key = ("competed_on", _normalize_name(vendor), _normalize_name(vendor_name))
            if comp_key not in seen_relationships:
                seen_relationships.add(comp_key)
                relationships.append(
                    _relationship(
                        rel_type="competed_on",
                        source_name=vendor,
                        target_name=vendor_name,
                        evidence=(
                            f"Observed {vendor} as another live prime participant on {vendor_name} while {focal_prime or 'the focal prime'} remains in scope."
                        ),
                        confidence=0.7,
                        source_urls=[search_url],
                    )
                )

    for row in (payload.get("subs") or [])[:MAX_SUBS]:
        if not isinstance(row, dict):
            continue
        vendor = str(row.get("vendor_name") or "").strip()
        if not vendor:
            continue
        key = ("subcontractor_of", _normalize_name(vendor), _normalize_name(vendor_name))
        if key in seen_relationships:
            continue
        seen_relationships.add(key)
        relationships.append(
            _relationship(
                rel_type="subcontractor_of",
                source_name=vendor,
                target_name=vendor_name,
                evidence=_evidence_snippet(row, vehicle_name=vendor_name, role_label="subcontractor"),
                confidence=0.76,
                source_urls=[search_url],
            )
        )

    for agency in _agency_rows(payload):
        key = ("funded_by", _normalize_name(agency["agency"]), _normalize_name(vendor_name))
        if key in seen_relationships:
            continue
        seen_relationships.add(key)
        vendor_list = ", ".join(agency["vendors"][:3]) or "multiple vendors"
        relationships.append(
            _relationship(
                rel_type="funded_by",
                source_name=agency["agency"],
                target_name=vendor_name,
                evidence=(
                    f"Live award picture ties {vendor_name} to {agency['agency']} through {agency['award_count']} observed award rows. "
                    f"Named vendors in that path include {vendor_list}."
                ),
                confidence=0.72,
                source_urls=[search_url],
            )
        )

    result.relationships = relationships
    result.identifiers.update(
        {
            "vehicle_name": vendor_name,
            "total_primes": total_primes,
            "total_subs": total_subs,
            "total_unique_vendors": total_unique,
            "idv_awards_checked": int(payload.get("idv_awards_checked") or 0),
        }
    )
    result.structured_fields.update(
        {
            "vehicle_name": vendor_name,
            "search_terms": list(payload.get("search_terms") or []),
            "observed_vendors": observed_vendors,
            "used_fixture": used_fixture,
            "errors": list(payload.get("errors") or []),
        }
    )
    if payload.get("errors") and not result.findings:
        result.error = " ; ".join(str(item.get("message") or "") for item in (payload.get("errors") or [])[:3] if isinstance(item, dict))
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
