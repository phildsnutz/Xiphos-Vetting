"""Helpers for summarizing customer-provided cyber-trust artifacts."""

from __future__ import annotations

from typing import Any

import db

try:
    from artifact_vault import list_case_artifacts
    HAS_ARTIFACT_VAULT = True
except ImportError:
    HAS_ARTIFACT_VAULT = False

try:
    from threat_intel_substrate import build_threat_intel_summary
    HAS_THREAT_INTEL = True
except ImportError:
    build_threat_intel_summary = None
    HAS_THREAT_INTEL = False


def _latest_artifact(case_id: str, source_system: str) -> dict | None:
    if not HAS_ARTIFACT_VAULT:
        return None
    for record in list_case_artifacts(case_id, limit=30):
        if record.get("source_system") == source_system:
            return record
    return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "on"}
    return default


def _latest_public_assurance_summary(case_id: str) -> dict | None:
    report = db.get_latest_enrichment(case_id)
    if not isinstance(report, dict):
        return None

    connector_status = report.get("connector_status") or {}
    connector_entry = connector_status.get("public_assurance_evidence_fixture") or {}
    structured_fields = connector_entry.get("structured_fields") or {}
    summary = structured_fields.get("summary") if isinstance(structured_fields.get("summary"), dict) else {}
    if not isinstance(summary, dict) or not summary:
        return None

    artifact_urls = [
        str(url)
        for url in (summary.get("artifact_urls") or [])
        if isinstance(url, str) and url.strip()
    ]
    artifact_kinds = [
        str(kind)
        for kind in (summary.get("artifact_kinds") or [])
        if isinstance(kind, str) and kind.strip()
    ]

    if not (
        _safe_bool(summary.get("public_evidence_present"))
        or _safe_bool(summary.get("sbom_present"))
        or _safe_bool(summary.get("security_txt_present"))
        or _safe_bool(summary.get("psirt_contact_present"))
        or _safe_bool(summary.get("support_lifecycle_published"))
        or _safe_bool(summary.get("provenance_attested"))
        or artifact_kinds
        or artifact_urls
    ):
        return None

    sbom_fresh_days = summary.get("sbom_fresh_days")
    try:
        sbom_fresh_days = int(sbom_fresh_days) if sbom_fresh_days is not None else None
    except (TypeError, ValueError):
        sbom_fresh_days = None

    evidence_sources: list[str] = []
    if _safe_bool(summary.get("sbom_present")):
        evidence_sources.append("public_sbom")
    if str(summary.get("vex_status") or "").strip().lower() not in {"", "missing", "unknown", "none"}:
        evidence_sources.append("public_vex")
    if _safe_bool(summary.get("security_txt_present")):
        evidence_sources.append("public_security_txt")
    if _safe_bool(summary.get("psirt_contact_present")):
        evidence_sources.append("public_psirt")
    if _safe_bool(summary.get("support_lifecycle_published")):
        evidence_sources.append("public_support_lifecycle")
    if _safe_bool(summary.get("provenance_attested")):
        evidence_sources.append("public_provenance")
    if str(summary.get("secure_by_design_evidence") or "").strip().lower() not in {"", "none"}:
        evidence_sources.append("public_secure_by_design")

    return {
        "public_evidence_present": True,
        "public_evidence_quality": str(summary.get("evidence_quality") or ""),
        "public_artifact_count": _safe_int(summary.get("public_artifact_count") or len(artifact_urls), len(artifact_urls)),
        "public_artifact_urls": artifact_urls,
        "public_artifact_kinds": artifact_kinds,
        "sbom_present": _safe_bool(summary.get("sbom_present")),
        "sbom_format": str(summary.get("sbom_format") or ""),
        "sbom_fresh_days": sbom_fresh_days,
        "vex_status": str(summary.get("vex_status") or ""),
        "security_txt_present": _safe_bool(summary.get("security_txt_present")),
        "psirt_contact_present": _safe_bool(summary.get("psirt_contact_present")),
        "support_lifecycle_published": _safe_bool(summary.get("support_lifecycle_published")),
        "support_lifecycle_status": str(summary.get("support_lifecycle_status") or ""),
        "provenance_attested": _safe_bool(summary.get("provenance_attested")),
        "secure_by_design_evidence": str(summary.get("secure_by_design_evidence") or ""),
        "public_artifact_sources": evidence_sources,
    }


def _connector_summary(report: dict | None, connector_name: str) -> dict:
    if not isinstance(report, dict):
        return {}
    connector_status = report.get("connector_status")
    if not isinstance(connector_status, dict):
        return {}
    connector_entry = connector_status.get(connector_name)
    if not isinstance(connector_entry, dict):
        return {}
    structured_fields = connector_entry.get("structured_fields")
    if not isinstance(structured_fields, dict):
        return {}
    summary = structured_fields.get("summary")
    return dict(summary) if isinstance(summary, dict) else {}


def _latest_open_source_assurance_summary(report: dict | None) -> dict | None:
    osv = _connector_summary(report, "osv_dev")
    deps = _connector_summary(report, "deps_dev")
    scorecard = _connector_summary(report, "openssf_scorecard")
    if not any((osv, deps, scorecard)):
        return None

    advisory_ids: list[str] = []
    for value in list(osv.get("osv_advisory_ids") or []) + list(deps.get("deps_dev_advisory_ids") or []):
        text = str(value or "").strip()
        if text and text not in advisory_ids:
            advisory_ids.append(text)

    vulnerable_packages: list[str] = []
    for value in list(osv.get("osv_vulnerable_packages") or []) + list(deps.get("deps_dev_packages_with_advisories") or []):
        text = str(value or "").strip()
        if text and text not in vulnerable_packages:
            vulnerable_packages.append(text)

    repository_urls: list[str] = []
    for value in list(deps.get("deps_dev_related_repositories") or []):
        text = str(value or "").strip()
        if text and text not in repository_urls:
            repository_urls.append(text)

    repo_scores = []
    for item in scorecard.get("scorecard_repo_scores") or []:
        if isinstance(item, dict):
            repo_scores.append(dict(item))

    package_inventory_count = max(
        _safe_int(osv.get("package_inventory_count")),
        _safe_int(deps.get("package_inventory_count")),
    )
    osv_vulnerability_count = _safe_int(osv.get("osv_vulnerability_count"))
    deps_advisory_count = _safe_int(deps.get("deps_dev_advisory_count"))
    low_repo_count = _safe_int(scorecard.get("scorecard_low_repo_count"))
    scorecard_average = scorecard.get("scorecard_average")
    try:
        scorecard_average = float(scorecard_average) if scorecard_average is not None else None
    except (TypeError, ValueError):
        scorecard_average = None

    open_source_risk_level = "low"
    if osv_vulnerability_count >= 3 or deps_advisory_count >= 3 or low_repo_count > 0:
        open_source_risk_level = "high"
    elif osv_vulnerability_count > 0 or deps_advisory_count > 0 or package_inventory_count > 0:
        open_source_risk_level = "medium"

    return {
        "package_inventory_present": bool(package_inventory_count),
        "package_inventory_count": package_inventory_count,
        "osv_vulnerability_count": osv_vulnerability_count,
        "open_source_advisory_count": len(advisory_ids),
        "open_source_advisory_ids": advisory_ids,
        "open_source_vulnerable_packages": vulnerable_packages,
        "deps_dev_related_repositories": repository_urls,
        "deps_dev_verified_attestations": _safe_int(deps.get("deps_dev_verified_attestations")),
        "deps_dev_verified_slsa_provenances": _safe_int(deps.get("deps_dev_verified_slsa_provenances")),
        "scorecard_average": scorecard_average,
        "scorecard_low_repo_count": low_repo_count,
        "scorecard_repo_scores": repo_scores,
        "open_source_risk_level": open_source_risk_level,
        "open_source_sources": [
            source
            for source, summary in (
                ("osv_dev", osv),
                ("deps_dev", deps),
                ("openssf_scorecard", scorecard),
            )
            if summary
        ],
    }


def get_latest_cyber_evidence_summary(case_id: str) -> dict | None:
    sprs = _latest_artifact(case_id, "sprs_import")
    oscal = _latest_artifact(case_id, "oscal_upload")
    nvd = _latest_artifact(case_id, "nvd_overlay")
    public_assurance = _latest_public_assurance_summary(case_id)
    latest_enrichment = db.get_latest_enrichment(case_id)
    open_source_assurance = _latest_open_source_assurance_summary(latest_enrichment)
    threat_intel = (
        build_threat_intel_summary(latest_enrichment)
        if HAS_THREAT_INTEL and callable(build_threat_intel_summary)
        else None
    )

    sprs_summary = ((sprs or {}).get("structured_fields") or {}).get("summary") or {}
    oscal_summary = ((oscal or {}).get("structured_fields") or {}).get("summary") or {}
    nvd_summary = ((nvd or {}).get("structured_fields") or {}).get("summary") or {}

    if not any([sprs, oscal, nvd, public_assurance, open_source_assurance, threat_intel]):
        return None

    current_cmmc_level = sprs_summary.get("current_cmmc_level")
    if current_cmmc_level is not None:
        try:
            current_cmmc_level = int(current_cmmc_level)
        except (TypeError, ValueError):
            current_cmmc_level = None

    open_poam_items = 0
    try:
        open_poam_items = int(oscal_summary.get("open_poam_items") or 0)
    except (TypeError, ValueError):
        open_poam_items = 0

    poam_active = sprs_summary.get("poam_active")
    if poam_active is None:
        poam_active = open_poam_items > 0
    else:
        poam_active = bool(poam_active) or open_poam_items > 0

    high_or_critical = 0
    critical = 0
    kev_count = 0
    try:
        high_or_critical = int(nvd_summary.get("high_or_critical_cve_count") or 0)
    except (TypeError, ValueError):
        high_or_critical = 0
    try:
        critical = int(nvd_summary.get("critical_cve_count") or 0)
    except (TypeError, ValueError):
        critical = 0
    try:
        kev_count = int(nvd_summary.get("kev_flagged_cve_count") or 0)
    except (TypeError, ValueError):
        kev_count = 0

    artifact_sources = [
        source
        for source, record in (
            ("sprs_import", sprs),
            ("oscal_upload", oscal),
            ("nvd_overlay", nvd),
        )
        if record
    ]
    if isinstance(public_assurance, dict):
        artifact_sources.extend(public_assurance.get("public_artifact_sources") or [])
        artifact_sources.append("public_assurance_evidence_fixture")
    if isinstance(open_source_assurance, dict):
        artifact_sources.extend(open_source_assurance.get("open_source_sources") or [])

    deduped_sources: list[str] = []
    for source in artifact_sources:
        text = str(source or "").strip()
        if text and text not in deduped_sources:
            deduped_sources.append(text)

    summary = {
        "sprs_artifact_id": sprs.get("id") if isinstance(sprs, dict) else None,
        "oscal_artifact_id": oscal.get("id") if isinstance(oscal, dict) else None,
        "nvd_artifact_id": nvd.get("id") if isinstance(nvd, dict) else None,
        "current_cmmc_level": current_cmmc_level,
        "assessment_date": sprs_summary.get("assessment_date") or "",
        "assessment_status": sprs_summary.get("status") or "",
        "poam_active": bool(poam_active),
        "open_poam_items": open_poam_items,
        "system_name": oscal_summary.get("system_name") or "",
        "total_control_references": int(oscal_summary.get("total_control_references") or 0),
        "high_or_critical_cve_count": high_or_critical,
        "critical_cve_count": critical,
        "kev_flagged_cve_count": kev_count,
        "product_terms": list((nvd or {}).get("structured_fields", {}).get("product_terms") or []),
        "artifact_sources": deduped_sources,
    }
    if isinstance(public_assurance, dict):
        summary.update(public_assurance)
    if isinstance(open_source_assurance, dict):
        summary.update(open_source_assurance)
    if isinstance(threat_intel, dict):
        summary.update(threat_intel)
    return summary


def build_cmmc_gate_overlay(
    summary: dict | None,
    *,
    profile: str = "",
    program: str = "",
    explicit_required_level: int = 0,
) -> dict:
    if not isinstance(summary, dict):
        return {}

    required_level = explicit_required_level
    if required_level <= 0 and profile == "defense_acquisition":
        required_level = 2
    handles_cui = required_level > 0
    current_level = summary.get("current_cmmc_level")
    if current_level is None:
        current_level = 0

    return {
        "handles_cui": handles_cui,
        "required_cmmc_level": required_level,
        "current_cmmc_level": int(current_level or 0),
        "entity_has_active_poam": bool(summary.get("poam_active")),
        "assessment_date": str(summary.get("assessment_date") or ""),
    }


def apply_cmmc_readiness_overlay(summary: dict | None, *, current_score: float = 0.0) -> float:
    if not isinstance(summary, dict):
        return current_score

    current_level = int(summary.get("current_cmmc_level") or 0)
    poam_active = bool(summary.get("poam_active"))
    critical = int(summary.get("critical_cve_count") or 0)
    kev = int(summary.get("kev_flagged_cve_count") or 0)

    score = float(current_score or 0.0)

    if current_level <= 0:
        score = max(score, 0.55)
    elif current_level == 1:
        score = max(score, 0.42 if poam_active else 0.5)
    else:
        score = max(score, 0.08 if not poam_active else 0.18)

    if critical > 0:
        score = max(score, min(0.75, 0.24 + critical * 0.08))
    if kev > 0:
        score = max(score, min(0.82, score + kev * 0.06))

    return round(min(score, 0.95), 4)
