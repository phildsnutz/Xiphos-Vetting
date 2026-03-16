"""
Institutional Risk Assessment

Evaluates foreign universities and research institutes for government/military ties.
Institutions vary by risk level: PLA-affiliated (critical), state key labs (high),
sanctioned-country universities (high), etc.

Curated database of high-risk institutions focusing on:
- PLA-affiliated (Seven Sons + other military research)
- Chinese state key labs and national labs
- Russian state research institutes
- Sanctioned-country institutions
- Institutions under government/military control

Reference: NCSC, State Department, export control guidance
"""

import time
import difflib
from . import EnrichmentResult, Finding


# Critical risk: PLA-affiliated universities
CRITICAL_RISK_INSTITUTIONS = [
    # Seven Sons of National Defence
    "Harbin Institute of Technology",
    "HIT",
    "Harbin Engineering University",
    "HEU",
    "Beijing University of Aeronautics and Astronautics",
    "BUAA",
    "Beihang University",
    "Northwestern Polytechnical University",
    "NWPU",
    "Nanjing University of Aeronautics and Astronautics",
    "NUAA",
    "National University of Defense Technology",
    "NUDT",
    "Beijing Institute of Technology",
    "BIT",
    # Russian military research institutes
    "Russian Federal Nuclear Center",
    "VNIIEF",
    "Kurchatov Institute",
    "Russian Academy of Sciences Institute of Applied Mathematics",
    "Institute of Experimental Physics",
    "All-Russia Research Institute of Optical and Physical Measurements",
    # Iranian military/weapons research
    "Imam Khomeini Naval University",
    "Amir Kabir University of Technology",
]

# High risk: State Key Labs and national research institutes
HIGH_RISK_INSTITUTIONS = [
    # Chinese state key labs and research institutes
    "State Key Laboratory of Satellite Ocean Environment Dynamics",
    "State Key Laboratory of Advanced Materials Synthesis",
    "State Key Laboratory of Turbulence and Complex Systems",
    "Institute of Engineering Mechanics",
    "Institute of Applied Physics and Computational Mathematics",
    "China Academy of Sciences",
    "CAS",
    "Chinese Academy of Engineering",
    "National Center for Supercomputing Applications China",
    "China National Space Administration",
    "CNSA",
    "China Aerospace Science and Technology Corporation",
    "CASC",
    "China Aviation Industry Corporation",
    "AVIC",
    # Russian research institutes
    "Skolkovo Institute of Science and Technology",
    "SKOLTECH",
    "Moscow Institute of Physics and Technology",
    "MIPT",
    "St. Petersburg State Polytechnical University",
    "Higher School of Economics",  # Some military research contracts
    # Iranian universities
    "University of Tehran",
    "Sharif University of Technology",
    "Amirkabir University of Technology",
    "Iran University of Science and Technology",
]

# Medium risk: Universities in sanctioned countries or with state funding concerns
MEDIUM_RISK_INSTITUTIONS = [
    # Universities in sanctioned countries
    "University of Damascus",
    "Damascus University",
    "Cuban universities",
    "Universidad de La Habana",
    "Venezuelan universities",
    "Universidad de los Andes Venezuela",
    # Institutions with government control concerns
    "Tsinghua University",  # PRC Ministry of Education
    "Peking University",  # PRC Ministry of Education
    "Fudan University",  # PRC Ministry of Education
    "Shanghai Jiao Tong University",  # PRC Ministry of Education, defense research
    "University of Science and Technology of China",
    "USTC",
    "Xiamen University",
    "Zhejiang University",
    "Wuhan University",
    # Russian universities with state/military ties
    "Moscow State University",
    "Saint-Petersburg State University",
    "Russian Military Academy",
]

# Institution risk categories by country
COUNTRY_RISK_TIERS = {
    "CN": {
        "default_severity": "medium",
        "description": "China - State funding, government control, dual-use research",
    },
    "RU": {
        "default_severity": "medium",
        "description": "Russia - State funding, sanctions, military research concerns",
    },
    "IR": {
        "default_severity": "high",
        "description": "Iran - Sanctioned country, military research, sanctions evasion",
    },
    "KP": {
        "default_severity": "critical",
        "description": "North Korea - Sanctioned country, weapons programs",
    },
    "SY": {
        "default_severity": "high",
        "description": "Syria - Sanctioned, WMD programs",
    },
    "CU": {
        "default_severity": "medium",
        "description": "Cuba - Sanctioned country",
    },
    "VE": {
        "default_severity": "medium",
        "description": "Venezuela - Sanctioned country",
    },
}

# Keywords suggesting government/military control
GOVERNMENT_CONTROL_KEYWORDS = [
    "state",
    "ministry",
    "national defense",
    "military",
    "academy",
    "strategic",
    "government",
    "national laboratory",
    "state key laboratory",
]


def _fuzzy_match_institution(
    institution_name: str, candidates: list[str], threshold: float = 0.75
) -> tuple[bool, float, str | None]:
    """
    Fuzzy match institution against candidate list.
    Returns (matched, score, matched_name).
    """
    if not institution_name:
        return (False, 0.0, None)

    inst_lower = institution_name.lower()
    max_score = 0.0
    best_match = None

    for candidate in candidates:
        candidate_lower = candidate.lower()

        # Exact substring match
        if candidate_lower in inst_lower or inst_lower in candidate_lower:
            return (True, 0.95, candidate)

        # Fuzzy match
        ratio = difflib.SequenceMatcher(None, inst_lower, candidate_lower).ratio()
        if ratio > max_score:
            max_score = ratio
            best_match = candidate

    if max_score >= threshold:
        return (True, max_score, best_match)

    return (False, max_score, None)


def _has_government_control_indicators(institution_name: str) -> bool:
    """Check if institution name suggests government/military control."""
    inst_lower = institution_name.lower()
    return any(kw in inst_lower for kw in GOVERNMENT_CONTROL_KEYWORDS)


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """
    Assess institutional risk based on known high-risk institutions and country.
    Expects optional home_institution in **ids.
    """
    t0 = time.time()
    result = EnrichmentResult(source="institutional_risk", vendor_name=vendor_name)

    try:
        country = (country or "").upper().strip()
        home_institution = ids.get("home_institution", "")

        # If institution not provided, try to use vendor_name as institution
        institution = home_institution or vendor_name

        if not institution:
            result.findings.append(
                Finding(
                    source="institutional_risk",
                    category="institutional_risk",
                    title="Institutional risk: No institution information",
                    detail="No institutional information provided. Cannot assess institutional risk.",
                    severity="info",
                    confidence=0.5,
                )
            )
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        findings_added = False

        # Check for critical risk institutions
        is_critical, critical_score, critical_match = _fuzzy_match_institution(
            institution, CRITICAL_RISK_INSTITUTIONS, threshold=0.70
        )

        if is_critical:
            result.findings.append(
                Finding(
                    source="institutional_risk",
                    category="institutional_risk",
                    title=f"CRITICAL: Known PLA/state military research institute ({critical_match})",
                    detail=(
                        f"Institution '{institution}' matches known critical-risk institution: {critical_match}. "
                        f"This institution has direct military/defense affiliation or state control. "
                        f"Enhanced due diligence required. Recommend compliance review before collaboration."
                    ),
                    severity="critical",
                    confidence=0.90,
                    raw_data={"matched_institution": critical_match, "risk_tier": "critical"},
                )
            )

            result.risk_signals.append(
                {
                    "signal": "critical_risk_institution",
                    "severity": "critical",
                    "detail": f"Known critical-risk institution: {critical_match}",
                }
            )

            findings_added = True

        # Check for high risk institutions
        elif not findings_added:
            is_high, high_score, high_match = _fuzzy_match_institution(
                institution, HIGH_RISK_INSTITUTIONS, threshold=0.70
            )

            if is_high:
                result.findings.append(
                    Finding(
                        source="institutional_risk",
                        category="institutional_risk",
                        title=f"HIGH: State key lab or military-aligned research institute ({high_match})",
                        detail=(
                            f"Institution '{institution}' matches high-risk institution: {high_match}. "
                            f"This institution has state/military research focus. "
                            f"Enhanced due diligence recommended."
                        ),
                        severity="high",
                        confidence=0.85,
                        raw_data={"matched_institution": high_match, "risk_tier": "high"},
                    )
                )

                result.risk_signals.append(
                    {
                        "signal": "high_risk_institution",
                        "severity": "high",
                        "detail": f"High-risk institution: {high_match}",
                    }
                )

                findings_added = True

            # Check for medium risk institutions
            else:
                is_medium, medium_score, medium_match = _fuzzy_match_institution(
                    institution, MEDIUM_RISK_INSTITUTIONS, threshold=0.70
                )

                if is_medium:
                    result.findings.append(
                        Finding(
                            source="institutional_risk",
                            category="institutional_risk",
                            title=f"MEDIUM: University with state/military ties ({medium_match})",
                            detail=(
                                f"Institution '{institution}' matches medium-risk institution: {medium_match}. "
                                f"This institution has state funding or potential military research ties. "
                                f"Standard due diligence recommended."
                            ),
                            severity="medium",
                            confidence=0.75,
                            raw_data={"matched_institution": medium_match, "risk_tier": "medium"},
                        )
                    )

                    result.risk_signals.append(
                        {
                            "signal": "medium_risk_institution",
                            "severity": "medium",
                            "detail": f"Medium-risk institution: {medium_match}",
                        }
                    )

                    findings_added = True

        # Check country + institution combination if not already flagged
        if not findings_added and country in COUNTRY_RISK_TIERS:
            tier_info = COUNTRY_RISK_TIERS[country]

            # Check for government control keywords
            has_control_keywords = _has_government_control_indicators(institution)

            if has_control_keywords:
                result.findings.append(
                    Finding(
                        source="institutional_risk",
                        category="institutional_risk",
                        title=f"MEDIUM: Institution in {country} with state control keywords",
                        detail=(
                            f"Institution '{institution}' from {country} ({tier_info['description']}) "
                            f"shows government control indicators. "
                            f"Due diligence recommended."
                        ),
                        severity=tier_info["default_severity"],
                        confidence=0.70,
                        raw_data={"country": country, "has_control_keywords": True},
                    )
                )

                result.risk_signals.append(
                    {
                        "signal": f"country_risk_{country}",
                        "severity": tier_info["default_severity"],
                        "detail": f"Institution from {country} with government control ties",
                    }
                )

                findings_added = True
            else:
                # Just country risk
                result.findings.append(
                    Finding(
                        source="institutional_risk",
                        category="institutional_risk",
                        title=f"Institution from {country} - default country risk assessment",
                        detail=(
                            f"Institution from {country} ({tier_info['description']}). "
                            f"Standard due diligence recommended."
                        ),
                        severity=tier_info["default_severity"],
                        confidence=0.70,
                        raw_data={"country": country},
                    )
                )

                result.risk_signals.append(
                    {
                        "signal": f"country_risk_{country}",
                        "severity": tier_info["default_severity"],
                        "detail": f"Institution from {country}",
                    }
                )

                findings_added = True

        # If no findings yet, provide info
        if not findings_added:
            result.findings.append(
                Finding(
                    source="institutional_risk",
                    category="institutional_risk",
                    title="Institutional risk: No major indicators",
                    detail=(
                        f"Institution '{institution}' does not match known high-risk institutions. "
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
