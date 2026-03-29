import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from export_ai_challenge import (  # noqa: E402
    _to_transaction_input,
    analyze_ambiguous_end_use,
    build_hybrid_posture,
)
from transaction_authorization import TransactionInput, TransactionOrchestrator  # noqa: E402


def _build_auth(payload: dict) -> tuple[TransactionInput, object]:
    txn = _to_transaction_input(payload)
    orchestrator = TransactionOrchestrator()
    orchestrator._persist = lambda auth, txn: None  # type: ignore[attr-defined]
    auth = orchestrator.authorize(txn)
    return txn, auth


def test_ai_challenge_elevates_black_box_special_project():
    txn, auth = _build_auth(
        {
            "jurisdiction_guess": "ear",
            "request_type": "item_transfer",
            "classification_guess": "EAR99",
            "item_or_data_summary": "Rugged networking kit for mission systems special project",
            "destination_country": "GB",
            "destination_company": "Allied Integrator Ltd",
            "end_use_summary": "Evaluation support for confidential customer mission systems program",
            "end_user_name": "Allied Integrator Ltd",
            "access_context": "Field integration support",
            "notes": "Customer directed special project",
        }
    )

    ai = analyze_ambiguous_end_use(txn, auth)

    assert auth.combined_posture == "likely_nlr"
    assert ai["proposed_posture"] == "escalate"
    assert ai["disagrees_with_deterministic"] is True
    assert "special_project" in ai["ambiguity_flags"]
    assert "program_name" in ai["missing_facts"]
    assert build_hybrid_posture(auth, ai) == "escalate"


def test_ai_challenge_holds_license_required_when_rules_are_already_conservative():
    txn, auth = _build_auth(
        {
            "jurisdiction_guess": "ear",
            "request_type": "technical_data_release",
            "classification_guess": "3E001",
            "item_or_data_summary": "Process tuning package for advanced radar module",
            "destination_country": "SG",
            "destination_company": "Lion City Systems",
            "end_use_summary": "Integration support for strategic program sustainment",
            "end_user_name": "Lion City Systems",
            "access_context": "Support team access for integration and testing",
            "notes": "Special project support",
        }
    )

    ai = analyze_ambiguous_end_use(txn, auth)

    assert auth.combined_posture == "likely_license_required"
    assert ai["proposed_posture"] == "likely_license_required"
    assert ai["disagrees_with_deterministic"] is False
    assert build_hybrid_posture(auth, ai) == "likely_license_required"


def test_ai_challenge_never_downgrades_insufficient_confidence():
    txn, auth = _build_auth(
        {
            "jurisdiction_guess": "ear",
            "request_type": "item_transfer",
            "classification_guess": "TBD",
            "item_or_data_summary": "Integration toolkit",
            "destination_country": "NL",
            "destination_company": "North Sea Systems",
            "end_use_summary": "Integration support for range instrumentation trial",
            "end_user_name": "North Sea Systems",
            "access_context": "Temporary field support",
            "notes": "Program office has not confirmed ECCN",
        }
    )

    ai = analyze_ambiguous_end_use(txn, auth)

    assert auth.combined_posture == "insufficient_confidence"
    assert ai["proposed_posture"] == "insufficient_confidence"
    assert "confirmed_classification" in ai["missing_facts"]
    assert build_hybrid_posture(auth, ai) == "insufficient_confidence"


def test_ai_challenge_escalates_remote_defense_service_without_ttcp():
    txn, auth = _build_auth(
        {
            "jurisdiction_guess": "itar",
            "request_type": "technical_data_release",
            "classification_guess": "USML CATEGORY XI",
            "item_or_data_summary": "Mission-system configuration notes and troubleshooting package",
            "destination_country": "GB",
            "destination_company": "Aegis Mission Systems Ltd",
            "end_use_summary": "Remote troubleshooting and mission planning support for allied air platform sustainment",
            "end_user_name": "Aegis Mission Systems Ltd",
            "access_context": "Remote access session and screen share from U.S. engineers into customer environment",
            "notes": "Customer wants support this week. No one has cited a TAA, MLA, or TTCP.",
        }
    )

    ai = analyze_ambiguous_end_use(txn, auth)

    assert auth.combined_posture == "likely_license_required"
    assert ai["proposed_posture"] == "escalate"
    assert "defense_service_or_remote_support" in ai["ambiguity_flags"]
    assert "agreement_scope_or_proviso_gap" in ai["ambiguity_flags"]
    assert "ttcp_or_tcp" in ai["missing_facts"]
    assert build_hybrid_posture(auth, ai) == "escalate"


def test_ai_challenge_holds_scoped_foreign_person_access_with_ttcp():
    txn, auth = _build_auth(
        {
            "jurisdiction_guess": "ear",
            "request_type": "foreign_person_access",
            "classification_guess": "3E001",
            "item_or_data_summary": "Flight-control source code and tuning notes",
            "destination_country": "US",
            "destination_company": "Falcon Embedded Systems",
            "end_use_summary": "Temporary software support for avionics sustainment",
            "end_user_name": "Falcon Embedded Systems",
            "access_context": "VPN source code access limited to named engineers only",
            "persons": [
                {
                    "name": "Arjun Rao",
                    "nationalities": ["IN"],
                    "employer": "Falcon Embedded Systems",
                    "role": "software engineer",
                    "item_classification": "3E001",
                    "access_level": "controlled_repo",
                }
            ],
            "notes": "Named engineers only. TTCP in place. Technology Control Plan approved. Access limited to the repository branch in scope.",
        }
    )

    ai = analyze_ambiguous_end_use(txn, auth)

    assert auth.combined_posture == "likely_exception_or_exemption"
    assert ai["proposed_posture"] == "likely_exception_or_exemption"
    assert "foreign_person_access" in ai["ambiguity_flags"]
    assert ai["missing_facts"] == []
    assert "deterministic posture should stand" in ai["explanation"].lower()
    assert build_hybrid_posture(auth, ai) == "likely_exception_or_exemption"
