"""
USAspending.gov Connector

Queries the USAspending API v2 for:
  - Federal contract award history by recipient
  - Total obligated amounts and award counts
  - Awarding agencies and NAICS codes
  - Contract types and set-aside programs

Free API, no key required.
API docs: https://api.usaspending.gov/
"""

import json
import re
import time
import urllib.request
import urllib.error

from . import EnrichmentResult, Finding

BASE = "https://api.usaspending.gov/api/v2"
USER_AGENT = "Xiphos/4.0 (compliance-tool@xiphos.dev)"
MAX_SUPPLY_CHAIN_GRAPH_SUBS = 30
MAX_SUPPLY_CHAIN_GRAPH_PRIMES = 25


def _post(url: str, payload: dict) -> dict | None:
    """POST JSON request."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "html" in content_type.lower() or raw[:20].startswith(b"<!DOCTYPE"):
                return None
            return json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _search_recipient(name: str) -> list[dict]:
    """Search for a recipient by name."""
    url = f"{BASE}/autocomplete/recipient/"
    data = _post(url, {"search_text": name, "limit": 5})
    if not data:
        return []
    return data.get("results", [])


def _get_recipient_profile(recipient_hash: str) -> dict | None:
    """Get detailed recipient profile."""
    url = f"{BASE}/recipient/{recipient_hash}/all/"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _search_awards(name: str, limit: int = 10) -> dict | None:
    """Search for awards by recipient name."""
    url = f"{BASE}/search/spending_by_award/"
    payload = {
        "filters": {
            "recipient_search_text": [name],
            "award_type_codes": ["A", "B", "C", "D"],  # Contracts only
            "time_period": [{"start_date": "2020-01-01", "end_date": "2026-12-31"}],
        },
        "fields": [
            "Award ID", "Recipient Name", "Award Amount",
            "Awarding Agency", "Start Date", "End Date",
            "Award Type", "Description", "NAICS Code",
        ],
        "page": 1,
        "limit": limit,
        "sort": "Award Amount",
        "order": "desc",
    }
    return _post(url, payload)


def _search_subaward_awards(vendor_name: str, limit: int = 50) -> dict | None:
    """
    Search subaward rows for a recipient.

    This is the correct searchable subaward surface. The legacy /subawards/
    endpoint only supports award_id lookups for a single prime award.
    """
    url = f"{BASE}/search/spending_by_award/"
    payload = {
        "subawards": True,
        "filters": {
            "recipient_search_text": [vendor_name],
            "award_type_codes": ["A", "B", "C", "D"],
            "time_period": [{"start_date": "2020-01-01", "end_date": "2026-12-31"}],
        },
        "fields": [
            "Prime Recipient Name",
            "Sub-Awardee Name",
            "Sub-Award Amount",
            "Sub-Award ID",
            "Awarding Agency",
            "Prime Award ID",
            "Sub-Award Date",
            "prime_award_generated_internal_id",
            "prime_award_internal_id",
        ],
        "page": 1,
        "limit": limit,
        "sort": "Sub-Award Amount",
        "order": "desc",
    }
    return _post(url, payload)


def _get_subawards_for_award(award_id: str, limit: int = 50) -> dict | None:
    """Get subawards for a specific prime award."""
    if not award_id:
        return None
    url = f"{BASE}/subawards/"
    payload = {
        "page": 1,
        "limit": limit,
        "sort": "amount",
        "order": "desc",
        "award_id": award_id,
    }
    return _post(url, payload)


_CORP_SUFFIXES = {
    "INC", "INCORPORATED", "LLC", "L.L.C", "CO", "COMPANY", "CORP",
    "CORPORATION", "LTD", "LIMITED", "LP", "LLP", "PLC", "THE",
}


def _normalize_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9 ]+", " ", (name or "").upper())
    tokens = [token for token in cleaned.split() if token and token not in _CORP_SUFFIXES]
    return " ".join(tokens)


def _exactish_name_match(candidate: str, targets: list[str]) -> bool:
    cand = _normalize_name(candidate)
    return bool(cand) and any(cand == _normalize_name(target) for target in targets if target)


def _extract_supply_chain(
    vendor_name: str,
    result: EnrichmentResult,
    recipient_name: str = "",
    awards: list[dict] | None = None,
):
    """
    Extract subcontractor/supply chain network from USASpending subawards.
    Identifies:
    - Subcontractors the vendor uses (vendor is prime)
    - Primes the vendor works under (vendor is sub)
    - Concentration risk (single sub getting >30% of subaward dollars)
    """
    import logging
    log = logging.getLogger(__name__)

    try:
        search_names = [vendor_name]
        if recipient_name and _normalize_name(recipient_name) != _normalize_name(vendor_name):
            search_names.append(recipient_name)

        subs_of_vendor = {}      # subcontractor_name -> {total_amount, count, agencies}
        primes_over_vendor = {}  # prime_name -> {total_amount, count, award_ids}
        total_subaward_dollars = 0

        # Upstream prime relationships: vendor appears as the sub-award recipient.
        for search_name in search_names:
            data = _search_subaward_awards(search_name, limit=50)
            if not data or "results" not in data:
                continue

            for sa in data.get("results", []):
                prime_name = (sa.get("Prime Recipient Name") or "").strip()
                sub_name = (sa.get("Sub-Awardee Name") or "").strip()
                amount = sa.get("Sub-Award Amount") or 0
                award_id = (sa.get("Prime Award ID") or "").strip()

                if not prime_name or not sub_name or not _exactish_name_match(sub_name, search_names):
                    continue
                if _normalize_name(prime_name) == _normalize_name(sub_name):
                    continue

                if prime_name not in primes_over_vendor:
                    primes_over_vendor[prime_name] = {"total_amount": 0, "count": 0, "award_ids": set()}
                primes_over_vendor[prime_name]["total_amount"] += amount
                primes_over_vendor[prime_name]["count"] += 1
                if award_id:
                    primes_over_vendor[prime_name]["award_ids"].add(award_id)

        # Downstream subcontractor relationships: vendor is the prime award recipient.
        award_rows = awards or []
        scanned_awards = 0
        for award in award_rows[:15]:
            award_id = (award.get("generated_internal_id") or award.get("Award ID") or "").strip()
            if not award_id:
                continue

            sub_data = _get_subawards_for_award(award_id, limit=40)
            if not sub_data or "results" not in sub_data:
                continue
            scanned_awards += 1

            for sa in sub_data.get("results", []):
                sub_name = (sa.get("recipient_name") or "").strip()
                amount = sa.get("amount") or 0
                agency = award.get("Awarding Agency", "")

                if not sub_name or _exactish_name_match(sub_name, search_names):
                    continue

                if sub_name not in subs_of_vendor:
                    subs_of_vendor[sub_name] = {"total_amount": 0, "count": 0, "agencies": set()}
                subs_of_vendor[sub_name]["total_amount"] += amount
                subs_of_vendor[sub_name]["count"] += 1
                if agency:
                    subs_of_vendor[sub_name]["agencies"].add(agency)
                total_subaward_dollars += amount

        # Build supply chain findings
        if subs_of_vendor:
            sorted_subs = sorted(subs_of_vendor.items(), key=lambda x: x[1]["total_amount"], reverse=True)

            # Store as relationships for graph ingestion
            for sub_name, info in sorted_subs[:MAX_SUPPLY_CHAIN_GRAPH_SUBS]:
                result.relationships.append({
                    "type": "subcontractor_of",
                    "source_entity": vendor_name,
                    "target_entity": sub_name,
                    "data_source": "usaspending_subawards",
                    "amount": info["total_amount"],
                    "count": info["count"],
                })

            # Top subcontractors finding
            sub_lines = []
            for name, info in sorted_subs[:10]:
                pct = (info["total_amount"] / total_subaward_dollars * 100) if total_subaward_dollars > 0 else 0
                sub_lines.append(
                    f"  - {name}: ${info['total_amount']:,.0f} ({info['count']} awards, {pct:.1f}%)"
                )

            result.findings.append(Finding(
                source="usaspending", category="supply_chain",
                title=f"Supply chain: {len(subs_of_vendor)} subcontractor(s), ${total_subaward_dollars:,.0f} total",
                detail=(
                    f"Identified {len(subs_of_vendor)} subcontractors receiving federal subawards from {vendor_name}:\n"
                    + "\n".join(sub_lines)
                ),
                severity="info", confidence=0.85,
                raw_data={
                    "subcontractor_count": len(subs_of_vendor),
                    "total_subaward_dollars": total_subaward_dollars,
                    "scanned_award_count": scanned_awards,
                    "top_subcontractors": [
                        {"name": n, "amount": i["total_amount"], "count": i["count"]}
                        for n, i in sorted_subs[:10]
                    ],
                },
            ))

            # Concentration risk: any single sub getting >30% of subaward dollars
            if total_subaward_dollars > 0:
                concentrated = [
                    (n, i) for n, i in sorted_subs
                    if i["total_amount"] / total_subaward_dollars > 0.30
                ]
                if concentrated:
                    conc_lines = [
                        f"  - {n}: ${i['total_amount']:,.0f} ({i['total_amount']/total_subaward_dollars*100:.1f}%)"
                        for n, i in concentrated
                    ]
                    result.findings.append(Finding(
                        source="usaspending", category="supply_chain",
                        title=f"Concentration risk: {len(concentrated)} subcontractor(s) exceed 30% of subaward spend",
                        detail=(
                            "The following subcontractors represent a disproportionate share of subaward dollars, "
                            "creating potential supply chain concentration risk:\n"
                            + "\n".join(conc_lines)
                        ),
                        severity="medium", confidence=0.8,
                    ))
                    result.risk_signals.append({
                        "signal": "supply_chain_concentration",
                        "severity": "medium",
                        "detail": f"{len(concentrated)} subcontractor(s) exceed 30% of subaward dollars",
                    })

        if primes_over_vendor:
            sorted_primes = sorted(primes_over_vendor.items(), key=lambda x: x[1]["total_amount"], reverse=True)

            for prime_name, info in sorted_primes[:MAX_SUPPLY_CHAIN_GRAPH_PRIMES]:
                result.relationships.append({
                    "type": "prime_contractor_of",
                    "source_entity": prime_name,
                    "target_entity": vendor_name,
                    "data_source": "usaspending_subawards",
                    "amount": info["total_amount"],
                    "count": info["count"],
                })

            prime_lines = [
                f"  - {n}: ${i['total_amount']:,.0f} ({i['count']} subawards)"
                for n, i in sorted_primes[:5]
            ]
            result.findings.append(Finding(
                source="usaspending", category="supply_chain",
                title=f"Prime contractor relationships: {vendor_name} is sub to {len(primes_over_vendor)} prime(s)",
                detail=(
                    f"Entity receives subawards from {len(primes_over_vendor)} prime contractor(s):\n"
                    + "\n".join(prime_lines)
                ),
                severity="info", confidence=0.8,
                raw_data={
                    "prime_count": len(primes_over_vendor),
                    "top_primes": [
                        {
                            "name": n,
                            "amount": i["total_amount"],
                            "count": i["count"],
                            "award_ids": sorted(i["award_ids"])[:5],
                        }
                        for n, i in sorted_primes[:10]
                    ],
                },
            ))

    except Exception as e:
        log.debug("USASpending supply chain extraction failed for %s: %s", vendor_name, e)


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query USAspending for federal contract history and supply chain."""
    t0 = time.time()
    result = EnrichmentResult(source="usaspending", vendor_name=vendor_name)

    try:
        # Step 1: Search for recipient
        recipients = _search_recipient(vendor_name)

        if not recipients:
            result.findings.append(Finding(
                source="usaspending", category="contracts",
                title="No USAspending recipient match",
                detail=f"No federal contract recipient found matching '{vendor_name}'. "
                       f"Entity may not have federal contract history.",
                severity="info", confidence=0.5,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Use the first match
        top = recipients[0]
        recipient_name = top.get("recipient_name", vendor_name)

        result.findings.append(Finding(
            source="usaspending", category="identity",
            title=f"USAspending recipient: {recipient_name}",
            detail="Matched recipient in federal spending database.",
            severity="info", confidence=0.8,
            url=f"https://www.usaspending.gov/search/?hash=&filters=%7B%22recipientSearchText%22%3A%5B%22{urllib.request.quote(recipient_name)}%22%5D%7D",
        ))

        time.sleep(0.3)

        # Step 2: LIVE API call - Search for contract awards
        awards_data = _search_awards(vendor_name, limit=15)

        if awards_data and "results" in awards_data:
            awards = awards_data["results"]
            total_count = awards_data.get("page_metadata", {}).get("total") or len(awards)

            total_amount = 0
            agencies = set()
            naics_codes = set()

            for award in awards:
                amt = award.get("Award Amount", 0) or 0
                total_amount += amt
                agency = award.get("Awarding Agency", "")
                if agency:
                    agencies.add(agency)
                naics = award.get("NAICS Code", "")
                if naics:
                    naics_codes.add(str(naics))

            # Set identifier for federal contractor
            if total_count > 0:
                result.identifiers["federal_contractor"] = True
                result.identifiers["total_obligations"] = total_amount

            result.findings.append(Finding(
                source="usaspending", category="contracts",
                title=f"Federal contracts: {total_count} awards, ${total_amount:,.0f} total",
                detail=(
                    f"Found {total_count} contract awards. "
                    f"Agencies: {', '.join(list(agencies)[:5])}. "
                    f"NAICS codes: {', '.join(list(naics_codes)[:5])}."
                ),
                severity="info", confidence=0.9,
                raw_data={
                    "total_awards": total_count,
                    "total_amount": total_amount,
                    "agencies": list(agencies),
                    "naics_codes": list(naics_codes),
                },
            ))

            # Report individual large awards
            for award in awards[:5]:
                amt = award.get("Award Amount", 0) or 0
                if amt > 0:
                    result.findings.append(Finding(
                        source="usaspending", category="contract_detail",
                        title=f"Award: ${amt:,.0f} -- {award.get('Awarding Agency', 'Unknown')}",
                        detail=(
                            f"ID: {award.get('Award ID', 'N/A')}\n"
                            f"Type: {award.get('Award Type', 'N/A')}\n"
                            f"Period: {award.get('Start Date', '?')} to {award.get('End Date', '?')}\n"
                            f"Description: {(award.get('Description', '') or '')[:200]}"
                        ),
                        severity="info", confidence=0.9,
                    ))

            # Risk signal: significant federal contractor
            if total_amount >= 1000000:
                result.risk_signals.append({
                    "signal": "significant_federal_contracts",
                    "severity": "info",
                    "detail": f"Entity is significant federal contractor (${total_amount:,.0f} total)",
                })
        else:
            result.findings.append(Finding(
                source="usaspending", category="contracts",
                title="No federal contracts found",
                detail=f"No federal contract history found for '{vendor_name}'.",
                severity="info", confidence=0.8,
            ))

    except Exception as e:
        result.error = str(e)

    # Step 3: Supply chain analysis (subcontractor network)
    try:
        _extract_supply_chain(vendor_name, result, recipient_name=recipient_name, awards=awards if 'awards' in locals() else [])
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("Supply chain extraction failed: %s", e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
