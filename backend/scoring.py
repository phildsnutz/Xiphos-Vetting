"""
Xiphos Bayesian Scoring Engine v2.8

Beta-distributed priors with conjugate updates, composite hard stop
rules, and integrated sanctions screening.

v2.8 changes:
  - Composite hard stop rules: country + ownership + program combinations
  - Sanctions screening wired into scoring pipeline (not just OFAC name match)
  - Comprehensive sanctioned country list triggers automatic hard stop
  - Shell company depth > 4 triggers hard stop for weapons/mission-critical
"""

import math
from dataclasses import dataclass, field
from ofac import screen_name, ScreeningResult

# ---- Geography risk ----

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

# Countries under comprehensive US sanctions (EO-based embargo).
# Any entity domiciled here is an automatic hard stop for weapons/mission-critical.
COMPREHENSIVELY_SANCTIONED = {"RU", "IR", "KP", "SY", "CU"}

# Countries with sectoral sanctions or elevated proliferation risk.
# State-owned + weapons program in these countries triggers hard stop.
SECTORAL_SANCTIONED = {"CN", "BY", "VE", "MM", "SD", "SO", "AF", "YE"}

def geo_risk(cc: str) -> float:
    return GEO_RISK.get(cc.upper(), 0.30)


# ---- Ownership ----

@dataclass
class OwnershipProfile:
    publicly_traded: bool = False
    state_owned: bool = False
    beneficial_owner_known: bool = False
    ownership_pct_resolved: float = 0.0
    shell_layers: int = 0
    pep_connection: bool = False

def ownership_risk(o: OwnershipProfile) -> float:
    r = 0.0
    if o.state_owned: r += 0.30
    if not o.beneficial_owner_known: r += 0.25
    r += (1 - o.ownership_pct_resolved) * 0.20
    if o.shell_layers > 0: r += min(o.shell_layers * 0.10, 0.30)
    if o.pep_connection: r += 0.15
    if o.publicly_traded: r -= 0.15
    return max(0.0, min(1.0, r))


# ---- Data quality ----

@dataclass
class DataQuality:
    has_lei: bool = False
    has_cage: bool = False
    has_duns: bool = False
    has_tax_id: bool = False
    has_audited_financials: bool = False
    years_of_records: int = 0

def data_quality_risk(d: DataQuality) -> float:
    missing = 0.0
    if not d.has_lei: missing += 0.15
    if not d.has_cage: missing += 0.12
    if not d.has_duns: missing += 0.10
    if not d.has_tax_id: missing += 0.15
    if not d.has_audited_financials: missing += 0.18
    age_penalty = 0.15 if d.years_of_records < 3 else (0.08 if d.years_of_records < 5 else 0.0)
    return min(1.0, missing + age_penalty)


# ---- Executive risk ----

@dataclass
class ExecProfile:
    known_execs: int = 0
    adverse_media: int = 0
    pep_execs: int = 0
    litigation_history: int = 0

def exec_risk(e: ExecProfile) -> float:
    r = 0.0
    if e.known_execs == 0: r += 0.25
    r += min(e.adverse_media * 0.12, 0.35)
    r += min(e.pep_execs * 0.10, 0.25)
    r += min(e.litigation_history * 0.05, 0.15)
    return max(0.0, min(1.0, r))


# ---- Program criticality ----

PROGRAM_MULTIPLIER = {
    "weapons_system": 1.5,
    "mission_critical": 1.35,
    "nuclear_related": 1.6,
    "intelligence_community": 1.5,
    "critical_infrastructure": 1.3,
    "dual_use": 1.20,
    "standard_industrial": 1.0,
    "commercial_off_shelf": 0.85,
    "services": 0.90,
}

HIGH_SENSITIVITY_PROGRAMS = {
    "weapons_system", "mission_critical", "nuclear_related",
    "intelligence_community", "critical_infrastructure",
}

def program_multiplier(p: str) -> float:
    return PROGRAM_MULTIPLIER.get(p, 1.0)


# ---- Beta distribution utilities ----

def ln_gamma(z: float) -> float:
    """Lanczos approximation of ln(Gamma(z))."""
    g = 7
    c = [
        0.99999999999980993, 676.5203681218851, -1259.1392167224028,
        771.32342877765313, -176.61502916214059, 12.507343278686905,
        -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7,
    ]
    if z < 0.5:
        return math.log(math.pi / math.sin(math.pi * z)) - ln_gamma(1 - z)
    z -= 1
    x = c[0]
    for i in range(1, g + 2):
        x += c[i] / (z + i)
    t = z + g + 0.5
    return 0.5 * math.log(2 * math.pi) + (z + 0.5) * math.log(t) - t + math.log(x)


def normal_cdf(x: float) -> float:
    t = 1 / (1 + 0.2316419 * abs(x))
    d = 0.3989422804014327
    p = d * math.exp(-x * x / 2) * t * \
        (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.8212560 + t * 1.3302744))))
    return 1 - p if x > 0 else p


def normal_quantile(p: float) -> float:
    """Inverse normal CDF (Beasley-Springer-Moro)."""
    if p <= 0: return float("-inf")
    if p >= 1: return float("inf")
    if p == 0.5: return 0.0

    a = [-3.969683028665376e1, 2.209460984245205e2,
         -2.759285104469687e2, 1.383577518672690e2,
         -3.066479806614716e1, 2.506628277459239e0]
    b = [-5.447609879822406e1, 1.615858368580409e2,
         -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1]
    c = [-7.784894002430293e-3, -3.223964580411365e-1,
         -2.400758277161838, -2.549732539343734,
         4.374664141464968, 2.938163982698783]
    d = [7.784695709041462e-3, 3.224671290700398e-1,
         2.445134137142996, 3.754408661907416]

    p_low = 0.02425
    p_high = 1 - p_low

    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5]) * q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def beta_quantile(p: float, a: float, b: float) -> float:
    """Beta quantile via normal approximation (good for a+b > 5)."""
    mu = a / (a + b)
    sigma = math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))
    z = normal_quantile(p)
    return max(0.0, min(1.0, mu + sigma * z))


# ---- Vendor input ----

@dataclass
class VendorInput:
    name: str
    country: str
    ownership: OwnershipProfile
    data_quality: DataQuality
    exec_profile: ExecProfile
    program: str = "standard_industrial"


# ---- Scoring result ----

@dataclass
class ScoringResult:
    calibrated_probability: float
    calibrated_tier: str
    interval_lower: float
    interval_upper: float
    interval_coverage: float
    mean_confidence: float
    contributions: list[dict]
    hard_stop_decisions: list[dict]
    soft_flags: list[dict]
    findings: list[str]
    marginal_information_values: list[dict]
    screening: ScreeningResult
    composite_score: int
    rubric_confidence: float


# =============================================================================
# COMPOSITE HARD STOP RULES (v2.8)
#
# These rules catch cases the Bayesian model underscores because the model
# treats each factor semi-independently. These are categorical prohibitions
# based on regulatory reality, not probability.
# =============================================================================

def _evaluate_composite_hard_stops(
    inp: VendorInput,
    screening: ScreeningResult,
    geo_raw: float,
) -> list[dict]:
    """
    Evaluate deterministic hard stop rules that fire based on factor
    combinations. Returns a list of hard stop decisions.
    """
    stops = []
    cc = inp.country.upper()
    is_sensitive = inp.program in HIGH_SENSITIVITY_PROGRAMS

    # Rule 1: Confirmed sanctions match (>88% fuzzy match)
    if screening.matched and screening.best_score > 0.88:
        stops.append({
            "trigger": f"{screening.matched_entry.list_type} Match: {screening.matched_name}",
            "explanation": (
                f"Entity matches {screening.matched_entry.list_type} list under "
                f"{screening.matched_entry.program} program -- "
                f"{screening.best_score*100:.0f}% fuzzy match confidence."
            ),
            "confidence": round(screening.best_score, 4),
            "rule": "sanctions_match",
        })

    # Rule 2: Comprehensively sanctioned country (RU, IR, KP, SY, CU)
    # Any entity domiciled in these countries is prohibited for sensitive programs.
    if cc in COMPREHENSIVELY_SANCTIONED and is_sensitive:
        stops.append({
            "trigger": f"Comprehensively Sanctioned Jurisdiction ({cc})",
            "explanation": (
                f"Entity domiciled in {cc}, which is under comprehensive US sanctions "
                f"(Executive Order embargo). Prohibited for {inp.program} programs "
                f"regardless of entity-level screening results."
            ),
            "confidence": 0.98,
            "rule": "sanctioned_country_sensitive",
        })

    # Rule 3: Comprehensively sanctioned country + state-owned (any program)
    if cc in COMPREHENSIVELY_SANCTIONED and inp.ownership.state_owned:
        # Avoid duplicate if rule 2 already fired
        if not any(s["rule"] == "sanctioned_country_sensitive" for s in stops):
            stops.append({
                "trigger": f"State-Owned Entity in Sanctioned Jurisdiction ({cc})",
                "explanation": (
                    f"State-owned enterprise in {cc}. Entities owned or controlled by "
                    f"comprehensively sanctioned governments are prohibited under OFAC regulations."
                ),
                "confidence": 0.97,
                "rule": "sanctioned_state_owned",
            })

    # Rule 4: Adversary state-owned enterprise in sensitive program
    if inp.ownership.state_owned and geo_raw > 0.50 and is_sensitive:
        if not any(s["rule"] in ("sanctioned_country_sensitive", "sanctioned_state_owned") for s in stops):
            stops.append({
                "trigger": f"Adversary State-Owned Enterprise ({cc})",
                "explanation": (
                    f"State-owned entity in high-risk jurisdiction ({cc}, geo_risk={geo_raw:.2f}) "
                    f"applied to {inp.program} program. CFIUS and ITAR restrictions likely apply."
                ),
                "confidence": 0.90,
                "rule": "adversary_state_owned",
            })

    # Rule 5: Sectoral-sanctioned country + state-owned + weapons/nuclear program
    if cc in SECTORAL_SANCTIONED and inp.ownership.state_owned:
        if inp.program in ("weapons_system", "nuclear_related"):
            if not any(s["rule"].startswith("sanctioned") or s["rule"] == "adversary_state_owned" for s in stops):
                stops.append({
                    "trigger": f"Sectoral Sanctions Risk ({cc} + State-Owned + {inp.program})",
                    "explanation": (
                        f"State-owned entity in {cc} (sectoral sanctions) applied to "
                        f"{inp.program} program. US sectoral sanctions and entity-specific "
                        f"designations likely prohibit this procurement."
                    ),
                    "confidence": 0.88,
                    "rule": "sectoral_state_weapons",
                })

    # Rule 6: Deep shell layering in sensitive program
    if inp.ownership.shell_layers >= 5 and is_sensitive:
        stops.append({
            "trigger": f"Excessive Corporate Layering ({inp.ownership.shell_layers} shell layers)",
            "explanation": (
                f"Entity has {inp.ownership.shell_layers} corporate shell layers with "
                f"only {round(inp.ownership.ownership_pct_resolved*100)}% ownership resolved. "
                f"This level of opacity is incompatible with {inp.program} program requirements."
            ),
            "confidence": 0.85,
            "rule": "shell_depth",
        })

    # Rule 7: Zero transparency + high-risk country
    if (not inp.ownership.beneficial_owner_known
        and inp.ownership.ownership_pct_resolved < 0.15
        and geo_raw > 0.60
        and not inp.ownership.publicly_traded):
        stops.append({
            "trigger": f"Opaque Entity in High-Risk Jurisdiction ({cc})",
            "explanation": (
                f"Entity in {cc} (geo_risk={geo_raw:.2f}) with no beneficial ownership data "
                f"and only {round(inp.ownership.ownership_pct_resolved*100)}% ownership resolved. "
                f"Cannot satisfy DFARS 252.204-7018 beneficial ownership requirements."
            ),
            "confidence": 0.87,
            "rule": "opaque_high_risk",
        })

    return stops


def score_vendor(inp: VendorInput, profile_id: str = "defense_acquisition") -> ScoringResult:
    """
    Score a vendor through the full Bayesian pipeline with composite
    hard stop rules and integrated sanctions screening.

    Args:
        inp: VendorInput with vendor details
        profile_id: Compliance profile to use (default: defense_acquisition for backward compatibility)

    Returns:
        ScoringResult with calibrated probabilities, tier, and detailed findings
    """
    # Import profiles module
    from profiles import get_profile, validate_profile_id

    # Validate profile
    if not validate_profile_id(profile_id):
        profile_id = "defense_acquisition"
    profile = get_profile(profile_id)

    # Step 1: Sanctions screening (integrated into pipeline)
    screening = screen_name(inp.name)

    # Step 2: Per-factor raw scores
    sanctions_raw = screening.best_score if screening.matched else 0.0
    geo_raw = geo_risk(inp.country)
    own_raw = ownership_risk(inp.ownership)
    dq_raw = data_quality_risk(inp.data_quality)
    ex_raw = exec_risk(inp.exec_profile)
    prog_mult = program_multiplier(inp.program)

    # Step 3: Get factor weights from profile, build factors list
    factor_weights = {f["name"]: f["weight"] for f in profile.risk_factors}

    # Build factors list dynamically based on profile
    factors = [
        {"name": "Sanctions",    "raw": sanctions_raw, "weight": factor_weights.get("Sanctions", 5.0)},
        {"name": "Geography",    "raw": geo_raw,       "weight": factor_weights.get("Geography", 2.5)},
        {"name": "Ownership",    "raw": own_raw,       "weight": factor_weights.get("Ownership", 3.0)},
        {"name": "Data Quality", "raw": dq_raw,        "weight": factor_weights.get("Data Quality", 1.5)},
        {"name": "Executive",    "raw": ex_raw,        "weight": factor_weights.get("Executive", 2.0)},
    ]

    # Step 3b: Bayesian update -- Beta(2, 8) prior
    alpha = 2.0
    beta = 8.0

    for f in factors:
        n = f["weight"] * prog_mult
        alpha += f["raw"] * n
        beta += (1 - f["raw"]) * n

    posterior_mean = alpha / (alpha + beta)
    lo = beta_quantile(0.025, alpha, beta)
    hi = beta_quantile(0.975, alpha, beta)

    # Step 4: Composite hard stop rules (v2.8)
    stops = _evaluate_composite_hard_stops(inp, screening, geo_raw)

    # Step 5: Tier assignment with profile-aware thresholds
    tier_thresholds = profile.tier_thresholds
    hard_stop_threshold = tier_thresholds.get("hard_stop", 0.60)
    elevated_threshold = tier_thresholds.get("elevated", 0.30)
    monitor_threshold = tier_thresholds.get("monitor", 0.15)

    # Hard stops override the Bayesian tier
    if stops:
        tier = "hard_stop"
        # If Bayesian model underscored, boost composite to reflect hard stop
        if posterior_mean < hard_stop_threshold:
            # Don't change the Bayesian math, but ensure the composite score
            # reflects the hard stop status
            pass
    elif posterior_mean >= hard_stop_threshold:
        tier = "hard_stop"
    elif posterior_mean >= elevated_threshold:
        tier = "elevated"
    elif posterior_mean >= monitor_threshold:
        tier = "monitor"
    else:
        tier = "clear"

    # Step 6: Contributions
    contributions = []
    confidences = []

    for f in factors:
        # Counterfactual: posterior without this factor
        a_wo, b_wo = 2.0, 8.0
        for g in factors:
            if g["name"] == f["name"]:
                continue
            n = g["weight"] * prog_mult
            a_wo += g["raw"] * n
            b_wo += (1 - g["raw"]) * n
        mean_without = a_wo / (a_wo + b_wo)
        shift = posterior_mean - mean_without

        conf = min(0.99, 0.5 + f["weight"] * 0.08 + (0.15 if f["raw"] > 0.01 else 0.0))
        confidences.append(conf)

        # Description
        desc = ""
        if f["name"] == "Sanctions":
            if screening.matched:
                desc = f'Match: "{screening.matched_name}" ({screening.matched_entry.list_type}) -- {screening.best_score*100:.0f}% similarity'
            else:
                desc = "No sanctions matches found across OFAC SDN, Entity List, CAATSA, SSI"
        elif f["name"] == "Geography":
            if geo_raw < 0.10: desc = f"Allied jurisdiction ({inp.country})"
            elif geo_raw < 0.25: desc = f"Moderate-risk jurisdiction ({inp.country})"
            elif geo_raw < 0.50: desc = f"Elevated-risk jurisdiction ({inp.country})"
            else: desc = f"High-risk / sanctioned jurisdiction ({inp.country})"
        elif f["name"] == "Ownership":
            if inp.ownership.state_owned: desc = "State-owned enterprise"
            elif not inp.ownership.beneficial_owner_known:
                desc = f"Beneficial ownership unresolved ({round(inp.ownership.ownership_pct_resolved*100)}% traced)"
            elif inp.ownership.publicly_traded: desc = "Publicly traded, transparent ownership"
            else: desc = f"Private entity, {round(inp.ownership.ownership_pct_resolved*100)}% ownership resolved"
        elif f["name"] == "Data Quality":
            gaps = []
            if not inp.data_quality.has_lei: gaps.append("LEI")
            if not inp.data_quality.has_cage: gaps.append("CAGE")
            if not inp.data_quality.has_duns: gaps.append("DUNS")
            if not inp.data_quality.has_tax_id: gaps.append("Tax ID")
            desc = f"Missing: {', '.join(gaps)}" if gaps else "Complete identifier coverage"
        elif f["name"] == "Executive":
            if inp.exec_profile.known_execs == 0: desc = "No executive data available"
            elif inp.exec_profile.adverse_media > 0:
                desc = f"{inp.exec_profile.adverse_media} adverse media hit(s) on {inp.exec_profile.known_execs} known exec(s)"
            else:
                desc = f"{inp.exec_profile.known_execs} executives screened, no adverse findings"

        contributions.append({
            "factor": f["name"],
            "raw_score": round(f["raw"], 4),
            "confidence": round(conf, 4),
            "signed_contribution": round(shift, 4),
            "description": desc,
        })

    # Step 7: Soft flags
    flags = []
    if inp.ownership.pep_connection:
        flags.append({"trigger": "PEP Connection", "explanation": "One or more principals match Politically Exposed Person databases.", "confidence": 0.65})
    if inp.ownership.ownership_pct_resolved < 0.60:
        flags.append({"trigger": "Unresolved Ownership", "explanation": f"Only {round(inp.ownership.ownership_pct_resolved*100)}% of beneficial ownership resolved.", "confidence": 0.80})
    if screening.matched and 0.70 < screening.best_score <= 0.88:
        flags.append({"trigger": "Fuzzy Sanctions Match", "explanation": f"Name similarity {screening.best_score*100:.0f}% to {screening.matched_entry.list_type} entry -- manual review recommended.", "confidence": round(screening.best_score, 4)})
    if inp.exec_profile.adverse_media > 0:
        flags.append({"trigger": "Adverse Media", "explanation": f"{inp.exec_profile.adverse_media} adverse media hit(s) detected on executive screening.", "confidence": 0.70})
    if inp.data_quality.years_of_records < 3:
        flags.append({"trigger": "Limited Operating History", "explanation": f"Entity has only {inp.data_quality.years_of_records} year(s) of verifiable records.", "confidence": 0.85})
    # Sectoral sanctions soft flag (state-owned in sectoral country, non-weapons)
    cc = inp.country.upper()
    if cc in SECTORAL_SANCTIONED and inp.ownership.state_owned and inp.program not in ("weapons_system", "nuclear_related"):
        if not stops:  # Only flag if no hard stop already
            flags.append({"trigger": f"Sectoral Sanctions Exposure ({cc})", "explanation": f"State-owned entity in {cc} which is subject to US sectoral sanctions. Enhanced due diligence required.", "confidence": 0.75})

    # Step 8: Key findings
    finds = []
    if stops:
        finds.append(f"HARD STOP: {stops[0]['trigger']}. This is an absolute compliance barrier.")
        if len(stops) > 1:
            finds.append(f"{len(stops)} independent hard stop rules triggered.")
    if posterior_mean > 0.50:
        finds.append(f"Bayesian posterior of {posterior_mean*100:.0f}% indicates substantial compliance risk.")
    elif posterior_mean < 0.15:
        finds.append(f"Low-risk profile with {posterior_mean*100:.0f}% posterior probability.")
    if geo_raw > 0.40:
        finds.append(f"Jurisdiction ({inp.country}) contributes significant geographic risk.")
    if not inp.ownership.beneficial_owner_known:
        finds.append("Beneficial ownership is unresolved -- enhanced due diligence recommended.")
    if inp.ownership.publicly_traded:
        finds.append("Publicly traded entity with regulatory disclosure requirements.")
    if flags:
        finds.append(f"{len(flags)} advisory flag(s) requiring analyst review.")

    # Step 9: MIV
    miv = []
    if not inp.ownership.beneficial_owner_known:
        impact = 8.5 if inp.ownership.ownership_pct_resolved < 0.50 else 4.2
        miv.append({"recommendation": "Obtain beneficial ownership registry filing", "expected_info_gain_pp": impact, "tier_change_probability": 0.35 if impact > 5 else 0.15})
    if not inp.data_quality.has_cage:
        miv.append({"recommendation": "Verify CAGE code assignment", "expected_info_gain_pp": 1.8, "tier_change_probability": 0.03})
    if not inp.data_quality.has_lei:
        miv.append({"recommendation": "Obtain LEI registration", "expected_info_gain_pp": 2.1, "tier_change_probability": 0.05})
    if inp.exec_profile.known_execs == 0:
        miv.append({"recommendation": "Conduct executive screening", "expected_info_gain_pp": 5.5, "tier_change_probability": 0.20})
    if inp.ownership.pep_connection:
        miv.append({"recommendation": "Run enhanced PEP screening on board members", "expected_info_gain_pp": 5.2, "tier_change_probability": 0.22})

    cov = sum(confidences) / len(confidences) if confidences else 0
    rubric_weights = [0.30, 0.20, 0.20, 0.15, 0.15]
    rubric_score = min(100, round(sum(f["raw"] * rubric_weights[i] for i, f in enumerate(factors)) * 100 * prog_mult))

    # If hard stop triggered, ensure composite score is at least 85
    if stops and rubric_score < 85:
        rubric_score = max(rubric_score, 85 + len(stops) * 5)
        rubric_score = min(100, rubric_score)

    return ScoringResult(
        calibrated_probability=round(posterior_mean, 4),
        calibrated_tier=tier,
        interval_lower=round(lo, 4),
        interval_upper=round(hi, 4),
        interval_coverage=round(cov, 4),
        mean_confidence=round(cov, 4),
        contributions=contributions,
        hard_stop_decisions=stops,
        soft_flags=flags,
        findings=finds,
        marginal_information_values=miv,
        screening=screening,
        composite_score=rubric_score,
        rubric_confidence=round(cov, 4),
    )
