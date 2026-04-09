"""
SAM.gov Connector

Queries the GSA Entity Management API for:
  - Entity registration status (UEI, CAGE, DUNS)
  - Exclusion records (debarment, suspension, ineligibility)
  - Entity details (address, business type, NAICS / PSC when present)
  - Responsibility & integrity records, proceedings, and corporate relationships

Free public API: 10 requests/day without key, 1000/day with key.
API docs: https://open.gsa.gov/api/entity-api/
"""

import os
import time
import urllib.parse
from datetime import datetime, timezone

from http_transport import curl_json_get
from secure_runtime_env import ensure_runtime_env_loaded

from . import EnrichmentResult, Finding

# Public API base -- no key needed for basic access (10/day)
BASE = "https://api.sam.gov/entity-information/v4"
EXCLUSIONS_BASE = "https://api.sam.gov/entity-information/v4/exclusions"

# For higher rate limits, set XIPHOS_SAM_API_KEY. Keep legacy aliases working
# so local tooling and older deploy notes do not silently break lookups.
API_KEY = os.environ.get("XIPHOS_SAM_API_KEY", "")

USER_AGENT = "Xiphos-Vetting/2.1"
_RATE_LIMIT_UNTIL: str = ""
ENTITY_TIMEOUT_SECONDS = float(os.environ.get("XIPHOS_SAM_ENTITY_TIMEOUT_SECONDS", "8"))
EXCLUSIONS_TIMEOUT_SECONDS = float(os.environ.get("XIPHOS_SAM_EXCLUSIONS_TIMEOUT_SECONDS", "6"))
BETWEEN_CALL_DELAY_SECONDS = float(os.environ.get("XIPHOS_SAM_BETWEEN_CALL_DELAY_SECONDS", "0.05"))
ENTITY_INCLUDE_SECTIONS = os.environ.get("XIPHOS_SAM_ENTITY_INCLUDE_SECTIONS", "").strip()
ENTITY_SUFFIXES = {
    "llc", "llp", "lp", "ltd", "inc", "co", "corp", "corporation",
    "incorporated", "limited", "company", "plc", "sa", "ag", "gmbh",
    "bv", "nv", "pty", "srl", "spa", "ab", "oy", "as", "se",
    "group", "holdings", "partners", "associates", "the",
}


def _sam_entity_url(uei: str) -> str:
    return f"https://sam.gov/entity/{uei}" if uei else "https://sam.gov/"


def _get_api_key() -> str:
    ensure_runtime_env_loaded(("XIPHOS_SAM_API_KEY", "SAM_GOV_API_KEY", "XIPHOS_SAM_GOV_API_KEY"))
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
            f"SAM.gov rate limit reached. API access resumes at {_RATE_LIMIT_UNTIL}."
            if _RATE_LIMIT_UNTIL
            else "SAM.gov rate limit reached."
        ),
    }


def _get(url: str, *, skip_accept_header: bool = False, timeout_seconds: float = 20) -> tuple[dict | None, dict]:
    """GET with optional API key and explicit status metadata.

    Args:
        skip_accept_header: If True, omit the ``Accept: application/json``
            header.  The SAM.gov exclusions endpoint returns HTTP 406 when
            that header is present, even though it serves JSON by default.
    """
    if _rate_limit_active():
        return None, _rate_limit_meta()

    api_key = _get_api_key()
    if api_key:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}api_key={api_key}"

    headers = {"User-Agent": USER_AGENT}
    if not skip_accept_header:
        headers["Accept"] = "application/json"
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
                "error": message or f"SAM.gov entity API returned HTTP {meta['status']}.",
            }
        if meta["status"] == 0:
            raise RuntimeError(meta["error"] or "curl transport returned no status.")
        return payload, {"status": meta["status"], "throttled": False, "error": ""}
    except Exception as exc:
        return None, {
            "status": 0,
            "throttled": False,
            "error": f"SAM.gov entity API unavailable: {exc}",
        }


def _unwrap_search_response(value) -> tuple[list[dict], dict]:
    if isinstance(value, tuple) and len(value) == 2:
        rows, meta = value
        return list(rows or []), dict(meta or {})
    return list(value or []), {"status": 200, "throttled": False, "error": ""}


def _strip_entity_suffixes(name: str) -> list[str]:
    cleaned = urllib.parse.unquote(str(name or ""))
    cleaned = cleaned.replace("/", " ")
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in cleaned)
    words = cleaned.split()
    return [w.lower() for w in words if len(w) >= 2 and w.lower() not in ENTITY_SUFFIXES]


def _name_match_score(query: str, candidate: str) -> float:
    import difflib

    query_tokens = _strip_entity_suffixes(query)
    candidate_tokens = _strip_entity_suffixes(candidate)
    if not query_tokens or not candidate_tokens:
        return 0.0

    query_set = set(query_tokens)
    candidate_set = set(candidate_tokens)
    token_coverage = len(query_set & candidate_set) / max(1, len(query_set))
    ratio = difflib.SequenceMatcher(None, " ".join(query_tokens), " ".join(candidate_tokens)).ratio()
    if query.lower() in candidate.lower():
        return max(token_coverage, ratio, 0.95)
    return max(token_coverage, ratio)


def _is_relevant_candidate(query: str, candidate: str, threshold: float = 0.6) -> bool:
    return _name_match_score(query, candidate) >= threshold


def _entity_query_variants(name: str) -> list[str]:
    variants: list[str] = []
    raw = " ".join(str(name or "").replace("/", " ").split())
    if raw:
        variants.append(raw)
    core_tokens = _strip_entity_suffixes(raw)
    simplified = " ".join(core_tokens)
    if simplified and simplified not in variants:
        variants.append(simplified)
    if len(core_tokens) > 1:
        leading = core_tokens[0]
        if leading and leading not in variants:
            variants.append(leading)
    if raw and " and " in raw.lower():
        primary = raw.split("/", 1)[0].strip()
        if primary and primary not in variants:
            variants.append(primary)
    return variants[:3]


def _build_entity_search_url(query: str, include_sections: str = "") -> str:
    encoded = urllib.parse.quote(query)
    url = (
        f"{BASE}/entities?legalBusinessName={encoded}"
        "&registrationStatus=A"
        "&page=0&size=8"
    )
    sections = str(include_sections or "").strip()
    if sections:
        url += f"&includeSections={urllib.parse.quote(sections, safe=',')}"
    return url


def _search_entities_for_query(query: str) -> tuple[list[dict], dict]:
    """Search for entity registrations by name. Requires API key."""
    if not _get_api_key():
        return [], {"status": 0, "throttled": False, "error": "SAM.gov API key not configured."}
    url = _build_entity_search_url(query, ENTITY_INCLUDE_SECTIONS)
    data, meta = _get(url, timeout_seconds=ENTITY_TIMEOUT_SECONDS)
    if not data:
        return [], meta
    return data.get("entityData", []), meta


def _search_entities(name: str) -> tuple[list[dict], dict]:
    aggregated: list[dict] = []
    seen: set[str] = set()
    last_meta = {"status": 200, "throttled": False, "error": ""}

    for query in _entity_query_variants(name):
        rows, meta = _search_entities_for_query(query)
        last_meta = meta
        if meta.get("throttled") or meta.get("error"):
            return [], meta
        for entity in rows:
            reg = entity.get("entityRegistration", {}) or {}
            legal_name = reg.get("legalBusinessName", "")
            uei = reg.get("ueiSAM", "")
            key = uei or legal_name
            if not legal_name or not key:
                continue
            if not _is_relevant_candidate(name, legal_name, threshold=0.6):
                continue
            if key in seen:
                continue
            seen.add(key)
            aggregated.append(entity)

        if aggregated:
            break

    return aggregated, last_meta


def _search_exclusions(name: str) -> tuple[list[dict], dict]:
    """Search for exclusion records by name. Requires API key."""
    if not _get_api_key():
        return [], {"status": 0, "throttled": False, "error": "SAM.gov API key not configured."}
    encoded = urllib.parse.quote(name)
    url = f"{EXCLUSIONS_BASE}?exclusionName={encoded}&page=0&size=10"
    # skip_accept_header: SAM.gov exclusions returns 406 when
    # Accept: application/json is sent explicitly (API quirk).
    data, meta = _get(url, skip_accept_header=True, timeout_seconds=EXCLUSIONS_TIMEOUT_SECONDS)
    if not data:
        return [], meta
    return data.get("excludedEntity", data.get("results", [])), meta


def _list_dicts(value) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        found = []
        for nested in value.values():
            if isinstance(nested, list):
                found.extend(item for item in nested if isinstance(item, dict))
        return found
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _extract_registration_summary(entity: dict) -> dict:
    reg = entity.get("entityRegistration", {}) or {}
    core = entity.get("coreData", {}) or {}
    integrity = entity.get("integrityInformation", {}) or {}

    addr = reg.get("physicalAddress") or core.get("physicalAddress") or {}
    entity_structure = core.get("entityStructure") or {}
    business_types = _dedupe(
        [item.get("businessTypeDesc") for item in _list_dicts(reg.get("businessTypes"))]
        + [item.get("businessTypeDesc") for item in _list_dicts(core.get("businessTypes"))]
        + [item.get("sbaBusinessTypeDesc") for item in _list_dicts(core.get("businessTypes"))]
    )

    naics_entries = _list_dicts(core.get("naics")) + _list_dicts(core.get("naicsList"))
    psc_entries = _list_dicts(core.get("pscList")) + _list_dicts(core.get("psc")) + _list_dicts(core.get("pscInfo"))
    naics = _dedupe(
        [
            " - ".join(part for part in [item.get("naicsCode"), item.get("naicsDesc")] if part)
            for item in naics_entries
        ]
    )
    psc = _dedupe(
        [
            " - ".join(part for part in [item.get("pscCode"), item.get("pscDescription") or item.get("pscDesc")] if part)
            for item in psc_entries
        ]
    )

    proceedings = integrity.get("proceedingsData") or {}
    corporate = integrity.get("corporateRelationships") or {}
    highest_owner = corporate.get("highestOwner") or {}
    immediate_owner = corporate.get("immediateOwner") or {}

    return {
        "uei": reg.get("ueiSAM", ""),
        "cage": reg.get("cageCode", ""),
        "legal_name": reg.get("legalBusinessName", ""),
        "dba_name": reg.get("dbaName", ""),
        "status": reg.get("registrationStatus", ""),
        "purpose": reg.get("purposeOfRegistrationDesc", ""),
        "entity_url": reg.get("entityURL", ""),
        "expiry": reg.get("registrationExpirationDate", ""),
        "registration_date": reg.get("registrationDate", ""),
        "uei_status": reg.get("ueiStatus", ""),
        "public_display_flag": reg.get("publicDisplayFlag", ""),
        "exclusion_status_flag": reg.get("exclusionStatusFlag", ""),
        "state_of_incorporation": entity_structure.get("stateOfIncorporationDesc", ""),
        "country_of_incorporation": entity_structure.get("countryOfIncorporationDesc", ""),
        "company_security_level": entity_structure.get("companySecurityLevelDesc", ""),
        "highest_employee_security_level": entity_structure.get("highestEmployeeSecurityLevelDesc", ""),
        "business_types": business_types,
        "naics": naics,
        "psc": psc,
        "location": {
            "city": addr.get("city", ""),
            "state_or_province": addr.get("stateOrProvinceCode", ""),
            "country": addr.get("countryCode", ""),
            "zip_code": addr.get("zipCode", ""),
        },
        "proceedings_count": proceedings.get("proceedingsRecordCount", 0) or 0,
        "responsibility_information_count": integrity.get("responsibilityInformationCount", 0) or 0,
        "highest_owner": {
            "name": highest_owner.get("legalBusinessName", ""),
            "cage": highest_owner.get("cageCode", ""),
            "integrity_records": highest_owner.get("integrityRecords", ""),
        },
        "immediate_owner": {
            "name": immediate_owner.get("legalBusinessName", ""),
            "cage": immediate_owner.get("cageCode", ""),
            "integrity_records": immediate_owner.get("integrityRecords", ""),
        },
    }


def _build_owner_relationship(
    *,
    vendor_name: str,
    vendor_country: str,
    uei: str,
    cage: str,
    owner_name: str,
    owner_cage: str,
    owner_level: str,
    rel_type: str,
    confidence: float,
    evidence: str,
) -> dict:
    structured_fields = {
        "standards": ["SAM.gov"],
        "relationship_scope": owner_level,
        "uei": uei,
    }
    if cage:
        structured_fields["vendor_cage"] = cage
    if owner_cage:
        structured_fields["owner_cage"] = owner_cage

    target_identifiers = {}
    if owner_cage:
        target_identifiers["cage"] = owner_cage

    return {
        "type": rel_type,
        "source_entity": vendor_name,
        "source_entity_type": "company",
        "source_identifiers": {
            key: value
            for key, value in {"uei": uei, "cage": cage}.items()
            if value
        },
        "target_entity": owner_name,
        "target_entity_type": "holding_company",
        "target_identifiers": target_identifiers,
        "country": vendor_country,
        "data_source": "sam_gov",
        "confidence": confidence,
        "evidence": evidence,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "artifact_ref": f"sam.gov://{uei}/{owner_level}/{owner_name}",
        "evidence_url": _sam_entity_url(uei),
        "evidence_title": "SAM.gov corporate relationship context",
        "structured_fields": structured_fields,
        "source_class": "gated_federal_source",
        "authority_level": "official_registry",
        "access_model": "public_api",
    }


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query SAM.gov for entity registration and exclusion data."""
    t0 = time.time()
    result = EnrichmentResult(source="sam_gov", vendor_name=vendor_name)
    result.structured_fields = {"entity_matches": []}

    try:
        # SAM.gov requires a free API key from https://sam.gov/content/entity-information
        if not _get_api_key():
            result.findings.append(Finding(
                source="sam_gov", category="configuration",
                title="SAM.gov API key not configured",
                detail="Set XIPHOS_SAM_API_KEY environment variable with a free key from "
                       "https://sam.gov/content/entity-information to enable SAM.gov lookups. "
                       "Free tier: 10 requests/day. Production: 1,000/day.",
                severity="info", confidence=1.0,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Step 1: Search for entity registration
        entities, entity_meta = _unwrap_search_response(_search_entities(vendor_name))

        if entities:
            for entity in entities[:3]:
                summary = _extract_registration_summary(entity)
                uei = summary["uei"]
                cage = summary["cage"]
                entity_url = summary.get("entity_url", "")
                legal_name = summary["legal_name"]
                status = summary["status"]
                expiry = summary["expiry"]
                purpose = summary["purpose"]
                location = summary["location"]
                result.structured_fields["entity_matches"].append(summary)

                if uei:
                    result.identifiers["uei"] = uei
                if cage:
                    result.identifiers["cage"] = cage
                if entity_url and entity_url.startswith("http"):
                    result.identifiers["website"] = entity_url
                    result.identifiers["sam_website"] = entity_url

                detail_parts = [
                    f"UEI: {uei or 'N/A'}",
                    f"CAGE: {cage or 'N/A'}",
                    f"Status: {status or 'Unknown'}",
                    f"Expires: {expiry or 'N/A'}",
                    f"Location: {location.get('city', '')}, {location.get('state_or_province', '')} {location.get('country', '')} {location.get('zip_code', '')}".strip(", "),
                    f"Purpose: {purpose or 'N/A'}",
                ]
                if summary["business_types"]:
                    detail_parts.append(f"Business types: {', '.join(summary['business_types'][:4])}")
                if summary["naics"]:
                    detail_parts.append(f"NAICS: {', '.join(summary['naics'][:3])}")
                if summary["psc"]:
                    detail_parts.append(f"PSC: {', '.join(summary['psc'][:3])}")
                if summary["company_security_level"]:
                    detail_parts.append(f"Company security level: {summary['company_security_level']}")

                result.findings.append(Finding(
                    source="sam_gov", category="registration",
                    title=f"SAM authority record: {legal_name}",
                    detail=" | ".join(part for part in detail_parts if part and not part.endswith(": ")),
                    severity="info", confidence=0.9,
                    url=f"https://sam.gov/entity/{uei}",
                    raw_data=summary,
                    structured_fields=summary,
                ))

                # Check registration health
                if status != "Active":
                    result.risk_signals.append({
                        "signal": "sam_inactive_registration",
                        "severity": "high",
                        "detail": f"SAM registration status: {status}",
                    })
                    result.findings.append(Finding(
                        source="sam_gov", category="registration",
                        title=f"SAM registration not active: {status}",
                        detail=f"Entity '{legal_name}' has SAM status '{status}'. Active registration required for federal contracts.",
                        severity="high", confidence=0.9,
                    ))

                integrity_count = int(summary["responsibility_information_count"] or 0)
                proceedings_count = int(summary["proceedings_count"] or 0)
                if integrity_count > 0 or proceedings_count > 0:
                    owner_flags = []
                    if summary["highest_owner"]["name"]:
                        owner_flags.append(
                            f"highest owner {summary['highest_owner']['name']} (integrity records: {summary['highest_owner']['integrity_records'] or 'N/A'})"
                        )
                    if summary["immediate_owner"]["name"]:
                        owner_flags.append(
                            f"immediate owner {summary['immediate_owner']['name']} (integrity records: {summary['immediate_owner']['integrity_records'] or 'N/A'})"
                        )
                    result.findings.append(Finding(
                        source="sam_gov",
                        category="integrity",
                        title="SAM responsibility and integrity records present",
                        detail=(
                            f"Responsibility records: {integrity_count} | Proceedings: {proceedings_count}"
                            + (f" | Corporate relationship context: {'; '.join(owner_flags)}" if owner_flags else "")
                        ),
                        severity="high" if integrity_count > 0 else "medium",
                        confidence=0.88,
                        url=f"https://sam.gov/entity/{uei}",
                        raw_data=summary,
                        structured_fields={
                            "responsibility_information_count": integrity_count,
                            "proceedings_count": proceedings_count,
                            "highest_owner": summary["highest_owner"],
                            "immediate_owner": summary["immediate_owner"],
                        },
                    ))
                    result.risk_signals.append({
                        "signal": "sam_integrity_records",
                        "severity": "high" if integrity_count > 0 else "medium",
                        "detail": f"SAM responsibility records={integrity_count}, proceedings={proceedings_count}",
                    })

                if summary["highest_owner"]["name"] or summary["immediate_owner"]["name"]:
                    result.findings.append(Finding(
                        source="sam_gov",
                        category="ownership",
                        title="SAM corporate relationship context available",
                        detail=(
                            f"Highest owner: {summary['highest_owner']['name'] or 'N/A'} | "
                            f"Immediate owner: {summary['immediate_owner']['name'] or 'N/A'}"
                        ),
                        severity="info",
                        confidence=0.82,
                        url=f"https://sam.gov/entity/{uei}",
                        raw_data=summary,
                        structured_fields={
                            "highest_owner": summary["highest_owner"],
                            "immediate_owner": summary["immediate_owner"],
                        },
                    ))

                immediate_owner_name = summary["immediate_owner"]["name"]
                if immediate_owner_name:
                    result.relationships.append({
                        **_build_owner_relationship(
                            vendor_name=legal_name or vendor_name,
                            vendor_country=location.get("country", "") or country,
                            uei=uei,
                            cage=cage,
                            owner_name=immediate_owner_name,
                            owner_cage=summary["immediate_owner"]["cage"],
                            owner_level="immediate_owner",
                            rel_type="owned_by",
                            confidence=0.91,
                            evidence=(
                                f"SAM.gov identifies {immediate_owner_name} as the immediate owner of "
                                f"{legal_name or vendor_name}."
                            ),
                        ),
                        "raw_data": {
                            "owner_name": immediate_owner_name,
                            "owner_cage": summary["immediate_owner"]["cage"],
                            "owner_level": "immediate_owner",
                        },
                    })

                highest_owner_name = summary["highest_owner"]["name"]
                if highest_owner_name and highest_owner_name != immediate_owner_name:
                    result.relationships.append({
                        **_build_owner_relationship(
                            vendor_name=legal_name or vendor_name,
                            vendor_country=location.get("country", "") or country,
                            uei=uei,
                            cage=cage,
                            owner_name=highest_owner_name,
                            owner_cage=summary["highest_owner"]["cage"],
                            owner_level="highest_owner",
                            rel_type="beneficially_owned_by",
                            confidence=0.86,
                            evidence=(
                                f"SAM.gov identifies {highest_owner_name} as the highest owner of "
                                f"{legal_name or vendor_name}."
                            ),
                        ),
                        "raw_data": {
                            "owner_name": highest_owner_name,
                            "owner_cage": summary["highest_owner"]["cage"],
                            "owner_level": "highest_owner",
                        },
                    })

        elif entity_meta.get("throttled"):
            detail = entity_meta.get("error") or "SAM.gov rate limit reached."
            if entity_meta.get("next_access_time"):
                detail += " This registration lookup should be retried after the quota window resets."
            result.error = detail
            result.structured_fields["sam_api_status"] = {
                "entity_lookup": dict(entity_meta),
            }
            result.findings.append(Finding(
                source="sam_gov",
                category="availability",
                title="SAM.gov registration lookup deferred by rate limit",
                detail=detail,
                severity="info",
                confidence=1.0,
                structured_fields=dict(entity_meta),
            ))
        elif entity_meta.get("error"):
            detail = str(entity_meta.get("error"))
            result.error = detail
            result.structured_fields["sam_api_status"] = {
                "entity_lookup": dict(entity_meta),
            }
            result.findings.append(Finding(
                source="sam_gov",
                category="availability",
                title="SAM.gov registration lookup unavailable",
                detail=detail,
                severity="info",
                confidence=0.35,
                structured_fields=dict(entity_meta),
            ))
        else:
            result.findings.append(Finding(
                source="sam_gov", category="registration",
                title="No SAM registration found",
                detail=f"No active SAM.gov entity registration found for '{vendor_name}'. "
                       f"Entity may not be registered for federal contracting.",
                severity="medium" if country in ("US", "USA", "") else "info",
                confidence=0.6,
            ))

        if BETWEEN_CALL_DELAY_SECONDS > 0:
            time.sleep(BETWEEN_CALL_DELAY_SECONDS)

        # Step 2: Check exclusions (debarment, suspension)
        exclusions, exclusion_meta = _unwrap_search_response(_search_exclusions(vendor_name))

        if exclusions:
            for exc in exclusions:
                exc_name = exc.get("name", "")
                exc_type = exc.get("exclusionType", "")
                exc_program = exc.get("exclusionProgram", "")
                agency = exc.get("excludingAgency", "")
                active_date = exc.get("activeDate", "")
                termination_date = exc.get("terminationDate", "")
                classification = exc.get("classification", {})
                class_type = classification.get("type", "")

                severity = "critical"
                if termination_date and termination_date < time.strftime("%Y-%m-%d"):
                    severity = "medium"  # Historical exclusion

                result.findings.append(Finding(
                    source="sam_gov", category="exclusion",
                    title=f"EXCLUSION: {exc_name} -- {exc_type}",
                    detail=(
                        f"Type: {exc_type} | Program: {exc_program} | Agency: {agency} | "
                        f"Active: {active_date} | Terminates: {termination_date or 'Indefinite'} | "
                        f"Classification: {class_type}"
                    ),
                    severity=severity, confidence=0.85,
                    url="https://sam.gov/search/?page=1&pageSize=25&sort=-relevance&sfm%5Bstatus%5D%5Bis_active%5D=true&sfm%5BsimpleSearch%5D%5BkeywordRadio%5D=ALL",
                    raw_data=exc,
                ))

                result.risk_signals.append({
                    "signal": "sam_exclusion",
                    "severity": severity,
                    "detail": f"{exc_type} by {agency}, active since {active_date}",
                })
        elif exclusion_meta.get("throttled"):
            detail = exclusion_meta.get("error") or "SAM.gov exclusions lookup rate-limited."
            if not result.error:
                result.error = detail
            result.structured_fields.setdefault("sam_api_status", {})["exclusions_lookup"] = dict(exclusion_meta)
            result.findings.append(Finding(
                source="sam_gov",
                category="availability",
                title="SAM.gov exclusions lookup deferred by rate limit",
                detail=detail,
                severity="info",
                confidence=1.0,
                structured_fields=dict(exclusion_meta),
            ))
        elif exclusion_meta.get("error"):
            detail = str(exclusion_meta.get("error"))
            if not result.error:
                result.error = detail
            result.structured_fields.setdefault("sam_api_status", {})["exclusions_lookup"] = dict(exclusion_meta)
            result.findings.append(Finding(
                source="sam_gov",
                category="availability",
                title="SAM.gov exclusions lookup unavailable",
                detail=detail,
                severity="info",
                confidence=0.35,
                structured_fields=dict(exclusion_meta),
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
