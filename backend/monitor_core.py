"""
Shared monitoring logic for synchronous and scheduled vendor rechecks.

This module centralizes:
- finding diffing
- registry mutation detection
- canonical enrich + persist + rescore flow
- score delta thresholding
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime
from typing import Callable, Optional

import db

try:
    from osint.enrichment import enrich_vendor as _enrich_vendor
    HAS_OSINT = True
except ImportError:
    _enrich_vendor = None
    HAS_OSINT = False

try:
    from profiles import get_connector_list as _get_connector_list
except ImportError:
    def _get_connector_list(_profile: str) -> list[str]:
        return []


SCORE_DELTA_ALERT_THRESHOLD = 5.0


def summarize_sources_triggered(report: dict | None) -> list[str]:
    """Return connector names that materially contributed data in a monitoring run."""
    connector_status = report.get("connector_status") if isinstance(report, dict) else {}
    triggered: list[str] = []
    for source, status in (connector_status or {}).items():
        if not isinstance(source, str) or not isinstance(status, dict):
            continue
        findings_count = int(status.get("findings_count") or 0)
        has_data = bool(status.get("has_data"))
        if findings_count > 0 or has_data:
            triggered.append(source)
    return sorted(set(triggered))


def classify_monitor_change(
    previous_risk: str,
    current_risk: str,
    previous_score: float,
    current_score: float,
    new_findings_count: int,
    sources_triggered: list[str] | None,
) -> str:
    """Classify the most important user-visible change from a monitor run."""
    if str(previous_risk or "") != str(current_risk or ""):
        return "score_change"
    if abs(float(current_score or 0.0) - float(previous_score or 0.0)) >= 0.01:
        return "score_change"
    if int(new_findings_count or 0) > 0:
        return "new_finding"
    if sources_triggered:
        return "source_triggered"
    return "no_change"


def build_monitor_delta_summary(
    previous_risk: str,
    current_risk: str,
    previous_score: float,
    current_score: float,
    new_findings_count: int,
    resolved_findings_count: int,
    sources_triggered: list[str] | None,
) -> str:
    """Build a one-line summary for a monitor run."""
    parts: list[str] = []
    score_delta = float(current_score or 0.0) - float(previous_score or 0.0)
    if abs(score_delta) >= 0.01:
        direction = "increased" if score_delta > 0 else "decreased"
        parts.append(f"Score {direction} {score_delta:+.1f}%")
    if str(previous_risk or "") and str(current_risk or "") and str(previous_risk) != str(current_risk):
        parts.append(f"Tier {previous_risk} -> {current_risk}")
    if int(new_findings_count or 0) > 0:
        parts.append(f"{int(new_findings_count)} new finding{'s' if int(new_findings_count) != 1 else ''}")
    if int(resolved_findings_count or 0) > 0:
        parts.append(f"{int(resolved_findings_count)} resolved finding{'s' if int(resolved_findings_count) != 1 else ''}")
    if sources_triggered:
        if len(sources_triggered) <= 2:
            parts.append(f"Sources triggered: {', '.join(sources_triggered)}")
        else:
            parts.append(f"{len(sources_triggered)} sources triggered")
    return ", ".join(parts) if parts else "No material delta detected"


def fingerprint_finding(finding: dict) -> str:
    """Generate a stable hash for a finding."""
    key = f"{finding.get('source', '')}-{finding.get('title', '')}-{finding.get('severity', '')}"
    return hashlib.md5(key.encode()).hexdigest()


def diff_findings(old_findings: list[dict], new_findings: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return newly introduced findings and findings that resolved."""
    old_fingerprints = {
        fingerprint_finding(finding): finding
        for finding in old_findings
        if isinstance(finding, dict)
    }
    new_fingerprints = {
        fingerprint_finding(finding): finding
        for finding in new_findings
        if isinstance(finding, dict)
    }
    new_only = [new_fingerprints[fp] for fp in new_fingerprints if fp not in old_fingerprints]
    resolved = [old_fingerprints[fp] for fp in old_fingerprints if fp not in new_fingerprints]
    return new_only, resolved


def is_registry_mutation_finding(finding: dict) -> bool:
    """Identify findings that represent official registry mutations."""
    if not isinstance(finding, dict):
        return False
    source = str(finding.get("source") or "").strip().lower()
    title = str(finding.get("title") or "").strip().lower()
    raw_data = finding.get("raw_data") if isinstance(finding.get("raw_data"), dict) else {}
    if source != "netherlands_kvk":
        return False
    return title.startswith("kvk mutation:") or isinstance(raw_data.get("mutation"), dict)


def emit_registry_mutation_alerts(vendor_id: str, vendor_name: str, new_findings: list[dict]) -> int:
    """Persist official registry mutation alerts and return how many were emitted."""
    emitted = 0
    for finding in new_findings:
        if not is_registry_mutation_finding(finding):
            continue
        db.save_alert(
            vendor_id=vendor_id,
            entity_name=vendor_name,
            severity="medium",
            title=f"Registry Mutation Alert: {vendor_name}",
            description=str(finding.get("title") or "KVK mutation detected"),
        )
        emitted += 1
    return emitted


def compute_new_risk_signals(previous_report: dict | None, current_report: dict) -> list[dict]:
    """Return risk signals newly introduced by the fresh enrichment run."""
    if not previous_report:
        return list(current_report.get("risk_signals", []) or [])

    old_signal_fingerprints = {
        hashlib.md5(f"{signal.get('type', '')}-{signal.get('message', '')}".encode()).hexdigest(): signal
        for signal in (previous_report.get("risk_signals", []) or [])
        if isinstance(signal, dict)
    }
    new_signals: list[dict] = []
    for signal in current_report.get("risk_signals", []) or []:
        if not isinstance(signal, dict):
            continue
        fp = hashlib.md5(f"{signal.get('type', '')}-{signal.get('message', '')}".encode()).hexdigest()
        if fp not in old_signal_fingerprints:
            new_signals.append(signal)
    return new_signals


def run_monitor_check(
    vendor: dict,
    *,
    connector_resolver: Optional[Callable[[str], list[str]]] = None,
    enrich_func: Optional[Callable[..., dict]] = None,
) -> dict | None:
    """
    Canonical monitoring check used by both monitoring entry points.

    Returns a normalized dict with findings delta, score delta, and current tier.
    """
    if not HAS_OSINT or not vendor:
        return None

    connector_resolver = connector_resolver or _get_connector_list
    enrich_func = enrich_func or _enrich_vendor
    if enrich_func is None:
        return None

    vendor_id = vendor["id"]
    vendor_name = vendor["name"]
    vendor_country = vendor["country"]
    profile = vendor.get("profile", "defense_acquisition")

    t0 = time.time()
    started_at = datetime.utcnow().isoformat() + "Z"
    previous_report = db.get_latest_enrichment(vendor_id)
    previous_score = db.get_latest_score(vendor_id)
    previous_tier = (
        previous_score.get("calibrated", {}).get("calibrated_tier", "unknown")
        if previous_score else "unknown"
    )
    previous_score_pct = (previous_score or {}).get("composite_score", 0)

    connectors = connector_resolver(profile)
    seed_ids = previous_report.get("identifiers", {}) if isinstance(previous_report, dict) else {}
    current_report = enrich_func(
        vendor_name=vendor_name,
        country=vendor_country,
        connectors=connectors or None,
        parallel=True,
        timeout=60,
        **(seed_ids if isinstance(seed_ids, dict) else {}),
    )

    old_findings = previous_report.get("findings", []) if isinstance(previous_report, dict) else []
    current_findings = current_report.get("findings", []) or []
    new_findings, resolved_findings = diff_findings(old_findings, current_findings)
    new_risk_signals = compute_new_risk_signals(previous_report, current_report)

    from server import _canonical_rescore_from_enrichment, _persist_enrichment_artifacts

    _persist_enrichment_artifacts(vendor_id, vendor, current_report)
    rescored = _canonical_rescore_from_enrichment(vendor_id, vendor, current_report)
    score_dict = rescored["score_dict"]

    current_tier = score_dict.get("calibrated", {}).get("calibrated_tier", "unknown")
    current_score_pct = score_dict.get("composite_score", 0)
    score_delta = abs(current_score_pct - previous_score_pct)
    elapsed_ms = int((time.time() - t0) * 1000)
    completed_at = datetime.utcnow().isoformat() + "Z"
    sources_triggered = summarize_sources_triggered(current_report)
    change_type = classify_monitor_change(
        previous_tier,
        current_tier,
        float(previous_score_pct or 0.0),
        float(current_score_pct or 0.0),
        len(new_findings),
        sources_triggered,
    )
    delta_summary = build_monitor_delta_summary(
        previous_tier,
        current_tier,
        float(previous_score_pct or 0.0),
        float(current_score_pct or 0.0),
        len(new_findings),
        len(resolved_findings),
        sources_triggered,
    )

    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "profile": profile,
        "previous_risk": previous_tier,
        "current_risk": current_tier,
        "old_tier": previous_tier,
        "new_tier": current_tier,
        "previous_score": previous_score_pct,
        "current_score": current_score_pct,
        "old_score": previous_score_pct,
        "new_score": current_score_pct,
        "risk_changed": previous_tier != current_tier,
        "new_findings": new_findings,
        "resolved_findings": resolved_findings,
        "new_risk_signals": new_risk_signals,
        "score_delta": score_delta,
        "score_delta_alert": score_delta >= SCORE_DELTA_ALERT_THRESHOLD,
        "elapsed_ms": elapsed_ms,
        "started_at": started_at,
        "completed_at": completed_at,
        "sources_triggered": sources_triggered,
        "change_type": change_type,
        "delta_summary": delta_summary,
        "score_dict": score_dict,
        "current_report": current_report,
    }
