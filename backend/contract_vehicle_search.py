"""Xiphos contract vehicle search with explicit upstream error reporting."""

from __future__ import annotations

import concurrent.futures
import os
from datetime import datetime
from typing import Any

import requests

TIMEOUT = 20
BASE_URL = "https://api.usaspending.gov/api/v2"
UA = "Xiphos/5.0 (support@xiphos.example)"

VEHICLE_ALIASES = {
    "leia": ["LEIA", "Law Enforcement Innovation Alliance"],
    "tacs": ["TACS", "Total Administrative and Compliance Services"],
    "sewp": ["SEWP", "Solutions for Enterprise-Wide Procurement"],
    "oasis": ["OASIS", "One Acquisition Solution for Integrated Services"],
    "cio-sp3": ["CIO-SP3", "Chief Information Officer Solutions and Partners 3"],
    "cio-sp4": ["CIO-SP4", "Chief Information Officer Solutions and Partners 4"],
    "alliant 2": ["Alliant 2"],
    "8(a) stars iii": ["8(a) STARS III"],
    "polaris": ["Polaris"],
    "vets 2": ["VETS 2"],
    "mas": ["MAS", "Multiple Award Schedule"],
    "ites-sw2": ["ITES-SW2", "Information Technology Enterprise Solutions - Software 2"],
    "ites-3s": ["ITES-3S", "Information Technology Enterprise Solutions 3 Services"],
    "eagle ii": ["EAGLE II"],
    "encore iii": ["ENCORE III"],
    "deos": ["DEOS", "Defense Enterprise Office Solutions"],
    "ems": ["EMS", "Enterprise Mission Support"],
}


def _verify_ssl() -> bool:
    raw = os.environ.get("XIPHOS_USASPENDING_VERIFY_SSL", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _error(source: str, message: str) -> dict[str, str]:
    return {"source": source, "message": message[:300]}


def _post_json(endpoint: str, payload: dict[str, Any], *, verify_ssl: bool) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    try:
        resp = requests.post(
            f"{BASE_URL}{endpoint}",
            json=payload,
            headers={
                "User-Agent": UA,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=TIMEOUT,
            verify=verify_ssl,
        )
        resp.raise_for_status()
        return resp.json(), None
    except requests.HTTPError as exc:
        body = exc.response.text[:300] if exc.response is not None else ""
        return None, _error(endpoint, f"HTTP {exc.response.status_code if exc.response is not None else 'error'}: {body}")
    except requests.RequestException as exc:
        return None, _error(endpoint, str(exc))
    except ValueError as exc:
        return None, _error(endpoint, f"Invalid JSON response: {exc}")


def _normalize_vehicle_terms(vehicle_name: str) -> list[str]:
    primary = vehicle_name.strip()
    if not primary:
        return []
    aliases = VEHICLE_ALIASES.get(primary.lower(), [primary])
    seen: set[str] = set()
    ordered: list[str] = []
    for term in aliases:
        key = term.upper().strip()
        if key and key not in seen:
            seen.add(key)
            ordered.append(term.strip())
    return ordered


def _search_prime_awards(term: str, limit: int, *, verify_ssl: bool) -> tuple[list[dict[str, Any]], set[str], list[dict[str, str]]]:
    payload = {
        "filters": {
            "keywords": [term],
            "award_type_codes": ["A", "B", "C", "D"],
        },
        "fields": [
            "Award ID", "Recipient Name", "Award Amount",
            "Awarding Agency", "Awarding Sub Agency",
            "Description", "Start Date", "End Date",
            "Award Type",
        ],
        "limit": limit,
        "page": 1,
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }
    data, err = _post_json('/search/spending_by_award/', payload, verify_ssl=verify_ssl)
    if err:
        return [], set(), [err]

    results: list[dict[str, Any]] = []
    award_ids: set[str] = set()
    for award in data.get('results', []) or []:
        recipient_name = (award.get('Recipient Name') or '').strip()
        if not recipient_name or recipient_name.lower() in {'redacted', 'multiple recipients'}:
            continue
        award_id = (award.get('Award ID') or '').strip()
        if award_id:
            award_ids.add(award_id)
        results.append({
            'vendor_name': recipient_name,
            'award_id': award_id,
            'award_amount': award.get('Award Amount', 0),
            'awarding_agency': award.get('Awarding Agency', ''),
            'awarding_sub_agency': award.get('Awarding Sub Agency', ''),
            'description': (award.get('Description', '') or '')[:240],
            'start_date': award.get('Start Date', ''),
            'end_date': award.get('End Date', ''),
            'award_type': award.get('Award Type', ''),
            'role': 'prime',
            'source': 'usaspending',
        })
    return results, award_ids, []


def _search_subawards(term: str, limit: int, *, verify_ssl: bool) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    payload = {
        'filters': {
            'keywords': [term],
            'award_type_codes': ['A', 'B', 'C', 'D'],
        },
        'fields': [
            'Sub-Award ID', 'Sub-Awardee Name', 'Sub-Award Amount',
            'Prime Award ID', 'Prime Recipient Name',
            'Sub-Award Date', 'Sub-Award Description',
        ],
        'limit': limit,
        'page': 1,
        'sort': 'Sub-Award Amount',
        'order': 'desc',
        'subawards': True,
    }
    data, err = _post_json('/search/spending_by_award/', payload, verify_ssl=verify_ssl)
    if err:
        return [], [err]

    results: list[dict[str, Any]] = []
    for sub in data.get('results', []) or []:
        sub_name = (sub.get('Sub-Awardee Name') or '').strip()
        if not sub_name or sub_name.lower() == 'redacted':
            continue
        results.append({
            'vendor_name': sub_name,
            'award_id': sub.get('Sub-Award ID', ''),
            'award_amount': sub.get('Sub-Award Amount', 0),
            'prime_award_id': sub.get('Prime Award ID', ''),
            'prime_recipient': sub.get('Prime Recipient Name', ''),
            'description': (sub.get('Sub-Award Description', '') or '')[:240],
            'start_date': sub.get('Sub-Award Date', ''),
            'role': 'subcontractor',
            'source': 'usaspending',
        })
    return results, []


def _search_idv_children(award_id: str, limit: int, *, verify_ssl: bool) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    payload = {
        'award_id': award_id,
        'limit': limit,
        'page': 1,
        'sort': 'obligated_amount',
        'order': 'desc',
    }
    data, err = _post_json('/idvs/awards/', payload, verify_ssl=verify_ssl)
    if err:
        return [], [err]

    results: list[dict[str, Any]] = []
    for row in data.get('results', []) or []:
        vendor_name = (row.get('recipient_name') or row.get('Recipient Name') or '').strip()
        if not vendor_name or vendor_name.lower() == 'redacted':
            continue
        results.append({
            'vendor_name': vendor_name,
            'award_id': row.get('piid') or row.get('award_id') or row.get('Award ID', ''),
            'award_amount': row.get('obligated_amount') or row.get('Award Amount', 0),
            'awarding_agency': row.get('awarding_agency') or row.get('Awarding Agency', ''),
            'description': (row.get('description') or row.get('Description') or '')[:240],
            'start_date': row.get('period_of_performance_start_date') or row.get('Start Date', ''),
            'end_date': row.get('period_of_performance_current_end_date') or row.get('End Date', ''),
            'award_type': row.get('award_type') or row.get('Award Type', ''),
            'uei': row.get('recipient_uei') or row.get('uei', ''),
            'role': 'prime',
            'source': 'usaspending_idv',
        })
    return results, []


def search_contract_vehicle(vehicle_name: str, include_subs: bool = True, limit: int = 30) -> dict[str, Any]:
    search_terms = _normalize_vehicle_terms(vehicle_name)
    verify_ssl = _verify_ssl()
    all_primes: list[dict[str, Any]] = []
    all_subs: list[dict[str, Any]] = []
    idv_award_ids: set[str] = set()
    errors: list[dict[str, str]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        prime_futures = [executor.submit(_search_prime_awards, term, limit, verify_ssl=verify_ssl) for term in search_terms]
        sub_futures = [executor.submit(_search_subawards, term, limit, verify_ssl=verify_ssl) for term in search_terms] if include_subs else []

        for future in concurrent.futures.as_completed(prime_futures, timeout=40):
            try:
                primes, award_ids, future_errors = future.result()
                all_primes.extend(primes)
                idv_award_ids.update(award_ids)
                errors.extend(future_errors)
            except Exception as exc:
                errors.append(_error('/search/spending_by_award/', f'Prime search failed: {exc}'))

        for future in concurrent.futures.as_completed(sub_futures, timeout=40):
            try:
                subs, future_errors = future.result()
                all_subs.extend(subs)
                errors.extend(future_errors)
            except Exception as exc:
                errors.append(_error('/search/spending_by_award/', f'Subaward search failed: {exc}'))

    idv_candidates = sorted(idv_award_ids)[: min(10, max(limit, 3))]
    if idv_candidates:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_search_idv_children, award_id, limit, verify_ssl=verify_ssl) for award_id in idv_candidates]
            for future in concurrent.futures.as_completed(futures, timeout=40):
                try:
                    related_awards, future_errors = future.result()
                    all_primes.extend(related_awards)
                    errors.extend(future_errors)
                except Exception as exc:
                    errors.append(_error('/idvs/awards/', f'IDV expansion failed: {exc}'))

    def _dedupe(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = (row.get('vendor_name') or '').upper().strip()
            if not key:
                continue
            if key not in deduped or (row.get('award_amount') or 0) > (deduped[key].get('award_amount') or 0):
                deduped[key] = row
        return deduped

    seen_primes = _dedupe(all_primes)
    seen_subs = _dedupe(all_subs)

    unique_vendors: dict[str, dict[str, Any]] = {}
    for row in [*seen_primes.values(), *seen_subs.values()]:
        key = row['vendor_name'].upper().strip()
        existing = unique_vendors.get(key)
        if not existing:
            unique_vendors[key] = {
                'vendor_name': row['vendor_name'],
                'role': row.get('role', 'prime'),
                'uei': row.get('uei', ''),
                'duns': row.get('duns', ''),
                'award_amount': row.get('award_amount', 0),
                'pop_state': row.get('pop_state', ''),
            }
            continue
        if existing['role'] != row.get('role'):
            existing['role'] = 'prime+sub'
        if (row.get('award_amount') or 0) > (existing.get('award_amount') or 0):
            existing['award_amount'] = row.get('award_amount', 0)
        if row.get('uei') and not existing.get('uei'):
            existing['uei'] = row.get('uei')

    normalized_errors: list[dict[str, str]] = []
    seen_errors: set[tuple[str, str]] = set()
    for err in errors:
        item = (err.get('source', ''), err.get('message', ''))
        if item in seen_errors or not item[1]:
            continue
        seen_errors.add(item)
        normalized_errors.append({'source': item[0], 'message': item[1]})

    return {
        'vehicle_name': vehicle_name,
        'search_terms': search_terms,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'primes': sorted(seen_primes.values(), key=lambda x: -(x.get('award_amount') or 0)),
        'subs': sorted(seen_subs.values(), key=lambda x: -(x.get('award_amount') or 0)),
        'unique_vendors': sorted(unique_vendors.values(), key=lambda x: -(x.get('award_amount') or 0)),
        'total_primes': len(seen_primes),
        'total_subs': len(seen_subs),
        'total_unique': len(unique_vendors),
        'idv_awards_checked': len(idv_candidates),
        'errors': normalized_errors,
    }
