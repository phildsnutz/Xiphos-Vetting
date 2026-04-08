"""Vendor ownership/control dossier support."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import threading
import time
from typing import Any, Callable

from osint.connector_registry import get_source_metadata_defaults
from osint.france_inpi_rne import enrich as france_inpi_rne_enrich
from osint.gleif_lei import enrich as gleif_lei_enrich
from osint.gleif_bods_ownership_fixture import enrich as gleif_bods_fixture_enrich
from osint.norway_brreg import enrich as norway_brreg_enrich
from osint.openownership_bods_fixture import enrich as openownership_bods_fixture_enrich
from osint.openownership_bods_public import enrich as openownership_bods_public_enrich
from osint.public_html_ownership import enrich as public_html_ownership_enrich
from ownership_control_intelligence import build_oci_summary


_SUPPORT_CACHE_TTL_SECONDS = max(int(os.environ.get("XIPHOS_VENDOR_OWNERSHIP_CACHE_TTL_SECONDS", "900") or 900), 0)
_SUPPORT_CACHE_LOCK = threading.Lock()
_SUPPORT_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_GRAPH_SYNC_REL_TYPES = frozenset({"owned_by", "beneficially_owned_by", "parent_of", "officer_of"})
_GRAPH_SYNC_AUTHORITIES = frozenset({"official_registry", "official_regulatory", "standards_modeled_fixture", "public_registry_aggregator"})


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _normalize(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", _clean(value).upper()).strip()


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
    return (str(vendor_id or "").strip(), _seed_metadata_stamp(seed_metadata) or _normalize(vendor_name))


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


def clear_vendor_ownership_support_cache() -> None:
    with _SUPPORT_CACHE_LOCK:
        _SUPPORT_CACHE.clear()


def _finding_to_dict(finding: Any) -> dict[str, Any]:
    return {
        "source": getattr(finding, "source", ""),
        "category": getattr(finding, "category", ""),
        "title": getattr(finding, "title", ""),
        "detail": getattr(finding, "detail", ""),
        "severity": str(getattr(finding, "severity", "info") or "info"),
        "confidence": float(getattr(finding, "confidence", 0.0) or 0.0),
        "url": getattr(finding, "url", ""),
        "raw_data": dict(getattr(finding, "raw_data", {}) or {}),
        "source_class": getattr(finding, "source_class", ""),
        "authority_level": getattr(finding, "authority_level", ""),
        "access_model": getattr(finding, "access_model", ""),
        "artifact_ref": getattr(finding, "artifact_ref", ""),
        "structured_fields": dict(getattr(finding, "structured_fields", {}) or {}),
    }


def _identifier_value(enrichment: dict[str, Any] | None, key: str) -> Any:
    identifiers = enrichment.get("identifiers") if isinstance(enrichment, dict) and isinstance(enrichment.get("identifiers"), dict) else {}
    return identifiers.get(key)


def _support_ids(seed_metadata: dict[str, Any], enrichment: dict[str, Any] | None, vendor: dict[str, Any] | None) -> dict[str, Any]:
    ids: dict[str, Any] = {}
    identifiers = enrichment.get("identifiers") if isinstance(enrichment, dict) and isinstance(enrichment.get("identifiers"), dict) else {}
    for key, value in identifiers.items():
        if str(key).startswith("__") or value in (None, "", []):
            continue
        ids[str(key)] = value

    vendor_input = vendor.get("vendor_input") if isinstance(vendor, dict) and isinstance(vendor.get("vendor_input"), dict) else {}
    vendor_ownership = vendor_input.get("ownership") if isinstance(vendor_input.get("ownership"), dict) else {}
    for key in (
        "lei",
        "uk_company_number",
        "norway_org_number",
        "fr_siren",
        "fr_siret",
        "website",
        "official_website",
    ):
        if ids.get(key) in (None, "", []):
            value = vendor_ownership.get(key) or vendor_input.get(key)
            if value not in (None, "", []):
                ids[key] = value

    for key, value in (seed_metadata or {}).items():
        if value in (None, "", []):
            continue
        if (
            str(key).startswith("openownership_")
            or str(key).startswith("norway_")
            or str(key).startswith("france_")
            or str(key).startswith("gleif_")
            or str(key).startswith("public_html_ownership")
            or str(key) in {"bods_path", "bods_url", "website", "official_website", "uk_company_number", "fr_siren", "fr_siret", "norway_org_number", "lei"}
        ):
            ids[str(key)] = value
    return ids


def _country_hint(vendor: dict[str, Any] | None, enrichment: dict[str, Any] | None) -> str:
    for candidate in (
        (vendor or {}).get("country"),
        _identifier_value(enrichment, "country"),
        _identifier_value(enrichment, "legal_jurisdiction"),
    ):
        text = _clean(candidate).upper()
        if not text:
            continue
        if text.startswith("US"):
            return "US"
        return text
    return ""


def _connector_plan(country: str, ids: dict[str, Any], seed_metadata: dict[str, Any]) -> list[tuple[str, Callable[..., Any]]]:
    plan: list[tuple[str, Callable[..., Any]]] = []
    if _truthy(seed_metadata.get("ownership_fixture_mode")):
        plan.extend(
            [
                ("gleif_bods_ownership_fixture", gleif_bods_fixture_enrich),
                ("openownership_bods_fixture", openownership_bods_fixture_enrich),
            ]
        )

    plan.append(("gleif_lei", gleif_lei_enrich))
    if ids.get("openownership_bods_path") or ids.get("openownership_bods_url") or ids.get("bods_path") or ids.get("bods_url") or ids.get("uk_company_number") or country in {"GB", "GBR", "UK"}:
        plan.append(("openownership_bods_public", openownership_bods_public_enrich))
    if ids.get("norway_brreg_url") or ids.get("brreg_org_url") or ids.get("norway_org_number") or country in {"NO", "NOR"}:
        plan.append(("norway_brreg", norway_brreg_enrich))
    if ids.get("france_inpi_rne_url") or ids.get("inpi_rne_url") or ids.get("fr_siren") or country in {"FR", "FRA"}:
        plan.append(("france_inpi_rne", france_inpi_rne_enrich))
    return plan


def _connector_status_entry(name: str, result: Any) -> dict[str, Any]:
    metadata = get_source_metadata_defaults(name)
    entry = {
        "has_data": bool(getattr(result, "has_data", False) or getattr(result, "findings", None) or getattr(result, "relationships", None)),
        "findings_count": len(getattr(result, "findings", []) or []),
        "relationship_count": len(getattr(result, "relationships", []) or []),
        "error": str(getattr(result, "error", "") or ""),
        "elapsed_ms": int(getattr(result, "elapsed_ms", 0) or 0),
        **metadata,
    }
    structured = getattr(result, "structured_fields", None)
    if isinstance(structured, dict) and structured:
        entry["structured_fields"] = structured
    return entry


def _merge_identifier_source(identifier_sources: dict[str, list[str]], key: str, source: str) -> None:
    if not key or not source:
        return
    identifier_sources.setdefault(str(key), [])
    if source not in identifier_sources[str(key)]:
        identifier_sources[str(key)].append(source)


def _relationship_name(rel: dict[str, Any], side: str) -> str:
    if side == "source":
        return _clean(rel.get("source_name") or rel.get("source_entity") or rel.get("source_entity_name"))
    return _clean(rel.get("target_name") or rel.get("target_entity") or rel.get("target_entity_name"))


def _relationship_type(rel: dict[str, Any]) -> str:
    return _clean(rel.get("rel_type") or rel.get("type")).lower()


def _relationship_key(rel: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        _relationship_type(rel),
        _normalize(_relationship_name(rel, "source")),
        _normalize(_relationship_name(rel, "target")),
        _clean(rel.get("data_source")),
        _clean(rel.get("artifact_ref") or rel.get("evidence") or rel.get("evidence_url")),
    )


def _finding_key(finding: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _clean(finding.get("source")),
        _clean(finding.get("title")),
        _clean(finding.get("detail")),
        _clean(finding.get("artifact_ref") or finding.get("url")),
    )


def _best_authority_bucket(value: str) -> int:
    normalized = _clean(value).lower()
    order = {
        "official_registry": 0,
        "official_regulatory": 1,
        "public_registry_aggregator": 2,
        "standards_modeled_fixture": 3,
        "first_party_self_disclosed": 4,
        "third_party_public": 5,
    }
    return order.get(normalized, 9)


def _compose_control_lines(relationships: list[dict[str, Any]], oci_summary: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if oci_summary.get("named_beneficial_owner_known"):
        owner = _clean(oci_summary.get("named_beneficial_owner"))
        lines.append(f"Named beneficial owner resolves to {owner}.")
    elif oci_summary.get("controlling_parent_known"):
        parent = _clean(oci_summary.get("controlling_parent"))
        lines.append(f"Controlling parent resolves to {parent}; named beneficial owner is still not publicly resolved.")
    elif oci_summary.get("owner_class_known"):
        owner_class = _clean(oci_summary.get("owner_class"))
        lines.append(f"Ownership posture resolves only to {owner_class}; no named beneficial owner has been corroborated.")

    direct = [
        rel for rel in relationships
        if _relationship_type(rel) == "owned_by"
    ]
    if direct:
        best = sorted(
            direct,
            key=lambda row: (
                _best_authority_bucket(str(row.get("authority_level") or "")),
                -float(row.get("confidence") or 0.0),
            ),
        )[0]
        target = _relationship_name(best, "target")
        source = str(best.get("data_source") or "ownership source").replace("_", " ")
        if target:
            lines.append(f"Direct parent path is anchored to {target} via {source}.")

    indirect = [
        rel for rel in relationships
        if _relationship_type(rel) == "beneficially_owned_by"
    ]
    if indirect and not oci_summary.get("named_beneficial_owner_known"):
        names = [
            _relationship_name(rel, "target")
            for rel in sorted(
                indirect,
                key=lambda row: (
                    _best_authority_bucket(str(row.get("authority_level") or "")),
                    -float(row.get("confidence") or 0.0),
                ),
            )
            if _relationship_name(rel, "target")
        ]
        if names:
            lines.append("Beneficial ownership or ultimate-parent evidence points to " + ", ".join(names[:3]) + ".")

    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        lowered = line.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(line)
    return deduped[:4]


def _compose_registry_lines(connector_status: dict[str, Any], identifiers: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if identifiers.get("lei"):
        lines.append(f"LEI corroborated: {_clean(identifiers.get('lei'))}.")
    if identifiers.get("norway_org_number"):
        lines.append(f"Norway registry corroborated organisation number {_clean(identifiers.get('norway_org_number'))}.")
    if identifiers.get("fr_siren"):
        lines.append(f"France registry corroborated SIREN {_clean(identifiers.get('fr_siren'))}.")
    if identifiers.get("uk_company_number"):
        lines.append(f"UK registry anchor available through company number {_clean(identifiers.get('uk_company_number'))}.")

    for source, status in sorted(connector_status.items()):
        if not isinstance(status, dict) or not status.get("has_data"):
            continue
        structured = status.get("structured_fields") if isinstance(status.get("structured_fields"), dict) else {}
        summary = structured.get("summary") if isinstance(structured.get("summary"), dict) else {}
        if source == "norway_brreg" and summary:
            count = int(summary.get("beneficial_owner_count") or 0)
            if count > 0:
                lines.append(f"Norway Brreg discloses {count} beneficial owner record{'s' if count != 1 else ''}.")
        if source == "france_inpi_rne" and summary:
            count = int(summary.get("beneficial_owner_count") or 0)
            access = _clean(summary.get("beneficial_owner_access"))
            if count > 0:
                lines.append(f"France INPI / RNE exposes {count} beneficial owner record{'s' if count != 1 else ''}.")
            elif access:
                lines.append(f"France INPI / RNE access posture: {access}.")
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        lowered = line.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(line)
    return deduped[:4]


def _compose_gap_lines(oci_summary: dict[str, Any], connector_status: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if not oci_summary.get("named_beneficial_owner_known") and not oci_summary.get("controlling_parent_known"):
        gaps.append("Named beneficial owner and controlling parent remain unresolved from current registry-grade evidence.")
    elif oci_summary.get("controlling_parent_known") and not oci_summary.get("named_beneficial_owner_known"):
        gaps.append("Named beneficial owner is still not public even though the controlling parent path is resolved.")
    if not any(
        isinstance(status, dict) and status.get("has_data") and str(status.get("authority_level") or "").lower() in {"official_registry", "official_regulatory"}
        for status in connector_status.values()
    ):
        gaps.append("No official registry-grade ownership evidence was captured for this entity.")
    for source, status in sorted(connector_status.items()):
        if not isinstance(status, dict) or status.get("has_data") or not status.get("error"):
            continue
        if source in {"norway_brreg", "france_inpi_rne"}:
            gaps.append(f"{source.replace('_', ' ').title()} did not return usable data: {_clean(status.get('error'))}.")
    deduped: list[str] = []
    seen: set[str] = set()
    for gap in gaps:
        lowered = gap.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(gap)
    return deduped[:4]


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


def _graph_entity_type(rel: dict[str, Any], side: str) -> str:
    if side == "source":
        return str(rel.get("source_entity_type") or "company")
    return str(rel.get("target_entity_type") or "company")


def _resolve_graph_entity(
    *,
    name: str,
    entity_type: str,
    source_name: str,
    index: dict[tuple[str, str], dict[str, Any]],
    identifiers: dict[str, Any] | None = None,
    country: str = "",
) -> str:
    from entity_resolution import ResolvedEntity
    from knowledge_graph import save_entity

    clean_name = str(name or "").strip()
    if not clean_name:
        return ""
    entity_type = str(entity_type or "company").strip() or "company"
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
            "country": country,
            "sources": [],
            "confidence": 0.82 if entity_type == "person" else 0.8,
        }
    else:
        entity_id = str(record["id"])

    aliases = [item for item in record.get("aliases", []) if item and item != clean_name]
    merged_identifiers = dict(record.get("identifiers") or {})
    for key_name, value in (identifiers or {}).items():
        if value not in (None, "", []):
            merged_identifiers[str(key_name)] = value
    sources = [str(item or "").strip() for item in (record.get("sources") or []) if str(item or "").strip()]
    if source_name not in sources:
        sources.append(source_name)
    save_entity(
        ResolvedEntity(
            id=entity_id,
            canonical_name=clean_name,
            entity_type=entity_type,
            aliases=aliases,
            identifiers=merged_identifiers,
            country=str(country or record.get("country") or ""),
            sources=sources,
            confidence=max(float(record.get("confidence") or 0.0), 0.8),
            last_updated=datetime.now(timezone.utc).isoformat(),
        )
    )
    index[key] = {
        **record,
        "id": entity_id,
        "canonical_name": clean_name,
        "entity_type": entity_type,
        "aliases": aliases,
        "identifiers": merged_identifiers,
        "country": str(country or record.get("country") or ""),
        "sources": sources,
        "confidence": max(float(record.get("confidence") or 0.0), 0.8),
    }
    return entity_id


def sync_vendor_ownership_graph(
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
        and _relationship_type(rel) in _GRAPH_SYNC_REL_TYPES
        and str(rel.get("authority_level") or "").strip().lower() in _GRAPH_SYNC_AUTHORITIES
    ]

    from knowledge_graph import get_kg_conn

    for rel in syncable_relationships:
        rel_type = _relationship_type(rel)
        source_name = _relationship_name(rel, "source")
        target_name = _relationship_name(rel, "target")
        if not source_name or not target_name:
            continue
        source_id = _resolve_graph_entity(
            name=source_name,
            entity_type=_graph_entity_type(rel, "source"),
            source_name=str(rel.get("data_source") or "vendor_ownership_support"),
            index=index,
            identifiers=rel.get("source_identifiers") if isinstance(rel.get("source_identifiers"), dict) else {},
        )
        target_id = _resolve_graph_entity(
            name=target_name,
            entity_type=_graph_entity_type(rel, "target"),
            source_name=str(rel.get("data_source") or "vendor_ownership_support"),
            index=index,
            identifiers=rel.get("target_identifiers") if isinstance(rel.get("target_identifiers"), dict) else {},
            country=str(rel.get("country") or ""),
        )
        if not source_id or not target_id:
            continue
        evidence = str(rel.get("evidence") or "")
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
            evidence_url=str(rel.get("evidence_url") or ""),
            evidence_title=str(rel.get("evidence_title") or f"Vendor ownership support: {vendor_name}"),
            source_class=str(rel.get("source_class") or "public_connector"),
            authority_level=str(rel.get("authority_level") or ""),
            access_model=str(rel.get("access_model") or ""),
            artifact_ref=str(rel.get("artifact_ref") or ""),
            structured_fields=dict(rel.get("structured_fields", {}) or {}),
            raw_data=dict(rel.get("raw_data", {}) or {}),
            observed_at=str(rel.get("observed_at") or ""),
            valid_from=str(rel.get("valid_from") or ""),
            vendor_id=vendor_id,
        )
        relationships_written += 1

    return {
        "enabled": True,
        "relationship_count": relationships_written,
        "reused_relationship_count": relationships_reused,
        "syncable_relationship_count": len(syncable_relationships),
    }


def build_vendor_ownership_support(
    *,
    vendor_id: str,
    vendor: dict[str, Any] | None = None,
    enrichment: dict[str, Any] | None = None,
    sync_graph: bool = False,
) -> dict[str, Any] | None:
    vendor_name = _clean((vendor or {}).get("name"))
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
                graph_sync = sync_vendor_ownership_graph(
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

    country = _country_hint(vendor, enrichment)
    ids = _support_ids(seed_metadata, enrichment, vendor)
    findings: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    identifiers: dict[str, Any] = {}
    identifier_sources: dict[str, list[str]] = {}
    connector_status: dict[str, Any] = {}
    ran_connectors: list[str] = []

    plan = _connector_plan(country, ids, seed_metadata)
    for connector_name, enrich_fn in plan:
        ran_connectors.append(connector_name)
        result = enrich_fn(vendor_name, country=country, **ids)
        status = _connector_status_entry(connector_name, result)
        connector_status[connector_name] = status

        for key, value in dict(getattr(result, "identifiers", {}) or {}).items():
            if value in (None, "", []):
                continue
            if identifiers.get(key) in (None, "", []):
                identifiers[str(key)] = value
            elif _clean(identifiers.get(key)) == _clean(value):
                identifiers[str(key)] = value
            _merge_identifier_source(identifier_sources, str(key), connector_name)

        findings.extend(
            _finding_to_dict(finding)
            for finding in (getattr(result, "findings", []) or [])
        )
        relationships.extend(
            dict(rel)
            for rel in (getattr(result, "relationships", []) or [])
            if isinstance(rel, dict)
        )

    official_relationships = [
        rel for rel in relationships
        if str(rel.get("authority_level") or "").lower() in {"official_registry", "official_regulatory", "standards_modeled_fixture", "public_registry_aggregator"}
    ]
    if ids.get("website") and not official_relationships and not _truthy(seed_metadata.get("ownership_disable_public_html")):
        connector_name = "public_html_ownership"
        ran_connectors.append(connector_name)
        result = public_html_ownership_enrich(vendor_name, country=country, **ids)
        connector_status[connector_name] = _connector_status_entry(connector_name, result)
        for key, value in dict(getattr(result, "identifiers", {}) or {}).items():
            if value in (None, "", []):
                continue
            if identifiers.get(key) in (None, "", []):
                identifiers[str(key)] = value
            _merge_identifier_source(identifier_sources, str(key), connector_name)
        findings.extend(_finding_to_dict(finding) for finding in (getattr(result, "findings", []) or []))
        relationships.extend(dict(rel) for rel in (getattr(result, "relationships", []) or []) if isinstance(rel, dict))

    dedup_findings: list[dict[str, Any]] = []
    seen_findings: set[tuple[str, str, str, str]] = set()
    for finding in findings:
        key = _finding_key(finding)
        if key in seen_findings:
            continue
        seen_findings.add(key)
        dedup_findings.append(finding)

    dedup_relationships: list[dict[str, Any]] = []
    seen_relationships: set[tuple[str, str, str, str, str]] = set()
    for relationship in relationships:
        key = _relationship_key(relationship)
        if key in seen_relationships:
            continue
        seen_relationships.add(key)
        dedup_relationships.append(relationship)

    vendor_input = vendor.get("vendor_input") if isinstance(vendor, dict) and isinstance(vendor.get("vendor_input"), dict) else {}
    ownership_profile = vendor_input.get("ownership") if isinstance(vendor_input.get("ownership"), dict) else {}
    oci_summary = build_oci_summary(ownership_profile, dedup_findings, dedup_relationships)
    control_lines = _compose_control_lines(dedup_relationships, oci_summary)
    registry_lines = _compose_registry_lines(connector_status, identifiers)
    gap_lines = _compose_gap_lines(oci_summary, connector_status)
    connectors_with_data = sum(1 for status in connector_status.values() if isinstance(status, dict) and status.get("has_data"))
    official_connectors_with_data = sum(
        1
        for status in connector_status.values()
        if isinstance(status, dict)
        and status.get("has_data")
        and str(status.get("authority_level") or "").lower() in {"official_registry", "official_regulatory"}
    )
    support_bundle = {
        "vendor_name": vendor_name,
        "country": country,
        "connectors_run": len(ran_connectors),
        "connectors_with_data": connectors_with_data,
        "official_connectors_with_data": official_connectors_with_data,
        "sources": [
            name
            for name, status in connector_status.items()
            if isinstance(status, dict) and status.get("has_data")
        ],
        "identifiers": identifiers,
        "identifier_sources": identifier_sources,
        "connector_status": connector_status,
        "findings": dedup_findings,
        "relationships": dedup_relationships,
        "oci_summary": oci_summary,
        "control_lines": control_lines,
        "registry_lines": registry_lines,
        "gap_lines": gap_lines,
        "metrics": {
            "ownership_relationship_count": len(
                [rel for rel in dedup_relationships if _relationship_type(rel) in {"owned_by", "beneficially_owned_by", "parent_of"}]
            ),
            "named_beneficial_owner_known": bool(oci_summary.get("named_beneficial_owner_known")),
            "controlling_parent_known": bool(oci_summary.get("controlling_parent_known")),
            "owner_class_known": bool(oci_summary.get("owner_class_known")),
            "official_connectors_with_data": official_connectors_with_data,
        },
    }

    graph_sync = None
    if sync_graph:
        graph_sync = sync_vendor_ownership_graph(
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            support_bundle=support_bundle,
        )
        support_bundle["graph_sync"] = graph_sync

    cached_bundle = {key: value for key, value in support_bundle.items() if key != "graph_sync"}
    _store_cached_support_entry(cache_key, bundle=cached_bundle, graph_sync=graph_sync)
    return support_bundle


def merge_enrichment_with_ownership_support(
    enrichment: dict[str, Any] | None,
    support_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    base = deepcopy(enrichment if isinstance(enrichment, dict) else {})
    if not isinstance(support_bundle, dict):
        return base

    merged_identifiers = dict(base.get("identifiers") or {})
    merged_sources = {
        str(key): list(values)
        for key, values in (base.get("identifier_sources") or {}).items()
        if isinstance(values, list)
    }
    merged_status = {
        str(key): dict(value)
        for key, value in (base.get("connector_status") or {}).items()
        if isinstance(value, dict)
    }

    for key, value in (support_bundle.get("identifiers") or {}).items():
        if value in (None, "", []):
            continue
        if merged_identifiers.get(key) in (None, "", []):
            merged_identifiers[str(key)] = value
        for source in (support_bundle.get("identifier_sources") or {}).get(key, []) or []:
            _merge_identifier_source(merged_sources, str(key), str(source))

    for source, status in (support_bundle.get("connector_status") or {}).items():
        if isinstance(status, dict):
            merged_status.setdefault(str(source), dict(status))

    existing_findings = [dict(item) for item in (base.get("findings") or []) if isinstance(item, dict)]
    seen_findings = {_finding_key(item) for item in existing_findings}
    for finding in support_bundle.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        key = _finding_key(finding)
        if key in seen_findings:
            continue
        seen_findings.add(key)
        existing_findings.append(dict(finding))

    existing_relationships = [dict(item) for item in (base.get("relationships") or []) if isinstance(item, dict)]
    seen_relationships = {_relationship_key(item) for item in existing_relationships}
    for relationship in support_bundle.get("relationships") or []:
        if not isinstance(relationship, dict):
            continue
        key = _relationship_key(relationship)
        if key in seen_relationships:
            continue
        seen_relationships.add(key)
        existing_relationships.append(dict(relationship))

    merged_summary = dict(base.get("summary") or {})
    merged_summary["connectors_run"] = len(merged_status)
    merged_summary["connectors_with_data"] = sum(
        1 for status in merged_status.values()
        if isinstance(status, dict) and status.get("has_data")
    )
    merged_summary["findings_total"] = len(existing_findings)

    base["identifiers"] = merged_identifiers
    base["identifier_sources"] = merged_sources
    base["connector_status"] = merged_status
    base["findings"] = existing_findings
    base["relationships"] = existing_relationships
    base["summary"] = merged_summary
    return base
