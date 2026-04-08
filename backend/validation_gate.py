"""
Validation gate for AXIOM and Contract Vehicle Intelligence findings.

This module is the Phase 3 keystone in the Helios workflow:
  - AXIOM can hunt for signal
  - the validation gate decides what is durable
  - only accepted findings are eligible for graph promotion

The first implementation is intentionally narrow. It validates AXIOM gap-fill
results before those results are treated as closed intelligence gaps.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


_OFFICIAL_SOURCE_CLASSES = {
    "official_registry",
    "official_program_system",
    "official_regulatory",
    "official_judicial_record",
}

_SOURCE_PROFILES: dict[str, dict[str, object]] = {
    "sam_gov": {
        "source_class": "official_registry",
        "authority_level": "official_registry",
        "authority_score": 0.98,
    },
    "sam_subawards": {
        "source_class": "official_program_system",
        "authority_level": "official_program_system",
        "authority_score": 0.94,
    },
    "sam_subaward_reporting": {
        "source_class": "official_program_system",
        "authority_level": "official_program_system",
        "authority_score": 0.94,
    },
    "usaspending": {
        "source_class": "official_program_system",
        "authority_level": "official_program_system",
        "authority_score": 0.94,
    },
    "fpds": {
        "source_class": "official_program_system",
        "authority_level": "official_program_system",
        "authority_score": 0.94,
    },
    "fpds_contracts": {
        "source_class": "official_program_system",
        "authority_level": "official_program_system",
        "authority_score": 0.94,
    },
    "sec_edgar": {
        "source_class": "official_regulatory",
        "authority_level": "official_regulatory",
        "authority_score": 0.9,
    },
    "courtlistener": {
        "source_class": "official_judicial_record",
        "authority_level": "official_judicial_record",
        "authority_score": 0.88,
    },
    "ofac": {
        "source_class": "official_regulatory",
        "authority_level": "official_regulatory",
        "authority_score": 0.91,
    },
    "trade_csl": {
        "source_class": "official_regulatory",
        "authority_level": "official_regulatory",
        "authority_score": 0.9,
    },
    "gleif": {
        "source_class": "official_registry",
        "authority_level": "official_registry",
        "authority_score": 0.9,
    },
    "gleif_lei": {
        "source_class": "official_registry",
        "authority_level": "official_registry",
        "authority_score": 0.9,
    },
    "opencorporates": {
        "source_class": "structured_public",
        "authority_level": "public_registry_aggregation",
        "authority_score": 0.72,
    },
    "opensanctions": {
        "source_class": "structured_public",
        "authority_level": "public_registry_aggregation",
        "authority_score": 0.68,
    },
    "public_html": {
        "source_class": "public_html",
        "authority_level": "public_capture",
        "authority_score": 0.52,
    },
    "public_html_ownership": {
        "source_class": "public_html",
        "authority_level": "public_capture",
        "authority_score": 0.55,
    },
    "careers_scraper": {
        "source_class": "public_html",
        "authority_level": "public_capture",
        "authority_score": 0.46,
    },
    "clearancejobs_followup": {
        "source_class": "public_html",
        "authority_level": "public_capture",
        "authority_score": 0.44,
    },
    "linkedin": {
        "source_class": "public_profile",
        "authority_level": "public_capture",
        "authority_score": 0.42,
    },
    "gdelt": {
        "source_class": "media_aggregation",
        "authority_level": "media_aggregation",
        "authority_score": 0.34,
    },
    "gdelt_media": {
        "source_class": "media_aggregation",
        "authority_level": "media_aggregation",
        "authority_score": 0.34,
    },
    "rss_public": {
        "source_class": "public_feed",
        "authority_level": "first_party_self_disclosed",
        "authority_score": 0.56,
    },
}


@dataclass
class NormalizedFinding:
    source: str
    raw_source: str
    source_class: str
    authority_level: str
    authority_score: float
    evidence: str
    confidence: float


@dataclass
class ValidationDecision:
    outcome: str
    confidence_label: str
    graph_action: str
    reasons: list[str]
    distinct_source_count: int
    official_source_count: int
    evidence_count: int
    average_source_score: float
    average_finding_confidence: float
    fill_confidence: float
    accepted_finding_count: int
    rejected_finding_count: int
    source_profiles: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_source_name(value: object) -> str:
    source = str(value or "").strip().lower()
    if source.startswith("connector:"):
        source = source.split(":", 1)[1].strip()
    if source.startswith("source:"):
        source = source.split(":", 1)[1].strip()
    return source


def _profile_source(source: str) -> dict[str, object]:
    normalized = _normalize_source_name(source)
    if normalized in _SOURCE_PROFILES:
        return dict(_SOURCE_PROFILES[normalized])
    if "sam" in normalized:
        return {
            "source_class": "official_registry",
            "authority_level": "official_registry",
            "authority_score": 0.92,
        }
    if "fpds" in normalized or "usaspending" in normalized:
        return {
            "source_class": "official_program_system",
            "authority_level": "official_program_system",
            "authority_score": 0.92,
        }
    if "court" in normalized:
        return {
            "source_class": "official_judicial_record",
            "authority_level": "official_judicial_record",
            "authority_score": 0.86,
        }
    if "sec" in normalized or "edgar" in normalized:
        return {
            "source_class": "official_regulatory",
            "authority_level": "official_regulatory",
            "authority_score": 0.88,
        }
    if "html" in normalized or "career" in normalized:
        return {
            "source_class": "public_html",
            "authority_level": "public_capture",
            "authority_score": 0.48,
        }
    if "news" in normalized or "gdelt" in normalized:
        return {
            "source_class": "media_aggregation",
            "authority_level": "media_aggregation",
            "authority_score": 0.34,
        }
    return {
        "source_class": "unknown",
        "authority_level": "unknown",
        "authority_score": 0.5,
    }


def _extract_evidence_text(finding: dict) -> str:
    for key in ("evidence", "value", "detail", "snippet", "title"):
        value = finding.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = finding.get("data")
    if isinstance(data, str) and data.strip():
        return data.strip()
    if isinstance(data, (dict, list)) and data:
        try:
            rendered = json.dumps(data, sort_keys=True)
        except (TypeError, ValueError):
            rendered = str(data)
        return rendered[:280]
    return ""


def extract_normalized_findings(result) -> list[NormalizedFinding]:
    attempts = list(getattr(result, "attempts", []) or [])
    result_confidence = _coerce_float(getattr(result, "fill_confidence", 0.0), 0.0)
    findings: list[NormalizedFinding] = []
    seen: set[tuple[str, str]] = set()

    for attempt in attempts:
        attempt_confidence = _coerce_float(getattr(attempt, "confidence_in_fill", result_confidence), result_confidence)
        for finding in list(getattr(attempt, "findings", []) or []):
            if not isinstance(finding, dict):
                continue
            raw_source = str(finding.get("source") or "").strip() or "unknown"
            source = _normalize_source_name(raw_source)
            evidence = _extract_evidence_text(finding)
            dedupe_key = (source, evidence)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            profile = _profile_source(source)
            findings.append(
                NormalizedFinding(
                    source=source or "unknown",
                    raw_source=raw_source,
                    source_class=str(profile.get("source_class") or "unknown"),
                    authority_level=str(profile.get("authority_level") or "unknown"),
                    authority_score=_coerce_float(profile.get("authority_score"), 0.5),
                    evidence=evidence,
                    confidence=_coerce_float(finding.get("confidence"), attempt_confidence),
                )
            )
    return findings


def validate_gap_fill_result(result) -> ValidationDecision:
    """
    Validate an AXIOM gap-fill result before it is treated as durable signal.

    Outcome meanings:
      - accepted: strong enough to promote into the durable intelligence path
      - review: useful lead, but still an analyst-review / partial state
      - rejected: not strong enough to drive dossier or graph updates
    """

    fill_confidence = _coerce_float(getattr(result, "fill_confidence", 0.0), 0.0)
    findings = extract_normalized_findings(result)

    if not findings:
        return ValidationDecision(
            outcome="rejected",
            confidence_label="unknown",
            graph_action="reject",
            reasons=["AXIOM returned no concrete findings to validate."],
            distinct_source_count=0,
            official_source_count=0,
            evidence_count=0,
            average_source_score=0.0,
            average_finding_confidence=0.0,
            fill_confidence=fill_confidence,
            accepted_finding_count=0,
            rejected_finding_count=0,
            source_profiles=[],
        )

    distinct_sources = sorted({finding.source for finding in findings})
    official_sources = sorted(
        {
            finding.source
            for finding in findings
            if finding.source_class in _OFFICIAL_SOURCE_CLASSES
        }
    )
    evidence_count = sum(1 for finding in findings if finding.evidence)
    average_source_score = round(sum(finding.authority_score for finding in findings) / len(findings), 4)
    average_finding_confidence = round(sum(finding.confidence for finding in findings) / len(findings), 4)

    reasons: list[str] = []
    outcome = "rejected"
    confidence_label = "unknown"
    graph_action = "reject"

    if official_sources and evidence_count >= 1 and fill_confidence >= 0.7:
        outcome = "accepted"
        confidence_label = "observed"
        graph_action = "promote"
        reasons.append("At least one official or authoritative source backs the fill.")
    elif len(distinct_sources) >= 2 and evidence_count >= 2 and average_source_score >= 0.65 and fill_confidence >= 0.65:
        outcome = "accepted"
        confidence_label = "corroborated"
        graph_action = "promote"
        reasons.append("Multiple independent sources corroborate the fill.")
    elif evidence_count >= 1 and average_source_score >= 0.55 and fill_confidence >= 0.5:
        outcome = "review"
        confidence_label = "inferred"
        graph_action = "hold_review"
        reasons.append("Useful signal exists, but corroboration is still thin.")
    elif evidence_count >= 1 and fill_confidence >= 0.35:
        outcome = "review"
        confidence_label = "weakly_inferred"
        graph_action = "hold_review"
        reasons.append("AXIOM surfaced a plausible lead, not a durable fact.")
    else:
        reasons.append("Returned signal is too weak or too thin for promotion.")

    if not official_sources:
        reasons.append("No official-source corroboration is present yet.")
    if len(distinct_sources) == 1:
        reasons.append("The fill is still relying on a single distinct source.")
    if average_source_score < 0.55:
        reasons.append("Source authority is below the durable-signal threshold.")
    if evidence_count == 0:
        reasons.append("No analyst-readable evidence snippet was returned.")

    source_profiles = [
        {
            "source": source,
            "source_class": next(f.source_class for f in findings if f.source == source),
            "authority_level": next(f.authority_level for f in findings if f.source == source),
            "authority_score": next(f.authority_score for f in findings if f.source == source),
        }
        for source in distinct_sources
    ]
    accepted_finding_count = sum(1 for finding in findings if finding.authority_score >= 0.55)
    rejected_finding_count = max(0, len(findings) - accepted_finding_count)

    return ValidationDecision(
        outcome=outcome,
        confidence_label=confidence_label,
        graph_action=graph_action,
        reasons=reasons,
        distinct_source_count=len(distinct_sources),
        official_source_count=len(official_sources),
        evidence_count=evidence_count,
        average_source_score=average_source_score,
        average_finding_confidence=average_finding_confidence,
        fill_confidence=fill_confidence,
        accepted_finding_count=accepted_finding_count,
        rejected_finding_count=rejected_finding_count,
        source_profiles=source_profiles,
    )


def should_promote_gap_fill(result) -> bool:
    """True when a gap-fill result is strong enough for the durable path."""
    decision = validate_gap_fill_result(result)
    return decision.outcome == "accepted"


# Backward-compatible alias for any local callers that still use the private name.
_extract_normalized_findings = extract_normalized_findings
