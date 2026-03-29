"""
GLEIF LEI Connector - LIVE API

Real-time queries to the Global LEI Foundation API for:
  - Legal Entity Identifier validation and lookup
  - Direct and ultimate parent relationships
  - Registration status (active, lapsed, retired)
  - Entity legal form and jurisdiction

Free API, no registration required.
API: https://api.gleif.org/api/v1
"""

import difflib
import json
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from . import EnrichmentResult, Finding

BASE = "https://api.gleif.org/api/v1"
USER_AGENT = "Xiphos/4.0 (compliance-tool@xiphos.dev)"
ENTITY_SUFFIXES = {
    "llc", "llp", "lp", "ltd", "inc", "co", "corp", "corporation",
    "incorporated", "limited", "company", "plc", "sa", "ag", "gmbh",
    "bv", "nv", "pty", "srl", "spa", "ab", "oy", "as", "se",
    "group", "holdings", "partners", "associates", "the",
}


def _strip_entity_suffixes(name: str) -> list[str]:
    cleaned = re.sub(r"[,.\-&/()']", " ", str(name or ""))
    words = cleaned.split()
    return [w.lower() for w in words if len(w) >= 2 and w.lower() not in ENTITY_SUFFIXES]


def _name_match_score(query: str, candidate: str) -> float:
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


def _candidate_country(entity: dict) -> str:
    legal_country = str((entity.get("legalAddress") or {}).get("country") or "").upper()
    if legal_country:
        return legal_country
    hq_country = str((entity.get("headquartersAddress") or {}).get("country") or "").upper()
    if hq_country:
        return hq_country
    jurisdiction = str(entity.get("jurisdiction") or "").upper()
    if jurisdiction.startswith("US"):
        return "US"
    return jurisdiction[:2] if len(jurisdiction) >= 2 else ""


def _pick_best_lei_record(records: list[dict], vendor_name: str, country: str = "") -> dict | None:
    normalized_country = str(country or "").upper()
    scored: list[tuple[float, dict]] = []
    for record in records:
        attrs = record.get("attributes", {}) or {}
        entity = attrs.get("entity", {}) or {}
        legal_name = entity.get("legalName", {})
        if isinstance(legal_name, dict):
            legal_name = legal_name.get("name", "")
        legal_name = str(legal_name or "")
        if not legal_name:
            continue

        score = _name_match_score(vendor_name, legal_name)
        candidate_country = _candidate_country(entity)
        candidate_jurisdiction = str(entity.get("jurisdiction") or "").upper()

        if normalized_country:
            same_country = candidate_country == normalized_country or candidate_jurisdiction.startswith(normalized_country)
            if same_country:
                score += 0.08
            elif normalized_country == "US":
                score -= 0.18
            else:
                score -= 0.08

        scored.append((score, record))

    if not scored:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_record = scored[0]
    best_entity = ((best_record.get("attributes") or {}).get("entity") or {})
    best_country = _candidate_country(best_entity)
    best_jurisdiction = str(best_entity.get("jurisdiction") or "").upper()

    if best_score < 0.72:
        return None
    if normalized_country == "US" and best_country != "US" and not best_jurisdiction.startswith("US"):
        return None
    return best_record


def _get(url: str) -> dict | None:
    """GET request to GLEIF API with proper headers."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.api+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            # Detect HTML responses (API redirect/deprecation)
            if "html" in content_type.lower() or raw[:20].startswith(b"<!DOCTYPE"):
                return None
            return json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _gleif_record_url(lei: str) -> str:
    return f"https://search.gleif.org/#/record/{lei}"


def _build_ownership_relationship(
    *,
    vendor_name: str,
    vendor_lei: str,
    vendor_country: str,
    rel_type: str,
    target_lei: str,
    target_name: str,
    target_country: str,
    evidence: str,
    confidence: float,
    valid_from: str,
    relationship_scope: str,
) -> dict:
    return {
        "type": rel_type,
        "source_entity": vendor_name,
        "source_entity_type": "company",
        "source_identifiers": {"lei": vendor_lei},
        "target_entity": target_name or target_lei,
        "target_entity_type": "holding_company",
        "target_identifiers": {"lei": target_lei},
        "country": target_country or vendor_country,
        "data_source": "gleif_lei",
        "confidence": confidence,
        "evidence": evidence,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "valid_from": valid_from,
        "artifact_ref": f"gleif://{vendor_lei}/{relationship_scope}/{target_lei}",
        "evidence_url": _gleif_record_url(target_lei),
        "evidence_title": "GLEIF Level 2 ownership path",
        "structured_fields": {
            "standards": ["GLEIF Level 2"],
            "relationship_scope": relationship_scope,
            "vendor_lei": vendor_lei,
            "target_lei": target_lei,
        },
        "source_class": "public_connector",
        "authority_level": "official_registry",
        "access_model": "public_api",
    }


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query GLEIF API for LEI data and ownership chains."""
    t0 = time.time()
    result = EnrichmentResult(source="gleif_lei", vendor_name=vendor_name)

    try:
        lei = ids.get("lei")

        # Step 1: Search for LEI if not provided - LIVE API call
        if not lei:
            encoded_name = urllib.parse.quote(vendor_name)
            url = f"{BASE}/lei-records?filter[fulltext]={encoded_name}&page[size]=8"

            records_data = _get(url)
            if records_data and "data" in records_data:
                records = records_data.get("data", [])
                best_record = _pick_best_lei_record(records, vendor_name, country=country)
                if best_record:
                    lei = best_record.get("id", "")

        if not lei:
            result.findings.append(Finding(
                source="gleif_lei", category="identity",
                title="No high-confidence LEI found",
                detail=f"No high-confidence Legal Entity Identifier match found for '{vendor_name}' in GLEIF API.",
                severity="info", confidence=0.7,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Step 2: Get full LEI record - LIVE API call
        url = f"{BASE}/lei-records/{lei}"
        record = _get(url)

        if record and "data" in record:
            data = record["data"]
            attrs = data.get("attributes", {})
            entity = attrs.get("entity", {})
            reg = attrs.get("registration", {})

            legal_name = entity.get("legalName", {}).get("name", "") if isinstance(entity.get("legalName"), dict) else str(entity.get("legalName", ""))
            legal_jurisdiction = entity.get("jurisdiction", "")
            legal_form = entity.get("legalForm", {}).get("id", "") if isinstance(entity.get("legalForm"), dict) else str(entity.get("legalForm", ""))
            status = entity.get("status", "")
            reg_status = reg.get("status", "")
            initial_reg = reg.get("initialRegistrationDate", "")
            next_renewal = reg.get("nextRenewalDate", "")

            # Addresses
            legal_addr = entity.get("legalAddress", {})
            hq_addr = entity.get("headquartersAddress", {})

            legal_country = legal_addr.get("country", "")
            hq_country = hq_addr.get("country", "")

            result.identifiers["lei"] = lei
            result.identifiers["legal_jurisdiction"] = legal_jurisdiction
            result.identifiers["legal_name"] = legal_name

            detail_parts = [
                f"LEI: {lei}",
                f"Legal Name: {legal_name}",
                f"Status: {status}",
                f"Registration Status: {reg_status}",
                f"Jurisdiction: {legal_jurisdiction}",
                f"Legal Form: {legal_form}",
                f"Registered: {initial_reg}",
                f"Next Renewal: {next_renewal}",
                f"Legal Address Country: {legal_country}",
                f"HQ Country: {hq_country}",
            ]

            result.findings.append(Finding(
                source="gleif_lei", category="identity",
                title=f"LEI verified: {legal_name}",
                detail="\n".join(detail_parts),
                severity="info", confidence=0.95,
                url=_gleif_record_url(lei),
                raw_data={"lei": lei, "status": status, "reg_status": reg_status,
                          "jurisdiction": legal_jurisdiction},
            ))

            # Check registration health
            if reg_status == "LAPSED":
                result.risk_signals.append({
                    "signal": "lei_lapsed",
                    "severity": "medium",
                    "detail": f"LEI registration lapsed - not renewed since {next_renewal}",
                })
                result.findings.append(Finding(
                    source="gleif_lei", category="data_quality",
                    title="LEI registration lapsed",
                    detail=f"LEI {lei} registration not renewed. May indicate operational changes.",
                    severity="medium", confidence=0.9,
                ))

            if status == "INACTIVE":
                result.risk_signals.append({
                    "signal": "lei_entity_inactive",
                    "severity": "high",
                    "detail": "Entity status is INACTIVE in GLEIF records",
                })

            # Jurisdiction mismatch
            if country and legal_country and country.upper() != legal_country.upper():
                result.risk_signals.append({
                    "signal": "jurisdiction_mismatch",
                    "severity": "low",
                    "detail": f"Vendor country ({country}) differs from LEI jurisdiction ({legal_country})",
                })

            time.sleep(0.15)

            # Step 3: Get parent relationships - LIVE API calls
            parent_url = f"{BASE}/lei-records/{lei}/direct-parent"
            parent_data = _get(parent_url)
            parent_lei = ""

            if parent_data and "data" in parent_data:
                parent = parent_data["data"]
                if parent:
                    parent_lei = parent.get("id", "") or ""
                    if parent_lei:
                        # Look up parent details
                        parent_detail_url = f"{BASE}/lei-records/{parent_lei}"
                        parent_detail = _get(parent_detail_url)
                        parent_name = ""
                        parent_country = ""

                        if parent_detail and "data" in parent_detail:
                            p_entity = parent_detail["data"].get("attributes", {}).get("entity", {})
                            parent_name = p_entity.get("legalName", {}).get("name", "") if isinstance(p_entity.get("legalName"), dict) else str(p_entity.get("legalName", ""))
                            parent_country = p_entity.get("legalAddress", {}).get("country", "")

                        result.findings.append(Finding(
                            source="gleif_lei", category="ownership",
                            title=f"Direct parent: {parent_name or parent_lei}",
                            detail=f"LEI: {parent_lei}\nCountry: {parent_country}",
                            severity="info", confidence=0.9,
                            url=_gleif_record_url(parent_lei),
                        ))

                        result.relationships.append({
                            **_build_ownership_relationship(
                                vendor_name=vendor_name,
                                vendor_lei=lei,
                                vendor_country=legal_country or hq_country or country.upper(),
                                rel_type="owned_by",
                                target_lei=parent_lei,
                                target_name=parent_name,
                                target_country=parent_country,
                                evidence="GLEIF Level 2 direct parent relationship from live GLEIF registry",
                                confidence=0.93,
                                valid_from=initial_reg,
                                relationship_scope="direct_parent",
                            ),
                            "raw_data": {
                                "parent_lei": parent_lei,
                                "parent_name": parent_name,
                                "parent_country": parent_country,
                            },
                        })

                        time.sleep(0.15)

            # Ultimate parent
            ultimate_url = f"{BASE}/lei-records/{lei}/ultimate-parent"
            ultimate_data = _get(ultimate_url)

            if ultimate_data and "data" in ultimate_data:
                ultimate = ultimate_data["data"]
                if ultimate:
                    ultimate_lei = ultimate.get("id", "")
                    if ultimate_lei and ultimate_lei != parent_lei:
                        ultimate_detail_url = f"{BASE}/lei-records/{ultimate_lei}"
                        ultimate_detail = _get(ultimate_detail_url)
                        ultimate_name = ""
                        ultimate_country = ""

                        if ultimate_detail and "data" in ultimate_detail:
                            u_entity = ultimate_detail["data"].get("attributes", {}).get("entity", {})
                            ultimate_name = u_entity.get("legalName", {}).get("name", "") if isinstance(u_entity.get("legalName"), dict) else str(u_entity.get("legalName", ""))
                            ultimate_country = u_entity.get("legalAddress", {}).get("country", "")

                        result.findings.append(Finding(
                            source="gleif_lei", category="ownership",
                            title=f"Ultimate parent: {ultimate_name or ultimate_lei}",
                            detail=f"LEI: {ultimate_lei}\nCountry: {ultimate_country}",
                            severity="info", confidence=0.9,
                            url=_gleif_record_url(ultimate_lei),
                        ))

                        result.relationships.append({
                            **_build_ownership_relationship(
                                vendor_name=vendor_name,
                                vendor_lei=lei,
                                vendor_country=legal_country or hq_country or country.upper(),
                                rel_type="beneficially_owned_by",
                                target_lei=ultimate_lei,
                                target_name=ultimate_name,
                                target_country=ultimate_country,
                                evidence="GLEIF Level 2 ultimate parent relationship from live GLEIF registry",
                                confidence=0.91,
                                valid_from=initial_reg,
                                relationship_scope="ultimate_parent",
                            ),
                            "raw_data": {
                                "parent_lei": ultimate_lei,
                                "parent_name": ultimate_name,
                                "parent_country": ultimate_country,
                            },
                        })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
