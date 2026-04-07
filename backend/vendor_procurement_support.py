"""Vendor procurement-footprint dossier support."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from osint.usaspending_vendor_live import SOURCE_NAME, enrich as usaspending_vendor_live_enrich


SUPPORT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "procurement_footprint"
    / "vendor_procurement_support_fixture.json"
)
_SUPPORT_CACHE_TTL_SECONDS = max(int(os.environ.get("XIPHOS_VENDOR_PROCUREMENT_CACHE_TTL_SECONDS", "900") or 900), 0)
_SUPPORT_CACHE_LOCK = threading.Lock()
_SUPPORT_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_GRAPH_SYNC_REL_TYPES = frozenset({
    "prime_on_vehicle",
    "subcontractor_on_vehicle",
    "prime_contractor_of",
    "subcontractor_of",
    "funded_by",
})
_GRAPH_SYNC_AUTHORITIES = frozenset({"official_program_system"})


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


def _seed_metadata_stamp(seed_metadata: dict[str, Any]) -> str:
    visible = {
        str(key): value
        for key, value in (seed_metadata or {}).items()
        if not str(key).startswith("__") and value not in (None, "", [])
    }
    if not visible:
        return ""
    return json.dumps(visible, sort_keys=True, default=str)


def _support_cache_key(vendor_id: str, vendor_name: str, seed_metadata: dict[str, Any]) -> tuple[str, str]:
    return (str(vendor_id or "").strip(), _seed_metadata_stamp(seed_metadata) or str(vendor_name or "").strip().upper())


def _get_cached_support_entry(cache_key: tuple[str, str]) -> dict[str, Any] | None:
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
    cache_key: tuple[str, str],
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


def _store_cached_support_graph_sync(cache_key: tuple[str, str], graph_sync: dict[str, Any]) -> None:
    if _SUPPORT_CACHE_TTL_SECONDS <= 0:
        return
    with _SUPPORT_CACHE_LOCK:
        cached = _SUPPORT_CACHE.get(cache_key)
        if not cached:
            return
        cached["graph_sync"] = deepcopy(graph_sync)
        cached["cached_at"] = time.time()


def clear_vendor_procurement_support_cache() -> None:
    with _SUPPORT_CACHE_LOCK:
        _SUPPORT_CACHE.clear()


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


def _support_ids(seed_metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in seed_metadata.items()
        if key.startswith("vendor_procurement_") and value not in (None, "", [])
    }


def _sync_name_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _graph_entity_id(name: str, entity_type: str) -> str:
    return f"{entity_type}:{hashlib.sha1(_sync_name_key(name).encode('utf-8')).hexdigest()[:18]}"


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
        record = dict(row)
        canonical_name = str(record.get("canonical_name") or "").strip()
        entity_type = str(record.get("entity_type") or "").strip()
        if canonical_name and entity_type:
            index[(entity_type, _sync_name_key(canonical_name))] = record
    return index


def _graph_entity_type(rel_type: str, side: str) -> str:
    if rel_type in {"prime_on_vehicle", "subcontractor_on_vehicle"}:
        return "company" if side == "source" else "contract_vehicle"
    if rel_type == "funded_by":
        return "government_agency" if side == "source" else "company"
    return "company"


def _relationship_evidence_url(rel: dict[str, Any]) -> str:
    urls = rel.get("source_urls") if isinstance(rel.get("source_urls"), list) else []
    for url in urls:
        text = str(url or "").strip()
        if text:
            return text
    return ""


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
    index[key] = {
        **record,
        "id": entity_id,
        "canonical_name": clean_name,
        "entity_type": entity_type,
        "aliases": aliases,
        "sources": sources,
        "confidence": max(float(record.get("confidence") or 0.0), 0.76),
    }
    return entity_id


def sync_vendor_procurement_graph(
    *,
    vendor_id: str,
    vendor_name: str,
    support_bundle: dict[str, Any],
) -> dict[str, Any]:
    from knowledge_graph import init_kg_db, link_entity_to_vendor, save_relationship

    init_kg_db()
    index = _load_graph_entity_index()
    relationships_written = 0
    relationships_reused = 0
    syncable_relationships = [
        rel
        for rel in (support_bundle.get("relationships") or [])
        if isinstance(rel, dict)
        and str(rel.get("rel_type") or "").strip() in _GRAPH_SYNC_REL_TYPES
        and str(rel.get("authority_level") or "").strip().lower() in _GRAPH_SYNC_AUTHORITIES
    ]

    from knowledge_graph import get_kg_conn

    for rel in syncable_relationships:
        rel_type = str(rel.get("rel_type") or "").strip()
        source_name = str(rel.get("source_name") or "").strip()
        target_name = str(rel.get("target_name") or "").strip()
        if not source_name or not target_name:
            continue
        source_id = _resolve_graph_entity(
            name=source_name,
            entity_type=_graph_entity_type(rel_type, "source"),
            source_name=str(rel.get("data_source") or "vendor_procurement_support"),
            index=index,
        )
        target_id = _resolve_graph_entity(
            name=target_name,
            entity_type=_graph_entity_type(rel_type, "target"),
            source_name=str(rel.get("data_source") or "vendor_procurement_support"),
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
        link_entity_to_vendor(source_id, vendor_id)
        link_entity_to_vendor(target_id, vendor_id)
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
            evidence_title=f"Vendor procurement support: {vendor_name}",
            source_class=str(rel.get("source_class") or "public_connector"),
            authority_level=str(rel.get("authority_level") or ""),
            access_model=str(rel.get("access_model") or ""),
            structured_fields={
                "vendor_name": vendor_name,
                "source_notes": list(rel.get("source_notes") or []),
            },
            vendor_id=vendor_id,
        )
        relationships_written += 1

    return {
        "enabled": True,
        "relationship_count": relationships_written,
        "reused_relationship_count": relationships_reused,
        "syncable_relationship_count": len(syncable_relationships),
    }


def build_vendor_procurement_support(
    *,
    vendor_id: str,
    vendor: dict[str, Any] | None = None,
    sync_graph: bool = False,
) -> dict[str, Any] | None:
    vendor_name = str((vendor or {}).get("name") or "").strip()
    if not vendor_name or not vendor_id:
        return None

    seed_metadata = _seed_metadata(vendor)
    cache_key = _support_cache_key(vendor_id, vendor_name, seed_metadata)
    cached = _get_cached_support_entry(cache_key)
    if cached is not None:
        support_bundle = dict(cached.get("bundle") or {})
        if sync_graph:
            graph_sync = cached.get("graph_sync")
            if not isinstance(graph_sync, dict):
                graph_sync = sync_vendor_procurement_graph(
                    vendor_id=vendor_id,
                    vendor_name=vendor_name,
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

    live_result = usaspending_vendor_live_enrich(vendor_name, **_support_ids(seed_metadata))
    findings = [_finding_to_dict(finding) for finding in (live_result.findings or [])]
    relationships = [dict(rel) for rel in (live_result.relationships or []) if isinstance(rel, dict)]
    structured = dict(getattr(live_result, "structured_fields", {}) or {})
    support_bundle = {
        "vendor_name": vendor_name,
        "connectors_run": 1,
        "connectors_with_data": 1 if (findings or relationships or structured) else 0,
        "relationships": relationships,
        "findings": findings,
        "matched_recipients": list(structured.get("matched_recipients") or []),
        "prime_awards": list(structured.get("prime_awards") or []),
        "subaward_rows": list(structured.get("subaward_rows") or []),
        "prime_vehicles": list(structured.get("prime_vehicles") or []),
        "sub_vehicles": list(structured.get("sub_vehicles") or []),
        "upstream_primes": list(structured.get("upstream_primes") or []),
        "downstream_subcontractors": list(structured.get("downstream_subcontractors") or []),
        "top_customers": list(structured.get("top_customers") or []),
        "award_momentum": dict(structured.get("award_momentum") or {}),
        "sources": [SOURCE_NAME] if findings or relationships or structured else [],
    }
    graph_sync = None
    if sync_graph:
        graph_sync = sync_vendor_procurement_graph(
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            support_bundle=support_bundle,
        )
        support_bundle["graph_sync"] = graph_sync

    cached_bundle = {key: value for key, value in support_bundle.items() if key != "graph_sync"}
    _store_cached_support_entry(cache_key, bundle=cached_bundle, graph_sync=graph_sync)
    return support_bundle
