"""Hybrid AI control-plane planner for Helios."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import re


_WHITESPACE_RE = re.compile(r"\s+")

TOOL_LIBRARY: dict[str, dict[str, str]] = {
    "case_snapshot": {
        "label": "Case snapshot",
        "surface": "case_detail",
        "mode": "read",
        "description": "Load the current case, score, and workflow posture.",
    },
    "supplier_passport": {
        "label": "Supplier passport",
        "surface": "supplier_passport",
        "mode": "read",
        "description": "Inspect control paths, identifiers, tribunal views, and provenance health.",
    },
    "graph_probe": {
        "label": "Graph probe",
        "surface": "graph",
        "mode": "read",
        "description": "Inspect graph density, relationship mix, and control-path reach.",
    },
    "network_risk": {
        "label": "Network risk",
        "surface": "graph",
        "mode": "read",
        "description": "Measure downstream exposure from linked entities.",
    },
    "enrichment_findings": {
        "label": "Enrichment findings",
        "surface": "enrichment",
        "mode": "read",
        "description": "Inspect raw findings, connector returns, and discovered identifiers.",
    },
    "identity_repair": {
        "label": "Identity repair",
        "surface": "identity",
        "mode": "review",
        "description": "Check for missing or weak identifiers before trusting the case.",
    },
    "export_guidance": {
        "label": "Export guidance",
        "surface": "export",
        "mode": "read",
        "description": "Inspect rules posture, AI challenge signals, and the final export next-step boundary.",
    },
    "cyber_evidence": {
        "label": "Supply chain assurance evidence",
        "surface": "cyber",
        "mode": "read",
        "description": "Inspect CMMC posture, SBOM or VEX gaps, CVE pressure, remediation evidence, and dependency signals.",
    },
    "person_screening": {
        "label": "Person screening",
        "surface": "export",
        "mode": "review",
        "description": "Run or inspect foreign-person and principal screening when needed.",
    },
    "monitoring_history": {
        "label": "Monitoring history",
        "surface": "monitoring",
        "mode": "read",
        "description": "Inspect prior changes, alerts, and monitoring cadence.",
    },
    "dossier": {
        "label": "Dossier builder",
        "surface": "dossier",
        "mode": "generate",
        "description": "Package the current case into an analyst or executive artifact.",
    },
}

PACK_LIBRARY: dict[str, dict[str, str]] = {
    "vesper": {
        "call_sign": "Vesper",
        "breed": "Dutch Shepherd",
        "role": "quarterback",
        "function": "mission_command",
        "summary": "Controls preflight, playbook selection, execution order, fallback handling, and stop conditions.",
    },
    "mako": {
        "call_sign": "Mako",
        "breed": "Belgian Malinois",
        "role": "collector",
        "function": "edge_collection",
        "summary": "Presses high-signal collectors, gap closure, and time-bounded evidence expansion at the edge.",
    },
    "bruno": {
        "call_sign": "Bruno",
        "breed": "Rottweiler",
        "role": "adjudicator",
        "function": "adverse_case_adjudication",
        "summary": "Treats contradictions, hidden-control pressure, and stop-case evidence with skepticism and force discipline.",
    },
    "sable": {
        "call_sign": "Sable",
        "breed": "Doberman",
        "role": "finisher",
        "function": "artifact_finish",
        "summary": "Converts the evidence state into a sharp analyst-facing brief without letting weak noise hijack the opening.",
    },
    "rex": {
        "call_sign": "Rex",
        "breed": "German Shepherd",
        "role": "generalist",
        "function": "balanced_fallback",
        "summary": "Provides balanced fallback coverage when the case does not justify a more specialized play.",
    },
}

EXECUTABLE_TOOL_IDS = frozenset(
    {
        "case_snapshot",
        "supplier_passport",
        "graph_probe",
        "network_risk",
        "enrichment_findings",
        "identity_repair",
        "export_guidance",
        "cyber_evidence",
        "person_screening",
        "monitoring_history",
    }
)

ASSISTANT_FEEDBACK_TYPES = frozenset(
    {
        "helpful",
        "objective_wrong",
        "tool_missing",
        "tool_noise",
        "missing_evidence",
        "wrong_explanation",
    }
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_prompt(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip()


def _has_phrase(text: str, phrase: str) -> bool:
    lowered = str(text or "").lower()
    target = str(phrase or "").lower().strip()
    if not target:
        return False
    if " " in target:
        return target in lowered
    return re.search(rf"\b{re.escape(target)}\b", lowered) is not None


def infer_objective(prompt: str) -> str:
    normalized = _normalize_prompt(prompt).lower()
    if any(_has_phrase(normalized, token) for token in ("control path", "ownership", "beneficial", "holding company", "pla", "owner")):
        return "trace_control_path"
    if any(_has_phrase(normalized, token) for token in ("export", "itar", "ear", "license", "foreign person", "destination")):
        return "export_review"
    if any(
        _has_phrase(normalized, token)
        for token in (
            "cyber",
            "cmmc",
            "cve",
            "kev",
            "firmware",
            "telecom",
            "network dependency",
            "sbom",
            "vex",
            "provenance",
            "dependency",
            "supply chain assurance",
        )
    ):
        return "cyber_investigation"
    if any(_has_phrase(normalized, token) for token in ("missing", "wrong", "outlier", "identity", "cage", "uei", "sam", "lei")):
        return "data_repair"
    if any(_has_phrase(normalized, token) for token in ("summary", "brief", "dossier", "executive")):
        return "executive_brief"
    if any(_has_phrase(normalized, token) for token in ("monitor", "changed", "drift", "watch")):
        return "monitor_change"
    return "explain_decision"


def _step(tool_id: str, reason: str, *, required: bool = True) -> dict[str, Any]:
    tool = TOOL_LIBRARY[tool_id]
    return {
        "tool_id": tool_id,
        "label": tool["label"],
        "surface": tool["surface"],
        "mode": tool["mode"],
        "description": tool["description"],
        "required": required,
        "reason": reason,
    }


def _anomaly_pressure(anomalies: list[dict[str, Any]]) -> str:
    high = sum(1 for item in anomalies if str(item.get("severity") or "").lower() == "high")
    medium = sum(1 for item in anomalies if str(item.get("severity") or "").lower() == "medium")
    if high >= 2 or (high >= 1 and medium >= 2):
        return "high"
    if high >= 1 or medium >= 2:
        return "medium"
    return "low"


def _resolve_workflow_lane(passport: dict[str, Any] | None, objective: str) -> str:
    workflow_lane = str((passport or {}).get("workflow_lane") or "").strip().lower()
    if workflow_lane:
        return workflow_lane
    if objective == "export_review":
        return "export_authorization"
    if objective == "cyber_investigation":
        return "supplier_cyber_trust"
    return "counterparty"


def _select_playbook(objective: str, anomalies: list[dict[str, Any]], supplier_passport: dict[str, Any] | None) -> dict[str, Any]:
    anomaly_codes = {str(item.get("code") or "") for item in anomalies}
    pressure = _anomaly_pressure(anomalies)
    lane = _resolve_workflow_lane(supplier_passport, objective)

    if objective == "trace_control_path":
        return {
            "playbook_id": "control_path_hardening",
            "label": "Control Path Hardening",
            "lane": lane,
            "style": "skeptical",
            "execution_mode": "escalated" if pressure != "low" else "standard",
            "lead": "vesper",
            "phases": ["preflight", "collect", "adjudicate", "package"],
            "success_condition": "Control-path pressure either resolves to a credible owner or is honestly left open.",
            "why_now": "The analyst is asking for hidden-control judgment, which requires tighter graph and ownership discipline than a generic explain flow.",
        }
    if objective == "data_repair":
        return {
            "playbook_id": "identity_repair_sprint",
            "label": "Identity Repair Sprint",
            "lane": lane,
            "style": "surgical",
            "execution_mode": "escalated" if "missing_core_identifiers" in anomaly_codes else "standard",
            "lead": "vesper",
            "phases": ["preflight", "collect", "repair", "re-score"],
            "success_condition": "Weak identifiers stop distorting the case and the next read is anchored to repaired identity.",
            "why_now": "The case is likely misbehaving because identity anchors or source matching are weak.",
        }
    if objective == "export_review":
        return {
            "playbook_id": "export_route_adjudication",
            "label": "Export Route Adjudication",
            "lane": lane,
            "style": "controlled",
            "execution_mode": "escalated" if "export_route_ambiguity" in anomaly_codes else "standard",
            "lead": "vesper",
            "phases": ["preflight", "collect", "adjudicate", "package"],
            "success_condition": "Route ambiguity, end-user ambiguity, and release conditions are explicit before any proceed posture is trusted.",
            "why_now": "Export cases fail when routing ambiguity hides inside an otherwise clean-looking authorization story.",
        }
    if objective == "cyber_investigation":
        return {
            "playbook_id": "assurance_pressure_thread",
            "label": "Assurance Pressure Thread",
            "lane": lane,
            "style": "pressure",
            "execution_mode": "escalated" if pressure == "high" else "standard",
            "lead": "vesper",
            "phases": ["preflight", "collect", "adjudicate", "package"],
            "success_condition": "Cyber, dependency, and provenance pressure are either corroborated, bounded, or explicitly unresolved.",
            "why_now": "Supply-chain assurance questions are usually weak-signal problems that need ordered pressure instead of one-shot explanation.",
        }
    if objective == "executive_brief":
        return {
            "playbook_id": "artifact_finish",
            "label": "Artifact Finish",
            "lane": lane,
            "style": "finish",
            "execution_mode": "standard",
            "lead": "sable",
            "phases": ["preflight", "adjudicate", "package"],
            "success_condition": "The brief opens with the judgment that matters and does not let weak residue dominate the artifact.",
            "why_now": "The request is brief-heavy, so Helios should package rather than keep expanding the search surface.",
        }
    if objective == "monitor_change":
        return {
            "playbook_id": "drift_scan",
            "label": "Drift Scan",
            "lane": lane,
            "style": "watchful",
            "execution_mode": "standard",
            "lead": "rex",
            "phases": ["preflight", "collect", "adjudicate"],
            "success_condition": "Only changes that materially alter the trust picture are escalated.",
            "why_now": "Monitoring work should stay light unless the drift actually changes the judgment.",
        }
    return {
        "playbook_id": "balanced_explanation",
        "label": "Balanced Explanation",
        "lane": lane,
        "style": "balanced",
        "execution_mode": "standard" if pressure == "low" else "escalated",
        "lead": "rex",
        "phases": ["preflight", "collect", "adjudicate", "package"],
        "success_condition": "The answer is grounded in the best available evidence bundle without pretending the case is cleaner than it is.",
        "why_now": "This is a general analytical request that still needs explicit guardrails and task ownership.",
    }


def _pack_lineup(playbook: dict[str, Any], anomalies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pressure = _anomaly_pressure(anomalies)
    lineup = [
        {**PACK_LIBRARY["vesper"], "active": True, "duty": "Call the play, set budgets, and decide when enough is enough."},
        {**PACK_LIBRARY["mako"], "active": True, "duty": "Drive high-signal collection and close the most valuable evidence gaps first."},
        {**PACK_LIBRARY["bruno"], "active": pressure != "low" or playbook.get("style") in {"skeptical", "pressure"}, "duty": "Challenge contradictions, hidden-control pressure, and stop-case evidence."},
        {**PACK_LIBRARY["sable"], "active": playbook.get("phases", [])[-1:] == ["package"] or playbook.get("lead") == "sable", "duty": "Finish the artifact so the opening tells the operator what matters."},
        {**PACK_LIBRARY["rex"], "active": True, "duty": "Carry balanced fallback coverage when the case does not justify more specialized aggression."},
    ]
    return lineup


def _step_owner(tool_id: str, objective: str) -> tuple[str, str, str]:
    if tool_id in {"case_snapshot", "monitoring_history"}:
        return "vesper", PACK_LIBRARY["vesper"]["call_sign"], "preflight"
    if tool_id in {"identity_repair", "enrichment_findings", "person_screening"}:
        return "mako", PACK_LIBRARY["mako"]["call_sign"], "collect"
    if tool_id in {"graph_probe", "network_risk", "supplier_passport", "export_guidance", "cyber_evidence"}:
        pack_id = "bruno" if objective in {"trace_control_path", "export_review", "cyber_investigation"} else "rex"
        phase = "adjudicate" if pack_id == "bruno" else "collect"
        return pack_id, PACK_LIBRARY[pack_id]["call_sign"], phase
    if tool_id == "dossier":
        return "sable", PACK_LIBRARY["sable"]["call_sign"], "package"
    return "rex", PACK_LIBRARY["rex"]["call_sign"], "collect"


def _assign_pack_owners(plan_steps: list[dict[str, Any]], objective: str) -> list[dict[str, Any]]:
    owned_steps: list[dict[str, Any]] = []
    for step in plan_steps:
        pack_id, pack_name, phase = _step_owner(str(step.get("tool_id") or ""), objective)
        enriched = dict(step)
        enriched["pack_id"] = pack_id
        enriched["pack_name"] = pack_name
        enriched["phase"] = phase
        owned_steps.append(enriched)
    return owned_steps


def _operator_brief(vendor_name: str, playbook: dict[str, Any], anomalies: list[dict[str, Any]]) -> str:
    pressure = _anomaly_pressure(anomalies)
    lead_name = PACK_LIBRARY[str(playbook.get("lead") or "vesper")]["call_sign"]
    if pressure == "high":
        return (
            f"{lead_name} is running an escalated {playbook['label'].lower()} on {vendor_name}. "
            "The case has enough pressure that Helios should act like a mission team, not a search box."
        )
    return (
        f"{lead_name} is running the {playbook['label'].lower()} on {vendor_name}. "
        "Helios will keep the run disciplined, visible, and bounded to what changes the judgment."
    )


def _operator_updates(playbook: dict[str, Any], anomalies: list[dict[str, Any]]) -> list[str]:
    updates = [
        f"Preflight selected `{playbook['playbook_id']}` because {str(playbook.get('why_now') or '').rstrip('.')}.",
        f"Execution mode is `{playbook['execution_mode']}` with `{_anomaly_pressure(anomalies)}` anomaly pressure.",
        f"Success condition: {str(playbook.get('success_condition') or '').rstrip('.')}.",
    ]
    if anomalies:
        lead = anomalies[0]
        updates.append(f"Top pressure point: {str(lead.get('message') or '').rstrip('.')}.")
    return updates[:4]


def _identity_anomalies(passport: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(passport, dict):
        return [{"code": "passport_missing", "severity": "high", "message": "Supplier passport is unavailable for this case."}]

    identifiers = (passport.get("identity") or {}).get("identifiers") or {}
    official = (passport.get("identity") or {}).get("official_corroboration") or {}
    core_fields = ["cage", "uei", "lei"]
    missing = [field for field in core_fields if not identifiers.get(field)]
    anomalies: list[dict[str, Any]] = []
    if missing:
        anomalies.append(
            {
                "code": "missing_core_identifiers",
                "severity": "high" if len(missing) >= 2 else "medium",
                "message": f"Core identity anchors missing: {', '.join(missing).upper()}",
            }
        )
    if int((passport.get("identity") or {}).get("connectors_with_data") or 0) < 3:
        anomalies.append(
            {
                "code": "thin_identity_coverage",
                "severity": "medium",
                "message": "Connector coverage is thin enough that identity certainty may be overstated.",
            }
        )
    coverage_level = str(official.get("coverage_level") or "").lower()
    if coverage_level in {"public_only", "missing"} and identifiers:
        anomalies.append(
            {
                "code": "official_corroboration_thin",
                "severity": "medium",
                "message": "Identity is leaning on public capture without strong official-source corroboration.",
            }
        )
    if int(official.get("blocked_connector_count") or 0) > 0:
        anomalies.append(
            {
                "code": "official_connector_blocked",
                "severity": "medium",
                "message": f"{int(official.get('blocked_connector_count') or 0)} official connector checks were blocked or throttled.",
            }
        )
    return anomalies


def _graph_anomalies(passport: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(passport, dict):
        return []
    graph = passport.get("graph") or {}
    claim_health = graph.get("claim_health") or {}
    intelligence = graph.get("intelligence") if isinstance(graph.get("intelligence"), dict) else {}
    anomalies: list[dict[str, Any]] = []
    if int(graph.get("relationship_count") or 0) < 3:
        anomalies.append(
            {
                "code": "thin_graph",
                "severity": "medium",
                "message": "Graph density is still thin and may miss hidden-control paths.",
            }
        )
    if int(claim_health.get("contradicted_claims") or 0) > 0:
        anomalies.append(
            {
                "code": "contradicted_claims",
                "severity": "high",
                "message": f"{int(claim_health.get('contradicted_claims') or 0)} contradictory control-path claims need review.",
            }
        )
    if int(claim_health.get("stale_paths") or 0) > 0:
        anomalies.append(
            {
                "code": "stale_control_paths",
                "severity": "medium",
                "message": f"{int(claim_health.get('stale_paths') or 0)} control paths are stale and should be refreshed.",
            }
        )
    if len(graph.get("control_paths") or []) == 0:
        anomalies.append(
            {
                "code": "no_control_paths",
                "severity": "medium",
                "message": "No control-path edges are captured yet.",
            }
        )
    missing_edge_families = intelligence.get("missing_required_edge_families") if isinstance(intelligence.get("missing_required_edge_families"), list) else []
    if missing_edge_families:
        anomalies.append(
            {
                "code": "missing_graph_edge_families",
                "severity": "high" if len(missing_edge_families) >= 2 else "medium",
                "message": "Required graph edge families are missing for this lane: "
                + ", ".join(str(item).replace("_", " ") for item in missing_edge_families[:4]),
            }
        )
    if float(intelligence.get("claim_coverage_pct") or 0.0) < 0.5 and int(graph.get("relationship_count") or 0) > 0:
        anomalies.append(
            {
                "code": "graph_claim_coverage_thin",
                "severity": "medium",
                "message": "Too many graph edges are not backed by scoped claim records yet.",
            }
        )
    if int(intelligence.get("legacy_unscoped_edge_count") or 0) > 0:
        anomalies.append(
            {
                "code": "legacy_graph_edges",
                "severity": "medium",
                "message": f"{int(intelligence.get('legacy_unscoped_edge_count') or 0)} legacy unscoped graph edge(s) are still present.",
            }
        )
    return anomalies


def _oci_anomalies(passport: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(passport, dict):
        return []
    ownership = passport.get("ownership") or {}
    profile = ownership.get("profile") if isinstance(ownership.get("profile"), dict) else {}
    oci = ownership.get("oci") if isinstance(ownership.get("oci"), dict) else {}
    graph = passport.get("graph") or {}
    anomalies: list[dict[str, Any]] = []

    shell_layers = int(profile.get("shell_layers") or 0)
    pep_connection = bool(profile.get("pep_connection"))
    ownership_resolution_pct = float(oci.get("ownership_resolution_pct") or 0.0)
    control_resolution_pct = float(oci.get("control_resolution_pct") or 0.0)
    named_owner_known = bool(oci.get("named_beneficial_owner_known"))
    descriptor_only = bool(oci.get("descriptor_only"))
    control_paths = graph.get("control_paths") or []

    if descriptor_only:
        anomalies.append(
            {
                "code": "descriptor_only_ownership",
                "severity": "medium",
                "message": "Ownership evidence is descriptor-only and still lacks a named beneficial owner.",
            }
        )
    if not named_owner_known and ownership_resolution_pct < 0.65:
        anomalies.append(
            {
                "code": "named_owner_unresolved",
                "severity": "high" if shell_layers >= 2 or pep_connection else "medium",
                "message": "Named beneficial ownership remains unresolved at the current evidence depth.",
            }
        )
    if control_resolution_pct < 0.5 or not control_paths:
        anomalies.append(
            {
                "code": "thin_control_resolution",
                "severity": "medium",
                "message": "Control-path resolution is still too thin to treat hidden-control risk as closed.",
            }
        )
    if shell_layers >= 2:
        anomalies.append(
            {
                "code": "layered_shell_risk",
                "severity": "high" if shell_layers >= 3 else "medium",
                "message": f"Ownership profile shows {shell_layers} shell layers, which increases concealment pressure.",
            }
        )
    if pep_connection:
        anomalies.append(
            {
                "code": "pep_control_overlap",
                "severity": "high",
                "message": "PEP-linked ownership or control pressure is present and should not be treated as routine.",
            }
        )
    return anomalies


def _cyber_anomalies(passport: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(passport, dict):
        return []
    cyber = passport.get("cyber") or {}
    threat = passport.get("threat_intel") or {}
    anomalies: list[dict[str, Any]] = []

    threat_pressure = str(threat.get("threat_pressure") or cyber.get("threat_pressure") or "").lower()
    advisory_count = len(threat.get("cisa_advisory_ids") or cyber.get("cisa_advisory_ids") or [])
    technique_count = len(threat.get("attack_technique_ids") or cyber.get("attack_technique_ids") or [])
    open_source_risk_level = str(cyber.get("open_source_risk_level") or "").lower()
    open_source_advisories = int(cyber.get("open_source_advisory_count") or 0)
    low_score_repos = int(cyber.get("scorecard_low_repo_count") or 0)

    if threat_pressure == "high":
        anomalies.append(
            {
                "code": "high_threat_pressure",
                "severity": "medium",
                "message": f"Shared threat intelligence maps {technique_count} ATT&CK techniques and {advisory_count} active CISA advisories to this case context.",
            }
        )
    elif threat_pressure == "medium" and (advisory_count > 0 or technique_count > 0):
        anomalies.append(
            {
                "code": "active_threat_signal",
                "severity": "low",
                "message": f"Threat-intel signal is present with {technique_count} ATT&CK techniques and {advisory_count} CISA advisories in scope.",
            }
        )
    if open_source_risk_level in {"medium", "high"} and open_source_advisories > 0:
        anomalies.append(
            {
                "code": "open_source_pressure",
                "severity": "medium" if open_source_risk_level == "high" else "low",
                "message": f"Open-source package exposure is {open_source_risk_level} with {open_source_advisories} advisories requiring triage.",
            }
        )
    if low_score_repos > 0:
        anomalies.append(
            {
                "code": "repository_hygiene_pressure",
                "severity": "low",
                "message": f"{low_score_repos} source repositories are failing hygiene thresholds.",
            }
        )
    return anomalies


def _lane_anomalies(passport: dict[str, Any] | None, objective: str) -> list[dict[str, Any]]:
    if not isinstance(passport, dict):
        return []
    anomalies: list[dict[str, Any]] = []
    workflow_lane = str(passport.get("workflow_lane") or "").strip().lower()
    export_summary = passport.get("export") if isinstance(passport.get("export"), dict) else {}
    cyber_summary = passport.get("cyber") if isinstance(passport.get("cyber"), dict) else {}
    if objective == "export_review" and not export_summary:
        anomalies.append(
            {
                "code": "missing_export_evidence",
                "severity": "high",
                "message": "Export evidence is missing for an export-focused request.",
            }
        )
    if objective == "cyber_investigation" and not cyber_summary:
        anomalies.append(
            {
                "code": "missing_cyber_evidence",
                "severity": "high",
                "message": "Supply chain assurance evidence is missing for this supplier-focused request.",
            }
        )
    if workflow_lane == "supplier_cyber_trust":
        has_cyber_signal = any(
            cyber_summary.get(key) not in (None, "", [], {}, False, 0)
            for key in (
                "artifact_sources",
                "sprs_artifact_id",
                "oscal_artifact_id",
                "nvd_artifact_id",
                "current_cmmc_level",
                "assessment_status",
                "total_control_references",
                "high_or_critical_cve_count",
                "critical_cve_count",
                "kev_flagged_cve_count",
            )
        )
        if not has_cyber_signal:
            anomalies.append(
                {
                    "code": "missing_cyber_evidence",
                    "severity": "high",
                    "message": "Cyber lane is active but no meaningful assurance evidence is attached yet.",
                }
            )
    if workflow_lane == "export_authorization":
        has_export_signal = any(
            export_summary.get(key) not in (None, "", [], {}, False, 0)
            for key in (
                "posture",
                "recommended_next_step",
                "official_references",
                "artifact_id",
                "classification_display",
                "destination_country",
            )
        )
        if not has_export_signal:
            anomalies.append(
                {
                    "code": "missing_export_evidence",
                    "severity": "high",
                    "message": "Export lane is active but the authorization evidence package is still thin.",
                }
            )
        export_text = " ".join(
            [
                str(export_summary.get("reason_summary") or ""),
                str(export_summary.get("recommended_next_step") or ""),
                str(export_summary.get("narrative") or ""),
                str(export_summary.get("destination_company") or ""),
                str(export_summary.get("end_use_summary") or ""),
                str(export_summary.get("access_context") or ""),
                str(export_summary.get("notes") or ""),
            ]
        ).lower()
        if any(
            token in export_text
            for token in (
                "onward delivery",
                "reseller",
                "ultimate consignee",
                "not yet resolved",
                "staging",
                "transshipment",
                "re-export",
                "reexport",
                "unknown end user",
            )
        ):
            anomalies.append(
                {
                    "code": "export_route_ambiguity",
                    "severity": "high",
                    "message": "Export narrative still shows routing or end-user ambiguity that needs analyst review.",
                }
            )
    return anomalies


def _plan_steps(objective: str, anomalies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [_step("case_snapshot", "Load the current case before any deeper branch.")]
    if objective == "trace_control_path":
        steps.extend(
            [
                _step("supplier_passport", "Pull the trust artifact with tribunal, control paths, and provenance health."),
                _step("graph_probe", "Inspect ownership, intermediary, and subsystem adjacency."),
                _step("network_risk", "Measure whether the path materially changes disposition."),
                _step("enrichment_findings", "Cross-check the raw evidence behind the graph path.", required=False),
            ]
        )
    elif objective == "data_repair":
        steps.extend(
            [
                _step("enrichment_findings", "Inspect identifier findings and connector returns."),
                _step("identity_repair", "Check whether missing anchors or false matches are driving the outlier."),
                _step("supplier_passport", "Re-evaluate posture after identity certainty is known."),
                _step("graph_probe", "Check whether graph thinness is the real problem.", required=False),
            ]
        )
    elif objective == "export_review":
        steps.extend(
            [
                _step("export_guidance", "Inspect request posture and next-step boundary."),
                _step("supplier_passport", "Check ownership, control, and control-path signals that affect export risk."),
                _step("person_screening", "Screen principals or foreign persons if access or release is in scope.", required=False),
            ]
        )
    elif objective == "cyber_investigation":
        steps.extend(
            [
                _step("cyber_evidence", "Inspect readiness, provenance, remediation, and vulnerability pressure."),
                _step("supplier_passport", "Check whether software, firmware, or dependency pressure compounds ownership or intermediary risk."),
                _step("graph_probe", "Trace supplier, software, and service dependencies through the graph.", required=False),
            ]
        )
    elif objective == "executive_brief":
        steps.extend(
            [
                _step("supplier_passport", "Anchor the brief in a portable trust artifact."),
                _step("dossier", "Package the case into a shareable artifact."),
            ]
        )
    elif objective == "monitor_change":
        steps.extend(
            [
                _step("monitoring_history", "Check what changed and when."),
                _step("supplier_passport", "Check whether the current trust artifact still holds."),
            ]
        )
    else:
        steps.extend(
            [
                _step("supplier_passport", "Pull the best current explanation artifact."),
                _step("network_risk", "Check whether graph pressure is changing the story.", required=False),
                _step("enrichment_findings", "Cross-check the top evidence for the answer.", required=False),
            ]
        )

    anomaly_codes = {item["code"] for item in anomalies}
    if "missing_core_identifiers" in anomaly_codes and objective != "data_repair":
        steps.append(_step("identity_repair", "Missing core identifiers should be checked before treating the answer as final.", required=False))
    if "thin_graph" in anomaly_codes and objective != "trace_control_path":
        steps.append(_step("graph_probe", "The graph is thin enough that hidden-control risk may be understated.", required=False))
    return steps


def build_case_assistant_plan(
    *,
    case_id: str,
    analyst_prompt: str,
    vendor: dict[str, Any] | None,
    score: dict[str, Any] | None = None,
    enrichment: dict[str, Any] | None = None,
    supplier_passport: dict[str, Any] | None = None,
    storyline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_prompt = _normalize_prompt(analyst_prompt)
    objective = infer_objective(normalized_prompt)
    anomalies = [
        *_identity_anomalies(supplier_passport),
        *_graph_anomalies(supplier_passport),
        *_oci_anomalies(supplier_passport),
        *_cyber_anomalies(supplier_passport),
        *_lane_anomalies(supplier_passport, objective),
    ]
    playbook = _select_playbook(objective, anomalies, supplier_passport)
    plan = _assign_pack_owners(_plan_steps(objective, anomalies), objective)
    tribunal = ((supplier_passport or {}).get("tribunal") or {}) if isinstance(supplier_passport, dict) else {}
    graph = ((supplier_passport or {}).get("graph") or {}) if isinstance(supplier_passport, dict) else {}
    pack = _pack_lineup(playbook, anomalies)
    quarterback = dict(PACK_LIBRARY["vesper"])
    preflight = {
        "workflow_lane": _resolve_workflow_lane(supplier_passport, objective),
        "anomaly_pressure": _anomaly_pressure(anomalies),
        "execution_mode": playbook.get("execution_mode"),
        "human_gate_required": True,
        "degraded_mode": any(str(item.get("code") or "") in {"official_connector_blocked", "missing_export_evidence", "missing_cyber_evidence"} for item in anomalies),
    }

    return {
        "version": "ai-control-plane-v1",
        "generated_at": _utc_now_iso(),
        "case_id": case_id,
        "vendor_name": str((vendor or {}).get("name") or ""),
        "analyst_prompt": normalized_prompt,
        "objective": objective,
        "current_posture": str((supplier_passport or {}).get("posture") or ""),
        "recommended_view": tribunal.get("recommended_view"),
        "consensus_level": tribunal.get("consensus_level"),
        "quarterback": quarterback,
        "playbook": playbook,
        "preflight": preflight,
        "pack": pack,
        "operator_brief": _operator_brief(str((vendor or {}).get("name") or "this case"), playbook, anomalies),
        "operator_updates": _operator_updates(playbook, anomalies),
        "anomalies": anomalies,
        "plan": plan,
        "context_snapshot": {
            "tier": str(((score or {}).get("calibrated") or {}).get("calibrated_tier") or ""),
            "findings_total": int(((enrichment or {}).get("summary") or {}).get("findings_total") or 0),
            "control_path_count": len(graph.get("control_paths") or []),
            "contradicted_claims": int((graph.get("claim_health") or {}).get("contradicted_claims") or 0),
        },
        "guardrails": [
            "Vesper owns the play call, but analyst approval still gates any execution or mutation.",
            "Show the analyst the plan before any live mutation or rerun.",
            "Never suppress missing-data or connector-gap warnings from the analyst.",
            "Do not auto-rerun live sources or mutate case state without explicit analyst approval.",
            "Cowork may diagnose and propose a fix, but production mutation remains human-gated.",
        ],
        "suggested_followups": [
            "Why is this case blocked right now?",
            "Show the strongest control path with evidence.",
            "Tell me which missing identifiers would most change the decision.",
        ],
        "storyline_available": bool((storyline or {}).get("cards")),
    }


def prepare_case_assistant_execution(
    plan_steps: list[dict[str, Any]],
    approved_tool_ids: list[str] | tuple[str, ...] | None,
) -> tuple[list[str], list[dict[str, Any]]]:
    planned = {str(step.get("tool_id") or "") for step in plan_steps}
    approved = [str(tool_id or "").strip() for tool_id in (approved_tool_ids or []) if str(tool_id or "").strip()]

    executable: list[str] = []
    blocked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool_id in approved:
        if tool_id in seen:
            continue
        seen.add(tool_id)
        if tool_id not in planned:
            blocked.append(
                {
                    "tool_id": tool_id,
                    "reason": "not_in_plan",
                    "message": "Tool was not part of the current assistant plan.",
                }
            )
            continue
        if tool_id not in EXECUTABLE_TOOL_IDS:
            blocked.append(
                {
                    "tool_id": tool_id,
                    "reason": "approval_boundary",
                    "message": "Tool is outside the current approved execution boundary.",
                }
            )
            continue
        executable.append(tool_id)
    return executable, blocked


def prepare_case_assistant_feedback(
    *,
    prompt: str,
    objective: str,
    verdict: str,
    feedback_type: str,
    comment: str = "",
    approved_tool_ids: list[str] | tuple[str, ...] | None = None,
    executed_tool_ids: list[str] | tuple[str, ...] | None = None,
    suggested_tool_ids: list[str] | tuple[str, ...] | None = None,
    anomaly_codes: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    normalized_prompt = _normalize_prompt(prompt)
    normalized_comment = _normalize_prompt(comment)
    normalized_verdict = str(verdict or "").strip().lower()
    normalized_feedback_type = str(feedback_type or "").strip().lower()

    if normalized_verdict not in {"accepted", "partial", "rejected"}:
        raise ValueError("verdict must be accepted, partial, or rejected")
    if normalized_feedback_type not in ASSISTANT_FEEDBACK_TYPES:
        raise ValueError("feedback_type is not supported")

    approved = [str(item).strip() for item in (approved_tool_ids or []) if str(item).strip()]
    executed = [str(item).strip() for item in (executed_tool_ids or []) if str(item).strip()]
    suggested = [str(item).strip() for item in (suggested_tool_ids or []) if str(item).strip()]
    anomalies = [str(item).strip() for item in (anomaly_codes or []) if str(item).strip()]

    category = "general"
    severity = "low"
    if normalized_feedback_type in {"tool_missing", "missing_evidence"}:
        category = "request"
        severity = "high" if normalized_verdict == "rejected" else "medium"
    elif normalized_feedback_type in {"objective_wrong", "tool_noise"}:
        category = "confusion"
        severity = "high" if normalized_verdict == "rejected" else "medium"
    elif normalized_feedback_type == "wrong_explanation":
        category = "bug"
        severity = "high" if normalized_verdict != "accepted" else "medium"

    if normalized_verdict == "accepted" and normalized_feedback_type == "helpful":
        summary = f"Assistant flow accepted for {objective.replace('_', ' ')}"
    elif normalized_feedback_type == "tool_missing":
        missing = ", ".join(suggested[:3]) if suggested else "additional tools"
        summary = f"Assistant plan missed {missing}"
    elif normalized_feedback_type == "tool_noise":
        noisy = ", ".join(approved[:3]) if approved else "selected tools"
        summary = f"Assistant plan included noisy tools: {noisy}"
    elif normalized_feedback_type == "objective_wrong":
        summary = f"Assistant picked the wrong objective for {objective.replace('_', ' ')}"
    elif normalized_feedback_type == "missing_evidence":
        summary = "Assistant answer lacked the evidence needed for analyst trust"
    else:
        summary = "Assistant explanation did not hold up under analyst review"

    details_parts = [
        f"Prompt: {normalized_prompt}" if normalized_prompt else "",
        f"Objective: {objective}",
        f"Verdict: {normalized_verdict}",
        f"Feedback type: {normalized_feedback_type}",
        f"Approved tools: {', '.join(approved)}" if approved else "",
        f"Executed tools: {', '.join(executed)}" if executed else "",
        f"Suggested tools: {', '.join(suggested)}" if suggested else "",
        f"Anomalies: {', '.join(anomalies)}" if anomalies else "",
        f"Analyst comment: {normalized_comment}" if normalized_comment else "",
    ]
    details = "\n".join(part for part in details_parts if part)

    training_signal = {
        "version": "assistant-feedback-v1",
        "captured_at": _utc_now_iso(),
        "objective": objective,
        "verdict": normalized_verdict,
        "feedback_type": normalized_feedback_type,
        "approved_tool_ids": approved,
        "executed_tool_ids": executed,
        "suggested_tool_ids": suggested,
        "anomaly_codes": anomalies,
        "comment": normalized_comment,
    }

    return {
        "category": category,
        "severity": severity,
        "summary": summary[:240],
        "details": details[:4000],
        "training_signal": training_signal,
    }
