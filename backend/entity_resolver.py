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
from secure_runtime_env import ensure_runtime_env_loaded

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
_GRAPH_MEMORY_LIMIT = 8
_GRAPH_RELATIONSHIP_SUMMARY_LIMIT = 3


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


def _safe_json_loads(value: object):
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return {}
    try:
        loaded = json.loads(str(value))
        return loaded if isinstance(loaded, (dict, list)) else {}
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


def _is_exact_memory_anchor(query: str, candidate: dict) -> bool:
    legal_name = str(candidate.get("legal_name") or "").strip()
    if not legal_name:
        return False
    source_tags = {
        chunk.strip().lower()
        for chunk in str(candidate.get("source") or "").split(",")
        if chunk.strip()
    }
    if not source_tags.intersection({"local_vendor_memory", "knowledge_graph"}):
        return False
    if _normalize_entity_name(query) != _normalize_entity_name(legal_name):
        return False
    if not (candidate.get("local_vendor_id") or candidate.get("graph_entity_id")):
        return False
    return float(candidate.get("confidence") or 0.0) >= 0.94


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for c in candidates:
        key = c.get("legal_name", "").upper().strip()
        if not key or len(key) < 2:
            continue
        if _is_noise_entity(c.get("legal_name", "")):
            continue
        if key not in merged:
            merged[key] = dict(c)
            continue

        existing = merged[key]
        for field in [
            "cik", "lei", "ticker", "country", "jurisdiction", "wikidata_id",
            "description", "company_number", "incorporation_date", "company_type",
            "status", "url", "entity_type",
            "uei", "cage", "duns", "naics", "state", "city",
            "naics_codes", "psc_codes",
            "entity_structure", "registration_status", "registration_expiry",
            "registration_purpose", "sba_certifications", "business_types",
            "highest_owner", "highest_owner_cage", "highest_owner_country",
            "immediate_owner", "immediate_owner_cage", "immediate_owner_country",
            "predecessors", "has_proceedings", "graph_entity_id",
            "graph_relationship_count", "graph_signal_summary",
        ]:
            if c.get(field) and not existing.get(field):
                existing[field] = c[field]
        if c.get("aliases"):
            existing_aliases = existing.get("aliases", []) or []
            combined_aliases = []
            for alias in [*existing_aliases, *c.get("aliases", [])]:
                alias_text = str(alias or "").strip()
                if alias_text and alias_text not in combined_aliases:
                    combined_aliases.append(alias_text)
            if combined_aliases:
                existing["aliases"] = combined_aliases[:8]
        if c.get("graph_relationship_count"):
            existing["graph_relationship_count"] = max(
                int(existing.get("graph_relationship_count") or 0),
                int(c.get("graph_relationship_count") or 0),
            )
        existing["confidence"] = max(existing.get("confidence", 0), c.get("confidence", 0))
        existing_src = existing.get("source", "")
        new_src = c.get("source", "")
        if new_src and new_src not in existing_src:
            existing["source"] = f"{existing_src},{new_src}"
            existing["confidence"] = min(1.0, existing["confidence"] + 0.1)

    return sorted(merged.values(), key=lambda x: -x.get("confidence", 0))


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


def _search_knowledge_graph_memory(name: str) -> list[dict]:
    """Search graph-anchored entity memory before falling back to thinner public ambiguity."""
    raw_query = re.sub(r"\s+", " ", str(name or "").strip())
    if not raw_query:
        return []

    normalized_query = _normalize_entity_name(raw_query)
    lowered_query = raw_query.lower()
    startswith_like = f"{lowered_query}%"
    contains_like = f"%{lowered_query}%"
    normalized_contains_like = f"%{normalized_query}%"

    try:
        from knowledge_graph import get_kg_conn, normalize_entity_aliases
    except Exception:
        return []

    # PostgreSQL stores aliases as JSONB, so alias search must cast to text
    # before applying LOWER(...). SQLite tolerates the cast and continues to
    # store JSON as plain text, so one query shape works across both backends.
    aliases_text_expr = "CAST(COALESCE(e.aliases, '[]') AS TEXT)"

    try:
        with get_kg_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    e.*,
                    (
                        SELECT COUNT(*)
                        FROM kg_relationships r
                        WHERE r.source_entity_id = e.id OR r.target_entity_id = e.id
                    ) AS relationship_count
                FROM kg_entities e
                WHERE LOWER(e.canonical_name) = ?
                   OR LOWER(e.canonical_name) LIKE ?
                   OR LOWER(e.canonical_name) LIKE ?
                   OR LOWER({aliases_text_expr}) LIKE ?
                ORDER BY
                    CASE
                        WHEN LOWER(e.canonical_name) = ? THEN 0
                        WHEN LOWER(e.canonical_name) LIKE ? THEN 1
                        WHEN LOWER({aliases_text_expr}) LIKE ? THEN 2
                        ELSE 3
                    END,
                    relationship_count DESC,
                    confidence DESC
                LIMIT ?
                """,
                (
                    lowered_query,
                    startswith_like,
                    contains_like,
                    normalized_contains_like,
                    lowered_query,
                    startswith_like,
                    normalized_contains_like,
                    _GRAPH_MEMORY_LIMIT,
                ),
            ).fetchall()

            candidates: list[dict] = []
            for row in rows:
                legal_name = str(row["canonical_name"] or "").strip()
                if not legal_name:
                    continue

                alias_values, _ = normalize_entity_aliases(row["aliases"], legal_name)
                match_names = [legal_name, *[str(alias).strip() for alias in alias_values if str(alias or "").strip()]]
                best_match = max((_name_match_score(raw_query, candidate_name) for candidate_name in match_names), default=0.0)
                if best_match < 0.48:
                    continue

                normalized_aliases = {_normalize_entity_name(alias) for alias in match_names if alias}
                exact_match = lowered_query == legal_name.lower().strip() or normalized_query in normalized_aliases
                prefix_match = any(alias.startswith(normalized_query) for alias in normalized_aliases if alias and normalized_query)

                relationship_count = int(row["relationship_count"] or 0)
                confidence = 0.74 + (best_match * 0.16) + min(0.06, relationship_count * 0.01)
                if exact_match:
                    confidence = max(confidence, 0.985)
                elif prefix_match:
                    confidence = max(confidence, 0.93)

                rel_rows = conn.execute(
                    """
                    SELECT rel_type, COUNT(*) AS cnt
                    FROM kg_relationships
                    WHERE source_entity_id = ? OR target_entity_id = ?
                    GROUP BY rel_type
                    ORDER BY cnt DESC, rel_type ASC
                    LIMIT 3
                    """,
                    (row["id"], row["id"]),
                ).fetchall()
                rel_summaries = [
                    f"{int(rel_row['cnt'] or 0)} {str(rel_row['rel_type'] or '').replace('_', ' ')}"
                    for rel_row in rel_rows
                    if rel_row["rel_type"]
                ]

                identifiers = _safe_json_loads(row["identifiers"])
                identifier_payload = identifiers if isinstance(identifiers, dict) else {}
                candidate = {
                    "legal_name": legal_name,
                    "country": str(row["country"] or "") or "US",
                    "graph_entity_id": str(row["id"] or ""),
                    "source": "knowledge_graph",
                    "confidence": round(min(confidence, 0.995), 3),
                    "entity_type": str(row["entity_type"] or "") or "Graph Memory",
                    "graph_relationship_count": relationship_count,
                    "aliases": match_names[1:6],
                }
                if rel_summaries:
                    candidate["graph_signal_summary"] = f"Graph signals already cluster around {', '.join(rel_summaries)}."

                for field in ("uei", "cage", "lei", "cik", "company_number", "wikidata_id", "ticker", "duns"):
                    if identifier_payload.get(field):
                        candidate[field] = identifier_payload[field]

                candidates.append(candidate)

            return candidates
    except Exception:
        return []


def _attach_graph_candidate_relationships(candidates: list[dict]) -> list[dict]:
    graph_candidates = [
        candidate for candidate in candidates
        if str(candidate.get("graph_entity_id") or "").strip()
    ]
    if len(graph_candidates) < 2:
        return candidates

    try:
        from knowledge_graph import get_kg_conn
    except Exception:
        return candidates

    entity_ids = [str(candidate["graph_entity_id"]).strip() for candidate in graph_candidates]
    placeholders = ",".join("?" for _ in entity_ids)

    try:
        with get_kg_conn() as conn:
            rel_rows = conn.execute(
                f"""
                SELECT source_entity_id, target_entity_id, rel_type
                FROM kg_relationships
                WHERE source_entity_id IN ({placeholders})
                   OR target_entity_id IN ({placeholders})
                """,
                (*entity_ids, *entity_ids),
            ).fetchall()
            neighbor_ids = {
                str(row["source_entity_id"] or "")
                for row in rel_rows
            } | {
                str(row["target_entity_id"] or "")
                for row in rel_rows
            }
            entity_name_map: dict[str, str] = {}
            if neighbor_ids:
                neighbor_placeholders = ",".join("?" for _ in neighbor_ids)
                entity_rows = conn.execute(
                    f"SELECT id, canonical_name FROM kg_entities WHERE id IN ({neighbor_placeholders})",
                    tuple(neighbor_ids),
                ).fetchall()
                entity_name_map = {
                    str(row["id"] or ""): str(row["canonical_name"] or "")
                    for row in entity_rows
                }
    except Exception:
        return candidates

    adjacency: dict[str, dict[str, list[str]]] = {entity_id: {} for entity_id in entity_ids}
    for row in rel_rows:
        source_entity_id = str(row["source_entity_id"] or "")
        target_entity_id = str(row["target_entity_id"] or "")
        rel_type = str(row["rel_type"] or "")
        if not source_entity_id or not target_entity_id or not rel_type:
            continue

        adjacency.setdefault(source_entity_id, {}).setdefault(target_entity_id, []).append(rel_type)
        adjacency.setdefault(target_entity_id, {}).setdefault(source_entity_id, []).append(rel_type)

    candidate_by_entity_id = {
        str(candidate["graph_entity_id"]).strip(): candidate
        for candidate in graph_candidates
    }

    for entity_id, candidate in candidate_by_entity_id.items():
        summaries: list[dict] = []
        candidate_neighbors = adjacency.get(entity_id, {})

        for other_entity_id, other_candidate in candidate_by_entity_id.items():
            if other_entity_id == entity_id:
                continue

            direct_rel_types = sorted(set(candidate_neighbors.get(other_entity_id, [])))
            if direct_rel_types:
                rel_label = ", ".join(rel_type.replace("_", " ") for rel_type in direct_rel_types[:3])
                summaries.append({
                    "candidate_name": other_candidate.get("legal_name", ""),
                    "relationship_kind": "direct",
                    "summary": f"Direct graph link to {other_candidate.get('legal_name', 'the other candidate')} via {rel_label}.",
                    "rel_types": direct_rel_types[:3],
                })
                continue

            shared_neighbors = set(candidate_neighbors.keys()) & set(adjacency.get(other_entity_id, {}).keys())
            shared_neighbors.discard(entity_id)
            shared_neighbors.discard(other_entity_id)
            if shared_neighbors:
                top_shared = sorted(shared_neighbors)[:2]
                shared_names = [
                    candidate_by_entity_id.get(shared_neighbor_id, {}).get("legal_name")
                    or entity_name_map.get(shared_neighbor_id)
                    or shared_neighbor_id
                    for shared_neighbor_id in top_shared
                ]
                summaries.append({
                    "candidate_name": other_candidate.get("legal_name", ""),
                    "relationship_kind": "shared_neighbor",
                    "summary": (
                        f"Shares {len(shared_neighbors)} graph counterpart"
                        f"{'' if len(shared_neighbors) == 1 else 's'} with {other_candidate.get('legal_name', 'the other candidate')}"
                        f"{': ' + ', '.join(shared_names) if shared_names else ''}."
                    ),
                    "shared_neighbor_count": len(shared_neighbors),
                })

        if summaries:
            candidate["graph_related_candidates"] = summaries[:_GRAPH_RELATIONSHIP_SUMMARY_LIMIT]

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


def _sam_api_key() -> str:
    ensure_runtime_env_loaded(("XIPHOS_SAM_API_KEY", "SAM_GOV_API_KEY", "XIPHOS_SAM_GOV_API_KEY"))
    return (
        os.environ.get("XIPHOS_SAM_API_KEY", "")
        or os.environ.get("SAM_GOV_API_KEY", "")
        or os.environ.get("XIPHOS_SAM_GOV_API_KEY", "")
    )


def _search_sam_gov(name: str) -> list[dict]:
    """Search SAM.gov entity API for UEI, CAGE, registration, SBA certs,
    corporate ownership, integrity data, and business types.
    Requires XIPHOS_SAM_API_KEY (or legacy SAM_GOV_API_KEY) env var.
    Sections pulled: entityRegistration, coreData, assertions, integrityInformation.
    Get a key at https://open.gsa.gov/api/entity-api/ """
    candidates = []
    api_key = _sam_api_key()
    if not api_key:
        return candidates

    try:
        params = {
            "api_key": api_key,
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
    local_exact_anchor = any(_is_exact_memory_anchor(name, candidate) for candidate in all_candidates)

    all_candidates.extend(_search_knowledge_graph_memory(name))

    if local_exact_anchor or any(_is_exact_memory_anchor(name, candidate) for candidate in all_candidates):
        return _attach_graph_candidate_relationships(_dedupe_candidates(all_candidates)[:12])

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
            if _sam_api_key() and sn == name:
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

    result = _dedupe_candidates(all_candidates)
    return _attach_graph_candidate_relationships(result[:12])
