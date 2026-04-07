"""Vehicle-intelligence dossier support built from replayable archive and protest fixtures."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from osint.contract_opportunities_archive_fixture import enrich as archive_fixture_enrich
from osint.contract_opportunities_public import enrich as contract_opportunities_public_enrich
from osint.contract_vehicle_wayback import enrich as contract_vehicle_wayback_enrich
from osint.gao_bid_protests_fixture import enrich as gao_fixture_enrich
from osint.gao_bid_protests_public import enrich as gao_public_enrich
from osint.public_html_contract_vehicle import enrich as public_html_contract_vehicle_enrich
from osint.usaspending_vehicle_live import enrich as usaspending_vehicle_live_enrich


SUPPORT_CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "vehicle_intelligence"
    / "vehicle_support_catalog.json"
)
_SUPPORT_CACHE_TTL_SECONDS = max(int(os.environ.get("XIPHOS_VEHICLE_SUPPORT_CACHE_TTL_SECONDS", "600") or 600), 0)
_SUPPORT_CACHE_LOCK = threading.Lock()
_SUPPORT_CACHE: dict[tuple[str, str, str, str], dict[str, Any]] = {}


def _seed_metadata(vendor: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(vendor, dict):
        return {}
    seed_metadata: dict[str, Any] = {}
    if isinstance(vendor.get("seed_metadata"), dict):
        seed_metadata.update(vendor.get("seed_metadata") or {})
    vendor_input = vendor.get("vendor_input") if isinstance(vendor.get("vendor_input"), dict) else {}
    nested = vendor_input.get("seed_metadata") if isinstance(vendor_input.get("seed_metadata"), dict) else {}
    seed_metadata.update(nested)
    return {
        str(key): value
        for key, value in seed_metadata.items()
        if not str(key).startswith("__") and value not in (None, "", [])
    }


def _support_vehicle_name(vehicle_name: str, vendor: dict[str, Any] | None) -> str:
    seed_metadata = _seed_metadata(vendor)
    explicit = seed_metadata.get("vehicle_intelligence_vehicle") or seed_metadata.get("contract_vehicle_name")
    resolved = str(explicit or vehicle_name or "").strip()
    return resolved


_PUBLIC_HTML_VEHICLE_KEYS = {
    "contract_vehicle_page",
    "contract_vehicle_pages",
    "contract_vehicle_public_html_page",
    "contract_vehicle_public_html_pages",
    "contract_vehicle_public_html_fixture_page",
    "contract_vehicle_public_html_fixture_pages",
}
_WAYBACK_VEHICLE_KEYS = {
    "contract_vehicle_archive_url",
    "contract_vehicle_archive_urls",
    "contract_vehicle_archive_seed_url",
    "contract_vehicle_archive_seed_urls",
    "contract_vehicle_wayback_fixture",
    "contract_vehicle_wayback_fixture_path",
}
_GAO_PUBLIC_KEYS = {
    "gao_public_url",
    "gao_public_urls",
    "gao_docket_url",
    "gao_docket_urls",
    "gao_decision_url",
    "gao_decision_urls",
    "gao_bid_protest_url",
    "gao_bid_protest_urls",
    "gao_public_html_fixture_page",
    "gao_public_html_fixture_pages",
}
_CONTRACT_OPPORTUNITY_NOTICE_KEYS = {
    "contract_opportunity_notice_url",
    "contract_opportunity_notice_urls",
    "contract_opportunity_notice_page",
    "contract_opportunity_notice_pages",
    "contract_opportunity_notice_fixture_page",
    "contract_opportunity_notice_fixture_pages",
}
_LIVE_VEHICLE_KEYS = {
    "contract_vehicle_live_fixture",
    "contract_vehicle_live_fixture_path",
    "contract_vehicle_live_fixture_vehicle",
    "contract_vehicle_live_limit",
    "contract_vehicle_live_include_subs",
}


def _normalize_vehicle_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _catalog_seed_metadata(vehicle_name: str) -> dict[str, Any]:
    if not SUPPORT_CATALOG_PATH.exists():
        return {}
    try:
        payload = json.loads(SUPPORT_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    normalized = _normalize_vehicle_name(vehicle_name)
    for record in payload.get("vehicles", []) or []:
        if not isinstance(record, dict):
            continue
        names = [record.get("vehicle_name", ""), *(record.get("aliases") or [])]
        if any(_normalize_vehicle_name(name) == normalized for name in names):
            seed_metadata = record.get("seed_metadata")
            return dict(seed_metadata) if isinstance(seed_metadata, dict) else {}
    return {}


def _merged_seed_metadata(vehicle_name: str, vendor: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    merged.update(_catalog_seed_metadata(vehicle_name))
    merged.update(_seed_metadata(vendor))
    return merged


def _seed_metadata_stamp(seed_metadata: dict[str, Any]) -> str:
    visible = {
        str(key): value
        for key, value in (seed_metadata or {}).items()
        if not str(key).startswith("__") and value not in (None, "", [])
    }
    if not visible:
        return ""
    return json.dumps(visible, sort_keys=True, default=str)


def _support_cache_key(
    *,
    scoped_vehicle_name: str,
    vendor: dict[str, Any] | None,
    seed_metadata: dict[str, Any],
    support_scope: str,
) -> tuple[str, str, str, str]:
    vendor_name = ""
    if isinstance(vendor, dict):
        vendor_name = str(vendor.get("name") or "").strip()
    return (
        _normalize_vehicle_name(scoped_vehicle_name),
        _normalize_vehicle_name(vendor_name),
        _seed_metadata_stamp(seed_metadata),
        str(support_scope or "full").strip().lower() or "full",
    )


def _get_cached_support_entry(cache_key: tuple[str, str, str, str]) -> dict[str, Any] | None:
    if _SUPPORT_CACHE_TTL_SECONDS <= 0:
        return None
    now = time.time()
    with _SUPPORT_CACHE_LOCK:
        expired = [
            key
            for key, value in _SUPPORT_CACHE.items()
            if now - float(value.get("cached_at", 0.0) or 0.0) > _SUPPORT_CACHE_TTL_SECONDS
        ]
        for key in expired:
            _SUPPORT_CACHE.pop(key, None)
        cached = _SUPPORT_CACHE.get(cache_key)
        if not cached:
            return None
        return {
            "bundle": deepcopy(cached.get("bundle") or {}),
            "graph_sync": deepcopy(cached.get("graph_sync")),
        }


def _store_cached_support_entry(
    cache_key: tuple[str, str, str, str],
    *,
    bundle: dict[str, Any],
    graph_sync: dict[str, Any] | None = None,
) -> None:
    if _SUPPORT_CACHE_TTL_SECONDS <= 0:
        return
    with _SUPPORT_CACHE_LOCK:
        _SUPPORT_CACHE[cache_key] = {
            "cached_at": time.time(),
            "bundle": deepcopy(bundle),
            "graph_sync": deepcopy(graph_sync) if isinstance(graph_sync, dict) else None,
        }


def _store_cached_support_graph_sync(cache_key: tuple[str, str, str, str], graph_sync: dict[str, Any]) -> None:
    if _SUPPORT_CACHE_TTL_SECONDS <= 0:
        return
    with _SUPPORT_CACHE_LOCK:
        cached = _SUPPORT_CACHE.get(cache_key)
        if not cached:
            return
        cached["graph_sync"] = deepcopy(graph_sync)
        cached["cached_at"] = time.time()


def clear_vehicle_intelligence_support_cache() -> None:
    with _SUPPORT_CACHE_LOCK:
        _SUPPORT_CACHE.clear()


def _public_html_vehicle_ids(seed_metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in seed_metadata.items()
        if key in _PUBLIC_HTML_VEHICLE_KEYS and value not in (None, "", [])
    }


def _wayback_vehicle_ids(seed_metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in seed_metadata.items()
        if key in _WAYBACK_VEHICLE_KEYS and value not in (None, "", [])
    }


def _gao_public_ids(seed_metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in seed_metadata.items()
        if key in _GAO_PUBLIC_KEYS and value not in (None, "", [])
    }


def _contract_opportunity_notice_ids(seed_metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in seed_metadata.items()
        if key in _CONTRACT_OPPORTUNITY_NOTICE_KEYS and value not in (None, "", [])
    }


def _live_vehicle_ids(seed_metadata: dict[str, Any], vendor: dict[str, Any] | None) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in seed_metadata.items()
        if key in _LIVE_VEHICLE_KEYS and value not in (None, "", [])
    }
    if isinstance(vendor, dict):
        prime_name = str(vendor.get("name") or "").strip()
        if prime_name:
            payload["prime_contractor_name"] = prime_name
    return payload


def _finding_to_dict(finding: Any) -> dict[str, Any]:
    return {
        "source": getattr(finding, "source", ""),
        "category": getattr(finding, "category", ""),
        "title": getattr(finding, "title", ""),
        "detail": getattr(finding, "detail", ""),
        "severity": getattr(finding, "severity", "info"),
        "confidence": float(getattr(finding, "confidence", 0.0) or 0.0),
        "url": getattr(finding, "url", ""),
        "raw_data": dict(getattr(finding, "raw_data", {}) or {}),
        "source_class": getattr(finding, "source_class", ""),
        "authority_level": getattr(finding, "authority_level", ""),
        "access_model": getattr(finding, "access_model", ""),
        "structured_fields": dict(getattr(finding, "structured_fields", {}) or {}),
    }


def _result_relationships(results: list[Any]) -> list[dict[str, Any]]:
    relationships = []
    for result in results:
        for relationship in getattr(result, "relationships", []) or []:
            if not isinstance(relationship, dict):
                continue
            relationships.append(dict(relationship))
    return relationships


def _result_observed_vendors(results: list[Any]) -> list[dict[str, Any]]:
    observed_by_name: dict[str, dict[str, Any]] = {}
    for result in results:
        structured = getattr(result, "structured_fields", {}) or {}
        for row in structured.get("observed_vendors") or []:
            if not isinstance(row, dict):
                continue
            vendor_name = str(row.get("vendor_name") or "").strip()
            if not vendor_name:
                continue
            key = _normalize_vehicle_name(vendor_name)
            candidate = dict(row)
            existing = observed_by_name.get(key)
            if existing is None:
                observed_by_name[key] = candidate
                continue
            if str(existing.get("role") or "") != str(candidate.get("role") or ""):
                existing["role"] = "prime+sub"
            try:
                existing_amount = float(existing.get("award_amount") or 0.0)
            except (TypeError, ValueError):
                existing_amount = 0.0
            try:
                candidate_amount = float(candidate.get("award_amount") or 0.0)
            except (TypeError, ValueError):
                candidate_amount = 0.0
            if candidate_amount > existing_amount:
                existing.update(candidate)
    return sorted(
        observed_by_name.values(),
        key=lambda row: (
            -(float(row.get("award_amount") or 0.0) if str(row.get("award_amount") or "").strip() else 0.0),
            str(row.get("vendor_name") or "").lower(),
        ),
    )


_GRAPH_SYNC_REL_TYPES = {
    "prime_contractor_of",
    "subcontractor_of",
    "competed_on",
    "incumbent_on",
    "teamed_with",
    "awarded_under",
    "predecessor_of",
    "successor_of",
    "funded_by",
    "performed_at",
}
_GRAPH_SYNC_AUTHORITIES = {
    "official_program_system",
    "official_registry",
    "official_regulatory",
}


def _sync_name_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _graph_entity_id(name: str, entity_type: str) -> str:
    normalized = _sync_name_key(name) or str(name or "").strip().upper()
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]
    prefix = {
        "contract_vehicle": "contract_vehicle",
        "government_agency": "government_agency",
        "installation": "installation",
        "holding_company": "holding_company",
    }.get(entity_type, entity_type or "entity")
    return f"{prefix}:{digest}"


def _graph_entity_type(rel_type: str, side: str) -> str:
    if rel_type in {"prime_contractor_of", "subcontractor_of", "competed_on", "incumbent_on"}:
        return "company" if side == "source" else "contract_vehicle"
    if rel_type == "teamed_with":
        return "company"
    if rel_type in {"awarded_under", "predecessor_of", "successor_of"}:
        return "contract_vehicle"
    if rel_type == "funded_by":
        return "government_agency" if side == "source" else "contract_vehicle"
    if rel_type == "performed_at":
        return "contract_vehicle" if side == "source" else "installation"
    return "company"


def _relationship_evidence_url(rel: dict[str, Any]) -> str:
    urls = rel.get("source_urls")
    if isinstance(urls, list):
        for item in urls:
            candidate = str(item or "").strip()
            if candidate:
                return candidate
    return str(rel.get("evidence_url") or "").strip()


def _load_graph_entity_index() -> dict[tuple[str, str], dict[str, Any]]:
    from knowledge_graph import get_kg_conn

    index: dict[tuple[str, str], dict[str, Any]] = {}
    with get_kg_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence
            FROM kg_entities
            """
        ).fetchall()
    for row in rows:
        aliases = row["aliases"]
        if not isinstance(aliases, list):
            try:
                aliases = json.loads(aliases or "[]")
            except Exception:
                aliases = []
        identifiers = row["identifiers"]
        if not isinstance(identifiers, dict):
            try:
                identifiers = json.loads(identifiers or "{}")
            except Exception:
                identifiers = {}
        record = {
            "id": str(row["id"]),
            "canonical_name": str(row["canonical_name"] or ""),
            "entity_type": str(row["entity_type"] or ""),
            "aliases": [str(item or "").strip() for item in (aliases or []) if str(item or "").strip()],
            "identifiers": identifiers or {},
            "country": str(row["country"] or ""),
            "sources": row["sources"] if isinstance(row["sources"], list) else [],
            "confidence": float(row["confidence"] or 0.0),
        }
        names = [record["canonical_name"], *record["aliases"]]
        for candidate in names:
            key = (record["entity_type"], _sync_name_key(candidate))
            if key[1] and key not in index:
                index[key] = record
    return index


def _resolve_graph_entity(
    *,
    name: str,
    entity_type: str,
    source_name: str,
    index: dict[tuple[str, str], dict[str, Any]],
) -> str:
    from entity_resolution import ResolvedEntity
    from knowledge_graph import save_entity

    clean_name = str(name or "").strip()
    if not clean_name:
        return ""
    key = (entity_type, _sync_name_key(clean_name))
    record = index.get(key)
    if record is None:
        entity_id = _graph_entity_id(clean_name, entity_type)
        record = {
            "id": entity_id,
            "canonical_name": clean_name,
            "entity_type": entity_type,
            "aliases": [],
            "identifiers": {},
            "country": "",
            "sources": [],
            "confidence": 0.78 if entity_type == "contract_vehicle" else 0.76,
        }
    else:
        entity_id = str(record["id"])

    aliases = [item for item in record.get("aliases", []) if item and item != clean_name]
    sources = [str(item or "").strip() for item in (record.get("sources") or []) if str(item or "").strip()]
    if source_name not in sources:
        sources.append(source_name)
    save_entity(
        ResolvedEntity(
            id=entity_id,
            canonical_name=clean_name,
            entity_type=entity_type,
            aliases=aliases,
            identifiers=record.get("identifiers") or {},
            country=str(record.get("country") or ""),
            sources=sources,
            confidence=max(float(record.get("confidence") or 0.0), 0.76),
            last_updated=datetime.now(timezone.utc).isoformat(),
        )
    )
    updated = {
        **record,
        "id": entity_id,
        "canonical_name": clean_name,
        "entity_type": entity_type,
        "aliases": aliases,
        "sources": sources,
        "confidence": max(float(record.get("confidence") or 0.0), 0.76),
    }
    index[key] = updated
    return entity_id


def sync_vehicle_support_graph(
    *,
    vehicle_name: str,
    support_bundle: dict[str, Any],
) -> dict[str, Any]:
    from knowledge_graph import get_kg_conn, init_kg_db, save_relationship

    init_kg_db()
    index = _load_graph_entity_index()
    relationships_written = 0
    relationships_reused = 0
    syncable_relationships = [
        rel
        for rel in (support_bundle.get("relationships") or [])
        if isinstance(rel, dict)
        and str(rel.get("rel_type") or "") in _GRAPH_SYNC_REL_TYPES
        and str(rel.get("authority_level") or "").strip().lower() in _GRAPH_SYNC_AUTHORITIES
    ]

    for rel in syncable_relationships:
        rel_type = str(rel.get("rel_type") or "").strip()
        source_name = str(rel.get("source_name") or "").strip()
        target_name = str(rel.get("target_name") or "").strip()
        if not source_name or not target_name:
            continue
        source_id = _resolve_graph_entity(
            name=source_name,
            entity_type=_graph_entity_type(rel_type, "source"),
            source_name=str(rel.get("data_source") or "vehicle_intelligence_support"),
            index=index,
        )
        target_id = _resolve_graph_entity(
            name=target_name,
            entity_type=_graph_entity_type(rel_type, "target"),
            source_name=str(rel.get("data_source") or "vehicle_intelligence_support"),
            index=index,
        )
        if not source_id or not target_id:
            continue
        evidence = str(rel.get("evidence_summary") or rel.get("evidence") or "")
        data_source = str(rel.get("data_source") or "")
        with get_kg_conn() as conn:
            existing = conn.execute(
                """
                SELECT id
                FROM kg_relationships
                WHERE source_entity_id = ?
                  AND target_entity_id = ?
                  AND rel_type = ?
                  AND data_source = ?
                  AND evidence = ?
                LIMIT 1
                """,
                (source_id, target_id, rel_type, data_source, evidence),
            ).fetchone()
        if existing:
            relationships_reused += 1
            continue
        save_relationship(
            source_entity_id=source_id,
            target_entity_id=target_id,
            rel_type=rel_type,
            confidence=float(rel.get("confidence") or 0.0),
            data_source=data_source,
            evidence=evidence,
            evidence_url=_relationship_evidence_url(rel),
            evidence_title=f"Vehicle intelligence support: {vehicle_name}",
            source_class=str(rel.get("source_class") or "public_connector"),
            authority_level=str(rel.get("authority_level") or ""),
            access_model=str(rel.get("access_model") or ""),
            structured_fields={
                "vehicle_name": vehicle_name,
                "source_notes": list(rel.get("source_notes") or []),
            },
        )
        relationships_written += 1

    return {
        "enabled": True,
        "relationship_count": relationships_written,
        "reused_relationship_count": relationships_reused,
        "syncable_relationship_count": len(syncable_relationships),
    }


def _gao_events(results: list[Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for result in results:
        for finding in getattr(result, "findings", []) or []:
            raw = dict(getattr(finding, "raw_data", {}) or {})
            if getattr(finding, "category", "") != "bid_protest" and not raw.get("forum"):
                continue
            protester = str(raw.get("protester") or "").strip()
            agency = str(raw.get("agency") or "").strip()
            decision_date = str(raw.get("decision_date") or "").strip()
            summary_bits = []
            if protester:
                summary_bits.append(f"Protester: {protester}")
            if agency:
                summary_bits.append(f"Agency: {agency}")
            if decision_date:
                summary_bits.append(f"Decision date: {decision_date}")
            summary_line = " | ".join(summary_bits)
            assessment = str(raw.get("assessment") or getattr(finding, "detail", "") or "").strip()
            if summary_line and assessment:
                assessment = f"{summary_line}. {assessment}"
            elif summary_line:
                assessment = summary_line
            events.append(
                {
                    "title": getattr(finding, "title", "") or "GAO bid protest",
                    "status": str(raw.get("status") or "observed"),
                    "connector": getattr(finding, "source", ""),
                    "assessment": assessment,
                    "subject": getattr(finding, "title", "") or "GAO bid protest",
                    "forum": str(raw.get("forum") or "GAO"),
                    "event_id": str(raw.get("event_id") or ""),
                    "vehicle_name": str(raw.get("vehicle_name") or ""),
                    "event_date": str(raw.get("decision_date") or ""),
                    "url": getattr(finding, "url", ""),
                }
            )
    return events


def build_vehicle_intelligence_support(
    *,
    vehicle_name: str,
    vendor: dict[str, Any] | None = None,
    sync_graph: bool = False,
    support_scope: str = "full",
) -> dict[str, Any] | None:
    scoped_vehicle_name = _support_vehicle_name(vehicle_name, vendor)
    if not scoped_vehicle_name:
        return None

    normalized_scope = str(support_scope or "full").strip().lower() or "full"
    seed_metadata = _merged_seed_metadata(scoped_vehicle_name, vendor)
    cache_key = _support_cache_key(
        scoped_vehicle_name=scoped_vehicle_name,
        vendor=vendor,
        seed_metadata=seed_metadata,
        support_scope=normalized_scope,
    )
    cached = _get_cached_support_entry(cache_key)
    if cached is not None:
        support_bundle = dict(cached.get("bundle") or {})
        if sync_graph:
            graph_sync = cached.get("graph_sync")
            if not isinstance(graph_sync, dict):
                graph_sync = sync_vehicle_support_graph(
                    vehicle_name=scoped_vehicle_name,
                    support_bundle=support_bundle,
                )
                _store_cached_support_graph_sync(cache_key, graph_sync)
            else:
                graph_sync = {
                    **graph_sync,
                    "relationship_count": 0,
                    "reused_relationship_count": max(
                        int(graph_sync.get("reused_relationship_count") or 0),
                        int(graph_sync.get("syncable_relationship_count") or 0),
                    ),
                    "cached": True,
                }
            support_bundle["graph_sync"] = graph_sync
        return support_bundle

    live_vehicle_result = usaspending_vehicle_live_enrich(
        scoped_vehicle_name,
        **_live_vehicle_ids(seed_metadata, vendor),
    )
    if normalized_scope == "market":
        results = [live_vehicle_result]
    else:
        archive_result = archive_fixture_enrich(scoped_vehicle_name)
        gao_result = gao_fixture_enrich(scoped_vehicle_name)
        results = [archive_result, gao_result, live_vehicle_result]
        contract_notice_ids = _contract_opportunity_notice_ids(seed_metadata)
        if contract_notice_ids:
            results.append(contract_opportunities_public_enrich(scoped_vehicle_name, **contract_notice_ids))
        gao_public_ids = _gao_public_ids(seed_metadata)
        if gao_public_ids:
            results.append(gao_public_enrich(scoped_vehicle_name, **gao_public_ids))
        wayback_ids = _wayback_vehicle_ids(seed_metadata)
        if wayback_ids:
            results.append(contract_vehicle_wayback_enrich(scoped_vehicle_name, **wayback_ids))
        public_html_ids = _public_html_vehicle_ids(seed_metadata)
        if public_html_ids:
            results.append(public_html_contract_vehicle_enrich(scoped_vehicle_name, **public_html_ids))

    findings = []
    for result in results:
        findings.extend(_finding_to_dict(finding) for finding in getattr(result, "findings", []) or [])

    relationships = _result_relationships(results)
    events = _gao_events(results)
    observed_vendors = _result_observed_vendors(results)
    connectors_with_data = sum(
        1
        for result in results
        if (getattr(result, "findings", None) or getattr(result, "identifiers", None) or getattr(result, "relationships", None))
    )

    support_bundle = {
        "vehicle_name": scoped_vehicle_name,
        "support_scope": normalized_scope,
        "connectors_run": len(results),
        "connectors_with_data": connectors_with_data,
        "relationships": relationships,
        "events": events,
        "findings": findings,
        "observed_vendors": observed_vendors,
        "sources": [getattr(result, "source", "") for result in results if getattr(result, "source", "")],
    }
    graph_sync = None
    if sync_graph:
        graph_sync = sync_vehicle_support_graph(
            vehicle_name=scoped_vehicle_name,
            support_bundle=support_bundle,
        )
        support_bundle["graph_sync"] = graph_sync
    cached_bundle = {key: value for key, value in support_bundle.items() if key != "graph_sync"}
    _store_cached_support_entry(cache_key, bundle=cached_bundle, graph_sync=graph_sync)
    return support_bundle
