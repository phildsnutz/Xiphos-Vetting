"""Shared workflow-control summaries for case UI and dossier output."""

from __future__ import annotations

from typing import Any


def _workflow_lane(
    vendor: dict[str, Any],
    *,
    cyber_summary: dict[str, Any] | None = None,
    export_summary: dict[str, Any] | None = None,
) -> str:
    vendor_input = vendor.get("vendor_input", {}) if isinstance(vendor.get("vendor_input"), dict) else {}
    profile = str(vendor_input.get("profile", vendor.get("profile", "")) or "").lower()
    has_export_lane = (
        isinstance(export_summary, dict)
        or isinstance(vendor_input.get("export_authorization"), dict)
        or profile == "itar_trade_compliance"
    )
    has_cyber_lane = (
        isinstance(cyber_summary, dict)
        and any(value not in (None, "", [], {}, False) for value in cyber_summary.values())
    ) or profile in {"supplier_cyber_trust", "cmmc_supplier_review"}
    if has_export_lane:
        return "export"
    if has_cyber_lane:
        return "cyber"
    return "counterparty"


def build_workflow_control_summary(
    vendor: dict[str, Any],
    *,
    foci_summary: dict[str, Any] | None = None,
    cyber_summary: dict[str, Any] | None = None,
    export_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lane = _workflow_lane(vendor, cyber_summary=cyber_summary, export_summary=export_summary)

    if lane == "export":
        export_summary = export_summary if isinstance(export_summary, dict) else {}
        has_request = bool(export_summary)
        has_artifact = bool(export_summary.get("artifact_id"))
        classification_display = str(export_summary.get("classification_display") or "").strip()
        missing_inputs: list[str] = []
        if not has_request:
            missing_inputs.append("Authorization request details")
        if not classification_display or classification_display == "Needs classification":
            missing_inputs.append("Confirmed jurisdiction or classification")
        if not has_artifact:
            missing_inputs.append("Customer export artifact or license history")

        support_level = (
            "artifact_backed"
            if has_artifact
            else "triage_only"
            if has_request
            else "awaiting_input"
        )
        label = (
            "Artifact-backed export review"
            if support_level == "artifact_backed"
            else "Rules-backed triage"
            if support_level == "triage_only"
            else "Awaiting request"
        )
        review_basis = (
            "BIS or DDTC rules guidance plus customer export artifacts and access-control evidence."
            if has_artifact
            else "BIS or DDTC rules guidance and case intake only."
            if has_request
            else "No export request has been captured yet."
        )
        return {
            "lane": lane,
            "support_level": support_level,
            "label": label,
            "review_basis": review_basis,
            "action_owner": "Trade compliance / export counsel",
            "decision_boundary": "Decision support for internal trade-compliance review. Not legal advice and not a government approval.",
            "missing_inputs": missing_inputs,
        }

    if lane == "cyber":
        cyber_summary = cyber_summary if isinstance(cyber_summary, dict) else {}
        has_sprs = bool(cyber_summary.get("sprs_artifact_id"))
        has_oscal = bool(cyber_summary.get("oscal_artifact_id"))
        has_nvd = bool(cyber_summary.get("nvd_artifact_id"))
        has_public_assurance = bool(cyber_summary.get("public_evidence_present"))
        evidence_count = sum(1 for present in (has_sprs, has_oscal, has_nvd) if present)
        missing_inputs: list[str] = []
        if not has_sprs:
            missing_inputs.append("Current SPRS export or attestation record")
        if not has_oscal:
            missing_inputs.append("Current SSP or POA&M artifact")
        if not has_nvd:
            missing_inputs.append("Product or platform vulnerability overlay")

        support_level = (
            "artifact_backed"
            if has_sprs and has_oscal
            else "partial"
            if evidence_count > 0 or has_public_assurance
            else "awaiting_input"
        )
        label = (
            "Artifact-backed supplier review"
            if support_level == "artifact_backed"
            else "Public and partial supplier evidence"
            if support_level == "partial" and has_public_assurance
            else "Partial supplier evidence"
            if support_level == "partial"
            else "Awaiting customer evidence"
        )
        review_basis = (
            "Supplier attestation, remediation artifacts, and vulnerability overlays are attached to the case."
            if support_level == "artifact_backed"
            else "First-party public assurance evidence is in view, but customer-controlled artifacts are still incomplete."
            if support_level == "partial" and has_public_assurance
            else "Some supplier cyber evidence is attached, but the review package is incomplete."
            if support_level == "partial"
            else "No customer-provided supplier cyber evidence is attached yet."
        )
        return {
            "lane": lane,
            "support_level": support_level,
            "label": label,
            "review_basis": review_basis,
            "action_owner": "Supply chain assurance / cyber office",
            "decision_boundary": "Supports supplier, software, and dependency assurance review. Does not replace independent certification, audit, or SSP validation.",
            "missing_inputs": missing_inputs,
        }

    foci_summary = foci_summary if isinstance(foci_summary, dict) else {}
    has_foci_artifact = bool(foci_summary.get("artifact_id"))
    foreign_interest = bool(
        foci_summary.get("foreign_interest_indicated")
        or foci_summary.get("declared_foreign_owner")
        or foci_summary.get("declared_foreign_country")
        or foci_summary.get("declared_foreign_ownership_pct")
    )
    mitigation_present = bool(
        foci_summary.get("mitigation_present")
        or foci_summary.get("declared_mitigation_type")
        or foci_summary.get("declared_mitigation_status")
    )
    missing_inputs = []
    if not has_foci_artifact:
        missing_inputs.append("Form 328, ownership chart, or mitigation package")
    elif foreign_interest and not mitigation_present:
        missing_inputs.append("Mitigation instrument or adjudication note")

    support_level = "artifact_backed" if has_foci_artifact else "triage_only"
    label = "Artifact-backed counterparty review" if has_foci_artifact else "Public-source triage"
    review_basis = (
        "Customer FOCI artifacts are attached alongside public-source ownership and relationship screening."
        if has_foci_artifact
        else "Public-source ownership, relationship, and screening data only."
    )
    return {
        "lane": lane,
        "support_level": support_level,
        "label": label,
        "review_basis": review_basis,
        "action_owner": "Industrial security / supply chain",
        "decision_boundary": "Supports internal award and hold decisions. Does not replace formal DCSA or legal adjudication.",
        "missing_inputs": missing_inputs,
    }
