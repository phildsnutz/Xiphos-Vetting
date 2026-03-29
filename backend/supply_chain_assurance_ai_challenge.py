from __future__ import annotations

from typing import Any

from cyber_risk_scoring import score_vendor_cyber_risk


ASSURANCE_POSTURE_HIERARCHY = ["blocked", "review", "qualified", "ready"]
ASSURANCE_POSTURE_SEVERITY = {
    posture: index for index, posture in enumerate(ASSURANCE_POSTURE_HIERARCHY)
}


def _context(case: dict[str, Any]) -> dict[str, Any]:
    return case.get("assurance_context") or {}


def _nvd(case: dict[str, Any]) -> dict[str, Any]:
    return case.get("nvd_summary") or {}


def _sprs(case: dict[str, Any]) -> dict[str, Any]:
    return case.get("sprs_summary") or {}


def _oscal(case: dict[str, Any]) -> dict[str, Any]:
    return case.get("oscal_summary") or {}


def _text_blob(case: dict[str, Any]) -> str:
    context = _context(case)
    parts = [
        case.get("description", ""),
        case.get("supplier_narrative", ""),
        case.get("product_narrative", ""),
        case.get("dependency_narrative", ""),
        context.get("vex_justification", ""),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _implemented_control_ratio(oscal_summary: dict[str, Any]) -> float:
    total_controls = _safe_int(oscal_summary.get("total_control_references"), 0)
    implemented = _safe_int(oscal_summary.get("implemented_control_count"), 0)
    if total_controls <= 0:
        return 0.0
    return implemented / total_controls


def _labelize(tokens: list[str], *, limit: int | None = None) -> str:
    items = [token.replace("_", " ") for token in tokens]
    if limit is not None:
        items = items[:limit]
    return ", ".join(items)


def deterministic_assurance_posture(result: dict[str, Any], case: dict[str, Any]) -> str:
    tier = str(result.get("cyber_risk_tier") or "").upper()
    context = case.get("assurance_context") or {}
    nvd_summary = case.get("nvd_summary") or {}
    sprs_summary = case.get("sprs_summary") or {}
    graph_data = case.get("graph_data") or {}
    high_risk_entities = sum(
        1
        for entity in graph_data.get("entities") or []
        if str(entity.get("risk_level") or "").lower() in {"high", "critical"}
    )
    critical_cves = int(nvd_summary.get("critical_cve_count") or 0)
    federal_scope = bool(context.get("federal_scope"))
    mission_critical = bool(context.get("mission_critical"))
    current_cmmc_level = int(sprs_summary.get("current_cmmc_level") or 0)
    has_oscal = bool(case.get("oscal_summary"))

    if tier == "CRITICAL":
        return "blocked"
    if tier in {"HIGH", "ELEVATED"}:
        return "review"
    if tier == "MODERATE":
        if critical_cves > 0 or high_risk_entities > 0:
            return "review"
        if federal_scope and (current_cmmc_level < 2 or not has_oscal):
            return "review"
        return "qualified"
    if tier == "LOW" and (mission_critical or federal_scope):
        return "qualified"
    return "ready"


def _collect_ambiguity_flags(case: dict[str, Any]) -> list[str]:
    context = _context(case)
    nvd_summary = _nvd(case)
    sprs_summary = _sprs(case)
    flags: list[str] = []

    sbom_present = bool(context.get("sbom_present"))
    sbom_fresh_days = _safe_int(context.get("sbom_fresh_days"), 999)
    vex_status = str(context.get("vex_status") or "missing").lower()
    secure_by_design_evidence = str(context.get("secure_by_design_evidence") or "none").lower()
    provenance_attested = bool(context.get("provenance_attested"))
    mission_critical = bool(context.get("mission_critical"))
    firmware_or_ot = bool(context.get("firmware_or_ot"))
    federal_scope = bool(context.get("federal_scope"))
    fourth_party_concentration = str(context.get("fourth_party_concentration") or "").lower()
    kev_count = _safe_int(nvd_summary.get("kev_flagged_cve_count"), 0)
    current_cmmc_level = _safe_int(sprs_summary.get("current_cmmc_level"), 0)
    open_source_risk_level = str(context.get("open_source_risk_level") or "").lower()
    scorecard_low_repo_count = _safe_int(context.get("scorecard_low_repo_count"), 0)
    threat_pressure = str(context.get("threat_pressure") or "").lower()
    cisa_advisory_count = _safe_int(context.get("cisa_advisory_count"), 0)
    attack_technique_count = len(context.get("attack_technique_ids") or [])

    if (not sbom_present) or sbom_fresh_days > 180 or vex_status in {"missing", "unknown", "none"}:
        flags.append("sbom_vex_gap")
    if secure_by_design_evidence == "marketing_only":
        flags.append("marketing_without_artifacts")
    if fourth_party_concentration in {"single_provider", "high"} or any(
        bool(context.get(key))
        for key in ("shared_signing_service", "shared_msp", "shared_telecom")
    ):
        flags.append("fourth_party_concentration")
    if mission_critical:
        flags.append("mission_critical_dependency")
    if firmware_or_ot:
        flags.append("firmware_or_ot_exposure")
    if federal_scope and current_cmmc_level < 2:
        flags.append("cmmc_evidence_gap")
    if vex_status == "not_affected" and (
        _safe_int(nvd_summary.get("critical_cve_count"), 0) > 0 or kev_count > 0
    ):
        flags.append("exploitability_contradiction")
    if not provenance_attested:
        flags.append("provenance_gap")
    if open_source_risk_level in {"medium", "high"} and _safe_int(context.get("open_source_advisory_count"), 0) > 0:
        flags.append("open_source_vulnerability_pressure")
    if scorecard_low_repo_count > 0:
        flags.append("repository_hygiene_gap")
    if threat_pressure in {"medium", "high"} and (cisa_advisory_count > 0 or attack_technique_count > 0):
        flags.append("active_threat_pressure")

    return flags


def _collect_missing_facts(case: dict[str, Any], flags: list[str]) -> list[str]:
    context = _context(case)
    missing: list[str] = []
    strong_exculpatory = _strong_exculpatory_evidence(case)

    if "sbom_vex_gap" in flags:
        if not context.get("sbom_present") or _safe_int(context.get("sbom_fresh_days"), 999) > 180:
            missing.append("fresh_sbom")
        if str(context.get("vex_status") or "missing").lower() in {"missing", "unknown", "none"}:
            missing.append("vex_assertion")
    if "marketing_without_artifacts" in flags:
        missing.append("secure_by_design_artifacts")
    if "fourth_party_concentration" in flags:
        missing.append("fourth_party_dependency_map")
    if "provenance_gap" in flags:
        missing.append("provenance_attestation")
    if "cmmc_evidence_gap" in flags:
        missing.append("current_cmmc_evidence")
    if "firmware_or_ot_exposure" in flags and not strong_exculpatory:
        missing.append("firmware_update_path")
    if "open_source_vulnerability_pressure" in flags:
        missing.append("package_vulnerability_triage")
    if "repository_hygiene_gap" in flags:
        missing.append("repository_hygiene_evidence")
    if "active_threat_pressure" in flags:
        missing.append("active_threat_mitigation")

    deduped: list[str] = []
    for item in missing:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _strong_exculpatory_evidence(case: dict[str, Any]) -> bool:
    context = _context(case)
    nvd_summary = _nvd(case)
    sprs_summary = _sprs(case)
    oscal_summary = _oscal(case)
    justification = str(context.get("vex_justification") or "").lower()

    return (
        bool(context.get("sbom_present"))
        and _safe_int(context.get("sbom_fresh_days"), 999) <= 45
        and str(context.get("vex_status") or "").lower() == "not_affected"
        and any(
            phrase in justification
            for phrase in (
                "not present in deployed build",
                "not in deployed build",
                "component absent",
                "not shipped",
                "non-deployed test image",
            )
        )
        and bool(context.get("provenance_attested"))
        and _safe_int(nvd_summary.get("kev_flagged_cve_count"), 0) == 0
        and _safe_int(sprs_summary.get("current_cmmc_level"), 0) >= 2
        and _implemented_control_ratio(oscal_summary) >= 0.75
    )


def _proposed_posture(
    deterministic_posture: str, case: dict[str, Any], ambiguity_flags: list[str]
) -> str:
    nvd_summary = _nvd(case)
    context = _context(case)
    vex_status = str(context.get("vex_status") or "missing").lower()
    kev_count = _safe_int(nvd_summary.get("kev_flagged_cve_count"), 0)
    critical_count = _safe_int(nvd_summary.get("critical_cve_count"), 0)

    if deterministic_posture == "blocked":
        return deterministic_posture

    if (
        "mission_critical_dependency" in ambiguity_flags
        and "firmware_or_ot_exposure" in ambiguity_flags
        and (kev_count > 0 or critical_count > 0)
        and vex_status in {"affected", "missing", "unknown", "none"}
    ):
        return "blocked"

    if deterministic_posture in {"ready", "qualified"} and any(
        flag in ambiguity_flags
        for flag in (
            "sbom_vex_gap",
            "marketing_without_artifacts",
            "fourth_party_concentration",
            "cmmc_evidence_gap",
            "provenance_gap",
            "open_source_vulnerability_pressure",
            "repository_hygiene_gap",
            "active_threat_pressure",
        )
    ):
        return "review"

    if deterministic_posture == "review" and _strong_exculpatory_evidence(case):
        return "qualified"

    return deterministic_posture


def analyze_supply_chain_assurance(
    case: dict[str, Any], deterministic_posture: str, deterministic_result: dict[str, Any]
) -> dict[str, Any]:
    ambiguity_flags = _collect_ambiguity_flags(case)
    missing_facts = _collect_missing_facts(case, ambiguity_flags)
    proposed_posture = _proposed_posture(deterministic_posture, case, ambiguity_flags)
    disagrees = proposed_posture != deterministic_posture
    text = _text_blob(case)
    strong_exculpatory = _strong_exculpatory_evidence(case)

    if strong_exculpatory and proposed_posture == deterministic_posture:
        explanation = (
            "The supplier, software, and dependency evidence is concrete enough that the deterministic assurance posture should stand. "
            "Fresh SBOM, VEX-backed exploitability separation, provenance, and current readiness evidence suppress a false alarm."
        )
    elif ambiguity_flags:
        context = _context(case)
        threat_phrase = ""
        if "active_threat_pressure" in ambiguity_flags:
            threat_pressure = str(context.get("threat_pressure") or "active").replace("_", " ")
            advisory_count = _safe_int(context.get("cisa_advisory_count"), 0)
            technique_count = len(context.get("attack_technique_ids") or [])
            threat_phrase = (
                f" Shared threat signal is {threat_pressure} with {advisory_count} CISA advisories and "
                f"{technique_count} ATT&CK techniques in scope."
            )
        explanation = (
            f"Supply chain assurance ambiguity detected across {_labelize(ambiguity_flags)}. "
            f"Helios should verify {_labelize(missing_facts, limit=4) or 'dependency evidence'} before clearance."
            f"{threat_phrase}"
        )
    else:
        explanation = (
            "The supplier, software, and dependency evidence is concrete enough that the deterministic assurance posture should stand."
        )

    recommended_questions: list[str] = []
    if "fresh_sbom" in missing_facts:
        recommended_questions.append("Can the supplier provide a fresh SBOM for the deployed build?")
    if "vex_assertion" in missing_facts:
        recommended_questions.append("Is there a VEX assertion that separates affected from exploitable components?")
    if "fourth_party_dependency_map" in missing_facts:
        recommended_questions.append("What fourth-party providers or shared services sit behind this supplier?")
    if "provenance_attestation" in missing_facts:
        recommended_questions.append("Is there signed provenance or build-attestation evidence for the current release?")
    if "current_cmmc_evidence" in missing_facts:
        recommended_questions.append("What current SPRS, CMMC, or equivalent federal evidence is on file?")
    if "firmware_update_path" in missing_facts:
        recommended_questions.append("How are firmware updates signed, distributed, and rolled back in the field?")
    if "package_vulnerability_triage" in missing_facts:
        recommended_questions.append("Which declared open-source packages remain affected, and what is the remediation timeline?")
    if "repository_hygiene_evidence" in missing_facts:
        recommended_questions.append("Which source repositories fail hygiene checks, and what remediation plan exists for branch protection, reviews, or pinning?")
    if "active_threat_mitigation" in missing_facts:
        recommended_questions.append("Which mitigations directly address the active ATT&CK techniques and CISA advisory tradecraft in scope?")

    return {
        "provider": "local_challenge_model",
        "mode": "heuristic_v1",
        "deterministic_posture": deterministic_posture,
        "deterministic_tier": deterministic_result.get("cyber_risk_tier"),
        "proposed_posture": proposed_posture,
        "disagrees_with_deterministic": disagrees,
        "ambiguity_flags": ambiguity_flags,
        "missing_facts": missing_facts,
        "recommended_questions": recommended_questions,
        "explanation": explanation,
        "context_text": text,
    }


def build_hybrid_assurance_posture(deterministic_posture: str, ai_assessment: dict[str, Any]) -> str:
    ai_posture = str(ai_assessment.get("proposed_posture") or deterministic_posture)
    if deterministic_posture == "blocked":
        return deterministic_posture
    if deterministic_posture == "review" and ai_posture == "qualified":
        return "qualified"
    deterministic_rank = ASSURANCE_POSTURE_SEVERITY.get(deterministic_posture, 99)
    ai_rank = ASSURANCE_POSTURE_SEVERITY.get(ai_posture, 99)
    return ai_posture if ai_rank < deterministic_rank else deterministic_posture


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _live_case_from_cyber_summary(
    cyber_summary: dict[str, Any],
    *,
    vendor: dict[str, Any] | None = None,
    supplier_passport: dict[str, Any] | None = None,
) -> dict[str, Any]:
    vendor = vendor or {}
    supplier_passport = supplier_passport or {}
    program = str(vendor.get("program") or "")
    profile = str(vendor.get("profile") or "")
    artifact_sources = [str(source) for source in (cyber_summary.get("artifact_sources") or []) if str(source)]
    product_terms = [str(term) for term in (cyber_summary.get("product_terms") or []) if str(term)]
    product_blob = " ".join(product_terms)
    network_risk = supplier_passport.get("network_risk") or {}
    high_risk_neighbors = int(network_risk.get("high_risk_neighbors") or 0)
    secure_by_design_evidence = str(cyber_summary.get("secure_by_design_evidence") or "").lower()
    vex_status = str(cyber_summary.get("vex_status") or "").lower()
    open_source_risk_level = str(cyber_summary.get("open_source_risk_level") or "").lower()
    threat_pressure = str(cyber_summary.get("threat_pressure") or "").lower()
    sbom_fresh_days = cyber_summary.get("sbom_fresh_days")
    try:
        sbom_fresh_days = int(sbom_fresh_days) if sbom_fresh_days is not None else 999
    except (TypeError, ValueError):
        sbom_fresh_days = 999

    return {
        "scenario_id": str(vendor.get("id") or "live-assurance-review"),
        "vendor_name": str(vendor.get("name") or supplier_passport.get("vendor", {}).get("name") or "Live supplier"),
        "description": "Live supply chain assurance review from captured cyber evidence artifacts.",
        "assurance_context": {
            "federal_scope": bool(profile == "defense_acquisition" or program.startswith("dod_") or cyber_summary.get("current_cmmc_level")),
            "mission_critical": bool(program in {"dod_classified", "dod_unclassified"}),
            "firmware_or_ot": _contains_any(
                product_blob,
                ("firmware", "embedded", "avionics", "ot", "ics", "scada", "satcom", "telemetry", "router", "modem"),
            ),
            "fourth_party_concentration": "high" if high_risk_neighbors >= 2 else "",
            "secure_by_design_evidence": secure_by_design_evidence or ("artifact_backed" if artifact_sources else "none"),
            "sbom_present": bool(cyber_summary.get("sbom_present")) or any("sbom" in source.lower() for source in artifact_sources),
            "sbom_fresh_days": sbom_fresh_days,
            "vex_status": vex_status or ("present" if any("vex" in source.lower() for source in artifact_sources) else "missing"),
            "provenance_attested": bool(cyber_summary.get("provenance_attested")) or any("provenance" in source.lower() for source in artifact_sources),
            "shared_telecom": _contains_any(product_blob, ("telecom", "carrier", "backhaul", "satcom")),
            "open_source_risk_level": open_source_risk_level,
            "open_source_advisory_count": int(cyber_summary.get("open_source_advisory_count") or 0),
            "scorecard_low_repo_count": int(cyber_summary.get("scorecard_low_repo_count") or 0),
            "threat_pressure": threat_pressure,
            "cisa_advisory_count": len(cyber_summary.get("cisa_advisory_ids") or []),
            "attack_technique_ids": [str(item) for item in (cyber_summary.get("attack_technique_ids") or []) if str(item)],
            "attack_actor_families": [str(item) for item in (cyber_summary.get("attack_actor_families") or []) if str(item)],
            "threat_sectors": [str(item) for item in (cyber_summary.get("threat_sectors") or []) if str(item)],
        },
        "sprs_summary": {
            "current_cmmc_level": cyber_summary.get("current_cmmc_level"),
            "assessment_status": cyber_summary.get("assessment_status"),
            "poam_active": cyber_summary.get("poam_active"),
        },
        "oscal_summary": {
            "system_name": cyber_summary.get("system_name"),
            "total_control_references": cyber_summary.get("total_control_references"),
        },
        "nvd_summary": {
            "high_or_critical_cve_count": cyber_summary.get("high_or_critical_cve_count"),
            "critical_cve_count": cyber_summary.get("critical_cve_count"),
            "kev_flagged_cve_count": cyber_summary.get("kev_flagged_cve_count"),
            "product_terms": product_terms,
        },
        "graph_data": {
            "entities": [{"risk_level": "high"} for _ in range(high_risk_neighbors)],
        },
    }


def _deterministic_reason_summary(
    cyber_summary: dict[str, Any],
    deterministic_posture: str,
    *,
    supplier_passport: dict[str, Any] | None = None,
) -> str:
    bits: list[str] = []
    current_cmmc_level = cyber_summary.get("current_cmmc_level")
    if current_cmmc_level:
        bits.append(f"CMMC L{int(current_cmmc_level)}")
    elif cyber_summary.get("sprs_artifact_id"):
        bits.append("SPRS evidence present")
    if cyber_summary.get("poam_active"):
        open_items = int(cyber_summary.get("open_poam_items") or 0)
        bits.append(f"POA&M active ({open_items} open)")
    high_or_critical = int(cyber_summary.get("high_or_critical_cve_count") or 0)
    if high_or_critical:
        bits.append(f"{high_or_critical} high / critical CVEs")
    kev_count = int(cyber_summary.get("kev_flagged_cve_count") or 0)
    if kev_count:
        bits.append(f"{kev_count} KEV")
    total_controls = int(cyber_summary.get("total_control_references") or 0)
    if total_controls:
        bits.append(f"{total_controls} control refs")
    if cyber_summary.get("public_evidence_present"):
        public_bits = []
        if cyber_summary.get("sbom_present"):
            sbom_format = str(cyber_summary.get("sbom_format") or "SBOM")
            public_bits.append(f"{sbom_format} SBOM published")
        if str(cyber_summary.get("vex_status") or "").lower() not in {"", "missing", "unknown", "none"}:
            public_bits.append("VEX disclosed")
        if cyber_summary.get("provenance_attested"):
            public_bits.append("provenance attested")
        if cyber_summary.get("support_lifecycle_published"):
            public_bits.append("support lifecycle published")
        if public_bits:
            bits.append(", ".join(public_bits))
    if int(cyber_summary.get("open_source_advisory_count") or 0) > 0:
        bits.append(f"{int(cyber_summary.get('open_source_advisory_count') or 0)} OSS advisories")
    if int(cyber_summary.get("scorecard_low_repo_count") or 0) > 0:
        bits.append(f"{int(cyber_summary.get('scorecard_low_repo_count') or 0)} low-score repositories")
    if str(cyber_summary.get("threat_pressure") or "").lower() in {"medium", "high"}:
        threat_bits: list[str] = []
        if len(cyber_summary.get("cisa_advisory_ids") or []) > 0:
            threat_bits.append(f"{len(cyber_summary.get('cisa_advisory_ids') or [])} CISA advisories")
        if len(cyber_summary.get("attack_technique_ids") or []) > 0:
            threat_bits.append(f"{len(cyber_summary.get('attack_technique_ids') or [])} ATT&CK techniques")
        if threat_bits:
            bits.append(f"{str(cyber_summary.get('threat_pressure') or '').lower()} threat pressure from {', '.join(threat_bits)}")
    network_risk = (supplier_passport or {}).get("network_risk") or {}
    if int(network_risk.get("high_risk_neighbors") or 0) > 0:
        bits.append(f"{int(network_risk.get('high_risk_neighbors') or 0)} high-risk linked entities")
    if bits:
        return f"{deterministic_posture.title()} posture from {'; '.join(bits)}."
    return "Cyber evidence is thin, so Helios is holding a cautious assurance posture."


def _deterministic_next_step(posture: str) -> str:
    if posture == "blocked":
        return "Do not clear the supplier until artifact-backed remediation or isolation evidence closes the highest-risk gaps."
    if posture == "review":
        return "Request current assurance artifacts and resolve the missing evidence before approval."
    if posture == "qualified":
        return "Proceed only with documented compensating controls and a dated evidence packet."
    return "Proceed with routine monitoring and scheduled evidence refresh."


def build_hybrid_assurance_review(
    cyber_summary: dict[str, Any] | None,
    *,
    vendor: dict[str, Any] | None = None,
    supplier_passport: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(cyber_summary, dict) or not cyber_summary:
        return None

    live_case = _live_case_from_cyber_summary(
        cyber_summary,
        vendor=vendor,
        supplier_passport=supplier_passport,
    )
    deterministic_result = score_vendor_cyber_risk(
        case_id=str(live_case["scenario_id"]),
        vendor_name=str(live_case.get("vendor_name") or ""),
        sprs_summary=live_case.get("sprs_summary"),
        nvd_summary=live_case.get("nvd_summary"),
        oscal_summary=live_case.get("oscal_summary"),
        graph_data=live_case.get("graph_data"),
        profile=str((vendor or {}).get("profile") or "defense_acquisition"),
    )
    deterministic_posture = deterministic_assurance_posture(deterministic_result, live_case)
    ai_assessment = analyze_supply_chain_assurance(
        live_case,
        deterministic_posture,
        deterministic_result,
    )
    final_posture = build_hybrid_assurance_posture(deterministic_posture, ai_assessment)

    return {
        "version": "assurance-hybrid-review-v1",
        "deterministic_posture": deterministic_posture,
        "deterministic_tier": deterministic_result.get("cyber_risk_tier"),
        "deterministic_reason_summary": _deterministic_reason_summary(
            cyber_summary,
            deterministic_posture,
            supplier_passport=supplier_passport,
        ),
        "deterministic_next_step": _deterministic_next_step(deterministic_posture),
        "ai_proposed_posture": ai_assessment["proposed_posture"],
        "final_posture": final_posture,
        "disagrees_with_deterministic": bool(ai_assessment["disagrees_with_deterministic"]),
        "ambiguity_flags": ai_assessment["ambiguity_flags"],
        "missing_facts": ai_assessment["missing_facts"],
        "recommended_questions": ai_assessment["recommended_questions"],
        "ai_explanation": ai_assessment["explanation"],
        "artifact_sources": [str(source) for source in (cyber_summary.get("artifact_sources") or []) if str(source)],
        "threat_pressure": str(cyber_summary.get("threat_pressure") or "low"),
        "attack_technique_ids": [str(item) for item in (cyber_summary.get("attack_technique_ids") or []) if str(item)],
        "attack_actor_families": [str(item) for item in (cyber_summary.get("attack_actor_families") or []) if str(item)],
        "cisa_advisory_ids": [str(item) for item in (cyber_summary.get("cisa_advisory_ids") or []) if str(item)],
        "threat_sectors": [str(item) for item in (cyber_summary.get("threat_sectors") or []) if str(item)],
        "open_source_risk_level": str(cyber_summary.get("open_source_risk_level") or "low"),
        "open_source_advisory_count": int(cyber_summary.get("open_source_advisory_count") or 0),
        "scorecard_low_repo_count": int(cyber_summary.get("scorecard_low_repo_count") or 0),
        "safe_boundary": {
            "ai_can_elevate": True,
            "ai_can_downgrade_blocked": False,
            "ai_can_downgrade_review_with_artifact_backed_evidence": True,
        },
    }
