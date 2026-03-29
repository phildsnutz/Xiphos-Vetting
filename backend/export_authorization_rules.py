"""
Export authorization reference guidance.

This module provides a lightweight, rules-first reference layer for export
authorization cases. It does not attempt to replace counsel, BIS, or DDTC.
Instead, it normalizes a small set of official policy signals so Helios can
surface:

- country posture
- classification posture
- end-use / end-user red flags
- a conservative authorization posture hint

The output is intentionally framed as decision support and escalation guidance.
"""

from __future__ import annotations

from typing import Any
import re

from itar_module import ALLIED_NATIONS, ITAR_ELEVATED_SCRUTINY, ITAR_PROHIBITED_COUNTRIES
from osint.evidence_metadata import get_source_metadata


_ECCN_RE = re.compile(r"^\s*([0-9])([A-E])([0-9]{3})\s*$", re.IGNORECASE)
_USML_RE = re.compile(r"\b(USML|CATEGORY\s+[IVXLC]+|CAT\s+[IVXLC]+)\b", re.IGNORECASE)


# BIS country guidance anchors:
# - Country Chart: supplement no. 1 to part 738
# - Country Groups: supplement no. 1 to part 740
# - Part 744 end-use / end-user controls
# - deemed export guidance
#
# v1 is intentionally conservative. It focuses on the highest-value decision
# buckets rather than trying to reproduce the entire EAR.
BIS_COUNTRY_GROUP_E1 = {"CU", "IR", "KP", "SY"}
BIS_HIGH_SCRUTINY_DESTINATIONS = {
    "AF", "BY", "CN", "CU", "HK", "IR", "KP", "MM", "MO", "RU", "SY", "VE",
}
BIS_ALLIED_LOW_FRICTION = set(ALLIED_NATIONS) | {"US", "IE", "CH", "FI", "PT"}

COUNTRY_NAME_ALIASES = {
    "UNITED STATES": "US",
    "USA": "US",
    "U.S.": "US",
    "UNITED KINGDOM": "GB",
    "UK": "GB",
    "GREAT BRITAIN": "GB",
    "GERMANY": "DE",
    "FRANCE": "FR",
    "CANADA": "CA",
    "AUSTRALIA": "AU",
    "NEW ZEALAND": "NZ",
    "JAPAN": "JP",
    "SOUTH KOREA": "KR",
    "KOREA, REPUBLIC OF": "KR",
    "POLAND": "PL",
    "INDIA": "IN",
    "UNITED ARAB EMIRATES": "AE",
    "UAE": "AE",
    "TAIWAN": "TW",
    "CHINA": "CN",
    "PEOPLE'S REPUBLIC OF CHINA": "CN",
    "RUSSIA": "RU",
    "RUSSIAN FEDERATION": "RU",
    "BELARUS": "BY",
    "IRAN": "IR",
    "SYRIA": "SY",
    "CUBA": "CU",
    "NORTH KOREA": "KP",
}


PART_744_RED_FLAGS = [
    {
        "key": "nuclear",
        "label": "Nuclear / fuel-cycle end use",
        "severity": "critical",
        "patterns": [
            "nuclear", "centrifuge", "uranium", "reactor", "fuel cycle",
            "reprocessing", "enrichment",
        ],
        "reference": "15 CFR 744.2",
    },
    {
        "key": "missile_uav",
        "label": "Missile / rocket / UAV end use",
        "severity": "critical",
        "patterns": [
            "missile", "rocket", "uav", "drone", "hypersonic",
            "launch vehicle", "reentry vehicle",
        ],
        "reference": "15 CFR 744.3",
    },
    {
        "key": "military_end_use",
        "label": "Military / intelligence end use",
        "severity": "high",
        "patterns": [
            "military", "defense ministry", "signals intelligence", "ew",
            "electronic warfare", "targeting", "battle management",
            "military end use", "military end user",
        ],
        "reference": "15 CFR 744.21 / 744.22 / 744.23",
    },
    {
        "key": "surveillance",
        "label": "Surveillance / interception signal",
        "severity": "high",
        "patterns": [
            "surveillance", "lawful intercept", "interception", "facial recognition",
            "bulk monitoring",
        ],
        "reference": "15 CFR 744.6 / 744.21 context",
    },
]


def _normalize_country(value: object) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    if len(raw) == 2 and raw.isalpha():
        return raw
    return COUNTRY_NAME_ALIASES.get(raw, raw[:2] if len(raw) >= 2 else raw)


def _severity_rank(value: str) -> int:
    order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    return order.get(value, 0)


def _parse_classification(classification_guess: object, jurisdiction_guess: object) -> dict[str, Any]:
    raw = str(classification_guess or "").strip().upper()
    jurisdiction = str(jurisdiction_guess or "").strip().lower()
    if not raw:
        return {
            "input": "",
            "classification_family": "unknown",
            "label": "Needs classification",
            "rationale": "No ECCN or USML reference was provided, so Helios cannot safely map the item to the CCL or USML yet.",
            "known": False,
        }

    if raw == "EAR99":
        return {
            "input": raw,
            "classification_family": "ear99",
            "label": "EAR99",
            "rationale": "EAR99 items are usually lower-friction, but they can still require authorization for restricted destinations, end users, or end uses.",
            "known": True,
        }

    if _USML_RE.search(raw) or jurisdiction == "itar":
        return {
            "input": raw,
            "classification_family": "usml",
            "label": "USML / ITAR-controlled",
            "rationale": "The request is framed as ITAR / USML-sensitive and should be handled as a DDTC-governed transfer unless classification proves otherwise.",
            "known": True,
        }

    match = _ECCN_RE.match(raw)
    if not match:
        return {
            "input": raw,
            "classification_family": "unknown",
            "label": "Needs classification review",
            "rationale": "The provided classification does not match a recognizable ECCN or USML pattern. Treat it as unverified until the item is classified.",
            "known": False,
        }

    category, product_group, digits = match.groups()
    if digits.startswith("6"):
        return {
            "input": raw,
            "classification_family": "six_hundred_series",
            "label": "600-series ECCN",
            "rationale": "600-series ECCNs map to more defense-adjacent items and usually call for closer license and destination review.",
            "known": True,
        }
    if digits == "515":
        return {
            "input": raw,
            "classification_family": "nine_x_515",
            "label": "9x515 ECCN",
            "rationale": "9x515 ECCNs are tightly controlled and typically need a deeper reason-of-control and destination review.",
            "known": True,
        }
    if raw in {"5A002", "5D002", "5E002"}:
        return {
            "input": raw,
            "classification_family": "encryption",
            "label": "Encryption-controlled ECCN",
            "rationale": "Encryption classifications frequently depend on product details, destination, and reporting / exception posture.",
            "known": True,
        }
    return {
        "input": raw,
        "classification_family": "eccn_controlled",
        "label": f"ECCN {category}{product_group}{digits}",
        "rationale": "The item appears to be classified on the Commerce Control List and should be checked against reasons for control, destination, and applicable license exceptions.",
        "known": True,
    }


def _analyze_country(destination_country: object) -> dict[str, str]:
    country = _normalize_country(destination_country)
    if not country:
        return {
            "destination_country": "",
            "country_bucket": "unknown",
            "rationale": "No destination or access country was provided, so Helios cannot apply country-chart or country-group logic yet.",
        }
    if country in BIS_COUNTRY_GROUP_E1 or country in ITAR_PROHIBITED_COUNTRIES:
        return {
            "destination_country": country,
            "country_bucket": "E:1 / prohibited destination",
            "rationale": "This destination sits in the highest-restriction bucket and usually requires a hard stop or a formal escalation path.",
        }
    if country in BIS_HIGH_SCRUTINY_DESTINATIONS or country in ITAR_ELEVATED_SCRUTINY:
        return {
            "destination_country": country,
            "country_bucket": "high-scrutiny destination",
            "rationale": "This destination requires heightened review for export, reexport, or foreign-person access scenarios.",
        }
    if country in BIS_ALLIED_LOW_FRICTION:
        return {
            "destination_country": country,
            "country_bucket": "allied / lower-friction destination",
            "rationale": "This destination generally supports lower-friction review, but classification, end-use, and end-user controls still apply.",
        }
    return {
        "destination_country": country,
        "country_bucket": "standard destination review",
        "rationale": "This destination still requires classification, country-chart, and end-use review, but it is not in the highest-risk buckets modeled by Helios v1.",
    }


def _analyze_end_use(*parts: object) -> list[dict[str, str]]:
    text = " ".join(str(part or "") for part in parts).lower()
    flags: list[dict[str, str]] = []
    for rule in PART_744_RED_FLAGS:
        if any(_pattern_present(text, pattern) for pattern in rule["patterns"]):
            flags.append(
                {
                    "key": rule["key"],
                    "label": rule["label"],
                    "severity": rule["severity"],
                    "reference": rule["reference"],
                    "rationale": f"Matched end-use or access context terms associated with {rule['label'].lower()}.",
                }
            )
    flags.sort(key=lambda item: _severity_rank(item["severity"]), reverse=True)
    return flags


def _pattern_present(text: str, pattern: str) -> bool:
    escaped = re.escape(pattern.lower())
    return re.search(rf"\b{escaped}\b", text) is not None


def _base_references(jurisdiction_guess: str, has_end_use_flags: bool, is_foreign_person_access: bool, needs_classification: bool) -> list[dict[str, str]]:
    refs = [
        {
            "title": "BIS Country Guidance",
            "url": "https://www.bis.gov/licensing/country-guidance",
            "note": "Use the Country Chart and country groups to test destination-based license requirements.",
        },
        {
            "title": "BIS End-Use / End-User Controls",
            "url": "https://www.bis.gov/licensing/guidance-on-end-user-and-end-use-controls-and-us-person-controls",
            "note": "Part 744 controls can trigger license requirements even when destination or EAR99 treatment would otherwise look lower-friction.",
        },
    ]
    if needs_classification:
        refs.append(
            {
                "title": "BIS Classify Your Item",
                "url": "https://media.bis.gov/licensing/classify-your-item",
                "note": "Confirm the ECCN or determine whether the item is EAR99 before relying on a posture call.",
            }
        )
    else:
        refs.append(
            {
                "title": "EAR § 732.3 Steps Regarding the General Prohibitions",
                "url": "https://www.bis.gov/regulations/ear/732",
                "note": "The official order of operations is classification first, then country, end-use, and end-user review.",
            }
        )
    if has_end_use_flags:
        refs.append(
            {
                "title": "BIS Part 744 Reference",
                "url": "https://www.bis.gov/licensing/guidance-on-end-user-and-end-use-controls-and-us-person-controls",
                "note": "Review the specific Part 744 controls implicated by the flagged end use or end user.",
            }
        )
    if is_foreign_person_access or jurisdiction_guess == "ear":
        refs.append(
            {
                "title": "BIS Deemed Exports",
                "url": "https://www.bis.gov/deemed-exports",
                "note": "Foreign-person access to controlled technology or source code can trigger a deemed export review inside the United States.",
            }
        )
    return refs


def _build_posture(
    *,
    request_type: str,
    jurisdiction_guess: str,
    country_info: dict[str, str],
    classification_info: dict[str, Any],
    end_use_flags: list[dict[str, str]],
    foreign_person_nationalities: list[str],
) -> tuple[str, str, float, str, str, list[str]]:
    destination = country_info["destination_country"]
    factors: list[str] = []
    prohibited_nationalities = sorted(
        {
            nat
            for nat in foreign_person_nationalities
            if nat in BIS_COUNTRY_GROUP_E1 or nat in ITAR_PROHIBITED_COUNTRIES
        }
    )

    if country_info["country_bucket"] == "E:1 / prohibited destination":
        factors.append(f"Destination {destination} falls into the highest-restriction bucket modeled by the BIS / ITAR rules layer.")
        return (
            "likely_prohibited",
            "Likely prohibited",
            0.96,
            f"{destination} is a prohibited or embargoed destination in the Helios rules dataset, so this request should be treated as a likely hard stop pending counsel or agency review.",
            "Treat as a hard-stop candidate and escalate to export counsel or the empowered official before moving anything, releasing any data, or granting access.",
            factors,
        )

    if prohibited_nationalities and request_type == "foreign_person_access":
        factors.append(f"Foreign-person access involves nationalities in a prohibited destination bucket: {', '.join(prohibited_nationalities)}.")
        return (
            "likely_prohibited",
            "Likely prohibited",
            0.94,
            "The foreign-person access request includes one or more prohibited nationalities, which strongly suggests a hard-stop posture unless a formal authorization path exists.",
            "Do not grant access. Escalate immediately for export-control review and confirm whether any authorization path exists.",
            factors,
        )

    if end_use_flags and end_use_flags[0]["severity"] == "critical":
        factors.append(f"Critical Part 744-style end-use signal detected: {end_use_flags[0]['label']}.")
        return (
            "escalate",
            "Escalate for BIS / DDTC review",
            0.88,
            "The request carries a critical end-use or end-user signal tied to BIS Part 744-style controls, so Helios cannot safely call this low-friction.",
            "Escalate with the item classification, destination, parties, and full end-use narrative for a formal export-control determination.",
            factors,
        )

    family = classification_info["classification_family"]
    if family == "unknown":
        factors.append("No reliable ECCN or USML classification is available yet.")
        return (
            "insufficient_confidence",
            "Insufficient confidence",
            0.48,
            "Helios does not have enough classification certainty to recommend a safe authorization path yet.",
            "Classify the item first, then rerun the authorization review with the confirmed ECCN or USML basis.",
            factors,
        )

    if family == "usml" and destination == "CA" and request_type == "item_transfer" and not end_use_flags:
        factors.append("The request is ITAR-shaped but Canada may support a narrower exemption path for some unclassified transfers.")
        return (
            "likely_exception_or_exemption",
            "Likely exception / exemption path",
            0.72,
            "This request may fit a narrower exemption path, but it still needs a disciplined DDTC / internal review before anyone treats it as approved.",
            "Validate the exact item scope, confirm that the Canadian exemption or other DDTC path truly applies, and preserve the rationale in the case record.",
            factors,
        )

    if family in {"usml", "six_hundred_series", "nine_x_515"}:
        factors.append(f"Classification family {classification_info['label']} is more tightly controlled than a typical EAR99 transfer.")
        return (
            "likely_license_required",
            "Likely license required",
            0.84,
            "The classification suggests a more tightly controlled defense-adjacent transfer, so Helios is treating the request as likely license-driven until a specific exception or exemption is proven.",
            "Review license requirements, any exception or exemption basis, and the destination / party posture before moving the item or granting access.",
            factors,
        )

    if family == "ear99":
        if country_info["country_bucket"] == "allied / lower-friction destination" and not end_use_flags:
            factors.append("EAR99 plus an allied destination is usually the cleanest low-friction path in the Helios rules layer.")
            return (
                "likely_nlr",
                "Likely NLR / low-friction path",
                0.76,
                "EAR99 treatment plus a lower-friction destination points toward a likely No License Required path, assuming the parties and end use stay clean.",
                "Confirm the receiving party, end use, and destination one more time, then preserve the rationale as an EAR99 / low-friction decision record.",
                factors,
            )
        factors.append("EAR99 does not remove end-user, end-use, or destination review obligations.")
        return (
            "likely_license_required" if country_info["country_bucket"] == "high-scrutiny destination" else "escalate",
            "Likely license required" if country_info["country_bucket"] == "high-scrutiny destination" else "Escalate for review",
            0.68,
            "The item may be EAR99, but destination or use-case risk means Helios is not comfortable treating it as a simple low-friction transfer.",
            "Check the destination, parties, and end-use facts against BIS country and Part 744 controls before clearing the transaction.",
            factors,
        )

    if family in {"eccn_controlled", "encryption"}:
        if country_info["country_bucket"] == "allied / lower-friction destination" and not end_use_flags:
            factors.append("Controlled ECCNs can still qualify for exception-driven handling, but the reason-of-control and destination logic must be verified.")
            return (
                "likely_exception_or_exemption",
                "Likely exception / exemption path",
                0.66,
                "This controlled classification may fit an exception-driven path, but Helios still expects a formal country-chart and reason-of-control review.",
                "Validate the reason of control, destination bucket, and license exception basis before treating the transfer as cleared.",
                factors,
            )
        factors.append("Controlled ECCNs normally require a destination-specific license analysis.")
        return (
            "likely_license_required",
            "Likely license required",
            0.78,
            "The item appears to be controlled on the CCL, so Helios is treating the request as license-driven until a specific exception or low-friction basis is confirmed.",
            "Run the ECCN through the Country Chart and Part 744 checks, then document the exact authorization basis in the case record.",
            factors,
        )

    return (
        "insufficient_confidence",
        "Insufficient confidence",
        0.45,
        "Helios could not map this request cleanly into one of the supported v1 export postures.",
        "Escalate with classification, destination, parties, and end-use details for a manual export-control review.",
        factors,
    )


def build_export_authorization_guidance(case_input: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build a conservative export-authorization guidance payload."""
    if not isinstance(case_input, dict) or not case_input:
        return None

    jurisdiction_guess = str(case_input.get("jurisdiction_guess") or "unknown").strip().lower()
    request_type = str(case_input.get("request_type") or "").strip()
    foreign_person_nationalities = [
        _normalize_country(value)
        for value in (case_input.get("foreign_person_nationalities") or [])
        if _normalize_country(value)
    ]

    classification_info = _parse_classification(
        case_input.get("classification_guess"),
        jurisdiction_guess,
    )
    country_info = _analyze_country(case_input.get("destination_country"))
    end_use_flags = _analyze_end_use(
        case_input.get("item_or_data_summary"),
        case_input.get("end_use_summary"),
        case_input.get("access_context"),
    )

    posture, posture_label, confidence, reason_summary, recommended_next_step, factors = _build_posture(
        request_type=request_type,
        jurisdiction_guess=jurisdiction_guess,
        country_info=country_info,
        classification_info=classification_info,
        end_use_flags=end_use_flags,
        foreign_person_nationalities=foreign_person_nationalities,
    )

    refs = _base_references(
        jurisdiction_guess,
        has_end_use_flags=bool(end_use_flags),
        is_foreign_person_access=request_type == "foreign_person_access",
        needs_classification=not classification_info["known"],
    )
    metadata = get_source_metadata("bis_rules_engine")

    if foreign_person_nationalities:
        factors.append(
            "Foreign-person nationalities under review: "
            + ", ".join(sorted(dict.fromkeys(foreign_person_nationalities)))
            + "."
        )
    factors.append(country_info["rationale"])
    factors.append(classification_info["rationale"])
    if end_use_flags:
        factors.append(
            "Flagged end-use / end-user signals: "
            + ", ".join(flag["label"] for flag in end_use_flags[:3])
            + "."
        )

    return {
        "source": "bis_rules_engine",
        "version": "bis-rules-v1",
        "posture": posture,
        "posture_label": posture_label,
        "confidence": confidence,
        "reason_summary": reason_summary,
        "recommended_next_step": recommended_next_step,
        "country_analysis": country_info,
        "classification_analysis": classification_info,
        "end_use_flags": end_use_flags,
        "official_references": refs,
        "factors": factors,
        **metadata,
    }
