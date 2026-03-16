"""
FARA (Foreign Agents Registration Act) Connector

Queries the DOJ FARA eFile API v1 to identify individuals and entities
registered as agents of foreign principals under 22 U.S.C. ss 611 et seq.

FARA requires persons acting as agents of foreign principals in a political
or quasi-political capacity to disclose their relationship, activities,
receipts, and disbursements. This is a critical risk indicator for defense
and intelligence vendor vetting because:

  1. Active registration means the vendor operates on behalf of a foreign
     government or foreign political entity.
  2. Registration involving adversarial nations (Russia, China, Iran, DPRK,
     Syria, Cuba, Venezuela) constitutes an extreme risk for defense supply
     chain integrity.
  3. Even terminated registrations reveal historical foreign influence ties.

API Documentation: https://efile.fara.gov/ords/fara/r/fara_ws/api/endpoints
Rate limit: 5 requests per 10 seconds. No authentication required.

Endpoints used:
  GET /api/v1/Registrants/json/Active       -> all active registrants
  GET /api/v1/Registrants/json/Terminated   -> all terminated registrants
  GET /api/v1/ForeignPrincipals/json/Active/{regNum}  -> foreign principals
"""

import json
import re
import time
import urllib.request
import urllib.error
import urllib.parse

from . import EnrichmentResult, Finding

# ---- API endpoints ----
BASE = "https://efile.fara.gov"
ACTIVE_REGISTRANTS   = f"{BASE}/api/v1/Registrants/json/Active"
TERMINATED_REGISTRANTS = f"{BASE}/api/v1/Registrants/json/Terminated"
ACTIVE_FP_TEMPLATE   = f"{BASE}/api/v1/ForeignPrincipals/json/Active/{{reg_num}}"
FARA_SEARCH_URL = "https://efile.fara.gov/ords/fara/f?p=1235:10"

USER_AGENT = "Xiphos-Vetting/2.5"
TIMEOUT = 20

# Adversarial nations for severity escalation (defense acquisition context)
ADVERSARIAL_NATIONS = {
    "russia", "russian federation",
    "china", "people's republic of china",
    "iran", "islamic republic of iran",
    "north korea", "democratic people's republic of korea",
    "syria", "syrian arab republic",
    "cuba",
    "venezuela",
}


def _normalize(name: str) -> str:
    """Strip legal suffixes and punctuation for fuzzy comparison."""
    name = name.lower().strip()
    name = re.sub(
        r'\b(inc|llc|ltd|plc|corp|co|sa|gmbh|ag|nv|bv|pllc|lp|'
        r'assoc|associates|foundation|agency|association|group)\b\.?',
        '', name,
    )
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _name_score(query: str, candidate: str) -> float:
    """Fuzzy match: exact, substring, then token-overlap (Dice coefficient)."""
    q = _normalize(query)
    c = _normalize(candidate)
    if not q or not c:
        return 0.0

    if q == c:
        return 1.0

    # Substring containment
    if q in c or c in q:
        return min(len(q), len(c)) / max(len(q), len(c))

    # Token overlap (Dice)
    qt = set(q.split())
    ct = set(c.split())
    if not qt or not ct:
        return 0.0
    return 2 * len(qt & ct) / (len(qt) + len(ct))


def _get_json(url: str) -> dict | list | None:
    """Fetch JSON from FARA API."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, json.JSONDecodeError, ValueError):
        return None


def _fetch_registrants(url: str) -> list[dict]:
    """Parse the FARA registrant list response."""
    data = _get_json(url)
    if not data or not isinstance(data, dict):
        return []
    # Response shape: { "REGISTRANTS_ACTIVE": { "ROW": [...] } }
    # or             { "REGISTRANTS_TERMINATED": { "ROW": [...] } }
    for key in data:
        inner = data[key]
        if isinstance(inner, dict) and "ROW" in inner:
            rows = inner["ROW"]
            return rows if isinstance(rows, list) else [rows]
    return []


def _is_adversarial(country: str) -> bool:
    """Check if a country name matches the adversarial nations list."""
    c = country.lower().strip()
    return any(adv in c for adv in ADVERSARIAL_NATIONS)


def _assess_severity(status: str, country: str) -> tuple[str, str]:
    """
    Map (registration status, foreign principal country) to severity + reason.
    """
    active = status.lower() in ("active", "current", "")
    adversarial = _is_adversarial(country)

    if active and adversarial:
        return "critical", f"Active FARA registration with adversarial nation: {country}"
    if active:
        return "high", f"Active FARA registration as foreign agent for: {country}"
    if adversarial:
        return "high", f"Terminated FARA registration with adversarial nation: {country}"
    return "medium", f"Terminated FARA registration (historical) for: {country}"


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """
    Query FARA for foreign-agent registrations matching vendor_name.

    Strategy:
      1. Fetch all active registrants (small list, ~500-600 entries).
      2. Fuzzy-match vendor name against registrant names.
      3. For matches, fetch their active foreign principals to get countries.
      4. Optionally check terminated registrants if no active match found.
    """
    t0 = time.time()
    result = EnrichmentResult(source="fara", vendor_name=vendor_name)
    match_threshold = 0.70

    try:
        # ---- Step 1: fetch active registrants and match ----
        active_regs = _fetch_registrants(ACTIVE_REGISTRANTS)
        matches: list[dict] = []

        for reg in active_regs:
            name = str(reg.get("Name", ""))
            score = _name_score(vendor_name, name)
            if score >= match_threshold:
                matches.append({
                    "name": name,
                    "reg_num": reg.get("Registration_Number"),
                    "reg_date": reg.get("Registration_Date", ""),
                    "status": "Active",
                    "city": reg.get("City", ""),
                    "state": reg.get("State", ""),
                    "score": score,
                })

        # ---- Step 2: if no active match, check terminated ----
        if not matches:
            time.sleep(0.5)  # rate limit: 5 req / 10s
            terminated_regs = _fetch_registrants(TERMINATED_REGISTRANTS)
            for reg in terminated_regs:
                name = str(reg.get("Name", ""))
                score = _name_score(vendor_name, name)
                if score >= match_threshold:
                    matches.append({
                        "name": name,
                        "reg_num": reg.get("Registration_Number"),
                        "reg_date": reg.get("Registration_Date", ""),
                        "status": "Terminated",
                        "city": reg.get("City", ""),
                        "state": reg.get("State", ""),
                        "score": score,
                    })

        if not matches:
            result.findings.append(Finding(
                source="fara",
                category="foreign_agent",
                title="No FARA registrations found",
                detail=(
                    f"'{vendor_name}' not found among active or terminated "
                    f"DOJ FARA registrants. No foreign agent activity detected."
                ),
                severity="info",
                confidence=0.85,
                url=FARA_SEARCH_URL,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # ---- Step 3: for each match, fetch foreign principals ----
        for match in matches[:5]:  # cap at 5 to respect rate limits
            reg_num = match["reg_num"]
            principals = []

            if reg_num and match["status"] == "Active":
                time.sleep(0.5)  # rate limit
                fp_url = ACTIVE_FP_TEMPLATE.format(reg_num=reg_num)
                fp_data = _get_json(fp_url)
                if fp_data and isinstance(fp_data, dict):
                    rowset = fp_data.get("ROWSET", {})
                    rows = rowset.get("ROW", [])
                    if isinstance(rows, dict):
                        rows = [rows]
                    principals = rows

            # Build findings from foreign principal data
            if principals:
                for fp in principals:
                    fp_name = fp.get("FP_NAME", "Unknown")
                    fp_country = fp.get("COUNTRY_NAME", "Unknown")
                    severity, reason = _assess_severity(match["status"], fp_country)

                    detail_lines = [
                        f"Registrant: {match['name']}",
                        f"Registration #: {reg_num}",
                        f"Status: {match['status']}",
                        f"Registered: {match['reg_date']}",
                        f"Foreign Principal: {fp_name}",
                        f"Principal Country: {fp_country}",
                        f"Match Score: {match['score']:.0%}",
                    ]

                    result.findings.append(Finding(
                        source="fara",
                        category="foreign_agent",
                        title=f"FARA: {match['name']} -> {fp_country} ({fp_name})",
                        detail="\n".join(detail_lines),
                        severity=severity,
                        confidence=min(match["score"], 0.95),
                        url=FARA_SEARCH_URL,
                        raw_data={
                            "registrant_name": match["name"],
                            "registration_number": reg_num,
                            "status": match["status"],
                            "foreign_principal": fp_name,
                            "country": fp_country,
                            "match_score": match["score"],
                        },
                    ))

                    result.risk_signals.append({
                        "signal": "fara_registrant",
                        "severity": severity,
                        "detail": reason,
                        "registrant_name": match["name"],
                        "registration_number": reg_num,
                        "foreign_principal": fp_name,
                        "foreign_principal_country": fp_country,
                        "status": match["status"],
                        "match_score": match["score"],
                    })

                    # Track adversarial connections
                    if _is_adversarial(fp_country):
                        result.risk_signals.append({
                            "signal": "fara_adversarial_nation",
                            "severity": "critical",
                            "detail": (
                                f"FARA registrant {match['name']} represents "
                                f"{fp_name} ({fp_country})"
                            ),
                            "country": fp_country,
                        })
            else:
                # Match but no foreign principal detail available
                severity = "high" if match["status"] == "Active" else "medium"
                result.findings.append(Finding(
                    source="fara",
                    category="foreign_agent",
                    title=f"FARA REGISTRANT: {match['name']} ({match['status']})",
                    detail=(
                        f"Registrant: {match['name']}\n"
                        f"Registration #: {reg_num}\n"
                        f"Status: {match['status']}\n"
                        f"Registered: {match['reg_date']}\n"
                        f"Match Score: {match['score']:.0%}"
                    ),
                    severity=severity,
                    confidence=min(match["score"], 0.90),
                    url=FARA_SEARCH_URL,
                    raw_data={
                        "registrant_name": match["name"],
                        "registration_number": reg_num,
                        "status": match["status"],
                        "match_score": match["score"],
                    },
                ))

                result.risk_signals.append({
                    "signal": "fara_registrant",
                    "severity": severity,
                    "detail": f"{match['status']} FARA registrant: {match['name']}",
                    "registrant_name": match["name"],
                    "registration_number": reg_num,
                    "status": match["status"],
                    "match_score": match["score"],
                })

            # Track identifiers
            if reg_num:
                result.identifiers["fara_registration_number"] = str(reg_num)

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
