"""
Xiphos FGAMLogit v5.0
Sensitivity-Aware Factored Generalized Additive Logistic Model

CANONICAL v5.0 scoring engine. Clean-break replacement for Beta(2,8) Bayesian.

Architecture:
  Layer 1 (Regulatory Gate Engine)  ->  regulatory_gates.py
  Layer 2 (Probabilistic Risk)      ->  THIS FILE
  Layer Integration                 ->  integrate_layers() in this file

Design:
  - Pure Python, zero external dependencies (no numpy / scipy / sklearn)
  - 14 factors: 5 commercial + 9 DoD-specific
  - Sensitivity-aware weights: factor weights and baseline vary by program context
  - Two-way interaction terms for synergistic risk combinations
  - Wilson-score confidence intervals (effective-n based on sensitivity + regulatory status)
  - Counterfactual Marginal Information Values (MIV)
  - Full backward-compatible output via ScoringResultV5 dataclass
  - Allied-nation false-positive mitigation on sanctions hard stops

Model version: 5.0-FGAMLogit-DoD-Dual-Vertical
Author:        Xiphos Platform
Date:          March 2026
"""

import math
from dataclasses import dataclass, field
from typing import Optional
from ofac import screen_name, ScreeningResult


# =============================================================================
# PURE PYTHON MATH UTILITIES
# =============================================================================

def _logistic(x: float) -> float:
    """Numerically stable logistic sigmoid: 1 / (1 + exp(-x))."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    else:
        e = math.exp(x)
        return e / (1.0 + e)


def _logit(p: float) -> float:
    """Log-odds: log(p / (1-p)). Clamps to avoid infinity."""
    p = max(1e-9, min(1.0 - 1e-9, p))
    return math.log(p / (1.0 - p))


def _wilson_ci(p_hat: float, n_effective: float, z: float = 1.96) -> tuple:
    """
    Wilson score confidence interval.
    Works for fractional n_effective (effective sample size).
    Returns (lower, upper) clamped to [0, 1].
    Ref: E.B. Wilson (1927)
    """
    n = max(n_effective, 1.0)
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denom
    spread = z * math.sqrt(p_hat * (1.0 - p_hat) / n + z2 / (4.0 * n * n)) / denom
    lo = max(0.0, center - spread)
    hi = min(1.0, center + spread)
    return (round(lo, 4), round(hi, 4))


# =============================================================================
# GEOGRAPHY RISK TABLE
# =============================================================================

GEO_RISK: dict[str, float] = {
    "US": 0.02, "GB": 0.03, "CA": 0.03, "AU": 0.03, "NZ": 0.04,
    "DE": 0.05, "FR": 0.05, "JP": 0.05, "KR": 0.08, "IL": 0.10,
    "NL": 0.05, "NO": 0.05, "DK": 0.05, "SE": 0.05, "FI": 0.06,
    "IT": 0.07, "ES": 0.07, "PL": 0.08, "CZ": 0.08,
    "BR": 0.18, "IN": 0.20, "MX": 0.22, "TR": 0.25, "AE": 0.15,
    "SA": 0.22, "TH": 0.18, "MY": 0.15, "SG": 0.06, "TW": 0.08,
    "AZ": 0.40, "PK": 0.45, "UA": 0.35, "BY": 0.55, "VE": 0.50,
    "MM": 0.50, "BD": 0.35, "VN": 0.30, "EG": 0.28, "NG": 0.38,
    "RU": 0.85, "CN": 0.45, "IR": 0.92, "KP": 0.98, "SY": 0.90,
    "CU": 0.70, "AF": 0.65, "SO": 0.60, "SD": 0.75, "YE": 0.55,
}

# Allied nations for false-positive mitigation (Five Eyes + NATO/key allies)
ALLIED_NATIONS = {
    "US", "GB", "CA", "AU", "NZ",
    "DE", "FR", "NL", "NO", "DK", "SE", "FI", "IT", "ES", "PL", "CZ",
    "JP", "KR", "IL", "SG", "TW",
}

COMPREHENSIVELY_SANCTIONED = {"RU", "IR", "KP", "SY", "CU"}

def geo_risk(cc: str) -> float:
    return GEO_RISK.get(cc.upper(), 0.30)


# =============================================================================
# INPUT DATACLASSES
# =============================================================================

@dataclass
class OwnershipProfile:
    publicly_traded: bool = False
    state_owned: bool = False
    beneficial_owner_known: bool = False
    ownership_pct_resolved: float = 0.0
    shell_layers: int = 0
    pep_connection: bool = False
    foreign_ownership_pct: float = 0.0
    foreign_ownership_is_allied: bool = True


@dataclass
class DataQuality:
    has_lei: bool = False
    has_cage: bool = False
    has_duns: bool = False
    has_tax_id: bool = False
    has_audited_financials: bool = False
    years_of_records: int = 0


@dataclass
class ExecProfile:
    known_execs: int = 0
    adverse_media: int = 0
    pep_execs: int = 0
    litigation_history: int = 0


@dataclass
class DoDContext:
    """
    DoD-specific context for Layer 2 scoring.
    All fields default to benign/non-applicable so commercial
    use requires no changes to existing call sites.
    """
    sensitivity: str = "COMMERCIAL"
    supply_chain_tier: int = 0
    regulatory_gate_proximity: float = 0.0
    itar_exposure: float = 0.0
    ear_control_status: float = 0.0
    foreign_ownership_depth: float = 0.0
    cmmc_readiness: float = 0.0
    single_source_risk: float = 0.0
    geopolitical_sector_exposure: float = 0.0
    financial_stability: float = 0.2
    compliance_history: float = 0.0


@dataclass
class VendorInputV5:
    """Complete vendor input for the v5.0 scorer."""
    name: str
    country: str
    ownership: OwnershipProfile
    data_quality: DataQuality
    exec_profile: ExecProfile
    dod: DoDContext = field(default_factory=DoDContext)


# =============================================================================
# MODEL PARAMETERS
# =============================================================================

SENSITIVITY_TIERS = ("SAP", "SCI", "TOP_SECRET", "SECRET", "CUI", "UNCLASSIFIED", "COMMERCIAL")

# 14 factor names in canonical order
FACTOR_NAMES = (
    "sanctions", "geography", "ownership", "data_quality", "executive",
    "regulatory_gate_proximity", "itar_exposure", "ear_control_status",
    "foreign_ownership_depth", "cmmc_readiness", "single_source_risk",
    "geopolitical_sector_exposure", "financial_stability", "compliance_history",
)

# Baseline log-odds by sensitivity (higher = more scrutiny = higher baseline risk)
BASELINE_LOGODDS: dict[str, float] = {
    "SAP":          0.50,
    "SCI":          0.30,
    "TOP_SECRET":   0.10,
    "SECRET":      -0.41,
    "CUI":         -1.39,
    "UNCLASSIFIED":-2.94,
    "COMMERCIAL":  -2.94,
}

# Factor weights: [factor][sensitivity] -> weight
FACTOR_WEIGHTS: dict[str, dict[str, float]] = {
    "sanctions": {
        "SAP": 2.5, "SCI": 2.3, "TOP_SECRET": 2.0, "SECRET": 1.8,
        "CUI": 1.5, "UNCLASSIFIED": 1.0, "COMMERCIAL": 1.0,
    },
    "geography": {
        "SAP": 2.0, "SCI": 1.8, "TOP_SECRET": 1.5, "SECRET": 1.3,
        "CUI": 1.2, "UNCLASSIFIED": 1.0, "COMMERCIAL": 1.0,
    },
    "ownership": {
        "SAP": 3.0, "SCI": 2.8, "TOP_SECRET": 2.2, "SECRET": 1.8,
        "CUI": 1.2, "UNCLASSIFIED": 0.8, "COMMERCIAL": 0.8,
    },
    "data_quality": {
        "SAP": 1.0, "SCI": 1.0, "TOP_SECRET": 1.0, "SECRET": 0.8,
        "CUI": 1.2, "UNCLASSIFIED": 0.6, "COMMERCIAL": 0.6,
    },
    "executive": {
        "SAP": 1.5, "SCI": 1.3, "TOP_SECRET": 1.0, "SECRET": 0.8,
        "CUI": 0.6, "UNCLASSIFIED": 0.5, "COMMERCIAL": 0.5,
    },
    "regulatory_gate_proximity": {
        "SAP": 3.5, "SCI": 3.2, "TOP_SECRET": 2.5, "SECRET": 2.0,
        "CUI": 1.8, "UNCLASSIFIED": 0.5, "COMMERCIAL": 0.0,
    },
    "itar_exposure": {
        "SAP": 2.8, "SCI": 2.5, "TOP_SECRET": 2.0, "SECRET": 1.5,
        "CUI": 1.0, "UNCLASSIFIED": 0.5, "COMMERCIAL": 0.0,
    },
    "ear_control_status": {
        "SAP": 2.2, "SCI": 2.0, "TOP_SECRET": 1.8, "SECRET": 1.5,
        "CUI": 1.0, "UNCLASSIFIED": 0.8, "COMMERCIAL": 0.0,
    },
    "foreign_ownership_depth": {
        "SAP": 2.5, "SCI": 2.3, "TOP_SECRET": 1.8, "SECRET": 1.5,
        "CUI": 1.2, "UNCLASSIFIED": 0.8, "COMMERCIAL": 0.5,
    },
    "cmmc_readiness": {
        "SAP": 2.0, "SCI": 2.0, "TOP_SECRET": 1.8, "SECRET": 1.5,
        "CUI": 3.0, "UNCLASSIFIED": 0.0, "COMMERCIAL": 0.0,
    },
    "single_source_risk": {
        "SAP": 1.5, "SCI": 1.5, "TOP_SECRET": 1.3, "SECRET": 1.2,
        "CUI": 1.2, "UNCLASSIFIED": 1.0, "COMMERCIAL": 1.2,
    },
    "geopolitical_sector_exposure": {
        "SAP": 2.0, "SCI": 1.8, "TOP_SECRET": 1.5, "SECRET": 1.2,
        "CUI": 1.0, "UNCLASSIFIED": 0.8, "COMMERCIAL": 0.8,
    },
    "financial_stability": {
        "SAP": 1.0, "SCI": 1.0, "TOP_SECRET": 1.0, "SECRET": 1.0,
        "CUI": 1.0, "UNCLASSIFIED": 1.0, "COMMERCIAL": 1.0,
    },
    "compliance_history": {
        "SAP": 1.5, "SCI": 1.5, "TOP_SECRET": 1.3, "SECRET": 1.2,
        "CUI": 1.0, "UNCLASSIFIED": 0.8, "COMMERCIAL": 0.8,
    },
}

# Interaction terms: (factor_a, factor_b) -> {sensitivity: gamma}
INTERACTION_WEIGHTS: dict[tuple[str, str], dict[str, float]] = {
    ("sanctions", "foreign_ownership_depth"): {
        "SAP": 0.6, "SCI": 0.5, "TOP_SECRET": 0.4, "SECRET": 0.3,
        "CUI": 0.2, "UNCLASSIFIED": 0.2, "COMMERCIAL": 0.2,
    },
    ("regulatory_gate_proximity", "cmmc_readiness"): {
        "SAP": 0.5, "SCI": 0.4, "TOP_SECRET": 0.3, "SECRET": 0.2,
        "CUI": 0.8, "UNCLASSIFIED": 0.0, "COMMERCIAL": 0.0,
    },
    ("foreign_ownership_depth", "geopolitical_sector_exposure"): {
        "SAP": 0.3, "SCI": 0.3, "TOP_SECRET": 0.3, "SECRET": 0.3,
        "CUI": 0.3, "UNCLASSIFIED": 0.3, "COMMERCIAL": 0.3,
    },
    ("single_source_risk", "financial_stability"): {
        "SAP": 0.4, "SCI": 0.4, "TOP_SECRET": 0.4, "SECRET": 0.4,
        "CUI": 0.4, "UNCLASSIFIED": 0.4, "COMMERCIAL": 0.4,
    },
    ("itar_exposure", "compliance_history"): {
        "SAP": 0.5, "SCI": 0.5, "TOP_SECRET": 0.5, "SECRET": 0.5,
        "CUI": 0.5, "UNCLASSIFIED": 0.5, "COMMERCIAL": 0.5,
    },
}

# Effective sample size for Wilson CI by sensitivity
# SAP cohort smaller = wider CI (more uncertainty)
EFFECTIVE_N_BASE: dict[str, float] = {
    "SAP": 50.0, "SCI": 60.0, "TOP_SECRET": 80.0, "SECRET": 100.0,
    "CUI": 120.0, "UNCLASSIFIED": 150.0, "COMMERCIAL": 150.0,
}


# =============================================================================
# FACTOR COMPUTATION (raw -> normalized 0-1)
# =============================================================================

def _compute_ownership_risk(o: OwnershipProfile) -> float:
    """Opacity / structure risk: 0 = transparent, 1 = opaque / risky."""
    r = 0.0
    if o.state_owned: r += 0.30
    if not o.beneficial_owner_known: r += 0.25
    r += (1.0 - o.ownership_pct_resolved) * 0.20
    if o.shell_layers > 0: r += min(o.shell_layers * 0.10, 0.30)
    if o.pep_connection: r += 0.15
    if o.publicly_traded: r -= 0.15
    return max(0.0, min(1.0, r))


def _compute_data_quality_risk(d: DataQuality) -> float:
    """Missing KYC data risk: 0 = complete, 1 = severely deficient."""
    missing = 0.0
    if not d.has_lei: missing += 0.15
    if not d.has_cage: missing += 0.12
    if not d.has_duns: missing += 0.10
    if not d.has_tax_id: missing += 0.15
    if not d.has_audited_financials: missing += 0.18
    age = 0.15 if d.years_of_records < 3 else (0.08 if d.years_of_records < 5 else 0.0)
    return min(1.0, missing + age)


def _compute_exec_risk(e: ExecProfile) -> float:
    """Executive / PEP risk: 0 = clean, 1 = high adverse."""
    r = 0.0
    if e.known_execs == 0: r += 0.25
    r += min(e.adverse_media * 0.12, 0.35)
    r += min(e.pep_execs * 0.10, 0.25)
    r += min(e.litigation_history * 0.05, 0.15)
    return max(0.0, min(1.0, r))


def _compute_foreign_ownership_depth(o: OwnershipProfile) -> float:
    """Foreign ownership concentration: 0 = none, 1 = fully foreign-controlled."""
    pct = o.foreign_ownership_pct
    if pct == 0.0:
        return 0.0
    if o.foreign_ownership_is_allied:
        if pct < 0.10: return 0.20
        if pct < 0.25: return 0.40
        return 0.50
    else:
        if pct < 0.10: return 0.35
        if pct < 0.25: return 0.55
        if pct < 0.50: return 0.70
        return 0.90


# =============================================================================
# HARD STOP EVALUATION (categorical overrides)
# =============================================================================

def _evaluate_hard_stops(
    screening: ScreeningResult,
    ownership: OwnershipProfile,
    country: str,
    sensitivity: str,
) -> list[dict]:
    """
    Categorical overrides that bypass the probabilistic scorer.
    Includes v3.0 allied-nation false-positive mitigation.
    """
    stops = []
    cc = country.upper()

    # Rule 1: Sanctions match with allied-nation cross-country mitigation
    if screening.matched:
        sanctions_threshold = 0.82  # v3.0 recalibrated composite threshold
        matched_country = ""
        if screening.matched_entry:
            matched_country = (screening.matched_entry.country or "").upper()
        vendor_is_allied = cc in ALLIED_NATIONS
        same_country = matched_country and matched_country == cc

        # Allied vendor matching a DIFFERENT country's entry = raise threshold
        if vendor_is_allied and not same_country:
            sanctions_threshold = 0.90

        if screening.best_score > sanctions_threshold:
            stops.append({
                "trigger": f"{screening.matched_entry.list_type} Match: {screening.matched_name}",
                "explanation": (
                    f"Entity matches {screening.matched_entry.list_type} list under "
                    f"{screening.matched_entry.program} program -- "
                    f"{screening.best_score * 100:.0f}% composite match confidence."
                ),
                "confidence": round(screening.best_score, 4),
            })

    # Rule 2: Comprehensively sanctioned country + state-owned
    if cc in COMPREHENSIVELY_SANCTIONED and ownership.state_owned:
        if not stops:
            stops.append({
                "trigger": f"State-Owned Entity in Sanctioned Jurisdiction ({cc})",
                "explanation": (
                    f"State-owned enterprise in {cc}. Entities owned or controlled by "
                    "comprehensively sanctioned governments are prohibited under OFAC."
                ),
                "confidence": 0.97,
            })

    # Rule 3: Adversary state-owned in high-risk jurisdiction
    country_risk = geo_risk(cc)
    if ownership.state_owned and country_risk > 0.50:
        if not any(s.get("confidence", 0) >= 0.95 for s in stops):
            stops.append({
                "trigger": "Adversary State-Owned Enterprise",
                "explanation": (
                    f"State-owned entity in adversarial jurisdiction ({cc}, "
                    f"geo_risk={country_risk:.2f}). Per EO 13959 and NDAA Section 1260H, "
                    "SOEs from adversary nations are disqualified from DoD supply chains."
                ),
                "confidence": 0.92,
            })

    # Rule 4: SAP/SCI with any foreign ownership
    if sensitivity in ("SAP", "SCI") and ownership.foreign_ownership_pct > 0.0:
        stops.append({
            "trigger": f"Foreign Ownership Disqualifier for {sensitivity}",
            "explanation": (
                f"{sensitivity} programs require 100% US ownership and control. "
                f"Entity has {ownership.foreign_ownership_pct * 100:.0f}% foreign ownership."
            ),
            "confidence": 0.99,
        })

    # Rule 5: Deep shell layering
    if ownership.shell_layers >= 5:
        stops.append({
            "trigger": f"Excessive Corporate Layering ({ownership.shell_layers} shell layers)",
            "explanation": (
                f"Entity has {ownership.shell_layers} corporate shell layers with "
                f"only {round(ownership.ownership_pct_resolved * 100)}% ownership resolved. "
                "Incompatible with DoD beneficial ownership requirements."
            ),
            "confidence": 0.85,
        })

    return stops


# =============================================================================
# SOFT FLAGS (advisory, below hard stop threshold)
# =============================================================================

def _evaluate_soft_flags(
    screening: ScreeningResult,
    ownership: OwnershipProfile,
    exec_profile: ExecProfile,
    data_quality: DataQuality,
    dod: DoDContext,
    country: str,
) -> list[dict]:
    flags = []
    cc = country.upper()

    # Fuzzy sanctions match (below hard stop, above noise)
    if screening.matched and 0.60 < screening.best_score <= 0.82:
        flags.append({
            "trigger": "Fuzzy Sanctions Match",
            "explanation": (
                f"Composite match score {screening.best_score * 100:.0f}% "
                f"(raw JW {screening.best_raw_jw * 100:.0f}%) to "
                f"{screening.matched_entry.list_type} entry -- manual review recommended."
            ),
            "confidence": round(screening.best_score, 4),
        })

    # Allied-nation cross-country near-miss (above 0.82 but below allied threshold 0.90)
    if screening.matched and 0.82 < screening.best_score <= 0.90:
        matched_country = ""
        if screening.matched_entry:
            matched_country = (screening.matched_entry.country or "").upper()
        same_country = matched_country and matched_country == cc
        if cc in ALLIED_NATIONS and not same_country:
            flags.append({
                "trigger": "Cross-Jurisdiction Name Similarity",
                "explanation": (
                    f"Vendor in allied nation ({cc}) has {screening.best_score * 100:.0f}% "
                    f"similarity to {screening.matched_entry.list_type} entry "
                    f'"{screening.matched_name}" ({matched_country}). '
                    "Country mismatch indicates likely false positive."
                ),
                "confidence": round(screening.best_score * 0.5, 4),
            })

    if ownership.pep_connection:
        flags.append({
            "trigger": "PEP Connection",
            "explanation": "One or more principals match Politically Exposed Person databases.",
            "confidence": 0.65,
        })
    if ownership.ownership_pct_resolved < 0.60:
        flags.append({
            "trigger": "Unresolved Beneficial Ownership",
            "explanation": (
                f"Only {round(ownership.ownership_pct_resolved * 100)}% of beneficial "
                "ownership resolved. Enhanced due diligence required."
            ),
            "confidence": 0.80,
        })
    if exec_profile.adverse_media > 0:
        flags.append({
            "trigger": "Adverse Media",
            "explanation": (
                f"{exec_profile.adverse_media} adverse media hit(s) on executive screening."
            ),
            "confidence": 0.70,
        })
    if data_quality.years_of_records < 3:
        flags.append({
            "trigger": "Limited Operating History",
            "explanation": (
                f"Entity has only {data_quality.years_of_records} year(s) of verifiable records."
            ),
            "confidence": 0.85,
        })
    if dod.regulatory_gate_proximity >= 0.5:
        flags.append({
            "trigger": "Regulatory Gate Proximity Alert",
            "explanation": (
                f"Gate proximity score {dod.regulatory_gate_proximity:.2f} indicates "
                "one or more compliance gates approaching failure state."
            ),
            "confidence": 0.88,
        })
    if dod.cmmc_readiness >= 0.5 and dod.sensitivity in ("SAP", "SCI", "TOP_SECRET", "SECRET", "CUI"):
        flags.append({
            "trigger": "CMMC Certification Gap",
            "explanation": (
                f"CMMC readiness gap score {dod.cmmc_readiness:.2f}. Certification distance "
                "may not meet contract schedule."
            ),
            "confidence": 0.82,
        })
    if dod.single_source_risk >= 0.6:
        flags.append({
            "trigger": "Single-Source Supply Risk",
            "explanation": (
                "Entity is sole or single source for a critical component. "
                "Supply chain resilience significantly compromised."
            ),
            "confidence": 0.75,
        })
    # Sectoral sanctions soft flag
    if cc in {"CN", "BY", "VE", "MM", "SD", "SO", "AF", "YE"}:
        if ownership.state_owned:
            flags.append({
                "trigger": f"Sectoral Sanctions Exposure ({cc})",
                "explanation": (
                    f"State-owned entity in {cc} subject to US sectoral sanctions. "
                    "Enhanced due diligence required."
                ),
                "confidence": 0.75,
            })

    return flags


# =============================================================================
# FACTOR DESCRIPTIONS (human-readable per-factor narratives)
# =============================================================================

def _factor_description(
    factor: str,
    score: float,
    inp: VendorInputV5,
    screening: ScreeningResult,
) -> str:
    if factor == "sanctions":
        if screening.matched:
            return (
                f'Match: "{screening.matched_name}" ({screening.matched_entry.list_type}) -- '
                f'{screening.best_score * 100:.0f}% composite '
                f'({screening.best_raw_jw * 100:.0f}% raw JW)'
            )
        return "No matches across OFAC SDN, Entity List, UK, EU, UN lists."
    if factor == "geography":
        gv = geo_risk(inp.country)
        if gv < 0.10: return f"Allied jurisdiction ({inp.country}) -- minimal geographic risk."
        if gv < 0.25: return f"Moderate-risk jurisdiction ({inp.country})."
        if gv < 0.50: return f"Elevated-risk jurisdiction ({inp.country})."
        return f"High-risk / adversarial jurisdiction ({inp.country})."
    if factor == "ownership":
        if inp.ownership.state_owned: return "State-owned enterprise."
        if not inp.ownership.beneficial_owner_known:
            return f"Beneficial ownership unresolved ({round(inp.ownership.ownership_pct_resolved * 100)}% traced)."
        if inp.ownership.publicly_traded: return "Publicly traded -- transparent ownership structure."
        return f"Private entity, {round(inp.ownership.ownership_pct_resolved * 100)}% ownership resolved."
    if factor == "data_quality":
        gaps = [k for k, v in {
            "LEI": inp.data_quality.has_lei, "CAGE": inp.data_quality.has_cage,
            "DUNS": inp.data_quality.has_duns, "Tax ID": inp.data_quality.has_tax_id,
            "Audited Financials": inp.data_quality.has_audited_financials,
        }.items() if not v]
        return f"Missing identifiers: {', '.join(gaps)}." if gaps else "Complete identifier coverage."
    if factor == "executive":
        if inp.exec_profile.known_execs == 0: return "No executive data available."
        if inp.exec_profile.adverse_media > 0:
            return f"{inp.exec_profile.adverse_media} adverse media hit(s) on {inp.exec_profile.known_execs} executive(s)."
        return f"{inp.exec_profile.known_execs} executive(s) screened -- no adverse findings."
    if factor == "regulatory_gate_proximity":
        if score < 0.1: return "All regulatory gates PASS cleanly."
        if score < 0.5: return f"Gate proximity {score:.2f} -- one or more gates PENDING, remediation on track."
        return f"Gate proximity {score:.2f} -- multiple gates PENDING or approaching failure."
    if factor == "itar_exposure":
        if score == 0.0: return "Non-ITAR item."
        return f"ITAR exposure {score:.2f} -- item is ITAR-controlled, Tier {inp.dod.supply_chain_tier} accountability."
    if factor == "ear_control_status":
        if score == 0.0: return "Not EAR-controlled."
        return f"EAR control score {score:.2f} -- dual-use item with foreign content considerations."
    if factor == "foreign_ownership_depth":
        pct = inp.ownership.foreign_ownership_pct
        if pct == 0.0: return "No foreign ownership detected."
        allied = "allied" if inp.ownership.foreign_ownership_is_allied else "non-allied"
        return f"{pct * 100:.0f}% foreign ownership from {allied} country."
    if factor == "cmmc_readiness":
        if score == 0.0: return "CMMC not required for this context."
        return f"CMMC readiness gap {score:.2f} -- certification distance from program requirement."
    if factor == "single_source_risk":
        if score < 0.2: return "Multiple qualified alternative suppliers available."
        if score < 0.6: return f"Limited supplier pool (score {score:.2f})."
        return f"Single/sole-source critical component (score {score:.2f})."
    if factor == "geopolitical_sector_exposure":
        if score < 0.2: return "Non-sensitive sector, stable location."
        if score < 0.6: return f"Moderately sensitive sector (score {score:.2f})."
        return f"High geopolitical sector exposure (score {score:.2f})."
    if factor == "financial_stability":
        if score < 0.2: return "Strong financial position."
        if score < 0.5: return f"Acceptable financial health (score {score:.2f}) -- monitor for deterioration."
        return f"Elevated financial distress (score {score:.2f}) -- business continuity risk."
    if factor == "compliance_history":
        if score < 0.1: return "Clean compliance record."
        if score < 0.4: return f"Minor historical violations, resolved (score {score:.2f})."
        return f"Pattern of compliance violations (score {score:.2f})."
    return f"Score {score:.2f}."


# =============================================================================
# MIV RECOMMENDATIONS
# =============================================================================

def _miv_recommendation(factor: str, score: float) -> str:
    recs = {
        "sanctions":                     "Re-screen with enhanced entity resolution against all active lists.",
        "geography":                     "Obtain country-of-incorporation and operational footprint details.",
        "ownership":                     "Commission beneficial ownership registry search (FinCEN/Companies House).",
        "data_quality":                  "Obtain missing identifiers: LEI, CAGE, DUNS, Tax ID.",
        "executive":                     "Conduct enhanced PEP and adverse media screening on all executives.",
        "regulatory_gate_proximity":     "Request current status letter for each pending regulatory gate.",
        "itar_exposure":                 "Obtain ITAR compliance certification and manufacturing process audit.",
        "ear_control_status":            "Request export control documentation package and deemed export training records.",
        "foreign_ownership_depth":       "Obtain full cap table with nationality of all beneficial owners > 5%.",
        "cmmc_readiness":                "Request current CMMC assessment report and remediation plan with timeline.",
        "single_source_risk":            "Assess alternative qualified suppliers; require continuity-of-supply plan.",
        "geopolitical_sector_exposure":  "Request supply chain map identifying foreign-origin components.",
        "financial_stability":           "Obtain audited financials, credit report, and bank covenant status.",
        "compliance_history":            "Request full regulatory violation history and corrective action reports.",
    }
    return recs.get(factor, "Gather additional documentation for this factor.")


# =============================================================================
# OUTPUT DATACLASS
# =============================================================================

@dataclass
class ScoringResultV5:
    """Complete output from the v5.0 two-layer scoring engine."""
    # Core probabilistic
    calibrated_probability: float
    calibrated_tier: str                    # combined_tier from integrate_layers()
    combined_tier: str                      # explicit combined tier field
    interval_lower: float
    interval_upper: float

    # Factor analysis
    contributions: list
    hard_stop_decisions: list
    soft_flags: list
    findings: list
    marginal_information_values: list

    # Screening passthrough
    screening: ScreeningResult

    # DoD output
    is_dod_eligible: bool
    is_dod_qualified: bool
    program_recommendation: str
    sensitivity_context: str
    supply_chain_tier: int

    # Regulatory (Layer 1)
    regulatory_status: str = "NOT_EVALUATED"
    regulatory_findings: list = field(default_factory=list)

    # Metadata
    model_version: str = "5.0-FGAMLogit-DoD-Dual-Vertical"

    def to_dict(self) -> dict:
        return {
            "calibrated_probability": self.calibrated_probability,
            "calibrated_tier": self.calibrated_tier,
            "combined_tier": self.combined_tier,
            "interval_lower": self.interval_lower,
            "interval_upper": self.interval_upper,
            "contributions": self.contributions,
            "hard_stop_decisions": self.hard_stop_decisions,
            "soft_flags": self.soft_flags,
            "findings": self.findings,
            "marginal_information_values": self.marginal_information_values,
            "is_dod_eligible": self.is_dod_eligible,
            "is_dod_qualified": self.is_dod_qualified,
            "program_recommendation": self.program_recommendation,
            "sensitivity_context": self.sensitivity_context,
            "supply_chain_tier": self.supply_chain_tier,
            "regulatory_status": self.regulatory_status,
            "regulatory_findings": self.regulatory_findings,
            "model_version": self.model_version,
            "screening": {
                "matched": self.screening.matched,
                "best_score": self.screening.best_score,
                "best_raw_jw": self.screening.best_raw_jw,
                "matched_name": self.screening.matched_name,
                "db_label": self.screening.db_label,
                "screening_ms": self.screening.screening_ms,
                "match_details": self.screening.match_details,
            },
        }


# =============================================================================
# LAYER INTEGRATION
# =============================================================================

def integrate_layers(
    regulatory_status: str,
    risk_probability: float,
    sensitivity: str,
) -> str:
    """
    Map (regulatory_status x risk_probability x sensitivity) -> combined_tier.
    """
    if regulatory_status == "NON_COMPLIANT":
        return "TIER_1_DISQUALIFIED"

    if regulatory_status == "REQUIRES_REVIEW":
        if risk_probability < 0.30:
            return "TIER_2_CONDITIONAL_ACCEPTABLE"
        if risk_probability < 0.60:
            return "TIER_2_ELEVATED_REVIEW"
        return "TIER_1_CRITICAL_CONCERN"

    # COMPLIANT paths
    if sensitivity in ("SAP", "SCI"):
        if risk_probability < 0.20:
            return "TIER_4_SAP_QUALIFIED"
        if risk_probability < 0.35:
            return "TIER_3_SAP_ACCEPTABLE"
        return "TIER_2_ELEVATED_CONCERN"

    if sensitivity == "TOP_SECRET":
        if risk_probability < 0.25:
            return "TIER_4_APPROVED"
        if risk_probability < 0.40:
            return "TIER_3_CONDITIONAL"
        return "TIER_2_ELEVATED"

    if sensitivity in ("SECRET", "CUI"):
        if risk_probability < 0.30:
            return "TIER_4_APPROVED"
        if risk_probability < 0.50:
            return "TIER_3_CONDITIONAL"
        return "TIER_2_CAUTION"

    # UNCLASSIFIED / COMMERCIAL
    if risk_probability < 0.15:
        return "TIER_4_CLEAR"
    if risk_probability < 0.30:
        return "TIER_3_CONDITIONAL"
    if risk_probability < 0.50:
        return "TIER_2_CAUTION_COMMERCIAL"
    return "TIER_1_CRITICAL_CONCERN"


def _program_recommendation(
    regulatory_status: str,
    risk_probability: float,
    combined_tier: str,
) -> str:
    if regulatory_status == "NON_COMPLIANT" or combined_tier == "TIER_1_DISQUALIFIED":
        return "DO_NOT_PROCEED"
    if combined_tier == "TIER_1_CRITICAL_CONCERN":
        if regulatory_status == "REQUIRES_REVIEW":
            return "DO_NOT_PROCEED_WITHOUT_MITIGATION"
        return "DO_NOT_PROCEED"
    if regulatory_status == "REQUIRES_REVIEW":
        if risk_probability < 0.35:
            return "CONDITIONAL_APPROVAL_WITH_OVERSIGHT"
        return "DO_NOT_PROCEED_WITHOUT_MITIGATION"
    # COMPLIANT
    if risk_probability < 0.25:
        return "APPROVED"
    if risk_probability < 0.40:
        return "APPROVED_WITH_ENHANCED_MONITORING"
    return "APPROVED_WITH_RESTRICTIVE_CONTROLS"


# =============================================================================
# COUNTERFACTUAL MIV COMPUTATION
# =============================================================================

def _compute_mivs(
    factor_scores: dict[str, float],
    probability: float,
    sensitivity: str,
) -> list[dict]:
    """
    Counterfactual Marginal Information Value for each factor.
    MIV = current_probability - probability_if_factor_were_zero.
    Higher MIV = more value in obtaining information to resolve this factor.
    """
    mivs = []

    for fname, fx in factor_scores.items():
        w = FACTOR_WEIGHTS.get(fname, {}).get(sensitivity, 0.0)
        if w == 0.0 or fx < 0.01:
            continue

        # Counterfactual: compute eta without this factor
        eta_cf = BASELINE_LOGODDS.get(sensitivity, -2.94)
        for gname, gx in factor_scores.items():
            gw = FACTOR_WEIGHTS.get(gname, {}).get(sensitivity, 0.0)
            if gname == fname:
                continue  # exclude this factor
            eta_cf += gw * gx
        # Interactions without this factor
        for (fa, fb), iweights in INTERACTION_WEIGHTS.items():
            iw = iweights.get(sensitivity, 0.0)
            if iw == 0.0 or fa == fname or fb == fname:
                continue
            eta_cf += iw * factor_scores.get(fa, 0.0) * factor_scores.get(fb, 0.0)

        prob_cf = _logistic(eta_cf)
        shift = probability - prob_cf
        shift_pp = shift * 100.0

        if abs(shift_pp) >= 1.0:
            tier_prob = min(0.90, abs(shift_pp) / 50.0)
            mivs.append({
                "factor": fname,
                "current_score": round(fx, 4),
                "effective_weight": round(w, 4),
                "expected_shift_pp": round(shift_pp, 2),
                "tier_change_probability": round(tier_prob, 3),
                "recommendation": _miv_recommendation(fname, fx),
            })

    mivs.sort(key=lambda m: abs(m["expected_shift_pp"]), reverse=True)
    return mivs


# =============================================================================
# MAIN SCORER
# =============================================================================

def score_vendor(
    inp: VendorInputV5,
    regulatory_status: str = "NOT_EVALUATED",
    regulatory_findings: list = None,
) -> ScoringResultV5:
    """
    Score a vendor through the full FGAMLogit v5.0 pipeline.

    Args:
        inp:                 VendorInputV5 with all factor inputs
        regulatory_status:   From Layer 1 ("COMPLIANT" / "NON_COMPLIANT" / "REQUIRES_REVIEW")
                             "NOT_EVALUATED" skips layer integration
        regulatory_findings: List of regulatory finding dicts from Layer 1

    Returns:
        ScoringResultV5 with full two-layer output
    """
    if regulatory_findings is None:
        regulatory_findings = []

    sensitivity = inp.dod.sensitivity
    if sensitivity not in BASELINE_LOGODDS:
        sensitivity = "COMMERCIAL"

    # Step 1: Sanctions screening
    screening = screen_name(inp.name)

    # Step 2: Compute raw factor scores
    sanctions_score = screening.best_score if screening.matched else 0.0
    geography_score = geo_risk(inp.country)
    ownership_score = _compute_ownership_risk(inp.ownership)
    dq_score = _compute_data_quality_risk(inp.data_quality)
    exec_score = _compute_exec_risk(inp.exec_profile)

    # Foreign ownership depth: use provided or compute from ownership profile
    fod_score = inp.dod.foreign_ownership_depth
    if fod_score == 0.0 and inp.ownership.foreign_ownership_pct > 0.0:
        fod_score = _compute_foreign_ownership_depth(inp.ownership)

    factor_scores: dict[str, float] = {
        "sanctions":                     sanctions_score,
        "geography":                     geography_score,
        "ownership":                     ownership_score,
        "data_quality":                  dq_score,
        "executive":                     exec_score,
        "regulatory_gate_proximity":     inp.dod.regulatory_gate_proximity,
        "itar_exposure":                 inp.dod.itar_exposure,
        "ear_control_status":            inp.dod.ear_control_status,
        "foreign_ownership_depth":       fod_score,
        "cmmc_readiness":                inp.dod.cmmc_readiness,
        "single_source_risk":            inp.dod.single_source_risk,
        "geopolitical_sector_exposure":  inp.dod.geopolitical_sector_exposure,
        "financial_stability":           inp.dod.financial_stability,
        "compliance_history":            inp.dod.compliance_history,
    }

    # Step 3: FGAMLogit log-odds computation
    eta = BASELINE_LOGODDS[sensitivity]
    for fname, fx in factor_scores.items():
        w = FACTOR_WEIGHTS[fname].get(sensitivity, 0.0)
        eta += w * fx
    for (fa, fb), iweights in INTERACTION_WEIGHTS.items():
        iw = iweights.get(sensitivity, 0.0)
        if iw == 0.0:
            continue
        eta += iw * factor_scores.get(fa, 0.0) * factor_scores.get(fb, 0.0)

    probability = _logistic(eta)

    # Step 4: Hard stops
    stops = _evaluate_hard_stops(screening, inp.ownership, inp.country, sensitivity)
    if stops:
        probability = max(probability, 0.82)

    # Step 5: Layer integration -> combined tier
    if regulatory_status == "NOT_EVALUATED":
        if probability >= 0.82 or stops:
            combined_tier = "TIER_1_CRITICAL_CONCERN"
        elif probability >= 0.50:
            combined_tier = "TIER_2_ELEVATED_REVIEW"
        elif probability >= 0.30:
            combined_tier = "TIER_3_CONDITIONAL"
        else:
            combined_tier = "TIER_4_CLEAR"
    else:
        combined_tier = integrate_layers(regulatory_status, probability, sensitivity)
        if stops and "TIER_1" not in combined_tier:
            combined_tier = "TIER_1_CRITICAL_CONCERN"

    # Step 6: Confidence interval (Wilson score)
    n_base = EFFECTIVE_N_BASE.get(sensitivity, 100.0)
    if regulatory_status == "REQUIRES_REVIEW":
        n_eff = n_base * 0.70
    else:
        n_eff = n_base
    ci_lo, ci_hi = _wilson_ci(probability, n_eff)

    # Step 7: Per-factor signed contributions (counterfactual)
    contributions = []
    for fname, fx in factor_scores.items():
        w = FACTOR_WEIGHTS[fname].get(sensitivity, 0.0)
        if w == 0.0:
            continue

        eta_without = BASELINE_LOGODDS[sensitivity]
        for gname, gx in factor_scores.items():
            gw = FACTOR_WEIGHTS[gname].get(sensitivity, 0.0)
            if gname == fname:
                continue
            eta_without += gw * gx
        for (fa, fb), iweights in INTERACTION_WEIGHTS.items():
            iw = iweights.get(sensitivity, 0.0)
            if iw == 0.0 or fa == fname or fb == fname:
                continue
            eta_without += iw * factor_scores.get(fa, 0.0) * factor_scores.get(fb, 0.0)

        prob_without = _logistic(eta_without)
        signed_contribution = probability - prob_without

        contributions.append({
            "factor": fname,
            "raw_score": round(fx, 4),
            "weight": round(w, 4),
            "signed_contribution": round(signed_contribution, 4),
            "description": _factor_description(fname, fx, inp, screening),
        })

    contributions.sort(key=lambda c: abs(c["signed_contribution"]), reverse=True)

    # Step 8: Soft flags
    flags = _evaluate_soft_flags(
        screening, inp.ownership, inp.exec_profile, inp.data_quality, inp.dod, inp.country
    )

    # Step 9: Key findings
    findings = []
    if stops:
        findings.append(
            f"Hard stop triggered: {stops[0]['trigger']}. Absolute compliance barrier."
        )
        if len(stops) > 1:
            findings.append(f"{len(stops)} independent hard stop rules triggered.")
    if probability >= 0.60:
        findings.append(
            f"FGAMLogit probability of {probability * 100:.1f}% indicates substantial risk."
        )
    elif probability < 0.15:
        findings.append(
            f"Low-risk profile -- FGAMLogit probability {probability * 100:.1f}%."
        )
    if regulatory_status == "NON_COMPLIANT":
        findings.append(
            "Entity is NON_COMPLIANT with mandatory DoD regulatory gates. "
            "Disqualified regardless of probabilistic score."
        )
    elif regulatory_status == "REQUIRES_REVIEW":
        findings.append(
            "One or more regulatory gates PENDING. Compliance achievable "
            "but requires documented remediation."
        )
    if geography_score > 0.40:
        findings.append(
            f"Jurisdiction ({inp.country}) contributes significant geographic risk "
            f"(score {geography_score:.2f})."
        )
    if not inp.ownership.beneficial_owner_known:
        findings.append("Beneficial ownership unresolved -- enhanced due diligence required.")
    if inp.ownership.publicly_traded:
        findings.append("Publicly traded entity with regulatory disclosure requirements.")
    if inp.dod.single_source_risk >= 0.8:
        findings.append(
            "Sole-source critical component per DoD Instruction 5200.44."
        )
    if flags:
        findings.append(f"{len(flags)} advisory flag(s) requiring analyst review.")

    # Step 10: MIVs (counterfactual)
    mivs = _compute_mivs(factor_scores, probability, sensitivity)

    # Step 11: DoD eligibility
    is_dod_eligible = regulatory_status not in ("NON_COMPLIANT",) and not bool(stops)
    is_dod_qualified = (
        regulatory_status == "COMPLIANT"
        and probability < 0.40
        and not stops
    )
    if regulatory_status == "NOT_EVALUATED":
        is_dod_eligible = not bool(stops)
        is_dod_qualified = probability < 0.25 and not stops

    recommendation = _program_recommendation(regulatory_status, probability, combined_tier)

    return ScoringResultV5(
        calibrated_probability=round(probability, 4),
        calibrated_tier=combined_tier,
        combined_tier=combined_tier,
        interval_lower=ci_lo,
        interval_upper=ci_hi,
        contributions=contributions,
        hard_stop_decisions=stops,
        soft_flags=flags,
        findings=findings,
        marginal_information_values=mivs,
        screening=screening,
        is_dod_eligible=is_dod_eligible,
        is_dod_qualified=is_dod_qualified,
        program_recommendation=recommendation,
        sensitivity_context=sensitivity,
        supply_chain_tier=inp.dod.supply_chain_tier,
        regulatory_status=regulatory_status,
        regulatory_findings=regulatory_findings,
        model_version="5.0-FGAMLogit-DoD-Dual-Vertical",
    )


# =============================================================================
# BACKWARD COMPATIBILITY SHIM
# =============================================================================

@dataclass
class VendorInput:
    """Legacy input shape -- passes through to v5.0 scorer with COMMERCIAL defaults."""
    name: str
    country: str
    ownership: OwnershipProfile
    data_quality: DataQuality
    exec_profile: ExecProfile
    program: str = "standard_industrial"


_PROGRAM_TO_SENSITIVITY: dict[str, str] = {
    "weapons_system":      "TOP_SECRET",
    "mission_critical":    "SECRET",
    "nuclear_related":     "TOP_SECRET",
    "intelligence_community": "SCI",
    "critical_infrastructure": "SECRET",
    "dual_use":            "CUI",
    "standard_industrial": "COMMERCIAL",
    "commercial_off_shelf":"COMMERCIAL",
    "services":            "COMMERCIAL",
}


def score_vendor_legacy(inp: VendorInput) -> ScoringResultV5:
    """Backward-compatible wrapper for legacy VendorInput callers."""
    ownership_v5 = OwnershipProfile(
        publicly_traded=inp.ownership.publicly_traded,
        state_owned=inp.ownership.state_owned,
        beneficial_owner_known=inp.ownership.beneficial_owner_known,
        ownership_pct_resolved=inp.ownership.ownership_pct_resolved,
        shell_layers=inp.ownership.shell_layers,
        pep_connection=inp.ownership.pep_connection,
        foreign_ownership_pct=0.0,
        foreign_ownership_is_allied=True,
    )
    sensitivity = _PROGRAM_TO_SENSITIVITY.get(inp.program, "COMMERCIAL")
    inp_v5 = VendorInputV5(
        name=inp.name, country=inp.country,
        ownership=ownership_v5, data_quality=inp.data_quality,
        exec_profile=inp.exec_profile,
        dod=DoDContext(sensitivity=sensitivity),
    )
    return score_vendor(inp_v5, regulatory_status="NOT_EVALUATED")
