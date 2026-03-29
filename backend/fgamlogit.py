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
from ofac import screen_name, ScreeningResult
from decision_engine import classify_alert, AlertDisposition
from compliance_profiles import apply_weight_overrides, get_profile, normalize_profile_id


# =============================================================================
# TIER DISPLAY LABELS: normalized output labels for external consumers
# =============================================================================

TIER_DISPLAY_LABELS = {
    "TIER_1_DISQUALIFIED": "BLOCKED",
    "TIER_1_CRITICAL_CONCERN": "BLOCKED",
    "TIER_2_ELEVATED": "REVIEW",
    "TIER_2_ELEVATED_REVIEW": "REVIEW",
    "TIER_2_CONDITIONAL_ACCEPTABLE": "REVIEW",
    "TIER_2_HIGH_CONCERN": "REVIEW",
    "TIER_2_CAUTION": "REVIEW",
    "TIER_2_CAUTION_COMMERCIAL": "REVIEW",
    "TIER_3_CONDITIONAL": "WATCH",
    "TIER_3_CRITICAL_ACCEPTABLE": "WATCH",
    "TIER_4_STANDARD": "QUALIFIED",
    "TIER_4_APPROVED": "QUALIFIED",
    "TIER_4_CRITICAL_QUALIFIED": "QUALIFIED",
    "TIER_4_CLEAR": "QUALIFIED",
    "TIER_5_PREFERRED": "APPROVED",
}


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

SANCTIONS_HARD_STOP_THRESHOLD_DEFAULT = 0.82
SANCTIONS_HARD_STOP_THRESHOLD_ALLIED_CROSS_COUNTRY = 0.90
SANCTIONS_SOFT_FLAG_FLOOR = 0.60

STANDALONE_TIER_THRESHOLDS = {
    "critical_concern": 0.82,
    "elevated_review": 0.50,
    "conditional": 0.30,
}

# ISO 3166 alpha-3 to alpha-2 for common defense countries
_ALPHA3_TO_ALPHA2 = {
    "USA": "US", "GBR": "GB", "CAN": "CA", "AUS": "AU", "NZL": "NZ",
    "DEU": "DE", "FRA": "FR", "NLD": "NL", "NOR": "NO", "DNK": "DK",
    "SWE": "SE", "FIN": "FI", "ITA": "IT", "ESP": "ES", "POL": "PL",
    "CZE": "CZ", "JPN": "JP", "KOR": "KR", "ISR": "IL", "SGP": "SG",
    "TWN": "TW", "IND": "IN", "BRA": "BR", "MEX": "MX", "TUR": "TR",
    "CHN": "CN", "RUS": "RU", "IRN": "IR", "PRK": "KP", "SYR": "SY",
    "CUB": "CU", "VEN": "VE", "BLR": "BY", "PAK": "PK", "SAU": "SA",
    "ARE": "AE", "EGY": "EG", "NGA": "NG", "ZAF": "ZA",
}


def _normalize_country(cc: str) -> str:
    """Normalize country code to 2-letter ISO 3166 alpha-2."""
    cc = cc.strip().upper()
    if len(cc) == 3:
        return _ALPHA3_TO_ALPHA2.get(cc, cc)
    return cc


def geo_risk(cc: str) -> float:
    return GEO_RISK.get(_normalize_country(cc), 0.15)


# =============================================================================
# INPUT DATACLASSES
# =============================================================================

@dataclass
class OwnershipProfile:
    publicly_traded: bool = False
    state_owned: bool = False
    beneficial_owner_known: bool = False
    named_beneficial_owner_known: bool = False
    controlling_parent_known: bool = False
    owner_class_known: bool = False
    owner_class: str = ""
    ownership_pct_resolved: float = 0.0
    control_resolution_pct: float = 0.0
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
    compliance_profile: str = "defense_acquisition"


# =============================================================================
# MODEL PARAMETERS
# =============================================================================

SENSITIVITY_TIERS = ("CRITICAL_SAP", "CRITICAL_SCI", "ELEVATED", "ENHANCED", "CONTROLLED", "STANDARD", "COMMERCIAL")

# 14 factor names in canonical order
FACTOR_NAMES = (
    "sanctions", "geography", "ownership", "data_quality", "executive",
    "regulatory_gate_proximity", "itar_exposure", "ear_control_status",
    "foreign_ownership_depth", "cmmc_readiness", "single_source_risk",
    "geopolitical_sector_exposure", "financial_stability", "compliance_history",
)

# Baseline log-odds: UNIFORM across all sensitivity tiers.
# A perfect vendor (all factors = 0) scores ~5% regardless of sensitivity.
# Sensitivity differentiation comes entirely from FACTOR WEIGHTS, not baseline.
# Like a medical test: a more sensitive test catches more problems but doesn't
# give healthy patients a higher probability of being sick.
BASELINE_LOGODDS: dict[str, float] = {
    "CRITICAL_SAP": -2.94,
    "CRITICAL_SCI": -2.94,
    "ELEVATED":     -2.94,
    "ENHANCED":     -2.94,
    "CONTROLLED":   -2.94,
    "STANDARD":     -2.94,
    "COMMERCIAL":   -2.94,
}

# Factor weights: [factor][sensitivity] -> weight
FACTOR_WEIGHTS: dict[str, dict[str, float]] = {
    "sanctions": {
        "CRITICAL_SAP": 2.5, "CRITICAL_SCI": 2.3, "ELEVATED": 2.0, "ENHANCED": 1.8,
        "CONTROLLED": 1.5, "STANDARD": 1.0, "COMMERCIAL": 1.0,
    },
    "geography": {
        "CRITICAL_SAP": 2.0, "CRITICAL_SCI": 1.8, "ELEVATED": 1.5, "ENHANCED": 1.3,
        "CONTROLLED": 1.2, "STANDARD": 1.0, "COMMERCIAL": 1.0,
    },
    "ownership": {
        "CRITICAL_SAP": 3.0, "CRITICAL_SCI": 2.8, "ELEVATED": 2.2, "ENHANCED": 1.8,
        "CONTROLLED": 1.2, "STANDARD": 0.8, "COMMERCIAL": 0.8,
    },
    "data_quality": {
        "CRITICAL_SAP": 2.0, "CRITICAL_SCI": 1.8, "ELEVATED": 1.5, "ENHANCED": 1.2,
        "CONTROLLED": 1.2, "STANDARD": 0.8, "COMMERCIAL": 0.6,
    },
    "executive": {
        "CRITICAL_SAP": 2.8, "CRITICAL_SCI": 2.5, "ELEVATED": 2.0, "ENHANCED": 1.5,
        "CONTROLLED": 1.0, "STANDARD": 0.8, "COMMERCIAL": 0.6,
    },
    "regulatory_gate_proximity": {
        "CRITICAL_SAP": 3.5, "CRITICAL_SCI": 3.2, "ELEVATED": 2.5, "ENHANCED": 2.0,
        "CONTROLLED": 1.8, "STANDARD": 0.5, "COMMERCIAL": 0.0,
    },
    "itar_exposure": {
        "CRITICAL_SAP": 2.8, "CRITICAL_SCI": 2.5, "ELEVATED": 2.0, "ENHANCED": 1.5,
        "CONTROLLED": 1.0, "STANDARD": 0.5, "COMMERCIAL": 0.0,
    },
    "ear_control_status": {
        "CRITICAL_SAP": 2.2, "CRITICAL_SCI": 2.0, "ELEVATED": 1.8, "ENHANCED": 1.5,
        "CONTROLLED": 1.0, "STANDARD": 0.8, "COMMERCIAL": 0.0,
    },
    "foreign_ownership_depth": {
        "CRITICAL_SAP": 2.5, "CRITICAL_SCI": 2.3, "ELEVATED": 1.8, "ENHANCED": 1.5,
        "CONTROLLED": 1.2, "STANDARD": 0.8, "COMMERCIAL": 0.5,
    },
    "cmmc_readiness": {
        "CRITICAL_SAP": 2.0, "CRITICAL_SCI": 2.0, "ELEVATED": 1.8, "ENHANCED": 1.5,
        "CONTROLLED": 3.0, "STANDARD": 0.0, "COMMERCIAL": 0.0,
    },
    "single_source_risk": {
        "CRITICAL_SAP": 1.5, "CRITICAL_SCI": 1.5, "ELEVATED": 1.3, "ENHANCED": 1.2,
        "CONTROLLED": 1.2, "STANDARD": 1.0, "COMMERCIAL": 1.2,
    },
    "geopolitical_sector_exposure": {
        "CRITICAL_SAP": 2.0, "CRITICAL_SCI": 1.8, "ELEVATED": 1.5, "ENHANCED": 1.2,
        "CONTROLLED": 1.0, "STANDARD": 0.8, "COMMERCIAL": 0.8,
    },
    "financial_stability": {
        "CRITICAL_SAP": 1.0, "CRITICAL_SCI": 1.0, "ELEVATED": 1.0, "ENHANCED": 1.0,
        "CONTROLLED": 1.0, "STANDARD": 1.0, "COMMERCIAL": 1.0,
    },
    "compliance_history": {
        "CRITICAL_SAP": 1.5, "CRITICAL_SCI": 1.5, "ELEVATED": 1.3, "ENHANCED": 1.2,
        "CONTROLLED": 1.0, "STANDARD": 0.8, "COMMERCIAL": 0.8,
    },
}

# Interaction terms: (factor_a, factor_b) -> {sensitivity: gamma}
INTERACTION_WEIGHTS: dict[tuple[str, str], dict[str, float]] = {
    ("sanctions", "foreign_ownership_depth"): {
        "CRITICAL_SAP": 0.6, "CRITICAL_SCI": 0.5, "ELEVATED": 0.4, "ENHANCED": 0.3,
        "CONTROLLED": 0.2, "STANDARD": 0.2, "COMMERCIAL": 0.2,
    },
    ("regulatory_gate_proximity", "cmmc_readiness"): {
        "CRITICAL_SAP": 0.5, "CRITICAL_SCI": 0.4, "ELEVATED": 0.3, "ENHANCED": 0.2,
        "CONTROLLED": 0.8, "STANDARD": 0.0, "COMMERCIAL": 0.0,
    },
    ("foreign_ownership_depth", "geopolitical_sector_exposure"): {
        "CRITICAL_SAP": 0.3, "CRITICAL_SCI": 0.3, "ELEVATED": 0.3, "ENHANCED": 0.3,
        "CONTROLLED": 0.3, "STANDARD": 0.3, "COMMERCIAL": 0.3,
    },
    ("single_source_risk", "financial_stability"): {
        "CRITICAL_SAP": 0.4, "CRITICAL_SCI": 0.4, "ELEVATED": 0.4, "ENHANCED": 0.4,
        "CONTROLLED": 0.4, "STANDARD": 0.4, "COMMERCIAL": 0.4,
    },
    ("itar_exposure", "compliance_history"): {
        "CRITICAL_SAP": 0.5, "CRITICAL_SCI": 0.5, "ELEVATED": 0.5, "ENHANCED": 0.5,
        "CONTROLLED": 0.5, "STANDARD": 0.5, "COMMERCIAL": 0.5,
    },
    ("itar_exposure", "foreign_ownership_depth"): {
        "CRITICAL_SAP": 0.8, "CRITICAL_SCI": 0.7, "ELEVATED": 0.6, "ENHANCED": 0.5,
        "CONTROLLED": 0.4, "STANDARD": 0.3, "COMMERCIAL": 0.2,
    },
    ("foreign_ownership_depth", "compliance_history"): {
        "CRITICAL_SAP": 0.5, "CRITICAL_SCI": 0.5, "ELEVATED": 0.4, "ENHANCED": 0.3,
        "CONTROLLED": 0.3, "STANDARD": 0.2, "COMMERCIAL": 0.2,
    },
}

# Effective sample size for Wilson CI by sensitivity
# SAP cohort smaller = wider CI (more uncertainty)
EFFECTIVE_N_BASE: dict[str, float] = {
    "CRITICAL_SAP": 50.0, "CRITICAL_SCI": 60.0, "ELEVATED": 80.0, "ENHANCED": 100.0,
    "CONTROLLED": 120.0, "STANDARD": 150.0, "COMMERCIAL": 150.0,
}

# Supply chain tier weight multiplier
# Tier 0 primes are already heavily vetted -> lower weights on uncertainty factors
# Tier 3 component/materials suppliers are less known -> higher weights
TIER_WEIGHT_MULTIPLIER: dict[int, float] = {
    0: 0.70,   # Prime contractor (cleared facilities, extensive track record)
    1: 1.00,   # Major subsystem (baseline)
    2: 1.30,   # Component supplier (moderate uncertainty)
    3: 1.60,   # Materials/foreign supplier (high uncertainty)
}

# DoD factor priors for UNKNOWN values (when factor = 0.0 and no data was provided)
# These add a SMALL uncertainty penalty ("not yet assessed"), NOT actual risk.
# Real data from supply chain context or OSINT replaces these immediately.
# Total prior contribution for T1 at ELEVATED: ~0.4 log-odds (shifts p by ~5-8pp)
DOD_FACTOR_PRIORS: dict[str, dict[int, float]] = {
    "itar_exposure": {0: 0.03, 1: 0.06, 2: 0.09, 3: 0.12},
    "ear_control_status": {0: 0.02, 1: 0.04, 2: 0.06, 3: 0.09},
    "cmmc_readiness": {0: 0.02, 1: 0.04, 2: 0.06, 3: 0.09},
    "single_source_risk": {0: 0.03, 1: 0.05, 2: 0.08, 3: 0.10},
    "geopolitical_sector_exposure": {0: 0.02, 1: 0.03, 2: 0.04, 3: 0.06},
    "compliance_history": {0: 0.01, 1: 0.02, 2: 0.04, 3: 0.06},
}

# Only commercial uncertainty factors get the tier multiplier
# DoD factors already have tier-specific priors (no double-counting)
TIER_MULTIPLIED_FACTORS = {
    "data_quality", "executive", "ownership",
}


# =============================================================================
# FACTOR COMPUTATION (raw -> normalized 0-1)
# =============================================================================

def _compute_ownership_risk(o: OwnershipProfile) -> float:
    """Opacity / structure risk: 0 = transparent, 1 = opaque / risky."""
    r = 0.0
    if o.state_owned:
        r += 0.30
    if not o.beneficial_owner_known:
        r += 0.25
    r += (1.0 - o.ownership_pct_resolved) * 0.20
    if o.shell_layers > 0:
        r += min(o.shell_layers * 0.10, 0.30)
    if o.pep_connection:
        r += 0.15
    if o.publicly_traded:
        r -= 0.15
    return max(0.0, min(1.0, r))


def _compute_data_quality_risk(d: DataQuality) -> float:
    """Missing KYC data risk: 0 = complete, 1 = severely deficient."""
    missing = 0.0
    if not d.has_lei:
        missing += 0.15
    if not d.has_cage:
        missing += 0.12
    if not d.has_duns:
        missing += 0.10
    if not d.has_tax_id:
        missing += 0.15
    if not d.has_audited_financials:
        missing += 0.18
    age = 0.15 if d.years_of_records < 3 else (0.08 if d.years_of_records < 5 else 0.0)
    return min(1.0, missing + age)


def _compute_exec_risk(e: ExecProfile) -> float:
    """Executive / PEP risk: 0 = clean, 1 = high adverse.
    Uses logarithmic scaling so 100 findings >> 3 findings instead of saturating."""
    r = 0.0
    if e.known_execs == 0:
        r += 0.25

    # Logarithmic scaling: log2(count+1) provides diminishing but continuous growth
    # 1 finding -> 0.12, 3 -> 0.24, 10 -> 0.42, 30 -> 0.59, 100 -> 0.80
    if e.adverse_media > 0:
        r += min(0.12 * math.log2(e.adverse_media + 1), 0.80)

    if e.pep_execs > 0:
        r += min(0.15 * math.log2(e.pep_execs + 1), 0.40)

    if e.litigation_history > 0:
        r += min(0.08 * math.log2(e.litigation_history + 1), 0.35)

    return max(0.0, min(1.0, r))


def _compute_foreign_ownership_depth(o: OwnershipProfile) -> float:
    """Foreign ownership concentration: 0 = none, 1 = fully foreign-controlled."""
    pct = o.foreign_ownership_pct
    if pct == 0.0:
        return 0.0
    if o.foreign_ownership_is_allied:
        if pct < 0.10:
            return 0.20
        if pct < 0.25:
            return 0.40
        return 0.50
    if pct < 0.10:
        return 0.35
    if pct < 0.25:
        return 0.55
    if pct < 0.50:
        return 0.70
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
    cc = _normalize_country(country)

    # Rule 1: Sanctions match with allied-nation cross-country mitigation
    if screening.matched:
        sanctions_threshold = SANCTIONS_HARD_STOP_THRESHOLD_DEFAULT
        matched_country = ""
        if screening.matched_entry:
            matched_country = (screening.matched_entry.country or "").upper()
        vendor_is_allied = cc in ALLIED_NATIONS
        same_country = matched_country and matched_country == cc

        # Allied vendor matching a DIFFERENT country's entry = raise threshold
        if vendor_is_allied and not same_country:
            sanctions_threshold = SANCTIONS_HARD_STOP_THRESHOLD_ALLIED_CROSS_COUNTRY

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
    if sensitivity in ("CRITICAL_SAP", "CRITICAL_SCI") and ownership.foreign_ownership_pct > 0.0:
        stops.append({
            "trigger": f"Foreign Ownership Disqualifier for {sensitivity}",
            "explanation": (
                f"{sensitivity} programs require 100% US ownership and control. "
                f"Entity has {ownership.foreign_ownership_pct * 100:.0f}% foreign ownership."
            ),
            "confidence": 0.99,
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
    if screening.matched and SANCTIONS_SOFT_FLAG_FLOOR < screening.best_score <= SANCTIONS_HARD_STOP_THRESHOLD_DEFAULT:
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
    if screening.matched and SANCTIONS_HARD_STOP_THRESHOLD_DEFAULT < screening.best_score <= SANCTIONS_HARD_STOP_THRESHOLD_ALLIED_CROSS_COUNTRY:
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
    if ownership.shell_layers >= 5:
        flags.append({
            "trigger": "Deep Corporate Layering",
            "explanation": (
                f"Entity has {ownership.shell_layers} corporate shell layers with "
                f"only {round(ownership.ownership_pct_resolved * 100)}% ownership resolved. "
                "Treat as elevated opacity risk requiring analyst review, not automatic disqualification."
            ),
            "confidence": 0.85,
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
    if dod.cmmc_readiness >= 0.5 and dod.sensitivity in ("CRITICAL_SAP", "CRITICAL_SCI", "ELEVATED", "ENHANCED", "CONTROLLED"):
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
        cc = _normalize_country(inp.country)
        gv = geo_risk(cc)
        if gv < 0.10:
            return f"Allied jurisdiction ({cc}) -- minimal geographic risk."
        if gv < 0.25:
            return f"Moderate-risk jurisdiction ({cc})."
        if gv < 0.50:
            return f"Elevated-risk jurisdiction ({cc})."
        return f"High-risk / adversarial jurisdiction ({cc})."
    if factor == "ownership":
        if inp.ownership.state_owned:
            return "State-owned enterprise."
        if inp.ownership.owner_class_known and not inp.ownership.beneficial_owner_known:
            return (
                f"Named beneficial owner unresolved. "
                f"Owner class self-disclosed as {inp.ownership.owner_class or 'unknown'} "
                f"({round(inp.ownership.ownership_pct_resolved * 100)}% traced)."
            )
        if not inp.ownership.beneficial_owner_known:
            return f"Beneficial ownership unresolved ({round(inp.ownership.ownership_pct_resolved * 100)}% traced)."
        if inp.ownership.publicly_traded:
            return "Publicly traded -- transparent ownership structure."
        return f"Private entity, {round(inp.ownership.ownership_pct_resolved * 100)}% ownership resolved."
    if factor == "data_quality":
        gaps = [k for k, v in {
            "LEI": inp.data_quality.has_lei, "CAGE": inp.data_quality.has_cage,
            "DUNS": inp.data_quality.has_duns, "Tax ID": inp.data_quality.has_tax_id,
            "Audited Financials": inp.data_quality.has_audited_financials,
        }.items() if not v]
        return f"Missing identifiers: {', '.join(gaps)}." if gaps else "Complete identifier coverage."
    if factor == "executive":
        if inp.exec_profile.known_execs == 0:
            return "No executive data available."
        if inp.exec_profile.adverse_media > 0:
            return f"{inp.exec_profile.adverse_media} adverse media hit(s) on {inp.exec_profile.known_execs} executive(s)."
        return f"{inp.exec_profile.known_execs} executive(s) screened -- no adverse findings."
    if factor == "regulatory_gate_proximity":
        if score < 0.1:
            return "All regulatory gates PASS cleanly."
        if score < 0.5:
            return f"Gate proximity {score:.2f} -- one or more gates PENDING, remediation on track."
        return f"Gate proximity {score:.2f} -- multiple gates PENDING or approaching failure."
    if factor == "itar_exposure":
        if score == 0.0:
            return "Non-ITAR item."
        return f"ITAR exposure {score:.2f} -- item is ITAR-controlled, Tier {inp.dod.supply_chain_tier} accountability."
    if factor == "ear_control_status":
        if score == 0.0:
            return "Not EAR-controlled."
        return f"EAR control score {score:.2f} -- dual-use item with foreign content considerations."
    if factor == "foreign_ownership_depth":
        pct = inp.ownership.foreign_ownership_pct
        if pct == 0.0:
            return "No foreign ownership detected."
        allied = "allied" if inp.ownership.foreign_ownership_is_allied else "non-allied"
        return f"{pct * 100:.0f}% foreign ownership from {allied} country."
    if factor == "cmmc_readiness":
        if score == 0.0:
            return "CMMC not required for this context."
        return f"CMMC readiness gap {score:.2f} -- certification distance from program requirement."
    if factor == "single_source_risk":
        if score < 0.2:
            return "Multiple qualified alternative suppliers available."
        if score < 0.6:
            return f"Limited supplier pool (score {score:.2f})."
        return f"Single/sole-source critical component (score {score:.2f})."
    if factor == "geopolitical_sector_exposure":
        if score < 0.2:
            return "Non-sensitive sector, stable location."
        if score < 0.6:
            return f"Moderately sensitive sector (score {score:.2f})."
        return f"High geopolitical sector exposure (score {score:.2f})."
    if factor == "financial_stability":
        if score < 0.2:
            return "Strong financial position."
        if score < 0.5:
            return f"Acceptable financial health (score {score:.2f}) -- monitor for deterioration."
        return f"Elevated financial distress (score {score:.2f}) -- business continuity risk."
    if factor == "compliance_history":
        if score < 0.1:
            return "Clean compliance record."
        if score < 0.4:
            return f"Minor historical violations, resolved (score {score:.2f})."
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
    calibrated_tier: str                    # canonical TIER_* contract used across API/db/tests
    combined_tier: str                      # explicit combined tier field
    display_tier: str                       # operator-facing label derived from calibrated_tier
    interval_lower: float
    interval_upper: float
    interval_coverage: float               # CI width as proportion of [0,1] range

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

    # Decision Engine (v5.1)
    alert_disposition: AlertDisposition = None

    # Compliance Profile (v5.2)
    compliance_profile: str = "defense_acquisition"

    # Metadata
    model_version: str = "5.2-FGAMLogit-DoD-ProfileAware"
    policy_metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "calibrated_probability": self.calibrated_probability,
            "calibrated_tier": self.calibrated_tier,
            "combined_tier": self.combined_tier,
            "display_tier": self.display_tier,
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
            "compliance_profile": self.compliance_profile,
            "model_version": self.model_version,
            "policy": self.policy_metadata,
            "screening": {
                "matched": self.screening.matched,
                "best_score": self.screening.best_score,
                "best_raw_jw": self.screening.best_raw_jw,
                "matched_name": self.screening.matched_name,
                "db_label": self.screening.db_label,
                "screening_ms": self.screening.screening_ms,
                "match_details": self.screening.match_details,
                "policy_basis": self.screening.policy_basis,
            },
            "alert_disposition": {
                "category": self.alert_disposition.category,
                "confidence_band": self.alert_disposition.confidence_band,
                "recommended_action": self.alert_disposition.recommended_action,
                "override_risk_weight": self.alert_disposition.override_risk_weight,
                "explanation": self.alert_disposition.explanation,
                "classification_factors": self.alert_disposition.classification_factors,
            } if self.alert_disposition else None,
        }


# =============================================================================
# HELPER FUNCTIONS FOR TIER NORMALIZATION
# =============================================================================

def _normalize_tier_label(internal_tier: str) -> str:
    """
    Map internal tier names to normalized external display labels.
    Consumers should use these labels instead of internal TIER_N names.
    """
    return TIER_DISPLAY_LABELS.get(internal_tier, internal_tier)


def _build_scoring_policy_metadata(
    *,
    sensitivity: str,
    profile_id: str,
    profile_baseline_shift: float,
    tier_mult: float,
    regulatory_status: str,
    screening: ScreeningResult,
    source_reliability_avg: float,
    source_reliability_multiplier: float,
    id_boost: int,
    n_base: float,
    n_eff: float,
) -> dict:
    metadata = {
        "mode": "layered" if regulatory_status != "NOT_EVALUATED" else "standalone",
        "sensitivity": sensitivity,
        "profile": profile_id,
        "baseline_logodds": BASELINE_LOGODDS[sensitivity],
        "profile_baseline_shift": round(profile_baseline_shift, 4),
        "tier_weight_multiplier": round(tier_mult, 4),
        "screening": screening.policy_basis,
        "sanctions_policy": {
            "hard_stop_threshold_default": SANCTIONS_HARD_STOP_THRESHOLD_DEFAULT,
            "hard_stop_threshold_allied_cross_country": SANCTIONS_HARD_STOP_THRESHOLD_ALLIED_CROSS_COUNTRY,
            "soft_flag_floor": SANCTIONS_SOFT_FLAG_FLOOR,
        },
        "uncertainty": {
            "effective_n_base": round(n_base, 4),
            "source_reliability_avg": round(source_reliability_avg, 4),
            "source_reliability_multiplier": round(source_reliability_multiplier, 4),
            "identifier_boost": id_boost,
            "effective_n_final": round(n_eff, 4),
        },
    }
    if regulatory_status == "NOT_EVALUATED":
        metadata["standalone_thresholds"] = STANDALONE_TIER_THRESHOLDS
    return metadata


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
    if sensitivity in ("CRITICAL_SAP", "CRITICAL_SCI"):
        if risk_probability < 0.20:
            return "TIER_4_CRITICAL_QUALIFIED"
        if risk_probability < 0.35:
            return "TIER_3_CRITICAL_ACCEPTABLE"
        if risk_probability >= 0.85:
            return "TIER_1_CRITICAL_CONCERN"
        return "TIER_2_HIGH_CONCERN"

    if sensitivity == "ELEVATED":
        # Unclassified defense work should surface moderate uncertainty earlier
        # without collapsing low-risk allies into review by default.
        if risk_probability < 0.16:
            return "TIER_4_APPROVED"
        if risk_probability < 0.40:
            return "TIER_3_CONDITIONAL"
        return "TIER_2_ELEVATED"

    if sensitivity == "ENHANCED":
        if risk_probability < 0.30:
            return "TIER_4_APPROVED"
        if risk_probability < 0.50:
            return "TIER_3_CONDITIONAL"
        return "TIER_2_CAUTION"

    if sensitivity == "CONTROLLED":
        # Dual-use and export-controlled work should not auto-clear
        # moderate opacity or documentation gaps.
        if risk_probability < 0.20:
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

        if abs(shift_pp) >= 0.5:
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
    extra_hard_stops: list = None,
    source_reliability_avg: float = 0.0,
) -> ScoringResultV5:
    """
    Score a vendor through the full FGAMLogit v5.0 pipeline.

    Args:
        inp:                    VendorInputV5 with all factor inputs
        regulatory_status:      From Layer 1 ("COMPLIANT" / "NON_COMPLIANT" / "REQUIRES_REVIEW")
                                "NOT_EVALUATED" skips layer integration
        regulatory_findings:    List of regulatory finding dicts from Layer 1
        extra_hard_stops:       Pre-determined hard stops from OSINT (SAM exclusions, UN sanctions, etc.)
                                These are treated as categorical prohibitions (p=1.0).
        source_reliability_avg: Average reliability of OSINT sources that contributed data (0.0-1.0).
                                Used to modulate CI width. 0.0 = no OSINT data (use base CI).
                                0.95 = mostly authoritative sources (narrower CI).
                                0.45 = mostly media sources (wider CI).

    Returns:
        ScoringResultV5 with full two-layer output
    """
    if regulatory_findings is None:
        regulatory_findings = []
    if extra_hard_stops is None:
        extra_hard_stops = []

    profile_id = normalize_profile_id(inp.compliance_profile)

    sensitivity = inp.dod.sensitivity
    if sensitivity not in BASELINE_LOGODDS:
        import logging
        logging.getLogger("xiphos").warning(
            f"Unknown sensitivity tier '{inp.dod.sensitivity}', falling back to COMMERCIAL"
        )
        sensitivity = "COMMERCIAL"

    # Step 1: Sanctions screening with decision engine classification
    screening = screen_name(inp.name, vendor_country=inp.country)
    disposition = classify_alert(screening, vendor_country=inp.country)

    # Step 2: Compute raw factor scores
    # v5.1: Use decision engine override_risk_weight instead of raw composite.
    # This prevents barely-above-threshold matches (0.76) from inflating risk
    # scores the same way perfect matches (1.0) do.
    sanctions_score = disposition.override_risk_weight
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

    # Step 2b: Apply DoD factor priors for unknown values
    # LIMITATION (L5): Cannot distinguish missing data (unknown factor) from explicit zero (zero risk).
    # Both cases produce factor_scores[key] == 0.0. When a DoD factor is 0.0, we assume it was
    # never set and apply the tier-based prior. If a vendor truly has zero risk in a category,
    # the caller should pass 0.001 (near-zero) instead of 0.0 to avoid prior injection.
    supply_tier = inp.dod.supply_chain_tier
    for dod_factor, tier_priors in DOD_FACTOR_PRIORS.items():
        if factor_scores.get(dod_factor, 0.0) == 0.0:
            prior = tier_priors.get(supply_tier, tier_priors.get(1, 0.15))
            factor_scores[dod_factor] = prior

    # Step 2c: Build profile-aware factor weights
    # Start with canonical weights for this sensitivity tier, then apply profile overrides
    base_weights = {fname: FACTOR_WEIGHTS[fname].get(sensitivity, 0.0) for fname in FACTOR_NAMES}
    profile_config = get_profile(profile_id)
    adjusted_weights = apply_weight_overrides(base_weights, profile_id)

    # Step 3: FGAMLogit log-odds computation with tier weight multiplier
    tier_mult = TIER_WEIGHT_MULTIPLIER.get(supply_tier, 1.0)
    eta = BASELINE_LOGODDS[sensitivity] + profile_config.baseline_shift
    for fname, fx in factor_scores.items():
        w = adjusted_weights.get(fname, 0.0)
        # Apply tier multiplier to uncertainty-sensitive factors
        if fname in TIER_MULTIPLIED_FACTORS:
            w *= tier_mult
        eta += w * fx
    for (fa, fb), iweights in INTERACTION_WEIGHTS.items():
        iw = iweights.get(sensitivity, 0.0)
        if iw == 0.0:
            continue
        eta += iw * factor_scores.get(fa, 0.0) * factor_scores.get(fb, 0.0)

    probability = _logistic(eta)

    # Step 4: Hard stops (internal rules + OSINT-discovered prohibitions)
    stops = _evaluate_hard_stops(screening, inp.ownership, inp.country, sensitivity)
    stops.extend(extra_hard_stops)  # Merge OSINT hard stops (SAM exclusions, UN sanctions, etc.)
    if stops:
        # Hard stops are categorical PROHIBITED state, not just a probability floor
        probability = 1.0

    # Step 5: Layer integration -> combined tier
    # NOTE (L4): NOT_EVALUATED branch is a fallback when Layer 1 (regulatory gates) is skipped.
    # In normal two-layer operation, regulatory_status is always "COMPLIANT", "NON_COMPLIANT",
    # or "REQUIRES_REVIEW" from Layer 1. This branch provides a probabilistic-only fallback
    # for standalone scoring or if Layer 1 is disabled.
    if regulatory_status == "NOT_EVALUATED":
        if stops:
            # Hard stop: categorical disqualification
            combined_tier = "TIER_1_DISQUALIFIED"
        elif probability >= STANDALONE_TIER_THRESHOLDS["critical_concern"]:
            combined_tier = "TIER_1_CRITICAL_CONCERN"
        elif probability >= STANDALONE_TIER_THRESHOLDS["elevated_review"]:
            combined_tier = "TIER_2_ELEVATED_REVIEW"
        elif probability >= STANDALONE_TIER_THRESHOLDS["conditional"]:
            combined_tier = "TIER_3_CONDITIONAL"
        else:
            combined_tier = "TIER_4_CLEAR"
    else:
        combined_tier = integrate_layers(regulatory_status, probability, sensitivity)
        if stops:
            # Hard stop overrides any regulatory status
            combined_tier = "TIER_1_DISQUALIFIED"

    # Step 6: Confidence interval (Wilson score)
    # n_effective modulated by: sensitivity tier, regulatory status, and source reliability.
    # Higher source reliability = more data confidence = higher n_eff = narrower CI.
    n_base = EFFECTIVE_N_BASE.get(sensitivity, 100.0)
    if regulatory_status == "REQUIRES_REVIEW":
        n_eff = n_base * 0.70
    else:
        n_eff = n_base
    # Source reliability modulation: scale n_eff by 0.6x (low reliability) to 1.3x (high reliability)
    reliability_multiplier = 1.0
    if source_reliability_avg > 0.0:
        # Map reliability 0.45->0.6x, 0.70->1.0x, 0.95->1.3x
        # Slope: (1.3 - 0.6) / (0.95 - 0.45) = 0.7 / 0.5 = 1.4, but we need 0.70->1.0
        # Actually: (1.0 - 0.6) / (0.70 - 0.45) = 0.4 / 0.25 = 1.6
        reliability_multiplier = 0.6 + (source_reliability_avg - 0.45) * 1.6
        reliability_multiplier = max(0.5, min(1.4, reliability_multiplier))
        n_eff *= reliability_multiplier

    # Data quality boost: well-identified vendors with multiple verified identifiers
    # get a higher n_eff because we have more independent evidence to base the score on.
    id_boost = 0
    if inp.data_quality.has_lei:
        id_boost += 20
    if inp.data_quality.has_cage:
        id_boost += 20
    if inp.data_quality.has_duns:
        id_boost += 15
    if inp.data_quality.has_tax_id:
        id_boost += 10
    if inp.data_quality.has_audited_financials:
        id_boost += 15
    if inp.ownership.publicly_traded:
        id_boost += 30
    n_eff += id_boost

    ci_lo, ci_hi = _wilson_ci(probability, n_eff)

    # Step 7: Per-factor signed contributions
    # When hard stops fire (p=1.0), counterfactual contributions are meaningless.
    # Instead, show the hard stop as the dominant contribution.
    contributions = []
    if stops:
        # Hard stop is categorical. Show the prohibition trigger as the sole contribution.
        # Probabilistic factors are irrelevant when a hard stop fires.
        stop_triggers = "; ".join(s.get("trigger", "") for s in stops[:3])
        contributions.append({
            "factor": "PROHIBITION",
            "raw_score": 1.0,
            "weight": 0.0,
            "signed_contribution": 1.0,
            "description": f"CATEGORICAL PROHIBITION: {stop_triggers}. "
                           f"This entity is blocked regardless of probabilistic risk factors.",
        })
    else:
        # Normal counterfactual contributions
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

    display_tier = _normalize_tier_label(combined_tier)
    policy_metadata = _build_scoring_policy_metadata(
        sensitivity=sensitivity,
        profile_id=profile_id,
        profile_baseline_shift=profile_config.baseline_shift,
        tier_mult=tier_mult,
        regulatory_status=regulatory_status,
        screening=screening,
        source_reliability_avg=source_reliability_avg,
        source_reliability_multiplier=reliability_multiplier,
        id_boost=id_boost,
        n_base=n_base,
        n_eff=n_eff,
    )

    return ScoringResultV5(
        calibrated_probability=round(probability, 4),
        calibrated_tier=combined_tier,
        combined_tier=combined_tier,
        display_tier=display_tier,
        interval_lower=ci_lo,
        interval_upper=ci_hi,
        interval_coverage=round(ci_hi - ci_lo, 4),  # Width of CI: smaller = more confident
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
        alert_disposition=disposition,
        compliance_profile=profile_id,
        model_version="5.2-FGAMLogit-DoD-ProfileAware",
        policy_metadata=policy_metadata,
    )


# =============================================================================
# PROGRAM-TO-SENSITIVITY MAP (single source of truth)
# =============================================================================

PROGRAM_TO_SENSITIVITY: dict[str, str] = {
    # v5.3 simplified program types (5 distinct sensitivity tiers, zero redundancy)
    "dod_classified":         "CRITICAL_SCI",   # DoD/IC classified, SAP/SCI
    "dod_unclassified":       "ELEVATED",       # Unclassified DoD, ITAR, weapons programs
    "federal_non_dod":        "ENHANCED",       # DHS, DOE, NASA, civilian agencies
    "regulated_commercial":   "CONTROLLED",     # Defense-adjacent, dual-use, export-controlled
    "commercial":             "COMMERCIAL",     # Standard commercial, no security requirements

    # Legacy keys (backward compatibility with existing cases in database)
    "weapons_system":         "ELEVATED",
    "mission_critical":       "ENHANCED",
    "nuclear_related":        "ELEVATED",
    "intelligence_community": "CRITICAL_SCI",
    "critical_infrastructure":"ENHANCED",
    "dual_use":               "CONTROLLED",
    "standard_industrial":    "COMMERCIAL",
    "commercial_off_shelf":   "COMMERCIAL",
    "services":               "COMMERCIAL",
}
