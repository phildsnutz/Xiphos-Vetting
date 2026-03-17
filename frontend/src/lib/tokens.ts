/** Xiphos design tokens - defense-grade design system */

export const T = {
  // Backgrounds
  bg: "#0a0e17",
  surface: "#111827",
  hover: "#1a2234",
  raised: "#162032",
  border: "#1e293b",
  borderLight: "#2a3a52",

  // Text
  text: "#e2e8f0",
  dim: "#94a3b8",
  muted: "#64748b",

  // Primary
  accent: "#3b82f6",
  accentHover: "#2563eb",

  // Semantic
  green: "#10b981",
  greenBg: "rgba(16,185,129,0.12)",
  amber: "#f59e0b",
  amberBg: "rgba(245,158,11,0.12)",
  orange: "#f97316",
  orangeBg: "rgba(249,115,22,0.12)",
  red: "#ef4444",
  redBg: "rgba(239,68,68,0.12)",
  dRed: "#dc2626",
  dRedBg: "rgba(220,38,38,0.15)",

  // Hard stop specific
  hardStopBg: "#7f1d1d",
  hardStopBorder: "#b91c1c",
} as const;

/** Type scale - minimum 11px, modular scale */
export const FS = {
  xs: 11,
  sm: 12,
  base: 13,
  md: 14,
  lg: 16,
  xl: 20,
  xxl: 28,
  huge: 36,
} as const;

/** Spacing scale */
export const SP = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;


// =============================================================================
// v5.0 TIER SYSTEM
// =============================================================================

/**
 * All v5.0 tier names from the FGAMLogit two-layer integration.
 * TIER_1 = critical/blocked, TIER_2 = elevated concern, TIER_3 = conditional, TIER_4 = approved/clear
 */
export type TierKey =
  | "TIER_1_DISQUALIFIED"
  | "TIER_1_CRITICAL_CONCERN"
  | "TIER_2_ELEVATED_REVIEW"
  | "TIER_2_CONDITIONAL_ACCEPTABLE"
  | "TIER_2_ELEVATED_CONCERN"
  | "TIER_2_ELEVATED"
  | "TIER_2_CAUTION"
  | "TIER_2_CAUTION_COMMERCIAL"
  | "TIER_3_CONDITIONAL"
  | "TIER_3_SAP_ACCEPTABLE"
  | "TIER_4_SAP_QUALIFIED"
  | "TIER_4_APPROVED"
  | "TIER_4_CLEAR";

export type RiskKey = "low" | "medium" | "elevated" | "high" | "critical";

/** Tier category: groups individual tiers into 4 visual bands */
export type TierBand = "critical" | "elevated" | "conditional" | "clear";

/** Which band does this tier belong to? */
export function tierBand(tier: TierKey): TierBand {
  if (tier.startsWith("TIER_1")) return "critical";
  if (tier.startsWith("TIER_2")) return "elevated";
  if (tier.startsWith("TIER_3")) return "conditional";
  return "clear";
}

/** Display metadata for each tier */
export const TIER_META: Record<TierKey, { label: string; shortLabel: string; color: string; bg: string; band: TierBand }> = {
  TIER_1_DISQUALIFIED:          { label: "DISQUALIFIED",              shortLabel: "DISQUALIFIED",  color: "#ffffff",  bg: T.hardStopBg,  band: "critical" },
  TIER_1_CRITICAL_CONCERN:      { label: "CRITICAL CONCERN",          shortLabel: "CRITICAL",      color: "#ffffff",  bg: T.hardStopBg,  band: "critical" },
  TIER_2_ELEVATED_REVIEW:       { label: "ELEVATED REVIEW",           shortLabel: "ELEVATED",      color: T.red,      bg: T.redBg,       band: "elevated" },
  TIER_2_CONDITIONAL_ACCEPTABLE:{ label: "CONDITIONAL ACCEPTABLE",    shortLabel: "CONDITIONAL",   color: T.orange,   bg: T.orangeBg,    band: "elevated" },
  TIER_2_ELEVATED_CONCERN:      { label: "ELEVATED CONCERN",          shortLabel: "ELEVATED",      color: T.red,      bg: T.redBg,       band: "elevated" },
  TIER_2_ELEVATED:              { label: "ELEVATED",                  shortLabel: "ELEVATED",      color: T.red,      bg: T.redBg,       band: "elevated" },
  TIER_2_CAUTION:               { label: "CAUTION",                   shortLabel: "CAUTION",       color: T.orange,   bg: T.orangeBg,    band: "elevated" },
  TIER_2_CAUTION_COMMERCIAL:    { label: "CAUTION",                   shortLabel: "CAUTION",       color: T.orange,   bg: T.orangeBg,    band: "elevated" },
  TIER_3_CONDITIONAL:           { label: "CONDITIONAL",               shortLabel: "CONDITIONAL",   color: T.amber,    bg: T.amberBg,     band: "conditional" },
  TIER_3_SAP_ACCEPTABLE:        { label: "SAP ACCEPTABLE",            shortLabel: "SAP OK",        color: T.amber,    bg: T.amberBg,     band: "conditional" },
  TIER_4_SAP_QUALIFIED:         { label: "SAP QUALIFIED",             shortLabel: "SAP QUALIFIED", color: T.green,    bg: T.greenBg,     band: "clear" },
  TIER_4_APPROVED:              { label: "APPROVED",                  shortLabel: "APPROVED",      color: T.green,    bg: T.greenBg,     band: "clear" },
  TIER_4_CLEAR:                 { label: "CLEAR",                     shortLabel: "CLEAR",         color: T.green,    bg: T.greenBg,     band: "clear" },
};

/** Band-level display metadata (for aggregated views like dashboards) */
export const BAND_META: Record<TierBand, { label: string; color: string; bg: string }> = {
  critical:    { label: "CRITICAL",     color: "#ffffff",  bg: T.hardStopBg },
  elevated:    { label: "ELEVATED",     color: T.red,      bg: T.redBg },
  conditional: { label: "CONDITIONAL",  color: T.amber,    bg: T.amberBg },
  clear:       { label: "CLEAR",        color: T.green,    bg: T.greenBg },
};

/** Map a tier to risk level (for the legacy risk-level display) */
export function tierToRisk(tier: TierKey): RiskKey {
  const b = tierBand(tier);
  if (b === "critical") return "critical";
  if (b === "elevated") return "elevated";
  if (b === "conditional") return "medium";
  return "low";
}

/** Get color for a tier */
export function tierColor(tier: TierKey): string {
  return TIER_META[tier]?.color ?? T.green;
}

/** Safely parse a tier string from the backend. Falls back to TIER_4_CLEAR. */
export function parseTier(raw: string | undefined | null): TierKey {
  if (!raw) return "TIER_4_CLEAR";
  if (raw in TIER_META) return raw as TierKey;
  return "TIER_4_CLEAR";
}

/** The 4 bands in display order (most severe first) for dashboard aggregation */
export const TIER_BANDS: TierBand[] = ["critical", "elevated", "conditional", "clear"];

/** All tiers belonging to a band */
export function tiersInBand(band: TierBand): TierKey[] {
  return (Object.keys(TIER_META) as TierKey[]).filter(t => TIER_META[t].band === band);
}

export const RISK_META: Record<RiskKey, { label: string; color: string; bg: string }> = {
  low:      { label: "LOW",      color: T.green,  bg: T.greenBg  },
  medium:   { label: "MEDIUM",   color: T.amber,  bg: T.amberBg  },
  elevated: { label: "ELEVATED", color: T.orange, bg: T.orangeBg },
  high:     { label: "HIGH",     color: T.red,    bg: T.redBg    },
  critical: { label: "CRITICAL", color: T.dRed,   bg: T.dRedBg   },
};

export function probColor(p: number): string {
  if (p < 0.15) return T.green;
  if (p < 0.3) return T.amber;
  if (p < 0.5) return T.orange;
  return T.red;
}

/** Verbal interpretation of posterior probability */
export function probLabel(p: number): string {
  if (p < 0.10) return "Very low risk";
  if (p < 0.20) return "Low risk";
  if (p < 0.35) return "Moderate risk";
  if (p < 0.50) return "Elevated risk";
  if (p < 0.70) return "High risk";
  return "Very high risk";
}
