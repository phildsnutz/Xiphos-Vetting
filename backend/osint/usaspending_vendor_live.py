"""Live USAspending collector for vendor procurement footprint.

This connector exists to answer procurement questions that the standard
counterparty enrichment stack does not currently surface well:
  - what vehicles a vendor appears on as prime
  - what vehicles a vendor appears on as subcontractor
  - which primes they recur under
  - which downstream subs recur under their own prime awards
  - which agencies dominate the observed federal footprint

It supports replayable fixtures so dossier work can stay local-first.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import re
import time
from pathlib import Path
from typing import Any

from http_transport import curl_json_get, curl_json_post

from . import EnrichmentResult, Finding


SOURCE_NAME = "usaspending_vendor_live"
BASE = "https://api.usaspending.gov/api/v2"
USER_AGENT = "Xiphos/6.0 (procurement-footprint@xiphos.dev)"
REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_KEYS = (
    "vendor_procurement_fixture",
    "vendor_procurement_fixture_path",
)
FIXTURE_VENDOR_KEYS = (
    "vendor_procurement_fixture_vendor",
    "vendor_name",
)
MAX_MATCHED_RECIPIENTS = 3
MAX_PRIME_AWARDS = 10
MAX_SUBAWARD_ROWS = 12
MAX_DOWNSTREAM_AWARDS = 5
MAX_PARENT_LOOKUPS = 10
MAX_VEHICLES = 8
MAX_COUNTERPARTIES = 8
MAX_CUSTOMERS = 6
RECENT_WINDOW_DAYS = 730

_CORP_SUFFIXES = {
    "INC", "INCORPORATED", "LLC", "L.L.C", "CO", "COMPANY", "CORP",
    "CORPORATION", "LTD", "LIMITED", "LP", "LLP", "PLC", "THE",
}
_KNOWN_VEHICLE_PATTERNS = (
    r"\bOASIS\+?\b",
    r"\bCIO-?SP4\b",
    r"\bSEWP\b",
    r"\bALLIANT 2\b",
    r"\bVETS 2\b",
    r"\bITES-?3S\b",
    r"\b8\(A\)\s+STARS\s+III\b",
)


def _normalize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9 ]+", " ", str(value or "").upper())
    tokens = [token for token in cleaned.split() if token and token not in _CORP_SUFFIXES]
    return " ".join(tokens)


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


def _parse_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text[:10]):
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _days_since(value: Any) -> int | None:
    parsed = _parse_date(value)
    if not parsed:
        return None
    return max(0, int((datetime.now(timezone.utc) - parsed).days))


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


def _match_fixture_vendor(vendor_name: str, payload: dict[str, Any], ids: dict[str, Any]) -> dict[str, Any] | None:
    normalized_target = _normalize_name(
        str(ids.get("vendor_procurement_fixture_vendor") or ids.get("vendor_name") or vendor_name)
    )
    for record in payload.get("vendors", []) or []:
        if not isinstance(record, dict):
            continue
        names = [record.get("vendor_name", ""), *(record.get("aliases") or [])]
        if any(_normalize_name(name) == normalized_target for name in names):
            return record
    return None


def _autocomplete_recipient(vendor_name: str) -> list[dict[str, Any]]:
    payload, meta = curl_json_post(
        f"{BASE}/autocomplete/recipient/",
        {"search_text": vendor_name, "limit": 8},
        headers={"User-Agent": USER_AGENT},
        timeout_seconds=6.0,
    )
    if not isinstance(payload, dict) or meta.get("status") != 200:
        return []
    results = payload.get("results")
    return list(results) if isinstance(results, list) else []


def _candidate_queries(vendor_name: str) -> list[str]:
    queries = [str(vendor_name or "").strip()]
    normalized = _normalize_name(vendor_name)
    tokens = normalized.split()
    if len(tokens) == 1 and tokens[0] and tokens[0] not in {query.upper() for query in queries if query}:
        queries.append(tokens[0])
    return [query for query in queries if query]


def _candidate_score(vendor_name: str, candidate_name: str) -> int:
    vendor_norm = _normalize_name(vendor_name)
    candidate_norm = _normalize_name(candidate_name)
    if not vendor_norm or not candidate_norm:
        return -1
    if vendor_norm == candidate_norm:
        return 100
    vendor_tokens = vendor_norm.split()
    candidate_tokens = candidate_norm.split()
    if not vendor_tokens or not candidate_tokens:
        return -1
    shared = len(set(vendor_tokens) & set(candidate_tokens))
    if shared == 0:
        return -1
    score = shared * 10
    if vendor_tokens[0] == candidate_tokens[0]:
        score += 10
    if len(vendor_tokens) == 1 and vendor_tokens[0] in candidate_tokens:
        score += 20
    if vendor_tokens and set(vendor_tokens).issubset(set(candidate_tokens)):
        score += 15
    return score


def _matched_recipients(vendor_name: str) -> list[dict[str, Any]]:
    seen_names: set[str] = set()
    rows = []
    for query in _candidate_queries(vendor_name):
        for row in _autocomplete_recipient(query):
            if not isinstance(row, dict):
                continue
            recipient_name = str(row.get("recipient_name") or "").strip()
            if not recipient_name:
                continue
            dedupe_key = _normalize_name(recipient_name)
            if dedupe_key in seen_names:
                continue
            seen_names.add(dedupe_key)
            score = _candidate_score(vendor_name, recipient_name)
            if score < 0:
                continue
            rows.append({**row, "__score": score})
    rows.sort(key=lambda item: (-int(item.get("__score") or 0), str(item.get("recipient_name") or "").lower()))
    return rows[: MAX_MATCHED_RECIPIENTS * 2]


def _search_prime_awards(recipient_name: str, *, limit: int = MAX_PRIME_AWARDS) -> dict[str, Any]:
    payload = {
        "filters": {
            "recipient_search_text": [recipient_name],
            "award_type_codes": ["A", "B", "C", "D"],
            "time_period": [{"start_date": "2020-01-01", "end_date": "2026-12-31"}],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Awarding Agency",
            "Awarding Sub Agency",
            "Funding Agency",
            "Description",
            "generated_internal_id",
            "Parent Award ID",
            "Start Date",
            "End Date",
        ],
        "page": 1,
        "limit": limit,
        "sort": "Award Amount",
        "order": "desc",
    }
    data, meta = curl_json_post(
        f"{BASE}/search/spending_by_award/",
        payload,
        headers={"User-Agent": USER_AGENT},
        timeout_seconds=8.0,
    )
    if not isinstance(data, dict) or meta.get("status") != 200:
        return {"results": [], "errors": [{"message": meta.get("error") or f"prime search HTTP {meta.get('status')}"}]}
    return data


def _search_subaward_rows(recipient_name: str, *, limit: int = MAX_SUBAWARD_ROWS) -> dict[str, Any]:
    payload = {
        "subawards": True,
        "filters": {
            "recipient_search_text": [recipient_name],
            "award_type_codes": ["A", "B", "C", "D"],
            "time_period": [{"start_date": "2020-01-01", "end_date": "2026-12-31"}],
        },
        "fields": [
            "Prime Recipient Name",
            "Sub-Awardee Name",
            "Sub-Award Amount",
            "Prime Award ID",
            "Awarding Agency",
            "Sub-Award Date",
            "prime_award_generated_internal_id",
            "prime_award_internal_id",
        ],
        "page": 1,
        "limit": limit,
        "sort": "Sub-Award Amount",
        "order": "desc",
    }
    data, meta = curl_json_post(
        f"{BASE}/search/spending_by_award/",
        payload,
        headers={"User-Agent": USER_AGENT},
        timeout_seconds=8.0,
    )
    if not isinstance(data, dict) or meta.get("status") != 200:
        return {"results": [], "errors": [{"message": meta.get("error") or f"subaward search HTTP {meta.get('status')}"}]}
    return data


def _award_detail(award_key: str) -> dict[str, Any]:
    if not award_key:
        return {}
    data, meta = curl_json_get(
        f"{BASE}/awards/{award_key}/",
        headers={"User-Agent": USER_AGENT},
        timeout_seconds=6.0,
    )
    if not isinstance(data, dict) or meta.get("status") != 200:
        return {}
    return data


def _subawards_for_award(award_key: str) -> dict[str, Any]:
    if not award_key:
        return {"results": []}
    data, meta = curl_json_post(
        f"{BASE}/subawards/",
        {
            "page": 1,
            "limit": 8,
            "sort": "amount",
            "order": "desc",
            "award_id": award_key,
        },
        headers={"User-Agent": USER_AGENT},
        timeout_seconds=6.0,
    )
    if not isinstance(data, dict) or meta.get("status") != 200:
        return {"results": []}
    return data


def _extract_vehicle_label(*texts: str) -> str:
    for text in texts:
        clean = str(text or "").strip()
        if not clean:
            continue
        for pattern in _KNOWN_VEHICLE_PATTERNS:
            matched = re.search(pattern, clean, flags=re.IGNORECASE)
            if matched:
                return matched.group(0).upper().replace("  ", " ")
        acronym_match = re.search(r"\(([A-Z0-9\-+]{3,})\)", clean)
        if acronym_match:
            return acronym_match.group(1).upper()
        if clean.isupper() and len(clean) <= 40:
            return clean
    return ""


def _vehicle_name_from_parent(parent_detail: dict[str, Any], parent_award: dict[str, Any]) -> str:
    program_acronym = str(parent_detail.get("program_acronym") or "").strip()
    description = str(parent_detail.get("description") or "").strip()
    parent_piid = str(parent_award.get("piid") or "").strip()
    detected = _extract_vehicle_label(program_acronym, description)
    if detected:
        return detected
    upper_description = description.upper()
    if "GOVERNMENT-WIDE ACQUISITION CONTRACT" in upper_description:
        return "GSA IT GWAC"
    if "FEDERAL SUPPLY SCHEDULE" in upper_description:
        return "FEDERAL SUPPLY SCHEDULE CONTRACT"
    if program_acronym:
        return program_acronym
    if description and (parent_piid or parent_award.get("generated_unique_award_id")):
        trimmed = " ".join(description.split())
        if len(trimmed) <= 60:
            return trimmed
        if parent_piid:
            return parent_piid
    return parent_piid


def _agency_label(detail: dict[str, Any], row: dict[str, Any]) -> str:
    awarding = detail.get("awarding_agency") if isinstance(detail.get("awarding_agency"), dict) else {}
    office = str(awarding.get("office_agency_name") or "").strip()
    subtier = awarding.get("subtier_agency") if isinstance(awarding.get("subtier_agency"), dict) else {}
    top = awarding.get("toptier_agency") if isinstance(awarding.get("toptier_agency"), dict) else {}
    if office:
        return office
    if subtier.get("name"):
        return str(subtier.get("name"))
    if top.get("name"):
        return str(top.get("name"))
    return str(row.get("Awarding Agency") or row.get("Awarding Sub Agency") or row.get("Awarding Agency") or "").strip()


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
        "source_notes": ["USAspending live vendor procurement footprint"],
        "source_class": "public_connector",
        "authority_level": "official_program_system",
        "access_model": "public_api",
        "confidence": confidence,
    }


def _prime_award_row(row: dict[str, Any], detail: dict[str, Any], parent_detail_cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    parent_award = detail.get("parent_award") if isinstance(detail.get("parent_award"), dict) else {}
    parent_generated_id = str(parent_award.get("generated_unique_award_id") or "").strip()
    parent_detail = parent_detail_cache.get(parent_generated_id) or {}
    vehicle_name = _vehicle_name_from_parent(parent_detail, parent_award)
    vehicle_key = parent_generated_id or str(row.get("Award ID") or "").strip()
    return {
        "award_id": str(row.get("Award ID") or detail.get("piid") or "").strip(),
        "generated_internal_id": str(row.get("generated_internal_id") or "").strip(),
        "recipient_name": str(row.get("Recipient Name") or detail.get("recipient", {}).get("recipient_name") or "").strip(),
        "award_amount": _safe_amount(row.get("Award Amount")),
        "awarding_agency": _agency_label(detail, row),
        "awarding_sub_agency": str(row.get("Awarding Sub Agency") or "").strip(),
        "funding_agency": str(row.get("Funding Agency") or "").strip(),
        "description": str(row.get("Description") or detail.get("description") or "").strip(),
        "start_date": str(row.get("Start Date") or detail.get("period_of_performance", {}).get("start_date") or "").strip(),
        "end_date": str(row.get("End Date") or detail.get("period_of_performance", {}).get("current_end_date") or "").strip(),
        "vehicle_key": vehicle_key,
        "vehicle_name": vehicle_name,
        "vehicle_source": "parent_award" if parent_generated_id else "standalone_award",
        "parent_award_id": str(parent_award.get("piid") or row.get("Parent Award ID") or "").strip(),
        "parent_generated_id": parent_generated_id,
    }


def _subaward_row(row: dict[str, Any], detail: dict[str, Any], parent_detail_cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    parent_award = detail.get("parent_award") if isinstance(detail.get("parent_award"), dict) else {}
    parent_generated_id = str(parent_award.get("generated_unique_award_id") or "").strip()
    parent_detail = parent_detail_cache.get(parent_generated_id) or {}
    vehicle_name = _vehicle_name_from_parent(parent_detail, parent_award)
    return {
        "prime_name": str(row.get("Prime Recipient Name") or "").strip(),
        "subawardee_name": str(row.get("Sub-Awardee Name") or "").strip(),
        "amount": _safe_amount(row.get("Sub-Award Amount")),
        "prime_award_id": str(row.get("Prime Award ID") or "").strip(),
        "prime_award_generated_internal_id": str(row.get("prime_award_generated_internal_id") or "").strip(),
        "awarding_agency": _agency_label(detail, row),
        "subaward_date": str(row.get("Sub-Award Date") or "").strip(),
        "vehicle_key": parent_generated_id or str(row.get("Prime Award ID") or "").strip(),
        "vehicle_name": vehicle_name,
        "parent_award_id": str(parent_award.get("piid") or "").strip(),
    }


def _aggregate_vehicle_rows(rows: list[dict[str, Any]], *, amount_key: str, counterparty_key: str) -> list[dict[str, Any]]:
    by_vehicle: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        vehicle_name = str(row.get("vehicle_name") or "").strip()
        vehicle_key = str(row.get("vehicle_key") or vehicle_name or "").strip()
        if not vehicle_key or not vehicle_name:
            continue
        dedupe_key = _normalize_name(vehicle_name) or vehicle_key
        bucket = by_vehicle.setdefault(
            dedupe_key,
            {
                "vehicle_key": vehicle_key,
                "vehicle_name": vehicle_name,
                "total_amount": 0.0,
                "award_count": 0,
                "counterparties": set(),
                "agencies": set(),
                "award_ids": set(),
            },
        )
        bucket["total_amount"] += _safe_amount(row.get(amount_key))
        bucket["award_count"] += 1
        counterparty = str(row.get(counterparty_key) or "").strip()
        if counterparty:
            bucket["counterparties"].add(counterparty)
        agency = str(row.get("awarding_agency") or "").strip()
        if agency:
            bucket["agencies"].add(agency)
        award_id = str(row.get("award_id") or row.get("prime_award_id") or "").strip()
        if award_id:
            bucket["award_ids"].add(award_id)
    vehicles = []
    for vehicle in by_vehicle.values():
        vehicles.append(
            {
                **vehicle,
                "counterparties": sorted(vehicle["counterparties"])[:6],
                "agencies": sorted(vehicle["agencies"])[:4],
                "award_ids": sorted(vehicle["award_ids"])[:6],
            }
        )
    vehicles.sort(key=lambda item: (-item["total_amount"], -item["award_count"], item["vehicle_name"].lower()))
    return vehicles[:MAX_VEHICLES]


def _aggregate_counterparty_rows(rows: list[dict[str, Any]], *, name_key: str, amount_key: str, vehicle_key: str) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get(name_key) or "").strip()
        if not name:
            continue
        bucket = by_name.setdefault(
            _normalize_name(name),
            {
                "name": name,
                "total_amount": 0.0,
                "count": 0,
                "vehicles": set(),
            },
        )
        bucket["total_amount"] += _safe_amount(row.get(amount_key))
        bucket["count"] += 1
        vehicle_name = str(row.get(vehicle_key) or "").strip()
        if vehicle_name:
            bucket["vehicles"].add(vehicle_name)
    rows_out = []
    for bucket in by_name.values():
        rows_out.append(
            {
                "name": bucket["name"],
                "total_amount": bucket["total_amount"],
                "count": bucket["count"],
                "vehicles": sorted(bucket["vehicles"])[:5],
            }
        )
    rows_out.sort(key=lambda item: (-item["total_amount"], -item["count"], item["name"].lower()))
    return rows_out[:MAX_COUNTERPARTIES]


def _aggregate_customers(prime_awards: list[dict[str, Any]], subawards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_agency: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "agency": "",
        "prime_awards": 0,
        "subaward_rows": 0,
        "prime_amount": 0.0,
        "sub_amount": 0.0,
    })
    for row in prime_awards:
        agency = str(row.get("awarding_agency") or "").strip()
        if not agency:
            continue
        bucket = by_agency[_normalize_name(agency)]
        bucket["agency"] = agency
        bucket["prime_awards"] += 1
        bucket["prime_amount"] += _safe_amount(row.get("award_amount"))
    for row in subawards:
        agency = str(row.get("awarding_agency") or "").strip()
        if not agency:
            continue
        bucket = by_agency[_normalize_name(agency)]
        bucket["agency"] = agency
        bucket["subaward_rows"] += 1
        bucket["sub_amount"] += _safe_amount(row.get("amount"))
    rows = list(by_agency.values())
    rows.sort(
        key=lambda item: (
            -(item["prime_amount"] + item["sub_amount"]),
            -(item["prime_awards"] + item["subaward_rows"]),
            item["agency"].lower(),
        )
    )
    return rows[:MAX_CUSTOMERS]


def _award_momentum(prime_awards: list[dict[str, Any]], subawards: list[dict[str, Any]]) -> dict[str, Any]:
    recent_prime = 0
    recent_sub = 0
    latest_dates: list[datetime] = []
    for row in prime_awards:
        days = _days_since(row.get("start_date"))
        if days is not None and days <= RECENT_WINDOW_DAYS:
            recent_prime += 1
        parsed = _parse_date(row.get("start_date"))
        if parsed:
            latest_dates.append(parsed)
    for row in subawards:
        days = _days_since(row.get("subaward_date"))
        if days is not None and days <= RECENT_WINDOW_DAYS:
            recent_sub += 1
        parsed = _parse_date(row.get("subaward_date"))
        if parsed:
            latest_dates.append(parsed)
    latest_activity = max(latest_dates).date().isoformat() if latest_dates else ""
    return {
        "prime_awards": len(prime_awards),
        "prime_total_amount": round(sum(_safe_amount(row.get("award_amount")) for row in prime_awards), 2),
        "subaward_rows": len(subawards),
        "sub_total_amount": round(sum(_safe_amount(row.get("amount")) for row in subawards), 2),
        "recent_prime_awards_24m": recent_prime,
        "recent_subaward_rows_24m": recent_sub,
        "latest_activity_date": latest_activity,
    }


def _search_url(vendor_name: str) -> str:
    return f"https://www.usaspending.gov/search/?hash=&filters=%7B%22recipientSearchText%22%3A%5B%22{vendor_name.replace(' ', '%20')}%22%5D%7D"


def _build_live_payload(vendor_name: str) -> dict[str, Any]:
    matched_candidates = _matched_recipients(vendor_name)
    matched_recipients: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    prime_rows_raw: list[dict[str, Any]] = []
    sub_rows_raw: list[dict[str, Any]] = []
    for recipient in matched_candidates:
        recipient_name = str(recipient.get("recipient_name") or "").strip()
        if not recipient_name:
            continue
        prime_data = _search_prime_awards(recipient_name)
        prime_results = [row for row in (prime_data.get("results") or []) if isinstance(row, dict)]
        prime_rows_raw.extend(prime_results)
        errors.extend(prime_data.get("errors") or [])

        sub_data = _search_subaward_rows(recipient_name)
        sub_results = [row for row in (sub_data.get("results") or []) if isinstance(row, dict)]
        sub_rows_raw.extend(sub_results)
        errors.extend(sub_data.get("errors") or [])
        if prime_results or sub_results:
            matched_recipients.append(recipient)
        if len(matched_recipients) >= MAX_MATCHED_RECIPIENTS:
            break

    prime_rows_by_id: dict[str, dict[str, Any]] = {}
    for row in prime_rows_raw:
        if not isinstance(row, dict):
            continue
        generated_id = str(row.get("generated_internal_id") or "").strip()
        if not generated_id:
            continue
        existing = prime_rows_by_id.get(generated_id)
        if existing is None or _safe_amount(row.get("Award Amount")) > _safe_amount(existing.get("Award Amount")):
            prime_rows_by_id[generated_id] = row

    detail_cache: dict[str, dict[str, Any]] = {}
    parent_detail_cache: dict[str, dict[str, Any]] = {}

    def cache_detail(award_key: str) -> dict[str, Any]:
        if not award_key:
            return {}
        cached = detail_cache.get(award_key)
        if cached is not None:
            return cached
        detail_cache[award_key] = _award_detail(award_key)
        return detail_cache[award_key]

    for award_key in list(prime_rows_by_id.keys())[:MAX_PARENT_LOOKUPS]:
        detail = cache_detail(award_key)
        parent_award = detail.get("parent_award") if isinstance(detail.get("parent_award"), dict) else {}
        parent_generated_id = str(parent_award.get("generated_unique_award_id") or "").strip()
        if parent_generated_id and parent_generated_id not in parent_detail_cache and len(parent_detail_cache) < MAX_PARENT_LOOKUPS:
            parent_detail_cache[parent_generated_id] = _award_detail(parent_generated_id)

    sub_rows_filtered: list[dict[str, Any]] = []
    for row in sub_rows_raw:
        if not isinstance(row, dict):
            continue
        subawardee = str(row.get("Sub-Awardee Name") or "").strip()
        if _candidate_score(vendor_name, subawardee) < 0:
            continue
        sub_rows_filtered.append(row)
        prime_generated_id = str(row.get("prime_award_generated_internal_id") or "").strip()
        if prime_generated_id and prime_generated_id not in detail_cache and len(detail_cache) < (MAX_PARENT_LOOKUPS * 2):
            detail_cache[prime_generated_id] = _award_detail(prime_generated_id)
            parent_award = detail_cache[prime_generated_id].get("parent_award") if isinstance(detail_cache[prime_generated_id].get("parent_award"), dict) else {}
            parent_generated_id = str(parent_award.get("generated_unique_award_id") or "").strip()
            if parent_generated_id and parent_generated_id not in parent_detail_cache and len(parent_detail_cache) < (MAX_PARENT_LOOKUPS * 2):
                parent_detail_cache[parent_generated_id] = _award_detail(parent_generated_id)

    prime_awards: list[dict[str, Any]] = []
    for row in sorted(prime_rows_by_id.values(), key=lambda item: -_safe_amount(item.get("Award Amount")))[:MAX_PRIME_AWARDS]:
        generated_id = str(row.get("generated_internal_id") or "").strip()
        detail = detail_cache.get(generated_id) or cache_detail(generated_id)
        prime_awards.append(_prime_award_row(row, detail, parent_detail_cache))

    subaward_rows: list[dict[str, Any]] = []
    for row in sorted(sub_rows_filtered, key=lambda item: -_safe_amount(item.get("Sub-Award Amount")))[:MAX_SUBAWARD_ROWS]:
        prime_generated_id = str(row.get("prime_award_generated_internal_id") or "").strip()
        detail = detail_cache.get(prime_generated_id) or cache_detail(prime_generated_id)
        subaward_rows.append(_subaward_row(row, detail, parent_detail_cache))

    downstream_rows: list[dict[str, Any]] = []
    for award in prime_awards[:MAX_DOWNSTREAM_AWARDS]:
        sub_data = _subawards_for_award(str(award.get("generated_internal_id") or ""))
        for row in sub_data.get("results") or []:
            if not isinstance(row, dict):
                continue
            downstream_rows.append(
                {
                    "recipient_name": str(row.get("recipient_name") or "").strip(),
                    "amount": _safe_amount(row.get("amount")),
                    "award_count": 1,
                    "vehicle_name": str(award.get("vehicle_name") or "").strip(),
                    "award_id": str(award.get("award_id") or "").strip(),
                }
            )

    prime_vehicles = _aggregate_vehicle_rows(prime_awards, amount_key="award_amount", counterparty_key="awarding_agency")
    sub_vehicles = _aggregate_vehicle_rows(subaward_rows, amount_key="amount", counterparty_key="prime_name")
    upstream_primes = _aggregate_counterparty_rows(subaward_rows, name_key="prime_name", amount_key="amount", vehicle_key="vehicle_name")
    downstream_subcontractors = _aggregate_counterparty_rows(downstream_rows, name_key="recipient_name", amount_key="amount", vehicle_key="vehicle_name")
    top_customers = _aggregate_customers(prime_awards, subaward_rows)
    award_momentum = _award_momentum(prime_awards, subaward_rows)

    return {
        "vendor_name": vendor_name,
        "matched_recipients": [
            {
                "recipient_name": str(row.get("recipient_name") or "").strip(),
                "recipient_hash": str(row.get("recipient_hash") or "").strip(),
                "score": int(row.get("__score") or 0),
            }
            for row in matched_recipients
        ],
        "prime_awards": prime_awards,
        "subaward_rows": subaward_rows,
        "prime_vehicles": prime_vehicles,
        "sub_vehicles": sub_vehicles,
        "upstream_primes": upstream_primes,
        "downstream_subcontractors": downstream_subcontractors,
        "top_customers": top_customers,
        "award_momentum": award_momentum,
        "errors": errors[:5],
    }


def _build_payload(vendor_name: str, ids: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    fixture_payload = _resolve_fixture_payload(ids)
    if fixture_payload:
        matched = _match_fixture_vendor(vendor_name, fixture_payload, ids)
        if matched:
            return dict(matched), True
    return _build_live_payload(vendor_name), False


def enrich(vendor_name: str, **ids) -> EnrichmentResult:
    started = time.perf_counter()
    result = EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        source_class="public_connector",
        authority_level="official_program_system",
        access_model="public_api",
    )

    payload, used_fixture = _build_payload(vendor_name, ids)
    search_url = _search_url(vendor_name)
    prime_vehicles = list(payload.get("prime_vehicles") or [])
    sub_vehicles = list(payload.get("sub_vehicles") or [])
    upstream_primes = list(payload.get("upstream_primes") or [])
    downstream_subcontractors = list(payload.get("downstream_subcontractors") or [])
    top_customers = list(payload.get("top_customers") or [])
    award_momentum = dict(payload.get("award_momentum") or {})

    if prime_vehicles or sub_vehicles:
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="contracts",
                title=f"Federal procurement footprint: {len(prime_vehicles)} prime vehicle and {len(sub_vehicles)} subcontract vehicle signals",
                detail=(
                    f"Observed {award_momentum.get('prime_awards', 0)} direct awards and "
                    f"{award_momentum.get('subaward_rows', 0)} subcontract rows in USAspending. "
                    f"Prime vehicles: {', '.join(item['vehicle_name'] for item in prime_vehicles[:3]) or 'none observed'}. "
                    f"Subcontract vehicles: {', '.join(item['vehicle_name'] for item in sub_vehicles[:3]) or 'none observed'}."
                ),
                severity="info",
                confidence=0.84,
                url=search_url,
                raw_data={"used_fixture": used_fixture},
                source_class="public_connector",
                authority_level="official_program_system",
                access_model="public_api",
                structured_fields={
                    "prime_vehicle_count": len(prime_vehicles),
                    "sub_vehicle_count": len(sub_vehicles),
                    "prime_awards": award_momentum.get("prime_awards", 0),
                    "subaward_rows": award_momentum.get("subaward_rows", 0),
                    "used_fixture": used_fixture,
                },
            )
        )
    if prime_vehicles:
        lead = prime_vehicles[0]
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="contracts",
                title=f"Prime vehicle access: {lead.get('vehicle_name', 'Unknown vehicle')}",
                detail=(
                    f"OBSERVED: {vendor_name} appears as a direct prime on {lead.get('vehicle_name', 'this vehicle')} "
                    f"through {lead.get('award_count', 0)} observed award row(s) worth {_format_currency(lead.get('total_amount'))}. "
                    f"Agencies in this path: {', '.join(lead.get('agencies') or []) or 'not surfaced'}."
                ),
                severity="info",
                confidence=0.82,
                url=search_url,
                raw_data={"vehicle": lead},
                source_class="public_connector",
                authority_level="official_program_system",
                access_model="public_api",
            )
        )
    if sub_vehicles:
        lead = sub_vehicles[0]
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="contracts",
                title=f"Subcontract footprint: {lead.get('vehicle_name', 'Unknown vehicle')}",
                detail=(
                    f"OBSERVED: {vendor_name} also appears as a subcontractor on {lead.get('vehicle_name', 'this vehicle')} "
                    f"through {_format_currency(lead.get('total_amount'))} in observed subaward flow. "
                    f"Named primes in this path: {', '.join(lead.get('counterparties') or []) or 'not surfaced'}."
                ),
                severity="info",
                confidence=0.8,
                url=search_url,
                raw_data={"vehicle": lead},
                source_class="public_connector",
                authority_level="official_program_system",
                access_model="public_api",
            )
        )
    if upstream_primes:
        lead = upstream_primes[0]
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="contracts",
                title=f"Recurring upstream prime: {lead.get('name', 'Unknown')}",
                detail=(
                    f"OBSERVED: {vendor_name} most often appears under {lead.get('name', 'this prime')} "
                    f"for {_format_currency(lead.get('total_amount'))} across {lead.get('count', 0)} observed subcontract rows. "
                    f"Vehicles in this path: {', '.join(lead.get('vehicles') or []) or 'not surfaced'}."
                ),
                severity="info",
                confidence=0.78,
                url=search_url,
                raw_data={"prime": lead},
                source_class="public_connector",
                authority_level="official_program_system",
                access_model="public_api",
            )
        )
    if payload.get("errors"):
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="contracts",
                title="USAspending procurement scan returned partial errors",
                detail=" ; ".join(str(item.get("message") or "") for item in payload.get("errors", [])[:3] if isinstance(item, dict)),
                severity="low",
                confidence=0.45,
                url=search_url,
                raw_data={"errors": payload.get("errors") or []},
                source_class="public_connector",
                authority_level="official_program_system",
                access_model="public_api",
            )
        )

    relationships: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for vehicle in prime_vehicles[:MAX_VEHICLES]:
        key = ("prime_on_vehicle", _normalize_name(vendor_name), _normalize_name(vehicle.get("vehicle_name")))
        if key in seen:
            continue
        seen.add(key)
        relationships.append(
            _relationship(
                rel_type="prime_on_vehicle",
                source_name=vendor_name,
                target_name=str(vehicle.get("vehicle_name") or "").strip(),
                evidence=(
                    f"USAspending observed {vendor_name} as prime on {vehicle.get('vehicle_name')} "
                    f"through {vehicle.get('award_count', 0)} award row(s) totaling {_format_currency(vehicle.get('total_amount'))}. "
                    f"Agencies: {', '.join(vehicle.get('agencies') or []) or 'not surfaced'}."
                ),
                confidence=0.86,
                source_urls=[search_url],
            )
        )

    for vehicle in sub_vehicles[:MAX_VEHICLES]:
        key = ("subcontractor_on_vehicle", _normalize_name(vendor_name), _normalize_name(vehicle.get("vehicle_name")))
        if key in seen:
            continue
        seen.add(key)
        relationships.append(
            _relationship(
                rel_type="subcontractor_on_vehicle",
                source_name=vendor_name,
                target_name=str(vehicle.get("vehicle_name") or "").strip(),
                evidence=(
                    f"USAspending observed {vendor_name} as subcontractor on {vehicle.get('vehicle_name')} "
                    f"with {_format_currency(vehicle.get('total_amount'))} in visible subaward flow. "
                    f"Named primes: {', '.join(vehicle.get('counterparties') or []) or 'not surfaced'}."
                ),
                confidence=0.82,
                source_urls=[search_url],
            )
        )

    for prime in upstream_primes[:MAX_COUNTERPARTIES]:
        key = ("prime_contractor_of", _normalize_name(prime.get("name")), _normalize_name(vendor_name))
        if key in seen:
            continue
        seen.add(key)
        relationships.append(
            _relationship(
                rel_type="prime_contractor_of",
                source_name=str(prime.get("name") or "").strip(),
                target_name=vendor_name,
                evidence=(
                    f"USAspending subaward rows show {vendor_name} performing under {prime.get('name')} "
                    f"for {_format_currency(prime.get('total_amount'))} across {prime.get('count', 0)} rows. "
                    f"Vehicles: {', '.join(prime.get('vehicles') or []) or 'not surfaced'}."
                ),
                confidence=0.78,
                source_urls=[search_url],
            )
        )

    for sub in downstream_subcontractors[:MAX_COUNTERPARTIES]:
        key = ("subcontractor_of", _normalize_name(vendor_name), _normalize_name(sub.get("name")))
        if key in seen:
            continue
        seen.add(key)
        relationships.append(
            _relationship(
                rel_type="subcontractor_of",
                source_name=vendor_name,
                target_name=str(sub.get("name") or "").strip(),
                evidence=(
                    f"USAspending subaward detail shows {vendor_name} flowing work to {sub.get('name')} "
                    f"for {_format_currency(sub.get('total_amount'))} across {sub.get('count', 0)} visible subaward rows. "
                    f"Vehicles: {', '.join(sub.get('vehicles') or []) or 'not surfaced'}."
                ),
                confidence=0.76,
                source_urls=[search_url],
            )
        )

    for agency in top_customers[:MAX_CUSTOMERS]:
        key = ("funded_by", _normalize_name(agency.get("agency")), _normalize_name(vendor_name))
        if key in seen:
            continue
        seen.add(key)
        relationships.append(
            _relationship(
                rel_type="funded_by",
                source_name=str(agency.get("agency") or "").strip(),
                target_name=vendor_name,
                evidence=(
                    f"USAspending ties {vendor_name} to {agency.get('agency')} through "
                    f"{agency.get('prime_awards', 0)} direct award row(s) and {agency.get('subaward_rows', 0)} subcontract row(s), "
                    f"representing {_format_currency(_safe_amount(agency.get('prime_amount')) + _safe_amount(agency.get('sub_amount')))} in visible flow."
                ),
                confidence=0.74,
                source_urls=[search_url],
            )
        )

    result.relationships = relationships
    result.structured_fields.update(
        {
            "vendor_name": vendor_name,
            "matched_recipients": list(payload.get("matched_recipients") or []),
            "prime_awards": list(payload.get("prime_awards") or []),
            "subaward_rows": list(payload.get("subaward_rows") or []),
            "prime_vehicles": prime_vehicles,
            "sub_vehicles": sub_vehicles,
            "upstream_primes": upstream_primes,
            "downstream_subcontractors": downstream_subcontractors,
            "top_customers": top_customers,
            "award_momentum": award_momentum,
            "used_fixture": used_fixture,
            "errors": list(payload.get("errors") or []),
        }
    )
    result.identifiers.update(
        {
            "prime_vehicle_count": len(prime_vehicles),
            "sub_vehicle_count": len(sub_vehicles),
            "prime_award_count": int(award_momentum.get("prime_awards") or 0),
            "subaward_row_count": int(award_momentum.get("subaward_rows") or 0),
        }
    )
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
