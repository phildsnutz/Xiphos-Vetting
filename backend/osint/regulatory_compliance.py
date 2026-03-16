"""
Regulatory Compliance Check

Screens vendors against multiple regulatory databases covering:
- FDA debarment list (pharmaceutical/medical device companies)
- EU REACH/RoHS high-concern substance (HCS) list
- Conflict minerals sourcing indicators
- SEC conflict minerals reporting

High-risk sector combinations:
- Pharma + FDA debarment = critical
- Electronics/manufacturing + conflict minerals = high
- Pharma + FDA debarment + high-concern substances = critical

Reference:
- FDA: https://www.fda.gov/drugs/guidance-compliance-regulatory-information/import-alerts
- EU REACH: https://echa.europa.eu/information-on-chemicals
- SEC Conflict Minerals: https://www.sec.gov/cgi-bin/browse-edgar
"""

import time
from . import EnrichmentResult, Finding


# Simulated FDA debarment list (pharma/device companies)
FDA_DEBARRED_ENTITIES = [
    "BadPharma Solutions",
    "Defective Devices Corp",
    "FDA Violation Inc",
    "Adulterated Products LLC",
    "Counterfeit Pharma Trading",
    "Unapproved Drug Manufacturer",
    "Contaminated Supplier Services",
]

# EU high-concern substances (simplified REACH/RoHS focus)
REACH_HOCS_KEYWORDS = [
    "lead",
    "mercury",
    "cadmium",
    "hexavalent chromium",
    "phthalates",
    "pbde",
    "brominated",
    "chlorinated",
    "asbestos",
    "asbest",
]

# Conflict minerals countries/regions
CONFLICT_MINERALS_REGIONS = {
    "CD": "Democratic Republic of Congo - High conflict mineral risk",
    "RW": "Rwanda - Transhipment hub for conflict minerals",
    "UG": "Uganda - Conflict minerals supply chain",
    "TZ": "Tanzania - Mineral processing and transhipment",
    "AO": "Angola - Diamond and mineral concerns",
    "ZM": "Zambia - Mineral processing",
    "ZW": "Zimbabwe - Mineral sourcing concerns",
    "MW": "Malawi - Mineral sourcing",
}

# Known conflict mineral sourcing entities (simulated)
CONFLICT_MINERALS_ENTITIES = [
    "Global Minerals Trading",
    "African Ore Imports",
    "Tantalum Supply Corp",
    "Tin Processing International",
    "Cobalt Trading Services",
    "Conflict-Free Metals Inc",  # Note: some legitimate conflict-free entities exist
]

# Sectors requiring compliance checks
REGULATED_SECTORS = {
    "pharma": ["pharmaceutical", "drug", "medicine", "biotech"],
    "devices": ["medical device", "medical equipment", "diagnostic"],
    "electronics": ["semiconductor", "circuit", "electronics", "computer"],
    "chemicals": ["chemical", "chemical manufacturing", "polymer"],
    "raw_materials": ["mining", "ore", "mineral", "refining", "smelting"],
}


def _is_sector(vendor_name: str, sector_keywords: list[str]) -> bool:
    """Check if vendor name suggests specified sector."""
    name_lower = vendor_name.lower()
    return any(kw in name_lower for kw in sector_keywords)


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """
    Check vendor against regulatory compliance databases.
    Expects optional industry_sector and product_category in **ids.
    """
    t0 = time.time()
    result = EnrichmentResult(source="regulatory_compliance", vendor_name=vendor_name)

    try:
        country = (country or "").upper().strip()
        industry_sector = ids.get("industry_sector", "").lower()
        product_category = ids.get("product_category", "").lower()

        vendor_lower = vendor_name.lower()
        findings_added = False

        # FDA DEBARMENT CHECK (Pharmaceutical/Device focused)
        is_pharma = (
            _is_sector(vendor_name, REGULATED_SECTORS.get("pharma", []))
            or "pharma" in industry_sector
        )
        is_device = (
            _is_sector(vendor_name, REGULATED_SECTORS.get("devices", []))
            or "device" in industry_sector
        )

        if is_pharma or is_device:
            # Check FDA debarment
            for debarred in FDA_DEBARRED_ENTITIES:
                if debarred.lower() in vendor_lower:
                    result.findings.append(
                        Finding(
                            source="regulatory_compliance",
                            category="regulatory_compliance",
                            title=f"CRITICAL: FDA debarment - {debarred}",
                            detail=(
                                f"Vendor {debarred} is on FDA debarment list. "
                                f"Debarred from supplying pharmaceutical or medical device products. "
                                f"Cannot be used as supplier or contractor. "
                                f"Verify current status at https://www.fda.gov/drugs/guidance-compliance-regulatory-information/import-alerts"
                            ),
                            severity="critical",
                            confidence=0.90,
                            url="https://www.fda.gov/drugs/guidance-compliance-regulatory-information/import-alerts",
                        )
                    )

                    result.risk_signals.append(
                        {
                            "signal": "fda_debarment",
                            "severity": "critical",
                            "detail": f"FDA debarred: {debarred}",
                        }
                    )

                    findings_added = True
                    break

        # REACH/RoHS HIGH-CONCERN SUBSTANCES CHECK (Electronics/Manufacturing)
        is_electronics = (
            _is_sector(vendor_name, REGULATED_SECTORS.get("electronics", []))
            or "electronics" in industry_sector
        )
        is_chemicals = (
            _is_sector(vendor_name, REGULATED_SECTORS.get("chemicals", []))
            or "chemical" in industry_sector
        )

        if (is_electronics or is_chemicals) and not findings_added:
            has_hcs_keywords = any(kw in vendor_lower for kw in REACH_HOCS_KEYWORDS)

            if has_hcs_keywords:
                result.findings.append(
                    Finding(
                        source="regulatory_compliance",
                        category="regulatory_compliance",
                        title="HIGH: Vendor deals with EU REACH high-concern substances (HCS)",
                        detail=(
                            f"Vendor '{vendor_name}' appears to supply or manufacture "
                            f"REACH-regulated high-concern substances (lead, mercury, cadmium, etc.). "
                            f"Must comply with EU REACH registration, authorization, and restriction requirements. "
                            f"RoHS compliance required for electronics placed on EU market. "
                            f"Verify compliance documentation."
                        ),
                        severity="high",
                        confidence=0.70,
                        url="https://echa.europa.eu/information-on-chemicals",
                    )
                )

                result.risk_signals.append(
                    {
                        "signal": "reach_hcs_supplier",
                        "severity": "high",
                        "detail": "Supplies REACH high-concern substances",
                    }
                )

                findings_added = True

        # CONFLICT MINERALS CHECK (Raw materials/Electronics)
        is_raw_materials = (
            _is_sector(vendor_name, REGULATED_SECTORS.get("raw_materials", []))
            or "mining" in industry_sector
        )

        if (is_raw_materials or is_electronics or "minerals" in product_category) and not findings_added:
            # Check country of origin
            if country in CONFLICT_MINERALS_REGIONS:
                region_info = CONFLICT_MINERALS_REGIONS[country]

                result.findings.append(
                    Finding(
                        source="regulatory_compliance",
                        category="regulatory_compliance",
                        title=f"HIGH: Conflict minerals risk - sourcing from {country}",
                        detail=(
                            f"Vendor from {country} ({region_info}). "
                            f"High conflict minerals risk. SEC requires reporting of conflict minerals sourcing. "
                            f"If vendor uses tantalum, tin, tungsten, gold from high-risk regions, "
                            f"must verify conflict-free sourcing. "
                            f"Recommend requesting Conflict Minerals Declaration."
                        ),
                        severity="high",
                        confidence=0.80,
                        url="https://www.sec.gov/cgi-bin/browse-edgar",
                        raw_data={"country": country, "region_risk": region_info},
                    )
                )

                result.risk_signals.append(
                    {
                        "signal": "conflict_minerals_country_risk",
                        "severity": "high",
                        "detail": f"Sourcing from conflict minerals region: {country}",
                    }
                )

                findings_added = True

            # Check for conflict minerals entities
            elif not findings_added:
                for conflict_entity in CONFLICT_MINERALS_ENTITIES:
                    if conflict_entity.lower() in vendor_lower:
                        result.findings.append(
                            Finding(
                                source="regulatory_compliance",
                                category="regulatory_compliance",
                                title=f"HIGH: Known conflict minerals supplier - {conflict_entity}",
                                detail=(
                                    f"Vendor '{vendor_name}' matches known or suspected conflict minerals trader: {conflict_entity}. "
                                    f"Must verify conflict-free sourcing and obtain conflict minerals declarations. "
                                    f"Recommend enhanced due diligence on mineral sourcing practices."
                                ),
                                severity="high",
                                confidence=0.75,
                            )
                        )

                        result.risk_signals.append(
                            {
                                "signal": "conflict_minerals_entity",
                                "severity": "high",
                                "detail": f"Suspected conflict minerals supplier: {conflict_entity}",
                            }
                        )

                        findings_added = True
                        break

        # Generic compliance finding if no specific violations found
        if not findings_added:
            if industry_sector or product_category:
                result.findings.append(
                    Finding(
                        source="regulatory_compliance",
                        category="regulatory_compliance",
                        title="Regulatory compliance: Standard screening completed",
                        detail=(
                            f"Vendor '{vendor_name}' (sector: {industry_sector or 'not specified'}) "
                            f"shows no major regulatory compliance violations in simulated screening. "
                            f"Recommend verifying against actual regulatory databases (FDA, REACH, SEC)."
                        ),
                        severity="info",
                        confidence=0.70,
                    )
                )
            else:
                result.findings.append(
                    Finding(
                        source="regulatory_compliance",
                        category="regulatory_compliance",
                        title="Regulatory compliance: Sector information needed",
                        detail=(
                            f"Industry sector not specified. Cannot perform targeted regulatory compliance check. "
                            f"Provide industry_sector (pharma, devices, electronics, chemicals, raw_materials) for full screening."
                        ),
                        severity="info",
                        confidence=0.5,
                    )
                )

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
