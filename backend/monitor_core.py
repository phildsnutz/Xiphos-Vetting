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
        "score_dict": score_dict,
        "current_report": current_report,
    }
