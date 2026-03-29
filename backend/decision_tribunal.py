"""Deterministic multi-view decision tribunal for supplier trust decisions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


_VIEW_ORDER = {"deny": 0, "watch": 1, "approve": 2}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clamp(value: float, floor: float = 0.0, ceiling: float = 1.0) -> float:
    return max(floor, min(ceiling, value))


def _tier_band(tier: str) -> str:
    normalized = str(tier or "").upper()
    if normalized.startswith("TIER_1"):
        return "critical"
    if normalized.startswith("TIER_2"):
        return "elevated"
    if normalized.startswith("TIER_3"):
        return "conditional"
    return "clear"


def _signal_packet(
    *,
    posture: str,
    score: dict | None,
    latest_decision: dict | None,
    workflow_control: dict | None,
    network_risk: dict | None,
    control_paths: list[dict[str, Any]] | None,
    claim_health: dict | None,
    foci_summary: dict | None,
    cyber_summary: dict | None,
    export_summary: dict | None,
    identity: dict | None,
) -> dict[str, Any]:
    calibrated = (score or {}).get("calibrated") or {}
    latest_decision_value = str((latest_decision or {}).get("decision") or "").lower()
    connector_coverage = int((identity or {}).get("connectors_with_data") or 0)
    identifiers = (identity or {}).get("identifiers") or {}
    identifier_count = sum(
        1 for value in identifiers.values() if value not in (None, "", [], {})
    )
    control_paths = [row for row in (control_paths or []) if isinstance(row, dict)]
    control_path_count = len(control_paths)
    ownership_path_count = sum(
        1
        for row in control_paths
        if str(row.get("rel_type") or "") in {"owned_by", "beneficially_owned_by"}
    )
    intermediary_path_count = sum(
        1
        for row in control_paths
        if str(row.get("rel_type") or "") in {
            "routes_payment_through",
            "depends_on_network",
            "depends_on_service",
            "distributed_by",
            "operates_facility",
            "ships_via",
        }
    )

    export_posture = str((export_summary or {}).get("posture") or "").lower()
    required_level = 2 if str((score or {}).get("profile") or "").lower() == "defense_acquisition" else 0
    current_level = int((cyber_summary or {}).get("current_cmmc_level") or 0)
    critical_cves = int(
        (cyber_summary or {}).get("critical_cve_count")
        or (cyber_summary or {}).get("high_or_critical_cve_count")
        or 0
    )
    kev_count = int((cyber_summary or {}).get("kev_flagged_cve_count") or 0)
    poam_active = bool((cyber_summary or {}).get("poam_active"))
    cyber_gap = (
        (required_level > 0 and current_level > 0 and current_level < required_level)
        or poam_active
        or critical_cves > 0
        or kev_count > 0
    )

    foreign_interest = bool((foci_summary or {}).get("foreign_interest_indicated"))
    mitigation_present = bool((foci_summary or {}).get("mitigation_present"))
    foreign_control_risk = foreign_interest and not mitigation_present
    mitigated_foreign_interest = foreign_interest and mitigation_present

    network_score = float((network_risk or {}).get("score") or 0.0)
    network_level = str((network_risk or {}).get("level") or "none").lower()

    claim_health = claim_health or {}
    contradicted_path_count = int(claim_health.get("contradicted_claims") or 0)
    stale_path_count = int(claim_health.get("stale_paths") or 0)
    corroborated_path_count = int(claim_health.get("corroborated_paths") or 0)

    return {
        "posture": str(posture or "pending").lower(),
        "tier_band": _tier_band(str(calibrated.get("calibrated_tier") or "")),
        "hard_stop": bool((score or {}).get("is_hard_stop") or str(posture or "").lower() == "blocked"),
        "latest_decision": latest_decision_value,
        "connector_coverage": connector_coverage,
        "identifier_count": identifier_count,
        "control_path_count": control_path_count,
        "ownership_path_count": ownership_path_count,
        "intermediary_path_count": intermediary_path_count,
        "contradicted_path_count": contradicted_path_count,
        "stale_path_count": stale_path_count,
        "corroborated_path_count": corroborated_path_count,
        "network_score": network_score,
        "network_level": network_level,
        "foreign_control_risk": foreign_control_risk,
        "mitigated_foreign_interest": mitigated_foreign_interest,
        "export_prohibited": export_posture == "likely_prohibited",
        "export_review_required": export_posture in {
            "likely_license_required",
            "insufficient_confidence",
            "escalate",
        },
        "cyber_gap": cyber_gap,
        "critical_cves": critical_cves,
        "kev_count": kev_count,
        "workflow_owner": str((workflow_control or {}).get("action_owner") or "Analyst"),
        "workflow_basis": str((workflow_control or {}).get("review_basis") or ""),
    }


def _compose_view(
    *,
    stance: str,
    label: str,
    owner: str,
    signals: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    signal_keys: list[str] = []
    score = 0.0

    def add(condition: bool, weight: float, reason: str, signal_key: str) -> None:
        nonlocal score
        if not condition:
            return
        score += weight
        reasons.append(reason)
        signal_keys.append(signal_key)

    posture = str(signals.get("posture") or "pending")
    latest_decision = str(signals.get("latest_decision") or "")
    network_level = str(signals.get("network_level") or "none")
    network_score = float(signals.get("network_score") or 0.0)

    if stance == "approve":
        score = 0.18
        add(posture == "approved", 0.28, "Primary posture already lands in approve territory.", "approved_posture")
        add(latest_decision == "approve", 0.12, "Latest analyst decision aligns with approval.", "analyst_approve")
        add(not signals["hard_stop"], 0.08, "No hard-stop is active.", "no_hard_stop")
        add(not signals["export_prohibited"] and not signals["export_review_required"], 0.08, "Export lane does not currently force additional review.", "export_clear")
        add(not signals["cyber_gap"], 0.06, "Cyber evidence does not show an active readiness gap.", "cyber_clear")
        add(signals["identifier_count"] >= 2, 0.05, "Identifier anchors are strong enough to trust the entity match.", "identifier_depth")
        add(signals["connector_coverage"] >= 4, 0.05, "Connector coverage is broad enough to support a cleaner decision.", "coverage_depth")
        add(signals["mitigated_foreign_interest"], 0.08, "Foreign-control evidence is disclosed and mitigated.", "ownership_mitigated")
        add(
            not signals["foreign_control_risk"] and not signals["mitigated_foreign_interest"],
            0.08,
            "Ownership and control evidence is currently clear.",
            "ownership_clear",
        )
        add(network_score <= 0.4 and network_level in {"none", "low"}, 0.08, "Network pressure is currently low.", "low_network_pressure")
        add(signals["contradicted_path_count"] == 0, 0.04, "No contradictory ownership or intermediary claims are present.", "no_contradictions")
        add(signals["stale_path_count"] == 0, 0.03, "Control-path evidence is fresh.", "fresh_control_paths")
        score -= 0.35 if signals["hard_stop"] else 0.0
        score -= 0.18 if signals["export_prohibited"] else 0.0
        score -= 0.12 if signals["foreign_control_risk"] else 0.0
        score -= 0.08 if signals["cyber_gap"] else 0.0
        score -= 0.08 if network_level in {"high", "critical"} else 0.0
    elif stance == "watch":
        score = 0.2
        add(posture in {"review", "pending"}, 0.24, "Current posture already requires conditions or analyst review.", "review_posture")
        add(latest_decision == "escalate", 0.12, "Latest analyst decision says escalate rather than clear.", "analyst_escalate")
        add(signals["export_review_required"], 0.18, "Export rules still require formal review.", "export_review")
        add(signals["cyber_gap"], 0.12, "Cyber evidence shows unresolved readiness or vulnerability pressure.", "cyber_gap")
        add(
            network_score > 0.4 or network_level in {"medium", "high", "critical"},
            0.12,
            "Network risk adds meaningful downstream pressure.",
            "network_pressure",
        )
        add(
            signals["control_path_count"] == 0 or signals["ownership_path_count"] == 0,
            0.08,
            "Control-path coverage is still thin and should be improved before a clean decision.",
            "thin_control_paths",
        )
        add(
            signals["foreign_control_risk"] or signals["mitigated_foreign_interest"],
            0.1,
            "Foreign-control evidence is present and still matters operationally.",
            "foreign_control_context",
        )
        add(signals["contradicted_path_count"] > 0, 0.08, "Some ownership or intermediary claims are contradictory.", "contradictory_claims")
        add(signals["stale_path_count"] > 0, 0.06, "Some control-path evidence is stale and should be refreshed.", "stale_claims")
        add(signals["intermediary_path_count"] > 0, 0.06, "Intermediaries are present and warrant watch conditions.", "intermediary_paths")
        score -= 0.32 if signals["foreign_control_risk"] and signals["cyber_gap"] and network_level in {"high", "critical"} else 0.0
        score -= 0.12 if signals["foreign_control_risk"] and signals["ownership_path_count"] > 0 and signals["intermediary_path_count"] > 0 else 0.0
        score -= 0.18 if signals["hard_stop"] else 0.0
        score -= 0.08 if posture == "approved" else 0.0
    else:
        score = 0.1
        add(signals["hard_stop"], 0.45, "A hard-stop or blocked posture is already active.", "hard_stop")
        add(latest_decision == "reject", 0.18, "Latest analyst decision already rejects the case.", "analyst_reject")
        add(signals["export_prohibited"], 0.18, "Export posture suggests the transaction is likely prohibited.", "export_prohibited")
        add(
            signals["foreign_control_risk"] and not signals["mitigated_foreign_interest"],
            0.14,
            "Foreign-control evidence is unresolved and unmitigated.",
            "foreign_control_risk",
        )
        add(
            signals["foreign_control_risk"] and signals["export_review_required"],
            0.1,
            "Ownership and export signals compound into a higher-control concern.",
            "compound_export_control",
        )
        add(
            network_level in {"high", "critical"} or network_score >= 2.5,
            0.12,
            "Network pressure is high enough to justify a deny posture.",
            "network_pressure",
        )
        add(
            signals["cyber_gap"] and (signals["critical_cves"] > 0 or signals["kev_count"] > 0),
            0.08,
            "Cyber evidence shows exploitable supplier pressure alongside unresolved controls.",
            "cyber_gap",
        )
        add(signals["contradicted_path_count"] >= 2, 0.05, "Contradictory control-path evidence lowers trust in the case.", "contradictory_claims")
        add(
            signals["intermediary_path_count"] > 0 and signals["ownership_path_count"] > 0,
            0.05,
            "Both control and intermediary paths are present, increasing hidden-control concern.",
            "compound_control_path",
        )
        score += 0.12 if signals["foreign_control_risk"] and signals["cyber_gap"] and network_level in {"high", "critical"} else 0.0
        score -= 0.16 if posture == "approved" else 0.0
        score -= 0.08 if signals["mitigated_foreign_interest"] else 0.0
        score -= 0.06 if not signals["cyber_gap"] and not signals["export_prohibited"] else 0.0

    score = _clamp(score)
    if not reasons:
        fallback = {
            "approve": "The available evidence does not currently justify escalation.",
            "watch": "The case still benefits from conditional handling and refresh discipline.",
            "deny": "The current evidence does not yet support a hard deny recommendation.",
        }
        reasons = [fallback[stance]]
        signal_keys = ["baseline"]

    return {
        "stance": stance,
        "label": label,
        "owner": owner,
        "score": round(score, 3),
        "summary": reasons[0],
        "reasons": reasons[:4],
        "signal_keys": signal_keys,
    }


def build_decision_tribunal_from_signals(signal_packet: dict[str, Any]) -> dict[str, Any]:
    signals = {
        "posture": str(signal_packet.get("posture") or "pending").lower(),
        "tier_band": str(signal_packet.get("tier_band") or "clear"),
        "hard_stop": bool(signal_packet.get("hard_stop")),
        "latest_decision": str(signal_packet.get("latest_decision") or ""),
        "connector_coverage": int(signal_packet.get("connector_coverage") or 0),
        "identifier_count": int(signal_packet.get("identifier_count") or 0),
        "control_path_count": int(signal_packet.get("control_path_count") or 0),
        "ownership_path_count": int(signal_packet.get("ownership_path_count") or 0),
        "intermediary_path_count": int(signal_packet.get("intermediary_path_count") or 0),
        "contradicted_path_count": int(signal_packet.get("contradicted_path_count") or 0),
        "stale_path_count": int(signal_packet.get("stale_path_count") or 0),
        "corroborated_path_count": int(signal_packet.get("corroborated_path_count") or 0),
        "network_score": float(signal_packet.get("network_score") or 0.0),
        "network_level": str(signal_packet.get("network_level") or "none").lower(),
        "foreign_control_risk": bool(signal_packet.get("foreign_control_risk")),
        "mitigated_foreign_interest": bool(signal_packet.get("mitigated_foreign_interest")),
        "export_prohibited": bool(signal_packet.get("export_prohibited")),
        "export_review_required": bool(signal_packet.get("export_review_required")),
        "cyber_gap": bool(signal_packet.get("cyber_gap")),
        "critical_cves": int(signal_packet.get("critical_cves") or 0),
        "kev_count": int(signal_packet.get("kev_count") or 0),
        "workflow_owner": str(signal_packet.get("workflow_owner") or "Analyst"),
        "workflow_basis": str(signal_packet.get("workflow_basis") or ""),
    }

    views = [
        _compose_view(stance="deny", label="Deny / Block", owner="Compliance lead", signals=signals),
        _compose_view(stance="watch", label="Watch / Conditional", owner=signals["workflow_owner"], signals=signals),
        _compose_view(stance="approve", label="Approve / Proceed", owner="Program / procurement", signals=signals),
    ]
    ordered = sorted(views, key=lambda item: (-float(item["score"]), _VIEW_ORDER[item["stance"]]))
    recommended = ordered[0]
    runner_up = ordered[1]
    gap = round(float(recommended["score"]) - float(runner_up["score"]), 3)
    consensus = "strong" if gap >= 0.2 else "moderate" if gap >= 0.1 else "contested"

    return {
        "version": "decision-tribunal-v1",
        "generated_at": _utc_now_iso(),
        "recommended_view": recommended["stance"],
        "recommended_label": recommended["label"],
        "consensus_level": consensus,
        "decision_gap": gap,
        "signal_snapshot": signals,
        "views": ordered,
    }


def build_decision_tribunal(
    *,
    posture: str,
    score: dict | None,
    latest_decision: dict | None = None,
    workflow_control: dict | None = None,
    network_risk: dict | None = None,
    control_paths: list[dict[str, Any]] | None = None,
    claim_health: dict | None = None,
    foci_summary: dict | None = None,
    cyber_summary: dict | None = None,
    export_summary: dict | None = None,
    identity: dict | None = None,
) -> dict[str, Any]:
    signals = _signal_packet(
        posture=posture,
        score=score,
        latest_decision=latest_decision,
        workflow_control=workflow_control,
        network_risk=network_risk,
        control_paths=control_paths,
        claim_health=claim_health,
        foci_summary=foci_summary,
        cyber_summary=cyber_summary,
        export_summary=export_summary,
        identity=identity,
    )
    return build_decision_tribunal_from_signals(signals)
