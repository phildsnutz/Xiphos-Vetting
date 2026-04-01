#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import db
import knowledge_graph as kg
import mission_threads
from entity_resolution import ResolvedEntity


DEFAULT_FIXTURE_PATH = ROOT_DIR / "fixtures" / "mission_threads" / "contested_sustainment_threads_v1.json"
DEFAULT_CREATED_BY = "fixture-seed"


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def load_fixture_pack(path: str | Path = DEFAULT_FIXTURE_PATH) -> dict[str, Any]:
    fixture_path = Path(path)
    with fixture_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("fixtures"), list):
        raise ValueError(f"Invalid mission-thread fixture pack: {fixture_path}")
    return payload


def list_fixture_headers(path: str | Path = DEFAULT_FIXTURE_PATH) -> list[dict[str, str]]:
    pack = load_fixture_pack(path)
    return [
        {
            "id": _normalize_text(fixture.get("id")),
            "title": _normalize_text(fixture.get("title") or fixture.get("id")),
        }
        for fixture in pack.get("fixtures") or []
        if _normalize_text(fixture.get("id"))
    ]


def get_fixture_by_id(fixture_id: str, *, path: str | Path = DEFAULT_FIXTURE_PATH) -> dict[str, Any]:
    normalized_id = _normalize_text(fixture_id)
    if not normalized_id:
        raise ValueError("fixture_id is required")
    pack = load_fixture_pack(path)
    for fixture in pack.get("fixtures") or []:
        if _normalize_text(fixture.get("id")) == normalized_id:
            return dict(fixture)
    available = ", ".join(header["id"] for header in list_fixture_headers(path))
    raise LookupError(f"Fixture not found: {normalized_id}. Available: {available}")


def _default_vendor_input(vendor: dict[str, Any]) -> dict[str, Any]:
    return {
        "ownership": {
            "publicly_traded": False,
            "state_owned": False,
            "beneficial_owner_known": False,
            "ownership_pct_resolved": 0.5,
            "shell_layers": 0,
            "pep_connection": False,
        },
        "data_quality": {
            "has_lei": bool((vendor.get("identifiers") or {}).get("lei")),
            "has_cage": bool((vendor.get("identifiers") or {}).get("cage")),
            "has_duns": bool((vendor.get("identifiers") or {}).get("duns")),
            "has_tax_id": False,
            "has_audited_financials": True,
            "years_of_records": 5,
        },
        "exec": {
            "known_execs": 3,
            "adverse_media": 0,
            "pep_execs": 0,
            "litigation_history": 0,
        },
    }


def _merge_dicts(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(base)
    if not isinstance(override, dict):
        return result
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def _default_score(vendor: dict[str, Any]) -> dict[str, Any]:
    return {
        "composite_score": 0.35,
        "is_hard_stop": False,
        "ownership": {
            "publicly_traded": False,
            "beneficial_owner_known": False,
        },
        "calibrated": {
            "calibrated_probability": 0.32,
            "calibrated_tier": "medium",
            "display_tier": "medium",
            "program_recommendation": "watch",
            "interval": {
                "lower": 0.25,
                "upper": 0.39,
                "coverage": 0.8,
            },
        },
    }


def _default_enrichment(vendor: dict[str, Any]) -> dict[str, Any]:
    identifiers = dict(vendor.get("identifiers") or {})
    return {
        "vendor_name": _normalize_text(vendor.get("name")),
        "country": _normalize_text(vendor.get("country")),
        "overall_risk": "MODERATE",
        "identifiers": identifiers,
        "summary": {
            "findings_total": 0,
            "critical": 0,
            "high": 0,
            "connectors_run": 1,
            "connectors_with_data": 1,
        },
        "connector_status": {
            "fixture_seed": {
                "status": "with_data",
                "findings": 0,
            }
        },
        "findings": [],
        "relationships": [],
        "total_elapsed_ms": 1,
        "enriched_at": "2026-03-31T00:00:00Z",
    }


def _entity_from_payload(payload: dict[str, Any]) -> ResolvedEntity:
    return ResolvedEntity(
        id=_normalize_text(payload.get("id")),
        canonical_name=_normalize_text(payload.get("canonical_name")),
        entity_type=_normalize_text(payload.get("entity_type") or "unknown"),
        aliases=list(payload.get("aliases") or []),
        identifiers=dict(payload.get("identifiers") or {}),
        country=_normalize_text(payload.get("country")),
        relationships=list(payload.get("relationships") or []),
        sources=list(payload.get("sources") or ["mission_thread_fixture"]),
        confidence=float(payload.get("confidence") or 0.8),
        last_updated=_normalize_text(payload.get("last_updated") or "2026-03-31T00:00:00Z"),
    )


def _seed_vendors(fixture: dict[str, Any]) -> list[str]:
    vendor_ids: list[str] = []
    for vendor in fixture.get("vendors") or []:
        vendor_id = _normalize_text(vendor.get("id"))
        if not vendor_id:
            continue
        vendor_input = _merge_dicts(_default_vendor_input(vendor), dict(vendor.get("vendor_input") or {}))
        db.upsert_vendor(
            vendor_id,
            _normalize_text(vendor.get("name")),
            _normalize_text(vendor.get("country") or "US"),
            _normalize_text(vendor.get("program") or "contested_logistics"),
            vendor_input,
            profile=_normalize_text(vendor.get("profile") or "defense_acquisition"),
        )
        db.save_score(vendor_id, _merge_dicts(_default_score(vendor), dict(vendor.get("score") or {})))
        enrichment = vendor.get("enrichment")
        if isinstance(enrichment, dict):
            db.save_enrichment(vendor_id, _merge_dicts(_default_enrichment(vendor), enrichment))
        vendor_ids.append(vendor_id)
    return vendor_ids


def _seed_entities_and_links(fixture: dict[str, Any]) -> list[str]:
    entity_ids: list[str] = []
    for entity_payload in fixture.get("entities") or []:
        entity = _entity_from_payload(dict(entity_payload))
        kg.save_entity(entity)
        entity_ids.append(entity.id)
    for link in fixture.get("vendor_entity_links") or []:
        vendor_id = _normalize_text(link.get("vendor_id"))
        entity_id = _normalize_text(link.get("entity_id"))
        if vendor_id and entity_id:
            kg.link_entity_to_vendor(entity_id, vendor_id)
    return entity_ids


def _seed_relationships(fixture: dict[str, Any]) -> int:
    count = 0
    for relationship in fixture.get("relationships") or []:
        kg.save_relationship(
            _normalize_text(relationship.get("source_entity_id")),
            _normalize_text(relationship.get("target_entity_id")),
            _normalize_text(relationship.get("rel_type")),
            confidence=float(relationship.get("confidence") or 0.7),
            data_source=_normalize_text(relationship.get("data_source") or "mission_thread_fixture"),
            evidence=_normalize_text(relationship.get("evidence")),
            observed_at=_normalize_text(relationship.get("observed_at")),
            valid_from=_normalize_text(relationship.get("valid_from")),
            valid_to=_normalize_text(relationship.get("valid_to")),
            claim_value=_normalize_text(relationship.get("claim_value")),
            contradiction_state=_normalize_text(relationship.get("contradiction_state") or "unreviewed"),
            artifact_ref=_normalize_text(relationship.get("artifact_ref")),
            evidence_url=_normalize_text(relationship.get("evidence_url")),
            evidence_title=_normalize_text(relationship.get("evidence_title")),
            raw_data=dict(relationship.get("raw_data") or {}),
            structured_fields=dict(relationship.get("structured_fields") or {}),
            source_class=_normalize_text(relationship.get("source_class")),
            authority_level=_normalize_text(relationship.get("authority_level")),
            access_model=_normalize_text(relationship.get("access_model")),
            vendor_id=_normalize_text(relationship.get("vendor_id")),
        )
        count += 1
    return count


def _ensure_thread(thread_payload: dict[str, Any]) -> dict[str, Any]:
    thread_id = _normalize_text(thread_payload.get("id"))
    existing = mission_threads.get_mission_thread(thread_id, include_members=False)
    if existing:
        return existing
    return mission_threads.create_mission_thread(
        thread_id=thread_id,
        name=_normalize_text(thread_payload.get("name")),
        description=_normalize_text(thread_payload.get("description")),
        created_by=_normalize_text(thread_payload.get("created_by") or DEFAULT_CREATED_BY),
        lane=_normalize_text(thread_payload.get("lane")),
        program=_normalize_text(thread_payload.get("program")),
        theater=_normalize_text(thread_payload.get("theater")),
        mission_type=_normalize_text(thread_payload.get("mission_type")),
        status=_normalize_text(thread_payload.get("status") or mission_threads.DEFAULT_THREAD_STATUS),
    )


def _seed_members(thread_id: str, members: list[dict[str, Any]]) -> list[int]:
    member_ids: list[int] = []
    for member in members:
        saved = mission_threads.add_mission_thread_member(
            thread_id,
            vendor_id=_normalize_text(member.get("vendor_id")),
            entity_id=_normalize_text(member.get("entity_id")),
            role=_normalize_text(member.get("role")),
            criticality=_normalize_text(member.get("criticality") or mission_threads.DEFAULT_MEMBER_CRITICALITY),
            subsystem=_normalize_text(member.get("subsystem")),
            site=_normalize_text(member.get("site")),
            is_alternate=bool(member.get("is_alternate")),
            notes=_normalize_text(member.get("notes")),
        )
        member_ids.append(int(saved.get("id") or 0))
    return [member_id for member_id in member_ids if member_id]


def seed_fixture(fixture: dict[str, Any], *, depth: int = 2) -> dict[str, Any]:
    db.init_db()
    kg.init_kg_db()

    fixture_id = _normalize_text(fixture.get("id"))
    thread_payload = dict(fixture.get("thread") or {})
    if not fixture_id or not thread_payload:
        raise ValueError("Fixture must include id and thread payload")

    vendor_ids = _seed_vendors(fixture)
    entity_ids = _seed_entities_and_links(fixture)
    relationship_count = _seed_relationships(fixture)
    thread = _ensure_thread(thread_payload)
    member_ids = _seed_members(_normalize_text(thread.get("id")), list(fixture.get("members") or []))
    summary = mission_threads.build_mission_thread_summary(_normalize_text(thread.get("id")), depth=depth)
    graph = mission_threads.build_mission_thread_graph(_normalize_text(thread.get("id")), depth=depth, include_provenance=False)

    return {
        "fixture_id": fixture_id,
        "title": _normalize_text(fixture.get("title") or fixture_id),
        "thread_id": _normalize_text(thread.get("id")),
        "thread_name": _normalize_text(thread.get("name")),
        "seeded_vendor_ids": vendor_ids,
        "seeded_entity_ids": entity_ids,
        "seeded_member_ids": member_ids,
        "relationship_seed_count": relationship_count,
        "summary": summary,
        "graph": {
            "entity_count": int((graph or {}).get("entity_count") or 0),
            "relationship_count": int((graph or {}).get("relationship_count") or 0),
            "relationship_type_distribution": dict((graph or {}).get("relationship_type_distribution") or {}),
            "resilience_summary": dict((graph or {}).get("resilience_summary") or {}),
        },
    }


def seed_fixture_by_id(
    fixture_id: str,
    *,
    fixture_path: str | Path = DEFAULT_FIXTURE_PATH,
    depth: int = 2,
) -> dict[str, Any]:
    return seed_fixture(get_fixture_by_id(fixture_id, path=fixture_path), depth=depth)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed fixture-backed mission threads into the local Helios databases.")
    parser.add_argument("--fixture-path", default=str(DEFAULT_FIXTURE_PATH), help="Path to the mission-thread fixture pack.")
    parser.add_argument("--fixture-id", help="Fixture id to seed.")
    parser.add_argument("--depth", type=int, default=2, help="Graph depth for the returned summary.")
    parser.add_argument("--list", action="store_true", help="List available fixture ids and exit.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.list:
        headers = list_fixture_headers(args.fixture_path)
        if args.json:
            print(json.dumps(headers, indent=2, sort_keys=True))
        else:
            for header in headers:
                print(f"{header['id']}: {header['title']}")
        return 0

    if not args.fixture_id:
        parser.error("--fixture-id is required unless --list is used")

    result = seed_fixture_by_id(
        args.fixture_id,
        fixture_path=args.fixture_path,
        depth=args.depth,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        summary = result.get("summary") or {}
        graph = result.get("graph") or {}
        print(f"fixture_id: {result['fixture_id']}")
        print(f"thread_id: {result['thread_id']}")
        print(f"thread_name: {result['thread_name']}")
        print(f"member_count: {summary.get('member_count', 0)}")
        print(f"entity_count: {graph.get('entity_count', 0)}")
        print(f"relationship_count: {graph.get('relationship_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
