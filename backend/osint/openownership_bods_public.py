"""Public Open Ownership BODS dataset connector."""

from __future__ import annotations

import gzip
import json
import os
import re
import time
import urllib.error
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
                "authority_level": "third_party_public",
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
            authority_level="third_party_public",
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
