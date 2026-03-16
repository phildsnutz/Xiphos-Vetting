"""
Deemed Export Screening

Assesses risk of technology transfer to foreign nationals under deemed export rules.
A "deemed export" occurs when controlled technical data is made available to a foreign
national in the US (or foreign person abroad via US person).

Deemed export rules apply to:
- Controlled technical data (ITAR, EAR)
- Visas/work permits of foreign nationals
- Academic collaboration with foreign students
- Research collaborations with foreign institutions

Reference: 15 CFR 734.2(b) (EAR deemed export rules)
https://www.ecfr.gov/current/title-15/section-734.2
"""

import time
from . import EnrichmentResult, Finding


# Countries with highest deemed export risk
SANCTIONED_COUNTRIES = {
    "CN": "China - CFIUS scrutiny, USML/EAR controls",
    "RU": "Russia - Sanctions, military technology concerns",
    "IR": "Iran - Sanctioned entity, weapons programs",
    "KP": "North Korea - Sanctioned entity, weapons programs",
}

# Entity List countries (elevated deemed export risk)
ENTITY_LIST_COUNTRIES = {
    "SY": "Syria - Entity List, WMD concerns",
    "CU": "Cuba - Sanctions, travel restrictions",
    "VE": "Venezuela - Sanctions, government control",
    "KZ": "Kazakhstan - Illicit trade hub",
    "AE": "United Arab Emirates - Transhipment concerns",
}

# All high-risk countries combined
ALL_HIGH_RISK = {**SANCTIONED_COUNTRIES, **ENTITY_LIST_COUNTRIES}

# Visa statuses with elevated deemed export risk
HIGH_RISK_VISAS = [
    "F-1",  # Student
    "J-1",  # Exchange visitor
    "H-1B",  # Specialty occupation (includes dual-use research)
    "L-1",  # Intra-company transfer
    "O-1",  # Individual with extraordinary ability
]


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """
    Screen for deemed export risk based on country of origin and visa status.
    Expects optional visa_status, research_domain, usml_category in **ids.
    """
    t0 = time.time()
    result = EnrichmentResult(source="deemed_export", vendor_name=vendor_name)

    try:
        country = (country or "").upper().strip()
        visa_status = ids.get("visa_status", "").upper()
        research_domain = ids.get("research_domain", "").lower()
        usml_category = ids.get("usml_category", "").upper()

        findings_added = False

        # Check for sanctioned country nationals accessing controlled tech
        if country in SANCTIONED_COUNTRIES:
            reason = SANCTIONED_COUNTRIES[country]

            result.findings.append(
                Finding(
                    source="deemed_export",
                    category="deemed_export",
                    title=f"CRITICAL: Sanctioned country national ({country}) - deemed export risk",
                    detail=(
                        f"Foreign national from {country} ({reason}). "
                        f"Technology transfer to this national constitutes deemed export under 15 CFR 734.2(b). "
                        f"Restrictions apply to: controlled technical data, restricted software, controlled goods. "
                        f"ITAR List of articles (USML) and EAR controlled items require authorization. "
                        f"Consult legal/compliance before any technology or data sharing."
                    ),
                    severity="critical",
                    confidence=0.95,
                    url="https://www.ecfr.gov/current/title-15/section-734.2",
                    raw_data={
                        "country": country,
                        "country_reason": reason,
                        "deemed_export_applies": True,
                    },
                )
            )

            result.risk_signals.append(
                {
                    "signal": "deemed_export_sanctioned_country",
                    "severity": "critical",
                    "detail": f"Sanctioned country national {country} - deemed export applies",
                }
            )

            findings_added = True

        # Check for Entity List country nationals (elevated risk)
        elif country in ENTITY_LIST_COUNTRIES:
            reason = ENTITY_LIST_COUNTRIES[country]

            result.findings.append(
                Finding(
                    source="deemed_export",
                    category="deemed_export",
                    title=f"HIGH: Entity List country national ({country}) - deemed export risk",
                    detail=(
                        f"Foreign national from {country} ({reason}). "
                        f"Technology transfer may constitute deemed export under 15 CFR 734.2(b). "
                        f"Risk level depends on: (1) sensitivity of technology/data, (2) visa status, "
                        f"(3) nature of access. Enhanced screening required."
                    ),
                    severity="high",
                    confidence=0.85,
                    url="https://www.ecfr.gov/current/title-15/section-734.2",
                    raw_data={
                        "country": country,
                        "country_reason": reason,
                        "entity_list_country": True,
                    },
                )
            )

            result.risk_signals.append(
                {
                    "signal": "deemed_export_entity_list",
                    "severity": "high",
                    "detail": f"Entity List country national {country}",
                }
            )

            findings_added = True

        # Check for other foreign nationals in sensitive research domains
        elif country and research_domain in [
            "ai",
            "semiconductors",
            "biotechnology",
            "quantum",
            "nanotechnology",
            "hypersonics",
            "autonomous systems",
        ]:
            result.findings.append(
                Finding(
                    source="deemed_export",
                    category="deemed_export",
                    title=f"MEDIUM: Foreign national in sensitive research domain",
                    detail=(
                        f"Foreign national from {country} in sensitive research domain ({research_domain}). "
                        f"Deemed export rules may apply if research is controlled. "
                        f"Verify: (1) whether research is subject to export control, (2) visa restrictions, "
                        f"(3) foreign student/researcher regulations."
                    ),
                    severity="medium",
                    confidence=0.75,
                    url="https://www.ecfr.gov/current/title-15/section-734.2",
                    raw_data={
                        "country": country,
                        "research_domain": research_domain,
                    },
                )
            )

            result.risk_signals.append(
                {
                    "signal": "deemed_export_sensitive_domain",
                    "severity": "medium",
                    "detail": f"Foreign national in sensitive domain: {research_domain}",
                }
            )

            findings_added = True

        # Check visa status if available
        if visa_status and visa_status in HIGH_RISK_VISAS:
            visa_detail = (
                f"Visa status {visa_status} indicates specific restrictions apply. "
                f"F-1 students: SEVIS tracking required for controlled research. "
                f"J-1 exchange visitors: State Dept. may impose research restrictions. "
                f"H-1B: Employer sponsorship creates employer-specific work authorization. "
                f"Verify visa restrictions with immigration counsel."
            )

            if country in ALL_HIGH_RISK:
                # Already have critical/high finding, add visa detail
                result.findings.append(
                    Finding(
                        source="deemed_export",
                        category="deemed_export",
                        title=f"Deemed export: Visa status {visa_status} adds restrictions",
                        detail=visa_detail,
                        severity="high",
                        confidence=0.80,
                    )
                )
            else:
                # Generic visa warning
                result.findings.append(
                    Finding(
                        source="deemed_export",
                        category="deemed_export",
                        title=f"Visa status {visa_status} - deemed export considerations",
                        detail=visa_detail,
                        severity="medium",
                        confidence=0.75,
                    )
                )

            findings_added = True

        # If no high-risk country and no sensitive indicators, provide info
        if not findings_added:
            result.findings.append(
                Finding(
                    source="deemed_export",
                    category="deemed_export",
                    title="Deemed export: No major risk indicators",
                    detail=(
                        f"Foreign national from {country or 'unknown'} does not show elevated deemed export risk. "
                        f"Standard deemed export screening still recommended if technology transfer occurs."
                    ),
                    severity="info",
                    confidence=0.80,
                )
            )

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
