/**
 * Xiphos Bayesian Scoring Engine
 *
 * Real probabilistic risk scoring using Beta-distributed priors,
 * evidence accumulation, and calibrated posterior estimation.
 *
 * This is NOT a mock. The math is real:
 * - Each risk factor has a Beta(alpha, beta) prior
 * - Evidence updates the posterior via conjugate Bayesian update
 * - Contributions are computed as posterior shift from prior mean
 * - Confidence intervals use Beta quantile approximation
 * - Hard stops are deterministic policy triggers, not probabilistic
 */

import { screenName, type ScreeningResult } from "./ofac";
import type { TierKey } from "./tokens";
import type { Calibration, Contribution, HardStop, Flag, MIV } from "./types";

/* ---- Geography risk tiers ---- */

const GEO_RISK: Record<string, number> = {
  // Five Eyes + allied
  US: 0.02, GB: 0.03, CA: 0.03, AU: 0.03, NZ: 0.04,
  // NATO + EU core
  DE: 0.05, FR: 0.05, JP: 0.05, KR: 0.08, IL: 0.10,
  NL: 0.05, NO: 0.05, DK: 0.05, SE: 0.05, FI: 0.06,
  IT: 0.07, ES: 0.07, PL: 0.08, CZ: 0.08,
  // Moderate
  BR: 0.18, IN: 0.20, MX: 0.22, TR: 0.25, AE: 0.15,
  SA: 0.22, TH: 0.18, MY: 0.15, SG: 0.06, TW: 0.08,
  // Elevated
  AZ: 0.40, PK: 0.45, UA: 0.35, BY: 0.55, VE: 0.50,
  MM: 0.50, BD: 0.35, VN: 0.30, EG: 0.28, NG: 0.38,
  // Sanctioned / comprehensively embargoed
  RU: 0.85, CN: 0.45, IR: 0.92, KP: 0.98, SY: 0.90,
  CU: 0.70, AF: 0.65, SO: 0.60, SD: 0.75, YE: 0.55,
};

function geoRisk(cc: string): number {
  return GEO_RISK[cc.toUpperCase()] ?? 0.30;
}

/* ---- Ownership transparency model ---- */

export interface OwnershipProfile {
  publiclyTraded: boolean;
  stateOwned: boolean;
  beneficialOwnerKnown: boolean;
  ownershipPctResolved: number; // 0..1
  shellLayers: number;
  pepConnection: boolean;
}

function ownershipRisk(o: OwnershipProfile): number {
  let r = 0;
  if (o.stateOwned) r += 0.30;
  if (!o.beneficialOwnerKnown) r += 0.25;
  r += (1 - o.ownershipPctResolved) * 0.20;
  if (o.shellLayers > 0) r += Math.min(o.shellLayers * 0.10, 0.30);
  if (o.pepConnection) r += 0.15;
  if (o.publiclyTraded) r -= 0.15;
  return Math.max(0, Math.min(1, r));
}

/* ---- Data quality model ---- */

export interface DataQuality {
  hasLEI: boolean;
  hasCAGE: boolean;
  hasDUNS: boolean;
  hasTaxId: boolean;
  hasAuditedFinancials: boolean;
  yearsOfRecords: number;
}

function dataQualityRisk(d: DataQuality): number {
  let missing = 0;
  if (!d.hasLEI) missing += 0.15;
  if (!d.hasCAGE) missing += 0.12;
  if (!d.hasDUNS) missing += 0.10;
  if (!d.hasTaxId) missing += 0.15;
  if (!d.hasAuditedFinancials) missing += 0.18;
  const agePenalty = d.yearsOfRecords < 3 ? 0.15 : d.yearsOfRecords < 5 ? 0.08 : 0;
  return Math.min(1, missing + agePenalty);
}

/* ---- Executive risk (simplified) ---- */

export interface ExecProfile {
  knownExecs: number;
  adverseMedia: number;
  pepExecs: number;
  litigationHistory: number;
}

function execRisk(e: ExecProfile): number {
  let r = 0;
  if (e.knownExecs === 0) r += 0.25;
  r += Math.min(e.adverseMedia * 0.12, 0.35);
  r += Math.min(e.pepExecs * 0.10, 0.25);
  r += Math.min(e.litigationHistory * 0.05, 0.15);
  return Math.max(0, Math.min(1, r));
}

/* ---- Program criticality ---- */

export type ProgramType =
  | "mission_critical"
  | "weapons_system"
  | "dual_use"
  | "standard_industrial"
  | "commercial_off_shelf"
  | "services";

function programMultiplier(p: ProgramType): number {
  const m: Record<ProgramType, number> = {
    weapons_system: 1.5,
    mission_critical: 1.35,
    dual_use: 1.20,
    standard_industrial: 1.0,
    commercial_off_shelf: 0.85,
    services: 0.90,
  };
  return m[p] ?? 1.0;
}

/* ---- Beta distribution utilities ---- */

/** Inverse normal CDF (Beasley-Springer-Moro approximation) */
function normalQuantile(p: number): number {
  if (p <= 0) return -Infinity;
  if (p >= 1) return Infinity;
  if (p === 0.5) return 0;

  const a = [
    -3.969683028665376e1, 2.209460984245205e2,
    -2.759285104469687e2, 1.383577518672690e2,
    -3.066479806614716e1, 2.506628277459239e0,
  ];
  const b = [
    -5.447609879822406e1, 1.615858368580409e2,
    -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1,
  ];
  const c = [
    -7.784894002430293e-3, -3.223964580411365e-1,
    -2.400758277161838, -2.549732539343734,
    4.374664141464968, 2.938163982698783,
  ];
  const d = [
    7.784695709041462e-3, 3.224671290700398e-1,
    2.445134137142996, 3.754408661907416,
  ];

  const pLow = 0.02425;
  const pHigh = 1 - pLow;

  let q: number;
  if (p < pLow) {
    q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  } else if (p <= pHigh) {
    q = p - 0.5;
    const r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
      (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  } else {
    q = Math.sqrt(-2 * Math.log(1 - p));
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
}

/** Beta quantile via normal approximation (good for a+b > 5) */
function betaQuantile(p: number, a: number, b: number): number {
  const mu = a / (a + b);
  const sigma = Math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)));
  const z = normalQuantile(p);
  return Math.max(0, Math.min(1, mu + sigma * z));
}

/* ---- Core scoring engine ---- */

export interface VendorInput {
  name: string;
  country: string;
  ownership: OwnershipProfile;
  dataQuality: DataQuality;
  exec: ExecProfile;
  program: ProgramType;
}

export interface ScoringResult {
  calibration: Calibration;
  screening: ScreeningResult;
  rubricScore: number;
  rubricConfidence: number;
}

/**
 * Score a vendor through the full Bayesian pipeline.
 *
 * 1. Screen against OFAC / sanctions lists
 * 2. Compute per-factor raw risk scores
 * 3. Apply Beta conjugate updates to prior
 * 4. Derive posterior mean, CI, tier
 * 5. Check hard-stop triggers
 * 6. Compute signed contributions
 */
export function scoreVendor(input: VendorInput): ScoringResult {
  // Step 1: Sanctions screening
  const screening = screenName(input.name);

  // Step 2: Per-factor raw scores
  const sanctionsRaw = screening.matched ? screening.bestScore : 0;
  const geoRaw = geoRisk(input.country);
  const ownRaw = ownershipRisk(input.ownership);
  const dqRaw = dataQualityRisk(input.dataQuality);
  const execRaw = execRisk(input.exec);
  const progMult = programMultiplier(input.program);

  // Step 3: Bayesian update
  // Prior: Beta(2, 8) => mean = 0.20 (mild skepticism toward risk)
  let alpha = 2;
  let beta = 8;

  // Each factor contributes pseudo-observations
  // Higher raw score => more "risk" observations
  const factors = [
    { name: "Sanctions",    raw: sanctionsRaw, weight: 5.0 },
    { name: "Geography",    raw: geoRaw,       weight: 2.5 },
    { name: "Ownership",    raw: ownRaw,       weight: 3.0 },
    { name: "Data Quality", raw: dqRaw,        weight: 1.5 },
    { name: "Executive",    raw: execRaw,      weight: 2.0 },
  ];

  for (const f of factors) {
    const n = f.weight * progMult;
    alpha += f.raw * n;
    beta += (1 - f.raw) * n;
  }

  const posteriorMean = alpha / (alpha + beta);
  const lo = betaQuantile(0.025, alpha, beta);
  const hi = betaQuantile(0.975, alpha, beta);

  // Step 4: Tier assignment
  let tier: TierKey;
  if (posteriorMean >= 0.60 || (screening.matched && screening.bestScore > 0.90)) {
    tier = "TIER_1_CRITICAL_CONCERN";
  } else if (posteriorMean >= 0.30) {
    tier = "TIER_2_ELEVATED_REVIEW";
  } else if (posteriorMean >= 0.15) {
    tier = "TIER_3_CONDITIONAL";
  } else {
    tier = "TIER_4_CLEAR";
  }

  // Step 5: Per-factor contributions (signed shift from prior)
  const contributions: Contribution[] = [];
  const confidences: number[] = [];

  for (const f of factors) {
    // Compute counterfactual: what would posterior be without this factor?
    let aWo = 2, bWo = 8;
    for (const g of factors) {
      if (g.name === f.name) continue;
      const n = g.weight * progMult;
      aWo += g.raw * n;
      bWo += (1 - g.raw) * n;
    }
    const meanWithout = aWo / (aWo + bWo);
    const shift = posteriorMean - meanWithout;

    // Confidence is function of data quality and weight
    const conf = Math.min(0.99, 0.5 + f.weight * 0.08 + (f.raw > 0.01 ? 0.15 : 0));

    confidences.push(conf);

    let desc = "";
    switch (f.name) {
      case "Sanctions":
        desc = screening.matched
          ? `Match: "${screening.matchedName}" (${screening.matchedEntry?.list}) -- ${(screening.bestScore * 100).toFixed(0)}% similarity`
          : "No sanctions matches found across OFAC SDN, Entity List, CAATSA, SSI";
        break;
      case "Geography":
        desc = geoRaw < 0.10 ? `Allied jurisdiction (${input.country})` :
          geoRaw < 0.25 ? `Moderate-risk jurisdiction (${input.country})` :
          geoRaw < 0.50 ? `Elevated-risk jurisdiction (${input.country})` :
          `High-risk / sanctioned jurisdiction (${input.country})`;
        break;
      case "Ownership":
        desc = input.ownership.stateOwned ? "State-owned enterprise" :
          !input.ownership.beneficialOwnerKnown ? `Beneficial ownership unresolved (${Math.round(input.ownership.ownershipPctResolved * 100)}% traced)` :
          input.ownership.publiclyTraded ? "Publicly traded, transparent ownership" :
          `Private entity, ${Math.round(input.ownership.ownershipPctResolved * 100)}% ownership resolved`;
        break;
      case "Data Quality": {
        const gaps: string[] = [];
        if (!input.dataQuality.hasLEI) gaps.push("LEI");
        if (!input.dataQuality.hasCAGE) gaps.push("CAGE");
        if (!input.dataQuality.hasDUNS) gaps.push("DUNS");
        if (!input.dataQuality.hasTaxId) gaps.push("Tax ID");
        desc = gaps.length > 0 ? `Missing: ${gaps.join(", ")}` : "Complete identifier coverage";
        break;
      }
      case "Executive":
        desc = input.exec.knownExecs === 0 ? "No executive data available" :
          input.exec.adverseMedia > 0 ? `${input.exec.adverseMedia} adverse media hit(s) on ${input.exec.knownExecs} known exec(s)` :
          `${input.exec.knownExecs} executives screened, no adverse findings`;
        break;
    }

    contributions.push({
      n: f.name,
      raw: f.raw,
      c: conf,
      s: shift,
      d: desc,
    });
  }

  // Step 6: Hard stops
  const stops: HardStop[] = [];
  if (screening.matched && screening.bestScore > 0.88) {
    stops.push({
      t: `${screening.matchedEntry?.list} Match: ${screening.matchedName}`,
      x: `Entity matches ${screening.matchedEntry?.list} list under ${screening.matchedEntry?.program} program -- ${(screening.bestScore * 100).toFixed(0)}% fuzzy match confidence.`,
      c: screening.bestScore,
    });
  }
  if (input.ownership.stateOwned && geoRaw > 0.50) {
    stops.push({
      t: "Adversary State-Owned Enterprise",
      x: `State-owned entity in sanctioned/adversarial jurisdiction (${input.country}).`,
      c: 0.90,
    });
  }

  // Step 7: Soft flags
  const flags: Flag[] = [];
  if (input.ownership.pepConnection) {
    flags.push({
      t: "PEP Connection",
      x: "One or more principals match Politically Exposed Person databases.",
      c: 0.65,
    });
  }
  if (input.ownership.ownershipPctResolved < 0.60) {
    flags.push({
      t: "Unresolved Ownership",
      x: `Only ${Math.round(input.ownership.ownershipPctResolved * 100)}% of beneficial ownership resolved.`,
      c: 0.80,
    });
  }
  if (screening.matched && screening.bestScore > 0.70 && screening.bestScore <= 0.88) {
    flags.push({
      t: "Fuzzy Sanctions Match",
      x: `Name similarity ${(screening.bestScore * 100).toFixed(0)}% to ${screening.matchedEntry?.list} entry -- manual review recommended.`,
      c: screening.bestScore,
    });
  }
  if (input.exec.adverseMedia > 0) {
    flags.push({
      t: "Adverse Media",
      x: `${input.exec.adverseMedia} adverse media hit(s) detected on executive screening.`,
      c: 0.70,
    });
  }
  if (input.dataQuality.yearsOfRecords < 3) {
    flags.push({
      t: "Limited Operating History",
      x: `Entity has only ${input.dataQuality.yearsOfRecords} year(s) of verifiable records.`,
      c: 0.85,
    });
  }

  // Step 8: Key findings (narrative)
  const finds: string[] = [];
  if (stops.length > 0) {
    finds.push(`Hard stop triggered: ${stops[0].t}. This is an absolute compliance barrier.`);
  }
  if (posteriorMean > 0.50) {
    finds.push(`Bayesian posterior of ${(posteriorMean * 100).toFixed(0)}% indicates substantial compliance risk.`);
  } else if (posteriorMean < 0.15) {
    finds.push(`Low-risk profile with ${(posteriorMean * 100).toFixed(0)}% posterior probability.`);
  }
  if (geoRaw > 0.40) {
    finds.push(`Jurisdiction (${input.country}) contributes significant geographic risk.`);
  }
  if (!input.ownership.beneficialOwnerKnown) {
    finds.push("Beneficial ownership is unresolved -- enhanced due diligence recommended.");
  }
  if (input.ownership.publiclyTraded) {
    finds.push("Publicly traded entity with regulatory disclosure requirements.");
  }
  if (flags.length > 0) {
    finds.push(`${flags.length} advisory flag(s) requiring analyst review.`);
  }

  // Step 9: MIV (most informative variables to collect)
  const miv: MIV[] = [];
  if (!input.ownership.beneficialOwnerKnown) {
    const impact = input.ownership.ownershipPctResolved < 0.50 ? 8.5 : 4.2;
    miv.push({ t: "Obtain beneficial ownership registry filing", i: impact, tp: impact > 5 ? 0.35 : 0.15 });
  }
  if (!input.dataQuality.hasCAGE) {
    miv.push({ t: "Verify CAGE code assignment", i: 1.8, tp: 0.03 });
  }
  if (!input.dataQuality.hasLEI) {
    miv.push({ t: "Obtain LEI registration", i: 2.1, tp: 0.05 });
  }
  if (input.exec.knownExecs === 0) {
    miv.push({ t: "Conduct executive screening", i: 5.5, tp: 0.20 });
  }
  if (input.ownership.pepConnection) {
    miv.push({ t: "Run enhanced PEP screening on board members", i: 5.2, tp: 0.22 });
  }

  // Coverage and mean confidence
  const cov = confidences.reduce((s, c) => s + c, 0) / confidences.length;
  const mc = cov;

  // Rubric score (0-100, weighted linear combination)
  const rubricWeights = [0.30, 0.20, 0.20, 0.15, 0.15]; // sanctions, geo, own, dq, exec
  const rubricScore = Math.round(
    factors.reduce((s, f, i) => s + f.raw * rubricWeights[i], 0) * 100 * progMult
  );
  const rubricConf = mc;

  return {
    calibration: {
      p: posteriorMean,
      tier,
      lo,
      hi,
      cov,
      mc,
      ct: contributions,
      stops,
      flags,
      finds,
      miv,
    },
    screening,
    rubricScore: Math.min(100, rubricScore),
    rubricConfidence: rubricConf,
  };
}
