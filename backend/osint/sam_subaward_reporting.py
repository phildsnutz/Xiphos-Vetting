"""
SAM.gov Acquisition Subaward Reporting Connector

Queries the official GSA Acquisition Subaward Reporting Public API for
published subcontract records tied to a vendor's known prime awards.

Because the API filters by prime award identifiers rather than vendor name,
this connector first uses the existing USAspending award search to identify
candidate prime contract PIIDs, then hydrates authoritative subcontract
records from SAM.gov.

Docs:
https://open.gsa.gov/api/acquisition-subaward-reporting-api/
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from secure_runtime_env import ensure_runtime_env_loaded

from . import EnrichmentResult, Finding
from . import usaspending

BASE = "https://api.sam.gov/prod/contract/v1/subcontracts/search"
USER_AGENT = "Xiphos-Vetting/2.1"
MAX_PRIME_AWARDS = 8
MAX_PAGES_PER_AWARD = 2
PAGE_SIZE = 200
MAX_GRAPH_SUBS = 30
LOOKBACK_START = "2020-01-01"


def _get_api_key() -> str:
    ensure_runtime_env_loaded(("XIPHOS_SAM_API_KEY", "SAM_GOV_API_KEY", "XIPHOS_SAM_GOV_API_KEY"))
    return os.environ.get("XIPHOS_SAM_API_KEY", os.environ.get("SAM_GOV_API_KEY", ""))


def _get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _extract_records(payload: dict | list | None) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []

    direct_keys = (
        "subcontracts",
        "subcontractsList",
        "subawardDetails",
        "subcontractDetails",
        "data",
        "results",
        "content",
        "items",
    )
    for key in direct_keys:
        value = payload.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value

    for value in payload.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            sample = value[0]
            if sample.get("subEntityLegalBusinessName") or sample.get("subAwardNumber"):
                return value
    return []


def _to_float(value) -> float:
    try:
        text = str(value or "").replace(",", "").strip()
        if not text:
            return 0.0
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _search_prime_awards(vendor_name: str) -> list[dict]:
    data = usaspending._search_awards(vendor_name, limit=MAX_PRIME_AWARDS)
    if not data:
        return []
    return data.get("results", []) or []


def _get_subcontracts_by_piid(
    piid: str,
    *,
    from_date: str = LOOKBACK_START,
    to_date: str = "",
    page_size: int = PAGE_SIZE,
    max_pages: int = MAX_PAGES_PER_AWARD,
) -> list[dict]:
    api_key = _get_api_key()
    if not api_key or not piid:
        return []

    resolved_to_date = to_date or datetime.utcnow().strftime("%Y-%m-%d")
    rows: list[dict] = []
    for page_number in range(max_pages):
        params = {
            "api_key": api_key,
            "PIID": piid,
            "fromDate": from_date,
            "toDate": resolved_to_date,
            "pageNumber": str(page_number),
            "pageSize": str(page_size),
        }
        url = f"{BASE}?{urllib.parse.urlencode(params)}"
        payload = _get(url)
        if not payload:
            break

        page_rows = _extract_records(payload)
        if not page_rows:
            break
        rows.extend(page_rows)

        total_pages = payload.get("totalPages")
        if total_pages is not None:
            try:
                if page_number + 1 >= int(total_pages):
                    break
            except (TypeError, ValueError):
                pass
        if len(page_rows) < page_size:
            break
    return rows


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    t0 = time.time()
    result = EnrichmentResult(source="sam_subaward_reporting", vendor_name=vendor_name)
    result.structured_fields = {
        "prime_contracts": [],
        "top_subcontractors": [],
    }

    api_key = _get_api_key()
    if not api_key:
        result.findings.append(Finding(
            source="sam_subaward_reporting",
            category="configuration",
            title="SAM subcontract API key not configured",
            detail=(
                "Set the API key environment variable XIPHOS_SAM_API_KEY "
                "(or SAM_GOV_API_KEY) to enable official SAM.gov subcontract "
                "reporting lookups."
            ),
            severity="info",
            confidence=1.0,
        ))
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    try:
        awards = _search_prime_awards(vendor_name)
        if not awards:
            result.findings.append(Finding(
                source="sam_subaward_reporting",
                category="subcontract_reporting",
                title="No candidate prime awards found for SAM subcontract search",
                detail=(
                    f"No recent USAspending prime awards were found for '{vendor_name}', "
                    "so no SAM subcontract reports could be queried."
                ),
                severity="info",
                confidence=0.7,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        subcontractors: dict[str, dict] = {}
        prime_contracts: list[dict] = []
        total_subaward_dollars = 0.0
        total_report_rows = 0
        seen_piids: set[str] = set()

        for award in awards[:MAX_PRIME_AWARDS]:
            piid = str(award.get("Award ID", "") or "").strip()
            if not piid or piid in seen_piids:
                continue
            seen_piids.add(piid)

            rows = _get_subcontracts_by_piid(piid)
            if not rows:
                continue

            prime_total = 0.0
            for row in rows:
                sub_name = (
                    row.get("subEntityLegalBusinessName")
                    or row.get("subEntityDoingBusinessAsName")
                    or ""
                ).strip()
                if not sub_name or usaspending._exactish_name_match(sub_name, [vendor_name]):
                    continue

                amount = _to_float(row.get("subAwardAmount"))
                prime_total += amount
                total_subaward_dollars += amount
                total_report_rows += 1

                entry = subcontractors.setdefault(sub_name, {
                    "total_amount": 0.0,
                    "count": 0,
                    "subaward_numbers": set(),
                    "prime_contract_keys": set(),
                    "sub_entity_uei": "",
                    "sub_parent_name": "",
                    "business_type": "",
                    "sample_description": "",
                    "last_date": "",
                })
                entry["total_amount"] += amount
                entry["count"] += 1
                if row.get("subAwardNumber"):
                    entry["subaward_numbers"].add(str(row.get("subAwardNumber")))
                if row.get("primeContractKey"):
                    entry["prime_contract_keys"].add(str(row.get("primeContractKey")))
                entry["sub_entity_uei"] = entry["sub_entity_uei"] or str(row.get("subEntityUei") or "")
                entry["sub_parent_name"] = entry["sub_parent_name"] or str(row.get("subEntityParentLegalBusinessName") or "")
                entry["business_type"] = entry["business_type"] or str(row.get("subBusinessType") or "")
                entry["sample_description"] = entry["sample_description"] or str(row.get("subAwardDescription") or "")
                entry["last_date"] = max(entry["last_date"], str(row.get("subAwardDate") or ""))

            prime_contracts.append({
                "piid": piid,
                "agency": award.get("Awarding Agency", ""),
                "award_amount": award.get("Award Amount", 0) or 0,
                "subcontract_report_count": len(rows),
                "subcontract_total": round(prime_total, 2),
            })

        if not subcontractors:
            result.findings.append(Finding(
                source="sam_subaward_reporting",
                category="subcontract_reporting",
                title="No published SAM subcontract reports found",
                detail=(
                    f"SAM.gov subcontract reporting returned no published subcontract rows for "
                    f"the recent prime awards found for '{vendor_name}'."
                ),
                severity="info",
                confidence=0.75,
                raw_data={"prime_contracts_checked": prime_contracts},
            ))
            result.structured_fields["prime_contracts"] = prime_contracts
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        sorted_subs = sorted(subcontractors.items(), key=lambda item: item[1]["total_amount"], reverse=True)

        result.identifiers["sam_subaward_report_count"] = total_report_rows
        result.identifiers["sam_prime_contract_count"] = len(prime_contracts)
        result.identifiers["has_sam_subcontract_reports"] = True
        result.structured_fields["prime_contracts"] = prime_contracts
        result.structured_fields["top_subcontractors"] = [
            {
                "name": name,
                "amount": round(info["total_amount"], 2),
                "count": info["count"],
                "sub_entity_uei": info["sub_entity_uei"],
                "sub_parent_name": info["sub_parent_name"],
                "business_type": info["business_type"],
                "last_date": info["last_date"],
            }
            for name, info in sorted_subs[:10]
        ]

        for sub_name, info in sorted_subs[:MAX_GRAPH_SUBS]:
            result.relationships.append({
                "type": "subcontractor_of",
                "source_entity": vendor_name,
                "target_entity": sub_name,
                "data_source": "sam_subaward_reporting",
                "amount": round(info["total_amount"], 2),
                "count": info["count"],
                "sub_entity_uei": info["sub_entity_uei"],
                "sub_parent_name": info["sub_parent_name"],
                "business_type": info["business_type"],
                "last_date": info["last_date"],
                "prime_contract_keys": sorted(info["prime_contract_keys"])[:5],
            })

        top_lines = []
        for sub_name, info in sorted_subs[:10]:
            pct = (info["total_amount"] / total_subaward_dollars * 100.0) if total_subaward_dollars else 0.0
            extra = []
            if info["sub_entity_uei"]:
                extra.append(f"UEI {info['sub_entity_uei']}")
            if info["sub_parent_name"]:
                extra.append(f"Parent {info['sub_parent_name']}")
            if info["business_type"]:
                extra.append(info["business_type"])
            suffix = f" [{'; '.join(extra)}]" if extra else ""
            top_lines.append(
                f"  - {sub_name}: ${info['total_amount']:,.0f} ({info['count']} reports, {pct:.1f}%){suffix}"
            )

        result.findings.append(Finding(
            source="sam_subaward_reporting",
            category="subcontract_reporting",
            title=f"SAM subcontract reports: {len(subcontractors)} subcontractor(s), ${total_subaward_dollars:,.0f} total",
            detail=(
                f"Official SAM.gov subcontract reports show {len(subcontractors)} subcontractor(s) across "
                f"{len(prime_contracts)} prime contract(s):\n" + "\n".join(top_lines)
            ),
            severity="info",
            confidence=0.92,
            raw_data={
                "subcontractor_count": len(subcontractors),
                "prime_contract_count": len(prime_contracts),
                "total_subaward_dollars": round(total_subaward_dollars, 2),
                "total_report_rows": total_report_rows,
                "top_subcontractors": result.structured_fields["top_subcontractors"],
                "prime_contracts": prime_contracts,
            },
            structured_fields=result.structured_fields,
        ))

        if total_subaward_dollars > 0:
            concentrated = [
                (name, info) for name, info in sorted_subs
                if info["total_amount"] / total_subaward_dollars > 0.30
            ]
            if concentrated:
                result.findings.append(Finding(
                    source="sam_subaward_reporting",
                    category="subcontract_reporting",
                    title=f"SAM subcontract concentration risk: {len(concentrated)} subcontractor(s) exceed 30% of reported dollars",
                    detail="\n".join(
                        f"  - {name}: ${info['total_amount']:,.0f} ({info['total_amount'] / total_subaward_dollars * 100:.1f}%)"
                        for name, info in concentrated
                    ),
                    severity="medium",
                    confidence=0.88,
                ))
                result.risk_signals.append({
                    "signal": "sam_subcontract_concentration",
                    "severity": "medium",
                    "detail": f"{len(concentrated)} subcontractor(s) exceed 30% of reported subcontract dollars",
                })

    except Exception as exc:
        result.error = str(exc)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
