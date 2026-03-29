from __future__ import annotations

import re
from typing import Any

from transaction_authorization import (
    TransactionAuthorization,
    TransactionInput,
    TransactionOrchestrator,
    TransactionPerson,
)


POSTURE_HIERARCHY = [
    "likely_prohibited",
    "escalate",
    "likely_license_required",
    "likely_exception_or_exemption",
    "likely_nlr",
    "insufficient_confidence",
]
POSTURE_SEVERITY = {posture: index for index, posture in enumerate(POSTURE_HIERARCHY)}


AMBIGUITY_PATTERNS = {
    "special_project": [
        "special project",
        "confidential customer",
        "sensitive customer",
        "customer directed",
        "strategic program",
    ],
    "government_or_military_context": [
        "government",
        "defense",
        "defence",
        "armed forces",
        "ministry",
        "naval",
        "air force",
        "maritime domain awareness",
        "range instrumentation",
    ],
    "transshipment_or_intermediary": [
        "reexport",
        "distributor",
        "reseller",
        "broker",
        "channel partner",
        "onward delivery",
    ],
    "telemetry_or_guidance": [
        "telemetry",
        "guidance",
        "launch",
        "uav",
        "drone",
        "unmanned",
        "range instrumentation",
    ],
    "surveillance_or_interception": [
        "surveillance",
        "monitoring",
        "intercept",
        "persistent monitoring",
        "maritime domain awareness",
    ],
    "integration_ambiguity": [
        "integration support",
        "integration",
        "pilot deployment",
        "evaluation",
        "lab evaluation",
        "testing",
        "trial",
        "support team",
    ],
    "defense_service_or_remote_support": [
        "technical assistance",
        "mission planning",
        "operator training",
        "training team",
        "field service representative",
        "remote troubleshooting",
        "depot repair guidance",
        "maintenance analytics support",
        "software support session",
    ],
    "remote_access_to_technical_data": [
        "remote access",
        "telework",
        "screen share",
        "vpn",
        "cloud repository",
        "source code access",
        "git repository",
        "shared workspace",
        "remote session",
    ],
    "agreement_scope_or_proviso_gap": [
        "expanded scope",
        "scope expanded",
        "new affiliate",
        "new site",
        "new country",
        "proviso",
        "not sure if taa",
        "unclear authority",
        "outside original scope",
    ],
    "third_country_national_or_subcontractor": [
        "third-country national",
        "dual national",
        "subcontractor",
        "affiliate engineer",
        "borrowed labor",
        "staff augmentation",
    ],
}

NEGATION_GUARDS = {
    "transshipment_or_intermediary": [
        "no broker",
        "no reseller",
        "no onward delivery",
        "no onward transfer",
        "without broker",
        "direct delivery",
        "direct end user",
        "final country confirmed",
        "no intermediary",
    ]
}


def _most_restrictive(*postures: str) -> str:
    best = "insufficient_confidence"
    best_rank = POSTURE_SEVERITY.get(best, 99)
    for posture in postures:
        rank = POSTURE_SEVERITY.get(posture, 99)
        if rank < best_rank:
            best = posture
            best_rank = rank
    return best


def _text_blob(txn: TransactionInput) -> str:
    person_parts: list[str] = []
    for person in txn.persons:
        person_parts.extend(
            [
                str(person.name or ""),
                " ".join(str(nat or "") for nat in person.nationalities),
                str(person.employer or ""),
                str(person.role or ""),
                str(person.access_level or ""),
            ]
        )
    return " ".join(
        [
            str(txn.item_or_data_summary or ""),
            str(txn.end_use_summary or ""),
            str(txn.access_context or ""),
            str(txn.destination_company or ""),
            str(txn.end_user_name or ""),
            str(txn.notes or ""),
            " ".join(person_parts),
        ]
    ).lower()


def _has_any(text: str, patterns: tuple[str, ...] | list[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def _agreement_reference_present(text: str) -> bool:
    if re.search(r"\bno\b[^.]{0,30}\b(taa|mla|wda)\b", text) or _has_any(
        text, ("unclear authority", "no agreement reference")
    ):
        return False
    return _has_any(
        text,
        (
            "taa ",
            "taa-",
            "mla ",
            "mla-",
            "wda ",
            "wda-",
            "agreement reference",
            "dsp-5",
            "dsp-73",
            "deccs authorization",
        ),
    )


def _ttcp_present(text: str) -> bool:
    if re.search(r"\b(no|without)\b[^.]{0,30}\b(ttcp|tcp)\b", text):
        return False
    return _has_any(
        text,
        (
            "ttcp",
            "tcp in place",
            "technology control plan",
            "access control plan",
            "named engineers only",
            "named personnel only",
        ),
    )


def _proviso_accepted(text: str) -> bool:
    if _has_any(text, ("proviso unclear", "proviso not accepted", "no proviso", "unclear proviso")):
        return False
    return _has_any(
        text,
        (
            "proviso accepted",
            "provisos accepted",
            "scope locked",
            "scope approved",
            "agreement scope confirmed",
        ),
    )


def _scope_confirmed(text: str) -> bool:
    return _has_any(
        text,
        (
            "scope confirmed",
            "agreement scope confirmed",
            "repository branch in scope",
            "limited to the repository branch",
            "bounded scope",
            "named engineers only",
        ),
    )


def _has_foreign_person(txn: TransactionInput) -> bool:
    for person in txn.persons:
        nationalities = [str(nat or "").upper() for nat in person.nationalities]
        if nationalities and any(nat and nat != "US" for nat in nationalities):
            return True
    return False


def _collect_ambiguity_flags(txn: TransactionInput, text: str) -> list[str]:
    flags: list[str] = []
    for flag, patterns in AMBIGUITY_PATTERNS.items():
        if _flag_present(text, flag, patterns):
            flags.append(flag)
    if txn.request_type == "foreign_person_access" or _has_foreign_person(txn):
        flags.append("foreign_person_access")
    if (
        (
            "defense_service_or_remote_support" in flags
            or "third_country_national_or_subcontractor" in flags
            or "agreement_scope_or_proviso_gap" in flags
        )
        and (not _agreement_reference_present(text) or not _proviso_accepted(text))
        and "agreement_scope_or_proviso_gap" not in flags
    ):
        flags.append("agreement_scope_or_proviso_gap")
    if (
        "foreign_person_access" in flags
        and "remote_access_to_technical_data" in flags
        and not _ttcp_present(text)
        and "agreement_scope_or_proviso_gap" not in flags
    ):
        flags.append("agreement_scope_or_proviso_gap")
    return flags


def _flag_present(text: str, flag: str, patterns: list[str]) -> bool:
    if flag == "transshipment_or_intermediary":
        guards = NEGATION_GUARDS.get(flag, [])
        if any(guard in text for guard in guards):
            return False
    return any(pattern in text for pattern in patterns)


def _collect_missing_facts(txn: TransactionInput, flags: list[str]) -> list[str]:
    missing: list[str] = []
    text = _text_blob(txn)
    if str(txn.classification_guess or "").strip().upper() in {"", "UNKNOWN", "TBD"}:
        missing.append("confirmed_classification")
    if "integration_ambiguity" in flags:
        missing.extend(["final_end_use", "operational_scope"])
    if "special_project" in flags:
        missing.extend(["program_name", "sponsoring_customer"])
    if "government_or_military_context" in flags:
        missing.extend(["government_sponsor", "specific_platform"])
    if "telemetry_or_guidance" in flags:
        missing.extend(["payload_or_platform_type"])
    if "surveillance_or_interception" in flags:
        missing.extend(["data_collection_scope"])
    if "transshipment_or_intermediary" in flags:
        end_user = str(txn.end_user_name or "").strip()
        if not end_user or _looks_like_intermediary_name(end_user):
            missing.append("final_end_user")
        if txn.request_type == "reexport" or any(
            token in text
            for token in (
                "another jurisdiction",
                "final countries not yet confirmed",
                "final country not yet confirmed",
                "onward delivery",
                "onward transfer",
                "reexport",
            )
        ):
            missing.append("final_country")
        missing.append("intermediary_role")
    if not str(txn.end_user_name or "").strip():
        missing.append("final_end_user")
    if "defense_service_or_remote_support" in flags:
        if not _scope_confirmed(text):
            missing.append("service_scope")
        if not str(txn.end_user_name or "").strip():
            missing.append("authorized_end_user")
    if "foreign_person_access" in flags:
        if not txn.persons:
            missing.append("authorized_person_list")
        if not str(txn.destination_country or "").strip():
            missing.append("access_location")
    if "remote_access_to_technical_data" in flags:
        if not _scope_confirmed(text):
            missing.append("remote_access_scope")
        if not _ttcp_present(text):
            missing.append("ttcp_or_tcp")
    if "agreement_scope_or_proviso_gap" in flags:
        if not _agreement_reference_present(text):
            missing.append("taa_mla_wda_reference")
        if not _proviso_accepted(text):
            missing.append("proviso_scope")
            missing.append("proviso_acceptance")
        if not _ttcp_present(text):
            missing.append("ttcp_or_tcp")
    if "third_country_national_or_subcontractor" in flags:
        missing.extend(["subcontractor_authority", "third_country_national_plan"])
    # Preserve order but deduplicate.
    deduped: list[str] = []
    for item in missing:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _ambiguity_score(flags: list[str]) -> int:
    score = 0
    for flag in flags:
        if flag in {"transshipment_or_intermediary", "telemetry_or_guidance", "surveillance_or_interception"}:
            score += 2
        else:
            score += 1
    return score


def _looks_like_intermediary_name(value: str) -> bool:
    text = str(value or "").lower()
    return any(
        token in text
        for token in (
            "distributor",
            "reseller",
            "broker",
            "channel",
            "logistics",
            "trading",
            "freeport",
            "hub",
            "partner",
        )
    )


def _proposed_posture(
    deterministic_posture: str, ambiguity_flags: list[str], missing_facts: list[str]
) -> str:
    if deterministic_posture in {"likely_prohibited", "insufficient_confidence"}:
        return deterministic_posture
    if not missing_facts and any(
        flag in ambiguity_flags
        for flag in ("foreign_person_access", "remote_access_to_technical_data", "defense_service_or_remote_support")
    ):
        return deterministic_posture
    score = _ambiguity_score(ambiguity_flags)
    if score >= 4:
        return "escalate"
    if any(
        flag in ambiguity_flags
        for flag in (
            "defense_service_or_remote_support",
            "foreign_person_access",
            "remote_access_to_technical_data",
            "agreement_scope_or_proviso_gap",
            "third_country_national_or_subcontractor",
        )
    ) and any(
        fact in missing_facts
        for fact in (
            "taa_mla_wda_reference",
            "proviso_scope",
            "proviso_acceptance",
            "ttcp_or_tcp",
            "authorized_person_list",
            "subcontractor_authority",
            "third_country_national_plan",
        )
    ):
        return "escalate"
    if deterministic_posture in {"likely_nlr", "likely_exception_or_exemption"} and score >= 2:
        return "escalate"
    if deterministic_posture == "likely_license_required" and score >= 3:
        return "escalate"
    if len(missing_facts) >= 4 and deterministic_posture == "likely_nlr":
        return "escalate"
    return deterministic_posture


def analyze_ambiguous_end_use(
    txn: TransactionInput, deterministic_auth: TransactionAuthorization
) -> dict[str, Any]:
    text = _text_blob(txn)
    ambiguity_flags = _collect_ambiguity_flags(txn, text)
    missing_facts = _collect_missing_facts(txn, ambiguity_flags)
    proposed_posture = _proposed_posture(
        deterministic_auth.combined_posture, ambiguity_flags, missing_facts
    )
    disagrees = proposed_posture != deterministic_auth.combined_posture

    if ambiguity_flags and not missing_facts and proposed_posture == deterministic_auth.combined_posture:
        explanation = (
            "The narrative contains defense-service or access signals, but the agreement, TTCP, and scope controls are concrete enough that the deterministic posture should stand."
        )
    elif ambiguity_flags:
        theme_text = ", ".join(flag.replace("_", " ") for flag in ambiguity_flags)
        explanation = (
            f"Ambiguous end-use narrative detected with {theme_text}. "
            f"Helios should verify {', '.join(missing_facts[:4]) or 'the final end use'} before clearance."
        )
    else:
        explanation = (
            "The end-use narrative is concrete enough that the deterministic posture should stand without AI-driven elevation."
        )

    recommended_questions: list[str] = []
    if "final_end_use" in missing_facts:
        recommended_questions.append("What is the final operational end use?")
    if "program_name" in missing_facts:
        recommended_questions.append("What program or project is this tied to?")
    if "government_sponsor" in missing_facts:
        recommended_questions.append("Is there a government, military, or intelligence sponsor?")
    if "final_country" in missing_facts:
        recommended_questions.append("What is the final country of use after the intermediary?")
    if "data_collection_scope" in missing_facts:
        recommended_questions.append("Will the deployment support surveillance, interception, or persistent monitoring?")
    if "payload_or_platform_type" in missing_facts:
        recommended_questions.append("What payload, platform, or vehicle will use this item or data?")
    if "taa_mla_wda_reference" in missing_facts:
        recommended_questions.append("What TAA, MLA, WDA, or other authorization covers this service or release?")
    if "ttcp_or_tcp" in missing_facts:
        recommended_questions.append("Is there an approved TTCP or TCP covering remote access and controlled data handling?")
    if "proviso_scope" in missing_facts or "proviso_acceptance" in missing_facts:
        recommended_questions.append("What provisos apply, and has the customer accepted the current scope without drift?")
    if "authorized_person_list" in missing_facts:
        recommended_questions.append("Which named foreign persons or subcontractor staff will receive access?")
    if "access_location" in missing_facts:
        recommended_questions.append("Where will the technical access occur, and from which country or facility?")
    if "subcontractor_authority" in missing_facts:
        recommended_questions.append("What authority allows the subcontractor or affiliate engineers to participate?")
    if "third_country_national_plan" in missing_facts:
        recommended_questions.append("How are dual or third-country nationals handled under the current authorization?")
    if "service_scope" in missing_facts:
        recommended_questions.append("Is this only installation or training, or does it expand into defense services or troubleshooting?")

    return {
        "provider": "local_challenge_model",
        "mode": "heuristic_v1",
        "deterministic_posture": deterministic_auth.combined_posture,
        "proposed_posture": proposed_posture,
        "disagrees_with_deterministic": disagrees,
        "ambiguity_flags": ambiguity_flags,
        "missing_facts": missing_facts,
        "recommended_questions": recommended_questions,
        "explanation": explanation,
    }


def build_hybrid_posture(
    deterministic_auth: TransactionAuthorization, ai_assessment: dict[str, Any]
) -> str:
    deterministic_posture = deterministic_auth.combined_posture
    ai_posture = str(ai_assessment.get("proposed_posture") or deterministic_posture)
    if deterministic_posture in {"likely_prohibited", "insufficient_confidence"}:
        return deterministic_posture
    return _most_restrictive(deterministic_posture, ai_posture)


def _to_transaction_input(export_input: dict[str, Any]) -> TransactionInput:
    recipient = (
        str(export_input.get("recipient_name") or "").strip()
        or str(export_input.get("destination_company") or "").strip()
        or str(export_input.get("end_user_name") or "").strip()
    )
    persons = [
        TransactionPerson(
            name=str(person.get("name") or ""),
            nationalities=[
                str(nat or "") for nat in (person.get("nationalities") or []) if str(nat or "").strip()
            ],
            employer=str(person.get("employer") or "") or None,
            role=str(person.get("role") or "") or None,
            item_classification=str(person.get("item_classification") or "") or None,
            access_level=str(person.get("access_level") or "") or None,
        )
        for person in (export_input.get("persons") or [])
        if isinstance(person, dict) and str(person.get("name") or "").strip()
    ]
    return TransactionInput(
        jurisdiction_guess=str(export_input.get("jurisdiction_guess") or "unknown"),
        request_type=str(export_input.get("request_type") or "item_transfer"),
        classification_guess=str(export_input.get("classification_guess") or "unknown"),
        item_or_data_summary=str(export_input.get("item_or_data_summary") or ""),
        destination_country=str(export_input.get("destination_country") or ""),
        destination_company=str(export_input.get("destination_company") or recipient),
        end_use_summary=str(export_input.get("end_use_summary") or ""),
        end_user_name=str(export_input.get("end_user_name") or recipient),
        access_context=str(export_input.get("access_context") or ""),
        persons=persons,
        notes=str(export_input.get("notes") or ""),
    )


def build_hybrid_export_review(export_input: dict[str, Any]) -> dict[str, Any]:
    txn = _to_transaction_input(export_input)
    orchestrator = TransactionOrchestrator()
    orchestrator._persist = lambda auth, txn: None  # type: ignore[attr-defined]
    deterministic_auth = orchestrator.authorize(txn)
    ai_assessment = analyze_ambiguous_end_use(txn, deterministic_auth)
    final_posture = build_hybrid_posture(deterministic_auth, ai_assessment)

    rules_guidance = deterministic_auth.rules_guidance or {}
    return {
        "version": "export-hybrid-review-v1",
        "deterministic_posture": deterministic_auth.combined_posture,
        "deterministic_posture_label": deterministic_auth.combined_posture_label,
        "deterministic_reason_summary": str(
            rules_guidance.get("reason_summary") or deterministic_auth.recommended_next_step or ""
        ),
        "deterministic_next_step": deterministic_auth.recommended_next_step,
        "ai_proposed_posture": ai_assessment["proposed_posture"],
        "final_posture": final_posture,
        "disagrees_with_deterministic": bool(ai_assessment["disagrees_with_deterministic"]),
        "ambiguity_flags": ai_assessment["ambiguity_flags"],
        "missing_facts": ai_assessment["missing_facts"],
        "recommended_questions": ai_assessment["recommended_questions"],
        "ai_explanation": ai_assessment["explanation"],
        "license_exception": deterministic_auth.license_exception,
        "safe_boundary": {
            "ai_can_elevate": True,
            "ai_can_downgrade_hard_stop": False,
            "ai_can_downgrade_insufficient_confidence": False,
        },
    }
