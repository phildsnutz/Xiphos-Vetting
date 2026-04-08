"""Ownership / Control / Influence helper logic for Helios."""

from __future__ import annotations

import logging
import os
import json
import re
from typing import Any


OCI_SCHEMA_VERSION = "oci-v1"
OCI_ADJUDICATOR_VERSION = "oci-adjudicator-v2"
logger = logging.getLogger(__name__)

_DESCRIPTOR_OWNER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bservice[- ]disabled veteran\b", re.IGNORECASE),
        "Service-Disabled Veteran",
    ),
    (
        re.compile(r"\bveteran[- ]owned\b|\bveteran\b", re.IGNORECASE),
        "Veteran",
    ),
    (
        re.compile(r"\bwoman[- ]owned\b|\bwomen[- ]owned\b|\bwosb\b|\bedwosb\b", re.IGNORECASE),
        "Woman-Owned",
    ),
    (
        re.compile(r"\bminority[- ]owned\b|\bminority\b", re.IGNORECASE),
        "Minority-Owned",
    ),
    (
        re.compile(r"\bfamily[- ]owned\b|\bfamily owned\b", re.IGNORECASE),
        "Family-Owned",
    ),
    (
        re.compile(r"\bemployee[- ]owned\b|\bemployee owned\b", re.IGNORECASE),
        "Employee-Owned",
    ),
    (
        re.compile(r"\bsmall business\b|\bsdvosb\b|\bvosb\b|\bhubzone\b|\b8\(a\)\b|\bsdb\b", re.IGNORECASE),
        "Set-Aside / Small-Business Descriptor",
    ),
)

_GENERIC_OWNER_TARGETS = {
    "",
    "owner",
    "owners",
    "ownership",
    "shareholder",
    "shareholders",
    "investor",
    "investors",
    "holding company",
    "parent company",
    "management team",
    "leadership team",
    "executive management team",
    "the fund",
    "the company",
    "company",
    "fund",
    "portfolio",
    "service-disabled veteran",
    "service disabled veteran",
    "veteran",
    "woman-owned",
    "minority-owned",
    "family-owned",
    "employee-owned",
    "small business",
    "sdvosb",
    "vosb",
    "wosb",
    "edwosb",
    "hubzone",
    "8(a)",
    "sdb",
}

_OWNERSHIP_REL_TYPES = {"owned_by", "beneficially_owned_by", "ultimate_parent", "parent_of"}
_CONTROL_REL_TYPES = _OWNERSHIP_REL_TYPES | {"backed_by", "led_by"}
_ALLOWED_OWNER_CLASSES: tuple[str, ...] = tuple(dict.fromkeys(label for _pattern, label in _DESCRIPTOR_OWNER_PATTERNS))


def _sanitize_ai_fragment(value: object, max_len: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:max_len]


def _oci_ai_enabled() -> bool:
    return os.environ.get("XIPHOS_OCI_AI_ADJUDICATOR", "true").strip().lower() not in {"0", "false", "no", "off"}


def get_oci_adjudicator_cache_key() -> str:
    if not _oci_ai_enabled():
        return f"{OCI_ADJUDICATOR_VERSION}:disabled"
    try:
        from ai_analysis import get_ai_config
    except Exception:
        return f"{OCI_ADJUDICATOR_VERSION}:rules"

    user_id = os.environ.get("XIPHOS_OCI_AI_USER_ID", "__org_default__")
    try:
        config = get_ai_config(user_id)
    except Exception:
        return f"{OCI_ADJUDICATOR_VERSION}:rules"
    if not config:
        return f"{OCI_ADJUDICATOR_VERSION}:rules"
    return ":".join(
        [
            OCI_ADJUDICATOR_VERSION,
            str(user_id or "__org_default__"),
            str(config.get("provider") or "unknown"),
            str(config.get("model") or "unknown"),
        ]
    )


def normalize_owner_class(text: str | None) -> str | None:
    value = str(text or "").strip()
    if not value:
        return None
    lowered = value.lower()
    for pattern, label in _DESCRIPTOR_OWNER_PATTERNS:
        if pattern.search(lowered):
            return label
    return None


def looks_like_descriptor_owner(name: str | None) -> bool:
    text = re.sub(r"\s+", " ", str(name or "").strip().lower())
    if not text:
        return True
    if text in _GENERIC_OWNER_TARGETS:
        return True
    if normalize_owner_class(text):
        return True
    if len(text.split()) <= 4 and any(token in text for token in ("owned", "owner", "shareholder", "investor")):
        if not any(ch.isupper() for ch in str(name or "")):
            return True
    return False


def extract_owner_class_evidence(findings: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings or []:
        source = str(finding.get("source") or "").strip().lower()
        category = str(finding.get("category") or "").strip().lower()
        title = str(finding.get("title") or "")
        detail = str(finding.get("detail") or "")
        structured = finding.get("structured_fields") if isinstance(finding.get("structured_fields"), dict) else {}
        descriptor_text = structured.get("ownership_descriptor")
        if not descriptor_text:
            if source == "sam_gov" and category == "registration":
                descriptor_text = detail
            elif source in {"public_html_ownership", "public_search_ownership"}:
                descriptor_text = detail
            else:
                # Do not let lower-tier supply chain or generic snippet text
                # rewrite the subject vendor's owner class.
                continue
        descriptor = normalize_owner_class(descriptor_text)
        if not descriptor:
            continue
        artifact_ref = str(finding.get("artifact_ref") or finding.get("url") or "")
        key = (descriptor, artifact_ref)
        if key in seen:
            continue
        seen.add(key)
        evidence.append(
            {
                "descriptor": descriptor,
                "source": str(finding.get("source") or ""),
                "authority_level": str(finding.get("authority_level") or ""),
                "access_model": str(finding.get("access_model") or ""),
                "confidence": float(finding.get("confidence") or 0.0),
                "title": title,
                "detail": detail,
                "artifact_ref": artifact_ref,
                "scope": str(structured.get("ownership_descriptor_scope") or ""),
            }
        )
    evidence.sort(key=lambda item: (-float(item.get("confidence") or 0.0), item.get("descriptor") or ""))
    return evidence


def relationship_supports_named_owner_resolution(relationship: dict[str, Any] | None) -> bool:
    rel = relationship if isinstance(relationship, dict) else {}
    rel_type = str(rel.get("type") or "").strip().lower()
    if rel_type not in _OWNERSHIP_REL_TYPES:
        return False

    target_name = str(rel.get("target_entity") or rel.get("parent_name") or rel.get("entity") or "").strip()
    if looks_like_descriptor_owner(target_name):
        return False

    authority_level = str(rel.get("authority_level") or "").strip().lower()
    access_model = str(rel.get("access_model") or "").strip().lower()
    confidence = float(rel.get("confidence") or 0.0)

    if authority_level == "third_party_public":
        return False
    if rel_type in {"beneficially_owned_by", "ultimate_parent"} and authority_level in {
        "official_registry",
        "official_program_system",
        "official_regulatory",
        "standards_modeled_fixture",
        "analyst_curated_fixture",
    }:
        return True
    if not access_model and confidence <= 0.0:
        return True
    if access_model == "search_snippet_only":
        return confidence >= 0.62
    return confidence >= 0.60


def classify_ownership_relationships(relationships: list[dict[str, Any]] | None) -> dict[str, list[dict[str, Any]]]:
    named_owners: list[dict[str, Any]] = []
    controlling_parents: list[dict[str, Any]] = []
    controllers: list[dict[str, Any]] = []
    rejected_descriptors: list[dict[str, Any]] = []
    weak_owner_candidates: list[dict[str, Any]] = []

    for rel in relationships or []:
        rel_type = str(rel.get("type") or "").strip().lower()
        if rel_type not in _CONTROL_REL_TYPES:
            continue
        target_name = str(rel.get("target_entity") or rel.get("parent_name") or rel.get("entity") or "").strip()
        if looks_like_descriptor_owner(target_name):
            rejected_descriptors.append(
                {
                    "rel_type": rel_type,
                    "target_name": target_name,
                    "source": str(rel.get("data_source") or ""),
                    "artifact_ref": str(rel.get("artifact_ref") or rel.get("evidence_url") or ""),
                }
            )
            continue
        row = {
            "rel_type": rel_type,
            "target_name": target_name,
            "target_entity_type": str(rel.get("target_entity_type") or "").strip().lower(),
            "source": str(rel.get("data_source") or ""),
            "authority_level": str(rel.get("authority_level") or ""),
            "access_model": str(rel.get("access_model") or ""),
            "confidence": float(rel.get("confidence") or 0.0),
            "artifact_ref": str(rel.get("artifact_ref") or rel.get("evidence_url") or ""),
            "evidence": str(rel.get("evidence") or ""),
        }
        if rel_type in _OWNERSHIP_REL_TYPES:
            if relationship_supports_named_owner_resolution(rel):
                target_entity_type = str(row.get("target_entity_type") or "")
                if target_entity_type in {"person", "individual", "natural_person"}:
                    named_owners.append(row)
                else:
                    controlling_parents.append(row)
            else:
                weak_owner_candidates.append(row)
        else:
            controllers.append(row)

    return {
        "named_owners": named_owners,
        "controlling_parents": controlling_parents,
        "controllers": controllers,
        "rejected_descriptors": rejected_descriptors,
        "weak_owner_candidates": weak_owner_candidates,
    }


def _should_run_ai_adjudication(
    owner_class_evidence: list[dict[str, Any]],
    classified: dict[str, list[dict[str, Any]]],
) -> bool:
    if not _oci_ai_enabled():
        return False
    if owner_class_evidence and not classified.get("weak_owner_candidates") and not classified.get("rejected_descriptors"):
        return False
    return bool(
        classified.get("weak_owner_candidates")
        or classified.get("controllers")
        or classified.get("controlling_parents")
        or classified.get("rejected_descriptors")
    )


def _sanitize_ai_adjudication_output(
    payload: dict[str, Any] | None,
    classified: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    allowed_candidates = {
        str(row.get("target_name") or "").strip()
        for bucket in ("weak_owner_candidates", "controllers", "controlling_parents")
        for row in classified.get(bucket, [])
        if str(row.get("target_name") or "").strip()
        and not looks_like_descriptor_owner(str(row.get("target_name") or ""))
    }
    weak_owner_candidates = {
        str(row.get("target_name") or "").strip()
        for row in classified.get("weak_owner_candidates", [])
        if str(row.get("target_name") or "").strip()
    }

    owner_class = normalize_owner_class(payload.get("owner_class"))
    should_set_owner_class = bool(payload.get("should_set_owner_class")) and bool(owner_class)

    control_candidate = _sanitize_ai_fragment(payload.get("control_candidate"), max_len=120)
    if not control_candidate or control_candidate not in allowed_candidates:
        control_candidate = None

    dismissed_named_owner_candidates: list[str] = []
    for candidate in payload.get("dismissed_named_owner_candidates") or []:
        normalized = _sanitize_ai_fragment(candidate, max_len=120)
        if normalized and normalized in weak_owner_candidates and normalized not in dismissed_named_owner_candidates:
            dismissed_named_owner_candidates.append(normalized)

    follow_up_queries: list[str] = []
    for candidate in payload.get("follow_up_queries") or []:
        normalized = _sanitize_ai_fragment(candidate, max_len=140)
        if normalized and normalized not in follow_up_queries:
            follow_up_queries.append(normalized)

    confidence = _sanitize_ai_fragment(payload.get("confidence"), max_len=16).lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium" if should_set_owner_class or control_candidate else "low"

    return {
        "owner_class": owner_class,
        "should_set_owner_class": should_set_owner_class,
        "descriptor_only": bool(payload.get("descriptor_only")),
        "control_signal_present": bool(payload.get("control_signal_present")) or bool(control_candidate),
        "control_candidate": control_candidate,
        "dismissed_named_owner_candidates": dismissed_named_owner_candidates[:5],
        "follow_up_queries": follow_up_queries[:5],
        "reason": _sanitize_ai_fragment(payload.get("reason") or payload.get("rationale"), max_len=320),
        "confidence": confidence,
    }


def _build_ai_adjudication_prompt(
    owner_class_evidence: list[dict[str, Any]],
    classified: dict[str, list[dict[str, Any]]],
) -> str:
    payload = {
        "descriptor_evidence": [
            {
                "descriptor": row.get("descriptor"),
                "source": row.get("source"),
                "detail": _sanitize_ai_fragment(row.get("detail"), max_len=220),
                "artifact_ref": row.get("artifact_ref"),
                "scope": row.get("scope"),
            }
            for row in owner_class_evidence[:5]
        ],
        "weak_owner_candidates": [
            {
                "name": row.get("target_name"),
                "authority_level": row.get("authority_level"),
                "access_model": row.get("access_model"),
                "evidence": _sanitize_ai_fragment(row.get("evidence"), max_len=220),
                "artifact_ref": row.get("artifact_ref"),
            }
            for row in classified.get("weak_owner_candidates", [])[:5]
        ],
        "controllers": [
            {
                "name": row.get("target_name"),
                "rel_type": row.get("rel_type"),
                "authority_level": row.get("authority_level"),
                "evidence": _sanitize_ai_fragment(row.get("evidence"), max_len=220),
                "artifact_ref": row.get("artifact_ref"),
            }
            for row in classified.get("controllers", [])[:5]
        ],
        "controlling_parents": [
            {
                "name": row.get("target_name"),
                "rel_type": row.get("rel_type"),
                "authority_level": row.get("authority_level"),
                "evidence": _sanitize_ai_fragment(row.get("evidence"), max_len=220),
                "artifact_ref": row.get("artifact_ref"),
            }
            for row in classified.get("controlling_parents", [])[:5]
        ],
        "rejected_descriptor_relationships": classified.get("rejected_descriptors", [])[:5],
        "allowed_owner_classes": list(_ALLOWED_OWNER_CLASSES),
    }
    return (
        "You are adjudicating beneficial ownership / control evidence for a national-security diligence system.\n"
        "You are NOT allowed to invent a named beneficial owner.\n"
        "You may only do three things:\n"
        "1. decide whether the evidence supports an owner class descriptor,\n"
        "2. decide whether there is a meaningful control signal worth surfacing,\n"
        "3. dismiss weak named-owner candidates that should not be treated as ownership truth.\n\n"
        "Hard rules:\n"
        "- Never output a named beneficial owner.\n"
        "- Only use one of the provided allowed owner classes or null.\n"
        "- control_candidate must be one of the provided candidate names or null.\n"
        "- If the evidence is descriptor-only, set descriptor_only=true.\n"
        "- If evidence is too weak, leave owner_class null and should_set_owner_class=false.\n\n"
        "Return valid JSON with exactly these keys:\n"
        "{\n"
        '  "owner_class": string|null,\n'
        '  "should_set_owner_class": boolean,\n'
        '  "descriptor_only": boolean,\n'
        '  "control_signal_present": boolean,\n'
        '  "control_candidate": string|null,\n'
        '  "dismissed_named_owner_candidates": string[],\n'
        '  "follow_up_queries": string[],\n'
        '  "confidence": "low"|"medium"|"high",\n'
        '  "reason": string\n'
        "}\n\n"
        f"Evidence payload:\n{json.dumps(payload, sort_keys=True)}"
    )


def _run_ai_adjudication(
    owner_class_evidence: list[dict[str, Any]],
    classified: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    if not _should_run_ai_adjudication(owner_class_evidence, classified):
        return None

    try:
        from ai_analysis import PROVIDER_CALLERS, _parse_analysis_json, get_ai_config
    except Exception:
        return None

    user_id = os.environ.get("XIPHOS_OCI_AI_USER_ID", "__org_default__")
    try:
        config = get_ai_config(user_id)
    except Exception:
        return None
    if not config:
        return None

    provider = str(config.get("provider") or "")
    model = str(config.get("model") or "")
    api_key = str(config.get("api_key") or "")
    caller = PROVIDER_CALLERS.get(provider)
    if not caller or not api_key:
        return None

    try:
        response = caller(api_key, model, _build_ai_adjudication_prompt(owner_class_evidence, classified))
        parsed = _parse_analysis_json(str(response.get("text") or ""))
        sanitized = _sanitize_ai_adjudication_output(parsed, classified)
    except Exception as exc:
        logger.warning("OCI AI adjudication failed: %s", exc)
        return None
    if not sanitized:
        return None
    return {
        **sanitized,
        "provider": provider,
        "model": model,
    }


def build_oci_summary(
    ownership_profile: dict[str, Any] | None,
    findings: list[dict[str, Any]] | None,
    relationships: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    profile = ownership_profile if isinstance(ownership_profile, dict) else {}
    classified = classify_ownership_relationships(relationships)
    owner_class_evidence = extract_owner_class_evidence(findings)
    profile_owner_class = normalize_owner_class(profile.get("owner_class"))
    owner_class = owner_class_evidence[0]["descriptor"] if owner_class_evidence else profile_owner_class
    ai_adjudication = _run_ai_adjudication(owner_class_evidence, classified)

    profile_named_owner = None
    for key in ("named_beneficial_owner", "beneficial_owner_name"):
        candidate = str(profile.get(key) or "").strip()
        if candidate and not looks_like_descriptor_owner(candidate):
            profile_named_owner = candidate
            break

    profile_controlling_parent = None
    for key in ("controlling_parent", "parent_company_name", "ultimate_parent_name"):
        candidate = str(profile.get(key) or "").strip()
        if candidate and not looks_like_descriptor_owner(candidate):
            profile_controlling_parent = candidate
            break

    named_owner = classified["named_owners"][0]["target_name"] if classified["named_owners"] else profile_named_owner
    controlling_parent = (
        classified["controlling_parents"][0]["target_name"]
        if classified["controlling_parents"]
        else profile_controlling_parent
    )
    named_owner_known = bool(named_owner)
    controlling_parent_known = bool(controlling_parent)
    if ai_adjudication and ai_adjudication.get("should_set_owner_class") and not owner_class:
        owner_class = str(ai_adjudication.get("owner_class") or "").strip() or None
    owner_class_known = bool(owner_class)

    ownership_resolution_pct = float(
        profile.get("ownership_resolution_pct")
        or profile.get("ownership_pct_resolved")
        or 0.0
    )
    control_resolution_pct = float(profile.get("control_resolution_pct") or 0.0)
    if named_owner_known and ownership_resolution_pct < 0.65:
        ownership_resolution_pct = 0.65
    if owner_class_known and ownership_resolution_pct < 0.55:
        ownership_resolution_pct = 0.55
    if controlling_parent_known and control_resolution_pct < 0.65:
        control_resolution_pct = 0.65
    if named_owner_known and control_resolution_pct < 0.65:
        control_resolution_pct = 0.65
    if owner_class_known and control_resolution_pct < 0.35:
        control_resolution_pct = 0.35
    if owner_class_known and not named_owner_known and not controlling_parent_known:
        ownership_resolution_pct = 0.55
        control_resolution_pct = 0.35
    if not named_owner_known and not owner_class_known and not controlling_parent_known:
        if classified["weak_owner_candidates"] or classified["controllers"]:
            ownership_resolution_pct = min(ownership_resolution_pct, 0.45)
            control_resolution_pct = min(control_resolution_pct, 0.35)
        else:
            ownership_resolution_pct = 0.0
            control_resolution_pct = 0.0

    ownership_gap = "named_owner_unknown"
    if named_owner_known:
        ownership_gap = "resolved_named_owner"
    elif controlling_parent_known:
        ownership_gap = "controlling_parent_only"
    elif owner_class_known:
        ownership_gap = "descriptor_only_owner_class"

    return {
        "schema_version": OCI_SCHEMA_VERSION,
        "adjudicator_version": OCI_ADJUDICATOR_VERSION,
        "adjudicator_mode": "rules_plus_ai" if ai_adjudication else "schema_ready_rules",
        "named_beneficial_owner_known": named_owner_known,
        "named_beneficial_owner": named_owner,
        "controlling_parent_known": controlling_parent_known,
        "controlling_parent": controlling_parent,
        "owner_class_known": owner_class_known,
        "owner_class": owner_class or None,
        "ownership_resolution_pct": ownership_resolution_pct,
        "control_resolution_pct": control_resolution_pct,
        "ownership_gap": ownership_gap,
        "descriptor_only": bool(owner_class_known and not named_owner_known),
        "named_owner_candidates": classified["named_owners"][:5],
        "weak_owner_candidates": classified["weak_owner_candidates"][:5],
        "controller_candidates": classified["controllers"][:5],
        "controlling_parent_candidates": classified["controlling_parents"][:5],
        "owner_class_evidence": owner_class_evidence[:5],
        "rejected_descriptor_relationships": classified["rejected_descriptors"][:5],
        "ai_adjudication": ai_adjudication,
    }
