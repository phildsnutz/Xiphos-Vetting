"""
Foreign Talent Program Screening

Identifies researchers and scholars recruited by foreign government talent
programs that may create conflicts of interest or facilitate technology transfer.

Known programs:
- China: Thousand Talents Plan (1000 Talents), Changjiang Scholars, Hundred Talents (100 Talents),
  Recruitment Program of Global Experts, Spring Light Plan, Young Thousand Talents
- Russia: Global Education program, Megagrants
- Iran: Elite Foundation and other recruitment initiatives

Also screens PLA-affiliated universities (Seven Sons of National Defence).
Flags institutions under China's Military-Civil Fusion (MCF) strategy.

Reference: NCSC China Talent Recruitment Programs Report
https://www.ncsc.gov.cn
"""

import time
import difflib
from . import EnrichmentResult, Finding


# Known talent program names and organizations
TALENT_PROGRAMS = {
    "CN": {
        "programs": [
            "Thousand Talents Plan",
            "1000 Talents",
            "1000 Young Talents",
            "Changjiang Scholars",
            "Hundred Talents",
            "100 Talents",
            "Recruitment Program of Global Experts",
            "RPGE",
            "Spring Light Plan",
            "Young Thousand Talents",
            "Youth Talents Program",
            "Qiushi Scholars",
        ],
        "severity": "high",
    },
    "RU": {
        "programs": [
            "Global Education Program",
            "Russian Global Education Program",
            "Megagrants",
            "Megagrant Program",
            "Federal Scholarship Program",
        ],
        "severity": "high",
    },
    "IR": {
        "programs": [
            "Elite Foundation",
            "Iranian Talent Recruitment",
            "Revolutionary Guard Education Programs",
        ],
        "severity": "critical",
    },
}

# PLA-affiliated universities (Seven Sons of National Defence + others)
PLA_AFFILIATED_INSTITUTIONS = [
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
    "Nanjing Aeronautical Institute",
    "National University of Defense Technology",
    "NUDT",
    "Beijing Institute of Technology",
    "BIT",
    # Additional PLA-affiliated universities
    "Dalian Maritime University",
    "Shanghai Jiao Tong University",  # SJTU (defense collaborations)
    "Tsinghua University",  # TSING HUA (national defense research)
    "University of Science and Technology of China",
    "USTC",
    "Xiamen University",
]

# Institutions under Military-Civil Fusion strategy
MCF_STRATEGY_INSTITUTIONS = [
    "China Academy of Sciences",
    "Chinese Academy of Engineering",
    "Institute of Engineering Mechanics",
    "Institute of Applied Physics and Computational Mathematics",
    "China National Space Administration",
    "CNSA",
    "Aerospace Corporation China",
    "State Key Laboratory",
    "National Laboratory",
    "Research Institute of China State Shipbuilding",
    "China Aviation Industry Corporation",
]

# Indicators in institution names suggesting military/defense ties
MILITARY_INSTITUTION_KEYWORDS = [
    "defense",
    "military",
    "aerospace",
    "spacecraft",
    "missiles",
    "rockets",
    "weaponry",
    "ordnance",
    "armed forces",
    "national defense",
    "state key laboratory",
    "national laboratory",
    "academy of sciences",
    "engineering research",
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


def _has_military_institution_keywords(institution_name: str) -> bool:
    """Check if institution name suggests military/defense ties."""
    inst_lower = institution_name.lower()
    return any(kw in inst_lower for kw in MILITARY_INSTITUTION_KEYWORDS)


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """
    Screen researchers and institutions for foreign talent program affiliation.
    Expects optional home_institution in **ids.
    """
    t0 = time.time()
    result = EnrichmentResult(source="foreign_talent_programs", vendor_name=vendor_name)

    try:
        country = (country or "").upper().strip()
        home_institution = ids.get("home_institution", "")

        findings_added = False

        # Check if vendor name matches known talent program
        vendor_lower = vendor_name.lower()

        for country_code, prog_info in TALENT_PROGRAMS.items():
            for program in prog_info["programs"]:
                if program.lower() in vendor_lower:
                    result.findings.append(
                        Finding(
                            source="foreign_talent_programs",
                            category="foreign_talent_program",
                            title=f"CRITICAL: {program} affiliation detected",
                            detail=(
                                f"Vendor/researcher name or affiliation matches known foreign talent program: {program}. "
                                f"Such programs may require disclosure of foreign support and create conflicts of interest. "
                                f"Verify: (1) enrollment status and obligations; (2) funding sources; "
                                f"(3) IP assignment agreements; (4) export control obligations."
                            ),
                            severity="critical" if country_code == "IR" else "high",
                            confidence=0.85,
                            raw_data={"program": program, "country": country_code},
                        )
                    )

                    result.risk_signals.append(
                        {
                            "signal": f"talent_program_{country_code}",
                            "severity": "critical" if country_code == "IR" else "high",
                            "detail": f"{program} affiliation",
                        }
                    )

                    findings_added = True
                    break

        # Check institution affiliation if provided
        if home_institution:
            # Check for PLA-affiliated universities
            is_pla, pla_score, pla_name = _fuzzy_match_institution(
                home_institution, PLA_AFFILIATED_INSTITUTIONS, threshold=0.70
            )

            if is_pla:
                result.findings.append(
                    Finding(
                        source="foreign_talent_programs",
                        category="foreign_talent_program",
                        title=f"CRITICAL: PLA-affiliated university detected ({pla_name})",
                        detail=(
                            f"Institution '{home_institution}' matches PLA-affiliated university: {pla_name}. "
                            f"PLA-affiliated institutions: Harbin Tech, Harbin Engineering, BUAA, NWPU, NUAA, NUDT, BIT. "
                            f"These institutions have direct military/defense roles and dual civilian-military structures. "
                            f"Enhanced due diligence required. Verify independence and authorization for collaborations."
                        ),
                        severity="critical",
                        confidence=0.85,
                        raw_data={"matched_institution": pla_name, "match_score": pla_score},
                    )
                )

                result.risk_signals.append(
                    {
                        "signal": "pla_affiliated_institution",
                        "severity": "critical",
                        "detail": f"PLA-affiliated university: {pla_name}",
                    }
                )

                findings_added = True

            # Check for Military-Civil Fusion institutions
            else:
                is_mcf, mcf_score, mcf_name = _fuzzy_match_institution(
                    home_institution, MCF_STRATEGY_INSTITUTIONS, threshold=0.70
                )

                if is_mcf:
                    result.findings.append(
                        Finding(
                            source="foreign_talent_programs",
                            category="foreign_talent_program",
                            title=f"HIGH: Military-Civil Fusion institution ({mcf_name})",
                            detail=(
                                f"Institution '{home_institution}' matches known Military-Civil Fusion (MCF) entity: {mcf_name}. "
                                f"MCF strategy blurs lines between civilian research and military applications. "
                                f"Enhanced vetting recommended."
                            ),
                            severity="high",
                            confidence=0.75,
                            raw_data={"mcf_entity": mcf_name, "match_score": mcf_score},
                        )
                    )

                    result.risk_signals.append(
                        {
                            "signal": "military_civil_fusion",
                            "severity": "high",
                            "detail": f"MCF institution: {mcf_name}",
                        }
                    )

                    findings_added = True

                # Check for military/defense keywords in institution name
                elif _has_military_institution_keywords(home_institution):
                    result.findings.append(
                        Finding(
                            source="foreign_talent_programs",
                            category="foreign_talent_program",
                            title="MEDIUM: Institution with military/defense keywords",
                            detail=(
                                f"Institution '{home_institution}' contains military or defense-related keywords. "
                                f"Recommend verifying institutional structure and research focus."
                            ),
                            severity="medium",
                            confidence=0.70,
                        )
                    )

                    result.risk_signals.append(
                        {
                            "signal": "military_institution_keywords",
                            "severity": "medium",
                            "detail": "Military/defense keywords in institution name",
                        }
                    )

                    findings_added = True

        # If no findings yet, provide generic screening result
        if not findings_added:
            result.findings.append(
                Finding(
                    source="foreign_talent_programs",
                    category="foreign_talent_program",
                    title="Foreign talent programs: No match found",
                    detail=(
                        f"'{vendor_name}' does not match known talent program affiliations or PLA-affiliated institutions. "
                        f"Standard due diligence recommended for foreign collaborators."
                    ),
                    severity="info",
                    confidence=0.80,
                )
            )

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
