"""
CFIUS Risk Indicator Connector

Assesses Committee on Foreign Investment in the United States (CFIUS) risk
based on country of origin and vendor characteristics.

CFIUS reviews foreign investments in US companies/assets for national security.
Countries with elevated scrutiny: China (CN), Russia (RU), Iran (IR),
North Korea (KP), Cuba (CU), Venezuela (VE).

High risk factors:
- From CFIUS-scrutiny country + State-owned entity
- From CFIUS-scrutiny country + Defense/critical infrastructure sector
- Foreign ownership of US technology/infrastructure company

CFIUS Info: https://home.treasury.gov/policy-issues/cfius-reviews
"""

import time

from . import EnrichmentResult, Finding

# Countries with elevated CFIUS scrutiny
CFIUS_SCRUTINY_COUNTRIES = {
    "CN": "China - High-tech competition, state control concerns",
    "RU": "Russia - Geopolitical adversary, sanctions regime",
    "IR": "Iran - Sanctioned entity, dual-use concerns",
    "KP": "North Korea - Sanctioned entity, weapons programs",
    "CU": "Cuba - Sanctioned entity, travel restrictions",
    "VE": "Venezuela - Sanctioned entity, authoritarian regime",
    "KZ": "Kazakhstan - Strategic minerals, border risk",
    "PK": "Pakistan - Defense/nuclear proliferation concerns",
    "SA": "Saudi Arabia - Defense/surveillance technology concerns",
}

# Sectors with CFIUS interest
CFIUS_SENSITIVE_SECTORS = [
    "defense",
    "aerospace",
    "semiconductors",
    "telecom",
    "critical infrastructure",
    "utilities",
    "energy",
    "financial",
    "infrastructure",
    "technology",
    "ai",
    "encryption",
    "biotech",
    "nuclear",
]

# Indicators of state ownership/control
STATE_OWNED_INDICATORS = [
    "state",
    "national",
    "government",
    "ministry",
    "authority",
    "public enterprise",
    "soe",  # State-owned enterprise
]


def _has_state_ownership_indicator(vendor_name: str) -> bool:
    """Check if vendor name suggests state ownership."""
    name_lower = vendor_name.lower()
    return any(indicator in name_lower for indicator in STATE_OWNED_INDICATORS)


def _has_sensitive_sector_indicator(vendor_name: str) -> bool:
    """Check if vendor name suggests sensitive sector."""
    name_lower = vendor_name.lower()
    return any(sector in name_lower for sector in CFIUS_SENSITIVE_SECTORS)


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Assess CFIUS risk based on country and vendor characteristics."""
    t0 = time.time()
    result = EnrichmentResult(source="cfius_risk", vendor_name=vendor_name)

    try:
        # Normalize country code
        country = (country or "").upper().strip()

        if not country:
            result.findings.append(Finding(
                source="cfius_risk",
                category="cfius_risk",
                title="CFIUS: Country of origin unknown",
                detail="Cannot assess CFIUS risk without country information. Recommend identifying vendor origin.",
                severity="info",
                confidence=0.5,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Check if country has elevated CFIUS scrutiny
        if country in CFIUS_SCRUTINY_COUNTRIES:
            scrutiny_reason = CFIUS_SCRUTINY_COUNTRIES[country]

            # Check for state ownership indicators
            is_state_owned = _has_state_ownership_indicator(vendor_name)

            # Check for sensitive sector indicators
            is_sensitive_sector = _has_sensitive_sector_indicator(vendor_name)

            # Risk assessment
            if is_state_owned or is_sensitive_sector:
                # High risk: CFIUS-scrutiny country + sensitive characteristics
                severity = "high"
                confidence = 0.85 if (is_state_owned and is_sensitive_sector) else 0.75

                detail = (
                    f"Vendor from {country} ({scrutiny_reason}) with risk indicators: "
                    f"State-owned={is_state_owned}, Sensitive sector={is_sensitive_sector}. "
                    f"CFIUS review likely for US investments/acquisitions."
                )

                result.findings.append(Finding(
                    source="cfius_risk",
                    category="cfius_risk",
                    title=f"CFIUS: HIGH RISK - {country} origin with sensitive characteristics",
                    detail=detail,
                    severity=severity,
                    confidence=confidence,
                    url="https://home.treasury.gov/policy-issues/cfius-reviews",
                    raw_data={
                        "country": country,
                        "state_owned": is_state_owned,
                        "sensitive_sector": is_sensitive_sector,
                    },
                ))

                result.risk_signals.append({
                    "signal": "cfius_high_risk",
                    "severity": "high",
                    "detail": f"CFIUS review likely for investments from {country}",
                })
            else:
                # Medium/elevated risk: CFIUS-scrutiny country, generic vendor
                detail = (
                    f"Vendor from {country} ({scrutiny_reason}). "
                    f"CFIUS may review foreign investments depending on transaction type and asset sensitivity."
                )

                result.findings.append(Finding(
                    source="cfius_risk",
                    category="cfius_risk",
                    title=f"CFIUS: ELEVATED RISK - {country} origin",
                    detail=detail,
                    severity="medium",
                    confidence=0.75,
                    url="https://home.treasury.gov/policy-issues/cfius-reviews",
                    raw_data={"country": country},
                ))

                result.risk_signals.append({
                    "signal": "cfius_elevated_risk",
                    "severity": "medium",
                    "detail": f"CFIUS scrutiny likely for {country} vendor",
                })
        else:
            # Lower risk: Vendor from country without elevated scrutiny
            result.findings.append(Finding(
                source="cfius_risk",
                category="cfius_risk",
                title=f"CFIUS: Standard risk assessment - {country} origin",
                detail=(
                    f"Vendor from {country} has lower default CFIUS scrutiny. "
                    f"CFIUS review depends on transaction type, asset sensitivity, and specific facts."
                ),
                severity="info",
                confidence=0.8,
                url="https://home.treasury.gov/policy-issues/cfius-reviews",
                raw_data={"country": country},
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
