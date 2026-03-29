"""Ownership / Control / Influence helper logic for Helios."""

from __future__ import annotations

import re
from typing import Any


OCI_SCHEMA_VERSION = "oci-v1"
OCI_ADJUDICATOR_VERSION = "oci-adjudicator-v1"

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
        structured = finding.get("structured_fields") if isinstance(finding.get("structured_fields"), dict) else {}
        descriptor = normalize_owner_class(structured.get("ownership_descriptor") or finding.get("detail") or "")
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
                "title": str(finding.get("title") or ""),
                "detail": str(finding.get("detail") or ""),
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
            "source": str(rel.get("data_source") or ""),
            "authority_level": str(rel.get("authority_level") or ""),
            "access_model": str(rel.get("access_model") or ""),
            "confidence": float(rel.get("confidence") or 0.0),
            "artifact_ref": str(rel.get("artifact_ref") or rel.get("evidence_url") or ""),
            "evidence": str(rel.get("evidence") or ""),
        }
        if rel_type in _OWNERSHIP_REL_TYPES:
            if relationship_supports_named_owner_resolution(rel):
                named_owners.append(row)
                if rel_type in {"beneficially_owned_by", "ultimate_parent", "parent_of"}:
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


def build_oci_summary(
    ownership_profile: dict[str, Any] | None,
    findings: list[dict[str, Any]] | None,
    relationships: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    profile = ownership_profile if isinstance(ownership_profile, dict) else {}
    classified = classify_ownership_relationships(relationships)
    owner_class_evidence = extract_owner_class_evidence(findings)
    owner_class = owner_class_evidence[0]["descriptor"] if owner_class_evidence else None

    profile_named_owner_known = bool(
        profile.get("named_beneficial_owner_known", profile.get("beneficial_owner_known", False))
    )
    named_owner_known = bool(profile_named_owner_known or classified["named_owners"])
    controlling_parent_known = bool(profile.get("controlling_parent_known") or classified["controlling_parents"])
    owner_class_known = bool(profile.get("owner_class_known") or owner_class)
    named_owner = None
    controlling_parent = None
    if classified["named_owners"]:
        named_owner = classified["named_owners"][0]["target_name"]
    if classified["controlling_parents"]:
        controlling_parent = classified["controlling_parents"][0]["target_name"]

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

    ownership_gap = "named_owner_unknown"
    if named_owner_known:
        ownership_gap = "resolved_named_owner"
    elif owner_class_known:
        ownership_gap = "descriptor_only_owner_class"

    return {
        "schema_version": OCI_SCHEMA_VERSION,
        "adjudicator_version": OCI_ADJUDICATOR_VERSION,
        "adjudicator_mode": "schema_ready_rules",
        "named_beneficial_owner_known": named_owner_known,
        "named_beneficial_owner": named_owner,
        "controlling_parent_known": controlling_parent_known,
        "controlling_parent": controlling_parent,
        "owner_class_known": owner_class_known,
        "owner_class": owner_class or profile.get("owner_class") or None,
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
    }
