"""
End-Use/End-User Red Flag Analysis

Screens vendors against BIS "Red Flag Indicators" from Know Your Customer (KYC)
guidance to identify diversion risks and suspicious intermediaries.

These indicators help identify:
- End-users in countries known for weapons proliferation
- Intermediaries and brokers (not legitimate end-users)
- Military end-use indicators
- Transactions inconsistent with stated end-use

Reference: BIS Red Flag Indicators
https://www.bis.doc.gov/index.php/enforcement/know-your-customer
"""

import time
from . import EnrichmentResult, Finding


# Countries with elevated diversion risk
DIVERSION_RISK_COUNTRIES = {
    "CN": "China - Advanced weapons, military technology acquisition",
    "RU": "Russia - Weapons development, circumventing sanctions",
    "IR": "Iran - Ballistic missiles, nuclear programs, sanctions evasion",
    "KP": "North Korea - Weapons programs, sanctions evasion",
    "SY": "Syria - WMD programs, terrorism support",
    "CU": "Cuba - Sanctions regime, arms acquisition",
    "VE": "Venezuela - Sanctions regime, military modernization",
    "PK": "Pakistan - Nuclear/ballistic missile development",
    "KZ": "Kazakhstan - Illicit trade hub, intermediary risk",
    "AE": "United Arab Emirates - Known transhipment hub",
    "HK": "Hong Kong - Dual-use technology transhipment",
    "SG": "Singapore - Regional dual-use trade hub",
}

# Military end-use keywords
MILITARY_KEYWORDS = [
    "military",
    "army",
    "navy",
    "air force",
    "defense ministry",
    "armed forces",
    "weapons",
    "ordnance",
    "missile",
    "rocket",
    "ammunition",
    "explosives",
    "warship",
    "aircraft",
    "combat",
    "tactical",
    "battalion",
    "regiment",
    "squadron",
    "defense contractor",
    "munitions",
    "ballistic",
]

# Intermediary/trading company keywords
INTERMEDIARY_KEYWORDS = [
    "trading",
    "trade company",
    "import export",
    "broker",
    "logistics",
    "freight",
    "forwarding",
    "shipping",
    "distribution",
    "wholesale",
    "reseller",
    "agent",
    "intermediary",
    "merchant",
    "importer",
    "exporter",
    "shipper",
    "consolidator",
]


def _has_military_indicators(vendor_name: str) -> bool:
    """Check if vendor name suggests military end-use."""
    name_lower = vendor_name.lower()
    return any(kw in name_lower for kw in MILITARY_KEYWORDS)


def _has_intermediary_indicators(vendor_name: str) -> bool:
    """Check if vendor appears to be trading company or intermediary."""
    name_lower = vendor_name.lower()
    return any(kw in name_lower for kw in INTERMEDIARY_KEYWORDS)


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """
    Screen vendor for BIS red flag indicators.
    Checks country + vendor characteristics against known diversion patterns.
    """
    t0 = time.time()
    result = EnrichmentResult(source="end_use_risk", vendor_name=vendor_name)

    try:
        country = (country or "").upper().strip()
        findings_added = False

        # Check for military end-use indicators
        has_military = _has_military_indicators(vendor_name)

        # Check for intermediary indicators
        has_intermediary = _has_intermediary_indicators(vendor_name)

        # Check country risk
        if country in DIVERSION_RISK_COUNTRIES:
            risk_reason = DIVERSION_RISK_COUNTRIES[country]

            # High-risk combination: diversion country + military keywords
            if has_military:
                result.findings.append(
                    Finding(
                        source="end_use_risk",
                        category="end_use_risk",
                        title=f"CRITICAL: Diversion country ({country}) + military end-use",
                        detail=(
                            f"Vendor from {country} ({risk_reason}) with apparent military end-use keywords. "
                            f"This combination suggests potential diversion risk. "
                            f"BIS Red Flag Checklist items: "
                            f"(1) End-user in elevated-risk country; (2) Military/weapons-related terminology; "
                            f"(3) Transaction inconsistent with stated commercial purpose. "
                            f"Recommend enhanced due diligence and possible denial."
                        ),
                        severity="critical",
                        confidence=0.90,
                        url="https://www.bis.doc.gov/index.php/enforcement/know-your-customer",
                        raw_data={
                            "country": country,
                            "military_keywords": has_military,
                            "intermediary": has_intermediary,
                        },
                    )
                )

                result.risk_signals.append(
                    {
                        "signal": "end_use_diversion_critical",
                        "severity": "critical",
                        "detail": f"Diversion country {country} + military end-use indicators",
                    }
                )

                findings_added = True

            # High-risk: diversion country + intermediary (typical diversion pattern)
            elif has_intermediary:
                result.findings.append(
                    Finding(
                        source="end_use_risk",
                        category="end_use_risk",
                        title=f"HIGH: Diversion country ({country}) + intermediary/broker",
                        detail=(
                            f"Vendor from {country} ({risk_reason}) appears to be intermediary/trading company. "
                            f"Intermediaries are often used in diversion schemes. "
                            f"BIS Red Flag Checklist items: "
                            f"(1) End-user in elevated-risk country; "
                            f"(2) Intermediary/broker rather than legitimate end-user; "
                            f"(3) Unusual payment or delivery arrangements. "
                            f"Recommend identity verification and end-use investigation."
                        ),
                        severity="high",
                        confidence=0.85,
                        url="https://www.bis.doc.gov/index.php/enforcement/know-your-customer",
                        raw_data={
                            "country": country,
                            "military_keywords": has_military,
                            "intermediary": has_intermediary,
                        },
                    )
                )

                result.risk_signals.append(
                    {
                        "signal": "end_use_intermediary_risk",
                        "severity": "high",
                        "detail": f"Intermediary from elevated-risk country {country}",
                    }
                )

                findings_added = True

            else:
                # Medium: diversion country alone
                result.findings.append(
                    Finding(
                        source="end_use_risk",
                        category="end_use_risk",
                        title=f"MEDIUM: Vendor from diversion-risk country ({country})",
                        detail=(
                            f"Vendor from {country} ({risk_reason}). "
                            f"Enhanced due diligence recommended. "
                            f"BIS Red Flag Checklist: Verify end-user legitimacy, stated end-use, "
                            f"and that items are not subject to export controls."
                        ),
                        severity="medium",
                        confidence=0.80,
                        url="https://www.bis.doc.gov/index.php/enforcement/know-your-customer",
                        raw_data={
                            "country": country,
                            "military_keywords": has_military,
                            "intermediary": has_intermediary,
                        },
                    )
                )

                result.risk_signals.append(
                    {
                        "signal": "end_use_country_risk",
                        "severity": "medium",
                        "detail": f"Elevated-risk country {country}",
                    }
                )

                findings_added = True

        # If no country risk, check for red flags in other characteristics
        if not findings_added:
            if has_military:
                result.findings.append(
                    Finding(
                        source="end_use_risk",
                        category="end_use_risk",
                        title="Military end-use indicator found",
                        detail=(
                            f"Vendor name suggests military/weapons-related end-use. "
                            f"Verify that export control status is properly assessed. "
                            f"BIS Red Flag Checklist: Confirm stated end-use and applicable regulations."
                        ),
                        severity="medium",
                        confidence=0.70,
                    )
                )

                result.risk_signals.append(
                    {
                        "signal": "military_end_use_indicator",
                        "severity": "medium",
                        "detail": "Military end-use keywords detected",
                    }
                )

                findings_added = True

            elif has_intermediary:
                result.findings.append(
                    Finding(
                        source="end_use_risk",
                        category="end_use_risk",
                        title="Intermediary/broker characteristics",
                        detail=(
                            f"Vendor appears to be intermediary or trading company. "
                            f"Enhanced KYC recommended. Verify actual end-user identity and end-use. "
                            f"BIS Red Flag Checklist: Confirm buyer is legitimate end-user, not reseller."
                        ),
                        severity="medium",
                        confidence=0.70,
                    )
                )

                result.risk_signals.append(
                    {
                        "signal": "intermediary_indicator",
                        "severity": "medium",
                        "detail": "Intermediary/broker characteristics detected",
                    }
                )

                findings_added = True

        if not findings_added:
            # No red flags found
            result.findings.append(
                Finding(
                    source="end_use_risk",
                    category="end_use_risk",
                    title="End-use risk: No major red flags",
                    detail=(
                        f"Vendor '{vendor_name}' does not show major BIS red flag indicators. "
                        f"Standard due diligence recommended."
                    ),
                    severity="info",
                    confidence=0.80,
                )
            )

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
