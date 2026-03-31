"""Public Open Ownership BODS dataset connector."""

from __future__ import annotations

import gzip
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import EnrichmentResult, Finding


SOURCE_NAME = "openownership_bods_public"
USER_AGENT = "Xiphos-Vetting/2.1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_PATHS = (
    REPO_ROOT / "var" / "openownership_bods_public.json",
    REPO_ROOT / "var" / "openownership_bods_public.jsonl",
    REPO_ROOT / "var" / "openownership_bods_public.json.gz",
    REPO_ROOT / "var" / "openownership_bods_public.jsonl.gz",
    REPO_ROOT / "var" / "openownership" / "bods_public.json",
    REPO_ROOT / "var" / "openownership" / "bods_public.jsonl",
    REPO_ROOT / "var" / "openownership" / "bods_public.json.gz",
    REPO_ROOT / "var" / "openownership" / "bods_public.jsonl.gz",
)


def _normalize_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(name or "").upper()).strip()


def _get_dataset_url(ids: dict) -> str:
    for key in ("openownership_bods_url", "bods_url"):
        value = str(ids.get(key) or "").strip()
        if value:
            return value
    return str(os.environ.get("XIPHOS_OPENOWNERSHIP_BODS_URL") or "").strip()


def _get_dataset_path(ids: dict) -> str:
    for key in ("openownership_bods_path", "bods_path"):
        value = str(ids.get(key) or "").strip()
        if value:
            return value
    env_path = str(os.environ.get("XIPHOS_OPENOWNERSHIP_BODS_PATH") or "").strip()
    if env_path:
        return env_path
    for candidate in DEFAULT_CACHE_PATHS:
        if candidate.exists():
            return str(candidate)
    return ""


def _fetch_json(url: str) -> dict | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _is_datasette_url(url: str) -> bool:
    return "bods-data-datasette.openownership.org" in str(url or "")


def _normalize_datasette_base(url: str) -> str:
    candidate = str(url or "").strip().rstrip("/")
    if candidate.endswith(".json"):
        candidate = candidate[:-5]
    return candidate


def _fetch_datasette_table(base_url: str, table: str, **params) -> tuple[dict | None, str]:
    query = {"_shape": "objects", **params}
    encoded = urllib.parse.urlencode(query, doseq=True)
    url = f"{_normalize_datasette_base(base_url)}/{table}.json?{encoded}"
    return _fetch_json(url), url


def _subject_key(ids: dict) -> str:
    company_number = str(ids.get("uk_company_number") or ids.get("company_number") or "").strip().upper()
    if not company_number:
        return ""
    return company_number if company_number.startswith("GB-COH-") else f"GB-COH-{company_number}"


def _exact_entity_match(row: dict, vendor_name: str, country: str, ids: dict) -> bool:
    subject_key = _subject_key(ids)
    declarationsubject = str(row.get("declarationsubject") or "").strip().upper()
    recordid = str(row.get("recordid") or "").strip().upper()
    if subject_key and (declarationsubject == subject_key or subject_key in recordid):
        return True
    if _normalize_name(row.get("recorddetails_name", "")) != _normalize_name(vendor_name):
        return False
    country_code = str(country or "").strip().upper()
    if country_code and str(row.get("recorddetails_jurisdiction_code") or "").strip().upper() not in {"", country_code}:
        return False
    return True


def _pick_datasette_entity_row(base_url: str, vendor_name: str, country: str, ids: dict) -> tuple[dict | None, str]:
    search_terms: list[str] = []
    subject_key = _subject_key(ids)
    if subject_key:
        search_terms.append(subject_key)
    if vendor_name:
        search_terms.append(vendor_name)
    seen_terms: set[str] = set()
    for term in search_terms:
        normalized = str(term or "").strip()
        if not normalized or normalized in seen_terms:
            continue
        seen_terms.add(normalized)
        payload, request_url = _fetch_datasette_table(base_url, "entity_statement", _search=normalized, _size=12)
        rows = payload.get("rows") if isinstance(payload, dict) else []
        for row in rows or []:
            if isinstance(row, dict) and _exact_entity_match(row, vendor_name, country, ids):
                return row, request_url
    return None, ""


def _resolve_datasette_party(base_url: str, record_key: str) -> dict:
    candidate = str(record_key or "").strip()
    if not candidate:
        return {"name": "", "entity_type": "holding_company", "country": "", "identifiers": {}}
    for table, entity_type in (("entity_statement", "holding_company"), ("person_statement", "person")):
        payload, _request_url = _fetch_datasette_table(base_url, table, _search=candidate, _size=8)
        rows = payload.get("rows") if isinstance(payload, dict) else []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            exact = {
                str(row.get("_link") or "").strip(),
                str(row.get("statementid") or "").strip(),
                str(row.get("recordid") or "").strip(),
                str(row.get("declarationsubject") or "").strip(),
            }
            if candidate not in exact:
                continue
            identifiers: dict[str, str] = {}
            declarationsubject = str(row.get("declarationsubject") or "").strip()
            if declarationsubject.startswith("GB-COH-"):
                identifiers["uk_company_number"] = declarationsubject.removeprefix("GB-COH-")
            return {
                "name": str(row.get("recorddetails_name") or candidate),
                "entity_type": entity_type,
                "country": str(row.get("recorddetails_jurisdiction_code") or "").strip(),
                "identifiers": identifiers,
            }
    return {"name": candidate, "entity_type": "holding_company", "country": "", "identifiers": {}}


def _relationship_directness(interests: list[dict]) -> str:
    values = {str(item.get("directorindirect") or "").strip().lower() for item in interests if isinstance(item, dict)}
    if "direct" in values:
        return "direct"
    if "indirect" in values:
        return "indirect"
    return "indirect"


def _record_from_datasette(base_url: str, vendor_name: str, country: str, ids: dict) -> tuple[dict | None, str]:
    entity_row, request_url = _pick_datasette_entity_row(base_url, vendor_name, country, ids)
    if not isinstance(entity_row, dict):
        return None, ""

    subject_key = str(entity_row.get("declarationsubject") or "").strip()
    payload, rel_request_url = _fetch_datasette_table(base_url, "relationship_statement", _search=subject_key, _size=50)
    relationship_rows = payload.get("rows") if isinstance(payload, dict) else []
    statements: list[dict] = []
    for relationship_row in relationship_rows or []:
        if not isinstance(relationship_row, dict):
            continue
        if str(relationship_row.get("recorddetails_subject") or "").strip() != subject_key:
            continue
        rel_link = str(relationship_row.get("_link") or "").strip()
        interests_payload, _interest_request_url = _fetch_datasette_table(
            base_url,
            "relationship_recordDetails_interests",
            _search=rel_link,
            _size=12,
        )
        interests = [
            item
            for item in ((interests_payload or {}).get("rows") or [])
            if isinstance(item, dict) and str(item.get("_link_relationship_statement") or "").strip() == rel_link
        ]
        interested_party = _resolve_datasette_party(base_url, str(relationship_row.get("recorddetails_interestedparty") or ""))
        statements.append(
            {
                "statement_id": str(relationship_row.get("statementid") or relationship_row.get("recordid") or rel_link),
                "statement_type": "ownershipOrControlStatement",
                "direct_or_indirect": _relationship_directness(interests),
                "interests": [str(item.get("type") or "").strip() for item in interests if str(item.get("type") or "").strip()],
                "interested_party": interested_party,
                "evidence": str(relationship_row.get("source_url") or rel_request_url),
            }
        )

    if not statements:
        return None, ""

    subject_identifiers: dict[str, str] = {}
    if subject_key.startswith("GB-COH-"):
        subject_identifiers["uk_company_number"] = subject_key.removeprefix("GB-COH-")
    return (
        {
            "record_id": str(entity_row.get("recordid") or subject_key),
            "name": str(entity_row.get("recorddetails_name") or vendor_name),
            "country": str(entity_row.get("recorddetails_jurisdiction_code") or country or "").strip().upper(),
            "subject": {
                "name": str(entity_row.get("recorddetails_name") or vendor_name),
                "entity_type": "company",
                "identifiers": subject_identifiers,
            },
            "statements": statements,
        },
        request_url,
    )


def _load_json_path(path: str) -> dict | None:
    dataset_path = Path(path).expanduser()
    if not dataset_path.exists():
        return None
    opener = gzip.open if dataset_path.suffix == ".gz" else open
    try:
        with opener(dataset_path, "rt", encoding="utf-8") as handle:
            raw_text = handle.read()
    except (OSError, UnicodeDecodeError):
        return None

    stripped = raw_text.lstrip()
    if not stripped:
        return None

    if dataset_path.name.endswith((".jsonl", ".jsonl.gz", ".ndjson", ".ndjson.gz")):
        records: list[dict] = []
        for line in raw_text.splitlines():
            normalized = line.strip()
            if not normalized:
                continue
            try:
                payload = json.loads(normalized)
            except json.JSONDecodeError:
                return None
            if isinstance(payload, dict):
                records.append(payload)
        return {"records": records}

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, list):
        return {"records": [item for item in payload if isinstance(item, dict)]}
    if isinstance(payload, dict):
        return payload
    return None


def _load_payload(ids: dict) -> tuple[dict | None, str]:
    dataset_path = _get_dataset_path(ids)
    if dataset_path:
        payload = _load_json_path(dataset_path)
        if payload is not None:
            return payload, str(Path(dataset_path).expanduser().resolve())
    dataset_url = _get_dataset_url(ids)
    if dataset_url and _is_datasette_url(dataset_url):
        return {"datasette_url": _normalize_datasette_base(dataset_url)}, _normalize_datasette_base(dataset_url)
    if dataset_url:
        return _fetch_json(dataset_url), dataset_url
    return None, ""


def _match_record(record: dict, vendor_name: str, country: str, ids: dict) -> bool:
    subject = record.get("subject") or {}
    subject_ids = subject.get("identifiers") if isinstance(subject.get("identifiers"), dict) else {}
    known_company_number = str(ids.get("uk_company_number") or ids.get("company_number") or "").strip().upper()
    known_lei = str(ids.get("lei") or "").strip().upper()
    if known_company_number and str(subject_ids.get("uk_company_number") or "").strip().upper() == known_company_number:
        return True
    if known_lei and str(subject_ids.get("lei") or "").strip().upper() == known_lei:
        return True
    if _normalize_name(record.get("name", "")) != _normalize_name(vendor_name):
        return False
    country_code = str(country or "").strip().upper()
    if country_code and str(record.get("country") or "").strip().upper() not in {"", country_code}:
        return False
    return True


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    started = time.perf_counter()
    result = EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        source_class="public_connector",
        authority_level="third_party_public",
        access_model="public_json",
    )

    payload, dataset_ref = _load_payload(ids)
    if not payload or not dataset_ref:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    if not isinstance(payload, dict):
        result.error = "Unable to fetch public Open Ownership dataset"
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    if payload.get("datasette_url"):
        record, record_ref = _record_from_datasette(str(payload.get("datasette_url") or dataset_ref), vendor_name, country, ids)
        if not isinstance(record, dict):
            result.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return result
        payload = {"records": [record]}
        dataset_ref = record_ref or dataset_ref

    records = payload.get("records")
    if not isinstance(records, list):
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="ownership",
                title="Open Ownership dataset shape unsupported",
                detail=(
                    "The configured public Open Ownership dataset does not expose a top-level "
                    "`records` array in the expected provider-neutral format."
                ),
                severity="info",
                confidence=0.8,
                url=dataset_ref if "://" in dataset_ref else "",
                raw_data={"top_level_keys": sorted(payload.keys())[:12]},
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="public_json",
            )
        )
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    record = next((item for item in records if isinstance(item, dict) and _match_record(item, vendor_name, country, ids)), None)
    if not isinstance(record, dict):
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    subject = record.get("subject") or {}
    statements = [statement for statement in (record.get("statements") or []) if isinstance(statement, dict)]
    direct_count = 0
    indirect_count = 0

    for statement in statements:
        interested_party = statement.get("interested_party") or {}
        target_name = str(interested_party.get("name") or "").strip()
        if not target_name:
            continue
        direct = str(statement.get("direct_or_indirect") or "").strip().lower() == "direct"
        rel_type = "owned_by" if direct else "beneficially_owned_by"
        if direct:
            direct_count += 1
        else:
            indirect_count += 1
        result.relationships.append(
            {
                "type": rel_type,
                "source_entity": subject.get("name", vendor_name),
                "source_entity_type": subject.get("entity_type", "company"),
                "source_identifiers": subject.get("identifiers", {}) or {},
                "target_entity": target_name,
                "target_entity_type": interested_party.get("entity_type", "holding_company"),
                "target_identifiers": interested_party.get("identifiers", {}) or {},
                "country": interested_party.get("country", record.get("country", "")),
                "data_source": SOURCE_NAME,
                "confidence": 0.9 if direct else 0.86,
                "evidence": str(statement.get("evidence") or "Open Ownership BODS public dataset statement"),
                "evidence_url": dataset_ref if "://" in dataset_ref else "",
                "artifact_ref": dataset_ref,
                "structured_fields": {
                    "statement_id": str(statement.get("statement_id") or ""),
                    "statement_type": str(statement.get("statement_type") or "ownershipOrControlStatement"),
                    "direct_or_indirect": str(statement.get("direct_or_indirect") or ""),
                    "interests": list(statement.get("interests") or []),
                    "beneficial_ownership_pct": statement.get("beneficial_ownership_pct"),
                    "component_records": list(statement.get("component_records") or []),
                    "standards": ["Beneficial Ownership Data Standard (BODS)"],
                    "dataset_ref": dataset_ref,
                },
                "source_class": "public_connector",
                "authority_level": "public_registry_aggregator" if _is_datasette_url(dataset_ref) else "third_party_public",
                "access_model": "public_json",
            }
        )

    subject_identifiers = subject.get("identifiers") if isinstance(subject.get("identifiers"), dict) else {}
    result.identifiers.update(subject_identifiers)
    if "://" in dataset_ref:
        result.identifiers["openownership_bods_url"] = dataset_ref
    else:
        result.identifiers["openownership_bods_path"] = dataset_ref

    result.findings.append(
        Finding(
            source=SOURCE_NAME,
            category="ownership",
            title="Open Ownership public BODS dataset matched",
            detail=(
                f"{subject.get('name', vendor_name)} matched a public BODS dataset. "
                f"{direct_count} direct and {indirect_count} indirect ownership or control statements were normalized."
            ),
            severity="medium" if indirect_count else "low",
            confidence=0.88,
            url=dataset_ref if "://" in dataset_ref else "",
            raw_data={
                "record_id": record.get("record_id", ""),
                "statement_count": len(statements),
            },
            artifact_ref=dataset_ref,
            structured_fields={
                "summary": {
                    "record_id": record.get("record_id", ""),
                    "statement_count": len(statements),
                    "direct_statement_count": direct_count,
                    "indirect_statement_count": indirect_count,
                }
            },
            source_class="public_connector",
            authority_level="public_registry_aggregator" if _is_datasette_url(dataset_ref) else "third_party_public",
            access_model="public_json",
        )
    )
    result.risk_signals.append(
        {
            "signal": "openownership_bods_public_present",
            "source": SOURCE_NAME,
            "severity": "medium" if indirect_count else "low",
            "confidence": 0.88,
            "summary": f"{len(statements)} public BODS statements matched for {subject.get('name', vendor_name)}",
        }
    )
    result.structured_fields = {
        "summary": {
            "record_id": record.get("record_id", ""),
            "statement_count": len(statements),
            "direct_statement_count": direct_count,
            "indirect_statement_count": indirect_count,
            "dataset_ref": dataset_ref,
        }
    }
    result.artifact_refs = [dataset_ref]
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
