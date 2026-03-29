"""Portable supplier-passport builder for case-level trust artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
from typing import Any
from urllib.parse import urlparse

import db
from osint.connector_registry import get_connector_entry, get_source_metadata_defaults
from ownership_control_intelligence import build_oci_summary, get_oci_adjudicator_cache_key

from decision_tribunal import build_decision_tribunal

try:
    from artifact_vault import list_case_artifacts
    HAS_ARTIFACT_VAULT = True
except ImportError:
    list_case_artifacts = None
    HAS_ARTIFACT_VAULT = False

try:
    from cyber_evidence import get_latest_cyber_evidence_summary
    HAS_CYBER_EVIDENCE = True
except ImportError:
    get_latest_cyber_evidence_summary = None
    HAS_CYBER_EVIDENCE = False

try:
    from export_evidence import get_export_evidence_summary
    HAS_EXPORT_EVIDENCE = True
except ImportError:
    get_export_evidence_summary = None
    HAS_EXPORT_EVIDENCE = False

try:
    from foci_evidence import get_latest_foci_summary
    HAS_FOCI_SUMMARY = True
except ImportError:
    get_latest_foci_summary = None
    HAS_FOCI_SUMMARY = False

try:
    from graph_ingest import build_graph_intelligence_summary, get_vendor_graph_summary
    HAS_GRAPH_SUMMARY = True
except ImportError:
    build_graph_intelligence_summary = None
    get_vendor_graph_summary = None
    HAS_GRAPH_SUMMARY = False

try:
    from knowledge_graph import attach_relationship_provenance
except ImportError:
    attach_relationship_provenance = None

try:
    from network_risk import compute_network_risk
    HAS_NETWORK_RISK = True
except ImportError:
    compute_network_risk = None
    HAS_NETWORK_RISK = False

try:
    from workflow_control_summary import build_workflow_control_summary
    HAS_WORKFLOW_CONTROL = True
except ImportError:
    build_workflow_control_summary = None
    HAS_WORKFLOW_CONTROL = False

try:
    from threat_intel_substrate import build_threat_intel_summary
    HAS_THREAT_INTEL = True
except ImportError:
    build_threat_intel_summary = None
    HAS_THREAT_INTEL = False


PROGRAM_LABELS = {
    "dod_classified": "DoD / IC (Classified)",
    "dod_unclassified": "DoD (Unclassified)",
    "federal_non_dod": "Federal (Non-DoD)",
    "regulated_commercial": "Regulated Commercial",
    "commercial": "Commercial",
    "weapons_system": "DoD (Unclassified)",
    "mission_critical": "Federal (Non-DoD)",
    "nuclear_related": "DoD (Unclassified)",
    "intelligence_community": "DoD / IC (Classified)",
    "critical_infrastructure": "Federal (Non-DoD)",
    "dual_use": "Regulated Commercial",
    "standard_industrial": "Commercial",
    "commercial_off_shelf": "Commercial",
    "services": "Commercial",
}

CONTROL_PATH_RELATIONSHIPS = {
    "backed_by",
    "led_by",
    "depends_on_network",
    "depends_on_service",
    "routes_payment_through",
    "distributed_by",
    "operates_facility",
    "ships_via",
    "owned_by",
    "beneficially_owned_by",
}

_STALE_CONTROL_PATH_DAYS = 365
_TRACKED_IDENTIFIER_SOURCES = {
    "cage": "sam_gov",
    "uei": "sam_gov",
    "lei": "gleif_lei",
    "cik": "sec_edgar",
    "uk_company_number": "uk_companies_house",
    "ca_corporation_number": "corporations_canada",
    "business_number": "corporations_canada",
    "abn": "australia_abn_asic",
    "acn": "australia_abn_asic",
    "uen": "singapore_acra",
    "nzbn": "new_zealand_companies_office",
    "nz_company_number": "new_zealand_companies_office",
    "norway_org_number": "norway_brreg",
    "kvk_number": "netherlands_kvk",
    "fr_siren": "france_inpi_rne",
    "fr_siret": "france_inpi_rne",
    "website": "public_search_ownership",
}
_IDENTIFIER_DISPLAY_ORDER = (
    "cage",
    "uei",
    "duns",
    "ncage",
    "lei",
    "cik",
    "uk_company_number",
    "ca_corporation_number",
    "business_number",
    "abn",
    "acn",
    "uen",
    "nzbn",
    "nz_company_number",
    "norway_org_number",
    "kvk_number",
    "fr_siren",
    "fr_siret",
    "website",
)
_AUTHORITY_PRIORITY = {
    "official_registry": 0,
    "official_program_system": 1,
    "official_regulatory": 2,
    "first_party_self_disclosed": 3,
    "third_party_public": 4,
    "analyst_curated_fixture": 5,
    "standards_modeled_fixture": 6,
}
_OFFICIAL_AUTHORITY_LEVELS = {
    "official_registry",
    "official_program_system",
    "official_regulatory",
}
_OFFICIAL_IDENTITY_FIELDS = (
    "cage",
    "uei",
    "lei",
    "cik",
    "uk_company_number",
    "ca_corporation_number",
    "business_number",
    "abn",
    "acn",
    "uen",
    "nzbn",
    "nz_company_number",
    "norway_org_number",
    "kvk_number",
    "fr_siren",
    "fr_siret",
)
_CONNECTOR_COUNTRY_HINTS = {
    "sam_gov": {"US", "USA"},
    "uk_companies_house": {"UK", "GB", "GBR", "UNITED KINGDOM", "ENGLAND", "SCOTLAND", "WALES", "NORTHERN IRELAND"},
    "corporations_canada": {"CA", "CAN", "CANADA"},
    "australia_abn_asic": {"AU", "AUS", "AUSTRALIA"},
    "singapore_acra": {"SG", "SGP", "SINGAPORE"},
    "new_zealand_companies_office": {"NZ", "NZL", "NEW ZEALAND"},
    "norway_brreg": {"NO", "NOR", "NORWAY"},
    "netherlands_kvk": {"NL", "NLD", "NETHERLANDS"},
    "france_inpi_rne": {"FR", "FRA", "FRANCE"},
}
_CONNECTOR_DOMAIN_HINTS = {
    "uk_companies_house": (".uk", ".co.uk", ".org.uk", ".gov.uk"),
    "corporations_canada": (".ca",),
    "australia_abn_asic": (".au",),
    "singapore_acra": (".sg",),
    "new_zealand_companies_office": (".nz",),
    "norway_brreg": (".no",),
    "netherlands_kvk": (".nl",),
    "france_inpi_rne": (".fr",),
}
_CONNECTOR_IDENTIFIER_HINTS = {
    "sam_gov": ("cage", "uei", "ncage", "duns", "federal_contractor", "has_sam_subcontract_reports"),
    "gleif_lei": ("lei",),
    "sec_edgar": ("cik",),
    "uk_companies_house": ("uk_company_number",),
    "corporations_canada": ("ca_corporation_number", "business_number"),
    "australia_abn_asic": ("abn", "acn"),
    "singapore_acra": ("uen",),
    "new_zealand_companies_office": ("nzbn", "nz_company_number"),
    "norway_brreg": ("norway_org_number",),
    "netherlands_kvk": ("kvk_number",),
    "france_inpi_rne": ("fr_siren",),
}
_GATED_OFFICIAL_CONNECTOR_SOURCES = {
    "norway_brreg",
    "france_inpi_rne",
}

_SUPPLIER_PASSPORT_CACHE: dict[tuple[str, str, str, str, str, str, str, str, str, str], dict[str, Any]] = {}
_SUPPLIER_PASSPORT_CACHE_LOCK = threading.Lock()
_SUPPLIER_PASSPORT_TTL_SECONDS = 120


def _summary_version(summary: dict | None) -> str:
    if not isinstance(summary, dict):
        return ""
    for key in ("generated_at", "evaluated_at", "updated_at", "scored_at", "enriched_at", "created_at", "id"):
        value = summary.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _supplier_passport_cache_key(
    case_id: str,
    mode: str,
    vendor: dict | None,
    score: dict | None,
    latest_decision: dict | None,
    enrichment: dict | None,
    foci_summary: dict | None,
    cyber_summary: dict | None,
    export_summary: dict | None,
    oci_adjudicator_key: str,
) -> tuple[str, str, str, str, str, str, str, str, str, str]:
    return (
        case_id,
        mode,
        str((vendor or {}).get("updated_at") or (vendor or {}).get("created_at") or ""),
        str((score or {}).get("scored_at") or ""),
        str((latest_decision or {}).get("created_at") or (latest_decision or {}).get("id") or ""),
        str((enrichment or {}).get("enriched_at") or ""),
        _summary_version(foci_summary),
        _summary_version(cyber_summary),
        _summary_version(export_summary),
        oci_adjudicator_key,
    )


def _get_cached_supplier_passport(cache_key: tuple[str, str, str, str, str, str, str, str, str, str]) -> dict[str, Any] | None:
    now = time.time()
    with _SUPPLIER_PASSPORT_CACHE_LOCK:
        cached = _SUPPLIER_PASSPORT_CACHE.get(cache_key)
        if not cached:
            return None
        if now - float(cached.get("_cached_at", 0.0)) > _SUPPLIER_PASSPORT_TTL_SECONDS:
            _SUPPLIER_PASSPORT_CACHE.pop(cache_key, None)
            return None
        payload = cached.get("payload")
        return payload.copy() if isinstance(payload, dict) else None


def _store_cached_supplier_passport(cache_key: tuple[str, str, str, str, str, str, str, str, str, str], passport: dict[str, Any]) -> None:
    with _SUPPLIER_PASSPORT_CACHE_LOCK:
        _SUPPLIER_PASSPORT_CACHE[cache_key] = {
            "_cached_at": time.time(),
            "payload": passport.copy(),
        }


def _program_label(program: str) -> str:
    return PROGRAM_LABELS.get(str(program or "").lower(), str(program or "Unknown").replace("_", " ").title())


def _normalized_passport_mode(mode: str | None) -> str:
    normalized = str(mode or "full").strip().lower()
    if normalized in {"light", "control"}:
        return normalized
    return "full"


def _passport_mode_settings(mode: str) -> dict[str, Any]:
    normalized = _normalized_passport_mode(mode)
    if normalized == "light":
        return {
            "graph_depth": 1,
            "include_provenance": False,
            "max_claim_records": 0,
            "max_evidence_records": 0,
            "include_workflow_control": False,
            "include_network_risk": False,
            "include_tribunal": False,
        }
    if normalized == "control":
        return {
            "graph_depth": 2,
            "include_provenance": True,
            "max_claim_records": 1,
            "max_evidence_records": 1,
            "include_workflow_control": False,
            "include_network_risk": False,
            "include_tribunal": False,
        }
    return {
        "graph_depth": 2,
        "include_provenance": True,
        "max_claim_records": 2,
        "max_evidence_records": 2,
        "include_workflow_control": True,
        "include_network_risk": True,
        "include_tribunal": True,
    }


def _workflow_lane(vendor: dict, cyber_summary: dict | None = None, export_summary: dict | None = None) -> str:
    vendor_input = vendor.get("vendor_input", {}) if isinstance(vendor.get("vendor_input"), dict) else {}
    profile = str(vendor_input.get("profile") or vendor.get("profile") or "").lower()
    if isinstance(export_summary, dict) or isinstance(vendor_input.get("export_authorization"), dict) or profile == "itar_trade_compliance":
        return "export_authorization"
    if isinstance(cyber_summary, dict) and any(value not in (None, "", [], {}, False) for value in cyber_summary.values()):
        return "supplier_cyber_trust"
    if profile in {"supplier_cyber_trust", "cmmc_supplier_review"}:
        return "supplier_cyber_trust"
    return "defense_counterparty_trust"


def _passport_posture(score: dict | None, latest_decision: dict | None = None) -> str:
    if isinstance(latest_decision, dict) and latest_decision.get("decision"):
        decision = str(latest_decision["decision"]).lower()
        return {
            "approve": "approved",
            "reject": "blocked",
            "escalate": "review",
        }.get(decision, decision)

    tier = str(((score or {}).get("calibrated") or {}).get("calibrated_tier") or "").upper()
    if any(token in tier for token in ("BLOCKED", "HARD_STOP", "DENIED", "DISQUALIFIED")):
        return "blocked"
    if any(token in tier for token in ("REVIEW", "ELEVATED", "CAUTION", "CONDITIONAL")):
        return "review"
    if any(token in tier for token in ("APPROVED", "QUALIFIED", "CLEAR", "ACCEPTABLE")):
        return "approved"
    return "pending"


def _entity_map(graph_summary: dict | None) -> dict[str, dict]:
    if not isinstance(graph_summary, dict):
        return {}
    entities = graph_summary.get("entities") or []
    return {
        str(entity.get("id")): entity
        for entity in entities
        if isinstance(entity, dict) and entity.get("id")
    }


def _top_control_paths(graph_summary: dict | None, limit: int = 5) -> list[dict]:
    if not isinstance(graph_summary, dict):
        return []
    relationships = graph_summary.get("relationships") or []
    if not isinstance(relationships, list):
        return []

    entity_lookup = _entity_map(graph_summary)
    rows: list[dict] = []
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        rel_type = str(rel.get("rel_type") or "")
        if rel_type not in CONTROL_PATH_RELATIONSHIPS:
            continue
        data_sources = rel.get("data_sources") or []
        rows.append(
            {
                "rel_type": rel_type,
                "source_entity_id": rel.get("source_entity_id"),
                "source_name": (entity_lookup.get(str(rel.get("source_entity_id"))) or {}).get("canonical_name")
                or rel.get("source_entity_id"),
                "target_entity_id": rel.get("target_entity_id"),
                "target_name": (entity_lookup.get(str(rel.get("target_entity_id"))) or {}).get("canonical_name")
                or rel.get("target_entity_id"),
                "confidence": float(rel.get("confidence") or 0.0),
                "corroboration_count": int(rel.get("corroboration_count") or len(data_sources) or 1),
                "data_sources": data_sources,
                "first_seen_at": rel.get("first_seen_at") or rel.get("created_at"),
                "last_seen_at": rel.get("last_seen_at") or rel.get("created_at"),
                "evidence_refs": _relationship_evidence_refs(rel),
            }
        )

    rows.sort(
        key=lambda item: (
            -int(item.get("corroboration_count") or 0),
            -float(item.get("confidence") or 0.0),
            str(item.get("rel_type") or ""),
        )
    )
    return rows[:limit]


def _control_relationship_graph(graph_summary: dict | None) -> dict:
    if not isinstance(graph_summary, dict):
        return {"entities": [], "relationships": []}

    root_entity_ids = {
        str(entity_id)
        for entity_id in (graph_summary.get("root_entity_ids") or [])
        if entity_id
    }
    control_relationships = [
        rel
        for rel in (graph_summary.get("relationships") or [])
        if isinstance(rel, dict) and str(rel.get("rel_type") or "") in CONTROL_PATH_RELATIONSHIPS
    ]
    if root_entity_ids:
        control_relationships = [
            rel
            for rel in control_relationships
            if str(rel.get("source_entity_id") or "") in root_entity_ids
            or str(rel.get("target_entity_id") or "") in root_entity_ids
        ]

    should_hydrate = any(not (rel.get("claim_records") or []) for rel in control_relationships)
    if should_hydrate and callable(attach_relationship_provenance):
        try:
            control_relationships = attach_relationship_provenance(
                control_relationships,
                max_claim_records=2,
                max_evidence_records=2,
            )
        except Exception:
            # Passport reads should degrade to topology-only control paths rather than fail.
            pass

    related_entity_ids = set(root_entity_ids)
    for rel in control_relationships:
        source_id = str(rel.get("source_entity_id") or "")
        target_id = str(rel.get("target_entity_id") or "")
        if source_id:
            related_entity_ids.add(source_id)
        if target_id:
            related_entity_ids.add(target_id)

    entities = []
    for entity in (graph_summary.get("entities") or []):
        entity_id = str((entity or {}).get("id") or "")
        if not related_entity_ids or entity_id in related_entity_ids:
            entities.append(entity)

    return {
        "entities": entities,
        "relationships": control_relationships,
    }


def _relationship_evidence_refs(rel: dict[str, Any], limit: int = 3) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for claim_record in rel.get("claim_records", []) or []:
        for evidence_record in claim_record.get("evidence_records", []) or []:
            title = str(evidence_record.get("title") or evidence_record.get("source") or "Evidence")
            url = str(evidence_record.get("url") or "")
            artifact_ref = str(evidence_record.get("artifact_ref") or "")
            key = (title, url, artifact_ref)
            if key in seen:
                continue
            seen.add(key)
            refs.append(
                {
                    "title": title,
                    "url": url,
                    "artifact_ref": artifact_ref,
                    "source": str(evidence_record.get("source") or ""),
                }
            )
            if len(refs) >= limit:
                return refs
    return refs


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None


def _graph_claim_health(graph_summary: dict | None) -> dict[str, Any]:
    if not isinstance(graph_summary, dict):
        return {
            "control_relationships": 0,
            "corroborated_paths": 0,
            "contradicted_claims": 0,
            "stale_paths": 0,
            "freshest_observation_at": None,
            "stale_threshold_days": _STALE_CONTROL_PATH_DAYS,
        }

    relationships = [
        rel
        for rel in (graph_summary.get("relationships") or [])
        if isinstance(rel, dict) and str(rel.get("rel_type") or "") in CONTROL_PATH_RELATIONSHIPS
    ]
    now = datetime.now(timezone.utc)
    corroborated = 0
    contradicted_claims = 0
    stale_paths = 0
    freshest: datetime | None = None

    for rel in relationships:
        if int(rel.get("corroboration_count") or 0) > 1:
            corroborated += 1

        last_seen = _parse_timestamp(rel.get("last_seen_at") or rel.get("created_at"))
        if last_seen:
            if freshest is None or last_seen > freshest:
                freshest = last_seen
            age_days = (now - last_seen.astimezone(timezone.utc)).days
            if age_days >= _STALE_CONTROL_PATH_DAYS:
                stale_paths += 1

        for claim_record in rel.get("claim_records", []) or []:
            state = str(claim_record.get("contradiction_state") or "unreviewed").lower()
            if state in {"contradicted", "disputed", "challenged"}:
                contradicted_claims += 1

    return {
        "control_relationships": len(relationships),
        "corroborated_paths": corroborated,
        "contradicted_claims": contradicted_claims,
        "stale_paths": stale_paths,
        "freshest_observation_at": freshest.isoformat().replace("+00:00", "Z") if freshest else None,
        "stale_threshold_days": _STALE_CONTROL_PATH_DAYS,
    }


def _artifact_snapshot(case_id: str) -> dict:
    if not callable(list_case_artifacts):
        return {"count": 0, "by_source": {}}
    counts: dict[str, int] = {}
    for record in list_case_artifacts(case_id, limit=50):
        source = str(record.get("source_system") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return {"count": sum(counts.values()), "by_source": counts}


def _clean_identifier_value(value: Any) -> Any | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
        return candidate or None
    return value


def _pick_next_access_time(status: dict[str, Any]) -> str | None:
    structured = status.get("structured_fields") if isinstance(status.get("structured_fields"), dict) else {}
    sam_api_status = structured.get("sam_api_status") if isinstance(structured.get("sam_api_status"), dict) else {}
    for lookup in sam_api_status.values():
        if not isinstance(lookup, dict):
            continue
        next_access_time = str(lookup.get("next_access_time") or "").strip()
        if next_access_time:
            return next_access_time
    return None


def _preferred_identifier_source(sources: list[str], connector_status: dict[str, Any]) -> str | None:
    ranked_sources: list[tuple[int, str]] = []
    for source in sources:
        status = connector_status.get(source) if isinstance(connector_status.get(source), dict) else {}
        authority = str(status.get("authority_level") or "")
        ranked_sources.append((_AUTHORITY_PRIORITY.get(authority, 99), source))
    if not ranked_sources:
        return None
    ranked_sources.sort(key=lambda item: (item[0], item[1]))
    return ranked_sources[0][1]


def _connector_status_with_defaults(source: str | None, connector_status: dict[str, Any]) -> dict[str, Any]:
    source_name = str(source or "").strip()
    defaults = get_source_metadata_defaults(source_name) if source_name else {
        "source_class": "public_connector",
        "authority_level": "",
        "access_model": "",
    }
    status = connector_status.get(source_name) if source_name and isinstance(connector_status.get(source_name), dict) else {}
    return {
        **defaults,
        **(status if isinstance(status, dict) else {}),
    }


def _is_official_authority(authority_level: str | None) -> bool:
    return str(authority_level or "").strip().lower() in _OFFICIAL_AUTHORITY_LEVELS


def _status_is_throttled(status: dict[str, Any]) -> bool:
    if bool(status.get("throttled")):
        return True
    structured = status.get("structured_fields") if isinstance(status.get("structured_fields"), dict) else {}

    def _walk(value: Any) -> bool:
        if isinstance(value, dict):
            if bool(value.get("throttled")):
                return True
            return any(_walk(item) for item in value.values())
        if isinstance(value, list):
            return any(_walk(item) for item in value)
        return False

    return _walk(structured)


def _official_connector_snapshot(enrichment: dict[str, Any] | None) -> list[dict[str, Any]]:
    connector_status = (
        enrichment.get("connector_status")
        if isinstance(enrichment, dict) and isinstance(enrichment.get("connector_status"), dict)
        else {}
    )
    rows: list[dict[str, Any]] = []
    for source in sorted(str(name) for name in connector_status.keys()):
        status = _connector_status_with_defaults(source, connector_status)
        authority_level = str(status.get("authority_level") or "")
        if not _is_official_authority(authority_level):
            continue
        entry = get_connector_entry(source)
        rows.append(
            {
                "source": source,
                "label": entry.label if entry else source.replace("_", " ").title(),
                "authority_level": authority_level,
                "access_model": str(status.get("access_model") or ""),
                "has_data": bool(status.get("has_data")),
                "error": str(status.get("error") or "").strip(),
                "throttled": _status_is_throttled(status),
                "next_access_time": _pick_next_access_time(status),
            }
        )
    return rows


def _country_hints_from_vendor(vendor: dict[str, Any] | None, identifiers: dict[str, Any]) -> set[str]:
    hints: set[str] = set()

    def add_hint(value: Any) -> None:
        if value in (None, ""):
            return
        text = str(value).strip().upper()
        if not text:
            return
        hints.add(text)
        if "-" in text:
            hints.add(text.split("-", 1)[0])

    if isinstance(vendor, dict):
        add_hint(vendor.get("country"))
        vendor_input = vendor.get("vendor_input") if isinstance(vendor.get("vendor_input"), dict) else {}
        add_hint(vendor_input.get("country"))
        add_hint(vendor_input.get("country_code"))
    for key in ("country", "country_code", "jurisdiction", "legal_jurisdiction"):
        add_hint(identifiers.get(key))

    website = _clean_identifier_value(identifiers.get("website"))
    if website:
        parsed = urlparse(str(website))
        host = (parsed.netloc or parsed.path or "").lower()
        for country, suffixes in {
            "UK": (".uk", ".co.uk", ".org.uk", ".gov.uk"),
            "CA": (".ca",),
            "AU": (".au",),
            "SG": (".sg",),
            "NZ": (".nz",),
            "FR": (".fr",),
        }.items():
            if any(host.endswith(suffix) for suffix in suffixes):
                hints.add(country)
    return hints


def _connector_relevant_to_case(
    source: str,
    connector: dict[str, Any],
    identifier_status: dict[str, dict[str, Any]],
    country_hints: set[str],
) -> bool:
    if bool(connector.get("has_data")):
        return True

    source_key = str(source or "")
    identifier_hints = _CONNECTOR_IDENTIFIER_HINTS.get(source_key, ())
    for field in identifier_hints:
        item = identifier_status.get(field)
        if isinstance(item, dict) and _clean_identifier_value(item.get("value")) not in (None, ""):
            return True

    country_expectations = _CONNECTOR_COUNTRY_HINTS.get(source_key, set())
    if country_expectations and country_hints.intersection(country_expectations):
        return True

    website_item = identifier_status.get("website")
    website_value = _clean_identifier_value(website_item.get("value")) if isinstance(website_item, dict) else None
    if website_value:
        parsed = urlparse(str(website_value))
        host = (parsed.netloc or parsed.path or "").lower()
        if any(host.endswith(suffix) for suffix in _CONNECTOR_DOMAIN_HINTS.get(source_key, ())):
            return True

    return False


def _official_corroboration_summary(
    identifier_status: dict[str, dict[str, Any]],
    enrichment: dict[str, Any] | None,
    vendor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    connectors = _official_connector_snapshot(enrichment)
    identifiers = {
        key: item.get("value")
        for key, item in identifier_status.items()
        if isinstance(item, dict)
    }
    country_hints = _country_hints_from_vendor(vendor, identifiers)
    relevant_connectors = [
        connector
        for connector in connectors
        if _connector_relevant_to_case(str(connector.get("source") or ""), connector, identifier_status, country_hints)
    ]
    blocked_connectors = [
        connector
        for connector in relevant_connectors
        if connector.get("throttled") or connector.get("error")
    ]
    gated_connectors = [
        connector
        for connector in relevant_connectors
        if str(connector.get("source") or "") in _GATED_OFFICIAL_CONNECTOR_SOURCES
        or "gated" in str(connector.get("access_model") or "").lower()
    ]

    official_verified_fields: list[str] = []
    public_capture_fields: list[str] = []
    unverified_official_fields: list[str] = []

    for key, item in identifier_status.items():
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "missing").lower()
        value = _clean_identifier_value(item.get("value"))
        authority_level = str(item.get("authority_level") or "")
        verification_tier = str(item.get("verification_tier") or "").lower()

        if value not in (None, ""):
            if state == "verified_present" and _is_official_authority(authority_level):
                official_verified_fields.append(str(key))
            elif verification_tier in {"publicly_captured", "publicly_disclosed"}:
                public_capture_fields.append(str(key))
        elif state == "unverified" and _is_official_authority(authority_level):
            unverified_official_fields.append(str(key))

    core_official_fields_verified = [
        key
        for key in official_verified_fields
        if key in _OFFICIAL_IDENTITY_FIELDS
    ]

    if len(official_verified_fields) >= 2:
        coverage_level = "strong"
        coverage_label = "Strong official corroboration"
    elif len(official_verified_fields) == 1:
        coverage_level = "partial"
        coverage_label = "Partial official corroboration"
    elif public_capture_fields or blocked_connectors or connectors:
        coverage_level = "public_only"
        coverage_label = "Public capture without official corroboration"
    else:
        coverage_level = "missing"
        coverage_label = "No official corroboration captured"

    return {
        "coverage_level": coverage_level,
        "coverage_label": coverage_label,
        "official_connector_count": len(connectors),
        "relevant_official_connector_count": len(relevant_connectors),
        "official_connectors_with_data": sum(1 for connector in connectors if connector.get("has_data")),
        "relevant_official_connectors_with_data": sum(1 for connector in relevant_connectors if connector.get("has_data")),
        "official_identifier_count": len(official_verified_fields),
        "official_identifiers_verified": official_verified_fields,
        "core_official_identifier_count": len(core_official_fields_verified),
        "core_official_identifiers_verified": core_official_fields_verified,
        "public_capture_fields": public_capture_fields,
        "unverified_official_fields": unverified_official_fields,
        "blocked_connector_count": len(blocked_connectors),
        "blocked_connectors": blocked_connectors,
        "gated_connector_count": len(gated_connectors),
        "gated_connectors": gated_connectors,
        "relevant_connectors": relevant_connectors,
        "connectors": connectors,
        "country_hints": sorted(country_hints),
        "core_official_fields": list(_OFFICIAL_IDENTITY_FIELDS),
    }


def _identifier_statuses(
    identifiers: dict[str, Any],
    enrichment: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    connector_status = (
        enrichment.get("connector_status")
        if isinstance(enrichment, dict) and isinstance(enrichment.get("connector_status"), dict)
        else {}
    )
    identifier_sources = (
        enrichment.get("identifier_sources")
        if isinstance(enrichment, dict) and isinstance(enrichment.get("identifier_sources"), dict)
        else {}
    )
    statuses: dict[str, dict[str, Any]] = {}
    ordered_keys = list(
        dict.fromkeys(
            [
                *[key for key in _IDENTIFIER_DISPLAY_ORDER if key in identifiers or key in _TRACKED_IDENTIFIER_SOURCES],
                *identifiers.keys(),
                *_TRACKED_IDENTIFIER_SOURCES.keys(),
            ]
        )
    )

    for key in ordered_keys:
        cleaned = _clean_identifier_value(identifiers.get(key))
        known_sources = [
            str(source)
            for source in (identifier_sources.get(key) or [])
            if isinstance(source, str) and source.strip()
        ]
        fallback_source = _TRACKED_IDENTIFIER_SOURCES.get(key)
        source = _preferred_identifier_source(known_sources, connector_status) if known_sources else fallback_source
        status = _connector_status_with_defaults(source, connector_status) if source else None
        payload: dict[str, Any] = {
            "state": "missing",
            "source": source,
            "sources": known_sources or ([fallback_source] if fallback_source else []),
            "value": cleaned,
            "reason": None,
            "next_access_time": None,
            "authority_level": str(status.get("authority_level") or "") if isinstance(status, dict) else None,
            "access_model": str(status.get("access_model") or "") if isinstance(status, dict) else None,
        }

        if cleaned is not None:
            payload["state"] = "verified_present"
        elif isinstance(status, dict):
            error_text = str(status.get("error") or "").strip()
            if source == "sam_gov":
                structured = status.get("structured_fields") if isinstance(status.get("structured_fields"), dict) else {}
                sam_api_status = structured.get("sam_api_status") if isinstance(structured.get("sam_api_status"), dict) else {}
                throttled = any(
                    isinstance(lookup, dict) and bool(lookup.get("throttled"))
                    for lookup in sam_api_status.values()
                )
                if throttled:
                    payload["state"] = "unverified"
                    payload["reason"] = error_text or "SAM.gov lookup throttled."
                    payload["next_access_time"] = _pick_next_access_time(status)
                elif error_text:
                    payload["state"] = "unverified"
                    payload["reason"] = error_text
                else:
                    payload["state"] = "verified_absent"
            else:
                if error_text:
                    payload["state"] = "unverified"
                    payload["reason"] = error_text
                else:
                    payload["state"] = "verified_absent"

        if payload["state"] != "missing" or cleaned is not None:
            display_tier, display_label = _identifier_display_semantics(
                str(payload.get("state") or "missing"),
                str(payload.get("authority_level") or ""),
            )
            payload["verification_tier"] = display_tier
            payload["verification_label"] = display_label
            statuses[key] = payload

    return statuses


def _identifier_display_semantics(state: str, authority_level: str) -> tuple[str, str]:
    normalized_state = str(state or "missing").lower()
    normalized_authority = str(authority_level or "").lower()

    if normalized_state == "verified_present":
        if normalized_authority == "first_party_self_disclosed":
            return "publicly_disclosed", "Publicly disclosed"
        if normalized_authority in {"third_party_public", "public_registry_aggregator"}:
            return "publicly_captured", "Publicly captured"
        return "verified", "Verified"
    if normalized_state == "verified_absent":
        return "verified_absent", "Verified absent"
    if normalized_state == "unverified":
        return "unverified", "Unverified"
    return "missing", "Missing"


def _monitoring_summary(case_id: str) -> dict:
    history = db.get_monitoring_history(case_id, limit=3)
    latest = history[0] if history else None
    return {
        "check_count": len(history),
        "latest_check": latest,
    }


def _network_risk_summary(case_id: str) -> dict | None:
    if not callable(compute_network_risk):
        return None
    try:
        risk = compute_network_risk(case_id)
    except Exception:
        return None
    return {
        "score": risk.get("network_risk_score", 0.0),
        "level": risk.get("network_risk_level", "none"),
        "neighbor_count": risk.get("neighbor_count", 0),
        "high_risk_neighbors": risk.get("high_risk_neighbors", 0),
        "top_contributors": (risk.get("risk_contributors") or [])[:3],
    }


def _resolved_ownership_profile(vendor_input: dict, score: dict | None) -> dict:
    raw_profile = vendor_input.get("ownership", {}) if isinstance(vendor_input.get("ownership"), dict) else {}
    scored_profile = (score or {}).get("ownership", {}) if isinstance((score or {}).get("ownership"), dict) else {}
    if not scored_profile:
        return dict(raw_profile)
    return {
        **raw_profile,
        **scored_profile,
    }


def _ownership_analyst_readout(oci: dict | None) -> str:
    data = oci if isinstance(oci, dict) else {}
    if not data:
        return "Ownership / control evidence not yet resolved."
    if data.get("named_beneficial_owner_known"):
        owner = str(data.get("named_beneficial_owner") or "named beneficial owner").strip()
        return f"Named beneficial owner resolved: {owner}."
    if data.get("descriptor_only"):
        owner_class = str(data.get("owner_class") or "owner class").strip()
        return f"Descriptor-only ownership evidence. No named beneficial owner resolved. Owner class: {owner_class}."
    if data.get("controlling_parent_known"):
        parent = str(data.get("controlling_parent") or "controlling parent").strip()
        return f"Controlling parent resolved: {parent}. Named beneficial owner still unknown."
    return "Named beneficial owner not resolved from current evidence."


def build_supplier_passport(
    case_id: str,
    *,
    mode: str = "full",
    vendor: dict | None = None,
    score: dict | None = None,
    latest_decision: dict | None = None,
    enrichment: dict | None = None,
    foci_summary: dict | None = None,
    cyber_summary: dict | None = None,
    export_summary: dict | None = None,
    graph_summary: dict | None = None,
) -> dict | None:
    passport_mode = _normalized_passport_mode(mode)
    mode_settings = _passport_mode_settings(passport_mode)
    vendor = vendor or db.get_vendor(case_id)
    if not vendor:
        return None

    vendor_input = vendor.get("vendor_input", {}) if isinstance(vendor.get("vendor_input"), dict) else {}
    score = score if score is not None else db.get_latest_score(case_id)
    latest_decision = latest_decision if latest_decision is not None else db.get_latest_decision(case_id)
    enrichment = enrichment if enrichment is not None else db.get_latest_enrichment(case_id)
    export_input = vendor_input.get("export_authorization") if isinstance(vendor_input.get("export_authorization"), dict) else None

    foci_summary = (
        foci_summary
        if foci_summary is not None
        else get_latest_foci_summary(case_id) if callable(get_latest_foci_summary) else None
    )
    cyber_summary = (
        cyber_summary
        if cyber_summary is not None
        else get_latest_cyber_evidence_summary(case_id) if callable(get_latest_cyber_evidence_summary) else None
    )
    export_summary = (
        export_summary
        if export_summary is not None
        else get_export_evidence_summary(case_id, export_input) if callable(get_export_evidence_summary) and export_input else None
    )
    workflow_lane = _workflow_lane(vendor, cyber_summary=cyber_summary, export_summary=export_summary)
    oci_adjudicator_key = get_oci_adjudicator_cache_key()

    cache_key = _supplier_passport_cache_key(
        case_id,
        passport_mode,
        vendor,
        score,
        latest_decision,
        enrichment,
        foci_summary,
        cyber_summary,
        export_summary,
        oci_adjudicator_key,
    )
    cached = _get_cached_supplier_passport(cache_key)
    if cached is not None:
        return cached

    workflow_control = (
        build_workflow_control_summary(
            vendor,
            foci_summary=foci_summary,
            cyber_summary=cyber_summary,
            export_summary=export_summary,
        )
        if mode_settings["include_workflow_control"] and callable(build_workflow_control_summary)
        else None
    )

    graph_summary = (
        graph_summary
        if graph_summary is not None
        else get_vendor_graph_summary(
            case_id,
            depth=mode_settings["graph_depth"],
            include_provenance=mode_settings["include_provenance"],
            max_claim_records=mode_settings["max_claim_records"],
            max_evidence_records=mode_settings["max_evidence_records"],
        )
        if callable(get_vendor_graph_summary)
        else None
    )
    if isinstance(graph_summary, dict) and graph_summary.get("error"):
        graph_summary = None
    network_risk = _network_risk_summary(case_id) if mode_settings["include_network_risk"] else None

    identifiers = {}
    if isinstance(enrichment, dict):
        identifiers = enrichment.get("identifiers") or {}
    identifier_status = _identifier_statuses(identifiers, enrichment)
    official_corroboration = _official_corroboration_summary(identifier_status, enrichment, vendor=vendor)
    threat_intel_summary = (
        build_threat_intel_summary(enrichment)
        if HAS_THREAT_INTEL and callable(build_threat_intel_summary)
        else None
    )

    summary = ((enrichment or {}).get("summary") or {}) if isinstance(enrichment, dict) else {}
    calibrated = (score or {}).get("calibrated") or {}
    control_graph_summary = _control_relationship_graph(graph_summary)
    control_paths = _top_control_paths(control_graph_summary)
    claim_health = _graph_claim_health(control_graph_summary)
    control_entities = control_graph_summary.get("entities") or []
    control_relationships = control_graph_summary.get("relationships") or []
    ownership_profile = _resolved_ownership_profile(vendor_input, score)
    ownership_oci_summary = build_oci_summary(
        ownership_profile,
        (enrichment or {}).get("findings") if isinstance(enrichment, dict) else [],
        (enrichment or {}).get("relationships") if isinstance(enrichment, dict) else [],
    )
    identity = {
        "identifiers": identifiers,
        "identifier_status": identifier_status,
        "official_corroboration": official_corroboration,
        "connectors_run": summary.get("connectors_run", 0),
        "connectors_with_data": summary.get("connectors_with_data", 0),
        "findings_total": summary.get("findings_total", 0),
        "overall_risk": (enrichment or {}).get("overall_risk"),
        "enriched_at": (enrichment or {}).get("enriched_at"),
    }

    posture = _passport_posture(score, latest_decision=latest_decision)
    graph_intelligence = (
        build_graph_intelligence_summary(graph_summary, workflow_lane=workflow_lane)
        if callable(build_graph_intelligence_summary)
        else ((graph_summary or {}).get("intelligence") if isinstance(graph_summary, dict) else None)
    )
    passport = {
        "passport_version": "supplier-passport-v1",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "case_id": case_id,
        "workflow_lane": workflow_lane,
        "posture": posture,
        "vendor": {
            "id": vendor["id"],
            "name": vendor["name"],
            "country": vendor.get("country", ""),
            "profile": vendor.get("profile", "defense_acquisition"),
            "program": vendor.get("program", ""),
            "program_label": _program_label(vendor.get("program", "")),
        },
        "score": {
            "composite_score": (score or {}).get("composite_score"),
            "calibrated_probability": calibrated.get("calibrated_probability"),
            "calibrated_tier": calibrated.get("calibrated_tier"),
            "program_recommendation": calibrated.get("program_recommendation"),
            "is_hard_stop": (score or {}).get("is_hard_stop", False),
            "scored_at": (score or {}).get("scored_at"),
        },
        "decision": latest_decision,
        "identity": identity,
        "ownership": {
            "profile": ownership_profile,
            "oci": ownership_oci_summary,
            "analyst_readout": _ownership_analyst_readout(ownership_oci_summary),
            "foci_summary": foci_summary,
            "workflow_control": workflow_control,
        },
        "export": export_summary,
        "cyber": cyber_summary,
        "threat_intel": threat_intel_summary,
        "graph": {
            "entity_count": len(control_entities),
            "relationship_count": len(control_relationships),
            "network_entity_count": (graph_summary or {}).get("entity_count", 0),
            "network_relationship_count": (graph_summary or {}).get("relationship_count", 0),
            "entity_type_distribution": (graph_summary or {}).get("entity_type_distribution", {}),
            "relationship_type_distribution": (graph_summary or {}).get("relationship_type_distribution", {}),
            "control_paths": control_paths,
            "claim_health": claim_health,
            "intelligence": graph_intelligence or {},
        },
        "network_risk": network_risk,
        "monitoring": _monitoring_summary(case_id),
        "artifacts": _artifact_snapshot(case_id),
        "tribunal": build_decision_tribunal(
            posture=posture,
            score={**(score or {}), "profile": vendor.get("profile", "defense_acquisition")},
            latest_decision=latest_decision,
            workflow_control=workflow_control,
            network_risk=network_risk,
            control_paths=control_paths,
            claim_health=claim_health,
            foci_summary=foci_summary,
            cyber_summary=cyber_summary,
            export_summary=export_summary,
            identity=identity,
            workflow_lane=workflow_lane,
            ownership_profile=ownership_profile,
            ownership_summary=ownership_oci_summary,
            graph_intelligence=graph_intelligence,
        ) if mode_settings["include_tribunal"] else {
            "recommended_view": None,
            "recommended_label": "Skipped",
            "consensus_level": "skipped",
            "decision_gap": 0.0,
            "views": [],
        },
    }
    _store_cached_supplier_passport(cache_key, passport)
    return passport
