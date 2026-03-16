"""
USML Category Risk Classifier

Classifies vendor by US Munitions List (USML) category and assesses
export control risk for ITAR compliance.

USML is part of the International Traffic in Arms Regulations (ITAR).
Categories I-XXI define defense articles subject to State Department control.

Reference: 22 CFR 121 (ITAR)
https://www.ecfr.gov/current/title-22/section-121
"""

import time
from . import EnrichmentResult, Finding


# USML Category definitions and risk tiers
USML_CATEGORIES = {
    "I": {
        "name": "Firearms, close assault weapons and components",
        "section": "22 CFR 121.1",
        "tier": "HIGH",
        "severity": "high",
    },
    "II": {
        "name": "Flame guns and components",
        "section": "22 CFR 121.2",
        "tier": "MEDIUM",
        "severity": "medium",
    },
    "III": {
        "name": "Ammunition",
        "section": "22 CFR 121.3",
        "tier": "HIGH",
        "severity": "high",
    },
    "IV": {
        "name": "Launch vehicles, missiles, bombs and components",
        "section": "22 CFR 121.4",
        "tier": "HIGHEST",
        "severity": "critical",
    },
    "V": {
        "name": "Explosives and energetic materials",
        "section": "22 CFR 121.5",
        "tier": "HIGH",
        "severity": "high",
    },
    "VI": {
        "name": "Naval vessels and components",
        "section": "22 CFR 121.6",
        "tier": "MEDIUM",
        "severity": "medium",
    },
    "VII": {
        "name": "Ground effect vehicles, motor vehicles, trailers and components",
        "section": "22 CFR 121.7",
        "tier": "MEDIUM",
        "severity": "medium",
    },
    "VIII": {
        "name": "Aircraft and associated equipment",
        "section": "22 CFR 121.8",
        "tier": "MEDIUM",
        "severity": "medium",
    },
    "IX": {
        "name": "Military training equipment",
        "section": "22 CFR 121.9",
        "tier": "LOWER",
        "severity": "medium",
    },
    "X": {
        "name": "Protective personnel equipment and components",
        "section": "22 CFR 121.10",
        "tier": "LOWER",
        "severity": "medium",
    },
    "XI": {
        "name": "Military electronics",
        "section": "22 CFR 121.11",
        "tier": "HIGH",
        "severity": "high",
    },
    "XII": {
        "name": "Fire control systems and components",
        "section": "22 CFR 121.12",
        "tier": "HIGH",
        "severity": "high",
    },
    "XIII": {
        "name": "Materials and munitions",
        "section": "22 CFR 121.13",
        "tier": "LOWER",
        "severity": "medium",
    },
    "XIV": {
        "name": "Toxicological agents and equipment",
        "section": "22 CFR 121.14",
        "tier": "LOWER",
        "severity": "medium",
    },
    "XV": {
        "name": "Spacecraft and related articles",
        "section": "22 CFR 121.15",
        "tier": "HIGHEST",
        "severity": "critical",
    },
    "XVI": {
        "name": "Nuclear weapons-related articles",
        "section": "22 CFR 121.16",
        "tier": "HIGHEST",
        "severity": "critical",
    },
    "XVII": {
        "name": "Classified articles and services",
        "section": "22 CFR 121.17",
        "tier": "HIGHEST",
        "severity": "critical",
    },
    "XVIII": {
        "name": "Directed energy weapons",
        "section": "22 CFR 121.18",
        "tier": "HIGHEST",
        "severity": "critical",
    },
    "XIX": {
        "name": "Submersible vessels and components",
        "section": "22 CFR 121.19",
        "tier": "MEDIUM",
        "severity": "medium",
    },
    "XX": {
        "name": "Submersible vessels and related articles",
        "section": "22 CFR 121.20",
        "tier": "MEDIUM",
        "severity": "medium",
    },
    "XXI": {
        "name": "Articles for military use",
        "section": "22 CFR 121.21",
        "tier": "MEDIUM",
        "severity": "medium",
    },
}

# Keyword patterns for inferring USML categories from vendor name
CATEGORY_KEYWORDS = {
    "IV": ["missile", "launch vehicle", "rocket", "propulsion", "ballistic"],
    "XV": ["spacecraft", "satellite", "space", "orbital", "payload"],
    "XVI": ["nuclear", "fissile", "weapons", "warhead"],
    "XVIII": ["directed energy", "laser", "particle beam", "electromagnetic"],
    "I": ["firearm", "rifle", "handgun", "pistol", "gun"],
    "III": ["ammunition", "munitions", "ordnance", "cartridge"],
    "XII": ["fire control", "targeting", "radar", "guidance", "aiming"],
    "XI": ["avionics", "electronics", "sonar", "sensor", "transmitter"],
    "VIII": ["aircraft", "helicopter", "fighter", "bomber", "airframe"],
    "VI": ["naval", "warship", "submarine", "destroyer", "frigate"],
    "VII": ["tank", "armored vehicle", "military vehicle", "personnel carrier"],
}

# Indicators of ITAR vs EAR classification
ITAR_KEYWORDS = [
    "state controlled",
    "military use",
    "defense article",
    "armed forces",
    "weapons system",
]
EAR_KEYWORDS = ["dual-use", "commercial", "civilian application", "non-military"]


def _infer_category_from_name(vendor_name: str) -> str | None:
    """
    Attempt to infer USML category from vendor name keywords.
    Returns category letter (e.g., "IV") or None.
    """
    name_lower = vendor_name.lower()

    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return cat

    return None


def _classify_itar_vs_ear(vendor_name: str, category: str | None) -> tuple[str, float]:
    """
    Classify whether item is likely ITAR (State Dept) or EAR (Commerce Dept).
    Returns (classification, confidence).
    """
    name_lower = vendor_name.lower()

    # Check for ITAR indicators
    itar_matches = sum(1 for kw in ITAR_KEYWORDS if kw in name_lower)
    ear_matches = sum(1 for kw in EAR_KEYWORDS if kw in name_lower)

    if itar_matches > ear_matches:
        return ("ITAR - State Department", 0.75)
    elif ear_matches > itar_matches:
        return ("EAR - Commerce Department", 0.75)

    # Default based on category if specified
    if category in ["IV", "XV", "XVI", "XVIII"]:
        return ("ITAR - State Department", 0.85)

    return ("ITAR - State Department (default)", 0.65)


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """
    Classify vendor by USML category and assess ITAR export control risk.
    Expects optional usml_category in **ids.
    """
    t0 = time.time()
    result = EnrichmentResult(source="usml_classifier", vendor_name=vendor_name)

    try:
        # Check if explicit USML category provided
        usml_category = ids.get("usml_category", "").upper()

        if not usml_category:
            # Try to infer from vendor name
            inferred = _infer_category_from_name(vendor_name)
            if inferred:
                usml_category = inferred

        if usml_category and usml_category in USML_CATEGORIES:
            # Category found - classify risk
            cat_info = USML_CATEGORIES[usml_category]
            classification, ear_itar_conf = _classify_itar_vs_ear(
                vendor_name, usml_category
            )

            result.findings.append(
                Finding(
                    source="usml_classifier",
                    category="export_control",
                    title=f"USML Category {usml_category}: {cat_info['name']}",
                    detail=(
                        f"Vendor subject to ITAR export controls. "
                        f"USML Category {usml_category}: {cat_info['name']}. "
                        f"Regulated under {cat_info['section']}. "
                        f"Export license required for defense articles. "
                        f"Likely classification: {classification}"
                    ),
                    severity=cat_info["severity"],
                    confidence=0.90,
                    url="https://www.ecfr.gov/current/title-22/section-121",
                    raw_data={
                        "category": usml_category,
                        "tier": cat_info["tier"],
                        "classification": classification,
                        "itar_vs_ear_confidence": ear_itar_conf,
                    },
                )
            )

            result.risk_signals.append(
                {
                    "signal": f"usml_category_{usml_category}",
                    "severity": cat_info["severity"],
                    "detail": f"USML Category {usml_category}: {cat_info['name']}",
                }
            )

        elif usml_category:
            # Invalid category provided
            result.findings.append(
                Finding(
                    source="usml_classifier",
                    category="export_control",
                    title=f"USML: Invalid category {usml_category}",
                    detail=(
                        f"Category {usml_category} not recognized. "
                        f"Valid USML categories: I-XXI. "
                        f"Verify category against 22 CFR 121."
                    ),
                    severity="info",
                    confidence=0.8,
                )
            )

        else:
            # No category found - generic ITAR advisory
            classification, conf = _classify_itar_vs_ear(vendor_name, None)

            result.findings.append(
                Finding(
                    source="usml_classifier",
                    category="export_control",
                    title="USML: Category not specified",
                    detail=(
                        f"No USML category provided for '{vendor_name}'. "
                        f"If vendor manufactures/supplies defense articles, "
                        f"must determine applicable USML category (I-XXI) and obtain "
                        f"State Department export license. Assumed classification: {classification}."
                    ),
                    severity="medium",
                    confidence=0.65,
                    url="https://www.ecfr.gov/current/title-22/section-121",
                    raw_data={"inferred_classification": classification},
                )
            )

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
