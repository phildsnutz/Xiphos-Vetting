"""
Xiphos Entity Resolution Layer

Resolves a user-typed entity name into canonical candidates by querying
SEC EDGAR, GLEIF, OpenCorporates, and Wikidata in parallel. Returns
candidate matches with discovered identifiers.

This sits between the Helios UI and the OSINT connectors.
"""

import re
import os
import json
import time
import sqlite3
import threading
import difflib
import requests
import concurrent.futures
from runtime_paths import get_cache_dir, get_main_db_path

TIMEOUT = 10
# Front Porch should move with partial truth, not wait on every slow registry.
RESOLUTION_TIMEOUT = float(os.environ.get("XIPHOS_ENTITY_RESOLUTION_TIMEOUT", "6"))
UA = "Xiphos/5.0 (tye.gonzalez@xiphosllc.com)"

# --- SEC EDGAR Ticker Cache ---
# The company_tickers.json file is ~5MB and updates once daily.
# Cache it locally to avoid downloading on every resolution request.
_EDGAR_CACHE_TTL = 86400  # 24 hours
_EDGAR_CACHE_DIR = get_cache_dir()
_EDGAR_CACHE_FILE = os.path.join(_EDGAR_CACHE_DIR, "company_tickers.json")
_edgar_lock = threading.Lock()
_edgar_data: dict | None = None
_edgar_loaded_at: float = 0.0
_LOCAL_VENDOR_MEMORY_LIMIT = 8


def _load_edgar_tickers() -> dict:
    """Load SEC EDGAR tickers from cache or fetch fresh. Thread-safe with 24h TTL."""
    global _edgar_data, _edgar_loaded_at

    now = time.time()

    # Fast path: in-memory cache is fresh
    if _edgar_data is not None and (now - _edgar_loaded_at) < _EDGAR_CACHE_TTL:
        return _edgar_data

    with _edgar_lock:
        # Double-check after acquiring lock
        if _edgar_data is not None and (now - _edgar_loaded_at) < _EDGAR_CACHE_TTL:
            return _edgar_data

        # Try loading from disk cache first
        try:
            if os.path.exists(_EDGAR_CACHE_FILE):
                file_age = now - os.path.getmtime(_EDGAR_CACHE_FILE)
                if file_age < _EDGAR_CACHE_TTL:
                    with open(_EDGAR_CACHE_FILE, "r") as f:
                        _edgar_data = json.load(f)
                    _edgar_loaded_at = now
                    return _edgar_data
        except Exception:
            pass

        # Fetch fresh from SEC
        try:
            resp = requests.get("https://www.sec.gov/files/company_tickers.json",
                                headers={"User-Agent": UA}, timeout=15)
            if resp.status_code == 200:
                _edgar_data = resp.json()
                _edgar_loaded_at = now

                # Persist to disk for cross-request caching
                try:
                    os.makedirs(_EDGAR_CACHE_DIR, exist_ok=True)
                    with open(_EDGAR_CACHE_FILE, "w") as f:
                        json.dump(_edgar_data, f)
                except Exception:
                    pass  # Disk write failure is non-fatal

                return _edgar_data
        except Exception:
            pass

        # Last resort: return stale in-memory data if available
        if _edgar_data is not None:
            return _edgar_data

        return {}

# Entity suffixes that should NOT drive matching on their own.
# These are legal structure designators, not meaningful name words.
ENTITY_SUFFIXES = {
    "llc", "llp", "lp", "ltd", "inc", "co", "corp", "corporation",
    "incorporated", "limited", "company", "plc", "sa", "ag", "gmbh",
    "bv", "nv", "pty", "srl", "spa", "ab", "oy", "as", "se",
    "group", "holdings", "partners", "associates", "the",
}


def _normalize_entity_name(name: str) -> str:
    tokens = _strip_entity_suffixes(name)
    if tokens:
        return " ".join(tokens)
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _safe_json_loads(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    try:
        loaded = json.loads(str(value))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _strip_entity_suffixes(name: str) -> list[str]:
    """Extract meaningful search words from entity name, stripping legal suffixes and short noise."""
    # Remove common punctuation
    cleaned = re.sub(r"[,.\-&/()']", " ", name)
    words = cleaned.split()
    # Keep words that are 2+ chars AND not entity suffixes
    meaningful = [w.lower() for w in words if len(w) >= 2 and w.lower() not in ENTITY_SUFFIXES]
    return meaningful


def _name_match_score(query: str, candidate: str) -> float:
    """Score how closely a candidate name matches the query after stripping legal suffixes."""
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


def _is_relevant_candidate(query: str, candidate: str, threshold: float = 0.55) -> bool:
    return _name_match_score(query, candidate) >= threshold


def _search_local_vendor_memory(name: str) -> list[dict]:
    """Search Helios local vendor memory before falling back to thinner public ambiguity."""
    db_path = get_main_db_path()
    if not db_path or not os.path.exists(db_path):
        return []

    raw_query = re.sub(r"\s+", " ", str(name or "").strip())
    if not raw_query:
        return []

    normalized_query = _normalize_entity_name(raw_query)
    lowered_query = raw_query.lower()
    startswith_like = f"{lowered_query}%"
    contains_like = f"%{lowered_query}%"
    candidates: list[dict] = []

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, name, country, program, profile, vendor_input, updated_at
                FROM vendors
                WHERE LOWER(name) = ?
                   OR LOWER(name) LIKE ?
                   OR LOWER(name) LIKE ?
                ORDER BY
                    CASE
                        WHEN LOWER(name) = ? THEN 0
                        WHEN LOWER(name) LIKE ? THEN 1
                        ELSE 2
                    END,
                    updated_at DESC
                LIMIT ?
                """,
                (lowered_query, startswith_like, contains_like, lowered_query, startswith_like, _LOCAL_VENDOR_MEMORY_LIMIT),
            ).fetchall()
    except Exception:
        return []

    for row in rows:
        legal_name = str(row["name"] or "").strip()
        if not legal_name:
            continue
        if not _is_relevant_candidate(name, legal_name, threshold=0.5):
            continue

        vendor_input = _safe_json_loads(row["vendor_input"])
        normalized_candidate = _normalize_entity_name(legal_name)
        match_score = _name_match_score(name, legal_name)
        exact_match = lowered_query == legal_name.lower().strip() or normalized_query == normalized_candidate
        prefix_match = bool(normalized_query and normalized_candidate.startswith(normalized_query))

        confidence = 0.78 + (match_score * 0.14)
        if exact_match:
            confidence = max(confidence, 0.99)
        elif prefix_match:
            confidence = max(confidence, 0.94)
        elif lowered_query in legal_name.lower():
            confidence = max(confidence, 0.9)

        entity_hint = str(vendor_input.get("entity_type") or vendor_input.get("industry") or "").strip()
        candidate = {
            "legal_name": legal_name,
            "country": str(row["country"] or "") or "US",
            "program": str(row["program"] or ""),
            "profile": str(row["profile"] or ""),
            "local_vendor_id": str(row["id"] or ""),
            "source": "local_vendor_memory",
            "confidence": round(min(confidence, 0.995), 3),
            "entity_type": entity_hint or "Known Vendor Memory",
        }
        website = str(vendor_input.get("website") or "").strip()
        if website:
            candidate["url"] = website
        ownership = str(vendor_input.get("ownership") or "").strip()
        if ownership:
            candidate["description"] = ownership[:180]
        candidates.append(candidate)

    return candidates


def _search_sec_edgar(name: str) -> list[dict]:
    """Search SEC EDGAR company tickers using cached data. Returns CIK, legal name, ticker for public companies."""
    candidates = []
    try:
        tickers = _load_edgar_tickers()
        if not tickers:
            return candidates

        name_lower = name.lower()
        # Extract meaningful search words (no entity suffixes like LLC, INC, CO)
        name_words = _strip_entity_suffixes(name)

        if not name_words:
            # If stripping left nothing, fall back to raw words 2+ chars
            name_words = [w.lower() for w in name.split() if len(w) >= 2]

        for _, entry in tickers.items():
            title = entry.get("title", "")
            title_lower = title.lower()
            # ALL meaningful search words must appear in the company title
            if all(w in title_lower for w in name_words):
                cik = str(entry.get("cik_str", ""))
                # Higher confidence for exact substring match
                conf = 0.9 if name_lower in title_lower else 0.65
                candidates.append({
                    "legal_name": title,
                    "cik": cik,
                    "ticker": entry.get("ticker", ""),
                    "country": "US",
                    "source": "sec_edgar",
                    "confidence": conf,
                    "entity_type": "Public Company (SEC Registrant)",
                })
                if len(candidates) >= 8:
                    break
    except Exception:
        pass
    return candidates


def _search_gleif(name: str) -> list[dict]:
    """Search GLEIF for LEI matches. Returns LEI, legal name, country.
    Post-filters results to ensure query words appear in legal name."""
    candidates = []
    try:
        # Try fulltext search (broader than exact name)
        url = f"https://api.gleif.org/api/v1/lei-records?filter[fulltext]={requests.utils.quote(name)}&page[size]=5"
        resp = requests.get(url, timeout=TIMEOUT)
        if resp.status_code == 200:
            # Split query name into words for matching
            query_words = set(name.lower().split())
            
            for record in resp.json().get("data", []):
                attrs = record.get("attributes", {})
                entity = attrs.get("entity", {})
                legal_name = entity.get("legalName", {}).get("name", "")
                lei = attrs.get("lei", "")
                country = entity.get("legalAddress", {}).get("country", "")
                status = entity.get("status", "")

                if legal_name and query_words and _is_relevant_candidate(name, legal_name, threshold=0.6):
                    match_score = _name_match_score(name, legal_name)
                    candidates.append({
                        "legal_name": legal_name,
                        "lei": lei,
                        "country": country,
                        "source": "gleif",
                        "confidence": round(min(0.95, 0.55 + (match_score * 0.4)), 2),
                        "entity_type": f"LEI Registered ({status})" if status else "LEI Registered",
                    })
    except Exception:
        pass
    return candidates


def _search_opencorporates(name: str) -> list[dict]:
    """Search OpenCorporates for company matches. Covers 200M+ companies including LLCs, LTDs, private."""
    candidates = []
    try:
        url = f"https://api.opencorporates.com/v0.4/companies/search?q={requests.utils.quote(name)}&per_page=8&order=score"
        resp = requests.get(url, timeout=TIMEOUT)
        if resp.status_code == 200:
            companies = resp.json().get("results", {}).get("companies", [])
            for item in companies:
                co = item.get("company", {})
                co_name = co.get("name", "")
                co_number = co.get("company_number", "")
                co_jurisdiction = co.get("jurisdiction_code", "").upper()
                co_status = co.get("current_status", "")
                co_type = co.get("company_type", "")
                co_inc_date = co.get("incorporation_date", "")
                co_url = co.get("opencorporates_url", "")

                # Extract country from jurisdiction (first 2 chars)
                country = co_jurisdiction[:2] if co_jurisdiction else ""

                if co_name and _is_relevant_candidate(name, co_name):
                    match_score = _name_match_score(name, co_name)
                    candidates.append({
                        "legal_name": co_name,
                        "country": country,
                        "jurisdiction": co_jurisdiction,
                        "incorporation_date": co_inc_date,
                        "company_number": co_number,
                        "company_type": co_type or "",
                        "status": co_status or "",
                        "source": "opencorporates",
                        "confidence": round(min(0.92, 0.5 + (match_score * 0.35)), 2),
                        "entity_type": f"{co_type}" if co_type else "Registered Entity",
                        "url": co_url,
                    })
    except Exception:
        pass
    return candidates


def _search_wikidata(name: str) -> list[dict]:
    """Search Wikidata for entity matches. Covers companies, organizations, agencies."""
    candidates = []
    try:
        url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={requests.utils.quote(name)}&language=en&format=json&type=item&limit=8"
        resp = requests.get(url, timeout=TIMEOUT)
        if resp.status_code == 200:
            for result in resp.json().get("search", []):
                label = result.get("label", "")
                desc = result.get("description", "")
                qid = result.get("id", "")

                if label and _is_relevant_candidate(name, label, threshold=0.58):
                    match_score = _name_match_score(name, label)
                    candidates.append({
                        "legal_name": label,
                        "wikidata_id": qid,
                        "description": desc,
                        "source": "wikidata",
                        "confidence": round(min(0.85, 0.45 + (match_score * 0.3)), 2),
                        "entity_type": desc[:50] if desc else "Wikidata Entity",
                    })
    except Exception:
        pass
    return candidates


_SAM_API_KEY = os.environ.get("XIPHOS_SAM_API_KEY", os.environ.get("SAM_GOV_API_KEY", ""))


def _search_sam_gov(name: str) -> list[dict]:
    """Search SAM.gov entity API for UEI, CAGE, registration, SBA certs,
    corporate ownership, integrity data, and business types.
    Requires XIPHOS_SAM_API_KEY (or legacy SAM_GOV_API_KEY) env var.
    Sections pulled: entityRegistration, coreData, assertions, integrityInformation.
    Get a key at https://open.gsa.gov/api/entity-api/ """
    candidates = []
    if not _SAM_API_KEY:
        return candidates

    try:
        params = {
            "api_key": _SAM_API_KEY,
            "registrationStatus": "A",
            "legalBusinessName": name,
            # Pull all high-value sections in one call
            "includeSections": "entityRegistration,coreData,assertions,integrityInformation",
            "page": "0",
            "size": "5",
        }
        resp = requests.get(
            "https://api.sam.gov/entity-information/v3/entities",
            params=params,
            timeout=15,  # Slightly longer for expanded sections
        )
        if resp.status_code == 200:
            data = resp.json()
            entities = data.get("entityData", [])
            for ent in entities:
                reg = ent.get("entityRegistration", {})
                core = ent.get("coreData", {})
                integrity = ent.get("integrityInformation", {})
                assertions = ent.get("assertions", {})

                # --- Registration ---
                legal_name = reg.get("legalBusinessName", "")
                uei = reg.get("ueiSAM", "")
                cage = reg.get("cageCode", "")
                duns = reg.get("duns", "")
                status = reg.get("registrationStatus", "")
                expiry = reg.get("registrationExpirationDate", "")
                purpose = reg.get("purposeOfRegistrationDesc", "")

                # --- Core Data ---
                phys_addr = core.get("physicalAddress", {})
                state = phys_addr.get("stateOrProvinceCode", "")
                city = phys_addr.get("city", "")
                country = phys_addr.get("countryCode", "US")

                entity_info = core.get("entityInformation", {})
                entity_type_desc = entity_info.get("entityStructureDesc", "")

                # NAICS codes
                naics_list = core.get("naicsList", [])
                primary_naics = naics_list[0].get("naicsCode", "") if naics_list else ""
                naics_codes = [n.get("naicsCode", "") for n in naics_list[:5] if n.get("naicsCode")]

                # SBA Business Types (8(a), HUBZone, SDVOSB, WOSB, etc.)
                biz_types = core.get("businessTypes", {})
                sba_types = biz_types.get("sbaBusinessTypeList", [])
                sba_labels = [t.get("sbaBusinessTypeDesc", "") for t in sba_types if t.get("sbaBusinessTypeDesc")]
                general_types = biz_types.get("businessTypeList", [])
                biz_labels = [t.get("businessTypeDesc", "") for t in general_types if t.get("businessTypeDesc")]

                # --- Integrity Information ---
                corp_rels = integrity.get("corporateRelationships", {})
                highest_owner = corp_rels.get("highestOwner", {})
                immediate_owner = corp_rels.get("immediateOwner", {})
                predecessors = corp_rels.get("predecessorsList", [])

                highest_owner_name = highest_owner.get("legalBusinessName", "")
                highest_owner_cage = highest_owner.get("cageCode", "")
                highest_owner_country = highest_owner.get("countryOfIncorporation", "")

                immediate_owner_name = immediate_owner.get("legalBusinessName", "")
                immediate_owner_cage = immediate_owner.get("cageCode", "")
                immediate_owner_country = immediate_owner.get("countryOfIncorporation", "")

                # Proceedings (legal/compliance issues)
                proceedings = integrity.get("proceedingsData", {})
                has_proceedings = bool(proceedings.get("listOfProceedings", []))

                # --- Assertions (goods/services) ---
                goods_services = assertions.get("goodsAndServices", {})
                psc_list = goods_services.get("pscList", [])
                psc_codes = [p.get("pscCode", "") for p in psc_list[:5] if p.get("pscCode")]

                if legal_name and _is_relevant_candidate(name, legal_name, threshold=0.6):
                    match_score = _name_match_score(name, legal_name)
                    candidate = {
                        "legal_name": legal_name,
                        "uei": uei,
                        "cage": cage,
                        "duns": duns,
                        "country": country,
                        "state": state,
                        "city": city,
                        "naics": primary_naics,
                        "naics_codes": naics_codes,
                        "psc_codes": psc_codes,
                        "entity_structure": entity_type_desc,
                        "registration_status": status,
                        "registration_expiry": expiry,
                        "registration_purpose": purpose,
                        "sba_certifications": sba_labels,
                        "business_types": biz_labels,
                        "source": "sam_gov",
                        "confidence": round(min(0.98, 0.65 + (match_score * 0.3)), 2),
                        "entity_type": f"SAM.gov Registered ({entity_type_desc})" if entity_type_desc else "SAM.gov Registered",
                    }

                    # Corporate ownership chain (critical for FOCI/ownership scoring)
                    if highest_owner_name:
                        candidate["highest_owner"] = highest_owner_name
                        candidate["highest_owner_cage"] = highest_owner_cage
                        candidate["highest_owner_country"] = highest_owner_country
                    if immediate_owner_name:
                        candidate["immediate_owner"] = immediate_owner_name
                        candidate["immediate_owner_cage"] = immediate_owner_cage
                        candidate["immediate_owner_country"] = immediate_owner_country
                    if predecessors:
                        candidate["predecessors"] = [p.get("legalBusinessName", "") for p in predecessors[:3]]

                    if has_proceedings:
                        candidate["has_proceedings"] = True

                    candidates.append(candidate)
    except Exception:
        pass
    return candidates


# Noise words to filter from entity resolution results
NOISE_PATTERNS = [
    "pension", "trust", "retirement", "funding", "securitization",
    "capital markets", "finance vehicle", "special purpose",
    "liquidating", "dissolved", "struck off", "receivership",
]


def _is_noise_entity(name: str) -> bool:
    """Filter out pension trusts, funding vehicles, and other non-operating entities."""
    name_lower = name.lower()
    return any(pattern in name_lower for pattern in NOISE_PATTERNS)


def resolve_entity(name: str) -> list[dict]:
    """
    Resolve a user-typed entity name into canonical candidates with identifiers.

    Queries SEC EDGAR, GLEIF, OpenCorporates, and Wikidata in parallel.
    Searches with both the full name and the core name (suffixes stripped)
    to maximize recall across registries that handle legal suffixes differently.
    Returns deduplicated candidate list sorted by confidence.
    """
    all_candidates = _search_local_vendor_memory(name)

    # Build a clean core name by stripping entity suffixes (LLC, INC, etc.)
    core_words = _strip_entity_suffixes(name)
    core_name = " ".join(core_words) if core_words else name

    # Determine search names: always include full name; add core name if different
    search_names = [name]
    if core_name.lower() != name.lower().strip():
        search_names.append(core_name)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    try:
        futures = {}
        for sn in search_names:
            # SEC EDGAR uses local word matching (already suffix-aware), only run once
            if sn == name:
                futures[executor.submit(_search_sec_edgar, name)] = "sec"
            # External APIs benefit from searching both forms
            futures[executor.submit(_search_gleif, sn)] = f"gleif({sn})"
            futures[executor.submit(_search_opencorporates, sn)] = f"oc({sn})"
            futures[executor.submit(_search_wikidata, sn)] = f"wiki({sn})"
            # SAM.gov for UEI/CAGE (only if API key configured)
            if _SAM_API_KEY and sn == name:
                futures[executor.submit(_search_sam_gov, name)] = "sam"

        done, not_done = concurrent.futures.wait(tuple(futures), timeout=RESOLUTION_TIMEOUT)

        for f in done:
            try:
                all_candidates.extend(f.result())
            except Exception:
                pass
        for f in not_done:
            f.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # Deduplicate by legal_name (merge identifiers from different sources)
    merged: dict[str, dict] = {}
    for c in all_candidates:
        key = c.get("legal_name", "").upper().strip()
        if not key or len(key) < 2:
            continue
        # Filter noise entities (pension trusts, funding vehicles, etc.)
        if _is_noise_entity(c.get("legal_name", "")):
            continue
        if key not in merged:
            merged[key] = dict(c)
        else:
            # Merge identifiers
            for field in ["cik", "lei", "ticker", "country", "jurisdiction", "wikidata_id",
                          "description", "company_number", "incorporation_date", "company_type",
                          "status", "url", "entity_type",
                          "uei", "cage", "duns", "naics", "state", "city",
                          "naics_codes", "psc_codes",
                          "entity_structure", "registration_status", "registration_expiry",
                          "registration_purpose", "sba_certifications", "business_types",
                          "highest_owner", "highest_owner_cage", "highest_owner_country",
                          "immediate_owner", "immediate_owner_cage", "immediate_owner_country",
                          "predecessors", "has_proceedings"]:
                if c.get(field) and not merged[key].get(field):
                    merged[key][field] = c[field]
            merged[key]["confidence"] = max(merged[key].get("confidence", 0), c.get("confidence", 0))
            existing_src = merged[key].get("source", "")
            new_src = c.get("source", "")
            if new_src and new_src not in existing_src:
                merged[key]["source"] = f"{existing_src},{new_src}"
                # Multi-source matches get a confidence boost
                merged[key]["confidence"] = min(1.0, merged[key]["confidence"] + 0.1)

    result = sorted(merged.values(), key=lambda x: -x.get("confidence", 0))
    return result[:12]
